// Home page: a solved gallery plan as the hero picture, and the headline numbers from the latest benchmark.
"use strict";

async function initHome() {
  const [gallery, dash] = await Promise.all([fetchJSON("data/gallery/index.json"), fetchJSON("data/dashboard.json")]);

  // Hero: the first solved multi-hub plan, so the picture shows more than one loop.
  const plans = (gallery?.plans || []).filter((e) => e.solved && e.valid);
  const pick = plans.find((e) => (e.metrics?.H || 0) >= 2) || plans[0];
  if (pick) {
    const [plan, answer] = await Promise.all([fetchJSON(`${pick.path}/plan.json`), fetchJSON(`${pick.path}/answer.json`)]);
    const art = document.getElementById("hero-art");
    if (plan) {
      art.append(planThumbnail(plan, answer, "hero-thumb"));
      art.href = `viewer.html?plan=${encodeURIComponent(pick.path)}`;
    }
  } else {
    document.getElementById("hero-art").hidden = true;
  }

  const stats = document.getElementById("stats");
  if (!dash?.n) { stats.closest("section").hidden = true; return; }
  const pct = (v) => `${Math.round(100 * v)}%`;
  const items = [
    // Each test plan runs twice (two device layouts), so the unit is a test case, not a plan.
    [dash.valid.toLocaleString(), "test cases solved", `of ${dash.n.toLocaleString()} (each plan with two device layouts)` +
      (dash.blocked ? `; the other ${dash.blocked} have no legal layout` : "")],
    [pct(dash.W), "lower cable cost", "than a greedy baseline with the same number of hubs"],
    [pct(dash.min_hub_share), "at the proven minimum", "number of hubs"],
    [String(dash.mismatches), "disagreements", "between the solver and the independent checker"],
  ];
  stats.replaceChildren(...items.map(([value, label, note]) => {
    const t = document.createElement("div");
    t.className = "tile";
    t.innerHTML = '<div class="tile-value"></div><div class="tile-label"></div><div class="tile-note"></div>';
    t.children[0].textContent = value;
    t.children[1].textContent = label;
    t.children[2].textContent = note;
    return t;
  }));
}

initHome();
