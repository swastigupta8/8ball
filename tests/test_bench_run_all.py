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


def test_unknown_gate_says_which_step():
    with pytest.raises(SystemExit, match="B5"):
        run_all.gate_ok([], "m2")


def test_batch_cli_fixture(tmp_path, capsys):
    assert cli.main(["batch", "--fixture", "--name", "c", "--out", str(tmp_path)]) == 0
    assert "gate valid: PASS" in capsys.readouterr().out
