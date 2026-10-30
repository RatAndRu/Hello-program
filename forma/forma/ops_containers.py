"""Банки, бутылки и отдельные крышки.

Сосуды строятся одной замкнутой оболочкой с настоящей внутренней полостью,
а не прозрачным цилиндром.  Профили дна задают внешний punt (углубление),
пластиковые лапки сплавляются с корпусом, резьба является винтовым объёмом.
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
    full = []
    for suffix, manifold, color_key, kind in parts:
        metal = 0.72 if kind == "jar_lid" else 0.0
        rough = 0.28 if kind == "jar_lid" else 0.5
        full.append((suffix, manifold, color_key, colors.get(kind, "#c5c9ca"),
                     metal, rough, kind))
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
                      rib_height: float) -> mf.Manifold:
    """Замкнутая стенка открытого сосуда с двумя отдельными донными вершинами.

    Кольца идут от дна ко рту.  Между наружным и внутренним верхними кольцами
    строится кромка; внутренняя оболочка имеет обратную ориентацию.  Никаких
    совпадающих осевых колец и вырожденных треугольников здесь нет.
    """
    if not outer or not inner or len(outer) != len(inner):
        raise GeometryError("Профили сосуда должны содержать одинаковое число колец.")
    verts: list[tuple[float, float, float]] = []

    def add_ring(radius: float, z: float, exponent: float, fluted: bool) -> None:
        for j in range(segments):
            theta = 2.0 * math.pi * j / segments
            rr = radius
            if fluted and ribs > 0 and rib_depth > 0 and rib_height > 0 and z <= rib_height:
                weight = max(0.0, 1.0 - z / rib_height)
                # Впадины уходят внутрь от исходного профиля: гребни не
                # выходят за номинальный габарит корпуса.
                rr += rib_depth * weight * (math.cos(ribs * theta) - 1.0)
            x, y = _xy(rr, theta, exponent)
            verts.append((x, y, z))

    for radius, z, exponent in outer:
        add_ring(radius, z, exponent, True)
    for radius, z, exponent in inner:
        add_ring(radius, z, exponent, False)
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


def _vessel_profiles(height: float, diameter: float, neck_d: float, wall: float,
                     base: float, form: str, neck: str, bottom: str,
                     vessel: str) -> tuple[float, list, float, list, float]:
    """Общий профиль банки/бутылки; возвращает также высоту пластиковых лапок."""
    r, nr = diameter * 0.5, neck_d * 0.5
    exponent = 4.5 if form == "квадратная" else 2.0
    feet_h = height * 0.035 if bottom == "ножки" else 0.0
    punt = min(diameter * 0.13, height * 0.045) if bottom == "углубление" else feet_h * 1.25
    edge_z = feet_h if feet_h else 0.0
    outer: list[tuple[float, float, float]] = [
        (r * 0.25, punt * 0.82 + edge_z * 0.18, exponent),
        (r * 0.56, punt * 0.35 + edge_z * 0.65, exponent),
        (r * 0.86, edge_z, exponent),
        (r, edge_z + max(0.8, base * 0.35), exponent),
    ]
    if vessel == "jar":
        body_top = height * 0.72
        shoulder_end = height * 0.86
        if form == "округлая":
            outer.extend(((r * 0.99, height * 0.20, exponent),
                          (r, height * 0.43, exponent),
                          (r * 0.98, body_top, exponent)))
        else:
            outer.extend(((r, height * 0.22, exponent), (r, body_top, exponent)))
        for i in range(1, 7):
            t = i / 6.0
            s = t * t * (3.0 - 2.0 * t)
            outer.append((r + (nr - r) * s,
                          body_top + (shoulder_end - body_top) * t,
                          exponent + (2.0 - exponent) * s))
        outer.extend(((nr, height - 3.0, 2.0), (nr, height, 2.0)))
    else:
        long_neck = neck == "длинная"
        body_top = height * (0.62 if long_neck else 0.70)
        shoulder_end = height * (0.79 if long_neck else 0.90)
        if form == "округлая":
            outer.extend(((r * 0.98, height * 0.18, exponent),
                          (r, height * 0.40, exponent),
                          (r * 0.99, body_top, exponent)))
        else:
            outer.extend(((r, height * 0.22, exponent), (r, body_top, exponent)))
        for i in range(1, 9):
            t = i / 8.0
            # Округлое горло имеет более плавный, выпуклый переход.
            s = t * t * (3.0 - 2.0 * t) if long_neck else math.sin(t * math.pi * 0.5)
            outer.append((r + (nr - r) * s,
                          body_top + (shoulder_end - body_top) * t,
                          exponent + (2.0 - exponent) * s))
        outer.extend(((nr, height - 2.2, 2.0), (nr, height, 2.0)))

    inner_center = outer_center = punt
    if feet_h:
        outer_center = punt
    inner_center += base
    inner: list[tuple[float, float, float]] = []
    # Внутреннее дно повторяет внешний punt с подъёмом на толщину дна.
    for radius, z, exp in outer[:4]:
        inner.append((max(0.2, radius - wall), z + base, exp))
    floor_side_z = outer[3][1] + base
    for radius, z, exp in outer[4:]:
        if z < floor_side_z - 1e-7:
            continue
        inner.append((max(0.2, radius - wall), z, exp))
    # После четырёх донных колец обязательно должна быть внутренняя стенка.
    if len(inner) != len(outer):
        raise GeometryError("Не удалось согласовать внутренний профиль сосуда.")
    return outer_center, outer, inner_center, inner, feet_h


def _vessel_body(a, vessel: str) -> tuple[mf.Manifold, dict]:
    is_jar = vessel == "jar"
    height = float(a.num("height", 110.0 if is_jar else 220.0, minv=30.0, maxv=1000.0))
    diameter = float(a.num("diameter", 80.0 if is_jar else 70.0, minv=20.0, maxv=500.0))
    neck_d = float(a.num("neck_d", 58.0 if is_jar else 28.0, minv=10.0, maxv=250.0))
    wall = float(a.num("wall", 1.4 if is_jar else 1.0, minv=0.35, maxv=8.0))
    base = float(a.num("base", 3.0 if is_jar else 3.5, minv=0.8, maxv=20.0))
    form = a.text("form", "округлая", choices=["цилиндр", "округлая", "квадратная"])
    kind = "банка" if is_jar else a.text("kind", "стекло", choices=["стекло", "пластик"])
    neck = "короткая" if is_jar else a.text("neck", "длинная", choices=["длинная", "округлая"])
    default_bottom = "углубление" if is_jar or kind == "стекло" else "ножки"
    bottom = a.text("bottom", default_bottom, choices=["плоское", "углубление", "ножки"])
    if is_jar and bottom == "ножки":
        raise GeometryError("Лапки относятся к пластиковой бутылке, а не к банке.")
    if not is_jar and bottom == "ножки" and kind != "пластик":
        raise GeometryError("Пять лапок формируются на пластиковой бутылке: выберите kind=пластик.")
    if neck_d >= diameter * 0.94:
        raise GeometryError("Горлышко должно быть уже корпуса: уменьшите neck_d.")
    if wall * 2.2 >= neck_d:
        raise GeometryError("Стенка закрывает отверстие горлышка: уменьшите wall.")
    segments = int(a.num("segments", 192, minv=64, maxv=384))
    ribs = int(a.num("ribs", 40 if is_jar else 0, minv=0, maxv=80))
    rib_depth = float(a.num("rib_depth", 0.45, minv=0.0, maxv=2.0)) if ribs else 0.0
    if ribs and segments < ribs * 3:
        segments = ribs * 4
    outer_center, outer, inner_center, inner, feet_h = _vessel_profiles(
        height, diameter, neck_d, wall, base, form, neck, bottom, vessel)
    body = _open_vessel_mesh(outer_center, outer, inner_center, inner, segments,
                             ribs, rib_depth, max(4.0, height * 0.045))
    if feet_h:
        # Пять настоящих petaloid-лапок.  Это части литого корпуса, поэтому
        # они сплавляются с ним, а не превращаются в искусственные объекты.
        feet = []
        for i in range(5):
            theta = 2.0 * math.pi * i / 5.0
            rr = diameter * 0.5 * 0.61
            foot = mf.Manifold.sphere(1.0, 40).scale(
                (diameter * 0.145, diameter * 0.115, feet_h * 0.78))
            foot = foot.rotate((0.0, 0.0, math.degrees(theta))).translate(
                (rr * math.cos(theta), rr * math.sin(theta), feet_h * 0.78))
            feet.append(foot)
        body = body + mf.Manifold.compose(feet)
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
        "base": base, "form": form, "kind": kind, "neck": neck, "bottom": bottom,
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


@op("jar", aliases=("банка", "jar_glass"), category="Примитивы",
    summary="Стеклянная банка с выбранной формой корпуса, настоящей полостью, "
            "округлой винтовой резьбой, углублением и круговым рифлением дна. "
            "Необязательная крышка остаётся отдельным выбираемым объектом.",
    example="банка = jar form=округлая diameter=80 height=110 ribs=40 cap=да",
    params={
        "height": "высота корпуса, мм (110)", "diameter": "диаметр корпуса, мм (80)",
        "neck_d": "наружный диаметр горлышка, мм (58)",
        "form": "цилиндр, округлая или квадратная (округлая)",
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
    root.transmission = float(a.num("transmission", 0.82, minv=0.0, maxv=1.0))
    root.rough = 0.16
    root.density = 2.5
    root.notes.append("открытая полость; центральный punt и рифление дна — геометрия")
    if cap:
        lid_obj = a.scene.objects[f"{name}.lid"]
        lid_obj.metal = 0.72
        lid_obj.rough = 0.28
    return root


@op("bottle", aliases=("бутылка", "bottle_glass", "bottle_plastic"), category="Примитивы",
    summary="Стеклянная или пластиковая бутылка: длинное либо округлое горло, "
            "три формы корпуса, punt или пять лапок, настоящая резьба и отдельные "
            "необязательные крышка/пробка.",
    example="бутылка = bottle kind=пластик form=округлая neck=округлая bottom=ножки closure=крышка",
    params={
        "kind": "стекло или пластик (стекло)",
        "height": "высота корпуса, мм (220)", "diameter": "диаметр корпуса, мм (70)",
        "neck_d": "наружный диаметр горлышка, мм (28)",
        "form": "цилиндр, округлая или квадратная (округлая)",
        "neck": "длинная или округлая (длинная)",
        "bottom": "плоское, углубление или ножки (по kind)",
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
    is_glass = p["kind"] == "стекло"
    root.transmission = float(a.num("transmission", 0.82 if is_glass else 0.25,
                                    minv=0.0, maxv=1.0))
    root.rough = 0.16 if is_glass else 0.3
    root.density = 2.5 if is_glass else 1.05
    root.notes.append("реальная полость и дно; closure — отдельная выбираемая деталь")
    if closure == "крышка":
        cap_obj = a.scene.objects[f"{name}.cap"]
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
        if kind == "банка":
            root.metal, root.rough = 0.72, 0.28
        else:
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
