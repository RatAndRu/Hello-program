// Обратная задача: дана собранная оболочка из плоских граней — получаем развёртку.
// Нужно для круглых тел (труба, конус, призма, пирамида), которые проще задать в 3D.

import {
  M3, Rigid, V2, V3, cross3, dot3, len3, m3apply, norm3, rigidApply, rigidId, rigidMul,
  rigidRotAbout, sub3, ensureCCW, DEG,
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

export interface Unfolded {
  faces: { id: string; name: string; poly: V2[] }[]
  hinges: { a: string; b: string; p0: V2; p1: V2; angle: number }[]
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

/** Развернуть оболочку в плоскость вдоль дерева смежности граней. */
export function unfold(faces3: Face3[], hinges3: Hinge3[]): Unfolded {
  const byId = new Map(faces3.map((f) => [f.id, f]))
  const normals = new Map<string, V3>()
  for (const f of faces3) normals.set(f.id, newellNormal(f.poly))

  const flat = new Map<string, Rigid>()
  const root = faces3[0]
  if (!root) return { faces: [], hinges: [], up: [0, 0, 1], seams: [], warning: ['Пустая оболочка'] }
  flat.set(root.id, planeFrame(root.poly, normals.get(root.id)!))

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

  // Обход в глубину: развёртка ложится лентой от корня, а не «веером в обе стороны».
  const queue = [root.id]
  while (queue.length) {
    const id = queue.pop()!
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
      queue.push(nb.other)
    }
  }

  const outFaces = faces3.map((f) => {
    const tf = flat.get(f.id) ?? rigidId()
    const poly = f.poly.map((p) => {
      const q = rigidApply(tf, p)
      return [q[0], q[1]] as V2
    })
    return { id: f.id, name: f.name ?? f.id, poly: ensureCCW(poly) }
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
    return [[q0[0], q0[1]], [q1[0], q1[1]]]
  }

  const outHinges: Unfolded['hinges'] = []
  const seams: Unfolded['seams'] = []
  const seen = new Set<string>()
  for (const h of hinges3) {
    const key = h.a < h.b ? `${h.a}|${h.b}` : `${h.b}|${h.a}`
    const p = findHinge2(h.a, h.b)
    if (seen.has(key)) continue
    seen.add(key)
    if (!p) {
      // ребро совпадает в 3D, но не в развёртке — это шов
      const sp = sharedPoints(byId.get(h.a)!.poly, byId.get(h.b)!.poly)
      const fa = flat.get(h.a)
      if (sp && fa) {
        const q0 = rigidApply(fa, sp[0])
        const q1 = rigidApply(fa, sp[1])
        seams.push({ a: h.a, b: h.b, p0: [q0[0], q0[1]], p1: [q1[0], q1[1]] })
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

  const rootTf = flat.get(root.id) ?? rigidId()
  const up = norm3(m3apply(rootTf.m, [0, 0, 1]))
  return { faces: outFaces, hinges: outHinges, up, seams, warning: [] }
}

export { newellNormal, sharedPoints }
export type { V2, V3, Rigid }
