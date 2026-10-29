/* Регресс: динамический clip и плотность edge-coverage для линейных стилей. */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const root = path.resolve(__dirname, '..');

async function main() {
  const { cameraClipRange } = await import(pathToFileURL(path.join(root, 'web/js/camera_clip.js')));
  const { edgeCoverageScale } = await import(pathToFileURL(path.join(root, 'web/js/edge_coverage.js')));

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

  assert.strictEqual(edgeCoverageScale(1100, 700, 1), 2, 'DPR=1: 2×2 coverage samples');
  assert.strictEqual(edgeCoverageScale(1100, 700, 2), 1, 'DPR=2 уже содержит 2×2 samples');
  assert(Math.abs(edgeCoverageScale(1100, 700, 1.5) - 4 / 3) < 1e-12);
  assert.strictEqual(edgeCoverageScale(4000, 2000, 1), 1, 'лимит 8 Мп не увеличивает огромный кадр');
  const capped = edgeCoverageScale(1920, 1080, 1);
  assert(capped > 1 && capped < 2, 'большой кадр получает ограниченный supersampling');
  assert(Math.floor(1920 * capped) * Math.floor(1080 * capped) <= 8000000);
  assert.strictEqual(edgeCoverageScale(1100, 700, NaN), 2);
  assert.strictEqual(edgeCoverageScale(1100, 700, 0), 2, 'некорректный DPR не отключает сглаживание');

  // Чистые функции должны быть реально подключены к renderer, а не остаться
  // неиспользуемым эталонным кодом.
  const viewer = fs.readFileSync(path.join(root, 'web/js/viewer.js'), 'utf8');
  for (const token of [
    "import { cameraClipRange } from './camera_clip.js'",
    "import { edgeCoverageScale } from './edge_coverage.js'",
    'this._edgePass = new ShaderPass',
    'this._renderEdgePass();',
    'u.tEdge.value = this._edgeRT.texture',
    'float edge = texture2D(tEdge, vUv).r',
  ]) assert(viewer.includes(token), `viewer не подключён: ${token}`);

  console.log('Линейный render: 4 ракурса clip, вырожденный AABB, DPR и лимит coverage проверены.');
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
