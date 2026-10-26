"""0.27: превью в карточках, отражения соседей, честное свечение и вид сцены."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from forma.render import _box_blur, _glow_pass, _mirror_ids, _prepare, render_single
from forma.run import build
from forma.webui import AppState, load_example


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError((result.error or {}).get("message", result.error))
    return result


def fails(script: str) -> str:
    result = build(script, analyze_model=False)
    if result.ok:
        raise AssertionError("ожидалась ошибка")
    return (result.error or {}).get("message", "")


def rgb(path: str) -> np.ndarray:
    """PNG читаем своим декодером: Pillow в зависимостях нет."""
    from forma.geometry import read_png
    arr = read_png(path)
    if arr is None:
        raise AssertionError("не удалось прочитать PNG")
    arr = np.asarray(arr, dtype=np.float32)
    if arr.max() > 1.5:
        arr = arr / 255.0
    return arr[..., :3]


class PreviewApi(unittest.TestCase):
    """Превью модели из карточки инструмента: модель без добавления в сцену."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = AppState()
        self.state.data_dir = Path(self.tmp.name)
        self.state.preview_dir = self.state.data_dir / "previews"
        self.script = "ш = sphere radius=20\nк = box size=[24,24,24] at=[38,0,0] color=#e05a3a"

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_builds_small_glb(self):
        res = self.state.preview(self.script)
        self.assertTrue(res.get("ok"), res)
        self.assertGreater(res["tris"], 0)
        self.assertEqual(len(res["size"]), 3)
        self.assertGreater(res["size"][0], 30.0)     # шар + куб рядом
        path = self.state.preview_dir / f"{res['key']}.glb"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes()[:4], b"glTF")

    def test_preview_cached_for_same_script(self):
        first = self.state.preview(self.script)
        second = self.state.preview(self.script)
        self.assertEqual(first["key"], second["key"])
        self.assertTrue(second.get("cached"))

    def test_preview_reports_script_error(self):
        res = self.state.preview("ш = sphere")
        self.assertFalse(res.get("ok"))
        self.assertIn("radius", (res.get("message") or "").lower())

    def test_preview_accepts_only_hex_keys(self):
        self.assertIsNone(self.state.preview_glb("../../etc/passwd"))
        res = self.state.preview(self.script)
        self.assertIsNotNone(self.state.preview_glb(res["key"]))


class GlowFix(unittest.TestCase):
    """Ореол рисуется только там, где источник реально виден."""

    def test_glow_does_not_leak_through_occluder(self):
        img = np.full((80, 80, 3), 0.2, dtype=np.float32)
        mask = np.zeros((80, 80), dtype=bool)
        mask[38:42, 38:42] = True                 # маленький светодиод
        source = np.zeros((80, 80, 3), dtype=np.float32)
        source[mask] = (1.0, 0.15, 0.1)
        out = _glow_pass(img, mask, None, source=source)
        # сквозь «корпус» свечение не проходит: далёкий пиксель не изменился
        self.assertLess(abs(float(out[10, 40, 0]) - 0.2), 0.02)
        self.assertLess(abs(float(out[70, 70, 0]) - 0.2), 0.02)
        # а рядом со светодиодом ореол есть и он красный
        self.assertGreater(float(out[40, 47, 0]), 0.2)
        self.assertGreater(float(out[40, 47, 0]), float(out[40, 47, 1]))

    def test_led_clock_halo_stays_on_screen(self):
        b = ok(load_example("clock_led"))
        with tempfile.TemporaryDirectory() as tmp:
            path = render_single(b.visible_solids(), tmp, filename="led.png",
                                 size=240, ss=1)
            img = rgb(path)
        green = img[..., 1] - img[..., 0]
        # корпус тёмный: зелёных пикселей немного, но они есть — это цифры
        self.assertGreater(float((green > 0.12).mean()), 0.004)
        self.assertLess(float((green > 0.12).mean()), 0.35)

    def test_led_panel_sits_near_glass(self):
        """В готовом проекте экран не прячется на дне глубокой ниши."""
        b = ok(load_example("clock_led"))
        panel = b.scene.resolve("экран").manifold.bounding_box()
        glass = b.scene.resolve("стекло").manifold.bounding_box()
        body = b.scene.resolve("корпус").manifold.bounding_box()
        # экран у передней стенки: до стекла меньше 8 мм
        gap = abs(glass[1] - panel[1])
        self.assertLess(gap, 8.0)
        # и цифры целиком на панели
        digits = b.scene.resolve("цифры").manifold.bounding_box()
        self.assertGreaterEqual(digits[0], panel[0] - 0.01)
        self.assertLessEqual(digits[3], panel[3] + 0.01)
        self.assertGreaterEqual(digits[2], panel[2] - 0.01)
        self.assertLessEqual(digits[5], panel[5] + 0.01)
        self.assertLessEqual(panel[2], body[5])


class MirrorReflections(unittest.TestCase):
    """Зеркало показывает соседей, а не только «студию»."""

    # зеркало кладём плашмя и поднимаем поворотом — так проверяется, что
    # поворот составного объекта двигает и раму, и отражающую пластину
    SCRIPT = ("з = mirror_plate width=300 height=220 frame=20 at=[0,120,0] "
              "plane=плашмя\n"
              "з = rotate [з] angle=90 axis=x pivot=[0,120,110]\n"
              "ш = sphere radius=40 at=[-30,40,40] color=#e03020")

    def test_mirror_material_detected(self):
        b = ok(self.SCRIPT)
        meshes = _prepare(b.visible_solids())
        ids = _mirror_ids(meshes)
        self.assertEqual(len(ids), 1)
        self.assertGreaterEqual(float(meshes[ids[0]]["metal"]), 0.85)
        self.assertLessEqual(float(meshes[ids[0]]["rough"]), 0.12)

    def test_reflection_shows_neighbour_colour(self):
        b = ok(self.SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            # без зеркала в кадре нет красного отражения
            solid_plain = [s for s in b.visible_solids() if s.name != "з.зеркало"]
            p1 = render_single(solid_plain, tmp, filename="no_mirror.png", size=220, ss=1)
            p2 = render_single(b.visible_solids(), tmp, filename="mirror.png", size=220, ss=1)
            without = rgb(p1)
            with_mirror = rgb(p2)
        red_without = float(((without[..., 0] - without[..., 1]) > 0.1).mean())
        red_with = float(((with_mirror[..., 0] - with_mirror[..., 1]) > 0.1).mean())
        # в зеркале появилось красное отражение шара
        self.assertGreater(red_with, red_without + 0.001)

    def test_rotate_moves_composite_parts(self):
        """Поворот зеркала двигает и отражающую пластину, а не только раму."""
        b = ok(self.SCRIPT)
        frame = b.scene.resolve("з").manifold.bounding_box()
        plate = b.scene.resolve("з.зеркало").manifold.bounding_box()
        # пластина внутри рамы по X и по высоте
        self.assertGreaterEqual(plate[0], frame[0] - 0.01)
        self.assertLessEqual(plate[3], frame[3] + 0.01)
        self.assertLess(plate[5] - plate[2], frame[5] - frame[2] + 0.01)
        # рама стоит вертикально: высота больше толщины
        self.assertGreater(frame[5] - frame[2], frame[4] - frame[1])


class SceneViewSettings(unittest.TestCase):
    """Ползунки вида сохраняются в сценарии и не сбрасываются."""

    def test_scene_op_saves_axes_poly_bloom(self):
        b = ok("к = box size=[20,20,20]\n"
               "scene bg=#101010 exposure=1.3 shadows=нет grid=да ground=нет "
               "axes=нет poly=да bloom=1.2")
        s = b.scene.settings
        self.assertFalse(s["axes"])
        self.assertTrue(s["poly"])
        self.assertFalse(s["shadows"])
        self.assertEqual(s["exposure"], 1.3)
        self.assertAlmostEqual(s["bloom"], 1.2, places=6)
        # настройки попадают в ответ интерфейсу — ползунки берут их оттуда
        payload = b.payload()
        self.assertFalse(payload["settings"]["axes"])
        self.assertTrue(payload["settings"]["poly"])

    def test_bloom_is_limited(self):
        b = ok("к = box size=[20,20,20]\nscene bloom=9")
        self.assertEqual(b.scene.settings["bloom"], 3.0)
        b2 = ok("к = box size=[20,20,20]\nscene bloom=-2")
        self.assertEqual(b2.scene.settings["bloom"], 0.0)

    def test_scene_op_unknown_env_still_fails(self):
        message = fails("к = box size=[20,20,20]\nscene env=марс")
        self.assertIn("марс", message.lower())


class ClearButtons(unittest.TestCase):
    """Уборка сцены: объекты и их строки, настройки вида остаются."""

    def test_object_lines_are_known(self):
        b = ok("к = box size=[20,20,20]\nш = sphere radius=10 at=[30,0,0]\n"
               "scene bg=#101010\nexposure = 1")
        payload = b.payload()
        lines = {o["line"] for o in payload["objects"]}
        self.assertIn(1, lines)
        self.assertIn(2, lines)
        self.assertNotIn(3, lines)


class BoxBlurSanity(unittest.TestCase):
    def test_box_blur_keeps_energy(self):
        arr = np.zeros((16, 16), dtype=np.float32)
        arr[8, 8] = 1.0
        out = _box_blur(arr, 2)
        self.assertAlmostEqual(float(out.sum()), 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
