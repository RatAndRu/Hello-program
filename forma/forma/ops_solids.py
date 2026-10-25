"""Производные тела: слиток, параболоид, седло, ступеньки, круг, сектор, овал, бусина.

Это тела, которые получаются из стандартных одной формулой, но собирать их
вручную долго: профиль ступеней, скруглённая кромка диска, сквозной канал
бусины, оболочка параболоида. Правило то же, что у ``ops_parts``: команда
появляется, когда заменяет три и более строки и несёт размеры, которые нельзя
угадать (шаг ступени, глубина седла, диаметр отверстия под шнур).
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import anchor, make_solid, op
from .ops_shapes import _profile


# --------------------------------------------------------------------------- #
#  Общие помощники
# --------------------------------------------------------------------------- #
def _segments(a, default: int, minv: int = 16, maxv: int = 512) -> int:
    """Сегментов по кругу: число из параметра или разумное по детализации."""
    from .ops import detail_factor

    asked = a.int("segments", None, minv=8, maxv=maxv)
    if asked:
        base = int(asked)
    else:
        base = int(default)
    factor = detail_factor(a)
    return int(max(minv, min(maxv, round(base * factor))))


def segments_at(a, diameter: float, minv: int = 16) -> int:
    """Сегментов по кругу — от диаметра и детализации."""
    return _segments(a, max(minv, int(diameter * 1.5)), minv=minv)


def _rounded_rect(hx: float, hy: float, r: float, steps: int = 6) -> list[tuple[float, float]]:
    """Прямоугольник со скруглёнными углами — против часовой стрелки."""
    hx, hy = max(hx, 1e-3), max(hy, 1e-3)
    r = max(0.0, min(r, min(hx, hy) * 0.98))
    if r <= 1e-6:
        return [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    pts: list[tuple[float, float]] = []
    centres = [(hx - r, -hy + r, -90.0), (hx - r, hy - r, 0.0),
               (-hx + r, hy - r, 90.0), (-hx + r, -hy + r, 180.0)]
    for cx, cy, start in centres:
        for k in range(steps + 1):
            ang = math.radians(start + 90.0 * k / steps)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _treat_corners(pts: list[tuple[float, float]], radius: float = 0.0,
                   chamfer: float = 0.0, steps: int = 5) -> list[tuple[float, float]]:
    """Скругляет или срезает выпуклые углы контура (вогнутые не трогает)."""
    if radius <= 1e-9 and chamfer <= 1e-9:
        return list(pts)
    n = len(pts)
    out: list[tuple[float, float]] = []
    for i in range(n):
        p0 = np.array(pts[i - 1], dtype=float)
        p1 = np.array(pts[i], dtype=float)
        p2 = np.array(pts[(i + 1) % n], dtype=float)
        # u1 — «пришли в точку», u2 — «уходим из точки». Для контура против
        # часовой стрелки положительное векторное произведение u1×u2 значит
        # выпуклый угол. Со знаком наоборот скруглялись вогнутые углы, а
        # ступени оставались острыми.
        u1, u2 = p1 - p0, p2 - p1
        l1, l2 = float(np.linalg.norm(u1)), float(np.linalg.norm(u2))
        if l1 < 1e-9 or l2 < 1e-9:
            out.append((float(p1[0]), float(p1[1])))
            continue
        v1, v2 = -u1 / l1, u2 / l2          # от точки к соседям
        convex = (u1[0] * u2[1] - u1[1] * u2[0]) > 1e-9
        if not convex:
            out.append((float(p1[0]), float(p1[1])))
            continue
        cosang = float(np.clip(v1 @ v2, -1.0, 1.0))
        alpha = math.acos(cosang)                      # внутренний угол
        if alpha < 1e-3 or alpha > math.pi - 1e-3:
            out.append((float(p1[0]), float(p1[1])))
            continue
        limit = 0.45 * min(l1, l2)
        if chamfer > 1e-9:
            c = min(chamfer, limit)
            out.append(tuple(p1 + v1 * c))
            out.append(tuple(p1 + v2 * c))
            continue
        d = radius / math.tan(alpha / 2.0)            # расстояние до точек касания
        if d > limit:                                 # радиус не влезает в рёбра
            d = limit
            radius_use = d * math.tan(alpha / 2.0)
        else:
            radius_use = radius
        if radius_use <= 1e-9:
            out.append((float(p1[0]), float(p1[1])))
            continue
        bis = v1 + v2
        bis = bis / np.linalg.norm(bis)
        centre = p1 + bis * (radius_use / math.sin(alpha / 2.0))
        t1 = p1 + v1 * d
        t2 = p1 + v2 * d
        a1 = math.atan2(t1[1] - centre[1], t1[0] - centre[0])
        a2 = math.atan2(t2[1] - centre[1], t2[0] - centre[0])
        sweep = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        for k in range(steps + 1):
            ang = a1 + sweep * k / steps
            out.append((centre[0] + radius_use * math.cos(ang),
                        centre[1] + radius_use * math.sin(ang)))
    return out


def _extrude_xz(pts: list[tuple[float, float]], width: float) -> mf.Manifold:
    """Контур в плоскости XZ (x — вперёд, y — вверх) выдавливается по Y."""
    cs = mf.CrossSection([_profile(pts)])
    if cs.is_empty():
        raise GeometryError("Контур не замкнулся: проверьте размеры.")
    solid = cs.extrude(float(width)).rotate((90.0, 0.0, 0.0))
    return solid.translate((0.0, float(width) / 2.0, 0.0))


# --------------------------------------------------------------------------- #
#  Круг — плоский цилиндр с объёмом
# --------------------------------------------------------------------------- #
@op("disc", aliases=("круг", "кружок", "круглый_диск", "диск", "disk"),
    category="Примитивы",
    summary="Круг — плоский цилиндр с объёмом: подставка, медаль, крышка, блин, "
            "шайба без дырки. Диаметр и толщина в миллиметрах; round скругляет "
            "кромку по всему кругу, поэтому край не режет.",
    example="блин = disc diameter=120 thickness=8\n"
            "медаль = disc diameter=80 thickness=6 round=2.5",
    params={"diameter": "диаметр, мм (100)", "thickness": "толщина, мм (6)",
            "round": "скругление кромки, мм (0)",
            "segments": "сегментов по кругу (по детализации)",
            "detail": "детализация 0…5 (3)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["diameter", "thickness"])
def disc(a, name):
    diameter = float(a.num("diameter", 100.0, minv=0.2))
    thickness = float(a.num("thickness", 6.0, minv=0.1))
    radius = diameter / 2.0
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    segments = _segments(a, max(24, int(diameter * 1.2)), minv=12)
    if round_r > 1e-6:
        if round_r >= radius - 1e-3:
            raise GeometryError(f"Скругление {round_r:g} мм больше радиуса {radius:g} мм.",
                                hint=f"round должен быть меньше {radius:g} мм.")
        if round_r * 2.0 >= thickness - 1e-3:
            raise GeometryError(
                f"Скругление {round_r:g} мм не оставляет толщины: она {thickness:g} мм.",
                hint=f"round должен быть меньше {thickness / 2:g} мм.")
        solid = mf.Manifold.cylinder(thickness - 2 * round_r, radius - round_r,
                                     radius - round_r, segments, center=True)
        solid = solid.minkowski_sum(mf.Manifold.sphere(round_r, max(12, segments // 4)))
    else:
        solid = mf.Manifold.cylinder(thickness, radius, radius, segments, center=True)
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="disc")
    out.notes.append(f"круг ø{diameter:g}×{thickness:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Сектор круга — кусок пирога
# --------------------------------------------------------------------------- #
@op("pie", aliases=("сектор_круга", "круговой_сектор", "кусок_пирога",
                    "сектор_диска", "pie_slice"),
    category="Примитивы",
    summary="Сектор круга — «кусок пирога» с объёмом: угол, поворот и толщина. "
            "Годится для стрелок-указателей, козырьков, сегментов диаграмм и "
            "секторных подставок. angle=360 даёт целый круг.",
    example="кусок = pie diameter=140 angle=90 thickness=8\n"
            "стрелка = pie diameter=120 angle=60 start=30 thickness=6",
    params={"diameter": "диаметр, мм (120)",
            "angle": "угол сектора, градусы (90)",
            "start": "откуда начинать, градусы от +X (0)",
            "thickness": "толщина, мм (6)",
            "segments": "сегментов по дуге (по детализации)",
            "detail": "детализация 0…5 (3)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["diameter"])
def pie(a, name):
    diameter = float(a.num("diameter", 120.0, minv=0.4))
    angle = float(a.num("angle", 90.0, minv=1.0, maxv=360.0) or 90.0)
    start = float(a.num("start", 0.0) or 0.0)
    thickness = float(a.num("thickness", 6.0, minv=0.1))
    radius = diameter / 2.0
    if angle < 359.5:
        full = _segments(a, max(24, int(diameter * 1.2)), minv=12)
        n = max(4, int(round(full * angle / 360.0)))
        pts = [(0.0, 0.0)]
        for k in range(n + 1):
            ang = math.radians(start + angle * k / n)
            pts.append((radius * math.cos(ang), radius * math.sin(ang)))
        solid = mf.CrossSection([_profile(pts)]).extrude(thickness)
    else:
        full = _segments(a, max(24, int(diameter * 1.2)), minv=12)
        solid = mf.Manifold.cylinder(thickness, radius, radius, full).translate((0, 0, 0))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="pie")
    out.notes.append(f"сектор {angle:g}° от {start:g}°, ø{diameter:g}×{thickness:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Овал — эллиптическая плита
# --------------------------------------------------------------------------- #
@op("oval", aliases=("овал", "овальная_плита", "эллипс_плита", "овальный_диск",
                     "ellipse_plate"),
    category="Примитивы",
    summary="Овал — плоская плита эллиптической формы с объёмом: стол, зеркало, "
            "поднос, площадка. width по X, length по Y, thickness по Z; round "
            "скругляет кромку. diameter делает из овала круг.",
    example="поднос = oval width=200 length=120 thickness=8\n"
            "зеркало = oval width=90 length=140 thickness=6 round=2",
    params={"width": "ширина по X, мм (160)",
            "length": "длина по Y, мм (100)",
            "diameter": "если задан — круг этого диаметра вместо овала",
            "thickness": "толщина, мм (6)",
            "round": "скругление кромки, мм (0)",
            "segments": "точек по контуру (по детализации)",
            "detail": "детализация 0…5 (3)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["width", "length"])
def oval(a, name):
    diameter = a.num("diameter", None, minv=0.2)
    if diameter is not None:
        width = length = float(diameter)
    else:
        width = float(a.num("width", 160.0, minv=0.2))
        length = float(a.num("length", 100.0, minv=0.2))
    thickness = float(a.num("thickness", 6.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    hx, hy = width / 2.0, length / 2.0
    segments = _segments(a, max(32, int(max(width, length) * 1.1)), minv=16)
    if round_r > 1e-6:
        if round_r >= min(hx, hy) - 1e-3:
            raise GeometryError(f"Скругление {round_r:g} мм больше полуширины овала.",
                                hint=f"round должен быть меньше {min(hx, hy):g} мм.")
        if round_r * 2.0 >= thickness - 1e-3:
            raise GeometryError(
                f"Скругление {round_r:g} мм не оставляет толщины: она {thickness:g} мм.",
                hint=f"round должен быть меньше {thickness / 2:g} мм.")
        ax, by = hx - round_r, hy - round_r
    else:
        ax, by = hx, hy
    ang = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    pts = [(float(ax * math.cos(t)), float(by * math.sin(t))) for t in ang]
    body = thickness - 2 * round_r if round_r > 1e-6 else thickness
    solid = mf.CrossSection([_profile(pts)]).extrude(body).translate((0, 0, -body / 2))
    if round_r > 1e-6:
        solid = solid.minkowski_sum(mf.Manifold.sphere(round_r, max(12, segments // 4)))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="oval")
    out.notes.append(f"овал {width:g}×{length:g}×{thickness:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Бусина — шар с отверстием
# --------------------------------------------------------------------------- #
@op("bead", aliases=("бусина", "бусинка", "бусик", "bead"),
    category="Примитивы",
    summary="Бусина — шар с отверстием под шнур (ось Z). Диаметр и высота "
            "задаются отдельно: высота меньше диаметра — сплюснутая бусина, "
            "больше — бочонок. hole — отверстие, chamfer снимает фаску у входа, "
            "поэтому шнур не режет кромку. Тело строится вращением профиля, "
            "поэтому ширина точная; сквозной канал и фаска срезают полюса — "
            "фактическую высоту команда пишет в отчёте.",
    example="бус = bead diameter=16 hole=4\n"
            "кольцо_бус = bead diameter=24 height=14 hole=6 chamfer=1.2",
    params={"diameter": "наружный диаметр, мм (16)",
            "height": "полная высота по оси Z (равна диаметру)",
            "hole": "диаметр отверстия, мм (4)",
            "chamfer": "фаска у входа в отверстие, мм (0)",
            "segments": "сегментов по кругу (по детализации)",
            "detail": "детализация 0…5 (3)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["diameter"])
def bead(a, name):
    diameter = float(a.num("diameter", 16.0, minv=0.6))
    height = float(a.num("height", diameter, minv=0.3))
    hole = float(a.num("hole", max(0.5, diameter * 0.25), minv=0.05))
    chamfer = float(a.num("chamfer", 0.0, minv=0.0) or 0.0)
    if hole >= min(diameter, height) * 0.85:
        raise GeometryError(
            f"Отверстие {hole:g} мм не оставляет стенки: бусина ø{diameter:g} мм.",
            hint=f"hole должен быть меньше {min(diameter, height) * 0.85:g} мм.")
    radius, half = diameter / 2.0, height / 2.0
    hole_r = hole / 2.0
    # высота, на которой отверстие выходит на поверхность
    z_s = half * math.sqrt(max(0.0, 1.0 - (hole_r / radius) ** 2))
    z_f, r_f = z_s, hole_r
    if chamfer > 1e-6:
        z_f = max(0.0, half - chamfer)
        r_f = radius * math.sqrt(max(0.0, 1.0 - (z_f / half) ** 2))
        # хватает ли места на фаску: она должна быть шире отверстия
        need = hole_r * 1.15
        if r_f < need:
            z_f = half * math.sqrt(max(0.0, 1.0 - (min(need, radius) / radius) ** 2))
            r_f = radius * math.sqrt(max(0.0, 1.0 - (z_f / half) ** 2))
        if r_f <= hole_r + 1e-6:
            z_f = z_s
            r_f = hole_r
            chamfer = 0.0
    z0 = z_f - (r_f - hole_r) if chamfer > 1e-6 else z_f
    if z0 <= 1e-6:
        z0 = z_f
    samples = 24
    # φ = 0 — полюс, φ = π/2 — экватор: точка (r, z) = (radius·sinφ, half·cosφ)
    phi_f = math.acos(min(1.0, max(-1.0, z_f / half)))
    prof: list[tuple[float, float]] = [(hole_r, z0), (max(r_f, hole_r), z_f)]
    for k in range(samples + 1):
        phi = phi_f + (math.pi - 2.0 * phi_f) * k / samples
        prof.append((radius * math.sin(phi), half * math.cos(phi)))
    prof.append((hole_r, -z0))
    solid = mf.Manifold.revolve(mf.CrossSection([_profile(prof)]), segments_at(a, diameter))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="bead")
    bb = solid.bounding_box()
    real_h = bb[5] - bb[2]
    note = f"бусина ø{diameter:g} мм, отверстие {hole:g} мм"
    if real_h < height - 0.05:
        # сквозной канал и фаска срезают полюса — говорим это прямо
        note += f", высота {real_h:.2f} из {height:g} мм (полюса срезаны каналом"
        note += f" и фаской {chamfer:g} мм)" if chamfer > 1e-6 else ")"
    else:
        note += f", высота {height:g} мм"
    out.notes.append(note)
    return out


# --------------------------------------------------------------------------- #
#  Слиток — объёмная трапеция
# --------------------------------------------------------------------------- #
@op("ingot", aliases=("слиток", "слиток_золота", "брусок_трапеция",
                      "трапеция_объёмная", "ingot_bar"),
    category="Примитивы",
    summary="Слиток — объёмная трапеция: нижняя площадка больше верхней, бока "
            "скошены, углы скруглены. Классический слиток металла, груз, "
            "кирпич-«трапеция», основание под наклонные стенки.",
    example="слиток = ingot length=100 width=50 height=22 taper=8\n"
            "груз = ingot length=60 width=40 height=30 taper=12 round=6",
    params={"length": "длина по X, мм (100)", "width": "ширина по Y, мм (50)",
            "height": "высота, мм (22)",
            "taper": "скос: насколько верхняя площадка меньше нижней, мм (8)",
            "round": "скругление углов в плане, мм (0)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["length"])
def ingot(a, name):
    length = float(a.num("length", 100.0, minv=1.0))
    width = float(a.num("width", 50.0, minv=1.0))
    height = float(a.num("height", 22.0, minv=0.5))
    taper = float(a.num("taper", 8.0, minv=0.0) or 0.0)
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    hx, hy = length / 2.0, width / 2.0
    taper = min(taper, min(hx, hy) * 0.9)
    bottom = _rounded_rect(hx, hy, round_r)
    top = _rounded_rect(hx - taper, hy - taper, round_r)
    pts = [(x, y, 0.0) for x, y in bottom] + [(x, y, height) for x, y in top]
    solid = mf.Manifold.hull_points(np.ascontiguousarray(pts, dtype=np.float64))
    # объём усечённой пирамиды: h/3·(S1 + S2 + √(S1·S2))
    s1, s2 = length * width, (length - 2 * taper) * (width - 2 * taper)
    expect = height / 3.0 * (s1 + s2 + math.sqrt(s1 * s2))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="ingot")
    out.notes.append(f"слиток {length:g}×{width:g}×{height:g} мм, скос {taper:g} мм, "
                     f"объём {solid.volume():.0f} мм³ (у трапеции {expect:.0f})")
    return out


# --------------------------------------------------------------------------- #
#  Параболоид — чаша или купол
# --------------------------------------------------------------------------- #
@op("paraboloid", aliases=("параболоид", "параболическая_чаша", "чаша_параболоида",
                           "купол_параболы", "paraboloid_dish"),
    category="Примитивы",
    summary="Параболоид вращения — гладкая чаша или купол: антенна, плафон, "
            "миска, купол башни. wall=0 даёт сплошное тело, wall>0 — настоящую "
            "чашу со стенкой (стенка меряется по высоте). В отличие от полусферы "
            "склон у чаши выполаживается к краю.",
    example="чаша = paraboloid diameter=140 height=34\n"
            "миска = paraboloid diameter=120 height=40 wall=3\n"
            "плафон = paraboloid diameter=90 height=60",
    params={"diameter": "диаметр по краю, мм (120)",
            "height": "высота от дна до края, мм (35)",
            "wall": "толщина стенки: 0 — сплошной купол (0)",
            "segments": "сегментов по кругу (по детализации)",
            "detail": "детализация 0…5 (3)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["diameter", "height"])
def paraboloid(a, name):
    diameter = float(a.num("diameter", 120.0, minv=1.0))
    height = float(a.num("height", 35.0, minv=0.5))
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    radius = diameter / 2.0
    segments = _segments(a, max(32, int(diameter * 0.8)), minv=16)
    samples = max(8, min(48, segments // 4))

    def outer(r: float) -> float:
        return height * (1.0 - (r / radius) ** 2)

    if wall <= 1e-6:
        prof = [(radius * (1.0 - k / samples), outer(radius * (1.0 - k / samples)))
                for k in range(samples + 1)]
        prof.append((0.0, 0.0))
    else:
        if wall >= height * 0.9:
            raise GeometryError(
                f"Стенка {wall:g} мм почти равна высоте {height:g} мм — чаши не будет.",
                hint=f"wall должен быть меньше {height * 0.9:g} мм.")
        r_in = radius * math.sqrt(max(0.0, 1.0 - wall / height))
        prof = [(radius * (1.0 - k / samples),
                 outer(radius * (1.0 - k / samples))) for k in range(samples + 1)]
        prof.append((0.0, height))
        prof.append((0.0, height - wall))
        for k in range(1, samples + 1):
            r = r_in * k / samples
            prof.append((r, outer(r) - wall))
        if r_in < radius - 1e-6:
            prof.append((radius, 0.0))
    cs = mf.CrossSection([_profile(prof)])
    if cs.is_empty():
        raise GeometryError("Профиль параболоида не замкнулся.")
    solid = mf.Manifold.revolve(cs, segments)
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="paraboloid")
    kind_text = "чаша со стенкой" if wall > 1e-6 else "сплошной купол"
    out.notes.append(f"параболоид ø{diameter:g}×{height:g} мм, {kind_text}"
                     + (f" {wall:g} мм" if wall > 1e-6 else ""))
    return out


# --------------------------------------------------------------------------- #
#  Гиперболический параболоид — седло
# --------------------------------------------------------------------------- #
@op("saddle", aliases=("гиперболический_параболоид", "гиперпараболоид", "седло",
                       "гиперболоид", "hyperbolic_paraboloid", "hypar"),
    category="Примитивы",
    summary="Гиперболический параболоид — седло: в одну сторону поверхность "
            "поднимается, в другую опускается. mode=гипар — классическая "
            "седловая крыша с прямыми рёбрами (углы попарно вверх и вниз), "
            "mode=седло — чаша-«чипс» (углы на одном уровне, края вверх-вниз). "
            "Толщина даёт настоящую плиту, а не лист.",
    example="крыша = saddle length=160 width=120 rise=40 thickness=5\n"
            "чипс = saddle length=120 width=120 rise=30 thickness=3 mode=седло",
    params={"length": "длина по X, мм (140)", "width": "ширина по Y, мм (140)",
            "rise": "перепад высот между верхом и низом, мм (40)",
            "thickness": "толщина плиты, мм (4)",
            "mode": "гипар (крыша) или седло (чипс) — «гипар»",
            "segments": "точек по стороне (по детализации)",
            "detail": "детализация 0…5 (3)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["length"])
def saddle(a, name):
    from .ops_sheet import _thick_surface

    length = float(a.num("length", 140.0, minv=1.0))
    width = float(a.num("width", 140.0, minv=1.0))
    rise = float(a.num("rise", 40.0, minv=0.1))
    thickness = float(a.num("thickness", 4.0, minv=0.2))
    mode = (a.text("mode", "гипар") or "гипар").strip().lower()
    if mode in ("седло", "чипс", "saddle", "чип"):
        mode = "седло"
    elif mode in ("гипар", "крыша", "hypar", "hyperbolic"):
        mode = "гипар"
    else:
        raise GeometryError(f"Неизвестный mode «{mode}».",
                            hint="mode=гипар (крыша с прямыми рёбрами) или "
                                 "mode=седло (чипс).")
    segments = _segments(a, max(16, min(64, int(max(length, width) * 0.3))),
                         minv=8, maxv=64)

    def point(s, t):
        x = (np.asarray(s, dtype=float) - 0.5) * length
        y = (np.asarray(t, dtype=float) - 0.5) * width
        u, v = 2.0 * x / length, 2.0 * y / width
        if mode == "седло":
            z = rise * 0.5 * (u * u - v * v)
        else:
            z = rise * 0.5 * (u * v)
        return np.stack([x, y, z], axis=-1)

    solid = _thick_surface(point, segments, segments, thickness, "седла")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="saddle")
    word = "седло-чипс" if mode == "седло" else "гипар (крыша)"
    out.notes.append(f"гиперболический параболоид {length:g}×{width:g} мм, "
                     f"перепад {rise:g} мм, толщина {thickness:g} мм — {word}")
    return out


# --------------------------------------------------------------------------- #
#  Ступеньки
# --------------------------------------------------------------------------- #
def _stairs_profile(steps: int, run: float, rise: float) -> list[tuple[float, float]]:
    """Контур лестницы в плоскости XZ: подъём идёт в +X."""
    pts = [(0.0, 0.0), (steps * run, 0.0), (steps * run, steps * rise)]
    for i in range(steps, 0, -1):
        pts.append(((i - 1) * run, i * rise))
        pts.append(((i - 1) * run, (i - 1) * rise))
    if len(pts) > 1 and abs(pts[-1][0]) < 1e-9 and abs(pts[-1][1]) < 1e-9:
        pts.pop()
    return pts


@op("stairs", aliases=("ступеньки", "ступени", "лестница", "лесенка", "staircase"),
    category="Примитивы",
    summary="Ступеньки — готовый марш: число ступеней, подъём, глубина проступи "
            "и ширина. shape=прямая — строгие блоки, скруглённая — круглая "
            "кромка-носик, скошенная — фаска на кромке. Подъём идёт в +X: "
            "низкая ступень слева, высокая справа.",
    example="марш = stairs steps=6 rise=18 run=28 width=120\n"
            "мягкий = stairs steps=5 rise=16 run=30 width=100 shape=скруглённая\n"
            "камень = stairs steps=7 rise=15 run=32 width=140 shape=скошенная",
    params={"steps": "число ступеней (6)", "rise": "высота ступени, мм (18)",
            "run": "глубина проступи, мм (28)", "width": "ширина марша, мм (120)",
            "shape": "прямая · скруглённая · скошенная — «прямая»",
            "round": "радиус скругления/фаски кромки, мм (авто)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["steps", "rise", "run"])
def stairs(a, name):
    steps = int(a.int("steps", 6, minv=1, maxv=120) or 6)
    rise = float(a.num("rise", 18.0, minv=0.5))
    run = float(a.num("run", 28.0, minv=0.5))
    width = float(a.num("width", 120.0, minv=1.0))
    shape = (a.text("shape", "прямая") or "прямая").strip().lower()
    shape = {"прямая": "прямая", "прямые": "прямая", "блок": "прямая",
             "скруглённая": "скруглённая", "скругленная": "скруглённая",
             "круглая": "скруглённая", "мягкая": "скруглённая",
             "скошенная": "скошенная", "фаска": "скошенная",
             "скошеные": "скошенная"}.get(shape)
    if shape is None:
        raise GeometryError(
            f"Неизвестная форма ступеней: «{a.text('shape')}».",
            hint="shape=прямая, скруглённая или скошенная.")
    edge = float(a.num("round", min(run, rise) * 0.35, minv=0.0) or 0.0)
    pts = _stairs_profile(steps, run, rise)
    if shape == "скруглённая":
        pts = _treat_corners(pts, radius=max(edge, 0.05))
    elif shape == "скошенная":
        pts = _treat_corners(pts, chamfer=max(edge, 0.05))
    solid = _extrude_xz(pts, width)
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="stairs")
    out.notes.append(f"{steps} ступеней {rise:g}×{run:g} мм, ширина {width:g} мм — "
                     f"{shape}, габарит {steps * run:g}×{width:g}×{steps * rise:g} мм")
    return out


def _placed(a, solid: mf.Manifold) -> mf.Manifold:
    return anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
