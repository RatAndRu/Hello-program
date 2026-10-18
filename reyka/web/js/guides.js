// Типы AR-направляющих. Все точки — в миллиметрах листа (0,0 — левый верхний угол).
// Каждый тип описывает: создание, параметры (для автопанели), отрисовку и ручки.

import {
  apply, add, sub, mulS, dot, len, dist, norm, perp, lerpP, reflect, clipSegment,
  circleFrom3, homography,
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
  }
  tf(p) { return this.mirror ? reflect(p, this.mirror.a, this.mirror.b) : p; }
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
};

export const TYPE_ORDER = ['line', 'parallel', 'circle', 'ellipse', 'rect', 'polygon', 'arc', 'grid', 'persp', 'pellipse', 'symmetry', 'radial'];

export function getProp(g, k) { return pDefault(g, k); }

export function defaultProps(type) {
  const o = {};
  for (const p of TYPES[type].props) o[p.key] = p.def;
  return o;
}
