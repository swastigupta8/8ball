"""Short-circuit isolators on the closed loops (V2 feature 1, docs/FEATURES_V2.md).

A ring runs hub -> d1 -> d2 -> ... -> dn -> hub (hub.sequence; leg i runs sequence[i] -> sequence[i + 1], so leg i joins
device d_i to d_(i+1), leg 0 is hub -> d1 and leg n is dn -> hub). A short circuit anywhere on a cable disables
every device on the same unbroken stretch of cable. The hub (the panel) is isolated on both sides, as on a real panel.

A short-circuit isolator sits on a leg between two devices and cuts the ring into segments: a short disables only the
devices of the segment it is in. With no isolators the whole ring is one segment.

Placement for "at most k devices lost per short": walk the devices in ring order and put an isolator on the leg after
every k-th device (legs k, 2k, ... while < n): ceil(n / k) - 1 per ring, the minimum, since a segment holds at most k.

This module only reads an answer dict; it changes no rule and no cable.
"""
from __future__ import annotations

import math

Isolator = dict   # {"hub_id": str, "leg_index": int, "point": [x, y]}


def _hub(answer: dict, hub_id: str) -> dict:
    for hub in answer["hubs"]:
        if hub["hub_id"] == hub_id:
            return hub
    raise KeyError(f"no hub {hub_id!r} in the answer")


def polyline_midpoint(poly: list) -> list[float]:
    """The point halfway along a polyline, by length."""
    total = sum(math.dist(a, b) for a, b in zip(poly, poly[1:]))
    if total <= 0.0:
        return [float(poly[0][0]), float(poly[0][1])]
    half, run = total / 2, 0.0
    for a, b in zip(poly, poly[1:]):
        seg = math.dist(a, b)
        if seg > 0 and run + seg >= half:
            f = (half - run) / seg
            return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]
        run += seg
    return [float(poly[-1][0]), float(poly[-1][1])]


def isolator_count(n_devices: int, max_lost: int) -> int:
    """Isolators one ring of n devices needs so that a short loses at most max_lost devices."""
    if max_lost < 1:
        raise ValueError("max_lost must be at least 1")
    return max(0, math.ceil(n_devices / max_lost) - 1)


def place_isolators(answer: dict, max_lost: int) -> list[Isolator]:
    """The fewest isolators so that no short circuit loses more than ``max_lost`` devices of any ring."""
    if max_lost < 1:
        raise ValueError("max_lost must be at least 1")
    out: list[Isolator] = []
    for hub in answer["hubs"]:
        n = len(hub["sequence"]) - 2
        for leg_index in range(max_lost, n, max_lost):
            out.append({"hub_id": hub["hub_id"], "leg_index": leg_index,
                        "point": polyline_midpoint(hub["legs"][leg_index]["polyline"])})
    return out


def short_effect(answer: dict, isolators: list[Isolator], hub_id: str, leg_index: int,
                 t: float | None = None) -> list[str]:
    """Node ids lost by a short circuit on leg ``leg_index`` of a hub's ring, in ring order.

    ``t`` (0..1) is how far along that leg, by length, the short is. It only matters on a leg that carries an
    isolator in its middle: a short in the first half belongs to the segment before the isolator, in the second half to
    the segment after it. With ``t`` left out, both sides are counted (the worst case).
    """
    hub = _hub(answer, hub_id)
    seq = hub["sequence"]
    n = len(seq) - 2
    if not 0 <= leg_index <= n:
        raise ValueError(f"{hub_id} has legs 0..{n}, not {leg_index}")
    iso = sorted(i["leg_index"] for i in isolators if i["hub_id"] == hub_id)
    before = sum(1 for i in iso if i < leg_index)
    if leg_index in iso:
        groups = {before, before + 1} if t is None else {before if t < 0.5 else before + 1}
    else:
        groups = {before}
    return [seq[j] for j in range(1, n + 1) if sum(1 for i in iso if i < j) in groups]


def worst_short(answer: dict, isolators: list[Isolator]) -> int:
    """The most devices any single short circuit can take out of one ring."""
    worst = 0
    for hub in answer["hubs"]:
        n = len(hub["sequence"]) - 2
        iso = sorted(i["leg_index"] for i in isolators if i["hub_id"] == hub["hub_id"])
        sizes: dict[int, int] = {}
        for j in range(1, n + 1):
            g = sum(1 for i in iso if i < j)
            sizes[g] = sizes.get(g, 0) + 1
        worst = max([worst, *sizes.values()])
    return worst


def isolator_table(answer: dict, max_k: int = 5) -> dict[str, list[Isolator]]:
    """k -> isolators, for k = 1..max_k (the table the viewer and /api/solve show)."""
    return {str(k): place_isolators(answer, k) for k in range(1, max_k + 1)}
