/* Карточка «Надпись» не должна выбрасывать клавиатурные спецсимволы. */
'use strict';
const fs = require('fs');
const path = require('path');
const source = fs.readFileSync(path.resolve(__dirname, '../web/js/app.js'), 'utf8')
  .replace(/\r\n?/g, '\n');
function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`нет функции ${name}`);
  const end = source.indexOf('\n}\n', start);
  if (end < 0) throw new Error(`функция ${name} не закрыта`);
  return source.slice(start, end + 3);
}
const marker = 'const TOOL_RECIPES = ';
const start = source.indexOf(marker) + marker.length;
const end = source.indexOf('\n];', start) + 2;
if (start < marker.length || end < 2) throw new Error('Не найдены карточки рецептов');
const tools = new Function(
  ['rnum', 'rvec', 'fnum'].map(functionSource).join('\n')
  + `\nreturn (${source.slice(start, end)});`
)();
const tool = tools.find((item) => item.title === 'Надпись');
if (!tool) throw new Error('Нет карточки «Надпись»');
const ascii = Array.from({ length: 95 }, (_, i) => String.fromCharCode(i + 32)).join('');
const script = tool.build({ word: ascii, size: 12, depth: 1.2 });
const encoded = JSON.stringify(ascii);
if (!script.includes(`text ${encoded} `)) {
  throw new Error('Карточка изменила текст или неверно экранировала спецсимволы');
}
for (const char of ['"', "'", '\\', '`', '|', '#', '$', '%', '&', '~']) {
  if (!encoded.includes(char)) throw new Error(`В сценарии потерян ${char}`);
}
const recipeValues = new Function(`${functionSource('recipeValues')}\nreturn recipeValues;`)();
const input = { value: ascii, checked: false };
const values = recipeValues(tool, { querySelector: () => input });
if (values.word !== ascii) throw new Error('Поле карточки обрезало ведущий пробел');
const stepToolValue = new Function(`${functionSource('stepToolValue')}\nreturn stepToolValue;`)();
if (stepToolValue(tool.fields[0], 'abc1', 1) !== null) {
  throw new Error('Текстовое поле ошибочно получило числовые стрелки');
}
console.log('Карточка «Надпись»: 95 ASCII-символов, пробелы и экранирование сохранены.');
