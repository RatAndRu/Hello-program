/* Карточки обновлённых примитивов формируют настоящие сохраняемые параметры. */
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

function cardFor(tool, overrides = {}) {
  return {
    querySelector(selector) {
      const match = selector.match(/data-key="([^"]+)/);
      const param = tool.params.find((item) => item.k === match[1]);
      if (!param) return null;
      const value = Object.prototype.hasOwnProperty.call(overrides, param.k)
        ? overrides[param.k] : param.v;
      return {
        value: String(value ?? ''),
        checked: param.kind === 'bool' ? Boolean(value) : value !== false,
      };
    },
  };
}

const wanted = ['box', 'sphere', 'ellipsoid', 'capsule', 'heart', 'crescent',
  'star', 'lightning', 'track', 'hinge', 'door_handle'];
const output = {};
for (const op of wanted) {
  const tool = tools.find((item) => item.op === op);
  if (!tool) throw new Error(`нет карточки ${op}`);
  if (!tool.desc || tool.desc.length < 45) throw new Error(`${op}: нет понятной справки`);
  if (!tool.params.length) throw new Error(`${op}: нет полей`);
  const script = shapeScript(tool, cardFor(tool));
  if (!script.includes(op)) throw new Error(`${op}: в сценарии нет команды`);
  if (/undefined|NaN/.test(script)) throw new Error(`${op}: потерян параметр`);
  if (script.includes('\\n')) throw new Error(`${op}: literal \\n вместо перевода строки`);
  output[op] = script;
}
for (const op of ['box', 'sphere', 'ellipsoid', 'capsule']) {
  const tool = tools.find((item) => item.op === op);
  for (const key of ['expand', 'expand_side', 'expand_joint', 'expand_seat', 'expand_smooth']) {
    if (!tool.params.some((p) => p.k === key)) throw new Error(`${op}: нет поля ${key}`);
  }
  if (!output[op].includes('expand_joint=посадка')) throw new Error(`${op}: не сохранён тип стыка`);
  if (output[op].includes('expand_seat=')) throw new Error(`${op}: авто-заход не должен становиться 0`);
}
if (!output.star.includes('facet=нет')) throw new Error('star: режим граней не сохранён');
if (!output.lightning.includes('zigzags=1')) throw new Error('lightning: число зигзагов не сохранено');
const track = tools.find((item) => item.op === 'track');
const noSleepers = shapeScript(track, cardFor(track, { sleepers: false }));
if (!noSleepers.includes('sleepers=нет') || noSleepers.includes('fasteners=')) {
  throw new Error('track: отключенные шпалы оставили противоречащие крепления');
}
for (const op of ['track', 'hinge', 'door_handle']) {
  const tool = tools.find((item) => item.op === op);
  if (tool.group !== 'Готовые детали') throw new Error(`${op}: неверная группа`);
}
const handle = tools.find((item) => item.op === 'door_handle');
if (!output.door_handle.includes('blend=3') || output.door_handle.includes('resolution=')) {
  throw new Error('door_handle: SDF-сопряжение или авторазрешение не сохранены');
}
const customHandle = shapeScript(handle, cardFor(handle, { blend: 4.5, resolution: 0.42 }));
if (!customHandle.includes('blend=4.5') || !customHandle.includes('resolution=0.42')) {
  throw new Error('door_handle: явные параметры SDF потеряны');
}
const lockHandle = shapeScript(handle, cardFor(handle, {
  form: 'прямоугольная', rosette: 'овальная', lock: true, lock_plug: true,
}));
if (!lockHandle.includes('form=прямоугольная') || !lockHandle.includes('rosette=овальная')
    || !lockHandle.includes('lock=да') || !lockHandle.includes('lock_plug=да')) {
  throw new Error('door_handle: форма, розетка или замок не сохранены карточкой');
}
const noLockHandle = shapeScript(handle, cardFor(handle, { lock: false, lock_plug: true }));
if (noLockHandle.includes('lock_plug=')) {
  throw new Error('door_handle: карточка оставила цилиндр без скважины');
}
if (process.argv.includes('--json')) console.log(JSON.stringify(output));
else console.log(`Сценарии ${wanted.length} карточек примитивов сформированы без подмен параметров.`);
