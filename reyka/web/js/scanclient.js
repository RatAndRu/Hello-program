// Клиент движка оцифровки: фоновый поток (Web Worker), а если он недоступен — тот же движок
// в основном потоке (медленнее для интерфейса, но работает везде).
export class ScanClient {
  constructor() {
    this.n = 0; this.cb = new Map(); this.lastRect = null; this.mode = 'starting';
    this.ready = new Promise((res) => { this._readyRes = res; });
    try {
      this.w = new Worker(new URL('./scanworker.js', import.meta.url), { type: 'module' });
      this.w.onmessage = (e) => this._done(e.data);
      this.w.onerror = (e) => { e.preventDefault && e.preventDefault(); this._fallback(); };
      // проверка, что поток реально запустился (модульные воркеры есть не везде)
      const id = ++this.n;
      this.cb.set(id, () => { clearTimeout(this._t); this.mode = 'worker'; this._readyRes(); });
      this.w.postMessage({ id, cmd: 'ping' });
      this._t = setTimeout(() => this._fallback(), 4000);
    } catch { this._fallback(); }
  }
  async _fallback() {
    if (this.mode === 'local' || this.mode === 'switching') return;
    clearTimeout(this._t);
    try { this.w && this.w.terminate(); } catch { /* уже нет */ }
    this.w = null; this.mode = 'switching'; // пока грузится движок — запросы ждут в this.cb
    const { ScanEngine, makePump } = await import('./scanengine.js');
    this.local = makePump(new ScanEngine(), (m) => this._done(m));
    this.mode = 'local';
    // всё, что ждало ответа от потока, — переотправляем
    const pend = [...this.cb.entries()].filter(([, f]) => f.msg);
    if (this.lastRect) this.local(this.lastRect);
    for (const [, f] of pend) if (f.msg.cmd !== 'rect') this.local(f.msg);
    this._readyRes();
  }
  _done(m) { const f = this.cb.get(m.id); if (!f) return; this.cb.delete(m.id); f(m); }
  _send(msg) {
    return new Promise((res, rej) => {
      const id = msg.id = ++this.n;
      const f = (m) => { if (m.error) rej(new Error(m.error)); else res(m); };
      f.msg = msg; this.cb.set(id, f);
      if (this.mode === 'local') this.local(msg);
      else if (this.w && (this.mode === 'worker' || this.mode === 'starting')) this.w.postMessage(msg);
      // 'switching' — отправим, когда движок загрузится
    });
  }
  // Новый снимок. В поток уходит копия (свою оставляем — для поворотов и пипетки).
  setRect(rect, ppm) {
    const msg = { cmd: 'rect', rect: { data: new Uint8ClampedArray(rect.data), w: rect.w, h: rect.h }, ppm };
    this.lastRect = msg;
    return this._send(msg);
  }
  async run(req) { const m = await this._send({ cmd: 'run', req }); return m.stale ? null : m.res; }
  async cached(req) { const m = await this._send({ cmd: 'run', req, probe: true }); return !!m.cached; }
}
