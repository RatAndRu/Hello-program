// v2.8: C++/WASM ускорение для carveHull.
// Загружает wasm модуль лениво при первом carveHull. Если не загрузился — JS-фоллбэк в recon.js.
let mod = null, loadP = null;
export function wasmReady() { return !!mod; }
export async function ensureCarveWasm(path = 'js/wasm/carve.mjs') {
  if (mod) return true;
  if (loadP) return loadP;
  loadP = (async () => {
    try {
      const url = new URL(path, import.meta.url);
      const m = await import(url.href);
      const instance = await m.default || await m.createModule();
      mod = instance;
      return true;
    } catch (e) {
      mod = null;
      return false;
    }
  })();
  return loadP;
}
// Запустить C carve_occ; возвращает true если получилось, и occ[] записан.
export function wasmCarveSlice(occ, dims, frames, opt) {
  if (!mod) return false;
  const { nx, ny, nz, vs, ox, oy, oz, Rb } = dims;
  const nF = frames.length;
  // Считаем общий размер буферов и упаковываем все маски/альфы в общий HEAPU8-блок
  let mOff = 0, aOff = 0;
  const mStart = []; const aStart = [];
  for (const f of frames) { mStart.push(mOff); mOff += f.mask.length; aStart.push(f.alpha ? aOff : -1); if (f.alpha) aOff += f.alpha.length; }
  const maskBase = mod._malloc(mOff || 1);
  const alphaBase = aOff ? mod._malloc(aOff) : 0;
  for (let i = 0; i < nF; i++) {
    mod.HEAPU8.set(frames[i].mask, maskBase + mStart[i]);
    if (frames[i].alpha && aStart[i] >= 0) mod.HEAPU8.set(frames[i].alpha, alphaBase + aStart[i]);
  }
  const FPF = 24;
  const fSize = nF * FPF * 4;
  const fp = mod._malloc(fSize);
  const fb = new Float32Array(nF * FPF);
  for (let i = 0; i < nF; i++) {
    const f = frames[i]; const K = f.K, R = f.R, t = f.t;
    const o = i * FPF;
    fb[o+0]=K.fx; fb[o+1]=K.fy; fb[o+2]=K.cx; fb[o+3]=K.cy;
    for (let j=0;j<9;j++) fb[o+4+j]=R[j];
    for (let j=0;j<3;j++) fb[o+13+j]=t[j];
    fb[o+16]=f.rms||0.5; fb[o+17]=f.w; fb[o+18]=f.h;
    fb[o+19]=maskBase + mStart[i];
    fb[o+20]=aStart[i] >= 0 ? alphaBase + aStart[i] : 0;
    fb[o+21]=f._wF != null ? f._wF : 1;
    fb[o+22]=f.trusted ? 1 : 0;
    fb[o+23]=0;
  }
  mod.HEAPF32.set(fb, fp >> 2);
  const occp = mod._malloc(occ.length * 4);
  try {
    mod._carve_occ(occp, nx, ny, nz, vs, ox, oy, oz, Rb, fp, nF,
                  opt.frac ?? 0.08, opt.few ? 1 : 0, opt.weakMaj ?? 0.5, opt.trustFrac ?? 0.1,
                  opt.wMean ?? 1);
    // В emscriptен модуле HEAPU8 смещение начинается с HEAP8_BASE (не нуля), а _malloc возвращает указатель уже в этом пространстве.
    // Корректно читать через mod.HEAPF32 с базы = occp >> 2:
    occ.set(mod.HEAPF32.subarray(occp >> 2, (occp >> 2) + occ.length));
  } catch (e) {
    mod._free(occp); mod._free(fp); mod._free(maskBase); if (alphaBase) mod._free(alphaBase);
    return false;
  }
  mod._free(occp); mod._free(fp); mod._free(maskBase); if (alphaBase) mod._free(alphaBase);
  return true;
}
