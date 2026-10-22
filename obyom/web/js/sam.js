// MobileSAM (Apache-2.0) — опциональное уточнение маски нейросетью.
// Загружается лениво при включении пользователем; ONNX Runtime Web (WASM backend, работает в WebView
// без COOP/COEP). Веса модели скачиваются с CDN при первом включении и кешируются в Cache Storage.
//
// Интерфейс:
//   samReady()   — true если модели загружены и готовы
//   samBusy()    — true если сейчас грузит/считает
//   ensureSam(logFn, progressFn) — загрузить ORT и веса
//   encodeFrame(rgba, w, h)  — закодировать кадр (эмбеддинг кешируется по хешу кадра)
//   refineMask(emb, w, h, bbox, points, negPoints) → Uint8Array маски {0=фон, 1=предмет} w*h, или null
//
// Принятые формы тензоров MobileSAM (single-mask decoder, экспорт ChaoningZhang / Acly):
//   encoder input:  "images"  Float32 1x3x1024x1024 (NCHW, RGB, нормализованный по IMAGENET)
//   encoder output: "image_embeddings" Float32 1x256x64x64
//   decoder inputs: image_embeddings [1,256,64,64], point_coords [1,N,2], point_labels [1,N],
//                   mask_input [1,1,256,256], has_mask_input [1], orig_im_size [2] (H,W)
//   decoder outputs: masks [1,1,H,W] (logits, upsampled до orig), iou_predictions [1,1]
//
// Промпт-точки подаются в координатах 1024×1024 (после ресайза/паддинга). Метки: 1=foreground, 0=background, -1=pad.
// Ббокс из цилиндра подаём как 2 точки: [x0,y0]=top-left (label=2), [x1,y1]=bottom-right (label=3) — как принято в SAM.

let ort = null, enc = null, dec = null;
let loading = false, busy = false, loadingP = null;
const MODEL_URLS = {
  enc: 'https://cdn.jsdelivr.net/gh/akbartus/MobileSAM-in-the-Browser@master/models/sam_encoder_quant.onnx',
  dec: 'https://cdn.jsdelivr.net/gh/akbartus/MobileSAM-in-the-Browser@master/models/sam_mask_decoder_quant.onnx',
};
const CACHE_NAME = 'obyom-sam-v1';

export function samReady() { return !!(enc && dec); }
export function samBusy() { return busy || loading; }

async function fetchAndCache(url) {
  try {
    const cache = await caches.open(CACHE_NAME);
    let resp = await cache.match(url);
    if (resp) return await resp.arrayBuffer();
    resp = await fetch(url);
    if (!resp.ok) throw new Error('http ' + resp.status);
    await cache.put(url, resp.clone());
    return await resp.arrayBuffer();
  } catch (e) {
    throw new Error('SAM: не удалось скачать ' + url + ' — ' + e.message);
  }
}

export async function ensureSam(log = () => {}, progress = () => {}) {
  if (samReady()) return true;
  if (loadingP) return loadingP;
  loading = true;
  loadingP = (async () => {
    try {
      progress(0.05, 'Загружаю ONNX Runtime…');
      ort = await import('https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/ort.wasm.min.js');
      ort.env.wasm.numThreads = 2;
      ort.env.wasm.simd = true;
      ort.env.wasm.wasmPaths = 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/';
      progress(0.2, 'Скачиваю MobileSAM encoder (~30 MB)…');
      const encBuf = await fetchAndCache(MODEL_URLS.enc);
      progress(0.6, 'Скачиваю decoder (~5 MB)…');
      const decBuf = await fetchAndCache(MODEL_URLS.dec);
      progress(0.8, 'Компилирую модели…');
      const sessOpt = { executionProviders: ['wasm'], graphOptimizationLevel: 'all' };
      // Пробуем создать сессии; у квантованной single-mask версии имена могут отличаться — пробуем варианты
      enc = await ort.InferenceSession.create(encBuf, { ...sessOpt, executionProviders: ['wasm'] });
      dec = await ort.InferenceSession.create(decBuf, { ...sessOpt, executionProviders: ['wasm'] });
      progress(1, 'Готово');
      log('AI-маска (MobileSAM) загружена');
      return true;
    } catch (e) {
      log('AI-маска: ' + (e.message || e));
      enc = null; dec = null;
      return false;
    } finally {
      loading = false;
    }
  })();
  return loadingP;
}

// Подготовка тензора 1×3×1024×1024 из RGBA-кадра (NCHW, ImageNet-нормализация).
// Возвращает {input: ort.Tensor, coordShift: [sx, sy, padX, padY]}, как перевести (x,y) из кадра в 1024-координаты.
function preprocessRgba(rgba, w, h) {
  const LONG = 1024;
  const scale = Math.min(LONG / w, LONG / h);
  const nw = Math.round(w * scale), nh = Math.round(h * scale);
  const padX = Math.round((LONG - nw) / 2), padY = Math.round((LONG - nh) / 2);
  // ресайзим через canvas до 1024×1024 с паддингом
  const cv = document.createElement('canvas'); cv.width = LONG; cv.height = LONG;
  const cx = cv.getContext('2d');
  const img = cx.createImageData(w, h); img.data.set(rgba);
  // нельзя putImageData с масштабом — рисуем через временный canvas
  const cv2 = document.createElement('canvas'); cv2.width = w; cv2.height = h;
  cv2.getContext('2d').putImageData(img, 0, 0);
  cx.fillStyle = '#000'; cx.fillRect(0, 0, LONG, LONG);
  cx.drawImage(cv2, padX, padY, nw, nh);
  const resized = cx.getImageData(0, 0, LONG, LONG).data;
  // CHW + ImageNet-нормализация
  const t = new Float32Array(3 * LONG * LONG);
  const muR = 0.485, muG = 0.456, muB = 0.406, sR = 0.229, sG = 0.224, sB = 0.225;
  for (let y = 0; y < LONG; y++) {
    for (let x = 0; x < LONG; x++) {
      const i = (y * LONG + x) * 4;
      const r = resized[i] / 255, g = resized[i+1] / 255, b = resized[i+2] / 255;
      t[y * LONG + x] = (r - muR) / sR;
      t[LONG * LONG + y * LONG + x] = (g - muG) / sG;
      t[2 * LONG * LONG + y * LONG + x] = (b - muB) / sB;
    }
  }
  return {
    tensor: new ort.Tensor('float32', t, [1, 3, LONG, LONG]),
    scale, nw, nh, padX, padY,
    toLong: (x, y) => [x * scale + padX, y * scale + padY],
  };
}

export async function encodeFrame(rgba, w, h) {
  if (!samReady()) return null;
  busy = true;
  try {
    const p = preprocessRgba(rgba, w, h);
    const out = await enc.run({ images: p.tensor });
    const emb = out.image_embeddings || out[Object.keys(out)[0]];
    return { emb, prep: p, w, h };
  } finally { busy = false; }
}

// points: [{x,y,label=1 (fg)|0 (bg)}]; bbox: [x0,y0,x1,y1] в координатах кадра
export async function refineMask(embObj, bbox, points = [], negPoints = []) {
  if (!samReady() || !embObj) return null;
  busy = true;
  try {
    const { emb, prep, w, h } = embObj;
    const toL = prep.toLong;
    // собираем промпт-точки: ббокс — 2 точки (label=2 top-left, label=3 bottom-right); пользовательские точки; pad -1
    const pts = []; const labels = [];
    if (bbox) {
      const [x0, y0] = toL(bbox[0], bbox[1]);
      const [x1, y1] = toL(bbox[2], bbox[3]);
      pts.push(x0, y0, x1, y1); labels.push(2, 3);
    }
    for (const p of points)   { const [lx, ly] = toL(p.x, p.y); pts.push(lx, ly); labels.push(1); }
    for (const p of negPoints){ const [lx, ly] = toL(p.x, p.y); pts.push(lx, ly); labels.push(0); }
    const nPts = pts.length / 2;
    // SAM всегда хочет минимум 1 точку + 1 pad; если пусто — добавляем одну псевдо-fg в центр ббокса
    let coordArr, labArr, nP;
    if (nPts === 0) {
      const cx = 512, cy = 512;
      coordArr = new Float32Array([cx, cy, 0, 0]); labArr = new Float32Array([1, -1]); nP = 2;
    } else {
      coordArr = new Float32Array(nPts * 2 + 2); labArr = new Float32Array(nPts + 1);
      coordArr.set(pts, 0); coordArr[nPts*2]=0; coordArr[nPts*2+1]=0;
      for (let i = 0; i < nPts; i++) labArr[i] = labels[i];
      labArr[nPts] = -1; nP = nPts + 1;
    }
    const point_coords = new ort.Tensor('float32', coordArr, [1, nP, 2]);
    const point_labels = new ort.Tensor('float32', labArr, [1, nP]);
    const mask_input = new ort.Tensor('float32', new Float32Array(256 * 256), [1, 1, 256, 256]);
    const has_mask = new ort.Tensor('float32', new Float32Array([0]), [1]);
    const orig_size = new ort.Tensor('float32', new Float32Array([h, w]), [2]);
    const feeds = { image_embeddings: emb, point_coords, point_labels, mask_input, has_mask_input: has_mask, orig_im_size };
    const r = await dec.run(feeds);
    const maskT = r.masks || r[Object.keys(r)[0]];
    // maskT: [1,1,h,w] logits (upsampled)
    const mh = maskT.dims[2], mw = maskT.dims[3];
    const mask = new Uint8Array(w * h);
    const md = maskT.data;
    if (mh === h && mw === w) {
      for (let i = 0; i < w * h; i++) mask[i] = md[i] > 0 ? 2 : 1; // 2=предмет, 1=неизвестно (как в computeMask)
    } else {
      // на случай, если декодер вернул другой размер (256×256), билинейно масштабируем
      for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
        const u = (x / w) * (mw - 1), v = (y / h) * (mh - 1);
        const i0 = u | 0, j0 = v | 0, a = u - i0, b = v - j0;
        const q = j0 * mw + i0;
        const v00 = md[q], v10 = md[Math.min(q+1, md.length-1)], v01 = md[Math.min(q+mw, md.length-1)], v11 = md[Math.min(q+mw+1, md.length-1)];
        const val = (1-a)*(1-b)*v00 + a*(1-b)*v10 + (1-a)*b*v01 + a*b*v11;
        mask[y*w+x] = val > 0 ? 2 : 1;
      }
    }
    return mask;
  } catch (e) {
    return null;
  } finally {
    busy = false;
  }
}
