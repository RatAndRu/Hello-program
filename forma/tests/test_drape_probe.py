"""Проверка конструкции исследовательских сцен, не пригодности движка к выпуску."""
from __future__ import annotations

from pathlib import Path
import sys
import types
import unittest
from unittest import mock

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(TOOLS))
import audit_drape_sleeve as audit  # noqa: E402
from drape_mujoco_probe import (TrajectoryAudit, changed_surface_distances, input_mesh, make_xml,
                                restart_from_rest, sampled_surface_distance, surface_samples,
                                tet_boundary, tetrahedral_shell)  # noqa: E402
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
        self.assertFalse(check.check(moving - [0., 0., 2.]))
        self.assertEqual(check.steps, 2)

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
