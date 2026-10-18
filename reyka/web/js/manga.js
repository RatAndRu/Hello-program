// Манга и аниме: объёмная голова (метод Лумиса), манекен с суставами, рука с пальцами,
// шпаргалка глаза, раскадровка, линии скорости и фокуса, лист разворота персонажа.
// Всё — обычные направляющие: точки в мм листа, рисуются через Pen поверх камеры.
// Никакого ИИ: простая 3D-геометрия (поворот + ортографическая проекция).

import { add, sub, mulS, dist, norm, perp, lerpP, len, dot } from './geom.js';
import { drawHair, HAIR_PRESETS, HAIR_DEFAULTS, HAIR_OPTIONS } from './hair.js';

const TAU = Math.PI * 2, D2R = Math.PI / 180;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;

let TYPES_REF = null; // ссылка на общую таблицу типов (для значений по умолчанию)
const P = (g, k) => {
  if (g.props && g.props[k] !== undefined) return g.props[k];
  const d = TYPES_REF && TYPES_REF[g.type] && TYPES_REF[g.type].props.find(x => x.key === k);
  return d ? d.def : undefined;
};

// ---------- 3D ----------
// Мир: x вправо, y вверх, z к зрителю. yaw — поворот головы влево/вправо (вокруг y),
// pitch — вверх/вниз (вокруг x), roll — наклон к плечу (в плоскости экрана).
function rotator(yaw, pitch, roll) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
  return (p) => {
    const x1 = p[0] * cy + p[2] * sy, z1 = -p[0] * sy + p[2] * cy, y1 = p[1];
    const y2 = y1 * cp + z1 * sp, z2 = -y1 * sp + z1 * cp;
    return [x1 * cr + y2 * sr, -x1 * sr + y2 * cr, z2];
  };
}
const v3n = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

// Камера для фигуры: центр C (мм), масштаб s (мм на единицу модели), повороты.
function view3(C, s, yaw, pitch, roll) {
  const R = rotator(yaw, pitch, roll);
  return {
    R,
    pr: (p) => { const q = R(p); return { x: C.x + q[0] * s, y: C.y - q[1] * s, z: q[2] }; },
    vis: (n) => R(n)[2],
  };
}
// Полилиния в 3D с видимостью по точкам: рисуются только видимые куски.
function poly3(pen, V, pts, visFn, layer = 'main', closed = false) {
  let run = [];
  const flush = () => { if (run.length > 1) pen.poly(run, false, layer); run = []; };
  const all = [];
  for (const p of pts) {
    const ok = visFn ? visFn(p) : true;
    all.push(ok);
    if (ok) run.push(V.pr(p)); else flush();
  }
  if (closed && all.length && all.every(Boolean)) { run = pts.map(p => V.pr(p)); pen.poly(run, true, layer); return; }
  if (closed && all[0] && run.length && all.length) { /* стык замкнутой линии */ run.push(V.pr(pts[0])); }
  flush();
}
// Простой детерминированный генератор случайных чисел (одинаковые линии при каждой отрисовке).
function rng(seed) { let a = (seed * 2654435761) >>> 0 || 1; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
// Сглаживание ломаной (Катмулл-Ром)
function spline(pts, n = 8) {
  if (pts.length < 3) return pts;
  const out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    for (let k = 0; k < n; k++) {
      const t = k / n, t2 = t * t, t3 = t2 * t;
      out.push(p1.map((_, d) => 0.5 * ((2 * p1[d]) + (-p0[d] + p2[d]) * t + (2 * p0[d] - 5 * p1[d] + 4 * p2[d] - p3[d]) * t2 + (-p0[d] + 3 * p1[d] - 3 * p2[d] + p3[d]) * t3)));
    }
  }
  out.push(pts[pts.length - 1]);
  return out;
}

// ======================================================================
// 1. ГОЛОВА (метод Лумиса) — с отдельными глазами, бровями, носом, ртом и ушами
// ======================================================================
// Модель: череп — шар радиуса 1 с центром в начале координат; линия бровей — его экватор (y=0);
// подбородок на y = −chin. Высоты черт — доли расстояния «брови → подбородок».
export const HEAD_PRESETS = {
  anime: { chin: 1.3, jaw: 'v', jawW: 0.8, eyeT: 0.3, eyeW: 0.36, eyeH: 0.78, eyeGap: 0.4, eyeTilt: 3, eyeShape: 'round', iris: 1.1, irisTall: 1.3, shine: true, lashes: true, crease: false, brows: true, browH: 0.12, noseStyle: 'tick', noseT: 0.62, noseSize: 0.7, mouthStyle: 'line', mouthT: 0.8, mouthW: 0.15, earShape: 'normal', earSize: 0.9 },
  shoujo: { chin: 1.25, jaw: 'v', jawW: 0.75, eyeT: 0.32, eyeW: 0.42, eyeH: 0.9, eyeGap: 0.41, eyeTilt: 0, eyeShape: 'round', iris: 1.2, irisTall: 1.35, shine: true, lashes: true, crease: true, brows: true, browH: 0.16, noseStyle: 'tick', noseT: 0.64, noseSize: 0.55, mouthStyle: 'smile', mouthT: 0.82, mouthW: 0.13, earShape: 'normal', earSize: 0.85 },
  shonen: { chin: 1.35, jaw: 'soft', jawW: 0.9, eyeT: 0.28, eyeW: 0.34, eyeH: 0.55, eyeGap: 0.42, eyeTilt: 8, eyeShape: 'sharp', iris: 1.0, irisTall: 1.15, shine: true, lashes: false, crease: false, brows: true, browH: 0.08, noseStyle: 'tri', noseT: 0.6, noseSize: 0.8, mouthStyle: 'line', mouthT: 0.78, mouthW: 0.17, earShape: 'normal', earSize: 0.95 },
  seinen: { chin: 1.45, jaw: 'soft', jawW: 0.92, eyeT: 0.2, eyeW: 0.29, eyeH: 0.48, eyeGap: 0.42, eyeTilt: 2, eyeShape: 'almond', iris: 1.0, irisTall: 1.05, shine: false, lashes: false, crease: true, brows: true, browH: 0.08, noseStyle: 'tri', noseT: 0.55, noseSize: 1.0, mouthStyle: 'lips', mouthT: 0.72, mouthW: 0.19, earShape: 'normal', earSize: 1.0 },
  // реализм: скулы ≈ 0.9 ширины черепа, углы челюсти ≈ 0.7, подбородок узкий
  real: { chin: 1.5, jaw: 'soft', jawW: 0.96, eyeT: 0.18, eyeW: 0.27, eyeH: 0.42, eyeGap: 0.42, eyeTilt: 0, eyeShape: 'almond', iris: 1.0, irisTall: 1.0, shine: false, lashes: false, crease: true, brows: true, browH: 0.07, noseStyle: 'real', noseT: 0.5, noseSize: 1.0, mouthStyle: 'lips', mouthT: 0.68, mouthW: 0.2, earShape: 'normal', earSize: 1.0 },
  realF: { chin: 1.42, jaw: 'soft', jawW: 0.84, eyeT: 0.2, eyeW: 0.29, eyeH: 0.52, eyeGap: 0.42, eyeTilt: 3, eyeShape: 'almond', iris: 1.05, irisTall: 1.0, shine: false, lashes: true, crease: true, brows: true, browH: 0.1, browTilt: -0.1, noseStyle: 'real', noseT: 0.53, noseSize: 0.82, mouthStyle: 'lips', mouthT: 0.7, mouthW: 0.18, earShape: 'normal', earSize: 0.92 },
  realHard: { chin: 1.58, jaw: 'square', jawW: 0.9, eyeT: 0.17, eyeW: 0.26, eyeH: 0.38, eyeGap: 0.42, eyeTilt: -2, eyeShape: 'almond', iris: 1.0, irisTall: 1.0, shine: false, lashes: false, crease: true, brows: true, browH: 0.05, browTilt: 0.25, noseStyle: 'real', noseT: 0.5, noseSize: 1.08, mouthStyle: 'lips', mouthT: 0.68, mouthW: 0.21, earShape: 'normal', earSize: 1.0 },
  chibi: { chin: 1.0, jaw: 'round', jawW: 0.95, eyeT: 0.42, eyeW: 0.46, eyeH: 1.0, eyeGap: 0.44, eyeTilt: 0, eyeShape: 'round', iris: 1.2, irisTall: 1.25, shine: true, lashes: false, crease: false, brows: true, browH: 0.1, noseStyle: 'none', noseT: 0.65, noseSize: 0.5, mouthStyle: 'smile', mouthT: 0.8, mouthW: 0.1, earShape: 'normal', earSize: 0.75 },
};
const JAWS = { v: [0.5, 0.62, 0.05], soft: [0.66, 0.74, 0.12], square: [0.8, 0.82, 0.2], round: [0.6, 0.86, 0.22] }; // [tA, ширина угла, ширина подбородка]

function headModel(o) {
  const Lc = o.chin, [tA, wAk, wC] = JAWS[o.jaw] || JAWS.soft, fw = o.jawW;
  const wA = wAk * fw, wCh = wC * fw + 0.03;
  // полуширина лица на высоте y (y ≤ 0 — ниже бровей)
  const tE = 0.45;
  const halfW = (y) => {
    if (y >= 0) return Math.sqrt(Math.max(0, 1 - y * y)) * 0.97;
    const t = Math.min(1, -y / Lc);
    if (t < tE) return lerp(0.92, lerp(0.92, wA, 0.35) , t / tE);
    if (t < tA) return lerp(lerp(0.92, wA, 0.35), wA, (t - tE) / Math.max(0.01, tA - tE));
    return lerp(wA, wCh, Math.pow((t - tA) / Math.max(0.01, 1 - tA), 0.9));
  };
  const chinZ = o.jaw === 'round' ? 0.72 : 0.8;
  const zc = (y) => (y >= 0 ? Math.sqrt(Math.max(0, 1 - y * y)) : lerp(1.0, chinZ, Math.pow(Math.min(1, -y / Lc), 1.4)));
  const faceZ = (x, y) => { const hw = Math.max(0.05, halfW(y)), q = Math.min(1, Math.abs(x) / hw); return zc(y) * Math.sqrt(Math.max(0, 1 - 0.86 * q * q)); };
  const at = (x, y, dz = 0) => [x, y, faceZ(x, y) + dz];
  const normal = (x, y) => { const e = 0.01; const dzx = (faceZ(x + e, y) - faceZ(x - e, y)) / (2 * e), dzy = (faceZ(x, y + e) - faceZ(x, y - e)) / (2 * e); return v3n([-dzx, -dzy, 1]); };
  return { Lc, tA, wA, wCh, halfW, zc, faceZ, at, normal, tE };
}

// Рисует голову. o — параметры (все черты), C — центр черепа (мм), r — радиус черепа (мм).
export function drawHead(pen, o, C, r, yaw, pitch, roll, opt = {}) {
  const M = headModel(o), V = view3(C, r, yaw, pitch, roll);
  const L = M.Lc;
  const faceVis = (p) => V.vis(M.normal(p[0], p[1])) > 0.03;
  const sphVis = (p) => V.R(p)[2] > 0.0;
  const main = opt.layer || 'main';
  const cons = o.loomis !== false;
  // 1) шар черепа (в ортографии — всегда круг)
  if (cons) pen.circle(C, r, 'aux');
  // боковые срезы (место уха) — только видимая сторона
  if (cons) for (const s of [-1, 1]) {
    if (V.vis([s, 0, 0]) < -0.05) continue;
    const pts = []; for (let i = 0; i <= 64; i++) { const a = TAU * i / 64; pts.push([s * 0.72, Math.sin(a) * 0.69, Math.cos(a) * 0.69]); }
    poly3(pen, V, pts, null, 'aux', true);
    // крест в боковом круге
    poly3(pen, V, [[s * 0.72, 0, 0.69], [s * 0.72, 0, -0.69]], null, 'aux');
    poly3(pen, V, [[s * 0.72, 0.69, 0], [s * 0.72, -0.69, 0]], null, 'aux');
  }
  // центральная линия по черепу и по лицу
  if (cons) {
    // большой круг x=0 через макушку; нижняя передняя часть закрыта лицом — её не рисуем
    const cl = []; for (let i = 0; i <= 96; i++) { const a = TAU * i / 96; cl.push([0, Math.sin(a), Math.cos(a)]); }
    poly3(pen, V, cl, (p) => sphVis(p) && !(p[1] < -0.02 && p[2] > 0), 'aux');
    const fl = []; for (let i = 0; i <= 30; i++) { const y = -L * i / 30; fl.push(M.at(0, y, 0.004)); }
    poly3(pen, V, fl, faceVis, 'aux');
    // линия бровей (экватор) — спереди
    const br = []; for (let i = 0; i <= 60; i++) { const a = -Math.PI * 0.62 + Math.PI * 1.24 * i / 60; br.push([Math.sin(a), 0, Math.cos(a)]); }
    poly3(pen, V, br, sphVis, 'aux');
  }
  // поперечные линии по лицу: глаза, низ носа, рот
  if (o.grid !== false) {
    for (const t of [o.eyeT, o.noseT, o.mouthT]) {
      const y = -t * L, hw = M.halfW(y) * 0.97, pts = [];
      for (let i = 0; i <= 40; i++) pts.push(M.at(-hw + 2 * hw * i / 40, y, 0.004));
      poly3(pen, V, pts, faceVis, 'aux');
    }
  }
  // волосы: линия роста волос и объём
  if (o.hair) {
    const yh = 0.5, rr = Math.sqrt(1 - yh * yh), hl = [];
    for (let i = 0; i <= 50; i++) { const a = -1.25 + 2.5 * i / 50; const y = yh - 0.38 * Math.pow(Math.abs(a) / 1.25, 3); const k = Math.sqrt(Math.max(0, 1 - y * y)) / rr; hl.push([Math.sin(a) * rr * k, y, Math.cos(a) * rr * k]); }
    poly3(pen, V, hl, sphVis, 'aux');
    pen.circle(C, r * 1.12, 'ghost');
  }
  // в профиль центральная линия лица становится контуром (лоб → переносица → губы → подбородок)
  if (Math.abs(Math.sin(yaw)) > 0.55) {
    const yE0 = -o.eyeT * L, yN0 = -o.noseT * L, yM0 = -o.mouthT * L, ns0 = o.noseSize, zc = M.zc;
    const ctl = [[0, 0.55, Math.sqrt(1 - 0.3025)], [0, 0.2, Math.sqrt(1 - 0.04) + 0.01], [0, 0, 1.02], [0, yE0 * 0.75, zc(yE0) - 0.035],
      [0, yN0 + 0.06 * ns0, zc(yN0) + 0.2 * ns0], [0, yN0, zc(yN0) + 0.02], [0, yM0 + 0.06, zc(yM0) + 0.03], [0, yM0, zc(yM0) + 0.005],
      [0, yM0 - 0.05, zc(yM0) + 0.025], [0, (yM0 - L) / 2, zc((yM0 - L) / 2) - 0.015], [0, -L, zc(-L) + 0.02]];
    poly3(pen, V, spline(ctl, 6), null, main);
  }
  // 2) челюсть: ухо → угол челюсти → подбородок (обе стороны)
  const jawSide = (s) => spline([[s * 0.7, -0.42 * L, -0.12], [s * M.wA, -M.tA * L, 0.05 + 0.25 * (1 - M.tA)], [s * M.wCh, -L, M.zc(-L) * 0.92], [0, -L * 1.01, M.zc(-L)]], 10);
  for (const s of [-1, 1]) {
    let pts = jawSide(s);
    // дальняя сторона в повороте: видна только часть от угла челюсти к подбородку (контур щеки)
    const far = V.vis([s, 0, 0]);
    if (far < -0.3) pts = pts.slice(far < -0.75 ? 16 : 7);
    poly3(pen, V, pts, null, main);
  }
  // щёки (скула) — от бокового круга вниз к углу челюсти, на видимой стороне
  for (const s of [-1, 1]) {
    if (V.vis([s, 0, 0.3]) < 0) continue;
    const pts = spline([[s * 0.86, -0.05 * L, 0.45], [s * 0.82, -0.3 * L, 0.42], [s * M.wA * 1.0, -M.tA * L, 0.05 + 0.25 * (1 - M.tA)]], 8);
    poly3(pen, V, pts, null, 'aux');
  }
  // шея
  // шея — цилиндр: его контур всегда по бокам, как бы ни повернулась голова
  if (o.neck) { const dx = Math.cos(yaw), dz = -Math.sin(yaw); for (const s of [-1, 1]) poly3(pen, V, [[s * 0.4 * dx, -0.5 * L, -0.15 + s * 0.4 * dz], [s * 0.42 * dx, -L - 0.45, -0.15 + s * 0.42 * dz]], null, main); }

  // 3) уши
  const earTop = 0.02, earBot = -o.noseT * L * (0.85 + 0.15 * o.earSize);
  for (const s of [-1, 1]) {
    if (V.vis([s, 0, -0.2]) < -0.2) continue;
    const h = (earTop - earBot) * o.earSize, y0 = (earTop + earBot) / 2 - h / 2, w = h * 0.5;
    let shp = [[0, 0.92], [-0.3, 1.0], [-0.62, 0.9], [-0.78, 0.62], [-0.66, 0.33], [-0.42, 0.08], [-0.16, -0.02], [0.02, 0.14]];
    if (o.earShape === 'elf') shp = [[0, 0.85], [-0.45, 1.2], [-1.25, 1.75], [-0.85, 0.9], [-0.66, 0.33], [-0.42, 0.08], [-0.16, -0.02], [0.02, 0.14]];
    const pts = spline(shp.map(([u, v]) => [s * 0.74, y0 + v * h, -0.06 + u * w]), 6);
    poly3(pen, V, pts, null, main);
    const inner = spline([[-0.12, 0.75], [-0.45, 0.78], [-0.55, 0.5], [-0.35, 0.25]].map(([u, v]) => [s * 0.745, y0 + v * h, -0.06 + u * w]), 6);
    poly3(pen, V, inner, null, 'aux');
  }

  // 4) глаза, брови
  const yE = -o.eyeT * L;
  const ew = o.eyeW, eh = ew * o.eyeH / 2, tilt = Math.tan((o.eyeTilt || 0) * D2R);
  const shapes = {
    almond: [(u) => Math.pow(1 - u * u, 0.8) * (1 + 0.22 * u), (u) => -0.55 * Math.pow(1 - u * u, 0.9)],
    round: [(u) => Math.pow(1 - u * u, 0.55) * (1 + 0.1 * u), (u) => -0.85 * Math.pow(1 - u * u, 0.65)],
    sharp: [(u) => 0.75 * Math.pow(1 - u * u, 0.9) * (1 + 0.45 * u), (u) => -0.32 * (1 - u * u)],
    droopy: [(u) => Math.pow(1 - u * u, 0.7) * (1 - 0.3 * u), (u) => -0.5 * Math.pow(1 - u * u, 0.8)],
    closed: [(u) => 0.45 * (1 - u * u), (u) => 0.45 * (1 - u * u)],
  };
  const [up0, lo0] = shapes[o.eyeShape] || shapes.almond;
  // моргание / прищур: верхнее и нижнее веко сходятся к линии чуть ниже середины
  const bl = o.eyeShape === 'closed' ? 0 : clamp(+o.blink || 0, 0, 1), meet = (u) => lo0(u) * 0.35;
  const up = (u) => lerp(up0(u), meet(u), bl), lo = (u) => lerp(lo0(u), meet(u), bl);
  const gx = clamp(+o.gazeX || 0, -1, 1), gy = clamp(+o.gazeY || 0, -1, 1);
  for (const s of [-1, 1]) {
    const cx = s * o.eyeGap;
    // u ∈ [−1, 1]: −1 — внутренний уголок (к носу)
    const toFace = (u, v, dz = 0.012) => { const x = cx + s * u * ew / 2, y = yE + v * eh + u * tilt * ew / 2 * 0.5; return M.at(x, y, dz); };
    const N = 28;
    const upper = [], lower = [];
    for (let i = 0; i <= N; i++) { const u = -1 + 2 * i / N; upper.push(toFace(u, up(u))); lower.push(toFace(u, lo(u))); }
    const evis = (p) => faceVis(p);
    poly3(pen, V, upper, evis, main);
    if (o.eyeShape !== 'closed') poly3(pen, V, lower, evis, o.lashes || o.eyeShape === 'round' ? main : 'aux');
    if (o.lashes && o.eyeShape !== 'closed' && bl < 0.7) { // жирная линия ресниц сверху (аниме)
      const l2 = []; for (let i = 4; i <= N; i++) { const u = -1 + 2 * i / N; l2.push(toFace(u * 1.04, up(u) + 0.13 + 0.12 * Math.max(0, u))); }
      poly3(pen, V, l2, evis, main);
      for (const u of [0.72, 0.9]) poly3(pen, V, [toFace(u, up(u) + 0.1), toFace(u + 0.32, up(u) + 0.5 + (u - 0.7))], evis, main);
    }
    if (o.crease && o.eyeShape !== 'closed') { const cr = []; for (let i = 3; i <= N - 1; i++) { const u = -1 + 2 * i / N; cr.push(toFace(u, up(u) * 1.25 + 0.28)); } poly3(pen, V, cr, evis, 'aux'); }
    if (o.eyeShape !== 'closed' && bl < 0.85) {
      // радужка — внутри разреза глаза
      const irx = o.iris * ew * 0.24, iry = irx * o.irisTall;
      const icx = gx * 0.32, icy = (gy * 0.25 - 0.05) * eh;
      const inEye = (u, v) => u > -1 && u < 1 && v / eh < up(u) - 0.02 && v / eh > lo(u) + 0.02;
      const ring = (rx, ry, layer) => {
        const pts = [], ok = [];
        for (let i = 0; i <= 48; i++) { const a = TAU * i / 48, u = icx + Math.cos(a) * rx / (ew / 2), v = icy + Math.sin(a) * ry; pts.push(toFace(u, v / eh, 0.016)); ok.push(inEye(u, v)); }
        let run = []; for (let i = 0; i < pts.length; i++) { if (ok[i] && faceVis(pts[i])) run.push(V.pr(pts[i])); else { if (run.length > 1) pen.poly(run, false, layer); run = []; } }
        if (run.length > 1) pen.poly(run, false, layer);
      };
      ring(irx, iry, main);
      ring(irx * 0.45, iry * 0.45, 'aux');
      if (o.shine) { // блики
        const hp = toFace(icx - 0.32 * irx / (ew / 2), (icy + 0.4 * iry) / eh, 0.02);
        if (faceVis(hp)) { const q = V.pr(hp); pen.circle(q, Math.max(0.3, irx * 0.28 * r), 'aux'); }
        const hp2 = toFace(icx + 0.35 * irx / (ew / 2), (icy - 0.42 * iry) / eh, 0.02);
        if (faceVis(hp2)) { const q = V.pr(hp2); pen.circle(q, Math.max(0.2, irx * 0.12 * r), 'aux'); }
      }
    }
    // бровь
    if (o.brows) {
      const bw = [], yb = up(0) + (o.browH || 0.1) / Math.max(0.02, eh) + 0.6;
      for (let i = 0; i <= 20; i++) { const u = -1.15 + 2.45 * i / 20; bw.push(toFace(u, yb + 0.35 * (1 - Math.pow((u - 0.15) / 1.3, 2)) - 0.15 * u * (o.browTilt || 0), 0.02)); }
      poly3(pen, V, bw, evis, main);
    }
  }
  // морщины: между бровями и на переносице (хмурится, морщится)
  if ((+o.wrinkle || 0) > 0.15) {
    const w = +o.wrinkle, yb = yE + eh * (up(0) + 0.9) + (o.browH || 0.1);
    for (const sx of [-1, 1]) poly3(pen, V, [M.at(sx * 0.055, yb + 0.05 * w, 0.02), M.at(sx * 0.075, yb - 0.09 * w, 0.02)], faceVis, 'aux');
    if (w > 0.45) for (const sx of [-1, 1]) poly3(pen, V, [M.at(sx * 0.07, yE * 0.25 - 0.02, 0.02), M.at(sx * 0.12, yE * 0.25 - 0.06, 0.02)], faceVis, 'aux');
  }

  // 5) нос
  const yN = -o.noseT * L, ns = o.noseSize, zN = M.zc(yN);
  const turned = Math.abs(Math.sin(yaw)) > 0.25 || Math.abs(Math.sin(pitch)) > 0.5;
  const tip = [0, yN + 0.06 * ns, zN + 0.2 * ns], base = [0, yN, zN + 0.03];
  const bridgeTop = M.at(0, yE * 0.4, 0.01);
  const bridge = spline([bridgeTop, [0, (yE * 0.4 + yN) / 2, M.zc((yE * 0.4 + yN) / 2) + 0.08 * ns], tip], 8);
  if (o.noseStyle === 'tick') {
    if (turned) poly3(pen, V, [...bridge.slice(Math.floor(bridge.length / 2)), base], null, main);
    else poly3(pen, V, [[0.015 * ns, yN + 0.05 * ns, zN + 0.12 * ns], [-0.035 * ns, yN, zN + 0.06]], null, main);
  } else if (o.noseStyle === 'tri') {
    poly3(pen, V, bridge, null, turned ? main : 'aux');
    const wl = M.at(-0.1 * ns, yN + 0.02, 0.0), wr = M.at(0.1 * ns, yN + 0.02, 0.0);
    poly3(pen, V, [wl, tip, wr], null, 'aux');
    poly3(pen, V, [wl, base, wr], faceVis, main);
  } else if (o.noseStyle === 'real') {
    for (const s of [-1, 1]) poly3(pen, V, spline([M.at(s * 0.05, yE * 0.3, 0.01), M.at(s * 0.06, yN * 0.7, 0.04), [s * 0.06 * ns, yN + 0.07 * ns, zN + 0.14 * ns]], 6), faceVis, 'aux');
    // кончик и крылья
    const tipPts = []; for (let i = 0; i <= 16; i++) { const a = Math.PI + Math.PI * i / 16; tipPts.push([Math.cos(a) * 0.07 * ns, yN + 0.06 * ns + Math.sin(a) * 0.055 * ns, zN + 0.18 * ns]); }
    poly3(pen, V, tipPts, null, main);
    for (const s of [-1, 1]) {
      const wing = spline([[s * 0.07 * ns, yN + 0.04 * ns, zN + 0.14 * ns], M.at(s * 0.12 * ns, yN + 0.05 * ns, 0.04), M.at(s * 0.11 * ns, yN - 0.005, 0.03), [s * 0.04 * ns, yN, zN + 0.08]], 6);
      poly3(pen, V, wing, null, main);
    }
    if (turned) poly3(pen, V, bridge, null, main);
  }

  // 6) рот
  const yM = -o.mouthT * L, mw = o.mouthW * (+o.mouthWk || 1);
  // приоткрытый рот (говорит, удивляется): у любого стиля — нижняя губа уходит вниз
  const mo = o.mouthStyle === 'open' ? Math.max(1, +o.mouthOpen || 0) : clamp(+o.mouthOpen || 0, 0, 1.3);
  const mline = (f, dz = 0.012) => { const pts = []; for (let i = 0; i <= 24; i++) { const x = -mw + 2 * mw * i / 24, q = x / mw; pts.push(M.at(x, yM + f(q), dz)); } return pts; };
  const topF = o.mouthStyle === 'smile' ? (q) => 0.045 * q * q - 0.02 : o.mouthStyle === 'lips' ? (q) => -0.01 * q * q : (q) => 0.01 - 0.01 * q * q;
  if (mo > 0.05 && o.mouthStyle !== 'open') {
    poly3(pen, V, mline(topF), faceVis, main);
    poly3(pen, V, mline((q) => topF(q) - 0.12 * mo * Math.pow(1 - q * q, 0.7)), faceVis, main);
  } else if (o.mouthStyle === 'line') poly3(pen, V, mline((q) => -0.015 * q * q + 0.01), faceVis, main);
  else if (o.mouthStyle === 'smile') poly3(pen, V, mline((q) => 0.045 * q * q - 0.02), faceVis, main);
  else if (o.mouthStyle === 'open') {
    poly3(pen, V, mline((q) => 0.01 - 0.01 * q * q), faceVis, main);
    poly3(pen, V, mline((q) => -0.12 * mo * Math.pow(1 - q * q, 0.7) + 0.01), faceVis, main);
  } else if (o.mouthStyle === 'lips') {
    poly3(pen, V, mline((q) => -0.01 * q * q), faceVis, main);
    poly3(pen, V, mline((q) => 0.055 * Math.pow(1 - q * q, 0.6) - 0.022 * Math.exp(-(q * q) / 0.012) + 0.012 * Math.exp(-((Math.abs(q) - 0.2) ** 2) / 0.01), 0.02), faceVis, 'aux');
    poly3(pen, V, mline((q) => -0.075 * Math.pow(1 - q * q, 0.65), 0.02), faceVis, 'aux');
  }
  return { V, M };
}

function headOpts(g) {
  const o = {};
  for (const k of ['chin', 'jaw', 'jawW', 'eyeT', 'eyeW', 'eyeH', 'eyeGap', 'eyeTilt', 'eyeShape', 'iris', 'irisTall', 'shine', 'lashes', 'crease', 'brows', 'browH', 'browTilt', 'noseStyle', 'noseT', 'noseSize', 'mouthStyle', 'mouthT', 'mouthW', 'earShape', 'earSize', 'gazeX', 'gazeY', 'loomis', 'grid', 'neck', 'hair', 'blink', 'mouthOpen', 'mouthWk', 'wrinkle']) o[k] = P(g, k);
  return o;
}
const presetSet = (presets) => (g, v) => { const p = presets[v]; if (p) Object.assign(g.props, JSON.parse(JSON.stringify(p))); };

const sec = (label) => ({ key: '_' + label, type: 'section', label });
const windOf = (g) => ({ amt: +P(g, 'windAmt') || 0, dir: +P(g, 'windDir') || 0, t: +P(g, 'windT') || 0 });
const headProps = [
  { key: 'preset', label: 'Стиль', type: 'select', options: [['anime', 'Аниме'], ['shoujo', 'Сёдзё'], ['shonen', 'Сёнэн'], ['seinen', 'Сэйнэн'], ['real', 'Реализм ♂'], ['realF', 'Реализм ♀'], ['realHard', 'Реализм ♂ брутальный'], ['chibi', 'Чиби']], def: 'anime', onSet: presetSet(HEAD_PRESETS) },
  sec('Поворот головы'),
  { key: 'yaw', label: 'Влево ↔ вправо, °', type: 'range', min: -180, max: 180, step: 1, def: 25 },
  { key: 'pitch', label: 'Вниз ↔ вверх, °', type: 'range', min: -90, max: 90, step: 1, def: -10 },
  { key: 'roll', label: 'Наклон к плечу (180 = вверх ногами), °', type: 'range', min: -180, max: 180, step: 1, def: 0 },
  sec('Лицо'),
  { key: 'chin', label: 'Длина лица (брови → подбородок)', type: 'range', min: 0.8, max: 1.9, step: 0.01, def: 1.3 },
  { key: 'jaw', label: 'Челюсть', type: 'select', options: [['v', 'Острая V'], ['soft', 'Мягкая'], ['square', 'Квадратная'], ['round', 'Круглая']], def: 'v' },
  { key: 'jawW', label: 'Ширина челюсти', type: 'range', min: 0.5, max: 1.2, step: 0.01, def: 0.8 },
  sec('Глаза'),
  { key: 'eyeShape', label: 'Форма', type: 'select', options: [['round', 'Круглые'], ['almond', 'Миндаль'], ['sharp', 'Острые'], ['droopy', 'Опущенные'], ['closed', 'Закрытые ^']], def: 'round' },
  { key: 'eyeT', label: 'Высота линии глаз', type: 'range', min: 0.05, max: 0.55, step: 0.01, def: 0.3 },
  { key: 'eyeW', label: 'Ширина глаза', type: 'range', min: 0.15, max: 0.6, step: 0.01, def: 0.36 },
  { key: 'eyeH', label: 'Раскрытие (высота)', type: 'range', min: 0.2, max: 1.3, step: 0.01, def: 0.78 },
  { key: 'eyeGap', label: 'Расстояние между глазами', type: 'range', min: 0.25, max: 0.6, step: 0.01, def: 0.4 },
  { key: 'eyeTilt', label: 'Наклон (уголки вверх), °', type: 'range', min: -20, max: 25, step: 1, def: 3 },
  { key: 'iris', label: 'Радужка', type: 'range', min: 0.5, max: 1.6, step: 0.05, def: 1.1 },
  { key: 'irisTall', label: 'Радужка вытянута', type: 'range', min: 0.8, max: 1.6, step: 0.05, def: 1.3 },
  { key: 'gazeX', label: 'Взгляд ← →', type: 'range', min: -1, max: 1, step: 0.05, def: 0 },
  { key: 'gazeY', label: 'Взгляд ↓ ↑', type: 'range', min: -1, max: 1, step: 0.05, def: 0 },
  { key: 'blink', label: 'Веки прикрыты (моргание, прищур)', type: 'range', min: 0, max: 1, step: 0.05, def: 0 },
  { key: 'shine', label: 'Блики', type: 'toggle', def: true },
  { key: 'lashes', label: 'Ресницы (жирная линия)', type: 'toggle', def: true },
  { key: 'crease', label: 'Складка века', type: 'toggle', def: false },
  { key: 'brows', label: 'Брови', type: 'toggle', def: true },
  { key: 'browH', label: 'Брови выше/ниже', type: 'range', min: 0.0, max: 0.3, step: 0.01, def: 0.12, show: (g) => P(g, 'brows') },
  { key: 'browTilt', label: 'Брови: грустные ↔ злые', type: 'range', min: -1, max: 1, step: 0.05, def: 0, show: (g) => P(g, 'brows') },
  sec('Нос'),
  { key: 'noseStyle', label: 'Нос', type: 'select', options: [['tick', 'Штрих'], ['tri', 'Треугольник'], ['real', 'Объёмный'], ['none', 'Нет']], def: 'tick' },
  { key: 'noseT', label: 'Высота носа', type: 'range', min: 0.3, max: 0.8, step: 0.01, def: 0.62 },
  { key: 'noseSize', label: 'Размер носа', type: 'range', min: 0.3, max: 1.6, step: 0.05, def: 0.7 },
  sec('Рот'),
  { key: 'mouthStyle', label: 'Рот', type: 'select', options: [['line', 'Линия'], ['smile', 'Улыбка'], ['open', 'Открыт'], ['lips', 'Губы']], def: 'line' },
  { key: 'mouthT', label: 'Высота рта', type: 'range', min: 0.5, max: 0.95, step: 0.01, def: 0.8 },
  { key: 'mouthW', label: 'Ширина рта', type: 'range', min: 0.05, max: 0.35, step: 0.01, def: 0.15 },
  { key: 'mouthOpen', label: 'Рот приоткрыт', type: 'range', min: 0, max: 1.3, step: 0.05, def: 0 },
  { key: 'wrinkle', label: 'Морщины (хмурится)', type: 'range', min: 0, max: 1, step: 0.05, def: 0 },
  { key: 'mouthWk', label: '', type: 'hidden', def: 1 },
  sec('Уши'),
  { key: 'earShape', label: 'Уши', type: 'select', options: [['normal', 'Обычные'], ['elf', 'Эльфийские']], def: 'normal' },
  { key: 'earSize', label: 'Размер ушей', type: 'range', min: 0.5, max: 1.4, step: 0.05, def: 0.9 },
  sec('Построение'),
  { key: 'loomis', label: 'Шар, боковой срез и оси (Лумис)', type: 'toggle', def: true },
  { key: 'grid', label: 'Линии глаз, носа и рта', type: 'toggle', def: true },
  { key: 'neck', label: 'Шея', type: 'toggle', def: true },
  { key: 'hair', label: 'Линия волос и объём причёски', type: 'toggle', def: false },
  { key: 'hairStyle', label: 'Причёска', type: 'select', options: [['none', 'Нет'], ...HAIR_OPTIONS, ['custom', 'Своя (от персонажа)']], def: 'none' },
  { key: 'windAmt', label: 'Ветер в волосах', type: 'range', min: 0, max: 1, step: 0.05, def: 0, show: (g) => P(g, 'hairStyle') !== 'none' },
  { key: 'windDir', label: 'Ветер дует: → 0°, ↑ 90°, ← 180°', type: 'range', min: -180, max: 180, step: 5, def: 0, show: (g) => P(g, 'hairStyle') !== 'none' && P(g, 'windAmt') > 0 },
  { key: 'windT', label: '', type: 'hidden', def: 0 },
  { key: 'r', label: 'Размер черепа (радиус), мм', type: 'range', min: 5, max: 150, step: 1, def: 30 },
];

const headPad = (C, r) => ({ c: { x: C.x + r * 2.05, y: C.y }, r: Math.max(6, r * 0.6) });
const head = {
  name: 'Голова 3D', icon: '🗿', group: 'manga',
  desc: 'Объёмная голова по методу Лумиса. Поворот — ручка в круглом «тачпаде» справа от головы (вбок — влево/вправо, вверх-вниз — наклон); размер и наклон к плечу — верхняя ручка; двигать — центр. Глаза, нос, рот и уши настраиваются отдельно',
  create: (c, s) => [{ x: c.x, y: c.y - s * 0.25 }],
  props: headProps,
  actions: [
    ['↕ Вверх ногами', (g) => { const r = +P(g, 'roll') || 0; g.props.roll = Math.abs(r) > 90 ? 0 : 180; }],
    ['⇋ Отразить поворот', (g) => { g.props.yaw = -(+P(g, 'yaw') || 0); g.props.roll = -(+P(g, 'roll') || 0); }],
    ['🎲 Пряди причёски', (g) => { g.props.hairSeed = 1 + Math.floor(Math.random() * 99999); }],
  ],
  init: (g, s) => { g.props.r = Math.round(s * 0.55); Object.assign(g.props, JSON.parse(JSON.stringify(HEAD_PRESETS.anime))); },
  moveIdx: 0,
  geo(g) { return { C: g.pts[0], r: +P(g, 'r') || 30, yaw: (+P(g, 'yaw') || 0) * D2R, pitch: (+P(g, 'pitch') || 0) * D2R, roll: (+P(g, 'roll') || 0) * D2R }; },
  draw(pen, g, ctx) {
    const { C, r, yaw, pitch, roll } = this.geo(g);
    drawHead(pen, headOpts(g), C, r, yaw, pitch, roll);
    const hs = P(g, 'hairStyle');
    const hp = hs === 'custom' ? g.props.hairCustom : HAIR_PRESETS[hs];
    if (hs && hs !== 'none' && hp) drawHair(pen, hp, C, r, yaw, pitch, roll, (hs === 'custom' ? +hp.seed : +P(g, 'hairSeed')) || 1, { chin: +P(g, 'chin') || 1.3, wind: windOf(g) });
    // «тачпад» поворота — отдельно от головы, чтобы не сливался с ручкой перемещения
    const T = headPad(C, r);
    pen.circle(T.c, T.r, 'ghost'); pen.seg({ x: T.c.x - T.r, y: T.c.y }, { x: T.c.x + T.r, y: T.c.y }, 'ghost'); pen.seg({ x: T.c.x, y: T.c.y - T.r }, { x: T.c.x, y: T.c.y + T.r }, 'ghost');
    if (ctx.labels) pen.label({ x: C.x, y: C.y - r * 1.35 }, `голова ${Math.round(r * (1 + (+P(g, 'chin') || 1)))} мм · ${Math.round(P(g, 'yaw'))}° / ${Math.round(P(g, 'pitch'))}°`);
  },
  handles(g) {
    const { C, r, yaw, pitch, roll } = this.geo(g);
    const crown = { x: C.x + Math.sin(roll) * r * 1.25, y: C.y - Math.cos(roll) * r * 1.25 };
    const T = headPad(C, r);
    // вперёд/назад: при |поворот| > 90° точка остаётся на краю круга (затылок к зрителю)
    const sx = Math.abs(yaw) > Math.PI / 2 ? Math.sign(yaw) : Math.sin(yaw);
    return [C, { x: crown.x, y: crown.y }, { x: T.c.x + T.r * sx, y: T.c.y - T.r * Math.sin(pitch) }];
  },
  handleLabel: (g, i) => (i === 0 ? 'двигать' : i === 1 ? 'размер · наклон' : 'поворот'),
  drag(g, i, p) {
    const { C, r, roll } = this.geo(g);
    if (i === 0) { g.pts[0] = p; return; }
    if (i === 1) {
      const d = sub(p, C);
      g.props.r = Math.max(4, Math.round(len(d) / 1.25 * 10) / 10);
      // верхняя ручка задаёт наклон к плечу, только если поворот небольшой (иначе — неоднозначно)
      g.props.roll = Math.round(clamp(Math.atan2(d.x, -d.y) / D2R, -180, 180));
      return;
    }
    // «тачпад»: вбок — поворот влево/вправо, вверх/вниз — наклон головы
    void roll;
    const T = headPad(C, r), X = (p.x - T.c.x) / T.r, Y = -(p.y - T.c.y) / T.r;
    g.props.yaw = Math.round(Math.asin(clamp(X, -1, 1)) / D2R); g.props.pitch = Math.round(Math.asin(clamp(Y, -1, 1)) / D2R);
  },
};

// ======================================================================
// 2. МАНЕКЕН ТЕЛА с суставами
// ======================================================================
// Кости — дерево. Поза хранится как относительные углы костей (повернул плечо — рука
// пошла следом) и «укорочение» f (1 — кость в плоскости листа, меньше — направлена
// на зрителя или от него; эллипс-сечение на кости показывает это).
// Единица — высота головы. Шаблон — 8 голов, стоя (y вниз, 0 — макушка).
export const BJ = ['pelvis', 'chest', 'neck', 'head', 'shR', 'elR', 'wrR', 'haR', 'shL', 'elL', 'wrL', 'haL', 'hipR', 'knR', 'anR', 'toR', 'hipL', 'knL', 'anL', 'toL'];
const BJ_RU = ['таз', 'грудь', 'шея', 'голова', 'плечо', 'локоть', 'запястье', 'кисть', 'плечо', 'локоть', 'запястье', 'кисть', 'бедро', 'колено', 'лодыжка', 'носок', 'бедро', 'колено', 'лодыжка', 'носок'];
const BPAR = [-1, 0, 1, 2, 2, 4, 5, 6, 2, 8, 9, 10, 0, 12, 13, 14, 0, 16, 17, 18];
const sym = (o) => { // дополняем левую сторону зеркально, если не задана
  const r = { ...o };
  for (const [a, b] of [['shR', 'shL'], ['elR', 'elL'], ['wrR', 'wrL'], ['haR', 'haL'], ['hipR', 'hipL'], ['knR', 'knL'], ['anR', 'anL'], ['toR', 'toL']]) if (r[a] && !r[b]) r[b] = [-r[a][0], r[a][1]];
  return r;
};
export const BODY_POSES = {
  stand: sym({ pelvis: [0, 3.85], chest: [0, 2.3], neck: [0, 1.3], head: [0, 0.5], shR: [-0.95, 1.48], elR: [-1.12, 2.95], wrR: [-1.2, 3.95], haR: [-1.25, 4.7], hipR: [-0.48, 3.95], knR: [-0.5, 5.85], anR: [-0.5, 7.7], toR: [-0.66, 8.02] }),
  contra: { pelvis: [0.1, 3.85], chest: [0.02, 2.3], neck: [-0.05, 1.3], head: [-0.05, 0.5], shR: [-0.95, 1.56], elR: [-1.12, 3.02], wrR: [-1.05, 4.0], haR: [-1.0, 4.72], shL: [0.9, 1.42], elL: [1.45, 2.75], wrL: [0.78, 3.62], haL: [0.42, 3.8], hipR: [-0.36, 3.84], knR: [-0.2, 5.8], anR: [-0.06, 7.7], toR: [-0.18, 8.02], hipL: [0.56, 4.06], knL: [0.78, 5.86], anL: [0.86, 7.62], toL: [1.08, 7.88] },
  walk: { pelvis: [0, 3.85], chest: [0.06, 2.3], neck: [0.12, 1.3], head: [0.18, 0.5], shR: [0.06, 1.5], elR: [-0.34, 2.9], wrR: [-0.55, 3.86], haR: [-0.62, 4.56], shL: [0.14, 1.5], elL: [0.46, 2.92], wrL: [0.86, 3.7], haL: [1.02, 4.36], hipR: [-0.02, 3.95], knR: [0.56, 5.76], anR: [0.6, 7.7], toR: [1.0, 7.96], hipL: [0.02, 3.95], knL: [-0.36, 5.8], anL: [-0.96, 7.46], toL: [-0.78, 7.96] },
  run: { pelvis: [0, 3.9], chest: [0.36, 2.44], neck: [0.56, 1.5], head: [0.78, 0.76], shR: [0.46, 1.66], elR: [0.86, 2.62], wrR: [1.46, 2.16], haR: [1.82, 2.0], shL: [0.52, 1.66], elL: [-0.56, 2.66], wrL: [0.08, 3.36], haL: [0.46, 3.86], hipR: [-0.02, 4.0], knR: [-0.62, 5.5], anR: [-1.66, 6.42], toR: [-1.96, 6.16], hipL: [0.02, 4.0], knL: [1.22, 4.76], anL: [0.86, 6.42], toL: [1.26, 6.62] },
  sit: { pelvis: [0, 5.7], chest: [0.05, 4.15], neck: [0.08, 3.15], head: [0.12, 2.35], shR: [0.06, 3.35], elR: [0.06, 4.8], wrR: [0.76, 5.2], haR: [1.42, 5.3], shL: [0.11, 3.35], elL: [0.12, 4.8], wrL: [0.82, 5.25], haL: [1.48, 5.36], hipR: [-0.02, 5.75], knR: [1.86, 5.66], anR: [1.86, 7.65], toR: [2.26, 7.95], hipL: [0.02, 5.75], knL: [1.92, 5.7], anL: [1.96, 7.65], toL: [2.36, 7.95] },
  jump: sym({ pelvis: [0, 3.85], chest: [0, 2.3], neck: [0, 1.3], head: [0, 0.5], shR: [-0.95, 1.45], elR: [-1.6, 0.56], wrR: [-2.05, -0.34], haR: [-2.25, -1.0], hipR: [-0.48, 3.95], knR: [-1.06, 5.6], anR: [-1.76, 7.0], toR: [-2.1, 7.12] }),
  fight: { pelvis: [-0.05, 3.95], chest: [0, 2.4], neck: [0.05, 1.42], head: [0.1, 0.64], shR: [-0.8, 1.6], elR: [-1.06, 2.5], wrR: [-0.46, 2.0], haR: [-0.2, 1.66], shL: [0.86, 1.55], elL: [1.36, 2.26], wrL: [1.56, 1.46], haL: [1.6, 0.96], hipR: [-0.5, 4.0], knR: [-1.1, 5.7], anR: [-1.4, 7.6], toR: [-1.76, 7.86], hipL: [0.4, 4.0], knL: [0.96, 5.8], anL: [1.2, 7.7], toL: [1.6, 7.9] },
};
export const L8 = BJ.map((n, i) => (BPAR[i] < 0 ? 0 : Math.hypot(BODY_POSES.stand[n][0] - BODY_POSES.stand[BJ[BPAR[i]]][0], BODY_POSES.stand[n][1] - BODY_POSES.stand[BJ[BPAR[i]]][1])));
const WIDE = new Set([4, 8, 12, 16]); // ключицы и тазовые кости — масштабируются по ширине
// длины костей (в головах) для заданных пропорций
function boneLens(N, build) {
  const k = (N - 1) / 7, wf = (0.55 + 0.45 * k), bs = build === 'female' ? [0.86, 1.12] : build === 'child' ? [0.9, 0.95] : build === 'hero' ? [1.12, 1.0] : [1, 1];
  return L8.map((l, i) => {
    if (i === 3) return 0.5 + 0.3 * k; // шея → центр головы
    if (WIDE.has(i)) return l * wf * (i === 4 || i === 8 ? bs[0] : bs[1]);
    return l * k;
  });
}
const absAng = (v) => Math.atan2(v[1], v[0]);
// поза из шаблона координат → относительные углы и укорочения
export function poseFromTemplate(T) {
  const pts = BJ.map(n => T[n]), abs = [], rel = [], f = [];
  for (let i = 0; i < BJ.length; i++) {
    const p = BPAR[i]; if (p < 0) { abs.push(-Math.PI / 2); rel.push(0); f.push(1); continue; }
    const v = [pts[i][0] - pts[p][0], pts[i][1] - pts[p][1]], a = absAng(v);
    abs.push(a);
    const pa = abs[p];
    let r = a - pa; while (r > Math.PI) r -= TAU; while (r < -Math.PI) r += TAU;
    rel.push(r);
    f.push(clamp(Math.hypot(v[0], v[1]) / L8[i], 0.12, 1));
  }
  return { rel: rel.map(x => Math.round(x / D2R * 10) / 10), f: f.map(x => Math.round(x * 100) / 100) };
}
// Позы, нарисованные в профиль (идёт, бежит, сидит): горизонталь шаблона — это глубина.
// Строим 3D (ширину плеч и бёдер берём из стоячей позы) и переводим в углы/укорочения/глубину.
const PROFILE_POSES = new Set(['walk', 'run', 'sit']);
export function poseFromProfile(T) {
  const St = BODY_POSES.stand, px = T.pelvis[0];
  const P3 = BJ.map(n => [/^(sh|el|wr|ha|hip|kn|an|to)/.test(n) ? St[n][0] * (/^(sh|hip)/.test(n) ? 1 : 0.9) : 0, T[n][1], T[n][0] - px]);
  const abs = [], rel = [], f = [], z = [];
  for (let i = 0; i < BJ.length; i++) {
    const p = BPAR[i]; if (p < 0) { abs.push(-Math.PI / 2); rel.push(0); f.push(1); z.push(1); continue; }
    const d = [P3[i][0] - P3[p][0], P3[i][1] - P3[p][1], P3[i][2] - P3[p][2]], a = Math.atan2(d[1], d[0]);
    abs.push(a);
    let r = a - abs[p]; while (r > Math.PI) r -= TAU; while (r < -Math.PI) r += TAU;
    rel.push(Math.round(r / D2R * 10) / 10);
    f.push(Math.round(clamp(Math.hypot(d[0], d[1]) / (Math.hypot(d[0], d[1], d[2]) || 1), 0.12, 1) * 100) / 100);
    z.push(d[2] < 0 ? -1 : 1);
  }
  return { rel, f, z };
}
// Позы, заданные сразу в 3D: [x, y, z] в головах; x — вправо от зрителя (правая рука фигуры
// при виде анфас — слева, x < 0), y — вниз, z — к зрителю (вперёд для фигуры).
// prop — что в руках (меч, пистолет): рисуется от кистей и идёт за ними, когда тянешь руки.
export const BODY_POSES_3D = {
  squat: { yaw: 35, pose: { pelvis: [0, 6.65, -0.6], chest: [0, 5.2, 0], neck: [0, 4.25, 0.3], head: [0, 3.5, 0.45], shR: [-0.95, 4.4, 0.25], elR: [-0.95, 5.62, 1.1], wrR: [-0.42, 5.92, 1.9], haR: [-0.12, 6.3, 2.4], shL: [0.95, 4.4, 0.25], elL: [0.95, 5.62, 1.1], wrL: [0.42, 5.92, 1.9], haL: [0.12, 6.3, 2.4], hipR: [-0.48, 6.75, -0.6], knR: [-0.82, 6.3, 1.12], anR: [-0.56, 7.7, 0], toR: [-0.66, 8.02, 0.45], hipL: [0.48, 6.75, -0.6], knL: [0.82, 6.3, 1.12], anL: [0.56, 7.7, 0], toL: [0.66, 8.02, 0.45] } },
  cross: { yaw: 20, pitch: 15, pose: { pelvis: [0, 7.2, 0], chest: [0, 5.65, 0], neck: [0, 4.65, 0], head: [0, 3.85, 0.05], shR: [-0.95, 4.83, 0], elR: [-1.35, 6.2, 0.35], wrR: [-1.75, 7.05, 0.9], haR: [-1.85, 7.45, 1.25], shL: [0.95, 4.83, 0], elL: [1.35, 6.2, 0.35], wrL: [1.75, 7.05, 0.9], haL: [1.85, 7.45, 1.25], hipR: [-0.48, 7.3, 0], knR: [-1.85, 7.55, 1.2], anR: [0.35, 7.72, 1.0], toR: [0.62, 7.82, 0.86], hipL: [0.48, 7.3, 0], knL: [1.85, 7.55, 1.2], anL: [-0.35, 7.62, 1.5], toL: [-0.62, 7.72, 1.5] } },
  hug: { yaw: 70, pose: { pelvis: [0, 7.25, 0], chest: [0, 5.8, 0.35], neck: [0, 4.9, 0.75], head: [0, 4.3, 1.15], shR: [-0.9, 5.0, 0.6], elR: [-1.0, 5.9, 1.6], wrR: [-0.2, 6.3, 2.0], haR: [0.3, 6.4, 1.9], shL: [0.9, 5.0, 0.6], elL: [1.0, 5.9, 1.6], wrL: [0.2, 6.35, 2.05], haL: [-0.3, 6.45, 1.95], hipR: [-0.48, 7.3, 0], knR: [-0.45, 5.7, 1.1], anR: [-0.45, 7.6, 1.5], toR: [-0.5, 7.9, 1.9], hipL: [0.48, 7.3, 0], knL: [0.45, 5.7, 1.1], anL: [0.45, 7.6, 1.5], toL: [0.5, 7.9, 1.9] } },
  fall: { yaw: 25, pose: { pelvis: [0, 3.85, 0], chest: [0, 2.4, -0.6], neck: [0, 1.5, -1.0], head: [0, 0.8, -1.25], shR: [-0.95, 1.65, -0.85], elR: [-1.9, 0.65, -0.4], wrR: [-2.3, -0.25, 0.0], haR: [-2.4, -0.9, 0.2], shL: [0.95, 1.65, -0.85], elL: [1.75, 2.2, 0.3], wrL: [2.3, 1.6, 0.9], haL: [2.6, 1.1, 1.1], hipR: [-0.48, 3.95, 0], knR: [-0.7, 4.8, 1.6], anR: [-0.9, 6.4, 2.2], toR: [-1.0, 6.5, 2.6], hipL: [0.48, 3.95, 0], knL: [0.9, 5.6, 0.8], anL: [1.1, 7.2, 0.2], toL: [1.2, 7.4, 0.5] } },
  shoot: { yaw: 55, prop: 'gun', dir: [0, 0, 1], pose: { pelvis: [0, 3.9, 0], chest: [0, 2.35, 0.25], neck: [0, 1.38, 0.4], head: [0, 0.6, 0.55], shR: [-0.9, 1.55, 0.35], elR: [-0.5, 1.8, 1.7], wrR: [-0.08, 1.85, 2.6], haR: [0, 1.88, 3.2], shL: [0.9, 1.55, 0.35], elL: [0.5, 1.85, 1.7], wrL: [0.08, 1.9, 2.6], haL: [0.02, 1.95, 3.1], hipR: [-0.48, 4.0, 0], knR: [-0.75, 5.85, 0.35], anR: [-0.8, 7.7, -0.1], toR: [-0.95, 8.02, 0.25], hipL: [0.48, 4.0, 0], knL: [0.7, 5.85, 0.5], anL: [0.8, 7.7, 0.6], toL: [0.95, 8.02, 0.95] } },
  shoot1: { yaw: 0, prop: 'gun', dir: [-0.7, 0, 0.71], pose: { pelvis: [0, 3.85, 0], chest: [0, 2.3, 0], neck: [0, 1.3, 0], head: [-0.15, 0.5, 0.05], shR: [-0.95, 1.45, 0], elR: [-2.0, 1.4, 1.05], wrR: [-2.7, 1.38, 1.75], haR: [-3.2, 1.37, 2.25], shL: [0.95, 1.48, 0], elL: [1.12, 2.95, 0.1], wrL: [1.2, 3.95, 0.1], haL: [1.25, 4.7, 0.1], hipR: [-0.55, 3.95, 0], knR: [-0.75, 5.85, 0], anR: [-0.85, 7.7, 0], toR: [-1.05, 8.02, 0.1], hipL: [0.48, 3.95, 0], knL: [0.6, 5.85, 0], anL: [0.7, 7.7, 0], toL: [0.9, 8.02, 0.1] } },
  sword: { yaw: 50, prop: 'sword', dir: [0, -0.55, 0.84], pose: { pelvis: [0, 3.95, 0], chest: [0, 2.4, 0.05], neck: [0, 1.4, 0.1], head: [0, 0.6, 0.15], shR: [-0.9, 1.6, 0.15], elR: [-0.75, 2.95, 0.7], wrR: [-0.25, 3.05, 1.75], haR: [0, 2.95, 2.3], shL: [0.9, 1.6, 0.15], elL: [0.75, 3.0, 0.55], wrL: [0.2, 3.4, 1.3], haL: [0.04, 3.32, 1.78], hipR: [-0.45, 4.05, 0], knR: [-0.5, 5.9, 0.6], anR: [-0.5, 7.7, 0.7], toR: [-0.5, 8.02, 1.1], hipL: [0.45, 4.05, 0], knL: [0.5, 5.9, -0.3], anL: [0.5, 7.6, -0.9], toL: [0.5, 8.02, -0.6] } },
  swordUp: { yaw: 40, prop: 'sword', dir: [0.05, -0.72, -0.69], pose: { pelvis: [0, 3.95, 0], chest: [0, 2.4, 0], neck: [0, 1.4, 0.05], head: [0, 0.6, 0.12], shR: [-0.9, 1.55, 0.05], elR: [-0.7, 0.4, 0.75], wrR: [-0.15, -0.2, 0.3], haR: [0, -0.45, -0.25], shL: [0.9, 1.55, 0.05], elL: [0.75, 0.45, 0.65], wrL: [0.15, -0.1, 0.2], haL: [0.02, -0.25, -0.1], hipR: [-0.45, 4.05, 0], knR: [-0.55, 5.85, 0.8], anR: [-0.55, 7.7, 0.95], toR: [-0.55, 8.02, 1.35], hipL: [0.45, 4.05, 0], knL: [0.5, 5.9, -0.4], anL: [0.5, 7.6, -1.0], toL: [0.5, 8.02, -0.7] } },
};
export function poseFrom3D(T) {
  const P3 = BJ.map(n => T[n]);
  const abs = [], rel = [], f = [], z = [];
  for (let i = 0; i < BJ.length; i++) {
    const p = BPAR[i]; if (p < 0) { abs.push(-Math.PI / 2); rel.push(0); f.push(1); z.push(1); continue; }
    const d = [P3[i][0] - P3[p][0], P3[i][1] - P3[p][1], P3[i][2] - P3[p][2]], a = Math.atan2(d[1], d[0]);
    abs.push(a);
    let r = a - abs[p]; while (r > Math.PI) r -= TAU; while (r < -Math.PI) r += TAU;
    rel.push(Math.round(r / D2R * 10) / 10);
    f.push(Math.round(clamp(Math.hypot(d[0], d[1]) / (Math.hypot(d[0], d[1], d[2]) || 1), 0.05, 1) * 1000) / 1000);
    z.push(d[2] < 0 ? -1 : 1);
  }
  return { rel, f, z };
}
const poseByName = (v) => {
  if (BODY_POSES_3D[v]) { const q = poseFrom3D(BODY_POSES_3D[v].pose); if (BODY_POSES_3D[v].prop) { q.prop = BODY_POSES_3D[v].prop; q.propDir = BODY_POSES_3D[v].dir; } return q; }
  return PROFILE_POSES.has(v) ? poseFromProfile(BODY_POSES[v]) : poseFromTemplate(BODY_POSES[v] || BODY_POSES.stand);
};

// Поворот всей фигуры: вокруг вертикали (анфас → профиль → спина), к себе/от себя, наклон в листе.
// Координаты тела: x вправо, y вниз, z к зрителю.
function bodyRot(g) {
  const ya = (+P(g, 'yaw') || 0) * D2R, pi = (+P(g, 'pitch') || 0) * D2R, le = (+P(g, 'lean') || 0) * D2R;
  const [cy, sy, cp, sp, cl, sl] = [Math.cos(ya), Math.sin(ya), Math.cos(pi), Math.sin(pi), Math.cos(le), Math.sin(le)];
  const fwd = (v) => { let [x, y, z] = v; [x, z] = [x * cy + z * sy, -x * sy + z * cy]; [y, z] = [y * cp - z * sp, y * sp + z * cp]; [x, y] = [x * cl - y * sl, x * sl + y * cl]; return [x, y, z]; };
  const inv = (v) => { let [x, y, z] = v; [x, y] = [x * cl + y * sl, -x * sl + y * cl]; [y, z] = [y * cp + z * sp, -y * sp + z * cp]; [x, z] = [x * cy - z * sy, x * sy + z * cy]; return [x, y, z]; };
  return { fwd, inv, ya, pi };
}
// Прямая кинематика. Поза — относительные углы костей в «плоскости тела» + укорочение f и
// сторона глубины z (±1: кость идёт к зрителю или от него). Отсюда — 3D-точки, которые
// поворачиваем целиком и проецируем на лист.
function bodyFK(g) {
  const N = +P(g, 'heads') || 7.5, u = (+P(g, 'h') || 150) / N, Ls = boneLens(N, P(g, 'build'));
  const pose = (g.props && g.props.pose) || poseFromTemplate(BODY_POSES.stand);
  const zs = pose.z || [], Rb = bodyRot(g);
  const B = [], abs = [];
  for (let i = 0; i < BJ.length; i++) {
    const p = BPAR[i];
    if (p < 0) { B.push([0, 0, 0]); abs.push(-Math.PI / 2); continue; }
    const a = abs[p] + (pose.rel[i] || 0) * D2R;
    abs.push(a);
    const l = Ls[i] * u, f = clamp(pose.f[i] ?? 1, 0, 1), dz = (zs[i] || 1) * l * Math.sqrt(Math.max(0, 1 - f * f));
    B.push([B[p][0] + Math.cos(a) * l * f, B[p][1] + Math.sin(a) * l * f, B[p][2] + dz]);
  }
  const W = B.map(Rb.fwd), O = g.pts[0];
  const pos = W.map(q => ({ x: O.x + q[0], y: O.y + q[1] }));
  // видимое укорочение кости (для эллипсов-сечений)
  const fe = BJ.map((_, i) => { const p = BPAR[i]; if (p < 0) return 1; const l = Ls[i] * u || 1; return clamp(Math.hypot(W[i][0] - W[p][0], W[i][1] - W[p][1]) / l, 0, 1); });
  return { pos, abs, u, Ls, N, pose, B, W, fe, Rb };
}
// Смещение корня (таза) в головах шаблона → мм листа с учётом поворота фигуры (для анимаций)
export function bodyRootShift(g, off) {
  const N = +P(g, 'heads') || 7.5, u = (+P(g, 'h') || 150) / N, k = (N - 1) / 7, w = bodyRot(g).fwd([off[0] * u * k, off[1] * u * k, off[2] * u * k]);
  return { x: w[0], y: w[1] };
}
// контур «капсулы» между двумя кругами
function capsule(a, b, ra, rb) {
  const d = sub(b, a), L = len(d);
  if (L < 1e-6) { const pts = []; for (let i = 0; i < 24; i++) { const t = TAU * i / 24; pts.push({ x: a.x + Math.cos(t) * ra, y: a.y + Math.sin(t) * ra }); } return pts; }
  const u = mulS(d, 1 / L), n = perp(u), ang = Math.atan2(u.y, u.x);
  const sa = clamp((ra - rb) / L, -0.95, 0.95), off = Math.asin(sa);
  const pts = [];
  for (let i = 0; i <= 12; i++) { const t = ang + Math.PI / 2 + off + (Math.PI - 2 * off) * i / 12; pts.push({ x: a.x + Math.cos(t) * ra, y: a.y + Math.sin(t) * ra }); }
  for (let i = 0; i <= 12; i++) { const t = ang - Math.PI / 2 - off + (Math.PI + 2 * off) * i / 12; pts.push({ x: b.x + Math.cos(t) * rb, y: b.y + Math.sin(t) * rb }); }
  void n;
  return pts;
}
// Рисует манекен по позициям суставов. w — переопределение ширины груди/таза (для видов сбоку).
export function drawMannequin(pen, pos, u, opt = {}) {
  const J = (n) => pos[BJ.indexOf(n)];
  const main = opt.layer || 'main', fs = opt.f || [];
  const limb = (a, b, ra, rb, fi) => {
    pen.poly(capsule(J(a), J(b), ra * u, rb * u), true, main);
    const f = fs[BJ.indexOf(b)];
    if (f !== undefined && f < 0.96) { // сечение — показывает, что кость идёт «в глубину»
      const m = lerpP(J(a), J(b), 0.5), d = sub(J(b), J(a)), rm = (ra + rb) / 2 * u;
      pen.ellipse(m, rm, Math.max(0.3, rm * Math.sqrt(1 - f * f)), Math.atan2(d.y, d.x) + Math.PI / 2, 'aux');
    }
  };
  const joint = (n, r) => pen.circle(J(n), r * u, 'aux');
  // голова
  if (!opt.noHead) {
    const nh = sub(J('head'), J('neck')), a = Math.atan2(nh.y, nh.x) + Math.PI / 2;
    pen.ellipse(J('head'), 0.37 * u, 0.5 * u, a, main);
    const ax = { x: Math.cos(a), y: Math.sin(a) }, ay = { x: -Math.sin(a), y: Math.cos(a) };
    // центральная линия лица — дуга по «яйцу» головы: в повороте уходит вбок, со спины не видна
    const hy = opt.headYaw || 0, hp = opt.headPitch || 0;
    if (Math.cos(hy) > -0.05) { const cl = []; for (let k2 = 0; k2 <= 16; k2++) { const ph = -Math.PI / 2 + Math.PI * k2 / 16; cl.push(add(J('head'), add(mulS(ax, 0.37 * u * Math.sin(hy) * Math.cos(ph)), mulS(ay, 0.5 * u * Math.sin(ph))))); } pen.poly(cl, false, 'aux'); }
    // линия глаз — экватор, при наклоне к себе/от себя становится дугой
    { const el = []; for (let k2 = 0; k2 <= 16; k2++) { const t = -Math.PI / 2 + Math.PI * k2 / 16; el.push(add(J('head'), add(mulS(ax, 0.37 * u * Math.sin(t)), mulS(ay, 0.05 * u + 0.5 * u * Math.sin(hp) * Math.cos(t) * 0.6)))); } pen.poly(el, false, 'aux'); }
  }
  // шея
  { const hb = lerpP(J('neck'), J('head'), 0.45); pen.poly(capsule(J('neck'), hb, 0.15 * u, 0.13 * u), true, main); }
  // грудная клетка — «яйцо» между шеей и грудью; ширина — по плечам (поворот корпуса виден сразу)
  const spU = sub(J('neck'), J('chest')), spL = len(spU) || 1, ua = mulS(spU, 1 / spL), na = perp(ua);
  const shW = opt.chestW != null ? opt.chestW : Math.max(0.35 * u, dist(J('shL'), J('shR')) * 0.42);
  opt._shW = shW;
  { const c = lerpP(J('chest'), J('neck'), 0.42); pen.ellipse(c, Math.max(0.6 * u, spL * 0.72), shW, Math.atan2(ua.y, ua.x), main); }
  // таз — трапеция по тазовым точкам
  const pv = J('pelvis'), up2 = norm(sub(J('chest'), pv)), np = perp(up2);
  const hpW = opt.pelvisW != null ? opt.pelvisW : Math.max(0.3 * u, dist(J('hipL'), J('hipR')) * 0.75);
  { const top = add(pv, mulS(up2, 0.42 * u)), bot = add(pv, mulS(up2, -0.42 * u));
    const q = [add(top, mulS(np, hpW * 0.95)), add(top, mulS(np, -hpW * 0.95)), add(bot, mulS(np, -hpW * 0.55)), add(bot, mulS(np, hpW * 0.55))];
    pen.poly(spline([[q[0].x, q[0].y], [q[1].x, q[1].y], [q[2].x, q[2].y], [q[3].x, q[3].y], [q[0].x, q[0].y]].map(v => [...v, 0]), 4).map(v => ({ x: v[0], y: v[1] })), true, main); }
  // позвоночник и «живот»
  pen.poly([J('pelvis'), J('chest'), J('neck')], false, 'aux');
  { const c = lerpP(J('chest'), J('neck'), 0.42), bottomRib = add(c, mulS(ua, -Math.max(0.6 * u, spL * 0.72) * 0.85)), top = add(pv, mulS(up2, 0.42 * u));
    for (const s of [-1, 1]) pen.seg(add(bottomRib, mulS(na, s * shW * 0.55)), add(top, mulS(np, s * hpW * 0.85)), 'aux'); }
  if (opt.extra) opt.extra(pen, J, shW, hpW);
  // руки и ноги
  for (const s of ['R', 'L']) {
    joint('sh' + s, 0.16);
    limb('sh' + s, 'el' + s, 0.15, 0.11); joint('el' + s, 0.1);
    limb('el' + s, 'wr' + s, 0.11, 0.08);
    limb('wr' + s, 'ha' + s, 0.09, 0.11);
    joint('hip' + s, 0.2);
    limb('hip' + s, 'kn' + s, 0.24, 0.15); joint('kn' + s, 0.13);
    limb('kn' + s, 'an' + s, 0.15, 0.09);
    // стопа — клин
    const an = J('an' + s), to = J('to' + s), d = sub(to, an), L = len(d) || 1, uu = mulS(d, 1 / L), nn = perp(uu);
    const heel = add(an, mulS(uu, -0.22 * u));
    pen.poly([add(heel, mulS(nn, 0.1 * u)), add(an, mulS(nn, 0.12 * u)), add(to, mulS(nn, 0.06 * u)), add(to, mulS(nn, -0.06 * u)), add(an, mulS(nn, -0.12 * u)), add(heel, mulS(nn, -0.1 * u))], true, main);
  }
}

// Параметры отрисовки манекена в 3D: ширина груди/таза с учётом поворота, голова, грудь, анатомия.
function bodyDrawOpts(g, FK) {
  const { B, Rb, u, fe } = FK, idx = (n) => BJ.indexOf(n);
  const sub3 = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]], n3 = v3n, crs = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dt3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const O = g.pts[0], P2 = (q) => { const w = Rb.fwd(q); return { x: O.x + w[0], y: O.y + w[1], z: w[2] }; };
  // рамка корпуса в теле: верх (к шее), право-лево (по плечам), вперёд
  const up = n3(sub3(B[idx('neck')], B[idx('chest')])), side = n3(sub3(B[idx('shL')], B[idx('shR')]));
  let fw = n3(crs(side, up)); if (fw[2] < 0 && Math.abs(fw[2]) > 0.2) fw = fw.map(x => -x);
  const hipSide = n3(sub3(B[idx('hipL')], B[idx('hipR')])), upP = n3(sub3(B[idx('chest')], B[idx('pelvis')]));
  let fwP = n3(crs(hipSide, upP)); if (dt3(fwP, fw) < 0) fwP = fwP.map(x => -x);
  // полуширина сечения на экране поперёк оси: эллипс с полуосями W (вбок) и D (вперёд)
  const halfOn = (axis, sideV, fwdV, Wd, Dd) => {
    const a = Rb.fwd(axis), n2 = norm({ x: -a[1], y: a[0] }), s2 = Rb.fwd(sideV), f2 = Rb.fwd(fwdV);
    return Math.hypot(Wd * (s2[0] * n2.x + s2[1] * n2.y), Dd * (f2[0] * n2.x + f2[1] * n2.y));
  };
  const shD = Math.hypot(...sub3(B[idx('shL')], B[idx('shR')])), hpD = Math.hypot(...sub3(B[idx('hipL')], B[idx('hipR')]));
  const build = P(g, 'build');
  const chestW = Math.max(0.3 * u, halfOn(up, side, fw, shD * 0.42, 0.5 * u));
  const pelvisW = Math.max(0.28 * u, halfOn(upP, hipSide, fwP, hpD * 0.75, 0.45 * u));
  let bust = P(g, 'bust'); if (bust === 'auto') bust = build === 'female' ? 'm' : build === 'hero' ? 'pecs' : 'none';
  const view = Rb.inv([0, 0, 1]); // направление на зрителя в координатах тела
  const yawH = Math.atan2(dt3(view, side.map(x => -x)), dt3(view, fw)), pitchH = Math.asin(clamp(dt3(view, up), -1, 1));
  const anat = P(g, 'anat');
  const extra = (pen, J) => {
    const C0 = B[idx('chest')], Nk = B[idx('neck')];
    const at = (k, s2, f2, base = C0) => [base[0] + up[0] * k + side[0] * s2 + fw[0] * f2, base[1] + up[1] * k + side[1] * s2 + fw[1] * f2, base[2] + up[2] * k + side[2] * s2 + fw[2] * f2];
    const vis = (n) => dt3(n, view) > 0.02;
    const spl = (L3, layer, fromBase) => { const pts = spline(L3, 6).map(P2); pen.poly(pts, false, layer); void fromBase; };
    const spL = Math.hypot(...sub3(Nk, C0)) || u, half = shD * 0.42;
    if (anat && vis(fw)) {
      // ключицы: от ямки шеи к плечам, лёгкая «V»
      const notch = at(spL * 0.86, 0, 0.32 * u);
      for (const sg of [-1, 1]) spl([notch, at(spL * 0.9, sg * half * 0.45, 0.36 * u), at(spL * 0.96, sg * half * 0.92, 0.18 * u)], 'aux');
      // грудина и нижний край рёбер (арка)
      spl([notch, at(spL * 0.35, 0, 0.5 * u), at(spL * 0.05, 0, 0.48 * u)], 'aux');
      const arch = []; for (let k = -6; k <= 6; k++) { const t = k / 6; arch.push(at(-spL * 0.1 + spL * 0.22 * (1 - Math.abs(t)), t * half * 0.8, 0.46 * u * Math.sqrt(1 - 0.5 * t * t))); }
      pen.poly(spline(arch, 3).map(P2), false, 'aux');
      // пупок
      const nav = [lerp(C0[0], B[idx('pelvis')][0], 0.55) + fwP[0] * 0.42 * u, lerp(C0[1], B[idx('pelvis')][1], 0.55) + fwP[1] * 0.42 * u, lerp(C0[2], B[idx('pelvis')][2], 0.55) + fwP[2] * 0.42 * u];
      pen.circle(P2(nav), 0.035 * u, 'aux');
    }
    if (bust === 'pecs' && vis(fw)) {
      for (const sg of [-1, 1]) spl([at(spL * 0.72, sg * 0.04 * u, 0.5 * u), at(spL * 0.34, sg * half * 0.3, 0.56 * u), at(spL * 0.3, sg * half * 0.72, 0.42 * u), at(spL * 0.62, sg * half * 0.9, 0.3 * u)], 'aux');
    } else if ((bust === 's' || bust === 'm' || bust === 'l') && dt3(fw, view) > -0.35) {
      // грудь — два шара, чуть разведённые в стороны и опущенные; нижний контур — основная линия
      const rb = u * (bust === 's' ? 0.17 : bust === 'm' ? 0.22 : 0.28), lift = bust === 'l' ? 0.08 : 0.0;
      for (const sg of [-1, 1]) {
        const ctr = at(spL * (0.32 - lift), sg * half * 0.44, 0.42 * u + rb * 0.35);
        const out = n3([fw[0] + side[0] * sg * 0.35 - up[0] * 0.15, fw[1] + side[1] * sg * 0.35 - up[1] * 0.15, fw[2] + side[2] * sg * 0.35 - up[2] * 0.15]);
        const c2 = P2(ctr);
        pen.circle(c2, rb, 'aux');
        // нижний контур груди (складка) — дуга по сфере снизу, видимая часть
        const low = []; for (let k = 0; k <= 18; k++) { const t = Math.PI * (0.05 + 0.9 * k / 18); const d = [-up[0] * Math.sin(t) + side[0] * Math.cos(t), -up[1] * Math.sin(t) + side[1] * Math.cos(t), -up[2] * Math.sin(t) + side[2] * Math.cos(t)]; const q = [ctr[0] + d[0] * rb, ctr[1] + d[1] * rb, ctr[2] + d[2] * rb]; low.push(P2(q)); }
        pen.poly(low, false, 'main');
        // верхний скат — от подмышки/ключицы к шару
        spl([at(spL * 0.82, sg * half * 0.55, 0.3 * u), at(spL * 0.55, sg * half * 0.5, 0.45 * u + rb * 0.25), [ctr[0] + up[0] * rb * 0.6 + fw[0] * rb * 0.75, ctr[1] + up[1] * rb * 0.6 + fw[1] * rb * 0.75, ctr[2] + up[2] * rb * 0.6 + fw[2] * rb * 0.75]], 'aux');
        // сосок — по направлению «out», если смотрит к нам
        if (vis(out)) pen.circle(P2([ctr[0] + out[0] * rb, ctr[1] + out[1] * rb, ctr[2] + out[2] * rb]), 0.03 * u, 'aux');
      }
    }
  };
  return { f: fe, chestW, pelvisW, headYaw: yawH, headPitch: pitchH, extra };
}

// Предмет в руках. Меч: рукоять между кистями (если они рядом) — клинок продолжает её от
// передней руки; иначе — по направлению кисти. Пистолет — по кисти. Всё в 3D, крутится с фигурой.
function drawProp(pen, g, FK) {
  const sel = P(g, 'prop') || 'pose', kind = sel === 'pose' ? (FK.pose.prop || 'none') : sel;
  if (kind === 'none') return;
  const { W, u } = FK, O = g.pts[0], P2 = (q) => ({ x: O.x + q[0], y: O.y + q[1] });
  const iR = BJ.indexOf('haR'), iL = BJ.indexOf('haL'), wR = W[BJ.indexOf('wrR')];
  const hR = W[iR], hL = W[iL], sub3 = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const nrm = (v) => { const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; };
  const at = (b, d, k) => [b[0] + d[0] * k, b[1] + d[1] * k, b[2] + d[2] * k];
  const twoHands = Math.hypot(...sub3(hR, hL)) < 0.9 * u;
  // направление: от задней кисти к передней (обе на рукояти) или по кисти правой руки
  // направление предмета задано позой (в осях тела — крутится вместе с фигурой); если предмет
  // выбран вручную — продолжаем кисть
  let dir = FK.pose.propDir ? nrm(FK.Rb.fwd(FK.pose.propDir)) : nrm(sub3(hR, wR));
  const grip = twoHands && kind !== 'gun' ? [(hR[0] + hL[0]) / 2, (hR[1] + hL[1]) / 2, (hR[2] + hL[2]) / 2] : hR;
  // поперечное направление (для ширины клинка/гарды): перпендикуляр к dir в плоскости экрана
  const sd = Math.hypot(dir[0], dir[1]) > 0.05 ? [-dir[1], dir[0], 0] : [1, 0, 0], sn = nrm(sd);
  if (kind === 'sword' || kind === 'staff') {
    const back = kind === 'staff' ? 2.2 : 0.45, fwd = kind === 'staff' ? 2.6 : 0.25;
    const pommel = at(grip, dir, -back * u), guard = at(grip, dir, fwd * u);
    pen.seg(P2(pommel), P2(guard), 'main');
    if (kind === 'sword') {
      const tip = at(guard, dir, 3.1 * u), wb = 0.06 * u;
      pen.seg(P2(at(guard, sn, -0.28 * u)), P2(at(guard, sn, 0.28 * u)), 'main');           // гарда
      pen.poly([P2(at(guard, sn, -wb)), P2(at(at(tip, dir, -0.35 * u), sn, -wb)), P2(tip), P2(at(at(tip, dir, -0.35 * u), sn, wb)), P2(at(guard, sn, wb))], false, 'main');
      pen.seg(P2(guard), P2(at(tip, dir, -0.3 * u)), 'aux');                                 // дол
    } else pen.seg(P2(guard), P2(at(guard, dir, 2.0 * u)), 'main');
  } else if (kind === 'gun') {
    // ствол вперёд по кисти, рукоять вниз от кисти (вниз — перпендикуляр к стволу к «низу» мира)
    const down0 = [0, 1, 0], dd = dir[1], dn = nrm([down0[0] - dir[0] * dd, down0[1] - dir[1] * dd, down0[2] - dir[2] * dd]);
    const b0 = at(hR, dir, -0.1 * u), b1 = at(hR, dir, 0.75 * u), hh = 0.16 * u;
    pen.poly([P2(b0), P2(b1), P2(at(b1, dn, hh)), P2(at(b0, dn, hh))], true, 'main');
    pen.poly([P2(at(b0, dn, hh)), P2(at(at(b0, dn, 0.55 * u), dir, -0.12 * u)), P2(at(at(b0, dn, 0.55 * u), dir, 0.14 * u)), P2(at(at(b0, dir, 0.25 * u), dn, hh))], false, 'main');
  }
}

const body = {
  name: 'Манекен', icon: '🕺', group: 'manga',
  desc: 'Шарнирный манекен в 3D: тяни за суставы — кости поворачиваются, дочерние части идут следом; ближе — кость уходит на тебя/от тебя. Позы: стоит, идёт, бежит, сидит, на корточках, по-турецки, обняв колени, прыжок, падение, стойка, с мечом, стрельба. «В руках» — меч, пистолет или шест: идут за кистями. Поверни всю фигуру (вокруг себя, к себе, в листе) — например, «обняв колени» + наклон 90° = свернулся калачиком лёжа. Рост — за ручку над головой',
  create: (c, s) => [{ x: c.x, y: c.y + s * 0.35 }],
  init: (g, s, dims) => { g.props.h = Math.round(Math.min(dims.H * 0.82, s * 3.2)); g.props.pose = poseFromTemplate(BODY_POSES.stand); g.pts[0] = { x: dims.W / 2, y: dims.H / 2 + g.props.h * (3.9 / 7.5 - 0.5) }; },
  props: [
    { key: 'posePreset', label: 'Поза', type: 'select', options: [['stand', 'Стоит'], ['contra', 'Контрапост'], ['walk', 'Идёт'], ['run', 'Бежит'], ['sit', 'Сидит на стуле'], ['squat', 'На корточках'], ['cross', 'Сидит по-турецки (калачиком)'], ['hug', 'Сидит, обняв колени'], ['jump', 'Прыжок'], ['fall', 'Падает'], ['fight', 'Стойка (кулаки)'], ['sword', 'С мечом (стойка)'], ['swordUp', 'Меч над головой'], ['shoot', 'Стреляет (двумя руками)'], ['shoot1', 'Стреляет (одной рукой)']], def: 'stand', onSet: (g, v) => { const m = BODY_POSES_3D[v]; g.props.pose = poseByName(v); g.props.yaw = m ? (m.yaw || 0) : PROFILE_POSES.has(v) ? 90 : 0; g.props.pitch = m ? (m.pitch || 0) : 0; g.props.lean = 0; } },
    { key: 'prop', label: 'В руках', type: 'select', options: [['pose', 'По позе'], ['none', 'Ничего'], ['sword', 'Меч'], ['gun', 'Пистолет'], ['staff', 'Шест / копьё']], def: 'pose' },
    { key: 'heads', label: 'Рост в головах', type: 'range', min: 2, max: 9, step: 0.5, def: 7.5 },
    { key: 'build', label: 'Телосложение', type: 'select', options: [['neutral', 'Обычное'], ['female', 'Женское'], ['hero', 'Атлет'], ['child', 'Ребёнок']], def: 'neutral' },
    sec('Поворот фигуры'),
    { key: 'yaw', label: 'Вокруг себя: анфас → профиль → спина, °', type: 'range', min: -180, max: 180, step: 5, def: 0 },
    { key: 'pitch', label: 'Наклон к себе / от себя, °', type: 'range', min: -90, max: 90, step: 5, def: 0 },
    { key: 'lean', label: 'Наклон в листе, °', type: 'range', min: -180, max: 180, step: 1, def: 0 },
    sec('Тело'),
    { key: 'bust', label: 'Грудь', type: 'select', options: [['auto', 'По телосложению'], ['none', 'Не показывать'], ['pecs', 'Грудные мышцы'], ['s', 'Маленькая'], ['m', 'Средняя'], ['l', 'Большая']], def: 'auto' },
    { key: 'anat', label: 'Анатомия торса (ключицы, рёбра, пупок)', type: 'toggle', def: true },
    { key: 'ruler', label: 'Линейка «в головах» сбоку', type: 'toggle', def: true },
    { key: 'plumb', label: 'Линия равновесия (отвес от шеи)', type: 'toggle', def: false },
    { key: 'h', label: 'Рост, мм', type: 'range', min: 20, max: 420, step: 1, def: 150 },
  ],
  moveIdx: 0,
  actions: [
    ['⇋ Отразить позу', (g) => { const pose = g.props.pose || poseFromTemplate(BODY_POSES.stand); const rel = pose.rel.slice(), f = pose.f.slice(), z = (pose.z || []).slice(); while (z.length < BJ.length) z.push(1); const sw = [[4, 8], [5, 9], [6, 10], [7, 11], [12, 16], [13, 17], [14, 18], [15, 19]]; for (const [a, b] of sw) { [rel[a], rel[b]] = [rel[b], rel[a]]; [f[a], f[b]] = [f[b], f[a]]; [z[a], z[b]] = [z[b], z[a]]; } g.props.pose = { rel: rel.map(x => -x), f, z, prop: pose.prop, propDir: pose.propDir ? [-pose.propDir[0], pose.propDir[1], pose.propDir[2]] : undefined }; g.props.lean = -(+P(g, 'lean') || 0); g.props.yaw = -(+P(g, 'yaw') || 0); }],
    ['↻ Профиль', (g) => { const y = +P(g, 'yaw') || 0; g.props.yaw = Math.abs(y - 90) < 5 ? 0 : 90; }],
    ['⟲ Со спины', (g) => { const y = +P(g, 'yaw') || 0; g.props.yaw = Math.abs(Math.abs(y) - 180) < 5 ? 0 : 180; }],
    ['◩ 3/4', (g) => { g.props.yaw = 35; }],
  ],
  draw(pen, g, ctx) {
    const FK = bodyFK(g), { pos, u, N } = FK;
    drawMannequin(pen, pos, u, bodyDrawOpts(g, FK));
    drawProp(pen, g, FK);
    const top = this.handles(g)[20];
    if (P(g, 'ruler')) {
      const xs = Math.min(...pos.map(p => p.x)) - 0.9 * u, yTop = top.y + 0.0, ys = [];
      // от макушки вниз N голов
      const head = pos[3], yt = head.y - 0.5 * u;
      for (let k = 0; k <= Math.ceil(N); k++) ys.push(yt + Math.min(k, N) * u);
      pen.seg({ x: xs, y: yt }, { x: xs, y: yt + N * u }, 'aux');
      ys.forEach((y, k) => { pen.seg({ x: xs - 0.15 * u, y }, { x: xs + 0.15 * u, y }, 'aux'); if (ctx.labels && k < N) pen.label({ x: xs - 0.45 * u, y: y + u / 2 }, String(k + 1)); });
      void yTop;
    }
    if (P(g, 'plumb')) { const n = pos[2]; pen.seg(n, { x: n.x, y: Math.max(...pos.map(p => p.y)) + 0.3 * u }, 'ghost'); }
    if (ctx.labels) pen.label({ x: pos[0].x, y: Math.max(...pos.map(p => p.y)) + 0.6 * u }, `${N} голов · голова ${Math.round(u)} мм`);
  },
  handles(g) {
    const { pos, B, Rb, u, abs } = bodyFK(g);
    const a = abs[3], t3 = Rb.fwd([B[3][0] + Math.cos(a) * 0.95 * u, B[3][1] + Math.sin(a) * 0.95 * u, B[3][2]]);
    const top = { x: g.pts[0].x + t3[0], y: g.pts[0].y + t3[1] };
    return [...pos.map(p => ({ x: p.x, y: p.y })), top];
  },
  drag(g, i, p) {
    if (i === 0) { g.pts[0] = p; return; }
    const { pos, abs, u, Ls, W, Rb } = bodyFK(g);
    if (i === 20) { // рост
      const top0 = this.handles(g)[20], d0 = dist(top0, pos[0]) || 1;
      g.props.h = clamp(Math.round((+P(g, 'h')) * dist(p, pos[0]) / d0), 15, 600);
      return;
    }
    // экранное смещение → 3D-кость (глубину сохраняем с той же стороны) → обратно в «плоскость тела»
    const par = BPAR[i], L = Ls[i] * u || 1;
    let v = sub(p, pos[par]); const lv = len(v); if (lv > L) v = mulS(v, L / lv);
    const w0z = W[i][2] - W[par][2], wz = (w0z < 0 ? -1 : 1) * Math.sqrt(Math.max(0, L * L - v.x * v.x - v.y * v.y));
    const b = Rb.inv([v.x, v.y, wz]);
    const pose = g.props.pose = g.props.pose || poseFromTemplate(BODY_POSES.stand);
    if (!pose.z) pose.z = BJ.map(() => 1);
    let r = Math.atan2(b[1], b[0]) - abs[par]; while (r > Math.PI) r -= TAU; while (r < -Math.PI) r += TAU;
    pose.rel[i] = Math.round(r / D2R * 100) / 100;
    pose.f[i] = Math.round(clamp(Math.hypot(b[0], b[1]) / L, 0.12, 1) * 10000) / 10000;
    pose.z[i] = b[2] < 0 ? -1 : 1;
  },
  handleLabel: (g, i) => (i === 20 ? 'рост' : BJ_RU[i]),
};

// ======================================================================
// 3. РУКА с пальцами (3D)
// ======================================================================
// Ладонь в своей системе: x — поперёк (к большому пальцу +), y — к пальцам, z — из ладони.
// Единица — длина ладони (от запястья до костяшки среднего пальца).
// Каждый палец сгибается по трём суставам одним параметром «сгиб» (как в жизни — суставы
// сгибаются вместе), плюс общий «разворот» пальцев. Большой палец — отведение + сгиб.
const FING = [ // [x, y основания, длины фаланг, радиус, развод °]
  { name: 'большой', base: [0.36, 0.22], len: [0.42, 0.32, 0.27], r: 0.1 },
  { name: 'указательный', base: [0.36, 0.98], len: [0.45, 0.27, 0.2], r: 0.085, splay: 7 },
  { name: 'средний', base: [0.12, 1.0], len: [0.5, 0.3, 0.21], r: 0.088, splay: 1 },
  { name: 'безымянный', base: [-0.12, 0.97], len: [0.47, 0.28, 0.2], r: 0.082, splay: -5 },
  { name: 'мизинец', base: [-0.34, 0.88], len: [0.36, 0.21, 0.18], r: 0.07, splay: -11 },
];
// Сгиб пальцев (большой — отдельно, см. TH). Большой палец задан четырьмя углами:
// abd — отведение в плоскости ладони (0 — вдоль пальцев, 90 — под прямым углом к ним),
// opp — вперёд, над ладонью (противопоставление), f1 — сгиб среднего сустава (у основания
// фаланги), f2 — сгиб кончика; минус — переразгиб (как у «класса»).
export const HAND_POSES = {
  open: [0, 0, 0, 0, 0], relaxed: [0.25, 0.3, 0.4, 0.5, 0.6], fist: [1.0, 1.55, 1.55, 1.55, 1.55], point: [0.9, 0, 1.5, 1.5, 1.5],
  peace: [0.9, 0, 0, 1.5, 1.5], ok: [0.58, 1.06, 0.15, 0.2, 0.25], grab: [0.45, 0.8, 0.8, 0.8, 0.8], thumbs: [0, 1.55, 1.55, 1.55, 1.55],
  gun: [0, 0, 1.55, 1.55, 1.55], rock: [0.9, 0, 1.5, 1.5, 0], call: [0, 1.55, 1.55, 1.55, 0], cross: [0.9, 0.05, 0.05, 1.5, 1.5],
  pen: [0, 0.55, 0.75, 1.2, 1.35], pinch: [0, 0.95, 0.4, 0.5, 0.6], claw: [0, 1.0, 1.0, 1.0, 1.0],
};
const TH = { // большой палец для жестов (если не задан — из сгиба)
  thumbs: { abd: 80, opp: 14, f1: 20, f2: -32 }, gun: { abd: 78, opp: 10, f1: -5, f2: -12 }, call: { abd: 82, opp: 12, f1: 0, f2: -20 },
  pen: { abd: 42, opp: 50, f1: 18, f2: 10 }, pinch: { abd: 30, opp: 48, f1: 22, f2: 30 }, claw: { abd: 55, opp: 40, f1: 25, f2: 40 },
  open: { abd: 50, opp: 8, f1: 0, f2: -5 },
};
// Скрещенные пальцы: указательный уходит к среднему, средний ложится сверху (развод °, подъём)
const SPL = { cross: [0, [-12, 0], [15, 0.16], 0, 0] };
const THUMB_PRON = 70;
const thumbKnot = (u) => { const K = [[-0.3, 46, 6], [0, 40, 15], [0.7, 14, 52], [1.0, -20, 52], [1.3, -38, 44]]; for (let q = 1; q < K.length; q++) if (u <= K[q][0]) { const t = (u - K[q - 1][0]) / (K[q][0] - K[q - 1][0]); return [lerp(K[q - 1][1], K[q][1], t), lerp(K[q - 1][2], K[q][2], t)]; } return [K[4][1], K[4][2]]; };
// старый «сгиб большого пальца» → четыре угла (две фазы: противопоставление, потом приведение в кулак)
export function thumbFromCurl(c) {
  const cc = clamp(c, -0.3, 1.3), [bd, od] = thumbKnot(cc);
  return { abd: Math.round(bd), opp: Math.round(od), f1: Math.round(24 * c), f2: Math.round(34 * c) };
}
const rodr = (v, k, a) => { // поворот v вокруг оси k (единичной) на угол a
  const c = Math.cos(a), s = Math.sin(a), d = v[0] * k[0] + v[1] * k[1] + v[2] * k[2];
  const cr = [k[1] * v[2] - k[2] * v[1], k[2] * v[0] - k[0] * v[2], k[0] * v[1] - k[1] * v[0]];
  return [v[0] * c + cr[0] * s + k[0] * d * (1 - c), v[1] * c + cr[1] * s + k[1] * d * (1 - c), v[2] * c + cr[2] * s + k[2] * d * (1 - c)];
};
function thumbChain(th, sx) {
  const F = FING[0], base = [F.base[0] * sx, F.base[1], 0], pts = [base];
  const b = th.abd * D2R * sx, o = th.opp * D2R;
  let dir = v3n([Math.sin(b) * Math.cos(o), Math.cos(b) * Math.cos(o), Math.sin(o)]);
  // Подушечка в покое смотрит поперёк ладони (к мизинцу и чуть вперёд); при противопоставлении
  // пястная кость проворачивается — подушечка разворачивается к остальным пальцам.
  // Суставы сгибаются в сторону подушечки.
  const pr0 = [-sx * 0.75, 0.05, 0.65], dp = pr0[0] * dir[0] + pr0[1] * dir[1] + pr0[2] * dir[2];
  let pad = v3n([pr0[0] - dp * dir[0], pr0[1] - dp * dir[1], pr0[2] - dp * dir[2]]);
  pad = rodr(pad, dir, -sx * THUMB_PRON * D2R * clamp(th.opp / 55, 0, 1));
  const k = v3n([dir[1] * pad[2] - dir[2] * pad[1], dir[2] * pad[0] - dir[0] * pad[2], dir[0] * pad[1] - dir[1] * pad[0]]);
  const angs = [0, th.f1 * D2R, th.f2 * D2R];
  let p = base;
  F.len.forEach((l, j) => { if (j) dir = rodr(dir, k, angs[j]); p = [p[0] + dir[0] * l, p[1] + dir[1] * l, p[2] + dir[2] * l]; pts.push(p); });
  return pts;
}
// th — большой палец {abd, opp, f1, f2}; spl — для скрещивания пальцев [[развод°, подъём], …]
function handModel(curl, spread, mirror, th, spl) {
  const sx = mirror ? -1 : 1, fingers = [];
  th = th || thumbFromCurl(curl[0] || 0);
  FING.forEach((F, fi) => {
    if (fi === 0) { fingers.push({ pts: thumbChain(th, sx), r: F.r }); return; }
    const c = curl[fi] || 0, ex = (spl && spl[fi]) || [0, 0];
    const base = [F.base[0] * sx, F.base[1], 0];
    const pts = [base];
    const spl0 = ((F.splay || 0) * (1 + 1.6 * spread) + (ex[0] || 0)) * D2R * sx;
    let dir = v3n([Math.sin(spl0), Math.cos(spl0), -(ex[1] || 0)]);
    const side = v3n([dir[1], -dir[0], 0]); // ось сгиба — поперёк пальца; поворот вокруг неё ведёт к ладони (+z)
    const angs = [0.85 * c, 1.1 * c, 0.75 * c];
    let p = base;
    F.len.forEach((l, j) => { dir = rodr(dir, side, angs[j]); p = [p[0] + dir[0] * l, p[1] + dir[1] * l, p[2] + dir[2] * l]; pts.push(p); });
    fingers.push({ pts, r: F.r, lift: ex[1] || 0 });
  });
  const palm = [[0.32, 0, 0], [0.5, 0.35, 0.02], [0.44, 0.98, 0], [0.12, 1.04, 0], [-0.12, 1.0, 0], [-0.4, 0.9, 0], [-0.44, 0.45, 0], [-0.3, 0, 0]].map(p => [p[0] * sx, p[1], p[2]]);
  return { fingers, palm, sx };
}
function handView(g) {
  const C = g.pts[0], s = +P(g, 'size') || 40;
  const yaw = (+P(g, 'turn') || 0) * D2R, pitch = (+P(g, 'tilt') || 0) * D2R, roll = (+P(g, 'rot') || 0) * D2R;
  return { V: view3(C, s, yaw, pitch, roll), C, s, yaw, pitch, roll };
}
// Две руки: у каждой — своё положение o и поворот r (в осях пары), сгиб, большой палец
const HP = (curl, th, o, r, spl) => ({ curl, th, o, r, spl });
// Хват двумя руками: обе кисти на одной оси (рукоять меча, пистолета). Ось кольца пальцев
// в кулаке идёт поперёк ладони (от большого пальца к мизинцу). Ладони смотрят в разные стороны
// (как на бите): левая повёрнута на 180° вокруг оси пальцев.
const RING = [0, 0.93, 0.3];
function gripPair(rR, curlR, curlL, thR, thL, gap, shiftL = [0, 0, 0]) {
  const RR = rotator(rR[0] * D2R, rR[1] * D2R, rR[2] * D2R), rL = [rR[0] + 180, rR[1], rR[2]], RL = rotator(rL[0] * D2R, rL[1] * D2R, rL[2] * D2R);
  const T = RR([1, 0, 0]), F = RR([0, 1, 0]), cR = RR(RING), cL = RL(RING);
  const oR = [-cR[0] + T[0] * gap / 2, -cR[1] + T[1] * gap / 2, -cR[2] + T[2] * gap / 2];
  const oL = [-cL[0] - T[0] * gap / 2 + shiftL[0], -cL[1] - T[1] * gap / 2 + shiftL[1], -cL[2] - T[2] * gap / 2 + shiftL[2]];
  return { R: HP(curlR, thR, oR, rR), L: HP(curlL, thL, oL, rL), axis: { T, F } };
}
function heartPair() { // кончики указательных сходятся сверху, большие пальцы — снизу
  const curl = [0, 1.0, 1.08, 1.16, 1.24], th = { abd: 88, opp: 25, f1: 0, f2: -5 }, rR = [30, 0, 44];
  const RR = rotator(rR[0] * D2R, rR[1] * D2R, rR[2] * D2R), M = handModel(curl, -0.3, false, th);
  const tip = (fi) => RR(M.fingers[fi].pts[M.fingers[fi].pts.length - 1]);
  const ti = tip(1), tt = tip(0), ox = -(ti[0] + tt[0]) / 2 - 0.03, oz = -(ti[2] + tt[2]) / 2;
  return { R: HP(curl, th, [ox, 0, oz], rR), L: HP(curl, th, [-ox, 0, oz], [-rR[0], rR[1], -rR[2]]) };
}
export const PAIR_POSES = {
  both: { R: HP(HAND_POSES.relaxed, null, [-1.1, 0, 0], [0, 0, 8]), L: HP(HAND_POSES.relaxed, null, [1.1, 0, 0], [0, 0, -8]) },
  pray: { R: HP([0, 0.04, 0.04, 0.04, 0.04], { abd: 14, opp: 4, f1: 4, f2: 0 }, [-0.12, 0, 0], [90, 0, 0]), L: HP([0, 0.04, 0.04, 0.04, 0.04], { abd: 14, opp: 4, f1: 4, f2: 0 }, [0.12, 0, 0], [-90, 0, 0]), view: { turn: 30, tilt: 0 } },
  heart: heartPair(),
  sword: { ...gripPair([180, 0, 120], HAND_POSES.fist, HAND_POSES.fist, null, null, 1.0), prop: 'sword' },
  pistol: { ...gripPair([180, 0, 90], [0, 0.3, 1.55, 1.55, 1.55], [0, 1.35, 1.35, 1.35, 1.35], { abd: 30, opp: 35, f1: 15, f2: 10 }, { abd: 35, opp: 40, f1: 15, f2: 10 }, 0.7, [0, 0, 0]), prop: 'gun' },
  interlace: { R: HP([0, 1.45, 1.45, 1.45, 1.45], { abd: 30, opp: 10, f1: 0, f2: 0 }, [-0.14, 0, 0.05], [90, 0, 0]), L: HP([0, 1.45, 1.45, 1.45, 1.45], { abd: 30, opp: 10, f1: 0, f2: 0 }, [0.14, 0.03, -0.05], [-90, 0, 0]), view: { turn: 25, tilt: 20 } },
  salute: { R: HP(HAND_POSES.fist, null, [-0.45, 0.15, 0], [90, 0, 0]), L: HP([0, 0, 0, 0, 0], { abd: 20, opp: 5, f1: 0, f2: 0 }, [0.08, -0.1, 0], [-90, 0, 0]), view: { turn: 35, tilt: 0 } },
  frame: { R: HP([0, 0, 1.55, 1.55, 1.55], { abd: 88, opp: 5, f1: 0, f2: -8 }, [-1.46, -1.5, 0], [0, 0, 0]), L: HP([0, 0, 1.55, 1.55, 1.55], { abd: 88, opp: 5, f1: 0, f2: -8 }, [1.46, 1.5, 0], [180, 0, 180]) },
};
const PAIR_OPTIONS = [['both', 'Две руки'], ['pray', 'Молится'], ['heart', 'Сердечко'], ['sword', 'Держит меч'], ['pistol', 'Пистолет двумя руками'], ['interlace', 'Сцепленные пальцы'], ['salute', 'Кулак в ладонь'], ['frame', 'Рамка из пальцев']];
const clone = (o) => JSON.parse(JSON.stringify(o));
function pairOf(g) {
  if (!g.props.pair) g.props.pair = clone(PAIR_POSES.both);
  return g.props.pair;
}
const thumbOf = (g) => (P(g, 'tAbd') !== undefined && g.props.tAbd !== undefined ? { abd: +g.props.tAbd, opp: +P(g, 'tOpp'), f1: +P(g, 'tF1'), f2: +P(g, 'tF2') } : thumbFromCurl(((g.props && g.props.curl) || HAND_POSES.relaxed)[0]));
// все кисти фигуры: [{ M, map(p3) → экран, z(p3), side }]
function handsOf(g) {
  const { V, s } = handView(g);
  if (P(g, 'side') !== 'both') {
    const M = handModel((g.props && g.props.curl) || HAND_POSES.relaxed, +P(g, 'spread') || 0, P(g, 'side') === 'L', thumbOf(g), g.props.spl);
    return [{ M, pr: (p) => V.pr(p), nz: (n) => V.vis(n), s, side: P(g, 'side') === 'L' ? 'L' : 'R' }];
  }
  const pair = pairOf(g);
  return ['R', 'L'].map((sd) => {
    const h = pair[sd], Rl = rotator((h.r[0] || 0) * D2R, (h.r[1] || 0) * D2R, (h.r[2] || 0) * D2R);
    const M = handModel(h.curl, 0, sd === 'L', h.th || null, h.spl);
    const loc = (p) => { const q = Rl(p); return [q[0] + h.o[0], q[1] + h.o[1], q[2] + h.o[2]]; };
    return { M, pr: (p) => V.pr(loc(p)), nz: (n) => V.vis(Rl(n)), s, side: sd, loc };
  });
}
function drawHandModel(pen, H, joints, labels) {
  const { M: Mh, pr: PR, nz, s } = H, sx = Mh.sx;
  const palmFront = nz([0, 0, 1]) > 0; // видим ладонь (иначе — тыльную сторону)
  pen.poly(Mh.palm.map(PR), true, 'main');
  if (joints && palmFront) {
    pen.poly(spline([[0.5, 0.62, 0], [0.1, 0.72, 0], [-0.42, 0.66, 0]].map(p => [p[0] * sx, p[1], p[2]]), 6).map(PR), false, 'aux');
    pen.poly(spline([[0.42, 0.95, 0], [0.12, 0.45, 0], [0.15, 0.08, 0]].map(p => [p[0] * sx, p[1], p[2]]), 6).map(PR), false, 'aux');
  }
  Mh.fingers.forEach((F, fi) => {
    const pr = F.pts.map(PR);
    for (let j = 0; j < pr.length - 1; j++) {
      const ra = F.r * s * (1 - 0.1 * j), rb = F.r * s * (0.9 - 0.1 * j);
      pen.poly(capsule(pr[j], pr[j + 1], ra, rb), true, j === 0 && fi > 0 ? 'aux' : 'main');
    }
    if (joints) for (let j = 1; j < pr.length - 1; j++) pen.circle(pr[j], F.r * s * 0.35, 'aux');
    if (!palmFront) { // ноготь — если видна тыльная сторона
      const a = F.pts[F.pts.length - 2], b = F.pts[F.pts.length - 1];
      const m = [lerp(a[0], b[0], 0.62), lerp(a[1], b[1], 0.62), lerp(a[2], b[2], 0.62) - F.r * 0.6];
      const mp = PR(m), d = sub(pr[pr.length - 1], pr[pr.length - 2]);
      pen.ellipse(mp, F.r * s * 0.55, Math.max(0.3, len(d) * 0.28), Math.atan2(d.y, d.x) + Math.PI / 2, 'aux');
    }
  });
  // запястье
  const w0 = PR([0.32 * sx, 0, 0]), w1 = PR([-0.3 * sx, 0, 0]);
  const dd = sub(PR([0, -0.45, 0]), PR([0, 0, 0]));
  pen.seg(w0, add(w0, dd), 'aux'); pen.seg(w1, add(w1, dd), 'aux');
  if (labels) pen.label(PR([0, -0.7, 0]), `${H.side === 'L' ? 'левая' : 'правая'} · ${palmFront ? 'ладонь' : 'тыльная сторона'}`);
}
const tipOf = (H, fi) => H.pr(H.M.fingers[fi].pts[H.M.fingers[fi].pts.length - 1]);
const hand = {
  name: 'Рука', icon: '✋', group: 'manga',
  desc: 'Кисть с пальцами в 3D — одна или обе руки. Тяни за кончик пальца — палец сгибается (большой — ходит во все стороны); за костяшку среднего — поворот и размер; за запястье — двигать. Большой палец можно точно настроить: отвести, вынести вперёд, согнуть каждый сустав',
  create: (c) => [{ x: c.x, y: c.y + 20 }],
  init: (g, s) => { g.props.size = Math.round(s * 0.55); g.props.curl = HAND_POSES.relaxed.slice(); Object.assign(g.props, tProps(thumbFromCurl(HAND_POSES.relaxed[0]))); },
  props: [
    { key: 'side', label: 'Рука', type: 'select', options: [['R', 'Правая'], ['L', 'Левая'], ['both', 'Обе']], def: 'R', onSet: (g, v) => { if (v === 'both') { pairOf(g); g.props.pairPose = g.props.pairPose || 'both'; } } },
    { key: 'posePreset', label: 'Жест', type: 'select', show: (g) => P(g, 'side') !== 'both', options: [['open', 'Открыта'], ['relaxed', 'Расслаблена'], ['fist', 'Кулак'], ['point', 'Указывает'], ['peace', 'V'], ['ok', 'OK'], ['grab', 'Хват'], ['thumbs', 'Класс'], ['gun', 'Пистолет'], ['rock', 'Коза'], ['call', 'Позвони'], ['cross', 'Скрестить пальцы'], ['pen', 'Держит карандаш'], ['pinch', 'Щепоть'], ['claw', 'Когти']], def: 'relaxed', onSet: (g, v) => { g.props.curl = (HAND_POSES[v] || HAND_POSES.relaxed).slice(); Object.assign(g.props, tProps(TH[v] || thumbFromCurl(g.props.curl[0]))); g.props.spl = SPL[v] ? clone(SPL[v]) : null; } },
    { key: 'pairPose', label: 'Две руки', type: 'select', show: (g) => P(g, 'side') === 'both', options: PAIR_OPTIONS, def: 'both', onSet: (g, v) => { const q = PAIR_POSES[v] || PAIR_POSES.both; g.props.pair = clone(q); if (q.view) Object.assign(g.props, q.view); else { g.props.turn = 0; g.props.tilt = 0; } } },
    { key: 'turn', label: 'Разворот: ладонь ↔ ребро ↔ тыльная, °', type: 'range', min: -180, max: 180, step: 1, def: 0 },
    { key: 'tilt', label: 'Наклон к себе / от себя, °', type: 'range', min: -80, max: 80, step: 1, def: 0 },
    { key: 'rot', label: 'Поворот в листе, °', type: 'range', min: -180, max: 180, step: 1, def: 0 },
    { key: 'spread', label: 'Развести пальцы', type: 'range', min: -0.5, max: 1.5, step: 0.05, def: 0.3, show: (g) => P(g, 'side') !== 'both' },
    { ...sec('Большой палец'), show: (g) => P(g, 'side') !== 'both' },
    { key: 'tAbd', label: 'Отвести от пальцев, ° (90 — под прямым углом)', type: 'range', min: -30, max: 110, step: 1, def: 40, show: (g) => P(g, 'side') !== 'both' },
    { key: 'tOpp', label: 'Вынести вперёд над ладонью, °', type: 'range', min: -20, max: 85, step: 1, def: 15, show: (g) => P(g, 'side') !== 'both' },
    { key: 'tF1', label: 'Сгиб среднего сустава, ° (минус — выгнуть)', type: 'range', min: -30, max: 95, step: 1, def: 6, show: (g) => P(g, 'side') !== 'both' },
    { key: 'tF2', label: 'Сгиб кончика, ° (минус — переразгиб)', type: 'range', min: -45, max: 95, step: 1, def: 8, show: (g) => P(g, 'side') !== 'both' },
    sec('Вид'),
    { key: 'joints', label: 'Суставы и складки', type: 'toggle', def: true },
    { key: 'size', label: 'Длина ладони, мм', type: 'range', min: 8, max: 200, step: 1, def: 40 },
  ],
  actions: [
    ['⇄ Другая рука', (g) => { const s = P(g, 'side'); if (s === 'both') { const p = pairOf(g); const m = (h) => ({ ...h, o: [-h.o[0], h.o[1], h.o[2]], r: [-h.r[0], h.r[1], -h.r[2]] }); g.props.pair = { R: m(p.L), L: m(p.R) }; } else g.props.side = s === 'L' ? 'R' : 'L'; }],
  ],
  moveIdx: 0,
  draw(pen, g, ctx) {
    const Hs = handsOf(g);
    for (const H of Hs) drawHandModel(pen, H, P(g, 'joints'), ctx.labels);
    const pair = P(g, 'side') === 'both' && g.props.pair;
    if (pair && pair.prop && pair.axis) { // предмет в руках: рукоять по оси хвата
      const { V } = handView(g), { T, F } = pair.axis, at = (a, b) => V.pr([T[0] * a + F[0] * b, T[1] * a + F[1] * b, T[2] * a + F[2] * b]);
      if (pair.prop === 'sword') {
        pen.seg(at(-1.15, 0), at(0.95, 0), 'aux');
        pen.seg(at(0.95, -0.55), at(0.95, 0.55), 'main');
        pen.poly([at(0.95, -0.07), at(3.6, -0.07), at(4.0, 0), at(3.6, 0.07), at(0.95, 0.07)], false, 'main');
      } else {
        pen.poly([at(-0.75, -0.18), at(0.45, -0.25), at(0.45, 0.22), at(-0.75, 0.3)], true, 'aux'); // рукоять
        pen.poly([at(0.45, -0.45), at(0.85, -0.45), at(0.85, 1.55), at(0.45, 1.55)], true, 'main'); // затвор и ствол
      }
    }
  },
  handles(g) {
    const { V } = handView(g), Hs = handsOf(g);
    const hs = [V.pr([0, 0, 0]), P(g, 'side') === 'both' ? V.pr([0, 1.25, 0]) : V.pr([0.12 * (P(g, 'side') === 'L' ? -1 : 1), 1.0, 0])];
    for (const H of Hs) for (let fi = 0; fi < 5; fi++) hs.push(tipOf(H, fi));
    return hs.map(q => ({ x: q.x, y: q.y }));
  },
  drag(g, i, p) {
    if (i === 0) { g.pts[0] = p; return; }
    const { C } = handView(g);
    if (i === 1) { // костяшка среднего пальца: поворот в листе и размер
      const d = sub(p, C);
      g.props.rot = Math.round(Math.atan2(d.x, -d.y) / D2R);
      g.props.size = clamp(Math.round(len(d) / (P(g, 'side') === 'both' ? 1.25 : 1.0)), 6, 300);
      return;
    }
    const k = i - 2, hi = Math.floor(k / 5), fi = k % 5, both = P(g, 'side') === 'both';
    const pair = both ? pairOf(g) : null, sd = both ? (hi ? 'L' : 'R') : null;
    const Hof = () => handsOf(g)[hi];
    const dist2 = () => { const t = tipOf(Hof(), fi); return Math.hypot(t.x - p.x, t.y - p.y); };
    if (fi === 0) { // большой палец: перебор отведения и выноса вперёд — ходит во все стороны
      const th = both ? (pair[sd].th = pair[sd].th || thumbFromCurl(pair[sd].curl[0])) : thumbOf(g);
      const set = (a, o) => { if (both) { th.abd = a; th.opp = o; } else { g.props.tAbd = a; g.props.tOpp = o; g.props.tF1 = th.f1; g.props.tF2 = th.f2; } };
      let best = [th.abd, th.opp], bd = Infinity;
      for (let a = -30; a <= 110; a += 5) for (let o = -20; o <= 85; o += 5) { set(a, o); const d = dist2(); if (d < bd) { bd = d; best = [a, o]; } }
      const [a0, o0] = best;
      for (let a = a0 - 4; a <= a0 + 4; a++) for (let o = o0 - 4; o <= o0 + 4; o++) { set(clamp(a, -30, 110), clamp(o, -20, 85)); const d = dist2(); if (d < bd) { bd = d; best = [clamp(a, -30, 110), clamp(o, -20, 85)]; } }
      set(best[0], best[1]);
      return;
    }
    const curl = both ? pair[sd].curl : (g.props.curl = ((g.props && g.props.curl) || HAND_POSES.relaxed).slice());
    let best = curl[fi], bd = Infinity;
    for (let c = -0.3; c <= 1.71; c += 0.02) { curl[fi] = c; const d = dist2(); if (d < bd) { bd = d; best = c; } }
    curl[fi] = Math.round(best * 100) / 100;
  },
  handleLabel: (g, i) => (i === 0 ? 'запястье' : i === 1 ? 'поворот' : FING[(i - 2) % 5].name),
};
function tProps(th) { return { tAbd: th.abd, tOpp: th.opp, tF1: th.f1, tF2: th.f2 }; }

// ======================================================================
// 4. ГЛАЗ — подробная шпаргалка (глазное яблоко + веки), разные стили и ракурсы
// ======================================================================
// Глаз — шар; разрез задан на шаре кривыми век (по долготе θ от внутреннего уголка к внешнему).
// Поворот головы (ракурс) поворачивает шар — разрез и радужка сами становятся «в перспективе»,
// в профиль глаз превращается в клин, радужка — в узкий эллипс.
export const EYE_PRESETS = {
  real: { W: 40, Hu: 22, Hl: 14, pu: 0.8, pl: 0.9, skew: 0.15, co: 4, rho: 23, tall: 1.0, lash: 'fine', crease: true, shine: 'small', brow: true },
  anime: { W: 42, Hu: 40, Hl: 22, pu: 0.55, pl: 0.7, skew: 0.1, co: 6, rho: 27, tall: 1.3, lash: 'bold', crease: true, shine: 'big', brow: true },
  shoujo: { W: 44, Hu: 46, Hl: 28, pu: 0.5, pl: 0.6, skew: 0.05, co: 3, rho: 30, tall: 1.35, lash: 'shoujo', crease: true, shine: 'many', brow: true },
  shonen: { W: 44, Hu: 22, Hl: 9, pu: 1.0, pl: 1.0, skew: 0.4, co: 10, rho: 22, tall: 1.1, lash: 'bold', crease: false, shine: 'small', brow: true },
  seinen: { W: 40, Hu: 18, Hl: 10, pu: 0.85, pl: 0.9, skew: 0.2, co: 3, rho: 22, tall: 1.0, lash: 'fine', crease: true, shine: 'small', brow: true },
  chibi: { W: 38, Hu: 48, Hl: 40, pu: 0.4, pl: 0.4, skew: 0, co: 0, rho: 30, tall: 1.25, lash: 'none', crease: false, shine: 'big', brow: false },
};
function drawEye(pen, g, ctx) {
  const C = g.pts[0], r = Math.max(2, dist(g.pts[0], g.pts[1]) / 1.6);
  const side = P(g, 'side') === 'L' ? -1 : 1; // внутренний уголок: у правого глаза — справа на рисунке
  const yaw = (+P(g, 'yaw') || 0) * D2R * side, pitch = (+P(g, 'pitch') || 0) * D2R, roll = (+P(g, 'roll') || 0) * D2R;
  const V = view3(C, r, yaw, pitch, roll);
  const W = (+P(g, 'W')) * D2R, open = +P(g, 'open'), Hu = (+P(g, 'Hu')) * D2R * open, Hl = (+P(g, 'Hl')) * D2R * Math.min(1, open * 1.4);
  const pu = +P(g, 'pu'), pl = +P(g, 'pl'), skew = +P(g, 'skew'), co = (+P(g, 'co')) * D2R, ci = -2 * D2R;
  const rho = (+P(g, 'rho')) * D2R, tall = +P(g, 'tall');
  const gx = (+P(g, 'gazeX') || 0) * 30 * D2R, gy = (+P(g, 'gazeY') || 0) * 22 * D2R;
  // θ < 0 — внутренний уголок (к носу). Для правого глаза (side=1) нос — справа на рисунке (+x).
  const sph = (th, ph, rad = 1) => [-side * Math.sin(th) * Math.cos(ph) * rad, Math.sin(ph) * rad, Math.cos(th) * Math.cos(ph) * rad];
  const mid = (t) => lerp(ci, co, (t + 1) / 2);
  const phU = (t) => mid(t) + Hu * Math.pow(Math.max(0, 1 - t * t), pu) * (1 + skew * t);
  const phL = (t) => mid(t) - Hl * Math.pow(Math.max(0, 1 - t * t), pl);
  const vis = (p) => V.R(p)[2] > -0.02;
  const N = 40;
  const curve = (f, rad = 1.0, t0 = -1, t1 = 1) => { const a = []; for (let i = 0; i <= N; i++) { const t = t0 + (t1 - t0) * i / N; a.push(sph(t * W, f(t), rad)); } return a; };
  if (P(g, 'build')) { // построение: шар, оси, направление взгляда
    pen.circle(C, r, 'aux');
    const eq = []; for (let i = 0; i <= 60; i++) { const a = -Math.PI / 2 + Math.PI * i / 60; eq.push([Math.sin(a), 0, Math.cos(a)]); }
    poly3(pen, V, eq, vis, 'aux');
    const mr = []; for (let i = 0; i <= 60; i++) { const a = -Math.PI / 2 + Math.PI * i / 60; mr.push([0, Math.sin(a), Math.cos(a)]); }
    poly3(pen, V, mr, vis, 'aux');
  }
  // веки
  const upper = curve(phU, 1.0), lower = curve(phL, 1.0);
  poly3(pen, V, upper, vis, 'main');
  poly3(pen, V, lower, vis, 'main');
  // толщина нижнего века и складка верхнего
  poly3(pen, V, curve((t) => phL(t) - 3 * D2R, 1.04, -0.85, 0.9), vis, 'aux');
  if (P(g, 'crease')) poly3(pen, V, curve((t) => phU(t) + 9 * D2R + 4 * D2R * (1 - t * t), 1.06, -0.8, 0.95), vis, 'aux');
  // слёзное мясцо во внутреннем уголке
  if (P(g, 'style') === 'real' || P(g, 'style') === 'seinen') { const t = -0.93; poly3(pen, V, [sph(t * W, phU(t) - 0.3 * Hu * 0.2), sph(-W * 0.86, mid(-1), 1.0), sph(t * W, phL(t) + 0.2 * Hl * 0.2)], vis, 'aux'); }
  // радужка, зрачок — только внутри разреза
  const inside = (p) => { // p — точка на шаре; переводим в (θ, φ)
    const th = Math.atan2(-side * p[0], p[2]), ph = Math.asin(clamp(p[1], -1, 1)), t = th / W;
    return t > -1 && t < 1 && ph < phU(t) - 0.5 * D2R && ph > phL(t) + 0.5 * D2R;
  };
  const ring = (rad, layer) => {
    const pts = [];
    for (let i = 0; i <= 64; i++) {
      const a = TAU * i / 64;
      // окружность вокруг оси взгляда (gx, gy), растянутая по вертикали (аниме)
      pts.push(sph(gx + Math.cos(a) * rad, gy + Math.sin(a) * rad * tall));
    }
    let run = [];
    for (const p of pts) { if (inside(p) && vis(p)) run.push(V.pr(p)); else { if (run.length > 1) pen.poly(run, false, layer); run = []; } }
    if (run.length > 1) pen.poly(run, false, layer);
  };
  ring(rho, 'main'); ring(rho * clamp(+P(g, 'pupil') || 0.42, 0.12, 0.85), 'main');
  if (P(g, 'style') !== 'real' && P(g, 'style') !== 'seinen') ring(rho * 0.75, 'aux'); // кольцо внутри радужки (аниме-тон)
  // блики (в экранных координатах, от источника света сверху-слева)
  const shine = P(g, 'shine');
  if (shine !== 'none' && open > 0.2) {
    const ic = V.pr(sph(gx, gy));
    const R0 = rho * r * 0.95;
    const blob = (dx, dy, rr) => pen.circle({ x: ic.x + dx * R0, y: ic.y + dy * R0 * tall }, Math.max(0.3, rr * R0), 'aux');
    if (shine === 'small') blob(-0.35, -0.38, 0.18);
    else if (shine === 'big') { blob(-0.32, -0.36, 0.34); blob(0.4, 0.42, 0.13); }
    else { blob(-0.32, -0.4, 0.32); blob(0.38, 0.4, 0.14); blob(0.36, -0.5, 0.1); blob(-0.45, 0.35, 0.08); }
  }
  // ресницы
  const lash = P(g, 'lash');
  const lashAt = (t, l, ang, layer = 'main') => {
    const a = sph(t * W, phU(t), 1.0), b = sph(t * W, phU(t) + 0.02, 1.0);
    if (!vis(a)) return;
    const pa = V.pr(a), pb = V.pr(b), d = sub(pb, pa), n0 = norm({ x: d.x, y: d.y });
    // направление: от центра глаза наружу и вверх
    const out = norm(sub(pa, C)), dir = norm(add(mulS(out, 1), mulS(n0, 0.4)));
    const dd = { x: dir.x * Math.cos(ang) - dir.y * Math.sin(ang), y: dir.x * Math.sin(ang) + dir.y * Math.cos(ang) };
    pen.seg(pa, add(pa, mulS(dd, l * r)), layer);
  };
  if (lash === 'fine') for (let k = 0; k < 14; k++) { const t = -0.75 + 1.65 * k / 13; lashAt(t, 0.18 + 0.12 * (t + 1) / 2, side * 0.2 * t); }
  if (lash === 'bold' || lash === 'shoujo') {
    poly3(pen, V, curve((t) => phU(t) + (3 + 4 * Math.max(0, t)) * D2R, 1.03, -0.9, 1.08), vis, 'main');
    for (const t of [0.7, 0.88, 1.0]) lashAt(t, 0.32 + 0.12 * (t - 0.7) * 3, side * 0.25);
    if (lash === 'shoujo') { for (let k = 0; k < 6; k++) { const t = -0.4 + 1.1 * k / 5, a = sph(t * W, phL(t), 1.0); if (!vis(a)) continue; const pa = V.pr(a), dir = norm(sub(pa, C)); pen.seg(pa, add(pa, mulS(dir, 0.14 * r)), 'aux'); } }
  }
  // бровь
  if (P(g, 'brow')) {
    const bh = (+P(g, 'browH')) * D2R;
    poly3(pen, V, curve((t) => Hu + bh + 10 * D2R * (1 - Math.pow((t - 0.15) / 1.3, 2)) - 4 * D2R * t * (+P(g, 'browTilt') || 0), 1.25, -1.05, 1.15), vis, 'main');
  }
  if (ctx.labels) pen.label({ x: C.x, y: C.y + r * 1.5 }, `${({ real: 'реализм', anime: 'аниме', shoujo: 'сёдзё', shonen: 'сёнэн', seinen: 'сэйнэн', chibi: 'чиби' })[P(g, 'style')] || ''} · ракурс ${Math.round(+P(g, 'yaw') || 0)}°`);
}
const eye = {
  name: 'Глаз', icon: '👁', group: 'manga',
  desc: 'Подробная шпаргалка глаза: глазное яблоко, веки, радужка, блики, ресницы. Стили, ракурс (анфас → три четверти → профиль), взгляд и раскрытие',
  create: (c, s) => [{ ...c }, { x: c.x + s * 0.6, y: c.y }],
  init: (g) => Object.assign(g.props, JSON.parse(JSON.stringify(EYE_PRESETS.anime))),
  props: [
    { key: 'style', label: 'Стиль', type: 'select', options: [['anime', 'Аниме'], ['shoujo', 'Сёдзё'], ['shonen', 'Сёнэн'], ['seinen', 'Сэйнэн'], ['real', 'Реализм'], ['chibi', 'Чиби']], def: 'anime', onSet: presetSet(EYE_PRESETS) },
    { key: 'side', label: 'Глаз', type: 'select', options: [['R', 'Правый'], ['L', 'Левый']], def: 'R' },
    sec('Ракурс и взгляд'),
    { key: 'yaw', label: 'Ракурс: анфас → профиль, °', type: 'range', min: -30, max: 85, step: 1, def: 0 },
    { key: 'pitch', label: 'Сверху ↔ снизу, °', type: 'range', min: -50, max: 50, step: 1, def: 0 },
    { key: 'roll', label: 'Наклон, °', type: 'range', min: -45, max: 45, step: 1, def: 0 },
    { key: 'gazeX', label: 'Взгляд к носу ↔ в сторону', type: 'range', min: -1, max: 1, step: 0.05, def: 0 },
    { key: 'gazeY', label: 'Взгляд ↓ ↑', type: 'range', min: -1, max: 1, step: 0.05, def: 0 },
    { key: 'open', label: 'Раскрытие (моргание)', type: 'range', min: 0, max: 1.3, step: 0.05, def: 1 },
    { key: 'pupil', label: 'Зрачок: узкий ↔ широкий', type: 'range', min: 0.15, max: 0.8, step: 0.01, def: 0.42 },
    sec('Форма'),
    { key: 'W', label: 'Ширина разреза, °', type: 'range', min: 25, max: 60, step: 1, def: 42 },
    { key: 'Hu', label: 'Верхнее веко, °', type: 'range', min: 5, max: 60, step: 1, def: 40 },
    { key: 'Hl', label: 'Нижнее веко, °', type: 'range', min: 2, max: 45, step: 1, def: 22 },
    { key: 'co', label: 'Внешний уголок вверх (цури-мэ) / вниз (тарэ-мэ), °', type: 'range', min: -15, max: 20, step: 1, def: 6 },
    { key: 'skew', label: 'Пик века к внешнему краю', type: 'range', min: -0.4, max: 0.6, step: 0.05, def: 0.1 },
    { key: 'rho', label: 'Радужка, °', type: 'range', min: 12, max: 40, step: 1, def: 27 },
    { key: 'tall', label: 'Радужка вытянута', type: 'range', min: 0.8, max: 1.6, step: 0.05, def: 1.3 },
    sec('Детали'),
    { key: 'lash', label: 'Ресницы', type: 'select', options: [['none', 'Нет'], ['fine', 'Тонкие'], ['bold', 'Жирная линия'], ['shoujo', 'Сёдзё']], def: 'bold' },
    { key: 'shine', label: 'Блики', type: 'select', options: [['none', 'Нет'], ['small', 'Маленький'], ['big', 'Большой'], ['many', 'Много']], def: 'big' },
    { key: 'crease', label: 'Складка века', type: 'toggle', def: true },
    { key: 'brow', label: 'Бровь', type: 'toggle', def: true },
    { key: 'browH', label: 'Бровь выше/ниже, °', type: 'range', min: 0, max: 40, step: 1, def: 12, show: (g) => P(g, 'brow') },
    { key: 'browTilt', label: 'Бровь: грустная ↔ злая', type: 'range', min: -1, max: 1, step: 0.05, def: 0, show: (g) => P(g, 'brow') },
    { key: 'build', label: 'Построение (шар и оси)', type: 'toggle', def: true },
    { key: 'pu', label: '', type: 'hidden', def: 0.55 }, { key: 'pl', label: '', type: 'hidden', def: 0.7 },
  ],
  draw(pen, g, ctx) { drawEye(pen, g, ctx); },
  handles: (g) => g.pts,
  drag(g, i, p) { if (i === 0) { const d = sub(p, g.pts[0]); g.pts = g.pts.map(q => add(q, d)); } else g.pts[1] = p; },
  moveIdx: 0,
};

// ======================================================================
// 5. РАСКАДРОВКА (шаблоны страниц манги)
// ======================================================================
const LAYOUTS = {
  classic: [{ h: 1, c: [1, 1] }, { h: 1.25, c: [1] }, { h: 1, c: [1.3, 1] }],
  g2x3: [{ h: 1, c: [1, 1] }, { h: 1, c: [1, 1] }, { h: 1, c: [1, 1] }],
  g3x3: [{ h: 1, c: [1, 1, 1] }, { h: 1, c: [1, 1, 1] }, { h: 1, c: [1, 1, 1] }],
  yonkoma: [{ h: 1, c: [1] }, { h: 1, c: [1] }, { h: 1, c: [1] }, { h: 1, c: [1] }],
  splash: [{ h: 2.2, c: [1] }, { h: 1, c: [1, 1] }],
  wide: [{ h: 1, c: [1] }, { h: 1.2, c: [1, 1, 1] }, { h: 1, c: [1] }],
  action: [{ h: 1, c: [1.5, 1] }, { h: 1.35, c: [1] }, { h: 1, c: [1, 1.2, 1] }],
  talk: [{ h: 1, c: [1, 1.4] }, { h: 1, c: [1.4, 1] }, { h: 1, c: [1, 1.4] }, { h: 1, c: [1] }],
};
function rectOf(a, b) { return { x0: Math.min(a.x, b.x), y0: Math.min(a.y, b.y), x1: Math.max(a.x, b.x), y1: Math.max(a.y, b.y) }; }
function panelPolys(g) {
  const A = rectOf(g.pts[0], g.pts[1]);
  const lay = P(g, 'layout') === 'custom'
    ? Array.from({ length: +P(g, 'rows') }, () => ({ h: 1, c: Array.from({ length: +P(g, 'cols') }, () => 1) }))
    : (LAYOUTS[P(g, 'layout')] || LAYOUTS.classic);
  const gH = +P(g, 'gutH'), gV = +P(g, 'gutV'), sl = Math.tan((+P(g, 'slant') || 0) * D2R);
  const W = A.x1 - A.x0, H = A.y1 - A.y0, xc = (A.x0 + A.x1) / 2;
  const tot = lay.reduce((s, r) => s + r.h, 0);
  // горизонтальные линии: y = yc + s·(x − xc) + off
  const hl = [{ yc: A.y0, s: 0, off: 0 }];
  let acc = 0;
  for (let k = 1; k < lay.length; k++) { acc += lay[k - 1].h; hl.push({ yc: A.y0 + H * acc / tot, s: sl * (k % 2 ? 1 : -1) * 0.5, sep: true }); }
  hl.push({ yc: A.y1, s: 0, off: 0 });
  const yOn = (L, x, off) => L.yc + L.s * (x - xc) + off;
  const inter = (V, Hh, offV, offH) => { // V: x = xm + t·(y − ym)
    const y = (Hh.yc + Hh.s * (V.xm - V.t * V.ym + offV - xc) + offH) / (1 - Hh.s * V.t);
    return { x: V.xm + V.t * (y - V.ym) + offV, y };
  };
  const polys = [];
  lay.forEach((row, k) => {
    const top = hl[k], bot = hl[k + 1];
    const ym = (yOn(top, xc, 0) + yOn(bot, xc, 0)) / 2;
    const ct = row.c.reduce((s, v) => s + v, 0);
    const vl = [{ xm: A.x0, t: 0, ym }];
    let a2 = 0;
    for (let j = 1; j < row.c.length; j++) { a2 += row.c[j - 1]; vl.push({ xm: A.x0 + W * a2 / ct, t: sl * ((j + k) % 2 ? 1 : -1) * 0.8, ym, sep: true }); }
    vl.push({ xm: A.x1, t: 0, ym });
    const cells = [];
    for (let j = 0; j < row.c.length; j++) {
      const L = vl[j], R = vl[j + 1];
      const oL = L.sep ? gV / 2 : 0, oR = R.sep ? -gV / 2 : 0, oT = top.sep ? gH / 2 : 0, oB = bot.sep ? -gH / 2 : 0;
      cells.push([inter(L, top, oL, oT), inter(R, top, oR, oT), inter(R, bot, oR, oB), inter(L, bot, oL, oB)]);
    }
    polys.push(...cells);
  });
  // японская манга: зеркалим всю страницу (большой кадр уходит вправо, нумерация — справа налево)
  if (P(g, 'rtl')) for (let i = 0; i < polys.length; i++) { const q = polys[i].map(v => ({ x: 2 * xc - v.x, y: v.y })); polys[i] = [q[1], q[0], q[3], q[2]]; }
  return { polys, A };
}
const panels = {
  name: 'Раскадровка', icon: '📖', group: 'manga',
  desc: 'Шаблоны страниц манги: кадры с промежутками, наклонные кадры для экшена. «Справа налево» зеркалит страницу, как в японской манге. Внутри кадров — композиция (трети, центр), безопасная зона для текста, стрелка порядка чтения. Углы области — за ручки',
  create: (c, s, d) => [{ x: 14, y: 16 }, { x: d.W - 14, y: d.H - 20 }],
  props: [
    { key: 'layout', label: 'Шаблон', type: 'select', options: [['classic', 'Классика'], ['g2x3', '2×3'], ['g3x3', '3×3'], ['yonkoma', '4-кома'], ['splash', 'Большой кадр'], ['wide', 'Широкие'], ['action', 'Экшен'], ['talk', 'Диалог'], ['custom', 'Своя сетка']], def: 'classic' },
    { key: 'rows', label: 'Рядов', type: 'range', min: 1, max: 8, step: 1, def: 3, show: (g) => P(g, 'layout') === 'custom' },
    { key: 'cols', label: 'Кадров в ряду', type: 'range', min: 1, max: 5, step: 1, def: 2, show: (g) => P(g, 'layout') === 'custom' },
    { key: 'gutH', label: 'Промежуток между рядами, мм', type: 'range', min: 0, max: 15, step: 0.5, def: 6 },
    { key: 'gutV', label: 'Промежуток между кадрами, мм', type: 'range', min: 0, max: 12, step: 0.5, def: 3 },
    { key: 'slant', label: 'Наклон границ (экшен), °', type: 'range', min: 0, max: 15, step: 0.5, def: 0 },
    { key: 'rtl', label: 'Справа налево (зеркалит страницу)', type: 'toggle', def: true },
    { key: 'nums', label: 'Номера кадров', type: 'toggle', def: true },
    { key: 'order', label: 'Стрелка порядка чтения', type: 'toggle', def: false },
    { key: 'inner', label: 'Внутри кадров', type: 'select', options: [['none', 'Ничего'], ['thirds', 'Трети (композиция)'], ['center', 'Центр и диагонали'], ['horizon', 'Линия горизонта (на трети)'], ['safe', 'Поле для текста (отступ)']], def: 'none' },
    { key: 'bleed', label: 'Поля: обрез и безопасная зона', type: 'toggle', def: false },
  ],
  draw(pen, g, ctx) {
    const { polys, A } = panelPolys(g);
    polys.forEach((q, i) => {
      pen.poly(q, true, 'main');
      const c = { x: (q[0].x + q[1].x + q[2].x + q[3].x) / 4, y: (q[0].y + q[1].y + q[2].y + q[3].y) / 4 };
      if (P(g, 'nums') && ctx.labels) pen.label(c, String(i + 1));
      const inner = P(g, 'inner') || 'none';
      // точка внутри четырёхугольника кадра по долям (u — слева направо, v — сверху вниз)
      const at = (u, v) => { const t = lerpP(q[0], q[1], u), b = lerpP(q[3], q[2], u); return lerpP(t, b, v); };
      if (inner === 'thirds') for (const k of [1 / 3, 2 / 3]) { pen.seg(at(k, 0), at(k, 1), 'aux'); pen.seg(at(0, k), at(1, k), 'aux'); }
      else if (inner === 'center') { pen.seg(q[0], q[2], 'aux'); pen.seg(q[1], q[3], 'aux'); pen.seg(at(0.5, 0), at(0.5, 1), 'aux'); pen.seg(at(0, 0.5), at(1, 0.5), 'aux'); }
      else if (inner === 'horizon') { pen.seg(at(0, 1 / 3), at(1, 1 / 3), 'aux'); pen.seg(at(0, 2 / 3), at(1, 2 / 3), 'ghost'); }
      else if (inner === 'safe') { const m = Math.min(0.12, 4 / Math.max(8, dist(q[0], q[1]))), mv = Math.min(0.12, 4 / Math.max(8, dist(q[0], q[3]))); pen.poly([at(m, mv), at(1 - m, mv), at(1 - m, 1 - mv), at(m, 1 - mv)], true, 'ghost'); }
    });
    // порядок чтения: зигзаг по центрам кадров со стрелками
    if (P(g, 'order') && polys.length > 1) {
      const cs = polys.map(q => ({ x: (q[0].x + q[1].x + q[2].x + q[3].x) / 4, y: (q[0].y + q[1].y + q[2].y + q[3].y) / 4 }));
      for (let i = 0; i < cs.length - 1; i++) {
        const a = cs[i], b = cs[i + 1], d = sub(b, a), L = len(d) || 1, u = mulS(d, 1 / L), n = perp(u), a2 = add(a, mulS(u, Math.min(6, L * 0.2))), b2 = add(a, mulS(u, L - Math.min(6, L * 0.2)));
        pen.seg(a2, b2, 'ghost');
        pen.poly([add(b2, add(mulS(u, -3), mulS(n, 1.6))), b2, add(b2, add(mulS(u, -3), mulS(n, -1.6)))], false, 'ghost');
      }
    }
    if (P(g, 'bleed')) {
      const e = 5;
      pen.poly([{ x: A.x0 - e, y: A.y0 - e }, { x: A.x1 + e, y: A.y0 - e }, { x: A.x1 + e, y: A.y1 + e }, { x: A.x0 - e, y: A.y1 + e }], true, 'ghost');
      pen.poly([{ x: A.x0 + e, y: A.y0 + e }, { x: A.x1 - e, y: A.y0 + e }, { x: A.x1 - e, y: A.y1 - e }, { x: A.x0 + e, y: A.y1 - e }], true, 'ghost');
    }
    if (ctx.labels) pen.label({ x: (A.x0 + A.x1) / 2, y: A.y0 - 5 }, `${polys.length} кадров${P(g, 'rtl') ? ' · справа налево' : ''}`);
  },
  handles(g) { const A = rectOf(g.pts[0], g.pts[1]); return [g.pts[0], g.pts[1], { x: (A.x0 + A.x1) / 2, y: (A.y0 + A.y1) / 2 }]; },
  drag(g, i, p) { if (i === 2) { const h = this.handles(g)[2], d = sub(p, h); g.pts = g.pts.map(q => add(q, d)); } else g.pts[i] = p; },
  moveIdx: 2,
};

// ======================================================================
// 6. ЛИНИИ СКОРОСТИ и ЛИНИИ ФОКУСА
// ======================================================================
function clipRay(o, d, R) { // параметр t выхода луча o + t·d из прямоугольника
  let t = Infinity;
  if (d.x > 1e-9) t = Math.min(t, (R.x1 - o.x) / d.x); else if (d.x < -1e-9) t = Math.min(t, (R.x0 - o.x) / d.x);
  if (d.y > 1e-9) t = Math.min(t, (R.y1 - o.y) / d.y); else if (d.y < -1e-9) t = Math.min(t, (R.y0 - o.y) / d.y);
  return t;
}
function clipLineRect(p, u, R) { // прямая p + t·u ∩ прямоугольник → [t0, t1] или null
  let t0 = -Infinity, t1 = Infinity;
  for (const [pp, uu, lo, hi] of [[p.x, u.x, R.x0, R.x1], [p.y, u.y, R.y0, R.y1]]) {
    if (Math.abs(uu) < 1e-9) { if (pp < lo || pp > hi) return null; continue; }
    let a = (lo - pp) / uu, b = (hi - pp) / uu; if (a > b) [a, b] = [b, a];
    t0 = Math.max(t0, a); t1 = Math.min(t1, b);
  }
  return t1 > t0 ? [t0, t1] : null;
}
// отрезок без части внутри круга (свободное место под персонажа)
function segMinusCircle(pen, a, b, c, r, layer) {
  if (r <= 0) { pen.seg(a, b, layer); return; }
  const d = sub(b, a), L2 = dot(d, d) || 1, f = sub(a, c);
  const B = 2 * dot(f, d), Cc = dot(f, f) - r * r, disc = B * B - 4 * L2 * Cc;
  if (disc <= 0) { pen.seg(a, b, layer); return; }
  const s = Math.sqrt(disc), t1 = (-B - s) / (2 * L2), t2 = (-B + s) / (2 * L2);
  if (t1 > 0) pen.seg(a, add(a, mulS(d, Math.min(1, t1))), layer);
  if (t2 < 1) pen.seg(add(a, mulS(d, Math.max(0, t2))), b, layer);
}
const speed = {
  name: 'Линии скорости', icon: '💨', group: 'manga',
  desc: 'Параллельные штрихи разной длины по направлению движения (или сходящиеся к точке). Ручки: ● центр (свободное место под героя), стрелка — направление, углы — область',
  create: (c, s) => [{ ...c }, { x: c.x + s, y: c.y }, { x: c.x - s * 1.4, y: c.y - s * 0.9 }, { x: c.x + s * 1.4, y: c.y + s * 0.9 }],
  props: [
    { key: 'mode', label: 'Вид', type: 'select', options: [['par', 'Параллельные'], ['conv', 'К точке (перспектива)']], def: 'par' },
    { key: 'count', label: 'Количество', type: 'range', min: 6, max: 160, step: 1, def: 40 },
    { key: 'lmin', label: 'Длина: от', type: 'range', min: 0.05, max: 1, step: 0.05, def: 0.25 },
    { key: 'lmax', label: 'Длина: до', type: 'range', min: 0.1, max: 1, step: 0.05, def: 0.75 },
    { key: 'anchor', label: 'Начало штрихов', type: 'select', options: [['back', 'От края сзади'], ['rand', 'Вразброс']], def: 'back' },
    { key: 'clear', label: 'Свободный круг в центре, мм', type: 'range', min: 0, max: 80, step: 1, def: 12 },
    { key: 'jit', label: 'Неровность шага', type: 'range', min: 0, max: 1, step: 0.05, def: 0.6 },
    { key: 'seed', label: 'Перемешать', type: 'range', min: 1, max: 30, step: 1, def: 1 },
    { key: 'frame', label: 'Показать область', type: 'toggle', def: true },
  ],
  draw(pen, g, ctx) {
    const [p0, p1] = g.pts, R = rectOf(g.pts[2], g.pts[3]), rnd = rng(+P(g, 'seed') * 7919 + 13);
    const n = +P(g, 'count'), lmin = Math.min(+P(g, 'lmin'), +P(g, 'lmax')), lmax = Math.max(+P(g, 'lmin'), +P(g, 'lmax')), jit = +P(g, 'jit'), clr = +P(g, 'clear');
    if (P(g, 'frame')) pen.poly([{ x: R.x0, y: R.y0 }, { x: R.x1, y: R.y0 }, { x: R.x1, y: R.y1 }, { x: R.x0, y: R.y1 }], true, 'ghost');
    if (P(g, 'mode') === 'conv') {
      const per = 2 * (R.x1 - R.x0 + R.y1 - R.y0);
      for (let k = 0; k < n; k++) {
        let s = per * (k + 0.5 + (rnd() - 0.5) * jit) / n; s = ((s % per) + per) % per;
        const w = R.x1 - R.x0, h = R.y1 - R.y0;
        const B = s < w ? { x: R.x0 + s, y: R.y0 } : s < w + h ? { x: R.x1, y: R.y0 + s - w } : s < 2 * w + h ? { x: R.x1 - (s - w - h), y: R.y1 } : { x: R.x0, y: R.y1 - (s - 2 * w - h) };
        const d = sub(p1, B), Lf = lmin + (lmax - lmin) * rnd();
        segMinusCircle(pen, B, add(B, mulS(d, Lf)), p0, clr, 'main');
      }
    } else {
      const u = norm(sub(p1, p0)), nn = perp(u);
      let lo = Infinity, hi = -Infinity;
      for (const c of [{ x: R.x0, y: R.y0 }, { x: R.x1, y: R.y0 }, { x: R.x1, y: R.y1 }, { x: R.x0, y: R.y1 }]) { const t = dot(sub(c, p0), nn); lo = Math.min(lo, t); hi = Math.max(hi, t); }
      for (let k = 0; k < n; k++) {
        const off = lo + (hi - lo) * (k + 0.5 + (rnd() - 0.5) * jit) / n, q = add(p0, mulS(nn, off));
        const tt = clipLineRect(q, u, R); if (!tt) continue;
        const span = tt[1] - tt[0], Lf = lmin + (lmax - lmin) * rnd();
        const st = P(g, 'anchor') === 'back' ? tt[0] : tt[0] + (span * (1 - Lf)) * rnd();
        segMinusCircle(pen, add(q, mulS(u, st)), add(q, mulS(u, st + span * Lf)), p0, clr, 'main');
      }
    }
    if (clr > 0) pen.circle(p0, clr, 'ghost');
    pen.seg(p0, p1, 'aux');
    const u2 = norm(sub(p1, p0)), n2 = perp(u2); // стрелка
    pen.poly([add(p1, add(mulS(u2, -4), mulS(n2, 2.5))), p1, add(p1, add(mulS(u2, -4), mulS(n2, -2.5)))], false, 'aux');
    void ctx;
  },
  handles: (g) => g.pts,
  drag(g, i, p) { if (i === 0) { const d = sub(p, g.pts[0]); g.pts = g.pts.map(q => add(q, d)); } else g.pts[i] = p; },
  moveIdx: 0,
};
const focus = {
  name: 'Линии фокуса', icon: '✺', group: 'manga',
  desc: 'Лучи от краёв к центру, обрываются у овала — взгляд читателя «втягивается» в героя: удивление, напряжение, удар. Ручки: центр, размер овала, углы области',
  create: (c, s, d) => [{ ...c }, { x: c.x + s * 0.45, y: c.y + s * 0.3 }, { x: 8, y: 8 }, { x: d.W - 8, y: d.H - 8 }],
  props: [
    { key: 'count', label: 'Лучей', type: 'range', min: 12, max: 360, step: 4, def: 96 },
    { key: 'inner', label: 'Разброс у овала', type: 'range', min: 0, max: 2, step: 0.05, def: 0.6 },
    { key: 'jit', label: 'Неровность шага', type: 'range', min: 0, max: 1, step: 0.05, def: 0.7 },
    { key: 'groups', label: 'Пучками', type: 'toggle', def: false },
    { key: 'seed', label: 'Перемешать', type: 'range', min: 1, max: 30, step: 1, def: 1 },
    { key: 'oval', label: 'Показать овал', type: 'toggle', def: true },
  ],
  draw(pen, g) {
    const [c, e] = g.pts, R = rectOf(g.pts[2], g.pts[3]), rnd = rng(+P(g, 'seed') * 104729 + 7);
    const rx = Math.max(2, Math.abs(e.x - c.x)), ry = Math.max(2, Math.abs(e.y - c.y));
    const n = +P(g, 'count'), inner = +P(g, 'inner'), jit = +P(g, 'jit');
    for (let k = 0; k < n; k++) {
      if (P(g, 'groups') && Math.floor(k / 6) % 2 === 1 && rnd() < 0.8) continue;
      const th = TAU * (k + (rnd() - 0.5) * jit) / n, d = { x: Math.cos(th), y: Math.sin(th) };
      const kIn = 1 + inner * Math.pow(rnd(), 1.6);
      const a = { x: c.x + d.x * rx * kIn, y: c.y + d.y * ry * kIn };
      const t = clipRay(c, d, R); if (!isFinite(t)) continue;
      const b = add(c, mulS(d, t));
      if (dot(sub(b, a), d) <= 0.5) continue;
      pen.seg(a, b, 'main');
    }
    if (P(g, 'oval')) pen.ellipse(c, rx, ry, 0, 'ghost');
    pen.poly([{ x: R.x0, y: R.y0 }, { x: R.x1, y: R.y0 }, { x: R.x1, y: R.y1 }, { x: R.x0, y: R.y1 }], true, 'ghost');
  },
  handles: (g) => g.pts,
  drag(g, i, p) { if (i === 0) { const d = sub(p, g.pts[0]); g.pts[0] = p; g.pts[1] = add(g.pts[1], d); } else g.pts[i] = p; },
  moveIdx: 0,
};

// ======================================================================
// 7. ЛИСТ РАЗВОРОТА ПЕРСОНАЖА (turnaround)
// ======================================================================
// Одна и та же фигура в нескольких видах (спереди, 3/4, сбоку, сзади) на общих
// горизонтальных линиях: макушка, глаза, подбородок, плечи, грудь, талия, пах, колени, стопы.
const MARKS = [[0, 'макушка'], [0.5, 'глаза'], [1, 'подбородок'], [1.45, 'плечи'], [2.2, 'грудь'], [3.0, 'талия'], [3.95, 'пах'], [5.85, 'колени'], [8, 'стопы']];
const VIEWS = { 3: [[0, 'спереди'], [90, 'сбоку'], [180, 'сзади']], 4: [[0, 'спереди'], [45, '3/4'], [90, 'сбоку'], [180, 'сзади']], 5: [[0, 'спереди'], [45, '3/4'], [90, 'сбоку'], [135, '3/4 сзади'], [180, 'сзади']] };
const A_POSE = { ...BODY_POSES.stand, elR: [-1.2, 2.92], wrR: [-1.38, 3.88], haR: [-1.48, 4.6], elL: [1.2, 2.92], wrL: [1.38, 3.88], haL: [1.48, 4.6] };
const ZDEPTH = { toR: 0.38, toL: 0.38, haR: 0.05, haL: 0.05, head: 0.0, chest: 0.05 };
const turn = {
  name: 'Разворот персонажа', icon: '👥', group: 'manga',
  desc: 'Лист для дизайна персонажа: одна фигура в 3–5 видах на общих линиях роста, чтобы пропорции совпадали во всех ракурсах',
  create: (c, s, d) => [{ x: 10, y: d.H * 0.1 }, { x: d.W - 10, y: d.H * 0.9 }],
  props: [
    { key: 'views', label: 'Видов', type: 'select', options: [['3', '3'], ['4', '4'], ['5', '5']], def: '4' },
    { key: 'heads', label: 'Рост в головах', type: 'range', min: 2, max: 9, step: 0.5, def: 7 },
    { key: 'build', label: 'Телосложение', type: 'select', options: [['neutral', 'Обычное'], ['female', 'Женское'], ['hero', 'Атлет'], ['child', 'Ребёнок']], def: 'neutral' },
    { key: 'headStyle', label: 'Голова', type: 'select', options: [['anime', 'Аниме'], ['shonen', 'Сёнэн'], ['real', 'Реализм ♂'], ['realF', 'Реализм ♀'], ['chibi', 'Чиби'], ['none', 'Простой овал']], def: 'anime' },
    { key: 'lines', label: 'Линии высот', type: 'toggle', def: true },
    { key: 'figs', label: 'Манекены', type: 'toggle', def: true },
  ],
  draw(pen, g, ctx) {
    const A = rectOf(g.pts[0], g.pts[1]), N = +P(g, 'heads'), k = (N - 1) / 7;
    const nV = (VIEWS[P(g, 'views')] || VIEWS[4]).length, wf0 = 0.55 + 0.45 * k;
    const bw = P(g, 'build') === 'hero' ? 1.12 : 1;
    // фигура должна поместиться и по высоте, и по ширине своей колонки
    const Hf = (A.y1 - A.y0) * 0.92, u = Math.min(Hf / N, (A.x1 - A.x0) / nV * 0.94 / (2 * (1.5 * wf0 * bw + 0.12))), top = A.y0 + (A.y1 - A.y0) * 0.04;
    const yOf = (t) => top + u * (t <= 1 ? t : 1 + (t - 1) * k);
    if (P(g, 'lines')) for (const [t, name] of MARKS) {
      if (t > 1 && N < 3.5 && (name === 'грудь' || name === 'колени')) continue;
      const y = yOf(t); if (y > A.y1 + 1) continue; pen.seg({ x: A.x0, y }, { x: A.x1, y }, 'aux');
      if (ctx.labels) pen.label({ x: A.x0 + 12, y: y - 3 }, name);
    }
    const views = VIEWS[P(g, 'views')] || VIEWS[4];
    const build = P(g, 'build'), bs = build === 'female' ? [0.86, 1.12] : build === 'child' ? [0.9, 0.95] : build === 'hero' ? [1.12, 1.0] : [1, 1];
    const wf = 0.55 + 0.45 * k, colW = (A.x1 - A.x0) / views.length;
    views.forEach(([deg, name], vi) => {
      const th = deg * D2R, cx = A.x0 + colW * (vi + 0.5), ct = Math.cos(th), st = Math.sin(th);
      pen.seg({ x: cx, y: top - 3 }, { x: cx, y: yOf(8) + 3 }, 'ghost');
      if (ctx.labels) pen.label({ x: cx, y: yOf(8) + 8 }, name);
      if (!P(g, 'figs')) return;
      const pos = BJ.map((n) => {
        const [x, t] = A_POSE[n], wide = /sh|el|wr|ha/.test(n) ? bs[0] : /hip|kn|an|to/.test(n) ? bs[1] : 1;
        const X = x * wf * wide, Z = ZDEPTH[n] || 0;
        return { x: cx + u * (X * ct + Z * st), y: yOf(t) };
      });
      const hs = P(g, 'headStyle');
      drawMannequin(pen, pos, u, { chestW: u * Math.hypot(0.8 * wf * bs[0] * ct, 0.5 * st), pelvisW: u * Math.hypot(0.72 * wf * bs[1] * ct, 0.45 * st), noHead: hs !== 'none' });
      if (hs !== 'none') {
        const o = { ...HEAD_PRESETS[hs], loomis: true, grid: true, neck: false, hair: false };
        const r = u / (1 + o.chin);
        drawHead(pen, o, { x: cx, y: top + r }, r, th, 0, 0);
      }
    });
  },
  handles(g) { const A = rectOf(g.pts[0], g.pts[1]); return [g.pts[0], g.pts[1], { x: (A.x0 + A.x1) / 2, y: (A.y0 + A.y1) / 2 }]; },
  drag(g, i, p) { if (i === 2) { const h = this.handles(g)[2], d = sub(p, h); g.pts = g.pts.map(q => add(q, d)); } else g.pts[i] = p; },
  moveIdx: 2,
};

// ======================================================================
// 8. ПРИЧЁСКИ — манекен волос (пряди в 3D поверх черепа)
// ======================================================================
const hairPreset = (v) => { const p = { ...HAIR_DEFAULTS, ...(HAIR_PRESETS[v] || {}) }; delete p.name; return p; };
const HAIR_KEYS = Object.keys(HAIR_DEFAULTS);
function randomHair(g, gender) {
  const keys = Object.keys(HAIR_PRESETS).filter(k => k.startsWith(gender + '_'));
  const k = keys[Math.floor(Math.random() * keys.length)], R = Math.random, p = hairPreset(k);
  p.len = clamp(p.len * (0.8 + 0.45 * R()), 0.6, 6); p.vol = clamp(p.vol + (R() - 0.5) * 0.15, 0, 0.6);
  p.wave = clamp(p.wave + (R() - 0.4) * 0.35, 0, 1); p.messy = clamp(R() * 0.8, 0, 1);
  if (R() < 0.4) p.bangs = ['none', 'straight', 'side', 'curtain', 'spiky', 'wispy'][Math.floor(R() * 6)];
  if (R() < 0.3) p.ends = ['straight', 'in', 'out'][Math.floor(R() * 3)];
  if (gender === 'f' && R() < 0.25) p.ahoge = !p.ahoge;
  Object.assign(g.props, p, { style: k, seed: 1 + Math.floor(R() * 99999) });
}
const hairT = {
  name: 'Причёски', icon: '💇', group: 'manga',
  desc: 'Манекен причёсок: готовые мужские и женские, всё настраивается — длина, объём, пробор, чёлка, хвосты, волна и кудри, шипы. «🎲» — перемешать пряди или собрать случайную причёску. Крутится как голова: тачпад справа',
  create: (c, s) => [{ x: c.x, y: c.y - s * 0.2 }],
  init: (g, s) => { g.props.r = Math.round(s * 0.5); Object.assign(g.props, hairPreset('f_long')); g.props.seed = 1 + Math.floor(Math.random() * 99999); },
  props: [
    { key: 'style', label: 'Причёска', type: 'select', options: HAIR_OPTIONS, def: 'f_long', onSet: (g, v) => { Object.assign(g.props, hairPreset(v)); } },
    { key: 'face', label: 'Под причёской', type: 'select', options: [['anime', 'Лицо аниме'], ['realF', 'Лицо реализм ♀'], ['real', 'Лицо реализм ♂'], ['skull', 'Только череп'], ['none', 'Ничего']], def: 'anime' },
    sec('Поворот головы'),
    { key: 'yaw', label: 'Влево ↔ вправо, °', type: 'range', min: -180, max: 180, step: 1, def: 20 },
    { key: 'pitch', label: 'Вниз ↔ вверх, °', type: 'range', min: -90, max: 90, step: 1, def: -5 },
    { key: 'roll', label: 'Наклон к плечу, °', type: 'range', min: -180, max: 180, step: 1, def: 0 },
    sec('Форма'),
    { key: 'len', label: 'Длина', type: 'range', min: 0.6, max: 6, step: 0.1, def: HAIR_DEFAULTS.len, fmt: (v) => v < 0.8 ? 'ёжик' : v < 1.4 ? 'короткие' : v < 2.4 ? 'до подбородка' : v < 3.5 ? 'до плеч' : v < 5 ? 'до груди' : 'до пояса' },
    { key: 'vol', label: 'Объём', type: 'range', min: 0, max: 0.6, step: 0.02, def: HAIR_DEFAULTS.vol },
    { key: 'part', label: 'Пробор', type: 'select', options: [['center', 'По центру'], ['side', 'Сбоку'], ['none', 'Зачёс назад']], def: 'center' },
    { key: 'bangs', label: 'Чёлка', type: 'select', options: [['none', 'Нет (лоб открыт)'], ['straight', 'Прямая'], ['side', 'Набок'], ['curtain', 'Шторка (на две стороны)'], ['spiky', 'Острые пряди (аниме)'], ['wispy', 'Рваная, тонкая']], def: 'side' },
    { key: 'bangLen', label: 'Длина чёлки', type: 'range', min: 0.1, max: 1.3, step: 0.05, def: 0.6, show: (g) => P(g, 'bangs') !== 'none', fmt: (v) => v < 0.45 ? 'короткая' : v < 0.8 ? 'до бровей' : v < 1.05 ? 'до глаз' : 'ниже глаз' },
    { key: 'tie', label: 'Собраны', type: 'select', options: [['none', 'Распущены'], ['pony', 'Хвост'], ['twin', 'Два хвоста'], ['bun', 'Пучок']], def: 'none' },
    { key: 'tailLen', label: 'Длина хвоста', type: 'range', min: 0.8, max: 6, step: 0.1, def: 3, show: (g) => ['pony', 'twin'].includes(P(g, 'tie')) },
    { key: 'locks', label: 'Пряди у лица', type: 'toggle', def: false },
    { key: 'ahoge', label: 'Ахогэ («антенна»)', type: 'toggle', def: false },
    sec('Характер'),
    { key: 'wave', label: 'Прямые → волна → кудри', type: 'range', min: 0, max: 1, step: 0.05, def: 0.1 },
    { key: 'spiky', label: 'Шипы (сёнэн)', type: 'range', min: 0, max: 1, step: 0.05, def: 0 },
    { key: 'ends', label: 'Кончики', type: 'select', options: [['straight', 'Прямые'], ['in', 'Внутрь'], ['out', 'Наружу']], def: 'straight' },
    { key: 'messy', label: 'Аккуратно ↔ небрежно', type: 'range', min: 0, max: 1, step: 0.05, def: 0.25 },
    sec('Штрихи'),
    { key: 'clumps', label: 'Прядей: мало ↔ много', type: 'range', min: 0, max: 1, step: 0.05, def: 0.5 },
    { key: 'detail', label: 'Штрихи внутри прядей', type: 'range', min: 0, max: 1, step: 0.05, def: 0.4, fmt: (v) => v < 0.3 ? 'минимум' : v < 0.7 ? 'немного' : 'подробно' },
    sec('Ветер'),
    { key: 'windAmt', label: 'Сила ветра', type: 'range', min: 0, max: 1, step: 0.05, def: 0 },
    { key: 'windDir', label: 'Дует: → 0°, ↑ 90°, ← 180°', type: 'range', min: -180, max: 180, step: 5, def: 0, show: (g) => P(g, 'windAmt') > 0 },
    { key: 'windT', label: '', type: 'hidden', def: 0 },
    { key: 'r', label: 'Размер черепа (радиус), мм', type: 'range', min: 5, max: 150, step: 1, def: 30 },
  ],
  actions: [
    ['🎲 Перемешать пряди', (g) => { g.props.seed = 1 + Math.floor(Math.random() * 99999); }],
    ['🎲 Случайная ♀', (g) => randomHair(g, 'f')],
    ['🎲 Случайная ♂', (g) => randomHair(g, 'm')],
  ],
  moveIdx: 0,
  geo: (g) => head.geo(g),
  draw(pen, g, ctx) {
    const { C, r, yaw, pitch, roll } = this.geo(g), face = P(g, 'face');
    const o = {}; for (const k of HAIR_KEYS) o[k] = P(g, k);
    let chin = 1.3;
    if (face === 'skull') pen.circle(C, r, 'aux');
    else if (face !== 'none') { const ho = { ...(HEAD_PRESETS[face] || HEAD_PRESETS.anime), loomis: false, grid: false, neck: true, hair: false, brows: true }; chin = ho.chin; drawHead(pen, ho, C, r, yaw, pitch, roll, { layer: 'aux' }); }
    drawHair(pen, o, C, r, yaw, pitch, roll, +P(g, 'seed') || 1, { chin, wind: windOf(g) });
    const T = headPad(C, r);
    pen.circle(T.c, T.r, 'ghost'); pen.seg({ x: T.c.x - T.r, y: T.c.y }, { x: T.c.x + T.r, y: T.c.y }, 'ghost'); pen.seg({ x: T.c.x, y: T.c.y - T.r }, { x: T.c.x, y: T.c.y + T.r }, 'ghost');
    if (ctx.labels) pen.label({ x: C.x, y: C.y - r * (1.45 + (+P(g, 'vol') || 0)) }, (HAIR_PRESETS[P(g, 'style')] || {}).name || 'причёска');
  },
  handles(g) { return head.handles.call(this, g); },
  drag(g, i, p) { return head.drag.call(this, g, i, p); },
  handleLabel: (g, i) => (i === 0 ? 'двигать' : i === 1 ? 'размер · наклон' : 'поворот'),
};

export const MANGA_ORDER = ['head', 'hair', 'eye', 'body', 'hand', 'turn', 'panels', 'speed', 'focus'];
export function registerManga(TYPES) {
  TYPES_REF = TYPES;
  Object.assign(TYPES, { head, hair: hairT, body, hand, eye, panels, speed, focus, turn });
}
