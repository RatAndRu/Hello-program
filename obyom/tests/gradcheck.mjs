// Проверка градиентов рендера сплэтов численно (конечные разности). node gradcheck.mjs → «mismatch 0» везде.
// С 1.9: гармоники цвета (sh), поправка яркости кадра (gain), цель прозрачности по маске (alphaW), стягивание к поверхности (depthW).
import { Splats, renderView, makeGrad } from '../web/js/splat.js';
let seed = 3; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
const DEG = 2, S = new Splats(30, DEG);
for (let i = 0; i < 12; i++) {
  const sh = []; for (let k = 0; k < 3 * S.nb; k++) sh.push(k < 3 ? (rnd() - 0.5) * 1.2 : (rnd() - 0.5) * 0.4);
  S.push([(rnd() - 0.5) * 30, (rnd() - 0.5) * 30, (rnd() - 0.5) * 20], [Math.log(2 + rnd() * 4), Math.log(2 + rnd() * 4), Math.log(1 + rnd() * 3)], [rnd(), rnd() - .5, rnd() - .5, rnd() - .5], (rnd() - 0.5) * 2, sh);
}
const w = 40, h = 32;
const view = { K: { fx: 60, fy: 60, cx: 20, cy: 16 }, t: [0, 0, 120], x0: 0, y0: 0, cw: w, ch: h, img: new Float32Array(w * h * 3).fill(0.9), bg: new Float32Array(w * h * 3).fill(0.2), wt: new Float32Array(w * h), at: new Int8Array(w * h).fill(-1), gain: [1.1, 0.95, 1.02] };
const aa = 0.3; view.R = [Math.cos(aa), 0, Math.sin(aa), 0, 1, 0, -Math.sin(aa), 0, Math.cos(aa)];
const OPT = { alphaW: 0.5, depthW: 0.05 };
let totalBad = 0;
const check = (label, get, set, gradOf, e) => {
  let tot = 0, bad = 0;
  for (let j = 0; j < w * h; j += 3) {
    view.wt.fill(0); view.at.fill(-1); view.wt[j] = 1; view.at[j] = j % 2; // пиксель: цвет + цель прозрачности
    const G = makeGrad(S.n, S.nb); renderView(S, view, { grad: G, ...OPT });
    const lossOf = () => renderView(S, view, { grad: makeGrad(S.n, S.nb), ...OPT }).loss;
    const v0 = get(); set(v0 + e); const lp = lossOf(); set(v0 - e); const lm = lossOf(); set(v0);
    const num = (lp - lm) / 2 / e, an = gradOf(G); if (Math.abs(num) + Math.abs(an) > 1e-6) tot++;
    if (Math.abs(num - an) > 1e-4 + 0.03 * Math.abs(num)) bad++;
  }
  totalBad += bad; console.log(label, 'pixels with grad', tot, 'mismatch', bad);
};
for (const [name, k] of [['mu', 0], ['mu', 2], ['ls', 0], ['ls', 2], ['q', 1], ['q', 3], ['op', 0], ['sh', 0], ['sh', 4], ['sh', 13], ['sh', 25]]) {
  const jj = name === 'q' ? 44 + k : name === 'op' ? 11 : name === 'sh' ? 3 * S.nb * 3 + k : 33 + k, e = name === 'mu' ? 1e-3 : 1e-4;
  check(`${name}[${k}]`, () => S[name][jj], (v) => { S[name][jj] = v; }, (G) => G[name][jj], e);
}
for (let c = 0; c < 3; c++) check(`gain[${c}]`, () => view.gain[c], (v) => { view.gain[c] = v; }, (G) => G.gain[c], 1e-4);
console.log(totalBad ? 'ЕСТЬ РАСХОЖДЕНИЯ' : 'OK');
