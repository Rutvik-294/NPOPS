"""NPOPS domain model — the schema of the North Pole enterprise."""
from __future__ import annotations

from .orm import Model, Column


class User(Model):
    __tablename__ = "users"
    id = Column("INTEGER", pk=True)
    username = Column("TEXT", null=False, unique=True)
    password_hash = Column("TEXT", null=False)
    full_name = Column("TEXT", null=False)
    role = Column("TEXT", null=False, default="viewer")  # admin|planner|elf|auditor|viewer
    email = Column("TEXT")
    active = Column("INTEGER", default=1)
    created_at = Column("TEXT", default="datetime placeholder")


class Session(Model):
    __tablename__ = "sessions"
    id = Column("TEXT", pk=True)
    user_id = Column("INTEGER", null=False, index=True)
    csrf_token = Column("TEXT", null=False)
    created_at = Column("TEXT")
    expires_at = Column("TEXT")
    ip = Column("TEXT")


class Region(Model):
    __tablename__ = "regions"
    id = Column("INTEGER", pk=True)
    name = Column("TEXT", null=False, unique=True)
    timezone_offset = Column("REAL", default=0.0)  # hours from UTC
    delivery_night_hours = Column("REAL", default=10.0)


class City(Model):
    __tablename__ = "cities"
    id = Column("INTEGER", pk=True)
    name = Column("TEXT", null=False, index=True)
    country = Column("TEXT", null=False, index=True)
    region_id = Column("INTEGER", null=False, index=True, fk=("regions", "id"))
    lat = Column("REAL", null=False)
    lon = Column("REAL", null=False)
    population = Column("INTEGER", default=0)
    children = Column("INTEGER", default=0)     # estimated children count
    nice_ratio = Column("REAL", default=0.92)
    local_utc_offset = Column("REAL", default=0.0)
    timezone_deadline = Column("REAL", default=6.0)  # local 6am deadline


class GiftCatalog(Model):
    __tablename__ = "gift_catalog"
    id = Column("INTEGER", pk=True)
    sku = Column("TEXT", null=False, unique=True)
    name = Column("TEXT", null=False)
    category = Column("TEXT", null=False)
    weight_kg = Column("REAL", null=False)
    volume_dm3 = Column("REAL", default=1.0)
    unit_cost_materials = Column("REAL", default=0.0)
    unit_labor_minutes = Column("REAL", default=1.0)
    complexity = Column("INTEGER", default=1)   # 1-5, affects work center routing
    active = Column("INTEGER", default=1)


class BomLine(Model):
    __tablename__ = "bom_lines"
    id = Column("INTEGER", pk=True)
    gift_sku = Column("TEXT", null=False, index=True)
    component_sku = Column("TEXT", null=False)
    qty_per_unit = Column("REAL", null=False)
    scrap_pct = Column("REAL", default=2.0)


class WorkCenter(Model):
    __tablename__ = "work_centers"
    id = Column("INTEGER", pk=True)
    code = Column("TEXT", null=False, unique=True)
    name = Column("TEXT", null=False)
    capacity_minutes_per_day = Column("REAL", null=False)
    elf_count = Column("INTEGER", default=10)
    min_complexity = Column("INTEGER", default=1)
    max_complexity = Column("INTEGER", default=5)
    active = Column("INTEGER", default=1)


class ProductionOrder(Model):
    __tablename__ = "production_orders"
    id = Column("INTEGER", pk=True)
    po_number = Column("TEXT", null=False, unique=True)
    gift_sku = Column("TEXT", null=False, index=True)
    qty = Column("INTEGER", null=False)
    status = Column("TEXT", null=False, default="draft")
    # draft|released|in_progress|completed|cancelled
    priority = Column("INTEGER", default=5)
    work_center_id = Column("INTEGER", fk=("work_centers", "id"))
    due_date = Column("TEXT")
    created_by = Column("INTEGER")
    created_at = Column("TEXT")
    completed_qty = Column("INTEGER", default=0)


class InventoryItem(Model):
    __tablename__ = "inventory_items"
    id = Column("INTEGER", pk=True)
    sku = Column("TEXT", null=False, index=True)
    location = Column("TEXT", null=False)       # e.g. WH-MAIN, WH-STABLES, SLEIGH
    on_hand = Column("REAL", default=0.0)
    allocated = Column("REAL", default=0.0)
    reorder_point = Column("REAL", default=0.0)
    reorder_qty = Column("REAL", default=0.0)
    unit = Column("TEXT", default="unit")
    updated_at = Column("TEXT")


class InventoryMove(Model):
    __tablename__ = "inventory_moves"
    id = Column("INTEGER", pk=True)
    sku = Column("TEXT", null=False, index=True)
    location = Column("TEXT", null=False)
    delta = Column("REAL", null=False)          # signed quantity
    reason = Column("TEXT", null=False)
    # receipt|issue|transfer_in|transfer_out|adjust|consume
    ref_type = Column("TEXT")                   # po|gift_id|manual
    ref_id = Column("TEXT")
    actor = Column("TEXT")
    created_at = Column("TEXT")


class Child(Model):
    __tablename__ = "children"
    id = Column("INTEGER", pk=True)
    name = Column("TEXT", null=False)
    city_id = Column("INTEGER", null=False, index=True, fk=("cities", "id"))
    behavior_score = Column("REAL", default=75.0)  # 0-100
    status = Column("TEXT", default="nice")        # nice|naughty|watchlist
    last_reviewed = Column("TEXT")


class WishList(Model):
    __tablename__ = "wishlists"
    id = Column("INTEGER", pk=True)
    child_id = Column("INTEGER", null=False, index=True, fk=("children", "id"))
    gift_sku = Column("TEXT", null=False)
    rank = Column("INTEGER", default=1)
    received_year = Column("INTEGER")


class DeliveryAssignment(Model):
    __tablename__ = "delivery_assignments"
    id = Column("INTEGER", pk=True)
    year = Column("INTEGER", null=False, index=True)
    child_id = Column("INTEGER", null=False, index=True)
    gift_sku = Column("TEXT", null=False)
    route_id = Column("TEXT", index=True)
    stop_seq = Column("INTEGER")
    status = Column("TEXT", default="planned")
    # planned|loaded|in_transit|delivered|failed
    delivered_at = Column("TEXT")


class Route(Model):
    __tablename__ = "routes"
    id = Column("TEXT", pk=True)                 # e.g. R-2026-A1
    year = Column("INTEGER", null=False, index=True)
    region_id = Column("INTEGER", null=False)
    name = Column("TEXT", null=False)
    stop_count = Column("INTEGER", default=0)
    total_km = Column("REAL", default=0.0)
    load_kg = Column("REAL", default=0.0)
    departure_utc = Column("REAL")
    completion_utc = Column("REAL")
    feasible = Column("INTEGER", default=1)
    infeasibility_reasons = Column("TEXT")       # JSON array
    city_ids = Column("TEXT")                    # JSON array of stop order
    created_at = Column("TEXT")


class AuditLog(Model):
    __tablename__ = "audit_log"
    id = Column("INTEGER", pk=True)
    ts = Column("TEXT")
    actor = Column("TEXT")
    action = Column("TEXT", null=False)
    entity = Column("TEXT")
    entity_id = Column("TEXT")
    detail = Column("TEXT")


class KpiSnapshot(Model):
    __tablename__ = "kpi_snapshots"
    id = Column("INTEGER", pk=True)
    captured_at = Column("TEXT")
    year = Column("INTEGER")
    metric = Column("TEXT", null=False, index=True)
    value = Column("REAL", null=False)
