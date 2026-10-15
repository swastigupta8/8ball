"""Data audit (Person B, step B1 / handoff S0.3): reproduce the handoff's section 3 facts.

    python -m eightball audit [--split train] [--limit 1500] [--out docs/data_facts.md]

Fast facts run over all 17,000 plans. Facts that need the door/passage graph (links, passages,
zones) run on a seeded random sample of --limit plans from --split, using the checker's own geometry.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from collections import Counter
from pathlib import Path

import shapely

from eightball import config
from eightball.evaluate import geom_indep
from eightball.io import resplan

GEOM_KEYS = ("living", "bedroom", "bathroom", "kitchen", "storage", "stair", "balcony", "door", "window",
             "wall", "front_door", "inner", "land", "garden", "pool", "parking")


def _valid(plan: dict, key: str):
    """make_valid geometry, or None when the key is missing, None or empty."""
    g = plan.get(key)
    if g is None or g.is_empty:
        return None
    return shapely.make_valid(g)


def _q(values, qs=(0.5, 0.95)):
    if not values:
        return {}
    vs = sorted(values)
    return {q: vs[min(len(vs) - 1, int(q * len(vs)))] for q in qs}


def _axis_share(geom, s: float) -> float:
    """Share of boundary length made of axis-aligned edges (within 1 mm per edge)."""
    tol = float(config.TOL_M) * s
    total = aligned = 0.0
    for poly in resplan.parts(geom):
        for ring in [poly.exterior, *poly.interiors]:
            xy = list(ring.coords)
            for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
                length = math.hypot(x2 - x1, y2 - y1)
                total += length
                if abs(x2 - x1) <= tol or abs(y2 - y1) <= tol:
                    aligned += length
    return aligned / total if total else 1.0


def fast_facts(plans) -> dict:
    """Facts that need only the raw geometry, over every plan."""
    scales, n_elig, area_elig, lower, area_binds, node_binds = [], [], [], Counter(), 0, 0
    invalid = Counter()
    storage_plans = multi_living = suspicious = big_room_plans = 0
    jagged = rooms_total = 0
    doors_total = doors_lt5 = doors_gt50 = plans_buried = 0
    axis_shares = []
    for plan in plans:
        s = resplan.scale(plan)
        scales.append(s)
        suspicious += resplan.scale_is_suspicious(s)
        for k in GEOM_KEYS:
            g = plan.get(k)
            if g is not None and not g.is_empty and not g.is_valid:
                invalid[k] += 1
        storage_plans += _valid(plan, "storage") is not None
        multi_living += len(resplan.parts(_valid(plan, "living"))) > 1
        rooms = resplan.room_parts(plan)
        elig = [(rid, t, p) for rid, t, p in rooms if t in resplan.ELIGIBLE]
        areas = [p.area / (s * s) for _r, _t, p in elig]
        n_elig.append(len(elig))
        total = sum(areas)
        area_elig.append(total)
        big_room_plans += any(a > 100 for a in areas)
        for _r, t, p in rooms:
            if t in geom_indep.OUTDOOR:
                continue  # the plot outline is almost always jagged; count indoor rooms only
            rooms_total += 1
            jagged += len(p.exterior.coords) - 1 > 30
        by_area, by_nodes = math.ceil(total / 100 - 1e-9), math.ceil(len(elig) / 5)
        lb = max(by_area, by_nodes, 1 if elig else 0)
        lower[lb] += 1
        area_binds += by_area > by_nodes
        node_binds += by_nodes > by_area
        wall = _valid(plan, "wall")
        buried = False
        for d in resplan.parts(_valid(plan, "door")):
            doors_total += 1
            cover = d.intersection(wall).area / d.area if wall is not None and d.area > 0 else 0.0
            doors_lt5 += cover < 0.05
            doors_gt50 += cover > 0.5
            buried = buried or cover > 0.5
        plans_buried += buried
        if wall is not None:
            axis_shares.append(_axis_share(wall, s))
    n = len(scales)
    return {
        "plans": n,
        "scale_median": statistics.median(scales),
        "scale_p05_p95": [_q(scales, (0.05,))[0.05], _q(scales)[0.95]],
        "suspicious_scale_plans": suspicious,
        "invalid_geometry": dict(invalid),
        "storage_plans": storage_plans,
        "multi_polygon_living_plans": multi_living,
        "eligible_rooms": {"median": statistics.median(n_elig), "p95": _q(n_elig)[0.95], "max": max(n_elig)},
        "eligible_area_m2": {"median": statistics.median(area_elig), "p95": _q(area_elig)[0.95]},
        "hub_lower_bound": {str(k): v for k, v in sorted(lower.items())},
        "area_binds_share": area_binds / n,
        "nodes_bind_share": node_binds / n,
        "plans_with_room_over_100m2": big_room_plans,
        "jagged_room_share": jagged / rooms_total if rooms_total else 0.0,
        "doors": {"total": doors_total, "lt5pct_wall_share": doors_lt5 / doors_total,
                  "gt50pct_wall_share": doors_gt50 / doors_total, "plans_with_buried_door": plans_buried},
        "axis_aligned": {"share_ge_99pct": sum(a >= 0.99 for a in axis_shares) / len(axis_shares),
                         "share_lt_90pct": sum(a < 0.90 for a in axis_shares) / len(axis_shares)},
    }


def count_zones(g: geom_indep.CheckGeom) -> int:
    """Connected sets of <= MAX_NODES eligible rooms with <= MAX_AREA, links within the set only."""
    elig = sorted(g.eligible)
    idx = {r: i for i, r in enumerate(elig)}
    nbr = {i: set() for i in range(len(elig))}
    for a, b in g.links.edges():
        if a in idx and b in idx and a != b:
            nbr[idx[a]].add(idx[b])
            nbr[idx[b]].add(idx[a])
    area = [g.area_m2[r] for r in elig]
    cap_n, cap_a = int(config.MAX_NODES_PER_HUB), float(config.MAX_AREA_M2)
    seen: set[int] = set()

    def grow(mask: int, total: float, frontier: set[int], start: int):
        seen.add(mask)
        if bin(mask).count("1") == cap_n:
            return
        for j in sorted(frontier):
            new = mask | (1 << j)
            if j < start or new in seen or total + area[j] > cap_a + 1e-9:
                continue
            grow(new, total + area[j], (frontier | nbr[j]) - {k for k in range(len(elig)) if new >> k & 1}, start)

    for i in range(len(elig)):
        if area[i] <= cap_a + 1e-9:
            grow(1 << i, area[i], set(nbr[i]), i)
    return len(seen)


def graph_facts(plans) -> dict:
    links_door = links_pass = isolated = 0
    pass_kinds = Counter()
    zones, single_door, eligible_total = [], 0, 0
    only_via_excluded = 0
    for plan in plans:
        g = geom_indep.build(plan)
        for a, b, d in g.links.edges(data=True):
            if d["kind"] == "door":
                links_door += 1
            else:
                links_pass += 1
                pass_kinds[" - ".join(sorted((g.room_type[a], g.room_type[b])))] += 1
        isolated += sum(1 for r in g.eligible if g.degree(r) == 0)
        single_door += sum(1 for r in g.eligible if g.degree(r) == 1)
        eligible_total += len(g.eligible)
        zones.append(count_zones(g))
        if g.eligible:
            strict = geom_indep.zone_connected(g, set(g.eligible))
            loose = geom_indep.zone_connected(g, set(g.eligible), via_excluded=True)
            only_via_excluded += (not strict) and loose
    n = len(plans)
    return {
        "sample_plans": n,
        "door_links_per_plan": links_door / n,
        "passages_per_plan": links_pass / n,
        "passage_kinds": dict(pass_kinds.most_common(8)),
        "eligible_rooms_with_no_link": isolated,
        "single_door_eligible_share": single_door / eligible_total if eligible_total else 0.0,
        "zones": {"median": statistics.median(zones), "p95": _q(zones)[0.95], "max": max(zones)},
        "plans_connected_only_via_excluded": only_via_excluded,
    }


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render(fast: dict, graph: dict, runtime: dict) -> str:
    lb = fast["hub_lower_bound"]
    n = fast["plans"]
    share = lambda k: _pct(lb.get(k, 0) / n)  # noqa: E731
    three_plus = sum(v for k, v in lb.items() if int(k) >= 3) / n
    d = fast["doors"]
    rows = [
        ("Plans", "17,000", f"{n:,}", ""),
        ("Scale (units/m)", "median 18.3, mostly 12–26",
         f"median {fast['scale_median']:.1f}, p5–p95 {fast['scale_p05_p95'][0]:.1f}–{fast['scale_p05_p95'][1]:.1f}", ""),
        ("Suspicious scale (< 8 or > 40)", "52 plans", f"{fast['suspicious_scale_plans']} plans", ""),
        ("Storage present", "1,781 plans", f"{fast['storage_plans']:,} plans", ""),
        ("Invalid geometry", "~400 door, ~400 window, 111 land, 7 bedroom, 5 bathroom",
         ", ".join(f"{v} {k}" for k, v in sorted(fast["invalid_geometry"].items(), key=lambda kv: -kv[1])), ""),
        ("Multi-polygon living rooms", "256 plans", f"{fast['multi_polygon_living_plans']} plans", "counted after make_valid, which splits a few more"),
        ("Jagged room outlines (> 30 vertices)", "0.5% of rooms", _pct(fast["jagged_room_share"]), "indoor rooms; land outlines are ~92% jagged"),
        ("Eligible rooms per plan", "median 4, p95 6, max 10",
         f"median {fast['eligible_rooms']['median']:.0f}, p95 {fast['eligible_rooms']['p95']}, max {fast['eligible_rooms']['max']}",
         "after dropping parts < 0.5 m² (max 10 → 9)"),
        ("Eligible area per plan", "median 95 m², p95 184 m²",
         f"median {fast['eligible_area_m2']['median']:.0f} m², p95 {fast['eligible_area_m2']['p95']:.0f} m²", ""),
        ("Hub lower bound", "1 hub 55%, 2 hubs 41%, 3+ ~4% (max 7)",
         f"1 hub {share('1')}, 2 hubs {share('2')}, 3+ {_pct(three_plus)} (max {max(int(k) for k in lb)})", ""),
        ("Binding limit", "area ~35%, 5-node 0.4%",
         f"area {_pct(fast['area_binds_share'])}, 5-node {_pct(fast['nodes_bind_share'])}", "strictly binding"),
        ("Plans with a room > 100 m²", "428", f"{fast['plans_with_room_over_100m2']}", "organisers drop these"),
        ("Doors < 5% covered by wall", "99.4% of 108,487", f"{_pct(d['lt5pct_wall_share'])} of {d['total']:,}", "door parts after make_valid; touching doors merge"),
        ("Doors > 50% covered by wall", "0.08%", _pct(d["gt50pct_wall_share"]), ""),
        ("Plans with a buried door", "0.48%", _pct(d["plans_with_buried_door"] / n), "→ always subtract doors from walls"),
        ("Walls ≥ 99% axis-aligned", "98.4% of plans", _pct(fast["axis_aligned"]["share_ge_99pct"]), "per-edge 1 mm test on wall outlines; stricter than the original"),
        ("Walls < 90% axis-aligned", "0.1% of plans", _pct(fast["axis_aligned"]["share_lt_90pct"]), ""),
    ]
    g = graph
    grows = [
        ("Door links per plan", "—", f"{g['door_links_per_plan']:.2f}", ""),
        ("Open passages per plan", "—", f"{g['passages_per_plan']:.2f}",
         "; ".join(f"{k} {v}" for k, v in g["passage_kinds"].items())),
        ("Eligible rooms with no door or passage", "—", f"{g['eligible_rooms_with_no_link']}", "these plans can't be fully zoned"),
        ("Single-door eligible rooms", "—", _pct(g["single_door_eligible_share"]), "where retracing is allowed"),
        ("Legal zones per plan", "median 11, max 106 (stored via_door edges)",
         f"median {g['zones']['median']:.0f}, p95 {g['zones']['p95']}, max {g['zones']['max']}", "our own graph; a 1,500-plan sample, so the max is lower"),
        ("Plans connected only through bathroom/stair", "28 of 17,000 (0.16%)",
         f"{g['plans_connected_only_via_excluded']} of {g['sample_plans']}", "whole plan as one zone, sample"),
    ]
    out = ["# Data facts (reproduced by `python -m eightball audit`)", "",
           f"Generated by `bench/audit.py` (Person B, step B1). Fast facts: all {n:,} plans in {runtime['fast']:.0f} s. "
           f"Graph facts: a seeded sample of {g['sample_plans']} plans from the `{runtime['split']}` split in "
           f"{runtime['graph']:.0f} s, using the checker's own door/passage graph (`evaluate/geom_indep.py`).", "",
           "## All plans", "", "| Fact | Handoff §3 | Ours | Note |", "|---|---|---|---|"]
    out += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
    out += ["", "## Door/passage graph (sample)", "", "| Fact | Handoff §3 | Ours | Note |", "|---|---|---|---|"]
    out += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in grows]
    return "\n".join(out) + "\n"


def run(split: str = "train", limit: int = 1500, out: str | None = None) -> dict:
    plans = resplan.load_plans()
    t0 = time.time()
    fast = fast_facts(plans)
    t1 = time.time()
    ids = resplan.split_ids(split)
    sample = random.Random(int(config.SEED)).sample(ids, min(limit, len(ids)))
    graph = graph_facts([resplan.get_plan(i) for i in sample])
    t2 = time.time()
    runtime = {"fast": t1 - t0, "graph": t2 - t1, "split": split}
    report = render(fast, graph, runtime)
    out_path = Path(out or "docs/data_facts.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    raw = Path(str(config.DATA_DIR)) / "out" / "audit.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps({"fast": fast, "graph": graph, "runtime": runtime}, indent=1, default=str), encoding="utf-8")
    return {"fast": fast, "graph": graph, "runtime": runtime, "path": str(out_path)}


def cli_main(args: argparse.Namespace) -> int:
    own = argparse.ArgumentParser(prog="eightball audit")
    own.add_argument("--split", default="train")
    own.add_argument("--limit", type=int, default=1500)
    extra = own.parse_args(getattr(args, "extra", []))
    result = run(split=extra.split, limit=extra.limit, out=args.out)
    print(f"wrote {result['path']} (fast {result['runtime']['fast']:.0f} s, graph {result['runtime']['graph']:.0f} s)")
    return 0
