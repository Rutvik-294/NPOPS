"""NPOPS Naughty/Nice service — behavior scoring and list management.

Scoring model: weighted behavioral events with recency decay, plus a
manual review workflow (watchlist -> nice/naughty with justification).
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone

from ..models import Child, City, WishList
from ..auth import utcnow_iso, audit

# Behavioral event weights (positive = nice evidence)
EVENT_WEIGHTS = {
    "shared_toy": 3.0, "helped_chores": 2.5, "kind_to_sibling": 3.0,
    "thanked_giver": 1.5, "fed_reindeer": 4.0, "left_cookies": 1.0,
    "tantrum": -3.0, "lied": -4.0, "hit_sibling": -5.0,
    "refused_bedtime": -1.0, "broccoli_strike": -0.5,
}
RECENCY_HALF_LIFE_DAYS = 120.0


def behavior_score(child: Child, events: list[dict]) -> float:
    """events: [{type, days_ago}]. Score clamped to [0, 100]."""
    base = 50.0
    now = datetime.now(timezone.utc)
    for ev in events:
        w = EVENT_WEIGHTS.get(ev["type"], 0.0)
        decay = 0.5 ** (ev.get("days_ago", 0) / RECENCY_HALF_LIFE_DAYS)
        base += w * decay
    return max(0.0, min(100.0, base))


def classify(score: float) -> str:
    if score >= 70:
        return "nice"
    if score >= 45:
        return "watchlist"
    return "naughty"


def review_child(child_id: int, decision: str, reviewer: str,
                 note: str = "") -> Child:
    child = Child.get(child_id)
    if not child:
        raise ValueError(f"unknown child {child_id}")
    if decision not in ("nice", "naughty", "watchlist"):
        raise ValueError("decision must be nice|naughty|watchlist")
    child.status = decision
    child.last_reviewed = utcnow_iso()
    child.update()
    audit(reviewer, "child_review", "child", child_id,
          f"{decision} (score {child.behavior_score}) {note}")
    return child


def rescan_all(seed_rng: int = 99) -> dict:
    """Annual behavior rescan — re-scores every child, reclassifies."""
    rng = random.Random(seed_rng)
    changed = {"nice": 0, "naughty": 0, "watchlist": 0}
    for child in Child.all():
        drift = rng.gauss(0, 6)
        child.behavior_score = round(max(0.0, min(100.0,
            child.behavior_score + drift)), 1)
        new_status = classify(child.behavior_score)
        if new_status != child.status:
            changed[child.status] = changed.get(child.status, 0) + 1
            child.status = new_status
        child.last_reviewed = utcnow_iso()
        child.update()
    audit("system", "rescan", "children", "all",
          f"transitions out: {changed}")
    return {"rescored": Child.count(), "status_changes_from": changed}


def list_stats() -> dict:
    rows = Child.all()
    by_status = {"nice": 0, "naughty": 0, "watchlist": 0}
    total_score = 0.0
    for c in rows:
        by_status[c.status] = by_status.get(c.status, 0) + 1
        total_score += c.behavior_score
    return {"total": len(rows), "by_status": by_status,
            "avg_score": round(total_score / len(rows), 1) if rows else 0}


def naughty_coal_load() -> float:
    """Coal required (kg), 0.5 kg per naughty child."""
    naughty = Child.count("status='naughty'")
    return naughty * 0.5


def delivery_manifest(year: int) -> list[dict]:
    """Build the full nice-list manifest: child -> gift -> city."""
    children = {c.id: c for c in Child.all("status='nice'")}
    cities = {c.id: c for c in City.all()}
    manifest = []
    for wl in WishList.all("rank=1"):
        ch = children.get(wl.child_id)
        if not ch:
            continue
        city = cities.get(ch.city_id)
        manifest.append({
            "child_id": ch.id, "child_name": ch.name,
            "city": city.name if city else "?", "country": city.country if city else "?",
            "gift_sku": wl.gift_sku,
        })
    return manifest
