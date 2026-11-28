"""Smoke tests for the illustrative LED keychain scene (not a print certification)."""
from pathlib import Path
import sys
import unittest

import manifold3d as mf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forma.run import build  # noqa: E402

SCENE = ROOT / "examples" / "clover_keychain_led_visual.forma"
HIDDEN_FOR_WIRING = {
    "лицо_клевера", "корпус_сзади", "вставка_верх", "вставка_право",
    "вставка_низ", "вставка_лево",
}


def built(script):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(result.error)
    return result


class CloverLedVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCENE.read_text(encoding="utf-8")
        cls.result = built(cls.script)
        cls.solids = {item.name: item for item in cls.result.visible_solids()}

    def test_scene_builds_as_separate_valid_visual_objects(self):
        required = HIDDEN_FOR_WIRING | {
            "макет_LED", "макет_отсека", "макет_батарейки", "макет_крышки",
            "макет_ползунка", "макет_резистора", "провод_плюс", "провод_минус",
            "термо_плюс", "термо_анод", "термо_катод",
        }
        self.assertTrue(required <= self.solids.keys())
        for name, solid in self.solids.items():
            with self.subTest(name=name):
                self.assertEqual(solid.manifold.status(), mf.Error.NoError)
                self.assertEqual(len(solid.manifold.decompose()), 1)
                self.assertGreater(solid.manifold.volume(), 0)
        self.assertEqual(self.solids["макет_LED"].color.lower(), "#58e968")
        self.assertEqual(self.solids["макет_LED"].emissive.lower(), "#39d950")

    def test_structural_solids_do_not_intersect_visible_parts(self):
        # Contacts, insulation, and resistor bands intentionally overlap their
        # component mock-ups; those are not printer-ready separate bodies.
        for structure in ("лицо_клевера", "корпус_сзади"):
            for name, solid in self.solids.items():
                if name == structure:
                    continue
                with self.subTest(structure=structure, other=name):
                    volume = (self.solids[structure].manifold ^ solid.manifold).volume()
                    self.assertLess(abs(volume), 1e-6)
        self.assertLess(abs((self.solids["макет_отсека"].manifold ^
                             self.solids["макет_батарейки"].manifold).volume()), 1e-6)

    def test_documented_hide_commands_make_wiring_and_battery_visible(self):
        inside_script = self.script
        for name in HIDDEN_FOR_WIRING:
            directive = f"# hide {name}\n"
            self.assertEqual(inside_script.count(directive), 1)
            inside_script = inside_script.replace(directive, f"hide {name}\n")
        inside = {item.name for item in built(inside_script).visible_solids()}
        self.assertEqual(inside, self.solids.keys() - HIDDEN_FOR_WIRING)
        self.assertTrue({"макет_LED", "макет_резистора", "провод_плюс",
                         "провод_минус"} <= inside)

        directive = "# hide макет_крышки\n"
        self.assertEqual(self.script.count(directive), 1)
        opened = {item.name for item in built(self.script.replace(
            directive, "hide макет_крышки\n")).visible_solids()}
        self.assertEqual(opened, self.solids.keys() - {"макет_крышки"})
        self.assertIn("макет_батарейки", opened)

    def test_illustrative_body_envelope_excludes_led_and_switch(self):
        # Bounds describe this drawing only, not a fit or print guarantee.
        boxes = [self.solids[name].manifold.bounding_box() for name in HIDDEN_FOR_WIRING]
        size = [max(box[i + 3] for box in boxes) - min(box[i] for box in boxes)
                for i in range(3)]
        self.assertAlmostEqual(size[0], 41.155, delta=0.02)
        self.assertAlmostEqual(size[1], 48.942, delta=0.02)
        self.assertAlmostEqual(size[2], 14.5, delta=0.02)


if __name__ == "__main__":
    unittest.main()
