import copy
import json
from pathlib import Path

import pytest

from eightball import config
from eightball.core import contracts as C
from eightball.io import answer_io, nodes as nodes_io, resplan
from tests.fixtures import synthetic as S

FIX = Path(__file__).parent / "fixtures" / "json"


def test_config_override_and_hash():
    h0 = config.config_hash()
    prev = config.override(TIME_BUDGET_S=1.0)
    try:
        assert config.TIME_BUDGET_S == 1.0
        assert config.config_hash() != h0
    finally:
        config.override(**prev)
    assert config.config_hash() == h0


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("EIGHTBALL_ALLOW_THROUGH_OTHER_ZONES", "true")
    monkeypatch.setenv("EIGHTBALL_MAX_SPLITS", "7")
    config.reset()
    try:
        assert config.ALLOW_THROUGH_OTHER_ZONES is True and config.MAX_SPLITS == 7
    finally:
        monkeypatch.delenv("EIGHTBALL_ALLOW_THROUGH_OTHER_ZONES")
        monkeypatch.delenv("EIGHTBALL_MAX_SPLITS")
        config.reset()


def test_synthetic_room_ids_are_canonical():
    assert [r[0] for r in resplan.room_parts(S.synth_1hub())] == ["living_0", "bedroom_0"]
    plan = S.synth_2hub()
    ids = {rid: poly.bounds[0] for rid, _t, poly in resplan.room_parts(plan)}
    assert sorted(ids, key=ids.get) == S.IDS_2HUB
    assert resplan.scale(plan) == pytest.approx(1.0)


@pytest.mark.parametrize("plan_id", [900001, 900002])
def test_fixture_nodes_match_eligible_rooms(plan_id):
    plan = S.PLANS[plan_id]()
    rooms = {rid: poly for rid, _t, poly in resplan.eligible_rooms(plan)}
    fixture = S.NODES[plan_id]
    assert [n["room_id"] for n in fixture] == list(rooms)
    assert [n["node_id"] for n in fixture] == [f"N{k}" for k in range(1, len(rooms) + 1)]
    generated = nodes_io.make_nodes(plan, "center")
    assert [n["room_id"] for n in generated] == list(rooms)
    for mode in ("center", "random"):
        for n in nodes_io.make_nodes(plan, mode):
            from shapely.geometry import Point

            poly = rooms[n["room_id"]]
            assert poly.contains(Point(n["point"]))
            assert poly.exterior.distance(Point(n["point"])) >= 0.5 - 1e-6


def test_valid_answers_pass():
    for name in ("answer_900001_valid.json", "answer_900002_valid.json"):
        answer_io.read_answer(FIX / name)


def test_broken_rule_answers_pass_shape_checks():
    for rule in ("coverage", "capacity", "zone", "ring", "free_space", "hub"):
        answer_io.read_answer(FIX / f"answer_900002_broken_{rule}.json")


def _valid():
    return json.loads((FIX / "answer_900002_valid.json").read_text(encoding="utf-8"))


def test_rejects_missing_return_leg():
    a = _valid()
    a["hubs"][0]["legs"].pop()
    with pytest.raises(answer_io.AnswerError, match="return leg"):
        answer_io.validate_answer(a)


def test_rejects_non_axis_segment():
    a = _valid()
    a["hubs"][0]["legs"][1]["polyline"] = [[1.95, 3.0], [4.0, 3.2], [6.0, 3.0]]
    with pytest.raises(answer_io.AnswerError, match="not axis-aligned"):
        answer_io.validate_answer(a)


def test_rejects_wrong_schema_version():
    a = _valid()
    a["schema_version"] = "8ball-answer/0"
    with pytest.raises(answer_io.AnswerError, match="schema"):
        answer_io.validate_answer(a)


def test_rejects_leg_not_starting_at_node():
    a = _valid()
    a["hubs"][0]["legs"][1]["polyline"][0] = [1.9, 3.0]
    with pytest.raises(answer_io.AnswerError, match="does not start"):
        answer_io.validate_answer(a)


def test_heatmap_and_branching_fixtures_validate():
    assert answer_io.heatmap_errors(answer_io.read_json(FIX / "heatmap_900002_H1.json")) == []
    assert answer_io.branching_errors(answer_io.read_json(FIX / "branching_900002.json")) == []
    hm = answer_io.make_heatmap(1, "H1", [(0, 0, 1.0)], (0, 0))
    assert answer_io.heatmap_errors(hm) == []
    bad = copy.deepcopy(hm)
    del bad["chosen"]
    assert answer_io.heatmap_errors(bad)


def test_zone_candidates_fixture_round_trips():
    data = answer_io.read_json(FIX / "zone_candidates_900002.json")
    cands = [C.zone_candidate_from_json(d) for d in data["candidates"]]
    assert all(c.area_m2 <= config.MAX_AREA_M2 and c.n_nodes <= config.MAX_NODES_PER_HUB for c in cands)
    assert [C.zone_candidate_to_json(c) for c in cands] == data["candidates"]
    by_id = {c.zone_id: c for c in cands}
    chosen = [by_id[z] for z in data["expected"]["zone_ids"]]
    assert sorted(r for c in chosen for r in c.room_ids) == sorted(data["rooms"])
    assert sum(c.cost for c in chosen) == data["expected"]["cost"]


def test_fixture_json_is_up_to_date():
    expected = {
        "answer_900001_valid.json": S.answer_1hub(),
        "answer_900002_valid.json": S.answer_2hub(),
        "zone_candidates_900002.json": S.zone_candidates_2hub(),
    }
    for name, doc in expected.items():
        assert json.loads((FIX / name).read_text(encoding="utf-8")) == json.loads(json.dumps(doc)), \
            f"{name} is stale: run python -m tests.fixtures.make_fixtures"
