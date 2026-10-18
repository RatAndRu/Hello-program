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
export function flatten(img, ppm, clean = 0.5) {
  const { data, w, h } = img;
  const cell = Math.max(12, Math.round(ppm * 12));
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
    for (let k = 0; k < gx * gy; k++) if (has[k] && bg[k * 3] + bg[k * 3 + 1] + bg[k * 3 + 2] < ref * 0.72) has[k] = 0;
  }
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
  const out = new Uint8ClampedArray(w * h * 4);
  const cut = 255 - 45 * clean;
  for (let y = 0; y < h; y++) {
    const fy = Math.min(gy - 1, Math.max(0, (y + 0.5) / cell - 0.5)), y0 = Math.floor(fy), y1 = Math.min(gy - 1, y0 + 1), ty = fy - y0;
    for (let x = 0; x < w; x++) {
      const fx = Math.min(gx - 1, Math.max(0, (x + 0.5) / cell - 0.5)), x0 = Math.floor(fx), x1 = Math.min(gx - 1, x0 + 1), tx = fx - x0;
      const i = (y * w + x) * 4;
      for (let ch = 0; ch < 3; ch++) {
        const a = sm[(y0 * gx + x0) * 3 + ch] * (1 - tx) + sm[(y0 * gx + x1) * 3 + ch] * tx;
        const b = sm[(y1 * gx + x0) * 3 + ch] * (1 - tx) + sm[(y1 * gx + x1) * 3 + ch] * tx;
        const bgv = Math.max(30, a * (1 - ty) + b * ty);
        let v = data[i + ch] / bgv * 255;
        v = v >= cut ? 255 : v * 255 / cut; // всё, что близко к бумаге, — чисто белое
        out[i + ch] = v;
      }
      out[i + 3] = 255;
    }
  }
  return { data: out, w, h };
}

// ---------- 4–5. Разделение на линии и цвета ----------
// lineLevel 0..1 — чувствительность к линиям; colors — сколько цветов (0 — только линии);
// minSpot — минимальный размер пятна в мм².
export function segment(img, ppm, { lineLevel = 0.5, colors = 6, minSpot = 2, paint = true } = {}) {
  const { data, w, h } = img;
  const n = w * h;
  const kind = new Uint8Array(n); // 0 бумага, 1 линия, 2 краска
  const lineThr = 90 + 110 * lineLevel; // яркость, ниже которой бесцветное — линия
  const colored = [];
  for (let i = 0, j = 0; i < n; i++, j += 4) {
    const r = data[j], g = data[j + 1], b = data[j + 2];
    const L = 0.299 * r + 0.587 * g + 0.114 * b;
    const C = Math.max(r, g, b) - Math.min(r, g, b);
    if (L < 60 || (L < lineThr && C < 55 + (lineThr - L) * 0.4)) kind[i] = 1;
    else if (paint && colors > 0 && (C > 28 || L < 225)) { kind[i] = 2; colored.push(i); }
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
    palette = mergeClose(kmeans(sample, Math.min(colors, sample.length)), sample);
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
function mergeClose(C, pts) {
  const cnt = C.map(() => 0);
  for (const p of pts) { let b = 0, bd = Infinity; C.forEach((c, i) => { const d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2; if (d < bd) { bd = d; b = i; } }); cnt[b]++; }
  let list = C.map((c, i) => ({ c, n: cnt[i] })).filter(x => x.n > 0);
  for (let changed = true; changed;) {
    changed = false;
    outer: for (let i = 0; i < list.length; i++) for (let j = i + 1; j < list.length; j++) {
      const a = list[i], b = list[j];
      const d = Math.sqrt((a.c[0] - b.c[0]) ** 2 * 0.3 + (a.c[1] - b.c[1]) ** 2 * 0.59 + (a.c[2] - b.c[2]) ** 2 * 0.11);
      if (d < 26) {
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
  const lim0 = Math.max(3, Math.round(Math.min(w, h) * 0.025));
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
  for (let s = 0; s < w * h; s++) {
    if (!kind[s] || seen[s]) continue;
    const sy = (s / w) | 0, sx = s - sy * w;
    if (sx >= B && sy >= B && sx < w - B && sy < h - B) continue;
    let sp = 0; comp.length = 0; stack[sp++] = s; seen[s] = 1;
    let x0 = w, x1 = 0, y0 = h, y1 = 0;
    while (sp) {
      const i = stack[--sp]; comp.push(i);
      const y = (i / w) | 0, x = i - y * w;
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
      for (const j of [x > 0 ? i - 1 : -1, x < w - 1 ? i + 1 : -1, y > 0 ? i - w : -1, y < h - 1 ? i + w : -1]) if (j >= 0 && !seen[j] && kind[j]) { seen[j] = 1; stack[sp++] = j; }
    }
    // «прилип к краю и тонкий вдоль него» — значит, это не рисунок
    const touchL = x0 < B, touchR = x1 >= w - B, touchT = y0 < B, touchB = y1 >= h - B;
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
export function traceMask(mask, w, h, { simplify = 0.9, minArea = 4, smooth = true } = {}) {
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
    const simp = simplifyClosed(pts, simplify);
    if (simp.length < 3) continue;
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

export function vectorize(seg, ppm, { smooth = 1, lineBlack = false, withColors = true } = {}) {
  const { w, h, kind, label, palette } = seg;
  const eps = 0.6 + smooth * 0.9;
  const layers = [];
  if (withColors) {
    for (let c = 1; c <= palette.length; c++) {
      const pc = palette[c - 1], chroma = Math.max(...pc) - Math.min(...pc), lum = 0.299 * pc[0] + 0.587 * pc[1] + 0.114 * pc[2];
      if (chroma < 22 && lum > 175) continue; // блёклый серый ореол вокруг линий — это бумага
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
        const d = traceMask(m, w, h, { simplify: eps, minArea: ppm * ppm * 1.0 });
        if (d) layers.push({ name: 'Цвет ' + c, color: hex(palette[c - 1]), d });
      }
    }
  }
  const lm = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) if (kind[i] === 1) lm[i] = 1;
  const ld = traceMask(lm, w, h, { simplify: Math.max(0.6, eps * 0.75), minArea: 2 });
  const lines = { name: 'Линии', color: lineBlack ? '#1a1a1a' : hex(seg.lineColor), d: ld };
  return { w, h, colors: layers, lines };
}

export function toSVG(vec, pwMm, phMm, { background = true } = {}) {
  const parts = [`<svg xmlns="http://www.w3.org/2000/svg" width="${pwMm}mm" height="${phMm}mm" viewBox="0 0 ${vec.w} ${vec.h}">`,
    `<title>Рейка AR — оцифрованный рисунок</title>`];
  if (background) parts.push(`<rect width="${vec.w}" height="${vec.h}" fill="#ffffff"/>`);
  if (vec.colors.length) {
    parts.push('<g id="colors">');
    for (const l of vec.colors) parts.push(`<path id="${l.name.replace(/\s/g, '_')}" fill="${l.color}" stroke="${l.color}" stroke-width="0.8" stroke-linejoin="round" fill-rule="evenodd" d="${l.d}"/>`);
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
  if (colors) for (const l of vec.colors) { const p = new Path2D(l.d); g.fillStyle = l.color; g.strokeStyle = l.color; g.lineWidth = 0.8; g.fill(p, 'evenodd'); g.stroke(p); }
  if (vec.lines.d) { g.fillStyle = vec.lines.color; g.fill(new Path2D(vec.lines.d), 'evenodd'); }
  return c;
}

export function imageDataCanvas(img) {
  const c = document.createElement('canvas');
  c.width = img.w; c.height = img.h;
  c.getContext('2d').putImageData(new ImageData(img.data, img.w, img.h), 0, 0);
  return c;
}
