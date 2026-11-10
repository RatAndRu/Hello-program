/* 0.77: плитка из манифеста вставляет ровно одну строку операции. */
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

let captured = null;
const helpers = `
let tileQuery = '';
function __setQuery(value) { tileQuery = value; }
function uniqueObjectName(name) { return name; }
function currentScript() { return 'куб = box size=[10,10,10]\\n'; }
function insertTool(lines, label) { globalThis.__sent = { lines, label }; }
`;
const { insertTileOp, tileMatches, __setQuery } = new Function(
  helpers + [functionSource('insertTileOp'), functionSource('tileMatches')].join('\n')
    + '\nreturn { insertTileOp, tileMatches, __setQuery };'
)();

const arch = tiles.find((tile) => tile.op === 'arch');
assert(arch, 'в манифесте нет арки');
insertTileOp(arch);
captured = globalThis.__sent;
assert.strictEqual(captured.lines, 'arch = arch');
assert.strictEqual(captured.label, arch.title);

// Заводские параметры едут в ту же строку и не теряются.
const hull = tiles.find((tile) => tile.op === 'hull');
insertTileOp(hull);
captured = globalThis.__sent;
assert(captured.lines.startsWith('hull = hull points='), captured.lines);
assert.strictEqual(captured.lines.split('\n').length, 1, 'плитка ставит одну строку');

// Параметров нет — строка остаётся без хвостового пробела.
tiles.forEach((tile) => {
  insertTileOp(tile);
  const lines = globalThis.__sent.lines;
  assert.strictEqual(lines.trim(), lines, tile.op);
  assert(!lines.includes('  '), tile.op);
});

// Поиск по подписи и слову операции: пустой запрос пропускает всё.
assert.strictEqual(tileMatches({ op: 'arch', title: 'Арка' }), true);
__setQuery('шестер');
assert.strictEqual(tileMatches({ op: 'gear', title: 'Шестерня' }), true);
assert.strictEqual(tileMatches({ op: 'arch', title: 'Арка' }), false);
__setQuery('web');
assert.strictEqual(tileMatches({ op: 'web', title: 'Паутина' }), true, 'слово операции тоже ищется');

console.log(`Плитки: ${tiles.length} строк манифеста, клик вставляет одну операцию.`);
