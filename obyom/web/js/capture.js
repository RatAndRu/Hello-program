// Объём — съёмка: камера, слежение за ковриком, автокадры, купол покрытия, AR-рамка объёма.
import { matLayout } from './mat.js';
import { detectMarkers, toGray } from './detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, camAngles, project } from './pose.js';
import { hasNativeCam, NativeCam } from './nativecam.js';

export const BANDS = [[8, 28], [28, 48], [48, 66], [66, 86]]; // пояса высоты камеры, градусы
export const AZ_BINS = 24;                                  // по 15°
const TRACK_W = 640;

export class Capture {
  constructor(video, overlay, opt) {
    this.video = video; this.ov = overlay; this.opt = opt; // {size, method:'walk'|'turn', Hb, onState, onShot, view}
    this.view = opt.view || null; // холст для показа кадров своей камеры (APK)
    // на вертушке — только кольцо меток: угловые метки неподвижны или лист свисает
    this.L = matLayout(opt.size || 'A4', opt.method === 'turn' ? 'round' : 'full');
    this.Lfull = matLayout(opt.size || 'A4', 'full'); // запасной вариант на вертушке: весь лист крутится вместе со столиком
    this.sharpMax = 0; this.ink = null; this.manual = false;
    this.cv = document.createElement('canvas'); this.cx = this.cv.getContext('2d', { willReadFrequently: true });
    this.shots = []; this.cells = new Map(); this.eqs = []; this.f = null;
    this.prev = null; this.running = false; this.paused = false; this.lastShot = 0;
  }
  async start() { await this.openCam(); this.running = true; this.loop(); }
  // Камера 1280×720 (в 1.5 «Лучше» просило Full HD — на части телефонов WebView тогда перестаёт обновлять кадры)
  async openCam() {
    // APK: своя камера (Camera2). Камера WebView на части телефонов «замирает», пока не коснёшься экрана.
    if (hasNativeCam()) {
      this.src = new NativeCam(this.view); await this.src.open(); this.native = true;
      // перезапуск камеры посреди съёмки — экспозиция снова фиксируется; новая съёмка — сначала свободная
      if (this.opt.torch) { this.torchOn = this.src.torch(true); if (!this.torchOn) this.opt.onTorchFail && this.opt.onTorchFail(); }
      this.src.lock(this.shots.length > 0 || (this.plates && this.plates.length > 0));
      this.video.style.display = 'none'; if (this.view) this.view.style.display = '';
      this.freshT = performance.now(); this.prevSig = null; this.woke = false;
      return;
    }
    this.native = false; this.src = this.video; this.video.style.display = ''; if (this.view) this.view.style.display = 'none';
    const c = { video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }, audio: false };
    this.stream = await navigator.mediaDevices.getUserMedia(c);
    this.video.srcObject = this.stream; this.video.muted = true; this.video.setAttribute('playsinline', '');
    await this.video.play();
    // попросим камеру держать фокус на ближнем расстоянии, если умеет
    try { const tr = this.stream.getVideoTracks()[0], cap = tr.getCapabilities ? tr.getCapabilities() : {}; if (cap.focusMode && cap.focusMode.includes('continuous')) await tr.applyConstraints({ advanced: [{ focusMode: 'continuous' }] }); } catch (e) {}
    this.freshT = performance.now(); this.prevSig = null; this.woke = false;
  }
  // Сторож: живая камера всегда шумит, поэтому два подряд совершенно одинаковых кадра = кадры не обновляются.
  // Такой кадр не анализируем (иначе на экране «застывшие» метки), через 1.5 с будим видео, через 4 с перезапускаем камеру.
  async revive(now) {
    const stale = now - this.freshT;
    if (stale > 1500 && !this.woke) { this.woke = true; if (!this.native) try { await this.video.play(); } catch (e) {} }
    if (stale > 4000 && !this.restarting && (this.restarts || 0) < 5) {
      this.restarting = true; this.restarts = (this.restarts || 0) + 1;
      try { this.closeCam(); await new Promise((r) => setTimeout(r, 300)); if (this.running) await this.openCam(); }
      catch (e) { console.warn('камера', e); }
      this.restarting = false;
    }
  }
  // ручной затвор: снимет ближайший кадр, где виден коврик (даже если эта ячейка купола уже есть)
  shootNow() { this.manual = true; }
  closeCam() { if (this.native && this.src) this.src.close(); if (this.stream) this.stream.getTracks().forEach((t) => t.stop()); this.stream = null; }
  stop() { this.running = false; if (this.native && this.src) { if (this.torchOn) this.src.torch(false); this.src.lock(false); } this.closeCam(); }
  // С первого снимка экспозиция и баланс белого зафиксированы (своя камера APK): все кадры одной яркости и цвета —
  // иначе телефон подкручивает их при каждом повороте, и сплэты/текстура «запоминают» пятна яркости.
  lockExposure() { if (this.native && this.src && !this.src.locked) this.expLocked = this.src.lock(true); }
  // кадр источника (своя камера или <video>) в холст w×h
  drawSrc(c, w, h) { if (this.native) this.src.drawTo(c, w, h); else c.drawImage(this.video, 0, 0, w, h); }
  get srcEl() { return this.native ? this.src : this.video; }
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
  // Таймер старта: после нажатия «▶» съёмка начнётся через delay секунд (успеть раскрутить столик и убрать руку)
  arm(delay = 0) { this.paused = false; this.startAt = performance.now() + delay * 1000; this.lastDir = null; this.theta = 0; this.blind = 0; }
  // насколько сдвинулся ракурс, градусы. Вертушка — по повороту столика (азимут) или подъёму держателя;
  // с рук — угол между направлениями на камеру.
  progress(a0, a1) {
    if (this.opt.method === 'turn') { const daz = Math.abs(((a1.az - a0.az + 540) % 360) - 180); return Math.max(daz, Math.abs(a1.el - a0.el)); }
    return angDeg(a0.c, a1.c);
  }
  async step() {
    const v = this.srcEl, vw = v.videoWidth, vh = v.videoHeight; if (!vw) return;
    const w = TRACK_W, h = Math.round(vh * w / vw);
    if (this.cv.width !== w || this.cv.height !== h) { this.cv.width = w; this.cv.height = h; }
    this.drawSrc(this.cx, w, h);
    const img = this.cx.getImageData(0, 0, w, h), g = toGray(new Uint8Array(img.data.buffer), w, h);
    const now = performance.now();
    // свежий ли кадр: «подпись» из редкой выборки пикселей
    let sig = 0, diff = 0; const ps = this.prevSig, n = Math.floor(g.length / 97), cur = new Uint8Array(n);
    for (let k = 0; k < n; k++) { const v2 = g[k * 97]; cur[k] = v2; if (ps) diff += Math.abs(v2 - ps[k]); sig += v2; }
    this.prevSig = cur;
    if (!ps || diff > 0) { this.freshT = now; this.woke = false; this.restarts = 0; }
    else {
      // тот же кадр: не анализируем; если так уже долго — чиним камеру
      const stale = now - this.freshT;
      if (stale > 1000) { const st = { ...(this.state || {}), stale: Math.round(stale / 100) / 10, found: false, ms: [], R: null, count: this.shots.length, coverage: this.coverage(), why: 'камера не присылает новые кадры' }; this.state = st; this.draw(st); this.opt.onState && this.opt.onState(st); }
      this.revive(now);
      return;
    }
    const ms = detectMarkers(g, w, h);
    // Фокус. Догадка — по ДЛИННОЙ стороне кадра (телефон в держателе стоит вертикально: кадр 720×1280,
    // а «0.75 × ширина» занижала фокус в 1.7 раза → поза не сходилась никогда: «поза неточная» на любом ракурсе).
    // Уточнение — по гомографиям коврика: они от фокуса не зависят, поэтому уравнения копятся с любого кадра
    // с ≥3 метками, а не только с уже «сошедшейся» позой (иначе замкнутый круг).
    if (this.fDims !== w + 'x' + h) { this.fDims = w + 'x' + h; this.eqs = []; this.f = null; }
    const L0 = Math.max(w, h);
    let f = this.f || 0.75 * L0, K = { fx: f, fy: f, cx: w / 2, cy: h / 2 };
    let p = ms.length ? poseFromMarkers(ms, this.L, K) : null;
    if (p && p.n >= 3 && p.H && this.eqs.length < 600) {
      this.eqs.push(...focalEqs(p.H, w / 2, h / 2));
      if (this.eqs.length >= 6) { const nf = focalFromEqs(this.eqs); if (nf > 0.4 * L0 && nf < 2 * L0) this.f = nf; }
    }
    if (p && p.rms >= 3 && this.f && Math.abs(this.f - f) > 0.02 * f) { f = this.f; K = { fx: f, fy: f, cx: w / 2, cy: h / 2 }; p = poseFromMarkers(ms, this.L, K); }
    const ringN = ms.filter((m) => m.id < 16).length;
    // вертушка: по кольцу не вышло — пробуем весь лист (если он крутится целиком, угловые метки тоже годятся;
    // если лист свисает/гнётся — поза не сойдётся и будет отброшена)
    if (this.opt.method === 'turn' && (!p || p.n < 2 || p.rms >= 3) && ms.length > ringN) { const q = poseFromMarkers(ms, this.Lfull, K); if (q && q.n >= 2 && q.rms < 2.5) p = q; }
    const dt = this.lastT ? Math.min(1, (now - this.lastT) / 1000) : 0; this.lastT = now;
    if (dt > 0) this.fps = this.fps ? this.fps * 0.9 + 0.1 / dt : 1 / dt; // скорость слежения, кадров/с
    const turn = this.opt.method === 'turn', step = this.opt.step || (turn ? 8 : 10);
    const st = { native: !!this.native, camFps: this.native ? this.src.fps : null, found: false, markers: ms.length, ring: ringN, poseRms: p ? p.rms : null, poseN: p ? p.n : 0, w, h, ms, count: this.shots.length, fps: this.fps || 0, step, restarts: this.restarts || 0 };
    let a = null, sh;
    if (p && p.n >= 2 && p.rms < 3) {
      a = camAngles(p.R, p.t);
      // скорость: угол между направлениями на камеру (в системе коврика) за секунду
      let speed = 0;
      if (this.prev) speed = this.progress(this.prev.a, a) / Math.max(0.03, (now - this.prev.t) / 1000);
      this.prev = { a, t: now };
      this.omega = this.omega == null ? speed : this.omega * 0.5 + speed * 0.5; this.poseT = now;
      Object.assign(st, { found: true, R: p.R, t: p.t, K, az: a.az, el: a.el, dist: a.dist, speed: this.omega, n: p.n, cell: this.cellOf(a), slow: true });
      sh = sharpness(g, w, h, this.cylBox(p.R, p.t, K, w, h));
    } else {
      this.prev = null;
      sh = sharpness(g, w, h, [(w * 0.2) | 0, (h * 0.2) | 0, (w * 0.8) | 0, (h * 0.8) | 0]);
    }
    // резкость сравниваем с последними ~8 кадрами (а не с рекордом за всё время — иначе при вращении не снимет никогда)
    (this.shHist = this.shHist || []).push(sh); if (this.shHist.length > 8) this.shHist.shift();
    const shMax = Math.max(...this.shHist);
    // ---- когда снимать: по пройденному углу. Медленнее крутится — реже кадры. Ограничения скорости нет. ----
    let why = '', due = false, blindShot = false;
    if (this.paused) why = 'пауза — нажми ▶';
    else if (this.startAt && now < this.startAt) { why = `старт через ${Math.ceil((this.startAt - now) / 1000)} с`; st.countdown = Math.ceil((this.startAt - now) / 1000); }
    else if (a) {
      this.blind = 0;
      const prog = this.lastDir ? this.progress(this.lastDir, a) : Infinity; this.theta = prog === Infinity ? 0 : prog;
      st.prog = prog;
      if (this.opt.close && p.n < 3) why = 'крупный план: нужно хотя бы 3 метки в кадре';
      else if (prog >= step) due = true;
      else if (this.omega < 1) why = turn ? 'столик стоит — крутни ещё раз (или подними держатель)' : 'стоишь на месте — иди дальше по кругу';
      else why = `жду поворота: ${prog.toFixed(0)}° из ${step}°`;
    } else if (this.poseT && now - this.poseT < 3000 && this.omega > 2 && this.lastDir) {
      // метки на миг потерялись (смаз) — досчитываем угол по последней скорости с замедлением
      this.omega *= Math.exp(-dt / 5); this.theta += this.omega * dt;
      if (this.theta >= step && this.blind < 6) { due = true; blindShot = true; }
      else why = 'метки смазаны — досчитываю поворот';
    } else why = !ms.length ? 'коврик не виден' : (p && p.n >= 2 ? `поза неточная (${p.rms.toFixed(1)} пикс) — смаз или блик` : `видно меток ${ms.length}${this.opt.method === 'turn' ? `, из круга ${ringN}` : ''} — нужно 2`);
    if (due && now - this.lastShot < 150) { due = false; why = 'слишком часто'; }
    if (due) {
      this.dueFrames = (this.dueFrames || 0) + 1;
      // подождём до 3 кадров слежения, если текущий заметно мутнее соседних
      if (sh < 0.8 * shMax && this.dueFrames <= 3) { due = false; why = 'кадр смазан — жду резкий'; }
    }
    const manual = this.manual && !this.paused;
    if (due || manual) {
      this.manual = false; this.dueFrames = 0;
      this.lastShot = now;
      if (a) { this.lastDir = a; this.theta = 0; } else { this.theta = 0; this.blind++; }
      if (st.cell && !this.cells.has(st.cell)) this.cells.set(st.cell, this.shots.length);
      this.lockExposure();
      const blob = await this.grab();
      this.shots.push({ blob, az: a ? a.az : null, el: a ? a.el : null, manual, blind: blindShot });
      st.count = this.shots.length; st.shot = true; why = '';
      this.opt.onShot && this.opt.onShot(this.shots.length, a, manual);
    }
    st.why = why; st.sharp = sh >= 0.8 * shMax;
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
    // крупный план: полноразмерный снимок камеры (в 3–4 раза больше деталей на текстуре), если APK умеет
    if (this.opt.close && this.native && this.src && this.src.still) { const b = await this.src.still(); if (b) return b; }
    const v = this.srcEl, W = Math.min(1280, v.videoWidth), H = Math.round(v.videoHeight * W / v.videoWidth);
    const c = document.createElement('canvas'); c.width = W; c.height = H; this.drawSrc(c.getContext('2d'), W, H);
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

const angDeg = (c0, c1) => { const d0 = Math.hypot(...c0), d1 = Math.hypot(...c1); return Math.acos(Math.max(-1, Math.min(1, (c0[0] * c1[0] + c0[1] * c1[1] + c0[2] * c1[2]) / (d0 * d1)))) * 180 / Math.PI; };
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
