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
