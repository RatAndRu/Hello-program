// Объём — режимы формы поверх оболочки (без нейросетей, чистая геометрия):
//  «Коробка»       — прямоугольный брусок, стоящий на столе: поворот и размеры по сечению, верх — по излому профиля;
//  «Призма»        — одно и то же сечение по всей высоте (флакон-брусок, мыло, деталь, фигурка-силуэт);
//  «Плоские грани» — находит плоскости в обычной модели (RANSAC) и делает их идеально ровными, рёбра — острыми.

// ---------- общий анализ оболочки ----------
function layerAreas(G) {
  const { occ, nx, ny, nz } = G, S = nx * ny, a = new Float64Array(nz);
  for (let z = 0; z < nz; z++) { let c = 0; for (let i = z * S, e = i + S; i < e; i++) if (occ[i] > 0.5) c++; a[z] = c; }
  return a;
}
// Высота: сечение почти постоянно, а над настоящим верхом оболочка сужается «крышей» (верх видно только сверху).
// Берём медиану площади нижней половины, ищем излом и продолжаем спад крыши назад до уровня медианы.
export function findTop(G, refArea) {
  const a = layerAreas(G), vs = G.vs, z0 = Math.min(a.length - 1, Math.ceil(3 / vs));
  let zt = a.length - 1; while (zt > z0 && a[zt] === 0) zt--;
  const lower = Array.from(a.slice(z0, Math.max(z0 + 1, Math.round(z0 + 0.5 * (zt - z0))))).sort((p, q) => p - q);
  const med = refArea ? refArea / (vs * vs) : (lower[lower.length >> 1] || 1);
  const sm = (z) => (a[Math.max(0, z - 1)] + a[z] + a[Math.min(a.length - 1, z + 1)]) / 3;
  let zk = z0; while (zk < zt && sm(zk) >= 0.9 * med) zk++;
  // продолжение спада: √(площадь) у «крыши» убывает почти линейно
  const pts = []; for (let z = zk; z <= zt; z++) { const r = Math.sqrt(a[z] / med); if (r < 0.95 && r > 0.3) pts.push([z, r]); }
  let top = zk * vs;
  if (pts.length >= 3) {
    let sx = 0, sy = 0, sxx = 0, sxy = 0; for (const [x, y] of pts) { sx += x; sy += y; sxx += x * x; sxy += x * y; }
    const n = pts.length, k = (n * sxy - sx * sy) / (n * sxx - sx * sx), b = (sy - k * sx) / n;
    if (k < 0) { const zf = (1 - b) / k; top = Math.max((zk - 6 / vs) * vs, Math.min(zk * vs, zf * vs)); }
  }
  return { top: Math.max(top, 2 * vs) + G.origin[2], med, zk };
}
// след предмета на столе: колонки, занятые в ≥ половине слоёв от 3 мм до верха (без «крыши»)
function footprint(G, topZ) {
  const { occ, nx, ny, vs, origin } = G, S = nx * ny;
  const z0 = Math.ceil(3 / vs), z1 = Math.max(z0 + 1, Math.floor((topZ - origin[2]) / vs) - 1);
  const cnt = new Float32Array(S);
  for (let z = z0; z < z1; z++) for (let i = 0; i < S; i++) if (occ[z * S + i] > 0.5) cnt[i]++;
  for (let i = 0; i < S; i++) cnt[i] /= (z1 - z0);
  // самый большой связный кусок
  const lab = new Int32Array(S); let best = 0, bestN = 0, L = 0;
  for (let i = 0; i < S; i++) {
    if (cnt[i] < 0.5 || lab[i]) continue; L++; let n = 0; const st = [i]; lab[i] = L;
    while (st.length) { const j = st.pop(); n++; const x = j % nx, y = (j / nx) | 0; for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const xx = x + dx, yy = y + dy; if (xx < 0 || yy < 0 || xx >= nx || yy >= ny) continue; const q = yy * nx + xx; if (cnt[q] >= 0.5 && !lab[q]) { lab[q] = L; st.push(q); } } }
    if (n > bestN) { bestN = n; best = L; }
  }
  for (let i = 0; i < S; i++) if (lab[i] !== best) cnt[i] = Math.min(cnt[i], 0.49);
  return cnt;
}

// ---------- сборщик сетки ----------
function builder() {
  const pos = [], nrm = [], idx = [];
  return {
    v(x, y, z, n) { pos.push(x, y, z); nrm.push(n[0], n[1], n[2]); return pos.length / 3 - 1; },
    t(a, b, c) { idx.push(a, b, c); },
    // сетка на прямоугольнике o + s·u + t·v (s,t ∈ [0,1]), нормаль n; шаг ~step мм
    quad(o, u, v, n, step = 2) {
      const lu = Math.hypot(...u), lv = Math.hypot(...v), nu = Math.max(1, Math.ceil(lu / step)), nv = Math.max(1, Math.ceil(lv / step)), b0 = pos.length / 3;
      for (let j = 0; j <= nv; j++) for (let i = 0; i <= nu; i++) { const s = i / nu, t = j / nv; this.v(o[0] + s * u[0] + t * v[0], o[1] + s * u[1] + t * v[1], o[2] + s * u[2] + t * v[2], n); }
      for (let j = 0; j < nv; j++) for (let i = 0; i < nu; i++) { const a = b0 + j * (nu + 1) + i, b = a + 1, c = a + nu + 2, d = a + nu + 1; idx.push(a, b, c, a, c, d); }
    },
    done() { return { pos: new Float32Array(pos), nrm: new Float32Array(nrm), idx: new Uint32Array(idx) }; },
  };
}

// ---------- «Коробка» ----------
export function boxMesh(G) {
  const top0 = findTop(G).top, fp = footprint(G, top0), { nx, ny, vs, origin } = G;
  const P = []; for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) if (fp[y * nx + x] >= 0.5) P.push(origin[0] + x * vs, origin[1] + y * vs);
  if (P.length < 12) throw new Error('Коробка: предмет слишком мал');
  // Сечение оболочки чуть больше коробки: при конечном числе ракурсов на каждой грани остаётся «горб».
  // Поэтому грань ставим там, где профиль следа падает до 75% от полного (а не по крайним точкам),
  // а поворот выбираем по наибольшему совпадению прямоугольника со следом.
  const fit = (th) => {
    const c = Math.cos(th), s = Math.sin(th), us = [], vv = [];
    for (let i = 0; i < P.length; i += 2) { us.push(c * P[i] + s * P[i + 1]); vv.push(-s * P[i] + c * P[i + 1]); }
    const edges = (arr) => {
      let lo = Infinity, hi = -Infinity; for (const x of arr) { if (x < lo) lo = x; if (x > hi) hi = x; }
      const nb = Math.round((hi - lo) / vs) + 1, h = new Float64Array(nb); for (const x of arr) h[Math.min(nb - 1, Math.round((x - lo) / vs))]++;
      const srt = Array.from(h).sort((a, b) => a - b), full = srt[Math.floor(srt.length * 0.75)] || 1;
      let a = 0; while (a < nb - 1 && h[a] < 0.75 * full) a++;
      let b = nb - 1; while (b > a && h[b] < 0.75 * full) b--;
      return [lo + (a - 0.5) * vs, lo + (b + 0.5) * vs];
    };
    const [u0, u1] = edges(us), [v0, v1] = edges(vv);
    let inside = 0; for (let i = 0; i < us.length; i++) if (us[i] >= u0 && us[i] <= u1 && vv[i] >= v0 && vv[i] <= v1) inside++;
    const ar = (u1 - u0) * (v1 - v0), fa = us.length * vs * vs, ia = inside * vs * vs;
    return { u0, u1, v0, v1, area: ar, iou: ia / (fa + ar - ia) };
  };
  let bt = 0, bi = -1;
  for (let d = 0; d < 90; d += 1) { const e = fit(d * Math.PI / 180); if (e.iou > bi) { bi = e.iou; bt = d; } }
  for (let d = bt - 1; d <= bt + 1; d += 0.1) { const e = fit(d * Math.PI / 180); if (e.iou > bi) { bi = e.iou; bt = d; } }
  const th = bt * Math.PI / 180, e = fit(th), c = Math.cos(th), s = Math.sin(th);
  const top = findTop(G, e.area).top;
  const U = [c, s, 0], V = [-s, c, 0], H = top;
  const corner = (u, v, z) => [u * U[0] + v * V[0], u * U[1] + v * V[1], z];
  const a = e.u1 - e.u0, b = e.v1 - e.v0, B = builder();
  const o = corner(e.u0, e.v0, 0), su = U.map((x) => x * a), sv = V.map((x) => x * b), sz = [0, 0, H];
  B.quad(corner(e.u0, e.v0, H), su, sv, [0, 0, 1]);                                     // верх
  B.quad(o, sv, su, [0, 0, -1]);                                                         // низ
  B.quad(o, su, sz, V.map((x) => -x));                                                   // бока
  B.quad(corner(e.u1, e.v0, 0), sv, sz, U);
  B.quad(corner(e.u1, e.v1, 0), su.map((x) => -x), sz, V);
  B.quad(corner(e.u0, e.v1, 0), sv.map((x) => -x), sz, U.map((x) => -x));
  return { mesh: B.done(), info: `${a.toFixed(1)} × ${b.toFixed(1)} × ${H.toFixed(1)} мм, поворот ${bt.toFixed(1)}°` };
}

// ---------- «Призма» ----------
// Сечение — изолиния 0.5 следа (marching squares с заполнением клеток): крышки и стенки сходятся точно.
export function prismMesh(G) {
  const top0 = findTop(G).top, fp0 = footprint(G, top0), { nx, ny, vs, origin } = G;
  // лёгкое сглаживание следа 3×3 — ровнее контур
  const fp = new Float32Array(nx * ny);
  fp.set(fp0);
  const iso = 0.5, X = (x) => origin[0] + x * vs, Y = (y) => origin[1] + y * vs;
  const P2 = new Map(); // ключ вершины → [x, y]
  const ck = (x, y) => 'c' + (y * nx + x), ek = (x, y, dir) => 'e' + dir + (y * nx + x); // ребро от узла (x,y) вправо (h) или вверх (v)
  const cross = (x, y, dir) => { const k = ek(x, y, dir); if (!P2.has(k)) { const f0 = fp[y * nx + x], f1 = dir === 'h' ? fp[y * nx + x + 1] : fp[(y + 1) * nx + x], t = (iso - f0) / (f1 - f0); P2.set(k, dir === 'h' ? [X(x + t), Y(y)] : [X(x), Y(y + t)]); } return k; };
  const corner = (x, y) => { const k = ck(x, y); if (!P2.has(k)) P2.set(k, [X(x), Y(y)]); return k; };
  const polys = [], segs = new Map();
  for (let y = 0; y < ny - 1; y++) for (let x = 0; x < nx - 1; x++) {
    const cs = [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1]], ins = cs.map(([a, b]) => fp[b * nx + a] >= iso);
    if (!ins.some(Boolean)) continue;
    const poly = [], kinds = [];
    for (let k = 0; k < 4; k++) {
      const [ax, ay] = cs[k]; if (ins[k]) { poly.push(corner(ax, ay)); kinds.push(0); }
      const n = (k + 1) % 4; if (ins[k] !== ins[n]) {
        const e = k === 0 ? cross(x, y, 'h') : k === 1 ? cross(x + 1, y, 'v') : k === 2 ? cross(x, y + 1, 'h') : cross(x, y, 'v');
        poly.push(e); kinds.push(1);
      }
    }
    polys.push(poly);
    // граница: соседние в обходе (против часовой) точки пересечения — внутри слева
    for (let i = 0; i < poly.length; i++) { const j = (i + 1) % poly.length; if (kinds[i] && kinds[j]) segs.set(poly[i], poly[j]); }
  }
  if (!polys.length) throw new Error('Призма: сечение не найдено');
  // петли контура
  const loops = [], used = new Set();
  for (const st of segs.keys()) {
    if (used.has(st)) continue; const L = []; let k = st;
    while (k && !used.has(k)) { used.add(k); L.push(k); k = segs.get(k); }
    if (L.length >= 3) loops.push(L);
  }
  // сглаживание контура (те же точки используют и крышки)
  for (const L of loops) for (let it = 0; it < 1; it++) { const Q = L.map((k) => P2.get(k).slice()); for (let i = 0; i < L.length; i++) { const a = Q[(i - 1 + L.length) % L.length], b = Q[i], c = Q[(i + 1) % L.length]; P2.set(L[i], [0.25 * a[0] + 0.5 * b[0] + 0.25 * c[0], 0.25 * a[1] + 0.5 * b[1] + 0.25 * c[1]]); } }
  // прямые участки контура → идеально прямые, углы между ними — острые
  let nLines = 0;
  for (const L of loops) { const pts = L.map((k) => P2.get(k)); nLines += snapLoop(pts, vs); L.forEach((k, i) => P2.set(k, pts[i])); }
  let area = 0; for (const poly of polys) for (let i = 1; i + 1 < poly.length; i++) { const a = P2.get(poly[0]), b = P2.get(poly[i]), c = P2.get(poly[i + 1]); area += ((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2; }
  const H = findTop(G, area).top;
  const B = builder();
  // крышки
  for (const [z, n, flip] of [[H, [0, 0, 1], false], [0, [0, 0, -1], true]]) {
    const vid = new Map(); const V = (k) => { let i = vid.get(k); if (i === undefined) { const p = P2.get(k); i = B.v(p[0], p[1], z, n); vid.set(k, i); } return i; };
    for (const poly of polys) for (let i = 1; i + 1 < poly.length; i++) { const a = V(poly[0]), b = V(poly[i]), c = V(poly[i + 1]); flip ? B.t(a, c, b) : B.t(a, b, c); }
  }
  // стенки: нормаль наружу — справа от направления обхода; на изломах > 35° нормали не усредняются
  const rows = Math.max(1, Math.ceil(H / 2)), cosC = Math.cos(35 * Math.PI / 180);
  for (const L of loops) {
    const n = L.length, pts = L.map((k) => P2.get(k));
    const en = pts.map((p, i) => { const q = pts[(i + 1) % n], dx = q[0] - p[0], dy = q[1] - p[1], l = Math.hypot(dx, dy) || 1; return [dy / l, -dx / l]; });
    const vn = pts.map((_, i) => { const a = en[(i - 1 + n) % n], b = en[i]; if (a[0] * b[0] + a[1] * b[1] < cosC) return null; const x = a[0] + b[0], y = a[1] + b[1], l = Math.hypot(x, y) || 1; return [x / l, y / l]; });
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n, p = pts[i], q = pts[j], na = vn[i] || en[i], nb = vn[j] || en[i], b0 = [];
      for (let r = 0; r <= rows; r++) { const z = H * r / rows; b0.push(B.v(p[0], p[1], z, [na[0], na[1], 0]), B.v(q[0], q[1], z, [nb[0], nb[1], 0])); }
      for (let r = 0; r < rows; r++) { const a = b0[r * 2], b = b0[r * 2 + 1], c = b0[r * 2 + 3], d = b0[r * 2 + 2]; B.t(a, b, c); B.t(a, c, d); }
    }
  }
  return { mesh: B.done(), info: `высота ${H.toFixed(1)} мм, сечение ${(area / 100).toFixed(1)} см²${nLines ? `, прямых сторон: ${nLines}` : ''}` };
}

// Прямые участки замкнутого контура (по порядку точек): растим отрезки, подгоняем прямую МНК,
// точки проецируем; скруглённый «угол» между двумя прямыми сводим в точку их пересечения.
function snapLoop(pts, vs, tol = 0.8, minLen = 7) {
  const n = pts.length; if (n < 12) return 0;
  const lab = new Int32Array(n).fill(-1), lines = [];
  const fitLine = (idx) => { let cx = 0, cy = 0; for (const i of idx) { cx += pts[i][0]; cy += pts[i][1]; } cx /= idx.length; cy /= idx.length; let sxx = 0, sxy = 0, syy = 0; for (const i of idx) { const dx = pts[i][0] - cx, dy = pts[i][1] - cy; sxx += dx * dx; sxy += dx * dy; syy += dy * dy; } const a = 0.5 * Math.atan2(2 * sxy, sxx - syy); return { c: [cx, cy], d: [Math.cos(a), Math.sin(a)] }; };
  const dist = (l, p) => Math.abs((p[0] - l.c[0]) * l.d[1] - (p[1] - l.c[1]) * l.d[0]);
  const grow = (l, i0) => { const run = [i0]; for (let k = 1; k < n; k++) { const i = (i0 + k) % n; if (lab[i] >= 0 || dist(l, pts[i]) > tol) break; run.push(i); } for (let k = 1; k < n - run.length; k++) { const i = (i0 - k + n) % n; if (lab[i] >= 0 || dist(l, pts[i]) > tol) break; run.unshift(i); } return run; };
  const len = (run) => Math.hypot(pts[run[run.length - 1]][0] - pts[run[0]][0], pts[run[run.length - 1]][1] - pts[run[0]][1]);
  const step = Math.max(3, Math.round(3 / vs));
  for (let it = 0; it < 24; it++) {
    let best = null;
    for (let i = 0; i < n; i += 2) {
      if (lab[i] >= 0) continue; const j = (i + step) % n; if (lab[j] >= 0) continue;
      const l = fitLine([(i - step + n) % n, i, j]); if (lab[(i - step + n) % n] >= 0) continue;
      const run = grow(l, i), L = len(run); if (!best || L > best.L) best = { run, L };
    }
    if (!best || best.L < minLen) break;
    let l = fitLine(best.run), run = grow(l, best.run[best.run.length >> 1]); l = fitLine(run); run = grow(l, run[run.length >> 1]);
    if (len(run) < minLen) { for (const i of best.run) lab[i] = -2; continue; }
    const id = lines.length; lines.push(l); for (const i of run) lab[i] = id;
  }
  for (let i = 0; i < n; i++) if (lab[i] === -2) lab[i] = -1;
  if (!lines.length) return 0;
  for (let i = 0; i < n; i++) if (lab[i] >= 0) { const l = lines[lab[i]], p = pts[i], t = (p[0] - l.c[0]) * l.d[0] + (p[1] - l.c[1]) * l.d[1]; pts[i] = [l.c[0] + t * l.d[0], l.c[1] + t * l.d[1]]; }
  // промежутки между прямыми A и B → точка пересечения (если угол заметный и точка рядом)
  let s0 = 0; while (s0 < n && lab[s0] < 0) s0++; if (s0 === n) return lines.length;
  for (let k = 0; k < n; k++) {
    const i = (s0 + k) % n, j = (i + 1) % n; if (lab[i] < 0 || lab[j] >= 0) continue;
    let e = j, gap = []; while (lab[e] < 0) { gap.push(e); e = (e + 1) % n; if (gap.length > n) break; }
    const A = lines[lab[i]], Bl = lines[lab[e]]; if (lab[i] === lab[e]) continue;
    const cr = A.d[0] * Bl.d[1] - A.d[1] * Bl.d[0]; if (Math.abs(cr) < Math.sin(20 * Math.PI / 180)) continue;
    const t = ((Bl.c[0] - A.c[0]) * Bl.d[1] - (Bl.c[1] - A.c[1]) * Bl.d[0]) / cr, X = [A.c[0] + t * A.d[0], A.c[1] + t * A.d[1]];
    if (gap.every((g) => Math.hypot(pts[g][0] - X[0], pts[g][1] - X[1]) < 5) && Math.hypot(pts[i][0] - X[0], pts[i][1] - X[1]) < 6) for (const g of gap.length ? gap : []) pts[g] = X.slice();
    if (!gap.length) { /* соседние точки разных прямых: угол между ними уже есть */ }
  }
  return lines.length;
}

// ---------- «Плоские грани» ----------
export function snapPlanes(M, opt = {}) {
  const { pos, nrm } = M, nv = pos.length / 3, asg = new Int32Array(nv).fill(-1), planes = [];
  const minN = Math.max(60, Math.round(nv * (opt.minFrac ?? 0.012)));
  let seed = 777; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const cos20 = Math.cos(25 * Math.PI / 180), cos25 = Math.cos(30 * Math.PI / 180);
  for (let it = 0; it < 30; it++) {
    let best = null, bc = 0;
    for (let k = 0; k < 160; k++) {
      const s = (rnd() * nv) | 0; if (asg[s] >= 0) continue;
      const n = [nrm[s * 3], nrm[s * 3 + 1], nrm[s * 3 + 2]], d = n[0] * pos[s * 3] + n[1] * pos[s * 3 + 1] + n[2] * pos[s * 3 + 2];
      let c = 0; for (let v = 0; v < nv; v++) { if (asg[v] >= 0) continue; const e = n[0] * pos[v * 3] + n[1] * pos[v * 3 + 1] + n[2] * pos[v * 3 + 2] - d; if (e > -1.2 && e < 1.2 && n[0] * nrm[v * 3] + n[1] * nrm[v * 3 + 1] + n[2] * nrm[v * 3 + 2] > cos20) c++; }
      if (c > bc) { bc = c; best = { n, d }; }
    }
    if (!best || bc < minN) break;
    // уточнение: плоскость по МНК (главные оси) через опорные точки, 2 прохода
    let pl = best, inl = [];
    for (let pass = 0; pass < 2; pass++) {
      inl = [];
      for (let v = 0; v < nv; v++) { if (asg[v] >= 0) continue; const e = pl.n[0] * pos[v * 3] + pl.n[1] * pos[v * 3 + 1] + pl.n[2] * pos[v * 3 + 2] - pl.d; if (Math.abs(e) < 1.6 && pl.n[0] * nrm[v * 3] + pl.n[1] * nrm[v * 3 + 1] + pl.n[2] * nrm[v * 3 + 2] > cos25) inl.push(v); }
      if (inl.length < minN) break;
      const c = [0, 0, 0]; for (const v of inl) for (let q = 0; q < 3; q++) c[q] += pos[v * 3 + q] / inl.length;
      const C = new Array(9).fill(0); for (const v of inl) for (let r = 0; r < 3; r++) for (let q = 0; q < 3; q++) C[r * 3 + q] += (pos[v * 3 + r] - c[r]) * (pos[v * 3 + q] - c[q]);
      let n = smallestEig(C); if (n[0] * pl.n[0] + n[1] * pl.n[1] + n[2] * pl.n[2] < 0) n = n.map((x) => -x);
      pl = { n, d: n[0] * c[0] + n[1] * c[1] + n[2] * c[2] };
    }
    if (inl.length < minN) { // этот кандидат не удержался — пометим, чтобы не выбирать снова
      continue;
    }
    let se = 0; for (const v of inl) { const e = pl.n[0] * pos[v * 3] + pl.n[1] * pos[v * 3 + 1] + pl.n[2] * pos[v * 3 + 2] - pl.d; se += e * e; }
    if (Math.sqrt(se / inl.length) > 0.9) break; // это уже не плоскость
    const id = planes.length; planes.push(pl); for (const v of inl) asg[v] = id;
  }
  if (!planes.length) return { mesh: M, info: 'плоскостей не найдено — оставлена обычная форма' };
  // притягивание: к своей плоскости; у рёбер — к линии пересечения двух; в углах — к точке трёх
  const cos65 = Math.cos(65 * Math.PI / 180);
  const out = new Float32Array(pos); let kept = 0;
  for (let v = 0; v < nv; v++) {
    const p = [pos[v * 3], pos[v * 3 + 1], pos[v * 3 + 2]], nn = [nrm[v * 3], nrm[v * 3 + 1], nrm[v * 3 + 2]];
    const cand = [];
    planes.forEach((pl, i) => { const e = pl.n[0] * p[0] + pl.n[1] * p[1] + pl.n[2] * p[2] - pl.d; if (i === asg[v] || (Math.abs(e) < 2.2 && pl.n[0] * nn[0] + pl.n[1] * nn[1] + pl.n[2] * nn[2] > cos65)) cand.push([Math.abs(e), i]); });
    if (!cand.length) continue;
    cand.sort((a, b) => a[0] - b[0]);
    const sel = []; for (const [, i] of cand) { if (sel.every((j) => Math.abs(dot(planes[i].n, planes[j].n)) < 0.94)) sel.push(i); if (sel.length === 3) break; }
    // допуск (v2.4): точка посреди грани глубже ~0.8 мм под плоскостью — настоящая вмятина (оболочка бывает только шире
    // предмета, а не уже), её не выравниваем. Рёбра и углы (2–3 плоскости) — выпрямляем как раньше
    if (sel.length === 1) { const pl = planes[sel[0]]; if (dot(pl.n, p) - pl.d < -(opt.band ?? 0.8)) { kept++; continue; } }
    const q = projectPlanes(p, sel.map((i) => planes[i]));
    if (q && Math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2]) < 4) { out[v * 3] = q[0]; out[v * 3 + 1] = q[1]; out[v * 3 + 2] = q[2]; }
  }
  const M2 = splitCreases({ pos: out, idx: M.idx }, 30);
  return { mesh: M2, kept, info: `${kept > 20 ? 'вмятины сохранены, ' : ''}${planes.length} плоск${planes.length % 10 === 1 && planes.length % 100 !== 11 ? 'ость' : planes.length % 10 >= 2 && planes.length % 10 <= 4 && (planes.length % 100 < 10 || planes.length % 100 >= 20) ? 'ости' : 'остей'}` };
}
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
// ближайшая к p точка, лежащая на всех плоскостях (1–3)
function projectPlanes(p, P) {
  const k = P.length; if (!k) return null;
  // x = p − Nᵀ λ, где (N Nᵀ) λ = N p − d
  const Gm = [], r = [];
  for (let i = 0; i < k; i++) { r.push(dot(P[i].n, p) - P[i].d); for (let j = 0; j < k; j++) Gm.push(dot(P[i].n, P[j].n)); }
  const lam = solve(Gm, r, k); if (!lam) return k > 1 ? projectPlanes(p, P.slice(0, k - 1)) : null;
  const x = p.slice(); for (let i = 0; i < k; i++) for (let c = 0; c < 3; c++) x[c] -= lam[i] * P[i].n[c];
  return x;
}
function solve(A, b, n) {
  const M = A.slice(), x = b.slice();
  for (let i = 0; i < n; i++) {
    let piv = i; for (let r = i + 1; r < n; r++) if (Math.abs(M[r * n + i]) > Math.abs(M[piv * n + i])) piv = r;
    if (Math.abs(M[piv * n + i]) < 0.05) return null;
    if (piv !== i) { for (let c = 0; c < n; c++) [M[i * n + c], M[piv * n + c]] = [M[piv * n + c], M[i * n + c]]; [x[i], x[piv]] = [x[piv], x[i]]; }
    for (let r = 0; r < n; r++) if (r !== i) { const f = M[r * n + i] / M[i * n + i]; for (let c = 0; c < n; c++) M[r * n + c] -= f * M[i * n + c]; x[r] -= f * x[i]; }
  }
  return x.map((v, i) => v / M[i * n + i]);
}
function smallestEig(C) {
  // обратные итерации со сдвигом: собственный вектор наименьшего значения симметричной 3×3
  const tr = C[0] + C[4] + C[8], A = [tr - C[0], -C[1], -C[2], -C[3], tr - C[4], -C[5], -C[6], -C[7], tr - C[8]];
  let v = [0.3, 0.5, 0.8];
  for (let i = 0; i < 60; i++) { const w = [A[0] * v[0] + A[1] * v[1] + A[2] * v[2], A[3] * v[0] + A[4] * v[1] + A[5] * v[2], A[6] * v[0] + A[7] * v[1] + A[8] * v[2]]; const l = Math.hypot(...w) || 1; v = w.map((x) => x / l); }
  return v;
}
// острые рёбра: вершина делится, если нормали прилегающих треугольников расходятся больше чем на deg
export function splitCreases(M, deg = 30) {
  const { pos, idx } = M, nv = pos.length / 3, nt = idx.length / 3, cosT = Math.cos(deg * Math.PI / 180);
  const fn = new Float32Array(nt * 3);
  for (let t = 0; t < nt; t++) {
    const a = idx[t * 3] * 3, b = idx[t * 3 + 1] * 3, c = idx[t * 3 + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2], vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    const x = uy * vz - uz * vy, y = uz * vx - ux * vz, z = ux * vy - uy * vx, l = Math.hypot(x, y, z) || 1;
    fn[t * 3] = x / l; fn[t * 3 + 1] = y / l; fn[t * 3 + 2] = z / l;
  }
  const inc = Array.from({ length: nv }, () => []); for (let t = 0; t < nt; t++) for (let k = 0; k < 3; k++) inc[idx[t * 3 + k]].push(t);
  const P = [], N = [], I = new Uint32Array(idx.length);
  for (let v = 0; v < nv; v++) {
    const groups = []; // [нормаль-сумма, первая нормаль, новый индекс]
    for (const t of inc[v]) {
      const n = [fn[t * 3], fn[t * 3 + 1], fn[t * 3 + 2]];
      let g = groups.find((G) => dot(G.f, n) > cosT);
      if (!g) { g = { f: n, s: [0, 0, 0], id: P.length / 3 }; groups.push(g); P.push(pos[v * 3], pos[v * 3 + 1], pos[v * 3 + 2]); N.push(0, 0, 0); }
      for (let c = 0; c < 3; c++) g.s[c] += n[c];
      for (let k = 0; k < 3; k++) if (idx[t * 3 + k] === v) I[t * 3 + k] = g.id;
    }
    for (const g of groups) { const l = Math.hypot(...g.s) || 1; for (let c = 0; c < 3; c++) N[g.id * 3 + c] = g.s[c] / l; }
  }
  return { pos: new Float32Array(P), nrm: new Float32Array(N), idx: I };
}
