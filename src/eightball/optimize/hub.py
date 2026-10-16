"""Hub placement by one insertion function (handoff 6 step 6, BUILD_SPLIT A9).

Given a loop (a closed cycle through a zone's nodes), the hub is a point H inside one of the zone's eligible rooms,
at least HUB_CLEARANCE_M from every wall and room boundary, that the ring is routed through:

  insertion cost of H into leg i -> j  =  min over headings [ F_i(H, hp) + turn(hp, hq) + R_j(H, hq) ]  -  cost(i -> j)

where F_i is the forward field of node i (leaving along its loop heading), R_j the *reversed* field into node j
(arriving along its loop heading) and turn adds 0.5 for a bend at H. The hub cost of the loop is the minimum over
legs and candidate points: the extra J of routing the loop through the hub. A point that already lies on a straight
stretch of the loop's own cable is free (extra 0, "hub on the wire"). The heatmap draws this same function.

Candidate points are the vertices of a hub grid: the track grid plus a HEATMAP_STEP_M lattice over the eligible
rooms. Costs use the hub grid for both the fields and cost(i -> j), so an insertion is never negative.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from eightball import config
from eightball.core import metrics
from eightball.core.contracts import CleanPlan
from eightball.io import resplan
from eightball.io.answer_io import make_heatmap
from eightball.optimize.loops import Loop
from eightball.routing import fields as fields_mod
from eightball.routing.api import HEADINGS, Polyline, free_point_id
from eightball.routing.astar import INF, HananRouter
from eightball.routing.hanan import build_tracks

TURN = 0.5
NODE_CLEAR_M = 0.3   # a hub keeps this far from every node of its own ring (not on top of a node)
WIRE_MIN_M = 0.05    # shortest stretch of cable worth putting a hub on


@dataclass(frozen=True)
class HubPlan:
    point: tuple[float, float]
    room_id: str
    extra: float                    # true extra J of the ring through the hub over the node-only loop (core metrics);
                                    # can be negative when the hub grid finds a better lane than the loop had
    on_wire: bool
    leg: int                        # the loop leg the hub is inserted into (order[leg] -> order[leg + 1])
    to_hub: tuple[tuple[float, float], ...]    # polyline order[leg] -> hub
    from_hub: tuple[tuple[float, float], ...]  # polyline hub -> order[leg + 1]
    field_extra: float = 0.0        # the insertion function's value at the point: what the heatmap draws (>= 0)


class HubContext:
    """Per-plan helper: the hub grid, hub regions and field caches."""

    def __init__(self, cp: CleanPlan, router: HananRouter):
        self.cp, self.router = cp, router
        self._hub_router: HananRouter | None = None
        self._regions: dict[tuple[str, ...], dict[str, BaseGeometry]] = {}
        self._fields: dict[tuple, object] = {}
        self.lattice_x0 = cp.inner.bounds[0]
        self.lattice_y0 = cp.inner.bounds[1]

    # ---- geometry ------------------------------------------------------------------------------

    def room_regions(self, rooms) -> dict[str, BaseGeometry]:
        """room id -> where a hub may sit in it: the room shrunk by HUB_CLEARANCE_M and kept clear of walls."""
        key = tuple(sorted(rooms))
        if key not in self._regions:
            c = float(config.HUB_CLEARANCE_M) * self.cp.scale
            walls = self.cp.walls.buffer(c)
            out = {}
            for r in key:
                room = self.cp.rooms[r]
                if room.eligible:
                    reg = room.poly.buffer(-c).difference(walls)
                    if not reg.is_empty:
                        out[r] = reg
            self._regions[key] = out
        return self._regions[key]

    def region(self, rooms) -> BaseGeometry:
        regs = list(self.room_regions(rooms).values())
        return unary_union(regs) if regs else shapely.Polygon()

    def room_of(self, rooms, point) -> str | None:
        p = Point(point)
        best, best_depth = None, -1.0
        for rid, reg in self.room_regions(rooms).items():
            if reg.buffer(1e-9 * self.cp.scale).covers(p):
                depth = self.cp.rooms[rid].poly.exterior.distance(p)
                if depth > best_depth:
                    best, best_depth = rid, depth
        return best

    def lattice_points(self) -> list[tuple[float, float]]:
        """HEATMAP_STEP_M lattice over every eligible room's hub region (whole plan, computed once)."""
        step = float(config.HEATMAP_STEP_M) * self.cp.scale
        pts: list[tuple[float, float]] = []
        for rid in self.cp.rooms:
            for reg in self.room_regions([rid]).values():
                minx, miny, maxx, maxy = reg.bounds
                xs = self.lattice_x0 + np.arange(np.ceil((minx - self.lattice_x0) / step),
                                                 np.floor((maxx - self.lattice_x0) / step) + 1) * step
                ys = self.lattice_y0 + np.arange(np.ceil((miny - self.lattice_y0) / step),
                                                 np.floor((maxy - self.lattice_y0) / step) + 1) * step
                if len(xs) == 0 or len(ys) == 0:
                    continue
                gx, gy = np.meshgrid(xs, ys)
                inside = shapely.contains_xy(reg, gx, gy)
                pts += list(zip(gx[inside].tolist(), gy[inside].tolist()))
        return sorted(set(pts))

    @property
    def hub_router(self) -> HananRouter:
        if self._hub_router is None:
            grid = build_tracks(self.cp, extra_points=self.lattice_points(), attach=False)
            self._hub_router = HananRouter(self.cp, grid)
        return self._hub_router

    # ---- fields --------------------------------------------------------------------------------

    def field(self, allowed, node: str, heading: int, reverse: bool):
        key = (frozenset(allowed), node, heading, reverse)
        if key not in self._fields:
            hr = self.hub_router
            self._fields[key] = (fields_mod.reverse_field if reverse else fields_mod.forward_field)(
                hr, allowed, node, heading)
        return self._fields[key]


def _turn(hp: int, hq: int) -> float | None:
    """Bend cost at the hub, or None for a reversal (that would retrace the arriving cable)."""
    if hp == hq:
        return 0.0
    return TURN if (hp - hq) % 4 in (1, 3) else None


def _near_nodes(cp: CleanPlan, nodes, point, clear_m: float) -> bool:
    c = clear_m * cp.scale
    return any((cp.nodes[n].point[0] - point[0]) ** 2 + (cp.nodes[n].point[1] - point[1]) ** 2 < c * c for n in nodes)


# ---- hub on the wire ---------------------------------------------------------------------------

def wire_hub(ctx: HubContext, loop: Loop) -> tuple[tuple[float, float], str, int] | None:
    """A point on a stretch of the loop's cable that is a legal hub site and that no other cable touches."""
    cp = ctx.cp
    if loop.n < 2:
        return None
    region = ctx.region(loop.rooms)
    if region.is_empty:
        return None
    s = cp.scale
    lines = [LineString(leg) for leg in loop.legs]
    best = None
    for k, line in enumerate(lines):
        others = unary_union([ln for j, ln in enumerate(lines) if j != k]).buffer(0.01 * s)
        for n in loop.order:
            others = others.union(Point(cp.nodes[n].point).buffer(NODE_CLEAR_M * s))
        free_part = line.intersection(region.buffer(1e-9 * s)).difference(others)
        for part in getattr(free_part, "geoms", [free_part]):
            if isinstance(part, LineString) and part.length >= WIRE_MIN_M * s:
                if best is None or part.length > best[0]:
                    best = (part.length, k, part)
    if best is None:
        return None
    _, k, part = best
    p = part.interpolate(0.5, normalized=True)
    point = (p.x, p.y)
    room = ctx.room_of(loop.rooms, point)
    return (point, room, k) if room is not None else None


def split_leg(leg, point) -> tuple[Polyline, Polyline]:
    """Split a polyline at a point lying on it (the point is kept as the end / start of the two parts)."""
    pts = [tuple(p) for p in leg]
    tol = 1e-6 * max(1.0, abs(point[0]) + abs(point[1]))
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        if min(a[0], b[0]) - tol <= point[0] <= max(a[0], b[0]) + tol and \
                min(a[1], b[1]) - tol <= point[1] <= max(a[1], b[1]) + tol and \
                (abs(a[0] - b[0]) <= tol and abs(point[0] - a[0]) <= tol or
                 abs(a[1] - b[1]) <= tol and abs(point[1] - a[1]) <= tol):
            first = pts[:i + 1] + [tuple(point)]
            second = [tuple(point)] + pts[i + 1:]
            return _dedupe(first), _dedupe(second)
    raise ValueError("point is not on the polyline")


def _dedupe(pts):
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > 1e-9 or abs(p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    return out


# ---- insertion costs ---------------------------------------------------------------------------

def _insertion_at(ctx: HubContext, allowed, loop: Loop, vertex: int) -> tuple[float, int, int, int]:
    """Cheapest insertion of the hub vertex into any leg: (extra, leg, hp, hq)."""
    n = loop.n
    best = (INF, -1, 0, 0)
    for i in range(n):
        j = (i + 1) % n
        fi = ctx.field(allowed, loop.order[i], loop.h_out[i], False)
        rj = ctx.field(allowed, loop.order[j], loop.h_in[j], True)
        base = ctx.hub_router.cost_table(allowed, loop.order[i], loop.order[j])[loop.h_out[i]][loop.h_in[j]]
        for hp in HEADINGS:
            f = fi.at_vertex(vertex, hp)
            if f == INF:
                continue
            for hq in HEADINGS:
                t = _turn(hp, hq)
                if t is None:
                    continue
                r = rj.at_vertex(vertex, hq)
                if r == INF:
                    continue
                extra = f + t + r - base
                if extra < best[0]:
                    best = (extra, i, hp, hq)
    return best


def candidate_vertices(ctx: HubContext, loop: Loop, allowed) -> list[int]:
    """Hub-grid vertices inside the zone's hub regions, off the nodes, with allowed cable around them."""
    hr = ctx.hub_router
    g = hr.grid
    region = ctx.region(loop.rooms)
    if region.is_empty:
        return []
    cover = region.buffer(1e-6 * ctx.cp.scale)
    shapely.prepare(cover)
    inside = shapely.covers(cover, shapely.points(g.vx, g.vy))
    ok_edges = g.allowed_edges(allowed)
    has_edge = np.zeros(g.n_vertices, dtype=bool)
    has_edge[g.e_a[ok_edges]] = True
    has_edge[g.e_b[ok_edges]] = True
    verts = np.nonzero(inside & has_edge)[0]
    return [int(v) for v in verts
            if not _near_nodes(ctx.cp, loop.order, (g.vx[v], g.vy[v]), NODE_CLEAR_M)]


def _build_off_wire(ctx: HubContext, allowed, loop: Loop, vertex: int, leg: int, hp: int, hq: int
                    ) -> tuple[Polyline, Polyline] | None:
    hr = ctx.hub_router
    g = hr.grid
    pid = free_point_id(float(g.vx[vertex]), float(g.vy[vertex]))
    n = loop.n
    i, j = leg, (leg + 1) % n
    c1, p1 = hr.cost(allowed, loop.order[i], loop.h_out[i], pid, hp)
    c2, p2 = hr.cost(allowed, pid, hq, loop.order[j], loop.h_in[j])
    if c1 == INF or c2 == INF:
        return None
    return p1, p2


def best_hub(ctx: HubContext, loop: Loop, top: int = 6) -> HubPlan | None:
    """The cheapest hub for a loop: on the wire if any stretch allows it, else the best insertion point."""
    cp = ctx.cp
    if loop.n < 2:
        return _single_node_hub(ctx, loop)
    wire = wire_hub(ctx, loop)
    if wire is not None:
        point, room, k = wire
        to_hub, from_hub = split_leg(loop.legs[k], point)
        return HubPlan(point, room, 0.0, True, k, tuple(to_hub), tuple(from_hub))
    allowed = ctx.router.allowed_rooms_for(loop.rooms)
    scored = []
    for v in candidate_vertices(ctx, loop, allowed):
        extra, leg, hp, hq = _insertion_at(ctx, allowed, loop, v)
        if extra < INF:
            scored.append((extra, v, leg, hp, hq))
    scored.sort()
    for extra, v, leg, hp, hq in scored[:top]:   # the first insertion point that can be built
        built = _build_off_wire(ctx, allowed, loop, v, leg, hp, hq)
        if built is None:
            continue
        g = ctx.hub_router.grid
        point = (float(g.vx[v]), float(g.vy[v]))
        room = ctx.room_of(loop.rooms, point)
        if room is None:
            continue
        plan = HubPlan(point, room, 0.0, False, leg, tuple(built[0]), tuple(built[1]), field_extra=max(0.0, extra))
        return HubPlan(point, room, ring_j(cp, loop, plan) - loop.J, False, leg, plan.to_hub, plan.from_hub,
                       field_extra=plan.field_extra)
    return None


def _single_node_hub(ctx: HubContext, loop: Loop) -> HubPlan | None:
    """A zone of one node: the ring goes out and back. Retracing is allowed only at a dead-end room; otherwise
    the way back avoids the edges of the way out (a second lane)."""
    from eightball.optimize.loops import dead_end_rooms

    cp, hr = ctx.cp, ctx.hub_router
    node = loop.order[0]
    allowed = ctx.router.allowed_rooms_for(loop.rooms)
    dead = cp.nodes[node].room_id in dead_end_rooms(cp)
    g = hr.grid
    fwd = [ctx.field(allowed, node, h, False) for h in HEADINGS]   # leave the node along h
    rev = [ctx.field(allowed, node, h, True) for h in HEADINGS]    # arrive at the node along h
    scored = []
    for v in candidate_vertices(ctx, loop, allowed):
        out = min((f.at_vertex(v, hp) for f in fwd for hp in HEADINGS), default=INF)
        back = min((r.at_vertex(v, hq) for r in rev for hq in HEADINGS), default=INF)
        if out < INF and back < INF:
            scored.append((out + back, v))
    scored.sort()
    best = None
    for _, v in scored[:6]:
        point = (float(g.vx[v]), float(g.vy[v]))
        room = ctx.room_of(loop.rooms, point)
        if room is None:
            continue
        pid = free_point_id(*point)
        _, out_poly, out_edges = hr.route(allowed, node, pid)
        for retrace in ((True, False) if dead else (False,)):
            cost, back_poly, _ = hr.route(allowed, pid, node, HEADINGS, HEADINGS, None if retrace else set(out_edges))
            if cost == INF:
                continue
            plan = HubPlan(point, room, 0.0, False, 0, tuple(out_poly), tuple(back_poly))
            j = ring_j(cp, loop, plan)
            plan = HubPlan(point, room, j - loop.J, False, 0, plan.to_hub, plan.from_hub, field_extra=max(0.0, j))
            if best is None or plan.extra < best.extra - 1e-9:
                best = plan
    return best


# ---- the ring with its hub, for the answer ----------------------------------------------------

def ring_legs(loop: Loop, hub: HubPlan) -> tuple[list[str], list[Polyline]]:
    """(node visiting order starting after the hub, one polyline per leg: hub -> ... -> hub)."""
    n = loop.n
    if n == 1:
        return [loop.order[0]], [list(hub.to_hub), list(hub.from_hub)]
    i, j = hub.leg, (hub.leg + 1) % n
    order = [loop.order[(j + k) % n] for k in range(n)]
    legs = [list(hub.from_hub)] + [list(loop.legs[(j + k) % n]) for k in range(n - 1)] + [list(hub.to_hub)]
    return order, legs


def ring_j(cp: CleanPlan, loop: Loop, hub: HubPlan) -> float:
    """True J of the ring through the hub (core metrics)."""
    order, legs = ring_legs(loop, hub)
    pts: list = []
    for leg in legs:
        pts.extend(leg)
    special = {metrics.snap_point(cp.nodes[v].point, cp.scale) for v in loop.order}
    special.add(metrics.snap_point(hub.point, cp.scale))
    return metrics.score_rings([metrics.normalise(pts, special, cp.scale)])["J"]


# ---- heatmap numbers ---------------------------------------------------------------------------

def heatmap_points(ctx: HubContext, loop: Loop, hub: HubPlan) -> list[tuple[float, float, float]]:
    """(x, y, extra J) for every lattice point of the zone's hub regions, plus the chosen point."""
    allowed = ctx.router.allowed_rooms_for(loop.rooms)
    g = ctx.hub_router.grid
    step = float(config.HEATMAP_STEP_M) * ctx.cp.scale
    region = ctx.region(loop.rooms)
    pts = []
    if loop.n >= 2 and not region.is_empty:
        cover = region.buffer(1e-6 * ctx.cp.scale)
        for v in candidate_vertices(ctx, loop, allowed):
            x, y = float(g.vx[v]), float(g.vy[v])
            fx = (x - ctx.lattice_x0) / step
            fy = (y - ctx.lattice_y0) / step
            if abs(fx - round(fx)) > 1e-6 or abs(fy - round(fy)) > 1e-6 or not cover.covers(Point(x, y)):
                continue
            extra = _insertion_at(ctx, allowed, loop, v)[0]
            if extra < INF:
                pts.append((x, y, max(0.0, extra)))
    pts.append((hub.point[0], hub.point[1], 0.0 if hub.on_wire else hub.field_extra))
    return pts


def make_heatmap_doc(ctx: HubContext, loop: Loop, hub: HubPlan, hub_id: str) -> dict:
    return make_heatmap(ctx.cp.plan_id, hub_id, heatmap_points(ctx, loop, hub), hub.point)


# ---- ranking -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class RankedLoop:
    loop: Loop
    hub: HubPlan
    total: float          # loop J + hub cost


def ranked_loops(ctx: HubContext, loops: list[Loop], topk: int | None = None) -> list[RankedLoop]:
    """Loops with their hubs, cheapest (loop J + hub cost) first, the top TOPK_LOOPS kept. A loop whose zone
    has no legal hub site is dropped."""
    topk = int(config.TOPK_LOOPS) if topk is None else topk
    out = []
    for lp in loops:
        hub = best_hub(ctx, lp)
        if hub is not None:
            out.append(RankedLoop(lp, hub, lp.J + hub.extra))
    out.sort(key=lambda r: (r.total, r.loop.order))
    return out[:topk]
