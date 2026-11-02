"""Экспорт в OpenSCAD: два режима и обещания, которые они дают.

`solid` обязан переносить геометрию без потерь: число точек и граней в
`polyhedron` совпадает с сеткой ядра. `script` обязан давать читаемый
параметрический файл там, где команды переводимы, и честно падать в
`polyhedron` там, где нет, — с комментарием, а не с тихой потерей детали.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from forma.run import build
from forma.scad import export_scad, scad_script, scad_solid

BRACKET = """
плита0 = box size=[80,60,6] center=да
h1 = cylinder radius=2.5 height=20 at=[-28,0,-6]
h2 = cylinder radius=2.5 height=20 at=[28,0,-6]
плита = difference [плита0] [h1] [h2]
"""


def _built(text: str = BRACKET):
    result = build(text, analyze_model=True)
    if not result.ok:
        raise AssertionError(f"build failed: {result.error}")
    return result


def _counts(text: str) -> tuple[int, int]:
    """Сколько точек и граней объявлено в первом polyhedron."""
    points_block = re.search(r"points = \[(.*?)\],\s*faces", text, re.S)
    faces_block = re.search(r"faces = \[(.*?)\],\s*convexity", text, re.S)
    assert points_block and faces_block, "polyhedron без points/faces"
    points = len(re.findall(r"\[-?[\d.]", points_block.group(1)))
    faces = len(re.findall(r"\[\d+, \d+, \d+\]", faces_block.group(1)))
    return points, faces


class SolidModeTest(unittest.TestCase):
    def test_geometry_matches_kernel(self):
        result = _built()
        text = scad_solid(result)
        solid = result.scene.visible_solids()[0]
        points, faces = _counts(text)
        self.assertEqual(faces, solid.manifold.num_tri())
        self.assertEqual(points, len(solid.manifold.to_mesh().vert_properties))

    def test_volume_comment_matches_metrics(self):
        result = _built()
        text = scad_solid(result)
        volume = result.analysis["metrics"]["volume_cm3"]
        self.assertIn(f"{volume:.3f} см³", text)

    def test_two_objects_give_two_calls(self):
        result = _built("""
a = box size=[20,20,20] center=да
b = sphere radius=10 at=[60,0,0]
""")
        text = scad_solid(result)
        self.assertEqual(text.count("();"), 2)

    def test_names_are_ascii(self):
        result = _built(BRACKET)
        text = scad_solid(result)
        modules = re.findall(r"module (\w+)\(\)", text)
        self.assertTrue(modules)
        for name in modules:
            self.assertTrue(name.isascii(), name)


class ScriptModeTest(unittest.TestCase):
    def test_bracket_translates_without_polyhedron(self):
        result = _built()
        text = scad_script(result, BRACKET)
        self.assertIn("difference() {", text)
        self.assertIn("cube([80, 60, 6], center = true)", text)
        self.assertIn("cylinder(h = 20, r = 2.5, center = true)", text)
        self.assertNotIn("polyhedron(", text)

    def test_positions_come_from_kernel(self):
        result = _built(BRACKET)
        text = scad_script(result, BRACKET)
        # отверстия стоят на x = ±28, по Z их центр — 4 мм (at=[..,..,-6], height=20)
        self.assertIn("translate([-28, 0, 4])", text)
        self.assertIn("translate([28, 0, 4])", text)

    def test_names_transliterated(self):
        result = _built(BRACKET)
        text = scad_script(result, BRACKET)
        self.assertIn("module plita()", text)
        self.assertIn("plita();", text)

    def test_unsupported_command_falls_back_honestly(self):
        text = """
g = gear teeth=12 module=2 thickness=6 bore=6
"""
        result = build(text, analyze_model=False)
        self.assertTrue(result.ok, result.error)
        scad = scad_script(result, text)
        self.assertIn("polyhedron(", scad)
        self.assertIn("НЕ ПЕРЕВЕДЕНО", scad)
        self.assertIn("gear", scad)

    def test_union_and_translate(self):
        text = """
a = box size=[20,20,20] center=да
b = cylinder radius=5 height=40 at=[0,0,0]
c = union [a] [b]
d = translate [c] z=30
"""
        result = build(text, analyze_model=False)
        self.assertTrue(result.ok, result.error)
        scad = scad_script(result, text)
        self.assertIn("union() {", scad)
        self.assertIn("translate([0, 0, 30])", scad)


class ExportFileTest(unittest.TestCase):
    def test_writes_file_and_reports(self):
        result = _built()
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ("solid", "script"):
                out = Path(tmp) / f"m_{mode}.scad"
                info = export_scad(result, out, mode=mode, source=BRACKET)
                self.assertTrue(out.exists())
                self.assertEqual(info["mode"], mode)
                self.assertGreater(info["bytes"], 100)

    def test_webui_menu_gives_scad(self):
        import os

        from forma.webui import AppState

        old = os.environ.get("FORMA_DATA")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FORMA_DATA"] = tmp
            try:
                st = AppState()
                st.build(BRACKET)
                res = st.export("scad")
                saved = Path(res["path"])
                self.assertTrue(saved.exists())
                self.assertEqual(saved.suffix, ".scad")
                text = saved.read_text(encoding="utf-8")
                self.assertIn("difference() {", text)
            finally:
                if old is None:
                    os.environ.pop("FORMA_DATA", None)
                else:
                    os.environ["FORMA_DATA"] = old

    def test_cli_format_follows_extension(self):
        from forma.cli import _format_from_suffix

        self.assertEqual(_format_from_suffix(Path("дом.stl")), "stl")
        self.assertEqual(_format_from_suffix(Path("дом.3mf")), "3mf")
        self.assertEqual(_format_from_suffix(Path("дом.нечто")), "glb")
        self.assertEqual(_format_from_suffix(Path("дом")), "glb")

    def test_broken_scene_is_refused(self):
        result = build("a = box size=[10,10,10] nope=да")
        self.assertFalse(result.ok)
        with self.assertRaises(ValueError):
            scad_solid(result)


if __name__ == "__main__":
    unittest.main()
