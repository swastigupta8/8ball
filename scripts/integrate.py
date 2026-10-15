"""Checkpoint runner for the integration laptop (docs/BUILD_SPLIT.md 6).

    python scripts/integrate.py --checkpoint i0|i1|i2|i3

Runs each check in order, stops at the first failure, prints a pass/fail summary, and exits non-zero on
failure. The batch commands' own exit codes decide pass/fail: `batch` must exit 0 only when its gate
condition holds (all valid, no metric mismatches, ...), which is Person B's job in B4/B5/B12.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

CHECKS = {
    "i0": [
        ("tests", [PY, "-m", "pytest", "-q"]),
        ("cli", [PY, "-m", "eightball", "--help"]),
    ],
    "i1": [
        ("tests", [PY, "-m", "pytest", "-q"]),
        ("10 greedy plans valid", [PY, "-m", "eightball", "batch", "--split", "train", "--limit", "10",
                                   "--solver", "greedy", "--nodes", "center", "--name", "i1"]),
    ],
    "i2": [
        ("tests", [PY, "-m", "pytest", "-q"]),
        ("M2 gate: 1,000 train plans", [PY, "-m", "eightball", "batch", "--split", "train", "--limit", "1000",
                                        "--solver", "exact,greedy", "--nodes", "center,random", "--name", "i2",
                                        "--gate", "m2"]),
        ("CP-SAT cross-check: 100 test plans", [PY, "-m", "eightball", "batch", "--split", "test", "--limit", "100",
                                               "--solver", "exact", "--nodes", "center", "--name", "i2_cpsat",
                                               "--gate", "cpsat"]),
    ],
    "i3": [
        ("tests", [PY, "-m", "pytest", "-q"]),
        ("M3 gate: full test split", [PY, "-m", "eightball", "batch", "--split", "test", "--solver", "exact",
                                      "--nodes", "center,random", "--name", "i3", "--gate", "m3"]),
        ("stitched floors", [PY, "-m", "eightball", "stitch", "--name", "i3"]),
    ],
}

MANUAL = {
    "i1": "Open the overlays in data/out/runs/i1/ and the web viewer (python -m http.server, web/) for the 10 plans.",
    "i2": "Heatmap minimum equals the chosen hub on 5 plans (viewer).",
    "i3": "Break-the-cable and heatmap work in the browser on a 1-, 2- and 3+-hub plan; "
          "`python -m eightball serve` solves an unseen test plan within the time budget.",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, choices=sorted(CHECKS))
    args = parser.parse_args()
    results = []
    for label, cmd in CHECKS[args.checkpoint]:
        print(f"\n=== {label}: {' '.join(cmd[1:])}", flush=True)
        code = subprocess.call(cmd, cwd=ROOT)
        results.append((label, code))
        if code != 0:
            break
    print(f"\n=== Checkpoint {args.checkpoint} summary")
    for label, code in results:
        print(f"  {'PASS' if code == 0 else 'FAIL'}  {label}")
    skipped = len(CHECKS[args.checkpoint]) - len(results)
    if skipped:
        print(f"  (skipped {skipped} later check(s) after the failure)")
    if args.checkpoint in MANUAL:
        print(f"  MANUAL: {MANUAL[args.checkpoint]}")
    ok = all(code == 0 for _, code in results) and not skipped
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
