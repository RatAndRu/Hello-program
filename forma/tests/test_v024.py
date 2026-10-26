"""0.24: фигуры-знаки — стрелка, Т, полумесяц, завиток, молния, банан, Y."""

from __future__ import annotations

import math
import unittest

from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError((result.error or {}).get("message", result.error))
    return result


def fails(script: str) -> str:
    result = build(script, analyze_model=False)
    if result.ok:
        raise AssertionError("ожидалась ошибка")
    return (result.error or {}).get("message", "")


def last(result):
    return list(result.scene.objects.values())[-1]


def size(m) -> tuple[float, float, float]:
    bb = m.bounding_box()
    return (bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])


class TestGlyphsAreSolids(unittest.TestCase):
    """Каждая фигура — одно замкнутое тело с положительным объёмом."""

    CASES = {
        "arrow": "стрелка = arrow length=120 width=26 head=42 head_width=68 depth=12",
        "tee": "тавр = tee arm=90 bar=20 stem=22 leg=60 depth=14",
        "crescent": "луна = crescent radius=50 thickness=18 depth=12",
        "swirl": "куча = swirl radius=42 height=70 coils=3",
        "lightning": "молния = lightning height=90 width=44 depth=10",
        "banana": "банан = banana length=120 bend=110 thick=28",
        "yoke": "рогатка = yoke height=110 spread=64 arm=16 depth=14",
    }

    def test_each_is_one_closed_body(self):
        for kind, script in self.CASES.items():
            with self.subTest(kind=kind):
                solid = last(ok(script))
                m = solid.manifold
                self.assertEqual(len(m.decompose()), 1, f"{kind}: должно быть одно тело")
                self.assertEqual(m.genus(), 0, f"{kind}: без дырок")
                self.assertGreater(m.volume(), 1000.0, f"{kind}: объём в мм³")
                self.assertEqual(solid.kind, kind)

    def test_objects_stand_on_floor(self):
        for kind, script in self.CASES.items():
            with self.subTest(kind=kind):
                m = last(ok(script)).manifold
                self.assertAlmostEqual(m.bounding_box()[2], 0.0, places=4,
                                       msg=f"{kind}: низ должен быть на z=0")


class TestExactSizes(unittest.TestCase):
    """Габариты означают то, что написано в параметрах — даже со скруглением."""

    def test_arrow_fits_requested_length_and_head(self):
        m = last(ok("с = arrow length=120 width=26 head=42 head_width=68 depth=12 "
                    "round=2")).manifold
        dx, dy, dz = size(m)
        # с 0.41 знак стоит: длина по X, толщина по Y, высота наконечника по Z
        self.assertAlmostEqual(dx, 120.0, places=3)
        self.assertAlmostEqual(dy, 12.0, places=3)
        self.assertAlmostEqual(dz, 68.0, places=3)

    def test_tee_total_height_is_bar_plus_leg(self):
        m = last(ok("т = tee arm=90 bar=20 stem=22 leg=60 depth=14 round=2")).manifold
        dx, dy, dz = size(m)
        self.assertAlmostEqual(dx, 90.0, places=3)
        self.assertAlmostEqual(dz, 80.0, places=3)

    def test_lightning_keeps_size_with_round(self):
        m = last(ok("м = lightning height=90 width=44 depth=10 round=1.5")).manifold
        dx, _, dz = size(m)
        self.assertAlmostEqual(dx, 44.0, places=3)
        self.assertAlmostEqual(dz, 90.0, places=3)

    def test_yoke_spread_is_outer_width(self):
        m = last(ok("р = yoke height=110 spread=64 arm=16 depth=14 round=2")).manifold
        dx, _, dz = size(m)
        self.assertAlmostEqual(dx, 80.0, places=3)   # spread + толщина ветви
        self.assertAlmostEqual(dz, 110.0, places=3)


class TestCrescent(unittest.TestCase):
    def test_bite_controls_thickness(self):
        thin = last(ok("л = crescent radius=50 thickness=8 bite=1.3 depth=10")).manifold
        thick = last(ok("л = crescent radius=50 thickness=30 bite=1 depth=10")).manifold
        self.assertGreater(thick.volume(), thin.volume() * 3)

    def test_impossible_bite_is_rejected(self):
        # оба круга почти совпали — серп превращается в тонкую полоску или исчезает
        message = fails("л = crescent radius=10 thickness=19.4 bite=0.6")
        self.assertTrue("bite" in message or "выкус" in message.lower()
                        or "влезает" in message.lower(), message)

    def test_thickness_bigger_than_disc_is_rejected(self):
        message = fails("л = crescent radius=10 thickness=18")
        self.assertTrue("толщин" in message.lower() or "влезает" in message.lower(), message)


class TestLightningShape(unittest.TestCase):
    def test_has_two_sharp_tips(self):
        """Молния — не прямоугольник: площадь заметно меньше габарита."""
        m = last(ok("м = lightning height=90 width=44 depth=10")).manifold
        dx, _, dz = size(m)
        self.assertLess(m.volume() / (dx * dz * 10.0), 0.45)
        self.assertGreater(m.volume() / (dx * dz * 10.0), 0.15)

    def test_size_validation(self):
        self.assertIn("height", fails("м = lightning height=1 width=44"))


class TestSwirl(unittest.TestCase):
    def test_coils_change_silhouette(self):
        one = last(ok("к = swirl radius=40 height=60 coils=1 groove=0")).manifold
        four = last(ok("к = swirl radius=40 height=60 coils=4 groove=0")).manifold
        self.assertGreater(four.num_tri(), one.num_tri())

    def test_groove_is_carved(self):
        smooth = last(ok("к = swirl radius=40 height=70 coils=3 groove=0")).manifold
        carved = last(ok("к = swirl radius=40 height=70 coils=3 groove=4")).manifold
        self.assertLess(carved.volume(), smooth.volume(), "канавка должна снимать материал")

    def test_too_deep_groove_is_rejected(self):
        self.assertIn("радиус", fails("к = swirl radius=10 height=50 groove=8"))


class TestBanana(unittest.TestCase):
    def test_bend_makes_arc(self):
        straight = last(ok("б = banana length=100 bend=0 thick=20 flat=1")).manifold
        bent = last(ok("б = banana length=100 bend=140 thick=20 flat=1")).manifold
        self.assertAlmostEqual(size(straight)[0], 100.0, places=2, msg="длина по дуге")
        self.assertLess(size(straight)[2], 21.0, "прямая почти лежит")
        self.assertGreater(size(bent)[2], 30.0, "дуга поднимается над полом")

    def test_ends_are_tapered(self):
        m = last(ok("б = banana length=120 bend=110 thick=28 taper=0.15")).manifold
        self.assertGreater(m.num_tri(), 1000)


class TestStand(unittest.TestCase):
    def test_stand_turns_sign_upright(self):
        # с 0.41 знаки по умолчанию стоят; plane=плашмя кладёт их на пол
        up = last(ok("с = arrow length=120 width=26 head=42 head_width=68 depth=12")).manifold
        flat = last(ok("с = arrow length=120 width=26 head=42 head_width=68 depth=12 "
                       "plane=плашмя")).manifold
        self.assertLess(size(flat)[2], 15.0)
        self.assertAlmostEqual(size(up)[2], 68.0, places=3)
        self.assertAlmostEqual(size(up)[0], 120.0, places=3)
        self.assertAlmostEqual(up.bounding_box()[2], 0.0, places=4)
        # старое «stand=нет» тоже кладёт знак
        old_style = last(ok("с = arrow length=120 width=26 head=42 head_width=68 depth=12 "
                            "stand=нет")).manifold
        self.assertLess(size(old_style)[2], 15.0)


class TestValidation(unittest.TestCase):
    def test_arrow_head_wider_than_shaft(self):
        message = fails("с = arrow length=100 width=30 head=30 head_width=20")
        self.assertIn("наконечник", message.lower())

    def test_tee_stem_not_narrower(self):
        self.assertIn("ножк", fails("т = tee arm=60 stem=80").lower())

    def test_yoke_too_narrow(self):
        self.assertTrue("spread" in fails("р = yoke height=100 spread=10 arm=16"))

    def test_banana_negative_bend(self):
        self.assertIn("bend", fails("б = banana length=100 bend=-10"))


class TestHelpAndAliases(unittest.TestCase):
    def test_help_lists_new_shapes(self):
        from forma.ops import OPS
        for name in ("arrow", "tee", "crescent", "swirl", "lightning", "banana", "yoke"):
            with self.subTest(name=name):
                spec = OPS.get(name)
                self.assertIsNotNone(spec)
                self.assertEqual(spec.category, "Примитивы")
                self.assertTrue(spec.summary)
                self.assertTrue(spec.params)
                self.assertTrue(spec.example)

    def test_russian_aliases(self):
        from forma.ops import lookup
        for alias, name in (("стрелка", "arrow"), ("полумесяц", "crescent"),
                            ("молния", "lightning"), ("рогатка", "yoke"),
                            ("завиток", "swirl"), ("банан", "banana")):
            with self.subTest(alias=alias):
                found = lookup(alias)
                self.assertIsNotNone(found, alias)
                self.assertEqual(found.name, name)

    def test_examples_from_help_build(self):
        from forma.ops import OPS
        for name in ("arrow", "tee", "crescent", "swirl", "lightning", "banana", "yoke"):
            with self.subTest(name=name):
                for line in OPS[name].example.splitlines():
                    if line.strip():
                        ok(line)


if __name__ == "__main__":
    unittest.main()
