// Объём — конвейер обработки: кадры → позы камеры → маски → оболочка → сетка → цвет → (сплэты).
// Один и тот же код работает в фоновом потоке (worker.js) и, если поток недоступен, в основном.
import { matLayout, matRaster } from './mat.js';
import { detectMarkers, toGray } from './detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal, camAngles, fitK1, undistortPts, undistortRGBA } from './pose.js';
import { computeMask, motionMasks, tableConsistency, carveHull, meshFromGrid, revolveGrid, taubin, computeNormals, colorize, depthMap, cleanGrid, vesselCarve, MOTION_OPT } from './recon.js';
import { ensureSam, samReady, encodeFrame, refineMask } from './sam.js';
import { alignHulls, intersectHulls, framesToA } from './align.js';
import { boxMesh, prismMesh, snapPlanes } from './shapes.js';
import { bakeTexture, subdivideLong } from './texture.js';
import { analyzeSurface, computeTangents, applyVertexDisp } from './surface.js';
import { splatCarve, initFromMesh, Trainer, splatViews, allowedRegion, packSplats, scalePacked } from './splat.js';
import { createPool, poolSize } from './splatpool.js';

export const PROC_W = 640;
// рабочая ширина кадра по качеству: «Лучше» — 960 px (мельче деталь силуэта, мельче воксели)
export const procW = (q) => (q === 'best' ? 960 : PROC_W);
export const TEX = { fast: 1024, normal: 2048, best: 4096 };
const tick = () => new Promise((r) => setTimeout(r, 0));

export async function decodeBlob(blob, W, dist) {
  const bmp = await createImageBitmap(blob);
  const w = W || bmp.width, h = Math.round(bmp.height * w / bmp.width), sw = bmp.width, shh = bmp.height;
  const cv = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(w, h) : Object.assign(document.createElement('canvas'), { width: w, height: h });
  const cx = cv.getContext('2d', { willReadFrequently: true });
  cx.imageSmoothingQuality = 'high';
  cx.drawImage(bmp, 0, 0, w, h); bmp.close && bmp.close();
  let rgba = new Uint8Array(cx.getImageData(0, 0, w, h).data.buffer);
  if (dist && dist.k1) rgba = undistortRGBA(rgba, w, h, dist.k1, dist.fr * w);
  return { rgba, w, h, srcW: sw, srcH: shh };
}
// атлас → JPEG (в фоновом потоке — OffscreenCanvas, иначе обычный canvas)
async function encodeJPEG(rgba, T, type = 'image/jpeg') {
  const id = new ImageData(new Uint8ClampedArray(rgba.buffer, rgba.byteOffset, rgba.byteLength), T, T);
  if (typeof OffscreenCanvas !== 'undefined') {
    const cv = new OffscreenCanvas(T, T); cv.getContext('2d').putImageData(id, 0, 0);
    const b = await cv.convertToBlob({ type, quality: 0.9 }); return new Uint8Array(await b.arrayBuffer());
  }
  const cv = Object.assign(document.createElement('canvas'), { width: T, height: T }); cv.getContext('2d').putImageData(id, 0, 0);
  const b = await new Promise((r) => cv.toBlob(r, type, 0.9)); return new Uint8Array(await b.arrayBuffer());
}
// карты нормалей / ORM / высоты — PNG (JPEG испортил бы нормали)
const encodePNG = (rgba, T) => encodeJPEG(rgba, T, 'image/png');

// job: {blobs:[Blob], mode:'mesh'|'splat'|'both', quality:'fast'|'normal'|'best', size:'A4'|'A3'|'A2', theme, Hb,
//       method:'walk'|'turn', shape:'normal'|'revolve'|'smooth', scale:[sx, sy] — поправка масштаба печати}
// cb: {progress(stage, p, text), preview(packed), log(text)}; shouldStop() → true — прервать
export async function runPipeline(job, cb, shouldStop = () => false) {
  const t0 = Date.now(), log = (s) => cb.log && cb.log(`${((Date.now() - t0) / 1000).toFixed(1)} с · ${s}`);
  // на вертушке угловые метки не используются: лист может свисать со столика или быть вырезан по кругу
  const turn = job.method === 'turn';
  const k = matLayout(job.size || 'A4', 'full').k, Rb = 55 * k, Hb = (job.Hb || 90 * k) + 15 * k;
  const Q = { fast: { N: 112, iters: 600, n0: 6000, nmax: 14000 }, normal: { N: 128, iters: 1200, n0: 8000, nmax: 20000, dIters: 600 }, best: { N: 200, iters: 2400, n0: 11000, nmax: 32000, deg: 2, dIters: 1200 } }[job.quality || 'normal'];
  const PW = procW(job.quality);
  // v2.5: продолжение после вылета — с сохранённой формы (контрольная точка перед текстурой), без пересчёта формы
  const R0 = job.resume && job.resume.stage === 'texture' ? job.resume : null;
  let A, good, els, elMax, G, vox, frAll, bottomOk = false, M, shapeInfo = '';
  const bt = job.bottom;
  const shape = job.shape || 'normal';
  function geom() { // сетка из оболочки по выбранной форме (вызывается снова после уточнения сплэтами)
    if (shape === 'box' || shape === 'prism') { const r = shape === 'box' ? boxMesh(G) : prismMesh(G); return { M: r.mesh, info: r.info }; }
    const GS = shape === 'revolve' ? revolveGrid(G) : G; // «сосуд» — обычная сетка с вырезанной полостью
    let M = meshFromGrid(GS, shape === 'smooth' ? 5 : 3); taubin(M, shape === 'smooth' ? 60 : 30); computeNormals(M);
    if (shape === 'planes') { const r = snapPlanes(M); return { M: r.mesh, info: r.info }; }
    return { M, info: '' };
  };
  if (R0) {
    ({ A, good, frAll, G, vox, M, elMax, bottomOk } = await restoreCkpt(R0, job, cb, shouldStop));
    els = good.map((f) => f.ang.el);
    log(`продолжаю с сохранённой формы: ${frAll.length} кадров, ${(M.idx.length / 3) | 0} треугольников — форма не пересчитывается`);
  } else {
  A = await prepSet(job.blobs, { size: job.size, method: job.method, Hb, theme: job.theme, plates: job.plates, PW, objColor: job.objColor, prepped: job.prepped || null, sam: !!job.sam }, cb, shouldStop, log, '');
  good = A.good;
  els = good.map((f) => f.ang.el); elMax = Math.max(...els);
  log(`кадров с позой: ${good.length}; высота камеры ${Math.min(...els).toFixed(0)}–${elMax.toFixed(0)}°`);
  // 4) оболочка → сетка
  cb.progress('Строю форму', 0, 'вырезаю объём');
  G = carveHull(good, { Rb, Hb }, Q.N, (p) => cb.progress('Строю форму', p * 0.7, 'вырезаю объём'), { photo: job.method === 'walk' && job.photo !== false });
  await tick();
  vox = 0; for (const v of G.occ) vox += v;
  if (vox < 50) throw new Error('Предмет не найден над ковриком. Он стоит в центре круга? Метки видны со всех сторон?');
  if (G.motionCut > 1000) log(`верх выше листа достроен по движению предмета между кадрами; лишнего вырезано ${(G.motionCut / 1000).toFixed(1)} см³`);
  if (G.photoCut > 1000) log(`выше листа лишнее вырезано по цвету (фон в разных кадрах разный, предмет — одинаковый): ${(G.photoCut / 1000).toFixed(1)} см³`);
  if (G.capBridge) log(`середина высокого предмета (${(G.capBridge / 10).toFixed(1)} см) видна только на фоне стола/стены — достроена по сечениям выше и ниже; верх по фону найден`);
  if (G.capTrim) log(`срезан пустой «колпак рамки»: ${(G.capTrim / 10).toFixed(1)} см сверху (его не видно на фоне листа). Верх рамки лучше ставить чуть выше предмета — кнопки ▲▼ при съёмке`);
  // 4б) «доснять низ»: вторая съёмка, где предмет лежит на боку / вверх дном — совмещаем и пересекаем оболочки
  frAll = good;
  if (bt && bt.blobs && bt.blobs.length >= 8) {
    try {
      const B = await prepSet(bt.blobs, { size: job.size, method: bt.method || job.method, Hb: bt.Hb || Hb, theme: job.theme, plates: bt.plates, PW, objColor: job.objColor }, cb, shouldStop, log, 'Низ: ');
      log(`низ: кадров с позой ${B.good.length}; высота камеры ${B.elMin.toFixed(0)}–${B.elMax.toFixed(0)}°`);
      const GB = carveHull(B.good, { Rb: B.Rb, Hb: B.Hb }, Q.N, (p) => cb.progress('Низ: строю форму', p, 'вырезаю объём'));
      await tick();
      const al = alignHulls(G, GB, (p) => cb.progress('Совмещаю две съёмки', p, 'ищу, как лежал предмет'));
      await tick();
      const occ0 = G.occ.slice(); intersectHulls(G, GB, al.R, al.t, 1); cleanGrid(G);
      let v2 = 0; for (const v of G.occ) v2 += v;
      const keep = v2 / vox, ang = Math.acos(Math.max(-1, Math.min(1, al.R[8]))) * 180 / Math.PI;
      if (al.score < 0.12 || keep < 0.6) {
        G.occ.set(occ0);
        log(`✗ низ не учтён: съёмки не совместились (совпадение ${(al.score * 100).toFixed(0)}%, осталось бы ${(keep * 100).toFixed(0)}% объёма). Предмет во второй съёмке целиком в рамке? Это тот же предмет?`);
      } else {
        bottomOk = true; frAll = good.concat(framesToA(B.good, al.R, al.t).map((f) => ({ ...f, bot: true, dist: B.dist })));
        log(`низ учтён: предмет во 2-й съёмке был повёрнут на ${ang.toFixed(0)}°; совпадение поверхностей ${(al.score * 100).toFixed(0)}%, ошибка ${al.rms.toFixed(1)} мм; вырезано ${((vox - v2) * G.vs ** 3 / 1000).toFixed(1)} см³ лишнего`);
        vox = v2;
      }
    } catch (e) { if (e.message === 'stopped') throw e; log('✗ низ не учтён: ' + e.message); }
  }
  if (shape === 'vessel') { // v2.3: полость внутри (кружка, ваза) — силуэты её не видят, достраиваем по горлышку и виду сверху
    const r = vesselCarve(G, good);
    if (!r.removed) shapeInfo = 'полость не построена: ' + r.reason;
    else {
      shapeInfo = `горлышко Ø${(2 * r.R).toFixed(0)} мм на высоте ${r.rim.toFixed(0)} мм, глубина ${r.depth.toFixed(0)} мм, стенка ~${r.wall.toFixed(1)} мм (по размеру горлышка), дно ${r.bottom.toFixed(0)} мм` +
        (r.measured ? ' (найдено по виду сверху)' : ' (дна сверху не видно — толщина по умолчанию; сними несколько кадров сверху, чтобы было видно дно)');
      vox = 0; for (const v of G.occ) vox += v > 0.5 ? 1 : 0;
      if (r.cap > 500) log(`срезана «шапка» над горлышком: ${(r.cap / 1000).toFixed(1)} см³ (по ${r.capBy === 'стенка' ? 'цвету стенки' : 'сужению'})`);
    }
  }
  { const g = geom(); M = g.M; if (g.info) shapeInfo = g.info; }
  if (shape !== 'normal') log(`форма: ${SHAPES[shape] || shape}${shapeInfo ? ' — ' + shapeInfo : ''}`);
  cb.progress('Строю форму', 1, `${(M.idx.length / 3) | 0} треугольников`);
  await tick();
  } // конец «не продолжение»
  // 5) цвет вершин (кадры обеих съёмок: вторая даёт цвет дна)
  const prepColor = (M) => { if (job.texture !== false && (shape === 'box' || shape === 'prism' || shape === 'planes')) M = subdivideLong(M, 6); // большие грани — мельче, чтобы лоскут влезал в кадр
    colorize(M, frAll, (p) => cb.progress('Раскрашиваю', p, '')); return M; };
  if (!R0) M = prepColor(M);
  await tick();
  const M0 = M; // сетка без текстуры — для сплэтов
  // «гибрид» (сетка + сплэты): сплэты видят вогнутости, которых не видят силуэты, — оболочку уточняем по ним, а текстуру
  // печём уже на уточнённой сетке (на исходной — не тратим время)
  const hybShape = ['normal', 'smooth', 'vessel', 'planes'].includes(shape);
  const hyb = job.mode === 'both' && job.hybrid !== false && hybShape;
  // v2.4: и в режиме «Полигоны» — короткое обучение сплэтов на кадрах 320 px только ради глубины (вогнутости, «жир» силуэтов)
  const depthPass = job.mode === 'mesh' && job.hybrid !== false && hybShape && (job.depthIters ?? Q.dIters) > 0;
  // обучение сплэтов (общая часть для «Сплэтов», «Обоих» и уточнения формы)
  const trainSplats = async (o) => {
    const S = initFromMesh(M0, o.n0, o.deg || 1);
    const sf = frAll.map((f) => shrinkFrame(f, o.W));
    const views = splatViews(M0, sf, depthMap);
    for (const v of views) v.src = null;
    if (o.free) for (const f of frAll) { f.rgba = null; f.bgMed = null; f.refOut = null; }
    const inside = allowedRegion(G, sf, 2);
    let pool = null;
    if (job.pool !== false) { try { pool = await createPool(job.poolSize || poolSize()); } catch (e) { pool = null; log('потоки для сплэтов не запустились: ' + e.message); } }
    const steps = o.iters;
    const tr = new Trainer(S, views, { iters: steps, extent: 2 * Rb, maxN: o.nmax, inside, batch: 1 });
    if (pool && !o.quiet) log(`сплэты учатся в ${pool.size} потоках`);
    const ts = Date.now();
    try {
      for (let i = 1; i <= steps; i++) {
        if (shouldStop()) break; // остановка — оставляем то, что успело выучиться
        if (pool) { try { await pool.step(tr); } catch (e) { log('✗ поток сплэтов упал: ' + e.message + ' — оставляю то, что успело выучиться'); break; } }
        else tr.step();
        if (i % 10 === 0) {
          const el = (Date.now() - ts) / 1000, left = el / i * (steps - i);
          cb.progress(o.label, i / steps, `шаг ${i} из ${steps} · капель ${S.n} · осталось ~${fmtT(left)}`);
          await tick();
        }
        if (o.preview && cb.preview && i % 100 === 0) cb.preview(packSplats(S));
      }
    } finally { if (pool) await pool.close(); }
    return { S, views, tr };
  };
  // оболочку уточняем по глубине сплэтов: воксели перед их поверхностью в нескольких кадрах — пустота. Возвращает новую сетку или null
  const carveBySplats = async (S, views) => {
    cb.progress('Уточняю форму по сплэтам', 0, 'глубина по кадрам'); await tick();
    const occ0 = G.occ.slice(), hc = splatCarve(G, S, views, { share: 0.5 });
    cleanGrid(G); let v2 = 0; for (const v of G.occ) v2 += v > 0.5 ? 1 : 0;
    if (v2 < 0.6 * vox) { G.occ.set(occ0); log(`✗ уточнение по сплэтам отменено: вырезало бы ${(100 - 100 * v2 / vox).toFixed(0)}% объёма`); return null; }
    if (!hc.removed) return null;
    log(`форма уточнена по сплэтам: вырезано ${(hc.volume / 1000).toFixed(1)} см³ (вогнутости, лишнее от силуэтов)`);
    vox = v2; return geom().M;
  };
  let tex = null, texInfo = null, pbr = null, nClose = 0;
  const texturize = async (M) => {
    tex = null; texInfo = null; pbr = null;
    // 5б) крупные планы (для текстуры): позы по меткам коврика, тот же фокус
    let texFrames = frAll; nClose = 0;
    if (job.close && job.close.length) {
      const L = A.L, K = good[0].K, cl = [];
      for (let i = 0; i < job.close.length; i++) {
        if (shouldStop()) throw new Error('stopped');
        try {
          const d = await decodeBlob(job.close[i], PW, A.dist); if (d.w !== good[0].w || d.h !== good[0].h) continue;
          const ms = detectMarkers(toGray(d.rgba, d.w, d.h), d.w, d.h); let p = poseFromMarkers(ms, L, K), Kc = K;
          // полноразмерный снимок может иметь чуть другую обрезку сенсора (другой угол обзора): уточняем фокус по его меткам
          if (p && p.n >= 3 && d.srcW > 1.5 * (good[0].srcW || d.w)) {
            const rf1 = refineFocal([p], K);
            if (Math.abs(rf1.f / K.fx - 1) < 0.08 && rf1.rms < 0.75 * p.rms) { Kc = { ...K, fx: rf1.f, fy: rf1.f }; p = poseFromMarkers(ms, L, Kc) || p; }
          }
          if (p && p.n >= 3 && p.rms < 2) cl.push({ ...d, R: p.R, t: p.t, K: Kc, rms: p.rms, blob: job.close[i], close: true });
        } catch (e) {}
        cb.progress('Крупные планы', (i + 1) / job.close.length, `${cl.length} из ${i + 1} с позой`);
        if (i % 2) await tick();
      }
      nClose = cl.length; texFrames = frAll.concat(cl);
      log(`крупные планы: поза найдена на ${cl.length} из ${job.close.length}${cl.length < job.close.length ? ' (в кадре должно быть видно хотя бы 3 метки коврика)' : ''}`);
    }
    // 5в) отдельная текстура: лучший кадр на каждый кусок поверхности, в полном разрешении
    if (job.texture !== false && job.mode !== 'splat') {
      try {
        const r = await bakeTexture(M, texFrames, { size: job.texSize || TEX[job.quality || 'normal'], decode: (b) => decodeBlob(b, 0, A.dist), encode: encodeJPEG, onProgress: (p, t) => cb.progress('Текстура', p, t) });
        if (r.tex) { M = r.mesh; tex = r.tex; texInfo = r.info; log(`текстура ${r.T}×${r.T}: ${r.info.charts} лоскутов из ${r.info.frames} кадров${nClose ? ' (с крупными планами)' : ''}, масштаб ${(r.info.scale * 100).toFixed(0)}% от кадра`); }
        // 5г) свет, рельеф, материал, текстура без теней — фотометрия по тем же кадрам
        if (r.tex && job.surface !== false) {
          try {
            const Sf = await analyzeSurface(r.mesh, texFrames, r.faceFrame, r.faceChart, r.atlas, r.T, { G, turn, torch: !!job.torch, refine: job.refine, refineMinShare: job.refineMinShare, onProgress: (p, t) => cb.progress('Рельеф и материал', p, t), tick });
            const [albedo, normal, orm, height] = await Promise.all([encodeJPEG(Sf.albedo, r.T), encodePNG(Sf.normal, Sf.Wr), encodePNG(Sf.orm, Sf.Wr), encodePNG(Sf.height, Sf.Wr)]);
            if (Sf.vdisp) {
              let mx = 0, sm = 0; for (const d of Sf.vdisp) { sm += d; if (Math.abs(d) > Math.abs(mx)) mx = d; }
              applyVertexDisp(M, Sf.vdisp);
              log(`форма уточнена по рисунку поверхности: в среднем ${(sm / Sf.vdisp.length).toFixed(2)} мм внутрь, до ${mx.toFixed(1)} мм (опора у ${Math.round(100 * Sf.info.refineShare)}% проверенных точек)`);
            } else if (Sf.info.refineSkip) log(`уточнение по рисунку пропущено (мало опоры: ${Sf.info.refineSkip})`);
            M.tan = computeTangents(M);
            pbr = { albedo, normal, orm, height, Wr: Sf.Wr, info: Sf.info };
            log(surfaceLog(Sf.info));
          } catch (e) { if (e.message === 'stopped') throw e; log('✗ рельеф и материал не получились: ' + e.message + ' — остаётся фото-текстура'); }
        }
      } catch (e) { if (e.message === 'stopped') throw e; log('✗ текстура не получилась: ' + e.message + ' — остаётся цвет вершин'); }
      await tick();
    }
    return M;
  };
  if (depthPass && !R0 && !shouldStop()) {
    const t1 = Date.now();
    const { S, views } = await trainSplats({ W: 320, iters: job.depthIters ?? Q.dIters, n0: 6000, nmax: 14000, label: 'Глубина по сплэтам', quiet: true });
    if (!shouldStop()) { const MH = await carveBySplats(S, views); if (MH) M = prepColor(MH); }
    log(`уточнение формы по сплэтам: ${((Date.now() - t1) / 1000).toFixed(0)} с`);
  }
  // контрольная точка: форма готова — если на текстуре приложение вылетит, продолжим отсюда (и сетка без текстуры уже сохранена)
  if (!hyb && !R0 && job.mode !== 'splat') {
    if (cb.partial) { const PM = { pos: Float32Array.from(M.pos), nrm: Float32Array.from(M.nrm), col: M.col, idx: M.idx }; scalePlain(PM, job.scale); cb.partial({ mesh: PM, stats: { frames: job.blobs.length, used: frAll.length, focal: A.rf.f, elMax, hullVol: vox * G.vs ** 3, t: (Date.now() - t0) / 1000 }, note: 'текстура не досчиталась — сохранена форма с цветом вершин' }); }
    if (job.ckptHook) job.ckptHook(packCkpt({ stage: 'texture', sig: '', A, good, frAll, G, vox, M, elMax, bottomOk })); // для тестов
    if (job.ckptId) await saveCkpt(job.ckptId, { stage: 'texture', sig: job.ckptSig || '', A, good, frAll, G, vox, M, elMax, bottomOk }).then(() => log('форма сохранена — если приложение закроется, продолжу с текстуры'), (e) => log('контрольная точка не сохранилась: ' + e.message));
  }
  if (!hyb) M = await texturize(M);
  const meshOf = (M) => ({ pos: M.pos, nrm: M.nrm, col: M.col, idx: M.idx, ...(tex ? { uv: M.uv, tex, ...(M.detail ? { detail: M.detail } : {}) } : {}), ...(pbr ? { pbr, tan: M.tan } : {}) });
  const result = { mesh: meshOf(M), stats: { tex: texInfo, close: nClose, frames: job.blobs.length + (bt && bt.blobs ? bt.blobs.length : 0), used: frAll.length, focal: A.rf.f, elMax, hullVol: vox * G.vs ** 3, t: 0, bottom: bottomOk } };
  if (elMax < (turn ? 62 : 50) && !bottomOk && !(turn && A.withPlate > 0.5 * good.length)) result.stats.warn = `Самый высокий кадр — ${elMax.toFixed(0)}°: верх модели может выйти «шапкой». В следующий раз ${turn ? 'сними «Фон» (пустой коврик с того же места) или ' : ''}добавь оборот почти сверху (65–75°), или «Доснять низ» (предмет на боку).`;
  result.stats.plate = A.withPlate || 0;
  // 6) сплэты
  // поправка масштаба печати (принтер мог чуть растянуть лист): X, Y — по калибровке, высота — по среднему.
  // Сетка (результат) масштабируется сразу — у сплэтов своя копия формы (M0) и свой масштаб в конце
  const sc = job.scale || [1, 1], sx = +sc[0] || 1, sy = +sc[1] || 1, sz = (sx + sy) / 2, scaled = Math.abs(sx - 1) > 1e-4 || Math.abs(sy - 1) > 1e-4;
  const scaleMesh = (RM) => {
    if (RM.pos === M0.pos) RM.pos = Float32Array.from(RM.pos); // сплэтам нужна форма в мм коврика (позы кадров)
    if (RM.nrm === M0.nrm) RM.nrm = Float32Array.from(RM.nrm);
    const P = RM.pos; for (let i = 0; i < P.length; i += 3) { P[i] *= sx; P[i + 1] *= sy; P[i + 2] *= sz; }
    computeNormals(RM);
  };
  if (scaled) {
    scaleMesh(result.mesh);
    result.stats.hullVol *= sx * sy * sz;
    log(`масштаб печати: ×${sx.toFixed(3)} по ширине, ×${sy.toFixed(3)} по длине`);
  }
  if (job.mode === 'splat' || job.mode === 'both') {
    if (job.mode === 'both' && cb.partial) cb.partial(result); // сетка готова — пусть сохранится до долгого обучения сплэтов
    // сплэтам хватает 640 px — учатся вдвое быстрее, чем на 960; полноразмерные кадры освобождаем — меньше пик памяти
    const { S, views, tr } = await trainSplats({ W: 640, iters: Q.iters, n0: Q.n0, nmax: Q.nmax, deg: Q.deg, free: true, preview: true, label: 'Учу сплэты' });
    if (hyb && !shouldStop()) {
      // сплэты уточняют оболочку: воксели перед их поверхностью в нескольких кадрах — пустота (вогнутости, «жир» силуэтов)
      const MC = await carveBySplats(S, views);
      // кадры для цвета и текстуры: освобождены перед обучением — раскрываем снова
      for (let k = 0; k < frAll.length; k++) { const f = frAll[k]; if (!f.rgba && f.blob) { try { f.rgba = (await decodeBlob(f.blob, f.w, A.dist)).rgba; } catch (e) {} } if (k % 4 === 3) { cb.progress('Уточняю форму по сплэтам', k / frAll.length, 'кадры для текстуры'); await tick(); } }
      const MH = await texturize(MC ? prepColor(MC) : M);
      result.mesh = meshOf(MH); result.stats.tex = texInfo; result.stats.close = nClose; result.stats.hullVol = vox * G.vs ** 3;
      if (scaled) { scaleMesh(result.mesh); result.stats.hullVol *= sx * sy * sz; }
      for (const f of frAll) f.rgba = null;
    }
    tr.finalize();
    result.splats = packSplats(S);
    log(`сплэты: ${S.n} капель, ${tr.it} шагов`);
  }
  if (result.splats && scaled) scalePacked(result.splats, sx, sy, sz);
  result.stats.t = (Date.now() - t0) / 1000;
  return result;
}

// одна съёмка: кадры → метки → фокус → позы → маски. tag — подпись для второй съёмки («Низ: »)
async function prepSet(blobs, cfg, cb, shouldStop, log, tag) {
  const turn = cfg.method === 'turn', PROC_W = cfg.PW || procW();
  const L = matLayout(cfg.size || 'A4', turn ? 'round' : 'full'), mr = matRaster(L, cfg.theme || 'light', 2);
  // запас по высоте рамки на случай если предмет чуть выше, чем пользователь указал (волосы, палец на подставке)
  const Rb = 55 * L.k, Hb = (cfg.Hb || 90 * L.k) + 15 * L.k;
  // вертушка: если меток круга не хватило, пробуем весь лист (лист крутится целиком) — только при точном совпадении
  const Lf = turn ? matLayout(cfg.size || 'A4', 'full') : null;
  // какая раскладка сошлась на этом кадре — такая и нужна для масок (des в цилиндре)
  const poseOf = (ms, K, maxR) => {
    const p = poseFromMarkers(ms, L, K);
    if (!Lf || (p && p.n >= 2 && p.rms <= maxR) || !ms.some((m) => m.id >= 16)) return p ? { ...p, L_: L } : p;
    const q = poseFromMarkers(ms, Lf, K);
    return q && q.n >= 2 && q.rms < Math.min(maxR, 2.5) ? { ...q, L_: Lf } : (p ? { ...p, L_: L } : p);
  };
  // 1) кадры и метки
  // v2.8: если кадры уже декодированы между съёмкой (prepped) и их размер совпадает с PROC_W, используем их.
  // Если размер не совпадает (напр. качество «Лучше» = 960 px) — перекодируем из blob'а как обычно.
  const prepped = cfg.prepped && cfg.prepped.length === blobs.length ? cfg.prepped : null;
  for (let i = 0; i < blobs.length; i++) {
    if (shouldStop()) throw new Error('stopped');
    let d, ms;
    const prepOk = prepped && prepped[i] && prepped[i].rgba && prepped[i].w >= PROC_W - 4; // допуск ± на округление
    if (prepOk) {
      d = { rgba: new Uint8ClampedArray(prepped[i].rgba), w: prepped[i].w, h: prepped[i].h }; ms = prepped[i].ms;
    } else {
      d = await decodeBlob(blobs[i], PROC_W);
      ms = detectMarkers(toGray(d.rgba, d.w, d.h), d.w, d.h);
    }
    const f00 = 0.75 * Math.max(d.w, d.h), K0 = { fx: f00, fy: f00, cx: d.w / 2, cy: d.h / 2 };
    const p = poseOf(ms, K0, 1e9);
    if (p && p.n >= 2) { eqs.push(...focalEqs(p.H, d.w / 2, d.h / 2)); frames.push({ ...d, ms, p, idx: i, blob: blobs[i] }); }
    cb.progress(tag + 'Метки на кадрах', (i + 1) / blobs.length, `${frames.length} из ${i + 1} кадров с метками`);
    if (i % 2) await tick();
  }
  if (frames.length < 8) throw new Error(`${tag}коврик найден только на ${frames.length} кадрах — нужно хотя бы 8. Сними ещё раз: все метки по кругу должны быть видны, без бликов.`);
  // 2) фокус камеры (по всем кадрам) и точные позы
  const w = frames[0].w, h = frames[0].h;
  const L0 = Math.max(w, h); // вертикальный кадр: фокус считаем от длинной стороны
  let f0 = focalFromEqs(eqs); if (!(f0 > 0.35 * L0 && f0 < 2 * L0)) f0 = 0.75 * L0;
  const rf = refineFocal(frames.map((f) => f.p), { fx: f0, fy: f0, cx: w / 2, cy: h / 2 });
  let K = { fx: rf.f, fy: rf.f, cx: w / 2, cy: h / 2 }, dist = null;
  // дисторсия объектива: k1 по углам меток; исправляем, только если она заметна и позы от этого точнее
  if (cfg.dist !== false && frames.length >= 6) {
    const dk = fitK1(frames.map((f) => f.p), K), rn = Math.hypot(w / 2, h / 2) / K.fx, shift = Math.abs(dk.k1) * rn ** 3 * K.fx;
    if (shift > 0.6 && dk.rms1 < 0.9 * dk.rms0) {
      dist = { k1: dk.k1, fr: K.fx / w };
      for (const f of frames) { f.rgba = undistortRGBA(f.rgba, w, h, dk.k1, K.fx); f.ms = f.ms.map((m) => ({ ...m, corners: undistortPts(m.corners, K, dk.k1) })); }
      const ps = frames.map((f) => poseOf(f.ms, K, 1e9)).filter((p) => p && p.n >= 2), rf2 = refineFocal(ps, K);
      log(`${tag}дисторсия объектива исправлена: на краю кадра было до ${shift.toFixed(1)} px (k1 ${dk.k1.toFixed(3)}), ошибка меток ${dk.rms0.toFixed(2)} → ${dk.rms1.toFixed(2)} px`);
      rf.f = rf2.f; rf.rms = rf2.rms; K = { fx: rf.f, fy: rf.f, cx: w / 2, cy: h / 2 };
    }
  }
  log(`${tag}фокус ${rf.f.toFixed(0)} px (угол обзора ${(2 * Math.atan(w / 2 / rf.f) * 180 / Math.PI).toFixed(0)}°), ошибка ${rf.rms.toFixed(2)} px`);
  const good = [];
  for (const f of frames) {
    const p = poseOf(f.ms, K, 3); if (!p || p.rms > 3) continue;
    f.R = p.R; f.t = p.t; f.K = K; f.rms = p.rms; f.L_ = p.L_; f.ang = camAngles(p.R, p.t); good.push(f);
  }
  // v2.8: прореживаем слишком близкие ракурсы (шаг меньше ~5°) — оставляем тот, у которого меньше rms.
  // На длинной съёмке с рук это часто 300+ кадров с копеечным шагом — только тратит время и множит «ложные фоны» от бликов.
  if (good.length > 80) {
    good.sort((a,b)=>a.rms-b.rms);
    const kept=[]; const taken=new Set();
    for (const g of good) {
      let tooClose=false;
      for (const k of kept) {
        const dA=Math.abs(k.ang.el-g.ang.el), dB=Math.acos(Math.max(-1,Math.min(1, k.R[6]*g.R[6]+k.R[7]*g.R[7]+k.R[8]*g.R[8])))*180/Math.PI;
        if (dA<4 && dB<6) { tooClose=true; break; }
      }
      if (!tooClose) kept.push(g);
    }
    if (kept.length >= 20) { log(`${tag}прорежено ракурсов: ${good.length} → ${kept.length} (убраны ближе 5°, более точный оставлен)`); good.length=0; good.push(...kept); }
  }
  await tick();
  // 2б) кадры фона (вертушка, телефон в держателе): пустой коврик с того же места. Поддерживаем несколько кадров
  // фона с разных ракурсов/высот: каждому предметному кадру подбираем самый близкий по позиции камеры.
  const plates = [];
  if (turn && cfg.plates && cfg.plates.length) {
    for (const b of cfg.plates) {
      try {
        const d = await decodeBlob(b, PROC_W, dist); if (d.w !== w || d.h !== h) { log(`${tag}✗ кадр фона другого размера — пропущен`); continue; }
        const ms = detectMarkers(toGray(d.rgba, d.w, d.h), d.w, d.h);
        const p = poseOf(ms, K, 1e9);
        if (!p || p.n < 2) { log(`${tag}✗ кадр фона — коврик не виден`); continue; }
        // plateEmpty проверяет, что в центре нет предмета, но допускает неточность позы (до 5 px)
        const why = plateEmpty(d, L, mr, K, Rb, Hb, 5);
        if (why) { log(`${tag}~ кадр фона не идеален: ${why} — берём как ориентир фона (с поправкой яркости)`); }
        plates.push({ rgba: d.rgba, t: p.t, pos: [-(p.R[0] * p.t[0] + p.R[3] * p.t[1] + p.R[6] * p.t[2]), -(p.R[1] * p.t[0] + p.R[4] * p.t[1] + p.R[7] * p.t[2]), -(p.R[2] * p.t[0] + p.R[5] * p.t[1] + p.R[8] * p.t[2])] });
      } catch (e) { log(`${tag}✗ кадр фона: ${e.message}`); }
    }
    if (plates.length) log(`${tag}кадров фона: ${plates.length} шт. — пространство над предметом вырезается и по фону за кругом (с поправкой на позицию камеры)`);
  }
  // 3) маски «где предмет»
  let withPlate = 0, nTrust = 0;
  const cleanFor = (f) => {
    if (!plates.length) return null;
    // позиция камеры этого кадра
    const Cf = [-(f.R[0] * f.t[0] + f.R[3] * f.t[1] + f.R[6] * f.t[2]), -(f.R[1] * f.t[0] + f.R[4] * f.t[1] + f.R[7] * f.t[2]), -(f.R[2] * f.t[0] + f.R[5] * f.t[1] + f.R[8] * f.t[2])];
    let best = null, bd = 40 * L.k; // в пределах 40 мм от камеры (допускает небольшие смещения держателя)
    for (const pl of plates) {
      const dt = Math.hypot(pl.pos[0] - Cf[0], pl.pos[1] - Cf[1], pl.pos[2] - Cf[2]);
      if (dt < bd) { bd = dt; best = pl; }
    }
    return best ? [best.rgba] : plates.map((p) => p.rgba); // если ничего не близко — пробуем все (plateModel выберет лучший)
  };
  for (let i = 0; i < good.length; i++) {
    if (shouldStop()) throw new Error('stopped');
    // enclose: кадр, где предмет целиком на листе (силуэт замкнут фоном коврика), — «доверенный»: за листом в нём
    // только фон, и его «фон» срезает шапку, даже если низкие ракурсы там видят лишь «неизвестно»
    const Lfr = good[i].L_ || L, mrfr = (good[i].L_ && good[i].L_ !== L) ? matRaster(good[i].L_, cfg.theme || 'light', 2) : mr;
    const m = computeMask(good[i], { layout: Lfr, mr: mrfr, Rb, Hb, cutOnly: turn, offMat: !turn, clean: cleanFor(good[i]), enclose: true, refOut: turn, plateOpt: { minAgree: 0.4, weak: true }, objColor: cfg.objColor });
    good[i].mask = m.mask; good[i].refOut = m.refOut; good[i].trusted = !!m.stats.enclosed; if (good[i].trusted) nTrust++; if (m.stats.plate) withPlate++;
    cb.progress(tag + 'Отделяю предмет от коврика', (i + 1) / good.length, `кадр ${i + 1} из ${good.length}`);
    if (i % 2) await tick();
  }
  // v2.8: AI-маска (MobileSAM) — уточняет каждую маску по ббоксу проекции цилиндра как промпту.
  // Маска SAM влияет только на «неизвестные» пиксели внутри цилиндра: не перезаписывает «точный фон» (m=0),
  // и добавляет предмет (m=2) там, где SAM уверен. Так не сломаются ни блики, ни коврик.
  if (cfg.sam) {
    log(`${tag}загружаю AI-маску…`);
    const samOk = await ensureSam((t) => cb.log(t), (p, t) => cb.progress(tag + 'AI-маска', p * 0.1, t));
    if (samOk) {
      log(`${tag}AI-маска (MobileSAM) уточняет силуэты…`);
      for (let i = 0; i < good.length; i++) {
        if (shouldStop()) break;
        const f = good[i];
        if (!f.rgba) continue;
        // ббокс проекции цилиндра (как подсказка для SAM)
        const { K, R, t } = f;
        let x0 = f.w, y0 = f.h, x1 = 0, y1 = 0;
        for (let z = 0; z <= 1; z++) for (let a = 0; a < 16; a++) {
          const ang = a / 16 * Math.PI * 2;
          const X = Rb * Math.cos(ang), Y = Rb * Math.sin(ang), Z = z * Hb;
          const cz = R[6]*X + R[7]*Y + R[8]*Z + t[2]; if (cz <= 1) continue;
          const u = K.fx*(R[0]*X + R[1]*Y + R[2]*Z + t[0])/cz + K.cx;
          const v = K.fy*(R[3]*X + R[4]*Y + R[5]*Z + t[1])/cz + K.cy;
          if (u < x0) x0 = u; if (v < y0) y0 = v; if (u > x1) x1 = u; if (v > y1) y1 = v;
        }
        x0 = Math.max(0, Math.min(f.w-1, x0|0)); y0 = Math.max(0, Math.min(f.h-1, y0|0));
        x1 = Math.max(0, Math.min(f.w-1, x1|0)); y1 = Math.max(0, Math.min(f.h-1, y1|0));
        const fg = [];
        // если есть цвет предмета (пипетка) — добавляем опорную точку в центр (пиксель этого цвета)
        if (cfg.objColor) {
          const cr=(cfg.objColor[0]||128), cg=(cfg.objColor[1]||128), cb_=(cfg.objColor[2]||128);
          let best=[(x0+x1)/2,(y0+y1)/2], bd=1e9;
          for (let yy=y0; yy<y1; yy+=4) for (let xx=x0; xx<x1; xx+=4){
            const ii=(yy*f.w+xx)*4;
            const dr=f.rgba[ii]-cr, dg=f.rgba[ii+1]-cg, db=f.rgba[ii+2]-cb_;
            const dd=dr*dr+dg*dg+db*db;
            if (dd<bd){bd=dd;best=[xx,yy];}
          }
          fg.push({x:best[0], y:best[1], label:1});
        }
        try {
          const emb = await encodeFrame(f.rgba, f.w, f.h);
          if (!emb) continue;
          const samMask = await refineMask(emb, [x0,y0,x1,y1], fg);
          if (samMask) {
            // сливаем: SAM говорит «предмет» (m=2) — ставим m=2 в обычную маску, только если там было «неизвестно» (1)
            // SAM не режет «предмет» обратно (не ставит 0), чтобы не сломать фон.
            for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
              const ii = y*f.w + x;
              if (samMask[ii] === 2 && f.mask[ii] === 1) f.mask[ii] = 2;
            }
          }
        } catch (e) { /* кадр не уточнился — не страшно */ }
        cb.progress(tag + 'AI-маска', (i+1) / good.length, `${i+1} из ${good.length}`);
        if (i % 2) await tick();
      }
      log(`${tag}AI-маска применена`);
    } else {
      log(`${tag}AI-маска не загрузилась — обычные маски`);
    }
  }
  if (plates.length) log(`${tag}кадров фона использовано: совпало с ${withPlate} кадрами из ${good.length} — пространство над предметом вырезано и по фону за кругом`);
  if (nTrust) log(`${tag}предмет целиком на листе в ${nTrust} кадрах из ${good.length} — по ним срезано лишнее над предметом`);
  else if (!withPlate) log(`${tag}ни в одном кадре предмет не лежит целиком на листе — «шапку» над ним срезать нечем: оборот повыше (от ~50°), коврик A3 или «Фон»`);
  // с рук: стол за листом — та же точка стола в других кадрах (срезает «колпак» над предметом, снятым почти в профиль)
  if (!turn && cfg.table !== false) {
    const tc = tableConsistency(good, { Rb });
    if (tc.marked > 0.002 * good.length * w * h) log(`${tag}стол за листом узнан по другим кадрам: ${(100 * tc.marked / (good.length * w * h)).toFixed(1)}% пикселей — по ним срезается лишнее над предметом`);
  }
  // вертушка: что двигалось между кадрами с одного места камеры — «улики» предмета для верха выше листа
  if (turn) {
    const mo = motionMasks(good, { tau: 22, minGroup: MOTION_OPT.minGroup, refMoveTol: 0.15 });
    if (mo.used) log(`${tag}движение: ${mo.groups} позиц. камеры, ${mo.used} кадров${mo.moved ? `, ${mo.moved} кадров не учтены — камера сдвинулась или менялся свет` : ''}`);
  }
  const els = good.map((f) => f.ang.el);
  return { withPlate, good, rf, L, Rb, Hb, turn, dist, elMax: Math.max(...els), elMin: Math.min(...els) };
}
// уменьшенная копия кадра (картинка — усреднением, маска — ближайшим), фокус в новых пикселях
export function shrinkFrame(f, W) {
  if (f.w <= W) return f;
  const k = f.w / W, w = W, h = Math.round(f.h / k), rgba = new Uint8Array(w * h * 4), mask = f.mask ? new Uint8Array(w * h) : null;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const x0 = Math.floor(x * k), x1 = Math.max(x0 + 1, Math.floor((x + 1) * k)), y0 = Math.floor(y * k), y1 = Math.max(y0 + 1, Math.floor((y + 1) * k));
    const s = [0, 0, 0, 0]; let n = 0;
    for (let yy = y0; yy < Math.min(f.h, y1); yy++) for (let xx = x0; xx < Math.min(f.w, x1); xx++) { const i = (yy * f.w + xx) * 4; s[0] += f.rgba[i]; s[1] += f.rgba[i + 1]; s[2] += f.rgba[i + 2]; n++; }
    const o = (y * w + x) * 4; rgba[o] = s[0] / n; rgba[o + 1] = s[1] / n; rgba[o + 2] = s[2] / n; rgba[o + 3] = 255;
    if (mask) mask[y * w + x] = f.mask[Math.min(f.h - 1, Math.floor((y + 0.5) * k)) * f.w + Math.min(f.w - 1, Math.floor((x + 0.5) * k))];
  }
  let bgMed = null;
  if (f.bgMed) { bgMed = new Uint8Array(w * h * 3); for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const j = (Math.min(f.h - 1, Math.floor((y + 0.5) * k)) * f.w + Math.min(f.w - 1, Math.floor((x + 0.5) * k))) * 3, o = (y * w + x) * 3; bgMed[o] = f.bgMed[j]; bgMed[o + 1] = f.bgMed[j + 1]; bgMed[o + 2] = f.bgMed[j + 2]; } }
  const K = { fx: f.K.fx / k, fy: f.K.fy / k, cx: f.K.cx / k, cy: f.K.cy / k };
  return { ...f, w, h, rgba, mask, K, bgMed };
}
// Кадр фона годится, только если предмет с коврика убран: центр круга должен выглядеть как сам коврик.
export function plateEmpty(d, L, mr, K0, Rb, Hb, maxRms = 3) {
  const ms = detectMarkers(toGray(d.rgba, d.w, d.h), d.w, d.h), p = poseFromMarkers(ms, L, K0);
  if (!p || p.n < 2 || p.rms > maxRms) return 'на нём не видно коврика (телефон сдвинули?)';
  const m = computeMask({ ...d, K: K0, R: p.R, t: p.t }, { layout: L, mr, Rb, Hb, cutOnly: true, offMat: false }).mask;
  let bg = 0, all = 0;
  for (let r = 4; r <= 0.65 * L.objR; r += 3) for (let a = 0; a < 360; a += 4) {
    const X = r * Math.cos(a * Math.PI / 180), Y = r * Math.sin(a * Math.PI / 180), R = p.R, t = p.t;
    const cz = R[6] * X + R[7] * Y + t[2]; if (cz <= 1) continue;
    const u = (K0.fx * (R[0] * X + R[1] * Y + t[0]) / cz + K0.cx) | 0, v = (K0.fy * (R[3] * X + R[4] * Y + t[1]) / cz + K0.cy) | 0;
    if (u < 0 || v < 0 || u >= d.w || v >= d.h) continue;
    all++; if (m[v * d.w + u] === 0 || m[v * d.w + u] === 3) bg++;
  }
  if (all < 50) return 'центр круга не в кадре';
  if (bg < 0.55 * all) return `в центре круга что-то стоит (коврик виден на ${Math.round(100 * bg / all)}%) — предмет нужно убрать`;
  return '';
}
const SHAPES = { revolve: 'тело вращения', smooth: 'гладкая', box: 'коробка', prism: 'призма (одно сечение по высоте)', planes: 'плоские грани', vessel: 'сосуд' };
export function fmtT(s) { s = Math.max(0, Math.round(s)); return s < 60 ? `${s} с` : `${Math.floor(s / 60)} мин ${s % 60 ? (s % 60) + ' с' : ''}`; }

// строка журнала про свет, рельеф и материалы
function surfaceLog(I) {
  const L = I.light, el = L ? Math.asin(Math.max(-1, Math.min(1, L.dir[2]))) * 180 / Math.PI : 0;
  const kinds = new Map(); for (const m of I.materials || []) { const k = m.metal >= 1 ? 'металл' : m.metal > 0 ? 'похоже на металл' : m.rough < 0.3 ? 'глянец' : m.rough < 0.75 ? 'полуглянец' : 'мат'; kinds.set(k, (kinds.get(k) || 0) + m.share); }
  const mats = [...kinds].filter(([, v]) => v > 0.04).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${k} ${Math.round(v * 100)}%`);
  const rm = I.relief && I.relief.mode, rf = Array.isArray(I.refine) ? I.refine[0] : null;
  return (rf && rf.found ? `поверхность уточнена по ${rf.found} точкам (в среднем на ${rf.meanMM} мм внутрь оболочки); ` : '') + (L ? `свет: лампа ${el.toFixed(0)}° над горизонтом${L.rotates ? ' (стоит в комнате, предмет вертится)' : ''}, рассеянного ${Math.round(L.ambient * 100)}%; ` : '') +
    `рельеф ${rm === 'none' ? 'выключен' : rm === 'photo' ? 'по смене света' : rm === 'torch' ? `по фонарику (фотометрия${I.torch ? `, комнатного света ${Math.round(I.torch.alpha / (1 + I.torch.alpha) * 100)}%` : ''})` : 'по светотени снимков (приблизительный)'}${rm === 'none' ? '' : `, перепад ±${I.heightRange} мм`}; материал (авто): ${mats.join(', ') || 'мат'} — можно поменять кнопками; текстура без бликов и теней`;
}

// ---------- v2.5: контрольная точка перед текстурой (продолжение после вылета) ----------
function scalePlain(M, sc) {
  const sx = +(sc && sc[0]) || 1, sy = +(sc && sc[1]) || 1, sz = (sx + sy) / 2; if (sx === 1 && sy === 1) return;
  const P = M.pos; for (let i = 0; i < P.length; i += 3) { P[i] *= sx; P[i + 1] *= sy; P[i + 2] *= sz; }
}
const frameKeys = ['w', 'h', 'K', 'R', 't', 'rms', 'srcW', 'srcH', 'idx', 'ang', 'bot', 'dist', 'trusted'];
export function packCkpt(c) {
  const fr = c.frAll.map((f) => { const o = {}; for (const k of frameKeys) if (f[k] !== undefined) o[k] = f[k]; o.mask = f.mask || null; return o; });
  const occ = new Uint8Array(c.G.occ.length); for (let i = 0; i < occ.length; i++) occ[i] = c.G.occ[i] > 0.5 ? 1 : 0;
  return { v: 1, stage: c.stage, sig: c.sig, t: Date.now(), nGood: c.good.length, frames: fr,
    A: { dist: c.A.dist || null, f: c.A.rf.f, withPlate: c.A.withPlate || 0, size: c.A.L && c.A.L.size },
    G: { occ, nx: c.G.nx, ny: c.G.ny, nz: c.G.nz, vs: c.G.vs, origin: c.G.origin, Rb: c.G.Rb, Hb: c.G.Hb },
    vox: c.vox, elMax: c.elMax, bottomOk: !!c.bottomOk, M: { pos: c.M.pos, nrm: c.M.nrm, col: c.M.col, idx: c.M.idx } };
}
async function saveCkpt(id, c) {
  if (typeof indexedDB === 'undefined') return;
  const store = await import('./store.js');
  await store.putFrames(id + ':ckpt', packCkpt(c));
}
async function restoreCkpt(R0, job, cb, shouldStop) {
  const turn = job.method === 'turn', L = matLayout(job.size || 'A4', turn ? 'round' : 'full');
  const frAll = [];
  for (let k = 0; k < R0.frames.length; k++) {
    if (shouldStop()) throw new Error('stopped');
    const s = R0.frames[k], blob = s.bot ? job.bottom && job.bottom.blobs && job.bottom.blobs[s.idx] : job.blobs[s.idx];
    if (!blob) throw new Error('кадры не совпадают с сохранённой формой');
    const d = await decodeBlob(blob, s.w, s.bot ? s.dist : R0.A.dist);
    frAll.push({ ...s, rgba: d.rgba, srcW: d.srcW, srcH: d.srcH, blob, mask: s.mask || undefined });
    cb.progress('Продолжаю: кадры', (k + 1) / R0.frames.length, `${k + 1} из ${R0.frames.length}`);
    if (k % 3 === 2) await tick();
  }
  const g = R0.G, occ = new Float32Array(g.occ.length); for (let i = 0; i < occ.length; i++) occ[i] = g.occ[i];
  const G = { ...g, occ };
  const good = frAll.slice(0, R0.nGood);
  const A = { L, dist: R0.A.dist, rf: { f: R0.A.f }, withPlate: R0.A.withPlate, good };
  const M = { pos: R0.M.pos, nrm: R0.M.nrm, col: R0.M.col, idx: R0.M.idx };
  return { A, good, frAll, G, vox: R0.vox, M, elMax: R0.elMax, bottomOk: R0.bottomOk };
}
