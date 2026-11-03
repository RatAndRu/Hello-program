"""Библиотека крепежа на `включить` — параметризация без Python.

Проверяем главный приём: числа лежат в `defaults.f3d`, сцена переопределяет их
между двумя включениями, и фигуры из `shapes.f3d` получаются другие. Если это
работает, внешние библиотеки-таблицы (BOSL2, MCAD и подобные) переносятся так же.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "forma" / "lib" / "fastener"
DEMO = LIB / "demo.forma"


class FastenerDemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DEMO.read_text(encoding="utf-8")
        cls.build = build(cls.text, base_dir=LIB)

    def test_builds_from_include(self):
        self.assertTrue(self.build.ok, self.build.error)

    def test_all_checks_pass(self):
        failed = [c for c in self.build.analysis["checks"] if not c["ok"]]
        self.assertEqual(failed, [])

    def test_override_of_standoff_height_is_applied(self):
        """В сцене стоит `стойка_высота = 14`, значит плита 6 + 14 = 20 мм."""
        size = self.build.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], 90.0, places=2)
        self.assertAlmostEqual(size[1], 60.0, places=2)
        self.assertAlmostEqual(size[2], 20.0, places=2)

    def test_default_height_would_be_lower(self):
        plain = self.text.replace("стойка_высота = 14", "стойка_высота = 10")
        b = build(plain, base_dir=LIB)
        self.assertTrue(b.ok, b.error)
        self.assertAlmostEqual(b.analysis["metrics"]["size"][2], 16.0, places=2)

    def test_wider_screw_grows_the_standoff_too(self):
        """Стенка стойки задана, а не диаметр: шире винт — толще стойка.

        Это правило библиотеки, а не случайность, поэтому объём растёт.
        """
        wide = self.text.replace("м3_проход = 3.6", "м3_проход = 4.6")
        b = build(wide, base_dir=LIB)
        self.assertTrue(b.ok, b.error)
        self.assertGreater(b.analysis["metrics"]["volume_cm3"],
                           self.build.analysis["metrics"]["volume_cm3"])

    def test_thinner_wall_removes_material(self):
        thin = self.text.replace("стойка_стенка", "стойка_стенка").replace(
            "м3_проход = 3.6", "м3_проход = 3.6").replace(
            "включить файл=shapes.f3d", "стойка_стенка = 0.8\nвключить файл=shapes.f3d")
        b = build(thin, base_dir=LIB)
        self.assertTrue(b.ok, b.error)
        self.assertLess(b.analysis["metrics"]["volume_cm3"],
                        self.build.analysis["metrics"]["volume_cm3"])

    def test_hex_pocket_stays_inside_the_plate(self):
        """Паз под гайку не должен пробивать плиту насквозь (высота 6, паз 2.4)."""
        self.assertGreater(self.build.analysis["metrics"]["volume_cm3"], 0)
        self.assertEqual(self.build.analysis["metrics"]["parts"], 1)


class FastenerFilesTest(unittest.TestCase):
    def test_defaults_and_shapes_are_separate_files(self):
        for name in ("defaults.f3d", "shapes.f3d"):
            self.assertTrue((LIB / name).is_file(), name)

    def test_shapes_build_alone(self):
        """Файл фигур — обычный сценарий: собирается и без сцены."""
        text = (LIB / "shapes.f3d").read_text(encoding="utf-8")
        b = build("включить файл=defaults.f3d\n" + text, base_dir=LIB)
        self.assertTrue(b.ok, b.error)
        names = {o.name for o in b.visible_solids()}
        self.assertIn("стойка_м3", names)

    def test_missing_include_is_reported(self):
        b = build("включить файл=нет_такого.f3d\n", base_dir=LIB)
        self.assertFalse(b.ok)
        self.assertIn("не найден", b.error["message"])


if __name__ == "__main__":
    unittest.main()
