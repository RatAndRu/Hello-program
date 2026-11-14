import './style.css'
import { parsePrompt, PromptError, PRESETS, Preset } from './core/lang'
import { BuildOpts, defaultOpts } from './core/build'
import { Report, Part, inspect, foldList, netSize } from './core/model'
import { NetView } from './render/net'
import { Scene3D } from './render/scene'
import {
  dxfString, download, objString, projectJSON, safeName, stlBuffer, svgString,
} from './core/export'
import { helpHTML } from './ui/help'

const $ = <T extends HTMLElement = HTMLElement>(sel: string): T =>
  document.querySelector(sel) as T

const STORE = 'sgib.state.v1'

interface State {
  prompt: string
  opts: BuildOpts
  history: string[]
  fold: number
}

const state: State = {
  prompt: 'коробка 200x150x100 с крышкой',
  opts: defaultOpts(),
  history: [],
  fold: 1,
}

let part: Part | null = null
let report: Report | null = null
let netView: NetView
let scene: Scene3D
let anim = 0

// ---------------------------------------------------------------- параметры

const num = (id: string, fallback: number): number => {
  const v = parseFloat(($(id) as HTMLInputElement).value)
  return isFinite(v) ? v : fallback
}

function readOpts(): BuildOpts {
  return {
    thickness: Math.max(0.2, num('#thickness', 2)),
    tabs: ($('#tabs') as HTMLInputElement).checked,
    tabHeight: Math.max(3, num('#tabH', 8)),
    segments: Math.max(3, Math.min(72, Math.round(num('#segments', 24)))),
  }
}

function writeOpts(o: BuildOpts): void {
  ;($('#thickness') as HTMLInputElement).value = String(o.thickness)
  ;($('#tabs') as HTMLInputElement).checked = o.tabs
  ;($('#tabH') as HTMLInputElement).value = String(o.tabHeight)
  ;($('#segments') as HTMLInputElement).value = String(o.segments)
}

function persist(): void {
  try {
    localStorage.setItem(STORE, JSON.stringify(state))
  } catch {
    /* приватный режим — не страшно */
  }
}

function restore(): void {
  try {
    const raw = localStorage.getItem(STORE)
    if (!raw) return
    const s = JSON.parse(raw) as Partial<State>
    if (s.prompt) state.prompt = s.prompt
    if (s.opts) state.opts = { ...state.opts, ...s.opts }
    if (Array.isArray(s.history)) state.history = s.history.slice(0, 12)
    if (typeof s.fold === 'number') state.fold = s.fold
  } catch {
    /* игнорируем битое состояние */
  }
}

// ---------------------------------------------------------------- сборка

function build(prompt = ($('#prompt') as HTMLTextAreaElement).value, opts = readOpts()): boolean {
  state.prompt = prompt
  state.opts = opts
  const verdict = $('#verdict')
  try {
    const parsed = parsePrompt(prompt, opts)
    part = parsed.part
    report = inspect(part)
    verdict.className = 'verdict'
    verdict.innerHTML =
      `<span class="tick">✓</span><span>Понял как <b>${escapeHTML(parsed.understood)}</b>` +
      (parsed.hints.length ? ` <span class="hint">— ${escapeHTML(parsed.hints.join('; '))}</span>` : '') +
      `</span>`
    applyPart(true)
    pushHistory(prompt)
    persist()
    return true
  } catch (e) {
    const msg = e instanceof PromptError ? e.message : (e as Error).message
    verdict.className = 'verdict error'
    verdict.innerHTML = `<span>✗</span><span>${escapeHTML(msg)}</span>`
    if (!part) {
      // пустой экран: покажем пример
      renderEmpty()
    }
    return false
  }
}

function applyPart(resetFold: boolean): void {
  if (!part || !report) return
  netView.setPart(part)
  scene.setThickness(state.opts.thickness, false)
  scene.setPart(part)
  renderReport(report)
  renderFolds(part)
  renderStatus(report)
  if (resetFold) {
    setFold(1, false)
  } else {
    setFold(state.fold, false)
  }
}

function renderEmpty(): void {
  $('#report').innerHTML =
    `<div class="r-row"><span>Пока пусто</span></div>` +
    `<div class="r-row"><span>Выберите пример слева или напишите свой запрос</span></div>`
  $('#folds').innerHTML = ''
  $('#status').innerHTML = ''
  $('#netHost').innerHTML =
    `<div class="empty-net"><span>Здесь появится развёртка</span>` +
    `<span class="muted">например: «коробка 200x150x100 с крышкой»</span></div>`
  scene.setPart(emptyPart())
}

let emptyCache: Part | null = null
function emptyPart(): Part {
  if (emptyCache) return emptyCache
  emptyCache = {
    name: 'Пусто',
    prompt: '',
    faces: [],
    hinges: [],
    up: [0, 0, 1],
  }
  return emptyCache
}

function renderReport(r: Report): void {
  const rows: string[] = []
  const nb = r.netBox
  const w = nb.max[0] - nb.min[0]
  const h = nb.max[1] - nb.min[1]
  rows.push(row('Развёртка', `${fmt(w)} × ${fmt(h)} мм`))
  rows.push(row('Габарит детали', `${fmt(r.size[0])} × ${fmt(r.size[1])} × ${fmt(r.size[2])} мм`))
  rows.push(row('Площадь материала', `${(r.areaMm2 / 100).toFixed(0)} см²`))
  rows.push(row('Сгибов', `${r.folds} · ${Math.round(r.totalAngle)}°`))
  rows.push(row('Реза', `${(r.cutMm / 10).toFixed(0)} см`))
  if (r.tabs) rows.push(row('Клапанов', String(r.tabs)))

  const badge = r.closed
    ? `<div class="r-badge ok">✓ оболочка замкнута</div>`
    : r.glueEdges && !r.openEdges
      ? `<div class="r-badge ok">✓ замкнута, ${r.glueEdges} ребра под склейку</div>`
      : `<div class="r-badge ${r.openEdges > 6 ? 'warn' : 'ok'}">◌ открыто ${r.openEdges} рёбер · ${Math.round(r.openLength)} мм</div>`

  const warns = r.warnings.length
    ? `<div class="warns">${r.warnings.map((x) => `<div>⚠ ${escapeHTML(x)}</div>`).join('')}</div>`
    : ''

  $('#report').innerHTML = badge + rows.join('') + warns
}

const row = (k: string, v: string) => `<div class="r-row"><span>${k}</span><b>${v}</b></div>`

function renderFolds(p: Part): void {
  const list = foldList(p)
  $('#foldCount').textContent = list.length ? `${list.length}` : ''
  $('#folds').innerHTML = list
    .map(
      (f) =>
        `<div class="fold-row" title="${escapeHTML(f.a)} ↔ ${escapeHTML(f.b)}"><i>${f.idx}</i>` +
        `<span>${escapeHTML(f.a)} ↔ ${escapeHTML(f.b)}</span><b>${Math.round(Math.abs(f.angle))}°</b></div>`,
    )
    .join('')
}

function renderStatus(r: Report): void {
  const bits = [
    `<span><b>${fmt(r.size[0])}</b> × <b>${fmt(r.size[1])}</b> × <b>${fmt(r.size[2])}</b> мм</span>`,
    `<span>${(r.areaMm2 / 100).toFixed(0)} см²</span>`,
    `<span>${r.folds} сгиб${plural(r.folds)}</span>`,
    `<span>${r.closed ? 'замкнута' : `открыто ${r.openEdges}`}</span>`,
  ]
  $('#status').innerHTML = bits.join('<span class="sep">·</span>')
}

const plural = (n: number) => (n % 10 === 1 && n % 100 !== 11 ? '' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? 'а' : 'ов')

// ---------------------------------------------------------------- складка

function setFold(t: number, fromUser = true): void {
  state.fold = t
  const slider = $('#fold') as HTMLInputElement
  slider.value = String(Math.round(t * 1000))
  slider.style.setProperty('--p', `${t * 100}%`)
  $('#foldPct').textContent = `${Math.round(t * 100)}%`
  $('#foldLine').textContent = t < 0.02 ? 'лист' : t > 0.98 ? 'собрано' : 'сгибаем'
  scene.setFold(t)
  if (fromUser) persist()
}

function play(): void {
  cancelAnimationFrame(anim)
  const from = state.fold > 0.5 ? 1 : 0
  const to = from === 1 ? 0 : 1
  const dur = 1250
  const t0 = performance.now()
  const step = (now: number) => {
    const k = Math.min(1, (now - t0) / dur)
    const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2
    setFold(from + (to - from) * e)
    if (k < 1) anim = requestAnimationFrame(step)
  }
  anim = requestAnimationFrame(step)
}

// ---------------------------------------------------------------- история

function pushHistory(prompt: string): void {
  const p = prompt.trim()
  if (!p) return
  state.history = [p, ...state.history.filter((x) => x !== p)].slice(0, 12)
  renderHistory()
}

function renderHistory(): void {
  const el = $('#history')
  el.innerHTML = state.history
    .map((h) => `<div class="h-item" title="${escapeHTML(h)}">${escapeHTML(h.replace(/\n/g, ' ⏎ '))}</div>`)
    .join('')
  el.querySelectorAll('.h-item').forEach((node, i) => {
    node.addEventListener('click', () => {
      const p = state.history[i]
      ;($('#prompt') as HTMLTextAreaElement).value = p
      build(p)
    })
  })
}

// ---------------------------------------------------------------- пресеты

let presetList: Preset[] = []

function renderPresets(): void {
  const el = $('#chips')
  const groups: Preset['group'][] = ['Бытовое', 'Круглые', 'Профили', 'Своя развёртка']
  presetList = groups.flatMap((g) => PRESETS.filter((p) => p.group === g))
  el.innerHTML = groups
    .map((g) =>
      PRESETS.filter((p) => p.group === g)
        .map((p) => {
          const i = presetList.indexOf(p)
          return `<button class="chip" data-preset="${i}" title="${escapeHTML(p.prompt.replace(/\n/g, ' ⏎ '))}">${escapeHTML(p.title)}</button>`
        })
        .join(''),
    )
    .join('')
  el.querySelectorAll('.chip').forEach((node) => {
    node.addEventListener('click', () => {
      const i = parseInt((node as HTMLElement).dataset.preset ?? '0', 10)
      const p = presetList[i]?.prompt ?? ''
      ;($('#prompt') as HTMLTextAreaElement).value = p
      build(p)
    })
  })
}

// ---------------------------------------------------------------- экспорт

function renderExports(): void {
  const buttons: [string, string, string][] = [
    ['SVG · выкройка', 'svg', 'wide'],
    ['DXF · лазер', 'dxf', ''],
    ['STL · 3D', 'stl', ''],
    ['OBJ · 3D', 'obj', ''],
    ['JSON · проект', 'json', 'wide'],
  ]
  const el = $('#exports')
  el.innerHTML = buttons
    .map(([label, kind, cls]) => `<button class="${cls}" data-export="${kind}">${label}</button>`)
    .join('')
  el.querySelectorAll('button').forEach((node) => {
    node.addEventListener('click', () => doExport((node as HTMLElement).dataset.export ?? ''))
  })
}

function doExport(kind: string): void {
  if (!part) return
  const name = safeName(part.name + '-' + fmt(netSize(part)[0]) + 'x' + fmt(netSize(part)[1]))
  switch (kind) {
    case 'svg':
      download(`${name}.svg`, svgString(part), 'image/svg+xml')
      break
    case 'dxf':
      download(`${name}.dxf`, dxfString(part), 'image/vnd.dxf')
      break
    case 'stl':
      download(`${name}.stl`, stlBuffer(part, state.opts.thickness), 'model/stl')
      break
    case 'obj':
      download(`${name}.obj`, objString(part, state.opts.thickness), 'model/obj')
      break
    case 'json':
      download(`${name}.json`, projectJSON(part, state.opts), 'application/json')
      break
  }
  flash(`Выгружено: ${name}.${kind === 'json' ? 'json' : kind}`)
}

function flash(msg: string): void {
  const el = $('#verdict')
  if (!el) return
  const prev = el.innerHTML
  const prevClass = el.className
  el.className = 'verdict'
  el.innerHTML = `<span class="tick">↓</span><span>${escapeHTML(msg)}</span>`
  setTimeout(() => {
    el.innerHTML = prev
    el.className = prevClass
  }, 2200)
}

// ---------------------------------------------------------------- помощь

function openHelp(): void {
  $('#modalContent').innerHTML = helpHTML()
  $('#modal').hidden = false
}

// ---------------------------------------------------------------- запуск

function escapeHTML(s: string): string {
  return s.replace(/[<>&]/g, (c) => (c === '<' ? '&lt;' : c === '>' ? '&gt;' : '&amp;'))
}

const fmt = (x: number): string => {
  const r = Math.round(x * 10) / 10
  return Number.isInteger(r) ? String(r) : r.toFixed(1)
}

function init(): void {
  restore()

  netView = new NetView($('#netHost'))
  scene = new Scene3D($('#threeHost'))
  ;(window as unknown as Record<string, unknown>).__sgib = { scene, netView }

  ;($('#prompt') as HTMLTextAreaElement).value = state.prompt
  writeOpts(state.opts)
  renderPresets()
  renderHistory()
  renderExports()

  $('#build').addEventListener('click', () => build())
  $('#play').addEventListener('click', play)
  $('#btnHelp').addEventListener('click', openHelp)
  $('#modalClose').addEventListener('click', () => ($('#modal').hidden = true))
  $('#modal').addEventListener('click', (e) => {
    if (e.target === $('#modal')) $('#modal').hidden = true
  })

  $('#clearHistory').addEventListener('click', () => {
    state.history = []
    renderHistory()
    persist()
  })

  const slider = $('#fold') as HTMLInputElement
  slider.addEventListener('input', () => setFold(parseInt(slider.value, 10) / 1000))

  // изменение параметров — пересборка
  for (const id of ['#tabs', '#tabH', '#segments']) {
    $(id).addEventListener('change', () => build(state.prompt))
  }
  $('#thickness').addEventListener('input', () => {
    const t = num('#thickness', 2)
    state.opts = { ...readOpts(), thickness: t }
    scene.setThickness(t)
    persist()
  })
  $('#thickness').addEventListener('change', () => build(state.prompt))

  // горячие клавиши
  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      build()
    }
    if (e.key === 'Escape' && !$('#modal').hidden) $('#modal').hidden = true
    const tag = (e.target as HTMLElement)?.tagName
    if (tag !== 'TEXTAREA' && tag !== 'INPUT' && e.code === 'Space') {
      e.preventDefault()
      play()
    }
  })

  // инструменты видов
  document.querySelectorAll('[data-net]').forEach((b) => {
    b.addEventListener('click', () => {
      const k = (b as HTMLElement).dataset.net
      if (k === 'zoomin') netView.zoom(1.25)
      if (k === 'zoomout') netView.zoom(1 / 1.25)
      if (k === 'fit') netView.fit()
      if (k === 'dims' || k === 'names') {
        const el = b as HTMLElement
        const pressed = el.getAttribute('aria-pressed') !== 'true'
        el.setAttribute('aria-pressed', String(pressed))
        netView.setOptions(k === 'dims' ? { showDims: pressed } : { showNames: pressed })
      }
    })
  })
  document.querySelectorAll('[data-3d]').forEach((b) => {
    b.addEventListener('click', () => {
      const k = (b as HTMLElement).dataset['3d']
      if (k === 'fit') {
        scene.fit()
        return
      }
      const el = b as HTMLElement
      const pressed = el.getAttribute('aria-pressed') !== 'true'
      el.setAttribute('aria-pressed', String(pressed))
      if (k === 'edges') scene.setToggles({ edges: pressed })
      if (k === 'grid') scene.setToggles({ grid: pressed })
    })
  })

  $('#btnSave').addEventListener('click', () => doExport('json'))
  $('#btnImport').addEventListener('click', () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = '.json,application/json'
    input.addEventListener('change', () => {
      const file = input.files?.[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = () => {
        try {
          const data = JSON.parse(String(reader.result))
          if (!data?.part?.faces) throw new Error('В файле нет детали')
          ;($('#prompt') as HTMLTextAreaElement).value = data.prompt ?? ''
          state.history = [data.prompt ?? '', ...state.history.filter((x) => x !== data.prompt)].slice(0, 12)
          renderHistory()
          build(data.prompt ?? '')
        } catch (err) {
          flash(`Не открылось: ${(err as Error).message}`)
        }
      }
      reader.readAsText(file)
    })
    input.click()
  })

  // первая сборка + эффектное складывание
  const ok = build(state.prompt)
  if (ok) {
    setFold(0, false)
    setTimeout(() => {
      const t0 = performance.now()
      const step = (now: number) => {
        const k = Math.min(1, (now - t0) / 1700)
        const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2
        setFold(e, false)
        if (k < 1) requestAnimationFrame(step)
      }
      requestAnimationFrame(step)
    }, 380)
  }
}

init()
