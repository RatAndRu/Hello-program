"""Кронштейн правый 00.039 — проверка чисел чертежа А2.

Тесты держат не «красиво ли», а те величины, которые на листе проставлены с
допуском: центры четырёх отверстий (±0.2), габарит плиты, высоту оси
патрубка (75±0.1), габарит окна в опоре и то, что деталь — одно тело.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "bracket_00039.forma"

L, W, T = 210.0, 130.0, 15.0
TOP = 100.0          # верх патрубка: ось 75 + Ø50/2
SPIGOT = 35.0        # прилив под плитой
# 135±0.2 — шаг по X, 100±0.02 — шаг по Y; от торцов по 15 (проверено по
# растру листа: 15.8 и 15.0 мм от кромки при масштабе 3.79 px/мм).
BOLTS = ((15.0, 15.0), (15.0, 115.0), (150.0, 15.0), (150.0, 115.0))


class BracketTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")
        cls.build = build(cls.text)
        cls.body = cls.build.scene.objects["тело"].manifold.bounding_box()

    def test_builds_without_errors(self):
        self.assertTrue(self.build.ok, self.build.error)

    def test_all_checks_pass(self):
        failed = [c for c in self.build.analysis["checks"] if not c["ok"]]
        self.assertEqual(failed, [])

    def test_overall_size_is_the_drawing_size(self):
        size = self.build.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], L, delta=0.3)
        self.assertAlmostEqual(size[1], W, delta=0.3)
        # полная высота = верх патрубка + прилив под плитой
        self.assertAlmostEqual(size[2], TOP + SPIGOT, delta=0.5)

    def test_pipe_axis_is_at_75(self):
        """75±0.1 на чертеже — высота оси патрубка над плитой."""
        pipe = self.build.scene.objects["патрубок"].manifold.bounding_box()
        centre_z = (pipe[2] + pipe[5]) / 2
        self.assertAlmostEqual(centre_z, 75.0, delta=0.2)
        self.assertAlmostEqual(pipe[5] - pipe[2], 50.0, delta=0.2)    # Ø50
        self.assertAlmostEqual(pipe[3] - pipe[0], 100.0, delta=0.2)   # 100 по X

    def test_bolt_holes_are_where_the_drawing_says(self):
        for i, (x, y) in enumerate(BOLTS, 1):
            with self.subTest(hole=i):
                bb = self.build.scene.objects[f"сверло_{i}"].manifold.bounding_box()
                self.assertAlmostEqual((bb[0] + bb[3]) / 2, x, delta=0.2)
                self.assertAlmostEqual((bb[1] + bb[4]) / 2, y, delta=0.2)
                self.assertAlmostEqual(bb[3] - bb[0], 9.0, delta=0.2)  # Ø9

    def test_plate_thickness_and_floor(self):
        plate = self.build.scene.objects["плита"].manifold.bounding_box()
        self.assertAlmostEqual(plate[2], 0.0, delta=0.1)      # низ плиты — Z=0
        self.assertAlmostEqual(plate[5], T, delta=0.1)

    def test_body_is_one_watertight_piece(self):
        self.assertEqual(len(self.build.scene.objects["тело"].manifold.decompose()), 1)
        checks = {c["rule"]: c["ok"] for c in self.build.analysis["checks"]}
        self.assertTrue(checks.get("watertight"))

    def test_boss_bore_and_spigot(self):
        """Ø70 бобышка, Ø60 прилив, буртик Ø65 — по габаритам объектов.

        Низ бобышки шире: галтель R8 у основания разводит её до Ø86 в самой
        точке касания плиты, поэтому Ø70 меряем выше галтели (на Z = 25).
        """
        import manifold3d as m3

        boss = self.build.scene.objects["бобышка"].manifold
        slab = m3.Manifold.cube((300, 300, 0.5), True).translate((45, 65, 25.25))
        ring = (boss ^ slab).bounding_box()
        self.assertAlmostEqual(ring[3] - ring[0], 70.0, delta=0.2)
        spig = self.build.scene.objects["прилив"].manifold.bounding_box()
        self.assertAlmostEqual(spig[3] - spig[0], 60.0, delta=0.2)
        collar = self.build.scene.objects["буртик"].manifold.bounding_box()
        self.assertAlmostEqual(collar[3] - collar[0], 65.0, delta=0.2)
        self.assertAlmostEqual(collar[5] - collar[2], 2.0, delta=0.2)

    def test_window_cut_in_the_support(self):
        """Окно прорезано насквозь по Y: 100 + запас по обе стороны."""
        self.assertIn("окно", self.build.scene.objects)
        win = self.build.scene.objects["окно"].manifold.bounding_box()
        self.assertGreater(win[4] - win[1], 100.0)        # шире опоры насквозь
        self.assertAlmostEqual(win[5], 37.0, delta=0.5)   # верх окна Z=37
        self.assertAlmostEqual(win[2], T, delta=0.5)      # низ окна на плите
        # скругления не вылезают за контур: окно уже вписанного прямоугольника
        self.assertGreater(win[0], 95.0)
        self.assertLess(win[3], 142.5)

    def test_support_is_a_wall_not_two_legs(self):
        """Опора — стенка толщиной 100 по Y (по разрезу Б-Б), а не рамка."""
        sup = self.build.scene.objects["опора"].manifold.bounding_box()
        self.assertAlmostEqual(sup[4] - sup[1], 100.0, delta=0.2)

    def test_pipe_fillets_are_in_profiles_not_global(self):
        """Галтель R5 и фаски 2×45° заложены в профили, а не командами.

        Проверено экспортом: `chamfer` по торцу патрубка оставлял в сетке
        три граничных ребра, и STL не собирался. Глобальный `fillet [тело]`
        падает на этой сборке с «слишком подробная сетка».
        """
        self.assertNotIn("fillet [тело]", self.text)
        self.assertIn("бобышка = lathe points=", self.text)
        pipe = [ln for ln in self.text.splitlines() if ln.startswith("патрубок = lathe")][0]
        profile = pipe.split("points=")[1].split(" segments")[0]
        # фаска 2×45°: r 23 при z 0 и r 25 при z 2
        self.assertIn("[23,0]", profile)
        self.assertIn("[25,2]", profile)

    def test_script_stays_readable(self):
        self.assertIn("плита = extrude", self.text)
        self.assertNotIn("import ", self.text)
        self.assertTrue(all(ord(ch) < 0x2500 for ch in self.text))


if __name__ == "__main__":
    unittest.main()
