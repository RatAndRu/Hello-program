"""Локальный сервер ФОРМА 3D: JSON-API + раздача интерфейса."""

from __future__ import annotations

import hashlib
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
from .instruction import instruction_text
from .errors import FormaError
from .geometry import export_3mf, export_glb, export_obj, export_ply, export_stl
from .render import render_views
from .resources import resource_warning
from .run import build as run_build
from .version import APP_NAME, __version__

MAX_UPLOAD = 300 * 1024 * 1024
MAX_BODY = 8 * 1024 * 1024
DEMO_MAX_SCRIPT_CHARS = 1_000_000
DEMO_MAX_COMMANDS = 4000
DEMO_DISABLED_POSTS = {
    "/api/save-file", "/api/upload", "/api/save", "/api/reveal",
    "/api/import", "/api/prompt",
}


def env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "да", "on"}


# Готовые картинки и записи из окна модели: их присылает браузер байтами,
# чтобы файл попал именно в «Загрузки» на этом компьютере.
MEDIA_SUFFIXES = (".gif", ".webm", ".mp4", ".png", ".webp", ".apng", ".jpeg", ".jpg")

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
    from .paths import user_data_dir as _dir
    return _dir()


class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        self.token = os.environ.get("FORMA_TOKEN") or secrets.token_urlsafe(16)
        self.data_dir = user_data_dir()
        self.last_build = None
        self.last_script = ""
        self.last_render: dict | None = None
        self.last_png_cache: dict[str, bytes] = {}
        self.gl_cache: tuple[str, bytes] | None = None
        self.project_name = os.environ.get("FORMA_START_PROJECT") or "проект"
        self.demo = env_flag("FORMA_DEMO")
        self.revision = os.environ.get("FORMA_REVISION") or "local"
        self.started = time.time()
        self.actions: list[dict] = []
        self.notes: list[dict] = []
        self.action_seq = 0
        self._last_build_hash: str | None = None
        self.frame_cache: dict[str, tuple[dict, bytes | None]] = {}
        self.frame_order: list[str] = []
        # превью карточек «Инструментов»: отдельная сборка, состояние не трогает
        self.preview_dir = self.data_dir / "previews"
        self.preview_cache: dict[str, dict] = {}

    def paths_info(self) -> dict:
        """Карта папок рядом с exe — показывается в справке."""
        try:
            from .paths import describe
            return describe()
        except Exception:
            return {"root": str(self.data_dir)}

    # ------------------------------------------------------------------ #
    def log_action(self, kind: str, text: str, ok: bool = True) -> dict:
        """Журнал действий пользователя и приложения — попадает в отчёт и запрос."""
        with self.lock:
            self.action_seq += 1
            item = {"id": self.action_seq, "kind": kind, "text": text,
                    "ok": bool(ok), "time": time.strftime("%H:%M:%S")}
            self.actions.append(item)
            del self.actions[:-120]
            return item

    def add_note(self, note: dict) -> dict:
        """Замечание к выделенной области: координаты + слова пользователя."""
        with self.lock:
            self.action_seq += 1
            item = {
                "id": self.action_seq,
                "time": time.strftime("%H:%M:%S"),
                "kind": str(note.get("kind") or "область").strip() or "область",
                "object": str(note.get("object") or "").strip(),
                "text": str(note.get("text") or "").strip(),
                "tris": int(note.get("tris") or 0),
                "area_mm2": round(float(note.get("area_mm2") or 0.0), 1),
                "center": [round(float(v), 2) for v in (note.get("center") or [0, 0, 0])],
                "size": [round(float(v), 2) for v in (note.get("size") or [0, 0, 0])],
                "bbox": [round(float(v), 2) for v in (note.get("bbox") or [0] * 6)],
                # приписка к пустому пространству: сколько кубов и где именно
                "cells": int(note.get("cells") or 0),
                "cell": round(float(note.get("cell") or 0.0), 2),
                "indices": str(note.get("indices") or "").strip(),
                "volume_cm3": round(float(note.get("volume_cm3") or 0.0), 1),
            }
            self.notes.append(item)
            del self.notes[:-80]
            if item["cells"]:
                self.log_action("приписка к пространству",
                                f"{item['cells']} сектор(ов): {item['text']}")
            else:
                self.log_action("замечание", f"{item['object']}: {item['text']}")
            return item

    def cut_region(self, script: str, name: str, center, radius) -> dict:
        """Вырезает выделенную область: дописывает в сценарий сферу и difference."""
        name = (name or "").strip()
        if not name:
            raise FormaError("Не выбран объект для вырезания.")
        try:
            cx, cy, cz = (float(v) for v in center)
        except Exception as exc:
            raise FormaError("Некорректные координаты выделения.") from exc
        r = max(0.5, min(5000.0, float(radius or 5.0)))
        lines = script.rstrip().split("\n") if script.strip() else []
        used = {line.split("=", 1)[0].strip() for line in lines if "=" in line}
        n = 1
        while f"вырез_{n}" in used:
            n += 1
        tool = f"вырез_{n}"
        lines.append(f"# вырезано выделенное: {name}, центр ({cx:.1f}, {cy:.1f}, {cz:.1f}), радиус {r:.1f} мм")
        lines.append(f"{tool} = sphere radius={r:.2f} at=[{cx:.2f}, {cy:.2f}, {cz:.2f}]")
        lines.append(f"{name} = difference [{name}, {tool}]")
        self.log_action("вырезание", f"«{name}»: сфера r={r:.1f} мм в ({cx:.1f}, {cy:.1f}, {cz:.1f})")
        return {"script": "\n".join(lines), "tool": tool, "radius": r}

    def demo_policy(self, script: str, overrides: dict | None = None,
                    upto: int | None = None) -> None:
        """Жёсткие границы публичного сервера до создания любой геометрии."""
        if not self.demo:
            return
        script = script or ""
        if len(script) > DEMO_MAX_SCRIPT_CHARS:
            raise FormaError("Публичное демо: сценарий больше 1 000 000 символов.")
        from .dsl import parse_script
        commands = parse_script(script)
        if len(commands) > DEMO_MAX_COMMANDS:
            raise FormaError("Публичное демо: не больше 4000 команд в одном сценарии.")
        for command in commands:
            if command.verb.strip().lower() in {"import", "импорт", "open", "открыть"}:
                raise FormaError("Публичное демо: импорт внешних файлов отключён. "
                                 "Используйте готовые проекты и команды Forma.")
        warning = resource_warning(script, overrides=overrides, upto=upto)
        if warning is not None:
            estimate = int(warning.get("estimated_tris") or 0)
            limit = int(warning.get("limit") or 500000)
            raise FormaError(f"Публичное демо: оценка {estimate:,} трис превышает "
                             f"общий лимит {limit:,}. Уменьшите сцену.".replace(",", " "))

    def build(self, script: str, auto: bool = False, allow_heavy: bool = False) -> dict:
        self.demo_policy(script)
        # Предупреждение делается ДО run_build: ни одна тяжёлая команда ещё
        # не создала сетку и не заняла процессор. Старая сцена остаётся на
        # экране, поэтому «отменить» действительно отменяет последнее действие.
        if not allow_heavy:
            warning = resource_warning(script)
            if warning is not None:
                warning.update({
                    "version": __version__, "server": {"token": self.token},
                    "script_hash": hashlib.sha1((script or "").encode("utf-8")).hexdigest(),
                    "actions": list(self.actions), "notes": list(self.notes),
                    "paused": True,
                })
                return warning
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
            if b.ok:
                a = b.analysis or {}
                checks = a.get("checks") or []
                passed = sum(1 for c in checks if c.get("ok"))
                dims = a.get("metrics", {}).get("size") or []
                dim_txt = (" · ".join(f"{v:.0f}" for v in dims) + " мм") if dims else ""
                failed = len(checks) - passed
                text = f"собрано {dim_txt}".strip()
                if checks:
                    text += f", проверки {passed}/{len(checks)}"
                if failed:
                    text += f", не пройдено {failed}"
                if not auto or self._last_build_hash != b.script_hash and failed:
                    self.log_action("сборка", text, ok=failed == 0)
            else:
                err = b.error or {}
                self.log_action("сборка", f"ошибка: {err.get('message', 'не собрано')}"
                                + (f" (строка {err.get('line')})" if err.get("line") else ""),
                                ok=False)
            self._last_build_hash = b.script_hash
            payload["actions"] = list(self.actions)
            payload["notes"] = list(self.notes)
            return payload

    def frame(self, script: str, upto: int, light: bool = True,
              allow_heavy: bool = False) -> dict:
        """Кадр сборки: сцена после первых ``upto`` команд сценария."""
        upto = max(0, min(int(upto), 4000))
        self.demo_policy(script, upto=upto)
        if not allow_heavy:
            warning = resource_warning(script, upto=upto)
            if warning is not None:
                warning.update(paused=True, action="frame", upto=upto)
                return warning
        import hashlib
        key = f"{hashlib.sha1((script or '').encode('utf-8')).hexdigest()[:12]}_{upto}"
        cached = self.frame_cache.get(key)
        if cached is None:
            with self.lock:
                b = run_build(script, upto=upto, analyze_model=False)
                payload = b.payload(light=light)
                glb = None
                if b.ok and not b.empty:
                    try:
                        glb = b.glb()
                    except Exception:
                        glb = None
                payload["key"] = key
                payload["glb"] = bool(glb)
                cached = (payload, glb)
                self.frame_cache[key] = cached
                self.frame_order.append(key)
                # держим не больше 48 кадров и ~96 МБ: у больших моделей GLB тяжёлый
                while len(self.frame_order) > 48 or (
                        len(self.frame_order) > 2
                        and sum(len(v[1] or b"") for v in self.frame_cache.values()) > 96 * 1024 * 1024):
                    old = self.frame_order.pop(0)
                    self.frame_cache.pop(old, None)
        return cached[0]

    def frame_glb(self, key: str) -> bytes | None:
        item = self.frame_cache.get(key)
        return item[1] if item else None

    def morph(self, script: str, param: str, value: float,
              allow_heavy: bool = False) -> dict:
        """Кадр морфинга: та же модель, но параметр сценария подменён.

        Так анимация меняет геометрию во времени: кадры строятся по запросу и
        кешируются рядом с кадрами сборки.
        """
        import hashlib
        param = str(param or "").strip()
        if not param:
            raise FormaError("Морфинг: не указан параметр сценария.")
        value = round(float(value), 4)
        self.demo_policy(script, overrides={param: value})
        if not allow_heavy:
            warning = resource_warning(script, overrides={param: value})
            if warning is not None:
                warning.update(paused=True, action="morph", param=param, value=value)
                return warning
        key = f"morph_{hashlib.sha1((script or '').encode('utf-8')).hexdigest()[:12]}_{param}_{value:g}"
        cached = self.frame_cache.get(key)
        if cached is None:
            with self.lock:
                b = run_build(script, analyze_model=False, overrides={param: value})
                payload = b.payload(light=False)
                glb = None
                if b.ok and not b.empty:
                    try:
                        glb = b.glb()
                    except Exception:
                        glb = None
                payload["key"] = key
                payload["glb"] = bool(glb)
                cached = (payload, glb)
                self.frame_cache[key] = cached
                self.frame_order.append(key)
                while len(self.frame_order) > 48 or (
                        len(self.frame_order) > 2
                        and sum(len(v[1] or b"") for v in self.frame_cache.values()) > 96 * 1024 * 1024):
                    old = self.frame_order.pop(0)
                    self.frame_cache.pop(old, None)
        return cached[0]

    def glb(self) -> bytes:
        with self.lock:
            if not self.last_build or not self.last_build.ok:
                raise FormaError("Сначала постройте модель.")
            if self.gl_cache is None or self.gl_cache[0] != self.last_build.script_hash:
                self.gl_cache = (self.last_build.script_hash, self.last_build.glb())
            return self.gl_cache[1]

    def preview(self, script: str, allow_heavy: bool = False) -> dict:
        """Строит модель для превью карточки инструмента, не меняя сцену.

        Кэш по хэшу сценария: одно и то же превью второй раз открывается
        мгновенно. В ответе — размеры и число треугольников для подписи.
        """
        script = (script or "").strip()
        if not script:
            raise FormaError("Пустой сценарий превью.")
        self.demo_policy(script)
        if not allow_heavy:
            warning = resource_warning(script)
            if warning is not None:
                warning["paused"] = True
                return warning
        key = hashlib.sha1(script.encode("utf-8")).hexdigest()[:16]
        cached = self.preview_cache.get(key)
        if cached and (self.preview_dir / f"{key}.glb").exists():
            return dict(cached, ok=True, cached=True)
        b = run_build(script, previous_analysis=None)
        if not b.ok:
            err = b.error or {}
            return {"ok": False, "error": err,
                    "message": err.get("message") or "Не удалось построить деталь."}
        solids = b.visible_solids()
        if not solids:
            return {"ok": False, "message": "В сценарии нет видимых деталей."}
        data = export_glb(solids)
        self.preview_dir.mkdir(parents=True, exist_ok=True)
        target = self.preview_dir / f"{key}.glb"
        target.write_bytes(data)
        meta = b.analysis or {}
        size = (meta.get("metrics") or {}).get("size") or []
        info = {
            "ok": True, "key": key, "url": f"/api/preview.glb?key={key}",
            "size": size,
            "tris": int((meta.get("metrics") or {}).get("tris") or 0),
            "objects": len(solids),
        }
        self.preview_cache[key] = info
        # держим кэш небольшим: превью — вспомогательные файлы
        if len(self.preview_cache) > 48:
            for old in list(self.preview_cache)[:-32]:
                self.preview_cache.pop(old, None)
                (self.preview_dir / f"{old}.glb").unlink(missing_ok=True)
        return info

    def preview_glb(self, key: str) -> bytes | None:
        if not key or not all(c in "0123456789abcdef" for c in key):
            return None
        path = self.preview_dir / f"{key}.glb"
        if not path.exists():
            return None
        return path.read_bytes()

    def _anime_style(self) -> dict | None:
        """Стиль аниме/манга из сценария (команда anime) — для снимков."""
        try:
            scene = self.last_build.scene if self.last_build else None
            style = (scene.settings or {}).get("anime") if scene else None
            return dict(style) if style else None
        except Exception:
            return None

    def render(self) -> dict:
        with self.lock:
            if not self.last_build or not self.last_build.ok:
                raise FormaError("Сначала постройте модель.")
            out = self.data_dir / "renders"
            stamp = time.strftime("%H%M%S")
            style = self._anime_style()
            result = render_views(self.last_build.visible_solids(), out,
                                  prefix=f"view_{stamp}", size=640, ss=2, style=style,
                                  groups=(self.last_build.scene.groups
                                          if self.last_build.scene else None))
            files = []
            for item in result["files"]:
                name = Path(item["path"]).name
                files.append({"label": item["label"], "url": file_url("renders", name),
                              "path": item["path"]})
            combined = None
            if result.get("combined"):
                combined = file_url("renders", Path(result['combined']).name)
            self.last_render = {"files": files, "combined": combined, "at": time.time()}
            self.log_action("снимки", "сделаны PNG-виды: " + ", ".join(f["label"] for f in files))
            return self.last_render

    def _to_downloads(self, path: Path) -> Path:
        """Копирует готовый файл в папку «Загрузки» и возвращает путь оттуда."""
        from .paths import downloads_dir
        try:
            target = downloads_dir() / path.name
            if target.resolve() != path.resolve():
                shutil.copy2(path, target)
            return target
        except OSError:
            return path

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
            scene = self.last_build.scene
            animation = scene.animation if scene else None
            animations = list(scene.animations) if scene else None
            if fmt == "glb":
                data = export_glb(solids, animation=animation, animations=animations,
                                  groups=dict(scene.groups) if scene else None)
                name = f"{base}.glb"
            elif fmt == "stl":
                data = export_stl(solids)
                name = f"{base}.stl"
            elif fmt == "obj":
                data = export_obj(solids)
                name = f"{base}.obj"
            elif fmt in ("ply", "3mf", "blend"):
                if fmt == "ply":
                    data = export_ply(solids)
                    name = f"{base}.ply"
                elif fmt == "3mf":
                    data = export_3mf(solids)
                    name = f"{base}.3mf"
                else:
                    from .blender import glb_to_blend
                    tmp = out_dir / f"_tmp_{base}.glb"
                    tmp.write_bytes(export_glb(solids, animation=animation,
                                               groups=dict(scene.groups) if scene else None,
                                               animations=animations))
                    name = f"{base}.blend"
                    try:
                        glb_to_blend(str(tmp), str(out_dir / name))
                    finally:
                        tmp.unlink(missing_ok=True)
                    return {"path": str(self._to_downloads(out_dir / name)),
                            "url": file_url("exports", name), "name": name}
            elif fmt == "png":
                result = render_views(solids, out_dir, prefix=base, size=900, ss=2,
                                      style=self._anime_style(),
                                      groups=(scene.groups if scene else None))
                name = Path(result.get("combined") or result["files"][0]["path"]).name
                data = Path(out_dir / name).read_bytes()
            elif fmt in ("dxf", "svg"):
                from . import cuts
                sections = [s for s in (getattr(scene, "sections", []) or [])
                            if s.get("contours")]
                if not sections:
                    raise FormaError("Нет сечений — добавьте в сценарий строку section z=40.")
                name = f"{base}_sections.{fmt}"
                target = out_dir / name
                if fmt == "dxf":
                    cuts.export_dxf(sections, target)
                else:
                    cuts.export_svg(sections, target)
                return {"path": str(self._to_downloads(target)),
                        "url": file_url("exports", name), "name": name}
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
                    zf.writestr(f"{base}.glb", export_glb(
                        solids, animation=animation,
                        groups=dict(scene.groups) if scene else None))
                    zf.writestr(f"{base}.stl", export_stl(solids))
                    zf.writestr(f"{base}.obj", export_obj(solids))
                    zf.writestr(f"{base}.ply", export_ply(solids))
                    zf.writestr("OTCHET.txt", (self.last_build.analysis or {}).get("text", ""))
                    zf.writestr("SPRAVKA.md", command_reference_md())
                    tmp = out_dir / "_views"
                    render_views(solids, tmp, prefix=base, size=800, ss=2,
                                 style=self._anime_style(),
                                 groups=(scene.groups if scene else None))
                    for png in sorted(tmp.glob("*.png")):
                        zf.write(png, f"views/{png.name}")
                    shutil.rmtree(tmp, ignore_errors=True)
                return {"path": str(self._to_downloads(target)),
                        "url": file_url("exports", name), "name": name}
            else:
                raise FormaError(f"Неизвестный формат «{fmt}».")
            target = out_dir / name
            target.write_bytes(data)
            return {"path": str(self._to_downloads(target)),
                    "url": file_url("exports", name), "name": name}

    def blender_info(self) -> dict:
        from .blender import available
        return available()

    def import_script(self, name: str, script: str) -> dict:
        """Готовит строку импорта для сценария (файл уже сохранён в imports)."""
        safe = slugify(name)
        line = f"{safe} = import file={Path(name).name} repair=да"
        return {"script": script, "name": safe, "line": line, "file": str(self.data_dir / "imports" / Path(name).name)}

    def save_upload(self, data: bytes, filename: str) -> dict:
        from .paths import safe_name
        clean = safe_name(filename or "модель.glb", "модель.glb")
        if not Path(clean).suffix:
            clean += ".glb"
        target = self.data_dir / "imports" / clean
        target.write_bytes(data)
        stem = slugify(Path(clean).stem)
        ext = Path(clean).suffix.lower()
        line = f"{stem} = import file={clean} unit=auto repair=да"
        note = ""
        if ext == ".blend":
            info = self.blender_info()
            note = ("" if info["found"] else
                    "Blender не найден на этом компьютере: .blend откроется только после установки Blender.")
        return {"file": clean, "path": str(target), "size": len(data),
                "line": line, "suffix": ext, "note": note}

    def save_media(self, data: bytes, filename: str) -> dict:
        """Кладёт присланный из окна файл (GIF, видео, снимок) в «Загрузки».

        Браузерная ссылка ``<a download>`` не даёт приложению знать, куда
        попал файл, и в некоторых сборках он молча терялся. Теперь интерфейс
        присылает байты сюда, а сервер пишет копию в папку данных и
        переносит её в «Загрузки» — тем же путём, что и остальной экспорт.
        """
        from .paths import safe_name
        raw = Path(str(filename or "")).name
        clean = safe_name(raw, "анимация.gif")
        suffix = Path(clean).suffix.lower()
        if suffix not in MEDIA_SUFFIXES:
            raise FormaError(f"Такой файл не сохраняем: «{suffix or 'без расширения'}». "
                             "Нужен GIF, WebM, MP4 или PNG.")
        if not data:
            raise FormaError("Пустой файл.")
        out_dir = self.data_dir / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / clean
        target.write_bytes(data)
        shown = self._to_downloads(target)
        self.log_action("экспорт", f"{clean} — {len(data) / 1024:.0f} КБ → {shown.parent}")
        return {"name": clean, "size": len(data), "path": str(shown),
                "app_path": str(target), "downloads": str(shown.parent),
                "url": file_url("exports", clean)}

    def reveal_path(self, path: str) -> dict:
        """Открывает папку с готовым файлом в проводнике (только на этом ПК)."""
        from .paths import data_root, downloads_dir
        target = Path(path or "").expanduser()
        try:
            target = target.resolve()
        except OSError:
            raise FormaError("Такой папки нет.")
        roots = []
        for root in (data_root(), downloads_dir()):
            try:
                roots.append(Path(root).resolve())
            except OSError:
                continue
        inside = any(root == target or root in target.parents for root in roots)
        if not inside:
            raise FormaError("Папка вне данных приложения.")
        folder = target if target.is_dir() else target.parent
        if not folder.exists():
            raise FormaError("Папки ещё нет — сначала сохраните файл.")
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{folder}"')
        else:
            os.system(f'xdg-open "{folder}" >/dev/null 2>&1 &')
        return {"folder": str(folder), "opened": True}

    def save_project(self, name: str, script: str) -> dict:
        display = "".join(c for c in (name or "проект") if c not in '\\/:*?"<>|').strip() or "проект"
        safe = slugify(display)
        path = self.data_dir / "projects" / f"{safe}.forma"
        path.write_text(script, encoding="utf-8")
        meta = {"script": script, "saved": time.strftime("%Y-%m-%d %H:%M"), "name": display}
        (self.data_dir / "projects" / f"{safe}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        shown = self._to_downloads(path)
        self.project_name = display
        return {"name": display, "key": safe, "path": str(shown), "app_path": str(path)}

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
    ("Выставка 1/4: поры и деформация", "tools_gallery_1"),
    ("Выставка 2/4: трещины и срезы", "tools_gallery_2"),
    ("Выставка 3/4: лист и гармошка", "tools_gallery_3"),
    ("Выставка 4/4: вафля, волосы и рельеф", "tools_gallery_4"),
    ("Кружка", "mug"),
    ("Кузов машины", "car"),
    ("Ваза", "vase"),
    ("Бутылка", "bottle"),
    ("Пришелец из капли", "alien"),
    ("Шестерня", "gear"),
    ("Манекен в T-позе", "mannequin"),
    ("Яблоко", "apple"),
    ("Анатомическая фигура", "human_studio"),
    ("Скелет взрослого человека: 206 костей", "human_skeleton"),
    ("Оригинальный скелет Forma: 206 костей без импорта", "human_skeleton_original"),
    ("Анимация по дорожкам и ключи", "animation_tracks"),
    ("Шкаф: дверь, ящик, колёсики", "wardrobe"),
    ("Ноутбук ThinkPad X1 Carbon Gen 11", "thinkpad_x1"),
    ("Мебельная фурнитура: монтажный стенд", "furniture_hardware"),
    ("Дверь и окна 0.55: все детали выбираются", "architecture_selectable_055"),
    ("Ручки и розетки 0.55: формы и замки", "handle_rosettes_055"),
    ("Выбор деталей 0.55: путь и петля", "selection_details_055"),
    ("Сопряжения 0.54: ручка, fireball и навершенник", "smooth_transitions_054"),
    ("Примитивы 0.53: путь и фурнитура", "fittings_053"),
    ("Примитивы 0.53: значки и половины", "glyphs_expansion_053"),
    ("Механика: вентилятор, прыжок, падение", "mechanics"),
    ("Витрина инструментов: 49 предметов", "showcase"),
    ("Мотоцикл: рама, вилка, езда и прыжок", "motorcycle"),
    ("Скелетон-часы: механизм и ход 10:10:35", "clock"),
    ("Часы с LED-экраном", "clock_led"),
    ("Аниме-бюст: голова, шея, плечи, волосы", "anime_face"),
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
        if token and secrets.compare_digest(token, self.state.token):
            return True
        # запасной вход: cookie, которую сервер ставит вместе с index.html.
        # Так открываются снимки и текстуры, если адрес потерял ?token=...
        cookie = self._cookie_token()
        return bool(cookie) and secrets.compare_digest(cookie, self.state.token)

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

    def _send_file(self, path: Path, ctype: str | None = None, download: bool = False,
                   headers: dict | None = None):
        if not path.exists() or not path.is_file():
            self._send_json({"error": {"message": "Файл не найден"}}, 404)
            return
        data = path.read_bytes()
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        if download:
            self.send_header("Content-Disposition",
                             f'attachment; filename="{urllib.parse.quote(path.name)}"')
        self.end_headers()
        self.wfile.write(data)

    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie", "") or ""
        for part in raw.split(";"):
            key, _, value = part.strip().partition("=")
            if key == "forma_token":
                return urllib.parse.unquote(value)
        return ""

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
            if path == "/healthz":
                self._send_json({
                    "ok": True, "app": APP_NAME, "version": __version__,
                    "revision": self.state.revision, "demo": self.state.demo,
                    "uptime_seconds": round(time.time() - self.state.started, 3),
                })
                return
            if path.startswith("/api/"):
                if not self._token_ok(query):
                    self._send_json({"error": {"message": "Нет доступа (токен)."}}, 403)
                    return
                self._api_get(path, query)
                return
            if path.startswith("/files/"):
                # Снимки, текстуры и экспорт — только чтение из папки данных.
                # Токен здесь не требуем: иначе картинка, открытая из отчёта
                # или из нового окна, показывала «Нет доступа (токен)».
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
            if target.name == "index.html" and target.parent == web_dir:
                # выдаём страницу с «вшитым» токеном и ставим cookie:
                # после перезагрузки или открытия голого адреса интерфейс цел.
                html = target.read_text(encoding="utf-8")
                html = html.replace("__FORMA_TOKEN__", self.state.token)
                data = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Set-Cookie",
                                 f"forma_token={urllib.parse.quote(self.state.token)}; Path=/; SameSite=Lax")
                self.end_headers()
                self.wfile.write(data)
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
            if self.state.demo and path in DEMO_DISABLED_POSTS:
                raise FormaError("Публичное демо: запись и локальные операции на сервере отключены. "
                                 "Экспорт доступен через кнопки скачивания.")
            if path == "/api/save-file":
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0:
                    raise FormaError("Пустой файл.")
                if length > MAX_UPLOAD:
                    raise FormaError("Файл больше 300 МБ — уменьшите длительность записи.")
                data = self.rfile.read(length)
                name = query.get("name", ["анимация.gif"])[0]
                self._send_json(self.state.save_media(data, name))
                return
            if path == "/api/upload":
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0:
                    raise FormaError("Пустой файл.")
                if length > MAX_UPLOAD:
                    raise FormaError("Файл больше 300 МБ — откройте его через импорт в сценарии.")
                data = self.rfile.read(length)
                name = query.get("name", ["модель.glb"])[0]
                self._send_json(self.state.save_upload(data, name))
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
                "revision": st.revision,
                "demo": st.demo,
                "script": script,
                "project": st.project_name,
                "examples": [{"name": n, "key": k} for n, k in EXAMPLES],
                "projects": st.list_projects(),
                "data_dir": str(st.data_dir),
                "paths": st.paths_info(),
                "has_build": bool(st.last_build and st.last_build.ok),
                "actions": list(st.actions),
                "notes": list(st.notes),
                "blender": st.blender_info(),
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
        if path == "/api/preview.glb":
            key = query.get("key", [""])[0]
            data = st.preview_glb(key)
            if data is None:
                self._send_json({"error": {"message": "Превью не найдено — постройте заново."}}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=600")
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/frame.glb":
            key = query.get("key", [""])[0]
            data = st.frame_glb(key)
            if data is None:
                self._send_json({"error": {"message": "Кадр не найден — постройте его заново"}}, 404)
                return
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
        if path == "/api/links":
            b = st.last_build
            if not b or not b.ok:
                self._send_json({"error": {"message": "Сначала постройте модель"}}, 409)
                return
            from .links import scene_links
            self._send_json(scene_links(b.scene))
            return
        if path == "/api/reference":
            self._send_json({"markdown": command_reference_md()})
            return
        if path == "/api/texture":
            from .textures import custom_texture_file, texture_file
            kind = query.get("kind", ["мрамор"])[0]
            try:
                scale = float(query.get("scale", ["1"])[0] or 1)
            except ValueError:
                scale = 1.0
            try:
                relief = float(query.get("relief", ["0"])[0] or 0)
            except ValueError:
                relief = 0.0
            if kind.strip().lower() in ("своя", "своё", "custom", "мой"):
                info = custom_texture_file(
                    pattern=query.get("pattern", ["полосы"])[0],
                    color1=query.get("color1", ["#3a6ea5"])[0],
                    color2=query.get("color2", ["#e8dfcf"])[0],
                    scale=scale, seed=query.get("seed", ["1"])[0],
                    relief=relief)
                if query.get("normal", ["0"])[0] in ("1", "да", "true") and info.get("normal_path"):
                    self._send_file(Path(info["normal_path"]), "image/png")
                    return
            else:
                info = texture_file(kind, scale=scale)
            self._send_file(Path(info["path"]), "image/png")
            return
        if path == "/api/textures":
            from .textures import KIND_NAMES
            self._send_json({"kinds": [{"key": k, "label": v} for k, v in KIND_NAMES.items()]})
            return
        if path == "/api/projects":
            self._send_json({"projects": st.list_projects()})
            return
        if path == "/api/instruction":
            kind = query.get("kind", ["full"])[0]
            try:
                text = instruction_text(kind)
            except Exception as exc:  # pragma: no cover
                self._send_json({"error": {"message": str(exc)}}, 500)
                return
            self._send_json({"kind": kind, "text": text, "chars": len(text)})
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
            self._send_json(st.build(script, auto=bool(body.get("auto")),
                                     allow_heavy=bool(body.get("allow_heavy"))))
            return
        if path == "/api/preview":
            self._send_json(st.preview(str(body.get("script") or ""),
                                       allow_heavy=bool(body.get("allow_heavy"))))
            return
        if path == "/api/morph":
            script = body.get("script", st.last_script)
            self._send_json(st.morph(script, body.get("param", ""),
                                     body.get("value", 0),
                                     allow_heavy=bool(body.get("allow_heavy"))))
            return
        if path == "/api/frame":
            script = body.get("script", st.last_script)
            try:
                upto = int(body.get("upto") or 0)
            except (TypeError, ValueError):
                raise FormaError("Номер кадра должен быть числом.")
            self._send_json(st.frame(script, upto,
                                     allow_heavy=bool(body.get("allow_heavy"))))
            return
        if path == "/api/action":
            self._send_json({"action": st.log_action(body.get("kind", "действие"),
                                                     str(body.get("text") or ""),
                                                     bool(body.get("ok", True)))})
            return
        if path == "/api/note":
            note = st.add_note(body)
            self._send_json({"note": note, "notes": list(st.notes)})
            return
        if path == "/api/notes":
            if body.get("clear"):
                st.notes.clear()
                st.log_action("замечания", "список замечаний очищен")
            self._send_json({"notes": list(st.notes)})
            return
        if path == "/api/edit/cut":
            res = st.cut_region(body.get("script", ""), body.get("object", ""),
                                body.get("center") or [], body.get("radius"))
            self._send_json(res)
            return
        if path == "/api/render":
            self._send_json(st.render())
            return
        if path == "/api/export":
            fmt = body.get("format", "glb")
            self._send_json(st.export(fmt, body.get("script")))
            return
        if path == "/api/reveal":
            self._send_json(st.reveal_path(str(body.get("path") or "")))
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
            text = build_prompt(b if b.ok else b, goal, notes=list(st.notes),
                                actions=list(st.actions),
                                with_reference=bool(body.get("reference", True)),
                                renders=st.last_render)
            out = st.data_dir / "prompts" / f"запрос_{time.strftime('%Y%m%d_%H%M%S')}.md"
            out.write_text(text, encoding="utf-8")
            self._send_json({"text": text, "path": str(out)})
            return
        if path == "/api/import":
            self._send_json(st.import_script(body.get("name", "импорт"),
                                             body.get("script", "")))
            return
        self._send_json({"error": {"message": f"Неизвестный маршрут {path}"}}, 404)


class FormaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(host: str = "127.0.0.1", port: int = 0) -> tuple[FormaHTTPServer, str]:
    try:
        from .paths import migrate_legacy
        migrate_legacy()  # старые APPDATA/User-папки переносим к exe и убираем
    except Exception:
        pass
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
