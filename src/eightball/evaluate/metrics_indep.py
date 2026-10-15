"""Checker metrics (Person B, step B2 / handoff S1.4). Independent of core/metrics.py.

Implements the metrics interface (handoff 7.4) from the spec (handoff 8.1, tests/metric_cases.py),
never from core/metrics.py. Imports nothing from eightball.core except dataclasses and constants.
"""
from __future__ import annotations


def score(answer: dict, scale: float) -> dict:
    """{"L": m, "X": int, "O": m, "B": int, "J": float, "per_hub": {...}}"""
    raise NotImplementedError("checker metrics: Person B, step B2 (handoff S1.4)")


def clash(poly_a, poly_b, scale: float) -> tuple[int, float]:
    """(crossings, shared length in metres) between two rings' polylines."""
    raise NotImplementedError("checker metrics: Person B, step B2 (handoff S1.4)")
