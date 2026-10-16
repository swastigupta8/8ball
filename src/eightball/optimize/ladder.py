"""Search ladder (handoff 6.1, BUILD_SPLIT A11): exactly one method decides each step.

  1. A greedy answer is made first (pipeline.py) and kept as best-so-far, so a timeout never returns nothing.
  2. Splits: every way to cover the rooms with the fewest zones (hubs). If there are at most MAX_SPLITS, try them all.
  3. Mixes inside a split: zones whose candidate loops clash with nothing take their best loop; the other zones'
     loop choices are tried in full if there are at most MAX_MIXES of them, otherwise by beam search (BEAM_WIDTH).
     The best mixes are re-scored with the exact metrics (clash.py).
  4. A CP-SAT backup (ZONE_SOLVER_BACKUP, loaded by name, B's module) picks the split when there are more than
     MAX_SPLITS or half the time budget is gone; step 3 then runs on its split.
  5. Polish (polish.py) with the time left. On a timeout the best so far is returned.

If no split exists at the lower bound (contiguity), one more hub is tried and the reason recorded.
Ties in J go to the smaller gap between the hubs' assigned areas.
"""
from __future__ import annotations

import importlib
import itertools
import math
import time
from dataclasses import dataclass, field

from eightball import config
from eightball.core.contracts import CleanPlan, ZoneCandidate, ZoneSelection
from eightball.optimize.clash import Candidate, ClashTable, make_candidate
from eightball.optimize.hub import HubContext, ranked_loops
from eightball.optimize.loops import enumerate_loops
from eightball.optimize.zones import Zone, enumerate_zones, zone_rooms
from eightball.routing.astar import HananRouter

COST_DECIMALS = 3  # zone costs are rounded to 1/1000 J so exhaustive search and CP-SAT compare equal sums


@dataclass
class ZoneData:
    zone: Zone
    cands: list[Candidate]          # ranked loops with hubs, cheapest first (at most TOPK_LOOPS)

    @property
    def cost(self) -> float:
        return round(self.cands[0].J, COST_DECIMALS)


# ---- step 0: costs of every zone ----------------------------------------------------------------

def build_zone_data(cp: CleanPlan, router: HananRouter, ctx: HubContext, zones: list[Zone],
                    deadline: float | None = None) -> list[ZoneData]:
    """Loops + hubs for every zone; zones with no routable loop or no legal hub site are left out."""
    data = []
    for z in sorted(zones, key=lambda z: (z.n_nodes, z.zone_id)):
        if deadline is not None and time.perf_counter() > deadline and data:
            break
        ranked = ranked_loops(ctx, enumerate_loops(cp, router, z.room_ids))
        cands = [make_candidate(cp, f"{z.zone_id}#{k}", rl) for k, rl in enumerate(ranked)]
        if cands:
            cands.sort(key=lambda c: (c.J, c.cid))
            data.append(ZoneData(z, cands))
    return data


def to_zone_candidates(data: list[ZoneData]) -> list[ZoneCandidate]:
    return [ZoneCandidate(zone_id=d.zone.zone_id, room_ids=frozenset(d.zone.room_ids), area_m2=d.zone.area_m2,
                          n_nodes=d.zone.n_nodes, cost=d.cost) for d in data]


# ---- step 2: splits -------------------------------------------------------------------------------

def covers(rooms: list[str], zones: list[tuple[int, float, object]], hubs: int, limit: int | None = None):
    """Yield every set of ``hubs`` zones that covers each room exactly once.

    zones: (room bit mask, area, payload). Rooms are bit k = rooms[k]. At most ``limit`` covers are produced.
    """
    full = (1 << len(rooms)) - 1
    by_low: dict[int, list[tuple[int, float, object]]] = {}
    for mask, area, payload in zones:
        by_low.setdefault((mask & -mask).bit_length() - 1, []).append((mask, area, payload))
    n_zone_rooms = int(config.MAX_NODES_PER_HUB)
    max_area = float(config.MAX_AREA_M2)
    count = 0
    areas = {}
    for mask, area, _ in zones:
        areas[mask] = area

    def rec(remaining: int, chosen: list, left: int):
        nonlocal count
        if limit is not None and count >= limit:
            return
        if remaining == 0:
            count += 1
            yield list(chosen)
            return
        if left == 0:
            return
        if math.ceil(bin(remaining).count("1") / n_zone_rooms) > left:
            return
        low = (remaining & -remaining).bit_length() - 1
        for mask, area, payload in by_low.get(low, []):
            if mask & ~remaining:
                continue
            chosen.append((mask, area, payload))
            yield from rec(remaining & ~mask, chosen, left - 1)
            chosen.pop()

    yield from rec(full, [], hubs)


def fewest_hub_covers(rooms: list[str], data: list[ZoneData], min_hubs: int, limit: int | None
                      ) -> tuple[int, list[list[ZoneData]], list[str]]:
    """(hubs, covers at that hub count, notes). Starts at the lower bound and adds hubs until a cover exists."""
    index = {r: k for k, r in enumerate(rooms)}
    zones = [(sum(1 << index[r] for r in d.zone.room_ids), d.zone.area_m2, d) for d in data]
    notes: list[str] = []
    for hubs in range(max(1, min_hubs), len(rooms) + 1):
        found = [[p for _, _, p in cov] for cov in covers(rooms, zones, hubs, limit)]
        if found:
            if hubs > min_hubs:
                notes.append(f"no split into {min_hubs} zone(s) exists (doors, passages, the 100 m2 / 5 node limits or "
                             f"hub sites): {hubs} hubs used")
            return hubs, found, notes
    return 0, [], notes + ["no split covers every room"]


# ---- the zone solver (additive cost, for the CP-SAT cross-check) ---------------------------------------

class ExhaustiveZoneSolver:
    """ZoneSolver by exhaustive search: the fewest hubs, then the lowest summed zone cost (clashes ignored)."""

    def select(self, rooms: list[str], candidates: list[ZoneCandidate], min_hubs: int, time_limit_s: float
               ) -> ZoneSelection:
        index = {r: k for k, r in enumerate(rooms)}
        zones = [(sum(1 << index[r] for r in c.room_ids), c.area_m2, c) for c in candidates]
        deadline = time.perf_counter() + time_limit_s
        for hubs in range(max(1, min_hubs), len(rooms) + 1):
            best, best_key, timed_out = None, None, False
            for cov in covers(rooms, zones, hubs):
                if time.perf_counter() > deadline:
                    timed_out = True
                    break
                cands = [p for _, _, p in cov]
                cost = round(sum(c.cost for c in cands), COST_DECIMALS)
                areas = [c.area_m2 for c in cands]
                key = (cost, round(max(areas) - min(areas), 6), sorted(c.zone_id for c in cands))
                if best_key is None or key < best_key:
                    best, best_key = cands, key
            if best is not None:
                return ZoneSelection(zone_ids=sorted(c.zone_id for c in best), hubs=hubs, cost=best_key[0],
                                     bound=best_key[0], optimal=not timed_out)
            if timed_out:
                break
        return ZoneSelection(zone_ids=[], hubs=0, cost=float("inf"), bound=None, optimal=False)


def load_backup_solver():
    """The CP-SAT backup, imported lazily by name (ZONE_SOLVER_BACKUP); None if it isn't available."""
    name = str(config.ZONE_SOLVER_BACKUP)
    try:
        module = importlib.import_module(f"eightball.optimize.{name}")
        cls = next(getattr(module, a) for a in dir(module) if a.lower().endswith("zonesolver") and a != "ZoneSolver")
        return cls()
    except (ImportError, StopIteration, NotImplementedError):
        return None


# ---- step 3: mixes ------------------------------------------------------------------------------------

@dataclass
class Solution:
    cands: list[Candidate]
    J: float
    area_gap: float
    hubs: int
    exact: dict = field(default_factory=dict)


def _area_gap(cands: list[Candidate], zone_area: dict[frozenset, float]) -> float:
    areas = [zone_area[c.rooms] for c in cands]
    return round(max(areas) - min(areas), 6)


def best_mix(table: ClashTable, split: list[ZoneData], zone_area, deadline: float | None = None
             ) -> tuple[list[Candidate], float] | None:
    """The best loop choice for every zone of a split, by exact J. None if the split has no candidate."""
    if any(not d.cands for d in split):
        return None
    zones = [d.cands for d in split]
    # a zone is free if none of its candidates clash with any candidate of another zone
    free = []
    for i, cs in enumerate(zones):
        clash = any(table.pair_cost(a, b) > 0 for j, other in enumerate(zones) if j != i for a in cs for b in other)
        free.append(not clash)
    pools = [[cs[0]] if free[i] else cs for i, cs in enumerate(zones)]
    size = math.prod(len(p) for p in pools)
    if size <= int(config.MAX_MIXES):
        mixes = [tuple(m) for m in itertools.product(*pools)]
    else:  # beam search on the additive cost
        beam: list[tuple[float, tuple[Candidate, ...]]] = [(0.0, ())]
        for pool in pools:
            nxt = []
            for _, partial in beam:
                for c in pool:
                    mix = partial + (c,)
                    nxt.append((table.mix_cost(mix), mix))
            nxt.sort(key=lambda t: (t[0], [c.cid for c in t[1]]))
            beam = nxt[:int(config.BEAM_WIDTH)]
        mixes = [m for _, m in beam]
    scored = table.rescore(mixes, keep=10)
    if not scored:
        return None
    J, mix = scored[0]
    return list(mix), J


def run_ladder(cp: CleanPlan, router: HananRouter, ctx: HubContext, deadline: float) -> tuple[Solution | None, dict]:
    """Steps 2-4. Returns the best solution found (or None) and a report: counts, notes, additive best cost, floor."""
    t_start = time.perf_counter()
    half = t_start + (deadline - t_start) / 2
    rooms = zone_rooms(cp)
    report: dict = {"notes": [], "splits": 0, "mixes_tried": 0}
    if not rooms:
        return None, report
    zones = enumerate_zones(cp, rooms)
    data = build_zone_data(cp, router, ctx, zones, deadline=half)
    report["zones"] = len(zones)
    report["zones_with_loops"] = len(data)
    if len(data) < len(zones):
        report["notes"].append(f"{len(zones) - len(data)} zone(s) left out (no routable loop / no legal hub site"
                               + (" / out of time)" if time.perf_counter() > half else ")"))
    min_hubs = min_hub_bound(cp, rooms)
    report["min_hubs_bound"] = min_hubs
    hubs, splits, notes = fewest_hub_covers(rooms, data, min_hubs, int(config.MAX_SPLITS) + 1)
    report["notes"] += notes
    if not splits:
        return None, report
    report["hubs"] = hubs
    over_limit = len(splits) > int(config.MAX_SPLITS)
    use_backup = over_limit or time.perf_counter() > half
    if use_backup:
        sel = _backup_split(rooms, data, min_hubs, deadline - time.perf_counter())
        if sel is not None:
            by_id = {d.zone.zone_id: d for d in data}
            splits = [[by_id[z] for z in sel.zone_ids]]
            report["notes"].append("split chosen by the backup solver")
            report["backup_used"] = True
        elif over_limit:
            splits = splits[:int(config.MAX_SPLITS)]
            report["notes"].append("backup solver unavailable: only the first MAX_SPLITS splits tried")
    report["splits"] = len(splits)

    exact = ExhaustiveZoneSolver().select(rooms, to_zone_candidates(data), min_hubs, max(1.0, deadline - time.perf_counter()))
    report["best_additive_cost"] = exact.cost if exact.hubs == hubs else None
    report["additive_optimal"] = exact.optimal

    table = ClashTable(cp)
    zone_area = {frozenset(d.zone.room_ids): d.zone.area_m2 for d in data}
    best: Solution | None = None
    splits.sort(key=lambda s: sum(d.cost for d in s))
    for split in splits:
        if time.perf_counter() > deadline and best is not None:
            report["notes"].append("time budget reached: best so far returned")
            break
        floor = sum(d.cost for d in split)  # clashes only add cost: this split can't do better than its floor
        if best is not None and floor > best.J + 1e-6:
            break  # splits are sorted by floor: none of the rest can beat the best
        mix = best_mix(table, split, zone_area, deadline)
        report["mixes_tried"] += 1
        if mix is None:
            continue
        cands, J = mix
        sol = Solution(cands, J, _area_gap(cands, zone_area), hubs)
        if best is None or (round(sol.J, 6), sol.area_gap) < (round(best.J, 6), best.area_gap):
            best = sol
    if best is not None and time.perf_counter() < deadline:  # step 5: polish with the time left
        from eightball.optimize import polish as polish_mod
        cands, prep = polish_mod.polish(cp, router, ctx, best.cands, table, deadline)
        report["polish"] = prep
        if prep["J_after"] < best.J - 1e-9:
            best = Solution(cands, prep["J_after"], best.area_gap, best.hubs)
    report["J_floor"] = report.get("best_additive_cost")
    return best, report


def _backup_split(rooms, data, min_hubs, time_left) -> ZoneSelection | None:
    solver = load_backup_solver()
    if solver is None:
        return None
    try:
        sel = solver.select(rooms, to_zone_candidates(data), min_hubs, max(1.0, time_left / 2))
    except NotImplementedError:
        return None
    return sel if sel.zone_ids else None


def min_hub_bound(cp: CleanPlan, rooms: list[str]) -> int:
    area = sum(cp.rooms[r].area_m2 for r in rooms)
    return max(math.ceil(area / float(config.MAX_AREA_M2) - 1e-9), math.ceil(len(rooms) / int(config.MAX_NODES_PER_HUB)))
