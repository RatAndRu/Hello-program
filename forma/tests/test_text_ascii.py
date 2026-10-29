"""Полнота и геометрия встроенного клавиатурного шрифта (0.52)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import string
import subprocess
import unittest

import numpy as np

from forma.dsl import parse_script
from forma.fonts import FALLBACK, glyph_strokes, text_solid
from forma.geometry import manifold_mesh
from forma.run import build
from forma.values import parse_value

ASCII = "".join(chr(code) for code in range(32, 127))


class TextAsciiTest(unittest.TestCase):
    def test_every_printable_ascii_glyph_has_its_own_definition(self):
        self.assertEqual(len(ASCII), 95)
        self.assertEqual(glyph_strokes(" "), [])
        for char in ASCII:
            with self.subTest(char=char, code=ord(char)):
                strokes = glyph_strokes(char)
                self.assertNotEqual(strokes, FALLBACK)
                if char != " ":
                    self.assertTrue(strokes)
                    self.assertTrue(all(len(line) >= 2 for line in strokes))
                    self.assertTrue(np.isfinite(np.asarray(
                        [point for line in strokes for point in line], dtype=float)).all())
        for char in string.ascii_lowercase:
            with self.subTest(lowercase=char):
                self.assertNotEqual(glyph_strokes(char), glyph_strokes(char.upper()))

    def test_every_nonspace_ascii_glyph_is_a_finite_solid(self):
        for char in ASCII[1:]:
            with self.subTest(char=char, code=ord(char)):
                solid, width = text_solid(char, size=8, depth=0.8, weight=0.55)
                self.assertEqual(str(solid.status()), "Error.NoError")
                self.assertFalse(solid.is_empty())
                self.assertGreater(solid.volume(), 1e-7)
                self.assertGreater(width, 0)
                vertices, faces = manifold_mesh(solid)
                self.assertTrue(np.isfinite(vertices).all())
                self.assertGreater(len(faces), 0)
                self.assertTrue(np.all(np.asarray(solid.bounding_box())[2::3] >= 0))
                self.assertAlmostEqual(float(solid.bounding_box()[5]), 0.8, places=5)

    def test_dsl_roundtrip_preserves_all_keyboard_specials(self):
        # JSON использует те же \" и \\, которые понимает DSL. В строке есть
        # #, =, кавычки, обе косые черты, backtick и вертикальная черта.
        script = "надпись = text " + json.dumps(ASCII, ensure_ascii=False) \
                 + " size=5 depth=0.5 weight=0.35 plane=xy"
        result = build(script, analyze_model=False)
        if not result.ok:
            self.fail(f"{result.error}\n{result.log}")
        command = parse_script(script)[0]
        self.assertEqual(parse_value(command.args[0], {}, {}), ASCII)
        obj = result.scene.objects["надпись"]
        self.assertEqual(str(obj.manifold.status()), "Error.NoError")
        self.assertGreater(obj.manifold.volume(), 0)

    def test_cyrillic_has_distinct_lowercase_forms(self):
        for char in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя":
            with self.subTest(char=char):
                self.assertNotEqual(glyph_strokes(char), FALLBACK)
                self.assertNotEqual(glyph_strokes(char), glyph_strokes(char.upper()))
                solid, _ = text_solid(char, size=8, depth=0.8, weight=0.55)
                self.assertGreater(solid.volume(), 1e-7)

    def test_live_text_card_preserves_ascii_and_spaces(self):
        node = shutil.which("node") or shutil.which("nodejs")
        if not node:
            self.skipTest("Node.js не установлен")
        script = Path(__file__).resolve().parent / "text_tools_test.js"
        completed = subprocess.run([node, str(script)], capture_output=True,
                                   text=True, timeout=30, check=False)
        self.assertEqual(completed.returncode, 0,
                         completed.stdout + "\n" + completed.stderr)
        self.assertIn("95 ASCII", completed.stdout)

    def test_space_only_text_has_an_actionable_error(self):
        result = build('пусто = text "   " size=10', analyze_model=False)
        self.assertFalse(result.ok)
        self.assertIn("Пустая надпись", str(result.error))


if __name__ == "__main__":
    unittest.main()
