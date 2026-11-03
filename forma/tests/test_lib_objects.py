"""Параметрические объекты «по референсу» — числа из CC0-наборов.

Проверяем не «похоже ли», а величины: длину меча, габарит шлема, высоту стула,
высоту столба. Плюс то, что параметр действительно меняет деталь.
"""
from __future__ import annotations

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
        for kind in ("sword", "helmet", "chair", "lamp"):
            self.assertIn(kind, LIBRARIES)
            self.assertEqual(LIBRARIES[kind]["build"].__name__, "build")

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
