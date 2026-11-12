"""Контроль опытных чередующихся проекций, не сертификация драпировки."""
from pathlib import Path
import sys
import unittest

import numpy as np

TOOLS = Path(__file__).resolve().parent.parent / 'tools'
sys.path.insert(0, str(TOOLS))

from drape_ipc_relaxation_probe import AlternatingProjector  # noqa: E402
from drape_mujoco_probe import TrajectoryAudit  # noqa: E402

try:
    import ipctk  # noqa: F401
except ImportError:
    ipctk = None


@unittest.skipIf(ipctk is None, 'ipctk нужен только для исследовательского опыта')
class AlternatingProjectorTest(unittest.TestCase):
    def setUp(self):
        self.vertices = np.asarray([[.1, .1, 1.], [.8, .1, 1.], [.1, .8, 1.]])
        self.faces = np.asarray([[0, 1, 2]], dtype=np.int64)
        self.support = np.asarray([[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]])

    def audit(self, old, faces, new):
        audit = TrajectoryAudit(old, faces,
                                {'опора': (self.support.reshape(-1, 3), self.faces)})
        return audit.check(new)

    def test_shape_pass_reduces_edge_error_and_keeps_pin(self):
        projector = AlternatingProjector(self.vertices, self.vertices, self.faces, [], self.support,
                                         passes=1, sweeps=30)
        changed = self.vertices.copy()
        changed[1] += [.5, 0., 0.]
        changed[2] += [0., .3, 0.]
        old_error = np.max(np.abs(np.linalg.norm(changed[projector.edges[:, 1]]
                                                 - changed[projector.edges[:, 0]], axis=1)
                                  - projector.rest))
        projector._shape_pass(changed, np.asarray([False, True, True]))
        new_error = np.max(np.abs(np.linalg.norm(changed[projector.edges[:, 1]]
                                                 - changed[projector.edges[:, 0]], axis=1)
                                  - projector.rest))
        self.assertLess(new_error, old_error * .01)
        np.testing.assert_array_equal(changed[0], self.vertices[0])

    def test_shape_pass_restores_parallel_wall_pairs_in_simple_case(self):
        reference = np.vstack((self.vertices, self.vertices + [0., 0., .4]))
        faces = np.asarray([[0, 1, 2], [3, 5, 4]], dtype=np.int64)
        shell = np.asarray([[0, 3], [1, 4], [2, 5]], dtype=np.int64)
        projector = AlternatingProjector(reference, reference, faces, shell, self.support,
                                         passes=1, sweeps=3)
        changed = reference.copy()
        changed[3:, 2] -= .25
        projector._shape_pass(changed, np.ones(6, dtype=bool))
        np.testing.assert_allclose(changed[3:, 2] - changed[:3, 2], .4, atol=1e-10)
        # Этот случай не является проверкой толщины произвольной сетки.

    def test_contact_is_checked_after_shape_pass_and_pin_is_fixed(self):
        projector = AlternatingProjector(self.vertices, self.vertices, self.faces, [], self.support,
                                         rounds=4, passes=2, sweeps=4)
        free = np.asarray([False, True, True])
        crossing = self.vertices.copy()
        crossing[1:, 2] -= 2.
        self.assertFalse(self.audit(self.vertices, self.faces, crossing))
        projector.project(self.vertices, crossing, free)
        self.assertTrue(self.audit(self.vertices, self.faces, crossing))
        np.testing.assert_array_equal(crossing[0], self.vertices[0])
        self.assertEqual(projector.stats()['shape_passes'], 2)
        self.assertEqual(projector.stats()['ipc']['calls'], 3)

    def test_invalid_pass_count_and_wall_pairs_rejected(self):
        with self.assertRaises(ValueError):
            AlternatingProjector(self.vertices, self.vertices, self.faces, [], self.support, sweeps=0)
        with self.assertRaises(ValueError):
            AlternatingProjector(self.vertices, self.vertices, self.faces,
                                 [[0, 1], [0, 2]], self.support)


if __name__ == '__main__':
    unittest.main()
