// Выгрузка: SVG/DXF для резки, STL/OBJ для 3D, JSON для проекта.

import * as THREE from 'three'
import { Part, foldPart } from './model'
import { renderNet } from '../render/net'

const n2 = (x: number) => Math.round(x * 1000) / 1000

export function svgString(part: Part): string {
  return renderNet(part, { showDims: true, showNames: false, forExport: true })
}

export function dxfString(part: Part): string {
  const out: string[] = []
  const line = (x1: number, y1: number, x2: number, y2: number, layer: string) => {
    out.push('0', 'LINE', '8', layer)
    out.push('10', n2(x1).toFixed(3), '20', n2(y1).toFixed(3), '30', '0.0')
    out.push('11', n2(x2).toFixed(3), '21', n2(y2).toFixed(3), '31', '0.0')
  }
  const same = (u: number[], w: number[]) => Math.hypot(u[0] - w[0], u[1] - w[1]) < 0.05

  out.push('0', 'SECTION', '2', 'HEADER', '9', '$INSUNITS', '70', '4', '0', 'ENDSEC')
  out.push('0', 'SECTION', '2', 'TABLES', '0', 'TABLE', '2', 'LAYER', '70', '3')
  for (const [name, color] of [
    ['CUT', 1],
    ['FOLD', 5],
    ['TAB', 3],
  ] as [string, number][]) {
    out.push('0', 'LAYER', '2', name, '70', '0', '62', String(color), '6', 'CONTINUOUS')
  }
  out.push('0', 'ENDSEC', '0', 'SECTION', '2', 'ENTITIES')

  for (const f of part.faces) {
    const n = f.poly.length
    for (let i = 0; i < n; i++) {
      const a = f.poly[i]
      const b = f.poly[(i + 1) % n]
      const hinge = part.hinges.find(
        (h) =>
          (h.a === f.id || h.b === f.id) &&
          ((same(h.p0, a) && same(h.p1, b)) || (same(h.p0, b) && same(h.p1, a))),
      )
      line(a[0], a[1], b[0], b[1], f.kind === 'tab' ? 'TAB' : hinge ? 'FOLD' : 'CUT')
    }
  }
  out.push('0', 'ENDSEC', '0', 'EOF')
  return out.join('\r\n')
}

interface Tri {
  a: [number, number, number]
  b: [number, number, number]
  c: [number, number, number]
}

export function triangles(part: Part, thickness: number): Tri[] {
  const th = Math.max(0.2, thickness)
  const folded = foldPart(part, 1)
  const tris: Tri[] = []
  const m = new THREE.Matrix4()

  for (const pf of folded.faces) {
    const shape = new THREE.Shape(pf.face.poly.map((p) => new THREE.Vector2(p[0], p[1])))
    const geo = new THREE.ExtrudeGeometry(shape, { depth: th, bevelEnabled: false, curveSegments: 1 })
    geo.translate(0, 0, -th / 2)
    if (pf.face.kind === 'tab') geo.translate(0, 0, th * 0.9)
    const pos = geo.getAttribute('position') as THREE.BufferAttribute
    m.set(
      pf.tf.m[0], pf.tf.m[1], pf.tf.m[2], pf.tf.t[0],
      pf.tf.m[3], pf.tf.m[4], pf.tf.m[5], pf.tf.t[1],
      pf.tf.m[6], pf.tf.m[7], pf.tf.m[8], pf.tf.t[2],
      0, 0, 0, 1,
    )
    const v = new THREE.Vector3()
    const pts: [number, number, number][] = []
    for (let i = 0; i < pos.count; i += 3) {
      const tri: [number, number, number][] = []
      for (let k = 0; k < 3; k++) {
        v.fromBufferAttribute(pos, i + k).applyMatrix4(m)
        tri.push([v.x, v.y, v.z])
      }
      tris.push({ a: tri[0], b: tri[1], c: tri[2] })
      void pts
    }
    geo.dispose()
  }
  return tris
}

export function stlBuffer(part: Part, thickness: number): ArrayBuffer {
  const tris = triangles(part, thickness)
  const buf = new ArrayBuffer(84 + tris.length * 50)
  const view = new DataView(buf)
  const header = `Сгиб: ${part.name}`
  for (let i = 0; i < 80; i++) view.setUint8(i, i < header.length ? header.charCodeAt(i) & 0x7f : 32)
  view.setUint32(80, tris.length, true)
  let o = 84
  for (const t of tris) {
    const ux = t.b[0] - t.a[0], uy = t.b[1] - t.a[1], uz = t.b[2] - t.a[2]
    const vx = t.c[0] - t.a[0], vy = t.c[1] - t.a[1], vz = t.c[2] - t.a[2]
    let nx = uy * vz - uz * vy
    let ny = uz * vx - ux * vz
    let nz = ux * vy - uy * vx
    const l = Math.hypot(nx, ny, nz) || 1
    nx /= l
    ny /= l
    nz /= l
    view.setFloat32(o, nx, true)
    view.setFloat32(o + 4, ny, true)
    view.setFloat32(o + 8, nz, true)
    let p = o + 12
    for (const v of [t.a, t.b, t.c]) {
      view.setFloat32(p, v[0], true)
      view.setFloat32(p + 4, v[1], true)
      view.setFloat32(p + 8, v[2], true)
      p += 12
    }
    view.setUint16(o + 48, 0, true)
    o += 50
  }
  return buf
}

export function objString(part: Part, thickness: number): string {
  const tris = triangles(part, thickness)
  const lines: string[] = [`# Сгиб · ${part.name}`, `o ${part.name.replace(/\s+/g, '_')}`]
  let i = 1
  for (const t of tris) {
    lines.push(`v ${n2(t.a[0])} ${n2(t.a[1])} ${n2(t.a[2])}`)
    lines.push(`v ${n2(t.b[0])} ${n2(t.b[1])} ${n2(t.b[2])}`)
    lines.push(`v ${n2(t.c[0])} ${n2(t.c[1])} ${n2(t.c[2])}`)
    lines.push(`f ${i} ${i + 1} ${i + 2}`)
    i += 3
  }
  return lines.join('\n')
}

export function projectJSON(part: Part, opts: unknown): string {
  return JSON.stringify(
    {
      app: 'sgib',
      version: 1,
      savedAt: new Date().toISOString(),
      prompt: part.prompt,
      params: opts,
      part,
    },
    null,
    2,
  )
}

export function download(filename: string, data: string | ArrayBuffer, mime: string): void {
  const blob = new Blob([data], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

export function safeName(s: string): string {
  return (s || 'деталь')
    .toLowerCase()
    .replace(/[^a-zа-я0-9]+/gi, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 48) || 'detali'
}
