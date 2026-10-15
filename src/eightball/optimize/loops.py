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
    """Rooms with a single door / passage to another room inside the building."""
    from eightball.geometry.doorgraph import OUTDOOR
    return {rid for rid in cp.rooms
            if sum(1 for nb in cp.links[rid] if cp.rooms[nb].type not in OUTDOOR) == 1}


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


def _shares(k: int, j: int, n: int, order, retrace: frozenset[str]) -> bool:
    """May leg k overlap leg j? Only consecutive legs meeting at a retracing node."""
    if (k - j) % n == 1 and order[k] in retrace:
        return True
    return (j - k) % n == 1 and order[j] in retrace


def _build_legs(router: HananRouter, allowed, order, h_out, h_in, retrace: frozenset[str], scale: float
                ) -> list[Polyline] | None:
    n = len(order)
    legs = [router.cost(allowed, order[k], h_out[k], order[(k + 1) % n], h_in[(k + 1) % n])[1] for k in range(n)]
    if any(not leg for leg in legs):
        return None
    if _illegal_overlap(legs, order, retrace, scale) == 0:
        return legs
    # re-route one leg after another, forbidding the edges of earlier legs (lanes)
    legs, edges = [], []
    for k in range(n):
        a, b = order[k], order[(k + 1) % n]
        forbid: set[int] = set()
        for j, e in enumerate(edges):
            if not _shares(k, j, n, order, retrace):
                forbid |= set(e)
        found = None
        for hs, he in (((h_out[k],), (h_in[(k + 1) % n],)), (HEADINGS, HEADINGS)):
            cost, poly, used = router.route(allowed, a, b, hs, he, forbid)
            if cost < INF:
                found = (poly, used)
                break
        if found is None:
            return None
        legs.append(found[0])
        edges.append(found[1])
    return legs if _illegal_overlap(legs, order, retrace, scale) == 0 else None


def _illegal_overlap(legs, order, retrace: frozenset[str], scale: float) -> float:
    n = len(legs)
    total = 0.0
    for j, k in itertools.combinations(range(n), 2):
        if n > 1 and not _shares(k, j, n, order, retrace):
            total += leg_overlap(legs[j], legs[k], scale)
    return total if total > OVERLAP_TOL_M else 0.0


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
        legs = _build_legs(router, allowed, order, h_out, h_in, retrace, cp.scale)
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
