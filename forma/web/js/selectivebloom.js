/**
 * Свечение только тех деталей, у которых оно задано.
 *
 * Обычный UnrealBloomPass светится по порогу яркости: белый шар рядом с
 * светодиодом «загорается» вместе с ним, потому что его пиксели тоже ярче
 * порога. Здесь ореол строится по отдельному проходу, в который попадают
 * **только** материалы с собственным emissive и его emissiveIntensity.
 * Остальные детали в этом проходе чёрные — они перекрывают свет сзади
 * (ореол не просвечивает сквозь корпус), но сами не светятся.
 */
import * as THREE from 'three';
import { Pass, FullScreenQuad } from 'three/addons/postprocessing/Pass.js';

const BLUR_SHADER = {
  uniforms: {
    tDiffuse: { value: null },
    uDirection: { value: new THREE.Vector2(1, 0) },
    uTexel: { value: new THREE.Vector2(1 / 512, 1 / 512) },
  },
  vertexShader: `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }`,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform vec2 uDirection;
    uniform vec2 uTexel;
    varying vec2 vUv;
    void main() {
      // девять отсчётов гауссом: мягкий ореол без ступенек
      vec2 step = uDirection * uTexel;
      vec4 sum = texture2D(tDiffuse, vUv) * 0.227027;
      sum += texture2D(tDiffuse, vUv + step * 1.384615) * 0.316216;
      sum += texture2D(tDiffuse, vUv - step * 1.384615) * 0.316216;
      sum += texture2D(tDiffuse, vUv + step * 3.230769) * 0.070270;
      sum += texture2D(tDiffuse, vUv - step * 3.230769) * 0.070270;
      gl_FragColor = sum;
    }`,
};

const COMPOSITE_SHADER = {
  uniforms: {
    tDiffuse: { value: null },
    tGlow: { value: null },
    uStrength: { value: 0.6 },
    uThreshold: { value: 0.0 },
  },
  vertexShader: `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }`,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform sampler2D tGlow;
    uniform float uStrength;
    varying vec2 vUv;
    void main() {
      vec4 base = texture2D(tDiffuse, vUv);
      vec3 glow = texture2D(tGlow, vUv).rgb;
      gl_FragColor = vec4(base.rgb + glow * uStrength, base.a);
    }`,
};

export class EmissiveBloomPass extends Pass {
  constructor(scene, camera, strength = 0.6) {
    super();
    this.scene = scene;
    this.camera = camera;
    this.strength = strength;
    this.needsSwap = true;
    this._glowRT = null;
    this._blurA = null;
    this._blurB = null;
    this._size = new THREE.Vector2(1, 1);
    this._blackMat = new THREE.MeshBasicMaterial({ color: 0x000000, toneMapped: false });
    this._glowMats = new Map();      // материал → «светящаяся» копия
    this._quad = new FullScreenQuad(new THREE.ShaderMaterial(BLUR_SHADER));
    this._composite = new FullScreenQuad(new THREE.ShaderMaterial(COMPOSITE_SHADER));
  }

  setSize(width, height) {
    const w = Math.max(2, Math.floor(width / 2));
    const h = Math.max(2, Math.floor(height / 2));
    this._size.set(w, h);
    const opts = {
      type: THREE.HalfFloatType,
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      depthBuffer: true,
      stencilBuffer: false,
    };
    this._glowRT?.dispose();
    this._blurA?.dispose();
    this._blurB?.dispose();
    this._glowRT = new THREE.WebGLRenderTarget(w, h, opts);
    this._blurA = new THREE.WebGLRenderTarget(w, h, { ...opts, depthBuffer: false });
    this._blurB = new THREE.WebGLRenderTarget(w, h, { ...opts, depthBuffer: false });
    this._quad.material.uniforms.uTexel.value.set(1 / w, 1 / h);
  }

  /** Материал-копия: тот же emissive, но без освещения — светится сам. */
  _glowMaterial(material) {
    if (!material) return this._blackMat;
    const emissive = material.emissive;
    const intensity = material.emissiveIntensity ?? 1;
    const on = emissive && intensity > 0.01
      && (emissive.r + emissive.g + emissive.b) > 0.02;
    if (!on) return this._blackMat;
    if (this._glowMats.has(material)) return this._glowMats.get(material);
    const color = emissive.clone().multiplyScalar(Math.min(intensity, 6));
    const made = new THREE.MeshBasicMaterial({
      color,
      toneMapped: false,
      side: material.side,
    });
    made.name = `${material.name || 'glow'}_glow`;
    this._glowMats.set(material, made);
    return made;
  }

  render(renderer, writeBuffer, readBuffer) {
    if (!this._glowRT) this.setSize(readBuffer.width, readBuffer.height);
    const scene = this.scene;
    const prevTarget = renderer.getRenderTarget();
    const prevAutoClear = renderer.autoClear;
    const prevClear = renderer.getClearColor(new THREE.Color());
    const prevClearAlpha = renderer.getClearAlpha();
    const prevOverride = scene.overrideMaterial;
    const prevBg = scene.background;
    const prevFog = scene.fog;

    // 1. Собираем «светящуюся» версию сцены: emissive детали — свои цвета,
    //    остальные — чёрные перекрыватели, чтобы ореол не шёл сквозь корпус.
    const swapped = [];
    scene.traverse((o) => {
      if (!o.isMesh || !o.material) return;
      swapped.push([o, o.material]);
      o.material = this._glowMaterial(Array.isArray(o.material) ? o.material[0] : o.material);
    });
    scene.background = null;
    scene.fog = null;
    scene.overrideMaterial = null;
    renderer.setRenderTarget(this._glowRT);
    renderer.setClearColor(0x000000, 0);
    renderer.clear(true, true, true);
    renderer.autoClear = false;
    renderer.render(scene, this.camera);
    swapped.forEach(([o, mat]) => { o.material = mat; });
    scene.background = prevBg;
    scene.fog = prevFog;
    scene.overrideMaterial = prevOverride;
    renderer.autoClear = prevAutoClear;

    // 2. Размытие: горизонталь и вертикаль, дважды — мягкий ореол.
    const blur = this._quad.material;
    blur.uniforms.tDiffuse.value = this._glowRT.texture;
    blur.uniforms.uDirection.value.set(1, 0);
    renderer.setRenderTarget(this._blurA);
    renderer.clear();
    this._quad.render(renderer);
    blur.uniforms.tDiffuse.value = this._blurA.texture;
    blur.uniforms.uDirection.value.set(0, 1);
    renderer.setRenderTarget(this._blurB);
    renderer.clear();
    this._quad.render(renderer);
    // второй, более широкий проход: крупные ореолы вокруг ярких мест
    blur.uniforms.tDiffuse.value = this._blurB.texture;
    blur.uniforms.uDirection.value.set(1, 0.35);
    renderer.setRenderTarget(this._blurA);
    renderer.clear();
    this._quad.render(renderer);
    blur.uniforms.tDiffuse.value = this._blurA.texture;
    blur.uniforms.uDirection.value.set(0.35, 1);
    renderer.setRenderTarget(this._blurB);
    renderer.clear();
    this._quad.render(renderer);

    // 3. Кадр + ореол. Пишем туда же, куда писал бы следующий проход.
    const target = this.renderToScreen ? null : writeBuffer;
    this._composite.material.uniforms.tDiffuse.value = readBuffer.texture;
    this._composite.material.uniforms.tGlow.value = this._blurB.texture;
    this._composite.material.uniforms.uStrength.value = Math.max(0, this.strength);
    renderer.setRenderTarget(target);
    this._composite.render(renderer);

    renderer.setRenderTarget(prevTarget);
    renderer.setClearColor(prevClear, prevClearAlpha);
  }

  dispose() {
    this._glowRT?.dispose();
    this._blurA?.dispose();
    this._blurB?.dispose();
    this._blackMat.dispose();
    this._glowMats.forEach((m) => m.dispose());
    this._glowMats.clear();
    this._quad.material.dispose();
    this._composite.material.dispose();
  }
}
