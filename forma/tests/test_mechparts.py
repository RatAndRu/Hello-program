"""Механические примитивы: подшипники, рейки, шестерни, крепёж, тара.

Проверяем числа, а не «похоже ли»: габарит, объём, число тел в детали и то,
что параметры действительно меняют геометрию. Отдельно проверяем реестр:
новые команды обязаны попасть в категорию «Примитивы» вместе с памяткой
исходной ориентации — иначе тест test_v041 упадёт на полноте реестра.
"""
from __future__ import annotations

import unittest

from forma.ops import OPS, lookup

from forma.run import build

MODULE_OPS = ("bearing", "din_rail", "crate", "lug", "corner_bracket", "buckle",
              "rack", "gear_internal", "gear_helical", "gear_bevel",
              "screw_head", "wing_nut", "special_nut")


def make(script: str):
    return build(script)


def size(b) -> list[float]:
    return [round(v, 1) for v in b.analysis["metrics"]["size"]]


def volume(b) -> float:
    return b.analysis["metrics"]["volume_cm3"]


def parts(b) -> int:
    return len(b.visible_solids()[0].manifold.decompose())


class RegistryTest(unittest.TestCase):
    def test_new_ops_are_primitives(self):
        for name in MODULE_OPS:
            spec = OPS.get(name)
            self.assertIsNotNone(spec, name)
            self.assertEqual(spec.category, "Примитивы", name)
            self.assertTrue(spec.summary and spec.example and spec.params, name)

    def test_russian_aliases_resolve(self):
        pairs = {
            "подшипник": "bearing",
            "монтажная_рейка": "din_rail",
            "дощатый_ящик": "crate",
            "проушина": "lug",
            "угловой_кронштейн": "corner_bracket",
            "фастекс": "buckle",
            "зубчатая_рейка": "rack",
            "внутренняя_шестерня": "gear_internal",
            "косозубая_шестерня": "gear_helical",
            "коническая_шестерня": "gear_bevel",
            "головка_винта": "screw_head",
            "барашек": "wing_nut",
            "гайка_nyloc": "special_nut",
        }
        for alias, expected in pairs.items():
            spec = lookup(alias)
            self.assertIsNotNone(spec, alias)
            self.assertEqual(spec.name, expected, alias)

    def test_orientation_notes_merged(self):
        from forma.orient_notes import PRIMITIVE_ORIENTATIONS
        for name in MODULE_OPS:
            self.assertIn(name, PRIMITIVE_ORIENTATIONS, name)
            self.assertTrue(PRIMITIVE_ORIENTATIONS[name].strip(), name)

    def test_alias_does_not_steal_old_command(self):
        # «ящик» исторически принадлежит box_body; тара живёт под своим именем.
        self.assertEqual(lookup("ящик").name, "box_body")
        self.assertEqual(lookup("crate").name, "crate")


class BearingTest(unittest.TestCase):
    def test_ball_bearing_sizes(self):
        b = make("b = bearing d=15 D=35 B=11")
        self.assertTrue(b.ok, b.error)
        self.assertEqual(size(b), [35.0, 35.0, 11.0])
        self.assertEqual(parts(b), 1)
        self.assertGreater(volume(b), 3.0)

    def test_all_kinds_build_single_body(self):
        scripts = {
            "шариковый": "d=15 D=35 B=11",
            "роликовый": "d=25 D=52 B=15 type=роликовый",
            "игольчатый": "d=20 D=26 B=16 type=игольчатый",
            "конический": "d=25 D=47 B=15 type=конический",
            "упорный": "d=30 D=47 B=11 type=упорный",
            "сферический": "d=30 D=62 B=20 type=сферический",
        }
        for name, args in scripts.items():
            b = make(f"b = bearing {args}")
            self.assertTrue(b.ok, f"{name}: {b.error}")
            self.assertEqual(parts(b), 1, name)

    def test_type_changes_geometry(self):
        ball = make("b = bearing d=25 D=52 B=15").analysis["metrics"]["volume_cm3"]
        roller = make("b = bearing d=25 D=52 B=15 type=роликовый") \
            .analysis["metrics"]["volume_cm3"]
        self.assertGreater(abs(roller - ball), 1.0)

    def test_thrust_is_two_washers(self):
        b = make("b = bearing d=30 D=47 B=11 type=упорный")
        self.assertEqual(size(b), [47.0, 47.0, 11.0])
        self.assertEqual(parts(b), 1)
        radial = make("b = bearing d=30 D=47 B=11")
        # у упорного два плоских кольца, у радиального ещё и сепаратор с телами
        self.assertGreater(volume(b), volume(radial) * 0.5)

    def test_shield_adds_material(self):
        open_b = make("b = bearing d=8 D=22 B=7").analysis["metrics"]["volume_cm3"]
        shut = make("b = bearing d=8 D=22 B=7 shield=да").analysis["metrics"]["volume_cm3"]
        self.assertGreater(shut, open_b)

    def test_bad_rings_rejected(self):
        b = make("b = bearing d=30 D=20")
        self.assertFalse(b.ok)
        self.assertIn("допустимо", b.error["message"])

    def test_unknown_type_has_hint(self):
        b = make("b = bearing type=космический")
        self.assertFalse(b.ok)
        self.assertIn("Есть:", b.error.get("hint", ""))


class DinRailTest(unittest.TestCase):
    def test_ts35_profile(self):
        b = make("r = din_rail length=500")
        self.assertTrue(b.ok, b.error)
        self.assertEqual(size(b), [500.0, 35.0, 7.5])
        self.assertEqual(parts(b), 1)

    def test_ts15_profile(self):
        b = make("r = din_rail length=300 size=15 thickness=0.8")
        self.assertEqual(size(b), [300.0, 15.0, 5.0])

    def test_slots_cut_material(self):
        solid = make("r = din_rail length=500 slots=нет").analysis["metrics"]["volume_cm3"]
        holed = make("r = din_rail length=500").analysis["metrics"]["volume_cm3"]
        self.assertLess(holed, solid)
        # просечки через 25 мм: на 500 мм их 20
        self.assertAlmostEqual((solid - holed) / 1.0, 20 * 15 * 6.5 / 1000,
                               delta=2.5)


class CrateTest(unittest.TestCase):
    def test_default_crate_is_drawing_size(self):
        b = make("c = crate length=880 width=600 height=790")
        self.assertTrue(b.ok, b.error)
        self.assertEqual(size(b), [880.0, 600.0, 790.0])
        self.assertEqual(parts(b), 1)

    def test_lid_and_skids_grow_height(self):
        plain = make("c = crate length=600 width=400 height=300")
        packed = make("c = crate length=600 width=400 height=300 lid=да skids=60")
        self.assertEqual(size(plain)[2], 300.0)
        self.assertGreater(size(packed)[2], 300.0)
        self.assertLess(volume(plain), volume(packed))

    def test_too_small_for_posts(self):
        b = make("c = crate length=200 width=200 post=90")
        self.assertFalse(b.ok)
        self.assertIn("стоек", b.error["message"].lower())


class LugTest(unittest.TestCase):
    def test_bent_lug(self):
        b = make("l = lug inner=32 outer=64 length=90 thickness=4 bend=30")
        self.assertTrue(b.ok, b.error)
        self.assertEqual(size(b), [64.0, 122.0, 30.0])
        self.assertEqual(parts(b), 1)

    def test_flat_lug_with_plate_holes(self):
        b = make("l = lug inner=20 outer=44 length=70 thickness=5 bend=0 plate_holes=4")
        self.assertEqual(size(b)[2], 5.0)
        self.assertLess(volume(b), volume(
            make("l = lug inner=20 outer=44 length=70 thickness=5 bend=0")))

    def test_wide_plate_rejected(self):
        b = make("l = lug inner=10 outer=40 width=60")
        self.assertFalse(b.ok)
        self.assertIn("головк", b.error["message"].lower())


class CornerBracketTest(unittest.TestCase):
    def test_bracket_with_gusset(self):
        b = make("k = corner_bracket size=[80,80] width=60 thickness=5 gusset=5")
        self.assertTrue(b.ok, b.error)
        self.assertEqual(size(b), [80.0, 60.0, 80.0])
        self.assertEqual(parts(b), 1)

    def test_gusset_adds_material(self):
        thin = make("k = corner_bracket size=[80,80] width=60 thickness=5 gusset=0")
        thick = make("k = corner_bracket size=[80,80] width=60 thickness=5 gusset=8")
        self.assertGreater(volume(thick), volume(thin))


class BuckleTest(unittest.TestCase):
    def test_two_halves(self):
        b = make("f = buckle width=25 length=60")
        self.assertTrue(b.ok, b.error)
        self.assertEqual(parts(b), 2)
        self.assertEqual(size(b)[2], 7.0)

    def test_too_short_for_prongs(self):
        b = make("f = buckle width=40 length=45")
        self.assertFalse(b.ok)
        self.assertIn("усики", b.error["message"])


class GearSetTest(unittest.TestCase):
    def test_rack_matches_module(self):
        b = make("z = rack length=300 module=2 width=20 height=18")
        self.assertTrue(b.ok, b.error)
        self.assertAlmostEqual(size(b)[0], 300.0, delta=0.1)
        self.assertAlmostEqual(size(b)[2], 18.0, delta=0.1)
        # шаг зуба π·m: на 300 мм при m=2 получается 47 зубьев
        self.assertEqual(parts(b), 1)

    def test_rack_holes_cut_material(self):
        solid = make("z = rack length=300 module=2 width=20 height=18")
        drilled = make("z = rack length=300 module=2 width=20 height=18 holes=3")
        self.assertLess(volume(drilled), volume(solid))

    def test_internal_gear_ring(self):
        b = make("g = gear_internal teeth=40 module=2 thickness=10 rim=6")
        self.assertTrue(b.ok, b.error)
        self.assertAlmostEqual(size(b)[0], 96.0, delta=0.2)
        self.assertEqual(parts(b), 1)
        # сквозное отверстие венца: внутренний контур не сплошной
        self.assertLess(volume(b), 3.5 * 3.5 * 3.14 * 1.0 * 10)

    def test_helical_gear_twists(self):
        straight = make("g = gear_helical teeth=24 module=2 thickness=12 angle=0")
        twisted = make("g = gear_helical teeth=24 module=2 thickness=12 angle=25")
        self.assertTrue(twisted.ok, twisted.error)
        self.assertEqual(size(straight)[:2], size(twisted)[:2])
        self.assertAlmostEqual(volume(straight), volume(twisted), delta=0.4)

    def test_bevel_gear_tapers(self):
        b = make("g = gear_bevel teeth=20 module=2 thickness=12 taper=0.6")
        self.assertTrue(b.ok, b.error)
        self.assertEqual(size(b)[2], 12.0)
        self.assertLess(size(b)[0], 44.0)
        self.assertEqual(parts(b), 1)

    def test_bevel_taper_changes_material(self):
        wide = make("g = gear_bevel teeth=20 module=2 thickness=12 taper=0.85")
        narrow = make("g = gear_bevel teeth=20 module=2 thickness=12 taper=0.35")
        self.assertGreater(volume(wide), volume(narrow) * 1.3)


class ScrewHeadTest(unittest.TestCase):
    HEADS = ("потай", "полукруг", "цилиндр", "шестигранник", "фланец",
             "шайба", "шестилопастная")
    DRIVES = ("крест", "шлиц", "звезда", "шестигранник", "torx_plus",
              "комбинированный", "нет")

    def test_every_head_builds(self):
        for head in self.HEADS:
            b = make(f"h = screw_head d=6 head={head} drive=крест")
            self.assertTrue(b.ok, f"{head}: {b.error}")
            self.assertEqual(parts(b), 1, head)
            self.assertGreater(volume(b), 0.01, head)

    def test_every_drive_builds(self):
        for drive in self.DRIVES:
            b = make(f"h = screw_head d=6 head=цилиндр drive={drive}")
            self.assertTrue(b.ok, f"{drive}: {b.error}")
            self.assertEqual(parts(b), 1, drive)

    def test_drive_removes_material(self):
        plain = make("h = screw_head d=6 head=цилиндр drive=нет")
        socket = make("h = screw_head d=6 head=цилиндр drive=шестигранник")
        self.assertLess(volume(socket), volume(plain))

    def test_countersunk_is_flat_and_wide(self):
        b = make("h = screw_head d=4 head=потай drive=крест")
        self.assertAlmostEqual(size(b)[0], 8.4, delta=0.2)
        self.assertLess(size(b)[2], 3.0)

    def test_unknown_head_message(self):
        b = make("h = screw_head head=круглая")
        self.assertFalse(b.ok)
        self.assertIn("Есть:", b.error.get("hint", ""))


class WingNutTest(unittest.TestCase):
    def test_wing_span(self):
        b = make("w = wing_nut d=8")
        self.assertTrue(b.ok, b.error)
        self.assertEqual(size(b)[0], 52.0)
        self.assertEqual(size(b)[2], 18.0)
        self.assertEqual(parts(b), 1)

    def test_thread_carved(self):
        cut = make("w = wing_nut d=8 thread=нет")
        threaded = make("w = wing_nut d=8")
        self.assertGreater(volume(cut), volume(threaded))


class SpecialNutTest(unittest.TestCase):
    KINDS = ("колпачковая", "фланец", "nyloc", "квадратная", "t", "закладная")

    def test_every_kind_builds(self):
        for kind in self.KINDS:
            b = make(f"n = special_nut d=8 type={kind}")
            self.assertTrue(b.ok, f"{kind}: {b.error}")
            self.assertEqual(parts(b), 1, kind)
            self.assertGreater(volume(b), 0.1, kind)

    def test_kinds_differ(self):
        sizes = {kind: size(make(f"n = special_nut d=8 type={kind}"))
                 for kind in self.KINDS}
        self.assertNotEqual(sizes["колпачковая"], sizes["квадратная"])
        self.assertNotEqual(sizes["t"], sizes["закладная"])

    def test_cap_is_taller_than_flat_nut(self):
        cap = make("n = special_nut d=8 type=колпачковая")
        plain = make("n = special_nut d=8 type=квадратная")
        self.assertGreater(size(cap)[2], size(plain)[2])


if __name__ == "__main__":
    unittest.main()
