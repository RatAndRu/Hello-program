// Служебный скрипт: выгружает списки полигонов для растеризации (проверка геометрии).
import { writeFileSync, mkdirSync } from 'node:fs'
import { parsePrompt } from '../src/core/lang'
import { defaultOpts } from '../src/core/build'
import { foldPart, inspect, foldList } from '../src/core/model'
import { polyBBox } from '../src/core/vec'

const prompts = [
  'коробка 200x150x100 с крышкой',
  'лоток 180x120x40',
  'труба 120x200 12 гран',
  'воронка 160x40x120 16 гран',
  'пирамида 4 120 140',
  'уголок 50x50 длина 400',
  'стакан 90x110 6 гран',
  'крышка 200x150x30',
  'шар 120 12x8',
  'кружка 90x110',
  'бутылка 80x220',
  'ступенчатая пирамида 160 4 40',
]

type Poly = { pts: [number, number][]; fill: string; stroke: string; w: number }
type Line = { pts: [number, number][]; color: string; w: number; dash?: number[] }

mkdirSync('tmp', { recursive: true })

const out: { name: string; prompt: string; net: (Poly | Line)[]; solid: Poly[]; stats: string }[] = []

for (const prompt of prompts) {
  const { part } = parsePrompt(prompt, defaultOpts())
  const rep = inspect(part)

  // ---------- развёртка ----------
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const f of part.faces) {
    const b = polyBBox(f.poly)
    minX = Math.min(minX, b.min[0]); minY = Math.min(minY, b.min[1])
    maxX = Math.max(maxX, b.max[0]); maxY = Math.max(maxY, b.max[1])
  }
  const W = maxX - minX, H = maxY - minY
  const S = 760 / Math.max(W, H)
  const pad = 20
  const tx = (p: [number, number]): [number, number] => [(p[0] - minX) * S + pad, (maxY - p[1]) * S + pad]

  const net: (Poly | Line)[] = []
  const size = { w: W * S + pad * 2, h: H * S + pad * 2 }
  for (const f of part.faces) {
    net.push({
      pts: f.poly.map((p) => tx(p as [number, number])),
      fill: f.kind === 'tab' ? '#e7c79a' : '#f2ecdf',
      stroke: f.kind === 'tab' ? '#c9a878' : '#f2ecdf',
      w: 0.5,
    })
  }
  const same = (u: number[], w: number[]) => Math.hypot(u[0] - w[0], u[1] - w[1]) < 0.05
  for (const f of part.faces) {
    if (f.kind === 'tab') continue
    const n = f.poly.length
    for (let i = 0; i < n; i++) {
      const a = f.poly[i], b = f.poly[(i + 1) % n]
      const hinge = part.hinges.find(
        (h) =>
          (h.a === f.id || h.b === f.id) &&
          ((same(h.p0, a) && same(h.p1, b)) || (same(h.p0, b) && same(h.p1, a))),
      )
      net.push({
        pts: [tx(a as [number, number]), tx(b as [number, number])],
        color: hinge ? '#c07d1e' : '#3a2f22',
        w: hinge ? 1.8 : 2.4,
        dash: hinge ? [6, 4] : undefined,
      })
    }
  }
  for (const f of foldList(part)) {
    const mx = (f.p0[0] + f.p1[0]) / 2
    const my = (f.p0[1] + f.p1[1]) / 2
    const c = tx([mx, my])
    net.push({ pts: [c, c], color: '#c07d1e', w: 5 })
  }

  // ---------- сборка ----------
  const folded = foldPart(part, 1)
  const dir = [0.62, -0.72, 0.42]
  const dl = Math.hypot(...dir)
  const view = dir.map((v) => v / dl)
  const up0 = [0, 0, 1]
  const right = [
    view[1] * up0[2] - view[2] * up0[1],
    view[2] * up0[0] - view[0] * up0[2],
    view[0] * up0[1] - view[1] * up0[0],
  ]
  const rl = Math.hypot(...right)
  const rt = right.map((v) => v / rl)
  const up = [
    rt[1] * view[2] - rt[2] * view[1],
    rt[2] * view[0] - rt[0] * view[2],
    rt[0] * view[1] - rt[1] * view[0],
  ]
  const proj = (p: number[]): [number, number, number] => [
    p[0] * rt[0] + p[1] * rt[1] + p[2] * rt[2],
    p[0] * up[0] + p[1] * up[1] + p[2] * up[2],
    p[0] * view[0] + p[1] * view[1] + p[2] * view[2],
  ]
  const pr = folded.faces.filter((pf) => pf.face.kind === 'panel').map((pf) => ({
    pts: pf.poly3.map(proj),
    n: pf.normal,
    tab: pf.face.kind === 'tab',
  }))
  let sx0 = Infinity, sy0 = Infinity, sx1 = -Infinity, sy1 = -Infinity
  for (const f of pr) for (const p of f.pts) {
    sx0 = Math.min(sx0, p[0]); sx1 = Math.max(sx1, p[0])
    sy0 = Math.min(sy0, p[1]); sy1 = Math.max(sy1, p[1])
  }
  const SS = 640 / Math.max(sx1 - sx0, sy1 - sy0)
  const sTx = (p: [number, number]): [number, number] => [
    (p[0] - sx0) * SS + 30,
    (sy1 - p[1]) * SS + 30,
  ]
  pr.sort((a, b) => avg(a.pts) - avg(b.pts))
  const solid: Poly[] = pr.map((f) => ({
    pts: f.pts.map((p) => sTx([p[0], p[1]])),
    fill: f.tab ? '#e8a95e' : shade(f.n),
    stroke: '#3a2f22',
    w: 0.9,
  }))

  out.push({
    name: part.name,
    prompt,
    net,
    solid,
    stats: `развёртка ${Math.round(W)}×${Math.round(H)}; сборка ${rep.size.map((v) => v.toFixed(0)).join('×')}; открыто ${rep.openEdges}; сгибов ${rep.folds}; клапанов ${rep.tabs}`,
    netSize: size,
  } as never)
  console.log(`${part.name}: ${out[out.length - 1].stats}`)
}

function avg(pts: number[][]): number {
  return pts.reduce((s, p) => s + p[2], 0) / pts.length
}

function shade(n: number[]): string {
  const light = [0.45, -0.55, 0.72]
  const d = Math.abs(
    (n[0] * light[0] + n[1] * light[1] + n[2] * light[2]) /
      (Math.hypot(n[0], n[1], n[2]) * Math.hypot(...light)),
  )
  const c = Math.round(105 + 125 * Math.pow(d, 0.65))
  return `rgb(${Math.min(255, Math.round(c * 1.03))},${Math.min(255, Math.round(c * 0.96))},${Math.min(255, Math.round(c * 0.83))})`
}

writeFileSync('tmp/scene.json', JSON.stringify(out))
