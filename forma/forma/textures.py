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
KIND_NAMES = {
    "wood": "дерево", "marble": "мрамор", "metal": "металл", "fabric": "ткань",
    "leather": "кожа", "checker": "клетка", "noise": "шум", "brick": "кирпич",
    "ceramic": "керамика",
}


def _rng(seed: int | str) -> np.random.Generator:
    if isinstance(seed, str):
        seed = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16)
    return np.random.default_rng(int(seed) & 0xFFFFFFFF)


def _noise(size: int, cells: int, rng: np.random.Generator, smooth: int = 2) -> np.ndarray:
    """Периодический (бесшовный по обеим осям) плавный шум 0..1."""
    g = rng.random((cells, cells)).astype(np.float32)
    # бесшовность: сшиваем крайние строки/столбцы
    g = 0.5 * (g + np.roll(g, 1, axis=0))
    step = max(1, size // cells)
    img = np.kron(g, np.ones((step, step), dtype=np.float32))
    if img.shape[0] < size:
        pad = size - img.shape[0]
        img = np.pad(img, ((0, pad), (0, pad)), mode="wrap")
    img = img[:size, :size]
    for _ in range(smooth):
        img = 0.25 * (np.roll(img, 1, 0) + np.roll(img, -1, 0)
                      + np.roll(img, 1, 1) + np.roll(img, -1, 1))
    lo, hi = float(img.min()), float(img.max())
    return (img - lo) / max(hi - lo, 1e-6)


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
    n1 = _noise(n, 8, rng)
    n2 = _noise(n, 24, rng)
    n3 = _noise(n, 64, rng)

    if key == "wood":
        rings = 0.5 + 0.5 * np.sin((u * 9.0 * k + 0.8 * n1 + 0.35 * n2) * 2 * np.pi)
        fibre = _noise(n, 128, rng)
        t = np.clip(0.18 + 0.72 * rings ** 1.6 + 0.16 * fibre, 0, 1)
        img = _mix((104, 62, 34), (214, 166, 112), t)
    elif key == "marble":
        veins = np.abs(np.sin((u * 2.2 + v * 1.1 + 1.9 * n1 + 0.6 * n2) * np.pi * 2.2))
        veins = np.clip(1.0 - veins * 1.8, 0, 1) ** 0.65
        t = np.clip(0.86 + 0.10 * n3 - 0.55 * veins, 0, 1)
        img = _mix((246, 245, 240), (126, 122, 118), t)
        img = _mix(img, (214, 208, 198), 0.35 * n2)
    elif key == "metal":
        brushed = _noise(n, 256, rng, smooth=1)
        band = 0.5 + 0.5 * np.sin(v * np.pi * 2 * 24 * k + n2 * 3)
        t = np.clip(0.55 + 0.18 * brushed + 0.10 * band, 0, 1)
        img = _mix((120, 128, 138), (226, 232, 240), t)
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
    return np.clip(img, 0, 255).astype(np.uint8)


def texture_file(kind: str, scale: float = 1.0, seed: int | str = 1,
                 size: int = 512) -> dict:
    """Создаёт PNG в папке данных и возвращает описание текстуры."""
    from .geometry import write_png

    key = KINDS.get(str(kind).strip().lower())
    if key is None:
        raise DslError(f"Неизвестная текстура «{kind}».",
                       hint="Доступно: " + ", ".join(sorted(KIND_NAMES.values())))
    tag = hashlib.sha1(f"{key}|{float(scale):.4f}|{seed}".encode("utf-8")).hexdigest()[:10]
    name = f"{key}_{tag}.png"
    path = user_data_dir() / "textures" / name
    if not path.exists():
        write_png(path, make_texture(key, size=size, seed=seed, scale=scale))
    return {"kind": key, "label": KIND_NAMES[key], "path": str(path),
            "scale": float(scale), "seed": str(seed)}


def load_texture_image(path: str):
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        img = Image.open(path).convert("RGBA")
        return img
    except Exception:
        return None


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
