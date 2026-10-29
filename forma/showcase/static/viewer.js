import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { GLTFLoader } from 'three/addons/GLTFLoader.js';

const VIEW_DIRECTIONS = {
  iso: new THREE.Vector3(1.15, 0.72, 1.35),
  front: new THREE.Vector3(0, 0.16, 1),
  side: new THREE.Vector3(1, 0.16, 0),
  top: new THREE.Vector3(0.001, 1, 0.001),
};

export class ShowcaseViewer {
  constructor(container, { onProgress } = {}) {
    this.container = container;
    this.onProgress = onProgress || (() => {});
    this.disposed = false;
    this.paused = false;
    this.needsRender = true;
    this.raf = 0;
    this.model = null;
    this.grid = null;

    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.12;
    this.renderer.setClearColor(0x0b1016, 1);
    container.prepend(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b1016);
    this.camera = new THREE.PerspectiveCamera(37, 1, 0.1, 10000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.09;
    this.controls.rotateSpeed = 0.75;
    this.controls.zoomSpeed = 0.85;
    this.controls.panSpeed = 0.65;
    this.controls.autoRotateSpeed = 0.65;
    this.controls.addEventListener('change', () => this.requestRender());

    const hemisphere = new THREE.HemisphereLight(0xe4efff, 0x273229, 1.65);
    this.scene.add(hemisphere);
    const key = new THREE.DirectionalLight(0xffffff, 2.8);
    key.position.set(1, 2, 1.4);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x9fc8ff, 1.15);
    fill.position.set(-1.5, 0.5, -1);
    this.scene.add(fill);
    const rim = new THREE.DirectionalLight(0xb8ffe1, 0.75);
    rim.position.set(-0.5, 1.2, 1.5);
    this.scene.add(rim);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.tick = this.tick.bind(this);
    this.tick();
  }

  resize() {
    if (this.disposed) return;
    const width = Math.max(2, this.container.clientWidth);
    const height = Math.max(2, this.container.clientHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.requestRender();
  }

  requestRender() {
    this.needsRender = true;
  }

  tick() {
    if (this.disposed || this.paused) return;
    this.raf = requestAnimationFrame(this.tick);
    if (document.hidden) return;
    const changed = this.controls.update();
    if (this.needsRender || changed || this.controls.autoRotate) {
      this.renderer.render(this.scene, this.camera);
      this.needsRender = false;
    }
  }

  pause() {
    this.paused = true;
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  resume() {
    if (this.disposed || !this.paused) return;
    this.paused = false;
    this.requestRender();
    this.tick();
  }

  async load(url) {
    const loader = new GLTFLoader();
    const gltf = await loader.loadAsync(url, (event) => {
      this.onProgress(event.loaded || 0, event.total || 0);
    });
    if (this.disposed) {
      this.disposeObject(gltf.scene);
      return;
    }
    this.clearModel();
    this.model = gltf.scene;
    this.model.traverse((object) => {
      if (!object.isMesh) return;
      object.frustumCulled = true;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        if (material) material.needsUpdate = true;
      }
    });
    this.scene.add(this.model);
    this.addGrid();
    this.setView('iso');
    this.requestRender();
  }

  addGrid() {
    const box = new THREE.Box3().setFromObject(this.model);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const span = Math.max(size.x, size.z, 1) * 1.5;
    this.grid = new THREE.GridHelper(span, 24, 0x385447, 0x23332e);
    this.grid.position.set(center.x, box.min.y - Math.max(size.y * 0.003, 0.01), center.z);
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.38;
    this.grid.material.depthWrite = false;
    this.scene.add(this.grid);
  }

  setView(name) {
    if (!this.model) return;
    const direction = (VIEW_DIRECTIONS[name] || VIEW_DIRECTIONS.iso).clone().normalize();
    const box = new THREE.Box3().setFromObject(this.model);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(size.length() * 0.5, 0.01);
    const distance = radius / Math.tan(THREE.MathUtils.degToRad(this.camera.fov * 0.5)) * 1.28;
    this.controls.target.copy(center);
    this.camera.position.copy(center).addScaledVector(direction, distance);
    this.camera.near = Math.max(0.01, radius / 1200);
    this.camera.far = Math.max(100, radius * 100);
    this.camera.updateProjectionMatrix();
    this.controls.minDistance = radius * 0.12;
    this.controls.maxDistance = radius * 20;
    this.controls.update();
    this.requestRender();
  }

  setWireframe(enabled) {
    if (!this.model) return;
    this.model.traverse((object) => {
      if (!object.isMesh) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        if (material) material.wireframe = enabled;
      }
    });
    this.requestRender();
  }

  setSpin(enabled) {
    this.controls.autoRotate = Boolean(enabled);
    this.requestRender();
  }

  clearModel() {
    if (this.model) {
      this.scene.remove(this.model);
      this.disposeObject(this.model);
      this.model = null;
    }
    if (this.grid) {
      this.scene.remove(this.grid);
      this.disposeObject(this.grid);
      this.grid = null;
    }
    this.requestRender();
  }

  disposeObject(root) {
    const materials = new Set();
    root.traverse((object) => {
      object.geometry?.dispose?.();
      if (object.material) {
        const list = Array.isArray(object.material) ? object.material : [object.material];
        list.forEach((material) => materials.add(material));
      }
    });
    for (const material of materials) {
      for (const value of Object.values(material)) {
        if (value?.isTexture) value.dispose();
      }
      material.dispose?.();
    }
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.resizeObserver.disconnect();
    this.clearModel();
    this.controls.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss?.();
    this.renderer.domElement.remove();
  }
}
