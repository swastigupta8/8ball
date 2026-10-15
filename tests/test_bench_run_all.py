import json
from pathlib import Path

import pytest

from eightball import cli
from eightball.bench import run_all
from eightball.core.contracts import SolveResult
from eightball.optimize import pipeline
from tests.fixtures import synthetic as S

FIX = Path(__file__).parent / "fixtures" / "json"


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


def test_unbuilt_solver_is_not_built():
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


def test_cross_check_skips_until_zone_candidates_exist():
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
