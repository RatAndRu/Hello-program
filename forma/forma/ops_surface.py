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
from pathlib import Path

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import manifold_from_arrays, manifold_mesh
from .ops_shape import shell_manifold
from .ops import make_solid, op
from .ops_extra import _derived, _one
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


def _refine_for(m: mf.Manifold, refine: float, cap: int = 140_000) -> float:
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
    moved = verts + normals * offs[:, None]
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
    summary="Волна по поверхности готового тела: складки ткани, гофра, плиссе, "
            "рябь, кора, мятая поверхность. Смещает вершины по нормали на "
            "функцию от координат. mode=радиус — волны вокруг оси Z (плиссе), "
            "высота — кольца по высоте, шум — нерегулярная мятость, клетка — "
            "стёганый узор, трещины — глубокие борозды. Тело остаётся "
            "замкнутым, размер меняется на доли amp.",
    example="ваза = cylinder radius=40 height=90\n"
            "wrinkle ваза amp=2 freq=14 mode=радиус\n"
            "сосуд = cylinder radius=40 height=90\n"
            "wrinkle сосуд amp=3 freq=20 mode=высота seed=3",
    params={"objects": "объект [a] или a",
            "amp": "амплитуда, мм (2): на сколько выступают складки",
            "freq": "частота: сколько волн по кругу или по высоте (12)",
            "mode": "радиус (вокруг оси), высота (кольца), шум (мятость), "
                    "клетка (стёганая), трещины (борозды) — «радиус»",
            "seed": "сдвиг узора, целое (0)",
            "detail": "длина ребра перед деформацией, мм (авто amp/2.5)",
            "twist": "закрутка волн по высоте, градусы на всю высоту (0)"},
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
    if amp <= 1e-6:
        return _derived(a, name, base.manifold, base, "wrinkle")
    seed = int(a.num("seed", 0) or 0)
    twist = math.radians(float(a.num("twist", 0.0) or 0.0))
    m = base.manifold
    bb = m.bounding_box()
    cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
    height = max(bb[5] - bb[2], 1e-6)
    # шаг сетки — от длины волны узора, а не от амплитуды: иначе на крупном
    # теле получается сотня тысяч лишних треугольников
    span = max(bb[3] - bb[0], bb[4] - bb[1], height)
    if mode == "радиус":
        wavelength = 2.0 * math.pi * (span / 2.0) / max(freq, 0.5)
    elif mode == "высота":
        wavelength = height / max(freq, 0.5)
    elif mode == "клетка":
        wavelength = span / max(freq, 0.5)
    else:                       # шум и трещины
        wavelength = span / max(freq, 0.5) * 0.7
    auto_refine = max(0.1, min(amp / 2.0, wavelength / 5.0))
    detail = a.num("detail", None, minv=0.02)
    refine = float(detail) if detail else auto_refine

    def offsets(verts: np.ndarray, normals: np.ndarray) -> np.ndarray:
        x, y, z = verts[:, 0] - cx, verts[:, 1] - cy, verts[:, 2] - bb[2]
        phi = np.arctan2(y, x)
        if mode == "радиус":
            ang = phi + twist * (z / height)
            return amp * np.cos(freq * ang)
        if mode == "высота":
            return amp * np.cos(2.0 * math.pi * freq * z / height)
        if mode == "шум":
            return amp * _fbm(verts * (freq / 40.0), 3, seed)
        if mode == "клетка":
            k = 2.0 * math.pi * freq / max(bb[3] - bb[0], bb[4] - bb[1], 1e-6)
            return amp * 0.5 * (np.cos(k * x) * np.cos(k * y) + np.cos(k * z * 1.0))
        # трещины: узкие борозды с рваным краем
        wobble = 0.35 * _fbm(np.stack([phi * 6.0, z / 12.0, phi * 2.0], axis=1), 2, seed)
        ridge = np.abs(np.cos(math.pi * freq * (phi / (2.0 * math.pi)) + wobble))
        return -amp * (1.0 - np.power(np.clip(ridge, 0.0, 1.0), 0.35))

    solid = _deform(m, offsets, "складки", refine=refine)
    a.scene.log("info", f"складки: {mode}, амплитуда {amp:g} мм, "
                        f"частота {freq:g}, {solid.num_tri():,} трис".replace(",", " "),
                a.cmd.line)
    return _derived(a, name, solid, base, "wrinkle")


# --------------------------------------------------------------------------- #
#  Карта высот: узор картинкой
# --------------------------------------------------------------------------- #
def _load_heightmap(path: str) -> np.ndarray:
    """Картинка → массив 0…1 (яркость), строки снизу вверх."""
    p = Path(path)
    if not p.exists():
        raise GeometryError(f"Не найден файл карты высот: {path}.",
                            hint="Положите картинку рядом с проектом и укажите путь.")
    try:
        from PIL import Image
    except ImportError as exc:      # pragma: no cover - Pillow всегда в зависимостях
        raise GeometryError("Для карт высот нужен Pillow.") from exc
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
            "её на грань в плоскости XY. Для тонкого узора тело дробится до "
            "шага depth/2 — без этого рельеф «поплывёт».",
    example='ваза = cylinder radius=40 height=90\n'
            'relief ваза image=docs/pattern.png depth=2 mode=обёртка\n'
            'плита = box size=[120,80,10]\n'
            'relief плита image=docs/pattern.png depth=1 mode=плоскость',
    params={"objects": "объект [a] или a",
            "image": "путь к картинке (обязательно)",
            "depth": "глубина рельефа, мм (2)",
            "mode": "обёртка (вокруг оси Z) или плоскость (по XY) — «обёртка»",
            "invert": "поменять местами выступы и впадины (нет)",
            "offset": "сдвиг узора по кругу, 0…1 (0)",
            "repeat": "сколько раз повторить узор по кругу (1)",
            "detail": "длина ребра перед деформацией, мм (авто depth/2)"},
    positional=["objects"])
def relief(a, name):
    base = _one(a, "relief")
    image = (a.text("image") or "").strip()
    if not image:
        raise GeometryError("Укажите картинку: relief [ваза] image=pattern.png depth=2")
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
@op("porous", aliases=("поры", "пористый", "губка", "пемза", "сыр", "sponge"),
    category="Форма и деформации",
    summary="Дырявит тело как пемзу, губку, воздушный шоколад или сыр. "
            "mode=поры — мелкие выбоины у поверхности; ячеи — крупные "
            "сообщающиеся каверны (губка); пузыри — полости внутри, снаружи "
            "поверхность гладкая (шоколад); глазки — редкие крупные круглые "
            "дырки (эмменталь). Всегда одно тело, дырки не касаются краёв "
            "без нужды.",
    example="камень = rock size=90 rough=0.4 seed=2\n"
            "porous камень mode=поры size=4 count=90\n"
            "губка = box size=[90,60,30]\n"
            "porous губка mode=ячеи size=12 count=35",
    params={"objects": "объект [a] или a",
            "mode": "поры, ячеи, пузыри или глазки — «поры»",
            "size": "радиус дырки, мм (4)",
            "count": "сколько дырок (60)",
            "seed": "число для повторяемого узора (0)",
            "spread": "разброс размеров 0…1: 0 — все одинаковые (0.45)",
            "detail": "качество сфер 6…24 (12)"},
    positional=["objects"])
def porous(a, name):
    base = _one(a, "porous")
    mode = (a.text("mode") or "поры").strip().lower()
    mode = {"поры": "поры", "пемза": "поры", "pores": "поры",
            "ячеи": "ячеи", "губка": "ячеи", "cells": "ячеи",
            "пузыри": "пузыри", "шоколад": "пузыри", "bubbles": "пузыри",
            "глазки": "пузыри", "сыр": "пузыри", "eyes": "пузыри"}.get(mode)
    if mode is None:
        raise GeometryError(f"Неизвестный режим пор «{a.text('mode')}».",
                            hint="mode: поры, ячеи, пузыри или глазки.")
    size = float(a.num("size", 4.0, minv=0.2))
    count = int(a.num("count", 60, minv=1, maxv=600))
    seed = int(a.num("seed", 0) or 0)
    spread = float(a.num("spread", 0.45, minv=0.0, maxv=0.9))
    seg = int(a.num("detail", 12, minv=6, maxv=24))
    rng = np.random.default_rng(seed)
    m = base.manifold
    bb = m.bounding_box()
    verts, faces = manifold_mesh(m)
    holes: list[mf.Manifold] = []
    radii = size * (1.0 - spread + 2.0 * spread * rng.random(count))

    if mode in ("поры", "ячеи"):
        want = count * (3 if mode == "поры" else 1)
        pts, nor = _surface_samples(verts, faces, max(want, count * 2), rng)
        used = 0
        for i in range(count):
            r = float(radii[i])
            # центр чуть снаружи: сфера выкусывает лунку глубиной ~0.45 r
            lift = r * (0.55 if mode == "поры" else 0.15)
            c = pts[i * (max(want, count * 2) // count)] + nor[i * (max(want, count * 2) // count)] * lift
            holes.append(mf.Manifold.sphere(r, seg).translate(tuple(float(v) for v in c)))
            used += 1
        a.scene.log("info", f"поры: {used} лунок по {size:g} мм", a.cmd.line)
    else:
        # пузыри и глазки — внутри тела, чтобы снаружи не осталось вмятин
        lo = np.array([bb[0], bb[1], bb[2]])
        hi = np.array([bb[3], bb[4], bb[5]])
        tries = 0
        while len(holes) < count and tries < count * 40:
            tries += 1
            p = lo + (hi - lo) * rng.random(3)
            r = float(radii[len(holes)])
            # расстояние до поверхности: ближайшее попадание луча в 6 сторон
            near = np.inf
            for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                end = p + np.asarray(d, dtype=np.float64) * (max(hi - lo) * 2 + 10)
                hits = m.ray_cast([float(v) for v in p], [float(v) for v in end])
                if hits:
                    near = min(near, float(np.linalg.norm(np.asarray(hits[0].position) - p)))
            if np.isfinite(near) and near > r * 1.15:
                holes.append(mf.Manifold.sphere(r, seg).translate(
                    tuple(float(v) for v in p)))
        if not holes:
            raise GeometryError("Не удалось разместить пузыри: деталь слишком тонкая.",
                                hint="Уменьшите size или возьмите mode=поры.")
        a.scene.log("info", f"пузыри: {len(holes)} полостей по {size:g} мм", a.cmd.line)

    solid = mf.Manifold.batch_boolean([m] + holes, mf.OpType.Subtract)
    solid = ensure_volume(solid, "пористой детали")
    if len(solid.decompose()) > 40:
        a.scene.log("warn", f"пористость развалила тело на {len(solid.decompose())} частей — "
                            f"уменьшите size или count", a.cmd.line)
    return _derived(a, name, solid, base, "porous")


# --------------------------------------------------------------------------- #
#  Чешуя
# --------------------------------------------------------------------------- #
def _scale_tile(w: float, l: float, t: float) -> mf.Manifold:
    """Одна чешуйка: выпуклая пластинка-капля, около 40 треугольников."""
    n = 9
    phi = np.linspace(-math.pi * 0.92, math.pi * 0.92, n)
    ring = np.stack([0.5 * w * np.sin(phi), 0.5 * l * (np.cos(phi) * 0.5 + 0.5)], axis=1)
    ring[:, 1] = ring[:, 1] - 0.5 * l * 0.5      # хвост чешуйки вниз
    cross = _cross([tuple(p) for p in ring])
    h = max(t, 0.05)
    core = cross.scale((0.94, 0.94)).extrude(h * 0.6)
    return core.minkowski_sum(mf.Manifold.sphere(h * 0.5, 2)).translate((0, 0, h * 0.35))


@op("scales", aliases=("чешуя", "чешуйки", "рыба_чешуя", "scales_tile"),
    category="Форма и деформации",
    summary="Покрывает тело чешуёй: лучи изнутри находят поверхность, на ней "
            "раскладываются черепицей выпуклые пластинки. Рыба, дракон, "
            "шишка, кольчуга. Ряды перекрываются на overlap, каждая чешуйка "
            "приподнята на lift — получается настоящая черепица, а не рисунок.",
    example="рыба = lathe points=[[0,0],[10,0],[26,30],[22,90],[8,120],[0,120]]\n"
            "scales рыба rows=9 per_row=16 length=16 lift=0.6\n"
            "шар = sphere radius=50\n"
            "scales шар rows=14 per_row=22 length=12 overlap=0.55",
    params={"objects": "объект [a] или a",
            "rows": "рядов по высоте (8)",
            "per_row": "чешуек в ряду (14); в нечётных рядах сдвиг на полшага",
            "length": "длина чешуйки, мм (14)",
            "width": "ширина; по умолчанию 0.8 длины",
            "thick": "толщина чешуйки, мм (0.22 длины)",
            "lift": "насколько приподнята над кожей, мм (0.5)",
            "overlap": "перекрытие рядов 0…0.8 (0.45)",
            "seed": "сдвиг раскладки (0)"},
    positional=["objects"])
def scales(a, name):
    base = _one(a, "scales")
    rows = int(a.num("rows", 8, minv=1, maxv=60))
    per_row = int(a.num("per_row", 14, minv=3, maxv=120))
    length = float(a.num("length", 14.0, minv=0.3))
    width = float(a.num("width", length * 0.8, minv=0.2))
    thick = float(a.num("thick", length * 0.22, minv=0.05))
    lift = float(a.num("lift", length * 0.04, minv=0.0))
    overlap = float(a.num("overlap", 0.45, minv=0.0, maxv=0.8))
    seed = int(a.num("seed", 0) or 0)
    m = base.manifold
    bb = m.bounding_box()
    cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
    z0, z1 = bb[2], bb[5]
    reach = max(bb[3] - bb[0], bb[4] - bb[1], z1 - z0) * 2.0 + 10.0
    step_z = (z1 - z0) / max(rows, 1) * (1.0 - overlap * 0.6)
    tiles: list[mf.Manifold] = []
    tile = _scale_tile(width, length, thick)
    for r in range(rows):
        z = z0 + (z1 - z0) * (r + 0.5) / rows
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
            # низ чешуйки уходит внутрь кожи: иначе часть пластинок
            # останется висеть отдельными телами
            mat[:, 3] = p + n * (lift - thick * 0.55)
            tiles.append(tile.transform(mat.tolist()))
    if not tiles:
        raise GeometryError("Чешуя не нашла поверхность: деталь слишком тонкая или "
                            "луч идёт мимо.", hint="Уменьшите rows и per_row.")
    solid = mf.Manifold.batch_boolean([m] + tiles, mf.OpType.Add)
    a.scene.log("info", f"чешуя: {len(tiles)} пластинок, шаг по высоте {step_z:.1f} мм",
                a.cmd.line)
    return _derived(a, name, solid, base, "scales")


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
    n_phi = int(a.num("segments", 0) or 0) or max(72, grooves * 8)
    n_phi = int(max(24, min(256, n_phi)))
    n_z = max(12, int(height / 12.0))
    phis = np.linspace(0.0, 2.0 * math.pi, n_phi, endpoint=False)
    zs = np.linspace(0.0, height, n_z + 1)

    def radius_at(phi: np.ndarray, z: float) -> np.ndarray:
        """Радиус ствола по кругу на высоте z: сбег + борозды + шум коры."""
        phi = np.asarray(phi, dtype=np.float64).reshape(-1)
        base = radius * (1.0 - taper * (z / height))
        # борозды: узкие впадины, слегка вихляющие по высоте
        wobble = 0.22 * _fbm(np.stack([phi * 2.5, np.full_like(phi, z / 40.0),
                                       np.zeros_like(phi)], axis=1), 2, seed)
        groove = np.abs(np.cos(0.5 * grooves * phi + wobble))
        base = base - depth * (1.0 - np.power(np.clip(groove, 0.0, 1.0), 0.4))
        # мелкая кора: шум по всей поверхности
        noise = _fbm(np.stack([phi * 3.0, np.full_like(phi, z / 9.0),
                               phi * z / 500.0], axis=1), 3, seed + 5)
        return np.clip(base + depth * 0.22 * noise, radius * 0.05, None)

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
