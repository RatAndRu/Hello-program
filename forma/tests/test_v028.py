"""0.28: корона, инь-ян, линза, патрон и развитие аниме-подачи.

Проверяем то, что видно пользователю: формы строятся и остаются цельными
телами, параметры действительно меняют результат, длина патрона равна
заданной, а штриховка, зерно бумаги и линии по группам/материалам реально
влияют на кадр.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from forma.anime import PRESETS, normalize_style
from forma.render import render_single, _prepare
from forma.run import build
from forma.webui import AppState


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


def size_of(result, name: str) -> list[float]:
    bb = result.scene.objects[name].manifold.bounding_box()
    return [float(bb[3] - bb[0]), float(bb[4] - bb[1]), float(bb[5] - bb[2])]


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


def luma(img: np.ndarray) -> np.ndarray:
    return img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114


class Crown(unittest.TestCase):
    def test_crown_is_one_closed_ring(self):
        b = ok("к = crown diameter=150 height=48 wall=4 teeth=12 tooth=30")
        m = b.scene.objects["к"].manifold
        self.assertEqual(str(m.status()), "Error.NoError")
        # кольцо — тело с одним сквозным отверстием: род 1, а не набор зубьев
        self.assertEqual(m.genus(), 1)
        self.assertGreater(m.volume(), 100.0)

    def test_crown_teeth_and_tip_change_shape(self):
        sharp = ok("к = crown diameter=150 height=48 teeth=12 tooth=30 tip=0")
        round_ = ok("к = crown diameter=150 height=48 teeth=12 tooth=30 tip=1")
        z_sharp = float(sharp.scene.objects["к"].manifold.bounding_box()[5])
        z_round = float(round_.scene.objects["к"].manifold.bounding_box()[5])
        # скруглённое остриё чуть ниже: та же высота зуба, но вершина мягче
        self.assertLessEqual(z_round, z_sharp + 1e-6)
        self.assertGreater(z_round, 48.0)

    def test_more_teeth_give_more_triangles(self):
        few = ok("к = crown diameter=150 height=48 teeth=8 tooth=30 detail=8")
        many = ok("к = crown diameter=150 height=48 teeth=16 tooth=30 detail=8")
        self.assertGreater(many.scene.objects["к"].manifold.num_tri(),
                           few.scene.objects["к"].manifold.num_tri())

    def test_crown_size_follows_parameters(self):
        b = ok("к = crown diameter=150 height=48 tooth=0")
        w, d, h = size_of(b, "к")
        self.assertAlmostEqual(w, 150.0, places=1)
        self.assertAlmostEqual(d, 150.0, places=1)
        self.assertAlmostEqual(h, 48.0, places=1)

    def test_crown_wall_must_fit(self):
        self.assertIn("стенка", fails("к = crown diameter=20 wall=12").lower())

    def test_unknown_tooth_shape_is_explained(self):
        message = fails("к = crown shape=пила")
        self.assertIn("пила", message.lower())


class YinYang(unittest.TestCase):
    def test_form_is_half_of_the_sign(self):
        left = ok("и = yin_yang diameter=120 thick=16")
        w, d, h = size_of(left, "и")
        # С 0.41 знак стоит в XZ: толщина по Y, диаметр по Z.
        self.assertAlmostEqual(h, 120.0, places=1)
        # «запятая» — половина круга: по Z весь диаметр, по X радиус плюс
        # малый полукруг (R + R/2 = 0.75 диаметра)
        self.assertAlmostEqual(w, 90.0, places=1)
        self.assertAlmostEqual(d, 16.0, places=1)

    def test_right_half_is_mirror(self):
        left = ok("и = yin_yang diameter=100 thick=10")
        right = ok("и = yin_yang diameter=100 thick=10 side=правый")
        bl = left.scene.objects["и"].manifold.bounding_box()
        br = right.scene.objects["и"].manifold.bounding_box()
        self.assertAlmostEqual(float(bl[0]), -float(br[3]), places=6)
        self.assertAlmostEqual(float(bl[3]), -float(br[0]), places=6)

    def test_left_and_right_add_up_to_full_disc(self):
        b = ok("и = yin_yang diameter=100 thick=10\n"
               "я = yin_yang diameter=100 thick=10 side=правый")
        m = b.scene.objects["и"].manifold + b.scene.objects["я"].manifold
        self.assertEqual(str(m.status()), "Error.NoError")
        bb = m.bounding_box()
        self.assertAlmostEqual(float(bb[3] - bb[0]), 100.0, places=1)
        self.assertAlmostEqual(float(bb[4] - bb[1]), 10.0, places=1)
        self.assertAlmostEqual(float(bb[5] - bb[2]), 100.0, places=1)

    def test_bad_side_is_reported(self):
        self.assertIn("сторона", fails("и = yin_yang side=середина").lower())


class Lens(unittest.TestCase):
    def test_convex_is_thicker_in_the_middle(self):
        convex = ok("л = lens diameter=70 sag=12 edge=40 mode=выпуклая")
        concave = ok("л = lens diameter=70 sag=12 edge=40 mode=вогнутая")
        # при одинаковом крае выпуклая набирает тело к центру, вогнутая — теряет
        self.assertGreater(convex.scene.objects["л"].manifold.volume(),
                           concave.scene.objects["л"].manifold.volume())
        self.assertGreater(size_of(convex, "л")[2], size_of(concave, "л")[2])
        self.assertAlmostEqual(size_of(convex, "л")[0], 70.0, places=1)

    def test_concave_gets_sane_default_edge(self):
        b = ok("л = lens diameter=70 sag=12 mode=вогнутая")
        self.assertGreater(size_of(b, "л")[2], 10.0)

    def test_sag_changes_thickness(self):
        thin = ok("л = lens diameter=60 sag=4 mode=выпуклая")
        thick = ok("л = lens diameter=60 sag=16 mode=выпуклая")
        self.assertGreater(size_of(thick, "л")[2], size_of(thin, "л")[2] + 5.0)

    def test_all_modes_build(self):
        for mode in ("выпуклая", "вогнутая", "плосковыпуклая", "плосковогнутая", "мениск"):
            b = ok(f"л = lens diameter=50 sag=10 edge=30 mode={mode}")
            self.assertGreater(size_of(b, "л")[2], 0.5, mode)

    def test_unknown_mode_is_explained(self):
        self.assertIn("линз", fails("л = lens mode=взгляд").lower())


class HalfCapsule(unittest.TestCase):
    def test_length_is_exact(self):
        for diameter, length in ((7.62, 56), (9, 29), (12.7, 99)):
            b = ok(f"п = полукапсула diameter={diameter} length={length} rim=0")
            self.assertAlmostEqual(size_of(b, "п")[2], float(length), places=2)

    def test_rim_widens_base_not_modes(self):
        plain = ok("п = полукапсула diameter=20 length=50 rim=0")
        rim = ok("п = полукапсула diameter=20 length=50 rim=2 rim_height=3")
        self.assertAlmostEqual(size_of(plain, "п")[0], 20.0, delta=0.1)
        self.assertAlmostEqual(size_of(rim, "п")[0], 24.0, delta=0.1)

    def test_cartridge_is_only_an_alias(self):
        b = ok("п = cartridge diameter=9 length=29 rim=0")
        m = b.scene.objects["п"].manifold
        self.assertEqual(str(m.status()), "Error.NoError")
        self.assertEqual(m.genus(), 0)

    def test_old_kind_is_rejected(self):
        message = fails("п = cartridge kind=артиллерийский").lower()
        self.assertIn("kind", message)
        self.assertIn("полукапсула", message)


class NewShapesInCatalog(unittest.TestCase):
    """Новые примитивы доступны и через превью из карточки инструмента."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = AppState()
        self.state.data_dir = Path(self.tmp.name)
        self.state.preview_dir = self.state.data_dir / "previews"

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_builds_each_new_shape(self):
        scripts = {
            "crown": "к = crown diameter=120 height=40 teeth=10",
            "yin": "и = yin_yang diameter=100 thick=12",
            "lens": "л = lens diameter=60 sag=10",
            "cartridge": "п = cartridge diameter=9 length=29",
        }
        for name, script in scripts.items():
            res = self.state.preview(script)
            self.assertTrue(res.get("ok"), (name, res))
            self.assertGreater(res["tris"], 0, name)
            self.assertTrue((self.state.preview_dir / f"{res['key']}.glb").exists(), name)


class AnimeHatch(unittest.TestCase):
    """Штриховка и бумага: то, что видно глазом."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = ok("шар = sphere radius=40 color=#dfe6f3\n"
                    "куб = box size=[40,40,40] at=[54,0,0] color=#f0c674")

    def tearDown(self):
        self.tmp.cleanup()

    def _render(self, name: str, style: dict) -> np.ndarray:
        path = render_single(self.b.visible_solids(), self.tmp.name,
                             filename=f"{name}.png", size=300, ss=1,
                             view="iso", style=normalize_style(style))
        return rgb(path)

    def test_hatch_darkens_shadows(self):
        plain = self._render("plain", {"mode": "аниме"})
        hatch = self._render("hatch", {"mode": "аниме", "hatch": 0.9,
                                       "hatch_angle": 48, "hatch_step": 6})
        body = luma(plain) < 0.9
        self.assertLess(float(luma(hatch)[body].mean()),
                        float(luma(plain)[body].mean()) - 0.01)
        # разница есть именно «полосами», а не сплошным затемнением
        diff = np.abs(luma(hatch) - luma(plain))
        self.assertGreater(float(diff[body].max()), 0.05)

    def test_hatch_angle_changes_pattern(self):
        a = self._render("a", {"mode": "аниме", "hatch": 0.9, "hatch_angle": 20})
        b = self._render("b", {"mode": "аниме", "hatch": 0.9, "hatch_angle": 110})
        self.assertGreater(float(np.abs(luma(a) - luma(b)).mean()), 1e-3)

    def test_paper_grain_is_visible_and_can_be_off(self):
        flat = self._render("flat", {"mode": "манга", "paper": "#f4f6fa", "paper_tex": 0})
        grain = self._render("grain", {"mode": "манга", "paper": "#f4f6fa", "paper_tex": 0.8})
        # угол кадра — чистая бумага: с зерном по ней идёт мелкий шум,
        # без зерна фон ровный
        corner_flat = luma(flat[:20, :20])
        corner_grain = luma(grain[:20, :20])
        self.assertGreater(float(corner_grain.std()), float(corner_flat.std()) * 1.4)
        diff = np.abs(corner_grain - corner_flat)
        self.assertGreater(float((diff > 2.0 / 255.0).mean()), 0.3)

    def test_sketch_mode_keeps_colour_but_quiets_it(self):
        anime = self._render("anime", {"mode": "аниме"})
        sketch = self._render("sketch", {"mode": "скетч", "hatch": 0.8, "paper_tex": 0.5})
        body = luma(anime) < 0.9
        sat_anime = float(np.abs(anime[..., 0] - anime[..., 2])[body].mean())
        sat_sketch = float(np.abs(sketch[..., 0] - sketch[..., 2])[body].mean())
        self.assertLess(sat_sketch, sat_anime)


class AnimeLines(unittest.TestCase):
    """Линии по группам и материалам: шов только там, где кончается «своё»."""

    def _frame(self, right_id: int, right_mat: int, left_id: int = 1,
               left_mat: int = 1):
        h, w = 48, 48
        img = np.full((h, w, 3), 0.62, dtype=np.float32)
        z = np.full((h, w), 100.0, dtype=np.float32)
        nrm = np.zeros((h, w, 3), dtype=np.float32)
        nrm[..., 2] = 1.0
        ids = np.full((h, w), left_id, dtype=np.int32)
        ids[:, w // 2:] = right_id
        groups = np.full((h, w), 1, dtype=np.int32)
        mats = np.full((h, w), left_mat, dtype=np.int32)
        mats[:, w // 2:] = right_mat
        return img, z, nrm, ids, groups, mats

    def _edges(self, style: dict, groups, mats, ids) -> int:
        from forma.anime import apply_style
        img, z, nrm, _, _, _ = self._frame(0, 0)
        out = apply_style(img, z, nrm, ids, style=style, groups=groups, mats=mats)
        # линия — тёмные пиксели на светлом теле
        return int((out.mean(axis=2) < 0.42).sum())

    def test_all_parts_draw_the_seam(self):
        img, z, nrm, ids, groups, mats = self._frame(2, 1, left_mat=1)
        n = self._edges({"mode": "линия", "seams": True}, groups, mats, ids)
        self.assertGreater(n, 10)

    def test_same_group_has_no_seam(self):
        img, z, nrm, ids, groups, mats = self._frame(2, 1, left_mat=1)
        n_all = self._edges({"mode": "линия", "seams": True}, groups, mats, ids)
        n_grp = self._edges({"mode": "линия", "seams": True, "lines": "группы"},
                            groups, mats, ids)
        self.assertLess(n_grp, n_all)

    def test_material_border_is_drawn_only_in_material_mode(self):
        img, z, nrm, ids, groups, mats = self._frame(1, 2, left_mat=1)
        # детали в одной группе: в режиме «группы» шва нет, «материалы» — есть
        n_grp = self._edges({"mode": "линия", "seams": True, "lines": "группы"},
                            groups, mats, ids)
        n_mat = self._edges({"mode": "линия", "seams": True, "lines": "материалы"},
                            groups, mats, ids)
        self.assertGreater(n_mat, n_grp)

    def test_unknown_lines_mode_is_explained(self):
        self.assertIn("линий", _style_error({"mode": "аниме", "lines": "мусор"}).lower())
        self.assertIn("линий", fails("anime mode=аниме lines=мусор").lower())


def _style_error(style: dict) -> str:
    try:
        normalize_style(style)
    except Exception as exc:                 # noqa: BLE001 — проверяем текст
        return str(exc)
    raise AssertionError("ожидалась ошибка")


class AnimeStyleParams(unittest.TestCase):
    def test_preset_sketch_has_hatch_and_paper(self):
        st = normalize_style({"mode": "скетч"})
        self.assertGreater(st["hatch"], 0.5)
        self.assertGreater(st["paper_tex"], 0.3)

    def test_hatch_is_checked(self):
        self.assertIn("штрих", _style_error({"mode": "аниме", "hatch": 5}).lower())

    def test_background_texture_is_checked(self):
        self.assertIn("бумаг", _style_error({"mode": "аниме", "paper_tex": -1}).lower())


class RenderGroups(unittest.TestCase):
    """Снимки получают группы сцены: без них режим «по группам» не работает."""

    def test_render_single_accepts_groups(self):
        b = ok("а = box size=[40,40,10]\nб = cylinder radius=8 height=10 at=[30,0,5]\n"
               "сборка = group [а, б]")
        with tempfile.TemporaryDirectory() as tmp:
            path = render_single(b.visible_solids(), tmp, filename="g.png", size=200,
                                 ss=1, view="iso",
                                 style=normalize_style({"mode": "линия", "lines": "группы"}),
                                 groups=b.scene.groups)
            self.assertTrue(Path(path).exists())

    def test_prepare_marks_groups_and_materials(self):
        b = ok("а = box size=[20,20,20] color=#ff0000\n"
               "б = box size=[20,20,20] at=[30,0,0] color=#ff0000\n"
               "в = box size=[20,20,20] at=[60,0,0] color=#00ff00\n"
               "сборка = group [а, б]")
        meshes = _prepare(b.visible_solids(), b.scene.groups)
        by_id = {}
        for m in meshes:
            key = tuple(round(float(c), 2) for c in m["color"])
            by_id.setdefault(key, []).append((m["gid"], m["mid"]))
        red = by_id[(1.0, 0.0, 0.0)]
        green = by_id[(0.0, 1.0, 0.0)]
        self.assertEqual(len({gid for gid, _ in red}), 1)       # обе красные в группе
        self.assertEqual(len({mid for _, mid in red}), 1)       # один материал
        self.assertNotEqual(red[0][1], green[0][1])             # материалы разные


if __name__ == "__main__":
    unittest.main()
