// Самопроверка геометрии: сборка без браузера.
import { foldPart, inspect, Part } from '../src/core/model'
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
