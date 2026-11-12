"""Командная строка ФОРМА 3D — удобно для проверки моделей без интерфейса."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import build_prompt, command_reference_md
from .geometry import export_obj, export_stl
from .scad import export_scad_bytes
from .render import render_views
from .run import build, selftest
from .version import APP_NAME, __version__


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _base_dir(path: str) -> Path | None:
    return None if path == "-" else Path(path).expanduser().resolve().parent


def _checks_failed(b) -> int:
    if not b.ok or not b.analysis:
        return 0
    return sum(1 for c in b.analysis.get("checks", []) if not c.get("ok"))


def _print_profile(b, limit: int = 10) -> None:
    """Печатает короткий профиль без изменения машинного JSON-вывода."""
    print("ПРОФИЛЬ КОМАНД (мс):")
    rows = sorted(b.command_timings, key=lambda item: item.get("ms", 0.0), reverse=True)
    if not rows:
        print("  команд нет")
    for item in rows[:limit]:
        target = f" → {item['target']}" if item.get("target") else ""
        status = "" if item.get("status") == "ok" else " [ошибка]"
        print(f"  {item.get('ms', 0.0):>10.3f}  строка {item.get('line', 0):>3}  "
              f"{item.get('verb') or 'параметр'}{target}{status}")
    if len(rows) > limit:
        print(f"  … ещё команд: {len(rows) - limit}")
    summary = "  итого: " + ", ".join(
        f"{key}={value} мс" for key, value in b.timings.items()
        if isinstance(value, (int, float)))
    if b.timings:
        print(summary)


def cmd_build(args) -> int:
    script = _read(args.script)
    b = build(script, base_dir=_base_dir(args.script))
    if getattr(args, "profile", False) and not args.json and not getattr(args, "digest", False):
        _print_profile(b)
        print()
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
    from .semantic_diff import semantic_diff

    a = build(_read(args.a), base_dir=_base_dir(args.a))
    c = build(_read(args.b), base_dir=_base_dir(args.b))
    for label, item in (("было", a), ("стало", c)):
        if not item.ok:
            print(f"{label}: ОШИБКА — {item.error.get('message')}")
            return 2
    try:
        report = semantic_diff(a, c, linear_tol=args.linear_tol,
                               area_tol=args.area_tol, volume_tol=args.volume_tol)
    except ValueError as exc:
        print(f"diff: ОШИБКА — {exc}")
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"Объекты: +{len(report['added'])} −{len(report['removed'])} "
          f"изменено {len(report['changed'])}; "
          f"контуры изменены: {len(report['contours']['changed'])}")
    for name in report["added"]:
        print(f"  + {name}")
    for name in report["removed"]:
        print(f"  − {name}")
    for item in report["changed"]:
        print(f"  ~ {item['name']}: {', '.join(item['reasons'])}")
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
    from .openscad import OpenSCADRunner
    openscad = OpenSCADRunner().info()
    print("OpenSCAD: " + (f"найден ({openscad['executable']})" if openscad["found"]
                         else "не найден (FORMA_OPENSCAD или PATH; GUI не нужен)"))
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
    b = build(script, base_dir=_base_dir(args.script))
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
    b = build(script, base_dir=_base_dir(args.script))
    if not b.ok:
        print("ОШИБКА:", b.error.get("message"), file=sys.stderr)
        return 2
    solids = b.visible_solids()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.format in ("glb", "glb-alpha"):
        out.write_bytes(b.export_glb(glass_fallback=args.format == "glb-alpha"))
    elif args.format == "scad":
        out.write_bytes(export_scad_bytes(solids, source=script))
    elif args.format == "drawing":
        from . import cuts
        from .webui import _drawing_sections
        cuts.export_dimensioned_dxf(_drawing_sections(b.scene), out)
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
    elif args.format in ("fold", "cp"):
        from .origami import encode_cp, encode_fold, pattern_from_scene
        pattern = pattern_from_scene(b.scene)
        text = encode_fold(pattern) if args.format == "fold" else encode_cp(pattern)
        out.write_text(text, encoding="utf-8")
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


def cmd_eval(args) -> int:
    from .eval import run_cli as run_eval_cli
    return run_eval_cli(args)


def cmd_fuzz(args) -> int:
    from .fuzz import run_cli as run_fuzz_cli
    return run_fuzz_cli(args)


def cmd_mesh(args) -> int:
    """Диагностирует укладку сетки без изменения исходного файла.

    Для .forma анализируются все видимые тела, а не только первое: иначе
    дефект во втором объекте сцены давал бы ложно зелёный результат CI.
    """
    from .mesh_quality import Rules, analyze, format_report, mesh_of

    if args.sliver is not None and args.sliver < 0:
        print("ОШИБКА: --sliver не может быть отрицательным", file=sys.stderr)
        return 2
    path = Path(args.file)
    try:
        if path.suffix.lower() == ".forma":
            b = build(_read(str(path)), base_dir=_base_dir(str(path)), analyze_model=False)
            if not b.ok:
                print("ОШИБКА:", (b.error or {}).get("message", "сценарий не построен"),
                      file=sys.stderr)
                return 2
            solids = b.visible_solids()
            if not solids:
                print("В сценарии нет видимых твёрдых тел", file=sys.stderr)
                return 2
            if len(solids) == 1:
                source = solids[0].manifold
            else:
                import numpy as np
                vertices, faces = [], []
                offset = 0
                for solid in solids:
                    v, f = mesh_of(solid.manifold)
                    vertices.append(v)
                    faces.append(f + offset)
                    offset += len(v)
                source = (np.vstack(vertices), np.vstack(faces))
        else:
            from .ops_io import load_any
            source = load_any(path)
        rules = Rules(sliver_area_pct=args.sliver) if args.sliver is not None else Rules()
        report = analyze(source, rules)
    except Exception as exc:
        print(f"ОШИБКА анализа сетки: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    return 0 if report["ok"] else 1


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
    p.add_argument("--profile", action="store_true",
                   help="показать время каждой команды и этапов сборки")
    p.add_argument("--digest", action="store_true",
                   help="короткая сводка (хеш сценария и ключевые метрики) в JSON")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("diff", help="семантически сравнить две сборки")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--json", action="store_true", help="объектный diff в JSON")
    p.add_argument("--linear-tol", type=float, default=1e-3, help="допуск размеров, мм")
    p.add_argument("--area-tol", type=float, default=None, help="допуск площади, мм²")
    p.add_argument("--volume-tol", type=float, default=None, help="допуск объёма, мм³")
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
    p.add_argument("--format", default="glb",
                   choices=["glb", "glb-alpha", "scad", "drawing", "stl", "obj", "ply", "3mf", "forma", "fold", "cp", "report", "prompt"])
    p.add_argument("--out", required=True)
    p.add_argument("--goal", default="")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("prompt", help="сформировать запрос к нейросети")
    p.add_argument("script", nargs="?", default="-")
    p.add_argument("--goal", default="")
    p.add_argument("--out")
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("eval", help="benchmark сценариев и оценка ответов нейросети")
    from .eval import configure_parser as configure_eval_parser
    configure_eval_parser(p)
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("fuzz", help="детерминированный fuzz DSL и GLB")
    from .fuzz import configure_parser as configure_fuzz_parser
    configure_fuzz_parser(p)
    p.set_defaults(func=cmd_fuzz)

    p = sub.add_parser("selftest", help="проверить геометрическое ядро")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("mesh", help="диагностика качества треугольной сетки")
    p.add_argument("file", help=".forma, .glb/.gltf, .stl, .obj, .ply, .3mf и другие поддерживаемые форматы")
    p.add_argument("--json", action="store_true", help="машинный JSON для CI")
    p.add_argument("--sliver", type=float, default=None,
                   help="допустимая доля площади игл на кривизне, %% (по умолчанию 1)")
    p.set_defaults(func=cmd_mesh)

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
