// v2.8: C++/WASM ускорение для carveHull.
// Загружает wasm модуль лениво; если он недоступен (не собран в CI, нет WASM, CSP и т.п.),
// оставляет JS-реализацию как fallback (recon.js не вызывает модуль напрямую, только через эту обёртку).
let mod = null, loadP = null;
export function wasmCarveReady() { return !!mod; }
export async function ensureCarveWasm(path = 'js/wasm/carve.mjs') {
  if (mod) return true;
  if (loadP) return loadP;
  loadP = (async () => {
    try {
      // в APK/сайте модуль лежит рядом с web/js; в dev тоже
      const url = new URL(path, import.meta.url);
      const m = await import(url.href);
      await m.ready;
      mod = m;
      return true;
    } catch (e) {
      mod = null;
      return false;
    }
  })();
  return loadP;
}
// pack frames into flat Float32 for wasm and run carve_occ on slice [zFrom,zTo)
export function wasmCarveSlice(occ, dims, frames, opt) {
  if (!mod) return false;
  const { nx, ny, nz, vs, ox, oy, oz, Rb } = dims;
  const nF = frames.length;
  // строим общий буфер масок и таблицу смещений
  let totalMask = 0;
  for (const f of frames) totalMask += f.mask.length;
  const maskBuf = new Uint8Array(totalMask);
  const offs = new Int32Array(nF);
  let p = 0;
  for (let i = 0; i < nF; i++) { offs[i] = p; maskBuf.set(frames[i].mask, p); p += frames[i].mask.length; }
  const floatsPerFrame = 21;
  const fb = new Float32Array(nF * floatsPerFrame);
  for (let i = 0; i < nF; i++) {
    const f = frames[i]; const K = f.K, R = f.R, t = f.t;
    const o = i * floatsPerFrame;
    fb[o+0]=K.fx; fb[o+1]=K.fy; fb[o+2]=K.cx; fb[o+3]=K.cy;
    for (let j=0;j<9;j++) fb[o+4+j]=R[j];
    for (let j=0;j<3;j++) fb[o+13+j]=t[j];
    fb[o+16]=f.rms||0.5; fb[o+17]=f.w; fb[o+18]=f.h; fb[o+19]=offs[i]; fb[o+20]=f.trusted?1:0;
  }
  try {
    const occp = mod._malloc(occ.length * 4); mod.HEAPF32.set(occ, occp>>2);
    const fbp = mod._malloc(fb.byteLength); mod.HEAPF32.set(fb, fbp>>2);
    const mp = mod._malloc(maskBuf.byteLength); mod.HEAPU8.set(maskBuf, mp);
    // корректируем смещения масок с учётом базы mp
    for (let i=0;i<nF;i++) fb[i*floatsPerFrame+20] = mp + offs[i];
    mod.HEAPF32.set(fb, fbp>>2);
    mod._carve_occ(occp, nx, ny, nz, vs, ox, oy, oz, Rb, fbp, nF, mp,
                   opt.frac ?? 0.08, (opt.few||false)?1:0, opt.weakMaj ?? 0.5, 0, nz);
    occ.set(mod.HEAPF32.subarray(occp>>2, (occp>>2)+occ.length));
    mod._free(occp); mod._free(fbp); mod._free(mp);
    return true;
  } catch (e) { return false; }
}
