import copy
import json
import pickle
from pathlib import Path

import pytest

from eightball import cli, config
from eightball.evaluate import geom_indep
from eightball.evaluate.checker import check
from tests.fixtures import synthetic as S

FIX = Path(__file__).parent / "fixtures" / "json"


def _answer(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _rules(result):
    return {v["rule"] for v in result["violations"]}


@pytest.mark.parametrize("plan_id", [900001, 900002])
def test_valid_fixture_answers_pass(plan_id):
    result = check(S.PLANS[plan_id](), _answer(f"answer_{plan_id}_valid"), S.NODES[plan_id])
    assert result["valid"], result["violations"]
    assert result["metrics"]["J"] == pytest.approx(_answer(f"answer_{plan_id}_valid")["metrics"]["J"], abs=0.004)


@pytest.mark.parametrize("rule", ["coverage", "capacity", "zone", "ring", "free_space", "hub"])
def test_each_broken_fixture_is_caught(rule):
    result = check(S.synth_2hub(), _answer(f"answer_900002_broken_{rule}"), S.NODES[900002])
    assert not result["valid"]
    assert rule in _rules(result)


def test_isolated_violations_have_one_rule():
    for rule in ("capacity", "ring", "free_space", "hub"):
        result = check(S.synth_2hub(), _answer(f"answer_900002_broken_{rule}"), S.NODES[900002])
        assert _rules(result) == {rule}, (rule, result["violations"])


def test_door_links_and_single_door_rooms():
    g = geom_indep.build(S.synth_2hub())
    pairs = {tuple(sorted(e)) for e in g.links.edges()}
    order = S.IDS_2HUB
    assert pairs == {tuple(sorted((order[i], order[i + 1]))) for i in range(5)}
    assert {r for r in g.rooms if g.degree(r) == 1} == {"living_0", "bedroom_2"}
    assert not g.passages


def _retrace_1hub(inside_bedroom_only: bool):
    a = _answer("answer_900001_valid")
    legs = a["hubs"][0]["legs"]
    if inside_bedroom_only:
        # back from N2 along the same line inside the bedroom, then a 3 cm lane through the door
        legs[2]["polyline"] = [[6.05, 2.0], [4.6, 2.0], [4.6, 1.97], [1.0, 1.97]]
    else:
        # retrace the whole way back to the hub, through the door and across the living room
        a["hubs"][0]["point"] = [1.0, 2.0]
        legs[0]["polyline"] = [[1.0, 2.0], [1.95, 2.0]]
        legs[2]["polyline"] = [[6.05, 2.0], [1.0, 2.0]]
    return a


def test_retrace_inside_the_dead_end_room_is_allowed():
    result = check(S.synth_1hub(), _retrace_1hub(True), S.NODES[900001])
    assert result["valid"], result["violations"]
    assert result["metrics"]["O"] == pytest.approx(1.45, abs=0.002)


def test_retrace_spilling_out_of_the_dead_end_room_is_flagged():
    result = check(S.synth_1hub(), _retrace_1hub(False), S.NODES[900001])
    assert _rules(result) == {"ring"}
    assert any("outside dead-end room bedroom_0" in v["message"] for v in result["violations"])


def _crossing_answer(polyline):
    a = _answer("answer_900002_valid")
    a["hubs"][0]["legs"][3]["polyline"] = polyline
    return a


def test_consecutive_legs_crossing_at_right_angles_are_not_an_overlap():
    """Regression (Person A, plan 108): a perpendicular crossing is an X, never a retrace."""
    a = _crossing_answer([[10, 3], [10, 2.8], [8.5, 2.8], [8.5, 3.2], [1.5, 3.2], [1.5, 2.97], [1.0, 2.97]])
    result = check(S.synth_2hub(), a, S.NODES[900002])
    assert result["valid"], result["violations"]
    assert result["metrics"]["X"] == 2 and result["metrics"]["O"] == 0


def test_crossing_at_a_bend_of_the_other_leg_is_not_an_overlap():
    a = _crossing_answer([[10, 3], [10, 2.8], [8.5, 2.8], [8.5, 3.2], [1.5, 3.2], [1.5, 2.97], [1.0, 2.97]])
    a["hubs"][0]["legs"][2]["polyline"] = [[6.0, 3.0], [8.5, 3.0], [8.5, 3.0002], [10.0, 3.0002], [10.0, 3.0]]
    result = check(S.synth_2hub(), a, S.NODES[900002])
    assert not any(v["rule"] == "ring" for v in result["violations"]), result["violations"]


def test_collinear_pieces_ignore_points():
    from eightball.evaluate.checker import collinear_pieces

    assert collinear_pieces([[0, 0], [4, 0]], [[2, -1], [2, 1]], 1.0) == []          # cross
    assert collinear_pieces([[0, 0], [4, 0]], [[4, 0], [4, 2]], 1.0) == []           # touch at an end
    pieces = collinear_pieces([[0, 0], [4, 0]], [[3, 0], [6, 0]], 1.0)                # share [3, 4]
    assert len(pieces) == 1 and pieces[0].length == pytest.approx(1.0)
    assert collinear_pieces([[0, 0], [4, 0]], [[0, 0.0015], [4, 0.0015]], 1.0) == []  # 1.5 mm apart


def test_retrace_outside_single_door_rooms_is_flagged():
    a = _answer("answer_900002_valid")
    ring = a["hubs"][0]
    ring["point"] = [1.0, 3.0]
    ring["legs"][0]["polyline"] = [[1.0, 3.0], [1.95, 3.0]]
    ring["legs"][3]["polyline"] = [[10.0, 3.0], [1.0, 3.0]]
    result = check(S.synth_2hub(), a, S.NODES[900002])
    assert _rules(result) == {"ring"}


def test_through_other_zones_switch():
    prev = config.override(ALLOW_THROUGH_OTHER_ZONES=True)
    try:
        result = check(S.synth_2hub(), _answer("answer_900002_broken_zone"), S.NODES[900002])
        assert not any("enters" in v["message"] for v in result["violations"])
    finally:
        config.override(**prev)


def test_moved_node_is_a_coverage_violation():
    a = _answer("answer_900002_valid")
    a["nodes"][0]["point"] = [1.5, 3.0]
    assert "coverage" in _rules(check(S.synth_2hub(), a, S.NODES[900002]))


def test_hub_room_id_must_contain_hub():
    a = _answer("answer_900002_valid")
    a["hubs"][0]["room_id"] = "kitchen_0"
    assert _rules(check(S.synth_2hub(), a, S.NODES[900002])) == {"hub"}


def test_schema_errors_short_circuit():
    a = _answer("answer_900002_valid")
    a["schema_version"] = "nope"
    result = check(S.synth_2hub(), a, S.NODES[900002])
    assert _rules(result) == {"schema"} and not result["valid"]


def test_check_cli_on_fixture(tmp_path, capsys):
    plan_file = tmp_path / "plan.pkl"
    plan_file.write_bytes(pickle.dumps(S.synth_2hub()))
    out = tmp_path / "result.json"
    code = cli.main(["check", "--plan-file", str(plan_file), "--answer", str(FIX / "answer_900002_broken_hub.json"),
                     "--nodes", "file", "--nodes-file", str(FIX / "nodes_900002.json"), "--out", str(out)])
    assert code == 1
    assert "hub [H1]" in capsys.readouterr().out
    assert json.loads(out.read_text())["valid"] is False
    code = cli.main(["check", "--plan-file", str(plan_file), "--answer", str(FIX / "answer_900002_valid.json"),
                     "--nodes", "file", "--nodes-file", str(FIX / "nodes_900002.json")])
    assert code == 0
