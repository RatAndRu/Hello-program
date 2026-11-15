// Самопроверка геометрии: сборка без браузера.
import { foldPart, inspect, Part } from '../src/core/model'
import { V3, polyArea } from '../src/core/vec'

/** Площадь плоского многоугольника в 3D. */
function polyArea3(poly: V3[]): number {
  let x = 0, y = 0, z = 0
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i]
    const b = poly[(i + 1) % poly.length]
    x += a[1] * b[2] - a[2] * b[1]
    y += a[2] * b[0] - a[0] * b[2]
    z += a[0] * b[1] - a[1] * b[0]
  }
  return Math.hypot(x, y, z) / 2
}
import { parsePrompt, PromptError } from '../src/core/lang'
import { defaultOpts } from '../src/core/build'

let failures = 0
let checks = 0

function ok(cond: boolean, msg: string) {
  checks++
  if (!cond) {
    failures++
    console.error(`  ✗ ${msg}`)
  }
}

function near(a: number, b: number, tol: number, msg: string) {
  ok(Math.abs(a - b) <= tol, `${msg}: ${a.toFixed(2)} вместо ${b.toFixed(2)}`)
}

function build(prompt: string): Part {
  const { part, understood } = parsePrompt(prompt, defaultOpts())
  console.log(`«${prompt}»\n  → ${understood}`)
  return part
}

function checkFolded(part: Part, want: [number, number, number], tol = 1.2) {
  // want: [X, Z(высота), Y] — сверяем габарит в мировых осях после выравнивания
  const folded = foldPart(part, 1)
  ok(folded.unplaced.length === 0, `все панели размещены (${folded.unplaced.join(',')})`)
  ok(
    folded.faces.every((f) => f.poly3.every((p) => p.every((v) => Number.isFinite(v)))),
    'нет NaN в координатах',
  )
  const rep = inspect(part)
  near(rep.size[0], want[0], tol, 'габарит X')
  near(rep.size[1], want[1], tol, 'габарит Y')
  near(rep.size[2], want[2], tol, 'габарит Z (высота)')
  console.log(
    `  развёртка ${rep.netBox.max[0] - rep.netBox.min[0]} × ${rep.netBox.max[1] - rep.netBox.min[1]} мм,` +
      ` сгибов ${rep.folds}, клапанов ${rep.tabs}, площадь ${(rep.areaMm2 / 100).toFixed(0)} см²,` +
      ` сборка ${rep.size.map((v) => v.toFixed(1)).join(' × ')} мм,` +
      ` открытых рёбер ${rep.openEdges} (${rep.openLength.toFixed(0)} мм), ` +
      `${rep.closed ? 'замкнута' : 'незамкнута'}`,
  )
  if (rep.warnings.length) console.log(`  ! ${rep.warnings.join('; ')}`)
  return rep
}

console.log('== Коробка 200×150×100 ==')
{
  const part = build('коробка 200x150x100 с крышкой')
  const rep = checkFolded(part, [200, 150, 100])
  ok(rep.closed, 'коробка замкнута')
}

console.log('== Лоток 180×120×40 ==')
{
  const part = build('лоток 180x120x40')
  const rep = checkFolded(part, [180, 120, 40])
  ok(!rep.closed, 'у лотка открытый верх')
  ok(rep.openEdges === 4, `4 открытых ребра (а получилось ${rep.openEdges})`)
}

console.log('== Обечайка Ø120 h200, 24 грани ==')
{
  const part = build('труба 120x200 24 гран')
  const rep = checkFolded(part, [119, 119, 200], 3)
  ok(rep.folds === 23, `23 сгиба (а получилось ${rep.folds})`)
  ok(rep.openEdges === 48, `48 открытых рёбер кромок (а получилось ${rep.openEdges})`)
}

console.log('== Стакан Ø90 h110, 6 граней ==')
{
  const part = build('стакан 90x110 6 гран')
  checkFolded(part, [90, 78, 110], 3)
}

console.log('== Воронка ==')
{
  const part = build('воронка 160x40x120 24 гран')
  checkFolded(part, [159, 159, 120], 3)
}

console.log('== Пирамида ==')
{
  const part = build('пирамида 4 120 140')
  const rep = checkFolded(part, [120, 120, 140], 3)
  ok(rep.closed, 'пирамида замкнута')
}

console.log('== Уголок ==')
{
  const part = build('уголок 50x50 длина 400')
  const rep = checkFolded(part, [50, 400, 50], 1.5)
  ok(rep.folds === 1, 'один сгиб')
  console.log(`  габарит: ${rep.size.map((v) => v.toFixed(1)).join(' × ')}`)
}

console.log('== Швеллер ==')
{
  const part = build('швеллер 60x40x60 длина 300')
  const rep = checkFolded(part, [60, 300, 40], 2)
  console.log(`  габарит: ${rep.size.map((v) => v.toFixed(1)).join(' × ')}`)
}

console.log('== Z-профиль ==')
{
  const part = build('z-профиль 30x70x30 длина 500')
  checkFolded(part, [60, 500, 70], 3)
}

console.log('== Своя развёртка ==')
{
  const part = build(
    ['полигон дно 0 0 100 0 100 60 0 60', 'полигон стенка 0 60 100 60 100 140 0 140', 'сгиб дно стенка 90'].join('\n'),
  )
  const rep = checkFolded(part, [100, 60, 80], 1.5)
  console.log(`  площадь ${rep.areaMm2} мм²`)
}

console.log('== Шар дольками ==')
{
  const part = build('шар 120 12x8')
  const rep = inspect(part)
  ok(rep.islands === 12, `долек-островов 12 (${rep.islands})`)
  ok(rep.closed, 'шар замкнут: кромки долек сходятся')
  // Площадь листа сравниваем с идеальной сферой: разница — цена фасеток.
  const ideal = Math.PI * 120 * 120
  const k = rep.areaMm2 / ideal
  ok(k > 0.93 && k <= 1.001, `площадь шара ${(k * 100).toFixed(1)}% от 4πR² (фасетки режут углы)`)
  near(rep.size[0], 120, 4, 'габарит X')
  near(rep.size[2], 120, 4, 'габарит Z')
  // Сумма площадей плоских панелей равна сумме площадей граней в 3D.
  const flat = part.faces.filter((f) => f.kind === 'panel').reduce((s, f) => s + Math.abs(polyArea(f.poly)), 0)
  const inSpace = foldPart(part, 1).faces
    .filter((f) => f.face.kind === 'panel')
    .reduce((s, f) => s + polyArea3(f.poly3), 0)
  near(flat, inSpace, flat * 0.002, 'развёртка изометрична (площадь сохраняется)')
}

console.log('== Кружка с ручкой ==')
{
  const part = build('кружка 90x110')
  const rep = inspect(part)
  ok(rep.islands === 2, `кружка = 2 куска: обечайка и ручка (${rep.islands})`)
  near(rep.size[0], 134, 3, 'габарит с ручкой')
  near(rep.size[2], 110, 1.5, 'высота кружки')
  // Ручка в собранном виде — дуга у стенки, а не где-то ещё.
  const h = foldPart(part, 1).faces.filter((f) => f.face.name.startsWith('ручка'))
  const zs = h.flatMap((f) => f.poly3.map((q) => q[2]))
  ok(Math.min(...zs) > 5 && Math.max(...zs) < 105, 'ручка стоит по высоте кружки')
}

console.log('== Бутылка ==')
{
  const part = build('бутылка 80x220')
  const rep = inspect(part)
  near(rep.size[0], 80, 1.5, 'диаметр')
  near(rep.size[2], 220, 2, 'высота')
  ok(rep.folds > 60, `много сгибов по обечайке (${rep.folds})`)
}

console.log('== Ступенчатая пирамида ==')
{
  const part = build('ступенчатая пирамида 160 4 40')
  const rep = inspect(part)
  ok(rep.islands === 5, `ярусы отдельными кусками (${rep.islands})`)
  near(rep.size[0], 160, 2, 'основание')
  near(rep.size[2], 160, 2, 'высота 4 яруса по 40')
}

console.log('== Ошибки разбора ==')
{
  for (const bad of ['привет', 'коробка', 'сгиб']) {
    try {
      parsePrompt(bad, defaultOpts())
      console.log(`  «${bad}» → разобрано без ошибки`)
    } catch (e) {
      if (!(e instanceof PromptError)) throw e
      console.log(`  «${bad}» → ${e.message}`)
    }
  }
}

console.log(`\n${checks - failures}/${checks} проверок пройдено`)
if (failures) throw new Error(`${failures} проверок не прошло`)
