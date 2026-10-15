# Build log: Person B

| date | who | what changed | notes |
|---|---|---|---|
| 2026-10-16 | Swasti (with Claude Code) | B1 audit: `bench/audit.py`, `docs/data_facts.md` | Facts match §3. New: 0.93 open passages/plan (mostly kitchen–living), 38.5% of eligible rooms single-door, 37 eligible rooms in 1,500 plans with no door/passage (can't be zoned). Some plans store missing categories as None, not empty |
| 2026-10-16 | Swasti (with Claude Code) | B2 checker: `evaluate/metrics_indep.py` (integer 1 mm grid; passes as ray sets for X), `evaluate/geom_indep.py` (walls minus doors, door links by contact length, passages by grown-room overlap minus walls/doors/windows), `evaluate/checker.py` + `check` CLI | Watch at I1: the "between rooms outside a door" check assumes rooms tile the interior; real plans may have unlabeled gaps (tolerance 5 cm) |
| 2026-10-16 | Swasti (with Claude Code) | Phase 0 built on `main`: skeleton, loader, config, contracts, schemas, answer I/O, PathCost protocol, room IDs, nodes, stubs, CLI, fixtures, integrate.py | Phase 0 is shared work; logged here because Swasti ran it. I0 waits on data + Prasoon's metric-case sign-off |
