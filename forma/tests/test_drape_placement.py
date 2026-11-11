"""Предварительный перенос не должен учитывать опоры сбоку или позади тела."""
from __future__ import annotations

from itertools import product
import unittest

import numpy as np

from forma.cloth import place
from forma.run import build


def plane(z, x0=-100, x1=100, y0=-100, y1=100):
    return np.array([[[x0, y0, z], [x1, y0, z], [x1, y1, z]],
                     [[x0, y0, z], [x1, y1, z], [x0, y1, z]]], dtype=float)


class PlacementTest(unittest.TestCase):
    def setUp(self):
        self.body = np.array(list(product((-5., 5.), (-5., 5.), (50., 60.))))
        self.gravity = np.array([0., 0., -1.])

    def test_floor_ignores_high_side_and_ceiling(self):
        for irrelevant in (plane(150, 110, 130, -10, 10), plane(120)):
            with self.subTest(support=irrelevant[0, 0]):
                result = place(self.body, np.concatenate((plane(0), irrelevant)), self.gravity, .02)
                self.assertAlmostEqual(float(result[:, 2].min()), .02, places=9)
                np.testing.assert_allclose(result[:, :2], self.body[:, :2])

    def test_first_support_in_gravity_direction(self):
        result = place(self.body, np.concatenate((plane(0), plane(30))), self.gravity, .02)
        self.assertAlmostEqual(float(result[:, 2].min()), 30.02, places=9)

    def test_overlapping_bounds_do_not_move(self):
        result = place(self.body, np.concatenate((plane(0), plane(55))), self.gravity, .02)
        np.testing.assert_array_equal(result, self.body)

    def test_rotated_gravity_and_geometry(self):
        angle = .71
        rotation = np.array([[np.cos(angle), 0., np.sin(angle)], [0., 1., 0.],
                             [-np.sin(angle), 0., np.cos(angle)]])
        translation = np.array([12., -8., 17.])
        supports = np.concatenate((plane(0), plane(150, 110, 130, -10, 10), plane(120)))
        expected = place(self.body, supports, self.gravity, .02) @ rotation.T + translation
        result = place(self.body @ rotation.T + translation, supports @ rotation.T + translation,
                       self.gravity @ rotation.T, .02)
        np.testing.assert_allclose(result, expected, rtol=0, atol=1e-12)

    def test_no_support_or_gravity_does_not_move(self):
        for supports, gravity in ((np.zeros((0, 3, 3)), self.gravity), (plane(0), np.zeros(3))):
            with self.subTest(gravity=gravity):
                np.testing.assert_array_equal(place(self.body, supports, gravity, .02), self.body)

    def test_cube_actually_reaches_floor_with_irrelevant_supports(self):
        common = "пол = box size=[200,200,6] at=[0,0,-6]\nкуб = box size=[10,10,10] at=[0,0,50]\n"
        for other in ("бок = box size=[20,20,150] at=[120,0,0]",
                      "бок = box size=[100,100,10] at=[0,0,100]"):
            with self.subTest(other=other):
                result = build(common + other + "\nитог = drape куб on=[пол,бок] "
                               "mesh=8 steps=55 constraints=14 rigid=1 g=0.2\n", analyze_model=False)
                self.assertTrue(result.ok, str(result.error))
                self.assertAlmostEqual(result.scene.objects["итог"].manifold.bounding_box()[2], .02, delta=.05)


if __name__ == "__main__":
    unittest.main()
