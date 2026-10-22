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
        rings = 0.5 + 0.5 * np.sin((u * 7.0 * k + 0.38 * n1 + 0.16 * n2) * 2 * np.pi)
        fibre = _noise(n, 128, rng)
        t = np.clip(0.18 + 0.72 * rings ** 1.6 + 0.16 * fibre, 0, 1)
        img = _mix((104, 62, 34), (214, 166, 112), t)
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
        band = 0.5 + 0.5 * np.sin(v * np.pi * 2 * 24 * k + n2 * 1.4)
        t = np.clip(0.38 + 0.34 * brushed + 0.26 * band, 0, 1)
        img = _mix((92, 100, 112), (238, 242, 248), t)
    elif key == "fabric":
        warp = 0.5 + 0.5 * np.sin(u * np.pi * 2 * 48 * k)
        weft = 0.5 + 0.5 * np.sin(v * np.pi * 2 * 48 * k)
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
        cols = max(2, int(round(5 * k)))
        vv = v * rows
        row = np.floor(vv)
        uu = u * cols + (row % 2) * 0.5
        col = np.floor(uu)
        mortar_u = np.minimum(uu - col, 1 - (uu - col))
        mortar_v = np.minimum(vv - row, 1 - (vv - row))
        mortar = (mortar_u < 0.06) | (mortar_v < 0.10)
        shade = 0.82 + 0.18 * n3
        t = np.where(mortar, 0.92, 0.18 + 0.55 * n2 + 0.15 * shade)
        img = _mix((176, 92, 70), (222, 206, 186), np.clip(t, 0, 1))
    else:  # ceramic
        t = np.clip(0.9 + 0.08 * n1 - 0.12 * n2, 0, 1)
        img = _mix((236, 240, 246), (188, 202, 220), t)
    if key not in ("checker", "brick", "marble"):
        # шов в UV-развёртке виден только на непериодической картинке
        img = _seamless(img)
    return np.clip(img, 0, 255).astype(np.uint8)


def make_custom(pattern: str = "полосы", color1="#3a6ea5", color2="#e8dfcf",
                scale: float = 1.0, seed: int | str = 1, size: int = 512) -> np.ndarray:
    """Своя процедурная текстура: узор + два цвета (бесшовная по построению)."""
    key = PATTERNS.get(str(pattern).strip().lower(), "stripes")
    n = int(max(64, min(1024, size)))
    rng = _rng(seed)
    c1 = np.asarray(parse_color(color1, (58, 110, 165)), dtype=np.float32)
    c2 = np.asarray(parse_color(color2, (232, 223, 207)), dtype=np.float32)
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
        # мягкий «перелив» без шва: косинус замыкается через период
        t = 0.5 + 0.35 * np.sin(2 * np.pi * (u * 0.5 + v * 0.5)) + 0.12 * (n2 - 0.5)
        t = np.clip(t, 0, 1)
    elif key == "dots":
        s = np.sin(2 * np.pi * u * k) * np.sin(2 * np.pi * v * k)
        t = np.clip((s > 0.55).astype(np.float32) * (0.8 + 0.2 * n2), 0, 1)
    elif key == "grid":
        fu = np.minimum((u * k) % 1.0, 1 - (u * k) % 1.0)
        fv = np.minimum((v * k) % 1.0, 1 - (v * k) % 1.0)
        t = np.clip((fu < 0.08) | (fv < 0.08), 0, 1).astype(np.float32)
        t = t * 0.9 + 0.1 * n2
    elif key == "stone":
        t = np.clip(0.45 * n1 + 0.35 * n2 + 0.2 * np.sin(2 * np.pi * (u * 3 + n1)), 0, 1)
    else:  # noise
        t = np.clip(0.4 * n1 + 0.6 * n2, 0, 1)
    img = _mix(c1, c2, np.clip(t, 0, 1))
    return np.clip(img, 0, 255).astype(np.uint8)


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
            "scale": float(scale), "seed": str(seed)}


def custom_texture_file(pattern: str = "полосы", color1: str = "#3a6ea5",
                        color2: str = "#e8dfcf", scale: float = 1.0,
                        seed: int | str = 1, size: int = 512) -> dict:
    """Сохраняет свою текстуру и возвращает описание (как у готовых)."""
    from .geometry import write_png

    image = make_custom(pattern, color1, color2, scale=scale, seed=seed, size=size)
    tag = hashlib.sha1(image.tobytes()).hexdigest()[:10]
    name = f"custom_{tag}.png"
    path = user_data_dir() / "textures" / name
    if not path.exists():
        write_png(path, image)
    key = PATTERNS.get(str(pattern).strip().lower(), "stripes")
    return {"kind": "custom", "label": "своя: " + PATTERN_NAMES.get(key, key),
            "path": str(path), "scale": float(scale), "seed": str(seed),
            "pattern": key, "color1": color1, "color2": color2}


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


def uv_triangles(verts: np.ndarray, faces: np.ndarray, mode: str = "cylinder",
                 bbox: np.ndarray | None = None, tile_mm: float = 140.0) -> np.ndarray:
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
    if mode == "planar":
        u = (tri[:, :, 0] - lo[0]) / span[0]
        w = (tri[:, :, 2] - lo[2]) / span[2]
    elif mode == "box":
        u = (tri[:, :, 0] - lo[0]) / span[0]
        w = (tri[:, :, 2] - lo[2]) / span[2]
    else:
        cx, cz = (lo[0] + hi[0]) / 2.0, (lo[2] + hi[2]) / 2.0
        u = np.arctan2(tri[:, :, 2] - cz, tri[:, :, 0] - cx) / (2.0 * np.pi) + 0.5
        w = (tri[:, :, 1] - lo[1]) / span[1]
        # крышки (нормаль вдоль вертикали) разворачиваем плоско —
        # иначе на торце получается «крест» из растянутых жил
        e1 = tri[:, 1] - tri[:, 0]
        e2 = tri[:, 2] - tri[:, 0]
        nrm = np.cross(e1, e2)
        vertical = np.abs(nrm[:, 1]) > 0.75 * (np.linalg.norm(nrm, axis=1) + 1e-12)
        if vertical.any():
            cap_u = (tri[:, :, 0] - lo[0]) / span[0]
            cap_w = (tri[:, :, 2] - lo[2]) / span[2]
            u = np.where(vertical[:, None], cap_u, u)
            w = np.where(vertical[:, None], cap_w, w)
        # разрыв шва: если треугольник переходит через 0/1, поднимаем малые u
        umin = u.min(axis=1, keepdims=True)
        umax = u.max(axis=1, keepdims=True)
        u = np.where((umax - umin > 0.5) & (u < 0.5), u + 1.0, u)
        # повторяем текстуру по окружности, чтобы рисунок был одинакового масштаба
        circ = np.pi * max(span[0], span[2])
        rep = max(1.0, round(circ / max(20.0, tile_mm)))
        u = u * rep
        w = w * max(1.0, round(span[1] / max(20.0, tile_mm)))
    return np.stack([u.ravel(), w.ravel()], axis=1).astype(np.float32)
