import fs from 'fs';
import { matLayout, matRaster } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
import { computeMask } from '../web/js/recon.js';
const dir = process.argv[2], ks = process.argv[3].split(',').map(Number), w = 640;
const gt = JSON.parse(fs.readFileSync(dir + '/gt.json')), h = Math.round(gt.h * w / gt.w);
const L = matLayout('A4', 'round'), mr = matRaster(L, 'light', 2);
const K = { fx: gt.K.fx * w / gt.w, fy: gt.K.fx * w / gt.w, cx: w / 2, cy: h / 2 };
for (const k of ks) {
  const fr = gt.frames[k], rgba = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', '_640.rgba'))), gm = new Uint8Array(fs.readFileSync(dir + `/m${String(k).padStart(3, '0')}_640.m`));
  const ms = detectMarkers(toGray(rgba, w, h), w, h), p = poseFromMarkers(ms, L, K); console.log(k, ms.length, rgba.length, w, h, K);
  const m = computeMask({ rgba, w, h, K, R: p.R, t: p.t }, { layout: L, mr, Rb: 55, Hb: 90, cutOnly: true, offMat: false, enclose: !!process.env.ENC }).mask;
  const o = Buffer.alloc(w * h * 3 * 2);
  const col = { 0: [0, 0, 0], 1: [120, 120, 120], 2: [255, 255, 255], 3: [40, 80, 220], 4: [200, 40, 40] };
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const i = y * w + x; let c = col[m[i]];
    let edge = false; if (x > 0 && y > 0 && x < w - 1 && y < h - 1) edge = gm[i] !== gm[i - 1] || gm[i] !== gm[i - w];
    if (edge) c = [255, 200, 0];
    const a = (y * 2 * w + x) * 3; o[a] = c[0]; o[a + 1] = c[1]; o[a + 2] = c[2];
    const b = (y * 2 * w + w + x) * 3; o[b] = rgba[i * 4]; o[b + 1] = rgba[i * 4 + 1]; o[b + 2] = rgba[i * 4 + 2]; }
  fs.writeFileSync(`/tmp/t/md_${k}.ppm`, Buffer.concat([Buffer.from(`P6\n${2 * w} ${h}\n255\n`), o]));
}
