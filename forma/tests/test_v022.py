"""0.22: настоящее яйцо, капля, наполнение, горка, массив по кругу."""

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


def radius_at(manifold, z: float) -> float:
    """Радиус тела на высоте z — по первому попаданию луча снаружи."""
    bb = manifold.bounding_box()
    away = (bb[3] - bb[0]) * 2 + 50
    hits = manifold.ray_cast([away, 0.0, z], [-away, 0.0, z])
    return abs(float(hits[0].position[0])) if hits else 0.0


class TestEgg(unittest.TestCase):
    def test_real_egg_proportions(self):
        b = ok("я = egg height=60 diameter=42 proportion=0.55")
        egg = last(b).manifold
        bb = egg.bounding_box()
        height = bb[5] - bb[2]
        width = bb[3] - bb[0]
        self.assertAlmostEqual(height, 60.0, delta=0.6)
        self.assertAlmostEqual(width, 42.0, delta=0.6)
        ratio = height / width
        self.assertTrue(1.3 <= ratio <= 1.5, ratio)
        # широкая точка ниже середины: низ тупой, верх острый
        low = radius_at(egg, 60 * 0.30)
        high = radius_at(egg, 60 * 0.80)
        self.assertGreater(low, high * 1.2, (low, high))
        self.assertLess(radius_at(egg, 60 * 0.93), 21 * 0.42)
        # самая широкая точка — около 45 % высоты
        widest = max(range(5, 96, 2), key=lambda p: radius_at(egg, 60 * p / 100))
        self.assertTrue(35 <= widest <= 52, widest)

    def test_profile_is_smooth(self):
        egg = last(ok("я = egg height=60 diameter=42 proportion=0.55")).manifold
        samples = [radius_at(egg, 60 * p / 100) for p in range(50, 100, 5)]
        for a, b in zip(samples, samples[1:]):
            self.assertGreaterEqual(a + 0.4, b)      # монотонно сужается, без шипа

    def test_sharp_bottom_flips_the_egg(self):
        up = last(ok("я = egg height=60 diameter=42 proportion=0.6")).manifold
        down = last(ok("я = egg height=60 diameter=42 proportion=0.6 sharp=низ")).manifold
        self.assertGreater(radius_at(up, 15), radius_at(up, 45))
        self.assertLess(radius_at(down, 15), radius_at(down, 45))

    def test_too_wide_is_rejected(self):
        message = fails("я = egg height=40 diameter=44")
        self.assertIn("шире", message)

    def test_symmetric_ovoid(self):
        a = radius_at(last(ok("я = egg height=60 diameter=42 proportion=0")).manifold, 15)
        b = radius_at(last(ok("я = egg height=60 diameter=42 proportion=0")).manifold, 45)
        self.assertAlmostEqual(a, b, delta=1.2)


class TestDrop(unittest.TestCase):
    def test_shape(self):
        d = last(ok("к = drop radius=14 height=40 tip=0.5")).manifold
        bb = d.bounding_box()
        self.assertAlmostEqual(bb[5] - bb[2], 40.0, delta=0.5)
        self.assertAlmostEqual(bb[3] - bb[0], 28.0, delta=0.6)
        self.assertGreater(radius_at(d, 14), radius_at(d, 34) * 2.0)

    def test_tip_changes_the_tail(self):
        blunt = last(ok("к = drop radius=12 height=44 tip=0")).manifold
        sharp = last(ok("к = drop radius=12 height=44 tip=1")).manifold
        self.assertGreater(radius_at(blunt, 34), radius_at(sharp, 34) * 1.3)

    def test_too_short_is_rejected(self):
        self.assertIn("мала", fails("к = drop radius=20 height=22"))


class TestFill(unittest.TestCase):
    PLAIN = "пос = plate diameter=170 depth=50 wall=4\n"
    FILL = "каша = fill [пос] grain=зерно size=7 level=0.7 seed=4"

    def test_grains_fill_the_bowl(self):
        b = ok(self.PLAIN + self.FILL)
        bowl = b.scene.objects["пос"].manifold
        fill = b.scene.objects["каша"].manifold
        bowl_bb, fill_bb = bowl.bounding_box(), fill.bounding_box()
        self.assertGreater(fill.volume(), bowl.volume() * 0.2)
        self.assertLess(fill.volume(), bowl.volume())
        self.assertGreater(fill_bb[2], bowl_bb[2] + 1.0)          # лежит на дне
        self.assertLess(fill_bb[2], bowl_bb[5] * 0.4)
        self.assertLess(fill_bb[5], bowl_bb[5] - 2.0)             # ниже борта
        self.assertLessEqual(fill_bb[3], bowl_bb[3] + 0.5)        # не вылезает за края

    def test_level_controls_height(self):
        low = last(ok(self.PLAIN + "к = fill [пос] grain=зерно size=7 level=0.35")).manifold
        high = last(ok(self.PLAIN + "к = fill [пос] grain=зерно size=7 level=0.85")).manifold
        self.assertGreater(high.bounding_box()[5], low.bounding_box()[5] + 8.0)
        self.assertGreater(high.volume(), low.volume())

    def test_seed_is_repeatable(self):
        a = last(ok(self.PLAIN + self.FILL)).manifold
        b = last(ok(self.PLAIN + self.FILL)).manifold
        c = last(ok(self.PLAIN + self.FILL.replace("seed=4", "seed=5"))).manifold
        self.assertAlmostEqual(a.volume(), b.volume(), places=3)
        self.assertNotAlmostEqual(a.volume(), c.volume(), places=3)

    def test_solid_object_has_no_cavity(self):
        message = fails("ш = sphere radius=40\nк = fill [ш] grain=шар size=6")
        self.assertIn("полост", message)

    def test_dome_heaps_the_middle(self):
        flat = last(ok(self.PLAIN + "к = fill [пос] grain=зерно size=8 level=0.6")).manifold
        dome = last(ok(self.PLAIN + "к = fill [пос] grain=зерно size=8 level=0.6 dome=0.9")).manifold
        self.assertGreater(dome.bounding_box()[5], flat.bounding_box()[5] + 5.0)
        self.assertGreater(dome.volume(), flat.volume())

    def test_separate_objects(self):
        b = ok("п = plate diameter=140 depth=45 wall=4\n"
               "к = fill [п] grain=горох size=14 level=0.45 count=18 as=отдельные")
        names = [n for n in b.scene.objects if n.startswith("к_")]
        self.assertGreater(len(names), 3)
        for n in names:
            self.assertGreater(b.scene.objects[n].manifold.volume(), 0.0)

    def test_custom_grain_shapes(self):
        for grain in ("шар", "горох", "куб", "галька", "капля", "зерно"):
            b = ok(self.PLAIN + f"к = fill [пос] grain={grain} size=8 level=0.5")
            self.assertGreater(last(b).manifold.volume(), 1000.0, grain)


class TestPile(unittest.TestCase):
    def test_mound_stands_on_the_floor(self):
        p = last(ok("г = pile radius=100 height=45 grain=галька size=14 seed=5")).manifold
        bb = p.bounding_box()
        self.assertAlmostEqual(bb[2], 0.0, delta=1.0)
        self.assertGreater(bb[5], 30.0)
        self.assertLessEqual(bb[5], 55.0)
        self.assertLessEqual(bb[3], 110.0)
        self.assertGreater(p.volume(), 30000.0)

    def test_seed_controls_layout(self):
        a = last(ok("г = pile radius=80 height=40 grain=шар size=12 seed=1")).manifold
        b = last(ok("г = pile radius=80 height=40 grain=шар size=12 seed=1")).manifold
        c = last(ok("г = pile radius=80 height=40 grain=шар size=12 seed=9")).manifold
        self.assertAlmostEqual(a.volume(), b.volume(), places=3)
        self.assertNotAlmostEqual(a.volume(), c.volume(), places=3)

    def test_pile_from_a_real_object(self):
        b = ok("к = drop radius=12 height=30\nг = pile [к] radius=90 height=40 size=16 seed=2")
        names = list(b.scene.objects)
        self.assertEqual(names, ["к", "г"])     # исходник остаётся, но погашен
        self.assertFalse(b.scene.objects["к"].visible)
        self.assertGreater(last(b).manifold.volume(), 20000.0)

    def test_optional_base_disc(self):
        plain = last(ok("г = pile radius=90 height=40 grain=галька size=14 seed=5")).manifold
        based = last(ok("г = pile radius=90 height=40 grain=галька size=14 seed=5 base=8")).manifold
        self.assertLess(based.bounding_box()[2], -7.0)
        self.assertGreater(based.volume(), plain.volume() + 200000.0)

    def test_too_big_grain(self):
        self.assertIn("зерно крупнее", fails("г = pile radius=10 height=4 grain=шар size=40"))


class TestRadialArray(unittest.TestCase):
    def test_full_circle(self):
        b = ok("ст = cylinder radius=5 height=40\nк = array [ст] count=6 mode=radial radius=60")
        ring = last(b).manifold
        bb = ring.bounding_box()
        self.assertAlmostEqual(bb[3], 65.0, delta=1.0)
        self.assertAlmostEqual(-bb[0], 65.0, delta=1.0)
        self.assertAlmostEqual(bb[4], 60.0 * math.sin(math.pi / 3) + 5.0, delta=1.0)
        self.assertAlmostEqual(-bb[1], 60.0 * math.sin(math.pi / 3) + 5.0, delta=1.0)

    def test_sector_does_not_close_the_circle(self):
        b = ok("д = box size=[20,10,8]\nс = array [д] count=3 mode=radial "
               "radius=60 angle=180 spin=no")
        bb = last(b).manifold.bounding_box()
        self.assertAlmostEqual(bb[4], 65.0, delta=1.0)     # копия на 90°
        self.assertAlmostEqual(bb[3], 70.0, delta=1.0)     # копия на 0° смотрит вбок

    def test_spin_turns_each_copy(self):
        plain = last(ok("д = box size=[30,10,8]\nс = array [д] count=4 mode=radial "
                        "radius=50 angle=90 spin=no")).manifold
        spun = last(ok("д = box size=[30,10,8]\nс = array [д] count=4 mode=radial "
                       "radius=50 angle=90 spin=да")).manifold
        self.assertNotAlmostEqual(plain.bounding_box()[4], spun.bounding_box()[4], delta=1.0)

    def test_radius_zero_keeps_the_old_behaviour(self):
        b = ok("д = box size=[30,10,8] at=[30,0,0]\nс = array [д] count=4 mode=radial")
        bb = last(b).manifold.bounding_box()
        self.assertAlmostEqual(bb[3], 45.0, delta=1.0)
        self.assertAlmostEqual(-bb[0], 45.0, delta=1.0)


class TestUvByMaterial(unittest.TestCase):
    def test_small_pattern_materials_get_the_atlas(self):
        from forma.textures import preferred_uv
        for kind in ("metal", "fabric", "leather", "checker", "noise"):
            self.assertEqual(preferred_uv(kind, ""), "atlas", kind)
        for kind in ("wood", "marble", "brick", "ceramic"):
            self.assertEqual(preferred_uv(kind, ""), "auto", kind)
        self.assertEqual(preferred_uv("", "dots"), "atlas")
        self.assertEqual(preferred_uv("", "stone"), "auto")

    def test_explicit_uv_wins(self):
        b = ok("к = cylinder radius=20 height=40\n"
               "texture к kind=metal pattern=dots uv=auto")
        self.assertEqual(b.scene.objects["к"].uv, "auto")
        b = ok("к = cylinder radius=20 height=40\n"
               "texture к kind=metal pattern=dots")
        self.assertEqual(b.scene.objects["к"].uv, "atlas")


class TestHelpAndUi(unittest.TestCase):
    def test_new_commands_in_help(self):
        import forma.run  # noqa: F401
        from forma.ops import OPS
        for name in ("egg", "drop", "fill", "pile"):
            self.assertIn(name, OPS)
        self.assertIn("капля", OPS["drop"].aliases)
        self.assertIn("куча", OPS["pile"].aliases)

    def test_ui_knows_the_new_tools(self):
        from pathlib import Path
        app = (Path(__file__).resolve().parents[1] / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("op: 'drop'", app)
        self.assertIn("const TOOL_RECIPES", app)
        for title in ("Наполнение", "Горка", "Массив по кругу"):
            self.assertIn(title, app)


if __name__ == "__main__":
    unittest.main()
