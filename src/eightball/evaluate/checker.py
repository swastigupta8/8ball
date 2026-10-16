"""Independent checker (Person B, step B2 / handoff S1.4, 8.2).

Reads only the raw plan, the node list and the answer JSON. Never imports eightball.geometry,
eightball.routing, eightball.optimize or eightball.core.metrics.

check(...) -> {"valid": bool, "violations": [{rule, hub_id, leg, location, message}], "metrics": {...}}
Rules: schema, coverage, capacity, zone, ring, free_space, hub. Strict readings follow config switches.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from eightball import config
from eightball.evaluate import geom_indep, metrics_indep
from eightball.io import answer_io, nodes as nodes_io, resplan

RULES = ("schema", "coverage", "capacity", "zone", "ring", "free_space", "hub")


def _v(rule, message, hub_id=None, leg=None, location=None) -> dict:
    loc = [float(location[0]), float(location[1])] if location is not None else None
    return {"rule": rule, "hub_id": hub_id, "leg": leg, "location": loc, "message": message}


def _check_nodes(answer: dict, expected: list[dict], g, tol: float) -> list[dict]:
    out = []
    got = {n["node_id"]: n for n in answer["nodes"]}
    exp = {n["node_id"]: n for n in expected}
    if set(got) != set(exp):
        out.append(_v("coverage", f"answer nodes {sorted(got)} differ from the plan's nodes {sorted(exp)}"))
    for nid, n in exp.items():
        if nid in got:
            p, q = got[nid]["point"], n["point"]
            if abs(p[0] - q[0]) > tol or abs(p[1] - q[1]) > tol or got[nid]["room_id"] != n["room_id"]:
                out.append(_v("coverage", f"{nid} moved or relabelled", location=p))
    for n in expected:
        if n["room_id"] not in g.eligible:
            out.append(_v("coverage", f"{n['node_id']} is in unknown room {n['room_id']}", location=n["point"]))
    return out


def _check_coverage(answer: dict, expected: list[dict], g) -> list[dict]:
    out = []
    owner = Counter(r for h in answer["hubs"] for r in h["room_ids"])
    for rid in sorted(g.eligible):
        if owner[rid] == 0:
            out.append(_v("coverage", f"room {rid} is not assigned to any hub", location=g.rooms[rid].representative_point().coords[0]))
        elif owner[rid] > 1:
            out.append(_v("coverage", f"room {rid} is assigned to {owner[rid]} hubs"))
    for rid in owner:
        if rid not in g.eligible:
            out.append(_v("coverage", f"{rid} is not an eligible room"))
    room_of = {n["node_id"]: n["room_id"] for n in expected}
    node_owner = Counter(nid for h in answer["hubs"] for nid in h["node_ids"])
    for nid in room_of:
        if node_owner[nid] != 1:
            out.append(_v("coverage", f"node {nid} is served by {node_owner[nid]} hubs"))
    for h in answer["hubs"]:
        want = sorted(nid for nid, rid in room_of.items() if rid in h["room_ids"])
        if sorted(h["node_ids"]) != want:
            out.append(_v("coverage", f"node_ids {sorted(h['node_ids'])} don't match the zone's rooms ({want})", h["hub_id"]))
    return out


def _check_capacity(answer: dict, g) -> list[dict]:
    out = []
    for h in answer["hubs"]:
        area = sum(g.area_m2.get(r, 0.0) for r in h["room_ids"])
        if area > float(config.MAX_AREA_M2) + 1e-9:
            out.append(_v("capacity", f"zone area {area:.2f} m2 > {config.MAX_AREA_M2}", h["hub_id"], location=h["point"]))
        if len(h["node_ids"]) > int(config.MAX_NODES_PER_HUB):
            out.append(_v("capacity", f"{len(h['node_ids'])} nodes > {config.MAX_NODES_PER_HUB}", h["hub_id"], location=h["point"]))
    return out


def _check_zone(answer: dict, g) -> list[dict]:
    out = []
    for h in answer["hubs"]:
        rooms = {r for r in h["room_ids"] if r in g.rooms}
        if not geom_indep.zone_connected(g, rooms, via_excluded=bool(config.ZONE_VIA_EXCLUDED_ROOMS)):
            out.append(_v("zone", f"rooms {sorted(rooms)} aren't connected through doors/passages within the zone",
                          h["hub_id"], location=h["point"]))
    return out


def _check_ring(answer: dict, g, points: dict) -> list[dict]:
    out = []
    unit = float(config.TOL_M) * g.scale
    single_door = {r for r in g.rooms if g.degree(r) == 1}
    for h in answer["hubs"]:
        hid, seq = h["hub_id"], h["sequence"]
        if seq[0] != hid or seq[-1] != hid:
            out.append(_v("ring", "ring doesn't start and end at its hub", hid))
        stops = seq[1:-1]
        counts = Counter(stops)
        for nid in h["node_ids"]:
            if counts[nid] != 1:
                out.append(_v("ring", f"node {nid} visited {counts[nid]} times", hid, location=points.get(nid)))
        for nid in counts:
            if nid not in h["node_ids"]:
                out.append(_v("ring", f"ring visits {nid}, which isn't one of its nodes", hid, location=points.get(nid)))
        pts = {**points, hid: h["point"]}
        for k, leg in enumerate(h["legs"]):
            poly = leg["polyline"]
            if leg["from"] in pts and Point(poly[0]).distance(Point(pts[leg["from"]])) > unit:
                out.append(_v("ring", f"leg doesn't start at {leg['from']}", hid, k, poly[0]))
            if leg["to"] in pts and Point(poly[-1]).distance(Point(pts[leg["to"]])) > unit:
                out.append(_v("ring", f"leg doesn't end at {leg['to']}", hid, k, poly[-1]))
        if bool(config.RETRACE_ONLY_SINGLE_DOOR):
            out += _check_retrace(h, g, single_door, unit, pts)
    return out


def _stop_room(g, point) -> str | None:
    p = Point(point)
    return next((r for r, poly in g.rooms.items() if poly.covers(p)), None)


def _axis_runs(poly, scale: float) -> list[tuple[str, int, int, int]]:
    """A polyline's axis-aligned segments on the 1 mm grid: (orientation, constant coord, lo, hi)."""
    unit = float(config.TOL_M)
    pts = [(round(x / scale / unit), round(y / scale / unit)) for x, y in poly]
    runs = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if y1 == y2 and x1 != x2:
            runs.append(("h", y1, min(x1, x2), max(x1, x2)))
        elif x1 == x2 and y1 != y2:
            runs.append(("v", x1, min(y1, y2), max(y1, y2)))
    return runs


def collinear_pieces(poly_a, poly_b, scale: float) -> list[LineString]:
    """Stretches where two polylines run along the same line (lines within 1 mm are the same line).

    Only shared length counts: two legs crossing or touching at a point share nothing here (a crossing
    is an X, scored by the metrics, not an overlap). Returned in drawing units."""
    unit = float(config.TOL_M) * scale
    pieces = []
    runs_b = _axis_runs(poly_b, scale)
    for orient, c, lo, hi in _axis_runs(poly_a, scale):
        for orient_b, c_b, lo_b, hi_b in runs_b:
            if orient != orient_b or c != c_b:
                continue
            a, b = max(lo, lo_b), min(hi, hi_b)
            if b > a:
                if orient == "h":
                    pieces.append(LineString([(a * unit, c * unit), (b * unit, c * unit)]))
                else:
                    pieces.append(LineString([(c * unit, a * unit), (c * unit, b * unit)]))
    return pieces


def _dead_end_region(g, room: str):
    """The single-door room plus its door or passage gap: where a retrace is allowed."""
    tol = float(config.TOL_M) * g.scale
    poly = g.rooms[room]
    gaps = [d for d in g.doors if d.distance(poly) <= 0.05 * g.scale]
    gaps += [p for p in g.passages if p.distance(poly) <= 0.05 * g.scale]
    return unary_union([poly, *gaps]).buffer(tol)


def _check_retrace(h: dict, g, single_door: set[str], unit: float, pts: dict) -> list[dict]:
    """Overlap inside one ring is a retrace, allowed only into a single-door room: the two legs must be
    consecutive, the stop between them (a node, or the hub) must sit in a single-door room, and the
    shared stretch must lie inside that room and its door gap. Overlap = collinear length only."""
    out = []
    legs = h["legs"]
    n = len(legs)
    for i in range(n):
        for j in range(i + 1, n):
            pieces = collinear_pieces(legs[i]["polyline"], legs[j]["polyline"], g.scale)
            if not pieces:
                continue
            length = sum(p.length for p in pieces) / g.scale
            loc = pieces[0].interpolate(0.5, normalized=True).coords[0]
            if j == i + 1:
                stop = legs[i]["to"]
            elif i == 0 and j == n - 1:
                stop = legs[0]["from"]
            else:
                stop = None
            room = _stop_room(g, pts[stop]) if stop in pts else None
            if stop is None or room is None or room not in single_door:
                why = "non-consecutive legs" if stop is None else f"at {stop}, whose room isn't single-door"
                out.append(_v("ring", f"legs {i} and {j} overlap {length:.3f} m ({why})", h["hub_id"], j, loc))
                continue
            region = _dead_end_region(g, room)
            outside = [p for p in pieces if not region.covers(p)]
            if outside:
                spill = sum(p.difference(region).length for p in outside) / g.scale
                where = outside[0].difference(region)
                loc = where.representative_point().coords[0] if not where.is_empty else loc
                out.append(_v("ring", f"legs {i} and {j} retrace {spill:.3f} m outside dead-end room {room} and its door",
                              h["hub_id"], j, loc))
    return out


def _check_free_space(answer: dict, g) -> list[dict]:
    out = []
    s = g.scale
    tol = float(config.TOL_M) * s
    clearance = float(config.WALL_CLEARANCE_M) / 2 * s
    inner = g.inner.buffer(tol)
    gaps = unary_union(g.doors + g.passages).buffer(tol) if (g.doors or g.passages) else None
    room_union = unary_union(list(g.rooms.values())).buffer(tol)
    owner = {r: h["hub_id"] for h in answer["hubs"] for r in h["room_ids"]}
    for h in answer["hubs"]:
        hid = h["hub_id"]
        own = set(h["room_ids"])
        others = [g.rooms[r] for r in g.eligible if r not in own]
        for k, leg in enumerate(h["legs"]):
            poly = leg["polyline"]
            for a, b in zip(poly, poly[1:]):
                if a == b:
                    continue
                seg = LineString([a, b])
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                if abs(a[0] - b[0]) > tol and abs(a[1] - b[1]) > tol:
                    out.append(_v("free_space", "segment isn't axis-aligned", hid, k, mid))
                if not inner.covers(seg):
                    out.append(_v("free_space", "segment leaves the inner boundary", hid, k, mid))
                if not g.blockers.is_empty and seg.distance(g.blockers) < clearance - tol:
                    hit = seg.intersection(g.blockers.buffer(clearance))
                    loc = hit.representative_point().coords[0] if not hit.is_empty else mid
                    out.append(_v("free_space", f"segment within {config.WALL_CLEARANCE_M / 2:.3f} m of a wall or window",
                                  hid, k, loc))
                outside_rooms = seg.difference(room_union)
                if outside_rooms.length > 0.05 * s:
                    stray = outside_rooms if gaps is None else outside_rooms.difference(gaps)
                    if stray.length > 0.05 * s:
                        out.append(_v("free_space", "segment passes between rooms outside a door or passage",
                                      hid, k, stray.representative_point().coords[0]))
                if not bool(config.ALLOW_THROUGH_OTHER_ZONES):
                    for poly_other in others:
                        inside = seg.intersection(poly_other)
                        if inside.length > tol:
                            rid = next(r for r in g.eligible if g.rooms[r] is poly_other)
                            who = owner.get(rid, "no hub")
                            out.append(_v("free_space", f"segment enters {rid} (zone of {who})", hid, k,
                                          inside.representative_point().coords[0]))
    return out


def _check_hub(answer: dict, g) -> list[dict]:
    out = []
    need = float(config.HUB_CLEARANCE_M) * g.scale - float(config.TOL_M) * g.scale
    for h in answer["hubs"]:
        p = Point(h["point"])
        rooms = [r for r in h["room_ids"] if r in g.rooms and r in g.eligible and g.rooms[r].covers(p)]
        if not rooms:
            out.append(_v("hub", "hub isn't inside an eligible room of its zone", h["hub_id"], location=h["point"]))
            continue
        if h.get("room_id") not in rooms:
            out.append(_v("hub", f"hub room_id {h.get('room_id')} doesn't contain the hub (it's in {rooms[0]})",
                          h["hub_id"], location=h["point"]))
        d_room = g.rooms[rooms[0]].exterior.distance(p)
        d_wall = g.walls.distance(p) if not g.walls.is_empty else float("inf")
        if min(d_room, d_wall) < need:
            out.append(_v("hub", f"hub is {min(d_room, d_wall) / g.scale:.3f} m from a wall (< {config.HUB_CLEARANCE_M})",
                          h["hub_id"], location=h["point"]))
    return out


def check(plan_raw: dict, answer: dict, nodes: list[dict] | None = None) -> dict:
    """Check one answer. `nodes` is the plan's official node list; defaults to the answer's own nodes."""
    shape = answer_io.answer_errors(answer)
    if any(e.startswith("schema:") for e in shape):
        return {"valid": False, "violations": [_v("schema", e) for e in shape], "metrics": {}}
    violations = [_v("schema", e) for e in shape]
    g = geom_indep.build(plan_raw)
    expected = nodes if nodes is not None else answer["nodes"]
    points = {n["node_id"]: n["point"] for n in expected}
    tol = float(config.TOL_M) * g.scale
    if abs(float(answer["scale"]) - g.scale) > 1e-6 * g.scale:
        violations.append(_v("schema", f"answer scale {answer['scale']} != plan scale {g.scale}"))
    violations += _check_nodes(answer, expected, g, tol)
    violations += _check_coverage(answer, expected, g)
    violations += _check_capacity(answer, g)
    violations += _check_zone(answer, g)
    violations += _check_ring(answer, g, points)
    violations += _check_free_space(answer, g)
    violations += _check_hub(answer, g)
    metrics = metrics_indep.score(answer, g.scale)
    metrics["H"] = len(answer["hubs"])
    return {"valid": not violations, "violations": violations, "metrics": metrics}


def _load_nodes(args, plan: dict) -> list[dict] | None:
    if args.nodes == "file":
        return nodes_io.read_nodes_file(args.nodes_file)
    if args.nodes in nodes_io.MODES:
        return nodes_io.get_nodes(plan, args.nodes)
    return None


def _load_plan(args) -> dict:
    if args.plan_file:
        import pickle

        path = Path(args.plan_file)
        if path.suffix == ".json":
            raise SystemExit("JSON plan files need the organiser adapter (B11)")
        with open(path, "rb") as fh:
            return resplan.normalize_keys(pickle.load(fh))
    return resplan.get_plan(args.plan_id)


def summarize(result: dict) -> str:
    m = result["metrics"]
    head = "VALID" if result["valid"] else f"INVALID ({len(result['violations'])} violations)"
    lines = [head]
    if m:
        lines.append(f"H={m['H']}  L={m['L']:.3f}  X={m['X']}  O={m['O']:.3f}  B={m['B']}  J={m['J']:.3f}")
    for v in result["violations"]:
        where = f" [{v['hub_id']}{'' if v['leg'] is None else ' leg ' + str(v['leg'])}]" if v["hub_id"] else ""
        lines.append(f"  {v['rule']}{where}: {v['message']}")
    return "\n".join(lines)


def cli_main(args: argparse.Namespace) -> int:
    plan = _load_plan(args)
    answer = answer_io.read_json(args.answer)
    result = check(plan, answer, _load_nodes(args, plan))
    print(summarize(result))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0 if result["valid"] else 1
