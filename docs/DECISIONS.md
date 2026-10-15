# Decision log

Newest first. Contract changes need a row here (docs/BUILD_SPLIT.md 3.3).

| Date | Decision | Why |
|---|---|---|
| 2026-10-16 | Overlap endpoints are not crossings unless a segment from a ring outside that overlap meets there (metric clarification 1) | Handoff 8.1's "third segment" was ambiguous; this matches a geometric intersection where shared runs are lines, not points |
| 2026-10-16 | With PASS_OTHER_NODE_IS_CROSSING, a meeting point is excluded only if every ring there has its own node or hub at that point (metric clarification 2) | Makes "touching another loop's node counts" precise |
| 2026-10-16 | Tolerance test cases use 0.2–0.4 mm (same) and 1.5 mm (different), not 0.5/0.9 mm (metric clarification 3) | Both implementations snap to a 1 mm grid, so 0.5–1 mm is a grey zone |
| 2026-10-16 | Synthetic plans 900001/900002 (scale 1) with hand-checked answers are the shared fixtures | Lets B build the checker and viewer, and A test output shape, before the solver exists |
| 2026-10-16 | Heatmap JSON gets `schema_version: "8ball-heatmap/1"` | Same versioning rule as answer and branching JSON |
| 2026-10-16 | Unknown CLI flags pass through as `args.extra`; `cli.py` is frozen after Phase 0 | Owners add flags without touching a shared file |
| 2026-10-16 | Python 3.14 environment; geopandas dropped from requirements | All pinned packages install on 3.14; geopandas isn't used anywhere |
| 2026-10-16 | Layout changes for the split: nodes in `io/nodes.py`; fine grid in `routing/finegrid.py`; debug overlay in `viz/debug.py`; plan export from the raw plan in `viz/export.py`; per-person PROGRESS and BUILD_LOG files | Keeps every file with exactly one owner (BUILD_SPLIT 2) |
| 2026-10-16 | Room IDs come only from `io/resplan.room_parts` (types in fixed order, make_valid, parts, drop < 0.5 m², sort by rounded bounds) | Solver and checker must agree on room IDs without sharing geometry code |
| 2026-10-16 | Two-person split: Person A solver (tracks 1+2), Person B checker + showcase (tracks 3+4); Phase 0 built by Swasti, reviewed by Prasoon | BUILD_SPLIT.md |
| 2026-10-16 | Contracts v1 drafted (freeze at I0 after Prasoon's review) | Phase 0 |
| 2026-10-16 | Final action plan v8 is the build plan | Fixes the v7 review issues; core unchanged |
| 2026-10-16 | Rank loops by loop J + hub cost | A loop with a free hub spot must not lose to one whose hub needs a detour |
| 2026-10-16 | Core metrics owned by track 2, not track 1 | Track 1 is the critical path; checker metrics stay with track 3 |
| 2026-10-16 | Heatmap legend "extra J for this zone's chosen loop"; reversed headings for fields into j | Precise claim; no silent bug |
| 2026-10-16 | Metric test cases from slides where they exist, else agreed by two people | Slides may lack worked examples |
| 2026-10-16 | Two independent metric implementations with a differential test on every answer | A shared module let one bug pass both optimiser and checker |
| 2026-10-16 | Branching tree built by track 1, drawn by track 4 | Earlier versions named two owners |
| 2026-10-16 | Route per zone, cached by allowed-room set | Correct paths when "through other hubs' rooms" is OFF |
| 2026-10-16 | One search ladder: greedy → exhaustive → beam → CP-SAT → polish | Exactly one method decides each step |
| 2026-10-16 | Pairwise clash table instead of a bounding-box interaction test | Exact and cheap; bounding boxes grouped every zone |
| 2026-10-16 | Hub chosen by the same direction-aware insertion function the heatmap draws | Map and choice can never disagree |
| 2026-10-16 | CP-SAT owned by track 3, not the exhaustive-solver author | Independent cross-check |
| 2026-10-16 | Per-plan budget 30 s (config); M2 = J never above greedy, lower on average | Defined numbers |
| 2026-10-16 | Cable through another hub's rooms: default OFF | Safe reading; always feasible under the zone rule |
| 2026-10-16 | Always subtract door shapes from walls | 0.48% of plans have a buried door |
| 2026-10-16 | CP-SAT backup behind `ZoneSolver` + stitched-floor scalability benchmark | Shows the method scales; cross-checks exhaustive search |
| 2026-10-16 | Ordered milestones M0–M5 | The team schedules its own way |
| 2026-10-16 | Headline features: break-the-cable + hub heatmap | High judge wow, cheap (reuse solver costs) |
| 2026-10-16 | Cut: fire/flood mode, fuzzer, CI, why panel, Pareto, 3D twin, other extras | Off the scoring path |
| 2026-10-16 | Exhaustive search for zones and combinations; CP-SAT as backup | ≤ 10 rooms, ≤ 106 zones; true J including clashes |
| 2026-10-16 | Shift effort to cable quality | Hub count ties on most plans |
| 2026-10-16 | Checker first, strict mode, different author from the solver | One misunderstanding must not end up in both |
| 2026-10-16 | Shrink free space 3–5 cm; simplify outlines only inward | Avoid touching walls under the 1 mm tolerance |
| 2026-10-16 | Never add a hub just for an area safety margin | An extra hub loses the ranking |
| 2026-10-16 | Zone via bathroom/stair only = not connected | Safe default; 28 of 17,000 plans |
| 2026-10-16 | Build our own door/passage graph | Stored labels unreliable |
| 2026-10-16 | Hub on the wire; offset door lanes; exact + polish | Zero added length/bends; zero overlap |
| 2026-10-15 | Layered architecture | Swap algorithms or front ends freely |
| 2026-10-15 | Cable may route through un-noded rooms | Confirmed clarification |
| 2026-10-15 | 5 nodes per hub, not 20 | Detailed spec says 5 |
