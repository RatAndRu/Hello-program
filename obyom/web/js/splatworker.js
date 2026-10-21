// Объём — поток для обучения сплэтов (v2.1): считает свою часть кадра (ряды тайлов k, k+K, …) — прямой и обратный
// проход, возвращает градиенты на картинке. Суммирует и переводит их в параметры капель главный поток (chain2d):
// итог тот же, что у обычного шага в одном потоке.
import { renderView } from './splat.js';
let P = {};
self.onmessage = (e) => {
  const m = e.data;
  if (m.type === 'ping') { self.postMessage({ type: 'pong' }); return; }
  // мягкое завершение: поток закрывается сам (terminate() вложенного потока в WebView/Chromium иногда роняет страницу)
  if (m.type === 'close') { self.postMessage({ type: 'bye' }); self.close(); return; }
  if (m.type === 'part') {
    try {
      const { n, deg, nb } = m, S = { n, deg, nb, cap: n, mu: m.mu, ls: m.ls, q: m.q, op: m.op, sh: m.sh };
      const G = { gain: [0, 0, 0] };
      const r = renderView(S, m.view, { grad: G, P, alphaW: m.alphaW, depthW: m.depthW, part: m.part, wsum: m.wsum, only2d: true });
      const d = r.d2, tr = [d.dU.buffer, d.dV.buffer, d.dA.buffer, d.dB.buffer, d.dC.buffer, d.dOp.buffer, d.dCol.buffer]; if (d.dZ) tr.push(d.dZ.buffer);
      self.postMessage({ type: 'd2', loss: r.loss, gain: G.gain, d2: d }, tr);
    } catch (err) { self.postMessage({ type: 'error', message: err.message || String(err) }); }
  }
};
