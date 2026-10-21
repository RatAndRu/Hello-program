// «Шапка» над предметом на вертушке: оболочка по маскам приложения против оболочки по точным маскам (те же позы).
// node tcap.mjs /tmp/t/spinS [/tmp/t/spinH …]   env: ENC=1 — правило «предмет целиком на листе»; PLATE=1 — кадр фона;
// STEP=2 — каждый второй кадр; TF=0.15 — доля доверенных кадров для вырезания; NOTRUST=1 — без доверенного голосования; FROM=k — с k-го кадра (без смазанных первых); MSTAT=1 — ошибки масок; NOMOTION=1 — без улик «движения» (вертушка); HB=90 — высота рамки; N=128.
// Печатает по слоям 10 мм: лишний объём (шапка) и срезанный объём настоящей оболочки, см³; и сколько кадров «замкнуты».
import fs from 'fs';
import { matLayout, matRaster } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
import { computeMask, carveHull, motionMasks } from '../web/js/recon.js';
import * as RC from '../web/js/recon.js';

const dirs = process.argv.slice(2), W = 640, STEP = +(process.env.STEP || 2), HB = +(process.env.HB || 90), N = +(process.env.N || 128);
const WALK = !!process.env.WALK; // WALK=1 — съёмка с рук: лист целиком, без вырезанного круга
const L = matLayout('A4', WALK ? 'full' : 'round'), mr = matRaster(L, 'light', 2);
const frames = [], eqs = [];
let w = 0, h = 0;
for (const dir of dirs) {
  const gt = JSON.parse(fs.readFileSync(dir + '/gt.json'));
  w = W; h = Math.round(gt.h * W / gt.w);
  const plate = process.env.PLATE && fs.existsSync(dir + '/plate_640.rgba') ? new Uint8Array(fs.readFileSync(dir + '/plate_640.rgba')) : null;
  gt.frames.forEach((fr, gi) => {
    if (gi % STEP || gi < +(process.env.FROM || 0)) return;
    const rgba = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', `_${W}.rgba`)));
    if (process.env.JIT && gi % 3 === 0) { const sh = 4 * (+process.env.JIT > 1 ? +process.env.JIT : 4); rgba.copyWithin(sh, 0, rgba.length - sh); } // JIT=1 — «камера сдвинулась» на 4 пикс. в каждом 3-м кадре
    const gm = new Uint8Array(fs.readFileSync(dir + `/m${String(gi).padStart(3, '0')}_${W}.m`));
    const f0 = 0.75 * Math.max(w, h), ms = detectMarkers(toGray(rgba, w, h), w, h), p = poseFromMarkers(ms, L, { fx: f0, fy: f0, cx: w / 2, cy: h / 2 });
    if (!p || p.n < 2) return;
    eqs.push(...focalEqs(p.H, w / 2, h / 2)); frames.push({ rgba, gm, ms, p, w, h, plate, el: fr.el, dir });
  });
}
const f0 = focalFromEqs(eqs), rf = refineFocal(frames.map((f) => f.p), { fx: f0, fy: f0, cx: w / 2, cy: h / 2 });
const K = { fx: rf.f, fy: rf.f, cx: w / 2, cy: h / 2 };
const good = [];
for (const f of frames) { const p = poseFromMarkers(f.ms, L, K); if (!p || p.rms > 3) continue; f.R = p.R; f.t = p.t; f.K = K; good.push(f); }
let enc = 0; const encByEl = {};
for (const f of good) {
  const m = computeMask(f, { layout: L, mr, Rb: 55, Hb: HB, cutOnly: !WALK, offMat: WALK, clean: f.plate ? [f.plate] : null, enclose: !!process.env.ENC, refOut: true });
  f.refOut = m.refOut; f.mask = m.mask; f.trusted = !!m.stats.enclosed && !process.env.NOTRUST; if (m.stats.enclosed) { enc++; encByEl[f.el] = (encByEl[f.el] || 0) + 1; }
}
if (process.env.MSTAT) {
  const agg = { near: 0, far: 0, farU: 0, farO: 0, farW: 0, fbg: 0, obj: 0 };
  for (const f of good) {
    const gm = f.gm, m = f.mask;
    for (let y = 3; y < h - 3; y++) for (let x = 3; x < w - 3; x++) {
      const i = y * w + x; if (gm[i]) { agg.obj++; if (m[i] === 0) agg.fbg++; continue; }
      if (m[i] === 0) continue;
      let near = false; for (let d = -3; d <= 3 && !near; d++) for (let e = -3; e <= 3; e++) if (gm[i + d * w + e]) { near = true; break; }
      if (near) agg.near++; else { agg.far++; if (m[i] === 1) agg.farU++; else if (m[i] === 2) agg.farO++; else agg.farW++; }
    }
  }
  const k = (v) => (v / good.length).toFixed(0);
  console.log(`на кадр: пикс. предмета ${k(agg.obj)}, ложный фон ${k(agg.fbg)}; ложный «не фон»: у кромки ±3 пикс ${k(agg.near)}, дальше ${k(agg.far)} (неизв. ${k(agg.farU)}, предмет ${k(agg.farO)}, прочее ${k(agg.farW)})`);
}
if (process.env.MF) RC.MOTION_OPT.frac = +process.env.MF; if (process.env.TAUS) RC.MOTION_OPT.tauS = +process.env.TAUS; if (process.env.SFRAC) RC.MOTION_OPT.sFrac = +process.env.SFRAC;
if (!WALK && !process.env.NOMOTION) { console.time('движение'); const mm = motionMasks(good); console.timeEnd('движение'); console.log('движение: групп', mm.groups, 'кадров', mm.used, mm.sizes.join('/'), 'сдвиг камеры', mm.moved); }
const G = carveHull(good, { Rb: 55, Hb: HB }, N, null, process.env.TF ? { trustFrac: +process.env.TF } : {});
console.log(`колпак срезан ${G.capTrim.toFixed(0)} мм, продлён ${G.capExt.toFixed(0)} мм; «движением» вырезано ${(G.motionCut / 1000).toFixed(1)} см³`);
const ideal = good.map((f) => ({ ...f, motion: null, mask: Uint8Array.from(f.gm, (v) => (v ? 2 : 0)) }));
const I = carveHull(ideal, { Rb: 55, Hb: HB }, N, null, { frac: 0, close: 0 });
if (process.env.IDEAL2) { const I2 = carveHull(ideal, { Rb: 55, Hb: HB }, N); let v2 = 0; for (const q of I2.occ) v2 += q; console.log(`точные маски, обычное вырезание: ${(v2 * I2.vs ** 3 / 1000).toFixed(1)} см³`); }
const vs3 = G.vs ** 3 / 1000, layers = [];
let extra = 0, cut = 0, vol = 0, ivol = 0;
const bb = (occ) => { let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9, z1 = -1e9; for (let z = 0; z < G.nz; z++) for (let y = 0; y < G.ny; y++) for (let x = 0; x < G.nx; x++) if (occ[(z * G.ny + y) * G.nx + x]) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); z1 = Math.max(z1, z); } return [(x1 - x0 + 1) * G.vs, (y1 - y0 + 1) * G.vs, (z1 + 1) * G.vs].map((v) => v.toFixed(0)).join('×'); };
for (let z = 0; z < G.nz; z++) {
  const li = Math.floor((z + 0.5) * G.vs / 10); layers[li] = layers[li] || [0, 0];
  for (let i = 0; i < G.nx * G.ny; i++) {
    const a = G.occ[z * G.nx * G.ny + i], b = I.occ[z * G.nx * G.ny + i];
    if (a) vol++; if (b) ivol++;
    if (a && !b) { extra++; layers[li][0]++; } else if (!a && b) { cut++; layers[li][1]++; }
  }
}
console.log(`кадров ${good.length} (замкнуто на листе: ${enc}${Object.keys(encByEl).length ? ' ' + JSON.stringify(encByEl) : ''}), фокус ${rf.f.toFixed(0)}`);
console.log(`объём ${(vol * vs3).toFixed(1)} см³ (точная оболочка ${(ivol * vs3).toFixed(1)}), лишнее ${(extra * vs3).toFixed(1)}, срезано ${(cut * vs3).toFixed(2)}`);
console.log(`габариты ${bb(G.occ)} мм (точная ${bb(I.occ)})`);
console.log('слои 10 мм (лишнее/срезано, см³): ' + layers.map((l, i) => `${i * 10}-${i * 10 + 10}: ${(l[0] * vs3).toFixed(1)}/${(l[1] * vs3).toFixed(2)}`).join('  '));
