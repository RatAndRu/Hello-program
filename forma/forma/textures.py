"""Процедурные текстуры: дерево, мрамор, металл, ткань, кожа, клетка, шум.

Генерируются математически (без внешних картинок), чтобы у модели сразу
появлялся материал, который видно и в окне приложения, и в Blender.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .errors import DslError
from .paths import user_data_dir

KINDS = {
    "дерево": "wood", "wood": "wood", "дуб": "wood", "орех": "wood",
    "мрамор": "marble", "marble": "marble", "камень": "marble",
    "металл": "metal", "metal": "metal", "сталь": "metal", "браш": "metal",
    "ткань": "fabric", "fabric": "fabric", "лён": "fabric",
    "кожа": "leather", "leather": "leather",
    "клетка": "checker", "шахматка": "checker", "checker": "checker",
    "шум": "noise", "noise": "noise", "гранит": "noise",
    "кирпич": "brick", "brick": "brick",
    "керамика": "ceramic", "ceramic": "ceramic", "глазурь": "ceramic",
}
PATTERNS = {
    "полосы": "stripes", "stripes": "stripes", "полоски": "stripes",
    "клетка": "checker", "шахматка": "checker", "checker": "checker",
    "волны": "waves", "waves": "waves", "зебра": "waves",
    "градиент": "gradient", "gradient": "gradient",
    "шум": "noise", "noise": "noise", "облака": "noise",
    "камень": "stone", "stone": "stone", "гранит": "stone",
    "точки": "dots", "dots": "dots", "горошек": "dots",
    "сетка": "grid", "grid": "grid", "клеточки": "grid",
}
PATTERN_NAMES = {
    "stripes": "полосы", "checker": "клетка", "waves": "волны",
    "gradient": "градиент", "noise": "шум", "stone": "камень",
    "dots": "точки", "grid": "сетка",
}
NAMED_COLORS = {
    "белый": (245, 245, 242), "чёрный": (24, 24, 26), "черный": (24, 24, 26),
    "серый": (128, 130, 134), "красный": (196, 62, 54), "синий": (48, 86, 168),
    "зелёный": (58, 128, 78), "желтый": (226, 190, 66), "жёлтый": (226, 190, 66),
    "коричневый": (104, 62, 34), "бежевый": (222, 206, 178),
    "бирюзовый": (52, 160, 158), "фиолетовый": (118, 74, 158),
    "золотой": (206, 168, 78), "медный": (184, 110, 66),
}

KIND_NAMES = {
    "wood": "дерево", "marble": "мрамор", "metal": "металл", "fabric": "ткань",
    "leather": "кожа", "checker": "клетка", "noise": "шум", "brick": "кирпич",
    "ceramic": "керамика",
}

# Через сколько миллиметров рисунок повторяется на поверхности. Дерево, мрамор
# и кирпич — крупные узоры: при повторе каждые 140 мм (общий шаг развёртки)
# шкаф выглядел «гофрированным», потому что кольца шли слишком часто.
TILE_MM = {
    "wood": 640.0, "marble": 520.0, "brick": 360.0, "fabric": 260.0,
    "leather": 300.0, "metal": 320.0, "checker": 120.0, "noise": 260.0,
    "ceramic": 420.0,
}


def parse_color(value, fallback=(200, 200, 200)) -> tuple[int, int, int]:
    """Цвет из «#rrggbb», названия или списка чисел."""
    if value is None:
        return fallback
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        return tuple(int(max(0, min(255, float(v)))) for v in value[:3])
    text = str(value).strip().lower()
    if not text:
        return fallback
    if text.startswith("#"):
        text = text[1:]
    if len(text) in (3, 6) and all(c in "0123456789abcdef" for c in text):
        if len(text) == 3:
            text = "".join(c * 2 for c in text)
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    return fallback


def _seamless(img: np.ndarray) -> np.ndarray:
    """Делает картинку бесшовной: смешивает её со сдвигом на полпериода."""
    a = img.astype(np.float32)
    h, w = a.shape[:2]
    rolled = np.roll(np.roll(a, w // 2, axis=1), h // 2, axis=0)
    x = np.linspace(0.0, 1.0, w, endpoint=False)[None, :, None]
    y = np.linspace(0.0, 1.0, h, endpoint=False)[:, None, None]
    wx = np.sin(np.pi * x) ** 0.6
    wy = np.sin(np.pi * y) ** 0.6
    weight = (wx * wy).astype(np.float32)
    return a * weight + rolled * (1.0 - weight)


def _rng(seed: int | str) -> np.random.Generator:
    if isinstance(seed, str):
        seed = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16)
    return np.random.default_rng(int(seed) & 0xFFFFFFFF)


def _noise(size: int, cells: int, rng: np.random.Generator, smooth: int = 2) -> np.ndarray:
    """Бесшовный плавный шум 0..1 (билинейное увеличение случайной решётки)."""
    cells = max(2, int(cells))
    g = rng.random((cells + 1, cells + 1)).astype(np.float32)
    g[-1, :] = g[0, :]
    g[:, -1] = g[:, 0]
    xs = np.linspace(0, cells, size, endpoint=False, dtype=np.float32)
    x0 = np.clip(np.floor(xs).astype(np.int32), 0, cells - 1)
    tx = xs - x0
    tx = tx * tx * (3 - 2 * tx)          # smoothstep
    a = g[:, x0] * (1 - tx)[None, :] + g[:, x0 + 1] * tx[None, :]
    out = a[x0, :] * (1 - tx)[:, None] + a[x0 + 1, :] * tx[:, None]
    for _ in range(max(0, int(smooth) - 1)):
        out = 0.25 * (np.roll(out, 1, 0) + np.roll(out, -1, 0)
                      + np.roll(out, 1, 1) + np.roll(out, -1, 1))
    lo, hi = float(out.min()), float(out.max())
    return (out - lo) / max(hi - lo, 1e-6)


def _fbm(size: int, rng: np.random.Generator, octaves=(4, 9, 18, 40)) -> np.ndarray:
    total = np.zeros((size, size), dtype=np.float32)
    amp = 1.0
    norm = 0.0
    for cells in octaves:
        total += amp * _noise(size, cells, rng)
        norm += amp
        amp *= 0.55
    return total / max(norm, 1e-6)


def _mix(c1, c2, t):
    c1 = np.asarray(c1, dtype=np.float32)
    c2 = np.asarray(c2, dtype=np.float32)
    tt = np.asarray(t, dtype=np.float32)[..., None]
    return c1 * (1 - tt) + c2 * tt


def make_texture(kind: str, size: int = 512, seed: int | str = 1,
                 scale: float = 1.0) -> np.ndarray:
    """Возвращает RGB-картинку (uint8, shape size×size×3)."""
    key = KINDS.get(str(kind).strip().lower())
    if key is None:
        raise DslError(f"Неизвестная текстура «{kind}».",
                       hint="Доступно: " + ", ".join(sorted(KIND_NAMES.values())))
    n = int(max(64, min(1024, size)))
    rng = _rng(seed)
    u, v = np.meshgrid(np.linspace(0, 1, n, endpoint=False),
                       np.linspace(0, 1, n, endpoint=False))
    k = max(0.2, float(scale))
    n1 = _noise(n, 5, rng)
    n2 = _noise(n, 13, rng)
    n3 = _noise(n, 33, rng)

    if key == "wood":
        # Годичные кольца: их число целое (иначе картинка не стыкуется сама с
        # собой), а фаза волнистая по обеим осям. Частые ровные полосы на
        # фасадах шкафа читались как «рубчик», а не как дерево.
        rings_n = max(3, int(round(9 * k)))       # ~15 мм между линиями
        # Волна колец должна быть медленной и слабой: при сильном искажении
        # доски шкафа выглядят как рубчик ткани.
        warp = (0.16 * n1 + 0.07 * n2
                + 0.07 * np.sin(2 * np.pi * v + 1.1)
                + 0.05 * np.sin(2 * np.pi * u + 0.4))
        rings = 0.5 + 0.5 * np.cos((u * rings_n + warp) * 2 * np.pi)
        # Волокно вытянуто вдоль колец: размытие только по v даёт длинные
        # штрихи, а не пятна.
        fibre = _noise(n, 160, rng)
        for _ in range(16):
            fibre = 0.5 * (fibre + np.roll(fibre, -1, axis=0))
        # У поздней древесины тёмная линия узкая, а не широкая полоса.
        # Одни кольца темнее, другие почти пропадают — так доска не выглядит
        # гофрированной; редкие «сучковые» сгущения дают крупный рисунок.
        amp = np.clip(0.25 + 0.95 * _noise(n, 3, rng) + 0.25 * (n2 - 0.5), 0, 1)
        line = (1.0 - rings) ** 3.0
        t = np.clip(0.87 - 0.46 * line * amp + 0.20 * (fibre - 0.5), 0, 1)
        img = _mix((98, 60, 34), (216, 176, 128), t)
    elif key == "marble":
        turb = _fbm(n, rng, (2, 5, 11, 23))
        turb2 = _fbm(n, rng, (3, 8, 17))
        cloud = _noise(n, 7, rng)
        # Полосы задаются фазой синуса: она замкнута по u и v, поэтому
        # картинка стыкуется без шва, а жилы выходят плавными и ветвящимися.
        phase = (2 * np.pi * (u + 0.35 * np.sin(2 * np.pi * v))
                 + 5.2 * turb + 1.4 * cloud)
        vein_main = np.exp(-((np.sin(phase) / 0.16) ** 2))
        phase2 = (2 * np.pi * (v * 2 - 0.45 * np.sin(2 * np.pi * u))
                  + 7.5 * turb2)
        vein_thin = np.exp(-((np.sin(phase2) / 0.09) ** 2)) * 0.55
        veins = np.clip(vein_main + vein_thin * 0.8, 0, 1)
        tone = np.clip(0.62 + 0.32 * cloud + 0.12 * (turb - 0.5), 0, 1)
        stone = _mix((252, 251, 248), (216, 214, 210), 1.0 - tone)
        img = _mix(stone, np.array((96, 98, 106), dtype=np.float32),
                   np.clip(veins, 0, 1) ** 1.1 * 0.55)
    elif key == "metal":
        brushed = _noise(n, 256, rng, smooth=1)
        bands = max(2, int(round(24 * k)))
        band = 0.5 + 0.5 * np.sin(v * np.pi * 2 * bands + n2 * 1.4)
        t = np.clip(0.38 + 0.34 * brushed + 0.26 * band, 0, 1)
        img = _mix((92, 100, 112), (238, 242, 248), t)
    elif key == "fabric":
        threads = max(2, int(round(48 * k)))
        warp = 0.5 + 0.5 * np.sin(u * np.pi * 2 * threads)
        weft = 0.5 + 0.5 * np.sin(v * np.pi * 2 * threads)
        t = np.clip(0.35 + 0.35 * warp * weft + 0.3 * n2, 0, 1)
        img = _mix((38, 62, 96), (128, 158, 198), t)
    elif key == "leather":
        pores = _noise(n, 96, rng) * _noise(n, 12, rng)
        t = np.clip(0.35 + 0.75 * pores + 0.1 * n1, 0, 1)
        img = _mix((74, 38, 26), (172, 112, 76), t)
    elif key == "checker":
        cells = max(2, int(round(8 * k)))
        cu = np.floor(u * cells).astype(np.int32)
        cv = np.floor(v * cells).astype(np.int32)
        m = (cu + cv) % 2
        img = _mix((238, 238, 232), (34, 40, 52), m.astype(np.float32))
        img = img * (0.94 + 0.06 * n3[..., None])
    elif key == "noise":
        t = np.clip(0.25 * n1 + 0.4 * n2 + 0.35 * n3, 0, 1)
        img = _mix((70, 72, 78), (198, 200, 205), t)
    elif key == "brick":
        rows = max(4, int(round(10 * k)))
        rows += rows % 2          # чётное число рядов: смещение кладки совпадёт
        cols = max(2, int(round(5 * k)))
        vv = v * rows
        row = np.floor(vv) % rows
        uu = u * cols + (row % 2) * 0.5
        col = np.floor(uu)
        mortar_u = np.minimum(uu - col, 1 - (uu - col))
        mortar_v = np.minimum(vv - np.floor(vv), 1 - (vv - np.floor(vv)))
        mortar = (mortar_u < 0.06) | (mortar_v < 0.10)
        shade = 0.82 + 0.18 * n3
        t = np.where(mortar, 0.92, 0.18 + 0.55 * n2 + 0.15 * shade)
        img = _mix((176, 92, 70), (222, 206, 186), np.clip(t, 0, 1))
    else:  # ceramic
        t = np.clip(0.9 + 0.08 * n1 - 0.12 * n2, 0, 1)
        img = _mix((236, 240, 246), (188, 202, 220), t)
    # Все узоры собраны из периодических функций и бесшовного шума, поэтому
    # картинка стыкуется сама с собой. Прежняя «сшивка» сдвигом на полпериода
    # оставляла на панелях широкие полосы-призраки.
    return np.clip(img, 0, 255).astype(np.uint8)


def custom_height(pattern: str = "полосы", scale: float = 1.0, seed: int | str = 1,
                  size: int = 512) -> np.ndarray:
    """Карта высот своего узора 0..1 — из неё делаются цвет и рельеф."""
    key = PATTERNS.get(str(pattern).strip().lower(), "stripes")
    n = int(max(64, min(1024, size)))
    rng = _rng(seed)
    u, v = np.meshgrid(np.linspace(0, 1, n, endpoint=False),
                       np.linspace(0, 1, n, endpoint=False))
    k = max(1, int(round(float(scale) * 6)))
    n1 = _noise(n, 6, rng)
    n2 = _noise(n, 18, rng)
    if key == "stripes":
        t = 0.5 + 0.5 * np.sin(2 * np.pi * (u * k + 0.1 * n1))
        t = np.clip(t ** 0.8, 0, 1)
    elif key == "checker":
        cu = np.floor(u * k * 2).astype(np.int32)
        cv = np.floor(v * k * 2).astype(np.int32)
        t = ((cu + cv) % 2).astype(np.float32) * 0.85 + 0.1 * n2
    elif key == "waves":
        t = 0.5 + 0.5 * np.sin(2 * np.pi * (v * k) + 2.4 * np.sin(2 * np.pi * u * 2))
        t = np.clip(t * (0.75 + 0.45 * n2), 0, 1)
    elif key == "gradient":
        t = 0.5 + 0.35 * np.sin(2 * np.pi * (u * 0.5 + v * 0.5)) + 0.12 * (n2 - 0.5)
        t = np.clip(t, 0, 1)
    elif key == "dots":
        s2 = np.sin(2 * np.pi * u * k) * np.sin(2 * np.pi * v * k)
        t = np.clip((s2 > 0.55).astype(np.float32) * (0.8 + 0.2 * n2), 0, 1)
    elif key == "grid":
        fu = np.minimum((u * k) % 1.0, 1 - (u * k) % 1.0)
        fv = np.minimum((v * k) % 1.0, 1 - (v * k) % 1.0)
        t = np.clip((fu < 0.08) | (fv < 0.08), 0, 1).astype(np.float32)
        t = t * 0.9 + 0.1 * n2
    elif key == "stone":
        t = np.clip(0.45 * n1 + 0.35 * n2 + 0.2 * np.sin(2 * np.pi * (u * 3 + n1)), 0, 1)
    else:  # noise
        t = np.clip(0.4 * n1 + 0.6 * n2, 0, 1)
    return np.clip(t, 0, 1).astype(np.float32)


def make_custom(pattern: str = "полосы", color1="#3a6ea5", color2="#e8dfcf",
                scale: float = 1.0, seed: int | str = 1, size: int = 512,
                relief: float = 0.0) -> np.ndarray:
    """Своя процедурная текстура: узор + два цвета + необязательный рельеф."""
    key = PATTERNS.get(str(pattern).strip().lower(), "stripes")
    c1 = np.asarray(parse_color(color1, (58, 110, 165)), dtype=np.float32)
    c2 = np.asarray(parse_color(color2, (232, 223, 207)), dtype=np.float32)
    t = custom_height(pattern, scale=scale, seed=seed, size=size)
    img = _mix(c1, c2, t)
    r = float(max(0.0, min(1.0, relief)))
    if r > 0.001:
        # Подсветка рельефа: край «выступает», впадина затемняется. Даже без
        # карты нормалей рисунок читается как объёмный.
        gy, gx = np.gradient(t)
        light = (-gx * 0.7 + -gy * 0.7)
        light = light / max(1e-6, float(np.abs(light).max()))
        img = img * (1.0 + r * 1.15 * light[..., None])
    _ = key
    return np.clip(img, 0, 255).astype(np.uint8)


def make_normal(pattern: str = "полосы", scale: float = 1.0, seed: int | str = 1,
                size: int = 512, relief: float = 0.6) -> np.ndarray:
    """Карта нормалей из той же карты высот — рельеф виден при любом свете."""
    t = custom_height(pattern, scale=scale, seed=seed, size=size)
    r = float(max(0.02, min(1.0, relief))) * 4.0
    gy, gx = np.gradient(t)
    nx = (-gx * r)
    ny = (-gy * r)
    nz = np.ones_like(nx)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([nx / length, ny / length, nz / length], axis=-1)
    return np.clip((rgb * 0.5 + 0.5) * 255, 0, 255).astype(np.uint8)


def texture_file(kind: str, scale: float = 1.0, seed: int | str = 1,
                 size: int = 512) -> dict:
    """Создаёт PNG в папке данных и возвращает описание текстуры."""
    from .geometry import write_png

    key = KINDS.get(str(kind).strip().lower())
    if key is None:
        raise DslError(f"Неизвестная текстура «{kind}».",
                       hint="Доступно: " + ", ".join(sorted(KIND_NAMES.values())))
    image = make_texture(key, size=size, seed=seed, scale=scale)
    # имя зависит от самих пикселей: изменили генератор — изменилась и картинка
    tag = hashlib.sha1(image.tobytes()).hexdigest()[:10]
    name = f"{key}_{tag}.png"
    path = user_data_dir() / "textures" / name
    if not path.exists():
        write_png(path, image)
    return {"kind": key, "label": KIND_NAMES[key], "path": str(path),
            "scale": float(scale), "seed": str(seed),
            "tile_mm": float(TILE_MM.get(key, 140.0))}


def custom_texture_file(pattern: str = "полосы", color1: str = "#3a6ea5",
                        color2: str = "#e8dfcf", scale: float = 1.0,
                        seed: int | str = 1, size: int = 512,
                        relief: float = 0.0) -> dict:
    """Сохраняет свою текстуру и (если нужен рельеф) карту нормалей."""
    from .geometry import write_png

    image = make_custom(pattern, color1, color2, scale=scale, seed=seed, size=size,
                        relief=relief)
    tag = hashlib.sha1(image.tobytes()).hexdigest()[:10]
    name = f"custom_{tag}.png"
    path = user_data_dir() / "textures" / name
    if not path.exists():
        write_png(path, image)
    info = {"kind": "custom", "label": "своя: "
            + PATTERN_NAMES.get(PATTERNS.get(str(pattern).strip().lower(), "stripes"), pattern),
            "path": str(path), "scale": float(scale), "seed": str(seed),
            "pattern": pattern, "color1": color1, "color2": color2,
            "relief": float(relief)}
    if relief > 0.001:
        normal = make_normal(pattern, scale=scale, seed=seed, size=size, relief=relief)
        ntag = hashlib.sha1(normal.tobytes()).hexdigest()[:10]
        npath = user_data_dir() / "textures" / f"custom_normal_{ntag}.png"
        if not npath.exists():
            write_png(npath, normal)
        info["normal_path"] = str(npath)
    return info


def load_texture_image(path: str):
    """Картинка текстуры в виде, который понимает экспорт GLB (без Pillow)."""
    from .geometry import SimpleImage, read_png
    arr = read_png(path)
    if arr is None:
        return None
    if arr.shape[2] == 3:
        alpha = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
        arr = np.concatenate([arr, alpha], axis=2)
    return SimpleImage(arr)


def uv_for(verts: np.ndarray, mode: str = "cylinder",
           bbox: np.ndarray | None = None) -> np.ndarray:
    """UV-развёртка по вершинам: цилиндр вокруг вертикали, плоскость или куб."""
    v = np.asarray(verts, dtype=np.float64)
    if len(v) == 0:
        return np.zeros((0, 2), dtype=np.float32)
    lo = v.min(axis=0) if bbox is None else np.asarray(bbox[:3], dtype=np.float64)
    hi = v.max(axis=0) if bbox is None else np.asarray(bbox[3:], dtype=np.float64)
    span = np.maximum(hi - lo, 1e-9)
    # ВАЖНО: координаты уже в системе glTF (X, Y — вверх, Z).
    if mode == "planar":
        u = (v[:, 0] - lo[0]) / span[0]
        w = (v[:, 2] - lo[2]) / span[2]
    elif mode == "box":
        c = (lo + hi) / 2
        d = np.abs(v - c) / span
        axis = np.argmax(d, axis=1)
        u = np.where(axis == 0, (v[:, 2] - lo[2]) / span[2], (v[:, 0] - lo[0]) / span[0])
        w = np.where(axis == 1, (v[:, 0] - lo[0]) / span[0], (v[:, 1] - lo[1]) / span[1])
    else:  # cylinder вокруг вертикали (Y в glTF)
        cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
        u = np.arctan2(v[:, 2] - cz, v[:, 0] - cx) / (2 * np.pi) + 0.5
        w = (v[:, 1] - lo[1]) / span[1]
    return np.stack([u, w], axis=1).astype(np.float32)


def _triplanar_uv(tri: np.ndarray, tile_mm: float,
                  origin: np.ndarray | None = None) -> np.ndarray:
    """Бесшовная развёртка по граням: проекция зависит от нормали треугольника.

    Для панелей шкафа, ящиков и любых составных предметов рисунок идёт в
    миллиметрах мира, поэтому линии на соседних деталях совпадают, а не
    «съезжают» на стыках. Масштаб текстуры одинаков по всем осям.
    """
    tile = max(1.0, float(tile_mm))
    o = np.zeros(3) if origin is None else np.asarray(origin, dtype=np.float64)[:3]
    p = tri - o
    e1 = tri[:, 1] - tri[:, 0]
    e2 = tri[:, 2] - tri[:, 0]
    nrm = np.cross(e1, e2)
    axis = np.argmax(np.abs(nrm), axis=1)
    # ось нормали → какая пара мировых осей становится (u, v)
    # x: (z, y), y (вверх): (x, z), z: (x, y) — без зеркального отражения
    ax = axis[:, None]
    # x: (z, y); y (вверх): (x, z); z: (x, y)
    u = np.where(ax == 0, p[:, :, 2], p[:, :, 0]) / tile
    w = np.where(ax == 0, p[:, :, 1],
                 np.where(ax == 1, p[:, :, 2], p[:, :, 1])) / tile
    # на гранях, смотрящих в минус оси, разворачиваем u, чтобы текст не зеркалился
    neg = np.take_along_axis(nrm, axis[:, None], axis=1)[:, 0] < 0
    u = np.where(neg[:, None], -u, u)
    return np.stack([u.ravel(), w.ravel()], axis=1).astype(np.float32)


def _round_uv(tri: np.ndarray, lo: np.ndarray, hi: np.ndarray,
              tile_mm: float) -> np.ndarray:
    """Круговая развёртка: u — угол вокруг вертикали, w — высота в мм.

    Шов разрезается по треугольникам (на разрыве к u прибавляется 1), а крышки
    разворачиваются плоско — иначе на торце получается «крест» из полос.
    """
    tile = max(1.0, float(tile_mm))
    span = np.maximum(hi - lo, 1e-9)
    cx, cz = (lo[0] + hi[0]) / 2.0, (lo[2] + hi[2]) / 2.0
    u = np.arctan2(tri[:, :, 2] - cz, tri[:, :, 0] - cx) / (2.0 * np.pi) + 0.5
    w = (tri[:, :, 1] - lo[1]) / span[1]
    e1 = tri[:, 1] - tri[:, 0]
    e2 = tri[:, 2] - tri[:, 0]
    nrm = np.cross(e1, e2)
    vertical = np.abs(nrm[:, 1]) > 0.75 * (np.linalg.norm(nrm, axis=1) + 1e-12)
    if vertical.any():
        cap_u = (tri[:, :, 0] - lo[0]) / span[0]
        cap_w = (tri[:, :, 2] - lo[2]) / span[2]
        u = np.where(vertical[:, None], cap_u, u)
        w = np.where(vertical[:, None], cap_w, w)
    umin = u.min(axis=1, keepdims=True)
    umax = u.max(axis=1, keepdims=True)
    u = np.where((umax - umin > 0.5) & (u < 0.5), u + 1.0, u)
    circ = np.pi * max(span[0], span[2])
    u = u * max(1.0, round(circ / max(20.0, tile)))
    w = w * max(1.0, round(span[1] / max(20.0, tile)))
    return np.stack([u.ravel(), w.ravel()], axis=1).astype(np.float32)


def _auto_uv(tri: np.ndarray, tile_mm: float, origin: np.ndarray,
             lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Развёртка «auto»: у плоских тел — по осям, у круглых — по углу.

    Раньше решение принималось на каждый треугольник отдельно. На плавных
    переходах (плечо вазы, скругление кружки) соседние грани попадали в разные
    развёртки, и рисунок рвался пополам. Теперь решение одно на всё тело:
    считаем, какая доля площади смотрит «вкось» (не вверх и не вдоль оси X/Z),
    и если такая доля велика — всё тело разворачиваем по окружности.
    Так у вазы, гайки и колеса нет ни одного стыка между развёртками,
    а у куба, панели и ящика рисунок по-прежнему идёт в миллиметрах мира,
    поэтому линии на соседних деталях совпадают.
    """
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(n, axis=1)
    ok = area > 1e-12
    if not np.any(ok):
        return _triplanar_uv(tri, tile_mm, origin=origin)
    nn = n[ok] / area[ok][:, None]
    side = np.abs(nn[:, 1]) <= 0.7
    off = np.minimum(np.abs(nn[:, 0]), np.abs(nn[:, 2])) > 0.2
    curved = side & off
    share = float(area[ok][curved].sum() / max(area[ok].sum(), 1e-9))
    if share >= 0.25:
        return _round_uv(tri, lo, hi, tile_mm)
    return _triplanar_uv(tri, tile_mm, origin=origin)


def uv_triangles(verts: np.ndarray, faces: np.ndarray, mode: str = "auto",
                 bbox: np.ndarray | None = None, tile_mm: float = 140.0,
                 origin=None) -> np.ndarray:
    """UV на каждый угол треугольника.

    Главное отличие от uv_for: шов цилиндра не «растягивается» через всю
    текстуру — на разрыве к u прибавляется 1, а вершины не склеены между
    треугольниками. Так мрамор и дерево выглядят без видимой полосы.
    """
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    lo = v.min(axis=0) if bbox is None else np.asarray(bbox[:3], dtype=np.float64)
    hi = v.max(axis=0) if bbox is None else np.asarray(bbox[3:], dtype=np.float64)
    span = np.maximum(hi - lo, 1e-9)
    tri = v[f]  # (F, 3, 3) — координаты в glTF (X, Y вверх, Z)
    mode = (mode or "auto").lower()
    if mode in ("auto", "triplanar", "box", "грани", "авто"):
        base = lo if origin is None else np.asarray(origin, dtype=np.float64)[:3]
        return _auto_uv(tri, tile_mm, base, lo, hi)
    if mode in ("cylinder", "цилиндр", "круг"):
        return _round_uv(tri, lo, hi, tile_mm)
    if mode == "planar":
        u = (tri[:, :, 0] - lo[0]) / span[0]
        w = (tri[:, :, 2] - lo[2]) / span[2]
    else:
        u = (tri[:, :, 0] - lo[0]) / span[0]
        w = (tri[:, :, 2] - lo[2]) / span[2]
    return np.stack([u.ravel(), w.ravel()], axis=1).astype(np.float32)
