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
    this.playing = false;
    this.speed = 1;
    this.loop = true;
    this._overlays = [];
    this._selOverlays = [];
    this.selectMode = false;
    this.selRadius = 14;
    this.selection = null;
    this.selections = [];
    this.hidden = new Set();
    this.sceneAnimation = null;
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

    this.hemi = new THREE.HemisphereLight(0xdfe9ff, 0x1a1f26, 0.55);
    scene.add(this.hemi);

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
      if (this.mixer) this.mixer.update(dt * this.speed);
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
    el.addEventListener('pointerdown', (e) => {
      down = { x: e.clientX, y: e.clientY, t: performance.now() };
    });
    el.addEventListener('pointerup', (e) => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      const quick = performance.now() - down.t < 420;
      down = null;
      if (moved > 5 || !quick || !this.model) return;
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
          if (!e.shiftKey && !e.ctrlKey && !e.metaKey) {
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
    el.addEventListener('dblclick', () => this.reset());
  }

  _updateExplode() {
    if (!this._explodeTargets || !this.action || this.sceneAnimation?.kind !== 'explode') return;
    const t = this.action.time / Math.max(0.2, Number(this.sceneAnimation.seconds) || 4);
    const e = Math.sin(Math.min(1, t) * Math.PI * 0.5);
    this._explodeTargets.forEach(({ node, dir }) => {
      node.position.set(dir.x * e, dir.y * e, dir.z * e);
    });
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
    this.model = null;
    this.mixer = null;
    this.action = null;
    this.playing = false;
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
    this._fit(root);
    this.setAxes(this.axesVisible);
    this.applyShading(this.shading);
    this.applySettings(this.settings);
    this._setupAnimation(gltf);
    if (animation && animation.kind) {
      // сценарий — источник истины: своя анимация работает даже если GLB её потерял
      this.applySceneAnimation(animation);
      this.playing = true;
    }
    this.hidden.forEach((name) => this.setObjectVisible(name, false));
    this.setPolygons(this.polygons);
    return this.bbox;
  }

  _setupAnimation(gltf) {
    this.mixer = null;
    this.action = null;
    if (!gltf.animations || !gltf.animations.length) return;
    this.mixer = new THREE.AnimationMixer(this.model);
    const clip = gltf.animations[0];
    this.clipDuration = clip.duration;
    this.action = this.mixer.clipAction(clip);
    this.action.setLoop(this.loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
    this.action.clampWhenFinished = !this.loop;
    if (this.playing) this.action.play();
  }

  hasAnimation() {
    return Boolean(this.action || this.sceneAnimation);
  }

  playAnimation(playing = true) {
    this.playing = playing;
    if (!this.action && this.sceneAnimation) {
      this.applySceneAnimation(this.sceneAnimation);
      this.action.paused = !playing;
      return;
    }
    if (!this.action) return;
    if (playing) {
      this.action.reset();
      this.action.paused = false;
      this.action.play();
    } else {
      this.action.paused = true;
    }
  }

  restartAnimation() {
    if (!this.action) return;
    this.action.reset();
    this.action.paused = false;
    this.action.play();
    this.playing = true;
  }

  setSpeed(v) {
    this.speed = Math.max(0.05, Math.min(8, v));
  }

  setLoop(loop) {
    this.loop = Boolean(loop);
    if (!this.action) return;
    this.action.setLoop(this.loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
    this.action.clampWhenFinished = !this.loop;
  }

  _fit(root) {
    const box = new THREE.Box3().setFromObject(root);
    if (box.isEmpty()) return;
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
    if (this.selectMode) this.controls.enablePan = false;
    else this.controls.enablePan = true;
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
    if (!additive) this.clearSelection();
    const size = new THREE.Vector3();
    const ctr = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(ctr);
    const overlay = this._addSelectionOverlay(out, this.selections.length);
    // GLB хранится в Y-up, а сценарий — в Z-up: переводим координаты обратно.
    const sel = {
      object: mesh.name || mesh.parent?.name || 'деталь',
      tris: count,
      area_mm2: area,
      center: [ctr.x, -ctr.z, ctr.y],
      size: [size.x, size.z, size.y],
      bbox: [box.min.x, -box.max.z, box.min.y, box.max.x, -box.min.z, box.max.y],
      radius: radius,
      point: [center.x, -center.z, center.y],
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
    if (!this.model || !name) return;
    if (visible) this.hidden.delete(name);
    else this.hidden.add(name);
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      const objName = o.name || o.parent?.name;
      if (objName === name) o.visible = visible;
    });
  }

  /** Наложить текстуру на объект (картинка уже загружена). */
  setTexture(name, url) {
    if (!this.model || !name) return;
    new THREE.TextureLoader().load(url, (tex) => {
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.wrapS = THREE.RepeatWrapping;
      tex.wrapT = THREE.RepeatWrapping;
      tex.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
      tex.needsUpdate = true;
      this.model.traverse((o) => {
        if (!o.isMesh) return;
        if (o.name !== name && o.parent?.name !== name) return;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m) => {
          if (!m) return;
          if (!m.userData.base) {
            m.userData.base = { color: m.color?.clone() || null, metal: m.metalness, rough: m.roughness, map: m.map };
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
      if (!o.isMesh) return;
      if (o.name !== name && o.parent?.name !== name) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => {
        if (!m) return;
        m.map = null;
        if (m.userData.base?.color) m.color?.copy(m.userData.base.color);
        m.needsUpdate = true;
      });
    });
  }

  /** Анимация из сценария: гарантированно работает, даже если GLB её не отдал. */
  applySceneAnimation(spec) {
    this.sceneAnimation = spec || null;
    if (!spec || !this.model) return;
    const kind = spec.kind || 'spin';
    const seconds = Math.max(0.2, Number(spec.seconds) || 4);
    const axis = (spec.axis || 'z').toLowerCase();
    const loop = spec.loop !== false;
    this.mixer = new THREE.AnimationMixer(this.model);
    const times = [0, seconds];
    const tracks = [];
    if (kind === 'spin') {
      const target = this.model.children[0] || this.model;
      target.name = target.name || 'FormaSpinTarget';
      const euler = { x: 0, y: 0, z: 0 };
      // axis — ось из сценария (Z вверх), в окне модель стоит в Y-up
      if (axis === 'x') euler.x = Math.PI * 2;
      else if (axis === 'y') euler.z = Math.PI * 2;
      else euler.y = -Math.PI * 2;
      const q0 = new THREE.Quaternion();
      const q1 = new THREE.Quaternion().setFromEuler(new THREE.Euler(euler.x, euler.y, euler.z));
      tracks.push(new THREE.QuaternionKeyframeTrack(
        `${target.name}.quaternion`, times, [...q0.toArray(), ...q1.toArray()]));
    } else if (kind === 'formation') {
      this.model.scale.setScalar(0.001);
      this.model.updateMatrixWorld();
      tracks.push(new THREE.VectorKeyframeTrack(`${this.model.name || 'Scene'}.scale`,
        [0, seconds * 0.8, seconds], [0.001, 0.001, 0.001, 1, 1, 1, 1, 1, 1]));
      tracks.push(new THREE.VectorKeyframeTrack(`${this.model.name || 'Scene'}.position`,
        [0, seconds], [0, 60, 0, 0, 0, 0]));
    } else if (kind === 'explode') {
      const offsets = [];
      this.model.traverse((o) => {
        if (!o.isMesh) return;
        const p = o.getWorldPosition(new THREE.Vector3());
        const dir = p.clone().normalize().multiplyScalar(60);
        offsets.push({ node: o, dir });
      });
      tracks.push(new THREE.VectorKeyframeTrack(`${this.model.name || 'Scene'}.position`,
        [0, seconds], [0, 0, 0, 0, 0, 0]));
      this._explodeTargets = offsets;
    }
    if (!tracks.length) return;
    const clip = new THREE.AnimationClip('FormaScene', seconds, tracks);
    this.action = this.mixer.clipAction(clip);
    this.action.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
    this.action.clampWhenFinished = !loop;
    this.action.play();
    this.playing = true;
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
    this.keyLight.color.set(env.key);
    this.fillLight.color.set(env.fill);
    this.rimLight.color.set(env.rim);
    this.keyLight.intensity = Number(s.key ?? 2.5);
    this.fillLight.intensity = Number(s.fill ?? 0.75);
    this.rimLight.intensity = Number(s.rim ?? 0.5);
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
