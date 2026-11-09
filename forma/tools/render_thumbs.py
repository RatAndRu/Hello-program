"""Плитки инструментов: изометрические миниатюры в ``web/thumbs``.

Плитка — это одна картинка и название. Ни пола, ни сетки, ни тени: на 96–128 px
любая лишняя линия превращается в шум. Поэтому рендер идёт с
``view="iso"``, ``shadow=False``, ``grid=False``.

Скрипт идемпотентен: существующий файл не перерисовывается, если не передан
``--force``. Так повторный запуск в CI не тратит минуты на ту же самую картинку.

    python tools/render_thumbs.py            # только недостающие
    python tools/render_thumbs.py --force    # перерисовать всё
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.render import render_single   # noqa: E402
from forma.run import build              # noqa: E402

OUT = ROOT / "web" / "thumbs"

# Заводские параметры для миниатюры. Это не «пресет формы»: значения взяты
# такими, чтобы силуэт операции читался в маленькой картинке.
FACTORY: dict[str, str] = {
    "box": "size=[120, 80, 60]",
    "sheet": "width=120 length=160 thickness=4",
    "cylinder": "radius=40 height=90",
    "cone": "radius=40 height=70",
    "sphere": "radius=45",
    "icosphere": "radius=45",
    "ellipsoid": "x=60 y=40 z=30",
    "prism": "sides=6 radius=40 height=60",
    "pyramid": "sides=4 radius=45 height=70",
    "octa": "radius=45",
    "torus": "major=40 minor=10",
    "tube": "diameter=40 wall=4 length=120",
    "washer": "outer=40 inner=16 thickness=6",
    "gear": "teeth=20 module=2 thickness=10",
    "shaft": "length=100 diameter=20 chamfer=1",
    "pipe": "diameter=32 wall=3 length=160",
    "capsule": "radius=20 height=80",
    "disc": "diameter=100 thickness=10",
    "bead": "diameter=40 height=40 hole=8",
    "ring": "diameter=100 thickness=8 width=12",
    "paraboloid": "diameter=80 height=60",
    "stairs": "steps=5 rise=18 run=26 width=100",
    "spring": "diameter=40 wire=3 turns=8",
}


def sample_script(op: str, params: str) -> str:
    return f"плитка = {op} {params}\n"


def render_one(op: str, params: str, force: bool = False) -> tuple[str, bool]:
    target = OUT / f"{op}.png"
    if target.exists() and not force:
        return op, False
    result = build(sample_script(op, params), analyze_model=False)
    if not result.ok:
        raise SystemExit(f"{op}: не собралось — {(result.error or {}).get('message')}")
    solids = result.scene.visible_solids()
    render_single(solids, str(OUT), f"{op}.png", size=128, ss=2, view="iso",
                  shadow=False, grid=False)
    return op, True


def main() -> int:
    parser = argparse.ArgumentParser(description="Миниатюры инструментов (плитки)")
    parser.add_argument("--force", action="store_true", help="перерисовать всё")
    parser.add_argument("--only", default="", help="через запятую: какие операции")
    args = parser.parse_args()
    wanted = [name.strip() for name in args.only.split(",") if name.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    made, skipped, failed = 0, 0, 0
    for op, params in FACTORY.items():
        if wanted and op not in wanted:
            continue
        try:
            _op, created = render_one(op, params, force=args.force)
        except SystemExit as exc:
            print(f"  ! {exc}", file=sys.stderr)
            failed += 1
            continue
        if created:
            made += 1
            print(f"  + {op}.png")
        else:
            skipped += 1
    print(f"плитки: сделано {made}, уже было {skipped}, ошибок {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
