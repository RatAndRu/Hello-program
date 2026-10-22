"""Тесты 0.11: анимация, удаление объектов, авто-история, целостность JS."""

from __future__ import annotations

import re
import sys
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


class TestAnimation(unittest.TestCase):
    def test_spin_clip_in_payload_and_glb(self):
        b = ok("к = sphere radius=30\nanimate kind=spin seconds=4")
        payload = b.payload()
        timeline = payload["timeline"]
        self.assertTrue(timeline["has"])
        self.assertEqual(timeline["kinds"], ["spin"])
        self.assertAlmostEqual(timeline["duration"], 4.0, places=2)
        clip = timeline["clips"][0]
        self.assertAlmostEqual(clip["end"], 4.0, places=2)
        self.assertIn("animation", payload)
        doc, _ = _glb_read(b.glb())
        self.assertTrue(doc.get("animations"), "GLB должен содержать клип анимации")

    def test_several_clips_follow_each_other(self):
        b = ok("к = box size=[10, 10, 10]\n"
               "animate kind=spin seconds=2\n"
               "animate kind=explode seconds=3 amount=20")
        clips = b.payload()["timeline"]["clips"]
        self.assertEqual(len(clips), 2)
        self.assertAlmostEqual(clips[0]["start"], 0.0, places=2)
        self.assertAlmostEqual(clips[1]["start"], clips[0]["end"], places=2)
        self.assertAlmostEqual(b.payload()["timeline"]["duration"],
                               clips[1]["end"], places=2)

    def test_assembly_length_depends_on_steps(self):
        b = ok("к = box size=[10, 10, 10]\nс = sphere radius=8\n"
               "animate kind=assembly hold=0.5")
        timeline = b.payload()["timeline"]
        self.assertGreater(timeline["assembly"]["hold"], 0)
        self.assertGreater(timeline["duration"], 0.5)

    def test_mug_example_has_playable_animation(self):
        """Кружка должна играть сразу: жалоба «даже у кружки не работает»."""
        script = (ROOT / "examples" / "mug.forma").read_text(encoding="utf-8")
        self.assertIn("animate", script)
        b = ok(script)
        timeline = b.payload()["timeline"]
        self.assertTrue(timeline["has"])
        self.assertIn("spin", timeline["kinds"])


class TestHumanHands(unittest.TestCase):
    def test_hands_are_connected(self):
        """Из SDF кисти отрывались от предплечий: 3 оболочки вместо одной."""
        b = ok("ч = human height=420 sex=ж pose=t detail=низкий")
        solid = b.scene.objects["ч"]
        self.assertEqual(len(solid.manifold.decompose()), 1,
                         "тело, голова, кисти и стопы должны быть одной оболочкой")
        self.assertGreater(solid.stats()["size"][2], 415)


class TestDelete(unittest.TestCase):
    def test_delete_removes_object(self):
        b = ok("к = box size=[10, 10, 10]\nш = sphere radius=8\nудалить ш")
        names = [o["name"] for o in b.payload()["objects"]]
        self.assertEqual(names, ["к"])
        self.assertTrue(any("удалено: ш" in l["message"] for l in b.log), b.log)

    def test_delete_all_clears_the_scene(self):
        b = build("к = box size=[10, 10, 10]\nш = sphere radius=8\nудалить all")
        self.assertFalse(b.ok)
        # пустая сцена — честная ошибка сборки, а не падение ядра
        self.assertIn("нет видимых объектов", b.error["message"])

    def test_delete_unknown_name_reports_error(self):
        b = build("к = box size=[10, 10, 10]\nудалить нет_такого")
        self.assertFalse(b.ok)
        self.assertIn("нет_такого", b.error["message"])


class TestWebConsole(unittest.TestCase):
    """Ловит опечатки вида this.applyShading(), из-за которых падала загрузка."""

    @classmethod
    def setUpClass(cls):
        cls.viewer = (ROOT / "web" / "js" / "viewer.js").read_text(encoding="utf-8")
        cls.app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")

    def test_viewer_calls_only_existing_methods(self):
        methods = set(re.findall(r"^\s{2}(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{",
                                 self.viewer, re.M))
        props = set(re.findall(r"this\.([A-Za-z_$][\w$]*)\s*=", self.viewer))
        calls = set(re.findall(r"this\.([A-Za-z_$][\w$]*)\s*\(", self.viewer))
        # колбэки интерфейса назначаются снаружи и вызываются через ?.()
        allowed = {"onSelect", "onSelection"}
        missing = sorted(calls - methods - props - allowed)
        self.assertEqual(missing, [], f"В viewer.js вызовы несуществующих методов: {missing}")

    def test_animation_is_ready_before_styling(self):
        """Анимация настраивается до setShading: падение оформления не убивает клип."""
        body = self.viewer.split("async load(url, animation = null) {", 1)[1].split("\n  }", 1)[0]
        self.assertIn("_setupAnimation(gltf)", body)
        self.assertLess(body.index("_setupAnimation(gltf)"), body.index("this.setShading("))
        self.assertLess(body.index("setTimeline("), body.index("this.setShading("))

    def test_history_and_delete_are_wired(self):
        for needle in ("function pushHistory", "function scheduleEditSnapshot",
                       "function deleteObject", "function renderHistory"):
            self.assertIn(needle, self.app, needle)
        index = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for ident in ("history-list", "btn-undo", "btn-redo", "anim-play", "objects-list"):
            self.assertIn(f'id="{ident}"', index, ident)


if __name__ == "__main__":
    unittest.main()
