// Рейка AR — главный модуль.
import * as G from './geom.js';
import { PaperTracker } from './tracker.js';
import { startCamera, createDemoStream, listCameras, trackCaps, setTorch, setZoom } from './camera.js';
import { TYPES, TYPE_ORDER, Pen, getProp, defaultProps } from './guides.js';
import { KalkaLayer, imageToCanvas, edgesCanvas, tonesCanvas, grayCanvas } from './tracing.js';
import * as store from './store.js';

const VERSION = '1.0';
const $ = (id) => document.getElementById(id);
const video = $('video'), glCanvas = $('gl'), overlay = $('overlay');
const octx = overlay.getContext('2d');
const tracker = new PaperTracker();
const kalkaLayer = new KalkaLayer(glCanvas);

const FORMATS = { A6: [105, 148], A5: [148, 210], A4: [210, 297], A3: [297, 420], Letter: [216, 279] };
const COLORS = ['#39ff14', '#ff2fd6', '#00e5ff', '#ffe600', '#ff3b30', '#ffffff', '#111111'];
const IS_APP = /ReykaAndroid/.test(navigator.userAgent);

// ---------- Состояние (сохраняется) ----------
const DEFAULT = () => ({
  v: 1,
  settings: { color: '#39ff14', width: 3, halo: true, alpha: 1, labels: true, magnet: true, rot: 0, mirror: false, wake: true, cameraId: null },
  paper: { format: 'A4', orient: 'auto', customW: 200, customH: 200, tracking: true },
  corners: null, cornersFor: null, landscape: false,
  guides: [], nextId: 1,
  kalka: { has: false, show: true, mode: 'orig', opacity: 0.6, detail: 0.45, thick: 2, levels: 3, color: '#ff2fd6', grid: false, cols: 4, part: false, cell: 0, cx: 0, cy: 0, scale: 1, rot: 0, flip: false, imgW: 0, imgH: 0 },
});

let S = mergeDeep(DEFAULT(), store.loadState() || {});

function mergeDeep(base, over) {
  for (const k of Object.keys(over || {})) {
    if (over[k] && typeof over[k] === 'object' && !Array.isArray(over[k]) && base[k] && typeof base[k] === 'object' && !Array.isArray(base[k])) mergeDeep(base[k], over[k]);
    else base[k] = over[k];
  }
  return base;
}

// ---------- Состояние (временное) ----------
const R = {
  W: 1, H: 1, DPR: 1,
  cam: null, vw: 0, vh: 0,
  zoom: 1, panX: 0, panY: 0,
  M: G.I3(), Minv: G.I3(), P2S: null, S2P: null, pw: 210, ph: 297,
  selected: null, mode: 'normal', kalkaEdit: false, clean: false,
  track: 'none', trackReason: '', lastDetect: 0, lostFrames: 0, pending: null, pendingCount: 0, forceCalib: false,
  paths: [], dots: [], undo: [], panel: null,
  pointers: new Map(), down: null, pinch: null, lastTap: 0, snapPt: null,
  kalkaSrc: null, kalkaReady: false, dirty: false, wake: null,
};

// ---------- Утилиты ----------
function toast(msg, ms = 2600) {
  const t = $('toast');
  t.textContent = msg; t.classList.remove('hidden');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add('hidden'), ms);
}
function persist() { R.dirty = true; }
setInterval(() => { if (R.dirty) { R.dirty = false; store.saveState(S); } }, 1200);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') { store.saveState(S); return; }
  keepAwake();
  // Система могла остановить камеру, пока приложение было свёрнуто.
  if (R.cam && !R.cam.demo && R.cam.track && R.cam.track.readyState === 'ended') startSource(false);
});

function pushUndo() {
  R.undo.push(JSON.stringify(S.guides));
  if (R.undo.length > 60) R.undo.shift();
}
function undo() {
  if (!R.undo.length) { toast('Нечего отменять'); return; }
  S.guides = JSON.parse(R.undo.pop());
  if (!S.guides.find(g => g.id === R.selected)) R.selected = null;
  persist(); refreshPanel();
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'html') e.innerHTML = v;
    else if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}

// ---------- Размеры и вид ----------
function resize() {
  R.DPR = Math.min(window.devicePixelRatio || 1, 2.5);
  R.W = window.innerWidth; R.H = window.innerHeight;
  for (const c of [overlay, glCanvas]) { c.width = Math.round(R.W * R.DPR); c.height = Math.round(R.H * R.DPR); }
  computeView();
}
window.addEventListener('resize', resize);

function computeView() {
  if (!R.vw) return;
  const rot = S.settings.rot || 0;
  const rw = rot % 180 ? R.vh : R.vw, rh = rot % 180 ? R.vw : R.vh;
  const fit = Math.min(R.W / rw, R.H / rh);
  let M = G.translate(-R.vw / 2, -R.vh / 2);
  if (S.settings.mirror) M = G.mul(G.scale(-1, 1), M);
  M = G.mul(G.rotate(rot * Math.PI / 180), M);
  M = G.mul(G.scale(fit * R.zoom), M);
  M = G.mul(G.translate(R.W / 2 + R.panX, R.H / 2 + R.panY), M);
  R.M = M; R.Minv = G.inv(M);
  video.style.width = R.vw + 'px'; video.style.height = R.vh + 'px';
  video.style.transform = `matrix(${M[0]},${M[3]},${M[1]},${M[4]},${M[2]},${M[5]})`;
}

function paperDims() {
  let w, h;
  if (S.paper.format === 'custom') { w = +S.paper.customW || 200; h = +S.paper.customH || 200; }
  else [w, h] = FORMATS[S.paper.format] || FORMATS.A4;
  const land = S.paper.orient === 'auto' ? S.landscape : S.paper.orient === 'land';
  return land ? [Math.max(w, h), Math.min(w, h)] : [Math.min(w, h), Math.max(w, h)];
}

const toScreen = (p) => { const r = G.apply(R.P2S, p.x, p.y); return { x: r.x, y: r.y }; };
const toPaper = (s) => { const r = G.apply(R.S2P, s.x, s.y); return { x: r.x, y: r.y }; };
const vToS = (p) => { const r = G.apply(R.M, p.x, p.y); return { x: r.x, y: r.y }; };
const sToV = (p) => { const r = G.apply(R.Minv, p.x, p.y); return { x: r.x, y: r.y }; };

// Порядок углов: по часовой на экране, первый — левый верхний на экране.
function orderCornersScreen(cv) {
  const sc = cv.map(vToS);
  const cx = sc.reduce((a, p) => a + p.x, 0) / 4, cy = sc.reduce((a, p) => a + p.y, 0) / 4;
  let idx = [0, 1, 2, 3].sort((a, b) => Math.atan2(sc[a].y - cy, sc[a].x - cx) - Math.atan2(sc[b].y - cy, sc[b].x - cx));
  let start = 0, best = Infinity;
  idx.forEach((k, j) => { const v = sc[k].x + sc[k].y; if (v < best) { best = v; start = j; } });
  idx = idx.slice(start).concat(idx.slice(0, start));
  return idx.map(k => ({ ...cv[k] }));
}

function updateLandscape(c) {
  const e01 = G.dist(c[0], c[1]) + G.dist(c[2], c[3]);
  const e12 = G.dist(c[1], c[2]) + G.dist(c[3], c[0]);
  S.landscape = e01 > e12;
}

// Совместить порядок новых углов с предыдущими (4 сдвига × 2 направления).
function matchOrder(c, prev) {
  let best = null, bestD = Infinity;
  for (const dirn of [1, -1]) for (let s = 0; s < 4; s++) {
    const cand = [0, 1, 2, 3].map(i => c[((s + dirn * i) % 4 + 4) % 4]);
    const d = cand.reduce((a, p, i) => a + G.dist(p, prev[i]), 0);
    if (d < bestD) { bestD = d; best = cand; }
  }
  return best;
}

function defaultCorners() {
  // Прямоугольник по центру экрана с пропорцией листа.
  const [pw, ph] = paperDims();
  const availW = R.W * 0.72, availH = R.H * 0.62;
  const k = Math.min(availW / pw, availH / ph);
  const w = pw * k, h = ph * k, cx = R.W / 2, cy = R.H / 2;
  const sc = [{ x: cx - w / 2, y: cy - h / 2 }, { x: cx + w / 2, y: cy - h / 2 }, { x: cx + w / 2, y: cy + h / 2 }, { x: cx - w / 2, y: cy + h / 2 }];
  return sc.map(sToV);
}

function getCorners() {
  if (S.corners && S.cornersFor && (S.cornersFor.w !== R.vw || S.cornersFor.h !== R.vh)) {
    // Поменялось разрешение камеры: пересчитываем пропорционально.
    const kx = R.vw / S.cornersFor.w, ky = R.vh / S.cornersFor.h;
    S.corners = S.corners.map(p => ({ x: p.x * kx, y: p.y * ky }));
    S.cornersFor = { w: R.vw, h: R.vh };
  }
  return S.corners || defaultCorners();
}

function setCorners(c) { S.corners = c.map(p => ({ x: p.x, y: p.y })); S.cornersFor = { w: R.vw, h: R.vh }; persist(); }

function updateMatrices() {
  const [pw, ph] = paperDims();
  R.pw = pw; R.ph = ph;
  const c = getCorners();
  const H = G.homography([{ x: 0, y: 0 }, { x: pw, y: 0 }, { x: pw, y: ph }, { x: 0, y: ph }], c);
  R.P2S = H ? G.mul(R.M, H) : null;
  R.S2P = R.P2S ? G.inv(R.P2S) : null;
}

// ---------- Слежение за листом ----------
function setTrack(state, reason = '') {
  if (R.track === state && R.trackReason === reason) return;
  R.track = state; R.trackReason = reason;
  const pill = $('statusPill');
  pill.dataset.state = state;
  const map = {
    none: 'Лист не задан',
    tracking: 'Лист: слежу',
    locked: 'Лист закреплён',
    lost: 'Лист потерян',
    calib: 'Углы листа: перетащи',
  };
  $('statusText').textContent = map[state] || state;
  if (R.panel === 'sheet') refreshPanel();
}

function trackStep(now) {
  if (R.mode === 'calib') { setTrack('calib'); return; }
  if (!S.paper.tracking) { setTrack(S.corners ? 'locked' : 'none'); return; }
  if (now - R.lastDetect < 85) return;
  R.lastDetect = now;
  const res = tracker.detect(video, R.vw, R.vh);
  if (!res) {
    R.lostFrames++;
    if (R.lostFrames > 8) setTrack(S.corners ? 'lost' : 'none', tracker.lastReason);
    return;
  }
  let c = res.corners;
  if (!S.corners || R.forceCalib) {
    c = orderCornersScreen(c);
    updateLandscape(c);
    setCorners(c);
    if (R.forceCalib) toast('Лист найден ✓');
    R.forceCalib = false; R.lostFrames = 0; R.pending = null;
    setTrack('tracking');
    return;
  }
  const prev = S.corners;
  c = matchOrder(c, prev);
  const diag = Math.hypot(R.vw, R.vh);
  const maxD = Math.max(...c.map((p, i) => G.dist(p, prev[i])));
  if (maxD > diag * 0.12) {
    // Резкий скачок: принимаем, только если 3 кадра подряд показывают то же самое.
    if (R.pending && c.every((p, i) => G.dist(p, R.pending[i]) < diag * 0.03)) R.pendingCount++;
    else { R.pending = c; R.pendingCount = 1; }
    if (R.pendingCount >= 3) { setCorners(c); R.pending = null; }
    return;
  }
  R.pending = null;
  // Мелкое дрожание гасим сильно, заметное движение догоняем быстро.
  const dead = diag * 0.0025;
  const a = maxD < dead ? 0.2 : maxD < dead * 4 ? 0.45 : 0.8;
  S.corners = prev.map((p, i) => ({ x: p.x + (c[i].x - p.x) * a, y: p.y + (c[i].y - p.y) * a }));
  S.cornersFor = { w: R.vw, h: R.vh };
  persist();
  R.lostFrames = 0;
  setTrack('tracking');
}

// ---------- Калька: геометрия ----------
function kalkaA() {
  const k = S.kalka;
  let m = G.translate(-k.imgW / 2, -k.imgH / 2);
  if (k.flip) m = G.mul(G.scale(-1, 1), m);
  m = G.mul(G.scale(k.scale), m);
  m = G.mul(G.rotate(k.rot), m);
  return G.mul(G.translate(k.cx, k.cy), m);
}
function kalkaCellRect() {
  const k = S.kalka, cell = k.imgW / k.cols, rows = Math.ceil(k.imgH / cell - 1e-6);
  const total = k.cols * rows, i = ((k.cell % total) + total) % total;
  const cx = i % k.cols, cy = Math.floor(i / k.cols);
  return { cell, rows, total, i, cx, cy, x0: cx * cell, y0: cy * cell, x1: Math.min(k.imgW, (cx + 1) * cell), y1: Math.min(k.imgH, (cy + 1) * cell) };
}
const cellName = (cx, cy) => String.fromCharCode(65 + (cx % 26)) + (cy + 1);

function fitKalka() {
  const k = S.kalka;
  if (!k.imgW) return;
  const m = 0.92;
  const rotated = Math.abs(Math.sin(k.rot)) > 0.7;
  const iw = rotated ? k.imgH : k.imgW, ih = rotated ? k.imgW : k.imgH;
  k.scale = Math.min(R.pw * m / iw, R.ph * m / ih);
  k.cx = R.pw / 2; k.cy = R.ph / 2;
  persist();
}

let kalkaTimer = 0;
function rebuildKalka(delay = 120) {
  clearTimeout(kalkaTimer);
  kalkaTimer = setTimeout(() => {
    if (!R.kalkaSrc) return;
    const k = S.kalka;
    let c = R.kalkaSrc;
    if (k.mode === 'edges') c = edgesCanvas(R.kalkaSrc, { detail: k.detail, thick: k.thick, color: k.color });
    else if (k.mode === 'tones') c = tonesCanvas(R.kalkaSrc, { levels: k.levels });
    else if (k.mode === 'gray') c = grayCanvas(R.kalkaSrc);
    kalkaLayer.setImage(c);
    R.kalkaReady = true;
  }, delay);
}

async function loadKalkaBlob(blob, isNew) {
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    img.decoding = 'async';
    await new Promise((res, rej) => { img.onload = res; img.onerror = () => rej(new Error('Не удалось открыть картинку')); img.src = url; });
    R.kalkaSrc = imageToCanvas(img);
    const k = S.kalka;
    k.imgW = R.kalkaSrc.width; k.imgH = R.kalkaSrc.height; k.has = true;
    if (isNew) { k.rot = 0; k.flip = false; k.cell = 0; k.show = true; updateMatrices(); fitKalka(); }
    rebuildKalka(0);
    persist();
  } finally { URL.revokeObjectURL(url); }
}

$('fileInput').addEventListener('change', async (e) => {
  const f = e.target.files && e.target.files[0];
  e.target.value = '';
  if (!f) return;
  try {
    await store.putFile('kalka', f);
    await loadKalkaBlob(f, true);
    toast('Картинка на листе. Её можно подвинуть: «Двигать и масштабировать».');
    refreshPanel();
  } catch (err) { toast(err.message || 'Ошибка картинки'); }
});

// ---------- Отрисовка ----------
const clipBig = () => ({ x0: -R.pw * 0.6, y0: -R.ph * 0.6, x1: R.pw * 1.6, y1: R.ph * 1.6 });

function colorOf(g) { return (g && g.color) || S.settings.color; }

function strokePaths(paths, dots) {
  const w = S.settings.width;
  const style = (layer, selected) => {
    if (layer === 'aux') return { w: Math.max(1, w * 0.55), a: 0.8, dash: null };
    if (layer === 'ghost') return { w: Math.max(1, w * 0.7), a: 0.6, dash: [8, 6] };
    return { w: selected ? w + 1 : w, a: 1, dash: null };
  };
  const byId = new Map(S.guides.map(g => [g.id, g]));
  const trace = (p) => { octx.beginPath(); p.pts.forEach((q, i) => i ? octx.lineTo(q.x, q.y) : octx.moveTo(q.x, q.y)); if (p.closed) octx.closePath(); };
  octx.lineJoin = 'round'; octx.lineCap = 'round';
  if (S.settings.halo) {
    for (const p of paths) {
      const st = style(p.layer, p.id === R.selected);
      const col = colorOf(byId.get(p.id));
      octx.strokeStyle = col === '#111111' ? 'rgba(255,255,255,0.55)' : 'rgba(0,0,0,0.5)';
      octx.globalAlpha = S.settings.alpha * st.a;
      octx.lineWidth = st.w + 2.6;
      octx.setLineDash(st.dash || []);
      trace(p); octx.stroke();
    }
  }
  for (const p of paths) {
    const st = style(p.layer, p.id === R.selected);
    octx.strokeStyle = p.color || colorOf(byId.get(p.id));
    octx.globalAlpha = S.settings.alpha * st.a;
    octx.lineWidth = st.w;
    octx.setLineDash(st.dash || []);
    trace(p); octx.stroke();
  }
  octx.setLineDash([]);
  for (const d of dots) {
    octx.globalAlpha = S.settings.alpha;
    octx.fillStyle = d.color || colorOf(byId.get(d.id));
    octx.beginPath(); octx.arc(d.x, d.y, Math.max(2.5, w * 0.9), 0, Math.PI * 2); octx.fill();
  }
  octx.globalAlpha = 1;
}

function drawLabels(labels) {
  octx.textAlign = 'center'; octx.textBaseline = 'middle';
  for (const l of labels) {
    if (l.small) {
      octx.font = '700 10px system-ui, sans-serif';
      octx.fillStyle = 'rgba(0,229,255,0.9)';
      octx.strokeStyle = 'rgba(0,0,0,0.7)'; octx.lineWidth = 3;
      octx.strokeText(l.text, l.x, l.y); octx.fillText(l.text, l.x, l.y);
      continue;
    }
    octx.font = '600 12px system-ui, sans-serif';
    const tw = octx.measureText(l.text).width + 12;
    octx.fillStyle = 'rgba(0,0,0,0.62)';
    roundRect(l.x - tw / 2, l.y - 10, tw, 20, 7); octx.fill();
    octx.fillStyle = '#fff';
    octx.fillText(l.text, l.x, l.y + 0.5);
  }
}

function roundRect(x, y, w, h, r) {
  octx.beginPath();
  octx.moveTo(x + r, y); octx.arcTo(x + w, y, x + w, y + h, r); octx.arcTo(x + w, y + h, x, y + h, r);
  octx.arcTo(x, y + h, x, y, r); octx.arcTo(x, y, x + w, y, r); octx.closePath();
}

function drawHandle(p, color, kind = 'pt') {
  octx.lineWidth = 2.5;
  octx.fillStyle = 'rgba(255,255,255,0.22)';
  octx.strokeStyle = '#fff';
  octx.beginPath();
  if (kind === 'move') { roundRect(p.x - 12, p.y - 12, 24, 24, 6); } else octx.arc(p.x, p.y, 12, 0, Math.PI * 2);
  octx.fill(); octx.stroke();
  octx.fillStyle = color;
  octx.beginPath(); octx.arc(p.x, p.y, 4.5, 0, Math.PI * 2); octx.fill();
}

function guideHandles(g) {
  const T = TYPES[g.type];
  return T.handles(g);
}
function isMoveHandle(g, i) {
  return ((g.type === 'circle' || g.type === 'ellipse' || g.type === 'polygon' || g.type === 'grid' || g.type === 'radial') && i === 0) ||
    (g.type === 'rect' && i === 3) || (g.type === 'pellipse' && i === 4);
}

function render() {
  octx.setTransform(R.DPR, 0, 0, R.DPR, 0, 0);
  octx.clearRect(0, 0, R.W, R.H);
  if (!R.P2S || !R.S2P) { kalkaLayer.clear(); return; }

  // Калька (WebGL)
  const k = S.kalka;
  if (k.has && k.show && R.kalkaReady) {
    const A = kalkaA();
    const F = G.mulAll([1, 0, 0, 0, -1, glCanvas.height, 0, 0, 1], G.scale(R.DPR), R.P2S, A, G.scale(k.imgW, k.imgH));
    const inv = G.inv(F);
    let crop = [0, 0, 1, 1];
    if (k.part) { const c = kalkaCellRect(); crop = [c.x0 / k.imgW, c.y0 / k.imgH, c.x1 / k.imgW, c.y1 / k.imgH]; }
    kalkaLayer.draw(inv, k.opacity, crop);
  } else kalkaLayer.clear();

  // Контур листа
  const sheet = [{ x: 0, y: 0 }, { x: R.pw, y: 0 }, { x: R.pw, y: R.ph }, { x: 0, y: R.ph }].map(toScreen);
  octx.lineWidth = R.mode === 'calib' ? 2 : 1.2;
  octx.strokeStyle = R.mode === 'calib' ? '#ff2fd6' : R.track === 'tracking' ? 'rgba(57,255,20,0.55)' : 'rgba(255,255,255,0.35)';
  octx.setLineDash(R.mode === 'calib' ? [] : [6, 6]);
  octx.beginPath(); sheet.forEach((p, i) => i ? octx.lineTo(p.x, p.y) : octx.moveTo(p.x, p.y)); octx.closePath(); octx.stroke();
  octx.setLineDash([]);

  const ctx = { W: R.pw, H: R.ph, rect: { x0: 0, y0: 0, x1: R.pw, y1: R.ph }, labels: S.settings.labels && !R.clean };
  const pen = new Pen(R.P2S, clipBig());
  for (const g of S.guides) {
    if (g.hidden) continue;
    pen.guideId = g.id;
    try { TYPES[g.type].draw(pen, g, ctx); } catch (e) { console.warn(e); }
  }
  // Зеркальные копии от осей симметрии
  for (const sym of S.guides) {
    if (sym.type !== 'symmetry' || sym.hidden || !getProp(sym, 'mirror')) continue;
    pen.mirror = { a: sym.pts[0], b: sym.pts[1] }; pen.layerOverride = 'ghost';
    for (const g of S.guides) {
      if (g === sym || g.type === 'symmetry' || g.hidden) continue;
      pen.guideId = g.id;
      const before = pen.paths.length;
      TYPES[g.type].draw(pen, g, { ...ctx, labels: false });
      for (let i = before; i < pen.paths.length; i++) { pen.paths[i].ghostOf = g.id; pen.paths[i].id = null; pen.paths[i].color = colorOf(g); }
    }
    pen.mirror = null; pen.layerOverride = null;
  }
  // Сетка кальки
  if (k.has && k.show && (k.grid || k.part)) {
    const kp = new Pen(G.mul(R.P2S, kalkaA()), { x0: -1e6, y0: -1e6, x1: 1e6, y1: 1e6 });
    const c = kalkaCellRect();
    const color = k.mode === 'edges' ? '#ffffff' : '#00e5ff';
    if (k.grid) {
      for (let j = 0; j <= k.cols; j++) kp.seg({ x: Math.min(k.imgW, j * c.cell), y: 0 }, { x: Math.min(k.imgW, j * c.cell), y: k.imgH }, 'aux');
      for (let i = 0; i <= c.rows; i++) kp.seg({ x: 0, y: Math.min(k.imgH, i * c.cell) }, { x: k.imgW, y: Math.min(k.imgH, i * c.cell) }, 'aux');
    }
    if (k.part) kp.poly([{ x: c.x0, y: c.y0 }, { x: c.x1, y: c.y0 }, { x: c.x1, y: c.y1 }, { x: c.x0, y: c.y1 }], true, 'main');
    for (const p of kp.paths) p.color = color;
    pen.paths.push(...kp.paths);
    if (k.grid && !R.clean) {
      const lbl = [];
      for (let cy = 0; cy < c.rows; cy++) for (let cx = 0; cx < k.cols; cx++) {
        const s = G.apply(G.mul(R.P2S, kalkaA()), cx * c.cell + Math.min(c.cell * 0.18, k.imgW * 0.04), Math.min(k.imgH, cy * c.cell + Math.min(c.cell * 0.14, k.imgH * 0.04)));
        if (s.w > 0) lbl.push({ x: s.x, y: s.y, text: cellName(cx, cy) });
      }
      if (lbl.length <= 80) pen.labels.push(...lbl.map(l => ({ ...l, small: true })));
    }
  }

  R.paths = pen.paths; R.dots = pen.points;
  strokePaths(pen.paths, pen.points);
  drawLabels(pen.labels);

  if (R.clean) return;

  // Ручки выбранной направляющей
  const sel = S.guides.find(g => g.id === R.selected);
  if (sel) guideHandles(sel).forEach((p, i) => drawHandle(toScreen(p), colorOf(sel), isMoveHandle(sel, i) ? 'move' : 'pt'));

  // Ручки кальки
  if (R.kalkaEdit && k.has) {
    const hs = kalkaHandles();
    octx.strokeStyle = '#fff'; octx.lineWidth = 1.5; octx.setLineDash([5, 5]);
    octx.beginPath(); hs.box.forEach((p, i) => i ? octx.lineTo(p.x, p.y) : octx.moveTo(p.x, p.y)); octx.closePath(); octx.stroke();
    octx.beginPath(); octx.moveTo(hs.topMid.x, hs.topMid.y); octx.lineTo(hs.rot.x, hs.rot.y); octx.stroke();
    octx.setLineDash([]);
    drawHandle(hs.scale, '#00e5ff'); drawHandle(hs.rot, '#ffe600'); drawHandle(hs.center, '#ff2fd6', 'move');
  }

  // Углы при ручной настройке
  if (R.mode === 'calib') {
    getCorners().map(vToS).forEach((p, i) => {
      drawHandle(p, '#ff2fd6');
      octx.fillStyle = '#fff'; octx.font = '700 12px system-ui'; octx.textAlign = 'center';
      octx.fillText(String(i + 1), p.x, p.y - 20);
    });
  }

  if (R.snapPt) {
    octx.strokeStyle = '#ffe600'; octx.lineWidth = 2;
    octx.beginPath(); octx.arc(R.snapPt.x, R.snapPt.y, 18, 0, Math.PI * 2); octx.stroke();
  }
}

function kalkaHandles() {
  const k = S.kalka, A = G.mul(R.P2S, kalkaA());
  const m = (x, y) => { const r = G.apply(A, x, y); return { x: r.x, y: r.y }; };
  const off = Math.max(k.imgW, k.imgH) * 0.1;
  return {
    box: [m(0, 0), m(k.imgW, 0), m(k.imgW, k.imgH), m(0, k.imgH)],
    scale: m(k.imgW, k.imgH), topMid: m(k.imgW / 2, 0), rot: m(k.imgW / 2, -off), center: m(k.imgW / 2, k.imgH / 2),
  };
}

// ---------- Главный цикл ----------
function frame(now) {
  requestAnimationFrame(frame);
  if (!R.vw) return;
  if (video.videoWidth && (video.videoWidth !== R.vw || video.videoHeight !== R.vh)) onVideoSize();
  trackStep(now);
  updateMatrices();
  render();
}

function onVideoSize() {
  const nw = video.videoWidth, nh = video.videoHeight;
  if (!nw || !nh) return;
  const swapped = R.vw && (nw !== R.vw || nh !== R.vh) && S.corners && S.cornersFor && Math.abs(nw / nh - S.cornersFor.w / S.cornersFor.h) > 0.05;
  R.vw = nw; R.vh = nh;
  if (swapped) { S.corners = null; R.forceCalib = true; toast('Камера повернулась — ищу лист заново'); }
  computeView();
}

// ---------- Камера ----------
async function startSource(demo) {
  $('startError').classList.add('hidden');
  try {
    if (R.cam) { R.cam.stop(); R.cam = null; }
    R.cam = demo ? createDemoStream(R.H > R.W) : await startCamera(S.settings.cameraId);
    video.srcObject = R.cam.stream;
    await video.play().catch(() => { });
    await new Promise((res) => { if (video.videoWidth) res(); else video.onloadedmetadata = () => res(); setTimeout(res, 3000); });
    R.vw = 0;
    onVideoSize();
    $('start').classList.add('hidden');
    keepAwake();
    if (!S.corners) toast(demo ? 'Демо: ищу лист…' : 'Ищу лист в кадре…');
    if (S.kalka.has && !R.kalkaSrc) {
      const b = await store.getFile('kalka');
      if (b) loadKalkaBlob(b, false).catch(() => { });
      else S.kalka.has = false;
    }
  } catch (err) {
    const e = $('startError');
    e.textContent = 'Камера не запустилась: ' + (err && err.name === 'NotAllowedError' ? 'нет разрешения. Разреши доступ к камере в настройках браузера.' : (err.message || err));
    e.classList.remove('hidden');
  }
}

async function keepAwake() {
  try {
    if (!S.settings.wake) { if (R.wake) { await R.wake.release(); R.wake = null; } return; }
    if ('wakeLock' in navigator && document.visibilityState === 'visible' && !R.wake) {
      R.wake = await navigator.wakeLock.request('screen');
      R.wake.addEventListener('release', () => { R.wake = null; });
    }
  } catch { }
}

$('btnStartCam').onclick = () => startSource(false);
$('btnStartDemo').onclick = () => startSource(true);

// ---------- Жесты ----------
function hitTarget(p) {
  if (R.mode === 'calib') {
    const cs = getCorners().map(vToS);
    let bi = -1, bd = 34;
    cs.forEach((c, i) => { const d = G.dist(c, p); if (d < bd) { bd = d; bi = i; } });
    if (bi >= 0) return { kind: 'corner', i: bi };
  }
  if (R.kalkaEdit && S.kalka.has) {
    const h = kalkaHandles();
    if (G.dist(h.scale, p) < 28) return { kind: 'kscale' };
    if (G.dist(h.rot, p) < 28) return { kind: 'krot' };
    const ip = G.apply(G.inv(G.mul(R.P2S, kalkaA())), p.x, p.y);
    if (ip.x >= 0 && ip.y >= 0 && ip.x <= S.kalka.imgW && ip.y <= S.kalka.imgH) return { kind: 'kmove' };
  }
  const sel = S.guides.find(g => g.id === R.selected);
  if (sel) {
    const hs = guideHandles(sel).map(toScreen);
    let bi = -1, bd = 28;
    hs.forEach((h, i) => { const d = G.dist(h, p); if (d < bd) { bd = d; bi = i; } });
    if (bi >= 0) return { kind: 'handle', id: sel.id, i: bi };
  }
  // Ближайшая линия
  let best = null, bd = 18;
  for (const path of R.paths) {
    if (path.id == null) continue;
    const pts = path.pts, n = pts.length;
    for (let i = 0; i < n - 1 + (path.closed ? 1 : 0); i++) {
      const d = G.distToSegment(p, pts[i], pts[(i + 1) % n]);
      const bias = path.id === R.selected ? 4 : 0;
      if (d - bias < bd) { bd = d - bias; best = path.id; }
    }
  }
  for (const d of R.dots) if (d.id != null && G.dist(d, p) < bd) { bd = G.dist(d, p); best = d.id; }
  if (best != null) return { kind: 'body', id: best };
  return { kind: 'empty' };
}

function snapPoint(p, g, i) {
  R.snapPt = null;
  if (!S.settings.magnet) return p;
  const sp = toScreen(p);
  const cands = [
    { x: 0, y: 0 }, { x: R.pw, y: 0 }, { x: R.pw, y: R.ph }, { x: 0, y: R.ph },
    { x: R.pw / 2, y: 0 }, { x: R.pw, y: R.ph / 2 }, { x: R.pw / 2, y: R.ph }, { x: 0, y: R.ph / 2 }, { x: R.pw / 2, y: R.ph / 2 },
  ];
  for (const o of S.guides) {
    if (o.hidden) continue;
    guideHandles(o).forEach((h, j) => { if (!(o.id === g.id && j === i)) cands.push(h); });
  }
  let best = null, bd = 16;
  for (const c of cands) { const d = G.dist(toScreen(c), sp); if (d < bd) { bd = d; best = c; } }
  if (best) { R.snapPt = toScreen(best); return { x: best.x, y: best.y }; }
  const T = TYPES[g.type];
  if (T.dirPair && T.dirPair.includes(i)) {
    const other = guideHandles(g)[T.dirPair[0] === i ? T.dirPair[1] : T.dirPair[0]];
    const d = G.sub(p, other), L = G.len(d);
    let a = Math.atan2(d.y, d.x) * 180 / Math.PI;
    const step = 15, ra = Math.round(a / step) * step;
    let LL = L;
    if (T.roundLen) LL = Math.max(2, Math.round(L));
    if (Math.abs(a - ra) < 3.2) {
      const rr = ra * Math.PI / 180;
      return { x: other.x + Math.cos(rr) * LL, y: other.y + Math.sin(rr) * LL };
    }
    if (T.roundLen) return G.add(other, G.mulS(G.norm(d), LL));
  }
  return p;
}

const ptOf = (e) => { const r = overlay.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };

overlay.addEventListener('pointerdown', (e) => {
  overlay.setPointerCapture(e.pointerId);
  const p = ptOf(e);
  R.pointers.set(e.pointerId, p);
  if (R.pointers.size === 2) {
    if (R.down && R.down.moved && R.down.undoPushed) { /* оставляем изменения */ }
    R.down = null; R.snapPt = null;
    const [a, b] = [...R.pointers.values()];
    R.pinch = { d0: G.dist(a, b) || 1, m0: G.lerpP(a, b, 0.5), zoom0: R.zoom, pan0: { x: R.panX, y: R.panY } };
    return;
  }
  if (R.pointers.size > 2) return;
  if (!R.P2S) return;
  const target = R.clean ? { kind: 'empty' } : hitTarget(p);
  R.down = { p0: p, t: performance.now(), moved: false, target, undoPushed: false };
  const t = target;
  if (t.kind === 'handle') {
    const g = S.guides.find(x => x.id === t.id);
    const h = toScreen(guideHandles(g)[t.i]);
    R.down.offset = { x: h.x - p.x, y: h.y - p.y };
  } else if (t.kind === 'body') {
    const g = S.guides.find(x => x.id === t.id);
    R.down.pts0 = JSON.parse(JSON.stringify(g.pts));
    R.down.paper0 = toPaper(p);
  } else if (t.kind === 'kmove' || t.kind === 'kscale' || t.kind === 'krot') {
    const k = S.kalka;
    R.down.k0 = { cx: k.cx, cy: k.cy, scale: k.scale, rot: k.rot };
    R.down.paper0 = toPaper(p);
  } else if (t.kind === 'empty') {
    R.down.pan0 = { x: R.panX, y: R.panY };
  }
});

overlay.addEventListener('pointermove', (e) => {
  if (!R.pointers.has(e.pointerId)) return;
  const p = ptOf(e);
  R.pointers.set(e.pointerId, p);
  if (R.pinch && R.pointers.size >= 2) {
    const [a, b] = [...R.pointers.values()];
    const d = G.dist(a, b), m = G.lerpP(a, b, 0.5);
    const z = G.clamp(R.pinch.zoom0 * d / R.pinch.d0, 0.35, 6);
    // зум вокруг стартовой середины + сдвиг
    const c = { x: R.W / 2 + R.pinch.pan0.x, y: R.H / 2 + R.pinch.pan0.y };
    const k = z / R.pinch.zoom0;
    R.zoom = z;
    R.panX = (R.pinch.m0.x + (c.x - R.pinch.m0.x) * k) - R.W / 2 + (m.x - R.pinch.m0.x);
    R.panY = (R.pinch.m0.y + (c.y - R.pinch.m0.y) * k) - R.H / 2 + (m.y - R.pinch.m0.y);
    computeView();
    return;
  }
  const D = R.down;
  if (!D) return;
  if (!D.moved && G.dist(p, D.p0) < 6) return;
  D.moved = true;
  const t = D.target;
  if (t.kind === 'handle' || t.kind === 'body') {
    if (!D.undoPushed) { pushUndo(); D.undoPushed = true; }
    const g = S.guides.find(x => x.id === t.id);
    if (!g) return;
    if (t.kind === 'body') R.selected = g.id;
    if (t.kind === 'handle') {
      let q = toPaper({ x: p.x + D.offset.x, y: p.y + D.offset.y });
      q = snapPoint(q, g, t.i);
      TYPES[g.type].drag(g, t.i, q);
    } else {
      const q = toPaper(p), d = G.sub(q, D.paper0);
      g.pts = D.pts0.map(x => G.add(x, d));
    }
    persist();
  } else if (t.kind === 'corner') {
    const c = getCorners().map(x => ({ ...x }));
    c[t.i] = sToV(p);
    if (G.isConvexQuad(c)) setCorners(c);
  } else if (t.kind === 'kmove') {
    const q = toPaper(p), k = S.kalka;
    k.cx = D.k0.cx + q.x - D.paper0.x; k.cy = D.k0.cy + q.y - D.paper0.y; persist();
  } else if (t.kind === 'kscale' || t.kind === 'krot') {
    const k = S.kalka, q = toPaper(p), c = { x: D.k0.cx, y: D.k0.cy };
    if (t.kind === 'kscale') {
      const r0 = G.dist(c, D.paper0) || 1;
      k.scale = Math.max(0.005, D.k0.scale * G.dist(c, q) / r0);
    } else {
      const a0 = Math.atan2(D.paper0.y - c.y, D.paper0.x - c.x), a1 = Math.atan2(q.y - c.y, q.x - c.x);
      let r = D.k0.rot + a1 - a0;
      if (S.settings.magnet) { const st = Math.PI / 12, rr = Math.round(r / st) * st; if (Math.abs(r - rr) < 0.05) r = rr; }
      k.rot = r;
    }
    persist();
  } else if (t.kind === 'empty' && D.pan0) {
    R.panX = D.pan0.x + p.x - D.p0.x; R.panY = D.pan0.y + p.y - D.p0.y;
    computeView();
  }
});

function endPointer(e) {
  if (!R.pointers.has(e.pointerId)) return;
  R.pointers.delete(e.pointerId);
  if (R.pinch) { if (R.pointers.size < 2) R.pinch = null; R.down = null; return; }
  const D = R.down; R.down = null; R.snapPt = null;
  if (!D) return;
  if (!D.moved) onTap(D);
  else if (D.target.kind === 'handle' || D.target.kind === 'body') refreshPanel(true);
}
overlay.addEventListener('pointerup', endPointer);
overlay.addEventListener('pointercancel', endPointer);

function onTap(D) {
  const now = performance.now();
  const dbl = now - R.lastTap < 320;
  R.lastTap = now;
  if (R.clean) { if (dbl) setClean(false); else showCleanHint(); return; }
  const t = D.target;
  if (t.kind === 'body' || t.kind === 'handle') {
    if (R.selected !== t.id) { R.selected = t.id; openPanel('guide'); }
    else if (R.panel !== 'guide') openPanel('guide');
  } else if (t.kind === 'empty') {
    if (R.selected) { R.selected = null; if (R.panel === 'guide') closePanel(); }
    else if (dbl) { R.zoom = 1; R.panX = 0; R.panY = 0; computeView(); toast('Масштаб сброшен'); }
  }
}

// ---------- Чистый режим ----------
function setClean(on) {
  R.clean = on;
  document.body.classList.toggle('clean', on);
  if (on) { R.selected = null; closePanel(); showCleanHint(); }
  else $('cleanHint').classList.add('hidden');
}
function showCleanHint() {
  const h = $('cleanHint'); h.classList.remove('hidden');
  clearTimeout(showCleanHint._t); showCleanHint._t = setTimeout(() => h.classList.add('hidden'), 2200);
}

// ---------- Направляющие: действия ----------
function addGuide(type) {
  pushUndo();
  const T = TYPES[type];
  const c = { x: R.pw / 2, y: R.ph / 2 }, s = Math.min(R.pw, R.ph) * 0.28;
  const g = { id: S.nextId++, type, pts: T.create(c, s, { W: R.pw, H: R.ph }), props: defaultProps(type), color: null };
  S.guides.push(g);
  R.selected = g.id;
  persist();
  openPanel('guide');
}

function removeGuide(id) {
  pushUndo();
  S.guides = S.guides.filter(g => g.id !== id);
  if (R.selected === id) R.selected = null;
  persist();
}

function duplicateGuide(id) {
  const g = S.guides.find(x => x.id === id);
  if (!g) return;
  pushUndo();
  const off = Math.min(R.pw, R.ph) * 0.05;
  const n = JSON.parse(JSON.stringify(g));
  n.id = S.nextId++;
  n.pts = n.pts.map(p => ({ x: p.x + off, y: p.y + off }));
  S.guides.push(n);
  R.selected = n.id;
  persist();
}

function centerGuide(id) {
  const g = S.guides.find(x => x.id === id);
  if (!g) return;
  pushUndo();
  const hs = guideHandles(g);
  const c = hs.reduce((a, p) => ({ x: a.x + p.x / hs.length, y: a.y + p.y / hs.length }), { x: 0, y: 0 });
  const d = { x: R.pw / 2 - c.x, y: R.ph / 2 - c.y };
  g.pts = g.pts.map(p => G.add(p, d));
  persist();
}

// ---------- Панели ----------
const panel = $('panel'), panelBody = $('panelBody'), panelTitle = $('panelTitle');
function openPanel(kind) {
  R.panel = kind;
  panel.classList.remove('hidden');
  if (kind !== 'kalka' && R.kalkaEdit) R.kalkaEdit = false;
  refreshPanel();
  updateBarState();
}
function closePanel() {
  R.panel = null;
  panel.classList.add('hidden');
  if (R.mode === 'calib') finishCalib();
  R.kalkaEdit = false;
  updateBarState();
}
$('panelClose').onclick = () => { if (R.panel === 'guide') R.selected = null; closePanel(); };

function updateBarState() {
  $('btnAdd').classList.toggle('active', R.panel === 'add' || R.panel === 'guide');
  $('btnKalka').classList.toggle('active', R.panel === 'kalka');
  $('btnSheet').classList.toggle('active', R.panel === 'sheet');
  $('btnMagnet').classList.toggle('on', !!S.settings.magnet);
}

function togglePanel(kind) { if (R.panel === kind) closePanel(); else openPanel(kind); }
$('btnAdd').onclick = () => togglePanel('add');
$('btnKalka').onclick = () => togglePanel('kalka');
$('btnSheet').onclick = () => togglePanel('sheet');
$('btnSettings').onclick = () => togglePanel('settings');
$('statusPill').onclick = () => togglePanel('sheet');
$('btnMagnet').onclick = () => { S.settings.magnet = !S.settings.magnet; persist(); updateBarState(); toast(S.settings.magnet ? 'Магнит включён: прилипание к точкам и углам 15°' : 'Магнит выключен'); };
$('btnUndo').onclick = undo;
$('btnClean').onclick = () => setClean(true);

// Контролы
function toggleRow(label, value, onChange) {
  const input = el('input', { type: 'checkbox' });
  input.checked = !!value;
  input.onchange = () => onChange(input.checked);
  return el('div', { class: 'row' }, el('label', {}, label), el('label', { class: 'switch' }, input, el('i')));
}
function rangeRow(label, min, max, step, value, onChange, fmt = (v) => v) {
  const val = el('span', { class: 'val' }, fmt(value));
  const input = el('input', { type: 'range', min, max, step, value });
  input.oninput = () => { const v = +input.value; val.textContent = fmt(v); onChange(v); };
  return el('div', { class: 'row' }, el('span', { class: 'lbl' }, label), input, val);
}
function segRow(label, options, value, onChange) {
  const seg = el('div', { class: 'seg' });
  for (const [v, t] of options) {
    const b = el('button', { class: String(v) === String(value) ? 'sel' : '' }, t);
    b.onclick = () => { onChange(v); [...seg.children].forEach(x => x.classList.remove('sel')); b.classList.add('sel'); };
    seg.append(b);
  }
  return el('div', { class: 'col' }, label ? el('span', { class: 'lbl' }, label) : null, seg);
}
function swatchRow(label, value, onChange, allowAuto) {
  const wrap = el('div', { class: 'swatches' });
  const mk = (c) => {
    const b = el('button', { class: (c === value ? 'sel ' : '') + (c ? '' : 'auto'), style: c ? `background:${c}` : '', title: c || 'общий цвет' });
    b.onclick = () => { onChange(c); [...wrap.children].forEach(x => x.classList.remove('sel')); b.classList.add('sel'); };
    return b;
  };
  if (allowAuto) wrap.append(mk(null));
  COLORS.forEach(c => wrap.append(mk(c)));
  return el('div', { class: 'col' }, el('span', { class: 'lbl' }, label), wrap);
}
const btn = (text, onClick, cls = '') => el('button', { class: 'btn ' + cls, onclick: onClick }, text);

function refreshPanel(soft) {
  if (!R.panel) return;
  if (soft && R.panel !== 'guide') return;
  const scroll = panelBody.scrollTop;
  panelBody.innerHTML = '';
  const f = { add: panelAdd, guide: panelGuide, kalka: panelKalka, sheet: panelSheet, settings: panelSettings }[R.panel];
  if (f) f();
  panelBody.scrollTop = scroll;
}

function panelAdd() {
  panelTitle.textContent = 'Добавить направляющую';
  const tools = el('div', { class: 'tools' });
  for (const t of TYPE_ORDER) {
    const T = TYPES[t];
    tools.append(el('button', { class: 'tool', title: T.desc, onclick: () => addGuide(t) }, el('b', {}, T.icon), el('span', {}, T.name)));
  }
  panelBody.append(tools);
  if (S.guides.length) {
    panelBody.append(el('div', { class: 'section-title' }, 'На листе'));
    const chips = el('div', { class: 'chips' });
    for (const g of S.guides) {
      const T = TYPES[g.type];
      chips.append(el('span', { class: 'chip' + (g.id === R.selected ? ' sel' : '') },
        el('i', { style: `background:${colorOf(g)}` }),
        el('span', { onclick: () => { R.selected = g.id; openPanel('guide'); } }, `${T.icon} ${T.name}`),
        el('button', { class: 'x', title: g.hidden ? 'Показать' : 'Скрыть', onclick: () => { g.hidden = !g.hidden; persist(); refreshPanel(); } }, g.hidden ? '🙈' : '👁'),
        el('button', { class: 'x', title: 'Удалить', onclick: () => { removeGuide(g.id); refreshPanel(); } }, '✕')));
    }
    panelBody.append(chips);
    panelBody.append(el('div', { class: 'btns' }, btn('Удалить все', () => { if (confirm('Удалить все направляющие?')) { pushUndo(); S.guides = []; R.selected = null; persist(); refreshPanel(); } }, 'danger')));
  } else {
    panelBody.append(el('p', { class: 'note' }, 'Направляющая появится в центре листа. Тяни за ', el('b', {}, 'кружки'), ', чтобы менять её, или за саму линию — чтобы двигать. Двумя пальцами — масштаб экрана.'));
  }
}

function panelGuide() {
  const g = S.guides.find(x => x.id === R.selected);
  if (!g) { closePanel(); return; }
  const T = TYPES[g.type];
  panelTitle.textContent = `${T.icon} ${T.name}`;
  panelBody.append(el('p', { class: 'note' }, T.desc));
  panelBody.append(swatchRow('Цвет', g.color, (c) => { g.color = c; persist(); }, true));
  for (const p of T.props) {
    if (p.show && !p.show(g)) continue;
    const v = getProp(g, p.key);
    const set = (val) => { pushUndo(); g.props[p.key] = val; persist(); if (T.props.some(q => q.show)) refreshPanel(); };
    if (p.type === 'toggle') panelBody.append(toggleRow(p.label, v, set));
    else if (p.type === 'range') panelBody.append(rangeRow(p.label, p.min, p.max, p.step, v, (val) => { g.props[p.key] = val; persist(); }, (x) => (p.step < 1 ? x.toFixed(2) : x)));
    else if (p.type === 'select') panelBody.append(segRow(p.label, p.options, v, set));
  }
  panelBody.append(el('div', { class: 'btns' },
    btn('⧉ Копия', () => { duplicateGuide(g.id); refreshPanel(); }),
    btn('◎ В центр', () => centerGuide(g.id)),
    btn(g.hidden ? '👁 Показать' : '🙈 Скрыть', () => { g.hidden = !g.hidden; persist(); refreshPanel(); }),
    btn('🗑 Удалить', () => { removeGuide(g.id); closePanel(); }, 'danger')));
  panelBody.append(el('p', { class: 'note' }, 'Совет: включи 👁 «чистый экран» сверху, чтобы панели не мешали рисовать.'));
}

function panelKalka() {
  panelTitle.textContent = '🖼 Калька';
  const k = S.kalka;
  if (!k.has) {
    panelBody.append(el('p', { class: 'note' }, 'Выбери картинку — она ляжет поверх листа полупрозрачным слоем. Можно показать только ', el('b', {}, 'контур'), ', ', el('b', {}, 'тона'), ', наложить ', el('b', {}, 'сетку'), ' или рисовать ', el('b', {}, 'по одной клетке'), '.'));
    panelBody.append(el('div', { class: 'btns' }, btn('Выбрать картинку', () => $('fileInput').click(), 'primary')));
    return;
  }
  panelBody.append(toggleRow('Показывать кальку', k.show, (v) => { k.show = v; persist(); }));
  panelBody.append(segRow('Что показывать', [['orig', 'Оригинал'], ['edges', 'Контур'], ['tones', 'Тона'], ['gray', 'Ч/Б']], k.mode, (v) => { k.mode = v; persist(); rebuildKalka(0); refreshPanel(); }));
  panelBody.append(rangeRow('Прозрачность', 0.1, 1, 0.05, k.opacity, (v) => { k.opacity = v; persist(); }, (v) => Math.round(v * 100) + '%'));
  if (k.mode === 'edges') {
    panelBody.append(rangeRow('Детализация', 0, 1, 0.05, k.detail, (v) => { k.detail = v; persist(); rebuildKalka(); }, (v) => Math.round(v * 100) + '%'));
    panelBody.append(rangeRow('Толщина', 1, 4, 1, k.thick, (v) => { k.thick = v; persist(); rebuildKalka(); }));
    panelBody.append(swatchRow('Цвет контура', k.color, (c) => { k.color = c; persist(); rebuildKalka(0); }, false));
  }
  if (k.mode === 'tones') panelBody.append(rangeRow('Уровней тона', 2, 6, 1, k.levels, (v) => { k.levels = v; persist(); rebuildKalka(); }));

  panelBody.append(el('div', { class: 'section-title' }, 'Сетка и клетки'));
  panelBody.append(toggleRow('Сетка поверх картинки', k.grid, (v) => { k.grid = v; persist(); }));
  panelBody.append(rangeRow('Клеток по ширине', 2, 12, 1, k.cols, (v) => { k.cols = v; k.cell = 0; persist(); refreshPanelPart(); }));
  panelBody.append(toggleRow('По частям (одна клетка)', k.part, (v) => { k.part = v; persist(); refreshPanel(); }));
  if (k.part) {
    const c = kalkaCellRect();
    const label = el('span', { class: 'cell', id: 'cellLabel' }, `${cellName(c.cx, c.cy)} · ${c.i + 1}/${c.total}`);
    panelBody.append(el('div', { class: 'part-nav' }, btn('◀', () => { k.cell = (kalkaCellRect().i - 1 + kalkaCellRect().total) % kalkaCellRect().total; persist(); refreshPanelPart(); }), label, btn('▶', () => { k.cell = (kalkaCellRect().i + 1) % kalkaCellRect().total; persist(); refreshPanelPart(); })));
  }

  panelBody.append(el('div', { class: 'section-title' }, 'Положение'));
  panelBody.append(toggleRow('Двигать и масштабировать', R.kalkaEdit, (v) => { R.kalkaEdit = v; if (v) { R.selected = null; toast('Тяни картинку; голубая ручка — размер, жёлтая — поворот'); } }));
  panelBody.append(el('div', { class: 'btns' },
    btn('⤢ Вписать в лист', () => { fitKalka(); }),
    btn('⟳ 90°', () => { k.rot = Math.round((k.rot + Math.PI / 2) / (Math.PI / 2)) * (Math.PI / 2); persist(); }),
    btn('⇋ Отразить', () => { k.flip = !k.flip; persist(); }),
    btn('Заменить', () => $('fileInput').click()),
    btn('Убрать', async () => { k.has = false; R.kalkaSrc = null; R.kalkaReady = false; R.kalkaEdit = false; await store.delFile('kalka'); persist(); refreshPanel(); }, 'danger')));
}
function refreshPanelPart() {
  const l = document.getElementById('cellLabel');
  if (l) { const c = kalkaCellRect(); l.textContent = `${cellName(c.cx, c.cy)} · ${c.i + 1}/${c.total}`; }
}

function startCalib() {
  R.mode = 'calib';
  if (S.paper.tracking) { S.paper.tracking = false; toast('Слежение выключено: углы задаёшь ты'); }
  if (!S.corners) setCorners(getCorners());
  R.selected = null;
  persist(); refreshPanel();
}
function finishCalib() {
  R.mode = 'normal';
  const c = getCorners();
  updateLandscapeKeepOrder(c);
  persist();
  if (R.panel === 'sheet') refreshPanel();
}
function updateLandscapeKeepOrder(c) { if (S.paper.orient === 'auto') updateLandscape(c); }

function panelSheet() {
  panelTitle.textContent = '📄 Лист';
  const st = {
    tracking: '✅ Слежу за листом — направляющие двигаются вместе с ним.',
    locked: '🔒 Лист закреплён: углы не меняются (удобно, если лист приклеен).',
    lost: '⚠️ Лист потерян' + (R.trackReason ? `: ${R.trackReason}` : '') + '. Направляющие остались на последнем месте.',
    none: '🔍 Лист ещё не найден' + (R.trackReason ? `: ${R.trackReason}` : '') + '.',
    calib: '✋ Перетащи 4 розовых угла точно на углы листа.',
  }[R.track] || '';
  panelBody.append(el('div', { class: 'status-line' }, st));
  if (R.mode === 'calib') {
    panelBody.append(el('div', { class: 'btns' }, btn('✓ Готово', () => { finishCalib(); }, 'primary')));
  } else {
    panelBody.append(el('div', { class: 'btns' },
      btn('🔍 Найти лист', () => { S.paper.tracking = true; R.forceCalib = true; persist(); toast('Ищу лист…'); refreshPanel(); }, 'primary'),
      btn('✋ Углы вручную', startCalib)));
  }
  panelBody.append(toggleRow('Следить за листом (если он сдвинется)', S.paper.tracking, (v) => { S.paper.tracking = v; if (v) R.mode = 'normal'; persist(); refreshPanel(); }));
  panelBody.append(segRow('Формат листа', [['A6', 'A6'], ['A5', 'A5'], ['A4', 'A4'], ['A3', 'A3'], ['Letter', 'Letter'], ['custom', 'Свой']], S.paper.format, (v) => { S.paper.format = v; persist(); refreshPanel(); }));
  if (S.paper.format === 'custom') {
    const wI = el('input', { type: 'number', min: 20, max: 2000, value: S.paper.customW });
    const hI = el('input', { type: 'number', min: 20, max: 2000, value: S.paper.customH });
    wI.onchange = () => { S.paper.customW = G.clamp(+wI.value || 200, 20, 2000); persist(); };
    hI.onchange = () => { S.paper.customH = G.clamp(+hI.value || 200, 20, 2000); persist(); };
    panelBody.append(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Размер, мм'), wI, el('span', {}, '×'), hI));
  }
  panelBody.append(segRow('Ориентация', [['auto', 'Авто'], ['port', 'Книжная'], ['land', 'Альбомная']], S.paper.orient, (v) => { S.paper.orient = v; persist(); }));
  panelBody.append(el('p', { class: 'note' },
    'Размер листа нужен, чтобы сантиметры и круги были настоящими. ',
    el('b', {}, 'Для лучшего распознавания: '), 'тёмный стол, ровный свет без бликов, весь лист в кадре. Если лист приклеен к столу — выключи слежение, так стабильнее.'));
}

async function panelSettings() {
  panelTitle.textContent = '⚙ Настройки';
  const s = S.settings;
  panelBody.append(el('div', { class: 'section-title' }, 'Линии'));
  panelBody.append(swatchRow('Цвет по умолчанию', s.color, (c) => { s.color = c; persist(); }, false));
  panelBody.append(rangeRow('Толщина', 1, 8, 0.5, s.width, (v) => { s.width = v; persist(); }, (v) => v + ' px'));
  panelBody.append(rangeRow('Яркость линий', 0.2, 1, 0.05, s.alpha, (v) => { s.alpha = v; persist(); }, (v) => Math.round(v * 100) + '%'));
  panelBody.append(toggleRow('Тёмная обводка (контраст на белом)', s.halo, (v) => { s.halo = v; persist(); }));
  panelBody.append(toggleRow('Подписи размеров', s.labels, (v) => { s.labels = v; persist(); }));

  panelBody.append(el('div', { class: 'section-title' }, 'Экран'));
  panelBody.append(el('div', { class: 'btns' },
    btn('⟳ Повернуть картинку 90°', () => { s.rot = ((s.rot || 0) + 90) % 360; R.panX = R.panY = 0; computeView(); persist(); }),
    btn('⤧ Сбросить масштаб', () => { R.zoom = 1; R.panX = R.panY = 0; computeView(); })));
  panelBody.append(toggleRow('Зеркально', s.mirror, (v) => { s.mirror = v; computeView(); persist(); }));
  panelBody.append(toggleRow('Не гасить экран', s.wake, (v) => { s.wake = v; persist(); keepAwake(); }));
  if (document.documentElement.requestFullscreen && !IS_APP) {
    panelBody.append(el('div', { class: 'btns' }, btn('⛶ Полный экран', () => { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(() => { }); })));
  }

  if (R.cam && !R.cam.demo) {
    panelBody.append(el('div', { class: 'section-title' }, 'Камера'));
    const caps = trackCaps(R.cam.track);
    if (caps.torch) panelBody.append(toggleRow('Фонарик (подсветка листа)', R.torch, async (v) => { try { await setTorch(R.cam.track, v); R.torch = v; } catch { toast('Фонарик недоступен'); } }));
    if (caps.zoom && caps.zoom.max > caps.zoom.min) {
      const cur = (R.cam.track.getSettings && R.cam.track.getSettings().zoom) || caps.zoom.min;
      panelBody.append(rangeRow('Зум камеры', caps.zoom.min, Math.min(caps.zoom.max, 4), caps.zoom.step || 0.1, cur, (v) => { setZoom(R.cam.track, v).catch(() => { }); }, (v) => (+v).toFixed(1) + '×'));
    }
    const cams = await listCameras();
    if (cams.length > 1 && R.panel === 'settings') {
      const sel = el('select', {});
      sel.append(el('option', { value: '' }, 'Основная задняя'));
      cams.forEach((c, i) => { const o = el('option', { value: c.deviceId }, c.label || `Камера ${i + 1}`); if (c.deviceId === s.cameraId) o.selected = true; sel.append(o); });
      sel.onchange = () => { s.cameraId = sel.value || null; persist(); startSource(false); };
      panelBody.append(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Камера'), sel));
    }
  } else if (R.cam && R.cam.demo) {
    panelBody.append(el('div', { class: 'btns' }, btn('📷 Включить настоящую камеру', () => startSource(false), 'primary')));
  }

  panelBody.append(el('div', { class: 'section-title' }, 'Прочее'));
  panelBody.append(el('div', { class: 'btns' }, btn('Сбросить всё', async () => {
    if (!confirm('Удалить все направляющие, кальку и настройки?')) return;
    store.clearState(); await store.delFile('kalka');
    S = DEFAULT(); R.kalkaSrc = null; R.kalkaReady = false; R.selected = null; R.forceCalib = true;
    computeView(); updateBarState(); refreshPanel();
  }, 'danger')));
  panelBody.append(el('p', { class: 'note' }, `Рейка AR v${VERSION}. Всё работает на устройстве, без интернета и без ИИ.`));
}

// ---------- Старт ----------
resize();
updateBarState();
requestAnimationFrame(frame);

if ('serviceWorker' in navigator && !IS_APP && location.protocol === 'https:') {
  navigator.serviceWorker.register('sw.js').catch(() => { });
}

// Для отладки/тестов
window.__reyka = { S: () => S, R, addGuide, startSource, openPanel, setClean };
