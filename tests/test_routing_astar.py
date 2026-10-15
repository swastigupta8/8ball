"""A6: per-zone A* on the Hanan grid (Person A)."""
from __future__ import annotations

import itertools

import networkx as nx
import pytest
from shapely.geometry import LineString

from eightball.geometry import build_clean_plan
from eightball.io import resplan
from eightball.routing import api
from eightball.routing.astar import INF, HananRouter
from eightball.routing.crude import CrudeRouter, poly_cost
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def check_path(cp, poly, a, b):
    assert poly[0] == pytest.approx(a) and poly[-1] == pytest.approx(b)
    assert all(abs(p[0] - q[0]) < 1e-9 or abs(p[1] - q[1]) < 1e-9 for p, q in zip(poly, poly[1:]))
    assert cp.free.buffer(0.01 * cp.scale).covers(LineString(poly))


def heading(p, q):
    if abs(q[0] - p[0]) >= abs(q[1] - p[1]):
        return api.EAST if q[0] > p[0] else api.WEST
    return api.NORTH if q[1] > p[1] else api.SOUTH


def test_straight_run_through_a_door():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    r = HananRouter(cp)
    allowed = frozenset(cp.rooms)
    cost, poly = r.cost(allowed, "N1", api.EAST, "N2", api.EAST)
    assert cost == pytest.approx(4.1)
    assert poly == [(1.95, 2.0), (6.05, 2.0)]


def test_headings_decide_the_bends_and_cost_matches_the_polyline():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    r = HananRouter(cp)
    allowed = frozenset(cp.rooms)
    a, b = cp.nodes["N1"].point, cp.nodes["N2"].point
    for hi, ho in itertools.product(api.HEADINGS, repeat=2):
        cost, poly = r.cost(allowed, "N1", hi, "N2", ho)
        if cost == INF:
            continue
        check_path(cp, poly, a, b)
        assert heading(poly[0], poly[1]) == hi and heading(poly[-2], poly[-1]) == ho
        assert cost == pytest.approx(poly_cost(poly, 1.0))
    straight = r.cost(allowed, "N1", api.EAST, "N2", api.EAST)[0]
    detour = r.cost(allowed, "N1", api.NORTH, "N2", api.SOUTH)[0]
    assert detour > straight


def test_allowed_rooms_restrict_the_route():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    r = HananRouter(cp)
    everything = frozenset(cp.rooms)
    assert r.shortest(everything, "N1", "N2")[0] < INF
    assert r.shortest(everything - {"kitchen_0"}, "N1", "N2")[0] == INF
    zone = r.allowed_rooms_for({"living_0", "kitchen_0", "bedroom_0"})
    assert "bedroom_1" not in zone and r.shortest(zone, "N1", "N2")[0] < INF
    assert r.shortest(zone, "N1", "N3")[0] == INF


def test_cache_is_keyed_by_allowed_set_and_source():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    r = HananRouter(cp)
    zone = r.allowed_rooms_for({"living_0", "kitchen_0", "bedroom_0"})
    r.cost(zone, "N1", api.EAST, "N5", api.EAST)
    n = len(r._runs)
    r.cost(zone, "N1", api.EAST, "N2", api.EAST)  # same source and start heading: no new run
    assert len(r._runs) == n
    r.cost(zone, "N1", api.NORTH, "N2", api.EAST)
    assert len(r._runs) == n + 1


def test_free_point_endpoint_must_be_a_vertex():
    from eightball.routing.hanan import build_tracks

    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    hub = (1.0, 2.97)
    r = HananRouter(cp, build_tracks(cp, extra_points=[hub], attach=False))
    zone = r.allowed_rooms_for({"living_0", "kitchen_0", "bedroom_0"})
    cost, poly = r.shortest(zone, api.free_point_id(*hub), "N1")
    assert cost < INF
    check_path(cp, poly, hub, cp.nodes["N1"].point)
    with pytest.raises(KeyError):
        HananRouter(cp).shortest(zone, api.free_point_id(*hub), "N1")


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_hanan_is_never_worse_than_the_crude_router_on_real_plans():
    pairs = 0
    for pid in resplan.split_ids("train")[:12]:
        cp = build_clean_plan(resplan.get_plan(pid))
        hanan, crude = HananRouter(cp), CrudeRouter(cp)
        allowed = frozenset(cp.rooms)
        inside = [k for k, v in cp.rooms.items() if v.poly.intersection(cp.inner).area >= 0.5 * v.poly.area]
        comp = {}
        for k, c in enumerate(nx.connected_components(cp.links.subgraph(inside))):
            comp.update({x: k for x in c})
        for n1, n2 in itertools.combinations(cp.nodes.values(), 2):
            if comp[n1.room_id] != comp[n2.room_id]:
                continue
            ch, ph = hanan.shortest(allowed, n1.id, n2.id)
            cc, _ = crude.shortest(allowed, n1.id, n2.id)
            assert ch < INF, f"plan {pid}: no Hanan path {n1.id}->{n2.id}"
            check_path(cp, ph, n1.point, n2.point)
            # the raster router has coarser geometry, so the Hanan cost may only be lower (small slack for the
            # crude router's endpoint shifts)
            assert ch <= cc + 0.05, f"plan {pid} {n1.id}->{n2.id}: hanan {ch:.3f} > crude {cc:.3f}"
            pairs += 1
    assert pairs > 20
