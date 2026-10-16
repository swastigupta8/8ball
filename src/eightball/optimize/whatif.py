"""What-if tools on top of the solver (V2 features 2 and 3, docs/FEATURES_V2.md).

  move_hub(plan_raw, nodes, answer, hub_id, point)   drag the hub: re-wire one ring through another legal hub spot
  tradeoff(plan_raw, nodes, default_answer=None)     the best layout for 1, 2, 3 ... more hubs than the minimum

Both only *use* the solver's own functions (hub insertion, zone costs, clash table, answer builder); the default
`pipeline.solve` answer is never touched, and no rule changes, so the checker needs no edit.

Plan contexts (clean plan, track grids, zone prices) are the expensive part, so the last few plans are kept in a small
cache: a drag or a trade-off call right after a solve of the same plan is quick.
"""
from __future__ import annotations

import copy
import hashlib
import threading
import time
from collections import OrderedDict

from eightball import config
from eightball.core.contracts import CleanPlan
from eightball.geometry import build_clean_plan
from eightball.optimize import ladder, loops as loops_mod
from eightball.optimize.clash import ClashTable
from eightball.optimize.hub import (HubContext, HubPlan, _build_off_wire, _turn, candidate_vertices, ring_j, ring_legs)
from eightball.optimize.polish import clean_leg, polyline_edges
from eightball.optimize.zones import enumerate_zones, zone_rooms
from eightball.routing.api import EAST, HEADINGS, NORTH, SOUTH, WEST, free_point_id
from eightball.routing.astar import INF, HananRouter

_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_CACHE_SIZE = 4
_LOCK = threading.RLock()   # the cached routers are shared: one what-if call at a time


class Context:
    """One plan's reusable objects."""

    def __init__(self, cp: CleanPlan):
        self.cp = cp
        self.router = HananRouter(cp)
        self.hub = HubContext(cp, self.router)
        self.zone_data: list[ladder.ZoneData] | None = None   # every zone priced, for the trade-off


def _key(plan_raw: dict, nodes: list[dict]) -> tuple:
    inner = plan_raw.get("inner")
    fingerprint = hashlib.sha1(inner.wkb).hexdigest() if inner is not None and hasattr(inner, "wkb") else ""
    pts = tuple(sorted((n["node_id"], n["room_id"], round(float(n["point"][0]), 6), round(float(n["point"][1]), 6))
                       for n in nodes))
    return int(plan_raw["id"]), float(plan_raw.get("area", 0.0)), fingerprint, pts


def context(plan_raw: dict, nodes: list[dict]) -> Context:
    """The cached Context of a plan with these nodes (built on first use)."""
    key = _key(plan_raw, nodes)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]["ctx"]
        ctx = Context(build_clean_plan(plan_raw, nodes))
        _CACHE[key] = {"ctx": ctx}
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
        return ctx


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


# ---- feature 3: drag the hub --------------------------------------------------------------------------------

def _heading(a, b) -> int:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dy) < abs(dx):
        return EAST if dx > 0 else WEST
    return NORTH if dy > 0 else SOUTH


def _first_heading(poly) -> int:
    for a, b in zip(poly, poly[1:]):
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-9:
            return _heading(a, b)
    return EAST


def _last_heading(poly) -> int:
    for a, b in zip(reversed(poly[:-1]), reversed(poly[1:])):
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) > 1e-9:
            return _heading(a, b)
    return EAST


def _same_polyline(p, q, tol: float) -> bool:
    p, q = clean_leg(p), clean_leg(q)
    return len(p) == len(q) and all(abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol for a, b in zip(p, q))


def _original_loop(ctx: Context, rooms: tuple[str, ...], order: tuple[str, ...], middle: list):
    """The solver's own loop through these nodes (before the hub was inserted), if its legs match the answer's."""
    cp = ctx.cp
    tol = 1e-4 * cp.scale
    for lp in loops_mod.enumerate_loops(cp, ctx.router, rooms):
        if lp.n != len(order) or set(lp.order) != set(order):
            continue
        shift = lp.order.index(order[0])
        rot = [(shift + k) % lp.n for k in range(lp.n)]
        if tuple(lp.order[i] for i in rot) != order:
            continue
        if all(_same_polyline(list(lp.legs[rot[k]]), middle[k], tol) for k in range(len(middle))):
            return lp, rot
    return None


def loop_without_hub(ctx: Context, hub: dict) -> tuple[loops_mod.Loop, bool]:
    """The ring of an answer hub with the hub taken out again: (loop, exact).

    Leg k of the loop runs order[k] -> order[k + 1]. The ring's own legs 1..n-1 are loop legs 0..n-2; the last loop
    leg is where the hub sits (node -> hub -> node). ``exact`` is True when it could be matched with the solver's
    own unpolished loop (so a move reproduces the heatmap's numbers); otherwise the detour through the old hub spot
    stands in for that leg and the move is only approximate.
    """
    cp = ctx.cp
    order = tuple(hub["sequence"][1:-1])
    rooms = tuple(sorted(hub["room_ids"]))
    n = len(order)
    if n == 1:
        return loops_mod.Loop(rooms, order, (), (0,), (0,), (), 0.0, 0, 0.0, 0, 0.0, True), True
    legs = [[tuple(p) for p in leg["polyline"]] for leg in hub["legs"]]
    middle = legs[1:n]
    detour = legs[n] + legs[0][1:]
    found = _original_loop(ctx, rooms, order, middle)
    if found is not None:   # the solver's own loop, started at this ring's first node: same legs, same headings
        lp, rot = found
        return loops_mod.Loop(rooms, order, tuple(lp.legs[i] for i in rot), tuple(lp.h_in[i] for i in rot),
                              tuple(lp.h_out[i] for i in rot), lp.retrace, lp.L, lp.X, lp.O, lp.B, lp.J, lp.clean), True
    ring = middle + [detour]
    h_out = tuple(_first_heading(ring[k]) for k in range(n))
    h_in = tuple(_last_heading(ring[(k - 1) % n]) for k in range(n))
    sc = loops_mod._score(cp, order, ring)
    loop = loops_mod.Loop(rooms, order, tuple(tuple(map(tuple, leg)) for leg in ring), h_in, h_out, (),
                          sc["L"], sc["X"], sc["O"], sc["B"], sc["J"], True)
    return loop, False


def _on_lattice(ctx: HubContext, x: float, y: float) -> bool:
    step = float(config.HEATMAP_STEP_M) * ctx.cp.scale
    fx, fy = (x - ctx.lattice_x0) / step, (y - ctx.lattice_y0) / step
    return abs(fx - round(fx)) <= 1e-6 and abs(fy - round(fy)) <= 1e-6


def _ring_dict(hub: dict) -> dict:
    return {"zone": list(hub["room_ids"]), "hub": tuple(hub["point"]), "hub_room": hub["room_id"],
            "order": list(hub["sequence"][1:-1]), "legs": [[tuple(p) for p in leg["polyline"]] for leg in hub["legs"]]}


def _carry_meta(new: dict, old: dict, note: str | None = None) -> dict:
    meta = old.get("meta", {})
    for key in ("solver", "best_additive_cost", "j_floor", "min_hubs_bound"):
        if key in meta:
            new["meta"][key] = meta[key]
    warnings = [*(meta.get("warnings") or []), *([note] if note else [])]
    if warnings:
        new["meta"]["warnings"] = warnings
    return new


def _insertion_options(hctx: HubContext, allowed, loop, vertex: int) -> list[tuple[float, int, int, int]]:
    """(extra, leg, hp, hq) for inserting the hub vertex into each leg of the loop (cheapest headings), cheapest first.
    Same function as the heatmap's, but one entry per leg instead of only the best."""
    n = loop.n
    out = []
    for i in range(n):
        j = (i + 1) % n
        fi = hctx.field(allowed, loop.order[i], loop.h_out[i], False)
        rj = hctx.field(allowed, loop.order[j], loop.h_in[j], True)
        base = hctx.hub_router.cost_table(allowed, loop.order[i], loop.order[j])[loop.h_out[i]][loop.h_in[j]]
        best = (INF, i, 0, 0)
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
                if f + t + r - base < best[0]:
                    best = (f + t + r - base, i, hp, hq)
        if best[0] < INF:
            out.append(best)
    return sorted(out)


def _build_around_own_cable(hctx: HubContext, allowed, loop, vertex: int, leg: int, hp: int, hq: int):
    """node -> hub -> node for a hub at ``vertex`` inserted into ``leg``, routed off the edges of the loop's other legs
    (and, for the second half, off the first half), paying 5 J for each vertex it has to share with them."""
    hr = hctx.hub_router
    g = hr.grid
    n = loop.n
    i, j = leg, (leg + 1) % n
    pid = free_point_id(float(g.vx[vertex]), float(g.vy[vertex]))
    node_vertices = {hr.vertex_of(v) for v in loop.order}
    forbid: set[int] = set()
    contacts: dict[int, float] = {}
    for k in range(n):
        if k == i:
            continue
        edges = polyline_edges(hr, loop.legs[k])
        forbid |= set(edges)
        for e in edges:
            for vtx in (int(g.e_a[e]), int(g.e_b[e])):
                if vtx not in node_vertices:
                    contacts[vtx] = 5.0
    first = None
    for starts, ends in (((loop.h_out[i],), (hp,)), (HEADINGS, HEADINGS)):
        cost, poly, edges = hr.route(allowed, loop.order[i], pid, starts, ends, forbid, contacts)
        if cost < INF:
            first = (poly, edges)
            break
    if first is None:
        return None
    for starts, ends in (((hq,), (loop.h_in[j],)), (HEADINGS, HEADINGS)):
        cost, poly, _ = hr.route(allowed, pid, loop.order[j], starts, ends, forbid | set(first[1]), contacts)
        if cost < INF:
            return first[0], poly
    return None


def move_hub(plan_raw: dict, nodes: list[dict], answer: dict, hub_id: str, point) -> dict:
    """The answer with one hub moved to ``point`` (a heatmap lattice spot of its zone) and its ring re-wired there.

    Returns ``{"answer": new answer, "branching": branching doc, "exact": bool, "extra_j": float}``. ``extra_j`` is the
    insertion function's value at the spot (what the heatmap draws). Raises ValueError for a spot that is not legal
    (not on the zone's heatmap lattice, too close to a wall, off the zone, or not wireable): the API answers 422.
    """
    from eightball.optimize import pipeline

    t0 = time.perf_counter()
    point = (float(point[0]), float(point[1]))
    index = next((k for k, h in enumerate(answer["hubs"]) if h["hub_id"] == hub_id), None)
    if index is None:
        raise ValueError(f"no hub {hub_id!r} in the answer")
    hub = answer["hubs"][index]
    with _LOCK:
        ctx = context(plan_raw, nodes)
        cp, hctx = ctx.cp, ctx.hub
        tol = 1e-6 * cp.scale
        rings = [_ring_dict(h) for h in answer["hubs"]]
        if abs(point[0] - hub["point"][0]) <= tol and abs(point[1] - hub["point"][1]) <= tol:
            return {"answer": copy.deepcopy(answer), "branching": pipeline._branching(cp, None, rings),
                    "exact": True, "extra_j": 0.0}
        loop, exact = loop_without_hub(ctx, hub)
        if loop.n < 2:
            raise ValueError("a zone with one device has only one hub spot")
        allowed = ctx.router.allowed_rooms_for(loop.rooms)
        grid = hctx.hub_router.grid
        vertex = grid.vertex_at(point, tol)
        legal = set(candidate_vertices(hctx, loop, allowed))
        if vertex is None or vertex not in legal or not _on_lattice(hctx, point[0], point[1]):
            raise ValueError(f"({point[0]:.3f}, {point[1]:.3f}) is not a legal hub spot of {hub_id}'s zone "
                             "(only its heatmap points are)")
        options = _insertion_options(hctx, allowed, loop, vertex)
        room = hctx.room_of(loop.rooms, point)
        if not options or room is None:
            raise ValueError(f"{hub_id} cannot be wired through that spot")
        spot = (float(grid.vx[vertex]), float(grid.vy[vertex]))
        extra = options[0][0]
        room_of = {n.id: n.room_id for n in cp.nodes.values()}
        # The heatmap prices a spot as if the ring's own cable were not in the way. A route that runs along the ring's
        # own cable breaks the ring rule (no overlap except retracing at a dead-end room), so each way of wiring the
        # spot (every leg it can be inserted into, straight or routed around the ring's own cable) is checked, and the
        # cheapest legal one is used. If none is legal the move is refused instead of returning an invalid answer.
        best = None
        for opt_extra, leg, hp, hq in options:
            for build in (_build_off_wire, _build_around_own_cable):
                built = build(hctx, allowed, loop, vertex, leg, hp, hq)
                if built is None:
                    continue
                plan = HubPlan(spot, room, 0.0, False, leg, tuple(built[0]), tuple(built[1]), field_extra=max(0.0, opt_extra))
                order, legs = ring_legs(loop, plan)
                if loops_mod._illegal_overlap(cp, legs, [hub_id, *order], frozenset(loop.retrace), room_of, cp.scale) != 0:
                    continue
                j = ring_j(cp, loop, plan)
                if best is None or j < best[0] - 1e-9:
                    best = (j, order, legs)
        if best is None:
            raise ValueError(f"a hub at ({spot[0]:.2f}, {spot[1]:.2f}) would make {hub_id}'s ring run along its own "
                             "cable (overlap), which is not allowed")
        _, order, legs = best
        rings[index] = {"zone": list(loop.rooms), "hub": spot, "hub_room": room, "order": order, "legs": legs}
        new = pipeline.build_answer(cp, rings, answer.get("meta", {}).get("solver", "exact"), time.perf_counter() - t0)
        _carry_meta(new, answer, f"{hub_id} moved by hand to ({spot[0]:.2f}, {spot[1]:.2f})"
                    + ("" if exact else " (approximate: ring re-routed from the answer's own legs)"))
        return {"answer": new, "branching": pipeline._branching(cp, None, rings), "exact": exact,
                "extra_j": max(0.0, extra)}


# ---- feature 2: the trade-off between the number of hubs and the cost J -------------------------------------

def _zone_data(ctx: Context, deadline: float) -> list[ladder.ZoneData]:
    if ctx.zone_data is None:
        zones = enumerate_zones(ctx.cp, zone_rooms(ctx.cp))
        ctx.zone_data = ladder.build_zone_data(ctx.cp, ctx.router, ctx.hub, zones, deadline=deadline)
    return ctx.zone_data


def _option(answer: dict) -> dict:
    m = answer["metrics"]
    return {"hubs": m["H"], "J": m["J"], "L": m["L"], "X": m["X"], "O": m["O"], "B": m["B"], "answer": answer}


def tradeoff(plan_raw: dict, nodes: list[dict], default_answer: dict | None = None,
             extra_hubs: int = 3, time_budget_s: float | None = None) -> dict:
    """The best layout for the default hub count and for up to ``extra_hubs`` more.

    The first option is the default solve (``default_answer`` if given, else a fresh `pipeline.solve`, so it is the
    same answer the normal solve returns). Each larger hub count picks the cheapest zones with exactly that many hubs
    (CP-SAT over the priced zones), then the best loop mix, a short polish and the true metrics J (which count the
    crossings between rings that the additive zone cost doesn't). A hub count with no legal split is skipped.

    Returns {"options": [{hubs, J, L, X, O, B, answer}, ...], "default_hubs": H, "notes": [...]}.
    """
    from eightball.optimize import pipeline, polish as polish_mod
    from eightball.optimize.cpsat import CpSatZoneSolver

    t0 = time.perf_counter()
    budget = float(config.TIME_BUDGET_S) if time_budget_s is None else float(time_budget_s)
    deadline = t0 + budget
    if default_answer is None:
        default_answer = pipeline.solve(plan_raw, nodes, "exact").answer
    options = [_option(default_answer)]
    notes: list[str] = []
    h0 = default_answer["metrics"]["H"]
    with _LOCK:
        ctx = context(plan_raw, nodes)
        cp = ctx.cp
        rooms = zone_rooms(cp)
        top = min(len(rooms), h0 + extra_hubs)
        if h0 >= top:
            return {"options": options, "default_hubs": h0, "notes": notes}
        data = _zone_data(ctx, t0 + 0.6 * budget)
        by_id = {d.zone.zone_id: d for d in data}
        cands = ladder.to_zone_candidates(data)
        zone_area = {frozenset(d.zone.room_ids): d.zone.area_m2 for d in data}
        table = ClashTable(cp)
        for hubs in range(h0 + 1, top + 1):
            if time.perf_counter() > deadline:
                notes.append(f"time budget reached: options above {hubs - 1} hubs not computed")
                break
            sel = CpSatZoneSolver().select(rooms, cands, hubs, max(1.0, deadline - time.perf_counter()), hubs=hubs)
            if not sel.zone_ids:
                notes.append(f"no legal split into exactly {hubs} zones")
                continue
            mix = ladder.best_mix(table, [by_id[z] for z in sel.zone_ids], zone_area, deadline)
            if mix is None:
                continue
            picked, _ = mix
            if time.perf_counter() < deadline:
                left = max(0.5, min(3.0, (deadline - time.perf_counter()) / 2))
                picked, _ = polish_mod.polish(cp, ctx.router, ctx.hub, picked, table, time.perf_counter() + left)
            rings = pipeline.rings_from_candidates(picked)
            answer = pipeline.build_answer(cp, rings, "exact", time.perf_counter() - t0)
            answer["meta"]["warnings"] = [f"trade-off option: {hubs} hubs (one more hub than the minimum)"
                                          if hubs == h0 + 1 else f"trade-off option: {hubs} hubs"]
            options.append(_option(answer))
    return {"options": options, "default_hubs": h0, "notes": notes}
