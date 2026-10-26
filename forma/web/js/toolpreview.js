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
import { wheelZoom } from './viewzoom.js';
import { loadGlb } from './glb.js';

const CARD_W = 480;
const CARD_H = 360;

/** Режет строку по словам под ширину, не больше `maxLines` строк. */
function wrapText(ctx, text, maxWidth, maxLines) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let current = '';
  for (const word of words) {
    const probe = current ? `${current} ${word}` : word;
    if (ctx.measureText(probe).width > maxWidth && current) {
      lines.push(current);
      current = word;
      if (lines.length === maxLines) break;
    } else {
      current = probe;
    }
  }
  if (lines.length < maxLines && current) lines.push(current);
  if (!lines.length) lines.push('');
  // если не влезло — многоточие в последней строке
  const used = lines.join(' ');
  if (used.length < String(text).length && lines.length) {
    lines[lines.length - 1] = `${lines[lines.length - 1].replace(/[\s,;.]+$/, '')}…`;
  }
  return lines;
}

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
    const job = loadGlb(this.loader, url).then((gltf) => {
      const root = gltf.scene;
      root.traverse((o) => {
        if (!o.isMesh) return;
        const mats = Array.isArray(o.material) ? o.material : [o.material];
        mats.forEach((m) => { if (m) m.envMapIntensity = 1.2; });
      });
      this._models.set(url, root);
      return root;
    }).catch(() => null).finally(() => this._pending.delete(url));
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

  /**
   * Пометка «здесь модель не построилась».
   *
   * Вместо голого «нет модели» пишем причину: какой параметр вышел из рамок и
   * какие у него границы. Полный текст (с подсказкой) остаётся в title —
   * наведите мышью, чтобы прочитать целиком.
   */
  fail(canvas, info = '') {
    if (!canvas) return;
    const reason = typeof info === 'string' ? info : (info.reason || '');
    const bounds = typeof info === 'string' ? '' : (info.bounds || '');
    canvas.dataset.failed = reason || '1';
    canvas.title = typeof info === 'string'
      ? (reason || 'Деталь не построилась')
      : [info.title || 'Деталь не построилась', info.hint || ''].filter(Boolean).join('\n');
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const label = 'нет модели';
    const small = Math.round(h / 13);
    const line = Math.round(small * 1.5);
    ctx.font = `600 ${Math.round(h / 14)}px sans-serif`;
    ctx.fillStyle = 'rgba(190, 122, 122, 0.9)';
    ctx.fillText(label, w / 2, h / 2 - line * 1.6);

    ctx.font = `${small}px sans-serif`;
    ctx.fillStyle = 'rgba(168, 178, 194, 0.92)';
    const lines = wrapText(ctx, reason || 'деталь не построилась', w - 70, 3);
    lines.forEach((text, i) => {
      ctx.fillText(text, w / 2, h / 2 - line * 0.3 + i * line);
    });
    if (bounds) {
      ctx.fillStyle = 'rgba(150, 160, 176, 0.8)';
      ctx.fillText(`допустимо: ${bounds}`, w / 2, h / 2 + line * (lines.length - 0.3) + line * 0.7);
    }
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
      const next = wheelZoom(view.zoom, e.deltaY, e.deltaMode);
      if (Math.abs(next - view.zoom) < 1e-4) return;
      view.zoom = next;
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
      if (!this.enabled) { this._queue.length = 0; break; }
      const canvas = this._queue.shift();
      const view = this._views.get(canvas);
      if (!view || !view.url) continue;
      // карточка ушла из вида — не тратим время
      if (!canvas.offsetParent) continue;
      const renderer = this._ensure();
      if (!renderer) { this.fail(canvas); continue; }
      const model = await this._loadModel(view.url);
      if (!this.enabled || !canvas.offsetParent) continue;
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
