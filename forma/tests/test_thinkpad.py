"""Приёмка цельного ThinkPad X1 Carbon Gen 11 и его рабочих анимаций."""

from __future__ import annotations

import io
import unittest

import manifold3d as mf
import numpy as np
import trimesh

from forma.fonts import FALLBACK, glyph_strokes, text_solid
from forma.geometry import _glb_read, manifold_mesh
from forma.ops import rotate, translate
from forma.run import build
from forma.webui import EXAMPLES, load_example


class ThinkPadX1Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(load_example("thinkpad_x1"), analyze_model=True)
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

    def intersection(self, first: str, second: str) -> float:
        return abs(float((self.objects[first].manifold
                          ^ self.objects[second].manifold).volume()))

    def probe(self, name: str, point, edge: float = 0.25) -> float:
        tool = mf.Manifold.cube((edge, edge, edge), True).translate(point)
        return abs(float((self.objects[name].manifold ^ tool).volume()))

    def closed_lid(self):
        pivot = (0, 96, 12.4)
        return {name: rotate(self.objects[name].manifold, 110, (1, 0, 0), pivot)
                for name in self.scene.groups["lid_assembly"]}

    def test_registered_and_internal_checks(self):
        self.assertIn(("Ноутбук ThinkPad X1 Carbon Gen 11", "thinkpad_x1"), EXAMPLES)
        analysis = self.payload["analysis"]
        self.assertEqual(analysis["checks_total"], 22)
        self.assertEqual(analysis["checks_passed"], 22)
        self.assertTrue(all(check["ok"] for check in analysis["checks"]))
        self.assertEqual(analysis["metrics"]["visible_count"], 66)
        self.assertEqual(len(self.objects["keyboard_caps"].manifold.decompose()), 78)
        self.assertEqual(len(self.scene.groups["lid_assembly"]), 29)

    def test_dimensions_key_pitch_and_polygon_budget(self):
        metrics = self.payload["analysis"]["metrics"]
        expected_open = (-157.8, -111.25, 0.0, 157.8, 169.66516486177113,
                         207.15129565787953)
        np.testing.assert_allclose(metrics["bbox"], expected_open, atol=1e-8)
        actual_tris = sum(obj.stats()["tris"] for obj in self.objects.values()
                          if obj.visible)
        self.assertLessEqual(actual_tris, 85000)

        def center(name):
            bb = self.objects[name].manifold.bounding_box()
            return np.asarray([(bb[i] + bb[i + 3]) / 2.0 for i in range(3)])

        self.assertAlmostEqual(center("key_j")[0] - center("key_h")[0], 18.0)
        self.assertAlmostEqual(center("key_k")[0] - center("key_j")[0], 18.0)
        bb = self.objects["trackpad"].manifold.bounding_box()
        np.testing.assert_allclose(np.asarray(bb[3:]) - np.asarray(bb[:3]),
                                   (110, 56, 0.5), atol=1e-6)
        screen = self.objects["screen_active"].manifold.bounding_box()
        self.assertAlmostEqual(screen[3] - screen[0], 301.7, places=5)

    def test_real_port_and_speaker_voids(self):
        # На оси разъёма зонд пуст, а в соседней стенке остаётся материал.
        self.assertLess(self.probe("base_lower", (-157.7, 70, 5.9)), 1e-8)
        self.assertGreater(self.probe("base_lower", (-150, 70, 5.9)), 0.01)
        self.assertLess(self.probe("base_lower", (157.7, 60, 5.9)), 1e-8)
        self.assertGreater(self.probe("base_lower", (150, 60, 5.9)), 0.01)
        self.assertLess(self.probe("deck", (-148.2, -22, 10.6)), 1e-8)
        self.assertGreater(self.probe("deck", (-146.6, -22, 10.6)), 0.01)

    def test_key_and_trackpad_travel_has_real_clearance(self):
        # Ниши должны быть глубже полного хода: клавиша не проваливается в
        # деку или подложку даже в нижней точке анимации.
        for name, travel in (("key_h", -0.55), ("key_j", -0.55),
                             ("key_k", -0.55), ("key_space", -0.55),
                             ("trackpad", -0.30)):
            for dz in (0.0, travel):
                with self.subTest(name=name, dz=dz):
                    moved = translate(self.objects[name].manifold, (0, 0, dz))
                    for other in ("keyboard_bed", "deck"):
                        volume = abs(float((moved ^ self.objects[other].manifold).volume()))
                        self.assertLess(volume, 1e-6, (name, dz, other))

    def test_closed_dimensions_and_hinge_clearance(self):
        closed = self.closed_lid()
        lo = np.full(3, np.inf)
        hi = np.full(3, -np.inf)
        for name, obj in self.objects.items():
            if not obj.visible:
                continue
            bb = closed.get(name, obj.manifold).bounding_box()
            lo = np.minimum(lo, bb[:3])
            hi = np.maximum(hi, bb[3:])
        np.testing.assert_allclose(lo, (-157.8, -111.25, 0), atol=1e-8)
        np.testing.assert_allclose(hi, (157.8, 111.25, 15.36), atol=1e-8)

        # Крышка вращается около задней оси и не проходит сквозь деку/днище.
        for angle in (0, 15, 30, 45, 60, 75, 90, 110):
            with self.subTest(angle=angle):
                shell = rotate(closed["lid_shell"], -angle, (1, 0, 0), (0, 96, 12.4))
                self.assertLess(abs(float((shell ^ self.objects["base_lower"].manifold).volume())), 1e-5)
                self.assertLess(abs(float((shell ^ self.objects["deck"].manifold).volume())), 1e-5)
        for name, solid in closed.items():
            for other in ("keyboard_caps", "keyboard_legends", "deck"):
                volume = abs(float((solid ^ self.objects[other].manifold).volume()))
                self.assertLess(volume, 1e-5, (name, other))

    def test_glb_animation_channels_and_dim_display(self):
        timeline = self.payload["timeline"]
        self.assertEqual(timeline["scenes"], ["крышка", "клавиши"])
        self.assertEqual(timeline["scene_durations"], {"крышка": 6.3, "клавиши": 2.45})
        self.assertEqual(timeline["count"], 15)
        doc, _ = _glb_read(self.glb())
        animations = doc.get("animations", [])
        self.assertEqual(len(animations), 12)
        turns = [a for a in animations if a.get("name", "").startswith("FormaTurn")]
        moves = [a for a in animations if a.get("name", "").startswith("FormaMove")]
        self.assertEqual((len(turns), len(moves)), (2, 10))
        for animation in turns:
            paths = {c["target"]["path"] for c in animation["channels"]}
            self.assertEqual(paths, {"rotation", "translation"})
            self.assertTrue(all(doc["nodes"][c["target"]["node"]].get("name") == "lid_assembly"
                                for c in animation["channels"]))
        move_targets = {doc["nodes"][c["target"]["node"]].get("name")
                        for a in moves for c in a["channels"]}
        self.assertEqual(move_targets, {"key_h_assembly", "key_j_assembly", "key_k_assembly",
                                        "key_space_assembly", "trackpad_assembly"})
        self.assertTrue(all(c["target"]["path"] == "translation"
                            for a in moves for c in a["channels"]))
        materials = {m.get("name"): m for m in doc.get("materials", [])}
        for name, strength in (("mat_screen_active", 0.18), ("mat_windows_0", 0.35)):
            extension = materials[name]["extensions"]["KHR_materials_emissive_strength"]
            self.assertEqual(extension["emissiveStrength"], strength)

    def test_glb_after_blender_style_position_weld(self):
        scene = trimesh.load(io.BytesIO(self.glb()), file_type="glb", process=False)
        self.assertEqual(len(scene.geometry), 66)
        self.assertEqual(sum(len(mesh.faces) for mesh in scene.geometry.values()),
                         sum(obj.stats()["tris"] for obj in self.objects.values() if obj.visible))
        for name, original in scene.geometry.items():
            with self.subTest(name=name):
                mesh = original.copy()
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

    def test_r_and_backslash_glyphs_weld_cleanly(self):
        self.assertNotEqual(glyph_strokes("\\"), FALLBACK)
        for char in ("R", "\\"):
            with self.subTest(char=char):
                solid, _ = text_solid(char, size=2.75, depth=0.2)
                vertices, faces = manifold_mesh(solid)
                mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
                mesh.merge_vertices(digits_vertex=5, merge_tex=True, merge_norm=True)
                mesh.remove_unreferenced_vertices()
                self.assertTrue(mesh.is_watertight)
                self.assertTrue(np.all(np.asarray(mesh.area_faces) > 1e-10))
                edges = np.sort(np.asarray(mesh.edges), axis=1)
                _, counts = np.unique(edges, axis=0, return_counts=True)
                self.assertTrue(np.all(counts == 2))


if __name__ == "__main__":
    unittest.main()
