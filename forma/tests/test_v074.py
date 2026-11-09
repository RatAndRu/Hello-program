"""0.74: полигонаж, пол, тени, оси и смешение стилей.

Проверяется то, что видно только на экране, но проверяемо в коде и на данных:
рёбра полигонажа совпадают с геометрией, пол не превращается в многоугольник,
маска тени не содержит модель, а смена стиля не оставляет параметров прошлого.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from forma.anime import PRESETS, normalize_style
from forma.run import build

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
VIEWER = (WEB / "js" / "viewer.js").read_text(encoding="utf-8")
PALETTE = (WEB / "js" / "style_presets.js").read_text(encoding="utf-8")
PAGE = (WEB / "index.html").read_text(encoding="utf-8")


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"{result.error}\n{script}")
    return result


class PolygonMode074Test(unittest.TestCase):
    """Полигонаж: явная заливка и рёбра из геометрии."""

    def test_scene_accepts_polygon_options(self):
        scene = ok(
            "к = box size=[20,20,20]\n"
            "scene poly=да poly_fill=сквозной poly_edges=структурные poly_angle=25"
        ).scene
        self.assertIs(scene.settings.get("poly"), True)
        self.assertEqual(scene.settings.get("poly_fill"), "сквозной")
        self.assertEqual(scene.settings.get("poly_edges"), "структурные")
        self.assertEqual(scene.settings.get("poly_angle"), 25.0)

    def test_unknown_polygon_values_are_rejected(self):
        for script, expected in (
            ("scene poly_fill=стекло", "граней полигонажа"),
            ("scene poly_edges=боковые", "рёбер полигонажа"),
        ):
            with self.subTest(script=script):
                result = build(f"к = box size=[20,20,20]\n{script}", analyze_model=False)
                self.assertFalse(result.ok)
                self.assertIn(expected, json.dumps(result.error, ensure_ascii=False))

    def test_viewer_has_two_fill_modes(self):
        self.assertIn("this.polygonFill = 'непрозрачный';", VIEWER)
        self.assertIn("this.polygonFill === 'сквозной'", VIEWER)
        # Непрозрачный режим отодвигает грани по глубине, а не двигает линию
        # мировым сдвигом: иначе на разной дальности линии то пропадают, то
        # просвечивают сквозь деталь.
        self.assertIn("m.polygonOffsetFactor = 1;", VIEWER)
        self.assertNotIn("gl_Position.z -= 0.00008 * gl_Position.w", VIEWER)

    def test_structural_edges_come_from_geometry(self):
        self.assertIn("creaseEdgePositions(geometry, this.polygonAngle)", VIEWER)
        self.assertIn("export function creaseEdgePositions", (WEB / "js" / "topology_lines.js")
                      .read_text(encoding="utf-8"))

    def test_polygons_stay_visible_in_art_style(self):
        self.assertIn("this._overlays.forEach((overlay) => { overlay.visible = this.polygons; });",
                      VIEWER)
        self.assertNotIn("overlay.visible = false", VIEWER)
        self.assertIn("return this._animeOn() ? 0x1b1f27 : 0x78aebe;", VIEWER)


class GroundAndShadow074Test(unittest.TestCase):
    """Пол по стрелке прогиба и честная маска тени."""

    def test_ground_segments_follow_radius(self):
        self.assertIn("_groundSegments(radius)", VIEWER)
        self.assertIn("this._groundSegments(groundRadius)", VIEWER)
        # Формула: 2·acos(1 − s/R); для радиуса 2048 мм при прогибе 0.3 мм это
        # около 200 сегментов — хорда 64 мм, но отклонение меньше 0.3 мм.
        def segments(radius: float, sagitta: float = 0.3) -> int:
            step = 2 * math.acos(max(-1.0, min(1.0, 1 - sagitta / radius)))
            return max(96, min(2048, math.ceil(2 * math.pi / step)))

        for radius in (10.0, 620.0, 2048.0):
            with self.subTest(radius=radius):
                count = segments(radius)
                sagitta = radius * (1 - math.cos(math.pi / count))
                self.assertLessEqual(sagitta, 0.31)

    def test_floor_is_repainted_and_marked_dirty(self):
        self.assertIn("_repaintGrid()", VIEWER)
        self.assertIn("this._shadowDirty = Boolean(this.groundVisible);", VIEWER)

    def test_shadow_mask_has_no_model(self):
        self.assertIn("if (this.model) this.model.visible = false;", VIEWER)
        self.assertIn("this._shadowMaskReady = true;", VIEWER)
        self.assertIn("uniform float uShadowMask;", VIEWER)
        # Точная маска главнее догадки по яркости.
        self.assertIn("mix(guessShadow, max(guessShadow * 0.35, castMask), uShadowMask)", VIEWER)


class AxesAndLineWidth074Test(unittest.TestCase):
    """Оси от нового габарита, тонкие линии и честная глубина стрелок."""

    def test_axes_follow_new_bbox(self):
        self.assertIn("this.setAxes(this.axesVisible);\n  }", VIEWER)
        self.assertIn("color, depthTest: true, depthWrite: false, transparent: true, opacity: 0.98,",
                      VIEWER)

    def test_hairline_contours_possible(self):
        self.assertIn("float radius = max(uLine * 0.5 * uPixelRatio, 0.28);", VIEWER)
        self.assertIn('id="anime-line" min="0.1" max="6" step="0.05"', PAGE)
        self.assertEqual(normalize_style({"mode": "аниме", "line": 0.1})["line"], 0.1)
        with self.assertRaises(Exception):
            normalize_style({"mode": "аниме", "line": 0.01})

    def test_python_contour_survives_thin_line(self):
        # Тоньше 0.2 px линия раньше просто не рисовалась: маска оставалась
        # пустой. Теперь она ослабляется, а не исчезает.
        from forma import anime
        source = Path(anime.__file__).read_text(encoding="utf-8")
        self.assertIn("coverage = max(0.25, radius / 0.2)", source)


class StyleMixing074Test(unittest.TestCase):
    """Смена стиля начинается с пресета — и в окне, и в сценарии."""

    def test_presets_are_pure(self):
        for mode, preset in PRESETS.items():
            with self.subTest(mode=mode):
                clean = normalize_style({"mode": mode})
                for key, value in preset.items():
                    self.assertEqual(clean[key], value, f"{mode}: {key}")

    def test_anime_has_no_sketch_hatch(self):
        anime = normalize_style({"mode": "аниме"})
        sketch = normalize_style({"mode": "скетч"})
        self.assertEqual(anime["hatch"], 0.0)
        self.assertGreater(sketch["hatch"], 0.5)
        self.assertEqual(normalize_style({"mode": "линия"})["shade"], False)
        self.assertEqual(normalize_style({"mode": "аниме"})["shade"], True)

    def test_js_uses_same_rule(self):
        self.assertIn("mergeAnimeStyle(state.anime, patch || {})", (WEB / "js" / "app.js")
                      .read_text(encoding="utf-8"))
        self.assertIn("export function mergeAnimeStyle", PALETTE)
        self.assertIn("export const ANIME_MODES", PALETTE)
        # Пресеты живут в одном месте: второй копии в app.js быть не должно.
        app = (WEB / "js" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("const ANIME_MODES = {", app)

    def test_style_uniforms_are_pushed_every_frame(self):
        self.assertIn("if (animeOn) this._applyAnimeUniforms();", VIEWER)
        # Сохранённое «до стиля» значение wireframe больше не перезаписывается.
        self.assertNotIn("if (saved) saved[1] = on;", VIEWER)


class FlatShading074Test(unittest.TestCase):
    """Проверка «сетка = поверхность» без догадок."""

    def test_flat_shading_exists_and_survives_reload(self):
        self.assertIn("setFlatShading(on)", VIEWER)
        self.assertIn("m.flatShading = this.flatShading;", VIEWER)
        self.assertIn("this.setFlatShading(this.flatShading === true);", VIEWER)
        self.assertIn('id="opt-flat"', PAGE)
        self.assertIn("setFlatShading(e.target.checked)", (WEB / "js" / "app.js").read_text(encoding="utf-8"))


class UiPolygonControls074Test(unittest.TestCase):
    """Настройки полигонажа доступны из окна и переживают перезагрузку."""

    def test_controls_exist(self):
        for element in ('id="poly-fill"', 'id="poly-edges"', 'id="poly-angle"'):
            with self.subTest(element=element):
                self.assertIn(element, PAGE)

    def test_options_are_persisted_and_restored(self):
        app = (WEB / "js" / "app.js").read_text(encoding="utf-8")
        for token in ("polyFill: state.polyFill", "polyEdges: state.polyEdges",
                      "polyAngle: state.polyAngle", "state.viewer?.setPolygonOptions(polygonOptions())"):
            with self.subTest(token=token):
                self.assertIn(token, app)

    def test_payload_scene_settings_apply(self):
        self.assertIn("if (s.poly_fill !== undefined", VIEWER)
        self.assertIn("this.setPolygonOptions({", VIEWER)


class SceneFile074Test(unittest.TestCase):
    """Параметры полигонажа доезжают до проекта, а не только до окна."""

    def test_scene_survives_roundtrip(self):
        result = ok("к = box size=[20,20,20]\nscene poly_fill=непрозрачный poly_edges=сетка poly_angle=32")
        payload = json.loads(json.dumps({"settings": result.scene.settings}, ensure_ascii=False))
        self.assertEqual(payload["settings"]["poly_edges"], "сетка")
        self.assertEqual(payload["settings"]["poly_angle"], 32.0)


if __name__ == "__main__":
    unittest.main()
