"""Включение файла-библиотеки: `включить файл=крепёж.f3d`.

Идея взята у OpenSCAD (`include`/`use`) — см. `docs/cad_triad.md`, §7.2.
Проверяем не только «работает», но и то, что ошибки объяснимы: нет файла,
цикл, слишком глубокая вложенность.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from forma.run import build, expand_includes


class IncludeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_file_is_inlined(self):
        self.write("крепёж.f3d", "болт = cylinder radius=3 height=20 at=[0,0,0]\n")
        b = build("включить файл=крепёж.f3d\nплита = box size=[40,40,6]\n",
                  analyze_model=False, base_dir=self.root)
        self.assertTrue(b.ok, b.error)
        self.assertEqual(sorted(b.scene.objects), ["болт", "плита"])

    def test_english_keyword_and_quotes(self):
        self.write("lib.f3d", "a = box size=[10,10,10]\n")
        b = build('include file="lib.f3d"\n', analyze_model=False, base_dir=self.root)
        self.assertTrue(b.ok, b.error)
        self.assertIn("a", b.scene.objects)

    def test_nested_and_relative_to_included_file(self):
        (self.root / "sub").mkdir()
        self.write("sub/внутри.f3d", "шайба = cylinder radius=5 height=2 at=[0,0,0]\n")
        self.write("верх.f3d", "включить файл=sub/внутри.f3d\n")
        b = build("включить файл=верх.f3d\n", analyze_model=False, base_dir=self.root)
        self.assertTrue(b.ok, b.error)
        self.assertIn("шайба", b.scene.objects)

    def test_comment_marks_the_source(self):
        self.write("lib.f3d", "a = box size=[10,10,10]\n")
        text = expand_includes("включить файл=lib.f3d\n", self.root)
        self.assertIn("# ← включено из lib.f3d", text)

    def test_cycle_is_explained(self):
        self.write("a.f3d", "включить файл=b.f3d\n")
        self.write("b.f3d", "включить файл=a.f3d\n")
        b = build("включить файл=a.f3d\n", analyze_model=False, base_dir=self.root)
        self.assertFalse(b.ok)
        self.assertIn("Циклическое включение", b.error["message"])
        self.assertIn("a.f3d", b.error["hint"])

    def test_missing_file_says_where_it_looked(self):
        b = build("включить файл=нет.f3d\n", analyze_model=False, base_dir=self.root)
        self.assertFalse(b.ok)
        self.assertIn("не найден", b.error["message"])
        self.assertIn(str(self.root), b.error["hint"])

    def test_text_outside_include_is_untouched(self):
        text = "плита = box size=[10,10,10]\n# включить файл=это-комментарий.f3d\n"
        self.assertEqual(expand_includes(text, self.root).strip(), text.strip())

    def test_original_script_and_hash_kept(self):
        self.write("lib.f3d", "a = box size=[10,10,10]\n")
        script = "включить файл=lib.f3d\nb = box size=[20,20,20] at=[30,0,0]\n"
        b = build(script, analyze_model=False, base_dir=self.root)
        self.assertTrue(b.ok, b.error)
        self.assertEqual(b.script, script)   # в редакторе остаётся то, что написал человек

    def test_included_geometry_is_built(self):
        self.write("плита.f3d",
                   "плита0 = box size=[80,60,6] center=да\n"
                   "h1 = cylinder radius=2.5 height=6 at=[-28,0,-3]\n"
                   "h2 = cylinder radius=2.5 height=6 at=[28,0,-3]\n"
                   "плита = difference [плита0] [h1] [h2]\n")
        b = build("включить файл=плита.f3d\n", analyze_model=True, base_dir=self.root)
        self.assertTrue(b.ok, b.error)
        self.assertAlmostEqual(b.analysis["metrics"]["volume_cm3"], 28.57, places=1)


if __name__ == "__main__":
    unittest.main()
