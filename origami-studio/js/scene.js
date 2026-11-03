import * as THREE from 'three';
import { OrbitControls } from '../vendor/OrbitControls.js';

const PAPER = 0xe99a7d;
const PAPER_LIGHT = 0xf9c8b3;
const PAPER_DARK = 0xd98870;

export class OrigamiScene {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
    this.camera.position.set(4.4, 3.1, 5.2);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.domElement.setAttribute('aria-label', 'Интерактивная 3D-модель журавлика');
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.minDistance = 3.2;
    this.controls.maxDistance = 11;
    this.controls.maxPolarAngle = Math.PI * 0.88;
    this.controls.target.set(0, 0.35, 0);

    this.scene.add(new THREE.HemisphereLight(0xfffaf1, 0x718078, 1.9));
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(3, 6, 4);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.left = -4;
    key.shadow.camera.right = 4;
    key.shadow.camera.top = 4;
    key.shadow.camera.bottom = -4;
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xf7c6ad, 1.2);
    fill.position.set(-4, 2, -3);
    this.scene.add(fill);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(30, 30),
      new THREE.ShadowMaterial({ color: 0x526157, opacity: 0.12 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.72;
    ground.receiveShadow = true;
    this.scene.add(ground);

    const grid = new THREE.GridHelper(12, 24, 0xb9c4bb, 0xd4d9d2);
    grid.position.y = -0.715;
    grid.material.transparent = true;
    grid.material.opacity = 0.28;
    this.scene.add(grid);

    this.flat = this.makeFlatSheet();
    this.base = this.makeBase();
    this.crane = this.makeCrane();
    this.scene.add(this.flat, this.base, this.crane);
    this.pose = 9;
    this.setPose(9);
    this.cameraPreset('hero', false);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.tick = this.tick.bind(this);
    this.renderer.setAnimationLoop(this.tick);
  }

  material(color) {
    return new THREE.MeshStandardMaterial({
      color, side: THREE.DoubleSide, roughness: 0.88, metalness: 0,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1
    });
  }

  polygon(points, color = PAPER, edgeOpacity = 0.18) {
    const vertices = points.flatMap(p => [p[0], p[1], p[2]]);
    const indices = [];
    for (let i = 1; i < points.length - 1; i++) indices.push(0, i, i + 1);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    const group = new THREE.Group();
    const mesh = new THREE.Mesh(geometry, this.material(color));
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry, 16),
      new THREE.LineBasicMaterial({ color: 0x765c51, transparent: true, opacity: edgeOpacity })
    );
    group.add(edges);
    return group;
  }

  makeFlatSheet() {
    const group = new THREE.Group();
    const geometry = new THREE.PlaneGeometry(3.55, 3.55, 1, 1);
    const sheet = new THREE.Mesh(geometry, this.material(PAPER_LIGHT));
    this.flatSheet = sheet;
    sheet.rotation.x = -Math.PI / 2;
    sheet.castShadow = true;
    group.add(sheet);
    const points = [
      new THREE.Vector3(-1.775, .006, -1.775), new THREE.Vector3(1.775, .006, 1.775),
      new THREE.Vector3(1.775, .006, -1.775), new THREE.Vector3(-1.775, .006, 1.775),
      new THREE.Vector3(0, .007, -1.775), new THREE.Vector3(0, .007, 1.775),
      new THREE.Vector3(-1.775, .007, 0), new THREE.Vector3(1.775, .007, 0)
    ];
    this.flatLines = new THREE.LineSegments(
      new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineDashedMaterial({ color: 0x9b6e5f, dashSize: .07, gapSize: .045, transparent: true, opacity: .55 })
    );
    this.flatLines.computeLineDistances();
    group.add(this.flatLines);
    group.position.y = -0.67;
    return group;
  }

  makeBase() {
    const group = new THREE.Group();
    const front = this.polygon([[0,1.45,0],[-1.15,0,0],[0,-1.35,.06],[1.15,0,0]], PAPER_LIGHT);
    const back = this.polygon([[0,1.45,-.035],[1.15,0,-.035],[0,-1.35,-.095],[-1.15,0,-.035]], PAPER);
    group.add(front, back);
    const center = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0,1.42,.065), new THREE.Vector3(0,-1.3,.065)]),
      new THREE.LineDashedMaterial({ color: 0x8c6c5e, dashSize: .06, gapSize: .04, opacity: .45, transparent: true })
    );
    center.computeLineDistances();
    group.add(center);
    group.position.y = .55;
    group.scale.setScalar(.82);
    return group;
  }

  ribbon(points, widths, color = PAPER) {
    const positions = [];
    const indices = [];
    points.forEach((p, i) => {
      positions.push(p[0] - widths[i], p[1], p[2], p[0] + widths[i], p[1], p[2]);
      if (i < points.length - 1) {
        const a = i * 2;
        indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
      }
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    const mesh = new THREE.Mesh(geometry, this.material(color));
    mesh.castShadow = true;
    const group = new THREE.Group();
    group.add(mesh);
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 12), new THREE.LineBasicMaterial({ color: 0x795e53, transparent: true, opacity: .16 }));
    group.add(edge);
    return group;
  }

  makeCrane() {
    const root = new THREE.Group();
    this.body = new THREE.Group();
    const bodyPoints = [
      [0,.52,0], [-.48,0,0], [0,-.46,0], [.48,0,0], [0,.03,.58], [0,.03,-.58]
    ];
    const faces = [[0,1,4],[0,4,3],[0,3,5],[0,5,1],[2,4,1],[2,3,4],[2,5,3],[2,1,5]];
    faces.forEach((f, i) => this.body.add(this.polygon(f.map(k => bodyPoints[k]), i % 3 === 0 ? PAPER_LIGHT : PAPER, .08)));
    root.add(this.body);

    this.leftWing = new THREE.Group();
    this.leftWing.add(this.polygon([[0,0,0],[-2.32,1.05,-.12],[-1.14,.02,-.62],[-.05,-.2,-.24]], PAPER_LIGHT));
    this.leftWing.add(this.polygon([[0,0,.015],[-2.32,1.05,-.12],[-1.08,.25,.48]], PAPER, .12));
    this.leftWing.position.set(-.18,.2,0);
    this.rightWing = new THREE.Group();
    this.rightWing.add(this.polygon([[0,0,0],[2.32,1.05,-.12],[1.14,.02,-.62],[.05,-.2,-.24]], PAPER));
    this.rightWing.add(this.polygon([[0,0,.015],[2.32,1.05,-.12],[1.08,.25,.48]], PAPER_LIGHT, .12));
    this.rightWing.position.set(.18,.2,0);
    root.add(this.leftWing, this.rightWing);

    this.neck = this.ribbon([[0,.03,.4],[0,.55,.64],[0,1.18,.89],[0,1.57,1.01]], [.16,.14,.105,.075], PAPER_LIGHT);
    this.head = new THREE.Group();
    this.head.add(this.ribbon([[0,1.56,1.0],[0,1.53,1.25],[0,1.41,1.52]], [.076,.07,.006], PAPER));
    this.neck.add(this.head);
    this.tail = this.ribbon([[0,.03,-.4],[0,.52,-.72],[0,1.02,-1.12],[0,1.36,-1.5]], [.15,.13,.075,.004], PAPER);
    root.add(this.neck, this.tail);

    const eye = new THREE.Mesh(new THREE.SphereGeometry(.018, 8, 8), new THREE.MeshBasicMaterial({ color: 0x273a32 }));
    eye.position.set(.074,1.535,1.235);
    this.head.add(eye);
    const eye2 = eye.clone();
    eye2.position.x = -.074;
    this.head.add(eye2);

    root.position.y = -.05;
    root.rotation.y = -.18;
    return root;
  }

  static ease(t) { return t * t * (3 - 2 * t); }
  static mix(a, b, t) { return a + (b - a) * t; }

  setPose(value) {
    this.pose = Math.max(0, Math.min(9, value));
    const p = this.pose;
    const flatT = OrigamiScene.ease(Math.max(0, Math.min(1, p - 1)));
    this.flat.visible = p < 2.05;
    this.flat.position.y = OrigamiScene.mix(-.67, .4, flatT);
    this.flat.rotation.x = OrigamiScene.mix(0, Math.PI / 2, flatT);
    this.flat.rotation.z = OrigamiScene.mix(0, Math.PI / 4, flatT);
    this.flat.scale.setScalar(OrigamiScene.mix(1, .68, flatT));
    this.flatLines.visible = true;
    this.flatSheet.material.color.set(p < .85 ? 0xfffdf8 : PAPER_LIGHT);
    this.flatLines.geometry.setDrawRange(0, p < .85 ? 4 : 8);

    this.base.visible = p >= 1.85 && p < 6.05;
    const baseT = OrigamiScene.ease(Math.max(0, Math.min(1, p - 2)));
    const narrowT = OrigamiScene.ease(Math.max(0, Math.min(1, p - 4)));
    this.base.scale.set(
      OrigamiScene.mix(.82,.6,baseT) * OrigamiScene.mix(1,.72,narrowT),
      OrigamiScene.mix(.82,1.12,baseT),
      OrigamiScene.mix(.82,.7,narrowT)
    );
    this.base.rotation.y = OrigamiScene.mix(0,.18,baseT);

    this.crane.visible = p >= 5.85;
    const emerge = OrigamiScene.ease(Math.max(0, Math.min(1, p - 5.8)));
    const wingT = OrigamiScene.ease(Math.max(0, Math.min(1, p - 7.7)));
    const inflate = OrigamiScene.ease(Math.max(0, Math.min(1, p - 8.65)));
    this.crane.scale.setScalar(OrigamiScene.mix(.7,1,emerge));
    this.body.scale.set(1, OrigamiScene.mix(1.25,1,inflate), OrigamiScene.mix(.35,1,inflate));
    this.leftWing.scale.set(OrigamiScene.mix(.35,1,wingT), OrigamiScene.mix(.4,1,wingT), 1);
    this.rightWing.scale.copy(this.leftWing.scale);
    this.leftWing.rotation.z = OrigamiScene.mix(-1.1,0,wingT);
    this.rightWing.rotation.z = OrigamiScene.mix(1.1,0,wingT);
    this.neck.rotation.x = OrigamiScene.mix(-.75,0,emerge);
    this.tail.rotation.x = OrigamiScene.mix(.75,0,emerge);
    const headT = OrigamiScene.ease(Math.max(0, Math.min(1, p - 6.75)));
    this.head.scale.set(OrigamiScene.mix(.05,1,headT), OrigamiScene.mix(.05,1,headT), OrigamiScene.mix(.05,1,headT));
    this.crane.rotation.y = -.18 + Math.sin(p * .4) * .025;
  }

  cameraPreset(name = 'hero', animate = true) {
    const presets = {
      hero: { position: [4.4,3.1,5.2], target: [0,.4,0] },
      iso: { position: [4.2,2.6,4.8], target: [0,.45,0] },
      top: { position: [0,6.6,.05], target: [0,-.3,0] },
      front: { position: [0,1.8,6.1], target: [0,.55,0] },
      side: { position: [5.8,1.9,.2], target: [0,.5,0] }
    };
    const preset = presets[name] || presets.hero;
    if (!animate) {
      this.camera.position.fromArray(preset.position);
      this.controls.target.fromArray(preset.target);
      this.controls.update();
      return;
    }
    this.cameraTween = {
      start: performance.now(), from: this.camera.position.clone(), to: new THREE.Vector3(...preset.position),
      targetFrom: this.controls.target.clone(), targetTo: new THREE.Vector3(...preset.target)
    };
  }

  tick(time) {
    if (this.cameraTween) {
      const t = Math.min(1, (time - this.cameraTween.start) / 500);
      const e = OrigamiScene.ease(t);
      this.camera.position.lerpVectors(this.cameraTween.from, this.cameraTween.to, e);
      this.controls.target.lerpVectors(this.cameraTween.targetFrom, this.cameraTween.targetTo, e);
      if (t >= 1) this.cameraTween = null;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  resize() {
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  resetCamera() { this.cameraPreset(this.pose < 2 ? 'top' : 'hero'); }
  get canvas() { return this.renderer.domElement; }
}
