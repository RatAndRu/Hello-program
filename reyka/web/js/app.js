// Рейка AR — главный модуль.
import * as G from './geom.js';
import * as CL from './colors.js';
import { PaperTracker } from './tracker.js';
import { startCamera, createDemoStream, listCameras, trackCaps, setTorch, setZoom } from './camera.js';
import { TYPES, TYPE_ORDER, MANGA_ORDER, Pen, getProp, defaultProps, planeH, viewHandles, rotHandleIndex, toFigure, spinFromPoint, canRotate } from './guides.js';
import { KalkaLayer, imageToCanvas, edgesCanvas, tonesCanvas, grayCanvas } from './tracing.js';
import * as store from './store.js';
import { estimateRect, cameraTilt, assumedFocal, manualCorners, fitFocal, completeRectangle, rigidPredict, planeNormal } from './perspective.js';
import { detectSegments, findVanishingPoints } from './vanish.js';
import * as scan from './scan.js';

const VERSION = '1.6';
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
  settings: { color: '#39ff14', width: 3, halo: true, alpha: 1, labels: true, magnet: true, rot: 0, mirror: false, wake: true, cameraId: null, demoTilt: 0 },
  manual: { on: false, tilt: 45, far: 0, yaw: 0, size: 1 },
  scan: { lines: 0.5, colors: 6, smooth: 1, clean: 0.5, minSpot: 2, lineBlack: false, paint: true, fmt: 'png', mode: 'color', sharpen: 0.6, grad: true, gap: 0, pal: 'auto' },
  paints: [], nextPaint: 1,
  colorUI: { cur: '#3b6fd4', mix: [], max2: false, water: false },
  paper: { format: 'A4', orient: 'auto', customW: 200, customH: 200, tracking: true },
  corners: null, cornersFor: null, landscape: false,
  guides: [], nextId: 1,
  kalka: { has: false, show: true, mode: 'orig', opacity: 0.6, detail: 0.45, thick: 2, levels: 3, color: '#ff2fd6', grid: false, cols: 4, part: false, cell: 0, cx: 0, cy: 0, scale: 1, rot: 0, flip: false, imgW: 0, imgH: 0, blink: false, blinkPeriod: 0.8, vpShow: false },
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
  kalkaSrc: null, kalkaReady: false, dirty: false, wake: null, vp: null, tiltInfo: null, scan: null,
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

// Ориентация листа: по НАСТОЯЩИМ пропорциям (с учётом перспективы), а не по длинам в кадре —
// иначе при камере под 45–60° книжный лист выглядит «альбомным».
function updateLandscape(c) {
  let w, h;
  if (S.paper.format === 'custom') { w = +S.paper.customW || 200; h = +S.paper.customH || 200; }
  else [w, h] = FORMATS[S.paper.format] || FORMATS.A4;
  const r = Math.max(w, h) / Math.min(w, h);
  if (r < 1.05) { S.landscape = false; return; }
  // какая ориентация лучше объясняет то, что видит камера
  const land = fitFocal(c, R.vw, R.vh, r), port = fitFocal(c, R.vw, R.vh, 1 / r);
  // Если перспектива не даёт уверенного ответа (неровный край — оторванная спираль,
  // камера почти сверху), решают длины сторон в кадре: верх/низ против боков.
  const lo = Math.min(land.cost, port.cost), hi = Math.max(land.cost, port.cost);
  if (hi < lo * 1.6 + 0.004) {
    const ed = (i) => G.dist(c[i], c[(i + 1) % 4]);
    S.landscape = ed(0) + ed(2) > ed(1) + ed(3);
  } else S.landscape = land.cost < port.cost;
}

// Наклон камеры относительно листа (для информации и подсказок).
function measureTilt() {
  if (!R.vw) return null;
  const c = getCorners();
  const [pw, ph] = paperDims();
  const H = G.homography([{ x: 0, y: 0 }, { x: pw, y: 0 }, { x: pw, y: ph }, { x: 0, y: ph }], c);
  const fit = fitFocal(c, R.vw, R.vh, pw / ph);
  const tilt = cameraTilt(H, fit.f, R.vw, R.vh);
  return { tilt, f: fit.f, measuredF: fit.cost < 0.03, fitCost: fit.cost };
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
    calib: 'Тяни углы',
    occl: '✋ Достраиваю',
  };
  $('statusText').textContent = map[state] || state;
  if (R.panel === 'sheet') refreshPanel();
}

function trackStep(now) {
  if (R.mode === 'calib') { setTrack('calib'); return; }
  if (!S.paper.tracking) { setTrack(S.corners ? 'locked' : 'none'); return; }
  if (now - R.lastDetect < 85) return;
  R.lastDetect = now;
  const prior = S.corners && !R.forceCalib ? S.corners : null;
  const res0 = tracker.detect(video, R.vw, R.vh, prior);
  const res = res0 && completeCorners(res0, prior);
  if (!res) {
    R.lostFrames++;
    if (R.lostFrames > 8) setTrack(S.corners ? 'lost' : 'none', tracker.lastReason);
    return;
  }
  let c = res.corners;
  R.occluded = res.how !== 'all';
  if (!R.occluded) learnCamera(c);
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
  setTrack(R.occluded ? 'occl' : 'tracking');
}

// ---------- Закрытый угол: достраиваем ----------
// Порядок: (1) телефон неподвижен → лист мог только сдвинуться/повернуться по столу,
// подгоняем это движение по видимым углам (хватает двух); (2) пересечение видимых
// частей сторон; (3) по трём углам с честной перспективой; (4) иначе лист не трогаем.
function paperRect() { const [pw, ph] = paperDims(); return [{ x: 0, y: 0 }, { x: pw, y: 0 }, { x: pw, y: ph }, { x: 0, y: ph }]; }
function completeCorners(res, prev) {
  let c = res.corners;
  const vis = c.map(p => !!p.vis), nv = vis.filter(Boolean).length;
  if (nv === 4) return { corners: c, how: 'all' };
  const diag = Math.hypot(R.vw, R.vh);
  if (prev) {
    // порядок углов приводим к прошлому, флажки едут вместе с углами
    c = matchOrder(c, prev);
    const v2 = c.map(p => !!p.vis), idx = [0, 1, 2, 3].filter(i => v2[i]);
    if (idx.length >= 2) {
      const H = G.homography(paperRect(), prev);
      if (H) {
        const r = rigidPredict(H, paperRect(), c, idx);
        if (r.rms < Math.max(2.5, diag * 0.004)) return { corners: c.map((p, i) => (v2[i] ? p : { ...r.pred[i], vis: false, ok: true })), how: 'rigid' };
      }
    }
  }
  const ok = c.map(p => !!p.ok), nok = ok.filter(Boolean).length;
  if (nok === 4) return { corners: c, how: 'lines' };
  if (nok === 3) {
    const k = ok.indexOf(false), [pw, ph] = paperDims();
    const A = c[(k + 2) % 4], B = c[(k + 1) % 4], D = c[(k + 3) % 4];
    let lenAB = (k + 1) % 2 === 0 ? pw : ph, lenAD = (k + 2) % 2 === 0 ? pw : ph;
    if (!prev) { // порядок углов ещё неизвестен: длинная сторона листа — там, где длиннее в кадре
      const lo = Math.min(pw, ph), hi = Math.max(pw, ph);
      if (G.dist(A, B) >= G.dist(A, D)) { lenAB = hi; lenAD = lo; } else { lenAB = lo; lenAD = hi; }
    }
    const f = R.fFit || assumedFocal(R.vw, R.vh);
    const C = completeRectangle(A, B, D, lenAB / lenAD, f, R.vw, R.vh, R.planeN || [0, 0, 1], prev ? prev[k] : null);
    const out = c.slice(); out[k] = { x: C.x, y: C.y, vis: false, ok: true };
    return { corners: out, how: 'persp3' };
  }
  if (prev) return { corners: prev.map(p => ({ ...p })), how: 'hold' };
  return null;
}

// Пока все 4 угла видны — запоминаем фокус камеры и наклон плоскости стола (для достройки).
function learnCamera(c) {
  const now = performance.now();
  if (now - (R.learnT || 0) < 1000) return;
  R.learnT = now;
  const [pw, ph] = paperDims();
  const fit = fitFocal(c, R.vw, R.vh, pw / ph);
  R.fFit = R.fFit ? R.fFit * 0.7 + fit.f * 0.3 : fit.f;
  const H = G.homography(paperRect(), c);
  if (H) R.planeN = planeNormal(H, R.fFit, R.vw, R.vh);
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
  // заливки (тени помощника света) — под линиями
  for (const p of paths) {
    if (!p.fill) continue;
    octx.save();
    if (p.holes && p.holes.length) {
      octx.beginPath(); octx.rect(-1e4, -1e4, 3e4, 3e4);
      for (const h of p.holes) { h.forEach((q, i) => i ? octx.lineTo(q.x, q.y) : octx.moveTo(q.x, q.y)); octx.closePath(); }
      octx.clip('evenodd');
    }
    octx.globalAlpha = 1;
    octx.fillStyle = 'rgba(15,20,45,0.42)';
    trace(p); octx.fill();
    octx.restore();
  }
  paths = paths.filter(p => !p.fill);
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
  if (kind === 'rot') { // круговая стрелка
    octx.strokeStyle = color; octx.lineWidth = 2.2;
    octx.beginPath(); octx.arc(p.x, p.y, 7, -2.6, 1.6); octx.stroke();
    const ax = p.x + 7 * Math.cos(1.6), ay = p.y + 7 * Math.sin(1.6);
    octx.fillStyle = color; octx.beginPath(); octx.moveTo(ax - 4.5, ay + 1); octx.lineTo(ax + 2, ay - 4); octx.lineTo(ax + 2.5, ay + 3.5); octx.closePath(); octx.fill();
    return;
  }
  octx.fillStyle = color;
  octx.beginPath(); octx.arc(p.x, p.y, 4.5, 0, Math.PI * 2); octx.fill();
}

// Ручки так, как они видны (у повёрнутой/наклонённой фигуры — уже повёрнуты) + ручка поворота.
function guideHandles(g) { return viewHandles(g); }
function isMoveHandle(g, i) {
  const T = TYPES[g.type];
  if (T && T.moveIdx !== undefined) return i === T.moveIdx;
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
    let op = k.opacity;
    if (k.blink) op = (performance.now() / 1000 / Math.max(0.2, k.blinkPeriod)) % 2 < 1 ? k.opacity : 0;
    kalkaLayer.draw(inv, op, crop);
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
    pen.L = planeH(g);
    try { TYPES[g.type].draw(pen, g, ctx); } catch (e) { console.warn(e); }
    pen.L = null;
  }
  // Зеркальные копии от осей симметрии
  for (const sym of S.guides) {
    if (sym.type !== 'symmetry' || sym.hidden || !getProp(sym, 'mirror')) continue;
    pen.mirror = { a: sym.pts[0], b: sym.pts[1] }; pen.layerOverride = 'ghost';
    for (const g of S.guides) {
      if (g === sym || g.type === 'symmetry' || g.hidden) continue;
      pen.guideId = g.id;
      const before = pen.paths.length;
      pen.L = planeH(g);
      try { TYPES[g.type].draw(pen, g, { ...ctx, labels: false }); } catch (e) { console.warn(e); }
      pen.L = null;
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

  if (k.has && k.show && k.vpShow && R.vp && R.vp.src === R.kalkaSrc) {
    const kp = new Pen(G.mul(R.P2S, kalkaA()), { x0: -1e6, y0: -1e6, x1: 1e6, y1: 1e6 });
    const cols = ['#ff3b30', '#00e5ff', '#ffe600', '#888888'];
    R.vp.segs.forEach((sg, i) => {
      const before = kp.paths.length;
      kp.seg({ x: sg.x1, y: sg.y1 }, { x: sg.x2, y: sg.y2 }, 'aux');
      for (let j = before; j < kp.paths.length; j++) kp.paths[j].color = cols[R.vp.cls[i]];
    });
    pen.paths.push(...kp.paths);
  }

  R.paths = pen.paths; R.dots = pen.points;
  strokePaths(pen.paths, pen.points);
  drawLabels(pen.labels);

  if (R.clean) return;

  // Ручки выбранной направляющей
  const sel = S.guides.find(g => g.id === R.selected);
  if (sel) {
    const hs = guideHandles(sel), ri = rotHandleIndex(sel);
    if (ri >= 0) { // пунктир от центра к ручке поворота
      const c = toScreen(hs[TYPES[sel.type].handles(sel).findIndex((_, i) => isMoveHandle(sel, i))] || hs[0]), r = toScreen(hs[ri]);
      octx.strokeStyle = 'rgba(255,255,255,0.6)'; octx.lineWidth = 1.2; octx.setLineDash([4, 4]);
      octx.beginPath(); octx.moveTo(c.x, c.y); octx.lineTo(r.x, r.y); octx.stroke(); octx.setLineDash([]);
    }
    hs.forEach((p, i) => drawHandle(toScreen(p), colorOf(sel), i === ri ? 'rot' : isMoveHandle(sel, i) ? 'move' : 'pt'));
  }

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
  if (now - (frame._t || 0) > 600) {
    frame._t = now;
    const lab = document.getElementById('tiltVal');
    if (lab) lab.textContent = tiltText();
    const sl = document.getElementById('sensorVal');
    if (sl) sl.textContent = sensorText();
  }
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
    R.cam = demo ? createDemoStream(R.H > R.W, S.settings.demoTilt || 0) : await startCamera(S.settings.cameraId);
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
    const ri = rotHandleIndex(o);
    guideHandles(o).forEach((h, j) => { if (j !== ri && !(o.id === g.id && j === i)) cands.push(h); });
  }
  let best = null, bd = 16;
  for (const c of cands) { const d = G.dist(toScreen(c), sp); if (d < bd) { bd = d; best = c; } }
  if (best) { R.snapPt = toScreen(best); return { x: best.x, y: best.y }; }
  const T = TYPES[g.type];
  if (T.dirPair && T.dirPair.includes(i) && !planeH(g)) {
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
  const target = R.pick ? { kind: 'pick' } : R.clean ? { kind: 'empty' } : hitTarget(p);
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
  if (D.target.kind === 'pick') return; // пипетка: дрожание пальца — не движение
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
      if (t.i === rotHandleIndex(g)) {
        // ручка поворота: угол вокруг центра (с магнитом — по 15°)
        let a = spinFromPoint(g, q);
        R.snapPt = null;
        if (S.settings.magnet) { const ra = Math.round(a / 15) * 15; if (Math.abs(a - ra) < 4) a = ra; }
        g.props = g.props || {};
        g.props.spin = Math.round(a);
      } else {
        q = snapPoint(q, g, t.i);
        if (!isMoveHandle(g, t.i)) q = toFigure(g, q); // центр стоит на месте, остальное — в плоскости фигуры
        TYPES[g.type].drag(g, t.i, q);
      }
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
  const t = D.target;
  if (t.kind === 'pick') { pickAt(D.p0); return; }
  if (R.clean) { if (dbl) setClean(false); else showCleanHint(); return; }
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
  if (T.init) T.init(g, s, { W: R.pw, H: R.ph });
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
  const hs = TYPES[g.type].handles(g);
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
  $('btnScan').classList.toggle('active', R.panel === 'scan');
  $('btnColors').classList.toggle('active', R.panel === 'colors');
}

function togglePanel(kind) { if (R.panel === kind) closePanel(); else openPanel(kind); }
$('btnAdd').onclick = () => togglePanel('add');
$('btnKalka').onclick = () => togglePanel('kalka');
$('btnSheet').onclick = () => togglePanel('sheet');
$('btnScan').onclick = () => togglePanel('scan');
$('btnColors').onclick = () => togglePanel('colors');
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
  const f = { add: panelAdd, guide: panelGuide, kalka: panelKalka, sheet: panelSheet, settings: panelSettings, scan: panelScan, colors: panelColors }[R.panel];
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
  panelBody.append(el('div', { class: 'section-title' }, 'Манга и аниме'));
  const mt = el('div', { class: 'tools' });
  for (const t of MANGA_ORDER) {
    const T = TYPES[t];
    mt.append(el('button', { class: 'tool', title: T.desc, onclick: () => addGuide(t) }, el('b', {}, T.icon), el('span', {}, T.name)));
  }
  panelBody.append(mt);
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
  let rotTitle = false;
  for (const p of T.props) {
    if (p.show && !p.show(g)) continue;
    if (p.type === 'hidden') continue;
    if (p.type === 'section') { panelBody.append(el('div', { class: 'section-title' }, p.label)); continue; }
    if (p.rot && !rotTitle) {
      rotTitle = true;
      panelBody.append(el('div', { class: 'section-title' }, 'Поворот и перспектива'));
      panelBody.append(el('p', { class: 'note' }, 'Вместе с фигурой поворачиваются и все её внутренние линии. Крутить можно и пальцем — за ручку со стрелкой. Наклон кладёт фигуру «на плоскость» под углом, например колесо или тарелку в перспективе.'));
    }
    const v = getProp(g, p.key);
    const set = (val) => { pushUndo(); g.props[p.key] = val; if (p.onSet) p.onSet(g, val); persist(); if (p.onSet || T.props.some(q => q.show)) refreshPanel(); };
    if (p.type === 'toggle') panelBody.append(toggleRow(p.label, v, set));
    else if (p.type === 'range') panelBody.append(rangeRow(p.label, p.min, p.max, p.step, v, (val) => { g.props[p.key] = val; persist(); }, p.fmt || ((x) => (p.step < 1 ? x.toFixed(2) : x))));
    else if (p.type === 'select') panelBody.append(segRow(p.label, p.options, v, set));
  }
  if (T.actions) panelBody.append(el('div', { class: 'btns' }, ...T.actions.map(([label, fn]) => btn(label, () => { pushUndo(); fn(g); persist(); refreshPanel(); }))));
  panelBody.append(el('div', { class: 'btns' },
    btn('⧉ Копия', () => { duplicateGuide(g.id); refreshPanel(); }),
    btn('◎ В центр', () => centerGuide(g.id)),
    ...(canRotate(g) ? [btn('↺ Без поворота', () => { pushUndo(); g.props = g.props || {}; g.props.spin = 0; g.props.tiltX = 0; g.props.tiltY = 0; persist(); refreshPanel(); })] : []),
    btn(g.hidden ? '👁 Показать' : '🙈 Скрыть', () => { g.hidden = !g.hidden; persist(); refreshPanel(); }),
    btn('🗑 Удалить', () => { removeGuide(g.id); closePanel(); }, 'danger')));
  panelBody.append(el('p', { class: 'note' }, 'Совет: включи 👁 «чистый экран» сверху, чтобы панели не мешали рисовать.'));
}

// ---------- 🎨 Цвета: пипетка, смешивание, подбор смеси ----------
function grabFrame() {
  if (!R.vw || !video) return null;
  const cv = R._grab || (R._grab = document.createElement('canvas'));
  if (cv.width !== R.vw || cv.height !== R.vh) { cv.width = R.vw; cv.height = R.vh; }
  const g = cv.getContext('2d', { willReadFrequently: true });
  try { g.drawImage(video, 0, 0, R.vw, R.vh); return { data: g.getImageData(0, 0, R.vw, R.vh).data, w: R.vw, h: R.vh }; } catch (e) { return null; }
}
function avgAt(fr, x, y, r) {
  let a = 0, b = 0, c = 0, n = 0;
  for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) {
    const xx = Math.round(x + dx), yy = Math.round(y + dy);
    if (xx < 0 || yy < 0 || xx >= fr.w || yy >= fr.h) continue;
    const i = (yy * fr.w + xx) * 4; a += fr.data[i]; b += fr.data[i + 1]; c += fr.data[i + 2]; n++;
  }
  return n ? [a / n, b / n, c / n] : [255, 255, 255];
}
// Белый бумаги рядом с точкой: точки листа поблизости, берём самые светлые (это бумага)
function paperWhiteNear(fr, pp) {
  if (!R.P2S || !S.corners) return null;
  const smp = [];
  for (let y = R.ph * 0.04; y < R.ph * 0.97; y += 5) for (let x = R.pw * 0.04; x < R.pw * 0.97; x += 5) {
    const v = sToV(toScreen({ x, y }));
    if (v.x < 0 || v.y < 0 || v.x >= fr.w || v.y >= fr.h) continue;
    const c = avgAt(fr, v.x, v.y, 1);
    smp.push({ d: Math.hypot(x - pp.x, y - pp.y), c, L: c[0] + c[1] + c[2] });
  }
  if (smp.length < 12) return null;
  smp.sort((a, b) => a.d - b.d);
  const near = smp.slice(0, Math.max(30, Math.round(smp.length * 0.15))).sort((a, b) => b.L - a.L).slice(0, 0 | Math.max(6, smp.length * 0.04));
  const w = [0, 1, 2].map(k => near.reduce((s2, q) => s2 + q.c[k], 0) / near.length);
  return w[0] + w[1] + w[2] > 150 ? w : null;
}
function startPick() {
  R.pick = true; closePanel();
  toast('🎯 Тапни по цвету на листе', 5000);
}
function pickAt(p) {
  R.pick = false;
  const fr = grabFrame(); if (!fr) { toast('Нет кадра с камеры'); return; }
  const v = sToV(p);
  const c = avgAt(fr, v.x, v.y, Math.max(2, Math.round(Math.min(fr.w, fr.h) / 150)));
  let rgb = c, note = '';
  const W = R.P2S ? paperWhiteNear(fr, toPaper(p)) : null;
  if (W) { const wl = CL.rgbToLin(W); rgb = CL.linToRgb(CL.rgbToLin(c).map((x, i) => x / Math.max(0.02, wl[i]) * 0.9)); note = ' · с поправкой на свет по бумаге'; }
  S.colorUI.cur = CL.rgbToHex(rgb); persist();
  openPanel('colors');
  toast(`Цвет: ${CL.colorName(S.colorUI.cur)} ${S.colorUI.cur}${note}`, 3500);
}
function addPaint(hex, name) {
  const n = S.paints.length + 1;
  S.paints.push({ id: S.nextPaint++, name: name || `${CL.colorName(hex)} ${n}`, hex, scan: true });
  persist();
}
let recipeCache = { key: '', list: [] };
function panelColors() {
  panelTitle.textContent = '🎨 Цвета и краски';
  const U = S.colorUI, cur = U.cur || '#3b6fd4';
  panelBody.append(el('p', { class: 'note' }, 'Узнай цвет пипеткой (поправка на освещение — по белой бумаге рядом), посмотри, как смешать его из своих красок, или что получится из смеси. Смешивание считается как у настоящих пигментов (модель Кубелки — Мунка), но приблизительно.'));
  // — текущий цвет
  panelBody.append(el('div', { class: 'section-title' }, 'Цвет'));
  const picker = el('input', { type: 'color', value: cur, class: 'color-input', title: 'Выбрать вручную' });
  picker.onchange = () => { U.cur = picker.value; persist(); refreshPanel(); };
  const rgb = CL.hexToRgb(cur);
  panelBody.append(el('div', { class: 'color-cur' }, el('div', { class: 'big-sw', style: `background:${cur}` }),
    el('div', { class: 'grow' }, el('b', {}, CL.colorName(cur)), el('div', { class: 'muted' }, `${cur.toUpperCase()} · RGB ${rgb.join(', ')}`)), picker));
  panelBody.append(el('div', { class: 'btns' }, btn('🎯 Пипетка: тапни по листу', startPick, 'primary'), btn('➕ В мои краски', () => { addPaint(cur); refreshPanel(); toast('Добавлено в «Мои краски»'); })));
  // — подбор смеси
  panelBody.append(el('div', { class: 'section-title' }, 'Как смешать этот цвет'));
  if (!S.paints.length) panelBody.append(el('p', { class: 'note' }, 'Сначала добавь свои краски (ниже — пипеткой с выкраски или готовым набором).'));
  else {
    panelBody.append(toggleRow('Не больше двух красок', U.max2, (v) => { U.max2 = v; persist(); refreshPanel(); }));
    panelBody.append(toggleRow('Акварель: светлее = больше воды', U.water, (v) => { U.water = v; persist(); refreshPanel(); }));
    const list = S.paints.map(p => ({ name: p.name, hex: p.hex, strength: p.strength || 1 }));
    if (U.water) list.push({ name: 'вода', hex: '#fbfbf8', strength: 1 });
    const key = cur + '|' + U.max2 + '|' + list.map(p => p.hex + p.strength).join(',');
    if (recipeCache.key !== key) recipeCache = { key, list: CL.findRecipes(cur, list, { maxPaints: U.max2 ? 2 : 3 }) };
    for (const r of recipeCache.list) {
      panelBody.append(el('div', { class: 'recipe' },
        el('div', { class: 'pair' }, el('i', { style: `background:${cur}`, title: 'нужно' }), el('i', { style: `background:${r.hex}`, title: 'получится' })),
        el('div', { class: 'grow' }, el('div', {}, CL.recipeText(r)), el('div', { class: 'muted' }, `${CL.closeness(r.dE)} · ΔE ${r.dE.toFixed(1)}`)),
        btn('В смесь', () => { U.mix = r.items.map(it => { const pp = S.paints.find(q => q.hex === it.hex && q.name === it.name); return pp ? { id: pp.id, parts: it.parts } : null; }).filter(Boolean); persist(); refreshPanel(); toast('Рецепт — в «Смешать»'); }, 'small')));
    }
    if (recipeCache.list[0] && recipeCache.list[0].dE > 10) panelBody.append(el('p', { class: 'note' }, 'Точно не получается — такого оттенка нет в твоих красках. Добавь краску ближе к нему (или белила для светлых тонов).'));
  }
  // — смешать
  panelBody.append(el('div', { class: 'section-title' }, 'Смешать'));
  U.mix = (U.mix || []).filter(m => S.paints.some(p => p.id === m.id));
  if (!U.mix.length) panelBody.append(el('p', { class: 'note' }, 'Нажми «🧪» у красок ниже, чтобы добавить их в смесь, и задай части.'));
  for (const m of U.mix) {
    const pnt = S.paints.find(p => p.id === m.id);
    const val = el('span', { class: 'parts' }, String(m.parts));
    panelBody.append(el('div', { class: 'paint-row' }, el('i', { class: 'sw', style: `background:${pnt.hex}` }), el('span', { class: 'grow' }, pnt.name),
      btn('−', () => { m.parts = Math.max(1, m.parts - 1); persist(); refreshPanel(); }, 'small'), val,
      btn('+', () => { m.parts = Math.min(99, m.parts + 1); persist(); refreshPanel(); }, 'small'),
      btn('✕', () => { U.mix = U.mix.filter(q => q !== m); persist(); refreshPanel(); }, 'small')));
  }
  if (U.mix.length) {
    const res = CL.mixHex(U.mix.map(m => { const pnt = S.paints.find(p => p.id === m.id); return { hex: pnt.hex, parts: m.parts, strength: pnt.strength || 1 }; }));
    panelBody.append(el('div', { class: 'color-cur' }, el('div', { class: 'big-sw', style: `background:${res}` }),
      el('div', { class: 'grow' }, el('b', {}, 'Получится: ' + CL.colorName(res)), el('div', { class: 'muted' }, res.toUpperCase() + (U.cur ? ` · до цели ΔE ${CL.deltaEHex(res, U.cur).toFixed(1)}` : '')))));
    panelBody.append(el('div', { class: 'btns' }, btn('➕ Смесь в мои краски', () => { addPaint(res, 'Смесь ' + CL.colorName(res)); refreshPanel(); }), btn('Сделать целью', () => { U.cur = res; persist(); refreshPanel(); }), btn('Очистить', () => { U.mix = []; persist(); refreshPanel(); })));
  }
  // — мои краски
  panelBody.append(el('div', { class: 'section-title' }, `Мои краски (${S.paints.length})`));
  panelBody.append(el('p', { class: 'note' }, 'Лучше всего — сделать выкраску (мазок каждой краски на белой бумаге) и снять каждую пипеткой: так учтётся именно твоя краска. 🖌 — использовать краску в оцифровке («Рисунок (вектор)» → палитра «Мои краски»).'));
  for (const pnt of S.paints) {
    const name = el('input', { type: 'text', value: pnt.name, class: 'name-input' }); name.onchange = () => { pnt.name = name.value.trim() || pnt.name; persist(); };
    const col = el('input', { type: 'color', value: pnt.hex, class: 'sw-input' }); col.onchange = () => { pnt.hex = col.value; persist(); refreshPanel(); };
    panelBody.append(el('div', { class: 'paint-row' }, col, name,
      el('button', { class: 'btn small' + (pnt.scan !== false ? ' on' : ''), title: 'Использовать в оцифровке', onclick: () => { pnt.scan = pnt.scan === false; persist(); refreshPanel(); } }, '🖌'),
      btn('🧪', () => { const m = U.mix.find(q => q.id === pnt.id); if (m) m.parts++; else U.mix.push({ id: pnt.id, parts: 1 }); persist(); refreshPanel(); }, 'small'),
      btn('✕', () => { S.paints = S.paints.filter(q => q !== pnt); persist(); refreshPanel(); }, 'small')));
  }
  panelBody.append(el('div', { class: 'btns' },
    ...Object.entries(CL.PRESET_SETS).map(([k, set]) => btn('+ Набор: ' + set.name, () => { for (const [nm, hx] of set.paints) if (!S.paints.some(p => p.name === nm)) addPaint(hx, nm); refreshPanel(); toast('Цвета набора примерные — лучше переснять пипеткой свои'); })),
    S.paints.length ? btn('Удалить все', () => { if (confirm('Удалить все свои краски?')) { S.paints = []; U.mix = []; persist(); refreshPanel(); } }, 'danger') : null));
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

  panelBody.append(el('div', { class: 'section-title' }, 'Проверка пропорций'));
  panelBody.append(toggleRow('Мигать (вкл/выкл)', k.blink, (v) => { k.blink = v; persist(); if (v) toast('Смотри, что «прыгает» при мигании — там пропорции расходятся'); }));
  panelBody.append(rangeRow('Период мигания', 0.3, 2, 0.1, k.blinkPeriod, (v) => { k.blinkPeriod = v; persist(); }, (v) => v.toFixed(1) + ' с'));

  panelBody.append(el('div', { class: 'section-title' }, 'Перспектива с фото'));
  panelBody.append(el('div', { class: 'btns' }, btn('📐 Найти точки схода', findKalkaPerspective, 'primary')));
  if (R.vp && R.vp.src === R.kalkaSrc) {
    panelBody.append(el('p', { class: 'note' }, R.vp.text));
    panelBody.append(toggleRow('Показать найденные линии', k.vpShow, (v) => { k.vpShow = v; persist(); }));
  } else panelBody.append(el('p', { class: 'note' }, 'Ищет на картинке прямые края (здания, комнаты, мебель) и точки, где они сходятся. Ставит на лист сетку перспективы как на фото.'));

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
    occl: '✋ Часть листа закрыта рукой — закрытые углы достраиваю по видимым (лист при этом не «прыгает»).',
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
      btn('🔍 Найти лист', () => { S.paper.tracking = true; S.manual.on = false; R.forceCalib = true; persist(); toast('Ищу лист…'); refreshPanel(); }, 'primary'),
      btn('✋ Углы вручную', startCalib)));
  }
  panelBody.append(toggleRow('Следить за листом (если он сдвинется)', S.paper.tracking, (v) => { S.paper.tracking = v; if (v) { R.mode = 'normal'; S.manual.on = false; } persist(); refreshPanel(); }));
  panelBody.append(segRow('Формат листа', [['A6', 'A6'], ['A5', 'A5'], ['A4', 'A4'], ['A3', 'A3'], ['Letter', 'Letter'], ['custom', 'Свой']], S.paper.format, (v) => { S.paper.format = v; persist(); refreshPanel(); }));
  if (S.paper.format === 'custom') {
    const wI = el('input', { type: 'number', min: 20, max: 2000, value: S.paper.customW });
    const hI = el('input', { type: 'number', min: 20, max: 2000, value: S.paper.customH });
    wI.onchange = () => { S.paper.customW = G.clamp(+wI.value || 200, 20, 2000); persist(); };
    hI.onchange = () => { S.paper.customH = G.clamp(+hI.value || 200, 20, 2000); persist(); };
    panelBody.append(el('div', { class: 'row' }, el('span', { class: 'lbl' }, 'Размер, мм'), wI, el('span', {}, '×'), hI));
  }
  panelBody.append(segRow('Ориентация', [['auto', 'Авто'], ['port', 'Книжная'], ['land', 'Альбомная']], S.paper.orient, (v) => { S.paper.orient = v; persist(); }));

  panelBody.append(el('div', { class: 'section-title' }, 'Камера под углом'));
  panelBody.append(el('div', { class: 'status-line', id: 'tiltVal' }, tiltText()));
  panelBody.append(el('div', { class: 'status-line', id: 'sensorVal' }, sensorText()));
  panelBody.append(el('p', { class: 'note' }, 'Ставить телефон строго сверху не обязательно: по 4 углам листа программа сама считает перспективу, и направляющие с калькой ложатся на лист с правильным искажением. ',
    'Если лист не находится, задай наклон вручную, а потом при желании поправь углы.'));
  panelBody.append(toggleRow('Задать наклон вручную', S.manual.on, (v) => { S.manual.on = v; if (v) { S.paper.tracking = false; R.mode = 'normal'; applyManual(); } persist(); refreshPanel(); }));
  if (S.manual.on) {
    const m = S.manual;
    panelBody.append(rangeRow('Наклон камеры', 0, 75, 1, m.tilt, (v) => { m.tilt = v; applyManual(); }, (v) => v + '°'));
    panelBody.append(el('div', { class: 'btns' }, btn('📱 Взять наклон с датчика (если лист лежит на ровном столе)', () => {
      if (R.sensorTilt == null) { toast('Датчик наклона недоступен'); return; }
      m.tilt = Math.max(0, Math.min(75, Math.round(R.sensorTilt))); applyManual(); persist(); refreshPanel();
    })));
    panelBody.append(segRow('Дальний край листа', [[0, '↑ Сверху'], [90, '→ Справа'], [180, '↓ Снизу'], [270, '← Слева']], m.far, (v) => { m.far = +v; applyManual(); }));
    panelBody.append(rangeRow('Поворот листа', -45, 45, 1, m.yaw, (v) => { m.yaw = v; applyManual(); }, (v) => v + '°'));
    panelBody.append(rangeRow('Размер на экране', 0.4, 1.6, 0.02, m.size, (v) => { m.size = v; applyManual(); }, (v) => Math.round(v * 100) + '%'));
    panelBody.append(el('div', { class: 'btns' }, btn('✋ Подогнать углы точно', startCalib)));
  }
  panelBody.append(el('p', { class: 'note' },
    'Размер листа нужен, чтобы сантиметры и круги были настоящими. ',
    el('b', {}, 'Для лучшего распознавания: '), 'тёмный стол, ровный свет без бликов, весь лист в кадре. Если лист приклеен к столу — выключи слежение, так стабильнее.'));
}

// ---------- Датчик наклона телефона (акселерометр) ----------
// Гравитация показывает, насколько камера отклонена от вертикали «вниз». Это не заменяет
// расчёт по листу (стол может быть наклонным, а лист — лежать на мольберте), поэтому
// используется как подсказка и для ручного режима.
R.sensorTilt = null;
if (typeof window !== 'undefined' && 'DeviceMotionEvent' in window) {
  window.addEventListener('devicemotion', (e) => {
    const a = e.accelerationIncludingGravity;
    if (!a || a.x == null || a.z == null) return;
    const n = Math.hypot(a.x, a.y, a.z);
    if (n < 5 || n > 15) return; // телефон трясут — не верим
    const t = Math.acos(Math.min(1, Math.abs(a.z) / n)) * 180 / Math.PI;
    R.sensorTilt = R.sensorTilt == null ? t : R.sensorTilt * 0.85 + t * 0.15;
  });
}
function sensorText() {
  if (R.sensorTilt == null) return '📱 Датчик телефона: нет данных (на этом устройстве датчик недоступен)';
  return `📱 Датчик телефона: камера отклонена от вертикали на ${Math.round(R.sensorTilt)}°`;
}

function tiltText() {
  if (!S.corners) return '📐 Наклон камеры: лист ещё не задан';
  const t = measureTilt();
  if (!t || t.tilt == null) return '📐 Наклон камеры: не удалось оценить';
  const deg = Math.round(t.tilt);
  const how = deg <= 8 ? 'почти сверху' : deg <= 30 ? 'небольшой наклон' : deg <= 55 ? 'заметный наклон — перспектива учтена' : 'сильный наклон — дальний край мельче, точность ниже';
  return `📐 Наклон камеры ≈ ${deg}° (${how})${t.measuredF ? '' : ' · оценка'}`;
}

function applyManual() {
  if (!R.vw) return;
  const m = S.manual, [pw, ph] = paperDims();
  const vs = Math.hypot(R.M[0], R.M[3]);
  const f = assumedFocal(R.vw, R.vh) * vs;
  const rot = Math.abs(Math.sin(m.yaw * Math.PI / 180)) > 0.7 || m.far % 180 ? [ph, pw] : [pw, ph];
  const k0 = Math.min(R.W * 0.8 / rot[0], R.H * 0.7 / rot[1]) * m.size;
  const sc = manualCorners({ pw, ph, f, size: k0, tilt: m.tilt, yaw: m.yaw, far: m.far, cx: R.W / 2, cy: R.H / 2 });
  setCorners(sc.map(sToV));
  persist();
}

async function findKalkaPerspective() {
  if (!R.kalkaSrc) return;
  toast('Ищу прямые и точки схода…', 8000);
  await new Promise(r => setTimeout(r, 30));
  const segs = detectSegments(R.kalkaSrc);
  const W = R.kalkaSrc.width, H = R.kalkaSrc.height;
  const vps = findVanishingPoints(segs, W, H, 3);
  const cls = segs.map(() => 3);
  vps.forEach((v, i) => v.inliers.forEach(q => { cls[q] = i; }));
  const vert = vps.find(v => v.vertical);
  const hor = vps.filter(v => v !== vert && !v.inf).sort((a, b) => a.x - b.x);
  let text;
  if (!hor.length) {
    R.vp = { src: R.kalkaSrc, segs, cls, text: `Прямых найдено: ${segs.length}. Точек схода не нашлось — на фото мало сходящихся прямых (лучше всего работают здания, интерьеры, столы).` };
    toast('Точки схода не найдены'); S.kalka.vpShow = true; persist(); refreshPanel(); return;
  }
  const A = kalkaA();
  const toP = (v) => { const r = G.apply(A, v.x, v.y); return { x: r.x, y: r.y }; };
  pushUndo();
  const g = { id: S.nextId++, type: 'persp', props: defaultProps('persp'), color: null, hidden: false };
  const p1 = toP(hor[0]);
  if (hor.length >= 2) {
    const p2 = toP(hor[1]);
    if (vert && !vert.inf) { g.props.vps = 3; g.pts = [p1, p2, toP(vert)]; }
    else { g.props.vps = 2; g.pts = [p1, p2, { x: (p1.x + p2.x) / 2, y: R.ph * 2 }]; }
  } else {
    g.props.vps = 1; g.pts = [p1, { x: p1.x + R.pw, y: p1.y }, { x: p1.x, y: R.ph * 2 }];
  }
  S.guides.push(g); R.selected = g.id;
  const names = ['красные', 'голубые', 'жёлтые'];
  text = `Найдено точек схода: ${g.props.vps} (из ${segs.length} прямых). Цвета линий: ${vps.map((v, i) => names[i] + (v === vert ? ' — вертикали' : '')).join(', ')}. Сетка перспективы добавлена — её можно поправить как обычную направляющую.`;
  R.vp = { src: R.kalkaSrc, segs, cls, text };
  S.kalka.vpShow = true; persist();
  toast('Перспектива с фото добавлена ✓');
  refreshPanel();
}

// ---------- Оцифровка ----------
function panelScan() {
  panelTitle.textContent = '📥 Оцифровать рисунок';
  const sc = S.scan;
  panelBody.append(el('p', { class: 'note' }, 'Снимает лист и выпрямляет его. Получаешь ', el('b', {}, 'скан'), ' (как у сканера документов: фон ровный, рисунок как есть) и, по желанию, ', el('b', {}, 'вектор'), ' — рисунок, заново собранный из линий и пятен краски (SVG). Без ИИ — только обработка изображения.'));
  if (!S.corners) panelBody.append(el('div', { class: 'status-line' }, '⚠️ Сначала нужно найти лист (📄 Лист).'));
  panelBody.append(el('p', { class: 'note' }, el('b', {}, 'Перед снимком: '), 'убери руки и карандаш с листа, свет ровный, без бликов. Камера под углом — можно, но сверху чётче.'));
  panelBody.append(toggleRow('Таймер 3 с (успеть убрать руки)', sc.timer !== false, (v) => { sc.timer = v; persist(); }));
  panelBody.append(toggleRow('Фото в полном разрешении (чётче; если камера умеет)', sc.hires !== false, (v) => { sc.hires = v; persist(); }));
  panelBody.append(rangeRow('Цветов краски', 0, 16, 1, sc.colors, (v) => { sc.colors = v; sc.paint = v > 0; persist(); }, (v) => v ? v : 'только линии'));
  panelBody.append(el('div', { class: 'btns' }, btn('📥 Оцифровать', () => runScan(), 'primary'),
    R.scan ? btn('Открыть последний', () => openScanView()) : null));
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function runScan() {
  if (R.scanBusy) return;
  if (!S.corners || !R.vw) { toast('Сначала найди лист'); return; }
  R.scanBusy = true;
  try {
    if (S.scan.timer !== false) for (let i = 3; i > 0; i--) { toast(`Убери руки… ${i}`, 1100); if (R.cam && R.cam.setHand) R.cam.setHand(false); await sleep(1000); }
    if (R.cam && R.cam.setHand) { R.cam.setHand(false); await sleep(600); }
    toast('Снимаю…', 4000);
    const [pw, ph] = paperDims();
    const P4 = [{ x: 0, y: 0 }, { x: pw, y: 0 }, { x: pw, y: ph }, { x: 0, y: ph }];
    const ppmFor = (c, max) => { const area = Math.abs(shoelace(c)); return G.clamp(Math.round(Math.sqrt(area / (pw * ph)) * 1.15 * 2) / 2, 3, max); };
    let rect = null, ppm = 4;
    // 1) пробуем настоящее фото в полном разрешении (в 2–4 раза больше пикселей, чем видео)
    if (S.scan.hires !== false) {
      const ph0 = await takeFullPhoto();
      if (ph0) {
        const r = locateInPhoto(ph0, getCorners());
        if (r) {
          const H = G.homography(P4, r.corners);
          if (H) { ppm = ppmFor(r.corners, 8); toast('Выпрямляю лист…', 4000); await sleep(20); rect = scan.rectify(r.frame, H, pw, ph, ppm); R.scanInfo = `фото ${r.frame.w}×${r.frame.h}`; }
        }
      }
    }
    // 2) иначе — несколько видеокадров: каждый выпрямляется по своим углам, смазанные
    //    отбрасываются, остальные совмещаются и усредняются (меньше шума, без смаза с рук)
    if (!rect) {
      ppm = ppmFor(getCorners(), 6);
      const r = await captureAligned(pw, ph, ppm, P4);
      rect = r.rect; R.scanInfo = `кадры видео: ${r.used} из ${r.total}`;
    }
    if (R.cam && R.cam.setHand) R.cam.setHand(true);
    toast('Убираю тени и фон…', 4000); await sleep(20);
    const flat = scan.flatten(rect, ppm, S.scan.clean);
    R.scan = { pw, ph, ppm, rect, flat, tab: 'photo' };
    openScanView(); // вектор считается только когда откроют его вкладку
    toast('Готово ✓ Можно подправить настройки и сохранить', 3000);
  } catch (e) { console.error(e); toast('Не получилось: ' + (e.message || e)); }
  finally { R.scanBusy = false; if (R.cam && R.cam.setHand) R.cam.setHand(true); }
}

// Серия видеокадров → выпрямление каждого по его собственным углам → отбор резких →
// совмещение сдвигом → усреднение. С рук кадры чуть «гуляют»: простое усреднение их смазало бы.
async function captureAligned(pw, ph, ppm, P4, n = 5) {
  const frames = [];
  for (let k = 0; k < n; k++) {
    const cv = document.createElement('canvas'); cv.width = R.vw; cv.height = R.vh;
    const g = cv.getContext('2d', { willReadFrequently: true }); g.drawImage(video, 0, 0, R.vw, R.vh);
    frames.push({ cv, g });
    if (k < n - 1) await sleep(90);
  }
  toast('Выпрямляю лист…', 4000); await sleep(20);
  const prior = getCorners(), diag = Math.hypot(R.vw, R.vh);
  const tr = new PaperTracker({ longSide: 640 });
  for (const f of frames) {
    let c = prior;
    const det = tr.detect(f.cv, R.vw, R.vh, prior);
    if (det && det.computed.every(Boolean)) {
      const m = matchOrder(det.corners.map(q => ({ x: q.x, y: q.y })), prior);
      const dmax = Math.max(...m.map((q, i) => Math.hypot(q.x - prior[i].x, q.y - prior[i].y)));
      if (dmax < diag * 0.04) c = m;
    }
    const H = G.homography(P4, c);
    f.rect = scan.rectify({ data: f.g.getImageData(0, 0, R.vw, R.vh).data, w: R.vw, h: R.vh }, H, pw, ph, ppm);
    f.sharp = scan.sharpness(f.rect);
    f.cv.width = f.cv.height = 1; // память
  }
  const best = Math.max(...frames.map(f => f.sharp));
  const use = frames.filter(f => f.sharp >= best * 0.82);
  use.sort((a, b) => b.sharp - a.sharp);
  const rect = scan.alignAverage(use.map(f => f.rect));
  return { rect, used: use.length, total: frames.length };
}

// Полноразмерное фото через ImageCapture (есть в Chrome/WebView на Android).
async function takeFullPhoto() {
  const track = R.cam && R.cam.track;
  if (!track || R.cam.demo || typeof ImageCapture === 'undefined' || track.readyState !== 'live') return null;
  try {
    const ic = new ImageCapture(track);
    const opts = {};
    try { const caps = await ic.getPhotoCapabilities(); if (caps && caps.imageWidth && caps.imageWidth.max) opts.imageWidth = Math.min(caps.imageWidth.max, 4096); } catch { /* без настроек */ }
    const blob = await Promise.race([ic.takePhoto(opts), sleep(7000).then(() => null)]);
    if (!blob) return null;
    const bmp = await createImageBitmap(blob);
    if (Math.max(bmp.width, bmp.height) < Math.max(R.vw, R.vh) * 1.25) { bmp.close && bmp.close(); return null; } // не больше видео — смысла нет
    return bmp;
  } catch (e) { console.warn('takePhoto:', e); return null; }
}

// Находим лист на фото заново (поворот и кадрирование фото могут отличаться от видео)
// и сопоставляем углы с углами из видео, чтобы верх рисунка остался верхом.
function locateInPhoto(bmp, vc) {
  const W = bmp.width, Hh = bmp.height;
  const cv = document.createElement('canvas'); cv.width = W; cv.height = Hh;
  const g = cv.getContext('2d', { willReadFrequently: true });
  g.drawImage(bmp, 0, 0); bmp.close && bmp.close();
  const det = new PaperTracker({ longSide: 900 }).detect(cv, W, Hh, null);
  if (!det || det.computed.filter(Boolean).length < 4) return null;
  const pc = det.corners.map(p => ({ x: p.x, y: p.y }));
  let best = null, bestE = Infinity;
  for (const rot of [0, 1, 2, 3]) for (const mode of ['min', 'max']) {
    const rw = rot % 2 ? R.vh : R.vw, rh = rot % 2 ? R.vw : R.vh;
    const sc = mode === 'min' ? Math.min(W / rw, Hh / rh) : Math.max(W / rw, Hh / rh);
    const ox = (W - rw * sc) / 2, oy = (Hh - rh * sc) / 2;
    const map = (p) => { let x = p.x, y = p.y, cw = R.vw, ch = R.vh; for (let k = 0; k < rot; k++) { const t = x; x = ch - y; y = t; const tw = cw; cw = ch; ch = tw; } return { x: ox + x * sc, y: oy + y * sc }; }; // поворот на 90°·rot по часовой
    const mc = vc.map(map);
    for (let sh = 0; sh < 4; sh++) for (const dir of [1, -1]) {
      let e = 0; const ord = [];
      for (let i = 0; i < 4; i++) { const q = pc[((sh + dir * i) % 4 + 4) % 4]; ord.push(q); e = Math.max(e, Math.hypot(q.x - mc[i].x, q.y - mc[i].y)); }
      if (e < bestE) { bestE = e; best = ord; }
    }
  }
  if (!best || bestE > Math.hypot(W, Hh) * 0.15) return null;
  return { frame: { data: g.getImageData(0, 0, W, Hh).data, w: W, h: Hh }, corners: best };
}

function shoelace(c) { let a = 0; for (let i = 0; i < c.length; i++) { const p = c[i], q = c[(i + 1) % c.length]; a += p.x * q.y - q.x * p.y; } return a / 2; }

async function processScan() {
  const sc = S.scan, d = R.scan;
  const mine = sc.pal === 'mine' ? S.paints.filter(p => p.scan !== false) : [];
  const useMine = mine.length > 0;
  const key = `${sc.lines}|${sc.paint}|${sc.colors}|${sc.minSpot}|${sc.smooth}|${sc.lineBlack}|${sc.grad}|${sc.gap || 0}|${useMine ? mine.map(p => p.hex).join(',') : 'auto'}|${d.flatKey || 0}`;
  if (d.vec && d.vecKey === key) return;
  toast('Распознаю линии и цвета…', 4000); await sleep(20);
  const nCol = useMine ? mine.length : (sc.paint ? sc.colors : 0);
  d.seg = scan.segment(d.flat, d.ppm, { lineLevel: sc.lines, colors: nCol, minSpot: sc.minSpot, paint: nCol > 0, fixed: useMine ? mine.map(p => CL.hexToRgb(p.hex)) : null });
  if (useMine) d.seg.names = mine.map(p => p.name);
  toast('Перевожу в вектор…', 4000); await sleep(20);
  // своими красками — ровной заливкой (градиент дал бы оттенки, которых у тебя нет)
  d.vec = scan.vectorize(d.seg, d.ppm, { smooth: sc.smooth, lineBlack: sc.lineBlack, withColors: nCol > 0, gradients: sc.grad !== false && !useMine, img: d.flat, gap: sc.gap || 0 });
  d.vecKey = key; d.svgKB = null;
}

// ключ «что сейчас на экране» — по нему кэшируются превью и готовый файл
function scanKey(tab) {
  const sc = S.scan, d = R.scan;
  return tab === 'photo' ? `p|${sc.mode}|${sc.sharpen}|${sc.obscura || 0}|${sc.tone || 'none'}|${sc.lpi || 45}|${d.flatKey || 0}` : `${tab}|${d.vecKey}`;
}

function scanCanvasFor(tab, scale) {
  const d = R.scan;
  if (tab === 'photo') {
    const sc = S.scan, key = scanKey('photo');
    if (d.encKey !== key) { d.enc = scan.enhance(d.flat, { mode: sc.mode || 'color', sharpen: sc.sharpen ?? 0.6, clean: sc.clean, obscura: sc.obscura || 0, tone: sc.tone || 'none', ppm: d.ppm, lpi: sc.lpi || 45 }); d.encKey = key; d.encCanvas = null; }
    const c = d.encCanvas || (d.encCanvas = scan.imageDataCanvas(d.enc));
    if (scale === 1) return c;
    const o = document.createElement('canvas'); o.width = Math.round(c.width * scale); o.height = Math.round(c.height * scale);
    o.getContext('2d').drawImage(c, 0, 0, o.width, o.height); return o;
  }
  return scan.renderVector(d.vec, scale, { colors: tab === 'vec' });
}

// Поворот результата на 90° и смена пропорций листа (если ориентация угадана неверно:
// например, у края оторвана спираль или телефон повернут относительно листа).
function rotateImg(img, cw) {
  const { data, w, h } = img, out = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const nx = cw ? h - 1 - y : y, ny = cw ? x : w - 1 - x, i = (y * w + x) * 4, o = (ny * h + nx) * 4;
    out[o] = data[i]; out[o + 1] = data[i + 1]; out[o + 2] = data[i + 2]; out[o + 3] = data[i + 3];
  }
  return { data: out, w: h, h: w };
}
function swapAspect(img, ppm, pw, ph, margin = 2) {
  // лист выпрямлен с пропорцией pw×ph, а на самом деле он ph×pw: растягиваем внутреннюю
  // часть (поле по краю не трогаем) — это ровно то же, что выпрямить заново с другими размерами
  const m = Math.round(margin * ppm), W = Math.round(ph * ppm) + 2 * m, H = Math.round(pw * ppm) + 2 * m;
  const out = new Uint8ClampedArray(W * H * 4).fill(255);
  const iw = img.w - 2 * m, ih = img.h - 2 * m, ow = W - 2 * m, oh = H - 2 * m, src = img.data;
  for (let y = 0; y < oh; y++) {
    const fy = Math.min(ih - 1.001, (y + 0.5) * ih / oh - 0.5), y0 = Math.max(0, Math.floor(fy)), ty = Math.max(0, fy - y0);
    for (let x = 0; x < ow; x++) {
      const fx = Math.min(iw - 1.001, (x + 0.5) * iw / ow - 0.5), x0 = Math.max(0, Math.floor(fx)), tx = Math.max(0, fx - x0);
      const i00 = ((y0 + m) * img.w + x0 + m) * 4, i10 = i00 + 4, i01 = i00 + img.w * 4, i11 = i01 + 4, o = ((y + m) * W + x + m) * 4;
      for (let c = 0; c < 3; c++) out[o + c] = (src[i00 + c] * (1 - tx) + src[i10 + c] * tx) * (1 - ty) + (src[i01 + c] * (1 - tx) + src[i11 + c] * tx) * ty;
    }
  }
  return { data: out, w: W, h: H };
}

// Просмотр с зумом: щипок, двойной тап (×3 / вписать), колёсико, кнопки − ＋ ⤢.
// Во время жеста рисуется готовая картинка, после — вектор перерисовывается чётко под масштаб.
function zoomViewer(stage, onTap) {
  const cv = el('canvas', { class: 'zoom-canvas' }), g = cv.getContext('2d');
  const lbl = el('span', { class: 'zlbl' }, '100%');
  const ctl = el('div', { class: 'zoom-ctl' });
  stage.append(cv, ctl);
  let src = null, z = 1, cx = 0.5, cy = 0.5, hiT = 0;
  const pts = new Map(); let pinch = null, drag = null, lastTap = 0;
  const dims = () => { const r = stage.getBoundingClientRect(); return { W: r.width, H: r.height, r }; };
  const fit = () => { const { W, H } = dims(); return src ? Math.min((W - 12) / src.w, (H - 12) / src.h) : 1; };
  const clampC = () => { z = Math.max(1, Math.min(12, z)); const k = 0.5 / z; cx = z <= 1 ? 0.5 : Math.max(k, Math.min(1 - k, cx)); cy = z <= 1 ? 0.5 : Math.max(k, Math.min(1 - k, cy)); };
  const draw = (hq) => {
    if (!src) return;
    const { W, H } = dims(), dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const k = fit() * z, tx = W / 2 - cx * src.w * k, ty = H / 2 - cy * src.h * k;
    g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, cv.width, cv.height);
    g.setTransform(k * dpr, 0, 0, k * dpr, tx * dpr, ty * dpr);
    g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
    if (hq && src.hi && k * dpr > (src.bmpScale || 1) * 1.15) { g.save(); g.beginPath(); g.rect(0, 0, src.w, src.h); g.clip(); src.hi(g); g.restore(); }
    else g.drawImage(src.bmp, 0, 0, src.w, src.h);
    lbl.textContent = Math.round(z * 100) + '%';
  };
  const redraw = () => { draw(false); clearTimeout(hiT); hiT = setTimeout(() => draw(true), 160); };
  const toContent = (px, py) => { const { W, H, r } = dims(), k = fit() * z; return { x: cx * src.w + (px - r.left - W / 2) / k, y: cy * src.h + (py - r.top - H / 2) / k }; };
  const zoomAt = (f, px, py) => {
    if (!src) return;
    const a = toContent(px, py); z *= f; clampC();
    const { W, H, r } = dims(), k = fit() * z;
    cx = (a.x - (px - r.left - W / 2) / k) / src.w; cy = (a.y - (py - r.top - H / 2) / k) / src.h; clampC(); redraw();
  };
  cv.addEventListener('pointerdown', (e) => {
    cv.setPointerCapture(e.pointerId); pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, m: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } }; drag = null; }
    else if (pts.size === 1) drag = { x: e.clientX, y: e.clientY, x0: e.clientX, y0: e.clientY, moved: false };
  });
  cv.addEventListener('pointermove', (e) => {
    if (!pts.has(e.pointerId) || !src) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pts.size >= 2) {
      const [a, b] = [...pts.values()], d = Math.hypot(a.x - b.x, a.y - b.y) || 1, m = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const k = fit() * z; cx -= (m.x - pinch.m.x) / k / src.w; cy -= (m.y - pinch.m.y) / k / src.h;
      zoomAt(d / pinch.d, m.x, m.y); pinch = { d, m };
    } else if (drag) {
      if (Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) > 6) drag.moved = true;
      if (drag.moved && z > 1) { const k = fit() * z; cx -= (e.clientX - drag.x) / k / src.w; cy -= (e.clientY - drag.y) / k / src.h; clampC(); redraw(); }
      drag.x = e.clientX; drag.y = e.clientY;
    }
  });
  const up = (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.delete(e.pointerId);
    if (pinch) { if (pts.size < 2) pinch = null; drag = null; return; }
    if (drag && !drag.moved && src) {
      const now = performance.now();
      const c = toContent(e.clientX, e.clientY);
      if (c.x >= 0 && c.y >= 0 && c.x < src.w && c.y < src.h && onTap && onTap(c.x, c.y)) { lastTap = 0; drag = null; return; }
      if (now - lastTap < 320) { if (z > 1.2) { z = 1; clampC(); redraw(); } else zoomAt(3, e.clientX, e.clientY); lastTap = 0; }
      else lastTap = now;
    }
    drag = null;
  };
  cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
  cv.addEventListener('wheel', (e) => { e.preventDefault(); zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY); }, { passive: false });
  const center = (f) => { const { r } = dims(); zoomAt(f, r.left + r.width / 2, r.top + r.height / 2); };
  ctl.append(el('button', { class: 'zbtn', onclick: () => center(1 / 1.6) }, '−'), lbl, el('button', { class: 'zbtn', onclick: () => center(1.6) }, '+'),
    el('button', { class: 'zbtn', title: 'Вписать', onclick: () => { z = 1; clampC(); redraw(); } }, '⤢'));
  const ro = new ResizeObserver(() => redraw()); ro.observe(stage);
  return { ctl, set(s2) { const same = src && src.w === s2.w && src.h === s2.h; src = s2; if (!same) { z = 1; cx = cy = 0.5; } redraw(); } };
}

function openScanView() {
  if (!R.scan) return;
  closePanel();
  const v = $('scanView'); v.innerHTML = ''; v.classList.remove('hidden');
  const d = R.scan, sc = S.scan;
  const stage = el('div', { class: 'scan-stage' });
  const info = el('div', { class: 'scan-info' });
  const pickBar = el('div', { class: 'pick-bar hidden' });
  // зум: щипок двумя пальцами, двойной тап, колёсико, кнопки; пипетка — тап в режиме 🎯
  const zv = zoomViewer(stage, (x, y) => {
    if (!d.pick) return false;
    const src = d.flat, xi = Math.round(x * src.w / d.vw), yi = Math.round(y * src.h / d.vh);
    const c = avgAt(src, xi, yi, Math.max(1, Math.round(d.ppm * 0.6)));
    const hex = CL.rgbToHex(c); S.colorUI.cur = hex; persist();
    pickBar.innerHTML = ''; pickBar.classList.remove('hidden');
    pickBar.append(el('i', { class: 'sw', style: `background:${hex}` }), el('span', { class: 'grow' }, `${CL.colorName(hex)} ${hex}`),
      btn('➕ В мои краски', () => { addPaint(hex); toast('Добавлено в «Мои краски»'); }, 'small'),
      btn('🎨 Как смешать', () => { closeScanView(); openPanel('colors'); }, 'small'));
    return true;
  });
  const pickBtn = el('button', { class: 'zbtn', title: 'Пипетка: узнать цвет', onclick: () => { d.pick = !d.pick; pickBtn.classList.toggle('on', d.pick); toast(d.pick ? '🎯 Тапни по цвету на рисунке' : 'Пипетка выключена', 1800); } }, '🎯');
  zv.ctl.prepend(pickBtn);
  let idle = 0;
  const showPreview = async () => {
    if (d.tab !== 'photo') await processScan();
    // превью — холст с зумом, без кодирования в PNG; вектор при приближении перерисовывается чётко
    const base = d.tab === 'photo' ? 1 : Math.min(2, 1400 / Math.max(d.vec.w, d.vec.h));
    const c = scanCanvasFor(d.tab, base);
    const cw = d.tab === 'photo' ? d.flat.w : d.vec.w, ch = d.tab === 'photo' ? d.flat.h : d.vec.h;
    d.vw = cw; d.vh = ch;
    const vec = d.tab !== 'photo' ? d.vec : null, colors = d.tab === 'vec';
    zv.set({ bmp: c, w: cw, h: ch, hi: vec ? (g) => { g.fillStyle = '#fff'; g.fillRect(0, 0, cw, ch); scan.drawVector(g, vec, { colors }); } : null, bmpScale: d.tab === 'photo' ? (c.width / cw) : base });
    let txt = `${d.pw}×${d.ph} мм · ${d.ppm} пикс/мм (${R.scanInfo || 'кадры видео'})`;
    if (d.tab !== 'photo') {
      if (d.svgKB == null) d.svgKB = Math.round(scan.toSVG(d.vec, d.pw, d.ph).length / 1024);
      const nC = d.vec.colors.length;
      if (sc.pal === 'mine' && S.paints.some(p => p.scan !== false)) txt += ` · своими красками: ${nC}`;
      else txt += sc.paint && sc.colors > 0 ? ` · оттенков найдено ${nC} из ${sc.colors}` : '';
      txt += ` · SVG ≈ ${d.svgKB} КБ`;
    }
    info.textContent = txt;
    // пока человек смотрит на результат — заранее готовим файл, чтобы «Поделиться» сработало сразу
    clearTimeout(idle); idle = setTimeout(() => prepareExport().catch(() => {}), 700);
  };
  let t = 0;
  const redo = () => { clearTimeout(t); t = setTimeout(() => showPreview(), 250); };
  const refresh = () => { d.flatKey = (d.flatKey || 0) + 1; d.vec = null; d.exp = null; };
  // «Очистка фона» пересчитывает выравнивание фона из выпрямленного снимка
  const reflat = () => { clearTimeout(t); t = setTimeout(async () => { toast('Пересчитываю фон…', 3000); await sleep(20); d.flat = scan.flatten(d.rect, d.ppm, sc.clean); refresh(); await showPreview(); }, 300); };
  const geomChange = async (fn) => { toast('Поворачиваю…', 2500); await sleep(20); fn(); d.flat = scan.flatten(d.rect, d.ppm, sc.clean); refresh(); await showPreview(); };
  const ctl = el('div', { class: 'scan-ctl' });
  const buildCtl = () => {
    ctl.innerHTML = '';
    ctl.append(segRow('', [['photo', 'Скан'], ['vec', 'Рисунок (вектор)'], ['lines', 'Только линии']], d.tab, (x) => { d.tab = x; buildCtl(); showPreview(); }));
    if (d.tab === 'photo') {
      ctl.append(el('p', { class: 'note' }, 'Настоящий скан: лист выпрямлен, фон выровнен, ничего не перерисовано — штриховка и тени рисунка остаются.'));
      ctl.append(segRow('Цвет', [['color', 'Цветной'], ['gray', 'Серый'], ['bw', 'Ч/Б'], ['manga', 'Манга']], sc.mode || 'color', (x) => { sc.mode = x; persist(); buildCtl(); showPreview(); }));
      if (sc.mode === 'manga') ctl.append(el('p', { class: 'note' }, 'Манга: чистая тушь + серые тона переведены в точечный растр (скринтон), как в печатной манге. Только чёрное и белое — печатается без серой «грязи».'),
        rangeRow('Растр (LPI)', 25, 85, 5, sc.lpi || 45, (x) => { sc.lpi = x; persist(); clearTimeout(t); t = setTimeout(showPreview, 250); }, (x) => x + ' · ' + (x < 40 ? 'крупный' : x < 60 ? 'средний' : 'мелкий')));
      ctl.append(rangeRow('Резкость', 0, 1.5, 0.1, sc.sharpen ?? 0.6, (x) => { sc.sharpen = x; persist(); clearTimeout(t); t = setTimeout(showPreview, 200); }, (x) => Math.round(x * 100) + '%'));
      if (sc.mode !== 'bw' && sc.mode !== 'manga') {
        ctl.append(rangeRow('Старое фото (абскура)', 0, 1, 0.05, sc.obscura || 0, (x) => { sc.obscura = x; persist(); clearTimeout(t); t = setTimeout(showPreview, 250); }, (x) => x ? Math.round(x * 100) + '%' : 'нет'));
        ctl.append(segRow('Тон', [['none', 'Обычный'], ['sepia', 'Сепия'], ['cold', 'Холодный']], sc.tone || 'none', (x) => { sc.tone = x; persist(); showPreview(); }));
      }
    } else {
      ctl.append(el('p', { class: 'note' }, d.tab === 'vec' ? 'Рисунок заново собран из контуров (вектор): линии + пятна краски, можно с плавными переходами.' : 'Только линии рисунка — для раскраски или обводки.'));
      if (d.tab === 'vec') {
        const mineN = S.paints.filter(p => p.scan !== false).length;
        ctl.append(segRow('Палитра', [['auto', 'Подобрать самой'], ['mine', `Мои краски (${mineN})`]], sc.pal || 'auto', (x) => {
          if (x === 'mine' && !mineN) { toast('Сначала добавь свои краски в 🎨 Цвета'); buildCtl(); return; }
          sc.pal = x; persist(); buildCtl(); redo();
        }));
        if (sc.pal === 'mine' && mineN) ctl.append(el('div', { class: 'swatches mini' }, ...S.paints.filter(p => p.scan !== false).map(p => el('i', { style: `background:${p.hex}`, title: p.name }))),
          el('p', { class: 'note' }, 'Каждое пятно краски рисуется ближайшей из твоих красок (🖌 в «Цвета» — какие участвуют).'));
        else {
          ctl.append(rangeRow('Цветов краски', 0, 16, 1, sc.colors, (x) => { sc.colors = x; sc.paint = x > 0; persist(); redo(); }, (x) => x || 'нет'));
          ctl.append(toggleRow('Плавные переходы (градиенты)', sc.grad !== false, (x) => { sc.grad = x; persist(); redo(); }));
        }
      }
      ctl.append(rangeRow('Чувствительность линий', 0, 1, 0.05, sc.lines, (x) => { sc.lines = x; persist(); redo(); }, (x) => Math.round(x * 100) + '%'));
      ctl.append(rangeRow('Сглаживание краёв', 0, 3, 0.25, sc.smooth, (x) => { sc.smooth = x; persist(); redo(); }));
      ctl.append(rangeRow('Заполнить пробелы до', 0, 2, 0.1, sc.gap || 0, (x) => { sc.gap = x; persist(); redo(); }, (x) => x ? x.toFixed(1) + ' мм' : 'нет'));
      ctl.append(rangeRow('Убрать пятна меньше', 0, 20, 1, sc.minSpot, (x) => { sc.minSpot = x; persist(); redo(); }, (x) => x + ' мм²'));
      ctl.append(toggleRow('Линии чёрным', sc.lineBlack, (x) => { sc.lineBlack = x; persist(); redo(); }));
    }
    ctl.append(rangeRow('Очистка фона', 0, 1, 0.05, sc.clean, (x) => { sc.clean = x; persist(); reflat(); }, (x) => x < 0.3 ? 'мягко' : x <= 0.6 ? 'обычно' : 'сильно'));
    ctl.append(el('div', { class: 'btns' },
      btn('↻ 90°', () => geomChange(() => { d.rect = rotateImg(d.rect, true); [d.pw, d.ph] = [d.ph, d.pw]; })),
      btn(d.pw > d.ph ? '⇄ Это книжный лист' : '⇄ Это альбомный лист', () => geomChange(() => { d.rect = swapAspect(d.rect, d.ppm, d.pw, d.ph); [d.pw, d.ph] = [d.ph, d.pw]; buildCtl(); }))));
    ctl.append(segRow('Формат', d.tab === 'photo' ? [['png', 'PNG'], ['jpg', 'JPG']] : [['png', 'PNG'], ['jpg', 'JPG'], ['svg', 'SVG (вектор)']], d.tab === 'photo' && sc.fmt === 'svg' ? 'png' : sc.fmt, (x) => { sc.fmt = x; persist(); clearTimeout(idle); idle = setTimeout(() => prepareExport().catch(() => {}), 300); }));
    ctl.append(el('div', { class: 'btns' },
      btn('💾 Сохранить', () => exportScan(false), 'primary'),
      btn('📤 Поделиться', () => exportScan(true)),
      btn('↻ Переснять', () => { closeScanView(); runScan(); })));
  };
  buildCtl();
  v.append(el('div', { class: 'scan-head' }, el('h2', {}, '📥 Оцифровка'), el('button', { class: 'icon small', onclick: closeScanView, 'aria-label': 'Закрыть' }, '✕')), stage, pickBar, info, ctl);
  showPreview();
}
function closeScanView() { $('scanView').classList.add('hidden'); $('scanView').innerHTML = ''; if (R.scan) R.scan.pick = false; }

// Готовый файл кэшируется по ключу (вкладка + настройки + формат): повторное «Сохранить» /
// «Поделиться» ничего не пересчитывает. Готовится заранее, пока открыт результат.
async function prepareExport() {
  const d = R.scan, sc = S.scan;
  if (!d) return null;
  const fmt = d.tab !== 'photo' && sc.fmt === 'svg' ? 'svg' : sc.fmt === 'jpg' ? 'jpg' : 'png';
  if (d.tab !== 'photo') await processScan();
  const key = scanKey(d.tab) + '|' + fmt + '|' + d.pw + 'x' + d.ph;
  if (d.exp && d.exp.key === key) return d.exp.p;
  const p = (async () => {
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    let blob;
    if (fmt === 'svg') {
      const vec = d.tab === 'lines' ? { ...d.vec, colors: [] } : d.vec;
      blob = new Blob([scan.toSVG(vec, d.pw, d.ph)], { type: 'image/svg+xml' });
    } else {
      const c = scanCanvasFor(d.tab, d.tab === 'photo' ? 1 : 8 / d.ppm);
      blob = await new Promise(r => c.toBlob(r, fmt === 'jpg' ? 'image/jpeg' : 'image/png', 0.93));
    }
    const out = { blob, name: `reyka-${stamp}.${fmt}`, b64: null };
    if (window.ReykaNative && window.ReykaNative.saveFile) out.b64 = await blobB64(blob);
    return out;
  })();
  d.exp = { key, p };
  return p;
}
function blobB64(blob) { return new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(String(fr.result).split(',')[1]); fr.readAsDataURL(blob); }); }

async function exportScan(share) {
  toast(share ? 'Открываю «Поделиться»…' : 'Сохраняю…', 2500);
  await sleep(10);
  try {
    const r = await prepareExport();
    if (r) await saveBlob(r.blob, r.name, share, r.b64);
  } catch (e) { console.error(e); toast('Не получилось: ' + (e.message || e)); }
}

async function saveBlob(blob, name, share, b64pre) {
  const N = window.ReykaNative;
  if (N && N.saveFile) {
    const b64 = b64pre || await blobB64(blob);
    const msg = share ? N.shareFile(b64, name, blob.type) : N.saveFile(b64, name, blob.type);
    if (msg) toast(msg, 3500);
    return;
  }
  const file = new File([blob], name, { type: blob.type });
  if (share && navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title: 'Рисунок' }); return; } catch (e) { if (e && e.name === 'AbortError') return; }
  }
  const a = el('a', { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  toast('Сохранено: ' + name);
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
    panelBody.append(segRow('Наклон камеры в демо', [[0, '0°'], [30, '30°'], [45, '45°'], [60, '60°']], s.demoTilt || 0, (v) => { s.demoTilt = +v; S.corners = null; R.forceCalib = true; S.paper.tracking = true; S.manual.on = false; persist(); startSource(true); }));
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
window.__reyka = { S: () => S, R, addGuide, completeCorners, tracker, locateInPhoto, startSource, openPanel, setClean, measureTilt, findKalkaPerspective, runScan: () => runScan() };
