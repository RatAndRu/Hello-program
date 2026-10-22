"""Надписи и логотипы: команды text и emboss.

`text` создаёт самостоятельную объёмную надпись, `emboss` выдавливает её на
детали — по плоской грани или с обёртыванием вокруг цилиндра (кружка, бутылка).
Шрифт свой, векторный: без внешних файлов и без «лесенок» из пикселей.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import DslError, GeometryError
from .fonts import text_solid
from .geometry import manifold_from_arrays, manifold_mesh
from .ops import make_solid, op

PLANES = {"xy": "xy", "xz": "xz", "yz": "yz", "горизонт": "xy", "стена": "xz"}


def _anchor_bbox(a, at) -> mf.Manifold:
    bb = a.bounding_box()
    dx = float(at[0]) - (bb[0] + bb[3]) / 2.0
    dy = float(at[1]) - (bb[1] + bb[4]) / 2.0
    dz = float(at[2]) - bb[2]
    return a.translate([dx, dy, dz])


def _stand(m: mf.Manifold, plane: str) -> mf.Manifold:
    if plane == "xy":
        return m
    if plane == "xz":
        # поворот +90° вокруг X: (x, y, z) → (x, −z, y)
        rot = np.array([[1.0, 0.0, 0.0, 0.0],
                        [0.0, 0.0, -1.0, 0.0],
                        [0.0, 1.0, 0.0, 0.0]])
        return m.transform(rot)
    # yz: поворот вокруг Y: (x,y,z) → (z, y, −x)
    rot = np.array([[0.0, 0.0, 1.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [-1.0, 0.0, 0.0, 0.0]])
    return m.transform(rot)


@op("text", aliases=("текст", "надпись", "буквы", "надписать", "label", "надпись3d"),
    category="Примитивы",
    summary="Создаёт объёмную надпись своим векторным шрифтом (латиница, кириллица, "
            "цифры). Без сторонних файлов: буквы гладкие, с ровными торцами.",
    example='надпись = text "ФОРМА 3D" size=20 depth=3',
    params={"text": "текст в кавычках",
            "size": "высота заглавных букв, мм (20)",
            "depth": "толщина надписи, мм (2)",
            "weight": "толщина штриха, мм (size × 0.095)",
            "align": "left, center или right",
            "spacing": "расстояние между буквами (1.1)",
            "plane": "как стоит: xy (лежит), xz (стоит стеной), yz (сбоку)",
            "at": "положение: центр по X/Y и низ по Z"},
    positional=["text"])
def text(a, name):
    raw = a.text("text")
    if not raw:
        raise DslError("Укажите текст в кавычках.",
                       hint='Например: надпись = text "ФОРМА 3D" size=20 depth=3',
                       line=a.cmd.line, command=a.cmd.text)
    size = float(a.num("size", 20.0, minv=1.0, maxv=2000.0))
    depth = float(a.num("depth", 2.0, minv=0.2, maxv=200.0))
    weight = a.num("weight")
    align = (a.text("align", "center") or "center").lower()
    if align not in ("left", "center", "right", "лево", "центр", "право"):
        raise DslError("Выравнивание — left, center или right.",
                       line=a.cmd.line, command=a.cmd.text)
    align = {"лево": "left", "центр": "center", "право": "right"}.get(align, align)
    spacing = float(a.num("spacing", 1.1, minv=0.2, maxv=3.0))
    plane = PLANES.get((a.text("plane", "xy") or "xy").lower())
    if plane is None:
        raise DslError("Плоскость надписи — xy, xz или yz.", line=a.cmd.line, command=a.cmd.text)
    solid, width = text_solid(raw, size=size, depth=depth, weight=weight,
                              align=align, spacing=spacing)
    solid = _stand(solid, plane)
    at = a.vec("at", 3, default=[0.0, 0.0, 0.0])
    solid = _anchor_bbox(solid, at)
    out = make_solid(a.scene, name, solid, a, kind="text")
    out.notes.append(f"надпись «{raw}»")
    a.scene.log("info", f"надпись «{raw}»: ширина {width:.1f} мм, высота {size:g} мм, "
                        f"толщина {depth:g} мм", a.cmd.line)
    return out


def _wrap_text(text: mf.Manifold, radius: float, depth: float, center, angle_deg: float,
               mode: str) -> mf.Manifold:
    """Оборачивает плоскую надпись вокруг вертикальной оси Z."""
    verts, faces = manifold_mesh(text)
    if len(faces) == 0:
        raise GeometryError("Надпись пустая — нечего оборачивать.")
    cx, cy = float(center[0]), float(center[1])
    radius = float(radius)
    if radius <= max(1.0, depth):
        raise GeometryError("Радиус обёртывания слишком мал для такой толщины.",
                            hint="Увеличьте wrap= или уменьшите depth=")
    theta = verts[:, 0] / radius
    if float(np.ptp(theta)) > 2 * math.pi * 0.98:
        raise GeometryError("Надпись длиннее окружности — уменьшите size или увеличьте wrap=.")
    radial = verts[:, 2] if mode == "relief" else verts[:, 2] - depth
    r = radius + radial
    out = np.empty_like(verts)
    out[:, 0] = r * np.sin(theta)
    out[:, 1] = -r * np.cos(theta)
    out[:, 2] = verts[:, 1]
    a = math.radians(float(angle_deg))
    ca, sa = math.cos(a), math.sin(a)
    x = out[:, 0] * ca - out[:, 1] * sa
    y = out[:, 0] * sa + out[:, 1] * ca
    out[:, 0] = x + cx
    out[:, 1] = y + cy
    try:
        return manifold_from_arrays(out, faces, "надпись на цилиндре")
    except Exception as exc:
        raise GeometryError(f"Не удалось обернуть надпись: {exc}") from exc


def _face_frame(base: mf.Manifold, face: str):
    """Точка на грани и направление наружу."""
    bb = base.bounding_box()
    cx, cy, cz = ((bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2)
    table = {
        "top": ([cx, cy, bb[5]], [0.0, 0.0, 1.0]),
        "bottom": ([cx, cy, bb[2]], [0.0, 0.0, -1.0]),
        "front": ([cx, bb[1], cz], [0.0, -1.0, 0.0]),
        "back": ([cx, bb[4], cz], [0.0, 1.0, 0.0]),
        "left": ([bb[0], cy, cz], [-1.0, 0.0, 0.0]),
        "right": ([bb[3], cy, cz], [1.0, 0.0, 0.0]),
    }
    if face not in table:
        raise DslError(f"Неизвестная грань «{face}».",
                       hint="Грани: auto, top, bottom, front, back, left, right")
    return table[face]


def _rx(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    m = np.eye(3, 4)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    return m


def _rz(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    m = np.eye(3, 4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    return m


def _orient(section: mf.Manifold, face: str) -> mf.Manifold:
    """Разворачивает плоскую надпись так, чтобы толщина смотрела наружу грани."""
    if face == "top":
        return section
    if face == "bottom":
        return section.transform(_rx(180.0))
    if face == "front":
        return section.transform(_rx(90.0))
    if face == "back":
        return section.transform(_rx(-90.0)).transform(_rz(180.0))
    if face == "left":
        return section.transform(_rz(-90.0) @ _rx(90.0))
    if face == "right":
        return section.transform(_rz(90.0) @ _rx(90.0))
    raise DslError(f"Неизвестная грань «{face}».")


def _seat(placed: mf.Manifold, point, normal, at, depth: float) -> mf.Manifold:
    """Прижимает надпись к грани: снаружи или с заглублением внутрь."""
    bb = placed.bounding_box()
    shift = [0.0, 0.0, 0.0]
    for i in range(3):
        if normal[i] > 0:
            shift[i] = point[i] - bb[i]
        elif normal[i] < 0:
            shift[i] = point[i] - bb[i + 3]
        else:
            shift[i] = point[i] + float(at[i]) - (bb[i] + bb[i + 3]) / 2.0
    return placed.translate(shift)


def _cylinder_radius(m: mf.Manifold) -> float | None:
    """Радиус, если деталь в плане круглая (для авто-обёртывания надписи)."""
    bb = m.bounding_box()
    z = (bb[2] + bb[5]) / 2.0
    try:
        cs = m.slice(z)
        if cs.is_empty():
            return None
    except Exception:
        return None
    from .cuts import section_polygons
    polys = section_polygons(cs)
    if not polys:
        return None
    outer = max(polys, key=lambda p: p["area"])
    if outer["area"] <= 0:
        return None
    pts = outer["points"]
    w = float(np.ptp(pts[:, 0]))
    h = float(np.ptp(pts[:, 1]))
    if abs(w - h) > 0.15 * max(w, h):
        return None
    perimeter = float(np.sum(np.linalg.norm(np.roll(pts, -1, axis=0) - pts, axis=1)))
    if perimeter <= 1e-9:
        return None
    circularity = 4.0 * math.pi * abs(outer["area"]) / (perimeter ** 2)
    if circularity < 0.85:
        return None
    return (w + h) / 4.0


@op("emboss", aliases=("выдавить", "тиснение", "гравировка", "выгравировать", "логотип", "logo"),
    category="Форма и деформации",
    summary="Выдавливает надпись на детали или гравирует её: плоская грань либо "
            "обёртывание вокруг цилиндра (кружка, бутылка, крышка).",
    example='кружка = cup diameter=80 height=95\nкружка = emboss [кружка] text="ФОРМА" size=14 depth=0.8',
    params={"objects": "объект, на который наносится надпись",
            "text": "текст в кавычках",
            "size": "высота букв, мм (14)",
            "depth": "высота рельефа / глубина гравировки, мм (0.8)",
            "weight": "толщина штриха, мм",
            "mode": "relief (выступает) или engrave (утоплено)",
            "face": "auto, top, bottom, front, back, left, right",
            "wrap": "радиус обёртывания вокруг Z; 0 — плоская грань (авто)",
            "angle": "поворот надписи вокруг вертикали, ° (0)",
            "at": "смещение центра надписи по X/Y/Z",
            "spacing": "расстояние между буквами (1.1)"},
    positional=["objects"])
def emboss(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("emboss работает с одним объектом.",
                            hint='Например: кружка = emboss [кружка] text="ФОРМА"')
    base = solids[0]
    raw = a.text("text")
    if not raw:
        raise DslError("Укажите текст в кавычках.",
                       hint='Например: emboss [кружка] text="ФОРМА" size=14 depth=0.8',
                       line=a.cmd.line, command=a.cmd.text)
    size = float(a.num("size", 14.0, minv=1.0, maxv=1000.0))
    depth = float(a.num("depth", 0.8, minv=0.05, maxv=50.0))
    weight = a.num("weight")
    mode = (a.text("mode", "relief") or "relief").lower()
    mode = {"выступ": "relief", "выпукло": "relief", "утопить": "engrave",
            "гравировка": "engrave", "врезка": "engrave"}.get(mode, mode)
    if mode not in ("relief", "engrave"):
        raise DslError("Режим — relief (выступает) или engrave (утоплено).",
                       line=a.cmd.line, command=a.cmd.text)
    face = (a.text("face", "auto") or "auto").lower()
    spacing = float(a.num("spacing", 1.1, minv=0.2, maxv=3.0))
    angle = float(a.num("angle", 0.0, minv=-720.0, maxv=720.0))
    wrap = a.num("wrap")
    at = a.vec("at", 3, default=[0.0, 0.0, 0.0])

    section, width = text_solid(raw, size=size, depth=depth, weight=weight,
                                align="center", spacing=spacing)
    bb = base.manifold.bounding_box()
    cx, cy, cz = ((bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2)
    if wrap is None:
        auto_radius = _cylinder_radius(base.manifold) if face == "auto" else None
        wrap = (auto_radius - 0.01) if auto_radius else 0.0
    wrap = float(wrap or 0.0)

    if wrap > 0:
        if face not in ("auto", "front", "back", "left", "right"):
            raise DslError("С обёртыванием (wrap=) надпись ставится на боковую поверхность.",
                           line=a.cmd.line, command=a.cmd.text)
        z_base = float(at[2]) if a.has("at") else cz - size / 2.0
        placed = _wrap_text(section, wrap, depth, (cx + at[0], cy + at[1]), angle, mode)
        tool = placed.translate([0.0, 0.0, z_base])
        where = f"вокруг оси Z, радиус {wrap:.1f} мм, угол {angle:g}°"
    else:
        if face == "auto":
            face = "top"
        point, normal = _face_frame(base.manifold, face)
        placed = _orient(section, face)
        tool = _seat(placed, point, normal, at, depth)
        if mode == "engrave":
            tool = tool.translate([-depth * n for n in normal])
        where = f"на грани {face}"

    try:
        result = base.manifold + tool if mode == "relief" else base.manifold - tool
    except Exception as exc:
        raise GeometryError(f"Не удалось нанести надпись: {exc}",
                            hint="Проверьте, что надпись пересекается с поверхностью детали.") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После нанесения надписи деталь исчезла — уменьшите depth.",
                            hint="Попробуйте depth=0.5 и mode=engrave.")
    solid = make_solid(a.scene, name, result, a, base=base, kind="emboss")
    a.scene.consume(base)
    solid.notes.append(f"надпись «{raw}» {where}")
    a.scene.log("info", f"надпись «{raw}» {where}: {mode}, высота {size:g} мм, "
                        f"рельеф {depth:g} мм, ширина {width:.1f} мм", a.cmd.line)
    return solid
