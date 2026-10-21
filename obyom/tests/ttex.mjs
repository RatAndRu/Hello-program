// Текстура-атлас против цвета вершин: рендер модели в «отложенных» ракурсах (не участвовали в обработке)
// и сравнение с настоящими кадрами сцены (PSNR по пикселям предмета).
// node ttex.mjs /tmp/t/st120 [N=128]   (нужны f*_640.rgba и f*_1280.rgba — toraw.py dir 640 / 1280)
import fs from 'fs';
import { matLayout, matRaster } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
import { computeMask, carveHull, meshFromGrid, taubin, computeNormals, colorize } from '../web/js/recon.js';
import { bakeTexture } from '../web/js/texture.js';
const dir = process.argv[2], N = +(process.argv[3] || 128), W = 640, SW = +(process.env.SW || 1280);
const gt = JSON.parse(fs.readFileSync(dir + '/gt.json')), w = W, h = Math.round(gt.h * W / gt.w), sh = Math.round(gt.h * SW / gt.w);
const L = matLayout('A4', 'full'), mr = matRaster(L, 'light', 2);
let K = { fx: 0.7 * w, fy: 0.7 * w, cx: w / 2, cy: h / 2 };
const frames = [], eqs = [], hold = [];
for (const [gi, fr] of gt.frames.entries()) {
  if (gi % 10 === 5) { hold.push(gi); continue; }
  const rgba = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', `_${W}.rgba`)));
  const ms = detectMarkers(toGray(rgba, w, h), w, h), p = poseFromMarkers(ms, L, K);
  if (p && p.n >= 2) { eqs.push(...focalEqs(p.H, w / 2, h / 2)); frames.push({ rgba, ms, p, w, h, gi, blob: dir + '/' + fr.file.replace('.jpg', `_${SW}.rgba`), srcW: SW, srcH: sh }); }
}
const f0 = focalFromEqs(eqs), rf = refineFocal(frames.map((f) => f.p), { ...K, fx: f0, fy: f0 }); K = { ...K, fx: rf.f, fy: rf.f };
const good = [];
for (const f of frames) { const p = poseFromMarkers(f.ms, L, K); if (!p || p.rms > 3) continue; f.R = p.R; f.t = p.t; f.K = K; f.rms = p.rms; f.mask = computeMask(f, { layout: L, mr, Rb: 55, Hb: 90 }).mask; good.push(f); }
const G = carveHull(good, { Rb: 55, Hb: 90 }, N);
const M = meshFromGrid(G, 3); taubin(M, 30); computeNormals(M); colorize(M, good);
console.log(`кадров ${good.length}, отложено ${hold.length}, треугольников ${M.idx.length / 3}, вершин ${M.pos.length / 3}`);
let texFr = good;
if (process.env.CLOSE) { // крупные планы: позы по меткам с тем же фокусом, без масок
  const cg = JSON.parse(fs.readFileSync(process.env.CLOSE + '/gt.json'));
  for (const fr of cg.frames) { const rgba = new Uint8Array(fs.readFileSync(process.env.CLOSE + '/' + fr.file.replace('.jpg', `_${W}.rgba`))); const ms = detectMarkers(toGray(rgba, w, h), w, h), p = poseFromMarkers(ms, L, K);
    if (p && p.n >= 3 && p.rms < 2) texFr = texFr.concat([{ rgba, w, h, R: p.R, t: p.t, K, rms: p.rms, close: true, blob: process.env.CLOSE + '/' + fr.file.replace('.jpg', `_${SW}.rgba`), srcW: SW, srcH: sh }]); }
  console.log('крупных планов', texFr.length - good.length);
}
let t0 = Date.now();
const r = await bakeTexture(M, texFr, { debug: !!process.env.DBG, consist: process.env.PC != null ? +process.env.PC : undefined, smooth: process.env.LAM != null ? +process.env.LAM : undefined, size: +(process.env.TEX || 2048), decode: async (p) => ({ rgba: new Uint8Array(fs.readFileSync(p)), w: SW, h: sh }) });
console.log(`атлас ${r.T}×${r.T}, лоскутов ${r.info.charts}, кадров ${r.info.frames}, масштаб ${r.info.scale.toFixed(2)}, невидимых граней ${r.info.unseen}, ${((Date.now() - t0) / 1000).toFixed(1)} с; вершин стало ${r.mesh.pos.length / 3}`);
if (process.env.GLB) { // GLB с текстурой: JPEG через PIL, проверка gltf-validator
  const { execFileSync } = await import('child_process'); const { createRequire } = await import('module');
  fs.writeFileSync('/tmp/t/atlas.rgba', r.atlas);
  execFileSync('python3', ['-c', `import numpy as np; from PIL import Image; a=np.fromfile('/tmp/t/atlas.rgba',np.uint8).reshape(${r.T},${r.T},4); Image.fromarray(a[:,:,:3]).save('/tmp/t/atlas.jpg',quality=90)`]);
  const { toGLB, toOBJ } = await import('../web/js/export.js');
  const Mt = { ...r.mesh, tex: { w: r.T, h: r.T, jpg: new Uint8Array(fs.readFileSync('/tmp/t/atlas.jpg')) } };
  const glb = toGLB(Mt, 'Тест'); fs.writeFileSync('/tmp/t/tex.glb', glb);
  const v = createRequire('/tmp/tools/')('gltf-validator'); const rep = await v.validateBytes(new Uint8Array(glb));
  console.log('GLB с текстурой', glb.length, 'ошибок', rep.issues.numErrors, 'предупреждений', rep.issues.numWarnings, rep.issues.messages.slice(0, 5).map((m) => m.code + ' ' + m.message).join(' | '));
  const o = toOBJ(Mt, 'tex'); console.log('OBJ', o.obj.length, 'MTL', new TextDecoder().decode(o.mtl).split('\n').pop() || new TextDecoder().decode(o.mtl).trim().split('\n').pop(), 'JPG', o.jpg.length);
}
if (process.env.ATLAS) { fs.writeFileSync('/tmp/t/atlas.rgba', r.atlas); console.log('atlas → /tmp/t/atlas.rgba', r.T); }
// программный рендер: цвет вершин или текстура, перспективно-правильная интерполяция
function render(Mx, R, t, Kr, rw, rh, tex) {
  const img = new Float32Array(rw * rh * 3), zb = new Float32Array(rw * rh).fill(1e9), P = new Float32Array(Mx.pos.length);
  for (let i = 0; i < Mx.pos.length; i += 3) { const X = Mx.pos[i], Y = Mx.pos[i + 1], Z = Mx.pos[i + 2], cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; P[i] = Kr.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + Kr.cx; P[i + 1] = Kr.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + Kr.cy; P[i + 2] = cz; }
  for (let f = 0; f < Mx.idx.length; f += 3) {
    const a = Mx.idx[f], b = Mx.idx[f + 1], c = Mx.idx[f + 2];
    const x0 = P[a * 3], y0 = P[a * 3 + 1], x1 = P[b * 3], y1 = P[b * 3 + 1], x2 = P[c * 3], y2 = P[c * 3 + 1];
    const den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2); if (Math.abs(den) < 1e-9) continue;
    const mnx = Math.max(0, Math.floor(Math.min(x0, x1, x2))), mxx = Math.min(rw - 1, Math.ceil(Math.max(x0, x1, x2))), mny = Math.max(0, Math.floor(Math.min(y0, y1, y2))), mxy = Math.min(rh - 1, Math.ceil(Math.max(y0, y1, y2)));
    for (let y = mny; y <= mxy; y++) for (let x = mnx; x <= mxx; x++) {
      const px = x + 0.5, py = y + 0.5, l0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / den, l1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / den, l2 = 1 - l0 - l1;
      if (l0 < 0 || l1 < 0 || l2 < 0) continue;
      const iz = l0 / P[a * 3 + 2] + l1 / P[b * 3 + 2] + l2 / P[c * 3 + 2], z = 1 / iz, j = y * rw + x; if (z >= zb[j]) continue; zb[j] = z;
      const w0 = l0 / P[a * 3 + 2] * z, w1 = l1 / P[b * 3 + 2] * z, w2 = l2 / P[c * 3 + 2] * z;
      if (tex) {
        const U = (w0 * Mx.uv[a * 2] + w1 * Mx.uv[b * 2] + w2 * Mx.uv[c * 2]) * tex.T - 0.5, V = (w0 * Mx.uv[a * 2 + 1] + w1 * Mx.uv[b * 2 + 1] + w2 * Mx.uv[c * 2 + 1]) * tex.T - 0.5;
        const ux = Math.max(0, Math.min(tex.T - 2, Math.floor(U))), vy = Math.max(0, Math.min(tex.T - 2, Math.floor(V))), fx = U - ux, fy = V - vy, o = (vy * tex.T + ux) * 4, s = tex.T * 4;
        for (let ch = 0; ch < 3; ch++) img[j * 3 + ch] = (tex.a[o + ch] * (1 - fx) + tex.a[o + 4 + ch] * fx) * (1 - fy) + (tex.a[o + s + ch] * (1 - fx) + tex.a[o + s + 4 + ch] * fx) * fy;
      } else for (let ch = 0; ch < 3; ch++) img[j * 3 + ch] = w0 * Mx.col[a * 3 + ch] + w1 * Mx.col[b * 3 + ch] + w2 * Mx.col[c * 3 + ch];
    }
  }
  return { img, zb };
}
// оценка в отложенных ракурсах: истинная поза из gt.json (в пикселях 1280 → масштаб RW)
const RW = +(process.env.RW || 1280), RH = Math.round(gt.h * RW / gt.w), ks = RW / gt.w;
const Kr = { fx: gt.K.fx * ks, fy: gt.K.fy * ks, cx: gt.K.cx * ks, cy: gt.K.cy * ks };
let sV = 0, sT = 0, nP = 0, sG = 0;
const shots = [];
for (const gi of hold) {
  const fr = gt.frames[gi];
  const ref = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', `_${RW}.rgba`)));
  const gm = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('f', 'm').replace('.jpg', `_${RW}.m`)));
  const A = render(M, fr.R, fr.t, Kr, RW, RH, null), B = render(r.mesh, fr.R, fr.t, Kr, RW, RH, { a: r.atlas, T: r.T });
  // только внутренние пиксели предмета (2 px от края маски) — там, где форма точно верна
  let eV = 0, eT = 0, n = 0, gV = 0, gT = 0;
  for (let y = 3; y < RH - 3; y++) for (let x = 3; x < RW - 3; x++) {
    const j = y * RW + x; if (!gm[j] || !gm[j - 3] || !gm[j + 3] || !gm[j - 3 * RW] || !gm[j + 3 * RW] || A.zb[j] > 1e8 || B.zb[j] > 1e8) continue;
    for (let ch = 0; ch < 3; ch++) { const g0 = ref[j * 4 + ch]; eV += (A.img[j * 3 + ch] - g0) ** 2; eT += (B.img[j * 3 + ch] - g0) ** 2; }
    // резкость (градиент) — детали текстуры
    const gr = (im, k) => Math.abs(im[k * 3] - im[(k + 1) * 3]) + Math.abs(im[k * 3] - im[(k + RW) * 3]);
    gV += gr(A.img, j); gT += gr(B.img, j); sG += Math.abs(ref[j * 4] - ref[(j + 1) * 4]) + Math.abs(ref[j * 4] - ref[(j + RW) * 4]);
    n++;
  }
  const psV = 10 * Math.log10(255 * 255 / (eV / (3 * n))), psT = 10 * Math.log10(255 * 255 / (eT / (3 * n)));
  console.log(`ракурс ${gi}: PSNR цвет вершин ${psV.toFixed(2)} дБ, текстура ${psT.toFixed(2)} дБ; резкость ${(gV / n).toFixed(1)} → ${(gT / n).toFixed(1)}`);
  sV += eV; sT += eT; nP += 3 * n;
  shots.push({ gi, A, B, ref });
}
console.log(`ИТОГО PSNR: цвет вершин ${(10 * Math.log10(255 * 255 / (sV / nP))).toFixed(2)} дБ, текстура ${(10 * Math.log10(255 * 255 / (sT / nP))).toFixed(2)} дБ`);
if (process.env.SHOT) { // кадр: эталон | цвет вершин | текстура (raw RGB, склеить toPng в python)
  const s = shots[+process.env.SHOT || 0], o = Buffer.alloc(RW * 3 * RH * 3);
  for (let y = 0; y < RH; y++) for (let x = 0; x < RW; x++) { const j = y * RW + x; for (let ch = 0; ch < 3; ch++) { o[(y * RW * 3 + x) * 3 + ch] = s.ref[j * 4 + ch]; o[(y * RW * 3 + RW + x) * 3 + ch] = s.A.zb[j] < 1e8 ? s.A.img[j * 3 + ch] : 20; o[(y * RW * 3 + 2 * RW + x) * 3 + ch] = s.B.zb[j] < 1e8 ? s.B.img[j * 3 + ch] : 20; } }
  fs.writeFileSync('/tmp/t/texshot.rgb', o); console.log('кадр → /tmp/t/texshot.rgb', RW * 3, RH);
}
