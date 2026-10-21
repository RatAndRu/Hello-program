// Объём — поиск меток коврика на кадре (без ИИ: порог, связные области, четырёхугольники, чтение битов).
import { DICT } from './mat.js';

export function toGray(rgba, w, h, out) {
  const g = out || new Uint8Array(w * h);
  for (let i = 0, j = 0; j < w * h; i += 4, j++) g[j] = (rgba[i] * 77 + rgba[i + 1] * 150 + rgba[i + 2] * 29) >> 8;
  return g;
}

function bilinear(g, w, h, x, y) {
  if (x < 0 || y < 0 || x > w - 1.001 || y > h - 1.001) return -1;
  const x0 = x | 0, y0 = y | 0, fx = x - x0, fy = y - y0, i = y0 * w + x0;
  return (g[i] * (1 - fx) + g[i + 1] * fx) * (1 - fy) + (g[i + w] * (1 - fx) + g[i + w + 1] * fx) * fy;
}

function hom4(Q) { // квадрат [0,1]² → четырёхугольник Q (4 точки) — проективное отображение
  const [x0, y0] = Q[0], [x1, y1] = Q[1], [x2, y2] = Q[2], [x3, y3] = Q[3];
  const dx1 = x1 - x2, dx2 = x3 - x2, dy1 = y1 - y2, dy2 = y3 - y2, sx = x0 - x1 + x2 - x3, sy = y0 - y1 + y2 - y3;
  let g = 0, hh = 0;
  if (Math.abs(sx) > 1e-9 || Math.abs(sy) > 1e-9) { const d = dx1 * dy2 - dx2 * dy1; g = (sx * dy2 - dx2 * sy) / d; hh = (dx1 * sy - sx * dy1) / d; }
  const a = x1 - x0 + g * x1, b = x3 - x0 + hh * x3, c = x0, d = y1 - y0 + g * y1, e = y3 - y0 + hh * y3, f = y0;
  return (u, v) => { const z = g * u + hh * v + 1; return [(a * u + b * v + c) / z, (d * u + e * v + f) / z]; };
}

const scratch = { w: 0, h: 0 };
function bufs(w, h) {
  if (scratch.w !== w || scratch.h !== h) {
    scratch.w = w; scratch.h = h;
    scratch.ii = new Uint32Array((w + 1) * (h + 1));
    scratch.bin = new Uint8Array(w * h);
    scratch.lab = new Int32Array(w * h);
  }
  return scratch;
}

// Главная функция: g — яркость (Uint8Array), возвращает [{id, corners:[[x,y]×4 в порядке TL TR BR BL метки], err}]
export function detectMarkers(g, w, h, opt = {}) {
  const S = bufs(w, h), ii = S.ii, bin = S.bin, lab = S.lab;
  // 1) адаптивный порог по интегральному изображению
  const W1 = w + 1;
  for (let y = 0; y < h; y++) { let row = 0; for (let x = 0; x < w; x++) { row += g[y * w + x]; ii[(y + 1) * W1 + x + 1] = ii[y * W1 + x + 1] + row; } }
  const rad = opt.win || Math.max(7, Math.round(Math.min(w, h) / 28)), C = opt.C ?? 6;
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - rad), y1 = Math.min(h, y + rad + 1);
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - rad), x1 = Math.min(w, x + rad + 1);
      const s = ii[y1 * W1 + x1] - ii[y0 * W1 + x1] - ii[y1 * W1 + x0] + ii[y0 * W1 + x0];
      bin[y * w + x] = g[y * w + x] * (x1 - x0) * (y1 - y0) < (s - C * (x1 - x0) * (y1 - y0)) ? 1 : 0;
    }
  }
  // 2) связные области тёмного (8-связность, union-find)
  const parent = [0];
  const find = (a) => { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; };
  lab.fill(0);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x; if (!bin[i]) continue;
    let l = 0;
    const nb = [x > 0 ? lab[i - 1] : 0, y > 0 ? lab[i - w] : 0, y > 0 && x > 0 ? lab[i - w - 1] : 0, y > 0 && x < w - 1 ? lab[i - w + 1] : 0];
    for (const n of nb) if (n) { const r = find(n); if (!l) l = r; else if (r !== l) { const a = Math.min(l, r), b = Math.max(l, r); parent[b] = a; l = a; } }
    if (!l) { l = parent.length; parent.push(l); }
    lab[i] = l;
  }
  const nL = parent.length;
  const minX = new Int32Array(nL).fill(1e9), minY = new Int32Array(nL).fill(1e9), maxX = new Int32Array(nL).fill(-1), maxY = new Int32Array(nL).fill(-1), cnt = new Int32Array(nL);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x; if (!lab[i]) continue;
    const l = find(lab[i]); lab[i] = l; cnt[l]++;
    if (x < minX[l]) minX[l] = x; if (x > maxX[l]) maxX[l] = x; if (y < minY[l]) minY[l] = y; if (y > maxY[l]) maxY[l] = y;
  }
  const minSide = opt.minSide || 10, maxSide = Math.max(w, h) / 2.2;
  const out = [];
  for (let l = 1; l < nL; l++) {
    if (!cnt[l] || parent[l] !== l) continue;
    const bw = maxX[l] - minX[l] + 1, bh = maxY[l] - minY[l] + 1;
    if (bw < minSide || bh < minSide || bw > maxSide || bh > maxSide || cnt[l] < minSide * 3) continue;
    if (minX[l] < 2 || minY[l] < 2 || maxX[l] > w - 3 || maxY[l] > h - 3) continue; // обрезано краем кадра
    // граница области → выпуклая оболочка
    const pts = [];
    for (let y = minY[l]; y <= maxY[l]; y++) {
      let first = -1, last = -1;
      for (let x = minX[l]; x <= maxX[l]; x++) if (lab[y * w + x] === l) { if (first < 0) first = x; last = x; }
      if (first >= 0) { pts.push([first, y]); if (last !== first) pts.push([last + 1, y]); }
    }
    if (pts.length < 8) continue;
    const hull = convexHull(pts);
    if (hull.length < 4) continue;
    const quad = quadFromHull(hull);
    if (!quad) continue;
    const qa = polyArea(quad), ha = polyArea(hull);
    if (qa < ha * 0.88 || qa < minSide * minSide * 0.6) continue;
    // заполненность: у метки рамка чёрная, внутри примерно половина — плотность 0.35…0.95
    const fill = cnt[l] / qa;
    if (fill < 0.3 || fill > 0.97) continue;
    if (!convexQuad(quad)) continue;
    let q = quad;
    if (polyArea(q, true) < 0) q = [q[0], q[3], q[2], q[1]]; // по часовой на экране
    const ref = refineQuad(g, w, h, q);
    const dec = decode(g, w, h, ref || q);
    if (!dec) continue;
    const k = dec.rot;
    const Q = ref || q;
    out.push({ id: dec.id, corners: [Q[k % 4], Q[(k + 1) % 4], Q[(k + 2) % 4], Q[(k + 3) % 4]], err: dec.err, refined: !!ref });
  }
  // одна и та же метка дважды — оставляем с меньшей ошибкой
  const best = new Map();
  for (const m of out) if (!best.has(m.id) || best.get(m.id).err > m.err) best.set(m.id, m);
  return [...best.values()];
}

function convexHull(P) {
  P.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const p of P) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
  for (let i = P.length - 1; i >= 0; i--) { const p = P[i]; while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
  up.pop(); lo.pop();
  return lo.concat(up);
}
function polyArea(P, signed) { let s = 0; for (let i = 0; i < P.length; i++) { const a = P[i], b = P[(i + 1) % P.length]; s += a[0] * b[1] - b[0] * a[1]; } return signed ? s / 2 : Math.abs(s / 2); }
function convexQuad(q) { let sg = 0; for (let i = 0; i < 4; i++) { const a = q[i], b = q[(i + 1) % 4], c = q[(i + 2) % 4]; const cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]); const s = Math.sign(cr); if (!s) return false; if (!sg) sg = s; else if (s !== sg) return false; } return true; }
function quadFromHull(H) {
  // самая длинная диагональ + две самые далёкие от неё точки
  let bi = 0, bj = 0, bd = -1;
  for (let i = 0; i < H.length; i++) for (let j = i + 1; j < H.length; j++) { const d = (H[i][0] - H[j][0]) ** 2 + (H[i][1] - H[j][1]) ** 2; if (d > bd) { bd = d; bi = i; bj = j; } }
  const A = H[bi], C = H[bj];
  let bP = null, bN = null, dP = 0, dN = 0;
  for (const p of H) { const cr = (C[0] - A[0]) * (p[1] - A[1]) - (C[1] - A[1]) * (p[0] - A[0]); if (cr > dP) { dP = cr; bP = p; } if (cr < dN) { dN = cr; bN = p; } }
  if (!bP || !bN) return null;
  // уточняем: каждую вершину — самая далёкая точка оболочки от диагонали соседей (2 прохода)
  let q = [A, bP, C, bN];
  for (let it = 0; it < 2; it++) {
    for (let k = 0; k < 4; k++) {
      const a = q[(k + 3) % 4], b = q[(k + 1) % 4];
      let best = q[k], bd2 = -1;
      const sgn = Math.sign((b[0] - a[0]) * (q[k][1] - a[1]) - (b[1] - a[1]) * (q[k][0] - a[0]));
      for (const p of H) { const cr = sgn * ((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])); if (cr > bd2) { bd2 = cr; best = p; } }
      q[k] = best;
    }
  }
  return q;
}
// уточнение углов: прямые по точкам максимального перепада яркости вдоль каждой стороны
function refineQuad(g, w, h, q) {
  const lines = [];
  for (let k = 0; k < 4; k++) {
    const a = q[k], b = q[(k + 1) % 4], dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy);
    if (L < 6) return null;
    const nx = -dy / L, ny = dx / L, pts = [];
    const N = Math.min(14, Math.max(6, Math.round(L / 4)));
    for (let s = 0; s < N; s++) {
      const t = 0.12 + 0.76 * s / (N - 1), px = a[0] + dx * t, py = a[1] + dy * t;
      let best = 0, bo = 0;
      for (let o = -3; o <= 3; o += 0.25) {
        const v1 = bilinear(g, w, h, px + nx * (o + 0.5), py + ny * (o + 0.5)), v0 = bilinear(g, w, h, px + nx * (o - 0.5), py + ny * (o - 0.5));
        if (v1 < 0 || v0 < 0) continue;
        const gr = Math.abs(v1 - v0);
        if (gr > best) { best = gr; bo = o; }
      }
      if (best > 8) pts.push([px + nx * bo, py + ny * bo]);
    }
    if (pts.length < 4) return null;
    // прямая через точки (PCA)
    let mx = 0, my = 0; for (const p of pts) { mx += p[0]; my += p[1]; } mx /= pts.length; my /= pts.length;
    let sxx = 0, sxy = 0, syy = 0; for (const p of pts) { const ux = p[0] - mx, uy = p[1] - my; sxx += ux * ux; sxy += ux * uy; syy += uy * uy; }
    const ang = 0.5 * Math.atan2(2 * sxy, sxx - syy);
    lines.push({ p: [mx, my], d: [Math.cos(ang), Math.sin(ang)] });
  }
  const out = [];
  for (let k = 0; k < 4; k++) {
    const L1 = lines[(k + 3) % 4], L2 = lines[k];
    const den = L1.d[0] * L2.d[1] - L1.d[1] * L2.d[0];
    if (Math.abs(den) < 1e-6) return null;
    const t = ((L2.p[0] - L1.p[0]) * L2.d[1] - (L2.p[1] - L1.p[1]) * L2.d[0]) / den;
    const c = [L1.p[0] + L1.d[0] * t, L1.p[1] + L1.d[1] * t];
    if (Math.hypot(c[0] - q[k][0], c[1] - q[k][1]) > 4) return null;
    out.push(c);
  }
  return out;
}
const pop = (x) => { let n = 0; while (x) { n += x & 1; x >>>= 1; } return n; };
function decode(g, w, h, q) {
  const H = hom4(q);
  const samp = (cx, cy) => { // среднее по клетке (3×3 точки)
    let s = 0, n = 0;
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) { const [x, y] = H((cx + 0.5 + a * 0.22) / 6, (cy + 0.5 + b * 0.22) / 6); const v = bilinear(g, w, h, x, y); if (v >= 0) { s += v; n++; } }
    return n ? s / n : -1;
  };
  const cells = new Float32Array(36);
  for (let r = 0; r < 6; r++) for (let c = 0; c < 6; c++) { const v = samp(c, r); if (v < 0) return null; cells[r * 6 + c] = v; }
  let bsum = 0, bn = 0;
  for (let r = 0; r < 6; r++) for (let c = 0; c < 6; c++) if (r === 0 || c === 0 || r === 5 || c === 5) { bsum += cells[r * 6 + c]; bn++; }
  // белое поле снаружи рамки
  let wsum = 0, wn = 0;
  for (let i = -1; i <= 6; i++) for (const [c, r] of [[i, -1], [i, 6], [-1, i], [6, i]]) { const v = samp(c, r); if (v >= 0) { wsum += v; wn++; } }
  if (!wn) return null;
  const black = bsum / bn, white = wsum / wn;
  if (white - black < 25) return null;
  const thr = (black + white) / 2;
  let bad = 0;
  for (let r = 0; r < 6; r++) for (let c = 0; c < 6; c++) if ((r === 0 || c === 0 || r === 5 || c === 5) && cells[r * 6 + c] > thr) bad++;
  if (bad > 2) return null;
  let bits = 0;
  for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) if (cells[(r + 1) * 6 + c + 1] < thr) bits |= 1 << (r * 4 + c);
  let best = null;
  for (let id = 0; id < DICT.length; id++) for (let k = 0; k < 4; k++) {
    const d = pop(bits ^ DICT[id].rot[k]);
    if (!best || d < best.err) best = { id, rot: k, err: d };
  }
  if (!best || best.err > 1 || bad + best.err > 2) return null;
  return best;
}
