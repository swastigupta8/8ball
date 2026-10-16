"""Check an answer produced for an uploaded floor plan: is it valid, are the numbers right, is it (near) optimal?

    python scripts/check_upload_result.py original_test_plan/floor_plan_input.json [data/out/api/<id>/answer.json] [--no-wide]

The first file is the input you uploaded (the body of POST /api/solve: {"plan": ..., "nodes": [...]}); the second is the
answer you downloaded (default: data/out/api/<plan id>/answer.json, where every solve is saved). It prints
  1. the answer's hubs and rings;
  2. the metrics recomputed from the polylines (core.metrics) against the ones in the file;
  3. the independent checker's verdict (evaluate.checker);
  4. every legal split into the fewest hubs, each with its best total J, and the lower bound of the best one;
  5. a far wider search (top-20 loops, every routing order, 3 crossing penalties, 8 polish passes), unless --no-wide;
  6. CP-SAT against the exhaustive zone search on the same zone costs.
Nothing is written. "Near optimal" means: close to what a much slower search finds. Hub count is a proven minimum
only given the doors and passages we detect.
"""
from __future__ import annotations

import itertools
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eightball import config  # noqa: E402
from eightball.api import server  # noqa: E402
from eightball.core import metrics  # noqa: E402
from eightball.evaluate import checker  # noqa: E402
from eightball.geometry import build_clean_plan  # noqa: E402
from eightball.optimize import ladder, loops, pipeline, polish  # noqa: E402
from eightball.optimize.clash import ClashTable  # noqa: E402
from eightball.optimize.hub import HubContext  # noqa: E402
from eightball.optimize.zones import enumerate_zones, zone_rooms  # noqa: E402
from eightball.routing.astar import HananRouter  # noqa: E402


def rounded(d: dict) -> dict:
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items() if k != "per_hub"}


def wide_build_legs(cp, router, allowed, order, h_out, h_in, retrace, room_of, scale):
    """loops._build_legs, but tries every routing order of the legs and three crossing penalties."""
    n = len(order)
    best = None

    def consider(legs):
        nonlocal best
        if legs is None or loops._illegal_overlap(cp, legs, order, retrace, room_of, scale) != 0:
            return
        j = loops._score(cp, order, legs)["J"]
        if best is None or j < best[0] - 1e-9:
            best = (j, legs)

    legs = [router.cost(allowed, order[k], h_out[k], order[(k + 1) % n], h_in[(k + 1) % n])[1] for k in range(n)]
    if not any(not leg for leg in legs):
        consider(legs)
    if n >= 2:
        node_vertices = {router.vertex_of(v) for v in order}
        for seq in itertools.permutations(range(n)):
            for penalty in (5.0, 2.0, 12.0):
                loops.CROSS = penalty
                consider(loops._route_in_turn(cp, router, allowed, order, h_out, h_in, retrace, room_of, list(seq),
                                              node_vertices))
        loops.CROSS = 5.0
    return best[1] if best else None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    body = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    plan = server.plan_from_payload(body["plan"])
    nodes = body.get("nodes")
    answer_path = Path(args[1]) if len(args) > 1 else ROOT / "data" / "out" / "api" / str(plan["id"]) / "answer.json"
    answer = json.loads(answer_path.read_text(encoding="utf-8"))

    print(f"== 1. the answer file  ({answer_path})")
    print("schema", answer["schema_version"], "| plan", answer["plan_id"], "| solver", answer["meta"]["solver"],
          "| warnings", answer["meta"].get("warnings"))
    for h in answer["hubs"]:
        print(f"  {h['hub_id']}: rooms {h['room_ids']}  area {h['area_m2']:.1f} m2  {' -> '.join(h['sequence'])}  "
              f"length {h['length_m']:.2f} m")

    print("== 2. metrics recomputed from the polylines (core.metrics)")
    res = metrics.score(answer, answer["scale"])
    print("recomputed:", rounded(res))
    print("in the file:", rounded(answer["metrics"]))

    print("== 3. independent checker")
    chk = checker.check(plan, answer, nodes)
    print("valid:", chk["valid"], "| violations:", chk["violations"], "| its metrics:", rounded(chk["metrics"]))

    print("== 4. every way to split the rooms into the fewest hubs")
    cp = build_clean_plan(plan, nodes)
    router = HananRouter(cp)
    ctx = HubContext(cp, router)
    rooms = zone_rooms(cp)
    zones = enumerate_zones(cp, rooms)
    data = ladder.build_zone_data(cp, router, ctx, zones)
    min_hubs = ladder.min_hub_bound(cp, rooms)
    hubs, splits, _notes = ladder.fewest_hub_covers(rooms, data, min_hubs, 100000)
    area = sum(cp.rooms[r].area_m2 for r in rooms)
    print(f"lower bound {min_hubs} hub(s) (area {area:.1f} m2, {len(rooms)} nodes); fewest found: {hubs}; "
          f"legal splits at that count: {len(splits)}; zones priced {len(data)} of {len(zones)}")
    table = ClashTable(cp)
    zone_area = {frozenset(d.zone.room_ids): d.zone.area_m2 for d in data}
    rows = []
    for split in splits[:200]:
        mix = ladder.best_mix(table, split, zone_area)
        if mix:
            rows.append((mix[1], [sorted(d.zone.room_ids) for d in split]))
    rows.sort(key=lambda r: r[0])
    for J, split in rows[:8]:
        print(f"  J {J:8.3f}   " + "  |  ".join(str(s) for s in split))
    if splits:
        print("floor of the best split (every leg at its cheapest, no turns or hub):",
              round(min(sum(d.floor for d in sp) for sp in splits), 3))

    if "--no-wide" not in sys.argv:
        print("== 5. much wider search")
        t = time.time()
        normal = pipeline.solve(plan, nodes, "exact").answer
        t_normal = time.time() - t
        original = (loops._build_legs, polish.polish)
        loops._build_legs = wide_build_legs
        previous = config.override(TOPK_LOOPS=20, TIME_BUDGET_S=600.0, MAX_MIXES=200_000)
        polish.polish = lambda *a, **k: original[1](*a, **{**k, "max_passes": 8})
        t = time.time()
        try:
            wide = pipeline.solve(plan, nodes, "exact").answer
        finally:
            loops._build_legs, polish.polish = original
            config.override(**previous)
        t_wide = time.time() - t
        gap = normal["metrics"]["J"] - wide["metrics"]["J"]
        print(f"normal solve: hubs {normal['metrics']['H']}  J {normal['metrics']['J']:.3f}  ({t_normal:.1f} s)")
        print(f"wide search : hubs {wide['metrics']['H']}  J {wide['metrics']['J']:.3f}  ({t_wide:.1f} s)  "
              f"-> {gap:.3f} lower ({100 * gap / normal['metrics']['J']:.2f}%)")

    print("== 6. CP-SAT (second solver) on the same zone costs")
    rooms2, cands = pipeline.zone_candidates(plan, nodes)
    exact = ladder.ExhaustiveZoneSolver().select(rooms2, cands, min_hubs, 60.0)
    backup = ladder.load_backup_solver()
    cpsat = backup.select(rooms2, cands, min_hubs, 60.0) if backup else None
    print("exhaustive:", exact.hubs, "hubs, cost", exact.cost, "|",
          "CP-SAT:" if cpsat else "CP-SAT not available",
          f"{cpsat.hubs} hubs, cost {cpsat.cost}, {'proven optimal' if cpsat.optimal else 'not proven'}" if cpsat else "")
    ok = chk["valid"] and abs(res["J"] - answer["metrics"]["J"]) < 1e-6
    print("\nRESULT:", "answer is valid and its numbers are right" if ok else "PROBLEM: see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
