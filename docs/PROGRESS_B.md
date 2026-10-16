# Progress: Person B (Checker + Showcase: tracks 3 + 4)

Steps from `docs/BUILD_SPLIT.md` section 5. Start after the I0 gate (B2, B3 can start on fixtures earlier).

| step | status | date | notes |
|---|---|---|---|
| B1 Data audit [S0.3] | done | 2026-10-16 | `python -m eightball audit` → docs/data_facts.md (all 17k in 81 s + 1,500-plan graph sample). Matches handoff §3; small gaps explained in the table |
| B2 Independent checker [S1.4] | done | 2026-10-16 | 15/15 metric cases; 2 valid fixtures pass, 6 broken caught (4 with exactly their rule); retrace rule = consecutive legs meeting at a stop in a single-door room. Not yet run on real plans (no data) |
| B3 Plan export, submission overlay, web viewer v0 [S1.6] | done | 2026-10-16 | `export-plan` (plan/answer/check bundle), `overlay` (SVG/PNG), `web/` viewer (pan/zoom, hover, layers, violations); tested in the browser on fixtures and real plan 14433. Real 10-plan check waits for A4 |
| B4 Batch runner minimal + `batch` CLI [S1.7] | done | 2026-10-16 | `batch --fixture` passes the gate (2/2); real runs call `pipeline.solve`, stop with exit 2 while A4 is a stub. Gate `valid` = all valid + no metric mismatch. I1 run waits for A4 |
| B5 Differential runner [S2.9] | done | 2026-10-16 | I2 run: 1,000 train plans x 2 node modes x exact+greedy = 4,000 answers, 0 metric mismatches, exact never worse than greedy, W 26.9%. Only plan 719 fails (kitchen door + passage) |
| B6 CP-SAT ZoneSolver [S3.1] | done | 2026-10-16 | Test split: CP-SAT matches A's additive optimum on every finished search; on 24 time-cut searches it finds a cheaper split, never a worse one |
| B7 Stitched floors [S3.3] | done | 2026-10-16 | Proxy costs: 72-room floor in 0.15 s (shown on the web). Solver costs: agrees with exhaustive on 9/9 floors that ran, up to 35 rooms; A's router caps plans at 64 rooms |
| B8 Heatmap view [S3.5] | done | 2026-10-16 | Real plans: the chosen hub is the cheapest heatmap spot on every hub of the 12 gallery plans (`heatmap_check`) |
| B9 Break-the-cable view + branching panel [S3.4, T4] | done | 2026-10-16 | Real plans with 1, 3 and 6 hubs (11028, 249, 1030) + 4 hubs (3149): worst single cut loses 0 devices on our loops vs up to 3 on branching |
| B10 Scorecard, gallery, dashboard page [S3.6] | done | 2026-10-16 | Gallery rebuilt from real solved plans (keeps only valid answers: 4 x 1 hub, 4 x 2, 4 x 3+); dashboard from the full test-split run |
| B11 API server + organiser adapter [S3.7] | done | 2026-10-16 | Live solve of unseen test plan 1 through /api/solve: valid, 2 hubs, J 51.8, 21 s (within the 30 s budget) |
| B12 Full test-split run + dashboard.json [S3.2] | doing | 2026-10-16 | 1,632 plans x 2 node modes: 0 metric mismatches; every exact answer valid except 279 items blocked by open questions 13-15 (the 25 "crashes" were the runner's cross-check on Q15 plans, fixed). Final I3 run: 2,985/2,985 exact valid, 0 mismatches; gate waits only on plan 14147 (A's zone_candidates error) |
