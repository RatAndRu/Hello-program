/**
 * Регресс 0.75: каждый параметр получает типизированный контрол.
 *
 * Проверяется модель, а не вёрстка: тип элемента, диапазон, единица, режим
 * «авто» и то, что свободный ввод остался только у `type: "str"`.
 */
import assert from 'node:assert/strict';

import {
  AUTO, controlModel, editFor, factoryValue, formatValue, modelFromCommand,
  parseLiteral, renderCommandParams, undeclaredKeys,
} from '../web/js/param_controls.js';

const num = { type: 'num', label: 'высота', min: 1, max: 100, step: 0.5, unit: 'мм' };
const int = { type: 'int', label: 'сегментов', min: 8, max: 512, step: 1, unit: '' };
const vec = { type: 'vec', label: 'габарит', size: 3, unit: 'мм', min: 0.1 };
const flag = { type: 'flag', label: 'центрировать', default: false };
const list = { type: 'enum', label: 'профиль', items: [
  { value: 'прямой', label: 'прямой' }, { value: 'холмик', label: 'холмик' },
], default: 'прямой' };
const text = { type: 'str', label: 'путь' };

// --- типы ---------------------------------------------------------------
assert.equal(controlModel(num, { key: 'h', value: 12, present: true }).kind, 'num');
assert.equal(controlModel(int, { key: 'segments', value: 64, present: true }).kind, 'int');
assert.equal(controlModel(flag, { key: 'center', value: true, present: true }).kind, 'flag');
assert.equal(controlModel(list, { key: 'form', value: 'холмик', present: true }).kind, 'enum');
assert.equal(controlModel(text, { key: 'path', value: '[[0,0,0]]', present: true }).kind, 'str');
const vector = controlModel(vec, { key: 'size', value: [10, 20, 30], present: true });
assert.equal(vector.kind, 'vec');
assert.equal(vector.components.length, 3);
assert.deepEqual(vector.components.map((c) => c.axis), ['x', 'y', 'z']);

// --- свободный ввод только у строк --------------------------------------
for (const spec of [num, int, vec, flag, list]) {
  assert.equal(controlModel(spec, { key: 'k' }).free, false, spec.type);
}
assert.equal(controlModel(text, { key: 'k' }).free, true);
assert.equal(controlModel(undefined, { key: 'что-то' }).declared, false);

// --- диапазоны и единицы -------------------------------------------------
const height = controlModel(num, { key: 'h', value: 12, present: true });
assert.equal(height.min, 1);
assert.equal(height.max, 100);
assert.equal(height.step, 0.5);
assert.equal(height.unit, 'мм');

// --- «авто» --------------------------------------------------------------
const autoSpec = { ...num, auto: 'omitted', auto_hint: 'по детализации' };
const present = controlModel(autoSpec, { key: 'segments', value: 96, present: true });
const omitted = controlModel(autoSpec, { key: 'segments', present: false });
assert.equal(present.auto.active, false);
assert.equal(omitted.auto.active, true);
assert.equal(omitted.auto.hint, 'по детализации');
assert.equal(omitted.auto.mode, 'omitted');
// снятие авто возвращает заводское значение
assert.equal(formatValue(factoryValue({ ...omitted, value: 96 })), '96');
// правка «в авто» — это unset_param, а не особое число
const autoEdit = editFor(omitted, AUTO, 12);
assert.deepEqual(autoEdit, { action: 'unset_param', param: 'segments', line: 12 });

const sentinel = controlModel({ ...num, auto: 'sentinel', sentinel_value: 0,
  auto_hint: '0 — по детализации' }, { key: 'segments', value: 96, present: true });
assert.equal(sentinel.auto.sentinel, 0);
assert.equal(editFor(sentinel, 0, 3).action, 'set_param');

const enumAuto = controlModel({ ...list, auto: 'enum', auto_hint: 'по сцене' },
  { key: 'form', present: false });
assert.ok(enumAuto.items.some((item) => item.value === 'авто'));

// --- разбор значений из сценария ----------------------------------------
assert.equal(parseLiteral('12'), 12);
assert.equal(parseLiteral('true'), true);
assert.equal(parseLiteral('[1, 2, 3]')[2], 3);
assert.equal(parseLiteral('"медь"'), 'медь');
assert.equal(parseLiteral('R/2'), 'R/2'); // связь не превращается в число

// --- модель по команде ---------------------------------------------------
const specs = { cylinder: { radius: num, height: num, segments: autoSpec } };
const command = { verb: 'cylinder', line: 4,
  kwargs: { radius: '30', height: '12' } };
const missing = modelFromCommand(specs, command, 'segments');
assert.equal(missing.present, false);
assert.equal(missing.auto.active, true);
const radius = modelFromCommand(specs, command, 'radius');
assert.equal(radius.value, 30);
assert.equal(radius.present, true);
assert.deepEqual(undeclaredKeys(specs, command, ['radius', 'wall']), ['wall']);

// --- запись значений -----------------------------------------------------
assert.equal(formatValue(1.234567), '1.2346');
assert.equal(formatValue([1, 2.5]), '[1, 2.5]');
assert.equal(formatValue(false), 'false');

// --- панель без DOM ------------------------------------------------------
// renderCommandParams рисует элементы; в node без DOM проверяем, что функция
// объявлена и требует только контейнер — остальное проверяет браузер.
assert.equal(typeof renderCommandParams, 'function');

console.log('param_controls: ok');
