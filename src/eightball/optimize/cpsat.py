"""CP-SAT ZoneSolver (Person B, step B6 / handoff S3.1, 6.2).

Set partitioning over the candidate zones:
  * one boolean per candidate zone; every room covered by exactly one chosen zone;
  * solve 1 minimises the number of zones (hubs), never below `min_hubs`;
  * solve 2 fixes that count and minimises the summed zone cost (best loop J + hub cost).
Costs are additive, so clashes between loops are invisible here; the ladder's later steps score them.
Because clashes only add cost, solve 2's bound is a valid floor within our model.

Imports only eightball.core contracts and config: never the exhaustive solver's code.
"""
from __future__ import annotations

import math

from ortools.sat.python import cp_model

from eightball import config
from eightball.core.contracts import ZoneCandidate, ZoneSelection

COST_SCALE = 1000  # costs are rounded to 1/1000 J for the integer model


class CpSatZoneSolver:
    name = "cpsat"

    def __init__(self, workers: int | None = None):
        self.workers = workers
        self.last_stats: dict = {}

    def _solver(self, time_limit_s: float, n_vars: int) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(0.01, float(time_limit_s))
        solver.parameters.random_seed = int(config.SEED)
        # One worker keeps small instances deterministic; large ones use parallel search.
        solver.parameters.num_workers = self.workers or (1 if n_vars < 2000 else 8)
        return solver

    def _model(self, rooms: list[str], cands: list[ZoneCandidate]):
        model = cp_model.CpModel()
        x = [model.new_bool_var(f"z{i}") for i in range(len(cands))]
        by_room: dict[str, list] = {r: [] for r in rooms}
        for var, cand in zip(x, cands):
            for r in cand.room_ids:
                by_room[r].append(var)
        for vars_ in by_room.values():
            if vars_:
                model.add_exactly_one(vars_)
            else:
                model.add_bool_or([])  # no candidate covers this room: infeasible
        return model, x

    def select(self, rooms: list[str], candidates: list[ZoneCandidate],
               min_hubs: int, time_limit_s: float, hubs: int | None = None) -> ZoneSelection:
        """The fewest hubs, then the cheapest split. With ``hubs`` set (the trade-off view), the hub count is fixed
        to exactly that many and the cheapest split with that count is returned (solve 1 is skipped)."""
        room_set = set(rooms)
        cands = [c for c in candidates if c.room_ids and c.room_ids <= room_set]
        n_vars = len(cands)
        stats = {"candidates": n_vars, "dropped": len(candidates) - n_vars}

        if hubs is not None:
            h_star, hubs_proven, time_split = int(hubs), True, 1.0
            stats["solve1"] = "skipped (hubs fixed)"
        else:
            # Solve 1: fewest hubs.
            model, x = self._model(rooms, cands)
            hubs_var = sum(x)
            model.add(hubs_var >= max(0, int(min_hubs)))
            model.minimize(hubs_var)
            solver = self._solver(0.4 * time_limit_s, n_vars)
            status1 = solver.solve(model)
            stats["solve1"] = solver.status_name(status1)
            if status1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                self.last_stats = stats
                return ZoneSelection(zone_ids=[], hubs=0, cost=math.inf, bound=None, optimal=False)
            h_star = int(round(solver.objective_value))
            hubs_proven = status1 == cp_model.OPTIMAL
            time_split = 0.6

        # Solve 2: cheapest split with that many hubs.
        model, x = self._model(rooms, cands)
        model.add(sum(x) == h_star)
        costs = [int(round(c.cost * COST_SCALE)) for c in cands]
        model.minimize(sum(cost * var for cost, var in zip(costs, x)))
        solver = self._solver(time_split * time_limit_s, n_vars)
        status2 = solver.solve(model)
        stats["solve2"] = solver.status_name(status2)
        stats["wall_time_s"] = solver.wall_time
        self.last_stats = stats
        if status2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return ZoneSelection(zone_ids=[], hubs=h_star, cost=math.inf, bound=None, optimal=False)
        chosen = [c for c, var in zip(cands, x) if solver.value(var)]
        return ZoneSelection(
            zone_ids=sorted(c.zone_id for c in chosen),
            hubs=h_star,
            cost=sum(c.cost for c in chosen),
            bound=solver.best_objective_bound / COST_SCALE,
            optimal=hubs_proven and status2 == cp_model.OPTIMAL,
        )
