# Build log: Person B

| date | who | what changed | notes |
|---|---|---|---|
| 2026-10-16 | Swasti (with Claude Code) | B2 checker: `evaluate/metrics_indep.py` (integer 1 mm grid; passes as ray sets for X), `evaluate/geom_indep.py` (walls minus doors, door links by contact length, passages by grown-room overlap minus walls/doors/windows), `evaluate/checker.py` + `check` CLI | Watch at I1: the "between rooms outside a door" check assumes rooms tile the interior; real plans may have unlabeled gaps (tolerance 5 cm) |
| 2026-10-16 | Swasti (with Claude Code) | Phase 0 built on `main`: skeleton, loader, config, contracts, schemas, answer I/O, PathCost protocol, room IDs, nodes, stubs, CLI, fixtures, integrate.py | Phase 0 is shared work; logged here because Swasti ran it. I0 waits on data + Prasoon's metric-case sign-off |
