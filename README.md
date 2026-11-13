# NPOPS — North Pole Operations Platform

An enterprise logistics & manufacturing SaaS for Santa's Workshop.
Season planning, a vehicle-route optimizer for the global delivery run,
production scheduling with MRP, inventory control, naughty/nice case
management, live sleigh tracking, and an audit trail — all in one
zero-dependency Python package.

```
        _
     -=(_)=-   NPOPS · North Pole Operations
       /(\      Season 2026 is coming.
       ˆˆ
```

## Why this exists

Delivering presents to every nice child on Earth is, operationally, a
capacitated vehicle-routing problem with hard time windows, a BOM-driven
manufacturing plan with capacity constraints, and a global supply chain
— compressed into one night. NPOPS treats it that way.

## Architecture

```
npops/
├── webframe.py        WSGI micro-framework (routing, middleware, static)
├── orm.py             ActiveRecord-style ORM over sqlite3
├── security.py        PBKDF2 password hashing, HMAC-signed tokens, CSRF
├── auth.py            Sessions, RBAC (admin/planner/elf/auditor/viewer)
├── models.py          16-table domain schema
├── seed.py            The world: 89 cities, workshop masters, children
├── api/app.py         REST API (32 routes) + server bootstrap
├── optimizer/vrp.py   Clarke-Wright savings + simulated-annealing local search
├── services/
│   ├── production.py  MRP, capacity leveling, production orders
│   ├── inventory.py   Movement ledger, PO receipt/consumption, sleigh loading
│   ├── naughty_nice.py Behavior scoring, reviews, coal logistics
│   └── delivery.py    Plan persistence, live tracking, KPI snapshots
└── web/               Vanilla-JS SPA (no build step, no framework)
tests/test_npops.py    23 tests: security, RBAC, ORM, VRP feasibility, WSGI
```

**Zero runtime dependencies.** Everything above is Python 3.12 stdlib —
no Flask, no SQLAlchemy, no numpy. The frontend is framework-free ES
modules. `pip install` is not a step.

## The optimizer

The delivery run is modeled as a multi-sortie VRP from the North Pole:

- **Constraints** — sleigh payload (15,000 kg) and volume (40,000 dm³);
  per-city wake-time deadlines on a global timeline anchored to the
  first timezone to hit midnight; chimney service time scaled by city
  child count.
- **Construction** — Clarke-Wright parallel savings merges one-stop
  sorties until the sortie budget is reached, respecting capacity.
- **Improvement** — simulated annealing over relocate / swap / 2-opt
  neighborhoods with violation-dominated cost, followed by a
  deterministic deadline-repair pass that greedily re-seats violating
  stops at their earliest feasible position.
- **Distances** — great-circle (haversine) with effective sleigh speed
  calibrated so a full global tour closes inside the night.

A full 58-city plan with 2 sorties solves to zero violations in under a
second on a laptop.

## The operating cycle

1. **Plan** — the nice list drives demand; the optimizer computes
   sorties and assigns every nice child's rank-1 wish to a route stop.
2. **Manufacture** — MRP explodes demand through BOMs, nets against
   on-hand, levels load across six work centers, and releases POs.
3. **Build** — elves receive materials into WH-MAIN, complete POs
   (components consumed, finished gifts to WH-GIFTS).
4. **Load** — finished gifts transfer WH-GIFTS → SLEIGH; assignments
   flip to `loaded`. The ledger invariant (sum of moves ≡ Δon-hand)
   holds throughout.
5. **Fly** — live tracking interpolates sleigh position along each
   sortie timeline; the mission clock drives per-route progress.

## Run it

```bash
python3 -m npops.api.app --db data/npops.db --port 8000
# → http://localhost:8000
```

Demo accounts (password `joy`, Santa is `ho-ho-ho`):

| User    | Role    | Can do                                        |
|---------|---------|-----------------------------------------------|
| sclaus  | admin   | everything incl. user management               |
| mclaus  | planner | plan & release production, review children     |
| tinsel  | planner | same as mclaus                                 |
| birch   | elf     | shop floor: receive/complete POs, move stock   |
| holly   | auditor | read everything, audit log, no writes          |

## Test

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

23 tests cover password hashing, token signing, RBAC matrices, ORM
constraints, BOM explosion math, VRP feasibility and determinism,
distance-matrix symmetry, the inventory ledger invariant, and full
WSGI-stack auth/CSRF/RBAC flows.

## Security notes

- Passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user salt.
- Sessions: 256-bit random IDs in HttpOnly SameSite=Lax cookies.
- State-changing requests require an HMAC-verified CSRF token header.
- SQL is fully parameterized; audit log records every mutation.

## Data

City coordinates are real (approximate city centers). Seed data is
deterministic (`random.Random(1847)`) so route plans are reproducible.
