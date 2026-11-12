"""Локальная поправка опоры не раздвигает свободные пары стенки.

Это не тест всей толщины, контакта по граням или непрерывного движения.
"""
import unittest

import numpy as np

from forma import cloth


class PlaneField:
    def closest(self, points):
        distance = points[:, 2].copy()
        normal = np.tile([0., 0., 1.], (len(points), 1))
        point = points.copy()
        point[:, 2] = 0.
        return distance, point, normal


class SlabField:
    """Две противоположные плоскости с недостаточным для пары промежутком."""
    def closest(self, points):
        lower = points[:, 2] + .2
        upper = .2 - points[:, 2]
        choose_lower = lower <= upper
        distance = np.where(choose_lower, lower, upper)
        normal = np.zeros_like(points)
        normal[:, 2] = np.where(choose_lower, 1., -1.)
        return distance, points.copy(), normal


class PairedSupportTest(unittest.TestCase):
    def test_one_side_contact_moves_both_without_changing_pair_vector(self):
        position = np.array([[0., 0., -.2], [0., 0., .4]])
        initial = position.copy()
        cloth._project_paired_support(position, np.ones(2, dtype=bool), PlaneField(),
                                      .1, np.array([[0, 1]], dtype=int))
        np.testing.assert_allclose(position[:, 2], [.1, .7], atol=1e-12)
        np.testing.assert_allclose(position[1] - position[0], initial[1] - initial[0], atol=1e-12)

    def test_real_support_field_keeps_pair_separation(self):
        triangles = np.array([[[-10., -10., 0.], [10., -10., 0.], [10., 10., 0.]],
                              [[-10., -10., 0.], [10., 10., 0.], [-10., 10., 0.]]])
        field = cloth.SupportField(triangles, cell=5.)
        position = np.array([[0., 0., -.2], [0., 0., .4]])
        cloth._project_paired_support(position, np.ones(2, dtype=bool), field, .1,
                                      np.array([[0, 1]], dtype=int))
        np.testing.assert_allclose(position[:, 2], [.1, .7], atol=1e-12)
        np.testing.assert_allclose(position[1] - position[0], [0., 0., .6], atol=1e-12)

    def test_deeper_side_drives_correction_and_unpaired_point_moves_independently(self):
        position = np.array([[0., 0., -.3], [0., 0., -.1], [1., 0., -.4]])
        cloth._project_paired_support(position, np.ones(3, dtype=bool), PlaneField(),
                                      0., np.array([[1, 0]], dtype=int))
        np.testing.assert_allclose(position[:, 2], [.0, .2, .0], atol=1e-12)

    def test_pinned_node_is_not_moved(self):
        position = np.array([[0., 0., .5], [0., 0., -.2]])
        free = np.array([False, True])
        pinned = position[0].copy()
        cloth._project_paired_support(position, free, PlaneField(), .1,
                                      np.array([[0, 1]], dtype=int))
        np.testing.assert_array_equal(position[0], pinned)
        self.assertAlmostEqual(position[1, 2], .1)

    def test_conflicting_supports_do_not_break_pair_but_cannot_be_claimed_resolved(self):
        position = np.array([[0., 0., -.5], [0., 0., .5]])
        initial = position.copy()
        cloth._project_paired_support(position, np.ones(2, dtype=bool), SlabField(), 0.,
                                      np.array([[0, 1]], dtype=int))
        np.testing.assert_array_equal(position, initial)  # не раскачивать пару между опорами
        distance, _, _ = SlabField().closest(position)
        self.assertLess(distance.min(), 0.)  # две опоры несовместимы с толщиной пары

    def test_blocked_pair_does_not_block_other_points(self):
        position = np.array([[-1., 0., -.5], [-1., 0., .5],
                             [0., 0., -.3], [0., 0., -.1], [1., 0., .3]])
        cloth._project_paired_support(position, np.ones(5, dtype=bool), SlabField(), 0.,
                                      np.array([[0, 1], [2, 3]], dtype=int))
        np.testing.assert_allclose(position[:, 2], [-.5, .5, -.2, .0, .2], atol=1e-12)

    def test_no_contact_does_not_change_positions(self):
        position = np.array([[0., 0., .5], [0., 0., 1.1], [1., 0., 1.]])
        initial = position.copy()
        cloth._project_paired_support(position, np.ones(3, dtype=bool), PlaneField(), .1,
                                      np.array([[0, 1]], dtype=int))
        np.testing.assert_array_equal(position, initial)


if __name__ == "__main__":
    unittest.main()
