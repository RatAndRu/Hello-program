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
        b = ok("a = box size=[10,10,10]\nanimate kind=рост seconds=2")
        anim = b.payload()["animation"]
        self.assertEqual(anim["kind"], "formation")
        self.assertAlmostEqual(anim["seconds"], 2.0)
        # «сборка» — это теперь пошаговая сборка сценария, а не рост
        b2 = ok("a = box size=[10,10,10]\nanimate kind=сборка hold=0.5")
        self.assertEqual(b2.payload()["animation"]["kind"], "assembly")
        self.assertAlmostEqual(b2.payload()["animation"]["hold"], 0.5)

    def test_timeline_of_several_clips(self):
        script = ("a = box size=[40,20,10]\nplace a at=[0,0,0]\n"
                  "animate kind=spin seconds=4\n"
                  "animate kind=formation seconds=2\n"
                  "animate kind=assembly hold=0.5\n")
        p = ok(script).payload()
        plan = p["timeline"]
        self.assertEqual([c["kind"] for c in plan["clips"]],
                         ["spin", "formation", "assembly"])
        self.assertAlmostEqual(plan["clips"][0]["start"], 0.0)
        self.assertAlmostEqual(plan["clips"][1]["start"], 4.0)
        self.assertAlmostEqual(plan["clips"][2]["start"], 6.0)
        # два кадра сборки (куб и его перенос) × 0.5 с
        self.assertAlmostEqual(plan["clips"][2]["length"], 1.0)
        self.assertAlmostEqual(plan["duration"], 7.0)
        self.assertEqual([c["kind"] for c in p["animations"]],
                         ["spin", "formation", "assembly"])

    def test_explicit_start_and_fps(self):
        p = ok("a = box size=[10,10,10]\nanimate kind=spin start=2.5 seconds=1 fps=12"
               ).payload()
        clip = p["timeline"]["clips"][0]
        self.assertAlmostEqual(clip["start"], 2.5)
        self.assertEqual(clip["fps"], 12)
        self.assertAlmostEqual(p["timeline"]["duration"], 3.5)

    def test_bad_axis(self):
        b = build("a = box size=[10,10,10]\nanimate kind=spin axis=w")
        self.assertFalse(b.ok)
        self.assertIn("Ось анимации", b.error["message"])

    def test_glb_keeps_every_clip(self):
        b = ok("a = box size=[30,20,10]\nb = sphere radius=8 at=[40,0,0]\n"
               "animate kind=spin seconds=2\nanimate kind=explode start=2 seconds=2")
        doc, binary = _glb_read(b.glb())
        names = [a.get("name") for a in doc.get("animations", [])]
        self.assertEqual(names, ["FormaSpin", "FormaExplode"])
        self.assertEqual(doc["buffers"][0]["byteLength"], len(binary))
        # анимация сборки в GLB не выгружается: её кадры — отдельные модели
        b2 = ok("a = box size=[10,10,10]\nanimate kind=assembly")
        doc2, _ = _glb_read(b2.glb())
        self.assertFalse(doc2.get("animations"))

    def test_explode_starts_from_node_position(self):
        b = ok("a = box size=[20,10,10]\nb = sphere radius=5 at=[30,0,0]\n"
               "animate kind=explode seconds=2 amount=20")
        doc, binary = _glb_read(b.glb())
        import numpy as np
        anim = doc["animations"][0]
        self.assertEqual(anim["name"], "FormaExplode")
        for ch in anim["channels"]:
            sampler = anim["samplers"][ch["sampler"]]
            acc = doc["accessors"][sampler["output"]]
            view = doc["bufferViews"][acc["bufferView"]]
            arr = np.frombuffer(binary, dtype=np.float32, count=acc["count"] * 3,
                                offset=view["byteOffset"]).reshape(-1, 3)
            node = doc["nodes"][ch["target"]["node"]]
            base = np.array(node.get("translation") or [0, 0, 0], dtype=np.float32)
            self.assertTrue(np.allclose(arr[0], base, atol=1e-5),
                            "кадр 0 должен совпадать с положением узла (иначе деталь прыгнет)")
            self.assertGreater(float(np.linalg.norm(arr[-1] - base)), 5.0)

    def test_assembly_frames(self):
        script = ("a = box size=[40,40,40]\nb = sphere radius=12 at=[10,0,0]\n"
                  "c = difference a b\n")
        p = ok(script).payload()
        self.assertEqual(len(p["frames"]), 3)
        self.assertEqual([f["n"] for f in p["frames"]], [1, 2, 3])
        self.assertEqual(p["steps"][-1]["verb"], "difference")


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
