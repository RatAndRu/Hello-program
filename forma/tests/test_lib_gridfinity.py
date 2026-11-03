"""Перенос Gridfinity в наши примитивы — проверка чисел, а не «на глаз».

Тесты держат то, что обещано в спецификации (42 / 41.5 / 7 / 2.6 × 4.4) и то,
что обещано нами: ящик входит в плиту без нахлёста, высота растёт по 7 мм на
юнит, магниты и перегородки меняют объём в ожидаемую сторону.

Если тест падает на габарите — сломалась геометрия переноса, а не «красота».
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forma.lib import gridfinity as gf
from forma.mesh_quality import analyze as mesh_report
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]


def build_script(script: str):
    return build(script, base_dir=ROOT)


def volume(b) -> float:
    return b.analysis["metrics"]["volume_cm3"]


def check_failures(b) -> list:
    return [c for c in b.analysis.get("checks", []) if not c["ok"]]


class RoundedRectTest(unittest.TestCase):
    def test_equal_point_count_for_any_radius(self):
        """loft требует одинаковую длину контуров — это и есть причина правила."""
        counts = {len(gf.rounded_rect(40, 30, r)) for r in (0, 0.5, 3.75, 6)}
        self.assertEqual(counts, {4 * (gf.SEG + 1)})

    def test_zero_radius_is_not_degenerate(self):
        """При r = 0 все точки угла схлопывались в одну и давали стяжки."""
        points = gf.rounded_rect(40, 30, 0)
        self.assertEqual(len(set(points)), len(points))

    def test_radius_limited_by_half_of_short_side(self):
        points = gf.rounded_rect(10, 10, 50)
        xs = [p[0] for p in points]
        self.assertLessEqual(max(xs), 5.0001)


class BinNumbersTest(unittest.TestCase):
    def test_single_unit_three_units_high(self):
        b = build_script(gf.bin_script(1, 1, 3))
        self.assertTrue(b.ok, b.error)
        size = b.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], 41.5, places=2)
        self.assertAlmostEqual(size[1], 41.5, places=2)
        self.assertAlmostEqual(size[2], 21.0, places=2)   # 3 юнита × 7 мм
        self.assertEqual(check_failures(b), [])

    def test_grid_pitch_is_42(self):
        """Каждый следующий юнит добавляет ровно шаг сетки."""
        b = build_script(gf.bin_script(2, 3, 6))
        self.assertTrue(b.ok, b.error)
        size = b.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], 41.5 + 42.0, places=2)
        self.assertAlmostEqual(size[1], 41.5 + 2 * 42.0, places=2)
        self.assertAlmostEqual(size[2], 42.0, places=2)   # 6 юнитов × 7 мм

    def test_height_grows_by_one_unit(self):
        heights = []
        for units in (3, 4, 5):
            b = build_script(gf.bin_script(1, 1, units))
            self.assertTrue(b.ok, b.error)
            heights.append(b.analysis["metrics"]["size"][2])
        self.assertAlmostEqual(heights[1] - heights[0], 7.0, places=2)
        self.assertAlmostEqual(heights[2] - heights[1], 7.0, places=2)

    def test_bin_is_single_watertight_body(self):
        b = build_script(gf.bin_script(2, 2, 4))
        self.assertTrue(b.ok, b.error)
        self.assertEqual(b.analysis["metrics"]["parts"], 1)
        self.assertEqual(mesh_report(b.visible_solids()[0].manifold)["boundary_edges"], 0)

    def test_too_low_bin_is_rejected(self):
        with self.assertRaises(ValueError):
            gf.bin_script(1, 1, 1)


class HolesAndDividersTest(unittest.TestCase):
    def test_magnets_and_screws_take_material_out(self):
        plain = volume(build_script(gf.bin_script(2, 2, 3, magnets=False, screws=False)))
        drilled = volume(build_script(gf.bin_script(2, 2, 3)))
        self.assertLess(drilled, plain)
        # 16 отверстий: магнит 2.4 и винт 4.6 глубиной — порядка 0.8 см³
        self.assertGreater(plain - drilled, 0.3)

    def test_hole_positions_follow_the_grid(self):
        holes = gf.bin_holes(2, 2)
        self.assertEqual(len(holes), 16)
        xs = sorted({round(x, 3) for x, _ in holes})
        self.assertEqual(len(xs), 4)
        # каждое отверстие — 12.75 от центра своего юнита (41.5/2 − 8), то есть
        # 8 мм от наружной стенки; проверяем это, а не абсолютные координаты
        centers = [-21.0, 21.0]
        for x in xs:
            self.assertAlmostEqual(min(abs(x - c) for c in centers), 12.75, places=2)

    def test_dividers_add_material_and_keep_it_solid(self):
        plain = volume(build_script(gf.bin_script(2, 2, 4, magnets=False, screws=False)))
        parted = build_script(gf.bin_script(2, 2, 4, magnets=False, screws=False, dividers=(2, 2)))
        self.assertTrue(parted.ok, parted.error)
        self.assertEqual(parted.analysis["metrics"]["parts"], 1)
        self.assertGreater(volume(parted), plain)


class BaseplateFitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plate = build_script(gf.baseplate_script(2, 2))
        cls.bin = build_script(gf.bin_script(1, 1, 3))

    def test_plate_size(self):
        self.assertTrue(self.plate.ok, self.plate.error)
        size = self.plate.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], 84.0, places=2)
        self.assertAlmostEqual(size[1], 84.0, places=2)
        self.assertAlmostEqual(size[2], 5.0, places=2)

    def test_bin_sits_in_the_pocket_without_interference(self):
        """Главная проверка переноса: замок ящика входит в карман плиты.

        Ящик ставится ЦЕНТРОМ В ЯЧЕЙКУ (−21, −21) и низом на дно кармана
        (0.15 мм). Попытка поставить его в (0, 0) — это стык четырёх ячеек:
        там ребро плиты, и тест сразу покажет нахлёст.
        """
        import manifold3d as mf

        plate = self.plate.visible_solids()[0].manifold
        for z in (gf.SPEC.plate_top, 0.5, 1.0):
            seated = self.bin.visible_solids()[0].manifold.translate([-21.0, -21.0, z])
            common = mf.Manifold.batch_boolean([plate, seated], mf.OpType.Intersect)
            self.assertLess(common.volume(), 0.1, f"z={z}")

    def test_stack_pitch_is_exactly_the_bin_height(self):
        """Шаг штабеля = высота ящика (21 мм): ровно на 21 нахлёста нет, ниже — есть."""
        import manifold3d as mf

        lower = self.bin.visible_solids()[0].manifold
        flush = mf.Manifold.batch_boolean([lower, lower.translate([0, 0, 21.0])],
                                          mf.OpType.Intersect)
        sunk = mf.Manifold.batch_boolean([lower, lower.translate([0, 0, 20.0])],
                                         mf.OpType.Intersect)
        self.assertLess(flush.volume(), 0.1)      # стоит на кромке, не врезается
        self.assertGreater(sunk.volume(), 5.0)    # ниже 21 мм уже мешает


class CommandLineTest(unittest.TestCase):
    def test_build_script_maps_text_parameters(self):
        script = gf.build_script(kind="bin", size="2x3", height="6", magnets="нет")
        self.assertIn("loft", script)
        self.assertNotIn("магнит =", script)
        self.assertIn("41.5", script)

    def test_plate_kind(self):
        script = gf.build_script(kind="baseplate", size="3x1")
        self.assertIn("плита", script)
        self.assertIn("126", script)      # 3 × 42

    def test_cli_prints_script(self):
        from forma.cli import main

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["lib", "gridfinity", "size=1x1", "height=3"])
        self.assertEqual(code, 0)
        text = buffer.getvalue()
        self.assertIn("loft", text)
        self.assertIn("check тело watertight", text)

    def test_cli_check_builds(self):
        from forma.cli import main

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["lib", "gridfinity", "size=1x1", "height=3", "--check"])
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertIn("в норме", buffer.getvalue())

    def test_cli_unknown_library(self):
        from forma.cli import main

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["lib", "не_такая"])
        self.assertEqual(code, 2)


class DeterminismTest(unittest.TestCase):
    def test_same_parameters_give_same_text(self):
        first = gf.bin_script(2, 2, 5, dividers=(2, 2))
        second = gf.bin_script(2, 2, 5, dividers=(2, 2))
        self.assertEqual(first, second)

    def test_spec_numbers_are_the_documented_ones(self):
        self.assertEqual(gf.SPEC.pitch, 42.0)
        self.assertEqual(gf.SPEC.base_top, 41.5)
        self.assertEqual(gf.SPEC.base_height, 7.0)
        self.assertAlmostEqual(gf.SPEC.base_top - 2 * (gf.SPEC.chamfer + gf.SPEC.flare), 35.6, places=3)
        self.assertAlmostEqual(gf.SPEC.lip_depth, 2.6)
        self.assertAlmostEqual(gf.SPEC.lip_height, 4.4)


if __name__ == "__main__":
    unittest.main()
