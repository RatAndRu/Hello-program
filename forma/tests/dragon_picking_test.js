/* Picking самого экспортированного Dragon Sovereign GLB через viewer.pickAt.

   GLB лежит в рабочей папке приложения (forma/exports/…) и в git не хранится:
   перед тестом его собирает python tools/export_dragon_glb.py. */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { pathToFileURL } = require('url');

const root = path.resolve(__dirname, '..');
const glbPath = path.resolve(process.argv[2] || path.join(
  root, 'exports/dragon_sovereign/dragon_sovereign.glb'));
const reportPath = process.argv[3] ? path.resolve(process.argv[3]) : null;
const viewerSource = fs.readFileSync(path.join(root, 'web/js/viewer.js'), 'utf8');

function sliceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  if (start < 0 || end < 0) throw new Error(`Не найден участок ${startMarker}`);
  return source.slice(start, end);
}

function parseGlb(buffer) {
  if (buffer.readUInt32LE(0) !== 0x46546c67 || buffer.readUInt32LE(4) !== 2) {
    throw new Error('Ожидался GLB 2.0');
  }
  const jsonLength = buffer.readUInt32LE(12);
  const document = JSON.parse(buffer.subarray(20, 20 + jsonLength).toString('utf8'));
  const binHeader = 20 + jsonLength;
  const binLength = buffer.readUInt32LE(binHeader);
  const bin = buffer.subarray(binHeader + 8, binHeader + 8 + binLength);
  return { document, bin };
}

async function main() {
  const THREE = await import(pathToFileURL(path.join(root, 'web/vendor/three.module.js')));
  const objectName = sliceBetween(viewerSource, '  _objectName(mesh) {', '\n  /** Все объекты');
  const pickAt = sliceBetween(viewerSource, '  pickAt(clientX, clientY) {', '\n  /** Полигонаж');
  const visibleSource = sliceBetween(viewerSource, 'function effectivelyVisible(', '\nconst ENV_PRESETS');
  const matchSource = sliceBetween(viewerSource, 'function meshMatches(', '\n/** Raycast');
  const meshMatches = new Function(`${matchSource}\nreturn meshMatches;`)();
  const holder = new Function('THREE', `${visibleSource}\nreturn { ${objectName},\n${pickAt} };`)(THREE);

  if (!fs.existsSync(glbPath)) {
    throw new Error(`Нет GLB дракона: ${glbPath}\n` +
      'Соберите его: python tools/export_dragon_glb.py (из каталога forma/)');
  }
  const bytes = fs.readFileSync(glbPath);
  const { document, bin } = parseGlb(bytes);
  const componentTypes = {
    5121: Uint8Array, 5123: Uint16Array, 5125: Uint32Array, 5126: Float32Array,
  };
  const widths = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 };

  function accessor(index) {
    const entry = document.accessors[index];
    const view = document.bufferViews[entry.bufferView];
    if (view.byteStride) throw new Error('Interleaved accessor не ожидается в этом GLB');
    const ArrayType = componentTypes[entry.componentType];
    const width = widths[entry.type];
    const offset = (view.byteOffset || 0) + (entry.byteOffset || 0);
    const length = entry.count * width * ArrayType.BYTES_PER_ELEMENT;
    const copy = bin.buffer.slice(bin.byteOffset + offset, bin.byteOffset + offset + length);
    return new ArrayType(copy);
  }

  function makeMesh(node) {
    const primitive = document.meshes[node.mesh].primitives[0];
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(
      accessor(primitive.attributes.POSITION), 3));
    if (primitive.indices !== undefined) {
      geometry.setIndex(new THREE.BufferAttribute(accessor(primitive.indices), 1));
    }
    geometry.computeBoundingBox();
    geometry.computeBoundingSphere();
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({ side: THREE.DoubleSide }));
    mesh.name = node.name || '';
    mesh.userData = { ...(node.extras || {}) };
    return mesh;
  }

  const meshes = new Map(document.nodes.map(node => [node.name, makeMesh(node)]));
  const expectedNames = [...meshes.keys()];
  if (expectedNames.sort().join(',') !== 'base,dragon,eye_L,eye_R') {
    throw new Error(`Неожиданный состав GLB: ${expectedNames.join(', ')}`);
  }

  function viewerFor(scene, names) {
    const viewer = {
      model: scene,
      camera: new THREE.PerspectiveCamera(45, 1, 0.05, 5000),
      renderer: { domElement: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 400 }) } },
      _itemByName: new Map(names.map(name => [name, {}])),
      _ghostNames: [], highlightName: '', _detachInstances() {},
    };
    viewer._objectName = holder._objectName;
    return viewer;
  }

  function pick(viewer, cameraPosition, target, expected) {
    viewer.camera.position.set(...cameraPosition);
    viewer.camera.lookAt(new THREE.Vector3(...target));
    viewer.camera.updateMatrixWorld(true);
    const ndc = new THREE.Vector3(...target).project(viewer.camera);
    const x = (ndc.x + 1) * 200;
    const y = (1 - ndc.y) * 200;
    const hit = holder.pickAt.call(viewer, x, y);
    if (!hit || hit.name !== expected || !meshMatches(hit.mesh, expected)) {
      throw new Error(`${expected}: picking вернул ${hit?.name || 'ничего'}`);
    }
    viewer.highlightName = expected;
    return { name: hit.name, point: hit.point.toArray(), faceIndex: hit.faceIndex,
      highlighted: meshMatches(hit.mesh, viewer.highlightName) };
  }

  // Малая сцена: один реальный GLB-узел, один клик.
  const small = new THREE.Scene();
  const smallMesh = meshes.get('eye_R').clone();
  small.add(smallMesh);
  small.updateMatrixWorld(true);
  const smallViewer = viewerFor(small, ['eye_R']);
  const eyeBox = smallMesh.geometry.boundingBox;
  const eyeCenter = eyeBox.getCenter(new THREE.Vector3());
  const smallResult = pick(smallViewer,
    [eyeCenter.x, eyeCenter.y, eyeCenter.z + 100], eyeCenter.toArray(), 'eye_R');

  // Полный состав: четыре независимые камеры/цели, без повторного прогона.
  const full = new THREE.Scene();
  for (const mesh of meshes.values()) full.add(mesh);
  full.updateMatrixWorld(true);
  const fullViewer = viewerFor(full, expectedNames);
  function eyeCase(name) {
    const center = meshes.get(name).geometry.boundingBox.getCenter(new THREE.Vector3());
    return [name, [center.x, center.y, center.z + 250], center.toArray()];
  }
  const cases = [
    // glTF: X право, Y вверх, Z = −Y Forma; передняя камера смотрит по −Z.
    // Центры глаз берём из текущего GLB, а не из координат старой ревизии.
    eyeCase('eye_R'), eyeCase('eye_L'),
    ['dragon', [0, 282, 400], [0, 282, 82]],
    ['base', [0, 500, 110], [0, 12, 110]],
  ];
  const fullResults = cases.map(([name, camera, target]) =>
    pick(fullViewer, camera, target, name));
  const report = {
    glb: path.relative(root, glbPath), bytes: bytes.length,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    small_scene: { passed: 1, total: 1, result: smallResult },
    full_scene: { passed: fullResults.length, total: cases.length, results: fullResults },
    names: expectedNames,
  };
  if (reportPath) {
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + '\n');
  }
  console.log(JSON.stringify(report, null, 2));
}

main().catch(error => {
  console.error(error.stack || error);
  process.exit(1);
});
