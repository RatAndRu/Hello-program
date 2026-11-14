// Модель детали: плоская развёртка (панели) + сгибы. Всё остальное выводится из неё.

import {
  Rigid, V2, V3, DEG, cross3, dot3, ensureCCW, len3, lift, m3apply, m3transpose, norm3, rigidApply,
  rigidId, rigidMul, rigidRotAbout, sub3, polyArea, polyBBox, polyCentroid, bboxUnion,
  Box2, Box2 as Box2T,
} from './vec'

export type FaceKind = 'panel' | 'tab'

export interface Face {
  id: string
  name: string
  /** Полигон в плоскости развёртки, мм, обход против часовой. */
  poly: V2[]
  kind: FaceKind
}

export interface Hinge {
  a: string
  b: string
  p0: V2
  p1: V2
  /** Угол сгиба: >0 — к лицевой стороне листа, <0 — к изнанке. */
  angle: number
  /** Шов: рёбра встречаются в 3D, но в развёртке не согнуты (стык впритык). */
  seam?: boolean
}

export interface Part {
  name: string
  prompt: string
  faces: Face[]
  hinges: Hinge[]
  nominal?: { w: number; h: number; d: number } | null
  sheet?: { w: number; h: number } | null
  /** Направление «вверх» собранной детали (для правильной ориентации вида). */
  up?: V3 | null
  meta?: { kind: string; [k: string]: string | number }
  warnings?: string[]
}

export interface PlacedFace {
  face: Face
  tf: Rigid
  poly3: V3[]
  normal: V3
  center: V3
}

export interface FoldResult {
  faces: PlacedFace[]
  root: string
  unplaced: string[]
  warnings: string[]
}

export function faceById(part: Part, id: string): Face | undefined {
  return part.faces.find((f) => f.id === id)
}

/** 3D-положение всех панелей при коэффициенте складывания t (0 — лист, 1 — деталь). */
export function foldPart(part: Part, t = 1): FoldResult {
  const placed = new Map<string, PlacedFace>()
  const warnings: string[] = []
  // Угол задан для перехода a -> b; в обратную сторону он меняет знак.
  const adj = new Map<string, { hinge: Hinge; other: string; angle: number }[]>()
  for (const f of part.faces) adj.set(f.id, [])
  for (const h of part.hinges) {
    if (h.seam) continue
    adj.get(h.a)?.push({ hinge: h, other: h.b, angle: h.angle })
    adj.get(h.b)?.push({ hinge: h, other: h.a, angle: -h.angle })
  }

  const panels = part.faces.filter((f) => f.kind === 'panel')
  const root = (panels[0] ?? part.faces[0])?.id
  if (!root) return { faces: [], root: '', unplaced: [], warnings: ['Пустая деталь'] }

  const place = (face: Face, tf: Rigid) => {
    const poly3 = face.poly.map((p) => rigidApply(tf, lift(p)))
    const n = norm3(m3n(tf))
    const c = polyCentroid(face.poly)
    placed.set(face.id, {
      face,
      tf,
      poly3,
      normal: n,
      center: rigidApply(tf, lift(c)),
    })
  }

  const rootFace = part.faces.find((f) => f.id === root)!
  place(rootFace, rigidId())

  // Обход в ширину по дереву сгибов: каждый сгиб поворачивает поддерево
  // вокруг своего ребра.
  const queue = [root]
  while (queue.length) {
    const id = queue.shift()!
    const parent = placed.get(id)!
    for (const { hinge, other, angle } of adj.get(id) ?? []) {
      if (placed.has(other)) continue
      const child = part.faces.find((f) => f.id === other)
      if (!child) continue
      const p0 = rigidApply(parent.tf, lift(hinge.p0))
      const p1 = rigidApply(parent.tf, lift(hinge.p1))
      const axis = norm3(sub3(p1, p0))
      const rot = rigidRotAbout(p0, axis, angle * t)
      place(child, rigidMul(rot, parent.tf))
      queue.push(child.id)
    }
  }

  const unplaced = part.faces.filter((f) => !placed.has(f.id)).map((f) => f.id)
  if (unplaced.length) {
    warnings.push(`Панели без сгибов не размещены: ${unplaced.join(', ')}`)
  }

  let faces = part.faces.map((f) => placed.get(f.id)).filter((f): f is PlacedFace => !!f)

  // Разворачиваем собранную деталь «вверх» — так её удобно смотреть и мерить.
  if (part.up) {
    const up = norm3(part.up)
    if (len3(sub3(up, [0, 0, 1])) > 1e-6) {
      const axis = cross3(up, [0, 0, 1])
      const ang = Math.acos(Math.max(-1, Math.min(1, dot3(up, [0, 0, 1])))) / DEG
      const rot = rigidRotAbout([0, 0, 0], norm3(axis), ang)
      faces = faces.map((f) => ({
        ...f,
        tf: rigidMul(rot, f.tf),
        poly3: f.poly3.map((q) => rigidApply(rot, q)),
        normal: m3apply(rot.m, f.normal),
        center: rigidApply(rot, f.center),
      }))
    }
  }

  return { faces, root, unplaced, warnings }
}

function m3n(tf: Rigid): V3 {
  // Третья колонка матрицы — нормаль листа.
  return [tf.m[2], tf.m[5], tf.m[8]]
}

export interface BBox3 {
  min: V3
  max: V3
}

export function bbox3Of(faces: PlacedFace[]): BBox3 {
  const min: V3 = [Infinity, Infinity, Infinity]
  const max: V3 = [-Infinity, -Infinity, -Infinity]
  for (const f of faces) {
    for (const p of f.poly3) {
      for (let i = 0; i < 3; i++) {
        if (p[i] < min[i]) min[i] = p[i]
        if (p[i] > max[i]) max[i] = p[i]
      }
    }
  }
  return { min, max }
}

export interface EdgeInfo {
  faceId: string
  kind: 'fold' | 'cut'
  p0: V3
  p1: V3
  length: number
  matched: boolean
}

function sameSeg(a0: V3, a1: V3, b0: V3, b1: V3, tol: number): boolean {
  const d = (p: V3, q: V3) => len3(sub3(p, q)) <= tol
  return (d(a0, b0) && d(a1, b1)) || (d(a0, b1) && d(a1, b0))
}

export interface Report {
  faces: number
  panels: number
  tabs: number
  folds: number
  totalAngle: number
  areaMm2: number
  cutMm: number
  foldMm: number
  size: V3
  netBox: Box2T
  closed: boolean
  openEdges: number
  openLength: number
  glueEdges: number
  glueLength: number
  warnings: string[]
}

/** Полная проверка собранной детали: размеры, площадь, замкнутость оболочки. */
export function inspect(part: Part): Report {
  const tol = 0.15
  const folded = foldPart(part, 1)
  const warnings = [...(part.warnings ?? []), ...folded.warnings]

  // Рёбра: сгибы и резы. Сгиб — ребро, общее для двух панелей в модели.
  const edges: EdgeInfo[] = []
  const same2 = (u: V2, w: V2) => Math.hypot(u[0] - w[0], u[1] - w[1]) <= tol
  for (const pf of folded.faces) {
    if (pf.face.kind === 'tab') continue
    const n = pf.face.poly.length
    for (let i = 0; i < n; i++) {
      const a = pf.face.poly[i]
      const b = pf.face.poly[(i + 1) % n]
      const a3 = pf.poly3[i]
      const b3 = pf.poly3[(i + 1) % n]
      let kind: 'fold' | 'cut' = 'cut'
      for (const h of part.hinges) {
        if (h.seam) continue
        if (h.a !== pf.face.id && h.b !== pf.face.id) continue
        const otherKind = part.faces.find((f) => f.id === (h.a === pf.face.id ? h.b : h.a))?.kind
        if (otherKind !== 'panel') continue // ребро панель-клапан остаётся резом
        if ((same2(h.p0, a) && same2(h.p1, b)) || (same2(h.p0, b) && same2(h.p1, a))) {
          kind = 'fold'
          break
        }
      }
      edges.push({ faceId: pf.face.id, kind, p0: a3, p1: b3, length: len3(sub3(b3, a3)), matched: false })
    }
  }

  for (let i = 0; i < edges.length; i++) {
    const e = edges[i]
    if (e.kind === 'fold') {
      e.matched = true
      continue
    }
    for (let j = 0; j < edges.length; j++) {
      if (i === j) continue
      const o = edges[j]
      if (o.kind === 'fold') continue
      if (sameSeg(e.p0, e.p1, o.p0, o.p1, tol)) {
        e.matched = true
        break
      }
    }
  }

  // Незамкнутое ребро может лежать на другой панели — это шов под склейку.
  const onPanel = (p: V3, own: string): boolean => {
    for (const pf of folded.faces) {
      if (pf.face.kind !== 'panel' || pf.face.id === own) continue
      const inv = m3transpose(pf.tf.m)
      const q = sub3(p, pf.tf.t)
      const local = m3apply(inv, q)
      if (Math.abs(local[2]) > 0.35) continue
      if (pointInPoly([local[0], local[1]], pf.face.poly, 0.35)) return true
    }
    return false
  }

  let cutMm = 0
  let foldMm = 0
  let openLength = 0
  let openEdges = 0
  let glueEdges = 0
  let glueLength = 0
  for (const e of edges) {
    if (e.kind === 'fold') {
      foldMm += e.length
      continue
    }
    cutMm += e.length
    if (e.matched) continue
    const mid: V3 = [
      (e.p0[0] + e.p1[0]) / 2,
      (e.p0[1] + e.p1[1]) / 2,
      (e.p0[2] + e.p1[2]) / 2,
    ]
    if (onPanel(mid, e.faceId)) {
      glueEdges++
      glueLength += e.length
    } else {
      openEdges++
      openLength += e.length
    }
  }

  const areaMm2 = part.faces
    .filter((f) => f.kind === 'panel')
    .reduce((s, f) => s + Math.abs(polyArea(f.poly)), 0)

  let netBox: Box2T | null = null
  for (const f of part.faces) netBox = bboxUnion(netBox, polyBBox(f.poly))
  const nb = netBox ?? { min: [0, 0] as V2, max: [0, 0] as V2 }

  const bb = bbox3Of(folded.faces.filter((f) => f.face.kind === 'panel'))
  const size: V3 = [bb.max[0] - bb.min[0], bb.max[1] - bb.min[1], bb.max[2] - bb.min[2]]

  if (part.nominal) {
    const d = [size[0], size[2], size[1]]
    const want = [part.nominal.w, part.nominal.h, part.nominal.d]
    const dev = Math.max(...want.map((w, i) => Math.abs(w - d[i])))
    if (dev > 0.6) {
      warnings.push(
        `Собранный габарит ${d.map((x) => Math.round(x * 10) / 10).join(' × ')} мм ` +
          `≠ заданным ${want.join(' × ')} мм`,
      )
    }
  }

  if (part.sheet) {
    const bw = nb.max[0] - nb.min[0]
    const bh = nb.max[1] - nb.min[1]
    const fitsDirect = bw <= part.sheet.w + 1e-6 && bh <= part.sheet.h + 1e-6
    const fitsRot = bh <= part.sheet.w + 1e-6 && bw <= part.sheet.h + 1e-6
    if (!fitsDirect && !fitsRot) {
      warnings.push(
        `Развёртка ${Math.round(bw)} × ${Math.round(bh)} мм не влезает в лист ` +
          `${part.sheet.w} × ${part.sheet.h} мм`,
      )
    }
  }

  return {
    faces: part.faces.length,
    panels: part.faces.filter((f) => f.kind === 'panel').length,
    tabs: part.faces.filter((f) => f.kind === 'tab').length,
    folds: part.hinges.filter(
      (h) =>
        !h.seam &&
        part.faces.find((f) => f.id === h.a)?.kind === 'panel' &&
        part.faces.find((f) => f.id === h.b)?.kind === 'panel',
    ).length,
    totalAngle: part.hinges
      .filter((h) => !h.seam)
      .reduce((s, h) => s + Math.abs(h.angle), 0),
    areaMm2,
    cutMm,
    foldMm,
    size,
    netBox: nb,
    closed: openEdges === 0 && part.faces.length > 1,
    openEdges,
    openLength,
    glueEdges,
    glueLength,
    warnings,
  }
}

/** Список сгибов в порядке сборки: номер, длина, угол, какие панели соединяет. */
export interface FoldItem {
  idx: number
  lengthMm: number
  angle: number
  a: string
  b: string
  p0: V2
  p1: V2
  seam: boolean
}

export function foldList(part: Part): FoldItem[] {
  const byId = new Map(part.faces.map((f) => [f.id, f]))
  const out: FoldItem[] = []
  let idx = 0
  for (const h of part.hinges) {
    const a = byId.get(h.a)
    const b = byId.get(h.b)
    if (!a || !b) continue
    if (a.kind !== 'panel' || b.kind !== 'panel') continue
    out.push({
      idx: ++idx,
      lengthMm: Math.hypot(h.p1[0] - h.p0[0], h.p1[1] - h.p0[1]),
      angle: h.angle,
      a: a.name,
      b: b.name,
      p0: h.p0,
      p1: h.p1,
      seam: !!h.seam,
    })
  }
  return out
}

export function netSize(part: Part): V2 {
  let b: Box2 | null = null
  for (const f of part.faces) b = bboxUnion(b, polyBBox(f.poly))
  const nb = b ?? { min: [0, 0] as V2, max: [0, 0] as V2 }
  return [nb.max[0] - nb.min[0], nb.max[1] - nb.min[1]]
}

export function faceArea(f: Face): number {
  return Math.abs(polyArea(f.poly))
}

export function edgesOfFace(f: Face): [V2, V2][] {
  return f.poly.map((p, i) => [p, f.poly[(i + 1) % f.poly.length]] as [V2, V2])
}

/** Общее ребро двух полигонов (для режима ручных команд «сгиб»). */
export function sharedEdge(pa: V2[], pb: V2[], tol = 0.2): [V2, V2] | null {
  const eq = (u: V2, w: V2) => Math.hypot(u[0] - w[0], u[1] - w[1]) <= tol
  for (let i = 0; i < pa.length; i++) {
    const a0 = pa[i]
    const a1 = pa[(i + 1) % pa.length]
    for (let j = 0; j < pb.length; j++) {
      const b0 = pb[j]
      const b1 = pb[(j + 1) % pb.length]
      if ((eq(a0, b0) && eq(a1, b1)) || (eq(a0, b1) && eq(a1, b0))) return [a0, a1]
    }
  }
  return null
}

/** Точка внутри полигона (2D, с допуском у края). */
export function pointInPoly(p: V2, poly: V2[], tol = 0): boolean {
  let inside = false
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i]
    const b = poly[j]
    if (a[1] > p[1] !== b[1] > p[1]) {
      const x = ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]
      if (p[0] < x) inside = !inside
    }
  }
  if (inside) return true
  if (tol <= 0) return false
  // рядом с контуром тоже считаем «на панели»
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i]
    const b = poly[(i + 1) % poly.length]
    if (distToSegment(p, a, b) <= tol) return true
  }
  return false
}

function distToSegment(p: V2, a: V2, b: V2): number {
  const dx = b[0] - a[0]
  const dy = b[1] - a[1]
  const l2 = dx * dx + dy * dy
  if (l2 < 1e-12) return Math.hypot(p[0] - a[0], p[1] - a[1])
  let t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2
  t = Math.max(0, Math.min(1, t))
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
}

export function normalizeFace(f: Face): Face {
  return { ...f, poly: ensureCCW(f.poly) }
}

export const newFace = (id: string, poly: V2[], name = '', kind: FaceKind = 'panel'): Face => ({
  id,
  name,
  poly: ensureCCW(poly),
  kind,
})

export function translatePart(part: Part, dx: number, dy: number): Part {
  return {
    ...part,
    faces: part.faces.map((f) => ({
      ...f,
      poly: f.poly.map((p) => [p[0] + dx, p[1] + dy] as V2),
    })),
    hinges: part.hinges.map((h) => ({
      ...h,
      p0: [h.p0[0] + dx, h.p0[1] + dy] as V2,
      p1: [h.p1[0] + dx, h.p1[1] + dy] as V2,
    })),
  }
}
