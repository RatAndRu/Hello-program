import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { GLTFLoader } from 'three/addons/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/RoomEnvironment.js';

const VIEW_DIRS = {
  iso: new THREE.Vector3(0.95, 0.72, -1.0),
  front: new THREE.Vector3(0, 0.18, -1),
  back: new THREE.Vector3(0, 0.18, 1),
  right: new THREE.Vector3(1, 0.18, 0),
  left: new THREE.Vector3(-1, 0.18, 0),
  top: new THREE.Vector3(0, 1, 0.001),
};

/** Совпадает ли меш с именем объекта из сценария. */
function meshMatches(o, name) {
  if (!o || !o.isMesh || !name) return false;
  const candidates = [o.name, o.parent?.name, o.userData?.formaName];
  for (let n = o.parent; n && n !== o; n = n.parent) candidates.push(n.name);
  return candidates.some((c) => c && c === name);
}

const ENV_PRESETS = {
  studio: { bg: '#0b0e13', key: '#ffffff', fill: '#9dbcff', rim: '#ffe6c4', ground: '#11161d', hemi: 0.55, fog: true },
  sun: { bg: '#1b2733', key: '#fff2d8', fill: '#a8c8ff', rim: '#ffd9a0', ground: '#20262b', hemi: 0.35, fog: true },
  sunset: { bg: '#241a20', key: '#ffcf9e', fill: '#7f9cc9', rim: '#ff9a6a', ground: '#2a1f24', hemi: 0.4, fog: true },
  night: { bg: '#05070d', key: '#cfd8ff', fill: '#5068a8', rim: '#8fb4ff', ground: '#0a0d14', hemi: 0.22, fog: true },
  soft: { bg: '#23272d', key: '#ffffff', fill: '#e8eefc', rim: '#ffffff', ground: '#2a2e34', hemi: 0.8, fog: true },
  back: { bg: '#0a0c11', key: '#ffffff', fill: '#6f8ccc', rim: '#ffffff', ground: '#0e1116', hemi: 0.25, fog: true },
  grey: { bg: '#8a8f98', key: '#ffffff', fill: '#dfe6f2', rim: '#ffffff', ground: '#7d828b', hemi: 0.9, fog: false },
  white: { bg: '#f2f4f7', key: '#ffffff', fill: '#e4ecff', rim: '#ffffff', ground: '#e7eaef', hemi: 1.1, fog: false },
  void: { bg: '#000000', key: '#ffffff', fill: '#8fb0ff', rim: '#ffd7a8', ground: '#000000', hemi: 0.3, fog: false },
};

export class Viewer {
  constructor(container) {
    this.container = container;
    this.renderer = null;
    this.model = null;
    this.wireframe = false;
    this.polygons = false;
    this.gridVisible = true;
    this.ready = false;
    this.lastUrl = null;
    this.bbox = null;
    this.settings = {};
    this.shading = 'realistic';
    this.mixer = null;
    this.action = null;
    this.actions = [];
    this.gltfClips = [];
    this.plan = null;          // тайм-лайн из сценария: {clips, duration, assembly}
    this.timeline = null;
    this.time = 0;
    this.duration = 0;
    this.playing = false;
    this.speed = 1;
    this.loop = true;
    this.manualAdvance = false;  // кадры сборки листает интерфейс
    this.onFrame = null;         // (dt) => void, для покадрового режима
    this.onTime = null;          // (time, duration) => void
    this.onEnd = null;           // достигнут конец без зацикливания
    this.frameRoot = null;
    this.frameKey = null;
    this._frameCache = new Map();
    this._animWrap = null;
    this._animCenter = null;
    this._explodeItems = [];
    this._overlays = [];
    this._selOverlays = [];
    this.selectMode = false;
    this.selRadius = 14;
    this.selection = null;
    this.selections = [];
    this.hidden = new Set();
    this._frames = 0;
    this._lastFps = 0;
    this._fpsTime = 0;
    this._init();
  }

  _init() {
    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      preserveDrawingBuffer: true,
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(this.container.clientWidth || 640, this.container.clientHeight || 480);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.localClippingEnabled = true;
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.display = 'block';
    this.container.appendChild(renderer.domElement);
    this.renderer = renderer;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0e13);
    scene.fog = new THREE.Fog(0x0b0e13, 4000, 9000);
    this.scene = scene;

    const pmrem = new THREE.PMREMGenerator(renderer);
    this.envTexture = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = this.envTexture;

    this.camera = new THREE.PerspectiveCamera(34, 1, 1, 40000);
    this.camera.position.set(300, 260, 380);

    this.controls = new OrbitControls(this.camera, renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.rotateSpeed = 0.85;
    this.controls.panSpeed = 0.8;
    this.controls.zoomSpeed = 0.9;
    this.controls.maxPolarAngle = Math.PI * 0.995;
    this.controls.minDistance = 5;
    this.controls.maxDistance = 40000;
    // Правая кнопка — перемещение по сцене, колесо — приближение.
    this.controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN,
    };
    this.controls.screenSpacePanning = true;
    this.controls.enablePan = true;
    renderer.domElement.addEventListener('contextmenu', (e) => e.preventDefault());

    this.hemi = new THREE.HemisphereLight(0xdfe9ff, 0x5d6a7d, 0.72);
    scene.add(this.hemi);

    // минимальная освещённость: даже внутренние и «спрятанные» участки видны
    this.ambient = new THREE.AmbientLight(0xdfe6f2, 0.34);
    scene.add(this.ambient);

    const key = new THREE.DirectionalLight(0xffffff, 2.5);
    key.position.set(320, 620, 420);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.6;
    this.keyLight = key;
    scene.add(key);

    this.fillLight = new THREE.DirectionalLight(0x9dbcff, 0.75);
    this.fillLight.position.set(-420, 260, -260);
    scene.add(this.fillLight);

    this.rimLight = new THREE.DirectionalLight(0xffe6c4, 0.5);
    this.rimLight.position.set(60, 180, -520);
    scene.add(this.rimLight);

    // Свет снизу («отражение от пола») — низ модели больше не проваливается в чёрный.
    this.bounceLight = new THREE.DirectionalLight(0xffe0bd, 1.15);
    this.bounceLight.position.set(-120, -520, 260);
    this.bounceLight.castShadow = false;
    this.bounceLight.target.position.set(0, 60, 0);
    this.scene.add(this.bounceLight, this.bounceLight.target);

    // «пол» с мягкой тенью
    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(1, 96),
      new THREE.MeshStandardMaterial({ color: 0x11161d, roughness: 0.94, metalness: 0.0 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    ground.position.y = -0.05;
    this.ground = ground;
    scene.add(ground);

    this.grid = new THREE.GridHelper(1000, 20, 0x2b3a4d, 0x1c2632);
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.85;
    this.grid.material.depthWrite = false;
    scene.add(this.grid);

    this.axesVisible = true;
    this.axes = this._buildAxes();
    this.axes.visible = true;
    scene.add(this.axes);

    const resize = () => this.resize();
    new ResizeObserver(resize).observe(this.container);
    window.addEventListener('resize', resize);

    const clock = new THREE.Clock();
    const loop = () => {
      requestAnimationFrame(loop);
      const dt = clock.getDelta();
      this.controls.update();
      this._animateTiming(dt);
      this._tickAnimation(dt);
      this._frames += 1;
      this._fpsTime += dt;
      if (this._fpsTime > 0.5) {
        this._lastFps = Math.round(this._frames / this._fpsTime);
        this._frames = 0;
        this._fpsTime = 0;
      }
      renderer.render(scene, this.camera);
    };
    loop();
    this.ready = true;

    this._bindPointer();
  }

  /** Оси X/Y/Z: стрелки и подписи, длину подбираем под модель. */
  _buildAxes() {
    const group = new THREE.Group();
    group.name = 'FormaAxes';
    const colors = { x: 0xff5a5a, y: 0x3ddc84, z: 0x4a9bff };
    // сценарий живёт в Z-up, окно — в Y-up: X→X, Y→-Z, Z→Y
    const dirs = {
      x: new THREE.Vector3(1, 0, 0),
      y: new THREE.Vector3(0, 0, -1),
      z: new THREE.Vector3(0, 1, 0),
    };
    Object.entries(dirs).forEach(([key, dir]) => {
      const color = colors[key];
      const mat = new THREE.MeshBasicMaterial({
        color, depthTest: false, depthWrite: false, transparent: true, opacity: 0.98,
      });
      const shaft = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 16), mat);
      shaft.name = 'axis-' + key;
      shaft.renderOrder = 990;
      const head = new THREE.Mesh(new THREE.ConeGeometry(1, 1, 20), mat);
      head.renderOrder = 991;
      const label = this._axisLabel(key.toUpperCase(), color);
      label.renderOrder = 992;
      group.add(shaft, head, label);
      group.userData[key] = { dir, shaft, head, label };
    });
    return group;
  }

  _axisLabel(text, color) {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#0b0e13';
    ctx.beginPath();
    ctx.arc(64, 64, 58, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#' + color.toString(16).padStart(6, '0');
    ctx.font = 'bold 74px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, 64, 70);
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, transparent: true, depthTest: false, depthWrite: false,
    }));
    sprite.renderOrder = 1000;
    return sprite;
  }

  _bindPointer() {
    const el = this.renderer.domElement;
    let down = null;
    let band = null;

    const local = (e) => {
      const rect = el.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top, w: rect.width, h: rect.height };
    };
    const hideBand = () => { if (band) { band.remove(); band = null; } };

    el.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;   // правая — панорама, средняя — вращение
      const p = local(e);
      down = { x: e.clientX, y: e.clientY, t: performance.now(), p };
      if (this.selectMode) {
        band = document.createElement('div');
        band.className = 'marquee';
        band.style.left = p.x + 'px';
        band.style.top = p.y + 'px';
        band.style.width = '0px';
        band.style.height = '0px';
        this.container.appendChild(band);
      }
    });

    el.addEventListener('pointermove', (e) => {
      if (!band || !down) return;
      const p = local(e);
      band.style.left = Math.min(down.p.x, p.x) + 'px';
      band.style.top = Math.min(down.p.y, p.y) + 'px';
      band.style.width = Math.abs(p.x - down.p.x) + 'px';
      band.style.height = Math.abs(p.y - down.p.y) + 'px';
    });

    el.addEventListener('pointerup', (e) => {
      if (e.button !== 0 || !down) { hideBand(); return; }
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      const quick = performance.now() - down.t < 420;
      const start = down;
      down = null;
      hideBand();
      if (!this.model) return;
      const additive = e.shiftKey || e.ctrlKey || e.metaKey;
      if (this.selectMode && moved > 8) {
        const p = local(e);
        this._selectMarquee({ x0: start.p.x, y0: start.p.y, x1: p.x, y1: p.y }, additive);
        if (this.onSelection) this.onSelection(this.selections);
        return;
      }
      if (moved > 5 || !quick) return;
      const rect = el.getBoundingClientRect();
      const pointer = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1
      );
      const ray = new THREE.Raycaster();
      ray.setFromCamera(pointer, this.camera);
      const hits = ray.intersectObject(this.model, true);
      if (this.selectMode) {
        if (!hits.length) {
          if (!additive) {
            this.clearSelection();
            if (this.onSelection) this.onSelection(this.selections);
          }
          return;
        }
        if (e.ctrlKey || e.metaKey) {
          this._removeSelectionAt(hits[0].point);
        } else {
          this._selectRegion(hits[0], e.shiftKey);
        }
        if (this.onSelection) this.onSelection(this.selections);
        return;
      }
      if (hits.length && this.onSelect) {
        const mesh = hits[0].object;
        this.onSelect(mesh.name || mesh.parent?.name || '');
      } else if (!hits.length && this.onSelect) {
        this.onSelect('');
      }
    });

    el.addEventListener('pointercancel', () => { down = null; hideBand(); });
    el.addEventListener('dblclick', () => this.reset());
  }

  /** Квадратное выделение: все треугольники, чьи центры попали в рамку. */
  _selectMarquee(rect, additive = false) {
    if (!this.model) return;
    const el = this.renderer.domElement;
    const w = el.clientWidth || 1;
    const h = el.clientHeight || 1;
    const x0 = Math.min(rect.x0, rect.x1), x1 = Math.max(rect.x0, rect.x1);
    const y0 = Math.min(rect.y0, rect.y1), y1 = Math.max(rect.y0, rect.y1);
    this.camera.updateMatrixWorld(true);
    const v = new THREE.Vector3();
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    const ab = new THREE.Vector3(), ac = new THREE.Vector3();
    let first = true;
    this.model.traverse((mesh) => {
      if (!mesh.isMesh || !mesh.visible) return;
      const geo = mesh.geometry;
      const pos = geo?.attributes?.position;
      if (!pos) return;
      mesh.updateMatrixWorld(true);
      const m = mesh.matrixWorld;
      const idx = geo.index;
      const total = idx ? Math.floor(idx.count / 3) : Math.floor(pos.count / 3);
      const stride = total > 150000 ? Math.ceil(total / 150000) : 1;
      const out = [];
      let area = 0, count = 0;
      const box = new THREE.Box3();
      for (let t = 0; t < total; t += stride) {
        const i0 = idx ? idx.getX(t * 3) : t * 3;
        const i1 = idx ? idx.getX(t * 3 + 1) : t * 3 + 1;
        const i2 = idx ? idx.getX(t * 3 + 2) : t * 3 + 2;
        a.fromBufferAttribute(pos, i0).applyMatrix4(m);
        b.fromBufferAttribute(pos, i1).applyMatrix4(m);
        c.fromBufferAttribute(pos, i2).applyMatrix4(m);
        v.copy(a).add(b).add(c).multiplyScalar(1 / 3).project(this.camera);
        if (v.z < -1 || v.z > 1) continue;
        const sx = (v.x * 0.5 + 0.5) * w;
        const sy = (-v.y * 0.5 + 0.5) * h;
        if (sx < x0 || sx > x1 || sy < y0 || sy > y1) continue;
        out.push(a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z);
        ab.subVectors(b, a); ac.subVectors(c, a);
        area += ab.cross(ac).length() * 0.5;
        box.expandByPoint(a); box.expandByPoint(b); box.expandByPoint(c);
        count += 1;
      }
      if (!count) return;
      const size = new THREE.Vector3();
      const ctr = new THREE.Vector3();
      box.getSize(size);
      box.getCenter(ctr);
      const radius = Math.max(2, size.length() * 0.5);
      this._commitRegion(mesh.name || mesh.parent?.name || 'деталь', out, count, area, box,
                         ctr, radius, additive || !first);
      first = false;
    });
    if (first && !additive) this.clearSelection();
  }

  _animateTiming(dt) {
    if (this._progress !== undefined && this._progress !== null) {
      this._progress = Math.min(1, this._progress + dt * 2.2);
      const e = 1 - Math.pow(1 - this._progress, 3);
      const p = this._from.clone().lerp(this._to, e);
      this.camera.position.copy(p);
      this.controls.target.copy(this._fromTarget.clone().lerp(this._toTarget, e));
      if (this._progress >= 1) {
        this._progress = null;
        if (this._pendingView) {
          this.setView(this._pendingView, false);
          this._pendingView = null;
        }
      }
    }
  }

  resize() {
    const w = this.container.clientWidth || 640;
    const h = this.container.clientHeight || 480;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / Math.max(h, 1);
    this.camera.updateProjectionMatrix();
  }

  disposeModel() {
    this.clearHighlight();
    if (!this.model) return;
    this.scene.remove(this.model);
    this.model.traverse((o) => {
      if (o.isMesh) {
        o.geometry?.dispose();
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m) => {
          if (!m) return;
          ['map', 'normalMap', 'roughnessMap', 'metalnessMap'].forEach((k) => m[k]?.dispose?.());
          m.dispose?.();
        });
      }
    });
    if (this._animWrap) {
      this.scene.remove(this._animWrap);
      this._animWrap = null;
    }
    if (this.frameRoot) {
      this.scene.remove(this.frameRoot);
      this.frameRoot = null;
      this.frameKey = null;
    }
    this.model = null;
    this.mixer = null;
    this.action = null;
    this.actions = [];
    this.gltfClips = [];
    this.plan = null;
    this.timeline = null;
    this.playing = false;
    this.time = 0;
    this.duration = 0;
    this._explodeItems = [];
    this._animCenter = null;
    this._clearOverlays();
    this._disposeSelOverlay();
    this.selection = null;
    this.selections = [];
  }

  _clearOverlays() {
    this._overlays.forEach((o) => {
      o.geometry?.dispose();
      o.material?.dispose();
      o.parent?.remove(o);
    });
    this._overlays = [];
  }

  async load(url, animation = null) {
    this.lastUrl = url;
    const loader = new GLTFLoader();
    const gltf = await new Promise((resolve, reject) => {
      loader.load(url, resolve, undefined, reject);
    });
    this.disposeModel();
    const root = gltf.scene;
    root.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = true;
        o.receiveShadow = true;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m) => {
          if (!m) return;
          m.envMapIntensity = 1.15;
          m.side = THREE.FrontSide;
          m.needsUpdate = true;
        });
      }
    });
    this.scene.add(root);
    this.model = root;
    // Модель уже на экране. Дальше — только оформление и анимация: сбой в них
    // не должен выглядеть как «не удалось показать модель».
    try {
      this._fit(root);
      // Сначала анимация: если что-то в оформлении ниже упадёт, модель всё равно
      // должна играть, а не превращаться в «статичную картинку».
      this._setupAnimation(gltf);
      this._prepareAnimWrap();
      const clips = animation?.clips?.length ? animation.clips
        : (animation && animation.kind ? [animation] : []);
      this.setTimeline({ clips, duration: Number(animation?.duration) || 0,
                         assembly: animation?.assembly || null });
      this.setAxes(this.axesVisible);
      this.setShading(this.shading);
      this.applySettings(this.settings);
      this.setPolygons(this.polygons);
      // Скрытые объекты остаются скрытыми и после пересборки: состояние живёт
      // в вьюере, а не только в списке объектов.
      this.hidden.forEach((name) => this.setObjectVisible(name, false));
      if (this.highlightName) this.setHighlight(this.highlightName);
    } catch (e) {
      console.error('оформление модели:', e);
    }
    return this.bbox;
  }

  _setupAnimation(gltf) {
    this.gltfClips = (gltf.animations || []).slice();
    this.mixer = null;
    this.action = null;
    this.actions = [];
    this.animDuration = 0;
    if (!this.gltfClips.length) return;
    this.mixer = new THREE.AnimationMixer(this.model);
    this.gltfClips.forEach((clip) => {
      const act = this.mixer.clipAction(clip);
      act.setLoop(THREE.LoopOnce, 1);
      act.clampWhenFinished = true;
      act.paused = true;
      act.enabled = true;
      act.play();
      this.actions.push(act);
      this.animDuration = Math.max(this.animDuration, clip.duration);
    });
  }

  /** Обёртка для процедурной анимации: вращение и рост идут вокруг центра модели. */
  _prepareAnimWrap() {
    this._animWrap = null;
    this._animCenter = null;
    this._explodeItems = [];
    if (!this.model) return;
    this.model.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(this.model);
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    // Ось вращения — вертикальная прямая через центр модели. Если начало
    // координат попадает внутрь габаритов (все модели ядра строятся вокруг
    // нуля), вращаем ровно вокруг него: у кружки ручка не сдвигает ось.
    if (!(box.min.x < 0 && box.max.x > 0)) center.x = (box.min.x + box.max.x) / 2;
    else center.x = 0;
    if (!(box.min.z < 0 && box.max.z > 0)) center.z = (box.min.z + box.max.z) / 2;
    else center.z = 0;
    const wrap = new THREE.Group();
    wrap.name = 'FormaAnimWrap';
    wrap.position.copy(center);
    this.scene.add(wrap);
    this.model.position.sub(center);
    wrap.add(this.model);
    this._animWrap = wrap;
    this._animCenter = center;
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      const p = new THREE.Vector3();
      o.getWorldPosition(p);
      const dir = p.clone().sub(center);
      const len = dir.length();
      const local = dir.length() > 1e-6 ? dir.normalize() : new THREE.Vector3(0, 1, 0);
      if (o.parent && o.parent !== wrap) {
        const q = new THREE.Quaternion();
        o.parent.getWorldQuaternion(q);
        local.applyQuaternion(q.invert());
      }
      this._explodeItems.push({ node: o, base: o.position.clone(), dir: local,
                                reach: Math.min(1, len / 120) });
    });
  }

  /** Тайм-лайн сценария: клипы со временем начала. */
  setTimeline(timeline) {
    this.plan = timeline && timeline.clips && timeline.clips.length ? timeline : null;
    this.timeline = this.plan;
    if (this.plan) {
      const ends = this.plan.clips.map((c) => Number(c.end) || 0);
      this.duration = Math.max(0.2, Number(this.plan.duration) || Math.max(...ends) || 4);
    } else {
      this.duration = Math.max(0.2, this.animDuration || 0);
    }
    this.time = 0;
    this.loop = this.plan ? this.plan.clips.every((c) => c.loop !== false) : this.loop;
    this.applyTime(0);
    return this.duration;
  }

  hasModel() {
    const stats = this.getStats?.();
    return Boolean(this.model && (!stats || typeof stats.meshes !== 'number' || stats.meshes > 0));
  }

  hasAnimation() {
    return Boolean((this.plan && this.plan.clips.length) || this.gltfClips.length);
  }

  animationKinds() {
    return (this.plan?.clips || []).map((c) => c.kind);
  }

  /** Ставит анимацию на нужную секунду — этим же работает прокрутка кадров. */
  applyTime(t) {
    const total = this.duration || 0;
    this.time = Math.max(0, Math.min(Number(t) || 0, Math.max(total, 0)));
    if (this.plan) this._applyPlan(this.time);
    else if (this.actions.length) {
      this.actions.forEach((act) => {
        const clip = act.getClip();
        act.time = Math.min(this.time, clip.duration);
      });
      if (this.mixer) this.mixer.update(0);
    }
    this.onTime?.(this.time, total);
  }

  setTime(t) {
    this.applyTime(t);
  }

  _easeOut(x) {
    return 1 - Math.pow(1 - Math.max(0, Math.min(1, x)), 3);
  }

  _applyPlan(t) {
    const wrap = this._animWrap;
    if (!wrap) return;
    let angle = 0;
    let axis = 'z';
    let scale = 1;
    let explode = 0;
    let forming = false;
    for (const clip of this.plan.clips) {
      const start = Number(clip.start) || 0;
      const earlyKind = String(clip.kind || 'spin').toLowerCase();
      if (t + 1e-6 < start) {
        // как в GLB: до начала формирования модель ещё «не выросла»
        if (earlyKind === 'formation') { forming = true; scale = 0.001; }
        continue;
      }
      const local = t - start;
      const len = Math.max(0.1, Number(clip.length) || Number(clip.seconds) || 4);
      const p = Math.max(0, Math.min(1, local / len));
      const kind = String(clip.kind || 'spin').toLowerCase();
      if (kind === 'spin') {
        angle = Math.PI * 2 * p;
        axis = String(clip.axis || 'z').toLowerCase();
      } else if (kind === 'formation') {
        // в GLB рост заканчивается на 0,85 длительности — держим ту же кривую
        forming = true;
        const grow = Math.min(1, local / Math.max(0.1, len * 0.85));
        scale = Math.max(0.001, 0.001 + 0.999 * grow);
      } else if (kind === 'explode') {
        explode = p * (Number(clip.amount) || 30);
      }
    }
    if (!forming) scale = 1;
    wrap.scale.setScalar(scale);
    const q = new THREE.Quaternion();
    if (angle) {
      const v = axis === 'x' ? new THREE.Vector3(1, 0, 0)
        : axis === 'y' ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0);
      q.setFromAxisAngle(v, angle);
    }
    wrap.quaternion.copy(q);
    this._explodeItems.forEach(({ node, base, dir }) => {
      if (!explode) { node.position.copy(base); return; }
      node.position.copy(base).addScaledVector(dir, explode);
    });
  }

  _tickAnimation(dt) {
    if (this.manualAdvance) {
      if (this.playing) this.onFrame?.(dt);
      return;
    }
    if (!this.hasAnimation()) return;
    if (!this.playing) return;
    const total = this.duration;
    let t = this.time + dt * this.speed;
    if (t > total) {
      if (this.loop) t = ((t - total) % Math.max(total, 0.001));
      else { t = total; this.playing = false; this.onEnd?.(); }
    }
    this.applyTime(t);
  }

  playAnimation(playing = true) {
    if (playing && !this.hasAnimation()) return false;
    this.playing = Boolean(playing);
    if (this.playing && !this.loop && this.time >= this.duration - 1e-6) this.applyTime(0);
    return true;
  }

  restartAnimation() {
    if (!this.hasAnimation()) return false;
    this.applyTime(0);
    this.playing = true;
    return true;
  }

  toggleAnimation() {
    return this.playAnimation(!this.playing);
  }

  setSpeed(v) {
    this.speed = Math.max(0.05, Math.min(8, v));
  }

  setLoop(loop) {
    this.loop = Boolean(loop);
  }

  /* ------------------------------------------------------------------ */
  /*  Кадры сборки: промежуточные модели по шагам сценария              */
  /* ------------------------------------------------------------------ */
  async loadFrame(key, url) {
    if (this.frameKey === key) return;
    if (this._frameCache.has(key)) {
      this._showFrameObject(key, this._frameCache.get(key));
      return;
    }
    const loader = new GLTFLoader();
    const gltf = await new Promise((resolve, reject) => {
      loader.load(url, resolve, undefined, reject);
    });
    const root = gltf.scene;
    root.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = true;
      o.receiveShadow = true;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => { if (m) { m.envMapIntensity = 1.15; m.side = THREE.FrontSide; } });
    });
    this._frameCache.set(key, root);
    while (this._frameCache.size > 20) {
      const oldest = this._frameCache.keys().next().value;
      this._frameCache.delete(oldest);
    }
    this._showFrameObject(key, root);
  }

  _showFrameObject(key, root) {
    if (this.frameKey === key) return;
    if (this.frameRoot) this.scene.remove(this.frameRoot);
    this.frameRoot = root;
    this.frameKey = key;
    if (this.model) this.model.visible = false;
    if (this._animWrap) this._animWrap.visible = false;
    this.scene.add(root);
  }

  showFinalModel() {
    if (this.frameRoot) this.scene.remove(this.frameRoot);
    this.frameRoot = null;
    this.frameKey = null;
    if (this.model) this.model.visible = true;
    if (this._animWrap) this._animWrap.visible = true;
  }

  _fit(root) {
    let box = new THREE.Box3().setFromObject(root);
    if (box.isEmpty()) {
      // Пустая рамка (например, все детали скрыты) не должна оставлять камеру
      // «в никуда»: ставим разумные границы, чтобы вид всё равно применился.
      box = new THREE.Box3(new THREE.Vector3(-50, -50, -50),
                           new THREE.Vector3(50, 50, 50));
    }
    const size = new THREE.Vector3();
    const center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);
    this.bbox = { min: box.min.clone(), max: box.max.clone(), size, center };
    const radius = Math.max(size.length() * 0.5, 10);
    const dist = radius / Math.tan((this.camera.fov * Math.PI) / 360) * 1.55;
    this._home = center.clone().add(VIEW_DIRS.iso.clone().normalize().multiplyScalar(dist));
    this._homeTarget = center.clone();
    this.dist = dist;

    const span = Math.max(size.x, size.z, 20);
    const gridSize = Math.pow(10, Math.ceil(Math.log10(span * 2.4)));
    this.scene.remove(this.grid);
    this.grid.geometry.dispose();
    this.grid.material.dispose();
    this.grid = new THREE.GridHelper(gridSize, 20, 0x33465e, 0x1d2733);
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.9;
    this.grid.material.depthWrite = false;
    this.grid.position.y = 0;
    this.grid.visible = this.gridVisible;
    this.scene.add(this.grid);

    const groundRadius = gridSize * 0.62;
    this.ground.geometry.dispose();
    this.ground.geometry = new THREE.CircleGeometry(groundRadius, 96);

    const shadowSpan = Math.max(size.x, size.y, size.z, 50) * 1.6;
    this.keyLight.shadow.camera.left = -shadowSpan;
    this.keyLight.shadow.camera.right = shadowSpan;
    this.keyLight.shadow.camera.top = shadowSpan;
    this.keyLight.shadow.camera.bottom = -shadowSpan;
    this.keyLight.shadow.camera.near = 1;
    this.keyLight.shadow.camera.far = shadowSpan * 8;
    this.keyLight.shadow.camera.updateProjectionMatrix();
    this.keyLight.position.copy(center).add(new THREE.Vector3(shadowSpan * 0.9, shadowSpan * 2.0, shadowSpan * 1.1));
    this.keyLight.target.position.copy(center);
    this.keyLight.target.updateMatrixWorld();
    this.scene.add(this.keyLight.target);

    this.scene.fog.near = dist * 2.2;
    this.scene.fog.far = dist * 8;
    this.setView('iso', true);
  }

  setView(name, animate = true) {
    if (!this._home) return;
    const dir = (VIEW_DIRS[name] || VIEW_DIRS.iso).clone().normalize();
    const center = this.bbox ? this.bbox.center : new THREE.Vector3();
    const target = center.clone();
    const pos = center.clone().add(dir.multiplyScalar(this.dist || 400));
    this._pendingView = null;
    if (animate) {
      this._from = this.camera.position.clone();
      this._fromTarget = this.controls.target.clone();
      this._to = pos;
      this._toTarget = target;
      this._progress = 0;
    } else {
      this.camera.position.copy(pos);
      this.controls.target.copy(target);
      this.camera.updateProjectionMatrix();
      this.controls.update();
    }
  }

  reset() {
    if (!this._home) return;
    this.camera.position.copy(this._home);
    this.controls.target.copy(this._homeTarget);
    this.controls.update();
  }

  setGrid(visible) {
    this.gridVisible = visible;
    this.grid.visible = visible;
    this.ground.visible = visible && this.settings.ground !== false;
  }

  setGround(visible) {
    this.ground.visible = visible;
  }

  setAxes(visible) {
    this.axesVisible = visible;
    this.axes.visible = visible;
    if (!visible) return;
    const size = this.bbox ? this.bbox.size : new THREE.Vector3(100, 100, 100);
    const length = Math.max(size.x, size.y, size.z, 20) * 0.6;
    const up = new THREE.Vector3(0, 1, 0);
    Object.entries(this.axes.userData).forEach(([key, part]) => {
      const { dir, shaft, head, label } = part;
      shaft.position.copy(dir).multiplyScalar(length * 0.5);
      shaft.scale.set(length * 0.018, length, length * 0.018);
      shaft.quaternion.setFromUnitVectors(up, dir);
      head.position.copy(dir).multiplyScalar(length * 0.93);
      head.quaternion.setFromUnitVectors(up, dir);
      head.scale.set(length * 0.048, length * 0.16, length * 0.048);
      label.position.copy(dir).multiplyScalar(length * 1.06);
      label.scale.setScalar(length * 0.13);
    });
  }

  setWireframe(on) {
    this.wireframe = on;
    if (!this.model) return;
    this.model.traverse((o) => {
      if (o.isMesh) {
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m) => { if (m) m.wireframe = on; });
      }
    });
  }

  /** Показывает каркас поверх поверхности (полигонаж). */
  setPolygons(on) {
    this.polygons = on;
    this._clearOverlays();
    if (!on) {
      this.setWireframe(false);
      return;
    }
    if (!this.model) return;
    const triangles = this.getStats().tris;
    const heavy = triangles > 150000;
    if (heavy) {
      this.setWireframe(true);
      return;
    }
    const mat = new THREE.LineBasicMaterial({
      color: 0x7fd4ff, transparent: true, opacity: 0.30, depthWrite: false,
    });
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      const geo = new THREE.WireframeGeometry(o.geometry);
      const lines = new THREE.LineSegments(geo, mat.clone());
      lines.renderOrder = 3;
      o.add(lines);
      this._overlays.push(lines);
    });
  }

  /** Режим выделения областей: клик по модели выбирает треугольники вокруг точки. */
  setSelectMode(on) {
    this.selectMode = Boolean(on);
    const el = this.renderer?.domElement;
    if (el) el.style.cursor = this.selectMode ? 'crosshair' : '';
    if (!this.selectMode) this.clearSelection();
    // Панорамирование правой кнопкой работает всегда; в режиме выделения
    // левая кнопка рисует рамку, поэтому вращение переносим на среднюю.
    this.controls.enablePan = true;
    this.controls.mouseButtons.LEFT = this.selectMode ? null : THREE.MOUSE.ROTATE;
    this.controls.mouseButtons.MIDDLE = this.selectMode ? THREE.MOUSE.ROTATE : THREE.MOUSE.DOLLY;
    this.controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
  }

  setSelectRadius(mm) {
    this.selRadius = Math.max(1, Number(mm) || 14);
  }

  _nearestRegion(point) {
    let best = -1;
    let bestDist = Infinity;
    this.selections.forEach((sel, i) => {
      const c = sel._center;
      const d = c.distanceTo(point);
      if (d < bestDist) { bestDist = d; best = i; }
    });
    return { index: best, distance: bestDist };
  }

  _selectRegion(hit, additive = false) {
    const mesh = hit.object;
    const geo = mesh.geometry;
    if (!geo || !geo.attributes || !geo.attributes.position) return null;
    mesh.updateMatrixWorld(true);
    const m = mesh.matrixWorld;
    const pos = geo.attributes.position;
    const idx = geo.index;
    const total = idx ? Math.floor(idx.count / 3) : Math.floor(pos.count / 3);
    const radius = this.selRadius;
    const center = hit.point.clone();
    const stride = total > 300000 ? Math.ceil(total / 300000) : 1;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    const mid = new THREE.Vector3(), ab = new THREE.Vector3(), ac = new THREE.Vector3();
    const out = [];
    let area = 0;
    let count = 0;
    const box = new THREE.Box3();
    for (let t = 0; t < total; t += stride) {
      const i0 = idx ? idx.getX(t * 3) : t * 3;
      const i1 = idx ? idx.getX(t * 3 + 1) : t * 3 + 1;
      const i2 = idx ? idx.getX(t * 3 + 2) : t * 3 + 2;
      a.fromBufferAttribute(pos, i0).applyMatrix4(m);
      b.fromBufferAttribute(pos, i1).applyMatrix4(m);
      c.fromBufferAttribute(pos, i2).applyMatrix4(m);
      mid.copy(a).add(b).add(c).multiplyScalar(1 / 3);
      if (mid.distanceTo(center) > radius) continue;
      out.push(a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z);
      ab.subVectors(b, a); ac.subVectors(c, a);
      area += ab.cross(ac).length() * 0.5;
      box.expandByPoint(a); box.expandByPoint(b); box.expandByPoint(c);
      count += 1;
    }
    if (!count) return null;
    return this._commitRegion(mesh.name || mesh.parent?.name || 'деталь', out, count, area,
                              box, center, radius, additive);
  }

  /** Добавляет выделенную область и её подсветку. */
  _commitRegion(name, vertices, count, area, box, point, radius, additive = false) {
    if (!count) return null;
    if (!additive) this.clearSelection();
    const size = new THREE.Vector3();
    const ctr = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(ctr);
    const overlay = this._addSelectionOverlay(vertices, this.selections.length);
    // GLB хранится в Y-up, а сценарий — в Z-up: переводим координаты обратно.
    const sel = {
      object: name,
      tris: count,
      area_mm2: area,
      center: [ctr.x, -ctr.z, ctr.y],
      size: [size.x, size.z, size.y],
      bbox: [box.min.x, -box.max.z, box.min.y, box.max.x, -box.min.z, box.max.y],
      radius,
      point: [point.x, -point.z, point.y],
      _center: ctr.clone(),
      _overlay: overlay,
    };
    this.selections.push(sel);
    this.selection = sel;
    return sel;
  }

  _addSelectionOverlay(vertices, index) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    const palette = [0xff5a5a, 0xffb35a, 0x7dff8f, 0x5ac8ff, 0xc78bff, 0xff6bd6];
    const mat = new THREE.MeshBasicMaterial({
      color: palette[index % palette.length], transparent: true, opacity: 0.45,
      side: THREE.DoubleSide, depthTest: false, depthWrite: false,
    });
    const hl = new THREE.Mesh(g, mat);
    hl.renderOrder = 900;
    this.scene.add(hl);
    this._selOverlays.push(hl);
    return hl;
  }

  _removeSelectionAt(point) {
    const { index, distance } = this._nearestRegion(point);
    if (index < 0) return;
    const sel = this.selections[index];
    const limit = Math.max(this.selRadius * 2.2, Math.max(...sel.size) * 0.75);
    if (distance > limit) return;
    this._disposeSelection(sel);
    this.selections.splice(index, 1);
    this.selection = this.selections[this.selections.length - 1] || null;
  }

  _disposeSelection(sel) {
    if (!sel?._overlay) return;
    this.scene.remove(sel._overlay);
    sel._overlay.geometry?.dispose();
    sel._overlay.material?.dispose();
    this._selOverlays = this._selOverlays.filter((o) => o !== sel._overlay);
    sel._overlay = null;
  }

  _disposeSelOverlay() {
    this._selOverlays.forEach((o) => {
      this.scene.remove(o);
      o.geometry?.dispose();
      o.material?.dispose();
    });
    this._selOverlays = [];
    this.selections.forEach((s) => { s._overlay = null; });
  }

  clearSelection() {
    this._disposeSelOverlay();
    this.selections = [];
    this.selection = null;
  }

  /** Суммарные данные по всем выделенным областям. */
  selectionSummary() {
    if (!this.selections.length) return null;
    let tris = 0, area = 0;
    const box = new THREE.Box3();
    this.selections.forEach((s) => {
      tris += s.tris;
      area += s.area_mm2;
      const b = s.bbox;
      box.expandByPoint(new THREE.Vector3(b[0], b[2], -b[1]));
      box.expandByPoint(new THREE.Vector3(b[3], b[5], -b[4]));
    });
    const size = new THREE.Vector3();
    const center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);
    const objects = [...new Set(this.selections.map((s) => s.object))];
    return {
      object: objects.join(', '),
      regions: this.selections.length,
      tris,
      area_mm2: area,
      center: [center.x, center.y, center.z],
      size: [size.x, size.y, size.z],
      bbox: [box.min.x, -box.max.z, box.min.y, box.max.x, -box.min.z, box.max.y],
      points: this.selections.map((s) => s.point),
      centers: this.selections.map((s) => s.center),
      radius: this.selRadius,
    };
  }

  /** Скрыть/показать объект сцены по имени. */
  setObjectVisible(name, visible) {
    if (!name) return;
    if (visible) this.hidden.delete(name);
    else this.hidden.add(name);
    if (!this.model) return;
    let found = 0;
    this.model.traverse((o) => {
      if (!meshMatches(o, name)) return;
      o.visible = Boolean(visible);
      found += 1;
    });
    if (found && visible) this.model.updateMatrixWorld(true);
    return found;
  }

  /** Меши объекта по имени (для подсветки и наведения камеры). */
  objectMeshes(name) {
    const out = [];
    if (!this.model || !name) return out;
    this.model.traverse((o) => { if (meshMatches(o, name)) out.push(o); });
    return out;
  }

  /** Подсветка выбранного объекта: свечение + рамка вокруг детали. */
  setHighlight(name) {
    this.clearHighlight();
    if (!name || !this.model) return false;
    const meshes = this.objectMeshes(name);
    if (!meshes.length) return false;
    this.highlightName = name;
    this._highlight = [];
    const box = new THREE.Box3();
    meshes.forEach((o) => {
      box.expandByObject(o);
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => {
        if (!m) return;
        if (!m.userData.baseEmissive) {
          m.userData.baseEmissive = {
            color: m.emissive ? m.emissive.clone() : null,
            intensity: m.emissiveIntensity ?? 1,
          };
        }
        if (m.emissive) {
          m.emissive.setHex(0x2f6bff);
          m.emissiveIntensity = 0.45;
        }
        this._highlight.push(m);
      });
    });
    if (!box.isEmpty()) {
      const pad = Math.max(0.5, box.getSize(new THREE.Vector3()).length() * 0.008);
      box.expandByScalar(pad);
      this._highlightBox = new THREE.Box3Helper(box, 0x6fb3ff);
      this._highlightBox.material.transparent = true;
      this._highlightBox.material.opacity = 0.75;
      this._highlightBox.material.depthWrite = false;
      this.scene.add(this._highlightBox);
    }
    return true;
  }

  clearHighlight() {
    (this._highlight || []).forEach((m) => {
      const base = m.userData.baseEmissive;
      if (!base) return;
      if (m.emissive && base.color) m.emissive.copy(base.color);
      m.emissiveIntensity = base.intensity;
    });
    this._highlight = [];
    if (this._highlightBox) {
      this.scene.remove(this._highlightBox);
      this._highlightBox.geometry?.dispose?.();
      this._highlightBox.material?.dispose?.();
      this._highlightBox = null;
    }
    this.highlightName = null;
  }

  /** Наводит камеру на объект — удобно, когда деталь выбрана в списке. */
  focusObject(name) {
    const meshes = this.objectMeshes(name);
    if (!meshes.length) return false;
    const box = new THREE.Box3();
    meshes.forEach((o) => box.expandByObject(o));
    if (box.isEmpty()) return false;
    const center = new THREE.Vector3();
    const size = new THREE.Vector3();
    box.getCenter(center);
    box.getSize(size);
    const radius = Math.max(size.length() * 0.5, 5);
    const dist = radius / Math.tan((this.camera.fov * Math.PI) / 360) * 1.8;
    const dir = VIEW_DIRS.iso.clone().normalize();
    this._from = this.camera.position.clone();
    this._to = center.clone().add(dir.multiplyScalar(dist));
    this._fromTarget = this.controls.target.clone();
    this._toTarget = center.clone();
    this._progress = 0;
    return true;
  }

  /** Наложить текстуру на объект; normalUrl — карта рельефа (необязательно). */
  setTexture(name, url, normalUrl = '') {
    if (!this.model || !name) return;
    new THREE.TextureLoader().load(url, (tex) => {
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.wrapS = THREE.RepeatWrapping;
      tex.wrapT = THREE.RepeatWrapping;
      tex.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
      tex.needsUpdate = true;
      if (normalUrl) {
        new THREE.TextureLoader().load(normalUrl, (nt) => {
          nt.wrapS = THREE.RepeatWrapping;
          nt.wrapT = THREE.RepeatWrapping;
          nt.needsUpdate = true;
          this.model.traverse((o) => {
            if (!meshMatches(o, name)) return;
            const mats = Array.isArray(o.material) ? o.material : [o.material];
            mats.forEach((m) => {
              if (!m) return;
              m.normalMap = nt;
              m.normalScale = new THREE.Vector2(0.8, 0.8);
              m.needsUpdate = true;
            });
          });
        }, undefined, () => {});
      }
      this.model.traverse((o) => {
        if (!meshMatches(o, name)) return;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m) => {
          if (!m) return;
          if (!m.userData.base) {
            m.userData.base = { color: m.color?.clone() || null, metal: m.metalness,
                                rough: m.roughness, map: m.map, normal: m.normalMap };
          }
          m.map = tex;
          m.color?.setHex(0xffffff);
          m.userData.base.map = tex;
          m.needsUpdate = true;
        });
      });
    }, undefined, () => { this.onTextureError?.(name); });
  }

  clearTexture(name) {
    if (!this.model || !name) return;
    this.model.traverse((o) => {
      if (!meshMatches(o, name)) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => {
        if (!m) return;
        m.map = null;
        m.normalMap = null;
        if (m.userData.base?.color) m.color?.copy(m.userData.base.color);
        m.needsUpdate = true;
      });
    });
  }

  setSpin(on) {
    this.controls.autoRotate = on;
    this.controls.autoRotateSpeed = 1.6;
  }

  setShading(mode) {
    this.shading = mode || 'realistic';
    if (!this.model) return;
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => {
        if (!m) return;
        if (!m.userData.base) {
          m.userData.base = { color: m.color ? m.color.clone() : null, metal: m.metalness, rough: m.roughness, map: m.map };
        }
        const b = m.userData.base;
        m.wireframe = false;
        if (mode === 'clay') {
          m.color?.setHex(0xd8d2c6);
          m.metalness = 0.0; m.roughness = 0.62;
          m.map = null;
        } else if (mode === 'metal') {
          m.color?.setHex(0xc9d2dd);
          m.metalness = 1.0; m.roughness = 0.22;
          m.map = b.map;
        } else if (mode === 'flat') {
          m.color?.copy(b.color || new THREE.Color(0xffffff));
          m.metalness = 0.0; m.roughness = 0.85;
          m.map = b.map;
        } else if (mode === 'wire') {
          m.wireframe = true;
        } else {
          m.color?.copy(b.color || new THREE.Color(0xffffff));
          m.metalness = b.metal ?? 0;
          m.roughness = b.rough ?? 0.5;
          m.map = b.map;
        }
        m.needsUpdate = true;
      });
    });
  }

  applyMaterial(name, { color, metal, rough }) {
    if (!this.model || !name) return;
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      if (o.name !== name && o.parent?.name !== name) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => {
        if (!m) return;
        if (!m.userData.base) {
          m.userData.base = { color: m.color?.clone() || null, metal: m.metalness, rough: m.roughness, map: m.map };
        }
        if (color) m.color?.set(color);
        if (metal !== undefined && metal !== null) m.metalness = metal;
        if (rough !== undefined && rough !== null) m.roughness = rough;
        if (color) m.userData.base.color = new THREE.Color(color);
        m.needsUpdate = true;
      });
    });
  }

  applySettings(settings) {
    this.settings = Object.assign({}, this.settings, settings || {});
    const s = this.settings;
    const env = ENV_PRESETS[s.env] || ENV_PRESETS.studio;
    const bg = s.bg || env.bg;
    this.scene.background = new THREE.Color(bg);
    this.scene.fog.color.set(bg);
    this.scene.fog.near = this.dist ? this.dist * 2.2 : 4000;
    this.scene.fog.far = this.dist ? this.dist * 8 : 9000;
    this.ground.material.color.set(env.ground);
    this.hemi.intensity = s.ambient !== undefined ? Number(s.ambient) : env.hemi;
    // нижняя граница освещённости: тёмных «провалов» внутри модели нет
    if (this.ambient) {
      const hemi = s.ambient !== undefined ? Number(s.ambient) : env.hemi;
      this.ambient.intensity = Math.max(0.18, hemi * 0.45);
    }
    this.keyLight.color.set(env.key);
    this.fillLight.color.set(env.fill);
    this.rimLight.color.set(env.rim);
    this.keyLight.intensity = Number(s.key ?? 2.5);
    this.fillLight.intensity = Number(s.fill ?? 0.75);
    this.rimLight.intensity = Number(s.rim ?? 0.5);
    this.bounceLight.intensity = Number(s.bounce ?? 1.15);
    this.renderer.toneMappingExposure = Number(s.exposure ?? 1.05);
    this.renderer.shadowMap.enabled = s.shadows !== false;
    this.keyLight.castShadow = s.shadows !== false;
    this.grid.visible = (s.grid !== false) && this.gridVisible;
    this.ground.visible = s.ground !== false;
    if (this.model) {
      this.model.traverse((o) => {
        if (!o.isMesh) return;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m) => { if (m) m.envMapIntensity = s.env === 'void' ? 0.4 : 1.15; });
      });
    }
  }

  setBackground(hex) {
    this.settings.bg = hex;
    this.scene.background = new THREE.Color(hex);
    this.scene.fog.color.set(hex);
  }

  setExposure(v) {
    this.settings.exposure = v;
    this.renderer.toneMappingExposure = v;
  }

  setEnv(name) {
    const env = ENV_PRESETS[name] || ENV_PRESETS.studio;
    this.settings.env = name;
    this.settings.key = env.key === '#ffffff' && name === 'soft' ? 1.9 : this.settings.key;
    this.applySettings({ env: name, bg: env.bg, ambient: env.hemi });
  }

  getStats() {
    let tris = 0;
    let verts = 0;
    let meshes = 0;
    if (this.model) {
      this.model.traverse((o) => {
        if (!o.isMesh) return;
        meshes += 1;
        const g = o.geometry;
        if (!g) return;
        const count = g.index ? g.index.count : (g.attributes?.position?.count || 0);
        tris += Math.floor(count / 3);
        verts += g.attributes?.position?.count || 0;
      });
    }
    return { tris, verts, meshes, fps: this._lastFps };
  }

  screenshot() {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL('image/png');
  }
}
