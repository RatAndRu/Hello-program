/* 0.78: шаг в стек объекта — поля, отправка и откат в интерфейсе.
 *
 * Проверяется поведение, а не текст: форма собирает значения по каталогу,
 * кнопка отправляет один шаг, а при отказе сервера текст сценария
 * возвращается к прежнему виду.
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'web/js/app.js'), 'utf8').replace(/\r\n?/g, '\n');

function functionSource(name) {
  const found = source.indexOf(`function ${name}(`);
  if (found < 0) throw new Error(`нет функции ${name}`);
  // `async` слева от объявления — часть функции: без него внутри окажется await.
  const start = source.slice(Math.max(0, found - 6), found) === 'async ' ? found - 6 : found;
  const end = source.indexOf('\n}\n', found);
  if (end < 0) throw new Error(`функция ${name} не закрыта`);
  return source.slice(start, end + 3);
}

function makeEl(tag) {
  const el = {
    tag, children: [], dataset: {}, style: {}, className: '', value: '', type: '',
    selected: false, listeners: {},
    append(...kids) { this.children.push(...kids); },
    appendChild(kid) { this.children.push(kid); return kid; },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    querySelector(selector) {
      const key = selector.replace('[data-step="', '').replace('"]', '');
      const walk = (node) => {
        if (!node || typeof node !== 'object') return null;
        if (node.dataset && node.dataset.step === key) return node;
        for (const kid of node.children || []) {
          const hit = walk(kid);
          if (hit) return hit;
        }
        return null;
      };
      return walk(this);
    },
    click() { if (this.listeners.click) this.listeners.click({ preventDefault() {} }); },
  };
  Object.defineProperty(el, 'innerHTML', { get() { return ''; }, set() { this.children = []; } });
  return el;
}

const catalog = [
  { op: 'union', title: 'Объединить с деталью', hint: 'Сливает детали',
    fields: [{ k: 'other', label: 'деталь', kind: 'object', required: true }] },
  { op: 'color', title: 'Покрасить', hint: 'Меняет цвет',
    fields: [{ k: 'color', label: 'цвет', kind: 'color', default: '#c9d1e3' },
             { k: 'material', label: 'материал', kind: 'text', default: 'plastic' }] },
];
const payload = {
  objects: [{ name: 'корпус' }, { name: 'крышка' }],
  provenance: [{ object: 'корпус', op: 'box', parents: [] }],
  timings: { total: 12 },
};
const calls = { api: [], script: [], built: [], errors: [], toasts: [] };
const env = {
  state: { heavyApproved: new Set() },
  currentScript: () => 'корпус = box size=[40, 40, 40]\n',
  api: async (path, body) => {
    calls.api.push({ path, body });
    if (env.failNext) { env.failNext = false; throw { message: 'Сценарий с этим шагом не собрался.' }; }
    return { ok: true, script: body.script + body.op + '\n', line: `${body.op} корпус`,
      line_number: 2, timings: { total: 9 } };
  },
  setScript: (text) => calls.script.push(text),
  applyBuild: (result) => calls.built.push(result),
  showError: (error) => calls.errors.push(error),
  toast: (text) => calls.toasts.push(text),
  $: () => makeEl('span'),
};

const names = ['document', 'stepCatalog', 'state', 'currentScript', 'api', 'setScript',
  'applyBuild', 'showError', 'toast', '$'];
const factory = new Function(names.join(','), `
  ${functionSource('applyStep')}
  ${functionSource('stepField')}
  ${functionSource('stepObjectNames')}
  ${functionSource('stepValues')}
  ${functionSource('stepAdder')}
  return { applyStep, stepAdder, stepValues, stepField };
`);
const ui = factory({ createElement: makeEl }, catalog, env.state, env.currentScript, env.api,
  env.setScript, env.applyBuild, env.showError, env.toast, env.$);

// 1. Форма: выбор операции и поля по каталогу, детали — из сцены.
const card = ui.stepAdder(payload, 'корпус', [{ line: 1, last_line: 1 }]);
const select = card.children.find((kid) => kid.tag === 'select');
assert(select, 'в блоке нет выбора операции');
assert.strictEqual(select.children.length, catalog.length);
const fields = card.children.find((kid) => kid.className.includes('step-fields'));
const label = fields.children[0];
const other = label.children[1];
assert.strictEqual(other.dataset.step, 'other', 'для объединения нет поля детали');
assert.strictEqual(other.tag, 'select');
assert.strictEqual(other.children.length, 3, 'две детали плюс пустой пункт');
assert.deepStrictEqual(other.children.slice(1).map((option) => option.value),
  ['корпус', 'крышка']);

// 2. Значения полей собираются по именам параметров.
other.children[1].selected = true;
other.value = 'крышка';
assert.deepStrictEqual(ui.stepValues(catalog[0], card), { other: 'крышка' });

// 3. Кнопка отправляет один шаг и применяет новый текст.
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function main() {
  const button = card.children.find((kid) => kid.className.includes('step-add'));
  button.click();
  await tick();
  assert.strictEqual(calls.api.length, 1, 'шаг должен уйти одним запросом');
  assert.strictEqual(calls.api[0].path, '/api/step');
  assert.strictEqual(calls.api[0].body.op, 'union');
  assert.strictEqual(calls.api[0].body.object, 'корпус');
  assert.deepStrictEqual(calls.api[0].body.values, { other: 'крышка' });
  assert.strictEqual(calls.api[0].body.after_line, 1);
  assert.strictEqual(calls.built.length, 1, 'успешный шаг перестраивает сцену');
  assert.strictEqual(calls.script.length, 1, 'успешный шаг ставит новый текст');
  assert.notStrictEqual(calls.script[0], env.currentScript());

  // 4. Отказ сервера — откат: в редактор возвращается прежний текст.
  env.failNext = true;
  await ui.applyStep('корпус', catalog[1], { color: '#ff0000' }, 1);
  await tick();
  assert.strictEqual(calls.errors.length, 1, 'причина отказа показана');
  assert.strictEqual(calls.script[calls.script.length - 1], env.currentScript(),
    'после отказа в редакторе остаётся прежний текст');
  console.log('Шаг объекта: поля, отправка и откат проверены.');
}

main().catch((err) => { console.error(err); process.exit(1); });
