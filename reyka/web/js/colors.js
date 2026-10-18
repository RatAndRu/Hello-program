// Цвета и краски: определение, смешивание, подбор смеси. Без ИИ — только колориметрия.
//
// Смешивание красок — НЕ среднее RGB (синий + жёлтый дали бы серый). Краски поглощают свет,
// поэтому используется модель Кубелки — Мунка: у каждой краски по каналу есть отношение
// поглощения к рассеянию K/S = (1 − R)² / 2R; у смеси K/S — взвешенная сумма, а цвет
// получается обратно из K/S. Так синий + жёлтый дают зелёный, красный + синий — тёмно-фиолетовый.
// Модель приближённая: настоящие пигменты различаются «силой» (насколько краска забивает
// другие) — её можно задать у каждой краски.

export const hexToRgb = (h) => { const s = String(h).replace('#', ''); const v = s.length === 3 ? s.split('').map(c => c + c).join('') : s; return [0, 2, 4].map(i => parseInt(v.slice(i, i + 2), 16) || 0); };
export const rgbToHex = (c) => '#' + c.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
const toLin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
const toSrgb = (v) => 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055);
export const rgbToLin = (c) => c.map(toLin);
export const linToRgb = (c) => c.map(v => toSrgb(Math.max(0, Math.min(1, v))));

export function rgbToLab(c) {
  const [r, g, b] = rgbToLin(c);
  let x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, y = 0.2126 * r + 0.7152 * g + 0.0722 * b, z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883;
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  x = f(x); y = f(y); z = f(z);
  return [116 * y - 16, 500 * (x - y), 200 * (y - z)];
}

// CIEDE2000: насколько глаз различает два цвета (≈1 — едва заметно, <3 — очень близко)
export function deltaE(l1, l2) {
  const [L1, a1, b1] = l1, [L2, a2, b2] = l2, rad = Math.PI / 180;
  const C1 = Math.hypot(a1, b1), C2 = Math.hypot(a2, b2), Cm = (C1 + C2) / 2;
  const G = 0.5 * (1 - Math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)));
  const a1p = a1 * (1 + G), a2p = a2 * (1 + G);
  const C1p = Math.hypot(a1p, b1), C2p = Math.hypot(a2p, b2);
  const h = (a, b) => { if (a === 0 && b === 0) return 0; const t = Math.atan2(b, a) / rad; return t < 0 ? t + 360 : t; };
  const h1p = h(a1p, b1), h2p = h(a2p, b2);
  const dLp = L2 - L1, dCp = C2p - C1p;
  let dhp = 0;
  if (C1p * C2p !== 0) { dhp = h2p - h1p; if (dhp > 180) dhp -= 360; else if (dhp < -180) dhp += 360; }
  const dHp = 2 * Math.sqrt(C1p * C2p) * Math.sin(dhp * rad / 2);
  const Lpm = (L1 + L2) / 2, Cpm = (C1p + C2p) / 2;
  let hpm = h1p + h2p;
  if (C1p * C2p !== 0) { if (Math.abs(h1p - h2p) > 180) hpm += h1p + h2p < 360 ? 360 : -360; hpm /= 2; }
  const T = 1 - 0.17 * Math.cos((hpm - 30) * rad) + 0.24 * Math.cos(2 * hpm * rad) + 0.32 * Math.cos((3 * hpm + 6) * rad) - 0.2 * Math.cos((4 * hpm - 63) * rad);
  const dTh = 30 * Math.exp(-(((hpm - 275) / 25) ** 2));
  const Rc = 2 * Math.sqrt(Cpm ** 7 / (Cpm ** 7 + 25 ** 7));
  const Sl = 1 + (0.015 * (Lpm - 50) ** 2) / Math.sqrt(20 + (Lpm - 50) ** 2), Sc = 1 + 0.045 * Cpm, Sh = 1 + 0.015 * Cpm * T;
  const Rt = -Math.sin(2 * dTh * rad) * Rc;
  return Math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh));
}
export const deltaEHex = (h1, h2) => deltaE(rgbToLab(hexToRgb(h1)), rgbToLab(hexToRgb(h2)));
export function closeness(dE) {
  if (dE < 1.5) return 'не отличить';
  if (dE < 3.5) return 'очень близко';
  if (dE < 7) return 'близко';
  if (dE < 12) return 'похоже';
  return 'приблизительно';
}

// ---- Кубелка — Мунк ----
const ksOf = (R) => { const r = Math.max(0.002, Math.min(0.998, R)); return (1 - r) * (1 - r) / (2 * r); };
const rOfKs = (ks) => 1 + ks - Math.sqrt(ks * ks + 2 * ks);
export function paintKS(hex) { return rgbToLin(hexToRgb(hex)).map(ksOf); }

// items: [{ hex, parts, strength? }] → hex смеси
export function mixHex(items) {
  let W = 0; const ks = [0, 0, 0];
  for (const it of items) {
    if (!(it.parts > 0)) continue;
    const w = it.parts * (it.strength || 1), k = paintKS(it.hex);
    for (let c = 0; c < 3; c++) ks[c] += w * k[c];
    W += w;
  }
  if (!W) return '#ffffff';
  return rgbToHex(linToRgb(ks.map(v => rOfKs(v / W))));
}

const gcd = (a, b) => (b ? gcd(b, a % b) : a);

// Подбор смеси из своих красок: перебираем одну, две и три краски в целых частях
// (до maxParts частей всего) и берём самые близкие по CIEDE2000. Чуть штрафуем за
// лишние краски — при почти равной точности лучше простой рецепт.
export function findRecipes(targetHex, paints, { maxPaints = 3, maxParts = 10, top = 4 } = {}) {
  const tLab = rgbToLab(hexToRgb(targetHex));
  const P = paints.map(p => ({ ...p, ks: paintKS(p.hex), s: p.strength || 1 }));
  const best = new Map(); // набор красок → лучший рецепт
  const tryMix = (idx, parts) => {
    let W = 0; const ks = [0, 0, 0];
    for (let j = 0; j < idx.length; j++) { const p = P[idx[j]], w = parts[j] * p.s; W += w; for (let c = 0; c < 3; c++) ks[c] += w * p.ks[c]; }
    const rgb = linToRgb(ks.map(v => rOfKs(v / W)));
    const dE = deltaE(tLab, rgbToLab(rgb));
    const score = dE + 0.7 * (idx.length - 1) + 0.012 * parts.reduce((a, b) => a + b, 0);
    const key = idx.join(',');
    const cur = best.get(key);
    if (!cur || score < cur.score) best.set(key, { score, dE, hex: rgbToHex(rgb), items: idx.map((k, j) => ({ name: P[k].name, hex: P[k].hex, parts: parts[j] })) });
  };
  const n = P.length;
  // пропорции: мелкие шаги + большие для светлых оттенков (например, 20 белил : 1 синей)
  const V2 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 30, 50].filter(v => v < maxParts * 5 + 1);
  const V3 = [1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30].filter(v => v < maxParts * 3 + 1);
  for (let i = 0; i < n; i++) tryMix([i], [1]);
  if (maxPaints >= 2) for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++)
    for (const a of V2) for (const b of V2) if (gcd(a, b) === 1) tryMix([i, j], [a, b]);
  if (maxPaints >= 3 && n <= 16) for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) for (let k = j + 1; k < n; k++)
    for (const a of V3) for (const b of V3) for (const c of V3) if (gcd(gcd(a, b), c) === 1) tryMix([i, j, k], [a, b, c]);
  return [...best.values()].sort((p, q) => p.score - q.score).slice(0, top);
}

export function recipeText(r) {
  const word = (n) => (n % 10 === 1 && n % 100 !== 11 ? 'часть' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? 'части' : 'частей');
  if (r.items.length === 1) return r.items[0].name + ' — как есть';
  return r.items.map(it => `${it.parts} ${word(it.parts)} — ${it.name}`).join(' + ');
}

// Примерное название цвета по-русски (для подписи найденного цвета)
export function colorName(hex) {
  const [r, g, b] = hexToRgb(hex).map(v => v / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), L = (mx + mn) / 2, d = mx - mn;
  const S = d === 0 ? 0 : d / (1 - Math.abs(2 * L - 1));
  let H = 0;
  if (d) { if (mx === r) H = 60 * (((g - b) / d) % 6); else if (mx === g) H = 60 * ((b - r) / d + 2); else H = 60 * ((r - g) / d + 4); if (H < 0) H += 360; }
  if (S < 0.12 || d < 0.06) return L > 0.92 ? 'белый' : L > 0.7 ? 'светло-серый' : L > 0.35 ? 'серый' : L > 0.13 ? 'тёмно-серый' : 'чёрный';
  let name;
  if (H < 15 || H >= 345) name = 'красный';
  else if (H < 40) name = L < 0.42 ? 'коричневый' : 'оранжевый';
  else if (H < 65) name = L < 0.35 ? 'оливковый' : 'жёлтый';
  else if (H < 90) name = 'салатовый';
  else if (H < 160) name = 'зелёный';
  else if (H < 190) name = 'бирюзовый';
  else if (H < 210) name = 'голубой';
  else if (H < 250) name = 'синий';
  else if (H < 290) name = 'фиолетовый';
  else name = 'малиновый';
  if ((name === 'красный' || name === 'малиновый') && L > 0.72) return 'розовый';
  if (name === 'коричневый' || name === 'оливковый') return (S < 0.3 ? 'серо-' : '') + name;
  const pre = L > 0.75 ? 'светло-' : L < 0.28 ? 'тёмно-' : S < 0.3 ? 'блёкло-' : '';
  return pre + name;
}

// Стартовые наборы (цвета примерные — лучше снять свои пипеткой с выкраски)
export const PRESET_SETS = {
  basic: { name: 'Базовый (12)', paints: [
    ['Белила', '#f4f3ee'], ['Чёрная', '#1d1d20'], ['Лимонная', '#f2e43b'], ['Кадмий жёлтый', '#f5b51f'],
    ['Охра', '#c69332'], ['Кадмий красный', '#de3f2a'], ['Краплак', '#a51f3c'], ['Ультрамарин', '#2a3a9e'],
    ['Синяя ФЦ', '#174a9a'], ['Изумрудная', '#11795a'], ['Сиена жжёная', '#8a3f1f'], ['Умбра жжёная', '#5a3b27']] },
  primary: { name: 'Три основных + белила', paints: [['Белила', '#f4f3ee'], ['Жёлтая', '#f6d21c'], ['Маджента', '#c2185b'], ['Циан', '#0f8fd0']] },
};
