"""Ревизия примитивов: параметры и собранные сетки.

Скрипт не смотрит на код «глазами», а строит пример каждого примитива и
проверяет то, что получается на выходе:

* сборка примера — время, число тел, треугольников;
* сетка каждого тела — контрольная очистка экспорта, вырожденные грани,
  non-manifold рёбра, минимальное ребро, объём, род, число частей;
* факт экспорта — STL и GLB пишутся, а не падают на «Экспорт остановлен»;
* параметры — сколько объявлено, сколько получило тип, что осталось свободным.

Запуск::

    python tools/audit_primitives.py                  # полный отчёт
    python tools/audit_primitives.py --only box,bolt  # конкретные примитивы
    python tools/audit_primitives.py --samples        # строка на примитив
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.geometry import (_clean_manifold_arrays, export_glb,  # noqa: E402
                            export_stl, manifold_mesh, solid_parts)
from forma.param_spec import spec_for  # noqa: E402
from forma.run import build  # noqa: E402
from forma.topology import analyze_topology  # noqa: E402

REPORT_MD = ROOT / "docs" / "primitives.md"
REPORT_JSON = ROOT / "docs" / "primitives.json"


def audit_solid(solid) -> dict:
    """Сетка одного тела: контрольная копия экспорта и её метрики."""
    verts, faces = _clean_manifold_arrays(solid.manifold)
    report = analyze_topology(verts, faces, include_quality=False)
    return {
        "name": solid.name,
        "triangles": len(faces),
        "volume": round(float(solid.manifold.volume()), 3),
        "genus": int(solid.manifold.genus()),
        "parts": int(solid_parts(solid.manifold)),
        "gate": bool(report["ok"]),
        "degenerate": int(report["degenerate_index"]),
        "non_manifold": int(report["non_manifold_edges"]),
        "boundary": int(report["boundary_edges"]),
        "duplicate_faces": int(report["duplicate_faces"]),
        "min_edge": float(report["min_edge"]),
    }


def audit_op(spec) -> dict:
    params = list(spec.params)
    typed = spec_for(spec.name, params)
    entry: dict = {
        "name": spec.name,
        "category": spec.category,
        "params": len(params),
        "typed": len(typed),
        "free": sorted(set(params) - set(typed)),
        "example": spec.example,
    }
    started = time.perf_counter()
    try:
        result = build(spec.example, analyze_model=False)
    except Exception as exc:  # падение ядра — тоже факт
        entry.update({"ok": False, "seconds": round(time.perf_counter() - started, 3),
                      "why": f"исключение: {exc!r}"[:300]})
        return entry
    entry["seconds"] = round(time.perf_counter() - started, 3)
    if not result.ok:
        entry.update({"ok": False, "why": (result.error or {}).get("message", "")[:300]})
        return entry
    solids = result.scene.visible_solids()
    entry["ok"] = True
    entry["solids"] = [audit_solid(solid) for solid in solids]
    entry["triangles"] = sum(item["triangles"] for item in entry["solids"])
    entry["export_stl"] = 0
    entry["export_glb"] = 0
    try:
        entry["export_stl"] = len(export_stl(solids))
        entry["export_glb"] = len(export_glb(solids))
    except Exception as exc:
        entry["export_error"] = str(exc)[:300]
    entry["issues"] = [
        f"{item['name']}: {label}"
        for item in entry["solids"]
        for label, bad in (("схлопнувшиеся грани", item["degenerate"]),
                           ("non-manifold рёбра", item["non_manifold"]),
                           ("граничные рёбра", item["boundary"]),
                           ("дубли граней", item["duplicate_faces"]))
        if bad
    ]
    if entry.get("export_error"):
        entry["issues"].append("экспорт: " + entry["export_error"])
    return entry


def summarize(rows: list[dict]) -> dict:
    built = [row for row in rows if row.get("ok")]
    broken = [row for row in rows if row.get("ok") is False]
    with_issues = [row for row in built if row.get("issues")]
    params = sum(row["params"] for row in rows)
    typed = sum(row["typed"] for row in rows)
    return {
        "primitives": len(rows),
        "built": len(built),
        "failed": len(broken),
        "params": params,
        "typed": typed,
        "fully_typed": sum(1 for row in rows if row["params"] and row["typed"] == row["params"]),
        "without_types": [row["name"] for row in rows if row["typed"] == 0],
        "mesh_issues": len(with_issues),
        "triangles": sum(row.get("triangles") or 0 for row in built),
        "seconds": round(sum(row.get("seconds") or 0 for row in rows), 1),
        "multipart": sorted(name for row in built
                            for name in ([row["name"]] if any(item["parts"] > 1
                                                             for item in row["solids"]) else [])),
        "failed_list": [(row["name"], row.get("why", "")) for row in broken],
        "issue_list": [(row["name"], row["issues"]) for row in with_issues],
        "free_params": dict(Counter(name for row in rows for name in row["free"]).most_common(20)),
        "slow": sorted(((row["name"], row.get("seconds") or 0) for row in built),
                       key=lambda item: -item[1])[:10],
    }


def markdown(rows: list[dict], stats: dict) -> str:
    lines = [
        "# Примитивы: параметры и сетки", "",
        f"Примитивов: **{stats['primitives']}**. Примеры собрались: **{stats['built']}**, "
        f"не собрались: **{stats['failed']}**. С замечаниями к сетке: "
        f"**{stats['mesh_issues']}**.", "",
        "| | |", "|---|---|",
        f"| параметров | {stats['params']} |",
        f"| с типом | {stats['typed']} |",
        f"| полностью типизированы | {stats['fully_typed']} |",
        f"| треугольников во всех примерах | {stats['triangles']} |",
        f"| тел из нескольких частей | {stats['multipart']} |",
        f"| время сборки примеров | {stats['seconds']} с |", "",
    ]
    if stats["failed_list"]:
        lines += ["## Не собираются", "", "| примитив | причина |", "|---|---|"]
        lines += [f"| `{name}` | {why.replace('|', '/')} |" for name, why in stats["failed_list"]]
        lines.append("")
    if stats["issue_list"]:
        lines += ["## Замечания к сетке", "", "| примитив | что не так |", "|---|---|"]
        lines += [f"| `{name}` | {'; '.join(issues).replace('|', '/')} |"
                  for name, issues in stats["issue_list"]]
        lines.append("")
    else:
        lines += ["## Замечания к сетке", "",
                  "Ни одного: каждый пример пишется в STL и GLB, без схлопнувшихся "
                  "граней, non-manifold и граничных рёбер.", ""]
    if stats["multipart"]:
        lines += ["## Многотельные детали", "",
                  "Это не ошибка: буквы, звенья цепи и бахрома ковра — отдельные "
                  "тела в одном объекте. Список нужен, чтобы отличать замысел от "
                  "случайно распавшейся детали.", ""]
        lines += [f"* `{name}`" for name in stats["multipart"]]
        lines.append("")
    if stats["free_params"]:
        lines += ["## Часто остаются без типа", "",
                  "| параметр | сколько примитивов |", "|---|---|"]
        lines += [f"| `{name}` | {count} |" for name, count in stats["free_params"].items()]
        lines.append("")
    lines += ["## Самые долгие примеры", "", "| примитив | секунды |", "|---|---|"]
    lines += [f"| `{name}` | {seconds} |" for name, seconds in stats["slow"]]
    lines.append("")
    lines += ["## Все примитивы", "",
              "| примитив | пример | с | типы | тела | треугольники | сетка |",
              "|---|---|---|---|---|---|---|"]
    for row in sorted(rows, key=lambda item: item["name"]):
        ok = {True: "✓", False: "✗", None: "—"}[row.get("ok")]
        mesh = "—" if not row.get("ok") else ("✓" if not row.get("issues") else "✗")
        lines.append(
            f"| `{row['name']}` | {ok} | {row.get('seconds', '')} | "
            f"{row['typed']}/{row['params']} | {len(row.get('solids') or [])} | "
            f"{row.get('triangles', '')} | {mesh} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ревизия примитивов и их сеток")
    parser.add_argument("--only", default="", help="через запятую: какие примитивы")
    parser.add_argument("--json", default="", help="куда писать JSON")
    parser.add_argument("--markdown", default="", help="куда писать markdown")
    parser.add_argument("--samples", action="store_true", help="печатать по строке")
    args = parser.parse_args()

    import forma.run  # noqa: F401  — регистрация операций
    from forma.ops import OPS

    wanted = [name.strip().lower() for name in args.only.split(",") if name.strip()]
    rows = []
    for spec in sorted(OPS.values(), key=lambda item: item.name):
        if spec.category != "Примитивы":
            continue
        if wanted and spec.name.lower() not in wanted:
            continue
        rows.append(audit_op(spec))
        if args.samples:
            row = rows[-1]
            mark = "ok" if row.get("ok") else "FAIL"
            note = "; ".join(row.get("issues") or [])[:90] if row.get("ok") else row.get("why", "")
            print(f"{row['name']:22s} {mark:4s} {row.get('seconds', ''):>6} "
                  f"{row['typed']:>3}/{row['params']:<3} {note}", flush=True)

    stats = summarize(rows)
    json_path = Path(args.json) if args.json else REPORT_JSON
    md_path = Path(args.markdown) if args.markdown else REPORT_MD
    if not wanted:
        json_path.write_text(json.dumps({"stats": stats, "primitives": rows},
                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        md_path.write_text(markdown(rows, stats) + "\n", encoding="utf-8")
        print(f"отчёт: {md_path.relative_to(ROOT)} и {json_path.relative_to(ROOT)}")
    print(f"примитивов {stats['primitives']}: собрались {stats['built']}, "
          f"не собрались {stats['failed']}, замечаний к сетке {stats['mesh_issues']}; "
          f"типы {stats['typed']}/{stats['params']}; {stats['seconds']} с")
    for name, issues in stats["issue_list"][:10]:
        print(f"  {name}: {'; '.join(issues)[:120]}")
    for name, why in stats["failed_list"][:10]:
        print(f"  {name}: {why[:120]}")
    return 0 if stats["failed"] == 0 and stats["mesh_issues"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
