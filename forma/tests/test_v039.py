"""0.39: новые тела — слиток, параболоид, седло, ступеньки, круг, овал, бусина.

Проверки держат просьбу пользователя:

1. **слиток** — объёмная трапеция: нижняя площадка больше верхней, скос и
   скругление углов, объём сходится с формулой усечённой пирамиды;
2. **параболоид** — чаша или купол; `wall>0` даёт настоящую чашу со стенкой;
3. **гиперболический параболоид** — седло: `mode=гипар` (крыша с прямыми
   рёбрами) и `mode=седло` (чипс), толщина делает плиту, а не лист;
4. **ступеньки** — марш одной деталью: число ступеней, подъём, проступь,
   ширина и независимые наружная/внутренняя кромки;
5. **круг** и **овал** — плоские тела с объёмом, а не плоские фигуры;
6. **сектор круга** — кусок пирога с углом, поворотом и толщиной;
7. **бусина** — шар с каналом под шнур; фаска у входа, точная ширина.
"""

from __future__ import annotations

import math
import unittest

import manifold3d as mf
import numpy as np

import forma.run  # noqa: F401  (наполняет реестр команд)
from forma.ops import OPS, lookup
from forma.run import build


def _build(script: str):
    b = build(script, analyze_model=False)
    assert b.ok, (b.error or {}).get("message")
    return b


def _solid(result, name: str):
    return result.scene.objects[name].manifold


def _size(result, name: str):
    bb = _solid(result, name).bounding_box()
    return np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]], dtype=float)


class MoreBodiesTest(unittest.TestCase):
    """Слиток, параболоид, седло, ступеньки, круг, сектор, овал, бусина."""

    def test_disc_is_a_cylinder_with_volume(self):
        b = _build("к = disc diameter=120 thickness=8")
        self.assertTrue(np.allclose(_size(b, "к"), [120.0, 120.0, 8.0], atol=0.3))
        expect = math.pi * 60 ** 2 * 8
        self.assertAlmostEqual(_solid(b, "к").volume() / expect, 1.0, delta=0.01)
        # кромка скруглена — объём меньше, габарит тот же
        r = _build("к = disc diameter=120 thickness=8 round=3")
        self.assertTrue(np.allclose(_size(r, "к"), [120.0, 120.0, 8.0], atol=0.3))
        self.assertLess(_solid(r, "к").volume(), _solid(b, "к").volume())

    def test_pie_is_a_quarter(self):
        b = _build("с = pie diameter=120 angle=90 thickness=6")
        expect = math.pi * 60 ** 2 * 6 / 4.0
        self.assertAlmostEqual(_solid(b, "с").volume() / expect, 1.0, delta=0.02)
        full = _build("ц = pie diameter=120 angle=360 thickness=6")
        self.assertAlmostEqual(_solid(full, "ц").volume() / (expect * 4), 1.0, delta=0.02)

    def test_pie_start_turns_the_slice(self):
        b0 = _build("с = pie diameter=100 angle=45 thickness=5")
        b90 = _build("с = pie diameter=100 angle=45 start=90 thickness=5")
        bb0 = _solid(b0, "с").bounding_box()
        bb90 = _solid(b90, "с").bounding_box()
        # кусок 0…45° лежит вдоль +X, повёрнутый на 90° — вдоль +Y
        self.assertGreater(bb0[3] - bb0[0], 45.0)
        self.assertLess(bb0[4] - bb0[1], 40.0)
        self.assertLess(bb90[3] - bb90[0], 40.0)
        self.assertGreater(bb90[4] - bb90[1], 45.0)

    def test_oval_plate(self):
        b = _build("о = oval width=200 length=120 thickness=8")
        self.assertTrue(np.allclose(_size(b, "о"), [200.0, 120.0, 8.0], atol=0.5))
        expect = math.pi * 100 * 60 * 8
        self.assertAlmostEqual(_solid(b, "о").volume() / expect, 1.0, delta=0.01)

    def test_bead_has_hole_and_exact_width(self):
        b = _build("б = bead diameter=24 hole=6")
        solid = _solid(b, "б")
        self.assertTrue(np.allclose(_size(b, "б")[:2], [24.0, 24.0], atol=0.05))
        # без отверстия шар весил бы больше
        ball = 4.0 / 3.0 * math.pi * 12 ** 3
        self.assertLess(solid.volume(), ball * 0.97)
        # канал действительно насквозь: сверху и снизу дырка
        cut = mf.Manifold.cylinder(4.0, 2.9, 2.9, 48, center=True).translate((0, 0, 12.0))
        top = mf.Manifold.batch_boolean([solid, cut], mf.OpType.Intersect)
        self.assertLess(top.volume(), 1.0)

    def test_bead_chamfer_and_note(self):
        b = _build("б = bead diameter=24 hole=6 chamfer=1.2")
        note = b.scene.objects["б"].notes[0]
        self.assertIn("фаской", note)
        plain = _build("б = bead diameter=24 hole=6")
        self.assertLess(_solid(b, "б").volume(), _solid(plain, "б").volume())

    def test_bead_refuses_thick_hole(self):
        bad = build("б = bead diameter=10 hole=9", analyze_model=False)
        self.assertFalse(bad.ok)
        self.assertIn("Отверстие", (bad.error or {}).get("message", ""))

    def test_ingot_is_a_truncated_pyramid(self):
        b = _build("и = ingot length=100 width=50 height=22 taper=8")
        self.assertTrue(np.allclose(_size(b, "и"), [100.0, 50.0, 22.0], atol=0.05))
        s1, s2 = 100 * 50, 84 * 34
        expect = 22 / 3.0 * (s1 + s2 + math.sqrt(s1 * s2))
        self.assertAlmostEqual(_solid(b, "и").volume() / expect, 1.0, delta=0.01)
        # верхняя площадка меньше нижней
        top = mf.Manifold.cube((200, 200, 2), center=True).translate((0, 0, 21.0))
        upper = mf.Manifold.batch_boolean([_solid(b, "и"), top], mf.OpType.Intersect)
        self.assertAlmostEqual(upper.volume(), 84 * 34 * 2, delta=200)

    def test_paraboloid_height_and_volume(self):
        b = _build("п = paraboloid diameter=140 height=34")
        self.assertTrue(np.allclose(_size(b, "п"), [140.0, 140.0, 34.0], atol=0.5))
        expect = math.pi * 70 ** 2 * 34 / 2.0
        self.assertAlmostEqual(_solid(b, "п").volume() / expect, 1.0, delta=0.02)

    def test_paraboloid_with_wall_is_a_dish(self):
        solid_state = _build("п = paraboloid diameter=120 height=40")
        dish = _build("ч = paraboloid diameter=120 height=40 wall=3")
        self.assertLess(_solid(dish, "ч").volume(), _solid(solid_state, "п").volume() * 0.2)
        # внутри чаши — пусто: кубик в середине не пересекает стенку
        probe = mf.Manifold.cube((30, 30, 2), center=True).translate((0.0, 0.0, 10.0))
        inner = mf.Manifold.batch_boolean([_solid(dish, "ч"), probe], mf.OpType.Intersect)
        self.assertLess(inner.volume(), 1.0)

    def test_paraboloid_refuses_thick_wall(self):
        bad = build("ч = paraboloid diameter=100 height=20 wall=19", analyze_model=False)
        self.assertFalse(bad.ok)

    def test_saddle_has_two_modes(self):
        roof = _build("с = saddle length=160 width=120 rise=40 thickness=4")
        chips = _build("с = saddle length=120 width=120 rise=30 thickness=3 mode=седло")
        for b, name in ((roof, "с"), (chips, "с")):
            solid = _solid(b, name)
            self.assertEqual(len(solid.decompose()), 1)     # одна деталь, не лист
            self.assertGreater(solid.volume(), 1000.0)
        # у гипара углы попарно вверх/вниз, у чипса — края вверх, середина вниз
        roof_bb = _solid(roof, "с").bounding_box()
        self.assertGreater(roof_bb[5] - roof_bb[2], 40.0)

    def test_saddle_refuses_unknown_mode(self):
        bad = build("с = saddle mode=восьмёрка", analyze_model=False)
        self.assertFalse(bad.ok)

    def test_stairs_geometry_and_shapes(self):
        b = _build("л = stairs steps=6 rise=18 run=28 width=120")
        self.assertTrue(np.allclose(_size(b, "л"), [168.0, 120.0, 108.0], atol=0.05))
        # марш — сплошной блок под ступенями: сумма столбиков 1+2+…+n
        expect = 18 * 28 * 120 * (6 * 7 / 2)
        self.assertAlmostEqual(_solid(b, "л").volume(), expect, delta=1.0)
        for shape in ("прямая", "скруглённая"):
            with self.subTest(shape=shape):
                s = _build(f"л = stairs steps=5 rise=16 run=30 width=100 shape={shape}")
                self.assertTrue(np.allclose(_size(s, "л"), [150.0, 100.0, 80.0], atol=0.6))

    def test_stairs_round_softens_steps(self):
        sharp = _build("л = stairs steps=5 rise=16 run=30 width=100")
        soft = _build("л = stairs steps=5 rise=16 run=30 width=100 shape=скруглённая")
        inner = _build("л = stairs steps=5 rise=16 run=30 width=100 inner=скруглённый")
        self.assertLess(_solid(soft, "л").volume(), _solid(sharp, "л").volume())
        self.assertGreater(_solid(inner, "л").volume(), _solid(sharp, "л").volume())
        self.assertTrue(np.allclose(_size(soft, "л"), [150.0, 100.0, 80.0], atol=0.05))
        rejected = build("л = stairs shape=скошенная", analyze_model=False)
        self.assertFalse(rejected.ok)

    def test_stairs_refuses_bad_shape(self):
        bad = build("л = stairs shape=винтовая", analyze_model=False)
        self.assertFalse(bad.ok)
        self.assertIn("shape", (bad.error or {}).get("message", ""))

    def test_new_bodies_registered_and_explained(self):
        for op in ("ingot", "paraboloid", "saddle", "stairs", "disc", "pie", "oval", "bead"):
            spec = OPS.get(op)
            with self.subTest(op=op):
                self.assertIsNotNone(spec)
                self.assertTrue(spec.summary)
                self.assertTrue(spec.example)
                self.assertGreaterEqual(len(spec.params), 4)

    def test_russian_names_resolve(self):
        for word, op in (("слиток", "ingot"), ("параболоид", "paraboloid"),
                         ("гиперболический_параболоид", "saddle"), ("седло", "saddle"),
                         ("ступеньки", "stairs"), ("лесенка", "stairs"),
                         ("круг", "disc"), ("овал", "oval"), ("бусина", "bead"),
                         ("сектор_круга", "pie")):
            with self.subTest(word=word):
                self.assertEqual(lookup(word).name, op)


class ExamplesAndHelpTest(unittest.TestCase):
    """Новые тела видны в справке, в каталоге и в примерах."""

    def test_help_explains_each_body(self):
        for op in ("ingot", "paraboloid", "saddle", "stairs", "disc", "pie",
                   "oval", "bead"):
            spec = OPS[op]
            with self.subTest(op=op):
                self.assertTrue(spec.summary)
                self.assertTrue(spec.example)
                self.assertEqual(spec.category, "Примитивы")

    def test_example_builds(self):
        from forma.webui import load_example

        for index in range(1, 5):
            with self.subTest(gallery=index):
                b = _build(load_example(f"tools_gallery_{index}"))
                self.assertEqual(len(b.scene.objects), 11)

    def test_example_in_menu(self):
        from forma.webui import EXAMPLES

        keys = [key for _, key in EXAMPLES]
        for index in range(1, 5):
            self.assertIn(f"tools_gallery_{index}", keys)
        self.assertNotIn("more_solids", keys)

    def test_cards_present(self):
        from pathlib import Path

        app = (Path(__file__).resolve().parent.parent / "web/js/app.js").read_text(
            encoding="utf-8")
        block = app.split("const TOOL_SHAPES = [", 1)[1].split("const TOOL_RECIPES", 1)[0]
        for title in ("Круг", "Овал", "Слиток", "Параболоид", "Седло (гипар)",
                      "Сектор круга", "Бусина", "Ступеньки"):
            with self.subTest(title=title):
                self.assertIn(f"title: '{title}'", block)

    def test_instruction_lists_new_bodies(self):
        from forma.instruction import full_instruction

        text = full_instruction()
        for word in ("ingot", "paraboloid", "saddle", "stairs", "disc", "pie",
                     "oval", "bead", "слиток", "ступеньки", "бусина"):
            with self.subTest(word=word):
                self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
