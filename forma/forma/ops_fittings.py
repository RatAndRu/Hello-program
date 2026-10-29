"""Железнодорожный путь и редактируемая дверная фурнитура.

Все сборки состоят из обычных объектов сцены. Общие вспомогательные детали
не регистрируются как скрытые заготовки: рельсы, шпалы, крепления и створки
петли сразу создаются в окончательном виде и доступны для правок и GLB.
"""
from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import (circle_profile, manifold_from_arrays, manifold_mesh,
                       normalize_color, sweep_solid)
from .ops import make_solid, op
from .shape_features import rounded_extrude


def _rounded_rect(width: float, height: float, radius: float,
                  segments: int = 8) -> np.ndarray:
    w, h = float(width), float(height)
    r = min(max(0.0, float(radius)), w * 0.499, h * 0.499)
    if r <= 1e-8:
        return np.asarray([(-w / 2, -h / 2), (w / 2, -h / 2),
                           (w / 2, h / 2), (-w / 2, h / 2)], dtype=float)
    points = []
    corners = ((w / 2 - r, h / 2 - r, 0.0),
               (-w / 2 + r, h / 2 - r, 90.0),
               (-w / 2 + r, -h / 2 + r, 180.0),
               (w / 2 - r, -h / 2 + r, 270.0))
    for cx, cy, start in corners:
        for i in range(segments + 1):
            angle = math.radians(start + 90.0 * i / segments)
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return np.asarray(points, dtype=float)


def _compound(parts: list[mf.Manifold], what: str) -> mf.Manifold:
    """Соединяет непересекающиеся тела без булевых и без сшивания их вершин."""
    parts = [p for p in parts if p is not None and not p.is_empty()]
    if not parts:
        raise GeometryError(f"{what}: пустая сборка")
    if len(parts) == 1:
        return parts[0]
    vertices, faces = [], []
    offset = 0
    for part in parts:
        v, f = manifold_mesh(part)
        v = np.asarray(v, dtype=float)[:, :3]
        f = np.asarray(f, dtype=np.int64)
        vertices.append(v)
        faces.append(f + offset)
        offset += len(v)
    result = manifold_from_arrays(np.concatenate(vertices), np.concatenate(faces), what)
    if result.status() != mf.Error.NoError:
        raise GeometryError(f"{what}: ошибка составной сетки {result.status().name}")
    return result


def _one(manifold: mf.Manifold, what: str) -> mf.Manifold:
    positive = [p for p in manifold.decompose() if p.volume() > 1e-7]
    if (manifold.status() != mf.Error.NoError or manifold.is_empty()
            or manifold.volume() <= 1e-7 or len(positive) != 1):
        raise GeometryError(f"{what}: деталь не является одним замкнутым телом")
    return manifold


def _part_color(a, key: str, default: str) -> str:
    return normalize_color(a.text(key, a.text("color", default) or default) or default)


def _assembly(a, name: str, parts: list[tuple], params: dict, family: str):
    """parts: (suffix, solid, color_key, default_color, metal, rough, kind)."""
    bounds = [part[1].bounding_box() for part in parts]
    lo = np.min(np.asarray([b[:3] for b in bounds], dtype=float), axis=0)
    hi = np.max(np.asarray([b[3:] for b in bounds], dtype=float), axis=0)
    at = np.asarray(a.vec("at", 3, default=(0, 0, 0)), dtype=float)
    shift = at - (lo + hi) * 0.5 if a.boolean("center", False) else at
    root = None
    for suffix, manifold, color_key, default_color, metal, rough, kind in parts:
        if np.any(np.abs(shift) > 1e-12):
            manifold = manifold.translate(tuple(float(v) for v in shift))
        made = make_solid(a.scene, name if not suffix else f"{name}{suffix}",
                          manifold, a, base=root, kind=kind)
        made.color = _part_color(a, color_key, default_color)
        if not a.has("metal"):
            made.metal = float(metal)
        if not a.has("rough"):
            made.rough = float(rough)
        made.meta["assembly_root"] = name
        if root is None:
            root = made
        else:
            made.meta["parent"] = name
    if root is None:
        raise GeometryError(f"{family}: не создано ни одной детали")
    root.meta["primitive_params"] = dict(params)
    root.meta[f"{family}_params"] = dict(params)
    return root


def _arc(points: list, center: tuple[float, float], radius: float,
         a0: float, a1: float, steps: int = 5) -> None:
    cx, cy = center
    for i in range(1, steps + 1):
        angle = math.radians(a0 + (a1 - a0) * i / steps)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))


def _dedupe(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    for point in points:
        p = (float(point[0]), float(point[1]))
        if not out or math.dist(out[-1], p) > 1e-8:
            out.append(p)
    if len(out) > 2 and math.dist(out[0], out[-1]) < 1e-8:
        out.pop()
    return out


def _rail_cross(profile: str, height: float, head_w: float, head_h: float,
                web: float, foot_w: float, foot_h: float,
                fillet: float) -> mf.CrossSection:
    if head_h >= height * 0.65 or foot_h >= height - head_h:
        raise GeometryError("track: head_height/foot_height не оставляют места стенке рельсы")
    if web >= min(head_w, foot_w) * 0.9:
        raise GeometryError("track: web должен быть заметно уже головки и подошвы")
    if profile == "брусок":
        return mf.CrossSection([_rounded_rect(head_w, height, fillet, 6)
                                + np.asarray([0.0, height / 2.0])])
    if profile == "двутавр":
        foot_w, foot_h = head_w, head_h
    z_head = height - head_h
    f = min(fillet, head_h * 0.28, (head_w - web) * 0.22,
            max(0.05, (z_head - foot_h) * 0.22))
    if profile == "т":
        foot_w, foot_h = web, 0.0
    if foot_w <= web + 0.1:
        foot_w = web + 0.1
    f = min(f, max(0.0, (foot_w - web) * 0.22))
    corner = min(max(0.05, f), head_h * 0.20, head_w * 0.10)
    right: list[tuple[float, float]] = []
    if foot_h > 1e-8:
        right.extend(((foot_w / 2, 0.0), (foot_w / 2, foot_h * 0.45),
                      (foot_w / 2 - min(foot_h * 0.65, foot_w * 0.12), foot_h)))
        if f > 0.05:
            right.append((web / 2 + f, foot_h))
            _arc(right, (web / 2 + f, foot_h + f), f, -90.0, -180.0, 5)
        else:
            right.append((web / 2, foot_h))
    else:
        right.append((web / 2, 0.0))
    if f > 0.05:
        right.append((web / 2, z_head - f))
        _arc(right, (web / 2 + f, z_head - f), f, 180.0, 90.0, 5)
    else:
        right.append((web / 2, z_head))
    right.append((head_w / 2 - corner, z_head))
    _arc(right, (head_w / 2 - corner, z_head + corner), corner, -90.0, 0.0, 4)
    right.append((head_w / 2, height - corner))
    _arc(right, (head_w / 2 - corner, height - corner), corner, 0.0, 90.0, 4)
    right = _dedupe(right)
    points = _dedupe(right + [(-x, z) for x, z in reversed(right)])
    cross = mf.CrossSection([np.asarray(points, dtype=float)])
    if cross.is_empty() or cross.area() <= 1e-8:
        raise GeometryError("track: профиль рельсы самопересекается или вырожден")
    return cross


def _rail_solid(cross: mf.CrossSection, length: float, x: float,
                z: float) -> mf.Manifold:
    return cross.extrude(length).rotate((90.0, 0.0, 0.0)).translate(
        (x, length / 2.0, z))


@op("track", aliases=("railway_track", "rail", "рельсовый_путь",
                       "железнодорожный_путь", "железная_дорога"),
    category="Примитивы",
    summary="Железнодорожный путь вдоль Y: одна или две рельсы с настоящим "
            "профилем, отключаемые фасонные шпалы, подкладки и крепления. "
            "Рельс стоит на подкладке в углублении шпалы. Детали сборки "
            "остаются отдельными: <имя>, <имя>.sleepers и <имя>.fasteners.",
    example="путь = track length=720 rails=2 gauge=180 sleepers=да fasteners=да\n"
            "одна = track length=500 rails=1 sleepers=нет rail_profile=двутавр\n"
            "бетон = track length=900 sleeper_shape=бетонная sleeper_step=75",
    params={"length": "длина пути по Y, мм (720)",
            "rails": "число рельс: 1 или 2 (2)",
            "gauge": "расстояние между осями рельс по X, мм (180)",
            "rail_profile": "рельса, двутавр, т или брусок (рельса)",
            "rail_height": "высота рельсы, мм (28)",
            "head_width": "ширина головки, мм (14)",
            "head_height": "высота головки, мм (7)",
            "web": "толщина стенки, мм (3)",
            "foot_width": "ширина подошвы, мм (24)",
            "foot_height": "высота подошвы, мм (4)",
            "rail_fillet": "радиусы сопряжения профиля, мм (1.2)",
            "sleepers": "шпалы да/нет (да)",
            "sleeper_shape": "скошенная, бетонная или брусок (скошенная)",
            "sleeper_count": "число шпал; 0 — автоматически по шагу (0)",
            "sleeper_step": "шаг шпал по Y, мм (65)",
            "sleeper_length": "длина шпалы по X, мм (250)",
            "sleeper_width": "ширина шпалы по Y, мм (32)",
            "sleeper_height": "высота шпалы, мм (16)",
            "sleeper_bevel": "скругление/скос шпалы, мм (2)",
            "fasteners": "подкладки, прижимы и гайки да/нет (да)",
            "plate_thickness": "толщина подкладки, мм (1.2)",
            "segments": "сегментов дуг профиля и крепления 12…64 (32)",
            "rail_color": "цвет рельс (steel); color окрашивает всю сборку",
            "sleeper_color": "цвет шпал (#62534a)",
            "fastener_color": "цвет креплений (#454c53)",
            "at": "сдвиг локального начала [x,y,z]; низ сборки на z=0",
            "center": "центрировать всю сборку в at (нет)"},
    positional=["length"])
def track(a, name):
    length = float(a.num("length", 720.0, minv=40.0, maxv=100000.0))
    rails = int(a.int("rails", 2, minv=1, maxv=2) or 2)
    gauge = float(a.num("gauge", 180.0, minv=30.0, maxv=10000.0))
    raw_profile = (a.text("rail_profile", "рельса") or "рельса").strip().lower()
    profile = {"рельса": "рельса", "железнодорожный": "рельса", "rail": "рельса",
               "двутавр": "двутавр", "i": "двутавр", "т": "т", "t": "т",
               "брусок": "брусок", "прямоугольный": "брусок"}.get(raw_profile)
    if profile is None:
        raise GeometryError("track: rail_profile=рельса, двутавр, т или брусок")
    height = float(a.num("rail_height", 28.0, minv=5.0, maxv=1000.0))
    head_w = float(a.num("head_width", 14.0, minv=2.0, maxv=500.0))
    head_h = float(a.num("head_height", 7.0, minv=1.0, maxv=500.0))
    web = float(a.num("web", 3.0, minv=0.4, maxv=200.0))
    foot_w = float(a.num("foot_width", 24.0, minv=2.0, maxv=500.0))
    foot_h = float(a.num("foot_height", 4.0, minv=0.4, maxv=500.0))
    fillet = float(a.num("rail_fillet", 1.2, minv=0.0, maxv=100.0) or 0.0)
    sleepers_on = a.boolean("sleepers", True)
    raw_sleeper = (a.text("sleeper_shape", "скошенная") or "скошенная").strip().lower()
    sleeper_shape = {"скошенная": "скошенная", "скруглённая": "скошенная",
                     "скругленная": "скошенная", "бетонная": "бетонная",
                     "брусок": "брусок", "прямоугольная": "брусок"}.get(raw_sleeper)
    if sleeper_shape is None:
        raise GeometryError("track: sleeper_shape=скошенная, бетонная или брусок")
    step = float(a.num("sleeper_step", 65.0, minv=10.0, maxv=10000.0))
    count = int(a.int("sleeper_count", 0, minv=0, maxv=1000) or 0)
    sleeper_l = float(a.num("sleeper_length", 250.0, minv=30.0, maxv=10000.0))
    sleeper_w = float(a.num("sleeper_width", 32.0, minv=5.0, maxv=1000.0))
    sleeper_h = float(a.num("sleeper_height", 16.0, minv=2.0, maxv=1000.0))
    sleeper_bevel = float(a.num("sleeper_bevel", 2.0, minv=0.0, maxv=100.0) or 0.0)
    fasteners = a.boolean("fasteners", True)
    if not sleepers_on:
        if fasteners and a.has("fasteners"):
            raise GeometryError("track: fasteners=да требует sleepers=да")
        fasteners = False
    plate_t = float(a.num("plate_thickness", 1.2, minv=0.2, maxv=100.0)) if fasteners else 0.0
    segments = int(a.int("segments", 32, minv=12, maxv=64) or 32)
    centers = [0.0] if rails == 1 else [-gauge / 2.0, gauge / 2.0]
    if rails == 2 and gauge <= foot_w + 4.0:
        raise GeometryError("track: gauge слишком мал для двух подошв рельс")
    if rails == 2 and sleeper_l <= gauge + foot_w + 8.0:
        raise GeometryError("track: sleeper_length должна перекрывать колею и обе подошвы")
    seat_depth = min(0.9, sleeper_h * 0.12) if sleepers_on else 0.0
    rail_z = sleeper_h - seat_depth + plate_t if sleepers_on else 0.0
    cross = _rail_cross(profile, height, head_w, head_h, web, foot_w, foot_h, fillet)
    rail_parts = [_rail_solid(cross, length, x, rail_z) for x in centers]
    rail_solid = _compound(rail_parts, "рельсы")
    parts = [("", rail_solid, "rail_color", "#78828b", 0.78, 0.30, "track")]
    positions = []
    if sleepers_on:
        if count <= 0:
            count = max(1, int(math.floor(length / step)) + 1)
        actual_step = step
        if count == 1:
            positions = [0.0]
        else:
            actual_step = min(step, (length - sleeper_w) / (count - 1)) \
                if length > sleeper_w else 0.0
            if actual_step < sleeper_w + 0.05:
                raise GeometryError(
                    "track: шпалы перекрываются по Y — увеличьте sleeper_step/length "
                    "или уменьшите sleeper_count/sleeper_width")
            positions = [(i - (count - 1) / 2.0) * actual_step for i in range(count)]
        if sleeper_shape == "брусок" or sleeper_bevel <= 1e-7:
            master = mf.Manifold.cube((sleeper_l, sleeper_w, sleeper_h), True).translate(
                (0.0, 0.0, sleeper_h / 2.0))
        else:
            radius = min(sleeper_bevel, sleeper_h * 0.42, sleeper_w * 0.18)
            outline = _rounded_rect(sleeper_l, sleeper_w, radius, 6)
            master = rounded_extrude(mf.CrossSection([outline]), sleeper_h, radius,
                                     "шпала", 16)
        if sleeper_shape == "бетонная":
            dip = sleeper_h * 0.16
            cutter = mf.Manifold.cube((sleeper_l * 0.24, sleeper_w + 2.0, dip + 1.0), True)
            master = master - cutter.translate((0.0, 0.0, sleeper_h - dip / 2.0 + 0.5))
        for x in centers:
            cutter = mf.Manifold.cube((foot_w + 10.0, sleeper_w + 2.0,
                                       seat_depth + 0.6), True).translate(
                (x, 0.0, sleeper_h - seat_depth / 2.0 + 0.3))
            master = master - cutter
        _one(master, "шпала")
        sleepers = _compound([master.translate((0.0, y, 0.0)) for y in positions], "шпалы")
        parts.append((".sleepers", sleepers, "sleeper_color", "#62534a", 0.0, 0.82,
                      "track_sleepers"))
    if fasteners:
        per_rail = []
        bolt_r = max(1.2, min(2.2, foot_w * 0.085))
        for x in centers:
            plate_bottom = rail_z - plate_t
            plate = mf.Manifold.cube((foot_w + 9.0, sleeper_w * 0.64, plate_t), True).translate(
                (x, 0.0, plate_bottom + plate_t / 2.0))
            pieces = [plate]
            for sign in (-1.0, 1.0):
                edge = x + sign * foot_w / 2.0
                clip_x = edge + sign * 2.0
                clip = mf.Manifold.cube((4.0, sleeper_w * 0.32, 1.2), True).translate(
                    (clip_x, 0.0, rail_z + 0.4))
                bolt_x = edge + sign * 3.0
                shank = mf.Manifold.cylinder(plate_t + 1.4, bolt_r * 0.45, bolt_r * 0.45,
                                             max(12, segments // 2)).translate(
                    (bolt_x, 0.0, plate_bottom))
                head = mf.Manifold.cylinder(1.8, bolt_r, bolt_r, 6).translate(
                    (bolt_x, 0.0, rail_z + 0.8))
                pieces.extend((clip, shank, head))
            per_rail.append(mf.Manifold.batch_boolean(pieces, mf.OpType.Add))
        fastener_parts = []
        for master in per_rail:
            _one(master, "крепление рельсы")
            fastener_parts.extend(master.translate((0.0, y, 0.0)) for y in positions)
        fasteners_solid = _compound(fastener_parts, "крепления пути")
        parts.append((".fasteners", fasteners_solid, "fastener_color", "#454c53", 0.72, 0.38,
                      "track_fasteners"))
    params = dict(length=length, rails=rails, gauge=gauge if rails == 2 else 0.0,
                  rail_profile=profile, rail_height=height, head_width=head_w,
                  head_height=head_h, web=web, foot_width=foot_w, foot_height=foot_h,
                  rail_fillet=fillet, sleepers=sleepers_on, sleeper_shape=sleeper_shape,
                  sleeper_count=len(positions),
                  sleeper_step=actual_step if sleepers_on and len(positions) > 1 else step,
                  sleeper_step_requested=step,
                  sleeper_length=sleeper_l, sleeper_width=sleeper_w,
                  sleeper_height=sleeper_h, sleeper_bevel=sleeper_bevel,
                  fasteners=fasteners, plate_thickness=plate_t, segments=segments)
    root = _assembly(a, name, parts, params, "track")
    root.notes.append(f"путь: {rails} рельс(ы), длина {length:g}, колея {params['gauge']:g}, "
                      f"шпал {len(positions)}, крепления={'да' if fasteners else 'нет'}")
    return root


def _hinge_leaf(width: float, height: float, thickness: float, corner: float,
                holes: int, hole_d: float, countersink: bool,
                segments: int) -> mf.Manifold:
    outline = _rounded_rect(width, height, corner, 8) + np.asarray([0.0, height / 2.0])
    leaf = mf.CrossSection([outline]).extrude(thickness)
    hole_r = hole_d / 2.0
    for i in range(holes):
        z = height * (i + 1) / (holes + 1)
        leaf = leaf - mf.Manifold.cylinder(thickness + 1.0, hole_r, hole_r, segments).translate(
            (0.0, z, -0.5))
        if countersink:
            outer = hole_r * 1.55
            depth = min(thickness * 0.55, outer - hole_r)
            if depth > 0.05:
                cone = mf.Manifold.cylinder(depth + 0.35, hole_r, outer, segments).translate(
                    (0.0, z, thickness - depth))
                leaf = leaf - cone
    return leaf.rotate((90.0, 0.0, 0.0)).translate((0.0, thickness / 2.0, 0.0))


@op("hinge", aliases=("петля", "дверная_петля", "мебельная_петля", "butt_hinge"),
    category="Примитивы",
    summary="Дверная петля из РОВНО ДВУХ редактируемых створок. Чередующиеся "
            "кулаки имеют осевой зазор; палец принадлежит левой створке, в "
            "правой — сквозное отверстие с clearance. Отверстия под шурупы "
            "настоящие, с optional зенковкой. open_angle поворачивает правую "
            "створку вокруг оси Z. Объекты: <имя> и <имя>.right.",
    example="петля = hinge height=90 leaf_width=38 barrel_d=11 knuckles=5 holes=3\n"
            "открытая = hinge height=100 open_angle=65 holes=4 countersink=да",
    params={"height": "высота створок по Z, мм (90)",
            "leaf_width": "ширина каждой створки от кулака, мм (38)",
            "thickness": "толщина створки, мм (2.2)",
            "corner": "радиус наружных углов, мм (4)",
            "barrel_d": "наружный диаметр кулаков, мм (11)",
            "pin_d": "диаметр пальца, мм (0.44 × barrel_d)",
            "knuckles": "нечётное число кулаков 3, 5, 7… (5)",
            "knuckle_gap": "осевой зазор между кулаками, мм (0.25)",
            "clearance": "радиальный зазор отверстия вокруг пальца, мм (0.18)",
            "barrel_overhang": "выход кулаков за верх/низ створок, мм (1)",
            "holes": "отверстий в каждой створке 0…8 (3)",
            "hole_d": "диаметр отверстий, мм (5)",
            "countersink": "зенковка на лицевой стороне −Y да/нет (да)",
            "open_angle": "поворот правой створки в сторону закрытия 0…180° (0)",
            "segments": "сегментов цилиндров 16…96 (48)",
            "left_color": "цвет левой створки и пальца (#aeb7bf)",
            "right_color": "цвет правой створки (#aeb7bf)",
            "at": "сдвиг оси петли [x,y,z]; низ створок на z=0",
            "center": "центрировать сборку в at (нет)"},
    positional=["height"])
def hinge(a, name):
    height = float(a.num("height", 90.0, minv=20.0, maxv=3000.0))
    leaf_w = float(a.num("leaf_width", 38.0, minv=10.0, maxv=1000.0))
    thickness = float(a.num("thickness", 2.2, minv=0.4, maxv=100.0))
    corner = float(a.num("corner", 4.0, minv=0.0, maxv=100.0) or 0.0)
    barrel_d = float(a.num("barrel_d", 11.0, minv=4.0, maxv=300.0))
    barrel_r = barrel_d / 2.0
    pin_d = float(a.num("pin_d", barrel_d * 0.44, minv=0.8, maxv=barrel_d * 0.85))
    pin_r = pin_d / 2.0
    knuckles = int(a.int("knuckles", 5, minv=3, maxv=15) or 5)
    if knuckles % 2 == 0:
        raise GeometryError("hinge: knuckles должно быть нечётным, чтобы верх и низ были на одной створке")
    gap = float(a.num("knuckle_gap", 0.25, minv=0.02, maxv=5.0))
    clearance = float(a.num("clearance", 0.18, minv=0.02, maxv=2.0))
    overhang = float(a.num("barrel_overhang", 1.0, minv=0.0, maxv=50.0) or 0.0)
    holes = int(a.int("holes", 3, minv=0, maxv=8) or 0)
    hole_d = float(a.num("hole_d", 5.0, minv=1.0, maxv=30.0))
    if hole_d >= leaf_w * 0.65:
        raise GeometryError("hinge: hole_d слишком велик для створки")
    countersink = a.boolean("countersink", True)
    open_angle = float(a.num("open_angle", 0.0, minv=0.0, maxv=180.0) or 0.0)
    segments = int(a.int("segments", 48, minv=16, maxv=96) or 48)
    if pin_r + clearance >= barrel_r - 0.25:
        raise GeometryError("hinge: палец и clearance не оставляют стенку кулака")
    barrel_h = height + 2.0 * overhang
    if barrel_h / knuckles <= gap + 0.2:
        raise GeometryError("hinge: knuckle_gap съедает кулаки")
    leaf = _hinge_leaf(leaf_w, height, thickness, corner, holes, hole_d,
                       countersink, segments)
    inner = barrel_r * 0.55
    # Ось вынесена от средней плоскости створок: при закрытии на 180° листы
    # занимают параллельные плоскости с зазором, а не входят друг в друга.
    plate_y = thickness * 0.65 + 0.12
    left_plate = leaf.translate((-inner - leaf_w / 2.0, plate_y, 0.0))
    right_plate = leaf.translate((inner + leaf_w / 2.0, plate_y, 0.0))
    left_knuckles, right_knuckles = [], []
    step = barrel_h / knuckles
    for i in range(knuckles):
        z0 = -overhang + i * step + gap / 2.0
        z1 = -overhang + (i + 1) * step - gap / 2.0
        knuckle = mf.Manifold.cylinder(z1 - z0, barrel_r, barrel_r, segments).translate(
            (0.0, 0.0, z0))
        # В реальной петле край створки не проходит сквозь чужие кулаки.
        # Вырезаем их с небольшим радиальным зазором до объединения.
        relief = mf.Manifold.cylinder(z1 - z0, barrel_r + 0.08, barrel_r + 0.08,
                                      segments).translate((0.0, 0.0, z0))
        if i % 2 == 0:
            left_knuckles.append(knuckle)
            right_plate = right_plate - relief
        else:
            right_knuckles.append(knuckle)
            left_plate = left_plate - relief
    pin = mf.Manifold.cylinder(barrel_h + 0.4, pin_r, pin_r, segments).translate(
        (0.0, 0.0, -overhang - 0.2))
    head_h = min(0.9, barrel_r * 0.22)
    bottom_head = mf.Manifold.cylinder(head_h + 0.2, barrel_r * 0.94, barrel_r * 0.94,
                                      segments).translate((0.0, 0.0, -overhang - head_h))
    top_head = mf.Manifold.cylinder(head_h + 0.2, barrel_r * 0.94, barrel_r * 0.94,
                                   segments).translate((0.0, 0.0, height + overhang - 0.2))
    for head in (bottom_head, top_head):
        head_relief = mf.Manifold.cylinder(head_h + 0.2, barrel_r * 0.94 + 0.08,
                                           barrel_r * 0.94 + 0.08, segments)
        head_bb = head.bounding_box()
        right_plate = right_plate - head_relief.translate((0.0, 0.0, head_bb[2]))
    left_parts = [left_plate, *left_knuckles, pin, bottom_head, top_head]
    right_parts = [right_plate, *right_knuckles]
    left = _one(mf.Manifold.batch_boolean(left_parts, mf.OpType.Add), "левая створка петли")
    right = mf.Manifold.batch_boolean(right_parts, mf.OpType.Add)
    bore = mf.Manifold.cylinder(barrel_h + 2.0, pin_r + clearance, pin_r + clearance,
                                segments).translate((0.0, 0.0, -overhang - 1.0))
    right = _one(right - bore, "правая створка петли")
    if abs(open_angle) > 1e-9:
        right = right.rotate((0.0, 0.0, -open_angle))
    params = dict(height=height, leaf_width=leaf_w, thickness=thickness, corner=corner,
                  barrel_d=barrel_d, pin_d=pin_d, knuckles=knuckles, knuckle_gap=gap,
                  clearance=clearance, barrel_overhang=overhang, holes=holes,
                  hole_d=hole_d, countersink=countersink, open_angle=open_angle,
                  segments=segments, objects=2)
    parts = [("", left, "left_color", "#aeb7bf", 0.82, 0.25, "hinge"),
             (".right", right, "right_color", "#aeb7bf", 0.82, 0.25, "hinge_leaf")]
    root = _assembly(a, name, parts, params, "hinge")
    root.notes.append(f"петля: две створки, {knuckles} кулаков, {holes} отверстий на створку, "
                      f"угол {open_angle:g}°")
    return root


def _rounded_cylinder(radius: float, height: float, edge: float,
                      segments: int) -> mf.Manifold:
    r = min(max(0.0, edge), radius * 0.45, height * 0.45)
    if r <= 1e-7:
        return mf.Manifold.cylinder(height, radius, radius, segments)
    profile = [(0.0, 0.0), (radius - r, 0.0)]
    _arc(profile, (radius - r, r), r, -90.0, 0.0, 5)
    profile.append((radius, height - r))
    _arc(profile, (radius - r, height - r), r, 0.0, 90.0, 5)
    profile.append((0.0, height))
    return mf.Manifold.revolve(mf.CrossSection([np.asarray(profile, dtype=float)]), segments)


def _y_solid(solid: mf.Manifold, depth: float, z: float) -> mf.Manifold:
    return solid.rotate((90.0, 0.0, 0.0)).translate((0.0, -depth, z))


def _bezier(points: list[tuple[float, float, float]], samples: int) -> np.ndarray:
    p = np.asarray(points, dtype=float)
    t = np.linspace(0.0, 1.0, samples)[:, None]
    return ((1 - t) ** 3 * p[0] + 3 * (1 - t) ** 2 * t * p[1]
            + 3 * (1 - t) * t ** 2 * p[2] + t ** 3 * p[3])


@op("door_handle", aliases=("дверная_ручка", "ручка_двери", "door_knob"),
    category="Примитивы",
    summary="Дверная ручка на розетке: четыре действительно разные формы. "
            "form=изогнутая — Г-образный рычаг, рельефная — рычаг с переменным "
            "сечением и продольным ребром, сферическая — шар, дисковая — "
            "круглая приплюснутая ручка. Дверь — плоскость XZ, вынос идёт в −Y, "
            "рычаг по умолчанию направлен +X.",
    example="ручка = door_handle form=изогнутая lever_length=115 projection=45\n"
            "лепесток = door_handle form=рельефная lever_length=120 relief=.6\n"
            "шар = door_handle form=сферическая knob_d=56\n"
            "диск = door_handle form=дисковая knob_d=58 disk_t=18",
    params={"form": "изогнутая, рельефная, сферическая или дисковая (изогнутая)",
            "rosette_d": "диаметр розетки, мм (52)",
            "rosette_t": "толщина розетки, мм (6)",
            "neck_d": "диаметр соединительной шейки, мм (16)",
            "projection": "вынос оси ручки от двери в −Y, мм (45)",
            "lever_length": "длина рычага по X, мм (115; только рычаги)",
            "lever_d": "толщина рычага, мм (17; только рычаги)",
            "relief": "высота продольного ребра 0…1 (0.55; только рельефная)",
            "knob_d": "диаметр сферы или диска, мм (56)",
            "disk_t": "толщина диска по Y, мм (18; только дисковая)",
            "hand": "направление рычага: право (+X) или лево (−X) (право)",
            "segments": "сегментов вращения 24…96 (48)",
            "at": "сдвиг локального начала [x,y,z]; розетка на двери y=0",
            "center": "центрировать всю ручку в at (нет)"},
    positional=["form"])
def door_handle(a, name):
    raw = (a.text("form", "изогнутая") or "изогнутая").strip().lower()
    form = {"изогнутая": "изогнутая", "г": "изогнутая", "г-образная": "изогнутая",
            "рычаг": "изогнутая", "lever": "изогнутая",
            "рельефная": "рельефная", "лепесток": "рельефная", "sculpted": "рельефная",
            "сферическая": "сферическая", "сфера": "сферическая", "шар": "сферическая",
            "sphere": "сферическая", "дисковая": "дисковая", "диск": "дисковая",
            "disk": "дисковая"}.get(raw)
    if form is None:
        raise GeometryError("door_handle: form=изогнутая, рельефная, сферическая или дисковая")
    rosette_d = float(a.num("rosette_d", 52.0, minv=16.0, maxv=500.0))
    rosette_t = float(a.num("rosette_t", 6.0, minv=1.0, maxv=100.0))
    neck_d = float(a.num("neck_d", 16.0, minv=3.0, maxv=100.0))
    projection = float(a.num("projection", 45.0, minv=12.0, maxv=500.0))
    lever_l = float(a.num("lever_length", 115.0, minv=35.0, maxv=1000.0))
    lever_d = float(a.num("lever_d", 17.0, minv=4.0, maxv=100.0))
    relief = float(a.num("relief", 0.55, minv=0.0, maxv=1.0))
    knob_d = float(a.num("knob_d", 56.0, minv=16.0, maxv=300.0))
    disk_t = float(a.num("disk_t", 18.0, minv=4.0, maxv=100.0))
    hand = (a.text("hand", "право") or "право").strip().lower()
    if hand not in ("право", "правый", "right", "лево", "левый", "left"):
        raise GeometryError("door_handle: hand=право или лево")
    segments = int(a.int("segments", 48, minv=24, maxv=96) or 48)
    if projection <= rosette_t + 2.0:
        raise GeometryError("door_handle: projection должен быть больше толщины розетки")
    knob_r = knob_d / 2.0
    zc = max(rosette_d / 2.0, knob_r if form in ("сферическая", "дисковая") else lever_d)
    rosette = _y_solid(_rounded_cylinder(rosette_d / 2.0, rosette_t, 1.2, segments), 0.0, zc)
    parts = [rosette]
    if form in ("сферическая", "дисковая"):
        neck = mf.Manifold.cylinder(projection - rosette_t + 0.8, neck_d / 2.0,
                                    neck_d / 2.0, segments)
        parts.append(_y_solid(neck, rosette_t - 0.4, zc))
        if form == "сферическая":
            parts.append(mf.Manifold.sphere(knob_r, segments).translate((0.0, -projection, zc)))
        else:
            disk = _rounded_cylinder(knob_r, disk_t, min(2.2, disk_t * 0.22), segments)
            parts.append(_y_solid(disk, projection - disk_t / 2.0, zc))
    else:
        neck_h = projection - rosette_t + lever_d * 0.25
        neck = mf.Manifold.cylinder(neck_h, neck_d / 2.0, neck_d / 2.0, segments)
        parts.append(_y_solid(neck, rosette_t - 0.4, zc))
        if form == "изогнутая":
            controls = [(0.0, -projection, zc),
                        (lever_l * 0.14, -projection - 6.0, zc + lever_l * 0.055),
                        (lever_l * 0.58, -projection - 8.0, zc + lever_l * 0.025),
                        (lever_l, -projection + 4.0, zc - lever_l * 0.10)]
        else:
            controls = [(0.0, -projection, zc),
                        (lever_l * 0.16, -projection - 4.0, zc + lever_l * 0.08),
                        (lever_l * 0.58, -projection - 10.0, zc + lever_l * 0.035),
                        (lever_l, -projection + 2.0, zc - lever_l * 0.045)]
        path = _bezier(controls, 42)
        r = lever_d / 2.0
        if form == "изогнутая":
            profile = circle_profile(1.0, 20) * np.asarray([r, r * 0.78])
            scales = [1.15, 1.04, 0.95, 0.84, 0.72]
        else:
            angles = np.linspace(0.0, 2.0 * math.pi, 24, endpoint=False)
            profile = np.column_stack((np.sign(np.cos(angles)) * np.abs(np.cos(angles)) ** 0.62 * r,
                                       np.sign(np.sin(angles)) * np.abs(np.sin(angles)) ** 0.62 * r * 0.62))
            scales = [1.20, 1.02, 0.86, 1.06, 0.78]
        lever = sweep_solid(path, profile, scale_curve=scales, round_caps=0.85,
                            what=f"ручка {form}")
        parts.append(lever)
        parts.append(mf.Manifold.sphere(r * 1.08, max(24, segments // 2)).translate(tuple(path[0])))
        if form == "рельефная" and relief > 1e-9:
            ridge_path = path[4:-3].copy()
            ridge_path[:, 2] += lever_d * (0.25 + 0.08 * relief)
            ridge = sweep_solid(ridge_path, circle_profile(lever_d * (0.045 + 0.10 * relief), 14),
                                scale_end=0.55, round_caps=0.8, what="рельефное ребро ручки")
            parts.append(ridge)
    solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    if hand in ("лево", "левый", "left"):
        solid = solid.mirror((-1.0, 0.0, 0.0))
    _one(solid, f"дверная ручка {form}")
    min_z = float(solid.bounding_box()[2])
    if abs(min_z) > 1e-9:
        solid = solid.translate((0.0, 0.0, -min_z))
    params = dict(form=form, rosette_d=rosette_d, rosette_t=rosette_t,
                  neck_d=neck_d, projection=projection,
                  lever_length=lever_l if form in ("изогнутая", "рельефная") else 0.0,
                  lever_d=lever_d if form in ("изогнутая", "рельефная") else 0.0,
                  relief=relief if form == "рельефная" else 0.0,
                  knob_d=knob_d if form in ("сферическая", "дисковая") else 0.0,
                  disk_t=disk_t if form == "дисковая" else 0.0,
                  hand="лево" if hand in ("лево", "левый", "left") else "право",
                  segments=segments)
    parts_out = [("", solid, "color", "#b8bfc6", 0.76, 0.24, "door_handle")]
    root = _assembly(a, name, parts_out, params, "door_handle")
    root.notes.append(f"дверная ручка: {form}, вынос {projection:g} мм, "
                      f"направление {params['hand']}")
    return root
