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
    import urllib.parse
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

        def post_bytes(name: str, data: bytes):
            """Приём готового файла (GIF, видео, снимок) — как это делает окно."""
            query = urllib.parse.quote(name)
            req = urllib.request.Request(
                f"{base}/api/save-file?name={query}&token={token}", data=data,
                headers={"Content-Type": "application/octet-stream"}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
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
                check("бюджет кубов записывается в сценарий", b'id="space-budget"' in html)
                budget = post("/api/build", {"script": (
                    "сетка cell=20 origin=[-60, -60, 0] size=[6, 4, 3]\n"
                    "корпус = box size=[300, 300, 40] at=[0, 0, -10]\n"
                    "вписать корпус\n"
                    "check корпус в_сетке\n"
                    "check корпус положение -60 -60 0 допуск=0.6")})
                budget_checks = (budget.get("analysis") or {}).get("checks") or []
                check("кубическая сетка ограничивает объём",
                      budget.get("ok") is True
                      and bool((budget.get("grid") or {}).get("cells"))
                      and budget_checks
                      and all(c.get("ok") for c in budget_checks),
                      f"кубов {len((budget.get('grid') or {}).get('cells') or [])}, "
                      f"проверок {len(budget_checks)}")
                check("переключатель повтора анимации", b'id="anim-loop"' in html)
                wardrobe = get("/api/example?key=wardrobe")
                cabinet = post("/api/build", {"script": wardrobe.get("script") or ""})
                cabinet_plan = cabinet.get("timeline") or {}
                cabinet_groups = cabinet.get("groups") or {}
                objects_anim = {c.get("object") for c in cabinet_plan.get("clips", [])}
                check("пример «Шкаф»: группы и движение по объектам",
                      cabinet.get("ok") is True
                      and {"фасад_л", "ручка_левая", "петля_1", "петля_2"}
                      <= set(cabinet_groups.get("дверь") or [])
                      and "ручка_ящика" in (cabinet_groups.get("ящик_сборка") or [])
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
                # 0.17: интерфейс для новых замечаний — статистика детали,
                # заслонки, вращение вокруг выделенного, подсветка строки
                check("кнопки «вокруг выделенного» и «заслонки»",
                      b'id="btn-orbit-sel"' in html and b'id="btn-occl"' in html
                      and b'id="btn-focus-sel"' in html)
                check("подсветка строки сценария", b'id="code-run"' in html
                      and b'id="code-run-soft"' in html and b"placeRunHighlight" in
                      get("/js/app.js", raw=True))
                clock = get("/api/example?key=clock")
                clock_build = post("/api/build", {"script": clock.get("script", "")})
                clock_plan = clock_build.get("timeline") or {}
                with_line = [c for c in clock_plan.get("clips", []) if c.get("line")]
                check("у каждого движения есть строка сценария",
                      clock_build.get("ok") is True and len(with_line) == len(clock_plan.get("clips", []))
                      and len(with_line) > 10, f"{len(with_line)} клипов")
                clock_frames = clock_build.get("frames") or []
                service = {"check", "color", "probe", "passport", "light", "scene"}
                check("в шагах сборки нет проверок и цвета",
                      bool(clock_frames) and not any(
                          (f.get("verb") or "") in service for f in clock_frames),
                      f"{len(clock_frames)} кадров из {len(clock_build.get('steps') or [])} команд")
                parts = [o for o in (clock_build.get("objects") or []) if "parts" in o]
                check("у детали есть число частей и площадь",
                      len(parts) == len(clock_build.get("objects") or [])
                      and all(o.get("area_mm2", 0) > 0 for o in parts),
                      f"{len(parts)} деталей")
                # 0.26: аниме/манга-стиль — команда, снимок и панель в окне
                anime_build = post("/api/build", {"script": (
                    "ш = sphere radius=30\nку = box size=[48,48,48] at=[58,0,0]\n"
                    "anime mode=манга line=2 tone=0.8")})
                style = (anime_build.get("settings") or {}).get("anime") or {}
                check("команда anime в сценарии",
                      anime_build.get("ok") is True and style.get("mode") == "манга"
                      and float(style.get("line") or 0) > 0,
                      str(style.get("mode")))
                anime_render = post("/api/render", {})
                first = (anime_render.get("files") or [{}])[0].get("url")
                if first:
                    import tempfile
                    from .geometry import read_png_gray
                    png = get(first, raw=True)
                    with tempfile.TemporaryDirectory() as tmp:
                        shot = Path(tmp) / "shot.png"
                        shot.write_bytes(png)
                        gray = read_png_gray(shot)
                    ink = float((gray < 0.2).mean())
                    paper = float(gray.mean())
                    check("снимок в аниме-стиле", 0.0005 < ink < 0.35 and paper > 0.6,
                          f"контура {ink * 100:.1f}%, фон {paper:.2f}")
                else:
                    check("снимок в аниме-стиле", False, "нет файла")
                check("панель стиля в интерфейсе",
                      b'id="anime-chips"' in html and b'id="anime-line"' in html
                      and b'id="anime-insert"' in html and b'id="anime-paper"' in html)
                # 0.27: превью в карточках инструментов, отражения, свечение,
                # честные ползунки и отдельная очистка сценария/сцены
                preview = post("/api/preview", {"script": (
                    "ш = sphere radius=24\n"
                    "к = box size=[30,30,30] at=[40,0,0] color=#e05a3a")})
                check("превью модели из карточки инструмента",
                      preview.get("ok") is True and preview.get("tris", 0) > 0,
                      f"{preview.get('tris', 0)} трис, {preview.get('size')}")
                preview_glb = get("/api/preview.glb?key=" + str(preview.get("key", "")), raw=True) \
                    if preview.get("key") else b""
                check("файл превью — GLB", preview_glb[:4] == b"glTF",
                      f"{len(preview_glb)} байт")
                check("окно превью в интерфейсе",
                      b'id="preview-modal"' in html and b'id="preview-canvas"' in html
                      and len(get("/js/preview3d.js", raw=True)) > 3000)
                check("очистка сценария и сцены — отдельные кнопки",
                      b'id="btn-clear-script"' in html and b'id="btn-clear-scene"' in html)
                scene_build = post("/api/build", {"script": (
                    "к = box size=[20,20,20]\n"
                    "scene bg=#101010 axes=нет poly=да bloom=1.2 exposure=1.3")})
                sc = scene_build.get("settings") or {}
                check("настройки вида в сценарии",
                      sc.get("axes") is False and sc.get("poly") is True
                      and abs(float(sc.get("bloom") or 0) - 1.2) < 1e-6
                      and abs(float(sc.get("exposure") or 0) - 1.3) < 1e-6,
                      f"axes={sc.get('axes')} poly={sc.get('poly')} bloom={sc.get('bloom')}")
                check("ползунок свечения в панели вида", b'id="bloom"' in html)
                mirror_build = post("/api/build", {"script": (
                    "з = mirror_plate width=300 height=220 frame=20 at=[0,120,0]\n"
                    "з = rotate [з] angle=90 axis=x pivot=[0,120,110]\n"
                    "ш = sphere radius=40 at=[-30,40,40] color=#e03020")})
                check("зеркало с отражением соседей: сборка",
                      mirror_build.get("ok") is True,
                      f"{mirror_build.get('analysis', {}).get('metrics', {}).get('tris', 0)} трис")
                # 0.28: живые превью прямо в карточках, четыре новые формы
                # и развитие аниме-подачи (штриховка, бумага, линии по группам)
                check("живые превью в карточках",
                      b'id="tools-thumbs"' in html
                      and len(get("/js/toolpreview.js", raw=True)) > 3000)
                ui_js = get("/js/app.js", raw=True)
                ui_css = get("/css/app.css", raw=True)
                check("стрелки шага у параметров инструментов",
                      b"tool-step" in ui_js and b"choices: [" in ui_js
                      and b".tool-step" in ui_css
                      and b"stepToolValue" in ui_js,
                      f"{ui_js.count(b'choices: [')} параметров с вариантами")
                check("панель стиля 0.28: штриховка и линии",
                      b'id="anime-row3"' in html and b'id="anime-hatch"' in html
                      and b'id="anime-paper-tex"' in html and b'id="anime-lines"' in html
                      and 'data-anime="скетч"'.encode("utf-8") in html)
                shapes = {
                    "корона": "к = crown diameter=120 height=40 teeth=10",
                    "инь-ян": "и = yin_yang diameter=100 thick=12",
                    "линза": "л = lens diameter=60 sag=10",
                    "патрон": "п = cartridge diameter=9 length=29",
                }
                for label, script in shapes.items():
                    try:
                        res = post("/api/preview", {"script": script})
                        check(f"превью формы «{label}»", res.get("ok") is True,
                              f"{res.get('tris', 0)} трис, {res.get('size', [])}")
                    except Exception as exc:
                        check(f"превью формы «{label}»", False, str(exc))
                sketch = post("/api/build", {"script": (
                    "ш = sphere radius=30 color=#dfe6f3\n"
                    "куб = box size=[36,36,36] at=[44,0,0] color=#f0c674\n"
                    "anime mode=скетч hatch=0.9 hatch_angle=50 paper_tex=0.6 lines=группы")})
                st = (sketch.get("settings") or {}).get("anime") or {}
                check("скетч с штриховкой в сценарии",
                      sketch.get("ok") is True and abs(float(st.get("hatch") or 0) - 0.9) < 1e-6
                      and abs(float(st.get("paper_tex") or 0) - 0.6) < 1e-6
                      and st.get("lines") == "группы",
                      f"hatch={st.get('hatch')} paper_tex={st.get('paper_tex')} "
                      f"lines={st.get('lines')}")
                # 0.29: дисковая пила, объяснение «нет модели», ревизия окон
                saw = post("/api/preview", {"script": (
                    "п = saw diameter=160 thickness=2.4 teeth=24 shape=трапеция "
                    "windows=5 kerf=3.2")})
                check("превью формы «дисковая пила»",
                      saw.get("ok") is True and saw.get("tris", 0) > 0,
                      f"{saw.get('tris', 0)} трис, {saw.get('size')}")
                bad = post("/api/preview", {"script": "п = saw diameter=200 teeth=900"})
                bad_err = (bad.get("error") or {})
                check("превью объясняет, почему нет модели",
                      bad.get("ok") is False and bad_err.get("param") == "teeth"
                      and bad_err.get("bounds") == "4…200"
                      and "4…200" in (bad_err.get("message") or ""),
                      f"param={bad_err.get('param')} рамки={bad_err.get('bounds')}")
                js_app = get("/js/app.js", raw=True)
                check("карточка пилы и подсветка плохого поля",
                      b"op: 'saw'" in js_app and b"markToolFieldError" in js_app)
                js_zoom = get("/js/viewzoom.js", raw=True)
                js_mirror = get("/js/planarmirror.js", raw=True)
                js_bloom = get("/js/selectivebloom.js", raw=True)
                check("модули окна: колесо, план-зеркало, свечение",
                      b"wheelZoom" in js_zoom and b"platePlane" in js_mirror
                      and b"EmissiveBloomPass" in js_bloom,
                      f"{len(js_zoom)}/{len(js_mirror)}/{len(js_bloom)} байт")
                check("шапки окон без тесноты",
                      b'class="tool-seg"' in html and b'id="show-chips"' in html
                      and b'id="btn-grid"' not in html)
                # 0.30: лист как тело, рулон, волнистость, оригами-сгиб, гофра
                flat = post("/api/preview", {"script": (
                    "л = sheet width=120 length=200 thickness=1.2")})
                check("превью формы «плоскость-лист»",
                      flat.get("ok") is True and flat.get("tris", 0) > 0,
                      f"{flat.get('tris', 0)} трис, {flat.get('size')}")
                rolled = post("/api/preview", {"script": (
                    "л = sheet width=120 length=600 thickness=0.6 roll=6 gap=1.4")})
                check("лист сворачивается в рулон",
                      rolled.get("ok") is True and rolled.get("tris", 0) > 1000,
                      f"{rolled.get('tris', 0)} трис, {rolled.get('size')}")
                folded = post("/api/preview", {"script": (
                    "л = sheet width=100 length=200 thickness=1\n"
                    "fold л parts=2 angle=180 gap=1")})
                check("сгиб пополам (оригами)",
                      folded.get("ok") is True and folded.get("tris", 0) > 100,
                      f"{folded.get('tris', 0)} трис, {folded.get('size')}")
                corr = post("/api/preview", {"script": (
                    "л = sheet width=120 length=200 thickness=1\n"
                    "corrugate л step=22 amp=5 mode=вафля")})
                check("гофрирование (вафля)",
                      corr.get("ok") is True and corr.get("tris", 0) > 1000,
                      f"{corr.get('tris', 0)} трис, {corr.get('size')}")
                card = post("/api/preview", {"script": (
                    "к = cardboard width=200 height=300 liner=0.4 flute=3.5 step=8")})
                check("гофрокартон одним телом",
                      card.get("ok") is True and card.get("objects") == 1,
                      f"{card.get('tris', 0)} трис, объектов {card.get('objects')}")
                check("карточки листа, сгиба, гофры и картона",
                      b"op: 'sheet'" in js_app and b"op: 'fold'" in js_app
                      and b"op: 'corrugate'" in js_app and b"op: 'cardboard'" in js_app)
                # 0.31: меню у курсора, растаскиваемые панели, часы без
                # фризов, готовые файлы — в «Загрузки»
                css = get("/css/app.css", raw=True)
                panels_js = get("/js/panels.js", raw=True)
                ctx_css = css.split(b".ctx-menu {", 1)[-1][:800]
                check("меню ПКМ появляется у курсора",
                      b"position: fixed" in ctx_css
                      and b"getBoundingClientRect" in js_app
                      and html.count(b'class="ctx-menu"') == 1,
                      f"css {len(ctx_css)} байт")
                check("панели растаскиваются и сворачиваются",
                      html.count(b'class="splitter"') == 2
                      and b'id="panel-viewer"' in html
                      and b"forma3d.panels" in panels_js
                      and b"installPanelLayout" in js_app
                      and b"is-collapsed" in css,
                      f"{len(panels_js)} байт скрипта панелей")
                clock_script = get("/api/example?key=clock")["script"]
                clock_payload = post("/api/build", {"script": clock_script})
                clock_mirrors = [o for o in clock_payload.get("objects", [])
                                 if o.get("mirror")]
                check("часы без зеркал — не фризят",
                      clock_payload.get("ok") is True and not clock_mirrors,
                      f"{len(clock_payload.get('objects', []))} деталей, "
                      f"зеркал {len(clock_mirrors)}")
                media = post_bytes("проверка_анимации.gif", b"GIF89a" + b"\x00" * 32)
                saved_path = Path(media.get("path") or "")
                check("GIF попадает в «Загрузки»",
                      bool(media.get("downloads")) and saved_path.exists()
                      and saved_path.name == "проверка_анимации.gif"
                      and b"/api/save-file?" in js_app
                      and b"btn-open-downloads" in html,
                      str(media.get("downloads") or ""))
                try:
                    saved_path.unlink(missing_ok=True)
                except OSError:
                    pass
                # 0.32: скульпт руками — вмятина, выдувание, щипок, стёсывание,
                # сверление с формой дна, полигонаж, острая складка
                sculpt = [
                    ("вмятина", "к = box size=[60,60,60] round=4\n"
                                "к = dent [к] depth=8 radius=18 soft=0.6 rim=0.3"),
                    ("выдувание", "ш = sphere radius=30 segments=40\n"
                                  "ш = blow [ш] height=12 radius=40"),
                    ("щипок", "ш = sphere radius=30 segments=40\n"
                              "ш = pinch [ш] axis=x amount=0.4 radius=16"),
                    ("стёсывание", "к = box size=[50,50,90] round=3\n"
                                  "к = shave [к] depth=12"),
                    ("заострение", "к = cylinder radius=8 height=90 segments=40\n"
                                   "к = point [к] length=25"),
                    ("сверление", "п = box size=[80,70,22]\n"
                                  "п = bore [п] diameter=14 depth=14 tip=конус countersink=4"),
                    ("полигонаж", "ш = sphere radius=30 segments=12\n"
                                  "ш = refine [ш] length=2"),
                    ("разровнять", "ш = sphere radius=32 segments=48\n"
                                   "ш = flatten [ш] at=[0,0,24] radius=24 strength=1"),
                    ("разгладить", "ш = sphere radius=30 segments=48\n"
                                   "ш = wrinkle [ш] amp=0.8 freq=40 mode=шум\n"
                                   "ш = polish [ш] passes=6 strength=0.8"),
                ]
                bad = []
                for title, script in sculpt:
                    res = post("/api/preview", {"script": script})
                    if res.get("ok") is not True or res.get("tris", 0) < 100:
                        bad.append(title)
                check("девять инструментов скульпта строятся",
                      not bad, "все, кроме " + ", ".join(bad) if bad else "9 из 9")
                sharp = post("/api/preview", {"script": (
                    "л = sheet width=120 length=200 thickness=1\n"
                    "fold л parts=2 angle=90 gap=2 sharp=1")})
                check("острая складка бумаги",
                      sharp.get("ok") is True and sharp.get("tris", 0) > 100,
                      f"{sharp.get('tris', 0)} трис")
                anime = post("/api/build", {"script": get("/api/example?key=anime_face")["script"]})
                anime_objs = [o for o in anime.get("objects", []) if o.get("visible")]
                check("пример «Аниме-бюст» — объём, а не панель",
                      anime.get("ok") is True and len(anime_objs) >= 1
                      and any(o.get("size", [0, 0, 0])[2] > 300 for o in anime_objs),
                      f"{len(anime_objs)} деталей, "
                      f"{sum(o.get('tris', 0) for o in anime_objs)} трис")
                cards = js_app.count("group: 'Скульпт'".encode()) if isinstance(js_app, bytes) else 0
                check("карточки скульпта с живыми превью",
                      cards >= 9 and b"op: 'dent'" in js_app and b"op: 'bore'" in js_app
                      and b"op: 'refine'" in js_app, f"{cards} карточек")
                # 0.32: степень детализации примитивов ползунком + число трисов
                sliders = js_app.count(b"detailParam(") if isinstance(js_app, bytes) else 0
                check("ползунок детализации у примитивов",
                      sliders >= 7 and b"kind: 'slider'" in js_app,
                      f"{sliders - 1} карточек" if sliders else "нет")
                check("подпись «сколько трисов» под миниатюрой",
                      b"tool-tris" in js_app and b"toolTrisText" in js_app
                      and b"tool-tris" in css,
                      "как в карточке, так и в стилях")
                grown = []
                # имя переменной не base: так называется адрес сервера в post()
                for op, dims in (("sphere", "radius=50"), ("cylinder", "radius=40 height=100"),
                                 ("cone", "radius=45 height=90")):
                    low = post("/api/preview", {"script": f"д = {op} {dims} detail=0"})
                    high = post("/api/preview", {"script": f"д = {op} {dims} detail=5"})
                    if not (low.get("ok") and high.get("ok")) \
                            or high.get("tris", 0) < low.get("tris", 0) * 2:
                        grown.append(op)
                check("детализация действительно меняет сетку", not grown,
                      "все, кроме " + ", ".join(grown) if grown else "0 → 5 втрое и больше")
                # 0.34: волосы, сгиб от угла, складки, цепь и инструкция для ИИ
                hair = post("/api/preview", {"script": (
                    "п = волосинки from=[-40,-30,196] to=[40,-30,196] count=30 "
                    "length=40 thick=1.6 dir=[0,-0.55,-1]\n"
                    "л = локон at=[0,0,150] length=150 radius=16 turns=0.6 "
                    "thick=16 thin=6 dir=[0,0,-1]")})
                check("волосы: волосинки и локон строятся",
                      hair.get("ok") is True and hair.get("tris", 0) > 300,
                      f"{hair.get('tris', 0)} трис")
                corner = post("/api/preview", {"script": (
                    "л = sheet width=120 length=160 thickness=1\n"
                    "с = сгиб л at=[0,0,1] dir=45 angle=135")})
                check("сгиб от угла (оригами по линии)",
                      corner.get("ok") is True and corner.get("tris", 0) > 100,
                      f"{corner.get('tris', 0)} трис")
                crease = post("/api/preview", {"script": (
                    "к = box size=[80,40,120] round=6\n"
                    "с = складка к from=[-30,-20,60] to=[30,-20,60] r=5 mode=канавка")})
                check("складка на одежде",
                      crease.get("ok") is True and crease.get("tris", 0) > 200,
                      f"{crease.get('tris', 0)} трис")
                chain = post("/api/preview", {"script": (
                    "ц = цепь links=8 size=26 wire=3.4 at=[0,0,80] dir=[1,0,0]")})
                check("цепь из зацепленных звеньев",
                      chain.get("ok") is True and chain.get("tris", 0) > 500,
                      f"{chain.get('tris', 0)} трис")
                link = post("/api/preview", {"script": (
                    "крюк = torus major=20 minor=4 at=[0,0,200]\n"
                    "ведро = cylinder radius=30 height=60 at=[0,0,40]\n"
                    "ц = соединить [крюк, ведро] size=16 wire=2.4 sag=0.15")})
                check("соединить две детали цепью",
                      link.get("ok") is True and link.get("tris", 0) > 400,
                      f"{link.get('tris', 0)} трис")
                check("пример «Оригами» собирается",
                      post("/api/build", {"script": get("/api/example?key=origami")["script"]})
                      .get("ok") is True)
                instr = get("/api/instruction?kind=full")
                cmds = get("/api/instruction?kind=commands")
                total_ops = len(__import__("forma.ops", fromlist=["OPS"]).OPS)
                check("инструкция для ИИ: все команды",
                      bool(instr.get("text")) and bool(cmds.get("text"))
                      and cmds.get("text", "").count("### ") >= total_ops,
                      f"{cmds.get('chars', 0)} символов, {total_ops} команд")
                check("кнопки копирования справочника в окне",
                      b'id="btn-copy-instruction"' in html
                      and b'id="btn-copy-commands"' in html,
                      "инструкция и все команды — отдельно от запроса")
                check("карточки сгиба от угла, складки и цепи",
                      "op: 'сгиб'".encode("utf-8") in js_app
                      and "op: 'складка'".encode("utf-8") in js_app
                      and "op: 'цепь'".encode("utf-8") in js_app,
                      "три новые карточки в инструментах")
                # 0.35: мерки соседа, размер по мерке и ряд с градацией
                rel = post("/api/preview", {"script": (
                    "ящик = box size=[80,50,30]\n"
                    "ш = cylinder radius=6 height=6\n"
                    "ш = translate [ш] offset=[0.5*width(ящик), 0, height(ящик)]")})
                rel_bb = (rel.get("size") or [0, 0, 0])
                check("мерка соседа: 0.5 ширины в сдвиге",
                      rel.get("ok") is True and float(rel_bb[0]) > 60,
                      f"габарит {rel_bb}")
                sized = post("/api/preview", {"script": (
                    "а = box size=[80,50,20]\n"
                    "б = box size=[10,10,10]\n"
                    "б = размер [б] width=1.5*width(а)")})
                sized_bb = sized.get("size") or [0, 0, 0]
                check("размер по мерке: ширина 1.5× соседа",
                      sized.get("ok") is True and abs(float(sized_bb[0]) - 120.0) < 1.0,
                      f"ширина {sized_bb[0]} мм")
                graded = post("/api/preview", {"script": (
                    "к = torus major=10 minor=2\n"
                    "р = ряд [к] count=4 grow=1.4")})
                graded_bb = graded.get("size") or [0, 0, 0]
                check("ряд: кольца растут по ступеням",
                      graded.get("ok") is True and float(graded_bb[0]) > 60,
                      f"внешнее кольцо {graded_bb[0]} мм")
                stepped = post("/api/preview", {"script": (
                    "ш = sphere radius=14 segments=64\n"
                    "р = ряд [ш] count=4 step=[36,0,0] инструмент=вмятина "
                    "сила=2 шаг_силы=1.5 radius=9")})
                check("сила инструмента ступенями (ряд с вмятинами)",
                      stepped.get("ok") is True and stepped.get("tris", 0) > 500,
                      f"{stepped.get('tris', 0)} трис")
                for key in ("wifi", "graded"):
                    one = get(f"/api/example?key={key}")
                    check(f"пример «{key}» собирается",
                          post("/api/build", {"script": one.get("script", "")})
                          .get("ok") is True)
                check("карточки ряда с градацией и размера по мерке",
                      "op: 'ряд'".encode("utf-8") in js_app
                      and "op: 'размер'".encode("utf-8") in js_app,
                      "две новые карточки в инструментах")
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
