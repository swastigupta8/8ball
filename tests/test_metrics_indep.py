import json
from pathlib import Path

import pytest

from eightball import config
from eightball.evaluate.metrics_indep import clash, score
from tests.metric_cases import CASES, check_result, to_answer

FIX = Path(__file__).parent / "fixtures" / "json"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_checker_metrics(case):
    assert check_result(score(to_answer(case), 1.0), case) == []


@pytest.mark.parametrize("name", ["answer_900001_valid.json", "answer_900002_valid.json"])
def test_fixture_answers_match_hand_metrics(name):
    answer = json.loads((FIX / name).read_text(encoding="utf-8"))
    got = score(answer, answer["scale"])
    exp = answer["metrics"]
    assert got["L"] == pytest.approx(exp["L"], abs=0.002)
    assert (got["X"], got["B"]) == (exp["X"], exp["B"])
    assert got["O"] == pytest.approx(exp["O"], abs=0.002)
    assert got["J"] == pytest.approx(exp["J"], abs=0.004)


def test_scale_is_applied():
    case = CASES[0]
    answer = to_answer(case)
    for hub in answer["hubs"]:
        hub["point"] = [v * 20 for v in hub["point"]]
        for leg in hub["legs"]:
            leg["polyline"] = [[x * 20, y * 20] for x, y in leg["polyline"]]
    for n in answer["nodes"]:
        n["point"] = [v * 20 for v in n["point"]]
    assert check_result(score(answer, 20.0), case) == []


def test_touch_switch_off_ignores_t_touch():
    case = next(c for c in CASES if c["id"] == "08_t_touch")
    prev = config.override(TOUCH_IS_CROSSING=False)
    try:
        assert score(to_answer(case), 1.0)["X"] == 0
    finally:
        config.override(**prev)


def test_other_node_switch_off_excludes_node_touch():
    case = next(c for c in CASES if c["id"] == "12_through_other_node")
    prev = config.override(PASS_OTHER_NODE_IS_CROSSING=False)
    try:
        assert score(to_answer(case), 1.0)["X"] == 0
    finally:
        config.override(**prev)


def test_clash_between_two_rings():
    ring_a = [(0, 0), (4, 0), (4, 2), (0, 2)]
    ring_b = [(1, -2), (3, -2), (3, 0), (1, 0)]  # shares [1,3] of y=0 with ring_a
    assert clash(ring_a, ring_b, 1.0) == (0, pytest.approx(2.0))
    ring_c = [(2, -1), (2, 1), (3, 1), (3, -1)]  # crosses ring_a's bottom edge twice
    assert clash(ring_a, ring_c, 1.0)[0] == 2
