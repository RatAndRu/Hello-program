"""Приёмка мебельного монтажного стенда.

Проверяются реальные посадки и экспортируемая сетка, а не только отсутствие
исключения при построении сценария.
"""

from __future__ import annotations

import io
import unittest

import numpy as np
import trimesh

from forma.run import build
from forma.webui import EXAMPLES, load_example


class FurnitureHardwareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(load_example("furniture_hardware"), analyze_model=True)
        if not cls.result.ok:
            raise AssertionError(cls.result.error)
        cls.scene = cls.result.scene
        cls.objects = cls.scene.objects
        cls.payload = cls.result.payload()
        cls._glb = None

    def intersection(self, first: str, second: str) -> float:
        return abs(float((self.objects[first].manifold
                          ^ self.objects[second].manifold).volume()))

    def probe(self, name: str, point, edge: float = 0.3) -> float:
        import manifold3d as mf
        tool = mf.Manifold.cube((edge, edge, edge), True).translate(point)
        return abs(float((self.objects[name].manifold ^ tool).volume()))

    def test_registered_and_internal_checks(self):
        self.assertIn(("Мебельная фурнитура: монтажный стенд", "furniture_hardware"),
                      EXAMPLES)
        analysis = self.payload["analysis"]
        self.assertEqual(analysis["checks_total"], 30)
        self.assertEqual(analysis["checks_passed"], 30)
        self.assertTrue(all(check["ok"] for check in analysis["checks"]))
        self.assertEqual(analysis["metrics"]["visible_count"], 34)

    def test_dimensions_and_polygon_budget(self):
        metrics = self.payload["analysis"]["metrics"]
        self.assertEqual(metrics["bbox"], (-560.0, -340.0, 0.0,
                                           560.0, 340.0, 424.0))
        visible = [obj for obj in self.objects.values() if obj.visible]
        actual_tris = sum(obj.stats()["tris"] for obj in visible)
        # Фактическая сцена: 87 008. Оставлен небольшой запас на допустимую
        # смену tessellation, но скрытый рост до сотен тысяч запрещён.
        self.assertLessEqual(actual_tris, 95000)
        limits = {"винт_м6": 22000, "кнопка": 9500, "конфирмат": 9000,
                  "эксцентрик": 5500, "уголок": 800}
        for name, limit in limits.items():
            self.assertLessEqual(self.objects[name].stats()["tris"], limit, name)

    def test_handle_spacing_and_panel_intersections(self):
        def center(name):
            bb = self.objects[name].manifold.bounding_box()
            return np.asarray([(bb[i] + bb[i + 3]) / 2.0 for i in range(3)])

        self.assertAlmostEqual(center("стяжка_192_б")[0]
                               - center("стяжка_192_а")[0], 192.0, places=6)
        self.assertAlmostEqual(center("стяжка_128_б")[0]
                               - center("стяжка_128_а")[0], 128.0, places=6)
        pairs = [("фасад_верх", "стяжка_192_а"),
                 ("фасад_верх", "стяжка_192_б"),
                 ("фасад_низ", "стяжка_128_а"),
                 ("фасад_низ", "стяжка_128_б"),
                 ("дверца", "стяжка_кнопки")]
        for panel, screw in pairs:
            self.assertLess(self.intersection(panel, screw), 1e-4, (panel, screw))
            self.assertAlmostEqual(self.objects[screw].manifold.bounding_box()[4],
                                   81.0, places=6)
        self.assertLess(self.intersection("фасад_верх", "ручка_192"), 1e-6)
        self.assertLess(self.intersection("фасад_низ", "ручка_128"), 1e-6)
        self.assertLess(self.intersection("дверца", "кнопка"), 1e-6)

    def test_grommet_fit_and_cap(self):
        self.assertLess(self.intersection("столешница", "люверс"), 1e-6)
        plate_bb = self.objects["столешница"].manifold.bounding_box()
        grommet_bb = self.objects["люверс"].manifold.bounding_box()
        cap_bb = self.objects["крышка_люверса"].manifold.bounding_box()
        self.assertEqual((plate_bb[2], plate_bb[5]), (24.0, 42.0))
        self.assertEqual((grommet_bb[2], grommet_bb[5]), (24.0, 46.0))
        self.assertAlmostEqual(cap_bb[2], 42.0, places=6)
        self.assertEqual(self.objects["столешница"].manifold.genus(), 1)
        self.assertEqual(self.objects["люверс"].manifold.genus(), 1)
        self.assertEqual(self.objects["крышка_люверса"].manifold.genus(), 1)

    def test_intended_topology_and_parts(self):
        genus = {"эксцентрик": 1, "конфирмат": 0, "уголок": 4,
                 "шкант": 0, "гайка_м6": 1, "кнопка": 0,
                 "фасад_верх": 2, "фасад_низ": 2, "дверца": 1}
        for name, expected in genus.items():
            self.assertEqual(self.objects[name].manifold.genus(), expected, name)
        for name in ("эксцентрик", "конфирмат", "уголок", "шкант"):
            self.assertEqual(len(self.objects[name].manifold.decompose()), 1, name)
        self.assertEqual(len(self.objects["полкодержатели"].manifold.decompose()), 2)

    def test_through_voids_and_solid_neighbours(self):
        # Пустота должна быть именно в оси отверстия, а рядом — полный материал.
        self.assertLess(self.probe("фасад_верх", (-446, 72, 304)), 1e-8)
        self.assertGreater(self.probe("фасад_верх", (-436, 72, 304)), 0.02)
        self.assertLess(self.probe("столешница", (290, 125, 33)), 1e-8)
        self.assertGreater(self.probe("столешница", (330, 125, 33)), 0.02)
        self.assertLess(self.probe("эксцентрик", (180, -60, 25)), 1e-8)
        self.assertGreater(self.probe("эксцентрик", (184, -60, 25)), 0.02)

    def test_glb_after_blender_style_position_weld(self):
        if self._glb is None:
            type(self)._glb = self.result.glb()
        scene = trimesh.load(io.BytesIO(self._glb), file_type="glb", process=False)
        self.assertEqual(len(scene.geometry), 34)
        self.assertEqual(sum(len(mesh.faces) for mesh in scene.geometry.values()),
                         sum(obj.stats()["tris"] for obj in self.objects.values()
                             if obj.visible))
        for name, mesh in scene.geometry.items():
            with self.subTest(name=name):
                mesh = mesh.copy()
                # UV и normal seams не являются геометрическими разрывами.
                # Это аналог Remove Doubles по позиции в Blender.
                mesh.merge_vertices(digits_vertex=5, merge_tex=True, merge_norm=True)
                mesh.remove_unreferenced_vertices()
                self.assertTrue(mesh.is_watertight)
                self.assertTrue(mesh.is_winding_consistent)
                areas = np.asarray(mesh.area_faces)
                self.assertTrue(np.all(np.isfinite(areas)))
                self.assertTrue(np.all(areas > 1e-10))
                faces = np.sort(np.asarray(mesh.faces), axis=1)
                self.assertEqual(len(faces), len(np.unique(faces, axis=0)))
                edges = np.sort(np.asarray(mesh.edges), axis=1)
                _, counts = np.unique(edges, axis=0, return_counts=True)
                self.assertTrue(np.all(counts == 2))


if __name__ == "__main__":
    unittest.main()
