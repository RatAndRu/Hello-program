"""Знаки и фигуры-символы: стрелка, Т, полумесяц, завиток, молния, скобка, Y.

Это не буквы шрифта, а **тела**: каждую фигуру можно резать, склеивать,
ставить на пол, печатать и проверять ядром. Плоские фигуры строятся в
плоскости XY и выдавливаются по Z; `round` — настоящее скругление кромок
(сжатие контура на радиус и «надувание» шаром), поэтому фигура не теряет
размеров, но перестаёт быть остроугольной.

Скобка и завиток — не плоские: это развёртка профиля по дуге и тело вращения
с винтовой канавкой, то есть настоящий объём, а не выдавленный контур.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import (circle_profile, ellipse_profile, sweep_solid, limit_segments,
                       FINENESS_MM)
from .ops import anchor, make_solid, op
from .ops_shapes import _cross, _profile, ensure_volume


# --------------------------------------------------------------------------- #
#  Общие помощники
# --------------------------------------------------------------------------- #
def _flat(cross: mf.CrossSection, depth: float, round_r: float,
          thin: float, size: tuple[float, float] | None = None) -> mf.Manifold:
    """Плоский контур → тело: выдавливание со скруглением кромок по радиусу.

    ``thin`` — самый узкий размер контура: скругление не может быть больше
    трети от него, иначе сжатие контура «съест» фигуру.

    ``size`` — итоговый габарит по X и Y. Скругление срезает острия, поэтому
    после него деталь чуть меньше заданной; масштаб возвращает точный размер
    (параметры должны означать ровно то, что написано).
    """
    depth = float(depth)
    r = min(float(round_r or 0.0), depth / 2.0 - 1e-4, float(thin) / 3.0)
    if r > 1e-3:
        core = cross.offset(-r, mf.JoinType.Round, 2.0, 20)
        if core.is_empty() or core.area() <= 1e-9:
            raise GeometryError("Скругление больше самой фигуры.",
                                hint="Уменьшите round примерно до трети толщины.")
        solid = core.extrude(depth - 2 * r).translate((0.0, 0.0, r))
        solid = solid.minkowski_sum(mf.Manifold.sphere(r, 20))
    else:
        solid = cross.extrude(depth)
    if size is not None:
        bb = solid.bounding_box()
        sx = float(size[0]) / max(bb[3] - bb[0], 1e-9)
        sy = float(size[1]) / max(bb[4] - bb[1], 1e-9)
        if abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4:
            m = np.eye(3, 4, dtype=np.float64)
            m[0, 0], m[1, 1] = sx, sy
            solid = solid.transform(m)
    return solid


def _poly_cross(points: list[tuple[float, float]]) -> mf.CrossSection:
    return _cross(points)


def _fit(cross: mf.CrossSection, width: float, height: float,
         what: str = "фигуры") -> mf.CrossSection:
    """Подгоняет контур точно под заданные габариты.

    Нужна там, где форму строят ломаной с остриями: без подгонки ``height``
    означал бы длину ломаной, а не высоту готовой детали.
    """
    bb = cross.bounds()
    sx = float(width) / max(bb[2] - bb[0], 1e-9)
    sy = float(height) / max(bb[3] - bb[1], 1e-9)
    if abs(sx - 1.0) < 1e-6 and abs(sy - 1.0) < 1e-6:
        return cross
    out = cross.scale((sx, sy))
    if out.is_empty() or out.area() <= 1e-9:
        raise GeometryError(f"Не удалось подогнать габарит {what}.",
                            hint="Проверьте width и height.")
    return out


def _circle_cs(radius: float, cx: float, cy: float, sides: int) -> mf.CrossSection:
    pts = circle_profile(radius, sides)
    pts = np.asarray(pts, dtype=np.float64) + np.array([cx, cy], dtype=np.float64)
    return mf.CrossSection([pts])


def _stadium(p0: tuple[float, float], p1: tuple[float, float],
             width: float, arc_pts: int = 16) -> np.ndarray:
    """Стадион (капсула) между двумя точками — ровный брус с круглыми торцами."""
    a = np.asarray(p0, dtype=np.float64)
    b = np.asarray(p1, dtype=np.float64)
    d = b - a
    length = float(np.linalg.norm(d))
    if length < 1e-9:
        raise GeometryError("Концы бруса совпали.")
    d = d / length
    n = np.array([-d[1], d[0]])
    r = float(width) / 2.0
    phi_a = np.linspace(-math.pi / 2, math.pi / 2, arc_pts)
    phi_b = np.linspace(math.pi / 2, 3 * math.pi / 2, arc_pts)
    pts = [b + r * (math.cos(t) * d + math.sin(t) * n) for t in phi_a]
    pts += [a + r * (math.cos(t) * d + math.sin(t) * n) for t in phi_b]
    return np.asarray(pts, dtype=np.float64)


def _segments_for(radius: float, asked: int | None, lo: int = 48, hi: int = 512) -> int:
    got = int(limit_segments(asked, max(radius, 1e-3), tolerance=FINENESS_MM, max_n=hi))
    return int(max(lo, min(hi, got)))


# --------------------------------------------------------------------------- #
#  Стрелка
# --------------------------------------------------------------------------- #
@op("arrow", aliases=("стрелка", "стрела", "указатель", "arrow_sign"),
    category="Примитивы",
    summary="Стрелка-указатель остриём вправо (по +X): древко, наконечник и "
            "необязательный вырез в хвосте. Одна деталь, годится для табличек, "
            "вывесок, маркеров и как «перо» для моделей. Плоскость XY, thickness "
            "по Z; round скругляет кромки настоящим радиусом.",
    example="стрелка = arrow length=120 width=26 head=42 head_width=68 depth=12 round=2",
    params={"length": "полная длина, мм (120)",
            "width": "толщина древка, мм (26)",
            "head": "длина наконечника, мм (0.32 длины)",
            "head_width": "размах наконечника, мм (2.6 ширины)",
            "tail": "глубина выреза в хвосте, мм: 0 — прямой срез, 0.3 ширины — "
                    "оперение стрелы (0)",
            "depth": "толщина по Z, мм (12)",
            "round": "скругление кромок, мм (0)",
            "stand": "поставить вертикально, как табличку (нет)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["length", "width"])
def arrow(a, name):
    length = float(a.num("length", 120.0, minv=1.0))
    width = float(a.num("width", 26.0, minv=0.2))
    head = float(a.num("head", length * 0.32, minv=0.2))
    head_width = float(a.num("head_width", width * 2.6, minv=0.2))
    tail = float(a.num("tail", 0.0, minv=0.0) or 0.0)
    depth = float(a.num("depth", 12.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if head >= length * 0.95:
        raise GeometryError(f"Наконечник {head:g} мм не оставляет древка при длине {length:g} мм.",
                            hint="head ≈ 0.25…0.4 от length.")
    if head_width <= width:
        raise GeometryError(f"Размах наконечника {head_width:g} мм должен быть больше "
                            f"древка {width:g} мм — иначе это не стрелка.",
                            hint="head_width ≈ 2…3 ширины древка.")
    if tail > length * 0.45:
        raise GeometryError("Вырез хвоста не может занимать почти половину стрелки.",
                            hint="tail ≈ 0.2…0.35 от width.")
    x_tail, x_head, x_tip = -length / 2.0, length / 2.0 - head, length / 2.0
    hw, hh = width / 2.0, head_width / 2.0
    pts = [(x_tail, -hw), (x_head, -hw), (x_head, -hh), (x_tip, 0.0),
           (x_head, hh), (x_head, hw), (x_tail, hw)]
    if tail > 1e-6:
        pts.append((x_tail + tail, 0.0))
    solid = _flat(_poly_cross(pts), depth, round_r, min(width, head),
                  size=(length, head_width))
    return make_solid(a.scene, name, _place_glyph(a, solid), a, kind="arrow")


def _placed(a, solid: mf.Manifold) -> mf.Manifold:
    return anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))


def _place_glyph(a, solid: mf.Manifold) -> mf.Manifold:
    """Плоский знак: лежит на полу или стоит, как табличка (stand=true)."""
    if a.boolean("stand", False):
        # фигура лежит в XY; поворот на 90° вокруг X ставит её вертикально
        solid = solid.rotate([90.0, 0.0, 0.0])
    return _placed(a, solid)


# --------------------------------------------------------------------------- #
#  Форма Т
# --------------------------------------------------------------------------- #
@op("tee", aliases=("форма_t", "буква_т", "т", "tee_shape", "t_shape"),
    category="Примитивы",
    summary="Буква Т / тавровая балка: перекладина сверху и ножка снизу, одной "
            "деталью. arm — полная ширина перекладины, bar — её толщина, "
            "stem — ширина ножки, leg — длина ножки под перекладиной. "
            "Стоит на полу, центр по XY.",
    example="тавр = tee arm=90 bar=20 stem=22 leg=60 depth=14 round=2",
    params={"arm": "ширина перекладины, мм (90)",
            "bar": "толщина перекладины, мм (20)",
            "stem": "ширина ножки, мм (20)",
            "leg": "длина ножки под перекладиной, мм (60)",
            "depth": "толщина по Z, мм (14)",
            "round": "скругление кромок, мм (0)",
            "stand": "поставить вертикально, как табличку (нет)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["arm", "leg"])
def tee(a, name):
    arm = float(a.num("arm", 90.0, minv=1.0))
    bar = float(a.num("bar", 20.0, minv=0.4))
    stem = float(a.num("stem", 20.0, minv=0.4))
    leg = float(a.num("leg", 60.0, minv=0.4))
    depth = float(a.num("depth", 14.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if stem >= arm:
        raise GeometryError(f"Ножка {stem:g} мм не уже перекладины {arm:g} мм — это уже не Т.",
                            hint="stem ≈ 0.2…0.35 от arm.")
    if bar >= arm * 1.2:
        raise GeometryError("Перекладина слишком толстая для такой ширины.",
                            hint="bar ≈ 0.15…0.3 от arm.")
    total = bar + leg
    half = total / 2.0
    bar_cs = mf.CrossSection([_profile([(-arm / 2, half - bar), (arm / 2, half - bar),
                                       (arm / 2, half), (-arm / 2, half)])])
    stem_cs = mf.CrossSection([_profile([(-stem / 2, -half), (stem / 2, -half),
                                        (stem / 2, half - bar * 0.5),
                                        (-stem / 2, half - bar * 0.5)])])
    cross = mf.CrossSection.batch_boolean([bar_cs, stem_cs], mf.OpType.Add)
    solid = _flat(cross, depth, round_r, min(stem, bar), size=(arm, total))
    return make_solid(a.scene, name, _place_glyph(a, solid), a, kind="tee")


# --------------------------------------------------------------------------- #
#  Полумесяц
# --------------------------------------------------------------------------- #
@op("crescent", aliases=("полумесяц", "луна", "месяц", "crescent_moon", "moon"),
    category="Примитивы",
    summary="Серп-полумесяц: из круга вычитается второй круг, рога сходятся в "
            "острия. radius — радиус луны, thickness — толщина серпа в самом "
            "широком месте, bite — радиус выкусывающего круга в долях radius: "
            "1.0 — классический месяц (оба круга равны), меньше 1 — крутые "
            "толстые рога, больше 1 — длинные тонкие рога, загнутые дугой. "
            "Рога смотрят в +X.",
    example="луна = crescent radius=50 thickness=18 depth=12 round=1.5\n"
            "полумесяц = crescent radius=40 thickness=8 bite=1.25 depth=8",
    params={"radius": "радиус внешнего круга, мм (50)",
            "thickness": "толщина серпа в широком месте, мм (0.36 радиуса)",
            "bite": "радиус второго круга в долях radius: 1 — классический "
                    "месяц, 0.8 — толстый, 1.3 — тонкие длинные рога (1.0)",
            "depth": "толщина по Z, мм (12)",
            "round": "скругление кромок, мм (0)",
            "segments": "точек по дуге (по размеру)",
            "stand": "поставить вертикально, как табличку (нет)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["radius", "thickness"])
def crescent(a, name):
    radius = float(a.num("radius", 50.0, minv=0.5))
    thickness = float(a.num("thickness", radius * 0.36, minv=0.1))
    bite = float(a.num("bite", 1.0, minv=0.5, maxv=1.6))
    depth = float(a.num("depth", 12.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if thickness >= radius * 1.6:
        raise GeometryError(f"Серп толщиной {thickness:g} мм не влезает в круг "
                            f"радиусом {radius:g} мм.", hint="thickness ≈ 0.15…0.5 от radius.")
    if thickness <= radius * 0.02:
        raise GeometryError("Серп получится бумажным — 2 % радиуса.",
                            hint="thickness ≥ 0.05 от radius.")
    r_bite = bite * radius
    # второй круг сдвинут так, чтобы в широком месте осталось ровно thickness
    d = thickness + r_bite - radius
    if d <= radius * 0.02:
        raise GeometryError("Выкус почти совпал с кругом: серп исчезает.",
                            hint="Увеличьте thickness или уменьшите bite.")
    if d >= radius + r_bite:
        raise GeometryError("Выкус не задевает круг — луна осталась целой.",
                            hint="Уменьшите bite или увеличьте thickness.")
    sides = _segments_for(radius * max(bite, 1.0) * 1.2,
                          a.int("segments", None, minv=24, maxv=512))
    outer = _circle_cs(radius, 0.0, 0.0, sides)
    inner = _circle_cs(r_bite, d, 0.0, sides)
    cross = mf.CrossSection.batch_boolean([outer, inner], mf.OpType.Subtract)
    if cross.is_empty() or cross.area() <= 1e-9:
        raise GeometryError("От круга ничего не осталось: уменьшите thickness.",
                            hint="thickness < radius.")
    solid = _flat(cross, depth, round_r, min(thickness, radius))
    return make_solid(a.scene, name, _place_glyph(a, solid), a, kind="crescent")


# --------------------------------------------------------------------------- #
#  Завиток (мягкое мороженое / «смайлик-какашка»)
# --------------------------------------------------------------------------- #
@op("swirl", aliases=("завиток", "какашка", "мороженое", "рожок", "soft_serve",
                      "curl_pile"),
    category="Примитивы",
    summary="Завиток-наплыв: тело вращения из наклонных колец-наплывов со "
            "спиральной канавкой и заострённой верхушкой — «мягкое мороженое», "
            "куча, спиральный столбик. Стоит на плоском дне, одно тело. "
            "radius — радиус у основания, height — высота, coils — число "
            "наплывов, groove — глубина спиральной канавки.",
    example="куча = swirl radius=42 height=70 coils=3\n"
            "мороженое = swirl radius=34 height=96 coils=4 groove=3",
    params={"radius": "радиус у основания, мм (40)",
            "height": "высота, мм (64)",
            "coils": "число наплывов-колец (3)",
            "groove": "глубина спиральной канавки, мм (0.1 радиуса); 0 — гладкий",
            "taper": "насколько сужается кверху: 0 — цилиндр, 0.85 — конус (0.62)",
            "segments": "точек по кругу (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["radius", "height"])
def swirl(a, name):
    radius = float(a.num("radius", 40.0, minv=1.0))
    height = float(a.num("height", 64.0, minv=1.0))
    coils = int(a.num("coils", 3, minv=1, maxv=12))
    groove = float(a.num("groove", radius * 0.10, minv=0.0))
    taper = float(a.num("taper", 0.62, minv=0.0, maxv=0.92))
    sides = _segments_for(radius, a.int("segments", None, minv=24, maxv=384))
    if groove >= radius * 0.45:
        raise GeometryError("Канавка глубже радиуса: завиток развалится.",
                            hint=f"groove ≤ {radius * 0.35:g} мм.")

    def outer_r(u: float) -> float:
        """Радиус поверхности на высоте u ∈ [0, 1] с наплывами и остриём."""
        base = radius * (1.0 - taper * u)
        wave = 1.0 + 0.16 * math.cos(2 * math.pi * coils * u - math.pi * 0.5)
        tip = min(1.0, (1.0 - u) / 0.10)          # верхушка сходит в точку
        return max(0.0, base * wave * tip)

    # профиль вращения (r, z): плоское дно → волнистая стенка → остриё
    steps = max(48, coils * 18)
    pts = [(0.0, 0.0), (outer_r(0.0), 0.0)]
    for i in range(1, steps + 1):
        u = i / steps
        pts.append((outer_r(u), height * u))
    pts.append((0.0, height))
    prof = np.asarray(pts, dtype=np.float64)
    prof[:, 0] = np.clip(prof[:, 0], 0.0, None)
    solid = mf.Manifold.revolve(mf.CrossSection([prof]), sides)
    solid = ensure_volume(solid, "завитка")

    if groove > 1e-3:
        # Винтовая канавка: труба по поверхности, вычитается из тела.
        # Важно не довести её до верхушки: там радиус стремится к нулю, и
        # труба пропорола бы остриё, оставив «кратер». Поэтому канавка идёт
        # только там, где тело ещё толще 1.8 глубины, и сходит на нет с концов.
        u_lo, u_hi = 0.035, 0.97
        for i in range(1, 200):
            u = 1.0 - i / 200.0
            if outer_r(u) >= groove * 1.8:
                u_hi = min(u_hi, u)
                break
        else:
            u_hi = 0.75
        if u_hi <= u_lo + 0.05:
            raise GeometryError("Канавка не помещается: завиток слишком тонкий.",
                                hint="Уменьшите groove или увеличьте radius.")
        n = max(64, int(coils * 40))
        path = []
        fade = []
        for i in range(n + 1):
            t = i / n
            u = u_lo + (u_hi - u_lo) * t
            ang = 2 * math.pi * coils * t
            r = outer_r(u) + groove * 0.45
            path.append((r * math.cos(ang), r * math.sin(ang), height * u))
            # плавное начало и конец канавки — без «обрыва» на поверхности
            fade.append(min(1.0, t / 0.08 + 0.25, (1.0 - t) / 0.10 + 0.25))
        path = np.asarray(path, dtype=np.float64)
        tube = sweep_solid(path, circle_profile(groove, 10), what="канавки",
                           scale_curve=fade)
        solid = solid - tube
        solid = ensure_volume(solid, "завитка")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="swirl")


# --------------------------------------------------------------------------- #
#  Молния
# --------------------------------------------------------------------------- #
@op("lightning", aliases=("молния", "зигзаг", "thunderbolt", "lightning_bolt"),
    category="Примитивы",
    summary="Молния-зигзаг классического силуэта: два острия и ступенька в "
            "середине. height — высота, width — ширина, depth — толщина по Z. "
            "Ложится остриём вниз, как на дорожном знаке; round скругляет "
            "кромки, чтобы не резало руки.",
    example="молния = lightning height=90 width=44 depth=10 round=1.5",
    params={"height": "высота, мм (90)",
            "width": "ширина по X, мм (0.49 высоты)",
            "depth": "толщина по Z, мм (10)", "round": "скругление кромок, мм (0)",
            "stand": "поставить вертикально, как табличку (нет)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["height", "width"])
def lightning(a, name):
    height = float(a.num("height", 90.0, minv=2.0))
    width = float(a.num("width", height * 0.49, minv=1.0))
    depth = float(a.num("depth", 10.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    # Классический силуэт молнии: 6 вершин, остриё сверху и снизу, ступенька
    # в середине. Координаты — доли габарита, y вверх. Проверено: контур
    # простой (не самопересекается), поэтому extrude и скругление работают.
    shape = [(0.556, 1.000),
             (0.000, 0.400),
             (0.500, 0.400),
             (0.444, 0.000),
             (1.000, 0.600),
             (0.500, 0.600)]
    pts = [(x * width, y * height) for x, y in shape]
    cross = _poly_cross(pts)
    cross = _fit(cross, width, height, "молнии")
    # самый узкий размер — толщина ступеньки (0.2 ширины), по ней и ограничиваем
    solid = _flat(cross, depth, round_r, width * 0.28, size=(width, height))
    return make_solid(a.scene, name, _place_glyph(a, solid), a, kind="lightning")


# --------------------------------------------------------------------------- #
#  Скобка: банан, бровь, стручок
# --------------------------------------------------------------------------- #
@op("banana", aliases=("банан", "бровь", "стручок", "скобка_дуга", "дуга",
                        "brow", "bean_pod"),
    category="Примитивы",
    summary="Изогнутая скобка-дуга с утолщением в середине: банан, бровь, "
            "бобовый стручок, ручка-скоба. Настоящая развёртка эллипса по дуге, "
            "концы сходят на нет. length — длина по дуге, bend — полный угол "
            "дуги, thick — толщина в середине, flat — приплюснутость сечения "
            "(1 — круглое, 0.5 — плоская бровь). Концы загнуты вверх.",
    example="банан = banana length=120 bend=110 thick=28 flat=0.75\n"
            "бровь = banana length=80 bend=60 thick=12 flat=0.55 taper=0.2",
    params={"length": "длина по дуге, мм (120)",
            "bend": "полный угол дуги, °: 0 — прямая, 180 — полукольцо (90)",
            "thick": "толщина в середине, мм (26)",
            "flat": "высота сечения к ширине: 1 — круглое, 0.5 — плоское (0.72)",
            "taper": "толщина кончиков в долях от середины (0.32)",
            "segments": "точек по дуге (по размеру)",
            "sides": "точек в сечении (по размеру)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["length", "bend"])
def banana(a, name):
    length = float(a.num("length", 120.0, minv=2.0))
    bend = float(a.num("bend", 90.0, minv=0.0, maxv=340.0))
    thick = float(a.num("thick", 26.0, minv=0.4))
    flat = float(a.num("flat", 0.72, minv=0.15, maxv=1.0))
    taper = float(a.num("taper", 0.32, minv=0.03, maxv=0.95))
    # полная длина: концы закруглены, поэтому дуга короче габарита на толщину
    # закруглённых кончиков (они сужены в taper раз)
    arc_len = max(thick * 1.2, length - thick * taper)
    if bend < 1.0:
        # почти прямая: дуга радиусом в километры только портит точность.
        # Точек всё равно много — иначе сужение кончиков (scale_curve)
        # применилось бы к обоим концам сразу, и брус вышел бы тонким.
        xs = np.linspace(-arc_len / 2, arc_len / 2, 17)
        path = np.stack([xs, np.zeros_like(xs), np.zeros_like(xs)], axis=1)
    else:
        ang = math.radians(bend)
        r_arc = arc_len / ang
        n = max(8, int(a.num("segments", 0, minv=0, maxv=512) or 0) or int(24 + bend / 4))
        n = min(n, 256)
        theta = np.linspace(-ang / 2, ang / 2, n)
        path = np.stack([r_arc * np.sin(theta), np.zeros_like(theta),
                         r_arc * (1.0 - np.cos(theta))], axis=1)
    prof = ellipse_profile(thick, thick * flat,
                           _segments_for(max(thick, 1.0),
                                         a.int("sides", None, minv=8, maxv=128), lo=12, hi=128))
    # толщина по длине: тонкие кончики, полная середина
    k = np.linspace(0.0, 1.0, 9)
    curve = list(taper + (1.0 - taper) * np.sin(np.pi * k) ** 0.55)
    solid = sweep_solid(path, prof, what="скобки", scale_curve=curve, round_caps=1.0)
    solid = ensure_volume(solid, "скобки")
    return make_solid(a.scene, name, _placed(a, solid), a, kind="banana")


# --------------------------------------------------------------------------- #
#  Форма Y (рогатка)
# --------------------------------------------------------------------------- #
@op("yoke", aliases=("форма_y", "рогатка", "игрек", "y_shape", "slingshot"),
    category="Примитивы",
    summary="Буква Y / рогатка: ствол снизу, две ветви вверх и в стороны, "
            "круглые концы. height — высота, spread — расстояние между верхними "
            "концами, arm — толщина ветвей, fork — на какой доле высоты "
            "расходятся ветви. Стоит на плоском дне.",
    example="рогатка = yoke height=110 spread=64 arm=16 fork=0.38 depth=14 round=2",
    params={"height": "высота до концов ветвей, мм (110)",
            "spread": "расстояние между концами ветвей, мм (64)",
            "arm": "толщина ветвей и ствола, мм (16)",
            "fork": "доля высоты, где начинается развилка: 0.2…0.7 (0.38)",
            "depth": "толщина по Z, мм (14)",
            "round": "скругление кромок, мм (0)",
            "stand": "поставить вертикально, как табличку (нет)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["height", "spread"])
def yoke(a, name):
    height = float(a.num("height", 110.0, minv=2.0))
    spread = float(a.num("spread", 64.0, minv=0.0))
    arm = float(a.num("arm", 16.0, minv=0.4))
    fork = float(a.num("fork", 0.38, minv=0.1, maxv=0.9))
    depth = float(a.num("depth", 14.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    if spread <= arm * 1.2:
        raise GeometryError(f"Ветви не разошлись: spread {spread:g} мм при толщине {arm:g} мм.",
                            hint="spread ≈ 3…6 толщин ветви.")
    if height * (1.0 - fork) < arm * 1.5:
        raise GeometryError("Развилка слишком высоко: ветвям не хватает длины.",
                            hint="fork ≈ 0.3…0.5.")
    crotch = (0.0, height * fork)
    left = (-spread / 2.0, height)
    right = (spread / 2.0, height)
    stem = _stadium((0.0, -arm), crotch, arm)
    l_arm = _stadium(crotch, left, arm)
    r_arm = _stadium(crotch, right, arm)
    cross = mf.CrossSection.batch_boolean(
        [mf.CrossSection([stem]), mf.CrossSection([l_arm]), mf.CrossSection([r_arm])],
        mf.OpType.Add)
    # плоское дно: отрезаем всё, что ниже y = 0
    floor = mf.CrossSection([_profile([(-height * 3, 0.0), (height * 3, 0.0),
                                       (height * 3, height * 3), (-height * 3, height * 3)])])
    cross = mf.CrossSection.batch_boolean([cross, floor], mf.OpType.Intersect)
    if cross.is_empty() or cross.area() <= 1e-9:
        raise GeometryError("Форма Y получилась пустой.",
                            hint="Проверьте height, spread и arm.")
    solid = _flat(cross, depth, round_r, arm, size=(spread + arm, height))
    return make_solid(a.scene, name, _place_glyph(a, solid), a, kind="yoke")

