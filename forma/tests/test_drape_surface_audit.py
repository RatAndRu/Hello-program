"""Диагностика соседних граней и разграничение движения и равновесия."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from forma.cloth_check import (_ADJACENT_INSET, _adjacent_intersections, self_intersections,
                               surface_intersections, triangle_intersections)
from forma.geometry import manifold_mesh
from forma.ops_interior import _drape_surface_contacts
from forma.run import build

try:
    import fcl
except ImportError:
    fcl = None


def fcl_mesh(vertices, faces):
    model = fcl.BVHModel()
    model.beginModel(len(vertices), len(faces))
    model.addSubModel(np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int32))
    model.endModel()
    return fcl.CollisionObject(model)


def fcl_triangle(triangle):
    return fcl_mesh(triangle, [[0, 1, 2]])


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

    def test_distinct_surfaces_find_crossing_coplanar_touch_and_miss(self):
        first = np.array([[[0, 0, 0], [2, 0, 0], [0, 2, 0]]], dtype=float)
        second = np.array([[[.4, .4, -1], [.4, .4, 1], [1.2, .4, 0]],
                           [[.2, .2, 0], [1, .2, 0], [.2, 1, 0]],
                           [[3, 3, 0], [4, 3, 0], [3, 4, 0]]], dtype=float)
        result = surface_intersections(first, second)
        self.assertTrue(result["complete"])
        self.assertEqual(result["pairs"], 2)
        reverse = surface_intersections(second, first)
        self.assertTrue(reverse["complete"])
        self.assertEqual(reverse["pairs"], 2)

    def test_distinct_surface_aabb_matches_brute_force(self):
        generator = np.random.default_rng(773)
        for _ in range(12):
            first = generator.normal(size=(17, 3, 3))
            second = generator.normal(size=(19, 3, 3)) + generator.uniform(-1.0, 1.0, size=3)
            brute = int(triangle_intersections(np.repeat(first, len(second), axis=0),
                                               np.tile(second, (len(first), 1, 1))).sum())
            result = surface_intersections(first, second)
            self.assertTrue(result["complete"])
            self.assertEqual(result["pairs"], brute)
            reverse = surface_intersections(second, first)
            self.assertTrue(reverse["complete"])
            self.assertEqual(reverse["pairs"], brute)

    def test_distinct_surface_limits_and_precision_are_not_success(self):
        first = np.array([[[0, 0, 0], [2, 0, 0], [0, 2, 0]]], dtype=float)
        second = np.array([[[.4, .4, -1], [.4, .4, 1], [1.2, .4, 0]]], dtype=float)
        self.assertFalse(surface_intersections(first, second, max_candidates=0)["complete"])
        self.assertFalse(surface_intersections(first, second, max_scan=0)["complete"])
        flat = np.array([[[0, 0, 0], [1, 0, 0], [2, 0, 0]]], dtype=float)
        result = surface_intersections(first, flat)
        self.assertFalse(result["complete"])
        self.assertEqual(result["degenerate"], 1)
        uncertain = np.array([[[1e10, 1e10, 0], [1e10 + 1, 1e10, 0],
                               [1e10, 1e10 + .000001, 0]]])
        self.assertFalse(surface_intersections(first, uncertain)["complete"])
        invalid = first.copy()
        invalid[0, 0, 0] = np.nan
        self.assertFalse(surface_intersections(invalid, second)["complete"])
        overflow = np.array([[[-1e308, 0, 0], [1e308, 0, 0], [0, 1, 0]]])
        self.assertFalse(surface_intersections(overflow, second)["complete"])
        self.assertFalse(_drape_surface_contacts([overflow], [second])["complete"])

    @unittest.skipIf(fcl is None, "FCL — необязательная независимая проверка")
    def test_distinct_surface_pairs_against_fcl(self):
        generator = np.random.default_rng(20261)

        def model(triangles):
            return fcl_mesh(triangles.reshape(-1, 3),
                            np.arange(3 * len(triangles), dtype=np.int32).reshape(-1, 3))

        for scale in (.001, 1., 1000.):
            for repeat in range(4):
                with self.subTest(scale=scale, repeat=repeat):
                    first = generator.normal(size=(40, 3, 3)) * scale
                    second = generator.normal(size=(45, 3, 3)) * scale
                    shift = generator.uniform(-10, 10, size=3) * scale
                    first += shift
                    second += shift
                    contacts = fcl.CollisionResult()
                    fcl.collide(model(first), model(second),
                                fcl.CollisionRequest(num_max_contacts=10_000, enable_contact=True), contacts)
                    independent = {(int(c.b1), int(c.b2)) for c in contacts.contacts}
                    result = surface_intersections(first, second)
                    self.assertTrue(result["complete"])
                    self.assertGreater(len(independent), 0)
                    self.assertEqual(result["pairs"], len(independent))

    def test_pairwise_surface_audit_checks_all_relevant_parts_and_limits(self):
        first = np.array([[[0, 0, 0], [2, 0, 0], [0, 2, 0]]], dtype=float)
        crossing = np.array([[[.4, .4, -1], [.4, .4, 1], [1.2, .4, 0]]], dtype=float)
        far = crossing + [100, 0, 0]
        result = _drape_surface_contacts([first, far, crossing])
        self.assertTrue(result["complete"])
        self.assertEqual(result["checks"], 1)
        self.assertEqual(result["pairs"], 1)
        supports = _drape_surface_contacts([first], [far, crossing])
        self.assertTrue(supports["complete"])
        self.assertEqual(supports["pairs"], 1)
        self.assertFalse(_drape_surface_contacts([first, crossing], max_checks=0)["complete"])
        self.assertFalse(_drape_surface_contacts([first], [crossing], max_scan=0)["complete"])
        self.assertFalse(_drape_surface_contacts([first], [crossing], max_candidates=0)["complete"])
        self.assertFalse(_drape_surface_contacts([first], [np.zeros((0, 3, 3))])["complete"])

    def test_small_support_crossing_without_vertex_contact_is_not_success(self):
        template = """
опора = box size=[1,20,1] at=[0,0,0]
тело = box size=[20,1,1] at=[0,0,{height}]
итог = drape тело on=опора g=0 gap=0 rigid=1 mesh=50 particles=200 steps=2 self=нет
"""
        for height, expect_pairs, expect_pass in ((.99995, True, False),
                                                   (1., True, False),
                                                   (1.01, False, True)):
            with self.subTest(height=height):
                result = build(template.format(height=height), analyze_model=False)
                self.assertTrue(result.ok, str(result.error))
                meta = result.scene.objects["итог"].meta["cloth"]
                self.assertEqual(bool(meta["support_surface_pairs"]), expect_pairs)
                self.assertTrue(meta["support_surface_complete"])
                self.assertEqual(meta["geometry_checks_passed"], expect_pass)
                self.assertEqual(meta["penetration"], 0.)  # проверка вершин ничего не нашла
                if height == .99995:
                    self.assertGreater(meta["support_overlap_volume"], 0.)
                    self.assertLess(meta["support_overlap_volume"], 1e-4)
                    self.assertTrue(any("положительный объём пересечения с опорами" in item["message"]
                                        for item in result.scene.logs))
                    if fcl is not None:
                        body = manifold_mesh(result.scene.objects["итог"].manifold)
                        support = manifold_mesh(result.scene.objects["опора"].manifold)
                        contacts = fcl.CollisionResult()
                        self.assertGreater(fcl.collide(fcl_mesh(*body), fcl_mesh(*support),
                                                      fcl.CollisionRequest(num_max_contacts=1), contacts), 0)
                if height == 1.:
                    # Точное касание разрешено физически, но поверхностный тест
                    # не может надёжно отличить его от проникновения.
                    self.assertEqual(meta["support_overlap_volume"], 0.)
                    self.assertTrue(any("не отличает допустимое касание" in item["message"]
                                        for item in result.scene.logs))

    def test_fully_contained_small_part_is_not_missed_by_volume_threshold(self):
        source = """
опора = box size=[20,20,20] at=[0,0,0]
тело = box size=[0.02,0.02,0.02] at=[0,0,10]
итог = drape тело on=опора g=0 gap=0 rigid=1 mesh=50 particles=200 steps=2 self=нет
"""
        result = build(source, analyze_model=False)
        self.assertTrue(result.ok, str(result.error))
        meta = result.scene.objects["итог"].meta["cloth"]
        self.assertTrue(meta["support_surface_complete"])
        self.assertEqual(meta["support_surface_pairs"], 0)  # поверхности не пересекаются
        self.assertGreater(meta["support_overlap_volume"], 0.)
        self.assertLess(meta["support_overlap_volume"], 1e-4)
        self.assertFalse(meta["geometry_checks_passed"])

    def test_small_overlap_of_different_parts_is_not_success(self):
        source = """
пол = box size=[80,80,1] at=[0,0,-30]
первый = box size=[1,20,1] at=[0,0,0]
второй = box size=[20,1,1] at=[0,0,0.99995]
итог = drape [первый,второй] on=пол g=0 gap=0 rigid=0 mesh=50 particles=200 steps=2 self=да self_gap=0.02
"""
        # Имитируем пропущенный решателем контакт, чтобы проверить именно аудит.
        with patch("forma.cloth.SurfaceContacts.project", return_value=(0, 0)):
            result = build(source, analyze_model=False)
        self.assertTrue(result.ok, str(result.error))
        meta = result.scene.objects["итог"].meta["cloth"]
        self.assertTrue(meta["parts_surface_checked"])
        self.assertTrue(meta["parts_surface_complete"])
        self.assertGreater(meta["parts_surface_pairs"], 0)
        self.assertGreater(meta["parts_overlap_volume"], 0.)
        self.assertLess(meta["parts_overlap_volume"], 1e-4)
        self.assertFalse(meta["geometry_checks_passed"])

    def test_surface_budget_exhaustion_is_not_success(self):
        source = """
опора = box size=[1,20,1] at=[0,0,0]
тело = box size=[20,1,1] at=[0,0,0.99995]
итог = drape тело on=опора g=0 gap=0 rigid=1 mesh=50 particles=200 steps=2 self=нет
"""
        incomplete = {"pairs": 0, "checks": 0, "candidates": 0, "scanned": 0,
                      "degenerate": 0, "uncertain": 0, "complete": False}
        with patch("forma.ops_interior._drape_surface_contacts", return_value=incomplete):
            result = build(source, analyze_model=False)
        self.assertTrue(result.ok, str(result.error))
        meta = result.scene.objects["итог"].meta["cloth"]
        self.assertFalse(meta["support_surface_complete"])
        self.assertFalse(meta["geometry_checks_passed"])
        self.assertTrue(any("проверка граней детали и опор не завершена" in item["message"]
                            for item in result.scene.logs))

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
