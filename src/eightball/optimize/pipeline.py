"""Solver facade (Person A, step A4; contract in docs/BUILD_SPLIT.md 3.1 item 7).

Person B calls only `solve` and `zone_candidates` from here (batch runner, API, stitched floors,
CP-SAT cross-check). Keep these signatures; change them only through a contract PR.
"""
from __future__ import annotations

import argparse
import math
import pickle
import time
from pathlib import Path

from eightball import config
from eightball.core import metrics
from eightball.core.contracts import (ANSWER_SCHEMA_VERSION, BRANCHING_SCHEMA_VERSION, CleanPlan, SolveResult,
                                      ZoneCandidate)
from eightball.geometry import build_clean_plan
from eightball.io import answer_io, nodes as nodes_io, resplan
from eightball.optimize import greedy
from eightball.routing.crude import CrudeRouter


def min_hubs_bound(cp: CleanPlan) -> int:
    rooms = [r for r in cp.rooms.values() if r.eligible]
    if not rooms:
        return 0
    area = sum(r.area_m2 for r in rooms)
    return max(math.ceil(area / float(config.MAX_AREA_M2) - 1e-9), math.ceil(len(rooms) / int(config.MAX_NODES_PER_HUB)))


def build_answer(cp: CleanPlan, rings: list[dict], solver: str, runtime_s: float, warnings: list[str] | None = None
                 ) -> dict:
    """Assemble the answer JSON (handoff 7.1) from rings: {"zone", "hub", "hub_room", "order", "legs"}."""
    node_list = [{"node_id": n.id, "room_id": n.room_id, "point": [n.point[0], n.point[1]]}
                 for n in sorted(cp.nodes.values(), key=lambda n: int(n.id[1:]))]
    hubs = []
    for k, ring in enumerate(rings, start=1):
        hid = f"H{k}"
        seq = [hid, *ring["order"], hid]
        hubs.append({
            "hub_id": hid, "point": [ring["hub"][0], ring["hub"][1]], "room_id": ring["hub_room"],
            "room_ids": sorted(ring["zone"]), "node_ids": sorted(ring["order"], key=lambda n: int(n[1:])),
            "sequence": seq,
            "legs": [{"from": seq[i], "to": seq[i + 1], "polyline": [[p[0], p[1]] for p in poly]}
                     for i, poly in enumerate(ring["legs"])],
            "area_m2": sum(cp.rooms[r].area_m2 for r in ring["zone"]), "length_m": 0.0})
    answer = {"schema_version": ANSWER_SCHEMA_VERSION, "plan_id": cp.plan_id, "scale": cp.scale, "nodes": node_list,
              "hubs": hubs, "metrics": {}, "meta": {}}
    result = metrics.score(answer, cp.scale)
    for hub in hubs:
        hub["length_m"] = result["per_hub"][hub["hub_id"]]["L"]
    answer["metrics"] = {"H": len(hubs), "L": result["L"], "X": result["X"], "O": result["O"], "B": result["B"],
                         "J": result["J"]}
    answer["meta"] = {"solver": solver, "runtime_s": runtime_s, "config_hash": config.config_hash(),
                      "seed": int(config.SEED), "best_additive_cost": None, "min_hubs_bound": min_hubs_bound(cp),
                      "j_floor": None}
    if warnings:
        answer["meta"]["warnings"] = list(warnings)
    if cp.flags:
        answer["meta"]["flags"] = list(cp.flags)
    return answer


def _branching(cp: CleanPlan, router: CrudeRouter, rings: list[dict]) -> dict:
    hubs = []
    for k, ring in enumerate(rings, start=1):
        allowed = router.allowed_rooms_for(ring["zone"])
        paths = router.branching_tree(allowed, ring["hub"], list(ring["order"]))
        hubs.append({"hub_id": f"H{k}", "point": [ring["hub"][0], ring["hub"][1]],
                     "paths": {n: [[p[0], p[1]] for p in poly] for n, poly in sorted(paths.items())}})
    doc = answer_io.make_branching(cp.plan_id, hubs)
    return doc if not answer_io.branching_errors(doc) else {"schema_version": BRANCHING_SCHEMA_VERSION,
                                                              "plan_id": cp.plan_id, "hubs": []}


def solve(plan_raw: dict, nodes: list[dict], solver: str = "exact") -> SolveResult:
    """Solve one plan. solver: 'greedy' | 'exact'. Never returns without an answer (greedy first).

    Until the exact solver lands (A11) 'exact' returns the greedy answer and says so in meta.solver.
    """
    t0 = time.perf_counter()
    cp = build_clean_plan(plan_raw, nodes)
    router = CrudeRouter(cp)
    rings, warnings = greedy.solve_zones(cp, router)
    label = "greedy"
    if solver not in ("greedy", "exact"):
        raise ValueError(f"unknown solver {solver!r}")
    if solver == "exact":
        warnings.append("exact_solver_not_built: returned the greedy answer")
    answer = build_answer(cp, rings, label, time.perf_counter() - t0, warnings)
    branching = _branching(cp, router, rings)
    answer["meta"]["runtime_s"] = time.perf_counter() - t0
    return SolveResult(answer=answer, heatmaps=[], branching=branching, runtime_s=answer["meta"]["runtime_s"])


def zone_candidates(plan_raw: dict, nodes: list[dict]) -> tuple[list[str], list[ZoneCandidate]]:
    """(eligible room ids, every legal zone with its additive cost) for the CP-SAT cross-check."""
    raise NotImplementedError("zone candidates: Person A, step A7")


def _load_plan(args: argparse.Namespace) -> dict:
    if getattr(args, "plan_file", None):
        with open(args.plan_file, "rb") as fh:
            return resplan.normalize_keys(pickle.load(fh))
    if args.plan_id is None:
        raise SystemExit("solve needs --plan-id or --plan-file")
    try:
        from tests.fixtures import synthetic
        if args.plan_id in synthetic.PLANS:
            return synthetic.PLANS[args.plan_id]()
    except ImportError:
        pass
    return resplan.get_plan(args.plan_id)


def cli_main(args: argparse.Namespace) -> int:
    """solve --plan-id ID [--nodes center|random|file] [--solver greedy|exact] [--out DIR]"""
    plan = _load_plan(args)
    mode = getattr(args, "nodes", "center")
    if mode == "file":
        if not getattr(args, "nodes_file", None):
            raise SystemExit("--nodes file needs --nodes-file")
        nodes = nodes_io.read_nodes_file(args.nodes_file)
    else:
        nodes = nodes_io.make_nodes(plan, mode)
    result = solve(plan, nodes, getattr(args, "solver", "exact"))
    out = Path(args.out) if getattr(args, "out", None) else Path(str(config.DATA_DIR)) / "out" / "solve" / str(plan["id"])
    answer_io.write_answer(out / "answer.json", result.answer)
    answer_io.write_branching(out / "branching.json", result.branching)
    for hm in result.heatmaps:
        answer_io.write_heatmap(out / f"heatmap_{hm['hub_id']}.json", hm)
    m = result.answer["metrics"]
    print(f"plan {plan['id']}: H={m['H']} L={m['L']:.2f} X={m['X']} O={m['O']:.2f} B={m['B']} J={m['J']:.2f} "
          f"({result.runtime_s:.2f}s, solver={result.answer['meta']['solver']}) -> {out}")
    for w in result.answer["meta"].get("warnings", []):
        print("  warning:", w)
    return 0
