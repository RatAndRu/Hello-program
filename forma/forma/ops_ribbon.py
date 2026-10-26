"""Полосы, сквозные решётки и наборы шипов на общей площадке."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, manifold_mesh
from .ops import anchor, make_solid, op
from .shape_features import apply_smooth


def _placed(a, solid: mf.Manifold) -> mf.Manifold:
    return anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))


def _one(solid: mf.Manifold, what: str) -> mf.Manifold:
    if solid.is_empty() or solid.volume() <= 1e-7:
        raise GeometryError(f"{what}: получилось пустое тело.")
    if len(solid.decompose()) != 1:
        raise GeometryError(f"{what}: деталь распалась на части; увеличьте рейки или рамку.")
    return solid


def _choice(raw: str, table: dict[str, str], what: str) -> str:
    value = table.get((raw or "").strip().lower())
    if value is None:
        raise GeometryError(f"{what}: неизвестное значение «{raw}». "
                            + "Доступно: " + ", ".join(dict.fromkeys(table.values())) + ".")
    return value


# --------------------------------------------------------------------------- #
#  Полоса
# --------------------------------------------------------------------------- #
def _strip_path(kind: str, length: float, curve: float) -> np.ndarray:
    if kind == "s":
        t = np.linspace(0.0, 1.0, 65)
        return np.column_stack((-length / 2 + length * t,
                                curve * np.sin(2 * math.pi * t)))
    if kind == "зигзаг":
        corners = np.asarray([(-length / 2, curve), (-length * 0.16, curve),
                              (length * 0.16, -curve), (length / 2, -curve)], dtype=float)
        chunks = []
        for i in range(len(corners) - 1):
            t = np.linspace(0.0, 1.0, 15, endpoint=i == len(corners) - 2)
            chunks.append(corners[i][None, :] * (1 - t[:, None])
                          + corners[i + 1][None, :] * t[:, None])
        return np.vstack(chunks)
    t = np.linspace(0.0, 1.0, 49)
    return np.column_stack((-length / 2 + length * t, np.zeros_like(t)))


def _horseshoe_path(length: float, radius: float) -> np.ndarray:
    """U-образная центральная линия: две прямые ноги и полукруг, открытая в −Y."""
    leg = (float(length) - math.pi * float(radius)) / 2.0
    if leg <= 1.0:
        raise GeometryError("Для подковы length должен быть больше π·curve + 2 мм.",
                            hint="Увеличьте length или уменьшите curve — радиус подковы.")
    r = float(radius)
    chunks = []
    left = np.linspace(0.0, 1.0, 18)
    chunks.append(np.column_stack([np.full_like(left, -r), -leg * (1.0 - left)]))
    theta = np.linspace(math.pi, 0.0, 49)[1:]
    chunks.append(np.column_stack([r * np.cos(theta), r * np.sin(theta)]))
    right = np.linspace(0.0, 1.0, 18)[1:]
    chunks.append(np.column_stack([np.full_like(right, r), -leg * right]))
    return np.vstack(chunks)


def _strip_mesh(path: np.ndarray, width: float, thickness: float, ends: str,
                collapse_left: float, collapse_right: float,
                across: int = 16) -> mf.Manifold:
    """Структурная сетка ленты вдоль трёхмерной центральной линии.

    Боковая ось остаётся горизонтальной, а толщина идёт по локальной нормали
    пути. Поэтому S/зигзаг можно задавать независимо в XY и XZ, не склеивая
    два разных изгиба в одну диагональную деформацию.
    """
    path = np.asarray(path, dtype=np.float64)
    n = len(path)
    tangents = np.empty_like(path)
    tangents[1:-1] = path[2:] - path[:-2]
    tangents[0] = path[1] - path[0]
    tangents[-1] = path[-1] - path[-2]
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1)[:, None], 1e-12)
    sides = np.cross(np.broadcast_to(np.array([0.0, 0.0, 1.0]), tangents.shape), tangents)
    sides /= np.maximum(np.linalg.norm(sides, axis=1)[:, None], 1e-12)
    ups = np.cross(tangents, sides)
    ups /= np.maximum(np.linalg.norm(ups, axis=1)[:, None], 1e-12)
    distances = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    total = max(float(distances[-1]), 1e-6)
    end_len = max(1e-3, min(total, width * 0.8) * 0.5)
    half = width / 2.0
    verts: list[tuple[float, float, float]] = []
    m = int(across)
    for i, (center, side, up) in enumerate(zip(path, sides, ups)):
        dist = min(distances[i], total - distances[i])
        factor = 1.0
        if ends != "прямоугольные" and dist < end_len:
            q = max(0.0, min(1.0, dist / end_len))
            factor = q if ends == "треугольные" else math.sqrt(max(0.0, 1 - (1 - q) ** 2))
        h = max(0.01, half * factor)
        for top_side in (1, 0):
            for j in range(m + 1):
                v = -1.0 + 2.0 * j / m
                collapse = collapse_left if v > 0 else collapse_right
                z = thickness * (1.0 - collapse * abs(v) ** 4) if top_side else 0.0
                point = center + side * (h * v) + up * z
                verts.append(tuple(float(c) for c in point))
    stride = m + 1
    ring = 2 * stride

    def top(i, j):
        return i * ring + j

    def bottom(i, j):
        return i * ring + stride + j

    faces: list[tuple[int, int, int]] = []
    for i in range(n - 1):
        for j in range(m):
            faces += [(top(i, j), top(i + 1, j), top(i + 1, j + 1)),
                      (top(i, j), top(i + 1, j + 1), top(i, j + 1)),
                      (bottom(i, j), bottom(i + 1, j + 1), bottom(i + 1, j)),
                      (bottom(i, j), bottom(i, j + 1), bottom(i + 1, j + 1))]
        for j in (0, m):
            if j == 0:
                faces += [(top(i, j), bottom(i, j), bottom(i + 1, j)),
                          (top(i, j), bottom(i + 1, j), top(i + 1, j))]
            else:
                faces += [(top(i, j), top(i + 1, j), bottom(i + 1, j)),
                          (top(i, j), bottom(i + 1, j), bottom(i, j))]
    for i, reverse in ((0, True), (n - 1, False)):
        for j in range(m):
            if reverse:
                faces += [(top(i, j), top(i, j + 1), bottom(i, j + 1)),
                          (top(i, j), bottom(i, j + 1), bottom(i, j))]
            else:
                faces += [(top(i, j), bottom(i, j), bottom(i, j + 1)),
                          (top(i, j), bottom(i, j + 1), top(i, j + 1))]
    return manifold_from_arrays(np.asarray(verts, dtype=float), np.asarray(faces, dtype=np.int64),
                                "полоса")


def _bend_strip(solid: mf.Manifold, length: float, angle: float) -> mf.Manifold:
    if abs(angle) < 1e-9:
        return solid
    verts, faces = manifold_mesh(solid)
    verts = np.asarray(verts, dtype=float).copy()
    theta = math.radians(angle)
    radius = length / abs(theta)
    phi = theta * verts[:, 0] / length
    z = verts[:, 2].copy()
    sign = 1.0 if angle > 0 else -1.0
    verts[:, 0] = radius * np.sin(phi) + z * np.sin(phi)
    verts[:, 2] = (sign * radius * (np.cos(phi) - math.cos(abs(theta) / 2))
                   + z * np.cos(phi))
    return manifold_from_arrays(verts, faces, "согнутая полоса")


@op("strip", aliases=("полоса", "полоска", "лента", "ribbon", "band_strip"),
    category="Примитивы",
    summary="Тонкая вытянутая полоса с объёмом. Концы бывают прямоугольными, "
            "треугольными или овальными; collapse_left/right независимо истончают "
            "боковые кромки, оставляя толстую сердцевину. path=прямая/S/зигзаг, "
            "центральное ровное отверстие и изгиб как у арки. path/curve задают "
            "контур в XY, path_z/curve_z — независимый контур в XZ. "
            "У подковы length — длина центральной линии, curve — радиус, "
            "свободные концы смотрят в −Y.",
    example="полоса = strip length=200 width=40 thickness=4 ends=овальные\n"
            "зигзаг = strip length=180 width=30 thickness=3 path=зигзаг curve=45 "
            "collapse_left=0.6 collapse_right=0.35 at=[0,120,0]\n"
            "с_окном = strip length=180 width=50 thickness=4 recess=круг recess_size=20\n"
            "прямоугольное = strip length=180 width=50 thickness=4 recess=прямоугольник "
            "recess_size=16 recess_length=30\n"
            "подкова = strip length=200 width=12 thickness=4 path=подкова curve=35",
    params={"length": "длина по X; у подковы — длина центральной линии, мм (200)",
            "width": "ширина, мм (40)",
            "thickness": "толщина сердцевины, мм (4)",
            "ends": "концы: прямоугольные, треугольные или овальные",
            "collapse_left": "истончение левой кромки 0…0.95 (0)",
            "collapse_right": "истончение правой кромки 0…0.95 (0)",
            "smooth": "уровни Loop-сглаживания 0…4 (0)",
            "bend": "общий угол дуги −180…180°, знак задаёт сторону (0)",
            "path": "контур центральной линии: прямая, S, зигзаг или подкова",
            "curve": "амплитуда S/зигзага по Y; радиус дуги подковы, мм (30)",
            "path_z": "второй контур в XZ: прямая, S или зигзаг",
            "curve_z": "амплитуда второго контура по Z, мм (30)",
            "recess": "центральное сквозное отверстие: нет, круг, прямоугольник, квадрат, треугольник",
            "recess_size": "диаметр круга, ширина прямоугольника или сторона квадрата/треугольника, мм (16)",
            "recess_length": "длина прямоугольной выемки по X, мм (24)",
            "at": "положение [x,y,z]", "center": "центрировать по габариту"},
    positional=["length", "width"])
def strip(a, name):
    length = float(a.num("length", 200.0, minv=10.0, maxv=10000.0))
    width = float(a.num("width", 40.0, minv=1.0, maxv=5000.0))
    thickness = float(a.num("thickness", 4.0, minv=0.1, maxv=1000.0))
    ends = _choice(a.text("ends", "прямоугольные"),
                   {"прямоугольные": "прямоугольные", "прямоугольный": "прямоугольные",
                    "треугольные": "треугольные", "треугольный": "треугольные",
                    "овальные": "овальные", "овальный": "овальные"}, "strip.ends")
    left = float(a.num("collapse_left", 0.0, minv=0.0, maxv=0.95) or 0.0)
    right = float(a.num("collapse_right", 0.0, minv=0.0, maxv=0.95) or 0.0)
    kind = _choice(a.text("path", "прямая"),
                   {"прямая": "прямая", "прямой": "прямая", "s": "s", "с": "s",
                    "зигзаг": "зигзаг", "z": "зигзаг", "з": "зигзаг",
                    "подкова": "подкова", "u": "подкова", "horseshoe": "подкова"}, "strip.path")
    curve = float(a.num("curve", 30.0, minv=0.1, maxv=5000.0))
    kind_z = _choice(a.text("path_z", "прямая"),
                     {"прямая": "прямая", "прямой": "прямая", "s": "s", "с": "s",
                      "зигзаг": "зигзаг", "z": "зигзаг", "з": "зигзаг"}, "strip.path_z")
    curve_z = float(a.num("curve_z", 30.0, minv=0.1, maxv=5000.0))
    bend = float(a.num("bend", 0.0, minv=-180.0, maxv=180.0) or 0.0)
    if kind == "подкова":
        if width >= 2.0 * curve:
            raise GeometryError("Ширина полосы не оставляет внутреннего радиуса подковы.",
                                hint="width должен быть меньше 2·curve.")
        if abs(bend) > 1e-9:
            raise GeometryError("У подковы используйте path_z для изгиба, а не bend.")
        horizontal = _horseshoe_path(length, curve)
        tx = np.linspace(0.0, 1.0, len(horizontal))
        tv = None
    else:
        horizontal = _strip_path(kind, length, curve)
        tx = (horizontal[:, 0] + length / 2.0) / length
        tv = None
    vertical = _strip_path(kind_z, length, curve_z)
    if kind == "подкова":
        tv = np.linspace(0.0, 1.0, len(vertical))
    elif tv is None:
        tv = (vertical[:, 0] + length / 2.0) / length
    centers = np.column_stack([horizontal, np.interp(tx, tv, vertical[:, 1])])
    solid = _strip_mesh(centers, width, thickness, ends, left, right)
    solid = apply_smooth(solid, a, "полоса")
    recess = _choice(a.text("recess", "нет"),
                     {"нет": "нет", "без": "нет", "круг": "круг", "круглая": "круг",
                      "прямоугольник": "прямоугольник", "прямоугольная": "прямоугольник",
                      "квадрат": "квадрат", "квадратная": "квадрат",
                      "треугольник": "треугольник", "треугольная": "треугольник"}, "strip.recess")
    if recess != "нет":
        if kind != "прямая" or kind_z != "прямая":
            raise GeometryError("Центральное отверстие доступно у прямой полосы.",
                                hint="Задайте path=прямая и path_z=прямая или recess=нет.")
        size = float(a.num("recess_size", 16.0, minv=0.5, maxv=5000.0))
        rect_length = float(a.num("recess_length", 24.0, minv=0.5, maxv=5000.0)) \
            if recess == "прямоугольник" else size
        if size >= width * 0.9 or rect_length >= length * 0.9:
            raise GeometryError("Размеры выемки не оставляют материала вокруг неё.")
        h = thickness * 2 + 4
        if recess == "круг":
            tool = mf.Manifold.cylinder(h, size / 2, size / 2, 64, center=True)
        elif recess == "квадрат":
            tool = mf.Manifold.cube((size, size, h), True)
        elif recess == "прямоугольник":
            tool = mf.Manifold.cube((rect_length, size, h), True)
        else:
            r = size / math.sqrt(3.0)
            pts = [(r * math.cos(math.radians(90 + 120 * i)),
                    r * math.sin(math.radians(90 + 120 * i))) for i in range(3)]
            tool = mf.CrossSection([pts]).extrude(h).translate((0, 0, -h / 2))
        solid = _one(solid - tool.translate((0, 0, thickness / 2)), "полоса с выемкой")
    solid = _bend_strip(solid, length, bend)
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="strip")
    out.notes.append(f"полоса {length:g}×{width:g}×{thickness:g} мм, контур Y={kind}, "
                     f"контур Z={kind_z}, концы {ends}")
    return out


# --------------------------------------------------------------------------- #
#  Решётка
# --------------------------------------------------------------------------- #
def _box_cutter(size, center, depth):
    return mf.Manifold.cube((float(size[0]), float(size[1]), depth + 2.0), True).translate(
        (float(center[0]), float(center[1]), depth / 2.0))


@op("grating", aliases=("решётка", "решетка", "перфорация_панель", "grid_panel",
                        "lattice_panel", "сетка_панель"),
    category="Примитивы",
    summary="Панель-решётка одним телом с настоящими сквозными отверстиями: "
            "параллельные прямые, квадратная клетка, круглые или треугольные "
            "ячейки и соты. bar — минимальная перемычка, frame — наружная рамка.",
    example="планки = grating width=180 height=100 depth=4 pattern=планки bars=7 bar=3 frame=6\n"
            "клетка = grating width=180 height=120 depth=4 pattern=клетка cols=5 rows=4 at=[0,160,0]\n"
            "соты = grating width=200 height=140 depth=4 pattern=соты cell=22 bar=3 at=[0,340,0]\n"
            "круги = grating width=180 height=120 pattern=круги cols=6 rows=4 bar=3\n"
            "треугольники = grating width=180 height=120 pattern=треугольники cols=6 rows=4",
    params={"width": "наружная ширина по X, мм (200)",
            "height": "наружная высота по Y, мм (120)", "depth": "толщина по Z, мм (4)",
            "pattern": "планки, клетка, круги, треугольники или соты",
            "bar": "минимальная перемычка между ячейками, мм (3)",
            "frame": "толщина наружной рамки, мм (6)",
            "bars": "число внутренних параллельных реек в режиме планки (7)",
            "cols": "число ячеек по X для клетки/кругов/треугольников (5)",
            "rows": "число ячеек по Y для клетки/кругов/треугольников (4)",
            "cell": "размер соты между параллельными гранями, мм (22)",
            "at": "положение [x,y,z]", "center": "центрировать по габариту"})
def grating(a, name):
    width = float(a.num("width", 200.0, minv=10.0, maxv=10000.0))
    height = float(a.num("height", 120.0, minv=10.0, maxv=10000.0))
    depth = float(a.num("depth", 4.0, minv=0.2, maxv=1000.0))
    bar = float(a.num("bar", 3.0, minv=0.2, maxv=1000.0))
    frame = float(a.num("frame", 6.0, minv=0.4, maxv=2000.0))
    pattern = _choice(a.text("pattern", "планки"),
                      {"планки": "планки", "прямые": "планки", "параллельные": "планки",
                       "клетка": "клетка", "квадрат": "клетка", "сетка": "клетка",
                       "круги": "круги", "круг": "круги", "круглые": "круги",
                       "отверстия": "круги", "circles": "круги",
                       "треугольники": "треугольники", "треугольная": "треугольники",
                       "треугольник": "треугольники", "triangles": "треугольники",
                       "соты": "соты", "honeycomb": "соты"}, "grating.pattern")
    iw, ih = width - 2 * frame, height - 2 * frame
    if iw <= 2 * bar or ih <= 2 * bar:
        raise GeometryError("Рамка и рейки не оставляют места для сквозных ячеек.")
    outer = mf.Manifold.cube((width, height, depth), True).translate((0, 0, depth / 2))
    cutters = []
    holes = 0
    if pattern == "планки":
        bars = int(a.int("bars", 7, minv=1, maxv=200) or 7)
        gap = (iw - bars * bar) / (bars + 1)
        if gap <= 0.15:
            raise GeometryError("Параллельные рейки не оставляют просветов.",
                                hint="Уменьшите bars/bar или увеличьте width.")
        x0 = -iw / 2
        for i in range(bars + 1):
            x = x0 + gap / 2 + i * (gap + bar)
            cutters.append(_box_cutter((gap, ih), (x, 0), depth))
        holes = bars + 1
    elif pattern in ("клетка", "круги", "треугольники"):
        cols = int(a.int("cols", 5, minv=1, maxv=100) or 5)
        rows = int(a.int("rows", 4, minv=1, maxv=100) or 4)
        gx = (iw - (cols - 1) * bar) / cols
        gy = (ih - (rows - 1) * bar) / rows
        if gx <= 0.15 or gy <= 0.15:
            raise GeometryError("Перемычки не оставляют просветов между ячейками.")
        for i in range(cols):
            x = -iw / 2 + gx / 2 + i * (gx + bar)
            for j in range(rows):
                y = -ih / 2 + gy / 2 + j * (gy + bar)
                if pattern == "клетка":
                    cutters.append(_box_cutter((gx, gy), (x, y), depth))
                elif pattern == "круги":
                    radius = min(gx, gy) / 2.0
                    cutters.append(mf.Manifold.cylinder(
                        depth + 2.0, radius, radius, 40).translate((x, y, -1.0)))
                else:
                    # Чередование вершины вверх/вниз даёт настоящую
                    # треугольную сетку, а не повёрнутые квадраты.
                    if (i + j) % 2 == 0:
                        pts = [(x - gx / 2, y - gy / 2), (x + gx / 2, y - gy / 2),
                               (x, y + gy / 2)]
                    else:
                        pts = [(x - gx / 2, y + gy / 2), (x + gx / 2, y + gy / 2),
                               (x, y - gy / 2)]
                    # CrossSection трактует обратную ориентацию как отверстие.
                    # У обеих ориентаций треугольника порядок должен быть CCW.
                    area2 = sum(pts[k][0] * pts[(k + 1) % 3][1]
                                - pts[(k + 1) % 3][0] * pts[k][1] for k in range(3))
                    if area2 < 0.0:
                        pts.reverse()
                    cutters.append(mf.CrossSection([pts]).extrude(depth + 2.0).translate((0, 0, -1)))
        holes = cols * rows
    else:
        cell = float(a.num("cell", 22.0, minv=2.0, maxv=5000.0))
        r = cell / math.sqrt(3.0)
        dx, dy = 1.5 * r + bar, cell + bar
        q = 0
        x = -iw / 2 + r
        while x + r <= iw / 2 + 1e-7:
            y = -ih / 2 + r + (q % 2) * dy / 2
            while y + r <= ih / 2 + 1e-7:
                pts = [(x + r * math.cos(math.radians(60 * k)),
                        y + r * math.sin(math.radians(60 * k))) for k in range(6)]
                cutters.append(mf.CrossSection([pts]).extrude(depth + 2).translate((0, 0, -1)))
                holes += 1
                y += dy
            q += 1
            x = -iw / 2 + r + q * dx
        if not holes:
            raise GeometryError("Сота не помещается внутри рамки.",
                                hint="Уменьшите cell/bar или увеличьте размер панели.")
    tool = mf.Manifold.batch_boolean(cutters, mf.OpType.Add)
    solid = _one(outer - tool, "решётка")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="grating")
    out.meta["openings"] = holes
    out.notes.append(f"решётка {pattern}: {holes} сквозных ячеек, рейки {bar:g} мм, рамка {frame:g} мм")
    return out


# --------------------------------------------------------------------------- #
#  Шипы
# --------------------------------------------------------------------------- #
@op("spikes", aliases=("шипы", "шип", "spike", "spike_array", "нарастить_шипы"),
    category="Форма и деформации",
    summary="Наращивает шипы на выбранной поверхности существующего тела, "
            "без собственной площадки или головы. Центры разводятся без "
            "перекрытий, корни входят в объект и образуют с ним одно тело. "
            "surface выбирает сторону, count или cols×rows — число шипов.",
    example="панель = box size=[120,80,12]\n"
            "панель = spikes [панель] surface=верх cols=4 rows=3 height=28 base_d=12 tip_d=.8\n"
            "ёж = sphere radius=45 segments=48\n"
            "ёж = spikes [ёж] surface=вся count=70 height=22 base_d=7 tip_d=0 seed=4",
    params={"objects": "существующий объект [a] или a (обязательно)",
            "surface": "верх, низ, право, лево, перёд, зад или вся",
            "count": "число шипов 1…400; если не задано — cols×rows",
            "cols": "условных колонок для count=cols×rows (4)",
            "rows": "условных строк для count=cols×rows (3)",
            "height": "высота каждого шипа над поверхностью, мм (28)",
            "base_d": "диаметр основания шипа, мм (12)",
            "tip_d": "диаметр плоского острия; 0 — точка, мм (0.8)",
            "sides": "граней шипа 3…64 (24)",
            "lean": "наклон всех шипов от нормали −45…45° (0)",
            "direction": "азимут наклона, градусы (0 — +X)",
            "seed": "повторяемая раскладка (1)"},
    positional=["objects"])
def spikes(a, name):
    from .ops_extra import _derived, _one as _one_object
    from .ops_surface import _frame, _surface_samples
    from .ops_shapes import ensure_volume
    from .geometry import manifold_mesh

    base = _one_object(a, "spikes")
    surface = (a.text("surface", "верх") or "верх").strip().lower()
    sides_map = {"верх": (0, 0, 1), "низ": (0, 0, -1), "право": (1, 0, 0),
                 "лево": (-1, 0, 0), "перёд": (0, -1, 0), "перед": (0, -1, 0),
                 "зад": (0, 1, 0)}
    if surface in ("все", "всё", "all"):
        surface = "вся"
    if surface != "вся" and surface not in sides_map:
        raise GeometryError("spikes: surface=верх, низ, право, лево, перёд, зад или вся.")
    cols = int(a.int("cols", 4, minv=1, maxv=100) or 4)
    rows = int(a.int("rows", 3, minv=1, maxv=100) or 3)
    count = int(a.num("count", cols * rows, minv=1, maxv=400))
    height = float(a.num("height", 28.0, minv=0.5, maxv=5000.0))
    base_d = float(a.num("base_d", 12.0, minv=0.4, maxv=5000.0))
    tip_d = float(a.num("tip_d", 0.8, minv=0.0, maxv=5000.0) or 0.0)
    sides = int(a.int("sides", 24, minv=3, maxv=64) or 24)
    lean = float(a.num("lean", 0.0, minv=-45.0, maxv=45.0) or 0.0)
    direction = float(a.num("direction", 0.0, minv=-360.0, maxv=360.0) or 0.0)
    seed = int(a.num("seed", 1, minv=0, maxv=1_000_000))
    if tip_d > base_d + 1e-9:
        raise GeometryError("tip_d не может быть больше base_d.")
    rng = np.random.default_rng(seed)
    verts, faces = manifold_mesh(base.manifold)
    points, normals = _surface_samples(verts, faces, max(4000, count * 80), rng)
    mask = np.ones(len(points), dtype=bool)
    if surface != "вся":
        side = np.asarray(sides_map[surface], dtype=np.float64)
        mask &= (normals @ side) > 0.25
        # На осевой плоскости корень не должен свисать за границу исходной
        # детали. Для криволинейных поверхностей естественный обхват остаётся.
        axis = int(np.argmax(np.abs(side)))
        tangent_axes = [i for i in range(3) if i != axis]
        bb = base.manifold.bounding_box()
        margin = base_d * 0.53
        for coordinate in tangent_axes:
            mask &= points[:, coordinate] >= bb[coordinate] + margin
            mask &= points[:, coordinate] <= bb[coordinate + 3] - margin
    indices = np.flatnonzero(mask)
    if len(indices) < count:
        raise GeometryError("На выбранной стороне недостаточно поверхности для шипов.")
    points, normals = points[indices], normals[indices]
    # Farthest-point: равномерная повторяемая раскладка без слипшихся оснований.
    chosen = [int(rng.integers(0, len(points)))]
    best = np.sum((points - points[chosen[0]]) ** 2, axis=1)
    best[chosen[0]] = -1.0
    minimum = base_d * 1.05
    while len(chosen) < count:
        index = int(np.argmax(best))
        if best[index] < minimum * minimum:
            raise GeometryError(f"На поверхности не помещаются {count} шипов с base_d={base_d:g}.",
                                hint="Уменьшите count/base_d или выберите больший объект.")
        chosen.append(index)
        best = np.minimum(best, np.sum((points - points[index]) ** 2, axis=1))
        best[chosen] = -1.0
    selected = np.asarray(chosen, dtype=np.int64)
    points, normals = points[selected], normals[selected]
    slope = math.tan(math.radians(lean))
    azimuth = np.array([math.cos(math.radians(direction)),
                        math.sin(math.radians(direction)), 0.0])
    root = max(0.08, min(0.5, base_d * 0.08))
    pieces = []
    for point, normal in zip(points, normals):
        normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
        tangent = azimuth - normal * float(np.dot(azimuth, normal))
        if np.linalg.norm(tangent) < 1e-8:
            tangent = np.cross(normal, np.array([0.0, 0.0, 1.0]))
        tangent /= max(float(np.linalg.norm(tangent)), 1e-12)
        grow = normal + tangent * slope
        grow /= max(float(np.linalg.norm(grow)), 1e-12)
        spike = mf.Manifold.cylinder(height + root, base_d / 2.0, tip_d / 2.0, sides)
        frame = _frame(grow)
        frame[:, 3] = point - normal * root
        pieces.append(spike.transform(frame))
    solid = mf.Manifold.batch_boolean([base.manifold] + pieces, mf.OpType.Add)
    solid = ensure_volume(solid, "шипов на поверхности")
    if len(solid.decompose()) != 1:
        raise GeometryError("Шипы не сварились с исходным объектом.")
    out = _derived(a, name, solid, base, "spikes")
    out.meta["spikes"] = count
    out.notes.append(f"шипов на исходной поверхности {count}, surface={surface}, seed={seed}")
    return out
