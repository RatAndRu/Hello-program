// Объём — «доснять низ»: совмещение второй съёмки (предмет лежит на боку / вверх дном) с основной.
// Без нейросетей: перебор поворотов (главные оси + равномерная сетка) → ICP по поверхностным вокселям
// (итеративно: ближайшие точки → лучший поворот по Хорну) → проверка совпадения в обе стороны.
// Потом оболочки пересекаются: вторая съёмка видит дно и верх сбоку — и вырезает то, что первая не видела.

// поверхностные воксели оболочки (занятые, у которых есть пустой сосед), без нижних zskip мм (там срез по столу)
export function surfacePoints(G, zskip = 3, maxN = 4000) {
  const { occ, nx, ny, nz, vs, origin } = G, S = nx * ny, zs = Math.ceil(zskip / vs), all = [];
  for (let z = zs; z < nz; z++) for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) {
    const i = z * S + y * nx + x; if (occ[i] < 0.5) continue;
    const e = (q) => occ[q] < 0.5;
    if ((x > 0 && e(i - 1)) || (x < nx - 1 && e(i + 1)) || (y > 0 && e(i - nx)) || (y < ny - 1 && e(i + nx)) || (z > 0 && e(i - S)) || z === nz - 1 || (z < nz - 1 && e(i + S)))
      all.push(origin[0] + x * vs, origin[1] + y * vs, origin[2] + z * vs);
  }
  return subsample(all, maxN);
}
function volumePoints(G, maxN = 6000) {
  const { occ, nx, ny, nz, vs, origin } = G, S = nx * ny, all = [];
  for (let z = 0; z < nz; z++) for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) if (occ[z * S + y * nx + x] > 0.5) all.push(origin[0] + x * vs, origin[1] + y * vs, origin[2] + z * vs);
  return subsample(all, maxN);
}
function subsample(all, maxN) {
  const n = all.length / 3; if (n <= maxN) return Float64Array.from(all);
  const out = new Float64Array(maxN * 3), st = n / maxN;
  for (let k = 0; k < maxN; k++) { const j = Math.floor(k * st) * 3; out[k * 3] = all[j]; out[k * 3 + 1] = all[j + 1]; out[k * 3 + 2] = all[j + 2]; }
  return out;
}

// ближайшая точка: равномерная сетка ячеек (поиск в 3×3×3 ячейках — верен до расстояния = ячейке)
class NN {
  constructor(P, cell) {
    this.P = P; this.c = cell; this.m = new Map();
    for (let i = 0; i < P.length / 3; i++) { const k = this.key(Math.floor(P[i * 3] / cell), Math.floor(P[i * 3 + 1] / cell), Math.floor(P[i * 3 + 2] / cell)); let a = this.m.get(k); if (!a) this.m.set(k, a = []); a.push(i); }
  }
  key(a, b, c) { return ((a + 1024) * 2048 + (b + 1024)) * 2048 + (c + 1024); }
  near(x, y, z) {
    const c = this.c, ix = Math.floor(x / c), iy = Math.floor(y / c), iz = Math.floor(z / c), P = this.P;
    let best = -1, bd = c * c;
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (let d = -1; d <= 1; d++) {
      const L = this.m.get(this.key(ix + a, iy + b, iz + d)); if (!L) continue;
      for (const j of L) { const dx = P[j * 3] - x, dy = P[j * 3 + 1] - y, dz = P[j * 3 + 2] - z, q = dx * dx + dy * dy + dz * dz; if (q < bd) { bd = q; best = j; } }
    }
    return best < 0 ? null : [best, bd];
  }
}

// собственные векторы симметричной матрицы (Якоби); n ≤ 4
function eigSym(A, n) {
  const a = A.slice(), V = new Array(n * n).fill(0); for (let i = 0; i < n; i++) V[i * n + i] = 1;
  for (let sweep = 0; sweep < 50; sweep++) {
    let off = 0; for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) off += a[p * n + q] ** 2;
    if (off < 1e-18) break;
    for (let p = 0; p < n; p++) for (let q = p + 1; q < n; q++) {
      const apq = a[p * n + q]; if (Math.abs(apq) < 1e-20) continue;
      const th = (a[q * n + q] - a[p * n + p]) / (2 * apq), t = Math.sign(th || 1) / (Math.abs(th) + Math.sqrt(th * th + 1)), c = 1 / Math.sqrt(t * t + 1), s = t * c;
      for (let k = 0; k < n; k++) { const akp = a[k * n + p], akq = a[k * n + q]; a[k * n + p] = c * akp - s * akq; a[k * n + q] = s * akp + c * akq; }
      for (let k = 0; k < n; k++) { const apk = a[p * n + k], aqk = a[q * n + k]; a[p * n + k] = c * apk - s * aqk; a[q * n + k] = s * apk + c * aqk; }
      for (let k = 0; k < n; k++) { const vkp = V[k * n + p], vkq = V[k * n + q]; V[k * n + p] = c * vkp - s * vkq; V[k * n + q] = s * vkp + c * vkq; }
    }
  }
  const vals = Array.from({ length: n }, (_, i) => a[i * n + i]), ord = vals.map((_, i) => i).sort((i, j) => vals[j] - vals[i]);
  return { vals: ord.map((i) => vals[i]), vecs: ord.map((i) => Array.from({ length: n }, (_, k) => V[k * n + i])) };
}
// лучший поворот R (и сдвиг t), переводящий точки b в a (метод Хорна через кватернион)
function horn(pa, pb, n) {
  const ca = [0, 0, 0], cb = [0, 0, 0];
  for (let i = 0; i < n; i++) for (let c = 0; c < 3; c++) { ca[c] += pa[i * 3 + c]; cb[c] += pb[i * 3 + c]; }
  for (let c = 0; c < 3; c++) { ca[c] /= n; cb[c] /= n; }
  const S = new Array(9).fill(0);
  for (let i = 0; i < n; i++) for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) S[r * 3 + c] += (pb[i * 3 + r] - cb[r]) * (pa[i * 3 + c] - ca[c]);
  const [xx, xy, xz, yx, yy, yz, zx, zy, zz] = S;
  const N = [xx + yy + zz, yz - zy, zx - xz, xy - yx, yz - zy, xx - yy - zz, xy + yx, zx + xz, zx - xz, xy + yx, -xx + yy - zz, yz + zy, xy - yx, zx + xz, yz + zy, -xx - yy + zz];
  const [w, x, y, z] = eigSym(N, 4).vecs[0];
  const R = quatR(w, x, y, z);
  return { R, t: [ca[0] - (R[0] * cb[0] + R[1] * cb[1] + R[2] * cb[2]), ca[1] - (R[3] * cb[0] + R[4] * cb[1] + R[5] * cb[2]), ca[2] - (R[6] * cb[0] + R[7] * cb[1] + R[8] * cb[2])] };
}
function quatR(w, x, y, z) {
  const l = Math.hypot(w, x, y, z); w /= l; x /= l; y /= l; z /= l;
  return [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x), 2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)];
}
const mul = (A, B) => { const C = new Array(9); for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) C[r * 3 + c] = A[r * 3] * B[c] + A[r * 3 + 1] * B[3 + c] + A[r * 3 + 2] * B[6 + c]; return C; };
const app = (R, t, p, i) => [R[0] * p[i] + R[1] * p[i + 1] + R[2] * p[i + 2] + t[0], R[3] * p[i] + R[4] * p[i + 1] + R[5] * p[i + 2] + t[1], R[6] * p[i] + R[7] * p[i + 1] + R[8] * p[i + 2] + t[2]];

// ICP: B → A. thr — порог пары (мм) на каждой итерации (по убыванию)
function icp(PB, nn, R, t, iters, thr0, thr1, stride = 1) {
  const n = PB.length / 3, pa = new Float64Array(n * 3), pb = new Float64Array(n * 3);
  for (let it = 0; it < iters; it++) {
    const thr = thr0 + (thr1 - thr0) * Math.min(1, it / Math.max(1, iters * 0.7)), t2 = thr * thr; let m = 0;
    for (let i = 0; i < n; i += stride) {
      const q = app(R, t, PB, i * 3), r = nn.near(q[0], q[1], q[2]); if (!r || r[1] > t2) continue;
      const j = r[0]; pa[m * 3] = nn.P[j * 3]; pa[m * 3 + 1] = nn.P[j * 3 + 1]; pa[m * 3 + 2] = nn.P[j * 3 + 2];
      pb[m * 3] = PB[i * 3]; pb[m * 3 + 1] = PB[i * 3 + 1]; pb[m * 3 + 2] = PB[i * 3 + 2]; m++;
    }
    if (m < 20) break;
    ({ R, t } = horn(pa, pb, m));
  }
  return { R, t };
}
function inliers(PB, nn, R, t, tau, stride = 1) {
  const n = PB.length / 3; let k = 0, c = 0, se = 0;
  for (let i = 0; i < n; i += stride) { c++; const q = app(R, t, PB, i * 3), r = nn.near(q[0], q[1], q[2]); if (r && r[1] <= tau * tau) { k++; se += r[1]; } }
  return { f: k / Math.max(1, c), rms: k ? Math.sqrt(se / k) : 1e9 };
}
function pca(P) {
  const n = P.length / 3, c = [0, 0, 0]; for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) c[k] += P[i * 3 + k] / n;
  const C = new Array(9).fill(0);
  for (let i = 0; i < n; i++) for (let r = 0; r < 3; r++) for (let s = 0; s < 3; s++) C[r * 3 + s] += (P[i * 3 + r] - c[r]) * (P[i * 3 + s] - c[s]) / n;
  return { c, E: eigSym(C, 3).vecs };
}

// GA — основная оболочка, GB — «низ». Возвращает R, t (точка B → точка A), долю совпадения и среднюю ошибку
export function alignHulls(GA, GB, onProgress, dbg) {
  const SA = surfacePoints(GA, 3, 5000), SB = surfacePoints(GB, 3, 5000);
  const VA = pca(volumePoints(GA)), VB = pca(volumePoints(GB));
  const nnA5 = new NN(SA, 6), nnA2 = new NN(SA, 2.5), nnB2 = new NN(SB, 2.5);
  // кандидаты поворота: соответствия главных осей (24 с учётом знаков) + 96 равномерных
  const cands = [];
  const EA = VA.E, EB = VB.E, perms = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];
  for (const p of perms) for (let sg = 0; sg < 8; sg++) {
    const s = [sg & 1 ? -1 : 1, sg & 2 ? -1 : 1, sg & 4 ? -1 : 1];
    // R = Σ_k s_k · a_{p[k]} · b_k^T
    const R = new Array(9).fill(0);
    for (let k = 0; k < 3; k++) for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) R[r * 3 + c] += s[k] * EA[p[k]][r] * EB[k][c];
    const det = R[0] * (R[4] * R[8] - R[5] * R[7]) - R[1] * (R[3] * R[8] - R[5] * R[6]) + R[2] * (R[3] * R[7] - R[4] * R[6]);
    if (det > 0) cands.push(R);
  }
  let seed = 12345; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  for (let k = 0; k < 96; k++) { const u1 = rnd(), u2 = rnd() * 2 * Math.PI, u3 = rnd() * 2 * Math.PI, a = Math.sqrt(1 - u1), b = Math.sqrt(u1); cands.push(quatR(a * Math.sin(u2), a * Math.cos(u2), b * Math.sin(u3), b * Math.cos(u3))); }
  const nB = SB.length / 3, qs = Math.max(1, Math.floor(nB / 300));
  const scored = cands.map((R, k) => {
    const t = [VA.c[0] - (R[0] * VB.c[0] + R[1] * VB.c[1] + R[2] * VB.c[2]), VA.c[1] - (R[3] * VB.c[0] + R[4] * VB.c[1] + R[5] * VB.c[2]), VA.c[2] - (R[6] * VB.c[0] + R[7] * VB.c[1] + R[8] * VB.c[2])];
    const r = icp(SB, nnA5, R, t, 8, 6, 4, qs);
    if (onProgress && k % 8 === 0) onProgress(0.6 * k / cands.length);
    return { ...r, s: inliers(SB, nnA5, r.R, r.t, 3, qs).f };
  }).sort((a, b) => b.s - a.s);
  const fs = Math.max(1, Math.floor(nB / 2000)), fa = Math.max(1, Math.floor(SA.length / 3 / 2000));
  const refine = (R, t) => { let r = icp(SB, nnA5, R, t, 12, 5, 2.5, fs); r = icp(SB, nnA2, r.R, r.t, 12, 2.5, 1.5, fs); return r; };
  const evalT = (r) => {
    const ab = inliers(SB, nnA2, r.R, r.t, 1.5, fs);
    // обратно: точки A в систему B
    const Ri = [r.R[0], r.R[3], r.R[6], r.R[1], r.R[4], r.R[7], r.R[2], r.R[5], r.R[8]], ti = [-(Ri[0] * r.t[0] + Ri[1] * r.t[1] + Ri[2] * r.t[2]), -(Ri[3] * r.t[0] + Ri[4] * r.t[1] + Ri[5] * r.t[2]), -(Ri[6] * r.t[0] + Ri[7] * r.t[1] + Ri[8] * r.t[2])];
    const ba = inliers(SA, nnB2, Ri, ti, 1.5, fa);
    return { R: r.R, t: r.t, score: (ab.f + ba.f) / 2, fAB: ab.f, fBA: ba.f, rms: ab.rms };
  };
  // 1) лучшие 10 кандидатов — точная подгонка
  const top = scored.slice(0, 10).map((c, k) => { const e = evalT(refine(c.R, c.t)); if (onProgress) onProgress(0.6 + 0.2 * (k + 1) / 10); return e; }).sort((a, b) => b.score - a.score);
  // 2) «прыжки» от трёх лучших: повернуть на ±8°/±16° вокруг осей через центр и снова подогнать — выход из ложных ям
  let best = top[0];
  const cB = VB.c;
  for (let k = 0; k < Math.min(3, top.length); k++) {
    let cur = top[k];
    for (let round = 0; round < 3; round++) {
      let improved = false;
      for (const deg of [8, -8, 16, -16]) for (let ax = 0; ax < 3; ax++) {
        const h = deg * Math.PI / 360, q = [Math.cos(h), 0, 0, 0]; q[1 + ax] = Math.sin(h);
        const P = quatR(q[0], q[1], q[2], q[3]);
        // поворот P вокруг текущего центра B в системе A: R' = P R, t' = c − P(c) + P t, где c = R cB + t
        const c = app(cur.R, cur.t, cB, 0), R2 = mul(P, cur.R), Pt = app(P, [0, 0, 0], cur.t, 0), Pc = app(P, [0, 0, 0], c, 0);
        const e = evalT(refine(R2, [c[0] - Pc[0] + Pt[0], c[1] - Pc[1] + Pt[1], c[2] - Pc[2] + Pt[2]]));
        if (e.score > cur.score + 0.003) { cur = e; improved = true; }
      }
      if (!improved) break;
    }
    if (cur.score > best.score) best = cur;
    if (onProgress) onProgress(0.8 + 0.2 * (k + 1) / 3);
  }
  if (dbg) { const ev = (R, t, lab) => { const ab = inliers(SB, nnA2, R, t, 1.5); console.log(lab, 'B→A', ab.f.toFixed(3), ab.rms.toFixed(2)); }; ev(dbg.R, dbg.t, 'истина'); const r = icp(SB, nnA2, dbg.R, dbg.t, 30, 2.5, 1.5); ev(r.R, r.t, 'ICP от истины'); scored.slice(0, 8).forEach((c, k) => ev(c.R, c.t, 'кандидат ' + k + ' s=' + c.s.toFixed(3))); }
  return best;
}

// Пересечение: из GA вырезается всё, что во второй съёмке (после совмещения) оказалось пустым.
// B слегка расширяется (dil вокселей) — запас на погрешность совмещения. Под столом второй съёмки предмета быть не может.
// Вне рамки второй съёмки — не трогаем (там она ничего не знает).
export function intersectHulls(GA, GB, R, t, dil = 1) {
  const B = GB, S = B.nx * B.ny;
  let ob = Uint8Array.from(B.occ, (v) => (v > 0.5 ? 1 : 0));
  for (let k = 0; k < dil; k++) {
    const nb = ob.slice();
    for (let z = 0; z < B.nz; z++) for (let y = 0; y < B.ny; y++) for (let x = 0; x < B.nx; x++) {
      const i = z * S + y * B.nx + x; if (ob[i]) continue;
      if ((x > 0 && ob[i - 1]) || (x < B.nx - 1 && ob[i + 1]) || (y > 0 && ob[i - B.nx]) || (y < B.ny - 1 && ob[i + B.nx]) || (z > 0 && ob[i - S]) || (z < B.nz - 1 && ob[i + S])) nb[i] = 1;
    }
    ob = nb;
  }
  const A = GA, SA = A.nx * A.ny, Rb2 = (B.Rb || (B.nx * B.vs / 2)) ** 2, ztol = Math.max(1.5, 1.5 * B.vs);
  let removed = 0;
  for (let z = 0; z < A.nz; z++) for (let y = 0; y < A.ny; y++) for (let x = 0; x < A.nx; x++) {
    const i = z * SA + y * A.nx + x; if (A.occ[i] < 0.5) continue;
    const px = A.origin[0] + x * A.vs - t[0], py = A.origin[1] + y * A.vs - t[1], pz = A.origin[2] + z * A.vs - t[2];
    const qx = R[0] * px + R[3] * py + R[6] * pz, qy = R[1] * px + R[4] * py + R[7] * pz, qz = R[2] * px + R[5] * py + R[8] * pz;
    let cut = false;
    if (qz < -ztol) cut = true; // под столом второй съёмки
    else {
      const bx = Math.round((qx - B.origin[0]) / B.vs), by = Math.round((qy - B.origin[1]) / B.vs), bz = Math.max(0, Math.round((qz - B.origin[2]) / B.vs));
      if (bx >= 0 && by >= 0 && bx < B.nx && by < B.ny && bz < B.nz && qx * qx + qy * qy < Rb2) cut = !ob[bz * S + by * B.nx + bx];
    }
    if (cut) { A.occ[i] = 0; removed++; }
  }
  return removed;
}
// позы кадров второй съёмки → в систему основной (p_B = Rᵀ(p_A − t))
export function framesToA(frames, R, t) {
  const Rt = [R[0], R[3], R[6], R[1], R[4], R[7], R[2], R[5], R[8]];
  const tt = [-(Rt[0] * t[0] + Rt[1] * t[1] + Rt[2] * t[2]), -(Rt[3] * t[0] + Rt[4] * t[1] + Rt[5] * t[2]), -(Rt[6] * t[0] + Rt[7] * t[1] + Rt[8] * t[2])];
  return frames.map((f) => { const R2 = mul(f.R, Rt); const t2 = app(f.R, f.t, tt, 0); return { ...f, R: R2, t: t2 }; });
}
