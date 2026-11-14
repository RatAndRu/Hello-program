// Отрисовка развёртки: SVG в миллиметрах, 1:1, с линиями реза и сгиба.

import { Part, Face, foldList, pointInPoly } from '../core/model'
import { V2, polyArea, polyBBox, polyCentroid, round } from '../core/vec'

export interface NetOpts {
  showDims: boolean
  showNames: boolean
  /** Для файла на лазер: отдельные слои, без «бумаги». */
  forExport?: boolean
}

interface EdgeDraw {
  p0: V2
  p1: V2
  fold: boolean
}

const fmt = (x: number) => {
  const r = round(x, 1)
  return Number.isInteger(r) ? String(r) : r.toFixed(1)
}

function faceEdges(part: Part, face: Face): EdgeDraw[] {
  const out: EdgeDraw[] = []
  const same = (u: V2, w: V2) => Math.hypot(u[0] - w[0], u[1] - w[1]) < 0.05
  const n = face.poly.length
  for (let i = 0; i < n; i++) {
    const p0 = face.poly[i]
    const p1 = face.poly[(i + 1) % n]
    const fold = part.hinges.some(
      (h) =>
        (h.a === face.id || h.b === face.id) &&
        ((same(h.p0, p0) && same(h.p1, p1)) || (same(h.p0, p1) && same(h.p1, p0))),
    )
    out.push({ p0, p1, fold })
  }
  return out
}

export function netExtent(part: Part): { min: V2; max: V2; w: number; h: number } {
  let min: V2 = [Infinity, Infinity]
  let max: V2 = [-Infinity, -Infinity]
  for (const f of part.faces) {
    const b = polyBBox(f.poly)
    min = [Math.min(min[0], b.min[0]), Math.min(min[1], b.min[1])]
    max = [Math.max(max[0], b.max[0]), Math.max(max[1], b.max[1])]
  }
  if (!isFinite(min[0])) return { min: [0, 0], max: [100, 100], w: 100, h: 100 }
  return { min, max, w: max[0] - min[0], h: max[1] - min[1] }
}

/** SVG-строка развёртки. Координаты — миллиметры, Y вверх (как в модели). */
export function renderNet(part: Part, opts: NetOpts): string {
  const ext = netExtent(part)
  const dim = Math.max(ext.w, ext.h)
  const pad = opts.forExport ? Math.max(10, dim * 0.045) : Math.max(9, dim * 0.05)
  // Поля несимметричные: слева и снизу живут размерные линии.
  const padL = pad * 1.55
  const padB = pad * 1.45
  const padR = pad * 0.8
  const padT = pad * 0.7
  const vb = {
    x: ext.min[0] - padL,
    y: -ext.max[1] - padB,
    w: ext.w + padL + padR,
    h: ext.h + padB + padT,
  }
  const fs = Math.max(3.5, dim / 48)
  const fsSmall = fs * 0.8
  // Для файла — толщина в мм (лазеру важен контур), на экране — в пикселях при вписанном масштабе.
  const stroke = opts.forExport ? 0.25 : Math.max(0.6, dim / 380)
  const dash = opts.forExport ? `${fs * 0.9} ${fs * 0.7}` : `${dim / 95} ${dim / 150}`

  const paper = opts.forExport ? '#ffffff' : '#f2ecdf'
  const cutColor = opts.forExport ? '#e2001a' : '#2b2419'
  const foldColor = opts.forExport ? '#0057ff' : '#c07d1e'

  const parts: string[] = []

  const hatch = Math.max(3.5, dim / 90)
  parts.push(`<defs>
    <pattern id="hatch" width="${hatch}" height="${hatch}" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
      <rect width="${hatch}" height="${hatch}" fill="${paper}"/>
      <line x1="0" y1="0" x2="0" y2="${hatch}" stroke="${cutColor}" stroke-width="${hatch * 0.11}" opacity="0.5"/>
    </pattern>
    <filter id="paperShadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="${fs * 0.25}" stdDeviation="${fs * 0.3}" flood-color="#000" flood-opacity="0.45"/>
    </filter>
    <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 z" fill="${opts.forExport ? '#555' : '#8c7b5f'}"/>
    </marker>
  </defs>`)

  // На экране лист — это силуэт выкройки; для файла печатаем во всю страницу.
  if (opts.forExport) {
    parts.push(`<rect x="${vb.x}" y="${vb.y}" width="${vb.w}" height="${vb.h}" fill="${paper}"/>`)
  } else {
    parts.push(`<g filter="url(#paperShadow)">`)
  }

  // Панели
  for (const f of part.faces) {
    const pts = f.poly.map((p) => `${round(p[0], 2)},${round(-p[1], 2)}`).join(' ')
    if (f.kind === 'tab') {
      parts.push(`<polygon points="${pts}" fill="url(#hatch)" stroke="${cutColor}" stroke-width="${stroke}"/>`)
    } else {
      parts.push(`<polygon points="${pts}" fill="${paper}" stroke="${paper}" stroke-width="${stroke * 0.6}"/>`)
    }
  }
  if (!opts.forExport) parts.push('</g>')

  // Тени от линий сгиба — тонкая светлая подложка под бумагой не нужна, но
  // панели обводим резами.
  for (const f of part.faces) {
    if (f.kind === 'tab') continue
    const edges = faceEdges(part, f)
    for (const e of edges) {
      if (e.fold) continue
      parts.push(
        `<line x1="${round(e.p0[0], 2)}" y1="${round(-e.p0[1], 2)}" x2="${round(e.p1[0], 2)}" y2="${round(-e.p1[1], 2)}" stroke="${cutColor}" stroke-width="${stroke}" stroke-linecap="round"/>`,
      )
    }
  }

  // Линии сгиба — нумерация совпадает с панелью «Сборка»
  const foldSegs = foldList(part).map((f) => ({ p0: f.p0, p1: f.p1, idx: f.idx, angle: f.angle }))
  for (const s of foldSegs) {
    parts.push(
      `<line x1="${round(s.p0[0], 2)}" y1="${round(-s.p0[1], 2)}" x2="${round(s.p1[0], 2)}" y2="${round(-s.p1[1], 2)}" stroke="${foldColor}" stroke-width="${stroke * 1.02}" stroke-dasharray="${dash}" stroke-linecap="round"/>`,
    )
  }

  // Номера сгибов
  if (!opts.forExport && foldSegs.length <= 18) {
    for (const s of foldSegs) {
      const mx = (s.p0[0] + s.p1[0]) / 2
      const my = -(s.p0[1] + s.p1[1]) / 2
      const r = fs * 0.95
      parts.push(
        `<circle cx="${round(mx, 2)}" cy="${round(my, 2)}" r="${r}" fill="${paper}" stroke="${foldColor}" stroke-width="${stroke * 0.66}" opacity="0.95"/>` +
          `<text x="${round(mx, 2)}" y="${round(my + fs * 0.32, 2)}" font-family="ui-monospace,monospace" font-size="${fs * 0.95}" fill="${foldColor}" text-anchor="middle">${s.idx}</text>`,
      )
    }
  }

  // Подписи панелей
  const panels = part.faces.filter((f) => f.kind !== 'tab')
  if (opts.showNames && !opts.forExport && panels.length <= 14) {
    for (const f of panels) {
      const b = polyBBox(f.poly)
      const w = b.max[0] - b.min[0]
      const h = b.max[1] - b.min[1]
      if (w < fs * 4.8 || h < fs * 3.2) continue
      // центр подписи — центроид полигона, а не центр габарита:
      // у секторов конуса это заметно.
      const c = polyCentroid(f.poly)
      const cx = c[0]
      const cy = -c[1]
      // подпись не должна вылезать за панель
      const perChar = fsSmall * 0.6
      const fit = Math.floor((w * 0.78 - fs) / perChar)
      if (fit < 4) continue
      const label =
        f.name.length > fit ? `${f.name.slice(0, Math.max(2, fit - 1))}…` : f.name
      parts.push(
        `<text x="${round(cx, 2)}" y="${round(cy, 2)}" font-family="-apple-system,Segoe UI,sans-serif" font-size="${fsSmall}" fill="#6d5f49" text-anchor="middle">${escapeXml(label)}</text>` +
          `<text x="${round(cx, 2)}" y="${round(cy + fsSmall * 1.2, 2)}" font-family="ui-monospace,monospace" font-size="${fsSmall * 0.82}" fill="#8d7f68" text-anchor="middle">${fmt(w)} × ${fmt(h)}</text>`,
      )
    }
  }

  // Габаритные размеры
  if (opts.showDims) {
    const dimColor = opts.forExport ? '#666' : '#8c7b5f'
    const y = -ext.min[1] + padB * 0.42
    const x0 = ext.min[0]
    const x1 = ext.max[0]
    parts.push(
      `<line x1="${round(x0, 2)}" y1="${round(y, 2)}" x2="${round(x1, 2)}" y2="${round(y, 2)}" stroke="${dimColor}" stroke-width="${stroke * 0.6}" marker-start="url(#arr)" marker-end="url(#arr)"/>`,
    )
    parts.push(
      `<text x="${round((x0 + x1) / 2, 2)}" y="${round(y + fs * 1.35, 2)}" font-family="ui-monospace,monospace" font-size="${fsSmall}" fill="${dimColor}" text-anchor="middle">${fmt(ext.w)} мм</text>`,
    )
    const x = ext.min[0] - padL * 0.55
    const y0 = -ext.max[1]
    const y1 = -ext.min[1]
    parts.push(
      `<line x1="${round(x, 2)}" y1="${round(y0, 2)}" x2="${round(x, 2)}" y2="${round(y1, 2)}" stroke="${dimColor}" stroke-width="${stroke * 0.6}" marker-start="url(#arr)" marker-end="url(#arr)"/>`,
    )
    parts.push(
      `<text x="${round(x - fs * 0.42, 2)}" y="${round((y0 + y1) / 2, 2)}" font-family="ui-monospace,monospace" font-size="${fsSmall}" fill="${dimColor}" text-anchor="middle" transform="rotate(-90 ${round(x - fs * 0.42, 2)} ${round((y0 + y1) / 2, 2)})">${fmt(ext.h)} мм</text>`,
    )
  }

  // Штамп
  if (opts.forExport) {
    const area = part.faces
      .filter((f) => f.kind === 'panel')
      .reduce((s, f) => s + Math.abs(polyArea(f.poly)), 0)
    const x = ext.min[0]
    const y = -ext.min[1] + padB * 0.5
    parts.push(
      `<text x="${round(x, 2)}" y="${round(y + fs * 3, 2)}" font-family="ui-monospace,monospace" font-size="${fsSmall}" fill="#444">${escapeXml(part.name)} · ${fmt(ext.w)} × ${fmt(ext.h)} мм · ${(area / 100).toFixed(0)} см² · 1:1</text>`,
    )
  }

  const vbStr = `${round(vb.x, 2)} ${round(vb.y, 2)} ${round(vb.w, 2)} ${round(vb.h, 2)}`
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vbStr}" preserveAspectRatio="xMidYMid meet" data-vb="${vbStr}">
    <g id="world">${parts.join('\n')}</g>
  </svg>`
}

function escapeXml(s: string): string {
  return s.replace(/[<>&"']/g, (c) =>
    c === '<' ? '&lt;' : c === '>' ? '&gt;' : c === '&' ? '&amp;' : c === '"' ? '&quot;' : '&apos;',
  )
}

/** Интерактивная развёртка: панорама колесом и мышью. */
export class NetView {
  private host: HTMLElement
  private svg: SVGSVGElement | null = null
  private world: SVGGElement | null = null
  private scale = 1
  private tx = 0
  private ty = 0
  private vb = { x: 0, y: 0, w: 100, h: 100 }
  private part: Part | null = null
  private opts: NetOpts = { showDims: true, showNames: true }
  private dragging = false
  private last = { x: 0, y: 0 }

  constructor(host: HTMLElement) {
    this.host = host
    host.addEventListener('wheel', this.onWheel, { passive: false })
    host.addEventListener('pointerdown', this.onDown)
    window.addEventListener('pointermove', this.onMove)
    window.addEventListener('pointerup', this.onUp)
  }

  setOptions(opts: Partial<NetOpts>) {
    this.opts = { ...this.opts, ...opts }
    if (this.part) this.render(this.part)
  }

  setPart(part: Part) {
    this.part = part
    this.render(part)
    this.fit()
  }

  private render(part: Part) {
    this.host.innerHTML =
      `<div class="legend"><span class="cut"><i></i>рез</span><span class="fold"><i></i>сгиб</span><span class="tab"><i></i>клапан</span></div>` +
      renderNet(part, this.opts)
    this.svg = this.host.querySelector('svg')
    this.world = this.host.querySelector('#world')
    const vbAttr = this.svg?.getAttribute('viewBox') ?? '0 0 100 100'
    const [x, y, w, h] = vbAttr.split(/\s+/).map(Number)
    this.vb = { x, y, w, h }
    const badge = document.createElement('div')
    badge.className = 'badge'
    badge.id = 'netBadge'
    const ext = netExtent(part)
    badge.textContent = `${fmt(ext.w)} × ${fmt(ext.h)} мм · 1:1`
    this.host.appendChild(badge)
    this.apply()
  }

  private apply() {
    if (!this.world) return
    const cx = this.vb.x + this.vb.w / 2
    const cy = this.vb.y + this.vb.h / 2
    this.world.setAttribute(
      'transform',
      `translate(${this.tx} ${this.ty}) translate(${cx} ${cy}) scale(${this.scale}) translate(${-cx} ${-cy})`,
    )
  }

  fit() {
    this.scale = 1
    this.tx = 0
    this.ty = 0
    this.apply()
  }

  zoom(factor: number) {
    this.scale = Math.max(0.2, Math.min(14, this.scale * factor))
    this.apply()
  }

  private onWheel = (e: WheelEvent) => {
    e.preventDefault()
    const k = e.deltaY < 0 ? 1.12 : 1 / 1.12
    const before = this.toNet(e.clientX, e.clientY)
    this.scale = Math.max(0.2, Math.min(14, this.scale * k))
    const after = this.toNet(e.clientX, e.clientY)
    if (before && after) {
      this.tx += before[0] - after[0]
      this.ty += before[1] - after[1]
    }
    this.apply()
  }

  private toNet(clientX: number, clientY: number): V2 | null {
    if (!this.svg) return null
    const pt = this.svg.createSVGPoint()
    pt.x = clientX
    pt.y = clientY
    const m = this.svg.getScreenCTM()
    if (!m) return null
    const local = pt.matrixTransform(m.inverse())
    // обратное к world-преобразованию
    const cx = this.vb.x + this.vb.w / 2
    const cy = this.vb.y + this.vb.h / 2
    return [
      (local.x - this.tx - cx) / this.scale + cx,
      (local.y - this.ty - cy) / this.scale + cy,
    ]
  }

  private onDown = (e: PointerEvent) => {
    if (e.button !== 0) return
    this.dragging = true
    this.last = { x: e.clientX, y: e.clientY }
  }

  private onMove = (e: PointerEvent) => {
    if (!this.dragging || !this.svg) return
    const m = this.svg.getScreenCTM()
    if (!m) return
    const k = 1 / (m.a || 1)
    this.tx += (e.clientX - this.last.x) * k
    this.ty += (e.clientY - this.last.y) * k
    this.last = { x: e.clientX, y: e.clientY }
    this.apply()
  }

  private onUp = () => {
    this.dragging = false
  }
}

export { fmt as fmtMm, pointInPoly }
