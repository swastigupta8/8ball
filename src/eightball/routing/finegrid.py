"""Fine-grid path-quality check vs the Hanan grid (handoff S2.2); reports V%.

For every pair of nodes that can be joined inside the building, compares the cheapest Hanan-grid path with the
cheapest path on a FINE_GRID_M raster (default 1 cm; the raster router keeps the exact endpoints). V% is the share of
pairs where the raster finds a path cheaper by more than 1 mm, i.e. where the track grid misses something.

Usage: python -m eightball finegrid --split train --limit 50 [--out report.json]
Set EIGHTBALL_FINE_GRID_M=0.02 for a quicker, coarser check.

Owner: Person A, step A6 (docs/BUILD_SPLIT.md).
"""
from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing as mp
import time
from pathlib import Path

import networkx as nx

from eightball import config
from eightball.geometry import build_clean_plan
from eightball.io import resplan
from eightball.routing.astar import INF, HananRouter
from eightball.routing.crude import CrudeRouter

TOL_M = 0.001  # the raster must beat Hanan by more than 1 mm to count


def node_pairs(cp):
    """Pairs of nodes whose rooms are joined by doors/passages without leaving the building."""
    inside = [k for k, v in cp.rooms.items() if v.poly.intersection(cp.inner).area >= 0.5 * v.poly.area]
    comp: dict[str, int] = {}
    for k, c in enumerate(nx.connected_components(cp.links.subgraph(inside))):
        comp.update({x: k for x in c})
    return [(a.id, b.id) for a, b in itertools.combinations(cp.nodes.values(), 2)
            if a.room_id in comp and b.room_id in comp and comp[a.room_id] == comp[b.room_id]]


def compare_plan(plan_id: int, cell_m: float | None = None) -> dict:
    cell_m = float(config.FINE_GRID_M if cell_m is None else cell_m)
    cp = build_clean_plan(resplan.get_plan(plan_id))
    hanan, fine = HananRouter(cp), CrudeRouter(cp, cell_m=cell_m)
    allowed = frozenset(cp.rooms)
    rows = []
    for a, b in node_pairs(cp):
        ch, _ = hanan.shortest(allowed, a, b)
        cf, _ = fine.shortest(allowed, a, b)
        rows.append({"plan": plan_id, "a": a, "b": b, "hanan": ch, "fine": cf})
    return {"plan": plan_id, "pairs": rows}


def _work(args):
    return compare_plan(*args)


def summarise(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["hanan"] < INF and r["fine"] < INF]
    worse = [r for r in ok if r["fine"] < r["hanan"] - TOL_M]
    gaps = [r["hanan"] - r["fine"] for r in worse]
    return {"pairs": len(rows), "compared": len(ok), "no_hanan_path": sum(r["hanan"] == INF for r in rows),
            "no_fine_path": sum(r["fine"] == INF for r in rows), "hanan_worse": len(worse),
            "V_percent": 100.0 * len(worse) / len(ok) if ok else 0.0,
            "mean_gap_m": sum(gaps) / len(gaps) if gaps else 0.0, "max_gap_m": max(gaps, default=0.0),
            "worst": sorted(worse, key=lambda r: r["fine"] - r["hanan"])[:10]}


def cli_main(args: argparse.Namespace) -> int:
    ids = resplan.split_ids(args.split)
    ids = ids[:args.limit] if args.limit else ids
    cell = float(config.FINE_GRID_M)
    t0 = time.time()
    with mp.Pool(min(len(ids), max(1, (mp.cpu_count() or 2) - 2))) as pool:
        results = pool.map(_work, [(pid, cell) for pid in ids], chunksize=1)
    rows = [r for res in results for r in res["pairs"]]
    report = summarise(rows)
    report.update({"split": args.split, "plans": len(ids), "cell_m": cell, "seconds": round(time.time() - t0, 1)})
    out = Path(args.out) if args.out else Path(str(config.DATA_DIR)) / "out" / "finegrid.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{report['plans']} plans, {report['compared']} node pairs at {cell * 100:.0f} cm: "
          f"V = {report['V_percent']:.2f}% (Hanan worse by > 1 mm), mean gap {report['mean_gap_m'] * 1000:.1f} mm, "
          f"max gap {report['max_gap_m']:.3f} m, no path: hanan {report['no_hanan_path']} / fine "
          f"{report['no_fine_path']}  [{report['seconds']} s] -> {out}")
    return 0
