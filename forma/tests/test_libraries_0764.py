"""Проверки новых возможностей: реальные тела, текстуры, расстояния и экспорт."""
from __future__ import annotations

import io
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import manifold3d as mf
import numpy as np
import trimesh

from forma.cuts import _brute_distance, _distance_to_mesh
from forma.geometry import _glb_read, manifold_mesh
from forma.noise import fast_noise, tileable_noise
from forma.run import build
from forma.sampling import PoissonDisk2D
from forma.textures import custom_height


def built(script):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    return result


class NoiseAndSamplingTest(unittest.TestCase):
    def test_fast_noise_batch_seed_and_types(self):
        points = np.random.default_rng(4).normal(size=(300, 3))
        for kind in ('simplex', 'perlin', 'value', 'cellular'):
            with self.subTest(kind=kind):
                a = fast_noise(points, seed=7, kind=kind)
                b = fast_noise(points, seed=7, kind=kind)
                c = fast_noise(points, seed=8, kind=kind)
                self.assertTrue(np.array_equal(a, b))
                self.assertFalse(np.array_equal(a, c))
                self.assertTrue(np.isfinite(a).all())
                self.assertGreater(float(np.ptp(a)), .01)
                self.assertEqual(a.shape, (300,))
        self.assertEqual(fast_noise(points[:, :2]).shape, (300,))
        np.testing.assert_array_equal(fast_noise(points, seed=2**31),
                                      fast_noise(points, seed=-(2**31)))
        with self.assertRaises(ValueError):
            fast_noise(points, kind='not-a-noise')

    def test_textures_are_seeded_and_roughly_join_at_tile_boundary(self):
        for pattern in ('fastnoise', 'вороной'):
            a = custom_height(pattern, 1, '7', 256)
            b = custom_height(pattern, 1, '7', 256)
            c = custom_height(pattern, 1, '8', 256)
            np.testing.assert_array_equal(a, b)
            self.assertFalse(np.array_equal(a, c))
            self.assertTrue(np.isfinite(a).all())
            self.assertGreater(float(np.ptp(a)), .1)
            # Pixel centres are one step apart, not the exact same boundary.
            self.assertLess(float(np.mean(abs(a[:, 0] - a[:, -1]))), .08)
            self.assertLess(float(np.mean(abs(a[0, :] - a[-1, :]))), .08)
        self.assertEqual(tileable_noise(64, 3, 1).shape, (64, 64))

    def test_solid_noise_and_normal_map_export(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'FORMA_DATA': td}):
            for kind in ('simplex', 'perlin', 'value', 'cellular'):
                script = ('a = sphere radius=15 segments=20\n'
                          f'a = wrinkle [a] mode=шум engine=fastnoise noise_kind={kind} '
                          'amp=0.5 freq=5 seed=7 detail=2 surface=вся\n'
                          'texture a kind=своя pattern=вороной scale=1 relief=0.5')
                a, b = built(script), built(script)
                ma, mb = a.scene.objects['a'].manifold, b.scene.objects['a'].manifold
                self.assertEqual(ma.status(), mf.Error.NoError)
                self.assertGreater(ma.volume(), 0)
                va, fa = manifold_mesh(ma)
                vb, fb = manifold_mesh(mb)
                np.testing.assert_array_equal(fa, fb)
                np.testing.assert_allclose(va, vb, atol=1e-6)
                data = a.export_glb()
                doc, _ = _glb_read(data)
                self.assertEqual(doc['asset']['extras']['formaUnits']['world'], 'meter')
                self.assertEqual(doc['materials'][0]['normalTexture']['scale'], 1.0)
                scene = trimesh.load(io.BytesIO(data), file_type='glb', force='scene')
                self.assertTrue(np.isfinite(scene.bounds).all())

    def test_legacy_wrinkle_unchanged_by_default(self):
        old = 'a = sphere radius=15 segments=20\na = wrinkle [a] mode=шум amp=0.5 freq=5 seed=7 detail=2 surface=вся'
        a = built(old).scene.objects['a'].manifold
        b = built(old + ' engine=forma').scene.objects['a'].manifold
        va, fa = manifold_mesh(a)
        vb, fb = manifold_mesh(b)
        np.testing.assert_array_equal(fa, fb)
        np.testing.assert_array_equal(va, vb)

    def test_scatter_poisson_seed_spacing_and_gap(self):
        script = ('a = box size=[5,5,5]\n'
                  'items = scatter [a] count=24 area=[160,120] distribution=poisson '
                  'distance=15 seed=7 scale=[1,1] gap=1 as=objects')
        first, second = built(script), built(script)
        names = first.scene.groups['items']
        self.assertEqual(len(names), 24)
        boxes = [first.scene.objects[n].manifold.bounding_box() for n in names]
        boxes2 = [second.scene.objects[n].manifold.bounding_box() for n in names]
        np.testing.assert_allclose(boxes, boxes2, atol=1e-7)
        xy = np.array([[(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2] for bb in boxes])
        distances = np.linalg.norm(xy[:, None] - xy[None, :], axis=2)
        distances += np.eye(len(xy)) * 1e9
        self.assertGreaterEqual(float(distances.min()), 15 - 1e-6)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a = first.scene.objects[names[i]].manifold
                b = first.scene.objects[names[j]].manifold
                self.assertLess((a ^ b).volume(), 1e-7)
        again = built(script.replace('seed=7', 'seed=8'))
        boxes3 = [again.scene.objects[n].manifold.bounding_box() for n in names]
        self.assertFalse(np.allclose(boxes, boxes3))

    def test_poisson_rejection_and_infeasible_request(self):
        rng = np.random.default_rng(4)
        p = PoissonDisk2D((-20, -20, 20, 20), 8, rng)
        while len(p.points) < 15:
            pt = p.candidate()
            if pt is None:
                break
            if math.hypot(*pt) < 5:
                p.reject()
            else:
                p.accept()
        self.assertGreaterEqual(len(p.points), 10)
        self.assertTrue(all(math.hypot(*pt) >= 5 for pt in p.points))
        bad = build('a = box size=[4,4,4]\nx = scatter [a] count=5 area=[5,5] '
                    'distribution=poisson distance=100', analyze_model=False)
        self.assertFalse(bad.ok)
        self.assertIn('удалось разместить только', str(bad.error))

    def test_legacy_scatter_default_is_stable(self):
        script = 'a = box size=[4,4,4]\nx = scatter [a] count=8 area=[90,90] seed=3 as=objects'
        a, b = built(script), built(script + ' distribution=random')
        for name in a.scene.groups['x']:
            np.testing.assert_array_equal(a.scene.objects[name].bbox, b.scene.objects[name].bbox)


class DistanceBVHTest(unittest.TestCase):
    def test_long_triangle_is_not_missed(self):
        verts = [[-100, 0, 0], [100, 0, 0], [0, 100, 0]]
        faces = [[0, 1, 2]]
        for i in range(3001):
            x, y, j = (i % 51) * .001, (i // 51) * .001, len(verts)
            verts.extend([[x, y, .2], [x + .001, y, .2], [x, y + .001, .2]])
            faces.append([j, j + 1, j + 2])
        v, f = np.asarray(verts, float), np.asarray(faces, np.int32)
        q = np.array([[0., 0., .05], [0., 1., .05]])
        got = _distance_to_mesh(q, v, f, cell=1)
        np.testing.assert_allclose(got, [.05, .05], atol=1e-10)
        np.testing.assert_allclose(got, _brute_distance(q, v, f), atol=1e-10)

    def test_bvh_matches_brute_on_closed_mesh(self):
        m = mf.Manifold.sphere(20, 80)
        v, f = manifold_mesh(m)
        self.assertGreater(len(f), 3000)
        points = np.random.default_rng(23).uniform(-25, 25, (45, 3))
        np.testing.assert_allclose(_distance_to_mesh(points, v, f),
                                   _brute_distance(points, v, f), atol=1e-9)

    def test_empty_input(self):
        self.assertTrue(np.isinf(_distance_to_mesh(np.array([[1., 2., 3.]]),
                                                   np.zeros((0, 3)), np.zeros((0, 3), int))[0]))


if __name__ == '__main__':
    unittest.main()
