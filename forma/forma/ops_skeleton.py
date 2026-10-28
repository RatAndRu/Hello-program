"""Команда оригинального параметрического скелета без импортируемых сеток."""
from __future__ import annotations

from .errors import DslError, GeometryError
from .geometry import normalize_color
from .model import Solid
from .ops import op


@op("skeleton_original", aliases=("original_skeleton", "скелет_параметрический"),
    category="Математические поверхности",
    summary="Строит с нуля 206 отдельных костей взрослого человека: собственные сечения, "
            "пластины, SDF-оболочки и булевы операции; готовые 3D-модели не используются.",
    example="скелет = skeleton_original height=1750 color=#d9cfb6",
    params={"height": "общий рост в мм, 1200…2200 (1750); масштабирует всю геометрию",
            "color": "цвет кости #RRGGBB (#d9cfb6)"})
def skeleton_original(a, name):
    from .skeleton_original import audit_original_skeleton, build_original_skeleton

    height = float(a.num("height", 1750.0) or 1750.0)
    if not 1200.0 <= height <= 2200.0:
        raise DslError("Рост скелета должен быть от 1200 до 2200 мм.",
                       line=a.cmd.line, command=a.cmd.text)
    base = name or a.scene.auto_name("скелет")
    color = normalize_color(a.text("color") or "#d9cfb6")
    try:
        bones = build_original_skeleton(height)
    except Exception as exc:
        if isinstance(exc, GeometryError):
            raise
        raise GeometryError(f"Не удалось построить оригинальный скелет: {exc}") from exc
    report = audit_original_skeleton(bones)
    if report["defects"]:
        raise GeometryError(f"Внутренний аудит скелета: {report['defects']}")
    object_names = []
    for index, bone in enumerate(bones, 1):
        object_name = f"{base}_{index:03d}_{bone.name}"
        object_names.append(object_name)
        a.scene.add(Solid(
            name=object_name, manifold=bone.solid, color=color, metal=0.0,
            rough=0.72, density=1.7, kind="bone", op="skeleton_original",
            line=a.cmd.line,
            meta={"title": bone.title, "division": bone.division,
                  "region": bone.region, "side": bone.side,
                  "origin": "original_parametric", "bone_index": index,
                  "smooth_normals": True},
        ))
    a.scene.groups[base] = object_names
    a.scene.log("info", f"Оригинальный скелет: 206 костей (80 осевых + 126 "
                        f"аппендикулярных), {report['triangles']:,} треугольников; "
                        "импортированные сетки не используются.".replace(",", " "), a.cmd.line)
    return None
