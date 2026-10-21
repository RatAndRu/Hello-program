// Объём — экспорт сетки в стандартные форматы. Внутри всё в миллиметрах, Z вверх.
// GLB / OBJ: метры, Y вверх (так ждут Blender, Godot, Unity, three.js).
// PLY: метры, Z вверх. STL: миллиметры, Z вверх (так ждут слайсеры 3D-принтеров).

const yUp = (x, y, z) => [x, z, -y];

export function toGLB(M, name = 'Объём') {
  const nv = M.pos.length / 3, nt = M.idx.length / 3;
  const pos = new Float32Array(nv * 3), nrm = new Float32Array(nv * 3), col = new Uint8Array(nv * 4);
  const mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
  for (let v = 0; v < nv; v++) {
    const p = yUp(M.pos[v * 3] / 1000, M.pos[v * 3 + 1] / 1000, M.pos[v * 3 + 2] / 1000);
    let n = yUp(M.nrm[v * 3], M.nrm[v * 3 + 1], M.nrm[v * 3 + 2]); const nl = Math.hypot(...n);
    n = nl > 1e-6 ? n.map((x) => x / nl) : [0, 1, 0];
    for (let c = 0; c < 3; c++) { pos[v * 3 + c] = p[c]; nrm[v * 3 + c] = n[c]; mn[c] = Math.min(mn[c], p[c]); mx[c] = Math.max(mx[c], p[c]); }
    col[v * 4] = M.col[v * 3]; col[v * 4 + 1] = M.col[v * 3 + 1]; col[v * 4 + 2] = M.col[v * 3 + 2]; col[v * 4 + 3] = 255;
  }
  const idx = new Uint32Array(M.idx);
  const pad4 = (n) => (n + 3) & ~3;
  const tex = M.uv && M.tex && M.tex.jpg ? M.tex : null; // с текстурой цвет вершин не пишем (glTF перемножил бы их)
  const views = tex ? [pos, nrm, new Float32Array(M.uv), idx, tex.jpg] : [pos, nrm, col, idx];
  let off = 0; const bufferViews = [], parts = [];
  for (const [i, a] of views.entries()) {
    const bytes = new Uint8Array(a.buffer, a.byteOffset, a.byteLength);
    const bv = { buffer: 0, byteOffset: off, byteLength: bytes.length }; if (i < 4) bv.target = i === 3 ? 34963 : 34962;
    bufferViews.push(bv);
    parts.push(bytes); off += pad4(bytes.length);
  }
  const json = {
    asset: { version: '2.0', generator: 'Объём — сканер без нейросетей' },
    scene: 0, scenes: [{ nodes: [0] }], nodes: [{ mesh: 0, name }],
    materials: [{ name: 'scan', pbrMetallicRoughness: { baseColorFactor: [1, 1, 1, 1], metallicFactor: 0, roughnessFactor: 0.85, ...(tex ? { baseColorTexture: { index: 0 } } : {}) }, doubleSided: false }],
    meshes: [{ name, primitives: [{ attributes: tex ? { POSITION: 0, NORMAL: 1, TEXCOORD_0: 2 } : { POSITION: 0, NORMAL: 1, COLOR_0: 2 }, indices: 3, material: 0, mode: 4 }] }],
    ...(tex ? { images: [{ bufferView: 4, mimeType: 'image/jpeg' }], samplers: [{ magFilter: 9729, minFilter: 9987, wrapS: 33071, wrapT: 33071 }], textures: [{ source: 0, sampler: 0 }] } : {}),
    buffers: [{ byteLength: off }], bufferViews,
    accessors: [
      { bufferView: 0, componentType: 5126, count: nv, type: 'VEC3', min: mn, max: mx },
      { bufferView: 1, componentType: 5126, count: nv, type: 'VEC3' },
      tex ? { bufferView: 2, componentType: 5126, count: nv, type: 'VEC2' } : { bufferView: 2, componentType: 5121, normalized: true, count: nv, type: 'VEC4' },
      { bufferView: 3, componentType: 5125, count: nt * 3, type: 'SCALAR' },
    ],
  };
  let js = new TextEncoder().encode(JSON.stringify(json));
  const jl = pad4(js.length), total = 12 + 8 + jl + 8 + off;
  const out = new Uint8Array(total), dv = new DataView(out.buffer);
  dv.setUint32(0, 0x46546C67, true); dv.setUint32(4, 2, true); dv.setUint32(8, total, true);
  dv.setUint32(12, jl, true); dv.setUint32(16, 0x4E4F534A, true); out.set(js, 20); for (let i = js.length; i < jl; i++) out[20 + i] = 0x20;
  let o = 20 + jl; dv.setUint32(o, off, true); dv.setUint32(o + 4, 0x004E4942, true); o += 8;
  let p = 0; for (const b of parts) { out.set(b, o + p); p += pad4(b.length); }
  return out;
}

// OBJ: с текстурой — {obj, mtl, jpg} (три файла рядом), без — {obj}
export function toOBJ(M, base = 'scan') {
  const tex = M.uv && M.tex && M.tex.jpg ? M.tex : null;
  const nv = M.pos.length / 3, L = ['# Объём — 3D-сканер. Единицы: метры, Y вверх. Цвет вершин после координат (r g b 0..1).'];
  if (tex) L.push(`mtllib ${base}.mtl`);
  for (let v = 0; v < nv; v++) {
    const p = yUp(M.pos[v * 3] / 1000, M.pos[v * 3 + 1] / 1000, M.pos[v * 3 + 2] / 1000);
    L.push(`v ${p[0].toFixed(5)} ${p[1].toFixed(5)} ${p[2].toFixed(5)} ${(M.col[v * 3] / 255).toFixed(3)} ${(M.col[v * 3 + 1] / 255).toFixed(3)} ${(M.col[v * 3 + 2] / 255).toFixed(3)}`);
  }
  for (let v = 0; v < nv; v++) { const n = yUp(M.nrm[v * 3], M.nrm[v * 3 + 1], M.nrm[v * 3 + 2]); L.push(`vn ${n[0].toFixed(3)} ${n[1].toFixed(3)} ${n[2].toFixed(3)}`); }
  if (tex) { for (let v = 0; v < nv; v++) L.push(`vt ${M.uv[v * 2].toFixed(5)} ${(1 - M.uv[v * 2 + 1]).toFixed(5)}`); L.push('usemtl scan'); }
  for (let i = 0; i < M.idx.length; i += 3) { const a = M.idx[i] + 1, b = M.idx[i + 1] + 1, c = M.idx[i + 2] + 1; L.push(tex ? `f ${a}/${a}/${a} ${b}/${b}/${b} ${c}/${c}/${c}` : `f ${a}//${a} ${b}//${b} ${c}//${c}`); }
  const enc = new TextEncoder(), obj = enc.encode(L.join('\n') + '\n');
  if (!tex) return { obj };
  const mtl = enc.encode(`# Объём\nnewmtl scan\nKa 1 1 1\nKd 1 1 1\nKs 0 0 0\nillum 1\nmap_Kd ${base}.jpg\n`);
  return { obj, mtl, jpg: tex.jpg };
}

export function toMeshPLY(M) {
  const nv = M.pos.length / 3, nt = M.idx.length / 3;
  const head = `ply\nformat binary_little_endian 1.0\ncomment Obyom 3D scanner, metres, Z up\nelement vertex ${nv}\nproperty float x\nproperty float y\nproperty float z\nproperty float nx\nproperty float ny\nproperty float nz\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nelement face ${nt}\nproperty list uchar int vertex_indices\nend_header\n`;
  const hb = new TextEncoder().encode(head), out = new Uint8Array(hb.length + nv * 27 + nt * 13), dv = new DataView(out.buffer);
  out.set(hb); let o = hb.length;
  for (let v = 0; v < nv; v++) {
    for (let c = 0; c < 3; c++) { dv.setFloat32(o, M.pos[v * 3 + c] / 1000, true); o += 4; }
    for (let c = 0; c < 3; c++) { dv.setFloat32(o, M.nrm[v * 3 + c], true); o += 4; }
    out[o++] = M.col[v * 3]; out[o++] = M.col[v * 3 + 1]; out[o++] = M.col[v * 3 + 2];
  }
  for (let i = 0; i < nt; i++) { out[o++] = 3; for (let c = 0; c < 3; c++) { dv.setInt32(o, M.idx[i * 3 + c], true); o += 4; } }
  return out;
}

export function toSTL(M) {
  const nt = M.idx.length / 3, out = new Uint8Array(84 + nt * 50), dv = new DataView(out.buffer);
  const title = new TextEncoder().encode('Obyom 3D scan, millimetres');
  out.set(title.subarray(0, 80)); dv.setUint32(80, nt, true);
  let o = 84; const P = M.pos;
  for (let i = 0; i < nt; i++) {
    const a = M.idx[i * 3] * 3, b = M.idx[i * 3 + 1] * 3, c = M.idx[i * 3 + 2] * 3;
    const ux = P[b] - P[a], uy = P[b + 1] - P[a + 1], uz = P[b + 2] - P[a + 2], vx = P[c] - P[a], vy = P[c + 1] - P[a + 1], vz = P[c + 2] - P[a + 2];
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx; const l = Math.hypot(nx, ny, nz) || 1;
    for (const v of [nx / l, ny / l, nz / l]) { dv.setFloat32(o, v, true); o += 4; }
    for (const q of [a, b, c]) for (let k = 0; k < 3; k++) { dv.setFloat32(o, P[q + k], true); o += 4; }
    o += 2;
  }
  return out;
}

// размеры модели (мм) — для подписи «47 × 47 × 75 мм»
export function bounds(M) {
  const mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
  for (let i = 0; i < M.pos.length; i += 3) for (let c = 0; c < 3; c++) { mn[c] = Math.min(mn[c], M.pos[i + c]); mx[c] = Math.max(mx[c], M.pos[i + c]); }
  return { mn, mx, size: [mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]] };
}
export function meshVolume(M) {
  let V = 0; const p = M.pos;
  for (let i = 0; i < M.idx.length; i += 3) {
    const a = M.idx[i] * 3, b = M.idx[i + 1] * 3, c = M.idx[i + 2] * 3;
    V += (p[a] * (p[b + 1] * p[c + 2] - p[b + 2] * p[c + 1]) - p[a + 1] * (p[b] * p[c + 2] - p[b + 2] * p[c]) + p[a + 2] * (p[b] * p[c + 1] - p[b + 1] * p[c])) / 6;
  }
  return V;
}
// упрощение для экспорта/просмотра: кластеризация вершин по сетке (быстро и надёжно)
export function decimate(M, cell) {
  const nv = M.pos.length / 3, map = new Map(), remap = new Int32Array(nv);
  const pos = [], nrm = [], col = [], cnt = [];
  for (let v = 0; v < nv; v++) {
    const k = `${Math.floor(M.pos[v * 3] / cell)},${Math.floor(M.pos[v * 3 + 1] / cell)},${Math.floor(M.pos[v * 3 + 2] / cell)}`;
    let id = map.get(k);
    if (id === undefined) { id = cnt.length; map.set(k, id); cnt.push(0); pos.push(0, 0, 0); nrm.push(0, 0, 0); col.push(0, 0, 0); }
    cnt[id]++; for (let c = 0; c < 3; c++) { pos[id * 3 + c] += M.pos[v * 3 + c]; nrm[id * 3 + c] += M.nrm[v * 3 + c]; col[id * 3 + c] += M.col[v * 3 + c]; }
    remap[v] = id;
  }
  for (let i = 0; i < cnt.length; i++) { const n = cnt[i]; for (let c = 0; c < 3; c++) { pos[i * 3 + c] /= n; col[i * 3 + c] /= n; } const l = Math.hypot(nrm[i * 3], nrm[i * 3 + 1], nrm[i * 3 + 2]) || 1; for (let c = 0; c < 3; c++) nrm[i * 3 + c] /= l; }
  const idx = [];
  for (let i = 0; i < M.idx.length; i += 3) { const a = remap[M.idx[i]], b = remap[M.idx[i + 1]], c = remap[M.idx[i + 2]]; if (a !== b && b !== c && a !== c) idx.push(a, b, c); }
  return { pos: new Float32Array(pos), nrm: new Float32Array(nrm), col: new Uint8Array(col.map(Math.round)), idx: new Uint32Array(idx) };
}
