// Подбор параметров сплэтов на синтетике: та же подготовка, что в приложении (метки → фокус → позы → маски → оболочка → сетка),
// каждый 6-й кадр — проверочный (в обучении не участвует).
// node tsplat2.mjs /tmp/t/spT        (WALK=1 — съёмка с рук, лист целиком)
// env: BATCH=1 (кадров на шаг) MEDW=1 (вес фона-медианы за листом, 0 — выкл.) ITERS=1200 N0=8000 NMAX=20000 DEG=1 AW=0.5 DW=0.02 FLAT=0.1 EXPO=1 LRDC=0.012 LRREST=0.0012 STEP=1 HB=90 PLY=путь PPM=путь
// Метрики на проверочных кадрах (яркость кадра подбирается МНК — у отложенного кадра своя экспозиция):
//   PSNR — внутри точной маски предмета; облачка — средняя непрозрачность капель на точном фоне (в рамке предмета);
//   дыры — средняя прозрачность T на точном предмете; мс/шаг.
import fs from 'fs';
import { matLayout, matRaster } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
import { computeMask, motionMasks, carveHull, meshFromGrid, taubin, computeNormals, colorize, depthMap } from '../web/js/recon.js';
import { initFromMesh, Trainer, splatViews, allowedRegion, renderView, packSplats, plyFromPacked, SPLAT_DEFAULTS } from '../web/js/splat.js';

const E = process.env, dirs = process.argv.slice(2), W = 640, STEP = +(E.STEP || 1), HB = +(E.HB || 90);
const WALK = !!E.WALK, L = matLayout('A4', WALK ? 'full' : 'round'), mr = matRaster(L, 'light', 2);
const frames = [], eqs = [];
let w = 0, h = 0;
for (const dir of dirs) {
  const gt = JSON.parse(fs.readFileSync(dir + '/gt.json'));
  w = W; h = Math.round(gt.h * W / gt.w);
  gt.frames.forEach((fr, gi) => {
    if (gi % STEP || gi < +(E.FROM || 0)) return;
    const rgba = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', `_${W}.rgba`)));
    const gm = new Uint8Array(fs.readFileSync(dir + `/m${String(gi).padStart(3, '0')}_${W}.m`));
    const f0 = 0.75 * Math.max(w, h), ms = detectMarkers(toGray(rgba, w, h), w, h), p = poseFromMarkers(ms, L, { fx: f0, fy: f0, cx: w / 2, cy: h / 2 });
    if (!p || p.n < 2) return;
    eqs.push(...focalEqs(p.H, w / 2, h / 2)); frames.push({ rgba, gm, ms, p, w, h, gi });
  });
}
const f0 = focalFromEqs(eqs), rf = refineFocal(frames.map((f) => f.p), { fx: f0, fy: f0, cx: w / 2, cy: h / 2 });
const K = { fx: rf.f, fy: rf.f, cx: w / 2, cy: h / 2 };
const good = [];
for (const f of frames) { const p = poseFromMarkers(f.ms, L, K); if (!p || p.rms > 3) continue; f.R = p.R; f.t = p.t; f.K = K; good.push(f); }
for (const f of good) {
  const m = computeMask(f, { layout: L, mr, Rb: 55, Hb: HB, cutOnly: !WALK, offMat: WALK, enclose: true, refOut: !WALK });
  f.mask = m.mask; f.refOut = m.refOut; f.trusted = !!m.stats.enclosed;
}
if (!WALK) motionMasks(good);
const G = carveHull(good, { Rb: 55, Hb: HB }, 128);
const M = meshFromGrid(G, 3); taubin(M, 30); computeNormals(M); colorize(M, good);
const test = good.filter((_, k) => k % 6 === 3), train = good.filter((_, k) => k % 6 !== 3);
const num = (k, d) => (E[k] !== undefined ? +E[k] : d);
const opt = {
  deg: num('DEG', SPLAT_DEFAULTS.deg), alphaW: num('AW', SPLAT_DEFAULTS.alphaW), depthW: num('DW', SPLAT_DEFAULTS.depthW), flat: num('FLAT', SPLAT_DEFAULTS.flat),
  clean: E.CLEAN !== '0', // v2.3: чистка облачков по согласию кадров
  batch: num('BATCH', 1), // кадров на шаг (v2.1: в приложении — по потоку на кадр)
  expo: E.EXPO !== undefined ? E.EXPO !== '0' : SPLAT_DEFAULTS.expo, lrDC: num('LRDC', SPLAT_DEFAULTS.lrDC), lrRest: num('LRREST', SPLAT_DEFAULTS.lrRest),
};
const ITERS = num('ITERS', 1200);
const S = initFromMesh(M, num('N0', 8000), opt.deg);
const vopt = { ...(E.MEDW !== undefined ? { medW: +E.MEDW } : {}), farHull: E.FAR !== '0' };
const SV = splatViews(M, train, depthMap, vopt);
if (E.DBGFAR) { const S0 = splatViews(M, train, depthMap, { ...vopt, farHull: false }); let ch = 0, all = 0, z0 = 0, gtObj = 0;
  SV.forEach((v, k) => { const f = train[k]; for (let j = 0; j < v.at.length; j++) { all++; if (v.at[j] === 0) z0++; if (v.at[j] !== S0[k].at[j]) { ch++; const x = j % v.cw + v.x0, y = (j / v.cw | 0) + v.y0; if (f.gm && f.gm[y * f.w + x]) gtObj++; } } });
  console.log(`farHull: изменено ${ch} пикс. из ${all} (${(100 * ch / all).toFixed(2)}%), из них на настоящем предмете ${gtObj}; цель «прозрачно» всего ${(100 * z0 / all).toFixed(1)}%`); process.exit(0); }
const tr = new Trainer(S, SV, { ...opt, iters: ITERS, extent: 110, maxN: num('NMAX', 20000), inside: allowedRegion(G, train, 2) });
const TV = splatViews(M, test, depthMap, vopt);

function evaluate() {
  let se = 0, nse = 0, fl = 0, nfl = 0, ho = 0, nho = 0;
  for (const v of TV) {
    const gm = v.src.gm, zero = new Float32Array(v.img.length);
    const { out, T } = renderView(S, { ...v, bg: zero, gain: [1, 1, 1] });
    // яркость кадра: img ≈ g·out + T·img (на предмете T≈0) — МНК по каналам
    const g = [0, 0, 0], a = [0, 0, 0], b = [0, 0, 0];
    for (let y = 0; y < v.ch; y++) for (let x = 0; x < v.cw; x++) {
      const j = y * v.cw + x, gi = (y + v.y0) * w + x + v.x0; if (!gm[gi]) continue;
      for (let c = 0; c < 3; c++) { const r = out[j * 3 + c], t = v.img[j * 3 + c] * (1 - T[j]); a[c] += r * t; b[c] += r * r; }
    }
    for (let c = 0; c < 3; c++) g[c] = b[c] > 0 ? Math.min(2, Math.max(0.5, a[c] / b[c])) : 1;
    for (let y = 0; y < v.ch; y++) for (let x = 0; x < v.cw; x++) {
      const j = y * v.cw + x, gi = (y + v.y0) * w + x + v.x0;
      if (gm[gi]) {
        for (let c = 0; c < 3; c++) { const d = g[c] * out[j * 3 + c] + T[j] * v.img[j * 3 + c] - v.img[j * 3 + c]; se += d * d; nse++; }
        ho += T[j]; nho++;
      } else {
        // фон у самой кромки (±2 пикс) не считаем — там и точная маска спорна
        let near = false; for (let d = -2; d <= 2 && !near; d++) for (let e = -2; e <= 2; e++) { const q = gi + d * w + e; if (q >= 0 && q < gm.length && gm[q]) { near = true; break; } }
        if (!near) { fl += 1 - T[j]; nfl++; }
      }
    }
  }
  return { psnr: 10 * Math.log10(nse / Math.max(1e-12, se)), floaters: fl / Math.max(1, nfl), holes: ho / Math.max(1, nho) };
}
const fmt = (r) => `PSNR ${r.psnr.toFixed(2)} облачка ${(100 * r.floaters).toFixed(2)}% дыры ${(100 * r.holes).toFixed(2)}%`;
console.log(`кадров ${good.length} (обучение ${SV.length}, проверка ${TV.length}), капель ${S.n}, параметры ${JSON.stringify(opt)} шагов ${ITERS}`);
console.log('до обучения:', fmt(evaluate()));
const t0 = Date.now(); let tTrain = 0;
for (let i = 1; i <= ITERS; i++) {
  const ts = Date.now(); tr.step(); tTrain += Date.now() - ts;
  if (E.VERB && i % 300 === 0) console.log('шаг', i, 'капель', S.n, fmt(evaluate()));
}
tr.finalize(allowedRegion(G, train, 1.5, 1));
const r = evaluate();
console.log(`ИТОГ: ${fmt(r)} капель ${S.n} убрано облачков ${tr.cleaned || 0} мс/шаг ${(tTrain / ITERS).toFixed(1)} всего ${((Date.now() - t0) / 1000).toFixed(0)} с`);
if (E.PLY) fs.writeFileSync(E.PLY, Buffer.from(plyFromPacked(packSplats(S))));
if (E.PPM) { // верх — проверочные кадры, низ — сплэты на сером
  const rows = TV.slice(0, 4).map((v) => ({ v, o: renderView(S, { ...v, bg: new Float32Array(v.img.length).fill(0.12), gain: [1, 1, 1] }).out }));
  const Wt = rows.reduce((a, q) => a + q.v.cw, 0), Hh = Math.max(...rows.map((q) => q.v.ch)), im = Buffer.alloc(Wt * Hh * 2 * 3);
  let ox = 0;
  for (const { v, o } of rows) { for (let y = 0; y < v.ch; y++) for (let x = 0; x < v.cw; x++) for (let c = 0; c < 3; c++) { im[(y * Wt + ox + x) * 3 + c] = v.img[(y * v.cw + x) * 3 + c] * 255; im[((y + Hh) * Wt + ox + x) * 3 + c] = Math.min(255, o[(y * v.cw + x) * 3 + c] * 255); } ox += v.cw; }
  fs.writeFileSync(E.PPM, Buffer.concat([Buffer.from(`P6\n${Wt} ${Hh * 2}\n255\n`), im]));
}
