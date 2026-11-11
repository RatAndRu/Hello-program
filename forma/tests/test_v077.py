"""Проверки сетки, диагностики и двух испытательных сцен драпировки.

Для независимой проверки поверхностей используется python-fcl, если он
установлен. Тесты сцен проверяют геометрию и предупреждения, но не объявляют
несошедшийся расчёт окончательным физическим равновесием.
"""
from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import manifold3d as mf
import numpy as np

from forma import cloth
from forma.cloth_check import self_intersections, triangle_intersections
from forma.geometry import manifold_mesh
from forma.ops_interior import _drape_support_intersections
from forma.run import build

try:
    import fcl
except ImportError:
    fcl = None

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "drape_atelier_077.forma"
DENSE = ROOT / "examples" / "drape_atelier_dense_077.forma"


def build_ok(source):
    result = build(source, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"Сцена не собралась: {result.error}")
    return result


def fcl_object(vertices, faces):
    model = fcl.BVHModel()
    model.beginModel(len(vertices), len(faces))
    model.addSubModel(np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int32))
    model.endModel()
    return fcl.CollisionObject(model)


def fcl_self_pairs(vertices, faces, limit=300_000):
    obj = fcl_object(vertices, faces)
    result = fcl.CollisionResult()
    fcl.collide(obj, obj, fcl.CollisionRequest(num_max_contacts=limit, enable_contact=True), result)
    if len(result.contacts) >= limit:
        raise AssertionError("FCL: исчерпан лимит контактов, проверка не завершена")
    return {(int(c.b1), int(c.b2)) for c in result.contacts
            if 0 <= c.b1 < c.b2 and not set(faces[c.b1]).intersection(faces[c.b2])}


class QuadMeshingTest(unittest.TestCase):
    def test_opposite_winding_uses_same_diagonal(self):
        vertices = np.array([[-1, 0, 0], [0, 2, 0], [1, 0, 0]], dtype=float)
        first = np.array([[0, 1, 2]], dtype=np.int64)
        v1, f1 = cloth._refine_long(vertices, first, 2.1)
        v2, f2 = cloth._refine_long(vertices, first[:, ::-1], 2.1)
        def triangles(v, f):
            return {tuple(sorted(tuple(np.round(x, 8)) for x in v[face])) for face in f}
        self.assertEqual(triangles(v1, f1), triangles(v2, f2))

    def test_sheet_sides_match_and_preserve_geometry(self):
        original, original_faces = manifold_mesh(mf.Manifold.cube((60, 48, .6)))
        vertices, faces = cloth.subdivide_to(original, original_faces, 7.0, 1200)
        self.assertTrue(cloth.is_closed(faces))
        self.assertLessEqual(len(vertices), 1200)
        self.assertEqual(len(np.unique(faces)), len(vertices))
        np.testing.assert_allclose(vertices.min(axis=0), original.min(axis=0), atol=1e-7)
        np.testing.assert_allclose(vertices.max(axis=0), original.max(axis=0), atol=1e-7)
        before, _ = cloth._volume_data(original, original_faces)
        after, _ = cloth._volume_data(vertices, faces)
        self.assertAlmostEqual(before, after, delta=1e-3)
        pairs, _ = cloth.shell_pairs(vertices, faces, cloth._thickness_of(vertices, faces))
        self.assertEqual(2 * len(pairs), len(vertices))
        other = np.full(len(vertices), -1, dtype=np.int64)
        other[pairs[:, 0]] = pairs[:, 1]
        other[pairs[:, 1]] = pairs[:, 0]
        lookup = {tuple(face) for face in np.sort(faces, axis=1)}
        top = np.all(np.isclose(vertices[faces, 2], .6, atol=1e-6), axis=1)
        self.assertGreater(int(top.sum()), 200)
        for mirrored in np.sort(other[faces[top]], axis=1):
            self.assertIn(tuple(mirrored), lookup)

    def test_budget_warning_reports_actual_resolution(self):
        vertices, faces = manifold_mesh(mf.Manifold.cube((200, 200, .4)))
        refined, refined_faces = cloth.subdivide_to(vertices, faces, 1.0, 500)
        self.assertLessEqual(len(refined), 500)
        self.assertTrue(cloth.is_closed(refined_faces))
        edges = cloth._edge_arrays(refined_faces)
        largest = np.linalg.norm(refined[edges[:, 1]] - refined[edges[:, 0]], axis=1).max()
        self.assertGreater(largest, 1.0)
        result = build_ok("""
пол = box size=[300,300,10] at=[0,0,-10]
лист = box size=[200,200,0.4] at=[0,0,30]
итог = drape лист on=пол mesh=1 particles=500 steps=1
""")
        meta = result.scene.objects["итог"].meta["cloth"]
        self.assertFalse(meta["mesh_complete"])
        self.assertGreater(meta["mesh_max_edge"], meta["mesh"])
        self.assertTrue(any(log["level"] == "warn" and "бюджет сетки" in log["message"]
                            for log in result.scene.logs))

    def test_dense_sleeve_has_closed_mesh_and_paired_walls(self):
        result = build_ok("рукав = pipe length=70 diameter=22 wall=0.6 sides=64")
        original, faces = manifold_mesh(result.scene.objects["рукав"].manifold)
        vertices, faces = cloth.subdivide_to(original, faces, 6, 5000)
        self.assertGreater(len(original), 64)
        self.assertGreater(len(faces), 4000)
        self.assertTrue(cloth.is_closed(faces))
        pairs, _ = cloth.shell_pairs(vertices, faces, cloth._thickness_of(vertices, faces))
        self.assertGreaterEqual(2 * len(pairs), .95 * len(vertices))


class SupportAndConvergenceTest(unittest.TestCase):
    def test_contact_distance_uses_edges_not_infinite_plane(self):
        tri = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], dtype=float)
        field = cloth.SupportField(tri, 10)
        points = np.array([[2, 2, .1], [.25, .25, -.1], [.25, .25, 0], [2, 2, 0]])
        distance, closest, normal = field.closest(points)
        self.assertAlmostEqual(distance[0], np.linalg.norm([1.5, 1.5, .1]))
        self.assertAlmostEqual(distance[1], -.1)
        self.assertAlmostEqual(distance[2], 0.0)
        self.assertAlmostEqual(distance[3], np.sqrt(4.5))
        np.testing.assert_allclose(closest[0], [.5, .5, 0], atol=1e-12)
        np.testing.assert_allclose(normal[1:3], [[0, 0, 1], [0, 0, 1]], atol=1e-12)

    def test_signed_distance_matches_box_near_faces_edges_corners(self):
        vertices, faces = manifold_mesh(mf.Manifold.cube((10, 10, 10)))
        points = np.random.default_rng(42).uniform(-2, 12, size=(1000, 3))
        q = np.abs(points - 5) - 5
        expected = np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(np.max(q, axis=1), 0)
        distance, _closest, _normal = cloth.SupportField(vertices[faces], 4).closest(points)
        np.testing.assert_allclose(distance, expected, atol=1e-9)

    def test_slow_freefall_is_not_reported_as_equilibrium(self):
        vertices = np.array([[0, 0, 10], [10, 0, 10], [0, 10, 10]], dtype=float)
        faces = np.array([[0, 1, 2]], dtype=np.int64)
        report = cloth.simulate(vertices, faces, None, gravity=np.array([0, 0, -1.]),
                                g=.001, steps=20, iterations=3, damping=.2,
                                bend=0, rigid=0, self_collision=False)
        self.assertFalse(report["converged"])
        self.assertEqual(report["steps"], 20)
        self.assertLess(report["movement_tolerance"], report["last_motion"])
        self.assertLess(report["vertices"][0, 2], 9.98)

    def test_step_count_includes_stability_checks(self):
        vertices = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], dtype=float)
        faces = np.array([[0, 1, 2]], dtype=np.int64)
        report = cloth.simulate(vertices, faces, None, gravity=np.zeros(3),
                                g=0, steps=20, iterations=3, bend=0, rigid=0,
                                self_collision=False, stable_steps=4)
        self.assertTrue(report["converged"])
        self.assertEqual(report["steps"], 4)

    def test_zero_gravity_does_not_teleport_body_to_support(self):
        body_vertices, body_faces = manifold_mesh(
            mf.Manifold.cube((20, 20, 20), True).translate((0, 0, 35)))
        support_vertices, support_faces = manifold_mesh(
            mf.Manifold.cube((150, 150, 10), True).translate((0, 0, -5)))
        report = cloth.simulate(body_vertices, body_faces, support_vertices[support_faces],
                                gravity=np.array([0, 0, -1.]), g=0, steps=20,
                                iterations=5, rigid=1, self_collision=False)
        np.testing.assert_allclose(report["vertices"], body_vertices, atol=1e-10)

    def test_explicit_pin_selects_group_nearest_not_each_part(self):
        result = build_ok("""
пол = box size=[200,100,10] at=[0,0,-10]
левый = box size=[10,10,10] at=[-30,0,30]
правый = box size=[10,10,10] at=[30,0,30]
итог = drape [левый,правый] on=пол pins=[[-35,-5,30]] pin_radius=0.01 rigid=1 mesh=12 particles=200 steps=8 constraints=4 g=0.1 self=нет
""")
        meta = result.scene.objects["итог"].meta["cloth"]
        self.assertEqual(meta["pinned"], 1)
        vertices, _faces = manifold_mesh(result.scene.objects["итог"].manifold)
        self.assertLess(np.min(np.linalg.norm(vertices - [-35, -5, 30], axis=1)), 1e-6)
        right_before = result.scene.objects["правый"].manifold.bounding_box()
        right_after = result.scene.objects["итог.02"].manifold.bounding_box()
        self.assertLess(right_after[5], right_before[5] - 0.1)

    def test_pins_keep_world_coordinates_for_different_gravity_axes(self):
        body, faces = manifold_mesh(mf.Manifold.cube((30, 30, .6), True).translate((0, 0, 30)))
        body, faces = cloth.subdivide_to(body, faces, 8, 400)
        support, support_faces = manifold_mesh(
            mf.Manifold.cube((150, 150, 10), True).translate((0, 0, -5)))
        pinned = np.isclose(body[:, 0], body[:, 0].min())
        for direction in ([0, 0, -1.], [1., 0, 0], [0, 1., 0]):
            with self.subTest(direction=direction):
                report = cloth.simulate(body, faces, support[support_faces],
                                        gravity=np.asarray(direction), g=.1, steps=8,
                                        iterations=6, thickness=.6, pinned=pinned,
                                        rigid=0, self_collision=False)
                np.testing.assert_array_equal(report["vertices"][pinned], body[pinned])
                self.assertGreater(np.max(np.linalg.norm(
                    report["vertices"][~pinned] - body[~pinned], axis=1)), .01)

    def test_stress_free_wall_remains_at_rest_without_external_forces(self):
        tube = build_ok("рукав = pipe length=24 diameter=12 wall=0.6 sides=16")
        shapes = [mf.Manifold.cube((40, 40, .6), True).translate((0, 0, 30)),
                  mf.Manifold.cube((40, 40, .6), True).rotate((29, 37, 13)).translate((3, -8, 30)),
                  tube.scene.objects["рукав"].manifold]
        for shape in shapes:
            vertices, faces = manifold_mesh(shape)
            vertices, faces = cloth.subdivide_to(vertices, faces, 8, 800)
            for self_collision in (False, True):
                with self.subTest(shape=shape.bounding_box(), self_collision=self_collision):
                    report = cloth.simulate(vertices, faces, None, gravity=np.zeros(3),
                                            g=0, steps=5, iterations=8, rigid=0,
                                            thickness=.6, self_collision=self_collision)
                    self.assertGreater(report["shell"], 0)
                    np.testing.assert_allclose(report["vertices"], vertices, rtol=0, atol=1e-10)
                    self.assertLess(report["strain_all"], 1e-10)


class IndependentChecksTest(unittest.TestCase):
    def test_triangle_cross_coplanar_and_miss(self):
        first = np.array([[[0, 0, 0], [2, 0, 0], [0, 2, 0]]] * 3, dtype=float)
        other = np.array([[[.4, .4, -1], [.4, .4, 1], [1.2, .4, 0]],
                          [[.2, .2, 0], [1, .2, 0], [.2, 1, 0]],
                          [[3, 3, 0], [4, 3, 0], [3, 4, 0]]], dtype=float)
        np.testing.assert_array_equal(triangle_intersections(first, other), [True, True, False])
        vertices = np.vstack((first[0], other[0]))
        faces = np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64)
        report = self_intersections(vertices, faces)
        self.assertEqual(report["pairs"], 1)
        self.assertTrue(report["complete"])
        self.assertFalse(self_intersections(vertices, faces, max_candidates=0)["complete"])
        collapsed = self_intersections(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]]),
                                       np.array([[0, 1, 2]]))
        self.assertEqual(collapsed["degenerate"], 1)
        self.assertFalse(collapsed["complete"])
        if fcl is not None:
            self.assertEqual(len(fcl_self_pairs(vertices, faces)), 1)

    def test_adjacent_faces_are_not_reported_as_intersecting(self):
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=float)
        faces = np.array([[0, 1, 2], [1, 3, 2]])
        report = self_intersections(vertices, faces)
        self.assertEqual(report["pairs"], 0)
        self.assertTrue(report["complete"])

    def test_support_boolean_and_limit(self):
        body = mf.Manifold.cube((5, 5, 5))
        volume, checked, complete = _drape_support_intersections([body], [body.translate((1, 0, 0))])
        self.assertAlmostEqual(volume, 100.0)
        self.assertEqual(checked, 1)
        self.assertTrue(complete)
        _volume, checked, complete = _drape_support_intersections([body], [body], max_checks=0)
        self.assertEqual(checked, 0)
        self.assertFalse(complete)

    def test_dense_rigid_sphere_does_not_repel_itself(self):
        prefix = """
пол = box size=[150,100,6] at=[0,0,-6]
шар = sphere radius=18 segments=96 detail=5 at=[0,0,55]
"""
        on = build_ok(prefix + "итог = drape шар on=пол mesh=5 steps=100 constraints=20 g=0.05 damping=0.3 self=да")
        off = build_ok(prefix + "итог = drape шар on=пол mesh=5 steps=100 constraints=20 g=0.05 damping=0.3 self=нет")
        a, b = on.scene.objects["итог"], off.scene.objects["итог"]
        self.assertGreater(len(manifold_mesh(a.manifold)[1]), 3000)
        self.assertEqual(a.meta["cloth"]["self_pairs"], 0)
        self.assertLess(a.meta["cloth"]["max_strain_all"], .05)
        self.assertLess(a.meta["cloth"]["support_overlap_volume"], 1e-4)
        np.testing.assert_allclose(a.manifold.bounding_box(), b.manifold.bounding_box(), atol=1e-6)
        self.assertAlmostEqual(a.manifold.volume(), b.manifold.volume(), delta=1e-5)

    def test_unsafe_surface_visible_in_log_and_metadata(self):
        script = """
пол = box size=[80,80,8] at=[0,0,-8]
лист = box size=[20,20,0.6] at=[0,0,10]
итог = drape лист on=пол mesh=8 steps=2
"""
        found = {"pairs": 2, "candidates": 9, "degenerate": 0, "complete": True}
        with patch("forma.ops_interior.self_intersections", return_value=found):
            result = build_ok(script)
        meta = result.scene.objects["итог"].meta["cloth"]
        self.assertEqual(meta["self_intersections"], 2)
        self.assertTrue(any(log["level"] == "warn" and "несоседних граней" in log["message"]
                            for log in result.scene.logs))


class ExampleScenesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normal = build_ok(EXAMPLE.read_text(encoding="utf-8"))
        cls.dense = build_ok(DENSE.read_text(encoding="utf-8"))

    def test_flat_layers_and_no_egg_carton(self):
        for result in (self.normal, self.dense):
            with self.subTest(example=result):
                low = result.scene.objects["слои"].manifold
                high = result.scene.objects["слои.02"].manifold
                self.assertLess(abs(float((low ^ high).volume())), 1e-4)
                vertices, _faces = manifold_mesh(high)
                b = high.bounding_box()
                region = ((np.abs(vertices[:, 0] + 234) < 20) & (np.abs(vertices[:, 1]) < 15) &
                          (vertices[:, 2] > (b[2] + b[5]) * .5))
                self.assertGreater(int(region.sum()), 10)
                z = vertices[region, 2]
                self.assertLess(float(np.percentile(z, 95) - np.percentile(z, 5)), .04)
                meta = result.scene.objects["слои"].meta["cloth"]
                self.assertTrue(meta["self_intersections_complete"])
                self.assertEqual(meta["self_intersections"], 0)
                self.assertTrue(meta["parts_overlap_complete"])

    def test_sleeve_density_and_unsettled_warning(self):
        normal = self.normal.scene.objects["упавший_рукав"].manifold
        dense = self.dense.scene.objects["упавший_рукав"].manifold
        _v1, f1 = manifold_mesh(normal)
        _v2, f2 = manifold_mesh(dense)
        self.assertGreater(len(f2), 3 * len(f1))
        for result in (self.normal, self.dense):
            with self.subTest(example=result):
                initial = result.scene.objects["рукав"].manifold
                sleeve = result.scene.objects["упавший_рукав"].manifold
                self.assertGreater(sleeve.volume() / initial.volume(), .9)
                meta = result.scene.objects["упавший_рукав"].meta["cloth"]
                self.assertTrue(meta["self_intersections_complete"])
                self.assertEqual(meta["self_intersections"], 0)
                if not meta["converged"]:
                    self.assertTrue(any("равновесие не подтверждено" in log["message"]
                                        for log in result.scene.logs))
        # Эта проверка показывает именно ограниченность плотного примера:
        # почти круглая трубка не должна подаваться как равновесная.
        meta = self.dense.scene.objects["упавший_рукав"].meta["cloth"]
        b0 = self.dense.scene.objects["рукав"].manifold.bounding_box()
        b1 = dense.bounding_box()
        if b1[5] - b1[2] > .8 * (b0[5] - b0[2]):
            self.assertFalse(meta["converged"])

    def test_ball_and_hanging_edges_are_actual_geometry(self):
        for result in (self.normal, self.dense):
            with self.subTest(example=result):
                ball = result.scene.objects["упавший_шар"]
                self.assertGreater(ball.meta["cloth"]["rigid"], .9)
                self.assertGreater(ball.manifold.volume() / result.scene.objects["шар"].manifold.volume(), .98)
                tablecloth = result.scene.objects["скатерть"]
                vertices, _faces = manifold_mesh(tablecloth.manifold)
                center = (np.abs(vertices[:, 0] - 150) < 25) & (np.abs(vertices[:, 1]) < 25)
                edge = (np.abs(vertices[:, 0] - 150) > 50) | (np.abs(vertices[:, 1]) > 50)
                self.assertGreater(float(np.median(vertices[center, 2]) - np.median(vertices[edge, 2])), 5)
                meta = tablecloth.meta["cloth"]
                self.assertTrue(meta["self_intersections_complete"])
                self.assertEqual(meta["self_intersections"], 0)
                self.assertTrue(meta["support_overlap_complete"])
                self.assertLess(meta["support_overlap_volume"], 1e-4)

    @unittest.skipIf(fcl is None, "python-fcl — дополнительная независимая проверка")
    def test_independent_fcl_checks_both_scenes(self):
        for result in (self.normal, self.dense):
            for name in ("слои", "слои.02", "упавший_рукав", "упавший_шар", "скатерть"):
                with self.subTest(scene=result, object=name):
                    vertices, faces = manifold_mesh(result.scene.objects[name].manifold)
                    self.assertFalse(fcl_self_pairs(vertices, faces))
            cloth_mesh = manifold_mesh(result.scene.objects["скатерть"].manifold)
            table_mesh = manifold_mesh(result.scene.objects["столешница"].manifold)
            result_fcl = fcl.CollisionResult()
            count = fcl.collide(fcl_object(*cloth_mesh), fcl_object(*table_mesh),
                                fcl.CollisionRequest(num_max_contacts=1), result_fcl)
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
