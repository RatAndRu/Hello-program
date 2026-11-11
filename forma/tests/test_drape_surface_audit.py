"""Диагностика соседних граней и разграничение движения и равновесия."""
from __future__ import annotations

import unittest

import numpy as np

from forma.cloth_check import _ADJACENT_INSET, _adjacent_intersections, self_intersections
from forma.run import build

try:
    import fcl
except ImportError:
    fcl = None


def fcl_triangle(triangle):
    model = fcl.BVHModel()
    model.beginModel(3, 1)
    model.addSubModel(np.asarray(triangle, dtype=float), np.array([[0, 1, 2]], dtype=np.int32))
    model.endModel()
    return fcl.CollisionObject(model)


class SurfaceAuditTest(unittest.TestCase):
    def test_neighbouring_faces_contact_and_crossing(self):
        cases = (
            # Общая кромка допустима.
            ([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, -2, 0]],
             [[0, 1, 2], [1, 0, 3]], 0),
            # Две грани с общей кромкой перекрываются за её пределами.
            ([[0, 0, 0], [2, 0, 0], [0, 2, 0], [.5, 1, 0]],
             [[0, 1, 2], [1, 0, 3]], 1),
            # Общая вершина и действительное пересечение за ней.
            ([[0, 0, 0], [2, 0, 0], [0, 2, 0], [1, .5, -1], [1, .5, 1]],
             [[0, 1, 2], [0, 3, 4]], 1),
        )
        for vertices, faces, expected in cases:
            with self.subTest(expected=expected):
                result = self_intersections(vertices, faces)
                self.assertTrue(result["complete"])
                self.assertEqual(result["pairs"], 0)
                self.assertEqual(result["adjacent_pairs"], expected)

    def test_uncertainty_and_limits_do_not_claim_completeness(self):
        vertices = np.array([[10000, 10000, 0], [10000.001, 10000, 0],
                             [10000.0005, 10000.0000001, 0],
                             [10000.0005, 9999.9999, 0]], dtype=float)
        faces = np.array([[0, 1, 2], [1, 0, 3]], dtype=np.int64)
        result = self_intersections(vertices, faces)
        self.assertGreater(result["adjacent_uncertain"], 0)
        self.assertFalse(result["complete"])
        self.assertFalse(result["adjacent_complete"])
        self.assertFalse(self_intersections(vertices, faces, max_candidates=0)["complete"])

    def test_small_motion_is_not_verified_equilibrium(self):
        source = """
пол = box size=[80,80,8] at=[0,0,-8]
корпус = box size=[10,10,10] at=[0,0,20]
итог = drape корпус on=пол g=0 rigid=1 steps=20
"""
        result = build(source, analyze_model=False)
        self.assertTrue(result.ok, str(result.error))
        meta = result.scene.objects["итог"].meta["cloth"]
        self.assertTrue(meta["movement_stable"])
        self.assertFalse(meta["equilibrium_verified"])
        self.assertTrue(meta["geometry_checks_passed"])
        self.assertTrue(any("силы отдельно не проверялись" in item["message"] for item in result.scene.logs))

    @unittest.skipIf(fcl is None, "FCL — необязательная независимая проверка")
    def test_neighbouring_triangles_against_fcl(self):
        generator = np.random.default_rng(904)
        matched = 0
        for _ in range(500):
            vertices = generator.normal(size=(5, 3))
            first, second = vertices[[0, 1, 2]], vertices[[0, 3, 4]]
            hit, uncertain = _adjacent_intersections(first[None], second[None])
            if uncertain[0]:
                continue
            a = first + (first.mean(axis=0) - first) * _ADJACENT_INSET
            b = second + (second.mean(axis=0) - second) * _ADJACENT_INSET
            result = fcl.CollisionResult()
            fcl_hit = bool(fcl.collide(fcl_triangle(a), fcl_triangle(b),
                                       fcl.CollisionRequest(num_max_contacts=1), result))
            self.assertEqual(bool(hit[0]), fcl_hit)
            matched += 1
        self.assertGreater(matched, 450)


if __name__ == "__main__":
    unittest.main()
