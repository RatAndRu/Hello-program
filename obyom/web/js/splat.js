import { carveVote } from './recon.js';
// Объём — гауссовы сплэты на процессоре (без видеокарты и без нейросетей).
// Каждая «капля»: центр, 3 радиуса, поворот, непрозрачность и цвет, зависящий от направления взгляда
// (сферические гармоники, как в оригинальном 3DGS: блик живёт на поверхности и смещается при повороте).
// Подгоняем их градиентным спуском (Adam) так, чтобы картинка совпала с кадрами. Рендер — тайлами, как в 3DGS.
// С 1.9: у каждого кадра своя поправка яркости (автоэкспозиция), маска требует прозрачности на фоне и
// непрозрачности на предмете, капли — плоские диски, стянутые вдоль луча к одной поверхности.

const TILE = 8;
const _D = new Float64Array(9), _dM = new Float64Array(9), _dR = new Float64Array(9), _S3 = new Float64Array(9), _TS = new Float64Array(6), _dT = new Float64Array(6);
const sig = (x) => 1 / (1 + Math.exp(-x));
export const SH_C0 = 0.28209479177387814;
const SH_C1 = 0.4886025119029199, SH_C2 = [1.0925484305920792, -1.0925484305920792, 0.31539156525252005, -1.0925484305920792, 0.5462742152960396];
// базис сферических гармоник степени deg (0..2) для направления (x,y,z) — порядок и знаки как в 3DGS
export function shBasis(deg, x, y, z, out) {
  out[0] = SH_C0;
  if (deg < 1) return out;
  out[1] = -SH_C1 * y; out[2] = SH_C1 * z; out[3] = -SH_C1 * x;
  if (deg < 2) return out;
  const xx = x * x, yy = y * y, zz = z * z;
  out[4] = SH_C2[0] * x * y; out[5] = SH_C2[1] * y * z; out[6] = SH_C2[2] * (2 * zz - xx - yy); out[7] = SH_C2[3] * x * z; out[8] = SH_C2[4] * (xx - yy);
  return out;
}

export class Splats {
  // deg — степень гармоник цвета: 0 — один цвет, 1 — 4 коэффициента на канал, 2 — 9
  constructor(n, deg = 1) { this.deg = deg; this.nb = (deg + 1) * (deg + 1); this.alloc(n); this.n = 0; }
  alloc(cap) {
    const old = this.cap ? this : null; this.cap = cap;
    const next = {};
    for (const [name, k] of Object.entries({ mu: 3, ls: 3, q: 4, op: 1, sh: 3 * this.nb })) { next[name] = new Float32Array(cap * k); if (old) next[name].set(old[name].subarray(0, old.n * k)); }
    Object.assign(this, next);
  }
  // sh: 3 числа — цвет 0..1 (остальные гармоники нули) или 3·nb коэффициентов [k][канал]
  push(mu, ls, q, op, sh) {
    if (this.n >= this.cap) this.alloc(Math.ceil(this.cap * 1.5) + 16);
    const i = this.n++, nb3 = 3 * this.nb;
    this.mu.set(mu, i * 3); this.ls.set(ls, i * 3); this.q.set(q, i * 4); this.op[i] = op;
    if (sh.length === nb3) this.sh.set(sh, i * nb3);
    else { this.sh.fill(0, i * nb3, (i + 1) * nb3); for (let c = 0; c < 3; c++) this.sh[i * nb3 + c] = (sh[c] - 0.5) / SH_C0; }
    return i;
  }
  // «средний» цвет капли (без зависимости от угла), 0..1
  baseColor(i, c) { return Math.min(1, Math.max(0, 0.5 + SH_C0 * this.sh[i * 3 * this.nb + c])); }
}

function quatToR(qw, qx, qy, qz, R) {
  const l = Math.hypot(qw, qx, qy, qz) || 1; const w = qw / l, x = qx / l, y = qy / l, z = qz / l;
  R[0] = 1 - 2 * (y * y + z * z); R[1] = 2 * (x * y - w * z); R[2] = 2 * (x * z + w * y);
  R[3] = 2 * (x * y + w * z); R[4] = 1 - 2 * (x * x + z * z); R[5] = 2 * (y * z - w * x);
  R[6] = 2 * (x * z - w * y); R[7] = 2 * (y * z + w * x); R[8] = 1 - 2 * (x * x + y * y);
  return l;
}

// ---------- прямой проход: проекция всех капель для одного вида ----------
// view: {K, R, t, x0, y0, cw, ch} — окно (кроп) кадра, в котором считаем
function preprocess(S, view, P) {
  const n = S.n, { K, R, t } = view;
  if (!P.cap || P.cap < n) {
    P.cap = Math.max(n, 16);
    for (const [k, m] of [['u', 1], ['v', 1], ['z', 1], ['A', 1], ['B', 1], ['C', 1], ['rad', 1], ['cov', 3], ['T', 6], ['M', 9], ['Rq', 9], ['ok', 1]]) P[k] = new Float32Array(P.cap * m);
  }
  const Rq = new Float32Array(9);
  for (let i = 0; i < n; i++) {
    P.ok[i] = 0;
    const X = S.mu[i * 3], Y = S.mu[i * 3 + 1], Z = S.mu[i * 3 + 2];
    const x = R[0] * X + R[1] * Y + R[2] * Z + t[0], y = R[3] * X + R[4] * Y + R[5] * Z + t[1], z = R[6] * X + R[7] * Y + R[8] * Z + t[2];
    if (z < 5) continue;
    quatToR(S.q[i * 4], S.q[i * 4 + 1], S.q[i * 4 + 2], S.q[i * 4 + 3], Rq);
    const s0 = Math.exp(S.ls[i * 3]), s1 = Math.exp(S.ls[i * 3 + 1]), s2 = Math.exp(S.ls[i * 3 + 2]);
    // M = Rq·diag(s); Σ = M Mᵀ
    const M = [Rq[0] * s0, Rq[1] * s1, Rq[2] * s2, Rq[3] * s0, Rq[4] * s1, Rq[5] * s2, Rq[6] * s0, Rq[7] * s1, Rq[8] * s2];
    const S00 = M[0] * M[0] + M[1] * M[1] + M[2] * M[2], S01 = M[0] * M[3] + M[1] * M[4] + M[2] * M[5], S02 = M[0] * M[6] + M[1] * M[7] + M[2] * M[8];
    const S11 = M[3] * M[3] + M[4] * M[4] + M[5] * M[5], S12 = M[3] * M[6] + M[4] * M[7] + M[5] * M[8], S22 = M[6] * M[6] + M[7] * M[7] + M[8] * M[8];
    // T = J·W (2×3)
    const iz = 1 / z, j00 = K.fx * iz, j02 = -K.fx * x * iz * iz, j11 = K.fy * iz, j12 = -K.fy * y * iz * iz;
    const T0 = j00 * R[0] + j02 * R[6], T1 = j00 * R[1] + j02 * R[7], T2 = j00 * R[2] + j02 * R[8];
    const T3 = j11 * R[3] + j12 * R[6], T4 = j11 * R[4] + j12 * R[7], T5 = j11 * R[5] + j12 * R[8];
    // Σ2 = T Σ Tᵀ
    const a0 = T0 * S00 + T1 * S01 + T2 * S02, a1 = T0 * S01 + T1 * S11 + T2 * S12, a2 = T0 * S02 + T1 * S12 + T2 * S22;
    const b0 = T3 * S00 + T4 * S01 + T5 * S02, b1 = T3 * S01 + T4 * S11 + T5 * S12, b2 = T3 * S02 + T4 * S12 + T5 * S22;
    const ca = a0 * T0 + a1 * T1 + a2 * T2 + 0.3, cb = a0 * T3 + a1 * T4 + a2 * T5, cc = b0 * T3 + b1 * T4 + b2 * T5 + 0.3;
    const det = ca * cc - cb * cb; if (det <= 1e-9) continue;
    const u = K.fx * x * iz + K.cx, v = K.fy * y * iz + K.cy;
    const mid = 0.5 * (ca + cc), lam = mid + Math.sqrt(Math.max(0.1, mid * mid - det));
    const o = 1 / (1 + Math.exp(-S.op[i])); if (o < 1 / 255) continue;
    const rad = Math.ceil(Math.sqrt(2 * Math.log(255 * o) * lam)); // дальше вклад < 1/255
    if (rad < 1) continue;
    if (u + rad < view.x0 || v + rad < view.y0 || u - rad > view.x0 + view.cw || v - rad > view.y0 + view.ch) continue;
    P.ok[i] = 1; P.u[i] = u; P.v[i] = v; P.z[i] = z; P.rad[i] = rad;
    P.A[i] = cc / det; P.B[i] = -cb / det; P.C[i] = ca / det;
    P.cov[i * 3] = ca; P.cov[i * 3 + 1] = cb; P.cov[i * 3 + 2] = cc;
    P.T.set([T0, T1, T2, T3, T4, T5], i * 6); P.M.set(M, i * 9); P.Rq.set(Rq, i * 9);
  }
}


const PK = 10; // упаковка капли в списке тайла: u v A B C opa c0 c1 c2 z
function binTiles(S, view, P, opa, col, part) {
  const n = S.n, tw = Math.ceil(view.cw / TILE), th = Math.ceil(view.ch / TILE), nt = tw * th;
  const idx = []; for (let i = 0; i < n; i++) if (P.ok[i]) idx.push(i);
  idx.sort((a, b) => P.z[a] - P.z[b]);
  // проход 1: счёт, проход 2: раскладка (сортировка подсчётом, порядок по глубине сохраняется)
  const cnt = new Int32Array(nt + 1);
  const each = (i, fn) => {
    const r = P.rad[i], u = P.u[i] - view.x0, v = P.v[i] - view.y0;
    const tx0 = Math.max(0, Math.floor((u - r) / TILE)), tx1 = Math.min(tw - 1, Math.floor((u + r) / TILE));
    const ty0 = Math.max(0, Math.floor((v - r) / TILE)), ty1 = Math.min(th - 1, Math.floor((v + r) / TILE));
    const A = P.A[i], B = P.B[i], C = P.C[i], lim = 2 * Math.log(255 * opa[i]);
    for (let ty = ty0; ty <= ty1; ty++) { if (part && ty % part.K !== part.k) continue; for (let tx = tx0; tx <= tx1; tx++) {
      // ближайшая к центру точка тайла: если там вклад < 1/255 — тайл не задет (точно для круга, осторожно для эллипса)
      if (tx1 - tx0 > 1 || ty1 - ty0 > 1) {
        const qx = Math.min(Math.max(u, tx * TILE), tx * TILE + TILE), qy = Math.min(Math.max(v, ty * TILE), ty * TILE + TILE);
        const dx = qx - u, dy = qy - v;
        if (A * dx * dx + C * dy * dy + 2 * B * dx * dy > lim * 1.6) continue;
      }
      fn(ty * tw + tx);
    } }
  };
  for (const i of idx) each(i, (t) => cnt[t + 1]++);
  for (let t = 0; t < nt; t++) cnt[t + 1] += cnt[t];
  const total = cnt[nt], list = new Int32Array(total), fill = cnt.slice(0, nt);
  for (const i of idx) each(i, (t) => { list[fill[t]++] = i; });
  const pk = new Float32Array(total * PK);
  for (let k = 0; k < total; k++) {
    const i = list[k], o = k * PK;
    pk[o] = P.u[i]; pk[o + 1] = P.v[i]; pk[o + 2] = P.A[i]; pk[o + 3] = P.B[i]; pk[o + 4] = P.C[i]; pk[o + 5] = opa[i];
    pk[o + 6] = col[i * 3]; pk[o + 7] = col[i * 3 + 1]; pk[o + 8] = col[i * 3 + 2]; pk[o + 9] = P.z[i];
  }
  return { start: cnt, list, pk, tw, th };
}

// центр камеры в координатах коврика: C = −Rᵀt
function camCenter(view) {
  if (!view.C) { const R = view.R, t = view.t; view.C = [-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])]; }
  return view.C;
}
// цвет каждой капли для этого вида (гармоники по направлению камера → капля); basis — для обратного прохода
function viewColors(S, view, P, col, basis) {
  const nb = S.nb, nb3 = 3 * nb, deg = S.deg, C = camCenter(view), b = new Float64Array(9), raw = new Uint8Array(S.n * 3);
  for (let i = 0; i < S.n; i++) {
    if (!P.ok[i]) continue;
    let dx = S.mu[i * 3] - C[0], dy = S.mu[i * 3 + 1] - C[1], dz = S.mu[i * 3 + 2] - C[2]; const l = Math.hypot(dx, dy, dz) || 1;
    shBasis(deg, dx / l, dy / l, dz / l, b);
    for (let k = 0; k < nb; k++) basis[i * nb + k] = b[k];
    for (let c = 0; c < 3; c++) {
      let v = 0.5; for (let k = 0; k < nb; k++) v += b[k] * S.sh[i * nb3 + k * 3 + c];
      if (v < 0) v = 0; else if (v > 1) v = 1; else raw[i * 3 + c] = 1; // 1 — внутри [0,1], градиент проходит
      col[i * 3 + c] = v;
    }
  }
  return raw;
}

// Рендер окна; если opt.grad — градиенты loss по параметрам капель, возвращаем loss.
// loss = Charbonnier(цвет) · wt  +  alphaW·(α − цель)² по маске  +  depthW·½Σ wᵢ(zᵢ − z̄)² (капли — к одной поверхности).
// view.gain [r,g,b] — поправка яркости кадра: на картинке капли = gain·цвет (фон за ними — сам кадр, без поправки).
export function renderView(S, view, opt = {}) {
  const P = opt.P || {};
  preprocess(S, view, P);
  const n = S.n, nb = S.nb, col = new Float32Array(n * 3), opa = new Float32Array(n), basis = new Float32Array(n * nb);
  for (let i = 0; i < n; i++) opa[i] = sig(S.op[i]);
  const inRange = viewColors(S, view, P, col, basis);
  const { start, list, pk, tw } = binTiles(S, view, P, opa, col, opt.part);
  const { cw, ch } = view, npx = cw * ch, gain = view.gain || [1, 1, 1];
  const out = opt.out || new Float32Array(npx * 3), Tf = new Float32Array(npx), last = new Int32Array(npx);
  const grad = opt.grad, sc = grad ? new Float32Array(npx * 3) : null, Wd = grad ? new Float32Array(npx) : null, Zd = grad ? new Float32Array(npx) : null;
  const bg = view.bg;
  // часть кадра (v2.1, потоки): только ряды тайлов с номером ≡ part.k (mod part.K) — остальные считают другие потоки
  const part = opt.part, rowOn = part ? (py) => ((py / TILE) | 0) % part.K === part.k : null;
  for (let py = 0; py < ch; py++) { if (rowOn && !rowOn(py)) continue; for (let px = 0; px < cw; px++) {
    const tile = ((py / TILE) | 0) * tw + ((px / TILE) | 0), k0 = start[tile], k1 = start[tile + 1];
    const gx = view.x0 + px + 0.5, gy = view.y0 + py + 0.5;
    let T = 1, r = 0, g = 0, b = 0, lastK = k0, ws = 0, zs = 0;
    for (let k = k0; k < k1; k++) {
      const o = k * PK, dx = gx - pk[o], dy = gy - pk[o + 1];
      const power = -0.5 * (pk[o + 2] * dx * dx + pk[o + 4] * dy * dy) - pk[o + 3] * dx * dy;
      if (power > 0 || power < -5.55) continue;
      const al = Math.min(0.99, pk[o + 5] * Math.exp(power));
      if (al < 1 / 255) continue;
      const nT = T * (1 - al);
      if (nT < 1e-4) break;
      const aT = al * T;
      r += pk[o + 6] * aT; g += pk[o + 7] * aT; b += pk[o + 8] * aT; ws += aT; zs += aT * pk[o + 9];
      T = nT; lastK = k + 1;
    }
    const j = py * cw + px;
    Tf[j] = T; last[j] = lastK;
    out[j * 3] = gain[0] * r + T * bg[j * 3]; out[j * 3 + 1] = gain[1] * g + T * bg[j * 3 + 1]; out[j * 3 + 2] = gain[2] * b + T * bg[j * 3 + 2];
    if (grad) { sc[j * 3] = r; sc[j * 3 + 1] = g; sc[j * 3 + 2] = b; Wd[j] = ws; Zd[j] = zs; }
  } }
  if (!grad) return { out, T: Tf };
  // ---------- обратный проход ----------
  const G = grad; // {mu, ls, q, op, sh, m2d(накопление |∂L/∂uv|), cnt, gain[3]}
  const tgt = view.img, wt = view.wt, at = view.at, eps = 0.03, aW = opt.alphaW || 0, dW = opt.depthW || 0;
  let loss = 0, wsum = 0;
  const dU = new Float32Array(n), dV = new Float32Array(n), dA = new Float32Array(n), dB = new Float32Array(n), dC = new Float32Array(n), dOp = new Float32Array(n), dCol = new Float32Array(n * 3), dZ = dW ? new Float32Array(n) : null;
  if (opt.wsum != null) wsum = opt.wsum; else for (let j = 0; j < npx; j++) wsum += wt[j];
  const norm = 1 / Math.max(1, wsum), dL = [0, 0, 0], dLs = [0, 0, 0];
  if (!G.gain) G.gain = [0, 0, 0];
  for (let py = 0; py < ch; py++) { if (rowOn && !rowOn(py)) continue; for (let px = 0; px < cw; px++) {
    const j = py * cw + px, w = wt[j];
    const tA = at && aW ? at[j] : -1;
    if (!w && tA < 0) continue;
    for (let c = 0; c < 3; c++) {
      if (!w) { dL[c] = 0; continue; }
      const rr = out[j * 3 + c] - tgt[j * 3 + c], s = Math.sqrt(rr * rr + eps * eps); loss += w * (s - eps); dL[c] = w * rr / s * norm;
      G.gain[c] += dL[c] * sc[j * 3 + c]; dLs[c] = dL[c] * gain[c];
    }
    if (!w) { dLs[0] = dLs[1] = dLs[2] = 0; }
    const TF = Tf[j];
    let bgDot = bg[j * 3] * dL[0] + bg[j * 3 + 1] * dL[1] + bg[j * 3 + 2] * dL[2];
    if (tA >= 0) { const e = 1 - TF - tA; loss += aW * e * e; bgDot += -2 * aW * e * norm; } // ∂/∂TF от (1−TF−цель)²
    const zbar = dW && Wd[j] > 0.3 ? Zd[j] / Wd[j] : NaN;
    const tile = ((py / TILE) | 0) * tw + ((px / TILE) | 0), k0 = start[tile];
    const gx = view.x0 + px + 0.5, gy = view.y0 + py + 0.5;
    let T = TF;
    let acc0 = 0, acc1 = 0, acc2 = 0, lastA = 0, lc0 = 0, lc1 = 0, lc2 = 0, accE = 0;
    for (let k = last[j] - 1; k >= k0; k--) {
      const o = k * PK, dx = gx - pk[o], dy = gy - pk[o + 1];
      const qa = pk[o + 2], qb = pk[o + 3], qc = pk[o + 4];
      const power = -0.5 * (qa * dx * dx + qc * dy * dy) - qb * dx * dy;
      if (power > 0 || power < -5.55) continue;
      const op = pk[o + 5], Gv = Math.exp(power), al0 = op * Gv, al = Math.min(0.99, al0);
      if (al < 1 / 255) continue;
      const i = list[k];
      T = T / (1 - al);
      const c0 = pk[o + 6], c1 = pk[o + 7], c2 = pk[o + 8];
      acc0 = lastA * lc0 + (1 - lastA) * acc0; acc1 = lastA * lc1 + (1 - lastA) * acc1; acc2 = lastA * lc2 + (1 - lastA) * acc2;
      lc0 = c0; lc1 = c1; lc2 = c2; lastA = al;
      const wct = al * T;
      dCol[i * 3] += wct * dLs[0]; dCol[i * 3 + 1] += wct * dLs[1]; dCol[i * 3 + 2] += wct * dLs[2];
      let dAl = T * ((c0 - acc0) * dLs[0] + (c1 - acc1) * dLs[1] + (c2 - acc2) * dLs[2]) - TF / (1 - al) * bgDot;
      if (zbar === zbar) {
        // ½·Σ wₖ(zₖ − z̄)²: по глубине капли и по её весу wᵢ = αᵢTᵢ (вес тех, кто за ней, делится на (1 − αᵢ))
        const e = pk[o + 9] - zbar, h = 0.5 * e * e; dZ[i] += dW * wct * e * norm; loss += dW * wct * h;
        dAl += dW * norm * (T * h - accE / (1 - al)); accE += wct * h;
      }
      if (al0 >= 0.99) continue; // в насыщении градиента нет
      dOp[i] += Gv * dAl;
      const dP = op * Gv * dAl;
      dU[i] += dP * (qa * dx + qb * dy); dV[i] += dP * (qc * dy + qb * dx);
      dA[i] += -0.5 * dx * dx * dP; dB[i] += -dx * dy * dP; dC[i] += -0.5 * dy * dy * dP;
    }
  } }
  const d2 = { dU, dV, dA, dB, dC, dOp, dCol, dZ };
  if (opt.only2d) return { loss: loss * norm, d2 }; // поток: только градиенты на картинке, остальное — chain2d в одном месте
  chain2d(S, view, P, d2, G, inRange, basis, opa);
  return { out, loss: loss * norm };
}

// градиенты на картинке (по центру, конике, непрозрачности, цвету капли в этом виде) → по параметрам капли.
// P, inRange, basis, opa — от preprocess/viewColors этого вида (у главного потока — свои, совпадают с потоками)
export function prepView(S, view, P) {
  preprocess(S, view, P);
  const n = S.n, nb = S.nb, col = new Float32Array(n * 3), opa = new Float32Array(n), basis = new Float32Array(n * nb);
  for (let i = 0; i < n; i++) opa[i] = sig(S.op[i]);
  const inRange = viewColors(S, view, P, col, basis);
  return { inRange, basis, opa };
}
export function chain2d(S, view, P, d2, G, inRange, basis, opa) {
  const { dU, dV, dA, dB, dC, dOp, dCol, dZ } = d2, n = S.n, nb = S.nb;
  const { K, R } = view, nb3 = 3 * nb;
  for (let i = 0; i < n; i++) {
    if (!P.ok[i]) continue;
    if (dZ && dZ[i]) { G.mu[i * 3] += dZ[i] * R[6]; G.mu[i * 3 + 1] += dZ[i] * R[7]; G.mu[i * 3 + 2] += dZ[i] * R[8]; }
    if (!(dU[i] || dV[i] || dA[i] || dB[i] || dC[i] || dOp[i] || dCol[i * 3] || dCol[i * 3 + 1] || dCol[i * 3 + 2])) continue;
    G.cnt[i]++; G.m2d[i] += Math.hypot(dU[i], dV[i]);
    // цвет: линейные гармоники (обрезка до [0,1] — без градиента)
    for (let c = 0; c < 3; c++) { if (!inRange[i * 3 + c]) continue; const g = dCol[i * 3 + c]; for (let k = 0; k < nb; k++) G.sh[i * nb3 + k * 3 + c] += g * basis[i * nb + k]; }
    G.op[i] += dOp[i] * opa[i] * (1 - opa[i]);
    // центр: u = fx·x/z + cx
    const X = S.mu[i * 3], Y = S.mu[i * 3 + 1], Z = S.mu[i * 3 + 2];
    const x = R[0] * X + R[1] * Y + R[2] * Z + view.t[0], y = R[3] * X + R[4] * Y + R[5] * Z + view.t[1], z = P.z[i], iz = 1 / z;
    const gpx = dU[i] * K.fx * iz, gpy = dV[i] * K.fy * iz, gpz = -(dU[i] * K.fx * x + dV[i] * K.fy * y) * iz * iz;
    G.mu[i * 3] += R[0] * gpx + R[3] * gpy + R[6] * gpz; G.mu[i * 3 + 1] += R[1] * gpx + R[4] * gpy + R[7] * gpz; G.mu[i * 3 + 2] += R[2] * gpx + R[5] * gpy + R[8] * gpz;
    // коника → Σ2: dΣ2 = −Q·Gq·Q
    const qa = P.A[i], qb = P.B[i], qc = P.C[i];
    const g11 = dA[i], g12 = dB[i] / 2, g22 = dC[i];
    // Q·G
    const m11 = qa * g11 + qb * g12, m12 = qa * g12 + qb * g22, m21 = qb * g11 + qc * g12, m22 = qb * g12 + qc * g22;
    const s11 = -(m11 * qa + m12 * qb), s12 = -(m11 * qb + m12 * qc), s22 = -(m21 * qb + m22 * qc);
    // Σ2 = T Σ3 Tᵀ → dΣ3 = Tᵀ dΣ2 T (dΣ2 симметричная: [[s11,s12],[s12,s22]])
    const T = P.T.subarray(i * 6, i * 6 + 6);
    const D = _D;
    for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) D[a * 3 + b] = T[a] * (s11 * T[b] + s12 * T[3 + b]) + T[3 + a] * (s12 * T[b] + s22 * T[3 + b]);
    // Σ3 = M Mᵀ → dM = 2·D·M
    const M = P.M.subarray(i * 9, i * 9 + 9), Rq = P.Rq.subarray(i * 9, i * 9 + 9);
    // вклад глубины в размер пятна: Σ2 зависит от J(p_c). dL/dT = 2·S2·T·Σ3, dL/dJ = dL/dT·Wᵀ
    {
      const S3 = _S3;
      for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) S3[a * 3 + b] = M[a * 3] * M[b * 3] + M[a * 3 + 1] * M[b * 3 + 1] + M[a * 3 + 2] * M[b * 3 + 2];
      const TS = _TS; // T·Σ3
      for (let r = 0; r < 2; r++) for (let b = 0; b < 3; b++) TS[r * 3 + b] = T[r * 3] * S3[b] + T[r * 3 + 1] * S3[3 + b] + T[r * 3 + 2] * S3[6 + b];
      const dT = _dT;
      for (let b = 0; b < 3; b++) { dT[b] = 2 * (s11 * TS[b] + s12 * TS[3 + b]); dT[3 + b] = 2 * (s12 * TS[b] + s22 * TS[3 + b]); }
      // T = J·W → dJ = dT·Wᵀ; нужны только j00 (0,0), j02 (0,2), j11 (1,1), j12 (1,2)
      const dJ = (r, c) => dT[r * 3] * R[c * 3] + dT[r * 3 + 1] * R[c * 3 + 1] + dT[r * 3 + 2] * R[c * 3 + 2];
      const d00 = dJ(0, 0), d02 = dJ(0, 2), d11 = dJ(1, 1), d12 = dJ(1, 2);
      const iz2 = iz * iz, iz3 = iz2 * iz;
      const ex = d02 * (-K.fx * iz2), ey = d12 * (-K.fy * iz2);
      const ez = d00 * (-K.fx * iz2) + d02 * (2 * K.fx * x * iz3) + d11 * (-K.fy * iz2) + d12 * (2 * K.fy * y * iz3);
      G.mu[i * 3] += R[0] * ex + R[3] * ey + R[6] * ez; G.mu[i * 3 + 1] += R[1] * ex + R[4] * ey + R[7] * ez; G.mu[i * 3 + 2] += R[2] * ex + R[5] * ey + R[8] * ez;
    }
    const dM = _dM;
    for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) dM[a * 3 + b] = 2 * (D[a * 3] * M[b] + D[a * 3 + 1] * M[3 + b] + D[a * 3 + 2] * M[6 + b]);
    const s = [Math.exp(S.ls[i * 3]), Math.exp(S.ls[i * 3 + 1]), Math.exp(S.ls[i * 3 + 2])];
    for (let k = 0; k < 3; k++) { const ds = dM[k] * Rq[k] + dM[3 + k] * Rq[3 + k] + dM[6 + k] * Rq[6 + k]; G.ls[i * 3 + k] += ds * s[k]; }
    // dRq = dM · diag(s)
    const dR = _dR; for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) dR[a * 3 + b] = dM[a * 3 + b] * s[b];
    const qw0 = S.q[i * 4], qx0 = S.q[i * 4 + 1], qy0 = S.q[i * 4 + 2], qz0 = S.q[i * 4 + 3], ql = Math.hypot(qw0, qx0, qy0, qz0) || 1;
    const w = qw0 / ql, qx = qx0 / ql, qy = qy0 / ql, qz = qz0 / ql;
    const gw = 2 * (-qz * dR[1] + qy * dR[2] + qz * dR[3] - qx * dR[5] - qy * dR[6] + qx * dR[7]);
    const gx = 2 * (qy * dR[1] + qz * dR[2] + qy * dR[3] - 2 * qx * dR[4] - w * dR[5] + qz * dR[6] + w * dR[7] - 2 * qx * dR[8]);
    const gy = 2 * (-2 * qy * dR[0] + qx * dR[1] + w * dR[2] + qx * dR[3] + qz * dR[5] - w * dR[6] + qz * dR[7] - 2 * qy * dR[8]);
    const gz = 2 * (-2 * qz * dR[0] - w * dR[1] + qx * dR[2] + w * dR[3] - 2 * qz * dR[4] + qy * dR[5] + qx * dR[6] + qy * dR[7]);
    const dot = w * gw + qx * gx + qy * gy + qz * gz;
    G.q[i * 4] += (gw - w * dot) / ql; G.q[i * 4 + 1] += (gx - qx * dot) / ql; G.q[i * 4 + 2] += (gy - qy * dot) / ql; G.q[i * 4 + 3] += (gz - qz * dot) / ql;
  }
}


// ---------- обучение ----------
export function makeGrad(n, nb = 4) { return { mu: new Float32Array(n * 3), ls: new Float32Array(n * 3), q: new Float32Array(n * 4), op: new Float32Array(n), sh: new Float32Array(n * 3 * nb), m2d: new Float32Array(n), cnt: new Float32Array(n), gain: [0, 0, 0] }; }

// Настройки по умолчанию подобраны на синтетических сценах (tests/tsplat.mjs, см. README)
// Подобрано на синтетике (tests/tsplat2.mjs, вертушка 72 кадра и обход с рук 36 кадров, PSNR на отложенных кадрах):
// глубинный регуляризатор в мм² почти бесполезен и при 0.02 стоил 2–3 дБ; гармоники 1-й степени +1 дБ к «одному цвету»;
// 2-я степень +0.6 дБ только при плотной съёмке (для «Лучше»); фон-медиана за листом на вертушке +2 дБ и втрое меньше облачков.
export const SPLAT_DEFAULTS = { deg: 1, alphaW: 0.2, depthW: 0.0003, flat: 0.1, expo: true, lrDC: 0.006, lrRest: 0.0012, lrGain: 0.004 };

export class Trainer {
  // views: [{K,R,t,x0,y0,cw,ch,img,bg,wt,at}]; inside(x,y,z) → можно ли капле быть здесь (рядом с оболочкой)
  constructor(S, views, opt = {}) {
    this.S = S; this.views = views; this.it = 0; this.iters = opt.iters || 1500; this.ext = opt.extent || 100;
    this.maxN = opt.maxN || 60000; this.inside = opt.inside || null;
    this.o = { ...SPLAT_DEFAULTS, ...opt };
    this.lr = { mu: 0.0016 * this.ext, ls: 0.005, q: 0.001, op: 0.05 };
    this.maxLs = Math.log(0.05 * this.ext); // капля не крупнее ~5% предмета
    this.flatL = this.o.flat < 1 ? Math.log(this.o.flat) : 0;
    this.resetAdam(); this.P = {}; this.seed = 7; this.seen = 0;
    this.losses = [];
    // поправки яркости кадров (лог-усиление по каналам) и их Adam
    const V = views.length; this.lg = new Float32Array(V * 3); this.mg = new Float32Array(V * 3); this.vg = new Float32Array(V * 3); this.tg = new Int32Array(V);
    for (const v of views) v.gain = [1, 1, 1];
  }
  resetAdam() {
    const n = this.S.cap, nb = this.S.nb;
    this.m = makeGrad(n, nb); this.v = makeGrad(n, nb); this.acc = { m2d: new Float32Array(n), cnt: new Float32Array(n) };
  }
  rnd() { this.seed = (this.seed * 1664525 + 1013904223) >>> 0; return this.seed / 4294967296; }
  // один шаг: B кадров (по умолчанию 1) → сумма градиентов → Adam. B > 1 — те же кадры можно считать в нескольких
  // потоках одновременно (SplatPool): шаг с пачкой из B кадров ≈ B обычных шагов по качеству, а по времени — один
  step() {
    const B = Math.min(this.o.batch || 1, this.views.length), picks = this.pick(B), G = this.gradBuf();
    const res = [];
    for (const vi of picks) {
      G.gain = [0, 0, 0];
      const r = renderView(this.S, this.views[vi], { grad: G, P: this.P, alphaW: this.o.alphaW, depthW: this.o.depthW });
      res.push({ vi, loss: r.loss, gain: G.gain });
    }
    return this.apply(G, res);
  }
  // B разных случайных кадров
  pick(B) {
    const V = this.views.length, out = [];
    while (out.length < B) { const vi = (this.rnd() * V) | 0; if (!out.includes(vi) || B > V) out.push(vi); }
    return out;
  }
  // буфер градиентов (обнуляется, а не создаётся заново каждый шаг — меньше работы сборщику мусора)
  gradBuf() {
    const S = this.S;
    if (!this.G || this.G.mu.length < S.cap * 3 || this.G.sh.length !== S.cap * 3 * S.nb) this.G = makeGrad(S.cap, S.nb);
    else { const n = S.n, G = this.G; G.mu.fill(0, 0, n * 3); G.ls.fill(0, 0, n * 3); G.q.fill(0, 0, n * 4); G.op.fill(0, 0, n); G.sh.fill(0, 0, n * 3 * S.nb); G.m2d.fill(0, 0, n); G.cnt.fill(0, 0, n); }
    return this.G;
  }
  // G — сумма градиентов по кадрам res = [{vi, loss, gain:[3]}]
  apply(G, res) {
    const S = this.S, n = S.n, nb = S.nb, B = res.length;
    if (this.m.mu.length < S.cap * 3) this.growAdam();
    let loss = 0; for (const r of res) loss += r.loss; loss /= B;
    this.losses.push(loss);
    const t = this.it / this.iters, lrMu = this.lr.mu * Math.pow(0.01, t); // позиция: экспоненциальное затухание
    const b1 = 0.9, b2 = 0.999, bc1 = 1 - Math.pow(b1, this.it + 1), bc2 = 1 - Math.pow(b2, this.it + 1), inv = 1 / B;
    const upd = (name, lr, lrRest, stride, k1) => {
      const p = S[name], g = G[name], m = this.m[name], v = this.v[name];
      for (let k = 0; k < k1; k++) {
        const gk = g[k] * inv; if (!gk) continue;
        m[k] = b1 * m[k] + (1 - b1) * gk; v[k] = b2 * v[k] + (1 - b2) * gk * gk;
        const l = stride && (k % stride) >= 3 ? lrRest : lr; // гармоники: «средний» цвет учится быстрее, чем зависимость от угла
        p[k] -= l * (m[k] / bc1) / (Math.sqrt(v[k] / bc2) + 1e-8);
      }
    };
    upd('mu', lrMu, 0, 0, n * 3); upd('ls', this.lr.ls, 0, 0, n * 3); upd('q', this.lr.q, 0, 0, n * 4); upd('op', this.lr.op, 0, 0, n); upd('sh', this.o.lrDC, this.o.lrRest, 3 * nb, n * 3 * nb);
    // поправка яркости кадров (Adam по лог-усилению); первые 10% шагов — без неё, пока цвет не сложился
    if (this.o.expo && this.it > this.iters * 0.1) {
      for (const { vi, gain } of res) {
        const view = this.views[vi], tg = ++this.tg[vi], c1 = 1 - Math.pow(b1, tg), c2 = 1 - Math.pow(b2, tg);
        for (let c = 0; c < 3; c++) {
          const k = vi * 3 + c, g = gain[c] * view.gain[c] + 0.002 * this.lg[k]; // + слабая тяга к 1
          this.mg[k] = b1 * this.mg[k] + (1 - b1) * g; this.vg[k] = b2 * this.vg[k] + (1 - b2) * g * g;
          this.lg[k] = Math.max(-0.5, Math.min(0.5, this.lg[k] - this.o.lrGain * (this.mg[k] / c1) / (Math.sqrt(this.vg[k] / c2) + 1e-8)));
        }
      }
      if (((this.seen + B) / 25 | 0) > (this.seen / 25 | 0)) { // общий множитель — у цветов капель, а не у кадров: среднее лог-усиление = 0
        for (let c = 0; c < 3; c++) { let s = 0; for (let k = 0; k < this.views.length; k++) s += this.lg[k * 3 + c]; s /= this.views.length; for (let k = 0; k < this.views.length; k++) this.lg[k * 3 + c] -= s; }
      }
      for (let k = 0; k < this.views.length; k++) for (let c = 0; c < 3; c++) this.views[k].gain[c] = Math.exp(this.lg[k * 3 + c]);
    }
    for (let i = 0; i < n; i++) {
      this.acc.m2d[i] += G.m2d[i]; this.acc.cnt[i] += G.cnt[i];
      for (let c = 0; c < 3; c++) if (S.ls[i * 3 + c] > this.maxLs) S.ls[i * 3 + c] = this.maxLs;
      // плоская капля (диск): третья ось — нормаль, не толще flat × меньшего из двух радиусов
      if (this.flatL) { const lim = Math.min(S.ls[i * 3], S.ls[i * 3 + 1]) + this.flatL; if (S.ls[i * 3 + 2] > lim) S.ls[i * 3 + 2] = lim; }
    }
    this.it++;
    // уплотнение и чистка — по числу просмотренных кадров (каждые 100), а не шагов: с пачкой кадров расписание то же
    const s0 = this.seen, s1 = (this.seen += B), cross = (P) => ((s1 / P) | 0) > ((s0 / P) | 0);
    if (cross(100) && s1 >= 200 && this.it <= this.iters * 0.65) this.densify();
    if (cross(100)) this.prune();
    return loss;
  }
  // в конце: строгая чистка (fn — более жёсткое правило «где можно жить») и выкидываем почти прозрачные
  finalize(fn) { if (fn) this.inside = fn; this.prune(); }
  growAdam() {
    const n = this.S.cap, nb = this.S.nb, grow = (o, k) => { const a = new Float32Array(n * k); a.set(o.subarray(0, Math.min(o.length, n * k))); return a; };
    for (const X of [this.m, this.v]) { X.mu = grow(X.mu, 3); X.ls = grow(X.ls, 3); X.q = grow(X.q, 4); X.op = grow(X.op, 1); X.sh = grow(X.sh, 3 * nb); }
    this.acc.m2d = grow(this.acc.m2d, 1); this.acc.cnt = grow(this.acc.cnt, 1);
  }
  densify() {
    const S = this.S, n = S.n, nb3 = 3 * S.nb;
    if (n >= this.maxN) { this.acc.m2d.fill(0); this.acc.cnt.fill(0); return; }
    const avg = []; for (let i = 0; i < n; i++) if (this.acc.cnt[i] > 0) avg.push([this.acc.m2d[i] / this.acc.cnt[i], i]);
    avg.sort((a, b) => b[0] - a[0]);
    const take = Math.min(Math.floor(n * 0.08), this.maxN - n, avg.length);
    const big = Math.log(0.012 * this.ext);
    for (let k = 0; k < take; k++) {
      const i = avg[k][1];
      const mu = [S.mu[i * 3], S.mu[i * 3 + 1], S.mu[i * 3 + 2]], ls = [S.ls[i * 3], S.ls[i * 3 + 1], S.ls[i * 3 + 2]], q = [...S.q.subarray(i * 4, i * 4 + 4)];
      const sh = S.sh.slice(i * nb3, (i + 1) * nb3), op = S.op[i];
      if (Math.max(...ls) > big) { // крупная — делим на две
        const R = new Float32Array(9); quatToR(q[0], q[1], q[2], q[3], R);
        const ax = ls.indexOf(Math.max(...ls)), s = Math.exp(ls[ax]) * 0.6;
        const d = [R[ax] * s, R[3 + ax] * s, R[6 + ax] * s];
        const nl = ls.map(v => v - Math.log(1.6));
        S.mu.set([mu[0] + d[0], mu[1] + d[1], mu[2] + d[2]], i * 3); S.ls.set(nl, i * 3);
        S.push([mu[0] - d[0], mu[1] - d[1], mu[2] - d[2]], nl, q, op, sh);
      } else S.push(mu, ls, q, op, sh); // мелкая — клон
    }
    this.acc.m2d.fill(0); this.acc.cnt.fill(0);
  }
  prune() {
    const S = this.S, nb3 = 3 * S.nb;
    const keepIdx = [];
    for (let i = 0; i < S.n; i++) {
      const o = sig(S.op[i]);
      if (o < 0.02) continue;
      if (this.inside && !this.inside(S.mu[i * 3], S.mu[i * 3 + 1], S.mu[i * 3 + 2])) continue;
      keepIdx.push(i);
    }
    if (keepIdx.length === S.n) return;
    const mv = (arr, k) => { for (let j = 0; j < keepIdx.length; j++) { const i = keepIdx[j]; if (i !== j) for (let c = 0; c < k; c++) arr[j * k + c] = arr[i * k + c]; } };
    for (const [name, k] of [['mu', 3], ['ls', 3], ['q', 4], ['op', 1], ['sh', nb3]]) { mv(S[name], k); mv(this.m[name], k); mv(this.v[name], k); }
    mv(this.acc.m2d, 1); mv(this.acc.cnt, 1);
    const w = keepIdx.length;
    for (const X of [this.m, this.v]) { X.mu.fill(0, w * 3, S.n * 3); X.ls.fill(0, w * 3, S.n * 3); X.q.fill(0, w * 4, S.n * 4); X.op.fill(0, w, S.n); X.sh.fill(0, w * nb3, S.n * nb3); }
    S.n = w;
  }
}

// начальные капли — точки на поверхности сетки, плоские вдоль поверхности (третья ось — по нормали)
export function initFromMesh(M, maxN = 8000, deg = SPLAT_DEFAULTS.deg) {
  const nv = M.pos.length / 3, step = Math.max(1, Math.floor(nv / maxN));
  // средняя длина ребра — для начального размера
  let el = 0, ec = 0; for (let i = 0; i < Math.min(M.idx.length, 30000); i += 3) { const a = M.idx[i] * 3, b = M.idx[i + 1] * 3; el += Math.hypot(M.pos[a] - M.pos[b], M.pos[a + 1] - M.pos[b + 1], M.pos[a + 2] - M.pos[b + 2]); ec++; }
  el /= Math.max(1, ec);
  const S = new Splats(Math.ceil(nv / step) + 16, deg);
  const r = Math.log(Math.max(0.3, el * Math.sqrt(step) * 0.75)), rn = r + Math.log(0.1);
  const logit = (p) => Math.log(p / (1 - p));
  for (let v = 0; v < nv; v += step) {
    const n = [M.nrm[v * 3], M.nrm[v * 3 + 1], M.nrm[v * 3 + 2]];
    // поворот (0,0,1) → n
    const dz = n[2], cx = -n[1], cy = n[0]; // ось = z × n
    let q = [1 + dz, cx, cy, 0]; const ql = Math.hypot(...q); q = ql < 1e-6 ? [0, 1, 0, 0] : q.map(x => x / ql);
    const c = [0, 1, 2].map(k => Math.min(0.97, Math.max(0.03, M.col[v * 3 + k] / 255)));
    S.push([M.pos[v * 3], M.pos[v * 3 + 1], M.pos[v * 3 + 2]], [r, r, rn], q, logit(0.6), c);
  }
  return S;
}

// ---------- упаковка для хранения и просмотра ----------
// v2: заголовок [PACK_MAGIC, 2, deg, n], затем на каплю: центр(3) logScale(3) quat(4) opacity цвет(3) + гармоники 1..nb−1 [k][канал].
// Старый формат (до 1.9): 14 чисел на каплю без заголовка.
const PACK_MAGIC = -77777;
export function splatInfo(p) {
  if (p && p.length >= 4 && p[0] === PACK_MAGIC) { const deg = p[2], nb = (deg + 1) * (deg + 1), stride = 14 + 3 * (nb - 1); return { off: 4, deg, nb, stride, n: p[3] }; }
  return { off: 0, deg: 0, nb: 1, stride: 14, n: p ? p.length / 14 : 0 };
}
export function packSplats(S) {
  const nb = S.nb, nb3 = 3 * nb, stride = 14 + 3 * (nb - 1), out = new Float32Array(4 + S.n * stride);
  out[0] = PACK_MAGIC; out[1] = 2; out[2] = S.deg; out[3] = S.n;
  for (let i = 0; i < S.n; i++) {
    const o = 4 + i * stride;
    out.set(S.mu.subarray(i * 3, i * 3 + 3), o); out.set(S.ls.subarray(i * 3, i * 3 + 3), o + 3);
    const q = S.q.subarray(i * 4, i * 4 + 4), l = Math.hypot(...q) || 1; for (let c = 0; c < 4; c++) out[o + 6 + c] = q[c] / l;
    out[o + 10] = sig(S.op[i]); for (let c = 0; c < 3; c++) out[o + 11 + c] = S.baseColor(i, c);
    for (let k = 1; k < nb; k++) for (let c = 0; c < 3; c++) out[o + 14 + (k - 1) * 3 + c] = S.sh[i * nb3 + k * 3 + c];
  }
  return out;
}
// масштаб (поправка печати коврика): центры × (sx,sy,sz), радиусы × среднее
export function scalePacked(p, sx, sy, sz) {
  const I = splatInfo(p), ls = Math.log(Math.cbrt(sx * sy * sz));
  for (let i = 0; i < I.n; i++) { const o = I.off + i * I.stride; p[o] *= sx; p[o + 1] *= sy; p[o + 2] *= sz; p[o + 3] += ls; p[o + 4] += ls; p[o + 5] += ls; }
}

// экспорт в стандартный PLY 3DGS (читают SuperSplat, Brush, аддоны Blender). Единицы — метры, Z вверх.
// Нормали — ось диска (плоские капли); гармоники — f_rest_* по каналам, как в 3DGS.
export function plyFromPacked(p) {
  const I = splatInfo(p), nr = I.nb - 1;
  const props = ['x', 'y', 'z', 'nx', 'ny', 'nz', 'f_dc_0', 'f_dc_1', 'f_dc_2'];
  for (let k = 0; k < 3 * nr; k++) props.push(`f_rest_${k}`);
  props.push('opacity', 'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3');
  const head = `ply\nformat binary_little_endian 1.0\ncomment Obyom 3D scanner\nelement vertex ${I.n}\n` + props.map(q => `property float ${q}`).join('\n') + '\nend_header\n';
  const hb = new TextEncoder().encode(head), buf = new ArrayBuffer(hb.length + I.n * props.length * 4), dv = new DataView(buf);
  new Uint8Array(buf).set(hb);
  let o = hb.length; const mm = 0.001, logit = (x) => { const v = Math.max(1e-4, Math.min(0.9999, x)); return Math.log(v / (1 - v)); };
  const f = (v) => { dv.setFloat32(o, v, true); o += 4; };
  for (let i = 0; i < I.n; i++) {
    const b = I.off + i * I.stride;
    const [w, x, y, z] = [p[b + 6], p[b + 7], p[b + 8], p[b + 9]];
    f(p[b] * mm); f(p[b + 1] * mm); f(p[b + 2] * mm);
    f(2 * (x * z + w * y)); f(2 * (y * z - w * x)); f(1 - 2 * (x * x + y * y)); // третий столбец поворота
    for (let c = 0; c < 3; c++) f((p[b + 11 + c] - 0.5) / SH_C0);
    for (let c = 0; c < 3; c++) for (let k = 0; k < nr; k++) f(p[b + 14 + k * 3 + c]);
    f(logit(p[b + 10]));
    for (let c = 0; c < 3; c++) f(p[b + 3 + c] + Math.log(mm));
    for (let c = 0; c < 4; c++) f(p[b + 6 + c]);
  }
  return buf;
}
// для тестов: прямо из капель
export function toPLY(S) { return plyFromPacked(packSplats(S)); }

// ---------- подготовка кадров для обучения ----------
// frames: [{w,h,rgba,K,R,t,mask}], M — сетка оболочки, G — воксели (для «можно ли капле быть здесь»)
export function splatViews(M, frames, depthMap, opt = {}) {
  const views = [];
  for (const f of frames) {
    const { w, h } = f, zb = depthMap(M, f, w, h);
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (zb[y * w + x] < 1e8) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    if (x1 < 0) continue;
    const m = opt.margin ?? 6; x0 = Math.max(0, x0 - m); y0 = Math.max(0, y0 - m); x1 = Math.min(w - 1, x1 + m); y1 = Math.min(h - 1, y1 + m);
    const cw = x1 - x0 + 1, ch = y1 - y0 + 1, n = cw * ch;
    const img = new Float32Array(n * 3), bg = new Float32Array(n * 3), wt = new Float32Array(n), at = new Int8Array(n).fill(-1);
    // v2.2: «далеко от оболочки» — оболочка всегда объемлет предмет, значит там, куда она не проецируется (с запасом
    // ~2 мм, как и область жизни капель), предмета точно нет: требуем прозрачность, даже если маска не уверена
    // (стена за листом, тень). Иначе крайние капли рисуют «дымку» под цвет стены — облачка над предметом.
    let far = null;
    if (opt.farHull !== false) {
      const zc = (() => { let s = 0, c = 0; for (let i = 0; i < zb.length; i += 7) if (zb[i] < 1e8) { s += zb[i]; c++; } return c ? s / c : 300; })();
      const r = Math.max(2, Math.ceil((opt.farPad ?? 2.5) * f.K.fx / zc));
      far = new Uint8Array(n).fill(1);
      const rowD = new Int32Array(n).fill(1 << 20); // расстояние по строке до пикселя оболочки (два прохода), затем по столбцу
      for (let y = 0; y < ch; y++) {
        let d = 1 << 20; for (let x = 0; x < cw; x++) { d = zb[(y + y0) * w + x + x0] < 1e8 ? 0 : d + 1; rowD[y * cw + x] = d; }
        d = 1 << 20; for (let x = cw - 1; x >= 0; x--) { d = zb[(y + y0) * w + x + x0] < 1e8 ? 0 : d + 1; if (d < rowD[y * cw + x]) rowD[y * cw + x] = d; }
      }
      for (let x = 0; x < cw; x++) for (let y = 0; y < ch; y++) {
        if (rowD[y * cw + x] > r) continue;
        for (let yy = Math.max(0, y - r); yy <= Math.min(ch - 1, y + r); yy++) far[yy * cw + x] = 0; // квадратная окрестность r — с запасом
      }
    }
    for (let y = 0; y < ch; y++) for (let x = 0; x < cw; x++) {
      const j = y * cw + x, gi = (y + y0) * w + x + x0;
      for (let c = 0; c < 3; c++) img[j * 3 + c] = f.rgba[gi * 4 + c] / 255;
      const isBg = f.mask ? f.mask[gi] === 0 : zb[gi] > 1e8, unk = f.mask && (f.mask[gi] === 1 || f.mask[gi] === 3);
      for (let c = 0; c < 3; c++) bg[j * 3 + c] = isBg ? img[j * 3 + c] : 0.5;
      // неуверенные пиксели (тень, блики коврика) почти не учитываем — иначе капли «рисуют» тень вокруг предмета
      wt[j] = unk ? (opt.unkW ?? 0.15) : 1; // 3 — слабый фон за листом
      // вертушка: за листом известен фон — медиана кадров с этого места (предмет крутится, стена стоит)
      if (unk && f.bgMed && opt.medW !== 0) { const gn = f.bgGain || 1; for (let c = 0; c < 3; c++) bg[j * 3 + c] = Math.min(1, gn * f.bgMed[gi * 3 + c] / 255); wt[j] = opt.medW ?? 1; }
      // цель прозрачности: уверенный фон — капель нет (0); уверенный предмет внутри оболочки — сплошь (1); прочее — без цели
      if (f.mask) at[j] = f.mask[gi] === 0 ? 0 : f.mask[gi] === 2 && zb[gi] < 1e8 ? 1 : -1;
      if (far && far[j] && at[j] < 0 && !(f.mask && f.mask[gi] === 2)) at[j] = 0;
    }
    views.push({ K: f.K, R: f.R, t: f.t, x0, y0, cw, ch, img, bg, wt, at, src: f });
  }
  return views;
}
// «рядом с оболочкой»: воксели, расширенные на pad мм
export function nearHull(G, pad = 3) {
  const { occ, nx, ny, nz, vs, origin } = G, k = Math.max(1, Math.ceil(pad / vs));
  let a = new Uint8Array(nx * ny * nz); for (let i = 0; i < a.length; i++) a[i] = occ[i] > 0.5 ? 1 : 0;
  const dil = (src, stride, len, dimIdx) => {
    const out = new Uint8Array(src.length);
    for (let i = 0; i < src.length; i++) {
      if (!src[i]) continue;
      const c = dimIdx(i);
      for (let d = -k; d <= k; d++) { const cc = c + d; if (cc >= 0 && cc < len) out[i + d * stride] = 1; }
    }
    return out;
  };
  a = dil(a, 1, nx, i => i % nx); a = dil(a, nx, ny, i => ((i / nx) | 0) % ny); a = dil(a, nx * ny, nz, i => (i / (nx * ny)) | 0);
  return (X, Y, Z) => {
    const x = Math.round((X - origin[0]) / vs), y = Math.round((Y - origin[1]) / vs), z = Math.round((Z - origin[2]) / vs);
    if (x < 0 || y < 0 || x >= nx || y >= ny) return false;
    if (z < 0) return Z > -pad; if (z >= nz) return false;
    return a[(z * ny + y) * nx + x] === 1;
  };
}
// Где капле можно жить: рядом с оболочкой, выше коврика и не на «уверенном фоне» (маска 0) в ≥2 кадрах
// Можно ли капле быть в точке: то же правило, что и для вырезания сетки (доля кадров, а не «любые два»),
// иначе сплэты обрезаются сильнее сетки.
export function allowedRegion(G, frames, pad = 2, frac = 0.08) {
  const near = nearHull(G, pad), few = frames.length < 8;
  return (X, Y, Z) => {
    if (Z < 0.4 || !near(X, Y, Z)) return false;
    let bg = 0, weak = 0, seen = 0;
    for (const f of frames) {
      const R = f.R, t = f.t, K = f.K, cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) continue;
      const u = (K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx) | 0, v = (K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy) | 0;
      if (u < 0 || v < 0 || u >= f.w || v >= f.h) continue;
      seen++; const mv = f.mask[v * f.w + u]; if (mv === 0) bg++; else if (mv === 3) weak++;
    }
    return !carveVote(bg, weak, seen, frac, few);
  };
}
