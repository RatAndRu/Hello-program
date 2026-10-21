// v2.1: шаг сплэтов по частям кадра (потоки) = обычный шаг. Сравнение градиентов: renderView целиком
// против суммы частей (only2d, part) + chain2d. node tpool.mjs
import { Splats, renderView, makeGrad, prepView, chain2d } from '../web/js/splat.js';
let seed = 3; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
const S = new Splats(600, 1);
for (let i = 0; i < 500; i++) S.push([(rnd() - 0.5) * 60, (rnd() - 0.5) * 45, 90 + rnd() * 30], [Math.log(1 + rnd() * 3), Math.log(1 + rnd() * 3), Math.log(0.3)], [rnd(), rnd(), rnd(), rnd()], rnd() * 4 - 2, [rnd(), rnd(), rnd()]);
const cw = 160, ch = 120, N = cw * ch, img = new Float32Array(N * 3), bg = new Float32Array(N * 3), wt = new Float32Array(N), at = new Int8Array(N);
for (let j = 0; j < N; j++) { for (let c = 0; c < 3; c++) { img[j * 3 + c] = rnd(); bg[j * 3 + c] = rnd(); } wt[j] = rnd() < 0.1 ? 0.15 : 1; at[j] = rnd() < 0.3 ? -1 : rnd() < 0.5 ? 0 : 1; }
const view = { K: { fx: 160, fy: 160, cx: 80, cy: 60 }, R: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, 0], x0: 0, y0: 0, cw, ch, img, bg, wt, at, gain: [1.1, 0.95, 1] };
const opt = { alphaW: 0.2, depthW: 0.0003 };
const G1 = makeGrad(S.n, S.nb), r1 = renderView(S, view, { ...opt, grad: G1, P: {} });
let ws = 0; for (let j = 0; j < N; j++) ws += wt[j];
for (const K of [2, 3, 4]) {
  const parts = []; for (let k = 0; k < K; k++) { const G = { gain: [0, 0, 0] }; const r = renderView(S, { ...view }, { ...opt, grad: G, P: {}, part: { k, K }, wsum: ws, only2d: true }); parts.push({ r, G }); }
  const d2 = parts[0].r.d2; let loss = parts[0].r.loss; const gain = [...parts[0].G.gain];
  for (let k = 1; k < K; k++) { const b = parts[k].r.d2; loss += parts[k].r.loss; for (let c = 0; c < 3; c++) gain[c] += parts[k].G.gain[c]; for (const nm of Object.keys(d2)) if (d2[nm]) for (let i = 0; i < d2[nm].length; i++) d2[nm][i] += b[nm][i]; }
  const P = {}, pv = prepView(S, view, P), G2 = makeGrad(S.n, S.nb); G2.gain = gain;
  chain2d(S, view, P, d2, G2, pv.inRange, pv.basis, pv.opa);
  let md = 0, mx = 0;
  for (const nm of ['mu', 'ls', 'q', 'op', 'sh', 'm2d', 'cnt']) for (let i = 0; i < G1[nm].length; i++) { md = Math.max(md, Math.abs(G1[nm][i] - G2[nm][i])); mx = Math.max(mx, Math.abs(G1[nm][i])); }
  for (let c = 0; c < 3; c++) md = Math.max(md, Math.abs(G1.gain[c] - gain[c]));
  console.log(`K=${K}: loss ${r1.loss.toFixed(6)} / ${loss.toFixed(6)}, макс. разница градиентов ${md.toExponential(2)} (макс. градиент ${mx.toExponential(2)})`);
  if (Math.abs(r1.loss - loss) > 1e-6 * Math.abs(r1.loss) + 1e-9 || md > 1e-5 * mx) { console.log('НЕ СОВПАЛО'); process.exit(1); }
}
console.log('совпадает');
