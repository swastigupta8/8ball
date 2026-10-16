# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: Honeywell judges at the HackHive hackathon demo. They give the landing page seconds, then need to land in the
viewer and see a plan solved. Secondary (the story): building-services engineers who wire devices on real flats.

## Product Purpose
8ball places the fewest network hubs on a floor plan and routes every device onto a closed, axis-aligned cable loop
through the doorways, ranked by fewest hubs, then total cost J = L + 5X + O + 0.5B. Success at the demo: a judge
understands "fewer hubs, closed loops, no single point of failure" and opens the viewer.

## Positioning
Closed loops (the way addressable fire-alarm loops are wired), so one cut cable never takes a device offline; an
exact solver with a proven hub lower bound; an independent checker, written separately, that has never disagreed with
the solver.

## Capabilities and Constraints
- Static web pages served by the project's own FastAPI server (`python -m eightball serve`); plain HTML/CSS/JS, no build.
- Must work offline at the demo: three.js is bundled in `web/vendor`, fonts in `web/fonts`; no CDN.
- Real data only: plans and answers come from `web/data/gallery` (git-ignored, regenerated per laptop) and headline
  numbers from `web/data/dashboard.json`.

## Evidence on Hand
Full test split results (dashboard.json): solved-and-valid count, W (cost saved against greedy), share of answers at
the proven minimum number of hubs, 0 solver/checker disagreements. Twelve solved gallery plans with 1, 2 and 3+ hubs.
No customers, testimonials, prices or awards exist; never invent them.

## Brand Commitments
Name "8ball". The user pinned the landing page's structure to a reference site: full-viewport dark hero, central 3D
object tilting toward the cursor, floating objects repelled by the pointer, rising particles, glass navigation, giant
headline (first a Galada script; the user then asked for a professional face: Manrope 800), a right-hand card switcher with a choreographed transition. Colours dark and deep; the 3+-hub theme is deep maroon/burgundy, not purple. Every page shares the landing page theme (no animations needed elsewhere).

## Product Principles
- Prove, don't claim: show a real solved plan, real numbers.
- One click to the viewer from anywhere on the landing page.
- Honest limits: research exercise, not a building-services design.
