"""Geometry checks for a hypothetical LED keychain layout, not a print approval.

All electronic components, fasteners and the switch transfer are mock-ups. These
checks cannot establish the fit of the unmeasured purchased battery holder,
serviceability, strength, electrical behaviour or safety of a real product.
"""
from pathlib import Path
import json
import re
import sys
import unittest

import manifold3d as mf
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forma.run import build  # noqa: E402

SCENE = ROOT / "examples" / "clover_keychain_led_integrated_concept.forma"
REAR = {"крышка_клевера", "шляпка1", "шляпка2", "шляпка3", "шляпка4", "зелёный_ползунок"}
HOLDER = {"макет_отсека", "макет_крышки_отсека", "макет_батарейки", "макет_ползунка_отсека"}
WIRES = {"провод_плюс", "провод_минус"}


def built(script):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    return result


def translated_in_local_x(body, dx):
    offset = dx / np.sqrt(2.0)
    return body.translate([offset, offset, 0])


def wire_points(script, name):
    match = re.search(rf"^{name} = sweep path=(\[.*?\]) radius=0\.5", script, re.M)
    if match is None:
        raise AssertionError(f"Cannot find wire path: {name}")
    return np.asarray(json.loads(match.group(1)), dtype=float)


class IntegratedCloverConceptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCENE.read_text(encoding="utf-8")
        cls.result = built(cls.script)
        cls.solids = {s.name: s.manifold for s in cls.result.visible_solids()}

    def test_objects_are_valid_and_structural_parts_are_connected(self):
        self.assertTrue((REAR | HOLDER | WIRES | {
            "корпус_клевера", "кольцо_LED", "макет_LED", "макет_резистора"
        }) <= self.solids.keys())
        for name, part in self.solids.items():
            with self.subTest(name=name):
                self.assertEqual(part.status(), mf.Error.NoError)
                self.assertEqual(len(part.decompose()), 1)
                self.assertGreater(part.volume(), 0)

    def test_mockups_do_not_clash_with_shell_lid_or_actuator(self):
        # Contacts intentionally overlap their insulation and resistor colour
        # bands intentionally overlap the resistor; these are visual mock-ups.
        for structure in ("корпус_клевера", "крышка_клевера", "зелёный_ползунок", "кольцо_LED"):
            for name, part in self.solids.items():
                if name == structure:
                    continue
                with self.subTest(structure=structure, other=name):
                    self.assertLess(abs((self.solids[structure] ^ part).volume()), 1e-6)
        for name in WIRES | {"макет_батарейки", "макет_крышки_отсека"}:
            with self.subTest(holder_other=name):
                self.assertLess(abs((self.solids["макет_отсека"] ^ self.solids[name]).volume()), 1e-6)
        self.assertLess(abs((self.solids["провод_плюс"] ^ self.solids["провод_минус"]).volume()), 1e-6)

    def test_holder_rests_on_shelf_and_is_retained_by_pads(self):
        # A very small virtual movement detects contact area without pretending
        # to measure physical tolerances or hold-down strength.
        holder = self.solids["макет_отсека"]
        shelf_overlap = (self.solids["корпус_клевера"] ^ holder.translate([0, 0, 0.05])).volume()
        pad_overlap = (self.solids["крышка_клевера"].translate([0, 0, 0.05]) ^ holder).volume()
        factory_lid_overlap = (self.solids["крышка_клевера"].translate([0, 0, 0.05]) ^
                               self.solids["макет_крышки_отсека"]).volume()
        self.assertGreater(shelf_overlap / 0.05, 80.0)  # mm², mock geometry
        self.assertGreater(pad_overlap / 0.05, 6.0)  # two pads, mock geometry
        self.assertLess(abs(factory_lid_overlap), 1e-6)
        for dx in (-0.25, 0.25):
            self.assertLess(abs((self.solids["корпус_клевера"] ^
                                 translated_in_local_x(holder, dx)).volume()), 1e-6)

    def test_led_seat_screw_pilots_and_assembly_window_are_modeled(self):
        led = self.solids["макет_LED"]
        # Opposite faces of the mock LED flange touch a lower seat and an upper
        # bezel. The bezel has zero design clearance; its real retention is NOT
        # designed or tested by these virtual contact checks.
        self.assertGreater((led.translate([0, 0, -0.05]) ^ self.solids["корпус_клевера"]).volume(), 0.1)
        self.assertGreater((led.translate([0, 0, 0.05]) ^ self.solids["кольцо_LED"]).volume(), 0.1)
        for x, y in ((16, 6), (6, 16), (-16, -6), (-6, -16)):
            probe = mf.Manifold.cylinder(7, 0.8, 0.8, 32).translate([x, y, -13])
            self.assertLess(abs((probe ^ self.solids["корпус_клевера"]).volume()), 1e-6)
            self.assertLess(abs((probe ^ self.solids["крышка_клевера"]).volume()), 1e-6)
        # Once the mock holder is removed, selected points in the wiring cavity
        # are reachable from behind through the opening in the shelf.
        c = np.sqrt(0.5)
        for x, y in ((-7, 0), (-6, 5), (5, 0)):
            probe = mf.Manifold.cylinder(9, 0.4, 0.4, 16).translate([c*(x-y), c*(x+y), -10.5])
            self.assertLess(abs((probe ^ self.solids["корпус_клевера"]).volume()), 1e-6)

    def test_slider_and_cover_clear_the_assumed_two_mm_travel(self):
        # The assumed internal tongue and mock switch move together by ±1 mm.
        # Actual switch dimensions and travel remain unmeasured.
        slot = (mf.Manifold.cube([4.8, 2.6, 0.1], True)
                .translate([-3, 13.9, -13.2]).rotate([0, 0, 45]))
        for dx in (-1.0, 0.0, 1.0):
            with self.subTest(dx=dx):
                actuator = translated_in_local_x(self.solids["зелёный_ползунок"], dx)
                switch = translated_in_local_x(self.solids["макет_ползунка_отсека"], dx)
                for obstacle in (self.solids["корпус_клевера"], self.solids["крышка_клевера"], switch):
                    self.assertLess(abs((actuator ^ obstacle).volume()), 1e-6)
                # At all tested positions the outer button covers the slot.
                self.assertLess(abs((slot - actuator).volume()), 1e-6)

    def test_wire_paths_start_straight_and_avoid_sharp_mock_bends(self):
        for name, projected_radius in (("красный_местный", 5.4), ("чёрный_местный", 4.0)):
            points = wire_points(self.script, name)
            with self.subTest(name=name):
                np.testing.assert_allclose(points[:3, 0], points[0, 0], atol=1e-9)
                np.testing.assert_allclose(points[:3, 2], points[0, 2], atol=1e-9)
                self.assertAlmostEqual(points[2, 1] - points[0, 1], 4.0)
                # The next 30 points follow a half-circle in plan.
                arc = points[2:33, :2] - np.array([1.0, 16.5])
                np.testing.assert_allclose(np.linalg.norm(arc, axis=1), projected_radius, atol=1e-3)
                ab = points[1:-1] - points[:-2]
                bc = points[2:] - points[1:-1]
                ac = points[2:] - points[:-2]
                denom = np.linalg.norm(ab, axis=1) * np.linalg.norm(bc, axis=1) * np.linalg.norm(ac, axis=1)
                curvature = 2.0 * np.linalg.norm(np.cross(ab, bc), axis=1) / denom
                nonzero = curvature[curvature > 1e-7]
                self.assertGreater(1.0 / nonzero.max(), 3.5)

    def test_front_and_rear_hide_mock_electronics_in_plan(self):
        # Orthographic projections check full wire and mock-holder silhouettes,
        # not material opacity or whether a real device can be assembled.
        skin = (self.solids["корпус_клевера"].slice(1.0) + self.solids["кольцо_LED"].slice(1.0) +
                self.solids["макет_LED"].slice(1.0))
        for name in WIRES | {"макет_резистора", "плюс_контакт", "анод_контакт", "катод_контакт"}:
            with self.subTest(front_hidden=name):
                self.assertLess(abs((self.solids[name].project() - skin).area()), 1e-5)
        rear = self.solids["крышка_клевера"].project() + self.solids["зелёный_ползунок"].project()
        for name in HOLDER:
            with self.subTest(rear_hidden=name):
                self.assertLess(abs((self.solids[name].project() - rear).area()), 1e-5)

    def test_hypothetical_opening_clearances(self):
        # These sample only straight, normal-to-face translations of the ideal
        # mockups. They do NOT model the unknown real lid, fastener removal,
        # flexible wire, lid mechanism, allowable bend radius or service forces.
        stationary = {"корпус_клевера", *HOLDER, *WIRES}
        for dz in (0.0, -0.1, -0.5, -1.0, -2.0, -4.0, -6.0, -8.0):
            for part in ("крышка_клевера", "зелёный_ползунок"):
                moved = self.solids[part].translate([0, 0, dz])
                for obstacle in stationary:
                    with self.subTest(dz=dz, moving=part, obstacle=obstacle):
                        self.assertLess(abs((moved ^ self.solids[obstacle]).volume()), 1e-6)
            for part in HOLDER:
                moved = self.solids[part].translate([0, 0, dz])
                with self.subTest(dz=dz, moving=part, obstacle="корпус_клевера"):
                    self.assertLess(abs((moved ^ self.solids["корпус_клевера"]).volume()), 1e-6)
        # The fictitious cap and battery also translate straight out of the
        # mock holder when shown in isolation: NOT the real lid's motion.
        for part in ("макет_крышки_отсека", "макет_батарейки"):
            for dz in (-0.05, -0.5, -1.0, -2.0, -4.0):
                with self.subTest(dz=dz, moving=part):
                    self.assertLess(abs((self.solids[part].translate([0, 0, dz]) ^
                                         self.solids["макет_отсека"]).volume()), 1e-6)

    def test_body_bounds_and_eye_probe(self):
        boxes = [self.solids[n].bounding_box() for n in ("корпус_клевера", "крышка_клевера")]
        size = [max(box[i+3] for box in boxes) - min(box[i] for box in boxes) for i in range(3)]
        np.testing.assert_allclose(size, [40.497, 48.942, 15.9], atol=0.03)
        # A Ø4.8 mm straight probe passes through the Ø5 mm hole. A real split
        # ring, print shrinkage and ear strength still require physical testing.
        probe = mf.Manifold.cylinder(25, 2.4, 2.4, 64).translate([0, 24, -15])
        for name, part in self.solids.items():
            with self.subTest(eye_probe=name):
                self.assertLess(abs((probe ^ part).volume()), 1e-6)

    def test_hide_commands_open_the_three_documented_views(self):
        script = self.script
        for name in REAR:
            directive = f"# hide {name}\n"
            self.assertEqual(script.count(directive), 1)
            script = script.replace(directive, f"hide {name}\n")
        opened = {s.name for s in built(script).visible_solids()}
        self.assertEqual(opened, self.solids.keys() - REAR)
        battery_script = script.replace("# hide макет_крышки_отсека\n", "hide макет_крышки_отсека\n")
        battery_view = {s.name for s in built(battery_script).visible_solids()}
        self.assertEqual(battery_view, self.solids.keys() - REAR - {"макет_крышки_отсека"})
        self.assertIn("макет_батарейки", battery_view)
        for name in HOLDER:
            directive = f"# hide {name}\n"
            self.assertEqual(script.count(directive), 1)
            script = script.replace(directive, f"hide {name}\n")
        empty = {s.name for s in built(script).visible_solids()}
        self.assertEqual(empty, self.solids.keys() - REAR - HOLDER)
        self.assertTrue(WIRES <= empty)


if __name__ == "__main__":
    unittest.main()
