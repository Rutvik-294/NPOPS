"""NPOPS Production Planning — capacity check + MRP run.

MRP explodes the master production schedule (gift demand) through BOMs,
nets against on-hand inventory, and proposes purchase orders with lead
times. Capacity planning levels loads against work center calendars.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from ..models import (GiftCatalog, BomLine, WorkCenter, InventoryItem,
                      ProductionOrder, WishList, Child, DeliveryAssignment)


def demand_for_year(year: int) -> dict[str, int]:
    """Independent demand: rank-1 wishlist items for nice children."""
    children = {c.id: c for c in Child.all("status='nice'")}
    demand: dict[str, int] = defaultdict(int)
    for wl in WishList.all("rank=1"):
        if wl.child_id in children:
            demand[wl.gift_sku] += 1
    return dict(demand)


def explode_bom(sku: str, qty: int, bom_index: dict[str, list[BomLine]],
                scrap_factor: float = 1.02) -> dict[str, float]:
    """Gross requirements of components for qty of sku (single level)."""
    req: dict[str, float] = {}
    for line in bom_index.get(sku, []):
        req[line.component_sku] = req.get(line.component_sku, 0.0) + \
            qty * line.qty_per_unit * (scrap_factor * (1 + line.scrap_pct / 100.0))
    return req


def run_mrp(year: int) -> dict:
    """Net requirements across all gifts for the given year."""
    demand = demand_for_year(year)
    gifts = {g.sku: g for g in GiftCatalog.all()}
    inv = {i.sku: i for i in InventoryItem.all("location='WH-MAIN'")}
    bom_index: dict[str, list[BomLine]] = defaultdict(list)
    for line in BomLine.all():
        bom_index[line.gift_sku].append(line)

    # Gift-level gross = demand net of finished goods on hand
    gift_inv = {i.sku: i for i in InventoryItem.all("location='WH-GIFTS'")}
    gift_net: dict[str, int] = {}
    for sku, d in demand.items():
        on_hand = gift_inv[sku].on_hand if sku in gift_inv else 0
        gift_net[sku] = max(0, math.ceil(d - on_hand))

    # Component gross requirements
    comp_gross: dict[str, float] = defaultdict(float)
    for sku, qty in gift_net.items():
        for comp, q in explode_bom(sku, qty, bom_index).items():
            comp_gross[comp] += q

    # Net vs on-hand, propose orders
    proposals = []
    for comp, gross in sorted(comp_gross.items()):
        on_hand = inv[comp].on_hand if comp in inv else 0.0
        net = max(0.0, gross - on_hand)
        if net <= 0:
            continue
        rop_qty = inv[comp].reorder_qty if comp in inv else net
        order_qty = max(net, 0) if net > rop_qty else max(net, rop_qty)
        proposals.append({
            "sku": comp,
            "gross_required": round(gross, 2),
            "on_hand": round(on_hand, 2),
            "net_requirement": round(net, 2),
            "proposed_order": round(order_qty, 2),
            "need_by": f"{year}-12-15",   # staging freeze date
        })

    gift_plan = []
    for sku, qty in sorted(gift_net.items(), key=lambda kv: -kv[1]):
        g = gifts[sku]
        gift_plan.append({
            "sku": sku, "name": g.name, "demand": demand[sku],
            "net_build": qty,
            "labor_minutes": qty * g.unit_labor_minutes,
            "weight_kg": qty * g.weight_kg,
            "complexity": g.complexity,
        })

    return {"year": year, "total_gifts_needed": sum(demand.values()),
            "total_to_build": sum(gift_net.values()),
            "gift_plan": gift_plan, "material_proposals": proposals}


def capacity_check(year: int) -> dict:
    """Level the build plan across work centers; flag overloads."""
    plan = run_mrp(year)
    wcs = WorkCenter.all("active=1")
    gifts = {g.sku: g for g in GiftCatalog.all()}
    load: dict[int, float] = defaultdict(float)
    assignment: dict[str, int] = {}
    for row in plan["gift_plan"]:
        g = gifts[row["sku"]]
        candidates = [wc for wc in wcs
                      if wc.min_complexity <= g.complexity <= wc.max_complexity]
        if not candidates:
            assignment[row["sku"]] = -1
            continue
        # least-loaded feasible center
        wc = min(candidates, key=lambda w: load[w.id])
        load[wc.id] += row["labor_minutes"]
        assignment[row["sku"]] = wc.id

    lines = []
    for wc in wcs:
        minutes = load.get(wc.id, 0.0)
        cap = wc.capacity_minutes_per_day * 5  # one build week, 5 days
        lines.append({
            "work_center": wc.code, "name": wc.name,
            "load_minutes": round(minutes), "capacity_minutes": cap,
            "utilization_pct": round(100 * minutes / cap, 1) if cap else 0,
            "status": "overloaded" if minutes > cap else "ok",
        })
    return {"year": year, "work_centers": lines,
            "unassignable": [sku for sku, wc in assignment.items() if wc == -1]}


def release_plan(year: int, actor: str) -> dict:
    """Turn MRP proposals into draft production orders."""
    plan = run_mrp(year)
    wcs = WorkCenter.all("active=1")
    gifts = {g.sku: g for g in GiftCatalog.all()}
    created = 0
    seq = ProductionOrder.count() + 1
    due = f"{year}-12-20"
    for row in plan["gift_plan"]:
        g = gifts[row["sku"]]
        cands = [wc for wc in wcs
                 if wc.min_complexity <= g.complexity <= wc.max_complexity]
        wc_id = min(cands, key=lambda w: w.id).id if cands else None
        sku = row["sku"]
        # refresh: replace any prior draft, keep released+ alone
        for po in ProductionOrder.all("gift_sku=? AND status='draft'", (sku,)):
            po.delete()
        existing = ProductionOrder.all(
            "gift_sku=? AND status IN ('released','in_progress')", (sku,))
        in_flight = sum(po.qty for po in existing)
        need = row["net_build"] - in_flight
        if need <= 0:
            continue
        ProductionOrder(po_number=f"PO-{year}-{seq:04d}", gift_sku=sku,
                        qty=need, status="draft", priority=5,
                        work_center_id=wc_id, due_date=due,
                        created_at=_now(), completed_qty=0).insert()
        seq += 1
        created += 1
    from ..auth import audit
    audit(actor, "mrp_release", "production_plan", str(year),
          f"{created} draft orders")
    return {"created": created, "year": year}


def _now() -> str:
    from ..auth import utcnow_iso
    return utcnow_iso()
