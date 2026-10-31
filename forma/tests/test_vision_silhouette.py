"""Проверяемые измерения по одному изображению и проекции Forma."""
from __future__ import annotations

import math
import unittest
from pathlib import Path
from unittest.mock import patch

import manifold3d as mf
import numpy as np

from forma import render
from forma.geometry import read_png
from forma.model import Solid
from forma.vision import (camera_elevation, compare, compare_model, fit_camera, iou,
                          mask_by_background, measure, render_mask, report)
from forma.vision import fit as fit_module

ROOT = Path(__file__).resolve().parents[1]


def rect_mask(w, h, x0=20, y0=20, W=200, H=200):
    mask = np.zeros((H, W), dtype=bool)
    mask[y0:y0 + h, x0:x0 + w] = True
    return mask


def ellipse_mask(a, b, cx=100, cy=100, W=260, H=260):
    yy, xx = np.mgrid[0:H, 0:W]
    return ((xx - cx) / a) ** 2 + ((yy - cy) / b) ** 2 <= 1.0


class SilhouetteTest(unittest.TestCase):
    def test_measure_rectangle(self):
        measured = measure(rect_mask(60, 120), profile_rows=4)
        self.assertEqual((measured.width, measured.height), (60, 120))
        self.assertAlmostEqual(measured.fill, 1.0, places=2)
        self.assertLess(measured.symmetry_err_pct, 1.0)
        self.assertEqual(len(measured.width_profile), 4)

    def test_symmetry_flags_asymmetric_part(self):
        mask = rect_mask(60, 120)
        mask[40:60, 20:110] = True
        self.assertGreater(measure(mask, profile_rows=4).symmetry_err_pct, 8.0)

    def test_identical_masks_pass_only_silhouette_contract(self):
        mask = ellipse_mask(60, 40)
        self.assertAlmostEqual(iou(mask, mask), 1.0, places=3)
        result = compare(mask, mask)
        self.assertTrue(result["passed"])
        self.assertEqual(result["verdict"], "силуэт совпадает")
        self.assertEqual(result["scope"], "single_projection")
        self.assertLess(result["row_err_px"], 0.5)

    def test_uniform_scale_and_translation_do_not_change_shape(self):
        ref = ellipse_mask(60, 40)
        scaled = ellipse_mask(120, 80, cx=260, cy=260, W=520, H=520)
        translated = ellipse_mask(60, 40, cx=170, cy=170)
        self.assertGreater(iou(ref, scaled), 0.98)
        self.assertAlmostEqual(iou(ref, translated), 1.0, places=3)
        self.assertLess(abs(compare(ref, scaled)["aspect_err_pct"]), 1.0)

    def test_narrower_model_is_rejected_by_iou_and_aspect(self):
        result = compare(ellipse_mask(60, 40), ellipse_mask(51, 40))
        self.assertFalse(result["passed"])
        self.assertLess(result["iou"], 0.90)
        self.assertLess(result["aspect_err_pct"], -10.0)

    def test_side_error_sign_describes_model_not_reference(self):
        ref = rect_mask(60, 120)
        ref[40:60, 20:110] = True
        model = rect_mask(60, 120)
        missing_right = compare(ref, model)
        extra_right = compare(model, ref)
        self.assertLess(missing_right["side_err"], -6.0)
        self.assertGreater(extra_right["side_err"], 6.0)
        self.assertFalse(missing_right["passed"])

    def test_narrow_row_is_seen_as_row_error(self):
        result = compare(rect_mask(60, 120), rect_mask(30, 120))
        self.assertFalse(result["passed"])
        self.assertGreater(result["row_err_px"], 15.0)

    def test_empty_mask_has_actionable_error(self):
        empty = np.zeros((30, 30), dtype=bool)
        for function in (iou, compare):
            with self.subTest(function=function.__name__):
                with self.assertRaisesRegex(ValueError, "пустая маска"):
                    function(empty, empty)

    def test_background_gradient_and_rgba_input(self):
        height, width = 160, 160
        yy, _xx = np.mgrid[0:height, 0:width]
        t = yy / (height - 1)
        bg = np.stack([120 + 40 * t, 175 + 30 * t, 229 + 20 * t], axis=2)
        image = bg.astype(np.uint8)
        image[50:120, 40:100] = (150, 150, 152)
        rgba = np.concatenate([image, np.full((height, width, 1), 255, dtype=np.uint8)], axis=2)
        for value in (image, rgba):
            with self.subTest(channels=value.shape[2]):
                mask = mask_by_background(value, tol=14)
                self.assertTrue(mask[80, 70])
                self.assertFalse(mask[10, 10])
                measured = measure(mask)
                self.assertEqual((measured.width, measured.height), (60, 70))

    def test_top_arc_recovers_orthographic_elevation(self):
        for elevation in (20.0, 35.0):
            with self.subTest(elevation=elevation):
                a = 90.0
                b = a * math.sin(math.radians(elevation))
                yy, xx = np.mgrid[0:320, 0:260]
                top = ((xx - 130) / a) ** 2 + ((yy - 100) / b) ** 2 <= 1.0
                tube = (np.abs(xx - 130) <= a) & (yy >= 100) & (yy <= 260)
                camera = camera_elevation(top | tube)
                self.assertTrue(camera["ok"], camera)
                self.assertAlmostEqual(camera["elevation_deg"], elevation, delta=2.0)

    def test_worst_cell_reports_location(self):
        ref = rect_mask(80, 140, x0=40, y0=20)
        broken = ref.copy()
        broken[:80, :] = False
        result = compare(ref, broken)
        self.assertIsNotNone(result["worst_cell"])
        self.assertEqual(result["worst_cell"]["cell"][0], 0)
        self.assertGreater(result["worst_cell"]["union_px"], 0)
        self.assertFalse(result["passed"])

    def test_real_photo_passport_is_reproducible(self):
        reference = ROOT.parent / ".github" / "forma-photo-saddle-reference.png"
        rgb = read_png(str(reference))
        self.assertIsNotNone(rgb)
        mask = mask_by_background(rgb)
        measured = measure(mask)
        self.assertEqual((measured.width, measured.height), (557, 662))
        self.assertEqual(measured.area, 222060)
        self.assertAlmostEqual(measured.fill, 0.6022227405, places=8)
        camera = camera_elevation(mask)
        self.assertTrue(camera["ok"], camera)
        self.assertAlmostEqual(camera["elevation_deg"], 36.1092805, places=5)
        self.assertLess(camera["resid_px"], 0.5)


class ProjectionFitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = mf.Manifold.cube([40, 30, 20]).translate([-20, -15, 0])
        boss = mf.Manifold.cylinder(20, 8, 8, 32).translate([10, -5, 20])
        cls.solids = [Solid("probe", base + boss)]

    def test_binary_raster_matches_shaded_render(self):
        size = 96
        direction = np.asarray(render.VIEWS["iso"][0], dtype=float)
        direction /= np.linalg.norm(direction)
        azim = math.degrees(math.atan2(direction[1], direction[0]))
        elev = math.degrees(math.asin(direction[2]))
        meshes = render._prepare(self.solids)
        vertices = np.concatenate([mesh["verts"] for mesh in meshes])
        lo, hi = vertices.min(axis=0), vertices.max(axis=0)
        bbox = [float(lo[0]), float(lo[1]), float(lo[2]),
                float(hi[0]), float(hi[1]), float(hi[2])]
        image, _camera = render._render_view(
            meshes, (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2,
            "iso", size, 1, bbox, grid=False, shadow=False, bg=(1.0, 1.0, 1.0))
        pixels = np.asarray(image)
        if pixels.max() <= 1.0001:
            pixels = pixels * 255.0
        shaded_mask = (255.0 - pixels).max(axis=2) > 12.0
        binary_mask = render_mask(self.solids, azim, elev, size=size)
        self.assertGreater(iou(shaded_mask, binary_mask), 0.995)
        self.assertLess(float(np.logical_xor(shaded_mask, binary_mask).mean()), 0.005)

    def test_default_render_does_not_mirror_canonical_coordinates(self):
        explicit = render_mask(self.solids, -60, 25, size=64, mirror=False)
        default = render_mask(self.solids, -60, 25, size=64)
        self.assertTrue(np.array_equal(explicit, default))

    def test_fit_reuses_mesh_and_preserves_global_views(self):
        reference = render_mask(self.solids, -60, 25, size=64)
        views_before = dict(render.VIEWS)
        with patch.object(fit_module, "manifold_mesh", wraps=fit_module.manifold_mesh) as prepared:
            result = fit_camera(reference, self.solids, azim=(-60, -30), elev=(20, 30),
                                size=64, refine=1, mirror=False)
        self.assertEqual(prepared.call_count, len(self.solids))
        self.assertEqual(render.VIEWS, views_before)
        self.assertGreater(result["renders"], 1)
        self.assertEqual(result["projection"], "orthographic")

    def test_fit_recovers_supplied_canonical_camera(self):
        reference = render_mask(self.solids, -60, 25, size=64, mirror=False)
        result = fit_camera(reference, self.solids, azim=(-60, 60), elev=(25,),
                            size=64, refine=0, mirror=False)
        self.assertEqual(result["azim_deg"], -60)
        self.assertEqual(result["elev_deg"], 25)
        self.assertGreater(result["iou"], 0.995)
        comparison = compare_model(reference, self.solids, -60, 25, size=64, mirror=False)
        self.assertTrue(comparison["passed"], comparison)

    def test_report_separates_measurement_fit_and_unobserved_geometry(self):
        reference = render_mask(self.solids, -60, 25, size=64)
        rgb = np.full((*reference.shape, 3), 255, dtype=np.uint8)
        rgb[reference] = (40, 40, 40)
        result = report(rgb, self.solids, azim=(-60,), elev=(25,), refine=0, size=64)
        self.assertEqual(result["provenance"]["reference"], "measured_from_mask")
        self.assertEqual(result["provenance"]["camera"], "fitted_by_orthographic_silhouette")
        self.assertEqual(result["provenance"]["absolute_scale"], "unknown_without_reference_dimension")
        self.assertEqual(result["provenance"]["hidden_geometry"], "not_validated")
        self.assertTrue(any("недостаточно" in item for item in result["limitations"]))
        self.assertNotIn("готово", dict(result["advice"]))
        with self.assertRaisesRegex(ValueError, "azim"):
            report(rgb, self.solids, azim=[], elev=(25,), refine=0, size=64)


if __name__ == "__main__":
    unittest.main()
