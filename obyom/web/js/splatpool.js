// Объём — обучение сплэтов в нескольких потоках (v2.1). Без общей памяти (в Android WebView её нет):
// каждый шаг — один кадр, как и раньше, но его ряды тайлов делятся между потоками (k, k+K, k+2K, … — поровну
// по работе). Потоки возвращают градиенты на картинке, главный поток их складывает и переводит в параметры капель
// (chain2d) — шаг математически тот же, что в одном потоке (меняется лишь порядок сложения), качество не страдает.
import { prepView, chain2d } from './splat.js';
const wait = (w, type, ms) => new Promise((res, rej) => {
  const to = ms ? setTimeout(() => rej(new Error('поток не ответил')), ms) : null;
  w.onmessage = (e) => { if (e.data.type === type) { if (to) clearTimeout(to); res(e.data); } else if (e.data.type === 'error') { if (to) clearTimeout(to); rej(new Error(e.data.message)); } };
  w.onerror = (e) => { if (to) clearTimeout(to); rej(new Error('поток: ' + (e.message || 'ошибка'))); };
});
// сколько потоков: ядер − 1 (главный поток обработки тоже работает), не больше 4 (малые ядра медленнее, нагрев)
// закрыть потоки мягко: просим закрыться и ждём ответа (до 3 с); terminate() — только для зависших
async function closeAll(ws) {
  await Promise.all(ws.map((w) => new Promise((res) => {
    const to = setTimeout(() => { try { w.terminate(); } catch (e) {} res(); }, 3000);
    w.onerror = null; w.onmessage = (e) => { if (e.data && e.data.type === 'bye') { clearTimeout(to); res(); } };
    try { w.postMessage({ type: 'close' }); } catch (e) { clearTimeout(to); res(); }
  })));
  await new Promise((r) => setTimeout(r, 50));
}
export function poolSize() {
  const hc = (typeof navigator !== 'undefined' && navigator.hardwareConcurrency) || 1;
  return Math.max(1, Math.min(4, hc - 1));
}
export async function createPool(nW) {
  if (typeof Worker === 'undefined' || nW < 2) return null;
  const ws = [];
  try {
    for (let i = 0; i < nW; i++) ws.push(new Worker(new URL('./splatworker.js', import.meta.url), { type: 'module' }));
    await Promise.all(ws.map((w) => { const p = wait(w, 'pong', 5000); w.postMessage({ type: 'ping' }); return p; }));
  } catch (e) { await closeAll(ws); return null; }
  let dead = null;
  return {
    size: nW,
    // один шаг обучения (как Trainer.step, но кадр считают все потоки по частям)
    async step(tr) {
      if (dead) throw dead;
      const S = tr.S, n = S.n, nb = S.nb, vi = tr.pick(1)[0], v = tr.views[vi];
      if (v._wsum == null) { let s = 0; for (let j = 0; j < v.wt.length; j++) s += v.wt[j]; v._wsum = s; }
      const view = { K: v.K, R: v.R, t: v.t, x0: v.x0, y0: v.y0, cw: v.cw, ch: v.ch, img: v.img, bg: v.bg, wt: v.wt, at: v.at, gain: v.gain };
      const base = { type: 'part', n, deg: S.deg, nb, mu: S.mu.subarray(0, n * 3), ls: S.ls.subarray(0, n * 3), q: S.q.subarray(0, n * 4), op: S.op.subarray(0, n), sh: S.sh.subarray(0, n * 3 * nb), view, wsum: v._wsum, alphaW: tr.o.alphaW, depthW: tr.o.depthW };
      const ps = ws.map((w, k) => { const p = wait(w, 'd2', 120000); w.postMessage({ ...base, part: { k, K: ws.length } }); return p; });
      const pv = prepView(S, v, tr.P); // пока потоки считают — проекция капель здесь (нужна для chain2d)
      let outs; try { outs = await Promise.all(ps); } catch (e) { dead = e; throw e; }
      const d2 = outs[0].d2; let loss = outs[0].loss; const gain = [...outs[0].gain];
      for (let o = 1; o < outs.length; o++) {
        const b = outs[o].d2; loss += outs[o].loss; for (let c = 0; c < 3; c++) gain[c] += outs[o].gain[c];
        for (const name of ['dU', 'dV', 'dA', 'dB', 'dC', 'dOp', 'dCol', 'dZ']) { const A = d2[name], B = b[name]; if (A && B) for (let i = 0; i < A.length; i++) A[i] += B[i]; }
      }
      const G = tr.gradBuf(); G.gain = gain;
      chain2d(S, v, tr.P, d2, G, pv.inRange, pv.basis, pv.opa);
      return tr.apply(G, [{ vi, loss, gain }]);
    },
    close() { return closeAll(ws); },
  };
}
