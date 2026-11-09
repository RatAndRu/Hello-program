/**
 * 0.79: значение-формула из сценария не превращается в константу.
 *
 * Типы теперь приходят из общей таблицы, поэтому контрол появляется и там, где
 * значение задано выражением (`round=R/2`, `at=[R, 0, 10]`). Такое поле должно
 * остаться читаемым и только для чтения: иначе первая же правка молча заменит
 * связь числом.
 */
import assert from 'node:assert/strict';

import {
  controlModel, parseLiteral, renderControl,
} from '../web/js/param_controls.js';

// --- минимальный DOM: проверяется модель и ветка отрисовки, не стили ---------
function makeNode(tag) {
  return {
    tag, children: [], dataset: {}, style: {}, className: '', value: '', type: '',
    title: '', readOnly: false, spellcheck: true, tabIndex: 0,
    listeners: {},
    append(...kids) { this.children.push(...kids); },
    appendChild(kid) { this.children.push(kid); return kid; },
    addEventListener(name, fn) { this.listeners[name] = fn; },
    querySelector() { return null; },
  };
}

globalThis.document = { createElement: (tag) => makeNode(tag) };

function walk(node, visit) {
  if (!node || typeof node !== 'object') return;
  visit(node);
  for (const kid of node.children || []) walk(kid, visit);
}

// --- модель ---------------------------------------------------------------
const num = { type: 'num', label: 'радиус', min: 1, max: 100, step: 0.5, unit: 'мм' };
const vec = { type: 'vec', label: 'положение', size: 3, unit: 'мм' };

const free = controlModel(num, { key: 'radius', value: parseLiteral('R/2'), present: true });
assert.equal(free.kind, 'num');
assert.equal(free.linked, true);
assert.equal(free.raw, 'R/2');

const plain = controlModel(num, { key: 'radius', value: 12, present: true });
assert.equal(plain.linked, undefined);
assert.equal(plain.raw, undefined);

const linkedVec = controlModel(vec, { key: 'at', value: parseLiteral('[R, 0, 10]'), present: true });
assert.equal(linkedVec.kind, 'vec');
assert.equal(linkedVec.linked, true);
assert.equal(linkedVec.raw, '[R, 0, 10]');

const numericVec = controlModel(vec, { key: 'at', value: [1.5, 0, 10], present: true });
assert.equal(numericVec.linked, undefined);

// Число, пришедшее строкой, связью не считается: сервер так отдаёт float.
assert.equal(controlModel(num, { key: 'h', value: '12.5', present: true }).linked, undefined);

// --- отрисовка ------------------------------------------------------------
const linkedRow = renderControl(free, () => {});
let linkedInput = null;
let sliders = 0;
let steps = 0;
walk(linkedRow, (node) => {
  if (node.dataset && node.dataset.linked === '1') linkedInput = node;
  if (node.className === 'pc-slider') sliders += 1;
  if (node.className === 'pc-step') steps += 1;
});
assert.ok(linkedInput, 'связанное значение показывается текстовым полем');
assert.equal(linkedInput.value, 'R/2');
assert.equal(linkedInput.readOnly, true);
assert.equal(sliders, 0, 'ползунок у формулы не появляется');
assert.equal(steps, 0, 'кнопки шага у формулы не появляются');

const plainRow = renderControl(plain, () => {});
let numberInput = null;
sliders = 0;
steps = 0;
walk(plainRow, (node) => {
  if (node.className === 'pc-num') numberInput = node;
  if (node.className === 'pc-slider') sliders += 1;
  if (node.className === 'pc-step') steps += 1;
});
assert.equal(numberInput.type, 'number');
assert.equal(numberInput.readOnly, false);
assert.equal(sliders, 1, 'обычное число по-прежнему с ползунком');
assert.equal(steps, 2);

console.log('param_linked_test: ok');
