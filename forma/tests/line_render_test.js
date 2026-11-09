/* Регресс: динамический clip и плотность edge-coverage для линейных стилей. */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const root = path.resolve(__dirname, '..');

async function main() {
  const { cameraClipRange, stableAngle } = await import(pathToFileURL(path.join(root, 'web/js/camera_clip.js')));
  const { edgeCoverageScale, edgeCoverageToInk, EDGE_COVERAGE_TO_INK_GLSL } = await import(
    pathToFileURL(path.join(root, 'web/js/edge_coverage.js')));
  const { TOPOLOGY_STROKE_PX, topologyLineMaterialWidth, uniqueTopologyPositions,
    creaseEdgePositions } = await import(
    pathToFileURL(path.join(root, 'web/js/topology_lines.js')));
  for (const ratio of [1, 2, 1.5]) {
    const actualCssWidth = 2 * topologyLineMaterialWidth(ratio) / ratio;
    assert(Math.abs(actualCssWidth - TOPOLOGY_STROKE_PX) < 1e-12,
      '±linewidth в LineMaterial не должен удваивать заказанную CSS-толщину');
  }

  // Два треугольника квадрата содержат шесть входных рёбер, но общая
  // диагональ должна попасть в экранный буфер один раз: четыре стороны + диагональ.
  const square = Float32Array.from([
    0, 0, 0, 1, 0, 0,
    1, 0, 0, 1, 1, 0,
    1, 1, 0, 0, 0, 0,
    1, 1, 0, 0, 0, 0, // reversed duplicate общей диагонали
    0, 0, 0, 0, 1, 0,
    0, 1, 0, 1, 1, 0,
    0, 0, 0, 0, 0, 0, // degenerate
  ]);
  const squareBefore = Array.from(square);
  const uniqueSquare = uniqueTopologyPositions(square);
  assert.strictEqual(uniqueSquare.length / 6, 5, 'общая диагональ не дублируется');
  assert.deepStrictEqual(Array.from(square), squareBefore, 'исходная геометрия не мутируется');
  assert.strictEqual(uniqueTopologyPositions([0, 0, 0, 0, 0, 0]).length, 0);
  assert.strictEqual(uniqueTopologyPositions([0, 0, 0, NaN, 1, 0]).length, 0);

  // Минимальный repro центра лампы: N треугольников веера дают 3N входных
  // рёбер, но только N спиц + N сегментов обода после точной deduplication.
  const fan = [];
  const spokes = 64;
  const ring = [];
  for (let i = 0; i < spokes; i += 1) {
    const angle = (i / spokes) * Math.PI * 2;
    ring.push([Math.fround(Math.cos(angle)), Math.fround(Math.sin(angle)), 0]);
  }
  for (let i = 0; i < spokes; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % spokes];
    fan.push(0, 0, 0, x1, y1, 0, x1, y1, 0, x2, y2, 0, x2, y2, 0, 0, 0, 0);
  }
  const uniqueFan = uniqueTopologyPositions(Float32Array.from(fan));
  assert.strictEqual(fan.length / 6, spokes * 3);
  assert.strictEqual(uniqueFan.length / 6, spokes * 2,
    'повторные спицы не должны создавать центральное пятно overdraw');

  const bbox = { min: { x: -50, y: -20, z: -10 }, max: { x: 50, y: 20, z: 10 } };
  const center = { x: 0, y: 0, z: 0 };
  const positions = [
    { x: 0, y: 0, z: 5000 },
    { x: 3200, y: 1700, z: 4100 },
    { x: -700, y: 900, z: -1200 },
  ];
  for (const position of positions) {
    const before = JSON.stringify({ position, bbox });
    const range = cameraClipRange(position, bbox);
    assert(range && Number.isFinite(range.near) && Number.isFinite(range.far));
    assert(range.near > 0 && range.far > range.near, 'clip должен быть положительным и непустым');
    assert.strictEqual(JSON.stringify({ position, bbox }), before, 'входные объекты не мутируются');

    // Все углы AABB должны оставаться между плоскостями при любом ракурсе.
    const direction = [center.x - position.x, center.y - position.y, center.z - position.z];
    const length = Math.hypot(...direction);
    for (let axis = 0; axis < 3; axis += 1) direction[axis] /= length;
    for (const x of [bbox.min.x, bbox.max.x]) {
      for (const y of [bbox.min.y, bbox.max.y]) {
        for (const z of [bbox.min.z, bbox.max.z]) {
          const rel = [x - position.x, y - position.y, z - position.z];
          const depth = rel.reduce((sum, value, i) => sum + value * direction[i], 0);
          assert(depth >= range.near - 1e-7, `near обрезает угол: ${depth} < ${range.near}`);
          assert(depth <= range.far + 1e-7, `far обрезает угол: ${depth} > ${range.far}`);
        }
      }
    }
  }
  const inside = cameraClipRange({ x: 2, y: 3, z: 4 }, bbox);
  assert(inside.near > 0 && inside.far > inside.near, 'камера внутри AABB: безопасный конечный clip');
  assert.strictEqual(cameraClipRange(null, bbox), null);
  assert.strictEqual(cameraClipRange({ x: NaN, y: 0, z: 1 }, bbox), null);
  assert.strictEqual(cameraClipRange({ x: 0, y: 0, z: 1 }, null), null);
  const point = cameraClipRange(
    { x: 0, y: 0, z: 10 },
    { min: { x: 0, y: 0, z: 0 }, max: { x: 0, y: 0, z: 0 } },
  );
  assert(point.near > 0 && point.far > point.near, 'вырожденный AABB не должен ломать камеру');

  // Крен — настоящий угол вокруг направления взгляда, а ±0 в HUD — только
  // численный шум. Ноль нормализуется и по значению, и по знаку Object.is.
  for (const value of [-0, -1e-12, -0.00049, 0, 0.00049]) {
    const clean = stableAngle(value);
    assert.strictEqual(clean, 0);
    assert(!Object.is(clean, -0), 'HUD не должен получать отрицательный ноль');
    assert.strictEqual(clean.toFixed(1), '0.0');
  }
  assert.strictEqual(stableAngle(-0.01), -0.01);
  assert.strictEqual(stableAngle(12.345), 12.345);
  assert(Number.isNaN(stableAngle(NaN)));

  assert.strictEqual(edgeCoverageScale(1100, 700, 1), 2, 'DPR=1: 2×2 coverage samples');
  assert.strictEqual(edgeCoverageScale(1100, 700, 2), 1, 'DPR=2 уже содержит 2×2 samples');
  assert(Math.abs(edgeCoverageScale(1100, 700, 1.5) - 4 / 3) < 1e-12);
  assert.strictEqual(edgeCoverageScale(4000, 2000, 1), 1, 'лимит 8 Мп не увеличивает огромный кадр');
  const capped = edgeCoverageScale(1920, 1080, 1);
  assert(capped > 1 && capped < 2, 'большой кадр получает ограниченный supersampling');
  assert(Math.floor(1920 * capped) * Math.floor(1080 * capped) <= 8000000);
  assert.strictEqual(edgeCoverageScale(1100, 700, NaN), 2);
  assert.strictEqual(edgeCoverageScale(1100, 700, 0), 2, 'некорректный DPR не отключает сглаживание');

  // При 2×2 coverage один из четырёх subpixel-образцов даёт coverage=0.25.
  // Он должен стать видимой линией, а не почти белым пунктирным фрагментом.
  assert.strictEqual(edgeCoverageToInk(0), 0);
  assert.strictEqual(edgeCoverageToInk(0.025), 0);
  assert(edgeCoverageToInk(0.25) > 0.5, 'один subpixel сохраняет больше 50% чернил');
  assert.strictEqual(edgeCoverageToInk(0.45), 1);
  assert.strictEqual(edgeCoverageToInk(1), 1);
  let previousInk = 0;
  for (let i = 0; i <= 100; i += 1) {
    const ink = edgeCoverageToInk(i / 100);
    assert(ink >= previousInk && ink <= 1, 'coverage → ink монотонно и ограничено');
    previousInk = ink;
  }
  assert(EDGE_COVERAGE_TO_INK_GLSL.includes('smoothstep(0.025, 0.45, coverage)'));

  // Чистые функции должны быть реально подключены к renderer, а не остаться
  // неиспользуемым эталонным кодом.
  const viewer = fs.readFileSync(path.join(root, 'web/js/viewer.js'), 'utf8');
  for (const token of [
    "import { cameraClipRange, stableAngle } from './camera_clip.js'",
    "import { edgeCoverageScale, EDGE_COVERAGE_TO_INK_GLSL } from './edge_coverage.js'",
    'this._edgePass = new ShaderPass',
    'this._renderEdgePass();',
    'u.tEdge.value = this._edgeRT.texture',
    '${EDGE_COVERAGE_TO_INK_GLSL}',
    'vec3 edgeSample = bridgedEdge(vUv);',
    'float edge = edgeCoverageToInk(edgeSample.r);',
    'col = mix(col, uInk, edge);',
    'mat.uniformsNeedUpdate = true;',
    "mat.uniforms.uGid.value = mode === 'материалы' ? 0 : (info.gid || 0);",
    "'все': 1",
    'if (uLines > 0.5 && uInner > 0.5 && uSeams > 0.5)',
    'mod(uGid, 256.0) / 255.0',
    'floor(uGid / 256.0) / 255.0',
    'abs(idN.b - idC.b)',
  ]) assert(viewer.includes(token), `viewer не подключён: ${token}`);
  assert(/_idNeeded\(\)\s*\{\s*return !!this\.model;\s*\}/.test(viewer),
    'ID-границы обязаны работать и при lines=все');
  assert(!viewer.includes('col = mix(col, uInk, edge * step(0.5, aC))'),
    'nearest-маска тела не должна занулять найденный контур');

  const polygons = viewer.slice(viewer.indexOf('  setPolygons(on) {'),
    viewer.indexOf('  /** Режим выделения областей', viewer.indexOf('  setPolygons(on) {')));
  for (const token of [
    'new THREE.WireframeGeometry(geometry)',
    'uniqueTopologyPositions(wire.attributes.position.array)',
    'creaseEdgePositions(geometry, this.polygonAngle)',
    'new LineSegmentsGeometry()',
    'new LineMaterial({',
    'const width = topologyLineMaterialWidth(this.renderer.getPixelRatio());',
    'alphaToCoverage: true',
    'this._applyPolygonFill();',
    'new LineSegments2(geo, this._polygonMaterial())',
    'this.scene.add(lines)',
    'this._syncTopologyOverlays();',
  ]) assert(polygons.includes(token), `Экранный полигонаж не подключён: ${token}`);
  assert(!polygons.includes('new THREE.LineBasicMaterial') && !polygons.includes('heavy'),
    'Полигонаж не должен возвращаться к однопиксельным GL_LINES на тяжёлой сцене');
  assert(viewer.includes('{ type: THREE.HalfFloatType, samples: 4 }'),
    'Буфер композера обязан быть multisampled: иначе полосы идут ступеньками');
  for (const file of ['LineSegments2.js', 'LineSegmentsGeometry.js', 'LineMaterial.js']) {
    assert(fs.statSync(path.join(root, 'web/vendor/lines', file)).size > 4000,
      `Отсутствует vendor-модуль экранных линий: ${file}`);
  }

  // Структурные рёбра: куб даёт 12 настоящих рёбер и ни одной диагонали
  // треугольников, цилиндр — только два обода при пороге больше шага граней.
  const cube = [];
  const corners = [[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
    [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]];
  [[0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6], [0, 4, 5], [0, 5, 1],
    [1, 5, 6], [1, 6, 2], [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]]
    .forEach((tri) => tri.forEach((i) => cube.push(...corners[i])));
  assert.strictEqual(creaseEdgePositions({ positions: cube }, 30).length / 6, 12,
    'Куб обязан дать 12 структурных рёбер: диагонали плоских граней — не рёбра');
  const round = [];
  const seg = 16;
  for (let i = 0; i < seg; i += 1) {
    const a0 = (i / seg) * Math.PI * 2, a1 = ((i + 1) / seg) * Math.PI * 2;
    const p0 = [Math.cos(a0), 0, Math.sin(a0)], p1 = [Math.cos(a1), 0, Math.sin(a1)];
    const p2 = [Math.cos(a1), 1, Math.sin(a1)], p3 = [Math.cos(a0), 1, Math.sin(a0)];
    round.push(...p0, ...p1, ...p2, ...p0, ...p2, ...p3);
  }
  assert.strictEqual(creaseEdgePositions({ positions: round }, 30).length / 6, 32,
    'Гранёный цилиндр (22.5°) при пороге 30° даёт только два обода');

  console.log('Линейный render: clip, DPR, subpixel, camera ±0, ID, экранный полигонаж '
    + 'и структурные рёбра проверены.');
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
