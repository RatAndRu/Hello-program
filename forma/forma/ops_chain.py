"""Цепи: готовое звено-кольцо и соединение готовых деталей цепью.

Цепь — редкая вещь, которую не собрать из примитивов «на глаз»: звенья
должны быть зацеплены, а не нанизаны, и повёрнуты друг к другу на 90°.
Поэтому здесь два инструмента:

* `цепь` — сразу цепочка из N звеньев вдоль направления: серьга, поводок,
  стропа, цепь на ворота;
* `соединить` — цепь между двумя **готовыми** деталями: находит, где они
  ближе всего друг к другу (или берёт from/to), вешает цепь с провисом и
  подбирает число звеньев по расстоянию. Это ответ на «свяжи две вещи»,
  когда склейка не нужна.

    цепь links=8 size=26 wire=4 at=[0,0,60] dir=[1,0,0]
    соединить [крюк, ведро] size=16 wire=2.4 sag=0.18
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile, ensure_ccw, solid_parts, sweep_solid
from .ops import make_solid, op
from .ops_fittings import _assembly


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        raise GeometryError("Нулевое направление.",
                            hint="Задайте другое направление (dir).")
    return v / n


def _link(length: float, width: float, wire: float, seg: int = 18,
          minor: int = 12) -> mf.Manifold:
    """Звено цепи — вытянутое кольцо (стадион), а не круг.

    Круглые кольца не сцепляются: у них сосед просто проходит рядом, а не
    сквозь отверстие. У вытянутого звена соседнее звено, повёрнутое на 90°,
    проходит как раз через его проушину — как у настоящей цепи.
    """
    lc = max(length - wire, wire * 1.2)          # осевая линия по длине
    wc = max(width - wire, wire * 0.9)           # осевая линия по ширине
    half = max(lc - wc, 0.01) * 0.5
    rad = wc * 0.5
    pts = []
    steps = max(8, seg // 2)
    for i in range(steps + 1):                    # правый полукруг
        a = -math.pi / 2 + math.pi * i / steps
        pts.append((half + rad * math.cos(a), rad * math.sin(a)))
    for i in range(steps + 1):                    # левый полукруг
        a = math.pi / 2 + math.pi * i / steps
        pts.append((-half + rad * math.cos(a), rad * math.sin(a)))
    path = np.asarray([[x, y, 0.0] for x, y in pts[:-1]], dtype=np.float64)
    prof = circle_profile(max(wire * 0.5, 0.1), minor)
    return sweep_solid(path, prof, closed_path=True, what="звена",
                       round_caps=0.0)


def _placed(link: mf.Manifold, center, x_axis, z_axis) -> mf.Manifold:
    """Ставит звено так, что его плоскость содержит x_axis, а ось — z_axis."""
    x = _unit(x_axis)
    z = np.asarray(z_axis, dtype=np.float64).reshape(3)
    z = z - x * float(np.dot(z, x))
    if float(np.linalg.norm(z)) < 1e-7:
        z = np.cross(x, np.array([0.0, 0.0, 1.0]))
        if float(np.linalg.norm(z)) < 1e-7:
            z = np.cross(x, np.array([1.0, 0.0, 0.0]))
    z = _unit(z)
    y = np.cross(z, x)
    matrix = np.hstack([np.stack([x, y, z], axis=1),
                        np.asarray(center, dtype=np.float64).reshape(3, 1)])
    return link.transform(np.ascontiguousarray(matrix, dtype=np.float64))


def _chain(points: np.ndarray, size: float, width: float, wire: float,
           pitch: float | None, ref_up) -> mf.Manifold:
    """Звенья вдоль ломаной: шаг по длине дуги, поворот на 90° друг к другу."""
    pitch = float(pitch) if pitch else (size - wire) * 0.62
    pitch = max(pitch, wire * 2.0)
    seg = points[1:] - points[:-1]
    seg_len = np.linalg.norm(seg, axis=1)
    total = float(seg_len.sum())
    if total < 1e-6:
        raise GeometryError("Длина цепи нулевая.", hint="Разведите точки.")
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    count = int(max(2, min(400, math.floor(total / pitch) + 1)))
    base_link = _link(size, width, wire, seg=18,
                      minor=max(8, int(18 * wire / max(size, 1e-3)) + 7))

    ref = np.asarray(ref_up, dtype=np.float64).reshape(3)
    links = []
    for i in range(count):
        s = i * pitch
        j = int(np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(seg) - 1))
        t = (s - cum[j]) / max(seg_len[j], 1e-9)
        t = float(np.clip(t, 0.0, 1.0))
        center = points[j] + seg[j] * t
        tangent = seg[j] / max(seg_len[j], 1e-9)
        axis = ref - tangent * float(np.dot(ref, tangent))
        if float(np.linalg.norm(axis)) < 0.2 * float(np.linalg.norm(ref)):
            axis = np.cross(tangent, np.array([1.0, 0.0, 0.0]))
        axis = _unit(axis)
        # соседние звенья повёрнуты на 90°: ось вращается вокруг касательной
        ang = (math.pi / 2.0) * i
        c, s_ = math.cos(ang), math.sin(ang)
        axis = _unit(axis * c + np.cross(tangent, axis) * s_)
        links.append(_placed(base_link, center, tangent, axis))
    return mf.Manifold.batch_boolean(links, mf.OpType.Add)


@op("цепь", aliases=("chain", "цепочка", "звенья", "цепь_звеньев"),
    category="Примитивы",
    summary="Цепь из звеньев: кольца зацеплены друг за друга и повёрнуты на 90°, "
            "поэтому это настоящая цепь, а не ряд колец рядом. Задаются размер "
            "звена, толщина прутка, число звеньев и направление.",
    example="цепь links=8 size=26 wire=4 at=[0,0,80] dir=[1,0,0]\n"
            "подвес = цепь links=14 size=18 wire=3 at=[0,0,120] dir=[0,0,-1]\n"
            "цепь links=6 size=30 wire=5 at=[0,0,40] dir=[1,0,0.4] metal=0.9",
    params={"links": "сколько звеньев (8)",
            "size": "длина звена, мм (24)",
            "width": "ширина звена, мм (0.58·size)",
            "wire": "толщина прутка, мм (3)",
            "pitch": "шаг между звеньями, мм (само: 0.62·size)",
            "at": "начало цепи [x,y,z] (0,0,0)",
            "dir": "направление цепи [x,y,z] (1,0,0)",
            "metal": "металличность 0…1 (0.75)"})
def chain(a, name):
    links = int(a.num("links", 8, minv=1, maxv=400))
    size = float(a.num("size", 24.0, minv=1.0, maxv=2000.0))
    width = float(a.num("width", size * 0.58, minv=size * 0.2, maxv=size))
    wire = float(a.num("wire", 3.0, minv=0.2, maxv=width * 0.5))
    pitch = a.num("pitch", None, minv=0.2)
    at = np.asarray(a.vec("at", 3, default=(0.0, 0.0, 0.0)), dtype=np.float64).reshape(3)
    direction = _unit(a.vec("dir", 3, default=(1.0, 0.0, 0.0)))
    step = float(pitch) if pitch else (size - wire) * 0.62
    points = np.stack([at, at + direction * (step * (links - 1) + size * 0.5)], axis=0)
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(ref, direction))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    solid = _chain(points, size, width, wire, step, ref)
    made = make_solid(a.scene, name, solid, a, kind="chain")
    made.metal = float(a.num("metal", 0.75, minv=0.0, maxv=1.0))
    made.rough = 0.35
    a.scene.log("info", f"цепь: {links} звеньев, {size:g} мм", a.cmd.line)
    return made


def _facing_points(solid_a, solid_b) -> tuple[np.ndarray, np.ndarray]:
    """Ближайшие друг к другу точки габаритов двух деталей."""
    ba = np.array(solid_a.manifold.bounding_box(), dtype=np.float64)
    bb = np.array(solid_b.manifold.bounding_box(), dtype=np.float64)
    ca = np.array([(ba[i] + ba[i + 3]) * 0.5 for i in range(3)])
    cb = np.array([(bb[i] + bb[i + 3]) * 0.5 for i in range(3)])
    ha = np.array([(ba[i + 3] - ba[i]) * 0.5 for i in range(3)])
    hb = np.array([(bb[i + 3] - bb[i]) * 0.5 for i in range(3)])
    d = cb - ca
    n = float(np.linalg.norm(d))
    if n < 1e-9:
        d, n = np.array([0.0, 0.0, 1.0]), 1.0
    d = d / n
    ra = float(np.sum(np.abs(d) * ha))
    rb = float(np.sum(np.abs(d) * hb))
    return ca + d * ra, cb - d * rb


@op("соединить", aliases=("chain_between", "связать_цепью", "прицепить",
                          "соединить_цепью", "подвесить"),
    category="Сборка",
    summary="Соединяет две готовые детали цепью: берёт ближайшие точки (или "
            "заданные from и to), вешает цепь с провисом, число звеньев "
            "подбирает по расстоянию. Когда склейка не нужна — это честное "
            "соединение: деталь висит на цепи.",
    example="крюк = torus major=20 minor=4 at=[0,0,200]\n"
            "ведро = cylinder radius=34 height=60 at=[0,0,40]\n"
            "соединить [крюк, ведро] size=16 wire=2.4 sag=0.15\n"
            "плита = box size=[120,60,10]\n"
            "лампа = sphere radius=20 at=[0,0,-80]\n"
            "соединить [плита, лампа] size=10 wire=1.6 links=9",
    params={"objects": "две детали [a, b]",
            "size": "длина звена, мм (18)",
            "width": "ширина звена, мм (0.58·size)",
            "wire": "толщина прутка, мм (2.6)",
            "links": "сколько звеньев (0 — подобрать по длине)",
            "sag": "провис 0…1 от длины (0.15)",
            "from": "начало цепи [x,y,z] (ближайшая точка первой детали)",
            "to": "конец цепи [x,y,z] (ближайшая точка второй)",
            "metal": "металличность 0…1 (0.75)"},
    positional=["objects"])
def chain_between(a, name):
    solids = a.solids()
    if len(solids) != 2:
        raise GeometryError("соединить ждёт ровно две детали.",
                            hint="Формат: connect = соединить [крюк, ведро] …")
    size = float(a.num("size", 18.0, minv=1.0, maxv=400.0))
    width = float(a.num("width", size * 0.58, minv=size * 0.2, maxv=size))
    wire = float(a.num("wire", 2.6, minv=0.2, maxv=width * 0.5))
    sag = float(a.num("sag", 0.15, minv=-1.0, maxv=1.0))
    links = int(a.num("links", 0, minv=0, maxv=400))
    pa, pb = _facing_points(solids[0], solids[1])
    from_p = a.vec("from", 3, default=None)
    to_p = a.vec("to", 3, default=None)
    if from_p is not None:
        pa = np.asarray(from_p, dtype=np.float64).reshape(3)
    if to_p is not None:
        pb = np.asarray(to_p, dtype=np.float64).reshape(3)

    # точка подвеса: чуть выше середины, провис — вниз
    mid = (pa + pb) * 0.5
    length = float(np.linalg.norm(pb - pa))
    mid = mid - np.array([0.0, 0.0, sag * max(length, 1.0) * 0.5])
    ts = np.linspace(0.0, 1.0, 9)
    path = ((1.0 - ts) ** 2)[:, None] * pa[None, :] \
        + (2.0 * (1.0 - ts) * ts)[:, None] * mid[None, :] \
        + (ts ** 2)[:, None] * pb[None, :]

    pitch = None
    if links > 1:
        pitch = max(float(np.linalg.norm(path[-1] - path[0])) / (links - 0.5),
                    wire * 2.0)
    ref = np.array([0.0, 0.0, 1.0])
    solid = _chain(path, size, width, wire, pitch, ref)
    made = make_solid(a.scene, name, solid, a, kind="chain")
    made.metal = float(a.num("metal", 0.75, minv=0.0, maxv=1.0))
    made.rough = 0.35
    a.scene.log("info",
                f"соединить: цепь {length:.0f} мм между «{solids[0].name}» "
                f"и «{solids[1].name}»", a.cmd.line)
    return made


def _bike_cylinder_y(radius: float, length: float, x: float, y: float, z: float,
                     segments: int) -> mf.Manifold:
    return mf.Manifold.cylinder(length, radius, radius, segments).rotate(
        (90.0, 0.0, 0.0)).translate((x, y + length * 0.5, z))


def _bike_plate(pitch: float, height: float, thickness: float, hole_r: float,
                y: float, z: float, segments: int) -> mf.Manifold:
    """Фигурная пластина с вогнутой талией и двумя настоящими отверстиями."""
    half = pitch * 0.5
    radius = height * 0.5
    waist = height * 0.29
    curve_steps = max(10, segments // 2)
    arc_steps = max(8, segments // 2)
    points = []
    for i in range(curve_steps + 1):
        x = -half + pitch * i / curve_steps
        u = abs(x / half)
        points.append((x, waist + (radius - waist) * u * u))
    for i in range(1, arc_steps + 1):
        angle = math.pi * 0.5 - math.pi * i / arc_steps
        points.append((half + radius * math.cos(angle), radius * math.sin(angle)))
    for i in range(1, curve_steps + 1):
        x = half - pitch * i / curve_steps
        u = abs(x / half)
        points.append((x, -waist - (radius - waist) * u * u))
    for i in range(1, arc_steps):
        angle = -math.pi * 0.5 - math.pi * i / arc_steps
        points.append((-half + radius * math.cos(angle), radius * math.sin(angle)))
    cross = mf.CrossSection([np.asarray(ensure_ccw(points), dtype=float)])
    plate = cross.extrude(thickness).rotate((90.0, 0.0, 0.0)).translate(
        (0.0, y + thickness * 0.5, z))
    for x in (-half, half):
        tool = _bike_cylinder_y(hole_r, thickness + 1.0, x, y, z, segments * 2)
        plate = plate - tool
    return plate


def _bike_tube(outer_r: float, inner_r: float, length: float, x: float, z: float,
               segments: int) -> mf.Manifold:
    outer = _bike_cylinder_y(outer_r, length, x, 0.0, z, segments * 2)
    inner = _bike_cylinder_y(inner_r, length + 1.0, x, 0.0, z, segments * 2)
    return outer - inner


@op("bicycle_chain", aliases=("велоцепь", "велосипедная_цепь", "bike_chain"),
    category="Примитивы",
    summary="Прямая велосипедная цепь из чередующихся внутренних и внешних "
            "фигурных пластин. Ролики, втулки и пины с проушинами являются "
            "настоящими отдельными деталями; каждая пластина выбирается.",
    example="цепь = bicycle_chain links=12 pitch=12.7 width=10.2",
    params={
        "links": "число роликов/шагов 3…64 (12)",
        "pitch": "шаг цепи, мм (12.7; стандарт 1/2 дюйма)",
        "roller_d": "наружный диаметр ролика, мм (7.7)",
        "pin_d": "диаметр пина, мм (3.3)",
        "width": "ширина по внешним пластинам, мм (10.2)",
        "plate_height": "высота фигурной пластины, мм (8)",
        "plate_thickness": "толщина внешней пластины, мм (1.2)",
        "clearance": "ходовой зазор ролика/пластин, мм (0.12)",
        "segments": "сегментов дуг 12…48 (24)",
        "at": "положение [x,y,z], низ на z=0", "center": "центрировать всю цепь",
        "color": "общий цвет", "plate_color": "цвет пластин",
        "roller_color": "цвет роликов", "bushing_color": "цвет втулок",
        "pin_color": "цвет пинов"})
def bicycle_chain(a, name):
    links = int(a.int("links", 12, minv=3, maxv=64) or 12)
    pitch = float(a.num("pitch", 12.7, minv=6.0, maxv=40.0))
    roller_d = float(a.num("roller_d", 7.7, minv=3.0, maxv=20.0))
    pin_d = float(a.num("pin_d", 3.3, minv=1.2, maxv=8.0))
    width = float(a.num("width", 10.2, minv=5.0, maxv=30.0))
    plate_h = float(a.num("plate_height", 8.0, minv=4.0, maxv=20.0))
    outer_t = float(a.num("plate_thickness", 1.2, minv=0.45, maxv=3.0))
    clearance = float(a.num("clearance", 0.12, minv=0.03, maxv=0.5))
    segments = int(a.int("segments", 24, minv=12, maxv=48) or 24)
    inner_t = outer_t * 0.83
    if plate_h < roller_d * 0.92:
        raise GeometryError("bicycle_chain: пластина слишком низкая для ролика.")
    if pitch < plate_h * 1.25:
        raise GeometryError("bicycle_chain: шаг слишком мал для фигурных пластин.")
    if pin_d >= roller_d * 0.62:
        raise GeometryError("bicycle_chain: пин не оставляет стенки ролика и втулки.")
    outer_y = width * 0.5 - outer_t * 0.5
    inner_y = width * 0.5 - outer_t - clearance - inner_t * 0.5
    roller_length = 2.0 * (inner_y - inner_t * 0.5 - clearance)
    if roller_length <= 1.0 or inner_y <= inner_t:
        raise GeometryError("bicycle_chain: width слишком мала для пластин и ролика.")
    pin_r = pin_d * 0.5
    bushing_r = roller_d * 0.34
    bushing_inner = pin_r + clearance * 0.55
    roller_inner = bushing_r + clearance * 0.65
    if roller_inner >= roller_d * 0.5 - 0.25:
        raise GeometryError("bicycle_chain: стенка ролика стала слишком тонкой.")
    z = plate_h * 0.5
    x_shift = -(links - 1) * pitch * 0.5
    parts = []
    # Первый объект получает короткое имя root; остальные имеют явные
    # физические suffix'ы и одинаково доступны для picking и экспорта.
    for span in range(links - 1):
        x = x_shift + (span + 0.5) * pitch
        outer = span % 2 == 0
        thickness = outer_t if outer else inner_t
        y = outer_y if outer else inner_y
        hole = pin_r + clearance * 0.35 if outer else bushing_r + clearance * 0.35
        family = "outer" if outer else "inner"
        for side, sign in (("a", -1.0), ("b", 1.0)):
            plate = _bike_plate(pitch, plate_h, thickness, hole, sign * y, z, segments)
            plate = plate.translate((x, 0.0, 0.0))
            suffix = "" if not parts else f".{family}_plate_{span + 1}_{side}"
            parts.append((suffix, plate, "plate_color", "bicycle_plate"))
    for i in range(links):
        x = x_shift + i * pitch
        roller = _bike_tube(roller_d * 0.5, roller_inner, roller_length, x, z, segments)
        bushing_len = 2.0 * (inner_y + inner_t * 0.5) + 0.08
        bushing = _bike_tube(bushing_r, bushing_inner, bushing_len, x, z, segments)
        pin = _bike_cylinder_y(pin_r, width + 0.5, x, 0.0, z, segments * 2)
        # Небольшие клепаные головки — часть того же физического пина.
        for sign in (-1.0, 1.0):
            head = _bike_cylinder_y(pin_r * 1.28, 0.28, x,
                                    sign * (width * 0.5 + 0.14), z, segments * 2)
            pin = pin + head
        parts.extend(((f".roller_{i + 1}", roller, "roller_color", "bicycle_roller"),
                      (f".bushing_{i + 1}", bushing, "bushing_color", "bicycle_bushing"),
                      (f".pin_{i + 1}", pin, "pin_color", "bicycle_pin")))
    full = []
    colors = {"bicycle_plate": "#aeb6bc", "bicycle_roller": "#858f96",
              "bicycle_bushing": "#747e85", "bicycle_pin": "#c1c7cb"}
    for suffix, solid, color_key, kind in parts:
        if solid_parts(solid) != 1:
            raise GeometryError(f"bicycle_chain: {kind} должен быть одной деталью.")
        full.append((suffix, solid, color_key, colors[kind], 0.82, 0.27, kind))
    root = _assembly(a, name, full, {
        "links": links, "pitch": pitch, "roller_d": roller_d, "pin_d": pin_d,
        "width": width, "plate_height": plate_h, "plate_thickness": outer_t,
        "clearance": clearance, "segments": segments}, "bicycle_chain")
    root.notes.append("чередование outer/inner; каждая пластина, ролик, втулка и пин выбираются")
    return root
