// Типы AR-направляющих. Все точки — в миллиметрах листа (0,0 — левый верхний угол).
// Каждый тип описывает: создание, параметры (для автопанели), отрисовку и ручки.

import { convexHull } from './geom.js';
import {
  apply, add, sub, mulS, dot, len, dist, norm, perp, lerpP, reflect, clipSegment,
  circleFrom3, homography, mul, inv,
} from './geom.js';

const TAU = Math.PI * 2;
const deg = (r) => r * 180 / Math.PI;
const fmtCm = (mm) => (mm / 10).toFixed(1).replace('.', ',') + ' см';
const fmtMm = (mm) => Math.round(mm) + ' мм';
const angleOf = (v) => { let a = -deg(Math.atan2(v.y, v.x)); a = ((a % 180) + 180) % 180; return Math.round(a) + '°'; };

// «Ручка»: рисует в мм листа, а сохраняет уже экранные полилинии.
export class Pen {
  constructor(P2S, clip) {
    this.M = P2S; this.clip = clip;
    this.paths = []; this.labels = []; this.points = [];
    this.mirror = null; this.layerOverride = null; this.guideId = null;
    this.L = null; // поворот/наклон фигуры (гомография в мм листа), см. planeH
  }
  tf(p) {
    if (this.L) { const r = apply(this.L, p.x, p.y); p = r.w > 1e-3 ? { x: r.x, y: r.y } : { x: NaN, y: NaN }; }
    return this.mirror ? reflect(p, this.mirror.a, this.mirror.b) : p;
  }
  mapRaw(p) { const r = apply(this.M, p.x, p.y); return r.w > 0 && isFinite(r.x) && isFinite(r.y) ? r : null; }
  pushPath(pts, closed, layer) {
    if (pts.length < 2) return;
    this.paths.push({ pts, closed, layer: this.layerOverride || layer, id: this.guideId });
  }
  polyRaw(pts, closed, layer) {
    let cur = [], broken = false;
    for (const p of pts) {
      const m = this.mapRaw(p);
      if (!m) { broken = true; this.pushPath(cur, false, layer); cur = []; continue; }
      cur.push(m);
    }
    this.pushPath(cur, closed && !broken, layer);
  }
  poly(pts, closed = false, layer = 'main') { this.polyRaw(pts.map(p => this.tf(p)), closed, layer); }
  seg(a, b, layer = 'main', clip = this.clip) {
    const c = clipSegment(this.tf(a), this.tf(b), clip);
    if (c) this.polyRaw(c, false, layer);
  }
  inf(p, d, layer = 'main', clip = this.clip) { const L = 1e5, u = norm(d); this.seg(sub(p, mulS(u, L)), add(p, mulS(u, L)), layer, clip); }
  ray(p, d, layer = 'main') { this.seg(p, add(p, mulS(norm(d), 1e5)), layer); }
  arc(c, r, a0, a1, layer = 'main', closed = false) {
    const span = a1 - a0;
    const n = Math.max(24, Math.min(240, Math.ceil(Math.abs(span) / TAU * 160)));
    const pts = [];
    for (let i = 0; i <= n; i++) { const a = a0 + span * i / n; pts.push({ x: c.x + Math.cos(a) * r, y: c.y + Math.sin(a) * r }); }
    if (closed) pts.pop();
    this.poly(pts, closed, layer);
  }
  circle(c, r, layer = 'main') { this.arc(c, r, 0, TAU, layer, true); }
  ellipse(c, A, B, rot, layer = 'main') {
    const pts = [], n = 160, cs = Math.cos(rot), sn = Math.sin(rot);
    for (let i = 0; i < n; i++) {
      const t = TAU * i / n, x = Math.cos(t) * A, y = Math.sin(t) * B;
      pts.push({ x: c.x + x * cs - y * sn, y: c.y + x * sn + y * cs });
    }
    this.poly(pts, true, layer);
  }
  // Заливка (тени). holes — области, которые не закрашивать (например, сам предмет).
  fill(pts, holes = [], layer = 'shade') {
    const map = (arr) => { const o = []; for (const p of arr) { const m = this.mapRaw(this.tf(p)); if (!m) return null; o.push(m); } return o; };
    const P = map(pts); if (!P || P.length < 3) return;
    const H = holes.map(map).filter(Boolean);
    this.paths.push({ pts: P, closed: true, fill: true, holes: H, layer: this.layerOverride || layer, id: this.guideId });
  }
  label(p, text) { const m = this.mapRaw(this.tf(p)); if (m && !this.mirror) this.labels.push({ x: m.x, y: m.y, text }); }
  dot(p, layer = 'main') { const m = this.mapRaw(this.tf(p)); if (m) this.points.push({ x: m.x, y: m.y, layer: this.layerOverride || layer, id: this.guideId }); }
}

// Веер лучей из точки схода, покрывающий область листа.
function fan(pen, vp, rect, count, layer) {
  const corners = [{ x: rect.x0, y: rect.y0 }, { x: rect.x1, y: rect.y0 }, { x: rect.x1, y: rect.y1 }, { x: rect.x0, y: rect.y1 }];
  const inside = vp.x > rect.x0 && vp.x < rect.x1 && vp.y > rect.y0 && vp.y < rect.y1;
  if (inside) {
    for (let i = 0; i < count; i++) { const a = TAU * i / count; pen.seg(vp, add(vp, mulS({ x: Math.cos(a), y: Math.sin(a) }, 1e5)), layer, rect); }
    return;
  }
  const mid = { x: (rect.x0 + rect.x1) / 2, y: (rect.y0 + rect.y1) / 2 };
  const base = Math.atan2(mid.y - vp.y, mid.x - vp.x);
  let lo = Infinity, hi = -Infinity;
  for (const c of corners) {
    let a = Math.atan2(c.y - vp.y, c.x - vp.x) - base;
    while (a > Math.PI) a -= TAU; while (a < -Math.PI) a += TAU;
    lo = Math.min(lo, a); hi = Math.max(hi, a);
  }
  for (let i = 0; i < count; i++) {
    const a = base + lo + (hi - lo) * (count === 1 ? 0.5 : i / (count - 1));
    pen.seg(vp, add(vp, mulS({ x: Math.cos(a), y: Math.sin(a) }, 1e5)), layer, rect);
  }
}

// Параллельные линии с шагом step, перпендикуляр n, через точку o — по всей области.
function parallels(pen, o, dir, step, rect, layer, maxLines = 220) {
  const n = perp(norm(dir));
  const cs = [{ x: rect.x0, y: rect.y0 }, { x: rect.x1, y: rect.y0 }, { x: rect.x1, y: rect.y1 }, { x: rect.x0, y: rect.y1 }];
  let lo = Infinity, hi = -Infinity;
  for (const c of cs) { const d = dot(sub(c, o), n); lo = Math.min(lo, d); hi = Math.max(hi, d); }
  const k0 = Math.ceil(lo / step), k1 = Math.floor(hi / step);
  if (k1 - k0 > maxLines) return;
  for (let k = k0; k <= k1; k++) pen.inf(add(o, mulS(n, k * step)), dir, layer, rect);
}

const translateAll = (g, i, p, centerIdx = 0) => {
  const h = TYPES[g.type].handles(g)[centerIdx];
  const d = sub(p, h);
  g.pts = g.pts.map(q => add(q, d));
};

const pDefault = (g, k) => (g.props && g.props[k] !== undefined ? g.props[k] : TYPES[g.type].props.find(x => x.key === k)?.def);

export const TYPES = {
  line: {
    name: 'Прямая', icon: '╱', desc: 'Отрезок или бесконечная линия по двум точкам',
    create: (c, s) => [{ x: c.x - s, y: c.y }, { x: c.x + s, y: c.y }],
    props: [
      { key: 'extend', label: 'Вид', type: 'select', options: [['seg', 'Отрезок'], ['line', 'Бесконечная']], def: 'seg' },
      { key: 'ticks', label: 'Деления через 1 см', type: 'toggle', def: false },
      { key: 'perpMid', label: 'Перпендикуляр через середину', type: 'toggle', def: false },
      { key: 'thirds', label: 'Отметки ½ и ⅓', type: 'toggle', def: false },
    ],
    draw(pen, g, ctx) {
      const [a, b] = g.pts, d = sub(b, a), L = len(d), u = norm(d), n = perp(u);
      if (pDefault(g, 'extend') === 'line') { pen.inf(a, d); pen.dot(a); pen.dot(b); } else pen.seg(a, b);
      if (pDefault(g, 'ticks') && L > 1) {
        for (let mm = 0; mm <= L + 0.01; mm += 10) {
          const p = add(a, mulS(u, mm)), big = Math.round(mm) % 50 === 0;
          pen.seg(sub(p, mulS(n, big ? 4 : 2.2)), add(p, mulS(n, big ? 4 : 2.2)), 'aux');
        }
      }
      if (pDefault(g, 'perpMid')) pen.inf(lerpP(a, b, 0.5), n, 'aux');
      if (pDefault(g, 'thirds')) {
        for (const t of [1 / 3, 0.5, 2 / 3]) {
          const p = lerpP(a, b, t), k = t === 0.5 ? 5 : 3;
          pen.seg(sub(p, mulS(n, k)), add(p, mulS(n, k)), 'aux');
        }
      }
      if (ctx.labels) pen.label(add(lerpP(a, b, 0.5), mulS(n, -6)), `${fmtCm(L)} · ${angleOf(d)}`);
    },
    handles: (g) => g.pts,
    drag(g, i, p) { g.pts[i] = p; },
    dirPair: [0, 1],
  },

  parallel: {
    name: 'Параллели', icon: '☰', desc: 'Набор параллельных линий с шагом — для текста, штриховки, наклона',
    create: (c, s) => [{ x: c.x - s, y: c.y }, { x: c.x + s, y: c.y }, { x: c.x, y: c.y - 10 }],
    props: [
      { key: 'cross', label: 'Добавить перпендикулярные', type: 'toggle', def: false },
    ],
    geo(g) {
      const [a, b, c] = g.pts, d = sub(b, a), u = norm(d), n = perp(u);
      let s = dot(sub(c, a), n); if (Math.abs(s) < 1) s = s < 0 ? -1 : 1;
      return { a, b, d, u, n, s };
    },
    draw(pen, g, ctx) {
      const { a, b, d, n, s } = this.geo(g);
      pen.seg(a, b);
      parallels(pen, a, d, Math.abs(s), ctx.rect, 'aux');
      if (pDefault(g, 'cross')) parallels(pen, a, n, Math.abs(s), ctx.rect, 'aux');
      if (ctx.labels) pen.label(add(lerpP(a, b, 0.5), mulS(n, s / 2)), `шаг ${fmtMm(Math.abs(s))} · ${angleOf(d)}`);
    },
    handles(g) { const { a, b, n, s } = this.geo(g); return [a, b, add(lerpP(a, b, 0.5), mulS(n, s))]; },
    drag(g, i, p) { g.pts[i] = p; },
    dirPair: [0, 1],
  },

  circle: {
    name: 'Круг', icon: '◯', desc: 'Окружность: центр и радиус, можно концентрические',
    create: (c, s) => [{ ...c }, { x: c.x + s, y: c.y }],
    props: [
      { key: 'rings', label: 'Концентрических', type: 'range', min: 1, max: 10, step: 1, def: 1 },
      { key: 'cross', label: 'Крест через центр', type: 'toggle', def: true },
      { key: 'box', label: 'Описанный квадрат', type: 'toggle', def: false },
    ],
    draw(pen, g, ctx) {
      const [c, e] = g.pts, r = dist(c, e), k = pDefault(g, 'rings');
      for (let i = 1; i <= k; i++) pen.circle(c, r * i / k, i === k ? 'main' : 'aux');
      if (pDefault(g, 'cross')) {
        pen.seg({ x: c.x - r * 1.15, y: c.y }, { x: c.x + r * 1.15, y: c.y }, 'aux');
        pen.seg({ x: c.x, y: c.y - r * 1.15 }, { x: c.x, y: c.y + r * 1.15 }, 'aux');
      }
      if (pDefault(g, 'box')) pen.poly([{ x: c.x - r, y: c.y - r }, { x: c.x + r, y: c.y - r }, { x: c.x + r, y: c.y + r }, { x: c.x - r, y: c.y + r }], true, 'aux');
      pen.dot(c, 'aux');
      if (ctx.labels) pen.label({ x: c.x, y: c.y - r - 5 }, `R ${fmtCm(r)} · Ø ${fmtCm(2 * r)}`);
    },
    handles: (g) => g.pts,
    drag(g, i, p) { if (i === 0) translateAll(g, i, p); else g.pts[1] = p; },
  },

  ellipse: {
    name: 'Эллипс', icon: '⬭', desc: 'Эллипс с поворотом: центр, большая и малая полуоси',
    create: (c, s) => [{ ...c }, { x: c.x + s, y: c.y }, { x: c.x, y: c.y - s * 0.55 }],
    props: [
      { key: 'axes', label: 'Оси', type: 'toggle', def: true },
      { key: 'box', label: 'Описанный прямоугольник', type: 'toggle', def: false },
    ],
    geo(g) {
      const [c, a, bRaw] = g.pts, u = norm(sub(a, c)), n = perp(u);
      const A = dist(c, a), B = Math.max(1, Math.abs(dot(sub(bRaw, c), n)));
      return { c, a, u, n, A, B, rot: Math.atan2(u.y, u.x) };
    },
    draw(pen, g, ctx) {
      const { c, u, n, A, B, rot } = this.geo(g);
      pen.ellipse(c, A, B, rot);
      if (pDefault(g, 'axes')) { pen.seg(sub(c, mulS(u, A * 1.1)), add(c, mulS(u, A * 1.1)), 'aux'); pen.seg(sub(c, mulS(n, B * 1.15)), add(c, mulS(n, B * 1.15)), 'aux'); }
      if (pDefault(g, 'box')) {
        const p = (x, y) => add(c, add(mulS(u, x), mulS(n, y)));
        pen.poly([p(-A, -B), p(A, -B), p(A, B), p(-A, B)], true, 'aux');
      }
      if (ctx.labels) pen.label(sub(c, mulS(n, B + 6)), `${fmtCm(2 * A)} × ${fmtCm(2 * B)}`);
    },
    handles(g) { const { c, a, n, B } = this.geo(g); const sgn = Math.sign(dot(sub(g.pts[2], c), n)) || -1; return [c, a, add(c, mulS(n, B * sgn))]; },
    drag(g, i, p) { if (i === 0) translateAll(g, i, p); else g.pts[i] = p; },
  },

  rect: {
    name: 'Прямоугольник', icon: '▭', desc: 'Прямоугольник или квадрат под любым углом',
    create: (c, s) => [{ x: c.x - s, y: c.y + s * 0.6 }, { x: c.x + s, y: c.y + s * 0.6 }, { x: c.x, y: c.y - s * 0.6 }],
    props: [
      { key: 'square', label: 'Квадрат', type: 'toggle', def: false },
      { key: 'diag', label: 'Диагонали', type: 'toggle', def: false },
      { key: 'mid', label: 'Средние линии', type: 'toggle', def: false },
    ],
    geo(g) {
      const [p0, p1, p2] = g.pts, u = norm(sub(p1, p0)), n = perp(u), L = dist(p0, p1);
      let h = dot(sub(p2, p0), n); if (Math.abs(h) < 1) h = h < 0 ? -1 : 1;
      if (pDefault(g, 'square')) h = Math.sign(h) * L;
      const q = [p0, p1, add(p1, mulS(n, h)), add(p0, mulS(n, h))];
      return { q, u, n, L, h, center: lerpP(q[0], q[2], 0.5) };
    },
    draw(pen, g, ctx) {
      const { q, L, h, n } = this.geo(g);
      pen.poly(q, true);
      if (pDefault(g, 'diag')) { pen.seg(q[0], q[2], 'aux'); pen.seg(q[1], q[3], 'aux'); }
      if (pDefault(g, 'mid')) { pen.seg(lerpP(q[0], q[1], 0.5), lerpP(q[2], q[3], 0.5), 'aux'); pen.seg(lerpP(q[1], q[2], 0.5), lerpP(q[3], q[0], 0.5), 'aux'); }
      if (ctx.labels) pen.label(add(lerpP(q[0], q[1], 0.5), mulS(n, -Math.sign(h) * 6)), `${fmtCm(L)} × ${fmtCm(Math.abs(h))}`);
    },
    handles(g) { const { q, center } = this.geo(g); return [q[0], q[1], lerpP(q[2], q[3], 0.5), center]; },
    drag(g, i, p) { if (i === 3) translateAll(g, i, p, 3); else g.pts[i] = p; },
    dirPair: [0, 1],
  },

  polygon: {
    name: 'Многоугольник', icon: '⬡', desc: 'Правильный многоугольник или звезда',
    create: (c, s) => [{ ...c }, { x: c.x, y: c.y - s }],
    props: [
      { key: 'sides', label: 'Углов', type: 'range', min: 3, max: 16, step: 1, def: 6 },
      { key: 'star', label: 'Звезда', type: 'toggle', def: false },
      { key: 'inner', label: 'Глубина звезды', type: 'range', min: 0.2, max: 0.9, step: 0.05, def: 0.5, show: (g) => pDefault(g, 'star') },
      { key: 'spokes', label: 'Лучи из центра', type: 'toggle', def: false },
      { key: 'circ', label: 'Описанная окружность', type: 'toggle', def: false },
    ],
    draw(pen, g, ctx) {
      const [c, v] = g.pts, r = dist(c, v), a0 = Math.atan2(v.y - c.y, v.x - c.x);
      const n = pDefault(g, 'sides'), star = pDefault(g, 'star'), k = pDefault(g, 'inner');
      const pts = [], outer = [];
      const steps = star ? n * 2 : n;
      for (let i = 0; i < steps; i++) {
        const a = a0 + TAU * i / steps, rr = star && i % 2 ? r * k : r;
        const p = { x: c.x + Math.cos(a) * rr, y: c.y + Math.sin(a) * rr };
        pts.push(p); if (!star || i % 2 === 0) outer.push(p);
      }
      pen.poly(pts, true);
      if (pDefault(g, 'spokes')) for (const p of outer) pen.seg(c, p, 'aux');
      if (pDefault(g, 'circ')) pen.circle(c, r, 'aux');
      pen.dot(c, 'aux');
      if (ctx.labels) pen.label({ x: c.x, y: c.y + r + 6 }, `${n} · сторона ${fmtCm(2 * r * Math.sin(Math.PI / n))}`);
    },
    handles: (g) => g.pts,
    drag(g, i, p) { if (i === 0) translateAll(g, i, p); else g.pts[1] = p; },
  },

  arc: {
    name: 'Дуга', icon: '◠', desc: 'Плавная дуга через три точки',
    create: (c, s) => [{ x: c.x - s, y: c.y + s * 0.3 }, { x: c.x, y: c.y - s * 0.4 }, { x: c.x + s, y: c.y + s * 0.3 }],
    props: [
      { key: 'full', label: 'Показать весь круг', type: 'toggle', def: false },
      { key: 'chord', label: 'Хорда', type: 'toggle', def: false },
    ],
    draw(pen, g, ctx) {
      const [a, m, b] = g.pts, C = circleFrom3(a, m, b);
      if (!C || C.r > 1e4) { pen.seg(a, b); return; }
      const ang = (p) => Math.atan2(p.y - C.c.y, p.x - C.c.x);
      let a0 = ang(a), a1 = ang(b), am = ang(m);
      const norm2 = (x) => ((x % TAU) + TAU) % TAU;
      // проходим от a к b через m
      const ccw = norm2(am - a0) < norm2(a1 - a0);
      let span = ccw ? norm2(a1 - a0) : -norm2(a0 - a1);
      pen.arc(C.c, C.r, a0, a0 + span);
      if (pDefault(g, 'full')) pen.circle(C.c, C.r, 'aux');
      if (pDefault(g, 'chord')) pen.seg(a, b, 'aux');
      if (ctx.labels) pen.label(add(m, mulS(norm(sub(m, C.c)), 6)), `R ${fmtCm(C.r)}`);
    },
    handles: (g) => g.pts,
    drag(g, i, p) { g.pts[i] = p; },
  },

  grid: {
    name: 'Сетка', icon: '#', desc: 'Клетка на весь лист: размер и поворот ручкой',
    create: (c, s) => [{ ...c }, { x: c.x + 20, y: c.y }],
    props: [
      { key: 'diag', label: 'Диагонали клеток', type: 'toggle', def: false },
      { key: 'sub', label: 'Полуклетки', type: 'toggle', def: false },
    ],
    draw(pen, g, ctx) {
      const [o, u] = g.pts, d = sub(u, o), s = Math.max(2, len(d)), n = perp(d);
      parallels(pen, o, d, s, ctx.rect, 'aux');
      parallels(pen, o, n, s, ctx.rect, 'aux');
      pen.seg(o, u);
      if (pDefault(g, 'sub')) {
        const off = add(o, mulS(add(norm(d), norm(n)), s / 2));
        parallels(pen, off, d, s, ctx.rect, 'aux'); parallels(pen, off, n, s, ctx.rect, 'aux');
      }
      if (pDefault(g, 'diag')) {
        const d1 = add(norm(d), norm(n)), d2 = sub(norm(d), norm(n));
        parallels(pen, o, d1, s / Math.SQRT2, ctx.rect, 'aux'); parallels(pen, o, d2, s / Math.SQRT2, ctx.rect, 'aux');
      }
      if (ctx.labels) pen.label(add(lerpP(o, u, 0.5), mulS(norm(n), -5)), `клетка ${fmtMm(s)}`);
    },
    handles: (g) => g.pts,
    drag(g, i, p) { if (i === 0) translateAll(g, i, p); else g.pts[1] = p; },
    dirPair: [0, 1],
    roundLen: true,
  },

  persp: {
    name: 'Перспектива', icon: '⟁', desc: '1, 2 или 3 точки схода с веером линий и горизонтом',
    create: (c, s, ctx) => [
      { x: ctx.W * 0.06, y: ctx.H * 0.38 },
      { x: ctx.W * 0.94, y: ctx.H * 0.38 },
      { x: ctx.W * 0.5, y: ctx.H * 0.96 },
    ],
    props: [
      { key: 'vps', label: 'Точек схода', type: 'select', options: [[1, '1'], [2, '2'], [3, '3']], def: 2 },
      { key: 'rays', label: 'Лучей из точки', type: 'range', min: 4, max: 60, step: 1, def: 18 },
      { key: 'horizon', label: 'Линия горизонта', type: 'toggle', def: true },
      { key: 'verticals', label: 'Вертикали / сетка', type: 'toggle', def: true, show: (g) => +pDefault(g, 'vps') < 3 },
    ],
    draw(pen, g, ctx) {
      const k = +pDefault(g, 'vps'), rays = pDefault(g, 'rays');
      const [v1, v2, v3] = g.pts;
      const R = { x0: -ctx.W * 0.03, y0: -ctx.H * 0.03, x1: ctx.W * 1.03, y1: ctx.H * 1.03 };
      let hDir = { x: 1, y: 0 };
      if (k >= 2) hDir = sub(v2, v1);
      if (pDefault(g, 'horizon')) pen.inf(v1, hDir, 'main');
      fan(pen, v1, R, rays, 'aux');
      if (k >= 2) fan(pen, v2, R, rays, 'aux');
      if (k >= 3) fan(pen, v3, R, rays, 'aux');
      if (k < 3 && pDefault(g, 'verticals')) {
        const step = Math.max(ctx.W, ctx.H) / 12;
        parallels(pen, v1, perp(hDir), step, ctx.rect, 'aux');
        if (k === 1) parallels(pen, v1, hDir, step, ctx.rect, 'aux');
      }
      const names = ['Т1', 'Т2', 'Т3'];
      [v1, v2, v3].slice(0, k).forEach((v, i) => { pen.dot(v); if (ctx.labels) pen.label({ x: v.x, y: v.y - 7 }, names[i]); });
    },
    handles(g) { return g.pts.slice(0, +pDefault(g, 'vps')); },
    drag(g, i, p) { g.pts[i] = p; },
  },

  pellipse: {
    name: 'Круг в перспективе', icon: '⊙', desc: 'Квадрат в перспективе и вписанный в него круг (колёса, кружки, цилиндры)',
    create: (c, s) => [
      { x: c.x - s * 0.8, y: c.y - s * 0.35 }, { x: c.x + s * 0.8, y: c.y - s * 0.35 },
      { x: c.x + s * 1.1, y: c.y + s * 0.45 }, { x: c.x - s * 1.1, y: c.y + s * 0.45 },
    ],
    props: [
      { key: 'quad', label: 'Квадрат', type: 'toggle', def: true },
      { key: 'cross', label: 'Средние линии', type: 'toggle', def: true },
      { key: 'diag', label: 'Диагонали', type: 'toggle', def: false },
    ],
    draw(pen, g) {
      const q = g.pts;
      const H = homography([{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }], q);
      if (!H) { pen.poly(q, true); return; }
      const m = (x, y) => { const r = apply(H, x, y); return { x: r.x, y: r.y }; };
      const pts = [];
      for (let i = 0; i < 160; i++) { const t = TAU * i / 160; pts.push(m(0.5 + 0.5 * Math.cos(t), 0.5 + 0.5 * Math.sin(t))); }
      pen.poly(pts, true);
      if (pDefault(g, 'quad')) pen.poly(q, true, 'aux');
      if (pDefault(g, 'cross')) { pen.seg(m(0.5, 0), m(0.5, 1), 'aux'); pen.seg(m(0, 0.5), m(1, 0.5), 'aux'); }
      if (pDefault(g, 'diag')) { pen.seg(q[0], q[2], 'aux'); pen.seg(q[1], q[3], 'aux'); }
      pen.dot(m(0.5, 0.5), 'aux');
    },
    handles(g) {
      const q = g.pts;
      const H = homography([{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }], q);
      const c = H ? apply(H, 0.5, 0.5) : lerpP(q[0], q[2], 0.5);
      return [...q, { x: c.x, y: c.y }];
    },
    drag(g, i, p) { if (i === 4) translateAll(g, i, p, 4); else g.pts[i] = p; },
  },

  symmetry: {
    name: 'Ось симметрии', icon: '⫼', desc: 'Ось, поперечные метки и зеркальные копии других направляющих',
    create: (c, s) => [{ x: c.x, y: c.y - s }, { x: c.x, y: c.y + s }],
    props: [
      { key: 'ticks', label: 'Поперечные линии', type: 'toggle', def: true },
      { key: 'step', label: 'Шаг меток, мм', type: 'range', min: 5, max: 50, step: 1, def: 10, show: (g) => pDefault(g, 'ticks') },
      { key: 'mirror', label: 'Зеркалить другие направляющие', type: 'toggle', def: true },
    ],
    draw(pen, g, ctx) {
      const [a, b] = g.pts, d = sub(b, a);
      pen.inf(a, d, 'main');
      if (pDefault(g, 'ticks')) {
        const step = pDefault(g, 'step'), u = norm(d), n = perp(u);
        // короткие поперечные линии по всей длине оси в пределах области
        const R = ctx.rect;
        const cs = [{ x: R.x0, y: R.y0 }, { x: R.x1, y: R.y0 }, { x: R.x1, y: R.y1 }, { x: R.x0, y: R.y1 }];
        let lo = Infinity, hi = -Infinity;
        for (const c of cs) { const t = dot(sub(c, a), u); lo = Math.min(lo, t); hi = Math.max(hi, t); }
        const half = Math.max(ctx.W, ctx.H);
        for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) {
          const p = add(a, mulS(u, t));
          pen.seg(sub(p, mulS(n, half)), add(p, mulS(n, half)), 'aux', R);
        }
      }
      pen.dot(a); pen.dot(b);
    },
    handles: (g) => g.pts,
    drag(g, i, p) { g.pts[i] = p; },
    dirPair: [0, 1],
  },

  radial: {
    name: 'Мандала', icon: '✳', desc: 'Лучи из центра и кольца — радиальная симметрия',
    create: (c, s) => [{ ...c }, { x: c.x + s, y: c.y }],
    props: [
      { key: 'rays', label: 'Лучей', type: 'range', min: 2, max: 48, step: 1, def: 12 },
      { key: 'rings', label: 'Колец', type: 'range', min: 0, max: 12, step: 1, def: 3 },
      { key: 'toEdge', label: 'Лучи до краёв листа', type: 'toggle', def: false },
    ],
    draw(pen, g, ctx) {
      const [c, e] = g.pts, r = dist(c, e), a0 = Math.atan2(e.y - c.y, e.x - c.x);
      const n = pDefault(g, 'rays'), k = pDefault(g, 'rings');
      for (let i = 0; i < n; i++) {
        const a = a0 + TAU * i / n, d = { x: Math.cos(a), y: Math.sin(a) };
        if (pDefault(g, 'toEdge')) pen.seg(c, add(c, mulS(d, 1e5)), i ? 'aux' : 'main', ctx.rect);
        else pen.seg(c, add(c, mulS(d, r)), i ? 'aux' : 'main');
      }
      for (let i = 1; i <= k; i++) pen.circle(c, r * i / k, i === k ? 'main' : 'aux');
      if (ctx.labels) pen.label({ x: c.x, y: c.y - r - 5 }, `${n} лучей · ${(360 / n).toFixed(n % 8 === 0 || 360 % n === 0 ? 0 : 1)}°`);
    },
    handles: (g) => g.pts,
    drag(g, i, p) { if (i === 0) translateAll(g, i, p); else g.pts[1] = p; },
  },
  light: {
    name: 'Свет и тень', icon: '☀', desc: 'Фигура и лампа: где блик, где граница света, своя и падающая тень. Тяни ☀, чтобы двигать свет',
    create: (c, s) => [{ x: c.x, y: c.y + s * 0.6 }, { x: c.x + s * 0.7, y: c.y + s * 0.6 }, { x: c.x - s * 1.3, y: c.y - s * 1.5 }],
    props: [
      { key: 'shape', label: 'Фигура', type: 'select', options: [['sphere', 'Шар'], ['cube', 'Куб'], ['cyl', 'Цилиндр'], ['cone', 'Конус']], def: 'sphere' },
      { key: 'depth', label: 'Свет: сзади ↔ спереди, °', type: 'range', min: -75, max: 75, step: 5, def: 30 },
      { key: 'view', label: 'Взгляд сверху, °', type: 'range', min: 0, max: 60, step: 5, def: 25 },
      { key: 'height', label: 'Высота', type: 'range', min: 0.5, max: 3, step: 0.1, def: 1.5, show: (g) => ['cyl', 'cone'].includes(pDefault(g, 'shape')) },
      { key: 'yaw', label: 'Поворот куба, °', type: 'range', min: 0, max: 90, step: 5, def: 30, show: (g) => pDefault(g, 'shape') === 'cube' },
      { key: 'cast', label: 'Падающая тень', type: 'toggle', def: true },
      { key: 'shade', label: 'Заливка тени', type: 'toggle', def: true },
    ],
    draw(pen, g, ctx) { drawLight(pen, g, ctx); },
    handles: (g) => g.pts,
    drag(g, i, p) { if (i === 0) translateAll(g, i, p); else g.pts[i] = p; },
  },
};

export const TYPE_ORDER = ['line', 'parallel', 'circle', 'ellipse', 'rect', 'polygon', 'arc', 'grid', 'persp', 'pellipse', 'symmetry', 'radial', 'light'];

export function getProp(g, k) { return pDefault(g, k); }

export function defaultProps(type) {
  const o = {};
  for (const p of TYPES[type].props) o[p.key] = p.def;
  return o;
}

// ---------- «Свет и тень»: мини-3D ----------
// Мир: x вправо, y вверх, z к зрителю. Земля — плоскость y=0. Ортографический вид
// со взглядом сверху под углом e. Свет — направленный (как солнце или далёкая лампа).
const v3 = { add: (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], sc: (a, k) => [a[0] * k, a[1] * k, a[2] * k], dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2], cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]], norm: (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; } };

// Непрерывный участок по кругу, где cond=true (самый длинный). Возвращает индексы по порядку.
function runs(n, cond) {
  const ok = []; for (let i = 0; i < n; i++) ok.push(!!cond(i));
  if (ok.every(Boolean)) return [[...Array(n).keys()]];
  const start = ok.indexOf(false);
  const out = []; let cur = [];
  for (let k = 1; k <= n; k++) { const i = (start + k) % n; if (ok[i]) cur.push(i); else if (cur.length) { out.push(cur); cur = []; } }
  if (cur.length) out.push(cur);
  return out;
}

function drawLight(pen, g, ctx) {
  const [c, sz, lp] = g.pts;
  const r = Math.max(3, dist(c, sz));
  const e = pDefault(g, 'view') * Math.PI / 180;
  const right = [1, 0, 0], up = [0, Math.cos(e), -Math.sin(e)], toV = [0, Math.sin(e), Math.cos(e)];
  const P = (q) => ({ x: c.x + v3.dot(q, right), y: c.y - v3.dot(q, up) });
  // направление на свет: куда на картинке + спереди/сзади
  const a = norm(sub(lp, c)), dl = pDefault(g, 'depth') * Math.PI / 180;
  const L = v3.norm(v3.add(v3.add(v3.sc(right, a.x * Math.cos(dl)), v3.sc(up, -a.y * Math.cos(dl))), v3.sc(toV, Math.sin(dl))));
  const shape = pDefault(g, 'shape'), shadeOn = pDefault(g, 'shade'), labels = ctx.labels;
  const castOn = pDefault(g, 'cast') && L[1] > 0.04;
  const toGround = (q) => { const t = q[1] / L[1]; return [q[0] - L[0] * t, 0, q[2] - L[2] * t]; };
  const N = 96;

  // солнце-ручка и луч к предмету
  pen.circle(lp, 3.2, 'aux');
  for (let i = 0; i < 8; i++) { const an = i * Math.PI / 4, d = { x: Math.cos(an), y: Math.sin(an) }; pen.seg(add(lp, mulS(d, 4.5)), add(lp, mulS(d, 7)), 'aux'); }
  pen.seg(add(lp, mulS(norm(sub(c, lp)), 9)), add(c, mulS(norm(sub(lp, c)), r * 1.4)), 'ghost');

  let silhouette = [], cast = null;
  const lbl = [];

  if (shape === 'sphere') {
    const C = [0, r, 0];
    const sil = [], silN = [];
    for (let i = 0; i < N; i++) { const t = i / N * TAU, n = v3.add(v3.sc(right, Math.cos(t)), v3.sc(up, Math.sin(t))); silN.push(n); sil.push(P(v3.add(C, v3.sc(n, r)))); }
    silhouette = sil;
    // граница света (терминатор)
    const e1 = v3.norm(v3.cross(L, Math.abs(L[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0])), e2 = v3.cross(L, e1);
    const term = [], termVis = [];
    for (let i = 0; i < N; i++) { const t = i / N * TAU, n = v3.add(v3.sc(e1, Math.cos(t)), v3.sc(e2, Math.sin(t))); term.push(P(v3.add(C, v3.sc(n, r)))); termVis.push(v3.dot(n, toV) >= 0); }
    const darkRuns = runs(N, i => v3.dot(silN[i], L) < 0);
    const visRuns = runs(N, i => termVis[i]);
    const tv = visRuns.sort((p, q) => q.length - p.length)[0] || [];
    if (shadeOn && darkRuns.length) {
      const ds = darkRuns.sort((p, q) => q.length - p.length)[0];
      if (ds.length === N && !tv.length) pen.fill(sil);
      else if (tv.length > 1) {
        const arc = ds.map(i => sil[i]);
        let tpts = tv.map(i => term[i]);
        if (dist(tpts[0], arc[arc.length - 1]) > dist(tpts[tpts.length - 1], arc[arc.length - 1])) tpts = tpts.reverse();
        const poly = arc.concat(tpts);
        pen.fill(poly);
        if (labels) { const m = poly.reduce((s2, p) => ({ x: s2.x + p.x / poly.length, y: s2.y + p.y / poly.length }), { x: 0, y: 0 }); lbl.push([m, 'своя тень']); }
      }
    }
    if (tv.length > 1) pen.poly(tv.map(i => term[i]), false, 'aux');
    pen.poly(sil, true, 'main');
    const Hh = v3.norm(v3.add(L, toV));
    if (v3.dot(Hh, toV) > 0) { const hp = P(v3.add(C, v3.sc(Hh, r))); pen.circle(hp, Math.max(1.2, r * 0.1), 'main'); pen.dot(hp); if (labels) lbl.push([add(hp, { x: 0, y: -r * 0.18 - 3 }), 'блик']); }
    if (castOn) {
      const pts = [];
      for (let i = 0; i < 24; i++) for (let j = 0; j <= 12; j++) { const th = i / 24 * TAU, ph = j / 12 * Math.PI; pts.push(toGround([r * Math.sin(ph) * Math.cos(th), r + r * Math.cos(ph), r * Math.sin(ph) * Math.sin(th)])); }
      cast = convexHull(pts.map(P));
    }
    // тень касания
    pen.ellipse(P([0, 0, 0]), r * 0.35, r * 0.35 * Math.sin(e) + 0.4, 0, 'aux');
  } else if (shape === 'cube') {
    const yaw = pDefault(g, 'yaw') * Math.PI / 180, cy = Math.cos(yaw), sy = Math.sin(yaw);
    const rot = (x, y, z) => [x * cy + z * sy, y, -x * sy + z * cy];
    const V = []; for (const y of [0, 2 * r]) for (const [x, z] of [[-r, -r], [r, -r], [r, r], [-r, r]]) V.push(rot(x, y, z));
    const faces = [
      { i: [4, 5, 6, 7], n: [0, 1, 0] }, { i: [0, 3, 2, 1], n: [0, -1, 0] },
      { i: [3, 7, 6, 2], n: rot(0, 0, 1) }, { i: [1, 5, 4, 0], n: rot(0, 0, -1) },
      { i: [2, 6, 5, 1], n: rot(1, 0, 0) }, { i: [0, 4, 7, 3], n: rot(-1, 0, 0) },
    ];
    const PV = V.map(P);
    silhouette = convexHull(PV);
    for (const f of faces) {
      if (v3.dot(f.n, toV) <= 1e-6) continue;
      const poly = f.i.map(k => PV[k]);
      if (shadeOn && v3.dot(f.n, L) < 0) { pen.fill(poly); if (labels) { const m = poly.reduce((s2, p) => ({ x: s2.x + p.x / 4, y: s2.y + p.y / 4 }), { x: 0, y: 0 }); lbl.push([m, 'тень']); } }
      pen.poly(poly, true, 'main');
    }
    if (castOn) cast = convexHull(V.map(toGround).map(P));
  } else {
    const isCone = shape === 'cone';
    const Hc = 2 * r * pDefault(g, 'height');
    const base = [], top = [], nrm = [];
    for (let i = 0; i < N; i++) {
      const t = i / N * TAU, x = Math.cos(t) * r, z = Math.sin(t) * r;
      base.push([x, 0, z]); top.push(isCone ? [0, Hc, 0] : [x, Hc, z]);
      nrm.push(isCone ? v3.norm([Math.cos(t) * Hc, r, Math.sin(t) * Hc]) : [Math.cos(t), 0, Math.sin(t)]);
    }
    const PB = base.map(P), PT = top.map(P);
    silhouette = convexHull(PB.concat(isCone ? [PT[0]] : PT));
    const vis = (i) => v3.dot(nrm[i], toV) > 0;
    // своя тень на боку
    if (shadeOn) {
      for (const run of runs(N, i => vis(i) && v3.dot(nrm[i], L) < 0)) {
        if (run.length < 2) continue;
        const poly = run.map(i => PB[i]).concat(isCone ? [PT[0]] : run.slice().reverse().map(i => PT[i]));
        pen.fill(poly);
        if (labels && run.length > 6) { const m = poly.reduce((s2, p) => ({ x: s2.x + p.x / poly.length, y: s2.y + p.y / poly.length }), { x: 0, y: 0 }); lbl.push([m, 'своя тень']); }
      }
    }
    // граница света на боку: переходы освещённость/тень на видимой стороне
    for (let i = 0; i < N; i++) {
      const j = (i + 1) % N;
      if (!vis(i)) continue;
      if ((v3.dot(nrm[i], L) < 0) !== (v3.dot(nrm[j], L) < 0)) pen.seg(PB[i], PT[i], 'aux');
    }
    // контур
    const frontRun = runs(N, i => base[i][2] >= 0 || e < 0.02)[0] || [];
    pen.poly(frontRun.map(i => PB[i]), false, 'main');
    if (!isCone) {
      pen.poly(PT, true, 'main');
      if (shadeOn && L[1] < 0) pen.fill(PT);
      const iR = 0, iL = N / 2;
      pen.seg(PB[iR], PT[iR]); pen.seg(PB[iL], PT[iL]);
    } else {
      // образующие силуэта: касательные из вершины к эллипсу основания
      const hull = silhouette; pen.poly(hull, true, 'main');
    }
    if (castOn) cast = convexHull(base.concat(isCone ? [top[0]] : top).map(toGround).map(P));
  }

  if (cast && cast.length > 2) {
    if (shadeOn) pen.fill(cast, [silhouette]);
    pen.poly(cast, true, 'aux');
    if (labels) {
      const m = cast.reduce((s2, p) => ({ x: s2.x + p.x / cast.length, y: s2.y + p.y / cast.length }), { x: 0, y: 0 });
      const away = norm(sub(m, c)); lbl.push([add(m, mulS(away, r * 0.4)), 'падающая тень']);
    }
  }
  for (const [p, t] of lbl) pen.label(p, t);
  void lerpP;
}

// ---------- Поворот и наклон плоских фигур ----------
// Фигура живёт на своей «плоскости»: её можно повернуть вокруг центра (spin) и наклонить
// в 3D (tiltX — вперёд/назад, tiltY — влево/вправо) с перспективой (depth). Всё это — одна
// гомография H, через которую проходят ВСЕ линии фигуры, включая внутренние (крест, оси,
// диагонали, лучи). Центр фигуры остаётся на месте.
export const ROT_PROPS = [
  { key: 'spin', label: 'Поворот вокруг центра, °', type: 'range', min: -180, max: 180, step: 1, def: 0, rot: true },
  { key: 'tiltX', label: 'Наклон вперёд/назад (перспектива), °', type: 'range', min: -80, max: 80, step: 1, def: 0, rot: true },
  { key: 'tiltY', label: 'Наклон влево/вправо (перспектива), °', type: 'range', min: -80, max: 80, step: 1, def: 0, rot: true },
  { key: 'depth', label: 'Сила перспективы', type: 'range', min: 0, max: 1, step: 0.05, def: 0.4, rot: true },
];
const ROT_FRAME = {
  circle: (g) => ({ C: g.pts[0], sz: dist(g.pts[0], g.pts[1]) }),
  polygon: (g) => ({ C: g.pts[0], sz: dist(g.pts[0], g.pts[1]) }),
  radial: (g) => ({ C: g.pts[0], sz: dist(g.pts[0], g.pts[1]) }),
  ellipse: (g) => { const e = TYPES.ellipse.geo(g); return { C: e.c, sz: e.A }; },
  rect: (g) => { const r = TYPES.rect.geo(g); return { C: r.center, sz: Math.max(r.L, Math.abs(r.h)) / 2 }; },
};
for (const t of Object.keys(ROT_FRAME)) TYPES[t].props.push(...ROT_PROPS.map(p => ({ ...p })));
export const canRotate = (g) => !!ROT_FRAME[g.type];

function planeParts(g) {
  const fr = ROT_FRAME[g.type]; if (!fr) return null;
  const { C, sz } = fr(g);
  const spin = (+pDefault(g, 'spin') || 0) * Math.PI / 180;
  const tx = (+pDefault(g, 'tiltX') || 0) * Math.PI / 180, ty = (+pDefault(g, 'tiltY') || 0) * Math.PI / 180;
  const depth = +pDefault(g, 'depth');
  const D = Math.max(1, sz) * (1.8 + 8 * (1 - (isFinite(depth) ? depth : 0.4)));
  // R3 = Rx(tiltX)·Ry(tiltY); точка плоскости (x, y, 0) → (X, Y, Z) → проекция X·D/(D+Z)
  const cx = Math.cos(tx), sx = Math.sin(tx), cy = Math.cos(ty), sy = Math.sin(ty);
  const a11 = cy, a12 = 0, a21 = sx * sy, a22 = cx, a31 = -cx * sy, a32 = sx;
  const P = [a11, a12, 0, a21, a22, 0, a31 / D, a32 / D, 1];
  const T1 = [1, 0, C.x, 0, 1, C.y, 0, 0, 1], T0 = [1, 0, -C.x, 0, 1, -C.y, 0, 0, 1];
  const Rs = [Math.cos(spin), -Math.sin(spin), 0, Math.sin(spin), Math.cos(spin), 0, 0, 0, 1];
  return { C, sz, spin, tilted: tx !== 0 || ty !== 0, Hn: mul(T1, mul(P, T0)), H: mul(T1, mul(P, mul(Rs, T0))) };
}
// Гомография фигуры или null, если фигура не повёрнута.
export function planeH(g) {
  const p = planeParts(g);
  if (!p || (p.spin === 0 && !p.tilted)) return null;
  return p.H;
}
const applyP = (M, p) => { const r = apply(M, p.x, p.y); return { x: r.x, y: r.y }; };
// Ручки на экране: собственные ручки фигуры, пропущенные через H, + ручка поворота (последняя).
export function viewHandles(g) {
  const T = TYPES[g.type], raw = T.handles(g);
  const pp = planeParts(g);
  if (!pp) return raw;
  const H = planeH(g);
  const hs = H ? raw.map(q => applyP(H, q)) : raw.map(q => ({ x: q.x, y: q.y }));
  hs.push(applyP(pp.H, { x: pp.C.x, y: pp.C.y - Math.max(8, pp.sz) * 1.3 - 16 }));
  return hs;
}
export const rotHandleIndex = (g) => (ROT_FRAME[g.type] ? TYPES[g.type].handles(g).length : -1);
// Точка листа → точка на плоскости фигуры (для перетаскивания ручек повёрнутой фигуры).
export function toFigure(g, p) { const H = planeH(g); return H ? applyP(inv(H), p) : p; }
// Угол поворота по положению ручки поворота (с учётом наклона).
export function spinFromPoint(g, p) {
  const pp = planeParts(g);
  const q = applyP(inv(pp.Hn), p);
  let a = Math.atan2(q.y - pp.C.y, q.x - pp.C.x) * 180 / Math.PI + 90;
  while (a > 180) a -= 360; while (a < -180) a += 360;
  return a;
}
