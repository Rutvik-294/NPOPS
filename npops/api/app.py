"""NPOPS REST API — assembles the App, wires routes + middleware."""
from __future__ import annotations

import os

from ..orm import Database, set_db
from ..webframe import App, json_response, HTTPError
from ..auth import (attach_session, check_csrf, login, logout, require_perm,
                    apply_session_cookie, ROLE_PERMISSIONS)
from .. import seed as seed_mod
import datetime as _dt
from ..models import (User, Session, Region, City, GiftCatalog, BomLine,
                      WorkCenter, ProductionOrder, InventoryItem,
                      InventoryMove, Child, WishList, DeliveryAssignment,
                      Route, AuditLog, KpiSnapshot)
from ..services import production, inventory as inv_svc, naughty_nice, delivery


def create_app(db_path: str, secret_path: str | None = None) -> App:
    db = Database(db_path)
    set_db(db)
    app = App()
    here = os.path.dirname(os.path.abspath(__file__))

    # ---------- auth ----------
    @app.post("/api/auth/login")
    def api_login(req):
        body = req.json
        user, session = login(body.get("username", ""),
                              body.get("password", ""),
                              req.environ.get("REMOTE_ADDR", ""))
        resp = json_response({"user": {"username": user.username,
                                       "full_name": user.full_name,
                                       "role": user.role}})
        apply_session_cookie(resp, session)
        return resp

    @app.post("/api/auth/logout")
    def api_logout(req):
        if req.ctx.get("session"):
            logout(req.ctx["session"].id)
        resp = json_response({"ok": True})
        resp.set_cookie("npops_session", "", max_age=0)
        return resp

    @app.get("/api/auth/me")
    def api_me(req):
        u = req.ctx.get("user")
        if not u:
            raise HTTPError(401)
        s = req.ctx["session"]
        return {"username": u.username, "full_name": u.full_name,
                "role": u.role, "csrf_token": s.csrf_token,
                "permissions": sorted(ROLE_PERMISSIONS.get(u.role, []))}

    # ---------- master data ----------
    @app.get("/api/regions")
    @require_perm("plan:read")
    def regions(req):
        return [r.to_dict() for r in Region.all()]

    @app.get("/api/cities")
    @require_perm("plan:read")
    def cities(req):
        q = req.query.get("q", "").lower()
        region = req.query.get("region")
        where, params = "1=1", []
        if q:
            where += " AND (LOWER(name) LIKE ? OR LOWER(country) LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]
        if region:
            where += " AND region_id=?"
            params.append(region)
        return [c.to_dict() for c in City.all(where, params, order="name")]

    @app.get("/api/gifts")
    @require_perm("prod:read")
    def gifts(req):
        return [g.to_dict() for g in GiftCatalog.all(order="sku")]

    @app.get("/api/work_centers")
    @require_perm("prod:read")
    def work_centers(req):
        return [w.to_dict() for w in WorkCenter.all()]

    # ---------- planning ----------
    @app.get("/api/plan")
    @require_perm("plan:read")
    def get_plan(req):
        year = int(req.query.get("year", _dt.date.today().year))
        plan = delivery.existing_plan(year)
        if not plan:
            raise HTTPError(404, "No plan computed yet for this year")
        return plan

    @app.post("/api/plan/compute")
    @require_perm("ops:run")
    def compute_plan(req):
        body = req.json
        year = int(body.get("year", _dt.date.today().year))
        iterations = int(body.get("iterations", 4000))
        return delivery.compute_and_persist_plan(year, req.ctx["user"].username,
                                                 iterations)

    # ---------- production ----------
    @app.get("/api/production/mrp")
    @require_perm("prod:read")
    def mrp(req):
        year = int(req.query.get("year", 2026))
        return production.run_mrp(year)

    @app.get("/api/production/capacity")
    @require_perm("prod:read")
    def capacity(req):
        year = int(req.query.get("year", 2026))
        return production.capacity_check(year)

    @app.post("/api/production/release")
    @require_perm("prod:write")
    def release(req):
        body = req.json
        return production.release_plan(int(body.get("year", 2026)),
                                       req.ctx["user"].username)

    @app.get("/api/production/orders")
    @require_perm("prod:read")
    def orders(req):
        status = req.query.get("status")
        where = "status=?" if status else "1=1"
        params = (status,) if status else ()
        return [po.to_dict() for po in
                ProductionOrder.all(where, params, order="po_number")]

    @app.post("/api/production/orders/{id}/receive")
    @require_perm("inv:write")
    def receive_po(req):
        po = ProductionOrder.get(int(req.params["id"]))
        if not po:
            raise HTTPError(404)
        return inv_svc.receive_po_materials(po.po_number,
                                            req.ctx["user"].username)

    @app.post("/api/production/orders/{id}/complete")
    @require_perm("prod:write")
    def complete_po(req):
        po = ProductionOrder.get(int(req.params["id"]))
        if not po:
            raise HTTPError(404)
        body = req.json if req.body else {}
        qty = body.get("qty")
        return inv_svc.complete_po(po.po_number, req.ctx["user"].username,
                                   qty)

    # ---------- inventory ----------
    @app.get("/api/inventory")
    @require_perm("inv:read")
    def inventory_list(req):
        loc = req.query.get("location")
        where = "location=?" if loc else "1=1"
        params = (loc,) if loc else ()
        return [i.to_dict() for i in InventoryItem.all(where, params,
                                                       order="sku")]

    @app.get("/api/inventory/moves")
    @require_perm("inv:read")
    def moves(req):
        return [m.to_dict() for m in
                InventoryMove.all(order="id DESC", limit=100)]

    @app.get("/api/inventory/alerts")
    @require_perm("inv:read")
    def alerts(req):
        return inv_svc.reorder_alerts()

    @app.post("/api/inventory/transfer")
    @require_perm("inv:write")
    def transfer(req):
        b = req.json
        inv_svc.transfer(b["sku"], b["src"], b["dst"], float(b["qty"]),
                         req.ctx["user"].username)
        return {"ok": True}

    @app.post("/api/inventory/load_sleigh")
    @require_perm("ops:run")
    def load_sleigh(req):
        b = req.json
        return inv_svc.load_to_sleigh(int(b.get("year", 2026)),
                                      req.ctx["user"].username)

    # ---------- naughty & nice ----------
    @app.get("/api/list/stats")
    @require_perm("list:read")
    def list_stats(req):
        return naughty_nice.list_stats()

    @app.get("/api/list/children")
    @require_perm("list:read")
    def children(req):
        q = req.query.get("q", "").lower()
        status = req.query.get("status")
        where, params = "1=1", []
        if q:
            where += " AND LOWER(name) LIKE ?"
            params.append(f"%{q}%")
        if status:
            where += " AND status=?"
            params.append(status)
        rows = Child.all(where, params, order="behavior_score DESC", limit=200)
        city_ids = {c.city_id for c in rows}
        cmap = {}
        if city_ids:
            marks = ",".join("?" for _ in city_ids)
            cmap = {c["id"]: c for c in
                    City.all(f"id IN ({marks})", tuple(city_ids))}
        out = []
        for c in rows:
            d = c.to_dict()
            city = cmap.get(c.city_id)
            d["city"] = city.name if city else "?"
            d["country"] = city.country if city else "?"
            out.append(d)
        return out

    @app.post("/api/list/children/{id}/review")
    @require_perm("list:read")  # reviewers are auditors/admins; fine-grained below
    def review(req):
        u = req.ctx["user"]
        if u.role not in ("admin", "planner"):
            raise HTTPError(403, "Only admins and planners review children")
        body = req.json
        child = naughty_nice.review_child(int(req.params["id"]),
                                          body.get("decision", ""),
                                          u.username, body.get("note", ""))
        return child.to_dict()

    @app.post("/api/list/rescan")
    @require_perm("ops:run")
    def rescan(req):
        return naughty_nice.rescan_all()

    @app.get("/api/list/coal")
    @require_perm("list:read")
    def coal(req):
        return {"coal_kg": naughty_nice.naughty_coal_load()}

    # ---------- tracking ----------
    @app.get("/api/tracking")
    @require_perm("track:read")
    def tracking(req):
        year = int(req.query.get("year", 2026))
        elapsed = float(req.query.get("elapsed", 0))
        return delivery.tracking_state(year, elapsed)

    # ---------- KPIs & analytics ----------
    @app.get("/api/kpis")
    @require_perm("plan:read")
    def kpis(req):
        year = int(req.query.get("year", 2026))
        return delivery.capture_kpis(year)

    @app.get("/api/kpis/history")
    @require_perm("plan:read")
    def kpi_history(req):
        metric = req.query.get("metric", "total_km")
        return delivery.kpi_history(metric)

    # ---------- audit ----------
    @app.get("/api/audit")
    @require_perm("audit:read")
    def audit_log(req):
        return [a.to_dict() for a in AuditLog.all(order="id DESC", limit=100)]

    # ---------- users (admin) ----------
    @app.get("/api/users")
    @require_perm("*")
    def users(req):
        return [{**u.to_dict(), "password_hash": None}
                for u in User.all(order="username")]

    @app.patch("/api/users/{id}")
    @require_perm("*")
    def user_update(req):
        u = User.get(int(req.params["id"]))
        if not u:
            raise HTTPError(404)
        body = req.json
        if "role" in body:
            if body["role"] not in ROLE_PERMISSIONS:
                raise HTTPError(422, "unknown role")
            u.role = body["role"]
        if "active" in body:
            u.active = int(bool(body["active"]))
        if u.username == req.ctx["user"].username and not u.active:
            raise HTTPError(422, "cannot deactivate yourself")
        u.update()
        from ..auth import audit
        audit(req.ctx["user"].username, "user_update", "user", u.id,
              f"role={u.role} active={u.active}")
        return {**u.to_dict(), "password_hash": None}

    # ---------- middleware & static ----------
    app.before_request(attach_session)
    app.before_request(check_csrf)
    here_web = os.path.normpath(os.path.join(here, "..", "web"))
    app.static("/", here_web)

    return app


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NPOPS server")
    parser.add_argument("--db", default="data/npops.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reseed", action="store_true")
    args = parser.parse_args()

    fresh = args.reseed or not os.path.exists(args.db)
    app = create_app(args.db)
    if fresh:
        db = app and None
        from ..orm import get_db
        seed_mod.seed(get_db())
        print(f"  seeded fresh database at {args.db}")
    app.run(args.host, args.port)


if __name__ == "__main__":
    main()
