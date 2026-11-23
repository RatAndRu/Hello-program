"""Проверка маленькой модели для ручной подготовки печати в слайсере."""

import io
import sys
import unittest
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from forma.geometry import export_stl  # noqa: E402
from forma.run import build  # noqa: E402


def triangles(mesh):
    """Координаты граней без зависимости от порядка вершин и треугольников."""
    return sorted(
        tuple(sorted(tuple(float(value) for value in vertex) for vertex in triangle))
        for triangle in mesh.vertices[mesh.faces]
    )


class TestX2DExample(unittest.TestCase):
    def test_stl_matches_scenario_and_is_a_closed_20mm_cube(self):
        scenario = ROOT / "examples" / "x2d_test_cube_20mm.forma"
        stl_file = ROOT / "examples" / "x2d_test_cube_20mm.stl"
        result = build(scenario.read_text(encoding="utf-8"), analyze_model=False)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(result.visible_solids()), 1)

        generated = trimesh.load(
            io.BytesIO(export_stl(result.visible_solids())), file_type="stl", force="mesh"
        )
        provided = trimesh.load(stl_file, file_type="stl", force="mesh")
        self.assertEqual(triangles(provided), triangles(generated))
        self.assertEqual(len(provided.faces), 12)
        np.testing.assert_allclose(provided.extents, [20, 20, 20], atol=1e-6)
        np.testing.assert_allclose(provided.bounds, [[-10, -10, 0], [10, 10, 20]], atol=1e-6)
        self.assertTrue(provided.is_watertight)
        self.assertTrue(provided.is_winding_consistent)
        self.assertTrue(provided.is_volume)
        self.assertAlmostEqual(provided.volume, 8000.0, places=5)


if __name__ == "__main__":
    unittest.main()
