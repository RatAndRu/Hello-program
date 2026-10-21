"""Обновляет картинки для README и справки.

Запуск из папки forma:
    PYTHONPATH=. python tools/render_docs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.render import render_single, render_views  # noqa: E402
from forma.run import build  # noqa: E402

DOCS = ROOT / "docs"


def render_example(key: str, prefix: str, size: int, single: str | None = None) -> None:
    script = (ROOT / "examples" / f"{key}.forma").read_text(encoding="utf-8")
    result = build(script)
    if not result.ok:
        raise SystemExit(f"{key}: {result.error.get('message')}")
    solids = result.visible_solids()
    if single:
        path = render_single(solids, str(DOCS), filename=f"{prefix}_{single}.png",
                             size=size, view=single)
        print("готово:", path)
        return
    info = render_views(solids, str(DOCS), prefix=prefix, size=size, ss=2)
    print("готово:", ", ".join(Path(f["path"]).name for f in info["files"]),
          "+", Path(info["combined"]).name)


def main() -> int:
    DOCS.mkdir(exist_ok=True)
    render_example("human_studio", "human", 520)
    render_example("mug_studio", "mug_studio", 720, single="iso")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
