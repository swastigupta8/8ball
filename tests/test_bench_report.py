import pytest

from eightball.bench import gallery, report
from eightball.bench import run_all
from tests.fixtures import synthetic as S


def _rec(plan_id, solver, J, valid=True, hubs=2, bound=2, nodes="center", rules=(), mismatch=()):
    return {"plan_id": plan_id, "solver": solver, "nodes": nodes, "status": "ok", "valid": valid, "hubs": hubs,
            "J": J, "runtime_s": 0.5, "rules": list(rules), "mismatch": list(mismatch), "min_hubs_bound": bound}


def test_dashboard_from_fixture_run(tmp_path):
    run_all.run(fixture=True, name="r", out_root=tmp_path)
    dash = report.from_run(tmp_path / "r")
    assert dash["schema_version"] == "8ball-dashboard/1"
    assert dash["n"] == 2 and dash["valid"] == 2 and dash["mismatches"] == 0
    assert dash["valid_share"] == 1.0 and dash["J"]["hist"]


def test_w_min_hub_share_and_failures():
    records = [
        _rec(1, "exact", 40.0), _rec(1, "greedy", 50.0),
        _rec(2, "exact", 30.0, hubs=3, bound=2), _rec(2, "greedy", 30.0),
        _rec(3, "exact", 20.0, valid=False, rules=("hub",)),
    ]
    dash = report.build(records, {"name": "t", "split": "test"})
    assert dash["solver"] == "exact" and dash["n"] == 3 and dash["valid"] == 2
    # plan 2's exact answer has 3 hubs vs greedy's 2: J isn't comparable, so only plan 1 counts
    assert dash["W"] == pytest.approx(0.2) and dash["W_pairs"] == 1
    assert dash["min_hub_share"] == pytest.approx(0.5)
    assert dash["failures"] == {"hub": 1}


def test_histogram_edges():
    assert report.histogram([]) == []
    assert report.histogram([5.0, 5.0]) == [[5.0, 5.0, 2]]
    bins = report.histogram([0.0, 1.0, 2.0, 3.0], bins=3)
    assert sum(b[2] for b in bins) == 4 and bins[0][0] == 0.0


def test_gallery_describe_synthetic():
    d = gallery.describe(S.synth_2hub())
    assert d["rooms"] == 6 and d["min_hubs"] == 2 and d["isolated"] == 0
    assert "open kitchen" not in d["tags"]


def test_paired_comparison_and_speed_numbers_for_the_results_cards():
    from eightball.bench import report

    def rec(plan, solver, hubs, J, t, nodes="center"):
        return {"plan_id": plan, "solver": solver, "nodes": nodes, "status": "ok", "valid": True, "hubs": hubs, "J": J,
                "runtime_s": t, "min_hubs_bound": hubs, "rules": []}

    records = [rec(1, "exact", 2, 40.0, 1.0), rec(1, "greedy", 3, 60.0, 0.5),    # fewer hubs
               rec(2, "exact", 2, 30.0, 2.0), rec(2, "greedy", 2, 45.0, 0.5),    # same hubs, cheaper
               rec(3, "exact", 1, 20.0, 9.0), rec(3, "greedy", 1, 20.0, 0.5)]    # a tie
    d = report.build(records)
    p = d["paired"]
    assert (p["n"], p["fewer_hubs"], p["cheaper_same_hubs"], p["tie"], p["worse"]) == (3, 1, 1, 1, 0)
    assert p["exact_J_mean"] == 30.0 and p["greedy_J_mean"] == 125 / 3
    assert d["runtime_s"]["share_under_5s"] == 2 / 3 and d["runtime_s"]["max"] == 9.0
    assert d["hubs"] == {"mean": 5 / 3, "max": 2}
