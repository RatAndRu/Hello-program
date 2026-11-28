"""Render the symmetric LED-clover concept and its illustrated overview.

Run from any directory with Forma's dependencies installed, for example:
    python forma/tools/render_clover_led_symmetric.py
The outputs are illustrations of the scene, not files approved for printing.
"""
from __future__ import annotations

import argparse
from copy import copy
from math import sqrt
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forma.render import VIEWS, render_single  # noqa: E402
from forma.run import build  # noqa: E402

SCENE = ROOT / "examples" / "clover_keychain_led_symmetric_concept.forma"
REAR = {
    "крышка_клевера", "зелёный_ползунок",
    *(f"зад_вставка_{direction}" for direction in ("верх", "право", "низ", "лево")),
    *(f"шляпка{i}" for i in range(1, 5)),
}
HOLDER = {"макет_отсека", "макет_крышки_отсека", "макет_батарейки", "макет_ползунка_отсека"}


def font(size: int, bold: bool = False):
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
             "/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    raise RuntimeError("Install a font with Cyrillic support (DejaVu Sans or Arial)")


def overview(out: Path):
    width, height = 2300, 2820
    bg, card = (10, 18, 19), (17, 29, 30)
    border, white, muted = (49, 81, 69), (232, 245, 237), (163, 188, 174)
    accent, warning = (113, 230, 164), (241, 169, 137)
    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    title, label, panel = font(52, True), font(23, True), font(33, True)
    subtitle, desc, small = font(27), font(25), font(23)
    draw.text((70, 32), "КЛЕВЕР  /  СИММЕТРИЧНЫЙ КОНЦЕПТ", font=title, fill=white)
    draw.text((73, 100), "Один контур корпуса и крышки · четыре одинаковых листочка", font=subtitle, fill=muted)
    draw.rounded_rectangle((1940, 42, 2228, 96), radius=25, outline=warning, width=2)
    draw.text((1963, 57), "НЕ ДЛЯ ПЕЧАТИ", font=label, fill=warning)

    margin, gap = 70, 30
    card_w = (width - 2 * margin - gap) // 2
    card_h, first_y = 995, 155
    tiles = [
        ("01", "ЛИЦО", "Симметричные листочки и зелёный LED", "clover_symmetric_front.png"),
        ("02", "ЗАДНЯЯ СТОРОНА", "Условные головки винтов и ползунок", "clover_symmetric_back.png"),
        ("03", "КРЫШКА СНЯТА", "Внутри — макет покупного отсека", "clover_symmetric_open.png"),
        ("04", "ОТСЕК УСЛОВНО СНЯТ", "Опорный буртик, провода и резистор", "clover_symmetric_cradle.png"),
    ]
    crop = (165, 150, 935, 950)
    thumb_h = 805
    thumb_w = round(thumb_h * (crop[2] - crop[0]) / (crop[3] - crop[1]))
    for index, (number, name, caption, filename) in enumerate(tiles):
        x = margin + (index % 2) * (card_w + gap)
        y = first_y + (index // 2) * (card_h + gap)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=25, fill=card, outline=border, width=2)
        draw.text((x + 28, y + 25), number, font=label, fill=accent)
        draw.text((x + 85, y + 17), name, font=panel, fill=white)
        thumbnail = Image.open(out / filename).convert("RGB").crop(crop).resize(
            (thumb_w, thumb_h), Image.Resampling.LANCZOS)
        mask = Image.new("L", thumbnail.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, thumb_w - 1, thumb_h - 1), radius=15, fill=255)
        image.paste(thumbnail, (x + (card_w - thumb_w) // 2, y + 82), mask)
        draw = ImageDraw.Draw(image)
        draw.text((x + 30, y + 930), caption, font=desc, fill=muted)

    x, y = margin, 2205
    draw.rounded_rectangle((x, y, width - margin, y + 470), radius=25, fill=card, outline=border, width=2)
    draw.text((x + 28, y + 25), "05", font=label, fill=accent)
    draw.text((x + 85, y + 17), "РАЗРЕЗ · ПОПЕРЁК МАКЕТА ОТСЕКА", font=panel, fill=white)
    section = Image.open(out / "clover_symmetric_section.png").convert("RGB").crop((200, 480, 1100, 820))
    section_w = 1000
    section_h = round(section.height * section_w / section.width)
    section = section.resize((section_w, section_h), Image.Resampling.LANCZOS)
    mask = Image.new("L", section.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, section_w - 1, section_h - 1), radius=15, fill=255)
    image.paste(section, (x + 20, y + 85), mask)
    draw = ImageDraw.Draw(image)
    tx = x + 1060
    draw.text((tx, y + 120), "68 × 76 × 16,3 мм", font=font(43, True), fill=accent)
    draw.text((tx, y + 182), "Корпус с крышкой и ушком;", font=desc, fill=white)
    draw.text((tx, y + 219), "без выступов LED и ползунка.", font=desc, fill=white)
    draw.text((tx, y + 286), "Исходный плоский клевер:", font=desc, fill=muted)
    draw.text((tx, y + 323), "≈ 39,9 × 48,9 × 3 мм.", font=desc, fill=muted)
    draw.line((70, 2705, width - 70, 2705), fill=border, width=2)
    draw.text((70, 2724), "Размеры и механизм отсека условны; настоящие детали не обмерены.", font=small, fill=muted)
    draw.text((70, 2758), "Это не модель для печати и не проверка прочности или безопасности изделия.", font=small, fill=muted)
    image.save(out / "clover_symmetric_views.png", optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    result = build(SCENE.read_text(encoding="utf-8"), analyze_model=False)
    if not result.ok:
        raise RuntimeError(result.error)
    objects = result.visible_solids()
    by_name = {obj.name: obj for obj in objects}
    # Rear/cutaway views do not need emissive bloom obscuring the interior.
    rear_objects = []
    for obj in objects:
        item = copy(obj)
        if item.name == "макет_LED":
            item.emissive = ""
            item.emissive_strength = 0
        rear_objects.append(item)
    section_objects = []
    for obj in rear_objects:
        item = copy(obj)
        # Keep local holder Y <= 10.8 mm: cuts across its fixed end and pads.
        item.manifold = item.manifold.trim_by_plane((1 / sqrt(2), -1 / sqrt(2), 0), -10.8)
        if not item.manifold.is_empty() and item.manifold.volume() > 1e-8:
            section_objects.append(item)
    VIEWS.update({
        "symmetric_top": ((0, 0, 1), (0, 1, 0)),
        "symmetric_top_iso": ((0, -0.55, 1.8), (0, 1, 0)),
        "symmetric_bottom": ((0, 0, -1), (0, 1, 0)),
        "symmetric_bottom_iso": ((0, 0.5, -1.8), (0, 1, 0)),
        "symmetric_side": ((1, -1, 0.25), (0, 0, 1)),
        "symmetric_section": ((-1 / sqrt(2), 1 / sqrt(2), 0), (0, 0, 1)),
    })
    views = [
        ("front", objects, "symmetric_top", 1100),
        ("iso", objects, "symmetric_top_iso", 1100),
        ("back", rear_objects, "symmetric_bottom", 1100),
        ("rear_iso", rear_objects, "symmetric_bottom_iso", 1100),
        ("open", [s for s in rear_objects if s.name not in REAR], "symmetric_bottom", 1100),
        ("battery", [s for s in rear_objects if s.name not in REAR | {"макет_крышки_отсека"}], "symmetric_bottom", 1100),
        ("cradle", [s for s in rear_objects if s.name not in REAR | HOLDER], "symmetric_bottom", 1100),
        ("cover", [by_name[n] for n in ("крышка_клевера", "зелёный_ползунок")], "symmetric_top_iso", 1100),
        ("side", rear_objects, "symmetric_side", 1100),
        ("section", section_objects, "symmetric_section", 1300),
    ]
    for name, visible, view, size in views:
        filename = f"clover_symmetric_{name}.png"
        print(f"Rendering {filename} ({len(visible)} objects)", flush=True)
        render_single(visible, str(out), filename, size=size, ss=2, view=view)
    overview(out)
    print(f"Saved {out / 'clover_symmetric_views.png'}")


if __name__ == "__main__":
    main()
