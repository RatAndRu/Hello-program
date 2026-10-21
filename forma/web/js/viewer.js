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

    this.axes = new THREE.AxesHelper(80);
    this.axes.material.transparent = true;
    this.axes.material.opacity = 0.55;
    this.axes.visible = false;
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
      if (hits.length && this.onSelect) {
        const mesh = hits[0].object;
        this.onSelect(mesh.name || mesh.parent?.name || '');
      } else if (!hits.length && this.onSelect) {
        this.onSelect('');
      }
    });
    el.addEventListener('dblclick', () => this.reset());
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
  }

  _clearOverlays() {
    this._overlays.forEach((o) => {
      o.geometry?.dispose();
      o.material?.dispose();
      o.parent?.remove(o);
    });
    this._overlays = [];
  }

  async load(url) {
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
    this.applyShading(this.shading);
    this.applySettings(this.settings);
    this._setupAnimation(gltf);
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
    return Boolean(this.action);
  }

  playAnimation(playing = true) {
    this.playing = playing;
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
    this.axes.visible = visible;
    if (this.bbox) this.axes.scale.setScalar(Math.max(this.bbox.size.length() * 0.18, 40) / 80);
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
