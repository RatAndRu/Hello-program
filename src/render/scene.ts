// 3D-вид собранной детали. Ось Z — вверх, как в модели.

import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { Part, foldPart, PlacedFace } from '../core/model'
import { Rigid } from '../core/vec'

export interface SceneToggles {
  edges: boolean
  grid: boolean
  tabs: boolean
}

interface FaceObject {
  group: THREE.Group
  plate: THREE.Mesh
  edges: THREE.LineSegments
  folds: THREE.LineSegments
  placed: PlacedFace
}

export class Scene3D {
  private host: HTMLElement
  private renderer: THREE.WebGLRenderer
  private scene: THREE.Scene
  private camera: THREE.PerspectiveCamera
  private controls: OrbitControls
  private root = new THREE.Group()
  private grid: THREE.Group = new THREE.Group()
  private objects: FaceObject[] = []
  private part: Part | null = null
  private foldT = 0
  private thickness = 2
  private toggles: SceneToggles = { edges: true, grid: true, tabs: true }
  private material: THREE.MeshStandardMaterial
  private tabMaterial: THREE.MeshStandardMaterial
  private cutMat: THREE.LineBasicMaterial
  private foldMat: THREE.LineBasicMaterial
  private needsRender = true
  private ro: ResizeObserver
  private raf = 0
  private fitted = false

  constructor(host: HTMLElement) {
    this.host = host
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1))
    this.renderer.setClearColor(0x000000, 0)
    host.appendChild(this.renderer.domElement)

    this.scene = new THREE.Scene()
    this.camera = new THREE.PerspectiveCamera(42, 1, 1, 20000)
    this.camera.up.set(0, 0, 1)
    this.camera.position.set(420, -520, 380)

    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.09
    this.controls.rotateSpeed = 0.75
    this.controls.zoomSpeed = 0.9
    this.controls.panSpeed = 0.8
    this.controls.addEventListener('change', () => {
      this.needsRender = true
    })

    const hemi = new THREE.HemisphereLight(0xfff2dd, 0x2a303c, 1.35)
    this.scene.add(hemi)
    const key = new THREE.DirectionalLight(0xfff0d8, 2.1)
    key.position.set(320, -420, 520)
    this.scene.add(key)
    const fill = new THREE.DirectionalLight(0x9fc3ff, 0.7)
    fill.position.set(-420, 260, 180)
    this.scene.add(fill)
    const rim = new THREE.DirectionalLight(0xffd7a8, 0.85)
    rim.position.set(120, 480, -260)
    this.scene.add(rim)

    this.material = new THREE.MeshStandardMaterial({
      color: 0xe6d8bf,
      roughness: 0.82,
      metalness: 0.04,
      side: THREE.DoubleSide,
    })
    this.tabMaterial = new THREE.MeshStandardMaterial({
      color: 0xffb454,
      roughness: 0.6,
      metalness: 0.05,
      transparent: true,
      opacity: 0.42,
      side: THREE.DoubleSide,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
    })
    this.cutMat = new THREE.LineBasicMaterial({ color: 0x2a2118, transparent: true, opacity: 0.75 })
    this.foldMat = new THREE.LineBasicMaterial({ color: 0xffb454, transparent: true, opacity: 0.95 })

    this.scene.add(this.root)
    this.scene.add(this.grid)
    this.buildGrid()

    this.ro = new ResizeObserver(() => this.resize())
    this.ro.observe(host)
    this.resize()
    this.loop()
  }

  private buildGrid(): void {
    this.grid.clear()
    const g = new THREE.GridHelper(2000, 40, 0x3a4356, 0x252b36)
    g.rotation.x = Math.PI / 2
    const mat = g.material as THREE.Material
    mat.transparent = true
    mat.opacity = 0.55
    g.position.z = -0.2
    this.grid.add(g)
    this.grid.visible = this.toggles.grid
  }

  private resize(): void {
    const w = this.host.clientWidth || 1
    const h = this.host.clientHeight || 1
    this.renderer.setSize(w, h, false)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    this.needsRender = true
  }

  setThickness(t: number, rebuild = true) {
    if (Math.abs(t - this.thickness) < 1e-6) return
    this.thickness = t
    if (rebuild && this.part) this.setPart(this.part, true)
  }

  setToggles(t: Partial<SceneToggles>) {
    this.toggles = { ...this.toggles, ...t }
    this.grid.visible = this.toggles.grid
    for (const o of this.objects) {
      const isTab = o.placed.face.kind === 'tab'
      o.group.visible = isTab ? this.toggles.tabs : true
      o.edges.visible = this.toggles.edges
      o.folds.visible = this.toggles.edges
    }
    this.needsRender = true
  }

  setPart(part: Part, keepCamera = false): void {
    this.part = part
    this.disposeObjects()
    const folded = foldPart(part, 1)
    const th = Math.max(0.35, this.thickness)

    for (const pf of folded.faces) {
      const isTab = pf.face.kind === 'tab'
      const shape = new THREE.Shape(pf.face.poly.map((p) => new THREE.Vector2(p[0], p[1])))
      const geo = new THREE.ExtrudeGeometry(shape, {
        depth: th,
        bevelEnabled: false,
        curveSegments: 1,
      })
      geo.translate(0, 0, -th / 2)
      if (isTab) geo.translate(0, 0, th * 0.9)
      geo.computeVertexNormals()

      const plate = new THREE.Mesh(geo, isTab ? this.tabMaterial : this.material)
      plate.matrixAutoUpdate = false
      plate.renderOrder = isTab ? 2 : 0

      const n = pf.face.poly.length
      const edgePts: number[] = []
      const foldPts: number[] = []
      const same = (u: number[], w: number[]) => Math.hypot(u[0] - w[0], u[1] - w[1]) < 0.05
      for (let i = 0; i < n; i++) {
        const a = pf.face.poly[i]
        const b = pf.face.poly[(i + 1) % n]
        edgePts.push(a[0], a[1], th / 2, b[0], b[1], th / 2)
        const hinge = part.hinges.find(
          (h) =>
            (h.a === pf.face.id || h.b === pf.face.id) &&
            ((same(h.p0, a) && same(h.p1, b)) || (same(h.p0, b) && same(h.p1, a))),
        )
        if (hinge) foldPts.push(a[0], a[1], th / 2 + 0.02, b[0], b[1], th / 2 + 0.02)
      }
      const eg = new THREE.BufferGeometry()
      eg.setAttribute('position', new THREE.Float32BufferAttribute(edgePts, 3))
      const edges = new THREE.LineSegments(eg, this.cutMat)

      const fg = new THREE.BufferGeometry()
      fg.setAttribute('position', new THREE.Float32BufferAttribute(foldPts, 3))
      const folds = new THREE.LineSegments(fg, this.foldMat)

      const group = new THREE.Group()
      group.matrixAutoUpdate = false
      group.add(plate, edges, folds)
      group.visible = !(isTab && !this.toggles.tabs)
      edges.visible = this.toggles.edges
      folds.visible = this.toggles.edges
      this.root.add(group)
      this.objects.push({ group, plate, edges, folds, placed: pf })
    }

    this.applyFold()
    if (!keepCamera || !this.fitted) this.fit()
    this.needsRender = true
  }

  private applyFold(): void {
    if (!this.part) return
    const t = this.foldT
    if (t >= 0.999) {
      // ничего не пересчитываем: позы уже собраны в setPart через foldPart(1)
      for (const o of this.objects) {
        setMatrix(o.group, o.placed.tf)
      }
      this.needsRender = true
      return
    }
    const folded = foldPart(this.part, t)
    const byId = new Map(folded.faces.map((f) => [f.face.id, f]))
    for (const o of this.objects) {
      const pf = byId.get(o.placed.face.id)
      if (pf) setMatrix(o.group, pf.tf)
    }
    this.needsRender = true
  }

  setFold(t: number) {
    this.foldT = Math.max(0, Math.min(1, t))
    this.applyFold()
  }

  fit(): void {
    if (!this.part) return
    const folded = foldPart(this.part, 1)
    const box = new THREE.Box3()
    for (const pf of folded.faces) {
      if (pf.face.kind === 'tab' && !this.toggles.tabs) continue
      for (const p of pf.poly3) box.expandByPoint(new THREE.Vector3(p[0], p[1], p[2]))
    }
    if (box.isEmpty()) return
    const center = box.getCenter(new THREE.Vector3())
    const size = box.getSize(new THREE.Vector3())
    const radius = Math.max(20, size.length() / 2)
    const dist = radius / Math.sin((this.camera.fov * Math.PI) / 360) * 1.15

    this.controls.target.copy(center)
    this.camera.position.copy(
      center.clone().add(new THREE.Vector3(0.62, -0.72, 0.42).normalize().multiplyScalar(dist)),
    )
    this.camera.near = Math.max(0.5, radius / 200)
    this.camera.far = dist * 12
    this.camera.updateProjectionMatrix()
    this.camera.lookAt(center)
    this.controls.update()
    this.grid.position.z = box.min.z - Math.max(1, size.z * 0.03)
    this.grid.scale.setScalar(Math.max(0.4, radius / 260))
    this.fitted = true
    this.needsRender = true
  }

  private loop = () => {
    this.raf = requestAnimationFrame(this.loop)
    const moving = this.controls.update()
    if (this.needsRender || moving) {
      this.renderer.render(this.scene, this.camera)
      this.needsRender = false
    }
  }

  private disposeObjects(): void {
    for (const o of this.objects) {
      o.plate.geometry.dispose()
      o.edges.geometry.dispose()
      o.folds.geometry.dispose()
      this.root.remove(o.group)
    }
    this.objects = []
  }

  dispose(): void {
    cancelAnimationFrame(this.raf)
    this.ro.disconnect()
    this.disposeObjects()
    this.renderer.dispose()
  }
}

function setMatrix(obj: THREE.Object3D, tf: Rigid): void {
  obj.matrix.set(
    tf.m[0], tf.m[1], tf.m[2], tf.t[0],
    tf.m[3], tf.m[4], tf.m[5], tf.t[1],
    tf.m[6], tf.m[7], tf.m[8], tf.t[2],
    0, 0, 0, 1,
  )
  obj.matrixWorldNeedsUpdate = true
}
