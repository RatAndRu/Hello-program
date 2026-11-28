"""Checks of an illustrative compact clover, NOT a manufacturing approval.

The holder, LED, PCB, screw heads and wiring are unmeasured mock-ups. These
checks cannot establish assembly, switch action, printed fit, strength, water
protection, electrical performance or battery safety.
"""
from itertools import combinations
from pathlib import Path
import json
import re
import sys
import tempfile
import unittest

import manifold3d as mf
import numpy as np

try:
    import lib3mf
except ImportError:
    lib3mf = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from forma.geometry import export_3mf  # noqa: E402
from forma.run import build  # noqa: E402
from make_clover_led_compact_print_layout import layout_content  # noqa: E402

SCENE = ROOT / "examples" / "clover_keychain_led_compact_concept.forma"
LAYOUT = ROOT / "examples" / "clover_keychain_led_compact_print_layout.forma"
PROBE = ROOT / "docs" / "clover_compact_cura_probe.json"
DIRECTIONS = ("верх", "право", "низ", "лево")
LEAVES = {f"лист_{d}" for d in DIRECTIONS}
HEADS = {f"шляпка{i}" for i in range(1, 5)}
COVER = {"крышка_клевера", "кнопка", *HEADS}
BOARD = {"макет_платы", "кнопка_платы_корпус", "нажим_платы", "чип1", "чип2"}
HOLDER = {"макет_отсека", "макет_батареи", "макет_крышечки", "макет_штатного_рычага"}
WIRES = {"плюс_отсека", "минус_отсека", "плюс_LED", "минус_LED", "анод_LED", "катод_LED"}
SCREW_AXES = ((0, 21.5), (21.5, 0), (0, -21.5), (-21.5, 0))


def built(script):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    return result


def local_shift(part, dx=0, dy=0, dz=0):
    """Holder local XY axes are rotated 45 degrees in the assembly."""
    s = np.sqrt(0.5)
    return part.translate([(dx - dy) * s, (dx + dy) * s, dz])


def signed_area(points):
    return float(np.sum(points[:, 0] * np.roll(points[:, 1], -1) -
                        points[:, 1] * np.roll(points[:, 0], -1)) / 2)


def largest_polygon(section):
    points = max(section.to_polygons(), key=lambda p: abs(signed_area(p)))
    if signed_area(points) < 0:
        points = points[::-1].copy()
    return mf.CrossSection([points])


def difference_area(a, b):
    return abs((a - b).area()) + abs((b - a).area())


def sweep_points(script, name):
    match = re.search(rf"^{name} = sweep path=(\[.*?\]) radius=([0-9.]+)", script, re.M)
    if match is None:
        raise AssertionError(f"Missing mock sweep: {name}")
    return np.asarray(json.loads(match.group(1)), dtype=float), float(match.group(2))


def sampled_minimum_radius(points):
    first, second = points[1:-1] - points[:-2], points[2:] - points[1:-1]
    across = points[2:] - points[:-2]
    denominator = np.linalg.norm(first, axis=1) * np.linalg.norm(second, axis=1) * np.linalg.norm(across, axis=1)
    valid = denominator > 1e-10
    curvature = 2 * np.linalg.norm(np.cross(first[valid], second[valid]), axis=1) / denominator[valid]
    return 1 / curvature.max()


class CompactCloverConceptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCENE.read_text(encoding="utf-8")
        cls.result = built(cls.script)
        cls.objects = {obj.name: obj for obj in cls.result.visible_solids()}
        cls.solids = {name: obj.manifold for name, obj in cls.objects.items()}
        cls.outline = largest_polygon(cls.solids["крышка_клевера"].slice(-15))
        cls.layout_script = LAYOUT.read_text(encoding="utf-8")
        cls.layout_result = built(cls.layout_script)
        cls.layout = {obj.name: obj.manifold for obj in cls.layout_result.visible_solids()}

    def test_visible_solids_are_connected_and_valid(self):
        expected = (LEAVES | COVER | BOARD | HOLDER | WIRES |
                    {"корпус_клевера", "макет_LED", "макет_резистора"})
        self.assertEqual(self.solids.keys(), expected)
        self.assertEqual(len(expected), 28)
        for name, part in self.solids.items():
            with self.subTest(name=name):
                self.assertEqual(part.status(), mf.Error.NoError)
                self.assertEqual(len(part.decompose()), 1)
                self.assertGreater(part.volume(), 0)
        self.assertEqual(self.objects["крышка_клевера"].color.lower(), "#206640")
        self.assertEqual(self.objects["макет_LED"].emissive.lower(), "#39d950")

    def test_symmetric_flower_and_equal_inlays(self):
        np.testing.assert_allclose(self.outline.bounds(), [-28.5, -28.5, 28.5, 28.5], atol=1e-5)
        self.assertAlmostEqual(self.outline.area(), 2486.642, delta=0.03)
        for angle in (90, 180, 270):
            with self.subTest(rotation=angle):
                self.assertLess(difference_area(self.outline, self.outline.rotate(angle)), 1e-5)
        # The centred ear only exists at Z=-0.8..3, so below it the body and
        # the lid have the same outside silhouette.
        for z in (-14.2, -12, -10, -6, -4.5, -2, -0.9):
            with self.subTest(body_z=z):
                body_outline = largest_polygon(self.solids["корпус_клевера"].slice(z))
                self.assertLess(difference_area(self.outline, body_outline), 1e-5)
        top = self.solids["лист_верх"].slice(2.5)
        for i, direction in enumerate(("верх", "лево", "низ", "право")):
            with self.subTest(leaf=direction):
                leaf = self.solids[f"лист_{direction}"].slice(2.5)
                self.assertLess(difference_area(top.rotate(90 * i), leaf), 1e-5)
                # Only an XY border in this sampled section, not 3D strength.
                self.assertLess(abs((leaf.offset(2.1, mf.JoinType.Round, 2, 96) - self.outline).area()), 1e-5)

    def test_marked_end_margins_in_holder_projection(self):
        # Same orientation as the marked screenshot: the wires point up. Use a
        # narrow strip at local X=0 and include both outgoing mock wires.
        outer = self.outline.rotate(-45)
        names = HOLDER | {"плюс_отсека", "минус_отсека"}
        projected = [self.solids[n].rotate([0, 0, -45]).project() for n in sorted(names)]
        components = projected[0]
        for section in projected[1:]:
            components += section
        axis = mf.CrossSection.square([0.0001, 70], True)
        a, b = (outer ^ axis).bounds(), (components ^ axis).bounds()
        lower, upper = b[1] - a[1], a[3] - b[3]
        self.assertAlmostEqual(lower, 3.649, delta=0.01)
        self.assertAlmostEqual(upper, 3.720, delta=0.01)
        self.assertLess(abs(lower - upper), 0.08)
        # These are axial 2D margins, not minimum wall thicknesses.

    def test_sampled_cavity_and_pilot_sections(self):
        body = self.solids["корпус_клевера"]
        for z in (-14.2, -12, -10, -8.1, -6, -4.5, -3.5, -2):
            with self.subTest(z=z):
                void = self.outline - body.slice(z)
                cavity = largest_polygon(void)
                expanded = cavity.offset(2.0, mf.JoinType.Round, 2, 96)
                self.assertLess(abs((expanded - self.outline).area()), 1e-5)
        # Ring material around the pilot exists at these selected sections.
        for z in (-14.2, -12, -9, -8.1):
            for x, y in SCREW_AXES:
                with self.subTest(z=z, axis=(x, y)):
                    ring = (mf.CrossSection.circle(3, 96) - mf.CrossSection.circle(0.86, 96)).translate([x, y])
                    self.assertLess(abs((ring - body.slice(z)).area()), 1e-5)
                    pin = mf.Manifold.cylinder(8, 0.8, 0.8, 48).translate([x, y, -16.1])
                    self.assertLess(abs((pin ^ body).volume()), 1e-6)
                    self.assertLess(abs((pin ^ self.solids["крышка_клевера"]).volume()), 1e-6)

    def test_nominal_pairwise_collisions(self):
        intentional = frozenset(("минус_LED", "катод_LED"))
        for (name_a, a), (name_b, b) in combinations(self.solids.items(), 2):
            volume = abs((a ^ b).volume())
            with self.subTest(first=name_a, second=name_b):
                if frozenset((name_a, name_b)) == intentional:
                    self.assertGreater(volume, 0)
                    self.assertLess(volume, 0.001)  # tiny illustrative junction
                else:
                    self.assertLess(volume, 1e-6)

    def test_idealized_holder_shelf_four_pads_and_clearance(self):
        holder = self.solids["макет_отсека"]
        np.testing.assert_allclose(holder.rotate([0, 0, -45]).bounding_box(),
                                   [-11.5, -21.1, -10, 11.5, 9.9, -4], atol=1e-5)
        # Tiny virtual motion reveals a contact, not actual force or retention.
        shelf = self.solids["корпус_клевера"] ^ holder.translate([0, 0, 0.05])
        self.assertGreater(shelf.volume() / 0.05, 500)
        pads = self.solids["крышка_клевера"].translate([0, 0, 0.06]) ^ holder
        for x in (-10.65, 10.65):
            for y in (7.2, 9.0):
                with self.subTest(x=x, y=y):
                    region = mf.Manifold.cube([1.7, 1.7, 1], True).translate([x, y, -10]).rotate([0, 0, 45])
                    self.assertGreater((pads ^ region).volume() / 0.01, 1.5)
        cap = self.solids["макет_крышечки"]
        self.assertLess(abs((self.solids["крышка_клевера"].translate([0, 0, 0.06]) ^ cap).volume()), 1e-6)
        for dx, dy in ((-0.25, 0), (0.25, 0), (0, -0.25), (0, 0.25)):
            with self.subTest(dx=dx, dy=dy):
                self.assertLess(abs((self.solids["корпус_клевера"] ^ local_shift(holder, dx, dy)).volume()), 1e-6)
        # The ends of the two illustrative wires touch the modeled straight
        # end of the holder. This does not locate real solder/strain relief.
        for name in ("плюс_отсека", "минус_отсека"):
            self.assertGreater((local_shift(self.solids[name], dy=-0.01) ^ holder).volume(), 0.001)

    def test_mock_pcb_clearance_is_smaller_than_known_edge_tolerance(self):
        board, lid = self.solids["макет_платы"], self.solids["крышка_клевера"]
        np.testing.assert_allclose(board.rotate([0, 0, -45]).bounding_box(),
                                   [-7.62, -3.69, -11.85, 7.62, 14.09, -10.65], atol=1e-5)
        for dy in (-0.24, 0.24):
            with self.subTest(dy=dy):
                self.assertLess(abs((local_shift(board, dy=dy) ^ lid).volume()), 1e-6)
        for dy in (-0.27, 0.27):
            with self.subTest(dy=dy):
                self.assertGreater((local_shift(board, dy=dy) ^ lid).volume(), 0.1)
        # Directly moving the rigid mock PCB through the fixed catches clashes.
        # Assembly would require a different path or elastic deformation.
        self.assertGreater((board.translate([0, 0, 0.05]) ^ lid).volume(), 0.1)

    def test_mock_button_clearance_contact_and_unsealed_hole(self):
        button = self.solids["кнопка"]
        lid, switch = self.solids["крышка_клевера"], self.solids["нажим_платы"]
        self.assertLess(abs((button.translate([0, 0, 0.14]) ^ switch).volume()), 1e-6)
        self.assertGreater((button.translate([0, 0, 0.16]) ^ switch).volume(), 0.03)
        self.assertLess(abs((button.translate([0, 0, 0.59]) ^ lid).volume()), 1e-6)
        self.assertGreater((button.translate([0, 0, 0.61]) ^ lid).volume(), 0.005)
        self.assertLess(abs((button.translate([0, 0, -0.14]) ^ lid).volume()), 1e-6)
        self.assertGreater((button.translate([0, 0, -0.16]) ^ lid).volume(), 0.05)
        hole = mf.CrossSection.circle(1.85, 64).translate([0, 12.2]).rotate(45)
        annulus = hole - button.slice(-15)
        self.assertGreater(annulus.area(), 2.9)
        self.assertLess(annulus.area(), 3.2)
        # Real switch compression/return, axial assembly and water sealing are
        # not modeled; collision with fixed solids is not switch movement.

    def test_led_seat_ear_and_open_annulus(self):
        body, led = self.solids["корпус_клевера"], self.solids["макет_LED"]
        self.assertGreater((led.translate([0, 0, 0.05]) ^ body).volume(), 0.1)
        self.assertLess(abs((led.translate([0, 0, -0.05]) ^ body).volume()), 1e-6)
        pin = mf.Manifold.cylinder(10, 2.4, 2.4, 96).translate([0, 31.5, -2])
        for name, part in self.solids.items():
            with self.subTest(ear_pin=name):
                self.assertLess(abs((pin ^ part).volume()), 1e-6)
        # There is a small projected gap around the nominal Ø5 LED in its
        # Ø5.3 hole. It is not a dust/water seal or an optical fit check.
        face = body.slice(1) + led.slice(1)
        exposed = self.solids["макет_отсека"].project() - face
        self.assertGreater(exposed.area(), 2.3)
        self.assertLess(exposed.area(), 2.5)

    def test_wire_graph_and_short_bends_are_only_illustrative(self):
        paths = {}
        for name, radius in (("плюс_отсека_мест", 0.35), ("минус_отсека_мест", 0.35),
                             ("плюс_LED_мест", 0.35), ("минус_LED_мест", 0.35),
                             ("анод_LED_мест", 0.22), ("катод_LED_мест", 0.22)):
            with self.subTest(path=name):
                points, actual_radius = sweep_points(self.script, name)
                self.assertAlmostEqual(actual_radius, radius)
                # These sub-millimetre-scale centreline bends are documented as
                # an unresolved risk, not recommended real wire bend radii.
                bend = sampled_minimum_radius(points)
                self.assertGreater(bend, 0.68)
                self.assertLess(bend, 1.05)
                paths[name] = points
        np.testing.assert_allclose(paths["плюс_отсека_мест"][0], [5, 9.9, -7.3])
        np.testing.assert_allclose(paths["минус_отсека_мест"][0], [3.2, 9.9, -7.3])
        np.testing.assert_allclose(paths["плюс_LED_мест"][-1], [-2, 7, -2.7])
        np.testing.assert_allclose(paths["анод_LED_мест"][0], [-2, 4, -2.7])
        np.testing.assert_allclose(paths["минус_LED_мест"][-1], paths["катод_LED_мест"][0])
        # PCB endpoints and actual connections are NOT represented by a real
        # manufacturer footprint, and must not be inferred from these paths.

    def test_layout_synchronization_orientation_and_no_mock_hardware(self):
        self.assertEqual(self.layout_script, layout_content(self.script))
        expected = {"на_столе_корпус_клевера", "на_столе_крышка", "на_столе_кнопка",
                    *(f"на_столе_лист_{d}" for d in DIRECTIONS)}
        self.assertEqual(self.layout.keys(), expected)
        for source in ("корпус_клевера", *sorted(LEAVES)):
            with self.subTest(source=source):
                expected_part = self.solids[source].rotate([180, 0, 0]).translate([-36, 0, 3])
                actual = self.layout[f"на_столе_{source}"]
                self.assertLess(abs((actual - expected_part).volume()) + abs((expected_part - actual).volume()), 1e-6)
        for name, part in self.layout.items():
            with self.subTest(part=name):
                self.assertAlmostEqual(part.bounding_box()[2], 0, delta=1e-5)
                self.assertEqual(part.status(), mf.Error.NoError)
                self.assertEqual(len(part.decompose()), 1)
        for (na, a), (nb, b) in combinations(self.layout.items(), 2):
            with self.subTest(first=na, second=nb):
                self.assertLess(abs((a ^ b).volume()), 1e-6)
        boxes = [p.bounding_box() for p in self.layout.values()]
        size = [max(b[i + 3] for b in boxes) - min(b[i] for b in boxes) for i in range(3)]
        np.testing.assert_allclose(size, [131, 65.95, 17.3], atol=0.01)

    def test_bounds_visibility_and_indicative_cura_probe(self):
        boxes = [self.solids[n].bounding_box() for n in ("корпус_клевера", "крышка_клевера")]
        size = [max(b[i + 3] for b in boxes) - min(b[i] for b in boxes) for i in range(3)]
        np.testing.assert_allclose(size, [57, 65, 19.3], atol=0.01)
        boxes = [part.bounding_box() for part in self.solids.values()]
        size = [max(b[i + 3] for b in boxes) - min(b[i] for b in boxes) for i in range(3)]
        np.testing.assert_allclose(size, [57, 65, 25.8], atol=0.01)
        script = self.script
        for name in COVER | BOARD:
            directive = f"# hide {name}\n"
            self.assertEqual(script.count(directive), 1)
            script = script.replace(directive, f"hide {name}\n")
        opened = {item.name for item in built(script).visible_solids()}
        self.assertEqual(opened, self.solids.keys() - COVER - BOARD)
        data = json.loads(PROBE.read_text(encoding="utf-8"))
        self.assertTrue(data["diagnostic_only"].startswith("NOT FOR PRINTING"))
        self.assertRegex(data["source_mesh_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(data["settings"]["layer_height"], 0.2)
        self.assertEqual(data["settings"]["machine_nozzle_size"], 0.4)
        self.assertEqual(data["settings"]["support_type"], "everywhere")
        self.assertEqual(data["settings"]["support_angle"], 50)
        self.assertEqual(data["layer_count"], 31)
        self.assertGreater(data["segment_counts"].get("SUPPORT", 0), 0)
        self.assertEqual(data["support_layers"], list(range(1, 27)))
        self.assertEqual(data["warnings"], [])

    @unittest.skipIf(lib3mf is None, "install lib3mf for an independent 3MF check")
    def test_independent_3mf_round_trip_of_experimental_layout(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "layout-not-for-printing.3mf"
            path.write_bytes(export_3mf(self.layout_result.visible_solids()))
            model = lib3mf.get_wrapper().CreateModel()
            reader = model.QueryReader("3mf")
            reader.SetStrictModeActive(True)
            reader.ReadFromFile(str(path))
            self.assertEqual(reader.GetWarningCount(), 0)
            iterator = model.GetMeshObjects()
            names = []
            while iterator.MoveNext():
                obj = iterator.GetCurrentMeshObject()
                names.append(obj.GetName())
                self.assertTrue(obj.IsManifoldAndOriented(), obj.GetName())
            self.assertEqual(set(names), set(self.layout))
            items = model.GetBuildItems()
            self.assertTrue(items.MoveNext())
            assembly = items.GetCurrent().GetObjectResource()
            self.assertTrue(assembly.IsComponentsObject())
            self.assertEqual(assembly.GetComponentCount(), 7)
            self.assertFalse(items.MoveNext())
        # lib3mf readback is not a Bambu Studio or multicolour print test.


if __name__ == "__main__":
    unittest.main()
