"""FreeCAD, тест 2: та же плита, но через эскиз с ограничениями (Sketcher).

Это главное отличие FreeCAD от OpenSCAD и от ФОРМЫ: геометрия задаётся не
числами координат, а **связями** («эта сторона горизонтальна», «эта длина 80»,
«угол прямой»). Ядро решает систему и находит координаты само, а число степеней
свободы показывает, всё ли задано.

Тест отвечает на три вопроса:
  1. сколько степеней свободы осталось (FreeCAD говорит это сам);
  2. работает ли параметрическая правка — меняем одну цифру (80 → 120),
     пересчитываем и проверяем, что объём изменился ровно на ожидаемую величину;
  3. сколько времени занимает пересчёт.

Запуск (в CI):  freecadcmd plate_sketch.py
"""
from __future__ import annotations

import json
import time

import FreeCAD as App  # noqa: N813
import Part
import Sketcher

W, D, T = 80.0, 60.0, 6.0
R, HOLES = 2.5, (-28.0, 28.0)


def make_sketch(doc):
    sk = doc.addObject("Sketcher::SketchObject", "Плита")
    sk.addGeometry(Part.LineSegment(App.Vector(-W / 2, -D / 2, 0), App.Vector(W / 2, -D / 2, 0)), False)
    sk.addGeometry(Part.LineSegment(App.Vector(W / 2, -D / 2, 0), App.Vector(W / 2, D / 2, 0)), False)
    sk.addGeometry(Part.LineSegment(App.Vector(W / 2, D / 2, 0), App.Vector(-W / 2, D / 2, 0)), False)
    sk.addGeometry(Part.LineSegment(App.Vector(-W / 2, D / 2, 0), App.Vector(-W / 2, -D / 2, 0)), False)
    # связность: конец одной линии = начало следующей
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", 1))
    sk.addConstraint(Sketcher.Constraint("Vertical", 3))
    # положение на плоскости: начало координат — левый нижний угол
    sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, -W / 2))
    sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, -D / 2))
    # размеры: ширина (правим её) и высота
    width = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, W))
    sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, D))
    return sk, width


def solid_from(sk) -> "Part.Shape":
    shape = sk.Shape
    try:
        wires = shape.Wires
        wire = wires[0] if wires else Part.Wire(shape.Edges)
    except Exception:
        wire = Part.Wire(shape.Edges)
    face = Part.Face(wire)
    solid = face.extrude(App.Vector(0, 0, T))
    for x in HOLES:
        solid = solid.cut(Part.makeCylinder(R, T, App.Vector(x, 0, 0)))
    return solid


def dof_of(sk) -> dict:
    info = {"dof_known": False}
    try:
        messages = sk.solve()
        info["solver_messages"] = list(messages)[:3]
        info["dof_known"] = True
    except Exception as exc:  # noqa: BLE001
        info["solver_error"] = str(exc)
    for attr in ("FullyConstrained", "DoF", "DegreesOfFreedom"):
        if hasattr(sk, attr):
            info[attr] = getattr(sk, attr)
    return info


def main() -> None:
    t0 = time.perf_counter()
    doc = App.newDocument("plate")
    sk, width_index = make_sketch(doc)
    doc.recompute()
    shape80 = solid_from(sk)
    build_ms = (time.perf_counter() - t0) * 1000.0

    data = {
        "tool": "FreeCAD Sketcher (ограничения)",
        "tool_volume_cm3": round(float(shape80.Volume) / 1000.0, 4),
        "solids": len(shape80.Solids),
        "valid": bool(shape80.isValid()),
        "build_ms": round(build_ms, 1),
        "notes": "геометрия получена решением ограничений, а не координатами",
    }
    data.update(dof_of(sk))

    # параметрическая правка: одна цифра 80 → 120
    t1 = time.perf_counter()
    sk.setDatum(width_index, App.Units.Quantity("120.0 mm"))
    doc.recompute()
    shape120 = solid_from(sk)
    data["edit_ms"] = round((time.perf_counter() - t1) * 1000.0, 1)
    data["volume_after_edit_tool_cm3"] = round(float(shape120.Volume) / 1000.0, 4)
    # ожидание считаем в Python, независимо от CAD
    expected = (120.0 * D - 2.0 * 3.141592653589793 * R * R) * T / 1000.0
    data["expected_after_edit_cm3"] = round(expected, 4)
    data["edit_chars"] = len("120") - len("80")

    shape80.exportStl("/tmp/_sk80.stl")
    shape120.exportStl("/tmp/_sk120.stl")
    if hasattr(shape120, "exportStep"):
        shape120.exportStep("out/plate_sketch_120.step")
    print("RESULT " + json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
