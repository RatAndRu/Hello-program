"""
ПИКСЕЛЬ — локальный сервер, форк forma/forma/webui.py
Сохраняет: TOKEN, user_data_dir(), /api/build, /api/state, /api/export, cookie, demo-режим
Разница: вместо manifold3d — Pillow/numpy, вместо 3D — пиксели
"""
from __future__ import annotations
import os, secrets, time, threading, urllib.parse, json, mimetypes
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_NAME = "Пиксель"
APP_TITLE = "ПИКСЕЛЬ — от пикселя к картине"
VERSION = "0.1.0"

def env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1","true","yes","да","on"}

class AppState:
    def __init__(self):
        self.token = os.environ.get("PIKSEL_TOKEN") or secrets.token_urlsafe(16)
        self.data_dir = Path.cwd() / "piksel-data"
        self.data_dir.mkdir(exist_ok=True)
        (self.data_dir / "projects").mkdir(exist_ok=True)
        (self.data_dir / "exports").mkdir(exist_ok=True)
        self.demo = env_flag("PIKSEL_DEMO")
        self.revision = os.environ.get("PIKSEL_REVISION") or "local"
        self.actions = []
        self.notes = []
        self.seq = 0
        self.last_pixels = None
        self.last_hd = None

    def log(self, kind, text, ok=True):
        self.seq+=1
        item={"id":self.seq,"kind":kind,"text":text,"ok":ok,"time":time.strftime("%H:%M:%S")}
        self.actions.append(item)
        del self.actions[:-120]
        return item

WEB_ROOT = Path(__file__).parent / "web"

class Handler(BaseHTTPRequestHandler):
    state: AppState
    def log_message(self, fmt, *a): pass

    def _token_ok(self, query):
        tok=query.get("token",[""])[0]
        if tok and secrets.compare_digest(tok, self.state.token): return True
        cookie=self.headers.get("Cookie","")
        for part in cookie.split(";"):
            if "piksel_token" in part:
                val=part.split("=",1)[-1].strip().strip('"')
                if secrets.compare_digest(urllib.parse.unquote(val), self.state.token):
                    return True
        return False

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        p=urlparse(self.path)
        q=parse_qs(p.query)
        path=p.path

        if path in ("/","/index.html"):
            html=(WEB_ROOT/"index.html").read_text(encoding="utf-8")
            html=html.replace("__PIKSEL_TOKEN__", self.state.token)
            self._send(200, html.encode(), "text/html; charset=utf-8")
            self.send_header("Set-Cookie", f"piksel_token={urllib.parse.quote(self.state.token)}; Path=/; SameSite=Lax")
            self.end_headers()
            return
        if path.startswith("/css/") or path.startswith("/js/") or path.startswith("/icons/"):
            fp=WEB_ROOT/path.lstrip("/")
            if fp.exists():
                ct=mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
                self._send(200, fp.read_bytes(), ct)
                return
        if path=="/api/state":
            self._json({"ok":True,"version":VERSION,"token":self.state.token,"actions":self.state.actions[-20:]})
            return
        if path=="/api/healthz":
            self._json({"ok":True,"revision":self.state.revision})
            return
        self._send(404,b"not found","text/plain")

    def do_POST(self):
        from urllib.parse import urlparse, parse_qs
        p=urlparse(self.path)
        q=parse_qs(p.query)
        length=int(self.headers.get("Content-Length","0") or 0)
        body=self.rfile.read(length) if length else b""
        # token check for API (кроме healthz)
        if p.path.startswith("/api/") and p.path not in ("/api/healthz",):
            if not self._token_ok(q):
                # для локалки разрешаем без токена на 127.0.0.1
                host=self.headers.get("Host","")
                if "127.0.0.1" not in host and "localhost" not in host:
                    self._json({"ok":False,"error":"bad token"},403)
                    return
        if p.path=="/api/pixel":
            try:
                data=json.loads(body.decode()) if body else {}
                prompt=data.get("prompt","")
                size=int(data.get("size",32))
                # mock: вернуть пиксели
                self.state.log("пиксель", f"промпт: {prompt[:40]}")
                self._json({"ok":True,"size":size,"note":"mock — реальная нейросеть подключится через Replicate/HF"})
            except Exception as e:
                self._json({"ok":False,"error":str(e)},500)
            return
        if p.path=="/api/detail":
            try:
                data=json.loads(body.decode()) if body else {}
                scale=int(data.get("scale",2))
                self.state.log("детализация", f"×{scale}")
                self._json({"ok":True,"scale":scale,"note":"mock — ControlNet Tile подключится здесь"})
            except Exception as e:
                self._json({"ok":False,"error":str(e)},500)
            return
        self._send(404,b"not found","text/plain")

    def _send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def _json(self, obj, code=200):
        data=json.dumps(obj, ensure_ascii=False).encode()
        self._send(code, data, "application/json; charset=utf-8")

def serve(port=17833, host="127.0.0.1"):
    state=AppState()
    Handler.state=state
    srv=ThreadingHTTPServer((host,port), Handler)
    actual= srv.server_address[1]
    url=f"http://{host}:{actual}/?token={state.token}"
    print(f"{APP_TITLE} v{VERSION}")
    print(f"Открой: {url}")
    print(f"Папки: {state.data_dir}")
    try:
        import webbrowser
        webbrowser.open(url)
    except: pass
    srv.serve_forever()

if __name__=="__main__":
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=17833)
    ap.add_argument("--host", default="127.0.0.1")
    a=ap.parse_args()
    serve(a.port, a.host)
