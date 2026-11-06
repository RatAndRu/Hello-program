/** Итоговая толщина линии в CSS px; LineMaterial получает половину в device px. */
// Экранная толщина ребра. Тоньше 2 px экранный quad покрывает лишь часть
// пикселя: линия становится бледной «рябью» и кажется пунктиром. 2 px даёт
// сплошное непрозрачное ядро, а мягкую кромку — MSAA буфера.
export const TOPOLOGY_STROKE_PX = 2.0;

export function topologyLineMaterialWidth(pixelRatio = 1) {
  const ratio = Math.max(Number(pixelRatio) || 1, 0.5);
  // r160 LineMaterial сдвигает обе стороны полосы на ±linewidth.
  return (TOPOLOGY_STROKE_PX * ratio) / 2;
}

/**
 * Уникальные рёбра для экранного полигонажа.
 *
 * WireframeGeometry выдаёт по три ребра на треугольник: общее ребро двух граней
 * встречается дважды. Здесь вершины не свариваются по допуску и координаты не
 * меняются — совпадают только буквально равные Float32-вершины исходной сетки.
 * Это убирает повторный overdraw в местах схождения рёбер и уменьшает буфер.
 */
export function uniqueTopologyPositions(source) {
  const data = source || [];
  const vertexIds = new Map();
  const edgeIds = new Set();
  const positions = [];
  let nextVertex = 0;

  function vertexId(offset) {
    const x = data[offset], y = data[offset + 1], z = data[offset + 2];
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return -1;
    // String(-0) === String(0): знак нуля не создаёт фиктивную вершину.
    const key = `${x},${y},${z}`;
    let id = vertexIds.get(key);
    if (id === undefined) {
      id = nextVertex++;
      vertexIds.set(key, id);
    }
    return id;
  }

  for (let offset = 0; offset + 5 < data.length; offset += 6) {
    const a = vertexId(offset), b = vertexId(offset + 3);
    if (a < 0 || b < 0 || a === b) continue;
    const lo = Math.min(a, b), hi = Math.max(a, b);
    const edge = `${lo}:${hi}`;
    if (edgeIds.has(edge)) continue;
    edgeIds.add(edge);
    for (let i = 0; i < 6; i += 1) positions.push(data[offset + i]);
  }
  return Float32Array.from(positions);
}
