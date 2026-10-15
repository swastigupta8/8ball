"""Every rule interpretation and tunable lives here (handoff section 4).

Values are module attributes (``config.MAX_AREA_M2``). Each can be overridden by the
environment variable ``EIGHTBALL_<NAME>`` or at runtime with ``override(...)``.
Never hard-code these values elsewhere.
"""
from __future__ import annotations

import hashlib
import json
import os

_DEFAULTS: dict[str, object] = {
    "MAX_NODES_PER_HUB": 5,
    "MAX_AREA_M2": 100.0,
    "HUB_CLEARANCE_M": 0.5,
    "NODE_CLEARANCE_M": 0.5,
    "TOL_M": 0.001,
    "WALL_CLEARANCE_M": 0.04,
    "LANE_SPACING_M": 0.03,
    "MERGE_LINES_M": 0.01,
    "ALLOW_THROUGH_OTHER_ZONES": False,
    "ALLOW_THROUGH_EXCLUDED": True,
    "ZONE_VIA_EXCLUDED_ROOMS": False,
    "RETRACE_ONLY_SINGLE_DOOR": True,
    "TOUCH_IS_CROSSING": True,
    "PASS_OTHER_NODE_IS_CROSSING": True,
    "UNSURE_GAP_IS_WALL": True,
    "PASSAGE_MIN_WIDTH_M": 0.6,
    "MIN_ROOM_PART_M2": 0.5,
    "TIME_BUDGET_S": 30.0,
    "SEED": 0,
    "TOPK_LOOPS": 5,
    "MAX_SPLITS": 10_000,
    "MAX_MIXES": 10_000,
    "BEAM_WIDTH": 200,
    "HEATMAP_STEP_M": 0.25,
    "FINE_GRID_M": 0.01,
    "STRICT_CHECKER": True,
    "ZONE_SOLVER_BACKUP": "cpsat",
    "DATA_DIR": "data",
}


def _coerce(default: object, raw: str) -> object:
    if isinstance(default, bool):
        if raw.strip().lower() in ("1", "true", "yes", "on"):
            return True
        if raw.strip().lower() in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"not a boolean: {raw!r}")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


def _load() -> None:
    for name, default in _DEFAULTS.items():
        raw = os.environ.get(f"EIGHTBALL_{name}")
        globals()[name] = default if raw is None else _coerce(default, raw)


_load()


def as_dict() -> dict[str, object]:
    return {name: globals()[name] for name in _DEFAULTS}


def config_hash() -> str:
    blob = json.dumps(as_dict(), sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def override(**values: object) -> dict[str, object]:
    """Set config values at runtime; returns the previous values so callers can restore them."""
    previous = {}
    for name, value in values.items():
        if name not in _DEFAULTS:
            raise KeyError(f"unknown config value: {name}")
        previous[name] = globals()[name]
        globals()[name] = value
    return previous


def reset() -> None:
    _load()
