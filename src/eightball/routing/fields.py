"""Direction-aware distance fields on the Hanan grid (handoff 6 step 6, BUILD_SPLIT A9).

A field maps (point, heading) to a cost in metres plus 0.5 per bend, over the grid restricted to the allowed rooms.
  forward  F(p, h): cost to arrive at p moving along h, having left a node along its loop heading.
  reverse  R(p, h): cost to leave p along h and arrive at a node along its loop heading.
The reverse field runs on the reversed graph with the headings kept, so it really measures p -> node (a field
computed forward from the node and read backwards would be wrong where a bend is cheaper one way than the other).
Points must be grid vertices; anything else is infinite.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

from eightball.routing.api import Point2
from eightball.routing.hanan import NO

INF = float("inf")
TURN = 0.5


@dataclass
class GridField:
    grid: object                  # TrackGrid
    dist: dict[int, float]        # state (vertex * 4 + heading) -> cost
    reverse: bool

    def value(self, point: Point2, heading: int) -> float:
        v = self.grid.vertex_at(point)
        return INF if v is None else self.dist.get(v * 4 + heading, INF)

    def at_vertex(self, vertex: int, heading: int) -> float:
        return self.dist.get(vertex * 4 + heading, INF)


def forward_field(router, allowed, node: str, heading: int) -> GridField:
    run = router._run(frozenset(allowed), router.vertex_of(node), heading)
    return GridField(router.grid, run.dist, False)


def reverse_field(router, allowed, node: str, heading: int) -> GridField:
    allowed = frozenset(allowed)
    edge_ok, nbr, nbr_edge, length = router._edge_ok(allowed), router._nbr, router._nbr_edge, router._len_m
    target = router.vertex_of(node)
    # fin[(w, h)]: cost to finish from w having arrived with heading h (0 at the node, arriving along `heading`)
    fin: dict[int, float] = {target * 4 + heading: 0.0}
    heap = [(0.0, target * 4 + heading)]
    done: set[int] = set()
    while heap:
        r, s = heapq.heappop(heap)
        if s in done:
            continue
        done.add(s)
        w2, h2 = divmod(s, 4)
        v = nbr[(h2 + 2) & 3][w2]          # the vertex from which a move along h2 reaches w2
        if v == NO:
            continue
        e = nbr_edge[(h2 + 2) & 3][w2]
        if not edge_ok[e]:
            continue
        for h in (h2, (h2 + 1) & 3, (h2 + 3) & 3):   # arrived at v along h, then continues along h2
            c = r + length[e] + (0.0 if h == h2 else TURN)
            t = v * 4 + h
            if c < fin.get(t, INF):
                fin[t] = c
                heapq.heappush(heap, (c, t))
    # leaving v along hq: the edge, then finish from the next vertex having arrived along hq
    dist: dict[int, float] = {}
    for s, c in fin.items():
        w, h = divmod(s, 4)
        v = nbr[(h + 2) & 3][w]
        if v == NO:
            continue
        e = nbr_edge[(h + 2) & 3][w]
        if edge_ok[e]:
            dist[v * 4 + h] = min(dist.get(v * 4 + h, INF), c + length[e])
    return GridField(router.grid, dist, True)
