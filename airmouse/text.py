"""Русский текст поверх кадра.

Встроенные шрифты OpenCV знают только латиницу, поэтому все подписи рисуются
через Pillow (он уже в зависимостях — из него же иконка в трее). Шрифт берётся
из системных; если ни одного не нашли, текст печатается транслитом через
``cv2.putText``, чтобы приложение никогда не падало из-за шрифтов.
"""

from __future__ import annotations

import functools
import pathlib
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = (
    "C:/Windows/Fonts/segoeui.ttf",       # Windows 10/11 — самый аккуратный
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/Verdana.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
FONT_DIRS = ("C:/Windows/Fonts", "/usr/share/fonts", "/usr/local/share/fonts")

# Транслит — только для аварийного варианта без TrueType-шрифта.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


@functools.lru_cache(maxsize=16)
def _font(size: int) -> Optional[ImageFont.FreeTypeFont]:
    """Первый найденный TrueType-шрифт нужного размера (или None)."""
    for candidate in FONT_CANDIDATES:
        path = pathlib.Path(candidate)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    for directory in FONT_DIRS:
        root = pathlib.Path(directory)
        if not root.is_dir():
            continue
        for path in root.rglob("*.ttf"):
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    return None


def available() -> bool:
    """Есть ли шрифт с кириллицей (нужно для тестов и диагностики)."""
    return _font(16) is not None


def translit(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        if low in _TRANSLIT:
            mapped = _TRANSLIT[low]
            out.append(mapped.upper() if ch.isupper() and mapped else mapped)
        else:
            out.append(ch if ord(ch) < 128 else "?")
    return "".join(out)


def measure(text: str, size: int = 16) -> Tuple[int, int]:
    """Ширина и высота строки в пикселях."""
    font = _font(size)
    if font is None:
        (w, h), _ = cv2.getTextSize(translit(text), cv2.FONT_HERSHEY_SIMPLEX,
                                    size / 28.0, 1)
        return w, h + 4
    box = font.getbbox(text)
    return box[2] - box[0], box[3] - box[1]


def fit(text: str, size: int, max_w: int) -> str:
    """Обрезать строку так, чтобы она влезла в ``max_w`` пикселей (с «…»).

    Нужно для живых строк вроде «взгляд: вниз · ошибка 1.2% · дрожание 0.6%»:
    они меняются по длине каждый кадр, а панель — фиксированной ширины. Без
    обрезки длинная строка выезжала за панель и накладывалась на соседнюю.
    """
    if not text or max_w <= 0:
        return ""
    # measure() считает по bbox глифов и немного занижает реальную ширину
    # отрисовки, поэтому оставляем запас — иначе строка всё-таки выезжает
    def width(t: str) -> int:
        return int(measure(t, size)[0] * 1.12)

    if width(text) <= max_w:
        return text
    ell = "…"
    for cut in range(len(text) - 1, 0, -1):
        candidate = text[:cut].rstrip() + ell
        if width(candidate) <= max_w:
            return candidate
    return ell


def draw(
    img: np.ndarray,
    text: str,
    org: Tuple[int, int],
    size: int = 16,
    color: Tuple[int, int, int] = (235, 235, 235),
    shadow: bool = True,
) -> Tuple[int, int, int, int]:
    """Рисует строку (BGR-цвет) и возвращает занятый прямоугольник.

    ``org`` — левый верхний угол текста. Функция меняет ``img`` на месте.
    """
    if not text:
        return org[0], org[1], org[0], org[1]
    font = _font(size)
    x, y = int(org[0]), int(org[1])

    if font is None:  # аварийный путь: транслит стандартным шрифтом OpenCV
        fallback = translit(text)
        scale = size / 28.0
        (w, h), base = cv2.getTextSize(fallback, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        cv2.putText(img, fallback, (x, y + h), cv2.FONT_HERSHEY_SIMPLEX, scale,
                    color, 1, cv2.LINE_AA)
        return x, y, x + w, y + h + base

    box = font.getbbox(text)
    w, h = box[2] - box[0], box[3] - box[1]
    tile_w, tile_h = max(w + 4, 1), max(h + 4, 1)
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    drawer = ImageDraw.Draw(tile)
    ox, oy = 2 - box[0], 2 - box[1]
    if shadow:
        drawer.text((ox + 1, oy + 1), text, font=font, fill=(0, 0, 0, 200))
    drawer.text((ox, oy), text, font=font, fill=(int(color[2]), int(color[1]), int(color[0]), 255))

    arr = np.array(tile)
    img_h, img_w = img.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + tile_w, img_w), min(y + tile_h, img_h)
    if x1 > x0 and y1 > y0:
        part = arr[y0 - y:y1 - y, x0 - x:x1 - x]
        alpha = part[:, :, 3:4].astype(np.float32) / 255.0
        bgr = part[:, :, 2::-1].astype(np.float32)  # RGB -> BGR
        roi = img[y0:y1, x0:x1].astype(np.float32)
        img[y0:y1, x0:x1] = (bgr * alpha + roi * (1.0 - alpha)).astype(np.uint8)
    return x, y, x + w, y + h
