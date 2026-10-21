// «Доснять низ»: две синтетические съёмки (стоит / лежит на боку) → оболочки → совмещение → пересечение.
// node tbottom.mjs /tmp/t/s2 /tmp/t/b2 "90,0,25,-16,34,24" [HB_A] [HB_B]  (ENV: CUTA=1 — режим вертушки для A)
import fs from 'fs';
import { matLayout, matRaster } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
import { computeMask, carveHull, cleanGrid } from '../web/js/recon.js';
import { alignHulls, intersectHulls } from '../web/js/align.js';
const [dirA, dirB, poseB] = process.argv.slice(2), HA = +(process.argv[5] || 90), HB = +(process.argv[6] || 90), N = 128, W = 640;
const L = matLayout('A4'), mr = matRaster(L, 'light', 2);
function hull(dir, Hb, cut) {
  const gt = JSON.parse(fs.readFileSync(dir + '/gt.json')), w = W, h = Math.round(gt.h * W / gt.w);
  let K = { fx: 0.7 * w, fy: 0.7 * w, cx: w / 2, cy: h / 2 }; const frames = [], eqs = [];
  for (const [gi, fr] of gt.frames.entries()) {
    const rgba = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', `_${W}.rgba`)));
    const ms = detectMarkers(toGray(rgba, w, h), w, h), p = poseFromMarkers(ms, L, K);
    if (p && p.n >= 2) { eqs.push(...focalEqs(p.H, w / 2, h / 2)); frames.push({ rgba, ms, p, w, h, gi }); }
  }
  const f0 = focalFromEqs(eqs), rf = refineFocal(frames.map((f) => f.p), { ...K, fx: f0, fy: f0 }); K = { ...K, fx: rf.f, fy: rf.f };
  const good = [];
  for (const f of frames) { const p = poseFromMarkers(f.ms, L, K); if (!p || p.rms > 3) continue; f.R = p.R; f.t = p.t; f.K = K; f.mask = computeMask(f, { layout: L, mr, Rb: 55, Hb, cutOnly: cut, offMat: !cut }).mask; if (process.env.GTM) { const gm = new Uint8Array(fs.readFileSync(dir + `/m${String(f.gi).padStart(3, '0')}_640.m`)); f.mask = gm.map((v) => (v ? 2 : 0)); } good.push(f); }
  if (process.env.DBG) { const errs = good.map((f) => { const g = gt.frames[f.gi], C = (R, t) => [0, 1, 2].map((c) => -(R[c] * t[0] + R[3 + c] * t[1] + R[6 + c] * t[2])); const a = C(f.R, f.t), b = C(g.R, g.t); return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]); }); console.log(dir, 'кадров', good.length, 'ошибка центра камеры, мм: медиана', errs.sort((a, b) => a - b)[errs.length >> 1].toFixed(2), 'макс', errs[errs.length - 1].toFixed(2), 'focal', K.fx.toFixed(1), 'gt', (gt.K.fx * W / gt.w).toFixed(1)); }
  return carveHull(good, { Rb: 55, Hb }, N);
}
// точная форма предмета (система предмета): цилиндр r24 h0..42, шар r17 z58, брусок x22..40 y-6..6 z10..30
const inObj = (x, y, z) => (x * x + y * y <= 576 && z >= 0 && z <= 42) || (x * x + y * y + (z - 58) ** 2 <= 289) || (x >= 22 && x <= 40 && y >= -6 && y <= 6 && z >= 10 && z <= 30);
function stats(G, name, T) {
  let v = 0, ex = 0, cu = 0, exTop = 0, exBot = 0; const S = G.nx * G.ny;
  for (let z = 0; z < G.nz; z++) for (let y = 0; y < G.ny; y++) for (let x = 0; x < G.nx; x++) {
    const X = G.origin[0] + x * G.vs, Y = G.origin[1] + y * G.vs, Z = G.origin[2] + z * G.vs, o = G.occ[z * S + y * G.nx + x] > 0.5, P = T ? [0, 1, 2].map((r) => T.R[r * 3] * X + T.R[r * 3 + 1] * Y + T.R[r * 3 + 2] * Z + T.t[r]) : [X, Y, Z], t = inObj(P[0], P[1], P[2]);
    if (o) v++; if (o && !t) { ex++; if (Z > 42) exTop++; if (Z < 10) exBot++; } if (!o && t) cu++;
  }
  const c = G.vs ** 3; console.log(`${name}: объём ${(v * c / 1000).toFixed(1)} см³, лишнее ${(ex * c / 1000).toFixed(1)} (сверху ${(exTop * c / 1000).toFixed(1)}, снизу ${(exBot * c / 1000).toFixed(1)}), срезано ${(cu * c / 1000).toFixed(2)} см³`);
}
console.time('hulls'); const GA = hull(dirA, HA, !!process.env.CUTA), GB = hull(dirB, HB, !!process.env.CUTB); console.timeEnd('hulls');
stats(GA, 'A (стоит)');
let truth = null;
if (poseB) { const v = poseB.split(',').map(Number), rad = (a) => a * Math.PI / 180; const rot = (ax, a) => { const c = Math.cos(rad(a)), s = Math.sin(rad(a)); return ax === 0 ? [1, 0, 0, 0, c, -s, 0, s, c] : ax === 1 ? [c, 0, s, 0, 1, 0, -s, 0, c] : [c, -s, 0, s, c, 0, 0, 0, 1]; }; const mul = (A, B) => { const C = []; for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) C.push(A[r * 3] * B[c] + A[r * 3 + 1] * B[3 + c] + A[r * 3 + 2] * B[6 + c]); return C; }; const QR = mul(rot(2, v[2]), mul(rot(1, v[1]), rot(0, v[0]))), QRt = [QR[0], QR[3], QR[6], QR[1], QR[4], QR[7], QR[2], QR[5], QR[8]]; truth = { R: QRt, t: [0, 1, 2].map((r) => -(QRt[r * 3] * v[3] + QRt[r * 3 + 1] * v[4] + QRt[r * 3 + 2] * v[5])) }; }
if (truth) stats(GB, 'B (лежит, в своей системе)', truth);
if (process.env.DBG && truth) { const S = GB.nx * GB.ny, h = {}; for (let z = 0; z < GB.nz; z++) for (let y = 0; y < GB.ny; y++) for (let x = 0; x < GB.nx; x++) { const X = GB.origin[0] + x * GB.vs, Y = GB.origin[1] + y * GB.vs, Z = GB.origin[2] + z * GB.vs, P = [0, 1, 2].map((r) => truth.R[r * 3] * X + truth.R[r * 3 + 1] * Y + truth.R[r * 3 + 2] * Z + truth.t[r]); if (!inObj(...P) || GB.occ[z * S + y * GB.nx + x] > 0.5) continue; const k = (P[0] * P[0] + P[1] * P[1] <= 576 && P[2] <= 42 ? 'cyl' : P[0] >= 22 ? 'box' : 'sph') + ' z' + (Math.round(P[2] / 10) * 10) + (P[1] > 0 ? ' y+' : ' y-') + (P[0] > 0 ? ' x+' : ' x-'); h[k] = (h[k] || 0) + 1; } console.log(Object.entries(h).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k, v]) => k + ':' + v).join('  ')); }
if (process.env.DBG) { console.log('capTrim A', GA.capTrim, 'B', GB.capTrim); const S = GB.nx * GB.ny; let line = ''; for (let z = 0; z < GB.nz; z += 6) { let cu = 0, ex = 0; for (let y = 0; y < GB.ny; y++) for (let x = 0; x < GB.nx; x++) { const X = GB.origin[0] + x * GB.vs, Y = GB.origin[1] + y * GB.vs, Z = GB.origin[2] + z * GB.vs, P = [0, 1, 2].map((r) => truth.R[r * 3] * X + truth.R[r * 3 + 1] * Y + truth.R[r * 3 + 2] * Z + truth.t[r]), t = inObj(...P), o = GB.occ[z * S + y * GB.nx + x] > 0.5; if (t && !o) cu++; if (o && !t) ex++; } line += `${(GB.origin[2] + z * GB.vs).toFixed(0)}:${cu}/${ex} `; } console.log('B по высоте срезано/лишнее:', line); }
console.time('align'); const al = alignHulls(GA, GB, null, process.env.DBG ? truth : null); console.timeEnd('align');
console.log('совпадение', al.score.toFixed(3), 'B→A', al.fAB.toFixed(3), 'A→B', al.fBA.toFixed(3), 'rms', al.rms.toFixed(2), 'мм');
if (poseB) { // истина: p_A = QRᵀ(p_B − QT)
  const v = poseB.split(',').map(Number), rad = (a) => a * Math.PI / 180;
  const rot = (ax, a) => { const c = Math.cos(rad(a)), s = Math.sin(rad(a)); return ax === 0 ? [1, 0, 0, 0, c, -s, 0, s, c] : ax === 1 ? [c, 0, s, 0, 1, 0, -s, 0, c] : [c, -s, 0, s, c, 0, 0, 0, 1]; };
  const mul = (A, B) => { const C = []; for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) C.push(A[r * 3] * B[c] + A[r * 3 + 1] * B[3 + c] + A[r * 3 + 2] * B[6 + c]); return C; };
  const QR = mul(rot(2, v[2]), mul(rot(1, v[1]), rot(0, v[0]))), QRt = [QR[0], QR[3], QR[6], QR[1], QR[4], QR[7], QR[2], QR[5], QR[8]];
  const tt = [0, 1, 2].map((r) => -(QRt[r * 3] * v[3] + QRt[r * 3 + 1] * v[4] + QRt[r * 3 + 2] * v[5]));
  const D = mul(al.R, [QR[0], QR[1], QR[2], QR[3], QR[4], QR[5], QR[6], QR[7], QR[8]]);
  const ang = Math.acos(Math.min(1, (D[0] + D[4] + D[8] - 1) / 2)) * 180 / Math.PI;
  // ошибка положения точки в центре предмета (0,0,35)
  const pB = [0, 1, 2].map((r) => QR[r * 3] * 0 + QR[r * 3 + 1] * 0 + QR[r * 3 + 2] * 35 + v[3 + r]);
  const pA = [0, 1, 2].map((r) => al.R[r * 3] * pB[0] + al.R[r * 3 + 1] * pB[1] + al.R[r * 3 + 2] * pB[2] + al.t[r]);
  console.log(`ошибка совмещения: поворот ${ang.toFixed(2)}°, центр ${Math.hypot(pA[0], pA[1], pA[2] - 35).toFixed(2)} мм`);
}
const rem = intersectHulls(GA, GB, al.R, al.t, +(process.env.DIL ?? 1)); cleanGrid(GA);
console.log('вырезано вокселей', rem);
stats(GA, 'A ∩ низ');
