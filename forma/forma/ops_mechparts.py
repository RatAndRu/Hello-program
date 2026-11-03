"""Механика и тара: подшипники, рейки, шестерни, проушины, ящик, фастекс.

Модуль самодостаточен: чтобы подключить его, достаточно одной строки импорта в
``run.py`` рядом с остальными ``ops_*``. Все детали — настоящие замкнутые тела,
размеры по умолчанию взяты у реальных изделий (подшипники ГОСТ 8338/3478,
рейка DIN 60715, тара 880×790×600 мм), а не «на глаз».

Что внутри:

* ``bearing`` — подшипник с кольцами, телами качения и сепаратором; шесть типов:
  шариковый, роликовый, игольчатый, конический, упорный, сферический;
* ``din_rail`` — монтажная рейка TS35/TS15/TS45 по DIN 60715 с просечками;
* ``crate`` — дощатый ящик на угловых стойках;
* ``lug`` — проушина: площадка с отверстием под палец и отогнутая полка;
* ``buckle`` — фастекс (side-release): рамка и ответная часть с усиками;
* ``corner_bracket`` — угловой кронштейн с косынкой (по фото сварного узла);
* ``rack`` — зубчатая рейка в паре с шестернёй ``gear``;
* ``gear_internal`` — колесо с внутренними зубьями; ``gear_helical`` —
  косозубое; ``gear_bevel`` — коническое;
* ``screw_head`` — конструктор головок винтов: семь профилей и шесть шлицов;
* ``wing_nut`` — барашек; ``special_nut`` — колпачковая, с фланцем, Nyloc,
  квадратная, T-гайка и закладная.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import anchor, make_solid, op
from .ops_hardware import _thread_bore


# --------------------------------------------------------------------------- #
#  Помощники
# --------------------------------------------------------------------------- #
def _cyl(h: float, r: float, seg: int = 72) -> mf.Manifold:
    return mf.Manifold.cylinder(float(h), float(r), float(r), int(seg))


def _cone(h: float, r1: float, r2: float, seg: int = 72) -> mf.Manifold:
    return mf.Manifold.cylinder(float(h), float(r1), float(r2), int(seg))


def _box(sx: float, sy: float, sz: float, center: bool = True) -> mf.Manifold:
    return mf.Manifold.cube([float(sx), float(sy), float(sz)], bool(center))


def _ring(outer_r: float, inner_r: float, h: float, seg: int = 96) -> mf.Manifold:
    if outer_r <= inner_r + 1e-6:
        raise GeometryError("Кольцо: наружный радиус должен быть больше внутреннего.")
    return _cyl(h, outer_r, seg) - _cyl(h + 0.4, inner_r, seg).translate((0, 0, -0.2))


def _plus_shape(size: float, width: float):
    """Контур крестового шлица: два пересекающихся паза одним полигоном.

    Две отдельные коробки давали вывернутую оболочку внутри головки, поэтому
    крест строится как один замкнутый контур.
    """
    h = size / 2.0
    w = max(0.2, width / 2.0)
    return [(h, w), (w, w), (w, h), (-w, h), (-w, w), (-h, w),
            (-h, -w), (-w, -w), (-w, -h), (w, -h), (w, -w), (h, -w)]


def _circle(r: float, seg: int = 72, cx: float = 0.0, cy: float = 0.0):
    return [(cx + r * math.cos(2 * math.pi * i / seg),
             cy + r * math.sin(2 * math.pi * i / seg)) for i in range(seg)]


def _clean(points):
    """Убирает дубли и приводит контур к обходу против часовой стрелки."""
    pts = []
    for p in points:
        q = (float(p[0]), float(p[1]))
        if not pts or abs(q[0] - pts[-1][0]) > 1e-7 or abs(q[1] - pts[-1][1]) > 1e-7:
            pts.append(q)
    if len(pts) > 2 and abs(pts[0][0] - pts[-1][0]) < 1e-7 and abs(pts[0][1] - pts[-1][1]) < 1e-7:
        pts.pop()
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
               - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    return pts if area > 0 else pts[::-1]


def _cross(points, holes=None) -> mf.CrossSection:
    if len(points) < 3:
        raise GeometryError("Контур сечения вырожден: меньше трёх точек.")
    cs = mf.CrossSection([_clean(points)])
    for hole in holes or []:
        if len(hole) < 3:
            continue
        cs = cs - mf.CrossSection([_clean(hole)])
    return cs


def _chamfer_ring(r_od: float, r_id: float, h: float, c: float) -> mf.Manifold:
    """Фаска 45° по наружным кромкам обоймы: снимает острые углы колец."""
    if c <= 0.05:
        return mf.Manifold()
    cuts = mf.Manifold()
    for z, up in ((0.0, False), (h, True)):
        for r, outward in ((r_od, True), (r_id, False)):
            s = 1.0 if outward else -1.0
            pts = [(r, z), (r + s * (c + 0.4), z if up else z - c),
                   (r + s * (c + 0.4), z + c if up else z - c - 0.4)]
            if not up:
                pts = [(r, z), (r + s * (c + 0.4), z + c),
                       (r + s * (c + 0.4), z - 0.4)]
            try:
                wedge = mf.Manifold.revolve(mf.CrossSection([_clean(pts)]), 96)
            except Exception:      # ядро не смогло — фаска не критична
                continue
            cuts = cuts + wedge
    return cuts


def _finish(a, name: str, solid: mf.Manifold, kind: str, note: str):
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("Деталь получилась пустой — проверьте размеры.")
    placed = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, placed, a, kind=kind)
    out.notes.append(note)
    a.scene.log("info", note, a.cmd.line)
    return out


def _part_count(solid: mf.Manifold) -> int:
    try:
        return len(solid.decompose())
    except Exception:      # pragma: no cover — ядро может не уметь decompose
        return 1


# --------------------------------------------------------------------------- #
#  Подшипник
# --------------------------------------------------------------------------- #
_BEARING_KINDS = {
    "шариковый": "ball", "шарик": "ball", "ball": "ball",
    "роликовый": "roller", "цилиндрический": "roller", "roller": "roller",
    "игольчатый": "needle", "игла": "needle", "needle": "needle",
    "конический": "taper", "конический_роликовый": "taper", "taper": "taper",
    "упорный": "thrust", "thrust": "thrust",
    "сферический": "spherical", "самоустанавливающийся": "spherical",
    "spherical": "spherical",
}


@op("bearing", aliases=("подшипник", "bearing_ball", "bearing_roller"),
    category="Примитивы",
    summary="Подшипник качения: наружное и внутреннее кольца с фасками, тела "
            "качения и штампованный сепаратор. Тип задаёт форму тел качения и "
            "схему колец.",
    example="шариковый = bearing d=15 D=35 B=11\n"
            "роликовый = bearing d=25 D=52 B=15 type=роликовый\n"
            "игольчатый = bearing d=20 D=26 B=16 type=игольчатый\n"
            "упорный = bearing d=30 D=47 B=11 type=упорный",
    params={"d": "внутренний (посадочный) диаметр, мм (8)",
            "D": "наружный диаметр, мм (22)",
            "B": "ширина, мм (7)",
            "type": "шариковый, роликовый, игольчатый, конический, упорный "
                    "или сферический (шариковый)",
            "balls": "число тел качения (0 — подобрать по шагу)",
            "cage": "строить сепаратор (да)",
            "shield": "закрыть кольца шайбами с двух сторон (нет)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def bearing(a, name):
    d = float(a.num("d", 8.0, minv=1.0, maxv=2000.0))
    D = float(a.num("D", 22.0, minv=d + 1.0, maxv=3000.0))
    B = float(a.num("B", 7.0, minv=0.5, maxv=600.0))
    kind_raw = (a.text("type") or "шариковый").strip().lower()
    if kind_raw not in _BEARING_KINDS:
        raise GeometryError(
            f"bearing: неизвестный тип «{kind_raw}».",
            hint="Есть: шариковый, роликовый, игольчатый, конический, "
                 "упорный, сферический.")
    kind = _BEARING_KINDS[kind_raw]
    cage = a.boolean("cage", True)
    shield = a.boolean("shield", False)

    r_in, r_out = d / 2.0, D / 2.0
    r_pitch = (r_in + r_out) / 2.0
    space = (r_out - r_in) / 2.0
    if space < 0.8:
        raise GeometryError("bearing: кольца почти касаются — увеличьте D "
                            "или уменьшите d.")

    if kind == "needle":
        r_elem, elem_h = space * 0.24, B * 0.92
    elif kind == "roller":
        r_elem, elem_h = space * 0.34, B * 0.74
    elif kind == "taper":
        r_elem, elem_h = space * 0.36, B * 0.72
    elif kind == "thrust":
        r_elem, elem_h = space * 0.30, B * 0.30
    elif kind == "spherical":
        r_elem, elem_h = space * 0.52, B * 0.30
    else:
        r_elem, elem_h = space * 0.54, B * 0.58

    inner_outer = r_pitch - r_elem * 0.95
    outer_inner = r_pitch + r_elem * 0.95
    if inner_outer <= r_in + 0.3:
        raise GeometryError("bearing: внутреннее кольцо вырождается — "
                            "увеличьте D/d.")
    if outer_inner >= r_out - 0.3:
        raise GeometryError("bearing: наружное кольцо вырождается — "
                            "увеличьте D/d.")

    count = int(a.num("balls", 0, minv=0, maxv=400) or 0)
    if count <= 0:
        pitch_len = 2.0 * math.pi * r_pitch
        step = r_elem * (2.9 if kind == "needle" else 2.4)
        count = max(3, int(pitch_len / max(step, 1e-3)))
    count = max(3, min(count, 400))

    # ---- упорный: два плоских кольца и шары между ними --------------------
    if kind == "thrust":
        h_ring = max(0.6, B * 0.26)
        gap = max(0.6, B - 2.0 * h_ring)
        r_ball = max(0.35, min((r_out - r_in) * 0.42, gap * 0.58))
        count = max(3, min(count, int(2 * math.pi * r_pitch / (r_ball * 2.3))))
        lower = _ring(r_out, r_in, h_ring)
        upper = _ring(r_out, r_in, h_ring).translate((0, 0, h_ring + gap))
        balls = mf.Manifold()
        for i in range(count):
            ang = 2 * math.pi * i / count
            balls = balls + mf.Manifold.sphere(r_ball, 24).translate(
                (r_pitch * math.cos(ang), r_pitch * math.sin(ang),
                 h_ring + gap / 2.0))
        solid = lower + balls + upper
        return _finish(a, name, solid, "bearing",
                       f"подшипник упорный {d:g}×{D:g}×{B:g} · шаров {count} "
                       f"Ø{2 * r_ball:.2f} мм")

    # ---- кольца -----------------------------------------------------------
    chamfer = min(space * 0.16, B * 0.14, 1.2)
    inner_ring = _chamfer_safe(_ring(inner_outer, r_in, B), r_in, B, chamfer)
    outer_ring = _chamfer_safe(_ring(r_out, outer_inner, B), r_out, B, chamfer)
    # Дорожка качения: поясок-канавка по среднему радиусу. Без неё шарик
    # касался бы колец по линии и сборка распалась бы на отдельные тела.
    if kind in ("ball", "spherical"):
        try:
            race = _torus(r_pitch, B / 2.0 if kind == "ball" else None,
                          r_elem * 0.90, B, rings=(inner_ring, outer_ring))
            inner_ring, outer_ring = race
        except Exception:
            pass

    # ---- тела качения -----------------------------------------------------
    elems = mf.Manifold()
    for i in range(count):
        ang = 2 * math.pi * i / count
        ca, sa = math.cos(ang), math.sin(ang)
        cx, cy = r_pitch * ca, r_pitch * sa
        if kind == "ball":
            elems = elems + mf.Manifold.sphere(r_elem, 28).translate(
                (cx, cy, B / 2.0))
        elif kind == "spherical":
            # два ряда бочкообразных роликов — признак самоустанавливающейся опоры
            barrel = (mf.Manifold.sphere(r_elem, 28)
                      ^ _cyl(elem_h * 1.5, r_elem * 0.62, 28).translate(
                          (0, 0, -elem_h * 0.75)))
            for zf in (0.33, 0.67):
                elems = elems + barrel.translate((cx, cy, B * zf))
        elif kind in ("roller", "needle"):
            piece = _cyl(elem_h, r_elem, 32).translate((0, 0, (B - elem_h) / 2.0))
            elems = elems + piece.translate((cx, cy, 0.0))
        else:      # taper: конус-ролик, ось радиальная, узкий конец внутрь
            piece = _cone(elem_h, r_elem * 0.60, r_elem * 1.04, 32)
            piece = piece.translate((0, 0, -elem_h / 2.0)).rotate((0, 90, 0))
            piece = piece.translate((0, 0, B / 2.0)).rotate((0, 0, math.degrees(ang)))
            elems = elems + piece.translate((r_pitch * ca, r_pitch * sa, 0.0))

    parts = [inner_ring + outer_ring, elems]

    # ---- сепаратор --------------------------------------------------------
    if cage and kind != "needle":
        # Корончатый сепаратор: сплошной обод снизу и рёбра-перемычки между
        # телами качения. Карманы открыты сверху — шарики видны, обод цел.
        band_z = B * 0.24
        band_h = B * 0.30
        rim_h = max(0.5, band_h * 0.38)
        band = _ring(outer_inner + 0.15, max(inner_outer - 0.15, r_in + 0.2),
                     band_h, 128).translate((0, 0, band_z))
        for i in range(count):
            ang = 2 * math.pi * i / count
            pocket = _cyl(band_h + 1.0, r_elem * 1.03, 40).translate(
                (r_pitch * math.cos(ang), r_pitch * math.sin(ang),
                 band_z + rim_h - 0.15))
            band = band - pocket
        if _part_count(band) > 1:      # страховка: обод не должен распасться
            band = _ring(outer_inner + 0.15, max(inner_outer - 0.15, r_in + 0.2),
                         rim_h, 128).translate((0, 0, band_z))
        parts.append(band)

    if shield:
        # Защитная шайба сидит в наружном кольце с лабиринтным зазором у
        # внутреннего: герметичное кольцо запирало бы воздух внутри и давало
        # вывернутую оболочку полости.
        sh = _ring(r_out - 0.4, inner_outer + max(0.25, r_elem * 0.12), 0.6, 96)
        parts.append(sh.translate((0, 0, 0.2)))
        parts.append(sh.translate((0, 0, B - 0.8)))

    solid = parts[0]
    for extra in parts[1:]:
        solid = solid + extra

    kind_names = {"ball": "шариковый", "roller": "роликовый",
                  "needle": "игольчатый", "taper": "конический",
                  "spherical": "сферический"}
    note = (f"подшипник {kind_names.get(kind, kind)} {d:g}×{D:g}×{B:g} · "
            f"тел качения {count}")
    if shield:
        note += " · закрытый"
    if _part_count(solid) > 1:
        note += f" · сборка из {_part_count(solid)} частей"
    return _finish(a, name, solid, "bearing", note)


def _torus(r_pitch: float, z_mid, r_minor: float, B: float, rings=(None, None)):
    """Кольцевая канавка под тела качения: тело вращения окружности вокруг Z."""
    if z_mid is None:
        z_mid = B / 2.0
    prof = [(r_pitch + r_minor * math.cos(2 * math.pi * i / 48),
             z_mid + r_minor * math.sin(2 * math.pi * i / 48)) for i in range(48)]
    groove = mf.Manifold.revolve(mf.CrossSection([_clean(prof)]), 96)
    return tuple(r - groove for r in rings)


def _chamfer_safe(ring: mf.Manifold, r_od: float, h: float, c: float) -> mf.Manifold:
    """Снимает фаску с наружной кромки обоймы, не ломаясь на мелких размерах."""
    if c <= 0.08:
        return ring
    try:
        cut = _chamfer_ring(r_od, r_od - 1.0, h, c)
        return ring - cut if not cut.is_empty() else ring
    except Exception:
        return ring


# --------------------------------------------------------------------------- #
#  Монтажная рейка DIN
# --------------------------------------------------------------------------- #
@op("din_rail", aliases=("рейка_din", "монтажная_рейка", "ts35", "din"),
    category="Примитивы",
    summary="Монтажная рейка по DIN 60715 (TS35, TS15, TS45): гнутый профиль "
            "с загнутыми полками и просечками через 25 мм.",
    example="рейка = din_rail length=500 size=35 slots=да",
    params={"length": "длина, мм (500)", "size": "35, 15 или 45 — ширина профиля (35)",
            "thickness": "толщина стали, мм (1)",
            "slots": "просечки под крепёж (да)",
            "slot_pitch": "шаг просечек, мм (25)", "slot_len": "длина просечки (15)",
            "slot_w": "ширина просечки (6.5)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def din_rail(a, name):
    length = float(a.num("length", 500.0, minv=20.0, maxv=6000.0))
    size = float(a.num("size", 35.0, minv=10.0, maxv=60.0))
    t = float(a.num("thickness", 1.0, minv=0.3, maxv=4.0))
    slots = a.boolean("slots", True)
    pitch = float(a.num("slot_pitch", 25.0, minv=5.0, maxv=200.0))
    slot_len = float(a.num("slot_len", 15.0, minv=1.0, maxv=60.0))
    slot_w = float(a.num("slot_w", 6.5, minv=1.0, maxv=30.0))

    h = 7.5 if size <= 40 else 9.0
    if size <= 20:
        h = 5.0
    half = size / 2.0
    flange = max(1.5, size * 0.11)      # загнутая полка
    opening = half - flange
    side = t + 0.2
    if opening <= t:
        raise GeometryError("Рейка: полки съели весь просвет — уменьшите толщину.")
    prof = [(-half, 0.0), (half, 0.0), (half, h), (opening, h),
            (opening, h - t), (half - side, h - t), (half - side, t),
            (-(half - side), t), (-(half - side), h - t), (-opening, h - t),
            (-opening, h), (-half, h)]
    body = _cross(prof).extrude(length).rotate((90, 0, 0)).rotate((0, 0, -90))
    body = body.translate((length / 2.0, 0, 0))
    count = 0
    if slots:
        count = max(1, int((length - pitch * 0.5) // pitch))
        start = -pitch * (count - 1) / 2.0
        for i in range(count):
            x = start + i * pitch
            cutter = _box(slot_len, slot_w, t * 4.0).translate((x, 0, t / 2.0))
            ends = (_cyl(t * 4.0, slot_w / 2.0, 24).translate(
                (x - slot_len / 2.0 + slot_w / 2.0, 0, -t))
                + _cyl(t * 4.0, slot_w / 2.0, 24).translate(
                    (x + slot_len / 2.0 - slot_w / 2.0, 0, -t)))
            body = body - (cutter + ends)
    return _finish(a, name, body, "din_rail",
                   f"рейка DIN TS{size:g} · {length:g} мм · сталь {t:g} мм"
                   + (f" · просечек {count}" if slots else " · без просечек"))


# --------------------------------------------------------------------------- #
#  Ящик
# --------------------------------------------------------------------------- #
@op("crate", aliases=("тарный_ящик", "дощатый_ящик", "деревянный_ящик",
                       "box_crate"), category="Примитивы",
    summary="Дощатый ящик на четырёх угловых стойках: дно, стенки из досок с "
            "зазорами, необязательные крышка и полозья.",
    example="ящик = crate length=880 width=600 height=790",
    params={"length": "наружная длина по X, мм (880)",
            "width": "наружная ширина по Y, мм (600)",
            "height": "высота стенки, мм (790)",
            "plank": "толщина доски, мм (20)", "post": "сечение стойки, мм (60)",
            "gap": "зазор между досками, мм (4)",
            "lid": "крышка с обвязкой (нет)",
            "skids": "высота полозьев, мм (0 — без них)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def crate(a, name):
    length = float(a.num("length", 880.0, minv=120.0, maxv=4000.0))
    width = float(a.num("width", 600.0, minv=120.0, maxv=4000.0))
    height = float(a.num("height", 790.0, minv=80.0, maxv=4000.0))
    plank = float(a.num("plank", 20.0, minv=4.0, maxv=80.0))
    post = float(a.num("post", 60.0, minv=15.0, maxv=200.0))
    gap = float(a.num("gap", 4.0, minv=0.0, maxv=40.0))
    lid = a.boolean("lid", False)
    skids = float(a.num("skids", 0.0, minv=0.0, maxv=200.0) or 0.0)
    if min(length, width) < 2 * post + 2 * plank:
        raise GeometryError("Ящик слишком мал для стоек такого сечения.")

    z0 = skids
    parts = []
    lap = 1.0            # перехлёст, чтобы доски гарантированно срослись со стойками
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts.append(_box(post, post, height, center=False).translate(
                (sx * (length / 2.0 - post) if sx > 0 else -length / 2.0,
                 sy * (width / 2.0 - post) if sy > 0 else -width / 2.0, z0)))
    floor = z0 + 2.0 * plank - 1.0
    rows = max(2, int((height - floor) / (plank + gap)))
    used = rows * plank + (rows - 1) * gap
    z_first = floor + max(0.0, (height - floor - used) / 2.0)
    long_span = length - 2 * post + 2 * lap
    short_span = width - 2 * post + 2 * lap
    for i in range(rows):
        zz = z_first + i * (plank + gap)
        for sy in (-1, 1):
            parts.append(_box(long_span, plank, plank, center=False).translate(
                (-long_span / 2.0, sy * (width / 2.0 - plank) if sy > 0
                 else -width / 2.0, zz)))
        for sx in (-1, 1):
            parts.append(_box(plank, short_span, plank, center=False).translate(
                (sx * (length / 2.0 - plank) if sx > 0 else -length / 2.0,
                 -short_span / 2.0, zz)))
    # дно: две продольные балки в стойках и настил из досок поперёк
    for sy in (-1, 1):
        parts.append(_box(long_span, post, plank, center=False).translate(
            (-long_span / 2.0,
             sy * (width / 2.0 - post) if sy > 0 else -width / 2.0, z0)))
    planks = max(1, int(long_span // (plank + gap)))
    step_x = long_span / planks
    for i in range(planks):
        x = -long_span / 2.0 + i * step_x
        parts.append(_box(min(plank, step_x - gap), width, plank,
                          center=False).translate(
            (x + gap / 2.0, -width / 2.0, z0 + plank - 1.0)))
    if lid:
        top = z0 + height
        parts.append(_box(length, width, plank, center=False).translate(
            (-length / 2.0, -width / 2.0, top)))
        for sx in (-1, 1):
            parts.append(_box(length, post * 0.7, plank * 0.8, center=False).translate(
                (-length / 2.0,
                 sx * (width / 2.0 - post * 0.7) if sx > 0 else -width / 2.0,
                 top + plank - 1.0)))
    if skids > 0:
        rail_w = min(width * 0.16, 100.0)
        for y in (-width / 2.0 + rail_w / 2.0, 0.0, width / 2.0 - rail_w / 2.0):
            parts.append(_box(length, rail_w, skids + 2.0 * plank, center=False).translate(
                (-length / 2.0, y - rail_w / 2.0, 0.0)))
    solid = parts[0]
    for extra in parts[1:]:
        solid = solid + extra
    return _finish(a, name, solid, "crate",
                   f"ящик {length:g}×{width:g}×{height:g} · доска {plank:g} мм · "
                   f"стоек 4 · досок стенок {rows * 4}, дна {planks}")


# --------------------------------------------------------------------------- #
#  Проушина
# --------------------------------------------------------------------------- #
@op("lug", aliases=("проушина", "ушкo", "ушко", "eye_lug"), category="Примитивы",
    summary="Проушина: площадка с отверстием под палец, отогнутая полка и "
            "крепёжные отверстия на полке и на площадке.",
    example="проушина = lug inner=32 outer=64 length=90 thickness=4 bend=30",
    params={"inner": "диаметр отверстия под палец, мм (32)",
            "outer": "наружный диаметр головки, мм (64)",
            "length": "длина площадки от центра отверстия, мм (90)",
            "width": "ширина площадки, мм (40)", "thickness": "толщина, мм (4)",
            "bend": "высота отогнутой полки, мм (30)",
            "holes": "отверстий на отогнутой полке (2)",
            "hole_d": "диаметр крепёжных отверстий, мм (7)",
            "plate_holes": "отверстий на площадке (0)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def lug(a, name):
    inner = float(a.num("inner", 32.0, minv=2.0, maxv=600.0))
    outer = float(a.num("outer", 64.0, minv=inner + 4.0, maxv=800.0))
    length = float(a.num("length", 90.0, minv=outer / 2.0 + 5.0, maxv=2000.0))
    width = float(a.num("width", 40.0, minv=5.0, maxv=600.0))
    t = float(a.num("thickness", 4.0, minv=0.8, maxv=40.0))
    bend = float(a.num("bend", 30.0, minv=0.0, maxv=800.0))
    holes = int(a.num("holes", 2, minv=0, maxv=8) or 0)
    plate_holes = int(a.num("plate_holes", 0, minv=0, maxv=8) or 0)
    hole_d = float(a.num("hole_d", 7.0, minv=0.5, maxv=inner))
    r_head = outer / 2.0
    if width > outer:
        raise GeometryError("Ширина площадки больше головки: площадка торчала бы "
                            "за полукруг. Уменьшите width или увеличьте outer.")

    hull = max(1.0, min(width, length) * 0.12)
    pts = [(-width / 2.0, 0.0)]
    for i in range(41):                       # дуга головки: слева через верх
        ang = math.pi * (1.0 - i / 40.0)
        pts.append((r_head * math.cos(ang), r_head * math.sin(ang)))
    pts += [(width / 2.0, 0.0),
            (width / 2.0, -length + hull), (width / 2.0 - hull, -length),
            (-width / 2.0 + hull, -length), (-width / 2.0, -length + hull)]
    plate = _cross(pts).extrude(t)
    plate = plate - _cyl(t + 2.0, inner / 2.0, 72).translate((0, 0, -1.0))
    solid = plate
    if plate_holes:
        gap_y = (length - r_head) / (plate_holes + 1)
        for i in range(plate_holes):
            y = -(r_head + gap_y * (i + 1))
            solid = solid - _cyl(t + 2.0, hole_d / 2.0, 32).translate(
                (0, y, -1.0))
    if bend > 0:
        flange = _box(width, t + 1.0, bend, center=False).translate(
            (-width / 2.0, -length, 0.0))
        flange = flange + _box(width, t, t, center=False).translate(
            (-width / 2.0, -length, 0.0))
        solid = solid + flange
        for i in range(holes):
            z = bend * (i + 1) / (holes + 1)
            x = -width / 2.0 + width * (i + 1) / (holes + 1)
            cutter = _cyl(t + 3.0, hole_d / 2.0, 32).rotate((90, 0, 0)).translate(
                (x, -length + t + 1.0, z))
            solid = solid - cutter
    return _finish(a, name, solid, "lug",
                   f"проушина Ø{inner:g} в головке Ø{outer:g} · полка {bend:g} мм · "
                   f"сталь {t:g} мм · отверстий {holes + plate_holes}")


# --------------------------------------------------------------------------- #
#  Угловой кронштейн с косынкой
# --------------------------------------------------------------------------- #
@op("corner_bracket", aliases=("угловой_кронштейн", "кронштейн_с_косынкой",
                               "уголок_с_косынкой", "corner_brace"),
    category="Примитивы",
    summary="Угловой кронштейн из двух полок с треугольной косынкой между ними "
            "(сварной узел по фото). Отверстия в обеих полках.",
    example="кронштейн = corner_bracket size=[80,80] width=60 thickness=5 gusset=3",
    params={"size": "длины полок [по X, по Z], мм ([80,80])",
            "width": "ширина полки по Y, мм (60)", "thickness": "толщина, мм (5)",
            "gusset": "толщина косынки, мм (5)", "gusset_depth": "катет косынки, мм (35)",
            "holes": "отверстий в каждой полке (2)", "hole_d": "диаметр (7)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def corner_bracket(a, name):
    size = a.vec("size", 2, default=(80.0, 80.0))
    arm_x, arm_z = float(size[0]), float(size[1])
    width = float(a.num("width", 60.0, minv=10.0, maxv=600.0))
    t = float(a.num("thickness", 5.0, minv=1.0, maxv=40.0))
    gus = float(a.num("gusset", 5.0, minv=0.0, maxv=40.0) or 0.0)
    gus_d = float(a.num("gusset_depth", 35.0, minv=5.0, maxv=600.0))
    holes = int(a.num("holes", 2, minv=0, maxv=6) or 0)
    hole_d = float(a.num("hole_d", 7.0, minv=0.5, maxv=40.0))
    arm_x = max(arm_x, t * 3.0)
    arm_z = max(arm_z, t * 3.0)
    gus_d = min(gus_d, arm_x * 0.8, arm_z * 0.8)

    base = _box(arm_x, width, t, center=False).translate((-arm_x / 2.0, -width / 2.0, 0.0))
    upright = _box(t, width, arm_z, center=False).translate(
        (-arm_x / 2.0, -width / 2.0, 0.0))
    solid = base + upright
    if gus > 0:
        tri = [(-arm_x / 2.0 + t - 1.0, 0.0), (-arm_x / 2.0 + t + gus_d, 0.0),
               (-arm_x / 2.0 + t - 1.0, gus_d)]
        wedge = _cross(tri).extrude(gus).rotate((90, 0, 0)).translate(
            (0, gus / 2.0, 0.0))
        solid = solid + wedge
    # Отверстия стоят двумя рядами по краям полки: по центру проходит косынка.
    row = width * (0.34 if gus > 0 else 0.0)
    for i in range(holes):
        x = -arm_x / 2.0 + arm_x * (i + 1) / (holes + 1) * 0.82
        z = arm_z * (i + 1) / (holes + 1) * 0.82
        for sy in ((-1, 1) if row > 0 else (0,)):
            y = sy * row
            solid = solid - _cyl(t + 2.0, hole_d / 2.0, 32).translate((x, y, -1.0))
            solid = solid - _cyl(t + 2.0, hole_d / 2.0, 32).rotate((0, 90, 0)).translate(
                (-arm_x / 2.0 - 1.0, y, z))
    return _finish(a, name, solid, "corner_bracket",
                   f"угловой кронштейн {arm_x:g}×{arm_z:g} · полка {width:g} мм · "
                   f"сталь {t:g} мм · косынка {gus:g} мм"
                   + (f" · отверстий {holes * 2}" if holes else ""))


# --------------------------------------------------------------------------- #
#  Фастекс
# --------------------------------------------------------------------------- #
@op("buckle", aliases=("фастекс", "застёжка", "пряжка", "side_release"),
    category="Примитивы",
    summary="Фастекс (side-release): рамка с гнёздами и ответная часть с двумя "
            "пружинными усиками. Обе половины лежат рядом, как в разобранном виде.",
    example="застёжка = buckle width=25 length=60",
    params={"width": "ширина под стропу, мм (25)", "length": "полная длина, мм (60)",
            "thickness": "толщина, мм (7)", "gap": "зазор между половинами, мм (2)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def buckle(a, name):
    strap = float(a.num("width", 25.0, minv=5.0, maxv=80.0))
    length = float(a.num("length", 60.0, minv=20.0, maxv=220.0))
    t = float(a.num("thickness", 7.0, minv=2.0, maxv=25.0))
    gap = float(a.num("gap", 2.0, minv=0.5, maxv=20.0))
    body_w = strap + t * 1.7
    wall = max(1.6, t * 0.58)

    # Раскладка: рамка слева −X, ответная часть справа +X, между ними зазор.
    f_len = length * 0.40
    m_len = length * 0.26
    prong = length - f_len - m_len - gap
    if prong < body_w * 0.35:
        raise GeometryError("Фастекс: усики короче корпуса — увеличьте length.")
    left = -length / 2.0
    right = length / 2.0

    # --- женская половина: замкнутая рамка и перекладина под стропу --------
    frame = _box(f_len, body_w, t).translate((left + f_len / 2.0, 0, 0))
    frame = frame - _box(f_len - 2.0 * wall, body_w - 2.0 * wall, t + 2.0).translate(
        (left + f_len / 2.0, 0, 0))
    bar_x = left + wall + strap * 0.22
    frame = frame + _box(wall * 0.9, body_w - 2.0 * wall, t).translate(
        (bar_x, 0, 0))

    # --- мужская половина: площадка с окном под стропу и два усика ---------
    plate = _box(m_len, body_w, t).translate((right - m_len / 2.0, 0, 0))
    plate = plate - _box(m_len * 0.34, strap, t + 2.0).translate(
        (right - m_len * 0.62, 0, 0))
    male = plate
    for sy in (-1, 1):
        y = sy * (body_w / 2.0 - wall * 0.55)
        arm = _box(prong + 1.0, wall * 1.1, t * 0.55).translate(
            (right - m_len - prong / 2.0 + 0.5, y, -t * 0.12))
        hook = _box(wall * 1.0, wall * 1.6, t * 0.55).translate(
            (right - m_len - prong + wall * 0.6, y, -t * 0.12))
        male = male + arm + hook
    guide_w = prong * 0.55
    guide = _box(guide_w, wall * 0.6, t * 0.55).translate(
        (right - m_len - guide_w / 2.0 + 0.5, 0, -t * 0.12))
    male = male + guide
    solid = frame + male
    parts = _part_count(solid)
    return _finish(a, name, solid, "buckle",
                   f"фастекс под стропу {strap:g} мм · {length:g}×{body_w:.0f}×{t:g} мм"
                   + (f" · половин: {parts}" if parts > 1 else ""))


# --------------------------------------------------------------------------- #
#  Зубчатые передачи: профиль зуба
# --------------------------------------------------------------------------- #
def _gear_profile(teeth: int, module: float, add: float = 1.0, ded: float = 1.25):
    pitch_r = module * teeth / 2.0
    r_tip = pitch_r + module * add
    r_root = pitch_r - module * ded
    if r_root <= 0.4:
        raise GeometryError(f"Модуль {module:g} мал для {teeth} зубьев.")
    step = 2.0 * math.pi / teeth
    pts = []
    for i in range(teeth):
        a0 = i * step
        for rf, share in ((r_root, -0.30), (r_tip, -0.16), (r_tip, 0.16),
                          (r_root, 0.30)):
            pts.append((rf * math.cos(a0 + share * step),
                        rf * math.sin(a0 + share * step)))
    return pts, r_tip, r_root, pitch_r


def _bore_hole(bore: float, r_limit: float, seg: int = 48):
    if bore <= 0:
        return None
    if bore / 2.0 >= r_limit - 0.5:
        raise GeometryError(f"Отверстие Ø{bore:g} мм больше тела колеса.")
    return _circle(bore / 2.0, seg)


# --------------------------------------------------------------------------- #
#  Зубчатая рейка
# --------------------------------------------------------------------------- #
@op("rack", aliases=("зубчатая_рейка", "рейка_зубчатая", "gear_rack"),
    category="Примитивы",
    summary="Зубчатая рейка под шестерню того же модуля: трапецеидальные зубья "
            "сверху, основание с крепёжными отверстиями.",
    example="рейка = rack length=300 module=2 width=20 height=18",
    params={"length": "длина, мм (300)", "module": "модуль, мм (2)",
            "width": "ширина, мм (20)", "height": "высота с зубьями, мм (18)",
            "teeth": "число зубьев (0 — по длине)",
            "holes": "отверстий в основании (0)", "hole_d": "диаметр отверстий (5)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def rack(a, name):
    length = float(a.num("length", 300.0, minv=20.0, maxv=4000.0))
    module = float(a.num("module", 2.0, minv=0.2, maxv=20.0))
    width = float(a.num("width", 20.0, minv=2.0, maxv=400.0))
    height = float(a.num("height", 18.0, minv=3.0, maxv=400.0))
    holes = int(a.num("holes", 0, minv=0, maxv=40) or 0)
    hole_d = float(a.num("hole_d", 5.0, minv=0.5, maxv=40.0))
    pitch = math.pi * module
    teeth = int(a.num("teeth", 0, minv=0, maxv=400) or 0) or max(3, int(length / pitch))
    teeth = max(3, teeth)
    tooth_h = module * 2.25
    if height <= tooth_h * 1.1:
        raise GeometryError(f"Высота рейки мала: на зубья нужно {tooth_h * 2.2:.1f} мм.")
    base_h = height - tooth_h
    step = length / teeth

    pts = [(-length / 2.0, 0.0)]
    for i in range(teeth):
        x0 = -length / 2.0 + i * step
        pts += [(x0 + step * 0.30, base_h),
                (x0 + step * 0.36, base_h + tooth_h * 0.45),
                (x0 + step * 0.38, base_h + tooth_h),
                (x0 + step * 0.62, base_h + tooth_h),
                (x0 + step * 0.64, base_h + tooth_h * 0.45),
                (x0 + step * 0.70, base_h)]
    pts += [(length / 2.0, 0.0)]
    solid = _cross(pts).extrude(width).rotate((90, 0, 0)).translate(
        (0, width / 2.0, 0))
    for i in range(holes):
        x = -length / 2.0 + length * (i + 1) / (holes + 1)
        solid = solid - _cyl(base_h + 2.0, hole_d / 2.0, 32).translate((x, 0, -1.0))
    return _finish(a, name, solid, "rack",
                   f"рейка m{module:g} · {teeth} зубьев · "
                   f"{length:g}×{width:g}×{height:g} мм")


# --------------------------------------------------------------------------- #
#  Колесо с внутренними зубьями
# --------------------------------------------------------------------------- #
@op("gear_internal", aliases=("внутренняя_шестерня", "кольцевая_шестерня",
                              "internal_gear"), category="Примитивы",
    summary="Колесо с внутренними зубьями: зубчатый венец смотрит внутрь, "
            "снаружи гладкий обод.",
    example="кольцо = gear_internal teeth=40 module=2 thickness=10 rim=6",
    params={"teeth": "число зубьев (40)", "module": "модуль, мм (2)",
            "thickness": "толщина, мм (10)", "rim": "толщина обода, мм (6)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def gear_internal(a, name):
    teeth = int(a.num("teeth", 40, minv=10, maxv=300))
    module = float(a.num("module", 2.0, minv=0.2, maxv=20.0))
    thickness = float(a.num("thickness", 10.0, minv=1.0, maxv=200.0))
    rim = float(a.num("rim", 6.0, minv=1.0, maxv=200.0))
    pitch_r = module * teeth / 2.0
    r_tip = pitch_r + module          # зубья направлены внутрь
    r_root = pitch_r - module * 1.25
    r_od = r_tip + rim
    if r_root <= module * 2.0:
        raise GeometryError("Слишком мало зубьев для внутреннего зацепления — "
                            "увеличьте teeth.")
    solid = _ring(r_od, r_root + 0.5, thickness)
    step = 2.0 * math.pi / teeth
    for i in range(teeth):
        a0 = i * step
        quad = [(r_root - 0.5, a0 - 0.30 * step), (r_tip, a0 - 0.17 * step),
                (r_tip, a0 + 0.17 * step), (r_root - 0.5, a0 + 0.30 * step)]
        pts2 = [(r * math.cos(a_), r * math.sin(a_)) for r, a_ in quad]
        solid = solid + _cross(pts2).extrude(thickness)
    return _finish(a, name, solid, "gear_internal",
                   f"колесо с внутренними зубьями z={teeth} m{module:g} · "
                   f"Ø{2 * r_od:.1f}×{thickness:g} мм")


# --------------------------------------------------------------------------- #
#  Косозубое колесо
# --------------------------------------------------------------------------- #
@op("gear_helical", aliases=("косозубая_шестерня", "шестерня_косозубая",
                             "helical_gear"), category="Примитивы",
    summary="Косозубая шестерня: тот же профиль зуба, что у gear, но венец "
            "закручен по винтовой линии на угол наклона зуба.",
    example="косозубая = gear_helical teeth=24 module=2 thickness=12 angle=20",
    params={"teeth": "число зубьев (24)", "module": "модуль, мм (2)",
            "thickness": "толщина венца, мм (12)",
            "angle": "угол наклона зуба, градусы (20)",
            "bore": "отверстие, мм (0)", "at": "положение [x,y,z]",
            "center": "центрировать в at"})
def gear_helical(a, name):
    teeth = int(a.num("teeth", 24, minv=6, maxv=200))
    module = float(a.num("module", 2.0, minv=0.2, maxv=20.0))
    thickness = float(a.num("thickness", 12.0, minv=1.0, maxv=200.0))
    angle = float(a.num("angle", 20.0, minv=-45.0, maxv=45.0))
    bore = float(a.num("bore", 0.0, minv=0.0) or 0.0)
    pts, r_tip, r_root, _ = _gear_profile(teeth, module)
    hole = _bore_hole(bore, r_root)
    cs = _cross(pts, [hole] if hole else None)
    div = max(4, int(abs(angle) / 2.5))
    solid = cs.extrude(thickness, div, twist_degrees=angle)
    return _finish(a, name, solid, "gear_helical",
                   f"косозубая z={teeth} m{module:g} · наклон {angle:g}° · "
                   f"Ø{2 * r_tip:.1f}×{thickness:g} мм")


# --------------------------------------------------------------------------- #
#  Коническое колесо
# --------------------------------------------------------------------------- #
@op("gear_bevel", aliases=("коническая_шестерня", "шестерня_коническая",
                           "bevel_gear"), category="Примитивы",
    summary="Коническая шестерня: зубья сбегают к малому торцу, венец сужается.",
    example="коническая = gear_bevel teeth=20 module=2 thickness=12 taper=0.6",
    params={"teeth": "число зубьев (20)", "module": "модуль по большому торцу (2)",
            "thickness": "ширина венца, мм (12)",
            "taper": "доля большого торца, остающаяся у малого, 0.3…0.85 (0.6)",
            "bore": "отверстие, мм (0)", "at": "положение [x,y,z]",
            "center": "центрировать в at"})
def gear_bevel(a, name):
    teeth = int(a.num("teeth", 20, minv=8, maxv=200))
    module = float(a.num("module", 2.0, minv=0.2, maxv=20.0))
    thickness = float(a.num("thickness", 12.0, minv=1.0, maxv=200.0))
    taper = float(a.num("taper", 0.6, minv=0.3, maxv=0.85))
    bore = float(a.num("bore", 0.0, minv=0.0) or 0.0)
    pts, r_tip, r_root, _ = _gear_profile(teeth, module)
    cs = _cross(pts)
    solid = cs.extrude(thickness, max(4, int(thickness / 1.5)),
                       twist_degrees=0.0, scale_top=(taper, taper))
    if bore:
        solid = solid - _cone(thickness + 2.0, bore / 2.0,
                              max(0.4, bore / 2.0 * taper), 48).translate(
            (0, 0, -1.0))
    return _finish(a, name, solid, "gear_bevel",
                   f"коническая z={teeth} m{module:g} · венец {thickness:g} мм · "
                   f"сужение до {taper * 100:.0f}%")


# --------------------------------------------------------------------------- #
#  Головки винтов
# --------------------------------------------------------------------------- #
_HEAD_TYPES = {
    "потай": "csk", "потайная": "csk", "csk": "csk", "зенкованная": "csk",
    "полукруг": "pan", "полукруглая": "pan", "pan": "pan",
    "цилиндр": "socket", "цилиндрическая": "socket", "socket": "socket",
    "шестигранник": "hex", "шестигранная": "hex", "hex": "hex",
    "фланец": "flange_hex", "с_фланцем": "flange_hex", "flange": "flange_hex",
    "шайба": "flange_pan", "с_шайбой": "flange_pan", "flanged_pan": "flange_pan",
    "шестилопастная": "lobe", "лобастая": "lobe", "lobe": "lobe",
}
_DRIVES = {
    "крест": "cross", "phillips": "cross", "ph": "cross",
    "шлиц": "slot", "плоский": "slot", "slot": "slot",
    "звезда": "torx", "torx": "torx",
    "шестигранник": "hex", "hex": "hex", "имбус": "hex",
    "torx_plus": "torx_plus", "торкс_плюс": "torx_plus",
    "комбинированный": "combo", "combo": "combo",
    "нет": "none", "none": "none", "без": "none",
}


@op("screw_head", aliases=("головка_винта", "винтовая_головка", "screwhead"),
    category="Примитивы",
    summary="Головка винта как отдельная деталь: семь профилей (потай, "
            "полукруг, цилиндр, шестигранник, с фланцем, «шайба», "
            "шестилопастная) и шесть шлицов.",
    example="головка = screw_head d=6 head=цилиндр drive=шестигранник\n"
            "потай = screw_head d=4 head=потай drive=крест\n"
            "торкс = screw_head d=5 head=полукруг drive=torx_plus",
    params={"d": "диаметр резьбы под головкой, мм (6)",
            "head_d": "диаметр головки (2 × d)",
            "head_h": "высота головки (у потайной — по углу 90°)",
            "head": "потай, полукруг, цилиндр, шестигранник, фланец, шайба "
                    "или шестилопастная (цилиндр)",
            "drive": "крест, шлиц, звезда, шестигранник, torx_plus, "
                     "комбинированный или нет (шестигранник)",
            "drive_size": "размер шлица, мм (0.5 × head_d)",
            "drive_depth": "глубина шлица, мм (0.5 × высоты головки)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def screw_head(a, name):
    d = float(a.num("d", 6.0, minv=0.5, maxv=100.0))
    head_raw = (a.text("head") or "цилиндр").strip().lower()
    if head_raw not in _HEAD_TYPES:
        raise GeometryError(
            f"screw_head: неизвестная головка «{head_raw}».",
            hint="Есть: потай, полукруг, цилиндр, шестигранник, фланец, "
                 "шайба, шестилопастная.")
    head = _HEAD_TYPES[head_raw]
    drive_raw = (a.text("drive") or "шестигранник").strip().lower()
    if drive_raw not in _DRIVES:
        raise GeometryError(
            f"screw_head: неизвестный шлиц «{drive_raw}».",
            hint="Есть: крест, шлиц, звезда, шестигранник, torx_plus, "
                 "комбинированный, нет.")
    drive = _DRIVES[drive_raw]
    default_d = 2.0 * d if head not in ("csk", "flange_hex", "flange_pan") else 2.1 * d
    head_d = float(a.num("head_d", default_d, minv=1.2 * d, maxv=20.0 * d))
    if head == "csk":
        head_h = float(a.num("head_h", (head_d - d) / 2.0, minv=0.4, maxv=5.0 * d))
    else:
        head_h = float(a.num("head_h", 0.62 * d, minv=0.4, maxv=10.0 * d))
    top = head_h

    if head == "csk":
        solid = _cone(head_h, d / 2.0, head_d / 2.0, 56)
        solid = solid + _cyl(0.3, head_d / 2.0, 56).translate((0, 0, head_h - 0.3))
        top = head_h
    elif head == "pan":
        body_h = head_h * 0.55
        rr = head_d / 2.0
        solid = _cyl(body_h, rr, 56)
        dome = mf.Manifold.sphere(rr, 48).translate((0, 0, body_h))
        dome = dome - _box(rr * 3, rr * 3, rr * 3).translate(
            (0, 0, body_h - rr * 1.5))          # оставляем верхнюю полусферу
        solid = solid + dome
        top = body_h + rr
    elif head == "socket":
        solid = _cyl(head_h, head_d / 2.0, 56)
        ch = min(head_h * 0.35, head_d * 0.12, 0.9)
        cutter = (_cyl(ch, head_d / 2.0 + 0.3, 56)
                  - _cyl(ch + 1.0, head_d / 2.0 - ch, 56))
        solid = solid - cutter.translate((0, 0, head_h - ch))
        top = head_h
    elif head == "hex":
        r = head_d / math.sqrt(3.0)
        solid = mf.Manifold.cylinder(head_h, r, r, 6)
        top = head_h
    elif head == "flange_hex":
        flange_h = max(0.6, head_h * 0.18)
        flange_r = head_d / 2.0
        r = (head_d * 0.845) / math.sqrt(3.0)
        solid = _cyl(flange_h, flange_r, 56)
        solid = solid + mf.Manifold.cylinder(head_h + flange_h * 0.5, r, r, 6)
        top = head_h + flange_h * 0.5
    elif head == "flange_pan":
        flange_h = max(0.6, head_h * 0.2)
        solid = _cyl(flange_h, head_d / 2.0, 56)
        solid = solid + _cyl(head_h, head_d * 0.36, 56).translate((0, 0, flange_h))
        top = head_h + flange_h
    else:      # шестилопастная: наружный контур с шестью плавными лопастями
        lobes = []
        for i in range(120):
            ang = 2 * math.pi * i / 120
            r = head_d / 2.0 * (0.86 + 0.14 * math.cos(6 * ang))
            lobes.append((r * math.cos(ang), r * math.sin(ang)))
        solid = _cross(lobes).extrude(head_h)
        top = head_h

    if drive != "none":
        size = float(a.num("drive_size", 0.5 * head_d, minv=0.3,
                           maxv=head_d * 0.8))
        want = float(a.num("drive_depth", max(0.5, head_h * 0.5), minv=0.1))
        deep = min(want, max(0.3, (top - 0.0) * 0.6))
        if drive == "cross":
            tool = _cross(_plus_shape(size, size * 0.28)).extrude(deep + 1.0)
            solid = solid - tool.translate((0, 0, top - deep))
        elif drive == "slot":
            solid = solid - _box(head_d * 1.05, max(0.4, size * 0.26), deep + 1.0).translate(
                (0, 0, top - deep))
        elif drive in ("torx", "torx_plus"):
            # Torx — шесть круглых лопастей вокруг одного кармана: союз
            # цилиндров даёт честный контур, модулированный радиус — нет.
            lobe_ring = size * 0.30
            lobe_r = size * 0.20 if drive == "torx" else size * 0.22
            core_r = size * 0.28 if drive == "torx" else size * 0.30
            cs = _cross(_circle(core_r, 48))
            for i in range(6):
                ang = 2 * math.pi * i / 6
                cs = cs + _cross(_circle(lobe_r, 32,
                                         lobe_ring * math.cos(ang),
                                         lobe_ring * math.sin(ang)))
            solid = solid - cs.extrude(deep + 1.0).translate((0, 0, top - deep))
        elif drive == "hex":
            r = size / math.sqrt(3.0)
            solid = solid - mf.Manifold.cylinder(deep + 1.0, r, r, 6).translate(
                (0, 0, top - deep))
        else:      # комбинированный: крест и поверх него прямой шлиц
            tool = _cross(_plus_shape(size, size * 0.26)).extrude(deep + 1.0)
            solid = solid - tool.translate((0, 0, top - deep))
            slot = _box(min(head_d * 0.92, size * 1.25), max(0.4, size * 0.20),
                        deep * 0.75 + 1.0)
            solid = solid - slot.translate((0, 0, top - deep * 0.75))
    return _finish(a, name, solid, "screw_head",
                   f"головка {head_raw} Ø{head_d:g}×{top:.2f} мм · шлиц {drive_raw}"
                   f" · под резьбу M{d:g}")


# --------------------------------------------------------------------------- #
#  Барашек
# --------------------------------------------------------------------------- #
@op("wing_nut", aliases=("барашек", "гайка_барашек", "wingnut"), category="Примитивы",
    summary="Гайка-барашек: ступица с резьбой и два лепестка-крыла, которые "
            "отливаются вместе со ступицей.",
    example="барашек = wing_nut d=8 wing=26 height=18",
    params={"d": "диаметр резьбы, мм (8)", "pitch": "шаг резьбы (1.25)",
            "height": "высота ступицы, мм (18)",
            "wing": "вылет крыла от оси, мм (26)",
            "wing_t": "толщина крыла, мм (5)",
            "thread": "нарезать резьбу (да)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def wing_nut(a, name):
    d = float(a.num("d", 8.0, minv=2.0, maxv=100.0))
    pitch = float(a.num("pitch", max(0.35, 0.15 * d), minv=0.1, maxv=10.0))
    h = float(a.num("height", 18.0, minv=4.0, maxv=200.0))
    wing = float(a.num("wing", 26.0, minv=d * 1.2, maxv=400.0))
    wt = float(a.num("wing_t", 5.0, minv=1.0, maxv=60.0))
    thread = a.boolean("thread", True)
    boss_r = max(d * 0.82, h * 0.42)
    if wing <= boss_r:
        raise GeometryError("Крыло короче ступицы — барашек не получится: "
                            "увеличьте wing.")

    # контур крыла в плоскости XZ (x — вылет, z — высота), симметрично
    right = [(0.0, h * 0.62), (wing * 0.22, h * 0.96), (wing * 0.55, h * 1.0),
             (wing * 0.84, h * 0.80), (wing, h * 0.42), (wing * 0.78, h * 0.10),
             (wing * 0.40, 0.0), (0.0, 0.0)]
    left = [(-x, z) for (x, z) in reversed(right[1:-1])]
    poly = right + left          # x>0 сверху вниз, затем x<0 снизу вверх
    body = _cross(poly).extrude(wt).rotate((90, 0, 0)).translate((0, wt / 2.0, 0))
    boss = _cyl(h, boss_r, 72)
    solid = body + boss
    if thread:
        solid = solid - _thread_bore(d, pitch, h)
    else:
        solid = solid - _cyl(h + 0.4, d * 0.42, 48).translate((0, 0, -0.2))
    return _finish(a, name, solid, "wing_nut",
                   f"барашек M{d:g} · высота {h:g} мм · вылет {wing:g} мм"
                   + (" · резьба" if thread else ""))


# --------------------------------------------------------------------------- #
#  Особые гайки
# --------------------------------------------------------------------------- #
_NUT_KINDS = {
    "колпачковая": "cap", "колпак": "cap", "cap": "cap",
    "фланец": "flange", "с_фланцем": "flange", "flange": "flange",
    "nyloc": "nyloc", "самоконтрящаяся": "nyloc", "нейлоновая": "nyloc",
    "квадратная": "square", "square": "square",
    "t": "t", "т": "t", "t_гайка": "t",
    "закладная": "weld", "weld": "weld", "приварная": "weld",
}


@op("special_nut", aliases=("гайка_колпачковая", "гайка_с_фланцем",
                            "гайка_nyloc", "гайка_квадратная", "гайка_t",
                            "гайка_закладная", "special_nut"),
    category="Примитивы",
    summary="Гайки, которых нет у nut: колпачковая, с фланцем, самоконтрящаяся "
            "Nyloc, квадратная, T-гайка и закладная (приварная).",
    example="колпак = special_nut d=8 type=колпачковая\n"
            "фланец = special_nut d=6 type=фланец\n"
            "nyloc = special_nut d=10 type=nyloc",
    params={"d": "диаметр резьбы, мм (8)", "pitch": "шаг резьбы (1.25)",
            "h": "высота гайки, мм (0.8 × d)",
            "s": "размер под ключ, мм (1.6 × d)",
            "type": "колпачковая, фланец, nyloc, квадратная, t или закладная "
                    "(колпачковая)",
            "thread": "нарезать резьбу (да)",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def special_nut(a, name):
    d = float(a.num("d", 8.0, minv=1.5, maxv=200.0))
    pitch = float(a.num("pitch", max(0.35, 0.15 * d), minv=0.1, maxv=20.0))
    h = float(a.num("h", 0.8 * d, minv=0.6, maxv=200.0))
    s = float(a.num("s", max(d + 2.0, 1.6 * d), minv=d * 0.9, maxv=600.0))
    kind_raw = (a.text("type") or "колпачковая").strip().lower()
    if kind_raw not in _NUT_KINDS:
        raise GeometryError(
            f"special_nut: неизвестный тип «{kind_raw}».",
            hint="Есть: колпачковая, фланец, nyloc, квадратная, t, закладная.")
    kind = _NUT_KINDS[kind_raw]
    thread = a.boolean("thread", True)
    hex_r = s / math.sqrt(3.0)

    if kind == "cap":
        dome_h = min(s * 0.55, h * 1.1)
        cap_r = s * 0.58
        cap = mf.Manifold.sphere(cap_r, 48).translate((0, 0, h - 1.0))
        cap = cap - _box(cap_r * 3, cap_r * 3, cap_r * 3).translate(
            (0, 0, h - 1.0 - cap_r * 1.5))
        solid = _hex_prism(s, h) + cap
        depth = h - 1.0 + dome_h * 0.55
    elif kind == "flange":
        flange_h = max(0.8, h * 0.18)
        flange_r = s * 0.72
        solid = _cyl(flange_h, flange_r, 72)
        solid = solid + _hex_prism(max(0.5, s * 0.88), h).translate((0, 0, flange_h))
        h = h + flange_h
        depth = h
    elif kind == "nyloc":
        h_hex = max(0.8, h * 0.72)
        collar_h = h - h_hex
        collar_r = s * 0.68
        solid = _hex_prism(s, h_hex)
        solid = solid + _cyl(collar_h + 1.0, collar_r, 64).translate((0, 0, h_hex - 1.0))
        # нейлоновое кольцо: кольцевой паз сверху
        solid = solid - _ring(collar_r - 0.8, d * 0.30, collar_h * 0.42 + 0.5).translate(
            (0, 0, h - collar_h * 0.42))
        depth = h
    elif kind == "square":
        side = s * 0.92
        solid = _box(side, side, h, center=False).translate((-side / 2.0, -side / 2.0, 0.0))
        depth = h
    elif kind == "t":
        flange_h = max(0.6, h * 0.22)
        flange_r = s * 0.78
        solid = _cyl(flange_h, flange_r, 72)
        solid = solid + _cyl(h - flange_h, min(s * 0.48, flange_r * 0.7), 64).translate(
            (0, 0, flange_h))
        h = h + flange_h
        depth = h
    else:      # закладная / приварная: квадратная площадка с четырьмя бобышками
        plate = s * 1.12
        plate_h = max(0.8, h * 0.3)
        solid = _box(plate, plate, plate_h, center=False).translate(
            (-plate / 2.0, -plate / 2.0, 0.0))
        boss_h = h - plate_h
        solid = solid + _cyl(boss_h, s * 0.42, 64).translate((0, 0, plate_h))
        for i in range(4):
            ang = math.pi / 4.0 + i * math.pi / 2.0
            px = plate * 0.36 * math.cos(ang)
            py = plate * 0.36 * math.sin(ang)
            solid = solid - _cyl(plate_h + 1.0, s * 0.10, 24).translate(
                (px, py, -0.5))
        h = h + 0.0
        depth = h

    if thread:
        solid = solid - _thread_bore(d, pitch, depth)
    else:
        solid = solid - _cyl(depth + 0.4, d * 0.42, 48).translate((0, 0, -0.2))
    return _finish(a, name, solid, "special_nut",
                   f"гайка {kind_raw} M{d:g} · под ключ {s:g} мм · высота {h:g} мм"
                   + (" · резьба" if thread else ""))


def _hex_prism(across_flats: float, height: float) -> mf.Manifold:
    r = float(across_flats) / math.sqrt(3.0)
    return mf.Manifold.cylinder(float(height), r, r, 6)


# --------------------------------------------------------------------------- #
#  Исходная ориентация (дополняет forma/orient_notes.py при импорте модуля)
# --------------------------------------------------------------------------- #
ORIENTATION_NOTES = {
    "bearing": "Ось и посадочное отверстие по Z: торцы колец в плоскостях XY, "
               "тела качения и сепаратор между ними. d — внутренний, D — "
               "наружный диаметр, B — ширина вдоль Z. Упорный тип даёт два "
               "плоских кольца с шарами между ними.",
    "din_rail": "Длина по X, ширина профиля (35/15/45) по Y, высота 7.5 мм по "
                "+Z; загнутые полки и просвет смотрят вверх +Z, просечки "
                "проходят по Z через заднюю стенку. Низ рейки на z=0.",
    "crate": "Длина по X, ширина по Y, высота по +Z; дно на z=0 (или на "
             "полозьях), стойки в четырёх вертикальных углах, доски стенок "
             "горизонтальны. Крышка при lid=да добавляется сверху +Z.",
    "lug": "Площадка лежит в XY, отверстие под палец в начале координат, "
           "площадка уходит в −Y; отогнутая полка поднимается +Z на дальнем "
           "конце −Y. Крепёжные отверстия полки проходят по Y.",
    "corner_bracket": "Угол в начале координат: горизонтальная полка идёт +X, "
                      "вертикальная поднимается +Z, ширина полки по Y "
                      "симметрична. Косынка стоит в плоскости XY? нет — в XZ, "
                      "по центру ширины.",
    "buckle": "Обе половины лежат в XY толщиной по Z: рамка слева −X, "
              "ответная часть справа +X, усики смотрят в −X. Окна под стропу "
              "сквозные по Z.",
    "rack": "Длина и зубья идут по X, ширина по Y, высота по +Z; зубья "
            "смотрят вверх +Z, основание снизу на z=0.",
    "gear_internal": "Венец лежит в XY, ось и толщина по Z; зубья направлены "
                     "внутрь к оси, наружная поверхность гладкая.",
    "gear_helical": "Венец лежит в XY, ось по Z; зубья закручены винтом вдоль "
                    "Z на angle. Положительный угол закручивает верх "
                    "относительно низа.",
    "gear_bevel": "Большой торец снизу на z=0, малый сверху +Z; зубья сбегают "
                  "к верхнему торцу, ось по Z.",
    "screw_head": "Головка стоит на плоском основании z=0 и растёт вверх +Z; "
                  "шлиц открыт сверху. У потайной основание — узкий торец "
                  "диаметром d, расширение идёт вверх.",
    "wing_nut": "Ось резьбы и ступицы по Z, крылья разведены по ±X и лежат "
                "плашмя: толщина крыла по Y. Низ гайки на z=0.",
    "special_nut": "Ось резьбы по Z, низ гайки на z=0; колпачок и поясок "
                   "Nyloc направлены +Z, фланец у фланцевой и T-гайки — вниз, "
                   "бобышки закладной — снизу −Z.",
}
