// Обратная задача: дана собранная оболочка из плоских граней — получаем развёртку.
// Оболочка может состоять из нескольких несвязанных кусков (островов): дольки
// шара, ручка кружки, ярусы пирамиды. Каждый остров разворачивается от своего
// корня, затем листы раскладываются по формату — как UV-карта в 3D-редакторе.

import {
  M3, Rigid, V2, V3, Box2, cross3, dot3, len3, m3apply, norm3, polyBBox, rigidApply,
  rigidId, rigidInv, rigidMul, rigidRotAbout, rigidShift, sub3, ensureCCW, DEG,
} from './vec'

export interface Face3 {
  id: string
  name?: string
  poly: V3[]
}

export interface Hinge3 {
  a: string
  b: string
}

export interface Island {
  /** Корневая панель острова. */
  root: string
  faces: string[]
  /** Габарит острова на листе. */
  box: Box2
  /** Отображение координат листа в 3D собранной детали. */
  home: Rigid
}

export interface Unfolded {
  faces: { id: string; name: string; poly: V2[] }[]
  hinges: { a: string; b: string; p0: V2; p1: V2; angle: number }[]
  islands: Island[]
  /** Куда смотрит ось Z исходной оболочки в собранном виде. */
  up: V3
  /** Швы: рёбра, которые в 3D совпадают, а в развёртке разъехались. */
  seams: { a: string; b: string; p0: V2; p1: V2 }[]
  warning: string[]
}

function newellNormal(poly: V3[]): V3 {
  let x = 0, y = 0, z = 0
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i]
    const q = poly[(i + 1) % poly.length]
    x += (p[1] - q[1]) * (p[2] + q[2])
    y += (p[2] - q[2]) * (p[0] + q[0])
    z += (p[0] - q[0]) * (p[1] + q[1])
  }
  return norm3([x, y, z])
}

/** Базис грани: отображение её плоскости на плоскость z = 0. */
function planeFrame(poly: V3[], n: V3): Rigid {
  const o = poly[0]
  let u = sub3(poly[1], poly[0])
  if (len3(u) < 1e-9) u = [1, 0, 0]
  u = norm3(u)
  let v = cross3(n, u)
  v = norm3(v)
  const m: M3 = [
    u[0], u[1], u[2],
    v[0], v[1], v[2],
    n[0], n[1], n[2],
  ]
  const t: V3 = [-dot3(u, o), -dot3(v, o), -dot3(n, o)]
  return { m, t }
}

function sharedPoints(a: V3[], b: V3[], tol = 1e-6): [V3, V3] | null {
  const eq = (p: V3, q: V3) => len3(sub3(p, q)) <= tol
  for (let i = 0; i < a.length; i++) {
    const a0 = a[i]
    const a1 = a[(i + 1) % a.length]
    for (let j = 0; j < b.length; j++) {
      const b0 = b[j]
      const b1 = b[(j + 1) % b.length]
      if ((eq(a0, b0) && eq(a1, b1)) || (eq(a0, b1) && eq(a1, b0))) return [a0, a1]
    }
  }
  return null
}

export interface UnfoldOpts {
  /** Зазор между островами на листе, мм. */
  gap?: number
  /** Раскладывать острова рядом (true) или оставить как развернулось. */
  pack?: boolean
}

/** Развернуть оболочку в плоскость: по дереву смежности граней, по островам. */
export function unfold(faces3: Face3[], hinges3: Hinge3[], opts: UnfoldOpts = {}): Unfolded {
  const empty: Unfolded = { faces: [], hinges: [], islands: [], up: [0, 0, 1], seams: [], warning: ['Пустая оболочка'] }
  if (!faces3.length) return empty

  const byId = new Map(faces3.map((f) => [f.id, f]))
  const normals = new Map<string, V3>()
  for (const f of faces3) normals.set(f.id, newellNormal(f.poly))

  const adj = new Map<string, { other: string; p0: V3; p1: V3 }[]>()
  for (const f of faces3) adj.set(f.id, [])
  for (const h of hinges3) {
    const A = byId.get(h.a)
    const B = byId.get(h.b)
    if (!A || !B) continue
    const sp = sharedPoints(A.poly, B.poly)
    if (!sp) continue
    adj.get(h.a)!.push({ other: h.b, p0: sp[0], p1: sp[1] })
    adj.get(h.b)!.push({ other: h.a, p0: sp[0], p1: sp[1] })
  }

  // Компоненты связности — будущие острова листа.
  const compOf = new Map<string, number>()
  const comps: string[][] = []
  for (const f of faces3) {
    if (compOf.has(f.id)) continue
    const idx = comps.length
    const group: string[] = []
    const stack = [f.id]
    compOf.set(f.id, idx)
    while (stack.length) {
      const id = stack.pop()!
      group.push(id)
      for (const nb of adj.get(id) ?? []) {
        if (compOf.has(nb.other)) continue
        compOf.set(nb.other, idx)
        stack.push(nb.other)
      }
    }
    comps.push(group)
  }

  // Каждый остров разворачивается от своего корня (первая грань компоненты).
  const flat = new Map<string, Rigid>()
  for (const group of comps) {
    const rootId = group[0]
    flat.set(rootId, planeFrame(byId.get(rootId)!.poly, normals.get(rootId)!))
    const stack = [rootId]
    while (stack.length) {
      const id = stack.pop()!
      const cur = flat.get(id)!
      for (const nb of [...(adj.get(id) ?? [])].reverse()) {
        if (flat.has(nb.other)) continue
        const q0 = rigidApply(cur, nb.p0)
        const q1 = rigidApply(cur, nb.p1)
        const axis = norm3(sub3(q1, q0))
        // Нормаль соседа в уже развёрнутой системе координат.
        const nc = m3apply(cur.m, normals.get(nb.other)!)
        // Единственный поворот вокруг ребра, который укладывает грань
        // в плоскость листа лицевой стороной вверх.
        const phi = Math.atan2(dot3(cross3(nc, [0, 0, 1]), axis), dot3(nc, [0, 0, 1])) / DEG
        const rot = rigidRotAbout(q0, axis, phi)
        flat.set(nb.other, rigidMul(rot, cur))
        stack.push(nb.other)
      }
    }
  }

  // Габариты островов до раскладки.
  const boxesBefore: Box2[] = comps.map((group) => {
    let b: Box2 | null = null
    for (const id of group) {
      const tf = flat.get(id)!
      const poly = byId.get(id)!.poly.map((p) => {
        const q = rigidApply(tf, p)
        return [q[0], q[1]] as V2
      })
      const bb = polyBBox(poly)
      b = b ? { min: [Math.min(b.min[0], bb.min[0]), Math.min(b.min[1], bb.min[1])], max: [Math.max(b.max[0], bb.max[0]), Math.max(b.max[1], bb.max[1])] } : bb
    }
    return b ?? { min: [0, 0], max: [0, 0] }
  })

  // Раскладка «полками»: крупные куски сверху, зазор между островами.
  const gap = Math.max(2, opts.gap ?? 12)
  const shift: V2[] = comps.map(() => [0, 0])
  if (opts.pack !== false && comps.length > 1) {
    const w = boxesBefore.map((b) => b.max[0] - b.min[0])
    const h = boxesBefore.map((b) => b.max[1] - b.min[1])
    const order = comps.map((_, i) => i).sort((a, b) => h[b] - h[a])
    // Целевая ширина листа: примерно квадрат по площади островов.
    const area = sum(w.map((v, i) => (v + gap) * (h[i] + gap)))
    const target = Math.max(Math.max(...w), Math.sqrt(area) * 1.05) + gap
    let x = 0
    let y = 0
    let rowH = 0
    for (const i of order) {
      if (x > 0 && x + w[i] > target) {
        x = 0
        y += rowH + gap
        rowH = 0
      }
      shift[i] = [x - boxesBefore[i].min[0], y - boxesBefore[i].min[1]]
      x += w[i] + gap
      rowH = Math.max(rowH, h[i])
    }
  }

  const outFaces = faces3.map((f) => {
    const tf = flat.get(f.id) ?? rigidId()
    const d = shift[compOf.get(f.id) ?? 0]
    const poly = f.poly.map((p) => {
      const q = rigidApply(tf, p)
      return [q[0] + d[0], q[1] + d[1]] as V2
    })
    return { id: f.id, name: f.name ?? f.id, poly: ensureCCW(poly) }
  })

  const islands: Island[] = comps.map((group, i) => {
    const rootId = group[0]
    const tf = flat.get(rootId)!
    const d = shift[i]
    // home: координаты листа -> 3D. Остров сдвинут на листе, значит в 3D
    // применяем обратный сдвиг и собственный базис корня.
    const home = rigidMul(rigidInv(tf), rigidShift(-d[0], -d[1]))
    const bb = boxesBefore[i]
    return {
      root: rootId,
      faces: group,
      home,
      box: {
        min: [bb.min[0] + d[0], bb.min[1] + d[1]],
        max: [bb.max[0] + d[0], bb.max[1] + d[1]],
      },
    }
  })

  // Ребро в координатах листа — из грани a; проверяем, что у грани b оно там же.
  const findHinge2 = (a: string, b: string): [V2, V2] | null => {
    const A = byId.get(a)!
    const B = byId.get(b)!
    const sp = sharedPoints(A.poly, B.poly)
    if (!sp) return null
    const fa = flat.get(a)!
    const fb = flat.get(b)
    if (!fb) return null
    const q0 = rigidApply(fa, sp[0])
    const q1 = rigidApply(fa, sp[1])
    const r0 = rigidApply(fb, sp[0])
    const r1 = rigidApply(fb, sp[1])
    const d = Math.hypot(q0[0] - r0[0], q0[1] - r0[1]) + Math.hypot(q1[0] - r1[0], q1[1] - r1[1])
    if (d > 1e-4) return null // это шов, а не сгиб
    const off = shift[compOf.get(a) ?? 0]
    return [
      [q0[0] + off[0], q0[1] + off[1]],
      [q1[0] + off[0], q1[1] + off[1]],
    ]
  }

  const outHinges: Unfolded['hinges'] = []
  const seams: Unfolded['seams'] = []
  const seen = new Set<string>()
  for (const h of hinges3) {
    const key = h.a < h.b ? `${h.a}|${h.b}` : `${h.b}|${h.a}`
    if (seen.has(key)) continue
    seen.add(key)
    const p = findHinge2(h.a, h.b)
    if (!p) {
      // ребро совпадает в 3D, но не в развёртке — это шов
      const sp = sharedPoints(byId.get(h.a)!.poly, byId.get(h.b)!.poly)
      const fa = flat.get(h.a)
      if (sp && fa) {
        const off = shift[compOf.get(h.a) ?? 0]
        const q0 = rigidApply(fa, sp[0])
        const q1 = rigidApply(fa, sp[1])
        seams.push({ a: h.a, b: h.b, p0: [q0[0] + off[0], q0[1] + off[1]], p1: [q1[0] + off[0], q1[1] + off[1]] })
      }
      continue
    }
    // Точный угол сборки: поворот вокруг ребра (p0->p1), обратный развёртке.
    const fa = flat.get(h.a)!
    const axis = norm3([p[1][0] - p[0][0], p[1][1] - p[0][1], 0])
    const nc = m3apply(fa.m, normals.get(h.b)!)
    const phi = Math.atan2(dot3(cross3(nc, [0, 0, 1]), axis), dot3(nc, [0, 0, 1])) / DEG
    outHinges.push({ a: h.a, b: h.b, p0: p[0], p1: p[1], angle: -phi })
  }

  // «Верх» берём по самому крупному острову.
  let big = 0
  for (let i = 1; i < comps.length; i++) if (comps[i].length > comps[big].length) big = i
  const rootTf = flat.get(comps[big][0]) ?? rigidId()
  const up = norm3(m3apply(rootTf.m, [0, 0, 1]))
  return { faces: outFaces, hinges: outHinges, islands, up, seams, warning: [] }
}

const sum = (a: number[]): number => a.reduce((s, v) => s + v, 0)

export { newellNormal, sharedPoints }
export type { V2, V3, Rigid }
