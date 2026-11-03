"""Параметрические объекты по CC0-референсам: меч, шлем, стул, фонарь.

Проверяем числа, а не «похоже ли»: габарит, объём материала, число частей,
срабатывание проверок сценария и то, что параметры действительно меняют деталь.
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forma.lib import LIBRARIES, objects
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]


def make(kind: str, **options):
    return build(objects.build_script(kind, **options), base_dir=ROOT)


def size(b) -> list[float]:
    return [round(v, 1) for v in b.analysis["metrics"]["size"]]


def volume(b) -> float:
    return b.analysis["metrics"]["volume_cm3"]


def failed_checks(b) -> list:
    return [c for c in b.analysis.get("checks", []) if not c["ok"]]


class SwordTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = make("sword")

    def test_builds_without_errors(self):
        self.assertTrue(self.model.ok, self.model.error)
        self.assertEqual(failed_checks(self.model), [])

    def test_total_length_and_thickness(self):
        """Одноручный меч X–XIV: 890–950 мм, толщина клинка 5 мм."""
        self.assertEqual(size(self.model), [190.0, 39.0, 889.5])

    def test_one_solid_body(self):
        self.assertEqual(self.model.analysis["metrics"]["parts"], 1)

    def test_blade_length_is_a_parameter(self):
        short = make("sword", blade=600)
        self.assertAlmostEqual(short.analysis["metrics"]["size"][2], 739.5, delta=0.5)

    def test_mass_is_a_bit_heavy_but_not_absurd(self):
        """Сталь 7.85 г/см³: 204 см³ → 1.6 кг. Реальный меч — 1.0–1.3 кг:
        у нас клинок без дола и рукоять сплошная, это честно записано в докстринге."""
        steel = volume(self.model) * 7.85 / 1000
        self.assertGreater(steel, 1.3)
        self.assertLess(steel, 1.9)

    def test_short_blade_is_rejected(self):
        with self.assertRaises(ValueError):
            objects.build_script("sword", blade=150)


class HelmetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = make("helmet")

    def test_gabarit_follows_head_circumference(self):
        """Обхват 580 мм → R = 580/2π + 6 ≈ 98.3, но не меньше dome=105.
        Поля 70 мм с каждой стороны: 2·(105+70) = 350."""
        self.assertEqual(size(self.model)[:2], [350.0, 350.0])

    def test_builds_without_errors(self):
        self.assertTrue(self.model.ok, self.model.error)
        self.assertEqual(failed_checks(self.model), [])

    def test_bigger_head_gives_a_bigger_helmet(self):
        big = make("helmet", head=640)
        self.assertGreater(size(big)[0], size(self.model)[0])

    def test_bigger_brim_adds_width(self):
        wide = make("helmet", brim=100)
        self.assertAlmostEqual(size(wide)[0], size(self.model)[0] + 60, delta=0.5)

    def test_shell_is_not_solid(self):
        """Тулья полая: объём заметно меньше объёма габаритного цилиндра."""
        bbox_volume = 350 * 350 * 94.9
        self.assertLess(volume(self.model) * 1000, bbox_volume * 0.2)


class ChairTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = make("chair")

    def test_gabarit_is_seat_by_seat_by_back_height(self):
        """Сиденье 440 на 450 мм, спинка 420 → верх 870."""
        self.assertEqual(size(self.model), [440.0, 440.0, 870.0])

    def test_builds_without_errors(self):
        self.assertTrue(self.model.ok, self.model.error)
        self.assertEqual(failed_checks(self.model), [])

    def test_seat_height_is_a_parameter(self):
        low = make("chair", seat_h=430)
        self.assertAlmostEqual(low.analysis["metrics"]["size"][2], 850.0, delta=0.5)

    def test_more_slats_add_material(self):
        two = make("chair", slats=2)
        four = make("chair", slats=4)
        self.assertLess(volume(two), volume(four))

    def test_chair_is_a_single_body(self):
        self.assertEqual(self.model.analysis["metrics"]["parts"], 1)


class LampTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = make("lamp")

    def test_height_is_the_pole_and_finial(self):
        """Столб 4000 + крыша 130 + шпиль: 4150 мм по факту."""
        self.assertAlmostEqual(self.model.analysis["metrics"]["size"][2], 4150.0, delta=2.0)

    def test_builds_without_errors(self):
        self.assertTrue(self.model.ok, self.model.error)
        self.assertEqual(failed_checks(self.model), [])

    def test_bracket_reaches_sideways(self):
        width, depth, _ = self.model.analysis["metrics"]["size"]
        self.assertGreater(width, 700)
        self.assertLess(depth, 400)

    def test_lantern_size_is_a_parameter(self):
        big = make("lamp", lantern=400)
        self.assertGreater(big.analysis["metrics"]["size"][2],
                           self.model.analysis["metrics"]["size"][2])

    def test_low_lamp_is_rejected(self):
        with self.assertRaises(ValueError):
            objects.build_script("lamp", height=900)


class RegistryTest(unittest.TestCase):
    def test_every_object_is_in_the_library_registry(self):
        for kind in ("sword", "helmet", "chair", "lamp"):
            self.assertIn(kind, LIBRARIES)
            self.assertTrue(LIBRARIES[kind]["title"].startswith(objects.BUILDERS[kind][0]))

    def test_params_help_matches_builders(self):
        helped = {name for name, _ in objects.params_help()}
        self.assertEqual(helped, set(objects.BUILDERS))

    def test_cli_builds_every_object(self):
        from forma.cli import main

        for kind in ("sword", "helmet", "chair", "lamp"):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["lib", kind, "--check"])
            self.assertEqual(code, 0, f"{kind}: {buffer.getvalue()}")
            self.assertIn("2 из 2", buffer.getvalue())

    def test_unknown_object_lists_the_known_ones(self):
        with self.assertRaises(ValueError) as ctx:
            objects.build_script("топор")
        self.assertIn("sword", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
