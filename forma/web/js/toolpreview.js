/**
 * Живые 3D-миниатюры в карточках «Инструментов».
 *
 * Одна WebGL-сцена на всю страницу, а не по контексту на карточку: браузер
 * держит всего 8–16 контекстов, а карточек десятки. Здесь модель по очереди
 * отрисовывается в общий буфер и копируется в обычный 2D-canvas карточки —
 * так миниатюру видно сразу, её можно крутить мышью, и это почти бесплатно
 * по ресурсам.
 */
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/RoomEnvironment.js';

const CARD_W = 480;
const CARD_H = 360;

export class ToolThumbs {
  constructor() {
    this.enabled = true;
    this.renderer = null;
    this.scene = null;
    this.camera = null;
    this.loader = null;
    this._models = new Map();     // url -> Object3D (прототип, не в сцене)
    this._pending = new Map();    // url -> Promise
    this._views = new WeakMap();  // canvas -> { yaw, pitch, zoom, url }
    this._queue = [];
    this._busy = false;
    this._failed = false;
    this._proxy = new THREE.Group();
  }

  /** Ленивая инициализация: без WebGL превью просто не показываем. */
  _ensure() {
    if (this.renderer || this._failed) return this.renderer;
    try {
      const renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        preserveDrawingBuffer: true,
      });
      renderer.setPixelRatio(1);
      renderer.setSize(CARD_W, CARD_H, false);
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.05;
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      this.renderer = renderer;

      const scene = new THREE.Scene();
      const pmrem = new THREE.PMREMGenerator(renderer);
      scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      scene.add(new THREE.HemisphereLight(0xdfe9ff, 0x20242c, 1.25));
      const key = new THREE.DirectionalLight(0xffffff, 2.3);
      key.position.set(320, 520, 300);
      scene.add(key);
      const fill = new THREE.DirectionalLight(0x9fc0ff, 0.85);
      fill.position.set(-300, 140, -240);
      scene.add(fill);
      scene.add(this._proxy);
      this.scene = scene;

      this.camera = new THREE.PerspectiveCamera(34, CARD_W / CARD_H, 0.5, 60000);
      this.camera.position.set(0, 0, 400);
      this.loader = new GLTFLoader();
      return renderer;
    } catch (err) {
      this._failed = true;
      return null;
    }
  }

  /** Готовит GLB один раз и раздаёт его всем карточкам с тем же сценарием. */
  _loadModel(url) {
    if (this._models.has(url)) return Promise.resolve(this._models.get(url));
    if (this._pending.has(url)) return this._pending.get(url);
    const job = new Promise((resolve) => {
      this.loader.load(url, (gltf) => {
        const root = gltf.scene;
        root.traverse((o) => {
          if (!o.isMesh) return;
          const mats = Array.isArray(o.material) ? o.material : [o.material];
          mats.forEach((m) => { if (m) m.envMapIntensity = 1.2; });
        });
        this._models.set(url, root);
        resolve(root);
      }, undefined, () => resolve(null));
    }).finally(() => this._pending.delete(url));
    this._pending.set(url, job);
    return job;
  }

  /** Показывает модель в canvas карточки. Повторный вызов — только обновление. */
  show(canvas, url, { reset = false } = {}) {
    if (!canvas) return;
    let view = this._views.get(canvas);
    if (!view) {
      view = { yaw: 0.6, pitch: 0.32, zoom: 1, url: null, box: null };
      this._views.set(canvas, view);
      this._bind(canvas, view);
    }
    if (reset) {
      view.yaw = 0.6;
      view.pitch = 0.32;
      view.zoom = 1;
    }
    if (view.url !== url) view.url = url;
    this._schedule(canvas, view);
  }

  /** Перерисовать все миниатюры (например, после смены размера окна). */
  refreshAll() {
    this._views = new WeakMap();
    document.querySelectorAll('canvas.tool-shot[data-url]').forEach((canvas) => {
      const url = canvas.dataset.url;
      if (url) this.show(canvas, url);
    });
  }

  /** Пометка «здесь модель не построилась» — карточка показывает заглушку. */
  fail(canvas, text = '') {
    if (!canvas) return;
    canvas.dataset.failed = text || '1';
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = 'rgba(150, 160, 176, 0.55)';
    ctx.font = `${Math.round(h / 9)}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('нет модели', w / 2, h / 2);
  }

  _bind(canvas, view) {
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    canvas.style.cursor = 'grab';
    canvas.addEventListener('pointerdown', (e) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      canvas.setPointerCapture?.(e.pointerId);
      canvas.style.cursor = 'grabbing';
      e.preventDefault();
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      view.yaw += (e.clientX - lastX) * 0.012;
      view.pitch = Math.max(-1.35, Math.min(1.35, view.pitch + (e.clientY - lastY) * 0.01));
      lastX = e.clientX;
      lastY = e.clientY;
      this._schedule(canvas, view);
    });
    const stop = () => { dragging = false; canvas.style.cursor = 'grab'; };
    canvas.addEventListener('pointerup', stop);
    canvas.addEventListener('pointercancel', stop);
    canvas.addEventListener('pointerleave', () => { if (dragging) stop(); });
    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      view.zoom = Math.max(0.45, Math.min(3.2, view.zoom * (e.deltaY > 0 ? 1.12 : 0.89)));
      this._schedule(canvas, view);
    }, { passive: false });
    canvas.addEventListener('dblclick', () => {
      view.yaw = 0.6;
      view.pitch = 0.32;
      view.zoom = 1;
      this._schedule(canvas, view);
    });
  }

  _schedule(canvas, view) {
    if (!this.enabled) return;
    view.dirty = true;
    if (this._queue.includes(canvas)) return;
    this._queue.push(canvas);
    if (!this._busy) this._drain();
  }

  async _drain() {
    this._busy = true;
    while (this._queue.length) {
      const canvas = this._queue.shift();
      const view = this._views.get(canvas);
      if (!view || !view.url) continue;
      // карточка ушла из вида — не тратим время
      if (!canvas.offsetParent) continue;
      const renderer = this._ensure();
      if (!renderer) { this.fail(canvas); continue; }
      const model = await this._loadModel(view.url);
      if (!model) { this.fail(canvas); continue; }
      this._paint(canvas, view, model);
      // даём браузеру вздохнуть между миниатюрами
      await new Promise((r) => setTimeout(r, 0));
    }
    this._busy = false;
  }

  _paint(canvas, view, prototype) {
    const renderer = this.renderer;
    const proxy = this._proxy;
    proxy.clear();
    const model = prototype.clone(true);
    // модель ставим на «пол» и центрируем — так масштаб одинаковый у всех
    const box = new THREE.Box3().setFromObject(model);
    if (box.isEmpty()) { this.fail(canvas); return; }
    const size = new THREE.Vector3();
    const center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);
    // Центр модели — в начало координат: тогда при вращении она крутится
    // вокруг себя, а не качается вокруг нижней точки.
    model.position.set(-center.x, -center.y, -center.z);
    const holder = new THREE.Group();
    holder.add(model);
    const radius = Math.max(size.length() * 0.5, 1);
    holder.rotation.x = view.pitch;
    holder.rotation.y = view.yaw;
    proxy.add(holder);
    // камера смотрит на центр модели; вписываем по габариту
    const dist = (radius / Math.tan((this.camera.fov * Math.PI) / 360)) * 1.12;
    this.camera.position.set(0, 0, dist / view.zoom);
    this.camera.lookAt(0, 0, 0);
    this.camera.near = Math.max(0.2, radius / 400);
    this.camera.far = Math.max(2000, dist * 24);
    this.camera.updateProjectionMatrix();
    renderer.render(this.scene, this.camera);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    // сохраняем пропорции модели: рисуем буфер целиком, он уже 4:3
    ctx.drawImage(renderer.domElement, 0, 0, w, h);
    delete canvas.dataset.failed;
    proxy.clear();
  }

  dispose() {
    this._queue.length = 0;
    this._models.forEach((m) => {
      m.traverse?.((o) => {
        if (!o.isMesh) return;
        o.geometry?.dispose();
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((mat) => mat?.dispose?.());
      });
    });
    this._models.clear();
    this.renderer?.dispose?.();
    this.renderer = null;
  }
}
