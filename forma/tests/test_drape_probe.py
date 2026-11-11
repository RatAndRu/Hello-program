"""Проверка конструкции исследовательских сцен, не пригодности движка к выпуску."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(TOOLS))
import audit_drape_sleeve as audit  # noqa: E402
from audit_drape_evolution import _signed_tetra_volumes, capture  # noqa: E402
from drape_mujoco_probe import (TrajectoryAudit, changed_surface_distances, input_mesh, make_xml,
                                restart_from_rest, sampled_surface_distance, surface_samples,
                                tet_boundary, tetrahedral_shell)  # noqa: E402
from drape_tet_pbd_probe import VolumeProjector  # noqa: E402
from drape_shear_probe import ShearProjector, _check_ccd, build_shear_links  # noqa: E402
from drape_support_probe import SupportContactProbe  # noqa: E402
from forma import cloth  # noqa: E402

try:
    import mujoco
except ImportError:
    mujoco = None

try:
    import ipctk  # noqa: F401
except ImportError:
    ipctk = None


class DrapeProbeConstructionTest(unittest.TestCase):
    def test_signed_tetra_volumes_distinguish_inversion(self):
        vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
        tets = np.array([[0, 1, 2, 3], [1, 0, 2, 3]])
        np.testing.assert_allclose(_signed_tetra_volumes(vertices, tets), [1 / 6, -1 / 6])
        np.testing.assert_allclose(_signed_tetra_volumes(vertices + [20, -5, 7], tets), [1 / 6, -1 / 6])

    def test_experimental_volume_projection_leaves_rest_and_pins_unchanged(self):
        reference = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]])
        tets = np.array([[0, 1, 2, 3]])
        free = np.array([False, True, True, True])
        supports = np.zeros(4, dtype=bool)
        for mode in ('lower', 'equal'):
            with self.subTest(mode=mode):
                projector = VolumeProjector(reference, tets, mode=mode)
                rest = reference.copy()
                projector.project(rest, free, supports)
                np.testing.assert_allclose(rest, reference)
                collapsed = reference.copy()
                collapsed[3, 2] = .05
                before = projector.measure(collapsed)['min_jacobian']
                projector.project(collapsed, free, supports)
                self.assertGreater(projector.measure(collapsed)['min_jacobian'], before)
                np.testing.assert_allclose(collapsed[0], reference[0])

    def test_shear_links_are_unique_pin_safe_and_rest_free(self):
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                             [0, 0, .1], [1, 0, .1], [0, 1, .1]], dtype=float)
        faces = np.array([[0, 1, 2], [5, 4, 3]], dtype=np.int64)
        shell = np.array([[0, 3], [1, 4], [2, 5]], dtype=np.int64)
        links = build_shear_links(vertices, faces, shell)
        self.assertEqual(len(links), 6)
        self.assertEqual(len({tuple(link) for link in links}), len(links))
        projector = ShearProjector(vertices, links)
        free = np.ones(len(vertices), dtype=bool)
        free[0] = False
        rest = vertices.copy()
        projector.project(rest, free)
        np.testing.assert_allclose(rest, vertices)
        moved = vertices.copy()
        moved[4, 0] += .2
        before = np.sum(np.abs(np.linalg.norm(moved[links[:, 1]] - moved[links[:, 0]], axis=1)
                               - projector.rest))
        projector.project(moved, free)
        after = np.sum(np.abs(np.linalg.norm(moved[links[:, 1]] - moved[links[:, 0]], axis=1)
                              - projector.rest))
        self.assertLess(after, before)
        np.testing.assert_array_equal(moved[0], vertices[0])
        with self.assertRaises(ValueError):
            build_shear_links(vertices, faces, np.array([[0, 3], [0, 4]]))

    def test_capture_records_actual_steps_without_changing_the_solver(self):
        source = '''пол = box size=[80,80,8] at=[0,0,-8]
корпус = box size=[10,10,10] at=[0,0,20]
итог = drape корпус on=пол g=0 rigid=1 steps=3
'''
        vertices, faces, history = capture(source, TOOLS.parent)
        self.assertEqual(len(history), 3)
        self.assertGreater(len(faces), 0)
        for frame in history:
            np.testing.assert_allclose(frame, vertices, atol=1e-9)

    def test_fcl_pair_count_is_independent_of_contact_order(self):
        faces = np.asarray([[0, 1, 2], [3, 4, 5], [6, 7, 8], [6, 9, 10]])
        vertices = np.zeros((11, 3))
        contacts = [[types.SimpleNamespace(b1=1, b2=0), types.SimpleNamespace(b1=0, b2=0)],
                    [types.SimpleNamespace(b1=3, b2=2)]]

        class Result:
            def __init__(self):
                self.contacts = []

        def collide(_a, _b, _request, result):
            if contacts:
                result.contacts = contacts.pop(0)
                return len(result.contacts)
            return 0

        fake = types.SimpleNamespace(CollisionResult=Result, CollisionRequest=lambda **_kwargs: None,
                                     collide=collide)
        with mock.patch.dict(sys.modules, {'fcl': fake}), mock.patch.object(audit, '_fcl_object'):
            result = audit._fcl_audit(vertices, faces, (vertices, faces))
        self.assertEqual(result['nonadjacent_pairs'], 1)
        self.assertEqual(result['adjacent_pairs_after_inset'], 1)

    def test_surface_distance_uses_edge_and_face_samples(self):
        vertices = np.array([[0., 0., 0.], [2., 0., 0.], [0., 2., 0.]])
        faces = np.array([[0, 1, 2]])
        samples = surface_samples(vertices, faces)
        self.assertEqual(len(samples), 7)
        self.assertAlmostEqual(sampled_surface_distance(samples, vertices, faces), 0., places=12)
        shifted = vertices + [0., 0., 0.2]
        self.assertAlmostEqual(sampled_surface_distance(samples, shifted, faces), .2, places=12)

    def test_changed_diagonal_in_bent_quad_changes_the_surface(self):
        vertices = np.array([[0., 0., 0.], [1., 0., 0.], [1., 1., .3], [0., 1., 0.]])
        source = np.array([[0, 1, 2], [0, 2, 3]])
        alternate = np.array([[0, 1, 3], [1, 2, 3]])
        same = changed_surface_distances(vertices, source, source)
        self.assertEqual(same['source_changed_faces'], 0)
        self.assertEqual(same['sampled_source_to_boundary_mm'], 0.)
        changed = changed_surface_distances(vertices, source, alternate)
        self.assertEqual(changed['source_changed_faces'], 2)
        self.assertEqual(changed['boundary_changed_faces'], 2)
        self.assertGreater(changed['sampled_source_to_boundary_mm'], .05)
        self.assertGreater(changed['sampled_boundary_to_source_mm'], .05)

    @unittest.skipIf(ipctk is None, 'ipctk — необязательный исследовательский инструмент')
    def test_ccd_catches_crossing_even_when_both_ends_are_separate(self):
        moving = np.array([[.1, .1, 1.], [.8, .1, 1.], [.1, .8, 1.]])
        fixed = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        faces = np.array([[0, 1, 2]])
        check = TrajectoryAudit(moving, faces, {'опора': (fixed, faces)})
        self.assertTrue(check.check(moving.copy()))
        self.assertIsNone(check.failed_segment)
        self.assertFalse(check.check(moving - [0., 0., 2.]))
        self.assertEqual(check.steps, 2)
        np.testing.assert_allclose(check.failed_segment[0][:3], moving)
        np.testing.assert_allclose(check.failed_segment[1][:3], moving - [0., 0., 2.])

    def test_support_probe_moves_face_for_static_vertices_and_respects_pins(self):
        vertices = np.array([[-2., -2., 1.], [2., -2., 1.], [0., 2., 1.]])
        faces = np.array([[0, 2, 1]], dtype=np.int64)  # нормаль смотрит к опоре
        support = np.array([[[0., 0., 0.], [.2, 0., 0.], [0., .2, 0.]]])
        probe = SupportContactProbe(vertices, faces, np.empty((0, 2), dtype=np.int64),
                                    np.zeros(3, dtype=np.int64), [0, 0, -1], support, .02)
        old = np.vstack((vertices, probe.static))
        moved = vertices - [0., 0., 1.2]
        current = np.vstack((moved, probe.static))
        owners, tids = probe.collider.candidates(old, current)
        self.assertTrue(np.any(owners >= len(vertices)))  # вершина опоры против грани
        self.assertTrue(np.all((owners < len(vertices)) !=
                               (probe.collider.faces[tids, 0] < len(vertices))))
        static_before = probe.static.copy()
        initial = moved.copy()
        found, _depth = probe.project(vertices, moved, np.ones(3, dtype=bool),
                                      np.zeros(3, dtype=bool), rounds=12)
        self.assertGreater(found, 0)
        self.assertGreater(float(moved[:, 2].mean()), float(initial[:, 2].mean()))
        np.testing.assert_array_equal(probe.static, static_before)
        pinned = initial.copy()
        probe.project(vertices, pinned, np.zeros(3, dtype=bool), np.zeros(3, dtype=bool), rounds=12)
        np.testing.assert_array_equal(pinned, initial)

    @unittest.skipIf(ipctk is None, 'ipctk — необязательный исследовательский инструмент')
    def test_support_probe_ccd_is_wired_to_each_step(self):
        command = [sys.executable, str(TOOLS / 'drape_support_probe.py'), '--steps', '1', '--ccd']
        run = subprocess.run(command, cwd=TOOLS.parent, text=True, encoding='utf-8',
                             capture_output=True, timeout=45)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(report['trajectory_ccd']['steps'], 1)
        self.assertEqual(report['trajectory_ccd']['min_distance_mm'], .005)
        self.assertEqual(report['passes'], 3)
        self.assertFalse(report['metadata']['equilibrium_verified'])

    @unittest.skipIf(ipctk is None, 'ipctk — необязательный исследовательский инструмент')
    def test_shear_ccd_saves_only_failing_segment(self):
        moving = np.array([[.1, .1, 1.], [.8, .1, 1.], [.1, .8, 1.]])
        fixed = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        faces = np.array([[0, 1, 2]])
        audit = TrajectoryAudit(moving, faces, {'опора': (fixed, faces)}, min_distance=.05)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'failed.npz'
            _check_ccd(audit, moving.copy(), path)
            self.assertFalse(path.exists())
            with self.assertRaisesRegex(RuntimeError, 'шага 2'):
                _check_ccd(audit, moving - [0., 0., 2.], path)
            self.assertTrue(path.is_file())
            with np.load(path) as saved:
                np.testing.assert_allclose(saved['start'][:3], moving)
                np.testing.assert_allclose(saved['end'][:3], moving - [0., 0., 2.])
                self.assertEqual(int(saved['dynamic_vertices']), 3)
                self.assertAlmostEqual(float(saved['min_distance']), .05)

    @unittest.skipIf(ipctk is None, 'ipctk — необязательный исследовательский инструмент')
    def test_shear_probe_ccd_is_wired_to_each_step(self):
        command = [sys.executable, str(TOOLS / 'drape_shear_probe.py'), '--steps', '1',
                   '--ccd', '--ccd-min-distance', '.005']
        run = subprocess.run(command, cwd=TOOLS.parent, text=True, encoding='utf-8',
                             capture_output=True, timeout=45)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual(report['trajectory_ccd']['steps'], 1)
        self.assertEqual(report['trajectory_ccd']['min_distance_mm'], .005)
        self.assertFalse(report['metadata']['equilibrium_verified'])

    def test_volume_layer_is_manifold_and_rest_volume_preserved(self):
        for case in ('sleeve', 'table'):
            with self.subTest(case=case):
                original, faces, _placed, _supports = input_mesh(case, 16)
                surface, tets, changed = tetrahedral_shell(case, original, faces)
                self.assertGreater(len(tets), 0)
                self.assertGreater(changed, 0)  # торцы пере-триангулированы
                self.assertTrue(cloth.is_closed(surface))
                reference, _ = cloth._volume_data(original, faces)
                reconstructed, _ = cloth._volume_data(original, surface)
                self.assertAlmostEqual(reference, reconstructed, delta=abs(reference) * 1e-8)
                points = original[tets]
                determinants = np.linalg.det(np.stack((points[:, 1] - points[:, 0],
                                                        points[:, 2] - points[:, 0],
                                                        points[:, 3] - points[:, 0]), axis=2))
                self.assertTrue(np.all(determinants > 0))
                self.assertAlmostEqual(float(determinants.sum() / 6), reference,
                                       delta=abs(reference) * 1e-8)

    @unittest.skipIf(mujoco is None or not mujoco.__version__.startswith('4.'),
                     'MuJoCo 4 — необязательный исследовательский инструмент')
    def test_manual_volume_nodes_include_and_weight_interior_nodes(self):
        outer = np.array([[0., 0., 2.], [1., 0., 2.], [0., 1., 2.], [0., 0., 3.]])
        vertices = np.vstack((outer, outer.mean(axis=0)))
        tets = np.array([[0, 1, 2, 4], [0, 3, 1, 4], [0, 2, 3, 4], [1, 3, 2, 4]])
        faces, tets, volume = tet_boundary(vertices, tets)
        self.assertEqual(len(faces), 4)
        self.assertNotIn(4, faces)
        self.assertAlmostEqual(volume, 1 / 6)
        xml = make_xml(vertices, faces, scale=1., mass=.1, dt=.001, g=0., radius=.0001,
                       young=0., bending='none', edge_time=0., ipc=True, rigid_supports=[],
                       tets=tets, volume_young=1000., volume_poisson=.3, volume_damping=0.,
                       manual_nodes=True)
        previous = mujoco.get_mju_user_warning()
        mujoco.set_mju_user_warning(lambda _message: None)
        self.addCleanup(mujoco.set_mju_user_warning, previous)
        model = mujoco.MjModel.from_xml_string(xml)
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, f'sleeve_{i}') for i in range(5)]
        self.assertTrue(all(index > 0 for index in ids))
        self.assertEqual(model.nv, 15)
        self.assertAlmostEqual(float(model.body_mass[ids].sum()), .1)
        self.assertGreater(float(model.body_mass[ids[4]]), float(model.body_mass[ids[0]]))
        np.testing.assert_allclose(data.xpos[ids], vertices, atol=1e-12)
        for _ in range(3):
            mujoco.mj_step(model, data)
        self.assertLess(float(np.max(np.abs(data.qvel))), 1e-10)
        repeat = restart_from_rest(mujoco, model, data, np.array(ids), 1., 3)
        self.assertLess(repeat['max_displacement_mm'], 1e-10)
        self.assertLess(repeat['max_speed_mm_s'], 1e-10)
        inner_joint = int(model.body_jntadr[ids[4]])
        data.qpos[model.jnt_qposadr[inner_joint]] += .001
        mujoco.mj_forward(model, data)
        self.assertGreater(float(np.max(np.abs(data.qfrc_passive))), 1e-7)
        self.assertFalse(np.any(data.warning.number))

    @unittest.skipIf(mujoco is None or not mujoco.__version__.startswith('4.'),
                     'MuJoCo 4 — необязательный исследовательский инструмент')
    def test_volume_layer_has_no_motion_without_load(self):
        previous = mujoco.get_mju_user_warning()
        warnings = []
        mujoco.set_mju_user_warning(warnings.append)
        self.addCleanup(mujoco.set_mju_user_warning, previous)
        for case in ('sleeve', 'table'):
            with self.subTest(case=case):
                original, faces, placed, supports = input_mesh(case, 16)
                surface, tets, _changed = tetrahedral_shell(case, original, faces)
                xml = make_xml(placed, surface, scale=.01, mass=.1, dt=.002, g=0.,
                               radius=.0001, young=0., bending='none', edge_time=0.,
                               ipc=True, rigid_supports=[value for name, value in supports.items()
                                                         if name != 'пол'],
                               tets=tets, volume_young=1000., volume_poisson=.3,
                               volume_damping=.002)
                model = mujoco.MjModel.from_xml_string(xml)
                data = mujoco.MjData(model)
                mujoco.mj_forward(model, data)
                for _ in range(3):
                    mujoco.mj_step(model, data)
                self.assertFalse(np.any(data.warning.number))
                self.assertLess(float(np.max(np.abs(data.qvel))), 1e-10)
                mujoco.mj_forward(model, data)
                idx = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_FLEX, 'sleeve')
                start = int(model.flex_vertadr[idx])
                actual = data.flexvert_xpos[start:start + len(original)] / .01
                np.testing.assert_allclose(actual, placed, atol=1e-9)
                # Проверяем не только отсутствие движения: объёмный материал
                # действительно прикладывает силы при пробной деформации.
                data.qpos[0] += .001
                mujoco.mj_forward(model, data)
                self.assertGreater(float(np.max(np.abs(data.qfrc_passive))), 1e-7)
                self.assertFalse(np.any(data.warning.number))
        self.assertTrue(all('has no equality constraints or passive forces' in msg for msg in warnings),
                        str(warnings))


if __name__ == '__main__':
    unittest.main()
