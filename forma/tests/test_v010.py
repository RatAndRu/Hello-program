"""Тесты 0.10: оптимизация сетки, спайка/отсечение, рельеф текстур, яблоко."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.geometry import _glb_read  # noqa: E402
from forma.run import build  # noqa: E402


def ok(script: str):
    b = build(script)
    if not b.ok:
        raise AssertionError(f"Сценарий не построился: {b.error}\n{script}")
    return b


class TestSegments(unittest.TestCase):
    def test_huge_segment_count_is_capped(self):
        b = ok("т = lathe points=[[0,0],[30,0],[30,60],[0,60]] segments=400")
        tris = b.analysis["metrics"]["tris"]
        self.assertLess(tris, 6000, "лишние сегменты на ровном теле вращения не нужны")
        self.assertTrue(any("точение" in l["message"] and "→" in l["message"]
                            for l in b.log), b.log)

    def test_explicit_small_segments_are_kept(self):
        b = ok("ш = sphere radius=30 segments=12")
        self.assertLess(b.analysis["metrics"]["tris"], 400)


class TestWeldAndTrim(unittest.TestCase):
    SCRIPT = """ц = cylinder radius=30 height=80 segments=96
т = torus major=34 minor=8 segments=96
т = place [т] at=[34,0,70] align=center
р = trim [т, ц]
к = weld [ц, р] tolerance=0.05
"""

    def test_trim_and_weld_build(self):
        b = ok(self.SCRIPT)
        names = {o["name"] for o in b.payload()["objects"]}
        self.assertIn("к", names)
        self.assertTrue(any("спайка" in l["message"] for l in b.log), b.log)
        self.assertTrue(any("отсечение" in l["message"] for l in b.log), b.log)
        self.assertGreater(b.analysis["metrics"]["volume_cm3"], 200)

    def test_weld_merges_two_objects(self):
        b = ok("а = sphere radius=20\nб = sphere radius=20\nб = place [б] at=[20,0,0] align=center\n"
               "в = weld [а, б]\n")
        volumes = {o["name"]: o["volume_cm3"] for o in b.payload()["objects"]}
        self.assertLess(volumes["в"], volumes["а"] + volumes["б"])
        self.assertGreater(volumes["в"], volumes["а"])


class TestTextureRelief(unittest.TestCase):
    def test_relief_adds_normal_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FORMA_DATA"] = tmp
            try:
                b = ok("к = cylinder radius=40 height=80 segments=64\n"
                       "texture к kind=своя pattern=камень color1=#8a5a2b "
                       "color2=#d9c9a8 scale=2 seed=7 relief=0.6\n")
                tex = b.payload()["objects"][0]["tex"]
                self.assertEqual(tex["kind"], "custom")
                self.assertAlmostEqual(tex["relief"], 0.6)
                # карта нормалей действительно попала в файл и в материал
                doc, _binary = _glb_read(b.glb())
                self.assertEqual(len(doc.get("images", [])), 2)
                material = doc["materials"][0]
                self.assertIn("normalTexture", material)
                self.assertIn("baseColorTexture", material["pbrMetallicRoughness"])
            finally:
                os.environ.pop("FORMA_DATA", None)


class TestAppleExample(unittest.TestCase):
    def test_apple_builds_and_passes_checks(self):
        script = (ROOT / "examples" / "apple.forma").read_text(encoding="utf-8")
        b = ok(script)
        a = b.analysis
        self.assertEqual(a["checks_total"], a["checks_passed"], a["checks"])
        names = [o["name"] for o in b.payload()["objects"]]
        self.assertEqual(names, ["яблоко", "черешок", "лист"])
        height = b.payload()["objects"][0]["size"][2]
        self.assertGreater(height, 70)

    def test_apple_is_not_inverted(self):
        script = (ROOT / "examples" / "apple.forma").read_text(encoding="utf-8")
        b = ok(script)
        objs = {o["name"]: o["bbox"] for o in b.payload()["objects"]}
        apple = objs["яблоко"]
        stem = objs["черешок"]
        # черешок выходит из верхней чашечки, а не из нижней
        self.assertGreater(stem[5], apple[5] - 1.0)


class TestOptimize(unittest.TestCase):
    def test_optimize_all(self):
        b = ok("к = cylinder radius=40 height=80 segments=96\n"
               "ш = sphere radius=30 segments=96\noptimize all tolerance=0.15\n")
        self.assertTrue(any("оптимизация" in l["message"] for l in b.log), b.log)


if __name__ == "__main__":
    unittest.main()
