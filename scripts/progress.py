"""Progress of a batch run that is still going, from the item folders it has written.

    python scripts/progress.py i3            # once
    python scripts/progress.py i3 --watch    # refresh every 30 s until it ends

Counts item folders written since the run's previous summary.json (a rerun reuses the folder), so the total
defaults to the previous run's item count; pass --total for a first run.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "data" / "out" / "runs"


def status(name: str, total: int | None) -> tuple[int, int, float, bool]:
    run = RUNS / name
    summary = run / "summary.json"
    since = summary.stat().st_mtime if summary.exists() else 0.0
    if total is None:
        total = len(json.loads(summary.read_text(encoding="utf-8"))["records"]) if summary.exists() else 0
    times = [max(f.stat().st_mtime for f in d.iterdir()) for d in run.iterdir() if d.is_dir() and any(d.iterdir())]
    new = [t for t in times if t > since]
    if not new and times and since >= max(times):
        return total, total, 0.0, True  # summary written after the last item: finished
    started = min(new) if new else time.time()
    return len(new), total, time.time() - started, False


def show(name: str, total: int | None) -> bool:
    done, total, el, finished = status(name, total)
    if finished:
        print(f"{name}: finished (summary.json written)")
        return True
    pct = done / total if total else 0
    eta = el / done * (total - done) if done else 0
    print(f"{name}: [{'#' * int(20 * pct):<20}] {done}/{total} ({100 * pct:.0f}%)  "
          f"{el / 60:.1f} min, ~{eta / 60:.0f} min left", flush=True)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--total", type=int)
    ap.add_argument("--watch", action="store_true")
    a = ap.parse_args()
    while not show(a.name, a.total) and a.watch:
        time.sleep(30)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
