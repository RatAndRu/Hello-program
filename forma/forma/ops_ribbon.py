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


def _strip_mesh(path: np.ndarray, width: float, thickness: float, ends: str,
                collapse_left: float, collapse_right: float,
                across: int = 16) -> mf.Manifold:
    """Структурная сетка: верх имеет переменную толщину, низ остаётся плоским."""
    n = len(path)
    tangents = np.empty_like(path)
    tangents[1:-1] = path[2:] - path[:-2]
    tangents[0] = path[1] - path[0]
    tangents[-1] = path[-1] - path[-2]
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1)[:, None], 1e-12)
    normals = np.column_stack((-tangents[:, 1], tangents[:, 0]))
    half = width / 2.0
    end_len = min(path[-1, 0] - path[0, 0], width * 0.8) * 0.5
    end_len = max(end_len, 1e-3)
    length_x = max(1e-6, path[-1, 0] - path[0, 0])
    verts: list[tuple[float, float, float]] = []
    m = int(across)
    for i, (center, normal) in enumerate(zip(path, normals)):
        dist = min(i, n - 1 - i) / (n - 1) * length_x
        factor = 1.0
        if ends != "прямоугольные" and dist < end_len:
            q = max(0.0, min(1.0, dist / end_len))
            factor = q if ends == "треугольные" else math.sqrt(max(0.0, 1 - (1 - q) ** 2))
        # Микроскопическая кромка вместо вырожденного веера из совпадающих
        # вершин; при ширине 40 мм это 0,02 мм и визуально является остриём.
        h = max(0.01, half * factor)
        for side in (1, 0):  # верх, затем низ
            for j in range(m + 1):
                v = -1.0 + 2.0 * j / m
                if side:
                    collapse = collapse_left if v > 0 else collapse_right
                    z = thickness * (1.0 - collapse * abs(v) ** 4)
                else:
                    z = 0.0
                xy = center + normal * (h * v)
                verts.append((float(xy[0]), float(xy[1]), float(z)))

    stride = m + 1
    ring = 2 * stride

    def top(i, j):
        return i * ring + j

    def bottom(i, j):
        return i * ring + stride + j

    faces: list[tuple[int, int, int]] = []
    for i in range(n - 1):
        for j in range(m):
            # Верх +Z и низ −Z.
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
            "центральная выемка и изгиб как у арки.",
    example="полоса = strip length=200 width=40 thickness=4 ends=овальные\n"
            "зигзаг = strip length=180 width=30 thickness=3 path=зигзаг curve=45 "
            "collapse_left=0.6 collapse_right=0.35 at=[0,120,0]\n"
            "с_окном = strip length=180 width=50 thickness=4 recess=круг recess_size=20\n"
            "прямоугольное = strip length=180 width=50 thickness=4 recess=прямоугольник "
            "recess_size=16 recess_length=30",
    params={"length": "длина по X, мм (200)", "width": "ширина, мм (40)",
            "thickness": "толщина сердцевины, мм (4)",
            "ends": "концы: прямоугольные, треугольные или овальные",
            "collapse_left": "истончение левой кромки 0…0.95 (0)",
            "collapse_right": "истончение правой кромки 0…0.95 (0)",
            "smooth": "уровни Loop-сглаживания 0…4 (0)",
            "bend": "общий угол дуги −180…180°, знак задаёт сторону (0)",
            "path": "контур центральной линии: прямая, S или зигзаг",
            "curve": "амплитуда S/зигзага по Y, мм (30)",
            "recess": "центральная сквозная выемка: нет, круг, прямоугольник, квадрат, треугольник",
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
                    "зигзаг": "зигзаг", "z": "зигзаг", "з": "зигзаг"}, "strip.path")
    curve = float(a.num("curve", 30.0, minv=0.1, maxv=5000.0))
    bend = float(a.num("bend", 0.0, minv=-180.0, maxv=180.0) or 0.0)
    centers = _strip_path(kind, length, curve)
    solid = _strip_mesh(centers, width, thickness, ends, left, right)
    recess = _choice(a.text("recess", "нет"),
                     {"нет": "нет", "без": "нет", "круг": "круг", "круглая": "круг",
                      "прямоугольник": "прямоугольник", "прямоугольная": "прямоугольник",
                      "квадрат": "квадрат", "квадратная": "квадрат",
                      "треугольник": "треугольник", "треугольная": "треугольник"}, "strip.recess")
    if recess != "нет":
        if kind != "прямая":
            raise GeometryError("Центральная выемка доступна у прямой полосы.",
                                hint="Задайте path=прямая или recess=нет.")
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
    solid = apply_smooth(solid, a, "полоса")
    solid = _bend_strip(solid, length, bend)
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="strip")
    out.notes.append(f"полоса {length:g}×{width:g}×{thickness:g} мм, {kind}, концы {ends}")
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
            "параллельные прямые, квадратная клетка или соты. bar — толщина "
            "реек, frame — наружной рамки, depth — толщина панели.",
    example="планки = grating width=180 height=100 depth=4 pattern=планки bars=7 bar=3 frame=6\n"
            "клетка = grating width=180 height=120 depth=4 pattern=клетка cols=5 rows=4 at=[0,160,0]\n"
            "соты = grating width=200 height=140 depth=4 pattern=соты cell=22 bar=3 at=[0,340,0]",
    params={"width": "наружная ширина по X, мм (200)",
            "height": "наружная высота по Y, мм (120)", "depth": "толщина по Z, мм (4)",
            "pattern": "планки, клетка или соты", "bar": "толщина реек, мм (3)",
            "frame": "толщина наружной рамки, мм (6)",
            "bars": "число внутренних параллельных реек в режиме планки (7)",
            "cols": "число квадратных ячеек по X (5)", "rows": "число ячеек по Y (4)",
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
    elif pattern == "клетка":
        cols = int(a.int("cols", 5, minv=1, maxv=100) or 5)
        rows = int(a.int("rows", 4, minv=1, maxv=100) or 4)
        gx = (iw - (cols - 1) * bar) / cols
        gy = (ih - (rows - 1) * bar) / rows
        if gx <= 0.15 or gy <= 0.15:
            raise GeometryError("Рейки клетки не оставляют квадратных просветов.")
        for i in range(cols):
            x = -iw / 2 + gx / 2 + i * (gx + bar)
            for j in range(rows):
                y = -ih / 2 + gy / 2 + j * (gy + bar)
                cutters.append(_box_cutter((gx, gy), (x, y), depth))
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
@op("spikes", aliases=("шипы", "шип", "spike", "spike_array", "панель_с_шипами"),
    category="Примитивы",
    summary="Набор шипов на одной прямоугольной площадке. Число по осям, высота, "
            "диаметры основания и острия, число граней, общий наклон и его "
            "направление настраиваются независимо; tip_d=0 даёт острый конус.",
    example="шипы = spikes width=120 length=80 base_h=4 cols=4 rows=3 height=28 "
            "base_d=12 tip_d=0.8 sides=24 lean=12 direction=0\n"
            "треугольные = spikes width=100 length=60 cols=3 rows=2 sides=3 tip_d=0 at=[0,140,0]",
    params={"width": "площадка по X, мм (120)", "length": "площадка по Y, мм (80)",
            "base_h": "толщина общей площадки, мм (4)",
            "cols": "шипов по X (4)", "rows": "шипов по Y (3)",
            "height": "высота каждого шипа над площадкой, мм (28)",
            "base_d": "диаметр основания шипа, мм (12)",
            "tip_d": "диаметр плоского острия; 0 — точка, мм (0.8)",
            "sides": "граней шипа 3…64 (24)",
            "lean": "наклон всех шипов от вертикали −45…45°, (0)",
            "direction": "азимут наклона в плане, градусы (0 — +X)",
            "at": "положение [x,y,z]", "center": "центрировать по габариту"})
def spikes(a, name):
    width = float(a.num("width", 120.0, minv=5.0, maxv=10000.0))
    length = float(a.num("length", 80.0, minv=5.0, maxv=10000.0))
    base_h = float(a.num("base_h", 4.0, minv=0.2, maxv=1000.0))
    cols = int(a.int("cols", 4, minv=1, maxv=100) or 4)
    rows = int(a.int("rows", 3, minv=1, maxv=100) or 3)
    height = float(a.num("height", 28.0, minv=0.5, maxv=5000.0))
    base_d = float(a.num("base_d", 12.0, minv=0.4, maxv=5000.0))
    tip_d = float(a.num("tip_d", 0.8, minv=0.0, maxv=5000.0) or 0.0)
    sides = int(a.int("sides", 24, minv=3, maxv=64) or 24)
    lean = float(a.num("lean", 0.0, minv=-45.0, maxv=45.0) or 0.0)
    direction = float(a.num("direction", 0.0, minv=-360.0, maxv=360.0) or 0.0)
    if tip_d > base_d + 1e-9:
        raise GeometryError("tip_d не может быть больше base_d.")
    if base_d * cols > width + 1e-9 or base_d * rows > length + 1e-9:
        raise GeometryError("Основания шипов не помещаются на площадке.",
                            hint="Уменьшите base_d/cols/rows или увеличьте площадку.")
    base = mf.Manifold.cube((width, length, base_h), True).translate((0, 0, base_h / 2))
    px = (width - base_d) / max(1, cols - 1) if cols > 1 else 0.0
    py = (length - base_d) / max(1, rows - 1) if rows > 1 else 0.0
    slope = math.tan(math.radians(lean))
    sx = slope * math.cos(math.radians(direction))
    sy = slope * math.sin(math.radians(direction))
    parts = [base]
    z0 = base_h - min(0.05, base_h * 0.1)
    for i in range(cols):
        x = 0.0 if cols == 1 else -width / 2 + base_d / 2 + i * px
        for j in range(rows):
            y = 0.0 if rows == 1 else -length / 2 + base_d / 2 + j * py
            spike = mf.Manifold.cylinder(height + 0.05, base_d / 2, tip_d / 2, sides)
            if abs(slope) > 1e-12:
                spike = spike.transform(np.asarray([[1, 0, sx, 0], [0, 1, sy, 0], [0, 0, 1, 0]],
                                                   dtype=float))
            parts.append(spike.translate((x, y, z0)))
    solid = _one(mf.Manifold.batch_boolean(parts, mf.OpType.Add), "шипы")
    out = make_solid(a.scene, name, _placed(a, solid), a, kind="spikes")
    out.meta["spikes"] = cols * rows
    out.notes.append(f"шипов {cols * rows}: высота {height:g}, основание {base_d:g}, остриё {tip_d:g} мм")
    return out
