# Progress: Person B (Checker + Showcase: tracks 3 + 4)

Steps from `docs/BUILD_SPLIT.md` section 5. Start after the I0 gate (B2, B3 can start on fixtures earlier).

| step | status | date | notes |
|---|---|---|---|
| B1 Data audit [S0.3] | done | 2026-10-16 | `python -m eightball audit` → docs/data_facts.md (all 17k in 81 s + 1,500-plan graph sample). Matches handoff §3; small gaps explained in the table |
| B2 Independent checker [S1.4] | done | 2026-10-16 | 15/15 metric cases; 2 valid fixtures pass, 6 broken caught (4 with exactly their rule); retrace rule = consecutive legs meeting at a stop in a single-door room. Not yet run on real plans (no data) |
| B3 Plan export, submission overlay, web viewer v0 [S1.6] | done | 2026-10-16 | `export-plan` (plan/answer/check bundle), `overlay` (SVG/PNG), `web/` viewer (pan/zoom, hover, layers, violations); tested in the browser on fixtures and real plan 14433. Real 10-plan check waits for A4 |
| B4 Batch runner minimal + `batch` CLI [S1.7] | done | 2026-10-16 | `batch --fixture` passes the gate (2/2); real runs call `pipeline.solve`, stop with exit 2 while A4 is a stub. Gate `valid` = all valid + no metric mismatch. I1 run waits for A4 |
| B5 Differential runner [S2.9] | doing | 2026-10-16 | Parallel workers (one task per plan+nodes), parquet, gates valid/m2/cpsat/m3, CP-SAT cross-check per exact item, --dashboard. Tested on fixtures + a 4-plan parallel run. The 1,000-plan M2 run waits for A4–A12 |
| B6 CP-SAT ZoneSolver [S3.1] | doing | 2026-10-16 | Solver built: fixture optimum, hand-built cases, 25 random instances = brute force, 80-room instance optimal. Full test-split cross-check vs `meta.best_additive_cost` waits for A7/A11 |
| B7 Stitched floors [S3.3] | doing | 2026-10-16 | Builder + benchmark done: CP-SAT solves a 72-room floor in 0.16 s (optimal); exhaustive search stops at its 30 s budget from 37 rooms. Uses proxy zone costs; rerun with `--candidates solver` after A7/A11 |
| B8 Heatmap view [S3.5] | doing | 2026-10-16 | Layer + legend (J units) + cheapest-spot badge, browser-tested on the fixture; `viz.export.heatmap_check` for batch use. Done-when (5 real plans) waits for A9 |
| B9 Break-the-cable view + branching panel [S3.4, T4] | doing | 2026-10-16 | Built and browser-tested on fixtures: one cut = loop loses 0 vs branching 3; two cuts lose only the devices between; counters + worst single cut. Done-when needs 3 real plans (1, 2, 3+ hubs) after A13 |
| B10 Scorecard, gallery, dashboard page [S3.6] | done | 2026-10-16 | `gallery.html` (12 real test plans, `python -m eightball.bench.gallery`), `dashboard.html` (tiles, J histogram, failures, scalability chart + table), viewer nav + certificate lines. All static; re-run gallery/report once the solver exists |
| B11 API server + organiser adapter [S3.7] | doing | 2026-10-16 | `serve`: /api/health, /api/plans, /api/plan/{id}, /api/solve (501 until A4), /api/validate; viewer served at / with plan-id box + Solve. Adapter: plan as WKT/GeoJSON per key + area. Done-when (solve an unseen test plan within budget) waits for A4 |
| B12 Full test-split run + dashboard.json [S3.2] | todo | | |
