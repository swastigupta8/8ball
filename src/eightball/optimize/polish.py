"""Polish (handoff 6 step 9, BUILD_SPLIT A12): improve the chosen solution without ever making it worse.

Moves, each accepted only if the true J of the whole mix (core metrics, every ring and every clash) drops and the
ring stays legal (no overlap except retracing inside a dead-end room):
  * rip-up and reroute: one loop leg is re-routed, in the same cycle,
      - "avoid":   off the edges of every other ring's cable and of its own other legs,
      - "touch":   paying X = 5 on every vertex any other cable uses,
      - "lane":    off its own current edges (another lane or another route);
    the hub is then placed again (hub.best_hub) on the changed loop;
  * clean polylines (clean_leg): no duplicate points, no collinear middle vertices, exact node and hub coordinates.
A room swap between neighbouring zones is not a move: the ladder already tried every fewest-hub split.
"""
from __future__ import annotations

import dataclasses
import time

from eightball.core.contracts import CleanPlan
from eightball.optimize import loops as loops_mod
from eightball.optimize.clash import Candidate, ClashTable, make_candidate
from eightball.optimize.hub import HubContext, RankedLoop, best_hub
from eightball.routing.api import HEADINGS, Polyline
from eightball.routing.astar import INF, HananRouter

CROSS = 5.0


def clean_leg(poly, tol: float = 1e-9) -> Polyline:
    """Drop duplicate points and collinear middle vertices; the two end points are kept exactly."""
    pts = [tuple(p) for p in poly]
    out = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - out[-1][0]) > tol or abs(p[1] - out[-1][1]) > tol:
            out.append(p)
    keep = [out[0]]
    for i in range(1, len(out) - 1):
        a, b, c = keep[-1], out[i], out[i + 1]
        d1, d2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        straight = abs(d1[0] * d2[1] - d1[1] * d2[0]) <= tol * (abs(d1[0]) + abs(d1[1]) + abs(d2[0]) + abs(d2[1])) \
            and d1[0] * d2[0] + d1[1] * d2[1] > 0
        if not straight:
            keep.append(b)
    keep.append(out[-1])
    return keep


def polyline_edges(router: HananRouter, poly) -> list[int]:
    """Grid edge ids along a polyline whose corners are grid vertices (pieces that aren't are skipped)."""
    g = router.grid
    edges: list[int] = []
    for p, q in zip(poly, poly[1:]):
        a, b = g.vertex_at(p), g.vertex_at(q)
        if a is None or b is None or a == b:
            continue
        heading = (0 if q[0] > p[0] else 2) if abs(q[1] - p[1]) < abs(q[0] - p[0]) else (1 if q[1] > p[1] else 3)
        v, walk = a, []
        while v != b and len(walk) < 100_000:
            w = int(g.nbr[heading][v])
            if w < 0:
                walk = []
                break
            walk.append(int(g.nbr_edge[heading][v]))
            v = w
        edges += walk if v == b else []
    return edges


def _cable_of(router: HananRouter, cand: Candidate) -> tuple[set[int], set[int]]:
    """(edges, vertices) the grid cable of a candidate ring uses."""
    g = router.grid
    edges = set(polyline_edges(router, cand.points))
    verts: set[int] = set()
    for e in edges:
        verts.add(int(g.e_a[e]))
        verts.add(int(g.e_b[e]))
    return edges, verts


def _variants(cp, router, allowed, loop, k, mode, others_edges, others_verts):
    """Alternative polyline for leg k of a loop, or None."""
    n = loop.n
    a, b = loop.order[k], loop.order[(k + 1) % n]
    room_of = {nd.id: nd.room_id for nd in cp.nodes.values()}
    g = router.grid
    forbid: set[int] = set()
    contacts: dict[int, float] = {}
    node_vertices = {router.vertex_of(v) for v in loop.order}
    for j in range(n):
        if j == k:
            continue
        own = set(polyline_edges(router, loop.legs[j]))
        ok_edges: set[int] = set()
        for v in loops_mod._pair_nodes(k, j, n, loop.order):
            if v in loop.retrace:
                ok_edges |= loops_mod._retrace_edges(router, cp, room_of[v])
        forbid |= own - ok_edges
        for e in own:
            for vtx in (int(g.e_a[e]), int(g.e_b[e])):
                if vtx not in node_vertices:
                    contacts[vtx] = CROSS
    if mode == "avoid":
        forbid |= others_edges
    elif mode == "touch":
        for vtx in others_verts:
            if vtx not in node_vertices:
                contacts[vtx] = CROSS
    elif mode == "lane":
        forbid |= set(polyline_edges(router, loop.legs[k]))
    for hs, he in (((loop.h_out[k],), (loop.h_in[(k + 1) % n],)), (HEADINGS, HEADINGS)):
        cost, poly, _ = router.route(allowed, a, b, hs, he, forbid, contacts)
        if cost < INF:
            return poly
    return None


def _with_leg(cp: CleanPlan, loop, k: int, poly) -> loops_mod.Loop | None:
    legs = [list(l) for l in loop.legs]
    legs[k] = [tuple(p) for p in poly]
    room_of = {nd.id: nd.room_id for nd in cp.nodes.values()}
    if loops_mod._illegal_overlap(cp, legs, loop.order, frozenset(loop.retrace), room_of, cp.scale) != 0:
        return None
    sc = loops_mod._score(cp, loop.order, legs)
    return dataclasses.replace(loop, legs=tuple(tuple(map(tuple, l)) for l in legs),
                               L=sc["L"], X=sc["X"], O=sc["O"], B=sc["B"], J=sc["J"])


def polish(cp: CleanPlan, router: HananRouter, ctx: HubContext, cands: list[Candidate], table: ClashTable,
           deadline: float, max_passes: int = 3) -> tuple[list[Candidate], dict]:
    """Return the polished candidates and a report. J never goes up."""
    cands = list(cands)
    j_start = j = table.exact(cands)["J"]
    tried = accepted = 0
    stamp = 0
    for _ in range(max_passes):
        improved = False
        for ci in range(len(cands)):
            loop = cands[ci].ranked.loop
            if loop.n < 2:
                continue
            allowed = router.allowed_rooms_for(loop.rooms)
            others = cands[:ci] + cands[ci + 1:]
            o_edges: set[int] = set()
            o_verts: set[int] = set()
            for oc in others:
                e, v = _cable_of(router, oc)
                o_edges |= e
                o_verts |= v
            for k in range(loop.n):
                if time.perf_counter() > deadline:
                    return cands, _report(j_start, j, tried, accepted)
                for mode in ("avoid", "touch", "lane"):
                    cur = cands[ci].ranked.loop
                    poly = _variants(cp, router, allowed, cur, k, mode, o_edges, o_verts)
                    if poly is None or [tuple(p) for p in poly] == [tuple(p) for p in cur.legs[k]]:
                        continue
                    new_loop = _with_leg(cp, cur, k, poly)
                    if new_loop is None:
                        continue
                    hub = best_hub(ctx, new_loop)
                    if hub is None:
                        continue
                    tried += 1
                    stamp += 1
                    rl = RankedLoop(new_loop, hub, new_loop.J + hub.extra)
                    cand = make_candidate(cp, f"{cands[ci].cid}~{stamp}", rl)
                    trial = cands[:ci] + [cand] + cands[ci + 1:]
                    j2 = table.exact(trial)["J"]
                    if j2 < j - 1e-9:
                        cands, j, improved = trial, j2, True
                        accepted += 1
        if not improved:
            break
    return cands, _report(j_start, j, tried, accepted)


def _report(j0: float, j1: float, tried: int, accepted: int) -> dict:
    return {"J_before": j0, "J_after": j1, "moves_tried": tried, "moves_accepted": accepted}
