/* Регресс 0.52: сценарии живых карточек интерьера совпадают с вставкой в проект. */
'use strict';
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'web/js/app.js'), 'utf8').replace(/\r\n?/g, '\n');
globalThis.detailParam = (value, hint) => ({ k: 'detail', v: value, hint });

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`нет функции ${name}`);
  const end = source.indexOf('\n}\n', start);
  if (end < 0) throw new Error(`функция ${name} не закрыта`);
  return source.slice(start, end + 3);
}

const marker = 'const TOOL_SHAPES = ';
const start = source.indexOf(marker) + marker.length;
const end = source.indexOf('\n];', start) + 2;
const tools = eval(`(${source.slice(start, end)})`);
const { shapeScript } = new Function(
  ['shapeParams', 'shapeScript'].map(functionSource).join('\n') + '\nreturn { shapeScript };'
)();
const wanted = ['table', 'door', 'window', 'curtain', 'drape', 'rug', 'socket', 'switch', 'bulb'];
const output = {};
for (const op of wanted) {
  const tool = tools.find((item) => item.op === op);
  if (!tool) throw new Error(`нет карточки ${op}`);
  const card = {
    querySelector(selector) {
      const match = selector.match(/data-key="([^"]+)/);
      const param = tool.params.find((item) => item.k === match[1]);
      return param ? { value: String(param.v ?? ''), checked: param.v !== false } : null;
    },
  };
  const script = shapeScript(tool, card);
  if (!script.includes(op)) throw new Error(`${op}: в сценарии нет команды`);
  if (script.includes('\\n')) throw new Error(`${op}: literal \\n вместо перевода строки`);
  if (!script.trim()) throw new Error(`${op}: пустой сценарий`);
  output[op] = script;
}
if ((output.drape.match(/\n/g) || []).length !== 2) {
  throw new Error('drape: карточка должна построить опору, ткань и выполнить drape');
}
// Авто-поля окна не должны перекрывать defaults выбранного типа. Иначе карточка
// панорамы молча отправляла opening=все casing=да sill=да вместо неподвижного
// панорамного блока. Явные пользовательские значения по-прежнему сохраняются.
for (const key of ['sections', 'opening', 'casing', 'sill']) {
  if (output.window.includes(`${key}=`)) throw new Error(`window: авто ${key} попало в команду`);
}
const windowTool = tools.find((item) => item.op === 'window');
const overrides = { type: 'панорамное', sections: '4', opening: 'все', casing: 'да', sill: 'нет' };
const explicitParams = windowTool.params.map((p) => ({ ...p, v: overrides[p.k] ?? p.v }));
const explicitTool = { ...windowTool, params: explicitParams };
const explicitCard = {
  querySelector(selector) {
    const match = selector.match(/data-key="([^"]+)/);
    const param = explicitParams.find((item) => item.k === match[1]);
    return param ? { value: String(param.v ?? ''), checked: param.v !== false } : null;
  },
};
const explicit = shapeScript(explicitTool, explicitCard);
for (const part of ['type=панорамное', 'sections=4', 'opening=все', 'casing=да', 'sill=нет']) {
  if (!explicit.includes(part)) throw new Error(`window: потерян явный параметр ${part}`);
}
if (process.argv.includes('--json')) console.log(JSON.stringify(output));
else console.log(`Сценарии ${wanted.length} интерьерных карточек сформированы без подмен параметров.`);
