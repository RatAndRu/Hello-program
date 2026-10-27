"""Приёмка цельного анатомического скелета: 206 костей, пустоты и экспорт."""

from __future__ import annotations

from collections import Counter
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import manifold3d as mf
import numpy as np
import trimesh

from forma.errors import GeometryError
from forma.geometry import _glb_read
from forma.ops_io import (_glb_node_cached, _glb_scene_cached, load_any,
                          resolve_file)
from forma.run import build
from forma.webui import EXAMPLES, load_example

ROOT = Path(__file__).resolve().parent.parent
ASSET = ROOT / "examples/assets/human_skeleton.glb"
NAMES = json.loads((ROOT / "examples/assets/human_skeleton.names.json").read_text(encoding="utf-8"))


class HumanSkeletonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(load_example("human_skeleton"), analyze_model=True)
        if not cls.result.ok:
            raise AssertionError(cls.result.error)
        cls.scene = cls.result.scene
        cls.objects = cls.scene.objects
        cls.payload = cls.result.payload()
        cls._glb = None

    @classmethod
    def glb(cls):
        if cls._glb is None:
            cls._glb = cls.result.glb()
        return cls._glb

    def probe(self, name: str, point, edge: float = 1.0) -> float:
        tool = mf.Manifold.cube((edge, edge, edge), True).translate(point)
        return abs(float((self.objects[name].manifold ^ tool).volume()))

    def empty_hits(self, point, edge: float = 1.0):
        hits = []
        tool = mf.Manifold.cube((edge, edge, edge), True).translate(point)
        for name, obj in self.objects.items():
            bb = obj.manifold.bounding_box()
            if not all(bb[i] - edge <= point[i] <= bb[i + 3] + edge for i in range(3)):
                continue
            volume = abs(float((obj.manifold ^ tool).volume()))
            if volume > 1e-7:
                hits.append((name, volume))
        return hits

    def test_registered_build_and_anatomical_regions(self):
        self.assertIn(("Скелет взрослого человека: 206 костей", "human_skeleton"), EXAMPLES)
        self.assertEqual(len(self.objects), 206)
        self.assertEqual(len(NAMES), 206)
        self.assertEqual({row["object"] for row in NAMES.values()}, set(self.objects))
        self.assertEqual({name: len(items) for name, items in self.scene.groups.items()}, {
            "череп": 29, "позвоночник": 26, "грудная_клетка": 25,
            "верхние_конечности": 64, "нижние_конечности": 62,
        })
        axial = sum(len(self.scene.groups[n]) for n in ("череп", "позвоночник", "грудная_клетка"))
        appendicular = sum(len(self.scene.groups[n]) for n in ("верхние_конечности", "нижние_конечности"))
        self.assertEqual((axial, appendicular), (80, 126))
        analysis = self.payload["analysis"]
        self.assertEqual((analysis["checks_passed"], analysis["checks_total"]), (412, 412))
        self.assertEqual(analysis["metrics"]["visible_count"], 206)
        self.assertEqual(analysis["metrics"]["tris"], 400168)

    def test_standard_206_bone_inventory(self):
        counts = Counter(row["subregion"] for row in NAMES.values())
        expected = {
            "мозговой череп": 8, "лицевой череп": 14, "подъязычная кость": 1,
            "слуховые косточки": 6, "шейный отдел": 7, "грудной отдел": 12,
            "поясничный отдел": 5, "крестец": 1, "копчик": 1, "грудина": 1,
            "истинные рёбра": 14, "ложные рёбра": 6, "колеблющиеся рёбра": 4,
            "плечевой пояс": 4, "плечо": 2, "предплечье": 4, "запястье": 16,
            "пясть": 10, "фаланги пальцев": 28, "тазовый пояс": 2,
            "бедро и надколенник": 4, "голень": 4, "предплюсна": 14,
            "плюсна": 10, "фаланги пальцев стопы": 28,
        }
        self.assertEqual(counts, expected)
        hand_groups = {"запястье", "пясть", "фаланги пальцев"}
        foot_groups = {"предплюсна", "плюсна", "фаланги пальцев стопы"}
        self.assertEqual(sum(row["subregion"] in hand_groups for row in NAMES.values()), 54)
        self.assertEqual(sum(row["subregion"] in foot_groups for row in NAMES.values()), 52)
        for side in ("left", "right"):
            rows = [row for row in NAMES.values() if f"_{side}_" in f"_{row['object']}_"]
            self.assertEqual(sum(row["subregion"] in hand_groups for row in rows), 27)
            self.assertEqual(sum(row["subregion"] in foot_groups for row in rows), 26)
            names = {row["object"] for row in rows}
            self.assertIn(f"proximal_phalanx_of_{side}_thumb", names)
            self.assertIn(f"distal_phalanx_of_{side}_thumb", names)
            self.assertNotIn(f"middle_phalanx_of_{side}_thumb", names)
            self.assertIn(f"proximal_phalanx_of_{side}_big_toe", names)
            self.assertIn(f"distal_phalanx_of_{side}_big_toe", names)
            self.assertNotIn(f"middle_phalanx_of_{side}_big_toe", names)

    def test_dimensions_canonical_axes_and_mesh_parts(self):
        bbox = self.payload["analysis"]["metrics"]["bbox"]
        self.assertAlmostEqual(bbox[2], 0.0, places=6)
        self.assertAlmostEqual(bbox[5], 1750.0, delta=0.02)
        self.assertEqual(sum(obj.stats()["tris"] for obj in self.objects.values()), 400168)
        for name, obj in self.objects.items():
            with self.subTest(object=name):
                self.assertEqual(obj.manifold.status(), mf.Error.NoError)
                self.assertGreater(obj.manifold.volume(), 0)
                self.assertEqual(len(obj.manifold.decompose()), 3 if name == "sternum" else 1)
        for right, left in (("right_femur", "left_femur"), ("right_humerus", "left_humerus"),
                            ("right_parietal", "left_parietal"), ("right_hip", "left_hip")):
            right_box = self.objects[right].manifold.bounding_box()
            left_box = self.objects[left].manifold.bounding_box()
            self.assertGreater((right_box[0] + right_box[3]) / 2, 0)
            self.assertLess((left_box[0] + left_box[3]) / 2, 0)
        self.assertLess(np.mean(self.objects["frontal"].manifold.bounding_box()[1::3]), 0)
        self.assertGreater(np.mean(self.objects["occipital"].manifold.bounding_box()[1::3]), 0)
        toe_y = np.mean(self.objects["distal_phalanx_of_right_big_toe"].manifold.bounding_box()[1::3])
        heel_y = np.mean(self.objects["right_calcaneus"].manifold.bounding_box()[1::3])
        self.assertLess(toe_y, heel_y)

    def test_real_skull_thoracic_and_pelvic_voids(self):
        voids = {
            "right_orbit": (30, -65, 1640), "left_orbit": (-30, -65, 1640),
            "thoracic_cavity": (0, -20, 1350), "pelvic_cavity": (0, -20, 930),
            "right_obturator_foramen": (45, -15, 875),
            "left_obturator_foramen": (-45, -15, 875),
        }
        for name, point in voids.items():
            with self.subTest(void=name):
                self.assertEqual(self.empty_hits(point), [])
        for name, point in (("sternum", (0, -80, 1350)),
                            ("fifth_thoracic_vertebra", (0, 45, 1380)),
                            ("right_hip", (70, -15, 875)),
                            ("left_hip", (-70, -15, 875))):
            with self.subTest(solid=name):
                self.assertGreater(self.probe(name, point), 0.01)

    def test_no_large_accidental_bone_intersections(self):
        names = list(self.objects)
        boxes = {name: self.objects[name].manifold.bounding_box() for name in names}
        rows = []
        for index, first in enumerate(names):
            a = boxes[first]
            for second in names[index + 1:]:
                b = boxes[second]
                overlap = [min(a[k + 3], b[k + 3]) - max(a[k], b[k]) for k in range(3)]
                if min(overlap) <= 0.02:
                    continue
                volume = abs(float((self.objects[first].manifold
                                    ^ self.objects[second].manifold).volume()))
                if volume > 1e-4:
                    rows.append((volume, first, second))
        rows.sort(reverse=True)
        # Слуховые косточки намеренно расположены внутри височной области и
        # сочленяются друг с другом. Все остальные контакты — только локальные
        # суставные/шовные перекрытия исходной анатомической модели.
        ordinary = [row for row in rows if not any(
            token in row[1] or token in row[2]
            for token in ("malleus", "incus", "stapes"))]
        self.assertLess(ordinary[0][0], 250.0, ordinary[:10])
        self.assertLess(max(row[0] for row in rows), 250.0, rows[:10])

    def test_exported_glb_is_complete_closed_and_attributed(self):
        data = self.glb()
        scene = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
        self.assertEqual(len(scene.graph.nodes_geometry), 206)
        self.assertEqual(sum(len(mesh.faces) for mesh in scene.geometry.values()), 400168)
        bad = []
        for name, mesh in scene.geometry.items():
            mesh = mesh.copy()
            mesh.merge_vertices(digits_vertex=5, merge_tex=True, merge_norm=True)
            mesh.remove_unreferenced_vertices()
            edges = np.sort(np.asarray(mesh.edges), axis=1)
            _, counts = np.unique(edges, axis=0, return_counts=True)
            areas = np.asarray(mesh.area_faces)
            faces = np.sort(np.asarray(mesh.faces), axis=1)
            row = (name, mesh.is_watertight, mesh.is_winding_consistent,
                   int(np.sum(counts == 1)), int(np.sum(counts > 2)),
                   int(np.sum(~np.isfinite(areas) | (areas <= 1e-10))),
                   int(len(faces) - len(np.unique(faces, axis=0))))
            if (not row[1] or not row[2] or any(row[3:])):
                bad.append(row)
        self.assertEqual(bad, [])
        doc, _ = _glb_read(data)
        self.assertIn("AnatomyTOOL", doc["asset"].get("copyright", ""))
        self.assertIn("CC BY-SA 4.0", doc["asset"]["extras"]["license"])
        self.assertIn("b78fc8e711dac5809a35f16209dc27a3df9f054d",
                      doc["asset"]["extras"]["source"])


class SkeletonImportTest(unittest.TestCase):
    def test_named_nodes_share_one_cached_scene_and_keep_orientation(self):
        _glb_scene_cached.cache_clear()
        _glb_node_cached.cache_clear()
        femur_v, femur_f = load_any(ASSET, scale=1000, node="FMA24474")
        frontal_v, frontal_f = load_any(ASSET, scale=1000, node="FMA52734")
        info = _glb_scene_cached.cache_info()
        self.assertEqual((info.misses, info.hits), (1, 1))
        self.assertEqual((len(femur_f), len(frontal_f)), (4790, 7630))
        self.assertGreater(femur_v[:, 0].min(), 0)
        self.assertLess(frontal_v[:, 1].max(), 0)
        self.assertAlmostEqual(femur_v[:, 2].max(), 902.8484497, places=4)
        before = femur_v.copy()
        load_any(ASSET, scale=1000, repair=True, node="FMA24474")
        np.testing.assert_array_equal(femur_v, before)
        with self.assertRaises(GeometryError):
            load_any(ASSET, node="FMA_DOES_NOT_EXIST")

    def test_bundled_asset_resolves_outside_source_checkout(self):
        old = Path.cwd()
        with tempfile.TemporaryDirectory() as temp:
            os.chdir(temp)
            try:
                with patch.object(sys, "_MEIPASS", str(ROOT), create=True):
                    self.assertEqual(resolve_file("examples/assets/human_skeleton.glb"), ASSET)
            finally:
                # Windows не удаляет временный каталог, пока он является cwd.
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
