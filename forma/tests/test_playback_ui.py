"""Минимальные регрессии нового контракта playback и панели вида."""
from __future__ import annotations

import unittest
from pathlib import Path

from forma.run import build

ROOT = Path(__file__).resolve().parent.parent


class AssemblyMeaningfulFramesTest(unittest.TestCase):
    def test_visibility_and_transforms_are_frames_but_service_commands_are_not(self):
        script = """\
a = box size=[40,40,40]
check a height 40..40
color a #ff0000
hide a
show a
translate a offset=[10,0,0]
b = box size=[20,20,20] at=[60,0,0]
scene grid=нет ground=да
animate kind=assembly hold=0.2
"""
        result = build(script, analyze_model=False)
        self.assertTrue(result.ok, result.error)
        frames = result.frames()
        self.assertEqual([f["line"] for f in frames], [1, 4, 5, 6, 7])
        self.assertEqual(frames[1]["objects"], [])
        self.assertEqual(frames[1]["removed"], ["a"])
        self.assertEqual(frames[2]["objects"], ["a"])
        self.assertEqual(frames[2]["added"], ["a"])
        self.assertEqual(frames[3]["affected"], ["a"])
        self.assertNotIn("check", [f["verb"] for f in frames])
        self.assertNotIn("color", [f["verb"] for f in frames])
        self.assertNotIn("scene", [f["verb"] for f in frames])
        self.assertNotIn("animate", [f["verb"] for f in frames])

    def test_empty_visibility_frame_is_a_real_preview_not_an_error(self):
        result = build("a = box size=[10,10,10]\nhide a\nshow a", analyze_model=False)
        self.assertTrue(result.ok, result.error)
        frames = result.frames()
        self.assertEqual(len(frames), 3)
        empty = build("a = box size=[10,10,10]\nhide a", upto=2, analyze_model=False)
        self.assertTrue(empty.ok, empty.error)
        self.assertTrue(empty.empty)

    def test_delete_of_last_object_is_also_a_meaningful_empty_frame(self):
        result = build("a = box size=[10,10,10]\ndelete a", analyze_model=False)
        self.assertTrue(result.ok, result.error)
        frames = result.frames()
        self.assertEqual([f["line"] for f in frames], [1, 2])
        self.assertEqual(frames[-1]["objects"], [])
        self.assertEqual(frames[-1]["removed"], ["a"])


class PlaybackSourceContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        cls.viewer = (ROOT / "web/js/viewer.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "web/index.html").read_text(encoding="utf-8")

    def test_camera_pose_is_visible_and_has_canonical_angles(self):
        self.assertIn('id="camera-hud"', self.html)
        self.assertIn("getCameraPose()", self.viewer)
        self.assertIn("азимут", self.app)
        self.assertIn("наклон", self.app)

    def test_playback_has_no_automatic_end_stop(self):
        tick = self.viewer.split("  _tickAnimation(dt) {", 1)[1].split("\n  playAnimation", 1)[0]
        self.assertNotIn("this.playing = false", tick)
        self.assertNotIn("this.onEnd?.()", tick)
        self.assertIn("t % total", tick)

    def test_modal_suspend_does_not_freeze_animation_clock(self):
        loop = self.viewer.split("const loop = () => {", 1)[1].split("    };", 1)[0]
        self.assertLess(loop.index("_tickAnimation(dt)"), loop.index("if (this._sceneSuspended"))
        self.assertIn("document.hidden", loop)

    def test_view_controls_are_independent_and_persistent(self):
        set_grid = self.viewer.split("  setGrid(visible) {", 1)[1].split("\n  setGround", 1)[0]
        self.assertNotIn("this.ground.visible", set_grid)
        self.assertIn("groundVisible", self.viewer)
        self.assertIn("forma3d.view", self.app)
        self.assertIn("state.viewSettings", self.app)
        self.assertIn("scroll: true", self.app.split("function updateSequence", 1)[1].split("function showMorph", 1)[0])

    def test_script_hidden_objects_do_not_suppress_their_assembly_step(self):
        load = self.app.split("async function loadModel", 1)[1].split("function sandboxParams", 1)[0]
        focus = self.app.split("function focusFrameObject", 1)[1].split("function setAnimMode", 1)[0]
        self.assertIn("state.userHidden.forEach", load)
        self.assertNotIn("state.hidden.forEach", load)
        self.assertIn("state.userHidden.has", focus)
        self.assertIn("restoreSavedFocus", load)
        self.assertIn("state.viewer.focusObject(state.focusObject)", load)

    def test_dynamic_track_click_uses_original_event_path(self):
        self.assertIn("e.composedPath()", self.app)
        self.assertIn("path.includes(panel)", self.app)

    def test_follow_scroll_is_applied_before_highlight_position(self):
        place = self.app.split("function placeRunHighlight", 1)[1].split("function highlightScriptLine", 1)[0]
        self.assertLess(place.index("ta.scrollTop ="), place.index("const offset ="))
        loop = self.viewer.split("const loop = () => {", 1)[1].split("    };", 1)[0]
        self.assertLess(loop.index("_animateTiming(dt)"), loop.index("controls.update()"))


if __name__ == "__main__":
    unittest.main()
