// Плоская и объёмная арифметика. Всё в миллиметрах, углы в градусах.

export type V2 = [number, number]
export type V3 = [number, number, number]

export const DEG = Math.PI / 180

export const v2 = (x: number, y: number): V2 => [x, y]
export const v3 = (x: number, y: number, z: number): V3 => [x, y, z]

export const add2 = (a: V2, b: V2): V2 => [a[0] + b[0], a[1] + b[1]]
export const sub2 = (a: V2, b: V2): V2 => [a[0] - b[0], a[1] - b[1]]
export const mul2 = (a: V2, s: number): V2 => [a[0] * s, a[1] * s]
export const dot2 = (a: V2, b: V2): number => a[0] * b[0] + a[1] * b[1]
export const cross2 = (a: V2, b: V2): number => a[0] * b[1] - a[1] * b[0]
export const len2 = (a: V2): number => Math.hypot(a[0], a[1])
export const len3 = (a: V3): number => Math.hypot(a[0], a[1], a[2])

export function norm2(a: V2): V2 {
  const l = len2(a)
  return l < 1e-12 ? [0, 0] : [a[0] / l, a[1] / l]
}

export function perp2(a: V2): V2 {
  return [-a[1], a[0]]
}

export const add3 = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
export const sub3 = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
export const mul3 = (a: V3, s: number): V3 => [a[0] * s, a[1] * s, a[2] * s]
export const dot3 = (a: V3, b: V3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
export const cross3 = (a: V3, b: V3): V3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
]

export function norm3(a: V3): V3 {
  const l = len3(a)
  return l < 1e-12 ? [0, 0, 0] : [a[0] / l, a[1] / l, a[2] / l]
}

// Матрица 3x3, построчно.
export type M3 = number[]

export const m3id = (): M3 => [1, 0, 0, 0, 1, 0, 0, 0, 1]

export function m3mul(a: M3, b: M3): M3 {
  const r = new Array<number>(9)
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 3; j++) {
      r[i * 3 + j] = a[i * 3] * b[j] + a[i * 3 + 1] * b[3 + j] + a[i * 3 + 2] * b[6 + j]
    }
  }
  return r
}

export function m3apply(m: M3, v: V3): V3 {
  return [
    m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
    m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
    m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
  ]
}

export const m3col = (m: M3, i: number): V3 => [m[i], m[3 + i], m[6 + i]]

export function m3transpose(m: M3): M3 {
  return [m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]]
}

/** Поворот на angleDeg вокруг единичного вектора оси (правая тройка). */
export function m3rot(axis: V3, angleDeg: number): M3 {
  const a = norm3(axis)
  if (len3(a) < 1e-9) return m3id()
  const t = angleDeg * DEG
  const c = Math.cos(t)
  const s = Math.sin(t)
  const k = 1 - c
  const [x, y, z] = a
  return [
    c + x * x * k, x * y * k - z * s, x * z * k + y * s,
    y * x * k + z * s, c + y * y * k, y * z * k - x * s,
    z * x * k - y * s, z * y * k + x * s, c + z * z * k,
  ]
}

/** Жёсткое преобразование: точка -> m * p + t. */
export interface Rigid {
  m: M3
  t: V3
}

export const rigidId = (): Rigid => ({ m: m3id(), t: [0, 0, 0] })

export function rigidApply(r: Rigid, p: V3): V3 {
  return add3(m3apply(r.m, p), r.t)
}

/** Композиция: сначала b, потом a. */
export function rigidMul(a: Rigid, b: Rigid): Rigid {
  return { m: m3mul(a.m, b.m), t: add3(m3apply(a.m, b.t), a.t) }
}

/** Поворот на angleDeg вокруг прямой, заданной точкой p и направлением axis. */
export function rigidRotAbout(p: V3, axis: V3, angleDeg: number): Rigid {
  const m = m3rot(axis, angleDeg)
  return { m, t: sub3(p, m3apply(m, p)) }
}

/** Плоская точка (x, y, 0) -> 3D. */
export const lift = (p: V2): V3 => [p[0], p[1], 0]

export function polyArea(poly: V2[]): number {
  let s = 0
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i]
    const b = poly[(i + 1) % poly.length]
    s += a[0] * b[1] - b[0] * a[1]
  }
  return s / 2
}

export function ensureCCW(poly: V2[]): V2[] {
  return polyArea(poly) < 0 ? [...poly].reverse() : poly
}

export function polyCentroid(poly: V2[]): V2 {
  const a = polyArea(poly)
  if (Math.abs(a) < 1e-9) {
    const s = poly.reduce((acc, p) => add2(acc, p), [0, 0] as V2)
    return [s[0] / poly.length, s[1] / poly.length]
  }
  let cx = 0
  let cy = 0
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i]
    const q = poly[(i + 1) % poly.length]
    const f = p[0] * q[1] - q[0] * p[1]
    cx += (p[0] + q[0]) * f
    cy += (p[1] + q[1]) * f
  }
  return [cx / (6 * a), cy / (6 * a)]
}

export interface Box2 {
  min: V2
  max: V2
}

export function polyBBox(poly: V2[]): Box2 {
  const min: V2 = [Infinity, Infinity]
  const max: V2 = [-Infinity, -Infinity]
  for (const p of poly) {
    min[0] = Math.min(min[0], p[0])
    min[1] = Math.min(min[1], p[1])
    max[0] = Math.max(max[0], p[0])
    max[1] = Math.max(max[1], p[1])
  }
  return { min, max }
}

export function bboxUnion(a: Box2 | null, b: Box2): Box2 {
  if (!a) return b
  return {
    min: [Math.min(a.min[0], b.min[0]), Math.min(a.min[1], b.min[1])],
    max: [Math.max(a.max[0], b.max[0]), Math.max(a.max[1], b.max[1])],
  }
}

export function boxesOverlap(a: Box2, b: Box2, eps = 0.2): boolean {
  return (
    a.min[0] < b.max[0] - eps &&
    b.min[0] < a.max[0] - eps &&
    a.min[1] < b.max[1] - eps &&
    b.min[1] < a.max[1] - eps
  )
}

export const round = (x: number, digits = 1): number => {
  const f = Math.pow(10, digits)
  return Math.round(x * f) / f
}

export function fmtMm(x: number): string {
  const r = round(x, 1)
  return Number.isInteger(r) ? String(r) : r.toFixed(1)
}
