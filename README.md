# 8ball

Team 8ball (Swasti, Prasoon, Chitra, Tanvi), HackHive x Honeywell: joint control-panel (hub) placement and closed-loop cable routing on ResPlan floor plans.

- **What we're building and how:** [`docs/BUILD_HANDOFF.md`](docs/BUILD_HANDOFF.md)
- **Who builds what:** [`docs/BUILD_SPLIT.md`](docs/BUILD_SPLIT.md) (Person A: solver; Person B: checker + showcase)
- **Progress:** [`docs/PROGRESS_P0.md`](docs/PROGRESS_P0.md), [`docs/PROGRESS_A.md`](docs/PROGRESS_A.md), [`docs/PROGRESS_B.md`](docs/PROGRESS_B.md)

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock   # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pip install -e . --no-deps
```

Put the ResPlan data (Kaggle `resplan/resplan`) in `data/raw/`: `ResPlan.pkl` and `split.json`. `data/` is never committed.

## Commands

```bash
python -m pytest -q
python -m eightball --help
python scripts/integrate.py --checkpoint i0
```
