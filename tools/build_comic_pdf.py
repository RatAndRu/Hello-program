#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сборка PDF-комикса «Ичиго и Кирито: Братья по оружию».

Скрипт:
  1) рисует страницы (обложка + панели с подписями + финальная страница) через Pillow;
  2) упаковывает их в PDF без сторонних библиотек (только стандартная библиотека).

Запуск:
    python tools/build_comic_pdf.py
Результат:
    comic/komiks_ichigo_i_kirito.pdf
"""

from __future__ import annotations

import os
import struct
import sys
from typing import List, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    print("Нужен Pillow:  pip install pillow")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COVER = os.path.join(ROOT, "art", "ichigo_kirito_brothers.png")
PANEL_DIR = os.path.join(ROOT, "comic", "panels")
OUT_PDF = os.path.join(ROOT, "comic", "komiks_ichigo_i_kirito.pdf")

FONT_DIR = "/usr/share/fonts/truetype/dejavu"
FONT_BOLD = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
FONT_REG = os.path.join(FONT_DIR, "DejaVuSans.ttf")

PAGE_W, PAGE_H = 1754, 1240        # A4 в альбомной ориентации при 150 dpi
BG = (18, 18, 24)
CARD = (34, 34, 44)
ACCENT = (255, 159, 67)
ACCENT2 = (95, 200, 255)
TEXT = (232, 232, 240)
MUTED = (150, 150, 165)

TITLE = "Ичиго и Кирито"
SUBTITLE = "Братья по оружию"

# (файл панели, заголовок главы, подпись)
CHAPTERS: List[Tuple[str, str, str]] = [
    ("panel01.jpg", "Пролог", "Город пал за одну ночь. Дым, луна и тишина — вот всё, что осталось от улиц."),
    ("panel02.jpg", "Глава 1. Встреча", "Ичиго думал, что остался один. Синяя вспышка — и рядом встаёт напарник."),
    ("panel03.jpg", "Глава 2. Легион", "Тьма не пришла одна: из пепла вышли сотни молчаливых масок."),
    ("panel04.jpg", "Глава 3. Братство", "Спина к спине. Один — с чёрным тесаком, второй — с двумя голубыми клинками."),
    ("panel05.jpg", "Глава 4. Натиск", "Они рубят волну за волной. Там, где стоят двое, врагу нет прохода."),
    ("panel06.jpg", "Глава 5. Босс", "А потом земля треснула. Он поднялся из чёрного тумана — и не был человеком."),
    ("panel07.jpg", "Глава 6. Один удар", "Два клинка, один вздох, один удар. Свет залил руины до самого горизонта."),
    ("panel08.jpg", "Эпилог", "Рассвет. Двое сидят на обломках и молчат — им не нужны слова, чтобы всё понять."),
]


def font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def cover_page() -> Image.Image:
    """Обложка: арт на всю страницу + затемнение снизу + название."""
    art = Image.open(COVER).convert("RGB")
    scale = max(PAGE_W / art.width, PAGE_H / art.height)
    art = art.resize((int(art.width * scale) + 1, int(art.height * scale) + 1), Image.LANCZOS)
    left = (art.width - PAGE_W) // 2
    top = (art.height - PAGE_H) // 2
    page = art.crop((left, top, left + PAGE_W, top + PAGE_H))

    # Градиентное затемнение нижней трети, чтобы текст читался
    overlay = Image.new("L", (PAGE_W, PAGE_H), 0)
    od = ImageDraw.Draw(overlay)
    start = int(PAGE_H * 0.52)
    for y in range(start, PAGE_H):
        k = (y - start) / (PAGE_H - start)
        od.line([(0, y), (PAGE_W, y)], fill=int(235 * k ** 1.2))
    page = Image.composite(Image.new("RGB", (PAGE_W, PAGE_H), (8, 8, 12)), page, overlay)

    d = ImageDraw.Draw(page)
    f_title = font(FONT_BOLD, 132)
    f_sub = font(FONT_BOLD, 58)
    f_note = font(FONT_REG, 34)

    x = 110
    d.text((x, PAGE_H - 430), TITLE, font=f_title, fill=(255, 255, 255))
    d.text((x + 6, PAGE_H - 285), SUBTITLE, font=f_sub, fill=ACCENT)
    d.line([(x + 8, PAGE_H - 200), (x + 720, PAGE_H - 200)], fill=ACCENT2, width=6)
    d.text((x + 8, PAGE_H - 170), "Фанатский комикс · 8 страниц · нарисовано ИИ",
           font=f_note, fill=MUTED)
    d.text((x + 8, PAGE_H - 118), "github.com/RatAndRu/Hello-program", font=f_note, fill=MUTED)
    return page


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> List[str]:
    lines, cur = [], ""
    for word in text.split():
        probe = (cur + " " + word).strip()
        if draw.textlength(probe, font=fnt) <= max_width or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def comic_page(index: int, filename: str, chapter: str, caption: str) -> Image.Image:
    page = Image.new("RGB", (PAGE_W, PAGE_H), BG)
    d = ImageDraw.Draw(page)
    margin = 48

    f_head = font(FONT_BOLD, 28)
    f_chapter = font(FONT_BOLD, 44)
    f_caption = font(FONT_REG, 30)

    d.text((margin, 20), f"{TITLE} — {SUBTITLE}", font=f_head, fill=MUTED)
    page_label = f"стр. {index + 1} / {len(CHAPTERS) + 2}"
    d.text((PAGE_W - margin - d.textlength(page_label, font=f_head), 20), page_label,
           font=f_head, fill=MUTED)

    # Картинка панели
    img = Image.open(os.path.join(PANEL_DIR, filename)).convert("RGB")
    area_w = PAGE_W - margin * 2
    area_h = 880
    scale = min(area_w / img.width, area_h / img.height)
    new = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    x = (PAGE_W - new.width) // 2
    y = 70
    page.paste(new, (x, y))
    d.rectangle([x - 3, y - 3, x + new.width + 2, y + new.height + 2], outline=(70, 70, 90), width=3)

    # Плашка с подписью
    caption_top = y + new.height + 34
    card = [margin, caption_top, PAGE_W - margin, PAGE_H - margin]
    d.rounded_rectangle(card, radius=18, fill=CARD, outline=(60, 60, 78), width=2)

    d.text((card[0] + 28, card[1] + 20), chapter, font=f_chapter, fill=ACCENT)
    text_lines = wrap(d, caption, f_caption, card[2] - card[0] - 56)
    ty = card[1] + 84
    for line in text_lines[:3]:
        d.text((card[0] + 28, ty), line, font=f_caption, fill=TEXT)
        ty += 42
    return page


def end_page() -> Image.Image:
    page = Image.new("RGB", (PAGE_W, PAGE_H), (10, 10, 14))
    d = ImageDraw.Draw(page)

    art = Image.open(COVER).convert("RGB")
    w = 900
    art = art.resize((w, int(art.height * w / art.width)), Image.LANCZOS)
    art = art.point(lambda v: int(v * 0.45))
    page.paste(art, ((PAGE_W - w) // 2, 150))

    f_big = font(FONT_BOLD, 150)
    f_mid = font(FONT_BOLD, 46)
    f_small = font(FONT_REG, 34)

    def center(text: str, y: int, fnt, fill):
        d.text(((PAGE_W - d.textlength(text, font=fnt)) / 2, y), text, font=fnt, fill=fill)

    center("КОНЕЦ", 640, f_big, ACCENT)
    center("Спасибо, что дочитал!", 830, f_mid, TEXT)
    center("Код и картинки: github.com/RatAndRu/Hello-program", 910, f_small, MUTED)
    center("Шахматы на Python лежат в папке chess/, запуск — start.vbs", 960, f_small, MUTED)
    return page


# ------------------------------------------------------------------ мини-генератор PDF

def _jpeg_bytes(img: Image.Image, quality: int = 92) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def write_pdf(pages: List[Image.Image], path: str, quality: int = 92) -> None:
    """Пишет PDF, где каждая страница — одна JPEG-картинка (никаких внешних зависимостей)."""
    objects: List[bytes] = []      # тела объектов, индекс = номер - 1
    total = len(pages)

    # Номера: 1 = каталог, 2 = дерево страниц, далее по 3 объекта на страницу
    page_ids = [3 + i * 3 for i in range(total)]
    content_ids = [4 + i * 3 for i in range(total)]
    image_ids = [5 + i * 3 for i in range(total)]

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {total} >>".encode("ascii"))

    for i, page in enumerate(pages):
        w, h = page.size
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] "
            f"/Resources << /XObject << /Im0 {image_ids[i]} 0 R >> >> "
            f"/Contents {content_ids[i]} 0 R >>".encode("ascii")
        )
        stream = f"q {w} 0 0 {h} 0 0 cm /Im0 Do Q".encode("ascii")
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

        data = _jpeg_bytes(page, quality)
        header = (
            f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>"
        ).encode("ascii")
        objects.append(header + b"\nstream\n" + data + b"\nendstream")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{num} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n"
    ).encode("ascii")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(out)


def main() -> int:
    missing = [f for f, _, _ in CHAPTERS if not os.path.exists(os.path.join(PANEL_DIR, f))]
    if missing:
        print("Нет файлов панелей:", ", ".join(missing))
        return 1

    pages = [cover_page()]
    for i, (fname, chapter, caption) in enumerate(CHAPTERS):
        pages.append(comic_page(i + 1, fname, chapter, caption))
        print(f"  страница {i + 2}: {chapter}")
    pages.append(end_page())

    write_pdf(pages, OUT_PDF)
    size_mb = os.path.getsize(OUT_PDF) / 1024 / 1024
    print(f"\nГотово: {os.path.relpath(OUT_PDF, ROOT)}  ({size_mb:.1f} МБ, {len(pages)} страниц)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
