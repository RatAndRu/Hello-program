"""Командная строка ФОРМА 3D — удобно для проверки моделей без интерфейса."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import build_prompt, command_reference_md
from .geometry import export_glb, export_obj, export_stl
from .render import render_views
from .run import build, selftest
from .version import APP_NAME, __version__


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _checks_failed(b) -> int:
    if not b.ok or not b.analysis:
        return 0
    return sum(1 for c in b.analysis.get("checks", []) if not c.get("ok"))


def _base(script_arg: str) -> Path:
    """Папка сценария — от неё считаются `включить файл=…`."""
    if not script_arg or script_arg == "-":
        return Path.cwd()
    return Path(script_arg).expanduser().resolve().parent


def cmd_build(args) -> int:
    script = _read(args.script)
    b = build(script, base_dir=_base(args.script))
    if getattr(args, "digest", False):
        digest = {
            "ok": b.ok,
            "script_hash": b.script_hash,
            "error": (b.error or {}).get("message") if not b.ok else None,
            "checks_failed": _checks_failed(b),
        }
        if b.ok:
            m = b.analysis["metrics"]
            digest.update({"size": m.get("size"), "volume_cm3": round(m.get("volume_cm3", 0), 3),
                           "tris": m.get("tris"), "genus": m.get("genus"),
                           "parts": m.get("parts")})
        print(json.dumps(digest, ensure_ascii=False))
    elif args.json:
        print(json.dumps(b.payload(), ensure_ascii=False, indent=2))
    else:
        if b.ok:
            print(b.analysis["text"])
            print()
            print(f"Построено за {b.timings.get('total')} мс")
        else:
            print("ОШИБКА:", b.error.get("message"))
            if b.error.get("hint"):
                print("Подсказка:", b.error["hint"])
            if b.error.get("line"):
                print("Строка:", b.error["line"])
            return 1
    if getattr(args, "trace", None) and b.ok:
        rows = [{"line": item.get("line"), "level": item.get("level"),
                 "message": item.get("message")} for item in b.log]
        Path(args.trace).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")
    if not b.ok:
        return 2
    failed = _checks_failed(b)
    if getattr(args, "strict", False) and failed:
        print(f"СТРОГИЙ РЕЖИМ: не выполнено проверок — {failed}.", file=sys.stderr)
        return 3
    return 0


def cmd_diff(args) -> int:
    a = build(_read(args.a))
    c = build(_read(args.b))
    for label, item in (("было", a), ("стало", c)):
        if not item.ok:
            print(f"{label}: ОШИБКА — {item.error.get('message')}")
            return 2
    print(f"{'показатель':<22}{'было':>14}{'стало':>14}{'разница':>14}")
    rows = [("объём, см³", "volume_cm3", 2), ("площадь, см²", "area_cm2", 2),
            ("треугольников", "tris", 0), ("отверстий (genus)", "genus", 0),
            ("частей", "parts", 0)]
    for title, key, digits in rows:
        va, vb = a.analysis["metrics"].get(key), c.analysis["metrics"].get(key)
        if va is None or vb is None:
            continue
        print(f"{title:<22}{va:>14.{digits}f}{vb:>14.{digits}f}{vb - va:>+14.{digits}f}")
    for axis in ("x", "y", "z"):
        sa = a.analysis["metrics"]["size"][{"x": 0, "y": 1, "z": 2}[axis]]
        sb = c.analysis["metrics"]["size"][{"x": 0, "y": 1, "z": 2}[axis]]
        print(f"размер {axis}, мм{'':<10}{sa:>14.2f}{sb:>14.2f}{sb - sa:>+14.2f}")
    return 0


def cmd_doctor(args) -> int:
    import platform
    from .paths import downloads_dir, user_data_dir
    from .version import __version__

    print(f"{APP_NAME} {__version__}")
    print(f"Python: {platform.python_version()} ({platform.system()} {platform.release()})")
    for module in ("manifold3d", "numpy", "trimesh", "webview"):
        try:
            mod = __import__(module)
            print(f"  {module}: {getattr(mod, '__version__', 'есть')}")
        except Exception as exc:
            print(f"  {module}: НЕТ ({exc})")
    from .paths import describe, migrate_legacy
    info = migrate_legacy()
    if info.get("removed"):
        print("Старые папки данных очищены: " + ", ".join(info["removed"]))
    folders = describe()
    print(f"Данные (рядом с exe): {folders['root']}")
    for name in ("projects", "exports", "renders", "prompts", "textures", "imports"):
        print(f"  {name}: {folders[name]}")
    print(f"Загрузки: {downloads_dir()}")
    try:
        probe = user_data_dir() / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        print("Запись в папку данных: да")
    except Exception as exc:
        print(f"Запись в папку данных: НЕТ ({exc})")
    try:
        probe = downloads_dir() / ".forma_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        print("Запись в «Загрузки»: да")
    except Exception as exc:
        print(f"Запись в «Загрузки»: НЕТ ({exc})")
    try:
        import manifold3d as mf
        mf.Manifold.cube([10, 10, 10], True)
        print("Ядро manifold: работает")
    except Exception as exc:
        print(f"Ядро manifold: ОШИБКА ({exc})")
    return 0


def cmd_render(args) -> int:
    script = _read(args.script)
    b = build(script, base_dir=_base(args.script))
    if not b.ok:
        print("ОШИБКА:", b.error.get("message"))
        return 2
    out = Path(args.out)
    views = tuple(args.views.split(","))
    style = (b.scene.settings or {}).get("anime") if b.scene else None
    if getattr(args, "style", None):
        # явный стиль в командной строке важнее команды anime в сценарии
        from .anime import normalize_mode, normalize_style
        text = str(args.style).strip().lower()
        style = normalize_style({"mode": normalize_mode(text, "аниме")}) \
            if text not in ("выкл", "off", "нет") else None
    result = render_views(b.visible_solids(), out, prefix=args.prefix, size=args.size,
                          ss=args.ss, views=views, combined=True, style=style,
                          groups=(b.scene.groups if b.scene else None))
    for item in result["files"]:
        print(item["path"])
    if result.get("combined"):
        print(result["combined"])
    if args.report:
        print()
        print(b.analysis["text"])
    return 0


def cmd_export(args) -> int:
    script = _read(args.script)
    b = build(script, base_dir=_base(args.script))
    if not b.ok:
        print("ОШИБКА:", b.error.get("message"), file=sys.stderr)
        return 2
    solids = b.visible_solids()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt = args.format or _format_from_suffix(out)
    if fmt == "glb":
        out.write_bytes(export_glb(solids))
    elif fmt == "stl":
        out.write_bytes(export_stl(solids))
    elif fmt == "obj":
        out.write_bytes(export_obj(solids))
    elif fmt == "ply":
        from .geometry import export_ply
        out.write_bytes(export_ply(solids))
    elif fmt == "3mf":
        from .geometry import export_3mf
        out.write_bytes(export_3mf(solids))
    elif fmt == "forma":
        out.write_text(script, encoding="utf-8")
    elif fmt == "report":
        out.write_text(b.analysis["text"], encoding="utf-8")
    elif fmt == "prompt":
        out.write_text(build_prompt(b, args.goal or ""), encoding="utf-8")
    else:
        print("Неизвестный формат", file=sys.stderr)
        return 2
    print(out)
    return 0


def _format_from_suffix(path: Path) -> str:
    """`.stl` → `stl`; незнакомое расширение — GLB, самый общий формат."""
    fmt = path.suffix.lower().lstrip(".")
    known = {"glb", "stl", "obj", "ply", "3mf", "forma", "report", "prompt"}
    return fmt if fmt in known else "glb"


def cmd_scad(args) -> int:
    """Выгрузка сцены в OpenSCAD: мост к его библиотекам и редактору."""
    from .scad import export_scad

    script = _read(args.script)
    b = build(script, analyze_model=args.mode == "script", base_dir=_base(args.script))
    if not b.ok:
        print("ОШИБКА:", b.error.get("message"), file=sys.stderr)
        return 2
    info = export_scad(b, args.out, mode=args.mode, source=script)
    print(json.dumps(info, ensure_ascii=False))
    return 0


def cmd_prompt(args) -> int:
    script = _read(args.script) if args.script != "-" else sys.stdin.read()
    b = build(script, base_dir=_base(args.script))
    text = build_prompt(b, args.goal or "")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text)
    return 0


def cmd_selftest(args) -> int:
    result = selftest()
    for case in result["cases"]:
        mark = "OK " if case["ok"] else "FAIL"
        print(f"[{mark}] {case['name']}", end="")
        if case.get("error"):
            print(" —", case["error"])
            continue
        print(f" — {case.get('tris')} трис, {case.get('timings')}")
        for chk in case.get("checks", []):
            print(("   ✓ " if chk["ok"] else "   ✗ ") + chk["text"])
    print()
    print("ИТОГ:", "всё в порядке" if result["ok"] else "есть проблемы")
    return 0 if result["ok"] else 1


def cmd_reference(args) -> int:
    text = command_reference_md()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(args.out)
    else:
        print(text)
    return 0


def cmd_mesh(args) -> int:
    """`forma mesh файл` — то же, что `check … сетка`, но без сценария."""
    import json

    from .mesh_quality import Rules, analyze, format_report, mesh_of, short_warnings

    path = Path(args.file)
    if not path.exists():
        print(f"Файл не найден: {path}")
        return 2
    suffix = path.suffix.lower()
    if suffix == ".forma":
        b = build(_read(str(path)), base_dir=_base(str(path)))
        if not b.ok:
            print("ОШИБКА:", b.error.get("message"))
            return 2
        solids = b.visible_solids()
        if not solids:
            print("В сцене нет видимых объектов.")
            return 2
        source = solids[0].manifold
    else:
        from .ops_io import load_any

        verts, faces = load_any(path)
        source = (verts, faces)
    rules = Rules() if args.sliver is None else Rules(sliver_area_pct=args.sliver)
    report = analyze(source, rules)
    if args.json:
        report.pop("_artifacts_obj", None)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    print(format_report(report))
    warnings = short_warnings(report)
    if warnings:
        print()
        print("КОРОТКО")
        for w in warnings:
            print(f"• {w}")
    return 0 if report["ok"] else 1


def cmd_lib(args) -> int:
    """`forma lib` — библиотеки-шаблоны: что есть и какой сценарий из них выходит.

    Смысл команды: чужие процедурные библиотеки (Gridfinity и подобные) у нас
    превращаются в обычный сценарий ФОРМЫ. Здесь их можно перечислить, собрать
    по параметрам и сразу проверить.
    """
    from .lib import LIBRARIES

    if not args.name:
        print("БИБЛИОТЕКИ-ШАБЛОНЫ")
        for key in sorted(LIBRARIES):
            item = LIBRARIES[key]
            print(f"• {key} — {item['title']}")
            print(f"  источник: {item['source']}")
            print(f"  {item['note']}")
        print()
        print("Собрать: forma lib gridfinity kind=bin size=2x3 height=6 --save ящик.forma")
        print("Проверить: forma lib gridfinity size=2x2 kind=baseplate --check")
        return 0

    name = args.name.strip().lower()
    if name not in LIBRARIES:
        print(f"Нет библиотеки «{args.name}». Есть: {', '.join(sorted(LIBRARIES))}")
        return 2
    options = {}
    for item in args.options or []:
        if "=" not in item:
            print(f"Параметр «{item}» без значения. Пишите так: size=2x3")
            return 2
        key, value = item.split("=", 1)
        options[key.strip().lower()] = value.strip()
    try:
        script = LIBRARIES[name]["build"](**options)
    except (TypeError, ValueError) as exc:
        print(f"ОШИБКА: {exc}")
        library_params = LIBRARIES[name].get("params")
        if library_params:
            print(f"Параметры: {library_params}")
        elif name == "gridfinity":
            from .lib.gridfinity import params_help
            print("Параметры:")
            for key, text in params_help():
                print(f"  {key} — {text}")
        return 2

    if args.save:
        path = Path(args.save).expanduser()
        path.write_text(script, encoding="utf-8")
        print(f"Сценарий сохранён: {path}")
    if args.check:
        b = build(script, base_dir=Path(args.save).expanduser().parent if args.save else Path.cwd())
        if not b.ok:
            print("ОШИБКА ПОСТРОЕНИЯ:", b.error.get("message"))
            if b.error.get("hint"):
                print("Подсказка:", b.error["hint"])
            return 2
        print(b.analysis["text"])
        return 0 if not _checks_failed(b) else 1
    if not args.save:
        print(script, end="")
    return 0


def cmd_serve(args) -> int:
    from .app import main as app_main
    return app_main(["--host", args.host, "--port", str(args.port)] +
                    (["--browser"] if args.browser else []) +
                    (["--no-open"] if args.no_open else []))


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv=None) -> int:
    _utf8_stdout()
    parser = argparse.ArgumentParser(prog="forma", description=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="построить модель и вывести отчёт")
    p.add_argument("script")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true",
                   help="вернуть код 3, если какая-то проверка check не выполнена")
    p.add_argument("--trace", help="записать журнал построения в JSONL")
    p.add_argument("--digest", action="store_true",
                   help="короткая сводка (хеш сценария и ключевые метрики) в JSON")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("diff", help="сравнить две сборки по метрикам")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("doctor", help="проверить окружение и папки")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("render", help="сделать PNG-снимки видов")
    p.add_argument("script")
    p.add_argument("--out", default="renders")
    p.add_argument("--prefix", default="model")
    p.add_argument("--views", default="iso,front,right,top")
    p.add_argument("--size", type=int, default=640)
    p.add_argument("--ss", type=int, default=2)
    p.add_argument("--report", action="store_true")
    p.add_argument("--style", default=None,
                   help="аниме-стиль снимков: аниме, манга, комикс, линия или выкл "
                        "(по умолчанию берётся из команды anime в сценарии)")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("export", help="экспортировать модель")
    p.add_argument("script")
    # формат не задан — берём из расширения файла, иначе GLB: так `--out дом.stl`
    # не запишет в файл .stl содержимое GLB
    p.add_argument("--format", default=None,
                   choices=["glb", "stl", "obj", "ply", "3mf", "forma", "report", "prompt"])
    p.add_argument("--out", required=True)
    p.add_argument("--goal", default="")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("scad", help="экспортировать сцену в OpenSCAD (.scad)")
    p.add_argument("script")
    p.add_argument("--out", required=True)
    p.add_argument("--mode", choices=("solid", "script"), default="solid",
                   help="solid — геометрия как есть; script — перевод по командам")
    p.set_defaults(func=cmd_scad)

    p = sub.add_parser("prompt", help="сформировать запрос к нейросети")
    p.add_argument("script", nargs="?", default="-")
    p.add_argument("--goal", default="")
    p.add_argument("--out")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("selftest", help="проверить геометрическое ядро")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("mesh", help="диагностика сетки: стяжки, иглы, плотность")
    p.add_argument("file", help="сценарий .forma, сетка .stl/.obj/.ply или .glb")
    p.add_argument("--json", action="store_true", help="выдать отчёт словарём")
    p.add_argument("--sliver", type=float, default=None,
                   help="порог площади под иглами на кривизне, %% (1)")
    p.set_defaults(func=cmd_mesh)

    p = sub.add_parser("lib", help="библиотеки-шаблоны: список и сборка сценария")
    p.add_argument("name", nargs="?", help="имя библиотеки; без него — список")
    p.add_argument("options", nargs="*", help="параметры вида size=2x3 height=6")
    p.add_argument("--save", help="записать сценарий в файл")
    p.add_argument("--check", action="store_true", help="сразу построить и показать отчёт")
    p.set_defaults(func=cmd_lib)

    p = sub.add_parser("reference", help="справочник команд в markdown")
    p.add_argument("--out")
    p.set_defaults(func=cmd_reference)

    p = sub.add_parser("serve", help="запустить интерфейс")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--browser", action="store_true")
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
