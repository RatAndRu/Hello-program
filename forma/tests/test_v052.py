from __future__ import annotations

import io
import json
import shutil
import struct
import subprocess
import unittest
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh

from forma.geometry import export_glb, manifold_mesh
from forma.run import build


def ok(script):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"build failed: {result.error}\n{result.log}")
    return result


def center(solid):
    bb = solid.manifold.bounding_box()
    return np.asarray([(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2,
                       (bb[2] + bb[5]) / 2])


def overlap_volume(solid, point, size=0.3):
    probe = mf.Manifold.cube((size, size, size), True).translate(point)
    return abs(float((solid.manifold ^ probe).volume()))


def glb_json(data):
    length, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A
    return json.loads(data[20:20 + length].decode("utf-8"))


class GroupCopiesTest(unittest.TestCase):
    def test_group_transforms_all_members_without_baking(self):
        result = ok("""a = box size=[4,4,4] at=[-10,0,0] color=#ff0000
b = box size=[4,4,4] at=[10,0,0] color=#00ff00
g = group [a,b]
rotate [g] angle=90 axis=z
translate [g] offset=[0,5,0]
scale [g] factor=2""")
        scene = result.scene
        self.assertEqual(set(scene.objects), {"a", "b"})
        self.assertEqual(scene.groups["g"], ["a", "b"])
        self.assertEqual(scene.objects["a"].color, "#ff0000")
        self.assertEqual(scene.objects["b"].color, "#00ff00")
        self.assertAlmostEqual(center(scene.objects["a"])[1], -15, places=4)
        self.assertAlmostEqual(center(scene.objects["b"])[1], 25, places=4)
        self.assertAlmostEqual(scene.objects["a"].manifold.bounding_box()[3] -
                               scene.objects["a"].manifold.bounding_box()[0], 8, places=4)

    def test_pack_is_separate_colored_editable_copies(self):
        result = ok("""a = box size=[10,10,15] color=#ff0000
b = box size=[8,12,20] color=#00ff00
host = box size=[70,30,3] at=[0,0,0]
books = array [a,b] mode=pack on=host count=4 gap=1 as=objects scale=[1,1] turn=0 seed=2
color books_002 #123456""")
        scene = result.scene
        self.assertEqual(len(scene.groups["books"]), 4)
        self.assertFalse(scene.objects["a"].visible)
        self.assertFalse(scene.objects["b"].visible)
        self.assertEqual(scene.objects["books_001"].color, "#ff0000")
        self.assertEqual(scene.objects["books_002"].color, "#123456")
        self.assertEqual(scene.objects["books_003"].color, "#ff0000")
        for index in range(1, 4):
            left = scene.objects[f"books_{index:03d}"].manifold.bounding_box()
            right = scene.objects[f"books_{index + 1:03d}"].manifold.bounding_box()
            self.assertGreaterEqual(right[0] - left[3], 1 - 1e-5)

    def test_linear_array_sequences_real_prototypes(self):
        result = ok("""a = box size=[5,6,7] color=#ff0000
b = box size=[9,10,11] color=#00ff00
row = array [a,b] mode=linear count=4 offset=[20,0,0] as=objects sequence=loop""")
        scene = result.scene
        self.assertEqual(scene.objects["row_001"].color, "#ff0000")
        self.assertEqual(scene.objects["row_002"].color, "#00ff00")
        first = scene.objects["row_001"].manifold.bounding_box()
        second = scene.objects["row_002"].manifold.bounding_box()
        self.assertAlmostEqual(first[5] - first[2], 7, places=4)
        self.assertAlmostEqual(second[5] - second[2], 11, places=4)

    def test_scatter_seed_and_non_overlap(self):
        script = """a = box size=[5,5,5] color=#ff0000
b = box size=[4,4,8] color=#00ff00
host = box size=[90,90,3] at=[0,0,0]
items = scatter [a,b] on=host count=10 gap=0.5 inset=5 as=objects seed=3"""
        first, second = ok(script), ok(script)
        names = first.scene.groups["items"]
        self.assertEqual(len(names), 10)
        for name in names:
            np.testing.assert_allclose(first.scene.objects[name].manifold.bounding_box(),
                                       second.scene.objects[name].manifold.bounding_box(), atol=1e-6)
            bb = first.scene.objects[name].manifold.bounding_box()
            self.assertAlmostEqual(bb[2], 3.0, places=4)
        # Радиус, использованный отбором, консервативен: реальные AABB тоже не пересекаются в XY.
        for i, left_name in enumerate(names):
            lb = first.scene.objects[left_name].manifold.bounding_box()
            for right_name in names[i + 1:]:
                rb = first.scene.objects[right_name].manifold.bounding_box()
                overlaps = (min(lb[3], rb[3]) > max(lb[0], rb[0]) and
                            min(lb[4], rb[4]) > max(lb[1], rb[1]))
                self.assertFalse(overlaps, (left_name, right_name))


class InteriorAssembliesTest(unittest.TestCase):
    def test_table_parts_and_real_splay(self):
        plain = ok("t = table legs=4 shelf=да splay=0")
        splayed = ok("t = table legs=4 shelf=да splay=10")
        self.assertIn("t.leg_04", plain.scene.objects)
        self.assertIn("t.shelf", plain.scene.objects)
        self.assertEqual(len(plain.visible_solids()), 6)
        a = plain.scene.objects["t.leg_01"].manifold.bounding_box()
        b = splayed.scene.objects["t.leg_01"].manifold.bounding_box()
        self.assertGreater(b[3] - b[0], a[3] - a[0] + 5)
        self.assertEqual(plain.scene.objects["t"].meta["interior_params"]["legs"], 4)
        square = ok("t = table leg_shape=square")
        leg_bb = square.scene.objects["t.leg_01"].manifold.bounding_box()
        self.assertAlmostEqual(leg_bb[2], 0.0, places=5)
        self.assertAlmostEqual(leg_bb[5], 70.0, places=5)

    def test_table_accepts_custom_top_and_leg(self):
        result = ok("""top = box size=[100,60,4] color=#885533
leg = cylinder radius=3 height=20 color=#333333
t = table [top] leg_object=leg height=50 legs=4 layout=inset""")
        scene = result.scene
        top_bb = scene.objects["t"].manifold.bounding_box()
        leg_bb = scene.objects["t.leg_01"].manifold.bounding_box()
        self.assertAlmostEqual(top_bb[5], 50.0, places=5)
        self.assertAlmostEqual(top_bb[3] - top_bb[0], 100.0, places=5)
        self.assertAlmostEqual(leg_bb[5] - leg_bb[2], 46.0, places=5)
        self.assertEqual(scene.objects["t"].color, "#885533")
        self.assertEqual(scene.objects["t.leg_01"].color, "#333333")

    def test_door_leaf_moves_only_leaf_and_hardware(self):
        result = ok("""door = door width=90 height=210 panels=2 columns=1 hinges=2
rotate [door.leaf] angle=30 axis=z pivot=[-44.4,-2.69,0]""")
        scene = result.scene
        for name in ("door.frame_right", "door.frame_top", "door.leaf",
                     "door.leaf.panel_01", "door.hinge_01", "door.leaf.handle",
                     "door.leaf.lock"):
            self.assertIn(name, scene.objects)
        self.assertEqual(scene.objects["door"].meta["leaf_object"], "door.leaf")
        leaf_bb = scene.objects["door.leaf"].manifold.bounding_box()
        self.assertAlmostEqual(leaf_bb[2], 0.6, places=5)
        self.assertAlmostEqual(leaf_bb[5], 210.0, places=5)
        moved = ok("""door = door width=90 height=210 panels=2 columns=1 hinges=2
rotate [door.leaf] angle=30 axis=z pivot=[-44.4,-2.69,0]""")
        # Корневая стойка и правая коробка не изменились; полотно и ручка повернуты.
        reference = ok("door = door width=90 height=210 panels=2 columns=1 hinges=2")
        for name in ("door", "door.frame_right", "door.frame_top"):
            np.testing.assert_allclose(moved.scene.objects[name].manifold.bounding_box(),
                                       reference.scene.objects[name].manifold.bounding_box(), atol=1e-6)
        self.assertFalse(np.allclose(moved.scene.objects["door.leaf.handle"].manifold.bounding_box(),
                                     reference.scene.objects["door.leaf.handle"].manifold.bounding_box()))

    def test_door_root_transforms_frame_leaf_and_hardware_together(self):
        base = ok("door = door width=90 height=210 panels=2 columns=1 hinges=2")
        moved = ok("""door = door width=90 height=210 panels=2 columns=1 hinges=2
translate [door] offset=[11,22,33]""")
        self.assertEqual(set(base.scene.objects), set(moved.scene.objects))
        for name in base.scene.objects:
            before = np.asarray(base.scene.objects[name].manifold.bounding_box())
            after = np.asarray(moved.scene.objects[name].manifold.bounding_box())
            np.testing.assert_allclose(after - before, [11, 22, 33, 11, 22, 33],
                                       atol=1e-5, err_msg=name)

    def test_curtain_is_volume_and_has_separate_hardware(self):
        result = ok("c = curtain width=100 height=150 folds=5 fold_depth=6 thickness=0.2")
        cloth = result.scene.objects["c"]
        self.assertEqual(cloth.manifold.status(), mf.Error.NoError)
        self.assertGreater(cloth.manifold.volume(), 1000)
        self.assertGreater(cloth.manifold.num_tri(), 1000)
        self.assertIn("c.rod", result.scene.objects)
        self.assertIn("c.ring_06", result.scene.objects)
        self.assertEqual(len(result.visible_solids()), 8)

    def test_rug_layers_pattern_deformation_and_budget(self):
        flat = ok("r = rug wave=0 lift=0 fringe=none stitches=нет binding=0")
        result = ok("r = rug wave=0.8 lift=9 pattern=круги fringe=ends stitches=да")
        scene = result.scene
        for name in ("r.pad", "r.border", "r.binding", "r.stitches", "r.fringe"):
            self.assertIn(name, scene.objects)
        self.assertTrue(scene.objects["r"].paint[0]["pattern"])
        self.assertGreater(scene.objects["r"].manifold.bounding_box()[5],
                           flat.scene.objects["r"].manifold.bounding_box()[5] + 5)
        self.assertLess(sum(s.manifold.num_tri() for s in result.visible_solids()), 30000)
        self.assertLessEqual(scene.objects["r.fringe"].meta.get("assembly_root") == "r", True)


class ElectricalTest(unittest.TestCase):
    def test_socket_holes_go_through_plate_and_insert(self):
        result = ok("s = socket sockets=1 holes=6 pin_pitch=19 ground=да")
        plate_bb = result.scene.objects["s"].manifold.bounding_box()
        self.assertAlmostEqual(plate_bb[2], 0.0, places=5)
        self.assertAlmostEqual(plate_bb[5], 86.0, places=5)
        for name in ("s", "s.insert_1"):
            self.assertAlmostEqual(overlap_volume(result.scene.objects[name], (-9.5, 0, 43)), 0, places=6)
            self.assertAlmostEqual(overlap_volume(result.scene.objects[name], (9.5, 0, 43)), 0, places=6)
        self.assertGreater(overlap_volume(result.scene.objects["s.insert_1"], (0, -5.5, 55)), 0)
        two = ok("s = socket sockets=2 width=0")
        bb = two.scene.objects["s"].manifold.bounding_box()
        self.assertGreater(bb[3] - bb[0], 150)

    def test_switch_state_changes_geometry(self):
        on = ok("s = switch rockers=2 state=on angle=8 led=да")
        off = ok("s = switch rockers=2 state=off angle=8 led=да")
        on_vertices, _ = manifold_mesh(on.scene.objects["s.rocker_1"].manifold)
        off_vertices, _ = manifold_mesh(off.scene.objects["s.rocker_1"].manifold)
        self.assertFalse(np.allclose(on_vertices, off_vertices))
        self.assertTrue(on.scene.objects["s.led_1"].emissive)
        self.assertIn("s.rocker_2", on.scene.objects)
        plate_bb = on.scene.objects["s"].manifold.bounding_box()
        led_bb = on.scene.objects["s.led_1"].manifold.bounding_box()
        self.assertAlmostEqual(plate_bb[2], 0.0, places=5)
        self.assertAlmostEqual(plate_bb[5], 86.0, places=5)
        self.assertGreater(led_bb[2], plate_bb[2])
        self.assertLess(led_bb[5], plate_bb[5])

    def test_detail_color_parameters_are_declared_and_applied(self):
        curtain = ok("c = curtain rod=да rings=да rod_color=#123456")
        self.assertEqual(curtain.scene.objects["c.rod"].color, "#123456")
        rug = ok("r = rug pad=0.2 fringe=ends fringe_count=2 pattern=полосы "
                 "pad_color=#111213 fringe_color=#212223 pattern_color=#313233")
        self.assertEqual(rug.scene.objects["r.pad"].color, "#111213")
        self.assertEqual(rug.scene.objects["r.fringe"].color, "#212223")
        self.assertEqual(rug.scene.objects["r"].paint[0]["color"], "#313233")
        socket = ok("s = socket insert_color=#414243 metal_color=#515253")
        self.assertEqual(socket.scene.objects["s.insert_1"].color, "#414243")
        self.assertEqual(socket.scene.objects["s.screw_1"].color, "#515253")
        switch = ok("s = switch corner=2 led=да led_color=#616263 metal_color=#717273")
        self.assertEqual(switch.scene.objects["s.led_1"].color, "#616263")
        self.assertEqual(switch.scene.objects["s.screw_1"].color, "#717273")
        bulb = ok("b = bulb base_color=#818283")
        self.assertEqual(bulb.scene.objects["b.base"].color, "#818283")

    def test_bulb_glass_is_hollow_and_parts_are_separate(self):
        result = ok("b = bulb shape=a60 base=E27 diameter=60 height=110 glass_wall=0.6 thread=нет glow=нет")
        scene = result.scene
        glass = scene.objects["b"]
        self.assertEqual(glass.manifold.status(), mf.Error.NoError)
        self.assertGreater(glass.transmission, 0.9)
        self.assertTrue(glass.meta["hollow_glass"])
        for name in ("b.base", "b.contact", "b.insulator"):
            self.assertIn(name, scene.objects)
        z = 20 - 0.8 + (110 - 20 + 0.8) * 0.34
        self.assertAlmostEqual(overlap_volume(glass, (0, 0, z), 0.5), 0, places=6)
        self.assertGreater(overlap_volume(glass, (29.7, 0, z), 0.25), 0)
        vertices, _ = manifold_mesh(glass.manifold)
        near_top = vertices[vertices[:, 2] > 105]
        self.assertGreater(float(np.max(np.linalg.norm(near_top[:, :2], axis=1))), 8.0)
        threaded = ok("b = bulb thread=да glow=да")
        self.assertIn("b.thread", threaded.scene.objects)
        self.assertTrue(threaded.scene.objects["b.glow"].emissive)
        self.assertGreater(threaded.scene.objects["b.thread"].manifold.num_tri(), 100)


class LiveToolCardsTest(unittest.TestCase):
    def test_every_interior_card_script_builds(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node не установлен")
        script = Path(__file__).resolve().parent / "interior_tools_test.js"
        completed = subprocess.run([node, str(script), "--json"], check=True,
                                   capture_output=True, text=True, timeout=30)
        scripts = json.loads(completed.stdout)
        self.assertEqual(set(scripts), {"table", "door", "window", "curtain", "drape",
                                       "rug", "socket", "switch", "bulb"})
        for op, source in scripts.items():
            with self.subTest(op=op):
                result = build(source, analyze_model=False)
                self.assertTrue(result.ok, result.error)
                self.assertTrue(result.visible_solids())


class ClothAndInterferenceTest(unittest.TestCase):
    def test_drape_deforms_mesh_contacts_support_and_preserves_lengths(self):
        result = ok("""cloth = box size=[140,110,0.4] at=[0,0,35]
host = box size=[90,70,20] at=[0,0,0]
d = drape [cloth] on=host iterations=40 detail=16 pin=none""")
        cloth = result.scene.objects["d"].meta["cloth"]
        self.assertGreater(cloth["vertices"], 40)
        self.assertGreater(cloth["contacts"], 0)
        self.assertEqual(cloth["free"], cloth["vertices"])
        self.assertLess(cloth["max_strain"], 0.12)
        self.assertFalse(cloth["self_collision"])
        self.assertFalse(result.scene.objects["cloth"].visible)
        bb = result.scene.objects["d"].manifold.bounding_box()
        self.assertLess(bb[2], 20)
        self.assertGreater(bb[5], 20)

    def test_drape_pins_and_flat_plane(self):
        result = ok("""cloth = box size=[60,40,0.3] at=[0,0,20]
d = drape [cloth] z=0 iterations=25 detail=12 pin=corners gap=0.05""")
        meta = result.scene.objects["d"].meta["cloth"]
        self.assertEqual(meta["pinned"], 4)
        self.assertGreater(meta["free"], 0)
        flat = ok("""cloth = box size=[60,40,0.3] at=[0,0,5]
d = drape [cloth] z=0 iterations=20 detail=12 pin=none gap=0.05""")
        self.assertLess(flat.scene.objects["d"].meta["cloth"]["max_strain"], 1e-6)

    def test_interference_exact_volume_allow_and_payload(self):
        result = ok("""a = box size=[10,10,10]
b = box size=[10,10,10] at=[5,0,0]
interference [a,b] tolerance=0.01""")
        report = result.scene.interferences[-1]
        self.assertEqual(report["count"], 1)
        self.assertAlmostEqual(report["pairs"][0]["volume_mm3"], 500.0, places=5)
        self.assertIn("interferences", result.payload())
        allowed = ok("""a = box size=[10,10,10]
b = box size=[10,10,10] at=[5,0,0]
interference [a,b] allow="a:b" """)
        self.assertEqual(allowed.scene.interferences[-1]["count"], 0)
        self.assertEqual(allowed.scene.interferences[-1]["allowed"], 1)
        separate = ok("""a = box size=[10,10,10]
b = box size=[10,10,10] at=[30,0,0]
interference [a,b]""")
        self.assertEqual(separate.scene.interferences[-1]["candidates"], 0)

    def test_interference_skips_registered_contacts_of_one_assembly(self):
        result = ok("t = table shelf=да\ninterference")
        report = result.scene.interferences[-1]
        self.assertGreater(report["skipped_parts"], 0)
        self.assertEqual(report["count"], 0)
        self.assertGreater(report["objects"], 3)

    def test_glb_export_preserves_editable_parts(self):
        result = ok("""t = table width=80 length=60 height=50 shelf=да at=[0,0,0]
d = door width=50 height=100 panels=2 at=[150,0,0]
b = bulb height=70 diameter=40 at=[250,0,0] thread=нет
s = socket at=[350,0,0]""")
        data = export_glb(result.visible_solids())
        doc = glb_json(data)
        names = {node.get("name") for node in doc.get("nodes", [])}
        for expected in ("t.shelf", "d.leaf.handle", "b.contact", "s.insert_1"):
            self.assertIn(expected, names)
        loaded = trimesh.load(io.BytesIO(data), file_type="glb", process=False)
        self.assertGreaterEqual(len(loaded.geometry), 10)


if __name__ == "__main__":
    unittest.main()
