/* Регрессии полного редактора: picking составных GLB-узлов и строки сборки. */
'use strict';

const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const root = path.resolve(__dirname, '..');
const viewerSource = fs.readFileSync(path.join(root, 'web/js/viewer.js'), 'utf8');
const appSource = fs.readFileSync(path.join(root, 'web/js/app.js'), 'utf8');

function sliceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  if (start < 0 || end < 0) throw new Error(`Не найден участок ${startMarker}`);
  return source.slice(start, end);
}

function functionBetween(source, startMarker, endMarker) {
  return sliceBetween(source, startMarker, endMarker);
}

async function pickingTest() {
  const THREE = await import(pathToFileURL(path.join(root, 'web/vendor/three.module.js')));
  const objectName = sliceBetween(viewerSource, '  _objectName(mesh) {', '\n  /** Все объекты');
  const pickAt = sliceBetween(viewerSource, '  pickAt(clientX, clientY) {', '\n  /** Полигонаж');
  const visibleSource = sliceBetween(viewerSource, 'function effectivelyVisible(', '\nconst ENV_PRESETS');
  const matchSource = sliceBetween(viewerSource, 'function meshMatches(', '\n/** Raycast');
  const meshMatches = new Function(`${matchSource}\nreturn meshMatches;`)();
  const holder = new Function('THREE', `${visibleSource}\nreturn { ${objectName},\n${pickAt} };`)(THREE);

  const model = new THREE.Scene();
  const entry = new THREE.Group();
  entry.name = 'entry';
  const leaf = new THREE.Group();
  // Имитируем GLTFLoader: очищенное node.name + исходное имя в extras.
  leaf.name = 'entryleaf';
  leaf.userData.formaName = 'entry.leaf';
  entry.add(leaf);
  model.add(entry);
  const leafMesh = new THREE.Mesh(new THREE.BoxGeometry(4, 4, 4), new THREE.MeshBasicMaterial());
  // GLTFLoader может оставить геометрию в безымянном дочернем Mesh.
  leafMesh.name = '';
  leaf.add(leafMesh);

  const ghost = new THREE.Mesh(new THREE.BoxGeometry(5, 5, 1), new THREE.MeshBasicMaterial());
  ghost.name = 'wall_socket';
  ghost.position.z = 5;
  model.add(ghost);
  const hiddenParent = new THREE.Group();
  hiddenParent.name = 'hidden-parent';
  hiddenParent.visible = false;
  const hiddenMesh = new THREE.Mesh(new THREE.BoxGeometry(6, 6, 1), new THREE.MeshBasicMaterial());
  hiddenMesh.name = 'wall_socket';
  hiddenMesh.position.z = 10;
  hiddenParent.add(hiddenMesh);
  model.add(hiddenParent);
  model.updateMatrixWorld(true);

  const known = new Map([['entry', {}], ['entry.leaf', {}], ['wall_socket', {}]]);
  const viewer = {
    model,
    camera: new THREE.PerspectiveCamera(45, 1, 0.1, 1000),
    renderer: { domElement: { getBoundingClientRect: () => ({ left: 0, top: 0, width: 200, height: 200 }) } },
    _itemByName: known,
    _ghostNames: ['wall_socket'],
    highlightName: 'entry.leaf',
    _detachInstances() {},
  };
  viewer._objectName = holder._objectName;
  viewer.camera.position.set(0, 0, 20);
  viewer.camera.lookAt(0, 0, 0);
  viewer.camera.updateMatrixWorld(true);

  if (holder._objectName.call(viewer, leafMesh) !== 'entry.leaf') {
    throw new Error('Безымянный Mesh не разрешился в составной entry.leaf');
  }
  if (!meshMatches(leafMesh, 'entry.leaf')) {
    throw new Error('Подсветка не использует каноническое formaName предка');
  }
  const picked = holder.pickAt.call(viewer, 100, 100);
  if (!picked || picked.name !== 'entry.leaf') {
    throw new Error(`Клик через заслонку выбрал ${picked?.name || 'ничего'} вместо entry.leaf`);
  }

  const sourceMesh = new THREE.Mesh(new THREE.BoxGeometry(4, 4, 4), new THREE.MeshBasicMaterial());
  sourceMesh.name = 'wall_socket';
  const instanced = new THREE.InstancedMesh(sourceMesh.geometry, sourceMesh.material, 1);
  instanced.setMatrixAt(0, new THREE.Matrix4());
  instanced.userData.instanceSources = [{ mesh: sourceMesh }];
  instanced.name = '__instances_wall_socket';
  instanced.position.z = 0;
  // Отдельная сцена: проверяется именно возврат исходного имени копии.
  const instanceModel = new THREE.Scene();
  instanceModel.add(instanced);
  instanceModel.updateMatrixWorld(true);
  const instanceViewer = { ...viewer, model: instanceModel, _ghostNames: [], highlightName: '' };
  const instanceHit = holder.pickAt.call(instanceViewer, 100, 100);
  if (!instanceHit || instanceHit.name !== 'wall_socket' || instanceHit.mesh !== sourceMesh) {
    throw new Error('InstancedMesh не вернул исходный редактируемый объект');
  }

  const pointerup = sliceBetween(viewerSource, "    el.addEventListener('pointerup'", "    el.addEventListener('pointercancel'");
  if (!pointerup.includes('const picked = this.pickAt(e.clientX, e.clientY)')) {
    throw new Error('pointerup обходит общий pickAt');
  }
  if (!appSource.includes('state.viewer.onSelect = (name) => selectObject(name);')
      || !appSource.includes("el.classList.toggle('selected', el.dataset.name === name)")) {
    throw new Error('Клик не синхронизирован с selectObject и строкой списка');
  }
  console.log('Picking: составные узлы, заслонки и instanced-копии разрешаются в имена Forma.');
}

async function frameCacheTest() {
  const keySource = functionBetween(appSource, 'function frameCacheKey(', '\nfunction frameUrl');
  const urlSource = functionBetween(appSource, 'function frameUrl(', '\nfunction frameScript');
  const scriptSource = functionBetween(appSource, 'function frameScript(', '\nfunction prefetchFrame');
  const prefetchSource = functionBetween(appSource, 'function prefetchFrame(', '\n/* --- транспорт');
  const showSource = functionBetween(appSource, 'async function showFrame(', '\n/** Во время сборки');
  const frames = [{ n: 1, line: 10 }, { n: 2, line: 20 }];
  const state = {
    payload: { script_hash: 'hash' }, builtScript: 'a = box size=[1,1,1]',
    anim: { epoch: 0, frameSerial: 0, cache: new Map(), framePending: new Map(),
      busy: false, next: undefined, seqKey: null },
    viewer: {
      async preloadFrame(key) { this.preloaded = key; },
      async loadFrame(key) { (this.loaded ||= []).push(key); return true; },
    },
  };
  let apiCalls = 0;
  const focused = [];
  const fns = new Function('state', 'animFrames', 'apiWithResourcePause', 'focusFrameObject',
    'toast', 'pauseAnim', 'currentScript', 'TOKEN',
    `${keySource}\n${urlSource}\n${scriptSource}\n${prefetchSource}\n${showSource}\nreturn { prefetchFrame, showFrame };`)(
    state, () => frames, async () => { apiCalls += 1; return { glb: true, key: `server-${apiCalls}` }; },
    (frame) => focused.push(frame.n), () => {}, () => {}, () => state.builtScript, 'token');
  fns.prefetchFrame(0);
  const pending = state.anim.framePending.get('hash_1');
  if (!pending) throw new Error('prefetch не зарегистрировал pending');
  await pending.promise;
  await fns.showFrame(0);
  if (apiCalls !== 1 || state.viewer.loaded.join(',') !== 'server-1') {
    throw new Error(`prefetch/showFrame повторно запросили кадр: api=${apiCalls}, loaded=${state.viewer.loaded}`);
  }

  // Медленный первый ответ не должен перекрыть более поздний переход.
  state.anim.cache.clear();
  state.anim.framePending.clear();
  state.anim.epoch += 1;
  state.anim.busy = false;
  state.anim.next = undefined;
  state.viewer.loaded = [];
  const deferred = [];
  const apiDeferred = () => new Promise((resolve) => deferred.push(resolve));
  const staleFns = new Function('state', 'animFrames', 'apiWithResourcePause', 'focusFrameObject',
    'toast', 'pauseAnim', 'currentScript', 'TOKEN',
    `${keySource}\n${urlSource}\n${scriptSource}\n${prefetchSource}\n${showSource}\nreturn { showFrame };`)(
    state, () => frames, apiDeferred, (frame) => focused.push(frame.n), () => {}, () => {}, () => state.builtScript, 'token');
  const first = staleFns.showFrame(0);
  await staleFns.showFrame(1); // встаёт в очередь, пока первый запрос занят
  if (deferred.length !== 1) throw new Error('Неожиданный параллельный запрос кадра');
  deferred[0]({ glb: true, key: 'old-frame' });
  await first;
  await new Promise((resolve) => setImmediate(resolve));
  if (deferred.length !== 2) throw new Error('Очередь не запустила последний кадр');
  deferred[1]({ glb: true, key: 'new-frame' });
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  if (state.viewer.loaded.join(',') !== 'new-frame') {
    throw new Error(`Устаревший кадр перекрыл актуальный: ${state.viewer.loaded}`);
  }
  console.log('Кадровый кеш: prefetch переиспользуется, устаревший ответ отбрасывается.');
}

function animationTest() {
  const highlightSource = functionBetween(appSource, 'function highlightScriptLine(', '\nfunction clearScriptHighlight');
  const state = { runLine: 0, runSoft: [] };
  const calls = [];
  const highlight = new Function('state', '$', 'placeRunHighlight',
    `return (${highlightSource});`)(state, () => null, (follow) => calls.push(follow));
  highlight(7, { scroll: false });
  highlight(8, { scroll: true });
  if (JSON.stringify(calls) !== JSON.stringify([false, true])) {
    throw new Error(`scroll не управляет автопрокруткой: ${JSON.stringify(calls)}`);
  }

  const assemblySource = functionBetween(appSource, 'function assemblyFrameIndexAt(', '\n/** Какая строка');
  const fromTimeSource = functionBetween(appSource, 'function highlightFromTime(', '\nfunction escapeHtml');
  const clips = [{ kind: 'assembly', start: 0, length: 3, hold: 1, line: 99 }];
  const frames = [{ line: 10 }, { line: 20 }, { line: 30 }];
  const animState = { anim: { mode: 'clips', frameIndex: 0 } };
  const seen = [];
  const fns = new Function('state', 'animClips', 'animFrames', 'highlightScriptLine',
    `${assemblySource}\n${fromTimeSource}\nreturn { assemblyFrameIndexAt, highlightFromTime };`)(
    animState, () => clips, () => frames,
    (line, options) => seen.push({ line, options }));
  fns.highlightFromTime(1.2, { scroll: false });
  if (seen.length !== 1 || seen[0].line !== 20 || seen[0].options.scroll !== false) {
    throw new Error(`Assembly подсветил не строку кадра: ${JSON.stringify(seen)}`);
  }
  if (fns.assemblyFrameIndexAt(2.99) !== 2 || fns.assemblyFrameIndexAt(4) !== -1) {
    throw new Error('Неверные границы кадров assembly');
  }

  if (!appSource.includes('function frameCacheKey(frame)') || appSource.includes('pf_${state.payload')) {
    throw new Error('Prefetch и showFrame используют разные ключи кадрового кеша');
  }
  if (!appSource.includes('if (pending?.epoch === epoch) await pending.promise;')) {
    throw new Error('showFrame не переиспользует pending prefetch');
  }
  if (!appSource.includes('if (state.anim.mode === \'clips\') updateSequence(t);')) {
    throw new Error('onTime снова имеет ранний выход для frames');
  }
  if (!viewerSource.includes('const serial = ++this._loadSerial;')
      || !viewerSource.includes('if (serial !== this._loadSerial)')) {
    throw new Error('Полная GLB-загрузка не защищена от устаревшего ответа');
  }
  const disposeSource = sliceBetween(viewerSource, '  disposeModel() {', '\n  _clearOverlays()');
  if (disposeSource.includes('if (!this.model) return;')) {
    throw new Error('disposeModel оставляет frameRoot/cache при пустой финальной модели');
  }
  const preloadSource = sliceBetween(viewerSource, '  async preloadFrame(', '\n  _showFrameObject');
  if (!preloadSource.includes('if (serial !== this._frameSerial)')) {
    throw new Error('preloadFrame может вернуть устаревший GLB в кеш');
  }
  console.log('Анимация: scroll, строка assembly и единый prefetch/showFrame кеш проверены.');
}

Promise.resolve()
  .then(pickingTest)
  .then(animationTest)
  .then(frameCacheTest)
  .catch((error) => { console.error(error.stack || error); process.exit(1); });
