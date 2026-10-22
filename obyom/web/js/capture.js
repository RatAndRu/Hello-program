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
    // v2.7: качество кадра в ячейке купола (1=хороший, 0=смазанный/слабый)
    this.cellQual = new Map();
    this.sharpMax = 0; this.ink = null; this.manual = false;
    this.cv = document.createElement('canvas'); this.cx = this.cv.getContext('2d', { willReadFrequently: true });
    this.shots = []; this.cells = new Map(); this.eqs = []; this.f = null;
    this.prev = null; this.running = false; this.paused = false; this.lastShot = 0;
    // v2.7: пипетка и силуэт
    this.objColor = opt.objColor || null; // [r,g,b] 0..255, подсказка «цвет однотонного предмета»
    this.pipette = false; // режим пипетки: тап по кадру — замер цвета
    this._pipCb = null;
    this.ov.addEventListener('click', (e) => this._onOverlayTap(e));
    // v2.8: перетаскиваемое солнце на оверлее — подсказка направления света для AR-предпросмотра
    this.sunDragging = false; this.sunPos = null;
    this.ov.addEventListener('pointerdown', (e) => this._sunDown(e));
    this.ov.addEventListener('pointermove', (e) => this._sunMove(e));
    const upFn = () => { this.sunDragging = false; };
    this.ov.addEventListener('pointerup', upFn); this.ov.addEventListener('pointercancel', upFn);
  }
  // Тап по overlay: в режиме пипетки замеряет цвет предмета в точке тапа и выходит из пипетки
  _onOverlayTap(e) {
    if (!this.pipette || !this.state) return;
    const ov = this.ov, rect = ov.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width * (this.state.w || 1);
    const y = (e.clientY - rect.top) / rect.height * (this.state.h || 1);
    const ix = Math.max(2, Math.min((this.state.w || 0) - 3, Math.round(x)));
    const iy = Math.max(2, Math.min((this.state.h || 0) - 3, Math.round(y)));
    if (!this.state.rgba) { this.pipette = false; if (this._pipCb) this._pipCb(null); return; }
    // медианный цвет в окне 7×7
    const w = this.state.w, buf = this.state.rgba;
    const rs=[], gs=[], bs=[];
    for (let dy=-3;dy<=3;dy++) for(let dx=-3;dx<=3;dx++){
      const i=((iy+dy)*w+(ix+dx))*4; rs.push(buf[i]); gs.push(buf[i+1]); bs.push(buf[i+2]);
    }
    rs.sort((a,b)=>a-b); gs.sort((a,b)=>a-b); bs.sort((a,b)=>a-b);
    this.objColor=[rs[rs.length>>1], gs[gs.length>>1], bs[bs.length>>1]];
    this.pipette=false; if(this._pipCb) this._pipCb(this.objColor);
  }
  setPipette(on, cb){ this.pipette=!!on; this._pipCb=cb||null; }
  getSunDir() { // единичный 2D-вектор направления света в координатах кадра
    if (!this.state || !this.state.w || !this.sunPos) return null;
    const W=this.state.w, H=this.state.h;
    const dx=(this.sunPos[0]-W/2)/(Math.min(W,H)/2), dy=(this.sunPos[1]-H/2)/(Math.min(W,H)/2);
    const l=Math.hypot(dx,dy); if (l<0.05) return null;
    return [dx/l,dy/l];
  }
  _sunDown(e){
    if (!this.state || !this.state.w) return;
    const dpr=Math.min(2, window.devicePixelRatio||1);
    const r=this.ov.getBoundingClientRect();
    const ex=(e.clientX-r.left)*dpr, ey=(e.clientY-r.top)*dpr;
    const sp=this._sunScreen(); if (!sp) return;
    if (Math.hypot(ex-sp[0], ey-sp[1]) < 30*dpr) { this.sunDragging=true; try{this.ov.setPointerCapture(e.pointerId);}catch(ee){} e.preventDefault(); }
  }
  _sunMove(e){
    if (!this.sunDragging) return;
    const dpr=Math.min(2, window.devicePixelRatio||1);
    const r=this.ov.getBoundingClientRect();
    const ex=(e.clientX-r.left)*dpr, ey=(e.clientY-r.top)*dpr;
    const W=this.ov.width, H=this.ov.height;
    const st=this.state; if (!st || !st.w) return;
    const s=Math.max(W/st.w, H/st.h), ox=(W-st.w*s)/2, oy=(H-st.h*s)/2;
    const fx=(ex-ox)/s, fy=(ey-oy)/s;
    this.sunPos=[Math.max(0,Math.min(st.w,fx)), Math.max(0,Math.min(st.h,fy))];
  }
  _sunScreen(){
    if (!this.sunPos || !this.state || !this.state.w) return null;
    const W=this.ov.width, H=this.ov.height, st=this.state;
    const s=Math.max(W/st.w, H/st.h), ox=(W-st.w*s)/2, oy=(H-st.h*s)/2;
    return [ox+this.sunPos[0]*s, oy+this.sunPos[1]*s];
  }
  async _bgPrepLoop() {
    while (!this._prepCanceled && (this.running || this.prepped.length < this.shots.length)) {
      const i = this.prepped.length;
      if (i >= this.shots.length) { await new Promise(r => setTimeout(r, 80)); continue; }
      try { this.prepped.push(await _prepFrame(this.shots[i].blob)); if (this.opt.onPrep) this.opt.onPrep(i, this.shots.length); }
      catch(e){ this.prepped.push({ blob:this.shots[i].blob, rgba:null, w:0, h:0, ms:[] }); }
    }
  }
  async start() { await this.openCam(); this.running = true; this.prepped = []; this._prepCanceled = false; this._bgPrep = this._bgPrepLoop(); this.loop(); }
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
  stop() { this.running = false; this._prepCanceled = true; if (this.native && this.src) { if (this.torchOn) this.src.torch(false); this.src.lock(false); } this.closeCam(); if (this._bgPrep) this._bgPrep.catch(()=>{}); }
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
    const st = { native: !!this.native, camFps: this.native ? this.src.fps : null, found: false, markers: ms.length, ring: ringN, poseRms: p ? p.rms : null, poseN: p ? p.n : 0, w, h, ms, rgba: img.data, count: this.shots.length, fps: this.fps || 0, step, restarts: this.restarts || 0 };
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
      if (st.cell) {
        const prev = this.cellQual.get(st.cell) || 0;
        this.cellQual.set(st.cell, Math.max(prev, st.sharp ? 1 : (blindShot ? 0.3 : 0.6)));
        if (!this.cells.has(st.cell)) this.cells.set(st.cell, this.shots.length);
      }
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
    // v2.7: грубый контур предмета в цилиндре — «что не похоже на коврик в рабочем объёме», обводка по контуру.
    // Это только подсказка пользователю во время съёмки (не используется в реконструкции). Считается на текущем уменьшенном кадре.
    let ctr = null;
    if (st.found) {
      ctr = _silhouetteContour(st, this.L, Rb, Hb, this.objColor);
      if (ctr && ctr.length > 20) {
        c.strokeStyle = this.objColor ? 'rgba(255,120,220,.95)' : 'rgba(120,220,255,.75)';
        c.lineWidth = 2.5 * dpr; c.beginPath();
        for (let i = 0; i < ctr.length; i++) { const [px, py] = P(ctr[i][0], ctr[i][1]); i ? c.lineTo(px, py) : c.moveTo(px, py); }
        c.stroke();
      }
    }
    // v2.7: индикатор пипетки — перекрестие
    if (this.pipette) {
      c.strokeStyle = '#ffd250'; c.lineWidth = 2 * dpr;
      c.beginPath(); c.arc(W/2, H/2, 22*dpr, 0, Math.PI*2); c.moveTo(W/2-30*dpr, H/2); c.lineTo(W/2+30*dpr, H/2); c.moveTo(W/2, H/2-30*dpr); c.lineTo(W/2, H/2+30*dpr); c.stroke();
      c.fillStyle = '#ffd250'; c.font = `${14*dpr}px sans-serif`; c.textAlign='center'; c.fillText('Тап по предмету', W/2, H/2-40*dpr);
    }
    // v2.8: AR-ручка «солнце» (перетаскивается) + псевдозатенение внутри силуэта
    if (st.found) {
      if (!this.sunPos) this.sunPos = [st.w * 0.2, st.h * 0.25];
      const sp = this._sunScreen();
      if (ctr && ctr.length > 20 && sp) {
        const lx = (sp[0]-W/2)/(Math.min(W,H)/2), ly=(sp[1]-H/2)/(Math.min(W,H)/2);
        const ll = Math.hypot(lx,ly)||1; const Lx=lx/ll, Ly=ly/ll;
        c.save(); c.beginPath();
        for (let i = 0; i < ctr.length; i++) { const [px,py]=P(ctr[i][0],ctr[i][1]); i?c.lineTo(px,py):c.moveTo(px,py); }
        c.closePath(); c.clip();
        const grd = c.createRadialGradient(W/2-Lx*W*0.28, H/2-Ly*H*0.28, 4*dpr, W/2+Lx*18*dpr, H/2+Ly*18*dpr, Math.max(W,H)*0.55);
        grd.addColorStop(0, 'rgba(255,230,150,0.12)');
        grd.addColorStop(0.5, 'rgba(0,0,0,0)');
        grd.addColorStop(1, 'rgba(20,30,60,0.35)');
        c.fillStyle = grd; c.fillRect(0,0,W,H);
        c.restore();
      }
      if (sp) {
        c.save();
        c.strokeStyle = 'rgba(255,210,80,.95)'; c.fillStyle = 'rgba(255,220,120,.95)';
        c.lineWidth = 2*dpr;
        for (let i=0;i<8;i++){ const a=i/8*Math.PI*2; c.beginPath(); c.moveTo(sp[0]+Math.cos(a)*18*dpr, sp[1]+Math.sin(a)*18*dpr); c.lineTo(sp[0]+Math.cos(a)*26*dpr, sp[1]+Math.sin(a)*26*dpr); c.stroke(); }
        c.beginPath(); c.arc(sp[0], sp[1], 14*dpr, 0, Math.PI*2); c.fill(); c.stroke();
        // центр рисуем маленьким кружком (вместо ☀ — не у всех шрифтов есть глиф)
        c.fillStyle='rgba(255,240,180,1)'; c.beginPath(); c.arc(sp[0], sp[1], 6*dpr, 0, Math.PI*2); c.fill();
        c.restore();
      }
    }
  }
}
// v2.8: фоновая подготовка кадра (decode до TRACK_W + detectMarkers) — запускается между выстрелами
async function _prepFrame(blob) {
  const bmp = await createImageBitmap(blob);
  const w = TRACK_W, h = Math.round(bmp.height * w / bmp.width);
  const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
  const cx = cv.getContext('2d'); cx.drawImage(bmp, 0, 0, w, h); bmp.close && bmp.close();
  const img = cx.getImageData(0, 0, w, h);
  const g = toGray(new Uint8Array(img.data.buffer), w, h);
  const ms = detectMarkers(g, w, h);
  return { blob, rgba: new Uint8ClampedArray(img.data.buffer), w, h, ms };
}
// Контур силуэта в кадре: очень грубая маска (не фон) в проекции цилиндра. Строится за ~1 мс.
// Считает ожидаемую яркость коврика по угловым/кольцевым меткам и обводит край «не фона» сверху-снизу-слева-справа.
function _silhouetteContour(st, L, Rb, Hb, objColor) {
  const { w, h, ms, rgba } = st; if (!rgba) return null;
  // ожидаемая яркость белого листа в кадре — по 4 самым ярким окрестностям меток
  let W0 = 180;
  const whites = [];
  for (const m of ms) {
    const xs = m.corners.map(q => q[0]), ys = m.corners.map(q => q[1]);
    const cx = (xs[0]+xs[2])/2, cy=(ys[0]+ys[2])/2;
    for (let dy=-8; dy<=8; dy+=4) for (let dx=-8; dx<=8; dx+=4){
      const x=(cx+dx)|0, y=(cy+dy)|0;
      if (x<3||y<3||x>=w-3||y>=h-3) continue;
      const i=(y*w+x)*4; const v = (rgba[i]*77+rgba[i+1]*150+rgba[i+2]*29)>>8;
      if (v>150) whites.push(v);
    }
  }
  if (whites.length) { whites.sort((a,b)=>a-b); W0 = whites[(whites.length*0.75)|0]; }
  // проекция цилиндра в пиксели → рамка
  let x0=w, x1=0, y0=h, y1=0;
  const R=st.R, t=st.t, K=st.K;
  for (const z of [0, Hb]) for (let i=0;i<64;i++){
    const a=i/64*Math.PI*2;
    const cz=R[6]*Rb*Math.cos(a)+R[7]*Rb*Math.sin(a)+R[8]*z+t[2]; if (cz<5) continue;
    const u=K.fx*(R[0]*Rb*Math.cos(a)+R[1]*Rb*Math.sin(a)+R[2]*z+t[0])/cz+K.cx;
    const vv=K.fy*(R[3]*Rb*Math.cos(a)+R[4]*Rb*Math.sin(a)+R[5]*z+t[1])/cz+K.cy;
    x0=Math.min(x0,u); x1=Math.max(x1,u); y0=Math.min(y0,vv); y1=Math.max(y1,vv);
  }
  x0=Math.max(0,(x0|0)-4); x1=Math.min(w-1,(x1|0)+4); y0=Math.max(0,(y0|0)-4); y1=Math.min(h-1,(y1|0)+4);
  if (x1-x0<20||y1-y0<20) return null;
  // набираем тёмные/цветные пиксели как «похоже на предмет»: не белый лист и не чёрные метки (слишком тёмные <40 не режет без подсказки)
  const mask = new Uint8Array(w*h);
  const darkBoost = objColor && (objColor[0]+objColor[1]+objColor[2])/3 < 100; // тёмный предмет — принимаем и тёмные пиксели
  for (let y=y0; y<=y1; y++) for (let x=x0; x<=x1; x++){
    const i=(y*w+x)*4, r=rgba[i], g=rgba[i+1], b=rgba[i+2], m=(r+g+b)/3;
    const ch=(Math.max(r,g,b)-Math.min(r,g,b))/(m+12);
    // белый лист: яркость ≥ 0.7·W0 и мало хромы — это фон
    const onMat = m > 0.6*W0 && ch<0.12;
    // чёрная метка: очень тёмно (<40) без подсказки — не считаем предметом
    const blackMark = !darkBoost && m < 45;
    // подсказка цвета предмета: похож — предмет
    const nearCol = objColor ? Math.sqrt((r-objColor[0])**2+(g-objColor[1])**2+(b-objColor[2])**2) < 55 : false;
    if (!onMat && !blackMark && (ch>0.13 || m < 0.35*W0 || nearCol)) mask[y*w+x]=1;
  }
  // простой контур: первая/последняя «не фоновая» точка по строкам и столбцам в рамке
  const pts=[];
  for (let y=y0; y<=y1; y+=Math.max(1,((y1-y0)/60)|0)){
    for(let x=x0;x<=x1;x++) if(mask[y*w+x]){ pts.push([x,y]); break; }
    for(let x=x1;x>=x0;x--) if(mask[y*w+x]){ pts.push([x,y]); break; }
  }
  for (let x=x0; x<=x1; x+=Math.max(1,((x1-x0)/60)|0)){
    for(let y=y0;y<=y1;y++) if(mask[y*w+x]){ pts.push([x,y]); break; }
    for(let y=y1;y>=y0;y--) if(mask[y*w+x]){ pts.push([x,y]); break; }
  }
  return pts;
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
// v2.7: ячейка залита зелёным — есть резкий кадр; жёлтым — кадр есть, но смазан/слепой;
// красным — пусто (ещё не было кадра в этом секторе/поясе). Точка текущего ракурса — красная, если кадр смазан.
export function drawDome(canvas, cells, cur, qual) {
  const dpr = Math.min(2, window.devicePixelRatio || 1), S = Math.round(canvas.clientWidth * dpr);
  if (canvas.width !== S) { canvas.width = S; canvas.height = S; }
  const c = canvas.getContext('2d'), R = S / 2 - 2 * dpr, cx = S / 2, cy = S / 2;
  c.clearRect(0, 0, S, S);
  c.fillStyle = 'rgba(0,0,0,.45)'; c.beginPath(); c.arc(cx, cy, R, 0, Math.PI * 2); c.fill();
  const nb = BANDS.length, ring = (b) => [R * (1 - b / nb), R * (1 - (b + 1) / nb) + 1], Q = qual || new Map();
  for (let b = 0; b < nb; b++) for (let k = 0; k < AZ_BINS; k++) {
    const key = `${b}:${k}`;
    const [r0, r1] = ring(b), a0 = -Math.PI / 2 + k / AZ_BINS * Math.PI * 2, a1 = a0 + Math.PI * 2 / AZ_BINS;
    c.beginPath(); c.arc(cx, cy, r0, a0, a1); c.arc(cx, cy, r1, a1, a0, true); c.closePath();
    let fill;
    if (!cells.has(key)) fill = b === nb - 1 ? 'rgba(255,90,70,.55)' : 'rgba(255,90,70,.35)'; // красный — пусто
    else { const q = Q.get(key) || 0.7; fill = q >= 0.85 ? (b === nb - 1 ? 'rgba(120,200,255,.9)' : 'rgba(90,220,140,.85)') : 'rgba(255,200,70,.8)'; }
    c.fillStyle = fill; c.fill(); c.strokeStyle = 'rgba(0,0,0,.3)'; c.lineWidth = 1; c.stroke();
  }
  if (cur && cur.az != null) {
    const b = Math.max(0, Math.min(nb - 0.01, BANDS.findIndex(([lo, hi]) => cur.el >= lo && cur.el < hi) + 0.5));
    const r = cur.el >= BANDS[nb - 1][1] ? 0 : R * (1 - (b < 0 ? 0 : b) / nb), a = -Math.PI / 2 + cur.az / 360 * Math.PI * 2;
    c.fillStyle = cur.sharp ? '#fff' : '#ff5a46'; c.beginPath(); c.arc(cx + r * Math.cos(a), cy + r * Math.sin(a), 4 * dpr, 0, Math.PI * 2); c.fill();
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
