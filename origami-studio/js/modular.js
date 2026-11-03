export function buildModulePlan({ count = 12, rows = 1, paperWidth = 40, paperHeight = 60, pitch = 18 } = {}) {
  count = Math.round(Number(count)); rows = Math.round(Number(rows));
  paperWidth = Number(paperWidth); paperHeight = Number(paperHeight); pitch = Number(pitch);
  if (!(count >= 6 && count <= 48)) throw new Error('Модулей в ряду: от 6 до 48');
  if (!(rows >= 1 && rows <= 8)) throw new Error('Рядов: от 1 до 8');
  if (!(paperWidth > 0 && paperHeight > 0 && pitch > 0)) throw new Error('Размеры должны быть положительными');
  const radiusMm = count * pitch / (2 * Math.PI);
  const planRows = Array.from({ length: rows }, (_, row) => ({
    row: row + 1,
    units: count,
    orientation: row % 2 ? 'перевёрнутый' : 'прямой',
    phase: row % 2 ? 0.5 : 0,
    radiusMm: radiusMm + row * pitch * .45,
  }));
  return {
    format: 'origami-studio-module-layout', version: 1, technique: 'Golden Venture',
    verification: 'layout-only; foldability, insertion and strength are not verified',
    paper: { widthMm: paperWidth, heightMm: paperHeight, count: count * rows },
    rows: planRows,
    totals: {
      units: count * rows, plannedTabInsertions: count * rows * 2,
      baseRadiusMm: radiusMm, baseDiameterMm: radiusMm * 2,
      paperAreaCm2: paperWidth * paperHeight * count * rows / 100,
    },
  };
}

export function modulePlanSvg(plan) {
  const size = 360, cx = 180, cy = 150;
  const maxRadius = Math.max(...plan.rows.map(row => row.radiusMm));
  const scale = Math.min(105 / maxRadius, 2.5);
  const rings = plan.rows.map(row => {
    const r = row.radiusMm * scale;
    const items = Array.from({ length: row.units }, (_, i) => {
      const angle = (i + row.phase) / row.units * Math.PI * 2 - Math.PI / 2;
      const x = cx + Math.cos(angle) * r, y = cy + Math.sin(angle) * r;
      const deg = angle * 180 / Math.PI + 90;
      const color = row.row % 2 ? '#b7cfc0' : '#e4a284';
      return `<g transform="translate(${x.toFixed(2)} ${y.toFixed(2)}) rotate(${deg.toFixed(2)})"><path d="M0 -10 L7 8 L0 5 L-7 8 Z" fill="${color}" stroke="#52695a" stroke-width=".7"/><path d="M0 -7V4" stroke="#fff8ed" stroke-width=".8"/></g>`;
    }).join('');
    return `<g data-row="${row.row}"><circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#cbd3c7" stroke-width=".6" stroke-dasharray="2 4"/>${items}</g>`;
  }).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 310" role="img" aria-label="Схема компоновки модулей по рядам">${rings}<text x="180" y="294" text-anchor="middle" fill="#7d887e" font-family="Arial,sans-serif" font-size="9">Вид сверху · схема позиций, не форма сложенного модуля</text></svg>`;
}

export function moduleBomHtml(plan) {
  return `<table><thead><tr><th>РЯД</th><th>ДЕТАЛЕЙ</th><th>ОРИЕНТАЦИЯ</th><th>СМЕЩЕНИЕ</th><th>РАДИУС</th><th>ДЕЙСТВИЕ</th></tr></thead><tbody>${plan.rows.map(row => `<tr><td>${row.row}</td><td>${row.units}</td><td>${row.orientation}</td><td>${row.phase ? '½ модуля' : '—'}</td><td>${row.radiusMm.toFixed(1)} мм</td><td>${row.row === 1 ? 'Замкнуть кольцо' : 'Вставлять выступы в два модуля ниже'}</td></tr>`).join('')}</tbody></table>`;
}
