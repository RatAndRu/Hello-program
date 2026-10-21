// Свет, рельеф, материал, текстура без теней — против эталона синтетической сцены (scene.py BUMP=1 MATS=1).
// node tsurf.mjs /tmp/t/rB          (WALK=1 — съёмка с рук)   env: LAM=1 ALIGN=2 SHOTS=/home/user/shots/ TEX=1024 HB=90
// Эталон: лампа LDIR (как в scene.py, по умолчанию [0.4,−0.5,0.75]), рассеянный 0.35 / прямой 0.65; на вертушке (LIGHTCAM) лампа поворачивается с камерой.
// Цилиндр r=24, h=42, бороздки h(z)=0.3·sin(2πz/5) мм; шар — глянец (узкий белый блик); кубик-ручка — металл (цветной блик).
import fs from 'fs';
import { execSync } from 'child_process';
import { matLayout, matRaster } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
import { computeMask, motionMasks, carveHull, meshFromGrid, taubin, computeNormals, colorize } from '../web/js/recon.js';
import { bakeTexture } from '../web/js/texture.js';
import { analyzeSurface } from '../web/js/surface.js';

const E = process.env, dir = process.argv[2], W = 640, HB = +(E.HB || 90), WALK = !!E.WALK, SH = E.SHOTS || '/home/user/shots/';
const L = matLayout('A4', WALK ? 'full' : 'round'), mr = matRaster(L, 'light', 2);
const gt = JSON.parse(fs.readFileSync(dir + '/gt.json')), h = Math.round(gt.h * W / gt.w), w = W;
const frames = [], eqs = [];
gt.frames.forEach((fr, gi) => {
  const rgba = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', `_${W}.rgba`)));
  const f0 = 0.75 * w, ms = detectMarkers(toGray(rgba, w, h), w, h), p = poseFromMarkers(ms, L, { fx: f0, fy: f0, cx: w / 2, cy: h / 2 });
  if (!p || p.n < 2) return; eqs.push(...focalEqs(p.H, w / 2, h / 2)); frames.push({ rgba, ms, p, w, h, gi });
});
const f0 = focalFromEqs(eqs), rf = refineFocal(frames.map((f) => f.p), { fx: f0, fy: f0, cx: w / 2, cy: h / 2 }), K = { fx: rf.f, fy: rf.f, cx: w / 2, cy: h / 2 };
const good = []; for (const f of frames) { const p = poseFromMarkers(f.ms, L, K); if (!p || p.rms > 3) continue; f.R = p.R; f.t = p.t; f.K = K; f.rms = p.rms; good.push(f); }
for (const f of good) { const m = computeMask(f, { layout: L, mr, Rb: 55, Hb: HB, cutOnly: !WALK, offMat: WALK, enclose: true, refOut: !WALK }); f.mask = m.mask; f.refOut = m.refOut; f.trusted = !!m.stats.enclosed; }
if (!WALK) motionMasks(good);
// IDEAL=1 — оболочка по точным маскам (проверка самого метода без ошибок формы)
const G = E.IDEAL ? carveHull(good.map((f) => ({ ...f, motion: null, mask: Uint8Array.from(fs.readFileSync(dir + `/m${String(f.gi).padStart(3, '0')}_${W}.m`), (v) => (v ? 2 : 0)) })), { Rb: 55, Hb: HB }, 128, null, { frac: 0, close: 0 }) : carveHull(good, { Rb: 55, Hb: HB }, 128);
let M = meshFromGrid(G, 3); taubin(M, 30); computeNormals(M); colorize(M, good);
console.time('текстура');
const B = await bakeTexture(M, good, { size: +(E.TEX || 1024) });
console.timeEnd('текстура');
console.log(`атлас ${B.T}, лоскутов ${B.info.charts}`);
console.time('поверхность');
const S = await analyzeSurface(B.mesh, good, B.faceFrame, B.faceChart, B.atlas, B.T, { G, turn: !WALK, ...(E.LAM ? { lam: +E.LAM } : {}), ...(E.ALIGN ? { align: +E.ALIGN } : {}), tick: async () => {}, ...(E.OPT ? JSON.parse(E.OPT) : {}), ...(E.NOSH ? { shadows: false } : {}), ...(E.GTL ? { forceLight: (() => { const Lg = (E.LDIR || '0.4,-0.5,0.75').split(',').map(Number), l = Math.hypot(...Lg), a = -Math.PI / 2, c = Math.cos(a), s_ = Math.sin(a), d = Lg.map((v) => v / l); const dd = WALK ? d : [c * d[0] - s_ * d[1], s_ * d[0] + c * d[1], d[2]]; return { a: 0.35, l0: dd.map((v) => v * 0.65), m: WALK ? 0 : 1 }; })() } : {}), ...(E.EDG ? { debugEdges: ({ EI, EJ, EW, ED }) => { const XW = globalThis.__Xp; const hg = (j) => { const X = [XW[j * 3], XW[j * 3 + 1], XW[j * 3 + 2]], k = 2 * Math.PI / 6, ang = Math.atan2(X[1], X[0]); return 0.4 * Math.cos(k * 24 * ang) * Math.cos(k * X[2]); }; let c = [0, 0, 0], n = 0, big = 0; for (let e = 0; e < EI.length; e++) { const i = EI[e], j = EJ[e], zi = XW[i * 3 + 2], r = Math.hypot(XW[i * 3], XW[i * 3 + 1]); if (!(zi > 22 && zi < 38 && r > 18 && r < 30) || (XW[i * 3] > 16 && Math.abs(XW[i * 3 + 1]) < 12)) continue; const g = hg(j) - hg(i); c[0] += g * ED[e]; c[1] += g * g; c[2] += ED[e] ** 2; n++; if (Math.abs(ED[e] - g) > 0.1) big++; } console.log('рёбра: совпадение', (c[0] / Math.sqrt(c[1] * c[2])).toFixed(3), 'n', n, 'плохих', big, 'rms gt', Math.sqrt(c[1] / n).toFixed(4), 'pred', Math.sqrt(c[2] / n).toFixed(4)); } } : {}), ...(E.GTPQ ? { debugPQ: (j, Xp, N0, T1, T2) => { const X = [Xp[j * 3], Xp[j * 3 + 1], Xp[j * 3 + 2]], r = Math.hypot(X[0], X[1]); if (!(r > 18 && r < 30 && Math.abs(N0[j * 3 + 2]) < 0.5)) return [0, 0]; const { g } = gtSide(X); const n0 = [N0[j * 3], N0[j * 3 + 1], N0[j * 3 + 2]], d = g[0] * n0[0] + g[1] * n0[1] + g[2] * n0[2]; return [(g[0] * T1[j * 3] + g[1] * T1[j * 3 + 1] + g[2] * T1[j * 3 + 2]) / d, (g[0] * T2[j * 3] + g[1] * T2[j * 3 + 1] + g[2] * T2[j * 3 + 2]) / d]; } } : {}), ...(E.NOAO ? { ao: false } : {}), ...(E.DBG ? { debug: (await import('/tmp/t/dbg.mjs'))[{ 2: 'solveDbg', 3: 'dimDbg', 4: 'dimDbg2', 5: 'grid2' }[E.DBG] || 'dbg'] } : {}) });
console.timeEnd('поверхность');
const I = S.info;
console.log('свет:', JSON.stringify(I.light), 'совмещение:', JSON.stringify(I.align || {}), 'выборок', I.samples);
// --- свет против эталона
if (I.light) { const Lg = (E.LDIR || '0.4,-0.5,0.75').split(',').map(Number), l = Math.hypot(...Lg); const g = Lg.map((v) => v / l); let d = I.light.dir;
  if (I.light.rotates) { const a = Math.PI / 2, c = Math.cos(a), s = Math.sin(a); d = [c * d[0] - s * d[1], s * d[0] + c * d[1], d[2]]; }
  const ang = Math.acos(Math.min(1, d[0] * g[0] + d[1] * g[1] + d[2] * g[2])) * 180 / Math.PI;
  console.log(`лампа: ошибка направления ${ang.toFixed(1)}°, поворот с камерой ${I.light.rotates ? 'да' : 'нет'} (эталон ${WALK ? 'нет' : 'да'}), рассеянный ${I.light.ambient} (эталон 0.35)`); }
// --- нормали: бок цилиндра (бороздки) и плоский верх
const { Nw, tri, texels, rhoC, lab } = S.world, Wr = S.Wr;
const pos = B.mesh.pos, idx = B.mesh.idx;
const Xof = (j) => { const f = tri[j]; const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2]; // центр грани (для классификации)
  return [0, 1, 2].map((k) => (pos[a * 3 + k] + pos[b * 3 + k] + pos[c * 3 + k]) / 3); };
const N0of = (j) => { const f = tri[j]; const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2]; let n = [0, 1, 2].map((k) => B.mesh.nrm[a * 3 + k] + B.mesh.nrm[b * 3 + k] + B.mesh.nrm[c * 3 + k]); const l = Math.hypot(...n); return n.map((v) => v / l); };
const angle = (a, b) => Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))) * 180 / Math.PI;
if (globalThis.__dbgJ) for (const [j, g] of globalThis.__dbgJ) { const W_ = S.world; const n0 = [W_.N0[j * 3], W_.N0[j * 3 + 1], W_.N0[j * 3 + 2]]; const a = Math.abs(n0[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]; let t1 = [a[1] * n0[2] - a[2] * n0[1], a[2] * n0[0] - a[0] * n0[2], a[0] * n0[1] - a[1] * n0[0]]; const l = Math.hypot(...t1); t1 = t1.map((v) => v / l); const t2 = [n0[1] * t1[2] - n0[2] * t1[1], n0[2] * t1[0] - n0[0] * t1[2], n0[0] * t1[1] - n0[1] * t1[0]]; const d = g[0] * n0[0] + g[1] * n0[1] + g[2] * n0[2]; console.log('точка', j, 'p,q измерено', W_.Pm[j].toFixed(3), W_.Qm[j].toFixed(3), 'эталон', ((g[0] * t1[0] + g[1] * t1[1] + g[2] * t1[2]) / d).toFixed(3), ((g[0] * t2[0] + g[1] * t2[1] + g[2] * t2[2]) / d).toFixed(3), 'инф', W_.Iaa[j].toFixed(0), W_.Ibb[j].toFixed(0), 'итог', [0, 1, 2].map((c) => W_.Nw[j * 3 + c] * 1).map((v, c) => v).reduce((s_, v, c) => s_ + v * t1[c], 0).toFixed(3)); }
// эталонная нормаль бока (BUMP=1: бороздки везде; BUMP=2: бороздки z<21, выпуклости z≥21)
const BUMPM = +(E.BUMP || 1);
function gtSide(X) { const BUMPM = +(E.BUMP || 1); const r = Math.hypot(X[0], X[1]), ang = Math.atan2(X[1], X[0]); let gz = -0.3 * 2 * Math.PI / 5 * Math.cos(2 * Math.PI * X[2] / 5), gs = 0;
  if (BUMPM === 2 && X[2] >= 21) { const k = 2 * Math.PI / 6, s_ = 24 * ang; gz = 0.4 * k * Math.cos(k * s_) * Math.sin(k * X[2]); gs = 0.4 * k * Math.sin(k * s_) * Math.cos(k * X[2]); }
  const t = [-Math.sin(ang), Math.cos(ang), 0]; let g = [X[0] / r + gs * t[0], X[1] / r + gs * t[1], gz]; const l = Math.hypot(...g); return { g: g.map((v) => v / l), t, rad: [X[0] / r, X[1] / r, 0] }; }
const XW = S.world.Xp, N0W = S.world.N0;
const zone = () => ({ n: 0, e0: 0, e1: 0, h: [0, 0, 0], v: [0, 0, 0] });
const Z = { gro: zone(), dim: zone() }, top = { n: 0, e0: 0, e1: 0 };
const acc = (c, a, b) => { c[0] += a * b; c[1] += a * a; c[2] += b * b; };
for (const j of texels) {
  const X = [XW[j * 3], XW[j * 3 + 1], XW[j * 3 + 2]], r = Math.hypot(X[0], X[1]), n = [Nw[j * 3], Nw[j * 3 + 1], Nw[j * 3 + 2]], n0 = [N0W[j * 3], N0W[j * 3 + 1], N0W[j * 3 + 2]];
  if (r > 18 && r < 30 && X[2] > 4 && X[2] < 38 && Math.abs(n0[2]) < 0.5 && !(X[0] > 16 && Math.abs(X[1]) < 12 && X[2] > 4 && X[2] < 36)) {
    const { g, t } = gtSide(X), zz = BUMPM === 2 && X[2] >= 21 ? Z.dim : Z.gro;
    zz.n++; zz.e0 += angle(n0, g); zz.e1 += angle(n, g);
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    acc(zz.h, dot(n, t) - dot(n0, t), dot(g, t)); acc(zz.v, n[2] - n0[2], g[2]);
    const fz_ = (X[2] / 7) % 1, fa_ = ((Math.atan2(X[1], X[0]) + Math.PI) / (Math.PI / 6)) % 1, nearEdge = fz_ < 0.15 || fz_ > 0.85 || fa_ < 0.15 || fa_ > 0.85;
    if (E.FAR && nearEdge) continue;
    if (S.world.Iaa[j] > 0) { zz.m = zz.m || [[0, 0, 0], [0, 0, 0], 0, 0, 0]; acc(zz.m[0], S.world.Pm[j] + dot(n0, t), dot(g, t)); acc(zz.m[1], S.world.Qm[j] + n0[2], g[2]); zz.m[2] += S.world.Iaa[j]; zz.m[3] += S.world.Ibb[j]; zz.m[4]++; }
  }
  if (r < 20 && Math.abs(X[2] - 42) < 3 && n0[2] > 0.8) { top.n++; top.e0 += angle(n0, [0, 0, 1]); top.e1 += angle(n, [0, 0, 1]); }
}
{ const H = S.world.Hh; if (H) { const c = [0, 0, 0]; let n = 0; const XW2 = S.world.Xp; for (const j of texels) { const X = [XW2[j * 3], XW2[j * 3 + 1], XW2[j * 3 + 2]], r = Math.hypot(X[0], X[1]); if (!(r > 18 && r < 30 && X[2] > 22 && X[2] < 38 && Math.abs(S.world.N0[j * 3 + 2]) < 0.5) || (X[0] > 16 && Math.abs(X[1]) < 12)) continue; const k = 2 * Math.PI / 6, ang = Math.atan2(X[1], X[0]), hg = 0.4 * Math.cos(k * 24 * ang) * Math.cos(k * X[2]); c[0] += H[j] * hg; c[1] += H[j] ** 2; c[2] += hg * hg; n++; } console.log(`  высота выпуклостей: совпадение ${(c[0] / Math.sqrt(c[1] * c[2])).toFixed(2)}, размах ${Math.sqrt(c[1] / n).toFixed(3)} мм (эталон ${Math.sqrt(c[2] / n).toFixed(3)}), ${n}`); } }
const cr = (c) => (c[0] / Math.sqrt(c[1] * c[2] + 1e-12)).toFixed(2);
for (const [nm, zz] of [['бороздки', Z.gro], ['выпуклости', Z.dim]]) if (zz.m) console.log(`  ${nm}: по точкам вбок ${cr(zz.m[0])} вверх ${cr(zz.m[1])}, средняя информация ${(zz.m[2] / zz.m[4]).toFixed(0)} / ${(zz.m[3] / zz.m[4]).toFixed(0)} (${zz.m[4]})`);
for (const [nm, zz] of [['бороздки', Z.gro], ['выпуклости', Z.dim]]) if (zz.n) console.log(`${nm} (${zz.n} текс.): ошибка нормали сетка ${(zz.e0 / zz.n).toFixed(1)}° → рельеф ${(zz.e1 / zz.n).toFixed(1)}°, совпадение наклона: вбок ${cr(zz.h)}, вверх ${cr(zz.v)}`);
console.log(`плоский верх (${top.n}): сетка ${(top.e0 / top.n).toFixed(1)}° → рельеф ${(top.e1 / top.n).toFixed(1)}° (должен остаться плоским)`);
// --- альбедо: бок цилиндра против эталонного узора (вдали от границ полос)
{ const gtCol = (X) => { const r = Math.hypot(X[0], X[1]), ang = Math.atan2(X[1], X[0]); const band = Math.floor(X[2] / 7) % 2, sec = Math.floor((ang + Math.PI) / (Math.PI / 6)) % 2; return (band ^ sec) ? [0.95, 0.8, 0.2] : [0.85, 0.25, 0.2]; };
  const edge = (X) => { const ang = Math.atan2(X[1], X[0]), fz = (X[2] / 7) % 1, fa = ((ang + Math.PI) / (Math.PI / 6)) % 1; return fz < 0.2 || fz > 0.8 || fa < 0.2 || fa > 0.8; };
  const sc = B.T / Wr, A = [[], [], [], []], RV = S.world.rhoV, RC = S.world.rhoC;
  for (const j of texels) {
    const X = Xof(j), r = Math.hypot(X[0], X[1]), n0 = N0of(j);
    if (!(r > 18 && r < 30 && X[2] > 4 && X[2] < 38 && Math.abs(n0[2]) < 0.5) || (X[0] > 18 && Math.abs(X[1]) < 10) || edge(X)) continue;
    const g = gtCol(X), x = j % Wr, y = (j / Wr) | 0, ti = (Math.floor((y + 0.5) * sc) * B.T + Math.floor((x + 0.5) * sc)) * 4;
    A[0].push([g, [B.atlas[ti], B.atlas[ti + 1], B.atlas[ti + 2]]]); A[1].push([g, [S.albedo[ti], S.albedo[ti + 1], S.albedo[ti + 2]]]); if (RV) A[2].push([g, [RV[j * 3], RV[j * 3 + 1], RV[j * 3 + 2]]]); A[3].push([g, [RC[j * 3], RC[j * 3 + 1], RC[j * 3 + 2]]]);
  }
  const err = (P) => { let e = 0, n = 0; for (let c = 0; c < 3; c++) { let sxy = 0, sxx = 0; for (const [g, v] of P) { sxy += g[c] * v[c]; sxx += g[c] * g[c]; } const k = sxy / sxx; for (const [g, v] of P) { e += (v[c] - k * g[c]) ** 2; n++; } } return Math.sqrt(e / n); };
  console.log(`цвет бока (${A[0].length} текс.), ошибка после общего масштаба: фото-текстура ${err(A[0]).toFixed(1)} → без теней ${err(A[1]).toFixed(1)}, светлый вид ${A[2].length ? err(A[2]).toFixed(1) : '-'}, по модели ${err(A[3]).toFixed(1)} (из 255)`); }
// --- альбедо шара (блики, сильная светотень)
{ const sc = B.T / Wr, A = [[], []];
  for (const j of texels) {
    const X = [S.world.Xp[j * 3], S.world.Xp[j * 3 + 1], S.world.Xp[j * 3 + 2]], q = [X[0], X[1], X[2] - 58], rq = Math.hypot(...q); if (rq > 21 || rq < 14 || X[2] < 48) continue;
    const th = Math.atan2(q[1], q[0]), ph = Math.acos(Math.max(-1, Math.min(1, q[2] / rq))), fa = (th / (Math.PI / 5)) % 1, fb = (ph / (Math.PI / 6)) % 1, fa2 = fa < 0 ? fa + 1 : fa;
    if (fa2 < 0.2 || fa2 > 0.8 || fb < 0.2 || fb > 0.8) continue;
    const ch = (Math.floor(th / (Math.PI / 5)) + Math.floor(ph / (Math.PI / 6))) % 2 !== 0, g = ch ? [0.9, 0.9, 0.95] : [0.2, 0.45, 0.9];
    const x = j % Wr, y = (j / Wr) | 0, ti = (Math.floor((y + 0.5) * sc) * B.T + Math.floor((x + 0.5) * sc)) * 4;
    A[0].push([g, [B.atlas[ti], B.atlas[ti + 1], B.atlas[ti + 2]]]); A[1].push([g, [S.albedo[ti], S.albedo[ti + 1], S.albedo[ti + 2]]]);
  }
  const err = (P) => { let e = 0, n = 0; for (let c = 0; c < 3; c++) { let sxy = 0, sxx = 0; for (const [g, v] of P) { sxy += g[c] * v[c]; sxx += g[c] * g[c]; } const k = sxy / sxx; for (const [g, v] of P) { e += (v[c] - k * g[c]) ** 2; n++; } } return Math.sqrt(e / n); };
  console.log(`цвет шара (${A[0].length} текс.): фото-текстура ${err(A[0]).toFixed(1)} → без теней ${err(A[1]).toFixed(1)}`); }
// --- материалы по частям
{ const part = (X) => (Math.hypot(X[0], X[1], X[2] - 58) < 21 ? 'шар' : X[0] > 18 && X[0] < 44 && Math.abs(X[1]) < 10 && X[2] > 6 && X[2] < 34 ? 'ручка' : Math.hypot(X[0], X[1]) < 30 && X[2] < 44 ? 'цилиндр' : null);
  const acc = {};
  for (const j of texels) { const p = part(Xof(j)); if (!p) continue; const a = acc[p] || (acc[p] = { n: 0, r: 0, m: 0 }); a.n++; a.r += S.orm[j * 4 + 1] / 255; a.m += S.orm[j * 4 + 2] / 255; }
  console.log('материал (шероховатость / металл): ' + Object.entries(acc).map(([k, a]) => `${k} ${(a.r / a.n).toFixed(2)} / ${(a.m / a.n).toFixed(2)}`).join(', ') + '  (эталон: цилиндр мат ~0.9/0, шар глянец ~0.3/0, ручка металл ~0.5/1)');
  console.log('зоны:', JSON.stringify(I.materials)); }
console.log('высота: ±' + I.heightRange + ' мм' + (I.reliefApprox ? ' (приблизительный рельеф по светотени)' : ''));
// --- картинки
const tag = E.TAG || (WALK ? 'w' : 'r');
const save = (name, rgba, n) => { const ppm = Buffer.alloc(n * n * 3); for (let i = 0; i < n * n; i++) { ppm[i * 3] = rgba[i * 4]; ppm[i * 3 + 1] = rgba[i * 4 + 1]; ppm[i * 3 + 2] = rgba[i * 4 + 2]; } fs.writeFileSync('/tmp/t/_s.ppm', Buffer.concat([Buffer.from(`P6\n${n} ${n}\n255\n`), ppm])); execSync(`python3 -c "from PIL import Image; Image.open('/tmp/t/_s.ppm').save('${SH}${name}')"`); };
save(`su_${tag}_atlas.png`, B.atlas, B.T); save(`su_${tag}_albedo.png`, S.albedo, B.T); save(`su_${tag}_normal.png`, S.normal, Wr); save(`su_${tag}_orm.png`, S.orm, Wr); save(`su_${tag}_height.png`, S.height, Wr);
