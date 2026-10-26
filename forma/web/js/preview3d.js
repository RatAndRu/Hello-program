/**
 * Маленькое 3D-окно для превью деталей из «Инструментов».
 *
 * Отдельный лёгкий рендерер: своя сцена, свой GLTFLoader, OrbitControls.
 * Пока окно закрыто, кадры не считаются — превью не тратит ресурсы.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { GLTFLoader } from 'three/addons/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/RoomEnvironment.js';
import { loadGlb } from './glb.js';

export class Preview3D {
  constructor(container) {
    this.container = container;
    this.spin = true;
    this.wire = false;
    this.model = null;
    this.ready = false;
    this._dead = false;
    this._frame = 0;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    renderer.domElement.style.display = 'block';
    container.appendChild(renderer.domElement);
    this.renderer = renderer;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x11161f);
    scene.fog = new THREE.Fog(0x11161f, 3000, 8000);
    this.scene = scene;

    const pmrem = new THREE.PMREMGenerator(renderer);
    this.envTexture = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = this.envTexture;

    this.camera = new THREE.PerspectiveCamera(36, 1, 1, 40000);
    this.camera.position.set(240, 190, 280);

    const controls = new OrbitControls(this.camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.09;
    controls.rotateSpeed = 0.9;
    controls.zoomSpeed = 0.9;
    controls.panSpeed = 0.7;
    controls.maxPolarAngle = Math.PI * 0.995;
    controls.minDistance = 5;
    controls.maxDistance = 20000;
    controls.addEventListener('start', () => { this._userMoved = true; });
    this.controls = controls;

    scene.add(new THREE.HemisphereLight(0xdfe9ff, 0x20242c, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(320, 480, 260);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x9fc0ff, 0.8);
    fill.position.set(-260, 120, -200);
    scene.add(fill);
    this.keyLight = key;

    const ground = new THREE.Mesh(
      new THREE.CircleGeometry(2000, 64),
      new THREE.MeshStandardMaterial({ color: 0x1a212b, roughness: 0.96, metalness: 0.0 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.01;
    ground.receiveShadow = true;
    scene.add(ground);

    const grid = new THREE.GridHelper(1200, 24, 0x2c3a4d, 0x1f2936);
    grid.position.y = 0.02;
    scene.add(grid);
    this.grid = grid;

    this._onResize = () => this.resize();
    this._observer = new ResizeObserver(this._onResize);
    this._observer.observe(container);
    this._tick = this._tick.bind(this);
    this._raf = requestAnimationFrame(this._tick);
    this.ready = true;
  }

  resize() {
    if (!this.renderer) return;
    const w = Math.max(2, this.container.clientWidth || 640);
    const h = Math.max(2, this.container.clientHeight || 420);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _tick() {
    if (this._dead) return;
    this._raf = requestAnimationFrame(this._tick);
    if (document.hidden) return;
    // окно закрыто — не тратим кадры впустую
    if (!this.container.offsetParent) return;
    if (this.spin && this.model && !this._userMoved) {
      this.model.rotation.y += 0.006;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  /** Загружает GLB, вписывает в кадр и запускает показ. */
  async load(url) {
    const loader = new GLTFLoader();
    const gltf = await loadGlb(loader, url);
    if (this._dead) return;
    this.clear();
    const root = gltf.scene;
    root.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = true;
      o.receiveShadow = true;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => {
        if (!m) return;
        m.envMapIntensity = 1.15;
        m.side = THREE.FrontSide;
        m.needsUpdate = true;
      });
    });
    // модель ставим на «пол» по её нижней точке — так превью читается
    const box = new THREE.Box3().setFromObject(root);
    const size = new THREE.Vector3();
    const center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);
    const wrap = new THREE.Group();
    wrap.add(root);
    root.position.set(-center.x, -box.min.y, -center.z);
    this.scene.add(wrap);
    this.model = wrap;
    this.bbox = { size, center };
    this.fit();
    this._userMoved = false;
    return gltf;
  }

  /** Вписывает модель в окно с текущего направления камеры. */
  fit() {
    if (!this.model) return;
    const box = new THREE.Box3().setFromObject(this.model);
    if (box.isEmpty()) return;
    const size = new THREE.Vector3();
    const center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);
    const radius = Math.max(size.length() * 0.5, 10);
    const dist = radius / Math.tan((this.camera.fov * Math.PI) / 360) * 1.5;
    const dir = new THREE.Vector3(0.9, 0.62, 1.0).normalize();
    this.camera.position.copy(center).addScaledVector(dir, dist);
    this.camera.near = Math.max(0.5, radius / 200);
    this.camera.far = Math.max(2000, dist * 20);
    this.camera.updateProjectionMatrix();
    this.controls.target.copy(center);
    this.controls.minDistance = radius * 0.4;
    this.controls.maxDistance = radius * 12;
    this.controls.update();
    this._userMoved = false;
  }

  setSpin(on) {
    this.spin = !!on;
    this._userMoved = false;
  }

  setWire(on) {
    this.wire = !!on;
    if (!this.model) return;
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => { if (m) m.wireframe = this.wire; });
    });
  }

  clear() {
    if (!this.model) return;
    this.scene.remove(this.model);
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      o.geometry?.dispose();
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      mats.forEach((m) => { if (m) m.dispose?.(); });
    });
    this.model = null;
  }

  dispose() {
    this._dead = true;
    cancelAnimationFrame(this._raf);
    this._observer?.disconnect();
    this.clear();
    this.grid?.geometry?.dispose();
    this.grid?.material?.dispose();
    this.envTexture?.dispose?.();
    this.controls?.dispose?.();
    this.renderer?.dispose?.();
    this.renderer?.domElement?.remove?.();
  }
}
