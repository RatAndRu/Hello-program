"""Удалённые демонстрационные проекты не возвращаются в основное приложение.

Сами параметрические команды фурнитуры остаются доступны; удалён именно
монтажный стенд, а не геометрический инструментарий.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from forma.webui import EXAMPLES, load_example

ROOT = Path(__file__).resolve().parents[1]


class FurnitureHardwareProjectRemovalTest(unittest.TestCase):
    def test_project_and_menu_entry_are_absent(self):
        self.assertNotIn("furniture_hardware", [key for _, key in EXAMPLES])
        self.assertFalse((ROOT / "examples/furniture_hardware.forma").exists())
        with self.assertRaises(Exception):
            load_example("furniture_hardware")

    def test_no_deleted_project_shortcut_or_versioned_menu_entries(self):
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        self.assertNotIn("'/бутылка': 'bottle'", app)
        self.assertNotIn("'/bottle': 'bottle'", app)
        for key in ("bottle", "furniture_hardware", "showcase",
                    "architecture_selectable_055", "handle_rosettes_055",
                    "selection_details_055", "smooth_transitions_054",
                    "fittings_053", "glyphs_expansion_053"):
            self.assertNotIn(key, [item for _, item in EXAMPLES], key)


if __name__ == "__main__":
    unittest.main()
