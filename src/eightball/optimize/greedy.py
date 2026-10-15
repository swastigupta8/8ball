"""Greedy baseline solver (handoff 8.5, BUILD_SPLIT A4). Also the comparison method for the "W% cheaper" claim.

1. Grow zones: start from the largest unassigned eligible room and add the neighbour (over door/passage links
   between eligible rooms) with the largest area that keeps <= MAX_AREA_M2 and <= MAX_NODES_PER_HUB.
2. Hub = the pole of inaccessibility of the zone's largest room, shrunk by HUB_CLEARANCE_M.
3. Order = nearest neighbour from the hub (by routed cost).
4. Legs = shortest paths on the crude router, each kept off the cells of the ring's earlier legs so a ring never
   overlaps itself or crosses itself (a dead-end room is left by a neighbouring lane, not by retracing).
A zone whose cable can't be routed is split into one zone per room, so the result stays valid.
"""
from __future__ import annotations

import itertools

import numpy as np
import shapely
from shapely.ops import polylabel

from eightball import config
from eightball.core.contracts import CleanPlan
from eightball.io import resplan
from eightball.routing import api
from eightball.routing.crude import CrudeRouter

INF = float("inf")
MAX_ORDER_TRIES = 12  # other node orders tried when the nearest-neighbour order walls itself in


def grow_zones(cp: CleanPlan) -> list[list[str]]:
    eligible = [rid for rid, r in cp.rooms.items() if r.eligible]
    adjacent = {rid: sorted(n for n in cp.links[rid] if cp.rooms[n].eligible) for rid in eligible}
    area = {rid: cp.rooms[rid].area_m2 for rid in eligible}
    unassigned = set(eligible)
    zones: list[list[str]] = []
    while unassigned:
        seed = max(sorted(unassigned), key=lambda r: area[r])
        zone, total = [seed], area[seed]
        unassigned.discard(seed)
        while len(zone) < int(config.MAX_NODES_PER_HUB):
            options = sorted({n for r in zone for n in adjacent[r]
                              if n in unassigned and total + area[n] <= float(config.MAX_AREA_M2) + 1e-9})
            if not options:
                break
            pick = max(options, key=lambda r: area[r])
            zone.append(pick)
            total += area[pick]
            unassigned.discard(pick)
        zones.append(zone)
    return zones


def hub_point(cp: CleanPlan, zone: list[str]) -> tuple[tuple[float, float], str, bool]:
    """(point, room id, clear): the deepest point of a zone room that keeps the 0.5 m margin and stays off the nodes.

    A hub sitting exactly on a node would make every leg share that point and its lines, so candidates within
    0.5 m of a node are skipped when any other exist. Falls back to the room's pole of inaccessibility.
    """
    s = cp.scale
    clearance = float(config.HUB_CLEARANCE_M) * s
    node_pts = np.array([n.point for n in cp.nodes.values() if n.room_id in zone]).reshape(-1, 2)
    for rid in sorted(zone, key=lambda r: -cp.rooms[r].area_m2):
        shrunk = cp.rooms[rid].poly.buffer(-clearance)
        polys = [p for p in resplan.parts(shrunk) if p.area > 0]
        if not polys:
            continue
        best = max(polys, key=lambda p: p.area)
        minx, miny, maxx, maxy = best.bounds
        step = 0.25 * s
        gx, gy = np.meshgrid(np.arange(minx, maxx + step, step), np.arange(miny, maxy + step, step))
        inside = shapely.contains_xy(best, gx, gy)
        pts = np.column_stack([gx[inside], gy[inside]])
        if len(pts):
            depth = shapely.distance(shapely.points(pts), best.boundary)
            gap = np.min(np.hypot(pts[:, None, 0] - node_pts[None, :, 0], pts[:, None, 1] - node_pts[None, :, 1]),
                         axis=1) if len(node_pts) else np.full(len(pts), np.inf)
            for min_gap in (0.5 * s, 0.3 * s, 0.1 * s):
                mask = gap >= min_gap
                if mask.any():
                    k = int(np.argmax(np.where(mask, depth, -1.0)))
                    return (float(pts[k, 0]), float(pts[k, 1])), rid, True
        c = polylabel(best, tolerance=0.01 * s)
        return (c.x, c.y), rid, True
    rid = max(zone, key=lambda r: cp.rooms[r].area_m2)
    c = polylabel(cp.rooms[rid].poly, tolerance=0.01 * s)
    return (c.x, c.y), rid, False


def _heading(p, q) -> int:
    if abs(q[0] - p[0]) >= abs(q[1] - p[1]):
        return api.EAST if q[0] > p[0] else api.WEST
    return api.NORTH if q[1] > p[1] else api.SOUTH


def _route_order(router: CrudeRouter, allowed: frozenset[str], hub_id: str, order: list[str], level: int
                 ) -> list[list[tuple[float, float]]] | None:
    """Legs hub -> order... -> hub. level 0: no leg crosses the previous leg (or, when closing, the first), and
    no leg runs along an earlier one; level 1: may cross the previous leg; level 2: may share lanes.

    A leg never leaves a point along the line the previous leg arrived on, in the opposite direction (that would
    retrace it), and the closing leg never arrives along the first leg's line in the opposite direction.
    """
    legs: list[list[tuple[float, float]]] = []
    cells_by_leg: list[dict[int, int]] = []
    used: dict[int, int] = {}
    here, arrived = hub_id, None  # arrived: heading of the last segment of the previous leg
    stops = [*order, hub_id]
    for i, target in enumerate(stops):
        starts = api.HEADINGS if arrived is None else tuple(h for h in api.HEADINGS if h != api.opposite(arrived))
        ends = api.HEADINGS
        closing = i == len(stops) - 1
        if closing:
            first = _heading(legs[0][0], legs[0][1])
            ends = tuple(h for h in api.HEADINGS if h != api.opposite(first))
        # Consecutive legs share a stop; keep them from crossing each other at all (a ring's first and last legs
        # share the hub, so the closing leg also stays off the first).
        hard = dict(used)
        for leg_cells in ([cells_by_leg[-1]] if cells_by_leg else []) + ([cells_by_leg[0]] if closing else []):
            for c in leg_cells:
                hard[c] = 3
        attempts = [(hard, starts, ends), (hard, api.HEADINGS, api.HEADINGS)]
        if level >= 1:
            attempts += [(used, starts, ends), (used, api.HEADINGS, api.HEADINGS)]
        if level >= 2:
            attempts += [(None, starts, ends), (None, api.HEADINGS, api.HEADINGS)]
        poly = None
        for avoid, s_h, e_h in attempts:
            cost, found = router.route(allowed, here, target, avoid, s_h, e_h)
            if cost < INF:
                poly = found
                break
        if poly is None:
            return None
        legs.append(poly)
        cells = router.cells_of(poly)
        cells_by_leg.append(cells)
        for c, m in cells.items():
            used[c] = used.get(c, 0) | m
        here, arrived = target, _heading(poly[-2], poly[-1])
    return legs


def route_ring(router: CrudeRouter, zone: list[str], hub: tuple[float, float], node_ids: list[str]
               ) -> tuple[list[str], list[list[tuple[float, float]]]] | None:
    """Order and legs of one ring, or None if some leg can't be routed.

    Tries the nearest-neighbour order first, then the other orders cheapest first (an early leg can wall off the
    hub), at three levels of strictness (see _route_order).
    """
    allowed = router.allowed_rooms_for(zone)
    hub_id = api.free_point_id(*hub)
    ids = [hub_id, *node_ids]
    dist = {(a, b): router.shortest(allowed, a, b)[0] for a in ids for b in ids if a != b}
    if any(dist[(hub_id, n)] == INF or dist[(n, hub_id)] == INF for n in node_ids):
        return None
    order, here, left = [], hub_id, list(node_ids)
    while left:
        nxt = min(left, key=lambda n: (dist[(here, n)], n))
        order.append(nxt)
        left.remove(nxt)
        here = nxt
    others = []
    for perm in itertools.permutations(node_ids):
        if list(perm) != order and perm[0] < perm[-1]:  # a reversed order is the same cycle; keep one
            stops = [hub_id, *perm, hub_id]
            others.append((sum(dist[(a, b)] for a, b in zip(stops, stops[1:])), list(perm)))
    others.sort(key=lambda t: (t[0], t[1]))
    candidates = [order] + [o for _, o in others[:MAX_ORDER_TRIES]]
    for level in (0, 1):
        for candidate in candidates:
            legs = _route_order(router, allowed, hub_id, candidate, level)
            if legs is not None:
                return candidate, legs
    legs = _route_order(router, allowed, hub_id, order, 2)
    return (order, legs) if legs is not None else None


def solve_zones(cp: CleanPlan, router: CrudeRouter) -> tuple[list[dict], list[str]]:
    """Rings for every zone: [{"zone", "hub", "hub_room", "order", "legs"}], plus warnings."""
    node_of_room = {n.room_id: n.id for n in cp.nodes.values()}
    warnings: list[str] = []
    rings: list[dict] = []

    def attempt(zone: list[str]) -> dict | None:
        zone = [r for r in zone if r in node_of_room]
        if not zone:
            return None
        hub, hub_room, clear = hub_point(cp, zone)
        routed = route_ring(router, zone, hub, [node_of_room[r] for r in zone])
        if routed is None:
            return None
        if not clear:
            warnings.append(f"hub_clearance:{hub_room}")
        order, legs = routed
        return {"zone": zone, "hub": hub, "hub_room": hub_room, "order": order, "legs": legs}

    for zone in grow_zones(cp):
        ring = attempt(zone)
        if ring is not None:
            rings.append(ring)
            continue
        warnings.append(f"zone_split:{'+'.join(zone)}")
        for room in zone:
            single = attempt([room])
            if single is None:
                warnings.append(f"unroutable:{room}")
            else:
                rings.append(single)
    rings.sort(key=lambda r: min(int(n[1:]) for n in r["order"]))
    return rings, warnings
