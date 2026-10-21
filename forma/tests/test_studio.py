"""Тесты материалов, света, анимации, импорта и анатомической фигуры."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.geometry import _glb_read, export_glb, export_ply, export_stl  # noqa: E402
from forma.run import build  # noqa: E402
from forma.textures import KIND_NAMES, make_texture  # noqa: E402


def ok(script: str):
    b = build(script)
    if not b.ok:
        raise AssertionError(f"Сценарий не построился: {b.error}\n{script}")
    return b


class TestTextures(unittest.TestCase):
    def test_all_textures_render(self):
        for kind in KIND_NAMES:
            img = make_texture(kind, size=64, seed=3)
            self.assertEqual(img.shape, (64, 64, 3), kind)
            self.assertGreater(int(img.mean()), 5, kind)
            self.assertLess(int(img.mean()), 250, kind)

    def test_texture_command_and_glb(self):
        b = ok("к = cylinder radius=30 height=60\ntexture к kind=мрамор scale=1.5\n"
               "color к #ffffff")
        solid = b.visible_solids()[0]
        self.assertIsNotNone(solid.tex)
        self.assertTrue(Path(solid.tex["path"]).exists())
        doc, _ = _glb_read(export_glb([solid]))
        self.assertTrue(doc.get("images"), "текстура должна попасть в GLB")
        self.assertTrue(doc.get("textures"))

    def test_unknown_texture(self):
        b = build("к = box size=[10,10,10]\ntexture к kind=нечто")
        self.assertFalse(b.ok)
        self.assertIn("Неизвестная текстура", b.error["message"])


class TestSceneAndLight(unittest.TestCase):
    def test_scene_settings(self):
        b = ok("к = box size=[10,10,10]\nscene bg=#112233 env=night exposure=1.4 "
               "shadows=нет grid=нет")
        s = b.payload()["settings"]
        self.assertEqual(s["bg"], "#112233")
        self.assertEqual(s["env"], "night")
        self.assertAlmostEqual(s["exposure"], 1.4)
        self.assertFalse(s["shadows"])
        self.assertFalse(s["grid"])

    def test_light_presets(self):
        b = ok("к = box size=[10,10,10]\nlight preset=солнце strength=1.2")
        s = b.payload()["settings"]
        self.assertEqual(s["env"], "sun")
        self.assertGreater(s["key"], 3.0)

    def test_bad_preset(self):
        b = build("к = box size=[10,10,10]\nlight preset=марс")
        self.assertFalse(b.ok)


class TestAnimation(unittest.TestCase):
    def test_animation_in_glb(self):
        for kind in ("spin", "formation", "explode"):
            b = ok("a = box size=[40,20,10]\nb = sphere radius=12\nplace b at=[60,0,0]\n"
                   f"animate kind={kind} seconds=3")
            doc, binary = _glb_read(export_glb(b.visible_solids(), animation={"kind": kind,
                                                                            "seconds": 3}))
            self.assertTrue(doc.get("animations"), kind)
            anim = doc["animations"][0]
            self.assertTrue(anim["channels"], kind)
            self.assertGreater(len(binary), 1000)
            self.assertEqual(doc["buffers"][0]["byteLength"], len(binary))

    def test_scene_animation_stored(self):
        b = ok("a = box size=[10,10,10]\nanimate kind=сборка seconds=2")
        anim = b.payload()["animation"]
        self.assertEqual(anim["kind"], "formation")
        self.assertAlmostEqual(anim["seconds"], 2.0)


class TestExportFormats(unittest.TestCase):
    def test_ply(self):
        b = ok("a = box size=[10,20,30]")
        data = export_ply(b.visible_solids())
        self.assertTrue(data.startswith(b"ply\nformat binary_little_endian"))
        self.assertIn(b"element vertex 24", data + b"")  # 24 вершины у куба
        self.assertGreater(len(data), 300)


class TestHuman(unittest.TestCase):
    def test_small_human(self):
        b = ok("ч = human height=400 sex=ж build=спортивный pose=t detail=низкий "
               "hair=да eyes=да\ncheck ч height 395..405\ncheck ч watertight")
        names = [s.name for s in b.scene.objects.values()]
        self.assertIn("ч", names)
        self.assertTrue(any("волосы" in n for n in names))
        self.assertTrue(any("глаза" in n for n in names))
        checks = b.analysis["checks"]
        self.assertTrue(all(c["ok"] for c in checks), checks)
        tris = sum(s.manifold.num_tri() for s in b.scene.objects.values())
        self.assertGreater(tris, 5000)

    def test_human_validation(self):
        b = build("ч = human height=50")
        self.assertFalse(b.ok)


class TestImport(unittest.TestCase):
    def test_import_stl(self):
        b = ok("куб = box size=[20,30,40]")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.stl"
            path.write_bytes(export_stl(b.visible_solids()))
            script = f"деталь = import file={path} unit=mm\ncheck деталь watertight"
            b2 = ok(script)
            solid = b2.visible_solids()[0]
            self.assertAlmostEqual(solid.bbox[5] - solid.bbox[2], 40, places=2)
            self.assertTrue(b2.analysis["checks"][0]["ok"])

    def test_missing_file(self):
        b = build("деталь = import file=нет_такого_файла.glb")
        self.assertFalse(b.ok)
        self.assertIn("не найден", b.error["message"].lower())


if __name__ == "__main__":
    if os.environ.get("FORMA_DATA") is None:
        os.environ["FORMA_DATA"] = os.path.join(tempfile.gettempdir(), "forma_test_data")
    unittest.main()


class TestReportAndSelection(unittest.TestCase):
    """Отчёт для нейросети: замечания, координаты, журнал, вырезание области."""

    SCRIPT = "к = cylinder radius=20 height=60\ncheck к watertight"

    def test_note_cut_prompt(self):
        from forma.agent import build_prompt
        from forma.webui import AppState

        st = AppState()
        res = st.build(self.SCRIPT, auto=False)
        self.assertTrue(res["ok"], res.get("error"))
        self.assertTrue(any(a["kind"] == "сборка" for a in st.actions))

        note = st.add_note({"object": "к", "text": "тут тонко", "tris": 12,
                            "area_mm2": 8.5, "center": [0, 0, 30], "size": [4, 4, 6],
                            "bbox": [-2, -2, 27, 2, 2, 33]})
        self.assertEqual(note["text"], "тут тонко")
        self.assertEqual(len(st.notes), 1)

        cut = st.cut_region(self.SCRIPT, "к", [0, 0, 30], 6)
        self.assertIn("difference [к, вырез_1]", cut["script"])
        built = st.build(cut["script"], auto=False)
        self.assertTrue(built["ok"], built.get("error"))

        text = build_prompt(st.last_build, "укрепи", notes=st.notes, actions=st.actions,
                            with_reference=False)
        self.assertIn("тут тонко", text)
        self.assertIn("Журнал действий", text)
        self.assertIn("центр (0.0, 0.0, 30.0)", text)
        self.assertNotIn("СПРАВКА ФОРМА 3D (кратко)", text)

        full = build_prompt(st.last_build, "укрепи", with_reference=True)
        self.assertIn("СПРАВКА ФОРМА 3D (кратко)", full)

    def test_failed_build_is_logged(self):
        from forma.webui import AppState

        st = AppState()
        res = st.build("к = такой_команды_нет", auto=False)
        self.assertFalse(res["ok"])
        self.assertTrue(any(not a["ok"] for a in st.actions))
        self.assertIn("ошибка", st.actions[-1]["text"])
