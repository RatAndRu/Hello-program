// Объём — реконструкция сетки без ИИ:
// 1) маска «точно фон» на каждом кадре (коврик совпал с ожидаемым рисунком / фон совпал с пустым кадром / вне цилиндра);
// 2) вырезание объёма (visual hull): воксель удаляется, если несколько кадров видят на его месте фон;
// 3) поверхность (surface nets) → сглаживание (Таубин) → цвета вершин из кадров с учётом видимости.

// ---------- маски ----------
// frame: {w,h,rgba,K,R,t}; ctx: {layout, mr (matRaster), Rb, Hb, clean?}
// результат: Uint8Array: 0 — точно фон, 1 — неизвестно, 2 — похоже на предмет
export function computeMask(fr, ctx) {
  const { w, h, rgba, K, R, t } = fr, L = ctx.layout, mr = ctx.mr;
  const n = w * h, mask = new Uint8Array(n).fill(1);
  const C = [-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])];
  const des = new Float32Array(n).fill(-1), unk = new Uint8Array(n);
  const inCyl = new Uint8Array(n);
  const Rb = ctx.Rb, Hb = ctx.Hb;
  // v2.6: подсказка «однотонный предмет такого цвета» (sRGB 0..255). Пиксели в цилиндре, похожие на этот цвет и
  // непохожие на ожидаемый коврик → «похоже на предмет». Это срабатывает на чёрных/белых фигурках, где по узору
  // коврика предмет нельзя отделить от чёрных меток (пипетка в кадре ставит objColor).
  const objCol = ctx.objColor && ctx.objColor.length === 3 ? [ctx.objColor[0], ctx.objColor[1], ctx.objColor[2]] : null;
  const objTol = ctx.objTol ?? (objCol && (objCol[0]+objCol[1]+objCol[2])/3 < 90 ? 55 : 50);
  const cut2 = ctx.cutOnly ? (L.cutR - 1.5 * L.k) ** 2 : 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    const cx = (x + 0.5 - K.cx) / K.fx, cy = (y + 0.5 - K.cy) / K.fy;
    const dx = R[0] * cx + R[3] * cy + R[6], dy = R[1] * cx + R[4] * cy + R[7], dz = R[2] * cx + R[5] * cy + R[8];
    // пересечение луча с цилиндром x²+y² ≤ Rb², 0 ≤ z ≤ Hb
    inCyl[i] = rayCyl(C, dx, dy, dz, Rb, Hb) ? 1 : 0;
    if (dz < -1e-6) {
      const s = -C[2] / dz, X = C[0] + dx * s, Y = C[1] + dy * s;
      const u = (X + L.cu) * mr.ppm, v = (L.cv - Y) * mr.ppm;
      // вертушка / вырезанный круг: всё за кругом — «не коврик» (столик, стол)
      if (cut2 && X * X + Y * Y > cut2) continue;
      if (u >= 0 && v >= 0 && u < mr.w - 1 && v < mr.h - 1) {
        const u0 = u | 0, v0 = v | 0, fu = u - u0, fv = v - v0, j = v0 * mr.w + u0;
        des[i] = (mr.g[j] * (1 - fu) + mr.g[j + 1] * fu) * (1 - fv) + (mr.g[j + mr.w] * (1 - fu) + mr.g[j + mr.w + 1] * fu) * fv;
        unk[i] = mr.unk[j];
      }
    }
  }
  // края рисунка (в пикселях кадра) — неизвестно: там размытие и погрешность позы
  const edge = new Uint8Array(n);
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const i = y * w + x; if (des[i] < 0) continue;
    let mx = des[i], mn = des[i];
    for (const j of [i - 1, i + 1, i - w, i + w, i - w - 1, i - w + 1, i + w - 1, i + w + 1]) { const v = des[j]; if (v < 0) { mx = 999; break; } if (v > mx) mx = v; if (v < mn) mn = v; }
    if (mx - mn > 40) edge[i] = 1;
  }
  const edge2 = dilate(edge, w, h, 1);
  // яркость и цвет
  const gray = new Float32Array(n);
  for (let i = 0; i < n; i++) gray[i] = 0.299 * rgba[i * 4] + 0.587 * rgba[i * 4 + 1] + 0.114 * rgba[i * 4 + 2];
  // баланс белого бумаги: средний цвет «белых» мест рисунка
  let wr = 0, wg = 0, wb = 0, wn = 0;
  for (let i = 0; i < n; i += 3) if (des[i] > 240 && !edge2[i] && !unk[i]) { wr += rgba[i * 4]; wg += rgba[i * 4 + 1]; wb += rgba[i * 4 + 2]; wn++; }
  if (wn < 50) return { mask, stats: { ok: false } };
  const wm = (wr + wg + wb) / (3 * wn), kr = wm / (wr / wn), kg = wm / (wg / wn), kb = wm / (wb / wn);
  // «белизна» бумаги: гладкая поверхность (полином 2-й степени) по верхней огибающей белых мест рисунка;
  // тёмные выбросы (предмет, тени) отбрасываются итерациями
  const sx = 2 / w, sy = 2 / h;
  const feat = (x, y) => { const u = x * sx - 1, v = y * sy - 1; return [1, u, v, u * u, u * v, v * v]; };
  const samp = [];
  for (let y = 0; y < h; y += 2) for (let x = 0; x < w; x += 2) { const i = y * w + x; if (des[i] > 200 && !edge2[i] && !unk[i]) samp.push(x, y, gray[i] / (des[i] / 255)); }
  let coef = null, keep = new Uint8Array(samp.length / 3).fill(1);
  for (let it = 0; it < 6; it++) {
    const A = Array.from({ length: 6 }, () => new Array(6).fill(0)), bb = new Array(6).fill(0);
    for (let k = 0; k < keep.length; k++) { if (!keep[k]) continue; const f = feat(samp[k * 3], samp[k * 3 + 1]), o = samp[k * 3 + 2]; for (let a = 0; a < 6; a++) { bb[a] += f[a] * o; for (let c = 0; c < 6; c++) A[a][c] += f[a] * f[c]; } }
    for (let a = 0; a < 6; a++) A[a][a] += 1e-3;
    const c = solve6(A, bb); if (!c) break; coef = c;
    let changed = 0;
    for (let k = 0; k < keep.length; k++) { const f = feat(samp[k * 3], samp[k * 3 + 1]); let p = 0; for (let a = 0; a < 6; a++) p += f[a] * coef[a]; const kk = samp[k * 3 + 2] > p * (it < 2 ? 0.8 : 0.9) ? 1 : 0; if (kk !== keep[k]) { keep[k] = kk; changed++; } }
    if (!changed && it > 2) break;
  }
  if (!coef) return { mask, stats: { ok: false } };
  const white = (x, y) => { const f = feat(x, y); let p = 0; for (let a = 0; a < 6; a++) p += f[a] * coef[a]; return p; };
  let rho = 0.15;
  { const rs = []; for (let y = 0; y < h; y += 2) for (let x = 0; x < w; x += 2) { const i = y * w + x; if (des[i] >= 0 && des[i] < 20 && !edge2[i]) rs.push(gray[i] / white(x, y)); } if (rs.length > 30) { rs.sort((a, c) => a - c); rho = Math.min(0.5, Math.max(0.02, rs[rs.length >> 1])); } }
  // кадров фона может быть несколько (разные положения держателя) — берём тот, что лучше совпал с этим кадром
  let PL = null;
  for (const P of ctx.clean ? (Array.isArray(ctx.clean) ? ctx.clean : [ctx.clean]) : []) {
    const pm = P && P.length === n * 4 ? plateModel(rgba, P, w, h, des, inCyl, ctx.plateOpt || {}) : null;
    if (pm && (!PL || pm.agree > PL.agree)) PL = pm;
  }
  const plateBg = new Uint8Array(n);
  // локальная корреляция наблюдаемого с ожидаемым рисунком (окно 7×7): узор коврика виден и в тени
  const ncc = nccMap(gray, des, w, h, 3);
  const strong = new Uint8Array(n); // фон, подтверждённый узором коврика
  const plain = new Uint8Array(n);  // фон только по белизне (без узора) — для светлых предметов ненадёжно
  let nb = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    if (!inCyl[i]) { mask[i] = 0; continue; }
    if (ncc.sd[i] > 14 && des[i] >= 0) { // в окне есть узор
      const r = rgba[i * 4] * kr, g = rgba[i * 4 + 1] * kg, b = rgba[i * 4 + 2] * kb, m = (r + g + b) / 3;
      const chroma = (Math.max(r, g, b) - Math.min(r, g, b)) / (m + 12);
      const W0 = white(x, y), ratio = ncc.so[i] / (ncc.sd[i] * W0 / 255 + 1e-6);
      if (ncc.c[i] > 0.72 && ratio > 0.25 && ratio < 1.6 && chroma < 0.16) { mask[i] = 0; strong[i] = 1; continue; }
      if (ncc.c[i] < 0.3 && !unk[i]) { mask[i] = 2; continue; }
      if (!unk[i]) continue;
    }
    if (des[i] >= 0 && !edge2[i] && !unk[i]) {
      const W0 = white(x, y);
      if (W0 > 0) {
        const pred = W0 * (rho + (1 - rho) * des[i] / 255);
        const r = rgba[i * 4] * kr, g = rgba[i * 4 + 1] * kg, b = rgba[i * 4 + 2] * kb, m = (r + g + b) / 3;
        const chroma = (Math.max(r, g, b) - Math.min(r, g, b)) / (m + 12);
        const diff = Math.abs(gray[i] - pred);
        // v2.6: «фон по белизне» на тёмных кусочках коврика (чёрные метки и кольца, des ~0) ненадёжен —
        // тёмный однотонный предмет там выглядит так же. Считаем «фоном по белизне» только там, где коврик
        // действительно светлый (pred ≥ 70), а в тёмных метках оставляем «неизвестно»: это безопаснее — предмет
        // не вырезается, а «дыра» позже закроется закрытием и заливкой.
        const onDarkMat = pred < 70;
        if (!onDarkMat && diff < Math.max(14, 0.11 * pred) && chroma < 0.13) { mask[i] = 0; plain[i] = 1; continue; }
        if (diff > Math.max(40, 0.3 * pred) || chroma > 0.3) { mask[i] = 2; continue; }
        if (onDarkMat) { /* оставляем неизвестно */ } else continue;
      }
    }
    if (PL && des[i] < 0) { // за листом: сравнение с кадром фона (пустая вертушка, телефон неподвижен)
      const d = PL.diff(x, y);
      if (d < PL.lo) { mask[i] = PL.weak ? 3 : 0; if (!PL.weak) plateBg[i] = 1; continue; }
      if (d > PL.hi) mask[i] = 2;
    }
  }
  // Край силуэта: окно 7×7 вокруг пикселя у края захватывает предмет, и корреляция падает.
  // Пробуем сдвинутые окна (целиком по одну сторону края): если в одном из них узор совпал,
  // подбираем там яркость a·рисунок+b и проверяем сам пиксель.
  if (ctx.edgeRefine !== false) {
    const near = dilate(strong, w, h, 4);
    const S = ncc.S, sh = [-3, 0, 3];
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = y * w + x; if (mask[i] === 0 || !near[i] || des[i] < 0 || !inCyl[i]) continue;
      const r = rgba[i * 4] * kr, g = rgba[i * 4 + 1] * kg, b = rgba[i * 4 + 2] * kb, m = (r + g + b) / 3;
      if ((Math.max(r, g, b) - Math.min(r, g, b)) / (m + 12) > 0.16) continue;
      let ok = false;
      for (const oy of sh) { for (const ox of sh) {
        if (!ox && !oy) continue;
        const st = S(x + ox, y + oy, 3); if (!st || st.c < 0.8 || st.sd < 14) continue;
        const pred = st.a * des[i] + st.b;
        if (Math.abs(gray[i] - pred) < Math.max(10, 2.5 * st.rms)) { ok = true; break; }
      } if (ok) break; }
      if (ok) mask[i] = 0;
    }
  }
  // ровные места в тени: фон, если рядом проверенный по узору коврик такой же яркости
  {
    const ver = new Uint8Array(n);
    for (let i = 0; i < n; i++) if (mask[i] === 0 && inCyl[i] && des[i] > 200) ver[i] = 1;
    const W1 = w + 1, Sv = new Float64Array(W1 * (h + 1)), Sg = new Float64Array(W1 * (h + 1));
    for (let y = 0; y < h; y++) { let a = 0, b = 0; for (let x = 0; x < w; x++) { const i = y * w + x; if (ver[i]) { a++; b += gray[i]; } Sv[(y + 1) * W1 + x + 1] = Sv[y * W1 + x + 1] + a; Sg[(y + 1) * W1 + x + 1] = Sg[y * W1 + x + 1] + b; } }
    const r = 6;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = y * w + x; if (mask[i] !== 1 || des[i] < 0 || unk[i] || !inCyl[i]) continue;
      const x0 = Math.max(0, x - r), y0 = Math.max(0, y - r), x1 = Math.min(w, x + r + 1), y1 = Math.min(h, y + r + 1);
      const cnt = Sv[y1 * W1 + x1] - Sv[y0 * W1 + x1] - Sv[y1 * W1 + x0] + Sv[y0 * W1 + x0]; if (cnt < 6) continue;
      const mg = (Sg[y1 * W1 + x1] - Sg[y0 * W1 + x1] - Sg[y1 * W1 + x0] + Sg[y0 * W1 + x0]) / cnt;
      const exp = mg * (rho + (1 - rho) * des[i] / 255); // ожидаемая яркость с учётом рисунка
      const rr = rgba[i * 4] * kr, gg = rgba[i * 4 + 1] * kg, bb2 = rgba[i * 4 + 2] * kb, m = (rr + gg + bb2) / 3;
      const chroma = (Math.max(rr, gg, bb2) - Math.min(rr, gg, bb2)) / (m + 12);
      if (Math.abs(gray[i] - exp) < Math.max(10, 0.08 * exp) && chroma < 0.14) { mask[i] = 0; plain[i] = 1; }
    }
  }
  // «Фон», со всех сторон окружённый предметом, — обычно блик или отражение коврика на блестящем боку.
  // Настоящий фон связан с областью вокруг. Замкнутые пятна → «неизвестно», кроме крупных сквозных
  // отверстий, где узор коврика подтверждён корреляцией (ручка кружки и т. п.).
  if (ctx.holes !== false) {
    const lab = new Int32Array(n), st = new Int32Array(n); let sp = 0;
    const seed = (j) => { if (!lab[j] && mask[j] === 0) { lab[j] = 1; st[sp++] = j; } };
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const i = y * w + x; if (!inCyl[i] || x === 0 || y === 0 || x === w - 1 || y === h - 1) seed(i); }
    const flood = (L) => { while (sp) { const j = st[--sp], x = j % w, y = (j / w) | 0; const nbh = [x > 0 ? j - 1 : -1, x < w - 1 ? j + 1 : -1, y > 0 ? j - w : -1, y < h - 1 ? j + w : -1]; for (const q of nbh) if (q >= 0 && !lab[q] && mask[q] === 0) { lab[q] = L; st[sp++] = q; } } };
    flood(1);
    const big = Math.max(400, 0.004 * n);
    for (let i = 0; i < n; i++) {
      if (mask[i] !== 0 || lab[i]) continue;
      const L = 2 + i; lab[i] = L; st[sp++] = i;
      const members = []; let ns = 0;
      while (sp) { const j = st[--sp]; members.push(j); if (strong[j]) ns++; const x = j % w, y = (j / w) | 0; const nbh = [x > 0 ? j - 1 : -1, x < w - 1 ? j + 1 : -1, y > 0 ? j - w : -1, y < h - 1 ? j + w : -1]; for (const q of nbh) if (q >= 0 && !lab[q] && mask[q] === 0) { lab[q] = L; st[sp++] = q; } }
      if (!(members.length > big && ns > 0.5 * members.length)) for (const j of members) mask[j] = 1;
    }
  }
  // Чистка «не фона»: крапинки и волоски вокруг предмета (края крапинок коврика, шум) иначе
  // не дают вырезать воксели у поверхности — модель выходит бугристой.
  if (ctx.clean2 !== false) {
    const nbm = new Uint8Array(n); for (let i = 0; i < n; i++) nbm[i] = mask[i] ? 1 : 0;
    const op = ctx.open ?? 1;
    if (op > 0) {
      const er = erode(nbm, w, h, op), opened = dilate(er, w, h, op);
      for (let i = 0; i < n; i++) if (nbm[i] && !opened[i] && inCyl[i]) { mask[i] = 0; nbm[i] = 0; }
    }
    // островки «не фона» меньше minA пикселей → фон
    const minA = ctx.minIsland ?? Math.max(30, 0.0005 * n);
    const lab = new Uint8Array(n), st = new Int32Array(n);
    for (let i = 0; i < n; i++) {
      if (!nbm[i] || lab[i] || !inCyl[i]) continue;
      let sp = 0; st[sp++] = i; lab[i] = 1; const mem = [];
      let touchesOut = false;
      while (sp) { const j = st[--sp]; mem.push(j); if (!inCyl[j]) touchesOut = true; const x = j % w, y = (j / w) | 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const X = x + dx, Y = y + dy; if (X < 0 || Y < 0 || X >= w || Y >= h) continue; const q = Y * w + X; if (nbm[q] && !lab[q]) { lab[q] = 1; st[sp++] = q; } } }
      if (mem.length < minA && !touchesOut) for (const j of mem) mask[j] = 0;
    }
  }
  // «Неизвестные» пиксели на самой кромке силуэта, касающиеся фона, — снимаем слоями (peel):
  // ошибочно «фоновых» пикселей предмета почти не бывает, а кромка из неизвестных дрожит в такт узору.
  for (let it = 0, P = ctx.peel ?? 1; it < P; it++) {
    const rm = [];
    for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) { const i = y * w + x; if (!mask[i] || (mask[i] === 2 && !(ctx.peelAll !== false && it === 0)) || !inCyl[i]) continue; if (!mask[i - 1] || !mask[i + 1] || !mask[i - w] || !mask[i + w]) rm.push(i); }
    for (const i of rm) mask[i] = 0;
  }
  // сглаживание контура силуэта: большинство в окне (2r+1)² для «фон / не фон»
  if ((ctx.major ?? 0) > 0) {
    const r = ctx.major, W1 = w + 1, I = new Int32Array(W1 * (h + 1));
    for (let y = 0; y < h; y++) { let a = 0; for (let x = 0; x < w; x++) { if (mask[y * w + x]) a++; I[(y + 1) * W1 + x + 1] = I[y * W1 + x + 1] + a; } }
    const out = mask.slice();
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = y * w + x; if (!inCyl[i]) continue;
      const x0 = Math.max(0, x - r), y0 = Math.max(0, y - r), x1 = Math.min(w, x + r + 1), y1 = Math.min(h, y + r + 1);
      const cnt = I[y1 * W1 + x1] - I[y0 * W1 + x1] - I[y1 * W1 + x0] + I[y0 * W1 + x0], tot = (x1 - x0) * (y1 - y0);
      if (mask[i] && cnt * 2 < tot) out[i] = 0; else if (!mask[i] && cnt * 2 > tot) out[i] = 1;
    }
    mask.set(out);
  }
  // Фон «по белизне» (узор коврика в окне не проверялся) → слабый фон: светлый матовый предмет на белой бумаге
  // выглядит так же, поэтому вырезать по нему можно только большинством кадров.
  // Только рядом со светлыми, похожими на бумагу частями предмета: у цветного предмета белизна надёжна.
  if (ctx.plainWeak !== false) {
    const pl = new Uint8Array(n);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = y * w + x; if (mask[i] !== 1 && mask[i] !== 2) continue; if (des[i] < 0) continue;
      const r = rgba[i * 4] * kr, g = rgba[i * 4 + 1] * kg, b = rgba[i * 4 + 2] * kb, m = (r + g + b) / 3;
      if ((Math.max(r, g, b) - Math.min(r, g, b)) / (m + 12) < 0.13 && gray[i] > 0.6 * white(x, y)) pl[i] = 1;
    }
    const zone = dilate(pl, w, h, ctx.plainZone ?? 3);
    for (let i = 0; i < n; i++) if (plain[i] && zone[i] && mask[i] === 0 && inCyl[i]) mask[i] = 3;
  }
  // v2.7: подсказка «однотонный предмет такого цвета» — пиксели цвета предмета в цилиндре, не совпадающие с ковриком, считаем предметом
  if (objCol) {
    const [or0, og0, ob0] = objCol;
    const chromaOk = 0.18;
    for (let i = 0; i < n; i++) {
      if (mask[i] === 0 || !inCyl[i]) continue;
      const R_ = rgba[i * 4], G_ = rgba[i * 4 + 1], B_ = rgba[i * 4 + 2], m = (R_ + G_ + B_) / 3;
      const dr = R_ - or0, dg = G_ - og0, db = B_ - ob0;
      const dd = Math.sqrt(dr * dr + dg * dg + db * db);
      const ch = (Math.max(R_, G_, B_) - Math.min(R_, G_, B_)) / (m + 12);
      const pred = white(i % w, (i / w) | 0) * (rho + (1 - rho) * des[i] / 255);
      const matDiff = des[i] >= 0 ? Math.abs(gray[i] - pred) : 0;
      // на коврике разница с ожидаемым должна быть заметна (иначе чёрные метки под чёрный предмет примем за него)
      if (dd < objTol && ch < chromaOk && (des[i] < 0 || matDiff > 18)) mask[i] = 2;
    }
  }
  // За листом (стол, стена): «слабый фон» (3) заливкой от области заведомо вне цилиндра — по плавности цвета
  // и по совпадению с цветами этого фона. Слабый фон вырезает воксель, только если так считает большинство кадров:
  // если заливка затекла в предмет похожего цвета в отдельных кадрах, предмет не режется.
  if (ctx.offMat !== false) {
    const hist = new Uint32Array(4096); let seeds = 0;
    const bl = blur3rgb(rgba, w, h);
    const q = (j) => ((bl[j * 3] >> 4) << 8) | ((bl[j * 3 + 1] >> 4) << 4) | (bl[j * 3 + 2] >> 4);
    for (let i = 0; i < n; i++) if (!inCyl[i] && des[i] < 0) { hist[q(i)]++; seeds++; }
    if (seeds > 200) {
      const thr = Math.max(3, seeds * 0.0004);
      const okc = (j) => { const c = q(j), R0 = c >> 8, G0 = (c >> 4) & 15, B0 = c & 15; let s2 = 0;
        for (let dr = -1; dr <= 1; dr++) for (let dg = -1; dg <= 1; dg++) for (let db = -1; db <= 1; db++) { const R1 = R0 + dr, G1 = G0 + dg, B1 = B0 + db; if (R1 < 0 || G1 < 0 || B1 < 0 || R1 > 15 || G1 > 15 || B1 > 15) continue; s2 += hist[(R1 << 8) | (G1 << 4) | B1]; }
        return s2 >= thr; };
      const vis = new Uint8Array(n), st = new Int32Array(n); let sp = 0;
      // v2.5: затравка — весь фон за листом, не только вне рамки: «чистка кромки» (peel) оставляет по краю рамки кольцо
      // фона в 1 пиксель, и заливка от «вне рамки» через него не проходила — «слабого фона» внутри рамки не было вовсе
      for (let i = 0; i < n; i++) if (des[i] < 0 && (!inCyl[i] || mask[i] === 0)) { vis[i] = 1; st[sp++] = i; }
      const step = ctx.offMatStep ?? 10;
      // перепад яркости (Собель) без размытия: заливка не переходит даже через слабый край
      const gr = (k) => { const x = k % w, y = (k / w) | 0; if (x < 1 || y < 1 || x >= w - 1 || y >= h - 1) return 0;
        const gx = gray[k - w + 1] + 2 * gray[k + 1] + gray[k + w + 1] - gray[k - w - 1] - 2 * gray[k - 1] - gray[k + w - 1];
        const gy = gray[k + w - 1] + 2 * gray[k + w] + gray[k + w + 1] - gray[k - w - 1] - 2 * gray[k - w] - gray[k - w + 1];
        return Math.abs(gx) + Math.abs(gy); };
      const gmax = ctx.offMatGrad ?? 40;
      while (sp) {
        const j = st[--sp], x = j % w, y = (j / w) | 0;
        const nb4 = [x > 0 ? j - 1 : -1, x < w - 1 ? j + 1 : -1, y > 0 ? j - w : -1, y < h - 1 ? j + w : -1];
        for (const k of nb4) {
          if (k < 0 || vis[k] || des[k] >= 0 || mask[k] === 0) continue;
          const d = Math.abs(bl[k * 3] - bl[j * 3]) + Math.abs(bl[k * 3 + 1] - bl[j * 3 + 1]) + Math.abs(bl[k * 3 + 2] - bl[j * 3 + 2]);
          if (d > step || gr(k) > gmax || !okc(k)) continue;
          vis[k] = 1; mask[k] = 3; st[sp++] = k;
        }
      }
      // v2.5: и без заливки — по цвету: цвет частый у фона этого кадра (вне рамки) и редкий у предмета (на листе, «точно предмет»).
      // Узорчатый стол заливка не проходит (перепады яркости), а по цвету он узнаётся. Режет только большинством кадров (слабый фон).
      if (ctx.colorWeak !== false) {
        const ho = new Uint32Array(4096); let no = 0;
        for (let i = 0; i < n; i++) if (mask[i] === 2 && des[i] >= 0) { ho[q(i)]++; no++; }
        if (no > 150) {
          const nbh = (H, c) => { const R0 = c >> 8, G0 = (c >> 4) & 15, B0 = c & 15; let s2 = 0; for (let dr = -1; dr <= 1; dr++) for (let dg = -1; dg <= 1; dg++) for (let db = -1; db <= 1; db++) { const R1 = R0 + dr, G1 = G0 + dg, B1 = B0 + db; if (R1 < 0 || G1 < 0 || B1 < 0 || R1 > 15 || G1 > 15 || B1 > 15) continue; s2 += H[(R1 << 8) | (G1 << 4) | B1]; } return s2; };
          const cache = new Int8Array(4096).fill(-1);
          for (let i = 0; i < n; i++) {
            if (mask[i] !== 1 || des[i] >= 0 || !inCyl[i]) continue;
            const c = q(i); let v = cache[c];
            if (v < 0) { const pb = nbh(hist, c) / seeds, po = nbh(ho, c) / no; v = cache[c] = pb > 0.002 && pb > 10 * po ? 1 : 0; }
            if (v) mask[i] = 3;
          }
        }
      }
      // отступ 2 пикселя от «не фона»: у самого края предмета слабым фоном не считаем
      const nb2 = new Uint8Array(n); for (let q = 0; q < n; q++) nb2[q] = mask[q] === 1 || mask[q] === 2 ? 1 : 0;
      const near2 = dilate(nb2, w, h, 2);
      for (let q = 0; q < n; q++) if (mask[q] === 3 && near2[q]) mask[q] = 1;
    }
  }
  // «Предмет целиком на листе»: если силуэт со всех сторон окружён фоном коврика, за краем листа предмета быть
  // не может — тогда всё за листом в этом кадре (стол, стена) — фон, и по нему вырезается пространство над предметом
  // («шапка»). Проверка: заливка от «за листом» по всему, что не подтверждённый фон (0). Если она заходит на лист
  // дальше узкой кромки у края — что-то (предмет, в т. ч. неуверенно распознанный белый) тянется с листа за край:
  // высокий предмет под низким углом. Такой кадр не трогаем, иначе срежется настоящий верх.
  let enclosed = false;
  if (ctx.enclose) {
    const off = new Uint8Array(n); let offN = 0;
    for (let i = 0; i < n; i++) if (inCyl[i] && des[i] < 0) { off[i] = 1; offN++; }
    if (offN > 0) {
      const band = dilate(off, w, h, ctx.encBand ?? 6);
      const vis = new Uint8Array(n), st = new Int32Array(n); let sp = 0, touch = 0;
      const tmax = ctx.encTol ?? 15;
      for (let i = 0; i < n; i++) if (off[i] && mask[i] !== 0) { vis[i] = 1; st[sp++] = i; }
      while (sp && touch <= tmax) {
        const j = st[--sp], x = j % w, y = (j / w) | 0;
        if (des[j] >= 0 && !band[j]) touch++;
        const nb4 = [x > 0 ? j - 1 : -1, x < w - 1 ? j + 1 : -1, y > 0 ? j - w : -1, y < h - 1 ? j + w : -1];
        for (const k of nb4) if (k >= 0 && !vis[k] && mask[k] !== 0) { vis[k] = 1; st[sp++] = k; }
      }
      if (touch <= tmax) { enclosed = true; for (let i = 0; i < n; i++) if (off[i]) mask[i] = 0; }
    }
  }
  // осторожность у границ: фон рядом с «не фоном» — в неизвестное
  const notBg = new Uint8Array(n); for (let i = 0; i < n; i++) notBg[i] = mask[i] === 1 || mask[i] === 2 ? 1 : 0;
  const grown = dilate(notBg, w, h, 1);
  for (let i = 0; i < n; i++) { if (ctx.grow && !mask[i] && grown[i] && inCyl[i]) mask[i] = 1; if (!mask[i]) nb++; }
  // 4 — «нет сведений»: за листом, ничем не подтверждено (ни фоном, ни отличием от кадра фона).
  // Такие кадры не считаются «видевшими» воксель: иначе они раздувают порог доли и над предметом остаётся шапка.
  if (ctx.mark4) for (let i = 0; i < n; i++) if (mask[i] === 1 && des[i] < 0 && inCyl[i]) mask[i] = 4;
  // заведомый фон для проверки «камера не сдвинулась» (улики «движения» на вертушке): за листом и вне рамки, через 3 пикс.
  let refOut = null;
  // Лист крутится вместе со столиком — его углы заметают круг радиусом в полудиагональ листа: эти точки не берём.
  if (ctx.refOut) {
    const r = [], sw2 = (0.5 * Math.hypot(210, 297) * L.k * 1.08) ** 2;
    for (let y = 2; y < h - 2; y += 3) for (let x = 2; x < w - 2; x += 3) {
      const i = y * w + x; if (des[i] >= 0 || inCyl[i]) continue;
      const cx = (x + 0.5 - K.cx) / K.fx, cy = (y + 0.5 - K.cy) / K.fy;
      const dx = R[0] * cx + R[3] * cy + R[6], dy = R[1] * cx + R[4] * cy + R[7], dz = R[2] * cx + R[5] * cy + R[8];
      if (dz < -1e-6) { const s = -C[2] / dz, X = C[0] + dx * s, Y = C[1] + dy * s; if (X * X + Y * Y < sw2) continue; }
      r.push(i);
    }
    refOut = Int32Array.from(r);
  }
  return { mask, refOut, stats: { ok: true, rho, bgFrac: nb / n, enclosed, plate: PL ? { shift: PL.shift, agree: PL.agree } : null } };
}
// Кадр фона (clean plate): телефон в держателе неподвижен, всё за листом (стол, стена) от кадра к кадру не меняется,
// а предмет на вертушке закрывает часть этого фона. Пиксель за листом, совпавший с фоном, — «здесь пусто»:
// так вырезается пространство над предметом, которое на фоне самого листа не видно («шапка гриба»).
// Подбираются сдвиг (держатель мог чуть сместиться) и усиление по каналам (автоэкспозиция).
function plateModel(rgba, P, w, h, des, inCyl, o) {
  const n = w * h, A = blur3rgb(rgba, w, h), B = blur3rgb(P, w, h);
  const ref = []; // заведомый фон: за листом и вне цилиндра рамки
  for (let y = 4; y < h - 4; y += 2) for (let x = 4; x < w - 4; x += 2) { const i = y * w + x; if (des[i] < 0 && !inCyl[i]) ref.push(i); }
  if (ref.length < 300) return null;
  const S = Math.max(1, Math.floor(ref.length / 4000));
  let best = null;
  for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
    let e = 0, c = 0;
    for (let k = 0; k < ref.length; k += S * 3) { const i = ref[k], j = i + dy * w + dx; e += Math.abs(A[i * 3] - B[j * 3]) + Math.abs(A[i * 3 + 1] - B[j * 3 + 1]) + Math.abs(A[i * 3 + 2] - B[j * 3 + 2]); c++; }
    e /= c; if (!best || e < best.e) best = { e, dx, dy };
  }
  const off = best.dy * w + best.dx;
  const g = [0, 1, 2].map((ch) => { const r = []; for (let k = 0; k < ref.length; k += S) { const i = ref[k], b = B[(i + off) * 3 + ch]; if (b > 20) r.push(A[i * 3 + ch] / b); } r.sort((a, c) => a - c); return r.length ? r[r.length >> 1] : 1; });
  if (g.some((v) => v < 0.5 || v > 2)) return null;
  // шум: разброс разницы на заведомом фоне
  const ds = [];
  const diff = (x, y) => { const xx = Math.min(w - 1, Math.max(0, x + best.dx)), yy = Math.min(h - 1, Math.max(0, y + best.dy)), i = (y * w + x) * 3, j = (yy * w + xx) * 3;
    return Math.abs(A[i] - g[0] * B[j]) + Math.abs(A[i + 1] - g[1] * B[j + 1]) + Math.abs(A[i + 2] - g[2] * B[j + 2]); };
  for (let k = 0; k < ref.length; k += S) { const i = ref[k]; ds.push(diff(i % w, (i / w) | 0)); }
  ds.sort((a, c) => a - c);
  const med = ds[ds.length >> 1], agree = ds.filter((v) => v < Math.max(24, 3 * med)).length / ds.length;
  if (agree < (o.minAgree ?? 0.6)) return null; // телефон сдвинулся или свет сильно изменился — фон не годится
  const lo = Math.max(o.lo ?? 21, 3 * med), hi = Math.max(o.hi ?? 75, 8 * med);
  return { diff, lo, hi, weak: !!o.weak, shift: [best.dx, best.dy], gain: g, agree };
}
function nccMap(o, d, w, h, r) {
  const n = w * h, W1 = w + 1, mk = () => new Float64Array(W1 * (h + 1));
  const So = mk(), Sd = mk(), Soo = mk(), Sdd = mk(), Sod = mk(), Sn = mk();
  for (let y = 0; y < h; y++) {
    let a = 0, b = 0, c = 0, e = 0, f = 0, g = 0;
    for (let x = 0; x < w; x++) {
      const i = y * w + x, dv = d[i];
      if (dv >= 0) { const ov = o[i]; a += ov; b += dv; c += ov * ov; e += dv * dv; f += ov * dv; g++; }
      const j = (y + 1) * W1 + x + 1, k = y * W1 + x + 1;
      So[j] = So[k] + a; Sd[j] = Sd[k] + b; Soo[j] = Soo[k] + c; Sdd[j] = Sdd[k] + e; Sod[j] = Sod[k] + f; Sn[j] = Sn[k] + g;
    }
  }
  const c = new Float32Array(n), sd = new Float32Array(n), so = new Float32Array(n);
  const box = (S, x0, y0, x1, y1) => S[y1 * W1 + x1] - S[y0 * W1 + x1] - S[y1 * W1 + x0] + S[y0 * W1 + x0];
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const x0 = Math.max(0, x - r), y0 = Math.max(0, y - r), x1 = Math.min(w, x + r + 1), y1 = Math.min(h, y + r + 1);
    const N = box(Sn, x0, y0, x1, y1); if (N < 12) continue;
    const mo = box(So, x0, y0, x1, y1) / N, md = box(Sd, x0, y0, x1, y1) / N;
    const vo = Math.max(0, box(Soo, x0, y0, x1, y1) / N - mo * mo), vd = Math.max(0, box(Sdd, x0, y0, x1, y1) / N - md * md);
    const cov = box(Sod, x0, y0, x1, y1) / N - mo * md, i = y * w + x;
    sd[i] = Math.sqrt(vd); so[i] = Math.sqrt(vo);
    c[i] = vo > 1 && vd > 1 ? cov / Math.sqrt(vo * vd) : 0;
  }
  const S = (x, y, r2) => {
    if (x < 0 || y < 0 || x >= w || y >= h) return null;
    const x0 = Math.max(0, x - r2), y0 = Math.max(0, y - r2), x1 = Math.min(w, x + r2 + 1), y1 = Math.min(h, y + r2 + 1);
    const N = box(Sn, x0, y0, x1, y1); if (N < 20) return null;
    const mo = box(So, x0, y0, x1, y1) / N, md = box(Sd, x0, y0, x1, y1) / N;
    const vo = Math.max(0, box(Soo, x0, y0, x1, y1) / N - mo * mo), vd = Math.max(0, box(Sdd, x0, y0, x1, y1) / N - md * md);
    if (vo < 1 || vd < 1) return null;
    const cov = box(Sod, x0, y0, x1, y1) / N - mo * md, cc = cov / Math.sqrt(vo * vd), a = cov / vd;
    return { c: cc, a, b: mo - a * md, sd: Math.sqrt(vd), rms: Math.sqrt(Math.max(0, vo * (1 - cc * cc))) };
  };
  return { c, sd, so, S };
}
function blur3rgb(rgba, w, h) {
  const o = new Uint8Array(w * h * 3);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let r = 0, g = 0, b = 0, k = 0;
    for (let yy = Math.max(0, y - 1); yy <= Math.min(h - 1, y + 1); yy++) for (let xx = Math.max(0, x - 1); xx <= Math.min(w - 1, x + 1); xx++) { const j = (yy * w + xx) * 4; r += rgba[j]; g += rgba[j + 1]; b += rgba[j + 2]; k++; }
    const i = (y * w + x) * 3; o[i] = r / k; o[i + 1] = g / k; o[i + 2] = b / k;
  }
  return o;
}
function rayCyl(C, dx, dy, dz, Rb, Hb) {
  // параметрический отрезок луча внутри слоя 0..Hb
  let t0 = 0, t1 = 1e9;
  if (Math.abs(dz) < 1e-9) { if (C[2] < 0 || C[2] > Hb) return false; }
  else { let a = (0 - C[2]) / dz, b = (Hb - C[2]) / dz; if (a > b) [a, b] = [b, a]; t0 = Math.max(t0, a); t1 = Math.min(t1, b); }
  if (t0 > t1) return false;
  const A = dx * dx + dy * dy, Bq = 2 * (C[0] * dx + C[1] * dy), Cq = C[0] * C[0] + C[1] * C[1] - Rb * Rb;
  if (A < 1e-12) return Cq <= 0;
  const D = Bq * Bq - 4 * A * Cq; if (D < 0) return false;
  const s = Math.sqrt(D), r0 = (-Bq - s) / (2 * A), r1 = (-Bq + s) / (2 * A);
  return Math.max(t0, r0) <= Math.min(t1, r1);
}
function erode(m, w, h, r) {
  const o = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (!m[y * w + x]) continue; let ok = 1;
    for (let yy = y - r; yy <= y + r && ok; yy++) for (let xx = x - r; xx <= x + r; xx++) { if (xx < 0 || yy < 0 || xx >= w || yy >= h || !m[yy * w + xx]) { ok = 0; break; } }
    o[y * w + x] = ok;
  }
  return o;
}
function dilate(m, w, h, r) {
  const o = new Uint8Array(m.length);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (!m[y * w + x]) continue;
    for (let yy = Math.max(0, y - r); yy <= Math.min(h - 1, y + r); yy++) for (let xx = Math.max(0, x - r); xx <= Math.min(w - 1, x + r); xx++) o[yy * w + xx] = 1;
  }
  return o;
}
function solve6(A, b) {
  const n = 6, M = A.map((r, i) => [...r, b[i]]);
  for (let c = 0; c < n; c++) { let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r; if (Math.abs(M[p][c]) < 1e-12) return null; [M[c], M[p]] = [M[p], M[c]]; for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; } }
  return M.map((r, i) => r[n] / r[i]);
}
// ---------- вырезание объёма ----------
// Решение «вырезать воксель»: фон по узору коврика (bg) — от доли frac видевших кадров;
// «слабый фон» за листом (weak) — только вместе с bg и большинством (weakMaj, по умолчанию 0.5) видевших.
export function carveVote(bg, weak, seen, frac = 0.08, few = false, weakMaj = 0.5) {
  if (seen < 3) return true;
  const need = few ? 1 : Math.max(2, Math.ceil(frac * seen));
  if (bg >= need) return true;
  return bg + weak >= need && bg + weak >= (weakMaj ?? 0.5) * seen;
}
// v2.3: субпиксельный край. Пиксели полосы «неизвестно» (1) на кромке силуэта — смесь предмета и фона. По цвету оцениваем
// долю предмета α (как в мэттинге): цвет пикселя между средним соседним фоном и средним соседним предметом.
// Если фон и предмет почти одного цвета — α не оценить, пиксель остаётся «не фон» (как раньше).
export function edgeAlpha(f, opt = {}) {
  const { w, h, mask, rgba } = f, np = w * h, al = new Uint8Array(np).fill(255), minC = opt.minContrast ?? 40, R = opt.band ?? 3;
  // «глубокий предмет»: пиксели предмета, у которых в радиусе 3 нет ничего, кроме предмета (эрозия) — их цвет чистый, без смеси
  const deep = new Uint8Array(np);
  { const rowOk = new Uint8Array(np);
    for (let y = 0; y < h; y++) { let run = 0; for (let x = 0; x < w; x++) { run = mask[y * w + x] === 2 ? run + 1 : 0; if (run >= 7) rowOk[y * w + x - 3] = 1; } }
    for (let x = 0; x < w; x++) { let run = 0; for (let y = 0; y < h; y++) { run = rowOk[y * w + x] ? run + 1 : 0; if (run >= 7) deep[(y - 3) * w + x] = 1; } } }
  const S = R + (opt.reach ?? 3);
  for (let y = S; y < h - S; y++) for (let x = S; x < w - S; x++) {
    const i = y * w + x, mi = mask[i]; if (mi !== 1 && mi !== 2) continue;
    let near = 0; for (let dy = -R; dy <= R && !near; dy++) for (let dx = -R; dx <= R; dx++) if (mask[i + dy * w + dx] === 0) { near = 1; break; }
    if (!near) continue; // не кромка
    let b0 = 0, b1 = 0, b2 = 0, cb = 0, o0 = 0, o1 = 0, o2 = 0, co = 0;
    for (let dy = -S; dy <= S; dy++) for (let dx = -S; dx <= S; dx++) {
      const j = i + dy * w + dx, m = mask[j];
      if (m === 0 && Math.abs(dx) <= R + 1 && Math.abs(dy) <= R + 1) { b0 += rgba[j * 4]; b1 += rgba[j * 4 + 1]; b2 += rgba[j * 4 + 2]; cb++; }
      else if (deep[j]) { o0 += rgba[j * 4]; o1 += rgba[j * 4 + 1]; o2 += rgba[j * 4 + 2]; co++; }
    }
    if (cb < 3 || co < 4) continue;
    b0 /= cb; b1 /= cb; b2 /= cb; o0 /= co; o1 /= co; o2 /= co;
    const d0 = o0 - b0, d1 = o1 - b1, d2 = o2 - b2, dd = d0 * d0 + d1 * d1 + d2 * d2;
    if (dd < minC * minC) continue; // фон и предмет похожи — долю не оценить
    const e0 = rgba[i * 4] - b0, e1 = rgba[i * 4 + 1] - b1, e2 = rgba[i * 4 + 2] - b2, a = (e0 * d0 + e1 * d1 + e2 * d2) / dd;
    // цвет должен лежать «между» фоном и предметом: иначе это рисунок/контур предмета, а не смесь — не трогаем
    const r0 = e0 - a * d0, r1 = e1 - a * d1, r2 = e2 - a * d2;
    if (r0 * r0 + r1 * r1 + r2 * r2 > 0.12 * dd) continue;
    al[i] = Math.max(0, Math.min(255, Math.round(a * 255)));
  }
  return al;
}
// мягкое значение «предмет» в пикселе для субпиксельной выборки: фон 0, предмет 1, кромка — α, прочее — 1 (не режет)
function softAt(f, i) { const m = f.mask[i]; return m === 0 ? 0 : (m === 1 || m === 2) && f.alpha[i] < 255 ? f.alpha[i] / 255 : m === 3 ? 0.5 : 1; }
// frames: [{w,h,K,R,t,mask}], box: {Rb,Hb}, N — вокселей по ширине
export function carveHull(frames, box, N = 128, onProgress, opt = {}) {
  const vs = 2 * box.Rb / N, nx = N, ny = N, nz = Math.max(8, Math.ceil(box.Hb / vs));
  const ox = -box.Rb + vs / 2, oy = -box.Rb + vs / 2, oz = vs / 2;
  const occ = new Float32Array(nx * ny * nz);
  const order = frames.map((_, i) => i);
  for (let i = order.length - 1; i > 0; i--) { const j = (i * 7919 + 13) % (i + 1); [order[i], order[j]] = [order[j], order[i]]; }
  const F = order.map(i => frames[i]);
  // Сколько кадров должны сказать «здесь фон», чтобы вырезать воксель. Не «любые два», а доля от видевших:
  // блики на блестящем предмете дают ложный «фон» в отдельных кадрах — они больше не прорезают дыры.
  const frac = opt.frac ?? 0.08, few = frames.length < 8, tfrac = opt.trustFrac ?? 0.1;
  const subpix = opt.subpix !== false;
  if (subpix) for (const f of F) if (f.rgba && !f.alpha) f.alpha = edgeAlpha(f, { reach: opt.alphaReach ?? 5 });
  // вес кадра по точности позы (ошибка меток rms, px): неточный кадр голосует слабее — ложные «фоны» по кромке не прорезают вмятин
  const wF = F.map((f) => { const r = f.rms ?? (f.p && f.p.rms) ?? 0.5; return opt.weighted === false ? 1 : 1 / (1 + Math.max(0, r - 1) ** 2); }); // до 1 px — полный вес
  { const m = wF.reduce((a_, b_) => a_ + b_, 0) / Math.max(1, wF.length); for (let k = 0; k < wF.length; k++) wF[k] /= m; } // средний вес 1
  const wMean = 1;
  for (let z = 0; z < nz; z++) {
    const Z = oz + z * vs;
    for (let y = 0; y < ny; y++) {
      const Y = oy + y * vs;
      for (let x = 0; x < nx; x++) {
        const X = ox + x * vs;
        if (X * X + Y * Y > box.Rb * box.Rb) continue;
        let bg = 0, weak = 0, seen = 0, left = F.length, tbg = 0, tseen = 0, nbg = 0;
        for (let k = 0; k < F.length; k++, left--) {
          const f = F[k], R = f.R, t = f.t, K = f.K;
          const cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) continue;
          const uf = K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx, vf = K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy;
          const u = uf | 0, v = vf | 0;
          if (u < 0 || v < 0 || u >= f.w || v >= f.h) continue;
          let mv = f.mask[v * f.w + u]; if (mv === 4) continue;
          // кромка: субпиксельно (билинейно по соседним пикселям) — «неизвестно» с долей предмета < ½ режет как фон
          if ((mv === 1 || mv === 2) && f.alpha && f.alpha[v * f.w + u] < 255 && u > 0 && v > 0 && u < f.w - 2 && v < f.h - 2) {
            const uu = uf - 0.5, vv = vf - 0.5, i0 = Math.floor(uu), j0 = Math.floor(vv), a = uu - i0, b = vv - j0, q = j0 * f.w + i0;
            const sv = (1 - a) * (1 - b) * softAt(f, q) + a * (1 - b) * softAt(f, q + 1) + (1 - a) * b * softAt(f, q + f.w) + a * b * softAt(f, q + f.w + 1);
            if (sv < 0.5) mv = 0;
          }
          const wk = wF[k];
          seen += wk;
          if (mv === 0) { bg += wk; nbg++; } else if (mv === 3) weak += wk;
          if (f.trusted) { tseen++; if (mv === 0) tbg++; }
          // досрочно: уже точно вырезан (даже если все оставшиеся кадры увидят точку)
          if (!few && nbg >= 2 && bg >= frac * (seen + left - 1)) break;
        }
        const need = few ? 1 : Math.max(2, Math.ceil(frac * seen));
        // «Доверенные» кадры (предмет целиком на листе, силуэт замкнут фоном коврика) голосуют ещё и между собой:
        // их «фон» не перевешивается «неизвестно» из низких ракурсов (тень, край листа) — так срезается шапка.
        const trustCut = tseen >= 3 && tbg >= Math.max(2, Math.ceil(tfrac * tseen));
        // взвешенно: минимум голосов «фон» — штуками (не меньше двух), доля — по весам кадров
        const cut = seen < 3 * wMean ? true : few ? nbg >= 1 : (nbg >= 2 && bg >= frac * seen) || (bg + weak >= Math.max(2 * wMean, frac * seen) && bg + weak >= (opt.weakMaj ?? 0.5) * seen && nbg + weak > 0);
        occ[(z * ny + y) * nx + x] = trustCut || cut ? 0 : 1;
      }
    }
    if (onProgress && (z & 3) === 0) onProgress(z / nz);
  }
  // дно: слои ниже ~2 мм копируют слой над ними (точки на самих линиях коврика не вырезаются)
  const zf = Math.min(nz - 1, Math.ceil(2 / vs));
  for (let z = 0; z < zf; z++) for (let i = 0; i < nx * ny; i++) occ[z * nx * ny + i] = occ[zf * nx * ny + i];
  // оставляем самую большую связную часть (убирает мусор)
  const zg = Math.max(1, Math.ceil(3 / vs));
  keepLargest(occ, nx, ny, nz, zg);
  // «Колпак рамки»: пространство над предметом, которое ни один кадр не видел на фоне листа, остаётся целым
  // цилиндром рамки. Его признак — слои, заполненные вплотную к стенке рамки по всему кругу, начиная от верха.
  // Настоящий предмет стенки рамки по кругу не касается (если он не шире рамки — тогда ничего не трогаем).
  // Вертушка: пространство, видимое только на фоне стола/стены, проверяем «движением» (что крутится — предмет)
  const mc = opt.motion === false ? null : motionCarve(occ, nx, ny, nz, vs, ox, oy, oz, zg, frames);
  if (mc && mc.removed) keepLargest(occ, nx, ny, nz, zg);
  // v2.5 «с рук»: пространство, видимое только на фоне пёстрого стола, чистим по согласованности цвета (до среза колпака)
  const pc = opt.photo ? photoCarve({ occ, nx, ny, nz, vs, origin: [ox, oy, oz] }, frames, { onProgress }) : null;
  if (pc && pc.removed) keepLargest(occ, nx, ny, nz, zg);
  const capTrim = opt.capTrim === false ? 0 : trimCap(occ, nx, ny, nz, vs, box.Rb, ox, oy, zg, frames, oz, !!opt.photo);
  if (capTrim) keepLargest(occ, nx, ny, nz, zg);
  // закрытие: заполняет мелкие ямки и щели от бликов; затем заливаем пустоты внутри
  const cr = opt.close ?? Math.max(1, Math.round(1.2 / vs));
  if (cr > 0) closeGrid(occ, nx, ny, nz, cr);
  fillVoids(occ, nx, ny, nz);
  return { occ, nx, ny, nz, vs, origin: [ox, oy, oz], capTrim: capTrim * vs, capExt: trimCap.lastExt || 0, capBridge: trimCap.lastBridge || 0, photoCut: pc ? pc.removed : 0, motionCut: mc ? mc.removed * vs ** 3 : 0, Rb: box.Rb, Hb: box.Hb };
}
// ---------- v2.5: вырезание по согласованности цвета (space carving) ----------
// Снимая «с рук», выше листа предмет виден только на фоне стола/стены. Если фон пёстрый, маска его не узнаёт, и над
// предметом остаётся цилиндр рамки. Но у точки на поверхности предмета цвет во всех кадрах, где она видна, одинаков, а
// пустая точка в каждом кадре «показывает» другой кусок фона. Снаружи внутрь: видимость — по z-буферу текущей оболочки
// (она всегда шире предмета, поэтому видимое по ней видно и на самом деле), несогласованные поверхностные воксели
// вырезаем, повторяем. Воксели, которые большинство кадров видят на фоне листа (маска 2), не трогаем — там силуэт точен.
export function photoCarve(G, frames, opt = {}) {
  const { occ, nx, ny, nz, vs } = G, [ox, oy, oz] = G.origin, S = nx * ny;
  const F = frames.filter((f) => f.rgba && f.mask && f.R);
  if (F.length < 6) return { removed: 0, iters: 0 };
  const sc = 2, zb = F.map((f) => ({ w: Math.ceil(f.w / sc), h: Math.ceil(f.h / sc), d: new Float32Array(Math.ceil(f.w / sc) * Math.ceil(f.h / sc)) }));
  const state = new Uint8Array(occ.length); // 0 — не оценён, 1 — можно резать, 2 — защищён
  const agreeFrac = opt.agree ?? 0.7, maxIt = opt.iters ?? 80, zg = Math.max(1, Math.ceil(4 / vs)), minV = opt.minViews ?? 4;
  const E = (x, y, z) => x < 0 || y < 0 || x >= nx || y >= ny || z >= nz || occ[(z * ny + y) * nx + x] <= 0.5;
  const NV = F.length, cr = new Int16Array(NV * 3), pu = new Int32Array(NV), pv = new Int32Array(NV), med = [0, 0, 0], tmp = new Int16Array(NV), dv = new Float32Array(NV);
  let tol = 20, tolInfo = null;
  let removed = 0, it = 0;
  for (; it < maxIt; it++) {
    const surf = [];
    for (let z = zg; z < nz; z++) for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) {
      const i = (z * ny + y) * nx + x; if (occ[i] <= 0.5) continue;
      if (E(x - 1, y, z) || E(x + 1, y, z) || E(x, y - 1, z) || E(x, y + 1, z) || E(x, y, z + 1) || E(x, y, z - 1)) surf.push(i);
    }
    // z-буферы (полразмера кадра), воксель — квадрат по его размеру на экране
    for (let k = 0; k < NV; k++) {
      const f = F[k], R = f.R, t = f.t, K = f.K, B = zb[k], D = B.d; D.fill(Infinity);
      for (const i of surf) {
        const x = i % nx, y = ((i / nx) | 0) % ny, z = (i / S) | 0, X = ox + x * vs, Y = oy + y * vs, Z = oz + z * vs;
        const cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) continue;
        const u = (K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx) / sc, v = (K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy) / sc;
        const r = 0.5 * K.fx * vs / cz / sc + 0.5;
        const u0 = Math.max(0, Math.floor(u - r)), u1 = Math.min(B.w - 1, Math.floor(u + r)), v0 = Math.max(0, Math.floor(v - r)), v1 = Math.min(B.h - 1, Math.floor(v + r));
        for (let yy = v0; yy <= v1; yy++) for (let xx = u0; xx <= u1; xx++) { const q = yy * B.w + xx; if (cz < D[q]) D[q] = cz; }
      }
    }
    // сбор: видимые кадры воксела (z-буфер), голоса «фон», цвета; dv — отклонения от медианы (мин. по окну 3×3)
    const gather = (i) => {
      const x = i % nx, y = ((i / nx) | 0) % ny, z = (i / S) | 0, X = ox + x * vs, Y = oy + y * vs, Z = oz + z * vs;
      let n = 0, n2 = 0, nb = 0;
      for (let k = 0; k < NV; k++) {
        const f = F[k], R = f.R, t = f.t, K = f.K;
        const cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) continue;
        const uf = K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx, vf = K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy;
        const u = uf | 0, v = vf | 0; if (u < 1 || v < 1 || u >= f.w - 1 || v >= f.h - 1) continue;
        const B = zb[k]; if (cz > B.d[((v / sc) | 0) * B.w + ((u / sc) | 0)] + 1.5 * vs) continue; // заслонён
        const m = f.mask[v * f.w + u]; if (m === 4) continue;
        if (m === 2) n2++;
        if (m === 0 || m === 3) { nb++; continue; } // за точкой узнан фон (стена/небо) — голос «пусто», цвет не нужен
        const p = (v * f.w + u) * 4; cr[n * 3] = f.rgba[p]; cr[n * 3 + 1] = f.rgba[p + 1]; cr[n * 3 + 2] = f.rgba[p + 2]; pu[n] = u; pv[n] = v; tmp[n] = k; n++;
      }
      if (n >= 2) {
        for (let c = 0; c < 3; c++) { const a_ = []; for (let j = 0; j < n; j++) a_.push(cr[j * 3 + c]); a_.sort((p_, q_) => p_ - q_); med[c] = a_[n >> 1]; }
        for (let j = 0; j < n; j++) {
          const f = F[tmp[j]], w = f.w; let best = 1e9;
          for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const p = ((pv[j] + dy) * w + pu[j] + dx) * 4, d = Math.abs(f.rgba[p] - med[0]) + Math.abs(f.rgba[p + 1] - med[1]) + Math.abs(f.rgba[p + 2] - med[2]); if (d < best) best = d; }
          dv[j] = best;
        }
      }
      return { n, n2, nb, nt: n + nb };
    };
    if (it === 0) { // допуск по самой съёмке: насколько согласован низ предмета, видимый на фоне листа (точно предмет)
      const ds = [];
      for (const i of surf) {
        const g = gather(i);
        if (g.nt >= 3) state[i] = g.n2 >= 2 && g.n2 >= 0.3 * g.nt ? 2 : 1;
        if (state[i] === 2 && g.n >= 3) { const a_ = Array.from(dv.subarray(0, g.n)).sort((p_, q_) => p_ - q_); ds.push(a_[Math.floor(g.n * 0.5)]); }
      }
      ds.sort((p_, q_) => p_ - q_);
      const d0 = ds.length >= 50 ? ds[Math.floor(ds.length * 0.5)] : 16;
      tol = opt.tol ?? Math.max(10, Math.min(40, 1.3 * d0 + 4));
      tolInfo = { d0, tol, nRef: ds.length };
    }
    const kill = [];
    for (const i of surf) {
      if (state[i] === 2) continue;
      const g = gather(i), nt = g.nt;
      if (!state[i] && nt >= 3) state[i] = g.n2 >= 2 && g.n2 >= 0.3 * nt ? 2 : 1;
      if (state[i] !== 1 || nt < minV) continue;
      if (g.n < 2) { if (g.nb >= minV) kill.push(i); continue; }
      let agree = 0; for (let j = 0; j < g.n; j++) if (dv[j] < tol) agree++;
      if (agree < agreeFrac * nt) kill.push(i); // согласных по цвету — меньшинство всех видевших
    }
    for (const i of kill) occ[i] = 0;
    removed += kill.length;
    if (opt.onProgress) opt.onProgress(Math.min(1, 0.7 + 0.3 * it / maxIt));
    if (kill.length < Math.max(10, surf.length * 0.0005)) break;
  }
  return { removed: removed * vs ** 3, iters: it + 1, tol: tolInfo };
}
// ---------- «Сосуд»: полость внутри (кружка, ваза, стакан) ----------
// Силуэты полость не видят никогда — снаружи она закрыта стенкой. Достраиваем: контур полости = верхний срез,
// суженный на толщину стенки; вниз полость только сужается (пересечение суженных срезов); глубину дна ищем
// перебором плоскостей: на верной глубине цвет дна одинаков во всех кадрах, которые видят его сквозь горлышко.
function dist2D(m, nx, ny) { // шашечное (3-4) расстояние до «пусто», в шагах сетки
  const d = new Float32Array(nx * ny), INF = 1e9;
  for (let i = 0; i < nx * ny; i++) d[i] = m[i] ? INF : 0;
  for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) { const i = y * nx + x; if (!d[i]) continue; let v = d[i];
    if (x > 0) v = Math.min(v, d[i - 1] + 1); else v = Math.min(v, 1); if (y > 0) v = Math.min(v, d[i - nx] + 1); else v = Math.min(v, 1);
    if (x > 0 && y > 0) v = Math.min(v, d[i - nx - 1] + 1.4142); if (x < nx - 1 && y > 0) v = Math.min(v, d[i - nx + 1] + 1.4142); d[i] = v; }
  for (let y = ny - 1; y >= 0; y--) for (let x = nx - 1; x >= 0; x--) { const i = y * nx + x; if (!d[i]) continue; let v = d[i];
    if (x < nx - 1) v = Math.min(v, d[i + 1] + 1); else v = Math.min(v, 1); if (y < ny - 1) v = Math.min(v, d[i + nx] + 1); else v = Math.min(v, 1);
    if (x < nx - 1 && y < ny - 1) v = Math.min(v, d[i + nx + 1] + 1.4142); if (x > 0 && y < ny - 1) v = Math.min(v, d[i + nx - 1] + 1.4142); d[i] = v; }
  return d;
}
function largest2D(m, nx, ny) {
  const lab = new Int32Array(nx * ny), st = []; let best = 0, bestL = 0, L = 0;
  for (let i = 0; i < nx * ny; i++) { if (!m[i] || lab[i]) continue; L++; let n = 0; st.push(i); lab[i] = L;
    while (st.length) { const j = st.pop(); n++; const x = j % nx, y = (j / nx) | 0;
      if (x > 0 && m[j - 1] && !lab[j - 1]) { lab[j - 1] = L; st.push(j - 1); } if (x < nx - 1 && m[j + 1] && !lab[j + 1]) { lab[j + 1] = L; st.push(j + 1); }
      if (y > 0 && m[j - nx] && !lab[j - nx]) { lab[j - nx] = L; st.push(j - nx); } if (y < ny - 1 && m[j + nx] && !lab[j + nx]) { lab[j + nx] = L; st.push(j + nx); } }
    if (n > best) { best = n; bestL = L; } }
  const out = new Uint8Array(nx * ny); for (let i = 0; i < nx * ny; i++) out[i] = lab[i] === bestL && bestL ? 1 : 0; return { m: out, n: best };
}
// Фотосогласованность внешней поверхности оболочки по слоям: настоящая стенка видна одинаковой во всех кадрах,
// «шапка» над горлышком — воздух, сквозь который кадры видят разные места внутренности.
export function shellConsistency(G, frames) {
  const { occ, nx, ny, nz, vs } = G, [ox, oy, oz] = G.origin, NN = nx * ny, O = (x, y, z) => x >= 0 && y >= 0 && z >= 0 && x < nx && y < ny && z < nz && occ[(z * ny + y) * nx + x] > 0.5;
  const cams = frames.filter((f) => f.rgba).map((f) => { const R = f.R, t = f.t; return { f, c: [-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])] }; });
  const out = new Float32Array(nz).fill(NaN);
  for (let z = 1; z < nz - 1; z++) {
    const pts = []; for (let y = 1; y < ny - 1; y++) for (let x = 1; x < nx - 1; x++) { if (!O(x, y, z)) continue; let gx = 0, gy = 0;
      if (!O(x - 1, y, z)) gx--; if (!O(x + 1, y, z)) gx++; if (!O(x, y - 1, z)) gy--; if (!O(x, y + 1, z)) gy++; if (gx || gy) { const l = Math.hypot(gx, gy); pts.push([x, y, gx / l, gy / l]); } }
    if (pts.length < 8) continue; const stp = Math.max(1, Math.floor(pts.length / 150)); let sv = 0, np = 0;
    for (let k = 0; k < pts.length; k += stp) { const [x, y, gx, gy] = pts[k], X = ox + (x + 0.5 * gx) * vs, Y = oy + (y + 0.5 * gy) * vs, Z = oz + z * vs; let n = 0, s0 = 0, s1 = 0, s2 = 0, q = 0;
      for (const cm of cams) { const dx = cm.c[0] - X, dy = cm.c[1] - Y, dz = cm.c[2] - Z, L = Math.hypot(dx, dy, dz); if ((dx * gx + dy * gy) / L < 0.35) continue;
        let vis = true; for (let s_ = 1.5; s_ < 60 && vis; s_ += 1) { const xi = Math.round(x + gx * 0.5 + s_ * dx / L), yi = Math.round(y + gy * 0.5 + s_ * dy / L), zi = Math.round(z + s_ * dz / L); if (zi >= nz) break; if (O(xi, yi, zi)) vis = false; }
        if (!vis) continue; const f = cm.f, R = f.R, t = f.t, K = f.K, cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) continue;
        const u = (K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx) | 0, v = (K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy) | 0; if (u < 1 || v < 1 || u >= f.w - 1 || v >= f.h - 1) continue;
        const i = (v * f.w + u) * 4, a = f.rgba[i], b = f.rgba[i + 1], c = f.rgba[i + 2]; n++; s0 += a; s1 += b; s2 += c; q += a * a + b * b + c * c; }
      if (n < 3) continue; sv += (q - (s0 * s0 + s1 * s1 + s2 * s2) / n) / n; np++; }
    if (np >= 6) out[z] = sv / np;
  }
  return out;
}
export function vesselCarve(G, frames, opt = {}) {
  const { occ, nx, ny, nz, vs } = G, [ox, oy, oz] = G.origin, NN = nx * ny;
  const area = new Int32Array(nz); for (let z = 0; z < nz; z++) { let a = 0; for (let i = 0; i < NN; i++) a += occ[z * NN + i] > 0.5 ? 1 : 0; area[z] = a; }
  let zt = nz - 1; while (zt > 0 && area[zt] === 0) zt--;
  // «шапка» над горлышком: сверху пространство над отверстием видно на фоне внутренности — силуэты его не срезают.
  // Кромка = верхний слой, где внешняя стенка фотосогласована; запасной признак — резкое сужение площади к верху.
  let zr = Math.max(1, zt - 1), capBy = '';
  { const c = shellConsistency(G, frames), body = [];
    for (let z = Math.round(0.15 * zt); z <= Math.round(0.7 * zt); z++) if (c[z] === c[z]) body.push(c[z]);
    body.sort((a_, b_) => a_ - b_); const M = body.length ? body[body.length >> 1] : NaN, thr = 2.5 * M;
    let z = zt, hi = 0; while (z > zt * 0.5 && !(c[z] < thr && c[z - 1] < thr)) { if (c[z] >= thr) hi++; z--; }
    if (M === M && hi >= 2 && z > zt * 0.5 && z < zt) { zr = z; capBy = 'стенка'; }
    else { const d = Math.max(1, Math.round(3 / vs)); let z2 = zt - 1; while (z2 - d > zt * 0.5 && area[z2] < 0.93 * area[z2 - d]) z2--; if (z2 < zt - 1) { zr = z2; capBy = 'площадь'; } } }
  let capRemoved = 0;
  for (let z = zr + 1; z <= zt; z++) for (let i = 0; i < NN; i++) if (occ[z * NN + i] > 0.5) { occ[z * NN + i] = 0; capRemoved++; }
  zt = zr;
  const H = (zt + 1) * vs, rim = new Uint8Array(NN); for (let i = 0; i < NN; i++) rim[i] = occ[zr * NN + i] > 0.5 ? 1 : 0;
  const R = Math.sqrt(largest2D(rim, nx, ny).n / Math.PI) * vs;
  const wall = opt.wall ?? Math.max(2, Math.min(5, 0.1 * R)), tv = wall / vs;
  // контуры полости по слоям сверху вниз
  const C = new Array(nz).fill(null);
  { const d = dist2D(rim, nx, ny), c = new Uint8Array(NN); for (let i = 0; i < NN; i++) c[i] = d[i] > tv ? 1 : 0; C[zr] = largest2D(c, nx, ny).m; }
  let cA = 0; for (const v of C[zr]) cA += v;
  if (cA * vs * vs < Math.PI * 9) return { removed: 0, reason: `горлышко слишком узкое (радиус ${R.toFixed(0)} мм, стенка ${wall.toFixed(1)} мм)` };
  const zMin = Math.max(1, Math.ceil((opt.minBottom ?? 2) / vs)); let zLow = zr;
  for (let z = zr - 1; z >= zMin; z--) { const sl = new Uint8Array(NN); for (let i = 0; i < NN; i++) sl[i] = occ[z * NN + i] > 0.5 ? 1 : 0;
    const d = dist2D(sl, nx, ny), c = new Uint8Array(NN); let n = 0; for (let i = 0; i < NN; i++) { c[i] = C[z + 1][i] && d[i] > tv ? 1 : 0; n += c[i]; }
    if (n * vs * vs < Math.PI * 4) break; C[z] = c; zLow = z; }
  // перебор глубины дна: zf — верхний слой дна (полость — слои zf+1..zt)
  const cams = frames.map((f) => { const Rm = f.R, t = f.t; return { f, c: [-(Rm[0] * t[0] + Rm[3] * t[1] + Rm[6] * t[2]), -(Rm[1] * t[0] + Rm[4] * t[1] + Rm[7] * t[2]), -(Rm[2] * t[0] + Rm[5] * t[1] + Rm[8] * t[2])] }; })
    .filter((c) => c.f.rgba && c.c[2] > oz + (zr + 1) * vs);
  const sample = (f, X, Y, Z, out) => { const Rm = f.R, t = f.t, K = f.K, cz = Rm[6] * X + Rm[7] * Y + Rm[8] * Z + t[2]; if (cz <= 1) return false;
    const u = (K.fx * (Rm[0] * X + Rm[1] * Y + Rm[2] * Z + t[0]) / cz + K.cx) | 0, v = (K.fy * (Rm[3] * X + Rm[4] * Y + Rm[5] * Z + t[1]) / cz + K.cy) | 0;
    if (u < 1 || v < 1 || u >= f.w - 1 || v >= f.h - 1) return false; const q = (v * f.w + u) * 4; out[0] = f.rgba[q]; out[1] = f.rgba[q + 1]; out[2] = f.rgba[q + 2]; return true; };
  const cost = new Float32Array(nz).fill(NaN), col = [0, 0, 0];
  for (let zf = zLow - 1; zf <= zr; zf++) {
    const Cf = zf === zr ? C[zr] : C[zf + 1]; if (!Cf) continue; // точки дна лежат под полостью слоя zf+1 (zf = zr — гипотеза «сплошная крышка»)
    const Zf = oz + (zf + 0.5) * vs, pts = []; for (let i = 0; i < NN; i++) if (Cf[i]) pts.push(i);
    const stp = Math.max(1, Math.floor(pts.length / 300)); let sv = 0, np = 0;
    for (let k = 0; k < pts.length; k += stp) { const i = pts[k], X = ox + (i % nx) * vs, Y = oy + ((i / nx) | 0) * vs; let n = 0, s0 = 0, s1 = 0, s2 = 0, q0 = 0, q1 = 0, q2 = 0;
      for (const cm of cams) { const dx = cm.c[0] - X, dy = cm.c[1] - Y, dz = cm.c[2] - Zf; let vis = true;
        for (let z = zf + 1; z <= zr && vis; z++) { const s_ = (oz + z * vs - Zf) / dz, xi = Math.round((X + s_ * dx - ox) / vs), yi = Math.round((Y + s_ * dy - oy) / vs);
          if (xi < 0 || yi < 0 || xi >= nx || yi >= ny || !C[z][yi * nx + xi]) vis = false; }
        if (!vis || !sample(cm.f, X, Y, Zf, col)) continue; n++; s0 += col[0]; s1 += col[1]; s2 += col[2]; q0 += col[0] * col[0]; q1 += col[1] * col[1]; q2 += col[2] * col[2]; }
      if (n < 3) continue; sv += (q0 - s0 * s0 / n + q1 - s1 * s1 / n + q2 - s2 * s2 / n) / n; np++; }
    if (np >= 12) cost[zf] = sv / np;
  }
  let zb = -1, cb = Infinity; const cs = []; for (let z = 0; z < zr - 1; z++) if (cost[z] === cost[z]) { cs.push(cost[z]); if (cost[z] < cb) { cb = cost[z]; zb = z; } }
  cs.sort((a, b) => a - b); const med = cs.length ? cs[cs.length >> 1] : NaN, lid = cost[zr];
  // настоящая ямка: и выше, и ниже найденной глубины стоимость заметно больше (однотонное дно даёт монотонный спад — не верим)
  const at = (z) => (z >= 0 && z < nz && cost[z] === cost[z] ? cost[z] : NaN), dz4 = Math.max(1, Math.round(4 / vs)), dz6 = Math.max(2, Math.round(6 / vs));
  let below = NaN; for (let z = zb - 1; z >= zb - dz4; z--) { const c = at(z); if (c === c) below = below === below ? Math.max(below, c) : c; }
  const above = at(zb + dz6);
  let measured = zb >= 0 && cs.length >= 4 && cb < 0.6 * med && !(lid <= cb * 1.1) && below > 1.25 * cb && above > 2 * cb && above - cb > 100;
  if (!measured) zb = Math.max(zLow, Math.min(zr - 2, Math.round((opt.defBottom ?? Math.max(3, Math.min(8, 0.08 * H))) / vs) - 1));
  zb = Math.max(zb, zLow - 1);
  let removed = 0;
  for (let z = zb + 1; z <= zt; z++) { const c = C[Math.min(z, zr)]; if (!c) continue; for (let i = 0; i < NN; i++) if (c[i] && occ[z * NN + i] > 0.5) { occ[z * NN + i] = 0; removed++; } }
  return { removed, volume: removed * vs ** 3, capBy, cap: capRemoved * vs ** 3, rim: (zr + 1) * vs, depth: (zt + 1 - (zb + 1)) * vs, bottom: (zb + 1) * vs, wall, R, measured, lidLike: lid <= cb * 1.1, cost: Array.from(cost) };
}
// ---------- «Движение» на вертушке: что крутится — то предмет ----------
// Камера стоит, крутится только столик с предметом. Стол и стена за листом в кадрах одной позиции камеры неподвижны:
// их медиана по кадрам — пустой фон. Пиксель за листом, заметно отличный от этой медианы, — это предмет
// (или его тень). Это только улика «здесь что-то есть»: ею ничего не вырезаем, лишь не даём срезать верх
// высокого предмета, который ни в одном кадре не виден на фоне листа.
// Кадры группируются по положению камеры (высота и расстояние до оси), так что перестановка держателя
// между оборотами учитывается: у каждой позиции свой фон.
// v2.5: «стол за листом» (съёмка с рук). Стол — плоскость z=0, как и коврик. Пиксель «неизвестно» за листом, чей луч
// упирается в стол, сравниваем с той же точкой стола в других кадрах, где она заведомо открыта (там за рамкой, фон 0):
// совпал рисунок (корреляция окна 5×5 на плоскости стола) — здесь тоже стол, «слабый фон» (3). Предмет, заслонивший стол,
// в разных кадрах заслоняет разные его точки — совпадения не будет. Так срезается «колпак» над высоким предметом,
// снятым почти в профиль, когда верх виден только на фоне стола (раньше колпак срезался вслепую — вместе с верхом).
export function tableConsistency(frames, opt = {}) {
  const Rb = opt.Rb || 55, rMax = opt.rMax ?? 2500, R = 2, NP = (2 * R + 1) ** 2, stride = opt.stride ?? 2;
  const gr = frames.map((f) => { const g = new Uint8Array(f.w * f.h); for (let i = 0; i < g.length; i++) g[i] = (77 * f.rgba[i * 4] + 150 * f.rgba[i * 4 + 1] + 29 * f.rgba[i * 4 + 2]) >> 8; return g; });
  const C = frames.map((f) => { const R_ = f.R, t = f.t; return [-(R_[0] * t[0] + R_[3] * t[1] + R_[6] * t[2]), -(R_[1] * t[0] + R_[4] * t[1] + R_[7] * t[2]), -(R_[2] * t[0] + R_[5] * t[1] + R_[8] * t[2])]; });
  const proj = (f, X, Y, out) => { const R_ = f.R, t = f.t, K = f.K, cz = R_[6] * X + R_[7] * Y + t[2]; if (cz <= 1) return false;
    out[0] = K.fx * (R_[0] * X + R_[1] * Y + t[0]) / cz + K.cx - 0.5; out[1] = K.fy * (R_[3] * X + R_[4] * Y + t[1]) / cz + K.cy - 0.5;
    return out[0] >= 1 && out[1] >= 1 && out[0] < f.w - 2 && out[1] < f.h - 2; };
  const samp = (g, w, x, y) => { const x0 = x | 0, y0 = y | 0, a = x - x0, b = y - y0, i = y0 * w + x0; return (g[i] * (1 - a) + g[i + 1] * a) * (1 - b) + (g[i + w] * (1 - a) + g[i + w + 1] * a) * b; };
  let marked = 0, tested = 0; const q = [0, 0], PX = new Float32Array(NP * 2), A = new Float32Array(NP), B = new Float32Array(NP);
  for (let i = 0; i < frames.length; i++) {
    const f = frames[i], { w, h, K, mask } = f, R_ = f.R, Ci = C[i], g = gr[i], add = [];
    for (let y = R + 1; y < h - R - 1; y += stride) for (let x = R + 1; x < w - R - 1; x += stride) {
      const p = y * w + x; if (mask[p] !== 1) continue;
      // точки стола под пикселями окна 5×5
      let ok = true;
      for (let dy = -R, k = 0; dy <= R && ok; dy++) for (let dx = -R; dx <= R; dx++, k++) {
        const cx = (x + dx + 0.5 - K.cx) / K.fx, cy = (y + dy + 0.5 - K.cy) / K.fy;
        const ddx = R_[0] * cx + R_[3] * cy + R_[6], ddy = R_[1] * cx + R_[4] * cy + R_[7], ddz = R_[2] * cx + R_[5] * cy + R_[8];
        if (ddz > -1e-4) { ok = false; break; } const s_ = -Ci[2] / ddz, X = Ci[0] + ddx * s_, Y = Ci[1] + ddy * s_;
        if (X * X + Y * Y < (1.3 * Rb) ** 2 || X * X + Y * Y > rMax * rMax) { ok = false; break; }
        PX[k * 2] = X; PX[k * 2 + 1] = Y; A[k] = g[(y + dy) * w + x + dx];
      }
      if (!ok) continue;
      let ma = 0; for (let k = 0; k < NP; k++) ma += A[k]; ma /= NP; let va = 0; for (let k = 0; k < NP; k++) { A[k] -= ma; va += A[k] * A[k]; }
      if (va / NP < 16) continue; // гладкий стол — тут работает заливка по цвету
      tested++;
      let agree = 0, views = 0;
      for (let j = 0; j < frames.length && views < 8; j++) {
        if (j === i) continue; const fj = frames[j];
        if (!proj(fj, PX[2 * (NP >> 1)], PX[2 * (NP >> 1) + 1], q)) continue;
        if (fj.mask[Math.round(q[1]) * fj.w + Math.round(q[0])] !== 0) continue; // там точка стола может быть заслонена
        let okj = true; for (let k = 0; k < NP; k++) { if (!proj(fj, PX[k * 2], PX[k * 2 + 1], q)) { okj = false; break; } B[k] = samp(gr[j], fj.w, q[0], q[1]); }
        if (!okj) continue;
        let mb = 0; for (let k = 0; k < NP; k++) mb += B[k]; mb /= NP; let vb = 0, ab = 0; for (let k = 0; k < NP; k++) { const b = B[k] - mb; vb += b * b; ab += A[k] * b; }
        views++; if (vb / NP > 8 && ab / Math.sqrt(va * vb) > (opt.ncc ?? 0.7)) agree++;
      }
      if (views >= 2 && agree >= 2 && agree >= 0.6 * views) add.push(p);
    }
    // шаг 2 пикселя: метим и соседей по сетке
    for (const p of add) { const x = p % w, y = (p / w) | 0; for (let dy = 0; dy < stride; dy++) for (let dx = 0; dx < stride; dx++) { const r = (y + dy) * w + x + dx; if (y + dy < h && x + dx < w && mask[r] === 1) { mask[r] = 3; marked++; } } }
  }
  return { tested, marked };
}
export function motionMasks(frames, opt = {}) {
  const tau = opt.tau ?? 26, minG = opt.minGroup ?? 8, refTol = opt.refMoveTol ?? 0.10, groups = [];
  for (const f of frames) {
    const R = f.R, t = f.t;
    const C = [-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])];
    const rho = Math.hypot(C[0], C[1]), cz = C[2], tol = Math.max(4, 0.025 * Math.hypot(rho, cz));
    let g = groups.find((q) => q.w === f.w && q.h === f.h && Math.abs(q.rho - rho) < tol && Math.abs(q.cz - cz) < tol);
    if (!g) { g = { rho, cz, w: f.w, h: f.h, fr: [] }; groups.push(g); }
    g.fr.push(f);
  }
  let used = 0;
  for (const g of groups) {
    if (g.fr.length < minG) continue;
    const { w, h } = g, n = g.fr.length, np = w * h, med = new Uint8Array(np * 3), buf = new Uint8Array(n);
    // медиана считается только там, где пригодится: за листом (маска 1 или 3) хотя бы в одном кадре
    const need = new Uint8Array(np);
    for (const f of g.fr) { for (let i = 0; i < np; i++) { const m = f.mask[i]; if (m === 1 || m === 3) need[i] = 1; } if (f.refOut) for (const i of f.refOut) need[i] = 1; }
    for (let i = 0; i < np; i++) {
      if (!need[i]) continue;
      for (let c = 0; c < 3; c++) {
        for (let k = 0; k < n; k++) buf[k] = g.fr[k].rgba[i * 4 + c];
        buf.sort(); med[i * 3 + c] = buf[n >> 1];
      }
    }
    for (const f of g.fr) {
      // поправка яркости (автоэкспозиция): медиана отношения кадр/фон по точкам за листом
      const rs = [];
      for (let i = 0; i < np; i += 7) if (need[i] && f.mask[i] !== 0 && f.mask[i] !== 2) { const a = f.rgba[i * 4] + f.rgba[i * 4 + 1] + f.rgba[i * 4 + 2], b = med[i * 3] + med[i * 3 + 1] + med[i * 3 + 2]; if (b > 60) rs.push(a / b); }
      rs.sort((a, b) => a - b); const gn = rs.length > 50 ? Math.min(1.5, Math.max(0.67, rs[rs.length >> 1])) : 1;
      const raw = new Uint8Array(np);
      for (let i = 0; i < np; i++) {
        const m = f.mask[i]; if (!need[i] || (m !== 1 && m !== 3)) continue;
        let d = 0; for (let c = 0; c < 3; c++) d = Math.max(d, Math.abs(f.rgba[i * 4 + c] - gn * med[i * 3 + c]));
        if (d > tau) raw[i] = 1;
      }
      // открытие 3×3: одиночные шумовые точки и полоски JPEG не считаются движением
      const er = new Uint8Array(np), mo = new Uint8Array(np);
      for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) { const i = y * w + x; if (raw[i] && raw[i - 1] && raw[i + 1] && raw[i - w] && raw[i + w]) er[i] = 1; }
      for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) { const i = y * w + x; if (er[i] || er[i - 1] || er[i + 1] || er[i - w] || er[i + w]) mo[i] = raw[i]; }
      // заведомый фон (за листом, вне рамки) заметно «движется» — камера сдвинулась или свет мигнул: улик не берём
      if (f.refOut && f.refOut.length > 200) {
        let nm = 0; for (const i of f.refOut) { let d = 0; for (let c = 0; c < 3; c++) d = Math.max(d, Math.abs(f.rgba[i * 4 + c] - gn * med[i * 3 + c])); if (d > tau) nm++; }
        f.refMoved = nm / f.refOut.length; f.refN = f.refOut.length;
        if (nm > refTol * f.refOut.length) { f.motion = null; f.bgMed = null; g.moved = (g.moved || 0) + 1; continue; }
      }
      f.motion = mo; used++;
      f.bgMed = med; f.bgGain = gn; // фон за предметом (медиана с этого места камеры) — сплэтам: капли не должны «рисовать» стену
    }
  }
  return { groups: groups.length, used, sizes: groups.map((g) => g.fr.length), moved: groups.reduce((a, g) => a + (g.moved || 0), 0) };
}
// после пересечения с «низом»: убрать обрывки (оставить стоящее на столе) и залить пустоты
export function cleanGrid(G) { const zg = Math.max(1, Math.ceil(3 / G.vs)); keepLargest(G.occ, G.nx, G.ny, G.nz, zg); fillVoids(G.occ, G.nx, G.ny, G.nz); return G; }
function trimCap(occ, nx, ny, nz, vs, Rb, ox, oy, zg, frames, oz, soft = false) {
  const ring = [], r0 = (Rb - 2.2 * vs) ** 2, r1 = Rb * Rb;
  for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) { const X = ox + x * vs, Y = oy + y * vs, d = X * X + Y * Y; if (d > r0 && d <= r1) ring.push(y * nx + x); }
  if (!ring.length) return 0;
  const rf = (z) => { let o = 0; for (const i of ring) if (occ[z * nx * ny + i] > 0.5) o++; return o / ring.length; };
  // верхний слой с заполненным кольцом; всё над ним — его рваная «крышка»
  let zr = nz - 1; while (zr >= 0 && rf(zr) < 0.5) zr--;
  if (zr < 0) return 0;
  let z = zr; while (z >= 0 && rf(z) >= 0.5) z--;
  if (z < zg + 2) return 0; // «предмет шире рамки» до самого низа — не трогаем
  let zt = nz - 1;
  for (; zt > z; zt--) { let any = false; for (let i = 0; i < nx * ny && !any; i++) any = occ[zt * nx * ny + i] > 0.5; if (any) break; }
  // v2.5: «мост». Над полосой колпака может стоять настоящий верх предмета: там фон (стена, небо) узнан, и форма уже
  // вырезана — узкая, стенок рамки не касается. Тогда полоса — середина предмета, а не крышка: вместо среза всего выше z
  // заменяем полосу сечениями сверху и снизу (их объединение, чуть расширенное), верх оставляем.
  trimCap.lastBridge = 0;
  { const S = nx * ny, area = (q) => { let a = 0; for (let i = 0; i < S; i++) a += occ[q * S + i] > 0.5 ? 1 : 0; return a; };
    let disc = 0; for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) { const X = ox + x * vs, Y = oy + y * vs; if (X * X + Y * Y <= Rb * Rb) disc++; }
    // «с рук» (soft): форма выше полосы уже вырезана по цвету — достаточно, что это не сплошной круг рамки
    let za = 0, good = 0, zTop = 0;
    for (const [rMax, aMax, rag] of soft ? [[0.1, 0.6, nz], [0.5, 0.9, Math.round(6 / vs)]] : [[0.1, 0.6, nz]]) {
      za = zr + 1; while (za <= zt && za - zr <= rag && rf(za) >= rMax) za++; // рваный край над полосой
      good = 0; zTop = za - 1;
      for (let q = za; q <= zt; q++) { const a = area(q); if (!a) break; if (rf(q) < rMax && a < aMax * disc) { good++; zTop = q; } else break; }
      if (good * vs >= 10) break;
    }
    if (good * vs >= 10 && za <= zt) {
      const Sa = new Uint8Array(S), Sb = new Uint8Array(S);
      for (let i = 0; i < S; i++) { Sa[i] = occ[za * S + i] > 0.5 ? 1 : 0; Sb[i] = z >= 0 && occ[z * S + i] > 0.5 ? 1 : 0; }
      const U = new Uint8Array(S); for (let i = 0; i < S; i++) U[i] = Sa[i] | Sb[i];
      const D = new Uint8Array(S);
      for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) { let v = 0; for (let dy = -1; dy <= 1 && !v; dy++) for (let dx = -1; dx <= 1 && !v; dx++) { const xx = x + dx, yy = y + dy; if (xx >= 0 && yy >= 0 && xx < nx && yy < ny && U[yy * nx + xx]) v = 1; } D[y * nx + x] = v; }
      for (let q = z + 1; q < za; q++) for (let i = 0; i < S; i++) if (!D[i]) occ[q * S + i] = 0;
      for (let q = zTop + 1; q <= zt; q++) occ.fill(0, q * S, (q + 1) * S); // над верхом — мусор
      trimCap.lastBridge = (za - z - 1) * vs; trimCap.lastExt = 0;
      return 0;
    }
  }
  // Высокий предмет: его верх тоже ни разу не виден на фоне листа и выглядит как «колпак». Если в кадрах там есть
  // «движение» (крутящийся предмет на неподвижном фоне), продолжаем предмет вверх, пока движение есть:
  // сечение — как у последнего надёжного слоя, сужаясь там, где движущийся силуэт уже.
  const capOcc = occ.slice((z + 1) * nx * ny, (zt + 1) * nx * ny); // для поиска «движения» в колпаке
  for (let q = z + 1; q <= zt; q++) occ.fill(0, q * nx * ny, (q + 1) * nx * ny);
  // Под колпаком — переходная полоса (~25 мм), которую тоже никто не видел на фоне листа: там форма расползается
  // «шляпкой гриба». В этой полосе слой может быть шире нижнего не больше чем на 1 воксель за 3 слоя (почти отвесно).
  const band = Math.round(25 / vs), S = nx * ny, prev = new Uint8Array(S), dil = new Uint8Array(S);
  const q0 = Math.max(zg + 1, z - band + 1);
  for (let q = q0; q <= z; q++) {
    for (let i = 0; i < S; i++) prev[i] = occ[(q - 1) * S + i] > 0.5 ? 1 : 0;
    if ((q - q0) % 3) { for (let i = 0; i < S; i++) if (!prev[i]) occ[q * S + i] = 0; continue; }
    for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) {
      let v = 0;
      for (let dy = -1; dy <= 1 && !v; dy++) for (let dx = -1; dx <= 1 && !v; dx++) { const xx = x + dx, yy = y + dy; if (xx >= 0 && yy >= 0 && xx < nx && yy < ny && prev[yy * nx + xx]) v = 1; }
      dil[y * nx + x] = v;
    }
    for (let i = 0; i < S; i++) if (!dil[i]) occ[q * S + i] = 0;
  }
  // уже суженный слой z — основа для продолжения вверх
  // основа — самый узкий слой надёжной полосы под колпаком (выше форма уже может расползаться «шляпкой»)
  let zb = z, ab = Infinity;
  for (let q = Math.max(zg + 1, z - band); q <= z; q++) { let a = 0; for (let i = 0; i < S; i++) a += occ[q * S + i] > 0.5 ? 1 : 0; if (a > 0 && a <= ab) { ab = a; zb = q; } }
  const ext = frames ? extendByMotion(occ, capOcc, nx, ny, vs, ox, oy, oz, z, zt, frames, zb) : z;
  trimCap.lastExt = (ext - z) * vs;
  return Math.max(0, zt - ext);
}
// Слои z+1..zt (над уровнем «колпака»): воксель — «предмет», если в ≥35% кадров, где его проекция за листом,
// там движение. Возвращает новый верх предмета; слои до него заполняются сечением предыдущего слоя ∩ улики.
export const MOTION_OPT = { frac: 0.3, off: 0.35, minGroup: 4 }; // v2.6: мягче пороги — тёмные силуэты дают мало разницы с медианой фона
// Воксель, который в большинстве кадров виден лишь за листом (маска 1/3), остаётся, только если там «движение»
// хотя бы в половине таких кадров. Середину силуэта однотонного предмета движение не покрывает — поэтому
// в каждом слое оставляем всё, что лежит между подтверждёнными вокселями по строкам и столбцам.
function motionCarve(occ, nx, ny, nz, vs, ox, oy, oz, zg, frames) {
  const minGroup = MOTION_OPT.minGroup ?? 4;
  const offF = MOTION_OPT.off;
  const F = frames.filter((f) => f.motion);
  if (F.length < minGroup) return null;
  const S = nx * ny, fr = new Float32Array(nz);
  // доля «непроверенных» вокселей в слое: в большинстве кадров видны только за листом (стол, стена)
  for (let q = zg + 1; q < nz; q++) {
    const Z = oz + q * vs; let occN = 0, cand = 0;
    for (let y = 0; y < ny; y += 2) for (let x = 0; x < nx; x += 2) { // через один — для скорости
      const i = q * S + y * nx + x; if (occ[i] < 0.5) continue; occN++;
      const X = ox + x * vs, Y = oy + y * vs; let so = 0, seen = 0;
      for (const f of F) {
        const R = f.R, t = f.t, K = f.K, cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) continue;
        const u = (K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx) | 0, v = (K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy) | 0;
        if (u < 0 || v < 0 || u >= f.w || v >= f.h) continue;
        const m = f.mask[v * f.w + u]; if (m === 4) continue;
        seen++; if (m === 1 || m === 3) so++;
      }
      if (so >= minGroup && so >= offF * seen) cand++;
    }
    fr[q] = occN ? cand / occN : 0;
  }
  let zu = -1;
  for (let q = zg + 2; q + 2 < nz; q++) if (fr[q] >= 0.35 && fr[q + 1] >= 0.35 && fr[q + 2] >= 0.3) { zu = q; break; }
  if (zu < 0) return null;
  let zt = nz - 1; for (; zt > zu; zt--) { let any = false; for (let i = 0; i < S && !any; i++) any = occ[zt * S + i] > 0.5; if (any) break; }
  if (zt <= zu) return null;
  // основа — самый узкий слой в полосе 25 мм под границей; выше — продолжение по «движению»
  const band = Math.round(25 / vs); let zb = zu, ab = Infinity;
  for (let q = Math.max(zg + 1, zu - band); q <= zu; q++) { let a = 0; for (let i = 0; i < S; i++) a += occ[q * S + i] > 0.5 ? 1 : 0; if (a > 0 && a <= ab) { ab = a; zb = q; } }
  const capOcc = occ.slice((zu + 1) * S, (zt + 1) * S), keepTop = occ.slice((zb + 1) * S, (zt + 1) * S);
  for (let q = zu + 1; q <= zt; q++) occ.fill(0, q * S, (q + 1) * S);
  const ext = extendByMotion(occ, capOcc, nx, ny, vs, ox, oy, oz, zu, zt, F, zb);
  if (ext <= zu) { occ.set(keepTop, (zb + 1) * S); return null; } // движения выше нет — решает прежнее правило «колпака»
  for (let q = ext + 1; q <= zt; q++) occ.fill(0, q * S, (q + 1) * S);
  let removed = 0; for (let i = 0; i < keepTop.length; i++) if (keepTop[i] > 0.5 && occ[(zb + 1) * S + i] < 0.5) removed++;
  return { removed, zu: zu * vs, top: ext * vs };
}
function extendByMotion(occ, capOcc, nx, ny, vs, ox, oy, oz, z, zt, frames, zb = z) {
  const mf = MOTION_OPT.frac;
  const minV = MOTION_OPT.minGroup ?? 4;
  const F = frames.filter((f) => f.motion);
  if (F.length < minV) return z;
  const S = nx * ny, ev = new Uint8Array(S), minVox = Math.max(3, Math.round(15 / (vs * vs))); // ≥ ~15 мм² сечения — для тонких деталей наверху (пальцы, волосы)
  let top = z, gap = 0;
  const lay = [];
  for (let q = z + 1; q <= zt; q++) {
    const Z = oz + q * vs; ev.fill(0); let cnt = 0;
    const prev = q === z + 1 ? null : lay[lay.length - 1];
    for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) {
      const i = y * nx + x; if (capOcc[(q - z - 1) * S + i] < 0.5 || occ[zb * S + i] < 0.5) continue; // только над основой
      const X = ox + x * vs, Y = oy + y * vs; let mv = 0, so = 0;
      for (const f of F) {
        const R = f.R, t = f.t, K = f.K, cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) continue;
        const u = (K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx) | 0, v = (K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy) | 0;
        if (u < 0 || v < 0 || u >= f.w || v >= f.h) continue;
        const j = v * f.w + u, m = f.mask[j];
        if (m === 2) { mv++; so++; continue; } // уверенный «предмет» на фоне листа — тоже улика
        if (m !== 1 && m !== 3) continue;
        so++; if (f.motion[j]) mv++;
      }
      if (so >= Math.max(3, Math.floor(minV / 2)) && mv >= Math.max(2, Math.floor(minV / 2)) && mv >= mf * so) { ev[i] = 1; cnt++; }
    }
    if (cnt < minVox) { if (++gap > Math.round(8 / vs)) break; lay.push(lay.length ? lay[lay.length - 1] : null); continue; }
    gap = 0; top = q;
    // улики → сплошное сечение: расширение на 2 вокселя (центр силуэта всегда закрыт предметом и не «движется»)
    // и заливка дыр по выпуклой оболочке строк/столбцов
    const d = dilate2(ev, nx, ny, 2), fill = new Uint8Array(S);
    for (let y = 0; y < ny; y++) { let a = -1, b = -1; for (let x = 0; x < nx; x++) if (d[y * nx + x]) { if (a < 0) a = x; b = x; } for (let x = a; a >= 0 && x <= b; x++) fill[y * nx + x] = 1; }
    for (let x = 0; x < nx; x++) { let a = -1, b = -1; for (let y = 0; y < ny; y++) if (d[y * nx + x]) { if (a < 0) a = y; b = y; } for (let y = 0; y < ny; y++) if (fill[y * nx + x] && (y < a || y > b)) fill[y * nx + x] = 0; }
    lay.push(fill);
  }
  if (top <= z) return z;
  // слои полосы над основой — не шире основы; выше каждый слой ⊆ слой ниже (вверх не расширяется) и ⊆ улики слоя
  for (let q = zb + 1; q <= z; q++) for (let i = 0; i < S; i++) if (occ[zb * S + i] < 0.5) occ[q * S + i] = 0;
  for (let q = z + 1; q <= top; q++) {
    const L = lay[q - z - 1];
    for (let i = 0; i < S; i++) occ[q * S + i] = occ[(q - 1) * S + i] > 0.5 && (!L || L[i]) ? 1 : 0;
  }
  return top;
}
function dilate2(a, nx, ny, r) {
  let cur = a;
  for (let k = 0; k < r; k++) {
    const o = new Uint8Array(nx * ny);
    for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) { const i = y * nx + x; o[i] = cur[i] || (x > 0 && cur[i - 1]) || (x < nx - 1 && cur[i + 1]) || (y > 0 && cur[i - nx]) || (y < ny - 1 && cur[i + nx]) ? 1 : 0; }
    cur = o;
  }
  return cur;
}
// морфология кубом радиуса r (разделимые проходы по осям)
function morph(occ, nx, ny, nz, r, dilate) {
  const tmp = new Float32Array(occ.length);
  const pass = (src, dst, stride, len, idx) => {
    for (let i = 0; i < src.length; i++) {
      const c = idx(i); let v = dilate ? 0 : 1;
      for (let d = -r; d <= r; d++) { const cc = c + d; const s = cc < 0 || cc >= len ? (dilate ? 0 : 1) : src[i + d * stride]; if (dilate ? s > 0.5 : s < 0.5) { v = dilate ? 1 : 0; break; } }
      dst[i] = v;
    }
  };
  pass(occ, tmp, 1, nx, (i) => i % nx); pass(tmp, occ, nx, ny, (i) => ((i / nx) | 0) % ny); pass(occ, tmp, nx * ny, nz, (i) => (i / (nx * ny)) | 0);
  occ.set(tmp);
}
function closeGrid(occ, nx, ny, nz, r) {
  const orig = occ.slice();
  morph(occ, nx, ny, nz, r, true); morph(occ, nx, ny, nz, r, false);
  // у дна (z=0) эрозия «съедает» нижний слой — там оставляем исходное
  for (let z = 0; z < Math.min(nz, r); z++) for (let i = 0; i < nx * ny; i++) { const j = z * nx * ny + i; occ[j] = Math.max(orig[j], occ[(r * ny * nx) + i] && orig[j + 0] ? 1 : orig[j]); }
}
// пустоты, не связанные с внешним пространством, — часть предмета
function fillVoids(occ, nx, ny, nz) {
  const out = new Uint8Array(occ.length), st = new Int32Array(occ.length); let sp = 0;
  const push = (j) => { if (!out[j] && occ[j] < 0.5) { out[j] = 1; st[sp++] = j; } };
  for (let z = 0; z < nz; z++) for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) if (x === 0 || y === 0 || z === nz - 1 || x === nx - 1 || y === ny - 1) push((z * ny + y) * nx + x);
  while (sp) {
    const j = st[--sp], x = j % nx, y = ((j / nx) | 0) % ny, z = (j / (nx * ny)) | 0;
    if (x > 0) push(j - 1); if (x < nx - 1) push(j + 1); if (y > 0) push(j - nx); if (y < ny - 1) push(j + nx); if (z > 0) push(j - nx * ny); if (z < nz - 1) push(j + nx * ny);
  }
  for (let j = 0; j < occ.length; j++) if (!out[j]) occ[j] = 1;
}
// Оставляем самую большую часть, СТОЯЩУЮ НА СТОЛЕ (касается нижних ~3 мм). Висящие в воздухе куски — это
// «неизвестное» пространство над предметом (его ни один кадр не видел на фоне листа), а не предмет.
// Раньше бралась просто самая большая часть — и при большой выбранной высоте мог остаться столб, а предмет исчезал.
function keepLargest(occ, nx, ny, nz, zg = 2) {
  const lab = new Int32Array(occ.length), sizes = [0], grounded = [false];
  const stack = new Int32Array(occ.length);
  for (let i = 0; i < occ.length; i++) {
    if (occ[i] < 0.5 || lab[i]) continue;
    const L = sizes.length; let sp = 0, cnt = 0, gr = false; stack[sp++] = i; lab[i] = L;
    while (sp) {
      const j = stack[--sp]; cnt++;
      const x = j % nx, y = ((j / nx) | 0) % ny, z = (j / (nx * ny)) | 0;
      if (z < zg) gr = true;
      const nb = [x > 0 ? j - 1 : -1, x < nx - 1 ? j + 1 : -1, y > 0 ? j - nx : -1, y < ny - 1 ? j + nx : -1, z > 0 ? j - nx * ny : -1, z < nz - 1 ? j + nx * ny : -1];
      for (const q of nb) if (q >= 0 && occ[q] >= 0.5 && !lab[q]) { lab[q] = L; stack[sp++] = q; }
    }
    sizes.push(cnt); grounded.push(gr);
  }
  let best = 0; for (let l = 1; l < sizes.length; l++) if (grounded[l] && sizes[l] > sizes[best]) best = l;
  if (!best) for (let l = 1; l < sizes.length; l++) if (sizes[l] > sizes[best]) best = l;
  for (let i = 0; i < occ.length; i++) if (occ[i] >= 0.5 && lab[i] !== best) occ[i] = 0;
}

// ---------- поверхность: surface nets по сглаженному полю ----------
// «Тело вращения» (бутылка, дезодорант, ваза): ось по центрам слоёв (допускается небольшой наклон),
// радиус каждого слоя — медиана по 48 секторам. Неровности силуэтов и блики усредняются по кругу.
export function revolveGrid(G) {
  const { nx, ny, nz, vs, origin, occ } = G, NS = 48;
  const cxs = [], cys = [], ws = [];
  for (let z = 0; z < nz; z++) { let sx = 0, sy = 0, n = 0; for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) if (occ[(z * ny + y) * nx + x] > 0.5) { sx += x; sy += y; n++; } cxs.push(n ? sx / n : 0); cys.push(n ? sy / n : 0); ws.push(n); }
  // взвешенная прямая c(z) = a + b·z для обеих координат
  const fit = (c) => { let W = 0, Sz = 0, Sc = 0, Szz = 0, Szc = 0; for (let z = 0; z < nz; z++) { const w = ws[z]; W += w; Sz += w * z; Sc += w * c[z]; Szz += w * z * z; Szc += w * z * c[z]; } const d = W * Szz - Sz * Sz; const b = Math.abs(d) > 1e-9 ? (W * Szc - Sz * Sc) / d : 0; return [(Sc - b * Sz) / Math.max(W, 1e-9), Math.max(-0.3, Math.min(0.3, b))]; };
  const [ax, bx] = fit(cxs), [ay, by] = fit(cys);
  const Rz = new Float32Array(nz);
  for (let z = 0; z < nz; z++) {
    if (!ws[z]) continue;
    const cx = ax + bx * z, cy = ay + by * z, sec = new Float32Array(NS);
    for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) if (occ[(z * ny + y) * nx + x] > 0.5) {
      const dx = x - cx, dy = y - cy, r = Math.hypot(dx, dy) + 0.5, k = Math.floor(((Math.atan2(dy, dx) + Math.PI) / (2 * Math.PI)) * NS) % NS;
      if (r > sec[k]) sec[k] = r;
    }
    const srt = Array.from(sec).sort((a, b) => a - b); Rz[z] = srt[NS >> 1];
  }
  // сглаживание профиля по высоте: медиана 5, затем среднее 3
  const med = new Float32Array(nz);
  for (let z = 0; z < nz; z++) { const w = []; for (let d = -2; d <= 2; d++) { const q = z + d; if (q >= 0 && q < nz) w.push(Rz[q]); } w.sort((a, b) => a - b); med[z] = Rz[z] ? w[w.length >> 1] : 0; }
  const out = new Float32Array(occ.length);
  for (let z = 0; z < nz; z++) {
    let r = med[z], c = 1; if (z > 0 && med[z - 1]) { r += med[z - 1]; c++; } if (z < nz - 1 && med[z + 1]) { r += med[z + 1]; c++; } r = med[z] ? r / c : 0;
    if (r <= 0) continue;
    const cx = ax + bx * z, cy = ay + by * z;
    for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) if (Math.hypot(x - cx, y - cy) <= r) out[(z * ny + y) * nx + x] = 1;
  }
  return { occ: out, nx, ny, nz, vs, origin };
}
export function meshFromGrid(G, smooth = 1) {
  const { nx, ny, nz, vs, origin } = G;
  // поле с пустой рамкой (чтобы поверхность была замкнутой) + размытие
  const X = nx + 2, Y = ny + 2, Z = nz + 2, f = new Float32Array(X * Y * Z);
  for (let z = 0; z < nz; z++) for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) f[((z + 1) * Y + y + 1) * X + x + 1] = G.occ[(z * ny + y) * nx + x];
  // дно на столе: слой z=0 (рамка) повторяет первый слой — дно ровно по плоскости стола
  for (let y = 0; y < Y; y++) for (let x = 0; x < X; x++) f[y * X + x] = 0;
  let F = f;
  for (let s = 0; s < smooth; s++) F = blur3(F, X, Y, Z);
  const iso = 0.5;
  const vid = new Int32Array(X * Y * Z).fill(-1), pos = [];
  const at = (x, y, z) => F[(z * Y + y) * X + x];
  const E = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];
  const cornerOff = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
  for (let z = 0; z < Z - 1; z++) for (let y = 0; y < Y - 1; y++) for (let x = 0; x < X - 1; x++) {
    const v = cornerOff.map(([a, b, c]) => at(x + a, y + b, z + c));
    let mask = 0; for (let k = 0; k < 8; k++) if (v[k] > iso) mask |= 1 << k;
    if (mask === 0 || mask === 255) continue;
    let sx = 0, sy = 0, sz = 0, c = 0;
    for (const [a, b] of E) {
      if ((v[a] > iso) === (v[b] > iso)) continue;
      const tt = (iso - v[a]) / (v[b] - v[a]), A = cornerOff[a], Bc = cornerOff[b];
      sx += A[0] + (Bc[0] - A[0]) * tt; sy += A[1] + (Bc[1] - A[1]) * tt; sz += A[2] + (Bc[2] - A[2]) * tt; c++;
    }
    vid[(z * Y + y) * X + x] = pos.length / 3;
    // клетка (x,y,z) в рамочной сетке → мир: индекс x соответствует вокселю x-1
    pos.push(origin[0] + (x - 1 + sx / c) * vs, origin[1] + (y - 1 + sy / c) * vs, Math.max(0, origin[2] + (z - 1 + sz / c) * vs));
  }
  const idx = [];
  const V = (x, y, z) => vid[(z * Y + y) * X + x];
  for (let z = 1; z < Z - 1; z++) for (let y = 1; y < Y - 1; y++) for (let x = 1; x < X - 1; x++) {
    const a = at(x, y, z) > iso;
    // ребро по x: (x,y,z)-(x+1,y,z), клетки вокруг: (x, y-1..y, z-1..z)
    if (x < X - 1 && a !== (at(x + 1, y, z) > iso)) quad(V(x, y - 1, z - 1), V(x, y, z - 1), V(x, y, z), V(x, y - 1, z), a);
    if (y < Y - 1 && a !== (at(x, y + 1, z) > iso)) quad(V(x - 1, y, z - 1), V(x - 1, y, z), V(x, y, z), V(x, y, z - 1), a);
    if (z < Z - 1 && a !== (at(x, y, z + 1) > iso)) quad(V(x - 1, y - 1, z), V(x, y - 1, z), V(x, y, z), V(x - 1, y, z), a);
  }
  function quad(a, b, c, d, flip) {
    if (a < 0 || b < 0 || c < 0 || d < 0) return;
    if (flip) idx.push(a, b, c, a, c, d); else idx.push(a, c, b, a, d, c);
  }
  return { pos: new Float32Array(pos), idx: new Uint32Array(idx) };
}
function blur3(f, X, Y, Z) {
  const k = [0.25, 0.5, 0.25];
  let a = f, b = new Float32Array(f.length);
  for (let axis = 0; axis < 3; axis++) {
    const st = axis === 0 ? 1 : axis === 1 ? X : X * Y, n = axis === 0 ? X : axis === 1 ? Y : Z;
    for (let i = 0; i < a.length; i++) {
      const c = axis === 0 ? i % X : axis === 1 ? ((i / X) | 0) % Y : (i / (X * Y)) | 0;
      b[i] = a[i] * k[1] + (c > 0 ? a[i - st] : 0) * k[0] + (c < n - 1 ? a[i + st] : 0) * k[2];
    }
    [a, b] = [b, a];
  }
  return a;
}

// ---------- сглаживание Таубина (без усадки) ----------
export function taubin(M, iters = 8, lam = 0.5, mu = -0.53) {
  const { pos, idx } = M, nv = pos.length / 3;
  const nbr = Array.from({ length: nv }, () => new Set());
  for (let i = 0; i < idx.length; i += 3) { const a = idx[i], b = idx[i + 1], c = idx[i + 2]; nbr[a].add(b).add(c); nbr[b].add(a).add(c); nbr[c].add(a).add(b); }
  const N = nbr.map(s => Int32Array.from(s));
  const tmp = new Float32Array(pos.length);
  const step = (f) => {
    for (let v = 0; v < nv; v++) {
      const nb = N[v]; if (!nb.length) { tmp[v * 3] = pos[v * 3]; tmp[v * 3 + 1] = pos[v * 3 + 1]; tmp[v * 3 + 2] = pos[v * 3 + 2]; continue; }
      let sx = 0, sy = 0, sz = 0; for (const q of nb) { sx += pos[q * 3]; sy += pos[q * 3 + 1]; sz += pos[q * 3 + 2]; }
      const k = 1 / nb.length;
      tmp[v * 3] = pos[v * 3] + f * (sx * k - pos[v * 3]); tmp[v * 3 + 1] = pos[v * 3 + 1] + f * (sy * k - pos[v * 3 + 1]);
      const z = pos[v * 3 + 2] + f * (sz * k - pos[v * 3 + 2]);
      tmp[v * 3 + 2] = pos[v * 3 + 2] < 0.05 ? 0 : Math.max(0, z); // дно остаётся на столе
    }
    pos.set(tmp);
  };
  for (let i = 0; i < iters; i++) { step(lam); step(mu); }
  return M;
}
export function computeNormals(M) {
  const { pos, idx } = M, n = new Float32Array(pos.length);
  for (let i = 0; i < idx.length; i += 3) {
    const a = idx[i] * 3, b = idx[i + 1] * 3, c = idx[i + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2], vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    for (const j of [a, b, c]) { n[j] += nx; n[j + 1] += ny; n[j + 2] += nz; }
  }
  for (let i = 0; i < n.length; i += 3) { const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1; n[i] /= l; n[i + 1] /= l; n[i + 2] /= l; }
  M.nrm = n; return M;
}

// ---------- карта глубины сетки для кадра (видимость) ----------
export function depthMap(M, f, w, h) {
  const { pos, idx } = M, K = f.K, sx = w / f.w, sy = h / f.h, R = f.R, t = f.t;
  const zb = new Float32Array(w * h).fill(1e9);
  const P = new Float32Array(pos.length);
  for (let i = 0; i < pos.length; i += 3) {
    const X = pos[i], Y = pos[i + 1], Z = pos[i + 2];
    const cz = R[6] * X + R[7] * Y + R[8] * Z + t[2];
    P[i] = (K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx) * sx; P[i + 1] = (K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy) * sy; P[i + 2] = cz;
  }
  for (let i = 0; i < idx.length; i += 3) {
    const a = idx[i] * 3, b = idx[i + 1] * 3, c = idx[i + 2] * 3;
    const x0 = P[a], y0 = P[a + 1], x1 = P[b], y1 = P[b + 1], x2 = P[c], y2 = P[c + 1];
    const minx = Math.max(0, Math.floor(Math.min(x0, x1, x2))), maxx = Math.min(w - 1, Math.ceil(Math.max(x0, x1, x2)));
    const miny = Math.max(0, Math.floor(Math.min(y0, y1, y2))), maxy = Math.min(h - 1, Math.ceil(Math.max(y0, y1, y2)));
    const den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2); if (Math.abs(den) < 1e-9) continue;
    for (let y = miny; y <= maxy; y++) for (let x = minx; x <= maxx; x++) {
      const px = x + 0.5, py = y + 0.5;
      const l0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / den, l1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / den, l2 = 1 - l0 - l1;
      if (l0 < -0.01 || l1 < -0.01 || l2 < -0.01) continue;
      const z = l0 * P[a + 2] + l1 * P[b + 2] + l2 * P[c + 2];
      const j = y * w + x; if (z < zb[j]) zb[j] = z;
    }
  }
  return zb;
}

// ---------- цвета вершин ----------
// frames: [{w,h,rgba,K,R,t}] (можно в большем разрешении, чем маски)
export function colorize(M, frames, onProgress) {
  const { pos, nrm } = M, nv = pos.length / 3;
  const acc = new Float32Array(nv * 4), mean = new Float32Array(nv * 3);
  const pass = (second) => {
    acc.fill(0);
    frames.forEach((f, fi) => {
      const dw = Math.min(320, f.w), dh = Math.round(f.h * dw / f.w);
      const zb = depthMap(M, f, dw, dh), R = f.R, t = f.t, K = f.K;
      const C = [-(R[0] * t[0] + R[3] * t[1] + R[6] * t[2]), -(R[1] * t[0] + R[4] * t[1] + R[7] * t[2]), -(R[2] * t[0] + R[5] * t[1] + R[8] * t[2])];
      for (let v = 0; v < nv; v++) {
        const X = pos[v * 3], Y = pos[v * 3 + 1], Z = pos[v * 3 + 2];
        let vx = C[0] - X, vy = C[1] - Y, vz = C[2] - Z; const vl = Math.hypot(vx, vy, vz); vx /= vl; vy /= vl; vz /= vl;
        const cosA = vx * nrm[v * 3] + vy * nrm[v * 3 + 1] + vz * nrm[v * 3 + 2];
        if (cosA < 0.2) continue;
        const cz = R[6] * X + R[7] * Y + R[8] * Z + t[2];
        const u = K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx, w = K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy;
        if (u < 1 || w < 1 || u >= f.w - 2 || w >= f.h - 2) continue;
        const du = Math.min(dw - 1, (u * dw / f.w) | 0), dv = Math.min(dh - 1, (w * dh / f.h) | 0);
        let zmin = 1e9; for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) { const x = du + a, y = dv + b; if (x >= 0 && y >= 0 && x < dw && y < dh) zmin = Math.min(zmin, zb[y * dw + x]); }
        if (cz > zmin * 1.004 + 1.5) continue; // заслонено
        const x0 = u | 0, y0 = w | 0, fx = u - x0, fy = w - y0, i = (y0 * f.w + x0) * 4, s = f.w * 4, px = f.rgba;
        let wt = cosA * cosA;
        const col = [0, 1, 2].map(c => (px[i + c] * (1 - fx) + px[i + 4 + c] * fx) * (1 - fy) + (px[i + s + c] * (1 - fx) + px[i + s + 4 + c] * fx) * fy);
        if (second) { const d = Math.abs(col[0] - mean[v * 3]) + Math.abs(col[1] - mean[v * 3 + 1]) + Math.abs(col[2] - mean[v * 3 + 2]); if (d > 60) wt *= 0.05; }
        acc[v * 4] += col[0] * wt; acc[v * 4 + 1] += col[1] * wt; acc[v * 4 + 2] += col[2] * wt; acc[v * 4 + 3] += wt;
      }
      if (onProgress) onProgress(((second ? 1 : 0) + (fi + 1) / frames.length) / 2);
    });
    for (let v = 0; v < nv; v++) { const W = acc[v * 4 + 3]; if (W > 0) for (let c = 0; c < 3; c++) mean[v * 3 + c] = acc[v * 4 + c] / W; else mean[v * 3] = mean[v * 3 + 1] = mean[v * 3 + 2] = -1; }
  };
  pass(false); pass(true);
  // вершины без цвета (дно, щели) — от соседей
  const col = new Uint8Array(nv * 3), has = new Uint8Array(nv);
  for (let v = 0; v < nv; v++) if (mean[v * 3] >= 0) { has[v] = 1; for (let c = 0; c < 3; c++) col[v * 3 + c] = Math.round(mean[v * 3 + c]); }
  const nbr = Array.from({ length: nv }, () => []);
  for (let i = 0; i < M.idx.length; i += 3) { const a = M.idx[i], b = M.idx[i + 1], c = M.idx[i + 2]; nbr[a].push(b, c); nbr[b].push(a, c); nbr[c].push(a, b); }
  for (let it = 0; it < 60; it++) {
    let changed = 0;
    for (let v = 0; v < nv; v++) {
      if (has[v]) continue;
      let s0 = 0, s1 = 0, s2 = 0, n = 0; for (const q of nbr[v]) if (has[q] === 1) { s0 += col[q * 3]; s1 += col[q * 3 + 1]; s2 += col[q * 3 + 2]; n++; }
      if (n) { col[v * 3] = s0 / n; col[v * 3 + 1] = s1 / n; col[v * 3 + 2] = s2 / n; has[v] = 2; changed++; }
    }
    for (let v = 0; v < nv; v++) if (has[v] === 2) has[v] = 1;
    if (!changed) break;
  }
  for (let v = 0; v < nv; v++) if (!has[v]) col[v * 3] = col[v * 3 + 1] = col[v * 3 + 2] = 128;
  M.col = col; return M;
}
