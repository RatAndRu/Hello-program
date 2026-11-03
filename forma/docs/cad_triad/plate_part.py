"""FreeCAD, тест 1: та же плита, что у OpenSCAD и ФОРМЫ — через Part (CSG).

Проверяем не «красоту», а измеримые свойства:
  * объём/площадь считает сам FreeCAD (B-rep), без STL и без сторонних библиотек;
  * экспорт STEP (точная геометрия) и его повторное чтение — объём должен совпасть;
  * время построения.

Запуск (в CI):  freecadcmd plate_part.py
Итог печатается одной строкой  RESULT {json}
"""
from __future__ import annotations

import json
import os
import time

import FreeCAD as App  # noqa: N813
import Part

W, D, T = 80.0, 60.0, 6.0
HOLES = (-28.0, 28.0)
R = 2.5


def measure(shape) -> dict:
    box = shape.BoundBox
    return {
        "volume_cm3": round(float(shape.Volume) / 1000.0, 4),
        "area_cm2": round(float(shape.Area) / 100.0, 3),
        "solids": len(shape.Solids),
        "faces": len(shape.Faces),
        "edges": len(shape.Edges),
        "valid": bool(shape.isValid()),
        "watertight": bool(len(shape.Solids) == 1 and shape.isValid()),
        "size": [round(box.XLength, 2), round(box.YLength, 2), round(box.ZLength, 2)],
        "tris_est": None,
    }


def main() -> None:
    out = os.path.abspath("out")
    os.makedirs(out, exist_ok=True)

    t0 = time.perf_counter()
    plate = Part.makeBox(W, D, T, App.Vector(-W / 2, -D / 2, 0))
    for x in HOLES:
        plate = plate.cut(Part.makeCylinder(R, T, App.Vector(x, 0, 0)))
    ms = (time.perf_counter() - t0) * 1000.0

    data = measure(plate)
    data.update({"tool": "FreeCAD Part (CSG)", "build_ms": round(ms, 1),
                 "notes": "B-rep: объём и площадь считает ядро OpenCASCADE"})

    stl = os.path.join(out, "plate_freecad.stl")
    step = os.path.join(out, "plate_freecad.step")
    plate.exportStl(stl)
    try:
        plate.exportStep(step)
    except Exception as exc:  # noqa: BLE001
        data["step_error"] = str(exc)
        try:
            Part.export([plate], step)
        except Exception as exc2:  # noqa: BLE001
            data["step_error"] = f"{exc} / {exc2}"
    if os.path.exists(step):
        data["step_bytes"] = os.path.getsize(step)
        back = Part.Shape()
        back.read(step)
        data["step_roundtrip_cm3"] = round(float(back.Volume) / 1000.0, 4)

    print("RESULT " + json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
