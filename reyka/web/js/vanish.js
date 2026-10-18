// Автоперспектива по фото — без ИИ:
//  1) детектор границ Кэнни;
//  2) «выращивание» отрезков: соседние пиксели границы с похожим направлением
//     объединяются, и через них проводится прямая (упрощённый LSD);
//  3) RANSAC: ищем точку, к которой сходится больше всего отрезков, — это точка схода.
//     Убираем её отрезки и ищем следующую (до 3 штук).

import { grayOf, cannyCore } from './tracing.js';

const MAX_SIDE = 900;

export function detectSegments(srcCanvas) {
  const k = Math.min(1, MAX_SIDE / Math.max(srcCanvas.width, srcCanvas.height));
  let src = srcCanvas;
  if (k < 1) {
    src = document.createElement('canvas');
    src.width = Math.round(srcCanvas.width * k); src.height = Math.round(srcCanvas.height * k);
    src.getContext('2d').drawImage(srcCanvas, 0, 0, src.width, src.height);
  }
  const { g, w, h } = grayOf(src);
  const { edge, ang } = cannyCore(g, w, h, { detail: 0.55, smooth: 1.2 });
  const used = new Uint8Array(w * h);
  const segs = [];
  const minLen = Math.max(18, Math.max(w, h) * 0.035);
  const tol = 22.5 * Math.PI / 180;
  const queue = new Int32Array(w * h);
  for (let s = 0; s < w * h; s++) {
    if (!edge[s] || used[s]) continue;
    // средний угол ведём через удвоенный угол (направление без знака)
    let cx = Math.cos(2 * ang[s]), cy = Math.sin(2 * ang[s]);
    let qh = 0, qt = 0;
    queue[qt++] = s; used[s] = 1;
    const pts = [];
    while (qh < qt) {
      const i = queue[qh++], y = (i / w) | 0, x = i - y * w;
      pts.push(x, y);
      const ra = Math.atan2(cy, cx) / 2;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        const xx = x + dx, yy = y + dy;
        if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue;
        const j = yy * w + xx;
        if (!edge[j] || used[j]) continue;
        let d = Math.abs(ang[j] - ra) % Math.PI; if (d > Math.PI / 2) d = Math.PI - d;
        if (d > tol) continue;
        used[j] = 1; queue[qt++] = j;
        cx += Math.cos(2 * ang[j]); cy += Math.sin(2 * ang[j]);
      }
    }
    const n = pts.length / 2;
    if (n < minLen * 0.8) continue;
    let mx = 0, my = 0;
    for (let i = 0; i < pts.length; i += 2) { mx += pts[i]; my += pts[i + 1]; }
    mx /= n; my /= n;
    let xx = 0, xy = 0, yy = 0;
    for (let i = 0; i < pts.length; i += 2) { const dx = pts[i] - mx, dy = pts[i + 1] - my; xx += dx * dx; xy += dx * dy; yy += dy * dy; }
    xx /= n; xy /= n; yy /= n;
    const tr = xx + yy, det = xx * yy - xy * xy;
    const l1 = tr / 2 + Math.sqrt(Math.max(0, tr * tr / 4 - det)), l2 = tr / 2 - Math.sqrt(Math.max(0, tr * tr / 4 - det));
    const a = 0.5 * Math.atan2(2 * xy, xx - yy);
    const ux = Math.cos(a), uy = Math.sin(a);
    let tmin = Infinity, tmax = -Infinity;
    for (let i = 0; i < pts.length; i += 2) { const t = (pts[i] - mx) * ux + (pts[i + 1] - my) * uy; if (t < tmin) tmin = t; if (t > tmax) tmax = t; }
    const len = tmax - tmin;
    const width = Math.sqrt(Math.max(0, l2)) * 3.46;
    if (len < minLen || width > 2.6 || len / Math.max(width, 0.5) < 10) continue;
    segs.push({ x1: (mx + ux * tmin) / k, y1: (my + uy * tmin) / k, x2: (mx + ux * tmax) / k, y2: (my + uy * tmax) / k, len: len / k });
    void l1;
  }
  return segs;
}

// Поиск до 3 точек схода. Возвращает [{x, y, inf, dir, inliers:[idx]}] в пикселях картинки.
export function findVanishingPoints(segs, W, H, maxVP = 3) {
  const s = Math.max(W, H) / 2, ox = W / 2, oy = H / 2;
  const L = segs.map(sg => {
    const a = [(sg.x1 - ox) / s, (sg.y1 - oy) / s, 1], b = [(sg.x2 - ox) / s, (sg.y2 - oy) / s, 1];
    const l = cross(a, b), nl = Math.hypot(l[0], l[1]) || 1;
    const dx = b[0] - a[0], dy = b[1] - a[1], dl = Math.hypot(dx, dy) || 1;
    return { l: [l[0] / nl, l[1] / nl, l[2] / nl], mx: (a[0] + b[0]) / 2, my: (a[1] + b[1]) / 2, ux: dx / dl, uy: dy / dl, w: sg.len };
  });
  const total = L.reduce((t, x) => t + x.w, 0);
  const remaining = new Set(L.map((_, i) => i));
  const out = [];
  const thr = 2.2 * Math.PI / 180;
  const err = (seg, v) => {
    let dx, dy;
    if (Math.abs(v[2]) < 1e-9) { dx = v[0]; dy = v[1]; }
    else { dx = v[0] / v[2] - seg.mx; dy = v[1] / v[2] - seg.my; }
    const dl = Math.hypot(dx, dy);
    if (dl < 1e-9) return 0;
    const c = Math.abs(seg.ux * dx + seg.uy * dy) / dl;
    return Math.acos(Math.min(1, c));
  };
  for (let k = 0; k < maxVP; k++) {
    const idx = [...remaining];
    if (idx.length < 3) break;
    const cum = []; let acc = 0;
    for (const i of idx) { acc += L[i].w; cum.push(acc); }
    const pick = () => { const r = Math.random() * acc; let lo = 0, hi = cum.length - 1; while (lo < hi) { const m = (lo + hi) >> 1; if (cum[m] < r) lo = m + 1; else hi = m; } return idx[lo]; };
    let best = null, bestScore = 0;
    for (let it = 0; it < 700; it++) {
      const i = pick(), j = pick();
      if (i === j) continue;
      // не берём почти совпадающие отрезки
      if (Math.abs(L[i].ux * L[j].uy - L[i].uy * L[j].ux) < 0.02 && Math.abs(L[i].l[2] - L[j].l[2]) < 0.01) continue;
      const v = cross(L[i].l, L[j].l);
      const nv = Math.hypot(...v); if (nv < 1e-12) continue;
      const vn = v.map(x => x / nv);
      let score = 0;
      for (const q of idx) if (err(L[q], vn) < thr) score += L[q].w;
      if (score > bestScore) { bestScore = score; best = vn; }
    }
    if (!best || bestScore < total * 0.07) break;
    let inl = idx.filter(q => err(L[q], best) < thr);
    if (inl.length < 3) break;
    // уточнение: наименьший собственный вектор Σ w·l·lᵀ
    const v = refine(inl.map(q => L[q]));
    if (v) { const inl2 = idx.filter(q => err(L[q], v) < thr); if (inl2.length >= inl.length * 0.8) { best = v; inl = inl2; } }
    inl.forEach(q => remaining.delete(q));
    const inf = Math.abs(best[2]) < 1e-6 || Math.hypot(best[0] / best[2], best[1] / best[2]) > 60;
    const vertness = inl.reduce((t, q) => t + Math.abs(L[q].uy) * L[q].w, 0) / inl.reduce((t, q) => t + L[q].w, 0);
    let x, y, dir = null;
    if (inf) {
      // направление: среднее направление отрезков
      let dx = 0, dy = 0;
      for (const q of inl) { const sg = L[q], sgn = (sg.ux * best[0] + sg.uy * best[1]) >= 0 ? 1 : -1; dx += sg.ux * sgn * sg.w; dy += sg.uy * sgn * sg.w; }
      const dl = Math.hypot(dx, dy) || 1; dir = { x: dx / dl, y: dy / dl };
      x = ox + dir.x * s * 80; y = oy + dir.y * s * 80;
    } else { x = ox + best[0] / best[2] * s; y = oy + best[1] / best[2] * s; }
    out.push({ x, y, inf, dir, vertical: vertness > 0.8, support: bestScore / total, inliers: inl });
  }
  return out;
}

function refine(lines) {
  const M = [0, 0, 0, 0, 0, 0, 0, 0, 0];
  for (const s of lines) { const l = s.l; for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) M[r * 3 + c] += s.w * l[r] * l[c]; }
  return smallestEigvec(M);
}

function smallestEigvec(A) {
  // Якоби для симметричной 3×3
  const a = [[A[0], A[1], A[2]], [A[3], A[4], A[5]], [A[6], A[7], A[8]]];
  const V = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  for (let sweep = 0; sweep < 30; sweep++) {
    let off = 0;
    for (let p = 0; p < 3; p++) for (let q = p + 1; q < 3; q++) off += a[p][q] ** 2;
    if (off < 1e-18) break;
    for (let p = 0; p < 3; p++) for (let q = p + 1; q < 3; q++) {
      if (Math.abs(a[p][q]) < 1e-20) continue;
      const th = (a[q][q] - a[p][p]) / (2 * a[p][q]);
      const t = Math.sign(th || 1) / (Math.abs(th) + Math.sqrt(th * th + 1));
      const c = 1 / Math.sqrt(t * t + 1), s = t * c;
      for (let k = 0; k < 3; k++) { const akp = a[k][p], akq = a[k][q]; a[k][p] = c * akp - s * akq; a[k][q] = s * akp + c * akq; }
      for (let k = 0; k < 3; k++) { const apk = a[p][k], aqk = a[q][k]; a[p][k] = c * apk - s * aqk; a[q][k] = s * apk + c * aqk; }
      for (let k = 0; k < 3; k++) { const vkp = V[k][p], vkq = V[k][q]; V[k][p] = c * vkp - s * vkq; V[k][q] = s * vkp + c * vkq; }
    }
  }
  let m = 0; for (let i = 1; i < 3; i++) if (a[i][i] < a[m][m]) m = i;
  const v = [V[0][m], V[1][m], V[2][m]], n = Math.hypot(...v);
  return n ? v.map(x => x / n) : null;
}

function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
