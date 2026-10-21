// Объём — конвейер обработки: кадры → позы камеры → маски → оболочка → сетка → цвет → (сплэты).
// Один и тот же код работает в фоновом потоке (worker.js) и, если поток недоступен, в основном.
import { matLayout, matRaster } from './mat.js';
import { detectMarkers, toGray } from './detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal, camAngles } from './pose.js';
import { computeMask, carveHull, meshFromGrid, revolveGrid, taubin, computeNormals, colorize, depthMap } from './recon.js';
import { initFromMesh, Trainer, splatViews, allowedRegion, packSplats } from './splat.js';

export const PROC_W = 640;
const tick = () => new Promise((r) => setTimeout(r, 0));

export async function decodeBlob(blob, W) {
  const bmp = await createImageBitmap(blob);
  const w = W, h = Math.round(bmp.height * W / bmp.width);
  const cv = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(w, h) : Object.assign(document.createElement('canvas'), { width: w, height: h });
  const cx = cv.getContext('2d', { willReadFrequently: true });
  cx.imageSmoothingQuality = 'high';
  cx.drawImage(bmp, 0, 0, w, h); bmp.close && bmp.close();
  return { rgba: new Uint8Array(cx.getImageData(0, 0, w, h).data.buffer), w, h };
}

// job: {blobs:[Blob], mode:'mesh'|'splat'|'both', quality:'fast'|'normal'|'best', size:'A4'|'A3'|'A2', theme, Hb,
//       method:'walk'|'turn', shape:'normal'|'revolve'|'smooth', scale:[sx, sy] — поправка масштаба печати}
// cb: {progress(stage, p, text), preview(packed), log(text)}; shouldStop() → true — прервать
export async function runPipeline(job, cb, shouldStop = () => false) {
  const t0 = Date.now(), log = (s) => cb.log && cb.log(`${((Date.now() - t0) / 1000).toFixed(1)} с · ${s}`);
  // на вертушке угловые метки не используются: лист может свисать со столика или быть вырезан по кругу
  const turn = job.method === 'turn';
  const L = matLayout(job.size || 'A4', turn ? 'round' : 'full'), mr = matRaster(L, job.theme || 'light', 2);
  const Rb = 55 * L.k, Hb = job.Hb || 90 * L.k;
  const Q = { fast: { N: 112, iters: 600, n0: 6000, nmax: 14000 }, normal: { N: 128, iters: 1200, n0: 8000, nmax: 20000 }, best: { N: 160, iters: 2400, n0: 11000, nmax: 32000 } }[job.quality || 'normal'];
  // 1) кадры и метки
  const frames = [], eqs = [];
  for (let i = 0; i < job.blobs.length; i++) {
    if (shouldStop()) throw new Error('stopped');
    const d = await decodeBlob(job.blobs[i], PROC_W);
    const ms = detectMarkers(toGray(d.rgba, d.w, d.h), d.w, d.h);
    const K0 = { fx: 0.7 * d.w, fy: 0.7 * d.w, cx: d.w / 2, cy: d.h / 2 };
    const p = poseFromMarkers(ms, L, K0);
    if (p && p.n >= 2) { eqs.push(...focalEqs(p.H, d.w / 2, d.h / 2)); frames.push({ ...d, ms, p, idx: i }); }
    cb.progress('Метки на кадрах', (i + 1) / job.blobs.length, `${frames.length} из ${i + 1} кадров с метками`);
    if (i % 2) await tick();
  }
  if (frames.length < 8) throw new Error(`Коврик найден только на ${frames.length} кадрах — нужно хотя бы 8. Сними ещё раз: все метки по кругу должны быть видны, без бликов.`);
  // 2) фокус камеры (по всем кадрам) и точные позы
  const w = frames[0].w, h = frames[0].h;
  let f0 = focalFromEqs(eqs); if (!(f0 > 0.4 * w && f0 < 1.6 * w)) f0 = 0.75 * w;
  const rf = refineFocal(frames.map((f) => f.p), { fx: f0, fy: f0, cx: w / 2, cy: h / 2 });
  const K = { fx: rf.f, fy: rf.f, cx: w / 2, cy: h / 2 };
  log(`фокус ${rf.f.toFixed(0)} px (угол обзора ${(2 * Math.atan(w / 2 / rf.f) * 180 / Math.PI).toFixed(0)}°), ошибка ${rf.rms.toFixed(2)} px`);
  const good = [];
  for (const f of frames) {
    const p = poseFromMarkers(f.ms, L, K); if (!p || p.rms > 3) continue;
    f.R = p.R; f.t = p.t; f.K = K; f.ang = camAngles(p.R, p.t); good.push(f);
  }
  await tick();
  // 3) маски «где предмет»
  for (let i = 0; i < good.length; i++) {
    if (shouldStop()) throw new Error('stopped');
    const m = computeMask(good[i], { layout: L, mr, Rb, Hb, cutOnly: turn });
    good[i].mask = m.mask;
    cb.progress('Отделяю предмет от коврика', (i + 1) / good.length, `кадр ${i + 1} из ${good.length}`);
    if (i % 2) await tick();
  }
  const els = good.map((f) => f.ang.el), elMax = Math.max(...els);
  log(`кадров с позой: ${good.length}; высота камеры ${Math.min(...els).toFixed(0)}–${elMax.toFixed(0)}°`);
  // 4) оболочка → сетка
  cb.progress('Строю форму', 0, 'вырезаю объём');
  const G = carveHull(good, { Rb, Hb }, Q.N, (p) => cb.progress('Строю форму', p * 0.7, 'вырезаю объём'));
  await tick();
  let vox = 0; for (const v of G.occ) vox += v;
  if (vox < 50) throw new Error('Предмет не найден над ковриком. Он стоит в центре круга? Метки видны со всех сторон?');
  const shape = job.shape || 'normal';
  const GS = shape === 'revolve' ? revolveGrid(G) : G;
  const M = meshFromGrid(GS, shape === 'smooth' ? 5 : 3); taubin(M, shape === 'smooth' ? 60 : 30); computeNormals(M);
  if (shape !== 'normal') log(`форма: ${shape === 'revolve' ? 'тело вращения' : 'гладкая'}`);
  cb.progress('Строю форму', 1, `${(M.idx.length / 3) | 0} треугольников`);
  await tick();
  // 5) цвет вершин
  colorize(M, good, (p) => cb.progress('Раскрашиваю', p, ''));
  await tick();
  const result = { mesh: { pos: M.pos, nrm: M.nrm, col: M.col, idx: M.idx }, stats: { frames: job.blobs.length, used: good.length, focal: rf.f, elMax, hullVol: vox * G.vs ** 3, t: 0 } };
  if (elMax < 50) result.stats.warn = 'Мало кадров сверху — верх модели может быть «колпаком». В следующий раз добавь круг с высоты 60–75°.';
  // 6) сплэты
  if (job.mode === 'splat' || job.mode === 'both') {
    const S = initFromMesh(M, Q.n0);
    const views = splatViews(M, good, depthMap);
    const tr = new Trainer(S, views, { iters: Q.iters, extent: 2 * Rb, maxN: Q.nmax, inside: allowedRegion(G, good, 2) });
    const ts = Date.now();
    for (let i = 1; i <= Q.iters; i++) {
      if (shouldStop()) break; // остановка — оставляем то, что успело выучиться
      tr.step();
      if (i % 10 === 0) {
        const el = (Date.now() - ts) / 1000, left = el / i * (Q.iters - i);
        cb.progress('Учу сплэты', i / Q.iters, `шаг ${i} из ${Q.iters} · капель ${S.n} · осталось ~${fmtT(left)}`);
        await tick();
      }
      if (cb.preview && i % 100 === 0) cb.preview(packSplats(S));
    }
    tr.finalize();
    result.splats = packSplats(S);
    log(`сплэты: ${S.n} капель, ${tr.it} шагов`);
  }
  // поправка масштаба печати (принтер мог чуть растянуть лист): X, Y — по калибровке, высота — по среднему
  const sc = job.scale || [1, 1], sx = +sc[0] || 1, sy = +sc[1] || 1, sz = (sx + sy) / 2;
  if (Math.abs(sx - 1) > 1e-4 || Math.abs(sy - 1) > 1e-4) {
    const P = result.mesh.pos; for (let i = 0; i < P.length; i += 3) { P[i] *= sx; P[i + 1] *= sy; P[i + 2] *= sz; }
    computeNormals(result.mesh);
    if (result.splats) { const S2 = result.splats, ls = Math.log(Math.cbrt(sx * sy * sz)); for (let i = 0; i < S2.length; i += 14) { S2[i] *= sx; S2[i + 1] *= sy; S2[i + 2] *= sz; S2[i + 3] += ls; S2[i + 4] += ls; S2[i + 5] += ls; } }
    result.stats.hullVol *= sx * sy * sz;
    log(`масштаб печати: ×${sx.toFixed(3)} по ширине, ×${sy.toFixed(3)} по длине`);
  }
  result.stats.t = (Date.now() - t0) / 1000;
  return result;
}
export function fmtT(s) { s = Math.max(0, Math.round(s)); return s < 60 ? `${s} с` : `${Math.floor(s / 60)} мин ${s % 60 ? (s % 60) + ' с' : ''}`; }
