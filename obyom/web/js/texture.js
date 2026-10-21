// Объём — отдельная текстура (атлас). Цвет поверхности берётся не из вершин (≈1 мм), а прямо из пикселей кадров
// в полном разрешении. Без нейросетей — классическая схема фотограмметрии:
//  1) каждому треугольнику — лучший кадр: где он крупнее всего (видно больше пикселей), не заслонён, кадр резкий,
//     и в этом кадре на его месте действительно предмет, а не фон (маска);
//  2) сглаживание выбора: соседние треугольники стараются брать один и тот же кадр — меньше швов;
//  3) связные куски с одним кадром — «лоскуты»; каждый лоскут — прямоугольник из своего кадра, укладка в атлас;
//  4) яркость лоскутов подгоняется к среднему цвету по всем кадрам (разная экспозиция → швы почти не видны).
import { depthMap } from './recon.js';

// Длинные рёбра (коробка, призма, плоские грани: огромные треугольники) — делим: лоскут должен влезать в один кадр.
export function subdivideLong(M, maxE = 8, maxPass = 8) {
  let pos = Array.from(M.pos), nrm = Array.from(M.nrm), col = M.col ? Array.from(M.col) : null, idx = Array.from(M.idx);
  for (let pass = 0; pass < maxPass; pass++) {
    const mid = new Map(), L2 = maxE * maxE;
    const len2 = (a, b) => (pos[a * 3] - pos[b * 3]) ** 2 + (pos[a * 3 + 1] - pos[b * 3 + 1]) ** 2 + (pos[a * 3 + 2] - pos[b * 3 + 2]) ** 2;
    const key = (a, b) => (a < b ? a * 4194304 + b : b * 4194304 + a);
    let any = false;
    for (let i = 0; i < idx.length; i += 3) for (let e = 0; e < 3; e++) { const a = idx[i + e], b = idx[i + (e + 1) % 3]; if (len2(a, b) > L2) { mid.set(key(a, b), -1); any = true; } }
    if (!any) break;
    const m = (a, b) => {
      const k = key(a, b); let v = mid.get(k); if (v === undefined) return -1;
      if (v < 0) {
        v = pos.length / 3; mid.set(k, v);
        for (let c = 0; c < 3; c++) { pos.push((pos[a * 3 + c] + pos[b * 3 + c]) / 2); nrm.push((nrm[a * 3 + c] + nrm[b * 3 + c]) / 2); if (col) col.push(Math.round((col[a * 3 + c] + col[b * 3 + c]) / 2)); }
      }
      return v;
    };
    const out = [];
    for (let i = 0; i < idx.length; i += 3) {
      const a = idx[i], b = idx[i + 1], c = idx[i + 2], ab = m(a, b), bc = m(b, c), ca = m(c, a);
      const n = (ab >= 0) + (bc >= 0) + (ca >= 0);
      if (!n) out.push(a, b, c);
      else if (n === 3) out.push(a, ab, ca, ab, b, bc, ca, bc, c, ab, bc, ca);
      else if (n === 1) { if (ab >= 0) out.push(a, ab, c, ab, b, c); else if (bc >= 0) out.push(a, b, bc, a, bc, c); else out.push(a, b, ca, ca, b, c); }
      else { // два ребра: «полоса» из трёх треугольников
        if (ab < 0) out.push(a, b, bc, a, bc, ca, ca, bc, c);
        else if (bc < 0) out.push(a, ab, ca, ab, b, c, ab, c, ca);
        else out.push(a, ab, bc, a, bc, c, ab, b, bc);
      }
    }
    idx = out;
  }
  for (let v = 0; v < nrm.length; v += 3) { const l = Math.hypot(nrm[v], nrm[v + 1], nrm[v + 2]) || 1; nrm[v] /= l; nrm[v + 1] /= l; nrm[v + 2] /= l; }
  return { pos: new Float32Array(pos), nrm: new Float32Array(nrm), col: col ? new Uint8Array(col) : null, idx: new Uint32Array(idx) };
}

// резкость кадра: средний модуль лапласиана там, где маска говорит «предмет»
function frameSharp(f) {
  const { w, h, rgba, mask } = f; let s = 0, n = 0;
  const g = (i) => 0.299 * rgba[i * 4] + 0.587 * rgba[i * 4 + 1] + 0.114 * rgba[i * 4 + 2];
  for (let y = 2; y < h - 2; y += 2) for (let x = 2; x < w - 2; x += 2) {
    const i = y * w + x; if (mask && (mask[i] === 0 || mask[i] === 3)) continue;
    s += Math.abs(4 * g(i) - g(i - 1) - g(i + 1) - g(i - w) - g(i + w)); n++;
  }
  return n > 50 ? s / n : 0;
}

// frames: [{w,h,K,R,t,rgba,mask?,blob,srcW,srcH,close?}] (K — в пикселях w×h); M: {pos,nrm,col,idx}
// opt: {size — наибольший атлас, decode(blob) → {rgba,w,h} в полном размере, encode(rgba,T) → Uint8Array (JPEG), onProgress}
export async function bakeTexture(M, frames, opt = {}) {
  const T0 = opt.size || 2048, prog = opt.onProgress || (() => {}), tick = () => new Promise((r) => setTimeout(r, 0));
  const { pos, idx } = M, nt = idx.length / 3, nv = pos.length / 3;
  // нормали и центры граней
  const fn = new Float32Array(nt * 3), fc = new Float32Array(nt * 3);
  for (let i = 0; i < nt; i++) {
    const a = idx[i * 3] * 3, b = idx[i * 3 + 1] * 3, c = idx[i * 3 + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2], vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx; const l = Math.hypot(nx, ny, nz) || 1;
    fn[i * 3] = nx / l; fn[i * 3 + 1] = ny / l; fn[i * 3 + 2] = nz / l;
    for (let k = 0; k < 3; k++) fc[i * 3 + k] = (pos[a + k] + pos[b + k] + pos[c + k]) / 3;
  }
  // качество кадров: резкость относительно медианы, точность позы
  const sh = frames.map(frameSharp), shs = sh.filter((v) => v > 0).sort((a, b) => a - b), shm = shs.length ? shs[shs.length >> 1] : 1;
  const q = frames.map((f, i) => Math.max(0.3, Math.min(1.5, (sh[i] > 0 ? sh[i] / shm : 1) ** 1.5)) / (1 + Math.max(0, (f.rms || 0) - 1)));
  // 1) кандидаты: до TOP лучших кадров на грань
  const pc = opt.consist ?? 22;
  const smp = (f, x, y, c) => { const w = f.w, x0 = Math.max(0, Math.min(w - 2, x | 0)), y0 = Math.max(0, Math.min(f.h - 2, y | 0)), fx = Math.min(1, Math.max(0, x - x0)), fy = Math.min(1, Math.max(0, y - y0)), i = (y0 * w + x0) * 4, s = w * 4, p = f.rgba; return (p[i + c] * (1 - fx) + p[i + 4 + c] * fx) * (1 - fy) + (p[i + s + c] * (1 - fx) + p[i + s + 4 + c] * fx) * fy; };
  const TOP = opt.top || 12, cL = new Int16Array(nt * TOP).fill(-1), cS = new Float32Array(nt * TOP);
  const P = new Float32Array(nv * 3);
  for (let fi = 0; fi < frames.length; fi++) {
    const f = frames[fi], { w, h, K, R, t } = f, s = (f.srcW || w) / w;
    const dw = Math.min(400, w), dh = Math.round(h * dw / w), zb = depthMap(M, f, dw, dh);
    const C = [-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])];
    for (let v = 0; v < nv; v++) {
      const X = pos[v * 3], Y = pos[v * 3 + 1], Z = pos[v * 3 + 2], cz = R[6] * X + R[7] * Y + R[8] * Z + t[2];
      P[v * 3 + 2] = cz; if (cz <= 1) continue;
      P[v * 3] = K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx; P[v * 3 + 1] = K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy;
    }
    const vis = (u, vv, cz) => { const du = Math.min(dw - 1, Math.max(0, (u * dw / w) | 0)), dv = Math.min(dh - 1, Math.max(0, (vv * dh / h) | 0)); let zm = 1e9; for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) { const x = du + a, y = dv + b; if (x >= 0 && y >= 0 && x < dw && y < dh) zm = Math.min(zm, zb[y * dw + x]); } return cz <= zm * 1.004 + 1.5; };
    for (let i = 0; i < nt; i++) {
      const a = idx[i * 3], b = idx[i * 3 + 1], c = idx[i * 3 + 2];
      let ok = true; for (const v of [a, b, c]) { const u = P[v * 3], vv = P[v * 3 + 1]; if (P[v * 3 + 2] <= 1 || u < 2 || vv < 2 || u > w - 3 || vv > h - 3) { ok = false; break; } }
      if (!ok) continue;
      let dx = C[0] - fc[i * 3], dy = C[1] - fc[i * 3 + 1], dz = C[2] - fc[i * 3 + 2]; const dl = Math.hypot(dx, dy, dz);
      const cosA = (dx * fn[i * 3] + dy * fn[i * 3 + 1] + dz * fn[i * 3 + 2]) / dl; if (cosA < 0.2) continue;
      const X = fc[i * 3], Y = fc[i * 3 + 1], Z = fc[i * 3 + 2], cz = R[6] * X + R[7] * Y + R[8] * Z + t[2];
      const u = K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx, vv = K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy;
      if (!vis(u, vv, cz)) continue;
      let nvis = 0; for (const v of [a, b, c]) if (vis(P[v * 3], P[v * 3 + 1], P[v * 3 + 2])) nvis++;
      if (nvis < 2) continue;
      const area = Math.abs((P[b * 3] - P[a * 3]) * (P[c * 3 + 1] - P[a * 3 + 1]) - (P[c * 3] - P[a * 3]) * (P[b * 3 + 1] - P[a * 3 + 1])) / 2 * s * s;
      let sc = (area + 0.05) * q[fi] * (0.5 + 0.5 * cosA);
      if (f.mask) { const mv = f.mask[(vv | 0) * w + (u | 0)]; if (mv === 0 || mv === 3) sc *= 0.03; } // в этом кадре здесь фон: оболочка шире предмета
      // согласие с другими кадрами: цвет грани в этом кадре против среднего по всем (M.col). Где форма неточна
      // (впадины, «юбка» оболочки), разные кадры видят на грани разное — берём тот, что согласен с большинством.
      if (M.col && f.rgba && pc > 0) {
        let d = 0;
        for (let ch = 0; ch < 3; ch++) { const mc = (M.col[a * 3 + ch] + M.col[b * 3 + ch] + M.col[c * 3 + ch]) / 3; const sm = (smp(f, u, vv, ch) * 2 + smp(f, P[a * 3], P[a * 3 + 1], ch) + smp(f, P[b * 3], P[b * 3 + 1], ch) + smp(f, P[c * 3], P[c * 3 + 1], ch)) / 5; d += Math.abs(sm - mc); }
        d /= 3; sc /= 1 + (d / pc) ** 2;
      }
      // вставка в список лучших
      const o = i * TOP; if (cL[o + TOP - 1] >= 0 && sc <= cS[o + TOP - 1]) continue;
      let k = TOP - 1; while (k > 0 && (cL[o + k - 1] < 0 || cS[o + k - 1] < sc)) { cL[o + k] = cL[o + k - 1]; cS[o + k] = cS[o + k - 1]; k--; }
      cL[o + k] = fi; cS[o + k] = sc;
    }
    prog(0.45 * (fi + 1) / frames.length, 'выбираю кадры');
    if (fi % 4 === 3) await tick();
  }
  // 2) соседи граней (по рёбрам) и сглаживание выбора (ICM)
  const nb = new Int32Array(nt * 3).fill(-1), em = new Map();
  for (let i = 0; i < nt; i++) for (let e = 0; e < 3; e++) {
    const a = idx[i * 3 + e], b = idx[i * 3 + (e + 1) % 3], k = a < b ? a * nv + b : b * nv + a, j = em.get(k);
    if (j === undefined) em.set(k, i * 3 + e); else { nb[i * 3 + e] = (j / 3) | 0; nb[j] = i; em.delete(k); }
  }
  const lab = new Int32Array(nt); for (let i = 0; i < nt; i++) lab[i] = cL[i * TOP];
  const lam = opt.smooth ?? 0.45;
  for (let it = 0; it < 8; it++) {
    let ch = 0;
    for (let i = 0; i < nt; i++) {
      const o = i * TOP; if (cL[o] < 0) continue;
      let best = lab[i], bestE = Infinity;
      for (let k = 0; k < TOP && cL[o + k] >= 0; k++) {
        const l = cL[o + k]; let E = 1 - cS[o + k] / cS[o];
        for (let e = 0; e < 3; e++) { const j = nb[i * 3 + e]; if (j >= 0 && lab[j] >= 0 && lab[j] !== l) E += lam; }
        if (E < bestE - 1e-9) { bestE = E; best = l; }
      }
      if (best !== lab[i]) { lab[i] = best; ch++; }
    }
    if (opt.debug) console.log('ICM', it, ch);
    if (!ch) break;
  }
  if (opt.debug) { let k = 0, d = 0; for (let i = 0; i < nt * 3; i++) if (nb[i] >= 0) { k++; if (lab[nb[i]] !== lab[(i / 3) | 0]) d++; } console.log('соседей', (k / (nt * 3)).toFixed(3), 'разных меток', (d / k).toFixed(3)); }
  await tick();
  // 3) лоскуты: связные куски с одним кадром
  const chart = new Int32Array(nt).fill(-1), charts = [];
  const stack = new Int32Array(nt);
  for (let i = 0; i < nt; i++) {
    if (chart[i] >= 0 || lab[i] < 0) continue;
    const id = charts.length, faces = []; let sp = 0; stack[sp++] = i; chart[i] = id;
    while (sp) { const j = stack[--sp]; faces.push(j); for (let e = 0; e < 3; e++) { const q2 = nb[j * 3 + e]; if (q2 >= 0 && chart[q2] < 0 && lab[q2] === lab[i]) { chart[q2] = id; stack[sp++] = q2; } } }
    charts.push({ fi: lab[i], faces });
  }
  // проекции вершин лоскута в его кадре (пиксели полного кадра) и рамка
  const pad = 2;
  const projSrc = (f, v) => { const { K, R, t } = f, s = (f.srcW || f.w) / f.w, X = pos[v * 3], Y = pos[v * 3 + 1], Z = pos[v * 3 + 2], cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; return [(K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx) * s, (K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy) * s]; };
  for (const c of charts) {
    const f = frames[c.fi]; let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const i of c.faces) for (let e = 0; e < 3; e++) { const [u, v] = projSrc(f, idx[i * 3 + e]); x0 = Math.min(x0, u); y0 = Math.min(y0, v); x1 = Math.max(x1, u); y1 = Math.max(y1, v); }
    c.bx = Math.floor(x0) - pad; c.by = Math.floor(y0) - pad; c.bw = Math.ceil(x1) + pad - c.bx; c.bh = Math.ceil(y1) + pad - c.by;
  }
  // грани, которые не видел ни один кадр (дно и т. п.): по текселю на грань, цвет — из вершин
  const unseen = []; for (let i = 0; i < nt; i++) if (lab[i] < 0) unseen.push(i);
  const us = unseen.length ? Math.ceil(Math.sqrt(unseen.length)) : 0;
  // 4) укладка в атлас (полки), масштаб σ ≤ 1 — не растягиваем кадр
  const G = 2; // поле вокруг лоскута в атласе — против просачивания соседей при фильтрации
  const rects = charts.map((c) => ({ c, w: 0, h: 0, x: 0, y: 0 }));
  if (us) rects.push({ c: null, w: 0, h: 0, x: 0, y: 0 });
  const order = rects.map((_, i) => i);
  const tryPack = (T, sg) => {
    for (const r of rects) { if (r.c) { r.w = Math.ceil(r.c.bw * sg) + 2 * G; r.h = Math.ceil(r.c.bh * sg) + 2 * G; } else { r.w = us + 2 * G; r.h = us + 2 * G; } if (r.w > T || r.h > T) return false; }
    order.sort((a, b) => rects[b].h - rects[a].h);
    let x = 0, y = 0, shH = 0;
    for (const k of order) { const r = rects[k]; if (x + r.w > T) { y += shH; x = 0; shH = 0; } if (y + r.h > T) return false; r.x = x; r.y = y; x += r.w; shH = Math.max(shH, r.h); }
    return true;
  };
  let srcArea = 0; for (const c of charts) srcArea += c.bw * c.bh;
  let T = T0, sg = Math.min(1, Math.sqrt(0.8 * T * T / Math.max(1, srcArea)));
  while (!tryPack(T, sg)) { sg *= 0.92; if (sg < 0.02) throw new Error('текстура не уложилась'); }
  if (sg >= 0.999) while (T > 512 && tryPack(T / 2, 1)) T /= 2; // всё влезает в меньший атлас без потери детали
  tryPack(T, sg);
  prog(0.55, `атлас ${T}×${T}, лоскутов ${charts.length}`);
  await tick();
  // 5) выравнивание яркости лоскутов к среднему цвету (M.col — среднее по всем кадрам)
  const sample = (f, x, y, c) => { const w = f.w, x0 = Math.max(0, Math.min(w - 2, x | 0)), y0 = Math.max(0, Math.min(f.h - 2, y | 0)), fx = Math.min(1, Math.max(0, x - x0)), fy = Math.min(1, Math.max(0, y - y0)), i = (y0 * w + x0) * 4, s = w * 4, p = f.rgba; return (p[i + c] * (1 - fx) + p[i + 4 + c] * fx) * (1 - fy) + (p[i + s + c] * (1 - fx) + p[i + s + 4 + c] * fx) * fy; };
  for (const c of charts) {
    const f = frames[c.fi], seen = new Set(); const st = [0, 0, 0], ss = [0, 0, 0]; let n = 0;
    if (!M.col || !f.rgba) { c.g = [1, 1, 1]; continue; }
    for (const i of c.faces) for (let e = 0; e < 3; e++) {
      const v = idx[i * 3 + e]; if (seen.has(v)) continue; seen.add(v);
      const s = (f.srcW || f.w) / f.w, [u, vv] = projSrc(f, v);
      for (let ch = 0; ch < 3; ch++) { st[ch] += M.col[v * 3 + ch]; ss[ch] += sample(f, u / s, vv / s, ch); } n++;
    }
    const k = 20; // «псевдосчёт»: у маленьких лоскутов поправка стремится к 1
    c.g = [0, 1, 2].map((ch) => { const m = ss[ch] / Math.max(1, n); return Math.max(0.67, Math.min(1.5, (st[ch] + k * m) / (ss[ch] + k * m + 1e-6))); });
  }
  // 6) заполнение атласа: по кадру за раз (в полном разрешении)
  const atlas = new Uint8Array(T * T * 4);
  let mr = 0, mg = 0, mb = 0; const nvc = M.col ? nv : 0; for (let v = 0; v < nvc; v++) { mr += M.col[v * 3]; mg += M.col[v * 3 + 1]; mb += M.col[v * 3 + 2]; }
  const fill = nvc ? [mr / nvc, mg / nvc, mb / nvc] : [128, 128, 128];
  for (let i = 0; i < T * T; i++) { atlas[i * 4] = fill[0]; atlas[i * 4 + 1] = fill[1]; atlas[i * 4 + 2] = fill[2]; atlas[i * 4 + 3] = 255; }
  const byFrame = new Map(); for (const r of rects) if (r.c) { const a = byFrame.get(r.c.fi) || []; a.push(r); byFrame.set(r.c.fi, a); }
  let done = 0;
  for (const [fi, rs] of byFrame) {
    const f = frames[fi];
    let src = null;
    try { src = f.blob && opt.decode ? await opt.decode(f.blob) : null; } catch (e) { src = null; }
    if (!src) src = { rgba: f.rgba, w: f.w, h: f.h };
    const k = src.w / (f.srcW || f.w); // если полный кадр не раскрылся — берём рабочий (w×h)
    const W = src.w, H = src.h, p = src.rgba;
    for (const r of rs) {
      const c = r.c, g = c.g;
      for (let ay = 0; ay < r.h; ay++) for (let ax = 0; ax < r.w; ax++) {
        const sx = (c.bx + (ax - G + 0.5) / sg - 0.5) * k, sy = (c.by + (ay - G + 0.5) / sg - 0.5) * k;
        const x0 = Math.max(0, Math.min(W - 2, Math.floor(sx))), y0 = Math.max(0, Math.min(H - 2, Math.floor(sy))), fx = Math.min(1, Math.max(0, sx - x0)), fy = Math.min(1, Math.max(0, sy - y0));
        const i = (y0 * W + x0) * 4, s = W * 4, o = ((r.y + ay) * T + r.x + ax) * 4;
        for (let ch = 0; ch < 3; ch++) atlas[o + ch] = Math.min(255, g[ch] * ((p[i + ch] * (1 - fx) + p[i + 4 + ch] * fx) * (1 - fy) + (p[i + s + ch] * (1 - fx) + p[i + s + 4 + ch] * fx) * fy));
      }
    }
    done++; prog(0.55 + 0.4 * done / byFrame.size, `кадр ${done} из ${byFrame.size}`);
    await tick();
  }
  // тексели невидимых граней
  const ur = rects.find((r) => !r.c);
  if (ur) unseen.forEach((i, k) => {
    const x = ur.x + G + (k % us), y = ur.y + G + ((k / us) | 0), o = (y * T + x) * 4;
    for (let ch = 0; ch < 3; ch++) { let s = 0; for (let e = 0; e < 3; e++) s += M.col ? M.col[idx[i * 3 + e] * 3 + ch] : 128; atlas[o + ch] = s / 3; }
  });
  // 7) новая сетка: вершина на каждом лоскуте своя (на швах — дубли с разными UV)
  const np = [], nn = [], nc = [], uv = [], ni = new Uint32Array(nt * 3);
  const stamp = new Int32Array(nv).fill(-1), map = new Int32Array(nv);
  const addV = (v, U, V) => { const id = np.length / 3; for (let c = 0; c < 3; c++) { np.push(pos[v * 3 + c]); nn.push(M.nrm[v * 3 + c]); nc.push(M.col ? M.col[v * 3 + c] : 200); } uv.push(U, V); return id; };
  rects.forEach((r, ri) => {
    if (!r.c) return; const c = r.c, f = frames[c.fi];
    for (const i of c.faces) for (let e = 0; e < 3; e++) {
      const v = idx[i * 3 + e];
      if (stamp[v] !== ri) { stamp[v] = ri; const [u, vv] = projSrc(f, v); map[v] = addV(v, (r.x + G + (u - c.bx) * sg) / T, (r.y + G + (vv - c.by) * sg) / T); }
      ni[i * 3 + e] = map[v];
    }
  });
  if (ur) unseen.forEach((i, k) => { const U = (ur.x + G + (k % us) + 0.5) / T, V = (ur.y + G + ((k / us) | 0) + 0.5) / T; for (let e = 0; e < 3; e++) ni[i * 3 + e] = addV(idx[i * 3 + e], U, V); });
  const mesh = { pos: new Float32Array(np), nrm: new Float32Array(nn), col: new Uint8Array(nc), idx: ni, uv: new Float32Array(uv) };
  const jpg = opt.encode ? await opt.encode(atlas, T) : null;
  prog(1, 'текстура готова');
  return { mesh, tex: jpg ? { w: T, h: T, jpg } : null, atlas, T, info: { charts: charts.length, frames: byFrame.size, scale: sg, unseen: unseen.length } };
}
