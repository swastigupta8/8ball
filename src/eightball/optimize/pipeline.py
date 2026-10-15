"""Solver facade (Person A, step A4; contract in docs/BUILD_SPLIT.md 3.1 item 7).

Person B calls only `solve` and `zone_candidates` from here (batch runner, API, stitched floors,
CP-SAT cross-check). Keep these signatures; change them only through a contract PR.
"""
from __future__ import annotations

import argparse

from eightball.core.contracts import SolveResult, ZoneCandidate


def solve(plan_raw: dict, nodes: list[dict], solver: str = "exact") -> SolveResult:
    """Solve one plan. solver: 'greedy' | 'exact'. Never returns without an answer (greedy first)."""
    raise NotImplementedError("solver facade: Person A, step A4")


def zone_candidates(plan_raw: dict, nodes: list[dict]) -> tuple[list[str], list[ZoneCandidate]]:
    """(eligible room ids, every legal zone with its additive cost) for the CP-SAT cross-check."""
    raise NotImplementedError("zone candidates: Person A, step A7")


def cli_main(args: argparse.Namespace) -> int:
    raise NotImplementedError("solve CLI: Person A, step A4")
