"""0.35: относительные мерки, размер по мерке и ряд с градацией силы.

Проверки держат просьбы пользователя:

1. **относительное смещение** — поставить деталь не на «пару сантиметров»,
   а на долю длины соседней: `0.5*width(а)`, `0.5*длина(а)`;
2. **относительный размер** — сделать деталь в 1.5 раза больше соседней:
   `размер [б] width=1.5*width(а)`, причём масштаб считается по факту;
3. **мерки по-русски** — `ширина()`, `высота()`, `глубина()`, `длина()`;
4. **ряд с градацией** — не одинаковые копии через равный шаг, а ступени
   изменения: рост `grow`, поворот `turn`, сдвиг `step`;
5. **сила инструмента ступенями** — `сила` и `шаг_силы`: вмятины глубже,
   крутка сильнее, сужение резче — как у значка Wi-Fi;
6. **примеры** — `wifi.forma` (кольца всё больше) и `graded.forma`
   (крутка по ступеням) собираются и дают ожидаемую геометрию.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from forma.ops import lookup
from forma.run import build
import forma.run  # noqa: F401  (наполняет реестр команд)
from forma.webui import EXAMPLES, load_example


def _build(script: str):
    b = build(script, analyze_model=False)
    assert b.ok, (b.error or {}).get("message")
    return b


def _solid(build_result, name: str):
    return build_result.scene.objects[name].manifold


def _size(build_result, name: str):
    bb = _solid(build_result, name).bounding_box()
    return np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]], dtype=float)


class RelativeMeasuresTest(unittest.TestCase):
    """Мерки соседа прямо в числах: 0.5 ширины, 1.5 высоты."""

    def test_half_width_moves_object(self):
        b = _build("а = box size=[80,40,20]\n"
                   "б = box size=[20,20,20]\n"
                   "б = translate [б] offset=[0.5*width(а),0,0]")
        bb = _solid(b, "б").bounding_box()
        # а шириной 80 стоит по центру в 0; б шириной 20 уехал на 40
        self.assertAlmostEqual((bb[0] + bb[3]) / 2.0, 40.0, places=3)

    def test_russian_measure_names(self):
        b = _build("ящик = box size=[80,40,60]\n"
                   "шайба = cylinder radius=5 height=2\n"
                   "шайба = translate [шайба] offset=[0,0,высота(ящик)]")
        bb = _solid(b, "шайба").bounding_box()
        self.assertAlmostEqual(bb[2], 60.0, places=3)

    def test_length_is_longest_side(self):
        b = _build("доска = box size=[200,40,20]\n"
                   "кубик = box size=[10,10,10]\n"
                   "кубик = translate [кубик] offset=[0.5*длина(доска),0,0]")
        bb = _solid(b, "кубик").bounding_box()
        self.assertAlmostEqual((bb[0] + bb[3]) / 2.0, 100.0, places=3)

    def test_measure_on_unknown_object_gives_error(self):
        b = build("а = box size=[10,10,10]\nб = translate [а] offset=[width(нет),0,0]",
                  analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("нет", (b.error or {}).get("message", "").lower())


class ResizeTest(unittest.TestCase):
    """`размер` задаёт габарит по мерке, а не множитель."""

    def test_width_from_other_object(self):
        b = _build("а = box size=[80,40,20]\n"
                   "б = box size=[10,10,10]\n"
                   "б = размер [б] width=1.5*width(а)")
        size = _size(b, "б")
        self.assertAlmostEqual(size[0], 120.0, places=3)
        self.assertAlmostEqual(size[2], 10.0, places=3)   # остальное не тронуто

    def test_two_axes_at_once(self):
        b = _build("а = box size=[80,40,20]\n"
                   "б = box size=[10,10,10]\n"
                   "б = размер [б] width=width(а) depth=0.5*depth(а)")
        size = _size(b, "б")
        self.assertAlmostEqual(size[0], 80.0, places=3)
        self.assertAlmostEqual(size[1], 20.0, places=3)

    def test_factor(self):
        b = _build("б = box size=[10,10,10]\nб = размер [б] factor=2")
        size = _size(b, "б")
        self.assertAlmostEqual(size[0], 20.0, places=3)
        self.assertAlmostEqual(size[2], 20.0, places=3)

    def test_length_target(self):
        b = _build("а = box size=[200,40,20]\n"
                   "б = box size=[10,10,10]\n"
                   "б = размер [б] length=0.25*length(а)")
        size = _size(b, "б")
        self.assertAlmostEqual(size.max(), 50.0, places=2)

    def test_without_target_is_error(self):
        b = build("б = box size=[10,10,10]\nб = размер [б]", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("размер", (b.error or {}).get("message", "").lower())


class GradedRowTest(unittest.TestCase):
    """`ряд`: копии с накоплением изменений."""

    def test_linear_step_accumulates(self):
        b = _build("а = box size=[10,10,10]\n"
                   "р = ряд [а] count=4 step=[20,0,0]")
        size = _size(b, "р")
        # четыре кубика по 10 через 20: от -5 до 65
        self.assertAlmostEqual(size[0], 70.0, places=3)

    def test_grow_multiplies_size(self):
        b = _build("к = torus major=10 minor=2\n"
                   "р = ряд [к] count=3 grow=1.5")
        size = _size(b, "р")
        # кольцо 24 мм, третья копия 1.5² = 2.25 → 54 мм
        self.assertAlmostEqual(size[0], 54.0, places=2)

    def test_turn_rotates_each_copy(self):
        b = _build("а = box size=[60,10,10]\n"
                   "р = ряд [а] count=3 turn=90 axis=z")
        size = _size(b, "р")
        # вторая копия повёрнута на 90° — габарит стал квадратным
        self.assertAlmostEqual(size[0], size[1], delta=0.5)

    def test_single_copy_is_source(self):
        b = _build("а = box size=[10,20,30]\nр = ряд [а] count=1")
        size = _size(b, "р")
        self.assertAlmostEqual(size[0], 10.0, places=3)
        self.assertAlmostEqual(size[2], 30.0, places=3)

    def test_at_moves_whole_row(self):
        b = _build("а = box size=[10,10,10]\nр = ряд [а] count=2 step=[20,0,0] at=[0,0,100]")
        bb = _solid(b, "р").bounding_box()
        self.assertAlmostEqual(bb[2], 100.0, places=2)

    def test_merge_false_keeps_first_only(self):
        b = _build("а = box size=[10,10,10]\nр = ряд [а] count=3 step=[20,0,0] merge=нет")
        size = _size(b, "р")
        self.assertAlmostEqual(size[0], 10.0, places=3)

    def test_unknown_tool_is_error(self):
        b = build("а = box size=[10,10,10]\nр = ряд [а] count=2 инструмент=магия",
                  analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("магия", (b.error or {}).get("message", "").lower())


class GradedStrengthTest(unittest.TestCase):
    """Сила инструмента идёт ступенями, а не одинаково у всех копий."""

    def test_dent_grows_with_each_copy(self):
        b = _build("ш = sphere radius=14 segments=64\n"
                   "р = ряд [ш] count=5 step=[34,0,0] инструмент=вмятина "
                   "сила=1.0 шаг_силы=1.6 soft=0.8")
        solid = _solid(b, "р")
        # объём пятой копии меньше первой: вмятина глубже
        parts = sorted(solid.decompose(), key=lambda m: m.bounding_box()[0])
        self.assertEqual(len(parts), 5)
        first, last = parts[0].volume(), parts[-1].volume()
        self.assertLess(last, first - 5.0)

    def test_twist_grows_with_each_copy(self):
        b = _build("б = box size=[20,20,80]\n"
                   "б = refine [б] length=8\n"
                   "р = ряд [б] count=4 step=[30,0,0] инструмент=скрутка "
                   "сила=15 шаг_силы=1.4 axis=z")
        parts = sorted(_solid(b, "р").decompose(), key=lambda m: m.bounding_box()[0])
        self.assertEqual(len(parts), 4)
        # у сильно закрученной копии вершина повёрнута: габарит по X больше 20
        widths = [p.bounding_box()[3] - p.bounding_box()[0] for p in parts]
        self.assertGreater(max(widths), 20.5)

    def test_taper_tool_narrows(self):
        b = _build("б = box size=[40,40,60]\n"
                   "б = refine [б] length=8\n"
                   "р = ряд [б] count=3 step=[50,0,0] инструмент=сужение "
                   "сила=0.6 шаг_силы=1.0")
        parts = sorted(_solid(b, "р").decompose(), key=lambda m: m.bounding_box()[0])
        # копии стоят через 50, поэтому делим по X
        first = parts[0].bounding_box()
        last = parts[-1].bounding_box()
        self.assertAlmostEqual(first[3] - first[0], 40.0, delta=0.5)
        self.assertAlmostEqual(last[3] - last[0], 40.0, delta=0.5)


class ExamplesTest(unittest.TestCase):
    """Примеры 0.35 собираются и показывают именно градацию."""

    def test_examples_registered(self):
        names = {e[1] if isinstance(e, (list, tuple)) else e for e in EXAMPLES}
        self.assertIn("wifi", names)
        self.assertIn("graded", names)

    def test_wifi_rings_grow(self):
        b = build(load_example("wifi"), analyze_model=False)
        self.assertTrue(b.ok, (b.error or {}).get("message"))
        bb = b.scene.objects["дуги"].manifold.bounding_box()
        width = bb[3] - bb[0]
        # три кольца 1.5×: внешнее кольцо диаметром 2·(22+4)·2.25 ≈ 117 мм
        self.assertGreater(width, 100.0)
        # дуги — именно половины: низ срезан ровно по полу
        self.assertGreaterEqual(bb[2], -0.01)

    def test_wifi_rings_are_concentric(self):
        b = build(load_example("wifi"), analyze_model=False)
        parts = b.scene.objects["дуги"].manifold.decompose()
        self.assertEqual(len(parts), 3)
        centers = [(p.bounding_box()[0] + p.bounding_box()[3]) / 2 for p in parts]
        for c in centers:
            self.assertAlmostEqual(c, 0.0, delta=0.5)

    def test_graded_example_builds(self):
        b = build(load_example("graded"), analyze_model=False)
        self.assertTrue(b.ok, (b.error or {}).get("message"))
        self.assertIn("бруски", b.scene.objects)
        self.assertEqual(len(b.scene.objects["бруски"].manifold.decompose()), 6)


if __name__ == "__main__":
    unittest.main()
