// v2.8: C++/WASM ускорение для carveHull.
// Загружает wasm модуль лениво при первом carveHull. Если не загрузился — JS-фоллбэк в recon.js.
//
// ABI (obyom/src/carve.c):
//   carve_occ(occ, nx, ny, nz, vs, ox, oy, oz, Rb, framesPtr, nFrames, maskBase, alphaBase,
//             frac, few, weakMaj, tfrac, wMean)
// framesPtr: массив FFrameDesc[nFrames] (FPF = 22 float'а); смещения maskOff/alphaOff от maskBase/alphaBase.
let mod = null, loadP = null;
export function wasmReady() { return !!mod; }

function modReady() {
  // emscriptен ES6-модуль с MODULARIZE=1 и EXPORT_NAME=createModule экспортирует функцию по умолчанию,
  // которая возвращает Promise<Module>; иногда уже является готовым Module, если импорт резолвился раньше.
  return mod && typeof mod._carve_occ === 'function';
}

export async function ensureCarveWasm(path = 'js/wasm/carve.mjs') {
  if (modReady()) return true;
  if (loadP) return loadP;
  loadP = (async () => {
    try {
      const url = new URL(path, import.meta.url);
      const m = await import(url.href);
      const factory = m.default || m.createModule;
      if (!factory) throw new Error('no module factory');
      mod = await factory();
      return modReady();
    } catch (e) {
      mod = null;
      return false;
    }
  })();
  return loadP;
}

// Упаковать кадры и вызвать carve_occ. occ[] — Float32Array (nx*ny*nz), будет записан результат.
export function wasmCarveSlice(occ, dims, frames, opt) {
  if (!modReady()) return false;
  const { nx, ny, nz, vs, ox, oy, oz, Rb } = dims;
  const nF = frames.length;
  const FPF = 24;
  // Собрать общие буферы масок и альф; смещения в них идут от 0
  let mOff = 0, aOff = 0;
  const mStart = new Int32Array(nF), aStart = new Int32Array(nF);
  for (let i = 0; i < nF; i++) {
    mStart[i] = mOff; mOff += frames[i].mask.length;
    if (frames[i].alpha) { aStart[i] = aOff; aOff += frames[i].alpha.length; } else aStart[i] = -1;
  }
  // Сначала выделяем маски и альфы, потом уже фреймы и occ — чтобы рост HEAP при _malloc не инвалидировал
  // представление HEAPF32/HEAPU8 (ссылки DataView живые, но запись через .set надо делать после всех аллокаций? —
  // нет, HEAPU8 это TypedArray поверх AB, при росте он меняет буфер; поэтому ставим данные ПОСЛЕ всех _malloc.
  const maskBase = mod._malloc(mOff || 1);
  const alphaBase = aOff ? mod._malloc(aOff) : 0;
  const fp = mod._malloc(nF * FPF * 4);
  const occp = mod._malloc(occ.length * 4);
  // После всех _malloc заново берём представления HEAP (на случай роста buffer)
  const H8 = mod.HEAPU8, H32 = mod.HEAPF32;
  for (let i = 0; i < nF; i++) {
    H8.set(frames[i].mask, maskBase + mStart[i]);
    if (frames[i].alpha && aStart[i] >= 0) H8.set(frames[i].alpha, alphaBase + aStart[i]);
  }
  // Упаковать FFrameDesc
  const fb = new Float32Array(nF * FPF);
  const view = new DataView(fb.buffer);
  for (let i = 0; i < nF; i++) {
    const f = frames[i]; const K = f.K, R = f.R, t = f.t;
    const o = i * FPF;
    fb[o+0]=K.fx; fb[o+1]=K.fy; fb[o+2]=K.cx; fb[o+3]=K.cy;
    for (let j=0;j<9;j++) fb[o+4+j]=R[j];
    for (let j=0;j<3;j++) fb[o+13+j]=t[j];
    fb[o+16]=f.rms||0.5; fb[o+17]=f.w; fb[o+18]=f.h;
    view.setUint32((o+19)*4, mStart[i], true);
    view.setUint32((o+20)*4, aStart[i] >= 0 ? aStart[i] : 0, true);
    fb[o+21] = f._wF != null ? f._wF : 1;
    fb[o+22] = f.trusted ? 1 : 0;
    fb.fill(0, o+23, o+FPF);
  }
  H32.set(fb, fp >> 2);
  try {
    mod._carve_occ(occp, nx, ny, nz, vs, ox, oy, oz, Rb, fp, nF,
                  maskBase, alphaBase,
                  opt.frac ?? 0.08, opt.few ? 1 : 0, opt.weakMaj ?? 0.5,
                  opt.wMean ?? 1);
    occ.set(H32.subarray(occp >> 2, (occp >> 2) + occ.length));
  } catch (e) {
    mod._free(occp); mod._free(fp); mod._free(maskBase); if (alphaBase) mod._free(alphaBase);
    return false;
  }
  mod._free(occp); mod._free(fp); mod._free(maskBase); if (alphaBase) mod._free(alphaBase);
  return true;
}
