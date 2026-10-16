# HANDOFF (V1, written 2026-10-16): read this first

You are a Claude Code session picking up Team 8ball's project from a previous session on this laptop. Everything you need
to continue without asking the user to repeat themselves is here. Read sections 0 to 3 now, the rest as you need it.

---

## 0. Your first ten minutes

1. `cd C:\Users\praso\OneDrive\Desktop\HackHive\8ball` (the git repo; the folder above it only holds the data zip and two .pptx files).
2. **Do the inbox routine** (the user's standing instruction, applies before *every* task): `git pull origin main`, read
   `docs/INBOX.md`, answer anything addressed to "A", add a row there for anything Swasti's side needs to know, push. Newest entry on top.
3. Check the state: `git status -sb`, `git log --oneline -5`, `git tag` (expect `i1 i2 i3 v1`), and is the web app up:
   open http://127.0.0.1:8765/api/health (if down, start it: `.venv\Scripts\python.exe -m eightball serve --port 8765`, keep it running).
4. Skim `README.md`, `docs/PROJECT_SUMMARY.md` (one page), `docs/EDGE_CASES.md` (every odd plan and the numbers), `docs/ASSUMPTIONS.md`.
5. Then ask the user what they want next (suggested agenda in section 9).

The previous session's memory notes (auto-loaded) are in
`C:\Users\praso\.claude\projects\C--Users-praso-OneDrive-Desktop-HackHive\memory\` (`MEMORY.md` indexes them).

---

## 1. The user and how they want to work

- The user is **Prasoon** (Team 8ball: Swasti, Prasoon, Chitra, Tanvi). GitHub user **PrasoonKK**, email prasoonkkashyap@gmail.com
  (git identity is set repo-locally to that; older commits are by "Prasoon" / prasoonwork1112@gmail.com, never rewrite them).
- **Explain in very simple words, short.** They repeatedly ask "explain simply". Lead with the answer, then a few bullets. No jargon without a gloss.
- **Show a progress bar for anything long** (they asked for it explicitly). Pattern used: run the job in the background, write a tiny
  script that counts finished items and prints `[####----] n/N  x%  elapsed, about m min left`, and stream it with the Monitor tool
  (see section 8 for the pitfalls). `scripts/progress.py` (Swasti's) reads a live batch folder.
- **Be honest about limits.** Wording the user has agreed to: the hub count is a *proven minimum* (given the doors and passages we detect);
  the cable is *near-optimal* (about 0.5% from a far wider search), **not** proven optimal. About 8% of plans have no legal split and are
  *set aside*, "as discussed in the doubt-clearing meeting". Never say "optimal" for the cable.
- **Don't do more than asked.** When they said "don't do anything else" they meant it (e.g. the original test plan: make the file, validate parse-only, stop).
- **Pushing:** `git push` fails inside the Bash/PowerShell tools (no credentials). Run it through the user's terminal tab instead:
  `mcp__terminal__run_in_terminal` with `command: "git push origin main"` and `tab_id: "c1"` (open a new tab if c1 is gone), then
  `mcp__terminal__read_terminal` to see the result. The user approved each push so far; commit and push after each finished piece of work.
  Commit messages end with the Claude co-author line given by the harness.
- The user switches between two things: telling you to do something, and asking questions. Answer questions without running tools unless a fact must be verified.

---

## 2. What the project is

HackHive x Honeywell, problem "Joint Optimization of Control-Panel Placement and Closed-Loop Cable Routing". For each ResPlan floor plan
(17,000 plans, Kaggle `resplan/resplan`): choose how many **hubs** and where, assign every eligible room (living, bedroom, kitchen,
storage; one **node** each) to one hub (<= 5 nodes and <= 100 m2 per hub, rooms joined by doors or open passages), order the nodes,
and route a **closed axis-aligned cable ring** per hub through doors. Ranking: fewest hubs, then lowest
`J = L + 5X + O + 0.5B` (length m, crossings, overlap m, bends). Any broken hard rule scores zero for that plan.
Full spec and reasoning: `docs/BUILD_HANDOFF.md` (the original handoff), `docs/BUILD_SPLIT.md` (who built what).

Team story: two Claude sessions built it in parallel: **Person A** (this laptop, Prasoon: geometry, routing, optimiser, solver facade)
and **Person B** (Swasti's laptop: independent checker, batch runner, CP-SAT second solver, web viewer, API server, gallery, dashboard).
They talk only through `docs/INBOX.md`. Since 2026-10-16 this laptop's `main` holds **both** halves, so you may edit anything; just
announce changes to Swasti's files in the inbox (the `evaluate/`, `bench/`, `api/`, `web/`, `viz/overlay.py`, `viz/export.py`, `optimize/cpsat.py` area).
There may also be "side sessions" in the Claude desktop app that the user spawned; one fixed the 25 crashes Swasti reported (commit 353df02).

---

## 3. Where things stand (V1)

**V1 = functionally complete**, tagged `v1` on `main` (commit 76314fb at time of writing). Tags `i1`, `i2`, `i3` are Swasti's integration
checkpoints; **`v1.0` is reserved for the submission**. Everything is pushed to https://github.com/swastigupta8/8ball (`main`).
Branches `person-a` and `person-b` are old; `main` supersedes them.

### Results (last full test split, run `data/out/runs/test_full3`, commit 11b62a7 + later no-solver-logic changes)
1,632 test plans x 2 node placements (centre, random) x solvers exact+greedy = 6,528 results, budget 90 s, 10 workers, 24 min.
- Exact: **2,990 of 3,264 valid**; **274 set aside** (248 no legal split + 26 node off the floor); **0 other invalid, 0 crashes, 0 scoring mismatches**
  with Swasti's independent checker; 0 overlaps in any valid answer.
- Exact is never worse than greedy by (hubs, J); same-hub J **23.9% lower**; fewer hubs on 259 results; 79% of valid answers sit at the
  area/node lower bound on hubs; mean 1.72 hubs, mean J 42.2.
- Speed: median 2.4 s, p95 6.2 s, p99 10.2 s, max 24.8 s (live budget 30 s; none over).
- CP-SAT second solver agrees with the exhaustive zone search on 3,231 of 3,239 checked answers (99.8%; the 8 differences were time-budget
  effects under 14 parallel workers: re-solved alone, 5 of 5 matched exactly). Swasti's gated I2 run: 1,825/1,825 exact valid.
- `meta.j_floor` is a true lower bound (never beaten). Wide-search measurement: 30 plans, same hubs, wide search cheaper on 12 plans,
  mean 0.51%, max 8.05% (plan 35); on the user's own plan 777001 it found 63.74 vs 63.80 (0.09%).
- Fine-grid check of the track grid (1 cm raster, 411 node pairs): V = 0.49%, worst gap 17 mm.
- Tests: **283 collected, all passing** (`python -m pytest -q`, about 5 min).

### What works (user-visible)
Web app (`python -m eightball serve --port 8765`, open http://127.0.0.1:8765; API docs at `/docs`):
- **Viewer**: type a ResPlan number, **Load**, **Solve**; or **Upload plan** (button or drag-and-drop of a .json; "sample file" link next to it).
  Shows hubs, rings, score, certificate ("Proven minimum hubs (n)... Within x% of the best possible in our model"), **Break the cable** view
  with branching comparison, **hub-cost heatmap**, layers, violations.
- **Download box** after any solve: Answer (JSON), Overlay (SVG), Overlay (PNG), Everything (JSON). Every solve is also saved to
  `data/out/api/<plan id>/` (answer.json, check.json, branching.json, heatmap_H*.json); `POST /api/overlay` makes the pictures.
- **Home page** (`/`, UI v2 by Swasti 2026-10-16), **Viewer** at `/viewer.html`, **Gallery** (12 real test plans) and **How it works** (benchmark + scalability chart; replaces the old Dashboard page): read `web/data/*` which is **git-ignored**, so on any new
  laptop regenerate (commands in README): `python -m eightball.bench.gallery`; `python -m eightball.bench.report data/out/runs/<full run>`;
  `python -m eightball stitch --split train` (about 5 min, prints only at the end).
- CLI: `solve`, `check`, `overlay`, `batch`, `export-plan`, `audit`, `finegrid`, `debug`, `stitch`, `serve` (`python -m eightball --help`).

### What is NOT done
See section 9 (open items). Short: the final I3 run, the submission package (requirements unknown), the demo rehearsal + backups, the deck,
UI polish, the V2 ideas.

---

## 4. Repo map

```
8ball/
  README.md                     run commands, status
  HANDOFF_V1.md                 this file
  pyproject.toml, requirements.lock   Python 3.14 venv at .venv (use .venv\Scripts\python.exe)
  data/                         git-ignored: raw/ResPlan.pkl + split.json, out/ (runs, api, solve, debug, scale ...)
  docs/   INBOX.md (A<->B messages), PROJECT_SUMMARY.md, EDGE_CASES.md, ASSUMPTIONS.md (solver A1-20, checker C1-..),
          OPEN_QUESTIONS.md (1-16), DECISIONS.md, PROGRESS_A/B.md, BUILD_LOG_A/B.md (detailed engineering logs, newest at bottom for A),
          BUILD_HANDOFF.md + BUILD_SPLIT.md (the original specs), data_facts.md (Swasti's data audit)
  src/eightball/
    config.py                   every rule switch (env override EIGHTBALL_<NAME>, e.g. EIGHTBALL_TIME_BUDGET_S=90)
    cli.py                      python -m eightball <command>
    core/   contracts.py, metrics.py (J = L+5X+O+0.5B on a 1 mm integer grid), schema/*.json
    io/     resplan.py (loader, scale, canonical room ids), nodes.py (practice nodes), answer_io.py
    geometry/  clean.py, doorgraph.py (doors + open passages), freespace.py          -> CleanPlan
    routing/   crude.py (10 cm raster A*, used by greedy), hanan.py (track grid), astar.py (HananRouter: cost, route(forbid, contacts),
               distance fields), fields.py, tree.py (branching tree), finegrid.py, api.py (PathCost protocol)
    optimize/  zones.py (ESU zone enumeration), loops.py (cycles, heading DP, lanes), hub.py (hub insertion fn, heatmap numbers),
               clash.py (pairwise clash table), ladder.py (search ladder + ExhaustiveZoneSolver), polish.py, greedy.py,
               pipeline.py (solve() facade, zone_candidates()), cpsat.py (Swasti's CP-SAT ZoneSolver)
    evaluate/  checker.py, geom_indep.py, metrics_indep.py   (Swasti's independent checker; do not import core.metrics there)
    bench/     run_all.py (batch), report.py (dashboard.json), gallery.py, stitch.py, audit.py
    api/server.py               FastAPI: /api/health, /plans, /plan/{id}, /solve, /overlay, /validate; serves web/ at "/"
    viz/       overlay.py (submission picture), export.py, debug.py
  web/          index.html + home.js (landing), viewer.html + app.js (viewer), style.css, gallery.*, how-it-works.* (was dashboard.*), thumb.js, samples/ (2 sample uploads), data/ (git-ignored outputs)
  tests/        283 tests; tests/fixtures/ (synthetic plans 900001/900002 and answers)
  scripts/      integrate.py (checkpoints i1/i2/i3, --workers N), progress.py, check_upload_result.py (see section 6)
  sample_input/ sample uploads + make_sample.py + run_sample.py + README.txt   (result_*.json here are untracked test outputs)
  original_test_plan/  floor_plan_input.json: a 14x10 m flat made from scratch (plan id 777001, 6 nodes, 2 hubs needed) + README.txt
```

Outside the repo, in `C:\Users\praso\OneDrive\Desktop\HackHive\`: `archive.zip` (the Kaggle data; `ResPlan.pkl` and `split.json` are already unpacked into `8ball\data\raw\`),
and the intermediate-update form `Cable Ring Challenge - Intermediate Update - 8ball FINAL.pptx` (see section 7). The older file without
"FINAL" is a superseded draft (it was open in PowerPoint and could not be overwritten).

### Solver in one paragraph
`pipeline.solve(plan_raw, nodes, "exact")`: clean the plan; greedy first (always an answer); then `ladder.run_ladder`: enumerate zones,
price only the zones that appear in some fewest-hub split (loops = every cycle through a zone's nodes, headings by DP, legs routed on the
Hanan track grid with lanes and a 5 J penalty for touching earlier cable; hub on the cable if possible, else cheapest insertion by
direction-aware distance fields), try every fewest-hub split, choose loops per zone with clash costs between zones (beam search if too many),
re-score the best mixes exactly, polish (rip-up and reroute), return the better of exact and greedy by (hubs, J). Timeouts return the best so far.
Answer JSON schema `8ball-answer/1` (`core/schema`), with `meta` fields `best_additive_cost`, `min_hubs_bound`, `j_floor`, `warnings`, `flags`.

---

## 5. Decisions and assumptions you must not silently change

Full lists: `docs/ASSUMPTIONS.md`, `docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md`. The ones that matter most:
- Organisers gave **no answers to open questions 1-3** (their checker/sample JSON, the judging split, the live time limit and node format). We run on
  written assumptions: live budget 30 s (`TIME_BUDGET_S`), batch runs 90 s, plan upload in our own format (WKT per layer + optional nodes).
  The adapter for their real format is `api/server.py: plan_from_payload` and `io/nodes.py: read_organiser_nodes` (still a stub): update when known.
- **Plans with no legal split (~8%)** (a room cut out of another room's polygon, a room over 100 m2, an isolated room, a node inside a wall) are
  **set aside** by user decision ("ignored as mentioned in the doubt-clearing meeting"). Do not invent assumptions to rescue them; if one is ever
  added it must be realistic and listed in ASSUMPTIONS.md first. Swasti's reports count them as "blocked by open questions 13-15".
- **Retrace is OFF** (`loops.ALLOW_RETRACE = False`, assumption 8): every ring leg keeps its own line (parallel runs 3 cm apart), because the
  checker's idea of a "single-door room" can differ from ours and a rejected overlap zeroes a plan. Cost: about 0.3% more J. The retrace code
  (dead-end rooms, `retrace_region`) is still there if it should ever be re-enabled.
- Cable never enters another hub's room; may cross rooms without a node; stays inside the inner boundary, 4 cm off walls; hub >= 0.5 m from
  walls/room boundary, never on a node; touching cable counts as a crossing; zones connect through doors/passages only (not via a bathroom).
- **Door links** (`doorgraph.link_door`): a room counts for a door if it covers >= 5% of the door buffer OR touches it along >= 25% of the longest contact.
- Track grid: node lines never merged except within 0.1 mm; no two lines within 2 mm; edges may sit up to 5 mm outside the shrunk floor (still 3.5 cm from walls);
  max 63 rooms per plan (int64 mask; `solve()` falls back to greedy with "exact solver failed" in `meta.warnings`).
- `web/data/` and `data/` are git-ignored on purpose.

---

## 6. Useful recipes

**Check an uploaded plan's answer (valid? right numbers? all splits? wider search? CP-SAT?):**
```
.venv\Scripts\python.exe scripts\check_upload_result.py original_test_plan\floor_plan_input.json
```
(second argument = downloaded answer file; default `data\out\api\<id>\answer.json`; `--no-wide` skips the slow wide search). This is
exactly how the user's plan 777001 was verified: valid, 2 hubs (the only legal 2-hub split), CP-SAT agrees, wide search 0.09% cheaper.

**Run something for many plans with Swasti's runner** (writes `data/out/runs/<name>/<plan>_<solver>_<nodes>/{answer,check}.json`, `summary.json`):
```
.venv\Scripts\python.exe -m eightball batch --split test --solver exact,greedy --nodes center,random --workers 10 --name myrun
```
set `EIGHTBALL_TIME_BUDGET_S=90` first (PowerShell: `$env:EIGHTBALL_TIME_BUDGET_S=90`); flags `--plans 1,2,3`, `--limit N`, `--gate cpsat` (CP-SAT cross-check). Each result row has
`valid, hubs, J, rules, blocked, runtime_s, min_hubs_bound, best_additive_cost, j_floor, greedy_J, cpsat_agree`. Full test split: about 25 min; with `--gate cpsat`: about 36 min.
**Do not run a batch while Swasti's final I3 run is going on a shared machine** (it measures timings).

**Final check run before submission** (about 1.5 h): `python scripts/integrate.py --checkpoint i3 --workers 6` with the 90 s budget. It is in Swasti's inbox row.

**Solve one plan from the command line:** `python -m eightball solve --plan-id 14433 --solver exact` (writes `data/out/solve/14433/`).
**Overlay picture:** `python -m eightball overlay --plan-id 14433 --answer <answer.json> --format png --out x.png`.
**Make a sample upload from a real plan:** `python sample_input/make_sample.py <plan id>`.

Good demo plans: 14433 (the handoff's demo plan, 2 hubs), 769 and 224 (2 hubs, 1 to 3 s), 14147 and 719 (formerly problem plans, now fine).
Plan 47, 70, 144, 3236 are examples of set-aside plans.

---

## 7. The intermediate update form (already filled)

`..\Cable Ring Challenge - Intermediate Update - 8ball FINAL.pptx` (3 slides: approach + assumptions; progress with two overlay screenshots, plan 14433
best result and plan 47 hard case; remaining issues + improvements + next steps). Built from the template by editing only grey text and the two image
slots (script was in the old scratchpad, now gone: edit the XML directly if changes are needed). Numbers in it came from the 150-plan run
(279/300 valid, 27% lower J than greedy at equal hubs, fewer hubs on 11%, median 3 s), **before** the final full run: they are slightly out of date vs section 3
(2,990/3,264 valid, 23.9%). Open points the user should confirm: (a) it mentions a "3D showcase page" (from screenshots the user sent of a page titled
"8BALL Engineering the invisible, LIVE 3D ENVIRONMENT"; I never saw that page in the repo, so confirm it exists); (b) the line "as discussed in the doubt-clearing meeting".
PowerPoint automation and LibreOffice are **not** usable here (PowerPoint COM returns 0x80048240; no LibreOffice), so layout was checked by font-metric calculation, never by eye.

---

## 8. Tooling gotchas learned the hard way

- **Shell quoting:** long inline `python -c` or heredoc scripts with quotes break in both Bash and PowerShell tools. Write the script to a file
  (scratchpad or `scripts/`) with the Write tool and run it. The Bash tool is Git Bash (use `/c/Users/...` paths); PowerShell is 5.1 (no `&&`).
- `sleep` as a foreground wait is blocked; for waits use `Monitor` (loop that prints) or `run_in_background`. A Monitor that checks "is any python
  running" never ends because the web server is python: check a specific PID or an output file instead. Monitors expire after 30 min: re-arm.
- Node is not installed (no `node --check` for web JS); test JS in the Browser pane with `mcp__Claude_Browser__javascript_tool`.
  Screenshots of the pane can time out when it is in the background; navigate again, or use `get_page_text` / JS state. Set a wide viewport with
  `resize_window` to see the whole header, then reset with preset `desktop`.
- The web server does **not** auto-reload Python changes: restart it (find processes whose command line contains `eightball serve`, stop, start again hidden
  with `Start-Process ... -WindowStyle Hidden`). Static files (web/*) are served live; just reload the page.
- **Never edit source while on a throwaway trial branch** and never `git branch -D` it with unmerged commits (three commits were lost once, recovered from the reflog).
  For trial integrations prefer doing nothing exotic: `main` already contains everything.
- `git checkout` of a branch that is behind can briefly show stale files; wait for the command to finish.
- Windows line endings produce "CRLF will be replaced" warnings: harmless.
- `docs/INBOX.md` has two tables: "Who must act now" (top) and the log (newest row first, right after the `|---|---|---|---|` header line).
- The `data/out/runs/*` folders are large and untracked; `test_full3` is the reference full run. `data/out/api/` holds saved web solves.

---

## 9. Open items and a suggested next phase

1. **Find the organisers' submission requirements** (which plans, file format, deadline, how to hand in). Nothing is known; check the problem slides/PDF/event page,
   else ask the user to ask. Everything in the submission package depends on it.
2. **Submission package** (per `docs/BUILD_HANDOFF.md` S5.1): answer JSON (convert to their format if given) + overlay SVG/PNG for every required plan
   (batch-generate from `answer.json` + `overlay` command), repo tag `v1.0`, README that works from a clean machine, the deck.
3. **Deck**: problem, approach, claims with real numbers (section 3), demo, break-the-cable resilience story. Source numbers: `docs/EDGE_CASES.md`, `docs/PROJECT_SUMMARY.md`.
   Use the honest wording from section 1.
4. **Demo rehearsal + backups** (handoff S4.1): on the demo laptop run twice in a row without a hitch: cold start, gallery, solve an unseen plan, score card,
   break a cable beside the branching layout, heatmap, How it works page, scalability chart. Backups: screen recording, ~10 pre-solved plans (1, 2, 3+ hubs).
   Remember to regenerate the git-ignored `web/data` on that laptop. Keep the server running; budget 30 s live.
5. **Final I3 run** (Swasti's row, about 1.5 h) on the final code; then possibly refresh the dashboard from it.
6. **Refresh the intermediate-update form numbers** if it has not been submitted yet (section 7), and verify the two points to confirm.
7. Optional polish / V2 ideas (not built): UI polish; real prices (cost per metre, labour per bend, hub price) with a cheapest-to-most-robust slider; photo/PDF to
   vector upload; multi-floor buildings with risers (stitched floors already show scaling); 3D twin linked to live output; run the slow wide search ahead of time for demo plans
   (about 0.5% cheaper cable on average, minutes per plan); the retrace option if the organisers confirm their single-door definition.
8. **Known limits to state, not fix** (unless the user asks): ~8% plans set aside; cable near- but not provably optimal; organiser checker/format unknown;
   Q16 (a kitchen with a door and an open passage counts as two openings: handled); max 63 rooms for the exact solver.

Swasti's laptop: she is doing the final I3 run and the checker-side docs; read `docs/INBOX.md` for her latest. If `git pull` shows her new commits, merge happens
automatically on `main` (she pushes to `main` too).

---

## 10. If something looks wrong

- Tests failing after a pull: `python -m pytest -q -x` and read the first failure; Swasti's test files are in `tests/test_checker*.py`, `test_bench*.py`, `test_api.py`, `test_viz.py`, `test_cpsat.py`.
- How it works / gallery empty: the git-ignored data is missing: regenerate (section 3).
- A plan returns the greedy answer with warnings: read `answer["meta"]["warnings"]` (e.g. "no split covers every room" = a set-aside plan; "exact solver failed" = too many rooms or a bug: reproduce with `scripts/check_upload_result.py`).
- Slow solves under load: set `EIGHTBALL_TIME_BUDGET_S=90` or run fewer workers.
- Mismatch between our scoring and the checker: that never happened on 6,528 results; if it does, compare `core/metrics.py` and `evaluate/metrics_indep.py` on the 15 cases in `tests/metric_cases.py` first.
