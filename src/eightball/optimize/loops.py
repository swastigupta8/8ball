"""Loop enumeration (handoff 6 step 5, BUILD_SPLIT A8).

A loop is a closed cycle through a zone's nodes (no hub yet: the hub is inserted into it afterwards, see hub.py).
For a zone of n nodes there are (n-1)!/2 cycles (a reversed cycle is the same loop; n = 2 gives one cycle).

For every cycle:
  1. cost tables of every leg for all 4 x 4 start/arrival headings come from the Hanan router;
  2. a dynamic programme over the cycle picks the heading at every node (leaving / arriving) that minimises
     metres + 0.5 per bend, including the turn at each node;
  3. legs are built by independent shortest paths; if that makes legs overlap illegally they are re-routed one
     after another with the edges of the earlier legs forbidden ("lanes");
  4. at a dead-end room (a single door or passage) the ring may retrace its own path (overlap + one reversal) or
     leave on a separate lane; both are tried and the cheaper one kept. Anywhere else overlap is illegal
     (RETRACE_ONLY_SINGLE_DOOR), so a loop whose legs still overlap there is marked not clean;
  5. the loop is scored with the true metrics (core.metrics): L, X, O, B, J, so self-crossings and overlap count.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.ops import unary_union

from eightball import config
from eightball.core import metrics
from eightball.core.contracts import CleanPlan
from eightball.routing.api import HEADINGS, Polyline
from eightball.routing.astar import INF, HananRouter
from eightball.routing.crude import poly_cost  # noqa: F401  (re-exported for callers that cost polylines)

TURN = 0.5
OVERLAP_TOL_M = 0.002


@dataclass(frozen=True)
class Loop:
    rooms: tuple[str, ...]            # the zone's room ids (sorted)
    order: tuple[str, ...]            # node ids in visiting order; leg k runs order[k] -> order[(k + 1) % n]
    legs: tuple[tuple[tuple[float, float], ...], ...]
    h_in: tuple[int, ...]             # per node: heading it is arrived at
    h_out: tuple[int, ...]            # per node: heading it is left along
    retrace: tuple[str, ...]          # nodes where the ring retraces its own path
    L: float
    X: int
    O: float
    B: int
    J: float
    clean: bool                       # no overlap except retracing at dead-end rooms

    @property
    def n(self) -> int:
        return len(self.order)


def dead_end_rooms(cp: CleanPlan) -> set[str]:
    """Rooms with a single door or passage to the rest of the building (two doors to one neighbour are two doors)."""
    from eightball.geometry.doorgraph import OUTDOOR
    openings: dict[str, int] = {rid: 0 for rid in cp.rooms}
    for door in cp.doors.values():
        for rid in door.rooms:
            if cp.rooms[rid].type not in OUTDOOR and all(cp.rooms[o].type not in OUTDOOR for o in door.rooms):
                openings[rid] += 1
    for passage in cp.passages.values():
        for rid in passage.rooms:
            if all(cp.rooms[o].type not in OUTDOOR for o in passage.rooms):
                openings[rid] += 1
    return {rid for rid, n in openings.items() if n == 1}


def _open_ring(poly, scale: float) -> metrics.Ring:
    """A polyline as an open 'ring' (no closing segment), for overlap tests between two legs."""
    pts: list[metrics.IPoint] = []
    for p in poly:
        q = metrics.snap_point(p, scale)
        if not pts or q != pts[-1]:
            pts.append(q)
    ring = metrics.Ring(pts, frozenset())
    ring.segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    return ring


def leg_overlap(poly_a, poly_b, scale: float) -> float:
    """Length (metres) two legs run along the same line."""
    a, b = _open_ring(poly_a, scale), _open_ring(poly_b, scale)
    return max(0.0, metrics.crossings_and_overlap([a, b])[1] - metrics.crossings_and_overlap([a])[1]
               - metrics.crossings_and_overlap([b])[1])


def _heading_dp(tables: list[list[list[float]]]) -> tuple[float, list[int], list[int]] | None:
    """Best (cost, h_out per node, h_in per node) over a cycle; tables[k][ho][hi] is leg k's cost."""
    n = len(tables)
    best = (INF, [], [])
    for x in HEADINGS:  # heading leaving node 0
        dp = {hi: tables[0][x][hi] for hi in HEADINGS}   # arrival heading at node 1
        back: list[dict[int, tuple[int, int]]] = [{}]
        for k in range(1, n):
            new: dict[int, float] = {}
            choice: dict[int, tuple[int, int]] = {}
            for hn in HEADINGS:
                cand = (INF, (0, 0))
                for hi in HEADINGS:       # arrived at node k with hi
                    if dp[hi] == INF:
                        continue
                    for ho in HEADINGS:   # leaves node k with ho
                        c = dp[hi] + (0.0 if hi == ho else TURN) + tables[k][ho][hn]
                        if c < cand[0]:
                            cand = (c, (hi, ho))
                new[hn], choice[hn] = cand
            dp, back = new, back + [choice]
        for h0 in HEADINGS:               # arrived back at node 0 with h0
            total = dp[h0] + (0.0 if h0 == x else TURN)
            if total < best[0]:
                h_in, h_out = [0] * n, [0] * n
                h_in[0], h_out[0] = h0, x
                hn = h0
                for k in range(n - 1, 0, -1):
                    hi, ho = back[k][hn]
                    h_in[k], h_out[k] = hi, ho
                    hn = hi
                best = (total, h_out, h_in)
    return best if best[0] < INF else None


def retrace_region(cp: CleanPlan, room_id: str):
    """Where a ring may retrace its own cable for a dead-end room: the room itself and its door gaps."""
    cached = getattr(cp, "_retrace_regions", None)
    if cached is None:
        cached = {}
        cp._retrace_regions = cached  # type: ignore[attr-defined]
    if room_id not in cached:
        parts = [cp.rooms[room_id].poly] + [cp.doors[d].poly for d in cp.rooms[room_id].door_ids if d in cp.doors]
        cached[room_id] = unary_union(parts).buffer(0.02 * cp.scale)
    return cached[room_id]


def _retrace_edges(router: HananRouter, cp: CleanPlan, room_id: str) -> set[int]:
    """Grid edges inside a dead-end room's retrace region."""
    cache = router.__dict__.setdefault("_retrace_edge_cache", {})
    if room_id not in cache:
        g = router.grid
        mx = (g.vx[g.e_a] + g.vx[g.e_b]) / 2
        my = (g.vy[g.e_a] + g.vy[g.e_b]) / 2
        region = retrace_region(cp, room_id)
        shapely.prepare(region)
        cache[room_id] = set(np.nonzero(shapely.covers(region, shapely.points(mx, my)))[0].tolist())
    return cache[room_id]


def _pair_nodes(k: int, j: int, n: int, order) -> list[str]:
    """The stops two legs share if they are consecutive (one or two nodes), else none."""
    out = []
    if (k - j) % n == 1:
        out.append(order[k])
    if (j - k) % n == 1:
        out.append(order[j])
    return out


CROSS = 5.0   # X weight: what a crossing or touch costs the router


def _build_legs(cp: CleanPlan, router: HananRouter, allowed, order, h_out, h_in, retrace: frozenset[str],
                room_of: dict[str, str], scale: float) -> list[Polyline] | None:
    """Legs of one cycle: independent shortest paths if they make a legal ring, and routed-in-turn variants where
    each leg stays off the edges of the earlier ones (lanes) and pays a penalty for touching their cable. Of the
    legal rings the cheapest by true J is returned."""
    n = len(order)
    best: tuple[float, list[Polyline]] | None = None

    def consider(legs: list[Polyline] | None) -> None:
        nonlocal best
        if legs is None or _illegal_overlap(cp, legs, order, retrace, room_of, scale) != 0:
            return
        j = _score(cp, order, legs)["J"]
        if best is None or j < best[0] - 1e-9:
            best = (j, legs)

    legs = [router.cost(allowed, order[k], h_out[k], order[(k + 1) % n], h_in[(k + 1) % n])[1] for k in range(n)]
    if not any(not leg for leg in legs):
        consider(legs)
    if n >= 2:
        node_vertices = {router.vertex_of(v) for v in order}
        lengths = [sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(leg, leg[1:])) for leg in legs]             if not any(not leg for leg in legs) else list(range(n))
        orders = [list(range(n)), list(range(n - 1, -1, -1)), sorted(range(n), key=lambda k: -lengths[k])]
        seen = []
        for seq in orders:
            if seq not in seen:
                seen.append(seq)
                consider(_route_in_turn(cp, router, allowed, order, h_out, h_in, retrace, room_of, seq, node_vertices))
    return best[1] if best is not None else None


def _route_in_turn(cp, router, allowed, order, h_out, h_in, retrace, room_of, seq, node_vertices
                   ) -> list[Polyline] | None:
    n = len(order)
    g = router.grid
    legs: list[Polyline | None] = [None] * n
    edges: list[list[int] | None] = [None] * n
    for k in seq:
        a, b = order[k], order[(k + 1) % n]
        forbid: set[int] = set()
        contacts: dict[int, float] = {}
        for j in range(n):
            if edges[j] is None:
                continue
            ok_edges: set[int] = set()
            for v in _pair_nodes(k, j, n, order):
                if v in retrace:
                    ok_edges |= _retrace_edges(router, cp, room_of[v])
            forbid |= set(edges[j]) - ok_edges
            for e in edges[j]:
                for vtx in (int(g.e_a[e]), int(g.e_b[e])):
                    if vtx not in node_vertices:
                        contacts[vtx] = CROSS
        found = None
        for hs, he in (((h_out[k],), (h_in[(k + 1) % n],)), (HEADINGS, HEADINGS)):
            cost, poly, used = router.route(allowed, a, b, hs, he, forbid, contacts)
            if cost < INF:
                found = (poly, used)
                break
        if found is None:
            return None
        legs[k], edges[k] = found
    return legs  # type: ignore[return-value]


def _illegal_overlap(cp: CleanPlan, legs, order, retrace: frozenset[str], room_of, scale: float) -> float:
    """Total overlap (m) between legs that isn't a retrace inside a dead-end room the ring retraces at."""
    n = len(legs)
    total = 0.0
    for j, k in itertools.combinations(range(n), 2):
        a, b = legs[j], legs[k]
        regions = [retrace_region(cp, room_of[v]) for v in _pair_nodes(k, j, n, order) if v in retrace] if n > 1 else []
        if regions:
            inside = unary_union(regions)
            pa = [tuple(p) for part in _outside(a, inside) for p in part]
            pb = [tuple(p) for part in _outside(b, inside) for p in part]
            parts_a, parts_b = _outside(a, inside), _outside(b, inside)
            total += sum(leg_overlap(x, y, scale) for x in parts_a for y in parts_b)
        else:
            total += leg_overlap(a, b, scale)
    return total if total > OVERLAP_TOL_M else 0.0


def _outside(poly, region) -> list[list[tuple[float, float]]]:
    """The pieces of a polyline that lie outside a region (as point lists)."""
    out = []
    diff = LineString(poly).difference(region)
    for part in getattr(diff, "geoms", [diff]):
        if isinstance(part, LineString) and not part.is_empty and part.length > 0:
            out.append([tuple(c) for c in part.coords])
    return out


def _score(cp: CleanPlan, order, legs) -> dict:
    pts: list = []
    for leg in legs:
        pts.extend(leg)
    special = {metrics.snap_point(cp.nodes[n].point, cp.scale) for n in order}
    ring = metrics.normalise(pts, special, cp.scale)
    return metrics.score_rings([ring])


def cycles(nodes: list[str]) -> list[tuple[str, ...]]:
    """Every cycle through the nodes once, starting at the first node; a reversed cycle counts once."""
    if len(nodes) <= 2:
        return [tuple(nodes)]
    first, rest = nodes[0], nodes[1:]
    return [(first, *perm) for perm in itertools.permutations(rest) if perm[0] < perm[-1]]


def best_loop(cp: CleanPlan, router: HananRouter, allowed, rooms: tuple[str, ...], order: tuple[str, ...],
              dead_ends: set[str], tables: dict) -> Loop | None:
    n = len(order)
    if n == 1:
        return Loop(rooms, order, (), (0,), (0,), (), 0.0, 0, 0.0, 0, 0.0, True)
    legs_t = []
    for k in range(n):
        key = (order[k], order[(k + 1) % n])
        if key not in tables:
            tables[key] = router.cost_table(allowed, *key)
        legs_t.append(tables[key])
    dp = _heading_dp(legs_t)
    if dp is None:
        return None
    _, h_out, h_in = dp
    room_of = {n_.id: n_.room_id for n_ in cp.nodes.values()}
    ends = [v for v in order if room_of[v] in dead_ends]

    def make(retrace: frozenset[str]) -> Loop | None:
        legs = _build_legs(cp, router, allowed, order, h_out, h_in, retrace, room_of, cp.scale)
        if legs is None:
            return None
        sc = _score(cp, order, legs)
        return Loop(rooms, order, tuple(tuple(map(tuple, leg)) for leg in legs), tuple(h_in), tuple(h_out),
                    tuple(sorted(retrace)), sc["L"], sc["X"], sc["O"], sc["B"], sc["J"], True)

    best = make(frozenset())
    if best is None:  # lanes impossible: try retracing at every dead end
        best = make(frozenset(ends)) if ends else None
    if best is None:
        return None
    retrace = set(best.retrace)
    for v in ends:  # keep a retrace where it beats a lane
        if v in retrace:
            continue
        trial = make(frozenset(retrace | {v}))
        if trial is not None and trial.J < best.J - 1e-9:
            best, retrace = trial, retrace | {v}
    return best


def enumerate_loops(cp: CleanPlan, router: HananRouter, room_ids, dead_ends: set[str] | None = None) -> list[Loop]:
    """Every loop of a zone, cheapest first (ties by node order). Loops that can't be routed are left out."""
    rooms = tuple(sorted(room_ids))
    node_of = {n.room_id: n.id for n in cp.nodes.values()}
    nodes = sorted((node_of[r] for r in rooms), key=lambda v: int(v[1:]))
    allowed = router.allowed_rooms_for(rooms)
    dead_ends = dead_end_rooms(cp) if dead_ends is None else dead_ends
    tables: dict = {}
    loops = [lp for order in cycles(nodes)
             if (lp := best_loop(cp, router, allowed, rooms, order, dead_ends, tables)) is not None]
    loops.sort(key=lambda lp: (lp.J, lp.order))
    return loops


def zone_floor(cp: CleanPlan, router: HananRouter, room_ids) -> float:
    """A valid lower bound on the J of any ring of the zone, within the track-grid model: the cheapest cycle through
    its nodes where every leg costs its cheapest path over all headings (metres + bends strictly inside the leg;
    no node turns, no crossings, no overlap, the hub free). 0 for a single node."""
    rooms = tuple(sorted(room_ids))
    node_of = {n.room_id: n.id for n in cp.nodes.values()}
    nodes = sorted((node_of[r] for r in rooms), key=lambda v: int(v[1:]))
    if len(nodes) < 2:
        return 0.0
    allowed = router.allowed_rooms_for(rooms)
    leg = {(a, b): min(min(row) for row in router.cost_table(allowed, a, b)) for a in nodes for b in nodes if a != b}
    best = INF
    for order in cycles(nodes):
        n = len(order)
        for seq in (order, order[::-1]):
            best = min(best, sum(leg[(seq[k], seq[(k + 1) % n])] for k in range(n)))
    return best
