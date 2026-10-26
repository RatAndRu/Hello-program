"""0.29: дисковая пила, честное зеркало, поэлементное свечение, причина «нет модели».

Проверяется то, что можно проверить без браузера: геометрия пилы и её ошибки,
наличие и логика JS-модулей (колесо, план-зеркало, emissive-bloom), передача
рамок параметра в интерфейс и разметка окон после ревизии.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from forma.errors import DslError
from forma.geometry import manifold_mesh
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]


def _solid(script: str):
    b = build(script, analyze_model=False)
    assert b.ok, (b.error or {}).get("message")
    name = next(iter(b.scene.objects))
    return b.scene.objects[name].manifold, b


class SawShapeTest(unittest.TestCase):
    """Дисковая пила — настоящий плоский диск с зубьями, а не «гармошка»."""

    def test_op_registered(self):
        import forma.run  # noqa: F401
        from forma.ops import OPS

        spec = OPS["saw"]
        self.assertEqual(spec.category, "Примитивы")
        self.assertTrue(spec.summary and spec.example and spec.params)
        for alias in ("пила", "дисковая_пила", "циркулярка", "circular_saw"):
            self.assertIn(alias, spec.aliases + (spec.name,))
        for key in ("diameter", "thickness", "teeth", "tooth", "shape", "rake",
                    "gullet", "kerf", "hole", "windows", "detail"):
            self.assertIn(key, spec.params)

    def test_default_disc_flat_and_round(self):
        m, _ = _solid("п = saw diameter=200 thickness=2.5 teeth=24")
        bb = m.bounding_box()
        width, thick, height = (bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
        # с 0.41 пила стоит на ребре лицом к зрителю (−Y): толщина идёт по Y,
        # полотно круглое в XZ, а не «лепестки» по высоте
        self.assertLess(thick, 5.0)
        self.assertGreater(width, 190.0)
        self.assertAlmostEqual(width, height, delta=0.8)
        # плашмя — лежит, как раньше
        flat, _ = _solid("п = saw diameter=200 thickness=2.5 teeth=24 plane=плашмя")
        fb = flat.bounding_box()
        self.assertLess(fb[5] - fb[2], 5.0)
        self.assertAlmostEqual(fb[3] - fb[0], fb[4] - fb[1], delta=0.8)
        self.assertEqual(m.genus(), 1)          # одно сквозное отверстие
        self.assertLess(m.num_tri(), 12000)

    def test_outer_diameter_is_exact(self):
        for teeth in (12, 24, 40):
            m, _ = _solid(f"п = saw diameter=160 thickness=2 teeth={teeth} "
                          "plane=плашмя")
            verts, _ = manifold_mesh(m)
            r = float(np.linalg.norm(verts[:, :2], axis=1).max())
            self.assertAlmostEqual(r, 80.0, delta=0.4,
                                   msg=f"вершина зуба не на диаметре при {teeth} зубьях")

    def test_four_tooth_shapes_build(self):
        out = {}
        for shape in ("треугольные", "трапеция", "крюк", "волна"):
            m, _ = _solid(f"п = saw diameter=150 teeth=18 shape={shape} "
                          "plane=плашмя")
            verts, _ = manifold_mesh(m)
            radii = np.linalg.norm(verts[:, :2], axis=1)
            out[shape] = (float(radii.max()), float(radii.min()), m.genus())
            self.assertEqual(out[shape][2], 1)
            self.assertAlmostEqual(out[shape][0], 75.0, delta=0.4)
        # форма меняет профиль: набор радиусов у волны и треугольника разный
        self.assertGreater(out["волна"][1], out["треугольные"][1] - 1e-6)

    def test_rake_moves_the_tip(self):
        a, _ = _solid("п = saw diameter=160 teeth=16 rake=30 plane=плашмя")
        b, _ = _solid("п = saw diameter=160 teeth=16 rake=-30 plane=плашмя")
        va, _ = manifold_mesh(a)
        vb, _ = manifold_mesh(b)
        # у положительного переднего угла вершина смещена вперёд по ходу
        tip_a = va[np.argmax(np.linalg.norm(va[:, :2], axis=1))][:2]
        tip_b = vb[np.argmax(np.linalg.norm(vb[:, :2], axis=1))][:2]
        ang_a = np.degrees(np.arctan2(tip_a[1], tip_a[0])) % 360
        ang_b = np.degrees(np.arctan2(tip_b[1], tip_b[0])) % 360
        self.assertNotAlmostEqual(ang_a, ang_b, places=1)
        self.assertAlmostEqual(float(np.linalg.norm(tip_a)), 80.0, delta=0.4)

    def test_kerf_widens_only_teeth(self):
        thin, _ = _solid("п = saw diameter=200 thickness=2 teeth=24 kerf=3.6 "
                         "plane=плашмя")
        plain, _ = _solid("п = saw diameter=200 thickness=2 teeth=24 kerf=2 "
                          "plane=плашмя")
        thin_bb = thin.bounding_box()
        plain_bb = plain.bounding_box()
        self.assertAlmostEqual(thin_bb[5] - thin_bb[2], 3.6, delta=0.05)
        self.assertAlmostEqual(plain_bb[5] - plain_bb[2], 2.0, delta=0.05)

    def test_windows_make_real_holes(self):
        m, _ = _solid("п = saw diameter=160 teeth=24 windows=5")
        self.assertEqual(m.genus(), 6)          # вал + пять окон
        none, _ = _solid("п = saw diameter=160 teeth=24")
        self.assertEqual(none.genus(), 1)

    def test_hole_and_thickness(self):
        m, _ = _solid("п = saw diameter=200 thickness=3 hole=22 plane=плашмя")
        verts, _ = manifold_mesh(m)
        radii = np.linalg.norm(verts[:, :2], axis=1)
        self.assertAlmostEqual(float(radii.min()), 11.0, delta=0.3)

    def test_unknown_shape_is_explained(self):
        b = build("п = saw shape=пилорама")
        self.assertFalse(b.ok)
        err = b.error or {}
        self.assertIn("пилорама", err.get("message", ""))
        self.assertIn("треугольные", err.get("hint", ""))

    def test_hole_too_big_is_explained(self):
        b = build("п = saw diameter=60 hole=58")
        self.assertFalse(b.ok)
        err = b.error or {}
        self.assertEqual(err.get("param"), "hole")
        self.assertIn("58", err.get("message", ""))
        self.assertTrue(err.get("hint"))
        # и сама геометрия просит уменьшить отверстие, а не «пила распалась»
        b2 = build("п = saw diameter=200 hole=190")
        self.assertFalse(b2.ok)
        self.assertEqual((b2.error or {}).get("param"), "hole")

    def test_aliases_build(self):
        for alias in ("пила", "циркулярка", "circular_saw"):
            b = build(f"д = {alias} diameter=120 teeth=12")
            self.assertTrue(b.ok, (b.error or {}).get("message"))


class PreviewReasonTest(unittest.TestCase):
    """«Нет модели» должно объяснять, какой параметр и какие у него рамки."""

    def test_bounds_travel_to_interface(self):
        b = build("п = saw diameter=200 teeth=900")
        err = b.error or {}
        self.assertEqual(err.get("param"), "teeth")
        self.assertEqual(err.get("min"), 4)
        self.assertEqual(err.get("max"), 200)
        self.assertEqual(err.get("bounds"), "4…200")
        self.assertEqual(err.get("value"), 900.0)
        self.assertIn("4…200", err.get("message", ""))
        self.assertTrue(err.get("hint"))

    def test_lower_bound_message(self):
        b = build("п = saw teeth=2")
        err = b.error or {}
        self.assertEqual(err.get("param"), "teeth")
        self.assertIn("4", err.get("bounds", ""))
        self.assertIn("2", err.get("message", ""))

    def test_text_value_message(self):
        b = build("п = saw teeth=много")
        self.assertFalse(b.ok)
        err = b.error or {}
        self.assertEqual(err.get("param"), "teeth")
        self.assertEqual(err.get("value"), "много")

    def test_error_dict_keeps_old_fields(self):
        err = DslError("беда", hint="подсказка", line=3, command="к = cube",
                       param="size", minv=1, maxv=5, value=9)
        data = err.to_dict()
        self.assertEqual(data["message"], "беда")
        self.assertEqual(data["hint"], "подсказка")
        self.assertEqual(data["line"], 3)
        self.assertEqual(data["command"], "к = cube")
        self.assertEqual(data["bounds"], "1…5")

    def test_card_thumbnail_shows_reason(self):
        js = (ROOT / "web/js/toolpreview.js").read_text(encoding="utf-8")
        self.assertIn("wrapText", js)
        self.assertIn("допустимо", js)
        self.assertIn("info.bounds", js)

    def test_app_marks_bad_field(self):
        app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("markToolFieldError", app)
        self.assertIn("tool-field-note", app)
        self.assertIn("Почему нет модели", app)
        self.assertIn("err.bounds", app)

    def test_preview_api_returns_error_details(self):
        from forma.webui import AppState

        st = AppState()
        res = st.preview("п = saw diameter=200 teeth=900")
        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error", {}).get("param"), "teeth")
        self.assertEqual(res.get("error", {}).get("bounds"), "4…200")


class ViewerModulesTest(unittest.TestCase):
    """Колесо, зеркало и свечение живут в отдельных модулях с проверяемой логикой."""

    def test_wheel_zoom_direction(self):
        js = (ROOT / "web/js/viewzoom.js").read_text(encoding="utf-8")
        self.assertIn("export function wheelZoom", js)
        self.assertIn("0.45", js)          # нижний предел
        self.assertIn("3.2", js)           # верхний предел
        self.assertIn("Math.exp", js)
        preview = (ROOT / "web/js/toolpreview.js").read_text(encoding="utf-8")
        self.assertIn("wheelZoom", preview)

    def test_mirror_normal_faces_the_camera(self):
        js = (ROOT / "web/js/planarmirror.js").read_text(encoding="utf-8")
        self.assertIn("export function platePlane", js)
        self.assertIn("eye", js)                       # нормаль направляется к камере
        self.assertIn("normal.dot(dir) < 0", js)
        self.assertIn("normal.negate()", js)
        self.assertIn("clippingPlanes", js)             # под зеркалом не просвечивает
        self.assertIn("texture2DProj", js)
        viewer = (ROOT / "web/js/viewer.js").read_text(encoding="utf-8")
        self.assertIn("PlanarMirror", viewer)
        self.assertNotIn("CubeCamera", viewer)

    def test_bloom_only_for_emissive(self):
        js = (ROOT / "web/js/selectivebloom.js").read_text(encoding="utf-8")
        self.assertIn("export class EmissiveBloomPass", js)
        self.assertIn("emissiveIntensity", js)
        self.assertIn("MeshBasicMaterial", js)          # чёрные перекрыватели
        viewer = (ROOT / "web/js/viewer.js").read_text(encoding="utf-8")
        self.assertIn("EmissiveBloomPass", viewer)
        self.assertNotIn("UnrealBloomPass", viewer)
        self.assertIn("mirrorSource", viewer)           # PBR-настройки живы под шейдером


class UiLayoutTest(unittest.TestCase):
    """Ревизия окон: ничего не сжимает соседа, инструменты компактнее."""

    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
        cls.app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")

    def test_viewer_head_is_grouped(self):
        self.assertIn('class="tool-seg"', self.html)
        self.assertIn('class="tool-sep"', self.html)
        # дубли переключателей убраны из шапки — они в панели «вид»
        self.assertNotIn('id="btn-grid"', self.html)
        self.assertNotIn('id="btn-wire"', self.html)
        self.assertIn('id="opt-grid"', self.html)
        self.assertIn('id="opt-poly"', self.html)

    def test_show_toggles_live_in_panel(self):
        for marker in ('id="btn-spin"', 'id="btn-focus-sel"', 'id="btn-orbit-sel"',
                       'id="btn-occl"', 'id="show-chips"'):
            self.assertIn(marker, self.html)
        panel = self.html.split('id="studio-panel"', 1)[1]
        self.assertIn('id="btn-spin"', panel)
        self.assertIn('id="btn-orbit-sel"', panel)

    def test_buttons_never_shrink(self):
        self.assertIn("button {\n  flex: 0 0 auto;", self.css)

    def test_heads_grow_instead_of_clipping(self):
        self.assertIn("min-height: 40px", self.css)
        self.assertIn(".panel-head {", self.css)
        head = self.css.split(".modal-head {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-wrap: nowrap", head)

    def test_tool_cards_use_inspector_grid(self):
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(92px, 1fr))",
                      self.css)
        cap = self.css.split(".tool-field-cap {", 1)[1].split("}", 1)[0]
        self.assertIn("text-overflow: ellipsis", cap)
        desc = self.css.split(".tool-desc {", 1)[1].split("}", 1)[0]
        self.assertIn("line-clamp", desc)

    def test_saw_card_in_tools(self):
        block = self.app.split("const TOOL_SHAPES = [", 1)[1].split("const TOOL_RECIPES", 1)[0]
        self.assertIn("op: 'saw'", block)
        card = block.split("op: 'saw'", 1)[1].split("op: '", 1)[0]
        self.assertIn("choices: ['треугольные', 'трапеция', 'крюк', 'волна']", card)
        self.assertIn("min: 20", card)
        self.assertIn("max: 4000", card)

    def test_field_tooltips_show_bounds(self):
        self.assertIn("допустимо ${p.min", self.app)
        self.assertIn("caption.title = p.label", self.app)


if __name__ == "__main__":
    unittest.main()
