# Build log: Person A

| date | who | what changed | notes |
|---|---|---|---|
| 2026-10-16 | Person A | A1: geometry/clean.py, doorgraph.py, freespace.py, viz/debug.py, tests/test_geometry_clean.py | CleanPlan geometry stays in drawing units (same frame as nodes and answer JSON); scale converts to metres. Passages use idea A; idea C flood-fill cross-check behind build_clean_plan(flood_check=True). Outdoor types (land, garden, pool, parking) get no links. Wall depth falls back to door thickness if the stored value is implausible (flag wall_depth_fallback); recheck on real data. Contract PR note: 'Contracts v1' tag contracts-v1 was not visible on origin when I pulled; branch person-a made from main dde29f1 |
