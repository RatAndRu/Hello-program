// Генераторы деталей: из геометрии — в плоскую развёртку с линиями сгиба.

import {
  V2, V3, add2, len2, mul2, norm2, polyArea, polyBBox, boxesOverlap, ensureCCW,
} from './vec'
import { Face, FaceKind, Hinge, Part, pointInPoly, sharedEdge } from './model'
import { Face3, unfold } from './unfold'

export interface BuildOpts {
  /** Толщина материала, мм — только для 3D-вида и экспорта. */
  thickness: number
  /** Клапаны для склейки. */
  tabs: boolean
  /** Высота клапана, мм. */
  tabHeight: number
  /** Число сегментов для круглых тел. */
  segments: number
}

export const defaultOpts = (): BuildOpts => ({
  thickness: 2,
  tabs: true,
  tabHeight: 8,
  segments: 24,
})

/** Знак угла выбираем так, чтобы клапан уходил на лицевую сторону листа. */
function signedAngle(p0: V2, p1: V2, child: V2[], mag: number): number {
  const ax = p1[0] - p0[0]
  const ay = p1[1] - p0[1]
  const c = child.reduce((s, q) => [s[0] + q[0], s[1] + q[1]] as V2, [0, 0] as V2)
  const cx = c[0] / child.length - p0[0]
  const cy = c[1] / child.length - p0[1]
  // (axis x r).z
  const motionZ = ax * cy - ay * cx
  return motionZ < 0 ? -mag : mag
}

export class Net {
  faces: Face[] = []
  hinges: Hinge[] = []
  private seq = 0

  add(poly: V2[], name: string, kind: FaceKind = 'panel'): Face {
    if (Math.abs(polyArea(poly)) < 1e-6) throw new Error(`Панель «${name}» вырождена`)
    const face: Face = { id: `f${++this.seq}`, name, poly: ensureCCW(poly), kind }
    this.faces.push(face)
    return face
  }

  /** Угол > 0 — деталь уходит на лицевую сторону листа. */
  foldAt(a: Face, b: Face, p0: V2, p1: V2, angle: number): Hinge {
    const h: Hinge = { a: a.id, b: b.id, p0, p1, angle }
    this.hinges.push(h)
    return h
  }

  fold(a: Face, b: Face, angle: number): Hinge {
    const e = sharedEdge(a.poly, b.poly)
    if (!e) throw new Error(`У панелей «${a.name}» и «${b.name}» нет общего ребра`)
    return this.foldAt(a, b, e[0], e[1], signedAngle(e[0], e[1], b.poly, angle))
  }

  /** Точный угол без эвристики — для автоматической развёртки. */
  foldSigned(a: Face, b: Face, p0: V2, p1: V2, angle: number): Hinge {
    return this.foldAt(a, b, p0, p1, angle)
  }

  isHingeEdge(face: Face, p0: V2, p1: V2): boolean {
    const eq = (u: V2, w: V2) => Math.hypot(u[0] - w[0], u[1] - w[1]) < 0.05
    return this.hinges.some(
      (h) =>
        (h.a === face.id || h.b === face.id) &&
        ((eq(h.p0, p0) && eq(h.p1, p1)) || (eq(h.p0, p1) && eq(h.p1, p0))),
    )
  }
}

/** Свободно ли место под клапан: проверяем не габарит, а сами точки. */
function tabIsFree(net: Net, tab: V2[], owner: Face): boolean {
  const bb = polyBBox(tab)
  const eps = 0.9
  const near = net.faces.filter((f) => f.id !== owner.id && boxesOverlap(polyBBox(f.poly), bb, eps))
  if (!near.length) return true
  const cx = tab.reduce((s, p) => s + p[0], 0) / tab.length
  const cy = tab.reduce((s, p) => s + p[1], 0) / tab.length
  const mid0: V2 = [(tab[0][0] + tab[3][0]) / 2, (tab[0][1] + tab[3][1]) / 2]
  const mid1: V2 = [(tab[1][0] + tab[2][0]) / 2, (tab[1][1] + tab[2][1]) / 2]
  const samples: V2[] = [tab[0], tab[1]]
  for (let t = 0.15; t <= 0.95; t += 0.2) {
    samples.push([mid0[0] + (mid1[0] - mid0[0]) * t, mid0[1] + (mid1[1] - mid0[1]) * t])
    samples.push([
      tab[0][0] + (tab[3][0] - tab[0][0]) * t + (cx - mid0[0]) * 0.35,
      tab[0][1] + (tab[3][1] - tab[0][1]) * t + (cy - mid0[1]) * 0.35,
    ])
    samples.push([
      tab[1][0] + (tab[2][0] - tab[1][0]) * t + (cx - mid1[0]) * 0.35,
      tab[1][1] + (tab[2][1] - tab[1][1]) * t + (cy - mid1[1]) * 0.35,
    ])
  }
  samples.push([cx, cy])
  for (const f of near) {
    for (const q of samples) if (pointInPoly(q, f.poly, 0.15)) return false
  }
  return true
}

export const rect = (x0: number, y0: number, x1: number, y1: number): V2[] => [
  [x0, y0],
  [x1, y0],
  [x1, y1],
  [x0, y1],
]

/** Клапаны для склейки вдоль резов, где хватает места. */
export function addTabs(net: Net, opts: BuildOpts, maxEdge = Infinity): number {
  if (!opts.tabs) return 0
  const h = Math.max(3, opts.tabHeight)
  let added = 0
  for (const face of [...net.faces]) {
    if (face.kind !== 'panel') continue
    if (face.name.startsWith('клапан')) continue
    const n = face.poly.length
    for (let i = 0; i < n; i++) {
      const p0 = face.poly[i]
      const p1 = face.poly[(i + 1) % n]
      if (net.isHingeEdge(face, p0, p1)) continue
      const dir = norm2([p1[0] - p0[0], p1[1] - p0[1]])
      const L = len2([p1[0] - p0[0], p1[1] - p0[1]])
      if (L < 3 * h || L > maxEdge) continue
      const out: V2 = [dir[1], -dir[0]] // для CCW-полигона внешняя сторона — справа
      const k = Math.min(h * 0.45, L * 0.2)
      const tabPoly: V2[] = [
        p0,
        p1,
        add2(add2(p1, mul2(out, h)), mul2(dir, -k)),
        add2(add2(p0, mul2(out, h)), mul2(dir, k)),
      ]
      if (!tabIsFree(net, tabPoly, face)) continue
      const tab = net.add(tabPoly, `клапан ${added + 1}`, 'tab')
      net.foldAt(face, tab, p0, p1, signedAngle(p0, p1, tabPoly, 90))
      added++
    }
  }
  return added
}

function finish(
  net: Net,
  name: string,
  prompt: string,
  nominal: Part['nominal'],
  meta: Part['meta'],
  warnings: string[] = [],
  up: V3 = [0, 0, 1],
): Part {
  return {
    name,
    prompt,
    faces: net.faces,
    hinges: net.hinges,
    nominal,
    meta,
    warnings,
    up,
  }
}

/** Коробка: дно, четыре стенки, крышка на сгибе. */
export function makeBox(w: number, d: number, h: number, closed: boolean, opts: BuildOpts, prompt: string): Part {
  const net = new Net()
  const bottom = net.add(rect(0, 0, w, d), 'дно')
  const south = net.add(rect(0, -h, w, 0), 'стенка передняя')
  const north = net.add(rect(0, d, w, d + h), 'стенка задняя')
  const west = net.add(rect(-h, 0, 0, d), 'стенка левая')
  const east = net.add(rect(w, 0, w + h, d), 'стенка правая')
  net.fold(bottom, south, 90)
  net.fold(bottom, north, 90)
  net.fold(bottom, west, 90)
  net.fold(bottom, east, 90)

  if (closed) {
    const lid = net.add(rect(0, d + h, w, d + h + d), 'крышка')
    net.fold(north, lid, 90)
    const flapW = net.add(rect(-h, d + h, 0, d + h + d), 'клапан крышки левый')
    const flapE = net.add(rect(w, d + h, w + h, d + h + d), 'клапан крышки правый')
    net.fold(lid, flapW, 90)
    net.fold(lid, flapE, 90)
    addTabs(net, opts)
    return finish(net, 'Коробка с крышкой', prompt, { w, h, d }, { kind: 'box', w, d, h })
  }

  addTabs(net, opts, h * 1.3)
  return finish(net, 'Коробка без крышки', prompt, { w, h, d }, { kind: 'box', w, d, h })
}

/** Лоток / обечайка-крышка: дно и борта. */
export function makeTray(w: number, d: number, h: number, opts: BuildOpts, prompt: string, label = 'Лоток'): Part {
  const net = new Net()
  const bottom = net.add(rect(0, 0, w, d), 'дно')
  const walls = [
    net.add(rect(0, -h, w, 0), 'борт передний'),
    net.add(rect(0, d, w, d + h), 'борт задний'),
    net.add(rect(-h, 0, 0, d), 'борт левый'),
    net.add(rect(w, 0, w + h, d), 'борт правый'),
  ]
  for (const wall of walls) net.fold(bottom, wall, 90)
  addTabs(net, opts, h * 1.3)
  return finish(net, label, prompt, { w, h, d }, { kind: 'tray', w, d, h })
}

function ring(radius: number, n: number, z: number): V3[] {
  const pts: V3[] = []
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2
    pts.push([radius * Math.cos(a), radius * Math.sin(a), z])
  }
  return pts
}

interface ShellResult {
  net: Net
  warn: string[]
  up: V3
  seams: { face: Face; p0: V2; p1: V2 }[]
}

/** Оболочка из фасеток, заданная в 3D, разворачивается автоматически. */
function fromShell(faces3: Face3[], hinges3: { a: string; b: string }[]): ShellResult {
  const unfolded = unfold(faces3, hinges3)
  const net = new Net()
  const byId = new Map<string, Face>()
  for (const f of unfolded.faces) byId.set(f.id, net.add(f.poly, f.name))
  for (const h of unfolded.hinges) {
    const a = byId.get(h.a)
    const b = byId.get(h.b)
    if (a && b) net.foldSigned(a, b, h.p0, h.p1, h.angle)
  }
  const seams: { face: Face; p0: V2; p1: V2 }[] = []
  for (const sm of unfolded.seams) {
    const face = byId.get(sm.a)
    if (face) seams.push({ face, p0: sm.p0, p1: sm.p1 })
  }
  return { net, warn: unfolded.warning, up: unfolded.up, seams }
}

/** Труба / обечайка / призма: призматическая оболочка из n фасеток. */
export function makeTube(d: number, h: number, n: number, opts: BuildOpts, prompt: string, label = 'Обечайка', withBottom = false): Part {
  const N = Math.max(3, Math.round(n))
  const R = d / 2
  const rings = N // фасетки
  const faces3: Face3[] = []
  const hinges3: { a: string; b: string }[] = []
  const b = ring(R, rings, 0)
  const t = ring(R, rings, h)
  for (let i = 0; i < rings; i++) {
    const j = (i + 1) % rings
    faces3.push({ id: `p${i}`, name: `грань ${i + 1}`, poly: [b[i], b[j], t[j], t[i]] })
  }
  for (let i = 0; i < rings; i++) {
    const j = (i + 1) % rings
    hinges3.push({ a: `p${i}`, b: `p${j}` })
  }
  if (withBottom) {
    const disc: V3[] = [...b].reverse()
    faces3.push({ id: 'bottom', name: 'дно', poly: disc })
    for (let i = 0; i < rings; i++) hinges3.push({ a: `p${i}`, b: 'bottom' })
  }
  const { net, warn, up, seams } = fromShell(faces3, hinges3)
  // Один клапан на шов, чтобы обечайка склеивалась.
  addFirstSeamTab(net, opts, seams)
  return finish(net, label, prompt, null, { kind: withBottom ? 'glass' : 'tube', d, h, n: N }, warn, up)
}

function addSeamTab(net: Net, opts: BuildOpts, seam?: { face: Face; p0: V2; p1: V2 }): boolean {
  if (!opts.tabs || !seam) return false
  const h = Math.max(3, opts.tabHeight + 4)
  const face = seam.face
  // находим ребро в обходе панели, чтобы внешняя сторона считалась верно
  const n = face.poly.length
  let edge: [V2, V2] | null = null
  for (let i = 0; i < n; i++) {
    const a = face.poly[i]
    const b = face.poly[(i + 1) % n]
    const m = (u: V2, w: V2) => Math.hypot(u[0] - w[0], u[1] - w[1]) < 0.2
    if ((m(a, seam.p0) && m(b, seam.p1)) || (m(a, seam.p1) && m(b, seam.p0))) {
      edge = [a, b]
      break
    }
  }
  if (!edge) return false
  const [p0, p1] = edge
  const dir = norm2([p1[0] - p0[0], p1[1] - p0[1]])
  const out: V2 = [dir[1], -dir[0]]
  const L = len2([p1[0] - p0[0], p1[1] - p0[1]])
  const k = Math.min(h * 0.5, L * 0.25)
  const tab: V2[] = [
    p0,
    p1,
    add2(add2(p1, mul2(out, h)), mul2(dir, -k)),
    add2(add2(p0, mul2(out, h)), mul2(dir, k)),
  ]
  if (!tabIsFree(net, tab, face)) return false
  const t = net.add(tab, 'клапан шва', 'tab')
  net.foldAt(face, t, p0, p1, signedAngle(p0, p1, tab, 90))
  return true
}

function addFirstSeamTab(net: Net, opts: BuildOpts, seams: { face: Face; p0: V2; p1: V2 }[]): void {
  for (const s of seams) if (addSeamTab(net, opts, s)) return
}

/** Усечённый конус / конус / воронка. */
export function makeFrustum(d1: number, d2: number, h: number, n: number, opts: BuildOpts, prompt: string, closedBottom = false): Part {
  const N = Math.max(3, Math.round(n))
  const R1 = d1 / 2
  const R2 = d2 / 2
  const b = ring(R1, N, 0)
  const faces3: Face3[] = []
  const hinges3: { a: string; b: string }[] = []
  if (R2 < 1e-6) {
    const apex: V3 = [0, 0, h]
    for (let i = 0; i < N; i++) {
      const j = (i + 1) % N
      faces3.push({ id: `p${i}`, name: `сектор ${i + 1}`, poly: [b[i], b[j], apex] })
    }
  } else {
    const t = ring(R2, N, h)
    for (let i = 0; i < N; i++) {
      const j = (i + 1) % N
      faces3.push({ id: `p${i}`, name: `сектор ${i + 1}`, poly: [b[i], b[j], t[j], t[i]] })
    }
  }
  for (let i = 0; i < N; i++) hinges3.push({ a: `p${i}`, b: `p${(i + 1) % N}` })
  if (closedBottom) {
    faces3.push({ id: 'bottom', name: 'дно', poly: [...b].reverse() })
    for (let i = 0; i < N; i++) hinges3.push({ a: `p${i}`, b: 'bottom' })
  }
  const { net, warn, up, seams } = fromShell(faces3, hinges3)
  addFirstSeamTab(net, opts, seams)
  return finish(net, 'Усечённый конус', prompt, null, { kind: 'frustum', d1, d2, h, n: N }, warn, up)
}

/** Пирамида: основание n-угольник + грани к вершине. */
export function makePyramid(n: number, a: number, h: number, opts: BuildOpts, prompt: string): Part {
  const N = Math.max(3, Math.round(n))
  const R = a / (2 * Math.sin(Math.PI / N))
  const base = ring(R, N, 0)
  const apex: V3 = [0, 0, h]
  const faces3: Face3[] = [{ id: 'base', name: 'основание', poly: [...base].reverse() }]
  for (let i = 0; i < N; i++) {
    const j = (i + 1) % N
    faces3.push({ id: `s${i}`, name: `грань ${i + 1}`, poly: [base[i], base[j], apex] })
  }
  const hinges3: { a: string; b: string }[] = []
  for (let i = 0; i < N; i++) hinges3.push({ a: 'base', b: `s${i}` })
  const { net, warn, up } = fromShell(faces3, hinges3)
  void opts
  return finish(net, 'Пирамида', prompt, null, { kind: 'pyramid', n: N, a, h }, warn, up)
}

/** Гнутый профиль: уголок, швеллер, Z. */
export function makeProfile(
  kind: 'уголок' | 'швеллер' | 'z',
  widths: number[],
  length: number,
  opts: BuildOpts,
  prompt: string,
): Part {
  void opts
  const net = new Net()
  const angles: number[] = kind === 'уголок' ? [90] : kind === 'швеллер' ? [90, 90] : [90, -90]
  const panels: Face[] = []
  let x = 0
  for (let i = 0; i < widths.length; i++) {
    const wdt = Math.max(2, widths[i])
    const name =
      kind === 'уголок'
        ? i === 0
          ? 'полка'
          : 'стенка'
        : i === 0
          ? 'полка 1'
          : i === widths.length - 1
            ? `полка ${i + 1}`
            : 'стенка'
    panels.push(net.add(rect(x, 0, x + wdt, length), name))
    x += wdt
  }
  for (let i = 1; i < panels.length; i++) net.fold(panels[i - 1], panels[i], angles[i - 1])
  const label = kind === 'уголок' ? 'Уголок' : kind === 'швеллер' ? 'Швеллер' : 'Z-профиль'
  return finish(net, label, prompt, null, { kind: 'profile', form: kind, widths: widths.join('×'), length })
}

/** Режим ручных команд: полигоны + сгибы. */
export function makeCustom(
  polys: { name: string; pts: V2[] }[],
  folds: { a: string; b: string; angle: number }[],
  opts: BuildOpts,
  prompt: string,
): Part {
  const net = new Net()
  const byName = new Map<string, Face>()
  for (const p of polys) byName.set(p.name.toLowerCase(), net.add(p.pts, p.name))
  for (const f of folds) {
    const a = byName.get(f.a.toLowerCase())
    const b = byName.get(f.b.toLowerCase())
    if (!a) throw new Error(`Неизвестная панель «${f.a}»`)
    if (!b) throw new Error(`Неизвестная панель «${f.b}»`)
    net.fold(a, b, f.angle)
  }
  addTabs(net, opts)
  return finish(net, 'Своя развёртка', prompt, null, { kind: 'custom' })
}

