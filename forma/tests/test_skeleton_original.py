"""Проверки нового скелета, построенного только собственной геометрией Forma."""
from __future__ import annotations

import io
import json
from pathlib import Path
import struct
import unittest

import trimesh

from forma.run import build
from forma.skeleton_original import (EXPECTED, audit_original_skeleton,
                                      build_original_skeleton, intersection_report)

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "examples" / "human_skeleton_original.forma"


def _script():
    return PROJECT.read_text(encoding="utf-8")


def _height(bones):
    lo = min(b.solid.bounding_box()[2] for b in bones)
    hi = max(b.solid.bounding_box()[5] for b in bones)
    return hi-lo


class OriginalSkeletonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bones = build_original_skeleton()

    def test_full_inventory_and_solids(self):
        report = audit_original_skeleton(self.bones)
        self.assertEqual(report["counts"], EXPECTED)
        self.assertEqual(report["defects"], [])
        self.assertEqual(len({b.name for b in self.bones}), 206)
        self.assertTrue(all(b.solid.status().name == "NoError" for b in self.bones))
        self.assertTrue(all(b.solid.volume() > 0 for b in self.bones))
        self.assertGreater(report["triangles"], 100_000)
        for side in ("r", "l"):
            self.assertEqual(
                {b.name for b in self.bones if b.name.startswith("hand_phalanx_1_") and b.name.endswith(side)},
                {f"hand_phalanx_1_proximal_{side}", f"hand_phalanx_1_distal_{side}"})
            self.assertEqual(
                {b.name for b in self.bones if b.name.startswith("foot_phalanx_1_") and b.name.endswith(side)},
                {f"foot_phalanx_1_proximal_{side}", f"foot_phalanx_1_distal_{side}"})

    def test_no_interpenetrating_bones(self):
        # Порог отбрасывает только численный шум; прежние суставные пересечения
        # были на три–четыре порядка больше и устранены самой геометрией.
        self.assertEqual(intersection_report(self.bones, min_volume=1.0), [])

    def test_height_is_real_parameter(self):
        small = build_original_skeleton(1200)
        large = build_original_skeleton(2200)
        self.assertAlmostEqual(_height(small), 1200, places=4)
        self.assertAlmostEqual(_height(large), 2200, places=4)
        v_small = sum(b.solid.volume() for b in small)
        v_large = sum(b.solid.volume() for b in large)
        expected = (2200/1200)**3
        self.assertAlmostEqual(v_large/v_small, expected, delta=expected*1e-5)

    def test_project_dsl_and_embedded_checks(self):
        result = build(_script())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(result.scene.objects), 206)
        self.assertEqual(len(result.scene.groups["скелет"]), 206)
        self.assertTrue(all(s.meta["origin"] == "original_parametric" for s in result.scene.objects.values()))
        self.assertEqual(len(result.analysis["checks"]), 16)
        self.assertTrue(all(c["ok"] for c in result.analysis["checks"]))

    def test_no_mesh_import_or_old_asset_dependency(self):
        executable = [line.split("#", 1)[0] for line in _script().splitlines()]
        self.assertFalse(any(" import " in f" {line} " for line in executable))
        source = (ROOT / "forma" / "skeleton_original.py").read_text(encoding="utf-8")
        self.assertNotIn("human_skeleton.glb", source)
        self.assertNotIn("prepare_human_skeleton", source)

    def test_project_is_registered_in_ui_examples(self):
        from forma.webui import EXAMPLES
        self.assertIn("human_skeleton_original", [key for _title, key in EXAMPLES])

    def test_glb_is_standard_and_reopenable(self):
        result = build(_script())
        self.assertTrue(result.ok, result.error)
        data = result.glb()
        self.assertEqual(data[:4], b"glTF")
        json_len, json_type = struct.unpack_from("<I4s", data, 12)
        self.assertEqual(json_type, b"JSON")
        document = json.loads(data[20:20+json_len])
        self.assertEqual(len(document["meshes"]), 206)
        self.assertEqual(sum("mesh" in node for node in document["nodes"]), 206)
        scene = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
        self.assertEqual(len(scene.geometry), 206)
        for mesh in scene.geometry.values():
            # GLB вправе дублировать одну позицию ради разных UV/normals.
            mesh.merge_vertices(digits_vertex=5, merge_tex=True, merge_norm=True)
            self.assertTrue(mesh.is_watertight)
            self.assertTrue(mesh.is_winding_consistent)
            self.assertGreater(len(mesh.faces), 0)


if __name__ == "__main__":
    unittest.main()
