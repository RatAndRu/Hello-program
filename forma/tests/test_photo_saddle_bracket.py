"""Геометрическая приёмка кронштейна, перестроенного по фотографии пользователя."""

from __future__ import annotations

import io
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh

from forma.geometry import _clean_manifold_arrays
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
        cls.body = next(s for s in cls.solids if s.name == "корпус").manifold

    def test_single_connected_solid_bounds_and_hole_topology(self):
        self.assertEqual(len(self.solids), 1)
        self.assertEqual(str(self.body.status()), "Error.NoError")
        self.assertEqual(len(self.body.decompose()), 1, "никаких отдельных микрофрагментов")
        # Сквозное ø30 и два открытых промежутка между ребром/полкой,
        # боссом и седлом. Правый канал и верхнее гнездо остаются глухими.
        self.assertEqual(self.body.genus(), 3)
        bbox = self.body.bounding_box()
        np.testing.assert_allclose(np.array(bbox[3:]) - np.array(bbox[:3]),
                                   [222.4878006, 214.1732330, 285.2991958], atol=0.002)
        self.assertGreater(self.body.volume(), 3_800_000)
        self.assertLess(self.body.volume(), 3_900_000)

    def test_reference_layout_slot_bores_chamfer_shell_and_gusset(self):
        def probe_volume(point, size=2.0):
            x, y, z = point
            half = size / 2
            probe = mf.Manifold.cube([size, size, size]).translate([x - half, y - half, z - half])
            return (self.body ^ probe).volume()

        expectations = [
            ((0, 25, 220), 0.0, "глухое гнездо выше дна"),
            ((0, 25, 205), 8.0, "дно гнезда не пробито"),
            ((80, 53.8007, 185.6362), 0.0, "правый канал вдоль X"),
            ((59, 53.8007, 185.6362), 8.0, "дно правого канала перед боссом"),
            ((80, 53.8007, 220), 8.0, "металл правой проушины"),
            ((-9.5267, -93.2069, 6.4833), 0.0, "сквозное малое отверстие"),
            ((2.9733, -71.5559, 6.4833), 8.0, "шейка малой проушины"),
            ((-38.7028, 7.0646, 20), 0.0, "открытая полость седла"),
            ((-98.7028, 7.0646, 20), 0.0, "полость проходит вдоль X слева"),
            ((21.2972, 7.0646, 20), 0.0, "полость проходит вдоль X справа"),
            ((-38.7028, -75.5164, 20), 8.0, "передняя стенка седла"),
            ((-30.4506, -45.1622, 127.3668), 8.0, "длинный видимый гуссет"),
        ]
        for point, expected, label in expectations:
            with self.subTest(label=label, point=point):
                self.assertAlmostEqual(probe_volume(point), expected, delta=0.002)
        with self.subTest("конусная фаска открыта"):
            self.assertAlmostEqual(probe_volume((7.4733, -93.2069, 16), 0.5), 0.0, places=6)
        with self.subTest("под фаской остаётся цилиндрическая стенка"):
            self.assertAlmostEqual(probe_volume((7.4733, -93.2069, 10), 0.5), 0.125, delta=0.0001)

    def test_glb_is_watertight_and_preserves_source_faces(self):
        data = self.result.glb()
        scene = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
        self.assertEqual(len(scene.geometry), 1)
        mesh = next(iter(scene.geometry.values()))
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
        self.assertTrue(mesh.is_watertight)
        self.assertTrue(mesh.is_winding_consistent)
        self.assertGreater(float(mesh.volume), 0)
        _vertices, faces = _clean_manifold_arrays(self.body)
        self.assertEqual(len(mesh.faces), len(faces))
        # 36 граней схлопывались после сварки близких вершин. Guarded export
        # объединяет такие вершины и сохраняет замкнутость, род и объём.
        self.assertEqual(len(mesh.faces), 413310)
        self.assertAlmostEqual(float(mesh.volume), self.body.volume(), delta=0.02)


if __name__ == "__main__":
    unittest.main()
