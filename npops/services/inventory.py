"""NPOPS Inventory service — movements, allocation, reorder alerts.

Every stock change goes through record_move() so the ledger and the
on-hand quantities can never drift apart (single point of mutation).
"""
from __future__ import annotations

from ..models import InventoryItem, InventoryMove
from ..auth import utcnow_iso, audit


def record_move(sku: str, location: str, delta: float, reason: str,
                actor: str, ref_type: str = "", ref_id: str = "") -> InventoryMove:
    """Apply a signed quantity change and log it atomically."""
    item = InventoryItem.all("sku=? AND location=?", (sku, location))
    if not item:
        if delta < 0:
            raise ValueError(f"negative stock for {sku}@{location}")
        item = InventoryItem(sku=sku, location=location, on_hand=0.0,
                             allocated=0.0, reorder_point=0,
                             reorder_qty=0, unit="unit",
                             updated_at=utcnow_iso())
        item.insert()
    else:
        item = item[0]
    new_on_hand = item.on_hand + delta
    if new_on_hand < -1e-9:
        raise ValueError(f"insufficient stock {sku}@{location}: "
                         f"{item.on_hand} + {delta}")
    item.on_hand = new_on_hand
    item.updated_at = utcnow_iso()
    item.update()
    mv = InventoryMove(sku=sku, location=location, delta=delta,
                       reason=reason, ref_type=ref_type, ref_id=str(ref_id),
                       actor=actor, created_at=utcnow_iso())
    mv.insert()
    return mv


def transfer(sku: str, src: str, dst: str, qty: float, actor: str,
             ref_type: str = "", ref_id: str = ""):
    record_move(sku, src, -qty, "transfer_out", actor, ref_type, ref_id)
    record_move(sku, dst, qty, "transfer_in", actor, ref_type, ref_id)


def receive_po_materials(po_number: str, actor: str) -> dict:
    """Receipt of a production order's materials into WH-MAIN."""
    from ..models import ProductionOrder, BomLine, GiftCatalog
    po = ProductionOrder.all("po_number=?", (po_number,))
    if not po:
        raise ValueError(f"unknown PO {po_number}")
    po = po[0]
    if po.status not in ("draft", "released"):
        raise ValueError(f"PO {po_number} not receivable (status={po.status})")
    lines = BomLine.all("gift_sku=?", (po.gift_sku,))
    received = []
    for line in lines:
        qty = po.qty * line.qty_per_unit * (1 + line.scrap_pct / 100.0)
        record_move(line.component_sku, "WH-MAIN", qty, "receipt",
                    actor, "po", po_number)
        received.append({"sku": line.component_sku, "qty": round(qty, 2)})
    if po.status == "draft":
        po.status = "released"
        po.update()
    audit(actor, "po_receive", "production_order", po_number,
          f"{len(received)} lines")
    return {"po_number": po_number, "received": received,
            "status": po.status}


def complete_po(po_number: str, actor: str, qty_done: int | None = None) -> dict:
    """Consume components, produce finished gifts, load capacity."""
    from ..models import ProductionOrder, BomLine
    po = ProductionOrder.all("po_number=?", (po_number,))
    if not po:
        raise ValueError(f"unknown PO {po_number}")
    po = po[0]
    if po.status not in ("released", "in_progress"):
        raise ValueError(f"PO {po_number} not completable (status={po.status})")
    qty = qty_done if qty_done is not None else po.qty
    if qty <= 0 or po.completed_qty + qty > po.qty:
        raise ValueError("bad completion quantity")
    lines = BomLine.all("gift_sku=?", (po.gift_sku,))
    for line in lines:
        consume = qty * line.qty_per_unit * (1 + line.scrap_pct / 100.0)
        record_move(line.component_sku, "WH-MAIN", -consume, "consume",
                    actor, "po", po_number)
    record_move(po.gift_sku, "WH-GIFTS", qty, "receipt", actor, "po", po_number)
    po.completed_qty += qty
    po.status = "completed" if po.completed_qty >= po.qty else "in_progress"
    po.update()
    audit(actor, "po_complete", "production_order", po_number,
          f"{qty} units -> WH-GIFTS")
    return {"po_number": po_number, "completed_qty": po.completed_qty,
            "status": po.status}


def reorder_alerts() -> list[dict]:
    """Items at or below reorder point."""
    alerts = []
    for item in InventoryItem.all():
        if item.reorder_point > 0 and item.on_hand <= item.reorder_point:
            alerts.append({
                "sku": item.sku, "location": item.location,
                "on_hand": item.on_hand, "reorder_point": item.reorder_point,
                "suggested_qty": item.reorder_qty, "unit": item.unit,
            })
    return alerts


def load_to_sleigh(year: int, actor: str) -> dict:
    """Allocate finished gifts to sleigh loading (WH-GIFTS -> SLEIGH)."""
    from ..models import GiftCatalog, DeliveryAssignment
    assignments = DeliveryAssignment.all("year=? AND status='planned'", (year,))
    if not assignments:
        return {"loaded": 0, "skus": {}}
    gifts = {g.sku: g for g in GiftCatalog.all()}
    by_sku: dict[str, int] = {}
    for a in assignments:
        by_sku[a.gift_sku] = by_sku.get(a.gift_sku, 0) + 1
    loaded = {}
    for sku, qty in by_sku.items():
        transfer(sku, "WH-GIFTS", "SLEIGH", qty, actor, "sleigh", str(year))
        loaded[sku] = qty
    for a in assignments:
        a.status = "loaded"
        a.update()
    audit(actor, "sleigh_load", "sleigh", str(year), f"{sum(loaded.values())} gifts")
    return {"loaded": sum(loaded.values()), "skus": loaded}
