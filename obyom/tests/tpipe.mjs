// Дымовой тест всего конвейера (runPipeline) в Node, без браузера: createImageBitmap / OffscreenCanvas / ImageData —
// заглушки, «снимки» — заранее раскрытые кадры сцены (toraw.py <dir> 640). JPEG не кодируется (сырые байты).
// node tpipe.mjs <dir> [mode=mesh|splat|both] [shape=normal|vessel|…]   env: QUALITY=fast, ITERS (сплэты), CLOSE=n
import fs from 'fs';
const dir = process.argv[2], mode = process.argv[3] || 'mesh', shape = process.argv[4] || 'normal';
const gt = JSON.parse(fs.readFileSync(dir + '/gt.json')), W = 640, H = Math.round(gt.h * W / gt.w);
globalThis.ImageData = class { constructor(data, w, h) { this.data = data; this.width = w; this.height = h; } };
globalThis.createImageBitmap = async (b) => { const r = b._raw; return { width: r.w, height: r.h, data: r.rgba, close() {} }; };
globalThis.OffscreenCanvas = class {
  constructor(w, h) { this.width = w; this.height = h; this.buf = new Uint8ClampedArray(w * h * 4); }
  getContext() { const c = this; return {
    drawImage(bm, x, y, w, h) { // ближайший сосед (масштаб в тесте 1:1)
      for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const sx = Math.min(bm.width - 1, (i * bm.width / w) | 0), sy = Math.min(bm.height - 1, (j * bm.height / h) | 0), s = (sy * bm.width + sx) * 4, o = (j * c.width + i) * 4; for (let k = 0; k < 4; k++) c.buf[o + k] = bm.data[s + k]; } },
    getImageData(x, y, w, h) { return { data: c.buf }; }, putImageData(id) { c.buf.set(id.data); } }; }
  async convertToBlob() { const u = new Uint8Array(this.buf.buffer.slice(0)); return { arrayBuffer: async () => u.buffer }; }
};
const blob = (f) => ({ _raw: { rgba: new Uint8Array(fs.readFileSync(dir + '/' + f.replace('.jpg', `_${W}.rgba`))), w: W, h: H } });
const blobs = gt.frames.map((fr) => blob(fr.file));
const { runPipeline } = await import('../web/js/pipeline.js');
const job = { blobs, mode, quality: process.env.QUALITY || 'fast', size: 'A4', theme: 'light', Hb: 90, method: process.env.WALK ? 'walk' : 'turn', shape, pool: false };
if (process.env.ITERS) job.iters = +process.env.ITERS;
const t0 = Date.now(); let last = '';
const cb = { progress: (t, p, s) => { const k = t; if (k !== last) { last = k; process.stdout.write(`  · ${t}\n`); } }, log: (m) => console.log('LOG', m), partial: () => console.log('  (сетка сохранена до сплэтов)'), preview: () => {} };
const r = await runPipeline(job, cb);
const M = r.mesh;
console.log('ИТОГ', ((Date.now() - t0) / 1000).toFixed(0) + ' с', 'вершин', M.pos.length / 3, 'треуг.', M.idx.length / 3, 'текстура', !!M.tex, 'детальность', !!M.detail, 'pbr', !!M.pbr, 'сплэты', r.splats ? r.splats.length : 0, 'объём оболочки', (r.stats.hullVol / 1000).toFixed(1), 'см³');
