"""Draw selected actual CuraEngine probe paths, not printer instructions.

The input is JSON from slice_clover_led_compact_probe.mjs. Green lines are
model extrusion paths, orange lines are generated support or its brim. The
picture is a few horizontal slices, not a simulation of a successful print.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "docs" / "clover_compact_cura_probe.json"
DEFAULT_OUTPUT = ROOT / "docs" / "clover_compact_cura_layers.png"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    raise RuntimeError("Install a Cyrillic font such as DejaVu Sans or Arial")


def render(probe: dict, output: Path) -> None:
    if not probe.get("diagnostic_only", "").startswith("NOT FOR PRINTING"):
        raise ValueError("Expected non-printable diagnostic probe data")
    if probe.get("layer_count") != 31 or not probe.get("segment_counts", {}).get("SUPPORT"):
        raise ValueError("Expected the support-enabled lid probe")
    paths = probe["paths"]
    outer = [p for p in paths if p[0] == 0 and p[1] == "WALL-OUTER"]
    if not outer:
        raise ValueError("First-layer outer-wall paths are missing")
    # The outline is measured from the first-layer paths, not assumed to be at
    # the origin: CuraEngine centres the 220 × 220 mm virtual plate.
    xs = [v for p in outer for v in (p[2], p[4])]
    ys = [v for p in outer for v in (p[3], p[5])]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    image = Image.new("RGB", (2200, 2020), (10, 18, 19))
    draw = ImageDraw.Draw(image)
    white, muted, accent, orange = (232, 245, 237), (164, 189, 176), (109, 218, 151), (243, 174, 83)
    card, border = (18, 30, 31), (48, 80, 68)
    draw.text((64, 28), "ПРОБНАЯ НАРЕЗКА КРЫШКИ", font=font(48, True), fill=white)
    draw.text((66, 91), "CuraEngine 5.11 alpha  ·  слой 0,20 мм  ·  сопло 0,40 мм", font=font(25), fill=muted)
    draw.rounded_rectangle((1840, 35, 2130, 88), radius=23, outline=(241, 169, 137), width=2)
    draw.text((1864, 48), "НЕ ДЛЯ ПЕЧАТИ", font=font(21, True), fill=(241, 169, 137))
    draw.text((66, 137), "Один участок крышки в плане: зелёный — деталь, оранжевый — линии поддержки.",
              font=font(25), fill=white)

    tiles = [
        (10, "1   ВНУТРИ ОТВЕРСТИЯ", "Опора возле отверстия кнопки"),
        (15, "2   ОПОРЫ ЗАЦЕПОВ", "Четыре участка под захватами платы"),
        (26, "3   КОНЕЦ ПОДДЕРЖЕК", "Зазор перед нависающей деталью"),
        (28, "4   ТОНКИЕ ЗАХВАТЫ", "Край около 0,25 мм: очень хрупкий"),
    ]
    colors = {
        "WALL-OUTER": (123, 222, 157), "WALL-INNER": (69, 163, 111),
        "SKIN": (44, 111, 79), "FILL": (42, 96, 73),
        "SUPPORT": orange, "SUPPORT-INTERFACE": orange, "SKIRT": orange,
    }
    card_w, card_h, x0, y0, gap = 1020, 780, 65, 190, 30
    plot_size, half_mm = 700, 18.5
    scale = plot_size / (2 * half_mm)
    for index, (layer, title, caption) in enumerate(tiles):
        x = x0 + (index % 2) * (card_w + gap)
        y = y0 + (index // 2) * (card_h + gap)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=23, fill=card, outline=border, width=2)
        draw.text((x + 25, y + 20), title, font=font(27, True), fill=white)
        draw.text((x + 25, y + 58), f"Слой {layer}  /  Z = {(layer + 1) * 0.2:.1f} мм", font=font(22), fill=accent)
        draw.text((x + 25, y + 735), caption, font=font(23), fill=muted)

        # Draw on a separate image so long paths cannot escape their panel.
        plot = Image.new("RGB", (plot_size, 620), (11, 20, 20))
        pd = ImageDraw.Draw(plot)
        layer_paths = [p for p in paths if p[0] == layer and p[1] in colors]
        if not layer_paths:
            raise ValueError(f"No paths for layer {layer}")
        layer_paths.sort(key=lambda p: p[1].startswith("SUPPORT") or p[1] == "SKIRT")
        for _, kind, x1, y1, x2, y2 in layer_paths:
            def point(xp: float, yp: float) -> tuple[float, float]:
                return ((xp - cx) * scale + plot_size / 2,
                        (cy - yp) * scale + plot.height / 2)
            width = 5 if kind.startswith("SUPPORT") or kind == "SKIRT" else 3
            pd.line((point(x1, y1), point(x2, y2)), fill=colors[kind], width=width)
        image.paste(plot, (x + (card_w - plot.width) // 2, y + 100))
        draw = ImageDraw.Draw(image)

    y = 1830
    draw.line((65, y, 2135, y), fill=border, width=2)
    draw.text((65, y + 22), "Обычные поддержки, угол 50° по Cura, размещение «везде», зазор Z 0,20 мм.",
              font=font(25), fill=white)
    draw.text((65, y + 64), "Корпус в этом тесте одноцветно объединён; Bambu Studio, снятие опор и печать не проверены.",
              font=font(23), fill=muted)
    draw.text((65, y + 101), "Срезы показывают лишь одну пробную конфигурацию, а не готовую технологию.",
              font=font(23), fill=muted)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    render(json.loads(args.input.read_text(encoding="utf-8")), args.output)
    print(f"Saved {args.output}")


if __name__ == "__main__":
    main()
