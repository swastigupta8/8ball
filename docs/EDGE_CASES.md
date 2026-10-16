# Edge cases (review after integration)

Every odd plan we hit while integrating, in one place. We stopped rerunning I2/I3 after each fix (each full
run is ~1.5 h); the numbers below come from the last full runs. **I2 passed (tag i2: 1,825/1,825 exact valid, 0 mismatches, W 26.7%). Before submission: one final I3 run on
the tagged code** (`scripts/integrate.py --checkpoint i3 --workers 6`, `EIGHTBALL_TIME_BUDGET_S=90`).

Status: **fixed** = fixed in code, last checked as noted · **set aside** = left out by team decision ·
**limit** = known limit, doesn't affect ResPlan answers.

## Plans that failed a gate

| plan(s) | what happened | owner | status |
|---|---|---|---|
| 719 | Kitchen with a door **and** an open passage. The solver treated it as a dead end and retraced; the checker counts two openings (Q16, C5) | A | fixed in e4064a0: retrace off (assumption 8). Verified: I2 passed (tag i2) |
| 14147 (center nodes) | `zone_candidates` raised ValueError "point is not on the polyline", so CP-SAT couldn't be checked (the solve itself was valid) | A | fixed in e4064a0 (split_leg tolerance). Not rerun in a gated I3 since |
| 684 | Square door touching bedroom, living room and bathroom_1; the checker linked only two of them (zone rule failed) | B | fixed in 56425e6 (C2: an irregular door joins every room it touches). Verified: I2 passed (tag i2) |
| 6017, 9740, 13025, 14932 | Ring overlaps of 0.03-0.47 m at a node: solver and checker disagreed on whether the room was single-door | A | fixed in 11b62a7: retrace off; A's third full run had 0 overlaps |
| 425, 1140 | T-junction doors linked the wrong rooms | B | fixed: the checker probes the floor beyond each door face (C2) |
| 108 | Perpendicular cable crossings counted as retrace overlap | B | fixed in f9fd353: only collinear length counts (C6) |
| 24 plans with a node off the floor (240, 5207, 14147, ...) | The runner's CP-SAT cross-check crashed and the item was logged as a solver crash | B | fixed in ad857b9; rerun of the 24 plans: 0 crashes |

## Plans set aside (open questions 13-15)

| what | how many (A's third full run, 11b62a7) | status |
|---|---|---|
| No legal split into zones (a room > 100 m², an isolated room, too many nodes) | 248 of 3,264 exact items | set aside: reported as blocked, not counted in gates (`--strict-blocked` counts them) |
| A node not on the free floor (inside a wall or off the plan) | 26 of 3,264 | set aside, same way |
| Eligible rooms with no door or passage (37 in a 1,500-plan sample, data audit) | part of the 248 | set aside |

## Limits

| what | effect | status |
|---|---|---|
| Time budget under load: 705 exact searches were cut at 30 s with 8 workers | CP-SAT found a cheaper split on 17 of them, never a worse one | limit: batch runs use 90 s; live demo keeps 30 s |
| Router room mask is int64: at most 64 rooms per plan | the two 16-flat stitched floors drop out | limit: no ResPlan flat comes close |
| Stitched floor 800000: node off the floor | dropped from the solver-cost stitch run | limit (same as Q15) |
| 4 stitched floors (10-57 rooms) have no legal split under the solver's zones | not in the scale chart; the web page keeps the proxy run | limit |

## Last known numbers (for the deck)

From A's third full test-split run (11b62a7, budget 90 s, 6,528 items): exact 2,990 of 3,264 valid,
274 set aside, **0 other invalid, 0 crashes, 0 scoring mismatches**; same-hub J 23.9% lower than greedy;
fewer hubs on 259 items; 79% at the proven hub minimum; runtime median 2.4 s, max 24.8 s.
B's I3 run (ad857b9): CP-SAT matches 2,279 of 2,279 checkable finished searches.
