"""Собрать GLB дракона для JS-проверки picking.

Тест `tests/dragon_picking_test.js` работает с настоящим экспортированным GLB
(состав узлов: base, dragon, eye_L, eye_R). Раньше этот файл лежал в git
рядом с рабочей папкой приложения; теперь `forma/exports/` — рабочий каталог
и в репозиторий не попадает, поэтому GLB собирается перед проверкой.

Запуск из forma/:

    python tools/export_dragon_glb.py            # exports/dragon_sovereign/dragon_sovereign.glb
    python tools/export_dragon_glb.py out.glb    # свой путь
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))

    from forma.run import build  # noqa: PLC0415 — путь к пакету нужен до импорта

    source = root / "examples" / "dragon_sovereign.forma"
    result = build(source.read_text(encoding="utf-8"), analyze_model=False,
                   base_dir=source.parent)
    if not result.ok:
        print(f"дракон не собрался: {result.error}")
        return 1

    if len(argv) > 1:
        target = Path(argv[1])
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
    else:
        target = root / "exports" / "dragon_sovereign" / "dragon_sovereign.glb"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(result.glb())
    names = sorted(solid.name for solid in result.visible_solids())
    print(f"{target}  {target.stat().st_size} байт, узлы: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
