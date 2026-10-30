#!/usr/bin/env python3
"""Картинка «фото → первая версия → вторая версия» с числами совпадения.

Запуск (из папки forma):
    PYTHONPATH=. python docs/make_loop_figure.py <фото> <out.png> v1.forma v3.forma

Каждый вариант собирается, сравнивается с фотографией тем же модулем, что и в
приложении, и рендерится с найденного ракурса — так на картинке видно ровно то,
что видит метрика.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.run import build
from forma.geometry import read_png
from forma.vision.fit import fit_camera, compare_model, render_mask, _set_view
from forma.vision.silhouette import mask_by_background

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def photo_panel(path: str, size: int) -> Image.Image:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, 0, (w - s) // 2 + s, s)).resize((size, size), Image.LANCZOS)
    return im


def model_panel(solids, azim, elev, size: int) -> Image.Image:
    from forma import render
    key = _set_view(azim, elev)
    meshes = render._prepare(solids)
    allv = np.concatenate([m["verts"] for m in meshes], axis=0)
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    bbox = [float(lo[0]), float(lo[1]), float(lo[2]), float(hi[0]), float(hi[1]), float(hi[2])]
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo)) / 2
    img, _ = render._render_view(meshes, center, radius, key, size, 1, bbox,
                                 grid=False, shadow=False)
    arr = np.asarray(img)
    if arr.max() <= 1.0001:
        arr = arr * 255.0
    return Image.fromarray(arr.astype(np.uint8))


def main(photo: str, out: str, *scripts: str) -> int:
    size, gap, head = 380, 16, 72
    rgb = read_png(photo)
    mask = mask_by_background(rgb, tol=14)
    panels = [(photo_panel(photo, size), "фотография", ["всё, что есть на входе"], (24, 32, 43))]

    for sc in scripts:
        src = Path(sc).read_text(encoding="utf-8")
        r = build(src)
        if not r.ok:
            print("не собралась:", sc, r.error)
            continue
        solids = r.visible_solids()
        fit = fit_camera(mask, solids, size=224)
        cmp_ = compare_model(mask, solids, fit["azim_deg"], fit["elev_deg"], size=224)
        img = model_panel(solids, fit["azim_deg"], fit["elev_deg"], size)
        sub = [f"IoU {cmp_['iou']:.2f}",
               f"пропорции {cmp_['aspect_err_pct']:+.0f} %",
               f"ошибка строк {cmp_['row_err_px']:.1f} px"]
        if cmp_.get("worst_cell"):
            i, j = cmp_["worst_cell"]["cell"]
            ver = "верх" if i == 0 else ("низ" if i == 3 else "середина")
            hor = "слева" if j == 0 else ("справа" if j == 3 else "по центру")
            sub.append(f"хуже всего: {ver} {hor}")
        col = (22, 132, 73) if cmp_["verdict"] == "похоже" else (192, 57, 43)
        panels.append((img, Path(sc).stem, sub, col))
        print(Path(sc).stem, fit["azim_deg"], fit["elev_deg"], cmp_["verdict"], round(cmp_["iou"], 3))

    W = len(panels) * size + (len(panels) - 1) * gap + 40
    H = size + head + 120
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(canvas)
    f20 = ImageFont.truetype(FONT_B, 20)
    f13 = ImageFont.truetype(FONT, 13)
    d.text((20, 16), "Один и тот же объект: фото → разбор → сборка → проверка числом",
           font=f20, fill=(24, 32, 43))
    d.text((20, 44), "Совпадение силуэта считается модулем forma.vision: IoU по кадру 256, "
                     "нормировка по габариту. Порог «похоже» — 0.90.", font=f13, fill=(107, 119, 133))
    x = 20
    for img, title, lines, col in panels:
        canvas.paste(img, (x, head))
        y = head + size + 8
        d.text((x, y), title, font=ImageFont.truetype(FONT_B, 15), fill=col)
        y += 22
        for ln in lines:
            d.text((x, y), "· " + ln, font=f13, fill=(24, 32, 43) if ln.startswith("IoU") is False else col)
            y += 18
        x += size + gap
    canvas.save(out)
    print("готово:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2], *sys.argv[3:]))
