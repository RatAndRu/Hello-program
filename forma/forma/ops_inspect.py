"""Разведка детали: сечения, пробы материала, паспорт.

Эти команды нужны не для того, чтобы «нарисовать красиво», а чтобы получить
проверяемые факты: где проходит контур, есть ли материал в точке, какие
отверстия и стенки получились. Нейросеть читает эти числа, а человек видит
разрез в окне и получает DXF/SVG для 2D-проверки.
"""

from __future__ import annotations

import math

from . import cuts
from .errors import DslError, GeometryError
from .ops import make_solid, op


def _main(scene):
    visible = scene.visible_solids()
    if not visible:
        raise GeometryError("В сцене нет видимых объектов — сначала постройте деталь.")
    return max(visible, key=lambda s: s.volume_cm3)


def _pick(a) -> list:
    if a.extra or "objects" in a.kwargs:
        return a.solids()
    return [_main(a.scene)]


def _plane_at(a) -> tuple[str, float]:
    plane = (a.text("plane", "z") or "z").strip().lower()
    if not a.has("plane"):
        # section x=… сам подсказывает плоскость
        for key in ("x", "y", "z"):
            if a.has(key):
                plane = key
                break
    aliases = {"z": "z", "xy": "z", "x": "x", "yz": "x", "y": "y", "xz": "y",
               "горизонт": "z", "вертикаль": "x"}
    plane = aliases.get(plane, plane)
    if plane not in cuts.PLANES:
        raise DslError("Плоскость сечения — z, x или y.",
                       hint="Например: section z=40", line=a.cmd.line, command=a.cmd.text)
    explicit = None
    for key in (plane, "at"):
        if a.has(key):
            explicit = float(a.num(key))
            break
    if explicit is None:
        bb = _pick(a)[0].manifold.bounding_box()
        i = cuts.axis_index(plane)
        explicit = (bb[i] + bb[i + 3]) / 2.0
    return plane, explicit


@op("section", aliases=("сечение", "разрез", "сечь", "плоскость_сечения", "2d"),
    category="Проверка",
    summary="Строит 2D-сечение детали: контуры, площадь, отверстия; пишет DXF и SVG. "
            "Разрез можно включить в сцену тонким телом, чтобы увидеть его в окне.",
    example='к = box size=[60,60,60]\nsection z=40',
    params={"objects": "объект (по умолчанию самый крупный видимый)",
            "plane": "плоскость сечения: z (горизонталь), x, y",
            "at": "координата плоскости, мм",
            "x": "координата для plane=x", "y": "координата для plane=y",
            "z": "координата для plane=z",
            "thickness": "толщина видимого среза, мм (0.4)",
            "show": "показать разрез в сцене (false)",
            "save": "записать DXF и SVG рядом с exe (true)"},
    positional=["objects"])
def section(a, name):
    solids = _pick(a)
    if len(solids) != 1:
        raise GeometryError("section строит сечение одного объекта.",
                            hint="Укажите объект: section кружка z=40")
    base = solids[0]
    plane, at = _plane_at(a)
    try:
        cs = cuts.slice_section(base.manifold, plane, at)
    except ValueError as exc:
        raise GeometryError(str(exc), hint="Проверьте координату: она должна быть внутри детали.",
                            line=a.cmd.line, command=a.cmd.text) from exc
    contours = cuts.section_polygons(cs)
    if not contours:
        raise GeometryError("В сечении нет контуров — плоскость проходит по пустоте.",
                            line=a.cmd.line, command=a.cmd.text)
    holes = [c for c in contours if c["area"] < 0]
    outer = [c for c in contours if c["area"] > 0]
    layer = f"{base.name}_{plane}{at:g}".replace(" ", "_")
    entry = {
        "object": base.name,
        "plane": plane,
        "at": round(float(at), 4),
        "layer": layer,
        "contours": [c["points"].tolist() for c in contours],
        "areas": [round(float(c["area"]), 4) for c in contours],
        "area": round(float(cs.area()), 4),
        "bbox": [round(float(v), 4) for v in cs.bounds()],
        "outer": len(outer),
        "holes": len(holes),
        "line": a.cmd.line,
    }
    a.scene.sections.append(entry)
    area_cm2 = abs(float(cs.area())) / 100.0
    holes_mm = sorted((2 * math.sqrt(abs(c["area"]) / math.pi) for c in holes), reverse=True)
    hole_text = "" if not holes else ", отверстий " + ", ".join(
        f"ø{value:.2f}" for value in holes_mm[:5]) + " мм"
    files = ""
    save = a.boolean("save", True) and not getattr(a.scene, "overrides", None)
    if save:
        try:
            from .paths import ensure_dirs
            out = ensure_dirs() / "exports"
            dxf = cuts.export_dxf([entry], out / f"{layer}.dxf")
            svg = cuts.export_svg([entry], out / f"{layer}.svg")
            entry["dxf"] = str(dxf)
            entry["svg"] = str(svg)
            files = f"; DXF/SVG: {dxf.name}, {svg.name}"
        except Exception as exc:  # запись файлов не должна ломать модель
            files = f"; файлы не записаны ({exc})"
    if a.boolean("show", False):
        thickness = float(a.num("thickness", 0.4, minv=0.05, maxv=5.0) or 0.4)
        thin = cuts.make_section_solid(cs, plane, at, thickness)
        solid = make_solid(a.scene, name or f"сечение_{len(a.scene.sections)}",
                           thin, a, base=None, kind="section")
        solid.color = "#8fd6bd"
        solid.visible = True
    a.scene.log("info",
                f"сечение {plane}={at:g}: контуров {len(contours)} "
                f"({len(outer)} внешних, {len(holes)} отверстий), площадь "
                f"{area_cm2:.2f} см²{hole_text}{files}", a.cmd.line)
    return None


@op("probe", aliases=("проба", "зонд", "точка", "материал_в_точке"), category="Проверка",
    summary="Проверяет, есть ли материал в точке, и показывает расстояние до стенки. "
            "Так проверяют полости, толщину стенок и «пустоту» внутри детали.",
    example='к = box size=[60,60,60]\nprobe x=0 y=0 z=40',
    params={"objects": "объект (по умолчанию самый крупный видимый)",
            "x": "координата X, мм (0)", "y": "координата Y, мм (0)",
            "z": "координата Z, мм (0)"},
    positional=["objects"])
def probe(a, name):
    solids = _pick(a)
    if len(solids) != 1:
        raise GeometryError("probe проверяет одну деталь.",
                            hint="Укажите объект: probe кружка x=0 y=0 z=40")
    base = solids[0]
    point = [float(a.num("x", 0.0)), float(a.num("y", 0.0)), float(a.num("z", 0.0))]
    info = cuts.point_info(base.manifold, point)
    entry = {"object": base.name, "point": [round(v, 3) for v in point], **info,
             "line": a.cmd.line}
    a.scene.probes.append(entry)
    if info.get("outside_bbox"):
        a.scene.log("info",
                    f"проба ({point[0]:g}, {point[1]:g}, {point[2]:g}): вне габаритов детали — "
                    "материала нет", a.cmd.line)
    elif info["inside"]:
        dist = info.get("distance")
        extra = "" if dist is None else (
            f", на поверхности" if info.get("on_surface") else f", до стенки {dist:.2f} мм")
        a.scene.log("info",
                    f"проба ({point[0]:g}, {point[1]:g}, {point[2]:g}): материал есть{extra}",
                    a.cmd.line)
    else:
        dist = info.get("distance")
        extra = "" if dist is None else f", до стенки {dist:.2f} мм"
        a.scene.log("info",
                    f"проба ({point[0]:g}, {point[1]:g}, {point[2]:g}): пусто{extra}",
                    a.cmd.line)
    return None


@op("passport", aliases=("паспорт", "паспорт_детали", "карточка"), category="Проверка",
    summary="Печатает паспорт детали: габариты, центр, массу, минимальную стенку и "
            "найденные отверстия — факты, по которым можно проверять модель.",
    example='кружка = cup diameter=80 height=95\npassport кружка',
    params={"objects": "объект (по умолчанию самый крупный видимый)"},
    positional=["objects"])
def passport(a, name):
    from .metrics import detail_passport
    solids = _pick(a)
    out = []
    for solid in solids:
        data = detail_passport(solid)
        out.append(data)
        fmt = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")  # noqa: E731
        size = data["size"]
        a.scene.log("info",
                    f"ПАСПОРТ {solid.name}: {fmt(size[0])}×{fmt(size[1])}×{fmt(size[2])} мм, "
                    f"центр ({fmt(data['center'][0])}, {fmt(data['center'][1])}, "
                    f"{fmt(data['center'][2])}), {fmt(data['volume_cm3'])} см³, "
                    f"{fmt(data['mass_g'])} г", a.cmd.line)
        wall = data.get("wall")
        if wall:
            a.scene.log("info",
                        f"  минимальная стенка: {fmt(wall['min'])} мм "
                        f"(медиана {fmt(wall['median'])}), отверстий: {len(data['holes'])}",
                        a.cmd.line)
        else:
            a.scene.log("info",
                        f"  деталь сплошная (полостей нет), отверстий: {len(data['holes'])}",
                        a.cmd.line)
        for hole in data["holes"][:6]:
            kind = "сквозное" if hole["through"] else "глухое"
            a.scene.log("info",
                        f"  отверстие ø{fmt(hole['diameter'])} мм в точке "
                        f"({fmt(hole['x'])}, {fmt(hole['y'])}), {kind}", a.cmd.line)
    a.scene.passports = out
    return None
