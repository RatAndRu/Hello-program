"""Сравнение: одна и та же деталь в OpenSCAD и в DSL ФОРМЫ.

Запускается в CI после того, как OpenSCAD отрендерил `bracket.scad` в STL.
Считает по STL объём, массу и треугольники (OpenSCAD сам этого не умеет),
затем строит ту же деталь через `forma.run.build` и печатает обе строки.

    python compare.py out/bracket.stl

Печатает таблицу в stdout — её видно в логе GitHub Actions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # форма/ — корень пакета
from forma.run import build  # noqa: E402

DENSITY_PLA = 1.24  # г/см³

#: та же деталь на DSL ФОРМЫ. Отверстия вычтены как цилиндры; скругление
#: углов радиусом 3 мм сделано примитивом `round` у коробки.
FORMA_DSL = """
плита0 = box size=[80,60,6] center=да round=3
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
        "bounds_z": [round(float(v), 2) for v in (mesh.bounds[0][2], mesh.bounds[1][2])],
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
    stl = Path(sys.argv[1] if len(sys.argv) > 1 else "out/bracket.stl")
    a = stl_stats(stl)
    b = forma_stats()

    print("=" * 78)
    print("ОДНА ДЕТАЛЬ, ДВА ИНСТРУМЕНТА")
    print("=" * 78)
    head = f"{'':22s} {'OpenSCAD + trimesh':>22s} {'ФОРМА 3D':>16s}"
    print(head)
    rows = [
        ("объём, см³", a["volume_cm3"], b["volume_cm3"]),
        ("масса (PLA), г", a["mass_g"], b["mass_g"]),
        ("треугольников", a["tris"], b["tris"]),
        ("габарит, мм", "×".join(map(str, a["size"])), "×".join(map(str, b["size"]))),
        ("замкнутость", a["watertight"], bool(b["watertight"])),
    ]
    for name, left, right in rows:
        if isinstance(left, float):
            print(f"{name:22s} {left:22.3f} {right:16.3f}")
        else:
            print(f"{name:22s} {str(left):>22s} {str(right):>16s}")

    delta = abs(a["volume_cm3"] - b["volume_cm3"]) / max(a["volume_cm3"], 1e-9) * 100
    print(f"{'расхождение объёма':22s} {delta:21.2f}%")
    print(f"{'время сборки':22s} {'(STL уже готов)':>22s} {str(b['ms']) + ' мс':>16s}")
    print()
    print("Проверки и предупреждения, которых в OpenSCAD нет вовсе:")
    for rule, ok, text in b["checks"]:
        print(f"  check {rule:12s} {'OK ' if ok else 'НЕТ'} {text}")
    for warning in b["warnings"]:
        print(f"  предупреждение: {warning}")
    print()
    print("Отчёт ФОРМЫ (как его видит человек):")
    print(b["txt"])


if __name__ == "__main__":
    main()
