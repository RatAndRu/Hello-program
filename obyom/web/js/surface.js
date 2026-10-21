// Объём — поверхность: свет, рельеф, материал. Без нейросетей — фотометрия по тем же кадрам, что и текстура.
//  1) Свет: «рассеянный + одна лампа». На вертушке лампа стоит в комнате и относительно предмета поворачивается
//     вместе с камерой (на угол азимута камеры); при съёмке с рук она неподвижна относительно предмета.
//     Какой случай, решает подгонка (меньше ошибка). Тени от самого предмета и затенённость в углах — по вокселям оболочки.
//  2) Рельеф (вертушка): точку поверхности видно при разных направлениях света → нормаль по яркостям
//     (фотометрическое стерео) с мягкой тягой к нормали сетки. С рук свет не меняется — рельеф приблизительный,
//     по мелкой светотени одного кадра. Высота — интегрирование нормалей по каждому лоскуту.
//  3) Материал: всё, что ярче рассеянного света, — блики. По зонам одного цвета: ширина пика по углу «полувектора» →
//     шероховатость, цвет блика как у самой поверхности при тёмном диффузном → металл.
//  4) Текстура без теней: пиксель атласа / рассчитанное освещение в его кадре; блики заменяются цветом по всем кадрам.
// Результат — карты в пространстве той же развёртки (UV) атласа: альбедо T×T, нормали, ORM (затенённость, шероховатость,
// металл) и высота — Wr×Wr (Wr = T·рабочий/полный кадр, ≤ 1024: столько и даёт кадр рабочего размера).
import { depthMap } from './recon.js';

const clamp = (x, a, b) => (x < a ? a : x > b ? b : x);
const lum = (r, g, b) => (r + g + b) / 3;

// solve A x = b, A — 3×3 симметричная (a00 a01 a02 a11 a12 a22)
function solve3(a, b) {
  const [a00, a01, a02, a11, a12, a22] = a;
  const c00 = a11 * a22 - a12 * a12, c01 = a02 * a12 - a01 * a22, c02 = a01 * a12 - a02 * a11;
  const det = a00 * c00 + a01 * c01 + a02 * c02; if (Math.abs(det) < 1e-12) return null;
  const c11 = a00 * a22 - a02 * a02, c12 = a01 * a02 - a00 * a12, c22 = a00 * a11 - a01 * a01;
  return [(c00 * b[0] + c01 * b[1] + c02 * b[2]) / det, (c01 * b[0] + c11 * b[1] + c12 * b[2]) / det, (c02 * b[0] + c12 * b[1] + c22 * b[2]) / det];
}
// solve 4×4 (полная матрица, построчно) — Гаусс с выбором ведущего
function solveN(A, b, n) {
  const M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    if (Math.abs(M[p][c]) < 1e-12) return null; [M[c], M[p]] = [M[p], M[c]];
    for (let r = 0; r < n; r++) if (r !== c) { const k = M[r][c] / M[c][c]; for (let j = c; j <= n; j++) M[r][j] -= k * M[c][j]; }
  }
  return M.map((r, i) => r[n] / r[i]);
}
const rotZ = (v, a) => { const c = Math.cos(a), s = Math.sin(a); return [c * v[0] - s * v[1], s * v[0] + c * v[1], v[2]]; };
const camC = (f) => { const R = f.R, t = f.t; return [-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])]; };

// воксели: занято ли (за пределами сетки — пусто; ниже стола — занято: стол заслоняет)
function occFn(G) {
  if (!G) return null;
  const { occ, nx, ny, nz, vs, origin } = G;
  return (X, Y, Z) => {
    if (Z < 0) return true;
    const x = Math.floor((X - origin[0]) / vs), y = Math.floor((Y - origin[1]) / vs), z = Math.floor((Z - origin[2]) / vs);
    if (x < 0 || y < 0 || z < 0 || x >= nx || y >= ny || z >= nz) return false;
    return occ[(z * ny + y) * nx + x] > 0.5;
  };
}
function march(occ, P, d, step, len) {
  for (let s = step; s < len; s += step) if (occ(P[0] + d[0] * s, P[1] + d[1] * s, P[2] + d[2] * s)) return true;
  return false;
}
// 24 направления по полусфере (косинусное распределение), вокруг +Z
const HEMI = (() => { const o = []; for (let i = 0; i < 24; i++) { const u = (i + 0.5) / 24, ph = i * 2.39996, r = Math.sqrt(u); o.push([r * Math.cos(ph), r * Math.sin(ph), Math.sqrt(1 - u)]); } return o; })();
function toFrame(n, d) { // d из системы с осью Z → система с осью n
  const a = Math.abs(n[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
  let tx = [a[1] * n[2] - a[2] * n[1], a[2] * n[0] - a[0] * n[2], a[0] * n[1] - a[1] * n[0]]; const l = Math.hypot(...tx); tx = tx.map((v) => v / l);
  const ty = [n[1] * tx[2] - n[2] * tx[1], n[2] * tx[0] - n[0] * tx[2], n[0] * tx[1] - n[1] * tx[0]];
  return [tx[0] * d[0] + ty[0] * d[1] + n[0] * d[2], tx[1] * d[0] + ty[1] * d[1] + n[1] * d[2], tx[2] * d[0] + ty[2] * d[1] + n[2] * d[2]];
}

// касательные для карты нормалей (как ждут glTF и Blender): T — вдоль +u, битангенс = cross(N,T)·w — «вверх по картинке» (−v)
export function computeTangents(M) {
  const { pos, nrm, uv, idx } = M, nv = pos.length / 3, tu = new Float32Array(nv * 3), tv = new Float32Array(nv * 3), out = new Float32Array(nv * 4);
  for (let i = 0; i < idx.length; i += 3) {
    const a = idx[i], b = idx[i + 1], c = idx[i + 2];
    const e1 = [pos[b * 3] - pos[a * 3], pos[b * 3 + 1] - pos[a * 3 + 1], pos[b * 3 + 2] - pos[a * 3 + 2]], e2 = [pos[c * 3] - pos[a * 3], pos[c * 3 + 1] - pos[a * 3 + 1], pos[c * 3 + 2] - pos[a * 3 + 2]];
    const du1 = uv[b * 2] - uv[a * 2], dv1 = uv[b * 2 + 1] - uv[a * 2 + 1], du2 = uv[c * 2] - uv[a * 2], dv2 = uv[c * 2 + 1] - uv[a * 2 + 1];
    const r = du1 * dv2 - du2 * dv1; if (Math.abs(r) < 1e-14) continue; const k = 1 / r;
    for (let j = 0; j < 3; j++) {
      const U = (e1[j] * dv2 - e2[j] * dv1) * k, V = (e2[j] * du1 - e1[j] * du2) * k;
      for (const v of [a, b, c]) { tu[v * 3 + j] += U; tv[v * 3 + j] += V; }
    }
  }
  for (let v = 0; v < nv; v++) {
    const n = [nrm[v * 3], nrm[v * 3 + 1], nrm[v * 3 + 2]];
    let t = [tu[v * 3], tu[v * 3 + 1], tu[v * 3 + 2]]; const d = t[0] * n[0] + t[1] * n[1] + t[2] * n[2];
    t = [t[0] - n[0] * d, t[1] - n[1] * d, t[2] - n[2] * d]; let l = Math.hypot(...t);
    if (l < 1e-9) { t = Math.abs(n[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0]; const d2 = t[0] * n[0] + t[1] * n[1] + t[2] * n[2]; t = [t[0] - n[0] * d2, t[1] - n[1] * d2, t[2] - n[2] * d2]; l = Math.hypot(...t); }
    t = t.map((x) => x / l);
    const bt = [n[1] * t[2] - n[2] * t[1], n[2] * t[0] - n[0] * t[2], n[0] * t[1] - n[1] * t[0]];
    const up = [-tv[v * 3], -tv[v * 3 + 1], -tv[v * 3 + 2]]; // «вверх по картинке» = убывание v
    out[v * 4] = t[0]; out[v * 4 + 1] = t[1]; out[v * 4 + 2] = t[2]; out[v * 4 + 3] = bt[0] * up[0] + bt[1] * up[1] + bt[2] * up[2] < 0 ? -1 : 1;
  }
  return out;
}

export const SURF_DEFAULTS = { lam: 1.0, align: 2, maxWr: 1024, minSamples: 5, specTau: 0.06, minCos: 0.4 };

// M — сетка с развёрткой {pos,nrm,uv,idx}; frames — кадры рабочего размера {w,h,rgba,K,R,t,mask?};
// faceFrame/faceChart — из bakeTexture; atlas — RGBA T×T (фото-текстура); opt: {G, turn, onProgress, tick, ...SURF_DEFAULTS}
export async function analyzeSurface(M, frames, faceFrame, faceChart, atlas, T, opt = {}) {
  const o = { ...SURF_DEFAULTS, ...opt }, prog = o.onProgress || (() => {}), tick = o.tick || (() => new Promise((r) => setTimeout(r, 0)));
  const { pos, nrm, uv, idx } = M, nt = idx.length / 3, nv = pos.length / 3, F = frames.length;
  // атлас уложен в пикселях исходного кадра (srcW); точность фотометрии — пиксель рабочего кадра → Wr = T·w/srcW
  const srcK = Math.max(1, (frames[0].srcW || frames[0].w) / frames[0].w);
  const Wr = Math.max(128, Math.min(o.maxWr, 1 << Math.round(Math.log2(T / srcK)))), NT = Wr * Wr;
  const info = {};
  // ---------- 1) растр развёртки: тексель → грань, барицентры, точка, нормаль ----------
  const tri = new Int32Array(NT).fill(-1), Xp = new Float32Array(NT * 3), N0 = new Float32Array(NT * 3), bw = new Float32Array(NT * 3);
  for (let f = 0; f < nt; f++) {
    const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2];
    const x0 = uv[a * 2] * Wr, y0 = uv[a * 2 + 1] * Wr, x1 = uv[b * 2] * Wr, y1 = uv[b * 2 + 1] * Wr, x2 = uv[c * 2] * Wr, y2 = uv[c * 2 + 1] * Wr;
    const den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2); if (Math.abs(den) < 1e-12) continue;
    const mnx = Math.max(0, Math.floor(Math.min(x0, x1, x2) - 0.5)), mxx = Math.min(Wr - 1, Math.ceil(Math.max(x0, x1, x2) + 0.5));
    const mny = Math.max(0, Math.floor(Math.min(y0, y1, y2) - 0.5)), mxy = Math.min(Wr - 1, Math.ceil(Math.max(y0, y1, y2) + 0.5));
    for (let y = mny; y <= mxy; y++) for (let x = mnx; x <= mxx; x++) {
      const px = x + 0.5, py = y + 0.5, l0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / den, l1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / den, l2 = 1 - l0 - l1;
      const e = -0.08; if (l0 < e || l1 < e || l2 < e) continue;
      const j = y * Wr + x; const inside = l0 >= 0 && l1 >= 0 && l2 >= 0; if (tri[j] >= 0 && !inside) continue;
      tri[j] = f; bw[j * 3] = l0; bw[j * 3 + 1] = l1; bw[j * 3 + 2] = l2;
    }
  }
  for (let j = 0; j < NT; j++) {
    const f = tri[j]; if (f < 0) continue;
    const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2], l0 = bw[j * 3], l1 = bw[j * 3 + 1], l2 = bw[j * 3 + 2];
    let nl = 0;
    for (let k = 0; k < 3; k++) { Xp[j * 3 + k] = l0 * pos[a * 3 + k] + l1 * pos[b * 3 + k] + l2 * pos[c * 3 + k]; N0[j * 3 + k] = l0 * nrm[a * 3 + k] + l1 * nrm[b * 3 + k] + l2 * nrm[c * 3 + k]; nl += N0[j * 3 + k] ** 2; }
    nl = Math.sqrt(nl) || 1; for (let k = 0; k < 3; k++) N0[j * 3 + k] /= nl;
  }
  if (o.debugEdges) globalThis.__Xp = Xp;
  const texels = []; for (let j = 0; j < NT; j++) if (tri[j] >= 0 && faceFrame[tri[j]] >= 0) texels.push(j);
  prog(0.05, 'развёртка');
  await tick();
  // ---------- 2) затенённость (AO) и тени — по вершинам, вокселями оболочки ----------
  const occ = occFn(o.G), vs = o.G ? o.G.vs : 1, useAO = o.ao !== false && occ, useSh = o.shadows !== false && occ;
  const aoV = new Float32Array(nv).fill(1);
  if (useAO) for (let v = 0; v < nv; v++) {
    const n = [nrm[v * 3], nrm[v * 3 + 1], nrm[v * 3 + 2]], P = [pos[v * 3] + n[0] * 1.5 * vs, pos[v * 3 + 1] + n[1] * 1.5 * vs, pos[v * 3 + 2] + n[2] * 1.5 * vs];
    let hit = 0; for (const d of HEMI) if (march(occ, P, toFrame(n, d), vs, 30)) hit++;
    aoV[v] = 1 - hit / HEMI.length;
  }
  const bary = (arrV, j) => { const f = tri[j], a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2]; return bw[j * 3] * arrV[a] + bw[j * 3 + 1] * arrV[b] + bw[j * 3 + 2] * arrV[c]; };
  const AO = new Float32Array(NT).fill(1); for (const j of texels) AO[j] = clamp(bary(aoV, j), 0, 1);
  prog(0.1, 'затенённость');
  await tick();
  // ---------- 3) кадры: глубина, центр, азимут ----------
  const fr = frames.map((f) => { const C = camC(f); return { f, C, phi: Math.atan2(C[1], C[0]), zb: depthMap(M, f, f.w, f.h) }; });
  const sampleRGB = (f, x, y, out) => {
    const w = f.w, x0 = Math.max(0, Math.min(w - 2, Math.floor(x))), y0 = Math.max(0, Math.min(f.h - 2, Math.floor(y))), fx = clamp(x - x0, 0, 1), fy = clamp(y - y0, 0, 1), i = (y0 * w + x0) * 4, s = w * 4, p = f.rgba;
    for (let c = 0; c < 3; c++) out[c] = (p[i + c] * (1 - fx) + p[i + 4 + c] * fx) * (1 - fy) + (p[i + s + c] * (1 - fx) + p[i + s + 4 + c] * fx) * fy;
    return out;
  };
  // проекция точки текселя в кадр: [u, v] или null (за кадром, заслонено, фон, под острым углом)
  const proj = (k, j) => {
    const { f, C, zb } = fr[k], R = f.R, t = f.t, K = f.K, X = Xp[j * 3], Y = Xp[j * 3 + 1], Z = Xp[j * 3 + 2];
    const cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) return null;
    const u = K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx, v = K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy;
    if (u < 3 || v < 3 || u > f.w - 4 || v > f.h - 4) return null;
    const dx = C[0] - X, dy = C[1] - Y, dz = C[2] - Z, dl = Math.hypot(dx, dy, dz);
    if ((dx * N0[j * 3] + dy * N0[j * 3 + 1] + dz * N0[j * 3 + 2]) / dl < o.minCos) return null;
    const ui = u | 0, vi = v | 0; let zm = 1e9;
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) zm = Math.min(zm, zb[(vi + b) * f.w + ui + a]);
    if (cz > zm * 1.004 + 1.5) return null;
    if (f.mask) { const m = f.mask[vi * f.w + ui]; if (m === 0 || m === 3) return null; }
    return [u, v];
  };
  // ---------- 4) уточнение совмещения: сдвиг каждого лоскута в каждом кадре (оболочка шире предмета → проекции «плывут») ----------
  const nCh = faceChart ? Math.max(0, ...faceChart) + 1 : 0, shift = new Map();
  if (o.align > 0 && nCh) {
    const byCh = Array.from({ length: nCh }, () => []);
    for (const j of texels) { const c = faceChart[tri[j]]; if (c >= 0 && byCh[c].length < 4000) byCh[c].push(j); }
    const R = o.align, rgb = [0, 0, 0];
    let tested = 0, moved = 0;
    for (let c = 0; c < nCh; c++) {
      let L = byCh[c]; if (L.length < 30) continue;
      if (L.length > 300) { const st = L.length / 300; L = Array.from({ length: 300 }, (_, i) => L[Math.floor(i * st)]); }
      const k0 = faceFrame[tri[L[0]]]; if (k0 < 0) continue;
      const ref = [], pts = [];
      for (const j of L) { const p = proj(k0, j); if (!p) continue; sampleRGB(fr[k0].f, p[0], p[1], rgb); ref.push(lum(...rgb)); pts.push(j); }
      if (pts.length < 25) continue;
      let mr = 0; for (const v of ref) mr += v; mr /= ref.length; let sr = 0; for (const v of ref) sr += (v - mr) ** 2; if (sr / ref.length < 16) continue; // гладкий лоскут — сдвиг не определить
      for (let k = 0; k < F; k++) {
        if (k === k0) continue;
        const P = [], I = []; for (let q = 0; q < pts.length; q++) { const p = proj(k, pts[q]); if (p) { P.push(p); I.push(q); } }
        if (P.length < 0.6 * pts.length) continue;
        const ncc = (dx, dy) => {
          let sa = 0, sb = 0, saa = 0, sbb = 0, sab = 0; const n = P.length;
          for (let q = 0; q < n; q++) { sampleRGB(fr[k].f, P[q][0] + dx, P[q][1] + dy, rgb); const b = lum(...rgb), a = ref[I[q]]; sa += a; sb += b; saa += a * a; sbb += b * b; sab += a * b; }
          const va = saa - sa * sa / n, vb = sbb - sb * sb / n; return va > 0 && vb > 0 ? (sab - sa * sb / n) / Math.sqrt(va * vb) : 0;
        };
        const z0 = ncc(0, 0); let best = z0, bx = 0, by = 0;
        for (let dy = -R; dy <= R; dy++) for (let dx = -R; dx <= R; dx++) { if (!dx && !dy) continue; const z = ncc(dx, dy); if (z > best) { best = z; bx = dx; by = dy; } }
        tested++;
        if (best > z0 + 0.03 && best > 0.5) { shift.set(c * 4096 + k, [bx, by]); moved++; }
      }
      if (c % 50 === 49) { prog(0.1 + 0.15 * c / nCh, 'совмещаю кадры'); await tick(); }
    }
    info.align = { tested, moved };
  }
  // ---------- 5) выборки: для каждого текселя — все кадры, где его видно ----------
  const cnt = new Uint16Array(NT), off = new Uint32Array(NT + 1);
  const pr = new Float32Array(2);
  const projS = (k, j) => { const p = proj(k, j); if (!p) return null; const s = faceChart ? shift.get(faceChart[tri[j]] * 4096 + k) : null; pr[0] = p[0] + (s ? s[0] : 0); pr[1] = p[1] + (s ? s[1] : 0); return pr; };
  for (const j of texels) { let n = 0; for (let k = 0; k < F; k++) if (proj(k, j)) n++; cnt[j] = Math.min(n, 255); }
  for (let j = 0; j < NT; j++) off[j + 1] = off[j] + cnt[j];
  const NS = off[NT], sK = new Uint8Array(NS), sC = new Uint8Array(NS * 3);
  { const rgb = [0, 0, 0];
    for (const j of texels) { let q = off[j]; const e = off[j + 1]; for (let k = 0; k < F && q < e; k++) { const p = projS(k, j); if (!p) continue; sampleRGB(fr[k].f, p[0], p[1], rgb); sK[q] = k; sC[q * 3] = rgb[0]; sC[q * 3 + 1] = rgb[1]; sC[q * 3 + 2] = rgb[2]; q++; } } }
  info.samples = NS; info.texels = texels.length;
  prog(0.35, `выборок ${NS}`);
  await tick();
  // ---------- 6) свет: подгонка (рассеянный a, лампа l0, усиление кадров g) ----------
  const sub = texels.filter((_, i) => i % 5 === 0 && true).filter((j) => cnt[j] >= 3);
  const nrmAt = (j) => [N0[j * 3], N0[j * 3 + 1], N0[j * 3 + 2]];
  const lightK = (l0, m) => fr.map((q) => rotZ(l0, m * q.phi));
  // тени по вершинам для набора направлений света → видимость по текселю
  const shadowFor = (Lk) => {
    if (!useSh) return null;
    const vis = new Uint8Array(nv * F);
    const uniq = new Map();
    for (let k = 0; k < F; k++) { const L = Lk[k], key = L.map((x) => x.toFixed(3)).join(','); if (uniq.has(key)) { vis.copyWithin(k * nv, uniq.get(key) * nv, uniq.get(key) * nv + nv); continue; } uniq.set(key, k);
      const ll = Math.hypot(...L), d = L.map((x) => x / ll);
      for (let v = 0; v < nv; v++) {
        const n = [nrm[v * 3], nrm[v * 3 + 1], nrm[v * 3 + 2]];
        if (d[2] < -0.05 || n[0] * d[0] + n[1] * d[1] + n[2] * d[2] < -0.1) { vis[k * nv + v] = 0; continue; }
        const P = [pos[v * 3] + n[0] * 1.5 * vs, pos[v * 3 + 1] + n[1] * 1.5 * vs, pos[v * 3 + 2] + n[2] * 1.5 * vs];
        vis[k * nv + v] = march(occ, P, d, vs, 150) ? 0 : 255;
      }
    }
    return vis;
  };
  const visAt = (vis, k, j) => { if (!vis) return 1; const f = tri[j], a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2], base = k * nv; return (bw[j * 3] * vis[base + a] + bw[j * 3 + 1] * vis[base + b] + bw[j * 3 + 2] * vis[base + c]) / 255; };
  const fitLight = (m, l0init, iters, vis, set) => {
    let l0 = [...l0init], a = 0.35; const g = new Float64Array(F).fill(1), rho = new Float64Array(NT);
    let err = Infinity;
    for (let it = 0; it < iters; it++) {
      const Lk = lightK(l0, m);
      const shade = (j, k) => { const n = nrmAt(j), L = Lk[k]; return a * AO[j] + visAt(vis, k, j) * Math.max(0, n[0] * L[0] + n[1] * L[1] + n[2] * L[2]); };
      // альбедо (яркость) по текселю
      for (const j of set) { let su = 0, ss = 0; for (let q = off[j]; q < off[j + 1]; q++) { const k = sK[q], s = g[k] * shade(j, k), I = lum(sC[q * 3], sC[q * 3 + 1], sC[q * 3 + 2]); if (I > 250) continue; su += I * s; ss += s * s; } rho[j] = ss > 0 ? su / ss : 0; }
      // остатки → порог для выбросов (блики, промахи совмещения)
      const res = []; for (let i = 0; i < set.length; i += 3) { const j = set[i]; for (let q = off[j]; q < off[j + 1]; q++) { const k = sK[q]; res.push(Math.abs(lum(sC[q * 3], sC[q * 3 + 1], sC[q * 3 + 2]) - g[k] * rho[j] * shade(j, k))); } }
      res.sort((x, y) => x - y); const med = res[res.length >> 1] || 1, thr = 3 * med + 2;
      err = 0; for (const r of res) err += Math.min(r, thr) ** 2; err /= Math.max(1, res.length);
      // a и l0: линейная задача [AO, vis·Rᵀn]·[a, l] = I/(gρ)
      const A = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], B = [0, 0, 0, 0];
      for (const j of set) {
        if (rho[j] < 8) continue; const n = nrmAt(j);
        for (let q = off[j]; q < off[j + 1]; q++) {
          const k = sK[q], I = lum(sC[q * 3], sC[q * 3 + 1], sC[q * 3 + 2]); if (I > 250) continue;
          const gr = g[k] * rho[j]; if (Math.abs(I - gr * shade(j, k)) > thr) continue;
          const L = Lk[k], lit = n[0] * L[0] + n[1] * L[1] + n[2] * L[2] > 0, vv = lit ? visAt(vis, k, j) : 0, rn = rotZ(n, -m * fr[k].phi);
          const row = [AO[j], vv * rn[0], vv * rn[1], vv * rn[2]], y = I / gr, w = gr * gr;
          for (let r = 0; r < 4; r++) { B[r] += w * row[r] * y; for (let c = 0; c < 4; c++) A[r][c] += w * row[r] * row[c]; }
        }
      }
      for (let r = 0; r < 4; r++) A[r][r] += 1e-6 * (A[r][r] + 1);
      const x = solveN(A, B, 4);
      if (x) { a = Math.max(0.02, x[0]); l0 = [x[1], x[2], x[3]]; const s = a + Math.hypot(...l0); a /= s; l0 = l0.map((v) => v / s); }
      // усиления кадров (автоэкспозиция) — слабо, со сжатием к 1
      if (o.gains !== false && it >= 2) {
        const Lk2 = lightK(l0, m), su = new Float64Array(F), ss = new Float64Array(F);
        for (const j of set) { const n = nrmAt(j); for (let q = off[j]; q < off[j + 1]; q++) { const k = sK[q], L = Lk2[k], p = rho[j] * (a * AO[j] + visAt(vis, k, j) * Math.max(0, n[0] * L[0] + n[1] * L[1] + n[2] * L[2])), I = lum(sC[q * 3], sC[q * 3 + 1], sC[q * 3 + 2]); if (I > 250) continue; su[k] += I * p; ss[k] += p * p; } }
        let lg = 0, nk = 0; for (let k = 0; k < F; k++) if (ss[k] > 0) { g[k] = clamp(su[k] / ss[k], 0.6, 1.6); lg += Math.log(g[k]); nk++; }
        lg = nk ? lg / nk : 0; for (let k = 0; k < F; k++) g[k] = ss[k] > 0 ? Math.exp(0.85 * (Math.log(g[k]) - lg)) : 1;
      }
    }
    return { l0, a, g, err, m };
  };
  // начальные направления: 6 азимутов на высоте 45° — и поворот лампы с камерой (m=1) или без (m=0)
  // модель света нужна только опытным режимам (рельеф по свету, текстура по модели) — по умолчанию не считаем (быстрее)
  const needLight = o.relief === 'photo' || o.delight === 'model' || o.fitLight;
  let LF = { a: 0.35, l0: [0, 0, 0.65], g: new Float64Array(F).fill(1), m: o.turn === false ? 0 : 1, err: 0 }, vis = null;
  if (!needLight && o.gains !== false) {
    // усиление кадров (автоэкспозиция) без модели света: медиана отношений «выборка / медиана точки по кадрам»
    const R = Array.from({ length: F }, () => []);
    for (let i = 0; i < texels.length; i += 3) { const j = texels[i], s0 = off[j], e = off[j + 1]; if (e - s0 < 5) continue;
      const v = []; for (let q = s0; q < e; q++) v.push(lum(sC[q * 3], sC[q * 3 + 1], sC[q * 3 + 2])); const sv = [...v].sort((a, b) => a - b), md = sv[sv.length >> 1]; if (md < 15) continue;
      for (let q = s0; q < e; q++) if (R[sK[q]].length < 4000) R[sK[q]].push(v[q - s0] / md); }
    let lg = 0, nk = 0; for (let k = 0; k < F; k++) { const r = R[k]; if (r.length < 50) continue; r.sort((a, b) => a - b); LF.g[k] = clamp(r[r.length >> 1], 0.6, 1.6); lg += Math.log(LF.g[k]); nk++; }
    lg = nk ? lg / nk : 0; for (let k = 0; k < F; k++) LF.g[k] = R[k].length >= 50 ? Math.exp(Math.log(LF.g[k]) - lg) : 1;
  }
  if (needLight) {
  const small = sub.filter((_, i) => i % 4 === 0);
  let best = null;
  for (const m of [0, 1]) for (let i = 0; i < 6; i++) {
    const az = i * Math.PI / 3, l = [0.45 * Math.cos(az), 0.45 * Math.sin(az), 0.45];
    const r = fitLight(m, l, 6, null, small);
    if (!best || r.err < best.err * (o.turn !== undefined && (m === 1) !== !!o.turn ? 0.97 : 1)) best = r;
  }
  info.lightPick = best.m;
  LF = fitLight(best.m, best.l0, 6, null, sub);
  vis = shadowFor(lightK(LF.l0, LF.m));
  if (vis) LF = fitLight(LF.m, LF.l0, 5, vis, sub), vis = shadowFor(lightK(LF.l0, LF.m));
  if (o.forceLight) { LF.a = o.forceLight.a; LF.l0 = o.forceLight.l0; LF.m = o.forceLight.m; LF.g = LF.g.map(() => 1); }
  }
  const { a: amb, g: gain, m: lm } = LF, l0 = LF.l0, Lk = lightK(l0, lm);
  if (needLight) info.light = { dir: l0.map((v) => +(v / Math.hypot(...l0)).toFixed(3)), direct: +Math.hypot(...l0).toFixed(3), ambient: +amb.toFixed(3), rotates: lm === 1, err: +Math.sqrt(LF.err).toFixed(2) };
  prog(0.5, 'свет найден');
  await tick();
  if (o.debug) o.debug({ off, sK, sC, Lk, gain, amb, AO, vis, visAt, fr, Xp, N0, tri, texels, Wr });
  // ---------- 7) нормали и альбедо по текселю ----------
  const Nw = new Float32Array(N0), rhoC = new Float32Array(NT * 3), conf = new Float32Array(NT);
  // разброс направлений света в точке: на вертушке горизонтальная часть l поворачивается вместе с камерой
  const photometric = lm === 1;
  // ---------- 9б) «обычный вид»: по каждой точке — медиана яркости по кадрам (блики в 1–3 кадрах и глубокие тени
  // отбрасываются) → яркость без случайностей одного кадра, без модели света
  const rhoV = new Float32Array(NT * 3);
  for (const j of texels) {
    const s0 = off[j], e = off[j + 1]; if (e - s0 < 1) continue;
    const L = []; for (let q = s0; q < e; q++) L.push([lum(sC[q * 3], sC[q * 3 + 1], sC[q * 3 + 2]) / gain[sK[q]], q]);
    L.sort((a, b) => a[0] - b[0]);
    // среднее по окну 60–85% (устойчивее одного значения)
    const a0 = Math.floor((L.length - 1) * (o.viewLo ?? 0.35)), a1 = Math.max(a0, Math.ceil((L.length - 1) * (o.viewHi ?? 0.65)));
    let n = 0; for (let i = a0; i <= a1; i++) { const q = L[i][1], g = gain[sK[q]]; for (let c = 0; c < 3; c++) rhoV[j * 3 + c] += sC[q * 3 + c] / g; n++; }
    for (let c = 0; c < 3; c++) rhoV[j * 3 + c] /= n;
  }
  // касательный базис по нормали сетки: t1 — горизонтальный, t2 — «вверх» (для верха/низа — произвольный)
  const T1 = new Float32Array(NT * 3), T2 = new Float32Array(NT * 3);
  for (const j of texels) {
    const n0 = nrmAt(j), a = Math.abs(n0[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
    let t1 = [a[1] * n0[2] - a[2] * n0[1], a[2] * n0[0] - a[0] * n0[2], a[0] * n0[1] - a[1] * n0[0]]; const l = Math.hypot(...t1); t1 = t1.map((v) => v / l);
    const t2 = [n0[1] * t1[2] - n0[2] * t1[1], n0[2] * t1[0] - n0[0] * t1[2], n0[0] * t1[1] - n0[1] * t1[0]];
    for (let c = 0; c < 3; c++) { T1[j * 3 + c] = t1[c]; T2[j * 3 + c] = t2[c]; }
  }
  const tiltN = (j, p, q) => { const n = [0, 0, 0]; for (let c = 0; c < 3; c++) n[c] = N0[j * 3 + c] + p * T1[j * 3 + c] + q * T2[j * 3 + c]; const l = Math.hypot(...n); return n.map((v) => v / l); };
  const shadeAt = (j, k, nn) => { const L = Lk[k]; return amb * AO[j] + visAt(vis, k, j) * Math.max(0, nn[0] * L[0] + nn[1] * L[1] + nn[2] * L[2]); };
  const albedoAt = (j, nn, outRGB) => { const su = [0, 0, 0]; let ss = 0; for (let q = off[j]; q < off[j + 1]; q++) { const k = sK[q], sh = gain[k] * shadeAt(j, k, nn); if (lum(sC[q * 3], sC[q * 3 + 1], sC[q * 3 + 2]) > 250) continue; for (let c = 0; c < 3; c++) su[c] += sC[q * 3 + c] * sh; ss += sh * sh; } for (let c = 0; c < 3; c++) outRGB[c] = ss > 0 ? su[c] / ss : 0; return ss; };
  // 7а) по каждой точке: наклоны (p, q) и их достоверность. Модель I = g·(ρ·shade(n) + c): смещение c поглощает
  // ошибку рассеянного света и затенённости — тогда наклон «вверх-вниз» (на вертушке он почти не меняет яркость
  // по кадрам) честно получает малый вес, и его восстанавливает уже общее поле высот (из уклонов вбок).
  const Pm = new Float32Array(NT), Qm = new Float32Array(NT), Iaa = new Float32Array(NT), Iab = new Float32Array(NT), Ibb = new Float32Array(NT);
  // шаг Гаусса — Ньютона по каждой точке от текущих наклонов (Pc, Qc): измерение (Pm, Qm) и его информация
  const measure = (Pc, Qc, inner) => { for (const j of texels) {
    Pm[j] = Pc[j]; Qm[j] = Qc[j]; Iaa[j] = Ibb[j] = Iab[j] = 0;
    const s0 = off[j], e = off[j + 1]; if (e - s0 < o.minSamples) continue;
    let p = Pc[j], q = Qc[j], used = 0, S = null; const rgb = [0, 0, 0];
    for (let it = 0; it < inner; it++) {
      const n = tiltN(j, p, q); albedoAt(j, n, rgb); const rho = lum(...rgb); if (rho < 6) { S = null; break; }
      const rs = []; for (let qq = s0; qq < e; qq++) { const k = sK[qq]; rs.push(Math.abs(lum(sC[qq * 3], sC[qq * 3 + 1], sC[qq * 3 + 2]) / gain[k] - rho * shadeAt(j, k, n))); }
      const srt = [...rs].sort((x, y) => x - y), sig = Math.max(2, 1.25 * srt[srt.length >> 1]), thr = Math.max(3 * sig, 0.04 * rho + 3);
      // неизвестные: ρ, c, u = ρ·Δp, w = ρ·Δq (линейно)
      const A = new Float64Array(16), B = new Float64Array(4); used = 0;
      const t1 = [T1[j * 3], T1[j * 3 + 1], T1[j * 3 + 2]], t2 = [T2[j * 3], T2[j * 3 + 1], T2[j * 3 + 2]];
      for (let qq = s0, i = 0; qq < e; qq++, i++) {
        if (rs[i] > thr) continue; const k = sK[qq], I = lum(sC[qq * 3], sC[qq * 3 + 1], sC[qq * 3 + 2]); if (I > 250) continue;
        const L = Lk[k], vv = visAt(vis, k, j), nl = n[0] * L[0] + n[1] * L[1] + n[2] * L[2], lit = nl > 0.03 && vv > 0.5;
        const row = [shadeAt(j, k, n), 1, lit ? vv * (t1[0] * L[0] + t1[1] * L[1] + t1[2] * L[2]) : 0, lit ? vv * (t2[0] * L[0] + t2[1] * L[1] + t2[2] * L[2]) : 0], y = I / gain[k];
        for (let r = 0; r < 4; r++) { B[r] += row[r] * y; for (let c = 0; c < 4; c++) A[r * 4 + c] += row[r] * row[c]; }
        used++;
      }
      if (used < o.minSamples) { S = null; break; }
      // априорно: смещение мало (|c| ≲ 4% ρ), наклон ≲ 0.5 рад (мягко)
      const cw = 1 / ((o.cPrior ?? 0.15) * rho) ** 2 * sig * sig; A[5] += cw;
      const pw = (sig / (0.5 * rho)) ** 2; A[10] += pw; A[15] += pw;
      const x = solveN([0, 1, 2, 3].map((r) => [A[r * 4], A[r * 4 + 1], A[r * 4 + 2], A[r * 4 + 3]]), [...B], 4); if (!x || x[0] < 3) { S = null; break; }
      const dp = x[2] / x[0], dq = x[3] / x[0], p1 = clamp(p + dp, -1.2, 1.2), q1 = clamp(q + dq, -1.2, 1.2);
      // информация о (p, q) после исключения ρ и c (дополнение Шура), в единицах 1/рад²
      const a00 = A[0], a01 = A[1], a11 = A[5] - cw, M2 = [[A[10] - pw, A[11]], [A[14], A[15] - pw]];
      const C2 = [[A[2], A[3]], [A[6], A[7]]]; // строки ρ, c × столбцы p, q
      const a11c = a11 + cw, det = a00 * a11c - a01 * a01;
      if (det <= 0) { S = null; break; }
      const inv = [[a11c / det, -a01 / det], [-a01 / det, a00 / det]];
      const sch = [[0, 0], [0, 0]];
      for (let r = 0; r < 2; r++) for (let c = 0; c < 2; c++) { let v = M2[r][c]; for (let a = 0; a < 2; a++) for (let b = 0; b < 2; b++) v -= C2[a][r] * inv[a][b] * C2[b][c]; sch[r][c] = v * x[0] * x[0] / (sig * sig); }
      S = sch; p = p1; q = q1;
    }
    if (!S) continue;
    Pm[j] = p; Qm[j] = q; Iaa[j] = Math.max(0, S[0][0]); Iab[j] = S[0][1]; Ibb[j] = Math.max(0, S[1][1]); conf[j] = Math.min(1, used / 10);
  } };
  // 7б) общее поле высот h (мм от поверхности сетки) по графу соседних точек в пространстве (без учёта лоскутов —
  // рельеф непрерывен через швы): Σ w·(h_j − h_i − ∇h·d)² + ν·(h_j − h_i)²/|d|²·… + μ·h²
  let Hh = null, texMM = 0.3;
  { const sz = []; for (let i = 0; i < texels.length; i += 7) { const t = tangentAt(texels[i]); if (t) sz.push(Math.sqrt(t[2] * t[3])); }
    sz.sort((a, b) => a - b); texMM = sz.length ? sz[sz.length >> 1] : 0.3; }
  const graph = buildGraph({ texels, Xp, N0, texMM });
  // режим рельефа: 'texture' (по умолчанию) — по мелкой светотени фото-текстуры, как в программах «нормаль из фото»;
  // 'photo' — фотометрия по кадрам вертушки (опыт: нужна точная форма, по силуэтам ненадёжно); 'none' — без рельефа
  const reliefMode = o.relief ?? 'texture';
  info.relief = { mode: reliefMode === 'photo' && !photometric ? 'texture' : reliefMode };
  if (reliefMode === 'photo' && photometric) {
    // внешние проходы: точка линеаризуется у нормали из общего поля высот (совместный Гаусс — Ньютон)
    const Pc = new Float32Array(NT), Qc = new Float32Array(NT); let RS = null, ne = 0;
    const rounds = o.reliefRounds ?? 3;
    for (let round = 0; round < rounds; round++) {
      measure(Pc, Qc, round === 0 ? (o.firstInner ?? 1) : 1);
      if (o.debugPQ) for (const j of texels) { const r = o.debugPQ(j, Xp, N0, T1, T2); if (r) { Pm[j] = r[0]; Qm[j] = r[1]; if (!o.keepInfo) { Iaa[j] = Ibb[j] = 1000; Iab[j] = 0; } } }
      if (o.horizOnly ?? true) for (const j of texels) { Ibb[j] = 0; Iab[j] = 0; }
      RS = await solveRelief({ texels, Xp, N0, T1, T2, Pm, Qm, Iaa, Iab, Ibb, NT, texMM, o, tick, tiltN, graph }); ne = RS.ne;
      for (const j of texels) { const N = [RS.N[j * 3], RS.N[j * 3 + 1], RS.N[j * 3 + 2]], dn = N[0] * N0[j * 3] + N[1] * N0[j * 3 + 1] + N[2] * N0[j * 3 + 2]; if (dn < 0.3) continue;
        Pc[j] = (N[0] * T1[j * 3] + N[1] * T1[j * 3 + 1] + N[2] * T1[j * 3 + 2]) / dn; Qc[j] = (N[0] * T2[j * 3] + N[1] * T2[j * 3 + 1] + N[2] * T2[j * 3 + 2]) / dn; }
      prog(0.5 + 0.15 * (round + 1) / rounds, 'рельеф по свету'); await tick();
    }
    Hh = RS.h; for (const j of texels) { Nw[j * 3] = RS.N[j * 3]; Nw[j * 3 + 1] = RS.N[j * 3 + 1]; Nw[j * 3 + 2] = RS.N[j * 3 + 2]; }
    info.relief.edges = ne;
  } else if (reliefMode !== 'none') {
    // яркость фото-текстуры на сетке Wr → высокие частоты (тёмное — углубление) → высота; уклоны нормируем:
    // 95% самых крутых мест ≈ reliefSlope (рад) — сила рельефа одинакова для любого предмета
    // яркость — медиана по кадрам (не фото-текстура: лоскуты из разных кадров со своей светотенью дали бы ступеньки на швах)
    const Y = new Float32Array(NT);
    for (const j of texels) Y[j] = Math.log(8 + lum(rhoV[j * 3], rhoV[j * 3 + 1], rhoV[j * 3 + 2]));
    const Ys = graphSmooth(graph, Y, texels, o.reliefIt ?? 30), h = new Float32Array(NT);
    for (const j of texels) h[j] = Y[j] - Ys[j];
    const gs = []; for (let e = 0; e < graph.EI.length; e += 3) { const i = graph.EI[e], j = graph.EJ[e]; gs.push(Math.abs(h[j] - h[i]) / Math.max(0.3 * texMM, Math.hypot(Xp[j * 3] - Xp[i * 3], Xp[j * 3 + 1] - Xp[i * 3 + 1], Xp[j * 3 + 2] - Xp[i * 3 + 2]))); }
    gs.sort((a, b) => a - b); const g95 = gs.length ? gs[Math.floor(gs.length * 0.95)] : 0;
    const k = g95 > 1e-6 ? (o.reliefSlope ?? 0.25) / g95 : 0; for (const j of texels) h[j] *= k;
    const RS = await solveRelief({ texels, Xp, N0, T1, T2, Pm, Qm, Iaa, Iab, Ibb, NT, texMM, o, tick, tiltN, hIn: h, graph });
    Hh = RS.h; for (const j of texels) { Nw[j * 3] = RS.N[j * 3]; Nw[j * 3 + 1] = RS.N[j * 3 + 1]; Nw[j * 3 + 2] = RS.N[j * 3 + 2]; }
    info.relief.edges = RS.ne; info.reliefApprox = true;
  }
  info.relief.texMM = +texMM.toFixed(3);
  for (const j of texels) { const n = [Nw[j * 3], Nw[j * 3 + 1], Nw[j * 3 + 2]], rgb = [0, 0, 0]; albedoAt(j, n, rgb); rhoC[j * 3] = rgb[0]; rhoC[j * 3 + 1] = rgb[1]; rhoC[j * 3 + 2] = rgb[2]; }
  prog(0.65, 'рельеф');
  await tick();
  // касательный базис текселя: T (вдоль +u), Bup (вверх по картинке = −v) — по грани
  function tangentAt(j) {
    const f = tri[j]; if (f < 0) return null; const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2];
    const e1 = [0, 1, 2].map((k) => pos[b * 3 + k] - pos[a * 3 + k]), e2 = [0, 1, 2].map((k) => pos[c * 3 + k] - pos[a * 3 + k]);
    const du1 = uv[b * 2] - uv[a * 2], dv1 = uv[b * 2 + 1] - uv[a * 2 + 1], du2 = uv[c * 2] - uv[a * 2], dv2 = uv[c * 2 + 1] - uv[a * 2 + 1];
    const r = du1 * dv2 - du2 * dv1; if (Math.abs(r) < 1e-14) return null;
    const U = [0, 1, 2].map((k) => (e1[k] * dv2 - e2[k] * dv1) / r), V = [0, 1, 2].map((k) => (e2[k] * du1 - e1[k] * du2) / r);
    return [U, V.map((x) => -x), Math.hypot(...U) / Wr, Math.hypot(...V) / Wr]; // + мм на тексель по u и v
  }
  // ---------- 8) материалы: зоны одного цвета, всплески бликов по кадрам ----------
  const lab = new Int8Array(NT).fill(-1), mats = clusterAlbedo(graphSmooth(graph, rhoV, texels, 3, 3), texels, 5);
  for (const j of texels) lab[j] = mats.label(j);
  // блик — короткий всплеск яркости точки на 1–4 кадра поверх плавной кривой освещения (лампа поворачивается
  // медленно — диффузная яркость меняется плавно): кривая = скользящая медиана по соседним кадрам.
  // Нормали не нужны — работает и при неточной форме. По зоне: доля точек со всплесками → глянец, ширина → шероховатость,
  // цвет всплеска как у поверхности при тёмном диффузном → металл.
  const specMax = new Float32Array(NT);
  // точка у края силуэта/заслонения в этом кадре (рядом в карте глубины скачок: фон, дальняя или ближняя часть):
  // при неточной позе туда попадает цвет коврика или другой части предмета — такой всплеск не блик
  const edgeR = o.edgePx ?? 3, ring = [[1, 0], [-1, 0], [0, 1], [0, -1], [0.7, 0.7], [-0.7, 0.7], [0.7, -0.7], [-0.7, -0.7]];
  const nearEdge = (k, j) => {
    const { f, zb } = fr[k], R = f.R, t = f.t, K = f.K, X = Xp[j * 3], Y = Xp[j * 3 + 1], Z = Xp[j * 3 + 2];
    const cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) return true;
    const u = K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx, v = K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy;
    for (const [a, b] of ring) { const uu = Math.round(u + a * edgeR), vv = Math.round(v + b * edgeR); if (uu < 0 || vv < 0 || uu >= f.w || vv >= f.h) return true; if (Math.abs(zb[vv * f.w + uu] - cz) > cz * 0.03 + 4) return true; }
    return false;
  };
  // самый светлый цвет поверхности рядом (радиус ≈ промах совмещения кадров): всплеск ниже него — это соседняя
  // светлая клетка/полоса, попавшая в точку из-за неточной позы, а не блик (шахматка, надписи)
  const lumV = new Float32Array(NT); for (const j of texels) lumV[j] = lum(rhoV[j * 3], rhoV[j * 3 + 1], rhoV[j * 3 + 2]);
  const nbrMax = graphMax(graph, lumV, texels, o.misregTx ?? 6);
  const st = mats.centers.map(() => ({ n: 0, sp: 0, rel: [], wid: 0, sc: [0, 0, 0], scn: 0, rho: [0, 0, 0] }));
  for (const j of texels) {
    const cl = lab[j]; if (cl < 0) continue; const s0 = off[j], e = off[j + 1], m = e - s0; if (m < 7) continue;
    const Z = st[cl]; Z.n++;
    const y = new Float32Array(m); for (let i = 0; i < m; i++) { const q = s0 + i; y[i] = lum(sC[q * 3], sC[q * 3 + 1], sC[q * 3 + 2]) / gain[sK[q]]; }
    let best = 0, bi = -1, cntS = 0; const sc = [0, 0, 0];
    for (let i = 0; i < m; i++) {
      // фон — бо́льшая из медиан слева и справа: ступенька (выход из тени) не всплеск
      const wl = [], wr = []; for (let d = 1; d <= 4; d++) { if (i - d >= 0) wl.push(y[i - d]); if (i + d < m) wr.push(y[i + d]); }
      if (wl.length < 2 || wr.length < 2) continue;
      wl.sort((a, b) => a - b); wr.sort((a, b) => a - b);
      const base = Math.max(wl[wl.length >> 1], wr[wr.length >> 1]), ex = y[i] - base;
      if (ex > (o.spikeK ?? 0.5) * base + 8) {
        // цвет прибавки: белый (блик пластика) или цвет самой поверхности (металл); иное — промах совмещения (соседний цвет)
        const q = s0 + i, g = gain[sK[q]], lv = Math.max(1, lum(rhoV[j * 3], rhoV[j * 3 + 1], rhoV[j * 3 + 2])), e3 = [0, 1, 2].map((c) => sC[q * 3 + c] / g - rhoV[j * 3 + c] * base / lv);
        const el = Math.hypot(...e3) || 1, cw = (e3[0] + e3[1] + e3[2]) / (Math.sqrt(3) * el), rl = Math.hypot(rhoV[j * 3], rhoV[j * 3 + 1], rhoV[j * 3 + 2]) || 1, co = (e3[0] * rhoV[j * 3] + e3[1] * rhoV[j * 3 + 1] + e3[2] * rhoV[j * 3 + 2]) / (el * rl);
        if (Math.max(cw, co) < 0.93) continue;
        if (nearEdge(sK[q], j)) continue;
        // белёсый всплеск ниже светлого соседа — промах совмещения; всплеск цвета самой поверхности (металл) соседом не объяснить
        if (!(co > 0.93 && co > cw + 0.02) && y[i] <= (o.spikeN ?? 1.2) * base * clamp(nbrMax[j] / Math.max(1, lumV[j]), 1, o.spikeCap ?? 2.5) + 8) continue;
        cntS++; for (let c = 0; c < 3; c++) sc[c] += e3[c]; if (ex / Math.max(8, base) > best) { best = ex / Math.max(8, base); bi = i; } }
    }
    if (cntS && cntS <= Math.max(2, 0.35 * m)) { Z.sp++; Z.rel.push(best); Z.wid += cntS; for (let c = 0; c < 3; c++) Z.sc[c] += sc[c]; Z.scn += cntS; if (sK[s0 + bi] === faceFrame[tri[j]]) specMax[j] = best; }
    for (let c = 0; c < 3; c++) Z.rho[c] += rhoV[j * 3 + c];
  }
  const matInfo = st.map((Z, i) => {
    const frac = Z.n ? Z.sp / Z.n : 0; Z.rel.sort((a, b) => a - b); const rel = Z.rel.length ? Z.rel[Z.rel.length >> 1] : 0, wid = Z.sp ? Z.wid / Z.sp : 0;
    const glossy = Z.n >= 30 && frac > (o.glossFrac ?? 0.055) && rel > 0.35;
    const scm = (Z.sc[0] + Z.sc[1] + Z.sc[2]) / 3, tint = Z.scn && scm > 2 ? Z.sc.map((v) => v / scm) : [1, 1, 1];
    const rm = Z.n ? Z.rho.map((v) => v / Z.n) : [128, 128, 128], rmm = (rm[0] + rm[1] + rm[2]) / 3 || 1, ctint = rm.map((v) => v / rmm);
    const tinted = Math.max(...tint.map((v) => Math.abs(v - 1))) > 0.2 && tint.reduce((s_, v, c) => s_ + (v - 1) * (ctint[c] - 1), 0) > 0.03;
    const metal = glossy && tinted && rel > 1.2 ? 1 : 0;
    // ширина всплеска (кадров, шаг ~5°) → шероховатость: 1–2 кадра — гладкий глянец, 4+ — полуматовый
    const rough = glossy ? clamp(0.35 + 0.1 * (wid - 1), 0.35, 0.7) : 0.9; // авто — осторожный полуглянец: ложный глянец не должен искриться (точный «Глянец» — кнопкой)
    const cc = mats.centers[i];
    return { color: cc.map((v) => Math.round(v)), share: mats.share[i], gloss: +frac.toFixed(2), peak: +rel.toFixed(2), width: +wid.toFixed(1), rough: +rough.toFixed(2), metal, tint: tint.map((v) => +v.toFixed(2)) };
  });
  info.materials = matInfo;
  prog(0.75, 'материалы');
  await tick();
  // ---------- 9) карты Wr×Wr: нормали (касательные), ORM, высота ----------
  const nmap = new Uint8Array(NT * 4), orm = new Uint8Array(NT * 4), hmap = new Uint8Array(NT * 4);
  const gx = new Float32Array(NT), gy = new Float32Array(NT), has = new Uint8Array(NT);
  for (const j of texels) {
    const t = tangentAt(j); const n = [Nw[j * 3], Nw[j * 3 + 1], Nw[j * 3 + 2]], n0 = nrmAt(j);
    let tx = [1, 0, 0], ty = [0, 1, 0];
    if (t) {
      // ортонормированный базис вокруг нормали сетки (как в шейдере: T, B = cross(N,T)·w)
      let T0 = t[0]; const d = T0[0] * n0[0] + T0[1] * n0[1] + T0[2] * n0[2]; T0 = [T0[0] - n0[0] * d, T0[1] - n0[1] * d, T0[2] - n0[2] * d]; const l = Math.hypot(...T0) || 1; tx = T0.map((v) => v / l);
      const bt = [n0[1] * tx[2] - n0[2] * tx[1], n0[2] * tx[0] - n0[0] * tx[2], n0[0] * tx[1] - n0[1] * tx[0]], w = bt[0] * t[1][0] + bt[1] * t[1][1] + bt[2] * t[1][2] < 0 ? -1 : 1; ty = bt.map((v) => v * w);
    }
    const x = n[0] * tx[0] + n[1] * tx[1] + n[2] * tx[2], y = n[0] * ty[0] + n[1] * ty[1] + n[2] * ty[2], z = Math.max(0.2, n[0] * n0[0] + n[1] * n0[1] + n[2] * n0[2]);
    const l = Math.hypot(x, y, z);
    nmap[j * 4] = Math.round((x / l * 0.5 + 0.5) * 255); nmap[j * 4 + 1] = Math.round((y / l * 0.5 + 0.5) * 255); nmap[j * 4 + 2] = Math.round((z / l * 0.5 + 0.5) * 255); nmap[j * 4 + 3] = 255;
    // уклоны высоты (мм на мм) → на тексель: dh/du = −x/z·(мм на тексель по u), dh/dv = +y/z·(мм по v)
    if (t) { gx[j] = -x / z * t[2]; gy[j] = y / z * t[3]; has[j] = 1; }
    const mi = lab[j] >= 0 ? matInfo[lab[j]] : { rough: 0.9, metal: 0 };
    orm[j * 4] = Math.round(255 * clamp(0.35 + 0.65 * AO[j], 0, 1)); orm[j * 4 + 1] = Math.round(255 * mi.rough); orm[j * 4 + 2] = Math.round(255 * mi.metal); orm[j * 4 + 3] = 255;
  }
  const height = Hh || integrateHeight(gx, gy, has, Wr, faceChart ? (j) => faceChart[tri[j]] : null, tri);
  // только рельеф: убираем плавную составляющую (её несёт сама сетка)
  const hs = graphSmooth(graph, height, texels, 60);
  const hh = new Float32Array(NT); const absv = [];
  for (const j of texels) { hh[j] = height[j] - hs[j]; absv.push(Math.abs(hh[j])); }
  absv.sort((x, y) => x - y); const hmax = Math.max(0.05, absv[Math.floor(absv.length * 0.995)] || 0.05);
  for (const j of texels) { const v = Math.round(128 + 127 * clamp(hh[j] / hmax, -1, 1)); hmap[j * 4] = hmap[j * 4 + 1] = hmap[j * 4 + 2] = v; hmap[j * 4 + 3] = 255; }
  info.heightRange = +hmax.toFixed(3); // мм: 0 и 255 в карте высот — ∓ это значение, 128 — поверхность сетки
  for (const m of [nmap, orm, hmap]) dilate(m, tri, Wr, 4, m === nmap ? [128, 128, 255] : m === hmap ? [128, 128, 128] : [255, 230, 0]);
  prog(0.85, 'карты');
  await tick();
  // ---------- 10) альбедо T×T: фото-текстура / освещение в её кадре; блики → цвет по всем кадрам ----------
  const alb = new Uint8Array(T * T * 4), sc = T / Wr;
  const nW = (x, y) => { const j = Math.min(Wr - 1, (y / sc) | 0) * Wr + Math.min(Wr - 1, (x / sc) | 0); return j; };
  // по умолчанию — по «обычному виду»: чёткая фото-текстура × сглаженное отношение (медиана / фото) — убирает тени
  // и блики кадра лоскута, не размывая рисунок
  if ((o.delight ?? 'views') === 'views') {
    const ph = new Float32Array(NT), cntW = new Float32Array(NT);
    for (let y = 0; y < T; y++) for (let x = 0; x < T; x++) { const j = nW(x, y), i = (y * T + x) * 4; if (tri[j] < 0) continue; ph[j] += lum(atlas[i], atlas[i + 1], atlas[i + 2]); cntW[j]++; }
    const lr = new Float32Array(NT), wHi = new Float32Array(NT);
    for (const j of texels) { if (!cntW[j]) continue; ph[j] /= cntW[j]; const v = lum(rhoV[j * 3], rhoV[j * 3 + 1], rhoV[j * 3 + 2]); if (v <= 0) continue;
      lr[j] = Math.log((v + 4) / (ph[j] + 4)); wHi[j] = clamp((ph[j] / Math.max(4, v) - 1.15) / 0.25, 0, 1); }
    const lrs = blurMasked(lr, tri, Wr, o.delightR ?? 4, faceChart);
    for (let y = 0; y < T; y++) for (let x = 0; x < T; x++) {
      const i = (y * T + x) * 4, j = nW(x, y); alb[i + 3] = 255;
      if (tri[j] < 0 || faceFrame[tri[j]] < 0 || !cntW[j]) { alb[i] = atlas[i]; alb[i + 1] = atlas[i + 1]; alb[i + 2] = atlas[i + 2]; continue; }
      // тени — только осветляем (плавно); блик — яркость медианы при оттенке фото (чужой цвет из-за неточного совмещения не просочится)
      const k = Math.exp(clamp(lrs[j], 0, 0.9)), w = wHi[j], kh = Math.min(1, lum(rhoV[j * 3], rhoV[j * 3 + 1], rhoV[j * 3 + 2]) / Math.max(1, ph[j]));
      const kk = k * (1 - w) + kh * w;
      for (let c = 0; c < 3; c++) alb[i + c] = clamp(Math.round(atlas[i + c] * kk), 0, 255);
    }
  } else
  // по модели света: фото-текстура / освещение в её кадре (точная форма и свет нужны — иначе хуже фото)
  for (let y = 0; y < T; y++) for (let x = 0; x < T; x++) {
    const i = (y * T + x) * 4, j = nW(x, y);
    alb[i + 3] = 255;
    if (tri[j] < 0 || faceFrame[tri[j]] < 0) { alb[i] = atlas[i]; alb[i + 1] = atlas[i + 1]; alb[i + 2] = atlas[i + 2]; continue; }
    const k = faceFrame[tri[j]], L = Lk[k], n = [Nw[j * 3], Nw[j * 3 + 1], Nw[j * 3 + 2]];
    const s = gain[k] * (amb * AO[j] + visAt(vis, k, j) * Math.max(0, n[0] * L[0] + n[1] * L[1] + n[2] * L[2]));
    const sp = specMax[j] / Math.max(20, lum(rhoC[j * 3], rhoC[j * 3 + 1], rhoC[j * 3 + 2]));
    const wB = clamp((sp - 0.12) / 0.15, 0, 1); // доля «цвета по всем кадрам» там, где в кадре лоскута блик
    for (let c = 0; c < 3; c++) { const a1 = atlas[i + c] / Math.max(s, 0.5 * amb + 0.05); alb[i + c] = clamp(Math.round(a1 * (1 - wB) + rhoC[j * 3 + c] * wB), 0, 255); }
  }
  // металл: базовый цвет glTF — цвет блика (а не тёмный диффузный)
  for (let ci = 0; ci < matInfo.length; ci++) {
    const mi = matInfo[ci]; if (!mi.metal) continue;
    for (let y = 0; y < T; y++) for (let x = 0; x < T; x++) { const j = nW(x, y); if (lab[j] !== ci) continue; const i = (y * T + x) * 4, m = lum(alb[i], alb[i + 1], alb[i + 2]) || 1, kk = mi.metal * Math.min(3, 150 / m) + (1 - mi.metal); for (let c = 0; c < 3; c++) alb[i + c] = clamp(Math.round(alb[i + c] * kk), 0, 255); }
  }
  prog(1, 'поверхность готова');
  return { Wr, albedo: alb, normal: nmap, orm, height: hmap, info, world: { Nw, rhoC, tri, AO, lab, conf, texels, Xp, N0, Hh, rhoV, Pm, Qm, Iaa, Ibb, Iab } };
}

// максимум по графу (наращивание на iters шагов)
export function graphMax(G, src, texels, iters) {
  let a = Float32Array.from(src), b = new Float32Array(src.length);
  for (let it = 0; it < iters; it++) {
    b.set(a);
    for (let e = 0; e < G.EI.length; e++) { const i = G.EI[e], j = G.EJ[e]; if (a[j] > b[i]) b[i] = a[j]; if (a[i] > b[j]) b[j] = a[i]; }
    const t = a; a = b; b = t;
  }
  return a;
}
// общее поле высот по графу соседних точек (см. шаг 7б); экспорт — для проверки отдельно
// граф соседних точек поверхности (в пространстве, сквозь швы развёртки): рёбра i<j, |d| ≤ 1.6 текселя, близкие нормали
export function buildGraph({ texels, Xp, N0, texMM }) {
  const R = 1.6 * texMM, cell = R, hash = new Map(), key = (x, y, z) => (x * 73856093) ^ (y * 19349663) ^ (z * 83492791);
  for (const j of texels) { const kk = key(Math.floor(Xp[j * 3] / cell), Math.floor(Xp[j * 3 + 1] / cell), Math.floor(Xp[j * 3 + 2] / cell)); let L = hash.get(kk); if (!L) hash.set(kk, (L = [])); L.push(j); }
  const EI = [], EJ = [];
  for (const i of texels) {
    const cx = Math.floor(Xp[i * 3] / cell), cy = Math.floor(Xp[i * 3 + 1] / cell), cz = Math.floor(Xp[i * 3 + 2] / cell);
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (let c = -1; c <= 1; c++) {
      const L = hash.get(key(cx + a, cy + b, cz + c)); if (!L) continue;
      for (const j of L) {
        if (j <= i) continue;
        const dl = Math.hypot(Xp[j * 3] - Xp[i * 3], Xp[j * 3 + 1] - Xp[i * 3 + 1], Xp[j * 3 + 2] - Xp[i * 3 + 2]);
        if (dl > R || dl < 0.2 * texMM) continue;
        if (N0[i * 3] * N0[j * 3] + N0[i * 3 + 1] * N0[j * 3 + 1] + N0[i * 3 + 2] * N0[j * 3 + 2] < 0.8) continue;
        EI.push(i); EJ.push(j);
      }
    }
  }
  return { EI: Int32Array.from(EI), EJ: Int32Array.from(EJ) };
}
// сглаживание по графу (усреднение с соседями, iters раз ≈ гаусс σ ≈ √iters · 0.7 текселя); ch — каналов на точку
export function graphSmooth(G, src, texels, iters, ch = 1) {
  let a = Float32Array.from(src), b = new Float32Array(src.length); const cnt = new Float32Array(src.length / ch);
  for (let e = 0; e < G.EI.length; e++) { cnt[G.EI[e]]++; cnt[G.EJ[e]]++; }
  for (let it = 0; it < iters; it++) {
    for (const j of texels) for (let c = 0; c < ch; c++) b[j * ch + c] = a[j * ch + c];
    for (let e = 0; e < G.EI.length; e++) { const i = G.EI[e], j = G.EJ[e]; for (let c = 0; c < ch; c++) { b[i * ch + c] += a[j * ch + c]; b[j * ch + c] += a[i * ch + c]; } }
    for (const j of texels) { const k = 1 / (1 + cnt[j]); for (let c = 0; c < ch; c++) b[j * ch + c] *= k; }
    const t = a; a = b; b = t;
  }
  return a;
}
// общее поле высот по графу соседних точек (см. шаг 7б); экспорт — для проверки отдельно
export async function solveRelief({ texels, Xp, N0, T1, T2, Pm, Qm, Iaa, Iab, Ibb, NT, texMM, o = {}, tick = async () => {}, tiltN, hIn = null, graph = null }) {
  const N = new Float32Array(N0), GR = graph || buildGraph({ texels, Xp, N0, texMM });
    const EI = GR.EI, EJ = GR.EJ, EW = new Float32Array(EI.length), ED = new Float32Array(EI.length), nu = o.reliefPrior ?? 4;
    if (!hIn) for (let e = 0; e < EI.length; e++) {
      const i = EI[e], j = EJ[e], d = [Xp[j * 3] - Xp[i * 3], Xp[j * 3 + 1] - Xp[i * 3 + 1], Xp[j * 3 + 2] - Xp[i * 3 + 2]], dl = Math.hypot(...d);
      // уклон вдоль d по каждой точке и его дисперсия (обратная информация в направлении d)
      let dh = 0, wsum = 0;
      for (const t of [i, j]) {
        const e1 = (d[0] * T1[t * 3] + d[1] * T1[t * 3 + 1] + d[2] * T1[t * 3 + 2]) / dl, e2 = (d[0] * T2[t * 3] + d[1] * T2[t * 3 + 1] + d[2] * T2[t * 3 + 2]) / dl;
        const ia = Iaa[t] + nu, ib = Ibb[t] + nu, iab = Iab[t], det = ia * ib - iab * iab; if (det <= 0) continue;
        const v = (e1 * e1 * ib - 2 * e1 * e2 * iab + e2 * e2 * ia) / det; // var(g·ê)
        const gpr = -(Pm[t] * e1 + Qm[t] * e2) * (Iaa[t] + Ibb[t] > 0 ? 1 : 0); // ∇h = −(p t1 + q t2)
        dh += gpr / v; wsum += 1 / v;
      }
      if (wsum) { EW[e] = wsum / 2 / (dl * dl); ED[e] = dh / wsum * dl; }
    }
    if (o.debugEdges) o.debugEdges({ EI, EJ, EW, ED });
    const ne = EI.length, h = new Float64Array(NT), diag = new Float64Array(NT), b = new Float64Array(NT);
    if (hIn) for (const j of texels) h[j] = hIn[j]; else {
    for (let e = 0; e < ne; e++) { const w = EW[e]; diag[EI[e]] += w; diag[EJ[e]] += w; b[EI[e]] -= w * ED[e]; b[EJ[e]] += w * ED[e]; }
    let md = 0, nd = 0; for (const j of texels) if (diag[j] > 0) { md += diag[j]; nd++; } md = nd ? md / nd : 1;
    const mu = (o.reliefAnchor ?? 2e-3) * md; for (const j of texels) diag[j] += mu;
    const Ax = (x, y) => { for (const j of texels) y[j] = mu * x[j]; for (let e = 0; e < ne; e++) { const i = EI[e], j = EJ[e], t = EW[e] * (x[j] - x[i]); y[i] -= t; y[j] += t; } };
    // сопряжённые градиенты с диагональным предобуславливателем
    const r = new Float64Array(NT), z = new Float64Array(NT), pp = new Float64Array(NT), Ap = new Float64Array(NT);
    for (const j of texels) { r[j] = b[j]; z[j] = r[j] / diag[j]; pp[j] = z[j]; }
    let rz = 0; for (const j of texels) rz += r[j] * z[j];
    for (let it = 0; it < (o.reliefIters ?? 400) && rz > 1e-14; it++) {
      Ax(pp, Ap); let pAp = 0; for (const j of texels) pAp += pp[j] * Ap[j]; if (pAp <= 0) break; const al = rz / pAp;
      let rz2 = 0; for (const j of texels) { h[j] += al * pp[j]; r[j] -= al * Ap[j]; z[j] = r[j] / diag[j]; rz2 += r[j] * z[j]; }
      const be = rz2 / rz; rz = rz2; for (const j of texels) pp[j] = z[j] + be * pp[j];
      if (it % 100 === 99) await tick();
    }
    }
    // нормали из поля высот: уклон по соседям (МНК в касательной плоскости)
    const G = new Float64Array(NT * 5);
    for (let e = 0; e < ne; e++) {
      const i = EI[e], j = EJ[e], dhv = h[j] - h[i];
      for (const [t, sgn] of [[i, 1], [j, -1]]) {
        const d1 = sgn * ((Xp[j * 3] - Xp[i * 3]) * T1[t * 3] + (Xp[j * 3 + 1] - Xp[i * 3 + 1]) * T1[t * 3 + 1] + (Xp[j * 3 + 2] - Xp[i * 3 + 2]) * T1[t * 3 + 2]);
        const d2 = sgn * ((Xp[j * 3] - Xp[i * 3]) * T2[t * 3] + (Xp[j * 3 + 1] - Xp[i * 3 + 1]) * T2[t * 3 + 1] + (Xp[j * 3 + 2] - Xp[i * 3 + 2]) * T2[t * 3 + 2]);
        const v = sgn * dhv; G[t * 5] += d1 * d1; G[t * 5 + 1] += d1 * d2; G[t * 5 + 2] += d2 * d2; G[t * 5 + 3] += d1 * v; G[t * 5 + 4] += d2 * v;
      }
    }
    for (const j of texels) {
      const a = G[j * 5] + 1e-3 * texMM * texMM, bb = G[j * 5 + 1], c = G[j * 5 + 2] + 1e-3 * texMM * texMM, det = a * c - bb * bb; if (det <= 0) continue;
      const g1 = (c * G[j * 5 + 3] - bb * G[j * 5 + 4]) / det, g2 = (a * G[j * 5 + 4] - bb * G[j * 5 + 3]) / det;
      const n = tiltN(j, clamp(-g1, -1.5, 1.5), clamp(-g2, -1.5, 1.5)); N[j * 3] = n[0]; N[j * 3 + 1] = n[1]; N[j * 3 + 2] = n[2];
    }
  return { h: new Float32Array(h), N, ne };
}

// размытие по маске (только тексели, принадлежащие тому же лоскуту, если задан faceChart): нормированная свёртка
function blurMasked(src, tri, W, r, faceChart) {
  const n = W * W, tmp = new Float32Array(n), out = new Float32Array(n), wt = new Float32Array(n), wt2 = new Float32Array(n);
  const ch = (j) => (tri[j] < 0 ? -1 : faceChart ? faceChart[tri[j]] : 0);
  const sig = r / 2, ker = []; for (let d = -r; d <= r; d++) ker.push(Math.exp(-(d * d) / (2 * sig * sig)));
  for (let y = 0; y < W; y++) for (let x = 0; x < W; x++) {
    const j = y * W + x, c = ch(j); if (c < 0) continue; let s = 0, w = 0;
    for (let d = -r; d <= r; d++) { const xx = x + d; if (xx < 0 || xx >= W) continue; const q = j + d; if (ch(q) !== c) continue; s += ker[d + r] * src[q]; w += ker[d + r]; }
    tmp[j] = w ? s / w : src[j]; wt[j] = w;
  }
  for (let y = 0; y < W; y++) for (let x = 0; x < W; x++) {
    const j = y * W + x, c = ch(j); if (c < 0) continue; let s = 0, w = 0;
    for (let d = -r; d <= r; d++) { const yy = y + d; if (yy < 0 || yy >= W) continue; const q = j + d * W; if (ch(q) !== c) continue; s += ker[d + r] * tmp[q]; w += ker[d + r]; }
    out[j] = w ? s / w : tmp[j]; wt2[j] = w;
  }
  return out;
}
// высота из уклонов: уравнение Пуассона в каждом лоскуте (Гаусс — Зейдель с перерелаксацией), края — свободные
function integrateHeight(gx, gy, has, W, chartOf, tri) {
  const n = W * W, h = new Float32Array(n), div = new Float32Array(n), nb = new Uint8Array(n);
  const same = (a, b) => has[a] && has[b] && (!chartOf || chartOf(a) === chartOf(b));
  for (let y = 0; y < W; y++) for (let x = 0; x < W; x++) {
    const j = y * W + x; if (!has[j]) continue; let d = 0, k = 0;
    if (x + 1 < W && same(j, j + 1)) { d += (gx[j] + gx[j + 1]) / 2; k++; }
    if (x > 0 && same(j, j - 1)) { d -= (gx[j] + gx[j - 1]) / 2; k++; }
    if (y + 1 < W && same(j, j + W)) { d += (gy[j] + gy[j + W]) / 2; k++; }
    if (y > 0 && same(j, j - W)) { d -= (gy[j] + gy[j - W]) / 2; k++; }
    div[j] = d; nb[j] = k;
  }
  const om = 1.85;
  for (let it = 0; it < 250; it++) for (let j = 0; j < n; j++) {
    const k = nb[j]; if (!k) continue; let s = 0; const x = j % W;
    if (x + 1 < W && same(j, j + 1)) s += h[j + 1]; if (x > 0 && same(j, j - 1)) s += h[j - 1];
    if (j + W < n && same(j, j + W)) s += h[j + W]; if (j >= W && same(j, j - W)) s += h[j - W];
    h[j] += om * ((s - div[j]) / k - h[j]);
  }
  return h;
}
// заполнить пустые тексели (поля между лоскутами) соседними значениями — против швов при фильтрации
function dilate(img, tri, W, pass, fill) {
  const ok = new Uint8Array(W * W); for (let j = 0; j < W * W; j++) ok[j] = tri[j] >= 0 ? 1 : 0;
  for (let p = 0; p < pass; p++) {
    const add = [];
    for (let j = 0; j < W * W; j++) {
      if (ok[j]) continue; const x = j % W; let s0 = 0, s1 = 0, s2 = 0, k = 0;
      for (const q of [x > 0 ? j - 1 : -1, x < W - 1 ? j + 1 : -1, j - W, j + W]) if (q >= 0 && q < W * W && ok[q]) { s0 += img[q * 4]; s1 += img[q * 4 + 1]; s2 += img[q * 4 + 2]; k++; }
      if (k) add.push([j, s0 / k, s1 / k, s2 / k]);
    }
    for (const [j, a, b, c] of add) { img[j * 4] = a; img[j * 4 + 1] = b; img[j * 4 + 2] = c; img[j * 4 + 3] = 255; ok[j] = 1; }
  }
  for (let j = 0; j < W * W; j++) if (!ok[j]) { img[j * 4] = fill[0]; img[j * 4 + 1] = fill[1]; img[j * 4 + 2] = fill[2]; img[j * 4 + 3] = 255; }
}
// k-средних по цвету альбедо (оттенок + яркость в логарифме): зоны одного материала
function clusterAlbedo(rho, texels, K) {
  const feat = (j) => { const r = rho[j * 3] + 1, g = rho[j * 3 + 1] + 1, b = rho[j * 3 + 2] + 1, s = r + g + b; return [3 * r / s, 3 * g / s, Math.log(s / 3) * 0.6]; };
  const smp = texels.filter((_, i) => i % 7 === 0); if (!smp.length) return { centers: [], share: [], label: () => -1 };
  const F = smp.map(feat), C = [F[0]];
  while (C.length < Math.min(K, F.length)) { let bi = 0, bd = -1; F.forEach((f, i) => { let d = Infinity; for (const c of C) d = Math.min(d, (f[0] - c[0]) ** 2 + (f[1] - c[1]) ** 2 + (f[2] - c[2]) ** 2); if (d > bd) { bd = d; bi = i; } }); if (bd < 0.01) break; C.push(F[bi]); }
  const near = (f) => { let bi = 0, bd = Infinity; C.forEach((c, i) => { const d = (f[0] - c[0]) ** 2 + (f[1] - c[1]) ** 2 + (f[2] - c[2]) ** 2; if (d < bd) { bd = d; bi = i; } }); return bi; };
  for (let it = 0; it < 12; it++) { const s = C.map(() => [0, 0, 0, 0]); F.forEach((f) => { const i = near(f); s[i][0] += f[0]; s[i][1] += f[1]; s[i][2] += f[2]; s[i][3]++; }); s.forEach((v, i) => { if (v[3]) C[i] = [v[0] / v[3], v[1] / v[3], v[2] / v[3]]; }); }
  const share = C.map(() => 0), colr = C.map(() => [0, 0, 0]);
  smp.forEach((j, i) => { const c = near(F[i]); share[c]++; for (let k = 0; k < 3; k++) colr[c][k] += rho[j * 3 + k]; });
  return { centers: colr.map((v, i) => v.map((x) => x / Math.max(1, share[i]))), share: share.map((v) => +(v / smp.length).toFixed(3)), label: (j) => near(feat(j)) };
}
