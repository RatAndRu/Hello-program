// Причёски: «манекен» волос в 3D поверх черепа Лумиса. Без ИИ — простая геометрия.
// Модель: череп — шар радиуса 1 (центр в начале координат), y вверх, z к зрителю,
// линия бровей — y = 0, подбородок ≈ −1.3. Волосы — пряди (клинья): у каждой есть корень
// у пробора, путь по поверхности черепа (с объёмом) и свободный участок, который висит вниз
// (с волной/кудрями). Пряди за головой скрываются. Случайность — от зерна (seed),
// поэтому линии не «прыгают» при каждой перерисовке.

const TAU = Math.PI * 2, D2R = Math.PI / 180;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const nrm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const scl = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const add3 = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sph = (az, el, R = 1) => [R * Math.cos(el) * Math.sin(az), R * Math.sin(el), R * Math.cos(el) * Math.cos(az)];
function rng(seed) { let a = (seed * 2654435761) >>> 0 || 1; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function rotator(yaw, pitch, roll) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
  return (p) => {
    const x1 = p[0] * cy + p[2] * sy, z1 = -p[0] * sy + p[2] * cy, y1 = p[1];
    const y2 = y1 * cp + z1 * sp, z2 = -y1 * sp + z1 * cp;
    return [x1 * cr + y2 * sr, -x1 * sr + y2 * cr, z2];
  };
}
function spline3(pts, n = 6) {
  if (pts.length < 3) { const out = []; for (let i = 0; i < pts.length - 1; i++) for (let k = 0; k < n; k++) out.push(pts[i].map((v, d) => lerp(v, pts[i + 1][d], k / n))); out.push(pts[pts.length - 1]); return out; }
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
// по сфере от направления a к направлению b
function slerpDir(a, b, t) {
  const A = nrm(a), B = nrm(b), d = clamp(A[0] * B[0] + A[1] * B[1] + A[2] * B[2], -0.999, 1), om = Math.acos(d);
  if (om < 1e-4) return A;
  const s = Math.sin(om), k1 = Math.sin((1 - t) * om) / s, k2 = Math.sin(t * om) / s;
  return nrm([A[0] * k1 + B[0] * k2, A[1] * k1 + B[1] * k2, A[2] * k1 + B[2] * k2]);
}

// ---------- параметры ----------
// len: длина (0.6 — ёжик, 1 — короткая, 2 — до подбородка, 3 — плечи, 4.5 — грудь, 6 — пояс)
// vol: объём; part: пробор center/side/none (зачёс назад); bangs: none/straight/side/curtain/spiky/wispy
// bangLen: длина чёлки (0.6 — брови, 1 — глаза); wave: волна/кудри; spiky: шипы (сёнэн);
// tie: none/pony/twin/bun; tailLen: длина хвоста; locks: пряди у лица; ahoge: «антенна»;
// clumps: количество прядей; detail: штрихи внутри; messy: небрежность; ends: кончики straight/in/out
export const HAIR_DEFAULTS = { len: 2, vol: 0.18, part: 'center', bangs: 'side', bangLen: 0.6, wave: 0.1, spiky: 0, tie: 'none', tailLen: 3, locks: false, ahoge: false, clumps: 0.5, detail: 0.4, messy: 0.25, ends: 'straight' };
export const HAIR_PRESETS = {
  m_short: { name: '♂ Короткая', len: 0.95, vol: 0.12, part: 'side', bangs: 'side', bangLen: 0.35, wave: 0.05, spiky: 0.15, tie: 'none', locks: false, ahoge: false, messy: 0.25, ends: 'straight' },
  m_spiky: { name: '♂ Шипы (сёнэн)', len: 1.25, vol: 0.22, part: 'center', bangs: 'spiky', bangLen: 0.75, wave: 0, spiky: 0.9, tie: 'none', locks: false, ahoge: false, messy: 0.35, ends: 'straight' },
  m_back: { name: '♂ Зачёс назад', len: 1.05, vol: 0.16, part: 'none', bangs: 'none', bangLen: 0, wave: 0.12, spiky: 0, tie: 'none', locks: false, ahoge: false, messy: 0.1, ends: 'straight' },
  m_messy: { name: '♂ Растрёпанная', len: 1.35, vol: 0.28, part: 'center', bangs: 'wispy', bangLen: 0.75, wave: 0.3, spiky: 0.35, tie: 'none', locks: false, ahoge: true, messy: 0.8, ends: 'out' },
  m_medium: { name: '♂ До подбородка', len: 2.0, vol: 0.18, part: 'center', bangs: 'curtain', bangLen: 0.8, wave: 0.08, spiky: 0.1, tie: 'none', locks: false, ahoge: false, messy: 0.3, ends: 'straight' },
  m_samurai: { name: '♂ Хвост (самурай)', len: 1.5, vol: 0.08, part: 'none', bangs: 'none', bangLen: 0, wave: 0.05, spiky: 0, tie: 'pony', tailLen: 2.4, locks: true, ahoge: false, messy: 0.3, ends: 'straight' },
  f_bob: { name: '♀ Каре', len: 1.9, vol: 0.2, part: 'side', bangs: 'none', bangLen: 0.5, wave: 0.04, spiky: 0, tie: 'none', locks: false, ahoge: false, messy: 0.12, ends: 'in' },
  f_hime: { name: '♀ Химэ (прямая чёлка)', len: 5, vol: 0.12, part: 'none', bangs: 'straight', bangLen: 0.65, wave: 0, spiky: 0, tie: 'none', locks: true, ahoge: false, messy: 0.05, ends: 'straight' },
  f_long: { name: '♀ Длинные волнистые', len: 4.4, vol: 0.22, part: 'side', bangs: 'side', bangLen: 0.7, wave: 0.6, spiky: 0, tie: 'none', locks: false, ahoge: false, messy: 0.3, ends: 'out' },
  f_pony: { name: '♀ Хвост', len: 1.3, vol: 0.12, part: 'center', bangs: 'wispy', bangLen: 0.65, wave: 0.15, spiky: 0, tie: 'pony', tailLen: 3.4, locks: true, ahoge: false, messy: 0.25, ends: 'straight' },
  f_twin: { name: '♀ Два хвоста', len: 1.3, vol: 0.12, part: 'center', bangs: 'straight', bangLen: 0.6, wave: 0.2, spiky: 0, tie: 'twin', tailLen: 3.8, locks: false, ahoge: true, messy: 0.2, ends: 'out' },
  f_bun: { name: '♀ Пучок', len: 1.3, vol: 0.1, part: 'side', bangs: 'side', bangLen: 0.55, wave: 0.1, spiky: 0, tie: 'bun', locks: true, ahoge: false, messy: 0.35, ends: 'straight' },
  f_pixie: { name: '♀ Пикси', len: 0.95, vol: 0.16, part: 'side', bangs: 'side', bangLen: 0.6, wave: 0.15, spiky: 0.2, tie: 'none', locks: false, ahoge: false, messy: 0.45, ends: 'out' },
  f_curly: { name: '♀ Кудри', len: 3, vol: 0.45, part: 'center', bangs: 'wispy', bangLen: 0.5, wave: 0.92, spiky: 0, tie: 'none', locks: false, ahoge: false, messy: 0.45, ends: 'straight' },
};
export const HAIR_OPTIONS = Object.entries(HAIR_PRESETS).map(([k, v]) => [k, v.name]);

// ---------- построение прядей ----------
// Возвращает { clumps: [{pts, w, tip, t0}], rings: [[3D-точки]], hairline: [...], cap: R }
export function buildHair(o0, seed = 1) {
  const o = { ...HAIR_DEFAULTS, ...o0 };
  const rnd = rng(seed * 7 + 3), J = (a) => (rnd() * 2 - 1) * a;
  const vol = o.vol, mess = o.messy, R1 = 1 + vol;
  const yEnd = 0.9 - o.len * 1.1;
  const partX = o.part === 'side' ? -0.36 : 0;
  const clumps = [], rings = [];
  const tieOf = (sg) => o.tie === 'pony' ? sph(Math.PI, 28 * D2R, 1 + vol * 0.6) : o.tie === 'twin' ? sph(sg * 112 * D2R, 30 * D2R, 1 + vol * 0.6) : o.tie === 'bun' ? sph(Math.PI, 58 * D2R, 1 + vol * 0.6) : null;
  // волна вдоль свободного участка
  const waveAt = (d, tang, rad, ph, k) => {
    if (o.wave <= 0.01) return [0, 0, 0];
    const per = lerp(1.7, 0.42, o.wave), A = o.wave * (0.1 + 0.12 * o.wave) * Math.min(1, d / 0.6), a = TAU * d / per + ph;
    const s1 = Math.sin(a) * A, s2 = o.wave > 0.55 ? Math.cos(a) * A * 0.8 : 0; // сильная волна — уже спираль (кудри)
    void k;
    return add3(scl(tang, s1), scl(rad, s2));
  };

  // 1) основная масса: корень у пробора → по черепу → вниз
  const NM = Math.round(8 + 18 * o.clumps), half = Math.ceil(NM / 2);
  const phase0 = rnd() * TAU; // общая фаза волны — волосы волнятся «вместе», а не вразнобой
  const bMin = o.bangs === 'none' ? (o.part === 'none' ? 80 : 42) : 70;
  for (const sg of [-1, 1]) for (let i = 0; i < half; i++) {
    const s = (i + 0.5) / half;
    const beta = sg * (lerp(bMin, 178, s) + J(6 + 10 * mess)) * D2R;
    let root;
    if (o.part === 'none') root = sph(sg * lerp(8, 60, s) * D2R + J(0.05), (50 + J(3)) * D2R);
    else { const th = lerp(62, 150, s) * D2R; root = nrm([partX + sg * 0.06, Math.sin(th), Math.cos(th)]); }
    const T = tieOf(sg);
    const W = (TAU * R1 * 0.5 / half) * (1.25 + J(0.3 * mess));
    const pts = [];
    if (T) { // волосы собраны к резинке/пучку
      for (let k = 0; k <= 14; k++) { const t = k / 14; pts.push(scl(slerpDir(root, T, t), 1 + vol * (0.25 + 0.5 * Math.sin(Math.PI * t)) * (o.tie === 'twin' ? 0.8 : 0.6))); }
      clumps.push({ pts, w: W * 0.8, tip: 'soft', t0: 0.25, kind: 'mass' });
      continue;
    }
    const ab = Math.abs(beta) / D2R, elSep = (ab < 90 ? -8 : lerp(-8, -42, clamp((ab - 90) / 90, 0, 1))) * D2R;
    const sep = sph(beta, elSep, 1);
    const yE = yEnd + J(0.35 * mess) - (ab > 120 ? 0.1 : 0);
    const sp = o.spiky * (0.7 + J(0.3));
    // зачёс назад: путь идёт через макушку, а не вокруг головы
    const via = o.part === 'none' ? sph(beta * 0.35, 78 * D2R) : null;
    const dirAt = (t) => (via ? (t < 0.5 ? slerpDir(root, via, t * 2) : slerpDir(via, sep, t * 2 - 1)) : slerpDir(root, sep, t));
    if (sp > 0.45) { // шипы: прядь идёт от пробора по черепу и торчит наружу-вверх «венцом»
      const tM = (0.4 + 0.55 * rnd()) * (0.7 + 0.3 * Math.min(1, o.len / 1.3));
      for (let k = 0; k <= 8; k++) { const t = tM * k / 8; pts.push(scl(dirAt(t), 1 + vol * (0.4 + 0.6 * t / tM))); }
      const a = pts[pts.length - 2], b = pts[pts.length - 1], tg = nrm([b[0] - a[0], b[1] - a[1], b[2] - a[2]]), rd = nrm(b);
      const out = nrm([tg[0] * 0.55 + rd[0], tg[1] * 0.55 + rd[1] + 0.15, tg[2] * 0.55 + rd[2]]);
      const Ls = (0.3 + 0.45 * sp) * (0.75 + J(0.35)) * Math.min(1.3, 0.6 + o.len * 0.4);
      pts.push(add3(b, scl(out, Ls * 0.55)), add3(add3(b, scl(out, Ls)), scl(tg, 0.08)));
      clumps.push({ pts: spline3(pts, 2), w: W * (1.05 + 0.25 * sp), tip: 'sharp', t0: 0.3, kind: 'mass' });
      continue;
    }
    for (let k = 0; k <= 16; k++) {
      const t = k / 16, d = dirAt(t);
      const Rr = 1 + vol * (0.35 + 0.65 * Math.sin(Math.PI * t / 2)) + sp * 0.85 * Math.pow(t, 1.6);
      const p = scl(d, Rr);
      if (p[1] < yE && k > 1) { pts.push(p); break; }
      pts.push(p);
    }
    const last = pts[pts.length - 1];
    if (last[1] > yE) { // свободный участок — вниз до длины, с волной
      const tang = nrm([Math.cos(beta), 0, -Math.sin(beta)]), rad = nrm([Math.sin(beta), 0, Math.cos(beta)]);
      const ph = o.wave > 0.6 ? rnd() * TAU : phase0 + beta * 0.25 + J(0.5 + mess);
      const drop = last[1] - yE, M = Math.max(2, Math.round(drop / 0.22));
      for (let m = 1; m <= M; m++) {
        const d = drop * m / M, fl = 1 + 0.05 * d + J(0.02);
        let p = [last[0] * fl, last[1] - d, last[2] * fl];
        p = add3(p, waveAt(d, tang, rad, ph, m));
        if (m >= M - 1 && o.ends !== 'straight') { const f = (m - (M - 2)) / 2; p = add3(p, add3(scl(rad, (o.ends === 'in' ? -0.2 : 0.28) * f), [0, (o.ends === 'in' ? 0.06 : 0.12) * f, 0])); }
        pts.push(p);
      }
    }
    clumps.push({ pts: spline3(pts, 2), w: W, tip: o.ends === 'in' && o.len < 2.6 ? 'blunt' : 'soft', t0: o.part === 'none' ? 0.02 : o.len < 1.3 ? 0.2 : 0.3, kind: 'mass' });
  }

  // 2) чёлка
  const yb = 0.5 - o.bangLen * 0.9;
  if (o.bangs !== 'none') {
    const spiky = o.bangs === 'spiky', NB = spiky ? 3 + Math.round(3 * o.clumps) : o.bangs === 'wispy' ? 7 + Math.round(9 * o.clumps) : 5 + Math.round(8 * o.clumps);
    for (let j = 0; j < NB; j++) {
      const f = (j + 0.5) / NB;
      let xe = lerp(-0.78, 0.78, f), y = yb, tip = 'soft', wk = 1;
      let rootX = partX + (f - 0.5) * 0.35;
      if (o.bangs === 'straight') { y = yb + J(0.03); tip = 'blunt'; }
      else if (o.bangs === 'side') { rootX = partX + J(0.05); xe = lerp(partX - 0.15, 0.86, f); y = yb + 0.28 * (1 - f) + J(0.06 * (1 + mess)); }
      else if (o.bangs === 'curtain') { const g = Math.abs(f - 0.5) * 2; xe = Math.sign(f - 0.5) * lerp(0.12, 0.88, g); y = yb + 0.25 - 0.45 * g + J(0.05); rootX = Math.sign(f - 0.5) * 0.04; }
      else if (spiky) { y = yb + rnd() * 0.32 - (j === Math.floor(NB / 2) ? 0.12 : 0); xe *= 1.08; tip = 'sharp'; wk = 1.25; }
      else { y = yb + J(0.22); tip = 'sharp'; wk = 0.65; }
      const root = scl(nrm([rootX, Math.sin(72 * D2R), Math.cos(72 * D2R)]), 1 + vol * 0.6);
      const hl = scl(nrm([xe * 0.85, Math.sin(46 * D2R), Math.cos(46 * D2R)]), 1 + vol * 0.6);
      const zf = (x, yy) => Math.sqrt(Math.max(0.06, 1 - x * x * 1.05 - Math.max(0, yy) * Math.max(0, yy))) + 0.05 + vol * 0.3;
      const ym = (hl[1] + y) / 2, mid = [xe * 0.97, ym, zf(xe * 0.97, ym)];
      const end = [xe, y, zf(xe, y)];
      clumps.push({ pts: spline3([root, hl, mid, end], 5), w: (1.75 / NB) * 1.15 * wk * (1 + J(0.25 * mess)), tip, t0: 0.12, kind: 'bang' });
    }
  }

  // 3) пряди у лица
  if (o.locks) for (const sg of [-1, 1]) for (let q = 0; q < 2; q++) {
    const yL = o.bangs === 'straight' && o.part === 'none' ? -1.3 : Math.min(yEnd, -1.7) + J(0.15);
    const a0 = sg * (60 + q * 9) * D2R;
    const pts = [sph(a0, 42 * D2R, 1 + vol * 0.6), sph(sg * (74 + q * 6) * D2R, 2 * D2R, 1 + vol * 0.9), [sg * (0.98 + q * 0.05), -0.6, 0.38 - q * 0.08], [sg * (0.95 + q * 0.06) + J(0.05), yL, 0.32 - q * 0.08]];
    clumps.push({ pts: spline3(pts, 6), w: 0.2, tip: o.bangs === 'straight' && o.part === 'none' ? 'blunt' : 'soft', t0: 0.15, kind: 'lock' });
  }

  // 4) хвосты / пучок
  if (o.tie === 'pony' || o.tie === 'twin') {
    const sides = o.tie === 'twin' ? [-1, 1] : [0];
    for (const sg of sides) {
      const T = tieOf(sg || 1), K = Math.round(3 + 4 * o.clumps), phT = rnd() * TAU;
      rings.push(ringAt(T, sg ? [sg, 0.2, -0.3] : [0, 0.2, -1], 0.16));
      for (let k = 0; k < K; k++) {
        const sp = K > 1 ? k / (K - 1) - 0.5 : 0, ph = o.wave > 0.6 ? rnd() * TAU : phT + J(0.4), L = o.tailLen * (1 + J(0.15 * mess));
        let base;
        if (sg) base = [T, add3(T, [sg * 0.35, 0.1, -0.05]), [sg * (1.3 + sp * 0.35), T[1] - L * 0.4, -0.25 + sp * 0.2], [sg * (1.15 + sp * 0.4), T[1] - L, -0.12 + sp * 0.25]];
        else base = [T, add3(T, [sp * 0.3, 0.12, -0.42]), [sp * 0.55, T[1] - L * 0.45, -1.05], [sp * 0.45, T[1] - L, -0.9]];
        let pts = spline3(base, 6);
        const tang = sg ? [0, 0, 1] : [1, 0, 0], rad = sg ? [sg, 0, 0] : [0, 0, -1];
        pts = pts.map((p, idx) => add3(p, waveAt(idx / pts.length * L, tang, rad, ph, idx)));
        clumps.push({ pts, w: 0.5 * 5 / (K + 1), tip: 'soft', t0: 0.04, kind: 'tail' });
      }
    }
  }
  let bun = null;
  if (o.tie === 'bun') {
    const T = tieOf(1), c = scl(nrm(T), Math.hypot(...T) + 0.32);
    bun = { c, r: 0.4 };
    // спиральные пряди на пучке
    // две спиральные пряди-«завитка» на пучке
    const ax = nrm(T), t1 = nrm([ax[2], 0, -ax[0]]), t2 = [ax[1] * t1[2] - ax[2] * t1[1], ax[2] * t1[0] - ax[0] * t1[2], ax[0] * t1[1] - ax[1] * t1[0]];
    for (let k = 0; k < 2; k++) { const ring = []; for (let m = 0; m <= 30; m++) { const a = TAU * 0.75 * m / 30 + k * Math.PI, rr = 0.4 * (0.35 + 0.6 * m / 30), h = Math.sqrt(Math.max(0, 0.16 - rr * rr)); ring.push(add3(add3(c, scl(ax, h)), add3(scl(t1, Math.cos(a) * rr), scl(t2, Math.sin(a) * rr)))); } rings.push(ring); }
    rings.push(ringAt(T, nrm(T), 0.17));
  }

  // 5) «антенна»
  if (o.ahoge) {
    const t = 1 + vol;
    clumps.push({ pts: spline3([sph(0.05, 84 * D2R, t), [0.04, t + 0.45, 0.16], [0.24, t + 0.75, 0.02], [0.38, t + 0.6, -0.1]], 6), w: 0.09, tip: 'sharp', t0: 0, kind: 'ahoge' });
  }

  // линия роста волос (если лоб открыт)
  const hairline = [];
  for (let k = 0; k <= 30; k++) { const a = lerp(-72, 72, k / 30), el = lerp(50, 18, Math.pow(Math.abs(a) / 72, 2)); hairline.push(sph(a * D2R, el * D2R, 1.004)); }
  return { clumps, rings, hairline, cap: R1 + 0.0, bun, o };
}
function ringAt(T, axis, r) {
  const A = nrm(axis), t1 = nrm(Math.abs(A[1]) < 0.9 ? [A[2], 0, -A[0]] : [1, 0, 0]), t2 = [A[1] * t1[2] - A[2] * t1[1], A[2] * t1[0] - A[0] * t1[2], A[0] * t1[1] - A[1] * t1[0]];
  const out = []; for (let k = 0; k <= 24; k++) { const a = TAU * k / 24; out.push(add3(T, add3(scl(t1, Math.cos(a) * r), scl(t2, Math.sin(a) * r)))); }
  return out;
}

// ---------- отрисовка ----------
// opt: { layer, chin } — chin: длина лица (для скрытия волос за лицом/шеей)
export function drawHair(pen, o, C, r, yaw, pitch, roll, seed = 1, opt = {}) {
  const H = buildHair(o, seed), R = rotator(yaw, pitch, roll), main = opt.layer || 'main', chin = opt.chin || 1.35;
  const pr = (p) => { const q = R(p); return { x: C.x + q[0] * r, y: C.y - q[1] * r, z: q[2] }; };
  // невидимо: за черепом или за лицом/шеей
  const neckA = R([0, -0.35, 0.1]), neckB = R([0, -chin - 1.2, -0.1]);
  const vis = (p) => {
    const q = R(p);
    if (q[2] >= -0.02) return true;
    // за черепом — и за собственным объёмом волос (задние пряди не просвечивают сквозь передние)
    const capR = 1 + H.o.vol * 0.9;
    if (q[0] * q[0] + q[1] * q[1] < (Math.hypot(p[0], p[1], p[2]) < capR + 0.15 ? capR * capR : 0.985)) return false;
    const ax = neckB[0] - neckA[0], ay = neckB[1] - neckA[1], L2 = ax * ax + ay * ay || 1;
    const t = clamp(((q[0] - neckA[0]) * ax + (q[1] - neckA[1]) * ay) / L2, 0, 1);
    const cx = neckA[0] + ax * t, cy = neckA[1] + ay * t, cz = lerp(neckA[2], neckB[2], t);
    const rad = t < 0.45 ? 0.78 : 0.5;
    if (Math.hypot(q[0] - cx, q[1] - cy) < rad && q[2] < cz) return false;
    // плечи и спина: длинные волосы за спиной закрыты телом
    const sh = R([0, -chin - 0.95, -0.1]);
    if (q[1] < sh[1] + 0.1 && Math.abs(q[0] - sh[0]) < 1.75 && q[2] < sh[2] + 0.05) return false;
    return true;
  };
  const runs = (pts, vs, layer, closed = false) => {
    let run = [];
    for (let i = 0; i < pts.length; i++) { if (vs[i]) run.push(pts[i]); else { if (run.length > 1) pen.poly(run, false, layer); run = []; } }
    if (run.length > 1) { if (closed && vs.every(Boolean)) pen.poly(run, true, layer); else pen.poly(run, false, layer); }
  };
  const det = H.o.detail;
  for (const cl of H.clumps) {
    const P3 = cl.pts, n = P3.length; if (n < 2) continue;
    const P2 = P3.map(pr), V = P3.map(vis);
    const i0 = Math.min(n - 2, Math.floor(cl.t0 * (n - 1)));
    const width = (t) => cl.tip === 'sharp' ? (1 - t) * 1.05 : cl.tip === 'blunt' ? 1 - 0.3 * t : Math.pow(Math.max(0, 1 - Math.pow(t, 2.4)), 0.75);
    const Lp = [], Rp = [], Vv = [];
    for (let i = i0; i < n; i++) {
      const a = P2[Math.max(0, i - 1)], b = P2[Math.min(n - 1, i + 1)];
      let dx = b.x - a.x, dy = b.y - a.y; const l = Math.hypot(dx, dy) || 1; dx /= l; dy /= l;
      const t = i / (n - 1), w = cl.w * r * 0.5 * width(t);
      Lp.push({ x: P2[i].x - dy * w, y: P2[i].y + dx * w }); Rp.push({ x: P2[i].x + dy * w, y: P2[i].y - dx * w }); Vv.push(V[i]);
    }
    const layer = cl.kind === 'ahoge' || cl.kind === 'bang' || cl.kind === 'lock' || cl.kind === 'tail' ? main : main;
    runs(Lp, Vv, layer); runs(Rp, Vv, layer);
    if (Vv[Vv.length - 1]) pen.seg(Lp[Lp.length - 1], Rp[Rp.length - 1], layer);
    // штрихи внутри пряди (детализация)
    const ns = det > 0.7 ? 2 : det > 0.3 ? 1 : 0;
    for (let s = 0; s < ns; s++) {
      const off = ns === 1 ? 0 : (s ? 0.28 : -0.28), a0 = Math.floor(Lp.length * (0.15 + 0.1 * s)), a1 = Math.floor(Lp.length * (0.78 - 0.08 * s));
      const pts = [], vs = [];
      for (let i = a0; i <= a1; i++) { pts.push({ x: lerp(Lp[i].x, Rp[i].x, 0.5 + off * 0.8), y: lerp(Lp[i].y, Rp[i].y, 0.5 + off * 0.8) }); vs.push(Vv[i]); }
      runs(pts, vs, 'aux');
    }
  }
  for (const ring of H.rings) runs(ring.map(pr), ring.map(vis), main);
  if (H.bun) {
    const c2 = pr(H.bun.c), pts = [], vs = [];
    const inv = rotator(0, 0, 0); void inv;
    for (let k = 0; k <= 48; k++) { const a = TAU * k / 48; pts.push({ x: c2.x + Math.cos(a) * H.bun.r * r, y: c2.y + Math.sin(a) * H.bun.r * r }); }
    // контур пучка виден, если центр перед головой или вне её силуэта
    const cq = R(H.bun.c), outside = Math.hypot(cq[0], cq[1]) > 1.0;
    for (let k = 0; k <= 48; k++) { const p = pts[k]; const dx = (p.x - C.x) / r, dy = -(p.y - C.y) / r; vs.push(cq[2] > -0.1 || outside || dx * dx + dy * dy > 1.0); }
    runs(pts, vs, main);
  }
  // «шапка» объёма: силуэт волос по черепу (в плоскости экрана — окружность радиуса cap)
  {
    const pts = [], vs = [], inv = (q) => { // точка силуэта в экранных осях → координаты модели
      // обратный поворот: перебором не нужно — используем ортонормальность
      const ex = R([1, 0, 0]), ey = R([0, 1, 0]), ez = R([0, 0, 1]);
      return [q[0] * ex[0] + q[1] * ex[1] + q[2] * ex[2], q[0] * ey[0] + q[1] * ey[1] + q[2] * ey[2], q[0] * ez[0] + q[1] * ez[1] + q[2] * ez[2]];
    };
    const capR = H.o.tie !== 'none' ? 1 + H.o.vol * 0.6 : H.cap, shortCut = 0.9 - H.o.len * 1.1;
    for (let k = 0; k <= 96; k++) {
      const a = TAU * k / 96, m = inv([Math.cos(a), Math.sin(a), 0]);
      pts.push({ x: C.x + Math.cos(a) * capR * r, y: C.y - Math.sin(a) * capR * r });
      const back = m[2] < -0.35;
      vs.push(m[1] > Math.max(-0.12, shortCut) || (back && m[1] > Math.max(-0.75, shortCut)) || (H.o.spiky < 0.45 && H.o.len > 1.3 && m[1] > -0.12 - 0.25 * Math.max(0, -m[2])));
    }
    runs(pts, vs, main);
  }
  // линия роста волос — пунктиром, когда лоб открыт
  if (H.o.bangs === 'none' || opt.hairline) runs(H.hairline.map(pr), H.hairline.map(p => R(p)[2] > 0.02), 'aux');
}
