"""JSON for the web pages: browsers reject Infinity and NaN, which Python's json module writes by default.

A cost of "no solution" is infinity in the solver; in a file the viewer reads it becomes null.
"""
from __future__ import annotations

import json
import math


def finite(obj):
    """The same structure with every non-finite float replaced by None."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [finite(v) for v in obj]
    return obj


def dumps(obj, indent: int | None = 1) -> str:
    """json.dumps that always produces strict JSON (a browser's JSON.parse accepts it)."""
    return json.dumps(finite(obj), indent=indent, allow_nan=False)
