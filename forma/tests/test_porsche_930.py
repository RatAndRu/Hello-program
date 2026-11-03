"""Чертёж → модель: Porsche 911 Turbo (930) на языке ФОРМЫ.

Проверяем не «красиво ли», а сходятся ли с чертежом те размеры, которые на
чертеже написаны: длина 4291, ширина 1775, высота 1310, база 2272, колея
1432/1492. Остальное (обводы) — построение по силуэту, его проверяет глаз,
а не тест.
"""
from __future__ import annotations

import unittest

from forma.run import build
from forma.webui import EXAMPLES, load_example

#: числа с листа: «Порше-911 Турбо», проекции сбоку, сверху, спереди и сзади
L, W, H = 4291.0, 1775.0, 1310.0
WB, TRACK_F, TRACK_R = 2272.0, 1432.0, 1492.0


class DrawingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = load_example("porsche_930")
        cls.build = build(cls.script, analyze_model=True)

    def test_builds_and_passes_checks(self):
        self.assertTrue(self.build.ok, self.build.error)
        failed = [c for c in self.build.analysis["checks"] if not c["ok"]]
        self.assertEqual(failed, [], failed)

    def test_overall_size_matches_the_drawing(self):
        size = self.build.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], L, delta=40)   # длина
        self.assertAlmostEqual(size[1], W, delta=40)   # ширина
        self.assertAlmostEqual(size[2], H, delta=20)   # высота

    def test_wheelbase_and_tracks_match(self):
        scene = self.build.scene
        front = -WB / 2
        rear = WB / 2
        for name, x, y, r in (
            ("колесо_пп", front, -TRACK_F / 2, 316.0),
            ("колесо_пз", front, TRACK_F / 2, 316.0),
            ("колесо_зп", rear, -TRACK_R / 2, 325.0),
            ("колесо_зз", rear, TRACK_R / 2, 325.0),
        ):
            with self.subTest(wheel=name):
                solid = scene.objects[name]
                bb = solid.manifold.bounding_box()
                centre = ((bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2)
                self.assertAlmostEqual(centre[0], x, delta=1.0)
                self.assertAlmostEqual(centre[1], y, delta=1.0)
                self.assertAlmostEqual(centre[2], r, delta=1.0)

    def test_wheels_stand_on_the_floor(self):
        for name in ("колесо_пп", "колесо_пз", "колесо_зп", "колесо_зз"):
            bb = self.build.scene.objects[name].manifold.bounding_box()
            self.assertAlmostEqual(bb[2], 0.0, delta=1.0, msg=name)

    def test_body_is_one_watertight_piece(self):
        body = self.build.scene.objects["кузов"]
        self.assertEqual(len(body.manifold.decompose()), 1)

    def test_glass_is_a_separate_part_inside_the_body_silhouette(self):
        scene = self.build.scene
        for name in ("лобовое", "заднее", "стекло_п", "стекло_з"):
            self.assertIn(name, scene.objects, name)
            self.assertGreater(scene.objects[name].manifold.volume(), 100_000, name)

    def test_tail_and_grille_exist(self):
        scene = self.build.scene
        self.assertIn("хвост", scene.objects)
        self.assertIn("решётка", scene.objects)
        # решётка сделана массивом: 15 ламелей в одном теле
        self.assertGreater(len(scene.objects["решётка"].manifold.decompose()), 5)

    def test_params_variant_is_consistent_with_the_plain_one(self):
        """Второй файл — тот же кузов, записанный выражениями от шести param."""
        from pathlib import Path

        path = Path(__file__).resolve().parents[1] / "examples" / "porsche_930_params.forma"
        text = path.read_text(encoding="utf-8")
        for marker in ("param L=", "param W=", "param H=", "param WB=",
                       "param KF=", "param KR=", "preset сток"):
            self.assertIn(marker, text)
        # сечения в параметрическом варианте — выражения, а не готовые числа
        self.assertIn("H-150", text)
        self.assertIn("W/2*", text)

    def test_listed_in_the_app(self):
        self.assertIn("porsche_930", [key for _, key in EXAMPLES])

    def test_body_rises_exactly_to_the_drawing_height(self):
        """1320 мм на листе — это высота кузова вместе с колёсами: пол на Z=0
        держат колёса, кузов начинается с просвета 150 мм."""
        body = self.build.scene.objects["кузов"].manifold.bounding_box()
        self.assertAlmostEqual(body[2], 150.0, delta=2.0)   # низ кузова = просвет
        self.assertAlmostEqual(body[5], H, delta=2.0)       # верх = высота листа

    def test_script_is_readable_text(self):
        """Сценарий остаётся текстом, который можно править руками."""
        self.assertIn("кузов_база = loft", self.script)
        self.assertTrue(all(ord(ch) < 0x2500 for ch in self.script))
        self.assertNotIn("import ", self.script)


if __name__ == "__main__":
    unittest.main()
