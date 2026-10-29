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
from .geometry import manifold_from_arrays, manifold_mesh, normalize_color
from .ops import make_solid, op
from .sdf import EllipseCylinder, Field, RoundBox, RoundedCylinder, Sphere, Tube
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
            "Рельс стоит на подкладке в углублении шпалы. Каждая рельса, шпала "
            "sleeper_NN и точка крепления fastener_left|right_NN — отдельный объект.",
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
    # Каждая физическая деталь — отдельный объект Forma. Compound из всех
    # рельс/шпал выглядел компактно в списке, но делал отдельную шпалу
    # недоступной для pick, скрытия, покраски и точечного экспорта.
    rail_names = ["left", "right"] if rails == 2 else ["single"]
    parts = [("" if index == 0 else f".rail_{rail_names[index]}", rail,
              "rail_color", "#78828b", 0.78, 0.30,
              "track" if index == 0 else "track_rail")
             for index, rail in enumerate(rail_parts)]
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
        for index, y in enumerate(positions):
            parts.append((f".sleeper_{index + 1:02d}", master.translate((0.0, y, 0.0)),
                          "sleeper_color", "#62534a", 0.0, 0.82, "track_sleeper"))
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
        for rail_index, master in enumerate(per_rail):
            _one(master, "крепление рельсы")
            for position_index, y in enumerate(positions):
                parts.append((f".fastener_{rail_names[rail_index]}_{position_index + 1:02d}",
                              master.translate((0.0, y, 0.0)), "fastener_color",
                              "#454c53", 0.72, 0.38, "track_fastener"))
    params = dict(length=length, rails=rails, gauge=gauge if rails == 2 else 0.0,
                  rail_profile=profile, rail_height=height, head_width=head_w,
                  head_height=head_h, web=web, foot_width=foot_w, foot_height=foot_h,
                  rail_fillet=fillet, sleepers=sleepers_on, sleeper_shape=sleeper_shape,
                  sleeper_count=len(positions),
                  sleeper_step=actual_step if sleepers_on and len(positions) > 1 else step,
                  sleeper_step_requested=step,
                  sleeper_length=sleeper_l, sleeper_width=sleeper_w,
                  sleeper_height=sleeper_h, sleeper_bevel=sleeper_bevel,
                  fasteners=fasteners, plate_thickness=plate_t, segments=segments,
                  objects=len(parts))
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


def _hinge_geometry(p: dict) -> tuple[mf.Manifold, mf.Manifold]:
    """Общий генератор standalone-петли и петель внутри двери."""
    height = p["height"]
    leaf_w = p["leaf_width"]
    thickness = p["thickness"]
    corner = p["corner"]
    holes = p["holes"]
    hole_d = p["hole_d"]
    countersink = p["countersink"]
    segments = p["segments"]
    barrel_r = p["barrel_d"] * 0.5
    pin_r = p["pin_d"] * 0.5
    knuckles = p["knuckles"]
    gap = p["knuckle_gap"]
    clearance = p["clearance"]
    overhang = p["barrel_overhang"]
    open_angle = p["open_angle"]
    barrel_h = height + 2.0 * overhang
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
    return left, right


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
    left, right = _hinge_geometry(dict(
        height=height, leaf_width=leaf_w, thickness=thickness, corner=corner,
        holes=holes, hole_d=hole_d, countersink=countersink, segments=segments,
        barrel_d=barrel_d, pin_d=pin_d, knuckles=knuckles, knuckle_gap=gap,
        clearance=clearance, barrel_overhang=overhang, open_angle=open_angle))
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


def _bezier(points: list[tuple[float, float, float]], samples: int) -> np.ndarray:
    p = np.asarray(points, dtype=float)
    t = np.linspace(0.0, 1.0, samples)[:, None]
    return ((1 - t) ** 3 * p[0] + 3 * (1 - t) ** 2 * t * p[1]
            + 3 * (1 - t) * t ** 2 * p[2] + t ** 3 * p[3])


def _smooth_control_values(values: np.ndarray, samples: int) -> np.ndarray:
    """C1-интерполяция толщины без ступеней производной np.interp."""
    values = np.asarray(values, dtype=np.float64)
    if len(values) < 2:
        return np.full(samples, float(values[0]))
    u = np.linspace(0.0, 1.0, samples) * (len(values) - 1)
    i = np.minimum(np.floor(u).astype(int), len(values) - 2)
    t = u - i
    p0 = values[np.maximum(i - 1, 0)]
    p1 = values[i]
    p2 = values[i + 1]
    p3 = values[np.minimum(i + 2, len(values) - 1)]
    return 0.5 * (2.0 * p1 + (-p0 + p2) * t
                  + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t * t
                  + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t * t * t)


def _keyhole_prims(p: dict, z: float, thickness: float) -> list[object]:
    """Евро-профиль скважины: круглая камера и узкий паз ниже."""
    d = p["lock_d"]
    y = -thickness * 0.5
    return [
        RoundedCylinder((0.0, y, z + d * 0.12), d * 0.5,
                        thickness + 4.0, 0.0, "y"),
        RoundBox((0.0, y, z - d * 0.25),
                 (p["lock_slot"], thickness + 4.0, d * 0.75),
                 min(0.45, p["lock_slot"] * 0.12)),
    ]


def _lock_plug(p: dict, z: float, segments: int) -> mf.Manifold:
    """Отдельный цилиндр замка с настоящим узким ключевым пазом."""
    d = p["lock_d"]
    clearance = min(0.35, d * 0.025)
    thickness = float(p.get("lock_plug_t", max(1.2, p["rosette_t"] * 0.65)))
    back = -min(0.35, thickness * 0.20)
    radius = d * 0.5 - clearance
    round_part = mf.Manifold.cylinder(thickness, radius, radius, segments).rotate(
        (90.0, 0.0, 0.0)).translate((0.0, back, z + d * 0.12))
    stem = mf.Manifold.cube((max(0.8, p["lock_slot"] - 2 * clearance),
                             thickness, d * 0.75 - 2 * clearance), True).translate(
        (0.0, back - thickness * 0.5, z - d * 0.25))
    plug = mf.Manifold.batch_boolean([round_part, stem], mf.OpType.Add)
    slot_depth = min(1.6, thickness * 0.9)
    slot_width = min(max(0.8, p["lock_slot"] * 0.30), p["lock_slot"] * 0.5)
    key_slot = mf.Manifold.cube((slot_width, slot_depth, d * 0.32), True).translate(
        (0.0, back - thickness + slot_depth * 0.20, z + d * 0.12))
    return _one(plug - key_slot, "цилиндр замка")


def _handle_sdf(form: str, p: dict, segments: int, blend: float,
                resolution: float | None) -> tuple[mf.Manifold, list[tuple[str, mf.Manifold]],
                                                   float, float, int]:
    """Единое SDF-поле ручки и независимые детали замка.

    Розетка, шейка и рычаг/шар остаются аналитическими примитивами до самой
    polygonization. Скважина вычитается из того же поля, поэтому это не
    нарисованный значок. Цилиндр и отдельная замочная планка — самостоятельные
    selectable-объекты, а не спрятанные в compound куски.
    """
    rosette_kind = p["rosette"]
    has_rosette = rosette_kind != "нет"
    rosette_r = p["rosette_d"] * 0.5
    rosette_t = p["rosette_t"]
    projection = p["projection"]
    neck_r = p["neck_d"] * 0.5
    knob_r = p["knob_d"] * 0.5
    lever_d = p["lever_d"]
    lever_l = p["lever_length"]
    relief = p["relief"]
    is_knob = form in ("сферическая", "дисковая")
    zc = max(p["rosette_h"] * 0.5 if has_rosette else 0.0,
             knob_r if is_knob else lever_d)
    join_limit = min(p["neck_d"], p["knob_d"] if is_knob else lever_d) * 0.45
    join = min(float(blend), join_limit)

    prims: list[tuple[object, float]] = []
    if rosette_kind == "круглая":
        prims.append((RoundedCylinder((0.0, -rosette_t * 0.5, zc), rosette_r,
                                      rosette_t, min(1.2, rosette_t * 0.22), "y"), 0.0))
    elif rosette_kind == "овальная":
        prims.append((EllipseCylinder((0.0, -rosette_t * 0.5, zc), rosette_r,
                                      p["rosette_h"] * 0.5, rosette_t,
                                      min(1.2, rosette_t * 0.22)), 0.0))
    elif rosette_kind == "прямоугольная":
        prims.append((RoundBox((0.0, -rosette_t * 0.5, zc),
                               (p["rosette_d"], rosette_t, p["rosette_h"]),
                               min(p["rosette_corner"], rosette_t * 0.45,
                                   rosette_r * 0.45, p["rosette_h"] * 0.1)), 0.0))

    neck_a = -rosette_t + 0.8 if has_rosette else 0.0
    if is_knob:
        neck_b = -projection - 0.8
        neck = RoundedCylinder((0.0, (neck_a + neck_b) * 0.5, zc), neck_r,
                               abs(neck_b - neck_a), 0.0, "y")
        prims.append((neck, join))
        if form == "сферическая":
            knob = Sphere((0.0, -projection, zc), knob_r)
        else:
            disk_t = p["disk_t"]
            knob = RoundedCylinder((0.0, -projection, zc), knob_r, disk_t,
                                   min(2.2, disk_t * 0.22), "y")
        prims.append((knob, join))
    else:
        neck_b = -projection + lever_d * 0.20
        neck = RoundedCylinder((0.0, (neck_a + neck_b) * 0.5, zc), neck_r,
                               abs(neck_b - neck_a), 0.0, "y")
        prims.append((neck, join))
        if form == "прямоугольная":
            # Длинные кромки остаются прямыми; RoundBox задаёт только малые
            # intentional-фаски. SDF используется на стыке с шейкой, а не для
            # превращения всего рычага в эллипсоид.
            lever = RoundBox((lever_l * 0.5, -projection, zc),
                             (lever_l + lever_d * 0.35, lever_d * 0.72, lever_d),
                             min(p["lever_corner"], lever_d * 0.20, lever_l * 0.05))
            prims.append((lever, join))
        else:
            curve = lever_l / 115.0
            if form == "изогнутая":
                controls = [(0.0, -projection, zc),
                            (lever_l * 0.14, -projection - 6.0 * curve, zc + lever_l * 0.055),
                            (lever_l * 0.58, -projection - 8.0 * curve, zc + lever_l * 0.025),
                            (lever_l, -projection + 4.0 * curve, zc - lever_l * 0.10)]
                scales = np.asarray([1.15, 1.04, 0.95, 0.84, 0.72])
                z_scale = 0.78
            else:
                controls = [(0.0, -projection, zc),
                            (lever_l * 0.16, -projection - 4.0 * curve, zc + lever_l * 0.08),
                            (lever_l * 0.58, -projection - 10.0 * curve, zc + lever_l * 0.035),
                            (lever_l, -projection + 2.0 * curve, zc - lever_l * 0.045)]
                scales = np.asarray([1.20, 1.02, 0.86, 1.06, 0.78])
                z_scale = 0.62
            path = _bezier(controls, max(64, segments))
            scale = _smooth_control_values(scales, len(path))
            radii = lever_d * 0.5 * scale
            lever = Tube(path, radii, z_scale=z_scale)
            prims.append((lever, join))
            if form == "рельефная" and relief > 1e-9:
                first, last = 3, len(path) - 2
                ridge_path = path[first:last].copy()
                body_z = radii[first:last] * z_scale
                ridge_path[:, 2] += body_z * 0.92
                ridge_r = radii[first:last] * (0.08 + 0.14 * relief)
                ridge = Tube(ridge_path, ridge_r)
                ridge_join = min(join * 0.55, float(np.min(ridge_r)) * 0.85)
                prims.append((ridge, ridge_join))

    feature = min(p["neck_d"], p["knob_d"] if is_knob else lever_d)
    actual_resolution = float(resolution) if resolution is not None else feature / max(10.0, segments * 0.65)
    actual_resolution = max(0.05, actual_resolution)
    margin = max(1.0, join * 1.8 + actual_resolution * 3.0)
    lo = np.min(np.asarray([prim.lo for prim, _ in prims]), axis=0) - margin
    hi = np.max(np.asarray([prim.hi for prim, _ in prims]), axis=0) + margin
    # SDF нужен для качества стыка, а не для неограниченного расхода RAM.
    budget = 8_000_000
    estimate = int(np.prod(np.ceil((hi - lo) / actual_resolution).astype(np.int64) + 1))
    if estimate > budget:
        actual_resolution *= (estimate / budget) ** (1.0 / 3.0) * 1.001
    field = Field([*lo, *hi], actual_resolution)
    for prim, amount in prims:
        field.add(prim, blend=amount)

    lock_z = zc - p["lock_offset"]
    integrated_lock = p["lock"] and rosette_kind in ("овальная", "прямоугольная")
    if integrated_lock:
        for cutter in _keyhole_prims(p, lock_z, rosette_t):
            field.cut(cutter)
    solid = field.mesh(smooth_iters=2, simplify=actual_resolution * 0.05,
                       what=f"дверная ручка {form}")
    _one(solid, f"дверная ручка {form}")

    extras: list[tuple[str, mf.Manifold]] = []
    if p["lock"] and not integrated_lock:
        # Круглая розетка и вариант без розетки получают отдельную планку
        # ниже ручки: не растягиваем круг в фальшивую «грушу» ради замка.
        plate_r = float(p.get("lock_plate_r", max(10.0, p["lock_d"] * 0.8)))
        plate = RoundedCylinder((0.0, -rosette_t * 0.5, lock_z), plate_r,
                                rosette_t, min(1.0, rosette_t * 0.22), "y")
        h = max(0.12, actual_resolution)
        margin = 3.0 * h + 0.5
        lock_field = Field([*(plate.lo - margin), *(plate.hi + margin)], h)
        lock_field.add(plate)
        for cutter in _keyhole_prims(p, lock_z, rosette_t):
            lock_field.cut(cutter)
        lock_plate = lock_field.mesh(smooth_iters=1, simplify=h * 0.04,
                                     what="замочная планка")
        extras.append((".lock_plate", _one(lock_plate, "замочная планка")))
    if p["lock_plug"]:
        extras.append((".lock_plug", _lock_plug(p, lock_z, segments)))
    return solid, extras, actual_resolution, join, estimate


@op("door_handle", aliases=("дверная_ручка", "ручка_двери", "door_knob"),
    category="Примитивы",
    summary="Гладкая SDF-ручка: пять форм рычага/кнопки, круглая, овальная, "
            "прямоугольная или отсутствующая розетка, настоящая скважина и "
            "отдельный цилиндр замка. Все видимые детали доступны для выбора.",
    example="ручка = door_handle form=изогнутая lever_length=115 projection=45\n"
            "лепесток = door_handle form=рельефная rosette=овальная lock=да lock_plug=да\n"
            "модерн = door_handle form=прямоугольная rosette=прямоугольная rosette_h=160\n"
            "шар = door_handle form=сферическая rosette=нет\n"
            "диск = door_handle form=дисковая knob_d=58 disk_t=18",
    params={"form": "изогнутая, рельефная, прямоугольная, сферическая или дисковая",
            "rosette": "круглая, овальная, прямоугольная или нет (круглая)",
            "rosette_d": "диаметр/ширина розетки, мм (52)",
            "rosette_h": "высота овала/прямоугольника; 0 — автоматически (0)",
            "rosette_t": "толщина розетки, мм (6)",
            "rosette_corner": "фаска прямоугольной розетки, мм (3)",
            "neck_d": "диаметр соединительной шейки, мм (16)",
            "projection": "вынос оси ручки от двери в −Y, мм (45)",
            "lever_length": "длина рычага по X, мм (115)",
            "lever_d": "толщина рычага, мм (17)",
            "lever_corner": "фаска прямоугольного рычага, мм (1.2)",
            "relief": "высота продольного ребра 0…1 (0.55; только рельефная)",
            "knob_d": "диаметр сферы или диска, мм (56)",
            "disk_t": "толщина диска по Y, мм (18; только дисковая)",
            "lock": "да — настоящая скважина в розетке/отдельной планке (нет)",
            "lock_plug": "да — отдельный цилиндр в скважине; требует lock=да (нет)",
            "lock_offset": "расстояние от оси ручки до замка вниз, мм (55)",
            "lock_d": "диаметр круглой части скважины, мм (18)",
            "lock_slot": "ширина нижней части скважины, мм (4)",
            "hand": "направление рычага: право (+X) или лево (−X) (право)",
            "segments": "детализация осевой линии и авторазрешения 24…96 (48)",
            "blend": "радиус плавных SDF-сопряжений частей, мм (3; 0 — острые)",
            "resolution": "шаг SDF-сетки, мм; не задан — автоматически по segments",
            "lock_color": "цвет замочной планки и цилиндра (#8f989f)",
            "at": "сдвиг локального начала [x,y,z]; задняя плоскость на y=0",
            "center": "центрировать всю ручку в at (нет)"},
    positional=["form"])
def door_handle(a, name):
    raw = (a.text("form", "изогнутая") or "изогнутая").strip().lower()
    form = {"изогнутая": "изогнутая", "г": "изогнутая", "г-образная": "изогнутая",
            "рычаг": "изогнутая", "lever": "изогнутая",
            "рельефная": "рельефная", "лепесток": "рельефная", "sculpted": "рельефная",
            "прямоугольная": "прямоугольная", "прямоугольный": "прямоугольная",
            "квадратная": "прямоугольная", "rect": "прямоугольная",
            "rectangular": "прямоугольная",
            "сферическая": "сферическая", "сфера": "сферическая", "шар": "сферическая",
            "sphere": "сферическая", "дисковая": "дисковая", "диск": "дисковая",
            "disk": "дисковая"}.get(raw)
    if form is None:
        raise GeometryError("door_handle: form=изогнутая, рельефная, прямоугольная, сферическая или дисковая")
    raw_rosette = (a.text("rosette", a.text("rosette_shape", "круглая") or "круглая")
                   or "круглая").strip().lower()
    rosette = {"круг": "круглая", "круглая": "круглая", "circle": "круглая",
               "овал": "овальная", "овальная": "овальная", "oval": "овальная",
               "прямоугольник": "прямоугольная", "прямоугольная": "прямоугольная",
               "rect": "прямоугольная", "rectangle": "прямоугольная",
               "нет": "нет", "none": "нет", "без": "нет", "без_розетки": "нет"}.get(raw_rosette)
    if rosette is None:
        raise GeometryError("door_handle: rosette=круглая, овальная, прямоугольная или нет")
    rosette_d = float(a.num("rosette_d", 52.0, minv=16.0, maxv=500.0))
    rosette_t = float(a.num("rosette_t", 6.0, minv=1.0, maxv=100.0))
    rosette_corner = float(a.num("rosette_corner", 3.0, minv=0.0, maxv=100.0) or 0.0)
    neck_d = float(a.num("neck_d", 16.0, minv=3.0, maxv=100.0))
    projection = float(a.num("projection", 45.0, minv=12.0, maxv=500.0))
    lever_l = float(a.num("lever_length", 115.0, minv=35.0, maxv=1000.0))
    lever_d = float(a.num("lever_d", 17.0, minv=4.0, maxv=100.0))
    lever_corner = float(a.num("lever_corner", 1.2, minv=0.0, maxv=20.0) or 0.0)
    relief = float(a.num("relief", 0.55, minv=0.0, maxv=1.0))
    knob_d = float(a.num("knob_d", 56.0, minv=16.0, maxv=300.0))
    disk_t = float(a.num("disk_t", 18.0, minv=4.0, maxv=100.0))
    lock = a.boolean("lock", False)
    lock_plug = a.boolean("lock_plug", False)
    if lock_plug and not lock:
        raise GeometryError("door_handle: lock_plug=да требует lock=да")
    lock_offset = float(a.num("lock_offset", 55.0, minv=12.0, maxv=500.0))
    lock_d = float(a.num("lock_d", 18.0, minv=6.0, maxv=60.0))
    lock_slot = float(a.num("lock_slot", 4.0, minv=1.0, maxv=20.0))
    if lock_slot > lock_d * 0.6:
        raise GeometryError("door_handle: lock_slot слишком широкий для lock_d")
    if lock and lock_offset <= (neck_d + lock_d) * 0.5 + 2.0:
        raise GeometryError("door_handle: lock_offset слишком мал — скважина пересечёт шейку")
    requested_h = float(a.num("rosette_h", 0.0, minv=0.0, maxv=2000.0) or 0.0)
    if rosette == "круглая":
        rosette_h = rosette_d
    elif rosette == "нет":
        rosette_h = 0.0
    else:
        automatic = rosette_d * (1.5 if rosette == "овальная" else 1.8)
        if lock:
            automatic = max(automatic, 2.0 * lock_offset + 3.0 * lock_d)
        rosette_h = requested_h or automatic
    if lock and rosette in ("овальная", "прямоугольная"):
        zc = rosette_h * 0.5
        lock_z = zc - lock_offset
        if lock_z - lock_d * 0.65 <= lock_d * 0.75 or lock_z + lock_d * 0.65 >= rosette_h - 0.5:
            raise GeometryError("door_handle: скважина не помещается в розетку; увеличьте rosette_h или lock_offset")
    if lock and rosette == "круглая":
        plate_r = max(10.0, lock_d * 0.8)
        if lock_offset <= rosette_d * 0.5 + plate_r + 1.0:
            raise GeometryError("door_handle: увеличьте lock_offset, чтобы замочная планка не пересекала круглую розетку")
    hand = (a.text("hand", "право") or "право").strip().lower()
    if hand not in ("право", "правый", "right", "лево", "левый", "left"):
        raise GeometryError("door_handle: hand=право или лево")
    segments = int(a.int("segments", 48, minv=24, maxv=96) or 48)
    if projection <= (rosette_t if rosette != "нет" else 0.0) + 2.0:
        raise GeometryError("door_handle: projection должен быть больше толщины розетки")
    blend = float(a.num("blend", 3.0, minv=0.0, maxv=100.0))
    requested_resolution = a.num("resolution", None, minv=0.05, maxv=100.0)
    cfg = dict(rosette=rosette, rosette_d=rosette_d, rosette_h=rosette_h,
               rosette_t=rosette_t, rosette_corner=rosette_corner, neck_d=neck_d,
               projection=projection, lever_d=lever_d, lever_length=lever_l,
               lever_corner=lever_corner, relief=relief, knob_d=knob_d, disk_t=disk_t,
               lock=lock, lock_plug=lock_plug, lock_offset=lock_offset,
               lock_d=lock_d, lock_slot=lock_slot)
    solid, extras, actual_resolution, join, estimate = _handle_sdf(
        form, cfg, segments, blend, requested_resolution)
    if estimate > 8_000_000:
        a.scene.log("warn", f"door_handle {form}: SDF разрешение ограничено "
                            f"{actual_resolution:.3f} мм (~{estimate:,} ячеек до ограничения)".replace(",", " "),
                    a.cmd.line)
    items = [("", solid), *extras]
    if hand in ("лево", "левый", "left"):
        items = [(suffix, part.mirror((-1.0, 0.0, 0.0))) for suffix, part in items]
    min_z = min(float(part.bounding_box()[2]) for _, part in items)
    if abs(min_z) > 1e-9:
        items = [(suffix, part.translate((0.0, 0.0, -min_z))) for suffix, part in items]
    lever_forms = ("изогнутая", "рельефная", "прямоугольная")
    params = dict(form=form, rosette=rosette, rosette_d=rosette_d,
                  rosette_h=rosette_h, rosette_t=rosette_t, rosette_corner=rosette_corner,
                  neck_d=neck_d, projection=projection,
                  lever_length=lever_l if form in lever_forms else 0.0,
                  lever_d=lever_d if form in lever_forms else 0.0,
                  lever_corner=lever_corner if form == "прямоугольная" else 0.0,
                  relief=relief if form == "рельефная" else 0.0,
                  knob_d=knob_d if form in ("сферическая", "дисковая") else 0.0,
                  disk_t=disk_t if form == "дисковая" else 0.0,
                  lock=lock, lock_plug=lock_plug, lock_offset=lock_offset if lock else 0.0,
                  lock_d=lock_d if lock else 0.0, lock_slot=lock_slot if lock else 0.0,
                  hand="лево" if hand in ("лево", "левый", "left") else "право",
                  segments=segments, blend=join, resolution=actual_resolution,
                  sdf=True, objects=1 + len(extras))
    parts_out = []
    for suffix, part in items:
        if not suffix:
            parts_out.append(("", part, "color", "#b8bfc6", 0.76, 0.24, "door_handle"))
        else:
            parts_out.append((suffix, part, "lock_color", "#8f989f", 0.82, 0.22,
                              "door_lock_plate" if suffix == ".lock_plate" else "door_lock"))
    root = _assembly(a, name, parts_out, params, "door_handle")
    root.notes.append(f"дверная ручка: {form}, розетка {rosette}, вынос {projection:g} мм, "
                      f"направление {params['hand']}; SDF сопряжение {join:g} мм, "
                      f"шаг {actual_resolution:.3f} мм; замок={'да' if lock else 'нет'}")
    return root
