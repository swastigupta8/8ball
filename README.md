# 8ball

Team 8ball (Swasti, Prasoon, Chitra, Tanvi), HackHive x Honeywell: joint control-panel (hub) placement and closed-loop cable routing on ResPlan floor plans.

**Picking this up in a new session? Read [`HANDOFF_V1.md`](HANDOFF_V1.md) first.**

**Status: V1.** The whole pipeline works end to end: plan in, hubs and closed cable rings out, checked by an independent checker, with a web app to upload a plan, solve it, look at it and download the result. What is left is polish, the final check run and the submission (see `docs/INBOX.md` and `docs/EDGE_CASES.md`).

- **Results and what has happened:** [`docs/PROJECT_SUMMARY.md`](docs/PROJECT_SUMMARY.md)
- **What we assume where the rules are unclear:** [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md)
- **Odd plans and known limits:** [`docs/EDGE_CASES.md`](docs/EDGE_CASES.md) (open questions: [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md))
- **What we built and how:** [`docs/BUILD_HANDOFF.md`](docs/BUILD_HANDOFF.md), **who built what:** [`docs/BUILD_SPLIT.md`](docs/BUILD_SPLIT.md)
- **The two Claude sessions talk through:** [`docs/INBOX.md`](docs/INBOX.md)

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock   # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pip install -e . --no-deps
```

Put the ResPlan data (Kaggle `resplan/resplan`) in `data/raw/`: `ResPlan.pkl` and `split.json`. `data/` is never committed.

## Run the web app

```bash
python -m eightball serve --port 8765
```

Open http://127.0.0.1:8765 for the home page. **Viewer** (`/viewer.html`): type a ResPlan number and press Load and Solve, or press **Upload plan** (or drop a file on the page) to solve your own floor plan. After a solve the **Download** box gives the solution JSON, the floor-plan image (PNG or SVG) and a full report; each solve is also saved in `data/out/api/<plan id>/`. Also: break-the-cable view, hub-cost heatmap, and a **2D / 3D** switch (top right of the canvas, or `viewer.html?id=14433&view=3d`): a rotatable 3D model of the floor plan with glowing cables, sliders for wall and cable height, colours and light direction, camera presets, and click-to-cut in 3D (three.js is bundled in `web/vendor/`, so it works offline). **Gallery** and **How it works** read result files that are not committed (`web/data/` is git-ignored); on a new laptop make them with:

```bash
python -m eightball.bench.gallery
python -m eightball batch --split test --solver exact,greedy --name test
python -m eightball.bench.report data/out/runs/test
python -m eightball stitch --split train
```

The interactive API page is at http://127.0.0.1:8765/docs.

## Try it with a sample input

`sample_input/` and `original_test_plan/` hold floor plans in the upload format (the body of `POST /api/solve`). Upload one in the viewer, or from the command line:

```bash
python sample_input/run_sample.py sample_input/sample_plan_769.json
```

`sample_input/README.txt` describes the format; `sample_input/make_sample.py` makes a sample from any ResPlan plan.

## Command line

```bash
python -m eightball solve --plan-id 14433 --solver exact      # answer.json in data/out/solve/<id>/
python -m eightball check --plan-id 14433 --answer data/out/solve/14433/answer.json
python -m eightball overlay --plan-id 14433 --answer data/out/solve/14433/answer.json --format png --out overlay.png
python -m eightball batch --split test --limit 50 --solver exact,greedy --nodes center,random
python -m eightball --help                                    # every command
```

## Tests and checkpoints

```bash
python -m pytest -q
python scripts/integrate.py --checkpoint i3 --workers 6       # the final check run (about 1.5 h); set EIGHTBALL_TIME_BUDGET_S=90
```

Git tags: `i1`, `i2`, `i3` (integration checkpoints), `v1` (this milestone). `v1.0` is kept for the submission.
