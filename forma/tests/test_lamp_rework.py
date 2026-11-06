"""Minimal repro'ы для бюджета микрофасок и размерных зависимостей."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forma.geometry import manifold_mesh  # noqa: E402
from forma.run import build  # noqa: E402


class FlatCapTriangulationTests(unittest.TestCase):
    def test_cylinder_caps_have_no_high_valence_pole(self):
        result = build("a = lathe points=[[0,0],[10,0],[10,20],[0,20]] segments=64",
                       analyze_model=False)
        self.assertTrue(result.ok, result.error)
        solid = result.scene.objects["a"].manifold
        verts, _ = manifold_mesh(solid)
        radial = np.linalg.norm(verts[:, :2], axis=1)
        for z in (0.0, 20.0):
            poles = np.count_nonzero((radial < 1e-7) & (np.abs(verts[:, 2] - z) < 1e-7))
            self.assertEqual(poles, 0, "плоская крышка не должна сходиться в центральный веер")
        self.assertLess(solid.num_tri(), 256)
        self.assertEqual(solid.status().name, "NoError")
        effective_segments = len(verts) // 2  # два кольца, pole-вершин больше нет
        expected_volume = (0.5 * effective_segments * 100
                           * math.sin(2 * math.pi / effective_segments) * 20)
        self.assertAlmostEqual(solid.volume(), expected_volume, delta=1.0)

    def test_banker_base_matches_revolve_but_not_its_pole_mesh(self):
        points = [[0,0],[78.003,0],[86.004,1.224],[90,3.74],[90,13.6],
                  [89.55,16.66],[87.75,18.7],[84.6,21.08],[81,24.48],
                  [76.5,29.24],[71.1,34.68],[63.9,40.8],[55.8,46.92],
                  [46.8,52.36],[37.8,57.12],[30.6,61.2],[26.1,64.6],
                  [24.75,68],[0,68]]
        source = "a = lathe points=" + repr(points).replace(" ", "") + " segments=64"
        result = build(source, analyze_model=False)
        self.assertTrue(result.ok, result.error)
        solid = result.scene.objects["a"].manifold
        reference = mf.Manifold.revolve(mf.CrossSection([np.asarray(points, dtype=float)]), 64)
        self.assertEqual(solid.status().name, "NoError")
        self.assertAlmostEqual(solid.volume(), reference.volume(),
                               delta=max(1.0, reference.volume() * 1e-5))
        for actual, expected in zip(solid.bounding_box(), reference.bounding_box()):
            self.assertAlmostEqual(actual, expected, delta=2e-5)
        self.assertLess(solid.num_tri(), reference.num_tri())
        verts, _ = manifold_mesh(solid)
        radial = np.linalg.norm(verts[:, :2], axis=1)
        for z in (0.0, 68.0):
            self.assertFalse(np.any((radial < 1e-7) & (np.abs(verts[:, 2] - z) < 1e-7)))


class FilletBudgetTests(unittest.TestCase):
    def test_dense_profile_does_not_multiply_micro_arcs(self):
        # Плавная дуга уже дискретизирована: фаска не должна добавлять
        # минимум восемь отрезков на каждом её sample перед revolve.
        count = 24
        points = ([[0, 0], [30, 0], [30, 10]]
                  + [[30 + 10 * math.cos(math.pi * i / count),
                      10 + 10 * math.sin(math.pi * i / count)]
                     for i in range(1, count + 1)] + [[0, 20]])
        source = "a = lathe points=" + repr(points).replace(" ", "") \
            + " segments=32 fillet=0.2"
        normal = build(source, analyze_model=False)
        detailed = build(source + " fillet_angle=0 fillet_steps=8", analyze_model=False)
        self.assertTrue(normal.ok, normal.error)
        self.assertTrue(detailed.ok, detailed.error)
        normal_tris = normal.scene.objects["a"].manifold.num_tri()
        detailed_tris = detailed.scene.objects["a"].manifold.num_tri()
        self.assertLess(normal_tris, 5_000)
        self.assertGreater(detailed_tris, normal_tris)
        self.assertEqual(normal.scene.objects["a"].manifold.status(),
                         detailed.scene.objects["a"].manifold.status())

    def test_arc_budget_still_controls_real_fillet(self):
        source = ("a = lathe points=[[0,0],[30,0],[30,30],[0,30]] "
                  "segments=32 fillet=5 fillet_angle=0 fillet_steps=")
        coarse = build(source + "2", analyze_model=False)
        fine = build(source + "8", analyze_model=False)
        self.assertTrue(coarse.ok, coarse.error)
        self.assertTrue(fine.ok, fine.error)
        a = coarse.scene.objects["a"].manifold
        b = fine.scene.objects["a"].manifold
        self.assertLess(a.num_tri(), b.num_tri())
        self.assertEqual(a.bounding_box(), b.bounding_box())
        self.assertGreater(a.volume(), 0.0)
        self.assertGreater(b.volume(), a.volume())


class DerivedDimensionTests(unittest.TestCase):
    def test_rebuild_ignores_stale_derived_override(self):
        script = """base_h = 20
column_h = derive base_h * 1.5
column_top = derive base_h + column_h
base = box size=[20,20,base_h]
column = box size=[10,10,column_h] at=[0,0,base_h]
"""
        result = build(script, analyze_model=False,
                       overrides={"base_h": 30, "column_h": 999, "column_top": 999})
        self.assertTrue(result.ok, result.error)
        scene = result.scene
        self.assertEqual(scene.params["column_h"], 45.0)
        self.assertEqual(scene.params["column_top"], 75.0)
        self.assertEqual(scene.objects["column"].manifold.bounding_box()[5], 75.0)
        self.assertEqual(len(scene.dimension_links), 2)
        schema = {item["name"]: item for item in scene.parameter_schema()}
        self.assertTrue(schema["column_h"]["derived"])
        self.assertTrue(schema["column_h"]["read_only"])
        self.assertEqual(schema["column_h"]["default"], 30.0)


if __name__ == "__main__":
    unittest.main()
