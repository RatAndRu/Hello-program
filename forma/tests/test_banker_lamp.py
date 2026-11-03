"""Геометрическая приёмка проекта Arte Lamp Banker A2492LT-1AB."""
from __future__ import annotations

import itertools
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
from forma.links import analyse  # noqa: E402
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

    def test_crown_and_large_turned_parts_are_real_geometry(self):
        shade = self.scene.objects["абажур"].manifold
        center_hits = shade.ray_cast([0, 0, 250], [0, 0, 500])
        end_hits = shade.ray_cast([119, 0, 250], [119, 0, 500])
        self.assertTrue(center_hits and end_hits)
        center_top = max(hit.position[2] for hit in center_hits)
        end_top = max(hit.position[2] for hit in end_hits)
        # Продольный свод виден в силуэте, а не только в счётчике треугольников.
        self.assertAlmostEqual(center_top, 400.0, places=2)
        self.assertLess(end_top, center_top - 10.0)
        base = self.scene.objects["основание"].manifold.num_tri()
        column = self.scene.objects["колонна"].manifold.num_tri()
        self.assertLess(base + column, 6_000)

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
        for name, expected in (("абажур", 397.6), ("вкладыш", 396.4)):
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

    def test_all_pair_intersections_are_only_mechanical_interfaces(self):
        # Это не разрешение на произвольные пересечения: перечислены только
        # скрытые посадки штифтов/шарниров, сварные углы и шнур внутри бусин.
        allowed = {
            frozenset(pair) for pair in [
                ("шарнир_седло", "шарнир"), ("шарнир", "стойка"),
                ("крепление_л", "набалдашник_л"),
                ("крепление_п", "набалдашник_п"),
                ("держатель_л", "держатель_перекладина"),
                ("держатель_п", "держатель_перекладина"),
                ("держатель_перекладина", "стойка"),
                ("крепление_цепочки", "цепочка_штифт"),
                ("крепление_цепочки", "цепочка_001"),
                ("крепление_цепочки", "цепочка_сердечник"),
                ("цепочка_сердечник", "наконечник"),
            ]
        }
        allowed |= {frozenset(("цепочка_сердечник", f"цепочка_{i:03d}"))
                    for i in range(1, 31)}
        unexpected = []
        solids = self.scene.visible_solids()
        for a, b in itertools.combinations(solids, 2):
            ba, bb = a.manifold.bounding_box(), b.manifold.bounding_box()
            if not all(ba[i] <= bb[i + 3] + 1e-7 and bb[i] <= ba[i + 3] + 1e-7
                       for i in range(3)):
                continue
            volume = abs(float((a.manifold ^ b.manifold).volume()))
            if volume > 1e-3 and frozenset((a.name, b.name)) not in allowed:
                unexpected.append((a.name, b.name, volume))
        self.assertFalse(unexpected, unexpected)

    def test_script_acceptance_checks_pass(self):
        checks = self.result.analysis.get("checks", [])
        self.assertGreaterEqual(len(checks), 12)
        self.assertFalse([c for c in checks if not c.get("ok")], checks)

    def test_mesh_budget_is_measured_per_part(self):
        solids = self.scene.visible_solids()
        total = sum(s.manifold.num_tri() for s in solids)
        base = self.scene.objects["основание"].manifold.num_tri()
        column = self.scene.objects["колонна"].manifold.num_tri()
        # До переработки: 84 276 всего, из них 71 248 на основании/колонне.
        self.assertLess(total, 20_000)
        self.assertLess(base, 6_000)
        self.assertLess(column, 6_000)
        self.assertLess(base + column, 10_000)

    def test_mounts_have_contact_without_accidental_intersection(self):
        zero_overlap = [
            ("основание", "колонна"), ("абажур", "вкладыш"),
            ("абажур", "стойка"), ("вкладыш", "патрон_подвес"),
            ("крепление_цепочки", "абажур"), ("рама_абажура", "абажур"),
            ("держатель_л", "абажур"), ("держатель_п", "абажур"),
            ("цепочка_001", "цепочка_002"), ("цепочка_030", "наконечник"),
        ]
        for left, right in zero_overlap:
            with self.subTest(pair=f"{left}/{right}"):
                a, b = self.scene.objects[left], self.scene.objects[right]
                overlap = abs(float((a.manifold ^ b.manifold).volume()))
                self.assertLess(overlap, 1e-3)
        contacts = [
            ("основание", "колонна"), ("крепление_цепочки", "абажур"),
            ("вкладыш", "патрон_подвес"), ("цепочка_001", "цепочка_002"),
            ("цепочка_030", "наконечник"),
            ("абажур", "вкладыш_фиксатор_л"), ("вкладыш", "вкладыш_фиксатор_л"),
        ]
        for left, right in contacts:
            with self.subTest(contact=f"{left}/{right}"):
                a, b = self.scene.objects[left], self.scene.objects[right]
                self.assertLessEqual(float(a.manifold.min_gap(b.manifold, 100.0)), 0.05)

    def test_no_floating_parts_in_contact_graph(self):
        report = analyse(self.scene.visible_solids())
        self.assertEqual(report["groups"], 1, report["loose"])
        self.assertEqual(report["loose"], [])

    def test_driving_dimension_rebuilds_dependent_geometry(self):
        result = build(self.path.read_text(encoding="utf-8"), analyze_model=False,
                       overrides={"base_h": 78, "column_h": 999, "column_top": 999})
        self.assertTrue(result.ok, result.error)
        scene = result.scene
        self.assertAlmostEqual(scene.params["column_h"], 97.5)
        self.assertAlmostEqual(scene.params["column_top"], 175.5)
        self.assertAlmostEqual(scene.objects["основание"].manifold.bounding_box()[5], 78.0)
        column_box = scene.objects["колонна"].manifold.bounding_box()
        self.assertAlmostEqual(column_box[2], 78.0)
        self.assertAlmostEqual(column_box[5], 175.5)
        self.assertAlmostEqual(scene.objects["шарнир"].manifold.bounding_box()[2], 177.5)
        self.assertAlmostEqual(scene.objects["абажур"].manifold.bounding_box()[5], 400.0)
        self.assertTrue(any(link["name"] == "column_h" for link in scene.dimension_links))

    def test_arm_links_remain_ordered_at_parameter_extreme(self):
        result = build(self.path.read_text(encoding="utf-8"), analyze_model=True,
                       overrides={"base_h": 100, "column_ratio": 1.8})
        self.assertTrue(result.ok, result.error)
        params = result.scene.params
        self.assertLess(params["joint_z"] + 8, params["arm_z1"])
        self.assertLess(params["arm_z1"], params["arm_z2"])
        self.assertLess(params["arm_z2"], params["arm_z3"])
        self.assertLess(params["arm_z3"], 340.0)
        self.assertFalse([c for c in result.analysis.get("checks", []) if not c.get("ok")])
        self.assertEqual(analyse(result.visible_solids())["groups"], 1)

    def test_glb_contains_editable_parts(self):
        data = export_glb(self.scene.visible_solids(), groups=dict(self.scene.groups))
        self.assertEqual(data[:4], b"glTF")
        json_length = int.from_bytes(data[12:16], "little")
        document = json.loads(data[20:20 + json_length])
        self.assertGreaterEqual(len(document.get("nodes", [])), 12)
        self.assertTrue(any(node.get("name") == "абажур" for node in document["nodes"]))


if __name__ == "__main__":
    unittest.main()
