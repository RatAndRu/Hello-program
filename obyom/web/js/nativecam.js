// Объём — своя камера приложения (Android, Camera2) вместо камеры WebView.
// В Android WebView есть ошибка Chromium (issues.chromium.org/40884226): на части телефонов изображение
// getUserMedia «замирает» и идёт, только пока палец касается экрана. В APK кадры поэтому берутся из
// нативной камеры через мост ObyomNative и рисуются на холсте. В браузере остаётся обычная камера.

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function hasNativeCam() {
  const N = typeof window !== 'undefined' && window.ObyomNative;
  return !!(N && typeof N.camStart === 'function' && typeof N.camFrame === 'function');
}

// поворот на rot° по часовой стрелке; (x, y, w, h) — прямоугольник уже повёрнутой картинки
export function drawRot(c, img, rot, x, y, w, h) {
  if (!rot) { c.drawImage(img, x, y, w, h); return; }
  c.save(); c.translate(x + w / 2, y + h / 2); c.rotate(rot * Math.PI / 180);
  const sw = rot % 180 ? h : w, sh = rot % 180 ? w : h;
  c.drawImage(img, -sw / 2, -sh / 2, sw, sh); c.restore();
}

export class NativeCam {
  constructor(view) {
    this.view = view; this.bm = null; this.id = -1; this.rot = 0; this.alive = false; this.err = '';
    this.frames = 0; this.t0 = 0;
  }
  // размеры кадра с учётом поворота (как у <video>)
  get videoWidth() { return !this.bm ? 0 : this.rot % 180 ? this.bm.height : this.bm.width; }
  get videoHeight() { return !this.bm ? 0 : this.rot % 180 ? this.bm.width : this.bm.height; }
  drawTo(c, w, h) { if (this.bm) drawRot(c, this.bm, this.rot, 0, 0, w, h); }

  async open() {
    const N = window.ObyomNative, t0 = performance.now();
    for (;;) {
      const r = N.camStart(1280, 720);
      if (r === 'ok') break;
      if (r !== 'perm') throw new Error(r);
      if (performance.now() - t0 > 90000) throw new Error('нет разрешения на камеру');
      await sleep(400);
    }
    this.alive = true; this.err = ''; this.t0 = performance.now(); this.frames = 0;
    this.pump();
    const t1 = performance.now();
    while (!this.bm && performance.now() - t1 < 8000) await sleep(50);
    if (!this.bm) { const e = this.err; this.close(); throw new Error('камера не прислала ни одного кадра' + (e ? ': ' + e : '')); }
  }
  close() {
    this.alive = false;
    try { window.ObyomNative.camStop(); } catch (e) {}
  }
  // забираем кадры, как только они готовы; анализ и показ берут последний
  async pump() {
    const N = window.ObyomNative;
    while (this.alive) {
      let s = '';
      try { s = N.camFrame(this.id); } catch (e) { s = 'E:' + (e && e.message); }
      if (!s) { await sleep(8); continue; }
      if (s.startsWith('E:')) { this.err = s.slice(2); await sleep(150); continue; }
      try {
        let p = 0; const parts = [];
        for (let k = 0; k < 4; k++) { const q = s.indexOf('|', p); parts.push(+s.slice(p, q)); p = q + 1; }
        const [rot, id] = parts, bin = atob(s.slice(p)), u = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
        const bm = await createImageBitmap(new Blob([u], { type: 'image/jpeg' }));
        if (!this.alive) { bm.close && bm.close(); break; }
        if (this.bm && this.bm.close) this.bm.close();
        this.bm = bm; this.id = id; this.rot = rot; this.err = ''; this.frames++;
        this.show();
      } catch (e) { this.err = 'кадр: ' + (e && e.message); await sleep(30); }
    }
  }
  get fps() { const dt = (performance.now() - this.t0) / 1000; return dt > 0 ? this.frames / dt : 0; }
  // показ на экране: как object-fit: cover у <video>
  show() {
    const v = this.view; if (!v || !this.bm) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1), W = Math.round(v.clientWidth * dpr), H = Math.round(v.clientHeight * dpr);
    if (!W || !H) return;
    if (v.width !== W || v.height !== H) { v.width = W; v.height = H; }
    const vw = this.videoWidth, vh = this.videoHeight, s = Math.max(W / vw, H / vh);
    drawRot(v.getContext('2d'), this.bm, this.rot, (W - vw * s) / 2, (H - vh * s) / 2, vw * s, vh * s);
  }
}
