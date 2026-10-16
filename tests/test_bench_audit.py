from eightball.bench import audit
from eightball.evaluate import geom_indep
from tests.fixtures import synthetic as S


def test_zone_count_matches_fixture_candidates():
    g = geom_indep.build(S.synth_2hub())
    assert audit.count_zones(g) == len(S.zone_candidates_2hub()["candidates"]) == 18


def test_zone_count_one_hub_plan():
    assert audit.count_zones(geom_indep.build(S.synth_1hub())) == 3  # living, bedroom, both


def test_fast_and_graph_facts_on_synthetic_plans():
    plans = [S.synth_1hub(), S.synth_2hub()]
    fast = audit.fast_facts(plans)
    assert fast["plans"] == 2
    assert fast["hub_lower_bound"] == {"1": 1, "2": 1}
    assert fast["doors"]["total"] == 6 and fast["doors"]["gt50pct_wall_share"] == 0
    assert fast["axis_aligned"]["share_ge_99pct"] == 1.0
    graph = audit.graph_facts(plans)
    assert graph["eligible_rooms_with_no_link"] == 0
    assert graph["passages_per_plan"] == 0
    report = audit.render(fast, graph, {"fast": 0.0, "graph": 0.0, "split": "synthetic"})
    assert report.startswith("# Data facts") and "| Plans |" in report
