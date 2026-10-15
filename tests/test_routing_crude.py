"""A2: crude router (Person A)."""
from __future__ import annotations

import itertools

import networkx as nx
import pytest
from shapely.geometry import LineString

from eightball.geometry import build_clean_plan
from eightball.io import resplan
from eightball.routing import api
from eightball.routing.crude import CrudeRouter, poly_cost
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def _axis_aligned(poly) -> bool:
    return all(abs(p[0] - q[0]) < 1e-9 or abs(p[1] - q[1]) < 1e-9 for p, q in zip(poly, poly[1:]))


def _check_path(cp, poly, a, b):
    assert poly[0] == pytest.approx(a) and poly[-1] == pytest.approx(b)
    assert _axis_aligned(poly)
    assert cp.free.buffer(1e-6 * cp.scale).covers(LineString(poly))


def test_path_through_a_door():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    r = CrudeRouter(cp)
    allowed = frozenset(cp.rooms)
    cost, poly = r.shortest(allowed, "N1", "N2")
    _check_path(cp, poly, cp.nodes["N1"].point, cp.nodes["N2"].point)
    assert cost == pytest.approx(4.1, abs=0.15)  # straight run of 4.1 m through the door, no bends
    assert any(abs(p[0] - 4.0) < 0.06 for p in poly) or poly[0][0] < 4.0 < poly[-1][0]


def test_headings_and_cost_api():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    r = CrudeRouter(cp)
    allowed = frozenset(cp.rooms)
    straight, poly = r.cost(allowed, "N1", api.EAST, "N2", api.EAST)
    assert straight == pytest.approx(poly_cost(poly, 1.0))
    assert poly[1][0] > poly[0][0]  # leaves heading east
    detour, poly2 = r.cost(allowed, "N1", api.NORTH, "N2", api.SOUTH)
    assert detour > straight  # leaving north and arriving south costs two extra bends
    assert poly2[1][1] > poly2[0][1]
    assert poly2[-1][1] < poly2[-2][1]


def test_allowed_rooms_restrict_the_route():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    r = CrudeRouter(cp)
    everything = frozenset(cp.rooms)
    assert r.shortest(everything, "N1", "N2")[0] < float("inf")  # living -> bedroom_0 through the kitchen
    without_kitchen = everything - {"kitchen_0"}
    assert r.shortest(without_kitchen, "N1", "N2")[0] == float("inf")
    assert r.allowed_rooms_for({"living_0", "kitchen_0", "bedroom_0"}) >= {"living_0", "kitchen_0", "bedroom_0"}
    assert "bedroom_1" not in r.allowed_rooms_for({"living_0", "kitchen_0", "bedroom_0"})


def test_free_point_endpoints_and_branching_tree():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    r = CrudeRouter(cp)
    zone = r.allowed_rooms_for({"living_0", "kitchen_0", "bedroom_0"})
    hub = (1.0, 2.97)
    cost, poly = r.shortest(zone, api.free_point_id(*hub), "N1")
    _check_path(cp, poly, hub, cp.nodes["N1"].point)
    tree = r.branching_tree(zone, hub, ["N1", "N5", "N2"])
    assert set(tree) == {"N1", "N5", "N2"}
    for nid, poly in tree.items():
        _check_path(cp, poly, hub, cp.nodes[nid].point)


def test_distance_field_is_not_implemented():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    with pytest.raises(NotImplementedError):
        CrudeRouter(cp).distance_field(frozenset(cp.rooms), "N1", 0)


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_real_plans_all_connected_pairs_have_paths():
    ids = resplan.split_ids("train")[:10] + [14433, 1448]
    checked = 0
    for pid in ids:
        cp = build_clean_plan(resplan.get_plan(pid))
        r = CrudeRouter(cp)
        allowed = frozenset(cp.rooms)
        comp_of = {}
        # rooms outside the inner boundary (balconies) can't carry a cable, so links through them don't count
        inside = [rid for rid, room in cp.rooms.items()
                  if room.poly.intersection(cp.inner).area >= 0.5 * room.poly.area]
        for k, comp in enumerate(nx.connected_components(cp.links.subgraph(inside))):
            comp_of.update({rid: k for rid in comp})
        for n1, n2 in itertools.combinations(cp.nodes.values(), 2):
            if comp_of[n1.room_id] != comp_of[n2.room_id]:
                continue
            cost, poly = r.shortest(allowed, n1.id, n2.id)
            assert cost < float("inf"), f"plan {pid}: no path {n1.id} -> {n2.id}"
            _check_path(cp, poly, n1.point, n2.point)
            checked += 1
    assert checked > 20
