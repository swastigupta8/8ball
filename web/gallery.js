// 8ball gallery (Person B, B10). Reads data/gallery/index.json (bench/gallery.py) and draws a card per
// plan with a small floor-plan thumbnail (thumb.js); each card opens the plan in the viewer.
"use strict";

function html(tag, attrs = {}, text = null) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== null) n.textContent = text;
  return n;
}

async function initGallery() {
  const index = await fetchJSON("data/gallery/index.json");
  if (!index || !index.plans?.length) {
    document.getElementById("empty").hidden = false;
    return;
  }
  const cards = await Promise.all(index.plans.map(async (e) => {
    const [plan, answer] = await Promise.all([fetchJSON(`${e.path}/plan.json`), e.solved ? fetchJSON(`${e.path}/answer.json`) : null]);
    const a = html("a", { class: "card", href: `viewer.html?plan=${encodeURIComponent(e.path)}` });
    if (plan) a.append(planThumbnail(plan, answer));
    const body = html("div", { class: "card-body" });
    const left = html("div");
    left.append(html("div", { class: "card-title" }, `Plan ${e.plan_id}`),
      html("div", { class: "card-facts" }, `${e.rooms} rooms · ${e.area_m2} m²`));
    const hubs = e.metrics?.H;
    const status = html("div", { class: `card-status ${e.solved && !e.valid ? "bad" : ""}` });
    if (e.solved) {
      status.append(html("b", {}, e.valid ? `cost ${e.metrics?.J?.toFixed(2) ?? "–"}` : "Invalid"),
        document.createTextNode(hubs != null ? `${hubs} hub${hubs === 1 ? "" : "s"}` : ""));
    } else {
      status.append(document.createTextNode("Not solved yet"));
    }
    body.append(left, status);
    a.append(body);
    return a;
  }));
  document.getElementById("cards").replaceChildren(...cards);
}

initGallery();
