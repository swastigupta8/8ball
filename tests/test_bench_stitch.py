import pytest

from eightball.bench import stitch as T
from eightball.evaluate import geom_indep
from eightball.io import resplan
from tests.fixtures import synthetic as S

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists()


def _door_pairs(g):
    return {tuple(sorted((a, b))) for a, b, d in g.links.edges(data=True) if d["kind"] == "door"}


def test_stitch_two_synthetic_flats():
    floor, notes = T.stitch([S.synth_1hub(), S.synth_2hub()])
    assert floor is not None, notes
    assert resplan.scale(floor) == pytest.approx(1.0)
    g = geom_indep.build(floor)
    assert len(g.eligible) == 8
    # 1 door in flat one, 5 in flat two, 1 cut between them
    assert len(_door_pairs(g)) == 7
    assert ("bedroom_0", "living_1") in _door_pairs(g)  # flat one's bedroom to flat two's living room
    assert floor["stitched_from"] == [900001, 900002]


def test_single_flat_round_trips_to_metres():
    floor, _ = T.stitch([S.synth_2hub()])
    assert len(geom_indep.build(floor).eligible) == 6


def test_zone_sets_match_fixture_candidates():
    g = geom_indep.build(S.synth_2hub())
    assert len(T.zone_sets(g)) == len(S.zone_candidates_2hub()["candidates"])


def test_proxy_tour():
    assert T.proxy_tour([(0, 0)]) == 0
    assert T.proxy_tour([(0, 0), (3, 4)]) == 14
    assert T.proxy_tour([(0, 0), (2, 0), (2, 2), (0, 2)]) == 8


def test_exhaustive_and_cpsat_agree_on_stitched_synthetic():
    floor, _ = T.stitch([S.synth_1hub(), S.synth_2hub()])
    p = T.bench_floor(floor, 5.0)
    assert p["agree"] and p["cpsat_optimal"] and p["exhaustive_finished"] and p["cpsat_gap"] == 0


def test_exhaustive_respects_budget():
    floor, _ = T.stitch([S.synth_2hub()] * 4)
    rooms, cands, _ = T.proxy_candidates(floor)
    _h, _c, finished, seconds = T.exhaustive_select(rooms, cands, 0.0)
    assert seconds < 2.0 and finished in (True, False)


def test_claim_text():
    pts = [{"rooms": 10, "cpsat_s": 0.1, "cpsat_gap": 0.0, "cpsat_optimal": True, "cpsat_hubs": 2},
           {"rooms": 40, "cpsat_s": 0.5, "cpsat_gap": 0.01, "cpsat_optimal": False, "cpsat_hubs": 9}]
    assert T.claim(pts)["N"] == 40 and "40-room" in T.claim(pts)["text"]


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_stitch_real_flats():
    floors = T.build_floors("train", [3], 1, seed=1)
    assert len(floors) == 1
    g = geom_indep.build(floors[0])
    assert len(g.eligible) >= 6 and len(floors[0]["stitched_from"]) == 3
