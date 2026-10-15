# Progress: Person A (Solver: tracks 1 + 2)

Steps from `docs/BUILD_SPLIT.md` section 4. Start after the I0 gate.

| step | status | date | notes |
|---|---|---|---|
| A1 Clean geometry, door graph, free space [S1.1] | done | 2026-10-16 | Real data: 12 plans build, 14433 debug PNG checked by eye (doors, kitchen passage, front door OK); full train split 13,053 plans, 0 exceptions, median 0.01 s/plan |
| A2 Crude router [S1.2] | done | 2026-10-16 | 10 cm raster A* over (cell, heading); 1,515 node pairs on 200 train plans: 0 bad (path exists, axis-aligned, inside free space, exact endpoints), ~0.1 s per pair. Pairs separated only by balconies correctly have no path |
| A3 Core metrics [S1.3] | done | 2026-10-16 | All 15 metric cases pass; fixture answers match hand-computed J; clash() equals the exact extra of a 2nd ring. Needs Prasoon sign-off on the cases (header of tests/metric_cases.py) |
| A4 Greedy + solve facade + `solve` CLI [S1.5] | todo | | |
| A5 Hanan tracks [S2.1] | todo | | |
| A6 Per-zone A*, cache, fine-grid check [S2.2] | todo | | |
| A7 Zones + `zone_candidates()` [S2.3] | todo | | |
| A8 Loops [S2.4] | todo | | |
| A9 Fields, hub function, heatmap JSON [S2.5] | todo | | |
| A10 Clash table [S2.6] | todo | | |
| A11 Search ladder + ExhaustiveZoneSolver + meta [S2.7] | todo | | |
| A12 Polish [S2.8] | todo | | |
| A13 Branching tree [S3.4, T1] | todo | | |
| A14 Fix B's reports; meet the time budget | todo | | |




