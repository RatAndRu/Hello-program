"""Сравнение: одна и та же деталь в OpenSCAD и в DSL ФОРМЫ.

Запускается в CI после того, как OpenSCAD отрендерил STL. Считает по STL
объём, массу и треугольники (OpenSCAD сам этого не умеет), затем строит ту же
деталь через `forma.run.build` и печатает общую таблицу.

    python compare.py out/bracket.stl out/from_forma.stl

Первый файл — рукописный `bracket.scad`, второй — `.scad`, который ФОРМА
сгенерировала сама из `bracket.f3d`. Если второй столбец совпал с третьим,
значит экспорт переносит геометрию без потерь.

Печатает таблицу в stdout — её видно в логе GitHub Actions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np  # noqa: F401  (нужен trimesh для части операций)
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # forma/ — корень пакета
from forma.run import build  # noqa: E402

DENSITY_PLA = 1.24  # г/см³

#: та же деталь на DSL ФОРМЫ, что и в `bracket.scad`, но БЕЗ скругления углов:
#: `round=3` у нас скругляет все 12 рёбер, а offset-трюк OpenSCAD — только
#: вертикальные, поэтому для честной сверки объёмов `round=0`.
FORMA_DSL = """
плита0 = box size=[80,60,6] center=да
h1 = cylinder radius=2.5 height=20 at=[-28,0,-6]
h2 = cylinder radius=2.5 height=20 at=[28,0,-6]
плита = difference [плита0] [h1] [h2]
check плита watertight
check плита collision
"""


def stl_stats(path: Path) -> dict:
    mesh = trimesh.load(path, force="mesh")
    volume = abs(float(mesh.volume))
    return {
        "volume_cm3": volume / 1000.0,
        "mass_g": volume / 1000.0 * DENSITY_PLA,
        "tris": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "size": [round(float(v), 2) for v in mesh.extents],
    }


def forma_stats() -> dict:
    result = build(FORMA_DSL, analyze_model=True)
    if not result.ok:
        raise SystemExit(f"ФОРМА не собрала деталь: {result.error}")
    metrics = result.analysis["metrics"]
    return {
        "volume_cm3": float(metrics["volume_cm3"]),
        "mass_g": float(metrics["mass_g"]),
        "tris": int(metrics["tris"]),
        "watertight": all(c["ok"] for c in result.analysis["checks"]
                          if c["rule"] == "watertight"),
        "size": [round(float(v), 2) for v in metrics["size"]],
        "warnings": list(result.analysis["warnings"]),
        "checks": [(c["rule"], c["ok"], c["text"]) for c in result.analysis["checks"]],
        "ms": result.timings.get("total"),
        "txt": result.analysis["text"],
    }


def main() -> None:
    hand = Path(sys.argv[1] if len(sys.argv) > 1 else "out/bracket.stl")
    exported = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    hand_stats = stl_stats(hand)
    exp_stats = stl_stats(exported) if exported and exported.exists() else None
    forma = forma_stats()

    print("=" * 92)
    print("ОДНА ДЕТАЛЬ, ДВА ИНСТРУМЕНТА")
    print("=" * 92)
    columns = ["OpenSCAD (руками)", "OpenSCAD (наш .scad)", "ФОРМА 3D"]
    print(f"{'':22s}" + "".join(f"{c:>23s}" for c in columns))
    rows = [
        ("объём, см³", hand_stats["volume_cm3"],
         exp_stats["volume_cm3"] if exp_stats else None, forma["volume_cm3"]),
        ("масса (PLA), г", hand_stats["mass_g"],
         exp_stats["mass_g"] if exp_stats else None, forma["mass_g"]),
        ("треугольников", hand_stats["tris"],
         exp_stats["tris"] if exp_stats else None, forma["tris"]),
        ("габарит, мм", "×".join(map(str, hand_stats["size"])),
         "×".join(map(str, exp_stats["size"])) if exp_stats else None,
         "×".join(map(str, forma["size"]))),
        ("замкнутость", hand_stats["watertight"],
         exp_stats["watertight"] if exp_stats else None, bool(forma["watertight"])),
    ]
    for name, left, middle, right in rows:
        if isinstance(left, float):
            mid = f"{middle:23.3f}" if middle is not None else f"{'—':>23s}"
            print(f"{name:22s} {left:22.3f}{mid} {right:16.3f}")
        else:
            mid = f"{str(middle):>23s}" if middle is not None else f"{'—':>23s}"
            print(f"{name:22s} {str(left):>22s}{mid} {str(right):>16s}")

    if exp_stats:
        # главное утверждение экспорта: перенос без потерь
        d1 = abs(exp_stats["volume_cm3"] - forma["volume_cm3"]) / forma["volume_cm3"] * 100
        d2 = abs(hand_stats["volume_cm3"] - forma["volume_cm3"]) / forma["volume_cm3"] * 100
        print(f"{'наш .scad ↔ ФОРМА':22s} {d1:21.3f}%   (перенос без потерь)")
        print(f"{'рукописный ↔ ФОРМА':22s} {d2:21.3f}%   "
              f"(разница — скругление углов в bracket.scad)")
    print(f"{'время сборки':22s} {'(STL уже готов)':>22s} {'':>23s} {str(forma['ms']) + ' мс':>16s}")
    print()
    print("Проверки и предупреждения, которых в OpenSCAD нет вовсе:")
    for rule, ok, text in forma["checks"]:
        print(f"  check {rule:12s} {'OK ' if ok else 'НЕТ'} {text}")
    for warning in forma["warnings"]:
        print(f"  предупреждение: {warning}")
    print()
    print("Отчёт ФОРМЫ (как его видит человек):")
    print(forma["txt"])


if __name__ == "__main__":
    main()
