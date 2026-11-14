// Разбор текстового запроса. Детерминированный, без нейросетей:
// ключевые слова + числа. Всё, что не распознано, честно сообщается.

import { V2 } from './vec'
import { Part } from './model'
import {
  BuildOpts, makeBox, makeCustom, makeFrustum, makeProfile, makePyramid, makeTray, makeTube,
} from './build'

export class PromptError extends Error {}

export interface Parsed {
  part: Part
  understood: string
  hints: string[]
}

const UNIT_CM = /(\d+(?:[.,]\d+)?)\s*(?:см|cm)\b/g
const UNIT_MM = /(\d+(?:[.,]\d+)?)\s*(?:мм|mm)\b/g

function normalize(input: string): string {
  let t = input.toLowerCase().replace(/ё/g, 'е')
  t = t.replace(UNIT_CM, (_, v: string) => String(parseFloat(v.replace(',', '.')) * 10))
  t = t.replace(UNIT_MM, (_, v: string) => String(parseFloat(v.replace(',', '.'))))
  t = t.replace(/(\d)\s*[х×x*]\s*(\d)/g, '$1x$2')
  t = t.replace(/(\d)\s+на\s+(\d)/g, '$1x$2')
  t = t.replace(/(\d),(\d)/g, '$1.$2')
  t = t.replace(/[«»"'`]/g, ' ')
  t = t.replace(/[ \t]+/g, ' ')
  return t.trim()
}

function named(t: string, keys: string[]): number | null {
  const re = new RegExp(`(?:${keys.join('|')})\\s*(?:=|:|—|-)?\\s*(\\d+(?:\\.\\d+)?)`)
  const m = t.match(re)
  return m ? parseFloat(m[1]) : null
}

function has(t: string, words: string[]): boolean {
  return words.some((w) => t.includes(w))
}

function nums(t: string): number[] {
  return [...t.matchAll(/\d+(?:\.\d+)?/g)].map((m) => parseFloat(m[0]))
}

interface Triple {
  v: [number, number, number]
  at: number
}

function triple(t: string): Triple | null {
  const m = t.match(/(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)/)
  if (!m) return null
  return { v: [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3])], at: m.index ?? 0 }
}

function pairs(t: string): number[][] {
  const out: number[][] = []
  for (const m of t.matchAll(/(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)/g)) {
    out.push([parseFloat(m[1]), parseFloat(m[2])])
  }
  return out
}

const KIND_RULES: { kind: string; words: string[] }[] = [
  { kind: 'profile-z', words: ['z-профиль', 'z профиль', 'зет', 'z-образ', 'z образ'] },
  { kind: 'profile-channel', words: ['швеллер', 'channel', 'п-профиль', 'п профиль'] },
  { kind: 'profile-angle', words: ['уголок', 'уголковый', 'л-профиль', 'l-профиль', 'angle'] },
  { kind: 'frustum', words: ['конус', 'воронк', 'ведро', 'ведерк', 'frustum', 'cone', 'обечайка конус'] },
  { kind: 'pyramid', words: ['пирамид', 'pyramid', 'шатер', 'шатёр'] },
  { kind: 'glass', words: ['стакан', 'чашк', 'cup', 'кружк'] },
  { kind: 'tube', words: ['труб', 'обечайк', 'цилиндр', 'гильз', 'tube', 'cylinder', 'sleeve', 'призм', 'гран'] },
  { kind: 'box', words: ['коробк', 'короб', 'ящик', 'куб', 'box', 'cube'] },
  { kind: 'lid', words: ['крышк', 'lid', 'cover'] },
  { kind: 'tray', words: ['лоток', 'лотка', 'поддон', 'ванноч', 'tray', 'противень'] },
]

function detectKind(t: string): string | null {
  for (const rule of KIND_RULES) {
    if (has(t, rule.words)) return rule.kind
  }
  return null
}

function parseCustom(raw: string, opts: BuildOpts): Parsed | null {
  const lines = raw
    .split(/[\n;]+/)
    .map((l) => l.trim())
    .filter(Boolean)
  if (!lines.some((l) => /^(полигон|polygon|panel)\s/i.test(l))) return null
  const polys: { name: string; pts: V2[] }[] = []
  const folds: { a: string; b: string; angle: number }[] = []
  for (const line of lines) {
    const low = line.toLowerCase()
    const pm = low.match(/^(?:полигон|polygon|panel)\s+([\wа-я-]+)\s*[:=]?\s*(.+)$/i)
    if (pm) {
      const coords = pm[2].replace(/[()]/g, ' ').match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? []
      if (coords.length < 6 || coords.length % 2 !== 0) {
        throw new PromptError(`Полигон «${pm[1]}»: нужно минимум 3 пары координат X Y`)
      }
      const pts: V2[] = []
      for (let i = 0; i < coords.length; i += 2) pts.push([coords[i], coords[i + 1]])
      polys.push({ name: pm[1], pts })
      continue
    }
    const fm = low.match(/^(?:сгиб|fold|складка)\s+([\wа-я-]+)\s+([\wа-я-]+)\s*(?:угол|angle)?\s*(-?\d+(?:\.\d+)?)?/)
    if (fm) {
      folds.push({ a: fm[1], b: fm[2], angle: fm[3] ? parseFloat(fm[3]) : 90 })
      continue
    }
    if (/^(материал|толщина|tab|клапан|#|\/\/)/.test(low)) continue
    throw new PromptError(`Не понял строку «${line}». Формат: «полигон имя x y x y …» или «сгиб A B 90»`)
  }
  if (!polys.length) throw new PromptError('В запросе нет ни одного полигона')
  const part = makeCustom(polys, folds, opts, raw.trim())
  return {
    part,
    understood: `своя развёртка: ${polys.length} панел(ей), ${folds.length} сгиб(ов)`,
    hints: [],
  }
}

export function parsePrompt(input: string, opts: BuildOpts): Parsed {
  const raw = input.trim()
  if (!raw) throw new PromptError('Пустой запрос')
  const custom = parseCustom(raw, opts)
  if (custom) return custom

  const t = normalize(raw).replace(/\n/g, ' ')
  const kind = detectKind(t)
  if (!kind) {
    throw new PromptError(
      'Не понял, что строить. Начните со слова: коробка, лоток, крышка, труба, стакан, конус, пирамида, призма, уголок, швеллер, z-профиль.',
    )
  }
  const all = nums(t)
  const tr = triple(t)
  const noTabs = has(t, ['без клапан', 'без склейк'])
  const o: BuildOpts = { ...opts, tabs: opts.tabs && !noTabs }
  const hints: string[] = []

  switch (kind) {
    case 'box': {
      const open = has(t, ['без крышк', 'открыт', 'без верха', 'open'])
      const w = named(t, ['w', 'ширина', 'шириной']) ?? tr?.v[0] ?? all[0] ?? 200
      const d = named(t, ['d', 'глубина', 'глубиной']) ?? tr?.v[1] ?? all[1] ?? 150
      const h = named(t, ['h', 'высота', 'высотой']) ?? tr?.v[2] ?? all[2] ?? 100
      const part = makeBox(w, d, h, !open, o, raw)
      hints.push(open ? 'крышка не строится — коробка открытая' : 'крышка на сгибе, клапаны для склейки')
      return {
        part,
        understood: `коробка ${fmt(w)} × ${fmt(d)} × ${fmt(h)} мм, ${open ? 'без крышки' : 'с крышкой'}`,
        hints,
      }
    }
    case 'tray': {
      const w = named(t, ['w', 'ширина']) ?? tr?.v[0] ?? all[0] ?? 200
      const d = named(t, ['d', 'глубина']) ?? tr?.v[1] ?? all[1] ?? 150
      const h = named(t, ['h', 'высота', 'борт', 'высотой']) ?? tr?.v[2] ?? all[2] ?? 40
      const part = makeTray(w, d, h, o, raw)
      return { part, understood: `лоток ${fmt(w)} × ${fmt(d)} × ${fmt(h)} мм`, hints }
    }
    case 'lid': {
      const w = named(t, ['w', 'ширина']) ?? tr?.v[0] ?? all[0] ?? 200
      const d = named(t, ['d', 'глубина']) ?? tr?.v[1] ?? all[1] ?? 150
      const h = named(t, ['h', 'высота', 'борт']) ?? tr?.v[2] ?? all[2] ?? 30
      const part = makeTray(w, d, h, o, raw, 'Крышка-обечайка')
      return { part, understood: `крышка-обечайка ${fmt(w)} × ${fmt(d)} × борт ${fmt(h)} мм`, hints }
    }
    case 'tube': {
      const d = named(t, ['d', 'диаметр', 'диам']) ?? all[0] ?? 100
      const h = named(t, ['h', 'высота', 'длина', 'высотой']) ?? all[1] ?? 150
      const seg = named(t, ['гран', 'сегмент']) ?? opts.segments
      const part = makeTube(d, h, seg, o, raw, 'Обечайка')
      return {
        part,
        understood: `обечайка Ø${fmt(d)} × ${fmt(h)} мм, ${Math.round(seg)} фасеток`,
        hints: ['круглое тело приближено плоскими фасетками — так его можно согнуть из листа'],
      }
    }
    case 'glass': {
      const d = named(t, ['d', 'диаметр', 'диам']) ?? all[0] ?? 80
      const h = named(t, ['h', 'высота']) ?? all[1] ?? 110
      const seg = named(t, ['гран', 'сегмент']) ?? 6
      const part = makeTube(d, h, seg, o, raw, 'Стакан', true)
      return {
        part,
        understood: `стакан Ø${fmt(d)} × ${fmt(h)} мм, ${Math.round(seg)} граней, с дном`,
        hints: [],
      }
    }
    case 'frustum': {
      const conical = has(t, ['колпак', 'острый', 'точк'])
      const d1 = named(t, ['d1', 'd', 'диаметр']) ?? tr?.v[0] ?? all[0] ?? 140
      const d2 = conical ? 0 : (tr?.v[1] ?? (all.length >= 3 ? all[1] : d1 * 0.4))
      const h = named(t, ['h', 'высота', 'высотой']) ?? tr?.v[2] ?? (all.length >= 3 ? all[2] : (all[1] ?? 100))
      const seg = named(t, ['гран', 'сегмент']) ?? opts.segments
      const part = makeFrustum(d1, d2, h, seg, o, raw)
      return {
        part,
        understood: `${d2 < 1 ? 'конус' : 'усечённый конус'} Ø${fmt(d1)}→${fmt(d2)} × ${fmt(h)} мм`,
        hints: [],
      }
    }
    case 'pyramid': {
      const small = all.findIndex((v) => v >= 3 && v <= 16 && Number.isInteger(v))
      const n = small >= 0 ? all[small] : 4
      const rest = all.filter((_, i) => i !== small)
      const a = named(t, ['a', 'сторона', 'основание']) ?? rest[0] ?? 120
      const h = named(t, ['h', 'высота']) ?? rest[1] ?? 140
      const part = makePyramid(n, a, h, o, raw)
      return { part, understood: `пирамида: основание ${Math.round(n)}-угольник со стороной ${fmt(a)} мм, высота ${fmt(h)} мм`, hints }
    }
    case 'profile-angle':
    case 'profile-channel':
    case 'profile-z': {
      const kind2 = kind === 'profile-angle' ? 'уголок' : kind === 'profile-channel' ? 'швеллер' : 'z'
      const defaults = kind2 === 'уголок' ? [50, 50] : [60, 40, 60]
      const ps = pairs(t)
      let widths: number[] = []
      if (kind2 === 'уголок') {
        const p = ps.find((p) => Math.abs(p[0] - p[1]) < 1e-6 && p[0] >= 10) ?? ps[ps.length - 1]
        widths = p ? [p[0], p[1]] : defaults
      } else {
        const p3 = t.match(/(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)/)
        widths = p3 ? [parseFloat(p3[1]), parseFloat(p3[2]), parseFloat(p3[3])] : ps.length ? [...ps[0], ps[0][1]] : defaults
        if (widths.length !== 3) widths = defaults
      }
      const length =
        named(t, ['длина', 'длиной', 'l']) ??
        (() => {
          const used = widths
          const rest = all.filter((v) => !used.includes(v))
          return rest.length ? rest[rest.length - 1] : 300
        })()
      const part = makeProfile(kind2, widths, length, o, raw)
      const label = kind2 === 'уголок' ? 'уголок' : kind2 === 'швеллер' ? 'швеллер' : 'Z-профиль'
      return { part, understood: `${label} ${widths.join(' × ')} мм, длина ${fmt(length)} мм`, hints }
    }
    default:
      throw new PromptError('Этот тип детали пока не поддержан')
  }
}

const fmt = (x: number): string => {
  const r = Math.round(x * 10) / 10
  return Number.isInteger(r) ? String(r) : r.toFixed(1)
}

export interface Preset {
  title: string
  prompt: string
  group: string
}

export const PRESETS: Preset[] = [
  { title: 'Коробка', prompt: 'коробка 200x150x100 с крышкой', group: 'Бытовое' },
  { title: 'Лоток', prompt: 'лоток 180x120x40', group: 'Бытовое' },
  { title: 'Крышка', prompt: 'крышка 200x150x30', group: 'Бытовое' },
  { title: 'Стакан шестигранный', prompt: 'стакан 90x110 6 гран', group: 'Круглые' },
  { title: 'Обечайка', prompt: 'труба 120x200 24 гран', group: 'Круглые' },
  { title: 'Воронка', prompt: 'воронка 160x40x120 24 гран', group: 'Круглые' },
  { title: 'Конус-колпак', prompt: 'конус-колпак 140x0x160 24 гран', group: 'Круглые' },
  { title: 'Пирамида', prompt: 'пирамида 4 120 140', group: 'Круглые' },
  { title: 'Уголок', prompt: 'уголок 50x50 длина 400', group: 'Профили' },
  { title: 'Швеллер', prompt: 'швеллер 60x40x60 длина 300', group: 'Профили' },
  { title: 'Z-профиль', prompt: 'z-профиль 30x70x30 длина 500', group: 'Профили' },
  {
    title: 'Домик-коробка',
    prompt: [
      'полигон дно 0 0 160 0 160 120 0 120',
      'полигон стенка 0 120 160 120 160 200 0 200',
      'полигон клепка 0 200 160 200 160 280 0 280',
      'сгиб дно стенка 90',
      'сгиб стенка клепка 90',
    ].join('\n'),
    group: 'Своя развёртка',
  },
]
