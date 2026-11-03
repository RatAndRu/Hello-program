"""DSL-команда openscad: внешний расчёт без выхода пользователя из Forma."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .errors import DslError, GeometryError
from .geometry import manifold_from_arrays
from .openscad import OpenSCADRunner
from .ops import make_solid, op
from .ops_io import resolve_file, weld_mesh


def scad_solid(a, name, source, *, scale: float = 1.0):
    runner = OpenSCADRunner(
        executable=a.text("executable", None),
        library_paths=_library_paths(a),
        timeout=float(a.num("timeout", 120.0, minv=0.1) or 120.0),
    )
    defines = _defines(a)
    result = runner.run(source, output_format=a.text("format", "stl") or "stl", defines=defines)
    for warning in result.warnings:
        a.scene.log("warn", f"OpenSCAD: {warning}", a.cmd.line)
    if not result.ok:
        error = result.error or {}
        raise GeometryError(error.get("message", "OpenSCAD не построил модель."),
                            hint=error.get("hint"), line=a.cmd.line, command=a.cmd.text)
    vertices, faces = result.vertices, result.faces
    if scale != 1.0:
        vertices = vertices * float(scale)
    at = a.vec("pos", 3, default=(0, 0, 0)) if a.has("pos") else a.vec("at", 3, default=(0, 0, 0))
    vertices = vertices + np.asarray(at, dtype=float)
    try:
        manifold = manifold_from_arrays(vertices, faces, what="OpenSCAD mesh")
    except GeometryError:
        if not a.boolean("repair", False):
            raise
        welded = weld_mesh(vertices, faces)
        if welded is None:
            raise
        manifold = manifold_from_arrays(welded[0], welded[1], what="OpenSCAD mesh (repair)")
    solid = make_solid(a.scene, name, manifold, a, kind="openscad")
    solid.meta["openscad"] = result.payload()
    solid.meta["source_file"] = result.source
    a.scene.log("info", f"OpenSCAD: {len(faces)} треугольников, "
                f"{result.duration_ms:.0f} мс; внешнее GUI не открывалось", a.cmd.line)
    return solid


def _library_paths(a) -> list[str]:
    raw = a.value("libraries", None)
    if raw is None:
        raw = a.value("library", None)
    if raw is None:
        return []
    if isinstance(raw, str):
        return [item for item in raw.split(";") if item.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    raise DslError("openscad.libraries должен быть путём или списком путей.",
                   line=a.cmd.line)


def _defines(a) -> dict:
    raw = a.value("define", None)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        result = {}
        for item in raw.split(","):
            if "=" not in item:
                raise DslError("openscad.define: ожидается name=value.", line=a.cmd.line)
            key, value = item.split("=", 1)
            result[key.strip()] = value.strip()
        return result
    raise DslError("openscad.define: ожидается name=value или объект.", line=a.cmd.line)


@op("openscad", aliases=("scad", "open_scad", "опенскад"), category="Сцена и материал",
    summary="Исполняет произвольный SCAD/BOSL2 настоящим OpenSCAD в фоне и возвращает mesh.",
    example="detail = openscad file=\"detail.scad\"\n"
            "bosl = openscad code=\"include <BOSL2/std.scad>\\ncube(10);\" libraries=\"/path/BOSL2\"",
    params={"target": "имя объекта", "file": "SCAD-файл", "code": "SCAD-текст",
            "libraries": "pinned-каталоги библиотек (OPENSCADPATH)",
            "define": "name=value через запятую", "format": "stl, 3mf, off или obj",
            "timeout": "лимит секунд (120)", "repair": "сварить швы при необходимости",
            "pos": "смещение [x,y,z]", "executable": "путь к OpenSCAD (обычно не нужен)"},
    positional=["target"])
def openscad(a, name):
    source = a.text("file", None)
    code = a.text("code", None)
    if source and code:
        raise DslError("openscad: укажите file=… или code=…, не оба.", line=a.cmd.line)
    if source:
        path = resolve_file(source, base_dir=getattr(a.scene, "base_dir", None))
        if path.suffix.lower() != ".scad":
            raise DslError("openscad.file должен иметь расширение .scad.", line=a.cmd.line)
        source = str(path)
    elif code:
        source = code.replace("\\n", "\n")
    else:
        raise DslError("Укажите SCAD: detail = openscad file=\"detail.scad\".",
                       hint="Для BOSL2 передайте libraries=…; Forma не интерпретирует SCAD сама.",
                       line=a.cmd.line)
    target = a.text("target") or name or a.scene.auto_name("openscad")
    return scad_solid(a, target, source)
