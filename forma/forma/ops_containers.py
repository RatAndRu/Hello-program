"""Банки, бутылки и отдельные крышки.

Сосуды строятся одной замкнутой оболочкой с настоящей внутренней полостью,
а не прозрачным цилиндром.  Профили дна задают внешний punt (углубление) и литое petaloid-дно,
резьба является винтовым объёмом.
Крышка и пробка — самостоятельно выбираемые физические детали.
"""

from __future__ import annotations

import copy
import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, solid_parts, sweep_solid
from .ops import op
from .ops_fittings import _assembly
from .ops_tech import _helix_ridge


def _emit(a, name: str, parts: list[tuple], params: dict):
    """Добавляет материалы к компактным записям деталей и регистрирует сборку."""
    colors = {
        "jar": "#b9d8d4", "bottle": "#b9d8d4", "jar_lid": "#b7b9b4",
        "bottle_cap": "#d5d7d2", "cork": "#b78c5d", "lid": "#c5c9ca",
        "pot_lid": "#c5c9ca", "lid_rim": "#9da6ab", "lid_handle": "#343a3e",
        "lid_fastener": "#9da6ab", "lid_vent": "#9da6ab",
    }
    preset = {}
    if a.has("material"):
        from .geometry import MATERIAL_PRESETS
        preset = MATERIAL_PRESETS.get((a.text("material") or "").strip().lower(), {})
    full = []
    for suffix, manifold, color_key, kind in parts:
        metal = preset.get("metal", 0.72 if kind == "jar_lid" else 0.0)
        rough = preset.get("rough", 0.28 if kind == "jar_lid" else 0.5)
        default_color = preset.get("color", colors.get(kind, "#c5c9ca"))
        full.append((suffix, manifold, color_key, default_color, metal, rough, kind))
    return _assembly(a, name, full, params, "containers")


def _xy(radius: float, theta: float, exponent: float) -> tuple[float, float]:
    """Точка круга или скруглённого прямоугольника (superellipse)."""
    c, s = math.cos(theta), math.sin(theta)
    power = 2.0 / exponent
    return (radius * math.copysign(abs(c) ** power, c),
            radius * math.copysign(abs(s) ** power, s))


def _open_vessel_mesh(outer_center_z: float, outer: list[tuple[float, float, float]],
                      inner_center_z: float, inner: list[tuple[float, float, float]],
                      segments: int, ribs: int, rib_depth: float,
                      rib_height: float, petaloid: dict | None = None) -> mf.Manifold:
    """Одна замкнутая оболочка с полостью и, при необходимости, литым дном.

    Petaloid-лапки задаются высотой точек наружных и внутренних колец дна.
    Поэтому они являются непрерывной частью корпуса: здесь нет приклеенных
    сфер, отдельных островов или стыков между разными примитивами.
    """
    if not outer or not inner or len(outer) != len(inner):
        raise GeometryError("Профили сосуда должны содержать одинаковое число колец.")
    verts: list[tuple[float, float, float]] = []

    def add_ring(radius: float, z: float, exponent: float, fluted: bool,
                 ring_index: int) -> None:
        for j in range(segments):
            theta = 2.0 * math.pi * j / segments
            rr = radius
            if (fluted and ribs > 0 and rib_depth > 0 and rib_height > 0
                    and z <= rib_height
                    and (not petaloid or ring_index >= petaloid["rings"] - 1)):
                weight = max(0.0, 1.0 - z / rib_height)
                # Впадины уходят внутрь от исходного профиля: гребни не
                # выходят за номинальный габарит корпуса.
                rr += rib_depth * weight * (math.cos(ribs * theta) - 1.0)
            x, y = _xy(rr, theta, exponent)
            zz = z
            if petaloid and ring_index < petaloid["rings"]:
                # Вершина лепестка остаётся на исходном профиле, а впадина
                # между лепестками поднимается. Внутренняя поверхность дна
                # повторяет ту же волну: толщина не исчезает и оболочки не
                # пересекаются даже на верхних участках впадин.
                wave = (0.5 + 0.5 * math.cos(petaloid["count"] * theta)) ** 1.35
                zz += petaloid["valley"][ring_index] * (1.0 - wave)
            verts.append((x, y, zz))

    for ring_index, (radius, z, exponent) in enumerate(outer):
        add_ring(radius, z, exponent, True, ring_index)
    for ring_index, (radius, z, exponent) in enumerate(inner):
        add_ring(radius, z, exponent, False, ring_index)
    outer_center = len(verts)
    verts.append((0.0, 0.0, outer_center_z))
    inner_center = len(verts)
    verts.append((0.0, 0.0, inner_center_z))

    faces: list[tuple[int, int, int]] = []
    rings = len(outer)
    inner_offset = rings * segments
    for ring in range(rings - 1):
        a, b = ring * segments, (ring + 1) * segments
        ia, ib = inner_offset + a, inner_offset + b
        for j in range(segments):
            k = (j + 1) % segments
            faces.extend(((a + j, a + k, b + k), (a + j, b + k, b + j)))
            faces.extend(((ia + j, ib + k, ia + k), (ia + j, ib + j, ib + k)))
    for j in range(segments):
        k = (j + 1) % segments
        # Внешнее дно смотрит вниз, внутреннее — в полость.
        faces.append((outer_center, k, j))
        faces.append((inner_center, inner_offset + j, inner_offset + k))
        # Верхняя кромка соединяет две оболочки.
        o = (rings - 1) * segments
        i = inner_offset + o
        faces.extend(((o + j, o + k, i + k), (o + j, i + k, i + j)))
    return manifold_from_arrays(np.asarray(verts), np.asarray(faces), "сосуд")


def _closed_radial(radius: float, height: float, segments: int, ribs: int = 0,
                   rib_depth: float = 0.0) -> mf.Manifold:
    """Рифлёный цилиндр с плоскими торцами; используется для крышек."""
    ring_count = 4
    verts: list[tuple[float, float, float]] = []
    for ring in range(ring_count):
        z = height * ring / (ring_count - 1)
        # Рифление затухает у торцов, чтобы кромки остались аккуратными.
        fade = 0.35 if ring in (0, ring_count - 1) else 1.0
        for j in range(segments):
            theta = 2.0 * math.pi * j / segments
            rr = radius
            if ribs:
                rr += rib_depth * fade * math.cos(ribs * theta)
            verts.append((rr * math.cos(theta), rr * math.sin(theta), z))
    bottom, top = len(verts), len(verts) + 1
    verts.extend(((0.0, 0.0, 0.0), (0.0, 0.0, height)))
    faces: list[tuple[int, int, int]] = []
    for ring in range(ring_count - 1):
        a, b = ring * segments, (ring + 1) * segments
        for j in range(segments):
            k = (j + 1) % segments
            faces.extend(((a + j, a + k, b + k), (a + j, b + k, b + j)))
    last = (ring_count - 1) * segments
    for j in range(segments):
        k = (j + 1) % segments
        faces.append((bottom, k, j))
        faces.append((top, last + j, last + k))
    return manifold_from_arrays(np.asarray(verts), np.asarray(faces), "крышка")


def _grow_profile(outer: list[tuple[float, float, float]], radius: float, z: float,
                  steps: int, curve: str = "smooth", exponent: float | None = None) -> None:
    """Добавляет плавный участок вращения без дублирующихся колец."""
    start_r, start_z, start_exp = outer[-1]
    if z <= start_z + 1e-7:
        raise GeometryError("Высота дна и корпуса оставила слишком мало места профилю.")
    target_exp = start_exp if exponent is None else float(exponent)
    for i in range(1, steps + 1):
        t = i / steps
        if curve == "linear":
            s = t
        elif curve == "smooth_start":
            # Нулевой уклон в начале и единичный в конце: сопрягает дно с
            # последующим прямым участком без ступеньки направления.
            s = t * t * (2.0 - t)
        elif curve == "sine":
            s = math.sin(t * math.pi * 0.5)
        else:
            s = t * t * (3.0 - 2.0 * t)
        outer.append((start_r + (radius - start_r) * s,
                      start_z + (z - start_z) * t,
                      start_exp + (target_exp - start_exp) * s))


def _vessel_profiles(height: float, diameter: float, neck_d: float, wall: float,
                     base: float, form: str, neck: str, bottom: str,
                     vessel: str, style: str, feet_count: int) -> tuple:
    """Строит действительно разные силуэты банок и бутылок.

    ``form`` задаёт сечение корпуса, а ``style`` — его пропорции и плечо.
    Материал сюда намеренно не передаётся: ни одна геометрическая настройка
    не включается и не отключается от выбора стекла/пластика.
    """
    r, nr = diameter * 0.5, neck_d * 0.5
    exponent = 4.5 if form == "квадратная" else 2.0
    feet_h = height * 0.035 if bottom == "ножки" else 0.0
    punt = min(diameter * 0.13, height * 0.045) if bottom == "углубление" else feet_h * 1.25

    base_scale = 1.0
    if vessel == "jar" and style == "амфора":
        base_scale = 0.82
    elif vessel == "bottle":
        base_scale = {"бургундская": 0.94, "пивная": 0.90,
                      "спортивная": 0.92}.get(style, 1.0)
    base_r = r * base_scale
    petaloid = None
    if feet_h:
        # Гладкое литое дно: девять радиальных колец центрального подъёма и
        # восемь колец перехода в корпус. Это не сглаживание грубой сетки —
        # сама поверхность сразу строится плотной и без крупных треугольников.
        petal_height = feet_h * 1.55
        max_valley = feet_h * 1.15
        bottom_count = 9
        outer = []
        valley = []
        for i in range(bottom_count):
            t = (i + 1) / bottom_count
            s = t * t * (3.0 - 2.0 * t)
            outer.append((base_r * (0.10 + 0.78 * t),
                          punt * (1.0 - s), exponent))
            valley.append(max_valley * s)
        # На боковом переходе радиус и обе высотные кривые согласованы по
        # касательным с дном и стенкой, чтобы не было тёмной кромки излома.
        # Вершина и впадина задаются двумя кубическими профилями с общей
        # конечной касательной. Впадина не проворачивается через промежуточный
        # минимум, а на последнем кольце обе кривые сливаются без угла.
        rise = petal_height - max_valley
        end_slope = petal_height * 0.5
        crest_quadratic = 3.0 * petal_height - end_slope
        crest_cubic = end_slope - 2.0 * petal_height
        valley_quadratic = 3.0 * rise - end_slope
        valley_cubic = end_slope - 2.0 * rise
        for s in (0.04, 0.12, 0.24, 0.38, 0.54, 0.70, 0.85, 1.0):
            radial = s * (2.0 - s)  # касательная дна в начале
            crest_z = crest_quadratic * s * s + crest_cubic * s ** 3
            valley_z = (max_valley + valley_quadratic * s * s
                        + valley_cubic * s ** 3)
            outer.append((base_r * (0.88 + 0.12 * radial), crest_z, exponent))
            valley.append(valley_z - crest_z)
        petaloid = {
            "count": feet_count,
            "valley": valley,
            "rings": len(outer),
            # Внутренняя оболочка повторяет со смещением base всю нижнюю
            # форму, включая переход, а не только центральный подъём.
            "offset_rings": len(outer),
            "height": petal_height,
        }
    else:
        outer = [
            (base_r * 0.25, punt * 0.82, exponent),
            (base_r * 0.56, punt * 0.35, exponent),
            (base_r * 0.86, 0.0, exponent),
            (base_r, max(0.8, base * 0.35), exponent),
        ]

    linear_start = "smooth_start" if petaloid else "linear"
    if vessel == "jar":
        if style == "коническая":
            body_top, shoulder_end = height * 0.74, height * 0.89
            _grow_profile(outer, r * 0.96, height * 0.20, 4, "linear")
            _grow_profile(outer, r * 0.74, body_top, 12, "linear")
        elif style == "амфора":
            body_top, shoulder_end = height * 0.72, height * 0.90
            _grow_profile(outer, r, height * 0.38, 10)
            _grow_profile(outer, r * 0.80, body_top, 10)
        else:
            body_top, shoulder_end = height * 0.72, height * 0.86
            if form == "округлая":
                _grow_profile(outer, r * 0.97, height * 0.20, 4)
                _grow_profile(outer, r, height * 0.43, 6)
                _grow_profile(outer, r * 0.98, body_top, 5)
            else:
                _grow_profile(outer, r, body_top, 12, "linear")
        _grow_profile(outer, nr, shoulder_end, 10, "smooth", 2.0)
    else:
        long_neck = neck == "длинная"
        if style == "винная":
            body_top = height * (0.68 if long_neck else 0.72)
            shoulder_end = height * (0.84 if long_neck else 0.89)
            _grow_profile(outer, r, body_top, 14, linear_start)
        elif style == "бургундская":
            body_top = height * (0.48 if long_neck else 0.56)
            shoulder_end = height * (0.84 if long_neck else 0.90)
            _grow_profile(outer, r, height * 0.34, 8)
            _grow_profile(outer, r, body_top, 4, "linear")
        elif style == "пивная":
            body_top = height * (0.52 if long_neck else 0.60)
            shoulder_end = height * (0.72 if long_neck else 0.82)
            _grow_profile(outer, r, height * 0.26, 7)
            _grow_profile(outer, r * 0.90, body_top, 8)
        elif style == "спортивная":
            body_top = height * (0.64 if long_neck else 0.68)
            shoulder_end = height * (0.82 if long_neck else 0.88)
            _grow_profile(outer, r, height * 0.24, 7)
            _grow_profile(outer, r * 0.78, height * 0.46, 8)
            _grow_profile(outer, r * 0.88, body_top, 7)
        else:
            body_top = height * (0.62 if long_neck else 0.70)
            shoulder_end = height * (0.80 if long_neck else 0.90)
            if form == "округлая":
                _grow_profile(outer, r * 0.96, height * 0.18, 4)
                _grow_profile(outer, r, height * 0.40, 6)
                _grow_profile(outer, r * 0.99, body_top, 5)
            else:
                _grow_profile(outer, r, body_top, 12, linear_start)
        _grow_profile(outer, nr, shoulder_end,
                      14 if style == "бургундская" else 10, "smooth", 2.0)

    # Короткое горло всегда имеет два отдельных кольца, даже при малой высоте.
    neck_mid = shoulder_end + (height - shoulder_end) * 0.55
    outer.extend(((nr, neck_mid, 2.0), (nr, height, 2.0)))

    outer_center = punt
    inner_center = outer_center + base
    inner: list[tuple[float, float, float]] = []
    # Внутреннее дно повторяет центральный подъём и весь petaloid-переход.
    # Общая волна добавляется к обеим оболочкам в _open_vessel_mesh, поэтому
    # между ними сохраняется заданная вертикальная толщина дна.
    offset_rings = petaloid["offset_rings"] if petaloid else 4
    for radius, z, exp in outer[:offset_rings]:
        inner.append((max(0.2, radius - wall), z + base, exp))
    floor_side_z = outer[offset_rings - 1][1] + base
    for radius, z, exp in outer[offset_rings:]:
        # Ранние кольца плавного petaloid-перехода могут лежать ниже base.
        # Внутренняя поверхность продолжает дно горизонтально, а не удаляет
        # кольца: нумерация оболочек и их неразрывность сохраняются.
        inner.append((max(0.2, radius - wall), max(z, floor_side_z), exp))
    if len(inner) != len(outer):
        raise GeometryError("Не удалось согласовать внутренний профиль сосуда: уменьшите base.")
    return outer_center, outer, inner_center, inner, petaloid


def _vessel_body(a, vessel: str) -> tuple[mf.Manifold, dict]:
    is_jar = vessel == "jar"
    height = float(a.num("height", 110.0 if is_jar else 220.0, minv=30.0, maxv=1000.0))
    diameter = float(a.num("diameter", 80.0 if is_jar else 70.0, minv=20.0, maxv=500.0))
    neck_d = float(a.num("neck_d", 58.0 if is_jar else 28.0, minv=10.0, maxv=250.0))
    wall = float(a.num("wall", 1.4 if is_jar else 1.0, minv=0.35, maxv=8.0))
    base = float(a.num("base", 3.0 if is_jar else 3.5, minv=0.8, maxv=20.0))
    form = a.text("form", "округлая", choices=["цилиндр", "округлая", "квадратная"])
    if is_jar:
        style = a.text("style", "классическая",
                       choices=["классическая", "коническая", "амфора"])
    else:
        style = a.text("style", "универсальная",
                       choices=["универсальная", "винная", "бургундская", "пивная", "спортивная"])
    # kind — только материал бутылки. Он не меняет ни силуэт, ни значения
    # геометрических параметров по умолчанию, ни доступность petaloid-дна.
    kind = "банка" if is_jar else a.text("kind", "стекло", choices=["стекло", "пластик"])
    neck = "короткая" if is_jar else a.text("neck", "длинная", choices=["длинная", "округлая"])
    bottom = a.text("bottom", "углубление", choices=["плоское", "углубление", "ножки"])
    if is_jar and bottom == "ножки":
        raise GeometryError("Лапки относятся к бутылке, а не к банке.")
    feet_count = int(a.num("feet_count", 5, minv=3, maxv=8))
    if neck_d >= diameter * 0.94:
        raise GeometryError("Горлышко должно быть уже корпуса: уменьшите neck_d.")
    if wall * 2.2 >= neck_d:
        raise GeometryError("Стенка закрывает отверстие горлышка: уменьшите wall.")
    segments = int(a.num("segments", 192, minv=64, maxv=384))
    ribs = int(a.num("ribs", 40 if is_jar else 0, minv=0, maxv=80))
    rib_depth = float(a.num("rib_depth", 0.45, minv=0.0, maxv=2.0)) if ribs else 0.0
    if ribs and segments < ribs * 3:
        segments = ribs * 4
    if not is_jar and bottom == "ножки":
        # Целое число одинаковых секторов на каждую долю: силуэт не зависит
        # от случайного сдвига сегментов относительно petaloid-волны.
        sector = feet_count * 4
        segments = max(feet_count * 16, segments // sector * sector)
    outer_center, outer, inner_center, inner, petaloid = _vessel_profiles(
        height, diameter, neck_d, wall, base, form, neck, bottom, vessel,
        style, feet_count)
    petal_height = petaloid["height"] if petaloid else 0.0
    body = _open_vessel_mesh(outer_center, outer, inner_center, inner, segments,
                             ribs, rib_depth,
                             max(4.0, height * 0.045) + petal_height, petaloid)
    thread = a.boolean("thread", True)
    thread_pitch = float(a.num("thread_pitch", 3.0, minv=1.2, maxv=8.0))
    thread_depth = float(a.num("thread_depth", 0.65, minv=0.2, maxv=1.5))
    thread_length = float(a.num("thread_length", 6.0 if is_jar else 7.0,
                                minv=2.0, maxv=18.0))
    if thread:
        ridge = _helix_ridge(neck_d * 0.5, thread_length, thread_pitch,
                             thread_depth, min(thread_pitch * 0.52, 1.5),
                             steps_per_turn=64, inset=thread_depth * 0.75,
                             fade=0.45, fade_top=0.35)
        body = body + ridge.translate((0.0, 0.0, height - thread_length - 1.0))
    if body.status() != mf.Error.NoError or solid_parts(body) != 1:
        raise GeometryError("Корпус сосуда должен остаться одной замкнутой деталью.")
    return body, {
        "height": height, "diameter": diameter, "neck_d": neck_d, "wall": wall,
        "base": base, "form": form, "style": style, "kind": kind,
        "neck": neck, "bottom": bottom, "feet_count": feet_count,
        "ribs": ribs, "rib_depth": rib_depth, "segments": segments, "thread": thread,
        "thread_pitch": thread_pitch, "thread_depth": thread_depth,
        "thread_length": thread_length,
    }


def _closure_cap(neck_d: float, thread_depth: float, height: float, ribs: int,
                 kind: str, segments: int, thread_pitch: float) -> mf.Manifold:
    """Отдельная навинчиваемая крышка с полостью и внутренней канавкой."""
    inner_r = neck_d * 0.5 + thread_depth + 0.28
    wall = 1.5 if kind == "пластик" else 1.0
    outer_r = inner_r + wall
    top = 1.4 if kind == "пластик" else 0.9
    body = _closed_radial(outer_r, height, max(96, segments), ribs,
                          0.35 if ribs else 0.0)
    bore = mf.Manifold.cylinder(height - top + 0.5, inner_r, inner_r,
                                max(64, segments // 2)).translate((0.0, 0.0, -0.25))
    body = body - bore
    groove = _helix_ridge(inner_r, min(height - top - 0.8, 6.0), thread_pitch,
                          0.55, min(1.3, thread_pitch * 0.48), steps_per_turn=56,
                          inset=0.12, fade=0.25, fade_top=0.25)
    body = body - groove.translate((0.0, 0.0, 0.45))
    if kind == "банка":
        # Неглубокая штампованная панель на верхней плоскости twist-off.
        recess = mf.Manifold.cylinder(0.32, max(1.0, outer_r - 2.2),
                                      max(1.0, outer_r - 2.2), 96)
        body = body - recess.translate((0.0, 0.0, height - 0.32))
    if body.status() != mf.Error.NoError or solid_parts(body) != 1:
        raise GeometryError("Крышка должна быть одной деталью с открытым низом.")
    return body


def _cork(neck_inner_d: float, height: float, segments: int) -> mf.Manifold:
    r = neck_inner_d * 0.5 - 0.12
    if r <= 0.5:
        raise GeometryError("Для пробки не осталось отверстия в горлышке.")
    profile = [(0.0, 0.0), (r * 0.82, 0.0), (r * 0.88, 0.8),
               (r, height - 1.0), (r * 0.88, height), (0.0, height)]
    return mf.Manifold.revolve(mf.CrossSection([profile]), segments)


def _vessel_finish(a, root, kind: str) -> None:
    """Применяет стекло/пластик, не затирая явный material-пресет DSL."""
    if a.has("material"):
        # material, transmission, rough и density уже обработаны Args.style().
        # Ветка kind здесь ничего не должна перезаписывать.
        return
    is_glass = kind in ("стекло", "банка")
    root.transmission = float(a.num("transmission", 0.82 if is_glass else 0.25,
                                    minv=0.0, maxv=1.0))
    if not a.has("rough"):
        root.rough = 0.16 if is_glass else 0.30
    if not a.has("density"):
        root.density = 2.5 if is_glass else 1.05


@op("jar", aliases=("банка", "jar_glass"), category="Примитивы",
    summary="Стеклянная банка с классическим, коническим или амфорным силуэтом, "
            "настоящей полостью, округлой винтовой резьбой, углублением и "
            "круговым рифлением дна. Крышка выбирается отдельно.",
    example="банка = jar style=амфора form=округлая diameter=80 height=110 ribs=40 cap=да",
    params={
        "height": "высота корпуса, мм (110)", "diameter": "диаметр корпуса, мм (80)",
        "neck_d": "наружный диаметр горлышка, мм (58)",
        "form": "сечение: цилиндр, округлая или квадратная (округлая)",
        "style": "силуэт: классическая, коническая или амфора (классическая)",
        "wall": "толщина стенки, мм (1.4)", "base": "толщина дна, мм (3)",
        "bottom": "плоское или углубление (углубление)",
        "ribs": "число вертикальных рёбер по дну 0…80 (40)",
        "rib_depth": "глубина рифления дна, мм (0.45)",
        "thread": "настоящая винтовая резьба: да/нет (да)",
        "thread_pitch": "шаг резьбы, мм (3)", "thread_depth": "высота витка, мм (0.65)",
        "thread_length": "длина резьбовой зоны, мм (6)",
        "cap": "отдельная крышка: да/нет (нет)",
        "segments": "сегментов по окружности 64…384 (192)",
        "at": "положение [x,y,z], низ на z=0", "center": "центрировать по высоте",
        "color": "цвет стекла", "cap_color": "цвет крышки"})
def jar(a, name):
    body, p = _vessel_body(a, "jar")
    cap = a.boolean("cap", False)
    parts = [("", body, "color", "jar")]
    if cap:
        cap_h = 8.0
        lid = (_closure_cap(p["neck_d"], p["thread_depth"], cap_h, 8, "банка",
                            p["segments"], p["thread_pitch"]) if p["thread"] else
               _plain_cap(p["neck_d"], cap_h, 8, "банка", p["segments"]))
        lid = lid.translate((0.0, 0.0, p["height"] - 3.5))
        parts.append((".lid", lid, "cap_color", "jar_lid"))
    root = _emit(a, name, parts, dict(p, cap=cap))
    _vessel_finish(a, root, "банка")
    root.notes.append("открытая полость; центральный punt и рифление дна — геометрия")
    if cap and not a.has("material"):
        lid_obj = a.scene.objects[f"{name}.lid"]
        if not a.has("metal"):
            lid_obj.metal = 0.72
        if not a.has("rough"):
            lid_obj.rough = 0.28
    return root


@op("bottle", aliases=("бутылка", "bottle_glass", "bottle_plastic"), category="Примитивы",
    summary="Бутылка с пятью самостоятельными силуэтами: универсальная, винная, "
            "бургундская, пивная или спортивная. Petaloid-лапки литые и непрерывные; "
            "материал не ограничивает геометрию. Резьба, крышка и пробка настраиваются.",
    example="бутылка = bottle style=спортивная kind=пластик form=округлая neck=округлая bottom=ножки closure=крышка",
    params={
        "kind": "отделка: стекло или пластик; не меняет геометрию (стекло)",
        "material": "необязательный общий пресет DSL; также не меняет геометрию",
        "height": "высота корпуса, мм (220)", "diameter": "диаметр корпуса, мм (70)",
        "neck_d": "наружный диаметр горлышка, мм (28)",
        "form": "сечение: цилиндр, округлая или квадратная (округлая)",
        "style": "силуэт: универсальная, винная, бургундская, пивная или спортивная",
        "neck": "длинная или округлая (длинная)",
        "bottom": "плоское, углубление или литые ножки (углубление)",
        "feet_count": "число petaloid-лепестков 3…8 (5)",
        "wall": "толщина стенки, мм (1)", "base": "толщина дна, мм (3.5)",
        "ribs": "рёбра по нижнему пояску 0…80 (0)",
        "rib_depth": "глубина рифления, мм (0.45)",
        "thread": "винтовое горло: да/нет; для пробки обычно нет (да)",
        "thread_pitch": "шаг резьбы, мм (3)", "thread_depth": "высота витка, мм (0.65)",
        "thread_length": "длина резьбовой зоны, мм (7)",
        "closure": "нет, крышка или пробка (нет)",
        "segments": "сегментов по окружности 64…384 (192)",
        "at": "положение [x,y,z], низ на z=0", "center": "центрировать по высоте",
        "color": "цвет материала", "cap_color": "цвет крышки",
        "transmission": "прозрачность корпуса 0…1 (стекло .82, пластик .25)"})
def bottle(a, name):
    body, p = _vessel_body(a, "bottle")
    closure = a.text("closure", "нет", choices=["нет", "крышка", "пробка"])
    if closure == "пробка" and p["thread"]:
        # Явный closure выбирает пробочное горло без не нужной резьбы.  Если
        # пользователь отдельно задал thread=да, сохраняем его намеренный выбор.
        if not a.has("thread"):
            body, p = _vessel_body_without_thread(a)
    parts = [("", body, "color", "bottle")]
    if closure == "крышка":
        cap_h = 13.0
        cap = (_closure_cap(p["neck_d"], p["thread_depth"], cap_h, 36, "пластик",
                            p["segments"], p["thread_pitch"]) if p["thread"] else
               _plain_cap(p["neck_d"], cap_h, 36, "пластик", p["segments"]))
        cap = cap.translate((0.0, 0.0, p["height"] - 4.0))
        parts.append((".cap", cap, "cap_color", "bottle_cap"))
    elif closure == "пробка":
        cork_h = 25.0
        cork = _cork(p["neck_d"] - 2.0 * p["wall"], cork_h, p["segments"])
        cork = cork.translate((0.0, 0.0, p["height"] - cork_h + 8.0))
        parts.append((".cork", cork, "cap_color", "cork"))
    root = _emit(a, name, parts, dict(p, closure=closure))
    _vessel_finish(a, root, p["kind"])
    root.notes.append("реальная полость и цельное дно; closure — отдельная выбираемая деталь")
    if closure == "крышка":
        cap_obj = a.scene.objects[f"{name}.cap"]
        if not a.has("material") and not a.has("rough"):
            cap_obj.rough = 0.36
    elif closure == "пробка":
        cork_obj = a.scene.objects[f"{name}.cork"]
        cork_obj.rough = 0.88
        cork_obj.density = 0.24
    return root


def _vessel_body_without_thread(a) -> tuple[mf.Manifold, dict]:
    """Внутренняя ветка closure=пробка без изменения пользовательского Args."""
    class _NoThreadArgs:
        def __init__(self, source):
            self.source = source
        def num(self, key, *args, **kwargs):
            return self.source.num(key, *args, **kwargs)
        def text(self, key, *args, **kwargs):
            return self.source.text(key, *args, **kwargs)
        def boolean(self, key, default=False):
            return False if key == "thread" else self.source.boolean(key, default)
    return _vessel_body(_NoThreadArgs(a), "bottle")


@op("lid", aliases=("крышка", "lid_pot", "lid_jar", "lid_bottle"), category="Примитивы",
    summary="Отдельная крышка трёх видов: баночная twist-off, рифлёная "
            "пластиковая бутылочная или кастрюльная. У кастрюльной ручка, "
            "крепёж, металлический обод и паровое отверстие выбираются отдельно.",
    example="крышка = lid kind=кастрюля material=стекло diameter=180 handle=скоба vent=да",
    params={
        "kind": "банка, бутылка или кастрюля (банка)",
        "diameter": "посадочный диаметр, мм (58; кастрюля 180)",
        "height": "высота баночной/бутылочной крышки, мм (8/13)",
        "neck_d": "диаметр горлышка для посадки; 0 — использовать diameter",
        "ribs": "число внешних рёбер; 0 — гладкая крышка (по виду)",
        "thread": "внутренняя винтовая канавка: да/нет (да)",
        "thread_pitch": "шаг внутренней резьбы, мм (3)",
        "material": "для кастрюли: металл или стекло (металл)",
        "handle": "для кастрюли: кнопка, скоба, дуга или нет (кнопка)",
        "vent": "настоящее паровое отверстие и отдельная втулка: да/нет (да)",
        "segments": "сегментов по окружности 64…384 (160)",
        "at": "положение [x,y,z], низ на z=0", "center": "центрировать по высоте",
        "color": "цвет корпуса крышки", "handle_color": "цвет ручки",
        "metal_color": "цвет обода, втулки и крепежа"})
def lid(a, name):
    kind = a.text("kind", "банка", choices=["банка", "бутылка", "кастрюля"])
    default_d = 180.0 if kind == "кастрюля" else (58.0 if kind == "банка" else 28.0)
    diameter = float(a.num("diameter", default_d, minv=16.0, maxv=500.0))
    neck_d = float(a.num("neck_d", diameter, minv=10.0, maxv=500.0))
    pitch = float(a.num("thread_pitch", 3.0, minv=1.2, maxv=8.0))
    segments = int(a.num("segments", 160, minv=64, maxv=384))
    if kind in ("банка", "бутылка"):
        h_default = 8.0 if kind == "банка" else 13.0
        height = float(a.num("height", h_default, minv=4.0, maxv=40.0))
        ribs_default = 8 if kind == "банка" else 36
        ribs = int(a.num("ribs", ribs_default, minv=0, maxv=80))
        thread = a.boolean("thread", True)
        cap = _closure_cap(neck_d, 0.65, height, ribs,
                           "банка" if kind == "банка" else "пластик",
                           segments, pitch) if thread else _plain_cap(neck_d, height, ribs, kind, segments)
        root = _emit(a, name, [("", cap, "color", "lid")], {
            "kind": kind, "diameter": diameter, "neck_d": neck_d, "height": height,
            "ribs": ribs, "thread": thread, "thread_pitch": pitch, "segments": segments})
        if not a.has("material"):
            if kind == "банка":
                if not a.has("metal"):
                    root.metal = 0.72
                if not a.has("rough"):
                    root.rough = 0.28
            elif not a.has("rough"):
                root.rough = 0.36
        return root

    material = a.text("material", "металл", choices=["металл", "стекло"])
    handle = a.text("handle", "кнопка", choices=["кнопка", "скоба", "дуга", "нет"])
    vent = a.boolean("vent", True)
    radius = diameter * 0.5
    thickness = 3.2 if material == "стекло" else 1.1
    dome = max(3.0, diameter * 0.035)
    # Замкнутый профиль листового/стеклянного диска с медленным куполом.
    profile = [(0.0, dome - thickness), (radius * 0.35, dome - thickness),
               (radius * 0.78, dome * 0.55 - thickness * 0.4),
               (radius - 1.5, 0.0), (radius + 1.2, 0.8),
               (radius + 1.2, 2.0), (radius - 1.0, 2.8),
               (radius * 0.78, dome * 0.55 + thickness * 0.6),
               (radius * 0.35, dome), (0.0, dome)]
    body = mf.Manifold.revolve(mf.CrossSection([profile]), segments)
    parts = [("", body, "color", "pot_lid")]
    if material == "стекло":
        # Единый обжимной профиль: наружная полоса соединяет верхнюю и
        # нижнюю закраины, а посадочный канал повторяет кромку без пересечения.
        rim_profile = [(radius - 1.5, -0.4), (radius + 2.4, -0.4),
                       (radius + 2.4, 3.2), (radius - 1.0, 3.2),
                       (radius - 1.0, 2.8), (radius + 1.25, 2.8),
                       (radius + 1.25, 0.0), (radius - 1.5, 0.0),
                       (radius - 1.5, -0.4)]
        rim = mf.Manifold.revolve(mf.CrossSection([rim_profile]), segments)
        parts.append((".rim", rim, "metal_color", "lid_rim"))
    top_z = dome
    if handle == "кнопка":
        stem = mf.Manifold.cylinder(9.0, 4.0, 4.0, 48).translate((0.0, 0.0, top_z + 0.8))
        knob = mf.Manifold.sphere(1.0, 48).scale((14.0, 14.0, 5.0)).translate(
            (0.0, 0.0, top_z + 12.0))
        base = mf.Manifold.cylinder(1.2, 9.0, 9.0, 64).translate((0.0, 0.0, top_z))
        handle_solid = base + stem + knob
        body = body - mf.Manifold.cylinder(thickness + 10.0, 2.15, 2.15, 36).translate(
            (0.0, 0.0, top_z - thickness - 3.0))
        handle_solid = handle_solid - mf.Manifold.cylinder(3.2, 2.05, 2.05, 36).translate(
            (0.0, 0.0, top_z - 0.1))
        handle_solid = handle_solid - body
        parts.append((".handle", handle_solid, "handle_color", "lid_handle"))
        screw = mf.Manifold.cylinder(thickness + 3.0, 2.0, 2.0, 32).translate(
            (0.0, 0.0, top_z - thickness - 1.0))
        parts.append((".fastener_1", screw, "metal_color", "lid_fastener"))
    elif handle in ("скоба", "дуга"):
        span = diameter * (0.40 if handle == "скоба" else 0.48)
        rise = 20.0 if handle == "скоба" else 18.0
        if handle == "скоба":
            # Прямоугольная отогнутая скоба, как на металлической крышке.
            path = [(-span * 0.5, 0.0, top_z + 1.0),
                    (-span * 0.5, 0.0, top_z + rise),
                    (-span * 0.5 + 4.0, 0.0, top_z + rise + 3.0),
                    (span * 0.5 - 4.0, 0.0, top_z + rise + 3.0),
                    (span * 0.5, 0.0, top_z + rise),
                    (span * 0.5, 0.0, top_z + 1.0)]
            half_width = 5.0
        else:
            # Широкая плоская дуга, а не круглый пруток.
            path = []
            for i in range(33):
                t = math.pi * i / 32.0
                path.append((-span * 0.5 * math.cos(t), 0.0,
                             top_z + 4.0 + rise * math.sin(t)))
            half_width = 6.0
        profile2 = np.array([(-0.9, -half_width), (0.9, -half_width),
                             (0.9, half_width), (-0.9, half_width)])
        grip = sweep_solid(np.asarray(path), profile2, up_hint=(0.0, 1.0, 0.0),
                           what="ручка крышки")
        feet = []
        for x in (-span * 0.5, span * 0.5):
            feet.append(mf.Manifold.cylinder(4.2, 5.0, 5.0, 40).translate(
                (x, 0.0, top_z)))
            body = body - mf.Manifold.cylinder(thickness + 10.0, 1.95, 1.95, 32).translate(
                (x, 0.0, top_z - thickness - 3.0))
        handle_solid = grip + mf.Manifold.compose(feet)
        for x in (-span * 0.5, span * 0.5):
            handle_solid = handle_solid - mf.Manifold.cylinder(2.0, 1.9, 1.9, 30).translate(
                (x, 0.0, top_z - 0.1))
        handle_solid = handle_solid - body
        parts.append((".handle", handle_solid, "handle_color", "lid_handle"))
        for i, x in enumerate((-span * 0.5, span * 0.5), 1):
            screw = mf.Manifold.cylinder(thickness + 2.0, 1.8, 1.8, 28).translate(
                (x, 0.0, top_z - thickness - 0.8))
            parts.append((f".fastener_{i}", screw, "metal_color", "lid_fastener"))
    parts[0] = ("", body, "color", "pot_lid")
    if vent:
        vx, vz = radius * 0.52, dome * 0.72
        hole = mf.Manifold.cylinder(12.0, 2.0, 2.0, 40).translate((vx, 0.0, -3.0))
        # Перестроим корень после выреза, сохранив его как первый элемент.
        body = body - hole
        parts[0] = ("", body, "color", "pot_lid")
        eyelet_profile = [(1.9, -0.4), (3.2, -0.4), (3.5, 0.2),
                          (3.2, 1.0), (1.9, 1.0), (1.9, -0.4)]
        eyelet = mf.Manifold.revolve(mf.CrossSection([eyelet_profile]), 56).translate(
            (vx, 0.0, vz))
        eyelet = eyelet - body
        parts.append((".vent", eyelet, "metal_color", "lid_vent"))
    # Здесь material — вид кастрюльной крышки, а не общий material-preset DSL.
    # Убираем его только из копии Args перед make_solid, сохраняя значение в meta.
    emit_a = a
    if "material" in a.kwargs:
        emit_a = copy.copy(a)
        emit_a.kwargs = {key: value for key, value in a.kwargs.items() if key != "material"}
    min_z = min(float(part[1].bounding_box()[2]) for part in parts)
    if min_z < -1e-8:
        parts = [(suffix, solid.translate((0.0, 0.0, -min_z)), color_key, kind_name)
                 for suffix, solid, color_key, kind_name in parts]
    root = _emit(emit_a, name, parts, {
        "kind": kind, "diameter": diameter, "material": material, "handle": handle,
        "vent": vent, "segments": segments, "thread": False, "ribs": 0})
    if material == "стекло":
        root.transmission, root.rough, root.density = 0.9, 0.12, 2.5
    else:
        root.metal, root.rough = 0.8, 0.24
    for obj in a.scene.objects.values():
        if obj.meta.get("assembly_root") != name:
            continue
        if obj.kind in ("lid_rim", "lid_fastener", "lid_vent") or (
                material == "металл" and obj.kind == "lid_handle"):
            obj.metal, obj.rough = 0.82, 0.24
    return root


def _plain_cap(neck_d: float, height: float, ribs: int, kind: str, segments: int) -> mf.Manifold:
    inner_r = neck_d * 0.5 + 0.35
    outer_r = inner_r + (1.0 if kind == "банка" else 1.5)
    top = 0.9 if kind == "банка" else 1.4
    body = _closed_radial(outer_r, height, max(96, segments), ribs, 0.35 if ribs else 0.0)
    bore = mf.Manifold.cylinder(height - top + 0.5, inner_r, inner_r,
                                max(64, segments // 2)).translate((0.0, 0.0, -0.25))
    return body - bore
