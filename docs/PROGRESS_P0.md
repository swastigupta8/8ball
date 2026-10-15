# Progress: Phase 0 (shared)

| step | status | date | notes |
|---|---|---|---|
| S0.1 Repo skeleton and environment | done | 2026-10-16 | Python 3.14.5 venv; all pinned deps install (OR-Tools 9.15, Shapely 2.1.2); geopandas dropped (unused) |
| S0.2 Data and loader | done | 2026-10-16 | 17,000 plans load (15 s), splits 13,053/1,632/1,632/683, plan 14433 scale ≈ 19.5; all 6 data tests green |
| S0.4 Config, contracts, schema, answer_io | done | 2026-10-16 | 10 contract tests green |
| S0.5 Metric test cases | doing | 2026-10-16 | 15 cases written by Swasti; **waiting for Prasoon's sign-off** and a third reviewer (see header of `tests/metric_cases.py`) |
| S0.6 PathCost protocol + heatmap contract | done | 2026-10-16 | `routing/api.py`; heatmap/branching writers in `io/answer_io.py` |
| P0.7 Shared input layer (room IDs, nodes) | done | 2026-10-16 | `resplan.room_parts`, `io/nodes.py`; synthetic plans confirm canonical IDs |
| P0.8 Cross-person contracts, stubs, CLI, fixtures | done | 2026-10-16 | facade, ZoneSolver, branching JSON, meta fields, CLI, 2 synthetic plans + 8 answers + heatmap + branching + zone candidates |
| P0 integrate.py | done | 2026-10-16 | `python scripts/integrate.py --checkpoint i0` |
| **I0 gate** | blocked | | Needs: Prasoon's metric-case sign-off (S0.5), then tag `contracts-v1` and create `person-a` / `person-b` |
