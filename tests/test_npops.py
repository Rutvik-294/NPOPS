"""NPOPS test suite — zero-dependency runner (unittest stdlib)."""
from __future__ import annotations

import sys
import unittest

sys.path.insert(0, ".")

from npops.orm import Database, set_db
from npops import seed
from npops.security import hash_password, verify_password, TokenSigner
from npops.auth import has_perm, ROLE_PERMISSIONS


def fresh_db():
    db = Database(":memory:")
    set_db(db)
    seed.seed(db)
    return db


class TestSecurity(unittest.TestCase):
    def test_password_roundtrip(self):
        h = hash_password("joy")
        self.assertTrue(verify_password("joy", h))
        self.assertFalse(verify_password("Joy", h))
        self.assertFalse(verify_password("", h))
        self.assertFalse(verify_password("joy", "garbage"))

    def test_token_signer(self):
        s = TokenSigner(b"k" * 32)
        tok = s.sign({"user": 1}, ttl=60)
        self.assertEqual(s.verify(tok)["user"], 1)
        self.assertIsNone(s.verify(tok + "x"))
        self.assertIsNone(s.verify("not.a.token"))
        expired = s.sign({"user": 1}, ttl=-10)
        self.assertIsNone(s.verify(expired))


class TestRBAC(unittest.TestCase):
    def test_permissions(self):
        self.assertTrue(has_perm("admin", "anything"))
        self.assertTrue(has_perm("planner", "plan:write"))
        self.assertFalse(has_perm("planner", "audit:read"))
        self.assertTrue(has_perm("elf", "prod:write"))
        self.assertFalse(has_perm("elf", "plan:write"))
        self.assertTrue(has_perm("auditor", "audit:read"))
        self.assertFalse(has_perm("viewer", "inv:write"))

    def test_roles_covered(self):
        for role in ("admin", "planner", "elf", "auditor", "viewer"):
            self.assertIn(role, ROLE_PERMISSIONS)


class TestORM(unittest.TestCase):
    def test_crud(self):
        fresh_db()
        from npops.models import City
        c = City.all("name=?", ("Tokyo",))[0]
        self.assertAlmostEqual(c.lat, 35.6762, places=3)
        c.nice_ratio = 0.5
        c.update()
        self.assertEqual(City.get(c.id).nice_ratio, 0.5)
        self.assertGreater(City.count(), 80)

    def test_unknown_column_rejected(self):
        from npops.orm import ModelMeta, Column, Model
        with self.assertRaises(ValueError):
            class Bad(Model):
                __tablename__ = "bad_test"
                order = Column("TEXT")


class TestSeed(unittest.TestCase):
    def test_seed_integrity(self):
        db = fresh_db()
        from npops.models import (City, Region, Child, GiftCatalog, BomLine,
                                  WorkCenter, InventoryItem, WishList, User)
        self.assertEqual(City.count(), len(seed.CITIES))
        self.assertEqual(Region.count(), len(seed.REGIONS))
        self.assertEqual(GiftCatalog.count(), len(seed.GIFTS))
        self.assertEqual(WorkCenter.count(), len(seed.WORK_CENTERS))
        self.assertEqual(User.count(), 6)
        # every bom line references a real gift and a real inventory item
        gift_skus = {g.sku for g in GiftCatalog.all()}
        for bl in BomLine.all():
            self.assertIn(bl.gift_sku, gift_skus)
        # every child has >= 1 wishlist item
        for ch in Child.all():
            self.assertGreaterEqual(WishList.count("child_id=?", (ch.id,)), 1)


class TestVRP(unittest.TestCase):
    def _demand(self):
        from npops.models import Child, WishList, GiftCatalog
        gifts = {g.sku: g for g in GiftCatalog.all()}
        nice = {c.id: c for c in Child.all("status='nice'")}
        demand = {}
        for wl in WishList.all("rank=1"):
            if wl.child_id in nice:
                g = gifts[wl.gift_sku]
                kg, dm3 = demand.get(nice[wl.child_id].city_id, (0.0, 0.0))
                demand[nice[wl.child_id].city_id] = (kg + g.weight_kg,
                                                     dm3 + g.volume_dm3)
        return demand

    def test_plan_feasible(self):
        db = fresh_db()
        from npops.models import City
        from npops.optimizer.vrp import plan_delivery_year, SLEIGH_CAPACITY_KG
        cities = City.all()
        sol = plan_delivery_year(cities, self._demand(), max_sorties=6,
                                 iterations=2000)
        self.assertEqual(sol.violations, [])
        self.assertGreater(len([l for l in sol.legs if l.stops]), 0)
        for leg in sol.legs:
            self.assertLessEqual(leg.load_kg(), SLEIGH_CAPACITY_KG + 1e-6)
        # every demand city visited exactly once
        visited = [s.city.id for l in sol.legs for s in l.stops]
        self.assertEqual(sorted(visited), sorted(self._demand().keys()))

    def test_deterministic(self):
        db = fresh_db()
        from npops.models import City
        from npops.optimizer.vrp import plan_delivery_year
        d = self._demand()
        a = plan_delivery_year(City.all(), d, iterations=500)
        b = plan_delivery_year(City.all(), d, iterations=500)
        self.assertEqual(round(a.total_km, 3), round(b.total_km, 3))

    def test_distance_matrix_symmetry(self):
        db = fresh_db()
        from npops.models import City
        from npops.optimizer.vrp import DistanceMatrix
        m = DistanceMatrix(City.all()[:20])
        for i in range(5):
            for j in range(5):
                self.assertAlmostEqual(m.d(i, j), m.d(j, i))
        self.assertAlmostEqual(m.d(0, 1), m.d(1, 0))


class TestProduction(unittest.TestCase):
    def test_mrp_nets_demand(self):
        db = fresh_db()
        from npops.services import production
        mrp = production.run_mrp(2026)
        self.assertGreater(mrp["total_gifts_needed"], 0)
        self.assertGreaterEqual(mrp["total_gifts_needed"],
                                mrp["total_to_build"])
        for p in mrp["material_proposals"]:
            self.assertGreaterEqual(p["proposed_order"], p["net_requirement"])

    def test_release_and_complete(self):
        db = fresh_db()
        from npops.services import production, inventory
        from npops.models import ProductionOrder, InventoryItem
        production.release_plan(2026, "tester")
        pos = ProductionOrder.all("status='draft'")
        self.assertGreater(len(pos), 0)
        for po in pos:
            inventory.receive_po_materials(po.po_number, "tester")
            r = inventory.complete_po(po.po_number, "tester")
            self.assertEqual(r["status"], "completed")
        # finished gifts now on hand
        gifts_on_hand = sum(i.on_hand for i in
                            InventoryItem.all("location='WH-GIFTS'"))
        self.assertGreater(gifts_on_hand, 0)
        # ledger movement equals the change in on-hand for each touched item
        from npops.models import InventoryMove
        touched = {m.sku for m in InventoryMove.all("location='WH-MAIN'")}
        for item in InventoryItem.all("location='WH-MAIN'"):
            if item.sku not in touched:
                continue
            moves = InventoryMove.all("sku=? AND location=?",
                                      (item.sku, "WH-MAIN"))
            ledger = sum(m.delta for m in moves)
            # seeded opening balance from RAW_MATERIALS
            opening = next((oh for sku, _u, oh, _r, _q in seed.RAW_MATERIALS
                            if sku == item.sku), 0.0)
            self.assertAlmostEqual(
                ledger, item.on_hand - opening, places=6,
                msg=f"ledger drift for {item.sku}")

    def test_negative_stock_rejected(self):
        db = fresh_db()
        from npops.services.inventory import record_move
        with self.assertRaises(ValueError):
            record_move("RAW-PINE", "WH-MAIN", -999999, "issue", "tester")


class TestNaughtyNice(unittest.TestCase):
    def test_classification_thresholds(self):
        from npops.services.naughty_nice import classify
        self.assertEqual(classify(85), "nice")
        self.assertEqual(classify(70), "nice")
        self.assertEqual(classify(50), "watchlist")
        self.assertEqual(classify(30), "naughty")

    def test_score_bounds_and_decay(self):
        from npops.services.naughty_nice import behavior_score
        c = type("C", (), {"behavior_score": 50})()
        s = behavior_score(c, [{"type": "fed_reindeer", "days_ago": 0}])
        self.assertGreater(s, 50)
        old = behavior_score(c, [{"type": "fed_reindeer", "days_ago": 365}])
        fresh = behavior_score(c, [{"type": "fed_reindeer", "days_ago": 0}])
        self.assertLess(old, fresh)
        capped = behavior_score(c, [{"type": "shared_toy", "days_ago": 0}] * 100)
        self.assertLessEqual(capped, 100)

    def test_coal_load(self):
        db = fresh_db()
        from npops.services import naughty_nice
        from npops.models import Child
        naughty = Child.count("status='naughty'")
        self.assertEqual(naughty_nice.naughty_coal_load(), naughty * 0.5)


class TestDeliveryService(unittest.TestCase):
    def test_full_cycle(self):
        db = fresh_db()
        from npops.services import delivery, inventory, production
        plan = delivery.compute_and_persist_plan(2026, "tester", iterations=1500)
        self.assertEqual(plan["violations"], [])
        self.assertGreater(plan["assignments"], 0)
        # persisted plan is retrievable
        again = delivery.existing_plan(2026)
        self.assertEqual(again["assignments"], plan["assignments"])
        # production cycle completes
        production.release_plan(2026, "tester")
        from npops.models import ProductionOrder
        for po in ProductionOrder.all():
            inventory.receive_po_materials(po.po_number, "tester")
            inventory.complete_po(po.po_number, "tester")
        loaded = inventory.load_to_sleigh(2026, "tester")
        self.assertEqual(loaded["loaded"], plan["assignments"])
        # tracking progresses
        t0 = delivery.tracking_state(2026, 0)
        t1 = delivery.tracking_state(2026, 20)
        self.assertEqual(t0["delivered"], 0)
        self.assertGreater(t1["delivered"], t0["delivered"])

    def test_kpis_snapshot(self):
        db = fresh_db()
        from npops.services import delivery
        k = delivery.capture_kpis(2026)
        self.assertIn("nice_children", k)
        hist = delivery.kpi_history("nice_children")
        self.assertGreaterEqual(len(hist), 1)


class TestWebApp(unittest.TestCase):
    """WSGI-level tests through the full middleware stack."""

    @classmethod
    def setUpClass(cls):
        from npops.api.app import create_app
        cls.app = create_app(":memory:")
        from npops.orm import get_db
        seed.seed(get_db())

    def wsgi(self, method, path, body=None, cookie=None, csrf=None):
        env = {
            "REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
            "SERVER_NAME": "test", "SERVER_PORT": "80",
            "CONTENT_LENGTH": "0", "REMOTE_ADDR": "1.2.3.4",
            "wsgi.input": None,
        }
        if body is not None:
            import json
            data = json.dumps(body).encode()
            env["wsgi.input"] = __import__("io").BytesIO(data)
            env["CONTENT_LENGTH"] = str(len(data))
            env["CONTENT_TYPE"] = "application/json"
        if cookie:
            env["HTTP_COOKIE"] = f"npops_session={cookie}"
        if csrf:
            env["HTTP_X_CSRF_TOKEN"] = csrf
        return self.app.handle(env)

    def test_auth_flow(self):
        r = self.wsgi("POST", "/api/auth/login",
                      {"username": "sclaus", "password": "ho-ho-ho"})
        self.assertEqual(r.status, 200)
        cookie = None
        csrf = None
        for k, v in r.headers:
            if k == "Set-Cookie" and "npops_session=" in v:
                cookie = v.split(";")[0].split("=", 1)[1]
            if k == "X-CSRF-Token":
                csrf = v
        self.assertIsNotNone(cookie)
        me = self.wsgi("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(me.status, 200)
        # bad login
        bad = self.wsgi("POST", "/api/auth/login",
                        {"username": "sclaus", "password": "wrong"})
        self.assertEqual(bad.status, 401)

    def test_rbac_enforced(self):
        import json
        for username, pw, path, method in [
            ("holly", "joy", "/api/production/release", "POST"),
            ("birch", "joy", "/api/users", "GET"),
            ("juniper", "joy", "/api/audit", "GET"),
        ]:
            r = self.wsgi("POST", "/api/auth/login",
                          {"username": username, "password": pw})
            cookie = csrf = None
            for k, v in r.headers:
                if k == "Set-Cookie" and "npops_session=" in v:
                    cookie = v.split(";")[0].split("=", 1)[1]
                if k == "X-CSRF-Token":
                    csrf = v
            resp = self.wsgi(method, path, body={}, cookie=cookie, csrf=csrf)
            self.assertEqual(resp.status, 403,
                             f"{username} should not access {path}")

    def test_csrf_enforced(self):
        r = self.wsgi("POST", "/api/auth/login",
                      {"username": "tinsel", "password": "joy"})
        cookie = None
        for k, v in r.headers:
            if k == "Set-Cookie" and "npops_session=" in v:
                cookie = v.split(";")[0].split("=", 1)[1]
        resp = self.wsgi("POST", "/api/list/rescan", body={},
                         cookie=cookie)  # no csrf header
        self.assertEqual(resp.status, 403)

    def test_unknown_route_404(self):
        self.assertEqual(self.wsgi("GET", "/api/nope").status, 404)

    def test_static_index(self):
        r = self.wsgi("GET", "/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"NPOPS", r.body)


def run_all() -> bool:
    suite = unittest.defaultTestLoader.discover(".", pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
