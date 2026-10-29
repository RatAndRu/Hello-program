"""Регресс одиночного плацкартного вагона 61-4194 и его GLB."""

from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh

from forma.dsl import parse_script
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "docs" / "make_train_carriage.py"
SPEC = importlib.util.spec_from_file_location("train_carriage_generator", GENERATOR)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SCENE_PATH = ROOT / "examples" / "train_carriage.forma"


class TrainCarriageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCENE_PATH.read_text(encoding="utf-8")
        cls.result = build(cls.script, analyze_model=False)
        if not cls.result.ok:
            raise AssertionError(f"{cls.result.error}\n{cls.result.log}")
        cls.report, cls.solids = MODULE.validate(cls.result)

    def test_generator_matches_editable_single_car_scene(self):
        self.assertEqual(self.script, MODULE.make_script())
        self.assertGreater(len(parse_script(self.script)), 1900)
        self.assertTrue(self.report["single_car"])
        self.assertIn("wagon", self.result.scene.groups)
        self.assertIn("track", self.result.scene.groups)
        objects = self.result.scene.objects
        self.assertEqual(len([n for n in objects if n == "car_roof"]), 1)
        self.assertEqual(len([n for n in objects if n.startswith("bogie_") and n.endswith("_kingpin")]), 2)
        self.assertEqual(len([n for n in objects if n.startswith("coupler_") and n.endswith("_head")]), 2)
        for token in ("loft", "lathe", "spring", "grating", "sweep", "array", "scatter",
                      "socket", "switch", 'text "РЖД"'):
            with self.subTest(tool=token):
                self.assertIn(token, self.script)
        self.assertNotIn("import", self.script.lower())
        self.assertNotIn("texture_file", self.script.lower())

    def test_geometry_layout_openings_and_connections(self):
        self.assertEqual(self.report["problems"], [])
        self.assertEqual(self.report["degenerate_faces"], [])
        self.assertGreater(self.report["objects"], 1100)
        self.assertGreater(self.report["triangles"], 300_000)
        self.assertLess(self.report["triangles"], 500_000)
        self.assertEqual(self.report["berths"], {
            "main_lower": 18, "main_upper": 18, "side_lower": 9, "side_upper": 9,
            "passenger_total": 54, "crew": 2,
        })
        self.assertEqual(self.report["support_counts"], {
            "luggage_brackets": 18, "side_rail_posts": 18, "ladder_hooks": 18,
        })
        self.assertTrue(all(x["residual_mm3"] == 0 for x in self.report["opening_probes"]))
        self.assertEqual(len(self.report["opening_probes"]), 30)
        self.assertTrue(all(x["residual_mm3"] == 0 for x in self.report["interior_door_probes"]))
        self.assertEqual(len(self.report["interior_door_probes"]), 4)
        for key in ("aisle_obstructions", "wheel_rail_intersections",
                    "underfloor_running_intersections", "unexpected_structural_intersections",
                    "service_panel_intersections", "furniture_intersections"):
            with self.subTest(check=key):
                self.assertEqual(self.report[key], [])

    def test_structural_contacts_include_gap_acceptance(self):
        self.assertEqual(self.report["problems"], [])
        self.assertGreaterEqual(len(self.report["structural_gaps"]), 20)
        self.assertTrue(all(x["gap_mm"] <= 0.02 for x in self.report["structural_gaps"]))
        # Контрольные соединения крыши/стен остаются явными в отчёте, а не
        # исчезают под общим разрешением на пересечения.
        self.assertTrue(self.report["structural_contacts"])

    def test_reference_dimensions_and_rotated_text_placement(self):
        expected = {"body_width_mm": 155.25, "coupler_axes_mm": 1226.85,
                    "wagon_base_mm": 850.0, "bogie_base_mm": 120.0,
                    "wheel_diameter_mm": 47.5, "wheel_contact_z": 0.0, "rail_head_z": 0.0,
                    "rail_gauge_mm": 76.0}
        for key, value in expected.items():
            with self.subTest(dimension=key):
                self.assertAlmostEqual(self.report["dimensions"][key], value, places=3)
        for name, sign, x in (("logo_far_rzd", 1, -260), ("logo_near_rzd", -1, -260),
                              ("number_far_text", 1, 480), ("number_near_text", -1, 480)):
            center = self.report["placement"][name]
            with self.subTest(text=name):
                self.assertGreater(center[1] * sign, 77)
                self.assertAlmostEqual(center[0], x, places=5)
        for name in ("side_number_01", "side_number_09"):
            self.assertLess(self.report["placement"][name][1], -43)
        for value in ("РЖД", "61-4194  РЖД", "54 МЕСТА", "АВАРИЙНЫЙ"):
            self.assertIn(f'text "{value}"', self.script)

    def test_glb_reimports_with_same_faces_and_bounds(self):
        data = self.result.glb()
        self.assertGreater(len(data), 1_000_000)
        scene = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
        self.assertGreaterEqual(len(scene.geometry), len(self.solids))
        self.assertEqual(sum(len(mesh.faces) for mesh in scene.geometry.values()), self.report["triangles"])
        for name, mesh in scene.geometry.items():
            with self.subTest(mesh=name):
                self.assertTrue(np.isfinite(mesh.vertices).all())
                self.assertGreater(len(mesh.faces), 0)
                self.assertGreater(float(mesh.volume), 1e-8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "train.glb"
            path.write_bytes(data)
            roundtrip = MODULE.glb_roundtrip(self.result, path, self.solids)
        self.assertEqual(roundtrip["faces"], self.report["triangles"])
        self.assertLess(roundtrip["max_bounds_deviation_mm"], 0.002)
        self.assertEqual(roundtrip["axis_map"], "glTF(x,y,z) = Forma(x,z,-y)")

    def test_interior_views_filter_same_solids_without_second_car(self):
        interior = MODULE.interior_solids(self.solids)
        self.assertLess(len(interior), len(self.solids))
        self.assertTrue(all(any(item is original for original in self.solids) for item in interior))
        names = {s.name for s in interior}
        self.assertNotIn("car_roof", names)
        self.assertNotIn("car_wall_near", names)
        self.assertNotIn("int_wall_lower_m1", names)
        self.assertFalse(any(n.startswith("track_") for n in names))
        self.assertIn("car_wall_far", names)
        self.assertIn("berth_main_05_1_lower_mattress", names)
        self.assertEqual(len(self.result.visible_solids()), len(self.solids))


if __name__ == "__main__":
    unittest.main()
