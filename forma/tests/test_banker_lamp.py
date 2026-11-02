"""Геометрическая приёмка проекта Arte Lamp Banker A2492LT-1AB."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forma.geometry import export_glb  # noqa: E402
from forma.run import build  # noqa: E402


class BankerLampTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / "examples" / "arte_lamp_banker_a2492lt_1ab.forma"
        cls.result = build(cls.path.read_text(encoding="utf-8"))
        if not cls.result.ok:
            raise AssertionError(cls.result.error)
        cls.scene = cls.result.scene

    def test_reference_dimensions_and_height(self):
        solids = self.scene.visible_solids()
        bounds = np.asarray([s.manifold.bounding_box() for s in solids], dtype=float)
        self.assertAlmostEqual(float(bounds[:, 2].min()), 0.0, places=4)
        self.assertAlmostEqual(float(bounds[:, 5].max()), 400.0, places=4)
        base = self.scene.objects["основание"].manifold.bounding_box()
        self.assertAlmostEqual(base[3] - base[0], 180.0, places=3)
        shade = self.scene.objects["абажур"].manifold.bounding_box()
        self.assertAlmostEqual(shade[3] - shade[0], 240.0, places=3)
        self.assertAlmostEqual(shade[5], 400.0, places=3)
        self.assertAlmostEqual(shade[2], 310.0, places=3)

    def test_major_parts_are_separate_and_selectable(self):
        names = ["абажур", "вкладыш", "лампочка", "основание", "колонна",
                 "шарнир", "стойка", "крепление_л", "крепление_п", "держатель_л",
                 "держатель_п", "наконечник"]
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, self.scene.objects)
                self.assertTrue(self.scene.objects[name].visible)
                self.assertEqual(self.scene.objects[name].manifold.status(), mf.Error.NoError)
                self.assertGreater(self.scene.objects[name].manifold.volume(), 0.0)
        self.assertIn("цепочка", self.scene.groups)
        self.assertEqual(len(self.scene.groups["цепочка"]), 30)
        for name in self.scene.groups["цепочка"]:
            self.assertTrue(self.scene.objects[name].visible)

    def test_shade_has_real_open_cavity_and_inner_liner(self):
        probe = mf.Manifold.cube((12, 12, 12), True).translate((0, 0, 335))
        for name in ("абажур", "вкладыш"):
            overlap = abs(float((self.scene.objects[name].manifold ^ probe).volume()))
            self.assertLess(overlap, 1e-5, name)
        liner = self.scene.objects["вкладыш"]
        self.assertLess(liner.manifold.volume(), self.scene.objects["абажур"].manifold.volume())
        self.assertEqual(liner.manifold.status(), mf.Error.NoError)
        # Луч снизу не должен встретить крышку на z=310: сначала идёт внутренняя арка.
        for name, expected in (("абажур", 397.8), ("вкладыш", 397.2)):
            hits = self.scene.objects[name].manifold.ray_cast([0, 0, 250], [0, 0, 500])
            self.assertTrue(hits, name)
            self.assertAlmostEqual(min(hit.position[2] for hit in hits), expected, places=2)

    def test_project_is_in_permanent_catalog(self):
        from forma.webui import EXAMPLES, load_example
        key = "arte_lamp_banker_a2492lt_1ab"
        self.assertIn(key, [item[1] for item in EXAMPLES])
        self.assertEqual(load_example(key), self.path.read_text(encoding="utf-8"))

    def test_no_unintended_large_intersections(self):
        pairs = [("абажур", "основание"), ("абажур", "колонна"),
                 ("цепочка_001", "основание"), ("цепочка_001", "колонна")]
        for left, right in pairs:
            volume = abs(float((self.scene.objects[left].manifold ^
                                self.scene.objects[right].manifold).volume()))
            self.assertLess(volume, 1e-4, f"{left}/{right}")

    def test_glb_contains_editable_parts(self):
        data = export_glb(self.scene.visible_solids(), groups=dict(self.scene.groups))
        self.assertEqual(data[:4], b"glTF")
        json_length = int.from_bytes(data[12:16], "little")
        document = json.loads(data[20:20 + json_length])
        self.assertGreaterEqual(len(document.get("nodes", [])), 12)
        self.assertTrue(any(node.get("name") == "абажур" for node in document["nodes"]))


if __name__ == "__main__":
    unittest.main()
