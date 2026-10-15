"""Stitched-floor scalability benchmark (Person B, step B7 / handoff S3.3).

    python -m eightball stitch [--split train] [--sizes 1,2,4,6,8] [--budget 30] [--candidates proxy|solver]
                               [--floors-per-size 2] [--name NAME]

Builds large synthetic floors from real flats:
  1. convert each flat to metres (scale = 1 afterwards) and move its inner box to start at (0, 0);
  2. place flats left to right with their outer walls touching, shifting each flat vertically so an
     eligible room on its left edge lines up with one on the previous flat's right edge;
  3. cut one 0.9 m door through both outer walls between that pair and add it to `inner`;
  4. merge every geometry key and re-run the checker's cleaning; floors that fail are dropped.

Then times zone selection on each floor: CP-SAT vs a plain exhaustive exact-cover search (stopped at
the budget). Zone costs come from `--candidates solver` (Person A's pipeline.zone_candidates, once A7
lands) or `proxy` (shortest Manhattan tour through the zone's nodes, walls ignored), clearly labelled.
Writes data/out/scale/scale.json (+ scale.png) and web/data/scale.json for the dashboard.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import time
from pathlib import Path

import shapely
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from eightball import config
from eightball.core.contracts import ZoneCandidate
from eightball.evaluate import geom_indep
from eightball.io import nodes as nodes_io, resplan

DOOR_W = 0.9
EDGE_TOL = 0.3
GEOM_KEYS = ("living", "bedroom", "bathroom", "kitchen", "storage", "stair", "balcony", "door", "window",
             "wall", "front_door", "inner", "garden", "pool", "parking")


def _get(plan: dict, key: str):
    g = plan.get(key)
    return None if g is None or g.is_empty else shapely.make_valid(g)


def to_metres(plan: dict) -> dict:
    """Copy of the flat in metres, inner box starting at (0, 0). Outdoor 'land' is dropped."""
    s = resplan.scale(plan)
    minx, miny, *_ = plan["inner"].bounds
    out = {}
    for key in GEOM_KEYS:
        g = _get(plan, key)
        if g is not None:
            g = affinity.translate(g, -minx, -miny)
            out[key] = affinity.scale(g, 1 / s, 1 / s, origin=(0, 0))
    depth = plan.get("wall_depth")
    out["wall_thickness"] = (float(depth) / s) if depth else 0.2
    out["id"] = int(plan["id"])
    return out


def _edge_rooms(flat: dict, side: str) -> list[Polygon]:
    inner = flat["inner"]
    minx, _, maxx, _ = inner.bounds
    rooms = []
    for key in resplan.ELIGIBLE:
        for p in resplan.parts(flat.get(key)):
            if side == "right" and p.bounds[2] >= maxx - EDGE_TOL:
                rooms.append(p)
            if side == "left" and p.bounds[0] <= minx + EDGE_TOL:
                rooms.append(p)
    return rooms


def _best_pair(left_rooms, right_rooms):
    """Pair of edge rooms and the vertical shift for the right flat that best lines them up."""
    best = None
    for a in left_rooms:
        for b in right_rooms:
            a_lo, a_hi = a.bounds[1], a.bounds[3]
            b_lo, b_hi = b.bounds[1], b.bounds[3]
            shift = (a_lo + a_hi) / 2 - (b_lo + b_hi) / 2
            overlap = min(a_hi, b_hi + shift) - max(a_lo, b_lo + shift)
            if best is None or overlap > best[0]:
                best = (overlap, a, b, shift)
    return best


def stitch(flats_raw: list[dict], floor_id: int = 800000) -> tuple[dict | None, list[str]]:
    """Merge flats (ResPlan dicts) into one floor dict in metres. Returns (floor, notes); floor None on failure."""
    notes: list[str] = []
    flats = [to_metres(p) for p in flats_raw]
    placed = [flats[0]]
    doors = []
    x_cursor = flats[0]["inner"].bounds[2]
    for prev, flat in zip(flats, flats[1:]):
        pair = _best_pair(_edge_rooms(placed[-1], "right"), _edge_rooms(flat, "left"))
        if pair is None or pair[0] < DOOR_W + 0.2:
            notes.append(f"no eligible rooms to join flat {prev['id']} and {flat['id']}")
            return None, notes
        overlap, a, b, shift = pair
        gap = placed[-1]["wall_thickness"] + flat["wall_thickness"]
        dx = x_cursor + gap
        moved = {k: (affinity.translate(v, dx, shift) if hasattr(v, "geom_type") else v) for k, v in flat.items()}
        b_moved = affinity.translate(b, dx, shift)
        y_lo = max(a.bounds[1], b_moved.bounds[1])
        y_hi = min(a.bounds[3], b_moved.bounds[3])
        yc = (y_lo + y_hi) / 2
        doors.append(box(a.bounds[2], yc - DOOR_W / 2, b_moved.bounds[0], yc + DOOR_W / 2))
        placed.append(moved)
        x_cursor = moved["inner"].bounds[2]
    floor = {}
    try:
        for key in GEOM_KEYS:
            geoms = [shapely.make_valid(f[key]) for f in placed if key in f]
            floor[key] = unary_union(geoms) if geoms else Polygon()
        cut = unary_union(doors) if doors else Polygon()
        floor["wall"] = floor["wall"].difference(cut)
        floor["door"] = unary_union([floor["door"], cut])
        floor["inner"] = unary_union([floor["inner"], cut])
    except shapely.errors.GEOSException as exc:
        notes.append(f"merging failed: {exc}")
        return None, notes
    floor["land"] = Polygon()
    floor["neighbor"] = Polygon()
    floor.update({"id": floor_id, "area": floor["inner"].area, "net_area": 0.0,
                  "wall_depth": float(min(f["wall_thickness"] for f in placed)), "graph": None,
                  "stitched_from": [f["id"] for f in placed]})
    try:
        g = geom_indep.build(floor)
    except Exception as exc:  # cleaning failed: drop this floor
        notes.append(f"cleaning failed: {type(exc).__name__}: {exc}")
        return None, notes
    if len(placed) > 1 and not _crosses_flats(g, doors):
        notes.append("a cut door didn't link two rooms")
        return None, notes
    return floor, notes


def _crosses_flats(g, doors) -> bool:
    links = {(a, b) for a, b, d in g.links.edges(data=True) if d["kind"] == "door"}
    for door in doors:
        touching = [r for r, poly in g.rooms.items() if poly.distance(door) < 0.05]
        if not any((a, b) in links or (b, a) in links for a, b in itertools.combinations(touching, 2)):
            return False
    return True


# ---- zone candidates ----

def proxy_tour(points: list[tuple[float, float]]) -> float:
    """Shortest closed Manhattan tour through the points (walls ignored)."""
    if len(points) <= 1:
        return 0.0
    first, rest = points[0], points[1:]
    best = math.inf
    for order in itertools.permutations(rest):
        tour = [first, *order, first]
        best = min(best, sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in zip(tour, tour[1:])))
    return best


def zone_sets(g: geom_indep.CheckGeom) -> list[frozenset[str]]:
    """Every connected set of <= MAX_NODES eligible rooms with <= MAX_AREA (links within the set only)."""
    elig = sorted(g.eligible)
    nbr = {r: set() for r in elig}
    for a, b in g.links.edges():
        if a in nbr and b in nbr and a != b:
            nbr[a].add(b)
            nbr[b].add(a)
    cap_n, cap_a = int(config.MAX_NODES_PER_HUB), float(config.MAX_AREA_M2)
    order = {r: i for i, r in enumerate(elig)}
    found: set[frozenset[str]] = set()

    def grow(members: frozenset[str], area: float, start: str):
        found.add(members)
        if len(members) == cap_n:
            return
        frontier = set().union(*(nbr[m] for m in members)) - members
        for r in sorted(frontier):
            if order[r] < order[start]:
                continue
            new = members | {r}
            if new not in found and area + g.area_m2[r] <= cap_a + 1e-9:
                grow(new, area + g.area_m2[r], start)

    for r in elig:
        if g.area_m2[r] <= cap_a + 1e-9:
            grow(frozenset([r]), g.area_m2[r], r)
    return sorted(found, key=lambda s: (len(s), sorted(s)))


def proxy_candidates(floor: dict) -> tuple[list[str], list[ZoneCandidate], int]:
    g = geom_indep.build(floor)
    nodes = {n["room_id"]: tuple(n["point"]) for n in nodes_io.make_nodes(floor, "center")}
    cands = []
    for k, rooms in enumerate(zone_sets(g)):
        area = sum(g.area_m2[r] for r in rooms)
        cost = proxy_tour([nodes[r] for r in sorted(rooms)])
        cands.append(ZoneCandidate(zone_id=f"Z{k}", room_ids=rooms, area_m2=area, n_nodes=len(rooms), cost=cost))
    rooms = sorted(g.eligible)
    total = sum(g.area_m2[r] for r in rooms)
    min_hubs = max(math.ceil(total / float(config.MAX_AREA_M2) - 1e-9), math.ceil(len(rooms) / int(config.MAX_NODES_PER_HUB)))
    return rooms, cands, min_hubs


def solver_candidates(floor: dict) -> tuple[list[str], list[ZoneCandidate], int]:
    from eightball.optimize import pipeline

    nodes = nodes_io.make_nodes(floor, "center")
    rooms, cands = pipeline.zone_candidates(floor, nodes)
    g = geom_indep.build(floor)
    total = sum(g.area_m2[r] for r in rooms)
    min_hubs = max(math.ceil(total / float(config.MAX_AREA_M2) - 1e-9), math.ceil(len(rooms) / int(config.MAX_NODES_PER_HUB)))
    return rooms, cands, min_hubs


# ---- exhaustive baseline ----

def exhaustive_select(rooms: list[str], cands: list[ZoneCandidate], budget_s: float):
    """Plain exact-cover search for (fewest zones, then lowest cost). Returns (hubs, cost, finished, seconds)."""
    t0 = time.perf_counter()
    deadline = t0 + budget_s
    by_room = {r: [c for c in cands if r in c.room_ids] for r in rooms}
    best = [None]
    finished = [True]
    nodes = [0]

    def go(left: frozenset, count: int, cost: float):
        nodes[0] += 1
        if nodes[0] % 2048 == 0 and time.perf_counter() > deadline:
            finished[0] = False
            raise TimeoutError
        if best[0] is not None and (count, cost) >= best[0]:
            return
        if not left:
            best[0] = (count, cost)
            return
        r = min(left, key=lambda q: len(by_room[q]))
        for c in by_room[r]:
            if c.room_ids <= left:
                go(left - c.room_ids, count + 1, cost + c.cost)

    try:
        go(frozenset(rooms), 0, 0.0)
    except TimeoutError:
        pass
    seconds = time.perf_counter() - t0
    hubs, cost = best[0] if best[0] else (None, None)
    return hubs, cost, finished[0], seconds


# ---- benchmark ----

def _has_oversized_room(plan: dict) -> bool:
    s2 = resplan.scale(plan) ** 2
    return any(poly.area / s2 > float(config.MAX_AREA_M2) for _r, _t, poly in resplan.eligible_rooms(plan))


def build_floors(split: str, sizes: list[int], per_size: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    ids = resplan.split_ids(split)
    floors, attempts, next_id = [], 0, 800000
    for n in sizes:
        made = 0
        while made < per_size and attempts < 200 * len(sizes) * per_size:
            attempts += 1
            flats = [resplan.get_plan(i) for i in rng.sample(ids, n)]
            if any(resplan.scale_is_suspicious(resplan.scale(p)) or _has_oversized_room(p) for p in flats):
                continue  # the organisers drop plans with a room over 100 m2; no hub could serve it
            floor, _notes = stitch(flats, next_id)
            if floor is None:
                continue
            next_id += 1
            floors.append(floor)
            made += 1
    return floors


def bench_floor(floor: dict, budget_s: float, source: str = "proxy") -> dict:
    from eightball.optimize.cpsat import CpSatZoneSolver

    t0 = time.perf_counter()
    rooms, cands, min_hubs = (solver_candidates if source == "solver" else proxy_candidates)(floor)
    t_cands = time.perf_counter() - t0
    solver = CpSatZoneSolver()
    t0 = time.perf_counter()
    sel = solver.select(rooms, cands, min_hubs, budget_s)
    t_cp = time.perf_counter() - t0
    ex_hubs, ex_cost, finished, t_ex = exhaustive_select(rooms, cands, budget_s)
    gap = None
    if sel.bound is not None and math.isfinite(sel.cost) and sel.cost > 0:
        gap = max(0.0, (sel.cost - sel.bound) / sel.cost)
    return {
        "floor_id": floor["id"], "flats": len(floor["stitched_from"]), "stitched_from": floor["stitched_from"],
        "rooms": len(rooms), "candidates": len(cands), "min_hubs": min_hubs, "candidates_s": round(t_cands, 3),
        "cpsat_s": round(t_cp, 3), "cpsat_hubs": sel.hubs, "cpsat_cost": sel.cost, "cpsat_optimal": sel.optimal,
        "cpsat_gap": gap,
        "exhaustive_s": round(t_ex, 3), "exhaustive_finished": finished, "exhaustive_hubs": ex_hubs,
        "exhaustive_cost": ex_cost,
        "agree": bool(finished and ((ex_hubs is None and not sel.zone_ids) or (
            ex_hubs == sel.hubs and ex_cost is not None and abs(ex_cost - sel.cost) < 1e-3 * max(1.0, abs(ex_cost))))),
    }


def claim(points: list[dict]) -> dict:
    solved = [p for p in points if p["cpsat_hubs"]]
    if not solved:
        return {}
    big = max(solved, key=lambda p: p["rooms"])
    return {"N": big["rooms"], "T": big["cpsat_s"], "G": big["cpsat_gap"], "optimal": big["cpsat_optimal"],
            "text": f"CP-SAT solves a {big['rooms']}-room floor in {big['cpsat_s']:.2f} s, "
                    f"within {100 * (big['cpsat_gap'] or 0):.1f}% of its own bound"}


def chart(points: list[dict], path: Path, budget_s: float, source: str) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=150)
    pts = sorted(points, key=lambda p: p["rooms"])
    floor_s = lambda t: max(t, 1e-3)  # noqa: E731  (sub-millisecond times would vanish on a log scale)
    ax.plot([p["rooms"] for p in pts], [floor_s(p["cpsat_s"]) for p in pts], "o-", color="#2563A8", label="CP-SAT")
    done = [p for p in pts if p["exhaustive_finished"]]
    cut = [p for p in pts if not p["exhaustive_finished"]]
    ax.plot([p["rooms"] for p in done], [floor_s(p["exhaustive_s"]) for p in done], "s-", color="#D2601A", label="Exhaustive search")
    if cut:
        ax.scatter([p["rooms"] for p in cut], [p["exhaustive_s"] for p in cut], marker="x", color="#D2601A", s=60,
                   label=f"Exhaustive: stopped at {budget_s:.0f} s budget")
    ax.set_yscale("log")
    ax.set_xlabel("Eligible rooms on the floor")
    ax.set_ylabel("Zone selection time (s, log scale)")
    ax.set_title("CP-SAT keeps going where exhaustive search stops", loc="left", fontsize=11, fontweight="bold")
    ax.text(0, -0.2, f"Zone costs: {source}. Stitched ResPlan flats.", transform=ax.transAxes, fontsize=7, color="#6B7280")
    ax.grid(True, which="both", color="#E5E5E2", linewidth=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def run(split="train", sizes=(1, 2, 4, 8, 12, 16), per_size=2, budget_s=30.0, source="proxy", seed=None,
        name="scale") -> dict:
    floors = build_floors(split, list(sizes), per_size, int(config.SEED) if seed is None else seed)
    points = [bench_floor(f, budget_s, source) for f in floors]
    source_label = ("solver costs (pipeline.zone_candidates)" if source == "solver"
                    else "proxy (shortest Manhattan tour through the zone's nodes, walls ignored)")
    result = {"schema_version": "8ball-scale/1", "name": name, "budget_s": budget_s, "cost_source": source_label,
              "points": points, "claim": claim(points)}
    out = Path(str(config.DATA_DIR)) / "out" / "scale"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    result["chart"] = str(chart(points, out / f"{name}.png", budget_s, source_label))
    Path("web/data").mkdir(parents=True, exist_ok=True)
    Path("web/data/scale.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def cli_main(args: argparse.Namespace) -> int:
    own = argparse.ArgumentParser(prog="eightball stitch")
    own.add_argument("--sizes", default="1,2,4,8,12,16")
    own.add_argument("--floors-per-size", type=int, default=2)
    own.add_argument("--budget", type=float, default=30.0)
    own.add_argument("--candidates", default="proxy", choices=("proxy", "solver"))
    own.add_argument("--seed", type=int)
    own.add_argument("--name", default="scale")
    extra = own.parse_args(getattr(args, "extra", []))
    result = run(split=args.split, sizes=[int(s) for s in extra.sizes.split(",")], per_size=extra.floors_per_size,
                 budget_s=extra.budget, source=extra.candidates, seed=extra.seed, name=extra.name)
    print(f"{'flats':>5} {'rooms':>5} {'cands':>6} {'hubs':>4} {'cpsat_s':>8} {'opt':>4} {'exh_s':>8} {'done':>5} {'agree':>5}")
    for p in result["points"]:
        print(f"{p['flats']:>5} {p['rooms']:>5} {p['candidates']:>6} {p['cpsat_hubs']:>4} {p['cpsat_s']:>8.3f} "
              f"{str(p['cpsat_optimal'])[:4]:>4} {p['exhaustive_s']:>8.3f} {str(p['exhaustive_finished']):>5} {str(p['agree']):>5}")
    print(result["claim"].get("text", "no floors solved"))
    print(f"chart: {result['chart']}")
    return 0 if result["points"] else 1
