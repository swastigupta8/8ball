"""Plan gallery (Person B, step B10): pick ~12 real test plans worth showing and export viewer bundles.

    python -m eightball.bench.gallery [--split test] [--size 12] [--solver exact]

Picks a spread: plans needing 1, 2 and 3+ hubs, plus "tricky" ones (open kitchen-living passages,
many single-door rooms, multi-part living rooms). If Person A's solver is built, each plan is solved
and checked; otherwise the bundle has the plan and its nodes only. Writes web/data/gallery/<id>/ and
web/data/gallery/index.json (git-ignored: it's derived from the dataset).
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from eightball import config
from eightball.evaluate import geom_indep
from eightball.io import nodes as nodes_io, resplan
from eightball.viz.export import export_bundle

OUT = Path("web/data/gallery")


def describe(plan: dict) -> dict:
    """Facts used to pick and label gallery plans."""
    g = geom_indep.build(plan)
    rooms = sorted(g.eligible)
    area = sum(g.area_m2[r] for r in rooms)
    lb = max(math.ceil(area / float(config.MAX_AREA_M2) - 1e-9), math.ceil(len(rooms) / int(config.MAX_NODES_PER_HUB)))
    passages = [(g.room_type[a], g.room_type[b]) for a, b, d in g.links.edges(data=True) if d["kind"] == "passage"]
    tags = []
    if any(set(p) == {"kitchen", "living"} for p in passages):
        tags.append("open kitchen")
    single = sum(1 for r in rooms if g.degree(r) == 1)
    if single >= 3:
        tags.append(f"{single} single-door rooms")
    if sum(1 for r in rooms if g.room_type[r] == "living") > 1:
        tags.append("split living room")
    isolated = [r for r in rooms if g.degree(r) == 0]
    return {"plan_id": int(plan["id"]), "rooms": len(rooms), "area_m2": round(area, 1), "min_hubs": lb,
            "tags": tags, "isolated": len(isolated)}


def pick(split: str = "test", size: int = 12, seed: int | None = None, pool: int = 400) -> list[dict]:
    rng = random.Random(int(config.SEED) if seed is None else seed)
    ids = resplan.split_ids(split)
    candidates = []
    for pid in rng.sample(ids, min(pool, len(ids))):
        plan = resplan.get_plan(pid)
        if resplan.scale_is_suspicious(resplan.scale(plan)):
            continue
        try:
            d = describe(plan)
        except Exception:
            continue
        if d["isolated"] or d["rooms"] < 2:
            continue  # unreachable rooms can't be zoned; not gallery material
        candidates.append(d)
    want = {1: size // 3, 2: size // 3, 3: size - 2 * (size // 3)}
    chosen: list[dict] = []
    for hubs, n in want.items():
        bucket = [c for c in candidates if (c["min_hubs"] >= 3 if hubs == 3 else c["min_hubs"] == hubs)]
        bucket.sort(key=lambda c: (-len(c["tags"]), -c["rooms"], c["plan_id"]))
        picked, seen = [], set()
        for c in bucket:  # first pass: one plan per (room count, tags) look, for variety
            sig = (c["rooms"], tuple(c["tags"]))
            if sig not in seen and len(picked) < n:
                picked.append(c)
                seen.add(sig)
        picked += [c for c in bucket if c not in picked][: n - len(picked)]
        chosen += picked
    return chosen


def _solver_ready() -> bool:
    from eightball.optimize import pipeline

    try:
        pipeline.solve({}, [], solver="greedy")
    except NotImplementedError:
        return False
    except Exception:
        return True
    return True


def build(split: str = "test", size: int = 12, solver: str = "exact", seed: int | None = None) -> list[dict]:
    from eightball.optimize import pipeline

    ready = _solver_ready()
    entries = []
    for d in pick(split, size, seed):
        plan = resplan.get_plan(d["plan_id"])
        nodes = nodes_io.get_nodes(plan, "center")
        answer = branching = heatmaps = None
        if ready:
            try:
                result = pipeline.solve(plan, nodes, solver=solver)
                answer, branching, heatmaps = result.answer, result.branching or None, result.heatmaps or None
            except Exception as exc:  # keep the plan in the gallery, without an answer
                d["error"] = f"{type(exc).__name__}: {exc}"
        folder = OUT / str(d["plan_id"])
        export_bundle(plan, folder, answer, nodes, branching, heatmaps)
        label = f"Plan {d['plan_id']} · {d['rooms']} rooms · {d['min_hubs']}+ hub{'s' if d['min_hubs'] > 1 else ''}"
        if d["tags"]:
            label += " · " + ", ".join(d["tags"])
        check = json.loads((folder / "check.json").read_text(encoding="utf-8")) if answer else None
        entries.append({**d, "id": f"gallery_{d['plan_id']}", "label": label, "path": f"data/gallery/{d['plan_id']}",
                        "has_branching": bool(branching), "has_heatmap": bool(heatmaps),
                        "solved": answer is not None, "valid": check["valid"] if check else None,
                        "metrics": check["metrics"] if check else None})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.json").write_text(json.dumps({"split": split, "solver_ready": ready, "plans": entries}, indent=1),
                                    encoding="utf-8")
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eightball.bench.gallery")
    parser.add_argument("--split", default="test")
    parser.add_argument("--size", type=int, default=12)
    parser.add_argument("--solver", default="exact")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    entries = build(args.split, args.size, args.solver, args.seed)
    for e in entries:
        print(e["label"] + ("" if e["solved"] else "  (not solved yet)"))
    print(f"wrote {len(entries)} plans to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
