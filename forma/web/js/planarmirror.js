/**
 * Настоящее плоское отражение для зеркальных деталей.
 *
 * Раньше зеркало получало кубическую карту, снятую из центра пластины, — это
 * отражало мир «как шар»: у предмета над зеркалом отражение оказывалось не
 * того размера и не на своём месте. Здесь сцена рисуется из **отражённой
 * камеры** (как в зеркале на самом деле), а пластина показывает этот кадр по
 * экранной проекции своей же точки — масштаб и параллакс совпадают.
 */
import * as THREE from 'three';

const VERT = `
  uniform mat4 uTextureMatrix;
  varying vec4 vUv;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vUv = uTextureMatrix * world;
    gl_Position = projectionMatrix * viewMatrix * world;
  }`;

const FRAG = `
  uniform sampler2D tReflect;
  uniform vec3 uTint;
  uniform float uOpacity;
  varying vec4 vUv;
  void main() {
    vec3 refl = texture2DProj(tReflect, vUv).rgb;
    gl_FragColor = vec4(refl * uTint, uOpacity);
  }`;

/**
 * Плоскость зеркальной детали в мировых координатах: нормаль и точка.
 *
 * Нормаль — самая «тонкая» ось габарита пластины. У неё два равноправных
 * направления, и раньше бралось всегда положительное: у пластины, повёрнутой
 * на 90°, это оказывалась нижняя грань, и отражение строилось от изнанки —
 * предмет «висел» не там и был не того масштаба. Теперь нормаль направлена
 * **к наблюдателю** (``eye``), а без него — вверх: отражает та сторона,
 * которую видно.
 */
export function platePlane(mesh, eye = null) {
  const geometry = mesh.geometry;
  if (!geometry) return null;
  const pos = geometry.attributes?.position;
  if (!pos) return null;
  mesh.updateWorldMatrix(true, true);
  const m = mesh.matrixWorld;
  if (!geometry.boundingBox) geometry.computeBoundingBox();
  const bb = geometry.boundingBox;
  const size = new THREE.Vector3().subVectors(bb.max, bb.min);
  const axes = ['x', 'y', 'z'];
  const thin = axes.reduce((a, b) => (size[a] <= size[b] ? a : b));
  const normal = new THREE.Vector3(
    thin === 'x' ? 1 : 0, thin === 'y' ? 1 : 0, thin === 'z' ? 1 : 0);
  normal.transformDirection(m);
  if (normal.lengthSq() < 1e-9) return null;
  normal.normalize();

  // центр детали — середина габарита в мировых координатах
  const center = new THREE.Vector3().addVectors(bb.min, bb.max).multiplyScalar(0.5)
    .applyMatrix4(m);

  // куда должна смотреть нормаль: на камеру, а если её нет — вверх
  const target = eye
    ? new THREE.Vector3(eye.x ?? eye[0], eye.y ?? eye[1], eye.z ?? eye[2])
    : new THREE.Vector3(0, 1, 0);
  const dir = target.sub(center);
  if (dir.lengthSq() < 1e-12) dir.set(0, 1, 0);
  if (normal.dot(dir) < 0) normal.negate();

  // видимая поверхность — та, что дальше всех по нормали
  const v = new THREE.Vector3();
  let best = -Infinity;
  for (let i = 0; i < pos.count; i += 1) {
    v.fromBufferAttribute(pos, i).applyMatrix4(m);
    const d = v.dot(normal);
    if (d > best) best = d;
  }
  if (!Number.isFinite(best)) return null;
  const point = normal.clone().multiplyScalar(best);
  return { normal, point, center };
}

export class PlanarMirror {
  constructor(mesh, material, { resolution = 1024 } = {}) {
    this.mesh = mesh;
    this.source = material;
    this.resolution = resolution;
    this.textureMatrix = new THREE.Matrix4();
    this.virtualCamera = new THREE.PerspectiveCamera();
    this.rt = null;
    this._dirty = true;
    this._lastCam = new THREE.Vector3(1e9, 1e9, 1e9);
    this._lastLook = new THREE.Vector3(1e9, 1e9, 1e9);
    const tint = material.color ? material.color.clone() : new THREE.Color(0xffffff);
    // почти белый оттенок: отражение не должно «перекрашивать» соседей
    tint.lerp(new THREE.Color(0xffffff), 0.75);
    this.material = new THREE.ShaderMaterial({
      uniforms: {
        tReflect: { value: null },
        uTextureMatrix: { value: this.textureMatrix },
        uTint: { value: new THREE.Vector3(tint.r, tint.g, tint.b) },
        uOpacity: { value: 1 },
      },
      vertexShader: VERT,
      fragmentShader: FRAG,
      toneMapped: false,
    });
    this.material.name = `${material.name || 'зеркало'}_reflect`;
    // правки материала (цвет, металл, шероховатость) идут в настоящий PBR
    this.material.userData.mirrorSource = material;
    mesh.material = this.material;
  }

  _ensureRT(renderer) {
    const size = new THREE.Vector2();
    renderer.getDrawingBufferSize(size);
    const w = Math.max(64, Math.min(this.resolution, Math.floor(size.x)));
    const h = Math.max(64, Math.min(this.resolution, Math.floor(size.y)));
    if (this.rt && this.rt.width === w && this.rt.height === h) return;
    this.rt?.dispose();
    this.rt = new THREE.WebGLRenderTarget(w, h, {
      type: THREE.HalfFloatType,
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      depthBuffer: true,
      stencilBuffer: false,
    });
    this.material.uniforms.tReflect.value = this.rt.texture;
    this._dirty = true;
  }

  /** Пересчитывает отражение. Вызывать до отрисовки кадра. */
  update(renderer, scene, camera, { hide = [], force = false } = {}) {
    this._ensureRT(renderer);
    const plane = platePlane(this.mesh, camera.position);
    if (!plane) return;
    // пластина могла сдвинуться сама (правка ползунка) — следим и за ней
    this.mesh.updateWorldMatrix(true, false);
    this._lastPos.setFromMatrixPosition(this.mesh.matrixWorld);
    const moved = force || this._dirty
      || this._lastCam.distanceToSquared(camera.position) > 1e-6
      || this._lastLook.distanceToSquared(camera.up) > 1e-6;
    if (!moved) return;
    this._lastCam.copy(camera.position);
    this._lastLook.copy(camera.up);
    this._dirty = false;

    const { normal, point } = plane;
    camera.updateMatrixWorld();
    const rotation = new THREE.Matrix4().extractRotation(camera.matrixWorld);
    const target = new THREE.Vector3(0, 0, -1).applyMatrix4(rotation).add(camera.position);
    const camPos = camera.position.clone();
    const reflectorPlane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, point);
    const mirroredPos = camPos.clone();
    const dist = reflectorPlane.distanceToPoint(camPos);
    mirroredPos.addScaledVector(normal, -2 * dist);
    const mirroredTarget = target.clone().addScaledVector(normal, -2 * reflectorPlane.distanceToPoint(target));
    const up = new THREE.Vector3(0, 1, 0).applyMatrix4(rotation).reflect(normal).normalize();

    const vc = this.virtualCamera;
    vc.position.copy(mirroredPos);
    vc.up.copy(up);
    vc.lookAt(mirroredTarget);
    vc.near = camera.near;
    vc.far = camera.far;
    vc.fov = camera.fov;
    vc.aspect = camera.aspect;
    vc.updateProjectionMatrix();
    vc.updateMatrixWorld();

    this.textureMatrix.set(
      0.5, 0.0, 0.0, 0.5,
      0.0, 0.5, 0.0, 0.5,
      0.0, 0.0, 0.5, 0.5,
      0.0, 0.0, 0.0, 1.0);
    this.textureMatrix.multiply(vc.projectionMatrix);
    this.textureMatrix.multiply(vc.matrixWorldInverse);

    // саму пластину и подсказки в отражение не пускаем
    const hidden = [];
    const hideList = [this.mesh, ...hide];
    hideList.forEach((o) => {
      if (!o) return;
      hidden.push([o, o.visible]);
      o.visible = false;
    });
    const prevTarget = renderer.getRenderTarget();
    const prevBg = scene.background;
    const prevFog = scene.fog;
    const prevPlanes = renderer.clippingPlanes;
    scene.fog = null;
    // Срезаем всё, что лежит по другую сторону пластины: иначе детали «под
    // зеркалом» просвечивают в отражении сквозь пол.
    renderer.clippingPlanes = [new THREE.Plane(
      normal.clone(), -normal.dot(point))];
    renderer.setRenderTarget(this.rt);
    renderer.clear();
    try {
      renderer.render(scene, vc);
    } finally {
      renderer.setRenderTarget(prevTarget);
      scene.background = prevBg;
      scene.fog = prevFog;
      renderer.clippingPlanes = prevPlanes;
      hidden.forEach(([o, vis]) => { o.visible = vis; });
    }
  }

  dispose() {
    this.rt?.dispose();
    this.material.dispose();
    if (this.mesh) this.mesh.material = this.source;
  }
}
