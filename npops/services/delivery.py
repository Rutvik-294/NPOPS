"""NPOPS Delivery service — plan persistence, tracking, KPIs.

Bridges the optimizer (pure computation) to the database (state), and
provides the live-tracking simulation clock for the night of operations.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..models import (City, Child, GiftCatalog, DeliveryAssignment, Route,
                      WishList, KpiSnapshot, ProductionOrder, InventoryItem)
from ..optimizer.vrp import plan_delivery_year, Solution
from ..auth import utcnow_iso, audit


def compute_and_persist_plan(year: int, actor: str, iterations: int = 4000) -> dict:
    """Full planning run: demand -> VRP -> Route + DeliveryAssignment rows."""
    cities = City.all()
    gifts = {g.sku: g for g in GiftCatalog.all()}
    children = {c.id: c for c in Child.all("status='nice'")}

    demand: dict[int, dict[str, int]] = {}
    for wl in WishList.all("rank=1"):
        if wl.child_id in children:
            demand.setdefault(children[wl.child_id].city_id, {}) \
                  [wl.gift_sku] = demand.get(children[wl.child_id].city_id, {}) \
                                        .get(wl.gift_sku, 0) + 1

    demand_by_city: dict[int, tuple[float, float]] = {}
    manifest: list[tuple[int, str]] = []   # (child_id, sku)
    for city_id, skus in demand.items():
        kg = sum(gifts[s].weight_kg * q for s, q in skus.items())
        dm3 = sum(gifts[s].volume_dm3 * q for s, q in skus.items())
        demand_by_city[city_id] = (kg, dm3)
        for sku, q in skus.items():
            for _ in range(q):
                manifest.append((None, sku))  # child resolved below
    # child->gift mapping
    child_gift: list[tuple[int, str]] = []
    for wl in WishList.all("rank=1"):
        if wl.child_id in children:
            child_gift.append((wl.child_id, wl.gift_sku))

    sol = plan_delivery_year(cities, demand_by_city, max_sorties=6,
                             iterations=iterations)

    # Wipe prior plan for this year
    for a in DeliveryAssignment.all("year=?", (year,)):
        a.delete()
    for r in Route.all("year=?", (year,)):
        r.delete()

    seq = 0
    total_kg = 0.0
    route_rows = []
    city_child_gift: dict[int, list[tuple[int, str]]] = {}
    for cid, sku in child_gift:
        city_child_gift.setdefault(children[cid].city_id, []).append((cid, sku))
    for li, leg in enumerate([l for l in sol.legs if l.stops]):
        route_id = f"R-{year}-{chr(65 + li)}1"
        city_ids = []
        for s in leg.stops:
            city_ids.append(s.city.id)
            total_kg += s.demand_kg
        route_rows.append({
            "route_id": route_id, "year": year,
            "region_id": leg.stops[0].city.region_id,
            "name": f"Sortie {li + 1}",
            "stop_count": len(leg.stops),
            "total_km": 0.0,  # filled after simulation export
            "load_kg": round(leg.load_kg(), 1),
            "departure_utc": 0.0,
            "completion_utc": round(max(s.depart for s in leg.stops), 2),
            "feasible": 1 if not sol.violations else 0,
            "infeasibility_reasons": json.dumps(sol.violations),
            "city_ids": json.dumps(city_ids),
            "created_at": utcnow_iso(),
        })
        for si, s in enumerate(leg.stops):
            for cid, sku in city_child_gift.get(s.city.id, []):
                DeliveryAssignment(year=year, child_id=cid, gift_sku=sku,
                                   route_id=route_id, stop_seq=si + 1,
                                   status="planned", delivered_at=None).insert()
                seq += 1

    # recompute leg distances properly
    from ..optimizer.vrp import DistanceMatrix
    served = [c for c in cities if c.id in demand_by_city]
    matrix = DistanceMatrix(served)
    total_km = 0.0
    legs_out = []
    for li, leg in enumerate([l for l in sol.legs if l.stops]):
        km = matrix.depot(leg.stops[0].mx)
        for a, b in zip(leg.stops, leg.stops[1:]):
            km += matrix.d(a.mx, b.mx)
        km += matrix.depot(leg.stops[-1].mx)
        total_km += km
        route_rows[li]["total_km"] = round(km, 1)
        route_rows[li]["departure_utc"] = 0.0 if li == 0 else \
            round(max(s.depart for s in [l for l in sol.legs if l.stops][li - 1].stops), 2)
        r = Route(**route_rows[li])
        r.insert()
        legs_out.append(r)

    audit(actor, "plan_compute", "routes", str(year),
          f"{len(legs_out)} sorties, {total_km:.0f} km, "
          f"feasible={not sol.violations}")
    return {"year": year, "routes": [r.to_dict() for r in legs_out],
            "assignments": seq, "total_km": round(total_km, 1),
            "total_kg": round(total_kg, 1),
            "violations": sol.violations,
            "makespan_h": round(sol.makespan, 2)}


def existing_plan(year: int) -> dict | None:
    routes = Route.all("year=?", (year,))
    if not routes:
        return None
    assignments = DeliveryAssignment.count("year=?", (year,))
    return {"year": year, "routes": [r.to_dict() for r in routes],
            "assignments": assignments,
            "total_km": round(sum(r.total_km for r in routes), 1),
            "total_kg": round(sum(r.load_kg for r in routes), 1),
            "feasible": all(r.feasible for r in routes)}


def tracking_state(year: int, elapsed_hours: float) -> dict:
    """Where is the sleigh now? Interpolates along each route timeline."""
    routes = Route.all("year=?", (year,))
    if not routes:
        return {"active": False}
    cities = {c.id: c for c in City.all()}
    stops_by_route: dict[str, list[DeliveryAssignment]] = {}
    assignments = DeliveryAssignment.all("year=?", (year,))
    for a in assignments:
        stops_by_route.setdefault(a.route_id, []).append(a)

    result = []
    delivered = 0
    for r in routes:
        city_ids = json.loads(r.city_ids or "[]")
        # position along stops
        done, current, pending = 0, None, 0
        for i, cid in enumerate(city_ids):
            count_here = len(stops_by_route.get(r.id, []))
            pass
        # simple model: route runs between its creation timeline values
        dur = max(r.completion_utc - r.departure_utc, 0.1)
        prog = (elapsed_hours - r.departure_utc) / dur
        if prog <= 0:
            status = "scheduled"
        elif prog >= 1:
            status = "complete"
        else:
            status = "in_transit"
        done = int(min(max(prog, 0), 1) * r.stop_count)
        delivered += done
        if status == "in_transit" and 0 < prog < 1 and city_ids:
            idx = min(int(prog * len(city_ids)), len(city_ids) - 1)
            cur = cities.get(city_ids[idx])
            current = {"city": cur.name, "country": cur.country,
                       "lat": cur.lat, "lon": cur.lon} if cur else None
        result.append({"route_id": r.id, "name": r.name, "status": status,
                       "progress": round(min(max(prog, 0), 1), 3),
                       "stops_done": done, "stops_total": r.stop_count,
                       "current": current})

    total = DeliveryAssignment.count("year=?", (year,))
    return {"active": True, "elapsed_hours": round(elapsed_hours, 2),
            "routes": result, "delivered": delivered, "total": total,
            "pct": round(100 * delivered / total, 1) if total else 0}


def capture_kpis(year: int) -> dict:
    """Compute and snapshot the operational KPI set."""
    kpis = {}
    kpis["nice_children"] = Child.count if False else _count_children("nice")
    kpis["naughty_children"] = _count_children("naughty")
    kpis["gifts_planned"] = DeliveryAssignment.count("year=?", (year,))
    routes = Route.all("year=?", (year,))
    kpis["total_km"] = round(sum(r.total_km for r in routes), 1)
    kpis["sorties"] = len(routes)
    kpis["plan_feasible"] = 1 if routes and all(r.feasible for r in routes) else 0
    kpis["pos_open"] = ProductionOrder.count(
        "status IN ('draft','released','in_progress')")
    kpis["pos_complete"] = ProductionOrder.count("status='completed'")
    kpis["materials_below_rop"] = len(_below_rop())
    now = utcnow_iso()
    for k, v in kpis.items():
        KpiSnapshot(captured_at=now, year=year, metric=k,
                    value=float(v)).insert()
    return kpis


def _count_children(status: str) -> int:
    return Child.count("status=?", (status,)) if False else \
        _child_count(status)


def _child_count(status: str) -> int:
    from ..models import Child as C
    return C.count("status=?", (status,))


def _below_rop() -> list:
    return [i for i in InventoryItem.all()
            if i.reorder_point > 0 and i.on_hand <= i.reorder_point]


def kpi_history(metric: str, limit: int = 50) -> list[dict]:
    from ..orm import get_db
    return get_db().query(
        "SELECT captured_at, value FROM kpi_snapshots WHERE metric=? "
        "ORDER BY id DESC LIMIT ?", (metric, limit))[::-1]
