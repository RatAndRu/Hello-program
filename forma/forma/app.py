"""Запуск приложения ФОРМА 3D: окно (pywebview) или браузер."""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser

from .version import APP_NAME, APP_TITLE, __version__
from .webui import serve_in_thread


def say(message: str = "") -> None:
    """Печать, безопасная в оконном режиме без консоли."""
    try:
        if sys.stdout is not None:
            print(message, flush=True)
    except Exception:
        pass


def _start_window(url: str) -> bool:
    try:
        import webview  # type: ignore
    except Exception as exc:
        say(f"Окно недоступно ({exc}). Открываю в браузере.")
        return False
    try:
        try:
            window = webview.create_window(
                APP_TITLE, url,
                width=1520, height=960,
                min_size=(1080, 680),
                background_color="#0c0f14",
                confirm_close=False,
                text_select=True,   # без этого в окне нельзя выделять и копировать текст
            )
        except TypeError:  # старый pywebview без параметра text_select
            window = webview.create_window(
                APP_TITLE, url,
                width=1520, height=960,
                min_size=(1080, 680),
                background_color="#0c0f14",
                confirm_close=False,
            )
        webview.start(debug=False, private_mode=False)
        return True
    except Exception as exc:
        say(f"Не удалось открыть окно ({exc}). Открываю в браузере.")
        return False


def _run_selftest(report_path: str | None) -> int:
    from .selftest import run_selftest

    result = run_selftest()
    lines = []
    for case in result["cases"]:
        mark = "OK  " if case["ok"] else "FAIL"
        if case.get("error"):
            lines.append(f"[{mark}] {case['name']}: {case['error']}")
        else:
            lines.append(f"[{mark}] {case['name']}: {case.get('tris')} трис")
            for chk in case.get("checks", []):
                lines.append(("   ✓ " if chk["ok"] else "   ✗ ") + chk["text"])
    lines.append("")
    lines.append("ИТОГ: " + ("всё в порядке" if result["ok"] else "есть проблемы"))
    text = "\n".join(lines)
    say(text)
    if report_path:
        try:
            from pathlib import Path
            Path(report_path).write_text(text, encoding="utf-8")
        except Exception:
            pass
    return 0 if result["ok"] else 1


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _run_uistest(report_path: str | None) -> int:
    """Проверка, что внутри собранного exe работают интерфейс и API."""
    import json
    import urllib.request
    from pathlib import Path

    lines = []
    ok = True

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and condition
        lines.append(("OK   " if condition else "FAIL ") + name + (f" — {detail}" if detail else ""))

    try:
        server, url = serve_in_thread(port=0, open_browser=False, verbose=False)
    except Exception as exc:
        lines.append(f"FAIL  запуск сервера: {exc}")
        ok = False
        server = None
        url = None
    if server and url:
        token = server.forma_state.token
        base = url.split("/?")[0]

        def get(path: str, raw: bool = False):
            req = urllib.request.Request(f"{base}{path}{'&' if '?' in path else '?'}token={token}")
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
                return data if raw else json.loads(data)

        def post(path: str, body: dict):
            req = urllib.request.Request(
                f"{base}{path}?token={token}", data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read())

        try:
            html = get("/?x=1", raw=True)
            check("страница интерфейса", b"FORMA" in html.upper() or "ФОРМА".encode("utf-8") in html,
                  f"{len(html)} байт")
            check("скрипт интерфейса", len(get("/js/app.js", raw=True)) > 5000)
            check("3D-движок (three.js)", len(get("/vendor/three.module.js", raw=True)) > 500000)
            check("загрузчик GLB", len(get("/vendor/GLTFLoader.js", raw=True)) > 50000)
            state = get("/api/state")
            check("состояние приложения", state.get("app") == "Форма 3D", state.get("version", ""))
            check("примеры моделей", len(state.get("examples", [])) >= 5,
                  f"{len(state.get('examples', []))} шт.")
            payload = post("/api/build", {"script": state["script"]})
            check("построение модели", payload.get("ok") is True,
                  f"{payload.get('analysis', {}).get('metrics', {}).get('tris', 0)} трис")
            check("проверки выполнены",
                  payload.get("analysis", {}).get("checks_total", 0) > 0,
                  f"{payload.get('analysis', {}).get('checks_passed')} из "
                  f"{payload.get('analysis', {}).get('checks_total')}")
            glb = get("/api/model.glb", raw=True)
            check("экспорт GLB", glb[:4] == b"glTF", f"{len(glb)} байт")
            try:
                rendered = post("/api/render", {})
                check("снимки видов (PNG)", len(rendered.get("files", [])) == 4)
            except Exception as exc:
                check("снимки видов (PNG)", False, str(exc))
            # новые возможности 0.2: текстуры, свет, анимация, импорт, форматы
            check("панель вида в интерфейсе", b"studio-panel" in html and b"material-panel" in html)
            # 0.9: редактор анимации, дорожка кадров, папки рядом с exe
            check("редактор анимации в интерфейсе",
                  b'id="anim-editor"' in html and b'id="anim-scrub"' in html
                  and b'id="anim-tracks"' in html and b'id="ae-kind"' in html)
            check("папки данных рядом с exe",
                  str(state.get("paths", {}).get("root", "")) == state.get("data_dir"),
                  str(state.get("data_dir", "")))
            # 0.3: командная строка, выделение области, замечания, журнал, отчёт
            check("командная строка и выделение", b'id="cmd-input"' in html and b'id="sel-card"' in html
                  and b'id="btn-copy-report"' in html)
            try:
                note = post("/api/note", {"object": "к", "text": "проверка замечания",
                                          "tris": 3, "area_mm2": 1.5,
                                          "center": [0, 0, 10], "size": [2, 2, 2],
                                          "bbox": [-1, -1, 9, 1, 1, 11]})
                check("замечание к области", note.get("note", {}).get("text") == "проверка замечания")
                space_note = post("/api/note", {
                    "kind": "пространство", "object": "секторы: 6",
                    "text": "поставить полку", "cells": 6, "cell": 50,
                    "indices": "i 0…1, j 0…0, k 0…1", "center": [50, -50, 25],
                    "size": [100, 100, 50], "volume_cm3": 500})
                cube_note = space_note.get("note") or {}
                check("приписка к кубическому объёму",
                      cube_note.get("cells") == 6
                      and cube_note.get("indices", "").startswith("i 0…1")
                      and cube_note.get("center") == [50.0, -50.0, 25.0],
                      str(cube_note.get("indices")))
                cut = post("/api/edit/cut", {"script": "к = cylinder radius=20 height=60",
                                             "object": "к", "center": [0, 0, 30], "radius": 6})
                check("вырезание выделенного", "difference [к, вырез_1]" in cut.get("script", ""))
                prompt = post("/api/prompt", {"script": state["script"], "goal": "тест",
                                              "reference": False})
                text = prompt.get("text", "")
                check("отчёт для нейросети", "Журнал действий" in text
                      and "Замечания пользователя" in text
                      and "СПРАВКА ФОРМА 3D (кратко)" not in text)
                state2 = get("/api/state")
                check("журнал действий в состоянии", len(state2.get("actions", [])) > 0,
                      f"{len(state2.get('actions', []))} записей")
            except Exception as exc:
                check("отчёт и выделение", False, str(exc))
            try:
                rich_script = (
                    "к = lathe points=[[0,0],[30,0],[30,60],[0,60]] "
                    "segments=96 thickness=3 open=top\n"
                    "к2 = cylinder radius=6 height=80 at=[40,0,40]\n"
                    "color к #ffffff\ntexture к kind=мрамор\n"
                    "scene bg=#10151c env=studio\nlight preset=студия\n"
                    "animate kind=spin seconds=4\ncheck к height 55..65")
                rich = post("/api/build", {"script": rich_script})
                check("текстура и материалы", rich.get("ok") is True and
                      bool(rich.get("objects", [{}])[0].get("tex")), "мрамор")
                check("настройки сцены", rich.get("settings", {}).get("env") == "studio")
                check("команда анимации", (rich.get("animation") or {}).get("kind") == "spin")
                check("тайм-лайн клипов", len(rich.get("timeline", {}).get("clips", [])) == 1
                      and rich.get("timeline", {}).get("clips", [{}])[0].get("kind") == "spin")
                frames = rich.get("frames", [])
                check("кадры сборки", len(frames) >= 2, f"{len(frames)} шт.")
                if frames:
                    fr = post("/api/frame", {"script": rich_script,
                                             "upto": frames[-1]["n"]})
                    frame_glb = get("/api/frame.glb?key=" + fr.get("key", ""), raw=True) \
                        if fr.get("glb") else b""
                    check("кадр сборки — отдельная модель", frame_glb[:4] == b"glTF",
                          f"{len(frame_glb)} байт")
                check("экспорт PLY", post("/api/export", {"format": "ply"})["name"].endswith(".ply"))
                rich_glb = get("/api/model.glb", raw=True)
                check("анимация и текстура в GLB",
                      b'"animations"' in rich_glb and b'"images"' in rich_glb,
                      f"{len(rich_glb)} байт")
                # 0.6: своя текстура, сохранение в «Загрузки», новые проверки
                png = get("/api/texture?kind=custom&pattern=waves&color1=%23c0504d&color2=%23f2e6d9",
                          raw=True)
                check("своя процедурная текстура", png[:8] == b"\x89PNG\r\n\x1a\n",
                      f"{len(png)} байт")
                # 0.10: песочница текстур, рельеф, спайка/отсечение, облегчение
                check("песочница генеративных текстур",
                      b'id="tex-modal"' in html and b'id="tex-big"' in html
                      and b'id="tex-relief"' in html and b'id="tex-apply"' in html)
                check("кнопка «облегчить» в списке объектов",
                      b'id="objects-optimize"' in html)
                from urllib.parse import quote
                relief_png = get("/api/texture?kind=" + quote("своя")
                                 + "&pattern=" + quote("камень")
                                 + "&color1=%238a5a2b&color2=%23d9c9a8&relief=0.6", raw=True)
                check("текстура с рельефом", relief_png[:8] == b"\x89PNG\r\n\x1a\n",
                      f"{len(relief_png)} байт")
                normal_png = get("/api/texture?kind=" + quote("своя")
                                 + "&pattern=" + quote("камень")
                                 + "&relief=0.6&normal=1", raw=True)
                check("карта нормалей к текстуре",
                      normal_png[:8] == b"\x89PNG\r\n\x1a\n", f"{len(normal_png)} байт")
                welded = post("/api/build", {"script": (
                    "ц = cylinder radius=30 height=80 segments=96\n"
                    "т = torus major=34 minor=8 segments=96\n"
                    "т = place [т] at=[34,0,70] align=center\n"
                    "р = trim [т, ц]\nк = weld [ц, р]\n")})
                check("отсечение и спайка",
                      welded.get("ok") is True
                      and any(o.get("name") == "к" for o in welded.get("objects", [])))
                apple = get("/api/example?key=apple")
                check("пример «Яблоко»", "яблоко" in (apple.get("script") or "").lower())
                tracks = get("/api/example?key=animation_tracks")
                built = post("/api/build", {"script": tracks.get("script") or ""})
                plan = built.get("timeline") or {}
                check("пример «Анимация по дорожкам»",
                      built.get("ok") is True and plan.get("track_count", 0) >= 4
                      and plan.get("key_count", 0) >= 2,
                      f"дорожек {plan.get('track_count')}, ключей {plan.get('key_count')}")
                section_script = (
                    "деталь = cube_hole size=[60,60,20] hole=16\n"
                    "section деталь z=10\n"
                    "probe деталь x=0 y=0 z=10\n"
                    "passport деталь\n"
                    "check деталь genus 1")
                sectioned = post("/api/build", {"script": section_script})
                check("сечение, проба и паспорт детали",
                      sectioned.get("ok") is True
                      and len(sectioned.get("sections") or []) >= 1
                      and len(sectioned.get("probes") or []) >= 1
                      and len(sectioned.get("passports") or []) >= 1,
                      f"сечений {len(sectioned.get('sections') or [])}, "
                      f"проб {len(sectioned.get('probes') or [])}")
                check("инструменты: фигуры и приёмы",
                      b'id="tools-modal"' in html and b'id="btn-tools"' in html)
                check("выделение кубических секторов",
                      b'id="space-card"' in html and b'id="btn-space"' in html)
                check("переключатель повтора анимации", b'id="anim-loop"' in html)
                wardrobe = get("/api/example?key=wardrobe")
                cabinet = post("/api/build", {"script": wardrobe.get("script") or ""})
                cabinet_plan = cabinet.get("timeline") or {}
                cabinet_groups = cabinet.get("groups") or {}
                objects_anim = {c.get("object") for c in cabinet_plan.get("clips", [])}
                check("пример «Шкаф»: группы и движение по объектам",
                      cabinet.get("ok") is True
                      and set(cabinet_groups.get("дверь") or []) == {"фасад_л", "ручка_левая"}
                      and {"дверь", "ящик_сборка", "колесо_1"} <= objects_anim
                      and any(c.get("kind") == "roll" for c in cabinet_plan.get("clips", [])),
                      f"групп {len(cabinet_groups)}, объектов в анимации {len(objects_anim)}")
                post("/api/build", {"script": section_script})
                dxf = post("/api/export", {"format": "dxf"})
                check("экспорт сечения в DXF", str(dxf.get("name", "")).endswith(".dxf"),
                      str(dxf.get("name") or dxf.get("error")))
                morph_script = ("R = 30\nк = cylinder radius=R height=40 segments=32\n"
                                "animate kind=morph param=R from=20 to=40 seconds=2")
                post("/api/build", {"script": morph_script})
                morphed = post("/api/morph", {"script": morph_script,
                                              "param": "R", "value": 20})
                check("морфинг строит кадр с другим параметром",
                      morphed.get("ok") is True and morphed.get("glb") is True,
                      str(morphed.get("key") or morphed.get("error")))
                exported = post("/api/export", {"format": "glb"})
                downloads = str(Path.home() / "Downloads")
                check("экспорт в «Загрузки»",
                      downloads.lower() in exported.get("path", "").lower()
                      or "exports" in exported.get("path", ""),
                      exported.get("path", ""))
                extra = post("/api/build", {"script": (
                    "к = box size=[40,40,40]\n"
                    "к = bevel [к] radius=3\n"
                    "check к sharp_edge 90\ncheck к tri_quality 2\n"
                    "check к wall_min 1..5\ncheck к size 39..41")})
                check("новые проверки sharp_edge/tri_quality/wall_min",
                      extra.get("ok") is True and
                      len(extra.get("analysis", {}).get("checks", [])) == 4)
            except Exception as exc:
                check("новые возможности", False, str(exc))
        except Exception as exc:
            check("ответ API", False, str(exc))
        finally:
            server.shutdown()
    text = "\n".join(lines) + "\n\nИТОГ: " + ("всё в порядке" if ok else "есть проблемы")
    say(text)
    if report_path:
        try:
            from pathlib import Path
            Path(report_path).write_text(text, encoding="utf-8")
        except Exception:
            pass
    return 0 if ok else 1


def main(argv=None) -> int:
    _utf8_stdout()
    parser = argparse.ArgumentParser(description=f"{APP_NAME} {__version__}")
    parser.add_argument("--port", type=int, default=0, help="порт (0 — свободный)")
    parser.add_argument("--host", default="127.0.0.1", help="адрес прослушивания")
    parser.add_argument("--browser", action="store_true", help="открыть в браузере")
    parser.add_argument("--no-open", action="store_true", help="не открывать окно/браузер")
    parser.add_argument("--selftest", action="store_true", help="проверить геометрическое ядро")
    parser.add_argument("--uistest", action="store_true", help="проверить интерфейс и API")
    parser.add_argument("--report", default=None, help="куда записать отчёт самопроверки")
    parser.add_argument("--version", action="store_true", help="показать версию")
    args, _unknown = parser.parse_known_args(argv)

    if args.version:
        say(f"{APP_NAME} {__version__}")
        return 0
    if args.selftest:
        return _run_selftest(args.report)
    if args.uistest:
        return _run_uistest(args.report)

    server, url = serve_in_thread(host=args.host, port=args.port, open_browser=False, verbose=False)
    say(f"{APP_NAME} {__version__}")
    say(f"Адрес интерфейса: {url}")
    say(f"Папка данных: {server.forma_state.data_dir}")

    if args.no_open:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            say("\nОстановлено.")
        return 0

    if args.browser:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            say("\nОстановлено.")
        return 0

    # по умолчанию — собственное окно; если не получилось, открываем браузер
    if _start_window(url):
        return 0
    webbrowser.open(url)
    say("Приложение работает в браузере. Закройте это окно для остановки.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        say("\nОстановлено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
