"""Checker metrics (Person B, step B2 / handoff S1.4). Independent of core/metrics.py.

Written from the spec (handoff 8.1) and the conventions in tests/metric_cases.py:
  * Coordinates are converted to metres and snapped to an integer grid of TOL_M (1 mm), so all
    geometry below is exact integer arithmetic.
  * Each ring is closed at its hub. Zero-length segments and straight-through vertices are dropped,
    except node and hub vertices; reversal vertices are kept.
  * B: every direction change (90-degree turn or reversal) around the closed ring.
  * O: per axis line, a stretch covered by k segments adds (k - 1) x its length.
  * X: at each point where segments meet, the ring "passes" through that point are compared. Two
    passes cross unless they share a ray (they run together: overlap, counted in O, including the
    end of a shared run). Touches count when TOUCH_IS_CROSSING. With PASS_OTHER_NODE_IS_CROSSING a
    point is excluded only if every ring involved has its own node or hub there; otherwise if any does.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from eightball import config

# Directions as unit vectors on the integer grid.
E, N, W, S = (1, 0), (0, 1), (-1, 0), (0, -1)


@dataclass
class _Seg:
    ring: int
    idx: int          # position in the ring's cyclic segment list
    a: tuple[int, int]
    b: tuple[int, int]

    @property
    def horizontal(self) -> bool:
        return self.a[1] == self.b[1] and self.a[0] != self.b[0]

    @property
    def vertical(self) -> bool:
        return self.a[0] == self.b[0] and self.a[1] != self.b[1]

    def contains(self, p: tuple[int, int]) -> bool:
        (x1, y1), (x2, y2) = self.a, self.b
        if self.horizontal:
            return p[1] == y1 and min(x1, x2) <= p[0] <= max(x1, x2)
        if self.vertical:
            return p[0] == x1 and min(y1, y2) <= p[1] <= max(y1, y2)
        # Non-axis segment (the checker reports these separately): exact collinearity test.
        cross = (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1)
        return cross == 0 and min(x1, x2) <= p[0] <= max(x1, x2) and min(y1, y2) <= p[1] <= max(y1, y2)

    def rays(self, p: tuple[int, int]) -> set[tuple[int, int]]:
        """Directions in which this segment leaves point p."""
        d = _direction(self.a, self.b)
        back = (-d[0], -d[1])
        if p == self.a:
            return {d}
        if p == self.b:
            return {back}
        return {d, back}

    def length(self) -> int:
        (x1, y1), (x2, y2) = self.a, self.b
        if x1 == x2 or y1 == y2:
            return abs(x2 - x1) + abs(y2 - y1)
        return round(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)


def _sign(v: int) -> int:
    return (v > 0) - (v < 0)


def _direction(a, b) -> tuple[int, int]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 or dy == 0:
        return (_sign(dx), _sign(dy))
    g = _gcd(abs(dx), abs(dy))
    return (dx // g, dy // g)


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def _snap(pt, scale: float) -> tuple[int, int]:
    unit = float(config.TOL_M)
    return (round(pt[0] / scale / unit), round(pt[1] / scale / unit))


def _ring_vertices(hub: dict, points: dict, scale: float) -> tuple[list[tuple[int, int]], set[tuple[int, int]]]:
    """Closed ring as a cyclic vertex list (no repeat of the first vertex) plus its stop points."""
    raw: list[tuple[tuple[int, int], bool]] = []
    for leg in hub["legs"]:
        poly = [_snap(p, scale) for p in leg["polyline"]]
        for k, p in enumerate(poly[:-1]):
            raw.append((p, k == 0))  # the first point of each leg is a stop (hub or node)
    stops = {_snap(points[s], scale) for s in hub["sequence"] if s in points}
    stops |= {p for p, is_stop in raw if is_stop}
    # Drop consecutive duplicates (cyclic), keeping the stop flag.
    verts: list[list] = []
    for p, is_stop in raw:
        if verts and verts[-1][0] == p:
            verts[-1][1] = verts[-1][1] or is_stop
        else:
            verts.append([p, is_stop])
    while len(verts) > 1 and verts[0][0] == verts[-1][0]:
        verts[0][1] = verts[0][1] or verts[-1][1]
        verts.pop()
    # Drop straight-through vertices that aren't stops (reversals stay).
    changed = True
    while changed and len(verts) > 2:
        changed = False
        for i in range(len(verts)):
            prev_p, (p, is_stop), next_p = verts[i - 1][0], verts[i], verts[(i + 1) % len(verts)][0]
            if not is_stop and _direction(prev_p, p) == _direction(p, next_p):
                verts.pop(i)
                changed = True
                break
    return [v[0] for v in verts], stops


def _ring_segments(ring: int, verts: list[tuple[int, int]]) -> list[_Seg]:
    if len(verts) < 2:
        return []
    return [_Seg(ring, i, verts[i], verts[(i + 1) % len(verts)]) for i in range(len(verts))]


def _bends(verts: list[tuple[int, int]]) -> int:
    n = len(verts)
    if n < 2:
        return 0
    count = 0
    for i in range(n):
        d_in = _direction(verts[i - 1], verts[i])
        d_out = _direction(verts[i], verts[(i + 1) % n])
        count += d_in != d_out
    return count


def _line_key(seg: _Seg):
    if seg.horizontal:
        return ("h", seg.a[1]), (min(seg.a[0], seg.b[0]), max(seg.a[0], seg.b[0]))
    if seg.vertical:
        return ("v", seg.a[0]), (min(seg.a[1], seg.b[1]), max(seg.a[1], seg.b[1]))
    return None, None


def _overlap(segs: list[_Seg]) -> int:
    """Sum over every axis line of (k - 1) x length for stretches covered by k segments (grid units)."""
    by_line: dict = defaultdict(list)
    for s in segs:
        key, span = _line_key(s)
        if key is not None:
            by_line[key].append(span)
    total = 0
    for spans in by_line.values():
        if len(spans) < 2:
            continue
        events = sorted({x for span in spans for x in span})
        for lo, hi in zip(events, events[1:]):
            k = sum(1 for a, b in spans if a <= lo and hi <= b)
            if k > 1:
                total += (k - 1) * (hi - lo)
    return total


def _candidate_points(segs: list[_Seg]) -> set[tuple[int, int]]:
    pts = {s.a for s in segs} | {s.b for s in segs}
    hs = [s for s in segs if s.horizontal]
    vs = [s for s in segs if s.vertical]
    for h in hs:
        hx1, hx2 = sorted((h.a[0], h.b[0]))
        y = h.a[1]
        for v in vs:
            vy1, vy2 = sorted((v.a[1], v.b[1]))
            x = v.a[0]
            if hx1 <= x <= hx2 and vy1 <= y <= vy2:
                pts.add((x, y))
    return pts


def _passes(p, touching: list[_Seg], ring_lengths: dict[int, int]) -> list[tuple[int, set]]:
    """Group the segments touching p into passes: per ring, segments consecutive through vertex p."""
    by_ring: dict[int, list[_Seg]] = defaultdict(list)
    for s in touching:
        by_ring[s.ring].append(s)
    out = []
    for ring, ss in by_ring.items():
        n = ring_lengths[ring]
        idxs = {s.idx: s for s in ss}
        parent = {i: i for i in idxs}

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, s in idxs.items():
            j = (i + 1) % n
            if j in idxs and s.b == p and idxs[j].a == p and j != i:
                parent[find(i)] = find(j)
        groups: dict[int, set] = defaultdict(set)
        for i, s in idxs.items():
            groups[find(i)] |= s.rays(p)
        out.extend((ring, rays) for rays in groups.values())
    return out


def _is_proper(rays_a: set, rays_b: set) -> bool:
    """Both passes go straight through p, perpendicular to each other."""
    straight = lambda r: (E in r and W in r) or (N in r and S in r)  # noqa: E731
    return straight(rays_a) and straight(rays_b) and not (rays_a & rays_b)


def _crossings(segs: list[_Seg], stops_by_ring: dict[int, set]) -> int:
    ring_lengths: dict[int, int] = defaultdict(int)
    for s in segs:
        ring_lengths[s.ring] += 1
    touch = bool(config.TOUCH_IS_CROSSING)
    other_node_counts = bool(config.PASS_OTHER_NODE_IS_CROSSING)
    count = 0
    for p in _candidate_points(segs):
        touching = [s for s in segs if s.contains(p)]
        passes = _passes(p, touching, ring_lengths)
        if len(passes) < 2:
            continue
        involved = set()
        for i in range(len(passes)):
            for j in range(i + 1, len(passes)):
                (ra, rays_a), (rb, rays_b) = passes[i], passes[j]
                if rays_a & rays_b:
                    continue  # running together: overlap, not a crossing
                if not touch and not _is_proper(rays_a, rays_b):
                    continue
                involved |= {ra, rb}
        if not involved:
            continue
        has_stop = [p in stops_by_ring.get(r, set()) for r in involved]
        excluded = all(has_stop) if other_node_counts else any(has_stop)
        if not excluded:
            count += 1
    return count


def _rings(answer: dict, scale: float):
    points = {n["node_id"]: n["point"] for n in answer.get("nodes", [])}
    rings = []
    for k, hub in enumerate(answer["hubs"]):
        pts = {**points, hub["hub_id"]: hub["point"]}
        verts, stops = _ring_vertices(hub, pts, scale)
        rings.append((hub["hub_id"], verts, stops, _ring_segments(k, verts)))
    return rings


def score(answer: dict, scale: float) -> dict:
    """{"L": m, "X": int, "O": m, "B": int, "J": float, "per_hub": {hub_id: {...}}}"""
    unit = float(config.TOL_M)
    rings = _rings(answer, scale)
    segs = [s for *_rest, ring_segs in rings for s in ring_segs]
    stops_by_ring = {k: stops for k, (_h, _v, stops, _s) in enumerate(rings)}
    per_hub = {}
    total_len = 0
    total_bends = 0
    for hub_id, verts, _stops, ring_segs in rings:
        length = sum(s.length() for s in ring_segs)
        bends = _bends(verts)
        total_len += length
        total_bends += bends
        per_hub[hub_id] = {"L": length * unit, "B": bends, "O_self": _overlap(ring_segs) * unit}
    L = total_len * unit
    O = _overlap(segs) * unit
    X = _crossings(segs, stops_by_ring)
    B = total_bends
    return {"L": L, "X": X, "O": O, "B": B, "J": L + 5 * X + O + 0.5 * B, "per_hub": per_hub}


def clash(poly_a, poly_b, scale: float) -> tuple[int, float]:
    """(crossings, shared length in metres) between two closed rings given as vertex lists.

    Only meetings *between* the two rings count; each ring's own vertices count as its stops."""
    unit = float(config.TOL_M)
    ra = [_snap(p, scale) for p in poly_a]
    rb = [_snap(p, scale) for p in poly_b]
    sa, sb = _ring_segments(0, _dedupe_cyclic(ra)), _ring_segments(1, _dedupe_cyclic(rb))
    shared = _overlap(sa + sb) - _overlap(sa) - _overlap(sb)
    both = sa + sb
    ring_lengths = {0: len(sa), 1: len(sb)}
    crossings = 0
    for p in _candidate_points(both):
        passes = _passes(p, [s for s in both if s.contains(p)], ring_lengths)
        if any(pa[0] != pb[0] and not (pa[1] & pb[1])
               for i, pa in enumerate(passes) for pb in passes[i + 1:]):
            crossings += 1
    return crossings, shared * unit


def _dedupe_cyclic(pts):
    out = []
    for p in pts:
        if not out or out[-1] != p:
            out.append(p)
    while len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out
