#!/usr/bin/env python3
"""Статический сервер для курса по топологии.

Отличия от `python3 -m http.server`:
  * раздаёт эту папку из любого рабочего каталога;
  * отдаёт /skachat как файл на скачивание с осмысленным именем.

    python3 forma/topology-course/serve.py            # http://localhost:8000/
    python3 forma/topology-course/serve.py --port 8080
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOWNLOAD_NAME = "topology-course.html"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 — имя задано базовым классом
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if path in ("/skachat", "/download"):
            data = (ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{DOWNLOAD_NAME}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if path in ("/skachat", "/download"):
            size = (ROOT / "index.html").stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{DOWNLOAD_NAME}"')
            self.send_header("Content-Length", str(size))
            self.end_headers()
            return
        super().do_HEAD()

    def log_message(self, fmt: str, *args) -> None:
        print("%s — %s" % (self.address_string(), fmt % args))


def main() -> int:
    ap = argparse.ArgumentParser(description="Сервер курса по топологии")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((args.bind, args.port), Handler) as httpd:
        print(f"Курс: http://localhost:{args.port}/  ·  скачивание: /skachat")
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
