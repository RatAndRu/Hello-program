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
        if (diff < Math.max(14, 0.11 * pred) && chroma < 0.13) { mask[i] = 0; plain[i] = 1; continue; }
        if (diff > Math.max(40, 0.3 * pred) || chroma > 0.3) { mask[i] = 2; continue; }
        continue;
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
      for (let i = 0; i < n; i++) if (!inCyl[i] && des[i] < 0) { vis[i] = 1; st[sp++] = i; }
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
  return { mask, stats: { ok: true, rho, bgFrac: nb / n, enclosed, plate: PL ? { shift: PL.shift, agree: PL.agree } : null } };
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
  for (let z = 0; z < nz; z++) {
    const Z = oz + z * vs;
    for (let y = 0; y < ny; y++) {
      const Y = oy + y * vs;
      for (let x = 0; x < nx; x++) {
        const X = ox + x * vs;
        if (X * X + Y * Y > box.Rb * box.Rb) continue;
        let bg = 0, weak = 0, seen = 0, left = F.length, tbg = 0, tseen = 0;
        for (let k = 0; k < F.length; k++, left--) {
          const f = F[k], R = f.R, t = f.t, K = f.K;
          const cz = R[6] * X + R[7] * Y + R[8] * Z + t[2]; if (cz <= 1) continue;
          const u = (K.fx * (R[0] * X + R[1] * Y + R[2] * Z + t[0]) / cz + K.cx) | 0, v = (K.fy * (R[3] * X + R[4] * Y + R[5] * Z + t[1]) / cz + K.cy) | 0;
          if (u < 0 || v < 0 || u >= f.w || v >= f.h) continue;
          const mv = f.mask[v * f.w + u]; if (mv === 4) continue;
          seen++;
          if (mv === 0) bg++; else if (mv === 3) weak++;
          if (f.trusted) { tseen++; if (mv === 0) tbg++; }
          // досрочно: уже точно вырезан (даже если все оставшиеся кадры увидят точку)
          if (!few && bg >= 2 && bg >= frac * (seen + left - 1)) break;
        }
        const need = few ? 1 : Math.max(2, Math.ceil(frac * seen));
        // «Доверенные» кадры (предмет целиком на листе, силуэт замкнут фоном коврика) голосуют ещё и между собой:
        // их «фон» не перевешивается «неизвестно» из низких ракурсов (тень, край листа) — так срезается шапка.
        const trustCut = tseen >= 3 && tbg >= Math.max(2, Math.ceil(tfrac * tseen));
        occ[(z * ny + y) * nx + x] = trustCut || carveVote(bg, weak, seen, frac, few, opt.weakMaj) ? 0 : 1;
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
  const capTrim = opt.capTrim === false ? 0 : trimCap(occ, nx, ny, nz, vs, box.Rb, ox, oy, zg);
  if (capTrim) keepLargest(occ, nx, ny, nz, zg);
  // закрытие: заполняет мелкие ямки и щели от бликов; затем заливаем пустоты внутри
  const cr = opt.close ?? Math.max(1, Math.round(1.2 / vs));
  if (cr > 0) closeGrid(occ, nx, ny, nz, cr);
  fillVoids(occ, nx, ny, nz);
  return { occ, nx, ny, nz, vs, origin: [ox, oy, oz], capTrim: capTrim * vs, Rb: box.Rb, Hb: box.Hb };
}
// после пересечения с «низом»: убрать обрывки (оставить стоящее на столе) и залить пустоты
export function cleanGrid(G) { const zg = Math.max(1, Math.ceil(3 / G.vs)); keepLargest(G.occ, G.nx, G.ny, G.nz, zg); fillVoids(G.occ, G.nx, G.ny, G.nz); return G; }
function trimCap(occ, nx, ny, nz, vs, Rb, ox, oy, zg) {
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
  return zt - z;
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
