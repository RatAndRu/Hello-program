/* Регресс: режим заслонок собирает всю цепочку объектов перед выделенным. */
'use strict';

const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'web/js/viewer.js'), 'utf8')
  .replace(/\r\n?/g, '\n');

function occludingMethod() {
  const start = source.indexOf('  _occludingNames(name) {');
  const end = source.indexOf('\n  _clearGhosts()', start);
  if (start < 0 || end < 0) throw new Error('Не найден метод _occludingNames');
  const method = source.slice(start, end);
  const visibleStart = source.indexOf('function effectivelyVisible(');
  const visibleEnd = source.indexOf('\nconst ENV_PRESETS', visibleStart);
  if (visibleStart < 0 || visibleEnd < 0) throw new Error('Не найден effectivelyVisible');
  const visible = source.slice(visibleStart, visibleEnd);
  return new Function('THREE', `${visible}\nreturn { ${method} };`);
}

async function main() {
  const THREE = await import(pathToFileURL(path.join(root, 'web/vendor/three.module.js')));
  const holder = occludingMethod()(THREE);
  const model = new THREE.Scene();

  function cube(name, z, x = 0) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(4, 4, 2),
      new THREE.MeshBasicMaterial()
    );
    mesh.name = name;
    mesh.position.set(x, 0, z);
    model.add(mesh);
    return mesh;
  }

  // Камера смотрит вдоль −Z. Перед target стоят три независимые заслонки.
  cube('target', -10);
  cube('front', 15);
  cube('middle', 5);
  cube('near', -2);
  cube('behind', -22);       // за целью: не заслонка
  cube('off_axis', 5, 20);   // вне лучей: не заслонка
  model.updateMatrixWorld(true);

  const viewer = {
    model,
    camera: new THREE.PerspectiveCamera(45, 1, 0.1, 1000),
    objectMeshes(name) {
      const meshes = [];
      model.traverse((object) => {
        if (object.isMesh && object.name === name) meshes.push(object);
      });
      return meshes;
    },
    _objectName(mesh) { return mesh.name; },
  };
  viewer.camera.position.set(0, 0, 30);
  viewer.camera.updateMatrixWorld(true);

  const names = holder._occludingNames.call(viewer, 'target').sort();
  const expected = ['front', 'middle', 'near'];
  if (JSON.stringify(names) !== JSON.stringify(expected)) {
    throw new Error(`Ожидались ${expected.join(', ')}; получено ${names.join(', ')}`);
  }

  // Скрытые пользователем объекты по-прежнему не считаются заслонками.
  model.getObjectByName('middle').visible = false;
  const withoutHidden = holder._occludingNames.call(viewer, 'target').sort();
  const expectedVisible = ['front', 'near'];
  if (JSON.stringify(withoutHidden) !== JSON.stringify(expectedVisible)) {
    throw new Error(`После скрытия middle: получено ${withoutHidden.join(', ')}`);
  }
  console.log('Заслонки: вся цепочка front + middle + near найдена; behind и off_axis исключены.');
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exit(1);
});
