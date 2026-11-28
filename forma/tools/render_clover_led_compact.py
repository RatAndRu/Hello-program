"""Render the compact LED-clover concept, orientation, and support diagram.

The pictures are engineering illustrations, not a slicer preview or an
approval to print. Requires the usual Forma dependencies and Pillow.
"""
from __future__ import annotations

import argparse
from copy import copy
from math import sqrt
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont
import manifold3d as mf
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forma.render import VIEWS, render_single  # noqa: E402
from forma.run import build  # noqa: E402

SCENE = ROOT / "examples" / "clover_keychain_led_compact_concept.forma"
LAYOUT = ROOT / "examples" / "clover_keychain_led_compact_print_layout.forma"
COVER = {"крышка_клевера", "кнопка", *(f"шляпка{i}" for i in range(1, 5))}
BOARD = {"макет_платы", "кнопка_платы_корпус", "нажим_платы", "чип1", "чип2"}
HOLDER = {"макет_отсека", "макет_батареи", "макет_крышечки", "макет_штатного_рычага"}
FACE = {"корпус_клевера", *(f"лист_{d}" for d in ("верх", "право", "низ", "лево"))}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
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
    raise RuntimeError("Install a Cyrillic font such as DejaVu Sans or Arial")


def without_bloom(items):
    result = []
    for obj in items:
        item = copy(obj)
        if item.name == "макет_LED":
            item.emissive = ""
            item.emissive_strength = 0
        result.append(item)
    return result


def support_diagram(path: Path) -> None:
    # Diagrammatic only: no automatic supports or generated G-code are shown.
    image = Image.new("RGB", (2100, 1190), (10, 18, 19))
    d = ImageDraw.Draw(image)
    white, muted = (232, 245, 237), (165, 190, 178)
    green, light_green, orange = (46, 125, 88), (103, 200, 142), (243, 183, 91)
    card, border = (18, 30, 31), (50, 81, 70)
    d.text((64, 35), "КРЫШКА  /  ГДЕ ВОЗМОЖНЫ ПОДДЕРЖКИ", font=font(46, True), fill=white)
    d.text((66, 100), "Схематично и не в масштабе: нарезка и реальные опоры ещё не рассчитывались.",
           font=font(25), fill=muted)
    panels = [
        (55, "A   ОГРАНИЧИТЕЛЬ КНОПКИ", "Свес около 0,65 мм"),
        (1065, "B   ЗАХВАТ ПЛАТЫ", "Свес около 0,59 мм; край толщиной 0,25 мм"),
    ]
    for x, title, subtitle in panels:
        y = 154
        d.rounded_rectangle((x, y, x + 970, y + 705), radius=24, fill=card, outline=border, width=2)
        d.text((x + 28, y + 25), title, font=font(28, True), fill=white)
        d.text((x + 28, y + 70), subtitle, font=font(23), fill=muted)
        # The lid is printed from its outside face, upwards. Green is the
        # modeled lid; the hatched amber region merely marks a potential
        # support location and is not a support model.
        plate_y, top_y = y + 555, y + 230
        d.rectangle((x + 75, plate_y, x + 825, plate_y + 70), fill=green, outline=light_green, width=2)
        d.rectangle((x + 245, top_y, x + 355, plate_y), fill=green, outline=light_green, width=2)
        d.rectangle((x + 355, top_y, x + 575, top_y + 37), fill=green, outline=light_green, width=2)
        hatch_box = (x + 365, top_y + 45, x + 565, plate_y - 10)
        d.rectangle(hatch_box, outline=orange, width=3)
        for hx in range(hatch_box[0] - 270, hatch_box[2], 23):
            # Clip the diagonal hatching to the schematic support box.
            for step in range(0, 285):
                px, py = hx + step, hatch_box[3] - step
                if hatch_box[0] <= px <= hatch_box[2] and hatch_box[1] <= py <= hatch_box[3]:
                    d.point((px, py), fill=orange)
        d.line((x + 52, plate_y + 92, x + 865, plate_y + 92), fill=(126, 149, 138), width=3)
        d.text((x + 75, plate_y + 102), "наружная сторона крышки на столе", font=font(21), fill=muted)
        d.line((x + 605, top_y + 160, x + 565, top_y + 160), fill=orange, width=4)
        d.text((x + 620, top_y + 140), "возможная", font=font(22, True), fill=orange)
        d.text((x + 620, top_y + 172), "поддержка", font=font(22, True), fill=orange)
    d.rounded_rectangle((55, 884, 2035, 1120), radius=24, fill=card, outline=border, width=2)
    d.text((83, 910), "ЧТО ПРОВЕРЯТЬ В СЛАЙСЕРЕ", font=font(27, True), fill=white)
    d.text((83, 960), "Зелёное — деталь; оранжевое — только ориентир, не готовая геометрия поддержки.",
           font=font(24), fill=muted)
    d.text((83, 1003), "Мелкие выступы, доступ для удаления, поверхность и зазоры требуют пробной нарезки.",
           font=font(24), fill=muted)
    d.text((83, 1051), "Корпус и цветные листочки печатаются вместе, лицом к столу; электронику не печатают.",
           font=font(24), fill=muted)
    image.save(path, optimize=True)


def margin_diagram(by_name, path: Path) -> None:
    """Compare the two marked gaps in the rear projection along local X=0.

    This is a 2D silhouette calculation, not a wall-thickness or fit test.
    The ear is deliberately excluded from the symmetric flower outline.
    """
    def signed_area(points):
        return float(np.sum(points[:, 0] * np.roll(points[:, 1], -1) -
                            points[:, 1] * np.roll(points[:, 0], -1)) / 2)

    lid_slice = by_name["крышка_клевера"].manifold.slice(-15)
    points = max(lid_slice.to_polygons(), key=lambda p: abs(signed_area(p)))
    if signed_area(points) < 0:
        points = points[::-1].copy()
    outline = mf.CrossSection([points]).rotate(-45)
    projected = {}
    for name in ("макет_отсека", "макет_крышечки", "макет_батареи",
                 "макет_штатного_рычага", "плюс_отсека", "минус_отсека"):
        projected[name] = by_name[name].manifold.rotate([0, 0, -45]).project()
    combined = projected["макет_отсека"]
    for name, section in projected.items():
        if name != "макет_отсека":
            combined += section
    axis = mf.CrossSection.square([0.0001, 70], True)
    outer_bounds = (outline ^ axis).bounds()
    object_bounds = (combined ^ axis).bounds()
    lower_gap = object_bounds[1] - outer_bounds[1]
    upper_gap = outer_bounds[3] - object_bounds[3]

    image = Image.new("RGB", (1900, 1180), (10, 18, 19))
    d = ImageDraw.Draw(image)
    white, muted, accent = (232, 245, 237), (165, 190, 178), (113, 230, 164)
    yellow = (249, 206, 82)
    d.text((65, 30), "ОТСТУПЫ  /  ВИД СО СТОРОНЫ КРЫШКИ", font=font(42, True), fill=white)
    d.text((67, 88), "Проекция по оси отсека, как на разметке; ушко не показано", font=font(23), fill=muted)
    d.rounded_rectangle((45, 142, 1080, 1082), radius=25, fill=(18, 30, 31), outline=(50, 81, 70), width=2)
    origin_x, origin_y, scale = 562, 607, 14.2

    def xy(x, y):
        return (origin_x + x * scale, origin_y - y * scale)

    def polygon(section, fill, outline_color=None):
        for p in section.to_polygons():
            pts = [xy(float(x), float(y)) for x, y in p]
            if len(pts) >= 3:
                d.polygon(pts, fill=fill)
                if outline_color:
                    d.line(pts + [pts[0]], fill=outline_color, width=3, joint="curve")

    polygon(outline, (30, 103, 71), (74, 158, 104))
    # The two colours distinguish the mock holder and its mock removable lid.
    polygon(projected["макет_отсека"], (63, 77, 74), (145, 164, 151))
    polygon(projected["макет_крышечки"], (137, 151, 145), (167, 181, 171))
    polygon(projected["плюс_отсека"], (230, 88, 78), (255, 158, 123))
    polygon(projected["минус_отсека"], (35, 62, 74), (119, 172, 178))
    polygon(projected["макет_штатного_рычага"], (120, 161, 134), (202, 226, 209))

    # Axial dimensions are measured against the outer contour and the union
    # of holder, factory-lid/lever and its two illustrative outgoing wires.
    def dimension(y_low, y_high, label):
        x = origin_x
        y1, y2 = xy(0, y_low)[1], xy(0, y_high)[1]
        d.line((x, y1, x, y2), fill=yellow, width=4)
        for yy in (y1, y2):
            d.line((x - 13, yy, x + 13, yy), fill=yellow, width=4)
        d.text((x + 22, (y1 + y2) / 2 - 16), label, font=font(27, True), fill=yellow,
               stroke_width=3, stroke_fill=(18, 30, 31))

    def fmt(value):
        return f"{value:.2f}".replace(".", ",") + " мм"

    dimension(object_bounds[3], outer_bounds[3], fmt(upper_gap))
    dimension(outer_bounds[1], object_bounds[1], fmt(lower_gap))
    x = 1125
    d.text((x, 194), "ДВА ПОЛЯ", font=font(29, True), fill=white)
    d.text((x, 264), "Сверху: до проводов", font=font(25), fill=muted)
    d.text((x, 301), f"≈ {fmt(upper_gap)}", font=font(40, True), fill=accent)
    d.text((x, 399), "Снизу: до держателя", font=font(25), fill=muted)
    d.text((x, 436), f"≈ {fmt(lower_gap)}", font=font(40, True), fill=accent)
    d.text((x, 535), "Разница по этой оси", font=font(25), fill=muted)
    d.text((x, 572), f"≈ {fmt(abs(upper_gap - lower_gap))}", font=font(34, True), fill=white)
    d.line((x, 655, 1832, 655), fill=(50, 81, 70), width=2)
    d.text((x, 683), "Сдвиг макета: −2,6 мм", font=font(24, True), fill=white)
    d.text((x, 725), "вдоль оси держателя.", font=font(24), fill=white)
    d.text((x, 797), "Это не минимальная толщина", font=font(22), fill=muted)
    d.text((x, 832), "стенки и не проверка посадки.", font=font(22), fill=muted)
    d.text((65, 1110), "Условные детали и провода; реальные размеры и безопасность ещё не подтверждены.",
           font=font(24), fill=muted)
    image.save(path, optimize=True)


def overview(out: Path) -> None:
    width, height = 2300, 3030
    bg, card = (10, 18, 19), (17, 29, 30)
    border, white, muted = (49, 81, 69), (232, 245, 237), (163, 188, 174)
    accent, warning = (113, 230, 164), (241, 169, 137)
    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image)
    draw.text((70, 30), "КЛЕВЕР  /  КОМПАКТНЫЙ КОНЦЕПТ", font=font(51, True), fill=white)
    draw.text((72, 100), "Симметричный корпус · однотонная крышка · схема кнопки", font=font(27), fill=muted)
    draw.rounded_rectangle((1920, 42, 2230, 98), radius=25, outline=warning, width=2)
    draw.text((1944, 57), "НЕ ДЛЯ ПЕЧАТИ", font=font(23, True), fill=warning)
    margin, gap = 70, 30
    card_w = (width - 2 * margin - gap) // 2
    card_h, first_y = 850, 153
    tiles = [
        ("01", "ЛИЦЕВАЯ СТОРОНА", "Четыре одинаковых цветных листочка", "clover_compact_front.png"),
        ("02", "ОДНОТОННАЯ КРЫШКА", "Макеты головок и утопленная кнопка", "clover_compact_back.png"),
        ("03", "СНЯТА КРЫШКА", "Отсек и провода показаны условно", "clover_compact_open.png"),
        ("04", "ОБЛЕГЧЁННАЯ ПОЛОСТЬ", "Скруглённые камеры и опоры винтов", "clover_compact_empty.png"),
        ("05", "РАЗРЕЗ КНОПКИ", "Плата и толкатель — не заводская CAD-модель", "clover_compact_section.png"),
        ("06", "ОРИЕНТАЦИЯ ДЕТАЛЕЙ", "Корпус лицом вниз; крышка и кнопка отдельно", "clover_compact_layout.png"),
    ]
    for i, (number, title, caption, filename) in enumerate(tiles):
        x = margin + (i % 2) * (card_w + gap)
        y = first_y + (i // 2) * (card_h + gap)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=25,
                               fill=card, outline=border, width=2)
        draw.text((x + 28, y + 22), number, font=font(23, True), fill=accent)
        draw.text((x + 84, y + 16), title, font=font(31, True), fill=white)
        pic = Image.open(out / filename).convert("RGB")
        # Wide section/layout views need a wider crop so their ends are not
        # clipped and the useful geometry is large enough in the overview.
        if filename.endswith("_section.png"):
            bounds = (.08, .28, .92, .75)
        elif filename.endswith("_layout.png"):
            bounds = (.04, .23, .96, .77)
        else:
            bounds = (.10, .08, .90, .94)
        left, top, right, bottom = (int(bounds[0] * pic.width), int(bounds[1] * pic.height),
                                    int(bounds[2] * pic.width), int(bounds[3] * pic.height))
        pic = pic.crop((left, top, right, bottom))
        pic.thumbnail((card_w - 70, 680), Image.Resampling.LANCZOS)
        mask = Image.new("L", pic.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, pic.width - 1, pic.height - 1), radius=15, fill=255)
        image.paste(pic, (x + (card_w - pic.width) // 2, y + 75), mask)
        draw = ImageDraw.Draw(image)
        draw.text((x + 28, y + 788), caption, font=font(23), fill=muted)
    y = 2810
    draw.line((70, y, width - 70, y), fill=border, width=2)
    draw.text((70, y + 28), "68 × 76 × 16,3  →  57 × 65 × 19,3 мм", font=font(38, True), fill=accent)
    draw.text((70, y + 90), "С платой корпус стал уже, но толще на 3 мм; размеры держателя и кнопки не обмерены.",
              font=font(24), fill=white)
    draw.text((70, y + 130), "Сборка, работа и печать не проверены; это не готовое изделие.", font=font(24), fill=muted)
    image.save(out / "clover_compact_views.png", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    built = build(SCENE.read_text(encoding="utf-8"), analyze_model=False)
    layout = build(LAYOUT.read_text(encoding="utf-8"), analyze_model=False)
    if not built.ok:
        raise RuntimeError(built.error)
    if not layout.ok:
        raise RuntimeError(layout.error)
    objects = built.visible_solids()
    by_name = {item.name: item for item in objects}
    rear = without_bloom(objects)
    # Cut through local X=0, the PCB button and the centreline of the holder.
    # Keep the negative local-X half while looking toward it from positive X.
    half = []
    normal = (-1 / sqrt(2), -1 / sqrt(2), 0)
    for item in rear:
        part = copy(item)
        part.manifold = part.manifold.trim_by_plane(normal, 0)
        if not part.manifold.is_empty() and part.manifold.volume() > 1e-8:
            half.append(part)
    VIEWS.update({
        "compact_front": ((0, 0, 1), (0, 1, 0)),
        "compact_front_iso": ((0, -.55, 1.8), (0, 1, 0)),
        "compact_back": ((0, 0, -1), (0, 1, 0)),
        "compact_local_back": ((0, 0, -1), (-1 / sqrt(2), 1 / sqrt(2), 0)),
        "compact_back_iso": ((0, .5, -1.8), (0, 1, 0)),
        "compact_section": ((1 / sqrt(2), 1 / sqrt(2), 0), (0, 0, 1)),
        "compact_layout": ((.35, -.85, 2), (0, 1, 0)),
        "compact_board": ((0, 0, -1), (1 / sqrt(2), -1 / sqrt(2), 0)),
    })
    views = [
        ("front", objects, "compact_front", 1100),
        ("iso", objects, "compact_front_iso", 1100),
        ("back", rear, "compact_back", 1100),
        ("open", [s for s in rear if s.name not in COVER | BOARD], "compact_local_back", 1100),
        ("battery", [s for s in rear if s.name not in COVER | BOARD | {"макет_крышечки"}], "compact_local_back", 1100),
        ("empty", [by_name[n] for n in FACE], "compact_back_iso", 1100),
        ("lid", [by_name[n] for n in ("крышка_клевера", "кнопка")], "compact_front_iso", 1100),
        ("board", [by_name[n] for n in BOARD], "compact_board", 1100),
        ("section", half, "compact_section", 1300),
        ("layout", layout.visible_solids(), "compact_layout", 1300),
    ]
    for name, visible, view, size in views:
        print(f"Rendering {name}: {len(visible)} objects", flush=True)
        render_single(visible, str(out), f"clover_compact_{name}.png", size=size, ss=2, view=view)
    support_diagram(out / "clover_compact_supports.png")
    margin_diagram(by_name, out / "clover_compact_margins.png")
    overview(out)
    print(f"Saved {out / 'clover_compact_views.png'}")


if __name__ == "__main__":
    main()
