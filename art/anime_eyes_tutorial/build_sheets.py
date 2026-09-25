"""Собирает контрольные листы: 4 шага отрисовки глаза в ряд с подписями."""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))

STYLES = [
    ("A", "Глаз A — мягкий круглый (бирюзовый)",
     ["tutorial_A_step1_sketch.png", "tutorial_A_step2_lineart.png",
      "tutorial_A_step3_shading.png", "tutorial_A_step4_final.png"]),
    ("B", "Глаз B — заводящий вытянутый (изумрудный)",
     ["tutorial_B_step1_sketch.png", "tutorial_B_step2_lineart.png",
      "tutorial_B_step3_shading.png", "tutorial_B_step4_final.png"]),
    ("C", "Глаз C — звёздный мечтательный (фиолетовый)",
     ["tutorial_C_step1_sketch.png", "tutorial_C_step2_lineart.png",
      "tutorial_C_step3_shading.png", "tutorial_C_step4_final.png"]),
]
STEP_LABELS = ["1 · Конструктив", "2 · Обводка", "3 · Тона и тени", "4 · Финал"]
CELL_H = 480
TITLE_H = 70
LABEL_H = 44
PAD = 16


def find_font(bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
        "/usr/share/fonts/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def make_sheet(key, title, files):
    fonts = (find_font(False) or "", find_font(True) or "")
    f_label = ImageFont.truetype(fonts[0], 26) if fonts[0] else ImageFont.load_default()
    f_title = ImageFont.truetype(fonts[1], 34) if fonts[1] else ImageFont.load_default()

    cells = []
    for i, name in enumerate(files):
        path = os.path.join(BASE, name)
        if os.path.exists(path):
            im = Image.open(path).convert("RGB")
            w = int(im.width * CELL_H / im.height)
            cells.append(im.resize((w, CELL_H), Image.LANCZOS))
        else:
            cells.append(None)  # placeholder

    cw = max((c.width for c in cells if c), default=854)
    W = cw * 4 + PAD * 5
    H = TITLE_H + LABEL_H + CELL_H + PAD * 3
    sheet = Image.new("RGB", (W, H), (245, 244, 240))
    d = ImageDraw.Draw(sheet)

    # заголовок
    if fonts[1]:
        tw = d.textlength(title, font=f_title)
        d.text(((W - tw) / 2, (TITLE_H - 34) / 2), title, fill=(30, 30, 30), font=f_title)
    y_img = TITLE_H + LABEL_H + PAD

    for i, cell in enumerate(cells):
        x = PAD + i * (cw + PAD)
        label = STEP_LABELS[i]
        if cell is None:
            # серый плейсхолдер «финал готовится»
            ph = Image.new("RGB", (cw, CELL_H), (215, 213, 208))
            dp = ImageDraw.Draw(ph)
            txt = "4 · Финал —\nв следующем сообщении"
            if fonts[0]:
                for j, line in enumerate(txt.split("\n")):
                    lw = dp.textlength(line, font=f_label)
                    dp.text(((cw - lw) / 2, CELL_H / 2 - 30 + j * 34), line,
                            fill=(110, 108, 104), font=f_label)
            sheet.paste(ph, (x, y_img))
        else:
            sheet.paste(cell, (x, y_img))
        d.text((x, TITLE_H + 8), label, fill=(30, 30, 30), font=f_label)
        d.rectangle([x, y_img, x + cell.width if cell else x + cw,
                     y_img + CELL_H], outline=(180, 178, 172), width=2)

    out = os.path.join(BASE, "sheet_%s.png" % key)
    sheet.save(out)
    print("sheet:", out, os.path.getsize(out) // 1024, "KB")


def main():
    for key, title, files in STYLES:
        make_sheet(key, title, files)


if __name__ == "__main__":
    main()
