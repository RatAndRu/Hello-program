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
    this.L = matLayout(opt.size || 'A4');
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
      const cell = this.cellOf(a), slow = speed < (this.opt.method === 'turn' ? 14 : 18);
      st.slow = slow; st.cell = cell;
      if (!this.paused && cell && !this.cells.has(cell) && slow && p.n >= 3 && now - this.lastShot > 350 && this.shots.length < 120) {
        this.lastShot = now; this.cells.set(cell, this.shots.length);
        const blob = await this.grab();
        this.shots.push({ blob, az: a.az, el: a.el });
        st.count = this.shots.length; st.shot = true;
        this.opt.onShot && this.opt.onShot(this.shots.length, a);
      }
    } else this.prev = null;
    st.coverage = this.coverage();
    this.state = st;
    this.draw(st);
    this.opt.onState && this.opt.onState(st);
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
