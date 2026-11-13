"""NPOPS Route Optimizer — vehicle routing for one delivery night.

Problem: Santa departs the North Pole, visits N cities worldwide, and
must be out of each timezone before local children wake. Constraints:

  1. Capacity: sleigh payload (kg) and volume (dm3) are finite.
  2. Time windows: each city has a local deadline (children wake ~6am);
     midnight-datum time = local_deadline - tz_offset must be respected
     in a *single global timeline* starting at local midnight UTC-datum.
  3. Single vehicle (one magical sleigh), so really a capacitated
     TSP-with-deadlines, but we plan multiple "sorties" (route legs that
     return to refit) modeled as a multi-route VRP.

Algorithm:
  - Clarke-Wright savings to build an initial VRP solution
  - Local search: relocate, swap, 2-opt, Or-opt with deadline-aware
    feasibility checks and simulated-annealing acceptance.
  - Global deadline repair: push infeasible stops to earlier regions.

Distances are great-circle (haversine) with an effective-speed boost
(9 reindeer, 1856 first flight) — flight time ~= km / MAGIC_SPEED.
"""
from __future__ import annotations

import math
import random

from ..models import City

# --- constants ----------------------------------------------------------------
MAGIC_SPEED_KMH = 4750.0        # "sleigh speed" (km/h) — calibrated so a
                                # full global tour fits inside the night
EARTH_R_KM = 6371.0
NORTH_POLE = (90.0, 0.0)
SLEIGH_CAPACITY_KG = 15000.0
SLEIGH_CAPACITY_DM3 = 40000.0
GROUND_TURNAROUND_MIN = 4.0     # per-stop chimney time in "sliding" minutes


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(h))


class DistanceMatrix:
    """N x N haversine matrix + depot row (index N is the North Pole)."""

    def __init__(self, cities: list[City]):
        self.cities = cities
        n = len(cities)
        coords = [(c.lat, c.lon) for c in cities] + [NORTH_POLE]
        m = [[0.0] * (n + 1) for _ in range(n + 1)]
        for i in range(n + 1):
            xi, yi = coords[i]
            for j in range(i + 1, n + 1):
                d = haversine((xi, yi), coords[j])
                m[i][j] = m[j][i] = d
        self.m = m
        self.n = n

    def depot(self, i: int) -> float:
        return self.m[i][self.n]

    def d(self, i: int, j: int) -> float:
        return self.m[i][j]

    def flight_hours(self, km: float) -> float:
        return km / MAGIC_SPEED_KMH


class Stop:
    __slots__ = ("city", "demand_kg", "demand_dm3", "deadline", "arrive",
                 "depart", "service_min", "mx")

    def __init__(self, city: City, demand_kg: float, demand_dm3: float,
                 deadline: float, service_min: float, mx: int = 0):
        self.city = city
        self.mx = mx                     # index into the distance matrix
        self.demand_kg = demand_kg
        self.demand_dm3 = demand_dm3
        self.deadline = deadline          # in global-timeline hours
        self.service_min = service_min
        self.arrive = 0.0
        self.depart = 0.0

    @property
    def city_name(self) -> str:
        return self.city.name


def build_stops(cities: list[City], demand_by_city: dict[int, tuple[float, float]]) -> list[Stop]:
    """demand_by_city: city_id -> (kg, dm3). Deadline = tz offset adjusted
    local wake time, expressed on a timeline where hour 0 = departure."""
    stops = []
    for mx, c in enumerate(cities):
        kg, dm3 = demand_by_city.get(c.id, (0.0, 0.0))
        anchor = 12.0  # UTC+12 midnight = hour 0
        deadline = (c.timezone_deadline - (c.local_utc_offset - anchor)) + 24.0
        stops.append(Stop(c, kg, dm3, deadline,
                          GROUND_TURNAROUND_MIN + min(20.0, c.children / 100_000),
                          mx=mx))
    return stops


class RouteLeg:
    """One sortie: depot -> stops... -> depot."""

    def __init__(self):
        self.stops: list[Stop] = []
        self.arrive = 0.0
        self.flight_km = 0.0

    def load_kg(self) -> float:
        return sum(s.demand_kg for s in self.stops)

    def load_dm3(self) -> float:
        return sum(s.demand_dm3 for s in self.stops)

    def copy(self) -> "RouteLeg":
        r = RouteLeg()
        r.stops = list(self.stops)
        return r


class Solution:
    def __init__(self, legs: list[RouteLeg], matrix: DistanceMatrix):
        self.legs = legs
        self.matrix = matrix
        self.evaluate()

    def copy(self) -> "Solution":
        return Solution([leg.copy() for leg in self.legs], self.matrix)

    def evaluate(self):
        """Simulate the full night: legs run sequentially from hour 0."""
        t = 0.0
        total_km = 0.0
        for leg in self.legs:
            t += self.matrix.flight_hours(self.matrix.depot(leg.stops[0].mx)) if leg.stops else 0.0
            for idx, s in enumerate(leg.stops):
                if idx == 0:
                    km = self.matrix.depot(s.mx)
                else:
                    km = self.matrix.d(leg.stops[idx - 1].mx, s.mx)
                fh = self.matrix.flight_hours(km)
                t += fh
                total_km += km
                s.arrive = t
                svc = s.service_min / 60.0
                t = max(t, 0.0) + svc
                s.depart = t
            if leg.stops:
                km_back = self.matrix.depot(leg.stops[-1].mx)
                total_km += km_back
                t += self.matrix.flight_hours(km_back)
                t += 0.5  # refit pause
            leg.arrive = t
            leg.flight_km = 0.0
        self.total_km = total_km
        self.makespan = t
        self.violations = self._violations()

    def _violations(self) -> list[str]:
        v = []
        for li, leg in enumerate(self.legs):
            if leg.load_kg() > SLEIGH_CAPACITY_KG:
                v.append(f"leg {li + 1}: overload {leg.load_kg():.0f}kg")
            if leg.load_dm3() > SLEIGH_CAPACITY_DM3:
                v.append(f"leg {li + 1}: volume exceeded")
            for s in leg.stops:
                if s.arrive > s.deadline:
                    v.append(f"{s.city_name}: missed wake deadline "
                             f"({s.arrive:.1f} > {s.deadline:.1f})")
        return v

    @property
    def feasible(self) -> bool:
        return not self.violations

    def cost(self) -> float:
        """Lower is better; violations dominate."""
        return self.makespan + 1000.0 * len(self.violations) + 0.01 * self.total_km


class ClarkeWright:
    """Parallel savings algorithm producing an initial solution."""

    def __init__(self, stops: list[Stop], matrix: DistanceMatrix,
                 max_legs: int):
        self.stops = stops
        self.m = matrix
        self.max_legs = max_legs

    def solve(self) -> Solution:
        n = len(self.stops)
        legs: list[RouteLeg] = []
        for s in self.stops:
            leg = RouteLeg()
            leg.stops = [s]
            legs.append(leg)
        active = n  # number of non-empty legs
        savings = []
        for i in range(n):
            for j in range(i + 1, n):
                si = self.m.depot(i) + self.m.depot(j) - self.m.d(i, j)
                savings.append((si, i, j))
        savings.sort(reverse=True)

        stop_leg: dict[int, int] = {i: i for i in range(n)}
        for s, i, j in savings:
            if active <= self.max_legs:
                break
            li, lj = stop_leg[i], stop_leg[j]
            if li == lj or li is None or lj is None:
                continue
            leg_i, leg_j = legs[li], legs[lj]
            si_stop, sj_stop = self.stops[i], self.stops[j]
            ii = leg_i.stops.index(si_stop)
            jj = leg_j.stops.index(sj_stop)
            if ii not in (0, len(leg_i.stops) - 1):
                continue
            if jj not in (0, len(leg_j.stops) - 1):
                continue
            merged = RouteLeg()
            if ii == len(leg_i.stops) - 1:
                seq_i = leg_i.stops
            else:
                seq_i = leg_i.stops[::-1]
            if jj == 0:
                seq_j = leg_j.stops
            else:
                seq_j = leg_j.stops[::-1]
            merged.stops = seq_i + seq_j
            if merged.load_kg() > SLEIGH_CAPACITY_KG or \
               merged.load_dm3() > SLEIGH_CAPACITY_DM3:
                continue
            legs[li] = merged
            legs[lj] = RouteLeg()
            active -= 1
            for st in merged.stops:
                stop_leg[st.mx] = li
            stop_leg[j] = li
        legs = [leg for leg in legs if leg.stops]
        return Solution(legs, self.m)


class LocalSearch:
    """Relocate / swap / 2-opt with SA acceptance and deadline repair."""

    def __init__(self, matrix: DistanceMatrix, iterations: int = 4000,
                 seed: int = 7):
        self.m = matrix
        self.iters = iterations
        self.rng = random.Random(seed)

    def improve(self, sol: Solution) -> Solution:
        best = sol.copy()
        best_cost = best.cost()
        cur = sol.copy()
        cur_cost = cur.cost()
        T0, T1 = 40.0, 0.05
        for it in range(self.iters):
            T = T0 * (T1 / T0) ** (it / self.iters)
            cand = self._neighbor(cur)
            c = cand.cost()
            if c < cur_cost or self.rng.random() < math.exp(-(c - cur_cost) / max(T, 1e-9)):
                cur, cur_cost = cand, c
                if c < best_cost:
                    best, best_cost = cand.copy(), c
        # final deadline-repair sweep (deterministic)
        best = self._repair(best)
        return best

    def _neighbor(self, sol: Solution) -> Solution:
        cand = sol.copy()
        op = self.rng.random()
        if op < 0.4:
            self._relocate(cand)
        elif op < 0.7:
            self._swap(cand)
        else:
            self._two_opt(cand)
        cand.evaluate()
        return cand

    def _pick_legs(self, sol: Solution):
        legs = [l for l in sol.legs if l.stops]
        if not legs:
            return None, None
        a = self.rng.choice(legs)
        b = self.rng.choice(legs) if len(legs) > 1 else a
        return a, b

    def _relocate(self, sol: Solution):
        a, b = self._pick_legs(sol)
        if not a or len(a.stops) < 1:
            return
        i = self.rng.randrange(len(a.stops))
        s = a.stops.pop(i)
        if b is a:
            j = self.rng.randrange(len(a.stops) + 1)
        else:
            j = self.rng.randrange(len(b.stops) + 1)
        b.stops.insert(j, s)
        if not a.stops and a in sol.legs and len(sol.legs) > 1:
            pass  # empty leg kept; harmless

    def _swap(self, sol: Solution):
        a, b = self._pick_legs(sol)
        if not a or not b:
            return
        i = self.rng.randrange(len(a.stops))
        j = self.rng.randrange(len(b.stops))
        a.stops[i], b.stops[j] = b.stops[j], a.stops[i]

    def _two_opt(self, sol: Solution):
        a, _ = self._pick_legs(sol)
        if not a or len(a.stops) < 2:
            return
        i = self.rng.randrange(len(a.stops))
        j = self.rng.randrange(len(a.stops))
        i, j = min(i, j), max(i, j)
        a.stops[i:j + 1] = a.stops[i:j + 1][::-1]

    def _repair(self, sol: Solution) -> Solution:
        """Greedily move deadline-violating stops to earlier legs/positions."""
        sol.evaluate()
        for _ in range(200):
            bad = None
            for li, leg in enumerate(sol.legs):
                for si, s in enumerate(leg.stops):
                    if s.arrive > s.deadline:
                        bad = (li, si, s)
                        break
                if bad:
                    break
            if not bad:
                break
            li, si, s = bad
            sol.legs[li].stops.pop(si)
            # find placement with earliest arrival for s
            best = None
            for lj, leg in enumerate(sol.legs):
                if leg.load_kg() + s.demand_kg > SLEIGH_CAPACITY_KG and lj != li:
                    continue
                for pos in range(len(leg.stops) + 1):
                    if lj == li and pos >= si:
                        pos2 = pos  # popped earlier; approximate
                    trial = Solution([l.copy() for l in sol.legs], self.m)
                    trial.legs[lj].stops.insert(pos, s)
                    trial.evaluate()
                    v = len(trial.violations)
                    key = (v, trial.makespan)
                    if best is None or key < best[0]:
                        best = (key, lj, pos)
            if best is None:
                # restore
                sol.legs[li].stops.insert(si, s)
                break
            _, lj, pos = best
            sol.legs[lj].stops.insert(pos, s)
            sol.evaluate()
        return sol


def plan_delivery_year(cities: list[City],
                       demand_by_city: dict[int, tuple[float, float]],
                       max_sorties: int = 6,
                       iterations: int = 4000) -> Solution:
    served = [c for c in cities if c.id in demand_by_city]
    matrix = DistanceMatrix(served)
    stops = build_stops(served, demand_by_city)
    init = ClarkeWright(stops, matrix, max_legs=max_sorties).solve()
    ls = LocalSearch(matrix, iterations=iterations)
    return ls.improve(init)
