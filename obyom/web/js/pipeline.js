// Объём — конвейер обработки: кадры → позы камеры → маски → оболочка → сетка → цвет → (сплэты).
// Один и тот же код работает в фоновом потоке (worker.js) и, если поток недоступен, в основном.
import { matLayout, matRaster } from './mat.js';
import { detectMarkers, toGray } from './detect.js';
import { poseFromMarkers, focalEqs, focalFromEqs, refineFocal, camAngles } from './pose.js';
import { computeMask, motionMasks, carveHull, meshFromGrid, revolveGrid, taubin, computeNormals, colorize, depthMap, cleanGrid } from './recon.js';
import { alignHulls, intersectHulls, framesToA } from './align.js';
import { boxMesh, prismMesh, snapPlanes } from './shapes.js';
import { bakeTexture, subdivideLong } from './texture.js';
import { analyzeSurface, computeTangents } from './surface.js';
import { initFromMesh, Trainer, splatViews, allowedRegion, packSplats, scalePacked } from './splat.js';
import { createPool, poolSize } from './splatpool.js';

export const PROC_W = 640;
// рабочая ширина кадра по качеству: «Лучше» — 960 px (мельче деталь силуэта, мельче воксели)
export const procW = (q) => (q === 'best' ? 960 : PROC_W);
const TEX = { fast: 1024, normal: 2048, best: 4096 };
const tick = () => new Promise((r) => setTimeout(r, 0));

export async function decodeBlob(blob, W) {
  const bmp = await createImageBitmap(blob);
  const w = W || bmp.width, h = Math.round(bmp.height * w / bmp.width), sw = bmp.width, shh = bmp.height;
  const cv = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(w, h) : Object.assign(document.createElement('canvas'), { width: w, height: h });
  const cx = cv.getContext('2d', { willReadFrequently: true });
  cx.imageSmoothingQuality = 'high';
  cx.drawImage(bmp, 0, 0, w, h); bmp.close && bmp.close();
  return { rgba: new Uint8Array(cx.getImageData(0, 0, w, h).data.buffer), w, h, srcW: sw, srcH: shh };
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
  const k = matLayout(job.size || 'A4', 'full').k, Rb = 55 * k, Hb = job.Hb || 90 * k;
  const Q = { fast: { N: 112, iters: 600, n0: 6000, nmax: 14000 }, normal: { N: 128, iters: 1200, n0: 8000, nmax: 20000 }, best: { N: 200, iters: 2400, n0: 11000, nmax: 32000, deg: 2 } }[job.quality || 'normal'];
  const PW = procW(job.quality);
  const A = await prepSet(job.blobs, { size: job.size, method: job.method, Hb, theme: job.theme, plates: job.plates, PW }, cb, shouldStop, log, '');
  const good = A.good;
  const els = good.map((f) => f.ang.el), elMax = Math.max(...els);
  log(`кадров с позой: ${good.length}; высота камеры ${Math.min(...els).toFixed(0)}–${elMax.toFixed(0)}°`);
  // 4) оболочка → сетка
  cb.progress('Строю форму', 0, 'вырезаю объём');
  const G = carveHull(good, { Rb, Hb }, Q.N, (p) => cb.progress('Строю форму', p * 0.7, 'вырезаю объём'));
  await tick();
  let vox = 0; for (const v of G.occ) vox += v;
  if (vox < 50) throw new Error('Предмет не найден над ковриком. Он стоит в центре круга? Метки видны со всех сторон?');
  if (G.motionCut > 1000) log(`верх выше листа достроен по движению предмета между кадрами; лишнего вырезано ${(G.motionCut / 1000).toFixed(1)} см³`);
  if (G.capTrim) log(`срезан пустой «колпак рамки»: ${(G.capTrim / 10).toFixed(1)} см сверху (его не видно на фоне листа). Верх рамки лучше ставить чуть выше предмета — кнопки ▲▼ при съёмке`);
  // 4б) «доснять низ»: вторая съёмка, где предмет лежит на боку / вверх дном — совмещаем и пересекаем оболочки
  let frAll = good, bottomOk = false;
  const bt = job.bottom;
  if (bt && bt.blobs && bt.blobs.length >= 8) {
    try {
      const B = await prepSet(bt.blobs, { size: job.size, method: bt.method || job.method, Hb: bt.Hb || Hb, theme: job.theme, plates: bt.plates, PW }, cb, shouldStop, log, 'Низ: ');
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
        bottomOk = true; frAll = good.concat(framesToA(B.good, al.R, al.t));
        log(`низ учтён: предмет во 2-й съёмке был повёрнут на ${ang.toFixed(0)}°; совпадение поверхностей ${(al.score * 100).toFixed(0)}%, ошибка ${al.rms.toFixed(1)} мм; вырезано ${((vox - v2) * G.vs ** 3 / 1000).toFixed(1)} см³ лишнего`);
        vox = v2;
      }
    } catch (e) { if (e.message === 'stopped') throw e; log('✗ низ не учтён: ' + e.message); }
  }
  const shape = job.shape || 'normal';
  let M, shapeInfo = '';
  if (shape === 'box' || shape === 'prism') {
    const r = shape === 'box' ? boxMesh(G) : prismMesh(G);
    M = r.mesh; shapeInfo = r.info;
  } else {
    const GS = shape === 'revolve' ? revolveGrid(G) : G;
    M = meshFromGrid(GS, shape === 'smooth' ? 5 : 3); taubin(M, shape === 'smooth' ? 60 : 30); computeNormals(M);
    if (shape === 'planes') { const r = snapPlanes(M); M = r.mesh; shapeInfo = r.info; }
  }
  if (shape !== 'normal') log(`форма: ${SHAPES[shape] || shape}${shapeInfo ? ' — ' + shapeInfo : ''}`);
  cb.progress('Строю форму', 1, `${(M.idx.length / 3) | 0} треугольников`);
  await tick();
  // 5) цвет вершин (кадры обеих съёмок: вторая даёт цвет дна)
  if (job.texture !== false && (shape === 'box' || shape === 'prism' || shape === 'planes')) M = subdivideLong(M, 6); // большие грани — мельче, чтобы лоскут влезал в кадр
  colorize(M, frAll, (p) => cb.progress('Раскрашиваю', p, ''));
  await tick();
  const M0 = M; // сетка без текстуры — для сплэтов
  // 5б) крупные планы (для текстуры): позы по меткам коврика, тот же фокус
  let texFrames = frAll, nClose = 0;
  if (job.close && job.close.length) {
    const L = A.L, K = good[0].K, cl = [];
    for (let i = 0; i < job.close.length; i++) {
      if (shouldStop()) throw new Error('stopped');
      try {
        const d = await decodeBlob(job.close[i], PW); if (d.w !== good[0].w || d.h !== good[0].h) continue;
        const ms = detectMarkers(toGray(d.rgba, d.w, d.h), d.w, d.h), p = poseFromMarkers(ms, L, K);
        if (p && p.n >= 3 && p.rms < 2) cl.push({ ...d, R: p.R, t: p.t, K, rms: p.rms, blob: job.close[i], close: true });
      } catch (e) {}
      cb.progress('Крупные планы', (i + 1) / job.close.length, `${cl.length} из ${i + 1} с позой`);
      if (i % 2) await tick();
    }
    nClose = cl.length; texFrames = frAll.concat(cl);
    log(`крупные планы: поза найдена на ${cl.length} из ${job.close.length}${cl.length < job.close.length ? ' (в кадре должно быть видно хотя бы 3 метки коврика)' : ''}`);
  }
  // 5в) отдельная текстура: лучший кадр на каждый кусок поверхности, в полном разрешении
  let tex = null, texInfo = null, pbr = null;
  if (job.texture !== false && job.mode !== 'splat') {
    try {
      const r = await bakeTexture(M, texFrames, { size: TEX[job.quality || 'normal'], decode: (b) => decodeBlob(b, 0), encode: encodeJPEG, onProgress: (p, t) => cb.progress('Текстура', p, t) });
      if (r.tex) { M = r.mesh; tex = r.tex; texInfo = r.info; log(`текстура ${r.T}×${r.T}: ${r.info.charts} лоскутов из ${r.info.frames} кадров${nClose ? ' (с крупными планами)' : ''}, масштаб ${(r.info.scale * 100).toFixed(0)}% от кадра`); }
      // 5г) свет, рельеф, материал, текстура без теней — фотометрия по тем же кадрам
      if (r.tex && job.surface !== false) {
        try {
          const Sf = await analyzeSurface(r.mesh, texFrames, r.faceFrame, r.faceChart, r.atlas, r.T, { G, turn, torch: !!job.torch, onProgress: (p, t) => cb.progress('Рельеф и материал', p, t), tick });
          const [albedo, normal, orm, height] = await Promise.all([encodeJPEG(Sf.albedo, r.T), encodePNG(Sf.normal, Sf.Wr), encodePNG(Sf.orm, Sf.Wr), encodePNG(Sf.height, Sf.Wr)]);
          M.tan = computeTangents(M);
          pbr = { albedo, normal, orm, height, Wr: Sf.Wr, info: Sf.info };
          log(surfaceLog(Sf.info));
        } catch (e) { if (e.message === 'stopped') throw e; log('✗ рельеф и материал не получились: ' + e.message + ' — остаётся фото-текстура'); }
      }
    } catch (e) { if (e.message === 'stopped') throw e; log('✗ текстура не получилась: ' + e.message + ' — остаётся цвет вершин'); }
    await tick();
  }
  const result = { mesh: { pos: M.pos, nrm: M.nrm, col: M.col, idx: M.idx, ...(tex ? { uv: M.uv, tex } : {}), ...(pbr ? { pbr, tan: M.tan } : {}) }, stats: { tex: texInfo, close: nClose, frames: job.blobs.length + (bt && bt.blobs ? bt.blobs.length : 0), used: frAll.length, focal: A.rf.f, elMax, hullVol: vox * G.vs ** 3, t: 0, bottom: bottomOk } };
  if (elMax < (turn ? 62 : 50) && !bottomOk && !(turn && A.withPlate > 0.5 * good.length)) result.stats.warn = `Самый высокий кадр — ${elMax.toFixed(0)}°: верх модели может выйти «шапкой». В следующий раз ${turn ? 'сними «Фон» (пустой коврик с того же места) или ' : ''}добавь оборот почти сверху (65–75°), или «Доснять низ» (предмет на боку).`;
  result.stats.plate = A.withPlate || 0;
  // 6) сплэты
  // поправка масштаба печати (принтер мог чуть растянуть лист): X, Y — по калибровке, высота — по среднему.
  // Сетка (результат) масштабируется сразу — у сплэтов своя копия формы (M0) и свой масштаб в конце
  const sc = job.scale || [1, 1], sx = +sc[0] || 1, sy = +sc[1] || 1, sz = (sx + sy) / 2, scaled = Math.abs(sx - 1) > 1e-4 || Math.abs(sy - 1) > 1e-4;
  if (scaled) {
    const RM = result.mesh;
    if (RM.pos === M0.pos) RM.pos = Float32Array.from(RM.pos); // сплэтам нужна форма в мм коврика (позы кадров)
    if (RM.nrm === M0.nrm) RM.nrm = Float32Array.from(RM.nrm);
    const P = RM.pos; for (let i = 0; i < P.length; i += 3) { P[i] *= sx; P[i + 1] *= sy; P[i + 2] *= sz; }
    computeNormals(RM);
    result.stats.hullVol *= sx * sy * sz;
    log(`масштаб печати: ×${sx.toFixed(3)} по ширине, ×${sy.toFixed(3)} по длине`);
  }
  if (job.mode === 'splat' || job.mode === 'both') {
    if (job.mode === 'both' && cb.partial) cb.partial(result); // сетка готова — пусть сохранится до долгого обучения сплэтов
    const S = initFromMesh(M0, Q.n0, Q.deg || 1); // цвет зависит от угла взгляда: гармоники 1-й степени, у «Лучше» — 2-й
    const sf = frAll.map((f) => shrinkFrame(f, 640)); // сплэтам хватает 640 px — учатся вдвое быстрее, чем на 960
    const views = splatViews(M0, sf, depthMap);
    // виды скопировали всё нужное — полноразмерные кадры больше не нужны: меньше пик памяти («Лучше» на телефоне)
    for (const v of views) v.src = null;
    for (const f of frAll) { f.rgba = null; f.bgMed = null; f.refOut = null; }
    // несколько потоков (v2.1): кадр шага считают все потоки по частям — тот же результат, быстрее
    const inside = allowedRegion(G, sf, 2);
    let pool = null;
    if (job.pool !== false) { try { pool = await createPool(job.poolSize || poolSize()); } catch (e) { pool = null; log('потоки для сплэтов не запустились: ' + e.message); } }
    const steps = Q.iters;
    const tr = new Trainer(S, views, { iters: steps, extent: 2 * Rb, maxN: Q.nmax, inside, batch: 1 });
    if (pool) log(`сплэты учатся в ${pool.size} потоках`);
    const ts = Date.now();
    try {
      for (let i = 1; i <= steps; i++) {
        if (shouldStop()) break; // остановка — оставляем то, что успело выучиться
        if (pool) { try { await pool.step(tr); } catch (e) { log('✗ поток сплэтов упал: ' + e.message + ' — оставляю то, что успело выучиться'); break; } }
        else tr.step();
        if (i % 10 === 0) {
          const el = (Date.now() - ts) / 1000, left = el / i * (steps - i);
          cb.progress('Учу сплэты', i / steps, `шаг ${i} из ${steps} · капель ${S.n} · осталось ~${fmtT(left)}`);
          await tick();
        }
        if (cb.preview && i % 100 === 0) cb.preview(packSplats(S));
      }
    } finally { if (pool) await pool.close(); }
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
  const Rb = 55 * L.k, Hb = cfg.Hb || 90 * L.k;
  // вертушка: если меток круга не хватило, пробуем весь лист (лист крутится целиком) — только при точном совпадении
  const Lf = turn ? matLayout(cfg.size || 'A4', 'full') : null;
  const poseOf = (ms, K, maxR) => {
    const p = poseFromMarkers(ms, L, K);
    if (!Lf || (p && p.n >= 2 && p.rms <= maxR) || !ms.some((m) => m.id >= 16)) return p;
    const q = poseFromMarkers(ms, Lf, K);
    return q && q.n >= 2 && q.rms < Math.min(maxR, 2.5) ? q : p;
  };
  // 1) кадры и метки
  const frames = [], eqs = [];
  for (let i = 0; i < blobs.length; i++) {
    if (shouldStop()) throw new Error('stopped');
    const d = await decodeBlob(blobs[i], PROC_W);
    const ms = detectMarkers(toGray(d.rgba, d.w, d.h), d.w, d.h);
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
  const K = { fx: rf.f, fy: rf.f, cx: w / 2, cy: h / 2 };
  log(`${tag}фокус ${rf.f.toFixed(0)} px (угол обзора ${(2 * Math.atan(w / 2 / rf.f) * 180 / Math.PI).toFixed(0)}°), ошибка ${rf.rms.toFixed(2)} px`);
  const good = [];
  for (const f of frames) {
    const p = poseOf(f.ms, K, 3); if (!p || p.rms > 3) continue;
    f.R = p.R; f.t = p.t; f.K = K; f.rms = p.rms; f.ang = camAngles(p.R, p.t); good.push(f);
  }
  await tick();
  // 2б) кадры фона (вертушка, телефон в держателе): пустой коврик с того же места
  const clean = [];
  if (turn && cfg.plates && cfg.plates.length) {
    for (const b of cfg.plates) {
      try {
        const d = await decodeBlob(b, PROC_W); if (d.w !== w || d.h !== h) { log(`${tag}✗ кадр фона другого размера — пропущен`); continue; }
        const why = plateEmpty(d, L, mr, K, Rb, Hb);
        if (why) { log(`${tag}✗ кадр фона не подошёл: ${why}`); continue; }
        clean.push(d.rgba);
      } catch (e) { log(`${tag}✗ кадр фона: ${e.message}`); }
    }
  }
  // 3) маски «где предмет»
  let withPlate = 0, nTrust = 0;
  for (let i = 0; i < good.length; i++) {
    if (shouldStop()) throw new Error('stopped');
    // enclose: кадр, где предмет целиком на листе (силуэт замкнут фоном коврика), — «доверенный»: за листом в нём
    // только фон, и его «фон» срезает шапку, даже если низкие ракурсы там видят лишь «неизвестно»
    const m = computeMask(good[i], { layout: L, mr, Rb, Hb, cutOnly: turn, offMat: !turn, clean: clean.length ? clean : null, enclose: true, refOut: turn });
    good[i].mask = m.mask; good[i].refOut = m.refOut; good[i].trusted = !!m.stats.enclosed; if (good[i].trusted) nTrust++; if (m.stats.plate) withPlate++;
    cb.progress(tag + 'Отделяю предмет от коврика', (i + 1) / good.length, `кадр ${i + 1} из ${good.length}`);
    if (i % 2) await tick();
  }
  if (clean.length) log(`${tag}кадр фона: ${clean.length} шт., совпал с ${withPlate} кадрами из ${good.length} — пространство над предметом вырезано и по фону за кругом`);
  if (nTrust) log(`${tag}предмет целиком на листе в ${nTrust} кадрах из ${good.length} — по ним срезано лишнее над предметом`);
  else if (!withPlate) log(`${tag}ни в одном кадре предмет не лежит целиком на листе — «шапку» над ним срезать нечем: оборот повыше (от ~50°), коврик A3 или «Фон»`);
  // вертушка: что двигалось между кадрами с одного места камеры — «улики» предмета для верха выше листа
  if (turn) {
    const mo = motionMasks(good);
    if (mo.used) log(`${tag}движение: ${mo.groups} позиц. камеры, ${mo.used} кадров${mo.moved ? `, ${mo.moved} кадров не учтены — камера сдвинулась или менялся свет` : ''}`);
  }
  const els = good.map((f) => f.ang.el);
  return { withPlate, good, rf, L, Rb, Hb, turn, elMax: Math.max(...els), elMin: Math.min(...els) };
}
// уменьшенная копия кадра (картинка — усреднением, маска — ближайшим), фокус в новых пикселях
function shrinkFrame(f, W) {
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
export function plateEmpty(d, L, mr, K0, Rb, Hb) {
  const ms = detectMarkers(toGray(d.rgba, d.w, d.h), d.w, d.h), p = poseFromMarkers(ms, L, K0);
  if (!p || p.n < 2 || p.rms > 3) return 'на нём не видно коврика (телефон сдвинули?)';
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
  if (bg < 0.8 * all) return `в центре круга что-то стоит (коврик виден на ${Math.round(100 * bg / all)}%) — предмет нужно убрать`;
  return '';
}
const SHAPES = { revolve: 'тело вращения', smooth: 'гладкая', box: 'коробка', prism: 'призма (одно сечение по высоте)', planes: 'плоские грани' };
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
