"""Core metrics (Person A, step A3 / handoff S1.3). Used by the optimiser.

Implements the metrics interface (handoff 7.4) following handoff 8.1 and the conventions in
tests/metric_cases.py. Must not be read by Person B (independence).

Everything is computed on a 1 mm integer grid in metres (coordinate / scale / TOL_M, rounded), so two points
within 1 mm are the same point and two lines within 1 mm are the same line.

  L  sum of ring segment lengths (metres).
  B  direction changes around each closed ring, hub and nodes included; a 180-degree reversal is one bend.
  O  per axis line, a stretch covered by k segments (any ring, the same ring too) adds (k - 1) x its length.
  X  points where two segments meet (proper crossings, T-touches, endpoint touches), once per point, except
       - consecutive segments of one ring at their shared vertex;
       - the end of a collinear overlap, unless a ring that takes no part in that overlap also meets there;
       - points where every ring meeting there has its own node or hub (strict: touching another ring's node counts).
Non-axis-aligned segments (never produced by our router) count towards L and B only.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from eightball import config

IPoint = tuple[int, int]


@dataclass
class Ring:
    """A closed ring on the 1 mm grid: distinct consecutive vertices, hub first, node vertices kept."""
    points: list[IPoint]
    special: frozenset[IPoint]  # this ring's own node and hub points
    segs: list[tuple[IPoint, IPoint]] = field(init=False)

    def __post_init__(self) -> None:
        n = len(self.points)
        self.segs = [(self.points[i], self.points[(i + 1) % n]) for i in range(n)] if n >= 2 else []


def _snap(v: float, scale: float) -> int:
    return math.floor(v / scale / float(config.TOL_M) + 0.5)


def snap_point(p, scale: float) -> IPoint:
    return (_snap(p[0], scale), _snap(p[1], scale))


def normalise(points, special: set[IPoint], scale: float) -> Ring:
    """Snap, drop zero-length segments and straight-through middle vertices (keeping node/hub vertices)."""
    pts: list[IPoint] = []
    for p in points:
        q = snap_point(p, scale)
        if not pts or q != pts[-1]:
            pts.append(q)
    while len(pts) > 1 and pts[0] == pts[-1]:  # closed polylines repeat the start
        pts.pop()
    changed = True
    while changed and len(pts) > 2:
        changed = False
        n = len(pts)
        for i in range(n):
            a, v, b = pts[i - 1], pts[i], pts[(i + 1) % n]
            if v in special:
                continue
            d1 = (v[0] - a[0], v[1] - a[1])
            d2 = (b[0] - v[0], b[1] - v[1])
            if d1[0] * d2[1] - d1[1] * d2[0] == 0 and d1[0] * d2[0] + d1[1] * d2[1] > 0:  # straight through
                del pts[i]
                changed = True
                break
    return Ring(pts, frozenset(special))


def _length_bends(ring: Ring) -> tuple[float, int]:
    total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in ring.segs)
    bends = 0
    n = len(ring.segs)
    for i in range(n):
        (a, v), (_, b) = ring.segs[i - 1], ring.segs[i]
        d1 = (v[0] - a[0], v[1] - a[1])
        d2 = (b[0] - v[0], b[1] - v[1])
        if not (d1[0] * d2[1] - d1[1] * d2[0] == 0 and d1[0] * d2[0] + d1[1] * d2[1] > 0):
            bends += 1
    return total * float(config.TOL_M), bends


@dataclass
class _Seg:
    ring: int
    idx: int
    a: IPoint  # sorted so a <= b
    b: IPoint


def _axis_segments(rings: list[Ring]) -> tuple[list[_Seg], list[_Seg]]:
    horizontal, vertical = [], []
    for r, ring in enumerate(rings):
        for i, (p, q) in enumerate(ring.segs):
            a, b = (p, q) if p <= q else (q, p)
            if a[1] == b[1] and a[0] != b[0]:
                horizontal.append(_Seg(r, i, a, b))
            elif a[0] == b[0] and a[1] != b[1]:
                vertical.append(_Seg(r, i, a, b))
    return horizontal, vertical


def _shared_vertices(rings: list[Ring], s: _Seg, t: _Seg) -> set[IPoint]:
    """Vertices shared by two consecutive segments of one ring (empty if not consecutive)."""
    if s.ring != t.ring:
        return set()
    ring = rings[s.ring]
    n = len(ring.segs)
    out: set[IPoint] = set()
    if (t.idx - s.idx) % n == 1:
        out.add(ring.segs[s.idx][1])
    if (s.idx - t.idx) % n == 1:
        out.add(ring.segs[t.idx][1])
    return out


def _overlap_length(segs: list[_Seg], axis: int) -> int:
    """Sum of (k - 1) x length over a set of collinear segments, in grid units."""
    events: list[tuple[int, int]] = []
    for s in segs:
        events.append((s.a[axis], 1))
        events.append((s.b[axis], -1))
    events.sort()
    total, k, prev = 0, 0, None
    for pos, delta in events:
        if prev is not None and k >= 2 and pos > prev:
            total += (k - 1) * (pos - prev)
        k += delta
        prev = pos
    return total


def crossings_and_overlap(rings: list[Ring]) -> tuple[int, float]:
    """(X, O in metres) of a set of rings."""
    horizontal, vertical = _axis_segments(rings)

    overlap = 0
    lines: dict[tuple[str, int], list[_Seg]] = defaultdict(list)
    for s in horizontal:
        lines[("h", s.a[1])].append(s)
    for s in vertical:
        lines[("v", s.a[0])].append(s)
    overlap_ends: dict[IPoint, set[int]] = defaultdict(set)
    contacts: set[IPoint] = set()
    touch_ok = bool(config.TOUCH_IS_CROSSING)

    for (kind, const), segs in lines.items():
        axis = 0 if kind == "h" else 1
        overlap += _overlap_length(segs, axis)
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                s, t = segs[i], segs[j]
                lo, hi = max(s.a[axis], t.a[axis]), min(s.b[axis], t.b[axis])
                if lo > hi:
                    continue
                mk = (lambda v: (v, const)) if kind == "h" else (lambda v: (const, v))
                if lo < hi:
                    for v in (lo, hi):
                        overlap_ends[mk(v)].update((s.ring, t.ring))
                elif touch_ok and mk(lo) not in _shared_vertices(rings, s, t):
                    contacts.add(mk(lo))

    if horizontal and vertical:
        hx0 = np.array([s.a[0] for s in horizontal])
        hx1 = np.array([s.b[0] for s in horizontal])
        hy = np.array([s.a[1] for s in horizontal])
        vx = np.array([s.a[0] for s in vertical])
        vy0 = np.array([s.a[1] for s in vertical])
        vy1 = np.array([s.b[1] for s in vertical])
        hit = (vx[None, :] >= hx0[:, None]) & (vx[None, :] <= hx1[:, None]) & \
              (hy[:, None] >= vy0[None, :]) & (hy[:, None] <= vy1[None, :])
        for hi_, vi_ in zip(*np.nonzero(hit)):
            h, v = horizontal[hi_], vertical[vi_]
            p = (v.a[0], h.a[1])
            if not touch_ok and not (h.a[0] < p[0] < h.b[0] and v.a[1] < p[1] < v.b[1]):
                continue
            if p in _shared_vertices(rings, h, v):
                continue
            contacts.add(p)

    crossings = 0
    strict = bool(config.PASS_OTHER_NODE_IS_CROSSING)
    for p in contacts:
        meeting = _rings_at(rings, horizontal, vertical, p)
        if p in overlap_ends and meeting <= overlap_ends[p]:
            continue  # only the rings of an overlap meet at its end
        own = [p in rings[r].special for r in meeting]
        if (all(own) if strict else any(own)):
            continue
        crossings += 1
    return crossings, overlap * float(config.TOL_M)


def _rings_at(rings, horizontal, vertical, p: IPoint) -> set[int]:
    out = set()
    for s in horizontal:
        if s.a[1] == p[1] and s.a[0] <= p[0] <= s.b[0]:
            out.add(s.ring)
    for s in vertical:
        if s.a[0] == p[0] and s.a[1] <= p[1] <= s.b[1]:
            out.add(s.ring)
    return out


def _j(L: float, X: int, O: float, B: int) -> float:
    return L + 5 * X + O + 0.5 * B


def hub_ring(hub: dict, nodes_by_id: dict[str, dict], scale: float) -> Ring:
    """The ring of one answer hub: its legs' polylines joined, closed at the hub."""
    pts: list = []
    for leg in hub["legs"]:
        pts.extend(leg["polyline"])
    special = {snap_point(hub["point"], scale)}
    special.update(snap_point(nodes_by_id[n]["point"], scale) for n in hub["node_ids"])
    return normalise(pts, special, scale)


def score_rings(rings: list[Ring]) -> dict:
    """L, X, O, B, J of a set of rings, plus each ring's standalone numbers under "per_ring"."""
    per_ring = []
    L = B = 0
    for ring in rings:
        l_, b_ = _length_bends(ring)
        x_, o_ = crossings_and_overlap([ring])
        per_ring.append({"L": l_, "B": b_, "X": x_, "O": o_, "J": _j(l_, x_, o_, b_)})
        L += l_
        B += b_
    X, O = crossings_and_overlap(rings)
    return {"L": L, "X": X, "O": O, "B": B, "J": _j(L, X, O, B), "per_ring": per_ring}


def score(answer: dict, scale: float) -> dict:
    """{"L": m, "X": int, "O": m, "B": int, "J": float, "per_hub": {hub_id: {...}}}"""
    nodes = {n["node_id"]: n for n in answer["nodes"]}
    hubs = answer["hubs"]
    result = score_rings([hub_ring(h, nodes, scale) for h in hubs])
    per_hub = {h["hub_id"]: pr for h, pr in zip(hubs, result.pop("per_ring"))}
    result["per_hub"] = per_hub
    return result


def clash(poly_a, poly_b, scale: float, special_a=None, special_b=None) -> tuple[int, float]:
    """(crossings, shared length in metres) that two rings add on top of their own scores.

    poly_a / poly_b are each ring's full closed polyline (drawing units). special_a / special_b are the
    ring's node and hub points (default: the first point, taken as the hub). J(a + b) = J(a) + J(b) +
    5 * crossings + shared, exactly.
    """
    sa = {snap_point(p, scale) for p in (special_a if special_a is not None else [poly_a[0]])}
    sb = {snap_point(p, scale) for p in (special_b if special_b is not None else [poly_b[0]])}
    a, b = normalise(poly_a, sa, scale), normalise(poly_b, sb, scale)
    x_ab, o_ab = crossings_and_overlap([a, b])
    x_a, o_a = crossings_and_overlap([a])
    x_b, o_b = crossings_and_overlap([b])
    return max(0, x_ab - x_a - x_b), max(0.0, o_ab - o_a - o_b)
