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
for (const k of [0, 5]) { const f = frames[k]; const o = Buffer.alloc(w * h * 3); for (let i = 0; i < w * h; i++) { const m = f.mask[i]; const c = m === 0 ? [40, 40, 160] : m === 2 ? [230, 60, 60] : [f.rgba[i * 4], f.rgba[i * 4 + 1], f.rgba[i * 4 + 2]]; o[i * 3] = c[0]; o[i * 3 + 1] = c[1]; o[i * 3 + 2] = c[2]; } fs.writeFileSync(`/tmp/t/mask${k}.ppm`, Buffer.concat([Buffer.from(`P6\n${w} ${h}\n255\n`), o])); }
{ const ideal = frames.map((f, k) => { const gm = fs.existsSync(dir + `/m${String(k).padStart(3,'0')}_640.m`) ? new Uint8Array(fs.readFileSync(dir + `/m${String(k).padStart(3,'0')}_640.m`)) : null; if (!gm) return null; const mk = new Uint8Array(w*h); for (let i=0;i<w*h;i++) mk[i] = gm[i] ? 1 : 0; const gt0 = gt.frames[k]; return { ...f, mask: mk }; }).filter(Boolean);
  if (ideal.length) { const Gi = carveHull(ideal, { Rb: 55, Hb: 90 }, N); let v = 0; for (const q of Gi.occ) v += q; console.log('IDEAL hull volume (gt masks, our poses)', (v * Gi.vs ** 3).toFixed(0)); globalThis.Gi = Gi; } }
console.time('hull'); const G = carveHull(frames, { Rb: 55, Hb: 90 }, N); console.timeEnd('hull');
let vox = 0; for (const v of G.occ) vox += v; console.log('hull volume mm3', (vox * G.vs ** 3).toFixed(0), 'true ~100500');
console.time('mesh'); const M = meshFromGrid(G, 1); taubin(M, 10); computeNormals(M); console.timeEnd('mesh');
// объём по сетке (знак = ориентация)
let V = 0; for (let i = 0; i < M.idx.length; i += 3) { const a = M.idx[i] * 3, b = M.idx[i + 1] * 3, c = M.idx[i + 2] * 3, p = M.pos; V += (p[a] * (p[b + 1] * p[c + 2] - p[b + 2] * p[c + 1]) - p[a + 1] * (p[b] * p[c + 2] - p[b + 2] * p[c]) + p[a + 2] * (p[b] * p[c + 1] - p[b + 1] * p[c])) / 6; }
console.log('verts', M.pos.length / 3, 'tris', M.idx.length / 3, 'mesh volume', V.toFixed(0));
console.time('color'); colorize(M, frames); console.timeEnd('color');
fs.writeFileSync('/tmp/t/mesh.json', JSON.stringify({ pos: [...M.pos].map(v => +v.toFixed(2)), idx: [...M.idx], col: [...M.col] }));
{ const { occ, nx, ny, nz, vs, origin } = G;
  for (let z = 0; z < nz; z += 6) { let a = 0, x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9; for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) if (occ[(z * ny + y) * nx + x] > 0.5) { a++; const X = origin[0] + x * vs, Y = origin[1] + y * vs; x0 = Math.min(x0, X); x1 = Math.max(x1, X); y0 = Math.min(y0, Y); y1 = Math.max(y1, Y); }
    const Z = origin[2] + z * vs; let ai=0; if (globalThis.Gi) for (let q=0;q<nx*ny;q++) ai += globalThis.Gi.occ[z*nx*ny+q]; const tr = ai*vs*vs; const tr0 = Z < 42 ? Math.PI * 576 + (Z > 10 && Z < 30 ? 216 : 0) : (Math.abs(Z - 58) < 17 ? Math.PI * (289 - (Z - 58) ** 2) : 0);
    console.log('z', Z.toFixed(0), 'area', (a * vs * vs).toFixed(0), 'true', tr.toFixed(0), 'x', x0.toFixed(0), x1.toFixed(0), 'y', y0.toFixed(0), y1.toFixed(0)); } }
