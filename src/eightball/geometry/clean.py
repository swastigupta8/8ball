"""Clean a raw ResPlan dict into a CleanPlan (handoff 6 step 1 and 7.2, BUILD_SPLIT A1).

Coordinates stay in the plan's drawing units, the same frame as the input nodes and the answer JSON;
``CleanPlan.scale`` converts to metres and ``Room.area_m2`` is already in square metres.
Room IDs come only from ``io.resplan.room_parts``, so they match the checker's.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import shapely
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from eightball import config
from eightball.core.contracts import CleanPlan, Node, Passage, Room
from eightball.geometry import doorgraph, freespace
from eightball.io import nodes as nodes_io
from eightball.io import resplan

SIMPLIFY_MIN_VERTICES = 30
SIMPLIFY_TOL_M = 0.02


def _repair(geom: BaseGeometry | None) -> BaseGeometry:
    if geom is None or geom.is_empty:
        return Polygon()
    return unary_union(resplan.parts(shapely.make_valid(geom))) if not geom.is_valid else geom


def simplify_inward(poly: Polygon, tol: float) -> Polygon:
    """Simplify jagged outlines so the result lies inside the original (never outside a wall)."""
    if len(poly.exterior.coords) <= SIMPLIFY_MIN_VERTICES and not poly.interiors:
        return poly
    inside = poly.simplify(tol, preserve_topology=True).intersection(poly)
    best = max(resplan.parts(shapely.make_valid(inside)), key=lambda p: p.area, default=None)
    if best is None or best.area < 0.98 * poly.area:
        return poly
    return best


def _axis_fraction(geom: BaseGeometry, tol: float) -> float:
    total = aligned = 0.0
    for poly in resplan.parts(geom):
        for ring in (poly.exterior, *poly.interiors):
            c = np.asarray(ring.coords)
            d = np.abs(np.diff(c, axis=0))
            length = np.hypot(d[:, 0], d[:, 1])
            total += float(length.sum())
            aligned += float(length[(d[:, 0] <= tol) | (d[:, 1] <= tol)].sum())
    return aligned / total if total > 0 else 1.0


def build_clean_plan(plan: dict, nodes: list[dict] | None = None, *, flood_check: bool = False) -> CleanPlan:
    """Build a CleanPlan. ``nodes`` is a node list (io/nodes format); practice nodes are generated if None.

    ``flood_check`` cross-checks the open passages with a flood fill (handoff idea C); disagreements are
    dropped and flagged. It is slower, so it is off by default.
    """
    s = resplan.scale(plan)
    flags: list[str] = []
    if resplan.scale_is_suspicious(s):
        flags.append("suspicious_scale")

    rooms: dict[str, Room] = {}
    simplify_tol = SIMPLIFY_TOL_M * s
    for rid, rtype, repaired in resplan.room_parts(plan):
        rooms[rid] = Room(id=rid, type=rtype, poly=simplify_inward(repaired, simplify_tol),
                          area_m2=repaired.area / (s * s), eligible=rtype in resplan.ELIGIBLE, door_ids=())
    for rtype, area in resplan.dropped_room_parts(plan):
        flags.append(f"dropped_sliver:{rtype}:{area:.2f}")

    # Always subtract the door shapes from the walls (0.48% of plans have a door buried in a wall).
    doors_raw = _repair(plan.get("door"))
    front_door = _repair(plan.get("front_door"))
    windows = _repair(plan.get("window"))
    inner = unary_union(resplan.parts(_repair(plan["inner"])))
    walls = unary_union(resplan.parts(_repair(plan.get("wall")).difference(doors_raw)))
    if _axis_fraction(walls, 0.001 * s) < 0.99:
        flags.append("non_axis_walls")

    door_polys = doorgraph.door_polygons(doors_raw, front_door)
    depth, fallback = doorgraph.wall_depth_units(plan, door_polys, s)
    if fallback:
        flags.append("wall_depth_fallback")
    doors, door_flags = doorgraph.make_doors(door_polys, rooms, depth)
    flags += door_flags

    candidates = doorgraph.find_passages(rooms, walls, windows, front_door, door_polys, depth, s)
    if flood_check and candidates:
        candidates, flood_flags = doorgraph.confirm_passages(candidates, rooms, walls, windows, front_door,
                                                             door_polys, depth, s)
        flags += flood_flags
    passages = {f"passage_{k}": Passage(id=f"passage_{k}", seg=seg, rooms=(a, b))
                for k, (a, b, seg) in enumerate(candidates)}

    links = nx.Graph()
    links.add_nodes_from(rooms)
    door_ids: dict[str, list[str]] = {rid: [] for rid in rooms}
    for door in doors.values():
        for rid in door.rooms:
            door_ids[rid].append(door.id)
        links.add_edge(*door.rooms, kind="door", id=door.id)
    for p in passages.values():
        if not links.has_edge(*p.rooms):
            links.add_edge(*p.rooms, kind="passage", id=p.id)
    rooms = {rid: Room(id=r.id, type=r.type, poly=r.poly, area_m2=r.area_m2, eligible=r.eligible,
                       door_ids=tuple(door_ids[rid])) for rid, r in rooms.items()}

    free = freespace.compute_free(inner, walls, windows, front_door, s)

    node_list = nodes if nodes is not None else nodes_io.make_nodes(plan, "center")
    node_map: dict[str, Node] = {}
    for n in node_list:
        node = Node(id=n["node_id"], room_id=n["room_id"], point=(float(n["point"][0]), float(n["point"][1])))
        node_map[node.id] = node
        room = rooms.get(node.room_id)
        if room is None or not room.eligible:
            flags.append(f"node_bad_room:{node.id}")
        elif not room.poly.contains(Point(node.point)) or \
                room.poly.exterior.distance(Point(node.point)) < float(config.NODE_CLEARANCE_M) * s - config.TOL_M * s:
            flags.append(f"node_clearance:{node.id}")
    covered = {n.room_id for n in node_map.values()}
    flags += [f"room_without_node:{rid}" for rid, r in rooms.items() if r.eligible and rid not in covered]

    return CleanPlan(plan_id=int(plan["id"]), scale=s, inner=inner, walls=walls, windows=windows,
                     front_door=front_door, rooms=rooms, doors=doors, passages=passages, links=links,
                     free=free, nodes=node_map, tracks=None, flags=flags)
