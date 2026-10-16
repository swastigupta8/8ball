// 8ball 3D view: a rotatable 3D model of the floor plan with the cable rings. Read-only add-on to the viewer.
// It never changes solver data: it reads the plan, answer and cuts that app.js already holds
// (window.eightballViewer) and draws them with three.js (bundled in ./vendor, so it works offline).
// app.js calls window.view3d.refresh() after every redraw; this file does nothing until the 3D button is pressed.
//
// Units: plan coordinates are y-up in "plan units" (plan.scale units per metre). The scene is in metres,
// centred on the plan: world X = (x - cx) / s, world Z = -(y - cy) / s, world Y = up.
import * as THREE from "./vendor/three.module.min.js";
import { OrbitControls } from "./vendor/OrbitControls.js";

const V = window.eightballViewer;
const $ = (id) => document.getElementById(id);

const DEFAULTS = {
  wallH: 1.2, wallExtra: 0, cableH: 0.45, thick: 0.035, glow: 1, lightAz: -50, lightEl: 52,
  wallColor: "#f3eee8", floorColor: "#ffffff", cableColor: "#22e0ff", byHub: true,
  pulse: true, labels: false, shadows: true, autoRotate: false,
  zoneFloor: false, invalidFloor: false, relief: 0.4,
};
const S = { ...DEFAULTS };
const CABLE_COLORS = ["#22e0ff", "#ffb347", "#8dff6a", "#ff6fb1", "#c58bff", "#ffe14d", "#5affd2", "#ff7a59"];
const BG = "#1d2724";
const SLAB = 0.18;            // floor slab thickness (m), drawn below y = 0
const UP = new THREE.Vector3(0, 1, 0);

let active = false;
let renderer = null, scene, camera, controls, sun, hemi, raycaster;
let wallMesh = [], glassMesh = [];
const groups = {};
let frame = { cx: 0, cy: 0, s: 1, R: 5 };
let built = { plan: null, answer: null, key: null };
let cableMats = [];
let pulses = [];             // {mesh, halo, ring, kind, i, n, ...}
let rings = [];              // per hub: {hub_id, pts:[Vector3], cum:[m], total, cuts:[m]}
let sparks = [];
let tween = null;
let lastT = 0;
let hoverPending = null;

const SHARED = new Set();
function shared(geo) { SHARED.add(geo); return geo; }
const UNIT_CYL = shared(new THREE.CylinderGeometry(1, 1, 1, 14, 1));
const UNIT_SPHERE = shared(new THREE.SphereGeometry(1, 20, 14));

// ---------- helpers ----------
function clear(group) {
  for (const obj of [...group.children]) {
    group.remove(obj);
    obj.traverse((o) => {
      if (o.geometry && !SHARED.has(o.geometry)) o.geometry.dispose();
      const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
      for (const m of mats) { if (m.map && m.userData.ownMap) m.map.dispose(); m.dispose(); }
    });
  }
}

function toWorld(p, y = 0) { return new THREE.Vector3((p[0] - frame.cx) / frame.s, y, -(p[1] - frame.cy) / frame.s); }

function cleanRing(ring) {
  const pts = [];
  for (const p of ring) {
    const q = pts[pts.length - 1];
    if (!q || Math.abs(q[0] - p[0]) > 1e-6 || Math.abs(q[1] - p[1]) > 1e-6) pts.push(p);
  }
  if (pts.length > 1) {
    const a = pts[0], b = pts[pts.length - 1];
    if (Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6) pts.pop();
  }
  return pts;
}

// polygon = [outer ring, ...holes] in plan units -> THREE.Shape in metres (x, y-up in the shape's own plane)
function shapeOf(poly) {
  const m = (r) => cleanRing(r).map((p) => new THREE.Vector2((p[0] - frame.cx) / frame.s, (p[1] - frame.cy) / frame.s));
  const outer = m(poly[0]);
  if (outer.length < 3) return null;
  const shape = new THREE.Shape(outer);
  for (const h of poly.slice(1)) {
    const pts = m(h);
    if (pts.length >= 3) shape.holes.push(new THREE.Path(pts));
  }
  return shape;
}

// Extrude polygons up from y = 0 to y = depth (the mesh is scaled in Y later), or down for the floor slab.
function extrude(polys, depth, down = false) {
  const shapes = polys.map(shapeOf).filter(Boolean);
  if (!shapes.length) return null;
  const geo = new THREE.ExtrudeGeometry(shapes, { depth, bevelEnabled: false, curveSegments: 4 });
  geo.rotateX(-Math.PI / 2);          // (x, y, z) -> (x, z, -y): shape y becomes world -Z, extrusion goes up
  if (down) geo.translate(0, -depth, 0);
  return geo;
}

function rng(seed) { let a = seed; return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

function woodTexture() {
  const size = 512, planks = 7, w = size / planks, r = rng(7);
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  for (let i = 0; i < planks; i++) {
    const shade = 0.84 + r() * 0.26;
    const joint = Math.floor(r() * size);
    for (const [y0, y1, sh] of [[0, joint, shade], [joint, size, 0.84 + r() * 0.26]]) {
      g.fillStyle = `rgb(${Math.min(255, 196 * sh) | 0},${Math.min(255, 148 * sh) | 0},${Math.min(255, 106 * sh) | 0})`;
      g.fillRect(i * w, y0, w, y1 - y0);
    }
    for (let k = 0; k < 26; k++) {
      g.strokeStyle = r() > 0.5 ? "rgba(255,230,200,.07)" : "rgba(70,35,15,.09)";
      g.lineWidth = 0.6 + r() * 1.2;
      const x = i * w + r() * w;
      g.beginPath(); g.moveTo(x, 0); g.lineTo(x + (r() - 0.5) * 6, size); g.stroke();
    }
    g.fillStyle = "rgba(50,25,10,.45)"; g.fillRect(i * w, joint, w, 1.5);
    g.fillStyle = "rgba(50,25,10,.55)"; g.fillRect(i * w, 0, 1.6, size);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.repeat.set(1 / 1.1, 1 / 1.1);
  if (renderer) tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  return tex;
}

function groundTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 512;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(256, 256, 20, 256, 256, 256);
  grad.addColorStop(0, "#3a4944"); grad.addColorStop(0.5, "#27332f"); grad.addColorStop(1, BG);
  g.fillStyle = grad; g.fillRect(0, 0, 512, 512);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function labelSprite(text, { size = 0.34, color = "#ffffff", bg = "rgba(10,16,14,.62)" } = {}) {
  const c = document.createElement("canvas");
  const g = c.getContext("2d");
  const font = "600 44px system-ui, sans-serif";
  g.font = font;
  const w = Math.ceil(g.measureText(text).width) + 36;
  c.width = w; c.height = 72;
  g.font = font;
  g.fillStyle = bg;
  g.beginPath(); g.roundRect(0, 0, w, 72, 20); g.fill();
  g.fillStyle = color; g.textBaseline = "middle"; g.fillText(text, 18, 38);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
  mat.userData.ownMap = true;
  const sp = new THREE.Sprite(mat);
  sp.scale.set((size * w) / 72, size, 1);
  sp.raycast = () => {};
  return sp;
}

const cableColour = (k) => (S.byHub ? CABLE_COLORS[k % CABLE_COLORS.length] : S.cableColor);

// ---------- renderer and static scene ----------
function ensureRenderer() {
  if (renderer) return true;
  const host = $("view3d");
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  } catch (err) {
    renderer = null;
    return false;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  host.prepend(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(BG);
  camera = new THREE.PerspectiveCamera(32, 1, 0.05, 600);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.screenSpacePanning = true;
  controls.maxPolarAngle = Math.PI / 2 - 0.03;
  controls.autoRotateSpeed = 1.6;
  controls.addEventListener("start", () => { tween = null; });

  hemi = new THREE.HemisphereLight(0xe6eeff, 0x6b5a4c, 1.05);
  scene.add(hemi);
  sun = new THREE.DirectionalLight(0xfff0dc, 2.3);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  sun.shadow.radius = 5;
  scene.add(sun, sun.target);

  for (const name of ["ground", "floor", "tint", "heat", "walls", "cables", "markers", "cuts", "pulses", "labels"]) {
    groups[name] = new THREE.Group();
    scene.add(groups[name]);
  }
  raycaster = new THREE.Raycaster();
  new ResizeObserver(resize).observe(host);
  bindPointer(renderer.domElement);
  return true;
}

function resize() {
  if (!renderer) return;
  const host = $("view3d");
  const w = host.clientWidth, h = host.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  // keep the whole plan in frame when the pane changes shape (e.g. break mode splits the canvas in two)
  const fit = fitDistance();
  if (lastFit && fit && built.plan) {
    const off = camera.position.clone().sub(controls.target).multiplyScalar(fit / lastFit);
    camera.position.copy(controls.target).add(off);
  }
  lastFit = fit;
}

let lastFit = 0;
function fitDistance() {
  const fovV = (camera.fov * Math.PI) / 180;
  const fovH = 2 * Math.atan(Math.tan(fovV / 2) * camera.aspect);
  return (0.86 * frame.R) / Math.sin(Math.min(fovV, fovH) / 2);
}

function updateLight() {
  const az = (S.lightAz * Math.PI) / 180, el = (S.lightEl * Math.PI) / 180;
  const d = frame.R * 3;
  sun.position.set(d * Math.cos(el) * Math.sin(az), d * Math.sin(el), d * Math.cos(el) * Math.cos(az));
  sun.target.position.set(0, 0, 0);
  const r = frame.R * 1.25;
  Object.assign(sun.shadow.camera, { left: -r, right: r, top: r, bottom: -r, near: 0.5, far: d * 2.4 });
  sun.shadow.camera.updateProjectionMatrix();
  sun.castShadow = S.shadows;
  renderer.shadowMap.needsUpdate = true;
}

function buildStatic() {
  const plan = V.state.plan;
  const [minx, miny, maxx, maxy] = plan.bounds;
  frame = { cx: (minx + maxx) / 2, cy: (miny + maxy) / 2, s: plan.scale, R: 0.5 * Math.hypot(maxx - minx, maxy - miny) / plan.scale };
  clear(groups.ground); clear(groups.floor); clear(groups.walls);
  wallMesh = []; glassMesh = []; wallExtra = null; wallMat = null;

  const ground = new THREE.Mesh(
    new THREE.CircleGeometry(frame.R * 7, 64),
    new THREE.MeshStandardMaterial({ map: groundTexture(), roughness: 0.4, metalness: 0.25 }),
  );
  ground.material.userData.ownMap = true;
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -SLAB - 0.002;
  ground.receiveShadow = true;
  groups.ground.add(ground);

  const slabGeo = extrude(plan.inner, SLAB, true);
  if (slabGeo) {
    const top = new THREE.MeshStandardMaterial({ map: woodTexture(), color: S.floorColor, roughness: 0.55, metalness: 0.02 });
    top.userData.ownMap = true;
    const side = new THREE.MeshStandardMaterial({ color: "#2b221c", roughness: 0.8 });
    const slab = new THREE.Mesh(slabGeo, [top, side]);
    slab.receiveShadow = true; slab.castShadow = true;
    slab.name = "floor";
    groups.floor.add(slab);
  }

  const wallGeo = extrude(plan.walls, 1);
  if (wallGeo) {
    wallMat = new THREE.MeshStandardMaterial({ color: S.wallColor, roughness: 0.88 });
    const m = new THREE.Mesh(wallGeo, wallMat);
    m.castShadow = true; m.receiveShadow = true; m.name = "walls";
    groups.walls.add(m); wallMesh.push(m);
    buildWallExtra();
  }
  const glassGeo = extrude(plan.windows || [], 1);
  if (glassGeo) {
    const m = new THREE.Mesh(glassGeo, new THREE.MeshStandardMaterial({
      color: "#a6d8ff", roughness: 0.1, metalness: 0.1, transparent: true, opacity: 0.38, depthWrite: false,
    }));
    m.name = "glass";
    m.raycast = () => {};
    groups.walls.add(m); glassMesh.push(m);
  }
  applyWallHeight();
  updateLight();
  controls.minDistance = Math.max(1, frame.R * 0.25);
  controls.maxDistance = frame.R * 7;
}

function applyWallHeight() {
  for (const m of wallMesh) m.scale.y = S.wallH;
  if (wallExtra) wallExtra.scale.y = S.wallH;
  for (const m of glassMesh) { m.scale.y = S.wallH * 0.97; m.position.y = 0.0; }
}

// "Wall thickness": the plan data has fixed walls, so extra thickness is added as a slim box along every
// edge of every wall outline (t/2 either side), drawn in one instanced mesh with the walls' own material.
let wallExtra = null, wallMat = null;
function buildWallExtra() {
  if (wallExtra) {
    groups.walls.remove(wallExtra);
    wallExtra.geometry.dispose();
    wallExtra.dispose();
    wallExtra = null;
  }
  const t = S.wallExtra;
  if (t < 0.005 || !wallMat) return;
  const edges = [];
  for (const poly of V.state.plan.walls) {
    for (const ring of poly) {
      const pts = cleanRing(ring);
      for (let i = 0; i < pts.length; i++) edges.push([toWorld(pts[i]), toWorld(pts[(i + 1) % pts.length])]);
    }
  }
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), wallMat, edges.length);
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), pos = new THREE.Vector3(), scl = new THREE.Vector3();
  let n = 0;
  for (const [a, b] of edges) {
    const dx = b.x - a.x, dz = b.z - a.z, len = Math.hypot(dx, dz);
    if (len < 1e-4) continue;
    q.setFromAxisAngle(UP, -Math.atan2(dz, dx));
    pos.set((a.x + b.x) / 2, 0.5, (a.z + b.z) / 2);
    scl.set(len + t, 0.9995, t);   // a hair lower than the wall top so the two tops never fight
    mesh.setMatrixAt(n++, m4.compose(pos, q, scl));
  }
  mesh.count = n;
  mesh.instanceMatrix.needsUpdate = true;
  mesh.castShadow = true; mesh.receiveShadow = true;
  mesh.scale.y = S.wallH;
  mesh.raycast = () => {};
  groups.walls.add(mesh);
  wallExtra = mesh;
}

// ---------- floor tint: zone colours and rooms with rule violations ----------
function inRing(p, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
const inPolygon = (p, rings) => inRing(p, rings[0]) && !rings.slice(1).some((h) => inRing(p, h));

// Rooms where the checker found a broken rule: the room containing the violation's location, or, for a
// violation with only a hub, that hub's rooms.
function invalidRoomIds() {
  const st = V.state, out = new Set();
  const zoneRooms = Object.fromEntries((st.answer?.hubs || []).map((h) => [h.hub_id, h.room_ids]));
  for (const v of st.check?.violations || []) {
    const room = v.location ? st.plan.rooms.find((r) => inPolygon(v.location, r.polygon)) : null;
    if (room) out.add(room.room_id);
    else for (const id of zoneRooms[v.hub_id] || []) out.add(id);
  }
  return out;
}

function buildTint() {
  clear(groups.tint);
  const st = V.state;
  const legend = [];
  if (S.zoneFloor || S.invalidFloor) {
    const { zoneOf, colorOf } = V.zoneColors();
    const bad = S.invalidFloor ? invalidRoomIds() : new Set();
    const byColor = {};
    for (const room of st.plan.rooms) {
      const col = bad.has(room.room_id) ? "#ff3b30" : S.zoneFloor && zoneOf[room.room_id] ? colorOf[zoneOf[room.room_id]] : null;
      if (col) (byColor[col] ||= []).push(room.polygon);
    }
    for (const [col, polys] of Object.entries(byColor)) {
      const geo = extrude(polys, 0.004);
      if (!geo) continue;
      const mat = new THREE.MeshStandardMaterial({
        color: col, transparent: true, opacity: 0.55, roughness: 0.7, depthWrite: false,
        polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
      });
      const m = new THREE.Mesh(geo, mat);
      m.position.y = 0.002;
      m.receiveShadow = true;
      m.raycast = () => {};
      groups.tint.add(m);
    }
    if (S.zoneFloor) for (const [hub, col] of Object.entries(colorOf)) legend.push({ color: col, label: `${hub} zone` });
    if (S.invalidFloor) legend.push(bad.size ? { color: "#ff3b30", label: "Room with a rule violation" } : { note: "No rule violations in this plan" });
  }
  tintLegend = legend;
  updateLegend();
}

// ---------- hub cost heatmap as terrain ----------
// Each hub's heatmap is a grid of [x, y, extra J]. Cheap spots (bright in 2D) become valleys; expensive
// spots rise by `relief` metres. relief = 0 gives a flat coloured sheet like the 2D map.
function buildHeat() {
  clear(groups.heat);
  const st = V.state;
  const hms = st.heatmaps || [];
  const on = !!st.layers?.heatmap && hms.length > 0;
  groups.heat.visible = on;
  heatLegend = on ? V.heatRange(hms) : null;
  if (on) {
    const { lo, hi } = heatLegend;
    for (const h of hms) {
      if (!h.points.length) continue;
      const cell = h.step_m * frame.s;
      const x0 = Math.min(...h.points.map((p) => p[0])), y0 = Math.min(...h.points.map((p) => p[1]));
      const at = new Map();
      const pos = [], col = [];
      h.points.forEach(([x, y, v], i) => {
        const k = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
        const w = toWorld([x, y], 0.03 + S.relief * k);
        pos.push(w.x, w.y, w.z);
        const [r, g, b] = V.rampRGB(k);
        const c = new THREE.Color().setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace);
        col.push(c.r, c.g, c.b);
        at.set(`${Math.round((x - x0) / cell)},${Math.round((y - y0) / cell)}`, i);
      });
      const idx = [];
      for (const key of at.keys()) {
        const [ix, iy] = key.split(",").map(Number);
        const a = at.get(key), b = at.get(`${ix + 1},${iy}`), c = at.get(`${ix},${iy + 1}`), d = at.get(`${ix + 1},${iy + 1}`);
        if (b !== undefined && c !== undefined && d !== undefined) idx.push(a, b, d, a, d, c);
        else if (b !== undefined && c !== undefined) idx.push(a, b, c);
        else if (b !== undefined && d !== undefined) idx.push(a, b, d);
        else if (c !== undefined && d !== undefined) idx.push(a, d, c);
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      geo.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
      geo.setIndex(idx);
      geo.computeVertexNormals();
      const surface = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
        vertexColors: true, roughness: 0.55, side: THREE.DoubleSide, transparent: true, opacity: 0.93,
      }));
      surface.castShadow = true; surface.receiveShadow = true;
      surface.raycast = () => {};
      const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: "#ffffff", wireframe: true, transparent: true, opacity: 0.1, depthWrite: false }));
      mesh.position.y = 0.002;
      mesh.raycast = () => {};
      groups.heat.add(surface, mesh);
    }
  }
  updateLegend();
}

// ---------- legend (bottom-left of the 3D view) ----------
let tintLegend = [], heatLegend = null;
function updateLegend() {
  const box = $("v3-legend");
  box.replaceChildren();
  const add = (el) => box.append(el);
  const mk = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
  for (const item of tintLegend) {
    const row = mk("div", "v3-leg-row");
    if (item.color) { const sw = mk("span", "v3-leg-sw"); sw.style.background = item.color; row.append(sw); }
    row.append(mk("span", "", item.label || item.note));
    add(row);
  }
  if (heatLegend) {
    const bar = mk("div", "v3-leg-bar");
    bar.style.background = `linear-gradient(to right, ${V.RAMP.join(", ")})`;
    const ends = mk("div", "v3-leg-ends");
    ends.append(mk("span", "", `+${heatLegend.lo.toFixed(2)} J`), mk("span", "", `+${heatLegend.hi.toFixed(2)} J or more`));
    add(mk("div", "v3-leg-title", "Hub cost: valleys are cheaper hub spots"));
    add(bar); add(ends);
  }
  box.hidden = !box.childNodes.length;
}

// ---------- cables, hubs, nodes, cuts ----------
function tube(a, b, radius, mat) {
  const len = a.distanceTo(b);
  if (len < 1e-4) return null;
  const m = new THREE.Mesh(UNIT_CYL, mat);
  m.position.copy(a).add(b).multiplyScalar(0.5);
  m.quaternion.setFromUnitVectors(UP, b.clone().sub(a).normalize());
  m.scale.set(radius, len, radius);
  return m;
}

function ball(p, radius, mat) {
  const m = new THREE.Mesh(UNIT_SPHERE, mat);
  m.position.copy(p);
  m.scale.setScalar(radius);
  return m;
}

function buildCables() {
  clear(groups.cables);
  cableMats = [];
  const { answer } = V.state;
  if (!answer) return;
  answer.hubs.forEach((h, k) => {
    const col = new THREE.Color(cableColour(k));
    const mat = new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 1, roughness: 0.35, metalness: 0.1 });
    const halo = new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.11, blending: THREE.AdditiveBlending, depthWrite: false });
    cableMats.push({ mat, halo });
    h.legs.forEach((leg, li) => {
      const pts = leg.polyline.map((p) => toWorld(p, S.cableH));
      let len = 0;
      for (let i = 1; i < pts.length; i++) len += pts[i].distanceTo(pts[i - 1]);
      const info = { hub_id: h.hub_id, leg: li + 1, legs: h.legs.length, from: leg.from, to: leg.to, length: len };
      for (let i = 0; i < pts.length; i++) {
        if (i > 0) {
          const t = tube(pts[i - 1], pts[i], S.thick, mat);
          if (t) { t.userData.cable = info; groups.cables.add(t); }
          const g = tube(pts[i - 1], pts[i], S.thick * 2.6, halo);
          if (g) { g.raycast = () => {}; groups.cables.add(g); }
        }
        const j = ball(pts[i], S.thick * 1.05, mat);
        j.userData.cable = info;
        groups.cables.add(j);
      }
    });
  });
  applyGlow();
}

function applyGlow() {
  for (const { halo } of cableMats) halo.opacity = 0.11 * S.glow;
  for (const { mat } of cableMats) mat.emissiveIntensity = 0.25 + 0.4 * S.glow;
}

function nodeStatuses() {
  const st = V.state;
  return st.breakMode && st.answer ? V.loopEffects().status : null;
}

function buildMarkers() {
  clear(groups.markers);
  const st = V.state;
  if (!st.answer) return;
  const status = nodeStatuses();
  const { hubOfNode } = V.zoneColors();
  const hubIndex = Object.fromEntries(st.answer.hubs.map((h, k) => [h.hub_id, k]));
  const poleMat = new THREE.MeshStandardMaterial({ color: "#8a8f94", roughness: 0.5, metalness: 0.5 });
  const pole = (p) => {
    const m = tube(new THREE.Vector3(p.x, 0, p.z), new THREE.Vector3(p.x, p.y, p.z), 0.012, poleMat);
    if (m) { m.castShadow = true; m.raycast = () => {}; groups.markers.add(m); }
  };

  for (const [nid, n] of Object.entries(V.nodePoints())) {
    const p = toWorld(n.point, S.cableH);
    const hub = hubOfNode[nid];
    const lost = status && status[nid] === "lost";
    const alive = status && status[nid] && !lost;
    const base = lost ? "#ff3b30" : alive ? "#38e08a" : cableColour(hubIndex[hub] ?? 0);
    const col = new THREE.Color(base);
    const core = ball(p, 0.1, new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.9, roughness: 0.3 }));
    core.castShadow = true;
    core.userData.tip = { title: `Node ${nid}`, lines: [`room ${n.room_id}`, hub ? `served by ${hub}` : "not served by any hub", ...(status ? [lost ? "cut off: no path to the hub" : "connected"] : [])] };
    const glow = ball(p, 0.2, new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.22 * S.glow, blending: THREE.AdditiveBlending, depthWrite: false }));
    glow.raycast = () => {};
    groups.markers.add(core, glow);
    pole(p);
  }

  st.answer.hubs.forEach((h, k) => {
    const p = toWorld(h.point, S.cableH);
    const col = new THREE.Color(cableColour(k));
    const box = new THREE.Mesh(
      new THREE.BoxGeometry(0.34, 0.2, 0.34),
      new THREE.MeshStandardMaterial({ color: "#20262b", emissive: col, emissiveIntensity: 0.18, roughness: 0.35, metalness: 0.6 }),
    );
    box.position.copy(p);
    box.castShadow = true;
    box.userData.tip = { title: `Hub ${h.hub_id}`, lines: [`in ${h.room_id}`, `${h.node_ids.length} nodes · ${h.area_m2.toFixed(1)} m²`] };
    const led = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.025, 0.2), new THREE.MeshBasicMaterial({ color: col }));
    led.position.set(p.x, p.y + 0.105, p.z);
    led.raycast = () => {};
    const halo = new THREE.Mesh(new THREE.RingGeometry(0.34, 0.46, 40), new THREE.MeshBasicMaterial({
      color: col, transparent: true, opacity: 0.55 * Math.min(1, S.glow), blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    }));
    halo.rotation.x = -Math.PI / 2;
    halo.position.set(p.x, 0.012, p.z);
    halo.raycast = () => {};
    groups.markers.add(box, led, halo);
    pole(p);
  });
}

// Break the cable: a cut is the same plan point app.js keeps in state.cuts.
function buildCuts() {
  clear(groups.cuts);
  sparks = [];
  const st = V.state;
  if (!st.breakMode || !st.answer) return;
  const s = st.plan.scale;
  const red = new THREE.Color("#ff3b30");
  for (const c of st.cuts) {
    const near = V.nearestRingSeg(st.loopModels, c);
    if (!near || near.d > 0.3 * s) continue;
    const p = toWorld(near.q, S.cableH);
    const g = new THREE.Group();
    g.position.copy(p);
    g.userData.cut = true;
    const core = ball(new THREE.Vector3(), 0.075, new THREE.MeshBasicMaterial({ color: red }));
    core.userData.cut = true;
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.2, 0.02, 10, 40), new THREE.MeshBasicMaterial({ color: red, transparent: true, opacity: 0.9 }));
    ring.rotation.x = Math.PI / 2;
    ring.userData.cut = true;
    ring.userData.pulse = true;
    const n = 26;
    const pos = new Float32Array(n * 3);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({
      color: "#ffb25c", size: 0.07, transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    pts.frustumCulled = false;
    pts.raycast = () => {};
    const r = rng(Math.floor(p.x * 997 + p.z * 131));
    const seeds = Array.from({ length: n }, () => ({ a: r() * Math.PI * 2, v: 0.35 + r() * 0.9, up: 0.5 + r() * 1.1, off: r() }));
    sparks.push({ geo, seeds, n });
    g.add(core, ring, pts);
    groups.cuts.add(g);
  }
}

// ---------- travelling pulses (the "cable glow") ----------
function buildPulses() {
  clear(groups.pulses);
  pulses = []; rings = [];
  const st = V.state;
  if (!st.answer) return;
  const s = st.plan.scale;
  const cutsByHub = {};
  if (st.breakMode) {
    for (const c of st.cuts) {
      const near = V.nearestRingSeg(st.loopModels, c);
      if (near && near.d <= 0.3 * s) (cutsByHub[near.model.hub_id] ||= []).push(near.pos / s);
    }
  }
  st.loopModels.forEach((m, k) => {
    const pts = [], cum = [];
    let d = 0;
    m.segs.forEach((seg, i) => {
      if (i === 0) { pts.push(toWorld(seg.a, S.cableH)); cum.push(0); }
      d += Math.hypot(seg.b[0] - seg.a[0], seg.b[1] - seg.a[1]) / s;
      pts.push(toWorld(seg.b, S.cableH)); cum.push(d);
    });
    const cuts = (cutsByHub[m.hub_id] || []).sort((a, b) => a - b);
    const ring = { hub_id: m.hub_id, pts, cum, total: d, cuts, color: new THREE.Color(cableColour(k)) };
    rings.push(ring);
    if (d < 0.5) return;
    const lo = cuts.length ? cuts[0] : d, hi = cuts.length ? cuts[cuts.length - 1] : d;
    const regions = cuts.length ? [{ len: lo, dir: 1, from: 0 }, { len: d - hi, dir: -1, from: d }] : [{ len: d, dir: 1, from: 0 }];
    for (const reg of regions) {
      if (reg.len < 0.4) continue;
      const n = Math.max(1, Math.round(reg.len / 4));
      for (let i = 0; i < n; i++) {
        const core = ball(new THREE.Vector3(), 0.075, new THREE.MeshBasicMaterial({ color: ring.color.clone().lerp(new THREE.Color("#ffffff"), 0.55) }));
        const halo = ball(new THREE.Vector3(), 0.2, new THREE.MeshBasicMaterial({ color: ring.color, transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false }));
        core.raycast = halo.raycast = () => {};
        groups.pulses.add(core, halo);
        pulses.push({ core, halo, ring, reg, i, n });
      }
    }
  });
  groups.pulses.visible = S.pulse;
}

function pointAlong(ring, u) {
  const { cum, pts } = ring;
  let i = 1;
  while (i < cum.length - 1 && cum[i] < u) i++;
  const span = cum[i] - cum[i - 1] || 1;
  return pts[i - 1].clone().lerp(pts[i], Math.max(0, Math.min(1, (u - cum[i - 1]) / span)));
}

// ---------- labels ----------
function buildLabels() {
  clear(groups.labels);
  groups.labels.visible = S.labels;
  const st = V.state;
  for (const room of st.plan.rooms) {
    const sp = labelSprite(room.type.replace(/_/g, " "), { size: 0.4 });
    sp.position.copy(toWorld(room.label_point, 0.08));
    groups.labels.add(sp);
  }
  (st.answer?.hubs || []).forEach((h, k) => {
    const sp = labelSprite(h.hub_id, { size: 0.4, color: cableColour(k) });
    sp.position.copy(toWorld(h.point, S.cableH + 0.4));
    groups.labels.add(sp);
  });
  for (const [nid, n] of Object.entries(V.nodePoints())) {
    const sp = labelSprite(nid, { size: 0.32 });
    sp.position.copy(toWorld(n.point, S.cableH + 0.3));
    groups.labels.add(sp);
  }
}

// ---------- sync with the viewer ----------
function rebuildDynamic() {
  buildCables(); buildMarkers(); buildCuts(); buildPulses(); buildLabels(); buildTint(); buildHeat();
}

function sync() {
  if (!active || !renderer) return;
  const st = V.state;
  if (!st.plan) return;
  const key = `${st.plan.plan_id}|${st.plan.bounds}`;
  if (st.plan !== built.plan) {
    buildStatic();
    rebuildDynamic();
    if (key !== built.key) presetCamera("iso", false);
  } else if (st.answer !== built.answer) {
    rebuildDynamic();
  } else {
    buildMarkers(); buildCuts(); buildPulses();
  }
  built = { plan: st.plan, answer: st.answer, key };
  syncHeatBox();
  const badge = $("v3-badge");
  const title = $("map-loop-title");
  badge.hidden = !(st.breakMode && title.textContent);
  badge.textContent = title.textContent;
  badge.classList.toggle("bad", title.classList.contains("bad"));
}

// ---------- camera ----------
function presetCamera(name, animate = true) {
  const fit = fitDistance();
  lastFit = fit;
  const to = name === "top"
    ? { theta: 0, phi: 0.02, r: fit * 0.95 }
    : { theta: -0.66, phi: 0.82, r: fit * 0.98 };
  const target = new THREE.Vector3(0, 0.15, 0);
  const cur = new THREE.Spherical().setFromVector3(camera.position.clone().sub(controls.target));
  const from = { theta: cur.theta, phi: cur.phi, r: cur.radius, target: controls.target.clone() };
  if (!animate) {
    controls.target.copy(target);
    camera.position.copy(target).add(new THREE.Vector3().setFromSphericalCoords(to.r, to.phi, to.theta));
    controls.update();
    return;
  }
  let dTheta = to.theta - from.theta;
  dTheta = Math.atan2(Math.sin(dTheta), Math.cos(dTheta));
  tween = { t0: performance.now(), dur: 750, from, to, dTheta, target };
}

function stepTween(now) {
  if (!tween) return;
  const k = Math.min(1, (now - tween.t0) / tween.dur);
  const e = 1 - Math.pow(1 - k, 3);
  const { from, to } = tween;
  const phi = Math.max(0.02, from.phi + (to.phi - from.phi) * e);
  const theta = from.theta + tween.dTheta * e;
  const r = from.r + (to.r - from.r) * e;
  controls.target.lerpVectors(from.target, tween.target, e);
  camera.position.copy(controls.target).add(new THREE.Vector3().setFromSphericalCoords(r, phi, theta));
  if (k >= 1) tween = null;
}

// ---------- pointer: hover tips and cutting ----------
function pick(evt) {
  const rect = renderer.domElement.getBoundingClientRect();
  const ndc = new THREE.Vector2(((evt.clientX - rect.left) / rect.width) * 2 - 1, -((evt.clientY - rect.top) / rect.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const targets = [...groups.cuts.children, ...groups.cables.children, ...groups.markers.children];
  return raycaster.intersectObjects(targets, true).find((h) => h.object.userData.cable || h.object.userData.tip || h.object.userData.cut) || null;
}

function bindPointer(canvas) {
  let down = null;
  canvas.addEventListener("pointerdown", (e) => { down = { x: e.clientX, y: e.clientY }; });
  canvas.addEventListener("pointerup", (e) => {
    const moved = down ? Math.abs(e.clientX - down.x) + Math.abs(e.clientY - down.y) : 99;
    down = null;
    if (moved > 5 || e.button !== 0 || !V.state.breakMode) return;
    const hit = pick(e);
    if (!hit) return;
    const p = hit.point;
    V.toggleCutAt([p.x * frame.s + frame.cx, -p.z * frame.s + frame.cy]);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (down || hoverPending) return;
    hoverPending = requestAnimationFrame(() => {
      hoverPending = null;
      const tip = $("v3-tip");
      const hit = active && renderer ? pick(e) : null;
      const o = hit?.object;
      let lines = null;
      if (o?.userData.tip) lines = [o.userData.tip.title, ...o.userData.tip.lines];
      else if (o?.userData.cable) {
        const c = o.userData.cable;
        lines = [`${c.hub_id} · leg ${c.leg} of ${c.legs}`, `${c.from} → ${c.to}`, `${c.length.toFixed(2)} m`, ...(V.state.breakMode ? ["Click to cut this cable"] : [])];
      } else if (o?.userData.cut) lines = ["Cut", "Click to repair"];
      canvas.style.cursor = lines && V.state.breakMode && (o.userData.cable || o.userData.cut) ? "pointer" : "";
      if (!lines) { tip.hidden = true; return; }
      const host = $("view3d").getBoundingClientRect();
      tip.replaceChildren(...lines.map((t, i) => { const d = document.createElement(i ? "div" : "strong"); d.textContent = t; return d; }));
      tip.style.left = `${Math.max(8, Math.min(e.clientX - host.left + 14, host.width - 230))}px`;
      tip.style.top = `${Math.max(8, Math.min(e.clientY - host.top + 14, host.height - 90))}px`;
      tip.hidden = false;
    });
  });
  canvas.addEventListener("pointerleave", () => { $("v3-tip").hidden = true; });
}

// ---------- render loop ----------
function loop(now) {
  if (!active) return;
  requestAnimationFrame(loop);
  const t = now / 1000, dt = Math.min(0.1, t - lastT || 0.016);
  lastT = t;
  stepTween(now);
  controls.autoRotate = S.autoRotate;
  controls.update();

  if (S.pulse) {
    const speed = 1.3;
    const breathe = 1 + 0.18 * Math.sin(t * 2.4);
    for (const { mat } of cableMats) mat.emissiveIntensity = (0.25 + 0.4 * S.glow) * breathe;
    for (const p of pulses) {
      const { reg, ring, i, n } = p;
      const u = (((t * speed + (i * reg.len) / n) % reg.len) + reg.len) % reg.len;
      const pos = pointAlong(ring, reg.dir > 0 ? u : reg.from - u);
      p.core.position.copy(pos);
      p.halo.position.copy(pos);
      p.halo.scale.setScalar(0.17 + 0.06 * Math.sin(t * 6 + i));
    }
  }
  for (const sp of sparks) {
    const a = sp.geo.attributes.position;
    sp.seeds.forEach((s, i) => {
      const age = (t * 1.1 + s.off) % 1;
      a.setXYZ(i, Math.cos(s.a) * s.v * age * 0.5, s.up * age * 0.5 - 0.9 * age * age * 0.5, Math.sin(s.a) * s.v * age * 0.5);
    });
    a.needsUpdate = true;
  }
  for (const g of groups.cuts.children) {
    const r = g.children.find((o) => o.userData.pulse);
    if (r) r.scale.setScalar(1 + 0.25 * Math.sin(t * 5));
  }
  renderer.render(scene, camera);
}

// ---------- UI ----------
const SLIDERS = [
  ["v3-wall", "wallH", (v) => `${v.toFixed(2)} m`, () => { applyWallHeight(); }],
  ["v3-wallx", "wallExtra", (v) => `+${Math.round(v * 100)} cm`, () => { buildWallExtra(); }],
  ["v3-relief", "relief", (v) => `${v.toFixed(2)} m`, () => { buildHeat(); }],
  ["v3-cableh", "cableH", (v) => `${v.toFixed(2)} m`, () => { rebuildDynamic(); }],
  ["v3-thick", "thick", (v) => `${(v * 200).toFixed(1)} cm`, () => { rebuildDynamic(); }],
  ["v3-glow", "glow", (v) => `${Math.round(v * 100)}%`, () => { applyGlow(); buildMarkers(); }],
  ["v3-light-az", "lightAz", (v) => `${Math.round(v)}°`, () => updateLight()],
  ["v3-light-el", "lightEl", (v) => `${Math.round(v)}°`, () => updateLight()],
];

function syncControls() {
  for (const [id, key, fmt] of SLIDERS) {
    const input = $(id);
    input.value = S[key];
    input.nextElementSibling.textContent = fmt(S[key]);
  }
  $("v3-wallcolor").value = S.wallColor;
  $("v3-floorcolor").value = S.floorColor;
  $("v3-cablecolor").value = S.cableColor;
  $("v3-cablecolor").disabled = S.byHub;
  $("v3-byhub").checked = S.byHub;
  $("v3-pulse").checked = S.pulse;
  $("v3-labels").checked = S.labels;
  $("v3-shadows").checked = S.shadows;
  $("v3-rotate").checked = S.autoRotate;
  $("v3-zones").checked = S.zoneFloor;
  $("v3-invalid").checked = S.invalidFloor;
  syncHeatBox();
}

// The heatmap switch is the one that already exists in the heatmap card (state.layers.heatmap), so 2D and 3D agree.
function syncHeatBox() {
  const has = (V.state.heatmaps || []).length > 0;
  const box = $("v3-heat");
  box.checked = has && !!V.state.layers.heatmap;
  box.disabled = !has;
  box.parentElement.title = has ? "Same switch as the heatmap card below" : "This plan has no heatmap data (press Solve)";
}

function bindControls() {
  for (const [id, key, fmt, apply] of SLIDERS) {
    $(id).addEventListener("input", (e) => {
      S[key] = Number(e.target.value);
      e.target.nextElementSibling.textContent = fmt(S[key]);
      if (renderer && built.plan) apply();
    });
  }
  $("v3-wallcolor").addEventListener("input", (e) => { S.wallColor = e.target.value; wallMesh.forEach((m) => m.material.color.set(S.wallColor)); });
  $("v3-floorcolor").addEventListener("input", (e) => { S.floorColor = e.target.value; const f = groups.floor?.children[0]; if (f) f.material[0].color.set(S.floorColor); });
  $("v3-cablecolor").addEventListener("input", (e) => { S.cableColor = e.target.value; if (built.plan) rebuildDynamic(); });
  $("v3-byhub").addEventListener("change", (e) => { S.byHub = e.target.checked; $("v3-cablecolor").disabled = S.byHub; if (built.plan) rebuildDynamic(); });
  $("v3-pulse").addEventListener("change", (e) => { S.pulse = e.target.checked; if (groups.pulses) groups.pulses.visible = S.pulse; });
  $("v3-labels").addEventListener("change", (e) => { S.labels = e.target.checked; if (groups.labels) groups.labels.visible = S.labels; });
  $("v3-shadows").addEventListener("change", (e) => { S.shadows = e.target.checked; if (renderer && built.plan) updateLight(); });
  $("v3-rotate").addEventListener("change", (e) => { S.autoRotate = e.target.checked; });
  $("v3-zones").addEventListener("change", (e) => { S.zoneFloor = e.target.checked; if (renderer && built.plan) buildTint(); });
  $("v3-invalid").addEventListener("change", (e) => { S.invalidFloor = e.target.checked; if (renderer && built.plan) buildTint(); });
  $("v3-heat").addEventListener("change", (e) => {
    const card = $("heat-toggle");
    card.checked = e.target.checked;
    card.dispatchEvent(new Event("change"));   // app.js turns the layer on or off and redraws the 2D map
  });
  $("heat-toggle").addEventListener("change", () => {
    setTimeout(() => {   // after app.js has updated state.layers.heatmap
      syncHeatBox();
      if (renderer && built.plan) buildHeat();
    }, 0);
  });
  document.querySelectorAll("#view3d-section [data-preset]").forEach((b) => b.addEventListener("click", () => renderer && presetCamera(b.dataset.preset)));
  $("v3-reset").addEventListener("click", () => {
    Object.assign(S, DEFAULTS);
    syncControls();
    if (renderer && built.plan) {
      wallMesh.forEach((m) => m.material.color.set(S.wallColor));
      const f = groups.floor?.children[0];
      if (f) f.material[0].color.set(S.floorColor);
      buildWallExtra(); applyWallHeight(); updateLight(); rebuildDynamic();
      groups.labels.visible = S.labels;
    }
  });
}

function setMode(mode) {
  const want3d = mode === "3d";
  if (want3d === active) return;
  const wrap = document.querySelector(".canvas-wrap");
  if (want3d) {
    if (!ensureRenderer()) {
      const msg = $("v3-msg");
      msg.textContent = "3D view needs WebGL, which this browser can't start.";
      msg.hidden = false;
      setTimeout(() => (msg.hidden = true), 4000);
      return;
    }
    active = true;
    wrap.classList.add("mode-3d");
    $("view3d").hidden = false;
    $("view3d-section").hidden = false;
    resize();
    built = { plan: null, answer: null, key: built.key };
    sync();
    lastT = 0;
    requestAnimationFrame(loop);
  } else {
    active = false;
    wrap.classList.remove("mode-3d");
    $("view3d").hidden = true;
    $("view3d-section").hidden = true;
    $("v3-tip").hidden = true;
  }
  $("mode-2d").classList.toggle("on", !want3d);
  $("mode-3d").classList.toggle("on", want3d);
  $("mode-2d").setAttribute("aria-pressed", String(!want3d));
  $("mode-3d").setAttribute("aria-pressed", String(want3d));
  try {
    const url = new URL(location.href);
    if (want3d) url.searchParams.set("view", "3d"); else url.searchParams.delete("view");
    history.replaceState(null, "", url);
  } catch { /* the address bar is only a convenience */ }
}

let firstRefresh = true;
function refresh() {
  const st = V.state;
  $("view-mode").hidden = !st.plan;
  if (firstRefresh && st.plan) {
    firstRefresh = false;
    if (new URL(location.href).searchParams.get("view") === "3d") setMode("3d");
  }
  if (active) sync();
}

if (V) {
  bindControls();
  syncControls();
  $("mode-2d").addEventListener("click", () => setMode("2d"));
  $("mode-3d").addEventListener("click", () => setMode("3d"));
  window.view3d = {
    refresh,
    // test helper: where a plan point (at cable height) appears on screen, in client pixels
    screenOf: (p) => { camera.updateMatrixWorld(); const v = toWorld(p, S.cableH).project(camera); const r = renderer.domElement.getBoundingClientRect(); return [r.left + ((v.x + 1) / 2) * r.width, r.top + ((1 - v.y) / 2) * r.height]; },
    setMode,
    info: () => ({
      active, settings: { ...S },
      cables: groups.cables?.children.length ?? 0, markers: groups.markers?.children.length ?? 0,
      pulses: pulses.length, cuts: groups.cuts?.children.length ?? 0, walls: wallMesh.length,
      frame, camera: camera ? camera.position.toArray() : null,
    }),
  };
  refresh();
}
