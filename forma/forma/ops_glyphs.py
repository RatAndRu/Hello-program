"""Знаки и фигуры-символы: стрелка, Т, полумесяц, завиток, молния, скобка, Y.

Это не буквы шрифта, а **тела**: каждую фигуру можно резать, склеивать,
ставить на пол, печатать и проверять ядром. Плоские фигуры сначала строятся
в XY, затем по умолчанию поворачиваются в XZ лицом −Y (их толщина идёт по Y);
`round` — настоящее скругление кромок
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
from .ops import anchor, make_solid, op, stand_flat_sign
from .ops_shapes import _cross, _profile, ensure_volume
from .shape_features import hollow_cross, rect_between


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
             width: float, arc_pts: int = 16, exact: bool = True) -> np.ndarray:
    """Стадион между точками; exact сохраняет экстремумы круглых торцов.

    Старые овальные ветви используют exact=False: их последующая подгонка
    намеренно даёт эллиптические торцы и не должна подменяться капсулой.
    """
    a = np.asarray(p0, dtype=np.float64)
    b = np.asarray(p1, dtype=np.float64)
    d = b - a
    length = float(np.linalg.norm(d))
    if length < 1e-9:
        raise GeometryError("Концы бруса совпали.")
    d = d / length
    n = np.array([-d[1], d[0]])
    r = float(width) / 2.0
    if not exact:
        phi_a = np.linspace(-math.pi / 2, math.pi / 2, arc_pts)
        phi_b = np.linspace(math.pi / 2, 3 * math.pi / 2, arc_pts)
    else:
        steps = max(4, int(arc_pts))
        if steps % 2:
            steps += 1

        def angles(lo, hi):
            values = list(np.linspace(lo, hi, steps + 1))
            # У наклонной капсулы габарит достигается не обязательно в
            # середине локальной дуги: добавляем мировые ±X и ±Y.
            for base in (math.atan2(n[0], d[0]), math.atan2(n[1], d[1])):
                for k in range(-4, 5):
                    t = base + k * math.pi
                    if lo + 1e-10 < t < hi - 1e-10:
                        values.append(t)
            return np.asarray(sorted(set(round(float(t), 12) for t in values)))

        phi_a = angles(-math.pi / 2, math.pi / 2)
        phi_b = angles(math.pi / 2, 3 * math.pi / 2)
    pts = [b + r * (math.cos(t) * d + math.sin(t) * n) for t in phi_a]
    pts += [a + r * (math.cos(t) * d + math.sin(t) * n) for t in phi_b]
    return np.asarray(pts, dtype=np.float64)


def _ellipse_between(p0: tuple[float, float], p1: tuple[float, float],
                     width: float, segments: int = 96) -> np.ndarray:
    """Цельный эллипс между двумя остриями, а не капсула с другой сеткой."""
    a, b = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
    delta = b - a
    length = float(np.linalg.norm(delta))
    if length < 1e-9:
        raise GeometryError("Концы овальной ветви совпали.")
    direction = delta / length
    normal = np.asarray([-direction[1], direction[0]])
    center = (a + b) / 2.0
    points = []
    for t in np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False):
        points.append(center + direction * (length * 0.5 * math.cos(t))
                      + normal * (width * 0.5 * math.sin(t)))
    return np.asarray(points, dtype=np.float64)


def _segments_for(radius: float, asked: int | None, lo: int = 48, hi: int = 512) -> int:
    got = int(limit_segments(asked, max(radius, 1e-3), tolerance=FINENESS_MM, max_n=hi))
    return int(max(lo, min(hi, got)))


# --------------------------------------------------------------------------- #
#  Стрелка
# --------------------------------------------------------------------------- #
@op("arrow", aliases=("стрелка", "стрела", "указатель", "arrow_sign"),
    category="Примитивы",
    summary="Стрелка остриём +X. head_width=width делает наконечник без "
            "выступающих краёв; tail — "
            "отдельный V-вырез хвоста. Одна деталь с настоящей толщиной; "
            "wall>0 делает сквозную формочку по всему контуру.",
    example="стрелка = arrow length=120 width=26 head=42 head_width=68 depth=12 round=2\n"
            "тонкая = arrow length=120 width=26 head_width=26",
    params={"length": "полная длина, мм (120)",
            "width": "толщина древка, мм (26)",
            "head": "длина наконечника, мм (0.32 длины)",
            "head_width": "размах наконечника; может быть равен width",
            "tail": "глубина V-выреза в хвосте, мм: 0 — прямой срез (0)",
            "depth": "толщина по глубине, мм (12); у стоящего знака — по Y",
            "round": "скругление кромок, мм (0)",
            "wall": "стенка сквозной формочки, мм; 0 — сплошная стрелка (0)",
            "plane": "фронт — стоит лицом к зрителю, плашмя — лежит лицом вверх — «фронт»",
            "stand": "то же, что plane=фронт: да — стоит, нет — лежит (да)",
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
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
    if head >= length * 0.95:
        raise GeometryError(f"Наконечник {head:g} мм не оставляет древка при длине {length:g} мм.",
                            hint="head ≈ 0.25…0.4 от length.")
    if head_width < width - 1e-9:
        raise GeometryError("Наконечник: head_width не может быть меньше древка width.",
                            hint="Для наконечника без выступов задайте head_width=width.")
    if tail > length * 0.45:
        raise GeometryError("Вырез хвоста не может занимать почти половину стрелки.",
                            hint="tail ≈ 0.2…0.35 от width.")
    x_tail, x_head, x_tip = -length / 2.0, length / 2.0 - head, length / 2.0
    hw, hh = width / 2.0, head_width / 2.0
    pts = [(x_tail, -hw), (x_head, -hw)]
    if hh > hw + 1e-9:
        pts.append((x_head, -hh))
    pts.append((x_tip, 0.0))
    if hh > hw + 1e-9:
        pts.append((x_head, hh))
    pts += [(x_head, hw), (x_tail, hw)]
    if tail > 1e-6:
        pts.append((x_tail + tail, 0.0))
    cross = hollow_cross(_poly_cross(pts), wall, "стрелка")
    overall_height = head_width
    solid = _flat(cross, depth, round_r, wall if wall > 1e-6 else min(width, head),
                  size=(length, overall_height))
    return make_solid(a.scene, name, _place_glyph(a, solid), a, kind="arrow")


def _placed(a, solid: mf.Manifold) -> mf.Manifold:
    return anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))


def _place_glyph(a, solid: mf.Manifold) -> mf.Manifold:
    """Плоский знак по правилу проекта: стоит лицом в −Y (табличка).

    ``plane=плашмя`` (или ``stand=нет``) кладёт знак на пол лицом вверх.
    """
    return _placed(a, stand_flat_sign(a, solid))


# --------------------------------------------------------------------------- #
#  Форма Т
# --------------------------------------------------------------------------- #
@op("tee", aliases=("форма_t", "буква_т", "т", "tee_shape", "t_shape"),
    category="Примитивы",
    summary="Буква Т / тавровая балка: перекладина сверху и ножка снизу, одной "
            "деталью. arm — полная ширина перекладины, bar — её толщина, "
            "stem — ширина ножки, leg — длина ножки под перекладиной. "
            "Стоит в XZ лицом −Y: перекладина сверху (+Z), ножка вниз (−Z), "
            "толщина depth по Y; опирается на нижний срез ножки. shape=бруски, "
            "овалы или капсулы: овалы — цельные эллиптические ветви, капсулы "
            "имеют прямые стороны и истинные полукруглые торцы.",
    example="тавр = tee arm=90 bar=20 stem=22 leg=60 depth=14 round=2",
    params={"arm": "ширина перекладины, мм (90)",
            "bar": "толщина перекладины, мм (20)",
            "stem": "ширина ножки, мм (20)",
            "leg": "длина ножки под перекладиной, мм (60)",
            "shape": "бруски — плоские торцы; овалы — эллиптические; "
                     "капсулы — прямые стороны и полукруглые торцы",
            "depth": "толщина по глубине, мм (14); у стоящего знака — по Y",
            "round": "скругление кромок, мм (0)",
            "plane": "фронт — стоит лицом к зрителю, плашмя — лежит лицом вверх — «фронт»",
            "stand": "то же, что plane=фронт: да — стоит, нет — лежит (да)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["arm", "leg"])
def tee(a, name):
    arm = float(a.num("arm", 90.0, minv=1.0))
    bar = float(a.num("bar", 20.0, minv=0.4))
    stem = float(a.num("stem", 20.0, minv=0.4))
    leg = float(a.num("leg", 60.0, minv=0.4))
    depth = float(a.num("depth", 14.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    shape = (a.text("shape", "бруски") or "бруски").strip().lower()
    if shape in ("капсула", "капсулы", "круглые", "capsule", "capsules"):
        shape = "капсулы"
    elif shape in ("овал", "овалы", "овальные", "эллипс", "ellipse", "oval"):
        shape = "овалы"
    elif shape in ("брусок", "бруски", "прямоугольные", "box", "rect"):
        shape = "бруски"
    else:
        raise GeometryError("tee: shape=бруски, овалы или капсулы.")
    if stem >= arm:
        raise GeometryError(f"Ножка {stem:g} мм не уже перекладины {arm:g} мм — это уже не Т.",
                            hint="stem ≈ 0.2…0.35 от arm.")
    if bar >= arm * 1.2:
        raise GeometryError("Перекладина слишком толстая для такой ширины.",
                            hint="bar ≈ 0.15…0.3 от arm.")
    total = bar + leg
    half = total / 2.0
    if shape in ("капсулы", "овалы"):
        if shape == "овалы":
            bar_cs = mf.CrossSection([_ellipse_between(
                (-arm / 2, half - bar / 2), (arm / 2, half - bar / 2), bar)])
            stem_cs = mf.CrossSection([_ellipse_between(
                (0.0, -half), (0.0, half - bar * 0.5), stem)])
        else:
            bar_cs = mf.CrossSection([_stadium((-arm / 2 + bar / 2, half - bar / 2),
                                              (arm / 2 - bar / 2, half - bar / 2), bar)])
            stem_cs = mf.CrossSection([_stadium((0.0, -half + stem / 2),
                                               (0.0, half - bar * 0.5), stem)])
        # Капсульная ножка не должна проходить сквозь перекладину, даже если
        # stem>bar. Подрезаем её чуть выше нижней плоскости перекладины:
        # остаётся надёжный захлёст, а верхняя плоскость остаётся ровной.
        if shape == "капсулы":
            joint = half - bar + min(0.05, bar * 0.1)
            clip = mf.CrossSection([_profile([(-stem, -half - 1.0), (stem, -half - 1.0),
                                             (stem, joint), (-stem, joint)])])
            stem_cs = mf.CrossSection.batch_boolean([stem_cs, clip], mf.OpType.Intersect)
    else:
        bar_cs = mf.CrossSection([_profile([(-arm / 2, half - bar), (arm / 2, half - bar),
                                           (arm / 2, half), (-arm / 2, half)])])
        stem_cs = mf.CrossSection([_profile([(-stem / 2, -half), (stem / 2, -half),
                                            (stem / 2, half - bar * 0.5),
                                            (-stem / 2, half - bar * 0.5)])])
    cross = mf.CrossSection.batch_boolean([bar_cs, stem_cs], mf.OpType.Add)
    fit_size = (arm, total) if shape != "капсулы" or round_r > 1e-6 else None
    solid = _flat(cross, depth, round_r, min(stem, bar), size=fit_size)
    out = make_solid(a.scene, name, _place_glyph(a, solid), a, kind="tee")
    out.meta["branch_shape"] = shape
    return out


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
            "Стоит в XZ лицом −Y: материал смещён в −X, вырез и рога — в +X, "
            "толщина depth по Y. wall>0 делает сквозную формочку по контуру "
            "серпа с равномерной стенкой.",
    example="луна = crescent radius=50 thickness=18 depth=12 round=1.5\n"
            "полумесяц = crescent radius=40 thickness=8 bite=1.25 depth=8",
    params={"radius": "радиус внешнего круга, мм (50)",
            "thickness": "толщина серпа в широком месте, мм (0.36 радиуса)",
            "bite": "радиус второго круга в долях radius: 1 — классический "
                    "месяц, 0.8 — толстый, 1.3 — тонкие длинные рога (1.0)",
            "depth": "толщина по глубине, мм (12); у стоящего знака — по Y",
            "round": "скругление кромок, мм (0)",
            "wall": "стенка сквозной формочки, мм; 0 — сплошной серп (0)",
            "segments": "точек по дуге (по размеру)",
            "plane": "фронт — стоит лицом к зрителю, плашмя — лежит лицом вверх — «фронт»",
            "stand": "то же, что plane=фронт: да — стоит, нет — лежит (да)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["radius", "thickness"])
def crescent(a, name):
    radius = float(a.num("radius", 50.0, minv=0.5))
    thickness = float(a.num("thickness", radius * 0.36, minv=0.1))
    bite = float(a.num("bite", 1.0, minv=0.5, maxv=1.6))
    depth = float(a.num("depth", 12.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
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
    cross = hollow_cross(cross, wall, "луна")
    thin = min(thickness, radius) if wall <= 1e-6 else wall
    solid = _flat(cross, depth, round_r, thin)
    return make_solid(a.scene, name, _place_glyph(a, solid), a, kind="crescent")


# --------------------------------------------------------------------------- #
#  Завиток (мягкое мороженое / «смайлик-какашка»)
# --------------------------------------------------------------------------- #
@op("swirl", aliases=("завиток", "какашка", "мороженое", "рожок", "soft_serve",
                      "curl_pile", "свиной_хвостик"),
    category="Примитивы",
    summary="Непрерывный завиток: одна гибкая труба идёт по трёхмерной "
            "спирали, как свиной хвостик или мягкое мороженое. Это не стопка "
            "дисков: витки плавно сужаются и заканчиваются остриём. merge "
            "сращивает витки общим телом, base скрывает начало в плоском "
            "основании, как у крема. root_d независимо сужает самый нижний "
            "конец, не меняя основной диаметр wire.",
    example="хвостик = swirl radius=40 height=64 coils=3 wire=16 taper=0.25\n"
            "мороженое = swirl radius=34 height=96 coils=4 wire=20 taper=0.7",
    params={"radius": "наружный радиус основания, мм (40)",
            "height": "высота до острия, мм (64)",
            "coils": "число непрерывных витков 1…12 (3)",
            "wire": "основной диаметр трубы витка, мм (авто, без касания витков)",
            "root_d": "диаметр самого начала витка, мм (= wire); меньше — тонкий скрытый конец",
            "taper": "сужение радиуса спирали 0…0.92 (0.62)",
            "merge": "да — общее тело без промежутков между витками; "
                     "разрешает wire не меньше шага (нет)",
            "base": "да — плоское основание высотой wire, полностью скрывающее "
                    "начало витка (нет)",
            "segments": "сегментов сечения трубы 12…64 (20)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["radius", "height"])
def swirl(a, name):
    radius = float(a.num("radius", 40.0, minv=2.0, maxv=5000.0))
    height = float(a.num("height", 64.0, minv=3.0, maxv=10000.0))
    coils = int(a.num("coils", 3, minv=1, maxv=12) or 3)
    merge = a.boolean("merge", False)
    base = a.boolean("base", False)
    pitch = height / coils
    auto_wire = min(radius * 0.42, pitch * (1.04 if merge else 0.78))
    wire = float(a.num("wire", auto_wire, minv=0.2, maxv=radius * 1.2))
    root_d = float(a.num("root_d", wire, minv=0.1, maxv=wire))
    taper = float(a.num("taper", 0.62, minv=0.0, maxv=0.92))
    sides = int(a.num("segments", 20, minv=12, maxv=64) or 20)
    if wire >= pitch * 0.96 and not merge:
        raise GeometryError("Труба завитка слишком толстая: соседние витки сольются.",
                            hint=f"Задайте wire меньше {pitch * 0.96:g} мм или merge=да.")
    if base and wire >= height:
        raise GeometryError("Для плоского основания height должен быть больше wire.")
    if wire >= radius * 1.15:
        raise GeometryError("Труба толще основания завитка.",
                            hint="Уменьшите wire или увеличьте radius.")

    base_r = radius - wire / 2.0
    base_tube = wire / 2.0
    root_tube = root_d / 2.0
    root_ramp = 0.12
    n = max(96, coils * 56)
    path: list[tuple[float, float, float]] = []
    scales: list[float] = []
    for i in range(n + 1):
        u = i / n
        angle = 2.0 * math.pi * coils * u
        center_r = base_r * (1.0 - taper * u)
        # Последняя часть витка мягко сворачивается к оси и образует остриё,
        # а не обрезанный цилиндр на вершине.
        if u > 0.78:
            q = (u - 0.78) / 0.22
            center_r *= 1.0 - (q * q * (3.0 - 2.0 * q))
        if u < root_ramp:
            q = u / root_ramp
            q = q * q * (3.0 - 2.0 * q)
            tube_r = root_tube + (base_tube - root_tube) * q
        else:
            tube_r = base_tube * ((1.0 - u) / (1.0 - root_ramp)) ** 0.9
        tube_r = max(0.015, tube_r)
        # Центральная линия не опускается вслед за тонким root_d: начало
        # остаётся внутри нижнего витка, а толстая часть не торчит под ним.
        z = base_tube + (height - base_tube) * u
        path.append((center_r * math.cos(angle), center_r * math.sin(angle), z))
        scales.append(tube_r)
    solid = sweep_solid(np.asarray(path, dtype=np.float64), circle_profile(1.0, sides),
                        what="непрерывного завитка", scale_curve=scales)
    if merge:
        # Общая сужающаяся сердцевина пересекает трубу на каждом шаге и
        # закрывает сквозные промежутки, оставляя снаружи спиральный рельеф.
        profile = [(0.0, 0.0)]
        for i in range(0, n + 1, max(1, n // 48)):
            cx, cy, z = path[i]
            rr = math.hypot(cx, cy) + scales[i] * 0.65
            profile.append((max(0.005, rr), max(0.0, z)))
        if profile[-1][1] < height:
            cx, cy, z = path[-1]
            profile.append((max(0.005, math.hypot(cx, cy) + scales[-1] * 0.65), height))
        profile.append((0.0, height))
        core = mf.Manifold.revolve(mf.CrossSection([np.asarray(profile, dtype=np.float64)]),
                                   max(48, sides * 3))
        solid = solid + core
    if base:
        # Начальное сечение лежит между z=0 и z=wire целиком внутри этого
        # цилиндра: снаружи остаётся ровная площадка без хвостика.
        pad = mf.Manifold.cylinder(wire, radius, radius, max(48, sides * 3))
        solid = solid + pad
    solid = ensure_volume(solid, "завитка")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="swirl")
    out.notes.append(f"непрерывная спираль: {coils} витков, труба ø{wire:g} мм, "
                     f"начало ø{root_d:g} мм, merge={'да' if merge else 'нет'}, "
                     f"base={'да' if base else 'нет'}")
    return out


# --------------------------------------------------------------------------- #
#  Молния
# --------------------------------------------------------------------------- #
@op("lightning", aliases=("молния", "зигзаг", "thunderbolt", "lightning_bolt"),
    category="Примитивы",
    summary="Молния-зигзаг классического силуэта: два острия и ступенька в "
            "середине. По умолчанию стоит в XZ лицом −Y: height — высота по Z, "
            "width — ширина по X, depth — толщина по Y. Нижнее остриё смотрит "
            "в −Z; round скругляет кромки, чтобы не резало руки.",
    example="молния = lightning height=90 width=44 depth=10 round=1.5\n"
            "формочка = lightning height=90 width=44 depth=10 wall=3",
    params={"height": "высота, мм (90)",
            "width": "ширина по X, мм (0.49 высоты)",
            "depth": "толщина по глубине, мм (10); у стоящего знака — по Y",
            "round": "скругление кромок, мм (0)",
            "wall": "стенка сквозной формочки/рамки, мм; 0 — сплошная (0)",
            "plane": "фронт — стоит лицом к зрителю, плашмя — лежит лицом вверх — «фронт»",
            "stand": "то же, что plane=фронт: да — стоит, нет — лежит (да)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["height", "width"])
def lightning(a, name):
    height = float(a.num("height", 90.0, minv=2.0))
    width = float(a.num("width", height * 0.49, minv=1.0))
    depth = float(a.num("depth", 10.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    wall = float(a.num("wall", 0.0, minv=0.0) or 0.0)
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
    cross = hollow_cross(cross, wall, "молния")
    # самый узкий размер — толщина ступеньки (0.2 ширины), по ней и ограничиваем
    thin = min(width * 0.28, wall) if wall > 1e-6 else width * 0.28
    solid = _flat(cross, depth, round_r, thin, size=(width, height))
    return make_solid(a.scene, name, _place_glyph(a, solid), a, kind="lightning")


# --------------------------------------------------------------------------- #
#  Скобка: банан, бровь, стручок
# --------------------------------------------------------------------------- #
@op("banana", aliases=("банан", "бровь", "стручок", "скобка_дуга",
                        "brow", "bean_pod"),
    category="Примитивы",
    summary="Изогнутая скобка-дуга с утолщением в середине: банан, бровь, "
            "бобовый стручок, ручка-скоба. Настоящая развёртка эллипса по дуге, "
            "концы сходят на нет. length — длина по дуге, bend — полный угол "
            "дуги, thick — толщина в середине, flat — приплюснутость сечения "
            "(1 — круглое, 0.5 — плоская бровь). Дуга лежит в XZ: её середина "
            "приподнята в +Z, концы находятся по ±X на одной высоте.",
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
    summary="Буква Y / рогатка с одинаковыми ветвями. shape=капсулы — прямые "
            "стороны и истинные полукруглые торцы; овалы — цельные эллиптические "
            "ветви; бруски — плоские торцы. smooth округляет внутренние стыки "
            "развилки, round — кромки толщины.",
    example="рогатка = yoke height=110 spread=64 arm=16 fork=0.38 depth=14 round=2\n"
            "игрек = yoke height=110 spread=64 arm=16 shape=бруски",
    params={"height": "высота до концов ветвей, мм (110)",
            "spread": "размах без толщины ветви; полный габарит spread+arm, мм (64)",
            "arm": "толщина ветвей и ствола, мм (16)",
            "shape": "капсулы — полукруглые торцы; овалы — эллиптические; "
                     "бруски/параллелепипеды — плоские",
            "fork": "доля высоты, где начинается развилка: 0.2…0.7 (0.38)",
            "depth": "толщина по глубине, мм (14); у стоящего знака — по Y",
            "round": "скругление кромок, мм (0)",
            "smooth": "сглаживание внутренних стыков ветвей 0…4 (0)",
            "plane": "фронт — стоит лицом к зрителю, плашмя — лежит лицом вверх — «фронт»",
            "stand": "то же, что plane=фронт: да — стоит, нет — лежит (да)",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["height", "spread"])
def yoke(a, name):
    height = float(a.num("height", 110.0, minv=2.0))
    spread = float(a.num("spread", 64.0, minv=0.0))
    arm = float(a.num("arm", 16.0, minv=0.4))
    fork = float(a.num("fork", 0.38, minv=0.1, maxv=0.9))
    depth = float(a.num("depth", 14.0, minv=0.1))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    smooth = int(a.num("smooth", 0, minv=0, maxv=4) or 0)
    shape = (a.text("shape") or "капсулы").strip().lower()
    if shape in ("капсула", "капсулы", "capsule", "capsules", "круглые"):
        shape = "капсулы"
    elif shape in ("овал", "овалы", "овальные", "эллипс", "ellipse", "oval"):
        shape = "овалы"
    elif shape in ("бруски", "брусок", "параллелепипеды", "прямоугольные",
                   "box", "rect", "плоские"):
        shape = "бруски"
    else:
        raise GeometryError("yoke: shape=капсулы, овалы или бруски.")
    if spread <= arm * 1.2:
        raise GeometryError(f"Ветви не разошлись: spread {spread:g} мм при толщине {arm:g} мм.",
                            hint="spread ≈ 3…6 толщин ветви.")
    if height * (1.0 - fork) < arm * 1.5:
        raise GeometryError("Развилка слишком высоко: ветвям не хватает длины.",
                            hint="fork ≈ 0.3…0.5.")
    crotch = (0.0, height * fork)
    if shape == "овалы":
        # Три настоящих эллипса, а не иная дискретизация капсул. Ствол и
        # ветви заходят друг в друга выше/ниже развилки: соединение объёмное,
        # а не контакт трёх остриёв в одной точке.
        left = (-(spread + arm) / 2.0, height)
        right = ((spread + arm) / 2.0, height)
        inner = (0.0, crotch[1] - arm * 0.75)
        stem = _ellipse_between((0.0, 0.0), (0.0, crotch[1] + arm * 0.75), arm)
        l_arm = _ellipse_between(inner, left, arm)
        r_arm = _ellipse_between(inner, right, arm)
    elif shape == "капсулы":
        # Центры торцевых дуг отступают на arm/2: габарит остаётся height,
        # а все три наружных окончания одинаково круглые.
        left = (-spread / 2.0, height - arm / 2.0)
        right = (spread / 2.0, height - arm / 2.0)
        stem = _stadium((0.0, arm / 2.0), crotch, arm)
        l_arm = _stadium(crotch, left, arm)
        r_arm = _stadium(crotch, right, arm)
    else:
        left = (-spread / 2.0, height)
        right = (spread / 2.0, height)
        stem = rect_between((0.0, 0.0), crotch, arm)
        l_arm = rect_between(crotch, left, arm)
        r_arm = rect_between(crotch, right, arm)
    cross = mf.CrossSection.batch_boolean(
        [mf.CrossSection([stem]), mf.CrossSection([l_arm]), mf.CrossSection([r_arm])],
        mf.OpType.Add)
    if smooth > 0:
        # Морфологическое замыкание заполняет только острые внутренние
        # пазухи развилки; наружные торцы и толщина ветвей сохраняются.
        rr = arm * 0.35 * smooth / 4.0
        cross = cross.offset(rr, mf.JoinType.Round, 2.0, 20)
        cross = cross.offset(-rr, mf.JoinType.Round, 2.0, 20)
    if cross.is_empty() or cross.area() <= 1e-9:
        raise GeometryError("Форма Y получилась пустой.",
                            hint="Проверьте height, spread и arm.")
    fit_size = (spread + arm, height) if shape != "капсулы" or round_r > 1e-6 else None
    solid = _flat(cross, depth, round_r, arm, size=fit_size)
    out = make_solid(a.scene, name, _place_glyph(a, solid), a, kind="yoke")
    out.meta["branch_shape"] = shape
    return out

