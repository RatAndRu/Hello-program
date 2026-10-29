"""Полная выбираемость составных деталей и двусторонние двери/окна."""
from __future__ import annotations

import json
import struct
import unittest

import manifold3d as mf
import numpy as np

from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"{result.error}\n{script}")
    for solid in result.visible_solids():
        if solid.manifold.status() != mf.Error.NoError or solid.manifold.is_empty():
            raise AssertionError((solid.name, solid.manifold.status()))
    return result


def glb_json(data: bytes) -> dict:
    length, kind = struct.unpack_from("<II", data, 12)
    assert kind == 0x4E4F534A
    return json.loads(data[20:20 + length])


def assert_mirror(test: unittest.TestCase, front, back) -> None:
    fb, bb = front.manifold.bounding_box(), back.manifold.bounding_box()
    np.testing.assert_allclose([fb[0], fb[2], fb[3], fb[5]],
                               [bb[0], bb[2], bb[3], bb[5]], atol=2e-4)
    test.assertAlmostEqual(fb[1], -bb[4], delta=2e-4)
    test.assertAlmostEqual(fb[4], -bb[1], delta=2e-4)


class CanonicalSelectionTest(unittest.TestCase):
    def test_every_track_and_hinge_part_has_canonical_glb_name(self):
        result = ok("путь = track length=140 rails=2 sleeper_count=2\n"
                    "петля = hinge height=60 leaf_width=25 at=[0,300,0]")
        doc = glb_json(result.glb())
        nodes = {node.get("name"): node for node in doc.get("nodes", [])}
        for solid in result.visible_solids():
            with self.subTest(name=solid.name):
                self.assertIn(solid.name, nodes)
                self.assertEqual((nodes[solid.name].get("extras") or {}).get("formaName"),
                                 solid.name)
        for index in (1, 2):
            self.assertIn(f"путь.sleeper_{index:02d}", result.scene.objects)
        self.assertIn("путь.rail_right", result.scene.objects)
        self.assertIn("петля.right", result.scene.objects)


class TwoSidedDoorTest(unittest.TestCase):
    SCRIPT = ("d = door width=90 height=210 panels=2 columns=1 hinges=2 "
              "handle_form=прямоугольная handle_rosette=круглая handle_resolution=.2 "
              "lock=да lock_plug=да lock_offset=10 lock_d=3")

    def test_all_front_and_back_parts_are_present_and_symmetric(self):
        result = ok(self.SCRIPT)
        scene = result.scene
        pairs = [("d.leaf.handle", "d.leaf.handle_back"),
                 ("d.leaf.lock", "d.leaf.lock_back"),
                 ("d.leaf.lock_plug", "d.leaf.lock_plug_back"),
                 ("d.leaf.panel_01", "d.leaf.panel_back_01"),
                 ("d.leaf.panel_02", "d.leaf.panel_back_02")]
        for left, right in pairs:
            with self.subTest(pair=(left, right)):
                self.assertIn(left, scene.objects)
                self.assertIn(right, scene.objects)
                assert_mirror(self, scene.objects[left], scene.objects[right])
        for index in (1, 2):
            self.assertIn(f"d.hinge_{index:02d}", scene.objects)
            self.assertIn(f"d.leaf.hinge_{index:02d}", scene.objects)
        self.assertTrue(scene.objects["d"].meta["interior_params"]["both_sides"])
        # Скважина проходит через полотно и отдельную замочную планку.
        leaf = scene.objects["d.leaf"].manifold
        self.assertEqual(leaf.ray_cast([33, -20, 95.36], [33, 20, 95.36]), [])
        plate = scene.objects["d.leaf.lock"].manifold
        self.assertEqual(plate.ray_cast([33, -20, 95.36], [33, 20, 95.36]), [])

    def test_hardware_is_on_stile_and_hinges_do_not_touch(self):
        result = ok("d = door panels=4 columns=2 hinges=3 lock_plug=да handle_resolution=.2")
        scene = result.scene
        panels = [solid for name, solid in scene.objects.items() if ".panel" in name]
        hardware = [scene.objects[name] for name in
                    ("d.leaf.handle", "d.leaf.handle_back", "d.leaf.lock_plug", "d.leaf.lock_plug_back")]
        for panel in panels:
            for fitting in hardware:
                with self.subTest(panel=panel.name, fitting=fitting.name):
                    overlap = panel.manifold ^ fitting.manifold
                    self.assertLess(abs(overlap.volume()), 1e-6)
        hinges = [scene.objects[f"d.hinge_{index:02d}"].manifold.bounding_box()
                  for index in (1, 2, 3)]
        for lower, upper in zip(hinges, hinges[1:]):
            self.assertGreater(upper[2] - lower[5], 1.0)

    def test_leaf_rotation_moves_both_handles_and_moving_hinge(self):
        base = ok(self.SCRIPT)
        moved = ok(self.SCRIPT + "\nrotate [d.leaf] angle=30 axis=z pivot=[-44.4,-2.69,0]")
        for name in ("d.leaf.handle", "d.leaf.handle_back", "d.leaf.lock_back",
                     "d.leaf.hinge_01", "d.leaf.panel_back_01"):
            with self.subTest(moved=name):
                self.assertFalse(np.allclose(base.scene.objects[name].manifold.bounding_box(),
                                             moved.scene.objects[name].manifold.bounding_box()))
        for name in ("d", "d.frame_right", "d.hinge_01"):
            np.testing.assert_allclose(base.scene.objects[name].manifold.bounding_box(),
                                       moved.scene.objects[name].manifold.bounding_box(), atol=1e-6)


class WindowFamilyTest(unittest.TestCase):
    def test_ordinary_panoramic_and_composite_have_real_parts(self):
        ordinary = ok("w = window handle_resolution=.2")
        self.assertEqual(len(ordinary.scene.objects), 20)
        self.assertIn("w.sash_01.glass", ordinary.scene.objects)
        self.assertIn("w.sash_02.handle", ordinary.scene.objects)
        self.assertGreater(ordinary.scene.objects["w.sash_01.glass"].transmission, 0.9)
        assert_mirror(self, ordinary.scene.objects["w.casing_front_left"],
                      ordinary.scene.objects["w.casing_back_left"])
        self.assertIn("w.sill", ordinary.scene.objects)

        panoramic = ok("w = window type=панорамное width=260 height=210 sections=3")
        self.assertEqual(len(panoramic.scene.objects), 12)
        self.assertFalse(any(n.endswith(".handle") for n in panoramic.scene.objects))
        self.assertFalse(any("casing" in n or n.endswith(".sill") for n in panoramic.scene.objects))
        self.assertEqual(panoramic.scene.objects["w"].meta["interior_params"]["opening"], "нет")

        composite = ok("w = window type=составное width=220 height=150 sections=3 rows=2 "
                       "handle_resolution=.2")
        self.assertEqual(len(composite.scene.objects), 34)
        self.assertEqual(len([n for n in composite.scene.objects if n.endswith(".handle")]), 4)
        self.assertEqual(len([n for n in composite.scene.objects if ".transom_" in n]), 3)
        self.assertNotIn("w.sash_02.handle", composite.scene.objects)

    def test_open_angle_moves_only_openable_sash_with_glass_and_handle(self):
        source = ("w = window type=составное width=220 height=150 sections=3 rows=2 "
                  "handle_resolution=.2 casing=нет sill=нет")
        closed = ok(source + " open_angle=0")
        opened = ok(source + " open_angle=25")
        for name in ("w.sash_01", "w.sash_01.glass", "w.sash_01.handle"):
            self.assertFalse(np.allclose(closed.scene.objects[name].manifold.bounding_box(),
                                         opened.scene.objects[name].manifold.bounding_box()))
        for name in ("w", "w.sash_02", "w.sash_02.glass", "w.mullion_01"):
            np.testing.assert_allclose(closed.scene.objects[name].manifold.bounding_box(),
                                       opened.scene.objects[name].manifold.bounding_box(), atol=1e-6)

    def test_manual_sash_rotation_keeps_glass_and_handle_attached(self):
        source = "w = window sections=1 casing=нет sill=нет handle_resolution=.2"
        base = ok(source)
        moved = ok(source + "\nrotate [w.sash_01] angle=20 axis=z pivot=[-55.15,0,0]")
        for name in ("w.sash_01.glass", "w.sash_01.handle"):
            self.assertFalse(np.allclose(base.scene.objects[name].manifold.bounding_box(),
                                         moved.scene.objects[name].manifold.bounding_box()))
        np.testing.assert_allclose(base.scene.objects["w"].manifold.bounding_box(),
                                   moved.scene.objects["w"].manifold.bounding_box(), atol=1e-6)


if __name__ == "__main__":
    unittest.main()
