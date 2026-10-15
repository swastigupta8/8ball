# Progress: Person B (Checker + Showcase: tracks 3 + 4)

Steps from `docs/BUILD_SPLIT.md` section 5. Start after the I0 gate (B2, B3 can start on fixtures earlier).

| step | status | date | notes |
|---|---|---|---|
| B1 Data audit [S0.3] | done | 2026-10-16 | `python -m eightball audit` → docs/data_facts.md (all 17k in 81 s + 1,500-plan graph sample). Matches handoff §3; small gaps explained in the table |
| B2 Independent checker [S1.4] | done | 2026-10-16 | 15/15 metric cases; 2 valid fixtures pass, 6 broken caught (4 with exactly their rule); retrace rule = consecutive legs meeting at a stop in a single-door room. Not yet run on real plans (no data) |
| B3 Plan export, submission overlay, web viewer v0 [S1.6] | done | 2026-10-16 | `export-plan` (plan/answer/check bundle), `overlay` (SVG/PNG), `web/` viewer (pan/zoom, hover, layers, violations); tested in the browser on fixtures and real plan 14433. Real 10-plan check waits for A4 |
| B4 Batch runner minimal + `batch` CLI [S1.7] | todo | | |
| B5 Differential runner [S2.9] | todo | | |
| B6 CP-SAT ZoneSolver [S3.1] | todo | | |
| B7 Stitched floors [S3.3] | todo | | |
| B8 Heatmap view [S3.5] | todo | | |
| B9 Break-the-cable view + branching panel [S3.4, T4] | todo | | |
| B10 Scorecard, gallery, dashboard page [S3.6] | todo | | |
| B11 API server + organiser adapter [S3.7] | todo | | |
| B12 Full test-split run + dashboard.json [S3.2] | todo | | |
