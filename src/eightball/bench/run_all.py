"""Batch runner (Person B, step B4 / handoff S1.7): solve many plans, check each, summarise.

    python -m eightball batch --split train --limit 10 --solver greedy --nodes center [--name i1]
    python -m eightball batch --fixture                      # replay the synthetic fixture answers
    extra flags: --gate valid|none   --overlays   --plans 14433,1448

Per run it writes data/out/runs/<name>/: one folder per (plan, solver, nodes) with answer.json,
check.json and (with --overlays, or for runs of <= 20 items) overlay.svg; plus summary.json and
summary.csv. The exit code is the gate: 0 only if the gate holds. Gate "valid" (default) = every
answer valid and no metric mismatch between the solver's reported metrics and the checker's.
B5 adds the full differential runner (multiprocessing, parquet, M2/M3 gates).
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from eightball import config
from eightball.evaluate import checker
from eightball.io import answer_io, nodes as nodes_io, resplan

LEN_TOL_M = 0.001  # lengths must agree within 1 mm; counts exactly (handoff 6 step 10)


@dataclass
class Record:
    plan_id: int
    solver: str
    nodes: str
    status: str                 # ok | solver_error | not_built | answer_error
    valid: bool = False
    hubs: int | None = None
    J: float | None = None
    L: float | None = None
    X: int | None = None
    O: float | None = None
    B: int | None = None
    J_solver: float | None = None
    mismatch: list[str] = field(default_factory=list)
    violations: int = 0
    rules: list[str] = field(default_factory=list)
    runtime_s: float = 0.0
    error: str = ""


def metric_mismatch(reported: dict, checked: dict) -> list[str]:
    """Differences between the solver's reported (core) metrics and the checker's own."""
    out = []
    for key in ("L", "O"):
        if key in reported and abs(float(reported[key]) - float(checked[key])) > LEN_TOL_M:
            out.append(f"{key}: solver {reported[key]:.4f} vs checker {checked[key]:.4f}")
    for key in ("X", "B"):
        if key in reported and int(reported[key]) != int(checked[key]):
            out.append(f"{key}: solver {reported[key]} vs checker {checked[key]}")
    return out


def select_plan_ids(split: str, limit: int | None, explicit: str | None = None) -> list[int]:
    if explicit:
        return [int(x) for x in explicit.split(",") if x.strip()]
    ids = resplan.split_ids(split)
    return ids[:limit] if limit else ids


def _solve(plan: dict, nodes: list[dict], solver: str):
    from eightball.optimize import pipeline

    return pipeline.solve(plan, nodes, solver=solver)


def run_one(plan: dict, nodes: list[dict], solver: str, nodes_mode: str, out_dir: Path | None,
            answer: dict | None = None, overlay: bool = False) -> Record:
    """Solve (or replay `answer`), check and save one item."""
    rec = Record(plan_id=int(plan["id"]), solver=solver, nodes=nodes_mode, status="ok")
    t0 = time.perf_counter()
    if answer is None:
        try:
            answer = _solve(plan, nodes, solver).answer
        except NotImplementedError as exc:
            rec.status, rec.error = "not_built", str(exc)
            return rec
        except Exception as exc:  # a crash on one plan must not stop the batch
            rec.status, rec.error = "solver_error", f"{type(exc).__name__}: {exc}"
            rec.runtime_s = time.perf_counter() - t0
            return rec
    rec.runtime_s = float(answer.get("meta", {}).get("runtime_s") or (time.perf_counter() - t0))
    shape = answer_io.answer_errors(answer)
    result = checker.check(plan, answer, nodes)
    m = result["metrics"]
    rec.valid = result["valid"]
    rec.violations = len(result["violations"])
    rec.rules = sorted({v["rule"] for v in result["violations"]})
    if shape and any(e.startswith("schema:") for e in shape):
        rec.status, rec.error = "answer_error", shape[0]
    if m:
        rec.hubs, rec.J, rec.L, rec.X, rec.O, rec.B = m["H"], m["J"], m["L"], m["X"], m["O"], m["B"]
        reported = answer.get("metrics", {})
        rec.J_solver = reported.get("J")
        rec.mismatch = metric_mismatch(reported, m)
    if out_dir is not None:
        item = out_dir / f"{rec.plan_id}_{solver}_{nodes_mode}"
        item.mkdir(parents=True, exist_ok=True)
        (item / "answer.json").write_text(json.dumps(answer, indent=1), encoding="utf-8")
        (item / "check.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        if overlay:
            from eightball.viz.overlay import render

            render(plan, answer, item / "overlay.svg", nodes, result)
    return rec


def gate_ok(records: list[Record], gate: str) -> tuple[bool, str]:
    if gate == "none":
        return True, "no gate"
    if gate == "valid":
        bad = [r for r in records if r.status != "ok" or not r.valid or r.mismatch]
        if not records:
            return False, "no plans ran"
        return not bad, f"{len(records) - len(bad)}/{len(records)} valid with matching metrics"
    raise SystemExit(f"gate '{gate}' is not built yet (Person B, step B5)")


def summarize(records: list[Record]) -> str:
    head = f"{'plan':>8} {'solver':<7} {'nodes':<7} {'status':<12} {'valid':<5} {'H':>2} {'J':>9} {'X':>2} {'O':>7} {'B':>3} {'t(s)':>6}  notes"
    lines = [head, "-" * len(head)]
    for r in records:
        j = f"{r.J:9.3f}" if r.J is not None else f"{'-':>9}"
        o = f"{r.O:7.3f}" if r.O is not None else f"{'-':>7}"
        notes = r.error or ", ".join(r.rules + [f"mismatch {m}" for m in r.mismatch])
        lines.append(f"{r.plan_id:>8} {r.solver:<7} {r.nodes:<7} {r.status:<12} {str(r.valid):<5} "
                     f"{r.hubs if r.hubs is not None else '-':>2} {j} {r.X if r.X is not None else '-':>2} {o} "
                     f"{r.B if r.B is not None else '-':>3} {r.runtime_s:6.2f}  {notes[:70]}")
    ok = [r for r in records if r.status == "ok"]
    valid = [r for r in ok if r.valid]
    js = [r.J for r in valid if r.J is not None]
    lines.append("-" * len(head))
    lines.append(f"{len(valid)}/{len(records)} valid | {sum(bool(r.mismatch) for r in ok)} metric mismatches | "
                 f"mean J {sum(js) / len(js):.3f}" if js else f"{len(valid)}/{len(records)} valid")
    return "\n".join(lines)


def write_summary(records: list[Record], out_dir: Path, meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(r) for r in records]
    (out_dir / "summary.json").write_text(json.dumps({"meta": meta, "records": rows}, indent=1), encoding="utf-8")
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["plan_id"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("; ".join(v) if isinstance(v, list) else v) for k, v in row.items()})


def fixture_items():
    """(plan, nodes, answer) for the synthetic fixtures' valid answers. Needs the repo's tests/ folder."""
    from tests.fixtures import synthetic as S

    fix = Path("tests/fixtures/json")
    for plan_id in (900001, 900002):
        answer = json.loads((fix / f"answer_{plan_id}_valid.json").read_text(encoding="utf-8"))
        yield S.PLANS[plan_id](), S.NODES[plan_id], answer


def run(split="train", limit=None, solvers=("greedy",), node_modes=("center",), name=None, fixture=False,
        gate="valid", overlays=None, plans=None, out_root=None) -> tuple[list[Record], bool, str]:
    name = name or time.strftime("run_%Y%m%d_%H%M%S")
    out_dir = Path(out_root or Path(str(config.DATA_DIR)) / "out" / "runs") / name
    records: list[Record] = []
    if fixture:
        for plan, nodes, answer in fixture_items():
            records.append(run_one(plan, nodes, "fixture", "fixture", out_dir, answer=answer, overlay=True))
    else:
        ids = select_plan_ids(split, limit, plans)
        draw = overlays if overlays is not None else len(ids) * len(solvers) * len(node_modes) <= 20
        for pid in ids:
            plan = resplan.get_plan(pid)
            for mode in node_modes:
                nodes = nodes_io.get_nodes(plan, mode)
                for solver in solvers:
                    rec = run_one(plan, nodes, solver, mode, out_dir, overlay=draw)
                    records.append(rec)
                    if rec.status == "not_built":
                        ok, why = False, f"solver '{solver}' not built yet: {rec.error}"
                        write_summary(records, out_dir, {"name": name, "gate": gate, "stopped": why})
                        return records, ok, why
    ok, why = gate_ok(records, gate)
    write_summary(records, out_dir, {"name": name, "split": split, "limit": limit, "solvers": list(solvers),
                                     "nodes": list(node_modes), "gate": gate, "gate_ok": ok, "gate_note": why,
                                     "config_hash": config.config_hash()})
    return records, ok, why


def cli_main(args: argparse.Namespace) -> int:
    own = argparse.ArgumentParser(prog="eightball batch")
    own.add_argument("--gate", default="valid")
    own.add_argument("--overlays", action="store_true", default=None)
    own.add_argument("--plans", help="comma list of plan ids instead of --split/--limit")
    extra = own.parse_args(getattr(args, "extra", []))
    if args.workers and args.workers > 1:
        print("note: --workers > 1 arrives with B5; running sequentially")
    records, ok, why = run(split=args.split, limit=args.limit, solvers=tuple(args.solver.split(",")),
                           node_modes=tuple(args.nodes.split(",")), name=args.name, fixture=args.fixture,
                           gate=extra.gate, overlays=extra.overlays, plans=extra.plans, out_root=args.out)
    print(summarize(records))
    print(f"gate {extra.gate}: {'PASS' if ok else 'FAIL'} ({why})")
    if any(r.status == "not_built" for r in records):
        return 2
    return 0 if ok else 1
