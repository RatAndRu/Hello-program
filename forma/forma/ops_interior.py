"""Редактируемые интерьерные сборки, ткань и пакетный анализ пересечений.

Составные команды создают обычные тела с именами ``root.child``. Корень двигает
всю сборку существующим механизмом ``_parts_follow``; вложенный корень вроде
``door.leaf`` двигает только полотно и его фурнитуру. Никакие детали не требуют
обязательного boolean-объединения и остаются доступны для дальнейшей правки.
"""
from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from . import cloth
from .cloth_check import self_intersections, surface_intersections
from .errors import GeometryError
from .geometry import (manifold_from_arrays, manifold_mesh, normalize_color,
                       pattern_shape)
from .ops import make_solid, op
from .ops_kit import _profile, _rect_profile, _revolve_profile, _tube_mesh
from .shape_features import rounded_extrude


def _color(a, key, default):
    return normalize_color(a.text(key, default) or default)


def _box(size, center=(0, 0, 0), round_r=0.0):
    sx, sy, sz = [float(v) for v in size]
    if min(sx, sy, sz) <= 0:
        raise GeometryError("Размеры блока должны быть положительными.")
    if round_r > 1e-6:
        r = min(float(round_r), min(sx, sy, sz) * 0.45)
        cross = mf.CrossSection([_rect_profile(sx, sy, 0.0)])
        solid = rounded_extrude(cross, sz, r, "интерьерный блок", 16)
        solid = solid.translate((0, 0, -sz / 2))
    else:
        solid = mf.Manifold.cube((sx, sy, sz), True)
    return solid.translate(tuple(float(v) for v in center))


def _cylinder(radius, height, at=(0, 0, 0), r2=None, segments=48):
    solid = mf.Manifold.cylinder(float(height), float(radius),
                                 float(radius if r2 is None else r2), int(segments))
    return solid.translate(tuple(float(v) for v in at))


def _rotation_to(direction):
    target = np.asarray(direction, dtype=float)
    target /= max(float(np.linalg.norm(target)), 1e-12)
    source = np.asarray([0.0, 0.0, 1.0])
    cross = np.cross(source, target)
    dot = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if np.linalg.norm(cross) < 1e-10:
        return np.eye(3) if dot > 0 else np.diag([1.0, -1.0, -1.0])
    skew = np.asarray([[0.0, -cross[2], cross[1]],
                       [cross[2], 0.0, -cross[0]],
                       [-cross[1], cross[0], 0.0]])
    return np.eye(3) + skew + skew @ skew * ((1.0 - dot) /
                                           max(float(np.dot(cross, cross)), 1e-12))


def _between(p0, p1, radius, r2=None, segments=32):
    p0, p1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
    direction = p1 - p0
    length = float(np.linalg.norm(direction))
    if length < 1e-6:
        raise GeometryError("Нулевая длина элемента.")
    solid = mf.Manifold.cylinder(length, float(radius),
                                 float(radius if r2 is None else r2), int(segments))
    matrix = np.eye(3, 4)
    matrix[:, :3] = _rotation_to(direction)
    matrix[:, 3] = p0
    return solid.transform(np.ascontiguousarray(matrix))


def _ellipse(width, length, segments=96):
    return [(width * 0.5 * math.cos(2 * math.pi * i / segments),
             length * 0.5 * math.sin(2 * math.pi * i / segments))
            for i in range(segments)]


def _outline(shape, width, length, corner=0.0):
    if shape == "ellipse":
        return _ellipse(width, length)
    return _rect_profile(width, length, corner, 10)


def _emit(a, name, parts, params=None):
    """Размещает и регистрирует сборку; первый элемент становится корнем."""
    if not parts:
        raise GeometryError("Пустая интерьерная сборка.")
    shift = np.asarray(a.vec("at", 3, default=(0, 0, 0)), dtype=float)
    if a.boolean("center", False):
        bounds = [part[1].bounding_box() for part in parts]
        lo = min(float(b[2]) for b in bounds)
        hi = max(float(b[5]) for b in bounds)
        shift[2] -= (lo + hi) * 0.5
    root = None
    for index, part in enumerate(parts):
        suffix, manifold, color, kind, style = part
        if np.any(np.abs(shift) > 1e-12):
            manifold = manifold.translate(tuple(shift))
        part_name = name if index == 0 else f"{name}{suffix}"
        made = make_solid(a.scene, part_name, manifold, a,
                          base=root, kind=kind)
        made.color = color
        for key, value in (style or {}).items():
            setattr(made, key, value)
        made.meta["assembly_root"] = name
        if index:
            made.meta["parent"] = name
        if index == 0:
            root = made
    if root is None:
        raise GeometryError("Не удалось создать корень сборки.")
    root.meta["interior_params"] = params or {}
    return root


def _ready_handle(form: str, cfg: dict, segments: int, blend: float,
                  resolution: float | None, hand: str = "право"):
    """Геометрия готовой door_handle, центрированная на оси крепления.

    Используется дверью и окном: здесь нет второй упрощённой реализации
    рычага. Возвращаются все части (включая замок), нормализованные так, что
    ось ручки находится в (0,0,0), задняя плоскость — на y=0, вынос — в −Y.
    """
    from .ops_fittings import _handle_sdf

    main, extras, actual_resolution, _join, _estimate = _handle_sdf(
        form, cfg, segments, blend, resolution)
    items = [("", main), *extras]
    if hand in ("лево", "левый", "left"):
        items = [(suffix, part.mirror((-1.0, 0.0, 0.0))) for suffix, part in items]
    min_z = min(float(part.bounding_box()[2]) for _, part in items)
    is_knob = form in ("сферическая", "дисковая")
    axis_before_shift = max(cfg["rosette_h"] * 0.5 if cfg["rosette"] != "нет" else 0.0,
                            cfg["knob_d"] * 0.5 if is_knob else cfg["lever_d"])
    axis_z = axis_before_shift - min_z
    normalized = [(suffix, part.translate((0.0, 0.0, -axis_z))) for suffix, part in items]
    return normalized, actual_resolution


def _targets(a):
    value = a.value("objects")
    if value is None or value == "":
        return [s for s in a.scene.objects.values() if s.visible]
    values = list(value) if isinstance(value, (list, tuple)) else [value]
    out = []
    for item in values:
        if isinstance(item, str) and item.strip() in a.scene.groups:
            members = a.scene.expand(item.strip())
        else:
            members = [a.scene.resolve(item)]
        for solid in members:
            if solid not in out:
                out.append(solid)
    return out


@op("interference", aliases=("пересечения", "коллизии", "collision_report"),
    category="Проверка",
    summary="Пакетный отчёт пересечений: AABB-отбор, точный объём Manifold, "
            "разрешённые пары и пропуск деталей одной составной сборки.",
    example='interference tolerance=0.01 allow="door.*:wall,table.*:floor"',
    params={"objects": "объекты, список или группа; по умолчанию все видимые",
            "tolerance": "минимальный объём пересечения, мм³ (0.01)",
            "allow": "разрешённые пары a:b,c:d; допустимы маски door.*:wall",
            "parts": "нет — пропускать детали с одним корнем имени (по умолчанию)",
            "limit": "максимум пар в отчёте (100)"},
    positional=["objects"])
def interference(a, name):
    from .collide import merge_allow, scan_pairs

    solids = [s for s in _targets(a) if s.visible]
    tolerance = float(a.num("tolerance", 0.01, minv=0.0) or 0.0)
    allow = a.text("allow", "") or ""
    skip_parts = not a.boolean("parts", False)
    limit = int(a.num("limit", 100, minv=1, maxv=10000) or 100)
    pairs, stats = scan_pairs(solids, tolerance=tolerance, allow=allow,
                              skip_parts=skip_parts, limit=limit)
    report = {"objects": stats["objects"], "candidates": stats["candidates"],
              "pairs": pairs, "count": stats["matched"],
              "allowed": stats["allowed"], "skipped_parts": stats["skipped_parts"],
              "truncated": stats["truncated"], "tolerance": tolerance,
              "line": a.cmd.line, "ok": not pairs}
    reports = list(getattr(a.scene, "interferences", []) or [])
    reports.append(report)
    a.scene.interferences = reports
    if allow:
        # Разрешение — не только фильтр этого отчёта, но и явно записанное
        # исключение для автоматического анализа и последующих check-правил.
        # Сам отчёт выше по-прежнему зависит только от своих аргументов.
        combined_allow = merge_allow(getattr(a.scene, "collision_allow", []), allow)
        a.scene.collision_allow = combined_allow.split(",") if combined_allow else []
    level = "warn" if pairs else "info"
    a.scene.log(level, f"interference: объектов {report['objects']}, "
                       f"кандидатов {report['candidates']}, "
                       f"пересечений {report['count']}, разрешено {report['allowed']}",
                a.cmd.line)
    for pair in pairs[:10]:
        a.scene.log("warn", f"  {pair['a']} ↔ {pair['b']}: "
                            f"{pair['volume_mm3']:g} мм³", a.cmd.line)
    if stats["truncated"]:
        a.scene.log("warn", f"  ещё {stats['truncated']} пар скрыто limit={limit}", a.cmd.line)
    return None


@op("table", aliases=("стол", "столик"), category="Примитивы",
    summary="Редактируемый стол: отдельные столешница, ножки и полка; форма, "
            "число и раскладка ножек, конусность, разнос и пользовательские детали.",
    example='стол = table width=180 length=100 height=75 shape=rounded corner=10 '
            'legs=4 layout=inset leg_shape=tapered splay=4 shelf=да',
    params={"objects": "одна пользовательская столешница [top] (то же, что top_object)",
            "width": "ширина столешницы X, мм (180)",
            "length": "глубина столешницы Y, мм (100)",
            "height": "общая высота, мм (75)", "thickness": "толщина столешницы (5)",
            "shape": "rect, rounded или ellipse", "corner": "радиус углов контура (8)",
            "round": "скругление кромки столешницы (0.8)",
            "legs": "число ножек (4)", "layout": "corners, inset, circle или pedestal",
            "inset": "отступ ножек от края (12)", "leg_shape": "round, square или tapered",
            "leg_radius": "радиус/половина сечения ножки (4)",
            "taper": "доля радиуса нижнего конца (0.65)",
            "splay": "разнос нижних концов наружу, градусы (0)",
            "shelf": "да — нижняя полка", "shelf_height": "высота низа полки (20)",
            "shelf_scale": "размер полки относительно столешницы (0.9)",
            "top_object": "имя пользовательской столешницы",
            "leg_object": "имя пользовательской ножки-прототипа",
            "top_color": "цвет столешницы", "leg_color": "цвет ножек",
            "shelf_color": "цвет нижней полки (по умолчанию как столешница)",
            "at": "положение сборки", "center": "центрировать по высоте"},
    positional=["objects"])
def table(a, name):
    width = float(a.num("width", 180.0, minv=10.0))
    length = float(a.num("length", 100.0, minv=10.0))
    height = float(a.num("height", 75.0, minv=5.0))
    thickness = float(a.num("thickness", 5.0, minv=0.3, maxv=height * 0.8))
    shape_raw = (a.text("shape", "rounded") or "rounded").lower()
    shape = {"rect": "rect", "прямоугольник": "rect", "rounded": "rounded",
             "скруглённый": "rounded", "скругленный": "rounded",
             "ellipse": "ellipse", "овал": "ellipse", "овальный": "ellipse"}.get(shape_raw)
    if shape is None:
        raise GeometryError("table: shape=rect, rounded или ellipse.")
    corner = float(a.num("corner", 8.0, minv=0.0) or 0.0) if shape == "rounded" else 0.0
    edge = float(a.num("round", 0.8, minv=0.0) or 0.0)
    top_name = (a.text("top_object") or "").strip()
    objects = a.value("objects")
    if not top_name and isinstance(objects, str):
        top_name = objects.strip()
    elif not top_name and isinstance(objects, (list, tuple)) and objects:
        if len(objects) != 1:
            raise GeometryError("table: позиционно передаётся одна столешница, [top].")
        top_name = str(objects[0]).strip()
    custom_top = a.scene.resolve(top_name) if top_name else None
    if custom_top:
        top = custom_top.manifold
        bb = top.bounding_box()
        if not a.has("width"):
            width = bb[3] - bb[0]
        if not a.has("length"):
            length = bb[4] - bb[1]
        if not a.has("thickness"):
            thickness = bb[5] - bb[2]
        top = top.translate((-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2, height - bb[5]))
        a.scene.consume(custom_top)
    else:
        profile = _outline(shape, width, length, corner)
        cross = mf.CrossSection([_profile(profile)])
        top = (rounded_extrude(cross, thickness, min(edge, thickness * 0.45),
                               "столешница", 16) if edge > 1e-6 else cross.extrude(thickness))
        top = top.translate((0, 0, height - thickness))
    leg_height = height - thickness
    count = int(a.num("legs", 4, minv=1, maxv=16) or 4)
    layout = (a.text("layout", "inset", ["corners", "inset", "circle", "pedestal"]) or "inset")
    inset = float(a.num("inset", 12.0, minv=0.0) or 0.0)
    radius = float(a.num("leg_radius", 4.0, minv=0.2))
    taper = float(a.num("taper", 0.65, minv=0.1, maxv=1.5))
    splay = math.radians(float(a.num("splay", 0.0, minv=-30.0, maxv=30.0) or 0.0))
    leg_kind = (a.text("leg_shape", "tapered", ["round", "square", "tapered"]) or "tapered")
    leg_proto_name = (a.text("leg_object") or "").strip()
    leg_proto = a.scene.resolve(leg_proto_name) if leg_proto_name else None
    if leg_proto:
        a.scene.consume(leg_proto)
    if layout == "pedestal":
        count = 1
    if layout in ("corners", "inset") and count != 4:
        raise GeometryError("table: layout=corners/inset использует legs=4; "
                            "для произвольного числа выберите circle.")
    if layout == "circle" and count < 3:
        raise GeometryError("table: layout=circle требует минимум три ножки.")
    points = []
    if layout in ("corners", "inset"):
        margin = radius + 1.0 if layout == "corners" else inset
        for x, y in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
            points.append((x * (width / 2 - margin), y * (length / 2 - margin)))
    elif layout == "circle":
        ring_r = max(1.0, min(width, length) / 2 - inset)
        for i in range(count):
            angle = 2 * math.pi * i / count
            points.append((ring_r * math.cos(angle), ring_r * math.sin(angle)))
    else:
        points.append((0.0, 0.0))
    top_color = _color(a, "top_color", custom_top.color if custom_top else "#7b523a")
    leg_color = _color(a, "leg_color", leg_proto.color if leg_proto else "#3b3430")
    parts = [("", top, top_color, "table_top", {"rough": 0.42})]
    for index, (x, y) in enumerate(points):
        if leg_proto:
            leg = leg_proto.manifold
            bb = leg.bounding_box()
            leg = leg.translate((-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2, -bb[2]))
            proto_height = bb[5] - bb[2]
            if proto_height <= 1e-6:
                raise GeometryError("table: у пользовательской ножки нулевая высота.")
            leg = leg.scale((1.0, 1.0, leg_height / proto_height))
        elif leg_kind == "square":
            leg = _box((2 * radius, 2 * radius, leg_height), (0, 0, leg_height / 2), radius * 0.15)
        else:
            leg = _cylinder(radius * (taper if leg_kind == "tapered" else 1.0),
                            leg_height, r2=radius, segments=40)
        if splay:
            outward = np.asarray([x, y, 0.0], dtype=float)
            if np.linalg.norm(outward) < 1e-8:
                outward = np.asarray([1.0, 0.0, 0.0])
            outward /= np.linalg.norm(outward)
            bottom = np.asarray([x, y, 0.0]) + outward * math.tan(splay) * leg_height
            top_point = np.asarray([x, y, leg_height])
            matrix = np.eye(3, 4)
            matrix[:, :3] = _rotation_to(top_point - bottom)
            matrix[:, 3] = bottom
            leg = leg.transform(np.ascontiguousarray(matrix))
        else:
            leg = leg.translate((x, y, 0))
        parts.append((f".leg_{index + 1:02d}", leg, leg_color, "table_leg", {"rough": 0.38}))
    if a.boolean("shelf", False):
        shelf_h = float(a.num("shelf_height", 20.0, minv=0.5, maxv=max(0.5, leg_height - 1)))
        shelf_scale = float(a.num("shelf_scale", 0.9, minv=0.2, maxv=1.0))
        shelf_t = min(2.0, thickness)
        profile = _outline(shape, width * shelf_scale, length * shelf_scale,
                           corner * shelf_scale)
        shelf = mf.CrossSection([_profile(profile)]).extrude(shelf_t).translate((0, 0, shelf_h))
        parts.append((".shelf", shelf, _color(a, "shelf_color", top_color), "table_shelf", {}))
    return _emit(a, name, parts, {"width": width, "length": length, "height": height,
                                  "thickness": thickness, "shape": shape, "legs": count,
                                  "layout": layout, "leg_shape": leg_kind, "splay": math.degrees(splay),
                                  "shelf": a.boolean("shelf", False)})


@op("door", aliases=("дверь", "дверь_сборка"), category="Примитивы",
    summary="Двусторонняя составная дверь на готовых hinge и door_handle: коробка, "
            "полотно, симметричные филёнки, обе ручки, замок и обе створки каждой "
            "петли остаются отдельными selectable-объектами.",
    example='door = door width=90 height=210 panels=4 columns=2 handle_form=прямоугольная\n'
            'rotate [door.leaf] angle=35 axis=z pivot=[-44.4,-2.69,0]\n'
            'без_замка = door handle_rosette=овальная lock=нет at=[150,0,0]',
    params={"width": "ширина проёма/полотна X, мм (90)",
            "height": "высота полотна, мм (210)", "thickness": "толщина полотна (4.5)",
            "frame": "ширина коробки (5)", "frame_depth": "глубина коробки Y (10)",
            "gap": "зазор полотна в коробке (0.6)",
            "panels": "число филёнок на КАЖДОЙ стороне (4)", "columns": "число колонок (2)",
            "panel_margin": "поле вокруг филёнок (9)", "panel_gap": "промежуток (4)",
            "panel_depth": "выступ филёнки на каждой стороне (0.5)",
            "hinges": "число петель (3)", "hinge_radius": "радиус кулака (1.4)",
            "hinge_height": "высота готовой петли; 0 — автоматически (0)",
            "hinge_leaf_width": "ширина каждой створки петли (4)",
            "hinge_thickness": "толщина створки петли (0.8)",
            "hinge_holes": "отверстий на каждой створке 0…4 (0)",
            "handle_height": "высота оси ручки (105)", "handle_offset": "от правого края (12)",
            "handle_length": "длина рычага (11)", "handle_radius": "половина толщины (1)",
            "backset": "вынос ручки от полотна (4)",
            "handle_form": "изогнутая, рельефная, прямоугольная, сферическая или дисковая",
            "handle_rosette": "круглая, овальная, прямоугольная или нет (круглая)",
            "handle_rosette_h": "высота розетки; 0 — автоматически (0)",
            "handle_hand": "лево или право; на второй стороне зеркально по Y (лево)",
            "handle_segments": "детализация готовой ручки 24…96 (32)",
            "handle_blend": "SDF-сопряжение ручки (0.8)",
            "handle_resolution": "шаг SDF; 0 — автоматически (0)",
            "lock": "да — сквозная скважина и замочные элементы на обеих сторонах (да)",
            "lock_plug": "да — отдельные цилиндры замка с двух сторон (нет)",
            "lock_offset": "замок ниже ручки; 0 — автоматически (0)",
            "lock_d": "диаметр скважины; 0 — автоматически (0)",
            "wood": "цвет полотна", "panel_color": "цвет филёнок",
            "frame_color": "цвет коробки", "metal_color": "цвет фурнитуры",
            "at": "положение сборки", "center": "центрировать по высоте"})
def door(a, name):
    from .ops_fittings import _hinge_geometry

    width = float(a.num("width", 90.0, minv=30.0))
    height = float(a.num("height", 210.0, minv=50.0))
    thickness = float(a.num("thickness", 4.5, minv=1.0, maxv=width * 0.2))
    frame = float(a.num("frame", 5.0, minv=0.5))
    frame_depth = float(a.num("frame_depth", 10.0, minv=thickness))
    gap = float(a.num("gap", 0.6, minv=0.0, maxv=width * 0.05) or 0.0)
    leaf_w, leaf_h = width - 2 * gap, height - gap
    front = -thickness / 2
    wood = _color(a, "wood", "#9b724c")
    panel_color = _color(a, "panel_color", wood)
    frame_color = _color(a, "frame_color", "#725137")
    metal = _color(a, "metal_color", "#b7a36a")
    metal_style = {"metal": 0.75, "rough": 0.25}
    parts = [("", _box((frame, frame_depth, height + frame),
                        (-width / 2 - frame / 2, 0, (height + frame) / 2), 0.25),
              frame_color, "door_frame", {"rough": 0.48}),
             (".frame_right", _box((frame, frame_depth, height + frame),
                                   (width / 2 + frame / 2, 0, (height + frame) / 2), 0.25),
              frame_color, "door_frame", {"rough": 0.48}),
             (".frame_top", _box((width, frame_depth, frame),
                                 (0, 0, height + frame / 2), 0.25),
              frame_color, "door_frame", {"rough": 0.48})]

    # Сначала параметры фурнитуры: скважина должна быть вырезана из полотна
    # до регистрации детали, а не нарисована поверх него.
    handle_h = float(a.num("handle_height", 105.0, minv=10.0, maxv=height - 5))
    handle_x = width / 2 - float(a.num("handle_offset", 12.0, minv=4.0))
    handle_r = float(a.num("handle_radius", 1.0, minv=0.2))
    backset = float(a.num("backset", 4.0, minv=1.0))
    handle_len = float(a.num("handle_length", 11.0, minv=3.0))
    handle_form = (a.text("handle_form", "изогнутая", ["изогнутая", "рельефная",
                   "прямоугольная", "сферическая", "дисковая"]) or "изогнутая")
    handle_rosette = (a.text("handle_rosette", "круглая",
                      ["круглая", "овальная", "прямоугольная", "нет"]) or "круглая")
    handle_hand = (a.text("handle_hand", "лево") or "лево").lower()
    if handle_hand not in ("лево", "право", "left", "right"):
        raise GeometryError("door: handle_hand=лево или право")
    lock = a.boolean("lock", True)
    lock_plug = a.boolean("lock_plug", False)
    if lock_plug and not lock:
        raise GeometryError("door: lock_plug=да требует lock=да")
    lock_offset = float(a.num("lock_offset", 0.0, minv=0.0) or 0.0) or handle_r * 8.0
    lock_d = float(a.num("lock_d", 0.0, minv=0.0) or 0.0) or handle_r * 2.4
    if lock and (lock_z := handle_h - lock_offset) <= lock_d:
        raise GeometryError("door: замок слишком низко; увеличьте handle_height или уменьшите lock_offset")
    rosette_d = handle_r * 4.0
    rosette_t = max(0.35, handle_r * 0.45)
    if handle_rosette == "круглая":
        rosette_h = rosette_d
    elif handle_rosette == "нет":
        rosette_h = 0.0
    else:
        requested_h = float(a.num("handle_rosette_h", 0.0, minv=0.0) or 0.0)
        automatic = rosette_d * 1.7
        if lock:
            automatic = max(automatic, 2.0 * lock_offset + 3.0 * lock_d)
        rosette_h = requested_h or automatic
    if lock and handle_rosette in ("овальная", "прямоугольная"):
        integrated_z = rosette_h * 0.5 - lock_offset
        if integrated_z - lock_d * 0.65 <= lock_d * 0.75 or integrated_z + lock_d * 0.65 >= rosette_h - 0.1:
            raise GeometryError("door: скважина не помещается в handle_rosette_h")
    leaf = _box((leaf_w, thickness, leaf_h), (0, 0, gap + leaf_h / 2),
                min(0.18, thickness * 0.12))
    if lock:
        bore = _between((handle_x, front + 1.0, lock_z + lock_d * 0.12),
                        (handle_x, -front - 1.0, lock_z + lock_d * 0.12),
                        lock_d * 0.52, segments=32)
        slot = _box((lock_d * 0.25, thickness + 2.0, lock_d * 0.75),
                    (handle_x, 0, lock_z - lock_d * 0.25))
        leaf = leaf - bore - slot
    parts.append((".leaf", leaf, wood, "door_leaf", {"rough": 0.46}))

    panel_count = int(a.num("panels", 4, minv=0, maxv=24) or 0)
    columns = int(a.num("columns", 2, minv=1, maxv=6) or 1)
    if panel_count:
        rows = int(math.ceil(panel_count / columns))
        margin = float(a.num("panel_margin", 9.0, minv=1.0))
        panel_gap = float(a.num("panel_gap", 4.0, minv=0.0) or 0.0)
        depth = float(a.num("panel_depth", 0.5, minv=0.1, maxv=thickness))
        # Ручка и замок принадлежат стойке, а не филёнке. Резервируем правую
        # стойку до булевых/размещения: иначе отдельная филёнка закрывает
        # сквозную скважину полотна и перехватывает raycast цилиндра.
        hardware_r = max(rosette_d, handle_r * 5.0
                         if handle_form in ("сферическая", "дисковая") else 0.0) * 0.5
        panel_left = -leaf_w / 2 + margin
        panel_right = min(leaf_w / 2 - margin, handle_x - hardware_r - 1.0)
        cell_w = (panel_right - panel_left - (columns - 1) * panel_gap) / columns
        cell_h = (leaf_h - 2 * margin - (rows - 1) * panel_gap) / rows
        if min(cell_w, cell_h) <= 1:
            raise GeometryError("door: филёнки не помещаются; уменьшите panels/columns/margin.")
        for index in range(panel_count):
            row, col = divmod(index, columns)
            x = panel_left + cell_w / 2 + col * (cell_w + panel_gap)
            z = gap + leaf_h - margin - cell_h / 2 - row * (cell_h + panel_gap)
            panel = _box((cell_w, depth, cell_h),
                         (x, front - depth / 2 + 0.05, z), min(0.35, depth * 0.4))
            parts.append((f".leaf.panel_{index + 1:02d}", panel, panel_color,
                          "door_panel", {"rough": 0.43}))
            parts.append((f".leaf.panel_back_{index + 1:02d}", panel.mirror((0.0, 1.0, 0.0)),
                          panel_color, "door_panel_back", {"rough": 0.43}))

    # Настоящие готовые петли: левая створка закреплена на коробке, правая
    # принадлежит door.leaf и следует за его поворотом.
    hinge_count = int(a.num("hinges", 3, minv=1, maxv=6) or 3)
    hinge_r = float(a.num("hinge_radius", 1.4, minv=0.3))
    hinge_h = float(a.num("hinge_height", 0.0, minv=0.0) or 0.0) or min(18.0, max(8.0, height * 0.10))
    hinge_leaf_w = float(a.num("hinge_leaf_width", 4.0, minv=1.5))
    hinge_t = float(a.num("hinge_thickness", 0.8, minv=0.2))
    hinge_holes = int(a.num("hinge_holes", 0, minv=0, maxv=4) or 0)
    if hinge_count * hinge_h > height * 0.9:
        raise GeometryError("door: петли перекрываются; уменьшите hinge_height или hinges")
    hinge_x = -width / 2 + gap
    plate_y = hinge_t * 0.65 + 0.12
    hinge_y = front - plate_y + hinge_t * 0.25
    for index in range(hinge_count):
        z_center = height * (index + 1) / (hinge_count + 1)
        left_hinge, right_hinge = _hinge_geometry(dict(
            height=hinge_h, leaf_width=hinge_leaf_w, thickness=hinge_t,
            corner=min(0.6, hinge_leaf_w * 0.15), holes=hinge_holes,
            hole_d=min(1.0, hinge_leaf_w * 0.20), countersink=True, segments=32,
            barrel_d=2.0 * hinge_r, pin_d=2.0 * hinge_r * 0.44, knuckles=5,
            knuckle_gap=min(0.08, hinge_h * 0.002), clearance=min(0.08, hinge_r * 0.08),
            barrel_overhang=min(0.3, hinge_h * 0.01), open_angle=0.0))
        shift = (hinge_x, hinge_y, z_center - hinge_h * 0.5)
        parts.append((f".hinge_{index + 1:02d}", left_hinge.translate(shift), metal,
                      "door_hinge", metal_style))
        parts.append((f".leaf.hinge_{index + 1:02d}", right_hinge.translate(shift), metal,
                      "door_hinge_leaf", metal_style))

    handle_segments = int(a.num("handle_segments", 32, minv=24, maxv=96) or 32)
    handle_blend = float(a.num("handle_blend", 0.8, minv=0.0))
    requested_resolution = a.num("handle_resolution", 0.0, minv=0.0) or None
    cfg = dict(rosette=handle_rosette, rosette_d=rosette_d, rosette_h=rosette_h,
               rosette_t=rosette_t, rosette_corner=min(0.5, handle_r * 0.3),
               neck_d=handle_r * 1.6, projection=backset,
               lever_d=handle_r * 2.0, lever_length=handle_len,
               lever_corner=min(0.25, handle_r * 0.2), relief=0.55,
               knob_d=handle_r * 5.0, disk_t=handle_r * 1.8,
               lock=lock, lock_plug=lock_plug, lock_offset=lock_offset,
               lock_d=lock_d, lock_slot=lock_d * 0.22,
               lock_plate_r=handle_r * 2.2, lock_plug_t=max(0.3, rosette_t * 0.65))
    handle_items, actual_handle_resolution = _ready_handle(
        handle_form, cfg, handle_segments, handle_blend, requested_resolution, handle_hand)
    for suffix, part in handle_items:
        if not suffix:
            front_name, back_name = ".leaf.handle", ".leaf.handle_back"
        elif suffix == ".lock_plate":
            front_name, back_name = ".leaf.lock", ".leaf.lock_back"
        else:
            front_name, back_name = ".leaf.lock_plug", ".leaf.lock_plug_back"
        parts.append((front_name, part.translate((handle_x, front, handle_h)), metal,
                      "door_handle" if not suffix else "door_lock", metal_style))
        parts.append((back_name, part.mirror((0.0, 1.0, 0.0)).translate(
            (handle_x, -front, handle_h)), metal,
            "door_handle_back" if not suffix else "door_lock_back", metal_style))

    params = {"width": width, "height": height, "thickness": thickness,
              "frame": frame, "gap": gap, "panels": panel_count, "columns": columns,
              "hinges": hinge_count, "hinge_height": hinge_h,
              "handle_form": handle_form, "handle_rosette": handle_rosette,
              "handle_resolution": actual_handle_resolution,
              "lock": lock, "lock_plug": lock_plug, "both_sides": True,
              "objects": len(parts)}
    root = _emit(a, name, parts, params)
    root.meta["hinge_pivot_local"] = [hinge_x, hinge_y, 0.0]
    root.meta["leaf_object"] = f"{name}.leaf"
    root.meta["handle_objects"] = [f"{name}.leaf.handle", f"{name}.leaf.handle_back"]
    return root


@op("window", aliases=("окно", "оконный_блок", "window_unit"), category="Примитивы",
    summary="Настраиваемое окно из отдельных рам, створок, стёкол, импостов, "
            "трансомов, ручек, наличников и подоконника. Обычное, панорамное "
            "и составное; открываемые створки вращаются вместе с фурнитурой.",
    example='окно = window width=120 height=140 sections=2 casing=да sill=да\n'
            'панорама = window type=панорамное width=260 height=210 sections=3 opening=нет at=[300,0,0]\n'
            'составное = window type=составное width=220 height=150 sections=3 rows=2 open_angle=20',
    params={"type": "обычное, панорамное или составное (обычное)",
            "width": "наружная ширина X, мм (120)", "height": "высота Z, мм (140)",
            "depth": "глубина наружной рамы Y, мм (8)",
            "frame": "ширина наружной рамы; 0 — по типу (0)",
            "sash": "ширина профиля створки; 0 — по типу (0)",
            "sections": "вертикальных секций; 0 — по типу (0)", "rows": "рядов по высоте 1…4 (1)",
            "mullion": "ширина вертикального импоста; 0 — автоматически (0)",
            "transom": "высота горизонтального трансома; 0 — автоматически (0)",
            "opening": "все, крайние или нет; определяет наличие ручек и open_angle",
            "open_angle": "открытие наружу/внутрь по Z, 0…120° (0)",
            "handle": "да — ручки на открываемых створках (да)",
            "handle_form": "форма готовой ручки (изогнутая)",
            "handle_length": "длина оконной ручки; 0 — автоматически (0)",
            "handle_d": "толщина оконной ручки; 0 — автоматически (0)",
            "handle_side": "авто, лево или право (авто)",
            "handle_resolution": "шаг SDF ручки; 0 — автоматически (0)",
            "glass_t": "толщина стекла (1.6)", "glass_color": "цвет стекла",
            "casing": "наличники с двух сторон; по умолчанию зависят от типа",
            "casing_width": "ширина наличника (5)", "casing_depth": "толщина наличника (1)",
            "sill": "подоконник; по умолчанию зависит от типа",
            "sill_depth": "глубина подоконника (16)", "sill_thickness": "толщина (2)",
            "sill_overhang": "боковой выступ подоконника (4)",
            "frame_color": "цвет наружной рамы", "sash_color": "цвет створок",
            "casing_color": "цвет наличников", "sill_color": "цвет подоконника",
            "handle_color": "цвет фурнитуры", "at": "положение сборки",
            "center": "центрировать по высоте"})
def window(a, name):
    raw_type = (a.text("type", "обычное") or "обычное").strip().lower()
    kind = {"обычное": "обычное", "обычный": "обычное", "casement": "обычное",
            "панорамное": "панорамное", "панорамный": "панорамное",
            "panoramic": "панорамное", "составное": "составное",
            "составной": "составное", "composite": "составное"}.get(raw_type)
    if kind is None:
        raise GeometryError("window: type=обычное, панорамное или составное")
    width = float(a.num("width", 120.0, minv=30.0))
    height = float(a.num("height", 140.0, minv=30.0))
    depth = float(a.num("depth", 8.0, minv=2.0))
    frame = float(a.num("frame", 0.0, minv=0.0) or 0.0) or (2.6 if kind == "панорамное" else 4.5)
    sash = float(a.num("sash", 0.0, minv=0.0) or 0.0) or (1.4 if kind == "панорамное" else 2.8)
    sections = int(a.num("sections", 0, minv=0, maxv=8) or 0)
    if not sections:
        sections = 3 if kind in ("панорамное", "составное") else 2
    rows = int(a.num("rows", 1, minv=1, maxv=4) or 1)
    mullion = float(a.num("mullion", 0.0, minv=0.0) or 0.0) or max(1.8, frame * 0.72)
    transom = float(a.num("transom", 0.0, minv=0.0) or 0.0) or max(1.8, frame * 0.72)
    if sections == 1:
        mullion = 0.0
    if rows == 1:
        transom = 0.0
    inner_w, inner_h = width - 2 * frame, height - 2 * frame
    cell_w = (inner_w - (sections - 1) * mullion) / sections
    cell_h = (inner_h - (rows - 1) * transom) / rows
    if min(cell_w, cell_h) <= 2 * sash + 2.0:
        raise GeometryError("window: секции не помещаются; уменьшите sections/rows/frame/sash")
    default_opening = "нет" if kind == "панорамное" else ("крайние" if kind == "составное" else "все")
    opening = (a.text("opening", default_opening, ["все", "крайние", "нет"]) or default_opening)
    open_angle = float(a.num("open_angle", 0.0, minv=0.0, maxv=120.0) or 0.0)
    handles = a.boolean("handle", True)
    handle_form = (a.text("handle_form", "изогнутая", ["изогнутая", "рельефная",
                   "прямоугольная", "сферическая", "дисковая"]) or "изогнутая")
    handle_len = float(a.num("handle_length", 0.0, minv=0.0) or 0.0) or max(10.0, min(28.0, height * 0.12))
    handle_d = float(a.num("handle_d", 0.0, minv=0.0) or 0.0) or max(2.0, min(4.0, height * 0.018))
    handle_side = (a.text("handle_side", "авто", ["авто", "лево", "право"]) or "авто")
    handle_resolution = a.num("handle_resolution", 0.0, minv=0.0) or None
    glass_t = float(a.num("glass_t", 1.6, minv=0.2, maxv=depth * 0.6))
    casing = a.boolean("casing", kind != "панорамное")
    sill = a.boolean("sill", kind != "панорамное")
    casing_w = float(a.num("casing_width", 5.0, minv=0.5))
    casing_t = float(a.num("casing_depth", 1.0, minv=0.2))
    sill_depth = float(a.num("sill_depth", 16.0, minv=2.0))
    sill_t = float(a.num("sill_thickness", 2.0, minv=0.3))
    sill_overhang = float(a.num("sill_overhang", 4.0, minv=0.0) or 0.0)
    frame_color = _color(a, "frame_color", "#e3e6e4")
    sash_color = _color(a, "sash_color", frame_color)
    glass_color = _color(a, "glass_color", "#b7d7e2")
    casing_color = _color(a, "casing_color", frame_color)
    sill_color = _color(a, "sill_color", "#d2c5b2")
    handle_color = _color(a, "handle_color", "#aab4ba")
    frame_style = {"rough": 0.34, "metal": 0.08}
    glass_style = {"rough": 0.07, "metal": 0.0, "transmission": 0.96}
    handle_style = {"rough": 0.24, "metal": 0.78}

    parts = [("", _box((frame, depth, height), (-width / 2 + frame / 2, 0, height / 2)),
              frame_color, "window_frame", frame_style),
             (".frame_right", _box((frame, depth, height),
                                   (width / 2 - frame / 2, 0, height / 2)),
              frame_color, "window_frame", frame_style),
             (".frame_bottom", _box((inner_w, depth, frame), (0, 0, frame / 2)),
              frame_color, "window_frame", frame_style),
             (".frame_top", _box((inner_w, depth, frame), (0, 0, height - frame / 2)),
              frame_color, "window_frame", frame_style)]

    # Импосты и трансомы не пересекаются: трансомы разрезаны на участки между
    # вертикальными стойками и плотно упираются в них торцами.
    x_cursor = -inner_w / 2
    cell_x = []
    for col in range(sections):
        center_x = x_cursor + cell_w / 2
        cell_x.append(center_x)
        x_cursor += cell_w
        if col < sections - 1:
            x = x_cursor + mullion / 2
            parts.append((f".mullion_{col + 1:02d}",
                          _box((mullion, depth * 0.90, inner_h), (x, 0, frame + inner_h / 2)),
                          frame_color, "window_mullion", frame_style))
            x_cursor += mullion
    z_cursor = frame
    cell_z = []
    for row in range(rows):
        center_z = z_cursor + cell_h / 2
        cell_z.append(center_z)
        z_cursor += cell_h
        if row < rows - 1:
            z = z_cursor + transom / 2
            for col, x in enumerate(cell_x):
                parts.append((f".transom_{row + 1:02d}_{col + 1:02d}",
                              _box((cell_w, depth * 0.90, transom), (x, 0, z)),
                              frame_color, "window_transom", frame_style))
            z_cursor += transom

    # Одна готовая ручка-мас­тер копируется на все открываемые створки.
    rosette_d = handle_d * 2.2
    handle_cfg = dict(rosette="круглая", rosette_d=rosette_d, rosette_h=rosette_d,
                      rosette_t=max(0.35, handle_d * 0.18), rosette_corner=0.3,
                      neck_d=handle_d * 0.75, projection=handle_d * 1.8,
                      lever_d=handle_d, lever_length=handle_len,
                      lever_corner=handle_d * 0.10, relief=0.45,
                      knob_d=handle_d * 2.5, disk_t=handle_d,
                      lock=False, lock_plug=False, lock_offset=0.0,
                      lock_d=1.0, lock_slot=0.2)
    handle_items = []
    if handles and opening != "нет":
        handle_items, actual_handle_resolution = _ready_handle(
            handle_form, handle_cfg, 24, min(0.5, handle_d * 0.18), handle_resolution)
    else:
        actual_handle_resolution = 0.0
    sash_depth = depth * 0.64
    sash_gap = min(0.35, cell_w * 0.01, cell_h * 0.01)
    pivots = {}
    sash_objects = []
    for row, cz in enumerate(cell_z):
        for col, cx in enumerate(cell_x):
            index = row * sections + col + 1
            base = f".sash_{index:02d}"
            sash_w, sash_h = cell_w - 2 * sash_gap, cell_h - 2 * sash_gap
            outer = _box((sash_w, sash_depth, sash_h), (cx, 0, cz))
            inner = _box((sash_w - 2 * sash, sash_depth + 1.0, sash_h - 2 * sash), (cx, 0, cz))
            sash_solid = outer - inner
            openable = opening == "все" or (opening == "крайние" and col in (0, sections - 1))
            if handle_side == "лево":
                sign = -1.0
            elif handle_side == "право":
                sign = 1.0
            else:
                sign = 1.0 if col % 2 == 0 else -1.0
            hinge_x = cx - sign * sash_w / 2
            angle = -sign * open_angle if openable else 0.0

            def place_sash(solid):
                if abs(angle) < 1e-9:
                    return solid
                return solid.translate((-hinge_x, 0.0, 0.0)).rotate(
                    (0.0, 0.0, angle)).translate((hinge_x, 0.0, 0.0))

            parts.append((base, place_sash(sash_solid), sash_color, "window_sash", frame_style))
            glass_w = sash_w - 2 * sash + 0.5
            glass_h = sash_h - 2 * sash + 0.5
            glass = _box((glass_w, glass_t, glass_h), (cx, -sash_depth * 0.08, cz))
            parts.append((base + ".glass", place_sash(glass), glass_color,
                          "window_glass", glass_style))
            sash_objects.append(f"{name}{base}")
            if openable:
                pivots[f"{name}{base}"] = [hinge_x, 0.0, cz - sash_h / 2]
            if openable and handles:
                hx = cx + sign * (sash_w / 2 - sash * 0.55)
                for suffix, handle_part in handle_items:
                    # Рычаг направлен вниз вдоль стойки, круглая розетка не
                    # меняет силуэт при повороте вокруг Y.
                    placed = handle_part.rotate((0.0, 90.0, 0.0)).translate(
                        (hx, -sash_depth / 2, cz))
                    parts.append((base + (".handle" if not suffix else suffix),
                                  place_sash(placed), handle_color, "window_handle", handle_style))

    if casing:
        front_y = -depth / 2 - casing_t / 2 + 0.10
        casing_parts = [
            ("left", _box((casing_w, casing_t, height + 2 * casing_w),
                          (-width / 2 - casing_w / 2, front_y, height / 2))),
            ("right", _box((casing_w, casing_t, height + 2 * casing_w),
                           (width / 2 + casing_w / 2, front_y, height / 2))),
            ("bottom", _box((width, casing_t, casing_w), (0, front_y, -casing_w / 2))),
            ("top", _box((width, casing_t, casing_w), (0, front_y, height + casing_w / 2))),
        ]
        for side, solid in casing_parts:
            parts.append((f".casing_front_{side}", solid, casing_color,
                          "window_casing", {"rough": 0.42}))
            parts.append((f".casing_back_{side}", solid.mirror((0.0, 1.0, 0.0)),
                          casing_color, "window_casing_back", {"rough": 0.42}))
    if sill:
        board = _box((width + 2 * sill_overhang, sill_depth, sill_t),
                     (0, -depth / 2 - sill_depth / 2 + 0.5, -sill_t / 2),
                     min(0.25, sill_t * 0.15))
        parts.append((".sill", board, sill_color, "window_sill", {"rough": 0.40}))

    params = {"type": kind, "width": width, "height": height, "depth": depth,
              "frame": frame, "sash": sash, "sections": sections, "rows": rows,
              "mullion": mullion, "transom": transom, "opening": opening,
              "open_angle": open_angle, "handle": handles, "handle_form": handle_form,
              "handle_resolution": actual_handle_resolution, "glass_t": glass_t,
              "casing": casing, "sill": sill, "objects": len(parts)}
    root = _emit(a, name, parts, params)
    root.meta["sash_objects"] = sash_objects
    root.meta["sash_pivots"] = pivots
    return root


def _grid_faces(ny, nx):
    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            b, c, d = a + 1, a + nx, a + nx + 1
            faces.extend(((a, b, d), (a, d, c)))
    return np.asarray(faces, dtype=np.int64)


def _thicken_open(vertices, faces, thickness, what):
    """Замыкает открытую поверхность в объём по усреднённым нормалям."""
    vertices = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    tri = vertices[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    areas = np.linalg.norm(normals, axis=1)
    if np.any(areas < 1e-10):
        raise GeometryError(f"{what}: сетка содержит вырожденные треугольники.")
    vertex_normals = np.zeros_like(vertices)
    for corner in range(3):
        np.add.at(vertex_normals, faces[:, corner], normals)
    lengths = np.linalg.norm(vertex_normals, axis=1)
    if np.any(lengths < 1e-10):
        raise GeometryError(f"{what}: не удалось определить нормали поверхности.")
    vertex_normals /= lengths[:, None]
    n = len(vertices)
    bottom = vertices - vertex_normals * float(thickness)
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]), axis=0)
    ordered = np.sort(edges, axis=1)
    unique, inverse, counts = np.unique(ordered, axis=0, return_inverse=True, return_counts=True)
    boundary = unique[counts == 1]
    side_faces = []
    for edge in boundary:
        # Ориентацию берём из единственного исходного треугольника.
        match = np.where(np.all(ordered == edge, axis=1))[0][0]
        a, b = edges[match]
        side_faces.extend(((int(b), int(a), int(a + n)),
                           (int(b), int(a + n), int(b + n))))
    all_vertices = np.vstack((vertices, bottom))
    all_faces = np.vstack((faces, faces[:, ::-1] + n,
                           np.asarray(side_faces, dtype=np.int64)))
    return manifold_from_arrays(all_vertices, all_faces, what)


def _ring(major, minor, at, axis=(1, 0, 0), segments=40, sides=10):
    profile = [(major + minor * math.cos(2 * math.pi * i / sides),
                minor * math.sin(2 * math.pi * i / sides)) for i in range(sides)]
    solid = _revolve_profile(profile, segments, "кольцо шторы")
    matrix = np.eye(3, 4)
    matrix[:, :3] = _rotation_to(axis)
    matrix[:, 3] = np.asarray(at, dtype=float)
    return solid.transform(np.ascontiguousarray(matrix))


@op("curtain", aliases=("штора", "портьера"), category="Примитивы",
    summary="Объёмная штора с реальными складками, толщиной, волнистым низом; "
            "карниз и кольца создаются отдельными деталями.",
    example='штора = curtain width=140 height=220 folds=8 fold_depth=7 thickness=0.18 '
            'wave=2 rod=да rings=да',
    params={"width": "ширина в собранном виде X, мм (140)",
            "height": "высота Z, мм (220)", "folds": "число полных складок (8)",
            "fold_depth": "амплитуда складок по Y, мм (7)",
            "thickness": "толщина ткани, мм (0.18)",
            "wave": "волнистость нижнего края, мм (2)",
            "billow": "дополнительный изгиб полотна по Y (1.5)",
            "detail": "число сегментов на складку, 4…16 (8)",
            "rows": "сегментов по высоте, 4…80 (28)",
            "rod": "да — отдельный карниз", "rings": "да — отдельные кольца",
            "rod_radius": "радиус карниза (1.5)", "color": "цвет ткани",
            "rod_color": "цвет карниза и колец",
            "at": "положение сборки", "center": "центрировать по высоте"})
def curtain(a, name):
    width = float(a.num("width", 140.0, minv=5.0))
    height = float(a.num("height", 220.0, minv=5.0))
    folds = int(a.num("folds", 8, minv=1, maxv=24) or 8)
    depth = float(a.num("fold_depth", 7.0, minv=0.05))
    thickness = float(a.num("thickness", 0.18, minv=0.01, maxv=depth * 0.4))
    wave = float(a.num("wave", 2.0, minv=0.0) or 0.0)
    billow = float(a.num("billow", 1.5, minv=0.0) or 0.0)
    per_fold = int(a.num("detail", 8, minv=4, maxv=16) or 8)
    rows = int(a.num("rows", 28, minv=4, maxv=80) or 28)
    nx = folds * per_fold + 1
    ny = rows + 1
    vertices = np.zeros((ny, nx, 3), dtype=float)
    for j in range(ny):
        v = j / rows
        for i in range(nx):
            u = i / (nx - 1)
            phase = 2 * math.pi * folds * u
            vertices[j, i] = ((u - 0.5) * width,
                              depth * math.sin(phase) * (0.82 + 0.18 * v) +
                              billow * math.sin(math.pi * v),
                              height * (1 - v) + wave * (v ** 5) * math.sin(phase + 0.5))
    cloth = _thicken_open(vertices.reshape(-1, 3), _grid_faces(ny, nx), thickness, "штора")
    color = _color(a, "color", "#c8b9a5")
    parts = [("", cloth, color, "curtain_cloth", {"rough": 0.92, "transmission": 0.02})]
    if a.boolean("rod", True):
        rod_r = float(a.num("rod_radius", 1.5, minv=0.2))
        rod_z = height + rod_r * 3.0
        rod = _between((-width / 2 - 5, 0, rod_z), (width / 2 + 5, 0, rod_z),
                       rod_r, segments=40)
        metal = _color(a, "rod_color", "#665f58")
        parts.append((".rod", rod, metal, "curtain_rod", {"metal": 0.55, "rough": 0.3}))
        if a.boolean("rings", True):
            for i in range(folds + 1):
                x = -width / 2 + width * i / folds
                ring = _ring(rod_r + 0.9, 0.22, (x, 0, rod_z), axis=(1, 0, 0))
                parts.append((f".ring_{i + 1:02d}", ring, metal, "curtain_ring",
                              {"metal": 0.55, "rough": 0.3}))
    return _emit(a, name, parts, {"width": width, "height": height, "folds": folds,
                                  "fold_depth": depth, "thickness": thickness,
                                  "wave": wave, "billow": billow, "detail": per_fold})


def _support_triangles(solids) -> np.ndarray:
    """Треугольники опор одним массивом: контакт считается по ним, а не по сетке."""
    chunks = []
    for solid in solids:
        vertices, faces = manifold_mesh(solid.manifold)
        if len(faces):
            chunks.append(vertices[faces])
    if not chunks:
        return np.zeros((0, 3, 3))
    return np.concatenate(chunks, axis=0)


def _floor_plane(level: float, extent: float = 600.0) -> np.ndarray:
    """Пол бесконечной площади не нужен: берём плиту под размер сцены."""
    extent = max(float(extent), 200.0)
    x = extent * 0.5
    down = extent * 0.25
    corners = np.array([[-x, -x, level], [x, -x, level], [x, x, level], [-x, x, level],
                        [-x, -x, level - down], [x, -x, level - down],
                        [x, x, level - down], [-x, x, level - down]])
    quads = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 4, 5), (0, 5, 1),
             (1, 5, 6), (1, 6, 2), (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0)]
    return corners[np.asarray(quads)]


def _draped_solid(vertices, faces):
    """Замкнутая деталь после драпировки.

    У смятой оболочки направление обхода может «вывернуться»: тело получается
    с отрицательным объёмом. Тогда те же грани перечисляются в обратном
    порядке — форма та же, ориентация правильная.
    """
    try:
        return manifold_from_arrays(vertices, faces, "драпировка")
    except GeometryError:
        return manifold_from_arrays(vertices, faces[:, ::-1], "драпировка")


def _drape_intersections(bodies, max_checks=32):
    """Измеряет общий объём пересечений разных выданных деталей.

    Не является тестом самопересечения внутри одной оболочки. Если пар слишком
    много или boolean не удался, незавершённость сообщается отдельно.
    """
    checked = 0
    volume = 0.0
    complete = True
    bounds = [body.bounding_box() for body in bodies]
    for i, first in enumerate(bodies):
        for j in range(i + 1, len(bodies)):
            b0, b1 = bounds[i], bounds[j]
            if any(b0[k + 3] <= b1[k] or b1[k + 3] <= b0[k] for k in range(3)):
                continue
            if checked >= max_checks:
                return volume, checked, False
            checked += 1
            try:
                common = first ^ bodies[j]
                if common.status() != mf.Error.NoError:
                    complete = False
                    continue
                measured = float(common.volume())
                # Отрицательный/NaN объём не означает «пересечения нет»: это
                # признак ненадёжного boolean у самопересекающейся оболочки.
                if not np.isfinite(measured) or measured < 0.0:
                    complete = False
                    continue
                volume += measured
            except Exception:
                complete = False
    return volume, checked, complete


def _drape_support_intersections(bodies, hosts, max_checks=32):
    """Проверяет результат с опорами, не проверяя опоры между собой."""
    checked = 0
    volume = 0.0
    complete = True
    bounds = [body.bounding_box() for body in bodies]
    hosts_bounds = [host.bounding_box() for host in hosts]
    for first, b0 in zip(bodies, bounds):
        for host, b1 in zip(hosts, hosts_bounds):
            if any(b0[k + 3] <= b1[k] or b1[k + 3] <= b0[k] for k in range(3)):
                continue
            if checked >= max_checks:
                return volume, checked, False
            checked += 1
            try:
                common = first ^ host
                measured = float(common.volume())
                if common.status() != mf.Error.NoError or not np.isfinite(measured) or measured < 0.0:
                    complete = False
                else:
                    volume += measured
            except Exception:
                complete = False
    return volume, checked, complete


def _drape_surface_contacts(bodies, supports=None, *, max_checks=32,
                            max_candidates=2_000_000, max_scan=20_000_000):
    """Ограниченная проверка поверхностей разных тел или тела и опор.

    ``bodies`` и ``supports`` содержат массивы треугольников. При supports=None
    проверяются пары разных тел, иначе — каждое тело с каждым набором опор.
    Касание и проникновение этой проверкой не различаются. Полное вложение
    контролируется отдельно через булевы операции над замкнутыми телами.
    """
    first = [np.asarray(tri, dtype=np.float64).reshape(-1, 3, 3) for tri in bodies]
    second = None if supports is None else [np.asarray(tri, dtype=np.float64).reshape(-1, 3, 3)
                                             for tri in supports]
    result = {"pairs": 0, "checks": 0, "candidates": 0, "scanned": 0,
              "degenerate": 0, "uncertain": 0, "complete": True}
    if max_checks < 0 or max_candidates < 0 or max_scan < 0:
        raise ValueError("Бюджеты проверки поверхностей не могут быть отрицательными")

    def bounds(tri):
        if not len(tri) or not np.all(np.isfinite(tri)):
            return None
        return tri.min(axis=(0, 1)), tri.max(axis=(0, 1))

    first_bounds = [bounds(tri) for tri in first]
    second_bounds = None if second is None else [bounds(tri) for tri in second]
    if any(b is None for b in first_bounds) or (second_bounds is not None and
                                                 any(b is None for b in second_bounds)):
        result["complete"] = False
        result["uncertain"] = 1
        return result
    for i, a in enumerate(first):
        items = ((j, first[j], first_bounds[j]) for j in range(i + 1, len(first))) if second is None \
            else ((j, tri, second_bounds[j]) for j, tri in enumerate(second))
        alo, ahi = first_bounds[i]
        for _j, b, (blo, bhi) in items:
            with np.errstate(over="ignore", invalid="ignore"):
                scale = max(1.0, float(np.max(ahi - alo)), float(np.max(bhi - blo)))
                magnitude = max(float(np.max(np.abs([alo, ahi]))), float(np.max(np.abs([blo, bhi]))))
                tol = 1e-9 * scale + 16.0 * np.finfo(np.float64).eps * magnitude
            if not np.isfinite(tol):
                result["complete"] = False
                result["uncertain"] += 1
                return result
            if np.any(ahi + tol < blo) or np.any(bhi + tol < alo):
                continue
            if result["checks"] >= max_checks:
                result["complete"] = False
                return result
            check = surface_intersections(a, b, max_candidates=max_candidates - result["candidates"],
                                          max_scan=max_scan - result["scanned"])
            result["checks"] += 1
            for field in ("pairs", "candidates", "scanned", "degenerate", "uncertain"):
                result[field] += check[field]
            if not check["complete"]:
                result["complete"] = False
                return result
    return result


def _pin_mask(vertices, mode, points, radius) -> np.ndarray:
    """Какие узлы держать на месте. Кромки замкнутой детали — по габариту."""
    pinned = np.zeros(len(vertices), dtype=bool)
    if not len(vertices):
        return pinned
    lo = vertices.min(axis=0)
    hi = vertices.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    eps = float(span.max()) * 1e-5
    if mode == "corners":
        on_x = (np.abs(vertices[:, 0] - lo[0]) < eps) | (np.abs(vertices[:, 0] - hi[0]) < eps)
        on_y = (np.abs(vertices[:, 1] - lo[1]) < eps) | (np.abs(vertices[:, 1] - hi[1]) < eps)
        pinned = on_x & on_y
    elif mode == "edges":
        pinned = (np.abs(vertices[:, 0] - lo[0]) < eps) | (np.abs(vertices[:, 0] - hi[0]) < eps) \
            | (np.abs(vertices[:, 1] - lo[1]) < eps) | (np.abs(vertices[:, 1] - hi[1]) < eps)
    elif mode in ("front", "back", "left", "right"):
        axis = 1 if mode in ("front", "back") else 0
        value = lo[axis] if mode in ("front", "left") else hi[axis]
        pinned = np.abs(vertices[:, axis] - value) < eps
    if points is not None and len(points):
        pin_points = np.asarray(points, dtype=float).reshape(-1, 3)
        for point in pin_points:
            distances = np.linalg.norm(vertices - point, axis=1)
            pinned[distances <= float(radius)] = True
            pinned[int(np.argmin(distances))] = True
    return pinned


@op("drape", aliases=("драпировка", "ткань_на", "cloth_relax", "постелить"),
    category="Поверхности и деформации",
    summary="Драпировка равновесием: деталь падает на выбранные опоры и ложится "
            "под гравитацией. Контакт считается по треугольникам опор (опор может "
            "быть сколько угодно), растяжение сдерживается связями, изгиб и трение "
            "настраиваются, целые куски (кубики, звенья цепей) держат форму. "
            "Гибкие слои и стенки учитывают самоконтакт. Анимации нет: "
            "получается сразу итоговая поза.",
    example='лист = box size=[150,150,0.4] at=[0,0,70]\n'
            'стол = box size=[80,80,40] at=[0,0,0]\n'
            'пол = box size=[400,400,20] at=[0,0,-20]\n'
            'скатерть = drape лист on=[стол, пол] gravity=z- mesh=4 friction=0.6',
    params={"objects": "деталь или список деталей: лист, корпус, цепь, несколько тел",
            "on": "опора или список опор; контакт по треугольникам всех опор",
            "gravity": "направление: z-, z+, x±, y± или [x,y,z]; число — это g вниз",
            "g": "ускорение за шаг, мм (0.2)", "steps": "шагов релаксации (55)",
            "iterations": "шагов релаксации — прежнее имя steps (55)",
            "constraints": "итераций ограничений на шаг (14)",
            "mesh": "шаг сетки расчёта, мм (3.5): меньше — точнее и медленнее",
            "particles": "бюджет узлов на деталь (4000)",
            "detail": "прежнее имя плотности: бюджет = 6·detail²",
            "friction": "трение о опоры 0…1 (0.6)", "bend": "сопротивление изгибу 0…1 (0.25)",
            "damping": "сохранение скорости 0…1 (0.88)", "stiffness": "жёсткость длин 0…1 (1.0)",
            "rigid": "auto, 0…1 или список: 1 — кусок держит форму, 0 — ткань (auto)",
            "self": "да — учитывать самоконтакт слоёв (да)",
            "self_gap": "зазор между поверхностями, мм (авто по толщине)",
            "thickness": "толщина открытого листа; для замкнутой детали — оценка по объёму и площади",
            "pin": "none, corners, edges, front, back, left или right",
            "pins": "точки [[x,y,z],…]: закрепляются ближайшие узлы",
            "pin_radius": "радиус выбора узлов около pins (2)",
            "gap": "зазор до опоры, мм (0.02)", "z": "уровень пола, если опоры не заданы"},
    positional=["objects"])
def drape(a, name):
    parts = a.solids()
    if not parts:
        raise GeometryError("drape: не задана деталь.",
                            hint="Например: скатерть = drape лист on=[стол, пол]")
    g_amount = float(a.num("g", 0.2, minv=0.0, maxv=20.0) or 0.0)
    gravity_value = a.value("gravity")
    if gravity_value is None:
        direction = cloth.parse_gravity("z-")
    elif isinstance(gravity_value, (int, float)) and not isinstance(gravity_value, bool):
        # старая запись: gravity=0.2 — это ускорение вниз, а не направление
        g_amount = float(gravity_value)
        direction = cloth.parse_gravity("z-")
    elif isinstance(gravity_value, (list, tuple)):
        vector = np.asarray(gravity_value, dtype=float).reshape(-1)
        if vector.size != 3:
            raise GeometryError("drape: в gravity должно быть три числа.",
                                hint="Например: gravity=[0,0,-1].")
        length = float(np.linalg.norm(vector))
        direction = vector / length if length > 1e-12 else np.zeros(3)
    else:
        direction = cloth.parse_gravity(str(gravity_value))

    steps = int(a.num("steps", None, minv=1, maxv=1000) or a.num("iterations", 55, minv=1, maxv=1000) or 55)
    constraints = int(a.num("constraints", 14, minv=1, maxv=64) or 14)
    mesh_step = float(a.num("mesh", 3.5, minv=0.05, maxv=200.0) or 3.5)
    budget = int(a.num("particles", 4000, minv=200, maxv=30000) or 4000)
    detail = a.num("detail", None, minv=2, maxv=64)
    if detail:
        budget = int(min(30000, max(200, 6.0 * float(detail) ** 2)))
    friction = float(a.num("friction", 0.6, minv=0.0, maxv=1.0) or 0.0)
    bend = float(a.num("bend", 0.25, minv=0.0, maxv=1.0) or 0.0)
    damping = float(a.num("damping", 0.88, minv=0.0, maxv=1.0) or 0.0)
    stiffness = float(a.num("stiffness", 1.0, minv=0.01, maxv=1.0) or 1.0)
    gap = float(a.num("gap", 0.02, minv=0.0, maxv=20.0) or 0.0)
    use_self = a.boolean("self", True)
    self_gap = a.num("self_gap", None, minv=0.005, maxv=100.0)
    pin_mode = (a.text("pin", "none",
                       ["none", "corners", "edges", "front", "back", "left", "right"]) or "none")
    pin_points = a.value("pins")
    pin_radius = float(a.num("pin_radius", 2.0, minv=0.001) or 2.0)

    hosts_value = a.value("on")
    host_values = list(hosts_value) if isinstance(hosts_value, (list, tuple)) else \
        ([hosts_value] if hosts_value else [])
    hosts = [a.scene.resolve(item) for item in host_values]
    supports = _support_triangles(hosts) if hosts else np.zeros((0, 3, 3))
    if not len(supports):
        floor = a.num("z", None)
        if floor is None:
            raise GeometryError("drape: не заданы опоры.",
                                hint="Укажите on=[стол, пол] или уровень пола z=0.")
        sizes = [np.ptp(manifold_mesh(part.manifold)[0], axis=0) for part in parts]
        supports = _floor_plane(float(floor),
                                3.0 * float(max(np.max(size) for size in sizes)) + 100.0)

    rigid_text = (a.text("rigid", "auto") or "auto").strip().lower()
    if rigid_text in ("auto", "авто"):
        rigid_value = "auto"
    else:
        rigid_value = float(a.num("rigid", 1.0, minv=0.0, maxv=1.0) or 0.0)

    merged_vertices, merged_faces, spans, colors, closed_flags = [], [], [], [], []
    naturals = []
    maximum_edges = []
    mesh_complete = True
    offset = 0
    for part in parts:
        vertices, faces = manifold_mesh(part.manifold)
        if len(vertices) == 0 or len(faces) == 0:
            raise GeometryError("drape: у детали нет сетки.")
        # Мельче толщины дробить бессмысленно: у проволоки звена цепи это
        # даёт узлы «в одну линию» и разваливает форму.
        natural = cloth._thickness_of(vertices, faces)
        step = max(mesh_step, 0.7 * natural)
        vertices, faces = cloth.subdivide_to(vertices, faces, step, budget)
        edges = cloth._edge_arrays(faces)
        longest = float(np.max(np.linalg.norm(vertices[edges[:, 1]] - vertices[edges[:, 0]], axis=1)))
        maximum_edges.append(longest)
        if longest > step * 1.01:
            mesh_complete = False
        merged_vertices.append(vertices)
        merged_faces.append(faces + offset)
        spans.append((offset, offset + len(vertices)))
        colors.append(part.color)
        closed_flags.append(cloth.is_closed(faces))
        naturals.append(natural)
        offset += len(vertices)
    vertices = np.vstack(merged_vertices)
    faces = np.concatenate(merged_faces, axis=0)

    pinned = np.zeros(len(vertices), dtype=bool)
    for begin, finish in spans:
        # Именованные кромки определяются по габариту каждой детали отдельно.
        pinned[begin:finish] = _pin_mask(vertices[begin:finish], pin_mode, None, pin_radius)
    if pin_points is not None:
        # Явные точки заданы в координатах сцены: ближайший узел выбирается
        # среди всей группы, а не принудительно на каждой удалённой детали.
        pinned |= _pin_mask(vertices, "none", pin_points, pin_radius)

    if rigid_value == "auto":
        rigid_input = cloth.auto_rigid_parts(vertices, faces)
    else:
        rigid_input = np.asarray([rigid_value], dtype=float)

    part_closed = all(closed_flags)
    if a.has("thickness"):
        thickness = float(a.num("thickness", 0.5, minv=0.005, maxv=50.0) or 0.5)
    else:
        sizes = [np.ptp(vertices[begin:finish], axis=0) for begin, finish in spans]
        thinnest = min(float(np.min(size)) for size in sizes)
        # тела меряем по настоящей толщине «2V/A»: у звена цепи габарит по
        # высоте — это вся цепь, и такая толщина раздувала самоколлизию
        natural_min = min([t for t in naturals if t > 0.0], default=0.0)
        thickness = float(min(5.0, max(0.05, natural_min if part_closed and natural_min > 0.0
                                      else thinnest)))

    report = cloth.simulate(vertices, faces, supports, gravity=direction, g=g_amount,
                            steps=steps, iterations=constraints, stiffness=stiffness,
                            bend=bend, damping=damping, friction=friction,
                            rigid=rigid_input, thickness=thickness,
                            self_collision=use_self, self_gap=self_gap, pinned=pinned, gap=gap)
    position = report["vertices"]
    if not np.all(np.isfinite(position)):
        raise GeometryError("drape: расчёт потерял устойчивость.")
    if not mesh_complete:
        a.scene.log("warn", f"drape: бюджет сетки не позволил достичь запрошенного шага: "
                            f"самое длинное ребро {max(maximum_edges):.2f} мм; "
                            "увеличьте particles или mesh.", a.cmd.line)
    if report["strain_all"] > 0.10:
        a.scene.log("warn", f"drape: максимальное изменение длины ребра {report['strain_all']:.1%} "
                            "(включая короткие рёбра стенки); "
                            "нерастяжимость не подтверждена. Попробуйте увеличить constraints "
                            "или уменьшить g.", a.cmd.line)
    if not report["converged"]:
        a.scene.log("warn", f"drape: достигнут предел {steps} шагов, равновесие не подтверждено "
                            f"(последнее смещение до {report['last_motion']:.3f} мм); "
                            "большее число шагов не гарантирует устойчивость.", a.cmd.line)
    else:
        a.scene.log("info", "drape: достигнут порог малого смещения; силы отдельно не "
                            "проверялись, поэтому равновесие не подтверждено.", a.cmd.line)

    emitted = []
    for index, (begin, finish) in enumerate(spans):
        local_faces = faces[(faces[:, 0] >= begin) & (faces[:, 0] < finish)] - begin
        local = position[begin:finish]
        if closed_flags[index]:
            body = _draped_solid(local, local_faces)
        else:
            body = _thicken_open(local, local_faces, thickness, "драпировка")
        suffix = "" if index == 0 else f".{index + 1:02d}"
        emitted.append((suffix, body, colors[index], "drape", {"rough": 0.9}))
    # Отдельная геометрическая проверка, а не счётчик контактов решателя.
    surface_checks, emitted_triangles = [], []
    for _suffix, body, _color, _kind, _material in emitted:
        check_vertices, check_faces = manifold_mesh(body)
        surface_checks.append(self_intersections(check_vertices, check_faces))
        emitted_triangles.append(check_vertices[check_faces])
    self_crossings = sum(check["pairs"] for check in surface_checks)
    adjacent_crossings = sum(check["adjacent_pairs"] for check in surface_checks)
    adjacent_uncertain = sum(check["adjacent_uncertain"] for check in surface_checks)
    adjacent_complete = all(check["adjacent_complete"] for check in surface_checks)
    self_check_complete = all(check["complete"] for check in surface_checks)
    if self_crossings:
        a.scene.log("warn", f"drape: найдены пересечения или касания {self_crossings} пар "
                            "несоседних граней внутри детали; геометрия небезопасна для экспорта.",
                    a.cmd.line)
    if adjacent_crossings:
        a.scene.log("warn", f"drape: найдены пересечения {adjacent_crossings} пар соседних "
                            "граней за пределами общей вершины или ребра; "
                            "геометрия небезопасна для экспорта.", a.cmd.line)
    if not self_check_complete:
        a.scene.log("warn", "drape: проверка самопересечений не завершена, есть вырожденные "
                            "грани или не хватает численной точности; отсутствие дефектов "
                            "не подтверждено.", a.cmd.line)

    # Независимо от частиц проверяем и грани разных поверхностей: проникновение
    # может пройти через середины граней, не затронув ни одной вершины. Контакт
    # учитывается консервативно, поскольку такой тест не отличает его от входа.
    parts_surface = {"pairs": 0, "checks": 0, "candidates": 0, "scanned": 0,
                     "degenerate": 0, "uncertain": 0, "complete": True}
    if use_self and len(emitted) > 1:
        parts_surface = _drape_surface_contacts(emitted_triangles)
    support_surface = _drape_surface_contacts(emitted_triangles, [supports])
    if parts_surface["pairs"]:
        a.scene.log("warn", f"drape: найдено касание или пересечение {parts_surface['pairs']} пар "
                            "граней разных деталей; проверка не отличает допустимое касание "
                            "от проникновения.", a.cmd.line)
    if not parts_surface["complete"]:
        a.scene.log("warn", "drape: проверка граней разных деталей не завершена или не хватает "
                            "численной точности.", a.cmd.line)
    if support_surface["pairs"]:
        a.scene.log("warn", f"drape: найдено касание или пересечение {support_surface['pairs']} пар "
                            "граней детали с опорами; проверка не отличает допустимое касание "
                            "от проникновения.", a.cmd.line)
    if not support_surface["complete"]:
        a.scene.log("warn", "drape: проверка граней детали и опор не завершена или не хватает "
                            "численной точности.", a.cmd.line)

    overlap, overlap_checks, overlap_complete = (0.0, 0, True)
    bodies = [item[1] for item in emitted]
    if use_self and len(emitted) > 1:
        overlap, overlap_checks, overlap_complete = _drape_intersections(bodies)
        if overlap_checks and (self_crossings or adjacent_crossings or not self_check_complete):
            overlap_complete = False  # boolean с самопересечениями ненадёжен
        if overlap > 0.0:
            a.scene.log("warn", f"drape: измерен положительный объём пересечения разных деталей "
                               f"{overlap:.6g} мм³; очень малое значение может зависеть от "
                               "численной точности. Попробуйте уменьшить mesh или увеличить "
                               "self_gap/steps.", a.cmd.line)
        if not overlap_complete:
            a.scene.log("warn", "drape: проверка пересечений разных деталей не завершена "
                                "или геометрия ненадёжна.", a.cmd.line)
    support_overlap, support_checks, support_complete = (0.0, 0, bool(hosts))
    if hosts:
        support_overlap, support_checks, support_complete = _drape_support_intersections(
            bodies, [host.manifold for host in hosts])
        if support_checks and (self_crossings or adjacent_crossings or not self_check_complete):
            support_complete = False
        if support_overlap > 0.0:
            a.scene.log("warn", f"drape: измерен положительный объём пересечения с опорами "
                                f"{support_overlap:.6g} мм³; очень малое значение может "
                                "зависеть от численной точности.", a.cmd.line)
        if not support_complete:
            a.scene.log("warn", "drape: проверка пересечений с опорами не завершена "
                                "или геометрия ненадёжна.", a.cmd.line)
    # Лишь ограниченные проверки, не доказательство и не проверка равновесия.
    # Касание граней без проникновения допустимо, но эта диагностика не умеет
    # его надёжно отличать: в таком случае она консервативно не заявляет успех.
    # Для z-пола без твёрдотельной опоры объёмная проверка не выполняется.
    geometry_checks_passed = (self_check_complete and not self_crossings and not adjacent_crossings
                              and (len(bodies) <= 1 or (use_self and overlap_complete and not overlap
                                                         and parts_surface["complete"]
                                                         and not parts_surface["pairs"]))
                              and bool(hosts) and support_complete and not support_overlap
                              and support_surface["complete"] and not support_surface["pairs"]
                              and report["penetration"] <= 1e-4)
    for part in parts:
        a.scene.consume(part)

    meta = {"vertices": int(report["vertices_count"]), "pinned": int(pinned.sum()),
            "free": int(len(pinned) - pinned.sum()), "contacts": int(report["contacts"]),
            "max_strain": float(report["strain"]), "strain_p90": float(report["strain_p90"]),
            "max_strain_all": float(report["strain_all"]),
            "strain_all_p90": float(report["strain_all_p90"]),
            "shortest_rest_edge": float(report["shortest_rest_edge"]),
            "stretch": float(report["stretch"]),
            "self_collision": bool(use_self), "self_gap": float(report["self_gap"]),
            "self_pairs": int(report["self_pairs"]), "self_method": report["self_method"],
            "self_intersections": int(self_crossings),
            "self_intersections_adjacent": int(adjacent_crossings),
            "self_intersections_complete": bool(self_check_complete),
            "self_intersections_adjacent_complete": bool(adjacent_complete),
            "self_intersections_adjacent_uncertain": int(adjacent_uncertain),
            "self_intersection_candidates": sum(check["candidates"] for check in surface_checks),
            "self_intersection_adjacent_candidates": sum(
                check["adjacent_candidates"] for check in surface_checks),
            "degenerate_faces": sum(check["degenerate"] for check in surface_checks),
            "parts_surface_pairs": int(parts_surface["pairs"]),
            "parts_surface_checks": int(parts_surface["checks"]),
            "parts_surface_checked": bool(use_self and len(emitted) > 1),
            "parts_surface_complete": bool(parts_surface["complete"]),
            "parts_surface_uncertain": int(parts_surface["uncertain"]),
            "support_surface_pairs": int(support_surface["pairs"]),
            "support_surface_checks": int(support_surface["checks"]),
            "support_surface_complete": bool(support_surface["complete"]),
            "support_surface_uncertain": int(support_surface["uncertain"]),
            "parts_overlap_volume": float(overlap), "parts_overlap_checks": overlap_checks,
            "parts_overlap_checked": bool(use_self and len(emitted) > 1),
            "parts_overlap_complete": overlap_complete,
            "support_overlap_volume": float(support_overlap), "support_overlap_checks": support_checks,
            "support_overlap_checked": bool(hosts), "support_overlap_complete": bool(support_complete),
            "steps": int(report["steps"]), "converged": bool(report["converged"]),
            "movement_stable": bool(report["converged"]),
            "equilibrium_verified": False,
            "geometry_checks_passed": bool(geometry_checks_passed),
            "last_motion": float(report["last_motion"]),
            "movement_tolerance": float(report["movement_tolerance"]), "constraints": constraints,
            "mesh": mesh_step, "mesh_max_edge": max(maximum_edges),
            "mesh_complete": bool(mesh_complete), "budget": budget,
            "thickness": thickness, "friction": friction, "bend": bend,
            "gravity": [round(float(v), 4) for v in direction], "g": g_amount,
            "rigid": (float(np.max(rigid_input)) if len(rigid_input) else 0.0),
            "parts": len(parts), "seconds": report["seconds"],
            "penetration": float(report["penetration"]), "closed": bool(part_closed),
            "supports": len(hosts), "cell": float(report["cell"])}
    root = _emit(a, name, emitted,
                 {"steps": steps, "constraints": constraints, "mesh": mesh_step,
                  "thickness": thickness, "friction": friction, "bend": bend,
                  "rigid": rigid_text, "self": use_self, "self_gap": self_gap,
                  "pin": pin_mode})
    root.notes.append(f"драпировка: {meta['vertices']} узлов, опор {len(hosts)}, "
                      f"контактов {meta['contacts']}; изменение длины всех рёбер: "
                      f"p90 {meta['strain_all_p90']:.1%}, максимум {meta['max_strain_all']:.1%}; "
                      f"несоседних пересечений/касаний {meta['self_intersections']}, "
                      f"пересечений соседних граней {meta['self_intersections_adjacent']}"
                      f"{'' if meta['self_intersections_complete'] else ' (проверка неполная)'}, "
                      f"{meta['seconds']:.2f} с")
    root.meta["cloth"] = meta
    a.scene.log("info", root.notes[-1], a.cmd.line)
    return root


def _resample_loop(points, count):
    points = np.asarray(points, dtype=float)
    closed = np.vstack((points, points[0]))
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    targets = np.linspace(0, cumulative[-1], count, endpoint=False)
    output = []
    segment = 0
    for target in targets:
        while segment + 1 < len(lengths) and cumulative[segment + 1] < target:
            segment += 1
        factor = (target - cumulative[segment]) / max(lengths[segment], 1e-12)
        output.append(closed[segment] * (1 - factor) + closed[segment + 1] * factor)
    return np.asarray(output)


def _radial_mesh(outline, rings, height_fn):
    n = len(outline)
    vertices = [np.asarray([0.0, 0.0, height_fn(0.0, 0.0)])]
    for ring in range(1, rings + 1):
        factor = ring / rings
        for x, y in outline * factor:
            vertices.append(np.asarray([x, y, height_fn(x, y)]))
    faces = []
    for i in range(n):
        faces.append((0, 1 + i, 1 + (i + 1) % n))
    for ring in range(1, rings):
        inner, outer = 1 + (ring - 1) * n, 1 + ring * n
        for i in range(n):
            j = (i + 1) % n
            faces.extend(((inner + i, outer + i, outer + j),
                          (inner + i, outer + j, inner + j)))
    return np.asarray(vertices), np.asarray(faces, dtype=np.int64)


@op("rug", aliases=("ковёр", "ковер", "carpet"), category="Примитивы",
    summary="Ковёр с объёмной волнистой основой, каймой, узором, подложкой, "
            "окантовкой, стежками, бахромой и приподнятым углом.",
    example='ковёр = rug width=180 length=120 shape=rounded corner=12 thickness=1.2 '
            'border=8 pattern=полосы fringe=ends lift=7 wave=0.4 stitches=да',
    params={"width": "ширина X, мм (180)", "length": "длина Y, мм (120)",
            "shape": "rect, rounded или ellipse", "corner": "радиус скругления контура (12)",
            "thickness": "толщина основы (1.2)", "pad": "толщина отдельной подложки (0.25)",
            "border": "ширина каймы, мм (8)", "pattern": "узор верха или none",
            "pattern_size": "размер элемента узора (3)", "pattern_step": "шаг узора (10)",
            "pattern_angle": "угол узора (0)", "wave": "амплитуда волнистости (0.35)",
            "lift": "подъём угла, мм (6)",
            "lift_corner": "front_right, front_left, back_right, back_left или none",
            "binding": "радиус окантовочного шнура; 0 отключает (0.35)",
            "stitches": "да — отдельные стежки", "fringe": "none, ends или all",
            "fringe_length": "длина бахромы (8)", "fringe_count": "число на конец / всего (24)",
            "rings": "радиальная плотность сетки 3…16 (10)",
            "detail": "сегментов периметра 16…128 (64)",
            "color": "цвет основы", "border_color": "цвет каймы и стежков",
            "pad_color": "цвет подложки", "pattern_color": "цвет узора",
            "fringe_color": "цвет бахромы",
            "at": "положение сборки", "center": "центрировать по высоте"})
def rug(a, name):
    width = float(a.num("width", 180.0, minv=10.0))
    length = float(a.num("length", 120.0, minv=10.0))
    shape = (a.text("shape", "rounded", ["rect", "rounded", "ellipse"]) or "rounded")
    corner = float(a.num("corner", 12.0, minv=0.0) or 0.0) if shape == "rounded" else 0.0
    thickness = float(a.num("thickness", 1.2, minv=0.05))
    wave = float(a.num("wave", 0.35, minv=0.0) or 0.0)
    lift = float(a.num("lift", 6.0, minv=0.0) or 0.0)
    lift_corner = (a.text("lift_corner", "front_right",
                          ["front_right", "front_left", "back_right", "back_left", "none"]) or "front_right")
    def height_fn(x, y):
        z = wave * math.sin(3 * math.pi * x / width + 0.4) * math.sin(2 * math.pi * y / length)
        if lift and lift_corner != "none":
            sx = 1 if "right" in lift_corner else -1
            sy = 1 if "back" in lift_corner else -1
            wx = max(0.0, 0.5 + sx * x / width)
            wy = max(0.0, 0.5 + sy * y / length)
            z += lift * (wx * wy) ** 5
        return z
    detail = int(a.num("detail", 64, minv=16, maxv=128) or 64)
    rings = int(a.num("rings", 10, minv=3, maxv=16) or 10)
    outline = _resample_loop(_outline(shape, width, length, corner), detail)
    vertices, faces = _radial_mesh(outline, rings, height_fn)
    cloth = _thicken_open(vertices, faces, thickness, "ковёр")
    color = _color(a, "color", "#9b6b57")
    parts = [("", cloth, color, "rug_cloth", {"rough": 0.96})]
    binding = float(a.num("binding", 0.35, minv=0.0) or 0.0)
    border = min(float(a.num("border", 8.0, minv=0.0) or 0.0), min(width, length) * 0.2)
    border_color = _color(a, "border_color", "#dac6a5")
    pad = float(a.num("pad", 0.25, minv=0.0) or 0.0)
    if pad > 0:
        pad_profile = mf.CrossSection([_profile((outline * 0.985).tolist())]).extrude(pad)
        pad_profile = pad_profile.translate((0, 0, -thickness - pad - 0.04))
        parts.append((".pad", pad_profile, _color(a, "pad_color", "#4b4642"),
                      "rug_pad", {"rough": 0.98}))
    if border > 0:
        outer_cs = mf.CrossSection([_profile(outline.tolist())])
        inner_cs = outer_cs.offset(-border, mf.JoinType.Round, 2.0, 12)
        polygons = inner_cs.to_polygons()
        if not polygons:
            raise GeometryError("rug: кайма съела всю середину; уменьшите border.")
        inner = _resample_loop(max(polygons, key=lambda p: len(p)), detail)
        band_vertices = []
        for loop in (inner, outline):
            for x, y in loop:
                band_vertices.append((x, y, height_fn(x, y) + 0.045))
        band_faces = []
        for i in range(detail):
            j = (i + 1) % detail
            band_faces.extend(((i, detail + i, detail + j), (i, detail + j, j)))
        band = _thicken_open(np.asarray(band_vertices), np.asarray(band_faces),
                             min(0.09, thickness * 0.3), "кайма ковра")
        parts.append((".border", band, border_color, "rug_border", {"rough": 0.94}))
    if binding > 0:
        path = np.asarray([[x, y, height_fn(x, y)] for x, y in outline] +
                          [[outline[0][0], outline[0][1], height_fn(*outline[0])]])
        cord = _tube_mesh(path, binding, 8, "окантовка ковра")
        parts.append((".binding", cord, border_color, "rug_binding", {"rough": 0.9}))
    if a.boolean("stitches", True):
        dash_count = min(160, detail)
        dash_length = max(0.2, 0.42 * 2 * math.pi * min(width, length) / dash_count)
        dashes = []
        for i in range(dash_count):
            p0 = outline[i]
            p1 = outline[(i + 1) % detail]
            tangent = p1 - p0
            tangent /= max(float(np.linalg.norm(tangent)), 1e-9)
            inward = np.asarray([-tangent[1], tangent[0]])
            middle = (p0 + p1) * 0.5 + inward * max(0.8, border * 0.45)
            start = middle - tangent * dash_length / 2
            end = middle + tangent * dash_length / 2
            z0, z1 = height_fn(*start) + 0.09, height_fn(*end) + 0.09
            dashes.append(_between((*start, z0), (*end, z1), 0.09, segments=6))
        if dashes:
            stitches = mf.Manifold.batch_boolean(dashes, mf.OpType.Add)
            parts.append((".stitches", stitches, border_color, "rug_stitches", {"rough": 0.9}))
    fringe = (a.text("fringe", "ends", ["none", "ends", "all"]) or "ends")
    fringe_count = int(a.num("fringe_count", 24, minv=0, maxv=80) or 0)
    fringe_length = float(a.num("fringe_length", 8.0, minv=0.1))
    strands = []
    if fringe != "none" and fringe_count:
        if fringe == "ends":
            for side in (-1, 1):
                for i in range(fringe_count):
                    x = -width * 0.47 + width * 0.94 * (i + 0.5) / fringe_count
                    y = side * length / 2
                    start = np.asarray([x, y, height_fn(x, y) - thickness * 0.35])
                    end = start + np.asarray([0.0, side * fringe_length, -0.25 * thickness])
                    strands.append(_between(start, end, 0.11, segments=6))
        else:
            loop = _resample_loop(outline, fringe_count)
            for x, y in loop:
                outward = np.asarray([x, y], dtype=float)
                outward /= max(float(np.linalg.norm(outward)), 1e-9)
                start = np.asarray([x, y, height_fn(x, y) - thickness * 0.35])
                end = start + np.asarray([*(outward * fringe_length), -0.25 * thickness])
                strands.append(_between(start, end, 0.11, segments=6))
    if strands:
        fringe_solid = mf.Manifold.batch_boolean(strands, mf.OpType.Add)
        parts.append((".fringe", fringe_solid, _color(a, "fringe_color", border_color),
                      "rug_fringe", {"rough": 0.95}))
    root = _emit(a, name, parts, {"width": width, "length": length, "shape": shape,
                                  "corner": corner, "thickness": thickness, "pad": pad,
                                  "border": border, "wave": wave, "lift": lift,
                                  "lift_corner": lift_corner, "fringe": fringe,
                                  "fringe_count": fringe_count, "detail": detail, "rings": rings})
    pattern_raw = a.text("pattern", "none") or "none"
    if pattern_raw.lower() not in ("none", "нет", "без"):
        root.paint = [{"color": _color(a, "pattern_color", border_color), "side": "верх",
                       "pattern": {"shape": pattern_shape(pattern_raw),
                                   "size": float(a.num("pattern_size", 3.0, minv=0.1)),
                                   "step": float(a.num("pattern_step", 10.0, minv=0.2)),
                                   "angle": float(a.num("pattern_angle", 0.0) or 0.0)}}]
    root.notes.append(f"ковёр: {len(vertices)} узлов верха, {len(strands)} нитей бахромы")
    return root


def _wall_plate(width, height, depth, corner):
    return _box((width, depth, height), (0, 0, height / 2), corner)


def _screw_y(x, y, z, radius=2.0):
    screw = _between((x, y, z), (x, y - 0.9, z), radius, segments=28)
    slot = _box((radius * 1.4, 1.4, radius * 0.28), (x, y - 0.55, z), 0)
    return screw - slot


@op("socket", aliases=("розетка", "power_socket"), category="Примитивы",
    summary="Одиночная/многоместная розетка: отдельная пластина, вставки с "
            "сквозными отверстиями, рамки, заземляющие контакты и винты.",
    example='розетка = socket sockets=2 pitch=72 holes=6 ground=да screws=да',
    params={"sockets": "число мест 1…3 (1)", "width": "ширина пластины; 0 = по числу мест",
            "height": "высота пластины (86)", "depth": "толщина пластины (10)",
            "pitch": "шаг между вставками (72)", "insert_radius": "радиус вставки (31)",
            "holes": "диаметр отверстий для штырей (6)", "pin_pitch": "межосевое расстояние (19)",
            "ground": "да — отдельные заземляющие контакты", "screws": "да — винты с прорезью",
            "corner": "скругление пластины (5)", "color": "цвет пластины",
            "insert_color": "цвет вставок", "metal_color": "цвет контактов и винтов",
            "at": "положение; лицевая сторона −Y", "center": "центрировать по Z"})
def socket(a, name):
    count = int(a.num("sockets", 1, minv=1, maxv=3) or 1)
    pitch = float(a.num("pitch", 72.0, minv=45.0))
    width_default = 86 + pitch * (count - 1)
    width_value = float(a.num("width", 0.0, minv=0.0) or 0.0)
    width = width_value or width_default
    if width < 50:
        raise GeometryError("socket: width=0 (авто) или не меньше 50 мм.")
    height = float(a.num("height", 86.0, minv=50.0))
    depth = float(a.num("depth", 10.0, minv=3.0))
    corner = float(a.num("corner", 5.0, minv=0.0) or 0.0)
    insert_r = float(a.num("insert_radius", 31.0, minv=20.0, maxv=height * 0.45))
    hole_d = float(a.num("holes", 6.0, minv=2.0, maxv=12.0))
    pin_pitch = float(a.num("pin_pitch", 19.0, minv=10.0, maxv=30.0))
    front = -depth / 2
    plate = _wall_plate(width, height, depth, corner)
    centers = [(i - (count - 1) / 2) * pitch for i in range(count)]
    # Отверстия продолжаются через пластину, а не упираются в глухую стенку.
    for x in centers:
        for dx in (-pin_pitch / 2, pin_pitch / 2):
            hole = _between((x + dx, depth, height / 2),
                            (x + dx, -depth, height / 2), hole_d / 2, segments=28)
            plate = plate - hole
    color = _color(a, "color", "#e7e2d8")
    insert_color = _color(a, "insert_color", "#f3f0e9")
    metal = _color(a, "metal_color", "#b8ad91")
    parts = [("", plate, color, "socket_plate", {"rough": 0.36})]
    for index, x in enumerate(centers, 1):
        z = height / 2
        insert = _between((x, front + 0.2, z), (x, front - 2.0, z), insert_r, segments=64)
        for dx in (-pin_pitch / 2, pin_pitch / 2):
            hole = _between((x + dx, front + 1, z), (x + dx, front - 3, z),
                            hole_d / 2, segments=28)
            insert = insert - hole
        parts.append((f".insert_{index}", insert, insert_color, "socket_insert", {"rough": 0.32}))
        outer = _between((x, front - 1.8, z), (x, front - 2.8, z), insert_r + 2.0, segments=64)
        inner = _between((x, front - 1.5, z), (x, front - 3.1, z), insert_r - 1.2, segments=64)
        parts.append((f".bezel_{index}", outer - inner, color, "socket_bezel", {"rough": 0.34}))
        if a.boolean("ground", True):
            for suffix, sign in (("top", 1), ("bottom", -1)):
                clip = _box((10, 2.2, 4.0), (x, front - 2.0, z + sign * 22.0), 0.5)
                parts.append((f".ground_{index}_{suffix}", clip, metal, "socket_ground",
                              {"metal": 0.75, "rough": 0.28}))
    if a.boolean("screws", True):
        for index, z in enumerate((7.0, height - 7.0), 1):
            parts.append((f".screw_{index}", _screw_y(0, front - 0.1, z), metal,
                          "socket_screw", {"metal": 0.7, "rough": 0.3}))
    return _emit(a, name, parts, {"sockets": count, "width": width, "height": height,
                                  "depth": depth, "pitch": pitch, "holes": hole_d,
                                  "pin_pitch": pin_pitch, "ground": a.boolean("ground", True)})


@op("switch", aliases=("выключатель", "light_switch"), category="Примитивы",
    summary="Выключатель с настоящими вырезами и отдельными клавишами. Современная "
            "клавиша имеет наклонную плоскость и нижнюю ступеньку; старая — более "
            "толстую выпуклую форму. Двойные/тройные клавиши, подсветка и винты "
            "остаются независимо выбираемыми деталями.",
    example='выключатель = switch rockers=2 style=современная state=on angle=7 led=да\n'
            'старый = switch style=старая state=off',
    params={"rockers": "число клавиш 1…3 (1)", "width": "ширина пластины; 0 = по числу клавиш",
            "height": "высота (86)", "depth": "толщина пластины (10)",
            "style": "современная или старая выпуклая клавиша (современная)",
            "state": "on/off — меняет наклон клавиш", "angle": "наклон клавиши, градусы (6)",
            "led": "да — отдельный светящийся индикатор", "screws": "да — винты",
            "corner": "скругление пластины (5)", "color": "цвет пластины",
            "rocker_color": "цвет клавиш", "led_color": "цвет индикатора",
            "metal_color": "цвет винтов",
            "at": "положение; лицевая сторона −Y", "center": "центрировать по Z"})
def switch(a, name):
    count = int(a.num("rockers", 1, minv=1, maxv=3) or 1)
    style = a.text("style", "современная", ["современная", "старая"])
    width_value = float(a.num("width", 0.0, minv=0.0) or 0.0)
    # Двойной выключатель по референсу остаётся на стандартной рамке 86 мм,
    # а не превращается в две отдельные одиночные пластины.
    width = width_value or (86.0 if count <= 2 else 128.0)
    if width < 50:
        raise GeometryError("switch: width=0 (авто) или не меньше 50 мм.")
    height = float(a.num("height", 86.0, minv=50.0))
    depth = float(a.num("depth", 10.0, minv=3.0))
    front = -depth / 2
    plate = _wall_plate(width, height, depth, float(a.num("corner", 5.0, minv=0.0) or 0.0))
    margin_x = 14.0 if count == 1 else (10.0 if count == 2 else 8.0)
    margin_z, gap = 9.0, 4.0
    rocker_w = (width - 2 * margin_x - (count - 1) * gap) / count
    rocker_h = height - 2 * margin_z
    if rocker_w < 14:
        raise GeometryError("switch: клавиши не помещаются в заданную ширину пластины.")
    centers = [(i - (count - 1) / 2) * (rocker_w + gap) for i in range(count)]
    old_w = min(rocker_w * 0.58, 26.0)
    old_h = rocker_h * 0.76
    opening_w = rocker_w + 1.2 if style == "современная" else old_w + 3.0
    opening_h = rocker_h + 1.2 if style == "современная" else old_h + 4.0
    for x in centers:
        opening = _box((opening_w, depth * 0.65, opening_h),
                       (x, front + depth * 0.2, height / 2), 1.2)
        plate = plate - opening
    color = _color(a, "color", "#e7e2d8")
    rocker_color = _color(a, "rocker_color", "#f3f0e9")
    metal = _color(a, "metal_color", "#b8ad91")
    parts = [("", plate, color, "switch_plate", {"rough": 0.36})]
    state = (a.text("state", "off", ["on", "off"]) or "off")
    angle = float(a.num("angle", 6.0, minv=0.0, maxv=20.0) or 0.0) * (1 if state == "on" else -1)
    for index, x in enumerate(centers, 1):
        if style == "современная":
            # Большая плоскость и более выступающая нижняя полка — это один
            # физический rocker, а не две независимо случайно склеенные детали.
            main = _box((rocker_w, 2.6, rocker_h - 5.0), (0, 0, 2.3), 1.0)
            lip = _box((rocker_w, 3.8, 5.4), (0, -0.3, -rocker_h / 2 + 2.7), 0.9)
            rocker = main + lip
        else:
            body = _box((old_w, 5.8, old_h), (0, 0, 0), 2.4)
            bulge = mf.Manifold.sphere(1.0, 40).scale(
                (old_w * 0.48, 3.0, old_h * 0.46)).translate((0, -2.0, 0))
            rocker = body + bulge
        rocker = rocker.rotate((angle, 0, 0)).translate((x, front + 0.2, height / 2))
        parts.append((f".rocker_{index}", rocker, rocker_color, "switch_rocker", {"rough": 0.3}))
        if a.boolean("led", False):
            led_color = _color(a, "led_color", "#77c9a6")
            led = _between((x, front - 1.4, height / 2 - rocker_h * 0.34),
                           (x, front - 2.0, height / 2 - rocker_h * 0.34), 1.2, segments=24)
            parts.append((f".led_{index}", led, led_color, "switch_led",
                          {"emissive": led_color, "emissive_strength": 1.8, "rough": 0.25}))
    if a.boolean("screws", True):
        screw_positions = ((0.0, 6.0), (0.0, height - 6.0)) if style == "современная" else (
            (-opening_w / 2 - 12.0, height / 2), (opening_w / 2 + 12.0, height / 2))
        for index, (sx, sz) in enumerate(screw_positions, 1):
            parts.append((f".screw_{index}", _screw_y(sx, front - 0.1, sz), metal,
                          "switch_screw", {"metal": 0.7, "rough": 0.3}))
    return _emit(a, name, parts, {"rockers": count, "width": width, "height": height,
                                  "depth": depth, "style": style, "state": state,
                                  "angle": angle, "led": a.boolean("led", False)})


def _bulb_outer(shape, neck, radius, base_z, height):
    """Плавный профиль: у круглых колб полюс купола не вырождается в остриё."""
    output = []

    def segment(t0, t1, radius_fn, steps=18):
        for i in range(steps):
            t = t0 + (t1 - t0) * i / steps
            u = (t - t0) / max(t1 - t0, 1e-12)
            output.append((float(radius_fn(u)), base_z + height * t))

    if shape == "tube":
        segment(0.0, 0.10, lambda u: neck + (radius - neck) * math.sin(u * math.pi / 2))
        segment(0.10, 0.76, lambda u: radius, steps=10)
        segment(0.76, 1.0, lambda u: radius * math.sqrt(max(0.0, 1.0 - u * u)), steps=22)
    else:
        shoulder = {"a60": 0.34, "globe": 0.24, "candle": 0.30, "pear": 0.30}[shape]
        segment(0.0, shoulder,
                lambda u: neck + (radius - neck) * math.sin(u * math.pi / 2), steps=20)
        if shape == "candle":
            # Свечная колба действительно завершается мягким остриём.
            segment(shoulder, 1.0, lambda u: radius * max(0.0, 1.0 - u ** 1.8) ** 1.3,
                    steps=28)
        elif shape == "pear":
            segment(shoulder, 1.0, lambda u: radius * math.sqrt(max(0.0, 1.0 - u ** 1.55)),
                    steps=28)
        else:
            # Эллиптический купол: dr/dz стремится к бесконечности у полюса,
            # поэтому верх круглый, а не «луковичный» cusp.
            segment(shoulder, 1.0, lambda u: radius * math.sqrt(max(0.0, 1.0 - u * u)),
                    steps=30)
    output.append((0.0, base_z + height))
    return np.asarray(output, dtype=float)


def _inward_offset(profile, wall):
    profile = np.asarray(profile, dtype=float)
    tangents = np.zeros_like(profile)
    tangents[1:-1] = profile[2:] - profile[:-2]
    tangents[0] = profile[1] - profile[0]
    tangents[-1] = profile[-1] - profile[-2]
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1)[:, None], 1e-12)
    normals = np.stack((tangents[:, 1], -tangents[:, 0]), axis=1)
    inner = profile - normals * wall
    inner[:, 0] = np.maximum(inner[:, 0], 0.0)
    return inner


@op("bulb", aliases=("лампочка", "лампа", "light_bulb"), category="Примитивы",
    summary="Лампочка с полым стеклом, формой колбы, цоколем E27/E14, контактом, "
            "настоящей или упрощённой резьбой и отдельным светящимся элементом.",
    example='лампа = bulb shape=a60 base=E27 diameter=60 height=110 glass_wall=0.6 '
            'thread=да glow=да glow_strength=3',
    params={"shape": "a60, globe, candle, tube или pear", "base": "E27 или E14",
            "diameter": "максимальный диаметр колбы (60)", "height": "общая высота (110)",
            "glass_wall": "толщина стекла (0.6)", "thread": "да — спиральная резьба; нет — гладкий цоколь",
            "pitch": "шаг резьбы; 0 = стандартный для цоколя",
            "glow": "да — отдельный светящийся элемент", "glow_strength": "яркость (3)",
            "glow_color": "цвет свечения", "glass_color": "цвет стекла",
            "base_color": "цвет цоколя, резьбы и контакта",
            "segments": "сегментов вращения 24…128 (64)",
            "at": "положение; ось +Z, контакт снизу", "center": "центрировать по Z"})
def bulb(a, name):
    shape = (a.text("shape", "a60", ["a60", "globe", "candle", "tube", "pear"]) or "a60")
    base_kind = (a.text("base", "E27", ["E27", "E14"]) or "E27")
    base_d = 27.0 if base_kind == "E27" else 14.0
    base_h = 20.0 if base_kind == "E27" else 15.0
    diameter = float(a.num("diameter", 60.0 if shape != "candle" else 38.0,
                           minv=base_d * 1.05))
    height = float(a.num("height", 110.0 if shape != "candle" else 95.0, minv=base_h * 2.0))
    wall = float(a.num("glass_wall", 0.6, minv=0.08, maxv=diameter * 0.08))
    segments = int(a.num("segments", 64, minv=24, maxv=128) or 64)
    outer = _bulb_outer(shape, base_d * 0.43, diameter / 2, base_h - 0.8, height - base_h + 0.8)
    inner = _inward_offset(outer, wall)
    profile = outer.tolist() + inner[::-1].tolist()
    glass = _revolve_profile(profile, segments, "полая колба")
    glass_color = _color(a, "glass_color", "#f2eee0")
    parts = [("", glass, glass_color, "bulb_glass",
              {"rough": 0.08, "transmission": 0.94})]
    base_r = base_d / 2
    metal = _color(a, "base_color", "#b8b2a5")
    shell = _cylinder(base_r * 0.94, base_h - 3.0, (0, 0, 2.4), segments=segments)
    parts.append((".base", shell, metal, "bulb_base", {"metal": 0.82, "rough": 0.25}))
    insulator = _cylinder(base_r * 0.72, 1.4, (0, 0, 1.2), segments=48)
    parts.append((".insulator", insulator, "#292827", "bulb_insulator", {"rough": 0.6}))
    contact = _cylinder(base_r * 0.48, 1.2, (0, 0, 0), r2=base_r * 0.42, segments=48)
    parts.append((".contact", contact, metal, "bulb_contact", {"metal": 0.85, "rough": 0.2}))
    if a.boolean("thread", True):
        standard_pitch = 3.6 if base_kind == "E27" else 2.8
        pitch = float(a.num("pitch", standard_pitch, minv=1.0))
        turns = max(2.0, (base_h - 5.0) / pitch)
        steps = max(48, int(math.ceil(turns * 28)))
        path = []
        for i in range(steps + 1):
            t = i / steps
            angle = 2 * math.pi * turns * t
            path.append((base_r * math.cos(angle), base_r * math.sin(angle), 3.2 + turns * pitch * t))
        thread = _tube_mesh(np.asarray(path), 0.62 if base_kind == "E27" else 0.45,
                            8, "резьба цоколя")
        parts.append((".thread", thread, metal, "bulb_thread", {"metal": 0.82, "rough": 0.25}))
    if a.boolean("glow", True):
        glow_color = _color(a, "glow_color", "#ffd7a0")
        strength = float(a.num("glow_strength", 3.0, minv=0.0))
        glow_r = min(diameter * 0.12, (height - base_h) * 0.16)
        glow = mf.Manifold.sphere(glow_r, 32).scale((1.0, 1.0, 1.5)).translate(
            (0, 0, base_h + (height - base_h) * 0.52))
        parts.append((".glow", glow, glow_color, "bulb_glow",
                      {"emissive": glow_color, "emissive_strength": strength, "rough": 0.35}))
    root = _emit(a, name, parts, {"shape": shape, "base": base_kind, "diameter": diameter,
                                  "height": height, "glass_wall": wall,
                                  "thread": a.boolean("thread", True),
                                  "glow": a.boolean("glow", True), "segments": segments})
    root.meta["hollow_glass"] = True
    return root
