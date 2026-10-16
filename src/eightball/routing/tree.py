"""Branching tree (handoff 6.3, BUILD_SPLIT A13): the shortest-path tree from a hub to every node of its zone.

One Dijkstra over (vertex, heading) from the hub (all four first headings, metres plus 0.5 per bend, the allowed
rooms only) gives a tree: paths to different nodes share their common prefix. The viewer draws it next to the ring
to show what a single cut costs a branching layout. The hub must be a vertex of the router's track grid
(build the tracks with the hub as an extra point).
"""
from __future__ import annotations

import heapq

from eightball.routing.api import HEADINGS, Point2, Polyline
from eightball.routing.hanan import NO

INF = float("inf")
TURN = 0.5


def branching_tree(router, allowed_rooms, hub: Point2, nodes: list[str]) -> dict[str, Polyline]:
    allowed = frozenset(allowed_rooms)
    g = router.grid
    src = g.vertex_at(hub)
    if src is None:
        raise KeyError("the hub is not a track vertex: build the tracks with it as an extra point")
    edge_ok, nbr, nbr_edge, length = router._edge_ok(allowed), router._nbr, router._nbr_edge, router._len_m
    dist: dict[int, float] = {}
    prev: dict[int, int] = {}
    heap: list[tuple[float, int]] = []
    for h in HEADINGS:
        v = nbr[h][src]
        if v != NO and edge_ok[nbr_edge[h][src]]:
            s = v * 4 + h
            dist[s] = length[nbr_edge[h][src]]
            prev[s] = -1
            heapq.heappush(heap, (dist[s], s))
    done: set[int] = set()
    while heap:
        d, s = heapq.heappop(heap)
        if s in done:
            continue
        done.add(s)
        v, h = divmod(s, 4)
        for h2 in (h, (h + 1) & 3, (h + 3) & 3):
            w = nbr[h2][v]
            if w == NO or not edge_ok[nbr_edge[h2][v]]:
                continue
            nd = d + length[nbr_edge[h2][v]] + (0.0 if h2 == h else TURN)
            t = w * 4 + h2
            if nd < dist.get(t, INF):
                dist[t] = nd
                prev[t] = s
                heapq.heappush(heap, (nd, t))
    out: dict[str, Polyline] = {}
    for n in nodes:
        vn = router.vertex_of(n)
        best = min((dist.get(vn * 4 + h, INF), vn * 4 + h) for h in HEADINGS)
        if best[0] == INF:
            continue
        states, st = [], best[1]
        while st != -1:
            states.append(st)
            st = prev[st]
        pts = [(router._vx[src], router._vy[src])] + [(router._vx[s // 4], router._vy[s // 4]) for s in reversed(states)]
        corners = [pts[0]]
        for k in range(1, len(pts) - 1):
            d1 = (pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
            d2 = (pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
            if d1[0] * d2[1] - d1[1] * d2[0] != 0:
                corners.append(pts[k])
        corners.append(pts[-1])
        corners[0] = (float(hub[0]), float(hub[1]))
        corners[-1] = router.cp.nodes[n].point
        out[n] = corners
    return out
