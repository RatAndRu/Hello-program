// Поиск листа бумаги в кадре без ИИ — классическое компьютерное зрение:
// 1) уменьшаем кадр и считаем яркость; 2) порог Оцу отделяет светлый лист от фона;
// 3) берём самую большую светлую область; 4) выпуклая оболочка → 4 угла;
// 5) уточняем стороны подгонкой прямых по краю и пересекаем их.
// Благодаря шагу 5 угол, закрытый пальцем, всё равно восстанавливается.

import { convexHull, polygonArea, isConvexQuad, dist, sub, cross } from './geom.js';

const ANALYSIS_LONG_SIDE = 320;

export class PaperTracker {
  constructor() {
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
    this.lastReason = '';
  }

  // source — <video> или canvas; vw/vh — его размеры в пикселях.
  detect(source, vw, vh) {
    if (!vw || !vh) return this.fail('нет кадра');
    const s = Math.min(1, ANALYSIS_LONG_SIDE / Math.max(vw, vh));
    const w = Math.max(16, Math.round(vw * s)), h = Math.max(16, Math.round(vh * s));
    if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
    try { this.ctx.drawImage(source, 0, 0, w, h); } catch { return this.fail('нет кадра'); }
    const data = this.ctx.getImageData(0, 0, w, h).data;
    const n = w * h;

    // Яркость + лёгкое размытие 3×3, чтобы карандашные штрихи не рвали маску.
    const lum0 = new Uint8ClampedArray(n);
    const chroma = new Uint8Array(n);
    for (let i = 0, j = 0; i < n; i++, j += 4) {
      const r = data[j], g = data[j + 1], b = data[j + 2];
      lum0[i] = (r * 77 + g * 150 + b * 29) >> 8;
      chroma[i] = Math.max(r, g, b) - Math.min(r, g, b);
    }
    const lum = boxBlur3(lum0, w, h);

    // Порог Оцу.
    const hist = new Uint32Array(256);
    for (let i = 0; i < n; i++) hist[lum[i]]++;
    const { t, m0, m1 } = otsu(hist, n);
    if (m1 - m0 < 28) return this.fail('мало контраста: положи лист на тёмный стол');

    // Бумага почти бесцветная, кожа руки — насыщеннее. Порог по насыщенности
    // адаптивный: медиана цветности светлых пикселей + запас (тёплая лампа ок).
    const chist = new Uint32Array(256);
    let bright = 0;
    for (let i = 0; i < n; i++) if (lum[i] > t) { chist[chroma[i]]++; bright++; }
    let acc = 0, med = 0;
    for (let i = 0; i < 256; i++) { acc += chist[i]; if (acc >= bright / 2) { med = i; break; } }
    const cmax = Math.max(40, Math.min(95, med + 30));
    const mask = new Uint8Array(n);
    for (let i = 0; i < n; i++) mask[i] = lum[i] > t && chroma[i] <= cmax ? 1 : 0;

    // Закрываем мелкие дырки (линии рисунка) — дилатация+эрозия 1px.
    const closed = erode(dilate(mask, w, h), w, h);

    const comp = largestComponent(closed, w, h);
    if (!comp) return this.fail('лист не найден');
    const { pixels, area } = comp;
    if (area < n * 0.04) return this.fail('лист слишком маленький или не виден');
    if (area > n * 0.97) return this.fail('лист занимает весь кадр — подними телефон выше');

    // Граница: крайние пиксели по строкам и столбцам.
    const rowMin = new Int32Array(h).fill(w), rowMax = new Int32Array(h).fill(-1);
    const colMin = new Int32Array(w).fill(h), colMax = new Int32Array(w).fill(-1);
    let borderTouch = 0;
    for (let k = 0; k < pixels.length; k++) {
      const idx = pixels[k], y = (idx / w) | 0, x = idx - y * w;
      if (x < rowMin[y]) rowMin[y] = x; if (x > rowMax[y]) rowMax[y] = x;
      if (y < colMin[x]) colMin[x] = y; if (y > colMax[x]) colMax[x] = y;
      if (x === 0 || y === 0 || x === w - 1 || y === h - 1) borderTouch++;
    }
    if (borderTouch > (w + h) * 0.12) return this.fail('лист не целиком в кадре');

    const edgePts = [];
    for (let y = 0; y < h; y++) if (rowMax[y] >= 0) { edgePts.push({ x: rowMin[y] + 0.5, y: y + 0.5 }); edgePts.push({ x: rowMax[y] + 0.5, y: y + 0.5 }); }
    for (let x = 0; x < w; x++) if (colMax[x] >= 0) { edgePts.push({ x: x + 0.5, y: colMin[x] + 0.5 }); edgePts.push({ x: x + 0.5, y: colMax[x] + 0.5 }); }

    const hull = convexHull(edgePts);
    if (hull.length < 4) return this.fail('лист не найден');
    let quad = maxAreaQuad(hull);
    if (!quad) return this.fail('лист не найден');

    const qa = Math.abs(polygonArea(quad));
    // Закрашенные места рисунка — «дырки» в маске бумаги; считаем их частью листа.
    const filled = filledArea(pixels, w, h);
    if (filled / qa < 0.72) return this.fail('форма не похожа на лист (рука или тень?)');

    const refined = refineQuad(quad, edgePts);
    const minSide = Math.min(...quad.map((p, i) => dist(p, quad[(i + 1) % 4])));
    const maxShift = Math.max(8, minSide * 0.18);
    if (refined && isConvexQuad(refined) && refined.every((p, i) => dist(p, quad[i]) < maxShift)) quad = refined;
    if (!isConvexQuad(quad)) return this.fail('лист не найден');

    this.lastReason = '';
    return { corners: quad.map(p => ({ x: p.x / s, y: p.y / s })), quality: Math.min(1, filled / qa) };
  }

  fail(reason) { this.lastReason = reason; return null; }
}

function boxBlur3(src, w, h) {
  const out = new Uint8ClampedArray(src.length);
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - 1), y1 = Math.min(h - 1, y + 1);
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - 1), x1 = Math.min(w - 1, x + 1);
      let s = 0, c = 0;
      for (let yy = y0; yy <= y1; yy++) for (let xx = x0; xx <= x1; xx++) { s += src[yy * w + xx]; c++; }
      out[y * w + x] = s / c;
    }
  }
  return out;
}

function otsu(hist, total) {
  let sum = 0;
  for (let i = 0; i < 256; i++) sum += i * hist[i];
  let sumB = 0, wB = 0, best = -1, t = 127, m0 = 0, m1 = 0;
  for (let i = 0; i < 256; i++) {
    wB += hist[i]; if (!wB) continue;
    const wF = total - wB; if (!wF) break;
    sumB += i * hist[i];
    const mB = sumB / wB, mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) * (mB - mF);
    if (between > best) { best = between; t = i; m0 = mB; m1 = mF; }
  }
  return { t, m0, m1 };
}

function dilate(m, w, h) {
  const o = new Uint8Array(m.length);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    o[i] = m[i] || (x > 0 && m[i - 1]) || (x < w - 1 && m[i + 1]) || (y > 0 && m[i - w]) || (y < h - 1 && m[i + w]) ? 1 : 0;
  }
  return o;
}

function erode(m, w, h) {
  const o = new Uint8Array(m.length);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    o[i] = m[i] && (x === 0 || m[i - 1]) && (x === w - 1 || m[i + 1]) && (y === 0 || m[i - w]) && (y === h - 1 || m[i + w]) ? 1 : 0;
  }
  return o;
}

function largestComponent(mask, w, h) {
  const n = w * h;
  const label = new Int32Array(n);
  const stack = new Int32Array(n);
  let best = null, cur = 0;
  for (let start = 0; start < n; start++) {
    if (!mask[start] || label[start]) continue;
    cur++;
    let sp = 0, count = 0;
    stack[sp++] = start; label[start] = cur;
    const pixels = [];
    while (sp) {
      const i = stack[--sp];
      pixels.push(i); count++;
      const y = (i / w) | 0, x = i - y * w;
      if (x > 0 && mask[i - 1] && !label[i - 1]) { label[i - 1] = cur; stack[sp++] = i - 1; }
      if (x < w - 1 && mask[i + 1] && !label[i + 1]) { label[i + 1] = cur; stack[sp++] = i + 1; }
      if (y > 0 && mask[i - w] && !label[i - w]) { label[i - w] = cur; stack[sp++] = i - w; }
      if (y < h - 1 && mask[i + w] && !label[i + w]) { label[i + w] = cur; stack[sp++] = i + w; }
    }
    if (!best || count > best.area) best = { pixels, area: count };
  }
  return best;
}

// Четырёхугольник максимальной площади из вершин оболочки (покоординатный подъём).
function maxAreaQuad(hull) {
  const n = hull.length;
  const pick = (f) => { let bi = 0, bv = -Infinity; for (let i = 0; i < n; i++) { const v = f(hull[i]); if (v > bv) { bv = v; bi = i; } } return bi; };
  let idx = [pick(p => -(p.x + p.y)), pick(p => p.x - p.y), pick(p => p.x + p.y), pick(p => p.y - p.x)];
  if (new Set(idx).size < 4) {
    idx = [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor(3 * n / 4)];
  }
  // Упорядочить по ходу оболочки.
  const order = idx.map((v, k) => ({ v, k })).sort((a, b) => a.v - b.v);
  let ids = order.map(o => o.v);
  const area = (ii) => Math.abs(polygonArea(ii.map(i => hull[i])));
  for (let iter = 0; iter < 4; iter++) {
    let changed = false;
    for (let k = 0; k < 4; k++) {
      const prev = ids[(k + 3) % 4], next = ids[(k + 1) % 4];
      let bestI = ids[k], bestA = area(ids);
      for (let j = (prev + 1) % n; j !== next; j = (j + 1) % n) {
        const t = ids.slice(); t[k] = j;
        const a = area(t);
        if (a > bestA + 1e-6) { bestA = a; bestI = j; }
      }
      if (bestI !== ids[k]) { ids[k] = bestI; changed = true; }
    }
    if (!changed) break;
  }
  if (new Set(ids).size < 4) return null;
  return ids.map(i => ({ x: hull[i].x, y: hull[i].y }));
}

// Уточнение: подгоняем прямую к краевым точкам каждой стороны и пересекаем.
function refineQuad(quad, pts) {
  const lines = [];
  for (let k = 0; k < 4; k++) {
    const a = quad[k], b = quad[(k + 1) % 4];
    let line = fitSide(a, b, pts, 4.0);
    for (const tol of [3.0, 2.0, 1.6]) if (line) line = fitSide(a, b, pts, tol, line) || line;
    if (!line) line = { p: a, d: sub(b, a) };
    lines.push(line);
  }
  const out = [];
  for (let k = 0; k < 4; k++) {
    const L1 = lines[(k + 3) % 4], L2 = lines[k];
    const den = cross(L1.d, L2.d);
    if (Math.abs(den) < 1e-9) return null;
    const t = cross(sub(L2.p, L1.p), L2.d) / den;
    out.push({ x: L1.p.x + L1.d.x * t, y: L1.p.y + L1.d.y * t });
  }
  return out;
}

function fitSide(a, b, pts, tol, ref) {
  const lp = ref ? ref.p : a;
  const ld = ref ? ref.d : sub(b, a);
  const L = Math.hypot(ld.x, ld.y) || 1;
  const ux = ld.x / L, uy = ld.y / L;
  const ab = sub(b, a), abL2 = ab.x * ab.x + ab.y * ab.y || 1;
  let sx = 0, sy = 0, c = 0;
  const sel = [];
  for (const p of pts) {
    const t = ((p.x - a.x) * ab.x + (p.y - a.y) * ab.y) / abL2;
    if (t < 0.08 || t > 0.92) continue;
    const dpx = p.x - lp.x, dpy = p.y - lp.y;
    const d = Math.abs(dpx * uy - dpy * ux);
    if (d > tol) continue;
    sel.push(p); sx += p.x; sy += p.y; c++;
  }
  if (c < 8) return null;
  const mx = sx / c, my = sy / c;
  let xx = 0, xy = 0, yy = 0;
  for (const p of sel) { const dx = p.x - mx, dy = p.y - my; xx += dx * dx; xy += dx * dy; yy += dy * dy; }
  const ang = 0.5 * Math.atan2(2 * xy, xx - yy);
  return { p: { x: mx, y: my }, d: { x: Math.cos(ang), y: Math.sin(ang) } };
}

// Площадь области вместе с внутренними дырками: заливаем «снаружи» от краёв кадра.
function filledArea(pixels, w, h) {
  const m = new Uint8Array(w * h);
  for (let k = 0; k < pixels.length; k++) m[pixels[k]] = 1;
  const stack = new Int32Array(w * h);
  let sp = 0, outside = 0;
  const push = (i) => { if (!m[i]) { m[i] = 2; stack[sp++] = i; } };
  for (let x = 0; x < w; x++) { push(x); push((h - 1) * w + x); }
  for (let y = 0; y < h; y++) { push(y * w); push(y * w + w - 1); }
  while (sp) {
    const i = stack[--sp]; outside++;
    const y = (i / w) | 0, x = i - y * w;
    if (x > 0) push(i - 1); if (x < w - 1) push(i + 1);
    if (y > 0) push(i - w); if (y < h - 1) push(i + w);
  }
  return w * h - outside;
}
