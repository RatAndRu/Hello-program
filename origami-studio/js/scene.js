import * as THREE from 'three';
import { OrbitControls } from '../vendor/OrbitControls.js';

const FRONT = 0xe9a080;
const BACK = 0xf7d5bd;
const EDGE = 0x795f52;

/** Renderer for one connected, solver-generated sheet. No independently posed body parts. */
export class OrigamiScene {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(34, 1, 0.05, 100);
    this.camera.position.set(4.2, 1.5, 5.2);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.02;
    this.renderer.domElement.setAttribute('aria-label', 'Журавлик из одной связанной поверхности бумаги');
    container.appendChild(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = .07;
    this.controls.minDistance = 2.2;
    this.controls.maxDistance = 12;
    this.controls.target.set(-.35, -.35, 0);
    this.scene.add(new THREE.HemisphereLight(0xfffaf1, 0x65756d, 2.0));
    const key = new THREE.DirectionalLight(0xffffff, 2.8);
    key.position.set(-3, 5, 5);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    Object.assign(key.shadow.camera, { left: -4, right: 4, top: 4, bottom: -4 });
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xf6c7ae, 1.3);
    fill.position.set(4, 1, -4);
    this.scene.add(fill);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), new THREE.ShadowMaterial({ color: 0x526157, opacity: .13 }));
    ground.rotation.x = -Math.PI / 2;
    this.ground = ground;
    ground.position.y = -1.45;
    ground.receiveShadow = true;
    this.scene.add(ground);
    const grid = new THREE.GridHelper(12, 24, 0xb9c4bb, 0xd4d9d2);
    this.grid = grid;
    grid.position.y = -1.445;
    grid.material.transparent = true;
    grid.material.opacity = .2;
    this.scene.add(grid);
    this.sheetRoot = new THREE.Group();
    this.scene.add(this.sheetRoot);
    this.frontMaterial = new THREE.MeshStandardMaterial({ color: FRONT, side: THREE.DoubleSide, roughness: .88, metalness: 0 });
    this.backMaterial = new THREE.MeshStandardMaterial({ color: BACK, side: THREE.DoubleSide, roughness: .9, metalness: 0 });
    this.edgeMaterial = new THREE.LineBasicMaterial({ color: EDGE, transparent: true, opacity: .27 });
    this.currentKey = '';
    this.ready = fetch('./data/crane.geometry.json').then(response => {
      if (!response.ok) throw new Error(`Crane geometry HTTP ${response.status}`);
      return response.json();
    }).then(data => {
      if (data.format !== 'origami-studio-connected-sheet') throw new Error('Unknown connected-sheet format');
      this.data = data;
      this.showStep(this.requestedStep ?? 9, true);
    });
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.tick = this.tick.bind(this);
    this.renderer.setAnimationLoop(this.tick);
  }

  clearSheet() {
    for (const child of [...this.sheetRoot.children]) {
      this.sheetRoot.remove(child);
      child.traverse(object => { if (object.geometry) object.geometry.dispose(); });
    }
    this.panelMeshes = [];
    this.edgeObject = null;
  }

  makePanel(panel) {
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(panel.points.flat());
    const indices = [];
    for (let i = 1; i < panel.points.length - 1; i++) indices.push(0, i, i + 1);
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    const mesh = new THREE.Mesh(geometry, panel.flipped ? this.backMaterial : this.frontMaterial);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.facetId = panel.id;
    mesh.userData.unfoldedPolygon = panel.uv;
    return mesh;
  }

  buildStatic(state, key) {
    if (this.currentKey === key) return;
    this.clearSheet();
    this.currentKey = key;
    const floor = Math.min(...state.panels.flatMap(panel => panel.points.map(point => point[1]))) - .035;
    this.ground.position.y = floor;
    this.grid.position.y = floor + .005;
    for (const panel of state.panels) {
      const mesh = this.makePanel(panel);
      this.panelMeshes.push(mesh);
      this.sheetRoot.add(mesh);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(state.edges.flat(2), 3));
    this.edgeObject = new THREE.LineSegments(geometry, this.edgeMaterial);
    this.sheetRoot.add(this.edgeObject);
  }

  buildAnimated(segment, key) {
    if (this.currentKey === key) return;
    const template = segment.frames[0];
    this.buildStatic(template, key);
    this.animationTemplate = template;
  }

  updateAnimated(segment, framePosition) {
    const frames = segment.frames;
    const aIndex = Math.min(frames.length - 1, Math.floor(framePosition));
    const bIndex = Math.min(frames.length - 1, aIndex + 1);
    const t = Math.max(0, Math.min(1, framePosition - aIndex));
    const a = frames[aIndex], b = frames[bIndex];
    for (let p = 0; p < this.panelMeshes.length; p++) {
      const mesh = this.panelMeshes[p];
      const attribute = mesh.geometry.getAttribute('position');
      const pa = a.panels[p].points, pb = b.panels[p].points;
      let cursor = 0;
      for (let v = 0; v < pa.length; v++) {
        for (let axis = 0; axis < 3; axis++) attribute.array[cursor++] = pa[v][axis] + (pb[v][axis] - pa[v][axis]) * t;
      }
      attribute.needsUpdate = true;
      mesh.geometry.computeVertexNormals();
    }
    if (this.edgeObject) {
      const values = [];
      const sameEdges = a.edges.length === b.edges.length;
      const edgeCount = sameEdges ? a.edges.length : (t < .5 ? a.edges.length : b.edges.length);
      for (let e = 0; e < edgeCount; e++) {
        const ea = sameEdges ? a.edges[e] : (t < .5 ? a.edges[e] : b.edges[e]);
        const eb = sameEdges ? b.edges[e] : ea;
        for (let end = 0; end < 2; end++) for (let axis = 0; axis < 3; axis++) {
          const va = ea[end][axis], vb = eb[end][axis];
          values.push(va + (vb - va) * t);
        }
      }
      this.edgeObject.geometry.setAttribute('position', new THREE.Float32BufferAttribute(values, 3));
    }
  }

  showStep(index, moveCamera = true) {
    this.requestedStep = Math.max(0, Math.min(9, Math.round(index)));
    if (!this.data) return;
    const track = this.data.tracks[this.requestedStep];
    this.buildStatic(this.data.states[track.endState], `state-${track.endState}`);
    if (moveCamera) this.cameraPreset(this.requestedStep < 2 ? 'sheet' : this.requestedStep === 9 ? 'hero' : 'iso');
  }

  setPose(value) {
    if (!this.data) return;
    const pose = Math.max(0, Math.min(8.9999, value));
    const index = Math.floor(pose);
    const local = pose - index;
    const track = this.data.tracks[index];
    const segments = track.animations.flatMap(animation => animation.segments);
    if (!segments.length) {
      this.buildStatic(this.data.states[track.endState], `state-${track.endState}`);
      return;
    }
    const scaled = Math.min(.999999, local) * segments.length;
    const segmentIndex = Math.floor(scaled);
    const within = scaled - segmentIndex;
    const segment = segments[segmentIndex];
    const key = `animation-${index}-${segmentIndex}`;
    this.buildAnimated(segment, key);
    this.updateAnimated(segment, within * (segment.frames.length - 1));
  }

  cameraPreset(name = 'hero', animate = true) {
    const presets = {
      hero: { position: [.44,.43,5.2], target: [.44,.43,-.65] },
      iso: { position: [.44,.43,5.2], target: [.44,.43,-.65] },
      sheet: { position: [0,0,6.4], target: [0,0,0] },
      front: { position: [-.4,-.4,6], target: [-.4,-.4,0] },
      side: { position: [5,.2,.3], target: [-.4,-.4,0] },
      top: { position: [0,6,.1], target: [0,-.3,0] },
    };
    const preset = presets[name] || presets.hero;
    if ((name === 'hero' || name === 'iso') && this.data) {
      const points = this.data.states[12].panels.flatMap(panel => panel.points);
      const min = [Infinity,Infinity,Infinity], max = [-Infinity,-Infinity,-Infinity];
      for (const point of points) for (let axis = 0; axis < 3; axis++) {
        min[axis] = Math.min(min[axis], point[axis]); max[axis] = Math.max(max[axis], point[axis]);
      }
      const centre = min.map((value, axis) => (value + max[axis]) / 2);
      preset.position = [centre[0], centre[1], centre[2] + 4.4];
      preset.target = centre;
    }
    if (!animate) {
      this.camera.position.fromArray(preset.position);
      this.controls.target.fromArray(preset.target);
      this.controls.update();
      return;
    }
    this.cameraTween = { start: performance.now(), from: this.camera.position.clone(), to: new THREE.Vector3(...preset.position), targetFrom: this.controls.target.clone(), targetTo: new THREE.Vector3(...preset.target) };
  }

  tick(time) {
    if (this.cameraTween) {
      const t = Math.min(1, (time - this.cameraTween.start) / 450);
      const e = t * t * (3 - 2 * t);
      this.camera.position.lerpVectors(this.cameraTween.from, this.cameraTween.to, e);
      this.controls.target.lerpVectors(this.cameraTween.targetFrom, this.cameraTween.targetTo, e);
      if (t >= 1) this.cameraTween = null;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  resize() {
    const width = Math.max(1, this.container.clientWidth), height = Math.max(1, this.container.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  resetCamera() { this.cameraPreset((this.requestedStep ?? 9) < 2 ? 'sheet' : 'hero'); }
  get canvas() { return this.renderer.domElement; }
}
