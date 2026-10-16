"""Clash table between candidate loops of different zones (handoff 6 step 7, BUILD_SPLIT A10).

A candidate is one ranked loop of a zone with its hub: a closed ring through the hub and the zone's nodes.
Two rings from different zones can cross (X, 5 each) or run along the same line (O, 1 per metre). For two rings
core.metrics.clash gives exactly the extra X and O they add on top of their own scores, so

    mix J  =  sum of ring J  +  sum over pairs of (5 * crossings + shared length)

is exact for up to two rings. With three or more rings it overcounts a point or stretch shared by 3+ rings, so the
best few mixes are re-scored with the full core.metrics.score_rings (``rescore``).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from eightball.core import metrics
from eightball.core.contracts import CleanPlan
from eightball.optimize.hub import RankedLoop, ring_legs


@dataclass(frozen=True)
class Candidate:
    cid: str                       # unique id, e.g. "Z7#2" (zone, rank)
    rooms: frozenset[str]
    ranked: RankedLoop
    points: tuple[tuple[float, float], ...]   # the closed ring's polyline, hub first
    special: tuple[tuple[float, float], ...]  # this ring's own node and hub points
    J: float                       # true ring J (core.metrics), hub included

    @property
    def area_key(self) -> frozenset[str]:
        return self.rooms


def make_candidate(cp: CleanPlan, cid: str, rl: RankedLoop) -> Candidate:
    order, legs = ring_legs(rl.loop, rl.hub)
    pts: list[tuple[float, float]] = []
    for leg in legs:
        pts.extend(tuple(p) for p in leg)
    special = tuple(cp.nodes[n].point for n in rl.loop.order) + (tuple(rl.hub.point),)
    ring = metrics.normalise(pts, {metrics.snap_point(p, cp.scale) for p in special}, cp.scale)
    return Candidate(cid=cid, rooms=frozenset(rl.loop.rooms), ranked=rl, points=tuple(pts), special=special,
                     J=metrics.score_rings([ring])["J"])


class ClashTable:
    def __init__(self, cp: CleanPlan):
        self.cp = cp
        self._cache: dict[tuple[str, str], tuple[int, float]] = {}

    def clash(self, a: Candidate, b: Candidate) -> tuple[int, float]:
        """(crossings, shared length in metres) that the two rings add to each other; cached."""
        key = (a.cid, b.cid) if a.cid <= b.cid else (b.cid, a.cid)
        if key not in self._cache:
            first, second = (a, b) if a.cid <= b.cid else (b, a)
            self._cache[key] = metrics.clash(first.points, second.points, self.cp.scale,
                                             first.special, second.special)
        return self._cache[key]

    def pair_cost(self, a: Candidate, b: Candidate) -> float:
        x, o = self.clash(a, b)
        return 5 * x + o

    def mix_cost(self, cands) -> float:
        """Additive mix J: ring J's plus every pair's clash."""
        cands = list(cands)
        return sum(c.J for c in cands) + sum(self.pair_cost(a, b) for a, b in itertools.combinations(cands, 2))

    def exact(self, cands) -> dict:
        """The full core.metrics score of the mix (every ring and every clash counted once)."""
        rings = [metrics.normalise(c.points, {metrics.snap_point(p, self.cp.scale) for p in c.special}, self.cp.scale)
                 for c in cands]
        return metrics.score_rings(rings)

    def rescore(self, mixes: list[tuple[Candidate, ...]], keep: int = 10) -> list[tuple[float, tuple[Candidate, ...]]]:
        """The ``keep`` cheapest mixes by additive cost, re-scored exactly, cheapest first."""
        top = sorted(mixes, key=lambda m: (self.mix_cost(m), [c.cid for c in m]))[:keep]
        scored = [(self.exact(m)["J"], m) for m in top]
        scored.sort(key=lambda t: (t[0], [c.cid for c in t[1]]))
        return scored
