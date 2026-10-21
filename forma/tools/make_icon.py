"""Генерирует иконку приложения (PNG + ICO) из настоящей 3D-модели."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import manifold3d as mf
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.geometry import write_png  # noqa: E402


def say(text: str) -> None:
    try:
        print(text, flush=True)
    except Exception:
        print(text.encode("ascii", "replace").decode("ascii"), flush=True)
from forma.model import Solid  # noqa: E402
from forma.render import _prepare, _render_view, _to_bytes  # noqa: E402


def build_mark():
    """Знак: керамическая сфера внутри металлического кольца — «форма в форме»."""
    ball = mf.Manifold.sphere(34, 128)
    ring = mf.Manifold.revolve(
        mf.CrossSection([np.array([[58, -8], [74, -8], [74, 8], [58, 8]], dtype=np.float64)]),
        160,
    )
    # наклоняем кольцо: получается «орбита»
    ring = rotate_x(ring, 68)
    ring = rotate_y(ring, 18)
    dot = mf.Manifold.sphere(8.5, 48).translate((54.0, 0.0, 12.0))
    ring = ring + dot
    base = mf.Manifold.cylinder(10, 44, 30, 96).translate((0, 0, -52))
    return [
        Solid(name="ball", manifold=ball, color="#e4e9f2", metal=0.05, rough=0.22),
        Solid(name="ring", manifold=ring, color="#6b9dff", metal=0.9, rough=0.18),
        Solid(name="base", manifold=base, color="#7ee0c0", metal=0.2, rough=0.4),
    ]


def rotate_y(m: mf.Manifold, deg: float) -> mf.Manifold:
    import math
    a = math.radians(deg)
    mat = np.array([[math.cos(a), 0, math.sin(a), 0], [0, 1, 0, 0],
                    [-math.sin(a), 0, math.cos(a), 0]], dtype=np.float64)
    return m.transform(mat)


def rotate_x(m: mf.Manifold, deg: float) -> mf.Manifold:
    import math
    a = math.radians(deg)
    mat = np.array([[1, 0, 0, 0], [0, math.cos(a), -math.sin(a), 0],
                    [0, math.sin(a), math.cos(a), 0]], dtype=np.float64)
    return m.transform(mat)


def round_mask(size: int, radius_ratio: float = 0.22) -> np.ndarray:
    r = size * radius_ratio
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) + 0.5
    dx = np.maximum(np.maximum(r - xx, xx - (size - r)), 0)
    dy = np.maximum(np.maximum(r - yy, yy - (size - r)), 0)
    dist = np.sqrt(dx * dx + dy * dy)
    return np.clip(r - dist + 0.5, 0, 1)


def render_icon(size: int) -> np.ndarray:
    solids = build_mark()
    meshes = _prepare(solids)
    img, _cam = _render_view(meshes, np.array([0.0, 0.0, 0.0]), 108.0, "iso",
                             size, 2, [-80, -80, -80, 80, 80, 80], grid=False,
                             shadow=False, bg=(0.045, 0.06, 0.085))
    mask = round_mask(size)[:, :, None]
    bg = np.array([0.045, 0.06, 0.085], dtype=np.float32)
    img = img * mask + bg * (1 - mask)
    return _to_bytes(img)


def write_ico(path: Path, images: list[tuple[int, np.ndarray]]) -> None:
    """ICO с PNG-содержимым (поддерживается Windows Vista+)."""
    import io
    import zlib

    def png_bytes(arr: np.ndarray) -> bytes:
        h, w, _ = arr.shape
        raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        out = b"\x89PNG\r\n\x1a\n"
        out += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        out += chunk(b"IDAT", zlib.compress(raw, 9))
        out += chunk(b"IEND", b"")
        return out

    entries = []
    datas = []
    offset = 6 + 16 * len(images)
    for size, arr in images:
        data = png_bytes(arr)
        entries.append(struct.pack("<BBBBHHII", 0 if size >= 256 else size,
                                   0 if size >= 256 else size, 0, 0, 1, 32,
                                   len(data), offset))
        datas.append(data)
        offset += len(data)
    header = struct.pack("<HHH", 0, 1, len(images))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + b"".join(entries) + b"".join(datas))


def main() -> int:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for s in sizes:
        arr = render_icon(s)
        images.append((s, arr))
        if s == 64:
            write_png(ROOT / "web" / "icon.png", arr)
        if s == 256:
            write_png(ROOT / "packaging" / "icon_256.png", arr)
    write_ico(ROOT / "packaging" / "icon.ico", images)
    write_png(ROOT / "packaging" / "icon_128.png", images[sizes.index(128)][1])
    say("Иконка создана: packaging/icon.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
