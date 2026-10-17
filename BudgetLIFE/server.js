#!/usr/bin/env node
/**
 * BudgetLIFE — локальный сервер приложения.
 *
 * В терминах стандарта SPECIALS это роль `app.py`: единственная точка входа,
 * которая знает свой блок портов, отдаёт интерфейс и служебные маршруты.
 *
 * Правила стандарта, соблюдённые здесь:
 *   • порт берётся ТОЛЬКО из своего блока (ports.json рядом с сервером),
 *     основной порт фиксирован — иначе «уедет» origin у установленного PWA;
 *   • порт занят — берём следующий из своего блока (никогда не сканируем подряд);
 *   • занятость проверяется честным bind-ом с SO_EXCLUSIVEADDRUSE, а не connect-ом;
 *   • выбранный порт пишется в data/port.txt (первая строка — число, ниже JSON);
 *   • обязательные маршруты: /api/identity (личность) и /api/health (готовность);
 *   • HTML, service worker и манифест отдаются с no-store — правки видны сразу;
 *   • логи пишутся в logs/server.log с ротацией;
 *   • остановка: снять слушателя, освободить порт-лок, убрать data/port.txt.
 *
 * Запуск:
 *   node server.js                          # свой блок портов, 127.0.0.1
 *   node server.js --port 5130 --host 127.0.0.1
 *   node server.js --dir dist               # что раздавать
 *   PORT=5130 HOST=127.0.0.1 node server.js
 */

import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

// ───────────────────────────── паспорт приложения ───────────────────────────
const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_ID = 'budgetlife';
const APP_NAME = 'BudgetLIFE';
const FALLBACK_BLOCK = { base: 5130, size: 10 }; // если ports.json потерян
const LOCK_RANGE = [18900, 18999]; // служебные порты-локи (вне блоков приложений)

const STARTED_AT = new Date();
const NODE_BIN = process.execPath;

// ───────────────────────────────── утилиты ──────────────────────────────────
function readVersion() {
  try {
    return JSON.parse(fs.readFileSync(path.join(HERE, 'package.json'), 'utf8')).version ?? '0.0.0';
  } catch {
    return '0.0.0';
  }
}

const VERSION = readVersion();

function parseArgs(argv) {
  const args = { port: null, host: null, dir: null, help: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--help' || arg === '-h') args.help = true;
    else if (arg.startsWith('--port=')) args.port = Number(arg.slice('--port='.length));
    else if (arg.startsWith('--host=')) args.host = arg.slice('--host='.length);
    else if (arg.startsWith('--dir=')) args.dir = arg.slice('--dir='.length);
  }
  return args;
}

/** Свой блок портов из ports.json (файл лежит рядом с сервером). */
function loadBlock() {
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(HERE, 'ports.json'), 'utf8'));
    const mine = (raw.blocks ?? []).find((b) => b.app_id === APP_ID);
    if (mine && Number.isFinite(mine.base)) {
      return { base: Number(mine.base), size: Number(mine.size) || FALLBACK_BLOCK.size };
    }
  } catch {
    /* файла нет или он бит — работаем на резервном блоке */
  }
  return { ...FALLBACK_BLOCK };
}

/** Кандидаты: сначала предпочтительный (или основной), дальше — свой блок. */
function candidates(block, prefer) {
  const list = [];
  const push = (p) => {
    if (Number.isFinite(p) && p > 0 && p < 65536 && !list.includes(p)) list.push(p);
  };
  push(prefer ?? block.base);
  for (let p = block.base; p < block.base + block.size; p += 1) push(p);
  return list;
}

/** Служебный порт-лок: защищает от гонки при одновременном запуске. */
function lockPortFor(appId) {
  const hash = createHash('sha1').update(appId).digest();
  const span = LOCK_RANGE[1] - LOCK_RANGE[0] + 1;
  return LOCK_RANGE[0] + (hash.readUInt16BE(0) % span);
}

function atomicWriteSync(file, text) {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, text, 'utf8');
  fs.renameSync(tmp, file); // rename атомарен — файла «наполовину записан» не бывает
}

/** data/port.txt: первая строка — число (совместимость), ниже — JSON. */
function writePortFile(dataDir, info) {
  const file = path.join(dataDir, 'port.txt');
  const payload = JSON.stringify({ ...info, updated_at: new Date().toISOString() });
  atomicWriteSync(file, `${info.port}\n${payload}\n`);
}

// ─────────────────────────────────── логи ───────────────────────────────────
const LOG_MAX_BYTES = 1024 * 1024; // 1 МБ, как в стандарте
const LOG_KEEP = 3;

let logFile = null;

function rotateIfNeeded(file) {
  try {
    const size = fs.statSync(file).size;
    if (size < LOG_MAX_BYTES) return;
    for (let i = LOG_KEEP - 1; i >= 1; i -= 1) {
      const from = `${file}.${i}`;
      const to = `${file}.${i + 1}`;
      if (fs.existsSync(from)) fs.renameSync(from, to);
    }
    fs.renameSync(file, `${file}.1`);
  } catch {
    /* лог не должен ронять сервер */
  }
}

function log(message, level = 'INFO') {
  const line = `[${new Date().toISOString()}] ${level} ${message}`;
  if (process.stdout?.writable) process.stdout.write(`${line}\n`);
  if (!logFile) return;
  try {
    if (fs.existsSync(logFile)) rotateIfNeeded(logFile);
    fs.appendFileSync(logFile, `${line}\n`, 'utf8');
  } catch {
    /* нет доступа к логу — работаем дальше */
  }
}

// ──────────────────────────────── HTTP-ответы ───────────────────────────────
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.webmanifest': 'application/manifest+json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.txt': 'text/plain; charset=utf-8',
  '.wasm': 'application/wasm',
};

function send(res, status, body, headers = {}) {
  res.writeHead(status, { 'X-App-Id': APP_ID, ...headers });
  res.end(body);
}

function sendJson(res, status, data, cache = 'no-store') {
  send(res, status, JSON.stringify(data, null, 2), {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': cache,
  });
}

/**
 * Кеширование по стандарту:
 *   html, sw.js, манифест — no-store (правки видны сразу, SW не «залипает»);
 *   хешированные файлы сборки (assets/…) — immutable, они меняют имя при правке.
 */
function cacheHeader(urlPath) {
  const file = urlPath.split('?')[0];
  if (file.startsWith('/assets/')) return 'public, max-age=31536000, immutable';
  if (/\.html$/.test(file) || file === '/' || file.endsWith('/sw.js') || file.endsWith('.webmanifest')) {
    return 'no-store';
  }
  return 'public, max-age=60';
}

// ───────────────────────────── обработка запроса ────────────────────────────
function createHandler(distDir) {
  return async function handle(req, res) {
    const url = new URL(req.url, `http://${req.headers.host ?? 'localhost'}`);
    const pathname = decodeURIComponent(url.pathname);

    // 1. Служебные маршруты (личность и готовность — по стандарту обязательны).
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      return sendJson(res, 405, { error: 'Метод не поддерживается' });
    }

    if (pathname === '/api/identity') {
      return sendJson(res, 200, {
        app_id: APP_ID,
        name: APP_NAME,
        version: VERSION,
        pid: process.pid,
        port: server.address()?.port ?? 0,
        host: HOST,
        url: baseUrl(),
        dist: distDir,
        data_dir: DATA_DIR,
        node: NODE_BIN,
        started_at: STARTED_AT.toISOString(),
      });
    }

    if (pathname === '/api/health') {
      return sendJson(res, 200, {
        ok: true,
        app_id: APP_ID,
        version: VERSION,
        port: server.address()?.port ?? 0,
        uptime_ms: Date.now() - STARTED_AT.getTime(),
        dist_ready: fs.existsSync(path.join(distDir, 'index.html')),
      });
    }

    if (pathname.startsWith('/api/')) {
      return sendJson(res, 404, { error: 'Неизвестный маршрут API', path: pathname });
    }

    // 2. Статика из dist/.
    const relative = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
    const target = path.resolve(distDir, relative);
    const inside = target === distDir || target.startsWith(distDir + path.sep);
    let filePath = inside ? target : null;

    if (filePath) {
      try {
        const stat = await fsp.stat(filePath);
        if (stat.isDirectory()) filePath = path.join(filePath, 'index.html');
        await fsp.access(filePath, fs.constants.R_OK);
      } catch {
        filePath = null;
      }
    }

    // 3. SPA-fallback: любой «не файл» отдаём index.html (роутер React разберётся).
    if (!filePath && !path.extname(pathname)) {
      const candidate = path.join(distDir, 'index.html');
      if (fs.existsSync(candidate)) filePath = candidate;
    }

    if (!filePath) {
      if (!fs.existsSync(path.join(distDir, 'index.html'))) {
        return send(
          res,
          503,
          '<meta charset="utf-8"><title>BudgetLIFE</title>' +
            '<div style="font:16px system-ui;padding:40px;max-width:640px">' +
            '<h1>Сборка не найдена</h1><p>Папка <code>dist/</code> пуста. ' +
            'Запустите <code>npm run build</code> (или start.vbs — он соберёт сам) ' +
            'и обновите страницу.</p></div>',
          { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
        );
      }
      return sendJson(res, 404, { error: 'Файл не найден', path: pathname });
    }

    try {
      const body = await fsp.readFile(filePath);
      send(res, 200, body, {
        'Content-Type': MIME[path.extname(filePath).toLowerCase()] ?? 'application/octet-stream',
        'Cache-Control': cacheHeader(pathname),
      });
    } catch (error) {
      log(`Ошибка отдачи ${filePath}: ${error.message}`, 'ERROR');
      sendJson(res, 500, { error: 'Не удалось прочитать файл' });
    }
  };
}

// ───────────────────────────────── запуск ───────────────────────────────────
const args = parseArgs(process.argv.slice(2));

if (args.help) {
  process.stdout.write(
    `${APP_NAME} ${VERSION} — локальный сервер\n\n` +
      '  --port=N     порт (по умолчанию — свой блок из ports.json)\n' +
      '  --host=HOST  адрес (по умолчанию 127.0.0.1)\n' +
      '  --dir=DIR    что раздавать (по умолчанию dist/)\n',
  );
  process.exit(0);
}

const DATA_DIR = path.join(HERE, 'data');
const LOGS_DIR = path.join(HERE, 'logs');
const DIST_DIR = path.resolve(HERE, args.dir ?? process.env.DIST ?? 'dist');
const HOST = args.host ?? process.env.HOST ?? '127.0.0.1';

for (const dir of [DATA_DIR, LOGS_DIR]) fs.mkdirSync(dir, { recursive: true });
logFile = path.join(LOGS_DIR, 'server.log');

const BLOCK = loadBlock();
const WANTED = args.port ?? (process.env.PORT ? Number(process.env.PORT) : null);
const CANDIDATES = candidates(BLOCK, WANTED);

const server = http.createServer(createHandler(DIST_DIR));
server.on('error', (error) => log(`Ошибка сервера: ${error.message}`, 'ERROR'));

let lockServer = null;
let baseUrl = () => `http://${HOST}:${server.address()?.port ?? 0}/`;

function acquireLock() {
  const port = lockPortFor(APP_ID);
  return new Promise((resolve) => {
    const lock = http.createServer();
    lock.once('error', () => resolve(null));
    lock.listen({ port, host: '127.0.0.1', exclusive: true }, () => resolve(lock));
  });
}

function tryListen(port) {
  return new Promise((resolve) => {
    const onError = (error) => {
      server.removeListener('listening', onReady);
      resolve({ ok: false, error });
    };
    const onReady = () => {
      server.removeListener('error', onError);
      resolve({ ok: true });
    };
    server.once('error', onError);
    server.once('listening', onReady);
    server.listen({ port, host: HOST, exclusive: true });
  });
}

function httpJson(url, timeout = 1500) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout }, (res) => {
      let raw = '';
      res.on('data', (chunk) => {
        raw += chunk;
      });
      res.on('end', () => {
        try {
          resolve(JSON.parse(raw));
        } catch {
          resolve(null);
        }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => {
      req.destroy();
      resolve(null);
    });
  });
}

async function main() {
  log(`=== ${APP_NAME} ${VERSION} ===`);
  log(`pid=${process.pid} node=${NODE_BIN}`);
  log(`папка=${HERE} dist=${DIST_DIR}`);
  log(`блок портов=${BLOCK.base}–${BLOCK.base + BLOCK.size - 1} (${APP_ID})`);

  // 1. Порт-лок: защита от гонки «два запуска одновременно».
  lockServer = await acquireLock();
  if (!lockServer) {
    log('Порт-лок занят: другой экземпляр уже запускается. Сверяю личность…', 'WARN');
    for (const port of CANDIDATES) {
      const identity = await httpJson(`http://${HOST}:${port}/api/identity`, 700);
      if (identity?.app_id === APP_ID) {
        log(`Уже запущено на порту ${port} (pid ${identity.pid}) — выходим`);
        process.exit(0);
      }
    }
    log('Лок занят, но своего сервера нет — пробуем продолжить', 'WARN');
  }

  // 2. Слушаем порт из своего блока (без сканирования чужих диапазонов).
  let chosen = null;
  for (const port of CANDIDATES) {
    const result = await tryListen(port);
    if (result.ok) {
      chosen = port;
      break;
    }
    if (result.error?.code === 'EADDRINUSE') {
      const identity = await httpJson(`http://${HOST}:${port}/api/identity`, 700);
      if (identity?.app_id === APP_ID) {
        log(`Уже запущено на порту ${port} (pid ${identity.pid}) — второй экземпляр не нужен`);
        process.exit(0);
      }
      log(`Порт ${port} занят чужим процессом — берём следующий`, 'WARN');
      continue;
    }
    log(`Порт ${port} недоступен: ${result.error?.message}`, 'ERROR');
  }

  if (!chosen) {
    log(`Свободного порта в блоке ${BLOCK.base}–${BLOCK.base + BLOCK.size - 1} нет`, 'ERROR');
    process.exit(1);
  }

  if (chosen !== BLOCK.base && chosen !== WANTED) {
    log(`Основной порт занят — работаем на ${chosen}`, 'WARN');
  }

  // 3. Фиксируем порт для лаунчера, ярлыков и трея.
  writePortFile(DATA_DIR, {
    port: chosen,
    app_id: APP_ID,
    pid: process.pid,
    host: HOST,
    url: `http://${HOST}:${chosen}/`,
  });

  const url = `http://${HOST}:${chosen}/`;
  log(`Готово: ${url}`);
  log(`Личность: ${url}api/identity · Здоровье: ${url}api/health`);
  if (!fs.existsSync(path.join(DIST_DIR, 'index.html'))) {
    log('ВНИМАНИЕ: dist/index.html не найден — выполните npm run build', 'WARN');
  }

  // 4. Корректная остановка: слушатель → лок → port.txt → выход.
  const shutdown = (signal) => {
    log(`Остановка (${signal})`);
    const finish = () => {
      try {
        if (lockServer) lockServer.close();
      } catch {
        /* уже закрыт */
      }
      try {
        const portFile = path.join(DATA_DIR, 'port.txt');
        if (fs.existsSync(portFile)) fs.unlinkSync(portFile);
      } catch {
        /* файл мог быть удалён вручную */
      }
      process.exit(0);
    };
    server.close(() => finish());
    setTimeout(finish, 1500).unref(); // не ждём «зависшие» соединения вечно
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('uncaughtException', (error) => log(`Необработанное исключение: ${error.stack}`, 'ERROR'));
  process.on('unhandledRejection', (reason) => log(`Необработанный промис: ${reason}`, 'ERROR'));
}

main().catch((error) => {
  log(`Не удалось запуститься: ${error.stack ?? error.message}`, 'ERROR');
  process.exit(1);
});
