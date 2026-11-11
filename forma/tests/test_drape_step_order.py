"""Затухание численного двухшагового цикла и диагностика стенки drape.

Порог движения — не доказательство физического равновесия; эти тесты не
проверяют непрерывные столкновения или сохранение всей толщины ткани.
"""
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from forma import cloth
from forma.run import build


class DrapeStepOrderTest(unittest.TestCase):
    def test_deformable_sphere_can_settle_without_alternating_step_order(self):
        path = (Path(__file__).resolve().parent.parent / "benchmarks" / "drape_six" /
                "03_soft_sphere.forma")
        source = path.read_text(encoding="utf-8")
        self.assertIn("steps=100 constraints=20", source)
        self.assertIn("g=0.1", source)
        source = source.replace("steps=100 constraints=20", "steps=140 constraints=60")
        source = source.replace("g=0.1", "g=0.05")

        result = build(source, analyze_model=False, base_dir=path.parent)
        self.assertTrue(result.ok, str(result.error))
        body = result.scene.objects["результат"]
        report = body.meta["cloth"]
        self.assertTrue(report["converged"])
        self.assertLess(report["last_motion"], report["movement_tolerance"])
        self.assertFalse(report["equilibrium_verified"])
        self.assertEqual(report["self_intersections"], 0)
        self.assertEqual(report["support_overlap_volume"], 0)
        self.assertLess(report["max_strain_all"], .06)
        bounds = body.manifold.bounding_box()
        self.assertGreater(bounds[5] - bounds[2], 24)
        self.assertLess(bounds[5] - bounds[2], 27)  # исходная высота — 28 мм

    def test_degenerate_normals_do_not_report_a_complete_wall_measurement(self):
        points = np.array([[0., 0., 0.], [1., 0., 0.], [2., 0., 0.],
                           [0., 0., .5], [1., 0., .5], [2., 0., .5]])
        faces = np.array([[0, 1, 2], [3, 5, 4]])
        shell = np.array([[0, 3], [1, 4], [2, 5]])
        report = cloth.wall_normal_projections(points, points, faces, shell)
        self.assertEqual(report, {"count": 3, "measured": 0, "complete": False})

    def test_scene_warns_when_measured_wall_projection_changes(self):
        projection = {"count": 4, "measured": 4, "complete": True,
                      "min_ratio": .8, "max_ratio": 1.0,
                      "p05_ratio": .8, "p95_ratio": 1.0}
        source = """
пол = box size=[40,40,2] at=[0,0,-2]
лист = box size=[10,10,0.6] at=[0,0,10]
итог = drape лист on=пол rigid=0 g=0 mesh=15 steps=1
"""
        with patch.object(cloth, "wall_normal_projections", return_value=projection) as measure:
            result = build(source, analyze_model=False)
        self.assertTrue(result.ok, str(result.error))
        measure.assert_called_once()
        meta = result.scene.objects["итог"].meta["cloth"]
        self.assertEqual(meta["shell_normal_projections"], projection)
        self.assertFalse(meta["wall_thickness_verified"])
        self.assertTrue(any(item["level"] == "warn" and
                            "сохранение толщины не подтверждено" in item["message"]
                            for item in result.scene.logs))


if __name__ == "__main__":
    unittest.main()
