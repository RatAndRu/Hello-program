"""Колонны, дуговые треугольные призмы и конструкционный профиль 2020."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile, loft_solid
from .ops import anchor, make_solid, op
from .shape_features import apply_smooth


def _placed(a, solid: mf.Manifold) -> mf.Manifold:
    return anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))


def _one(solid: mf.Manifold, what: str) -> mf.Manifold:
    if solid.is_empty() or solid.volume() <= 1e-7 or str(solid.status()) != "Error.NoError":
        raise GeometryError(f"{what}: не удалось построить замкнутое тело.")
    if len(solid.decompose()) != 1:
        raise GeometryError(f"{what}: деталь распалась на части.")
    return solid


def _choice(raw: str, table: dict[str, str], what: str) -> str:
    value = table.get((raw or "").strip().lower())
    if value is None:
        raise GeometryError(f"{what}: неизвестное значение «{raw}». "
                            + "Доступно: " + ", ".join(dict.fromkeys(table.values())) + ".")
    return value


def _section(width: float, depth: float, kind: str, segments: int = 48) -> np.ndarray:
    if kind == "цилиндр":
        return np.asarray(circle_profile(width / 2.0, segments), dtype=float)
    x, y = width / 2.0, depth / 2.0
    return np.asarray([(-x, -y), (x, -y), (x, y), (-x, y)], dtype=float)


def _prism_section(width: float, depth: float, height: float, kind: str,
                   segments: int = 48) -> mf.Manifold:
    return mf.CrossSection([_section(width, depth, kind, segments).tolist()]).extrude(height)


# --------------------------------------------------------------------------- #
#  Колонна
# --------------------------------------------------------------------------- #
@op("column", aliases=("колонна", "колонна_песочные", "column_hourglass"),
    category="Примитивы",
    summary="Колонна с нижней площадкой и верхним бортиком. form=ровная, "
            "песочные (параболическое сужение посередине) или конус; section — "
            "цилиндр или брусок. Высота включает площадку и бортик.",
    example="колонна = column height=180 width=42 form=песочные waist=0.55 "
            "section=цилиндр base=да base_size=72 base_h=12 rim=8 rim_h=10\n"
            "стойка = column height=150 width=36 depth=28 form=конус taper=0.45 "
            "section=брусок smooth=1 at=[130,0,0]",
    params={"height": "полная высота с площадкой и бортиком, мм (180)",
            "width": "диаметр цилиндра или ширина бруска X, мм (42)",
            "depth": "глубина бруска Y; у цилиндра не используется (42)",
            "form": "ровная, песочные или конус",
            "waist": "доля ширины в середине песочных часов 0.2…1 (0.55)",
            "taper": "сужение верха конуса 0…0.85 (0.35)",
            "section": "сечение: цилиндр или брусок",
            "base": "нижняя площадка да/нет (да)",
            "base_size": "диаметр/сторона нижней площадки, мм (72)",
            "base_h": "высота нижней площадки, мм (12)",
            "rim": "вылет верхнего бортика над стойкой; 0 — без бортика, мм (8)",
            "rim_h": "высота верхнего бортика, мм (10)",
            "smooth": "уровни Loop-сглаживания 0…4 (0)",
            "segments": "сегментов цилиндра (48)",
            "at": "положение [x,y,z]", "center": "центрировать по габариту"})
def column(a, name):
    height = float(a.num("height", 180.0, minv=10.0, maxv=10000.0))
    width = float(a.num("width", 42.0, minv=1.0, maxv=5000.0))
    depth = float(a.num("depth", width, minv=1.0, maxv=5000.0))
    form = _choice(a.text("form", "ровная"),
                   {"ровная": "ровная", "прямая": "ровная", "классическая": "ровная",
                    "песочные": "песочные", "парабола": "песочные", "параболическая": "песочные",
                    "конус": "конус", "сужающаяся": "конус", "сужение": "конус"}, "column.form")
    section = _choice(a.text("section", "цилиндр"),
                      {"цилиндр": "цилиндр", "круг": "цилиндр", "брусок": "брусок",
                       "параллелепипед": "брусок", "квадрат": "брусок"}, "column.section")
    waist = float(a.num("waist", 0.55, minv=0.2, maxv=1.0))
    taper = float(a.num("taper", 0.35, minv=0.0, maxv=0.85) or 0.0)
    base = a.boolean("base", True)
    base_size = float(a.num("base_size", 72.0, minv=1.0, maxv=5000.0))
    base_h = float(a.num("base_h", 12.0, minv=0.0, maxv=5000.0) or 0.0) if base else 0.0
    rim = float(a.num("rim", 8.0, minv=0.0, maxv=1000.0) or 0.0)
    rim_h = float(a.num("rim_h", 10.0, minv=0.0, maxv=5000.0) or 0.0) if rim > 0 else 0.0
    if base_h + rim_h >= height - 1.0:
        raise GeometryError("Площадка и бортик не оставляют высоты самой колонне.")
    segments = int(a.int("segments", 48, minv=12, maxv=128) or 48)
    overlap = min(0.05, height * 0.001)
    z0 = max(0.0, base_h - overlap)
    z1 = min(height, height - rim_h + overlap) if rim_h else height
    steps = 24 if form != "ровная" else 1
    sections, positions = [], []
    for i in range(steps + 1):
        u = i / steps
        if form == "песочные":
            factor = waist + (1.0 - waist) * (2.0 * u - 1.0) ** 2
        elif form == "конус":
            factor = 1.0 - taper * u
        else:
            factor = 1.0
        sections.append(_section(width * factor, depth * factor, section, segments))
        positions.append(z0 + (z1 - z0) * u)
    shaft = loft_solid(sections, positions, axis="z", what="колонна")
    parts = [shaft]
    if base:
        plate = _prism_section(base_size, base_size, base_h, section, segments)
        parts.append(plate)
    if rim > 0:
        top_factor = 1.0 if form != "конус" else 1.0 - taper
        rim_w = width * top_factor + 2 * rim
        rim_d = depth * top_factor + 2 * rim
        cap = _prism_section(rim_w, rim_d, rim_h, section, segments).translate(
            (0, 0, height - rim_h))
        parts.append(cap)
    solid = _one(mf.Manifold.batch_boolean(parts, mf.OpType.Add), "колонна")
    solid = apply_smooth(solid, a, "колонна")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="column")
    out.notes.append(f"колонна {form}/{section}, высота {height:g} мм; площадка "
                     f"{'да' if base else 'нет'}, бортик {rim:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Дуговая треугольная призма
# --------------------------------------------------------------------------- #
def _arc_edge(p0, p1, arc: float, steps: int = 24):
    p0, p1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
    edge = p1 - p0
    normal = np.asarray([edge[1], -edge[0]]) / max(float(np.linalg.norm(edge)), 1e-12)
    points = []
    for i in range(steps):
        t = i / steps
        p = p0 * (1 - t) + p1 * t + normal * (4 * arc * t * (1 - t))
        points.append((float(p[0]), float(p[1])))
    return points


@op("arc_prism", aliases=("дуговая_призма", "кривая_призма", "параболическая_призма",
                          "палатка", "curved_tri_prism"),
    category="Примитивы",
    summary="Треугольная призма с независимо изогнутыми сторонами основания. "
            "arc_a/arc_b/arc_c — стрелы парабол в мм: 0 — плоская сторона, "
            "положительная — выпуклость наружу, отрицательная — вогнутость внутрь.",
    example="палатка = arc_prism a=100 b=90 c=90 height=120 arc_a=0 arc_b=-16 arc_c=-16\n"
            "парус = arc_prism a=110 b=80 c=75 height=90 arc_a=12 arc_b=-10 arc_c=0 at=[0,160,0]",
    params={"a": "нижняя сторона по X, мм (100)",
            "b": "левая сторона от начала к вершине, мм (90)",
            "c": "правая сторона от вершины к концу основания, мм (90)",
            "height": "выдавливание по +Z, мм (120)",
            "arc_a": "дуга нижней стороны: + наружу, − внутрь, мм (0)",
            "arc_b": "дуга левой стороны: + наружу, − внутрь, мм (−12)",
            "arc_c": "дуга правой стороны: + наружу, − внутрь, мм (0)",
            "at": "положение [x,y,z]", "center": "центрировать по габариту"},
    positional=["a", "b", "c"])
def arc_prism(a, name):
    side_a = float(a.num("a", 100.0, minv=1.0, maxv=10000.0))
    side_b = float(a.num("b", 90.0, minv=0.5, maxv=10000.0))
    side_c = float(a.num("c", 90.0, minv=0.5, maxv=10000.0))
    if side_a + side_b <= side_c + 1e-6 or side_a + side_c <= side_b + 1e-6 \
            or side_b + side_c <= side_a + 1e-6:
        raise GeometryError("Из сторон a,b,c треугольник не сложить.")
    height = float(a.num("height", 120.0, minv=0.5, maxv=10000.0))
    arcs = [float(a.num(key, default, minv=-5000.0, maxv=5000.0) or 0.0)
            for key, default in (("arc_a", 0.0), ("arc_b", -12.0), ("arc_c", 0.0))]
    x = (side_a ** 2 + side_b ** 2 - side_c ** 2) / (2.0 * side_a)
    y = math.sqrt(max(1e-9, side_b ** 2 - x ** 2))
    v0 = np.asarray([0.0, 0.0])
    v1 = np.asarray([side_a, 0.0])
    v2 = np.asarray([x, y])
    pts = []
    # Периметр против часовой стрелки: нижняя a, правая c, левая b.
    for p0, p1, arc in ((v0, v1, arcs[0]), (v1, v2, arcs[2]), (v2, v0, arcs[1])):
        pts.extend(_arc_edge(p0, p1, arc))
    pts = np.asarray(pts, dtype=float)
    center = (pts.min(axis=0) + pts.max(axis=0)) / 2.0
    pts -= center
    cross = mf.CrossSection([pts.tolist()])
    if cross.is_empty() or cross.area() <= 1e-7:
        raise GeometryError("Дуги сторон стёрли основание призмы.",
                            hint="Уменьшите вогнутость arc_a/arc_b/arc_c.")
    solid = _one(cross.extrude(height), "дуговая призма")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="arc_prism")
    out.meta["arcs"] = {"a": arcs[0], "b": arcs[1], "c": arcs[2]}
    out.notes.append(f"дуговая призма: дуги a/b/c = {arcs[0]:g}/{arcs[1]:g}/{arcs[2]:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Профиль 2020
# --------------------------------------------------------------------------- #
def _rounded_square(size: float, radius: float) -> list[tuple[float, float]]:
    h, r = size / 2.0, min(radius, size / 2.0 - 1e-3)
    if r <= 1e-6:
        return [(-h, -h), (h, -h), (h, h), (-h, h)]
    pts = []
    for cx, cy, start in ((h - r, -h + r, -90), (h - r, h - r, 0),
                          (-h + r, h - r, 90), (-h + r, -h + r, 180)):
        for i in range(9):
            angle = math.radians(start + 90 * i / 8)
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def _chamfered_square(size: float, chamfer: float) -> list[tuple[float, float]]:
    h = size / 2.0
    c = max(0.01, min(chamfer, h * 0.8))
    return [(-h + c, -h), (h - c, -h), (h, -h + c), (h, h - c),
            (h - c, h), (-h + c, h), (-h, h - c), (-h, -h + c)]


def _regular_hole(diameter: float, sides: int) -> list[tuple[float, float]]:
    r = diameter / 2.0
    start = 45.0 if sides == 4 else (90.0 if sides == 3 else 0.0)
    return [(r * math.cos(math.radians(start + 360 * i / sides)),
             r * math.sin(math.radians(start + 360 * i / sides))) for i in range(sides)]


@op("profile2020", aliases=("профиль2020", "профиль_2020", "profile_2020",
                            "алюминиевый_профиль", "конструкционный_профиль", "extrusion_2020"),
    category="Примитивы",
    summary="Конструкционный профиль 20×20 и других размеров с четырьмя "
            "продольными углублениями. groove задаёт форму канала, depth — его "
            "глубину, rail — форму угловых реек. Центральное осевое отверстие "
            "бывает круглым, квадратным, треугольным или шестигранным.",
    example="профиль = profile2020 length=300 size=20 slot=6 channel=9 depth=4 "
            "groove=прямоугольная rail=скруглённая rail_r=1.2 bore=5 bore_shape=круг\n"
            "шестигранный = profile2020 length=160 size=24 groove=овальная "
            "bore=7 bore_shape=шестигранник at=[60,0,0]",
    params={"length": "длина по +Z, мм (300)", "size": "наружный квадрат, мм (20)",
            "slot": "ширина узкой горловины паза, мм (6)",
            "channel": "ширина внутреннего углубления, мм (9)",
            "depth": "полная глубина углубления от поверхности, мм (4)",
            "groove": "форма углубления: прямоугольная, треугольная или овальная",
            "rail": "угловые рейки: прямая, скруглённая или фаска",
            "rail_r": "радиус/размер фаски угловых реек, мм (1.2)",
            "bore": "диаметр описанной окружности осевого отверстия; 0 — без него, мм (5)",
            "bore_shape": "круг, квадрат, треугольник или шестигранник",
            "at": "положение [x,y,z]", "center": "центрировать по габариту"})
def profile2020(a, name):
    length = float(a.num("length", 300.0, minv=5.0, maxv=10000.0))
    size = float(a.num("size", 20.0, minv=8.0, maxv=1000.0))
    slot = float(a.num("slot", 6.0, minv=0.8, maxv=500.0))
    channel = float(a.num("channel", 9.0, minv=1.0, maxv=500.0))
    depth = float(a.num("depth", 4.0, minv=0.6, maxv=500.0))
    groove = _choice(a.text("groove", "прямоугольная"),
                     {"прямоугольная": "прямоугольная", "прямоугольный": "прямоугольная",
                      "треугольная": "треугольная", "треугольный": "треугольная",
                      "овальная": "овальная", "овальный": "овальная"}, "profile2020.groove")
    rail = _choice(a.text("rail", "скруглённая"),
                   {"прямая": "прямая", "острая": "прямая", "квадрат": "прямая",
                    "скруглённая": "скруглённая", "скругленная": "скруглённая",
                    "фаска": "фаска"}, "profile2020.rail")
    rail_r = float(a.num("rail_r", 1.2, minv=0.1, maxv=100.0))
    bore = float(a.num("bore", 5.0, minv=0.0, maxv=500.0) or 0.0)
    bore_shape = _choice(a.text("bore_shape", "круг"),
                         {"круг": "круг", "круглое": "круг", "квадрат": "квадрат",
                          "квадратное": "квадрат", "треугольник": "треугольник",
                          "треугольное": "треугольник", "шестигранник": "шестигранник",
                          "шестиугольник": "шестигранник", "гексагон": "шестигранник"},
                         "profile2020.bore_shape")
    if channel < slot:
        raise GeometryError("channel должна быть не меньше slot — иначе это не T-паз.")
    if channel >= size - 0.8 or slot >= size - 0.8:
        raise GeometryError("Паз не оставляет угловых реек профиля.")
    if bore > 0 and depth + bore / 2 >= size / 2 - 0.4:
        raise GeometryError("Пазы соединяются с осевым отверстием и разрушают профиль.",
                            hint="Уменьшите depth/bore или увеличьте size.")
    if bore == 0 and depth >= size / 2 - 0.4:
        raise GeometryError("Пазы сходятся в центре профиля; уменьшите depth.")
    h = size / 2.0
    if rail == "скруглённая":
        outer_pts = _rounded_square(size, rail_r)
    elif rail == "фаска":
        outer_pts = _chamfered_square(size, rail_r)
    else:
        outer_pts = _rounded_square(size, 0.0)
    solid = mf.CrossSection([outer_pts]).extrude(length)
    neck = min(depth * 0.35, depth - 0.2)
    tools = []
    for quarter in range(4):
        # Сначала строим паз на +X, затем поворачиваем на четыре стороны.
        neck_pts = [(h - neck, -slot / 2), (h + 1, -slot / 2),
                    (h + 1, slot / 2), (h - neck, slot / 2)]
        x0, x1 = h - depth, h - neck + 0.05
        if groove == "прямоугольная":
            inner_pts = [(x0, -channel / 2), (x1, -channel / 2),
                         (x1, channel / 2), (x0, channel / 2)]
        elif groove == "треугольная":
            inner_pts = [(x0, 0), (x1, -channel / 2), (x1, channel / 2)]
        else:
            cx, rx = (x0 + x1) / 2, (x1 - x0) / 2
            inner_pts = [(cx + rx * math.cos(2 * math.pi * i / 32),
                          channel / 2 * math.sin(2 * math.pi * i / 32)) for i in range(32)]
        cutter = (mf.CrossSection([neck_pts]).extrude(length + 2)
                  + mf.CrossSection([inner_pts]).extrude(length + 2))
        cutter = cutter.translate((0, 0, -1)).rotate((0, 0, 90 * quarter))
        tools.append(cutter)
    if bore > 0:
        if bore_shape == "круг":
            bore_tool = mf.Manifold.cylinder(length + 2, bore / 2, bore / 2, 64)
        else:
            sides = {"квадрат": 4, "треугольник": 3, "шестигранник": 6}[bore_shape]
            bore_tool = mf.CrossSection([_regular_hole(bore, sides)]).extrude(length + 2)
        tools.append(bore_tool.translate((0, 0, -1)))
    solid = _one(solid - mf.Manifold.batch_boolean(tools, mf.OpType.Add), "профиль 2020")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="profile2020")
    out.notes.append(f"профиль {size:g}×{size:g}×{length:g} мм, пазы {groove}, "
                     f"углы {rail}, ось {bore_shape} {bore:g} мм")
    return out
