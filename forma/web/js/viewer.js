import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { GLTFLoader } from 'three/addons/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/RoomEnvironment.js';

const VIEW_DIRS = {
  iso: new THREE.Vector3(0.95, 0.72, 1.0),
  front: new THREE.Vector3(0, 0.18, 1),
  right: new THREE.Vector3(1, 0.18, 0),
  top: new THREE.Vector3(0, 1, 0.001),
};

export class Viewer {
  constructor(container) {
    this.container = container;
    this.renderer = null;
    this.model = null;
    this.wireframe = false;
    this.gridVisible = true;
    this.ready = false;
    this.lastUrl = null;
    this.bbox = null;
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
    renderer.domElement.style.width = '100%';
    renderer.domElement.style.height = '100%';
    this.container.appendChild(renderer.domElement);
    this.renderer = renderer;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0e13);
    scene.fog = new THREE.Fog(0x0b0e13, 4000, 9000);
    this.scene = scene;

    const pmrem = new THREE.PMREMGenerator(renderer);
    this.envTexture = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = this.envTexture;

    this.camera = new THREE.PerspectiveCamera(34, 1, 1, 20000);
    this.camera.position.set(300, 260, 380);

    this.controls = new OrbitControls(this.camera, renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.rotateSpeed = 0.85;
    this.controls.panSpeed = 0.8;
    this.controls.zoomSpeed = 0.9;
    this.controls.maxPolarAngle = Math.PI * 0.98;
    this.controls.minDistance = 5;
    this.controls.maxDistance = 15000;

    const hemi = new THREE.HemisphereLight(0xdfe9ff, 0x1a1f26, 0.55);
    scene.add(hemi);

    const key = new THREE.DirectionalLight(0xffffff, 2.5);
    key.position.set(320, 620, 420);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.6;
    this.keyLight = key;
    scene.add(key);

    const fill = new THREE.DirectionalLight(0x9dbcff, 0.75);
    fill.position.set(-420, 260, -260);
    scene.add(fill);

    const rim = new THREE.DirectionalLight(0xffe6c4, 0.5);
    rim.position.set(60, 180, -520);
    scene.add(rim);

    // «пол» со мягкой тенью
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
    scene.add(this.grid);

    this.axes = new THREE.AxesHelper(60);
    this.axes.material.transparent = true;
    this.axes.material.opacity = 0.35;
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
      renderer.render(scene, this.camera);
    };
    loop();
    this.ready = true;
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
    return this.bbox;
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

    // пол и сетка под модель
    const span = Math.max(size.x, size.z, 20);
    const gridSize = Math.pow(10, Math.ceil(Math.log10(span * 2.4)));
    const divisions = 20;
    this.scene.remove(this.grid);
    this.grid.geometry.dispose();
    this.grid.material.dispose();
    this.grid = new THREE.GridHelper(gridSize, divisions, 0x33465e, 0x1d2733);
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.9;
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
    this.ground.visible = visible;
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

  setSpin(on) {
    this.controls.autoRotate = on;
    this.controls.autoRotateSpeed = 1.6;
  }

  screenshot() {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL('image/png');
  }
}
