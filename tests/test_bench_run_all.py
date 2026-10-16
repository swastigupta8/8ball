import json
from pathlib import Path

import pytest

from eightball import cli
from eightball.bench import run_all
from eightball.core.contracts import SolveResult
from eightball.optimize import pipeline
from tests.fixtures import synthetic as S

FIX = Path(__file__).parent / "fixtures" / "json"


def _not_built(*_a, **_k):
    raise NotImplementedError("solver facade: Person A, step A4")


def _answer(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def test_fixture_run_passes_gate(tmp_path):
    records, ok, why = run_all.run(fixture=True, name="t", out_root=tmp_path)
    assert ok, why
    assert [r.plan_id for r in records] == [900001, 900002] and all(r.valid for r in records)
    summary = json.loads((tmp_path / "t" / "summary.json").read_text())
    assert summary["meta"]["gate_ok"] is True and len(summary["records"]) == 2
    assert (tmp_path / "t" / "900002_fixture_fixture" / "overlay.svg").exists()
    assert (tmp_path / "t" / "summary.csv").read_text().startswith("plan_id,")


def test_metric_mismatch_is_reported_and_fails_gate(tmp_path):
    answer = _answer("answer_900002_valid")
    answer["metrics"]["B"] = 7
    answer["metrics"]["L"] = 36.5
    rec = run_all.run_one(S.synth_2hub(), S.NODES[900002], "x", "fixture", None, answer=answer)
    assert rec.valid and len(rec.mismatch) == 2
    ok, _ = run_all.gate_ok([rec], "valid")
    assert not ok


def test_invalid_answer_fails_gate():
    rec = run_all.run_one(S.synth_2hub(), S.NODES[900002], "x", "fixture", None,
                          answer=_answer("answer_900002_broken_hub"))
    assert not rec.valid and rec.rules == ["hub"]
    assert run_all.gate_ok([rec], "valid")[0] is False
    assert run_all.gate_ok([rec], "none")[0] is True


def test_unbuilt_solver_is_not_built(monkeypatch):
    monkeypatch.setattr(pipeline, "solve", _not_built)
    rec = run_all.run_one(S.synth_1hub(), S.NODES[900001], "greedy", "fixture", None)
    assert rec.status == "not_built" and "Person A" in rec.error


def test_solver_crash_is_recorded_not_raised(monkeypatch):
    def boom(plan, nodes, solver="exact"):
        raise ValueError("bad geometry")
    monkeypatch.setattr(pipeline, "solve", boom)
    rec = run_all.run_one(S.synth_1hub(), S.NODES[900001], "greedy", "fixture", None)
    assert rec.status == "solver_error" and "bad geometry" in rec.error


def test_solver_result_is_checked(monkeypatch, tmp_path):
    answer = _answer("answer_900001_valid")
    monkeypatch.setattr(pipeline, "solve", lambda plan, nodes, solver="exact": SolveResult(answer, [], {}, 0.01))
    rec = run_all.run_one(S.synth_1hub(), S.NODES[900001], "greedy", "center", tmp_path, overlay=True)
    assert rec.status == "ok" and rec.valid and rec.J == pytest.approx(12.16, abs=0.004) and not rec.mismatch
    assert (tmp_path / "900001_greedy_center" / "check.json").exists()


def test_unknown_gate_is_rejected():
    with pytest.raises(SystemExit, match="unknown gate"):
        run_all.gate_ok([], "m9")


def _r(plan_id, solver, J, valid=True, hubs=2, nodes="center", mismatch=(), cpsat_agree=None):
    return run_all.Record(plan_id=plan_id, solver=solver, nodes=nodes, status="ok", valid=valid, hubs=hubs, J=J,
                          mismatch=list(mismatch), cpsat_agree=cpsat_agree)


def test_m2_gate():
    recs = [_r(1, "exact", 40), _r(1, "greedy", 50), _r(2, "exact", 30), _r(2, "greedy", 30)]
    run_all.pair_greedy(recs)
    ok, why = run_all.gate_ok(recs, "m2")
    assert ok and "W 12.5%" in why  # mean J 35 vs 40


def test_m2_compares_j_only_at_equal_hub_count():
    """Fewer hubs ranks first even when J rises; more hubs is always worse."""
    fewer = [_r(1, "exact", 70, hubs=2), _r(1, "greedy", 50, hubs=3), _r(2, "exact", 30), _r(2, "greedy", 40)]
    run_all.pair_greedy(fewer)
    assert run_all.gate_ok(fewer, "m2")[0]
    more = [_r(1, "exact", 30, hubs=3), _r(1, "greedy", 50, hubs=2)]
    run_all.pair_greedy(more)
    assert not run_all.gate_ok(more, "m2")[0]
    worse = [_r(1, "exact", 55), _r(1, "greedy", 50)]
    run_all.pair_greedy(worse)
    assert run_all.gate_ok(worse, "m2")[0] is False
    only_exact = [_r(1, "exact", 40)]
    assert "no exact/greedy pairs" in run_all.gate_ok(only_exact, "m2")[1]


def test_cpsat_and_m3_gates():
    good = [_r(1, "exact", 40, cpsat_agree=True), _r(2, "exact", 30, cpsat_agree=True)]
    assert run_all.gate_ok(good, "cpsat")[0] and run_all.gate_ok(good, "m3")[0]
    unchecked = [_r(1, "exact", 40, cpsat_agree=True), _r(2, "exact", 30)]
    assert not run_all.gate_ok(unchecked, "cpsat")[0]
    invalid = [_r(1, "exact", 40, valid=False, cpsat_agree=True)]
    assert run_all.gate_ok(invalid, "cpsat")[0] and not run_all.gate_ok(invalid, "m3")[0]


def test_cpsat_cross_check(monkeypatch):
    from eightball.core.contracts import zone_candidate_from_json

    data = json.loads((FIX / "zone_candidates_900002.json").read_text(encoding="utf-8"))
    cands = [zone_candidate_from_json(d) for d in data["candidates"]]
    monkeypatch.setattr(pipeline, "zone_candidates", lambda plan, nodes: (data["rooms"], cands))
    rec = _r(900002, "exact", 40.22)
    rec.min_hubs_bound, rec.best_additive_cost = 2, 62.0
    run_all.cpsat_cross_check(rec, S.synth_2hub(), S.NODES[900002])
    assert rec.cpsat_agree is True and rec.cpsat_hubs == 2 and rec.cpsat_cost == pytest.approx(62.0)
    rec.best_additive_cost = 61.0
    run_all.cpsat_cross_check(rec, S.synth_2hub(), S.NODES[900002])
    assert rec.cpsat_agree is False


def test_cross_check_skips_until_zone_candidates_exist(monkeypatch):
    monkeypatch.setattr(pipeline, "zone_candidates", _not_built)
    rec = _r(900002, "exact", 40.22)
    run_all.cpsat_cross_check(rec, S.synth_2hub(), S.NODES[900002])
    assert rec.cpsat_agree is None and "cross-check skipped" in rec.error


def test_meta_fields_are_recorded():
    answer = _answer("answer_900002_valid")
    answer["meta"].update({"min_hubs_bound": 2, "best_additive_cost": 62.0, "j_floor": 40.0})
    rec = run_all.run_one(S.synth_2hub(), S.NODES[900002], "exact", "fixture", None, answer=answer)
    assert (rec.min_hubs_bound, rec.best_additive_cost, rec.j_floor) == (2, 62.0, 40.0)


def test_fixture_run_writes_parquet(tmp_path):
    import pandas as pd

    run_all.run(fixture=True, name="p", out_root=tmp_path)
    df = pd.read_parquet(tmp_path / "p" / "runs.parquet")
    assert len(df) == 2 and set(df["valid"]) == {True}


def test_batch_cli_fixture(tmp_path, capsys):
    assert cli.main(["batch", "--fixture", "--name", "c", "--out", str(tmp_path)]) == 0
    assert "gate valid: PASS" in capsys.readouterr().out


def test_blocked_reason_from_solver_notes():
    no_split = {"meta": {"warnings": ["no split into 2 zone(s) exists (doors, passages ...)"]}}
    assert run_all.blocked_reason(no_split, False) == "Q13/Q14: no legal split"
    assert run_all.blocked_reason(no_split, True) == ""
    wall_node = {"meta": {"flags": ["node_clearance:N3"]}}
    assert run_all.blocked_reason(wall_node, False) == "Q15: node not on free floor"
    assert run_all.blocked_reason({"meta": {}}, False) == ""
    covers = {"meta": {"warnings": ["zone_split:storage_0", "no split covers every room"]}}
    assert run_all.blocked_reason(covers, False) == "Q13/Q14: no legal split"
    assert run_all.blocked_reason({"meta": {"flags": ["node_not_in_free_space:N2"]}}, False).startswith("Q15")


def test_regate_rescores_a_saved_run(tmp_path):
    run_all.run(fixture=True, name="g", out_root=tmp_path)
    records, ok, why = run_all.regate(tmp_path / "g", "valid")
    assert ok and len(records) == 2


def test_blocked_items_leave_the_gate_unless_strict():
    recs = [_r(1, "exact", 40), _r(2, "exact", 30, valid=False)]
    recs[1].blocked = "Q13/Q14: no legal split"
    ok, why = run_all.gate_ok(recs, "valid")
    assert ok and "1 item(s) on 1 plan(s) blocked" in why
    assert not run_all.gate_ok(recs, "valid", strict_blocked=True)[0]
    unexplained = [_r(1, "exact", 40), _r(2, "exact", 30, valid=False)]
    assert not run_all.gate_ok(unexplained, "valid")[0]


def test_cross_check_agrees_when_both_find_no_split(monkeypatch):
    monkeypatch.setattr(pipeline, "zone_candidates", lambda plan, nodes: (["a", "b"], []))
    rec = _r(47, "exact", 50.0)
    run_all.cpsat_cross_check(rec, S.synth_2hub(), S.NODES[900002])
    assert rec.cpsat_agree is True


def test_m2_needs_exact_valid_but_not_greedy():
    # plan 1's greedy answer is invalid (no comparison there); plan 2 gives the J comparison
    recs = [_r(1, "exact", 40), _r(1, "greedy", 50, valid=False), _r(2, "exact", 30), _r(2, "greedy", 35)]
    run_all.pair_greedy(recs)
    assert run_all.gate_ok(recs, "m2")[0]
    recs = [_r(1, "exact", 40, valid=False), _r(1, "greedy", 50)]
    run_all.pair_greedy(recs)
    assert not run_all.gate_ok(recs, "m2")[0]



def test_cpsat_gate_allows_cheaper_cpsat_when_search_was_cut():
    fine = _r(1, "exact", 40, cpsat_agree=True)
    cut = _r(2, "exact", 50, cpsat_agree=False)
    cut.search_complete, cut.cpsat_hubs, cut.cpsat_cost, cut.best_additive_cost = False, 2, 49.0, 52.0
    ok, why = run_all.gate_ok([fine, cut], "cpsat")
    assert ok and "1 search(es) cut by the time budget (CP-SAT cheaper on 1" in why
    finished_disagree = _r(3, "exact", 50, cpsat_agree=False)
    assert not run_all.gate_ok([fine, finished_disagree], "cpsat")[0]


def test_search_complete_reads_solver_notes():
    assert run_all.search_complete({"meta": {}})
    assert run_all.search_complete({"meta": {"warnings": ["3 zone(s) not priced (not in a fewest-hub split ...)"]}})
    assert not run_all.search_complete({"meta": {"warnings": ["no split into 2 zone(s) exists (doors ...)"]}})
    assert not run_all.search_complete({"meta": {"warnings": ["split chosen by the backup solver"]}})


def test_m3_needs_exact_valid_but_not_greedy():
    recs = [_r(1, "exact", 40, cpsat_agree=True), _r(1, "greedy", 50, valid=False)]
    assert run_all.gate_ok(recs, "m3")[0]
