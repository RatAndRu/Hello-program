// Поиск листа бумаги в кадре без ИИ — классическое компьютерное зрение:
// 1) уменьшаем кадр и считаем яркость; 2) порог Оцу отделяет светлый лист от фона;
// 3) берём самую большую светлую область; 4) выпуклая оболочка → 4 угла;
// 5) каждая сторона ищется отдельно (RANSAC по краевым точкам): рука на краю — это
//    «выбросы», прямая находится по открытой части стороны; углы — пересечения сторон.
// Для каждого угла сообщаем, виден ли он. Закрытый угол достраивает app.js
// (по прошлому положению листа или по трём другим углам с учётом перспективы).

import { convexHull, polygonArea, isConvexQuad, dist, sub, cross } from './geom.js';

const ANALYSIS_LONG_SIDE = 320;

export class PaperTracker {
  constructor(opts = {}) {
    this.longSide = opts.longSide || ANALYSIS_LONG_SIDE; // для полноразмерного фото — точнее
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
    this.lastReason = '';
  }

  // source — <video> или canvas; vw/vh — его размеры в пикселях.
  // prior — прошлые углы (в пикселях кадра): помогает, когда рука закрывает угол или край.
  detect(source, vw, vh, prior = null) {
    if (!vw || !vh) return this.fail('нет кадра');
    const s = Math.min(1, this.longSide / Math.max(vw, vh));
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

    // Граница: крайние пиксели по строкам и столбцам (для первой оценки) и все краевые пиксели (для подгонки сторон).
    const rowMin = new Int32Array(h).fill(w), rowMax = new Int32Array(h).fill(-1);
    const colMin = new Int32Array(w).fill(h), colMax = new Int32Array(w).fill(-1);
    const inC = new Uint8Array(n);
    for (let k = 0; k < pixels.length; k++) inC[pixels[k]] = 1;
    let borderTouch = 0;
    const bpts = [];
    for (let k = 0; k < pixels.length; k++) {
      const idx = pixels[k], y = (idx / w) | 0, x = idx - y * w;
      if (x < rowMin[y]) rowMin[y] = x; if (x > rowMax[y]) rowMax[y] = x;
      if (y < colMin[x]) colMin[x] = y; if (y > colMax[x]) colMax[x] = y;
      const edge = x === 0 || y === 0 || x === w - 1 || y === h - 1;
      if (edge) borderTouch++;
      if (!edge && (!inC[idx - 1] || !inC[idx + 1] || !inC[idx - w] || !inC[idx + w])) bpts.push({ x: x + 0.5, y: y + 0.5 });
    }
    if (borderTouch > (w + h) * 0.12) return this.fail('лист не целиком в кадре');

    // Два кандидата: от прошлого положения листа (если есть) и «с нуля» — от оболочки области.
    // Каждый проверяем по маске бумаги и берём лучший; прошлому положению — небольшой бонус
    // (стабильность), но если лист переложили или наклонили камеру — победит поиск с нуля.
    const cands = [];
    if (prior) {
      const init = prior.map(p => ({ x: p.x * s, y: p.y * s }));
      if (isConvexQuad(init)) { const f = fitQuadRobust(init, bpts, 0.07); f.init = init; f.fromPrior = true; cands.push(f); }
    }
    if (!cands.length || cands[0].nVis < 4) {
      const edgePts = [];
      for (let y = 0; y < h; y++) if (rowMax[y] >= 0) { edgePts.push({ x: rowMin[y] + 0.5, y: y + 0.5 }); edgePts.push({ x: rowMax[y] + 0.5, y: y + 0.5 }); }
      for (let x = 0; x < w; x++) if (colMax[x] >= 0) { edgePts.push({ x: x + 0.5, y: colMin[x] + 0.5 }); edgePts.push({ x: x + 0.5, y: colMax[x] + 0.5 }); }
      const hull = convexHull(edgePts);
      const quad0 = hull.length >= 4 ? maxAreaQuad(hull) : null;
      if (quad0) { const f = fitQuadRobust(quad0, bpts, 0.06); f.init = quad0; cands.push(f); }
    }
    let filled = -1, best = null, bestScore = -Infinity, reason = 'лист не найден';
    for (const fit of cands) {
      if (fit.okSides < 2 || fit.nComputed < 2) { reason = 'лист закрыт — не видно краёв'; continue; }
      if (!prior && fit.nComputed < 3) { reason = 'лист закрыт рукой'; continue; }
      const quad = fit.corners;
      if (!isConvexQuad(quad)) { reason = 'форма не похожа на лист'; continue; }
      const qa = Math.abs(polygonArea(quad));
      if (qa < n * 0.03) { reason = 'лист слишком маленький или не виден'; continue; }
      // Закрашенные места рисунка — «дырки» в маске бумаги; считаем их частью листа.
      if (filled < 0) filled = filledArea(pixels, w, h);
      // Рука может закрыть часть листа, но бумаги в найденном четырёхугольнике должно быть много,
      // и вне его — мало (иначе мы нашли не те края).
      let outside = 0;
      for (let k = 0; k < pixels.length; k += 2) { const idx = pixels[k], y = (idx / w) | 0, x = idx - y * w; if (!insideQuad(quad, x + 0.5, y + 0.5, 2.5)) outside += 2; }
      const cover = (filled - outside) / qa;
      const outLim = fit.nComputed === 4 ? 0.12 : 0.2;
      if (cover < 0.5) { reason = 'форма не похожа на лист (рука или тень?)'; continue; }
      if (outside > qa * outLim) { reason = 'форма не похожа на лист'; continue; }
      const score = fit.nComputed * 4 + fit.nVis * 2 + fit.okSides - (outside / qa) * 20 + (fit.fromPrior ? 1.5 : 0);
      if (score > bestScore) { bestScore = score; best = fit; best.quality = Math.min(1, cover); }
    }
    if (!best) return this.fail(reason);
    const fit = best, quad = fit.corners;
    this.lastQuality = fit.quality;

    this.lastReason = '';
    return {
      corners: quad.map((p, i) => ({ x: p.x / s, y: p.y / s, vis: fit.visible[i], ok: fit.computed[i] })),
      visible: fit.visible.slice(), computed: fit.computed.slice(),
      quality: this.lastQuality || 0.8,
    };
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

function insideQuad(q, x, y, tol) {
  const sg = polygonArea(q) >= 0 ? 1 : -1;
  for (let i = 0; i < 4; i++) {
    const a = q[i], b = q[(i + 1) % 4];
    const c = sg * ((b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x));
    const L = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    if (c / L < -tol) return false; // порядок по часовой в координатах экрана (y вниз)
  }
  return true;
}

// Устойчивая подгонка 4 сторон: для каждой стороны RANSAC по краевым точкам рядом с ней.
// Рука на краю листа даёт «выбросы» — они отбрасываются, прямая находится по открытой части.
// Угол = пересечение соседних сторон; угол «виден», если обе стороны подходят к нему вплотную.
function fitQuadRobust(init, pts, bandK) {
  // приводим к обходу по часовой (на экране), чтобы insideQuad работал
  let q = init;
  if (polygonArea(q) < 0) q = [q[0], q[3], q[2], q[1]];
  const flipped = q !== init;
  const sides = [];
  for (let k = 0; k < 4; k++) sides.push(fitSideRobust(q[k], q[(k + 1) % 4], pts, bandK));
  const corners = [], visible = [], computed = [];
  for (let k = 0; k < 4; k++) {
    const A = sides[(k + 3) % 4], B = sides[k];
    let c = null;
    if (A && B) {
      const den = cross(A.d, B.d);
      if (Math.abs(den) > 0.15) { // стороны не почти параллельны
        const t = cross(sub(B.p, A.p), B.d) / den;
        c = { x: A.p.x + A.d.x * t, y: A.p.y + A.d.y * t };
        if (dist(c, q[k]) > Math.max(12, dist(q[k], q[(k + 2) % 4]) * 0.25)) c = null; // улетело — не верим
      }
    }
    computed.push(!!c);
    corners.push(c || { x: q[k].x, y: q[k].y });
    visible.push(!!c && A.endCov >= 0.45 && B.startCov >= 0.45);
  }
  let res = { corners, visible, computed, sides };
  if (flipped) {
    const m = [0, 3, 2, 1];
    res = { corners: m.map(i => corners[i]), visible: m.map(i => visible[i]), computed: m.map(i => computed[i]), sides };
  }
  res.okSides = sides.filter(Boolean).length;
  res.nVis = res.visible.filter(Boolean).length;
  res.nComputed = res.computed.filter(Boolean).length;
  return res;
}

function fitSideRobust(a, b, pts, bandK) {
  const ab = sub(b, a), L = Math.hypot(ab.x, ab.y);
  if (L < 8) return null;
  const ux = ab.x / L, uy = ab.y / L;
  const band = Math.max(4, L * bandK);
  // Обход по часовой: снаружи листа знаковое расстояние s > 0.
  // Наружу полосу расширяем до самой дальней краевой точки в пролёте стороны:
  // если угол срезан рукой, начальная сторона может пройти по хорде между ладонями,
  // а настоящий край листа виден дальше — его нельзя потерять.
  let outBand = band;
  const span = [];
  for (const p of pts) {
    const dx = p.x - a.x, dy = p.y - a.y;
    const t = (dx * ux + dy * uy) / L, sd = dx * uy - dy * ux;
    if (t < 0.08 || t > 0.92 || sd < -L * 0.5) continue;
    span.push(p);
    if (sd > outBand) outBand = sd;
  }
  outBand = Math.min(outBand + 3, Math.max(band, L * 0.35));
  const cand = [];
  for (const p of pts) {
    const dx = p.x - a.x, dy = p.y - a.y;
    const t = (dx * ux + dy * uy) / L, sd = dx * uy - dy * ux;
    if (t < -0.12 || t > 1.12) continue;
    if (sd < -band || sd > outBand) continue;
    cand.push(p);
  }
  if (cand.length < 10) return null;
  // RANSAC (детерминированный генератор — без «дрожания» между кадрами).
  // Край листа — «опорная» прямая: снаружи от него листа нет. Прямая, за которой
  // остаётся кусок листа (например, хорда по краям ладоней), штрафуется.
  let seed = 12345;
  const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  let best = null, bestN = 0;
  const thr = 1.3;
  for (let it = 0; it < 90; it++) {
    const p = cand[Math.floor(rnd() * cand.length)], q2 = cand[Math.floor(rnd() * cand.length)];
    const dx = q2.x - p.x, dy = q2.y - p.y, dl = Math.hypot(dx, dy);
    if (dl < L * 0.15) continue;
    let nx = -dy / dl, ny = dx / dl;
    if (Math.abs(nx * ux + ny * uy) > 0.35) continue; // направление сильно отличается от стороны
    if (nx * uy - ny * ux < 0) { nx = -nx; ny = -ny; } // нормаль — наружу
    let c = 0, out = 0;
    for (const r of cand) if (Math.abs((r.x - p.x) * nx + (r.y - p.y) * ny) < thr) c++;
    for (const r of span) if ((r.x - p.x) * nx + (r.y - p.y) * ny > 2.5) out++;
    const sc = c - 2 * out;
    if (sc > bestN) { bestN = sc; best = { p, nx, ny }; }
  }
  if (!best || bestN < 8) return null;
  let line = lsq(cand.filter(r => Math.abs((r.x - best.p.x) * best.nx + (r.y - best.p.y) * best.ny) < thr));
  for (let rep = 0; rep < 2 && line; rep++) {
    const nx = -line.d.y, ny = line.d.x;
    const inl = cand.filter(r => Math.abs((r.x - line.p.x) * nx + (r.y - line.p.y) * ny) < 1.1);
    if (inl.length < 8) break;
    line = lsq(inl);
  }
  if (!line) return null;
  // покрытие стороны найденными точками (по 40 корзинам) и у каждого конца
  const nx = -line.d.y, ny = line.d.x;
  const bins = new Uint8Array(40);
  let n = 0;
  for (const r of cand) {
    if (Math.abs((r.x - line.p.x) * nx + (r.y - line.p.y) * ny) > 1.3) continue;
    const t = ((r.x - a.x) * ux + (r.y - a.y) * uy) / L;
    if (t < 0 || t >= 1) continue;
    bins[Math.min(39, Math.floor(t * 40))] = 1; n++;
  }
  let cov = 0, s0 = 0, s1 = 0;
  for (let i = 0; i < 40; i++) { cov += bins[i]; if (i < 6) s0 += bins[i]; if (i >= 34) s1 += bins[i]; }
  cov /= 40;
  if (cov < 0.2 || n < 10) return null;
  if (line.d.x * ux + line.d.y * uy < 0) line.d = { x: -line.d.x, y: -line.d.y };
  return { p: line.p, d: line.d, cov, startCov: s0 / 6, endCov: s1 / 6, n };
}

function lsq(sel) {
  if (sel.length < 2) return null;
  let mx = 0, my = 0;
  for (const p of sel) { mx += p.x; my += p.y; }
  mx /= sel.length; my /= sel.length;
  let xx = 0, xy = 0, yy = 0;
  for (const p of sel) { const dx = p.x - mx, dy = p.y - my; xx += dx * dx; xy += dx * dy; yy += dy * dy; }
  const ang = 0.5 * Math.atan2(2 * xy, xx - yy);
  return { p: { x: mx, y: my }, d: { x: Math.cos(ang), y: Math.sin(ang) } };
}
