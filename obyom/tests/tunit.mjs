// Быстрые проверки без сцен (CI): node tunit.mjs → «OK», иначе код выхода 1
import { makeZip, makeZipBlob } from '../web/js/zip.js';
import { applyVertexDisp, weldIndex } from '../web/js/surface.js';
import { snapPlanes } from '../web/js/shapes.js';
let bad = 0; const check = (ok, what) => { console.log((ok ? '✓ ' : '✗ ') + what); if (!ok) bad++; };

// 1) потоковый ZIP = обычный ZIP байт в байт
{
  const a = new Uint8Array(5000).map((_, i) => (i * 7) & 255), b = new TextEncoder().encode('{"x":1}');
  const z1 = makeZip([{ name: 'frames/f000.jpg', data: a }, { name: 'info.json', data: b }]);
  const z2 = new Uint8Array(await (await makeZipBlob([{ name: 'frames/f000.jpg', data: new Blob([a]) }, { name: 'info.json', data: b }])).arrayBuffer());
  check(z1.length === z2.length && z1.every((v, i) => v === z2[i]), 'потоковый ZIP совпадает с обычным');
}
// 2) сдвиг вершин: копии вершины на шве развёртки остаются вместе, нормали у них общие
{
  // два треугольника, общая сторона — вершины продублированы (как после развёртки)
  const pos = new Float32Array([0, 0, 0, 10, 0, 0, 0, 10, 0, /* копии */ 10, 0, 0, 0, 10, 0, 10, 10, 2]);
  const nrm = new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1, 0.1, 0, 0.99, 0.1, 0, 0.99, 0.1, 0, 0.99]);
  const M = { pos, nrm, idx: new Uint32Array([0, 1, 2, 3, 5, 4]) };
  const W = weldIndex(pos); check(W.n === 4, 'склейка по положению: 6 вершин → 4');
  applyVertexDisp(M, new Float32Array([0, 1, 1, 1, 1, 0]));
  const same = (i, j) => Math.hypot(M.pos[i * 3] - M.pos[j * 3], M.pos[i * 3 + 1] - M.pos[j * 3 + 1], M.pos[i * 3 + 2] - M.pos[j * 3 + 2]) < 1e-5;
  check(same(1, 3) && same(2, 4), 'шов без трещины после сдвига');
  check(Math.abs(M.nrm[3] - M.nrm[9]) < 1e-6 && Math.abs(M.nrm[5] - M.nrm[11]) < 1e-6, 'общая нормаль у копий вершины');
}
// 3) «Плоские грани»: вмятина 1.5 мм сохраняется, шум ровной части убирается
{
  const n = 81, pos = [], nrm = [], idx = [];
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) { const X = x - 40, Y = y - 40, r = Math.hypot(X, Y); pos.push(X, Y, (r < 10 ? -1.5 * Math.cos(r / 10 * Math.PI / 2) ** 2 : 0) + 0.3 * Math.sin(x * 1.7 + y)); nrm.push(0, 0, 1); }
  for (let y = 0; y < n - 1; y++) for (let x = 0; x < n - 1; x++) { const a = y * n + x; idx.push(a, a + 1, a + n, a + 1, a + n + 1, a + n); }
  const r = snapPlanes({ pos: new Float32Array(pos), nrm: new Float32Array(nrm), idx: new Uint32Array(idx) });
  let zc = 1e9, rough = 0, nr = 0; for (let i = 0; i < r.mesh.pos.length; i += 3) { const X = r.mesh.pos[i], Y = r.mesh.pos[i + 1], Z = r.mesh.pos[i + 2]; if (Math.hypot(X, Y) < 1) zc = Math.min(zc, Z); if (Math.hypot(X, Y) > 15) { rough += Math.abs(Z); nr++; } }
  check(zc < -1.0, `плоские грани: вмятина сохранена (дно ${zc.toFixed(2)} мм из −1.5)`);
  check(rough / nr < 0.05, `плоские грани: ровная часть выровнена (шум ${(rough / nr).toFixed(3)} мм)`);
}
// 2б) острое ребро (копии с разными нормалями) после сдвига остаётся острым
{
  const pos = new Float32Array([0, 0, 0, 10, 0, 0, 0, 10, 0, 10, 0, 0, 0, 10, 0, 5, 5, -10]);
  const nrm = new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1, 0.7, 0.7, 0, 0.7, 0.7, 0, 0.7, 0.7, 0]);
  const M = { pos, nrm, idx: new Uint32Array([0, 1, 2, 3, 5, 4]) };
  applyVertexDisp(M, new Float32Array(6).fill(0.1));
  check(M.nrm[3] * M.nrm[9] + M.nrm[4] * M.nrm[10] + M.nrm[5] * M.nrm[11] < 0.9, 'острое ребро не сглажено');
}
console.log(bad ? 'ЕСТЬ ОШИБКИ' : 'OK'); if (bad) process.exit(1);
