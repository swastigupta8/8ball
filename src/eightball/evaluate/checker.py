"""Independent checker (Person B, step B2 / handoff S1.4, 8.2).

Reads only the raw plan, the node list and the answer JSON. Never imports eightball.geometry,
eightball.routing, eightball.optimize or eightball.core.metrics.
"""
from __future__ import annotations

import argparse


def check(plan_raw: dict, answer: dict, nodes: list[dict] | None = None) -> dict:
    """{"valid": bool, "violations": [{rule, hub_id, leg, location, message}], "metrics": {...}}"""
    raise NotImplementedError("checker: Person B, step B2")


def cli_main(args: argparse.Namespace) -> int:
    raise NotImplementedError("check CLI: Person B, step B2")
