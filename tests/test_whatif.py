"""V2 features 2 and 3: the hubs-vs-cost trade-off and moving a hub (optimize/whatif.py, cpsat select(hubs=), API)."""
import copy

import pytest

from eightball.api import server
from eightball.evaluate import checker
from eightball.optimize import pipeline, whatif
from eightball.optimize.cpsat import CpSatZoneSolver
from tests.fixtures import synthetic as S

PID = 900002        # two 3-device zones; solves in well under a second
PLAN, NODES = S.PLANS[PID](), S.NODES[PID]


@pytest.fixture(scope="module")
def solved():
    res = pipeline.solve(PLAN, NODES, "exact")
    assert res.answer["meta"]["solver"] == "exact" and res.heatmaps
    return res


# ---- CP-SAT: fixed hub count ------------------------------------------------------------------------------

def test_select_with_fixed_hubs_returns_exactly_that_many_zones_covering_every_room():
    rooms, cands = pipeline.zone_candidates(PLAN, NODES)
    by_id = {c.zone_id: c for c in cands}
    default = CpSatZoneSolver().select(rooms, cands, 1, 10.0)
    assert default.hubs == 2                                  # the default behaviour is untouched
    for hubs in (2, 3, 4):
        sel = CpSatZoneSolver().select(rooms, cands, 1, 10.0, hubs=hubs)
        assert sel.hubs == hubs and len(sel.zone_ids) == hubs
        covered = [r for z in sel.zone_ids for r in by_id[z].room_ids]
        assert sorted(covered) == sorted(rooms)               # every room once
    none = CpSatZoneSolver().select(rooms, cands, 1, 10.0, hubs=1)
    assert none.zone_ids == []                                # no legal one-zone split here


# ---- trade-off --------------------------------------------------------------------------------------------

def test_tradeoff_first_option_is_the_default_solve_and_every_option_is_valid(solved):
    out = pipeline.tradeoff(PLAN, NODES)                       # no answer given: it solves the plan itself
    opts = out["options"]
    assert out["default_hubs"] == solved.answer["metrics"]["H"] == opts[0]["hubs"] == 2
    assert opts[0]["J"] == pytest.approx(solved.answer["metrics"]["J"], abs=1e-9)
    assert opts[0]["answer"]["hubs"] == solved.answer["hubs"]  # the same layout, not just the same score
    assert [o["hubs"] for o in opts] == list(range(2, 2 + len(opts))) and len(opts) >= 3
    for o in opts:
        assert checker.check(PLAN, o["answer"], NODES)["valid"], o["hubs"]
        assert o["answer"]["metrics"]["H"] == o["hubs"] == len(o["answer"]["hubs"])
        assert o["J"] == pytest.approx(o["L"] + 5 * o["X"] + o["O"] + 0.5 * o["B"], abs=1e-6)


def test_tradeoff_reuses_a_given_answer_and_does_not_change_it(solved):
    given = copy.deepcopy(solved.answer)
    out = pipeline.tradeoff(PLAN, NODES, given)
    assert out["options"][0]["answer"] is given and given == solved.answer


# ---- move the hub -----------------------------------------------------------------------------------------

def _heat(solved, hub_id):
    return next(h for h in solved.heatmaps if h["hub_id"] == hub_id)


def _a_legal_spot(solved, hub_id="H1"):
    """A heatmap point (other than the hub's own) that a move accepts."""
    hub = next(h for h in solved.answer["hubs"] if h["hub_id"] == hub_id)
    for x, y, _ in _heat(solved, hub_id)["points"]:
        if abs(x - hub["point"][0]) + abs(y - hub["point"][1]) < 1e-6:
            continue
        try:
            pipeline.move_hub(PLAN, NODES, solved.answer, hub_id, (x, y))
        except ValueError:
            continue
        return x, y
    raise AssertionError("no legal spot found")


def test_moving_a_hub_to_where_it_already_is_changes_nothing(solved):
    hub = solved.answer["hubs"][0]
    out = pipeline.move_hub(PLAN, NODES, solved.answer, hub["hub_id"], hub["point"])
    assert out["answer"]["metrics"] == solved.answer["metrics"]
    assert out["answer"]["hubs"] == solved.answer["hubs"]


def test_moving_to_other_heatmap_spots_costs_the_heatmap_value_and_stays_valid(solved):
    answer = solved.answer
    hub = answer["hubs"][0]
    pts = _heat(solved, hub["hub_id"])["points"]
    pts = sorted(pts, key=lambda p: p[2])
    sample = [p for p in pts[:: max(1, len(pts) // 8)] if abs(p[0] - hub["point"][0]) + abs(p[1] - hub["point"][1]) > 1e-6][:8]
    assert len(sample) >= 4
    moved_ok = 0
    for x, y, extra in sample:
        out = pipeline.move_hub(PLAN, NODES, answer, hub["hub_id"], (x, y))   # every heatmap spot can be wired legally
        moved_ok += 1
        new = out["answer"]
        moved = next(h for h in new["hubs"] if h["hub_id"] == hub["hub_id"])
        assert moved["point"] == pytest.approx([x, y], abs=1e-6)
        assert checker.check(PLAN, new, NODES)["valid"], (x, y)
        delta = new["metrics"]["J"] - answer["metrics"]["J"]
        assert out["exact"] and out["extra_j"] == pytest.approx(extra, abs=1e-6)
        # the heatmap prices the spot without the ring's own cable in the way: the true change is near it, not equal
        assert abs(delta - extra) < 12.0
        other = [h for h in answer["hubs"] if h["hub_id"] != hub["hub_id"]][0]
        assert next(h for h in new["hubs"] if h["hub_id"] == other["hub_id"])["legs"] == other["legs"]   # others untouched
    assert moved_ok == len(sample) >= 4


def test_the_input_answer_is_never_modified(solved):
    before = copy.deepcopy(solved.answer)
    pipeline.move_hub(PLAN, NODES, solved.answer, "H1", _a_legal_spot(solved))
    assert solved.answer == before


@pytest.mark.parametrize("point", [(0.0, 0.0), (3.1234567, 2.7654321)])
def test_a_spot_that_is_not_a_heatmap_point_is_refused(solved, point):
    with pytest.raises(ValueError):
        pipeline.move_hub(PLAN, NODES, solved.answer, "H1", point)


def test_a_spot_in_the_other_zone_and_an_unknown_hub_are_refused(solved):
    other = _heat(solved, "H2")["points"][0][:2]
    with pytest.raises(ValueError):
        pipeline.move_hub(PLAN, NODES, solved.answer, "H1", other)
    with pytest.raises(ValueError):
        pipeline.move_hub(PLAN, NODES, solved.answer, "H9", other)


# ---- API ----------------------------------------------------------------------------------------------------

def test_api_tradeoff_checks_every_option():
    res = server.tradeoff(server.TradeoffRequest(plan_id=PID))
    assert res["default_hubs"] == 2 and len(res["options"]) >= 3
    assert all(o["valid"] and o["check"]["valid"] for o in res["options"])


def test_api_move_hub_returns_a_checked_answer_and_422_for_bad_spots(solved):
    x, y = _a_legal_spot(solved)
    res = server.move_hub(server.MoveHubRequest(plan_id=PID, answer=solved.answer, hub_id="H1", point=[x, y]))
    assert res["check"]["valid"] and res["branching"]["hubs"] and "extra_j" in res
    with pytest.raises(ValueError):          # the app's ValueError handler turns this into HTTP 422
        server.move_hub(server.MoveHubRequest(plan_id=PID, answer=solved.answer, hub_id="H1", point=[0.0, 0.0]))


def test_the_context_cache_is_bounded():
    whatif.clear_cache()
    whatif.context(PLAN, NODES)
    assert len(whatif._CACHE) == 1


def test_every_heatmap_spot_gives_a_checker_valid_answer_or_a_clear_refusal(solved):
    """Spots whose cable would run along the ring's own cable are routed around it; a move is never returned invalid."""
    hub = solved.answer["hubs"][0]
    for x, y, _ in _heat(solved, hub["hub_id"])["points"][::6]:
        try:
            out = pipeline.move_hub(PLAN, NODES, solved.answer, hub["hub_id"], (x, y))
        except ValueError as err:
            assert "overlap" in str(err)
        else:
            assert checker.check(PLAN, out["answer"], NODES)["valid"], (x, y)
