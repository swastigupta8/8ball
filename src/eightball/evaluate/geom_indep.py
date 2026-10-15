"""The checker's own minimal geometry (Person B, B2 / handoff S1.4). Never imports eightball.geometry.

Only room IDs come from the shared `io.resplan.room_parts`, so the checker and the solver agree on
names. Everything else (walls, door links, passages) is computed here from the raw plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

import networkx as nx
import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from eightball import config
from eightball.io import resplan


@dataclass
class CheckGeom:
    plan_id: int
    scale: float
    inner: BaseGeometry
    walls: BaseGeometry          # walls with door shapes subtracted
    windows: BaseGeometry
    doors: list[Polygon]         # door parts, front door excluded
    rooms: dict[str, Polygon]    # every room (eligible and excluded) by canonical id
    room_type: dict[str, str]
    eligible: set[str]
    area_m2: dict[str, float]
    links: nx.MultiGraph         # rooms as nodes; one edge per door or passage
    passages: list[BaseGeometry] = field(default_factory=list)
    blockers: BaseGeometry | None = None  # walls + windows, for clearance checks

    def degree(self, room_id: str) -> int:
        return self.links.degree(room_id) if room_id in self.links else 0


def _valid(g):
    if g is None or g.is_empty:
        return Polygon()
    return shapely.make_valid(g)


def _wall_depth(plan: dict, s: float) -> float:
    d = plan.get("wall_depth")
    try:
        d = float(d)
    except (TypeError, ValueError):
        d = 0.0
    return d if d > 0 else 0.2 * s


def build(plan: dict) -> CheckGeom:
    s = resplan.scale(plan)
    inner = _valid(plan["inner"])
    door_all = _valid(plan.get("door"))
    front = _valid(plan.get("front_door"))
    walls = _valid(plan.get("wall")).difference(door_all)
    windows = _valid(plan.get("window"))

    rooms, room_type = {}, {}
    for rid, rtype, poly in resplan.room_parts(plan):
        rooms[rid], room_type[rid] = poly, rtype
    eligible = {rid for rid, t in room_type.items() if t in resplan.ELIGIBLE}
    area_m2 = {rid: rooms[rid].area / (s * s) for rid in rooms}

    doors = []
    for d in resplan.parts(door_all):
        if not front.is_empty and d.intersection(front).area > 0.5 * d.area:
            continue
        doors.append(d)

    links = nx.MultiGraph()
    links.add_nodes_from(rooms)
    depth = _wall_depth(plan, s)
    reach = 0.6 * depth + 0.02 * s
    for k, d in enumerate(doors):
        zone = d.buffer(reach)
        contacts = []
        for rid, poly in rooms.items():
            c = poly.boundary.intersection(zone).length
            if c > 0.05 * s:
                contacts.append((c, rid))
        contacts.sort(reverse=True)
        if len(contacts) >= 2 and contacts[1][0] >= 0.25 * contacts[0][0]:
            links.add_edge(contacts[0][1], contacts[1][1], kind="door", ref=k)

    blocked = unary_union([walls.buffer(0.01 * s), unary_union(doors).buffer(0.01 * s) if doors else Polygon(),
                           windows.buffer(0.01 * s)])
    passages = []
    eps = 0.6 * depth
    min_width = float(config.PASSAGE_MIN_WIDTH_M) * s
    grown = {rid: poly.buffer(eps) for rid, poly in rooms.items()}
    for a, b in combinations(rooms, 2):
        if not grown[a].intersects(grown[b]):
            continue
        shared = grown[a].intersection(grown[b]).intersection(inner).difference(blocked)
        for part in resplan.parts(shared):
            minx, miny, maxx, maxy = part.bounds
            if max(maxx - minx, maxy - miny) >= min_width:
                links.add_edge(a, b, kind="passage", ref=len(passages))
                passages.append(part)
                break

    blockers = unary_union([walls, windows])
    return CheckGeom(plan_id=int(plan["id"]), scale=s, inner=inner, walls=walls, windows=windows, doors=doors,
                     rooms=rooms, room_type=room_type, eligible=eligible, area_m2=area_m2, links=links,
                     passages=passages, blockers=blockers)


def zone_connected(g: CheckGeom, room_ids: set[str], via_excluded: bool = False) -> bool:
    """Rooms connected using only door/passage links between rooms of the zone.

    With via_excluded, paths may also pass through excluded (un-noded) rooms."""
    if not room_ids:
        return False
    allowed = set(room_ids)
    if via_excluded:
        allowed |= {r for r in g.rooms if r not in g.eligible}
    sub = nx.Graph()
    sub.add_nodes_from(allowed)
    for a, b in g.links.edges():
        if a in allowed and b in allowed:
            sub.add_edge(a, b)
    component = nx.node_connected_component(sub, next(iter(room_ids)))
    return set(room_ids) <= component
