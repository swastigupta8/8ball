"""Short-circuit isolators (V2 feature 1): placement, the effect of a short, and the API key."""
import json
import math
from pathlib import Path

import pytest

from eightball.optimize import isolators as iso

FIX = Path(__file__).parent / "fixtures" / "json"


def _ring(n: int, hub_id: str = "H1") -> dict:
    """A synthetic ring of n devices on a line: hub at x=0, devices at x=2, 4, ... (legs are straight)."""
    seq = [hub_id] + [f"N{k}" for k in range(1, n + 1)] + [hub_id]
    pts = [[0.0, 0.0]] + [[2.0 * k, 0.0] for k in range(1, n + 1)] + [[0.0, 0.0]]
    legs = [{"from": seq[i], "to": seq[i + 1], "polyline": [pts[i], pts[i + 1]]} for i in range(n + 1)]
    return {"hub_id": hub_id, "sequence": seq, "legs": legs, "node_ids": seq[1:-1]}


def _answer(*rings: dict) -> dict:
    return {"hubs": list(rings)}


@pytest.mark.parametrize("n,k,expected", [(5, 1, 4), (5, 2, 2), (5, 3, 1), (5, 4, 1), (5, 5, 0), (1, 1, 0), (2, 1, 1)])
def test_isolator_count_is_ceil_n_over_k_minus_one(n, k, expected):
    assert iso.isolator_count(n, k) == expected
    assert len(iso.place_isolators(_answer(_ring(n)), k)) == expected


def test_five_device_ring_with_k2_gets_two_isolators_and_worst_short_loses_at_most_two():
    ans = _answer(_ring(5))
    placed = iso.place_isolators(ans, 2)
    assert [p["leg_index"] for p in placed] == [2, 4]
    assert iso.worst_short(ans, placed) == 2
    for leg in range(6):  # a short anywhere on the ring
        assert len(iso.short_effect(ans, placed, "H1", leg, t=0.25)) <= 2
        assert len(iso.short_effect(ans, placed, "H1", leg, t=0.75)) <= 2


def test_k_equal_to_the_ring_size_needs_no_isolator_and_a_short_loses_everything():
    ans = _answer(_ring(5))
    assert iso.place_isolators(ans, 5) == []
    assert iso.short_effect(ans, [], "H1", 2) == ["N1", "N2", "N3", "N4", "N5"]
    assert iso.worst_short(ans, []) == 5


def test_with_no_isolators_a_short_loses_all_devices_on_any_leg():
    ans = _answer(_ring(4))
    for leg in range(5):
        assert iso.short_effect(ans, [], "H1", leg) == ["N1", "N2", "N3", "N4"]


def test_a_short_on_the_hubs_own_legs_loses_only_its_segment():
    ans = _answer(_ring(5))
    placed = iso.place_isolators(ans, 2)            # isolators on legs 2 and 4: segments {N1,N2} {N3,N4} {N5}
    assert iso.short_effect(ans, placed, "H1", 0) == ["N1", "N2"]
    assert iso.short_effect(ans, placed, "H1", 5) == ["N5"]


def test_a_short_next_to_an_isolator_belongs_to_the_side_it_is_on():
    ans = _answer(_ring(5))
    placed = iso.place_isolators(ans, 2)
    assert iso.short_effect(ans, placed, "H1", 2, t=0.2) == ["N1", "N2"]
    assert iso.short_effect(ans, placed, "H1", 2, t=0.8) == ["N3", "N4"]
    assert iso.short_effect(ans, placed, "H1", 2) == ["N1", "N2", "N3", "N4"]    # no t: both sides


def test_isolator_sits_in_the_middle_of_its_leg():
    ans = _answer(_ring(3))
    (p,) = iso.place_isolators(ans, 2)
    assert p["leg_index"] == 2 and p["point"] == pytest.approx([5.0, 0.0])      # leg 2 runs x=4 -> x=6
    l_shape = [[0, 0], [4, 0], [4, 2]]
    assert iso.polyline_midpoint(l_shape) == pytest.approx([3.0, 0.0])           # 3 of the 6 units along it


def test_rings_are_independent_and_totals_add_up():
    ans = _answer(_ring(5, "H1"), _ring(2, "H2"))
    table = iso.isolator_table(ans)
    assert sorted(table) == ["1", "2", "3", "4", "5"]
    assert [len(table[str(k)]) for k in range(1, 6)] == [4 + 1, 2 + 0, 1 + 0, 1 + 0, 0]
    assert {p["hub_id"] for p in table["1"]} == {"H1", "H2"}
    assert iso.short_effect(ans, table["1"], "H2", 1, t=0.1) == ["N1"]


def test_bad_arguments_are_refused():
    ans = _answer(_ring(3))
    with pytest.raises(ValueError):
        iso.place_isolators(ans, 0)
    with pytest.raises(ValueError):
        iso.short_effect(ans, [], "H1", 9)
    with pytest.raises(KeyError):
        iso.short_effect(ans, [], "H9", 0)


def test_works_on_a_real_answer_file():
    answer = json.loads((FIX / "answer_900002_valid.json").read_text(encoding="utf-8"))
    for k in (1, 2, 3):
        placed = iso.place_isolators(answer, k)
        assert iso.worst_short(answer, placed) <= k
        assert len(placed) == sum(math.ceil((len(h["sequence"]) - 2) / k) - 1 for h in answer["hubs"])
    only_ring = answer["hubs"][0]
    n = len(only_ring["sequence"]) - 2
    assert iso.short_effect(answer, [], only_ring["hub_id"], 0) == only_ring["sequence"][1:-1] and n >= 1
