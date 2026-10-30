"""0.57: геометрическая приёмка сосудов, велоцепи и исправленных деталей."""

from __future__ import annotations

import io
import json
import struct
import unittest

import manifold3d as mf
import numpy as np
import trimesh

from forma.geometry import solid_parts
from forma.ops import OPS
from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"{result.error}\n{script}")
    return result


def valid(m: mf.Manifold):
    assert m.status() == mf.Error.NoError
    assert not m.is_empty() and m.volume() > 0
    assert solid_parts(m) == 1
    return m


def overlap(first, second) -> float:
    return abs(float((first.manifold ^ second.manifold).volume()))


def probe(obj, point, edge=0.5) -> float:
    tool = mf.Manifold.cube((edge, edge, edge), True).translate(point)
    return abs(float((obj.manifold ^ tool).volume()))


def glb_json(data: bytes) -> dict:
    length, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A
    return json.loads(data[20:20 + length])


class RailHoleTest(unittest.TestCase):
    def test_every_rail_has_real_through_holes(self):
        plain = ok("п = track length=300 rails=2 sleepers=нет")
        drilled = ok("п = track length=300 rails=2 sleepers=нет rail_holes=3 rail_hole_d=8")
        self.assertEqual(set(drilled.scene.objects), {"п", "п.rail_right"})
        for name, x in (("п", -90.0), ("п.rail_right", 90.0)):
            obj = drilled.scene.objects[name]
            valid(obj.manifold)
            self.assertEqual(obj.manifold.genus(), 3, name)
            self.assertLess(obj.manifold.volume(), plain.scene.objects[name].manifold.volume())
            p = obj.meta.get("primitive_params", drilled.scene.objects["п"].meta["primitive_params"])
            self.assertEqual(p["rail_holes"], 3)
            self.assertEqual(p["rail_hole_positions"], [-75.0, 0.0, 75.0])
            for y in (-75.0, 0.0, 75.0):
                self.assertLess(probe(obj, (x, y, 12.5)), 1e-8, (name, y))
                self.assertGreater(probe(obj, (x, y, 18.0)), 0.01, (name, y))
        self.assertFalse(build("п = track rail_profile=брусок rail_holes=2").ok)
        self.assertFalse(build("п = track rail_holes=2 rail_hole_d=30").ok)


class BicycleChainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = ok("ц = bicycle_chain links=5")
        cls.objects = cls.result.scene.objects

    def test_real_repeating_parts_and_selectability(self):
        self.assertEqual(len(self.objects), 23)
        expected = {"bicycle_plate": 8, "bicycle_roller": 5,
                    "bicycle_bushing": 5, "bicycle_pin": 5}
        self.assertEqual({kind: sum(o.kind == kind for o in self.objects.values())
                          for kind in expected}, expected)
        for name, obj in self.objects.items():
            with self.subTest(part=name):
                valid(obj.manifold)
                self.assertEqual(obj.meta.get("assembly_root"), "ц")
                self.assertTrue(obj.meta.get("parent") or name == "ц")
        self.assertEqual(self.objects["ц"].meta["primitive_params"]["pitch"], 12.7)
        self.assertEqual(self.objects["ц.roller_1"].manifold.genus(), 1)
        self.assertEqual(self.objects["ц.bushing_1"].manifold.genus(), 1)
        self.assertEqual(self.objects["ц"].manifold.genus(), 2)

    def test_pins_rollers_bushings_and_plates_do_not_overlap(self):
        pairs = (("ц", "ц.pin_1"), ("ц", "ц.roller_1"),
                 ("ц.inner_plate_2_a", "ц.bushing_2"),
                 ("ц.inner_plate_2_a", "ц.pin_2"),
                 ("ц.roller_1", "ц.bushing_1"),
                 ("ц.roller_1", "ц.pin_1"),
                 ("ц.bushing_1", "ц.pin_1"),
                 ("ц", "ц.inner_plate_2_a"))
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                self.assertLess(overlap(self.objects[first], self.objects[second]), 1e-6)

    def test_all_parts_survive_blender_compatible_export(self):
        data = self.result.glb()
        doc = glb_json(data)
        self.assertEqual(len(doc.get("nodes", [])), 23)
        for node in doc["nodes"]:
            self.assertEqual((node.get("extras") or {}).get("formaName"), node.get("name"))
        scene = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
        self.assertEqual(len(scene.geometry), 23)
        for name, mesh in scene.geometry.items():
            with self.subTest(mesh=name):
                mesh.merge_vertices(merge_tex=True, merge_norm=True)
                self.assertTrue(mesh.is_watertight)
                self.assertTrue(mesh.is_winding_consistent)


class JarTest(unittest.TestCase):
    def test_forms_cavity_thread_bottom_and_cap(self):
        variants = {}
        for form in ("цилиндр", "округлая", "квадратная"):
            result = ok(f"б = jar form={form} cap=да")
            variants[form] = result
            body = result.scene.objects["б"]
            cap = result.scene.objects["б.lid"]
            valid(body.manifold)
            valid(cap.manifold)
            self.assertEqual(cap.meta.get("parent"), "б")
            self.assertEqual(cap.meta.get("assembly_root"), "б")
            self.assertLess(overlap(body, cap), 1e-6)
            self.assertLess(probe(body, (0, 0, 105)), 1e-8, "горлышко должно быть открыто")
            self.assertGreater(probe(body, (39.3, 0, 45)), 0.001)
            self.assertGreater(body.transmission, 0.8)
            self.assertEqual(body.meta["primitive_params"]["form"], form)
        self.assertEqual(len({round(r.scene.objects["б"].manifold.volume(), 3)
                              for r in variants.values()}), 3)
        threaded = variants["округлая"].scene.objects["б"]
        plain = ok("б = jar form=округлая thread=нет ribs=40").scene.objects["б"]
        self.assertGreater(threaded.manifold.volume(), plain.manifold.volume())
        self.assertGreater(threaded.manifold.num_tri(), plain.manifold.num_tri())

    def test_punt_and_circular_bottom_ribs_are_geometry(self):
        punt = ok("б = jar bottom=углубление ribs=0 thread=нет").scene.objects["б"]
        flat = ok("б = jar bottom=плоское ribs=0 thread=нет").scene.objects["б"]
        ribbed = ok("б = jar bottom=углубление ribs=40 thread=нет").scene.objects["б"]
        hit = punt.manifold.ray_cast([0, 0, -10], [0, 0, 30])
        self.assertTrue(hit)
        self.assertGreater(float(hit[0].position[2]), 4.0)
        flat_hit = flat.manifold.ray_cast([0, 0, -10], [0, 0, 30])
        self.assertAlmostEqual(float(flat_hit[0].position[2]), 0.0, delta=1e-5)
        self.assertLess(ribbed.manifold.volume(), punt.manifold.volume())
        self.assertNotAlmostEqual(ribbed.manifold.volume(), punt.manifold.volume(), places=3)


class BottleTest(unittest.TestCase):
    def test_glass_plastic_necks_and_closures(self):
        glass = ok("б = bottle kind=стекло neck=длинная closure=пробка")
        body = glass.scene.objects["б"]
        cork = glass.scene.objects["б.cork"]
        valid(body.manifold)
        valid(cork.manifold)
        self.assertFalse(body.meta["primitive_params"]["thread"])
        self.assertEqual(cork.meta["parent"], "б")
        self.assertLess(overlap(body, cork), 1e-6)
        rounded = ok("б = bottle kind=пластик neck=округлая closure=крышка")
        self.assertIn("б.cap", rounded.scene.objects)
        self.assertTrue(rounded.scene.objects["б"].meta["primitive_params"]["thread"])
        self.assertLess(overlap(rounded.scene.objects["б"], rounded.scene.objects["б.cap"]), 1e-6)
        self.assertNotAlmostEqual(body.manifold.volume(),
                                    rounded.scene.objects["б"].manifold.volume(), places=2)
        self.assertGreater(rounded.scene.objects["б"].density, 1.0)
        self.assertLess(rounded.scene.objects["б"].density, 1.2)

    def test_five_plastic_feet_and_punt_are_not_decoration(self):
        plastic = ok("б = bottle kind=пластик bottom=ножки").scene.objects["б"]
        valid(plastic.manifold)
        self.assertAlmostEqual(plastic.manifold.bounding_box()[2], 0.0, delta=1e-5)
        band = mf.Manifold.cube((200, 200, 0.3), True).translate((0, 0, 0.5))
        feet = plastic.manifold ^ band
        self.assertEqual(solid_parts(feet), 5, "на нижнем срезе должны быть пять отдельных лапок")
        punt = ok("б = bottle kind=пластик bottom=углубление").scene.objects["б"]
        self.assertNotAlmostEqual(plastic.manifold.volume(), punt.manifold.volume(), places=2)
        self.assertNotEqual(plastic.manifold.num_tri(), punt.manifold.num_tri())
        for neck in ("длинная", "округлая"):
            result = ok(f"б = bottle neck={neck}")
            self.assertEqual(result.scene.objects["б"].meta["primitive_params"]["neck"], neck)


class StandaloneLidTest(unittest.TestCase):
    def test_jar_and_bottle_lids_have_open_undersides(self):
        for kind, height in (("банка", 8.0), ("бутылка", 13.0)):
            result = ok(f"к = lid kind={kind}")
            body = result.scene.objects["к"]
            valid(body.manifold)
            self.assertLess(probe(body, (0, 0, 1.0)), 1e-8)
            self.assertGreater(probe(body, (0, 0, height - 0.4)), 0.005)
            self.assertEqual(body.meta["primitive_params"]["kind"], kind)
            smooth = ok(f"к = lid kind={kind} ribs=0 thread=нет").scene.objects["к"]
            self.assertNotAlmostEqual(body.manifold.volume(), smooth.manifold.volume(), places=2)

    def test_pot_lid_handle_rim_fasteners_and_vent_are_separate_and_fitted(self):
        result = ok("к = lid kind=кастрюля material=стекло handle=скоба vent=да")
        objects = result.scene.objects
        self.assertEqual(set(objects), {"к", "к.rim", "к.handle", "к.fastener_1",
                                       "к.fastener_2", "к.vent"})
        for name, obj in objects.items():
            with self.subTest(part=name):
                valid(obj.manifold)
                self.assertEqual(obj.meta["assembly_root"], "к")
        self.assertEqual(objects["к"].manifold.genus(), 3)
        self.assertEqual(objects["к.rim"].manifold.genus(), 1)
        self.assertGreater(objects["к"].transmission, 0.8)
        for other in ("к.rim", "к.handle", "к.fastener_1", "к.fastener_2", "к.vent"):
            self.assertLess(overlap(objects["к"], objects[other]), 1e-5, other)
        for fastener in ("к.fastener_1", "к.fastener_2"):
            self.assertLess(overlap(objects["к.handle"], objects[fastener]), 1e-5)
        knob = ok("к = lid kind=кастрюля material=металл handle=кнопка")
        self.assertIn("к.handle", knob.scene.objects)
        self.assertNotIn("к.rim", knob.scene.objects)
        self.assertLess(overlap(knob.scene.objects["к"], knob.scene.objects["к.handle"]), 1e-5)
        self.assertLess(overlap(knob.scene.objects["к"], knob.scene.objects["к.fastener_1"]), 1e-5)


class SwitchRevisionTest(unittest.TestCase):
    def test_double_modern_and_old_rockers_have_distinct_real_shapes(self):
        double = ok("в = switch rockers=2 style=современная")
        self.assertAlmostEqual(double.scene.objects["в"].manifold.bounding_box()[3], 43.0)
        self.assertIn("в.rocker_2", double.scene.objects)
        modern = double.scene.objects["в.rocker_1"]
        old = ok("в = switch style=старая").scene.objects["в.rocker_1"]
        valid(modern.manifold)
        valid(old.manifold)
        self.assertNotAlmostEqual(modern.manifold.volume(), old.manifold.volume(), places=2)
        self.assertGreater(old.manifold.bounding_box()[1] * -1, 3.5)
        self.assertEqual(double.scene.objects["в"].meta["interior_params"]["style"], "современная")


class RegistryAndHelpTest(unittest.TestCase):
    def test_cards_orientations_and_no_legacy_zigzag_parameter(self):
        from forma.orient_notes import PRIMITIVE_ORIENTATIONS
        for op in ("jar", "bottle", "lid", "bicycle_chain"):
            self.assertIn(op, OPS)
            self.assertTrue(OPS[op].summary)
            self.assertTrue(OPS[op].example)
            self.assertIn(op, PRIMITIVE_ORIENTATIONS)
        self.assertNotIn("zigzags", OPS["lightning"].params)


if __name__ == "__main__":
    unittest.main()
