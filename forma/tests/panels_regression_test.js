/* Минимальный DOM-repro: ⤢ должен расширять активную панель, не только прятать соседей. */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

function classes(initial = []) {
  const values = new Set(initial);
  return {
    toggle(name, force) { if (force) values.add(name); else values.delete(name); },
    contains(name) { return values.has(name); },
  };
}

async function main() {
  const elements = {};
  for (const [name, id] of Object.entries({ editor: 'panel-editor', viewer: 'panel-viewer', report: 'panel-report' })) {
    elements[id] = { classList: classes(['panel']) };
  }
  const styleValues = {};
  const layout = {
    clientWidth: 1000,
    style: { setProperty(name, value) { styleValues[name] = value; } },
  };
  globalThis.localStorage = { getItem() { return null; }, setItem() {} };
  globalThis.window = { addEventListener() {} };
  globalThis.document = {
    getElementById(id) { return elements[id] || null; },
    querySelectorAll() { return []; },
  };
  const { PanelLayout } = await import(pathToFileURL(path.resolve(__dirname, '../web/js/panels.js')));
  const panels = new PanelLayout({ layout });
  const width = (name) => parseInt(styleValues[`--w-${name}`], 10);
  const total = () => width('editor') + width('viewer') + width('report') + 18;

  panels.toggleMaximize('viewer');
  assert.strictEqual(width('editor'), 26);
  assert.strictEqual(width('report'), 26);
  assert.strictEqual(width('viewer'), 930, 'viewer получает всё освободившееся место');
  assert.strictEqual(total(), 1000, 'ширины не оставляют пустую полосу и не переполняют layout');
  assert(!elements['panel-viewer'].classList.contains('is-collapsed'));

  panels.toggleMaximize('viewer');
  assert(width('viewer') > 26 && total() === 1000, 'повторный ⤢ возвращает трёхпанельный вид');

  panels.toggleCollapse('viewer');
  assert.strictEqual(width('viewer'), 26);
  panels.toggleMaximize('viewer');
  assert.strictEqual(width('viewer'), 930, 'даже ранее свёрнутая цель разворачивается');
  assert(!elements['panel-viewer'].classList.contains('is-collapsed'));
  panels.toggleMaximize('viewer');
  assert.strictEqual(width('viewer'), 26, 'возврат сохраняет прежнее collapsed-состояние');

  const css = fs.readFileSync(path.resolve(__dirname, '../web/css/app.css'), 'utf8');
  assert(css.includes('grid-template-rows: auto minmax(0, 1fr) 42px 30px;'),
    'перенесённые кнопки не должны перекрываться фиксированной строкой toolbar');
  assert(/\.actions\s*\{[^}]*min-width:\s*0;[^}]*flex-wrap:\s*wrap;/s.test(css),
    'actions обязаны сжиматься и переноситься внутри доступной ширины');
  console.log('Панели: maximize расширяет цель, сохраняет сумму ширин и прежний вид.');
}

main().catch((error) => { console.error(error.stack || error); process.exit(1); });
