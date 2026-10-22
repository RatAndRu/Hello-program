import fs from 'fs';
// v2.2: по умолчанию — те же параметры, что в приложении (peel=1, frac=0.08, major по умолчанию); PEEL/MAJ/FRAC — переопределить
import { matLayout, matRaster } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
import { shellConsistency, vesselCarve, edgeAlpha, revolveGrid, computeMask, carveHull, meshFromGrid, taubin, computeNormals, colorize } from '../web/js/recon.js';
const dir = process.argv[2], W = 640, theme = process.argv[3] || 'light', N = +(process.argv[4] || 128);
const gt = JSON.parse(fs.readFileSync(dir + '/gt.json')); const s = W / gt.w, w = W, h = Math.round(gt.h * s);
const L = matLayout('A4'); const mr = matRaster(L, theme, 2);
let K = { fx: 0.7 * w, fy: 0.7 * w, cx: w / 2, cy: h / 2 };
const frames = []; const eqs = [];
for (const [gi, fr] of gt.frames.entries()) {
  const rgba = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', `_${W}.rgba`)));
  const ms = detectMarkers(toGray(rgba, w, h), w, h); const p = poseFromMarkers(ms, L, K);
  if (!p) continue; eqs.push(...focalEqs(p.H, w / 2, h / 2)); frames.push({ rgba, ms, p, w, h, gi });
}
const f0 = focalFromEqs(eqs); const rf = refineFocal(frames.map(f => f.p), { ...K, fx: f0, fy: f0 }); K = { ...K, fx: rf.f, fy: rf.f };
let clean = null; if (fs.existsSync(dir + '/clean_640.rgba')) clean = new Uint8Array(fs.readFileSync(dir + '/clean_640.rgba'));
console.time('masks');
for (const f of frames) { const p = poseFromMarkers(f.ms, L, K); f.R = p.R; f.t = p.t; f.K = K; f.rms = p.rms; const m = computeMask(f, { layout: L, mr, Rb: 55, Hb: +(process.env.HB || 90), clean, cutOnly: !!process.env.CUT, offMat: process.env.NOOFF ? false : undefined, plainWeak: process.env.NOPW ? false : undefined, plainZone: process.env.PZ ? +process.env.PZ : undefined, peel: process.env.PEEL != null ? +process.env.PEEL : undefined, peelAll: !!process.env.PALL, major: process.env.MAJ != null ? +process.env.MAJ : undefined, edgeRefine: process.env.NOER ? false : undefined }); f.mask = m.mask; f.stats = m.stats; }
console.timeEnd('masks');
// имитация бликов на блестящем предмете: ложный «фон» пятнами внутри предмета
if (process.env.CORRUPT) { let seed = 11; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  frames.forEach((f, k) => { const gm = new Uint8Array(fs.readFileSync(dir + `/m${String(k).padStart(3, '0')}_640.m`)); const pts = []; for (let i = 0; i < w * h; i += 7) if (gm[i]) pts.push(i);
    const nb = +process.env.CORRUPT; for (let b = 0; b < nb; b++) { const c = pts[(rnd() * pts.length) | 0], cx = c % w, cy = (c / w) | 0, r = 3 + rnd() * 6; for (let y = Math.max(0, cy - r | 0); y < Math.min(h, cy + r + 1); y++) for (let x = Math.max(0, cx - r | 0); x < Math.min(w, cx + r + 1); x++) if ((x - cx) ** 2 + (y - cy) ** 2 < r * r && gm[y * w + x]) f.mask[y * w + x] = 0; } }); console.log('corrupted masks with', process.env.CORRUPT, 'blobs/frame'); }
if (process.env.EDGESTAT) { const H = {}; const add = (k) => { H[k] = (H[k] || 0) + 1; };
  frames.forEach((f) => { const p = dir + `/m${String(f.gi).padStart(3, '0')}_640.m`; if (!fs.existsSync(p)) return; const gm = new Uint8Array(fs.readFileSync(p)); const al = edgeAlpha(f);
    for (let y = 4; y < h - 4; y++) for (let x = 4; x < w - 4; x++) { const i = y * w + x; let d = 9;
      for (let dy = -3; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) if ((gm[i + dy * w + dx] ? 1 : 0) !== (gm[i] ? 1 : 0)) d = Math.min(d, Math.max(Math.abs(dx), Math.abs(dy)));
      if (d > 3) continue; const side = gm[i] ? 'obj' : 'bg', m = f.mask[i]; add(`${side}${d} m${m}`); if (m === 1) add(`${side}${d} m1 α${al[i] === 255 ? 'нет' : al[i] < 128 ? '<½' : '≥½'}`); } });
  console.log(Object.keys(H).sort().map((k) => k + ':' + H[k]).join('\n')); }
if (process.env.RMS) console.log('rms', frames.map((f) => f.rms.toFixed(2)).join(' '));
console.log('bgFrac', frames.map(f => f.stats.bgFrac?.toFixed(2)).join(' '));
// сохранить пару масок как картинки
for (const k of (process.env.MK ? process.env.MK.split(',').map(Number) : [0, 5]).filter(k => k < frames.length)) { const f = frames[k]; const o = Buffer.alloc(w * h * 3); for (let i = 0; i < w * h; i++) { const m = f.mask[i]; const c = m === 0 ? [40, 40, 160] : m === 3 ? [90, 160, 90] : m === 2 ? [230, 60, 60] : [f.rgba[i * 4], f.rgba[i * 4 + 1], f.rgba[i * 4 + 2]]; o[i * 3] = c[0]; o[i * 3 + 1] = c[1]; o[i * 3 + 2] = c[2]; } fs.writeFileSync(`/tmp/t/mask${k}.ppm`, Buffer.concat([Buffer.from(`P6\n${w} ${h}\n255\n`), o])); }
if (process.env.MSTAT) { let fb=0, fbB=0, fnb=0, fnbB=0, unkB=0, nobj=0, nB=0;
  frames.forEach((f,k)=>{ const p=dir + `/m${String(frames[k].gi).padStart(3,'0')}_640.m`; if(!fs.existsSync(p)) return; const gm=new Uint8Array(fs.readFileSync(p));
    for (let y=2;y<h-2;y++) for (let x=2;x<w-2;x++){ const i=y*w+x; const o=gm[i]?1:0; let b=false; for(let d=-2;d<=2&&!b;d++) for(let e=-2;e<=2;e++){ if((gm[i+d*w+e]?1:0)!==o){b=true;break;} }
      if(o) nobj++; if(b) nB++; const m=f.mask[i];
      if(o && m===0){ fb++; if(b) fbB++; } if(!o && m!==0){ fnb++; if(b) fnbB++; } if(b && m===1) unkB++; } });
  { const k=5, f=frames[k]; const gm=new Uint8Array(fs.readFileSync(dir + `/m${String(frames[k].gi).padStart(3,'0')}_640.m`)); let o='P6\n'+w+' '+h+'\n255\n'; const buf=Buffer.alloc(w*h*3); for(let i=0;i<w*h;i++){ const g=gm[i]?1:0, m=f.mask[i]; let c=[30,30,90]; if(g&&m===2)c=[200,200,200]; else if(g&&m===1)c=[120,120,120]; else if(g&&m===0)c=[255,0,0]; else if(!g&&m===1)c=[255,220,0]; else if(!g&&m===2)c=[255,0,255]; buf[i*3]=c[0];buf[i*3+1]=c[1];buf[i*3+2]=c[2]; } fs.writeFileSync('err5.ppm', Buffer.concat([Buffer.from(o),buf])); }
  console.log('MSTAT objpx',nobj,'falseBg',fb,'(border',fbB,') falseNotBg',fnb,'(border',fnbB,') borderpx',nB,'unk@border',unkB); }
{ const ideal = frames.map((f, k) => { const gm = fs.existsSync(dir + `/m${String(frames[k].gi).padStart(3,'0')}_640.m`) ? new Uint8Array(fs.readFileSync(dir + `/m${String(frames[k].gi).padStart(3,'0')}_640.m`)) : null; if (!gm) return null; const mk = new Uint8Array(w*h); for (let i=0;i<w*h;i++) mk[i] = gm[i] ? 1 : 0; const gt0 = gt.frames[k]; return { ...f, mask: mk }; }).filter(Boolean);
  if (ideal.length) { const Gi = carveHull(ideal, { Rb: 55, Hb: +(process.env.HB || 90) }, N, null, { frac: 0, close: 0 }); let v = 0; for (const q of Gi.occ) v += q; console.log('IDEAL hull volume (gt masks, our poses)', (v * Gi.vs ** 3).toFixed(0)); globalThis.Gi = Gi; } }
// имитация неточных поз (смаз, «желе» при съёмке с рук): поворот ~0.4°, сдвиг ~1 мм у части кадров
if (process.env.POSEERR) { let seed = 5; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296 - 0.5; };
  const amp = +process.env.POSEERR; frames.forEach((f, k) => { if (k % 2) return; const a = [rnd(), rnd(), rnd()].map(v => v * 0.014 * amp), c = Math.cos, s = Math.sin;
    const Rx = [1,0,0, 0,c(a[0]),-s(a[0]), 0,s(a[0]),c(a[0])], Ry = [c(a[1]),0,s(a[1]), 0,1,0, -s(a[1]),0,c(a[1])];
    const mul = (A, B) => { const C = []; for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) C[i*3+j] = A[i*3]*B[j] + A[i*3+1]*B[3+j] + A[i*3+2]*B[6+j]; return C; };
    f.R = mul(mul(Rx, Ry), f.R); f.t = [f.t[0] + rnd() * 2 * amp, f.t[1] + rnd() * 2 * amp, f.t[2]]; }); console.log('pose errors amp', amp); }
console.time('hull'); const G = process.env.USEIDEAL ? globalThis.Gi : carveHull(frames, { Rb: 55, Hb: +(process.env.HB || 90) }, N, null, { subpix: process.env.SUBPIX !== '0', weighted: process.env.WT !== '0', weakMaj: process.env.WM != null ? +process.env.WM : undefined, frac: process.env.FRAC != null ? +process.env.FRAC : undefined, close: process.env.CLOSE != null ? +process.env.CLOSE : undefined }); console.timeEnd('hull'); console.log('capTrim', G.capTrim); if (process.env.FILL) { const disc = []; let line = ''; for (let z = 0; z < G.nz; z += Math.max(1, Math.round(+(process.env.FSTEP||10) / G.vs))) { let o = 0, d = 0, ro = 0, rd = 0; for (let y = 0; y < G.ny; y++) for (let x = 0; x < G.nx; x++) { const X = G.origin[0] + x * G.vs, Y = G.origin[1] + y * G.vs; if (X * X + Y * Y > 55 * 55) continue; d++; const oc = G.occ[(z * G.ny + y) * G.nx + x] > 0.5 ? 1 : 0; o += oc; if (X * X + Y * Y > (55 - 2 * G.vs) ** 2) { rd++; ro += oc; } } line += `${(z * G.vs).toFixed(0)}:${(o / d).toFixed(2)}/${(ro / rd).toFixed(2)} `; } console.log('FILL', line); } if (globalThis.Gi && G !== globalThis.Gi) { let cut = 0, extra = 0, cutTop = 0; const Gi = globalThis.Gi; for (let i = 0; i < G.occ.length; i++) { if (Gi.occ[i] > 0.5 && G.occ[i] < 0.5) { cut++; if ((i / (G.nx * G.ny) | 0) * G.vs > 45) cutTop++; } if (Gi.occ[i] < 0.5 && G.occ[i] > 0.5) extra++; } const v3 = G.vs ** 3; console.log('CUT mm3', (cut * v3).toFixed(0), 'of which z>45:', (cutTop * v3).toFixed(0), 'EXTRA mm3', (extra * v3).toFixed(0)); }
if (process.env.SHELL) { const c = shellConsistency(G, frames); console.log('shell', Array.from(c).map((v, z) => v === v ? `${(z * G.vs).toFixed(0)}:${v.toFixed(0)}` : '').filter(Boolean).join(' ')); }
if (process.env.VESSEL) { const t0v = Date.now(), r = vesselCarve(G, frames); const { cost, ...rr } = r; console.log('VESSEL', JSON.stringify(rr, (k, v) => typeof v === 'number' ? +v.toFixed(1) : v), (Date.now() - t0v) + 'мс');
  if (cost) console.log('cost', cost.map((c, z) => c === c ? `${(z * G.vs).toFixed(0)}:${c.toFixed(0)}` : '').filter(Boolean).join(' ')); }
let vox = 0; for (const v of G.occ) vox += v; console.log('hull volume mm3', (vox * G.vs ** 3).toFixed(0), 'true ~100500');
console.time('mesh'); const M = meshFromGrid(process.env.REV ? revolveGrid(G) : G, +(process.env.SM || 1)); taubin(M, +(process.env.TB || 10)); computeNormals(M); console.timeEnd('mesh');
// объём по сетке (знак = ориентация)
let V = 0; for (let i = 0; i < M.idx.length; i += 3) { const a = M.idx[i] * 3, b = M.idx[i + 1] * 3, c = M.idx[i + 2] * 3, p = M.pos; V += (p[a] * (p[b + 1] * p[c + 2] - p[b + 2] * p[c + 1]) - p[a + 1] * (p[b] * p[c + 2] - p[b + 2] * p[c]) + p[a + 2] * (p[b] * p[c + 1] - p[b + 1] * p[c])) / 6; }
console.log('verts', M.pos.length / 3, 'tris', M.idx.length / 3, 'mesh volume', V.toFixed(0));
console.time('color'); colorize(M, frames); console.timeEnd('color');
fs.writeFileSync('/tmp/t/mesh.json', JSON.stringify({ pos: [...M.pos].map(v => +v.toFixed(2)), idx: [...M.idx], col: [...M.col] }));
{ const { occ, nx, ny, nz, vs, origin } = G;
  for (let z = 0; z < nz; z += 6) { let a = 0, x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9; for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) if (occ[(z * ny + y) * nx + x] > 0.5) { a++; const X = origin[0] + x * vs, Y = origin[1] + y * vs; x0 = Math.min(x0, X); x1 = Math.max(x1, X); y0 = Math.min(y0, Y); y1 = Math.max(y1, Y); }
    const Z = origin[2] + z * vs; let ai=0; if (globalThis.Gi) for (let q=0;q<nx*ny;q++) ai += globalThis.Gi.occ[z*nx*ny+q]; const tr = ai*vs*vs; const tr0 = Z < 42 ? Math.PI * 576 + (Z > 10 && Z < 30 ? 216 : 0) : (Math.abs(Z - 58) < 17 ? Math.PI * (289 - (Z - 58) ** 2) : 0);
    console.log('z', Z.toFixed(0), 'area', (a * vs * vs).toFixed(0), 'true', tr.toFixed(0), 'x', x0.toFixed(0), x1.toFixed(0), 'y', y0.toFixed(0), y1.toFixed(0)); } }
