/* Регресс 0.43: все числовые стрелки ограничены и останавливаются на границе. */
'use strict';
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'web/js/app.js'), 'utf8');

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`нет функции ${name}`);
  const end = source.indexOf('\n}\n', start);
  if (end < 0) throw new Error(`функция ${name} не закрыта`);
  return source.slice(start, end + 3);
}

globalThis.TOOL_COLOR_STEPS = [];
const { stepToolValue } = new Function(
  ['fnum', 'numFromText', 'stepToolValue'].map(functionSource).join('\n')
  + '\nreturn { stepToolValue };'
)();
globalThis.detailParam = (value, hint) => ({
  k: 'detail', label: 'детализация', v: value, min: 0, max: 5, step: 1,
  kind: 'slider', hint,
});
function catalog(name) {
  const marker = `const ${name} = `;
  const start = source.indexOf(marker) + marker.length;
  const end = source.indexOf('\n];', start) + 2;
  return eval(`(${source.slice(start, end)})`);
}

let count = 0;
const failures = [];
for (const card of [...catalog('TOOL_SHAPES'), ...catalog('TOOL_RECIPES')]) {
  for (const p of card.params || []) {
    const numeric = !['raw', 'vec', 'bool', 'color'].includes(p.kind)
      && !p.choices && typeof p.v === 'number';
    if (!numeric) continue;
    count += 1;
    const id = `${card.op}.${p.k}`;
    if (!Number.isFinite(p.min) || !Number.isFinite(p.max) || p.min > p.max) {
      failures.push(`${id}: нет конечных min/max`);
      continue;
    }
    if (p.v < p.min || p.v > p.max) failures.push(`${id}: default вне диапазона`);
    const above = Number(stepToolValue(p, String(p.max), 1));
    const below = Number(stepToolValue(p, String(p.min), -1));
    if (above !== p.max) failures.push(`${id}: max → ${above}`);
    if (below !== p.min) failures.push(`${id}: min → ${below}`);
    const inwardLow = Number(stepToolValue(p, String(p.min), 1));
    const inwardHigh = Number(stepToolValue(p, String(p.max), -1));
    if (inwardLow < p.min || inwardLow > p.max) failures.push(`${id}: шаг от min вне диапазона`);
    if (inwardHigh < p.min || inwardHigh > p.max) failures.push(`${id}: шаг от max вне диапазона`);
  }
}
if (failures.length) {
  console.error(failures.join('\n'));
  process.exit(1);
}
console.log(`Числовых полей: ${count}; границы min/max и остановка стрелок проверены.`);
