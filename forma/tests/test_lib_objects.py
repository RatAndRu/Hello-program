"""Параметрические объекты «по референсу» — числа из CC0-наборов.

Проверяем не «похоже ли», а величины: длину меча, габарит шлема, высоту стула,
высоту столба. Плюс то, что параметр действительно меняет деталь.
"""
from __future__ import annotations

import re
import unittest

from forma.lib import objects
from forma.mesh_quality import analyze as mesh_report
from forma.run import build


def make(kind: str, **options):
    return build(objects.build_script(kind, **options))


def size_of(b) -> list[float]:
    return b.analysis["metrics"]["size"]


class SwordTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = make("sword")

    def test_builds_and_passes_checks(self):
        self.assertTrue(self.build.ok, self.build.error)
        self.assertEqual([c for c in self.build.analysis["checks"] if not c["ok"]], [])

    def test_total_length_matches_typology(self):
        """Одноручный меч X–XIV: 900–1000 мм от навершия до острия."""
        height = size_of(self.build)[2]
        self.assertGreater(height, 880)
        self.assertLess(height, 1000)

    def test_blade_length_is_a_parameter(self):
        short = make("sword", blade=600)
        long_ = make("sword", blade=850)
        self.assertAlmostEqual(size_of(short)[2], 889.5 - 150, delta=1.0)
        self.assertAlmostEqual(size_of(long_)[2], 889.5 + 100, delta=1.0)

    def test_mass_estimate_is_in_steel_range(self):
        """Объём × 7.85 г/см³ — оценка массы; для нашего меча 1.4–1.8 кг."""
        volume = self.build.analysis["metrics"]["volume_cm3"]
        mass = volume * 7.85 / 1000
        self.assertGreater(mass, 1.2)
        self.assertLess(mass, 1.9)

    def test_guard_width_is_the_widest_part(self):
        width, depth, _ = size_of(self.build)
        self.assertAlmostEqual(width, 190.0, delta=0.5)   # гарда 190 мм
        self.assertLess(depth, 60)

    def test_mesh_is_closed(self):
        report = mesh_report(self.build.visible_solids()[0].manifold)
        self.assertEqual(report["boundary_edges"], 0)


class HelmetTest(unittest.TestCase):
    def test_diameter_follows_head_circumference(self):
        """Радиус тульи = max(dome, обхват/2π + 6). При 580 мм побеждает dome=105."""
        import math

        b = make("helmet", head=580, brim=70)
        radius = max(105.0, 580 / (2 * math.pi) + 6.0)
        self.assertAlmostEqual(size_of(b)[0], 2 * (radius + 70), delta=1.5)

    def test_big_head_grows_the_helmet(self):
        import math

        b = make("helmet", head=720)
        radius = max(105.0, 720 / (2 * math.pi) + 6.0)
        self.assertAlmostEqual(size_of(b)[0], 2 * (radius + 70), delta=1.5)

    def test_wider_brim_widens_the_helmet(self):
        narrow = make("helmet", brim=40)
        wide = make("helmet", brim=100)
        self.assertAlmostEqual(size_of(wide)[0] - size_of(narrow)[0], 120.0, delta=1.0)

    def test_height_is_below_the_diameter(self):
        b = make("helmet")
        width, _, height = size_of(b)
        self.assertLess(height, width / 2)     # кастрюльный шлем плоский

    def test_dome_is_hollow(self):
        b = make("helmet")
        self.assertGreater(b.analysis["metrics"]["volume_cm3"], 100)


class ChairTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = make("chair")

    def test_seat_and_back_heights(self):
        width, depth, height = size_of(self.build)
        self.assertAlmostEqual(width, 440.0, delta=0.6)
        self.assertAlmostEqual(depth, 440.0, delta=0.6)
        self.assertAlmostEqual(height, 870.0, delta=0.6)   # 450 сиденье + 420 спинка

    def test_seat_height_parameter(self):
        low = make("chair", seat_h=420)
        self.assertAlmostEqual(size_of(low)[2], 840.0, delta=0.6)

    def test_back_slats_count(self):
        two = make("chair", slats=2)
        five = make("chair", slats=5)
        self.assertLess(two.analysis["metrics"]["volume_cm3"],
                        five.analysis["metrics"]["volume_cm3"])

    def test_chair_is_one_body(self):
        self.assertEqual(self.build.analysis["metrics"]["parts"], 1)


class LampTest(unittest.TestCase):
    def test_height_parameter(self):
        b = make("lamp", height=3500)
        # высота столба + крыша (0.35·фонарь, шпиль сидит на 0.6 её высоты) + шпиль
        self.assertAlmostEqual(size_of(b)[2], 3500 + 260 * 0.35 * 0.6 + 260 * 0.2, delta=2.0)

    def test_too_short_lamp_is_rejected(self):
        with self.assertRaises(ValueError):
            objects.build_script("lamp", height=900)

    def test_arm_reaches_sideways(self):
        b = make("lamp")
        self.assertGreater(size_of(b)[0], 300)

    def test_unknown_object_is_rejected(self):
        with self.assertRaises(ValueError):
            objects.build_script("нет_такого")


class RegistryTest(unittest.TestCase):
    def test_every_object_is_registered_for_cli(self):
        from forma.lib import LIBRARIES
        kinds = ("sword", "dagger", "axe", "shield", "helmet",
                 "chair", "table", "lamp", "column")
        for kind in kinds:
            self.assertIn(kind, LIBRARIES)
            self.assertEqual(LIBRARIES[kind]["build"].__name__, "build")

    def test_params_help_covers_every_object(self):
        from forma.lib import objects as lib_objects
        helped = {name for name, _ in lib_objects.params_help()}
        self.assertEqual(helped, set(lib_objects.BUILDERS))

    def test_cli_builds_a_column_with_flutes(self):
        import io
        from contextlib import redirect_stdout

        from forma.cli import main

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["lib", "column", "height=2400", "flutes=16", "--check"])
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertIn("2 400", buffer.getvalue())

    def test_cli_builds_a_sword(self):
        import io
        from contextlib import redirect_stdout

        from forma.cli import main

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["lib", "sword", "blade=700", "--check"])
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertIn("в норме", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()


class DaggerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = make("dagger")

    def test_length_is_grip_guard_blade_pommel(self):
        """95 рукоять + 8 гарда + 280 клинок + 14 навершие = 397 мм."""
        self.assertAlmostEqual(size_of(self.build)[2], 397.0, delta=0.6)

    def test_guard_disc_is_the_widest_part(self):
        width, depth, _ = size_of(self.build)
        self.assertAlmostEqual(width, 64.0, delta=0.6)      # гарда Ø64
        self.assertAlmostEqual(depth, 64.0, delta=0.6)

    def test_blade_parameter_shortens_the_dagger(self):
        short = make("dagger", blade=200)
        self.assertAlmostEqual(size_of(short)[2], 317.0, delta=0.6)

    def test_too_short_blade_is_rejected(self):
        with self.assertRaises(ValueError):
            objects.build_script("dagger", blade=90)


class AxeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = make("axe")

    def test_haft_sets_the_height(self):
        """Рукоять 700 мм, но она выходит над головой на 6 %."""
        self.assertAlmostEqual(size_of(self.build)[2], 742.0, delta=0.6)

    def test_blade_reach_sets_the_width(self):
        """24.05 проушина + 6 перемычка + 140 вылет + 24.05 = 194.1 мм."""
        self.assertAlmostEqual(size_of(self.build)[0], 194.1, delta=1.0)

    def test_head_is_one_body_with_the_haft(self):
        self.assertEqual(self.build.analysis["metrics"]["parts"], 1)

    def test_edge_is_thinner_than_the_eye(self):
        """Спуски: тот же клин с более толстым лезвием весит больше."""
        thin = make("axe", edge=3)
        thick = make("axe", edge=12)
        self.assertLess(thin.analysis["metrics"]["volume_cm3"],
                        thick.analysis["metrics"]["volume_cm3"])

    def test_nonsense_edge_is_rejected(self):
        with self.assertRaises(ValueError):
            objects.build_script("axe", thickness=26, edge=20)


class ShieldTest(unittest.TestCase):
    def test_gabarit_and_boss_depth(self):
        """520 × (22 корпус + 60 умбон + 12 рукоять) × 700."""
        b = make("shield")
        width, depth, height = size_of(b)
        self.assertAlmostEqual(width, 520.0, delta=1.0)
        self.assertAlmostEqual(depth, 94.0, delta=2.0)
        self.assertAlmostEqual(height, 700.0, delta=1.0)

    def test_shield_without_boss_and_straps_is_a_plate(self):
        b = make("shield", boss=0, straps=0)
        self.assertAlmostEqual(size_of(b)[1], 22.0, delta=1.0)
        self.assertEqual(b.analysis["metrics"]["parts"], 1)

    def test_too_small_shield_is_rejected(self):
        with self.assertRaises(ValueError):
            objects.build_script("shield", height=200)


class TableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = make("table")

    def test_gabarit(self):
        self.assertEqual([round(v, 1) for v in size_of(self.build)], [1200.0, 700.0, 750.0])

    def test_top_overhangs_the_legs(self):
        """Столешница нависает над ножками — иначе стол выглядит «на ходулях»."""
        script = objects.build_script("table")
        spacing = [float(v) for v in re.findall(r"spacing=\[([\d.]+),([\d.]+),0\]",
                                                script)[0]]
        # шаг между ножками меньше габарита: столешница выступает с каждого края
        self.assertLessEqual(spacing[0], 1200.0 - 2 * 36)
        self.assertLessEqual(spacing[1], 700.0 - 2 * 36)

    def test_stretcher_makes_one_body(self):
        b = make("table", length=900, width=900, height=740, stretcher=300)
        self.assertEqual(b.analysis["metrics"]["parts"], 1)

    def test_taller_legs_add_material(self):
        low = make("table", height=600)
        high = make("table", height=900)
        self.assertLess(low.analysis["metrics"]["volume_cm3"],
                        high.analysis["metrics"]["volume_cm3"])

    def test_tiny_table_is_rejected(self):
        with self.assertRaises(ValueError):
            objects.build_script("table", length=300)


class ColumnTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = make("column")

    def test_gabarit_is_plinth_and_height(self):
        """Плита 1.36 диаметра в стороне, высота ровно заданная."""
        width, depth, height = size_of(self.build)
        self.assertAlmostEqual(width, 408.0, delta=1.0)
        self.assertAlmostEqual(depth, 408.0, delta=1.0)
        self.assertAlmostEqual(height, 3000.0, delta=1.0)

    def test_flutes_remove_material(self):
        plain = make("column")
        fluted = make("column", flutes=20)
        self.assertLess(fluted.analysis["metrics"]["volume_cm3"],
                        plain.analysis["metrics"]["volume_cm3"])

    def test_shaft_taper_is_visible(self):
        """Сужение 0.14: наверху ствол тоньше, чем внизу."""
        b = make("column")
        self.assertEqual(b.analysis["metrics"]["parts"], 1)

    def test_bad_taper_is_rejected(self):
        with self.assertRaises(ValueError):
            objects.build_script("column", taper=0.9)
