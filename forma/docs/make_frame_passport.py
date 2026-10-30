#!/usr/bin/env python3
"""Паспорт кадра: наносит измеренные числа на фотографию-референс.

Запуск (нужны numpy и Pillow):
    python forma/docs/make_frame_passport.py <фото> <выход.png>

Числа берутся модулем forma.vision.silhouette, то есть те же, что попадут в
постановку задачи и проверки. Ничего не «прикидывается» на глаз: если модуль
не смог измерить наклон — на картинке будет написано, что не смог.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.vision.silhouette import (mask_by_background, measure,
                                     camera_elevation, fit_top_arc)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
INK = (24, 32, 43)
ACC = (37, 99, 235)
BAD = (192, 57, 43)
GOOD = (22, 132, 73)
BG = (255, 255, 255)


def _wrap(text: str, width: int) -> list:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 <= width:
            cur = (cur + " " + wd).strip()
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return ["· " + ln for ln in lines] if lines else [text]


def main(src: str, dst: str) -> int:
    im = Image.open(src).convert("RGB")
    a = np.asarray(im)
    mask = mask_by_background(a, tol=14)
    s = measure(mask)
    cam = camera_elevation(mask)
    arc = fit_top_arc(mask)

    W, H = im.size
    pad_top, pad_bot = 150, 210
    canvas = Image.new("RGB", (max(W, 900), H + pad_top + pad_bot), BG)
    canvas.paste(im, (0, pad_top))
    d = ImageDraw.Draw(canvas, "RGBA")
    f11 = ImageFont.truetype(FONT, 11)
    f13 = ImageFont.truetype(FONT, 13)
    f15 = ImageFont.truetype(FONT_B, 15)
    f20 = ImageFont.truetype(FONT_B, 20)

    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    off = pad_top

    def L(p1, p2, color, w=2, dash=False):
        if not dash:
            d.line([p1[0], p1[1] + off, p2[0], p2[1] + off], fill=color, width=w)
            return
        (x1_, y1_), (x2_, y2_) = p1, p2
        n = max(int(np.hypot(x2_ - x1_, y2_ - y1_) / 9), 1)
        for k in range(0, n, 2):
            t1, t2 = k / n, min((k + 1) / n, 1.0)
            d.line([x1_ + (x2_ - x1_) * t1, y1_ + (y2_ - y1_) * t1 + off,
                    x1_ + (x2_ - x1_) * t2, y1_ + (y2_ - y1_) * t2 + off],
                   fill=color, width=w)

    def T(xy, txt, font=f13, color=INK, bg=True, anchor="la"):
        if bg:
            bbox = d.textbbox(xy, txt, font=font, anchor=anchor)
            d.rectangle([bbox[0] - 3, bbox[1] - 2, bbox[2] + 3, bbox[3] + 2],
                        fill=(255, 255, 255, 225))
        d.text(xy, txt, font=font, fill=color, anchor=anchor)

    # 1. габарит
    d.rectangle([x0, y0 + off, x1, y1 + off], outline=ACC, width=1)
    L((x0, y1 + 14), (x1, y1 + 14), ACC, 2)
    T(((x0 + x1) / 2, y1 + 18), f"габарит силуэта {s.width} × {s.height} px",
      f13, ACC, anchor="ma")

    # 2. ось и цилиндр
    if arc:
        cx, cy, a_, b_, resid, cover = arc
        L((cx, y0 - 8), (cx, y1 + 4), (120, 120, 120), 1, dash=True)
        d.ellipse([cx - a_, cy - b_ + off, cx + a_, cy + b_ + off], outline=GOOD, width=2)
        L((cx - a_, cy), (cx + a_, cy), GOOD, 1, dash=True)
        T((cx + a_ + 8, cy - 6), f"верхний эллипс: 2a = {2 * a_:.0f} px, "
                                 f"b/a = {b_ / a_:.2f} → наклон {cam.get('elevation_deg', 0):.1f}°",
          f13, GOOD)
        T((cx + 6, y0 - 34), f"центр оси x = {cx:.0f}", f11, (120, 120, 120))
        d.line([cx - 6, y0 + off, cx + 6, y0 + off], fill=BAD, width=2)

    # 3. профиль ширины по строкам
    for frac, wpx in s.width_profile:
        yy = y0 + frac * (y1 - y0)
        d.line([x0 - 18, yy + off, x0 - 4, yy + off], fill=INK, width=2)
        d.line([x1 + 4, yy + off, x1 + 18, yy + off], fill=INK, width=2)

    # 4. приговоры
    y = 18
    d.text((16, y), "Паспорт кадра — числа, а не впечатления", font=f20, fill=INK)
    y += 30
    facts = [
        f"высота / ширина силуэта: {s.height / s.width:.2f}",
        f"заполнение габарита: {s.fill:.2f}",
        f"вытянутость (главные оси): {s.anisotropy:.2f}",
        f"несимметричность относительно оси: {s.symmetry_err_pct:.0f} %",
    ]
    for f in facts:
        d.text((16, y), "· " + f, font=f13, fill=INK)
        y += 18

    y = H + pad_top + 10
    d.text((16, y), "Что из этого следует для модели", font=f15, fill=INK)
    y += 24
    if arc:
        cx, cy, a_, b_, resid, cover = arc
        notes = [
            (f"цилиндр: диаметр {2 * a_:.0f} px = {2 * a_ / s.height:.2f} от высоты детали; "
             f"его ось вертикальна, центр на x = {cx:.0f}", GOOD),
            (f"камера: подъём ≈ {cam.get('elevation_deg', 0):.0f}° (кажущийся; "
             f"перспектива добавляет до 3–4°), дуга описана с ошибкой {resid:.1f} px", GOOD),
            (f"профиль ширины снят в {len(s.width_profile)} сечениях — по нему считается "
             f"ошибка строк при проверке модели", INK),
            (f"не видно и нельзя придумывать: толщина полки, глубина паза, наличие "
             f"внутренних стенок — нужны второй вид или решение по назначению", BAD),
        ]
    else:
        notes = [("верхняя кромка не распознана как эллипс — наклон камеры не измерен, "
                  "его нужно подбирать рендером", BAD)]
    for txt, col in notes:
        for line in _wrap(txt, 108):
            d.text((16, y), line, font=f13, fill=col)
            y += 19
        y += 3

    Image.fromarray(np.asarray(canvas)).save(dst)
    print("готово:", dst)
    print("числа:", {k: round(v, 3) if isinstance(v, float) else v
                     for k, v in s.as_dict().items() if k not in ("width_profile", "notes")})
    print("камера:", cam)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
