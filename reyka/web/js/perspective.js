// Перспектива камеры — без ИИ, чистая проективная геометрия.
//  • estimateRect: по 4 углам листа в кадре оценивает фокусное расстояние камеры
//    и НАСТОЯЩИЕ пропорции листа (метод Zhang & He, «whiteboard scanning»).
//    Нужно, чтобы под углом 45° книжный A4 не спутать с альбомным.
//  • cameraTilt: угол наклона камеры относительно листа (0° — ровно сверху).
//  • manualCorners: углы листа по заданному вручную наклону камеры.

import { mul, dist } from './geom.js';

const cross3 = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// Типичная камера телефона: ~65–70° по длинной стороне.
export const assumedFocal = (vw, vh) => 0.78 * Math.max(vw, vh);

// corners: [ЛВ, ПВ, ПН, ЛН] (по кругу). Возвращает ratio = |c0c1| / |c0c3| и f (или null).
export function estimateRect(c, vw, vh) {
  const u0 = vw / 2, v0 = vh / 2;
  const m = (p) => [p.x - u0, p.y - v0, 1];
  const m1 = m(c[0]), m2 = m(c[1]), m3 = m(c[3]), m4 = m(c[2]);
  const k2 = dot3(cross3(m1, m4), m3) / dot3(cross3(m2, m4), m3);
  const k3 = dot3(cross3(m1, m4), m2) / dot3(cross3(m3, m4), m2);
  const n2 = [k2 * m2[0] - m1[0], k2 * m2[1] - m1[1], k2 * m2[2] - m1[2]];
  const n3 = [k3 * m3[0] - m1[0], k3 * m3[1] - m1[1], k3 * m3[2] - m1[2]];
  const affine = (dist(c[0], c[1]) + dist(c[3], c[2])) / (dist(c[0], c[3]) + dist(c[1], c[2]));
  const den = n2[2] * n3[2];
  const maxDim = Math.max(vw, vh);
  if (Math.abs(den) > 1e-9) {
    const f2 = -(n2[0] * n3[0] + n2[1] * n3[1]) / den;
    if (isFinite(f2) && f2 > (0.35 * maxDim) ** 2 && f2 < (3.5 * maxDim) ** 2) {
      const a = Math.sqrt((n2[0] ** 2 + n2[1] ** 2) / f2 + n2[2] ** 2);
      const b = Math.sqrt((n3[0] ** 2 + n3[1] ** 2) / f2 + n3[2] ** 2);
      if (a > 0 && b > 0) return { ratio: a / b, f: Math.sqrt(f2), affine };
    }
  }
  // Вырожденный случай (стороны листа параллельны краям кадра): фокус не вычислить,
  // берём типичный для телефона — пропорции всё равно получаются близкими к правде.
  const fa = assumedFocal(vw, vh), f2a = fa * fa;
  const a = Math.sqrt((n2[0] ** 2 + n2[1] ** 2) / f2a + n2[2] ** 2);
  const b = Math.sqrt((n3[0] ** 2 + n3[1] ** 2) / f2a + n3[2] ** 2);
  if (isFinite(a) && isFinite(b) && a > 0 && b > 0) return { ratio: a / b, f: null, affine };
  return { ratio: affine, f: null, affine };
}

// Наклон камеры (градусы) по гомографии «лист (мм) → кадр (px)» и фокусному f.
export function cameraTilt(H, f, vw, vh) {
  if (!H || !f) return null;
  const Kinv = [1 / f, 0, -vw / 2 / f, 0, 1 / f, -vh / 2 / f, 0, 0, 1];
  const B = mul(Kinv, H);
  const h1 = [B[0], B[3], B[6]], h2 = [B[1], B[4], B[7]];
  const n1 = Math.hypot(...h1), n2 = Math.hypot(...h2);
  if (!n1 || !n2) return null;
  const r1 = h1.map(v => v / n1), r2 = h2.map(v => v / n2);
  const r3 = cross3(r1, r2);
  const n3 = Math.hypot(...r3) || 1;
  return Math.acos(Math.min(1, Math.abs(r3[2] / n3))) * 180 / Math.PI;
}

// Углы листа (в экранных px) для камеры, наклонённой на tilt°.
//  pw, ph — размер листа в мм; f — фокус в экранных px; size — px на мм в центре;
//  yaw — поворот листа на столе (°); far — где дальний край: 0 верх, 90 право, 180 низ, 270 лево.
export function manualCorners({ pw, ph, f, size, tilt, yaw, far, cx, cy }) {
  const t = tilt * Math.PI / 180, ys = yaw * Math.PI / 180, fr = far * Math.PI / 180;
  const d = f / size;
  const pts = [[-pw / 2, -ph / 2], [pw / 2, -ph / 2], [pw / 2, ph / 2], [-pw / 2, ph / 2]];
  return pts.map(([X0, Y0]) => {
    const X = X0 * Math.cos(ys) - Y0 * Math.sin(ys), Y = X0 * Math.sin(ys) + Y0 * Math.cos(ys);
    const Z = d - Y * Math.sin(t);
    const x = f * X / Z, y = f * Y * Math.cos(t) / Z;
    return { x: cx + x * Math.cos(fr) - y * Math.sin(fr), y: cy + x * Math.sin(fr) + y * Math.cos(fr) };
  });
}

// Пропорция листа при заданном фокусе f.
export function ratioAtF(c, vw, vh, f) {
  const u0 = vw / 2, v0 = vh / 2;
  const m = (p) => [p.x - u0, p.y - v0, 1];
  const m1 = m(c[0]), m2 = m(c[1]), m3 = m(c[3]), m4 = m(c[2]);
  const k2 = dot3(cross3(m1, m4), m3) / dot3(cross3(m2, m4), m3);
  const k3 = dot3(cross3(m1, m4), m2) / dot3(cross3(m3, m4), m2);
  const n2 = [k2 * m2[0] - m1[0], k2 * m2[1] - m1[1], k2 * m2[2] - m1[2]];
  const n3 = [k3 * m3[0] - m1[0], k3 * m3[1] - m1[1], k3 * m3[2] - m1[2]];
  const a = Math.sqrt((n2[0] ** 2 + n2[1] ** 2) / (f * f) + n2[2] ** 2);
  const b = Math.sqrt((n3[0] ** 2 + n3[1] ** 2) / (f * f) + n3[2] ** 2);
  return a / b;
}

// Автокалибровка: формат листа известен → подбираем фокус, при котором пропорции совпадают.
// Небольшая «тяга» к типичному фокусу телефона спасает вырожденные положения.
export function fitFocal(c, vw, vh, target) {
  const fa = assumedFocal(vw, vh), maxDim = Math.max(vw, vh);
  let best = fa, bc = Infinity;
  for (let k = 0; k <= 80; k++) {
    const f = maxDim * 0.45 * Math.pow(2.5 / 0.45, k / 80);
    const r = ratioAtF(c, vw, vh, f);
    if (!isFinite(r) || r <= 0) continue;
    const cost = Math.abs(Math.log(r / target)) + 0.03 * Math.abs(Math.log(f / fa));
    if (cost < bc) { bc = cost; best = f; }
  }
  return { f: best, cost: bc };
}

// ---------- Достройка закрытого угла ----------

// По трём углам прямоугольника (A — между B и D) и известным пропорциям |AB|/|AD|
// восстанавливаем 4-й угол с честной перспективой: лучи камеры → точки в 3D,
// условия «угол 90°» и «пропорции сторон» → 4-й угол C = B + D − A → проекция.
// nPrior — ожидаемая нормаль плоскости листа в координатах камеры (из прошлых кадров или датчика);
// задача по трём углам допускает до 4 решений, нормаль выбирает правильное.
export function completeRectangle(A, B, D, ratio, f, vw, vh, nPrior = [0, 0, 1], hint = null) {
  const u0 = vw / 2, v0 = vh / 2;
  const ray = (p) => [(p.x - u0) / f, (p.y - v0) / f, 1];
  const a = ray(A), b = ray(B), d = ray(D);
  const aa = dot3(a, a), ab = dot3(a, b), ad = dot3(a, d), bd = dot3(b, d), bb = dot3(b, b), dd = dot3(d, d);
  // Глубина A = 1. Условие 90°: (sb·b − a)·(sd·d − a) = 0 → sd выражается через sb.
  const sdOf = (sb) => { const den = sb * bd - ad; return Math.abs(den) < 1e-12 ? NaN : (sb * ab - aa) / den; };
  // Условие пропорций: |AB|² − r²|AD|² = 0 — одно уравнение по sb.
  const g = (sb) => { const sd = sdOf(sb); if (!(sd > 0.05)) return NaN; return (sb * sb * bb - 2 * sb * ab + aa) - ratio * ratio * (sd * sd * dd - 2 * sd * ad + aa); };
  const roots = [];
  let prevS = null, prevG = NaN;
  for (let i = 0; i <= 400; i++) {
    const sb = 0.1 * Math.pow(100, i / 400), gv = g(sb);
    if (isFinite(gv) && isFinite(prevG) && Math.sign(gv) !== Math.sign(prevG)) {
      let lo = prevS, hi = sb, glo = prevG;
      for (let k = 0; k < 60; k++) { const m = (lo + hi) / 2, gm = g(m); if (!isFinite(gm)) break; if (Math.sign(gm) === Math.sign(glo)) { lo = m; glo = gm; } else hi = m; }
      const r = (lo + hi) / 2, sd = sdOf(r);
      if (sd > 0.05) roots.push([r, sd]);
    }
    prevS = sb; prevG = gv;
  }
  if (!roots.length) return { x: B.x + D.x - A.x, y: B.y + D.y - A.y, approx: true }; // параллелограмм
  // из нескольких решений берём то, где плоскость листа ближе к ожидаемой
  const normalOf = ([sb, sd]) => {
    const AB = [sb * b[0] - a[0], sb * b[1] - a[1], sb * b[2] - a[2]], AD = [sd * d[0] - a[0], sd * d[1] - a[1], sd * d[2] - a[2]];
    const n = cross3(AB, AD), l = Math.hypot(...n) || 1; return n.map(v => v / l);
  };
  const np = Math.hypot(...nPrior) || 1;
  const pointOf = ([sb, sd]) => { const C = [sb * b[0] + sd * d[0] - a[0], sb * b[1] + sd * d[1] - a[1], sb * b[2] + sd * d[2] - a[2]]; return C[2] > 1e-6 ? { x: u0 + f * C[0] / C[2], y: v0 + f * C[1] / C[2] } : null; };
  const score = (r) => {
    if (hint) { const q = pointOf(r); return q ? Math.hypot(q.x - hint.x, q.y - hint.y) : Infinity; }
    return -Math.abs(dot3(normalOf(r), nPrior) / np);
  };
  roots.sort((p, q) => score(p) - score(q));
  const [sb, sd] = roots[0];
  const C = [sb * b[0] + sd * d[0] - a[0], sb * b[1] + sd * d[1] - a[1], sb * b[2] + sd * d[2] - a[2]];
  if (C[2] <= 1e-6) return { x: B.x + D.x - A.x, y: B.y + D.y - A.y, approx: true };
  return { x: u0 + f * C[0] / C[2], y: v0 + f * C[1] / C[2], nRoots: roots.length, normal: normalOf(roots[0]) };
}

// Телефон в держателе неподвижен, значит лист может только сдвинуться/повернуться по столу:
// 3 параметра (угол, сдвиг x, y) в миллиметрах листа. Подгоняем их по видимым углам
// и предсказываем закрытые. Hprev — гомография «мм листа → кадр» для прошлого положения.
export function rigidPredict(Hprev, paperPts, obs, visIdx) {
  const cx = paperPts.reduce((s, p) => s + p.x, 0) / 4, cy = paperPts.reduce((s, p) => s + p.y, 0) / 4;
  const proj = (prm, P) => {
    const [th, tx, ty] = prm, c = Math.cos(th), s = Math.sin(th);
    const x = cx + (P.x - cx) * c - (P.y - cy) * s + tx, y = cy + (P.x - cx) * s + (P.y - cy) * c + ty;
    const w = Hprev[6] * x + Hprev[7] * y + Hprev[8];
    return { x: (Hprev[0] * x + Hprev[1] * y + Hprev[2]) / w, y: (Hprev[3] * x + Hprev[4] * y + Hprev[5]) / w };
  };
  const resid = (prm) => { const r = []; for (const i of visIdx) { const q = proj(prm, paperPts[i]); r.push(q.x - obs[i].x, q.y - obs[i].y); } return r; };
  let prm = [0, 0, 0];
  const nP = visIdx.length >= 2 ? 3 : 2; // по одному углу поворот не определить
  for (let it = 0; it < 15; it++) {
    const r0 = resid(prm);
    const J = [];
    for (let k = 0; k < nP; k++) { const e = k === 0 ? 1e-5 : 1e-3; const p2 = prm.slice(); p2[k] += e; const r1 = resid(p2); J.push(r1.map((v, i) => (v - r0[i]) / e)); }
    // нормальные уравнения (JᵀJ) Δ = −Jᵀ r
    const A = [], g = [];
    for (let i = 0; i < nP; i++) { A.push([]); g.push(-J[i].reduce((s, v, k) => s + v * r0[k], 0)); for (let j = 0; j < nP; j++) A[i].push(J[i].reduce((s, v, k) => s + v * J[j][k], 0) + (i === j ? 1e-9 : 0)); }
    const dlt = solveSmall(A, g);
    if (!dlt) break;
    for (let k = 0; k < nP; k++) prm[k] += dlt[k];
    if (Math.hypot(...dlt) < 1e-7) break;
  }
  const r = resid(prm);
  const rms = Math.sqrt(r.reduce((s, v) => s + v * v, 0) / Math.max(1, r.length / 2));
  return { pred: paperPts.map(P => proj(prm, P)), rms, prm };
}

function solveSmall(A, b) {
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    if (Math.abs(M[p][c]) < 1e-15) return null;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = 0; r < n; r++) if (r !== c) { const k = M[r][c] / M[c][c]; for (let j = c; j <= n; j++) M[r][j] -= k * M[c][j]; }
  }
  return M.map((r, i) => r[n] / r[i]);
}

// Нормаль плоскости листа в координатах камеры по гомографии «мм → кадр» и фокусу.
export function planeNormal(H, f, vw, vh) {
  const Kinv = [1 / f, 0, -vw / 2 / f, 0, 1 / f, -vh / 2 / f, 0, 0, 1];
  const B = mul(Kinv, H);
  const r1 = [B[0], B[3], B[6]], r2 = [B[1], B[4], B[7]];
  const n = cross3(r1, r2), l = Math.hypot(...n) || 1;
  return n.map(v => v / l);
}
