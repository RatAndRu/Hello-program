import http from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const portArg = process.argv.indexOf('--port');
const port = Number(process.env.PORT || (portArg >= 0 ? process.argv[portArg + 1] : 3000));
const mime = {
  '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp',
  '.txt': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8',
  '.webm': 'video/webm', '.zip': 'application/zip', '.woff2': 'font/woff2'
};

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');
    let pathname = decodeURIComponent(url.pathname);
    if (pathname === '/healthz') {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
      res.end(JSON.stringify({ status: 'ok', application: 'origami-studio', revision: process.env.ORIGAMI_REVISION || 'local' }));
      return;
    }
    if (pathname === '/') pathname = '/index.html';
    const filename = path.resolve(root, `.${pathname}`);
    if (!filename.startsWith(`${root}${path.sep}`)) {
      res.writeHead(403).end('Forbidden');
      return;
    }
    const info = await stat(filename);
    if (!info.isFile()) throw new Error('Not a file');
    const body = await readFile(filename);
    res.writeHead(200, {
      'Content-Type': mime[path.extname(filename)] || 'application/octet-stream',
      'Cache-Control': 'no-cache',
      'X-Content-Type-Options': 'nosniff',
      'Access-Control-Allow-Origin': '*'
    });
    res.end(body);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Файл не найден');
  }
});
server.listen(port, '0.0.0.0', () => console.log(`Origami Studio: http://0.0.0.0:${port}`));
