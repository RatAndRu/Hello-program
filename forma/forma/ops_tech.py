"""Технологические элементы: резьба и уклоны (draft).

Резьба строится честной винтовой поверхностью: треугольный профиль ведётся
по спирали и сплавляется со стержнем. Так получается и болт, и гайка, и
горлышко бутылки — без «нарисованных полосок».
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, manifold_mesh
from .ops import make_solid, op


def _helix_ridge(radius: float, length: float, pitch: float, depth: float,
                 width: float, steps_per_turn: int = 48, right: bool = True,
                 inset: float = 0.8, fade: float = 0.0,
                 fade_top: float | None = None) -> mf.Manifold:
    """Винтовой гребень; fade/fade_top задают затухание внизу/вверху.

    Без fade_top сохраняется прежнее симметричное поведение. Нулевой
    fade_top нужен саморезу без шейки: резьба доходит до головки целиком.
    """
    if pitch <= 1e-6 or length <= 1e-6:
        raise GeometryError("Шаг и длина резьбы должны быть положительными.")
    if width > 0.9 * pitch:
        width = 0.9 * pitch
    turns = length / pitch
    steps = max(12, min(int(turns * steps_per_turn) + 1, 40000))
    profile = [(-inset, -width / 2.0), (depth, 0.0), (-inset, width / 2.0)]
    sign = 1.0 if right else -1.0
    top_fade = fade if fade_top is None else max(0.0, float(fade_top))
    verts = []
    for i in range(steps):
        t = i / (steps - 1)
        theta = sign * 2.0 * math.pi * turns * t
        z = t * length
        c, s = math.cos(theta), math.sin(theta)
        factor = 1.0
        if fade > 1e-9 or top_fade > 1e-9:
            u = 1.0
            if fade > 1e-9:
                u = min(u, t * length / fade)
            if top_fade > 1e-9:
                u = min(u, (1.0 - t) * length / top_fade)
            u = max(0.02, u)
            factor = u * u * (3.0 - 2.0 * u)
        for dr, dz in profile:
            r = radius + dr * factor
            verts.append((r * c, r * s, z + dz * factor))
    verts = np.asarray(verts, dtype=np.float64)
    faces = []
    n = len(profile)
    for i in range(steps - 1):
        base0 = i * n
        base1 = (i + 1) * n
        for j in range(n):
            j2 = (j + 1) % n
            a, b = base0 + j, base0 + j2
            c, d = base1 + j2, base1 + j
            faces.append((a, b, c))
            faces.append((a, c, d))
    # торцы
    last = (steps - 1) * n
    faces.append(tuple(range(n - 1, -1, -1)))
    faces.append(tuple(last + j for j in range(n)))
    faces = np.asarray(faces, dtype=np.int64)
    try:
        ridge = manifold_from_arrays(verts, faces, "резьба")
    except GeometryError:
        # обратный обход граней (винтовая поверхность чувствительна к знаку)
        ridge = manifold_from_arrays(verts, faces[:, ::-1], "резьба")
    if not right:
        return ridge
    return ridge


@op("thread", aliases=("резьба", "нарезка", "винт", "bolt"), category="Форма и деформации",
    summary="Строит настоящую винтовую резьбу: стержень с витками или гайку с "
            "внутренней резьбой. Витки плавные, шаг и глубина задаются.",
    example="болт = thread diameter=10 length=24 pitch=1.5",
    params={"objects": "готовый цилиндр (необязательно)",
            "diameter": "наружный диаметр, мм (10)",
            "length": "длина резьбы, мм (20)",
            "pitch": "шаг резьбы, мм (1.5)",
            "depth": "глубина витка, мм (0.6 × шаг)",
            "internal": "внутренняя резьба — гайка (false)",
            "right": "правая резьба (true)"},
    positional=["objects"])
def thread(a, name):
    has_obj = bool(a.extra or "objects" in a.kwargs)
    base = a.solids()[0] if has_obj else None
    internal = a.boolean("internal", False)
    right = a.boolean("right", True)
    if base is not None:
        bb = base.manifold.bounding_box()
        size = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
        diameter = float(a.num("diameter", max(size[0], size[1])))
        length = float(a.num("length", size[2]))
        z0 = bb[2]
        cx, cy = (bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2
    else:
        diameter = float(a.num("diameter", 10.0, minv=1.0, maxv=4000.0))
        length = float(a.num("length", 20.0, minv=1.0, maxv=4000.0))
        z0, cx, cy = 0.0, 0.0, 0.0
    pitch = float(a.num("pitch", max(0.5, diameter * 0.15), minv=0.1, maxv=200.0))
    depth = float(a.num("depth", min(1.2, max(0.2, pitch * 0.6)), minv=0.05, maxv=50.0))
    if depth * 2.2 >= diameter:
        raise GeometryError("Виток глубже стержня — уменьшите depth или увеличьте diameter.")
    radius = diameter / 2.0
    core = radius - depth
    ridge = _helix_ridge(core, length, pitch, depth, min(pitch * 0.62, 2.4),
                         right=right, inset=0.6)
    ridge = ridge.translate([cx, cy, z0])
    if internal:
        bore = mf.Manifold.cylinder(length + 0.4, core, core, 96).translate(
            [cx, cy, z0 - 0.2])
        if base is None:
            outer = mf.Manifold.cylinder(length, radius, radius, 96).translate([cx, cy, z0])
            result = outer - bore - ridge
        else:
            result = (base.manifold - bore - ridge)
    else:
        core_solid = mf.Manifold.cylinder(length, core, core, 96).translate([cx, cy, z0])
        result = core_solid + ridge
        if base is not None:
            result = base.manifold + result
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("Резьба получилась пустой — проверьте диаметр и глубину.")
    solid = make_solid(a.scene, name, result, a, base=base, kind="thread")
    if base is not None:
        a.scene.consume(base)
    solid.notes.append(f"резьба Ø{diameter:g}×{pitch:g}, длина {length:g} мм")
    a.scene.log("info", f"резьба: Ø{diameter:g} мм, шаг {pitch:g} мм, глубина {depth:g} мм, "
                        f"длина {length:g} мм, {'внутренняя' if internal else 'наружная'}",
                a.cmd.line)
    return solid


@op("draft", aliases=("уклон", "конусность", "технологический_уклон"), category="Форма и деформации",
    summary="Строит технологический уклон: стенки сужаются кверху (или книзу), "
            "чтобы деталь вынималась из формы и печаталась устойчиво.",
    example='корпус = box size=[60,60,80]\nкорпус = draft [корпус] angle=2',
    params={"objects": "объект", "angle": "угол уклона, ° (2)",
            "axis": "направление сужения: +z (кверху) или -z",
            "keep": "сохранить исходный объект (false)"},
    positional=["objects"])
def draft(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("draft работает с одним объектом.",
                            hint="Например: корпус = draft [корпус] angle=2")
    base = solids[0]
    angle = float(a.num("angle", 2.0, minv=0.1, maxv=45.0))
    axis = (a.text("axis", "+z") or "+z").strip().lower()
    up = axis not in ("-z", "z-", "вниз", "книзу")
    bb = base.manifold.bounding_box()
    cx, cy = (bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2
    height = bb[5] - bb[2]
    if height <= 1e-6:
        raise GeometryError("У детали нет высоты — уклон не нужен.")
    radius = max(bb[3] - bb[0], bb[4] - bb[1]) / 2.0
    slope = math.tan(math.radians(angle))
    verts, faces = manifold_mesh(base.manifold)
    z_rel = (verts[:, 2] - bb[2]) / height
    if not up:
        z_rel = 1.0 - z_rel
    factor = 1.0 - slope * (z_rel * height) / max(radius, 1e-6)
    factor = np.clip(factor, 0.25, 1.0)
    out = verts.copy()
    out[:, 0] = cx + (verts[:, 0] - cx) * factor
    out[:, 1] = cy + (verts[:, 1] - cy) * factor
    try:
        result = manifold_from_arrays(out, faces, "уклон")
    except GeometryError as exc:
        raise GeometryError(f"Не удалось построить уклон: {exc}",
                            hint="Уменьшите angle (например, 1.5) или упростите деталь.") from exc
    solid = make_solid(a.scene, name, result, a, base=base, kind="draft")
    a.scene.consume(base)
    solid.notes.append(f"уклон {angle:g}° {'кверху' if up else 'книзу'}")
    a.scene.log("info", f"уклон {angle:g}° {'кверху' if up else 'книзу'}: "
                        f"сужение {slope * height:.2f} мм на высоте {height:.1f} мм", a.cmd.line)
    return solid
