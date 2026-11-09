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

/**
 * Рёбра, которые видно всегда: границы перепада нормали, а не пиксельный поиск.
 *
 * Экранный контур ищет перепад по нормалям и глубине в пределах нескольких
 * пикселей, поэтому ребро тоньше пикселя, ребро под малым углом к экрану или
 * ребро на дальней сцене может «пропасть». Здесь ребро берётся из самой сетки
 * на CPU: треугольники сшиваются по совпадающим координатам, каждому ребру
 * считаются две соседние грани, и в ответ попадают только те, где двугранный
 * угол больше порога. Такие рёбра не зависят от ракурса и рисуются
 * LineSegments2 — стабильная толщина без лесенок.
 *
 * Координаты не сдвигаются и не свариваются по допуску: вершины считаются
 * общими, только если совпали после квантования на долю габарита, что убирает
 * ошибки Float32 в раскрое одной поверхности.
 */
export function creaseEdgePositions(source, angleDeg = 32, options = {}) {
  const array = source?.attributes?.position?.array || source?.positions || source;
  const index = source?.index?.array || source?.index || null;
  const data = array || [];
  const triangles = index ? Math.floor(index.length / 3) : Math.floor(data.length / 9);
  if (triangles < 1) return new Float32Array(0);
  const openEdges = options.openEdges !== false;

  let minX = Infinity, minY = Infinity, minZ = Infinity;
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
  for (let i = 0; i + 2 < data.length; i += 3) {
    const x = data[i], y = data[i + 1], z = data[i + 2];
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
    if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
  }
  const diag = Math.hypot(maxX - minX, maxY - minY, maxZ - minZ);
  // Допуск сварки — 1e-5 от габарита: у детали 1300 мм это 0.013 мм, у
  // детали 5 мм — 0.00005 мм. Меньше шума Float32, больше настоящего зазора.
  const eps = Math.max(diag * 1e-5, 1e-7);

  const ids = new Map();
  const points = [];
  const vertexOf = (offset) => {
    const x = data[offset], y = data[offset + 1], z = data[offset + 2];
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return -1;
    const key = `${Math.round(x / eps)},${Math.round(y / eps)},${Math.round(z / eps)}`;
    let id = ids.get(key);
    if (id === undefined) {
      id = points.length / 3;
      ids.set(key, id);
      points.push(x, y, z);
    }
    return id;
  };

  const edges = new Map();
  const addEdge = (a, b, nx, ny, nz) => {
    const lo = Math.min(a, b), hi = Math.max(a, b);
    const key = `${lo}:${hi}`;
    let record = edges.get(key);
    if (!record) {
      record = { a: lo, b: hi, nx: 0, ny: 0, nz: 0, faces: 0 };
      edges.set(key, record);
    }
    record.nx += nx; record.ny += ny; record.nz += nz;
    record.faces += 1;
  };

  for (let t = 0; t < triangles; t += 1) {
    const i0 = index ? index[t * 3] : t * 3;
    const i1 = index ? index[t * 3 + 1] : t * 3 + 1;
    const i2 = index ? index[t * 3 + 2] : t * 3 + 2;
    const a = vertexOf(i0 * 3), b = vertexOf(i1 * 3), c = vertexOf(i2 * 3);
    if (a < 0 || b < 0 || c < 0 || a === b || b === c || a === c) continue;
    const ax = points[a * 3], ay = points[a * 3 + 1], az = points[a * 3 + 2];
    const bx = points[b * 3], by = points[b * 3 + 1], bz = points[b * 3 + 2];
    const cx = points[c * 3], cy = points[c * 3 + 1], cz = points[c * 3 + 2];
    const ux = bx - ax, uy = by - ay, uz = bz - az;
    const vx = cx - ax, vy = cy - ay, vz = cz - az;
    let nx = uy * vz - uz * vy;
    let ny = uz * vx - ux * vz;
    let nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz);
    if (!(len > 0)) continue;                 // вырожденный треугольник
    nx /= len; ny /= len; nz /= len;
    addEdge(a, b, nx, ny, nz);
    addEdge(b, c, nx, ny, nz);
    addEdge(c, a, nx, ny, nz);
  }

  const threshold = Math.cos(Math.max(0, Math.min(179.9, Number(angleDeg))) * Math.PI / 180);
  const out = [];
  edges.forEach((record) => {
    if (record.faces < 2) {
      if (!openEdges) return;
    } else {
      // У сшитых граней нормали накапливаются; нормируем сумму и сравниваем
      // косинус угла между гранями с порогом. Общая диагональ двух
      // компланарных треугольников даёт cos = 1 и в ответ не попадает.
      // |n1 + n2|² = 2 + 2·cos(угол), значит cos = |s|²/2 − 1.
      const sum = record.nx * record.nx + record.ny * record.ny + record.nz * record.nz;
      const cos = Math.max(-1, Math.min(1, sum / 2 - 1));
      if (cos > threshold) return;
    }
    out.push(points[record.a * 3], points[record.a * 3 + 1], points[record.a * 3 + 2],
      points[record.b * 3], points[record.b * 3 + 1], points[record.b * 3 + 2]);
  });
  return Float32Array.from(out);
}
