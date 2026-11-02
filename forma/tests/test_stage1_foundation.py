"""Этап 1: Contour2D, допуски, толщина/уклон и семантический diff."""

from __future__ import annotations

import contextlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest

import manifold3d as mf
import numpy as np

from forma.cli import main as cli_main
from forma.geometry import manifold_mesh
from forma.run import build
from forma.semantic_diff import semantic_diff


def _build(script: str):
    result = build(script)
    assert result.ok, (result.error or {}).get("message")
    return result


def _solid(result, name="д"):
    return result.scene.objects[name].manifold


class Contour2DTest(unittest.TestCase):
    def test_composite_line_arc_bezier_extrudes_as_one_profile(self):
        result = _build("""
п = contour2d start=[0,0] segments=[["line",[40,0]],["arc",[40,10],10,-90,0],["bezier",[[50,10],[55,20],[45,30],[40,40]]],["line",[0,40]]] closed=да tolerance=.08
д = extrude profile=п height=5
""")
        contour = result.scene.contours["п"]
        self.assertEqual([s["kind"] for s in contour.segments], ["line", "arc", "bezier", "line"])
        self.assertGreater(contour.to_dict()["sample"]["points"], 20)
        solid = _solid(result)
        self.assertEqual(solid.status(), mf.Error.NoError)
        self.assertEqual(len(solid.decompose()), 1)
        self.assertAlmostEqual(solid.bounding_box()[5], 5.0, delta=1e-5)
        self.assertGreater(solid.volume(), 1000.0)

    def test_ellipse_sampling_is_deterministic_and_follows_tolerance(self):
        coarse = _build("э = contour2d kind=ellipse rx=20 ry=8 tolerance=.2\n"
                        "д = extrude profile=э height=2")
        fine = _build("э = contour2d kind=ellipse rx=20 ry=8 tolerance=.03\n"
                      "д = extrude profile=э height=2")
        c0 = coarse.scene.contours["э"].sample()
        c1 = fine.scene.contours["э"].sample()
        np.testing.assert_allclose(c0, coarse.scene.contours["э"].sample())
        self.assertGreater(len(c1), len(c0) * 1.5)
        equation = (c1[:, 0] / 20.0) ** 2 + (c1[:, 1] / 8.0) ** 2
        np.testing.assert_allclose(equation, 1.0, atol=1e-9)
        self.assertGreater(_solid(fine).num_tri(), _solid(coarse).num_tri())

    def test_bezier_is_a_real_cubic_and_respects_point_budget(self):
        result = _build("к = contour2d kind=bezier points=[[0,0],[10,20],[30,20],[40,0]] tolerance=.05")
        contour = result.scene.contours["к"]
        points = contour.sample()
        np.testing.assert_allclose(points[0], [0, 0])
        np.testing.assert_allclose(points[-1], [40, 0])
        self.assertGreater(float(points[:, 1].max()), 10.0)
        self.assertGreater(len(points), 8)
        bad = build("к = contour2d kind=bezier points=[[0,0],[10,20],[30,20],[40,0]] tolerance=.0001 max_points=4",
                    analyze_model=False)
        self.assertFalse(bad.ok)
        self.assertIn("max_points", (bad.error or {}).get("message", ""))

    def test_disconnected_segments_are_rejected_at_the_joint(self):
        result = build("п = contour2d start=[0,0] segments=[[\"line\",[10,0]],[\"arc\",[20,0],5,180,270]]",
                       analyze_model=False)
        self.assertFalse(result.ok)
        message = (result.error or {}).get("message", "")
        self.assertTrue("стык" in message.lower() or "соедин" in message.lower())

    def test_arc_and_quadratic_bezier_keep_analytic_endpoints(self):
        result = _build("а = contour2d kind=arc radius=10 from=0 to=90 tolerance=.05\n"
                        "к = contour2d kind=bezier points=[[0,0],[5,10],[10,0]] tolerance=.05")
        arc = result.scene.contours["а"].sample()
        np.testing.assert_allclose(arc[0], [10, 0], atol=1e-9)
        np.testing.assert_allclose(arc[-1], [0, 10], atol=1e-9)
        np.testing.assert_allclose(np.linalg.norm(arc, axis=1), 10.0, atol=1e-9)
        curve = result.scene.contours["к"].sample()
        self.assertAlmostEqual(float(curve[:, 1].max()), 5.0, delta=1e-9)
        self.assertTrue(result.payload()["empty"])
        self.assertEqual(len(result.payload()["contours"]), 2)


class ContourIntegrationTest(unittest.TestCase):
    def test_lathe_accepts_reusable_contour(self):
        result = _build("п = contour2d start=[0,0] segments=[[\"line\",[30,0]],[\"line\",[30,40]],[\"line\",[0,40]]] closed=да\n"
                        "д = lathe points=п segments=96")
        self.assertAlmostEqual(_solid(result).volume(), math.pi * 30 ** 2 * 40,
                               delta=math.pi * 30 ** 2 * 40 * 0.01)

    def test_loft_aligns_adaptive_contours_with_different_sample_counts(self):
        result = _build("а = contour2d kind=ellipse rx=20 ry=10 tolerance=.2\n"
                        "б = contour2d kind=ellipse rx=15 ry=8 tolerance=.04\n"
                        "д = loft sections=[а,б] positions=[0,20]")
        solid = _solid(result)
        self.assertEqual(solid.status(), mf.Error.NoError)
        self.assertAlmostEqual(solid.bounding_box()[5], 20.0, delta=1e-5)
        self.assertEqual(len(solid.decompose()), 1)

    def test_sweep_accepts_contour_profile_and_bezier_path(self):
        result = _build("профиль = contour2d kind=ellipse rx=3 ry=2 tolerance=.08\n"
                        "путь = contour2d kind=bezier points=[[0,0],[10,20],[30,20],[40,0]] tolerance=.08\n"
                        "д = sweep path=путь profile=профиль")
        solid = _solid(result)
        self.assertEqual(solid.status(), mf.Error.NoError)
        bb = solid.bounding_box()
        self.assertGreater(bb[4], 10.0)
        self.assertGreater(bb[3], 35.0)
        self.assertEqual(len(solid.decompose()), 1)

    def test_sweep_plane_and_operation_tolerance_are_independent(self):
        result = _build("путь = contour2d kind=line points=[[0,0],[10,0]] plane=xz at=[1,2,3]\n"
                        "профиль = contour2d kind=ellipse rx=2 ry=1 tolerance=.1\n"
                        "д = sweep path=путь profile=профиль tolerance=.02")
        solid = _solid(result)
        self.assertEqual(solid.status(), mf.Error.NoError)
        self.assertAlmostEqual(solid.bounding_box()[0], 1.0, delta=1e-5)
        self.assertAlmostEqual(solid.bounding_box()[3], 11.0, delta=1e-5)

    def test_smooth_loft_uses_the_end_profile_for_its_cap(self):
        result = _build("а = contour2d kind=ellipse rx=20 ry=10 tolerance=.2\n"
                        "б = contour2d kind=ellipse rx=15 ry=8 tolerance=.04\n"
                        "д = loft sections=[а,б] positions=[0,20] smooth=3")
        self.assertEqual(_solid(result).status(), mf.Error.NoError)
        self.assertEqual(len(_solid(result).decompose()), 1)


class ThicknessAndDraftTest(unittest.TestCase):
    def test_extrude_thickness_leaves_bottom_and_real_wall(self):
        result = _build("э = contour2d kind=ellipse rx=20 ry=10 tolerance=.08\n"
                        "д = extrude profile=э height=10 thickness=2 open=top")
        solid = _solid(result)
        centre_bottom = mf.Manifold.cube([1, 1, 1], True).translate([0, 0, 1])
        centre_void = mf.Manifold.cube([1, 1, 1], True).translate([0, 0, 5])
        wall = mf.Manifold.cube([1, 1, 1], True).translate([19, 0, 5])
        self.assertGreater((solid ^ centre_bottom).volume(), 0.9)
        self.assertLess((solid ^ centre_void).volume(), 1e-5)
        self.assertGreater((solid ^ wall).volume(), 0.9)
        self.assertEqual(len(solid.decompose()), 1)

    def test_draft_offsets_top_by_height_tan_angle(self):
        result = _build("д = extrude profile=[[-20,-10],[20,-10],[20,10],[-20,10]] height=10 draft=10")
        solid = _solid(result)
        verts, _ = manifold_mesh(solid)
        top = verts[np.abs(verts[:, 2] - 10.0) < 1e-4]
        expected_delta = 10.0 * math.tan(math.radians(10.0))
        self.assertAlmostEqual(float(top[:, 0].max() - top[:, 0].min()),
                               40.0 - 2 * expected_delta, delta=0.01)
        self.assertAlmostEqual(float(top[:, 1].max() - top[:, 1].min()),
                               20.0 - 2 * expected_delta, delta=0.01)
        self.assertEqual(solid.status(), mf.Error.NoError)

    def test_draft_thickness_and_contour_hole_remain_one_manifold(self):
        result = _build("о = contour2d kind=ellipse rx=5 ry=4 tolerance=.1\n"
                        "д = extrude profile=[[-20,-10],[20,-10],[20,10],[-20,10]] "
                        "holes=о height=10 draft=5 thickness=1 open=top")
        solid = _solid(result)
        self.assertEqual(solid.status(), mf.Error.NoError)
        self.assertEqual(len(solid.decompose()), 1)
        centre = mf.Manifold.cube([1, 1, 1], True).translate([0, 0, 5])
        self.assertLess((solid ^ centre).volume(), 1e-5)
        self.assertGreater(solid.volume(), 0.0)


class SemanticDiffTest(unittest.TestCase):
    def test_object_measurements_parameters_and_tolerances(self):
        before = _build("let w=10\nк = box size=[10,10,10]")
        after = _build("let w=12\nк = box size=[10,10,12]\nш = sphere radius=3 segments=12")
        report = semantic_diff(before, after, linear_tol=0.01)
        self.assertEqual(report["added"], ["ш"])
        changed = {item["name"]: item for item in report["changed"]}
        self.assertIn("к", changed)
        self.assertAlmostEqual(changed["к"]["measurements"]["size"]["delta"][2], 2.0)
        self.assertEqual(report["parameters"]["changed"]["w"]["delta"], 2.0)
        close = _build("let w=10.000001\nк = box size=[10,10,10.000001]")
        self.assertFalse(semantic_diff(before, close, linear_tol=0.001)["changed"])
        self.assertFalse(semantic_diff(before, close, linear_tol=0.001)["parameters"]["changed"])

    def test_cli_diff_emits_machine_readable_report(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "a.forma"
            b = Path(folder) / "b.forma"
            a.write_text("к = box size=[10,10,10]", encoding="utf-8")
            b.write_text("к = box size=[10,10,11]", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli_main(["diff", str(a), str(b), "--json"])
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["changed"][0]["name"], "к")
            self.assertAlmostEqual(report["changed"][0]["measurements"]["size"]["delta"][2], 1.0)

    def test_additional_measure_functions_are_numeric(self):
        result = _build("к = box size=[10,10,10]\n"
                        "let a=area(к)\nlet t=tris(к)\nlet p=parts(к)\nlet g=genus(к)")
        self.assertAlmostEqual(result.scene.params["a"], 6.0)
        self.assertEqual(result.scene.params["t"], 12.0)
        self.assertEqual(result.scene.params["p"], 1.0)
        self.assertEqual(result.scene.params["g"], 0.0)

    def test_semantic_diff_reports_contours_and_invalid_tolerance(self):
        before = _build("э = contour2d kind=ellipse rx=10 ry=5")
        after = _build("э = contour2d kind=ellipse rx=12 ry=5")
        report = semantic_diff(before, after)
        self.assertEqual(report["contours"]["changed"][0]["name"], "э")
        with self.assertRaises(ValueError):
            semantic_diff(before, after, linear_tol=0)


if __name__ == "__main__":
    unittest.main()
