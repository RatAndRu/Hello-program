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


def cmd_build(args) -> int:
    script = _read(args.script)
    b = build(script)
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
    print(f"Данные: {user_data_dir()}")
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
    b = build(script)
    if not b.ok:
        print("ОШИБКА:", b.error.get("message"))
        return 2
    out = Path(args.out)
    views = tuple(args.views.split(","))
    result = render_views(b.visible_solids(), out, prefix=args.prefix, size=args.size,
                          ss=args.ss, views=views, combined=True)
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
    b = build(script)
    if not b.ok:
        print("ОШИБКА:", b.error.get("message"), file=sys.stderr)
        return 2
    solids = b.visible_solids()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "glb":
        out.write_bytes(export_glb(solids))
    elif args.format == "stl":
        out.write_bytes(export_stl(solids))
    elif args.format == "obj":
        out.write_bytes(export_obj(solids))
    elif args.format == "ply":
        from .geometry import export_ply
        out.write_bytes(export_ply(solids))
    elif args.format == "3mf":
        from .geometry import export_3mf
        out.write_bytes(export_3mf(solids))
    elif args.format == "forma":
        out.write_text(script, encoding="utf-8")
    elif args.format == "report":
        out.write_text(b.analysis["text"], encoding="utf-8")
    elif args.format == "prompt":
        out.write_text(build_prompt(b, args.goal or ""), encoding="utf-8")
    else:
        print("Неизвестный формат", file=sys.stderr)
        return 2
    print(out)
    return 0


def cmd_prompt(args) -> int:
    script = _read(args.script) if args.script != "-" else sys.stdin.read()
    b = build(script)
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
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("export", help="экспортировать модель")
    p.add_argument("script")
    p.add_argument("--format", default="glb",
                   choices=["glb", "stl", "obj", "ply", "3mf", "forma", "report", "prompt"])
    p.add_argument("--out", required=True)
    p.add_argument("--goal", default="")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("prompt", help="сформировать запрос к нейросети")
    p.add_argument("script", nargs="?", default="-")
    p.add_argument("--goal", default="")
    p.add_argument("--out")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("selftest", help="проверить геометрическое ядро")
    p.set_defaults(func=cmd_selftest)

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
