# 8ball: Two-Person Build Split

> **For Claude Code.** Read `docs/BUILD_HANDOFF.md` first (the single source of truth), then this file. The user will tell you whether you are **Person A** or **Person B**. Work only on your own steps (§4 or §5) and only touch files you own (§2). If this file and the handoff disagree, **this file wins on who does what and which files**; the handoff wins on *how* to build each step.
>
> **For the team.** Two people build in parallel on two Claude Code sessions. They meet through the GitHub repo (`swastigupta8/8ball`) and integrate on one laptop at four checkpoints (§6). The other two teammates have support roles (§8).

---

## 1. The split in one table

| | **Person A: Solver** | **Person B: Checker + Showcase** |
|---|---|---|
| Handoff tracks | T1 Geometry + routing, T2 Optimiser | T3 Checker + scale, T4 Viewer + story |
| Builds | clean geometry, door graph, free space, crude router, Hanan grid, per-zone A*, distance fields, branching tree, core metrics, greedy, zones, loops, hub function, heatmap numbers, clash table, search ladder, polish, solver facade | data audit, independent checker (own geometry + own metrics), batch runner + differential test, CP-SAT, stitched floors, plan export, submission overlay, web viewer, break-the-cable view, heatmap view, scorecard, gallery, dashboard, API server |
| Produces for the other | `answer.json`, `heatmap.json`, `branching.json`, zone candidates, the `solve()` facade | checker verdicts, mismatch reports, the CP-SAT `ZoneSolver`, every visual |
| Never touches | `evaluate/`, `bench/`, `api/`, `web/`, `viz/overlay.py`, `viz/export.py`, `optimize/cpsat.py` | `geometry/`, `routing/`, `optimize/` (except `cpsat.py`), `core/metrics.py` |

**Why this split.** The handoff requires the exhaustive solver (T2) and the checker and CP-SAT (T3) to have **different authors**, so both cross-checks stay independent. Of all the ways to pair four tracks between two people, only {T1+T2} vs {T3+T4} meets that rule without the checker author also writing the geometry the checker is meant to verify.

---

## 2. File ownership (no one edits the other person's files)

| Owner | Files |
|---|---|
| **Shared** (written together in Phase 0; afterwards changed only by a contract PR that both approve, see §3.3) | `pyproject.toml`, `requirements.txt`, `requirements.lock`, `.gitignore`, `src/eightball/config.py`, `src/eightball/cli.py`, `src/eightball/core/contracts.py`, `src/eightball/core/schema/*.json`, `src/eightball/io/*` (`resplan.py`, `answer_io.py`, `nodes.py`), `src/eightball/routing/api.py`, `tests/metric_cases.py`, `tests/test_contracts.py`, `tests/fixtures/*`, `docs/BUILD_HANDOFF.md`, `docs/BUILD_SPLIT.md`, `docs/DECISIONS.md`, `docs/OPEN_QUESTIONS.md` |
| **Person A** | `src/eightball/geometry/*`, `src/eightball/routing/*` (not `api.py`), `src/eightball/optimize/*` (not `cpsat.py`), `src/eightball/core/metrics.py`, `src/eightball/viz/debug.py`, `tests/test_metrics_core.py`, `tests/test_geometry_*.py`, `tests/test_routing_*.py`, `tests/test_optimize_*.py`, `docs/PROGRESS_A.md`, `docs/BUILD_LOG_A.md` |
| **Person B** | `src/eightball/evaluate/*`, `src/eightball/optimize/cpsat.py`, `src/eightball/bench/*`, `src/eightball/api/*`, `src/eightball/viz/overlay.py`, `src/eightball/viz/export.py`, `web/*`, `tests/test_metrics_indep.py`, `tests/test_checker*.py`, `tests/test_cpsat*.py`, `tests/test_bench*.py`, `tests/test_viz*.py`, `docs/PROGRESS_B.md`, `docs/BUILD_LOG_B.md`, `docs/data_facts.md` |

**Changes from the handoff's file layout**, so the split stays clean (record these in `DECISIONS.md` in Phase 0):
- `geometry/nodes_gen.py` moves to the shared `io/nodes.py`. Nodes are an *input*, and both people need them from day one.
- `bench/finegrid.py` becomes `routing/finegrid.py` (A). It measures A's router.
- `viz/overlay.py debug` becomes `viz/debug.py` (A). `viz/overlay.py` (submission overlay) stays with B.
- `cli export-plan` is built from the **raw** plan in `viz/export.py` (B). The viewer only draws geometry, so it doesn't need A's cleaning.
- Progress and build logs are split per person (`PROGRESS_A.md` / `PROGRESS_B.md`, `BUILD_LOG_A.md` / `BUILD_LOG_B.md`). Both people updating one file after every step would conflict constantly.

---

## 3. Phase 0: done together, on one laptop, in one Claude Code session

Both people sit together for this. Nothing is split until Phase 0 is pushed to `main`.

### 3.1 Steps
1. **S0.1** Repo skeleton (handoff §11), plus `docs/PROGRESS_A.md` and `docs/PROGRESS_B.md` listing **only that person's steps** from §4/§5 as `todo`, and `docs/BUILD_LOG_A.md` / `docs/BUILD_LOG_B.md`.
2. **S0.2** Data loader `io/resplan.py`.
3. **S0.4** Config, contracts, answer schema, `answer_io`.
4. **S0.5** Metric test cases. **Both people agree on every expected value** (write both names in a comment per case). This is the handoff's "agreed by two people".
5. **S0.6** PathCost protocol and heatmap contract.
6. **P0.7 Shared input layer (new).**
   - `io/resplan.py: room_parts(plan) -> list[tuple[room_id, type, Polygon]]`. This is the **only** place room IDs are made. The order:
     1. types in the fixed order living, bedroom, kitchen, storage, then the excluded types;
     2. `make_valid`, then `parts()`;
     3. drop parts below `MIN_ROOM_PART_M2`;
     4. sort the parts of each type by `(round(minx), round(miny))` of their bounds;
     5. number them `{type}_{k}` from 0.

     A's cleaning and B's checker both call this, so their room IDs always match. Capacity area always uses these **repaired** polygons, never A's simplified ones.
   - `io/nodes.py`: practice nodes (handoff §8.3, modes `center` and `random`), `load_nodes`, `save_nodes`, and a reader for the organisers' format once known. Output: `[{"node_id","room_id","point"}]`, with `N1…Nn` in room-ID order.
7. **P0.8 Cross-person contracts and stubs (new).** Add these to `core/contracts.py` and the schemas, and create a stub file for every entry point one person calls in the other's area. Each stub raises `NotImplementedError` with a pointer to its owner's step.
   - **Solver facade** (A implements in `optimize/pipeline.py`):
     ```python
     @dataclass
     class SolveResult:
         answer: dict              # answer JSON (§7.1 of the handoff)
         heatmaps: list[dict]      # one heatmap JSON per hub (§7.5)
         branching: dict           # branching JSON (below)
         runtime_s: float
     def solve(plan_raw: dict, nodes: list[dict], solver: str = "exact") -> SolveResult: ...
     def zone_candidates(plan_raw: dict, nodes: list[dict]) -> tuple[list[str], list["ZoneCandidate"]]: ...
     ```
   - **ZoneSolver** (A implements the exhaustive one; B implements CP-SAT in `optimize/cpsat.py`):
     ```python
     @dataclass(frozen=True)
     class ZoneCandidate:
         zone_id: str; room_ids: frozenset[str]; area_m2: float; n_nodes: int
         cost: float               # best loop J + hub cost (additive, no clashes)
     @dataclass
     class ZoneSelection:
         zone_ids: list[str]; hubs: int; cost: float; bound: float | None; optimal: bool
     class ZoneSolver(Protocol):
         def select(self, rooms: list[str], candidates: list[ZoneCandidate],
                    min_hubs: int, time_limit_s: float) -> ZoneSelection: ...
     ```
     A's ladder loads the backup solver by name from config (`ZONE_SOLVER_BACKUP = "cpsat"`) with a lazy import, so A never imports B's file at module load.
   - **Branching JSON** (A writes, B draws):
     ```json
     {"schema_version": "8ball-branching/1", "plan_id": 14433,
      "hubs": [{"hub_id": "H1", "point": [x, y], "paths": {"N1": [[x, y], [x, y]]}}]}
     ```
   - **Answer `meta` additions** (A fills, B reads):
     - `best_additive_cost`: exhaustive search's best summed zone cost, ignoring clashes. Used for the CP-SAT cross-check.
     - `min_hubs_bound`: max(⌈area/100⌉, ⌈nodes/5⌉).
     - `j_floor`: the in-model lower bound, for the certificate.
     - `metrics`: always computed by `core.metrics`. The differential test compares this against the checker's own numbers, so B never imports `core.metrics`.
   - **CLI** `cli.py` with every subcommand already registered, each dispatching by lazy import to its owner's module:
     - `solve` → `optimize.pipeline` (A)
     - `check` → `evaluate.checker` (B)
     - `export-plan` → `viz.export` (B)
     - `overlay` → `viz.overlay` (B)
     - `batch` → `bench.run_all` (B)
     - `serve` → `api.server` (B)

     After Phase 0, nobody edits `cli.py`.
   - **Fixtures** in `tests/fixtures/`:
     - 2 hand-written valid answers (a 1-hub and a 2-hub plan),
     - 6 broken answers (one per hard rule),
     - 1 heatmap JSON,
     - 1 branching JSON,
     - 1 list of zone candidates.

     B builds against these before A's solver exists; A uses them to test that its output has the right shape.
8. **Integration script** `scripts/integrate.py` (shared). It runs `pytest -q`, then `python -m eightball batch --split train --limit 10 --solver greedy --nodes center`, and prints a pass/fail summary. Later checkpoints add their own commands (§6).

### 3.2 Phase 0 gate (I0)
- `python -m pytest -q` passes (contract tests green; metric tests collected as `xfail`; stubs raise `NotImplementedError`).
- `DECISIONS.md` rows: "Contracts v1 frozen", "Two-person split (BUILD_SPLIT.md)", plus the five layout changes in §2.
- Push to `main` and tag `contracts-v1`. Create the branches `person-a` and `person-b` from that tag.

### 3.3 Changing a shared file later
Open a PR titled `contract: <change>`. It must contain:
- the schema version bump (if any),
- a `DECISIONS.md` row,
- the updated fixtures,
- updates to every consumer in the same PR.

The other person reviews it before merge. Small additions to `config.py` (a new switch with a default) follow the same rule.

---

## 4. Person A: Solver (tracks 1 + 2)

Each step uses the **Do** and **Done when** of the handoff step named in brackets, except for the differences noted here. Commit after each step on `person-a`; open a PR to `main` at each checkpoint (§6) or sooner.

| Step | What | Differences from the handoff |
|---|---|---|
| **A1** [S1.1] | Clean geometry, door graph, free space | Nodes come from `io/nodes.py`; room IDs from `io/resplan.room_parts`; debug PNGs from `viz/debug.py` |
| **A2** [S1.2] | Crude router (10 cm raster A*) | — |
| **A3** [S1.3] | Core metrics `core/metrics.py` | Written without looking at B's `metrics_indep.py` |
| **A4** [S1.5 + facade] | Greedy baseline, plus `optimize/pipeline.solve(..., solver="greedy")` returning `SolveResult` (heatmaps and branching can be empty lists/dicts for now), plus the `solve` CLI writing `answer.json` | **Done when:** 10 train plans produce answers that pass `answer_io` schema validation, and `core.metrics` scores them. The checker verdict comes at checkpoint I1 |
| → | **Checkpoint I1** (§6) | |
| **A5** [S2.1] | Hanan tracks | — |
| **A6** [S2.2] | Per-zone A*, cache, fine-grid check | Fine-grid script lives in `routing/finegrid.py`; write V% to `docs/BUILD_LOG_A.md` (B copies it into `data_facts.md`) |
| **A7** [S2.3] | Zone enumeration, plus `pipeline.zone_candidates()` | Hand B a dump of candidates for 20 test plans in `tests/fixtures/` via a contract PR |
| **A8** [S2.4] | Loop enumeration | — |
| **A9** [S2.5] | Distance fields, hub insertion function, ranking, heatmap JSON | `solve()` now fills `heatmaps` |
| **A10** [S2.6] | Clash table | — |
| **A11** [S2.7] | Search ladder, plus `ExhaustiveZoneSolver.select` (additive best), plus `meta` fields (§3.1 item 7) | Calls the backup solver through `ZoneSolver` by config name. Until B's CP-SAT lands, the stub raising `NotImplementedError` is caught and logged, and the ladder falls back to beam search |
| **A12** [S2.8] | Polish | — |
| → | **Checkpoint I2 (M2)** (§6) | |
| **A13** [S3.4, T1 part] | `routing/tree.py` branching tree; `solve()` now fills `branching` | — |
| **A14** | Fix everything B's runs report: invalids, metric mismatches, CP-SAT disagreements, slow plans. Make the live path meet `TIME_BUDGET_S` | **Done when:** B's latest test-split run shows 0 invalid and 0 mismatches |
| → | **Checkpoint I3 (M3)** (§6) | |

---

## 5. Person B: Checker + Showcase (tracks 3 + 4)

Same rules: handoff step in brackets, differences noted. Commit on `person-b`; PR to `main` at each checkpoint or sooner. B builds against the fixtures from Phase 0 until A's real output lands.

| Step | What | Differences from the handoff |
|---|---|---|
| **B1** [S0.3] | Data audit → `docs/data_facts.md` | — |
| **B2** [S1.4] | Independent checker: `geom_indep.py`, `metrics_indep.py`, `checker.py`, `check` CLI | Uses `io/resplan.room_parts` for room IDs only; everything else is its own code. Written without looking at A's `core/metrics.py` or `geometry/`. **Done when:** the handoff's tests pass, and all Phase 0 fixtures get the right verdict (2 valid, 6 caught) |
| **B3** [S1.6 + export] | `viz/export.py` (raw plan → `plan.json`), `viz/overlay.py` submission overlay, web viewer v0 | Built and tested on the fixture answers |
| **B4** [S1.7 batch] | `bench/run_all.py` minimal plus the `batch` CLI: for each plan, calls `optimize.pipeline.solve`, writes the answer, runs the checker, prints the summary table | Until A4 is merged, test it with a `--fixture` mode that replays fixture answers |
| → | **Checkpoint I1** (§6) | |
| **B5** [S2.9] | Full differential runner: multiprocessing, parquet output, both node modes, `answer.meta.metrics` vs checker metrics, W% vs greedy | **Done when:** it runs on 1,000 train plans with the greedy solver and reports 0 mismatches. The exact-solver run happens at I2 |
| **B6** [S3.1] | CP-SAT `ZoneSolver` in `optimize/cpsat.py` | First tested on the fixture candidates and on hand-built set-partition cases with known answers. The full-test-split cross-check (hub count and additive cost equal `meta.best_additive_cost`) runs after A11 is merged |
| **B7** [S3.3] | Stitched floors `bench/stitch.py` | Builds ResPlan-shaped plan dicts (in metres, so `scale = 1`) that A's `solve()` accepts. Times exhaustive search vs CP-SAT once A11 is in `main` |
| **B8** [S3.5] | Heatmap view | Built on the fixture heatmap JSON; switched to real output after A9 |
| **B9** [S3.4, T4 part] | Break-the-cable view plus branching comparison panel | Built on the fixture branching JSON; real output after A13 |
| **B10** [S3.6] | Scorecard, plan gallery, dashboard page | Gallery plans are picked with the support teammates (§8) |
| **B11** [S3.7] | API server `api/server.py` plus the organiser-input adapter | Calls `optimize.pipeline.solve`; the viewer falls back to static files |
| → | **Checkpoint I2 (M2)**: B runs the gate (§6) | |
| **B12** [S3.2] | Full test-split run, the switch-ON comparison, `web/data/dashboard.json`; report every failure to A as a GitHub issue with plan ID and violation | **Done when:** 0 invalid and 0 mismatches on the test split (after A14 fixes) |
| → | **Checkpoint I3 (M3)** (§6) | |

---

## 6. Integration on the one laptop

**One laptop is the integration and demo machine.** It holds the only `data/raw/` copy used for gate runs, and it's where the demo runs. Either person can drive it, and a support teammate can too.

### 6.1 Branches and merging
- `main` is always runnable. Each person works on `person-a` / `person-b` and merges `main` into their branch after every checkpoint (`git pull origin main`).
- PRs go into `main` only after `scripts/integrate.py` passes on the integration laptop. File ownership (§2) keeps conflicts to the shared files, and those only change through contract PRs.
- Never force-push `main`. Tag each checkpoint (`i1`, `i2`, `i3`).

### 6.2 Checkpoint procedure (the same every time)
```bash
git checkout main && git pull
git merge origin/person-a
git merge origin/person-b
pip install -r requirements.lock
python scripts/integrate.py --checkpoint <i1|i2|i3>
```
If it passes: push `main`, tag the checkpoint, and both people merge `main` back into their branches. If it fails: don't push. The failing side fixes it on their branch, and you rerun.

### 6.3 What each checkpoint checks
| Checkpoint | Needs | `integrate.py` checks |
|---|---|---|
| **I1 = M1** | A1–A4, B1–B4 | `pytest -q` green; `batch --split train --limit 10 --solver greedy` → **10/10 valid** (B's checker on A's answers); overlays and the web viewer render the 10 answers |
| **I2 = M2** | A5–A12, B5–B11 | `run_all --split train --limit 1000 --solver exact,greedy --nodes center,random` → **0 invalid, 0 metric mismatches, exact J ≤ greedy J on every plan and lower on average**; CP-SAT matches exhaustive search on 100 test plans; heatmap minimum equals the chosen hub on 5 plans |
| **I3 = M3** | A13–A14, B12 | Full test split: 0 invalid, 0 mismatches, CP-SAT matches on 100%; break-the-cable and heatmap work in the browser on a 1-, 2- and 3+-hub plan; stitched-floor chart exists; `serve` solves an unseen test plan within budget. **Cut line: nothing new starts after this** |

After I3, both people work together on the integration laptop on **S4.1** (backups and rehearsal) and **S5.1** (submission).

---

## 7. Rules both Claude Code sessions follow
1. Follow the handoff's §0 session protocol, but use **your own** `docs/PROGRESS_<A|B>.md` and `docs/BUILD_LOG_<A|B>.md`.
2. **Only edit files you own (§2).** If you need something from the other person's area, don't write it yourself. Write the need as a GitHub issue (or a note in your build log) and build against the fixture or stub meanwhile.
3. **Independence:** Person A never reads or imports `evaluate/`. Person B never reads `core/metrics.py`, `geometry/` or `optimize/` (except calling the `pipeline` facade and implementing `cpsat.py`).
4. A rule question goes to the user. Pick the strict reading meanwhile, and record it in your build log for the next contract PR.
5. Push your branch at least after every step, so the other person can see progress.

**Paste this to start each Claude Code session:**

> Person A: *"Read `docs/BUILD_HANDOFF.md` and `docs/BUILD_SPLIT.md`. You are **Person A (Solver)**. Check `docs/PROGRESS_A.md` and continue from the first step that isn't done. Work on branch `person-a` and only touch files Person A owns."*
>
> Person B: *"Read `docs/BUILD_HANDOFF.md` and `docs/BUILD_SPLIT.md`. You are **Person B (Checker + Showcase)**. Check `docs/PROGRESS_B.md` and continue from the first step that isn't done. Work on branch `person-b` and only touch files Person B owns."*
>
> Phase 0 (together): *"Read `docs/BUILD_HANDOFF.md` and `docs/BUILD_SPLIT.md`. We are doing **Phase 0** together. Start at §3.1 step 1 and stop at the I0 gate."*

---

## 8. The other two teammates (no coding session needed)
- **Third reviewer of the metric cases.** Check every expected value in `tests/metric_cases.py` before I0 (handoff §13: "reviewed by a third").
- **Eyeball checks.** Debug PNGs from A1 (doors link the right rooms, passages, front door excluded) and the 50-plan passage cross-check.
- **Organiser questions.** Send the §4 list from the handoff, and turn the answers into config changes through contract PRs.
- **Gallery and pitch.** Pick the ~12 gallery plans (B10), build the deck, and drive the I3 rehearsal on the integration laptop.

---

## 9. Timeline shape (order only; no hours)

```
Phase 0 (together) ──► I0
A: A1 → A2 → A3 → A4 ─────────────► I1 ─► A5 → … → A12 ─────────► I2 ─► A13 → A14 ──► I3 ─► S4.1, S5.1 (together)
B: B1 → B2 → B3 → B4 ─────────────► I1 ─► B5 → B6 → … → B11 ──────► I2 ─► B12 ────────► I3 ─┘
```
Person A is the critical path. If B reaches a checkpoint first, B's slack goes to B6–B11 (all buildable on fixtures), never into A's files.
