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
from .ops_basic import _sliced_sphere
from .ops_shapes import _profile, _revolve
from .shape_features import apply_smooth, cut_center_hole


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
#  Круг — плоский, вогнутый или выпуклый цилиндр с объёмом
# --------------------------------------------------------------------------- #
def _top_kind(a, what: str) -> str:
    raw = (a.text("top", "плоская") or "плоская").strip().lower()
    value = {"плоская": "плоская", "плоский": "плоская",
             "вогнутая": "вогнутая", "вогнутый": "вогнутая",
             "выпуклая": "выпуклая", "выпуклый": "выпуклая"}.get(raw)
    if value is None:
        raise GeometryError(f"{what}: top=плоская, вогнутая или выпуклая.")
    return value


def _curved_plate(hx: float, hy: float, thickness: float, sag: float,
                  top: str, segments: int, what: str) -> mf.Manifold:
    """Параболическая верхняя поверхность при идеально плоском низе."""
    if top == "вогнутая" and sag >= thickness - 0.05:
        raise GeometryError(f"{what}: sag почти прорезает вогнутую пластину.",
                            hint=f"sag должна быть меньше {thickness - 0.05:g} мм.")
    sign = 1.0 if top == "выпуклая" else -1.0
    profile = [(0.0, 0.0), (1.0, 0.0), (1.0, thickness)]
    for i in range(1, 25):
        r = 1.0 - i / 24.0
        z = thickness + sign * sag * (1.0 - r * r)
        profile.append((r, z))
    # revolve замыкает профиль по оси; четвёрки сегментов дают точные полуоси.
    segments = max(12, int(segments))
    segments += (-segments) % 4
    solid = _revolve(profile, segments, what)
    if abs(hx - hy) > 1e-9 or abs(hx - 1.0) > 1e-9:
        solid = solid.transform(np.asarray([[hx, 0, 0, 0], [0, hy, 0, 0], [0, 0, 1, 0]],
                                           dtype=float))
    return solid


@op("disc", aliases=("круг", "кружок", "круглый_диск", "диск", "disk"),
    category="Примитивы",
    summary="Круг с плоской, параболически вогнутой или выпуклой верхней "
            "поверхностью. sag — стрела кривизны в мм как у кнопки; низ всегда "
            "плоский. round скругляет кромку плоского варианта.",
    example="блин = disc diameter=120 thickness=8\n"
            "чаша = disc diameter=100 thickness=8 top=вогнутая sag=3\n"
            "линза = disc diameter=90 thickness=6 top=выпуклая sag=4",
    params={"diameter": "диаметр, мм (100)", "thickness": "толщина у кромки, мм (6)",
            "top": "верх: плоская, вогнутая или выпуклая",
            "sag": "стрела верхней кривизны, мм (авто: 25% толщины)",
            "round": "скругление кромки, мм (0; только top=плоская)",
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
    top = _top_kind(a, "круг")
    if top != "плоская":
        if round_r > 1e-6:
            raise GeometryError("Круг: round совместим только с top=плоская.",
                                hint="Для вогнутого/выпуклого верха задайте round=0.")
        sag = float(a.num("sag", max(0.1, thickness * 0.25), minv=0.01))
        solid = _curved_plate(radius, radius, thickness, sag, top, segments, "круг")
    elif round_r > 1e-6:
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
    out.notes.append(f"круг ø{diameter:g}×{thickness:g} мм, верх {top}")
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
            "hole": "центральное сквозное отверстие у вершины сектора, мм (0 — сплошной)",
            "smooth": "уровни Loop-сглаживания всего сектора 0…4 (0)",
            "segments": "сегментов по дуге (по детализации)",
            "detail": "детализация 0…5 (3)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["diameter"])
def pie(a, name):
    diameter = float(a.num("diameter", 120.0, minv=0.4))
    angle = float(a.num("angle", 90.0, minv=1.0, maxv=360.0) or 90.0)
    start = float(a.num("start", 0.0) or 0.0)
    thickness = float(a.num("thickness", 6.0, minv=0.1))
    hole = float(a.num("hole", 0.0, minv=0.0) or 0.0)
    radius = diameter / 2.0
    if hole >= diameter - 0.4:
        raise GeometryError("Сектор круга: hole не оставляет дуги вокруг отверстия.",
                            hint="Уменьшите hole хотя бы на 0.4 мм ниже diameter.")
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
    solid = cut_center_hole(solid, thickness, hole, what="сектор круга")
    solid = apply_smooth(solid, a, "сектор круга")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="pie")
    out.notes.append(f"сектор {angle:g}° от {start:g}°, ø{diameter:g}×{thickness:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Овал — эллиптическая плита
# --------------------------------------------------------------------------- #
@op("oval", aliases=("овал", "овальная_плита", "эллипс_плита", "овальный_диск",
                     "ellipse_plate"),
    category="Примитивы",
    summary="Овальная плита с плоской, параболически вогнутой или выпуклой "
            "верхней поверхностью. width по X, length по Y, thickness у кромки "
            "по Z; sag — стрела кривизны. Низ плоский, diameter делает круг.",
    example="поднос = oval width=200 length=120 thickness=8\n"
            "вогнутый = oval width=160 length=100 thickness=7 top=вогнутая sag=3\n"
            "купол = oval width=150 length=100 thickness=5 top=выпуклая sag=5",
    params={"width": "ширина по X, мм (160)",
            "length": "длина по Y, мм (100)",
            "diameter": "если задан — круг этого диаметра вместо овала",
            "thickness": "толщина у кромки, мм (6)",
            "top": "верх: плоская, вогнутая или выпуклая",
            "sag": "стрела верхней кривизны, мм (авто: 25% толщины)",
            "round": "скругление кромки, мм (0; только top=плоская)",
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
    top = _top_kind(a, "овал")
    if top != "плоская":
        if round_r > 1e-6:
            raise GeometryError("Овал: round совместим только с top=плоская.",
                                hint="Для вогнутого/выпуклого верха задайте round=0.")
        sag = float(a.num("sag", max(0.1, thickness * 0.25), minv=0.01))
        solid = _curved_plate(hx, hy, thickness, sag, top, segments, "овал")
    else:
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
    out.notes.append(f"овал {width:g}×{length:g}×{thickness:g} мм, верх {top}")
    return out


# --------------------------------------------------------------------------- #
#  Бусина — шар с отверстием
# --------------------------------------------------------------------------- #
@op("bead", aliases=("бусина", "бусинка", "бусик", "bead"),
    category="Примитивы",
    summary="Бусина — шар с отверстием под шнур (ось Z). Диаметр и высота "
            "независимы. slice/cut отсекают верх как у шара (cut=slice·radius), "
            "round скругляет плоскую кромку среза; chamfer раскрывает вход "
            "отверстия. Канал вырезается после масштаба высоты и остаётся круглым.",
    example="бус = bead diameter=16 hole=4\n"
            "кольцо_бус = bead diameter=24 height=14 hole=6 chamfer=1.2\n"
            "срез = bead diameter=24 height=18 hole=6 slice=0.5 round=1",
    params={"diameter": "наружный диаметр, мм (16)",
            "height": "полная высота по оси Z (равна диаметру)",
            "hole": "диаметр отверстия, мм (4)",
            "slice": "срез сверху, доля radius=diameter/2, 0…1 (0)",
            "cut": "срез сверху в мм; альтернатива slice, не одновременно",
            "round": "скругление новой кромки среза, мм; требует slice/cut (0)",
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
    slice_share = float(a.num("slice", 0.0, minv=0.0, maxv=1.0) or 0.0)
    cut_mm = a.num("cut", None, minv=0.0)
    if cut_mm is not None and a.has("slice"):
        raise GeometryError("Бусина: задайте slice ИЛИ cut, не оба сразу.")
    cut = float(cut_mm) if cut_mm is not None else slice_share * radius
    if cut > radius + 1e-9:
        raise GeometryError("Бусина: cut не может быть больше radius=diameter/2.")
    if cut >= height - 0.05 and cut > 1e-9:
        raise GeometryError("Срез бусины должен оставить нижнюю часть тела.",
                            hint="Уменьшите slice/cut или увеличьте height.")
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if round_r > 1e-9 and cut <= 1e-9:
        raise GeometryError("Бусина: round относится к срезу — задайте slice>0 или cut>0.")
    if cut > 1e-9:
        # Сферический профиль даёт ту же кромку, что sphere. Масштаб только
        # по Z сохраняет круглое отверстие в плане; абсолютный cut остаётся мм.
        source_cut = radius * cut / half
        segments = segments_at(a, diameter)
        solid = _sliced_sphere(radius, source_cut, round_r, segments)
        sz = half / radius
        solid = solid.transform(np.array([[1.0, 0.0, 0.0, 0.0],
                                          [0.0, 1.0, 0.0, 0.0],
                                          [0.0, 0.0, sz, 0.0]]))
        channel = mf.Manifold.cylinder(2.0 * height + 4.0, hole_r, hole_r,
                                       segments, center=True)
        solid = solid - channel
        top_z = half - cut
        if chamfer > 1e-6:
            flare = mf.Manifold.cylinder(chamfer + 1.0, hole_r,
                                         hole_r + chamfer + 1.0, segments)
            solid = solid - flare.translate((0.0, 0.0, top_z - chamfer))
        solid = _placed(a, solid)
        out = make_solid(a.scene, name, solid, a, kind="bead")
        bb = solid.bounding_box()
        out.meta["slice"] = {"cut_mm": cut, "plane_z": float(bb[5]),
                             "round": round_r}
        out.notes.append(f"бусина ø{diameter:g}×{height:g}, срез {cut:g} мм, "
                         f"кромка round={round_r:g}, отверстие {hole:g}")
        return out
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
    summary="Слиток — объёмная трапеция с независимой верхней площадкой. "
            "taper_mode=бока скашивает только лево/право и оставляет перёд/зад "
            "параллельными; top_size/top_offset задают верх напрямую. round "
            "округляет углы контура, smooth сглаживает всё тело.",
    example="слиток = ingot length=100 width=50 height=22 taper=8\n"
            "груз = ingot length=60 width=40 height=30 taper_mode=бока taper=8 smooth=1\n"
            "верх = ingot length=100 width=50 height=22 top_size=[70,35] top_offset=[8,0]",
    params={"length": "длина низа по X, мм (100)", "width": "ширина низа по Y, мм (50)",
            "height": "высота, мм (22)",
            "taper": "скос верхней площадки относительно низа, мм (8)",
            "taper_mode": "все — скос со всех сторон; бока/sides — только ±X, перёд/зад параллельны",
            "top_size": "независимые размеры верха [X,Y]; перекрывает taper",
            "top_offset": "сдвиг верхней плоскости [dx,dy], мм",
            "round": "скругление только углов контура в плане, мм (0)",
            "smooth": "Loop-сглаживание всех граней 0…4 (0)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["length"])
def ingot(a, name):
    length = float(a.num("length", 100.0, minv=1.0))
    width = float(a.num("width", 50.0, minv=1.0))
    height = float(a.num("height", 22.0, minv=0.5))
    taper = float(a.num("taper", 8.0, minv=0.0) or 0.0)
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    mode = (a.text("taper_mode") or "все").strip().lower()
    if mode in ("бока", "боковые", "sides", "side", "x"):
        mode = "бока"
    elif mode in ("все", "все_стороны", "all", "полный"):
        mode = "все"
    else:
        raise GeometryError("ingot: taper_mode=все или бока.")
    hx, hy = length / 2.0, width / 2.0
    taper = min(taper, (hx if mode == "бока" else min(hx, hy)) * 0.9)
    tx = hx - taper
    ty = hy if mode == "бока" else hy - taper
    top_size = a.vec("top_size", 2, default=None)
    if top_size is not None:
        if any(float(v) <= 0.2 for v in top_size):
            raise GeometryError("ingot: стороны top_size должны быть больше 0.2 мм.")
        tx, ty = float(top_size[0]) / 2.0, float(top_size[1]) / 2.0
    offset = np.asarray(a.vec("top_offset", 2, default=(0.0, 0.0)), dtype=np.float64)
    bottom = _rounded_rect(hx, hy, round_r)
    top = _rounded_rect(tx, ty, round_r)
    top = [(x + float(offset[0]), y + float(offset[1])) for x, y in top]
    pts = [(x, y, 0.0) for x, y in bottom] + [(x, y, height) for x, y in top]
    solid = mf.Manifold.hull_points(np.ascontiguousarray(pts, dtype=np.float64))
    solid = apply_smooth(solid, a, "слиток")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="ingot")
    out.notes.append(f"слиток {length:g}×{width:g}×{height:g} мм, скос {taper:g} мм "
                     f"({mode}), верх {2*tx:g}×{2*ty:g}, сдвиг {offset.tolist()}")
    return out


# --------------------------------------------------------------------------- #
#  Параболоид — чаша или купол
# --------------------------------------------------------------------------- #
@op("paraboloid", aliases=("параболоид", "параболическая_чаша", "чаша_параболоида",
                           "купол_параболы", "paraboloid_dish"),
    category="Примитивы",
    summary="Параболоид вращения — гладкая чаша или купол: антенна, плафон, "
            "миска, купол башни. wall=0 даёт сплошное тело, wall>0 — настоящую "
            "чашу со стенкой (стенка меряется по высоте). Сплошной купол "
            "направлен вершиной +Z; полая чаша стоит дном вниз и открыта +Z. "
            "В отличие от полусферы склон у чаши выполаживается к краю.",
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
    # Сплошной профиль — купол вершиной +Z. У полой чаши дно и раскрытие
    # меняются местами: после переворота дно остаётся внизу, полость открыта +Z.
    if wall > 1e-6:
        solid = solid.rotate((180.0, 0.0, 0.0))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="paraboloid")
    kind_text = "чаша со стенкой, раскрытие +Z" if wall > 1e-6 else "сплошной купол"
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
def _stairs_profile(steps: int, run: float, rise: float,
                    outer_r: float = 0.0, inner_r: float = 0.0) -> list[tuple[float, float]]:
    """Контур марша XZ с независимыми дугами наружных/внутренних углов."""
    base = [(0.0, 0.0), (steps * run, 0.0), (steps * run, steps * rise)]
    for i in range(steps, 0, -1):
        base.append(((i - 1) * run, i * rise))
        base.append(((i - 1) * run, (i - 1) * rise))
    if abs(base[-1][0]) < 1e-9 and abs(base[-1][1]) < 1e-9:
        base.pop()
    outer = {(round(j * run, 9), round((j + 1) * rise, 9)) for j in range(steps)}
    inner = {(round(j * run, 9), round(j * rise, 9)) for j in range(1, steps)}
    out: list[tuple[float, float]] = []
    for i, cur in enumerate(base):
        prev = base[i - 1]
        nxt = base[(i + 1) % len(base)]
        key = (round(cur[0], 9), round(cur[1], 9))
        radius = outer_r if key in outer else inner_r if key in inner else 0.0
        if radius <= 1e-9 or i == 0 or i + 1 >= len(base):
            out.append(cur)
            continue
        u0 = np.asarray(prev) - np.asarray(cur)
        u1 = np.asarray(nxt) - np.asarray(cur)
        u0 /= np.linalg.norm(u0)
        u1 /= np.linalg.norm(u1)
        p0 = np.asarray(cur) + u0 * radius
        p1 = np.asarray(cur) + u1 * radius
        center = p0 + p1 - np.asarray(cur)
        v0, v1 = p0 - center, p1 - center
        cross = float(v0[0] * v1[1] - v0[1] * v1[0])
        a0 = math.atan2(float(v0[1]), float(v0[0]))
        a1 = math.atan2(float(v1[1]), float(v1[0]))
        if cross > 0.0:
            while a1 <= a0:
                a1 += 2.0 * math.pi
        else:
            while a1 >= a0:
                a1 -= 2.0 * math.pi
        for k in range(9):
            q = k / 8.0
            ang = a0 + (a1 - a0) * q
            pt = center + radius * np.asarray([math.cos(ang), math.sin(ang)])
            out.append((float(pt[0]), float(pt[1])))
    return out


@op("stairs", aliases=("ступеньки", "ступени", "ступеньки_марш", "лесенка", "staircase"),
    category="Примитивы",
    summary="Прямой лестничный марш без скошенных ступеней. Наружная кромка "
            "и внутренний угол настраиваются отдельно: shape=прямая/скруглённая, "
            "inner=прямой/скруглённый. Подъём идёт в +X.",
    example="марш = stairs steps=6 rise=18 run=28 width=120\n"
            "мягкий = stairs steps=6 rise=18 run=28 width=120 shape=скруглённая inner=скруглённый",
    params={"steps": "число ступеней 1…120 (6)", "rise": "высота ступени, мм (18)",
            "run": "глубина проступи, мм (28)", "width": "ширина марша, мм (120)",
            "shape": "наружная кромка: прямая или скруглённая — «прямая»",
            "round": "радиус наружной кромки, мм (авто)",
            "inner": "внутренний угол: прямой или скруглённый — «прямой»",
            "inner_r": "радиус внутреннего угла, мм (авто)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["steps", "rise", "run"])
def stairs(a, name):
    steps = int(a.int("steps", 6, minv=1, maxv=120) or 6)
    rise = float(a.num("rise", 18.0, minv=0.5, maxv=2000.0))
    run = float(a.num("run", 28.0, minv=0.5, maxv=5000.0))
    width = float(a.num("width", 120.0, minv=1.0, maxv=10000.0))
    shape = (a.text("shape", "прямая") or "прямая").strip().lower()
    shape = {"прямая": "прямая", "прямые": "прямая", "блок": "прямая",
             "скруглённая": "скруглённая", "скругленная": "скруглённая",
             "круглая": "скруглённая", "мягкая": "скруглённая"}.get(shape)
    if shape is None:
        raise GeometryError("shape=прямая или скруглённая; скошенного режима нет.")
    inner = (a.text("inner", "прямой") or "прямой").strip().lower()
    inner = {"прямой": "прямой", "прямые": "прямой", "острый": "прямой",
             "скруглённый": "скруглённый", "скругленный": "скруглённый",
             "круглый": "скруглённый", "мягкий": "скруглённый"}.get(inner)
    if inner is None:
        raise GeometryError("inner=прямой или скруглённый.")
    max_r = min(run, rise) * 0.45
    edge = float(a.num("round", min(run, rise) * 0.25,
                       minv=0.0, maxv=max_r) or 0.0)
    inner_r = float(a.num("inner_r", min(run, rise) * 0.25,
                          minv=0.0, maxv=max_r) or 0.0)
    pts = _stairs_profile(steps, run, rise,
                          outer_r=edge if shape == "скруглённая" else 0.0,
                          inner_r=inner_r if inner == "скруглённый" else 0.0)
    solid = _extrude_xz(pts, width)
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="stairs")
    out.notes.append(f"{steps} ступеней {rise:g}×{run:g} мм, ширина {width:g} мм; "
                     f"кромка {shape}, внутренний угол {inner}")
    return out


# --------------------------------------------------------------------------- #
#  Треугольная призма с произвольными углами
# --------------------------------------------------------------------------- #
@op("tri_prism", aliases=("треугольная_призма", "призма_треугольная", "призма3",
                          "треугольник_призма", "triangular_prism"),
    category="Примитивы",
    summary="Треугольная призма с любым треугольником в основании: стороны "
            "задаются числами a, b, c — можно сделать равнобедренную, "
            "прямоугольную или косоугольную. Вместо сторон можно дать основание "
            "и два угла: base, angle_a, angle_b. Основание лежит в XY: сторона "
            "a идёт по X, третья вершина смещена в +Y; height — выдавливание "
            "призмы по +Z.",
    example="клин = tri_prism a=120 b=90 c=60 height=80\n"
            "остроугольная = tri_prism a=100 b=100 c=40 height=50\n"
            "по_углам = tri_prism base=110 angle_a=55 angle_b=65 height=60",
    params={"a": "сторона a (низ, вдоль X), мм (100)",
            "b": "сторона b, мм (по умолчанию равна a)",
            "c": "сторона c, мм (по умолчанию равна a)",
            "base": "основание для варианта с углами, мм (a)",
            "angle_a": "угол при основании слева, градусы (без углов — не задан)",
            "angle_b": "угол при основании справа, градусы",
            "height": "высота призмы, мм (100)",
            "round": "скругление рёбер в основании, мм (0)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["a"])
def tri_prism(a, name):
    side_a = float(a.num("a", 100.0, minv=1.0))
    base = a.num("base", None, minv=1.0)
    ang_a = a.num("angle_a", None, minv=1.0, maxv=179.0)
    ang_b = a.num("angle_b", None, minv=1.0, maxv=179.0)
    if base is not None or ang_a is not None or ang_b is not None:
        # вариант «основание + два угла»
        side_a = float(base if base is not None else side_a)
        aa = float(ang_a if ang_a is not None else 60.0)
        ab = float(ang_b if ang_b is not None else aa)
        ag = 180.0 - aa - ab
        if ag <= 0.5:
            raise GeometryError(
                f"Углы {aa:g}° + {ab:g}° не оставляют третьего угла ({ag:g}°).",
                hint="Сумма двух углов при основании должна быть меньше 180°.")
        k = math.sin(math.radians(ag))
        side_b = side_a * math.sin(math.radians(ab)) / k
        side_c = side_a * math.sin(math.radians(aa)) / k
        # раскладываем углы обратно: A при стороне a слева, B справа
        aa, ab, _ = aa, ab, ag
    else:
        side_b = float(a.num("b", side_a, minv=0.5))
        side_c = float(a.num("c", side_a, minv=0.5))
        aa = None
    height = float(a.num("height", 100.0, minv=0.5))
    if side_a + side_b <= side_c + 1e-6 or side_a + side_c <= side_b + 1e-6 \
            or side_b + side_c <= side_a + 1e-6:
        raise GeometryError(
            f"Из сторон {side_a:g}, {side_b:g}, {side_c:g} треугольник не сложить.",
            hint="Каждая сторона должна быть меньше суммы двух других.")
    x = (side_a ** 2 + side_b ** 2 - side_c ** 2) / (2.0 * side_a)
    y = math.sqrt(max(1e-9, side_b ** 2 - x ** 2))
    pts = [(0.0, 0.0), (side_a, 0.0), (x, y)]
    # основание centred: сдвигаем так, чтобы центр габарита был в нуле
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    dx, dy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    pts = [(px - dx, py - dy) for px, py in pts]
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if round_r > 1e-6:
        pts = _treat_corners(pts, radius=round_r)
    solid = mf.CrossSection([_profile(pts)]).extrude(height)
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="tri_prism")
    kind_text = "равносторонняя" if abs(side_a - side_b) < 1e-3 and abs(side_b - side_c) < 1e-3 \
        else "произвольная"
    out.notes.append(f"треугольная призма {kind_text}: стороны {side_a:g}×"
                     f"{side_b:g}×{side_c:g} мм, высота {height:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Сектор тора
# --------------------------------------------------------------------------- #
@op("torus_sector", aliases=("сектор_тора", "дуга_тора", "часть_тора", "torus_arc",
                             "сектор_кольца"),
    category="Примитивы",
    summary="Сектор тора — дуга бублика круглого сечения. hole>0 делает "
            "продольный туннель ВДОЛЬ всей дуги, как в полом проводе: канал "
            "открыт на обоих торцах и не сверлит трубку поперёк.",
    example="полукольцо = torus_sector major=60 minor=10 angle=180\n"
            "трубка = torus_sector major=50 minor=12 angle=200 hole=8\n"
            "звено = torus_sector major=30 minor=8 angle=180 hole=6",
    params={"major": "радиус кольца (до центра трубки), мм (50)",
            "minor": "радиус трубки, мм (10)",
            "angle": "угол дуги, градусы (180)",
            "start": "откуда начинать дугу, градусы от +X (0)",
            "hole": "диаметр продольного канала по всей дуге, мм (0 — сплошной)",
            "segments": "сегментов по дуге и трубке (по детализации)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["major", "minor"])
def torus_sector(a, name):
    major = float(a.num("major", 50.0, minv=1.0))
    minor = float(a.num("minor", 10.0, minv=0.5))
    angle = float(a.num("angle", 180.0, minv=2.0, maxv=360.0) or 180.0)
    start = float(a.num("start", 0.0) or 0.0)
    hole = float(a.num("hole", 0.0, minv=0.0) or 0.0)
    segments = _segments(a, max(32, int(major * 1.2)), minv=12)
    nprof = max(16, segments // 2)
    prof = [(major + minor * math.cos(t), minor * math.sin(t))
            for t in np.linspace(0.0, 2.0 * math.pi, nprof, endpoint=False)]
    paths = [_profile(prof)]
    if hole > 1e-6:
        if hole >= minor * 2.0 - 0.1:
            raise GeometryError(
                f"Канал {hole:g} мм не оставляет стенки трубки: она "
                f"{minor * 2:g} мм в диаметре.",
                hint=f"hole должен быть меньше {minor * 2 - 0.1:g} мм.")
        inner = hole / 2.0
        paths.append(_profile([(major + inner * math.cos(t), inner * math.sin(t))
                               for t in np.linspace(0.0, 2.0 * math.pi, nprof,
                                                    endpoint=False)]))
    cross = mf.CrossSection(paths, fillrule=mf.FillRule.EvenOdd)
    solid = mf.Manifold.revolve(cross, segments, angle)
    if abs(start) > 1e-6:
        solid = solid.rotate((0.0, 0.0, start))
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="torus_sector")
    out.notes.append(f"сектор тора {angle:g}°: кольцо R{major:g}, трубка "
                     f"r{minor:g} мм" +
                     (f", продольный канал ø{hole:g} мм" if hole else ""))
    return out

def _placed(a, solid: mf.Manifold) -> mf.Manifold:
    return anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
