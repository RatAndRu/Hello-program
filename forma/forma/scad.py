"""Нативный Forma → OpenSCAD mesh export.

Экспортируется построенная геометрия (triangulated Manifold), а не выдуманное
параметрическое дерево. Полученный .scad можно открыть/обработать настоящим
OpenSCAD; обратный параметрический round-trip этот формат не обещает.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable

from .errors import GeometryError
from .geometry import manifold_mesh


def _number(value: float, precision: int) -> str:
    value = float(value)
    if not math.isfinite(value):
        raise GeometryError("SCAD export: координата не является конечным числом.")
    if abs(value) < 0.5 * 10 ** (-(precision - 2)):
        value = 0.0
    return format(value, f".{int(precision)}g")


def _identifier(value: str, index: int) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_]", "_", str(value or "")).strip("_")
    if not candidate or candidate[0].isdigit():
        candidate = f"object_{index}"
    return f"forma_{candidate}"


def _as_solids(solids) -> list:
    if hasattr(solids, "manifold"):
        return [solids]
    return list(solids)


def scad_manifest(solids, source: str = "") -> dict:
    rows = []
    for index, solid in enumerate(_as_solids(solids), start=1):
        passport = (getattr(solid, "meta", None) or {}).get("provenance") or {}
        rows.append({
            "index": index,
            "name": solid.name,
            "operation": solid.op or passport.get("operation") or "solid",
            "line": int(solid.line or passport.get("line") or 0),
            "parents": list(passport.get("parents") or []),
            "module": (getattr(solid, "meta", None) or {}).get("module"),
            "units": "mm",
        })
    return {
        "format": "OpenSCAD polyhedron mesh",
        "source": source,
        "objects": rows,
        "parametric_roundtrip": False,
        "note": "Сетка уже построена; исходные выражения и зависимости не восстанавливаются.",
    }


def scad_polyhedron(solid, name: str | None = None, precision: int = 12,
                    index: int = 1) -> str:
    """Возвращает один module с настоящими points/faces из manifold."""
    if not 6 <= int(precision) <= 17:
        raise ValueError("SCAD precision должно быть целым от 6 до 17 знаков.")
    vertices, faces = manifold_mesh(solid.manifold)
    if len(vertices) == 0 or len(faces) == 0:
        raise GeometryError(f"SCAD export: объект «{solid.name}» пуст.")
    identifier = _identifier(name or solid.name, index)
    passport = (getattr(solid, "meta", None) or {}).get("provenance") or {}
    parents = ", ".join(passport.get("parents") or [])
    lines = [
        f"// object: {solid.name}",
        f"// operation: {solid.op or passport.get('operation') or 'solid'}; "
        f"line: {int(solid.line or passport.get('line') or 0)}"
        + (f"; parents: {parents}" if parents else ""),
        f"module {identifier}() {{",
        "  polyhedron(",
        "    points=[", 
    ]
    for vertex in vertices:
        lines.append("      [" + ", ".join(_number(v, precision) for v in vertex[:3]) + "],")
    lines += ["    ],", "    faces=["]
    for face in faces:
        if len(face) < 3:
            continue
        lines.append("      [" + ", ".join(str(int(v)) for v in face) + "],")
    lines += ["    ],", "    convexity = 10", "  );", "}", ""]
    return "\n".join(lines)


def export_scad(solids, path: str | Path | None = None, *, precision: int = 12,
                source: str = "") -> str | Path:
    """Экспортирует все visible Solid в один .scad.

    Без ``path`` возвращает текст; с ``path`` записывает UTF-8 и возвращает
    Path. Это удобно и API, и CLI, и не заставляет вызывать внешний CAD.
    """
    items = _as_solids(solids)
    if not items:
        raise GeometryError("SCAD export: нет видимых объектов.")
    chunks = [
        "// Forma native mesh export; units: mm",
        "// Geometry is already evaluated; this is not a parametric round-trip.",
        "// Use the headless openscad command in Forma for arbitrary SCAD/BOSL2 input.",
        "",
    ]
    used_identifiers: set[str] = set()
    for index, solid in enumerate(items, start=1):
        # Имена Forma могут отличаться только символами, которые SCAD не
        # разрешает в идентификаторе. Не создаём два одинаковых module.
        export_name = solid.name
        identifier = _identifier(export_name, index)
        suffix = index
        while identifier in used_identifiers:
            export_name = f"{solid.name}_{suffix}"
            identifier = _identifier(export_name, index)
            suffix += 1
        used_identifiers.add(identifier)
        chunks.append(scad_polyhedron(solid, name=export_name, precision=precision, index=index))
        chunks.append(f"{identifier}();")
        chunks.append("")
    text = "\n".join(chunks)
    if path is None:
        return text
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def export_scad_bytes(solids, *, precision: int = 12, source: str = "") -> bytes:
    return str(export_scad(solids, precision=precision, source=source)).encode("utf-8")


# Совместимые короткие имена для скриптов/внешних адаптеров.
solid_to_scad = scad_polyhedron
