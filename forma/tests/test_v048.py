"""0.48: полости, глазное яблоко, Shrinkwrap, паутина и новая чешуя."""

from __future__ import annotations

import math
import unittest

import numpy as np

from forma.geometry import manifold_mesh
from forma.ops_surface import _scale_tile
from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    return result


def fails(script: str) -> str:
    result = build(script, analyze_model=False)
    if result.ok:
        raise AssertionError("ожидалась ошибка")
    return (result.error or {}).get("message", "")


def last(result):
    return list(result.scene.objects.values())[-1]


def parts(manifold) -> int:
    return len([p for p in manifold.decompose() if p.volume() > 1e-7])


def vertical_hits(manifold, x=0.0, y=0.0):
    return manifold.ray_cast([x, y, 10000.0], [x, y, -10000.0])


class TestCavitiesAndProfiles048(unittest.TestCase):
    def test_half_oval_has_real_open_cavity_and_bottom(self):
        solid = last(ok("полуовал width=160 height=90 thickness=24 plane=плашмя"))
        hollow = last(ok("полуовал width=160 height=90 thickness=24 wall=3 "
                         "cavity_depth=19 plane=плашмя"))
        self.assertEqual(parts(hollow.manifold), 1)
        self.assertLess(hollow.manifold.volume(), solid.manifold.volume() * 0.75)
        hits = vertical_hits(hollow.manifold)
        self.assertEqual(len(hits), 2)
        self.assertAlmostEqual(hits[0].position[2], 5.0, delta=0.08)  # 24 − 19
        self.assertAlmostEqual(hits[1].position[2], 0.0, delta=0.08)
        self.assertEqual(hollow.meta["cavity_depth"], 19.0)

    def test_pie_cavity_is_offset_not_scaled_decoration(self):
        hollow = last(ok("pie diameter=140 angle=180 thickness=24 wall=3 cavity_depth=18"))
        self.assertEqual(parts(hollow.manifold), 1)
        hits = vertical_hits(hollow.manifold)
        self.assertEqual(len(hits), 2)
        self.assertAlmostEqual(hits[0].position[2], 6.0, delta=0.08)
        self.assertIn("wall", hollow.meta)
        self.assertIn("wall", fails("pie diameter=40 angle=180 thickness=5 wall=4 cavity_depth=4"))

    def test_grommet_concave_transition_replaces_straight_shoulder(self):
        straight = last(ok("grommet diameter=12 height=10 wall=1.6 flange=4"))
        curved = last(ok("grommet diameter=12 height=10 wall=1.6 flange=4 "
                         "transition=вогнутая transition_h=5"))
        self.assertEqual(parts(curved.manifold), 1)
        self.assertLess(curved.manifold.volume(), straight.manifold.volume() * 0.8)
        self.assertEqual(curved.manifold.bounding_box(), straight.manifold.bounding_box())
        self.assertEqual(curved.meta["transition"], "вогнутая")
        self.assertGreater(curved.manifold.num_tri(), straight.manifold.num_tri())

    def test_stairs_turn_each_tread_without_detaching(self):
        straight = last(ok("stairs steps=7 rise=18 run=28 width=120"))
        turned = last(ok("stairs steps=7 rise=18 run=28 width=120 turn=30"))
        self.assertEqual(parts(turned.manifold), 1)
        self.assertEqual(turned.meta["turn"], 30.0)
        self.assertAlmostEqual(turned.manifold.bounding_box()[5],
                               straight.manifold.bounding_box()[5], delta=1e-6)
        turned_span = turned.manifold.bounding_box()[3] - turned.manifold.bounding_box()[0]
        straight_span = straight.manifold.bounding_box()[3] - straight.manifold.bounding_box()[0]
        self.assertGreater(turned_span, straight_span + 50.0)
        self.assertNotAlmostEqual(turned.manifold.volume(), straight.manifold.volume(), places=3)
        self.assertIn("разъединил", fails("stairs steps=5 rise=18 run=40 width=5 turn=45"))


class TestEyeballAndWeb048(unittest.TestCase):
    def test_eyeball_four_watertight_optical_parts(self):
        result = ok("глаз = eyeball diameter=24 iris=11 pupil=4.6")
        self.assertEqual(len(result.scene.objects), 4)
        names = ["глаз", "глаз_радужка", "глаз_зрачок", "глаз_роговица"]
        for name in names:
            obj = result.scene.objects[name]
            self.assertEqual(obj.manifold.status(), obj.manifold.status().NoError)
            self.assertEqual(parts(obj.manifold), 1)
            self.assertGreater(obj.manifold.volume(), 0.0)
        sclera, iris, pupil, cornea = [result.scene.objects[n] for n in names]
        self.assertEqual(cornea.transmission, 1.0)
        self.assertLess(cornea.manifold.bounding_box()[1], pupil.manifold.bounding_box()[1])
        self.assertLess(pupil.manifold.bounding_box()[1], iris.manifold.bounding_box()[1])
        self.assertLess(iris.manifold.bounding_box()[1], sclera.manifold.bounding_box()[1])
        self.assertLess((cornea.manifold ^ pupil.manifold).volume(), 1e-5)
        self.assertLess((cornea.manifold ^ iris.manifold).volume(), 1e-5)
        self.assertGreater((iris.manifold ^ sclera.manifold).volume(), 0.0)  # нет щели

    def test_open_web_has_capsule_volume_and_real_through_cells(self):
        web = last(ok("web shape=круг radius=30 radials=8 rings=2 wire=.5 sag=.1"))
        self.assertEqual(parts(web.manifold), 1)
        self.assertGreater(web.manifold.volume(), 10.0)
        self.assertGreater(web.manifold.genus(), 0)
        angle = math.pi / 8.0
        self.assertEqual(vertical_hits(web.manifold, 15 * math.cos(angle),
                                       15 * math.sin(angle)), [])
        filled = last(ok("web shape=круг radius=30 radials=8 rings=2 wire=.5 "
                         "sag=.1 membrane=да membrane_thick=.2 scallop=0"))
        self.assertNotEqual(vertical_hits(filled.manifold, 15 * math.cos(angle),
                                          15 * math.sin(angle)), [])
        self.assertGreater(filled.manifold.volume(), web.manifold.volume())

    def test_wing_and_fin_have_scalloped_membranes(self):
        for shape in ("крыло", "плавник"):
            with self.subTest(shape=shape):
                flat = last(ok(f"web shape={shape} radius=70 radials=7 scallop=0 membrane=да"))
                curved = last(ok(f"web shape={shape} radius=70 radials=7 scallop=.45 membrane=да"))
                self.assertEqual(parts(curved.manifold), 1)
                self.assertLess(curved.manifold.volume(), flat.manifold.volume() * 0.94)
                self.assertTrue(curved.meta["membrane"])


class TestShrinkwrap048(unittest.TestCase):
    script = ("цель = sphere radius=20\n"
              "плёнка = box size=[20,20,2] at=[0,0,20]\n"
              "плёнка = shrinkwrap [цель, плёнка] gap={gap} direction=вниз detail=2")

    def test_gap_sign_and_preserved_thickness(self):
        wrapped = {}
        for gap in (1.0, -1.0):
            result = ok(self.script.format(gap=gap))
            obj = result.scene.objects["плёнка"]
            self.assertEqual(parts(obj.manifold), 1)
            self.assertGreater(obj.manifold.volume(), 100.0)
            hits = vertical_hits(obj.manifold)
            self.assertEqual(len(hits), 2)
            wrapped[gap] = hits
            # Проецируется именно сетка: это не плоская исходная пластина.
            bb = obj.manifold.bounding_box()
            self.assertGreater(bb[5] - bb[2], 3.0)
            self.assertAlmostEqual(hits[0].position[2] - hits[1].position[2], 2.0, delta=0.15)
        self.assertAlmostEqual(wrapped[1.0][1].position[2] - wrapped[-1.0][1].position[2],
                               2.0, delta=0.15)

    def test_smooth_join_consumes_target_and_stays_one_body(self):
        result = ok(self.script.format(gap=-1) + " join=сгладить weld=2")
        self.assertEqual(parts(result.scene.objects["плёнка"].manifold), 1)
        self.assertFalse(result.scene.objects["цель"].visible)
        self.assertEqual(result.scene.objects["плёнка"].meta["join"], "сгладить")


class TestFlatScales048(unittest.TestCase):
    def test_tiles_are_flat_sheared_plates_and_kinds_differ(self):
        fish = _scale_tile(9, 14, 1.1, "рыба", 24)
        dragon = _scale_tile(9, 14, 1.1, "дракон", 24)
        for tile in (fish, dragon):
            verts, _ = manifold_mesh(tile)
            levels = np.round(verts[:, 2] + math.tan(math.radians(24)) * verts[:, 1], 5)
            self.assertEqual(len(np.unique(levels)), 2)  # две плоские стороны
            self.assertEqual(parts(tile), 1)
        self.assertNotAlmostEqual(fish.volume(), dragon.volume(), places=4)
        self.assertGreater(fish.num_tri(), dragon.num_tri())

    def test_rows_have_exact_overlap_and_dragon_is_supported(self):
        for kind in ("рыба", "дракон"):
            with self.subTest(kind=kind):
                obj = last(ok(f"ш = sphere radius=30\nscales ш kind={kind} rows=8 "
                              "per_row=12 length=6 overlap=.45"))
                self.assertEqual(parts(obj.manifold), 1)
                self.assertTrue(obj.meta["flat"])
                self.assertEqual(obj.meta["scale_kind"], kind)
                self.assertEqual(obj.meta["tiles"], 96)
                self.assertAlmostEqual(obj.meta["row_step"], 3.3)
                self.assertAlmostEqual(obj.meta["row_step"] / 6.0, 0.55)


if __name__ == "__main__":
    unittest.main()
