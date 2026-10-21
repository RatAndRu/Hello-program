// Объём — печатный коврик: геометрия, словарь меток, отрисовка (печать и «модель» для масок).
// Мировые координаты коврика: начало в центре круга, X вправо, Y «вперёд» (к верху листа), Z вверх, мм.

// ---------- словарь меток 4×4 бит (рамка 6×6 клеток) ----------
const rotCW = (code) => { // поворот сетки 4×4 на 90° по часовой: new[r][c] = old[3-c][r]
  let o = 0;
  for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) if (code >> ((3 - c) * 4 + r) & 1) o |= 1 << (r * 4 + c);
  return o;
};
const pop = (x) => { let n = 0; while (x) { n += x & 1; x >>>= 1; } return n; };
function buildDict(n, minD) {
  const out = [];
  let s = 12345;
  const order = [...Array(65536).keys()];
  for (let i = order.length - 1; i > 0; i--) { s = (s * 1103515245 + 12345) >>> 0; const j = s % (i + 1); [order[i], order[j]] = [order[j], order[i]]; }
  for (const c of order) {
    const p = pop(c); if (p < 5 || p > 11) continue;
    const r1 = rotCW(c), r2 = rotCW(r1), r3 = rotCW(r2);
    if (pop(c ^ r1) < minD || pop(c ^ r2) < minD || pop(c ^ r3) < minD) continue; // ориентация должна читаться однозначно
    let ok = true;
    for (const o of out) for (const r of o.rot) if (pop(c ^ r) < minD) { ok = false; break; }
    if (!ok) continue;
    out.push({ code: c, rot: [c, r1, r2, r3] });
    if (out.length >= n) break;
  }
  return out;
}
export const DICT = buildDict(24, 5);
export const N_RING = 16;

// ---------- раскладка ----------
// size: 'A4' (210×297) или 'A3' (тот же рисунок ×√2). Всё в мм.
export function matLayout(size = 'A4') {
  const k = size === 'A3' ? Math.SQRT2 : 1;
  const W = 210 * k, H = 297 * k, cu = W / 2, cv = H / 2;
  const toSheet = (X, Y) => [cu + X, cv - Y];
  const markers = [];
  const add = (id, X, Y, s, ang) => { // ang — куда смотрит «верх» метки (рад, от оси X)
    const up = [Math.cos(ang), Math.sin(ang)], rt = [Math.sin(ang), -Math.cos(ang)], h = s / 2;
    const P = (a, b) => [X + h * (a * rt[0] + b * up[0]), Y + h * (a * rt[1] + b * up[1])];
    markers.push({ id, X, Y, s, ang, corners: [P(-1, 1), P(1, 1), P(1, -1), P(-1, -1)] }); // TL TR BR BL
  };
  const Rr = 85 * k, s = 20 * k;
  for (let i = 0; i < N_RING; i++) { const a = Math.PI / 2 - i * 2 * Math.PI / N_RING; add(i, Rr * Math.cos(a), Rr * Math.sin(a), s, a); }
  const sb = 18 * k, bu = 20 * k, bv = 24 * k;
  add(16, -cu + bu, cv - bv, sb, Math.PI / 2); add(17, cu - bu, cv - bv, sb, Math.PI / 2);
  add(18, -cu + bu, -cv + bv, sb, Math.PI / 2); add(19, cu - bu, -cv + bv, sb, Math.PI / 2);
  return { size, k, W, H, cu, cv, toSheet, markers, ringR: Rr, discR: 66 * k, cutR: 100 * k, objR: 62 * k };
}

// ---------- примитивы рисунка (общие для печати и для модели) ----------
// theme: 'light' — белый центр (для тёмных и цветных предметов), 'dark' — серый центр (для белых и светлых)
export function matPrims(L, theme = 'light') {
  const P = [], k = L.k;
  const grey = theme === 'dark' ? 90 : 255;
  P.push({ t: 'disc', c: [0, 0], r: L.discR, v: grey });
  // крапинки: известный случайный узор — по нему тень на коврике отличается от предмета
  for (const d of matDots(L)) P.push({ t: 'disc', c: [d[0], d[1]], r: d[2], v: 150 });
  for (const r of [20, 40, 60]) if (r * k < L.discR) P.push({ t: 'ring', c: [0, 0], r: r * k, w: 0.35 * k, v: theme === 'dark' ? 150 : 170 });
  P.push({ t: 'line', a: [-L.discR, 0], b: [L.discR, 0], w: 0.3 * k, v: theme === 'dark' ? 150 : 170 });
  P.push({ t: 'line', a: [0, -L.discR], b: [0, L.discR], w: 0.3 * k, v: theme === 'dark' ? 150 : 170 });
  for (let d = 0; d < 360; d += 10) {
    const a = Math.PI / 2 - d * Math.PI / 180, r0 = L.discR, r1 = L.discR + (d % 30 ? 2.5 : 4.5) * k;
    P.push({ t: 'line', a: [r0 * Math.cos(a), r0 * Math.sin(a)], b: [r1 * Math.cos(a), r1 * Math.sin(a)], w: 0.45 * k, v: 0 });
  }
  P.push({ t: 'poly', pts: [[0, L.discR + 8.5 * k], [-3 * k, L.discR + 5 * k], [3 * k, L.discR + 5 * k]], v: 0 }); // «перед»
  P.push({ t: 'ring', c: [0, 0], r: L.cutR, w: 0.3 * k, v: 140, dash: 3 * k });
  for (const m of L.markers) {
    // белое поле вокруг метки + чёрная рамка + биты
    const cell = m.s / 6, code = DICT[m.id].code;
    const C = (cx, cy) => { // клетка → мир (cx, cy — от левого верхнего угла, в клетках)
      const a = cx / 6, b = cy / 6, [tl, tr, br, bl] = m.corners;
      return [tl[0] + (tr[0] - tl[0]) * a + (bl[0] - tl[0]) * b, tl[1] + (tr[1] - tl[1]) * a + (bl[1] - tl[1]) * b];
    };
    P.push({ t: 'poly', pts: [C(-1, -1), C(7, -1), C(7, 7), C(-1, 7)], v: 255 });
    P.push({ t: 'poly', pts: [C(0, 0), C(6, 0), C(6, 6), C(0, 6)], v: 0 });
    for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) if (!(code >> (r * 4 + c) & 1)) P.push({ t: 'poly', pts: [C(c + 1, r + 1), C(c + 2, r + 1), C(c + 2, r + 2), C(c + 1, r + 2)], v: 255 });
  }
  return P;
}
export function matDots(L) {
  if (L._dots) return L._dots;
  const k = L.k, out = [], cell = 4.2 * k;
  let seed = 987654321;
  const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const nearMarker = (X, Y) => L.markers.some(m => Math.hypot(X - m.X, Y - m.Y) < m.s * 0.5 * 1.42 + m.s / 6 + 1.6 * k);
  for (let gy = -L.cutR; gy <= L.cutR; gy += cell) for (let gx = -L.cutR; gx <= L.cutR; gx += cell) {
    const X = gx + (rnd() - 0.5) * cell * 0.8, Y = gy + (rnd() - 0.5) * cell * 0.8, r = (0.75 + rnd() * 0.55) * k;
    const rr = Math.hypot(X, Y);
    if (rr > L.cutR - 2.5 * k || Math.abs(rr - L.discR - 2 * k) < 3.2 * k) continue; // не на шкале градусов
    if (nearMarker(X, Y) || rnd() < 0.18) continue;
    out.push([X, Y, r]);
  }
  L._dots = out;
  return out;
}
// области с надписями — в модели они «неизвестны» (в мм листа: u, v, w, h)
export function textRects(L) {
  const k = L.k;
  return [[40 * k, 4 * k, L.W - 80 * k, 40 * k], [40 * k, L.H - 44 * k, L.W - 80 * k, 40 * k]];
}

// ---------- растр-модель коврика (без canvas, для масок и тестов) ----------
// возвращает { g: Uint8Array яркость, unk: Uint8Array 1=неизвестно, w, h, ppm }
export function matRaster(L, theme = 'light', ppm = 2) {
  const w = Math.round(L.W * ppm), h = Math.round(L.H * ppm), g = new Uint8Array(w * h).fill(255), unk = new Uint8Array(w * h);
  const SS = 3; // суперсэмплинг краёв
  const toPx = (X, Y) => { const [u, v] = L.toSheet(X, Y); return [u * ppm, v * ppm]; };
  const paint = (inside, bb, v) => {
    const x0 = Math.max(0, Math.floor(bb[0])), x1 = Math.min(w - 1, Math.ceil(bb[2])), y0 = Math.max(0, Math.floor(bb[1])), y1 = Math.min(h - 1, Math.ceil(bb[3]));
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      let n = 0;
      for (let sy = 0; sy < SS; sy++) for (let sx = 0; sx < SS; sx++) if (inside(x + (sx + 0.5) / SS, y + (sy + 0.5) / SS)) n++;
      if (n) { const a = n / (SS * SS), i = y * w + x; g[i] = Math.round(g[i] * (1 - a) + v * a); }
    }
  };
  for (const p of matPrims(L, theme)) {
    if (p.t === 'poly') {
      const q = p.pts.map(([X, Y]) => toPx(X, Y));
      const bb = [Math.min(...q.map(a => a[0])), Math.min(...q.map(a => a[1])), Math.max(...q.map(a => a[0])), Math.max(...q.map(a => a[1]))];
      paint((x, y) => { let s = 0; for (let i = 0; i < q.length; i++) { const a = q[i], b = q[(i + 1) % q.length]; const cr = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]); if (cr > 0) s |= 1; else if (cr < 0) s |= 2; } return s !== 3; }, bb, p.v);
    } else if (p.t === 'disc' || p.t === 'ring') {
      const [cx, cy] = toPx(p.c[0], p.c[1]), R = p.r * ppm, hw = (p.w || 0) * ppm / 2, R1 = R + hw + 1;
      const dash = p.dash ? p.dash * ppm : 0;
      paint((x, y) => {
        const d = Math.hypot(x - cx, y - cy);
        if (p.t === 'disc') return d <= R;
        if (Math.abs(d - R) > hw) return false;
        if (dash) { const s = (Math.atan2(y - cy, x - cx) + Math.PI) * R; return Math.floor(s / dash) % 2 === 0; }
        return true;
      }, [cx - R1, cy - R1, cx + R1, cy + R1], p.v);
    } else if (p.t === 'line') {
      const a = toPx(...p.a), b = toPx(...p.b), hw = Math.max(0.5, p.w * ppm / 2);
      const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy || 1;
      paint((x, y) => { const t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / L2)); return Math.hypot(x - a[0] - t * dx, y - a[1] - t * dy) <= hw; },
        [Math.min(a[0], b[0]) - hw - 1, Math.min(a[1], b[1]) - hw - 1, Math.max(a[0], b[0]) + hw + 1, Math.max(a[1], b[1]) + hw + 1], p.v);
    }
  }
  for (const [u, v, rw, rh] of textRects(L)) for (let y = Math.floor(v * ppm); y < Math.min(h, (v + rh) * ppm); y++) for (let x = Math.floor(u * ppm); x < Math.min(w, (u + rw) * ppm); x++) unk[y * w + x] = 1;
  return { g, unk, w, h, ppm };
}

// ---------- печать (canvas): точный масштаб, линейка 100 мм, подсказки ----------
export function drawMatCanvas(ctx, L, theme = 'light', ppm = 300 / 25.4) {
  const k = L.k, S = (X, Y) => { const [u, v] = L.toSheet(X, Y); return [u * ppm, v * ppm]; };
  ctx.save();
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, L.W * ppm, L.H * ppm);
  const col = (v) => `rgb(${v},${v},${v})`;
  for (const p of matPrims(L, theme)) {
    ctx.setLineDash([]);
    if (p.t === 'poly') { ctx.beginPath(); p.pts.forEach(([X, Y], i) => { const [x, y] = S(X, Y); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.closePath(); ctx.fillStyle = col(p.v); ctx.fill(); }
    else if (p.t === 'disc') { const [x, y] = S(...p.c); ctx.beginPath(); ctx.arc(x, y, p.r * ppm, 0, Math.PI * 2); ctx.fillStyle = col(p.v); ctx.fill(); }
    else if (p.t === 'ring') { const [x, y] = S(...p.c); if (p.dash) ctx.setLineDash([p.dash * ppm, p.dash * ppm]); ctx.beginPath(); ctx.arc(x, y, p.r * ppm, 0, Math.PI * 2); ctx.strokeStyle = col(p.v); ctx.lineWidth = p.w * ppm; ctx.stroke(); }
    else if (p.t === 'line') { const a = S(...p.a), b = S(...p.b); ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.strokeStyle = col(p.v); ctx.lineWidth = p.w * ppm; ctx.stroke(); }
  }
  ctx.setLineDash([]);
  // подписи градусов
  ctx.fillStyle = '#000'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.font = `${3 * k * ppm}px sans-serif`;
  for (let d = 0; d < 360; d += 30) { if (d === 0) continue; const a = Math.PI / 2 - d * Math.PI / 180, r = L.discR - 4 * k; const [x, y] = S(r * Math.cos(a), r * Math.sin(a)); ctx.fillStyle = theme === 'dark' ? '#ddd' : '#555'; ctx.fillText(d + '°', x, y); }
  // верхняя полоса: название и линейка
  const mm = (v) => v * ppm, cx = L.W / 2;
  ctx.fillStyle = '#000';
  ctx.font = `bold ${mm(4.6 * k)}px sans-serif`; ctx.fillText('Объём — коврик для 3D-съёмки · ' + L.size, mm(cx), mm(11 * k));
  ctx.font = `${mm(3 * k)}px sans-serif`; ctx.fillText('Печатать в масштабе 100% («Фактический размер»), без «Вписать в страницу»', mm(cx), mm(18 * k));
  const ry = 30 * k, rx0 = cx - 50;
  ctx.lineWidth = mm(0.3); ctx.strokeStyle = '#000';
  ctx.beginPath(); ctx.moveTo(mm(rx0), mm(ry)); ctx.lineTo(mm(rx0 + 100), mm(ry)); ctx.stroke();
  for (let i = 0; i <= 100; i += 5) { ctx.beginPath(); ctx.moveTo(mm(rx0 + i), mm(ry)); ctx.lineTo(mm(rx0 + i), mm(ry - (i % 10 ? 1.5 : 3))); ctx.stroke(); }
  ctx.font = `${mm(2.8 * k)}px sans-serif`; ctx.fillText('ровно 100 мм — проверь линейкой', mm(cx), mm(ry + 4 * k));
  // нижняя полоса: подсказки
  const tips = ['Предмет — в центр круга. Метки не закрывать, лист не мять и не сгибать.', 'Для столика — вырежи круг по пунктиру и приклей. Для съёмки с рук — положи лист на стол.', L.size === 'A4' ? 'Предмет до ~12 см в ширину. Для крупных — печатай A3.' : 'Предмет до ~17 см в ширину.'];
  ctx.font = `${mm(2.8 * k)}px sans-serif`;
  tips.forEach((t, i) => ctx.fillText(t, mm(cx), mm(L.H - (34 - i * 6) * k)));
  ctx.restore();
}
