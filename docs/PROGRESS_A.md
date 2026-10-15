# Progress: Person A (Solver: tracks 1 + 2)

Steps from `docs/BUILD_SPLIT.md` section 4. Start after the I0 gate.

| step | status | date | notes |
|---|---|---|---|
| A1 Clean geometry, door graph, free space [S1.1] | done | 2026-10-16 | Real data: 12 plans build, 14433 debug PNG checked by eye (doors, kitchen passage, front door OK); full train split 13,053 plans, 0 exceptions, median 0.01 s/plan |
| A2 Crude router [S1.2] | done | 2026-10-16 | 10 cm raster A* over (cell, heading); 1,515 node pairs on 200 train plans: 0 bad (path exists, axis-aligned, inside free space, exact endpoints), ~0.1 s per pair. Pairs separated only by balconies correctly have no path |
| A3 Core metrics [S1.3] | done | 2026-10-16 | All 15 metric cases pass; fixture answers match hand-computed J; clash() equals the exact extra of a 2nd ring. Needs Prasoon sign-off on the cases (header of tests/metric_cases.py) |
| A4 Greedy + solve facade + `solve` CLI [S1.5] | done | 2026-10-16 | solve(greedy) works; 600 train plans, 0 exceptions, median 0.25 s; 388 rings (100 plans x 2 node modes): 0 self-overlaps, 154 with crossings (valid, cost 5 each); our own hard-rule checks pass on 10 plans x 2 modes + 14433. Independent checker verdict comes at I1 |
| A5 Hanan tracks [S2.1] | done | 2026-10-16 | 300 train plans: 0 failures, median build 5 ms (p95 14 ms), median 829 vertices / 1,535 edges; every node is a vertex; every in-building door has 3 lane edges (50 plans checked) |
| A6 Per-zone A*, cache, fine-grid check [S2.2] | done | 2026-10-16 | HananRouter (astar.py): cost for all 4x4 headings, cache by (allowed rooms, source, start heading); never worse than the crude router on 12 plans. Fine grid (1 cm, 50 train plans, 411 pairs): **V = 0.49%**, mean gap 17 mm, max 17 mm (target <= 2%, so no centre lines needed) |
| A7 Zones + `zone_candidates()` [S2.3] | doing | 2026-10-16 | enumerate_zones done (ESU over bit masks, equals brute force on 40 plans): full train split median 11 zones, max 63, median 0.08 ms. zone_candidates() and the 20-plan fixture dump wait for loop costs (A8/A9) |
| A8 Loops [S2.4] | done | 2026-10-16 | optimize/loops.py: all (n-1)!/2 cycles per zone, heading DP over 4x4 cost tables, lane re-routing with forbidden edges, retrace-vs-lane at dead-end rooms, true J from core.metrics. Hall test (corridor + 3 bedrooms) picks left-to-right order; real plans: all zones <=3 nodes give clean loops; median 0.31 s to enumerate every zone loop of a plan |
| A9 Fields, hub function, heatmap JSON [S2.5] | todo | | |
| A10 Clash table [S2.6] | todo | | |
| A11 Search ladder + ExhaustiveZoneSolver + meta [S2.7] | todo | | |
| A12 Polish [S2.8] | todo | | |
| A13 Branching tree [S3.4, T1] | todo | | |
| A14 Fix B's reports; meet the time budget | todo | | |





