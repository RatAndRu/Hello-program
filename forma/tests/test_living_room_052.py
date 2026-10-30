"""Регресс пересобранной гостиной 0.52 и её Blender-совместимого GLB."""

from __future__ import annotations

import importlib.util
import io
import json
import struct
import unittest
from pathlib import Path

import numpy as np
import trimesh

from forma.geometry import _glb_valid_faces, manifold_mesh
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "docs" / "make_living_room.py"
SPEC = importlib.util.spec_from_file_location("living_room_052_generator", GENERATOR)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SCENE_PATH = ROOT / "examples" / "living_room_diorama.forma"
validate = MODULE.validate


class LivingRoom052Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCENE_PATH.read_text(encoding="utf-8")
        cls.result = build(cls.script, analyze_model=False)
        if not cls.result.ok:
            raise AssertionError(f"{cls.result.error}\n{cls.result.log}")
        cls.report, cls.solids = validate(cls.result)

    def test_scene_is_valid_and_has_no_unexpected_intersections(self):
        self.assertEqual(self.report["problems"], [])
        self.assertEqual(self.report["unexpected_collisions"], [])
        self.assertEqual(self.report["bookcase_frame_overlaps"], [])
        self.assertGreater(self.report["objects"], 200)
        self.assertLess(self.report["triangles"], 150_000)
        self.assertEqual(self.report["door_opening_residual_mm3"], 0)
        self.assertEqual(self.report["window_opening_residual_mm3"], 0)

    def test_structural_joints_are_contacts_not_hidden_gaps(self):
        self.assertEqual(self.report["problems"], [])
        self.assertGreaterEqual(len(self.report["bookcase_frame_contacts"]), 17)
        self.assertTrue(all(x["gap_mm"] <= 0.02
                            for x in self.report["bookcase_frame_contacts"]))
        self.assertTrue(all(x["gap_mm"] <= 0.02 for x in self.report["support_contacts"]))
        self.assertTrue(all(x["volume_mm3"] <= 80.0
                            for x in self.report["bookcase_frame_contacts"]))
        objects = self.result.scene.objects
        for name in ("bookcase_shelf_0", "bookcase_shelf_1", "bookcase_shelf_2"):
            with self.subTest(shelf=name):
                self.assertLessEqual(objects[name].manifold.min_gap(
                    objects["bookcase_back"].manifold, 1.0), 0.02)

    def test_new_tools_are_real_editable_parts_of_the_room(self):
        objects = self.result.scene.objects
        for name in ("entry.leaf", "entry.leaf.lock", "curtain_left", "curtain_right",
                     "living_rug.border", "living_rug.fringe", "throw", "coffee",
                     "coffee.leg_03", "wall_socket.insert_1", "wall_switch.rocker_1",
                     "lamp_bulb", "lamp_bulb.thread"):
            with self.subTest(name=name):
                self.assertIn(name, objects)
                self.assertGreater(objects[name].manifold.volume(), 0)
        self.assertEqual(len([n for n in objects if n.startswith("books_")]), 15)
        self.assertEqual(len([n for n in objects if n.startswith("floorboards_")]), 12)
        self.assertEqual(len(self.result.scene.groups["remote"]), 9)
        self.assertGreater(objects["throw"].meta["cloth"]["contacts"], 0)
        self.assertGreater(objects["throw"].meta["cloth"]["pinned"], 0)

    def test_support_heights_and_lowercase_special_text(self):
        self.assertAlmostEqual(self.report["remote_bottom_z"], 29.6, places=5)
        self.assertAlmostEqual(self.report["cup_bottom_z"], 29.6, places=5)
        self.assertIn('text "Гостиная 1:20"', self.script)
        self.assertIn('text "Forma & 3D"', self.script)
        self.assertIn('text "living / 02"', self.script)

    def test_glb_preserves_editable_composite_names(self):
        data = self.result.glb()
        json_length = struct.unpack_from('<I', data, 12)[0]
        document = json.loads(data[20:20 + json_length])
        names = {node.get('name', '') for node in document.get('nodes', [])}
        self.assertTrue({'entry', 'entry.leaf', 'wall_socket',
                         'wall_socket.insert_1', 'wall_switch', 'bookcase_back'} <= names)

    def test_glb_scene_reimports_with_finite_geometry(self):
        data = self.result.glb()
        self.assertGreater(len(data), 1_000_000)
        scene = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
        self.assertGreaterEqual(len(scene.geometry), len(self.solids))
        # GLB законно не содержит нулевые boolean-следы. Сравниваем с исходником,
        # очищенным тем же узким фильтром, а не возвращаем вырожденные грани.
        source_triangles = 0
        for obj in self.solids:
            verts, faces = manifold_mesh(obj.manifold)
            source_triangles += len(_glb_valid_faces(verts, faces))
        self.assertEqual(sum(len(mesh.faces) for mesh in scene.geometry.values()),
                         source_triangles)
        for name, mesh in scene.geometry.items():
            with self.subTest(mesh=name):
                self.assertTrue(np.isfinite(mesh.vertices).all())
                self.assertGreater(len(mesh.faces), 0)
                self.assertGreater(float(mesh.volume), 1e-8)


if __name__ == "__main__":
    unittest.main()
