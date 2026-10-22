// Объём — квадратная сетка (ретопология, v2.3). Без нейросетей: surface nets на грубой решётке + расслабление
// с проекцией на исходную поверхность. Для анимации и скульптинга: ровные четырёхугольники примерно одного размера.
// Текстура на квадах не переносится (лоскуты атласа режутся) — цвет вершин; детальную текстуру запекают в Blender
// с исходной (треугольной) модели: Bake → Selected to Active.

// M: {pos, nrm, col, idx} (мм, Z вверх, замкнутая); target — желаемое число четырёхугольников
export function quadRemesh(M, target = 4000, opt = {}) {
  const P = M.pos, I = M.idx, nt = I.length / 3;
  let A = 0; const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < P.length; i += 3) for (let c = 0; c < 3; c++) { if (P[i + c] < mn[c]) mn[c] = P[i + c]; if (P[i + c] > mx[c]) mx[c] = P[i + c]; }
  for (let t = 0; t < nt; t++) { const a = I[t * 3] * 3, b = I[t * 3 + 1] * 3, c = I[t * 3 + 2] * 3;
    const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2], vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2];
    A += 0.5 * Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx); }
  const cs = opt.cell || Math.sqrt(1.55 * A / Math.max(50, target)); // ячейка решётки даёт в среднем ~1.55 квада
  // решётка с полями; узлы сдвинуты на «некруглую» долю, чтобы лучи не попадали точно в рёбра треугольников
  const ox = mn[0] - 1.37 * cs, oy = mn[1] - 1.41 * cs, oz = mn[2] - 1.29 * cs;
  const nx = Math.ceil((mx[0] - ox) / cs) + 2, ny = Math.ceil((mx[1] - oy) / cs) + 2, nz = Math.ceil((mx[2] - oz) / cs) + 2;
  if (nx * ny * nz > 6e6) throw new Error('слишком мелкие квадраты для такого предмета');
  // 1) внутри/снаружи в узлах: чётность пересечений вертикального луча с треугольниками
  const cols = new Array(nx * ny);
  for (let t = 0; t < nt; t++) {
    const a = I[t * 3] * 3, b = I[t * 3 + 1] * 3, c = I[t * 3 + 2] * 3;
    const x0 = Math.max(0, Math.ceil((Math.min(P[a], P[b], P[c]) - ox) / cs)), x1 = Math.min(nx - 1, Math.floor((Math.max(P[a], P[b], P[c]) - ox) / cs));
    const y0 = Math.max(0, Math.ceil((Math.min(P[a + 1], P[b + 1], P[c + 1]) - oy) / cs)), y1 = Math.min(ny - 1, Math.floor((Math.max(P[a + 1], P[b + 1], P[c + 1]) - oy) / cs));
    for (let iy = y0; iy <= y1; iy++) for (let ix = x0; ix <= x1; ix++) {
      const X = ox + ix * cs, Y = oy + iy * cs;
      const d = (P[b] - P[a]) * (P[c + 1] - P[a + 1]) - (P[c] - P[a]) * (P[b + 1] - P[a + 1]); if (Math.abs(d) < 1e-12) continue;
      const l1 = ((X - P[a]) * (P[c + 1] - P[a + 1]) - (P[c] - P[a]) * (Y - P[a + 1])) / d, l2 = ((P[b] - P[a]) * (Y - P[a + 1]) - (X - P[a]) * (P[b + 1] - P[a + 1])) / d;
      if (l1 < 0 || l2 < 0 || l1 + l2 > 1) continue;
      const z = P[a + 2] + l1 * (P[b + 2] - P[a + 2]) + l2 * (P[c + 2] - P[a + 2]);
      (cols[iy * nx + ix] ||= []).push(z);
    }
  }
  const inside = new Uint8Array(nx * ny * nz), G = (x, y, z) => (z * ny + y) * nx + x;
  for (let iy = 0; iy < ny; iy++) for (let ix = 0; ix < nx; ix++) {
    const zs = cols[iy * nx + ix]; if (!zs) continue; zs.sort((p, q) => p - q);
    if (zs.length & 1) zs.unshift(mn[2] - 1e-3); // модель открыта снизу (срез по столу) — закрываем дно плоскостью
    let k = 0; for (let iz = 0; iz < nz; iz++) { const Z = oz + iz * cs; while (k < zs.length && zs[k] < Z) k++; if (k & 1) inside[G(ix, iy, iz)] = 1; }
  }
  // 2) surface nets: вершина в каждой ячейке со сменой знака — среднее середин «пересечённых» рёбер ячейки
  const cellV = new Int32Array((nx - 1) * (ny - 1) * (nz - 1)).fill(-1), C = (x, y, z) => (z * (ny - 1) + y) * (nx - 1) + x;
  const pos = [];
  const E = [[0, 0, 0, 1, 0, 0], [0, 1, 0, 1, 1, 0], [0, 0, 1, 1, 0, 1], [0, 1, 1, 1, 1, 1], [0, 0, 0, 0, 1, 0], [1, 0, 0, 1, 1, 0], [0, 0, 1, 0, 1, 1], [1, 0, 1, 1, 1, 1], [0, 0, 0, 0, 0, 1], [1, 0, 0, 1, 0, 1], [0, 1, 0, 0, 1, 1], [1, 1, 0, 1, 1, 1]];
  for (let z = 0; z < nz - 1; z++) for (let y = 0; y < ny - 1; y++) for (let x = 0; x < nx - 1; x++) {
    let sx = 0, sy = 0, sz = 0, n = 0;
    for (const e of E) { const a = inside[G(x + e[0], y + e[1], z + e[2])], b = inside[G(x + e[3], y + e[4], z + e[5])]; if (a !== b) { sx += (e[0] + e[3]) / 2; sy += (e[1] + e[4]) / 2; sz += (e[2] + e[5]) / 2; n++; } }
    if (!n) continue;
    cellV[C(x, y, z)] = pos.length / 3; pos.push(ox + (x + sx / n) * cs, oy + (y + sy / n) * cs, oz + (z + sz / n) * cs);
  }
  // четырёхугольник на каждое ребро решётки со сменой знака (вокруг ребра — 4 ячейки); обход — наружу
  const quads = [];
  const emit = (a, b, c, d, flip) => { if (a < 0 || b < 0 || c < 0 || d < 0) return; if (flip) quads.push(a, d, c, b); else quads.push(a, b, c, d); };
  for (let z = 1; z < nz - 1; z++) for (let y = 1; y < ny - 1; y++) for (let x = 0; x < nx - 1; x++) { const s0 = inside[G(x, y, z)]; if (s0 === inside[G(x + 1, y, z)]) continue;
    emit(cellV[C(x, y - 1, z - 1)], cellV[C(x, y, z - 1)], cellV[C(x, y, z)], cellV[C(x, y - 1, z)], !s0); }
  for (let z = 1; z < nz - 1; z++) for (let y = 0; y < ny - 1; y++) for (let x = 1; x < nx - 1; x++) { const s0 = inside[G(x, y, z)]; if (s0 === inside[G(x, y + 1, z)]) continue;
    emit(cellV[C(x - 1, y, z - 1)], cellV[C(x - 1, y, z)], cellV[C(x, y, z)], cellV[C(x, y, z - 1)], !s0); }
  for (let z = 0; z < nz - 1; z++) for (let y = 1; y < ny - 1; y++) for (let x = 1; x < nx - 1; x++) { const s0 = inside[G(x, y, z)]; if (s0 === inside[G(x, y, z + 1)]) continue;
    emit(cellV[C(x - 1, y - 1, z)], cellV[C(x, y - 1, z)], cellV[C(x, y, z)], cellV[C(x - 1, y, z)], !s0); }
  const nv = pos.length / 3, V = new Float32Array(pos);
  // 3) соседи по квадам; расслабление с проекцией на исходную поверхность (ближайшая точка треугольника)
  const nb = Array.from({ length: nv }, () => new Set());
  for (let q = 0; q < quads.length; q += 4) for (let k = 0; k < 4; k++) { const a = quads[q + k], b = quads[q + ((k + 1) & 3)]; nb[a].add(b); nb[b].add(a); }
  const hc = cs, hash = new Map(), key = (x, y, z) => (x * 73856093) ^ (y * 19349663) ^ (z * 83492791);
  for (let t = 0; t < nt; t++) { const a = I[t * 3] * 3, b = I[t * 3 + 1] * 3, c = I[t * 3 + 2] * 3;
    const lo = [0, 1, 2].map((d) => Math.floor((Math.min(P[a + d], P[b + d], P[c + d])) / hc)), hi = [0, 1, 2].map((d) => Math.floor((Math.max(P[a + d], P[b + d], P[c + d])) / hc));
    for (let x = lo[0]; x <= hi[0]; x++) for (let y = lo[1]; y <= hi[1]; y++) for (let z = lo[2]; z <= hi[2]; z++) { const k = key(x, y, z); let l = hash.get(k); if (!l) hash.set(k, l = []); l.push(t); } }
  const near = { t: -1, u: 0, v: 0, d: Infinity };
  const project = (px, py, pz, out) => {
    const cx = Math.floor(px / hc), cy = Math.floor(py / hc), cz = Math.floor(pz / hc); near.d = Infinity; near.t = -1;
    for (let r = 1; r <= 2 && near.t < 0; r++) for (let x = cx - r; x <= cx + r; x++) for (let y = cy - r; y <= cy + r; y++) for (let z = cz - r; z <= cz + r; z++) {
      const l = hash.get(key(x, y, z)); if (!l) continue;
      for (const t of l) closestOnTri(P, I, t, px, py, pz, near);
    }
    if (near.t < 0) { out[0] = px; out[1] = py; out[2] = pz; return false; }
    const a = I[near.t * 3] * 3, b = I[near.t * 3 + 1] * 3, c = I[near.t * 3 + 2] * 3, w = 1 - near.u - near.v;
    for (let d = 0; d < 3; d++) out[d] = w * P[a + d] + near.u * P[b + d] + near.v * P[c + d];
    return true;
  };
  const tmp = [0, 0, 0], it = opt.relax ?? 6;
  for (let v = 0; v < nv; v++) { project(V[v * 3], V[v * 3 + 1], V[v * 3 + 2], tmp); V[v * 3] = tmp[0]; V[v * 3 + 1] = tmp[1]; V[v * 3 + 2] = tmp[2]; }
  for (let k = 0; k < it; k++) {
    const W = V.slice();
    for (let v = 0; v < nv; v++) { if (!nb[v].size) continue; let sx = 0, sy = 0, sz = 0; for (const u of nb[v]) { sx += W[u * 3]; sy += W[u * 3 + 1]; sz += W[u * 3 + 2]; } const n = nb[v].size;
      project(0.5 * W[v * 3] + 0.5 * sx / n, 0.5 * W[v * 3 + 1] + 0.5 * sy / n, 0.5 * W[v * 3 + 2] + 0.5 * sz / n, tmp); V[v * 3] = tmp[0]; V[v * 3 + 1] = tmp[1]; V[v * 3 + 2] = tmp[2]; }
  }
  // цвет — из ближайшей точки исходной поверхности; нормали — по квадам
  const col = new Uint8Array(nv * 3), nrm = new Float32Array(nv * 3);
  for (let v = 0; v < nv; v++) { if (!project(V[v * 3], V[v * 3 + 1], V[v * 3 + 2], tmp) || !M.col) { col[v * 3] = col[v * 3 + 1] = col[v * 3 + 2] = 200; continue; }
    const a = I[near.t * 3] * 3, b = I[near.t * 3 + 1] * 3, c = I[near.t * 3 + 2] * 3, w = 1 - near.u - near.v;
    for (let d = 0; d < 3; d++) col[v * 3 + d] = Math.round(w * M.col[a + d] + near.u * M.col[b + d] + near.v * M.col[c + d]); }
  for (let q = 0; q < quads.length; q += 4) { const a = quads[q] * 3, b = quads[q + 1] * 3, c = quads[q + 2] * 3, d = quads[q + 3] * 3;
    const ux = V[c] - V[a], uy = V[c + 1] - V[a + 1], uz = V[c + 2] - V[a + 2], wx = V[d] - V[b], wy = V[d + 1] - V[b + 1], wz = V[d + 2] - V[b + 2];
    const n = [uy * wz - uz * wy, uz * wx - ux * wz, ux * wy - uy * wx]; for (const i of [a, b, c, d]) { nrm[i] += n[0]; nrm[i + 1] += n[1]; nrm[i + 2] += n[2]; } }
  for (let v = 0; v < nv; v++) { const l = Math.hypot(nrm[v * 3], nrm[v * 3 + 1], nrm[v * 3 + 2]) || 1; nrm[v * 3] /= l; nrm[v * 3 + 1] /= l; nrm[v * 3 + 2] /= l; }
  return { pos: V, nrm, col, quads: new Uint32Array(quads), cell: cs };
}

// ближайшая точка треугольника t к p (Эриксон, «Real-Time Collision Detection»); обновляет near, если ближе
function closestOnTri(P, I, t, px, py, pz, near) {
  const a = I[t * 3] * 3, b = I[t * 3 + 1] * 3, c = I[t * 3 + 2] * 3;
  const abx = P[b] - P[a], aby = P[b + 1] - P[a + 1], abz = P[b + 2] - P[a + 2], acx = P[c] - P[a], acy = P[c + 1] - P[a + 1], acz = P[c + 2] - P[a + 2];
  const apx = px - P[a], apy = py - P[a + 1], apz = pz - P[a + 2];
  const d1 = abx * apx + aby * apy + abz * apz, d2 = acx * apx + acy * apy + acz * apz;
  let u, v;
  if (d1 <= 0 && d2 <= 0) { u = 0; v = 0; }
  else {
    const bpx = px - P[b], bpy = py - P[b + 1], bpz = pz - P[b + 2], d3 = abx * bpx + aby * bpy + abz * bpz, d4 = acx * bpx + acy * bpy + acz * bpz;
    const cpx = px - P[c], cpy = py - P[c + 1], cpz = pz - P[c + 2], d5 = abx * cpx + aby * cpy + abz * cpz, d6 = acx * cpx + acy * cpy + acz * cpz;
    const vc = d1 * d4 - d3 * d2, vb = d5 * d2 - d1 * d6, va = d3 * d6 - d5 * d4;
    if (d3 >= 0 && d4 <= d3) { u = 1; v = 0; }
    else if (d6 >= 0 && d5 <= d6) { u = 0; v = 1; }
    else if (vc <= 0 && d1 >= 0 && d3 <= 0) { u = d1 / (d1 - d3); v = 0; }
    else if (vb <= 0 && d2 >= 0 && d6 <= 0) { u = 0; v = d2 / (d2 - d6); }
    else if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) { const w = (d4 - d3) / ((d4 - d3) + (d5 - d6)); u = 1 - w; v = w; }
    else { const den = 1 / (va + vb + vc); u = vb * den; v = vc * den; }
  }
  const qx = P[a] + u * abx + v * acx - px, qy = P[a + 1] + u * aby + v * acy - py, qz = P[a + 2] + u * abz + v * acz - pz, d = qx * qx + qy * qy + qz * qz;
  if (d < near.d) { near.d = d; near.t = t; near.u = u; near.v = v; }
}

// OBJ из четырёхугольников (метры, Y вверх — как остальной экспорт)
export function toQuadOBJ(Q) {
  const nv = Q.pos.length / 3, L = ['# Объём — квадратная сетка (ретопология). Метры, Y вверх. Цвет вершин после координат.', `# квадратов ${Q.quads.length / 4}, шаг ~${Q.cell.toFixed(1)} мм`];
  for (let v = 0; v < nv; v++) L.push(`v ${(Q.pos[v * 3] / 1000).toFixed(5)} ${(Q.pos[v * 3 + 2] / 1000).toFixed(5)} ${(-Q.pos[v * 3 + 1] / 1000).toFixed(5)} ${(Q.col[v * 3] / 255).toFixed(3)} ${(Q.col[v * 3 + 1] / 255).toFixed(3)} ${(Q.col[v * 3 + 2] / 255).toFixed(3)}`);
  for (let v = 0; v < nv; v++) L.push(`vn ${Q.nrm[v * 3].toFixed(3)} ${Q.nrm[v * 3 + 2].toFixed(3)} ${(-Q.nrm[v * 3 + 1]).toFixed(3)}`);
  for (let q = 0; q < Q.quads.length; q += 4) { const f = [0, 1, 2, 3].map((k) => Q.quads[q + k] + 1); L.push('f ' + f.map((i) => `${i}//${i}`).join(' ')); }
  return new TextEncoder().encode(L.join('\n') + '\n');
}
