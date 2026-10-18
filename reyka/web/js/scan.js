// Оцифровка рисунка с бумаги — без ИИ:
//  1) несколько кадров усредняются (меньше шума);
//  2) лист «выпрямляется» по найденным углам (обратная гомография) → вид строго сверху;
//  3) фон выравнивается: по сетке ищется цвет бумаги и на него делится картинка —
//     уходят тени, виньетка, желтизна лампы;
//  4) пиксели делятся на «бумага», «линии» (тёмное и бесцветное) и «краска»;
//  5) краски сводятся к K цветам (k-средних), мелкие пятна убираются;
//  6) каждая область обводится контуром по границам пикселей, упрощается
//     (Дуглас–Пекер) и сглаживается кривыми Безье → настоящий вектор (SVG).

import { apply } from './geom.js';

// ---------- 1. Захват ----------
export async function captureFrames(video, vw, vh, n = 6, gapMs = 70) {
  const c = document.createElement('canvas');
  c.width = vw; c.height = vh;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  const acc = new Float32Array(vw * vh * 3);
  for (let k = 0; k < n; k++) {
    ctx.drawImage(video, 0, 0, vw, vh);
    const d = ctx.getImageData(0, 0, vw, vh).data;
    for (let i = 0, j = 0; i < acc.length; i += 3, j += 4) { acc[i] += d[j]; acc[i + 1] += d[j + 1]; acc[i + 2] += d[j + 2]; }
    if (k < n - 1) await new Promise(r => setTimeout(r, gapMs));
  }
  const out = new Uint8ClampedArray(vw * vh * 4);
  for (let i = 0, j = 0; i < acc.length; i += 3, j += 4) { out[j] = acc[i] / n; out[j + 1] = acc[i + 1] / n; out[j + 2] = acc[i + 2] / n; out[j + 3] = 255; }
  return { data: out, w: vw, h: vh };
}

// ---------- 2. Выпрямление ----------
// H — гомография «лист (мм) → кадр (px)». ppm — пикселей на мм в результате.
export function rectify(frame, H, pw, ph, ppm, marginMm = 2) {
  const W = Math.round(pw * ppm), Hh = Math.round(ph * ppm);
  const out = new Uint8ClampedArray(W * Hh * 4);
  const { data, w, h } = frame;
  for (let y = 0; y < Hh; y++) {
    for (let x = 0; x < W; x++) {
      const o = (y * W + x) * 4;
      const mx = (x + 0.5) / ppm, my = (y + 0.5) / ppm;
      if (mx < marginMm || my < marginMm || mx > pw - marginMm || my > ph - marginMm) { out[o] = out[o + 1] = out[o + 2] = 255; out[o + 3] = 255; continue; }
      const p = apply(H, mx, my);
      const sx = p.x - 0.5, sy = p.y - 0.5;
      const x0 = Math.floor(sx), y0 = Math.floor(sy);
      if (x0 < 0 || y0 < 0 || x0 >= w - 1 || y0 >= h - 1) { out[o] = out[o + 1] = out[o + 2] = 255; out[o + 3] = 255; continue; }
      const fx = sx - x0, fy = sy - y0;
      const i00 = (y0 * w + x0) * 4, i10 = i00 + 4, i01 = i00 + w * 4, i11 = i01 + 4;
      for (let c = 0; c < 3; c++) {
        const a = data[i00 + c] + (data[i10 + c] - data[i00 + c]) * fx;
        const b = data[i01 + c] + (data[i11 + c] - data[i01 + c]) * fx;
        out[o + c] = a + (b - a) * fy;
      }
      out[o + 3] = 255;
    }
  }
  return { data: out, w: W, h: Hh };
}

// ---------- 3. Выравнивание фона ----------
export function flatten(img, ppm, clean = 0.5, marginMm = 2) {
  const { data, w, h } = img;
  // Свет на бумаге оцениваем по клеткам ~5 мм: в каждой берём светлые пиксели (бумагу).
  // ВАЖНО: белое поле, которое добавляет выпрямление по краю, — не бумага, его пропускаем
  // (раньше оно делало край «светлее», и по краям скана появлялась тёмная рамка).
  const cell = Math.max(8, Math.round(ppm * 5));
  const gx = Math.ceil(w / cell), gy = Math.ceil(h / cell), GN = gx * gy;
  const m0 = Math.ceil((marginMm + 0.7) * ppm);
  const val = new Float32Array(GN * 3), ok = new Uint8Array(GN);
  const lum = [], idx = [];
  for (let cy = 0; cy < gy; cy++) for (let cx = 0; cx < gx; cx++) {
    const xa = Math.max(m0, cx * cell), xb = Math.min(w - m0, (cx + 1) * cell), ya = Math.max(m0, cy * cell), yb = Math.min(h - m0, (cy + 1) * cell);
    if (xb - xa < 2 || yb - ya < 2) continue;
    lum.length = 0; idx.length = 0;
    const st = cell > 16 ? 2 : 1;
    for (let y = ya; y < yb; y += st) for (let x = xa; x < xb; x += st) { const i = (y * w + x) * 4, L = data[i] + data[i + 1] + data[i + 2]; if (L >= 762) continue; lum.push(L); idx.push(i); }
    const n = lum.length; if (n < 6) continue;
    const srt = Float32Array.from(lum).sort();
    const lo = srt[Math.floor(n * 0.92)], hi = srt[Math.min(n - 1, Math.floor(n * 0.99))];
    let r = 0, g = 0, bb = 0, c = 0;
    for (let k = 0; k < n; k++) if (lum[k] >= lo && lum[k] <= hi) { const i = idx[k]; r += data[i]; g += data[i + 1]; bb += data[i + 2]; c++; }
    if (!c) continue;
    const o = (cy * gx + cx) * 3; val[o] = r / c; val[o + 1] = g / c; val[o + 2] = bb / c; ok[cy * gx + cx] = 1;
  }
  if (!ok.some(Boolean)) { val.fill(235); ok.fill(1); }
  const Lv = (A, k) => A[k * 3] + A[k * 3 + 1] + A[k * 3 + 2];
  // Отбор «это бумага»: клетка не сильно темнее сглаженного света вокруг и не цветная.
  // Тень/штриховка рисунка темнее окружающей бумаги больше чем на τ — её не трогаем,
  // свет под ней достраивается от соседей (pull-push). Плавное падение света к краям
  // (виньетка камеры, лампа сбоку) — это бумага: его модель повторяет и убирает.
  const tau = 0.05 + 0.13 * clean, delta = 0.025 + 0.05 * clean, dSlow = 0.012 + 0.02 * clean;
  const wt = new Float32Array(GN);
  // 1) «Заливка» бумаги от самых светлых клеток: шаг на соседа разрешён, если он темнее
  //    не больше чем на δ и того же оттенка. Плавная виньетка проходится целиком (≈2%/клетку),
  //    а край штриховки — это скачок, через него заливка не идёт, даже если пятно огромное.
  {
    const P = new Float32Array(GN), chr = new Float32Array(GN * 3);
    const okL = []; for (let k = 0; k < GN; k++) if (ok[k]) { P[k] = Lv(val, k); okL.push(P[k]); for (let ch = 0; ch < 3; ch++) chr[k * 3 + ch] = val[k * 3 + ch] / (P[k] / 3 + 1e-3); }
    okL.sort((p, q) => p - q);
    const seedT = okL[Math.floor(okL.length * 0.9)] * 0.97;
    const acc = new Uint8Array(GN), heap = [], ref = new Float32Array(GN);
    const DBG = globalThis.__flDebug ? (globalThis.__flDebug = { par: {}, acc, P, ref, gx, gy, cell }) : null;
    const push = k => { heap.push(k); let i = heap.length - 1; while (i > 0) { const pa = (i - 1) >> 1; if (P[heap[pa]] >= P[heap[i]]) break; [heap[pa], heap[i]] = [heap[i], heap[pa]]; i = pa; } };
    const pop = () => { const top = heap[0], last = heap.pop(); if (heap.length) { heap[0] = last; let i = 0; for (;;) { const l = 2 * i + 1, r = l + 1; let m = i; if (l < heap.length && P[heap[l]] > P[heap[m]]) m = l; if (r < heap.length && P[heap[r]] > P[heap[m]]) m = r; if (m === i) break; [heap[m], heap[i]] = [heap[i], heap[m]]; i = m; } } return top; };
    for (let k = 0; k < GN; k++) if (ok[k] && P[k] >= seedT) { acc[k] = 1; ref[k] = P[k]; push(k); }
    while (heap.length) {
      const k = pop(), cx = k % gx, cy = (k - cx) / gx;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        const x = cx + dx, y = cy + dy; if (x < 0 || y < 0 || x >= gx || y >= gy) continue;
        const n = y * gx + x; if (acc[n] || !ok[n]) continue;
        const st = dx && dy ? 1.25 : 1;
        if (P[n] < ref[k] * (1 - delta * st)) continue; // опора «помнит» яркость: лесенкой по краю тени не спуститься
        let cd = 0; for (let ch = 0; ch < 3; ch++) cd = Math.max(cd, Math.abs(chr[n * 3 + ch] - chr[k * 3 + ch]));
        if (cd > 0.06) continue;
        if (DBG) DBG.par[n] = k;
        acc[n] = 1; ref[n] = Math.max(P[n], ref[k] * (1 - dSlow * st)); push(n);
      }
    }
    for (let k = 0; k < GN; k++) wt[k] = acc[k];
  }
  let S = smoothGrid(pullPush(val, wt, gx, gy), gx, gy, 2);
  // 2) уточнение: из принятых убираем клетки, заметно темнее модели (мелкие тени, пятна)
  for (let it = 0; it < 2; it++) {
    for (let k = 0; k < GN; k++) {
      if (!ok[k] || !wt[k]) continue;
      const d = 1 - Lv(val, k) / Math.max(1, Lv(S, k));
      wt[k] = Math.max(0, Math.min(1, (tau + 0.03 - d) / 0.06));
    }
    S = smoothGrid(pullPush(val, wt, gx, gy), gx, gy, it < 1 ? 2 : 1);
  }
  const ratio = new Float32Array(w * h * 3);
  for (let y = 0; y < h; y++) {
    const fyR = (y + 0.5) / cell - 0.5, y0 = Math.max(0, Math.min(gy - 2, Math.floor(fyR))), y1 = Math.min(gy - 1, y0 + 1);
    const ty = gy > 1 ? Math.max(-0.5, Math.min(1.5, fyR - y0)) : 0;
    for (let x = 0; x < w; x++) {
      const fxR = (x + 0.5) / cell - 0.5, x0 = Math.max(0, Math.min(gx - 2, Math.floor(fxR))), x1 = Math.min(gx - 1, x0 + 1);
      const tx = gx > 1 ? Math.max(-0.5, Math.min(1.5, fxR - x0)) : 0;
      const i = (y * w + x) * 4, o = (y * w + x) * 3;
      for (let ch = 0; ch < 3; ch++) {
        const a = S[(y0 * gx + x0) * 3 + ch] * (1 - tx) + S[(y0 * gx + x1) * 3 + ch] * tx;
        const b2 = S[(y1 * gx + x0) * 3 + ch] * (1 - tx) + S[(y1 * gx + x1) * 3 + ch] * tx;
        const bgv = a * (1 - ty) + b2 * ty;
        ratio[o + ch] = Math.max(0, 1 - data[i + ch] / Math.max(30, bgv));
      }
    }
  }
  // карта света (для эффекта «старое фото»): яркость бумаги, 1 — самое светлое место
  const light = new Float32Array(GN);
  { const ls = []; for (let k = 0; k < GN; k++) ls.push(Lv(S, k)); const ref = ls.slice().sort((p, q) => p - q)[Math.floor(GN * 0.97)] || 1; for (let k = 0; k < GN; k++) light[k] = Math.min(1, ls[k] / ref); }
  // Тоновая кривая как у сканеров документов: шум бумаги срезаем, слабый карандаш усиливаем
  // плавной кривой (без обрезки — полутона и штриховка сохраняются). Цветную краску не трогаем.
  const floor = 0.015 + 0.06 * clean;
  const hist = new Uint32Array(101);
  let cnt = 0;
  for (let o = 0; o < ratio.length; o += 9) {
    const vv = (ratio[o] + ratio[o + 1] + ratio[o + 2]) / 3, cr = Math.max(ratio[o], ratio[o + 1], ratio[o + 2]) - Math.min(ratio[o], ratio[o + 1], ratio[o + 2]);
    if (vv > floor + 0.03 && cr < 0.08) { hist[Math.min(100, Math.round(vv * 100))]++; cnt++; }
  }
  let p95 = 0.6;
  if (cnt > 50) { let acc = 0; for (let k = 0; k <= 100; k++) { acc += hist[k]; if (acc >= cnt * 0.95) { p95 = k / 100; break; } } }
  const pn = Math.max(0.02, (p95 - floor) / (1 - floor));
  // k: (1 − e^(−k·pn)) / (1 − e^(−k)) = 0.82 (если и так темно — k → 0, кривая почти прямая)
  let kk = 0.01;
  const curve = (k, n) => (1 - Math.exp(-k * n)) / (1 - Math.exp(-k));
  if (curve(0.01, pn) < 0.82) { let lo = 0.01, hi = 9; for (let it = 0; it < 40; it++) { const m = (lo + hi) / 2; if (curve(m, pn) < 0.82) lo = m; else hi = m; } kk = (lo + hi) / 2; }
  const LUT = new Float32Array(1001);
  for (let k = 0; k <= 1000; k++) { const n = k / 1000; LUT[k] = curve(kk, n); }
  const out = new Uint8ClampedArray(w * h * 4);
  for (let k = 0, i = 0, o = 0; k < w * h; k++, i += 4, o += 3) {
    const cr = Math.max(ratio[o], ratio[o + 1], ratio[o + 2]) - Math.min(ratio[o], ratio[o + 1], ratio[o + 2]);
    const wc = Math.max(0, Math.min(1, 1 - (cr - 0.05) / 0.12)); // 1 — бесцветное, 0 — краска
    for (let ch = 0; ch < 3; ch++) {
      const vv = ratio[o + ch];
      const n = vv <= floor ? 0 : Math.min(1, (vv - floor) / (1 - floor));
      const ink = LUT[Math.round(n * 1000)] * wc + n * (1 - wc);
      out[i + ch] = 255 * (1 - ink);
    }
    out[i + 3] = 255;
  }
  return { data: out, w, h, gain: kk, light: { g: light, gx, gy, cell } };
}

// Pull-push: заполняем клетки без данных (вес 0) гладко от соседей любой удалённости.
function pullPush(v, wt, gx, gy) {
  const levels = [{ v: v.slice(), w: wt.slice(), gx, gy }];
  while (levels[levels.length - 1].gx > 1 || levels[levels.length - 1].gy > 1) {
    const F = levels[levels.length - 1], nx = Math.ceil(F.gx / 2), ny = Math.ceil(F.gy / 2);
    const nv = new Float32Array(nx * ny * 3), nw = new Float32Array(nx * ny);
    for (let Y = 0; Y < ny; Y++) for (let X = 0; X < nx; X++) {
      let W = 0, r = 0, g = 0, b = 0;
      for (let dy = 0; dy < 2; dy++) for (let dx = 0; dx < 2; dx++) {
        const x = 2 * X + dx, y = 2 * Y + dy; if (x >= F.gx || y >= F.gy) continue;
        const k = y * F.gx + x, ww = F.w[k]; if (ww <= 0) continue;
        W += ww; r += ww * F.v[k * 3]; g += ww * F.v[k * 3 + 1]; b += ww * F.v[k * 3 + 2];
      }
      const K = Y * nx + X;
      nw[K] = Math.min(1, W);
      if (W > 1e-6) { nv[K * 3] = r / W; nv[K * 3 + 1] = g / W; nv[K * 3 + 2] = b / W; }
    }
    levels.push({ v: nv, w: nw, gx: nx, gy: ny });
  }
  for (let l = levels.length - 2; l >= 0; l--) {
    const F = levels[l], C = levels[l + 1];
    for (let y = 0; y < F.gy; y++) for (let x = 0; x < F.gx; x++) {
      const k = y * F.gx + x, ww = Math.min(1, F.w[k]);
      if (ww >= 1) continue;
      const fx = Math.max(0, Math.min(C.gx - 1, (x + 0.5) / 2 - 0.5)), fy = Math.max(0, Math.min(C.gy - 1, (y + 0.5) / 2 - 0.5));
      const x0 = Math.floor(fx), y0 = Math.floor(fy), x1 = Math.min(C.gx - 1, x0 + 1), y1 = Math.min(C.gy - 1, y0 + 1), tx = fx - x0, ty = fy - y0;
      for (let ch = 0; ch < 3; ch++) {
        const up = (C.v[(y0 * C.gx + x0) * 3 + ch] * (1 - tx) + C.v[(y0 * C.gx + x1) * 3 + ch] * tx) * (1 - ty) + (C.v[(y1 * C.gx + x0) * 3 + ch] * (1 - tx) + C.v[(y1 * C.gx + x1) * 3 + ch] * tx) * ty;
        F.v[k * 3 + ch] = ww * F.v[k * 3 + ch] + (1 - ww) * up;
      }
      F.w[k] = 1;
    }
  }
  return levels[0].v;
}
function smoothGrid(v, gx, gy, passes) {
  let a = v;
  for (let p = 0; p < passes; p++) {
    const o = new Float32Array(a.length);
    for (let y = 0; y < gy; y++) for (let x = 0; x < gx; x++) for (let ch = 0; ch < 3; ch++) {
      let s = 0, c = 0;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const xx = x + dx, yy = y + dy; if (xx < 0 || yy < 0 || xx >= gx || yy >= gy) continue; s += a[(yy * gx + xx) * 3 + ch]; c++; }
      o[(y * gx + x) * 3 + ch] = s / c;
    }
    a = o;
  }
  return a;
}

function solveSym(A0, b0) {
  const n = b0.length, M = A0.map((r, i) => [...r, b0[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    if (Math.abs(M[p][c]) < 1e-12) return null;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let j = c; j <= n; j++) M[r][j] -= f * M[c][j]; }
  }
  return M.map((r, i) => r[n] / r[i]);
}

// ---------- 4–5. Разделение на линии и цвета ----------
// lineLevel 0..1 — чувствительность к линиям; colors — сколько цветов (0 — только линии);
// minSpot — минимальный размер пятна в мм².
export function segment(img, ppm, { lineLevel = 0.5, colors = 6, minSpot = 2, paint = true } = {}) {
  const { data, w, h } = img;
  const n = w * h;
  const kind = new Uint8Array(n); // 0 бумага, 1 линия, 2 краска
  const lineThr = 90 + 110 * lineLevel; // яркость, ниже которой бесцветное — линия
  // Линия — это то, что темнее своего окружения. Ровная штриховка/тень темна, но не темнее
  // соседей — она уходит в «краску» (серые тона), а не в линии.
  const Lum = new Float32Array(n);
  for (let i = 0, j = 0; i < n; i++, j += 4) Lum[i] = 0.299 * data[j] + 0.587 * data[j + 1] + 0.114 * data[j + 2];
  const loc = boxBlur(Lum, w, h, Math.max(3, Math.round(1.6 * ppm)));
  const dLine = 18 + 22 * (1 - lineLevel);
  const colored = [];
  for (let i = 0, j = 0; i < n; i++, j += 4) {
    const r = data[j], g = data[j + 1], b = data[j + 2];
    const L = Lum[i];
    const C = Math.max(r, g, b) - Math.min(r, g, b);
    const contrast = loc[i] - L;
    if (L < 45 || (L < lineThr && C < 55 + (lineThr - L) * 0.4 && contrast > dLine)) kind[i] = 1;
    else if (paint && colors > 0 && (C > 28 || L < 225)) { kind[i] = 2; colored.push(i); }
  }
  // Гистерезис: светлые продолжения штриха присоединяем к уверенным линиям
  // (по связности), а одиночные светлые пятна — шум — не берём.
  clearBorderJunk(kind, w, h, Math.ceil(2 * ppm)); // сначала убираем кусочки стола у края
  {
    const weakThr = Math.min(242, lineThr + 50);
    const band = Math.ceil(2 * ppm) + Math.ceil(3 * ppm); // в полосу у края не растём
    const stack = new Int32Array(n); let sp = 0;
    for (let i = 0; i < n; i++) if (kind[i] === 1) stack[sp++] = i;
    while (sp) {
      const i = stack[--sp], y = (i / w) | 0, x = i - y * w;
      for (const j of [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]) {
        if (j < 0 || kind[j] === 1) continue;
        { const jy = (j / w) | 0, jx = j - jy * w; if (jx < band || jy < band || jx >= w - band || jy >= h - band) continue; }
        const q = j * 4, r = data[q], g = data[q + 1], b = data[q + 2];
        const L = Lum[j], C = Math.max(r, g, b) - Math.min(r, g, b);
        if (L < weakThr && C < 40 && loc[j] - L > dLine * 0.45) { kind[j] = 1; stack[sp++] = j; }
      }
    }
  }
  // тонкие полосы у самого края (кусочек стола из-за неточного угла) — убираем
  clearBorderJunk(kind, w, h, Math.ceil(2 * ppm));
  // убираем мелкий мусор из линий
  const minLine = Math.max(4, Math.round(0.35 * ppm * ppm));
  removeSmall(kind, w, h, 1, minLine, 0);

  // k-средних по цветам краски
  let palette = [];
  const label = new Uint8Array(n); // 0 — нет цвета, 1..K
  if (colored.length && colors > 0) {
    const sample = [];
    const step = Math.max(1, Math.floor(colored.length / 25000));
    for (let k = 0; k < colored.length; k += step) { if (kind[colored[k]] !== 2) continue; const j = colored[k] * 4; sample.push([data[j], data[j + 1], data[j + 2]]); }
    // порог слияния зависит от того, сколько оттенков просили: при 16 различаем и близкие
    // тона карандаша (раньше всё серое сливалось в 2–4 цвета)
    const mergeThr = colors <= 4 ? 22 : colors <= 8 ? 14 : 7;
    palette = mergeClose(bestKmeans(sample, Math.min(colors, sample.length)), sample, mergeThr);
    for (const i of colored) {
      if (kind[i] !== 2) continue;
      const j = i * 4;
      let best = 0, bd = Infinity;
      for (let c = 0; c < palette.length; c++) { const p = palette[c], d = (p[0] - data[j]) ** 2 * 0.3 + (p[1] - data[j + 1]) ** 2 * 0.59 + (p[2] - data[j + 2]) ** 2 * 0.11; if (d < bd) { bd = d; best = c; } }
      label[i] = best + 1;
    }
    majority(label, kind, w, h);
    const minArea = Math.max(6, Math.round(minSpot * ppm * ppm));
    for (let c = 1; c <= palette.length; c++) removeSmallLabel(label, w, h, c, minArea);
    // удаляем почти-белые «цвета» (остатки бумаги)
    palette = palette.map(p => p.map(v => Math.round(v)));
  }
  // цвет линий — средний цвет линейных пикселей (затемнённый)
  let lr = 0, lg = 0, lb = 0, lc = 0;
  for (let i = 0; i < n; i += 3) if (kind[i] === 1) { const j = i * 4; lr += data[j]; lg += data[j + 1]; lb += data[j + 2]; lc++; }
  const lineColor = lc ? [lr / lc * 0.6, lg / lc * 0.6, lb / lc * 0.6].map(Math.round) : [30, 30, 30];
  return { w, h, kind, label, palette, lineColor };
}

// Среднее по квадрату (2r+1)² через интегральное изображение.
function boxBlur(src, w, h, r) {
  const I = new Float64Array((w + 1) * (h + 1));
  for (let y = 0; y < h; y++) { let row = 0; for (let x = 0; x < w; x++) { row += src[y * w + x]; I[(y + 1) * (w + 1) + x + 1] = I[y * (w + 1) + x + 1] + row; } }
  const out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - r), y1 = Math.min(h, y + r + 1);
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - r), x1 = Math.min(w, x + r + 1);
      out[y * w + x] = (I[y1 * (w + 1) + x1] - I[y0 * (w + 1) + x1] - I[y1 * (w + 1) + x0] + I[y0 * (w + 1) + x0]) / ((x1 - x0) * (y1 - y0));
    }
  }
  return out;
}

// k-средних несколько раз с разной стартовой точкой — берём лучший по ошибке
function bestKmeans(pts, k) {
  let best = null, bestE = Infinity;
  for (let t = 0; t < 3; t++) {
    const C = kmeans(pts, k);
    let e = 0; for (let i = 0; i < pts.length; i += 3) { const p = pts[i]; let bd = Infinity; for (const c of C) { const d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2; if (d < bd) bd = d; } e += bd; }
    if (e < bestE) { bestE = e; best = C; }
  }
  return best;
}
function kmeans(pts, k) {
  // k-means++ инициализация
  const C = [pts[Math.floor(Math.random() * pts.length)].slice()];
  const d2 = new Float64Array(pts.length).fill(Infinity);
  while (C.length < k) {
    let sum = 0;
    const last = C[C.length - 1];
    for (let i = 0; i < pts.length; i++) { const p = pts[i], d = (p[0] - last[0]) ** 2 + (p[1] - last[1]) ** 2 + (p[2] - last[2]) ** 2; if (d < d2[i]) d2[i] = d; sum += d2[i]; }
    if (!sum) break;
    let r = Math.random() * sum, i = 0;
    for (; i < pts.length - 1; i++) { r -= d2[i]; if (r <= 0) break; }
    C.push(pts[i].slice());
  }
  const as = new Int32Array(pts.length);
  for (let it = 0; it < 14; it++) {
    const S = C.map(() => [0, 0, 0, 0]);
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i]; let b = 0, bd = Infinity;
      for (let c = 0; c < C.length; c++) { const d = (p[0] - C[c][0]) ** 2 + (p[1] - C[c][1]) ** 2 + (p[2] - C[c][2]) ** 2; if (d < bd) { bd = d; b = c; } }
      as[i] = b; S[b][0] += p[0]; S[b][1] += p[1]; S[b][2] += p[2]; S[b][3]++;
    }
    for (let c = 0; c < C.length; c++) if (S[c][3]) C[c] = [S[c][0] / S[c][3], S[c][1] / S[c][3], S[c][2] / S[c][3]];
  }
  // сортируем от тёмных к светлым
  return C.sort((a, b) => (a[0] + a[1] + a[2]) - (b[0] + b[1] + b[2]));
}

// Сливаем почти одинаковые цвета (k-средних иногда делит одну краску на два оттенка).
function mergeClose(C, pts, thr = 26) {
  const cnt = C.map(() => 0);
  for (const p of pts) { let b = 0, bd = Infinity; C.forEach((c, i) => { const d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2; if (d < bd) { bd = d; b = i; } }); cnt[b]++; }
  let list = C.map((c, i) => ({ c, n: cnt[i] })).filter(x => x.n > 0);
  for (let changed = true; changed;) {
    changed = false;
    outer: for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
      const a = list[i], b = list[j];
      const d = Math.sqrt((a.c[0] - b.c[0]) ** 2 * 0.3 + (a.c[1] - b.c[1]) ** 2 * 0.59 + (a.c[2] - b.c[2]) ** 2 * 0.11);
      if (d < thr) {
        const n = a.n + b.n;
        list[i] = { c: [0, 1, 2].map(k => (a.c[k] * a.n + b.c[k] * b.n) / n), n };
        list.splice(j, 1); changed = true; break outer;
      }
    }
  }
  return list.map(x => x.c).sort((a, b) => (a[0] + a[1] + a[2]) - (b[0] + b[1] + b[2]));
}

function majority(label, kind, w, h) {
  const cp = label.slice();
  const cnt = new Uint16Array(32);
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const i = y * w + x;
    if (kind[i] === 1) continue;
    cnt.fill(0);
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) cnt[cp[i + dy * w + dx]]++;
    let b = cp[i], bc = cnt[b];
    for (let c = 0; c < 32; c++) if (cnt[c] > bc) { bc = cnt[c]; b = c; }
    if (bc >= 5) label[i] = b;
  }
}

function clearBorderJunk(kind, w, h, mpx = 0) {
  // mpx — белое поле по краю (отступ при выпрямлении): «край» начинается за ним.
  const B = mpx + 2;
  // 1) короткие «заходы» от края внутрь в каждой строке/столбце (клин стола)
  const lim0 = Math.max(3, Math.round(Math.min(w, h) * 0.025), Math.round(mpx * 2.5)); // клин до ~5 мм
  const run = (get, n) => {
    let a = 0; while (a < Math.min(n, B) && !kind[get(a)]) a++;
    if (a >= B || a >= n) return;
    let r = a; while (r < n && kind[get(r)]) r++;
    if (r - a < lim0) for (let k = a; k < r; k++) kind[get(k)] = 0;
  };
  for (let y = 0; y < h; y++) { run(x => y * w + x, w); run(x => y * w + w - 1 - x, w); }
  for (let x = 0; x < w; x++) { run(y => y * w + x, h); run(y => (h - 1 - y) * w + x, h); }
  // 2) тонкие компоненты, прилипшие к краю
  const seen = new Uint8Array(w * h), stack = new Int32Array(w * h), comp = [];
  const lim = Math.min(w, h) * 0.04;
  // тени/виньетка в углах дают полоски чуть поодаль от края — ищем в полосе ~5 мм
  const B2 = B + Math.round(mpx * 1.5);
  for (let s = 0; s < w * h; s++) {
    if (!kind[s] || seen[s]) continue;
    const sy = (s / w) | 0, sx = s - sy * w;
    if (sx >= B2 && sy >= B2 && sx < w - B2 && sy < h - B2) continue;
    let sp = 0; comp.length = 0; stack[sp++] = s; seen[s] = 1;
    let x0 = w, x1 = 0, y0 = h, y1 = 0;
    while (sp) {
      const i = stack[--sp]; comp.push(i);
      const y = (i / w) | 0, x = i - y * w;
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      for (const j of [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]) if (j >= 0 && !seen[j] && kind[j]) { seen[j] = 1; stack[sp++] = j; }
    }
    // «прилип к краю и тонкий вдоль него» — значит, это не рисунок
    const touchL = x0 < B2, touchR = x1 >= w - B2, touchT = y0 < B2, touchB = y1 >= h - B2;
    const thin = ((touchL || touchR) && x1 - x0 < lim) || ((touchT || touchB) && y1 - y0 < lim);
    if (thin) for (const i of comp) kind[i] = 0;
  }
}

function removeSmall(arr, w, h, val, minArea, repl) {
  const seen = new Uint8Array(w * h), stack = new Int32Array(w * h), comp = [];
  for (let s = 0; s < w * h; s++) {
    if (arr[s] !== val || seen[s]) continue;
    let sp = 0; comp.length = 0; stack[sp++] = s; seen[s] = 1;
    while (sp) {
      const i = stack[--sp]; comp.push(i);
      const y = (i / w) | 0, x = i - y * w;
      for (const j of [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1, x > 0 && y > 0 ? i - w - 1 : -1, x < w - 1 && y < h - 1 ? i + w + 1 : -1, x < w - 1 && y > 0 ? i - w + 1 : -1, x > 0 && y < h - 1 ? i + w - 1 : -1]) {
        if (j >= 0 && !seen[j] && arr[j] === val) { seen[j] = 1; stack[sp++] = j; }
      }
    }
    if (comp.length < minArea) for (const i of comp) arr[i] = repl;
  }
}

function removeSmallLabel(label, w, h, c, minArea) {
  const seen = new Uint8Array(w * h), stack = new Int32Array(w * h), comp = [];
  for (let s = 0; s < w * h; s++) {
    if (label[s] !== c || seen[s]) continue;
    let sp = 0; comp.length = 0; stack[sp++] = s; seen[s] = 1;
    const around = new Map();
    while (sp) {
      const i = stack[--sp]; comp.push(i);
      const y = (i / w) | 0, x = i - y * w;
      for (const j of [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]) {
        if (j < 0) continue;
        if (label[j] === c) { if (!seen[j]) { seen[j] = 1; stack[sp++] = j; } }
        else around.set(label[j], (around.get(label[j]) || 0) + 1);
      }
    }
    if (comp.length < minArea) {
      let b = 0, bc = -1; for (const [k, v] of around) if (v > bc) { bc = v; b = k; }
      for (const i of comp) label[i] = b;
    }
  }
}

// ---------- 6. Вектор ----------
// Обводка маски по границам пикселей → упрощение → сглаживание. Возвращает SVG path «d».
export function traceMask(mask, w, h, { simplify = 0.9, minArea = 4, smooth = true, ox = 0, oy = 0 } = {}) {
  const W1 = w + 1;
  // рёбра: от вершины к вершине, «внутри» справа (обход по часовой)
  const next = new Map(); // ключ вершины → список рёбер
  const edges = [];
  const add = (x1, y1, x2, y2) => {
    const k = y1 * W1 + x1, id = edges.length;
    edges.push([x1, y1, x2, y2]);
    const l = next.get(k); if (l) l.push(id); else next.set(k, [id]);
  };
  const at = (x, y) => x >= 0 && y >= 0 && x < w && y < h && mask[y * w + x];
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (!mask[y * w + x]) continue;
    if (!at(x, y - 1)) add(x, y, x + 1, y);
    if (!at(x + 1, y)) add(x + 1, y, x + 1, y + 1);
    if (!at(x, y + 1)) add(x + 1, y + 1, x, y + 1);
    if (!at(x - 1, y)) add(x, y + 1, x, y);
  }
  const used = new Uint8Array(edges.length);
  let d = '';
  for (let s = 0; s < edges.length; s++) {
    if (used[s]) continue;
    const loop = [];
    let e = s, guard = 0;
    while (!used[e] && guard++ < 4e6) {
      used[e] = 1;
      const [x1, y1, x2, y2] = edges[e];
      loop.push([x1, y1]);
      const cand = (next.get(y2 * W1 + x2) || []).filter(id => !used[id]);
      if (!cand.length) break;
      if (cand.length === 1) e = cand[0];
      else {
        // развилка (пиксели касаются углами): поворачиваем направо
        const dx = x2 - x1, dy = y2 - y1;
        let best = cand[0], bs = -Infinity;
        for (const id of cand) { const [a1, b1, a2, b2] = edges[id]; const ex = a2 - a1, ey = b2 - b1; const crs = dx * ey - dy * ex; if (crs > bs) { bs = crs; best = id; } }
        e = best;
      }
    }
    if (loop.length < 4) continue;
    // убираем точки на прямых
    const pts = [];
    for (let i = 0; i < loop.length; i++) {
      const a = loop[(i - 1 + loop.length) % loop.length], b = loop[i], c = loop[(i + 1) % loop.length];
      if ((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) !== 0) pts.push(b);
    }
    if (pts.length < 3) continue;
    let area = 0; for (let i = 0; i < pts.length; i++) { const a = pts[i], b = pts[(i + 1) % pts.length]; area += a[0] * b[1] - b[0] * a[1]; }
    if (Math.abs(area / 2) < minArea) continue;
    let simp = simplifyClosed(pts, simplify);
    if (simp.length < 3) continue;
    if (ox || oy) simp = simp.map(q => [q[0] + ox, q[1] + oy]);
    d += smooth ? smoothPath(simp) : 'M' + simp.map(p => p[0] + ' ' + p[1]).join('L') + 'Z';
  }
  return d;
}

function simplifyClosed(pts, eps) {
  if (pts.length < 8) return pts;
  // разрезаем по самой дальней паре точек и упрощаем две половины
  let far = 0, fd = -1;
  for (let i = 1; i < pts.length; i++) { const d = (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2; if (d > fd) { fd = d; far = i; } }
  const a = dp(pts.slice(0, far + 1), eps), b = dp(pts.slice(far).concat([pts[0]]), eps);
  return a.slice(0, -1).concat(b.slice(0, -1));
}

function dp(pts, eps) {
  if (pts.length < 3) return pts;
  const keep = new Uint8Array(pts.length); keep[0] = keep[pts.length - 1] = 1;
  const st = [[0, pts.length - 1]];
  while (st.length) {
    const [s, e] = st.pop();
    const [ax, ay] = pts[s], [bx, by] = pts[e];
    const dx = bx - ax, dy = by - ay, L = Math.hypot(dx, dy) || 1;
    let mi = -1, md = eps;
    for (let i = s + 1; i < e; i++) { const d = Math.abs((pts[i][0] - ax) * dy - (pts[i][1] - ay) * dx) / L; if (d > md) { md = d; mi = i; } }
    if (mi >= 0) { keep[mi] = 1; st.push([s, mi], [mi, e]); }
  }
  return pts.filter((_, i) => keep[i]);
}

const f1 = (v) => Math.round(v * 10) / 10;
function smoothPath(p) {
  const n = p.length;
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const m0 = mid(p[n - 1], p[0]);
  let s = `M${f1(m0[0])} ${f1(m0[1])}`;
  for (let i = 0; i < n; i++) {
    const a = p[(i - 1 + n) % n], b = p[i], c = p[(i + 1) % n];
    const m = mid(b, c);
    // острые углы оставляем острыми
    const v1x = b[0] - a[0], v1y = b[1] - a[1], v2x = c[0] - b[0], v2y = c[1] - b[1];
    const cos = (v1x * v2x + v1y * v2y) / ((Math.hypot(v1x, v1y) * Math.hypot(v2x, v2y)) || 1);
    if (cos < 0.64) s += `L${f1(b[0])} ${f1(b[1])}L${f1(m[0])} ${f1(m[1])}`;
    else s += `Q${f1(b[0])} ${f1(b[1])} ${f1(m[0])} ${f1(m[1])}`;
  }
  return s + 'Z';
}

// ---------- Сборка результата ----------
const hex = (c) => '#' + c.map(v => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('');

export function vectorize(seg, ppm, { smooth = 1, lineBlack = false, withColors = true, gradients = false, img = null } = {}) {
  const { w, h, kind, label, palette } = seg;
  const eps = 0.6 + smooth * 0.9;
  const layers = [];
  if (withColors) {
    for (let c = 1; c <= palette.length; c++) {
      const pc = palette[c - 1], chroma = Math.max(...pc) - Math.min(...pc), lum = 0.299 * pc[0] + 0.587 * pc[1] + 0.114 * pc[2];
      // блёклый серый ореол вокруг линий — это бумага; но если просили много оттенков,
      // светлые серые тона карандаша нужны — порог выше
      if (chroma < 22 && lum > (palette.length > 8 ? 232 : palette.length > 4 ? 205 : 175)) continue;
      const m = new Uint8Array(w * h);
      let any = 0;
      for (let i = 0; i < w * h; i++) if (label[i] === c && kind[i] !== 1) { m[i] = 1; any++; }
      // краска под линиями: продлеваем цвет под линию, чтобы не было белых щелей
      if (any) {
        for (let i = 0; i < w * h; i++) if (kind[i] === 1 && !m[i]) {
          const y = (i / w) | 0, x = i - y * w;
          let near = 0;
          for (let dy = -2; dy <= 2 && !near; dy++) for (let dx = -2; dx <= 2; dx++) { const xx = x + dx, yy = y + dy; if (xx >= 0 && yy >= 0 && xx < w && yy < h && label[yy * w + xx] === c && kind[yy * w + xx] !== 1) { near = 1; break; } }
          if (near) m[i] = 1;
        }
        if (gradients && img) {
          const parts = gradientParts(m, w, h, img, kind, { simplify: eps, minArea: ppm * ppm * 1.0 });
          if (parts.length) layers.push({ name: 'Цвет ' + c, color: hex(palette[c - 1]), d: parts.map(q => q.d).join(''), parts });
        } else {
          const d = traceMask(m, w, h, { simplify: eps, minArea: ppm * ppm * 1.0 });
          if (d) layers.push({ name: 'Цвет ' + c, color: hex(palette[c - 1]), d });
        }
      }
    }
  }
  const lm = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) if (kind[i] === 1) lm[i] = 1;
  const ld = traceMask(lm, w, h, { simplify: Math.max(0.6, eps * 0.75), minArea: 2 });
  const lines = { name: 'Линии', color: lineBlack ? '#1a1a1a' : hex(seg.lineColor), d: ld };
  return { w, h, colors: layers, lines };
}

// Каждое пятно краски — отдельный контур; цвет по его пикселям: линейный градиент
// (если перепад заметен) или средний цвет пятна.
function gradientParts(m, w, h, img, kind, opts) {
  const seen = new Uint8Array(w * h), stack = new Int32Array(w * h), comp = [];
  const parts = [], D = img.data;
  for (let s0 = 0; s0 < w * h; s0++) {
    if (!m[s0] || seen[s0]) continue;
    let sp = 0; comp.length = 0; stack[sp++] = s0; seen[s0] = 1;
    let x0 = w, x1 = 0, y0 = h, y1 = 0;
    while (sp) {
      const i = stack[--sp]; comp.push(i);
      const y = (i / w) | 0, x = i - y * w;
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      if (x > 0 && m[i - 1] && !seen[i - 1]) { seen[i - 1] = 1; stack[sp++] = i - 1; }
      if (x < w - 1 && m[i + 1] && !seen[i + 1]) { seen[i + 1] = 1; stack[sp++] = i + 1; }
      if (y > 0 && m[i - w] && !seen[i - w]) { seen[i - w] = 1; stack[sp++] = i - w; }
      if (y < h - 1 && m[i + w] && !seen[i + w]) { seen[i + w] = 1; stack[sp++] = i + w; }
    }
    if (comp.length < opts.minArea) continue;
    // контур только этого пятна
    const bw = x1 - x0 + 1, bh = y1 - y0 + 1, crop = new Uint8Array(bw * bh);
    for (const i of comp) { const y = (i / w) | 0, x = i - y * w; crop[(y - y0) * bw + (x - x0)] = 1; }
    const d = traceMask(crop, bw, bh, { simplify: opts.simplify, minArea: opts.minArea, ox: x0, oy: y0 });
    if (!d) continue;
    // цвет: выборка пикселей пятна (без линий)
    const step = Math.max(1, Math.floor(comp.length / 4000));
    const S = [];
    for (let k = 0; k < comp.length; k += step) { const i = comp[k]; if (kind[i] === 1) continue; const y = (i / w) | 0, x = i - y * w; S.push([x + 0.5, y + 0.5, D[i * 4], D[i * 4 + 1], D[i * 4 + 2]]); }
    if (S.length < 3) { for (let k = 0; k < comp.length; k += step) { const i = comp[k], y = (i / w) | 0, x = i - y * w; S.push([x + 0.5, y + 0.5, D[i * 4], D[i * 4 + 1], D[i * 4 + 2]]); } }
    let mx = 0, my = 0, mr = 0, mg = 0, mb = 0;
    for (const q of S) { mx += q[0]; my += q[1]; mr += q[2]; mg += q[3]; mb += q[4]; }
    const N = S.length; mx /= N; my /= N; mr /= N; mg /= N; mb /= N;
    const mean = [mr, mg, mb].map(Math.round);
    // направление: регрессия яркости по x, y
    let sxx = 0, sxy = 0, syy = 0, sxl = 0, syl = 0;
    for (const q of S) { const dx = q[0] - mx, dy = q[1] - my, l = 0.299 * q[2] + 0.587 * q[3] + 0.114 * q[4] - (0.299 * mr + 0.587 * mg + 0.114 * mb); sxx += dx * dx; sxy += dx * dy; syy += dy * dy; sxl += dx * l; syl += dy * l; }
    const det = sxx * syy - sxy * sxy;
    let fill = hex(mean);
    if (det > 1e-6 && N > 30) {
      const gxl = (sxl * syy - syl * sxy) / det, gyl = (syl * sxx - sxl * sxy) / det, gm = Math.hypot(gxl, gyl);
      if (gm > 1e-6) {
        const ux = gxl / gm, uy = gyl / gm;
        let tmin = Infinity, tmax = -Infinity, st = 0, stt = 0;
        for (const q of S) { const t = (q[0] - mx) * ux + (q[1] - my) * uy; if (t < tmin) tmin = t; if (t > tmax) tmax = t; st += t; stt += t * t; }
        if (gm * (tmax - tmin) > 14) {
          const vt = stt / N - (st / N) ** 2;
          const cAt = (t) => [2, 3, 4].map((ch, k) => { let sc = 0; for (const q of S) sc += ((q[0] - mx) * ux + (q[1] - my) * uy) * (q[ch] - [mr, mg, mb][k]); const slope = vt > 1e-9 ? sc / N / vt : 0; return Math.round([mr, mg, mb][k] + slope * t); });
          // градиент чуть «внутрь», чтобы крайние цвета не пересвечивали
          const a = tmin * 0.9, b = tmax * 0.9;
          fill = { x1: +(mx + ux * a).toFixed(1), y1: +(my + uy * a).toFixed(1), x2: +(mx + ux * b).toFixed(1), y2: +(my + uy * b).toFixed(1), c1: hex(cAt(a)), c2: hex(cAt(b)) };
        }
      }
    }
    // радиальная модель: L = a + b·x + c·y + k·(x² + y²) — для «шаров», бликов, виньеток
    const rad = radialFit(S, mx, my, mr, mg, mb, Math.max(bw, bh));
    if (rad) fill = rad;
    parts.push({ d, fill });
  }
  return parts;
}

function radialFit(S, mx, my, mr, mg, mb, size) {
  const N = S.length; if (N < 60) return null;
  const sc = size / 2 || 1;
  // МНК по 4 параметрам (b, c, k, a) для яркости
  const A = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], R = [0, 0, 0, 0], Rl = [0, 0, 0];
  const Lm = 0.299 * mr + 0.587 * mg + 0.114 * mb;
  const A3 = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  let sst = 0;
  for (const q of S) {
    const x = (q[0] - mx) / sc, y = (q[1] - my) / sc, l = 0.299 * q[2] + 0.587 * q[3] + 0.114 * q[4] - Lm;
    const f = [x, y, x * x + y * y, 1];
    for (let i = 0; i < 4; i++) { R[i] += f[i] * l; for (let j = 0; j < 4; j++) A[i][j] += f[i] * f[j]; }
    const f3 = [x, y, 1]; for (let i = 0; i < 3; i++) { Rl[i] += f3[i] * l; for (let j = 0; j < 3; j++) A3[i][j] += f3[i] * f3[j]; }
    sst += l * l;
  }
  const sol = solveSym(A, R), sol3 = solveSym(A3, Rl);
  if (!sol || !sol3) return null;
  const [b, c, k, a] = sol;
  if (Math.abs(k) < 1e-6) return null;
  let sse4 = 0, sse3 = 0;
  for (const q of S) {
    const x = (q[0] - mx) / sc, y = (q[1] - my) / sc, l = 0.299 * q[2] + 0.587 * q[3] + 0.114 * q[4] - Lm;
    sse4 += (l - (b * x + c * y + k * (x * x + y * y) + a)) ** 2; sse3 += (l - (sol3[0] * x + sol3[1] * y + sol3[2])) ** 2;
  }
  if (sse4 > sse3 * 0.6 || sst - sse4 < N * 40) return null; // радиальная не намного лучше линейной
  const cx = -b / (2 * k), cy = -c / (2 * k);
  if (Math.hypot(cx, cy) > 2.5) return null; // центр далеко — хватит линейного
  const X = mx + cx * sc, Y = my + cy * sc;
  let rmin = Infinity, rmax = 0, sr = 0, srr = 0;
  const rs = S.map(q => { const r = Math.hypot(q[0] - X, q[1] - Y); if (r < rmin) rmin = r; if (r > rmax) rmax = r; sr += r; srr += r * r; return r; });
  const mrr = sr / N, vr = srr / N - mrr * mrr; if (vr < 1e-6 || rmax < 2) return null;
  const col = (r) => [2, 3, 4].map((ch, kk) => { let s = 0, m = 0; for (let i = 0; i < N; i++) m += S[i][ch]; m /= N; for (let i = 0; i < N; i++) s += (rs[i] - mrr) * (S[i][ch] - m); return Math.round(m + s / N / vr * (r - mrr)); });
  return { radial: true, cx: +X.toFixed(1), cy: +Y.toFixed(1), r: +rmax.toFixed(1), o1: +(rmin / rmax).toFixed(3), c1: hex(col(rmin)), c2: hex(col(rmax)) };
}

export function toSVG(vec, pwMm, phMm, { background = true } = {}) {
  const parts = [`<svg xmlns="http://www.w3.org/2000/svg" width="${pwMm}mm" height="${phMm}mm" viewBox="0 0 ${vec.w} ${vec.h}">`,
    `<title>Рейка AR — оцифрованный рисунок</title>`];
  if (background) parts.push(`<rect width="${vec.w}" height="${vec.h}" fill="#ffffff"/>`);
  if (vec.colors.length) {
    parts.push('<g id="colors">');
    let gi = 0; const defs = [];
    for (const l of vec.colors) {
      if (!l.parts) { parts.push(`<path id="${l.name.replace(/\s/g, '_')}" fill="${l.color}" stroke="${l.color}" stroke-width="0.8" stroke-linejoin="round" fill-rule="evenodd" d="${l.d}"/>`); continue; }
      parts.push(`<g id="${l.name.replace(/\s/g, '_')}">`);
      for (const q of l.parts) {
        let f = q.fill;
        if (typeof f !== 'string' && f.radial) { const id = 'g' + (gi++); defs.push(`<radialGradient id="${id}" gradientUnits="userSpaceOnUse" cx="${f.cx}" cy="${f.cy}" r="${f.r}"><stop offset="${f.o1}" stop-color="${f.c1}"/><stop offset="1" stop-color="${f.c2}"/></radialGradient>`); f = `url(#${id})`; }
        else if (typeof f !== 'string') { const id = 'g' + (gi++); defs.push(`<linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="${f.x1}" y1="${f.y1}" x2="${f.x2}" y2="${f.y2}"><stop offset="0" stop-color="${f.c1}"/><stop offset="1" stop-color="${f.c2}"/></linearGradient>`); f = `url(#${id})`; }
        parts.push(`<path fill="${f}" stroke="${f}" stroke-width="0.8" stroke-linejoin="round" fill-rule="evenodd" d="${q.d}"/>`);
      }
      parts.push('</g>');
    }
    if (defs.length) parts.splice(2, 0, '<defs>' + defs.join('') + '</defs>');
    parts.push('</g>');
  }
  if (vec.lines.d) parts.push(`<g id="lines"><path fill="${vec.lines.color}" fill-rule="evenodd" d="${vec.lines.d}"/></g>`);
  parts.push('</svg>');
  return parts.join('\n');
}

// Рисуем вектор в canvas (для предпросмотра и PNG/JPG).
export function renderVector(vec, scale, { background = true, colors = true } = {}) {
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(vec.w * scale)); c.height = Math.max(1, Math.round(vec.h * scale));
  const g = c.getContext('2d');
  if (background) { g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height); }
  g.scale(scale, scale);
  g.lineJoin = 'round';
  if (colors) for (const l of vec.colors) {
    for (const q of (l.parts || [{ d: l.d, fill: l.color }])) {
      const p = new Path2D(q.d); let f = q.fill;
      if (typeof f !== 'string' && f.radial) { const gr = g.createRadialGradient(f.cx, f.cy, 0, f.cx, f.cy, f.r); gr.addColorStop(f.o1, f.c1); gr.addColorStop(1, f.c2); f = gr; }
      else if (typeof f !== 'string') { const gr = g.createLinearGradient(f.x1, f.y1, f.x2, f.y2); gr.addColorStop(0, f.c1); gr.addColorStop(1, f.c2); f = gr; }
      g.fillStyle = f; g.strokeStyle = f; g.lineWidth = 0.8; g.fill(p, 'evenodd'); g.stroke(p);
    }
  }
  if (vec.lines.d) { g.fillStyle = vec.lines.color; g.fill(new Path2D(vec.lines.d), 'evenodd'); }
  return c;
}

export function imageDataCanvas(img) {
  const c = document.createElement('canvas');
  c.width = img.w; c.height = img.h;
  c.getContext('2d').putImageData(new ImageData(img.data, img.w, img.h), 0, 0);
  return c;
}

// ---------- Скан «как у сканера документов» ----------
// mode: 'color' | 'gray' | 'bw'; sharpen 0..1.5 — нерезкое маскирование (возвращает чёткость
// после выпрямления и сглаживания кадров).
export function enhance(img, { mode = 'color', sharpen = 0.6, clean = 0.5, obscura = 0, tone = 'none', ppm = 6, lpi = 45 } = {}) {
  const { data, w, h } = img, n = w * h;
  const out = new Uint8ClampedArray(n * 4);
  const ch3 = mode === 'color' ? 3 : 1;
  const planes = [];
  if (ch3 === 3) for (let c = 0; c < 3; c++) { const p = new Float32Array(n); for (let i = 0; i < n; i++) p[i] = data[i * 4 + c]; planes.push(p); }
  else { const p = new Float32Array(n); for (let i = 0; i < n; i++) p[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2]; planes.push(p); }
  if (sharpen > 0) {
    for (const p of planes) {
      const bl = boxBlur(p, w, h, 1);
      for (let i = 0; i < n; i++) p[i] = p[i] + sharpen * (p[i] - bl[i]);
    }
  }
  if (mode === 'manga') return mangaTone(planes[0], w, h, ppm, lpi, clean);
  if (mode === 'bw') {
    // Ч/Б с мягким краем (без «лесенки»)
    const T = 205 - 45 * clean, soft = 14;
    const p = planes[0];
    for (let i = 0; i < n; i++) { const v = Math.max(0, Math.min(1, (p[i] - (T - soft)) / (2 * soft))) * 255; out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = v; out[i * 4 + 3] = 255; }
    return { data: out, w, h };
  }
  for (let i = 0; i < n; i++) {
    if (ch3 === 3) { out[i * 4] = planes[0][i]; out[i * 4 + 1] = planes[1][i]; out[i * 4 + 2] = planes[2][i]; }
    else out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = planes[0][i];
    out[i * 4 + 3] = 255;
  }
  if (obscura > 0 || tone !== 'none') oldPhoto(out, w, h, img.light, obscura, tone);
  return { data: out, w, h };
}

// Манга: тушь — сплошным чёрным, полутона — точечным растром (AM-скринтон, 45°), как в печати.
// Результат строго чёрно-белый, в 2× разрешении, чтобы точки были круглыми, а не «лесенкой».
function mangaTone(L, w, h, ppm, lpi, clean) {
  const up = 2, W = w * up, H = h * up, out = new Uint8ClampedArray(W * H * 4);
  const loc = boxBlur(L, w, h, Math.max(2, Math.round(1.2 * ppm)));
  const per = ppm * up * 25.4 / lpi;                    // период растра в пикселях выхода
  const inkT = 60 + 30 * (1 - clean), paperT = 238 - 10 * (1 - clean), dLine = 22;
  // тон считаем БЕЗ линий (усреднение только по не-линиям), иначе вокруг штриха — ореол из точек
  const n = w * h, mk = new Float32Array(n), lm = new Float32Array(n);
  for (let i = 0; i < n; i++) { const isL = L[i] < inkT || (loc[i] - L[i] > dLine && L[i] < 205); mk[i] = isL ? 0 : 1; lm[i] = isL ? 0 : L[i]; }
  const rT = Math.max(1, Math.round(per / up / 2)), bm = boxBlur(mk, w, h, rT + 1), bl = boxBlur(lm, w, h, rT + 1);
  const tone = new Float32Array(n);
  for (let i = 0; i < n; i++) tone[i] = bm[i] > 0.05 ? bl[i] / bm[i] : 255;
  const c45 = Math.SQRT1_2;
  const at = (A, x, y) => { // билинейно из исходного разрешения
    const fx = Math.min(w - 1.001, Math.max(0, x / up - 0.25)), fy = Math.min(h - 1.001, Math.max(0, y / up - 0.25));
    const x0 = fx | 0, y0 = fy | 0, tx = fx - x0, ty = fy - y0, i = y0 * w + x0;
    return (A[i] * (1 - tx) + A[i + 1] * tx) * (1 - ty) + (A[i + w] * (1 - tx) + A[i + w + 1] * tx) * ty;
  };
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const l = at(L, x, y), lc = at(loc, x, y);
    let black;
    if (l < inkT || (lc - l > dLine && l < 205)) black = true;           // тушь и линии
    else {
      const t = Math.max(0, Math.min(1, (paperT - at(tone, x, y)) / (paperT - inkT)));
      if (t < 0.04) black = false;
      else if (t > 0.96) black = true;
      else {
        const u = (x * c45 + y * c45) / per, v = (-x * c45 + y * c45) / per;
        let fu = u - Math.floor(u) - 0.5, fv = v - Math.floor(v) - 0.5;
        if (t <= 0.5) black = fu * fu + fv * fv < t / Math.PI;           // чёрные точки
        else { fu = fu < 0 ? fu + 0.5 : fu - 0.5; fv = fv < 0 ? fv + 0.5 : fv - 0.5; black = !(fu * fu + fv * fv < (1 - t) / Math.PI); } // белые точки
      }
    }
    const o = (y * W + x) * 4, val = black ? 0 : 255;
    out[o] = out[o + 1] = out[o + 2] = val; out[o + 3] = 255;
  }
  return { data: out, w: W, h: H };
}

// «Старое фото / камера-обскура»: светлый центр и тёмные края — по НАСТОЯЩЕЙ карте света
// этого снимка (как было на бумаге) плюс мягкая виньетка объектива, тон и зерно.
function oldPhoto(out, w, h, light, a, tone) {
  const tint = tone === 'sepia' ? [1.07, 0.95, 0.8] : tone === 'cold' ? [0.92, 0.98, 1.08] : [1, 1, 1];
  const ta = tone === 'none' ? 0 : Math.max(0.6, a);
  const mul = tint.map(t => 1 + (t - 1) * ta);
  let seed = 12345; const rnd = () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 4294967296);
  const lightAt = (x, y) => {
    if (!light) return 1;
    const { g, gx, gy, cell } = light;
    const fx = Math.max(0, Math.min(gx - 1, (x + 0.5) / cell - 0.5)), fy = Math.max(0, Math.min(gy - 1, (y + 0.5) / cell - 0.5));
    const x0 = Math.floor(fx), y0 = Math.floor(fy), x1 = Math.min(gx - 1, x0 + 1), y1 = Math.min(gy - 1, y0 + 1), tx = fx - x0, ty = fy - y0;
    return (g[y0 * gx + x0] * (1 - tx) + g[y0 * gx + x1] * tx) * (1 - ty) + (g[y1 * gx + x0] * (1 - tx) + g[y1 * gx + x1] * tx) * ty;
  };
  const step = 4; // карту считаем по сетке 4 px и интерполируем — быстро
  const gw = Math.ceil(w / step) + 1, gh = Math.ceil(h / step) + 1, F = new Float32Array(gw * gh);
  for (let j = 0; j < gh; j++) for (let i = 0; i < gw; i++) {
    const x = Math.min(w - 1, i * step), y = Math.min(h - 1, j * step);
    const u = (x / w - 0.5) * 2, v = (y / h - 0.5) * 2, r2 = (u * u + v * v) / 2;
    const syn = 1 - 0.55 * r2 * r2 - 0.25 * r2;
    F[j * gw + i] = 1 + (Math.pow(lightAt(x, y), 1.5) * syn - 1) * a;
  }
  for (let y = 0; y < h; y++) {
    const fj = y / step, j0 = Math.floor(fj), tj = fj - j0;
    for (let x = 0; x < w; x++) {
      const fi = x / step, i0 = Math.floor(fi), ti = fi - i0;
      const f = (F[j0 * gw + i0] * (1 - ti) + F[j0 * gw + i0 + 1] * ti) * (1 - tj) + (F[(j0 + 1) * gw + i0] * (1 - ti) + F[(j0 + 1) * gw + i0 + 1] * ti) * tj;
      const gr = a > 0 ? (rnd() - 0.5) * 12 * a : 0, o = (y * w + x) * 4;
      for (let c = 0; c < 3; c++) out[o + c] = out[o + c] * f * mul[c] + gr;
    }
  }
}

// Резкость кадра: дисперсия лапласиана по яркости (смазанный кадр — маленькая).
export function sharpness(img) {
  const { data, w, h } = img;
  let s = 0, s2 = 0, c = 0;
  const x0 = Math.round(w * 0.08), x1 = Math.round(w * 0.92), y0 = Math.round(h * 0.08), y1 = Math.round(h * 0.92);
  const L = (x, y) => { const i = (y * w + x) * 4; return 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]; };
  for (let y = y0; y < y1; y += 2) for (let x = x0; x < x1; x += 2) {
    const v = 4 * L(x, y) - L(x - 1, y) - L(x + 1, y) - L(x, y - 1) - L(x, y + 1);
    s += v; s2 += v * v; c++;
  }
  return c ? s2 / c - (s / c) ** 2 : 0;
}

// Совмещаем выпрямленные кадры с первым (самым резким) сдвигом ±3 пикселя и усредняем.
export function alignAverage(list) {
  if (list.length === 1) return list[0];
  const ref = list[0], { w, h } = ref;
  const acc = new Float32Array(w * h * 3), cnt = new Float32Array(w * h);
  const gray = (img) => { const g = new Float32Array(w * h); for (let i = 0; i < w * h; i++) g[i] = 0.299 * img.data[i * 4] + 0.587 * img.data[i * 4 + 1] + 0.114 * img.data[i * 4 + 2]; return g; };
  const gr = gray(ref);
  for (let k = 0; k < list.length; k++) {
    const img = list[k];
    let bx = 0, by = 0;
    if (k > 0) {
      const gi = gray(img);
      let bs = Infinity;
      for (let dy = -3; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) {
        let sad = 0;
        for (let y = Math.round(h * 0.1); y < h * 0.9; y += 3) for (let x = Math.round(w * 0.1); x < w * 0.9; x += 3) sad += Math.abs(gr[y * w + x] - gi[(y + dy) * w + x + dx]);
        if (sad < bs) { bs = sad; bx = dx; by = dy; }
      }
    }
    for (let y = 0; y < h; y++) {
      const sy = y + by; if (sy < 0 || sy >= h) continue;
      for (let x = 0; x < w; x++) {
        const sx = x + bx; if (sx < 0 || sx >= w) continue;
        const i = y * w + x, j = (sy * w + sx) * 4;
        acc[i * 3] += img.data[j]; acc[i * 3 + 1] += img.data[j + 1]; acc[i * 3 + 2] += img.data[j + 2]; cnt[i]++;
      }
    }
  }
  const out = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) { const c = cnt[i] || 1; out[i * 4] = acc[i * 3] / c; out[i * 4 + 1] = acc[i * 3 + 1] / c; out[i * 4 + 2] = acc[i * 3 + 2] / c; out[i * 4 + 3] = 255; }
  return { data: out, w, h };
}
