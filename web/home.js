// 8ball landing page: a real solved plan in 3D (tilts toward the cursor), floating hubs and devices that the
// pointer pushes away, rising signals, and a three-card switcher (1 / 2 / 3+ hubs) with a spin-and-swap transition.
// Data: web/data/gallery (solved plans). three.js is bundled in ./vendor (offline).
import * as THREE from "./vendor/three.module.min.js";

// The viewer used to live at index.html; old links (?plan=… or ?id=…) still land here, so forward them.
if (/[?&](plan|id)=/.test(location.search)) location.replace(`viewer.html${location.search}`);

const $ = (id) => document.getElementById(id);
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const mobile = () => innerWidth <= 860;
const HUB = ["#5ff0cf", "#f2b680", "#ff8fbd", "#a7b6ff", "#d4a8ff", "#ffe08a"];  // light sources, one per hub
const THEMES = ["theme-1", "theme-2", "theme-3"];
const DEG = Math.PI / 180;  // home page shows the plans only; numbers live on How it works

// ---------- tiny tween ----------
const ease = {
  in: (t) => t * t,
  out: (t) => 1 - (1 - t) * (1 - t),
  back: (s) => (t) => 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2,
};
function tween(ms, fn, onUpdate, onDone) {
  const t0 = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - t0) / ms);
    onUpdate(fn(t));
    if (t < 1) requestAnimationFrame(step); else onDone && onDone();
  };
  requestAnimationFrame(step);
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- pointer ----------
const mouse = { x: 0, y: 0, px: -9999, py: -9999 };
const cur = { x: 0, y: 0 };
addEventListener("pointermove", (e) => {
  mouse.x = e.clientX / innerWidth - 0.5;
  mouse.y = e.clientY / innerHeight - 0.5;
  mouse.px = e.clientX;
  mouse.py = e.clientY;
});
addEventListener("pointerleave", () => { mouse.px = mouse.py = -9999; });

// ---------- the plan in 3D ----------
const planCanvas = $("plan3d");
const planR = new THREE.WebGLRenderer({ canvas: planCanvas, alpha: true, antialias: true });
planR.setPixelRatio(Math.min(devicePixelRatio, 1.75));
planR.outputColorSpace = THREE.SRGBColorSpace;
const planScene = new THREE.Scene();
const planCam = new THREE.PerspectiveCamera(30, 1, 0.1, 400);
const pivot = new THREE.Group();
planScene.add(pivot);
planScene.add(new THREE.HemisphereLight(0xdfeaff, 0x05060a, 0.75));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(-6, 14, 8);
planScene.add(sun);
let planGroup = null, pulses = [];
const SIZE = 10;  // the plan's longer side, in scene units

function cleanRing(ring) {
  const pts = [];
  for (const p of ring) {
    const q = pts[pts.length - 1];
    if (!q || Math.abs(q[0] - p[0]) > 1e-9 || Math.abs(q[1] - p[1]) > 1e-9) pts.push(p);
  }
  const a = pts[0], b = pts[pts.length - 1];
  if (pts.length > 1 && Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9) pts.pop();
  return pts;
}

function buildPlan(plan, answer) {
  const [minx, miny, maxx, maxy] = plan.bounds;
  const cx = (minx + maxx) / 2, cy = (miny + maxy) / 2;
  const k = SIZE / Math.max(maxx - minx, maxy - miny);        // plan units -> scene units
  const m = plan.scale * k;                                    // metres -> scene units
  const v2 = (p) => new THREE.Vector2((p[0] - cx) * k, (p[1] - cy) * k);
  const v3 = (p, h) => new THREE.Vector3((p[0] - cx) * k, h, -(p[1] - cy) * k);
  const shape = (poly) => {
    const outer = cleanRing(poly[0]).map(v2);
    if (outer.length < 3) return null;
    const s = new THREE.Shape(outer);
    for (const h of poly.slice(1)) { const pts = cleanRing(h).map(v2); if (pts.length >= 3) s.holes.push(new THREE.Path(pts)); }
    return s;
  };
  const slab = (polys, depth) => {
    const shapes = polys.map(shape).filter(Boolean);
    if (!shapes.length) return null;
    const g = new THREE.ExtrudeGeometry(shapes, { depth, bevelEnabled: false, curveSegments: 2 });
    g.rotateX(-Math.PI / 2);
    return g;
  };

  const group = new THREE.Group();
  const hubColor = {}, zoneOf = {};
  (answer?.hubs || []).forEach((h, i) => { hubColor[h.hub_id] = new THREE.Color(HUB[i % HUB.length]); h.room_ids.forEach((r) => (zoneOf[r] = h.hub_id)); });

  const shadowTex = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const g = c.getContext("2d"), r = g.createRadialGradient(64, 64, 8, 64, 64, 64);
    r.addColorStop(0, "rgba(0,0,0,.55)"); r.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = r; g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  })();
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry((maxx - minx) * k * 1.5, (maxy - miny) * k * 1.7),
    new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = -0.9;
  group.add(shadow);
  const floor = slab(plan.inner, 0.12 * m);
  if (floor) {
    floor.translate(0, -0.12 * m, 0);
    group.add(new THREE.Mesh(floor, new THREE.MeshStandardMaterial({ color: 0x1b2328, roughness: 0.92 })));
  }
  for (const room of plan.rooms) {
    const zone = zoneOf[room.room_id];
    const s = shape(room.polygon);  // one polygon: [outer ring, ...holes]
    if (!s) continue;
    const g = new THREE.ShapeGeometry(s);
    g.rotateX(-Math.PI / 2);
    const mat = zone
      ? new THREE.MeshBasicMaterial({ color: hubColor[zone], transparent: true, opacity: 0.16, depthWrite: false })
      : new THREE.MeshBasicMaterial({ color: room.eligible ? 0x2a343a : 0x11161a, transparent: true, opacity: 0.9, depthWrite: false });
    const mesh = new THREE.Mesh(g, mat);
    mesh.position.y = 0.004;
    group.add(mesh);
  }
  const walls = slab(plan.walls, 0.95 * m);
  if (walls) group.add(new THREE.Mesh(walls, new THREE.MeshStandardMaterial({ color: 0xeee8de, roughness: 0.5 })));

  pulses = [];
  const cableH = 0.32 * m;
  for (const h of answer?.hubs || []) {
    const color = hubColor[h.hub_id];
    const path = new THREE.CurvePath();
    for (const leg of h.legs) {
      for (let i = 1; i < leg.polyline.length; i++) {
        const a = v3(leg.polyline[i - 1], cableH), b = v3(leg.polyline[i], cableH);
        if (a.distanceTo(b) > 1e-6) path.add(new THREE.LineCurve3(a, b));
      }
    }
    if (!path.curves.length) continue;
    const segs = Math.max(64, path.curves.length * 6);
    group.add(new THREE.Mesh(new THREE.TubeGeometry(path, segs, 0.05 * m, 8, false), new THREE.MeshBasicMaterial({ color })));
    group.add(new THREE.Mesh(new THREE.TubeGeometry(path, segs, 0.16 * m, 8, false),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.16, blending: THREE.AdditiveBlending, depthWrite: false })));
    for (let j = 0; j < 3; j++) {  // signals running round the loop
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.1 * m, 12, 12), new THREE.MeshBasicMaterial({ color: 0xffffff }));
      group.add(dot);
      pulses.push({ dot, path, offset: j / 3, speed: 0.06 + 0.5 / Math.max(4, path.getLength() / m) });
    }
    const hub = new THREE.Mesh(new THREE.BoxGeometry(0.46 * m, 0.46 * m, 0.46 * m),
      new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.65, roughness: 0.3 }));
    hub.position.copy(v3(h.point, cableH));
    group.add(hub);
    const light = new THREE.PointLight(color, 3.2, 3.2 * m * 4, 1.6);
    light.position.copy(v3(h.point, 1.4 * m));
    group.add(light);
  }
  for (const n of plan.nodes) {
    const dev = new THREE.Mesh(new THREE.CylinderGeometry(0.15 * m, 0.17 * m, 0.08 * m, 20),
      new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xffffff, emissiveIntensity: 0.35, roughness: 0.35 }));
    dev.position.copy(v3(n.point, cableH));
    group.add(dev);
  }
  return group;
}

function setPlan(item) {
  if (planGroup) {
    pivot.remove(planGroup);
    planGroup.traverse((o) => { o.geometry?.dispose(); o.material?.dispose(); });
  }
  planGroup = buildPlan(item.plan, item.answer);
  pivot.add(planGroup);
}

function framePlan() {
  const w = planCanvas.clientWidth || innerWidth, h = planCanvas.clientHeight || innerHeight;
  planR.setSize(w, h, false);
  planCam.aspect = w / h;
  // The plan fills ~46% of the width on a desktop, ~88% on a phone; never taller than ~62% of the height.
  let share = 0.92, tall = 0.95;
  planCam.clearViewOffset();
  if (!mobile()) {  // fit the gap right of the description; at the plan's height the right side is open
    const left = document.querySelector(".desc").getBoundingClientRect().right + 28, right = w * 0.94;
    share = Math.min(0.42, (right - left) / w);
    tall = 0.5;
    const dx = ((left + right) / 2 - w / 2) * 0.5;  // halfway to the gap's centre, so it still reads as centred
    planCam.setViewOffset(w, h, -dx, 0, w, h);
  }
  const tanH = Math.tan((planCam.fov * DEG) / 2);
  const d = Math.max(SIZE / (share * 2 * tanH * planCam.aspect), SIZE / (tall * 2 * tanH));
  planCam.position.set(0, d * 0.72, d * 0.7);
  planCam.lookAt(0, 1.1, 0);  // sits a touch below centre, clear of the cards
  planCam.updateProjectionMatrix();
}

// ---------- floating hubs and devices (two flat layers: behind the plan and in front of everything) ----------
function makeLayer(canvas) {
  const r = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  r.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  r.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, -2000, 2000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x0a0a14, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(-300, 500, 600);
  scene.add(key);
  const group = new THREE.Group();
  scene.add(group);
  return { r, scene, cam, group, items: [] };
}
const back = makeLayer($("float-back"));
const front = makeLayer($("float-front"));

// [left %, top %, size px, kind]; kind h = hub cube, d = device puck
// Placed in the clear space around the plan, off the headline, the cards and the side title.
const FRONT = [[47, 17, 60, "h"], [58, 21, 48, "d"], [36, 80, 54, "d"], [84, 53, 62, "h"], [52, 81, 46, "d"], [80, 63, 52, "h"]];
const BACK = [[44, 30, 34, "d"], [61, 62, 30, "h"], [24, 66, 32, "h"], [83, 45, 36, "d"]];

function floaterMesh(kind, size, color) {
  const mat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: kind === "h" ? 0.35 : 0.12,
                                                 roughness: 0.32, metalness: 0.25, transparent: true });
  const geo = kind === "h"
    ? new THREE.BoxGeometry(size * 0.55, size * 0.55, size * 0.55)
    : new THREE.CylinderGeometry(size * 0.42, size * 0.46, size * 0.16, 32);
  const mesh = new THREE.Mesh(geo, mat);
  if (kind === "d") {  // the detector's indicator ring
    const ring = new THREE.Mesh(new THREE.TorusGeometry(size * 0.2, size * 0.035, 10, 32),
      new THREE.MeshBasicMaterial({ color: 0xf2b680, transparent: true }));
    ring.rotation.x = Math.PI / 2;
    ring.position.y = size * 0.085;
    mesh.add(ring);
  }
  return mesh;
}

function fill(layer, spec, palette) {
  const list = mobile() ? spec.slice(0, Math.ceil(spec.length / 2)) : spec;
  list.forEach(([lx, ty, size, kind], i) => {
    const s = mobile() ? size * 0.7 : size;
    const color = kind === "h" ? palette[i % palette.length] : "#f4f1ec";
    const mesh = floaterMesh(kind, s, color);
    mesh.rotation.set(Math.random() * Math.PI, Math.random() * Math.PI, 0);
    layer.group.add(mesh);
    layer.items.push({ mesh, kind, lx, ty, size: s, rx: 0, ry: 0, bx: 0, by: 0, spin: 0.004 + Math.random() * 0.004,
                       axis: new THREE.Vector3(Math.random(), 1, Math.random()).normalize(), phase: i * 0.7,
                       dur: [5, 7, 6, 8, 5.5, 6.5, 9, 11, 10][i % 9], hidden: false });
  });
}

function sizeLayer(layer) {
  const w = innerWidth, h = innerHeight;
  layer.r.setSize(w, h, false);
  Object.assign(layer.cam, { left: -w / 2, right: w / 2, top: h / 2, bottom: -h / 2 });
  layer.cam.updateProjectionMatrix();
}

function stepLayer(layer, t, par, switching) {
  const w = innerWidth, h = innerHeight;
  layer.group.position.set(cur.x * par, -cur.y * par, 0);
  for (const it of layer.items) {
    const baseX = (it.lx / 100 - 0.5) * w + it.bx, baseY = (0.5 - it.ty / 100) * h + it.by;
    if (!switching) {
      const sx = w / 2 + baseX + layer.group.position.x, sy = h / 2 - baseY - layer.group.position.y;
      const dx = mouse.px - sx, dy = mouse.py - sy, dist = Math.hypot(dx, dy);
      let tx = 0, ty = 0, boost = 1;
      if (dist < 320 && dist > 0) {
        const f = (320 - dist) / 320;
        tx = (-dx / dist) * f * 90;
        ty = (dy / dist) * f * 90;
        boost = 1 + f * 5;
      }
      it.rx += (tx - it.rx) * 0.1;
      it.ry += (ty - it.ry) * 0.1;
      const ph = ((t + it.phase) * Math.PI * 2) / it.dur;
      it.mesh.position.set(baseX + it.rx, baseY + it.ry + (reduce ? 0 : Math.sin(ph) * 14), 0);
      it.mesh.rotateOnAxis(it.axis, reduce ? 0 : it.spin * boost);
    }
  }
  layer.r.render(layer.scene, layer.cam);
}

// Switch: every floater implodes to the centre, takes the new plan's colours, and bursts out to a new spot.
async function burst(layer, palette) {
  const jobs = layer.items.map((it, i) => new Promise((done) => {
    const from = it.mesh.position.clone();
    const to = new THREE.Vector3(-layer.group.position.x, -layer.group.position.y, 0);
    tween(500, ease.in, (e) => {
      it.mesh.position.lerpVectors(from, to, e);
      it.mesh.scale.setScalar(1 - 0.9 * e);
      it.mesh.material.opacity = 1 - e;
      it.mesh.rotateOnAxis(it.axis, 0.08);
    }, async () => {
      if (it.kind === "h") { const c = new THREE.Color(palette[i % palette.length]); it.mesh.material.color.copy(c); it.mesh.material.emissive.copy(c); }
      await wait(300);
      const nbx = (Math.random() - 0.5) * 80, nby = (Math.random() - 0.5) * 80;  // small drift keeps them off the copy
      const w = innerWidth, h = innerHeight;
      const end = new THREE.Vector3((it.lx / 100 - 0.5) * w + nbx, (0.5 - it.ty / 100) * h + nby, 0);
      const start = it.mesh.position.clone();
      tween(900, ease.back(1.5), (e) => {
        it.mesh.position.lerpVectors(start, end, e);
        it.mesh.scale.setScalar(Math.max(0.05, 0.1 + 0.9 * e));
        it.mesh.material.opacity = Math.min(1, e * 1.4);
      }, () => { it.bx = nbx; it.by = nby; it.rx = it.ry = 0; done(); });
    });
  }));
  await Promise.all(jobs);
}

// ---------- rising signals ----------
function signal() {
  const s = document.createElement("span");
  const size = 4 + Math.random() * 9, dur = 5 + Math.random() * 6;
  s.className = "signal";
  Object.assign(s.style, { width: `${size}px`, height: `${size}px`, left: `${Math.random() * 100}%`, animationDuration: `${dur}s` });
  s.style.setProperty("--o", (0.4 + Math.random() * 0.45).toFixed(2));
  s.style.setProperty("--drift", `${((Math.random() - 0.5) * 60).toFixed(0)}px`);
  $("signals").appendChild(s);
  setTimeout(() => s.remove(), dur * 1000);
}

// ---------- data, cards and the switch ----------
async function json(url) { try { const r = await fetch(url, { cache: "no-store" }); return r.ok ? r.json() : null; } catch { return null; } }

const state = { items: [], index: 0, switching: false, spin: 0, introAt: Infinity };

function hubsLabel(n) { return `${n} hub${n === 1 ? "" : "s"}`; }


async function select(i) {
  if (state.switching || i === state.index || !state.items[i]) return;
  state.switching = true;
  state.index = i;
  [...$("cards").children].forEach((c, k) => c.setAttribute("aria-pressed", String(k === i)));
  document.body.className = THEMES[Math.min(2, state.items[i].answer.hubs.length - 1)];
  const palette = HUB.slice(0, Math.max(1, state.items[i].answer.hubs.length));
  if (reduce) {
    setPlan(state.items[i]); state.switching = false; return;
  }
  const spinDone = new Promise((done) => {
    tween(600, ease.in, (e) => { state.spin = 360 * e; planCanvas.style.filter = `blur(${14 * e}px)`; }, () => {
      setPlan(state.items[i]);
      tween(1500, ease.back(0.7), (e) => { state.spin = 360 + 360 * e; planCanvas.style.filter = `blur(${14 * (1 - Math.min(1, e))}px)`; },
        () => { state.spin = 0; planCanvas.style.filter = ""; done(); });
    });
  });
  await Promise.all([spinDone, burst(front, palette), burst(back, palette)]);
  state.switching = false;
}

function card(item, i) {
  const btn = document.createElement("button");
  btn.className = "card";
  btn.type = "button";
  btn.setAttribute("aria-pressed", String(i === 0));
  btn.append(planThumbnail(item.plan, item.answer, "thumb"));
  const name = document.createElement("span");
  name.className = "card-name";
  name.textContent = hubsLabel(item.answer.hubs.length);
  btn.append(name);
  btn.addEventListener("click", () => select(i));
  return btn;
}

async function load() {
  const gallery = await json("data/gallery/index.json");
  const solved = (gallery?.plans || []).filter((e) => e.solved && e.valid && e.metrics?.H);
  const picks = [1, 2, 3].map((n) => solved.find((e) => (n < 3 ? e.metrics.H === n : e.metrics.H >= 3))).filter(Boolean);
  const items = await Promise.all(picks.map(async (entry) => {
    const [plan, answer] = await Promise.all([json(`${entry.path}/plan.json`), json(`${entry.path}/answer.json`)]);
    return plan && answer ? { entry, plan, answer } : null;
  }));
  state.items = items.filter(Boolean);
  if (!state.items.length) { document.querySelector(".picker").hidden = true; return; }
  $("cards").replaceChildren(...state.items.map(card));
  document.body.className = THEMES[Math.min(2, state.items[0].answer.hubs.length - 1)];
  const first = HUB.slice(0, Math.max(1, state.items[0].answer.hubs.length));
  for (const layer of [front, back]) layer.items.forEach((it, k) => { if (it.kind === "h") { const c = new THREE.Color(first[k % first.length]); it.mesh.material.color.copy(c); it.mesh.material.emissive.copy(c); } });
  setPlan(state.items[0]);
  state.introAt = performance.now();
  const n = state.items.length;
  $("prev").addEventListener("click", () => select((state.index - 1 + n) % n));
  $("next").addEventListener("click", () => select((state.index + 1) % n));
}

// ---------- layout and the frame loop ----------
function layout() {
  if (mobile()) {
    const r = $("plan-slot").getBoundingClientRect();
    Object.assign(planCanvas.style, { top: `${r.top + scrollY}px`, height: `${r.height}px` });
  } else {
    planCanvas.style.top = planCanvas.style.height = "";
  }
  framePlan();
  sizeLayer(back);
  sizeLayer(front);
}

function frame(now) {
  const t = now / 1000;
  cur.x += (mouse.x - cur.x) * 0.05;
  cur.y += (mouse.y - cur.y) * 0.05;
  pivot.rotation.y = (cur.x * 34 + state.spin) * DEG;
  pivot.rotation.x = cur.y * 14 * DEG;
  const intro = reduce ? 1 : ease.back(1.2)(Math.min(1, Math.max(0, (now - state.introAt) / 1600)));
  pivot.scale.setScalar(0.6 + 0.4 * intro);
  pivot.position.y = (reduce ? 0 : Math.sin((t * Math.PI * 2) / 6) * 0.22) - (1 - intro) * 3;
  for (const p of pulses) p.dot.position.copy(p.path.getPointAt((t * p.speed + p.offset) % 1));
  planR.render(planScene, planCam);
  stepLayer(back, t, -30, state.switching);
  stepLayer(front, t, 60, state.switching);
  requestAnimationFrame(frame);
}

if (!mobile()) fill(front, FRONT, HUB);  // on a phone the front layer would sit on the text
if (!mobile()) fill(back, BACK, HUB);
layout();
addEventListener("resize", layout);
document.fonts?.ready.then(layout);
new ResizeObserver(() => mobile() && layout()).observe(document.querySelector(".hero"));  // the slot moves as fonts and cards load
load().then(layout);
requestAnimationFrame(frame);
if (!reduce) setInterval(signal, 300);
