"""0.17: детали второго эшелона, качение колёс, мировые UV, примеры и интерфейс."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from forma.run import build
from forma.textures import uv_triangles

ROOT = Path(__file__).resolve().parent.parent


def scene(script: str):
    res = build(script)
    if res.error:
        raise AssertionError(res.error)
    return res


class NewPartsTest(unittest.TestCase):
    """Новые инструменты: каждое тело замкнуто, цельно и нужных размеров."""

    CASES = {
        "панель = panel size=[240,160,22] wall=3 round=8": (240, 160, 25),
        "косынка = gusset leg=70 height=55 thickness=6": (70, 6, 55),
        "ножка = leg height=90 top=34 bottom=22 flange=8": (34, 34, 90),
        "профиль = profile2020 length=300 size=20": (20, 20, 300),
        "люверс = grommet diameter=12 height=8 wall=1.6 flange=3": (21.2, 21.2, 8),
        "червяк = worm length=90 diameter=30 pitch=8 depth=4": (30, 30, 90),
        "рог = horn length=160 radius=22 tip=3 bend=55": (160, 44, 79),
        "ящик = drawer size=[420,480,180] wall=14 front=18": (427, 503, 180),
    }

    def test_parts_are_solid(self):
        for script, (sx, sy, sz) in self.CASES.items():
            with self.subTest(script=script.split("=")[0].strip()):
                res = scene(script)
                obj = res.scene.visible_solids()[-1]
                bb = obj.manifold.bounding_box()
                self.assertEqual(len(obj.manifold.decompose()), 1, script)
                self.assertTrue(obj.manifold.is_empty() is False)
                self.assertEqual(str(obj.manifold.status()), "Error.NoError")
                self.assertAlmostEqual(bb[3] - bb[0], sx, delta=max(2.0, sx * 0.02))
                self.assertAlmostEqual(bb[4] - bb[1], sy, delta=max(2.0, sy * 0.03))
                self.assertAlmostEqual(bb[5] - bb[2], sz, delta=max(2.0, sz * 0.04))

    def test_knurl_keeps_one_body(self):
        res = scene("ручка = cylinder radius=16 height=70 segments=48\n"
                    "ручка = knurl [ручка] count=24 depth=1")
        obj = res.scene.visible_solids()[-1]
        self.assertEqual(len(obj.manifold.decompose()), 1)
        bb = obj.manifold.bounding_box()
        self.assertAlmostEqual(bb[2], 0.0, delta=0.01)
        self.assertLess(obj.manifold.volume(), 3.14159 * 16 * 16 * 70)
        self.assertGreater(obj.manifold.volume(), 3.14159 * 14 * 14 * 70)

    def test_rail_is_channel(self):
        res = scene("рельс = rail length=400 width=30 height=14 wall=2")
        obj = res.scene.visible_solids()[-1]
        solid_box = 400 * 30 * 14
        self.assertLess(obj.manifold.volume(), solid_box * 0.75)
        self.assertEqual(len(obj.manifold.decompose()), 1)


class WheelTest(unittest.TestCase):
    """Колесо: ось Y, катится вдоль X, спицы в плоскости колеса."""

    def test_axis_and_spokes(self):
        res = scene("к = wheel diameter=600 width=140 rim=30 spokes=5 hub=60 tire=18")
        bb = res.scene.visible_solids()[-1].manifold.bounding_box()
        self.assertAlmostEqual(bb[3] - bb[0], 600, delta=1)
        self.assertAlmostEqual(bb[4] - bb[1], 140, delta=1)
        self.assertAlmostEqual(bb[5] - bb[2], 600, delta=1)

    def test_spokes_do_not_stick_out(self):
        res = scene("к = wheel diameter=200 width=40 rim=12 spokes=6 hub=30 tire=10")
        obj = res.scene.visible_solids()[-1]
        bb = obj.manifold.bounding_box()
        self.assertLessEqual(bb[4] - bb[1], 40.5)
        self.assertEqual(len(obj.manifold.decompose()), 1)


class TextureSeamTest(unittest.TestCase):
    """UV в мировых координатах: соседние детали продолжают рисунок."""

    def test_world_origin_is_shared(self):
        verts = np.array([[0, 0, 0], [0, 0, 10], [10, 0, 0]], dtype=float)
        faces = np.array([[0, 1, 2]], dtype=np.int64)
        a = uv_triangles(verts, faces, "auto", origin=(0, 0, 0))
        moved = verts + np.array([500.0, 0.0, 0.0])
        b = uv_triangles(moved, faces, "auto", origin=(0, 0, 0))
        self.assertAlmostEqual(b[0][0] - a[0][0], 500.0 / 140.0, places=4)
        self.assertAlmostEqual(a[0][1], b[0][1], places=6)

    def test_object_origin_would_drift(self):
        verts = np.array([[0, 0, 0], [0, 0, 10], [10, 0, 0]], dtype=float)
        faces = np.array([[0, 1, 2]], dtype=np.int64)
        a = uv_triangles(verts, faces, "auto")
        moved = verts + np.array([500.0, 0.0, 0.0])
        b = uv_triangles(moved, faces, "auto", bbox=moved.min(axis=0).tolist()
                         + moved.max(axis=0).tolist())
        # без общего начала координат рисунок начинается заново на каждой детали
        self.assertAlmostEqual(a[0][0], b[0][0], places=6)

    def test_uv_scale_is_millimetres(self):
        verts = np.array([[0, 0, 0], [140, 0, 0], [0, 0, 140]], dtype=float)
        faces = np.array([[0, 1, 2]], dtype=np.int64)
        uv = uv_triangles(verts, faces, "auto", origin=(0, 0, 0))
        self.assertAlmostEqual(abs(uv[1][0] - uv[0][0]), 1.0, places=4)


class ExamplesTest(unittest.TestCase):
    """Витрина, мотоцикл и часы: собираются без ошибок и проходят проверки."""

    def _example(self, name):
        res = scene((ROOT / "examples" / f"{name}.forma").read_text(encoding="utf-8"))
        checks = res.analysis["checks"]
        self.assertTrue(checks, name)
        failed = [c for c in checks if not c["ok"]]
        self.assertFalse(failed, f"{name}: " + "; ".join(
            f"{c['text']} — {c['actual']}" for c in failed))
        return res

    def test_motorcycle(self):
        res = self._example("motorcycle")
        names = {o.name for o in res.visible_solids()}
        for part in ("колесо_зад", "колесо_перед", "бак", "седло", "глушитель"):
            self.assertIn(part, names)
        self.assertGreaterEqual(len(res.visible_solids()), 30)
        plan = res.scene.animation_plan()
        self.assertEqual(set(plan["scenes"]), {"езда", "прыжок"})
        kinds = {c["kind"] for c in plan["clips"]}
        self.assertTrue({"roll", "turn", "move"} <= kinds, kinds)
        self.assertIn("рама", plan.get("groups") or {})

    def test_clock(self):
        res = self._example("clock")
        names = {o.name for o in res.visible_solids()}
        for part in ("баланс", "анкер", "анкерное", "барабан", "минутное", "секундная"):
            self.assertIn(part, names)
        plan = res.scene.animation_plan()
        self.assertGreaterEqual(len(plan["clips"]), 20)
        self.assertEqual(set(plan["scenes"]), {"ход"})
        self.assertEqual({c.get("scene") for c in plan["clips"]}, {"ход"})
        self.assertEqual({c["kind"] for c in plan["clips"]}, {"turn"})

    def test_showcase_has_many_tools(self):
        res = self._example("showcase")
        names = {o.name for o in res.visible_solids()}
        for part in ("турбина", "плитки", "ряд_штифтов", "листва", "профиль",
                     "червяк", "направляющая", "панель"):
            self.assertIn(part, names)
        self.assertGreaterEqual(len(res.visible_solids()), 30)


class InterfaceTest(unittest.TestCase):
    """Интерфейс: удаление клавишей, сцены, кисть, кубы и новые карточки."""

    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        cls.viewer = (ROOT / "web" / "js" / "viewer.js").read_text(encoding="utf-8")

    def test_delete_key(self):
        self.assertIn("Delete", self.app)
        self.assertIn("Backspace", self.app)
        self.assertIn("deleteObject", self.app)
        self.assertIn("clearSpaceSelection", self.app)

    def test_tool_cards(self):
        for op in ("panel", "drawer", "profile2020", "worm", "horn",
                   "grommet", "leg", "rail", "gusset"):
            self.assertIn(f"op: '{op}'", self.app)
        blocks = self.app.split("const TOOL_SHAPES = [", 1)[1].split("const TOOL_RECIPES", 1)[0]
        self.assertGreaterEqual(blocks.count("op: '"), 40)
        self.assertIn("group:", blocks)

    def test_recipes_are_separate(self):
        recipes = self.app.split("const TOOL_RECIPES = [", 1)[1].split("function uniqueObjectName", 1)[0]
        for title in ("Скрутка", "Изгиб", "Резьба: болт", "Резьба: гайка", "Фаска", "Облегчение"):
            self.assertIn(f"title: '{title}'", recipes)
        self.assertGreaterEqual(recipes.count("title:"), 12)

    def test_viewer_features(self):
        for name in ("setScene", "scenes", "setObjectPolygons", "objectPolygons",
                     "selectSpaceForObject", "paintMode", "setPaintMode", "renderNow"):
            self.assertIn(name, self.viewer)
        self.assertIn("preserveDrawingBuffer", self.viewer)

    def test_gif_export_wired(self):
        gif = (ROOT / "web" / "js" / "gif.js").read_text(encoding="utf-8")
        self.assertIn("encodeGif", gif)
        self.assertIn("medianCut", gif)
        self.assertIn("exportAnimationGif", self.app)
        self.assertIn("exportAnimationWebm", self.app)
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-format="gif"', html)
        self.assertIn('data-format="webm"', html)


class UiPolishTest(unittest.TestCase):
    """Замечания к интерфейсу: строки сценария, заслонки, камера, статистика."""

    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        cls.viewer = (ROOT / "web" / "js" / "viewer.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_line_highlight_ui(self):
        for name in ("placeRunHighlight", "highlightScriptLine", "highlightFromTime",
                     "activeClipsAt", "pickClosest", "clearScriptHighlight"):
            self.assertIn(f"function {name}", self.app)
        self.assertIn('id="code-run"', self.html)
        self.assertIn('id="code-run-soft"', self.html)
        self.assertIn(".code-run-soft", (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8"))

    def test_occluders(self):
        for name in ("_occludingNames", "_applyGhosts", "refreshOccluders", "setOccluders",
                     "ghostOccluders"):
            self.assertIn(name, self.viewer)
        self.assertIn("depthWrite = false", self.viewer)
        self.assertIn('id="btn-occl"', self.html)
        self.assertIn("state.occluders = !state.occluders", self.app)
        # каркас заслонок не перехватывает клик
        self.assertIn("ghosts.has(hitName)", self.viewer)

    def test_orbit_around_selection(self):
        self.assertIn("setOrbitTarget", self.viewer)
        self.assertIn('id="btn-orbit-sel"', self.html)
        self.assertIn("orbitSelection", self.app)
        self.assertIn("state.viewer?.setOrbitTarget(name)", self.app)

    def test_object_stats(self):
        self.assertIn("function renderObjectStats", self.app)
        self.assertIn("function renderSceneStats", self.app)
        self.assertIn('id="btn-focus-sel"', self.html)

    def test_no_autoplay(self):
        self.assertIn("Не запускаем анимацию сами", self.app)
        self.assertIn("анимация готова", self.app)
        self.assertNotIn("state.viewer.playAnimation(true);\n      state.anim.playing", self.app)

    def test_space_cell_covers_model(self):
        # ограничение 32 секторов убрано: объём обхватывает модель
        self.assertIn("MAX_TOTAL", self.viewer)
        self.assertIn("rebuildSpace", self.viewer)
        self.assertNotIn("Math.min(32, n)", self.viewer)
        self.assertIn("onSpaceCell", self.app)

    def test_frames_skip_service_commands(self):
        from forma.run import FRAME_SKIP_VERBS
        for verb in ("check", "color", "probe", "passport", "light", "scene", "param", "note"):
            self.assertIn(verb, FRAME_SKIP_VERBS)

    def test_payload_has_object_details(self):
        res = scene("к = box size=[40,20,10]\n"
                    "о = cylinder radius=5 height=20 at=[60,0,0]\n"
                    "check к size 39..41")
        payload = res.payload()
        obj = payload["objects"][0]
        self.assertEqual(obj["parts"], 1)
        self.assertGreater(obj["area_mm2"], 0)
        frames = payload["frames"]
        self.assertTrue(frames)
        self.assertFalse([f for f in frames if (f.get("verb") or "") in
                          ("check", "color", "light", "scene")])
        self.assertLess(len(frames), len(payload["steps"]))


if __name__ == "__main__":
    unittest.main()
