"""0.30: плоскость-лист, рулон, волнистость, оригами-сгиб и гофрирование.

Главная мысль проверок: лист — это **тело**, а не висячий полигон (объём
замкнут и равен длине × ширине × толщине), а сгиб и гофра не рвут и не
протыкают поверхность: объём сохраняется, тело остаётся одним куском.
"""

from __future__ import annotations

import math
import unittest
from pathlib import Path

import numpy as np

from forma.geometry import manifold_mesh
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]


def _obj(script: str):
    b = build(script, analyze_model=False)
    assert b.ok, (b.error or {}).get("message")
    name = next(iter(b.scene.objects))
    solid = b.scene.objects[name]
    return solid.manifold, b


def _size(m):
    bb = m.bounding_box()
    return (bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])


class SheetPrimitiveTest(unittest.TestCase):
    """Плоскость — тонкий параллелепипед с настоящим объёмом."""

    def test_registered_as_primitive(self):
        import forma.run  # noqa: F401
        from forma.ops import OPS

        spec = OPS["sheet"]
        self.assertEqual(spec.category, "Примитивы")
        self.assertTrue(spec.summary and spec.example and spec.params)
        for alias in ("плоскость", "лист", "plane", "panel"):
            self.assertIn(alias, spec.aliases + (spec.name,))
        for key in ("width", "length", "thickness", "step", "amp", "wave",
                    "roll", "gap", "segments"):
            self.assertIn(key, spec.params)

    def test_flat_sheet_is_a_solid_box(self):
        m, _ = _obj("л = sheet width=120 length=200 thickness=1.2")
        w, d, h = _size(m)
        self.assertAlmostEqual(w, 200.0, delta=0.01)
        self.assertAlmostEqual(d, 120.0, delta=0.01)
        self.assertAlmostEqual(h, 1.2, delta=0.01)
        # ровно объём параллелепипеда: открытых полигонов нет
        self.assertAlmostEqual(m.volume(), 200 * 120 * 1.2, delta=1.0)
        self.assertEqual(m.genus(), 0)

    def test_thickness_is_kept(self):
        for t in (0.3, 2.0, 12.0):
            m, _ = _obj(f"л = sheet width=80 length=90 thickness={t}")
            self.assertAlmostEqual(_size(m)[2], t, delta=0.01)
            self.assertAlmostEqual(m.volume(), 80 * 90 * t, delta=max(1.0, t))

    def test_waves_height_and_step(self):
        m, _ = _obj("л = sheet width=100 length=200 thickness=1 step=25 amp=6")
        w, d, h = _size(m)
        self.assertAlmostEqual(h, 2 * 6 + 1, delta=0.35)
        self.assertAlmostEqual(w, 200.0, delta=1.5)
        # амплитуда действительно задаёт высоту волны
        m2, _ = _obj("л = sheet width=100 length=200 thickness=1 step=25 amp=2")
        self.assertLess(_size(m2)[2], _size(m)[2] - 5)
        # шаг волны — число бугров по длине
        self.assertGreater(m.num_tri(), 2000)

    def test_wave_directions(self):
        along, _ = _obj("л = sheet width=100 length=200 thickness=1 step=25 amp=5 wave=вдоль")
        across, _ = _obj("л = sheet width=100 length=200 thickness=1 step=25 amp=5 wave=поперёк")
        cross, _ = _obj("л = sheet width=200 length=200 thickness=1 step=25 amp=5 wave=крест")
        self.assertAlmostEqual(_size(along)[1], 100.0, delta=0.3)   # по ширине ровно
        self.assertGreater(_size(across)[1], 100.5)                  # ширина в волне
        self.assertGreater(_size(cross)[2], 9.0)                     # клетка выше
        for m in (along, across, cross):
            self.assertEqual(m.genus(), 0)
            self.assertGreater(m.volume(), 0)

    def test_roll_is_a_spiral(self):
        m, _ = _obj("л = sheet width=120 length=600 thickness=0.6 roll=6 gap=1.4")
        w, d, h = _size(m)
        self.assertAlmostEqual(d, 120.0, delta=0.5)      # ширина листа = длина рулона
        self.assertGreater(w, 20.0)
        self.assertAlmostEqual(w, h, delta=2.0)          # рулон круглый
        self.assertLess(w, 80.0)
        self.assertEqual(m.genus(), 0)
        # лист не сжат: объём близок к length × width × thickness
        self.assertAlmostEqual(m.volume(), 600 * 120 * 0.6, delta=600 * 120 * 0.6 * 0.05)

    def test_roll_gap_controls_layers(self):
        tight, _ = _obj("л = sheet width=100 length=400 thickness=0.6 roll=5 gap=0.7")
        loose, _ = _obj("л = sheet width=100 length=400 thickness=0.6 roll=5 gap=3")
        self.assertLess(_size(tight)[0], _size(loose)[0])

    def test_roll_refuses_impossible(self):
        b = build("л = sheet width=100 length=200 thickness=1 roll=5 gap=0.5")
        self.assertFalse(b.ok)
        self.assertIn("зазор", (b.error or {}).get("message", "").lower()
                      + (b.error or {}).get("hint", "").lower())

    def test_roll_with_waves_is_explained(self):
        b = build("л = sheet width=100 length=300 thickness=1 step=20 amp=3 roll=3")
        self.assertFalse(b.ok)
        self.assertIn("волнистость", (b.error or {}).get("hint", "") + (b.error or {}).get("message", ""))

    def test_roll_too_short_is_explained(self):
        b = build("л = sheet width=100 length=80 thickness=0.5 roll=8 gap=1")
        self.assertFalse(b.ok)
        err = b.error or {}
        self.assertIn("roll", err.get("hint", "") + err.get("message", ""))

    def test_wave_too_big_is_explained(self):
        b = build("л = sheet width=100 length=40 thickness=1 step=10 amp=30")
        self.assertFalse(b.ok)
        self.assertTrue((b.error or {}).get("message"))


class FoldTest(unittest.TestCase):
    """Сгиб как оригами: слои ложатся рядом, поверхность не рвётся."""

    def test_half_fold_halves_the_length(self):
        m, _ = _obj("л = sheet width=100 length=200 thickness=1\n"
                    "fold л parts=2 angle=180 gap=1")
        w, d, h = _size(m)
        self.assertAlmostEqual(d, 100.0, delta=0.5)
        self.assertLess(w, 105.0)
        self.assertAlmostEqual(h, 3.0, delta=0.2)     # два слоя и просвет
        self.assertEqual(m.genus(), 0)

    def test_fold_keeps_volume(self):
        m, _ = _obj("л = sheet width=100 length=200 thickness=1\n"
                    "fold л parts=2 angle=180 gap=1")
        self.assertAlmostEqual(m.volume(), 20000.0, delta=200.0)

    def test_gap_separates_layers(self):
        a, _ = _obj("л = sheet width=100 length=200 thickness=1\nfold л parts=2 angle=180 gap=0.5")
        b, _ = _obj("л = sheet width=100 length=200 thickness=1\nfold л parts=2 angle=180 gap=4")
        self.assertGreater(_size(b)[2], _size(a)[2] + 3.0)

    def test_thirds_and_accordion(self):
        third, _ = _obj("л = sheet width=100 length=300 thickness=1\n"
                        "fold л parts=3 angle=180 gap=1")
        self.assertEqual(third.genus(), 0)
        self.assertLess(_size(third)[0], 110.0)
        acc, _ = _obj("л = sheet width=100 length=300 thickness=1\n"
                      "fold л parts=4 angle=120 gap=1")
        verts, _ = manifold_mesh(acc)
        self.assertGreater(float(verts[:, 2].max()), 20.0)   # гармошка поднялась
        self.assertAlmostEqual(acc.volume(), 30000.0, delta=300.0)

    def test_quarter_fold_and_axis(self):
        m, _ = _obj("л = sheet width=100 length=200 thickness=1\n"
                    "fold л parts=2 angle=90 axis=y")
        w, d, h = _size(m)
        self.assertAlmostEqual(w, 200.0, delta=0.5)           # вдоль X не сгибали
        self.assertLess(d, 55.0)                              # ширина сложилась вдвое
        self.assertAlmostEqual(h, 50.0, delta=2.0)            # половина встала на 90°
        self.assertEqual(m.genus(), 0)

    def test_too_short_for_fold_is_explained(self):
        b = build("л = sheet width=80 length=30 thickness=1\nfold л parts=6 angle=180 gap=3")
        self.assertFalse(b.ok)
        self.assertIn("parts", (b.error or {}).get("hint", ""))

    def test_fold_works_on_any_solid(self):
        b = build("к = cube size=[60,60,4]\nfold к parts=2 angle=180 gap=1")
        self.assertTrue(b.ok, (b.error or {}).get("message"))


class CorrugateTest(unittest.TestCase):
    """Гофрирование: волны по готовой детали, объём и толщина сохраняются."""

    def test_modes_and_height(self):
        for mode in ("гофра", "вафля", "рифление", "зигзаг"):
            m, _ = _obj(f"л = sheet width=120 length=200 thickness=1\n"
                        f"corrugate л step=25 amp=5 mode={mode}")
            self.assertEqual(m.genus(), 0, mode)
            self.assertGreater(_size(m)[2], 7.0, mode)
            self.assertAlmostEqual(m.volume(), 24000.0, delta=240.0, msg=mode)

    def test_amp_zero_is_harmless(self):
        m, _ = _obj("л = sheet width=100 length=200 thickness=1\ncorrugate л step=20 amp=0")
        self.assertAlmostEqual(m.volume(), 20000.0, delta=20.0)

    def test_angle_turns_the_pattern(self):
        a, _ = _obj("л = sheet width=120 length=200 thickness=1\ncorrugate л step=30 amp=4 angle=0")
        b, _ = _obj("л = sheet width=120 length=200 thickness=1\ncorrugate л step=30 amp=4 angle=90")
        va, _ = manifold_mesh(a)
        vb, _ = manifold_mesh(b)
        # профиль вдоль X разный: у повёрнутого узора высота по сечению другая
        self.assertFalse(np.allclose(va[:, 2], vb[:, 2]))

    def test_bad_mode(self):
        b = build("л = sheet width=100 length=200 thickness=1\ncorrugate л mode=гармошка")
        self.assertFalse(b.ok)
        self.assertIn("гофра", (b.error or {}).get("hint", ""))

    def test_works_on_curved_part(self):
        b = build("ц = cylinder radius=40 height=100\ncorrugate ц step=20 amp=3")
        self.assertTrue(b.ok, (b.error or {}).get("message"))


class CardboardTest(unittest.TestCase):
    """Гофрокартон: линеры и гофра одним телом."""

    def test_three_layers(self):
        m, _ = _obj("к = cardboard width=200 height=300 liner=0.4 flute=3.5 step=8")
        w, d, h = _size(m)
        self.assertAlmostEqual(w, 300.0, delta=0.5)
        self.assertAlmostEqual(d, 200.0, delta=0.5)
        self.assertAlmostEqual(h, 2 * 0.4 + 3.5, delta=0.3)
        self.assertEqual(len([p for p in m.decompose() if p.volume() > 0]), 1)

    def test_two_layers(self):
        m, _ = _obj("к = cardboard width=150 height=200 layer=2 flute=2.5 step=6")
        self.assertAlmostEqual(_size(m)[2], 0.4 + 2.5, delta=0.3)
        self.assertEqual(len([p for p in m.decompose() if p.volume() > 0]), 1)

    def test_flute_lower_than_liner_is_explained(self):
        b = build("к = cardboard flute=0.2 liner=1")
        self.assertFalse(b.ok)
        self.assertIn("flute", (b.error or {}).get("hint", ""))

    def test_step_smaller_than_flute_is_explained(self):
        b = build("к = cardboard flute=6 step=4")
        self.assertFalse(b.ok)
        self.assertIn("step", (b.error or {}).get("hint", ""))


class SheetToolsInUiTest(unittest.TestCase):
    """Карточки новых инструментов и справка."""

    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        cls.block = cls.app.split("const TOOL_SHAPES = [", 1)[1].split("const TOOL_RECIPES", 1)[0]

    def test_cards_exist(self):
        for op in ("sheet", "fold", "corrugate", "cardboard"):
            self.assertIn(f"op: '{op}'", self.block)

    def test_card_values_build(self):
        """Значения из карточек действительно собираются — без выдуманных чисел."""
        cases = {
            "sheet": "лист = sheet width=120 length=200 thickness=1.2 step=0 amp=0 "
                     "wave=вдоль roll=0 gap=0",
            "fold": "заготовка = sheet width=120 length=240 thickness=1\n"
                    "fold заготовка parts=2 angle=180 gap=0.5 axis=x",
            "corrugate": "заготовка = sheet width=160 length=220 thickness=1\n"
                         "corrugate заготовка step=22 amp=5 mode=гофра angle=0",
            "cardboard": "картон = cardboard width=200 height=300 liner=0.4 "
                         "flute=3.5 step=8 layer=3",
        }
        for op, script in cases.items():
            with self.subTest(op=op):
                b = build(script, analyze_model=False)
                self.assertTrue(b.ok, (b.error or {}).get("message"))

    def test_help_has_explanations(self):
        import forma.run  # noqa: F401
        from forma.ops import OPS

        for op in ("sheet", "fold", "corrugate", "cardboard"):
            spec = OPS[op]
            self.assertTrue(spec.summary)
            self.assertTrue(spec.example)
            self.assertGreaterEqual(len(spec.params), 4)


if __name__ == "__main__":
    unittest.main()
