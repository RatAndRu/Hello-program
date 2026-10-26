"""Поверхности: складки, карты высот, поры, чешуя, решётки, кора, кладка, починка.

Все команды этого модуля работают с **готовым телом**: берут его сетку,
меняют вершины или вычитают/добавляют детали, и собирают тело обратно через
``manifold_from_arrays``. Поэтому они применимы к любой фигуре — вазе,
коробке, скану, — а не только к своим примитивам.

Общий приём — «сдвинуть вершины по нормали на функцию от координат»: одна
формула даёт плиссе, гофру, кору, мятую ткань и рябь. Второй приём —
«поставить детали по поверхности»: лучи изнутри наружу находят точки и
нормали, по ним раскладываются чешуйки, поры и листья.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, manifold_mesh
from .ops_shape import shell_manifold
from .ops import make_solid, op
from .ops_extra import _derived, _fuse_surface, _one
from .ops_shapes import _cross, _profile, ensure_volume

MAX_DEFORM_TRIS = 400_000


# --------------------------------------------------------------------------- #
#  Общие помощники: сетка, нормали, деформация
# --------------------------------------------------------------------------- #
def _vertex_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Нормали вершин: сумма нормалей треугольников (без разделения по граням)."""
    tri = verts[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    vn = np.zeros_like(verts)
    for k in range(3):
        np.add.at(vn, faces[:, k], n)
    ln = np.linalg.norm(vn, axis=1, keepdims=True)
    return vn / np.maximum(ln, 1e-12)


def _refine_for(m: mf.Manifold, refine: float, cap: int = 300_000) -> float:
    """Подбирает шаг дробления так, чтобы после деформации не было миллиона граней.

    Площадь поверхности известна, поэтому ожидаемое число треугольников
    считается заранее: N ≈ 2·S / L². Если выходит слишком много — шаг
    увеличивается (узор станет грубее, но модель останется живой).
    """
    area = float(m.surface_area())
    need = 2.0 * area / max(refine * refine, 1e-9)
    if need <= cap:
        return float(refine)
    return float(math.sqrt(2.0 * area / cap))


def _deform(m: mf.Manifold, fn, what: str = "деформации",
            refine: float | None = None) -> mf.Manifold:
    """Сдвигает вершины тела по нормали: ``fn(verts, normals) -> offsets``."""
    if refine and refine > 0:
        m = m.refine_to_length(_refine_for(m, float(refine)))
    verts, faces = manifold_mesh(m)
    if len(verts) == 0 or len(faces) == 0:
        raise GeometryError(f"У {what} нет сетки: нечего менять.")
    if len(verts) > MAX_DEFORM_TRIS:
        raise GeometryError(
            f"Слишком плотная сетка для {what}: {len(verts):,} вершин.".replace(",", " "),
            hint="Сначала упростите деталь командой simplify.")
    normals = _vertex_normals(verts, faces)
    offs = np.asarray(fn(verts, normals), dtype=np.float64).reshape(-1)
    if len(offs) != len(verts) or not np.all(np.isfinite(offs)):
        raise GeometryError(f"{what.capitalize()}: функция деформации дала неверные смещения.")
    moved = verts + normals * offs[:, None]
    if not np.all(np.isfinite(moved)):
        raise GeometryError(f"{what.capitalize()}: в сетке появились нечисловые координаты.")
    return manifold_from_arrays(moved, faces, what)


def _hash01(ix, iy, iz, seed: int) -> np.ndarray:
    """Детерминированный «случайный» 0…1 по целым координатам."""
    x = (np.asarray(ix, dtype=np.int64) * 374761393
         + np.asarray(iy, dtype=np.int64) * 668265263
         + np.asarray(iz, dtype=np.int64) * 1442695040
         + int(seed) * 1013904223)
    x = (x ^ (x >> 13)) * 1274126177
    x = x ^ (x >> 16)
    return (x & 0xFFFFFF).astype(np.float64) / float(0xFFFFFF)


def _value_noise(pts: np.ndarray, seed: int = 0) -> np.ndarray:
    """Гладкий шум 0…1: кубическая интерполяция случайных значений в узлах."""
    p = np.asarray(pts, dtype=np.float64)
    i = np.floor(p).astype(np.int64)
    f = p - i
    f = f * f * (3.0 - 2.0 * f)          # smoothstep

    def corner(dx, dy, dz):
        return _hash01(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz, seed)

    c00 = corner(0, 0, 0) * (1 - f[:, 0]) + corner(1, 0, 0) * f[:, 0]
    c10 = corner(0, 1, 0) * (1 - f[:, 0]) + corner(1, 1, 0) * f[:, 0]
    c01 = corner(0, 0, 1) * (1 - f[:, 0]) + corner(1, 0, 1) * f[:, 0]
    c11 = corner(0, 1, 1) * (1 - f[:, 0]) + corner(1, 1, 1) * f[:, 0]
    c0 = c00 * (1 - f[:, 1]) + c10 * f[:, 1]
    c1 = c01 * (1 - f[:, 1]) + c11 * f[:, 1]
    return c0 * (1 - f[:, 2]) + c1 * f[:, 2]


def _fbm(pts: np.ndarray, octaves: int = 3, seed: int = 0) -> np.ndarray:
    """Фрактальный шум в диапазоне −1…1."""
    total = np.zeros(len(pts), dtype=np.float64)
    amp, freq, norm = 1.0, 1.0, 0.0
    for k in range(max(1, octaves)):
        total += amp * (_value_noise(pts * freq, seed + k * 17) - 0.5) * 2.0
        norm += amp
        amp *= 0.55
        freq *= 2.07
    return total / max(norm, 1e-9)


def _surface_samples(verts: np.ndarray, faces: np.ndarray, count: int,
                     rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """``count`` случайных точек на поверхности (по площади) и их нормали."""
    tri = verts[faces]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(n, axis=1) / 2.0
    total = float(area.sum())
    if total <= 1e-12:
        raise GeometryError("Поверхность пустая: не с чего брать точки.")
    idx = rng.choice(len(faces), size=int(count), p=area / total)
    # случайная точка внутри треугольника (равномерно)
    r1 = np.sqrt(rng.random(len(idx)))
    r2 = rng.random(len(idx))
    a, b, c = tri[idx, 0], tri[idx, 1], tri[idx, 2]
    pts = (a * (1 - r1)[:, None] + b * (r1 * (1 - r2))[:, None] + c * (r1 * r2)[:, None])
    nor = n[idx] / np.maximum(np.linalg.norm(n[idx], axis=1), 1e-12)[:, None]
    return pts, nor


def _frame(normal: np.ndarray, hint=(0.0, 0.0, 1.0)) -> np.ndarray:
    """Матрица 3×4: локальная Z смотрит по нормали, локальный X — по касательной."""
    z = np.asarray(normal, dtype=np.float64)
    z = z / max(float(np.linalg.norm(z)), 1e-12)
    up = np.asarray(hint, dtype=np.float64)
    if abs(float(np.dot(up, z))) > 0.95:
        up = np.array([1.0, 0.0, 0.0])
    x = np.cross(up, z)
    x /= max(float(np.linalg.norm(x)), 1e-12)
    y = np.cross(z, x)
    mat = np.eye(3, 4, dtype=np.float64)
    mat[:, 0], mat[:, 1], mat[:, 2] = x, y, z
    return mat


# --------------------------------------------------------------------------- #
#  Мятая поверхность: складки, гофра, шум, клетка, трещины
# --------------------------------------------------------------------------- #
@op("wrinkle", aliases=("складки", "гофра", "мятая", "морщины", "рябь", "crumple"),
    category="Форма и деформации",
    summary="Деформирует наружную поверхность готового тела: mode=радиус — "
            "плиссе вокруг выбранной оси, высота — кольца вдоль неё, шум — "
            "нерегулярная мятость, клетка — стёганый узор, трещины — узкие "
            "борозды. surface=наружная оставляет внутреннюю стенку рукава "
            "неподвижной, surface=вся деформирует обе. Сетка автоматически "
            "разбивается минимум на десять отрезков на волну, без диагональных "
            "полос от слишком крупных треугольников.",
    example="ваза = cylinder radius=40 height=90\n"
            "wrinkle ваза amp=2 freq=14 mode=радиус axis=z surface=наружная\n"
            "сосуд = cylinder radius=40 height=90\n"
            "wrinkle сосуд amp=3 freq=20 mode=высота seed=3",
    params={"objects": "объект [a] или a",
            "amp": "амплитуда, мм (2)",
            "freq": "число волн по кругу/вдоль оси или масштаб шума (12)",
            "mode": "радиус, высота, шум, клетка или трещины — «радиус»",
            "axis": "ось рукава и колец: x, y или z (z)",
            "surface": "наружная — только внешняя стенка; вся — включая внутреннюю",
            "seed": "сдвиг узора, целое (0)",
            "detail": "явная длина ребра, мм (авто: длина волны/10…12)",
            "twist": "закрутка волн вдоль оси, градусы на всю длину (0)"},
    positional=["objects"])
def wrinkle(a, name):
    base = _one(a, "wrinkle")
    amp = float(a.num("amp", 2.0, minv=0.0))
    freq = float(a.num("freq", 12.0, minv=0.5))
    mode = (a.text("mode") or "радиус").strip().lower()
    mode = {"радиус": "радиус", "radius": "радиус", "высота": "высота", "height": "высота",
            "кольца": "высота", "шум": "шум", "noise": "шум", "мятая": "шум",
            "клетка": "клетка", "checker": "клетка", "стежка": "клетка",
            "трещины": "трещины", "cracks": "трещины"}.get(mode)
    if mode is None:
        raise GeometryError(f"Неизвестный режим складок «{a.text('mode')}».",
                            hint="mode: радиус, высота, шум, клетка или трещины.")
    axis_raw = (a.text("axis", "z") or "z").strip().lower()
    axis_raw = {"х": "x", "у": "y", "з": "z"}.get(axis_raw, axis_raw)
    if axis_raw not in ("x", "y", "z"):
        raise GeometryError("wrinkle: axis=x, y или z.")
    axis = "xyz".index(axis_raw)
    others = [i for i in range(3) if i != axis]
    surface = (a.text("surface", "наружная") or "наружная").strip().lower()
    if surface in ("все", "всё", "all", "обе"):
        surface = "вся"
    elif surface in ("outer", "снаружи", "внешняя"):
        surface = "наружная"
    if surface not in ("наружная", "вся"):
        raise GeometryError("wrinkle: surface=наружная или вся.")
    if amp <= 1e-6:
        return _derived(a, name, base.manifold, base, "wrinkle")
    seed = int(a.num("seed", 0) or 0)
    twist = math.radians(float(a.num("twist", 0.0) or 0.0))
    m = base.manifold
    bb = m.bounding_box()
    ext = np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])
    c0 = (bb[others[0]] + bb[others[0] + 3]) * 0.5
    c1 = (bb[others[1]] + bb[others[1] + 3]) * 0.5
    z0, height = bb[axis], max(float(ext[axis]), 1e-6)
    radial_span = max(float(ext[others[0]]), float(ext[others[1]]), 1e-6)
    waves = max(1, int(round(freq)))
    # Ненулевая фаза и второй, несинхронный гармонический компонент ломают
    # зеркальную симметрию даже при seed=0. Seed меняет не только поворот
    # узора, но и его фазу/нерегулярность, поэтому действительно работает.
    phase = 0.23 + 0.61803398875 * seed
    if mode == "радиус":
        wavelength = math.pi * radial_span / waves
    elif mode == "высота":
        wavelength = height / max(freq, 0.5)
    elif mode == "клетка":
        wavelength = radial_span / max(freq, 0.5)
    else:
        wavelength = max(radial_span, height) / max(freq, 0.5) * 0.7
    auto_refine = max(0.05, wavelength / (12.0 if mode in ("радиус", "трещины") else 10.0))
    detail = a.num("detail", None, minv=0.02)
    refine = float(detail) if detail else auto_refine

    def offsets(verts: np.ndarray, normals: np.ndarray) -> np.ndarray:
        u = verts[:, others[0]] - c0
        v = verts[:, others[1]] - c1
        z = verts[:, axis] - z0
        phi = np.arctan2(v, u)
        if mode == "радиус":
            ang = phi + twist * (z / height)
            ang += 0.075 * np.sin(3.0 * phi + phase) + 0.035 * np.sin(5.0 * phi - phase)
            off = amp * (0.86 * np.cos(waves * ang + phase)
                         + 0.14 * np.sin((waves + 1) * ang - 0.7 * phase))
        elif mode == "высота":
            off = amp * (0.86 * np.cos(2.0 * math.pi * freq * z / height + phase)
                         + 0.14 * np.sin(2.0 * math.pi * (freq + 1.0) * z / height - phase))
        elif mode == "шум":
            scale = freq / max(float(ext.max()), 1.0)
            shift = np.asarray([0.37 * seed, -0.19 * seed, 0.23 * seed])
            off = amp * _fbm(verts * scale + shift, 4, seed)
        elif mode == "клетка":
            k = 2.0 * math.pi * freq / radial_span
            off = amp * 0.5 * (np.cos(k * u + phase) * np.cos(k * v - 0.4 * phase)
                               + np.cos(k * z + 0.7 * phase))
        else:
            # Целое waves — периодический шов отсутствует. Узкий профиль
            # делает именно впадины, а не выпуклые вертикальные рейки.
            wobble = 0.28 * _fbm(np.stack([np.cos(phi) * 3.0, np.sin(phi) * 3.0,
                                           z / max(height / 8.0, 1.0)], axis=1), 2, seed)
            ridge = np.abs(np.sin(0.5 * waves * (phi + wobble) + 0.37 * phase))
            off = -amp * (1.0 - np.power(np.clip(ridge, 0.0, 1.0), 0.42))
        if mode in ("радиус", "трещины"):
            # Угловой узор определён на боковой стенке. На торцевом веере он
            # превращался в звезду и радиальные сектора. Плавное затухание по
            # координате (не по усреднённой нормали) сохраняет торец и кромку
            # исходными и не оставляет зубцов на первом ряде треугольников.
            edge = np.clip(np.minimum(z, height - z) / (height * 0.08), 0.0, 1.0)
            edge = edge * edge * (3.0 - 2.0 * edge)
            off = off * edge
        if surface == "наружная":
            radial = np.stack([u, v], axis=1)
            length = np.linalg.norm(radial, axis=1)
            radial /= np.maximum(length, 1e-12)[:, None]
            dot = normals[:, others[0]] * radial[:, 0] + normals[:, others[1]] * radial[:, 1]
            # Торцы не отсекаем. Отсекаются только боковые нормали, смотрящие
            # к оси: это внутренняя стенка рукава или внутренняя сторона кольца.
            inner = (np.abs(normals[:, axis]) < 0.85) & (dot < -0.15)
            off = np.where(inner, 0.0, off)
        return off

    solid = _deform(m, offsets, "складки", refine=refine)
    a.scene.log("info", f"складки: {mode}, axis={axis_raw}, surface={surface}, "
                        f"амплитуда {amp:g} мм, частота {freq:g}, ребро {refine:g} мм, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return _derived(a, name, solid, base, "wrinkle")


# --------------------------------------------------------------------------- #
#  Трещины: удар, разлом и продольные ложбинки древесины
# --------------------------------------------------------------------------- #
@op("crack", aliases=("трещина", "трещины", "потрескивание", "разлом", "fracture",
                      "wood_grain", "растрескивание"),
    category="Форма и деформации",
    summary="Вдавливает настоящие трещины в выбранную поверхность. mode=удар — "
            "радиальные ветви от at; разлом — длинная неровная трещина с "
            "ответвлениями; дерево — ровные продольные ложбинки вдоль волокон. "
            "at и dir выбирают грань, radius — размер области, width/depth — "
            "ширину и глубину борозды. Линии проецируются на реальную сетку "
            "лучами, поэтому работают и на плоскости, и на выпуклом теле.",
    example="плита = box size=[100,80,16]\n"
            "crack плита mode=удар at=[0,0,16] dir=[0,0,1] count=8 radius=35 width=1.4 depth=1.2\n"
            "доска = box size=[140,60,12]\n"
            "crack доска mode=дерево count=14 width=1 depth=.7 angle=0",
    params={"objects": "объект [a] или a",
            "mode": "удар, разлом или дерево — «удар»",
            "at": "центр сети/области [x,y,z] (центр верхней грани)",
            "dir": "наружная нормаль выбранной поверхности [x,y,z]",
            "radius": "полуразмер области, мм (по габариту и режиму)",
            "count": "лучей удара, ветвей разлома или линий дерева",
            "width": "полная ширина борозды, мм (1.4)",
            "depth": "глубина борозды, мм (1.2)",
            "angle": "поворот направления в касательной плоскости, ° (0)",
            "seed": "повторяемая форма ветвей (0)",
            "detail": "явная длина ребра, мм (авто width/4)"},
    positional=["objects"])
def crack(a, name):
    base = _one(a, "crack")
    mode = (a.text("mode", "удар") or "удар").strip().lower()
    mode = {"удар": "удар", "impact": "удар", "разлом": "разлом", "землетрясение": "разлом",
            "fracture": "разлом", "дерево": "дерево", "волокна": "дерево",
            "древесина": "дерево", "wood": "дерево"}.get(mode)
    if mode is None:
        raise GeometryError("crack: mode=удар, разлом или дерево.")
    m = base.manifold
    bb = m.bounding_box()
    centre = np.array([(bb[i] + bb[i + 3]) * 0.5 for i in range(3)])
    at_raw = a.vec("at", 3, default=None)
    at = (np.array([centre[0], centre[1], bb[5]]) if at_raw is None
          else np.asarray(at_raw, dtype=np.float64).reshape(3))
    dir_raw = a.vec("dir", 3, default=None)
    normal = (np.asarray(dir_raw, dtype=np.float64).reshape(3) if dir_raw is not None
              else at - centre)
    if float(np.linalg.norm(normal)) < 1e-9:
        normal = np.array([0.0, 0.0, 1.0])
    normal /= float(np.linalg.norm(normal))
    ext = np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])
    default_count = 12 if mode == "дерево" else 5 if mode == "разлом" else 8
    count = int(a.num("count", default_count, minv=1, maxv=80))
    width = float(a.num("width", 1.4, minv=0.05, maxv=1000.0))
    depth = float(a.num("depth", 1.2, minv=0.02, maxv=1000.0))
    radius_default = float(ext.max()) * (0.60 if mode == "дерево" else 0.36)
    radius = float(a.num("radius", radius_default, minv=0.5, maxv=10_000.0))
    seed = int(a.num("seed", 0) or 0)
    rng = np.random.default_rng(seed)

    grain = np.array([0.0, 0.0, 1.0]) if abs(normal[2]) < 0.85 else np.array([1.0, 0.0, 0.0])
    e1 = grain - normal * float(np.dot(grain, normal))
    e1 /= max(float(np.linalg.norm(e1)), 1e-12)
    e2 = np.cross(normal, e1)
    e2 /= max(float(np.linalg.norm(e2)), 1e-12)
    angle = math.radians(float(a.num("angle", 0.0, minv=-180.0, maxv=180.0)))
    e1, e2 = (e1 * math.cos(angle) + e2 * math.sin(angle),
              -e1 * math.sin(angle) + e2 * math.cos(angle))

    paths2: list[np.ndarray] = []
    if mode == "удар":
        for i in range(count):
            phi = 2.0 * math.pi * (i + rng.uniform(-0.16, 0.16)) / count
            direction = np.array([math.cos(phi), math.sin(phi)])
            side = np.array([-direction[1], direction[0]])
            length = radius * rng.uniform(0.68, 1.12)
            t = np.linspace(0.0, 1.0, 8)
            jitter = np.cumsum(rng.normal(0.0, width * 0.55, len(t)))
            jitter -= jitter[0]
            jitter *= np.sin(math.pi * t)
            line = direction[None, :] * (length * t)[:, None] + side[None, :] * jitter[:, None]
            paths2.append(line)
            # Каждая вторая главная трещина даёт короткое боковое ответвление.
            if i % 2 == 0:
                start = line[len(line) // 2]
                branch_phi = phi + rng.choice([-1.0, 1.0]) * rng.uniform(0.55, 1.0)
                bd = np.array([math.cos(branch_phi), math.sin(branch_phi)])
                bt = np.linspace(0.0, 1.0, 5)
                branch = start[None, :] + bd[None, :] * (radius * 0.36 * bt)[:, None]
                branch += rng.normal(0.0, width * 0.30, branch.shape) * np.sin(math.pi * bt)[:, None]
                paths2.append(branch)
    elif mode == "разлом":
        t = np.linspace(-1.0, 1.0, 17)
        jitter = np.cumsum(rng.normal(0.0, width * 0.75 + radius * 0.008, len(t)))
        jitter -= np.linspace(jitter[0], jitter[-1], len(t))
        paths2.append(np.stack([radius * t, jitter], axis=1))
        for _ in range(count):
            start_t = rng.uniform(-0.72, 0.72)
            start = np.array([radius * start_t,
                              float(np.interp(start_t, t, jitter))])
            phi = rng.choice([-1.0, 1.0]) * rng.uniform(0.55, 1.15)
            if rng.random() < 0.5:
                phi += math.pi
            direction = np.array([math.cos(phi), math.sin(phi)])
            bt = np.linspace(0.0, 1.0, 6)
            branch = start[None, :] + direction[None, :] * (radius * rng.uniform(0.22, 0.48) * bt)[:, None]
            branch += rng.normal(0.0, width * 0.35, branch.shape) * np.sin(math.pi * bt)[:, None]
            paths2.append(branch)
    else:
        for i in range(count):
            across = 0.0 if count == 1 else -radius + 2.0 * radius * i / (count - 1)
            t = np.linspace(-1.0, 1.0, 11)
            wobble = width * 0.30 * np.sin(t * math.pi * 2.0 + rng.uniform(0.0, 2.0 * math.pi))
            paths2.append(np.stack([radius * t, across + wobble], axis=1))

    reach = float(np.linalg.norm(ext)) * 1.5 + 10.0
    paths3: list[np.ndarray] = []

    def project(line: np.ndarray):
        current = []
        for uv in line:
            q = at + e1 * float(uv[0]) + e2 * float(uv[1])
            start = q + normal * reach
            end = q - normal * reach
            hits = m.ray_cast([float(v) for v in start], [float(v) for v in end])
            if not hits:
                if len(current) >= 2:
                    paths3.append(np.asarray(current))
                current = []
                continue
            hit = min(hits, key=lambda h: float(np.linalg.norm(np.asarray(h.position) - start)))
            current.append(np.asarray(hit.position, dtype=np.float64))
        if len(current) >= 2:
            paths3.append(np.asarray(current))

    for line in paths2:
        project(line)
    if not paths3:
        raise GeometryError("Трещины не попали на поверхность.",
                            hint="Проверьте at/dir и увеличьте radius.")
    segments = [(path[i], path[i + 1]) for path in paths3 for i in range(len(path) - 1)
                if float(np.linalg.norm(path[i + 1] - path[i])) > 1e-8]
    detail = a.num("detail", None, minv=0.02)
    # Три сегмента на ширину достаточно для V-профиля; четвёртый ранее
    # почти удваивал полигонаж без заметного выигрыша на печатной детали.
    refine = float(detail) if detail else max(0.05, width / 3.0)

    def offsets(verts: np.ndarray, normals: np.ndarray) -> np.ndarray:
        best = np.full(len(verts), np.inf)
        for p0, p1 in segments:
            vector = p1 - p0
            denom = max(float(vector @ vector), 1e-18)
            t = np.clip(((verts - p0) @ vector) / denom, 0.0, 1.0)
            delta = verts - (p0[None, :] + t[:, None] * vector[None, :])
            best = np.minimum(best, np.sum(delta * delta, axis=1))
        q = np.clip(np.sqrt(best) / (width * 0.5), 0.0, 1.0)
        if mode == "дерево":
            profile = (1.0 - q * q) ** 2
        else:
            # V-образная трещина с коротким сглаживанием самой кромки.
            profile = 1.0 - q
            profile = profile * profile * (3.0 - 2.0 * profile)
        return -depth * profile

    solid = _deform(m, offsets, "трещин", refine=refine)
    solid = solid.simplify(max(0.005, refine * 0.018))
    if solid.volume() >= m.volume() - 1e-7:
        raise GeometryError("Трещины не углубили поверхность: увеличьте depth или уменьшите detail.")
    a.scene.log("info", f"crack: {mode}, линий {len(paths3)}, сегментов {len(segments)}, "
                        f"width={width:g}, depth={depth:g}, seed={seed}", a.cmd.line)
    out = _derived(a, name, solid, base, "crack")
    out.notes.append(f"трещины: {mode}, линий {len(paths3)}, width={width:g}, depth={depth:g}")
    return out


# --------------------------------------------------------------------------- #
#  Карта высот: узор картинкой
# --------------------------------------------------------------------------- #
def _load_heightmap(path: str) -> np.ndarray:
    """Картинка → массив 0…1 (яркость), строки снизу вверх."""
    p = Path(path)
    if not p.exists() and not p.is_absolute():
        # Встроенный пример обязан открываться из любой рабочей папки и из
        # однофайлового EXE, а не только из корня исходников.
        resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        candidate = resource_root / p
        if candidate.exists():
            p = candidate
    if not p.exists():
        raise GeometryError(f"Не найден файл карты высот: {path}.",
                            hint="Положите картинку рядом с проектом и укажите путь; "
                                 "либо используйте встроенную docs/pattern.png.")
    from .geometry import read_png_gray
    if p.suffix.lower() == ".png":
        arr = read_png_gray(p)                  # свой декодер: без Pillow
    else:
        try:
            from PIL import Image
        except ImportError as exc:
            raise GeometryError(
                f"Формат {p.suffix or 'без расширения'} требует Pillow.",
                hint="Сохраните карту высот в PNG — он читается без зависимостей.",
            ) from exc
        img = Image.open(p).convert("L")
        arr = np.asarray(img, dtype=np.float64) / 255.0
    arr = 1.0 - arr                 # белое — выступ, чёрное — впадина
    return arr[::-1]                # строки снизу вверх: как ось Y


def _sample_map(arr: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Билинейная выборка карты с зажимом по краям."""
    h, w = arr.shape[:2]
    x = np.clip(u, 0.0, 1.0) * (w - 1)
    y = np.clip(v, 0.0, 1.0) * (h - 1)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx, fy = x - x0, y - y0
    return (arr[y0, x0] * (1 - fx) * (1 - fy) + arr[y0, x1] * fx * (1 - fy)
            + arr[y1, x0] * (1 - fx) * fy + arr[y1, x1] * fx * fy)


@op("relief", aliases=("рельеф", "карта_высот", "heightmap", "тиснение", "узор"),
    category="Форма и деформации",
    summary="Выдавливает картинку на поверхности: узор на вазе, логотип, принт, "
            "рельеф коры. Читает файл в градациях серого (белое — выступ) и "
            "смещает вершины по нормали. mode=обёртка оборачивает картинку "
            "вокруг оси Z без шва (ваза, кружка, стакан), mode=плоскость кладёт "
            "её на грань в плоскости XY. Встроенная карта docs/pattern.png "
            "подставляется без image и упаковывается в EXE: готовый пример "
            "доступен всегда. Своя картинка задаётся image=путь.png.",
    example='ваза = cylinder radius=40 height=90\n'
            'relief ваза image=docs/pattern.png depth=2 mode=обёртка\n'
            'плита = box size=[120,80,10]\n'
            'relief плита image=docs/pattern.png depth=1 mode=плоскость',
    params={"objects": "объект [a] или a",
            "image": "путь к PNG; без параметра — встроенная docs/pattern.png",
            "depth": "глубина рельефа, мм (2)",
            "mode": "обёртка (вокруг оси Z) или плоскость (по XY) — «обёртка»",
            "invert": "поменять местами выступы и впадины (нет)",
            "offset": "сдвиг узора по кругу, 0…1 (0)",
            "repeat": "сколько раз повторить узор по кругу (1)",
            "detail": "длина ребра перед деформацией, мм (авто depth/2)"},
    positional=["objects"])
def relief(a, name):
    base = _one(a, "relief")
    image = (a.text("image") or "docs/pattern.png").strip()
    depth = float(a.num("depth", 2.0, minv=0.01))
    mode = (a.text("mode") or "обёртка").strip().lower()
    if mode in ("обертка", "wrap", "круг", "цилиндр"):
        mode = "обёртка"
    if mode in ("плоскость", "plane", "плоская", "грань"):
        mode = "плоскость"
    if mode not in ("обёртка", "плоскость"):
        raise GeometryError(f"Неизвестный режим рельефа «{a.text('mode')}».",
                            hint="mode: обёртка или плоскость.")
    invert = a.boolean("invert", False)
    offset = float(a.num("offset", 0.0) or 0.0)
    repeat = float(a.num("repeat", 1.0, minv=1.0) or 1.0)
    arr = _load_heightmap(image)
    bb = base.manifold.bounding_box()
    cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
    z0, z1 = bb[2], bb[5]
    x0, x1, y0, y1 = bb[0], bb[3], bb[1], bb[4]
    detail = a.num("detail", None, minv=0.02)
    refine = float(detail) if detail else max(0.1, depth / 2.0)

    def offsets(verts: np.ndarray, normals: np.ndarray) -> np.ndarray:
        if mode == "обёртка":
            phi = np.arctan2(verts[:, 1] - cy, verts[:, 0] - cx)
            u = phi / (2.0 * math.pi) + 0.5 + offset
            u = np.mod(u * repeat, 1.0)
            v = (verts[:, 2] - z0) / max(z1 - z0, 1e-9)
        else:
            u = (verts[:, 0] - x0) / max(x1 - x0, 1e-9)
            v = (verts[:, 1] - y0) / max(y1 - y0, 1e-9)
        h = _sample_map(arr, u, v)
        # подложка 0.15: узор не «висит» на нуле, низ остаётся плоским
        value = 0.15 + 0.85 * h
        if invert:
            value = 1.15 - value
        return depth * value

    solid = _deform(base.manifold, offsets, "рельефа", refine=refine)
    a.scene.log("info", f"рельеф: {Path(image).name}, {mode}, глубина {depth:g} мм, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return _derived(a, name, solid, base, "relief")


# --------------------------------------------------------------------------- #
#  Пористые: пемза, губка, шоколад, сыр
# --------------------------------------------------------------------------- #
def _pit_tool(radius: float, depth: float, cylindrical: bool, smooth: float,
              rough: float, uneven: float, segments: int,
              rng: np.random.Generator) -> mf.Manifold:
    """Резец ямы с точным раскрытием radius и глубиной depth.

    Локальная ось Z смотрит наружу, плоскость поверхности — z=0. Профиль
    вращения задаёт нижнюю стенку и продолжается над поверхностью. Поэтому
    кромка не зависит от исходной триангуляции, а smooth/rough/uneven меняют
    саму геометрию резца, а не материал.
    """
    r, d = float(radius), float(depth)
    over = max(r, d) * 0.6 + 1.0
    nr = max(6, int(segments))
    if not cylindrical:
        # Сферический сегмент: r² = 2·R·d − d². Это верно и для глубокой
        # ямы (тогда у раскрытия есть вертикальный участок стенки).
        sphere_r = (r * r + d * d) / (2.0 * d)
        qs = np.linspace(0.0, 1.0, nr + 1)[1:]
        rho = r * qs
        z = sphere_r - d - np.sqrt(np.maximum(sphere_r * sphere_r - rho * rho, 0.0))
        if smooth > 1e-9:
            band = max(0.05, 0.5 * smooth)
            w = np.clip((1.0 - qs) / band, 0.0, 1.0)
            w = w * w * (3.0 - 2.0 * w)
            z = z * w
        profile = [(0.0, -d)] + [(float(rr), float(zz)) for rr, zz in zip(rho, z)]
    else:
        # Цилиндр с плоским дном. smooth закругляет только входную кромку;
        # основная стенка остаётся цилиндрической, а не становится конусом.
        shaft = r * (1.0 - 0.30 * smooth)
        bevel = min(d * 0.65, r * 0.9) * smooth
        profile = [(0.0, -d), (shaft, -d)]
        if bevel > 1e-6:
            for t in np.linspace(0.0, 1.0, nr + 1)[1:]:
                ang = float(t) * math.pi * 0.5
                rr = shaft + (r - shaft) * math.sin(ang)
                zz = -bevel + bevel * (1.0 - math.cos(ang))
                profile.append((float(rr), float(zz)))
        else:
            profile.append((r, 0.0))
    profile += [(r, over), (0.0, over)]
    tool = mf.Manifold.revolve(_cross(profile), max(12, segments * 2))
    if rough <= 1e-9 and uneven <= 1e-9:
        return tool

    verts, faces = manifold_mesh(tool)
    rho = np.linalg.norm(verts[:, :2], axis=1)
    phi = np.arctan2(verts[:, 1], verts[:, 0])
    phase = rng.uniform(0.0, 2.0 * math.pi, 3)
    radial_scale = 1.0 + uneven * (0.16 * np.sin(3.0 * phi + phase[0])
                                   + 0.10 * np.sin(5.0 * phi + phase[1])
                                   + 0.06 * np.sin(7.0 * phi + phase[2]))
    verts[:, 0] *= radial_scale
    verts[:, 1] *= radial_scale
    if rough > 1e-9:
        scale = max(r / 3.0, 0.05)
        noise = _fbm(verts / scale, 3, int(rng.integers(0, 2**31 - 1)))
        fade = np.clip(rho / max(r, 1e-9), 0.0, 1.0)
        mask = verts[:, 2] < -1e-6
        delta = rough * min(d, r) * 0.16 * noise * fade * mask
        verts[:, 2] = np.where(mask, np.minimum(verts[:, 2] + delta, -1e-5), verts[:, 2])
    return manifold_from_arrays(verts, faces, "резца поры")


def _spaced_surface_points(verts, faces, count: int, radius: float,
                           rng: np.random.Generator):
    """Ровно count неперекрывающихся раскрытий либо понятный отказ.

    Расстояние 2.05·max_radius гарантирует, что круги раскрытия не сливаются
    даже на соседних гранях. Жадный выбор самой удалённой точки (farthest
    point) даёт равномерную повторяемую раскладку вместо случайных скоплений.
    """
    pool = max(4000, int(count) * 80)
    pts, nor = _surface_samples(verts, faces, pool, rng)
    minimum = max(float(radius) * 2.05, 1e-6)
    chosen = [int(rng.integers(0, len(pts)))]
    best = np.sum((pts - pts[chosen[0]]) ** 2, axis=1)
    best[chosen[0]] = -1.0
    while len(chosen) < count:
        index = int(np.argmax(best))
        if best[index] < minimum * minimum:
            raise GeometryError(
                f"На поверхности не помещаются {count} неперекрывающихся ям "
                f"радиуса {radius:g} мм (размещено {len(chosen)}).",
                hint="Уменьшите size/width, spread или count; либо увеличьте деталь.")
        chosen.append(index)
        best = np.minimum(best, np.sum((pts - pts[index]) ** 2, axis=1))
        best[chosen] = -1.0
    idx = np.asarray(chosen, dtype=np.int64)
    return pts[idx], nor[idx]


@op("porous", aliases=("поры", "пористый", "губка", "пемза", "сыр", "sponge"),
    category="Форма и деформации",
    summary="Сферические ямы, цилиндрические отверстия и внутренние пузыри "
            "с повторяемой раскладкой. size — радиус раскрытия, width — его "
            "диаметр (если задан, имеет приоритет), depth — точная глубина от "
            "поверхности. mode=поры/ячеи — сферические ямы; отверстия/глазки — "
            "цилиндры с плоским дном; пузыри — полости внутри. Раскрытия не "
            "перекрываются: невозможный count отклоняется. smooth закругляет "
            "переход к яме, uneven делает кромку неровной, rough добавляет "
            "шероховатость стенок, seed повторяет весь узор.",
    example="камень = rock size=90 rough=0.4 seed=2\n"
            "porous камень mode=поры size=4 depth=2 count=30 smooth=.35 seed=4\n"
            "плита = box size=[90,60,20]\n"
            "porous плита mode=отверстия width=8 depth=6 count=12 smooth=.2",
    params={"objects": "объект [a] или a",
            "mode": "поры, ячеи, отверстия, глазки или пузыри — «поры»",
            "size": "радиус раскрытия, мм (4)",
            "width": "диаметр раскрытия, мм; перекрывает size",
            "depth": "глубина от исходной поверхности, мм (по режиму)",
            "count": "число неперекрывающихся ям/отверстий; отказ, если не помещаются (60)",
            "seed": "повторяемый seed раскладки и неровностей (0)",
            "spread": "случайный разброс радиусов 0…0.9 (0 — одинаковые)",
            "smooth": "плавный переход к яме 0…1 (0.25)",
            "rough": "шероховатость стенок 0…1 (0); синоним roughness",
            "uneven": "неровность кромки 0…1 (0)",
            "through": "для цилиндров: сквозное отверстие (нет)",
            "detail": "радиальное разбиение профиля 6…24 (12)"},
    positional=["objects"])
def porous(a, name):
    base = _one(a, "porous")
    mode = (a.text("mode") or "поры").strip().lower()
    mode = {"поры": "поры", "пемза": "поры", "pores": "поры", "сфера": "поры",
            "ячеи": "ячеи", "губка": "ячеи", "cells": "ячеи",
            "отверстия": "отверстия", "отверстие": "отверстия", "цилиндры": "отверстия",
            "цилиндрические": "отверстия", "holes": "отверстия", "глазки": "отверстия",
            "сыр": "отверстия", "eyes": "отверстия",
            "пузыри": "пузыри", "шоколад": "пузыри", "bubbles": "пузыри"}.get(mode)
    if mode is None:
        raise GeometryError(f"Неизвестный режим пор «{a.text('mode')}».",
                            hint="mode: поры, ячеи, отверстия, глазки или пузыри.")
    size = float(a.num("size", 4.0, minv=0.2))
    width = a.num("width", None, minv=0.4)
    if width is not None:
        size = float(width) * 0.5
    count = int(a.num("count", 60, minv=1, maxv=600))
    seed = int(a.num("seed", 0) or 0)
    spread = float(a.num("spread", 0.0, minv=0.0, maxv=0.9))
    smooth = float(a.num("smooth", 0.25, minv=0.0, maxv=1.0))
    rough_value = a.num("rough", None, minv=0.0, maxv=1.0)
    rough = float(rough_value if rough_value is not None else
                  a.num("roughness", 0.0, minv=0.0, maxv=1.0))
    uneven = float(a.num("uneven", 0.0, minv=0.0, maxv=1.0))
    seg = int(a.num("detail", 12, minv=6, maxv=24))
    through = a.boolean("through", False)
    default_depth = size * (0.55 if mode == "поры" else 1.0 if mode == "ячеи" else 1.5)
    depth = float(a.num("depth", default_depth, minv=0.05))
    rng = np.random.default_rng(seed)
    m = base.manifold
    bb = m.bounding_box()
    verts, faces = manifold_mesh(m)
    radii = size * (1.0 - spread + 2.0 * spread * rng.random(count))
    holes: list[mf.Manifold] = []

    if mode != "пузыри":
        pts, nor = _spaced_surface_points(verts, faces, count, float(radii.max()), rng)
        if through and mode == "отверстия":
            depth = float(max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])) * 2.5
        for i in range(count):
            tool = _pit_tool(float(radii[i]), depth, mode == "отверстия",
                             smooth, rough, uneven, seg, rng)
            frame = _frame(nor[i])
            frame[:, 3] = pts[i]
            holes.append(tool.transform(frame))
        a.scene.log("info", f"porous: {count} шт., mode={mode}, радиус {size:g}, "
                            f"глубина {depth:g}, smooth={smooth:g}, rough={rough:g}, "
                            f"uneven={uneven:g}", a.cmd.line)
    else:
        lo = np.array([bb[0], bb[1], bb[2]])
        hi = np.array([bb[3], bb[4], bb[5]])
        tries = 0
        while len(holes) < count and tries < count * 60:
            tries += 1
            p = lo + (hi - lo) * rng.random(3)
            r = float(radii[len(holes)])
            near = np.inf
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, -1), (0, -1, 0)):
                end = p + np.asarray(d, dtype=np.float64) * (max(hi - lo) * 2 + 10)
                hits = m.ray_cast([float(v) for v in p], [float(v) for v in end])
                if hits:
                    near = min(near, float(np.linalg.norm(np.asarray(hits[0].position) - p)))
            if np.isfinite(near) and near > r * 1.15:
                holes.append(mf.Manifold.sphere(r, seg).translate(tuple(float(v) for v in p)))
        if len(holes) != count:
            raise GeometryError(f"Размещено только {len(holes)} из {count} пузырей: "
                                "деталь слишком тонкая для такого размера.",
                                hint="Уменьшите size/count или выберите mode=поры.")

    solid = mf.Manifold.batch_boolean([m] + holes, mf.OpType.Subtract)
    solid = ensure_volume(solid, "пористой детали")
    if solid.volume() >= m.volume() - 1e-7:
        raise GeometryError("Поры не изменили объём: проверьте size/depth и поверхность.")
    parts = len([p for p in solid.decompose() if p.volume() > 1e-6])
    if parts > 1:
        a.scene.log("warn", f"пористость разделила тело на {parts} частей — "
                            "уменьшите size/depth или count", a.cmd.line)
    out = _derived(a, name, solid, base, "porous")
    out.notes.append(f"поры: mode={mode}, count={count}, size={size:g}, depth={depth:g}, "
                     f"seed={seed}, smooth={smooth:g}, rough={rough:g}, uneven={uneven:g}")
    return out


# --------------------------------------------------------------------------- #
#  Shrinkwrap — проекция сетки на поверхность другого тела
# --------------------------------------------------------------------------- #
def _shrink_direction(a) -> tuple[str, np.ndarray | None]:
    raw = (a.text("direction", "ближняя") or "ближняя").strip().lower()
    values = {
        "ближняя": ("ближняя", None), "nearest": ("ближняя", None),
        "нормаль": ("нормаль", None), "normal": ("нормаль", None),
        "вниз": ("вниз", np.asarray([0.0, 0.0, -1.0])),
        "-z": ("-Z", np.asarray([0.0, 0.0, -1.0])),
        "вверх": ("вверх", np.asarray([0.0, 0.0, 1.0])),
        "+z": ("+Z", np.asarray([0.0, 0.0, 1.0])),
        "право": ("+X", np.asarray([1.0, 0.0, 0.0])),
        "+x": ("+X", np.asarray([1.0, 0.0, 0.0])),
        "лево": ("-X", np.asarray([-1.0, 0.0, 0.0])),
        "-x": ("-X", np.asarray([-1.0, 0.0, 0.0])),
        "зад": ("+Y", np.asarray([0.0, 1.0, 0.0])),
        "+y": ("+Y", np.asarray([0.0, 1.0, 0.0])),
        "перед": ("-Y", np.asarray([0.0, -1.0, 0.0])),
        "перёд": ("-Y", np.asarray([0.0, -1.0, 0.0])),
        "-y": ("-Y", np.asarray([0.0, -1.0, 0.0])),
    }
    if raw not in values:
        raise GeometryError("shrinkwrap: direction=ближняя, нормаль, вверх, вниз, ±X или ±Y.")
    return values[raw]


def _ray_on(m: mf.Manifold, point: np.ndarray, direction: np.ndarray,
            reach: float):
    norm = float(np.linalg.norm(direction))
    if norm < 1e-10:
        return None
    d = np.asarray(direction, dtype=np.float64) / norm
    end = np.asarray(point, dtype=np.float64) + d * reach
    hits = m.ray_cast([float(v) for v in point], [float(v) for v in end])
    if not hits:
        return None
    hit = hits[0]
    p = np.asarray(hit.position, dtype=np.float64)
    n = np.asarray(hit.normal, dtype=np.float64)
    n /= max(float(np.linalg.norm(n)), 1e-12)
    return p, n


@op("shrinkwrap", aliases=("обтянуть", "шринкwrap", "shrink_wrap",
                           "проекция_на_поверхность", "спроецировать_на"),
    category="Форма и деформации",
    summary="Настоящий Shrinkwrap: вершины ВТОРОГО объекта проецируются лучами "
            "на сетку ПЕРВОГО. gap>0 приподнимает над поверхностью, gap<0 "
            "погружает внутрь. Замкнутая деталь сохраняет локальную толщину: "
            "ближняя сторона получает gap, дальняя — gap плюс толщина. "
            "transition плавно возвращает удалённые вершины к исходной форме; "
            "join=сгладить дополнительно округляет вогнутый стык с целью.",
    example="цель = sphere radius=35\n"
            "плёнка = box size=[65,65,2] at=[0,0,34]\n"
            "плёнка = shrinkwrap [цель, плёнка] gap=0.4 detail=2\n"
            "врезка = shrinkwrap [цель, плёнка] gap=-1 direction=вниз",
    params={"objects": "[цель, деформируемый объект] — строго в этом порядке",
            "gap": "зазор по нормали цели, мм: + нависание, − погружение (0)",
            "direction": "ближняя, нормаль, вверх, вниз, ±X, ±Y (ближняя)",
            "amount": "сила проецирования 0…1 (1)",
            "transition": "ширина плавного затухания по расстоянию до цели, мм (0 — вся сетка)",
            "detail": "шаг дробления исходной сетки, мм (авто; меньше — точнее)",
            "join": "нет — оставить два объекта; слить — boolean; сгладить — слить и скруглить стык",
            "weld": "радиус сглаживания стыка для join=сгладить, мм (2)"},
    positional=["objects"])
def shrinkwrap(a, name):
    solids = a.solids()
    if len(solids) != 2:
        raise GeometryError("shrinkwrap требует ровно два объекта: [цель, объект].")
    target, source = solids
    gap = float(a.num("gap", 0.0) or 0.0)
    amount = float(a.num("amount", 1.0, minv=0.0, maxv=1.0))
    transition = float(a.num("transition", 0.0, minv=0.0) or 0.0)
    join = (a.text("join", "нет") or "нет").strip().lower()
    join = {"нет": "нет", "раздельно": "нет", "none": "нет",
            "слить": "слить", "union": "слить", "сгладить": "сгладить",
            "плавно": "сгладить", "smooth": "сгладить"}.get(join)
    if join is None:
        raise GeometryError("shrinkwrap: join=нет, слить или сгладить.")
    weld = float(a.num("weld", 2.0, minv=0.05))
    direction_name, fixed = _shrink_direction(a)
    source_m = source.manifold
    source_bb = source_m.bounding_box()
    source_size = np.asarray([source_bb[3] - source_bb[0],
                              source_bb[4] - source_bb[1],
                              source_bb[5] - source_bb[2]], dtype=np.float64)
    detail = a.num("detail", None, minv=0.02)
    step = float(detail) if detail is not None else max(0.25, float(np.max(source_size)) / 55.0)
    step = _refine_for(source_m, step, cap=60_000)
    refined = source_m.refine_to_length(step)
    verts, faces = manifold_mesh(refined)
    if len(verts) == 0 or len(faces) == 0:
        raise GeometryError("shrinkwrap: у деформируемого объекта нет сетки.")
    if len(verts) > MAX_DEFORM_TRIS:
        raise GeometryError("shrinkwrap: сетка слишком плотная; увеличьте detail или примените simplify.")
    normals = _vertex_normals(verts, faces)
    target_bb = target.manifold.bounding_box()
    center = np.asarray([(target_bb[0] + target_bb[3]) / 2.0,
                         (target_bb[1] + target_bb[4]) / 2.0,
                         (target_bb[2] + target_bb[5]) / 2.0])
    target_size = np.asarray(target_bb[3:], dtype=np.float64) - np.asarray(target_bb[:3], dtype=np.float64)
    reach = float(np.linalg.norm(target_size) + np.linalg.norm(source_size) +
                  abs(gap) * 4.0 + step * 4.0 + 10.0)
    hp = np.zeros_like(verts)
    hn = np.zeros_like(verts)
    weight = np.zeros(len(verts), dtype=np.float64)
    hits_count = 0
    axes = (np.asarray([1.0, 0.0, 0.0]), np.asarray([-1.0, 0.0, 0.0]),
            np.asarray([0.0, 1.0, 0.0]), np.asarray([0.0, -1.0, 0.0]),
            np.asarray([0.0, 0.0, 1.0]), np.asarray([0.0, 0.0, -1.0]))
    for i, (point, normal) in enumerate(zip(verts, normals)):
        if fixed is not None:
            candidates = (_ray_on(target.manifold, point, fixed, reach),)
        else:
            dirs = [-normal, normal] if direction_name == "нормаль" else [-normal, normal, center - point]
            found = [_ray_on(target.manifold, point, d, reach) for d in dirs]
            found = [hit for hit in found if hit is not None]
            if not found and direction_name == "ближняя":
                found = [_ray_on(target.manifold, point, d, reach) for d in axes]
                found = [hit for hit in found if hit is not None]
            candidates = found
        best = None
        best_dist = math.inf
        for hit in candidates:
            if hit is None:
                continue
            dist = float(np.linalg.norm(hit[0] - point))
            if dist < best_dist:
                best, best_dist = hit, dist
        if best is None:
            continue
        hp[i], hn[i] = best
        w = 1.0
        if transition > 1e-9:
            w = float(np.clip(1.0 - best_dist / transition, 0.0, 1.0))
            w = w * w * (3.0 - 2.0 * w)
        weight[i] = w
        if w > 1e-9:
            hits_count += 1
    if hits_count == 0:
        raise GeometryError("shrinkwrap: лучи не нашли поверхность цели.",
                            hint="Поменяйте direction, придвиньте объект или увеличьте transition=0.")
    # Толщина измеряется ВДОЛЬ проекционного луча в обе стороны. У боковой
    # грани пластины луч по нормали ушёл бы вдоль листа и дал десятки мм —
    # отсюда ложные «лепестки». Сумма двух проб даёт настоящую толщину и на
    # верхней/нижней стороне, и на ребре, даже где нормали усреднены.
    thickness = np.zeros(len(verts), dtype=np.float64)
    valid_thickness = []
    eps = max(1e-4, step * 1e-3)
    source_reach = float(np.max(source_size)) * 2.0 + step * 4.0
    for i in np.nonzero(weight > 1e-9)[0]:
        ray = hp[i] - verts[i]
        if np.linalg.norm(ray) < 1e-9:
            ray = -normals[i]
        ray = ray / max(float(np.linalg.norm(ray)), 1e-12)
        distances = []
        for sign in (-1.0, 1.0):
            direction = ray * sign
            start = verts[i] + direction * eps
            hit = _ray_on(refined, start, direction, source_reach)
            if hit is not None:
                distance = float(np.linalg.norm(hit[0] - verts[i]))
                if distance > eps * 0.5:
                    distances.append(distance)
        if distances:
            value = float(sum(distances))
            thickness[i] = value
            valid_thickness.append(value)
    fallback = float(np.median(valid_thickness)) if valid_thickness else float(np.min(source_size))
    thickness[thickness <= 1e-9] = max(fallback, 0.02)
    # Редкий касательный луч не должен вытянуть ребро вдоль всей детали.
    if valid_thickness:
        thickness = np.minimum(thickness, max(fallback * 3.0, 0.02))
    facing = np.clip(0.5 + 0.5 * np.einsum("ij,ij->i", normals, hn), 0.0, 1.0)
    facing = facing * facing * (3.0 - 2.0 * facing)
    projected = hp + hn * (gap + facing * thickness)[:, None]
    moved = verts + (projected - verts) * (weight * amount)[:, None]
    result = manifold_from_arrays(moved, faces, "shrinkwrap")
    if result.is_empty() or result.volume() <= 1e-7:
        raise GeometryError("shrinkwrap: проекция схлопнула объём; измените direction/gap.")
    if join != "нет":
        result = result + target.manifold
        if join == "сгладить":
            if len([p for p in result.decompose() if p.volume() > 1e-7]) != 1:
                raise GeometryError("shrinkwrap: при положительном gap объекты не пересекаются, стык сглаживать нечего.",
                                    hint="Для join=сгладить используйте gap≤0 или join=нет.")
            result = _fuse_surface(result, weld, 34.0, "вогнутые")
    out = _derived(a, name, result, source, "shrinkwrap")
    if join != "нет":
        a.scene.consume(target)
    out.meta.update(shrinkwrap_target=target.name, gap=gap, direction=direction_name,
                    transition=transition, detail=step, join=join, projected_vertices=hits_count)
    a.scene.log("info", f"shrinkwrap: {hits_count}/{len(verts)} вершин, gap={gap:g} мм, "
                        f"шаг {step:g} мм, join={join}", a.cmd.line)
    return out


# --------------------------------------------------------------------------- #
#  Чешуя
# --------------------------------------------------------------------------- #
def _scale_tile(w: float, l: float, t: float, kind: str = "рыба",
                tilt: float = 18.0, tile_variant: str = "волна") -> mf.Manifold:
    """Плоская наклонная чешуйка; корень +Y, свободный конец −Y.

    Никакого minkowski/эллипсоида: две плоские параллельные стороны и
    силуэт рыбьего веера или острого драконьего листа. Наклон выполнен shear-
    преобразованием, поэтому проекция длины остаётся точно равной ``l`` — ею
    можно честно управлять перекрытием следующего корня.
    """
    if kind == "черепица":
        if tile_variant == "плоская":
            outline = [(-0.50 * w, 0.50 * l), (0.50 * w, 0.50 * l),
                       (0.50 * w, -0.34 * l), (0.40 * w, -0.50 * l),
                       (-0.40 * w, -0.50 * l), (-0.50 * w, -0.34 * l)]
        elif tile_variant == "ромб":
            outline = [(-0.32 * w, 0.50 * l), (0.32 * w, 0.50 * l),
                       (0.50 * w, 0.08 * l), (0.0, -0.50 * l),
                       (-0.50 * w, 0.08 * l)]
        else:
            # Волна/испанская: прямая прикладная кромка и дуговой свободный
            # край. У испанской плитки середина чуть приподнята — это не
            # копия рыбьего веера и не выпуклая капля.
            outline = [(-0.50 * w, 0.50 * l), (0.50 * w, 0.50 * l),
                       (0.50 * w, -0.10 * l)]
            for i in range(1, 17):
                theta = math.pi * i / 16.0
                x = 0.50 * w * math.cos(theta)
                y = -0.10 * l - 0.40 * l * math.sin(theta)
                if tile_variant == "испанская":
                    y += 0.10 * l * math.sin(2.0 * theta) ** 2
                outline.append((x, y))
            outline.append((-0.50 * w, -0.10 * l))
    elif kind == "дракон":
        outline = [(-0.22 * w, 0.50 * l), (0.22 * w, 0.50 * l),
                   (0.50 * w, 0.10 * l), (0.34 * w, -0.20 * l),
                   (0.0, -0.50 * l), (-0.34 * w, -0.20 * l), (-0.50 * w, 0.10 * l)]
    else:
        outline = [(-0.23 * w, 0.50 * l), (0.23 * w, 0.50 * l),
                   (0.43 * w, 0.10 * l)]
        # Нижний эллиптический веер: широкий округлый конечный сектор.
        for i in range(13):
            theta = -math.pi * i / 12.0
            outline.append((0.50 * w * math.cos(theta),
                            -0.12 * l + 0.38 * l * math.sin(theta)))
        outline.append((-0.43 * w, 0.10 * l))
    cross = mf.CrossSection([_profile(outline)])
    plate = cross.extrude(t).translate((0.0, 0.0, -t / 2.0))
    slope = math.tan(math.radians(tilt))
    embed = t * 0.65
    shear = np.asarray([[1.0, 0.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0, 0.0],
                        [0.0, -slope, 1.0, slope * l / 2.0 - embed]], dtype=np.float64)
    return plate.transform(shear)


@op("scales", aliases=("чешуя", "чешуйки", "рыба_чешуя", "драконья_чешуя"),
    category="Форма и деформации",
    summary="Плоская чешуя и черепица вместо старых выпуклых капель. kind=рыба "
            "даёт округлый веер, дракон — заострённый лист, черепица — кровельные "
            "варианты tile=плоская, волна, ромб или испанская. Каждая пластинка "
            "наклонена от погружённого корня к приподнятому концу; верхний "
            "конечный сектор на overlap перекрывает корень следующей нижней. "
            "Шаг рядов равен length·(1−overlap), поэтому перекрытие реальное.",
    example="рыба = lathe points=[[0,0],[10,0],[26,30],[22,90],[8,120],[0,120]]\n"
            "scales рыба kind=рыба rows=9 per_row=16 length=16 tilt=18 overlap=.45\n"
            "дракон = sphere radius=50\n"
            "scales дракон kind=дракон rows=10 per_row=20 length=14 width=9 tilt=28",
    params={"objects": "объект [a] или a",
            "kind": "рыба, дракон или черепица (рыба)",
            "tile": "вариант черепицы: плоская, волна, ромб или испанская (волна)",
            "tile_style": "синоним tile",
            "variant": "синоним tile",
            "rows": "рядов по высоте (8)",
            "per_row": "чешуек в ряду (14); чётные ряды сдвинуты на полшага",
            "length": "длина от корня до конца, мм (14)",
            "width": "ширина; рыба 0.9 length, дракон 0.65 length",
            "thick": "толщина плоской пластинки, мм (0.08 length)",
            "tilt": "наклон плоскости от корня к концу, ° 0…45 (18; дракон 28)",
            "overlap": "перекрытие корня следующей чешуйки 0.05…0.85 (0.45)",
            "seed": "сдвиг раскладки (0)"},
    positional=["objects"])
def scales(a, name):
    base = _one(a, "scales")
    kind = (a.text("kind", "рыба") or "рыба").strip().lower()
    kind = {"рыба": "рыба", "рыбья": "рыба", "fish": "рыба",
            "дракон": "дракон", "драконья": "дракон", "dragon": "дракон",
            "черепица": "черепица", "черепичная": "черепица", "tile": "черепица",
            "roof": "черепица", "кровля": "черепица"}.get(kind)
    if kind is None:
        raise GeometryError("scales: kind=рыба, дракон или черепица.")
    tile_raw = (a.text("tile", a.text("tile_style", a.text("variant", "волна"))) or "волна").strip().lower()
    tile_variant = {"плоская": "плоская", "плоский": "плоская", "flat": "плоская",
                    "волна": "волна", "волнистая": "волна", "wave": "волна",
                    "ромб": "ромб", "ромбовидная": "ромб", "diamond": "ромб",
                    "испанская": "испанская", "испанский": "испанская", "spanish": "испанская",
                    "голландская": "волна", "dutch": "волна"}.get(tile_raw)
    if tile_variant is None:
        raise GeometryError("scales: tile=плоская, волна, ромб или испанская.")
    rows = int(a.num("rows", 8, minv=1, maxv=60))
    per_row = int(a.num("per_row", 14, minv=3, maxv=120))
    length = float(a.num("length", 14.0, minv=0.3))
    width = float(a.num("width", length * (0.65 if kind == "дракон" else 0.9), minv=0.2))
    thick = float(a.num("thick", length * 0.08, minv=0.03))
    tilt = float(a.num("tilt", 28.0 if kind == "дракон" else (12.0 if kind == "черепица" else 18.0),
                       minv=0.0, maxv=45.0) or 0.0)
    overlap = float(a.num("overlap", 0.45, minv=0.05, maxv=0.85))
    seed = int(a.num("seed", 0) or 0)
    m = base.manifold
    bb = m.bounding_box()
    cx, cy, cz = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0, (bb[2] + bb[5]) / 2.0
    z0, z1 = bb[2], bb[5]
    reach = max(bb[3] - bb[0], bb[4] - bb[1], z1 - z0) * 2.0 + 10.0
    step_z = length * (1.0 - overlap)
    centre_span = (rows - 1) * step_z
    if centre_span > (z1 - z0) + 1e-7:
        raise GeometryError("scales: ряды с такой length/overlap не помещаются по высоте тела.",
                            hint="Уменьшите rows/length или увеличьте overlap; не растягивайте перекрытие.")
    bottom = cz - centre_span / 2.0
    tiles: list[mf.Manifold] = []
    tile = _scale_tile(width, length, thick, kind, tilt, tile_variant)
    for r in range(rows):
        z = bottom + r * step_z
        offset = 0.5 * (r % 2)
        for j in range(per_row):
            ang = 2.0 * math.pi * (j + offset + 0.13 * seed) / per_row
            d = np.array([math.cos(ang), math.sin(ang), 0.0])
            origin = np.array([cx, cy, z])
            end = origin + d * reach
            hits = m.ray_cast([float(v) for v in origin], [float(v) for v in end])
            if not hits:
                continue
            hit = max(hits, key=lambda h: float(np.linalg.norm(np.asarray(h.position) - origin)))
            p = np.asarray(hit.position, dtype=np.float64)
            n = np.asarray(hit.normal, dtype=np.float64)
            if np.linalg.norm(n) < 1e-9:
                n = d
            mat = _frame(n)
            mat[:, 3] = p
            tiles.append(tile.transform(mat.tolist()))
    if not tiles:
        raise GeometryError("Чешуя не нашла поверхность: деталь слишком тонкая или "
                            "луч идёт мимо.", hint="Уменьшите rows и per_row.")
    solid = mf.Manifold.batch_boolean([m] + tiles, mf.OpType.Add)
    out = _derived(a, name, solid, base, "scales")
    out.meta.update(scale_kind=kind, tile_variant=tile_variant if kind == "черепица" else None,
                    tiles=len(tiles), row_step=step_z,
                    overlap=overlap, tilt=tilt, flat=True, root_direction="+Y / верх")
    a.scene.log("info", f"чешуя ({kind}): {len(tiles)} плоских пластинок, "
                        f"перекрытие {overlap * 100:g}%, шаг {step_z:.2f} мм", a.cmd.line)
    return out


# --------------------------------------------------------------------------- #
#  Решётка (клетка, забор, купол-сетка)
# --------------------------------------------------------------------------- #
@op("lattice", aliases=("решётка", "сетка", "клетка", "забор", "grid_shell"),
    category="Форма и деформации",
    summary="Превращает тело в решётку: прутья пересекаются под углом и "
            "обрезаются по оболочке детали. mode=прямоуг — клетка из "
            "вертикальных и горизонтальных прутьев (забор, окно), ромб — "
            "диагональная сетка (купол, корзина), соты — шестиугольный узор. "
            "Результат — одно тело-сетка толщиной depth.",
    example="блок = sphere radius=80\n"
            "купол = shell блок thickness=16\n"
            "lattice купол cell=26 wire=5 mode=ромб\n"
            "окно = box size=[200,12,140]\n"
            "lattice окно cell=30 wire=6 mode=прямоуг",
    params={"objects": "объект [a] или a",
            "cell": "размер ячейки, мм (30)",
            "wire": "толщина прута, мм (5)",
            "depth": "глубина решётки от поверхности, мм (авто wire×2)",
            "mode": "прямоуг, ромб или соты — «прямоуг»",
            "angle": "наклон второй семьи прутьев, градусы (авто 90 или 45)",
            "seed": "сдвиг узора (0)"},
    positional=["objects"])
def lattice(a, name):
    base = _one(a, "lattice")
    cell = float(a.num("cell", 30.0, minv=2.0))
    wire = float(a.num("wire", 5.0, minv=0.3))
    mode = (a.text("mode") or "прямоуг").strip().lower()
    mode = {"прямоуг": "прямоуг", "клетка": "прямоуг", "grid": "прямоуг",
            "ромб": "ромб", "диагональ": "ромб", "diamond": "ромб",
            "соты": "соты", "honeycomb": "соты", "hex": "соты"}.get(mode)
    if mode is None:
        raise GeometryError(f"Неизвестный узор решётки «{a.text('mode')}».",
                            hint="mode: прямоуг, ромб или соты.")
    if wire >= cell * 0.8:
        raise GeometryError(f"Прут {wire:g} мм почти равен ячейке {cell:g} мм — "
                            f"решётка станет сплошной.", hint="wire ≈ 0.1…0.25 от cell.")
    depth = float(a.num("depth", 0.0, minv=0.0) or 0.0)
    seed = int(a.num("seed", 0) or 0)
    m = base.manifold
    bb = m.bounding_box()
    size = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
    pad = max(size) * 0.15 + cell
    span = [sz + 2 * pad for sz in size]
    cx, cy, cz = ((bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0, (bb[2] + bb[5]) / 2.0)
    shift = (seed % 7) * 0.13 * cell

    bars: list[mf.Manifold] = []

    def add_grid(angles: list[float], spacing: float) -> None:
        """Семейства параллельных прутьев под заданными углами вокруг Z."""
        reach = (span[0] + span[1]) * 1.2
        for ang in angles:
            # прутья строятся вдоль X, потом поворачиваются на угол
            n = max(1, int(round(reach / spacing)))
            for i in range(n + 1):
                z_off = -reach / 2.0 + reach * i / n
                bar = mf.Manifold.cube([reach, wire, span[2]], True)
                bar = mf.Manifold.rotate(bar, [0.0, 0.0, float(ang)])
                # сдвиг по нормали к пруту (перпендикуляр в плоскости XY)
                nx, ny = -math.sin(math.radians(ang)), math.cos(math.radians(ang))
                bars.append(bar.translate((cx + nx * z_off + shift,
                                           cy + ny * z_off, cz)))

    if mode == "прямоуг":
        add_grid([0.0, 90.0], cell)
        # прутья по высоте — чтобы получилась объёмная клетка
        n_z = max(1, int(round(span[2] / (cell * 1.5))))
        for i in range(n_z + 1):
            z = bb[2] - pad + span[2] * i / n_z
            bars.append(mf.Manifold.cube([span[0], span[1], wire], True)
                        .translate((cx, cy, z)))
    elif mode == "ромб":
        add_grid([45.0, -45.0], cell * 1.15)
        n_z = max(1, int(round(span[2] / (cell * 2.0))))
        for i in range(n_z + 1):
            z = bb[2] - pad + span[2] * i / n_z
            bars.append(mf.Manifold.cube([span[0], span[1], wire * 0.9], True)
                        .translate((cx, cy, z)))
    else:                       # соты
        add_grid([0.0, 60.0, 120.0], cell * 1.3)

    side = mf.Manifold.batch_boolean(bars, mf.OpType.Add)
    region = m
    if depth > 1e-6:
        if depth * 2 >= min(size):
            raise GeometryError(f"Глубина решётки {depth:g} мм больше половины "
                                f"детали ({min(size):.1f} мм).",
                                hint="depth ≈ 0.1…0.3 от толщины детали.")
        ball = mf.Manifold.sphere(depth, 20)
        inner = m.minkowski_difference(ball)
        if inner.is_empty():
            raise GeometryError("Не удалось снять внутренний слой: уменьшите depth.")
        region = m - inner
    solid = side ^ region
    solid = ensure_volume(solid, "решётки")
    parts = len([p for p in solid.decompose() if p.volume() > 0])
    a.scene.log("info", f"решётка: {mode}, ячейка {cell:g}, прут {wire:g}, "
                        f"частей {parts}", a.cmd.line)
    if parts > 30:
        a.scene.log("warn", "решётка рассыпалась на куски — увеличьте wire или "
                            "уменьшите cell", a.cmd.line)
    return _derived(a, name, solid, base, "lattice")


# --------------------------------------------------------------------------- #
#  Кора
# --------------------------------------------------------------------------- #
@op("bark", aliases=("кора", "дерево_кора", "ствол", "trunk", "tree_bark"),
    category="Примитивы",
    summary="Ствол с настоящей корой: продольные борозды переменной глубины, "
            "мелкие трещины и сбег к вершине. Не текстура, а геометрия — "
            "борозды видны в профиль и печатаются. Одно тело, стоит на полу.",
    example="дуб = bark height=600 radius=90 grooves=14 depth=9 seed=2\n"
            "тонкий = bark height=300 radius=30 grooves=9 depth=4 taper=0.35",
    params={"height": "высота, мм (500)",
            "radius": "радиус у комля, мм (70)",
            "taper": "сужение кверху 0…0.8 (0.28)",
            "grooves": "число продольных борозд (12)",
            "depth": "глубина борозд, мм (0.12 радиуса)",
            "seed": "сдвиг узора (0)",
            "segments": "точек по кругу (по размеру)"},
    positional=["height", "radius"])
def bark(a, name):
    height = float(a.num("height", 500.0, minv=5.0))
    radius = float(a.num("radius", 70.0, minv=1.0))
    taper = float(a.num("taper", 0.28, minv=0.0, maxv=0.8))
    grooves = int(a.num("grooves", 12, minv=3, maxv=64))
    depth = float(a.num("depth", radius * 0.12, minv=0.0))
    seed = int(a.num("seed", 0) or 0)
    if depth >= radius * 0.45:
        raise GeometryError(f"Борозда {depth:g} мм глубже трети радиуса {radius:g} мм.",
                            hint="depth ≈ 0.08…0.2 от radius.")
    n_phi = int(a.num("segments", 0) or 0) or max(96, grooves * 14)
    n_phi = int(max(48, min(512, n_phi)))
    n_z = int(max(24, min(240, height / 7.0)))
    phis = np.linspace(0.0, 2.0 * math.pi, n_phi, endpoint=False)
    zs = np.linspace(0.0, height, n_z + 1)

    rng = np.random.default_rng(seed)
    spacing = 2.0 * math.pi / grooves
    main = (np.arange(grooves) + rng.uniform(-0.30, 0.30, grooves)) * spacing
    # Между главными трещинами проходят более короткие и тонкие вторичные.
    angles = np.concatenate([main, main + spacing * rng.uniform(0.22, 0.46, grooves)])
    widths = np.concatenate([spacing * rng.uniform(0.035, 0.075, grooves),
                             spacing * rng.uniform(0.018, 0.045, grooves)])
    strengths = np.concatenate([rng.uniform(0.68, 1.18, grooves),
                                rng.uniform(0.22, 0.55, grooves)])
    phases = rng.uniform(0.0, 2.0 * math.pi, (len(angles), 3))
    frequencies = rng.uniform(1.2, 3.8, (len(angles), 2))

    def radius_at(phi: np.ndarray, z: float) -> np.ndarray:
        """Нерегулярные продольные трещины и чешуйки, бесшовные по окружности."""
        phi = np.asarray(phi, dtype=np.float64).reshape(-1)
        t = z / height
        base = radius * (1.0 - taper * t)
        centres = (angles + spacing * 0.12 * (
            np.sin(2.0 * math.pi * frequencies[:, 0] * t + phases[:, 0])
            + 0.42 * np.sin(2.0 * math.pi * frequencies[:, 1] * t + phases[:, 1])))
        delta = (phi[None, :] - centres[:, None] + math.pi) % (2.0 * math.pi) - math.pi
        local_w = widths * (0.82 + 0.18 * np.sin(2.0 * math.pi * t + phases[:, 2]))
        # Глубина меняется по высоте, но трещина не исчезает целиком: кора
        # остаётся связной, без отдельных пятен и висячих чешуек.
        local_d = strengths * (0.74 + 0.26 * np.sin(
            2.0 * math.pi * frequencies[:, 1] * t + phases[:, 2]))
        groove = np.exp(-np.power(np.abs(delta) / np.maximum(local_w[:, None], 1e-6), 1.35))
        cut = np.sum(groove * local_d[:, None], axis=0)
        cut = np.clip(cut, 0.0, 1.35)
        # Периодические координаты cos/sin исключают вертикальный шов на
        # стыке 0/2π; разные масштабы дают пластины и мелкую шелуху.
        coarse = _fbm(np.stack([np.cos(phi) * grooves / 3.0,
                                np.sin(phi) * grooves / 3.0,
                                np.full_like(phi, z / 22.0)], axis=1), 3, seed + 5)
        fine = _fbm(np.stack([np.cos(phi) * grooves,
                              np.sin(phi) * grooves,
                              np.full_like(phi, z / 4.5)], axis=1), 2, seed + 19)
        return np.clip(base - depth * cut + depth * (0.20 * coarse + 0.07 * fine),
                       radius * 0.05, None)

    rings = []
    for z in zs:
        r = radius_at(phis, float(z))
        rings.append(np.stack([r * np.cos(phis), r * np.sin(phis), np.full(n_phi, z)], axis=1))
    verts = np.vstack(rings)
    faces = []
    for i in range(n_z):
        a0, b0 = i * n_phi, (i + 1) * n_phi
        for j in range(n_phi):
            j2 = (j + 1) % n_phi
            faces.append((a0 + j, a0 + j2, b0 + j2))
            faces.append((a0 + j, b0 + j2, b0 + j))
    # дно и вершина — веером к центру
    bottom = len(verts)
    verts = np.vstack([verts, np.array([[0.0, 0.0, 0.0]])])
    top = len(verts)
    verts = np.vstack([verts, np.array([[0.0, 0.0, height]])])
    for j in range(n_phi):
        j2 = (j + 1) % n_phi
        faces.append((bottom, j2, j))
        base_top = n_z * n_phi
        faces.append((top, base_top + j, base_top + j2))
    solid = manifold_from_arrays(verts, np.asarray(faces, dtype=np.int64), "коры")
    solid = ensure_volume(solid, "коры")
    return make_solid(a.scene, name, solid, a, kind="bark")


# --------------------------------------------------------------------------- #
#  Кирпичная кладка
# --------------------------------------------------------------------------- #
@op("bricks", aliases=("кладка", "кирпич", "кирпичная_кладка", "masonry", "wall"),
    category="Примитивы",
    summary="Кирпичная кладка одной деталью: ряды со сдвигом вполкирпича, швы "
            "вдавлены, углы кирпичей скруглены, размеры чуть разные. Плоскость "
            "стены — XZ, толщина по Y, стоит на полу. Швы видны в профиль и "
            "остаются после печати.",
    example="стена = bricks width=400 height=300 thick=40 brick=[90,42] joint=7\n"
            "камин = bricks width=260 height=180 brick=[60,28] joint=5 seed=4",
    params={"width": "ширина стены, мм (400)",
            "height": "высота стены, мм (300)",
            "thick": "толщина стены, мм (40)",
            "brick": "размер кирпича [длина, высота], мм ([90,42])",
            "joint": "ширина шва, мм (6)",
            "depth": "глубина шва, мм (0.5 толщины)",
            "seed": "разброс размеров и оттенка, целое (0)",
            "round": "скругление кромок кирпича, мм (1.5)"},
    positional=["width", "height"])
def bricks(a, name):
    width = float(a.num("width", 400.0, minv=10.0))
    height = float(a.num("height", 300.0, minv=10.0))
    thick = float(a.num("thick", 40.0, minv=2.0))
    brick_raw = a.value("brick")
    if isinstance(brick_raw, (list, tuple)) and len(brick_raw) == 2:
        bw, bh = float(brick_raw[0]), float(brick_raw[1])
    else:
        bw, bh = 90.0, 42.0
    joint = float(a.num("joint", 6.0, minv=0.2))
    depth = float(a.num("depth", thick * 0.5, minv=0.1))
    seed = int(a.num("seed", 0) or 0)
    round_r = float(a.num("round", 1.5, minv=0.0))
    if bw <= joint * 2 or bh <= joint * 2:
        raise GeometryError("Кирпич слишком мал для такого шва.",
                            hint="brick ≥ 3 × joint.")
    if depth >= thick * 0.95:
        raise GeometryError("Шов глубже толщины стены — стена распадётся.",
                            hint="depth ≤ 0.7 × thick.")
    rng = np.random.default_rng(seed)
    rows = max(1, int(round(height / (bh + joint))))
    step_z = height / rows
    cols = max(1, int(round(width / (bw + joint))))
    step_x = width / cols
    parts: list[mf.Manifold] = []
    for r in range(rows):
        z0 = r * step_z
        offset = (step_x / 2.0) if (r % 2) else 0.0
        x = -width / 2.0 - offset
        while x < width / 2.0:
            w = step_x - joint
            h = step_z - joint
            if w > 1e-3 and h > 1e-3:
                jitter = 0.02 * seed * (rng.random() - 0.5)
                d = thick * (0.96 + jitter)
                cross = _cross([(-w / 2, -h / 2), (w / 2, -h / 2),
                                (w / 2, h / 2), (-w / 2, h / 2)])
                rr = min(round_r, w * 0.2, h * 0.2)
                if rr > 1e-3:
                    cross = cross.offset(-rr, mf.JoinType.Round, 2.0, 6)
                # кирпич удобно строить в плоскости XY, а стена стоит в XZ:
                # поворот на 90° вокруг X (собственное вращение, не отражение),
                # затем сдвиг так, чтобы лицо кирпича было на y = 0
                block = mf.Manifold.rotate(cross.extrude(d), [90.0, 0.0, 0.0])
                block = block.translate((0.0, d, 0.0))
                parts.append(block.translate((x + step_x / 2.0, 0.0,
                                              z0 + step_z / 2.0)))
            x += step_x
    # задняя плита: связывает кирпичи в одно тело
    # задняя плита: заполняет всё за швами, связывает кирпичи в одно тело
    back_thick = max(thick - depth, 0.5)
    back = mf.Manifold.cube([width, back_thick, height], True).translate(
        (0.0, depth + back_thick / 2.0, height / 2.0))
    solid = mf.Manifold.batch_boolean(parts + [back], mf.OpType.Add)
    # обрезаем по заданным габаритам: крайние кирпичи со сдвигом торчат вбок
    clip = mf.Manifold.cube([width, thick + 2.0, height], True).translate(
        (0.0, thick / 2.0 - 1.0, height / 2.0))
    solid = solid ^ clip
    solid = ensure_volume(solid, "кладки")
    a.scene.log("info", f"кладка: {rows} рядов × {cols} кирпичей, шов {joint:g} мм, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="bricks")


# --------------------------------------------------------------------------- #
#  Починка сканов
# --------------------------------------------------------------------------- #
@op("repair", aliases=("починить", "заделать", "закрыть_дыры", "fix_mesh", "heal"),
    category="Форма и деформации",
    summary="Доводит скан до рабочего тела: заделывает дыры по краю разрывов, "
            "выбрасывает мелкий мусор, сглаживает лесенки и упрощает сетку. "
            "После этого скан можно резать, печатать и проверять ядром — "
            "manifold требует замкнутый объём.",
    example='кружка = cylinder radius=40 height=90\nrepair кружка smooth=1',
    params={"objects": "объект [a] или a",
            "smooth": "проходов сглаживания 0…5 (1)",
            "simplify": "доля треугольников после упрощения 0…1 (0.5); 1 — не упрощать",
            "drop": "выбросить куски меньше, % объёма (0.05)",
            "deviation": "допустимое отклонение при упрощении, мм (0.2)"},
    positional=["objects"])
def repair(a, name):
    base = _one(a, "repair")
    smooth_steps = int(a.num("smooth", 1, minv=0, maxv=5))
    keep = float(a.num("simplify", 0.5, minv=0.05, maxv=1.0))
    drop = float(a.num("drop", 0.05, minv=0.0, maxv=10.0))
    deviation = float(a.num("deviation", 0.2, minv=0.01))
    m = base.manifold
    verts, faces = manifold_mesh(m)
    verts = np.asarray(verts, dtype=np.float64)
    faces = np.asarray(faces, dtype=np.int64)

    # --- 1. Находим граничные рёбра и зашиваем петли веером от центра
    edges: dict[tuple[int, int], int] = {}
    for tri in faces:
        for k in range(3):
            a0, a1 = int(tri[k]), int(tri[(k + 1) % 3])
            key = (a0, a1) if a0 < a1 else (a1, a0)
            edges[key] = edges.get(key, 0) + 1
    border = [e for e, cnt in edges.items() if cnt == 1]
    added = 0
    if border:
        # собираем петли
        nxt: dict[int, list[int]] = {}
        for a0, a1 in border:
            nxt.setdefault(a0, []).append(a1)
            nxt.setdefault(a1, []).append(a0)
        seen: set[tuple[int, int]] = set()
        new_faces: list[tuple[int, int, int]] = []
        for start in list(nxt):
            for first in nxt[start]:
                key = (start, first) if start < first else (first, start)
                if key in seen:
                    continue
                loop = [start]
                prev, cur = start, first
                seen.add(key)
                while cur != start and len(loop) < 100_000:
                    loop.append(cur)
                    cand = [v for v in nxt.get(cur, []) if v != prev]
                    if not cand:
                        break
                    nv = cand[0]
                    seen.add((cur, nv) if cur < nv else (nv, cur))
                    prev, cur = cur, nv
                if len(loop) < 3:
                    continue
                # веер: центр петли → треугольники
                pts = verts[loop]
                center = pts.mean(axis=0)
                ci = len(verts)
                verts = np.vstack([verts, center[None, :]])
                for i in range(len(loop)):
                    new_faces.append((ci, loop[i], loop[(i + 1) % len(loop)]))
                added += 1
        if new_faces:
            faces = np.vstack([faces, np.asarray(new_faces, dtype=np.int64)])

    # --- 2. Собираем обратно (дыры зашиты)
    try:
        solid = manifold_from_arrays(verts, faces, "скана")
    except GeometryError:
        raise
    # --- 3. Сглаживание лесенок
    for _ in range(smooth_steps):
        solid = solid.smooth_out(50.0, 0.18)
    # --- 4. Убираем мелкий мусор и упрощаем
    pieces = [p for p in solid.decompose() if p.volume() > 0]
    if len(pieces) > 1:
        main_volume = max(p.volume() for p in pieces)
        keep_parts = [p for p in pieces if p.volume() >= main_volume * drop / 100.0]
        solid = mf.Manifold.batch_boolean(keep_parts, mf.OpType.Add)
    if keep < 0.999:
        target = max(64, int(solid.num_tri() * keep))
        solid = solid.as_original().simplify(deviation) if hasattr(solid, "as_original") else solid
    solid = ensure_volume(solid, "починенного скана")
    a.scene.log("info", f"починка: зашито петель {added}, глажек {smooth_steps}, "
                        f"итог {solid.num_tri():,} трис, частей "
                        f"{len(solid.decompose())}".replace(",", " "), a.cmd.line)
    return _derived(a, name, solid, base, "repair")
