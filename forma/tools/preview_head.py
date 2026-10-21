"""Просмотр головы фигуры: python tools/preview_head.py [--секс м] [--выход файл]."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from forma.anatomy import Anatomy, HumanParams
from forma.geometry import write_png
from forma.model import Solid
from forma.render import _prepare, _render_view, _to_bytes, _compose


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sex", default="м")
    ap.add_argument("--detail", default="высокий")
    ap.add_argument("--out", default="head_preview.png")
    ap.add_argument("--size", type=int, default=520)
    args = ap.parse_args()

    a = Anatomy(HumanParams(height=1780, sex=args.sex, detail=args.detail))
    res = a.build()
    solids = [Solid(name="skin", manifold=res["skin"], color="#e0b298")]
    for name, m, kind in res["extras"]:
        color = {"hair": "#33241b", "eyes": "#f4f1ea", "iris": "#4a3423",
                 "brows": "#33241b"}.get(kind, "#dddddd")
        solids.append(Solid(name=name, manifold=m, color=color))
    meshes = _prepare(solids)
    c = a.head_c
    radius = a.head_hh * 1.05
    bb = np.array([c[0] - a.head_w * 1.4, c[1] - a.head_d * 1.4, c[2] - a.head_hh * 1.6,
                   c[0] + a.head_w * 1.4, c[1] + a.head_d * 1.4, c[2] + a.head_hh * 1.5])
    images = []
    for view in ("front", "iso", "right"):
        img, _ = _render_view(meshes, np.array([c[0], c[1] + a.head_d * 0.2, c[2]]),
                              radius, view, args.size, 2, bb)
        images.append(img)
    out = Path(args.out)
    write_png(out, _to_bytes(_compose(images)))
    print(f"готово: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
