// Метод скана из версии 1.3 («обскура»): ровно тот код, что дал понравившийся эффект.
// Освещение бумаги приближается гладким полиномом 3-й степени по всему листу. На краях он
// «перелетает», поэтому края темнеют, центр светлеет — получается виньетка, как у старой
// камеры-обскуры, а тоновая кривая делает карандаш контрастным. Не исправляем — это стиль.

export function flatten13(img, ppm, clean = 0.5) {
  const { data, w, h } = img;
  const cell = Math.max(10, Math.round(ppm * 7));
  const gx = Math.ceil(w / cell), gy = Math.ceil(h / cell);
  const bg = new Float32Array(gx * gy * 3), has = new Uint8Array(gx * gy);
  const buf = [];
  for (let cy = 0; cy < gy; cy++) for (let cx = 0; cx < gx; cx++) {
    buf.length = 0;
    let total = 0;
    for (let y = cy * cell; y < Math.min(h, (cy + 1) * cell); y += 2) for (let x = cx * cell; x < Math.min(w, (cx + 1) * cell); x += 2) {
      const i = (y * w + x) * 4, r = data[i], g = data[i + 1], b = data[i + 2];
      total++;
      const mx = Math.max(r, g, b), mn = Math.min(r, g, b);
      if (mx - mn < 48) buf.push(r + g + b, r, g, b);
    }
    const n = buf.length / 4;
    if (n < total * 0.12 || n < 6) continue;
    // берём самые светлые 35% бесцветных пикселей — это бумага
    const idx = [...Array(n).keys()].sort((a, b) => buf[b * 4] - buf[a * 4]).slice(0, Math.max(3, Math.round(n * 0.35)));
    let r = 0, g = 0, b = 0;
    for (const k of idx) { r += buf[k * 4 + 1]; g += buf[k * 4 + 2]; b += buf[k * 4 + 3]; }
    const o = (cy * gx + cx) * 3;
    bg[o] = r / idx.length; bg[o + 1] = g / idx.length; bg[o + 2] = b / idx.length; has[cy * gx + cx] = 1;
  }
  // клетки, где «бумагой» оказалась тёмная линия (вся клетка закрашена), — отбрасываем
  {
    const lv = []; for (let k = 0; k < gx * gy; k++) if (has[k]) lv.push(bg[k * 3] + bg[k * 3 + 1] + bg[k * 3 + 2]);
    lv.sort((a, b) => a - b);
    const ref = lv.length ? lv[Math.floor(lv.length * 0.75)] : 0;
    // сравниваем с соседями (а не со всем листом): плавная виньетка/тень в углу — это бумага,
    // а клетка, резко темнее соседей, — закрашенное место
    const lum = (k) => bg[k * 3] + bg[k * 3 + 1] + bg[k * 3 + 2];
    const drop = [];
    for (let cy = 0; cy < gy; cy++) for (let cx = 0; cx < gx; cx++) {
      const k = cy * gx + cx; if (!has[k]) continue;
      const nb = [];
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) { if (!dx && !dy) continue; const x = cx + dx, y = cy + dy; if (x < 0 || y < 0 || x >= gx || y >= gy || !has[y * gx + x]) continue; nb.push(lum(y * gx + x)); }
      nb.sort((a, b) => a - b);
      const loc = nb.length >= 3 ? nb[Math.floor(nb.length * 0.6)] : ref;
      if (lum(k) < loc * 0.8 || lum(k) < ref * 0.4) drop.push(k);
    }
    for (const k of drop) has[k] = 0;
  }
  const meas = has.slice(), measBg = bg.slice(); // реально измеренные клетки — для гладкой модели
  // пустые клетки (закрыты краской) — заполняем соседями
  if (!has.some(Boolean)) { bg.fill(235); has.fill(1); }
  for (let iter = 0; iter < gx + gy && has.some(v => !v); iter++) {
    const nh = has.slice();
    for (let cy = 0; cy < gy; cy++) for (let cx = 0; cx < gx; cx++) {
      const k = cy * gx + cx; if (has[k]) continue;
      let r = 0, g = 0, b = 0, c = 0;
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]]) {
        const x = cx + dx, y = cy + dy; if (x < 0 || y < 0 || x >= gx || y >= gy || !has[y * gx + x]) continue;
        const o = (y * gx + x) * 3; r += bg[o]; g += bg[o + 1]; b += bg[o + 2]; c++;
      }
      if (c) { const o = k * 3; bg[o] = r / c; bg[o + 1] = g / c; bg[o + 2] = b / c; nh[k] = 1; }
    }
    has.set(nh);
  }
  // лёгкое сглаживание сетки
  const sm = bg.slice();
  for (let cy = 0; cy < gy; cy++) for (let cx = 0; cx < gx; cx++) for (let ch = 0; ch < 3; ch++) {
    let s = 0, c = 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const x = cx + dx, y = cy + dy; if (x < 0 || y < 0 || x >= gx || y >= gy) continue; s += bg[(y * gx + x) * 3 + ch]; c++; }
    sm[(cy * gx + cx) * 3 + ch] = s / c;
  }
  // Освещение бумаги — гладкая поверхность (полином 3-й степени по x, y), подогнанная по клеткам
  // с асимметричным отбором: бумага — самое светлое, поэтому клетки темнее модели (штриховка,
  // тень на рисунке) постепенно теряют вес. Плавные тени лампы и виньетку модель повторяет,
  // а крупную штриховку «съесть» не может — она остаётся на скане.
  const poly = fitLightSurface(measBg, meas, gx, gy);
  // «Очистка фона» выше 0.6 добавляет локальную сетку: уходят и резкие тени (от руки, телефона),
  // но может посветлеть крупная штриховка.
  const alpha = Math.max(0, Math.min(1, (clean - 0.6) / 0.4));
  const ratio = new Float32Array(w * h * 3);
  const basis = new Float32Array(10), PB = [0, 0, 0], LB = [0, 0, 0];
  for (let y = 0; y < h; y++) {
    const fyR = (y + 0.5) / cell - 0.5, y0 = Math.max(0, Math.min(gy - 2, Math.floor(fyR))), y1 = Math.min(gy - 1, y0 + 1);
    const ty = gy > 1 ? Math.max(-0.6, Math.min(1.6, fyR - y0)) : 0;
    const v = ((y + 0.5) / cell) / gy * 2 - 1;
    for (let x = 0; x < w; x++) {
      const fxR = (x + 0.5) / cell - 0.5, x0 = Math.max(0, Math.min(gx - 2, Math.floor(fxR))), x1 = Math.min(gx - 1, x0 + 1);
      const tx = gx > 1 ? Math.max(-0.6, Math.min(1.6, fxR - x0)) : 0;
      const u = ((x + 0.5) / cell) / gx * 2 - 1;
      polyBasis(u, v, basis);
      const i = (y * w + x) * 4, o = (y * w + x) * 3;
      let pl = 0, ll = 0;
      for (let ch = 0; ch < 3; ch++) {
        let pb = 0; const cf = poly[ch]; for (let k = 0; k < 10; k++) pb += cf[k] * basis[k];
        const a = sm[(y0 * gx + x0) * 3 + ch] * (1 - tx) + sm[(y0 * gx + x1) * 3 + ch] * tx;
        const b = sm[(y1 * gx + x0) * 3 + ch] * (1 - tx) + sm[(y1 * gx + x1) * 3 + ch] * tx;
        PB[ch] = pb; LB[ch] = a * (1 - ty) + b * ty; pl += pb; ll += LB[ch];
      }
      // Локальная оценка близка к гладкой (±5–12%) — это бумага, гладкая модель там просто
      // неточна (края, места без «чистой» бумаги): берём локальную. Намного темнее — это
      // штриховка/тень рисунка: оставляем гладкую, чтобы не стереть.
      const rr = Math.abs(ll / Math.max(1, pl) - 1);
      const wl = Math.max(alpha, Math.max(0, Math.min(1, 1 - (rr - 0.05) / 0.07)));
      for (let ch = 0; ch < 3; ch++) {
        const bgv = PB[ch] * (1 - wl) + LB[ch] * wl;
        ratio[o + ch] = Math.max(0, 1 - data[i + ch] / Math.max(30, bgv));
      }
    }
  }
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
  return { data: out, w, h, gain: kk };
}

function polyBasis(u, v, b) {
  b[0] = 1; b[1] = u; b[2] = v; b[3] = u * u; b[4] = u * v; b[5] = v * v; b[6] = u * u * u; b[7] = u * u * v; b[8] = u * v * v; b[9] = v * v * v;
}
// Взвешенный МНК с асимметричным перевзвешиванием (клетки темнее модели теряют вес).
function fitLightSurface(bg, has, gx, gy) {
  const pts = [];
  for (let cy = 0; cy < gy; cy++) for (let cx = 0; cx < gx; cx++) {
    const k = cy * gx + cx; if (!has[k]) continue;
    pts.push({ u: (cx + 0.5) / gx * 2 - 1, v: (cy + 0.5) / gy * 2 - 1, c: [bg[k * 3], bg[k * 3 + 1], bg[k * 3 + 2]], wt: 1 });
  }
  const flat = (val) => [[val, 0, 0, 0, 0, 0, 0, 0, 0, 0], [val, 0, 0, 0, 0, 0, 0, 0, 0, 0], [val, 0, 0, 0, 0, 0, 0, 0, 0, 0]];
  if (pts.length < 4) return flat(pts.length ? (pts[0].c[0] + pts[0].c[1] + pts[0].c[2]) / 3 : 235);
  const nb = pts.length >= 24 ? 10 : pts.length >= 8 ? 6 : 3; // мало клеток — проще модель
  const b = new Float32Array(10);
  let coef = null;
  for (let it = 0; it < 10; it++) {
    const A = Array.from({ length: nb }, () => new Float64Array(nb)), R = [new Float64Array(nb), new Float64Array(nb), new Float64Array(nb)];
    for (const p of pts) {
      if (p.wt < 1e-3) continue;
      polyBasis(p.u, p.v, b);
      for (let i = 0; i < nb; i++) { const bi = b[i] * p.wt; for (let j = 0; j < nb; j++) A[i][j] += bi * b[j]; for (let ch = 0; ch < 3; ch++) R[ch][i] += bi * p.c[ch]; }
    }
    for (let i = 0; i < nb; i++) A[i][i] += 1e-6 * (A[0][0] || 1);
    const sol = [0, 1, 2].map(ch => solveSym(A, R[ch]));
    if (sol.some(x => !x)) break;
    coef = sol.map(x => { const c = new Array(10).fill(0); for (let i = 0; i < nb; i++) c[i] = x[i]; return c; });
    // перевзвешивание по яркости
    for (const p of pts) {
      polyBasis(p.u, p.v, b);
      let m = 0, val = 0;
      for (let ch = 0; ch < 3; ch++) { let s = 0; for (let i = 0; i < 10; i++) s += coef[ch][i] * b[i]; m += s; val += p.c[ch]; }
      const r = (val - m) / Math.max(1, m);
      p.wt = r >= -0.03 ? 1 : Math.exp(-(((r + 0.03) / 0.04) ** 2));
    }
  }
  return coef || flat(235);
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


export function enhance13(img, { mode = 'color', sharpen = 0.6, clean = 0.5 } = {}) {
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
  return { data: out, w, h };
}

