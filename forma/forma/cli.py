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


def cmd_build(args) -> int:
    script = _read(args.script)
    b = build(script)
    if args.json:
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
    return 0 if b.ok else 2


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
    p.set_defaults(func=cmd_build)

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
    p.add_argument("--format", default="glb", choices=["glb", "stl", "obj", "forma", "report", "prompt"])
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
