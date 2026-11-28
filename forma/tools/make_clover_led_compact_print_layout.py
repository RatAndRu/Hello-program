"""Make the illustrative print orientation from the compact assembly scene.

This is deliberately NOT a print-ready export. All electronics and mock screws
are hidden; the body/inlays, lid and plunger remain experimental. Run with
``--check`` to verify that the checked-in layout is in sync with the assembly.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "examples" / "clover_keychain_led_compact_concept.forma"
LAYOUT = ROOT / "examples" / "clover_keychain_led_compact_print_layout.forma"
MARKER = "# ------------------------- Видимость"

INTRO = """# СХЕМА ОРИЕНТАЦИИ — ЭКСПЕРИМЕНТАЛЬНЫЙ МАКЕТ, НЕ ГОТОВЫЙ ФАЙЛ ДЛЯ ПЕЧАТИ.
# На столе только 7 видимых тел: многоцветный корпус (5 тел), крышка и кнопка.
# Электроника, крепёж и батарея скрыты. Многоцветная нарезка и печать не проверены.
# Этот файл воспроизводится утилитой tools/make_clover_led_compact_print_layout.py.
# Посадки, сборка, прочность и безопасность не подтверждены.

"""
HIDDEN = (
    "макет_LED", "макет_отсека", "макет_батареи", "макет_крышечки",
    "макет_штатного_рычага", "макет_платы", "кнопка_платы_корпус",
    "нажим_платы", "чип1", "чип2", "шляпка1", "шляпка2", "шляпка3",
    "шляпка4", "плюс_отсека", "минус_отсека", "плюс_LED", "минус_LED",
    "анод_LED", "катод_LED", "макет_резистора",
)
FACE_PARTS = ("корпус_клевера", "лист_верх", "лист_право", "лист_низ", "лист_лево")


def layout_content(scene: str) -> str:
    if scene.count(MARKER) != 1:
        raise ValueError("Assembly visibility marker is missing or duplicated")
    body = scene.split(MARKER, 1)[0]
    # The warning in the assembly refers to *its* export; this layout hides
    # the same mock objects explicitly, but remains a non-print-ready concept.
    old = "# провода и головки винтов: ВСЁ попадёт в экспорт. Их реальные размеры,"
    new = "# провода и головки винтов ниже СКРЫТЫ. Их реальные размеры,"
    if body.count(old) != 1:
        raise ValueError("Assembly export warning changed; review the layout")
    body = body.replace(old, new, 1)
    lines = [INTRO + body, "# --------- Схематическая раскладка деталей на Z=0 ---------"]
    lines.extend(f"hide {name}" for name in HIDDEN)
    # The five body/inlay bodies remain registered relative to one another:
    # face Z=3 becomes Z=0 and the cavity points upward. The ear also touches
    # this plane. They are parts of ONE multi-material print, not five prints.
    for name in FACE_PARTS:
        target = f"на_столе_{name}"
        lines.extend((f"{target} = rotate [{name}] angle=180 axis=x",
                      f"{target} = translate [{target}] offset=[-36,0,3]"))
    # The monochrome lid's outside face is on the bed; the loose plunger rests
    # on its flange. There are no modeled slicer supports in this scene.
    lines.extend((
        "на_столе_крышка = translate [крышка_клевера] offset=[38,0,16.3]",
        "на_столе_кнопка = rotate [кнопка] angle=180 axis=x",
        "на_столе_кнопка = translate [на_столе_кнопка] offset=[8.6267,-26.3733,-13.85]",
    ))
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the layout is out of date")
    parser.add_argument("--output", type=Path, default=LAYOUT)
    args = parser.parse_args()
    expected = layout_content(SCENE.read_text(encoding="utf-8"))
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != expected:
            print(f"Out of date: {args.output}")
            return 1
        print(f"Up to date: {args.output}")
        return 0
    args.output.write_text(expected, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
