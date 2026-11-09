/* 0.77: панель плиток действительно собирает все примитивы.
 *
 * Проверяется не текст функции, а результат: DOM-заглушка, настоящий
 * renderTiles и манифест картинок. Плитка на панели = картинка + операция;
 * поиск фильтрует по подписи и слову операции.
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'web/js/app.js'), 'utf8').replace(/\r\n?/g, '\n');
const tiles = JSON.parse(fs.readFileSync(path.join(root, 'web/thumbs/tiles.json'), 'utf8')).tiles;

function functionSource(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`нет функции ${name}`);
  const end = source.indexOf('\n}\n', start);
  if (end < 0) throw new Error(`функция ${name} не закрыта`);
  return source.slice(start, end + 3);
}

function arraySource(name) {
  const marker = `const ${name} = `;
  const start = source.indexOf(marker);
  if (start < 0) throw new Error(`нет ${name}`);
  const begin = start + marker.length;
  const end = source.indexOf('\n];', begin) + 2;
  return source.slice(begin, end);
}

globalThis.detailParam = (value, hint) => ({ k: 'detail', v: value, hint });
const TOOL_SHAPES = eval(`(${arraySource('TOOL_SHAPES')})`);
const TOOL_LAYOUTS = eval(`(${arraySource('TOOL_LAYOUTS')})`);
const TOOL_PAINT = eval(`(${arraySource('TOOL_PAINT')})`);

/** Минимальная заглушка элемента: только то, что нужно renderTiles. */
function makeEl(tag) {
  const el = {
    tag, children: [], dataset: {}, style: {}, className: '', value: '', listeners: {},
    append(...kids) { this.children.push(...kids); },
    appendChild(kid) { this.children.push(kid); return kid; },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    focus() {}, setSelectionRange() {},
    click() { if (this.listeners.click) this.listeners.click(); },
  };
  Object.defineProperty(el, 'textContent', {
    get() { return this._text || ''; },
    set(value) { this._text = String(value); this.children = []; },
  });
  return el;
}

const tileThumbs = new Map(tiles.map((row) => [row.op, `/thumbs/${row.op}.png`]));
const tileList = tiles.map((row) => ({ op: row.op, title: row.title, params: row.params,
  url: `/thumbs/${row.op}.png` }));
const catalog = new Set([...TOOL_SHAPES, ...TOOL_LAYOUTS, ...TOOL_PAINT]
  .map((tool) => String(tool.op || '').toLowerCase()));
const inserted = [];

const names = ['document', 'tileThumbs', 'tileList', 'ALL_TOOL_SHAPES', 'addShapeTool',
  'detachedToolCard', 'insertTileOp', 'renderTools'];
const api = new Function(names.join(','), `
  let tileQuery = '';
  ${functionSource('tileMatches')}
  ${functionSource('tileGrid')}
  ${functionSource('renderTiles')}
  return { renderTiles, tileMatches, setQuery: (value) => { tileQuery = value; } };
`)(
  { createElement: makeEl },
  tileThumbs,
  tileList,
  [...TOOL_SHAPES, ...TOOL_LAYOUTS, ...TOOL_PAINT],
  (tool) => inserted.push(`card:${tool.op}`),
  () => makeEl('div'),
  (item) => inserted.push(`line:${item.op}`),
  () => {},
);

function tilesIn(node, out = []) {
  if (!node || typeof node !== 'object') return out;
  if (typeof node.className === 'string' && node.className.split(/\s+/).join(' ').includes('tile')
      && node.dataset && node.dataset.op) {
    out.push(node);
  }
  (node.children || []).forEach((kid) => tilesIn(kid, out));
  return out;
}

function heads(node, out = []) {
  if (!node || typeof node !== 'object') return out;
  if (node.className === 'tiles-group') out.push(node.textContent);
  (node.children || []).forEach((kid) => heads(kid, out));
  return out;
}

// 1. Панель покрывает манифест целиком, без дублей.
const panel = makeEl('div');
api.renderTiles(panel);
const shown = tilesIn(panel);
const ops = shown.map((el) => el.dataset.op);
assert.strictEqual(new Set(ops).size, ops.length, 'одна операция — одна плитка');
assert.strictEqual(new Set(ops).size, tiles.length, 'на панели не все плитки манифеста');
tiles.forEach((row) => assert(ops.includes(row.op), `нет плитки ${row.op}`));
assert(heads(panel).length > 0, 'плитки сгруппированы');

// 2. Плитка сверх каталога берёт подпись и картинку из манифеста.
const manifestOnly = shown.find((el) => !catalog.has(el.dataset.op));
const row = tiles.find((item) => item.op === manifestOnly.dataset.op);
const img = manifestOnly.children.find((kid) => kid.tag === 'img');
assert.strictEqual(img.src, `/thumbs/${row.op}.png`);
assert.strictEqual(manifestOnly.children.find((kid) => kid.className === 'tile-cap').textContent,
  row.title);

// 3. Клик по плитке каталога и по плитке манифеста ведут в разные пути,
//    но оба ставят операцию.
const catalogTile = shown.find((el) => catalog.has(el.dataset.op));
const extraTile = shown.find((el) => !catalog.has(el.dataset.op));
assert(catalogTile, 'в каталоге нет ни одной плитки');
assert(extraTile, 'манифест не добавил ни одной плитки сверх каталога');
catalogTile.click();
extraTile.click();
assert.deepStrictEqual(inserted, [`card:${catalogTile.dataset.op}`, `line:${extraTile.dataset.op}`]);

// 4. Поиск по подписи и по слову операции.
const search = panel.children.find((el) => el.tag === 'input');
assert(search, 'у сетки нет поиска');
const gear = tiles.find((row) => row.op === 'gear');
api.setQuery(gear.title.slice(0, 5).toLowerCase());
const filtered = makeEl('div');
api.renderTiles(filtered);
const found = tilesIn(filtered).map((el) => el.dataset.op);
assert(found.includes('gear'), 'поиск по подписи не нашёл шестерню');
assert(found.length < tiles.length, 'поиск ничего не отфильтровал');
api.setQuery('zzzzz-нет-такого');
const empty = makeEl('div');
api.renderTiles(empty);
assert.strictEqual(tilesIn(empty).length, 0, 'пустой результат поиска показал плитки');
api.setQuery('');

console.log(`Плитки в интерфейсе: ${ops.length} на панели, `
  + `${catalog.size} из каталога, поиск фильтрует.`);
