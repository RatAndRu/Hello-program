"""Регрессии дополнительного восстановления тонкой оболочки.

Они не доказывают непрерывный контакт или сохранение всей толщины.
"""
import unittest

import numpy as np

from forma import cloth


class FreeSpace:
    def closest(self, points):
        return (np.full(len(points), np.inf), points.copy(),
                np.tile([0., 0., 1.], (len(points), 1)))


class ShellRelaxationTest(unittest.TestCase):
    def setUp(self):
        self.reference = np.array([[-5., -5., 0.], [5., -5., 0.], [5., 5., 0.], [-5., 5., 0.],
                                   [-5., -5., .6], [5., -5., .6], [5., 5., .6], [-5., 5., .6]])
        self.faces = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
                               [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                               [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], dtype=int)
        self.shell = np.array([[0, 4], [1, 5], [2, 6], [3, 7]], dtype=int)
        self.edges = cloth._edge_arrays(self.faces)
        self.colors = cloth._edge_colors(self.edges, len(self.reference))
        self.rest = np.linalg.norm(self.reference[self.edges[:, 1]] - self.reference[self.edges[:, 0]], axis=1)
        normals = cloth.vertex_normals(self.reference, self.faces)
        direction = normals[self.shell[:, 0]] - normals[self.shell[:, 1]]
        direction /= np.maximum(np.linalg.norm(direction, axis=1), 1e-12)[:, None]
        delta = self.reference[self.shell[:, 1]] - self.reference[self.shell[:, 0]]
        self.height = np.einsum('ij,ij->i', delta, direction)
        self.tangent = np.linalg.norm(delta - self.height[:, None] * direction, axis=1)

    def project(self, position, free):
        cloth._relax_shell_with_support(position, free, self.faces, self.edges, self.colors,
                                        self.rest, self.shell, self.height, self.tangent,
                                        FreeSpace(), 0., 1.)

    def test_rest_shape_is_unchanged(self):
        position = self.reference.copy()
        self.project(position, np.ones(len(position), dtype=bool))
        np.testing.assert_allclose(position, self.reference, atol=1e-12)

    def test_distorted_wall_is_restored_and_pin_does_not_move(self):
        position = self.reference.copy()
        position[4, 2] -= .2
        free = np.ones(len(position), dtype=bool)
        free[0] = False
        original_pin = position[0].copy()
        before = cloth.wall_normal_projections(self.reference, position, self.faces, self.shell)
        self.project(position, free)
        after = cloth.wall_normal_projections(self.reference, position, self.faces, self.shell)
        np.testing.assert_array_equal(position[0], original_pin)
        self.assertLess(abs(1. - after['min_ratio']), abs(1. - before['min_ratio']))
        self.assertTrue(np.all(np.isfinite(position)))

    def test_fully_pinned_mesh_is_unchanged(self):
        position = self.reference.copy()
        position[4, 2] -= .2
        before = position.copy()
        self.project(position, np.zeros(len(position), dtype=bool))
        np.testing.assert_array_equal(position, before)


if __name__ == '__main__':
    unittest.main()
