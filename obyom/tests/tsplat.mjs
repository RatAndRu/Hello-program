import fs from 'fs';
import { matLayout, matRaster } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
import { computeMask, carveHull, meshFromGrid, taubin, computeNormals, colorize } from '../web/js/recon.js';
const dir = process.argv[2], W = 640, theme = process.argv[3] || 'light', N = +(process.argv[4] || 128);
const gt = JSON.parse(fs.readFileSync(dir + '/gt.json')); const s = W / gt.w, w = W, h = Math.round(gt.h * s);
const L = matLayout('A4'); const mr = matRaster(L, theme, 2);
let K = { fx: 0.7 * w, fy: 0.7 * w, cx: w / 2, cy: h / 2 };
const frames = []; const eqs = [];
for (const fr of gt.frames) {
  const rgba = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', `_${W}.rgba`)));
  const ms = detectMarkers(toGray(rgba, w, h), w, h); const p = poseFromMarkers(ms, L, K);
  if (!p) continue; eqs.push(...focalEqs(p.H, w / 2, h / 2)); frames.push({ rgba, ms, p, w, h });
}
const f0 = focalFromEqs(eqs); const rf = refineFocal(frames.map(f => f.p), { ...K, fx: f0, fy: f0 }); K = { ...K, fx: rf.f, fy: rf.f };
let clean = null; if (fs.existsSync(dir + '/clean_640.rgba')) clean = new Uint8Array(fs.readFileSync(dir + '/clean_640.rgba'));
console.time('masks');
for (const f of frames) { const p = poseFromMarkers(f.ms, L, K); f.R = p.R; f.t = p.t; f.K = K; const m = computeMask(f, { layout: L, mr, Rb: 55, Hb: 90, clean }); f.mask = m.mask; f.stats = m.stats; }
console.timeEnd('masks');
console.log('bgFrac', frames.map(f => f.stats.bgFrac?.toFixed(2)).join(' '));
// сохранить пару масок как картинки
{ const ideal = frames.map((f, k) => { const gm = fs.existsSync(dir + `/m${String(k).padStart(3,'0')}_640.m`) ? new Uint8Array(fs.readFileSync(dir + `/m${String(k).padStart(3,'0')}_640.m`)) : null; if (!gm) return null; const mk = new Uint8Array(w*h); for (let i=0;i<w*h;i++) mk[i] = gm[i] ? 1 : 0; const gt0 = gt.frames[k]; return { ...f, mask: mk }; }).filter(Boolean);
  if (ideal.length) { const Gi = carveHull(ideal, { Rb: 55, Hb: 90 }, N); let v = 0; for (const q of Gi.occ) v += q; console.log('IDEAL hull volume (gt masks, our poses)', (v * Gi.vs ** 3).toFixed(0)); globalThis.Gi = Gi; } }
console.time('hull'); const G = carveHull(frames, { Rb: 55, Hb: 90 }, N); console.timeEnd('hull');
let vox = 0; for (const v of G.occ) vox += v; console.log('hull volume mm3', (vox * G.vs ** 3).toFixed(0), 'true ~100500');
console.time('mesh'); const M = meshFromGrid(G, 1); taubin(M, 6); computeNormals(M); console.timeEnd('mesh');
// объём по сетке (знак = ориентация)
let V = 0; for (let i = 0; i < M.idx.length; i += 3) { const a = M.idx[i] * 3, b = M.idx[i + 1] * 3, c = M.idx[i + 2] * 3, p = M.pos; V += (p[a] * (p[b + 1] * p[c + 2] - p[b + 2] * p[c + 1]) - p[a + 1] * (p[b] * p[c + 2] - p[b + 2] * p[c]) + p[a + 2] * (p[b] * p[c + 1] - p[b + 1] * p[c])) / 6; }
console.log('verts', M.pos.length / 3, 'tris', M.idx.length / 3, 'mesh volume', V.toFixed(0));
console.time('color'); colorize(M, frames); console.timeEnd('color');
import { initFromMesh, Trainer, splatViews, nearHull, allowedRegion, renderView, toPLY } from '../web/js/splat.js';
import { depthMap } from '../web/js/recon.js';
const ITERS = +(process.argv[5] || 1500);
const test = frames.filter((_, k) => k % 6 === 3), train = frames.filter((_, k) => k % 6 !== 3);
const S = initFromMesh(M, +(process.env.N0||8000)); console.log('init splats', S.n);
const SV = splatViews(M, train, depthMap); console.log("views", SV.length, "avg px", (SV.reduce((a, v) => a + v.cw * v.ch, 0) / SV.length) | 0);
const tr = new Trainer(S, SV, { iters: ITERS, extent: 100, maxN: +(process.env.NMAX||20000), inside: allowedRegion(G, train, 2) });
// оценка: PSNR на тестовых кадрах внутри GT-маски объекта
const TV = splatViews(M, test, depthMap);
const evalP = () => { let se = 0, n = 0; TV.forEach((v, k) => { const gm = new Uint8Array(fs.readFileSync(dir + `/m${String(frames.indexOf(test[k])).padStart(3, '0')}_640.m`)); const o = renderView(S, { ...v, bg: v.img }).out; for (let y = 0; y < v.ch; y++) for (let x = 0; x < v.cw; x++) { const gi = (y + v.y0) * w + x + v.x0; if (!gm[gi]) continue; const j = y * v.cw + x; for (let c = 0; c < 3; c++) { const d = o[j * 3 + c] - v.img[j * 3 + c]; se += d * d; n++; } } }); return (10 * Math.log10(n / se)).toFixed(2); };
console.log('PSNR before', evalP());
const t0 = Date.now();
for (let i = 1; i <= ITERS; i++) { tr.step(); if (i % 250 === 0) { const L = tr.losses.slice(-250).reduce((a, b) => a + b, 0) / 250; console.log('it', i, 'loss', L.toFixed(4), 'n', S.n, 'ms/it', ((Date.now() - t0) / i).toFixed(1), 'PSNR', evalP()); } }
const nb = S.n; tr.finalize(allowedRegion(G, train, 1.5, 1)); console.log('final prune', nb, '->', S.n, 'PSNR', evalP());
fs.writeFileSync('/tmp/t/splats.ply', Buffer.from(toPLY(S)));
// картинки: тест-кадр, сплэты, сетка-цвет для сравнения
const rows = TV.slice(0, 3).map(v => { const o = renderView(S, { ...v, bg: new Float32Array(v.img.length).fill(0.12) }).out; return { v, o }; });
const Wt = rows.reduce((a, r) => a + r.v.cw, 0), Ht = Math.max(...rows.map(r => r.v.ch)) * 2;
const im = Buffer.alloc(Wt * Ht * 3); let ox = 0;
for (const { v, o } of rows) { for (let y = 0; y < v.ch; y++) for (let x = 0; x < v.cw; x++) for (let c = 0; c < 3; c++) { im[((y) * Wt + ox + x) * 3 + c] = v.img[(y * v.cw + x) * 3 + c] * 255; im[((y + Ht / 2) * Wt + ox + x) * 3 + c] = Math.min(255, o[(y * v.cw + x) * 3 + c] * 255); } ox += v.cw; }
fs.writeFileSync('/tmp/t/splat.ppm', Buffer.concat([Buffer.from(`P6\n${Wt} ${Ht}\n255\n`), im]));
