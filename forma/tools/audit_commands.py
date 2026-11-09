"""Ревизия реестра команд: что объявлено — и что на самом деле работает.

Скрипт не «смотрит глазами», а строит каждый пример из реестра и записывает
факт: собралось ли, за сколько, сколько треугольников, какие параметры описаны
типами, есть ли памятка об ориентации и упоминание в тестах. На выходе —
машинный отчёт (JSON) и человеческий (markdown), по ним и планируется работа.

    python tools/audit_commands.py                    # полный отчёт
    python tools/audit_commands.py --limit 40         # быстрый срез
    python tools/audit_commands.py --only box,bolt    # конкретные команды
    python tools/audit_commands.py --json audit.json  # куда писать
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.param_spec import SPECS, spec_for  # noqa: E402
from forma.run import build                    # noqa: E402

# Почему пример не собрался — по тексту ошибки. «Внешнее ПО» (OpenSCAD) не вина
# команды: без установленной программы такой пример проверить нельзя.
WHY_KINDS = (
    ("tool", ("OpenSCAD не найден", "не найден OpenSCAD", "FORMA_OPENSCAD")),
    ("file", ("Не удалось прочитать", "не удалось прочитать", "нет файла",
              "No such file", "не найден файл")),
    ("object", ("Не найден объект", "не объявлен", "Неизвестный объект")),
    ("geometry", ("столкновени", "manifold", "пусто", "вырожден")),
)


def classify(message: str) -> str:
    text = message or ""
    for kind, needles in WHY_KINDS:
        if any(needle in text for needle in needles):
            return kind
    return "script"

REPORT_MD = ROOT / "docs" / "revision.md"
REPORT_JSON = ROOT / "docs" / "revision.json"


def test_mentions() -> set[str]:
    """Имена команд, которые вообще встречаются в тестах."""
    names: set[str] = set()
    folder = ROOT / "tests"
    for file in list(folder.glob("*.py")) + list(folder.glob("*.js")):
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        names.update(text.split())
    return names


def audit_op(spec, mentions: set[str]) -> dict:
    from forma.orient_notes import orientation_for

    example = (spec.example or "").strip()
    entry: dict = {
        "name": spec.name,
        "category": spec.category,
        "aliases": list(spec.aliases),
        "params": list(spec.params),
        "positional": spec.positional if isinstance(spec.positional, str) else list(spec.positional or []),
        "typed": sorted(spec_for(spec.name, list(spec.params))),
        "typed_explicit": sorted(SPECS.get(spec.name, {})),
        "typed_all": bool(spec.params) and set(spec.params) <= set(spec_for(spec.name, list(spec.params))),
        "orientation": bool(orientation_for(spec.name)),
        "summary_len": len(spec.summary or ""),
        "mentions_tests": spec.name in mentions
        or any(alias in mentions for alias in spec.aliases),
    }
    if not example:
        entry.update({"example": "", "ok": None, "why": "нет примера"})
        return entry
    entry["example"] = example
    entry["checks"] = sum(1 for line in example.splitlines()
                          if line.strip().lower().startswith("check"))
    started = time.perf_counter()
    try:
        result = build(example, analyze_model=False)
    except Exception as exc:  # падение ядра — это тоже факт
        entry.update({"ok": False, "seconds": round(time.perf_counter() - started, 2),
                      "why": f"исключение: {exc!r}"[:300]})
        return entry
    seconds = round(time.perf_counter() - started, 2)
    if not result.ok:
        why = (result.error or {}).get("message", "не собралось")[:300]
        entry.update({"ok": False, "seconds": seconds, "why": why,
                      "why_kind": classify(why)})
        return entry
    solids = result.scene.visible_solids()
    entry.update({
        "ok": True,
        "seconds": seconds,
        "objects": len(result.scene.objects),
        "solids": len(solids),
        "tris": sum(int(solid.stats()["tris"]) for solid in solids),
        "checks": entry["checks"],
        "non_manifold": sum(1 for solid in solids
                             if str(solid.manifold.status()).split(".")[-1] != "NoError"),
    })
    return entry


def summarize(rows: list[dict]) -> dict:
    cats = Counter(row["category"] for row in rows)
    total_params = sum(len(row["params"]) for row in rows)
    typed_params = sum(len(row["typed"]) for row in rows)
    failed = [row for row in rows if row["ok"] is False]
    blocked = [row for row in failed if row.get("why_kind") == "tool"]
    no_example = [row for row in rows if row["ok"] is None]
    slow = sorted((row for row in rows if row["ok"]), key=lambda row: -row["seconds"])[:12]
    non_manifold = [row for row in rows if row["ok"] and row.get("non_manifold")]
    return {
        "commands": len(rows),
        "categories": dict(cats),
        "examples_failed": len(failed),
        "examples_blocked": len(blocked),
        "failed_kinds": dict(Counter(row.get("why_kind", "script") for row in failed)),
        "examples_missing": len(no_example),
        "typed_params": typed_params,
        "total_params": total_params,
        "typed_commands": sum(1 for row in rows if row["typed"]),
        "fully_typed_commands": sum(1 for row in rows if row["typed_all"]),
        "with_orientation": sum(1 for row in rows if row["orientation"]),
        "without_tests": sum(1 for row in rows if not row["mentions_tests"]),
        "total_seconds": round(sum(row.get("seconds") or 0 for row in rows), 1),
        "slow": [(row["name"], row["seconds"], row.get("tris", 0)) for row in slow],
        "non_manifold": [(row["name"], row["non_manifold"]) for row in non_manifold],
        "failed": [(row["name"], row.get("why", ""), row.get("why_kind", "script"))
                   for row in failed],
        "blocked": [(row["name"], row.get("why", "")) for row in blocked],
    }


def markdown(rows: list[dict], stats: dict) -> str:
    lines = ["# Ревизия реестра команд", "",
             f"Команд: **{stats['commands']}**. Примеры собрались: "
             f"**{stats['commands'] - stats['examples_failed'] - stats['examples_missing']}**, "
             f"не собрались: **{stats['examples_failed'] - stats['examples_blocked']}**, "
             f"ждут внешней программы (OpenSCAD): **{stats['examples_blocked']}**, "
             f"без примера: **{stats['examples_missing']}**.", "",
             "| | |", "|---|---|",
             f"| параметров всего | {stats['total_params']} |",
             f"| параметров с типом | {stats['typed_params']} |",
             f"| команд с типами | {stats['typed_commands']} |",
             f"| команд с полной типизацией | {stats['fully_typed_commands']} |",
             f"| памяток об ориентации | {stats['with_orientation']} |",
             f"| команд без упоминания в тестах | {stats['without_tests']} |",
             f"| суммарное время примеров | {stats['total_seconds']} с |", ""]
    broken = [item for item in stats["failed"] if item[2] != "tool"]
    if broken:
        lines += ["## Примеры, которые не собираются", "",
                  "| команда | вид | причина |", "|---|---|---|"]
        lines += [f"| `{name}` | {kind} | {why.replace('|', '/')} |"
                  for name, why, kind in broken]
        lines.append("")
    if stats["blocked"]:
        lines += ["## Примеры, ждущие внешней программы", "",
                  "Эти примеры исправны, но для запуска нужен OpenSCAD "
                  "(Forma не запускает внешнее GUI и не подменяет расчёт).", ""]
        lines += [f"* `{name}` — {why.replace('|', '/')}" for name, why in stats["blocked"]]
        lines.append("")
    if stats["non_manifold"]:
        lines += ["## Тела с не manifold-геометрией", ""]
        lines += [f"* `{name}` — {count} тел(о)" for name, count in stats["non_manifold"]]
        lines.append("")
    lines += ["## Самые долгие примеры", "", "| команда | секунды | треугольники |", "|---|---|---|"]
    lines += [f"| `{name}` | {seconds} | {tris} |" for name, seconds, tris in stats["slow"]]
    lines.append("")
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_cat[row["category"]].append(row)
    for category in sorted(by_cat):
        items = sorted(by_cat[category], key=lambda row: row["name"])
        lines += [f"## {category} — {len(items)}", "",
                  "| команда | пример | с | типы | ориентация | тесты |",
                  "|---|---|---|---|---|---|"]
        for row in items:
            ok = {True: "✓", False: "✗", None: "—"}[row["ok"]]
            typed = f"{len(row['typed'])}/{len(row['params'])}"
            lines.append(f"| `{row['name']}` | {ok} | {row.get('seconds', '')} | {typed} | "
                         f"{'✓' if row['orientation'] else ''} | "
                         f"{'✓' if row['mentions_tests'] else ''} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ревизия реестра команд")
    parser.add_argument("--only", default="", help="через запятую: какие команды")
    parser.add_argument("--limit", type=int, default=0, help="только первые N команд")
    parser.add_argument("--json", default="", help="куда писать JSON-отчёт")
    parser.add_argument("--markdown", default="", help="куда писать markdown-отчёт")
    parser.add_argument("--samples", action="store_true", help="печатать по строке на команду")
    args = parser.parse_args()

    import forma.run  # noqa: F401  — регистрация операций
    from forma.ops import OPS

    wanted = [name.strip().lower() for name in args.only.split(",") if name.strip()]
    mentions = test_mentions()
    rows = []
    specs = sorted(OPS.values(), key=lambda spec: spec.name)
    for spec in specs:
        if wanted and spec.name.lower() not in wanted:
            continue
        if args.limit and len(rows) >= args.limit:
            break
        rows.append(audit_op(spec, mentions))
        if args.samples:
            row = rows[-1]
            mark = {True: "ok", False: "FAIL", None: "нет"}[row["ok"]]
            print(f"{row['name']:22s} {mark:4s} {row.get('seconds', ''):>6} "
                  f"{row.get('why', '')}", flush=True)

    stats = summarize(rows)
    json_path = Path(args.json) if args.json else REPORT_JSON
    md_path = Path(args.markdown) if args.markdown else REPORT_MD
    if not wanted and not args.limit:
        json_path.write_text(json.dumps({"stats": stats, "commands": rows},
                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        md_path.write_text(markdown(rows, stats) + "\n", encoding="utf-8")
        print(f"отчёт: {md_path.relative_to(ROOT)} и {json_path.relative_to(ROOT)}")
    print(f"команд {stats['commands']}: собрались "
          f"{stats['commands'] - stats['examples_failed'] - stats['examples_missing']}, "
          f"не собрались {stats['examples_failed'] - stats['examples_blocked']}, "
          f"ждут внешней программы {stats['examples_blocked']}, "
          f"без примера {stats['examples_missing']}; "
          f"типы {stats['typed_params']}/{stats['total_params']}; "
          f"{stats['total_seconds']} с на все примеры")
    if broken := [row for row in rows if row["ok"] is False and row.get("why_kind") != "tool"]:
        print("не собираются: " + ", ".join(f"{row['name']} ({row.get('why_kind')})"
                                            for row in broken))
    return 0 if stats["examples_failed"] == stats["examples_blocked"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
