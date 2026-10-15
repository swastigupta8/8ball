# 8ball — HackHive × Honeywell: Build Handoff

> **For Claude Code.** This file is the single source of truth for the project. Read it fully before doing anything. Then follow **§0 Session protocol** and start at the first step in **§11 Build plan** whose status in `docs/PROGRESS.md` isn't `done`.
>
> **For the team.** This handoff covers everything decided during ideation (project log v8, 16 Oct 2026) plus the concrete specs needed to build it. Nothing has been built yet.

---

## 0. Session protocol (how Claude Code works on this repo)

1. **One step at a time.** Steps are in §11 and numbered `S0.1`, `S0.2`, …. Do exactly one step per run unless the user says otherwise. Each step lists its **Goal**, **Do**, **Files** and **Done when**. "Done when" is a set of commands that must pass.
2. **Progress file.** Keep `docs/PROGRESS.md` as a table: `step | status (todo/doing/done/blocked) | date | notes`.
   - Create it in S0.1 with every step listed as `todo`.
   - Update it at the end of every step.
   - At the start of a session, read it and announce the next step.
3. **Verify before claiming done.** Run the step's "Done when" commands and show their output. A step with failing checks is not done.
4. **Commit after each step:** `git commit -m "S<id>: <short summary>"`. Commit small and often.
5. **Contracts are frozen** (§7) once S0.4–S0.6 are done. Changing one needs:
   - a version bump in the schema string,
   - a row in `docs/DECISIONS.md`,
   - updates to every consumer in the same commit.
6. **Assumptions are switches** (§4, `config.py`). Never hard-code a rule interpretation. Read it from config.
7. **When blocked or unsure, ask the user.** Don't guess at a rule. If a step is ambiguous, pick the **safe/strict** reading, note it in `docs/DECISIONS.md`, and tell the user.
8. **Logs.**
   - Append decisions to `docs/DECISIONS.md` (newest first: date, decision, why).
   - Append build events to `docs/BUILD_LOG.md` (date, who, what changed, notes).
9. **Data stays out of git.** `data/` is git-ignored.
10. **Speak plainly to the user.** They prefer simple explanations and short summaries.

---

## 1. The hackathon and the task

- **Event:** HackHive × Honeywell (problem slides titled "UR Hackathon 2026H2"). Team **8ball**: Swasti, Prasoon, Chitra, Tanvi.
- **Problem title:** *Joint Optimization of Control-Panel Placement and Closed-Loop Cable Routing.*
- **Dataset:** ResPlan, 17,000 residential floor plans (Kaggle `resplan/resplan`, plus a GitHub repo). Plans come from South Asian listings.
- **Task, per floor plan:**
  1. **Place hubs:** choose how many and where.
  2. **Assign rooms:** each eligible room and its node goes to one hub.
  3. **Order nodes:** one closed sequence per hub.
  4. **Route cable:** axis-aligned, through doors.
- **Deliverables per plan:**
  1. **Floor-plan overlay:** zones, hub and node IDs, visiting order, full rings including the return leg, violations in red.
  2. **JSON** with the same hubs, sequences, polylines and lengths.
- **Expected outcome (PDF):** a working prototype that processes an *unseen* ResPlan plan and produces the overlay plus matching JSON. The visual must clearly show that routes pass through doors or open passages, avoid walls and windows, and return to their hub.
- **Live demo:** the organisers hand over an unseen plan, and we solve it live.
- **Disclaimer on the slides:** "Research exercise: results are not a building-services design."

### 1.1 Eligible rooms and nodes
- **Eligible rooms:** `living`, `bedroom`, `kitchen`, `storage`. Each polygon is one room with **one node**.
- **Nodes** are fixed input points, one per eligible room, an arbitrary interior point at least 0.5 m from the walls. Teams cannot move them.
  - The dataset does **not** contain nodes. The organisers presumably supply them for hidden plans.
  - For practice we generate our own (§8.3).
- **Excluded rooms** (no node, no hub): `bathroom`, `balcony`, `stair`, `garden`, `pool`, `parking`, `land`.
- The organisers' benchmark keeps only plans a reference solver can solve, so no single room exceeds 100 m².

### 1.2 Hard rules (breaking any one makes the plan invalid, scoring 0)

| # | Rule | Meaning |
|---|---|---|
| 1 | Coverage | Every eligible room and its node is assigned to exactly one hub. None omitted, split or duplicated. |
| 2 | Capacity | Each hub: ≤ **100 m²** of eligible-room area **and** ≤ **5 nodes**. Both apply at once. |
| 3 | Zone | A hub's rooms connect through doors or open passages only. Windows, wall-only adjacency and the entrance don't count. |
| 4 | Ring | One closed ring per hub: H → every assigned node exactly once → same H. No branches; it never ends at another hub. Retracing a door to reach a single-door room is allowed, and the shared length counts as overlap. |
| 5 | Free space | Cable stays inside the inner boundary, outside walls and windows, runs only horizontally or vertically, and passes between rooms only through door or open-passage gaps. |
| 6 | Hub point | Inside an eligible room assigned to that hub, ≥ 0.5 m from walls. A hub and a node may share a room. |

- **Minimum hubs** = max(⌈total eligible area / 100⌉, ⌈nodes / 5⌉).
- The PDF project definition said 20 devices per panel; the detailed slides say **5**. **We use 5.**

### 1.3 Ranking and cost

**Fewest hubs wins. Ties go to the lowest J. Then the smallest assigned-area gap between hubs.**

```
J = L + 5·X + O + 0.5·B        (all in metres)
```

- **L (1 per m):** sum of polyline lengths over every leg of every ring, return legs included.
- **X (5 each):** crossings. Points where two cables meet *away from a node or hub*, inside one ring or between rings, counted once per point.
- **O (1 per m):** overlap. Length where two legs run along the same line. A stretch covered by k legs counts (k−1) × its length. A retrace on the same line counts; parallel runs on different lines don't.
- **B (0.5 each):** bends. Direction changes along each closed ring, nodes and hub included. All turns are 90°; a reversal counts once.
- **Tolerance 1 mm:** points closer than that are the same point, and lines within 1 mm of each other are the same line.
- Weights are "starting values, fixed after reference runs".

How scoring works across plans:
- The checker recomputes every metric from the submitted polylines; values reported in the JSON are ignored.
- Per plan, valid designs are ranked by hub count, then J.
- Rank points are summed over hidden, unseen plans.
- An invalid or missing plan scores zero.

**Worked examples from slide 7 (use them as metric test cases, §9):**
- **Length:** rectangle ring with legs 4 + 2 + 3 + 3 → L = 12 m (return leg included). Out-and-back retrace of 3 m → L = 6 m.
- **Crossings:** a "+" crossing in the open → X = 1. Two legs meeting at a node (an L-shape through a node) → X = 0.
- **Overlap:** 2 m on the same line → O = 2. Parallel runs on different lines → O = 0.
- **Bends:** a Z-shape with two turns → B = 2. Straight through a node → B = 0.

**Worked example from slide 5** (an invented 6-room layout):
- H1: Living + Bedrooms 1 and 3, 71 m², 3 nodes, 23.8 m, 8 bends.
- H2: Bedroom 2 + Kitchen + Storage, 47 m², 3 nodes, 25.2 m, 12 bends.
- 2 hubs is the lower bound (118 m², 6 nodes).
- A single-door room is entered and left through the same door with **two parallel runs**.

### 1.4 Scale (slide 4)

ResPlan coordinates are **drawing units, not metres**. The README claims metres; that's wrong.

```python
scale = (plan["inner"].area / plan["area"]) ** 0.5   # drawing units per metre
metres = units / scale;  m2 = units2 / scale**2;  0.5 m = 0.5 * scale units
```

Don't use `net_area` (it's 0 in 32% of plans). Convert once per plan, before any limit or clearance check.

---

## 2. Strategy (why the plan looks like this)

1. **Hub count mostly ties.** About 55% of plans need 1 hub and 41% need 2. Every competent team reaches the minimum, so **J decides the ranking**. Effort goes into cable quality.
2. **Zero invalid plans.** One broken rule means 0 for that plan.
   - Strict checker, safe-side assumptions.
   - Two independent metric implementations.
3. **Exhaustive search is feasible.**
   - Plans have ≤ 10 eligible rooms, and there are ≤ 106 legal zones per plan.
   - So we can try every split and every loop order, and score with the **true J**, including clashes between loops (an additive solver like CP-SAT can't see those).
4. **Differentiators** reuse solver numbers:
   - **break-the-cable mode**, showing why closed loops exist (Honeywell fire/security loops survive one cut),
   - **hub cost heatmap**,
   - **CP-SAT backup**, showing the method scales beyond ResPlan,
   - an honest **certificate**.

---

## 3. Data facts (verified on all 17,000 plans; reproduced in S0.3)

- **Format.** `ResPlan.pkl` is a Python list of 17,000 dicts with Shapely 2 geometries and NetworkX graphs.
  - Keys: `living, bedroom, bathroom, kitchen, storage, stair, balcony, door, window, wall, front_door, inner, land, garden, pool, parking, neighbor, id, area, net_area, wall_depth, graph`, plus `area_change_sqft` on augmented plans.
  - Missing categories are empty geometries; `storage` exists in only 1,781 plans.
  - Normalise the key `balacony → balcony` (see `resplan_utils.normalize_keys`).
- **Splits.** `split.json` has `train` 13,053 / `val` 1,632 / `test` 1,632 / `augmented` 683, as lists of plan `id`s. **Tune on train, report on test.**
- **Scale.** Median 18.3 units/m, mostly 12–26. 52 plans have suspicious scale or area (scale < 8 or > 40). Flag them; don't crash.
- **Stored graph is unreliable.**
  - Edge types are `via_door` 54%, `adjacency` 35%, `direct` 8%, `via_window` 3%.
  - `adjacency` means a shared wall only, which is **not** a valid zone link.
  - `resplan_utils.plan_to_graph()` produces different labels (`via_opening`, `fallback`).
  - Open passages aren't labelled reliably.
  - → **We build our own door/passage graph from geometry.**
- **Walls vs doors.** Of 108,487 doors, 99.4% have < 5% of their area covered by wall and 0.08% are more than half covered. 0.48% of plans have a door buried in a wall. → **Always subtract door shapes from walls.**
- **Invalid geometry:** about 400 door, 400 window, 111 land, 7 bedroom and 5 bathroom polygons are invalid → `make_valid`.
- **Multi-polygon living rooms:** 256 plans.
- **Jagged outlines:** 0.5% of room polygons have more than 30 vertices.
- **Size:** eligible rooms per plan median 4, p95 6, max 10. Eligible area median 95 m², p95 184 m².
- **Hub lower bound:** 1 hub in 55% of plans, 2 in 41%, 3 or more in about 4% (max 7). Area binds in about 35% of plans; the 5-node limit in 0.4%.
- **Rooms > 100 m²:** 428 plans have one; the organisers exclude them.
- **Axis alignment:** 98.4% of plans have ≥ 99% axis-aligned wall length, and 0.1% are below 90%.
- **Zones:** median 11 legal zones per plan, max 106. Listing them took 8 s for all 17,000 plans (measured with the stored `via_door` edges; recompute with our graph).
- **Strict zone rule cost:** only 28 of 17,000 plans (0.16%) have eligible rooms connected *only* through a bathroom or stair.

---

## 4. Assumptions (until the organisers answer) → `config.py` switches

Every ambiguous rule is a named config value, set to the **safe** side.

```python
# src/eightball/config.py  (frozen defaults; override via env or CLI)
MAX_NODES_PER_HUB      = 5
MAX_AREA_M2            = 100.0
HUB_CLEARANCE_M        = 0.5      # hub ≥ 0.5 m from walls
NODE_CLEARANCE_M       = 0.5      # practice-node generation
TOL_M                  = 0.001    # 1 mm: same point / same line
WALL_CLEARANCE_M       = 0.04     # free space shrunk 3–5 cm from walls & windows
LANE_SPACING_M         = 0.03     # parallel door lanes
MERGE_LINES_M          = 0.01     # merge Hanan lines closer than 1 cm
ALLOW_THROUGH_OTHER_ZONES = False # cable through another hub's rooms (switch, default OFF)
ALLOW_THROUGH_EXCLUDED = True     # cable through bathroom/stair/hall: confirmed allowed
ZONE_VIA_EXCLUDED_ROOMS = False   # zone connected only via bathroom/stair? NO (strict)
RETRACE_ONLY_SINGLE_DOOR = True   # retracing allowed only into single-door rooms
TOUCH_IS_CROSSING      = True     # T-touch between cables counts as a crossing
PASS_OTHER_NODE_IS_CROSSING = True
UNSURE_GAP_IS_WALL     = True     # open-passage detection: cautious
PASSAGE_MIN_WIDTH_M    = 0.6      # wall-free shared edge ≥ 0.6 m = open passage
MIN_ROOM_PART_M2       = 0.5      # polygon parts smaller than this are dropped (logged)
TIME_BUDGET_S          = 30.0     # per plan; lower once organisers give a limit
SEED                   = 0
TOPK_LOOPS             = 5
MAX_SPLITS             = 10_000
MAX_MIXES              = 10_000
BEAM_WIDTH             = 200
HEATMAP_STEP_M         = 0.25
FINE_GRID_M            = 0.01     # path-quality check
STRICT_CHECKER         = True     # anything ambiguous counts against us
```

| Assumption | How we build it |
|---|---|
| ≤ 5 nodes and ≤ 100 m² per hub | Hard limit in solver and checker |
| Cable may cross bathrooms, stairs, halls | Allowed (confirmed) |
| Cable through another hub's rooms | Switch, default **OFF**. Paths are routed per zone, so OFF is always feasible. Measure what ON would save on the test split |
| Zone connectivity | Rooms connect only through door/passage links **between rooms of the same zone** |
| Retracing | Only into single-door rooms; everywhere else, use lanes |
| Lines > 1 mm apart are distinct | Door lanes 3 cm apart |
| Touching another cable = a crossing; never pass through another loop's node | The checker counts it; the router keeps cables apart |
| Cable never touches walls or windows | Free space shrunk 3–5 cm |
| Area = repaired polygon ÷ scale² | Never add a hub just for a safety margin |
| Each polygon part ≥ 0.5 m² of an eligible type is its own room with its own node (slides: "each polygon is one room") | Log dropped slivers; open question |
| Organisers supply hidden-plan nodes | Input accepts their format; practice nodes = farthest-from-walls + random |

**Open questions for the organisers** (most important first). Keep these in `docs/OPEN_QUESTIONS.md` and update the switches when they're answered.
1. Can we get the scoring checker, or at least a sample output JSON with its schema?
2. What's the judging split between the hidden-plan score and the demo/presentation?
3. What's the time limit per plan in the live run, and the input format? Are node points supplied, and in what format?
4. Can a loop pass through a room assigned to a different hub?
5. Is retracing allowed anywhere other than into a single-door room?
6. How is room area computed for the 100 m² limit (raw polygon, repaired, which scale)?
7. Does a T-touch count as a crossing? Does passing through another loop's node? Does a cable on a wall's edge count as touching the wall?
8. Are collinear middle vertices or duplicate points allowed in polylines, and how do they affect bend counting?
9. Is a zone contiguous if two noded rooms connect only through a bathroom or stair? (28 plans)
10. How does the checker detect open passages? Is a return leg a few cm away a distinct line?
11. Is a multi-polygon living room one room or several? (256 plans) What happens with non-axis-aligned walls? (1.6% of plans)
12. Confirm 5 nodes per hub, not 20. Is pre-written code allowed before the event?

---

## 5. Architecture

Seven layers, each calling only the one below, all speaking one shared contract:

```
Presentation (web viewer)  →  API (FastAPI)  →  Evaluation (checker)  →  Optimisation  →  Routing  →  Geometry  →  Data I/O
                                         shared core: contracts, config, core metrics
```

- **No upward imports.** A layer imports only from the layer below and from `core`.
- **One contract.** Typed dataclasses plus a versioned JSON schema (§7).
- **Algorithms behind interfaces:** `Router`, `ZoneSolver` (exhaustive | CP-SAT), `RingSolver`, `Refiner`, chosen by config.
- **Independent validator.** `evaluate/` reads only answer JSON plus the raw plan, has **its own geometry and its own metric code**, and never imports `core.metrics`, `geometry`, `routing` or `optimize`.

### 5.1 Repo layout

```
8ball/
  pyproject.toml            # package "eightball", python >=3.11
  requirements.txt          # pinned (see S0.1)
  README.md
  data/                     # git-ignored: raw/ResPlan.pkl, raw/split.json, nodes/, out/
  docs/  PROGRESS.md DECISIONS.md BUILD_LOG.md OPEN_QUESTIONS.md data_facts.md BUILD_HANDOFF.md (this file)
  src/eightball/
    config.py
    core/        contracts.py  schema/answer.schema.json  metrics.py (core metrics, track 2)
    io/          resplan.py (load, split, scale)  answer_io.py  nodes.py
    geometry/    clean.py  doorgraph.py  freespace.py  nodes_gen.py
    routing/     crude.py (10 cm raster A*)  hanan.py  astar.py  fields.py  tree.py  api.py (PathCost)
    optimize/    zones.py  loops.py  hub.py  clash.py  ladder.py  polish.py  greedy.py  cpsat.py  heatmap.py
    evaluate/    checker.py  geom_indep.py  metrics_indep.py  (track 3; independent)
    bench/       run_all.py  stitch.py  finegrid.py  report.py
    api/         server.py
    viz/         overlay.py (matplotlib PNG/SVG for submission)
    cli.py       # python -m eightball ...
  web/          index.html app.js style.css   (viewer; vanilla JS + SVG)
  tests/        test_*.py  metric_cases.py
```

### 5.2 Four tracks (team ownership; one Claude Code session can build all of them in step order)

| Track | Owns | Stub it ships first |
|---|---|---|
| 1. Geometry + routing | clean, door graph, free space, Hanan tracks, per-zone paths, distance fields, branching tree | CleanPlan for 10 plans; crude router (10 cm grid) behind the PathCost API |
| 2. Optimiser | zones, loops, hub function, clash table, search ladder, polish, greedy baseline, heatmap numbers, **core metrics** | greedy grouping + nearest-node order on the crude router |
| 3. Checker + scale | checker with its own geometry and **its own metric code**, differential test, CP-SAT backup, 17k runner, stitched floors, dashboard data | checker scoring a hand-written answer JSON |
| 4. Viewer + story | 2D viewer, scorecard, plan gallery, break-the-cable with the branching comparison, heatmap view, pitch | viewer reading a hand-written answer JSON |

Track 2 (exhaustive solver) and track 3 (checker, CP-SAT) **must have different human owners**, so the cross-checks stay independent. Owners are named at M0.

---

## 6. Solver design (the algorithm)

1. **Clean.**
   - Convert to metres.
   - Subtract door shapes from walls.
   - `make_valid`; split multi-part shapes; drop parts < `MIN_ROOM_PART_M2`.
   - Simplify outlines **inward only** (the result must lie inside the original).
   - Build our own door/passage graph (front door excluded; unsure gap = wall).
2. **Tracks.** One Hanan grid per plan:
   - Free space = inner − walls − windows (doors carved), **shrunk by `WALL_CLEARANCE_M`**.
   - Lines through corners of the shrunk free space, door-gap centres and nodes.
   - Door lanes at ±`LANE_SPACING_M` through each door.
   - Merge lines closer than 1 cm.
   - Keep only edges lying inside the shrunk free space.
   - Tag every edge with the room it lies in.
3. **Paths, per zone.**
   - A zone may use its own rooms plus un-noded rooms, plus every room if `ALLOW_THROUGH_OTHER_ZONES`.
   - A* over (point, heading): 1 per metre + 0.5 per turn, on edges in those rooms only.
   - Store each node pair for 4 × 4 headings, cached by `(allowed_room_set, a, b)`. With the switch ON this collapses to one table.
   - Fine-grid check on 50 train plans: wherever a 1 cm grid finds a cheaper path, add corridor centre lines to the tracks and re-check.
4. **Zones.** Every group of ≤ 5 rooms with ≤ 100 m², connected under the zone rule.
5. **Loops.**
   - Every visiting order: (n−1)!/2 cycles, ≤ 12 for n = 5; a reversed cycle is the same loop.
   - Dead-end (single-door) room: choose retrace (d m overlap + 1 reversal bend) or an offset lane (≈ +1 bend, + about 0.06 m), whichever is cheaper.
   - Score each cycle with the **true ring J** (core metrics), including self-crossings and overlap.
   - Add each cycle's **hub cost** from step 6 (run for every cycle).
   - Keep the **top `TOPK_LOOPS` by loop J + hub cost**.
6. **Hub, by one insertion function.**
   - For each node, a direction-aware distance field over the zone's allowed grid (grid point × 4 headings), seeded with that node's heading in the loop. The field **into** j runs with headings reversed, so it measures p → j.
   - A candidate point's cost = the cheapest insertion into any leg i→j: `field_i(p) + field_j(p) + turn_at_p − cost(i→j)`.
   - Candidates: every 25 cm in the zone's eligible rooms at ≥ 0.5 m from walls, plus every straight stretch of the loop's legs (cost 0, "hub on the wire").
   - The hub is the minimum for its loop. The heatmap draws the **same** function, so they always agree.
7. **Clash table.**
   - For every pair of candidate loops from different zones, compute crossings and shared length exactly (polyline intersection at 1 mm), cached per pair.
   - Mix J = Σ loop J + Σ pairwise clashes.
   - Pairwise sums overcount overlap where 3 or more legs share a stretch, so re-score the best 10 mixes with core metrics.
8. **Combine by the search ladder** (§6.1). Tie-break: area gap.
9. **Polish.**
   - Rip-up-and-reroute, lanes, room swaps, hub moves. **Keep a change only if it stays valid and J drops.**
   - Clean polylines: no duplicate points, no collinear middle vertices, exact node and hub coordinates.
10. **Check.** Nothing ships unless the independent checker passes **and** checker metrics equal core metrics (lengths within 1 mm, counts exactly).

### 6.1 Search ladder (exactly one method decides each step)
1. **Greedy answer first** (milliseconds), kept as best-so-far, so a timeout never returns nothing.
2. **Splits.** Count the fewest-hub splits S. If S ≤ `MAX_SPLITS`, try them all.
3. **Mixes inside a split.**
   - Zones whose loops clash with nothing take their best loop.
   - Count the mixes M of the rest. If M ≤ `MAX_MIXES`, try them all; otherwise beam search (width `BEAM_WIDTH`).
4. **CP-SAT chooses the split** when S > `MAX_SPLITS` or half the time budget is gone. Step 3 then runs on its split.
5. **Polish** with the time left. On timeout, return best-so-far.

If no split exists at the hub lower bound (because of contiguity), retry with +1 hub and record why. Fixed seeds keep results deterministic.

### 6.2 CP-SAT backup
- **Model.**
  - One boolean per candidate zone; each eligible room covered exactly once.
  - Solve 1: minimise the number of hubs.
  - Solve 2: fix that count and minimise Σ best-loop cost (loop J + hub cost).
  - Clashes are invisible to this additive cost and are handled by steps 7–9. Because clashes only add cost, CP-SAT's bound is a valid floor (within our model).
- **When it runs:** ladder step 4, the cross-check, the scalability benchmark, or when chosen in config. It has a time limit and returns its best answer plus its bound.
- **Cross-check:** on every test-split plan, exhaustive search also records its best **additive** cost (ignoring clashes). CP-SAT must match that cost and the hub count.

### 6.3 Headline features
- **Break-the-cable mode.**
  - Click a segment to cut it. The viewer walks the loop both ways from the hub; every device stays green, with arrows showing which way its signal now arrives.
  - Cut a second segment and the devices between the cuts turn red.
  - **Branching comparison:** the shortest-path tree from the hub to every node over the same allowed grid (track 1 builds it, track 4 draws it). A cut turns every downstream device red.
  - Shown side by side with a counter, "devices lost: loop 0, branching N", plus each plan's worst single cut.
- **Hub cost heatmap.**
  - Colours every candidate hub point by the step-6 insertion function. The chosen point is always drawn.
  - Legend: "extra J for this zone's chosen loop".

### 6.4 What we claim (fill W, V, X, N, T, G from real runs)
- **Hubs:** proven minimum, given the doors and openings we detected.
- **Valid:** zero invalid results across the test split, confirmed by two independent metric implementations.
- **Cheaper:** W% lower J than a sensible greedy method (greedy grouping, nearest-node order, shortest paths).
- **Paths:** the track grid misses at most V% against a 1 cm grid.
- **Optimality:** within X% of the best in our model. X = 0% only when no cables clash, between loops or within one. Lead with W and V; the wall-ignoring absolute floor is a footnote.
- **Scales:** both solvers agree on every test plan. On stitched floors, "CP-SAT solves an N-room floor in T s, within G% of its own bound".
- **Fair:** tuned on train, reported on test.

---

## 7. Contracts (frozen in M0)

### 7.1 Answer JSON (`schema_version: "8ball-answer/1"`)
Coordinates are in the plan's **drawing units**, same frame as the input; `scale` is included so any reader can convert. Every leg polyline starts exactly at its `from` point and ends exactly at its `to` point, and every segment is axis-aligned.

```json
{
  "schema_version": "8ball-answer/1",
  "plan_id": 14433,
  "scale": 18.31,
  "nodes": [ {"node_id": "N1", "room_id": "bedroom_0", "point": [x, y]} ],
  "hubs": [
    {
      "hub_id": "H1",
      "point": [x, y],
      "room_id": "living_0",
      "room_ids": ["living_0", "bedroom_0"],
      "node_ids": ["N1", "N2"],
      "sequence": ["H1", "N2", "N1", "H1"],
      "legs": [ {"from": "H1", "to": "N2", "polyline": [[x, y], [x, y]]} ],
      "area_m2": 71.2,
      "length_m": 23.8
    }
  ],
  "metrics": {"H": 2, "L": 49.0, "X": 0, "O": 0.0, "B": 20, "J": 59.0},
  "meta": {"solver": "exhaustive", "runtime_s": 0.41, "config_hash": "…", "seed": 0}
}
```

- Room IDs are `"{type}_{k}"`, where k is the index of the polygon part in the plan's geometry for that type, **after** the cleaning order (deterministic). Node IDs are `N1…Nn` in room-ID order.
- `metrics` are informational; the organisers ignore them.
- A JSON Schema file lives at `core/schema/answer.schema.json`. When the organisers publish their schema, write an **adapter** (`io/answer_io.py: to_organiser_format`) rather than changing ours.

### 7.2 CleanPlan (geometry → everyone)
```python
@dataclass(frozen=True)
class Room:   id: str; type: str; poly: Polygon; area_m2: float; eligible: bool; door_ids: tuple[str,...]
@dataclass(frozen=True)
class Door:   id: str; poly: Polygon; rooms: tuple[str,str]; center: tuple[float,float]; axis: str  # 'h'|'v' wall orientation
@dataclass(frozen=True)
class Passage: id: str; seg: LineString; rooms: tuple[str,str]
@dataclass(frozen=True)
class Node:   id: str; room_id: str; point: tuple[float,float]
@dataclass
class CleanPlan:
    plan_id: int; scale: float
    inner: Polygon; walls: Polygon|MultiPolygon; windows: ...; front_door: ...
    rooms: dict[str, Room]; doors: dict[str, Door]; passages: dict[str, Passage]
    links: nx.Graph            # rooms as nodes; edges = door/passage links (front door excluded)
    free: Polygon|MultiPolygon # inner − walls − windows, shrunk by WALL_CLEARANCE_M
    nodes: dict[str, Node]
    tracks: "TrackGrid|None"   # filled by routing.hanan; every edge tagged with room_id
    flags: list[str]           # e.g. 'suspicious_scale', 'dropped_sliver:living_2', 'non_axis_walls'
```

### 7.3 PathCost API (routing → optimiser)
```python
class PathCost(Protocol):
    def cost(self, allowed_rooms: frozenset[str], a: str, heading_in: int, b: str, heading_out: int
             ) -> tuple[float, list[tuple[float,float]]]: ...   # cost = metres + 0.5*bends (incl. turn at a? no: turns strictly between a and b)
    def distance_field(self, allowed_rooms: frozenset[str], node: str, heading: int, reverse: bool=False
             ) -> "Field": ...                                     # Field.value(point, heading) -> float
    def branching_tree(self, allowed_rooms: frozenset[str], hub: tuple[float,float], nodes: list[str]
             ) -> dict[str, list[tuple[float,float]]]: ...         # node_id -> polyline from hub
# headings: 0=+x, 1=+y, 2=-x, 3=-y. 'a','b' are node ids or 'P:x,y' for free points (hub candidates).
```
Turn cost at a node is added by the ring scorer from `heading_in` / `heading_out` at that node, never inside `cost()`, so it isn't double counted.

### 7.4 Metrics interface (implemented twice)
```python
def score(answer: dict, scale: float) -> dict:
    # returns {"L": m, "X": int, "O": m, "B": int, "J": float, "per_hub": {...}}
def clash(poly_a, poly_b, scale) -> tuple[int, float]:   # crossings, shared length (m)
```
- `core/metrics.py` (track 2) is used by the optimiser.
- `evaluate/metrics_indep.py` (track 3) is written separately from the spec and imports nothing from `core` except the dataclasses.
- Both must pass `tests/metric_cases.py`.

### 7.5 Heatmap grid (optimiser → viewer)
```json
{"plan_id": 14433, "hub_id": "H1", "step_m": 0.25, "points": [[x, y, extraJ], ...], "chosen": [x, y], "legend": "extra J for this zone's chosen loop"}
```

---

## 8. Precise specs for the tricky parts

### 8.1 Metric computation (both implementations follow this; strict readings marked ⚑)
1. **Normalise each ring.**
   - Ring = concatenation of its legs' polylines.
   - Snap coordinates to a 1 mm grid in metres (`round(v/scale/TOL_M)`).
   - Drop zero-length segments and collinear middle vertices, **but keep vertices that are nodes or the hub**.
2. **L** = Σ segment lengths / scale.
3. **B.**
   - Walk the closed ring vertex by vertex, including node vertices and the hub, where the closing leg meets the first.
   - A 90° change = 1 bend; a 180° reversal = 1 bend; straight = 0.
4. **O.**
   - Group all segments of all rings by (orientation, constant coordinate snapped to 1 mm).
   - On each line, sweep the intervals. For every elementary stretch covered by k segments, add (k−1) × length.
   - ⚑ Segments of the same ring count too (retrace).
5. **X.**
   - Find every point where two segments meet: proper crossings, T-touches ⚑ and endpoint touches. Ignore pairs of consecutive segments in the same ring at their shared vertex.
   - Exclude points that coincide (≤ 1 mm) with any node or hub point **of the rings involved**. ⚑ Touching *another* loop's node still counts when `PASS_OTHER_NODE_IS_CROSSING`.
   - Collinear overlapping segments contribute to O, not X, except at overlap endpoints where a third segment meets.
   - Deduplicate points within 1 mm. Each unique point counts once.
6. **J** = L + 5X + O + 0.5B, summed over all rings.

### 8.2 Checker rules (strict mode)
- **Coverage:** every eligible room has exactly one node and appears in exactly one hub's `room_ids`; `node_ids` match the rooms.
- **Capacity:** Σ room area (repaired polygon / scale²) ≤ 100 + 1e-9, and ≤ 5 nodes.
- **Zone:** rooms connected in the checker's **own** door/passage graph using only links between rooms of that zone.
- **Ring:**
  - `sequence[0] == sequence[-1] == hub_id`, every node exactly once.
  - Consecutive legs join exactly.
  - No branch.
  - ⚑ Overlap inside one ring only where both overlapping legs touch a single-door room (if `RETRACE_ONLY_SINGLE_DOOR`).
- **Free space:**
  - Every segment axis-aligned (|dx| ≤ tol or |dy| ≤ tol).
  - Inside `inner`; not intersecting the interior of walls or windows (walls with doors subtracted).
  - ⚑ Not within `WALL_CLEARANCE_M/2` of a wall or window boundary.
  - Crossing from one room to another only through a door or passage gap.
  - ⚑ If `ALLOW_THROUGH_OTHER_ZONES` is False, the segment doesn't enter another zone's eligible room.
- **Hub:** point inside an eligible room of its zone; distance to every wall polygon and to the room boundary ≥ 0.5 m − tol.
- **Output:** a list of violations `{rule, hub_id, leg, location:[x,y], message}`, drawn in red by the viewer.

### 8.3 Practice node generation (until organisers supply nodes)
- Mode `center`: `shapely.ops.polylabel(room.buffer(-0.5*scale), tolerance=0.01*scale)`. If the shrunk room is empty, use `polylabel(room)` and flag it.
- Mode `random`: a uniform random point in `room.buffer(-0.5*scale)` (seeded).
- Save to `data/nodes/{mode}/{plan_id}.json`. Every benchmark runs on **both** modes.

### 8.4 Door / passage graph
- **Door → rooms.** Buffer the door polygon by `0.6 × wall_depth`, intersect with room polygons, and keep the two rooms with the largest contact length (drop others below 25% of the best). Exclude `front_door`. A door touching an excluded room still links it (used for routing). Zone links use eligible–eligible edges only.
- **Open passage (idea A).** For each pair of rooms whose buffered polygons overlap, take the shared boundary stretch (room A boundary ∩ room B buffered by `wall_depth`) minus walls buffered by 1 cm. A wall-free contiguous stretch ≥ `PASSAGE_MIN_WIDTH_M` is a passage.
- **Idea C (flood fill, used to cross-check A on 50 plans).** Rasterise free space at 2 cm; rooms are connected if a flood from one reaches the other without crossing a door polygon.
- **Rule:** where A and C disagree, the link is **not** a passage (`UNSURE_GAP_IS_WALL`).

### 8.5 Greedy baseline (also the comparison method for the "W% cheaper" claim)
1. Start from the largest unassigned eligible room and grow a zone by BFS over zone links, adding the neighbour that keeps area ≤ 100 and nodes ≤ 5 with the largest area. Repeat.
2. Hub = polylabel of the first room, shrunk by 0.5 m.
3. Order = nearest-neighbour from the hub.
4. Legs = shortest PathCost paths.

---

## 9. Metric test cases (`tests/metric_cases.py`)

Each case: rings as polylines in metres (scale = 1), node and hub points, and expected L, X, O, B. Cases come from the slides where they exist; otherwise they're hand-computed and **agreed by two people** (note who in a comment).

1. Slide 7 loop (4 + 2 + 3 + 3 = 12 m): H (0,0) → N1 (4,0) → N2 (4,2) → N3 (1,2) → back to H via (0,2), so the last leg is [(1,2),(0,2),(0,0)]. Expect L = 12, B = 4 (turns at N1, N2, (0,2) and H; straight through N3), X = 0, O = 0.
2. Slide 7 retrace: H (0,0) → N (3,0) → H: L = 6, O = 3, B = 2 (two reversals, at N and at H).
3. Slide 7 crossing: two separate rings crossing in a "+" away from nodes: X = 1.
4. Slide 7 meet at node: two legs meeting at a node point: X = 0.
5. Slide 7 overlap: two rings sharing 2 m of the same line: O = 2.
6. Slide 7 parallel: two rings on lines 3 cm apart: O = 0.
7. Slide 7 Z-shape: B = 2. Straight through a node: B = 0.
8. T-touch (strict): X = 1.
9. Three legs on one 1 m stretch: O = 2.
10. Collinear middle vertex / duplicate point: no extra bend.
11. 1 mm tolerance: endpoints 0.5 mm apart count as the same point; lines 0.9 mm apart count as the same line; 1.5 mm apart count as different.
12. A ring passing through another ring's node: X = 1 (strict switch).

---

## 10. Milestones (each gates the next)

| Milestone | Done when |
|---|---|
| **M0 Contracts** | Five contracts frozen (answer JSON, CleanPlan, PathCost API, metrics interface + test cases, heatmap grid); owners named; walls-vs-doors check reproduced |
| **M1 Dumb end to end** | Crude router → greedy → checker → viewer works on 10 plans. From here we always have a demo |
| **M2 Exact solver** | On 1,000 train plans: zero invalid, J never higher than greedy on any plan and lower on average, zero metric mismatches |
| **M3 Feature complete** | Every test-split plan runs with zero invalid and zero mismatches; break-the-cable (with branching comparison) and heatmap work; CP-SAT matches exhaustive search on every test plan; stitched-floor chart drawn. **Cut line: nothing new starts after this** |
| **M4 Freeze** | Bug fixes only; backup demo video; rehearsals |
| **M5 Submit** | Answer files, overlays, repo and deck handed in |

**Cut (don't build unless M3 is done and the team agrees):** why panel, Pareto sliders, 3D twin, plan editor/upload, fuzzer, CI, fire/flood mode, gestures, photo/PDF upload, learned warm start, solver replay, installer mode. A track that finishes early helps another track reach its milestone.

---

## 11. Build plan: executable steps

Legend: **[T1]–[T4]** = owning track. Every step ends with: tests green, `PROGRESS.md` updated, commit.

### Phase 0: Setup (before M0)

**S0.1 Repo skeleton and environment [all]**
- **Goal:** an empty but runnable package.
- **Do:**
  - `git init`.
  - Create the layout in §5.1, `pyproject.toml` (package `eightball`, src layout) and `.gitignore` (`data/`, `.venv/`, `__pycache__/`, `*.pkl`).
  - Pin `requirements.txt`: `shapely==2.1.*` (2.0+ unpickles ResPlan; this was verified with 2.2.0), `numpy`, `networkx>=3`, `matplotlib`, `geopandas`, `ortools`, `fastapi`, `uvicorn`, `jsonschema`, `pytest`, `pandas`, `pyarrow`, `tqdm`. Record exact versions after install (`pip freeze > requirements.lock`).
  - Create `docs/PROGRESS.md` (all steps `todo`), `DECISIONS.md` (seeded with §12), `BUILD_LOG.md`, `OPEN_QUESTIONS.md` (§4 list), and copy this file to `docs/BUILD_HANDOFF.md`.
- **Done when:** `python -m pytest -q` runs (0 tests OK) and `python -c "import eightball"` works.

**S0.2 Data and loader [T1]**
- **Goal:** load plans, ids, splits and scale reliably.
- **Do:**
  - Get the data: `kaggle datasets download -d resplan/resplan -p data/raw --unzip`, or ask the user to place `archive.zip` contents in `data/raw/` (`ResPlan.pkl` is about 287 MB, plus `split.json`).
  - `io/resplan.py` provides:
    - `load_plans(path) -> list[dict]` (cached pickle load; apply `balacony → balcony`),
    - `get_plan(id)`,
    - `split_ids(name)`,
    - `scale(plan)`,
    - `parts(geom)` (single/multi/collection → list of polygons).
- **Done when:** `tests/test_io.py` checks 17,000 plans, split sizes 13,053/1,632/1,632/683, and plan `id` 14433 has scale ≈ √(46029.3/120.77) ≈ 19.5.

**S0.3 Data audit (reproduce §3) [T1]**
- **Goal:** confirm the facts we rely on.
- **Do:** `bench/audit.py` computes and writes to `docs/data_facts.md`: scale distribution, eligible rooms per plan, eligible area, hub lower bound distribution, walls-vs-doors coverage, invalid geometry counts, multi-polygon living count, axis alignment.
- **Done when:** the numbers match §3 within rounding (they will shift slightly once we use our own door graph; note any differences).

### Phase M0: Contracts

**S0.4 Core contracts + config [T2 + T3 agree]**
- **Do:**
  - `config.py` (§4) with env override (`EIGHTBALL_<NAME>`) and `config_hash()`.
  - `core/contracts.py` dataclasses (§7.2).
  - `core/schema/answer.schema.json` (§7.1).
  - `io/answer_io.py` with `write_answer` / `read_answer` (validated).
- **Done when:** `tests/test_contracts.py` validates a hand-written sample answer (2 hubs) and rejects 3 broken ones (missing return leg, non-axis segment, wrong schema_version).

**S0.5 Metric test cases [T2 + T3, agreed by two people]**
- **Do:** write `tests/metric_cases.py` with the 12 cases in §9 as pure data, plus `tests/test_metrics_core.py` and `tests/test_metrics_indep.py`. Both test files are parameterised over the cases and currently `xfail`.
- **Done when:** the cases load and the tests are collected.

**S0.6 PathCost protocol + heatmap contract [T1 + T2]**
- **Do:** `routing/api.py` Protocol (§7.3), heading constants, and a `Field` interface; heatmap JSON writer (§7.5).
- **Done when:** the import works and type-checks (`python -m compileall src`).

**→ Gate M0:** contracts committed, `DECISIONS.md` row "Contracts v1 frozen", owners recorded.

### Phase M1: Dumb end to end

**S1.1 Geometry clean + door graph + free space + nodes [T1]**
- **Do:**
  - `geometry/clean.py`: `make_valid` everything; subtract doors from walls; split parts; drop slivers; deterministic room IDs; area_m2; simplify inward only (`poly.simplify(tol).intersection(poly)` then re-validate); flags.
  - `geometry/doorgraph.py`: §8.4 idea A (plus C behind a flag).
  - `geometry/freespace.py`: inner − walls − windows, shrunk by `WALL_CLEARANCE_M*scale`.
  - `geometry/nodes_gen.py`: §8.3; accepts external nodes.
  - `build_clean_plan(plan, nodes=None) -> CleanPlan`.
  - `viz/overlay.py debug`: PNG of rooms, doors, links, free space and nodes.
- **Done when:**
  - The 10 plans `[0..9]` of the train split, plus ids 14433 and 1448, build without error.
  - Debug PNGs are saved to `data/out/debug/` and inspected by eye. Doors link the right rooms, the kitchen-to-living openings are detected as passages, and the front door is excluded.
  - Unit tests: rooms ≥ 1 per plan; each node lies inside its room at ≥ 0.5 m from the boundary; free space doesn't touch walls.
  - Run over the full train split: no exceptions (flag and continue).

**S1.2 Crude router [T1]**
- **Do:** `routing/crude.py`: rasterise the allowed free space at 10 cm; A* over (cell, heading) with cost 1/m + 0.5/turn; return a cleaned axis-aligned polyline that snaps exactly to the endpoints (add a short axis-aligned stub from the cell centre to the exact point if needed, staying in free space). Implements `PathCost.cost` and `branching_tree`.
- **Done when:** on 10 plans, paths exist between all node pairs of each door-connected component; every segment is axis-aligned and inside free space (checked with Shapely).

**S1.3 Core metrics [T2]**
- **Do:** `core/metrics.py` per §8.1.
- **Done when:** `test_metrics_core.py` passes all 12 cases (remove `xfail`).

**S1.4 Checker [T3, different person from S1.3]**
- **Do:**
  - `evaluate/geom_indep.py`: its own minimal geometry (scale, rooms, door links, walls with doors subtracted). **Don't** import `eightball.geometry`.
  - `evaluate/metrics_indep.py` per §8.1, written from the spec, not from `core/metrics.py`.
  - `evaluate/checker.py`: `check(plan_raw, answer) -> {"valid": bool, "violations": [...], "metrics": {...}}` per §8.2.
  - CLI: `python -m eightball check --plan-id 14433 --answer file.json`.
- **Done when:**
  - `test_metrics_indep.py` passes all 12 cases.
  - `tests/test_checker.py` catches one hand-made violation per rule (6 cases) and passes one valid hand-written answer.

**S1.5 Greedy baseline solver [T2]**
- **Do:** `optimize/greedy.py` per §8.5, using the crude router; emits answer JSON.
- **Done when:** on 10 plans the checker reports `valid` for every one, or every invalid case is explained and fixed.

**S1.6 Viewer v0 + submission overlay [T4]**
- **Do:**
  - `viz/overlay.py submit`: matplotlib SVG/PNG with walls, doors, windows, zones tinted per hub, hub squares with IDs, node circles with IDs, ring polylines in the hub colour with order numbers on each leg (return leg included), violations as red markers with text, and a scorecard (H, L, X, O, B, J).
  - `web/`: a static page that loads `plan.json` (geometry exported by `cli export-plan`) plus `answer.json` and draws them in SVG (pan/zoom, hover IDs).
- **Done when:** overlays for the 10 greedy answers render. The web viewer opens via `python -m http.server` and shows the same.

**S1.7 End-to-end CLI [all]**
- **Do:** `cli.py` commands:
  - `solve --plan-id ID [--nodes center|random|file] [--solver greedy|exact] [--out DIR]` writes answer + overlay + check result;
  - `check`;
  - `export-plan`;
  - `batch --split train --limit N`.
- **Done when:** `python -m eightball batch --split train --limit 10 --solver greedy` reports 10/10 valid, with a summary table (H, J, runtime).

**→ Gate M1:** demo-able. Write a BUILD_LOG entry.

### Phase M2: Exact solver

**S2.1 Hanan tracks [T1]**
- **Do:**
  - `routing/hanan.py`: per §6 step 2. Build the x and y line sets from:
    - corners of the shrunk free space,
    - door-gap centres, with lanes at ±`LANE_SPACING_M`,
    - nodes,
    - (later) hub candidates.
  - Merge lines within 1 cm. Intersect lines into vertices and keep edges whose segment lies within the shrunk free space (prepared geometry, `covers`). Tag each edge with its room (the edge midpoint's containing room; excluded rooms are tagged too).
  - Store as arrays (vertex coords, adjacency per heading).
- **Done when:** on 50 train plans every node is a vertex, every door has ≥ 3 parallel crossing edges (centre ± lane), and the grid builds in < 0.5 s per plan (median).

**S2.2 Per-zone A* + cache + fine-grid check [T1]**
- **Do:**
  - `routing/astar.py`: A* on the Hanan grid over (vertex, heading), restricted to edges tagged with the allowed rooms. Implement `PathCost.cost` for all 4 × 4 heading combinations, with an LRU cache keyed by `(frozenset(allowed), a, b)`.
  - `bench/finegrid.py`: compare against a 1 cm raster A* on 50 train plans. Where the fine grid is cheaper by more than 1 mm, add corridor centre lines and re-run.
- **Done when:** the fine-grid report gives V% (share of node pairs where Hanan is worse) and the mean gap, written to `docs/data_facts.md`. Target V ≤ 2% after centre lines.

**S2.3 Zone enumeration [T2]**
- **Do:** `optimize/zones.py`: every connected set (zone links within the set only) of ≤ 5 eligible rooms with Σ area ≤ 100. Grow subsets by BFS from each room in canonical order to avoid duplicates; use a bitmask.
- **Done when:** on the full train split, median ≈ 11 and max ≈ 106 (expect small shifts with our own graph), in < 1 ms median per plan.

**S2.4 Loop enumeration [T2]**
- **Do:** `optimize/loops.py`:
  - For each zone, enumerate all (n−1)!/2 cycles over its nodes (n = 1: hub out-and-back; n = 2: one cycle).
  - For each leg choose headings to minimise turns at nodes, via dynamic programming over the 4 headings at each node using the 4 × 4 costs.
  - For single-door rooms evaluate retrace vs lane.
  - Assemble the ring and score it with `core.metrics` (self-crossings and overlap included).
- **Done when:** unit tests on synthetic plans (a corridor with 3 bedrooms; a single-door room) pick the expected order; the slide 5 schematic replica gives sensible values.

**S2.5 Hub insertion function + ranking [T2, fields by T1]**
- **Do:**
  - `routing/fields.py`: a direction-aware Dijkstra field from a node and heading (forward), and the **reversed** field into a node.
  - `optimize/hub.py`: candidates (25 cm grid in the zone's eligible rooms at ≥ 0.5 m, plus straight stretches of legs); `hub_cost(loop)` = the minimum insertion; the chosen point inserted into the ring.
  - Rank each zone's cycles by loop J + hub cost and keep the top 5.
  - `optimize/heatmap.py` writes the §7.5 JSON from the same function.
- **Done when:**
  - The hub always passes the checker's hub rule on 200 plans.
  - The heatmap minimum equals the chosen hub cost (unit test).
  - A test confirms the reversed-heading field (an asymmetric case).

**S2.6 Clash table [T2]**
- **Do:** `optimize/clash.py`: for candidate loops of different zones, `clash()` from core metrics, cached by (loop_id_a, loop_id_b). Mix scoring = Σ J + Σ clashes; re-score the top 10 mixes with the full `core.metrics.score`.
- **Done when:** on 2-hub plans, the mix score equals the full score whenever ≤ 2 legs overlap (test), and the re-scoring is applied.

**S2.7 Search ladder [T2]**
- **Do:** `optimize/ladder.py` per §6.1, with time-budget handling and best-so-far; +1-hub retry with a recorded reason; area-gap tie-break.
- **Done when:** a plan never returns an empty answer even with `TIME_BUDGET_S=0.01` (it returns greedy).

**S2.8 Polish [T2]**
- **Do:** `optimize/polish.py`: rip-up-and-reroute of clashing legs (forbid the other ring's edges and lines within 1 mm, then re-route); lane switch; room swap between neighbouring zones (capacity + connectivity re-check); hub moves along the field. Accept only if the checker-valid status holds and J drops. Final polyline cleaning.
- **Done when:** on 100 multi-hub train plans, polish never increases J and never produces an invalid result.

**S2.9 Differential test + M2 benchmark [T3]**
- **Do:** `bench/run_all.py --split train --limit 1000 --solver exact,greedy --nodes center,random` with multiprocessing. Per plan it records: H, J (core), J (checker), metrics mismatch, valid, violations, runtime, greedy J. Output `data/out/runs/<name>.parquet` plus a summary.
- **Done when (M2 gate):**
  - 0 invalid.
  - 0 mismatches (lengths ≤ 1 mm, counts exact).
  - Exact J ≤ greedy J on every plan, and lower on average.
  - Median runtime reported.
  - W% computed.

### Phase M3: Feature complete

**S3.1 CP-SAT ZoneSolver + cross-check [T3, not the S2 author]**
- **Do:** `optimize/cpsat.py` per §6.2 (OR-Tools CP-SAT; two-stage solve; time limit; returns its bound). Plug it in behind `ZoneSolver`. Cross-check against exhaustive search's best additive cost on the full test split.
- **Done when:** hub count and additive cost match on 100% of test plans (report any mismatch as a bug and fix it).

**S3.2 Full test-split run + dashboard data [T3]**
- **Do:** run `run_all.py --split test --solver exact --nodes center,random`, plus `ALLOW_THROUGH_OTHER_ZONES=True` for comparison. `bench/report.py` writes `web/data/dashboard.json`: share at proven minimum, J distribution, W%, V%, X% (gap to the in-model floor on multi-hub plans), runtime percentiles, failure categories, and what the switch would save.
- **Done when:** 0 invalid and 0 mismatches on the test split; `dashboard.json` exists.

**S3.3 Stitched-floor scalability benchmark [T3]**
- **Do:** `bench/stitch.py`:
  1. Convert flats to metres (rescale geometry by 1/scale).
  2. Place flats with outer walls touching.
  3. Where eligible rooms of two flats meet, cut one door (0.9 m) through both outer walls and fill the gap.
  4. Merge inners and re-run cleaning.
  5. Build floors of 2–8 flats (about 10–80 eligible rooms). Drop floors that fail cleaning.
  6. Time exhaustive search (until budget) vs CP-SAT.
  7. Write a chart (runtime vs room count) and claim numbers (N, T, G).
- **Done when:** the chart PNG and `web/data/scale.json` exist.

**S3.4 Break-the-cable + branching comparison [T1 tree, T4 view]**
- **Do:** `routing/tree.py` `branching_tree` from the existing fields. In the viewer: click a segment to cut; walk the ring both ways from the hub; colour devices green with arrows, or red when between two cuts. A side panel shows the branching layout for the same zones and hubs, with the "devices lost: loop 0, branching N" counter and each plan's worst single cut.
- **Done when:** it works on 3 plans (1, 2 and 3+ hubs) in the browser.

**S3.5 Heatmap view [T4]**
- **Do:** the viewer layer reads the heatmap JSON. Colour ramp in J units, the chosen hub always drawn, legend "extra J for this zone's chosen loop".
- **Done when:** for 5 plans the brightest (cheapest) cell is at the chosen hub.

**S3.6 Scorecard, gallery, dashboard page [T4]**
- **Do:**
  - Scorecard per plan: H, L, X, O, B, J, certificate line ("proven minimum hubs given detected doors"; "within X% of in-model floor").
  - Plan gallery of about 12 curated plans (1, 2 and 3+ hubs; tricky doors).
  - Dashboard page from `dashboard.json` and `scale.json`.
- **Done when:** every page loads from static files.

**S3.7 API service + live-run path [T2 + T4]**
- **Do:** `api/server.py` (FastAPI): `GET /plans?split=`, `GET /plan/{id}`, `POST /solve` (plan id or uploaded ResPlan dict + optional nodes; returns answer + heatmap + check within `TIME_BUDGET_S`, best-so-far on timeout), `POST /validate`. The viewer calls the API when it's available and falls back to static files otherwise. An **organiser-input adapter** reads their plan/node format once known.
- **Done when:** `uvicorn eightball.api.server:app` serves; solving an unseen test plan from the viewer completes within budget.

**→ Gate M3 (cut line):** everything in the M3 row of §10 is true. Nothing new starts after this.

### Phase M4: Freeze

**S4.1 Backups and rehearsal [T4 + all]**
- **Do:**
  - Pre-solve 10 plans (1, 2 and 3+ hubs) and store their outputs.
  - Record a screen video of the full demo script.
  - `README.md` "reproduce from a clean machine" steps.
  - Pin `requirements.lock`.
  - Run a rehearsal checklist: cold start → solve unseen plan → break a cable → heatmap → dashboard → scale chart.
- **Demo script:** gallery → solve → scorecard → break a cable next to the branching layout → heatmap → 17k dashboard → CP-SAT scalability chart.
- **Done when:** the checklist passes twice in a row on the demo laptop.

### Phase M5: Submit

**S5.1 Submission package [all]**
- **Do:**
  - Answer JSON (converted to the organiser format if one is given) plus SVG/PNG overlays for every required plan.
  - Repo tag `v1.0`.
  - Deck: problem → approach → claims with real numbers (W, V, X, N, T, G) → demo → resilience story.
- **Done when:** the organisers' submission requirements checklist is ticked.

---

## 12. Decision log (seed `docs/DECISIONS.md` with this; newest first)

| Date | Decision | Why |
|---|---|---|
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

---

## 13. Known risks → where each is handled

| Risk | Mitigation (step) |
|---|---|
| Live unseen plan crashes the parser | Full-split runs (S1.1, S3.2); greedy first (S2.7); backups (S4.1) |
| Our rule reading differs from the official checker | Strict checker + switches (S1.4); ask for their checker or schema |
| A metric bug the optimiser exploits and the checker approves | Two implementations + differential test (S1.3, S1.4, S2.9) |
| Both metric implementations share the same misreading | Slide-based cases, agreed by two people and reviewed by a third (S0.5) |
| Track 1 delays everyone | Crude router + 10 CleanPlans ship first (S1.1, S1.2) |
| Per-zone routing slow on large floors | Cache by allowed-room set; profile on stitched floors (S2.2, S3.3) |
| Cable on a wall edge | Shrunk free space; simplify inward (S1.1, S2.1) |
| Door buried in a wall | Subtract doors from walls (S1.1) |
| Open passages missed or invented | Idea A + C cross-check; unsure = wall (S1.1) |
| Hanan grid misses cheaper paths | Fine-grid check + centre lines (S2.2) |
| Slivers / MultiPolygons after repair | Split parts, drop below threshold, log (S1.1) |
| Small rooms vanish at 0.5 m shrink | Not hub sites; still hold a node (S2.5) |
| Hub lower bound infeasible (contiguity) | +1 hub retry with a reason (S2.7) |
| Combining blows up | Ladder: clash-free zones fixed, beam, CP-SAT (S2.7, S3.1) |
| Heatmap disagrees with the hub | One function + reversed-heading test (S2.5) |
| Stitched floors break cleaning | Metres first, door through both walls, drop failures (S3.3) |
| Solver and viewer disagree on JSON | Frozen schema + validation (S0.4) |
| Shapely/pickle version mismatch | Pinned lock file (S0.1) |
| Merge conflicts (4 people) | One module per person, small commits, PR reviews |

---

## 14. Ideas parked (Appendix: revive only after M3, with team agreement)
- **Pareto explorer:** hard rules never toggle; precompute non-dominated designs; real-world weights (₹/m, labour per bend, hub price).
- **Upload your own plan:** tier 1 ResPlan file; tier 2 in-browser editor; tier 3 photo/PDF → vector via OpenCV.
- **3D twin** (three.js, cables as tubes) + gestures (MediaPipe Hands behind a toggle).
- **Why panel** ("hub here because moving it 1 m east adds 2 bends, +1.0 J").
- **Fire/flood resilience mode** (replaced by break-the-cable).
- Solver replay, installer mode, learned warm start, plan fuzzer, CI.
- **Visual style options** for later polish: metro-map, blueprint, clean architectural (default: clean architectural, close to the organisers' slide 5 look).

---

## 15. Quick reference snippets

```python
import pickle, json
plans = pickle.load(open("data/raw/ResPlan.pkl", "rb"))     # list[dict], 17,000
split = json.load(open("data/raw/split.json"))             # train/val/test/augmented -> ids
plan  = next(p for p in plans if p["id"] == 14433)
scale = (plan["inner"].area / plan["area"]) ** 0.5           # units per metre
def parts(g):
    if g is None or g.is_empty: return []
    return list(g.geoms) if hasattr(g, "geoms") else [g]
ELIGIBLE = ("living", "bedroom", "kitchen", "storage")
EXCLUDED = ("bathroom", "balcony", "stair", "garden", "pool", "parking", "land")
walls = shapely.make_valid(plan["wall"]).difference(shapely.make_valid(plan["door"]))   # always
```

**First action in a fresh Claude Code session:** read this file and check whether `docs/PROGRESS.md` exists. If it doesn't, start **S0.1**. If it does, continue from the first step not marked `done`. Tell the user which step you're on in one line, then do it.
