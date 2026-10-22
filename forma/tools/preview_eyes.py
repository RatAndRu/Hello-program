"""Крупный план глаз: python tools/preview_eyes.py [файл]."""
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
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/preview/eyes.png")
    a = Anatomy(HumanParams(height=1780, sex="м", detail="высокий"))
    res = a.build()
    colors = {"hair": "#33241b", "eyes": "#f6f3ee", "iris": "#6b4a2f",
              "brows": "#33241b", "lashes": "#241a12", "pupils": "#120d09"}
    solids = [Solid(name="skin", manifold=res["skin"], color="#e8c2a8")]
    for name, m, kind in res["extras"]:
        solids.append(Solid(name=name, manifold=m, color=colors.get(kind, "#dddddd")))
    meshes = _prepare(solids)
    eye = a._eye_geom(solids[0].manifold)[0][0]
    size = a.head_hh * 0.30
    bb = np.array([eye[0] - size * 1.1, eye[1] - size * 1.2, eye[2] - size * 0.85,
                   eye[0] + size * 1.1, eye[1] + size * 0.9, eye[2] + size * 0.85])
    images = []
    for view in ("front", "iso", "right"):
        img, _ = _render_view(meshes, np.array([eye[0], eye[1], eye[2]]), size * 1.35,
                              view, 460, 2, bb)
        images.append(img)
    write_png(out, _to_bytes(_compose(images)))
    print("готово:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
