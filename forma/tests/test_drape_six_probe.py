"""Проверка конструкции шести диагностических сценариев и отдельного опыта.

Эти тесты не объявляют приближённый решатель готовым или нерастяжимым.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest import mock

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
import drape_six_probe as probe  # noqa: E402
from drape_triangle_probe import TriangleSupportProbe  # noqa: E402
from forma import cloth  # noqa: E402
from forma.run import build  # noqa: E402

try:
    import fcl  # noqa: F401
except ImportError:
    fcl = None
try:
    import ipctk  # noqa: F401
except ImportError:
    ipctk = None


class FreezeXYProbeTest(unittest.TestCase):
    def test_horizontal_correction_preserves_height_and_can_restore_one_edge(self):
        position = np.array([[0., 0., 0.], [10., 0., -6.]])
        experiment = probe.FreezeXYProbe(strength=1.)
        experiment.planar(position, np.array([0]), np.array([1]), np.array([10.]),
                          np.array([True, True]), np.array([0., 0., -1.]))
        np.testing.assert_allclose(position, [[0., 0., 0.], [8., 0., -6.]], atol=1e-12)
        self.assertAlmostEqual(np.linalg.norm(position[1] - position[0]), 10.)

    def test_horizontal_motion_cannot_fix_excess_vertical_distance(self):
        position = np.array([[0., 0., 0.], [1., 0., -11.]])
        initial = position.copy()
        experiment = probe.FreezeXYProbe(strength=1.)
        experiment.planar(position, np.array([0]), np.array([1]), np.array([10.]),
                          np.array([True, True]), np.array([0., 0., -1.]))
        np.testing.assert_array_equal(position, initial)
        self.assertEqual(experiment.infeasible_observations, 1)

    def test_inward_only_cannot_fix_a_short_edge(self):
        position = np.array([[0., 0., 0.], [4., 0., -6.]])
        initial = position.copy()
        experiment = probe.FreezeXYProbe(strength=1.)
        experiment.planar(position, np.array([0]), np.array([1]), np.array([10.]),
                          np.array([True, True]), np.array([0., 0., -1.]))
        np.testing.assert_array_equal(position, initial)
        self.assertLess(np.linalg.norm(position[1] - position[0]), 10.)

    def test_rollback_freezes_the_contacted_free_vertex_at_its_previous_position(self):
        triangle = np.array([[[-5., -5., 0.], [5., -5., 0.], [0., 5., 0.]]])
        field = cloth.SupportField(triangle, 4.)
        previous = np.array([[0., 0., .3], [1., 0., .3]])
        current = np.array([[0., 0., -.1], [1., 0., -.1]])
        free = np.array([True, False])
        experiment = probe.FreezeXYProbe()
        experiment.setup(2)
        experiment.rollback(previous, current, free, field, 0.)
        np.testing.assert_allclose(current[0], previous[0])
        np.testing.assert_allclose(current[1], [1., 0., -.1])
        np.testing.assert_array_equal(experiment.frozen, [True, False])
        np.testing.assert_array_equal(free, [False, False])
        current[0] += [3., 4., 5.]
        experiment.restore(current)
        np.testing.assert_allclose(current[0], previous[0])

    def test_correction_is_horizontal_for_an_arbitrary_gravity_direction(self):
        position = np.array([[0., 0., 0.], [6., -10., 0.]])
        before = position.copy()
        gravity = np.array([1., 0., 0.])
        experiment = probe.FreezeXYProbe(strength=1.)
        experiment.planar(position, np.array([0]), np.array([1]), np.array([10.]),
                          np.array([True, True]), gravity)
        np.testing.assert_allclose(position[:, 0], before[:, 0])
        self.assertAlmostEqual(np.linalg.norm(position[1] - position[0]), 10.)


class SixScenarioProbeTest(unittest.TestCase):
    def test_six_different_sources_and_explicit_soft_sphere(self):
        self.assertEqual(len(probe.CASES), 6)
        paths = [probe.ROOT / case[0] for case in probe.CASES.values()]
        self.assertEqual(len(set(paths)), 6)
        self.assertTrue(all(path.is_file() for path in paths))
        sphere_script = paths[2].read_text(encoding="utf-8")
        self.assertIn("rigid=0", sphere_script)

    def test_rod_is_longitudinal_and_initially_inside_the_open_sleeve(self):
        path = probe.ROOT / probe.CASES["06_sleeve_around_rod"][0]
        script = path.read_text(encoding="utf-8").split("результат = drape", 1)[0]
        scene = build(script, analyze_model=False)
        self.assertTrue(scene.ok, scene.error)
        sleeve = scene.scene.objects["рукав"].manifold
        rod = scene.scene.objects["стержень"].manifold
        box = np.asarray(rod.bounding_box())
        self.assertGreater(box[3] - box[0], 4 * (box[4] - box[1]))
        self.assertAlmostEqual(float((sleeve ^ rod).volume()), 0.)
        self.assertLess(box[0], -25.)
        self.assertGreater(box[3], 25.)
        if fcl is not None:
            from audit_drape_sleeve import _fcl_object
            from forma.geometry import manifold_mesh
            first = _fcl_object(fcl, *manifold_mesh(sleeve))
            second = _fcl_object(fcl, *manifold_mesh(rod))
            distance = fcl.distance(first, second, fcl.DistanceRequest(), fcl.DistanceResult())
            self.assertGreater(distance, 4.)

    def test_current_instrumentation_does_not_change_the_solver(self):
        vertices = np.array([[-2., -2., 3.], [2., -2., 3.], [2., 2., 3.], [-2., 2., 3.]])
        faces = np.array([[0, 1, 2], [0, 2, 3]])
        supports = np.array([[[-10., -10., 0.], [10., -10., 0.], [10., 10., 0.]],
                             [[-10., -10., 0.], [10., 10., 0.], [-10., 10., 0.]]])
        kwargs = dict(gravity=np.array([0., 0., -1.]), steps=5, iterations=4,
                      self_collision=False, thickness=.2, gap=.05)
        expected = cloth.simulate(vertices, faces, supports, **kwargs)
        state = {}
        actual = probe._instrumented_solver("current", state, False)(vertices, faces, supports, **kwargs)
        np.testing.assert_array_equal(actual["vertices"], expected["vertices"])
        self.assertEqual(actual["steps"], expected["steps"])
        self.assertEqual(state["frames"], expected["steps"])
        self.assertGreater(len(state["placed"]), 0)

    def test_simple_flat_scene_measures_thickness_edges_and_glb(self):
        report = probe.run_case("02_sheet_over_sheet", check_glb=True,
                                with_fcl=fcl is not None, with_ccd=ipctk is not None)
        self.assertLess(report["visible_triangles"], 100_000)
        self.assertEqual(report["visible_triangles"], report["glb"]["triangles"])
        self.assertAlmostEqual(report["height_final_mm"], .6, delta=.002)
        self.assertLess(report["edges"]["max_abs_percent"], .01)
        self.assertIsNotNone(report["shell_pair_lengths"])
        self.assertTrue(report["metadata"]["converged"])
        self.assertFalse(report["metadata"]["equilibrium_verified"])
        if fcl is not None:
            self.assertFalse(report["fcl_by_support"]["площадка"]["contact_or_crossing"])
            self.assertEqual(report["fcl"]["nonadjacent_pairs"], 0)
        if ipctk is not None:
            self.assertTrue(report["ccd"]["completed"])
        json.dumps(report, ensure_ascii=False, allow_nan=False)

    def test_xy_experiment_is_isolated_and_rolls_back_contacts(self):
        original = cloth.simulate
        report = probe.run_case("02_sheet_over_sheet", mode="stop-xy")
        self.assertIs(cloth.simulate, original)
        self.assertGreater(report["stop_xy"]["frozen_vertices"], 0)
        self.assertFalse(report["metadata"]["equilibrium_verified"])
        self.assertAlmostEqual(report["height_final_mm"], .6, delta=.002)

    def test_solver_is_restored_when_build_fails(self):
        original = cloth.simulate
        with mock.patch.object(probe, "build", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError) as caught:
                probe.run_case("02_sheet_over_sheet")
        self.assertEqual(str(caught.exception), "test")
        self.assertIs(cloth.simulate, original)

    def test_wall_pair_length_can_hide_a_loss_of_normal_thickness(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.],
                              [0., 0., .6], [1., 0., .6], [0., 1., .6]])
        faces = np.array([[0, 2, 1], [3, 4, 5]])
        shell = np.array([[0, 3], [1, 4], [2, 5]])
        current = reference.copy()
        current[3:, 0] += .3
        current[3:, 2] = np.sqrt(.6 ** 2 - .3 ** 2)
        lengths = probe._ratios(reference, current, shell)
        normal = probe._wall_normal_projections(reference, current, faces, shell)
        self.assertLess(lengths["max_abs_percent"], 1e-10)
        self.assertTrue(normal["complete"])
        self.assertAlmostEqual(normal["min_ratio"], np.sqrt(.75), places=10)

    def test_tetra_probe_detects_a_flipped_cell_and_reports_changed_boundary(self):
        from forma.geometry import manifold_mesh
        scene = build("лист = box size=[8,8,0.6]", analyze_model=False)
        self.assertTrue(scene.ok, str(scene.error))
        vertices, faces = manifold_mesh(scene.scene.objects["лист"].manifold)
        vertices, faces = cloth.subdivide_to(vertices, faces, 4., 800)
        rest = probe._tetra_probe("04_tablecloth", vertices, vertices, faces)
        self.assertTrue(rest["available"])
        self.assertEqual(rest["inverted"], 0)
        self.assertGreater(rest["retriangulated_boundary_faces"], 0)
        changed = vertices.copy()
        top = np.flatnonzero(vertices[:, 2] > np.mean(vertices[:, 2]))
        changed[top[0], 2] = vertices[:, 2].min() - 1.
        flipped = probe._tetra_probe("04_tablecloth", vertices, changed, faces)
        self.assertGreater(flipped["inverted"], 0)
        self.assertLess(flipped["min_jacobian"], 0.)
        self.assertFalse(probe._tetra_probe("03_soft_sphere", vertices, vertices, faces)["available"])

    def test_triangle_probe_moves_only_free_vertices_outward(self):
        support = np.array([[[-5., -5., 0.], [5., -5., 0.], [0., 5., 0.]]])
        field = cloth.SupportField(support, 4.)
        position = np.array([[-.5, -.5, -.2], [.5, -.5, .3], [0., .5, .3]])
        fixed = position[2].copy()
        experiment = TriangleSupportProbe(field, np.array([[0, 1, 2]]), np.empty((0, 2), int))
        experiment.project(position, np.array([True, True, False]), rounds=4)
        np.testing.assert_array_equal(position[2], fixed)
        self.assertGreater(position[0, 2], 0.)
        self.assertGreater(experiment.applied_rounds, 0)
        self.assertFalse(experiment.budget_exceeded)


if __name__ == "__main__":
    unittest.main()
