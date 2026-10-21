"""Локальный сервер ФОРМА 3D: JSON-API + раздача интерфейса."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import shutil
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .agent import build_prompt, command_reference_md
from .errors import FormaError
from .geometry import export_glb, export_obj, export_stl
from .render import render_views
from .run import build as run_build
from .version import APP_NAME, __version__

MAX_BODY = 8 * 1024 * 1024

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", " ": "_",
}


def slugify(name: str) -> str:
    """Имя файла без кириллицы — надёжно открывается на любой системе и в URL."""
    low = (name or "").strip().lower()
    out = "".join(_TRANSLIT.get(ch, ch) for ch in low)
    keep = "".join(c for c in out if c.isalnum() or c in "._-")
    return keep.strip("._-") or "model"


def file_url(kind: str, name: str) -> str:
    return f"/files/{kind}/{urllib.parse.quote(name)}"


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / rel


def user_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        path = base / "Forma3D"
    else:
        path = Path.home() / ".forma3d"
    for sub in ("projects", "exports", "renders", "prompts"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    return path


class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.token = secrets.token_urlsafe(16)
        self.data_dir = user_data_dir()
        self.last_build = None
        self.last_script = ""
        self.last_render: dict | None = None
        self.last_png_cache: dict[str, bytes] = {}
        self.gl_cache: tuple[str, bytes] | None = None
        self.project_name = "проект"
        self.started = time.time()

    # ------------------------------------------------------------------ #
    def build(self, script: str) -> dict:
        with self.lock:
            previous = self.last_build.analysis if self.last_build and self.last_build.ok else None
            b = run_build(script, previous_analysis=previous)
            self.last_build = b
            self.last_script = script
            self.last_render = None
            self.gl_cache = None
            payload = b.payload()
            payload["version"] = __version__
            payload["server"] = {"token": self.token}
            if b.ok:
                payload["glb_url"] = f"/api/model.glb?v={b.script_hash}"
            return payload

    def glb(self) -> bytes:
        with self.lock:
            if not self.last_build or not self.last_build.ok:
                raise FormaError("Сначала постройте модель.")
            if self.gl_cache is None or self.gl_cache[0] != self.last_build.script_hash:
                self.gl_cache = (self.last_build.script_hash, self.last_build.glb())
            return self.gl_cache[1]

    def render(self) -> dict:
        with self.lock:
            if not self.last_build or not self.last_build.ok:
                raise FormaError("Сначала постройте модель.")
            out = self.data_dir / "renders"
            stamp = time.strftime("%H%M%S")
            result = render_views(self.last_build.visible_solids(), out,
                                  prefix=f"view_{stamp}", size=640, ss=2)
            files = []
            for item in result["files"]:
                name = Path(item["path"]).name
                files.append({"label": item["label"], "url": file_url("renders", name),
                              "path": item["path"]})
            combined = None
            if result.get("combined"):
                combined = file_url("renders", Path(result['combined']).name)
            self.last_render = {"files": files, "combined": combined, "at": time.time()}
            return self.last_render

    def export(self, fmt: str, script: str | None = None) -> dict:
        if script is not None and script != self.last_script:
            self.build(script)
        with self.lock:
            if not self.last_build or not self.last_build.ok:
                raise FormaError("Сначала постройте модель.")
            solids = self.last_build.visible_solids()
            out_dir = self.data_dir / "exports"
            base = slugify(self.project_name or "model")
            fmt = fmt.lower()
            if fmt == "glb":
                data = export_glb(solids)
                name = f"{base}.glb"
            elif fmt == "stl":
                data = export_stl(solids)
                name = f"{base}.stl"
            elif fmt == "obj":
                data = export_obj(solids)
                name = f"{base}.obj"
            elif fmt == "png":
                result = render_views(solids, out_dir, prefix=base, size=900, ss=2)
                name = Path(result.get("combined") or result["files"][0]["path"]).name
                data = Path(out_dir / name).read_bytes()
            elif fmt == "forma":
                data = self.last_script.encode("utf-8")
                name = f"{base}.forma"
            elif fmt == "prompt":
                text = build_prompt(self.last_build, "")
                data = text.encode("utf-8")
                name = f"{base}_prompt.md"
            elif fmt == "zip":
                name = f"{base}_forma.zip"
                target = out_dir / name
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(f"{base}.forma", self.last_script)
                    zf.writestr(f"{base}.glb", export_glb(solids))
                    zf.writestr(f"{base}.stl", export_stl(solids))
                    zf.writestr(f"{base}.obj", export_obj(solids))
                    zf.writestr("OTCHET.txt", (self.last_build.analysis or {}).get("text", ""))
                    zf.writestr("SPRAVKA.md", command_reference_md())
                    tmp = out_dir / "_views"
                    render_views(solids, tmp, prefix=base, size=800, ss=2)
                    for png in sorted(tmp.glob("*.png")):
                        zf.write(png, f"views/{png.name}")
                    shutil.rmtree(tmp, ignore_errors=True)
                return {"path": str(target), "url": file_url("exports", name), "name": name}
            else:
                raise FormaError(f"Неизвестный формат «{fmt}».")
            target = out_dir / name
            target.write_bytes(data)
            return {"path": str(target), "url": file_url("exports", name), "name": name}

    def save_project(self, name: str, script: str) -> dict:
        display = "".join(c for c in (name or "проект") if c not in '\\/:*?"<>|').strip() or "проект"
        safe = slugify(display)
        path = self.data_dir / "projects" / f"{safe}.forma"
        path.write_text(script, encoding="utf-8")
        meta = {"script": script, "saved": time.strftime("%Y-%m-%d %H:%M"), "name": display}
        (self.data_dir / "projects" / f"{safe}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self.project_name = display
        return {"name": display, "key": safe, "path": str(path)}

    def list_projects(self) -> list[dict]:
        out = []
        for p in sorted((self.data_dir / "projects").glob("*.forma")):
            stat = p.stat()
            display = p.stem
            meta_path = p.with_suffix(".json")
            if meta_path.exists():
                try:
                    display = json.loads(meta_path.read_text(encoding="utf-8")).get("name", p.stem)
                except Exception:
                    pass
            out.append({"name": display, "key": p.stem, "modified": stat.st_mtime,
                        "size": stat.st_size})
        out.sort(key=lambda x: x["modified"], reverse=True)
        return out

    def open_project(self, key: str) -> dict:
        safe = slugify(key)
        path = self.data_dir / "projects" / f"{safe}.forma"
        if not path.exists() and (self.data_dir / "projects" / f"{key}.forma").exists():
            path = self.data_dir / "projects" / f"{key}.forma"
        if not path.exists():
            raise FormaError(f"Проект «{key}» не найден.")
        script = path.read_text(encoding="utf-8")
        self.project_name = key
        return {"name": key, "script": script}


EXAMPLES = [
    ("Кружка", "mug"),
    ("Кузов машины", "car"),
    ("Ваза", "vase"),
    ("Бутылка", "bottle"),
    ("Кубик с отверстием", "cube_hole"),
    ("Органическая капля", "blob"),
    ("Шестерня", "gear"),
    ("Человек (манекен)", "human"),
]


def load_example(key: str) -> str:
    path = resource_path(f"examples/{key}.forma")
    if not path.exists():
        raise FormaError(f"Пример «{key}» не найден в сборке.")
    return path.read_text(encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = f"Forma3D/{__version__}"
    state: AppState = None  # задаётся при создании сервера

    # ------------------------------------------------------------------ #
    def log_message(self, fmt, *args):  # тише в консоли
        if os.environ.get("FORMA_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _token_ok(self, query: dict) -> bool:
        token = query.get("token", [""])[0]
        return secrets.compare_digest(token, self.state.token)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, exc: Exception, status=400):
        if isinstance(exc, FormaError):
            data = {"error": exc.to_dict()}
        else:
            data = {"error": {"message": str(exc), "internal": True}}
        self._send_json(data, status)

    def _send_file(self, path: Path, ctype: str | None = None, download: bool = False):
        if not path.exists() or not path.is_file():
            self._send_json({"error": {"message": "Файл не найден"}}, 404)
            return
        data = path.read_bytes()
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if download:
            self.send_header("Content-Disposition",
                             f'attachment; filename="{urllib.parse.quote(path.name)}"')
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_BODY:
            raise FormaError("Слишком большой запрос.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise FormaError(f"Некорректный JSON: {exc}") from exc

    # ------------------------------------------------------------------ #
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                if not self._token_ok(query):
                    self._send_json({"error": {"message": "Нет доступа (токен)."}}, 403)
                    return
                self._api_get(path, query)
                return
            if path.startswith("/files/"):
                if not self._token_ok(query):
                    self._send_json({"error": {"message": "Нет доступа (токен)."}}, 403)
                    return
                rel = path[len("/files/"):]
                base = (self.state.data_dir / rel.split("/")[0]).resolve()
                target = (self.state.data_dir / rel).resolve()
                if base not in target.parents and target != base:
                    self._send_json({"error": {"message": "Недопустимый путь"}}, 403)
                    return
                self._send_file(target, download="download" in query)
                return
            # статика интерфейса
            rel = path.lstrip("/") or "index.html"
            web_dir = resource_path("web").resolve()
            target = (web_dir / rel).resolve()
            if web_dir not in target.parents and target != web_dir:
                self.send_error(404)
                return
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                self.send_error(404)
                return
            self._send_file(target)
        except Exception as exc:  # pragma: no cover
            self._send_error_json(exc, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if not self._token_ok(query):
                self._send_json({"error": {"message": "Нет доступа (токен)."}}, 403)
                return
            body = self._read_body()
            self._api_post(path, body)
        except Exception as exc:  # pragma: no cover
            status = 400 if isinstance(exc, FormaError) else 500
            if status == 500:
                traceback.print_exc()
            self._send_error_json(exc, status)

    # ------------------------------------------------------------------ #
    def _api_get(self, path: str, query: dict):
        st = self.state
        if path == "/api/state":
            script = st.last_script
            project_path = st.data_dir / "projects" / f"{st.project_name}.forma"
            if not script and project_path.exists():
                script = project_path.read_text(encoding="utf-8")
            if not script:
                script = load_example("mug")
            self._send_json({
                "app": APP_NAME,
                "version": __version__,
                "script": script,
                "project": st.project_name,
                "examples": [{"name": n, "key": k} for n, k in EXAMPLES],
                "projects": st.list_projects(),
                "data_dir": str(st.data_dir),
                "has_build": bool(st.last_build and st.last_build.ok),
            })
            return
        if path == "/api/model.glb":
            data = st.glb()
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/commands":
            from .run import commands_help
            self._send_json({"commands": commands_help()})
            return
        if path == "/api/reference":
            self._send_json({"markdown": command_reference_md()})
            return
        if path == "/api/projects":
            self._send_json({"projects": st.list_projects()})
            return
        if path == "/api/example":
            key = query.get("key", ["mug"])[0]
            self._send_json({"script": load_example(key)})
            return
        if path == "/api/project":
            name = query.get("name", [""])[0]
            self._send_json(st.open_project(name))
            return
        self._send_json({"error": {"message": f"Неизвестный маршрут {path}"}}, 404)

    def _api_post(self, path: str, body: dict):
        st = self.state
        if path == "/api/build":
            script = body.get("script", "")
            self._send_json(st.build(script))
            return
        if path == "/api/render":
            self._send_json(st.render())
            return
        if path == "/api/export":
            fmt = body.get("format", "glb")
            self._send_json(st.export(fmt, body.get("script")))
            return
        if path == "/api/save":
            self._send_json(st.save_project(body.get("name", "проект"), body.get("script", "")))
            return
        if path == "/api/prompt":
            script = body.get("script", st.last_script)
            goal = body.get("goal", "")
            b = st.last_build
            if b is None or b.script != script:
                b = run_build(script)
            text = build_prompt(b if b.ok else b, goal)
            out = st.data_dir / "prompts" / f"запрос_{time.strftime('%Y%m%d_%H%M%S')}.md"
            out.write_text(text, encoding="utf-8")
            self._send_json({"text": text, "path": str(out)})
            return
        if path == "/api/import":
            script = body.get("script", "")
            self._send_json({"script": script, "name": body.get("name", "импорт")})
            return
        self._send_json({"error": {"message": f"Неизвестный маршрут {path}"}}, 404)


class FormaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(host: str = "127.0.0.1", port: int = 0) -> tuple[FormaHTTPServer, str]:
    state = AppState()
    handler = type("BoundHandler", (Handler,), {"state": state})
    server = FormaHTTPServer((host, port), handler)
    actual_port = server.server_address[1]
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{actual_port}/?token={state.token}"
    server.forma_state = state  # type: ignore[attr-defined]
    server.forma_url = url  # type: ignore[attr-defined]
    return server, url


def serve_in_thread(host: str = "127.0.0.1", port: int = 0, open_browser: bool = False,
                    verbose: bool = True) -> tuple[FormaHTTPServer, str]:
    server, url = make_server(host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if open_browser:
        webbrowser.open(url)
    if verbose:
        print(f"{APP_NAME} {__version__}")
        print(f"Интерфейс: {url}")
        print(f"Папка данных: {server.forma_state.data_dir}")
        print("Для остановки закройте это окно или нажмите Ctrl+C.")
    return server, url
