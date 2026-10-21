import fs from 'fs';
import { matLayout } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, camAngles, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
const dir = process.argv[2], W = +process.argv[3] || 640;
const gt = JSON.parse(fs.readFileSync(dir + '/gt.json')); const s = W / gt.w, w = W, h = Math.round(gt.h * s);
const L = matLayout('A4');
const Ktrue = { fx: gt.K.fx * s, fy: gt.K.fy * s, cx: w / 2, cy: h / 2 };
let K = { fx: 0.7 * w, fy: 0.7 * w, cx: w / 2, cy: h / 2 };
const res = []; let eqs = []; let tdet = 0;
for (const fr of gt.frames) {
  const buf = new Uint8Array(fs.readFileSync(dir + '/' + fr.file.replace('.jpg', `_${W}.rgba`)));
  const g = toGray(buf, w, h);
  const t0 = performance.now(); const ms = detectMarkers(g, w, h); tdet += performance.now() - t0;
  const p = poseFromMarkers(ms, L, K);
  if (p) eqs.push(...focalEqs(p.H, w / 2, h / 2));
  res.push({ fr, ms, p });
}
const f0 = focalFromEqs(eqs); console.log('focal closed-form', f0.toFixed(1), 'true', Ktrue.fx.toFixed(1), 'det ms/frame', (tdet / gt.frames.length).toFixed(1));
const good = res.filter(r => r.p);
const rf = refineFocal(good.map(r => r.p), { ...K, fx: f0, fy: f0 }); console.log('focal refined', rf.f.toFixed(1), 'rms', rf.rms.toFixed(3));
K = { ...K, fx: rf.f, fy: rf.f };
let errs = [];
for (const r of res) {
  const p = r.p && poseFromMarkers(r.ms, L, K);
  if (!p) { console.log(r.fr.file, 'NO POSE', r.ms.length); continue; }
  const a = camAngles(p.R, p.t), b = camAngles(r.fr.R, r.fr.t.map(v => v));
  const dc = Math.hypot(a.c[0] - b.c[0], a.c[1] - b.c[1], a.c[2] - b.c[2]);
  errs.push(dc);
  console.log(r.fr.file, 'markers', r.ms.length, 'rms', p.rms.toFixed(2), 'camErr mm', dc.toFixed(2), 'az', a.az.toFixed(1), b.az.toFixed(1), 'el', a.el.toFixed(1), b.el.toFixed(1));
}
errs.sort((a, b) => a - b); console.log('median cam err mm', errs[errs.length >> 1].toFixed(2), 'max', errs.at(-1).toFixed(2));
