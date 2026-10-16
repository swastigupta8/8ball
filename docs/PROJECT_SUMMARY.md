# 8ball: what has happened so far (one page)

**Status: V1 (2026-10-16, git tag `v1`).** Functionally complete; what remains is the final I3 run, the submission package, the demo rehearsal and UI polish. The web app now also takes an uploaded floor plan and lets you download the answer JSON and the overlay.

Team 8ball (Swasti, Prasoon, Chitra, Tanvi), HackHive x Honeywell. Task: for each ResPlan floor plan, choose how many control-panel hubs to use and where, give each room to one hub, and route one closed cable loop per hub through its rooms' nodes. Fewest hubs wins; ties go to the lowest cost J = length + 5 x crossings + overlap + 0.5 x bends.

## How the work was split
- **Person A (Prasoon's session): the solver.** Reads and cleans the plans, scores layouts, finds the hubs, zones, loops and routes.
- **Person B (Swasti's session): checker and showcase.** An independent checker, the batch runner, the CP-SAT cross-check, the web viewer, the gallery, the dashboard and the API server.
- The two sessions share one answer format, work on separate branches (`person-a`, `person-b`) and talk through `docs/INBOX.md`.

## What is built
| Area | Status |
|---|---|
| Plan cleaning, door and open-passage graph, free floor | Done, runs on all 13,053 train plans without a crash |
| Scoring (length, crossings, overlap, bends) | Done, passes all 15 agreed test cases |
| Greedy solver (safety net) | Done |
| Exact solver: every legal zone, every visiting order, hub placement, clash check between zones, polish | Done |
| Heatmap data, branching-layout data, lower bound | Done |
| Independent checker, batch runner, CP-SAT second solver | Done (Swasti) |
| Viewer, break-the-cable view, heatmap view, gallery, dashboard, API server | Done (Swasti) |
| Intermediate update form | Filled in |

## Results (full test split: 1,632 plans, two node placements, 3,264 exact answers)
- About 91% valid. The rest are plans with no legal split (a room cut out of another room, a room over 100 m², a node inside a wall). As agreed in the doubt-clearing meeting, these are set aside.
- No other invalid answers, no crashes, no scoring mismatches with the independent checker.
- Cable cost about 24% below the greedy solver at the same hub count. Never worse. Fewer hubs on about 260 answers.
- About 79% of valid answers reach the smallest hub count the area and node limits allow.
- CP-SAT agreed on 99.8% of checked answers.
- Median 3 s per plan, most under 10 s, a few large plans 20 to 40 s.
- A much wider search found only about 0.5% cheaper cable on average, up to 8% on some plans.

## What is left
1. Swasti's final integration runs (checkpoints I2 and I3) and tags.
2. Merge `person-a` and `person-b` into `main`.
3. Backups, a README for a clean machine, a demo rehearsal and the submission files.
4. Put the final numbers into the deck.
5. Frontend polish (see below).

## Assumptions and open questions
Written down in `docs/ASSUMPTIONS.md` and `docs/OPEN_QUESTIONS.md`. The organisers did not answer the questions about the scoring checker, the judging split, the time limit or the node format, so we proceed on our stated assumptions.
