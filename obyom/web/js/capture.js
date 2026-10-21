// Объём — съёмка: камера, слежение за ковриком, автокадры, купол покрытия, AR-рамка объёма.
import { matLayout } from './mat.js';
import { detectMarkers, toGray } from './detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, camAngles, project } from './pose.js';

export const BANDS = [[8, 28], [28, 48], [48, 66], [66, 86]]; // пояса высоты камеры, градусы
export const AZ_BINS = 24;                                  // по 15°
const TRACK_W = 640;

export class Capture {
  constructor(video, overlay, opt) {
    this.video = video; this.ov = overlay; this.opt = opt; // {size, method:'walk'|'turn', Hb, onState, onShot}
    // на вертушке — только кольцо меток: угловые метки неподвижны или лист свисает
    this.L = matLayout(opt.size || 'A4', opt.method === 'turn' ? 'round' : 'full');
    this.sharpMax = 0; this.ink = null; this.manual = false;
    this.cv = document.createElement('canvas'); this.cx = this.cv.getContext('2d', { willReadFrequently: true });
    this.shots = []; this.cells = new Map(); this.eqs = []; this.f = null;
    this.prev = null; this.running = false; this.paused = false; this.lastShot = 0;
  }
  async start() {
    const c = { video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }, audio: false };
    this.stream = await navigator.mediaDevices.getUserMedia(c);
    this.video.srcObject = this.stream; this.video.muted = true; this.video.setAttribute('playsinline', '');
    await this.video.play();
    // попросим камеру держать фокус на ближнем расстоянии, если умеет
    try { const tr = this.stream.getVideoTracks()[0], cap = tr.getCapabilities ? tr.getCapabilities() : {}; if (cap.focusMode && cap.focusMode.includes('continuous')) await tr.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (e) {}
    this.running = true; this.loop();
  }
  // ручной затвор: снимет ближайший кадр, где виден коврик (даже если эта ячейка купола уже есть)
  shootNow() { this.manual = true; }
  stop() { this.running = false; if (this.stream) this.stream.getTracks().forEach((t) => t.stop()); this.stream = null; }
  coverage() {
    // доля заполненных ячеек по поясам
    const per = BANDS.map(() => 0);
    for (const k of this.cells.keys()) { const b = +k.split(':')[0]; per[b]++; }
    return per.map((n) => n / AZ_BINS);
  }
  cellOf(a) { let b = BANDS.findIndex(([lo, hi]) => a.el >= lo && a.el < hi); if (b < 0) return null; return `${b}:${Math.floor(a.az / (360 / AZ_BINS)) % AZ_BINS}`; }
  async loop() {
    while (this.running) {
      const t0 = performance.now();
      try { await this.step(); } catch (e) { console.warn(e); }
      const dt = performance.now() - t0;
      await new Promise((r) => setTimeout(r, Math.max(10, 60 - dt)));
    }
  }
  async step() {
    const v = this.video, vw = v.videoWidth, vh = v.videoHeight; if (!vw) return;
    const w = TRACK_W, h = Math.round(vh * w / vw);
    if (this.cv.width !== w || this.cv.height !== h) { this.cv.width = w; this.cv.height = h; }
    this.cx.drawImage(v, 0, 0, w, h);
    const img = this.cx.getImageData(0, 0, w, h), g = toGray(new Uint8Array(img.data.buffer), w, h);
    const ms = detectMarkers(g, w, h);
    const f = this.f || 0.75 * w, K = { fx: f, fy: f, cx: w / 2, cy: h / 2 };
    const p = ms.length ? poseFromMarkers(ms, this.L, K) : null;
    const now = performance.now();
    const st = { found: !!p, markers: ms.length, w, h, ms, count: this.shots.length };
    if (p && p.n >= 2 && p.rms < 3) {
      if (this.eqs.length < 400 && p.n >= 3) { this.eqs.push(...focalEqs(p.H, w / 2, h / 2)); if (this.eqs.length >= 12) { const nf = focalFromEqs(this.eqs); if (nf > 0.45 * w && nf < 1.6 * w) this.f = nf; } }
      const a = camAngles(p.R, p.t);
      // скорость: угол между направлениями на камеру за секунду
      let speed = 0;
      if (this.prev) { const c0 = this.prev.a.c, c1 = a.c, d0 = Math.hypot(...c0), d1 = Math.hypot(...c1); const cos = (c0[0] * c1[0] + c0[1] * c1[1] + c0[2] * c1[2]) / (d0 * d1); speed = Math.acos(Math.min(1, cos)) * 180 / Math.PI / Math.max(0.03, (now - this.prev.t) / 1000); }
      this.prev = { a, t: now };
      Object.assign(st, { R: p.R, t: p.t, K, az: a.az, el: a.el, dist: a.dist, speed, n: p.n });
      // На вертушке скорость считается по повороту коврика; рука крутит рывком — порог мягче,
      // а смаз ловит проверка резкости.
      const turn = this.opt.method === 'turn', lim = turn ? 30 : 16;
      const cell = this.cellOf(a), slow = speed < lim;
      const sh = sharpness(g, w, h, this.cylBox(R_(p), p.t, K, w, h));
      this.sharpMax = Math.max(this.sharpMax * 0.997, sh);
      const sharp = sh >= (turn ? 0.7 : 0.75) * this.sharpMax;
      Object.assign(st, { slow, cell, sharp, sh, lim });
      let why = '';
      if (this.paused) why = 'пауза';
      else if (this.shots.length >= 120) why = 'уже 120 кадров — хватит';
      else if (!cell) why = a.el < BANDS[0][0] ? 'камера слишком низко' : 'камера слишком высоко';
      else if (p.n < 3) why = `видно мало меток (${p.n}, нужно 3)`;
      else if (!slow) why = `быстро: ${speed.toFixed(0)}°/с, нужно < ${lim}`;
      else if (!sharp) why = 'кадр смазан — подожди долю секунды';
      else if (this.cells.has(cell)) why = turn ? 'этот угол уже снят — крути дальше' : 'этот угол уже снят — иди дальше';
      else if (now - this.lastShot <= 350) why = 'пауза между кадрами';
      st.why = why;
      const manual = this.manual && !this.paused && this.shots.length < 150;
      if ((!why || manual)) {
        this.manual = false;
        this.lastShot = now; if (cell && !this.cells.has(cell)) this.cells.set(cell, this.shots.length);
        const blob = await this.grab();
        this.shots.push({ blob, az: a.az, el: a.el, manual });
        st.count = this.shots.length; st.shot = true; st.why = '';
        this.opt.onShot && this.opt.onShot(this.shots.length, a, manual);
      }
    } else { this.prev = null; st.why = ms.length ? `видно мало меток (${ms.length})` : 'коврик не виден'; }
    // контраст печати: насколько чёрное на метках действительно чёрное (p10/p90 яркости внутри метки)
    if (ms.length) { const r = inkRatio(g, w, h, ms); if (r != null) this.ink = this.ink == null ? r : this.ink * 0.9 + r * 0.1; }
    st.ink = this.ink;
    st.coverage = this.coverage();
    this.state = st;
    this.draw(st);
    this.opt.onState && this.opt.onState(st);
  }
  // рамка (в пикселях кадра) вокруг рабочего объёма — там меряем резкость
  cylBox(R, t, K, w, h) {
    const Rb = 55 * this.L.k, Hb = this.opt.Hb || 90 * this.L.k; let x0 = w, y0 = h, x1 = 0, y1 = 0;
    for (const z of [0, Hb]) for (let i = 0; i < 8; i++) {
      const X = Rb * Math.cos(i * Math.PI / 4), Y = Rb * Math.sin(i * Math.PI / 4);
      if (R[6] * X + R[7] * Y + R[8] * z + t[2] < 5) continue;
      const q = project(K, R, t, X, Y, z); x0 = Math.min(x0, q[0]); y0 = Math.min(y0, q[1]); x1 = Math.max(x1, q[0]); y1 = Math.max(y1, q[1]);
    }
    return [Math.max(1, x0 | 0), Math.max(1, y0 | 0), Math.min(w - 2, x1 | 0), Math.min(h - 2, y1 | 0)];
  }
  async grab() {
    const v = this.video, W = Math.min(1280, v.videoWidth), H = Math.round(v.videoHeight * W / v.videoWidth);
    const c = document.createElement('canvas'); c.width = W; c.height = H; c.getContext('2d').drawImage(v, 0, 0, W, H);
    return await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.92));
  }
  // наложение: метки, цилиндр рабочего объёма, стрелка «перед»
  draw(st) {
    const ov = this.ov, v = this.video, dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = Math.round(ov.clientWidth * dpr), H = Math.round(ov.clientHeight * dpr);
    if (ov.width !== W || ov.height !== H) { ov.width = W; ov.height = H; }
    const c = ov.getContext('2d'); c.clearRect(0, 0, W, H);
    if (!st.w) return;
    // видео показано как object-fit: cover
    const s = Math.max(W / st.w, H / st.h), ox = (W - st.w * s) / 2, oy = (H - st.h * s) / 2;
    const P = (x, y) => [ox + x * s, oy + y * s];
    c.lineWidth = 2 * dpr;
    for (const m of st.ms) { c.strokeStyle = 'rgba(80,220,140,.9)'; c.beginPath(); m.corners.forEach((q, i) => { const [x, y] = P(q[0], q[1]); i ? c.lineTo(x, y) : c.moveTo(x, y); }); c.closePath(); c.stroke(); }
    if (!st.R) return;
    const Rb = 55 * this.L.k, Hb = this.opt.Hb || 90 * this.L.k;
    const pr = (X, Y, Z) => { const R = st.R, t = st.t; if (R[6] * X + R[7] * Y + R[8] * Z + t[2] < 5) return null; const q = project(st.K, R, t, X, Y, Z); return P(q[0], q[1]); };
    c.strokeStyle = st.slow ? 'rgba(255,210,80,.85)' : 'rgba(255,90,70,.9)';
    for (const z of [0, Hb]) { c.beginPath(); let first = true; for (let i = 0; i <= 48; i++) { const a = i / 48 * Math.PI * 2, q = pr(Rb * Math.cos(a), Rb * Math.sin(a), z); if (!q) { first = true; continue; } first ? c.moveTo(...q) : c.lineTo(...q); first = false; } c.stroke(); }
    for (let i = 0; i < 8; i++) { const a = i / 8 * Math.PI * 2, q0 = pr(Rb * Math.cos(a), Rb * Math.sin(a), 0), q1 = pr(Rb * Math.cos(a), Rb * Math.sin(a), Hb); if (q0 && q1) { c.beginPath(); c.moveTo(...q0); c.lineTo(...q1); c.stroke(); } }
  }
}

const R_ = (p) => p.R;
// резкость: средний модуль лапласиана в рамке, нормированный на яркость
export function sharpness(g, w, h, bb) {
  let [x0, y0, x1, y1] = bb; if (x1 - x0 < 8 || y1 - y0 < 8) { x0 = 1; y0 = 1; x1 = w - 2; y1 = h - 2; }
  let s = 0, m = 0, n = 0;
  for (let y = y0; y <= y1; y += 2) for (let x = x0; x <= x1; x += 2) { const i = y * w + x, v = g[i]; s += Math.abs(4 * v - g[i - 1] - g[i + 1] - g[i - w] - g[i + w]); m += v; n++; }
  return n ? s / (m / n + 10) : 0;
}
// p10/p90 яркости внутри найденных меток: ~0.1 — чёрный, > 0.4 — бледная печать
export function inkRatio(g, w, h, ms) {
  const rs = [];
  for (const m of ms) {
    const xs = m.corners.map((c) => c[0]), ys = m.corners.map((c) => c[1]);
    const x0 = Math.max(0, Math.min(...xs) | 0), x1 = Math.min(w - 1, Math.max(...xs) | 0), y0 = Math.max(0, Math.min(...ys) | 0), y1 = Math.min(h - 1, Math.max(...ys) | 0);
    if (x1 - x0 < 6 || y1 - y0 < 6) continue;
    const v = []; for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) v.push(g[y * w + x]);
    v.sort((a, b) => a - b); const p10 = v[(v.length * 0.1) | 0], p90 = v[(v.length * 0.9) | 0];
    if (p90 > 20) rs.push(p10 / p90);
  }
  if (!rs.length) return null; rs.sort((a, b) => a - b); return rs[rs.length >> 1];
}
export function inkLabel(r) { if (r == null) return ''; return r < 0.22 ? 'печать: чёрный отлично' : r < 0.4 ? 'печать: чёрный норм' : 'печать бледная — ярче свет или печать темнее'; }

// купол покрытия: вид сверху, кольца = пояса высоты (внешнее — низкое), сектора = азимут
export function drawDome(canvas, cells, cur) {
  const dpr = Math.min(2, window.devicePixelRatio || 1), S = Math.round(canvas.clientWidth * dpr);
  if (canvas.width !== S) { canvas.width = S; canvas.height = S; }
  const c = canvas.getContext('2d'), R = S / 2 - 2 * dpr, cx = S / 2, cy = S / 2;
  c.clearRect(0, 0, S, S);
  c.fillStyle = 'rgba(0,0,0,.45)'; c.beginPath(); c.arc(cx, cy, R, 0, Math.PI * 2); c.fill();
  const nb = BANDS.length, ring = (b) => [R * (1 - b / nb), R * (1 - (b + 1) / nb) + 1];
  for (let b = 0; b < nb; b++) for (let k = 0; k < AZ_BINS; k++) {
    const [r0, r1] = ring(b), a0 = -Math.PI / 2 + k / AZ_BINS * Math.PI * 2, a1 = a0 + Math.PI * 2 / AZ_BINS;
    c.beginPath(); c.arc(cx, cy, r0, a0, a1); c.arc(cx, cy, r1, a1, a0, true); c.closePath();
    c.fillStyle = cells.has(`${b}:${k}`) ? (b === nb - 1 ? 'rgba(120,200,255,.9)' : 'rgba(90,220,140,.85)') : 'rgba(255,255,255,.07)';
    c.fill(); c.strokeStyle = 'rgba(0,0,0,.35)'; c.lineWidth = 1; c.stroke();
  }
  if (cur && cur.az != null) {
    const b = Math.max(0, Math.min(nb - 0.01, BANDS.findIndex(([lo, hi]) => cur.el >= lo && cur.el < hi) + 0.5));
    const r = cur.el >= BANDS[nb - 1][1] ? 0 : R * (1 - (b < 0 ? 0 : b) / nb), a = -Math.PI / 2 + cur.az / 360 * Math.PI * 2;
    c.fillStyle = '#fff'; c.beginPath(); c.arc(cx + r * Math.cos(a), cy + r * Math.sin(a), 4 * dpr, 0, Math.PI * 2); c.fill();
  }
}

let actx = null;
export function beep(freq = 880, dur = 0.06, vol = 0.15) {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const o = actx.createOscillator(), g = actx.createGain(); o.frequency.value = freq; o.type = 'sine';
    g.gain.setValueAtTime(vol, actx.currentTime); g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + dur);
    o.connect(g).connect(actx.destination); o.start(); o.stop(actx.currentTime + dur + 0.02);
  } catch (e) {}
}
