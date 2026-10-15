"""CP-SAT ZoneSolver (Person B, step B6 / handoff S3.1, 6.2).

Imports only eightball.core contracts and config: never the exhaustive solver's code.
"""
from __future__ import annotations

from eightball.core.contracts import ZoneCandidate, ZoneSelection


class CpSatZoneSolver:
    name = "cpsat"

    def select(self, rooms: list[str], candidates: list[ZoneCandidate],
               min_hubs: int, time_limit_s: float) -> ZoneSelection:
        raise NotImplementedError("CP-SAT zone solver: Person B, step B6")
