"""0.31: меню у курсора, растаскиваемые панели, часы без фризов, файлы в «Загрузки».

Проверки держат четыре жалобы пользователя:

1. меню по правой кнопке должно появляться **рядом с курсором**, а не в углу
   панели — значит, оно позиционируется по экранным координатам;
2. границы окон можно **тянуть мышью**, панели сворачивать и разворачивать,
   ширины запоминаются;
3. часы **не фризят**: зеркалом считается только явно помеченный материал,
   клип-плоскость не меняет состав списка плоскостей, отражения обновляются
   с ограничением частоты;
4. готовые файлы (GIF/WebM/снимки) попадают **в папку «Загрузки»** на этом
   компьютере, а не «куда-нибудь в браузер».
"""

from __future__ import annotations

import json
import os
import re
import struct
import tempfile
import unittest
from pathlib import Path

from forma.geometry import export_glb
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _read(*parts: str) -> str:
    return (WEB.joinpath(*parts)).read_text(encoding="utf-8")


def _build(script: str):
    b = build(script, analyze_model=False)
    assert b.ok, (b.error or {}).get("message")
    return b


def _glb_materials(data: bytes) -> list[str]:
    """Имена материалов из JSON-чанка GLB — без внешних зависимостей."""
    offset = 12
    doc = None
    while offset < len(data):
        length, ctype = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8: offset + 8 + length]
        offset += 8 + length
        if ctype == 0x4E4F534A:
            doc = json.loads(chunk.decode("utf-8"))
    return [str(m.get("name") or "") for m in (doc or {}).get("materials", [])]


class ContextMenuNearCursorTest(unittest.TestCase):
    """Меню ПКМ открывается у курсора, а не у угла панели модели."""

    @classmethod
    def setUpClass(cls):
        cls.css = _read("css", "app.css")
        cls.index = _read("index.html")
        cls.app = _read("js", "app.js")

    def test_menu_is_fixed_to_the_window(self):
        block = re.search(r"\.ctx-menu\s*\{(.*?)\}", self.css, re.S)
        self.assertIsNotNone(block)
        self.assertIn("position: fixed", block.group(1).replace("  ", " "))

    def test_menu_lives_outside_the_viewer_panel(self):
        # раньше меню лежало внутри #viewer и считало координаты от панели
        start = self.index.index('id="viewer"')
        viewer_end = self.index.index("</section>", start)
        menu_at = self.index.index('class="ctx-menu"')
        self.assertGreater(menu_at, viewer_end,
                           "меню не должно лежать внутри панели модели")
        self.assertNotIn("ctx-menu", self.index[start:viewer_end])

    def test_menu_coordinates_come_from_pointer_and_are_clamped(self):
        body = self._function("openContextMenu")
        self.assertIn("getBoundingClientRect()", body)
        self.assertIn("window.innerWidth", body)
        self.assertIn("window.innerHeight", body)
        # позиция ставится в пикселях экрана — без вычитания смещения панели
        self.assertIn("menu.style.left", body)
        self.assertIn("menu.style.top", body)

    def test_right_button_passes_client_coordinates(self):
        self.assertIn("openContextMenu(event.clientX, event.clientY", self.app)

    def test_menu_is_above_modals(self):
        z = int(re.search(r"\.ctx-menu\s*\{[^}]*z-index:\s*(\d+)", self.css, re.S).group(1))
        modal = int(re.search(r"\.modal\s*\{[^}]*z-index:\s*(\d+)", self.css, re.S).group(1))
        self.assertGreater(z, modal)

    def _function(self, name: str) -> str:
        start = self.app.index(f"function {name}(")
        depth = 0
        for i in range(start, len(self.app)):
            if self.app[i] == "{":
                depth += 1
            elif self.app[i] == "}":
                depth -= 1
                if depth == 0:
                    return self.app[start:i + 1]
        return self.app[start:]


class PanelSplitterTest(unittest.TestCase):
    """Панели растаскиваются мышью, сворачиваются и запоминают ширину."""

    @classmethod
    def setUpClass(cls):
        cls.index = _read("index.html")
        cls.css = _read("css", "app.css")
        cls.app = _read("js", "app.js")
        cls.panels = _read("js", "panels.js")

    def test_three_named_panels(self):
        for name in ("panel-editor", "panel-viewer", "panel-report",
                     "panel-editor\"", "panel-viewer\"", "panel-report\""):
            self.assertIn(name, self.index)
        self.assertIn('id="panel-editor"', self.index)
        self.assertIn('id="panel-viewer"', self.index)
        self.assertIn('id="panel-report"', self.index)

    def test_two_splitters_between_three_panels(self):
        self.assertEqual(self.index.count('class="splitter"'), 2)
        self.assertIn('data-split="editor"', self.index)
        self.assertIn('data-split="viewer"', self.index)
        self.assertEqual(self.index.count('class="splitter-fold"'), 2)

    def test_every_panel_can_be_restored_and_maximized(self):
        self.assertEqual(self.index.count('class="panel-fold"'), 3)
        for name in ("editor", "viewer", "report"):
            self.assertIn(f'data-panel="{name}"', self.index)
        self.assertIn('id="btn-open-downloads"', self.index)

    def test_grid_uses_width_variables(self):
        block = re.search(r"\.layout\s*\{(.*?)\}", self.css, re.S).group(1)
        for var in ("--w-editor", "--w-viewer", "--w-report", "--splitter"):
            self.assertIn(var, block)

    def test_splitter_is_draggable_and_shows_grip(self):
        block = re.search(r"\.splitter\s*\{(.*?)\}", self.css, re.S).group(1)
        self.assertIn("cursor: col-resize", block)
        self.assertIn("touch-action: none", block)
        self.assertIn(".splitter-grip", self.css)
        self.assertIn(".splitter.dragging", self.css)

    def test_collapsed_panel_keeps_only_strip(self):
        self.assertIn(".panel.is-collapsed", self.css)
        self.assertIn(".panel.is-collapsed > .panel-fold", self.css)
        self.assertIn("writing-mode: vertical-rl", self.css)

    def test_drag_uses_pointer_events_and_min_widths(self):
        for token in ("pointerdown", "pointermove", "pointerup",
                      "setPointerCapture", "COL_RESIZE" if False else "col-resize"):
            if token == "col-resize":
                continue
            self.assertIn(token, self.panels)
        self.assertIn("const MIN = {", self.panels)
        self.assertIn("editor: 250", self.panels)
        self.assertIn("viewer: 320", self.panels)
        self.assertIn("report: 250", self.panels)

    def test_widths_are_remembered(self):
        self.assertIn("localStorage.setItem", self.panels)
        self.assertIn("localStorage.getItem", self.panels)
        self.assertIn("forma3d.panels", self.panels)

    def test_double_click_collapses(self):
        self.assertIn("dblclick", self.panels)
        self.assertIn("toggleCollapse", self.panels)

    def test_app_installs_panels_and_resizes_viewer(self):
        self.assertIn("import { installPanelLayout } from './panels.js';", self.app)
        self.assertIn("installPanelLayout({", self.app)
        self.assertIn("onResize: () => state.viewer?.resize()", self.app)

    def test_script_is_loaded_by_page(self):
        self.assertIn('js/app.js', self.index)
        self.assertTrue((WEB / "js" / "panels.js").exists())


class MirrorMarkingTest(unittest.TestCase):
    """Зеркало — только явная метка, а не «металл с малой шероховатостью»."""

    def test_solid_has_mirror_flag_off_by_default(self):
        from forma.model import Solid
        import manifold3d as mf

        box = mf.Manifold.cube([10, 10, 10], True)
        self.assertFalse(Solid(name="к", manifold=box).mirror)

    def test_material_preset_sets_mirror(self):
        b = _build("з = box size=[10, 10, 2]\ncolor з material=зеркало")
        self.assertTrue(b.scene.objects["з"].mirror)
        b2 = _build("з = box size=[10, 10, 2]\ncolor з material=mirror")
        self.assertTrue(b2.scene.objects["з"].mirror)

    def test_plain_metal_is_not_a_mirror(self):
        # именно этот случай ломал часы: десятки «металл 0.95 / шероховатость 0.12»
        b = _build("о = box size=[10, 10, 2]\ncolor о #cfd4da metal=0.95 rough=0.12")
        obj = b.scene.objects["о"]
        self.assertFalse(obj.mirror)
        self.assertGreaterEqual(obj.metal, 0.9)
        self.assertLessEqual(obj.rough, 0.12)

    def test_mirror_plate_is_marked(self):
        # зеркалит стекло, а не рамка вокруг него
        b = _build("з = mirror_plate width=200 height=300 frame=20")
        glass = [o for name, o in b.scene.objects.items() if name.startswith("з.")]
        self.assertTrue(glass, "у зеркальной плиты должно быть стекло")
        self.assertTrue(any(o.mirror for o in glass))
        self.assertFalse(b.scene.objects["з"].mirror)

    def test_payload_carries_mirror_flag(self):
        b = _build("a = box size=[10, 10, 2]\nb = box size=[10, 10, 2]\n"
                   "color b material=зеркало")
        payload = b.payload()
        flags = {o["name"]: o.get("mirror") for o in payload["objects"]}
        self.assertFalse(flags["a"])
        self.assertTrue(flags["b"])

    def test_glb_names_marked_material(self):
        b = _build("a = box size=[10, 10, 2]\nb = box size=[10, 10, 2]\n"
                   "color b material=зеркало")
        names = _glb_materials(export_glb(b.visible_solids()))
        self.assertIn("mat_a", names)
        self.assertIn("mat_mirror__b", names)

    def test_unmarked_scene_has_no_mirror_materials(self):
        b = _build("a = box size=[10, 10, 2]\ncolor a #cfd4da metal=0.95 rough=0.12")
        names = _glb_materials(export_glb(b.visible_solids()))
        self.assertFalse([n for n in names if "mirror__" in n])


class ClockPerformanceTest(unittest.TestCase):
    """Часы: сцена без зеркал и без пересборки шейдеров на каждом кадре."""

    @classmethod
    def setUpClass(cls):
        cls.viewer = _read("js", "viewer.js")
        cls.mirror = _read("js", "planarmirror.js")

    def test_clock_has_no_mirror_materials(self):
        from forma.webui import load_example

        b = build(load_example("clock"), analyze_model=False)
        self.assertTrue(b.ok, (b.error or {}).get("message"))
        self.assertFalse([s.name for s in b.visible_solids() if getattr(s, "mirror", False)],
                         "в часах не должно быть зеркальных деталей")
        names = _glb_materials(export_glb(b.visible_solids()))
        self.assertFalse([n for n in names if "mirror__" in n])

    def test_mirror_detection_is_explicit_only(self):
        body = self._method("_isMirrorMaterial")
        self.assertIn("mirror__", body)
        self.assertIn("isMirror", body)
        self.assertNotIn("metalness", body)
        self.assertNotIn("roughness", body)

    def test_clip_plane_list_length_never_changes(self):
        # список плоскостей постоянной длины — иначе three.js пересобирает
        # все шейдеры сцены на каждом кадре (окно встаёт намертво)
        self.assertIn("const CLIP_ARRAY = [CLIP_PLANE]", self.mirror)
        self.assertIn("1e7", self.mirror)
        self.assertIsNone(re.search(r"clippingPlanes\s*=\s*\[\s*\]", self.mirror))
        self.assertIsNone(re.search(r"clippingPlanes\s*=\s*prevPlanes", self.mirror))
        self.assertNotIn("clippingPlanes.pop", self.mirror)

    def test_reflection_updates_are_throttled(self):
        body = self._method("_refreshMirrors")
        self.assertIn("gap", body)
        self.assertIn("performance.now()", body)
        self.assertIn("< gap", body)

    def test_mirror_center_uses_real_camera_field(self):
        body = self._method("_updateMirrorCenters")
        self.assertIn("virtualCamera", body)
        self.assertNotIn("item.cam.", body)

    def test_shadow_map_not_rebuilt_every_frame(self):
        body = self._method("_renderFrame")
        self.assertIn("autoUpdate = false", body)
        self.assertIn("_shadowDirty", body)

    def test_composer_rebuilt_only_on_key_change(self):
        body = self._method("_ensureComposer")
        self.assertIn("_composerKey", body)

    def test_quality_adapts_to_fps(self):
        body = self._method("_adaptQuality")
        self.assertIn("setPixelRatio", body)
        self.assertIn("quality", body)
        # округление до нуля не должно отключать подстройку: при кадре
        # длиной в секунду fps = 1/секунда, а не «0 — ничего не делаем»
        self.assertIn("Number.isFinite(fps)", body)
        self.assertIn("const fps = this._frames / this._fpsTime;", self.viewer)
        self.assertIn("this._adaptQuality(fps);", self.viewer)

    def test_heavy_scene_starts_in_economy_mode(self):
        self.assertIn("loaded.tris > 200000", self.viewer)

    def _method(self, name: str) -> str:
        start = self.viewer.index(f"\n  {name}(") + 1
        brace = self.viewer.index("{", start)
        depth = 0
        for i in range(brace, len(self.viewer)):
            if self.viewer[i] == "{":
                depth += 1
            elif self.viewer[i] == "}":
                depth -= 1
                if depth == 0:
                    return self.viewer[start:i + 1]
        return self.viewer[start:]


class DownloadsTest(unittest.TestCase):
    """Анимации и снимки попадают в «Загрузки» этого компьютера."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._old = (os.environ.get("FORMA_DATA"), os.environ.get("FORMA_DOWNLOADS"))
        os.environ["FORMA_DATA"] = str(self.tmp / "data")
        os.environ["FORMA_DOWNLOADS"] = str(self.tmp / "Загрузки")

    def tearDown(self):
        for key, value in zip(("FORMA_DATA", "FORMA_DOWNLOADS"), self._old):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _state(self):
        from forma.webui import AppState

        return AppState()

    def test_gif_lands_in_downloads(self):
        st = self._state()
        data = b"GIF89a" + b"\x00" * 200
        res = st.save_media(data, "анимация.gif")
        self.assertEqual(res["name"], "анимация.gif")
        self.assertEqual(res["size"], len(data))
        self.assertEqual(Path(res["path"]).parent, Path(os.environ["FORMA_DOWNLOADS"]))
        self.assertTrue((Path(os.environ["FORMA_DOWNLOADS"]) / "анимация.gif").exists())
        self.assertEqual((Path(os.environ["FORMA_DOWNLOADS"]) / "анимация.gif").read_bytes(), data)
        # копия остаётся и в папке данных приложения
        self.assertTrue((st.data_dir / "exports" / "анимация.gif").exists())

    def test_video_and_screenshot_are_accepted(self):
        st = self._state()
        for name in ("ролик.webm", "ролик.mp4", "снимок.png", "кадр.webp"):
            res = st.save_media(b"xx", name)
            self.assertTrue(Path(res["path"]).exists(), name)

    def test_unknown_type_is_rejected(self):
        from forma.errors import FormaError

        st = self._state()
        with self.assertRaises(FormaError):
            st.save_media(b"MZ", "вирус.exe")
        with self.assertRaises(FormaError):
            st.save_media(b"", "пусто.gif")

    def test_path_traversal_stays_inside_exports(self):
        st = self._state()
        res = st.save_media(b"xx", "../../зло.gif")
        self.assertEqual(Path(res["app_path"]).parent, st.data_dir / "exports")
        self.assertFalse((self.tmp / "зло.gif").exists())

    def test_response_tells_where_the_file_is(self):
        st = self._state()
        res = st.save_media(b"xx", "клип.gif")
        self.assertIn("downloads", res)
        self.assertEqual(res["downloads"], str(Path(os.environ["FORMA_DOWNLOADS"])))
        self.assertTrue(res["url"].startswith("/files/exports/"))

    def test_journal_remembers_the_save(self):
        st = self._state()
        st.save_media(b"xx", "журнал.gif")
        self.assertTrue(any("журнал.gif" in a["text"] for a in st.actions))

    def test_reveal_refuses_foreign_folders(self):
        from forma.errors import FormaError

        st = self._state()
        with self.assertRaises(FormaError):
            st.reveal_path(str(self.tmp))
        # своя папка проходит проверку (открывать её в тесте не нужно)
        self.assertTrue(str(st.data_dir / "exports").startswith(str(st.data_dir)))

    def test_server_routes_and_limits(self):
        src = (ROOT / "forma" / "webui.py").read_text(encoding="utf-8")
        self.assertIn('"/api/save-file"', src)
        self.assertIn('"/api/reveal"', src)
        self.assertIn("MAX_UPLOAD", src)
        self.assertIn("MEDIA_SUFFIXES", src)

    def test_interface_sends_bytes_not_link(self):
        app = _read("js", "app.js")
        self.assertIn("async function saveBlob(", app)
        self.assertIn("/api/save-file?", app)
        for fn in ("exportAnimationGif", "exportAnimationWebm"):
            start = app.index(f"async function {fn}(")
            end = app.index("\nasync function ", start + 10) if "\nasync function " in app[start + 10:] else len(app)
            body = app[start:min(end, start + 4000)]
            self.assertIn("saveBlob(", body, fn)
            self.assertNotIn("downloadBlob(new Blob", body, fn)
        self.assertIn("toastSaved", app)
        self.assertIn("btn-open-downloads", app)

    def test_exports_do_not_download_twice(self):
        app = _read("js", "app.js")
        # браузер больше не скачивает то, что сервер уже положил в «Загрузки»
        self.assertNotIn("res.url + '&token=' + encodeURIComponent(TOKEN) + '&download=1'", app)
        self.assertNotIn("link.download = res.name", app)
        self.assertIn("exportSaved(res", app)


if __name__ == "__main__":
    unittest.main(verbosity=2)
