"""Geometric checks of the symmetric clover *concept*, not print approval.

The holder, wiring, LED, fasteners and switch are hypothetical mock-ups. These
checks do not establish real fit, correct switch travel, retention, assembly,
strength, electrical performance, water protection, or product safety.
"""
from itertools import combinations
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

SCENE = ROOT / "examples" / "clover_keychain_led_symmetric_concept.forma"
DIRECTIONS = ("верх", "право", "низ", "лево")
FRONT_INLAYS = {f"вставка_{direction}" for direction in DIRECTIONS}
REAR_INLAYS = {f"зад_вставка_{direction}" for direction in DIRECTIONS}
HEADS = {f"шляпка{i}" for i in range(1, 5)}
REAR = {"крышка_клевера", "зелёный_ползунок", *REAR_INLAYS, *HEADS}
HOLDER = {"макет_отсека", "макет_крышки_отсека", "макет_батарейки", "макет_ползунка_отсека"}
WIRES = {"провод_плюс", "провод_минус"}
SCREW_AXES = ((0, 21.5), (21.5, 0), (0, -21.5), (-21.5, 0))

# Overlapping solid mock-ups of insulation, contacts and colour bands are
# intentional. They would not be suitable separate parts for 3MF printing.
INTENTIONAL_OVERLAPS = {
    frozenset(pair) for pair in (
        ("макет_LED", "анод_контакт"), ("макет_LED", "термо_анод"),
        ("провод_плюс", "плюс_контакт"), ("провод_плюс", "термо_плюс"),
        ("провод_минус", "катод_контакт"), ("провод_минус", "термо_катод"),
        ("макет_резистора", "анод_контакт"), ("макет_резистора", "термо_анод"),
        ("плюс_контакт", "термо_плюс"), ("анод_контакт", "термо_анод"),
        ("катод_контакт", "термо_катод"),
        *(("макет_резистора", f"полоса{i}") for i in range(1, 5)),
    )
}


def built(script):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    return result


def shifted_local(body, dx=0.0, dy=0.0, dz=0.0):
    """The hypothetical holder's axes are rotated 45° in the XY plane."""
    s = np.sqrt(0.5)
    return body.translate([(dx - dy) * s, (dx + dy) * s, dz])


def signed_area(polygon):
    return float(np.sum(polygon[:, 0] * np.roll(polygon[:, 1], -1) -
                        polygon[:, 1] * np.roll(polygon[:, 0], -1)) / 2)


def largest_polygon(section):
    points = max(section.to_polygons(), key=lambda p: abs(signed_area(p)))
    if signed_area(points) < 0:
        points = points[::-1].copy()
    return mf.CrossSection([points])


def outline_at(body, z):
    # Keep only the outside contour; pocket, screw and LED holes are irrelevant
    # to comparisons of the body's silhouette at a given Z level.
    return largest_polygon(body.slice(z))


def symmetric_difference_area(first, second):
    return abs((first - second).area()) + abs((second - first).area())


def wire_points(script, name):
    match = re.search(rf"^{name} = sweep path=(\[.*?\]) radius=0\.5", script, re.M)
    if match is None:
        raise AssertionError(f"Cannot find wire path: {name}")
    return np.asarray(json.loads(match.group(1)), dtype=float)


class SymmetricCloverConceptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCENE.read_text(encoding="utf-8")
        cls.result = built(cls.script)
        cls.objects = {item.name: item for item in cls.result.visible_solids()}
        cls.solids = {name: item.manifold for name, item in cls.objects.items()}
        cls.outline = outline_at(cls.solids["крышка_клевера"], -12.5)

    def test_visible_bodies_are_valid_connected_mockups(self):
        self.assertTrue((REAR | HOLDER | FRONT_INLAYS | WIRES | {
            "корпус_клевера", "кольцо_LED", "макет_LED", "макет_резистора"
        }) <= self.solids.keys())
        for name, part in self.solids.items():
            with self.subTest(name=name):
                self.assertEqual(part.status(), mf.Error.NoError)
                self.assertEqual(len(part.decompose()), 1)
                self.assertGreater(part.volume(), 0)
        self.assertEqual(self.objects["макет_LED"].emissive.lower(), "#39d950")

    def test_body_and_lid_share_a_fourfold_symmetric_outline_except_ear(self):
        outline = self.outline
        np.testing.assert_allclose(outline.bounds(), [-34, -34, 34, 34], atol=1e-5)
        self.assertAlmostEqual(outline.area(), 3374.594, delta=0.02)
        for angle in (90, 180, 270):
            with self.subTest(rotation=angle):
                self.assertLess(symmetric_difference_area(outline, outline.rotate(angle)), 1e-5)
        # The ear occupies Z=-6.75..-2.95; outside that interval the body's
        # outer profile is the cover profile, including at the seam.
        for z in (-11.4, -10, -8, -7, -2.9, -2, 0.5, 1.9, 2.9):
            with self.subTest(body_z=z):
                self.assertLess(symmetric_difference_area(
                    outline, outline_at(self.solids["корпус_клевера"], z)), 1e-5)
        for z in (-13.2, -13.0, -12.8, -11.6):
            with self.subTest(lid_z=z):
                self.assertLess(symmetric_difference_area(
                    outline, outline_at(self.solids["крышка_клевера"], z)), 1e-5)
        ear_region = (mf.CrossSection.square([10.02, 12.82], True)
                      .translate([0, (29.2 + 42.02) / 2]))
        for z in (-6, -3.5):
            with self.subTest(ear_z=z):
                body_outline = outline_at(self.solids["корпус_клевера"], z)
                self.assertLess(abs((outline - body_outline).area()), 1e-5)
                self.assertGreater((body_outline - outline).area(), 80)
                self.assertLess(abs((body_outline - outline - ear_region).area()), 1e-5)

    def test_four_equal_leaf_shapes_and_sampled_outer_rim(self):
        for prefix, z in (("", 2.5), ("зад_", -13.1)):
            top = self.solids[f"{prefix}вставка_верх"].slice(z)
            for index, direction in enumerate(("верх", "лево", "низ", "право")):
                with self.subTest(side=prefix, leaf=direction):
                    leaf = self.solids[f"{prefix}вставка_{direction}"].slice(z)
                    self.assertLess(symmetric_difference_area(top.rotate(90 * index), leaf), 1e-5)
                    # A 1.8 mm dilation fits inside the common outer contour in
                    # this section. It is not a full 3D strength evaluation.
                    border = leaf.offset(1.8, mf.JoinType.Round, 2, 96)
                    self.assertLess(abs((border - self.outline).area()), 1e-5)

    def test_selected_cavity_sections_have_planar_clearance_to_outline(self):
        # This samples 2D sections, not a global wall-thickness or strength
        # proof. The main cavity is the largest hole; pilot holes are separate.
        for z in (-11.4, -10, -8, -6, -5.1, -4.05, -3.9, -2, -0.1, 0.1):
            with self.subTest(z=z):
                void = self.outline - self.solids["корпус_клевера"].slice(z)
                cavity = largest_polygon(void)
                self.assertGreater(cavity.area(), 100)
                expanded = cavity.offset(2.0, mf.JoinType.Round, 2, 96)
                self.assertLess(abs((expanded - self.outline).area()), 1e-5)

    def test_no_unintended_nominal_intersections(self):
        for (name_a, part_a), (name_b, part_b) in combinations(self.solids.items(), 2):
            if frozenset((name_a, name_b)) in INTENTIONAL_OVERLAPS:
                continue
            with self.subTest(first=name_a, second=name_b):
                self.assertLess(abs((part_a ^ part_b).volume()), 1e-6)

    def test_pilot_holes_and_mock_screw_boss_sections(self):
        body = self.solids["корпус_клевера"]
        section = body.slice(-10)
        for x, y in SCREW_AXES:
            with self.subTest(axis=(x, y)):
                # Ø1.6 test pin passes through the Ø2.2 cover hole and Ø1.7
                # nominal pilot. Screw shafts/threads are not modeled.
                pin = mf.Manifold.cylinder(7.25, 0.8, 0.8, 48).translate([x, y, -13.2])
                for name in ("корпус_клевера", "крышка_клевера", *REAR_INLAYS):
                    self.assertLess(abs((pin ^ self.solids[name]).volume()), 1e-6)
                outer = mf.CrossSection.circle(3, 96).translate([x, y])
                hole = mf.CrossSection.circle(0.86, 96).translate([x, y])
                self.assertLess(abs(((outer - hole) - section).area()), 1e-5)

    def test_mock_holder_shelf_and_each_pad_contact(self):
        holder = self.solids["макет_отсека"]
        np.testing.assert_allclose(holder.rotate([0, 0, -45]).bounding_box(),
                                   [-11.5, -18.5, -11.2, 11.5, 12.5, -5.2], atol=1e-5)
        shelf = self.solids["корпус_клевера"] ^ holder.translate([0, 0, 0.05])
        self.assertGreater(shelf.volume() / 0.05, 80.0)
        pads = self.solids["крышка_клевера"].translate([0, 0, 0.05]) ^ holder
        for x in (-8.2, 8.2):
            with self.subTest(pad=x):
                region = (mf.Manifold.cube([3, 3, 2], True)
                          .translate([x, 10.8, -11.3]).rotate([0, 0, 45]))
                self.assertGreater((pads ^ region).volume() / 0.05, 3.5)
        factory_lid = self.solids["макет_крышки_отсека"]
        self.assertLess(abs((self.solids["крышка_клевера"].translate([0, 0, 0.05]) ^
                             factory_lid).volume()), 1e-6)
        # Samples of the nominal 0.3 mm side clearance of the idealized holder.
        for dx, dy in ((-0.25, 0), (0.25, 0), (0, -0.25), (0, 0.25)):
            with self.subTest(dx=dx, dy=dy):
                self.assertLess(abs((self.solids["корпус_клевера"] ^
                                     shifted_local(holder, dx, dy)).volume()), 1e-6)

    def test_led_seat_and_eye_probe(self):
        led = self.solids["макет_LED"]
        self.assertGreater((led.translate([0, 0, -0.05]) ^ self.solids["корпус_клевера"]).volume(), 0.1)
        self.assertGreater((led.translate([0, 0, 0.05]) ^ self.solids["кольцо_LED"]).volume(), 0.1)
        # A straight Ø4.8 probe through the Ø5 modeled hole is not a test of a
        # real split ring, material strength, tolerances, or loading of the ear.
        probe = mf.Manifold.cylinder(25, 2.4, 2.4, 96).translate([0, 37, -15])
        for name, part in self.solids.items():
            with self.subTest(eye_probe=name):
                self.assertLess(abs((probe ^ part).volume()), 1e-6)

    def test_slider_sampled_motion_and_projection_are_distinct(self):
        # Nominal assumed motion only: there is no measured real switch. The
        # model does not yet include a retainer or a dust/water seal.
        slot = mf.CrossSection.square([3.8, 2.6], True).translate([0, 13.9]).rotate(45)
        actuator = self.solids["зелёный_ползунок"]
        switch = self.solids["макет_ползунка_отсека"]
        for dx in (-0.5, 0.0, 0.5):
            with self.subTest(dx=dx):
                moved = shifted_local(actuator, dx=dx)
                moved_switch = shifted_local(switch, dx=dx)
                self.assertLess(abs((moved ^ moved_switch).volume()), 1e-6)
                for name, part in self.solids.items():
                    if name in ("зелёный_ползунок", "макет_ползунка_отсека"):
                        continue
                    self.assertLess(abs((moved ^ part).volume()), 1e-6, name)
                    self.assertLess(abs((moved_switch ^ part).volume()), 1e-6, name)
                # It covers the slot from directly behind, not a physical seal.
                self.assertLess(abs((slot - moved.project()).area()), 1e-5)
                # Cap is 0.15 mm away from the outside of the lid and inserts;
                # a 0.14 mm approach remains clear, 0.16 mm reaches material.
                face_parts = [self.solids[n] for n in ("крышка_клевера", *REAR_INLAYS)]
                for part in face_parts:
                    self.assertLess(abs((moved.translate([0, 0, 0.14]) ^ part).volume()), 1e-6)
                hit = sum(abs((moved.translate([0, 0, 0.16]) ^ part).volume()) for part in face_parts)
                self.assertGreater(hit, 0.01)
                if dx:
                    # At the extremes, the cap overlaps an inlay in XY, but
                    # the two are separated along Z: a 2D overlap is not a 3D clash.
                    overlap = sum((moved.project() ^ self.solids[n].project()).area() for n in REAR_INLAYS)
                    self.assertGreater(overlap, 0.7)
        # An idealized ±0.2 mm gap surrounds the hypothetical switch tongue.
        # Virtual penetration just past that gap illustrates potential contact,
        # not a proof of actuation force, travel, or assembly.
        for sign in (-1, 1):
            self.assertLess(abs((shifted_local(actuator, dx=sign * 0.19) ^ switch).volume()), 1e-6)
            self.assertGreater((shifted_local(actuator, dx=sign * 0.21) ^ switch).volume(), 0.02)

    def test_mock_electronics_are_hidden_in_selected_projections(self):
        face = (self.solids["корпус_клевера"].slice(1.0) + self.solids["кольцо_LED"].slice(1.0) +
                self.solids["макет_LED"].slice(1.0))
        for name in WIRES | {"макет_резистора", "плюс_контакт", "анод_контакт", "катод_контакт"}:
            with self.subTest(face=name):
                self.assertLess(abs((self.solids[name].project() - face).area()), 1e-5)
        back = self.solids["крышка_клевера"].project() + self.solids["зелёный_ползунок"].project()
        for name in HOLDER | WIRES | {"макет_резистора"}:
            with self.subTest(back=name):
                self.assertLess(abs((self.solids[name].project() - back).area()), 1e-5)

    def test_selected_straight_opening_motions_of_idealized_parts(self):
        # Discrete straight translations are NOT a real assembly simulation:
        # screws, factory lid travel, wire bending/strain and hands are omitted.
        stationary = {"корпус_клевера", *HOLDER, *WIRES}
        for dz in (0.0, -0.1, -0.5, -1.0, -2.0, -4.0, -6.0, -8.0):
            for name in REAR:
                moved = self.solids[name].translate([0, 0, dz])
                for other in stationary:
                    with self.subTest(dz=dz, moving=name, obstacle=other):
                        self.assertLess(abs((moved ^ self.solids[other]).volume()), 1e-6)
            for name in HOLDER:
                with self.subTest(dz=dz, moving=name):
                    self.assertLess(abs((self.solids[name].translate([0, 0, dz]) ^
                                         self.solids["корпус_клевера"]).volume()), 1e-6)
        for name in ("макет_крышки_отсека", "макет_батарейки"):
            for dz in (-0.05, -0.5, -1.0, -2.0, -4.0):
                with self.subTest(moving=name, dz=dz):
                    self.assertLess(abs((self.solids[name].translate([0, 0, dz]) ^
                                         self.solids["макет_отсека"]).volume()), 1e-6)

    def test_mock_wires_start_straight_and_have_no_sharp_sampled_bends(self):
        for name, radius in (("красный_местный", 5.4), ("чёрный_местный", 4.0)):
            points = wire_points(self.script, name)
            with self.subTest(name=name):
                np.testing.assert_allclose(points[:3, 0], points[0, 0], atol=1e-9)
                np.testing.assert_allclose(points[:3, 2], points[0, 2], atol=1e-9)
                self.assertAlmostEqual(points[2, 1] - points[0, 1], 4.0)
                arc = points[2:33, :2] - np.array([1.0, 16.5])
                np.testing.assert_allclose(np.linalg.norm(arc, axis=1), radius, atol=1e-3)
                ab = points[1:-1] - points[:-2]
                bc = points[2:] - points[1:-1]
                ac = points[2:] - points[:-2]
                denom = np.linalg.norm(ab, axis=1) * np.linalg.norm(bc, axis=1) * np.linalg.norm(ac, axis=1)
                curvature = 2 * np.linalg.norm(np.cross(ab, bc), axis=1) / denom
                self.assertGreater(1 / curvature[curvature > 1e-7].max(), 3.5)

    def test_bounds_and_documented_hide_commands(self):
        boxes = [self.solids[n].bounding_box() for n in ("корпус_клевера", "крышка_клевера")]
        size = [max(b[i + 3] for b in boxes) - min(b[i] for b in boxes) for i in range(3)]
        np.testing.assert_allclose(size, [68, 76, 16.3], atol=0.01)
        all_boxes = [part.bounding_box() for part in self.solids.values()]
        full_size = [max(b[i + 3] for b in all_boxes) - min(b[i] for b in all_boxes) for i in range(3)]
        np.testing.assert_allclose(full_size, [68, 76, 23.25], atol=0.01)
        script = self.script
        for name in REAR:
            directive = f"# hide {name}\n"
            self.assertEqual(script.count(directive), 1)
            script = script.replace(directive, f"hide {name}\n")
        opened = {item.name for item in built(script).visible_solids()}
        self.assertEqual(opened, self.solids.keys() - REAR)
        cap = "# hide макет_крышки_отсека\n"
        self.assertEqual(script.count(cap), 1)
        battery = {item.name for item in built(script.replace(cap, cap[2:])).visible_solids()}
        self.assertEqual(battery, self.solids.keys() - REAR - {"макет_крышки_отсека"})
        for name in HOLDER:
            directive = f"# hide {name}\n"
            self.assertEqual(script.count(directive), 1)
            script = script.replace(directive, f"hide {name}\n")
        empty = {item.name for item in built(script).visible_solids()}
        self.assertEqual(empty, self.solids.keys() - REAR - HOLDER)
        self.assertTrue(WIRES <= empty)


if __name__ == "__main__":
    unittest.main()
