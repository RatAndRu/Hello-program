"""Паутина из капсульных нитей и натянутые мембраны крыла/плавника."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile, sweep_solid
from .ops import anchor, make_solid, op, stand_flat_sign
from .ops_shapes import _profile


def _clean_path(points) -> np.ndarray:
    out = []
    for point in points:
        p = np.asarray(point, dtype=np.float64)
        if not out or np.linalg.norm(p - out[-1]) > 1e-7:
            out.append(p)
    if len(out) < 2:
        raise GeometryError("Паутина: нить выродилась в точку.")
    return np.asarray(out)


def _thread(points, diameter: float, sides: int, what: str,
            closed: bool = False) -> mf.Manifold:
    path = _clean_path(points)
    if path.shape[1] == 2:
        path = np.column_stack((path, np.zeros(len(path))))
    # Плоские торцы здесь важны не для внешнего вида, а для топологии:
    # collapsed-кольца полусферических caps у многих нитей в одной точке
    # после сварки GLB давали рёбра с четырьмя гранями.  Тонкая нить всё
    # равно остаётся круглым прутом; концы перекрываются узлом/мембраной.
    return sweep_solid(path, circle_profile(diameter / 2.0, sides),
                       closed_path=closed, round_caps=0.0, what=what)


def _ray_polygon_distance(center: np.ndarray, direction: np.ndarray,
                          polygon: np.ndarray) -> float:
    best = math.inf
    for i, p0 in enumerate(polygon):
        p1 = polygon[(i + 1) % len(polygon)]
        edge = p1 - p0
        rhs = p0 - center
        matrix = np.column_stack((direction, -edge))
        det = float(np.linalg.det(matrix))
        if abs(det) < 1e-10:
            continue
        distance, u = np.linalg.solve(matrix, rhs)
        if distance >= -1e-8 and -1e-8 <= u <= 1.0 + 1e-8:
            best = min(best, float(distance))
    if not math.isfinite(best):
        raise GeometryError("Паутина: луч не пересёк контур.")
    return best


@op("web", aliases=("паутина", "паутинка", "spider_web", "webbing",
                    "сеть_нитей", "мембрана_крыла"),
    category="Примитивы",
    summary="Плоская паутина из настоящих капсульных нитей круглого сечения: "
            "радиальные нити, провисающие кольца и открытые сквозные ячейки. "
            "shape=круг/сектор/угол/треугольник задаёт паутину; крыло и плавник "
            "по умолчанию добавляют тонкую мембрану с вогнутыми промежутками "
            "между рёбрами. membrane=нет оставляет только открытую сеть.",
    example="паутина = web shape=круг radius=70 radials=12 rings=5 wire=0.8 sag=.14\n"
            "сектор = паутина shape=сектор radius=80 angle=220 radials=9 rings=4\n"
            "крыло = web shape=крыло radius=110 angle=145 radials=7 scallop=.34 membrane=да\n"
            "плавник = web shape=плавник radius=75 angle=105 radials=8 scallop=.28",
    params={"shape": "круг, сектор, угол, треугольник, крыло или плавник (круг)",
            "radius": "радиус/длина от корня, мм (60)",
            "aspect": "ширина эллиптического веера относительно radius (1; крыло 0.8)",
            "angle": "раствор сектора/веера, ° (сектор 180, крыло 145, плавник 105)",
            "start": "начало сектора или центральное направление крыла, ° (0)",
            "radials": "число радиальных нитей/рёбер (12; крыло 7)",
            "rings": "число дуговых колец (5; крыло/плавник 0)",
            "wire": "диаметр радиальных нитей, мм (0.8)",
            "ring_wire": "диаметр колец, мм (0.75 wire)",
            "sag": "провисание колец между нитями, доля 0…0.45 (0.12)",
            "bend": "боковой изгиб каждой радиальной нити, мм (0)",
            "frame": "капсульная нить по наружному контуру (да; для крыла нет)",
            "membrane": "да — тонкая сплошная перепонка, нет — сквозная сеть",
            "membrane_thick": "толщина перепонки, мм (0.35 wire)",
            "scallop": "вогнутость края мембраны между рёбрами 0…0.75 (крыло 0.34)",
            "sides": "сегментов круглого сечения нити 6…16 (8)",
            "plane": "плашмя — сеть в XY, фронт — стоит лицом в −Y (плашмя)",
            "at": "положение [x,y,z]", "center": "центрировать по Z"},
    positional=["radius"])
def web(a, name):
    raw = (a.text("shape", "круг") or "круг").strip().lower()
    shape = {"круг": "круг", "круговая": "круг", "circle": "круг",
             "сектор": "сектор", "веер": "сектор", "sector": "сектор",
             "угол": "угол", "угловая": "угол", "corner": "угол",
             "треугольник": "треугольник", "треугольная": "треугольник",
             "triangle": "треугольник", "крыло": "крыло", "wing": "крыло",
             "дракон": "крыло", "летучая_мышь": "крыло",
             "плавник": "плавник", "fin": "плавник", "рыба": "плавник"}.get(raw)
    if shape is None:
        raise GeometryError("web: shape=круг, сектор, угол, треугольник, крыло или плавник.")
    fan = shape in ("сектор", "угол", "крыло", "плавник")
    full = not fan
    radius = float(a.num("radius", 60.0, minv=2.0, maxv=10000.0))
    default_aspect = 0.8 if shape in ("крыло", "плавник") else 1.0
    aspect = float(a.num("aspect", default_aspect, minv=0.15, maxv=4.0))
    default_angle = {"сектор": 180.0, "угол": 90.0, "крыло": 145.0,
                     "плавник": 105.0}.get(shape, 360.0)
    angle = float(a.num("angle", default_angle, minv=10.0, maxv=360.0) or default_angle)
    if shape == "угол" and not a.has("angle"):
        angle = 90.0
    start = float(a.num("start", 0.0) or 0.0)
    radials = int(a.int("radials", 7 if shape in ("крыло", "плавник") else 12,
                        minv=2, maxv=80) or 2)
    if full and radials < 3:
        raise GeometryError("web: у замкнутой паутины нужно не меньше трёх радиальных нитей.")
    rings = int(a.int("rings", 0 if shape in ("крыло", "плавник") else 5,
                      minv=0, maxv=30) or 0)
    wire = float(a.num("wire", 0.8, minv=0.05, maxv=radius * 0.15))
    ring_wire = float(a.num("ring_wire", wire * 0.75, minv=0.04, maxv=radius * 0.15))
    sag = float(a.num("sag", 0.12, minv=0.0, maxv=0.45) or 0.0)
    bend = float(a.num("bend", 0.0, minv=-radius, maxv=radius) or 0.0)
    membrane = a.boolean("membrane", shape in ("крыло", "плавник"))
    membrane_thick = float(a.num("membrane_thick", wire * 0.35,
                                 minv=0.02, maxv=radius * 0.1))
    scallop = float(a.num("scallop", 0.34 if shape == "крыло" else
                          0.28 if shape == "плавник" else 0.0,
                          minv=0.0, maxv=0.75) or 0.0)
    frame = a.boolean("frame", shape not in ("крыло", "плавник"))
    sides = int(a.int("sides", 8, minv=6, maxv=16) or 8)

    if shape == "треугольник":
        # Равносторонний треугольник с вершиной по направлению start.
        polygon = np.asarray([(radius * math.cos(math.radians(start + 90 + 120 * k)),
                               radius * math.sin(math.radians(start + 90 + 120 * k)))
                              for k in range(3)], dtype=np.float64)
    else:
        polygon = None

    def boundary(theta_deg: float) -> np.ndarray:
        theta = math.radians(theta_deg)
        if polygon is not None:
            direction = np.asarray([math.cos(theta), math.sin(theta)])
            return direction * _ray_polygon_distance(np.zeros(2), direction, polygon)
        return np.asarray([radius * math.cos(theta), radius * aspect * math.sin(theta)])

    if full:
        angles = [start + 360.0 * j / radials for j in range(radials)]
    elif shape in ("крыло", "плавник"):
        angles = [start - angle / 2.0 + angle * j / (radials - 1) for j in range(radials)]
    else:
        angles = [start + angle * j / (radials - 1) for j in range(radials)]
    ends = [boundary(theta) for theta in angles]

    parts: list[mf.Manifold] = []
    for end in ends:
        length = float(np.linalg.norm(end))
        side = np.asarray([-end[1], end[0]]) / max(length, 1e-9)
        path = []
        for i in range(9):
            t = i / 8.0
            path.append(end * t + side * (bend * math.sin(math.pi * t)))
        # Не ставим несколько плоских крышек точно в общий корень.  Сдвиг
        # меньше диаметра нити и потому неразличим в модели, зато убирает
        # совпадающие fan-треугольники на стыке.  Для мембраны слегка
        # заводим ребро за контур: иначе его торец и вертикальная стенка
        # перепонки соприкасаются по одной линии без объёмного перекрытия.
        if length > 1e-9 and (not membrane or shape in ("крыло", "плавник")):
            root_shift = min(length * 0.00125, wire * 0.75)
            path[0] = path[0] + (path[1] - path[0]) * (root_shift /
                         max(float(np.linalg.norm(path[1] - path[0])), 1e-9))
            if membrane:
                tangent = path[-1] - path[-2]
                path[-1] = path[-1] + tangent / max(float(np.linalg.norm(tangent)), 1e-9) * (wire * 0.05)
        parts.append(_thread(path, wire, sides, "радиальной нити"))

    # Центральный узел нужен только открытой сети без перепонки.  У
    # вееров используем маленький кубический узел: его плоские грани не
    # образуют тонкие сферические лоскуты с корнями рёбер.  В круге и
    # секторе кольца уже связывают нити, а круглый узел даёт гладкий стык.
    if not membrane:
        hub_radius = max(wire, ring_wire) * 1.25
        if shape in ("крыло", "плавник"):
            parts.append(mf.Manifold.cube((2.0 * hub_radius,) * 3, True))
        else:
            parts.append(mf.Manifold.sphere(hub_radius, max(12, sides * 2)))

    def arc_points(j: int, fraction: float, amount: float, samples: int = 9):
        """Дуга между соседними нитями; середина провисает к корню."""
        theta0 = angles[j]
        theta1 = angles[(j + 1) % radials]
        if full and j + 1 == radials:
            theta1 += 360.0
        points = []
        for k in range(samples + 1):
            u = k / samples
            if polygon is None:
                point = boundary(theta0 + (theta1 - theta0) * u)
            else:
                point = ends[j] * (1.0 - u) + ends[(j + 1) % radials] * u
            point = point * (fraction * (1.0 - amount * math.sin(math.pi * u)))
            points.append(point)
        return points

    segments = radials if full else radials - 1
    for ring in range(rings):
        fraction = (ring + 1.0) / (rings + 1.0)
        path = []
        for j in range(segments):
            points = arc_points(j, fraction, sag)
            path.extend(points if not path else points[1:])
        parts.append(_thread(path, ring_wire, sides, "кольца паутины", closed=full))
    if frame:
        path = []
        for j in range(segments):
            points = arc_points(j, 1.0, scallop if membrane else sag)
            path.extend(points if not path else points[1:])
        parts.append(_thread(path, wire, sides, "наружного контура", closed=full))

    if membrane:
        outline = []
        for j in range(segments):
            points = arc_points(j, 1.0, scallop, samples=12)
            outline.extend(points if not outline else points[1:])
        if not full:
            outline.insert(0, np.zeros(2))
        cross = mf.CrossSection([_profile(outline)])
        if cross.is_empty() or cross.area() <= 1e-7:
            raise GeometryError("web: мембрана выродилась; уменьшите scallop/bend.")
        skin = cross.extrude(membrane_thick).translate((0.0, 0.0, -membrane_thick / 2.0))
        parts.append(skin)

    if membrane and shape not in ("крыло", "плавник"):
        # У открытого сектора пакетный union иногда оставляет два
        # совпадающих ребра на стыке перепонки и крайней нити.  Последовательное
        # объединение здесь детерминированно сохраняет объёмное перекрытие;
        # для обычной сети остаётся быстрый batch_boolean.
        solid = parts[0]
        for part in parts[1:]:
            solid = solid + part
    else:
        solid = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
    if solid.is_empty() or solid.volume() <= 1e-8:
        raise GeometryError("web: не удалось собрать нити в объёмную сеть.")
    components = len([p for p in solid.decompose() if p.volume() > 1e-8])
    if components != 1:
        raise GeometryError(f"web: сеть распалась на {components} частей.",
                            hint="Увеличите wire или число колец; нити должны пересекаться.")
    if a.has("plane"):
        solid = stand_flat_sign(a, solid)
    solid = anchor(solid, a.vec("at", 3, default=(0.0, 0.0, 0.0)),
                   a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="web")
    out.meta.update(shape=shape, radials=radials, rings=rings, wire=wire,
                    ring_wire=ring_wire, sag=sag, bend=bend, membrane=membrane,
                    scallop=scallop, open_cells=not membrane)
    out.notes.append(f"{shape}: {radials} радиальных нитей, {rings} колец, "
                     f"прут {wire:g}/{ring_wire:g} мм; "
                     + ("тонкая мембрана" if membrane else "сквозные открытые ячейки"))
    return out
