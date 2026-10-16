"""Dashboard data from a batch run (Person B, B10 now; B12 extends it).

    python -m eightball.bench.report data/out/runs/<name> [--out web/data/dashboard.json]

Reads a run's summary.json (bench/run_all.py) and writes the dashboard JSON ("8ball-dashboard/1"):
validity, metric mismatches, share at the proven-minimum hub count, the J distribution, W% vs greedy,
runtime percentiles and failure categories. Missing inputs give null fields, never errors.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from pathlib import Path

from eightball.bench import webjson

SCHEMA = "8ball-dashboard/1"


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    vs = sorted(values)
    return vs[min(len(vs) - 1, int(q * len(vs)))]


def histogram(values: list[float], bins: int = 12) -> list[list[float]]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [[lo, hi, len(values)]]
    width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        counts[min(bins - 1, int((v - lo) / width))] += 1
    return [[round(lo + i * width, 3), round(lo + (i + 1) * width, 3), c] for i, c in enumerate(counts)]


def build(records: list[dict], meta: dict | None = None) -> dict:
    meta = meta or {}
    solvers = sorted({r["solver"] for r in records})
    main = "exact" if "exact" in solvers else (solvers[0] if solvers else None)
    rows = [r for r in records if r["solver"] == main]
    blocked = [r for r in rows if r.get("blocked")]
    ok = [r for r in rows if r["status"] == "ok"]
    valid = [r for r in ok if r["valid"]]
    js = [r["J"] for r in valid if r.get("J") is not None]
    bounds = [r for r in valid if r.get("min_hubs_bound") is not None and r.get("hubs") is not None]
    greedy = {(r["plan_id"], r["nodes"]): r for r in records if r["solver"] == "greedy" and r.get("valid")}
    savings = []
    if main != "greedy":
        for r in valid:
            g = greedy.get((r["plan_id"], r["nodes"]))
            if g and g.get("J") and r.get("J") is not None and g.get("hubs") == r.get("hubs"):
                savings.append((g["J"] - r["J"]) / g["J"])
    # Same-case comparison with the greedy solver: only cases where both answers are valid.
    paired = {"n": 0, "exact_J_mean": None, "greedy_J_mean": None, "fewer_hubs": 0, "cheaper_same_hubs": 0, "tie": 0, "worse": 0}
    if main != "greedy":
        pe, pg = [], []
        for r in valid:
            g = greedy.get((r["plan_id"], r["nodes"]))
            if not g or g.get("J") is None or r.get("J") is None or r.get("hubs") is None or g.get("hubs") is None:
                continue
            pe.append(r["J"])
            pg.append(g["J"])
            if r["hubs"] < g["hubs"]:
                paired["fewer_hubs"] += 1
            elif r["hubs"] > g["hubs"]:
                paired["worse"] += 1
            elif r["J"] < g["J"] - 1e-6:
                paired["cheaper_same_hubs"] += 1
            elif r["J"] > g["J"] + 1e-6:
                paired["worse"] += 1
            else:
                paired["tie"] += 1
        paired.update(n=len(pe), exact_J_mean=statistics.mean(pe) if pe else None, greedy_J_mean=statistics.mean(pg) if pg else None)
    failures = Counter()
    for r in rows:
        if r.get("blocked"):
            failures[f"blocked: {r['blocked']}"] += 1
            continue
        if r["status"] != "ok":
            failures[r["status"]] += 1
        for rule in r.get("rules", []):
            failures[rule] += 1
        if r.get("mismatch"):
            failures["metric mismatch"] += 1
    runtimes = [r["runtime_s"] for r in ok]
    return {
        "schema_version": SCHEMA,
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "run": meta.get("name"),
        "split": meta.get("split"),
        "solver": main,
        "n": len(rows),
        "blocked": len(blocked),
        "valid": len(valid),
        "valid_share": len(valid) / len(rows) if rows else None,
        "mismatches": sum(1 for r in ok if r.get("mismatch")),
        "min_hub_share": (sum(1 for r in bounds if r["hubs"] == r["min_hubs_bound"]) / len(bounds)) if bounds else None,
        "J": {"mean": statistics.mean(js) if js else None, "p50": _pct(js, 0.5), "p95": _pct(js, 0.95),
              "hist": histogram(js)},
        "W": statistics.mean(savings) if savings else None,
        "W_pairs": len(savings),
        "runtime_s": {"p50": _pct(runtimes, 0.5), "p95": _pct(runtimes, 0.95), "max": max(runtimes) if runtimes else None,
                      "mean": statistics.mean(runtimes) if runtimes else None,
                      "share_under_5s": (sum(1 for t in runtimes if t < 5.0) / len(runtimes)) if runtimes else None},
        "paired": paired,
        "hubs": {"mean": statistics.mean(r["hubs"] for r in valid if r.get("hubs") is not None) if valid else None,
                 "max": max((r["hubs"] for r in valid if r.get("hubs") is not None), default=None)},
        "failures": dict(failures.most_common()),
    }


def from_run(run_dir: str | Path) -> dict:
    data = json.loads((Path(run_dir) / "summary.json").read_text(encoding="utf-8"))
    return build(data["records"], data.get("meta"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eightball.bench.report")
    parser.add_argument("run_dir")
    parser.add_argument("--out", default="web/data/dashboard.json")
    args = parser.parse_args(argv)
    dash = from_run(args.run_dir)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(webjson.dumps(dash), encoding="utf-8")
    print(f"wrote {args.out}: {dash['valid']}/{dash['n']} valid, {dash['mismatches']} mismatches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
