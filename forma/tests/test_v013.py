"""Тесты 0.13: сечения, пробы, паспорт, Хаусдорф, надписи, резьба, уклон."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.geometry import export_stl  # noqa: E402
from forma.run import build  # noqa: E402


def ok(script: str, **kwargs):
    b = build(script, **kwargs)
    if not b.ok:
        raise AssertionError(f"Сценарий не построился: {b.error}\n{script}")
    return b


class TestSection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp(prefix="forma-test-")
        os.environ["FORMA_DATA"] = cls.data

    def test_section_contours_and_files(self):
        b = ok("к = cylinder radius=20 height=40 segments=48\nsection к z=20")
        self.assertEqual(len(b.scene.sections), 1)
        sec = b.scene.sections[0]
        self.assertEqual(sec["plane"], "z")
        self.assertAlmostEqual(sec["area"], 3.1416 * 400, delta=20)
        self.assertEqual(sec["outer"], 1)
        self.assertEqual(sec["holes"], 0)
        # файлы пишутся рядом с данными (папка exports)
        self.assertTrue(Path(sec["dxf"]).exists())
        self.assertTrue(Path(sec["svg"]).exists())
        payload = b.payload(light=True)["sections"][0]
        self.assertEqual(payload["plane"], "z")
        self.assertGreaterEqual(len(payload["contours"]), 1)

    def test_section_finds_holes(self):
        b = ok("плита = box size=[60, 60, 10]\n"
               "отв = cylinder radius=8 height=20 at=[0, 0, -5]\n"
               "плита = difference [плита, отв]\nsection плита z=5")
        sec = b.scene.sections[0]
        self.assertEqual(sec["holes"], 1)
        self.assertGreaterEqual(sec["outer"], 1)

    def test_section_outside_is_error(self):
        b = build("к = cylinder radius=20 height=40\nsection к z=90")
        self.assertFalse(b.ok)

    def test_section_plane_x(self):
        b = ok("к = box size=[40, 30, 20]\nsection к x=0")
        sec = b.scene.sections[0]
        self.assertEqual(sec["plane"], "x")
        self.assertAlmostEqual(sec["area"], 30 * 20, delta=1)


class TestProbe(unittest.TestCase):
    def test_probe_wall_and_void(self):
        b = ok("кружка = cylinder radius=40 height=100 segments=64\n"
               "кружка = shell [кружка] thickness=4 open=top\n"
               "probe кружка x=0 y=0 z=50\n"
               "probe кружка x=39 y=0 z=50")
        probes = b.scene.probes
        self.assertEqual(len(probes), 2)
        self.assertFalse(probes[0]["inside"])
        self.assertTrue(probes[1]["inside"])
        self.assertLess(probes[1]["distance"], 2.0)
        text = " ".join(log["message"] for log in b.scene.logs)
        self.assertIn("материал есть", text)
        self.assertIn("пусто", text)


class TestPassport(unittest.TestCase):
    def test_passport_plate_with_holes(self):
        b = ok("плита = box size=[80, 60, 10]\n"
               "о1 = cylinder radius=6 height=20 at=[20, 0, -5]\n"
               "о2 = cylinder radius=4 height=20 at=[-20, 0, -5]\n"
               "плита = difference [плита, о1, о2]")
        passport = b.analysis["metrics"]["passport"]
        self.assertEqual(passport["name"], "плита")
        self.assertAlmostEqual(passport["size"][0], 80, delta=0.1)
        self.assertAlmostEqual(passport["center"][2], 5, delta=0.1)
        diameters = sorted(round(h["diameter"], 1) for h in passport["holes"])
        self.assertEqual(len(diameters), 2)
        self.assertTrue(all(h["through"] for h in passport["holes"]))
        self.assertIn("ПАСПОРТ ДЕТАЛИ", b.analysis["text"])

    def test_passport_command(self):
        b = ok("шайба = cylinder radius=10 height=4\npassport шайба")
        self.assertEqual(len(b.scene.passports), 1)
        self.assertTrue(any("ПАСПОРТ шайба" in log["message"] for log in b.scene.logs))


class TestDeviation(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="forma-ref-"))
        ref = ok("сфера = sphere radius=40 segments=64", analyze_model=False)
        self.ref = self.tmp / "ref.stl"
        self.ref.write_bytes(export_stl([ref.scene.objects["сфера"]]))

    def test_same_shape_passes(self):
        b = ok(f'деталь = sphere radius=40 segments=64\n'
               f'check деталь deviation "{self.ref}" 0.3')
        check = b.analysis["checks"][0]
        self.assertTrue(check["ok"], check["text"])
        self.assertLess(check["actual"], 0.05)

    def test_bigger_shape_fails(self):
        b = ok(f'деталь = sphere radius=41 segments=64\n'
               f'check деталь deviation "{self.ref}" 0.3')
        check = b.analysis["checks"][0]
        self.assertFalse(check["ok"])
        self.assertAlmostEqual(check["actual"], 1.0, delta=0.2)

    def test_alias_and_missing_file(self):
        b = ok("деталь = sphere radius=40\ncheck деталь гаусдорф нет-такого.stl")
        check = b.analysis["checks"][0]
        self.assertFalse(check["ok"])
        self.assertIn("не найден", check["text"].lower())


class TestSimplifyDeviation(unittest.TestCase):
    def test_simplify_keeps_shape(self):
        b = ok("сфера = sphere radius=40 segments=72\n"
               "сфера = simplify [сфера] deviation=1.0", analyze_model=False)
        s = b.scene.objects["сфера"]
        self.assertLess(s.stats()["tris"], 1800 * 1.05)
        text = " ".join(log["message"] for log in b.scene.logs)
        self.assertIn("фактическое отклонение", text)

    def test_simplify_does_not_pounce(self):
        b = ok("к = cylinder radius=30 height=60 segments=64\n"
               "к = simplify [к] deviation=0.2")
        s = b.scene.objects["к"]
        self.assertAlmostEqual(s.stats()["size"][0], 60, delta=0.5)


class TestText(unittest.TestCase):
    def test_text_height_and_width(self):
        b = ok('надпись = text "ФОРМА" size=20 depth=3', analyze_model=False)
        s = b.scene.objects["надпись"]
        size = s.stats()["size"]
        self.assertAlmostEqual(size[2], 3, delta=0.01)
        self.assertGreater(size[1], 16)
        self.assertLess(size[1], 24)
        self.assertGreater(size[0], 40)

    def test_text_standing(self):
        b = ok('надпись = text "AAA" size=10 depth=2 plane=xz at=[0, 0, 5]', analyze_model=False)
        s = b.scene.objects["надпись"]
        bb = s.bbox
        self.assertAlmostEqual(bb[2], 5, delta=0.2)
        self.assertGreater(s.stats()["size"][2], 8)

    def test_empty_text_is_error(self):
        b = build('надпись = text "" size=10')
        self.assertFalse(b.ok)


class TestEmboss(unittest.TestCase):
    def base(self):
        return ("кружка = cylinder radius=40 height=100 segments=64\n"
                "кружка = shell [кружка] thickness=5 open=top\n")

    def test_relief_adds_material(self):
        plain = ok(self.base(), analyze_model=False).scene.objects["кружка"]
        b = ok(self.base() + 'д = emboss [кружка] text="ФОРМА" size=14 depth=1.0',
               analyze_model=False)
        s = b.scene.objects["д"]
        self.assertGreater(s.volume_cm3, plain.volume_cm3)
        self.assertGreater(s.stats()["size"][1], 80.5)

    def test_engrave_removes_material_and_wraps(self):
        plain = ok(self.base(), analyze_model=False).scene.objects["кружка"]
        b = ok(self.base() + 'д = emboss [кружка] text="ОК" size=12 depth=1.5 mode=engrave',
               analyze_model=False)
        s = b.scene.objects["д"]
        self.assertLess(s.volume_cm3, plain.volume_cm3)
        self.assertLessEqual(s.stats()["size"][1], 80.05)

    def test_flat_face_top(self):
        b = ok('п = box size=[80, 40, 8]\n'
               'п = emboss [п] text="ФОРМА" size=10 depth=1.2 face=top', analyze_model=False)
        s = b.scene.objects["п"]
        self.assertAlmostEqual(s.stats()["size"][2], 9.2, delta=0.2)
        self.assertAlmostEqual(s.stats()["size"][0], 80, delta=0.2)


class TestThread(unittest.TestCase):
    def test_bolt(self):
        b = ok("болт = thread diameter=10 length=12 pitch=1.5", analyze_model=False)
        s = b.scene.objects["болт"]
        size = s.stats()["size"]
        self.assertAlmostEqual(size[0], 10, delta=0.1)
        self.assertGreater(s.stats()["tris"], 2000)
        self.assertAlmostEqual(size[2], 12, delta=1.2)

    def test_nut_is_hollow(self):
        b = ok("гайка = thread diameter=16 length=6 pitch=1.5 internal=true",
               analyze_model=False)
        s = b.scene.objects["гайка"]
        self.assertGreater(s.stats()["genus"], 0)

    def test_thread_on_existing_rod(self):
        b = ok("шпилька = cylinder radius=5 height=20\n"
               "шпилька = thread [шпилька] pitch=1.5", analyze_model=False)
        s = b.scene.objects["шпилька"]
        self.assertAlmostEqual(s.stats()["size"][0], 10, delta=0.2)


class TestDraft(unittest.TestCase):
    def test_draft_narrows_the_top(self):
        b = ok("плита = box size=[40, 40, 40]\nплита = draft [плита] angle=3",
               analyze_model=False)
        m = b.scene.objects["плита"].manifold
        from forma.cuts import section_polygons
        bottom = section_polygons(m.slice(1))[0]
        top = section_polygons(m.slice(39))[0]
        self.assertGreater(bottom["points"][:, 0].max(), top["points"][:, 0].max() + 1.0)

    def test_draft_down(self):
        b = ok("плита = box size=[40, 40, 40]\nплита = draft [плита] angle=3 axis=-z",
               analyze_model=False)
        m = b.scene.objects["плита"].manifold
        from forma.cuts import section_polygons
        bottom = section_polygons(m.slice(1))[0]
        top = section_polygons(m.slice(39))[0]
        self.assertLess(bottom["points"][:, 0].max(), top["points"][:, 0].max() - 1.0)


class TestSectionExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp(prefix="forma-exp-")
        os.environ["FORMA_DATA"] = cls.data

    def test_dxf_and_svg_export(self):
        from forma.webui import AppState
        st = AppState()
        st.project_name = "тест"
        st.build("к = cylinder radius=20 height=40\nsection к z=20")
        dxf = st.export("dxf")
        svg = st.export("svg")
        for item in (dxf, svg):
            self.assertTrue(Path(item["path"]).exists(), item)
        text = Path(dxf["path"]).read_text(encoding="utf-8")
        self.assertIn("SECTION", text)
        self.assertIn("LINE", text)
        svg_text = Path(svg["path"]).read_text(encoding="utf-8")
        self.assertIn("<svg", svg_text)
        self.assertIn("<path", svg_text)

    def test_export_without_sections_is_error(self):
        from forma.webui import AppState
        st = AppState()
        st.build("к = box size=[10, 10, 10]")
        with self.assertRaises(Exception):
            st.export("dxf")


class TestMobileSchema(unittest.TestCase):
    """Паспорт и сечения попадают в payload, который читает интерфейс."""

    def test_payload_has_new_blocks(self):
        b = ok("к = cylinder radius=20 height=40\n"
               "section к z=20\nprobe к x=0 y=0 z=20\npassport к")
        payload = b.payload(light=True)
        self.assertIn("sections", payload)
        self.assertIn("probes", payload)
        self.assertIn("passports", payload)
        self.assertEqual(len(payload["probes"]), 1)
        self.assertTrue(payload["passports"])


if __name__ == "__main__":
    unittest.main()

class TestPlaceSides(unittest.TestCase):
    def _y(self, b, name):
        for s in b.scene.objects.values():
            if s.name == name:
                return s.bbox[1], s.bbox[4]
        raise AssertionError(name)

    def test_front_and_back(self):
        b = ok("корпус = box size=[100, 40, 60]\n"
               "крышка = box size=[30, 10, 10]\n"
               "крышка = place [крышка] on=корпус side=front offset=2")
        lo, hi = self._y(b, "крышка")
        # спереди — со стороны −Y, за габаритом корпуса с зазором 2 мм
        self.assertAlmostEqual(hi, -22.0, places=3)
        self.assertAlmostEqual(lo, -32.0, places=3)
        b = ok("корпус = box size=[100, 40, 60]\n"
               "крышка = box size=[30, 10, 10]\n"
               "крышка = place [крышка] on=корпус side=back offset=2")
        lo, hi = self._y(b, "крышка")
        self.assertAlmostEqual(lo, 22.0, places=3)
        self.assertAlmostEqual(hi, 32.0, places=3)
