"""0.73: габарит как инвариант, отказ от распада, полость и смещения.

Проверяется то, что раньше проходило молча: выпуклый рельеф `face_box`
менял габарит, вогнутый — распадался на части или оставлял закрытые полости,
а лучшие параметры четырёх примитивов были недоступны из интерфейса.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import manifold3d as mf

from forma.geometry import solid_parts
from forma.ops import OPS
from forma.run import build

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "web" / "js" / "app.js"


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"{result.error}\n{script}")
    return result


def solid_of(script: str):
    return ok(script).scene.all_solids()[-1]


def bbox(solid) -> tuple[float, float, float]:
    box = solid.manifold.bounding_box()
    return (box[3] - box[0], box[4] - box[1], box[5] - box[2])


def contains(solid, point) -> bool:
    probe = mf.Manifold.cube((0.4, 0.4, 0.4), True).translate(tuple(point))
    return not (solid.manifold ^ probe).is_empty()


class FaceBoxGauge073Test(unittest.TestCase):
    """Габарит готовой детали всегда равен size."""

    def test_convex_all_faces_keeps_size(self):
        for relief in (3, 7, 12, 20):
            with self.subTest(relief=relief):
                solid = solid_of(
                    f"к = face_box size=[80,80,80] mode=выпуклый profile=линза "
                    f"faces=все relief={relief} margin=8")
                for value in bbox(solid):
                    self.assertAlmostEqual(value, 80.0, places=2)
                self.assertEqual(solid_parts(solid.manifold), 1)

    def test_convex_single_face_keeps_size_in_all_axes(self):
        solid = solid_of("к = face_box size=[80,80,80] mode=выпуклый "
                         "profile=квадрат faces=верх relief=10 margin=8")
        for value in bbox(solid):
            self.assertAlmostEqual(value, 80.0, places=2)

    def test_convex_two_faces_keep_their_sides(self):
        solid = solid_of("к = face_box size=[60,50,40] mode=выпуклый profile=трапеция "
                         "faces=верх,перёд relief=6 margin=5")
        for measured, expected in zip(bbox(solid), (60.0, 50.0, 40.0)):
            self.assertAlmostEqual(measured, expected, places=2)

    def test_concave_keeps_size(self):
        solid = solid_of("к = face_box size=[80,80,80] mode=вогнутый profile=линза "
                         "faces=верх relief=8 margin=5")
        for value in bbox(solid):
            self.assertAlmostEqual(value, 80.0, places=2)

    def test_convex_relief_bigger_than_half_is_reported(self):
        result = build("к = face_box size=[40,40,40] mode=выпуклый relief=25",
                       analyze_model=False)
        self.assertFalse(result.ok)
        self.assertIn("не оставляет ядра", result.error["message"])

    def test_offset_moves_recess_off_centre(self):
        plain = solid_of("к = face_box size=[80,80,20] mode=вогнутый profile=квадрат "
                         "faces=верх relief=6 margin=6")
        shifted = solid_of("к = face_box size=[80,80,20] mode=вогнутый profile=квадрат "
                           "faces=верх relief=6 margin=6 offset=[25,25]")
        # Без смещения угловая точка грани цела, со смещением — попадает в лунку.
        self.assertTrue(contains(plain, (36, 36, 18)))
        self.assertFalse(contains(plain, (0, 0, 18)))
        self.assertFalse(contains(shifted, (36, 36, 18)))
        self.assertTrue(contains(shifted, (-30, -30, 18)))
        # Смещённая лунка выходит за край грани, поэтому снимает меньше материала.
        self.assertGreater(shifted.manifold.volume(), plain.manifold.volume())


class FaceBoxStructure073Test(unittest.TestCase):
    """Распад и закрытые полости останавливают сборку с понятным текстом."""

    def test_split_is_reported_with_safe_depth(self):
        result = build("к = face_box size=[80,80,80] mode=вогнутый profile=квадрат "
                       "faces=все relief=12 margin=10", analyze_model=False)
        self.assertFalse(result.ok)
        message = result.error["message"]
        self.assertIn("распадается на 2 части", message)
        hint = result.error["hint"]
        self.assertIn("relief не больше 10", hint)

    def test_closed_cavities_are_reported(self):
        result = build("к = face_box size=[80,80,80] mode=вогнутый profile=линза "
                       "faces=все relief=30 margin=10", analyze_model=False)
        self.assertFalse(result.ok)
        self.assertIn("закрытых полостей", result.error["message"])

    def test_deep_single_face_stays_whole(self):
        solid = solid_of("к = face_box size=[80,80,80] mode=вогнутый profile=квадрат "
                         "faces=верх relief=30 margin=10")
        self.assertEqual(solid_parts(solid.manifold), 1)
        self.assertEqual(int(solid.manifold.genus()), 0)

    def test_safe_depth_really_builds(self):
        solid = solid_of("к = face_box size=[80,80,80] mode=вогнутый profile=квадрат "
                         "faces=все relief=10 margin=10")
        self.assertEqual(solid_parts(solid.manifold), 1)


class CubeHole073Test(unittest.TestCase):
    """Смещение от центра и глухие отверстия."""

    def test_offset_moves_hole_off_centre(self):
        solid = solid_of("к = cube_hole size=[60,60,12] hole_z=8 offset=[20,20]")
        self.assertEqual(solid_parts(solid.manifold), 1)
        self.assertFalse(contains(solid, (20, 20, 0)) or contains(solid, (20, 20, 4)))
        self.assertTrue(contains(solid, (0, 0, 0)))

    def test_blind_hole_has_no_through_genus(self):
        through = solid_of("к = cube_hole size=[40,40,30] hole=14")
        blind = solid_of("к = cube_hole size=[40,40,30] hole=14 depth=12")
        self.assertEqual(int(through.manifold.genus()), 1)
        self.assertEqual(int(blind.manifold.genus()), 0)
        self.assertGreater(blind.manifold.volume(), through.manifold.volume())
        self.assertAlmostEqual(blind.manifold.volume(), 40 * 40 * 30 - 3.14159 * 49 * 12,
                               delta=400)

    def test_offset_outside_block_is_reported(self):
        result = build("к = cube_hole size=[40,40,40] hole=30 offset=[10,0]",
                       analyze_model=False)
        self.assertFalse(result.ok)
        self.assertIn("выходит за брусок", result.error["message"])

    def test_axes_are_independent_in_ui_and_dsl(self):
        solid = solid_of("к = cube_hole size=[50,50,50] hole_x=10 hole_y_shape=квадрат "
                         "hole_y=12 hole_z=8")
        self.assertEqual(solid_parts(solid.manifold), 1)
        # Три взаимно перпендикулярных канала дают род не меньше трёх.
        self.assertGreaterEqual(int(solid.manifold.genus()), 3)


class BoxCavity073Test(unittest.TestCase):
    """Полость со стенкой в любом блоке."""

    def test_plain_box_becomes_case(self):
        solid = solid_of("ящик = box size=[120,80,60] wall=4")
        self.assertEqual(solid_parts(solid.manifold), 1)
        for measured, expected in zip(bbox(solid), (120.0, 80.0, 60.0)):
            self.assertAlmostEqual(measured, expected, places=2)
        self.assertTrue(contains(solid, (0, 0, 2)))
        self.assertFalse(contains(solid, (0, 0, 40)))
        self.assertAlmostEqual(solid.manifold.volume(), 120 * 80 * 60 - 112 * 72 * 56,
                               delta=2000)

    def test_bottom_cavity_opens_down(self):
        solid = solid_of("стакан = box size=[60,60,80] wall=3 cavity=низ")
        self.assertFalse(contains(solid, (0, 0, 5)))
        self.assertTrue(contains(solid, (0, 0, 78)))

    def test_cavity_follows_taper(self):
        solid = solid_of("клин = box size=[100,70,40] top_size=[80,50] wall=4")
        for measured, expected in zip(bbox(solid), (100.0, 70.0, 40.0)):
            self.assertAlmostEqual(measured, expected, places=2)
        self.assertFalse(contains(solid, (0, 0, 30)))

    def test_cavity_depth_is_respected(self):
        solid = solid_of("лоток = box size=[100,100,60] wall=4 cavity_depth=20")
        self.assertTrue(contains(solid, (0, 0, 30)))
        self.assertFalse(contains(solid, (0, 0, 50)))

    def test_too_deep_cavity_is_reported(self):
        result = build("к = box size=[100,100,60] wall=4 cavity_depth=59",
                       analyze_model=False)
        self.assertFalse(result.ok)
        self.assertIn("не оставляет дна", result.error["message"])


class Naming073Test(unittest.TestCase):
    """Местные синонимы переводятся в канонические имена."""

    def test_face_box_synonyms(self):
        ok("к = face_box size=[60,60,60] направление=выпуклый форма_рельефа=линза "
           "выступ=5 поле_до_края=8")
        ok("к = face_box size=[60,60,60] mode=вогнутый глубина=5 faces=верх")

    def test_cube_hole_synonyms(self):
        ok("к = cube_hole size=[40,40,40] отверстие=12 глубина=10")

    def test_box_and_box_body_synonyms(self):
        ok("к = box size=[80,80,60] стенка=4 полость=верх")
        ok("к = box_body size=[200,150,80] припуск=0.5 скругление_в_плане=8")

    def test_global_size_synonym(self):
        ok("к = box габарит=[40,40,40]")


class UiParity073Test(unittest.TestCase):
    """Каждый параметр этих команд доступен из карточки."""

    OPS_UNDER_TEST = ("box", "face_box", "cube_hole", "box_body")
    POSITIONAL_ONLY = {"at", "center"}

    def card_keys(self, op: str) -> set[str]:
        source = APP_JS.read_text(encoding="utf-8")
        start = source.index(f"op: '{op}'")
        end = source.index("\n  },", start)
        block = source[start:end]
        keys = set(re.findall(r"k: '([^']+)'", block))
        if "detailParam(" in block:
            keys.add("detail")
        return keys

    def test_every_dsl_param_is_in_card(self):
        for op in self.OPS_UNDER_TEST:
            with self.subTest(op=op):
                missing = set(OPS[op].params) - self.card_keys(op) - self.POSITIONAL_ONLY
                self.assertFalse(missing, f"{op}: нет в карточке {sorted(missing)}")

    def test_card_has_no_unknown_params(self):
        for op in self.OPS_UNDER_TEST:
            with self.subTest(op=op):
                extra = self.card_keys(op) - set(OPS[op].params)
                self.assertFalse(extra, f"{op}: карточка знает лишнее {sorted(extra)}")


class Docs073Test(unittest.TestCase):
    """Стандарт имён и атлас понятий существуют и связаны из справки."""

    def test_naming_and_atlas_exist(self):
        naming = ROOT / "docs" / "NAMING.md"
        atlas = ROOT / "docs" / "ATLAS.md"
        self.assertTrue(naming.is_file())
        self.assertTrue(atlas.is_file())
        self.assertIn("NAMING.md", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("ATLAS.md", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
