"""A9: distance fields, hub insertion, loop ranking and heatmap numbers (Person A)."""
from __future__ import annotations

import math
import random

import pytest
from shapely.geometry import Point

from eightball import config
from eightball.geometry import build_clean_plan
from eightball.io import answer_io, resplan
from eightball.optimize import hub as hubmod
from eightball.optimize.hub import HubContext, best_hub, heatmap_points, make_heatmap_doc, ranked_loops, ring_legs
from eightball.optimize.loops import enumerate_loops
from eightball.routing import api
from eightball.routing.astar import INF, HananRouter
from tests.fixtures import synthetic as syn
from tests.test_optimize_loops import HALL_NODES, hall_plan

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()
HALL_ROOMS = ["living_0", "bedroom_0", "bedroom_1", "bedroom_2"]


def hall():
    cp = build_clean_plan(hall_plan(), HALL_NODES)
    router = HananRouter(cp)
    return cp, router, HubContext(cp, router)


def test_fields_agree_with_point_to_point_routing_in_both_directions():
    """The reversed field measures p -> node and the forward field node -> p, bends included."""
    cp, router, ctx = hall()
    hr = ctx.hub_router
    allowed = router.allowed_rooms_for(HALL_ROOMS)
    g = hr.grid
    rng = random.Random(1)
    verts = [v for v in rng.sample(range(g.n_vertices), 60) if (g.nbr[:, v] >= 0).any()]
    checked = 0
    for node, h_node in (("N2", api.EAST), ("N3", api.SOUTH), ("N1", api.NORTH)):
        fwd = ctx.field(allowed, node, h_node, False)
        rev = ctx.field(allowed, node, h_node, True)
        for v in verts:
            pid = api.free_point_id(float(g.vx[v]), float(g.vy[v]))
            for h in api.HEADINGS:
                f = fwd.at_vertex(v, h)
                ref_f = hr.cost(allowed, node, h_node, pid, h)[0] if node != pid else INF
                assert f == pytest.approx(ref_f) or (f == INF and ref_f == INF)
                r = rev.at_vertex(v, h)
                ref_r = hr.cost(allowed, pid, h, node, h_node)[0]
                assert r == pytest.approx(ref_r) or (r == INF and ref_r == INF), (node, v, h, r, ref_r)
                checked += f < INF and r < INF
    assert checked > 50


def test_asymmetric_case_reverse_differs_from_forward():
    cp, router, ctx = hall()
    allowed = router.allowed_rooms_for(HALL_ROOMS)
    fwd = ctx.field(allowed, "N2", api.NORTH, False)
    rev = ctx.field(allowed, "N2", api.NORTH, True)
    g = ctx.hub_router.grid
    diffs = [abs(fwd.at_vertex(v, h) - rev.at_vertex(v, h)) for v in range(0, g.n_vertices, 7) for h in api.HEADINGS
             if fwd.at_vertex(v, h) < INF and rev.at_vertex(v, h) < INF]
    assert diffs and max(diffs) > 0.4  # a bend costs 0.5, and it lands on opposite ends of the two fields


def test_hub_on_the_wire_costs_nothing_and_is_a_legal_site():
    cp, router, ctx = hall()
    loop = enumerate_loops(cp, router, HALL_ROOMS)[0]
    hub = best_hub(ctx, loop)
    assert hub is not None and hub.on_wire and hub.extra == 0.0
    # inside an eligible room of the zone, 0.5 m from its boundary and from every wall
    room = cp.rooms[hub.room_id]
    p = Point(hub.point)
    assert hub.room_id in HALL_ROOMS and room.poly.contains(p)
    assert room.poly.exterior.distance(p) >= config.HUB_CLEARANCE_M * cp.scale - 1e-6
    assert cp.walls.distance(p) >= config.HUB_CLEARANCE_M * cp.scale - 1e-6
    # the ring through the hub scores the same as the loop
    assert hubmod.ring_j(cp, loop, hub) == pytest.approx(loop.J)
    order, legs = ring_legs(loop, hub)
    assert sorted(order) == sorted(loop.order) and len(legs) == loop.n + 1
    assert legs[0][0] == pytest.approx(hub.point) and legs[-1][-1] == pytest.approx(hub.point)
    for k, leg in enumerate(legs[:-1]):
        assert legs[k + 1][0] == pytest.approx(leg[-1])


def test_off_the_wire_insertion_is_never_negative_and_matches_a_real_ring(monkeypatch):
    cp, router, ctx = hall()
    loop = enumerate_loops(cp, router, HALL_ROOMS)[0]
    monkeypatch.setattr(hubmod, "wire_hub", lambda *_: None)
    hub = best_hub(ctx, loop)
    assert hub is not None and not hub.on_wire
    assert hub.field_extra >= 0 and math.isfinite(hub.extra)
    assert hubmod.ring_j(cp, loop, hub) - loop.J == pytest.approx(hub.extra)
    allowed = router.allowed_rooms_for(HALL_ROOMS)
    g = ctx.hub_router.grid
    for v in hubmod.candidate_vertices(ctx, loop, allowed)[:80]:
        assert hubmod._insertion_at(ctx, allowed, loop, v)[0] >= -1e-9


def test_heatmap_minimum_is_the_chosen_hub():
    cp, router, ctx = hall()
    loop = enumerate_loops(cp, router, HALL_ROOMS)[0]
    for wire in (True, False):
        if not wire:
            import eightball.optimize.hub as h
            old = h.wire_hub
            h.wire_hub = lambda *_: None
        try:
            hub = best_hub(ctx, loop)
            doc = make_heatmap_doc(ctx, loop, hub, "H1")
        finally:
            if not wire:
                h.wire_hub = old
        assert answer_io.heatmap_errors(doc) == []
        values = [p[2] for p in doc["points"]]
        chosen = next(p for p in doc["points"] if (p[0], p[1]) == pytest.approx(tuple(doc["chosen"])))
        assert min(values) == pytest.approx(chosen[2], abs=1e-9)
        assert len(doc["points"]) > 10 and min(values) >= -1e-9


def test_single_node_zone_gets_an_out_and_back_ring():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    router = HananRouter(cp)
    ctx = HubContext(cp, router)
    loop = enumerate_loops(cp, router, ["bedroom_0"])[0]
    hub = best_hub(ctx, loop)
    assert hub is not None and hub.room_id == "bedroom_0"
    order, legs = ring_legs(loop, hub)
    assert order == ["N2"] and len(legs) == 2
    assert legs[0][0] == pytest.approx(hub.point) or legs[0][-1] == pytest.approx(hub.point)
    assert math.isfinite(hub.extra)


def test_ranking_orders_by_loop_plus_hub_cost():
    cp, router, ctx = hall()
    loops = enumerate_loops(cp, router, HALL_ROOMS)
    ranked = ranked_loops(ctx, loops, topk=2)
    assert len(ranked) == 2 and ranked[0].total <= ranked[1].total
    assert ranked[0].total == pytest.approx(ranked[0].loop.J + ranked[0].hub.extra)


def test_zone_with_no_room_for_a_hub_is_dropped():
    """A room too small to keep 0.5 m from its walls cannot host a hub; a zone made only of such rooms has none."""
    cp, router, ctx = hall()
    tiny = ctx.room_regions(["bedroom_0"])
    assert "bedroom_0" in tiny  # 3.9 x 3.8 m is big enough
    cp2 = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    ctx2 = HubContext(cp2, HananRouter(cp2))
    old = config.override(HUB_CLEARANCE_M=3.0)  # no 8 x 4 m flat can keep 3 m from its walls
    try:
        ctx2._regions.clear()
        loops = enumerate_loops(cp2, ctx2.router, ["living_0", "bedroom_0"])
        assert ranked_loops(ctx2, loops) == []
    finally:
        config.override(**old)


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_hub_is_always_a_legal_site_on_real_plans():
    from eightball.optimize.zones import enumerate_zones

    zones_checked = 0
    for pid in resplan.split_ids("train")[:25]:
        cp = build_clean_plan(resplan.get_plan(pid))
        router = HananRouter(cp)
        ctx = HubContext(cp, router)
        for z in enumerate_zones(cp):
            if z.n_nodes > 3:
                continue
            for r in ranked_loops(ctx, enumerate_loops(cp, router, z.room_ids), topk=2):
                p = Point(r.hub.point)
                room = cp.rooms[r.hub.room_id]
                assert r.hub.room_id in z.room_ids
                assert room.poly.exterior.distance(p) >= config.HUB_CLEARANCE_M * cp.scale - 1e-6
                assert cp.walls.distance(p) >= config.HUB_CLEARANCE_M * cp.scale - 1e-6
                assert r.hub.field_extra >= 0
                zones_checked += 1
    assert zones_checked > 40
