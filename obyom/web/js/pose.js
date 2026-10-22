// Объём — положение камеры по меткам коврика: гомография, фокус, поза, уточнение (Гаусс—Ньютон).
// Камера как в OpenCV: x вправо, y вниз, z вперёд. Мир — коврик: X вправо, Y вперёд, Z вверх (мм).

export function solve(A, b) { // Гаусс с выбором ведущего; A — массив строк, b — массив
  const n = b.length, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    if (Math.abs(M[p][c]) < 1e-12) return null;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; if (f) for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  return M.map((r, i) => r[n] / r[i]);
}

// гомография по ≥4 парам (src: мир XY, dst: пиксели), с нормализацией
export function homography(src, dst) {
  const norm = (P) => {
    let mx = 0, my = 0; for (const p of P) { mx += p[0]; my += p[1]; } mx /= P.length; my /= P.length;
    let d = 0; for (const p of P) d += Math.hypot(p[0] - mx, p[1] - my); d = d / P.length || 1;
    const s = Math.SQRT2 / d; return { T: [s, 0, -s * mx, 0, s, -s * my, 0, 0, 1], f: (p) => [(p[0] - mx) * s, (p[1] - my) * s] };
  };
  const ns = norm(src), nd = norm(dst);
  const AtA = Array.from({ length: 8 }, () => new Array(8).fill(0)), Atb = new Array(8).fill(0);
  for (let i = 0; i < src.length; i++) {
    const [x, y] = ns.f(src[i]), [u, v] = nd.f(dst[i]);
    const rows = [[x, y, 1, 0, 0, 0, -u * x, -u * y, u], [0, 0, 0, x, y, 1, -v * x, -v * y, v]];
    for (const r of rows) for (let a = 0; a < 8; a++) { Atb[a] += r[a] * r[8]; for (let b = 0; b < 8; b++) AtA[a][b] += r[a] * r[b]; }
  }
  const hh = solve(AtA, Atb); if (!hh) return null;
  const Hn = [...hh, 1];
  // H = Td⁻¹ · Hn · Ts
  const Td = nd.T, s = Td[0], Tdi = [1 / s, 0, -Td[2] / s, 0, 1 / s, -Td[5] / s, 0, 0, 1];
  const H = mul3(Tdi, mul3(Hn, ns.T));
  return H.map(v => v / H[8]);
}
export function mul3(A, B) { const C = new Array(9); for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) C[i * 3 + j] = A[i * 3] * B[j] + A[i * 3 + 1] * B[3 + j] + A[i * 3 + 2] * B[6 + j]; return C; }
export function applyH(H, x, y) { const z = H[6] * x + H[7] * y + H[8]; return [(H[0] * x + H[1] * y + H[2]) / z, (H[3] * x + H[4] * y + H[5]) / z]; }
export function invH(m) {
  const [a, b, c, d, e, f, g, h, i] = m, A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g, det = a * A + b * B + c * C;
  return [A / det, -(b * i - c * h) / det, (b * f - c * e) / det, B / det, (a * i - c * g) / det, -(a * f - c * d) / det, C / det, -(a * h - b * g) / det, (a * e - b * d) / det];
}

// оценка фокуса по гомографии плоскости (главная точка — центр кадра, пиксели квадратные)
// возвращает {a, b}: уравнения a·(1/f²) + b = 0 (две штуки), чтобы копить по многим кадрам
export function focalEqs(H, cx, cy) {
  const T = [1, 0, -cx, 0, 1, -cy, 0, 0, 1], M = mul3(T, H);
  const h11 = M[0], h21 = M[3], h31 = M[6], h12 = M[1], h22 = M[4], h32 = M[7];
  return [{ a: h11 * h12 + h21 * h22, b: h31 * h32 }, { a: h11 * h11 + h21 * h21 - h12 * h12 - h22 * h22, b: h31 * h31 - h32 * h32 }];
}
export function focalFromEqs(eqs) {
  let num = 0, den = 0;
  for (const e of eqs) { num += e.a * e.b; den += e.a * e.a; }
  const x = -num / den; // 1/f²
  return x > 0 ? 1 / Math.sqrt(x) : 0;
}

// --- вращения ---
export function rodrigues(w) {
  const th = Math.hypot(w[0], w[1], w[2]);
  if (th < 1e-12) return [1, -w[2], w[1], w[2], 1, -w[0], -w[1], w[0], 1];
  const k = [w[0] / th, w[1] / th, w[2] / th], c = Math.cos(th), s = Math.sin(th), v = 1 - c;
  return [c + k[0] * k[0] * v, k[0] * k[1] * v - k[2] * s, k[0] * k[2] * v + k[1] * s,
    k[1] * k[0] * v + k[2] * s, c + k[1] * k[1] * v, k[1] * k[2] * v - k[0] * s,
    k[2] * k[0] * v - k[1] * s, k[2] * k[1] * v + k[0] * s, c + k[2] * k[2] * v];
}
function orthonormalize(R) { // полярное разложение итерациями
  let M = R.slice();
  for (let it = 0; it < 8; it++) { const I = invH(M); M = M.map((v, i) => 0.5 * (v + I[(i % 3) * 3 + ((i / 3) | 0)])); }
  return M;
}

// поза из гомографии: H ~ K [r1 r2 t]
export function poseFromH(H, K) {
  const Ki = [1 / K.fx, 0, -K.cx / K.fx, 0, 1 / K.fy, -K.cy / K.fy, 0, 0, 1], M = mul3(Ki, H);
  const h1 = [M[0], M[3], M[6]], h2 = [M[1], M[4], M[7]], h3 = [M[2], M[5], M[8]];
  let l = 2 / (Math.hypot(...h1) + Math.hypot(...h2));
  if (h3[2] * l < 0) l = -l;
  const r1 = h1.map(v => v * l), r2 = h2.map(v => v * l), t = h3.map(v => v * l);
  const r3 = [r1[1] * r2[2] - r1[2] * r2[1], r1[2] * r2[0] - r1[0] * r2[2], r1[0] * r2[1] - r1[1] * r2[0]];
  const R = orthonormalize([r1[0], r2[0], r3[0], r1[1], r2[1], r3[1], r1[2], r2[2], r3[2]]);
  return { R, t };
}

export function project(K, R, t, X, Y, Z) {
  const x = R[0] * X + R[1] * Y + R[2] * Z + t[0], y = R[3] * X + R[4] * Y + R[5] * Z + t[1], z = R[6] * X + R[7] * Y + R[8] * Z + t[2];
  return [K.fx * x / z + K.cx, K.fy * y / z + K.cy, z];
}

// уточнение позы по точкам (мир XYZ ↔ пиксели), возвращает {R, t, rms}
export function refinePose(K, R0, t0, Pw, Pi, iters = 12) {
  let R = R0.slice(), t = t0.slice(), lambda = 1e-3;
  const err = (R, t) => { let s = 0; for (let i = 0; i < Pw.length; i++) { const p = project(K, R, t, ...Pw[i]); s += (p[0] - Pi[i][0]) ** 2 + (p[1] - Pi[i][1]) ** 2; } return s; };
  let e0 = err(R, t);
  for (let it = 0; it < iters; it++) {
    const A = Array.from({ length: 6 }, () => new Array(6).fill(0)), b = new Array(6).fill(0);
    for (let i = 0; i < Pw.length; i++) {
      const [X, Y, Z] = Pw[i];
      const rx = R[0] * X + R[1] * Y + R[2] * Z, ry = R[3] * X + R[4] * Y + R[5] * Z, rz = R[6] * X + R[7] * Y + R[8] * Z;
      const x = rx + t[0], y = ry + t[1], z = rz + t[2];
      const u = K.fx * x / z + K.cx, v = K.fy * y / z + K.cy;
      const ru = u - Pi[i][0], rv = v - Pi[i][1];
      const du = [K.fx / z, 0, -K.fx * x / (z * z)], dv = [0, K.fy / z, -K.fy * y / (z * z)];
      // d(Pc)/d(δω) = -[RP]× ; d(Pc)/dt = I
      const Jw = [[0, rz, -ry], [-rz, 0, rx], [ry, -rx, 0]]; // столбцы: ∂Pc/∂ω_k = (e_k × RP) → матрица -[RP]×
      const ju = new Array(6), jv = new Array(6);
      for (let k = 0; k < 3; k++) {
        ju[k] = du[0] * Jw[0][k] + du[1] * Jw[1][k] + du[2] * Jw[2][k];
        jv[k] = dv[0] * Jw[0][k] + dv[1] * Jw[1][k] + dv[2] * Jw[2][k];
        ju[3 + k] = du[k]; jv[3 + k] = dv[k];
      }
      for (let a = 0; a < 6; a++) { b[a] -= ju[a] * ru + jv[a] * rv; for (let c = 0; c < 6; c++) A[a][c] += ju[a] * ju[c] + jv[a] * jv[c]; }
    }
    let improved = false;
    for (let tries = 0; tries < 5 && !improved; tries++) {
      const Ad = A.map((r, i) => r.map((v, j) => (i === j ? v * (1 + lambda) + 1e-9 : v)));
      const d = solve(Ad, b); if (!d) break;
      const dR = rodrigues([d[0], d[1], d[2]]), R2 = mul3(dR, R), t2 = [t[0] + d[3], t[1] + d[4], t[2] + d[5]];
      const e2 = err(R2, t2);
      if (e2 < e0) { R = R2; t = t2; e0 = e2; lambda = Math.max(1e-7, lambda / 4); improved = true; }
      else lambda *= 8;
    }
    if (!improved) break;
  }
  return { R, t, rms: Math.sqrt(e0 / Math.max(1, Pw.length)) };
}

// поза по найденным меткам: markers [{id, corners}] + раскладка коврика
export function poseFromMarkers(markers, layout, K) {
  const byId = new Map(layout.markers.map(m => [m.id, m]));
  let Pw = [], Pi = [], owners = [];
  for (const m of markers) { const d = byId.get(m.id); if (!d) continue; for (let k = 0; k < 4; k++) { Pw.push([d.corners[k][0], d.corners[k][1], 0]); Pi.push(m.corners[k]); owners.push(m.id); } }
  if (Pw.length < 4) return null;
  let H = homography(Pw.map(p => [p[0], p[1]]), Pi); if (!H) return null;
  // отбрасываем метку, которая сильно не согласуется (ложное чтение)
  if (Pw.length >= 12) {
    const errs = new Map();
    for (let i = 0; i < Pw.length; i++) { const p = applyH(H, Pw[i][0], Pw[i][1]); const e = Math.hypot(p[0] - Pi[i][0], p[1] - Pi[i][1]); errs.set(owners[i], Math.max(errs.get(owners[i]) || 0, e)); }
    const med = [...errs.values()].sort((a, b) => a - b)[errs.size >> 1];
    const bad = new Set([...errs].filter(([, e]) => e > Math.max(3, med * 4)).map(([id]) => id));
    if (bad.size) { const keep = owners.map(o => !bad.has(o)); Pw = Pw.filter((_, i) => keep[i]); Pi = Pi.filter((_, i) => keep[i]); owners = owners.filter((_, i) => keep[i]); H = homography(Pw.map(p => [p[0], p[1]]), Pi); if (!H) return null; }
  }
  const p0 = poseFromH(H, K);
  const r = refinePose(K, p0.R, p0.t, Pw, Pi);
  return { R: r.R, t: r.t, rms: r.rms, H, n: owners.length / 4, Pw, Pi };
}

// положение камеры в мире и её «высота» над столом
export function camCenter(R, t) { return [-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])]; }
export function camAngles(R, t) { // азимут (0 = спереди, по часовой сверху) и высота над горизонтом, в градусах
  const c = camCenter(R, t), r = Math.hypot(c[0], c[1]);
  return { az: ((Math.atan2(c[0], c[1]) * 180 / Math.PI) + 360) % 360, el: Math.atan2(c[2], r) * 180 / Math.PI, dist: Math.hypot(c[0], c[1], c[2]), c };
}

// уточнение общего фокуса по набору кадров: золотое сечение по суммарной ошибке
export function refineFocal(frames, K0) {
  const total = (f) => {
    const K = { ...K0, fx: f, fy: f }; let s = 0, n = 0;
    for (const fr of frames) { const p0 = poseFromH(fr.H, K); const r = refinePose(K, p0.R, p0.t, fr.Pw, fr.Pi, 6); s += r.rms * r.rms * fr.Pw.length; n += fr.Pw.length; }
    return s / Math.max(1, n);
  };
  let a = K0.fx * 0.7, b = K0.fx * 1.4;
  const gr = (Math.sqrt(5) - 1) / 2;
  let c = b - gr * (b - a), d = a + gr * (b - a), fc = total(c), fd = total(d);
  for (let i = 0; i < 22; i++) {
    if (fc < fd) { b = d; d = c; fd = fc; c = b - gr * (b - a); fc = total(c); }
    else { a = c; c = d; fc = fd; d = a + gr * (b - a); fd = total(d); }
  }
  const f = (a + b) / 2;
  return { f, rms: Math.sqrt(total(f)) };
}

// ---------- Дисторсия объектива (v2.3) ----------
// Модель: x_d = x_u·(1 + k1·r_u²) в нормированных координатах (x = (u − cx)/f). Оценка — по углам меток: поза и k1 по очереди.
export function undistortPts(pts, K, k1) {
  if (!k1) return pts;
  return pts.map(([u, v]) => { const xd = (u - K.cx) / K.fx, yd = (v - K.cy) / K.fy; let xu = xd, yu = yd;
    for (let i = 0; i < 8; i++) { const s = 1 + k1 * (xu * xu + yu * yu); xu = xd / s; yu = yd / s; }
    return [xu * K.fx + K.cx, yu * K.fy + K.cy]; });
}
export function fitK1(poses, K, iters = 3) {
  const rmsOf = (k) => { let s = 0, n = 0; for (const p of poses) { const Pi = undistortPts(p.Pi, K, k), H = homography(p.Pw.map((q) => [q[0], q[1]]), Pi); if (!H) continue; const p0 = poseFromH(H, K), r = refinePose(K, p0.R, p0.t, p.Pw, Pi, 6); s += r.rms * r.rms * Pi.length; n += Pi.length; } return Math.sqrt(s / Math.max(1, n)); };
  // g(k): позы по исправленным с k углам → МНК-оценка k1 по искажённым наблюдениям. Неподвижная точка g — ответ;
  // поза частично «съедает» дисторсию, поэтому простая итерация сходится медленно — ускоряем Стеффенсеном.
  const g = (k1) => {
    let num = 0, den = 0;
    for (const p of poses) {
      const Pi = undistortPts(p.Pi, K, k1), H = homography(p.Pw.map((q) => [q[0], q[1]]), Pi); if (!H) continue;
      const p0 = poseFromH(H, K), r = refinePose(K, p0.R, p0.t, p.Pw, Pi, 6), R = r.R, t = r.t;
      for (let i = 0; i < p.Pw.length; i++) { const [X, Y, Z] = p.Pw[i], z = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (z <= 1) continue;
        const xn = (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / z, yn = (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / z, r2 = xn * xn + yn * yn;
        const xo = (p.Pi[i][0] - K.cx) / K.fx, yo = (p.Pi[i][1] - K.cy) / K.fy; // наблюдение — искажённое
        num += (xo - xn) * xn * r2 + (yo - yn) * yn * r2; den += r2 * r2 * (xn * xn + yn * yn); }
    }
    return den > 0 ? Math.max(-0.4, Math.min(0.4, num / den)) : k1;
  };
  const rms0 = rmsOf(0); let k = 0;
  for (let it = 0; it < iters; it++) {
    const k1 = g(k), k2 = g(k1), d = k2 - 2 * k1 + k;
    const kn = Math.abs(d) > 1e-9 ? k - (k1 - k) ** 2 / d : k2;
    k = Math.max(-0.4, Math.min(0.4, Number.isFinite(kn) ? kn : k2));
    if (Math.abs(k2 - k1) < 1e-5) break;
  }
  const rms1 = rmsOf(k);
  if (!(rms1 < rms0)) return { k1: 0, rms0, rms1: rms0 };
  return { k1: k, rms0, rms1 };
}

// дисторсия (v2.3): перерисовка кадра в неискажённую проекцию; dist = { k1, fr } — fr = фокус / ширина кадра
export function undistortRGBA(rgba, w, h, k1, fx) {
  const out = new Uint8Array(w * h * 4), cx = w / 2, cy = h / 2;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const xu = (x - cx) / fx, yu = (y - cy) / fx, s = 1 + k1 * (xu * xu + yu * yu), u = cx + xu * s * fx, v = cy + yu * s * fx, o = (y * w + x) * 4;
    const i0 = Math.floor(u), j0 = Math.floor(v); if (i0 < 0 || j0 < 0 || i0 >= w - 1 || j0 >= h - 1) { const q = (Math.min(h - 1, Math.max(0, Math.round(v))) * w + Math.min(w - 1, Math.max(0, Math.round(u)))) * 4; out[o] = rgba[q]; out[o + 1] = rgba[q + 1]; out[o + 2] = rgba[q + 2]; out[o + 3] = 255; continue; }
    const a = u - i0, b = v - j0, q = (j0 * w + i0) * 4, q2 = q + w * 4;
    for (let c = 0; c < 3; c++) out[o + c] = (1 - b) * ((1 - a) * rgba[q + c] + a * rgba[q + 4 + c]) + b * ((1 - a) * rgba[q2 + c] + a * rgba[q2 + 4 + c]) + 0.5;
    out[o + 3] = 255;
  }
  return out;
}
