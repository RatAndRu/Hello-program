// общая часть тестов: синтетическая съёмка → позы → маски → оболочка (как в приложении)
import fs from 'fs';
import { matLayout, matRaster } from '../web/js/mat.js';
import { detectMarkers, toGray } from '../web/js/detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal } from '../web/js/pose.js';
import { computeMask, carveHull } from '../web/js/recon.js';
export function loadSet(dir, Hb = 90, cut = false, W = 640) {
  const L = matLayout('A4', cut ? 'round' : 'full'), mr = matRaster(L, 'light', 2);
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
  return good;
}
export const hullOf = (good, Hb = 90, N = 128) => carveHull(good, { Rb: 55, Hb }, N);
export function meshVolume(M) { let v = 0; const P = M.pos, I = M.idx; for (let i = 0; i < I.length; i += 3) { const a = I[i] * 3, b = I[i + 1] * 3, c = I[i + 2] * 3; v += (P[a] * (P[b + 1] * P[c + 2] - P[b + 2] * P[c + 1]) - P[a + 1] * (P[b] * P[c + 2] - P[b + 2] * P[c]) + P[a + 2] * (P[b] * P[c + 1] - P[b + 1] * P[c])) / 6; } return v; }
export function saveMesh(M, path) { fs.writeFileSync(path, JSON.stringify({ pos: [...M.pos].map((v) => +v.toFixed(2)), idx: [...M.idx], col: [...(M.col || new Uint8Array(M.pos.length).fill(200))] })); }
