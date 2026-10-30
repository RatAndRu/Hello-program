"""Геометрическая приёмка кронштейна, построенного по фотографии пользователя."""

from __future__ import annotations

import io
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh

from forma.geometry import _glb_valid_faces, manifold_mesh
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "showcase" / "sources" / "photo" / "saddle_bracket.forma"


class PhotoSaddleBracketTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(SOURCE.read_text(encoding="utf-8"), analyze_model=False)
        if not cls.result.ok:
            raise AssertionError(f"{cls.result.error}\n{cls.result.log}")
        cls.solids = cls.result.visible_solids()
        cls.body = cls.solids[0].manifold

    def test_single_solid_bounds_and_two_through_holes(self):
        self.assertEqual(len(self.solids), 1)
        self.assertEqual(self.solids[0].name, "корпус")
        self.assertEqual(str(self.body.status()), "Error.NoError")
        self.assertEqual(self.body.genus(), 2, "ровно два сквозных отверстия; гнездо слепое")
        bbox = self.body.bounding_box()
        np.testing.assert_allclose(np.array(bbox[3:]) - np.array(bbox[:3]),
                                   [251.0, 219.0, 245.0], atol=0.002)
        self.assertGreater(self.body.volume(), 2_000_000)

    def test_slot_holes_shell_and_lugs_are_real_geometry(self):
        def probe_volume(point):
            x, y, z = point
            probe = mf.Manifold.cube([2.0, 2.0, 2.0]).translate([x - 1, y - 1, z - 1])
            return (self.body ^ probe).volume()

        expectations = [
            ((0, 25, 180), 0.0, "глухое гнездо выше дна"),
            ((0, 25, 170), 8.0, "дно гнезда не пробито"),
            ((98, -10, 145), 0.0, "горизонтальное отверстие"),
            ((98, -10, 180), 8.0, "металл правой проушины"),
            ((-82, -110, 7), 0.0, "вертикальное отверстие"),
            ((-82, -85, 7), 8.0, "металл малой проушины"),
            ((0, 0, 40), 0.0, "открытая полость седла"),
            ((85, 40, 20), 8.0, "стенка седла"),
        ]
        for point, expected, label in expectations:
            with self.subTest(label=label, point=point):
                volume = probe_volume(point)
                if expected == 0:
                    self.assertAlmostEqual(volume, 0.0, places=6)
                else:
                    self.assertAlmostEqual(volume, expected, delta=0.002)

    def test_glb_is_watertight_and_preserves_source_faces(self):
        data = self.result.glb()
        scene = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
        self.assertEqual(len(scene.geometry), 1)
        mesh = next(iter(scene.geometry.values()))
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_winding_consistent)
        self.assertGreater(float(mesh.volume), 0)
        vertices, faces = manifold_mesh(self.body)
        self.assertEqual(len(mesh.faces), len(_glb_valid_faces(vertices, faces)))
        self.assertAlmostEqual(float(mesh.volume), self.body.volume(), delta=0.02)


if __name__ == "__main__":
    unittest.main()
