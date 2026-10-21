import { Splats, renderView, makeGrad } from '../web/js/splat.js';
let seed = 3; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
const S = new Splats(30);
for (let i = 0; i < 12; i++) S.push([(rnd() - 0.5) * 30, (rnd() - 0.5) * 30, (rnd() - 0.5) * 20], [Math.log(2 + rnd() * 4), Math.log(2 + rnd() * 4), Math.log(1 + rnd() * 3)], [rnd(), rnd() - .5, rnd() - .5, rnd() - .5], (rnd() - 0.5) * 2, [rnd() * 2 - 1, rnd() * 2 - 1, rnd() * 2 - 1]);
const w = 40, h = 32;
const view = { K: { fx: 60, fy: 60, cx: 20, cy: 16 }, t: [0, 0, 120], x0: 0, y0: 0, cw: w, ch: h, img: new Float32Array(w*h*3).fill(0.9), bg: new Float32Array(w*h*3).fill(0.2), wt: new Float32Array(w * h) };
const aa = 0.3; view.R = [Math.cos(aa), 0, Math.sin(aa), 0, 1, 0, -Math.sin(aa), 0, Math.cos(aa)];
for (const [name,k] of [['mu',0],['mu',2],['ls',0],['ls',2],['q',1],['q',3]]) { let shown = 0, tot=0, bad=0;
for (let j = 0; j < w * h && 1; j++) {
  view.wt.fill(0); view.wt[j] = 1;
  const G = makeGrad(S.n); renderView(S, view, { grad: G });
  const lossOf = () => renderView(S, view, { grad: makeGrad(S.n) }).loss;
  const jj = name==='q'? 44+k : 33+k; const v0 = S[name][jj], e = name==='mu'?1e-3:1e-4; S[name][jj] = v0 + e; const lp = lossOf(); S[name][jj] = v0 - e; const lm = lossOf(); S[name][jj] = v0;
  const num = (lp - lm) / 2 / e, an = G[name][jj]; if (Math.abs(num)+Math.abs(an)>1e-6) tot++;
  if (Math.abs(num - an) > 1e-4 + 0.02 * Math.abs(num)) { bad++; }
}
console.log(name,k,'pixels with grad',tot,'mismatch',bad); }
