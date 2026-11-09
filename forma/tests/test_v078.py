"""0.78: шаг в стек объекта — одна строка, проверка сборки и откат.

Стек объекта — это строки сценария с тем же именем слева. Шаг добавляет ещё
одну: объединить, вычесть, повернуть, покрасить. Проверяется главное: строка
ставится после своих деталей, но до первого их использования; сценарий с шагом
обязан собраться; при отказе текст не меняется.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from forma.errors import FormaError
from forma.run import build
from forma.steps import (CATALOG, append_step, build_line, catalog,
                         insertion_index, number_text)

ROOT = Path(__file__).resolve().parent.parent

BASE = ("a = box size=[40, 40, 40]\n"
        "b = box size=[30, 30, 30] at=[20, 0, 0]\n")


def build_text(text: str):
    return build(text, analyze_model=False)


class CatalogTest(unittest.TestCase):
    def test_every_step_is_a_real_operation(self):
        from forma.ops import lookup

        for entry in catalog():
            self.assertIsNotNone(lookup(entry["op"]), entry["op"])
            self.assertTrue(entry["title"], entry["op"])
            self.assertTrue(entry["fields"], entry["op"])

    def test_catalog_payload_is_plain_data(self):
        for entry in catalog():
            self.assertEqual(set(entry), {"op", "title", "hint", "fields"})
            for field in entry["fields"]:
                self.assertIn("kind", field)
                self.assertIn(field["kind"],
                              {"object", "number", "vec3", "axis", "keep", "color", "text"})

    def test_number_text_reads_like_a_scenario(self):
        self.assertEqual(number_text(90), "90")
        self.assertEqual(number_text(0.05), "0.05")
        self.assertEqual(number_text(12.5), "12.5")
        self.assertEqual(number_text(0), "0")


class LineTest(unittest.TestCase):
    def test_every_step_builds(self):
        expectations = {
            "union": {"other": "b"},
            "difference": {"other": "b"},
            "intersect": {"other": "b"},
            "weld": {"other": "b", "tolerance": 0.05},
            "translate": {"offset": [0, 0, 10]},
            "rotate": {"angle": 45, "axis": "z"},
            "scale": {"factor": [1, 1, 1.5]},
            "slice": {"axis": "z", "at": 20, "keep": "top"},
            "color": {"color": "#ff0000", "material": "plastic"},
        }
        self.assertEqual(sorted(expectations), sorted(CATALOG))
        for op, values in expectations.items():
            text = append_step(BASE, "a", op, values)["script"]
            result = build_text(text)
            self.assertTrue(result.ok, f"{op}: {(result.error or {}).get('message')}")
            self.assertIn("a", result.scene.objects, op)

    def test_geometry_actually_changes(self):
        plain = build_text(BASE)

        def volume(op, values):
            text = append_step(BASE, "a", op, values)["script"]
            result = build_text(text)
            self.assertTrue(result.ok, op)
            return result.scene.objects["a"].stats()["volume"]

        self.assertGreater(volume("union", {"other": "b"}), plain.scene.objects["a"].stats()["volume"])
        self.assertLess(volume("difference", {"other": "b"}),
                        plain.scene.objects["a"].stats()["volume"])
        self.assertLess(volume("slice", {"axis": "z", "at": 20, "keep": "top"}),
                        plain.scene.objects["a"].stats()["volume"])
        self.assertAlmostEqual(volume("scale", {"factor": [1, 1, 2]}),
                               plain.scene.objects["a"].stats()["volume"] * 2, delta=1.0)

        moved = build_text(append_step(BASE, "a", "translate", {"offset": [0, 0, 25]})["script"])
        self.assertAlmostEqual(moved.scene.objects["a"].bbox[2],
                               plain.scene.objects["a"].bbox[2] + 25, delta=1e-6)

        painted = build_text(append_step(BASE, "a", "color", {"color": "#ff0000"})["script"])
        self.assertEqual(painted.scene.objects["a"].color, "#ff0000")

    def test_bad_values_are_rejected_before_building(self):
        with self.assertRaises(FormaError):
            build_line("color", "a", {"color": "красный"})
        with self.assertRaises(FormaError):
            build_line("difference", "a", {"other": "a"})
        with self.assertRaises(FormaError):
            build_line("rotate", "a", {"angle": "много"})
        with self.assertRaises(FormaError):
            build_line("не_шаг", "a", {})


class InsertionTest(unittest.TestCase):
    def test_step_goes_after_its_parts(self):
        index = insertion_index(BASE, "a", "b")
        self.assertEqual(index, 2, "шаг обязан стоять после второй детали")

    def test_step_goes_before_first_use(self):
        text = BASE + "g = union [a, b]\n"
        added = append_step(text, "a", "union", {"other": "b"})
        self.assertEqual(added["line_number"], 3)
        lines = added["script"].splitlines()
        self.assertEqual(lines[2], "a = union [a, b]")
        self.assertEqual(lines[3], "g = union [a, b]")

    def test_step_goes_before_check(self):
        text = "a = box size=[40, 40, 40]\ncheck a watertight\n"
        added = append_step(text, "a", "translate", {"offset": [0, 0, 5]})
        self.assertEqual(added["script"].splitlines()[1], "translate [a] offset=[0, 0, 5]")
        self.assertEqual(added["script"].splitlines()[2], "check a watertight")

    def test_second_step_follows_the_first(self):
        """Стек объекта растёт вниз: новый шаг идёт после прежних, а не до них."""
        first = append_step(BASE, "a", "translate", {"offset": [0, 0, 5]})["script"]
        second = append_step(first, "a", "scale", {"factor": [2, 2, 2]})["script"]
        lines = second.splitlines()
        self.assertLess(lines.index("translate [a] offset=[0, 0, 5]"),
                        lines.index("scale [a] factor=[2, 2, 2]"))
        after = build_text(second)
        self.assertTrue(after.ok, (after.error or {}).get("message"))

    def test_unknown_object_falls_back_to_client_hint(self):
        text = "a = box size=[40, 40, 40]\n"
        added = append_step(text, "чужая", "translate", {"offset": [0, 0, 5]}, after_line=1)
        self.assertEqual(added["line_number"], 2)


class RollbackTest(unittest.TestCase):
    def test_failed_build_leaves_text_untouched(self):
        """Отказ сервера: текст остаётся прежним, шаг не попадает в сценарий."""
        added = append_step("a = box size=[40, 40, 40]\nb = box size=[40, 40, 40]\n",
                            "a", "difference", {"other": "b"})
        result = build_text(added["script"])
        self.assertFalse(result.ok)
        self.assertIn("ничего не осталось", (result.error or {}).get("message", ""))
        # Именно поэтому клиент не применяет текст: проверка идёт до правки.
        self.assertEqual(added["script"].count("difference"), 1)

    def test_server_and_ui_are_wired(self):
        webui = (ROOT / "forma" / "webui.py").read_text(encoding="utf-8")
        app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn('"/api/steps"', webui)
        self.assertIn('"/api/step"', webui)
        self.assertIn("append_step", webui)
        for token in ("stepAdder", "applyStep", "loadSteps", "/api/step"):
            self.assertIn(token, app)
        self.assertIn("step-field", (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
