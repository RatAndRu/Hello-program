"""0.42: независимые плоскости, срезы и топология стандартных тел."""

from __future__ import annotations

import math
import unittest

import numpy as np

import forma.run  # noqa: F401
from forma.run import build, commands_help


def ok(script: str):
    result = build(script, analyze_model=False)
    assert result.ok, (result.error or {}).get("message")
    return result


def fail(script: str) -> str:
    result = build(script, analyze_model=False)
    assert not result.ok, script
    return (result.error or {}).get("message", "")


def solid(result, name="д"):
    return result.scene.objects[name].manifold


def verts(result, name="д") -> np.ndarray:
    return np.asarray(solid(result, name).to_mesh().vert_properties,
                      dtype=np.float64)[:, :3]


def ring(vertices: np.ndarray, top: bool) -> np.ndarray:
    z = vertices[:, 2].max() if top else vertices[:, 2].min()
    return vertices[np.abs(vertices[:, 2] - z) < 1e-5]


def size(result, name="д") -> np.ndarray:
    bb = solid(result, name).bounding_box()
    return np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])


def watertight(test: unittest.TestCase, result, name="д"):
    body = solid(result, name)
    test.assertEqual(body.status().name, "NoError")
    test.assertEqual(len(body.decompose()), 1)
    test.assertGreater(body.volume(), 0.0)


class BoxTopTest(unittest.TestCase):
    def test_top_size_and_offset_are_independent(self):
        b = ok("д = box size=[100,80,50] top_size=[60,40] top_offset=[10,-5]")
        v = verts(b)
        bottom, top = ring(v, False), ring(v, True)
        self.assertTrue(np.allclose(top[:, 2], 50.0, atol=1e-6))
        self.assertAlmostEqual(top[:, 0].max() - top[:, 0].min(), 60.0, places=5)
        self.assertAlmostEqual(top[:, 1].max() - top[:, 1].min(), 40.0, places=5)
        delta = top[:, :2].mean(axis=0) - bottom[:, :2].mean(axis=0)
        self.assertTrue(np.allclose(delta, [10.0, -5.0], atol=1e-6))
        watertight(self, b)

    def test_parallelogram_has_real_angle_and_volume(self):
        b = ok("д = box size=[100,80,50] base_angle=60")
        expected = 100.0 * 80.0 * math.sin(math.radians(60.0)) * 50.0
        self.assertAlmostEqual(solid(b).volume(), expected, delta=1.0)
        v = ring(verts(b), False)
        self.assertAlmostEqual(v[:, 1].max() - v[:, 1].min(),
                               80.0 * math.sin(math.radians(60.0)), places=5)
        watertight(self, b)

    def test_round_custom_box_preserves_height_and_stays_inside(self):
        script = "д = box size=[100,80,50] top_size=[60,40] top_offset=[10,-5] base_angle=70"
        plain = solid(ok(script))
        rounded = solid(ok(script + " round=3"))
        pb, rb = plain.bounding_box(), rounded.bounding_box()
        self.assertAlmostEqual(pb[2], rb[2], places=5)
        self.assertAlmostEqual(pb[5], rb[5], places=5)
        self.assertGreaterEqual(rb[0], pb[0] - 1e-5)
        self.assertGreaterEqual(rb[1], pb[1] - 1e-5)
        self.assertLessEqual(rb[3], pb[3] + 1e-5)
        self.assertLessEqual(rb[4], pb[4] + 1e-5)
        self.assertLess(rounded.volume(), plain.volume())
        self.assertEqual(rounded.status().name, "NoError")


class PrismAndCylinderTest(unittest.TestCase):
    def test_prism_top_scale_offset_and_r2(self):
        b = ok("д = prism sides=6 radius=30 r2=20 height=50 "
               "top_scale=[1.2,0.8] top_offset=[10,-5]")
        v = verts(b)
        bottom, top = ring(v, False), ring(v, True)
        self.assertAlmostEqual(top[:, 0].max() - top[:, 0].min(), 48.0, places=5)
        self.assertAlmostEqual(top[:, 1].max() - top[:, 1].min(),
                               40.0 * math.sin(math.radians(60.0)) * 0.8, places=5)
        delta = top[:, :2].mean(axis=0) - bottom[:, :2].mean(axis=0)
        self.assertTrue(np.allclose(delta, [10.0, -5.0], atol=1e-6))
        watertight(self, b)

    def test_prism_parallelogram_and_validation(self):
        b = ok("д = prism sides=4 radius=30 height=50 base_angle=60")
        side = math.sqrt(2.0) * 30.0
        self.assertAlmostEqual(solid(b).volume(),
                               side * side * math.sin(math.radians(60.0)) * 50.0,
                               delta=1.0)
        self.assertIn("sides=4", fail("д = prism sides=6 radius=30 height=50 base_angle=60"))

    def test_prism_smooth_is_geometric_and_keeps_bounds(self):
        plain = ok("д = prism sides=6 radius=30 height=50")
        smooth = ok("д = prism sides=6 radius=30 height=50 smooth=2")
        self.assertEqual(solid(smooth).num_tri(), solid(plain).num_tri() * 16)
        self.assertTrue(np.allclose(size(plain), size(smooth), atol=1e-5))
        self.assertNotAlmostEqual(solid(plain).volume(), solid(smooth).volume(), places=2)
        watertight(self, smooth)

    def test_cylinder_top_is_shifted_ellipse(self):
        b = ok("д = cylinder radius=40 height=60 r2=30 "
               "top_scale=[1.2,0.7] top_offset=[10,-5]")
        v = verts(b)
        bottom, top = ring(v, False), ring(v, True)
        self.assertTrue(np.allclose(top[:, 2], 60.0, atol=1e-6))
        self.assertAlmostEqual(top[:, 0].max() - top[:, 0].min(), 72.0, places=4)
        self.assertAlmostEqual(top[:, 1].max() - top[:, 1].min(), 42.0, places=4)
        delta = top[:, :2].mean(axis=0) - bottom[:, :2].mean(axis=0)
        self.assertTrue(np.allclose(delta, [10.0, -5.0], atol=1e-5))
        watertight(self, b)

    def test_cylinder_custom_round_preserves_height_and_stays_inside(self):
        script = "д = cylinder radius=40 height=60 r2=30 top_scale=[1.2,0.7] top_offset=[10,-5]"
        plain = solid(ok(script))
        rounded = solid(ok(script + " round=3"))
        pb, rb = plain.bounding_box(), rounded.bounding_box()
        self.assertAlmostEqual(pb[2], rb[2], places=5)
        self.assertAlmostEqual(pb[5], rb[5], places=5)
        self.assertTrue(all(rb[i] >= pb[i] - 1e-5 for i in (0, 1)))
        self.assertTrue(all(rb[i] <= pb[i] + 1e-5 for i in (3, 4)))
        self.assertLess(rounded.volume(), plain.volume())


class PyramidTest(unittest.TestCase):
    def test_tip_can_sit_above_requested_corner(self):
        b = ok("д = pyramid sides=4 radius=40 height=70 tip_at=corner tip_index=0")
        top = ring(verts(b), True)
        self.assertEqual(len(top), 1)
        self.assertTrue(np.allclose(top[0], [40.0, 0.0, 70.0], atol=1e-6))
        self.assertEqual(b.scene.objects["д"].meta["tip"]["mode"], "corner")

    def test_tip_can_sit_above_requested_edge(self):
        b = ok("д = pyramid sides=4 radius=40 height=70 tip_at=edge tip_index=1")
        top = ring(verts(b), True)
        self.assertTrue(np.allclose(top[0], [-20.0, 20.0, 70.0], atol=1e-6))

    def test_parallelogram_pyramid_and_conflicts(self):
        b = ok("д = pyramid sides=4 radius=40 height=70 base_angle=60 tip_at=corner")
        side = math.sqrt(2.0) * 40.0
        expected = side * side * math.sin(math.radians(60.0)) * 70.0 / 3.0
        self.assertAlmostEqual(solid(b).volume(), expected, delta=2.0)
        self.assertIn("ИЛИ", fail("д = pyramid radius=40 height=70 tip=[1,2] tip_at=corner"))
        self.assertIn("tip_index", fail("д = pyramid radius=40 height=70 tip_index=1"))

    def test_pyramid_smooth_levels_are_real(self):
        plain = ok("д = pyramid sides=4 radius=40 height=70")
        smooth = ok("д = pyramid sides=4 radius=40 height=70 smooth=2")
        self.assertEqual(solid(smooth).num_tri(), solid(plain).num_tri() * 16)
        self.assertTrue(np.allclose(size(plain), size(smooth), atol=1e-5))
        watertight(self, smooth)


class OctaAndEllipsoidTest(unittest.TestCase):
    def test_octa_divisions_add_vertices_without_changing_shape(self):
        plain = ok("д = octa radius=30 height=80")
        divided = ok("д = octa radius=30 height=80 divisions=2")
        self.assertEqual(solid(plain).num_vert(), 6)
        self.assertEqual(solid(plain).num_tri(), 8)
        self.assertEqual(solid(divided).num_vert(), 66)
        self.assertEqual(solid(divided).num_tri(), 128)
        self.assertAlmostEqual(solid(divided).volume(), solid(plain).volume(), places=4)
        self.assertTrue(np.allclose(size(plain), size(divided), atol=1e-6))

    def test_octa_smooth_changes_geometry_and_keeps_bounds(self):
        plain = ok("д = octa radius=30 height=80")
        smooth = ok("д = octa radius=30 height=80 divisions=1 smooth=2")
        self.assertEqual(solid(smooth).num_tri(), 512)
        self.assertTrue(np.allclose(size(plain), size(smooth), atol=1e-5))
        self.assertNotAlmostEqual(solid(plain).volume(), solid(smooth).volume(), places=2)
        watertight(self, smooth)

    def test_ellipsoid_geodesic_detail_levels(self):
        counts = []
        for level, expected in ((0, 20), (1, 80), (2, 320)):
            b = ok(f"д = ellipsoid x=60 y=40 z=22 divisions={level}")
            counts.append(solid(b).num_tri())
            self.assertEqual(solid(b).num_tri(), expected)
            self.assertTrue(np.allclose(size(b), [120.0, 80.0, 44.0], atol=0.2))
            watertight(self, b)
        self.assertEqual(counts, [20, 80, 320])
        self.assertIn("ИЛИ", fail("д = ellipsoid x=60 divisions=2 detail=3"))


class IcosphereTopologyTest(unittest.TestCase):
    def test_triangle_mode_now_accepts_zero(self):
        b = ok("д = icosphere radius=40 divisions=0")
        self.assertEqual(solid(b).num_vert(), 12)
        self.assertEqual(solid(b).num_tri(), 20)
        self.assertEqual(b.scene.objects["д"].meta["topology"]["panels"], 20)
        watertight(self, b)

    def test_quad_mode_has_cube_sphere_panels(self):
        for level, panels in ((0, 6), (1, 24), (2, 96)):
            b = ok(f"д = icosphere radius=40 mode=quad divisions={level}")
            topology = b.scene.objects["д"].meta["topology"]
            self.assertEqual(topology["panels"], panels)
            self.assertEqual(topology["quads"], panels)
            self.assertEqual(solid(b).num_tri(), panels * 2)
            watertight(self, b)
        cube = solid(ok("д = icosphere radius=40 mode=quad divisions=0"))
        self.assertAlmostEqual(cube.volume(), (80.0 / math.sqrt(3.0)) ** 3, delta=2.0)

    def test_pentagon_mode_is_dodecahedron_at_zero(self):
        b = ok("д = icosphere radius=40 mode=pentagon divisions=0")
        topology = b.scene.objects["д"].meta["topology"]
        self.assertEqual(topology["panels"], 12)
        self.assertEqual(topology["pentagons"], 12)
        self.assertEqual(topology["hexagons"], 0)
        self.assertEqual(solid(b).num_vert(), 20)
        self.assertEqual(solid(b).num_tri(), 36)
        watertight(self, b)

    def test_honeycomb_has_twelve_pentagons_and_hexagons(self):
        b = ok("д = icosphere radius=40 mode=сота divisions=1")
        topology = b.scene.objects["д"].meta["topology"]
        self.assertEqual(topology["panels"], 122)
        self.assertEqual(topology["pentagons"], 12)
        self.assertEqual(topology["hexagons"], 110)
        payload = b.payload()["objects"][0]["topology"]
        self.assertEqual(payload["hexagons"], 110)
        watertight(self, b)

    def test_unknown_icosphere_mode_is_explained(self):
        self.assertIn("mode", fail("д = icosphere radius=40 mode=семиугольник"))


class SphereSliceTest(unittest.TestCase):
    def test_half_slice_has_analytic_volume_and_original_center(self):
        b = ok("д = sphere radius=40 slice=1 at=[0,0,40]")
        body = solid(b)
        bb = body.bounding_box()
        self.assertAlmostEqual(bb[2], 0.0, delta=1e-5)
        self.assertAlmostEqual(bb[5], 40.0, delta=1e-5)
        expected = 2.0 / 3.0 * math.pi * 40.0 ** 3
        self.assertAlmostEqual(body.volume() / expected, 1.0, delta=0.01)
        watertight(self, b)

    def test_fraction_and_millimetres_describe_same_slice(self):
        fraction = solid(ok("д = sphere radius=40 slice=0.3"))
        millimetres = solid(ok("д = sphere radius=40 cut=12"))
        self.assertAlmostEqual(fraction.volume(), millimetres.volume(), delta=1e-4)
        self.assertAlmostEqual(fraction.bounding_box()[5], 28.0, places=4)
        expected = math.pi * (40.0 ** 2 * (28.0 + 40.0) - (28.0 ** 3 + 40.0 ** 3) / 3.0)
        self.assertAlmostEqual(fraction.volume() / expected, 1.0, delta=0.01)

    def test_rounded_slice_has_smaller_top_rim_and_volume(self):
        sharp = solid(ok("д = sphere radius=40 slice=0.5 round=0"))
        rounded_result = ok("д = sphere radius=40 slice=0.5 round=3")
        rounded = solid(rounded_result)
        self.assertAlmostEqual(sharp.bounding_box()[5], rounded.bounding_box()[5], places=5)
        self.assertLess(rounded.volume(), sharp.volume())
        sharp_top = ring(verts(ok("д = sphere radius=40 slice=0.5")), True)
        rounded_top = ring(verts(rounded_result), True)
        sharp_r = np.linalg.norm(sharp_top[:, :2], axis=1).max()
        rounded_r = np.linalg.norm(rounded_top[:, :2], axis=1).max()
        self.assertLess(rounded_r, sharp_r)
        watertight(self, rounded_result)

    def test_slice_validation(self):
        self.assertIn("глубже", fail("д = sphere radius=40 cut=41"))
        self.assertIn("ИЛИ", fail("д = sphere radius=40 slice=0.2 cut=4"))
        self.assertIn("slice>0", fail("д = sphere radius=40 round=2"))
        self.assertIn("слишком велик", fail("д = sphere radius=40 slice=1 round=20"))


class HelpTest(unittest.TestCase):
    def test_new_parameters_are_in_command_reference(self):
        commands = {c["name"]: c for c in commands_help()}
        expected = {
            "box": {"top_size", "top_offset", "base_angle"},
            "prism": {"top_scale", "top_offset", "base_angle", "smooth"},
            "pyramid": {"tip_at", "tip_index", "base_angle", "smooth"},
            "cylinder": {"top_scale", "top_offset"},
            "octa": {"divisions", "smooth"},
            "sphere": {"slice", "cut", "round"},
            "icosphere": {"mode", "divisions"},
            "ellipsoid": {"divisions"},
        }
        for name, params in expected.items():
            actual = {p["name"] for p in commands[name]["params"]}
            self.assertTrue(params <= actual, (name, params - actual))


if __name__ == "__main__":
    unittest.main()
