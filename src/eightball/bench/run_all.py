"""Batch runner and differential test (Person B, steps B4 + B5 / handoff S1.7, S2.9).

    python -m eightball batch --split train --limit 1000 --solver exact,greedy --nodes center,random --workers 4 --name m2
    python -m eightball batch --fixture                      # replay the synthetic fixture answers
    extra flags: --gate valid|m2|cpsat|m3|none   --cross-check   --overlays   --plans 14433,1448   --dashboard

Each item (plan, node mode, solver) is solved through pipeline.solve, checked by the independent checker,
and compared metric by metric (solver-reported core metrics vs checker metrics). Optionally, the CP-SAT
zone solver is run on the plan's zone candidates and compared with the exhaustive search's additive cost.

Writes data/out/runs/<name>/: per item answer.json, check.json (+ overlay.svg for small runs or with
--overlays); summary.json, summary.csv and runs.parquet. With --dashboard it also writes
web/data/dashboard.json. The exit code is the gate: 0 only when it holds.

Gates:
  Items marked "blocked" (invalid only because of an open organiser question, see blocked_reason) are
  reported separately and left out of every gate; --strict-blocked counts them as failures.
  valid  every item valid, no metric mismatch (I1)
  m2     valid + exact J <= greedy J on every (plan, nodes) pair + lower on average (M2, I2)
  cpsat  CP-SAT matches exhaustive search's hub count and additive cost on every exact item
  m3     valid + CP-SAT matches on every exact item (M3, I3)
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from eightball import config
from eightball.evaluate import checker
from eightball.io import answer_io, nodes as nodes_io, resplan

LEN_TOL_M = 0.001  # lengths must agree within 1 mm; counts exactly (handoff 6 step 10)
GATES = ("valid", "m2", "cpsat", "m3", "none")


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
    min_hubs_bound: int | None = None
    best_additive_cost: float | None = None
    j_floor: float | None = None
    greedy_J: float | None = None
    greedy_hubs: int | None = None
    cpsat_hubs: int | None = None
    cpsat_cost: float | None = None
    cpsat_agree: bool | None = None
    blocked: str = ""           # open-question reason when the plan has no legal answer under the strict reading
    search_complete: bool | None = None  # False when the exact search was cut by the time budget


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


def blocked_reason(answer: dict, valid: bool) -> str:
    """Why an invalid answer is out of the solver's hands under the strict reading (open questions 13-15).

    Person A's solver says so in meta.warnings ("no split covers every room", "no split into N zone(s)
    exists ...") or meta.flags (node_not_in_free_space, node_clearance, node_bad_room). Valid answers are
    never blocked."""
    if valid:
        return ""
    meta = answer.get("meta", {})
    if any(str(w).startswith(("no split into", "no split covers every room")) for w in meta.get("warnings", [])):
        return "Q13/Q14: no legal split"
    if any(str(f).startswith(("node_not_in_free_space", "node_clearance", "node_bad_room")) for f in meta.get("flags", [])):
        return "Q15: node not on free floor"
    return ""


def search_complete(answer: dict) -> bool:
    """False when Person A's exact search didn't cover every fewest-hub split: the backup solver picked
    the split (time budget), or no split existed at the lower bound and the search retried with more
    hubs. Its best_additive_cost is then not the optimum CP-SAT is compared against. ("N zone(s) not
    priced" alone is normal: zones outside every fewest-hub split are never priced.)"""
    notes = [str(w) for w in answer.get("meta", {}).get("warnings", [])]
    return not any("backup solver" in w or w.startswith("no split into") for w in notes)


def cpsat_cross_check(rec: Record, plan: dict, nodes: list[dict]) -> None:
    """Run CP-SAT on the plan's zone candidates; it must match the exhaustive search's hub count and
    best additive cost (handoff 6.2). Fills rec.cpsat_*; leaves cpsat_agree None if it can't run."""
    from eightball.optimize import pipeline
    from eightball.optimize.cpsat import CpSatZoneSolver

    try:
        rooms, cands = pipeline.zone_candidates(plan, nodes)
    except Exception as exc:  # e.g. a node off the floor (Q15): note it, keep the solve result
        rec.error = (rec.error + "; " if rec.error else "") + f"cross-check skipped: {exc}"
        return
    sel = CpSatZoneSolver().select(rooms, cands, rec.min_hubs_bound or 1, float(config.TIME_BUDGET_S))
    rec.cpsat_hubs, rec.cpsat_cost = sel.hubs, sel.cost
    ref = rec.best_additive_cost
    if not sel.zone_ids and ref is None:
        rec.cpsat_agree = True  # both solvers find no legal split
        return
    rec.cpsat_agree = bool(
        sel.zone_ids and ref is not None and sel.hubs == rec.hubs
        and abs(sel.cost - ref) <= 1e-3 * max(1.0, abs(ref)))


def run_one(plan: dict, nodes: list[dict], solver: str, nodes_mode: str, out_dir: Path | None,
            answer: dict | None = None, overlay: bool = False, cross_check: bool = False) -> Record:
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
    meta = answer.get("meta", {})
    rec.runtime_s = float(meta.get("runtime_s") or (time.perf_counter() - t0))
    rec.min_hubs_bound = meta.get("min_hubs_bound")
    rec.best_additive_cost = meta.get("best_additive_cost")
    rec.j_floor = meta.get("j_floor")
    shape = answer_io.answer_errors(answer)
    result = checker.check(plan, answer, nodes)
    m = result["metrics"]
    rec.valid = result["valid"]
    rec.blocked = blocked_reason(answer, rec.valid)
    rec.search_complete = search_complete(answer) if solver == "exact" else None
    rec.violations = len(result["violations"])
    rec.rules = sorted({v["rule"] for v in result["violations"]})
    if shape and any(e.startswith("schema:") for e in shape):
        rec.status, rec.error = "answer_error", shape[0]
    if m:
        rec.hubs, rec.J, rec.L, rec.X, rec.O, rec.B = m["H"], m["J"], m["L"], m["X"], m["O"], m["B"]
        reported = answer.get("metrics", {})
        rec.J_solver = reported.get("J")
        rec.mismatch = metric_mismatch(reported, m)
    if cross_check and solver == "exact" and rec.status == "ok" and not rec.blocked:
        cpsat_cross_check(rec, plan, nodes)
    if out_dir is not None:
        item = out_dir / f"{rec.plan_id}_{solver}_{nodes_mode}"
        item.mkdir(parents=True, exist_ok=True)
        (item / "answer.json").write_text(json.dumps(answer, indent=1), encoding="utf-8")
        (item / "check.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        if overlay:
            from eightball.viz.overlay import render

            render(plan, answer, item / "overlay.svg", nodes, result)
    return rec


def _task(plan_id: int, mode: str, solvers: tuple[str, ...], out_dir: str, overlay: bool, cross_check: bool) -> list[dict]:
    """One (plan, node mode) with every solver. Top level so worker processes can run it."""
    plan = resplan.get_plan(plan_id)
    nodes = nodes_io.get_nodes(plan, mode)
    out = []
    for solver in solvers:
        rec = run_one(plan, nodes, solver, mode, Path(out_dir), overlay=overlay, cross_check=cross_check)
        out.append(asdict(rec))
        if rec.status == "not_built":
            break
    return out


def _init_worker(data_dir: str, overrides: dict) -> None:
    config.override(DATA_DIR=data_dir, **overrides)
    resplan.load_plans()  # load the pickle once per worker


def pair_greedy(records: list[Record]) -> None:
    """Attach each item's greedy J (same plan and nodes) for the W% and M2 comparisons."""
    greedy = {(r.plan_id, r.nodes): r for r in records if r.solver == "greedy" and r.valid}
    for r in records:
        g = greedy.get((r.plan_id, r.nodes)) if r.solver != "greedy" else None
        if g is not None:
            r.greedy_J, r.greedy_hubs = g.J, g.hubs


def gate_ok(records: list[Record], gate: str, strict_blocked: bool = False) -> tuple[bool, str]:
    if gate not in GATES:
        raise SystemExit(f"unknown gate '{gate}' (choose from {', '.join(GATES)})")
    if gate == "none":
        return True, "no gate"
    if not records:
        return False, "no plans ran"
    blocked = [r for r in records if r.blocked]
    if blocked and not strict_blocked:
        ok, why = gate_ok([r for r in records if not r.blocked], gate)
        plans = len({r.plan_id for r in blocked})
        return ok, f"{why}; {len(blocked)} item(s) on {plans} plan(s) blocked by open questions 13-15, not counted"
    bad = [r for r in records if r.status != "ok" or not r.valid or r.mismatch]
    valid_note = f"{len(records) - len(bad)}/{len(records)} valid with matching metrics"
    if gate == "valid":
        return not bad, valid_note
    exact = [r for r in records if r.solver == "exact"]
    if gate in ("cpsat", "m3"):
        # Exact answers must be valid; greedy is only the yardstick (its mismatches still count).
        bad = [r for r in records if r.status != "ok" or r.mismatch or (r.solver == "exact" and not r.valid)]
        valid_note = (f"{sum(1 for r in exact if r.valid)}/{len(exact)} exact answers valid; "
                      f"{sum(1 for r in records if r.mismatch)} metric mismatches")
        # Where the exact search finished, CP-SAT must match it; where the time budget cut it, CP-SAT
        # may only be cheaper (it prices every zone).
        complete = [r for r in exact if r.search_complete is not False]
        cut = [r for r in exact if r.search_complete is False]
        unchecked = [r for r in exact if r.status == "ok" and r.cpsat_agree is None]
        mismatched = [r for r in complete if r.cpsat_agree is False]
        cut_worse = [r for r in cut if r.cpsat_agree is False and r.cpsat_hubs == r.hubs and r.cpsat_cost is not None
                     and r.best_additive_cost is not None and r.cpsat_cost > r.best_additive_cost + 1e-3]
        cut_cheaper = [r for r in cut if r.cpsat_agree is False and r not in cut_worse]
        cp_ok = bool(exact) and not unchecked and not mismatched and not cut_worse
        cp_note = (f"CP-SAT matches the exact search on {len(complete) - len(mismatched) - len([r for r in complete if r.cpsat_agree is None])}"
                   f"/{len(complete)} finished searches; {len(cut)} search(es) cut by the time budget "
                   f"(CP-SAT cheaper on {len(cut_cheaper)}, worse on {len(cut_worse)}); {len(unchecked)} not checked")
        if gate == "cpsat":
            return cp_ok, cp_note
        return (not bad) and cp_ok, f"{valid_note}; {cp_note}"
    # m2: the exact solver must be valid; greedy is only the yardstick (its mismatches still count).
    # Ranking is hubs first, then J, so J is compared only at equal hub count.
    bad = [r for r in records if r.status != "ok" or r.mismatch or (r.solver == "exact" and not r.valid)]
    valid_note = (f"{sum(1 for r in exact if r.valid)}/{len(exact)} exact answers valid; "
                  f"{sum(1 for r in records if r.mismatch)} metric mismatches")
    pairs = [r for r in exact if r.greedy_J is not None and r.J is not None]
    if not pairs:
        return False, f"{valid_note}; no exact/greedy pairs (run --solver exact,greedy)"
    more_hubs = [r for r in pairs if r.greedy_hubs is not None and r.hubs > r.greedy_hubs]
    fewer_hubs = [r for r in pairs if r.greedy_hubs is not None and r.hubs < r.greedy_hubs]
    equal = [r for r in pairs if r not in more_hubs and r not in fewer_hubs]
    worse = more_hubs + [r for r in equal if r.J > r.greedy_J + 1e-6]
    if equal:
        mean_e, mean_g = statistics.mean(r.J for r in equal), statistics.mean(r.greedy_J for r in equal)
    else:
        mean_e = mean_g = 0.0
    ok = not bad and not worse and (mean_e < mean_g or not equal)
    w = (mean_g - mean_e) / mean_g if mean_g else 0.0
    return ok, (f"{valid_note}; exact worse than greedy on {len(worse)}/{len(pairs)} pairs "
                f"({len(fewer_hubs)} use fewer hubs); at equal hubs mean J exact {mean_e:.3f} vs greedy {mean_g:.3f} "
                f"(W {100 * w:.1f}%)")


def summarize(records: list[Record]) -> str:
    head = f"{'plan':>8} {'solver':<7} {'nodes':<7} {'status':<12} {'valid':<5} {'H':>2} {'J':>9} {'X':>2} {'O':>7} {'B':>3} {'t(s)':>6}  notes"
    lines = [head, "-" * len(head)]
    show = records if len(records) <= 60 else [r for r in records if r.status != "ok" or not r.valid or r.mismatch][:60]
    blocked = [r for r in records if r.blocked]
    for r in show:
        j = f"{r.J:9.3f}" if r.J is not None else f"{'-':>9}"
        o = f"{r.O:7.3f}" if r.O is not None else f"{'-':>7}"
        notes = r.error or ", ".join(([f"blocked: {r.blocked}"] if r.blocked else []) + r.rules + [f"mismatch {m}" for m in r.mismatch]
                                     + ([] if r.cpsat_agree is not False else ["CP-SAT disagrees"]))
        lines.append(f"{r.plan_id:>8} {r.solver:<7} {r.nodes:<7} {r.status:<12} {str(r.valid):<5} "
                     f"{r.hubs if r.hubs is not None else '-':>2} {j} {r.X if r.X is not None else '-':>2} {o} "
                     f"{r.B if r.B is not None else '-':>3} {r.runtime_s:6.2f}  {notes[:70]}")
    if len(show) < len(records):
        lines.append(f"... {len(records)} items; showing only the {len(show)} with problems")
    ok = [r for r in records if r.status == "ok"]
    valid = [r for r in ok if r.valid]
    js = [r.J for r in valid if r.J is not None]
    times = sorted(r.runtime_s for r in ok)
    lines.append("-" * len(head))
    tail = f"{len(valid)}/{len(records)} valid | {len(blocked)} blocked by open questions | {sum(bool(r.mismatch) for r in ok)} metric mismatches"
    if js:
        tail += f" | mean J {sum(js) / len(js):.3f}"
    if times:
        tail += f" | median runtime {times[len(times) // 2]:.2f} s"
    lines.append(tail)
    return "\n".join(lines)


def write_summary(records: list[Record], out_dir: Path, meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(r) for r in records]
    (out_dir / "summary.json").write_text(json.dumps({"meta": meta, "records": rows}, indent=1), encoding="utf-8")
    flat = [{k: ("; ".join(v) if isinstance(v, list) else v) for k, v in row.items()} for row in rows]
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(flat[0]) if flat else ["plan_id"])
        writer.writeheader()
        writer.writerows(flat)
    if flat:
        import pandas as pd

        pd.DataFrame(flat).to_parquet(out_dir / "runs.parquet", index=False)


def fixture_items():
    """(plan, nodes, answer) for the synthetic fixtures' valid answers. Needs the repo's tests/ folder."""
    from tests.fixtures import synthetic as S

    fix = Path("tests/fixtures/json")
    for plan_id in (900001, 900002):
        answer = json.loads((fix / f"answer_{plan_id}_valid.json").read_text(encoding="utf-8"))
        yield S.PLANS[plan_id](), S.NODES[plan_id], answer


def _progress(done: int, total: int, t0: float) -> None:
    """One log line about every 2% (and at the end): works in a terminal and in a redirected log."""
    step = max(1, total // 50)
    if done % step and done != total:
        return
    el = time.perf_counter() - t0
    eta = el / done * (total - done) if done else 0
    bar = "#" * (20 * done // total)
    print(f"  [{bar:<20}] {done}/{total} ({100 * done // total}%)  {el / 60:.1f} min, ~{eta / 60:.0f} min left",
          flush=True)


def _run_sequential(tasks, solvers, out_dir, overlay, cross_check) -> tuple[list[Record], str | None]:
    records: list[Record] = []
    t0 = time.perf_counter()
    for i, (pid, mode) in enumerate(tasks, 1):
        _progress(i - 1, len(tasks), t0)
        for row in _task(pid, mode, solvers, str(out_dir), overlay, cross_check):
            rec = Record(**row)
            records.append(rec)
            if rec.status == "not_built":
                return records, f"solver '{rec.solver}' not built yet: {rec.error}"
    _progress(len(tasks), len(tasks), t0)
    return records, None


def _run_parallel(tasks, solvers, out_dir, overlay, cross_check, workers) -> tuple[list[Record], str | None]:
    overrides = {k: v for k, v in config.as_dict().items() if k != "DATA_DIR"}
    order = {t: i for i, t in enumerate(tasks)}
    results: dict[tuple, list[dict]] = {}
    stopped = None
    t0 = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers, initializer=_init_worker,
            initargs=(str(Path(str(config.DATA_DIR)).resolve()), overrides)) as pool:
        futures = {pool.submit(_task, pid, mode, solvers, str(out_dir), overlay, cross_check): (pid, mode)
                   for pid, mode in tasks}
        for fut in concurrent.futures.as_completed(futures):
            key = futures[fut]
            if fut.cancelled():
                continue  # cancelled after the solver turned out to be unbuilt: not a result
            try:
                rows = fut.result()
            except Exception as exc:  # a worker crash is a per-plan failure, not a batch failure
                rows = [asdict(Record(plan_id=key[0], solver=s, nodes=key[1], status="solver_error",
                                      error=f"worker: {type(exc).__name__}: {exc}")) for s in solvers]
            results[key] = rows
            _progress(len(results), len(tasks), t0)
            if any(r["status"] == "not_built" for r in rows) and stopped is None:
                stopped = f"solver not built yet: {next(r['error'] for r in rows if r['status'] == 'not_built')}"
                for f in futures:
                    f.cancel()
    records = [Record(**row) for key in sorted(results, key=order.get) for row in results[key]]
    return records, stopped


def run(split="train", limit=None, solvers=("greedy",), node_modes=("center",), name=None, fixture=False,
        gate="valid", overlays=None, plans=None, out_root=None, workers=0, cross_check=None,
        dashboard=False, strict_blocked=False) -> tuple[list[Record], bool, str]:
    name = name or time.strftime("run_%Y%m%d_%H%M%S")
    out_dir = Path(out_root or Path(str(config.DATA_DIR)) / "out" / "runs") / name
    cross_check = gate in ("cpsat", "m3") if cross_check is None else cross_check
    stopped = None
    if fixture:
        records = [run_one(plan, nodes, "fixture", "fixture", out_dir, answer=answer, overlay=True)
                   for plan, nodes, answer in fixture_items()]
    else:
        ids = select_plan_ids(split, limit, plans)
        tasks = [(pid, mode) for pid in ids for mode in node_modes]
        draw = overlays if overlays is not None else len(tasks) * len(solvers) <= 20
        if workers and workers > 1 and len(tasks) > 1:
            records, stopped = _run_parallel(tasks, tuple(solvers), out_dir, draw, cross_check, workers)
        else:
            records, stopped = _run_sequential(tasks, tuple(solvers), out_dir, draw, cross_check)
    pair_greedy(records)
    if stopped:
        ok, why = False, stopped
    else:
        ok, why = gate_ok(records, gate, strict_blocked)
    meta = {"name": name, "split": split, "limit": limit, "solvers": list(solvers), "nodes": list(node_modes),
            "gate": gate, "gate_ok": ok, "gate_note": why, "workers": workers, "cross_check": cross_check,
            "config_hash": config.config_hash()}
    write_summary(records, out_dir, meta)
    if dashboard and records:
        from eightball.bench import report

        dash = report.build([asdict(r) for r in records], meta)
        Path("web/data").mkdir(parents=True, exist_ok=True)
        Path("web/data/dashboard.json").write_text(json.dumps(dash, indent=1), encoding="utf-8")
    return records, ok, why


def regate(run_dir: str | Path, gate: str, strict_blocked: bool = False, dashboard: bool = False
           ) -> tuple[list[Record], bool, str]:
    """Re-score a finished run from its saved answers (no solving): recompute the blocked reasons and the gate."""
    run_dir = Path(run_dir)
    data = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    records = [Record(**{k: v for k, v in row.items() if k in Record.__dataclass_fields__}) for row in data["records"]]
    for r in records:
        item = run_dir / f"{r.plan_id}_{r.solver}_{r.nodes}" / "answer.json"
        if r.status == "ok" and item.exists():
            saved = json.loads(item.read_text(encoding="utf-8"))
            r.blocked = blocked_reason(saved, r.valid)
            r.search_complete = search_complete(saved) if r.solver == "exact" else None
    pair_greedy(records)
    ok, why = gate_ok(records, gate, strict_blocked)
    meta = {**data.get("meta", {}), "gate": gate, "gate_ok": ok, "gate_note": why, "regated": True}
    write_summary(records, run_dir, meta)
    if dashboard and records:
        from eightball.bench import report

        Path("web/data").mkdir(parents=True, exist_ok=True)
        Path("web/data/dashboard.json").write_text(json.dumps(report.build([asdict(r) for r in records], meta), indent=1),
                                                  encoding="utf-8")
    return records, ok, why


def cli_main(args: argparse.Namespace) -> int:
    own = argparse.ArgumentParser(prog="eightball batch")
    own.add_argument("--gate", default="valid", choices=GATES)
    own.add_argument("--overlays", action="store_true", default=None)
    own.add_argument("--plans", help="comma list of plan ids instead of --split/--limit")
    own.add_argument("--cross-check", action="store_true", default=None,
                     help="run the CP-SAT cross-check (on by default for --gate cpsat/m3)")
    own.add_argument("--dashboard", action="store_true", help="also write web/data/dashboard.json")
    own.add_argument("--regate", help="re-score the finished run data/out/runs/<name> without solving")
    own.add_argument("--strict-blocked", action="store_true",
                     help="count plans blocked by open questions 13-15 as gate failures")
    extra = own.parse_args(getattr(args, "extra", []))
    if extra.regate:
        run_dir = Path(args.out or Path(str(config.DATA_DIR)) / "out" / "runs") / extra.regate
        records, ok, why = regate(run_dir, extra.gate, extra.strict_blocked, extra.dashboard)
        print(summarize(records))
        print(f"gate {extra.gate}: {'PASS' if ok else 'FAIL'} ({why})")
        return 0 if ok else 1
    workers = args.workers if args.workers else 0
    if workers < 0:
        workers = max(1, (os.cpu_count() or 2) - 1)
    records, ok, why = run(split=args.split, limit=args.limit, solvers=tuple(args.solver.split(",")),
                           node_modes=tuple(args.nodes.split(",")), name=args.name, fixture=args.fixture,
                           gate=extra.gate, overlays=extra.overlays, plans=extra.plans, out_root=args.out,
                           workers=workers, cross_check=extra.cross_check, dashboard=extra.dashboard,
                           strict_blocked=extra.strict_blocked)
    print(summarize(records))
    print(f"gate {extra.gate}: {'PASS' if ok else 'FAIL'} ({why})")
    if any(r.status == "not_built" for r in records):
        return 2
    return 0 if ok else 1
