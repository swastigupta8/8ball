"""Core metrics (Person A, step A3 / handoff S1.3). Used by the optimiser.

Implements the metrics interface (handoff 7.4) following handoff 8.1 and the conventions in
tests/metric_cases.py. Must not be read by Person B (independence).
"""
from __future__ import annotations


def score(answer: dict, scale: float) -> dict:
    """{"L": m, "X": int, "O": m, "B": int, "J": float, "per_hub": {...}}"""
    raise NotImplementedError("core metrics: Person A, step A3 (handoff S1.3)")


def clash(poly_a, poly_b, scale: float) -> tuple[int, float]:
    """(crossings, shared length in metres) between two rings' polylines."""
    raise NotImplementedError("core metrics: Person A, step A3 (handoff S1.3)")
