"""0.43: переработанные готовые формы, удаления и границы полей инструментов."""

from __future__ import annotations

import math
import shutil
import subprocess
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np

import forma.run  # noqa: F401 — наполняет реестр
from forma.ops import lookup
from forma.ops_blade import _arc_path
from forma.run import build, commands_help

ROOT = Path(__file__).resolve().parents[1]


def ok(script: str):
    result = build(script, analyze_model=False)
    assert result.ok, (result.error or {}).get("message")
    return result


def solid(result, name="о"):
    return result.scene.objects[name].manifold


def size(result, name="о"):
    bb = solid(result, name).bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


def inside(m, point) -> bool:
    probe = mf.Manifold.cube((0.4, 0.4, 0.4), True).translate(point)
    return bool((m ^ probe).volume() > 1e-7)


class RemovedObjectsTest(unittest.TestCase):
    REMOVED = ("rail", "bearing", "hinge", "caster", "rack", "coupling",
               "heatsink", "leg")

    def test_registry_rejects_all_eight(self):
        for op in self.REMOVED:
            with self.subTest(op=op):
                self.assertIsNone(lookup(op))
                self.assertFalse(build(f"о = {op}", analyze_model=False).ok)

    def test_cards_and_legacy_modes_are_gone(self):
        text = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        for op in self.REMOVED:
            self.assertNotIn(f"op: '{op}'", text)
        self.assertIsNone(lookup("форма_п"))
        self.assertIsNone(lookup("форма_у"))
        for script in ("о = arrow feathers=да", "о = cartridge kind=пистолетный",
                       "о = hemisphere mode=миска", "о = крюк eye=да",
                       "о = stairs shape=скошенная"):
            with self.subTest(script=script):
                self.assertFalse(build(script, analyze_model=False).ok)


class HandleTest(unittest.TestCase):
    def test_all_independent_shape_combinations_are_one_body(self):
        for bar in ("цилиндр", "капсула", "брусок"):
            for post in ("цилиндр", "капсула", "брусок"):
                with self.subTest(bar=bar, post=post):
                    b = ok(f"о = handle length=160 height=34 diameter=10 "
                           f"bar_shape={bar} post_shape={post} plates=нет")
                    m = solid(b)
                    self.assertEqual(len(m.decompose()), 1)
                    self.assertAlmostEqual(size(b)[0], 160.0, delta=0.05,
                                           msg="перекладина шире боковых стоек")
                    self.assertAlmostEqual(m.bounding_box()[2], 0.0, places=5)

    def test_plates_are_really_removable(self):
        with_plates = ok("о = handle plates=да")
        without = ok("о = handle plates=нет")
        self.assertGreater(solid(with_plates).volume(), solid(without).volume())
        self.assertGreater(size(with_plates)[0], size(without)[0])
        self.assertAlmostEqual(size(without)[0], 160.0, delta=0.05)

    def test_capsule_posts_have_flat_mounting_bottom(self):
        b = ok("о = handle length=160 height=34 diameter=10 "
               "bar_shape=капсула post_shape=капсула plates=нет")
        m = solid(b)
        for x in (-75.0, 75.0):
            self.assertTrue(inside(m, (x, 0.0, 0.2)),
                            "нижний торец капсульной стойки должен быть плоским")


class SwirlAndLadderTest(unittest.TestCase):
    def test_swirl_is_one_continuous_tapered_tube(self):
        thin = solid(ok("о = swirl radius=40 height=64 coils=3 wire=8"))
        thick = solid(ok("о = swirl radius=40 height=64 coils=3 wire=16"))
        self.assertEqual(len(thick.decompose()), 1)
        self.assertGreater(thick.volume(), thin.volume() * 1.5)
        self.assertAlmostEqual(thick.bounding_box()[5], 64.0, delta=0.2)
        self.assertFalse(build("о = swirl groove=4", analyze_model=False).ok)
        self.assertFalse(build("о = swirl radius=40 height=60 coils=3 wire=20",
                               analyze_model=False).ok)

    def test_all_ladder_shapes_stay_joined(self):
        for rail in ("капсула", "брусок", "овал"):
            for rung in ("цилиндр", "брусок"):
                with self.subTest(rail=rail, rung=rung):
                    b = ok(f"о = ladder length=600 width=300 rail={rail} rail_d=38 "
                           f"rung={rung} rung_d=30 rungs=4 tilt=0")
                    self.assertEqual(len(solid(b).decompose()), 1)
                    self.assertAlmostEqual(size(b)[1], 338.0, delta=0.05)

    def test_oval_rail_has_flat_sides_not_ellipsoid(self):
        b = ok("о = ladder length=600 width=300 rail=овал rail_d=38 "
               "rung=цилиндр rung_d=30 rungs=4 tilt=0")
        m = solid(b)
        vertices = np.asarray(m.to_mesh().vert_properties)[:, :3]
        side = vertices[np.abs(vertices[:, 1] - m.bounding_box()[4]) < 1e-4]
        # У стадиона вся боковая грань лежит на maxY, поэтому там есть и верх,
        # и низ рейки. У эллипсоида на maxY была бы только экваториальная линия.
        self.assertGreater(float(np.ptp(side[:, 2])), 37.9)

    def test_too_thick_rung_is_rejected(self):
        self.assertFalse(build("о = ladder rail_d=20 rung_d=30",
                               analyze_model=False).ok)


class StairsLeverAndSmallPartsTest(unittest.TestCase):
    def test_stairs_have_independent_outer_and_inner_corners(self):
        sharp = solid(ok("о = stairs steps=5 rise=16 run=30 width=100"))
        outer = solid(ok("о = stairs steps=5 rise=16 run=30 width=100 shape=скруглённая"))
        inner = solid(ok("о = stairs steps=5 rise=16 run=30 width=100 inner=скруглённый"))
        self.assertLess(outer.volume(), sharp.volume())
        self.assertGreater(inner.volume(), sharp.volume())
        self.assertFalse(build("о = stairs shape=скошенная", analyze_model=False).ok)

    def test_ball_knob_uses_length_and_shaft_does_not_pierce_it(self):
        short = ok("о = lever length=180 diameter=14 knob=шар knob_d=34 knob_h=30")
        long = ok("о = lever length=180 diameter=14 knob=шар knob_d=34 knob_h=70")
        self.assertGreater(solid(long).volume(), solid(short).volume())
        self.assertAlmostEqual(size(long)[0], 180.0, delta=0.05)
        m = solid(long)
        vertices = np.asarray(m.to_mesh().vert_properties)[:, :3]
        at_tip = vertices[np.abs(vertices[:, 0] - m.bounding_box()[3]) < 1e-4]
        self.assertLessEqual(len(at_tip), 2, "плоский торец палки виден на острие шара")
        self.assertFalse(build("о = lever knob=нет", analyze_model=False).ok)

    def test_button_and_grommet_have_real_smoothing(self):
        plain = ok("о = button")
        smooth = ok("о = button smooth=1")
        self.assertEqual(len(smooth.scene.objects), 2)
        self.assertGreater(solid(smooth).num_tri(), solid(plain).num_tri())
        g0 = solid(ok("о = grommet"))
        g1 = solid(ok("о = grommet smooth=1"))
        self.assertGreater(g1.num_tri(), g0.num_tri())

    def test_gusset_is_exact_right_triangle(self):
        b = ok("о = gusset leg=70 height=55 thickness=6")
        m = solid(b)
        self.assertEqual(len(m.decompose()), 1)
        self.assertEqual(len(m.to_mesh().vert_properties), 6)
        self.assertAlmostEqual(m.volume(), 0.5 * 70 * 55 * 6, delta=0.01)
        self.assertTrue(np.allclose(size(b), [70, 6, 55], atol=1e-5))


class BladeTest(unittest.TestCase):
    def test_arc_has_exact_requested_sagitta_and_direction(self):
        for curve in (20.0, -20.0, 0.0):
            path = _arc_path(400.0, curve, 41)
            # 0.45: сгиб в плоскости ШИРИНЫ XY, а не через толщину Z.
            self.assertAlmostEqual(float(path[len(path) // 2, 1]), curve, places=7)
            self.assertAlmostEqual(float(path[0, 1]), 0.0, places=7)
            self.assertAlmostEqual(float(path[-1, 1]), 0.0, places=7)
            self.assertTrue(np.allclose(path[:, 2], 0.0))

    def test_profile_and_section_change_whole_blade(self):
        straight = solid(ok("о = blade profile=прямой section=клин tip=тупое curve=0"))
        leaf = solid(ok("о = blade profile=листовой section=клин tip=тупое curve=0"))
        flat = solid(ok("о = blade profile=прямой section=плоский tip=тупое curve=0"))
        self.assertGreater(leaf.volume(), straight.volume() * 1.01)
        self.assertNotAlmostEqual(flat.volume(), straight.volume(), delta=100.0)

    def test_tip_types_and_all_presets_build(self):
        for tip in ("острое", "киссаки", "закруглённое", "тупое"):
            with self.subTest(tip=tip):
                self.assertEqual(len(solid(ok(f"о = blade tip={tip}")).decompose()), 1)
        for kind in ("катана", "танто", "ятоган", "стилет", "двуручник", "серп", "нож"):
            with self.subTest(kind=kind):
                self.assertEqual(len(solid(ok(f"о = blade kind={kind}")).decompose()), 1)


class FirstBatchRegressionTest(unittest.TestCase):
    def test_hemisphere_wall_replaces_mode(self):
        full = solid(ok("о = hemisphere radius=50"))
        bowl = solid(ok("о = hemisphere radius=50 wall=4 round=1"))
        self.assertAlmostEqual(full.volume(), 2.0 * math.pi * 50.0 ** 3 / 3.0,
                               delta=full.volume() * 0.01)
        self.assertLess(bowl.volume(), full.volume() * 0.5)
        self.assertAlmostEqual(bowl.bounding_box()[5], 50.0, delta=0.05)

    def test_smooth_bracket_oval_bracket_and_plate(self):
        for script in ("о = bracket angle=180 smooth=1",
                       "о = скоба length=120 width=40 height=35 wall=3 shape=овал smooth=1"):
            with self.subTest(script=script):
                self.assertEqual(len(solid(ok(script)).decompose()), 1)
        shallow = size(ok("о = plate diameter=120 depth=20 rim=4 rim_height=3"))[2]
        deep = size(ok("о = plate diameter=120 depth=30 rim=4 rim_height=3"))[2]
        self.assertAlmostEqual(deep - shallow, 10.0, delta=0.1)

    def test_hollow_shapes_star_leaves_and_yin_yang(self):
        for script in ("о = lightning wall=2", "о = heart wall=2",
                       "о = plus wall=2", "о = horn wall=2",
                       "о = star outer=50 inner=20 depth=10 bevel=2 twist=25 blade=0.2 hole=8 wall=2",
                       "о = yin_yang hole=12", "о = yin_yang wall=4"):
            with self.subTest(script=script):
                self.assertEqual(len(solid(ok(script)).decompose()), 1)
        for kind in ("овал", "липа", "дуб", "клен", "заострённый"):
            with self.subTest(kind=kind):
                b = ok(f"о = leaf kind={kind} length=90 width=45 thickness=2")
                self.assertAlmostEqual(size(b)[0], 90.0, delta=0.1)
                self.assertAlmostEqual(size(b)[2], 45.0, delta=0.1)

    def test_narrow_arrow_and_new_hook_have_no_legacy_parts(self):
        arrow = ok("о = arrow length=120 width=26 head_width=26")
        self.assertAlmostEqual(size(arrow)[2], 26.0, delta=0.1)
        for tip in ("капсула", "острый"):
            with self.subTest(tip=tip):
                self.assertEqual(len(solid(ok(f"о = крюк tip={tip}")).decompose()), 1)


class HelpExamplesTest(unittest.TestCase):
    def test_every_primitive_help_example_builds(self):
        specs = [c for c in commands_help() if c["category"] == "Примитивы"]
        self.assertEqual(len(specs), 114)
        for spec in specs:
            with self.subTest(command=spec["name"]):
                result = build(spec["example"], analyze_model=False)
                self.assertTrue(result.ok, (result.error or {}).get("message"))
                for object_name, obj in result.scene.objects.items():
                    self.assertFalse(obj.manifold.is_empty(), object_name)
                    self.assertEqual(str(obj.manifold.status()), "Error.NoError", object_name)


class NumericBoundsTest(unittest.TestCase):
    def test_node_steps_stop_at_every_numeric_boundary(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js нужен для выполнения JS-проверки стрелок")
        script = ROOT / "tests/ui_bounds_test.js"
        result = subprocess.run([node, str(script)], cwd=ROOT, text=True,
                                capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("границы", result.stdout)


if __name__ == "__main__":
    unittest.main()
