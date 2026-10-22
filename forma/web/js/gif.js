/* GIF89a: сжатие кадров без сторонних библиотек.
 *
 * Приложению нельзя тянуть npm-пакеты в рантайме, поэтому кодировщик свой:
 * медианное разбиение палитры (не больше 256 цветов на кадр) и LZW —
 * ровно то, что требует формат GIF. Кадры приходят как RGBA-пиксели.
 */

const HIST_BITS = 5;
const HIST_SIZE = 1 << (HIST_BITS * 3);

function clamp255(v) {
  return v < 0 ? 0 : v > 255 ? 255 : v;
}

/** Гистограмма 32×32×32 и суммы настоящих цветов в каждой ячейке. */
function buildHistogram(rgba, width, height) {
  const hist = new Uint32Array(HIST_SIZE);
  const rsum = new Float64Array(HIST_SIZE);
  const gsum = new Float64Array(HIST_SIZE);
  const bsum = new Float64Array(HIST_SIZE);
  const n = width * height;
  for (let i = 0; i < n; i++) {
    const p = i * 4;
    if (rgba[p + 3] < 8) continue;
    const key = ((rgba[p] >> 3) << 10) | ((rgba[p + 1] >> 3) << 5) | (rgba[p + 2] >> 3);
    hist[key] += 1;
    rsum[key] += rgba[p];
    gsum[key] += rgba[p + 1];
    bsum[key] += rgba[p + 2];
  }
  return { hist, rsum, gsum, bsum };
}

/** Медианное разбиение: коробки с наибольшим разбросом делятся пополам. */
function medianCut(data, maxColors) {
  const { hist, rsum, gsum, bsum } = data;
  const cells = [];
  let total = 0;
  for (let key = 0; key < HIST_SIZE; key++) {
    const w = hist[key];
    if (!w) continue;
    cells.push({ r: rsum[key] / w, g: gsum[key] / w, b: bsum[key] / w, w });
    total += w;
  }
  if (!cells.length) return [{ r: 0, g: 0, b: 0 }];
  if (cells.length <= maxColors) return cells.map((c) => ({ r: c.r, g: c.g, b: c.b }));
  const stats = (list) => {
    let rmin = 255; let rmax = 0; let gmin = 255; let gmax = 0; let bmin = 255; let bmax = 0;
    list.forEach((c) => {
      rmin = Math.min(rmin, c.r); rmax = Math.max(rmax, c.r);
      gmin = Math.min(gmin, c.g); gmax = Math.max(gmax, c.g);
      bmin = Math.min(bmin, c.b); bmax = Math.max(bmax, c.b);
    });
    const dr = rmax - rmin; const dg = gmax - gmin; const db = bmax - bmin;
    const range = Math.max(dr, dg, db);
    const axis = range === dr ? 'r' : range === dg ? 'g' : 'b';
    return { range, axis };
  };
  const average = (box) => {
    let r = 0; let g = 0; let b = 0; let w = 0;
    box.cells.forEach((c) => { r += c.r * c.w; g += c.g * c.w; b += c.b * c.w; w += c.w; });
    return { r: Math.round(r / w), g: Math.round(g / w), b: Math.round(b / w) };
  };
  const boxes = [{ cells, w: total, stats: stats(cells) }];
  while (boxes.length < maxColors) {
    let best = -1; let bestScore = 0;
    for (let i = 0; i < boxes.length; i++) {
      if (boxes[i].cells.length < 2) continue;
      const score = boxes[i].stats.range * Math.log2(1 + boxes[i].w);
      if (score > bestScore) { bestScore = score; best = i; }
    }
    if (best < 0 || bestScore <= 0) break;
    const box = boxes[best];
    const axis = box.stats.axis;
    box.cells.sort((a, b) => a[axis] - b[axis]);
    const half = box.w / 2;
    let acc = 0; let cut = 0;
    for (; cut < box.cells.length - 1; cut++) {
      acc += box.cells[cut].w;
      if (acc >= half) { cut += 1; break; }
    }
    cut = Math.max(1, Math.min(box.cells.length - 1, cut));
    const left = box.cells.slice(0, cut);
    const right = box.cells.slice(cut);
    const sum = (list) => list.reduce((acc2, c) => acc2 + c.w, 0);
    boxes.splice(best, 1,
      { cells: left, w: sum(left), stats: stats(left) },
      { cells: right, w: sum(right), stats: stats(right) });
  }
  return boxes.map(average);
}

function paletteBits(count) {
  let bits = 1;
  while ((1 << bits) < count) bits += 1;
  return Math.min(8, Math.max(1, bits));
}

function buildLookup(hist, palette) {
  const lut = new Uint8Array(HIST_SIZE);
  const count = Math.max(1, palette.length);
  const colors = palette.map((c) => [clamp255(c.r), clamp255(c.g), clamp255(c.b)]);
  for (let key = 0; key < HIST_SIZE; key++) {
    if (!hist.hist[key]) continue;
    const w = hist.hist[key];
    const r = hist.rsum[key] / w;
    const g = hist.gsum[key] / w;
    const b = hist.bsum[key] / w;
    let best = 0; let bestD = Infinity;
    for (let i = 0; i < count; i++) {
      const dr = r - colors[i][0];
      const dg = g - colors[i][1];
      const db = b - colors[i][2];
      const d = dr * dr + dg * dg + db * db;
      if (d < bestD) { bestD = d; best = i; if (!d) break; }
    }
    lut[key] = best;
  }
  return lut;
}

function lzwPack(indices, minCodeSize) {
  const clearCode = 1 << minCodeSize;
  const endCode = clearCode + 1;
  let codeSize = minCodeSize + 1;
  let freeCode = endCode + 1;
  let dict = new Map();
  const out = [];
  let cur = 0; let bits = 0;
  const emit = (code) => {
    cur |= code << bits;
    bits += codeSize;
    while (bits >= 8) {
      out.push(cur & 255);
      cur >>>= 8;
      bits -= 8;
    }
  };
  emit(clearCode);
  let prefix = indices[0];
  for (let i = 1; i < indices.length; i++) {
    const k = indices[i];
    const key = prefix * 4096 + k;
    const found = dict.get(key);
    if (found !== undefined) {
      prefix = found;
      continue;
    }
    emit(prefix);
    if (freeCode < 4096) {
      dict.set(key, freeCode);
      freeCode += 1;
      if (freeCode === (1 << codeSize) + 1 && codeSize < 12) codeSize += 1;
    } else {
      emit(clearCode);
      dict = new Map();
      codeSize = minCodeSize + 1;
      freeCode = endCode + 1;
    }
    prefix = k;
  }
  emit(prefix);
  emit(endCode);
  if (bits > 0) out.push(cur & 255);
  return out;
}

function writeSubBlocks(bytes, push) {
  let i = 0;
  while (i < bytes.length) {
    const chunk = bytes.slice(i, i + 255);
    push(chunk.length);
    for (let j = 0; j < chunk.length; j++) push(chunk[j]);
    i += 255;
  }
  push(0);
}

export function encodeGif(frames, width, height, { fps = 12, maxColors = 256, loop = true } = {}) {
  const out = [];
  const push = (...b) => b.forEach((v) => out.push(v & 255));
  const pushStr = (s) => { for (let i = 0; i < s.length; i++) out.push(s.charCodeAt(i)); };
  const u16 = (v) => { out.push(v & 255); out.push((v >> 8) & 255); };

  pushStr('GIF89a');
  u16(width); u16(height);
  push(0x70, 0, 0);                 // без глобальной палитры
  if (loop) {
    push(0x21, 0xFF, 0x0B);
    pushStr('NETSCAPE2.0');
    push(0x03, 0x01, 0x00, 0x00, 0x00);
  } else {
    push(0x21, 0xFF, 0x0B);
    pushStr('NETSCAPE2.0');
    push(0x03, 0x01, 0x01, 0x00, 0x00);
  }
  const delay = Math.max(2, Math.round(100 / Math.max(1, fps)));
  for (const frame of frames) {
    const hist = buildHistogram(frame, width, height);
    const palette = medianCut(hist, maxColors);
    const bits = paletteBits(Math.max(2, palette.length));
    const size = 1 << bits;
    push(0x21, 0xF9, 0x04, 0x04);    // GCE: disposal=1, без прозрачности
    u16(delay);
    push(0x00, 0x00);
    push(0x2C);
    u16(0); u16(0); u16(width); u16(height);
    push(0x80 | (bits - 1));
    for (let i = 0; i < size; i++) {
      const c = palette[i] || { r: 0, g: 0, b: 0 };
      push(clamp255(c.r), clamp255(c.g), clamp255(c.b));
    }
    const lut = buildLookup(hist, palette);
    const indices = new Uint8Array(width * height);
    for (let i = 0; i < width * height; i++) {
      const p = i * 4;
      if (frame[p + 3] < 8) { indices[i] = 0; continue; }
      const key = ((frame[p] >> 3) << 10) | ((frame[p + 1] >> 3) << 5) | (frame[p + 2] >> 3);
      indices[i] = lut[key] < size ? lut[key] : 0;
    }
    push(Math.max(2, bits));
    const packed = lzwPack(indices, Math.max(2, bits));
    writeSubBlocks(packed, push);
  }
  push(0x3B);
  return new Uint8Array(out);
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
