"""0.40: механика и произвольные формы — призма, сектор тора, лестница,
рычаг, кнопка. Плюс регрессия на мёртвый интерфейс 0.38.

Проверки держат просьбу пользователя:

1. **треугольная призма** — не только равносторонний треугольник: стороны
   подбираются числами, есть прямой и тупоугольный вариант, а также задание
   через основание и два угла;
2. **сектор тора** — дуга бублика с углом и поворотом; `hole` делает кольцо
   дырявым (сквозное отверстие, род 1), не ломая габарит;
3. **лестница** — форма боковых реек (капсула, брусок, овал) и перекладин
   (цилиндр, брусок) настраивается; число перекладин и наклон работают;
   вся лестница — один объём;
4. **рычаг** — палка цилиндр/брусок плюс ручка шар/цилиндр/нет, наклон;
5. **кнопка** — верх плоский/вогнутый/выпуклый, гнездо цилиндр/квадрат,
   посадка плотная или с зазором, и **два отдельных объекта** для анимации;
6. карточки, справка, пример и проверка синтаксиса app.js (регрессия 0.38).
"""

from __future__ import annotations

import math
import unittest

import numpy as np

import forma.run  # noqa: F401  (наполняет реестр команд)
from forma.ops import OPS, lookup
from forma.run import build


def _build(script: str):
    b = build(script, analyze_model=False)
    assert b.ok, (b.error or {}).get("message")
    return b


def _solid(result, name: str):
    return result.scene.objects[name].manifold


def _size(result, name: str):
    bb = _solid(result, name).bounding_box()
    return np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]], dtype=float)


class TriPrismTest(unittest.TestCase):
    """Треугольная призма с произвольными углами."""

    def test_equilateral_matches_formula(self):
        b = _build("п = tri_prism a=100 height=60")
        side, h = 100.0, 60.0
        area = math.sqrt(3) / 4.0 * side ** 2
        self.assertAlmostEqual(_solid(b, "п").volume() / (area * h), 1.0, delta=0.01)
        self.assertAlmostEqual(_size(b, "п")[0], side, delta=0.05)
        self.assertAlmostEqual(_size(b, "п")[2], h, delta=0.05)

    def test_sides_can_differ(self):
        b = _build("к = tri_prism a=120 b=90 c=60 height=80")
        # треугольник целиком помещается в габарит по X, высота не меняется
        self.assertAlmostEqual(_size(b, "к")[0], 120.0, delta=0.05)
        self.assertAlmostEqual(_size(b, "к")[2], 80.0, delta=0.05)
        # площадь по Герону × высота
        p = (120 + 90 + 60) / 2.0
        area = math.sqrt(p * (p - 120) * (p - 90) * (p - 60))
        self.assertAlmostEqual(_solid(b, "к").volume() / (area * 80), 1.0, delta=0.01)

    def test_right_triangle(self):
        b = _build("т = tri_prism a=60 b=80 c=100 height=40")
        area = 0.5 * 60 * 80
        self.assertAlmostEqual(_solid(b, "т").volume() / (area * 40), 1.0, delta=0.01)
        self.assertTrue(np.all(np.isfinite(_size(b, "т"))))

    def test_angles_give_the_same_shape_as_sides(self):
        by_angles = _build("у = tri_prism base=100 angle_a=30 angle_b=120 height=40")
        # угол 30° при основании слева, 120° справа: вершина уходит за габарит
        self.assertAlmostEqual(_size(by_angles, "у")[0], 150.0, delta=1.0)
        self.assertAlmostEqual(_size(by_angles, "у")[1], 86.60, delta=1.0)

    def test_impossible_sides_are_reported(self):
        b = build("ф = tri_prism a=10 b=1 c=1", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("треугольник", (b.error or {}).get("message", ""))

    def test_rounding_keeps_height_and_shrinks_volume(self):
        sharp = _build("о = tri_prism a=100 b=100 c=80 height=50")
        soft = _build("о = tri_prism a=100 b=100 c=80 height=50 round=5")
        self.assertAlmostEqual(_size(soft, "о")[2], 50.0, delta=0.05)
        self.assertLess(_solid(soft, "о").volume(), _solid(sharp, "о").volume())
        self.assertEqual(len(_solid(soft, "о").decompose()), 1)


class TorusSectorTest(unittest.TestCase):
    """Дуга тора и дырявый сектор."""

    def test_full_ring_volume(self):
        b = _build("к = torus_sector major=60 minor=10 angle=360")
        expect = 2 * math.pi ** 2 * 60 * 10 ** 2
        self.assertAlmostEqual(_solid(b, "к").volume() / expect, 1.0, delta=0.02)
        self.assertAlmostEqual(_size(b, "к")[2], 20.0, delta=0.3)

    def test_half_ring_is_half(self):
        full = _build("к = torus_sector major=60 minor=10 angle=360")
        half = _build("к = torus_sector major=60 minor=10 angle=180")
        self.assertAlmostEqual(_solid(half, "к").volume() / _solid(full, "к").volume(),
                               0.5, delta=0.03)
        # дуга 0…180° идёт от +X через +Y к −X: 140 в ширину, 70 в высоту
        self.assertTrue(np.allclose(_size(half, "к"), [140.0, 70.0, 20.0], atol=0.5))
        quarter = _build("к = torus_sector major=60 minor=10 angle=90")
        self.assertTrue(np.allclose(_size(quarter, "к"), [70.0, 70.0, 20.0], atol=0.5))

    def test_hole_makes_it_hollow(self):
        solid_arc = _build("п = torus_sector major=50 minor=12 angle=200")
        holed = _build("п = torus_sector major=50 minor=12 angle=200 hole=8")
        self.assertEqual(_solid(solid_arc, "п").genus(), 0)
        self.assertEqual(_solid(holed, "п").genus(), 1)
        self.assertLess(_solid(holed, "п").volume(), _solid(solid_arc, "п").volume())
        self.assertEqual(len(_solid(holed, "п").decompose()), 1)

    def test_too_big_hole_is_reported(self):
        b = build("п = torus_sector major=50 minor=10 hole=40", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("стенки", (b.error or {}).get("message", ""))

    def test_start_rotates_the_arc(self):
        flat = _build("п = torus_sector major=60 minor=10 angle=180")
        turned = _build("п = torus_sector major=60 minor=10 angle=180 start=90")
        # поворот на 90° меняет ширину и высоту дуги местами
        self.assertTrue(np.allclose(_size(flat, "п"), [140.0, 70.0, 20.0], atol=0.5))
        self.assertTrue(np.allclose(_size(turned, "п"), [70.0, 140.0, 20.0], atol=0.5))


class LadderTest(unittest.TestCase):
    """Лестница: рейки и перекладины настраиваются."""

    def test_standing_ladder_height(self):
        b = _build("л = ladder length=1800 width=420 rungs=9 tilt=90")
        self.assertAlmostEqual(_size(b, "л")[2], 1800.0, delta=3.0)
        self.assertAlmostEqual(_size(b, "л")[1], 420.0 + 38.0, delta=2.0)

    def test_tilt_is_angle_to_floor(self):
        # 90° — стоит: высота равна длине реек
        stand = _build("л = ladder length=1800 width=420 rungs=9 tilt=90")
        self.assertAlmostEqual(_size(stand, "л")[2], 1800.0, delta=1.0)
        # 0° — лежит: высота равна толщине рейки
        lying = _build("л = ladder length=1800 width=420 rungs=9 tilt=0")
        self.assertAlmostEqual(_size(lying, "л")[2], 38.0, delta=1.0)
        self.assertAlmostEqual(_size(lying, "л")[0], 1800.0, delta=1.0)
        # 72° — приставная: высокая и наклонная
        lean = _build("л = ladder length=1800 width=420 rungs=9 tilt=72")
        h = _size(lean, "л")[2]
        self.assertGreater(h, 1800 * 0.94)
        self.assertLess(h, 1800.0)
        self.assertGreater(_size(lean, "л")[0], 400.0)

    def test_one_body(self):
        b = _build("л = ladder length=1600 width=400 rungs=8")
        self.assertEqual(len(_solid(b, "л").decompose()), 1)

    def test_more_rungs_add_material(self):
        few = _build("л = ladder length=1600 width=400 rungs=4")
        many = _build("л = ladder length=1600 width=400 rungs=12")
        self.assertLess(_solid(few, "л").volume(), _solid(many, "л").volume())
        self.assertLess(_solid(few, "л").num_tri(), _solid(many, "л").num_tri())

    def test_rail_and_rung_shapes_differ(self):
        kinds = {
            "капсула": "rail=капсула rail_d=40 rung=цилиндр rung_d=28",
            "брусок": "rail=брусок rail_d=40 rung=брусок rung_d=28",
            "овал": "rail=овал rail_d=40 rung=цилиндр rung_d=28",
        }
        sizes = {}
        for key, extra in kinds.items():
            b = _build(f"л = ladder length=1200 width=360 rungs=6 {extra}")
            sizes[key] = _size(b, "л")
            self.assertAlmostEqual(sizes[key][2], 1200 * math.sin(math.radians(75)),
                                   delta=15.0)
            self.assertAlmostEqual(sizes[key][1], 360.0 + 40.0, delta=1.0)
        # овал — скруглённое сечение, габарит по Y такой же, а объём меньше бруска
        box = _build("л = ladder length=1200 width=360 rungs=6 rail=брусок rail_d=40")
        oval = _build("л = ladder length=1200 width=360 rungs=6 rail=овал rail_d=40")
        self.assertLess(_solid(oval, "л").volume(), _solid(box, "л").volume())

    def test_bad_shape_names_are_reported(self):
        b = build("л = ladder rail=верёвка", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("рейки", (b.error or {}).get("message", ""))


class LeverTest(unittest.TestCase):
    """Рычаг: палка и ручка."""

    def test_length_is_exact(self):
        b = _build("р = lever length=180 diameter=14 knob=шар knob_d=34")
        self.assertAlmostEqual(_size(b, "р")[0], 180.0, delta=0.5)

    def test_knob_shapes(self):
        ball = _build("р = lever length=180 diameter=14 knob=шар knob_d=40 knob_h=50")
        tube = _build("р = lever length=180 diameter=14 knob=цилиндр knob_d=40 knob_h=50")
        self.assertEqual(len(_solid(ball, "р").decompose()), 1)
        self.assertEqual(len(_solid(tube, "р").decompose()), 1)
        self.assertAlmostEqual(_size(ball, "р")[1], 40.0, delta=0.2)
        self.assertAlmostEqual(_size(tube, "р")[1], 40.0, delta=0.2)
        self.assertNotAlmostEqual(_solid(ball, "р").volume(), _solid(tube, "р").volume(), delta=1.0)

    def test_square_shaft(self):
        b = _build("р = lever length=140 shaft=брусок size=20 knob=цилиндр knob_d=30 knob_h=40")
        self.assertAlmostEqual(_size(b, "р")[0], 140.0, delta=0.2)
        self.assertAlmostEqual(_size(b, "р")[1], 30.0, delta=0.2)
        self.assertEqual(len(_solid(b, "р").decompose()), 1)

    def test_angle_lifts_the_tip(self):
        flat = _build("р = lever length=200 diameter=12 knob=шар knob_d=26 knob_h=40")
        up = _build("р = lever length=200 diameter=12 knob=шар knob_d=26 knob_h=40 angle=30")
        self.assertAlmostEqual(_size(flat, "р")[2], 26.0, delta=0.3)
        self.assertGreater(_size(up, "р")[2], 90.0)

    def test_none_knob_is_removed(self):
        b = build("р = lever knob=нет", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("больше нет", (b.error or {}).get("message", ""))

    def test_bad_knob_is_reported(self):
        b = build("р = lever knob=грабли", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("knob", (b.error or {}).get("message", ""))


class ButtonTest(unittest.TestCase):
    """Кнопка — две отдельные детали."""

    def test_two_objects(self):
        b = _build("к = button diameter=30 height=10")
        self.assertIn("к", b.scene.objects)
        self.assertIn("к_гнездо", b.scene.objects)
        self.assertEqual(len(b.scene.objects), 2)

    def test_cap_sits_above_the_socket_floor(self):
        b = _build("к = button diameter=30 height=10 base_h=8")
        plate = _solid(b, "к_гнездо").bounding_box()
        cap = _solid(b, "к").bounding_box()
        self.assertAlmostEqual(plate[2], 0.0, delta=1e-6)     # гнездо стоит на полу
        self.assertAlmostEqual(plate[5], 8.0, delta=0.05)     # высота платформы
        self.assertGreater(cap[2], plate[2])                  # шляпка в вырезе
        self.assertLess(cap[2], plate[5])                     # но ниже верха гнезда
        self.assertGreater(cap[5], plate[5])                  # и выступает над ним
        self.assertAlmostEqual(plate[3] - plate[0], plate[4] - plate[1], delta=0.2)

    def test_parts_do_not_intersect(self):
        b = _build("к = button diameter=30 height=10 fit=зазор gap=3")
        cap = b.scene.objects["к"].manifold
        plate = b.scene.objects["к_гнездо"].manifold
        gap = cap.bounding_box()[2] - plate.bounding_box()[5]
        self.assertLess(gap, 0.0)  # шляпка сидит в вырезе, а не поверх
        cap_r = (cap.bounding_box()[3] - cap.bounding_box()[0]) / 2.0
        self.assertAlmostEqual(cap_r, 15.0, delta=0.2)

    def test_loose_fit_removes_more_material(self):
        tight = _build("к = button diameter=30 height=10 fit=плотно")
        loose = _build("к = button diameter=30 height=10 fit=зазор gap=4")
        self.assertLess(_solid(loose, "к_гнездо").volume(),
                        _solid(tight, "к_гнездо").volume())

    def test_square_socket_is_centred(self):
        b = _build("к = button diameter=24 height=8 base=квадрат base_d=60")
        plate = _solid(b, "к_гнездо").bounding_box()
        self.assertAlmostEqual(plate[3] - plate[0], 60.0, delta=0.2)
        self.assertAlmostEqual(plate[4] - plate[1], 60.0, delta=0.2)
        self.assertAlmostEqual((plate[0] + plate[3]) / 2.0, 0.0, delta=0.2)
        self.assertAlmostEqual((plate[1] + plate[4]) / 2.0, 0.0, delta=0.2)

    def test_top_shapes_change_volume(self):
        flat = _build("к = button diameter=40 height=12 top=плоская")
        dish = _build("к = button diameter=40 height=12 top=вогнутая")
        dome = _build("к = button diameter=40 height=12 top=выпуклая")
        self.assertLess(_solid(dish, "к").volume(), _solid(flat, "к").volume())
        self.assertGreater(_solid(dome, "к").volume(), _solid(flat, "к").volume())

    def test_too_deep_dish_is_reported(self):
        b = build("к = button height=10 top=вогнутая sag=20", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("Ложбинка", (b.error or {}).get("message", ""))


class CatalogAndHelpTest(unittest.TestCase):
    """Команды видны в справке, каталоге и примере."""

    OPS = ("tri_prism", "torus_sector", "ladder", "lever", "button")

    def test_help_explains_each_command(self):
        for op in self.OPS:
            spec = OPS[op]
            with self.subTest(op=op):
                self.assertTrue(spec.summary)
                self.assertTrue(spec.example)
                self.assertEqual(spec.category, "Примитивы")

    def test_russian_aliases(self):
        for word, op in (("лестница", "ladder"), ("рычаг", "lever"),
                         ("кнопка", "button"), ("треугольная_призма", "tri_prism"),
                         ("сектор_тора", "torus_sector")):
            with self.subTest(word=word):
                self.assertEqual(lookup(word).name, op)

    def test_parameter_aliases_reach_the_command(self):
        b = _build("л = лестница длина=1500 ширина=400 наклон=90 перекладин=6")
        self.assertAlmostEqual(_size(b, "л")[2], 1500.0, delta=3.0)
        b = _build("к = кнопка диаметр=30 высота=10 посадка=зазор зазор=2")
        self.assertIn("к_гнездо", b.scene.objects)



    def test_cards_present(self):
        from pathlib import Path

        app = (Path(__file__).resolve().parent.parent / "web/js/app.js").read_text(
            encoding="utf-8")
        block = app.split("const TOOL_SHAPES = [", 1)[1].split("const TOOL_RECIPES", 1)[0]
        for title in ("Треугольная призма", "Сектор тора", "Лестница", "Рычаг",
                      "Кнопка (2 детали)"):
            with self.subTest(title=title):
                self.assertIn(f"title: '{title}'", block)

    def test_instruction_lists_new_commands(self):
        from forma.instruction import full_instruction

        text = full_instruction()
        for word in ("tri_prism", "torus_sector", "ladder", "lever", "button",
                     "лестница", "рычаг", "кнопка", "Сектор тора", "Треугольная призма"):
            with self.subTest(word=word):
                self.assertIn(word, text)


class ScriptSyntaxTest(unittest.TestCase):
    """Регрессия 0.38: интерфейс умирал от повторного объявления в app.js."""

    def test_app_js_has_no_duplicate_const_in_functions(self):
        """В 0.38 в renderTools было два `const order` — модуль не загружался.

        Ищем объявления на верхнем уровне каждой функции (отступ 2 пробела):
        имя, объявленное дважды в одной области видимости, — фатальная
        SyntaxError, и весь интерфейс остаётся мёртвым.
        """
        from pathlib import Path

        app = (Path(__file__).resolve().parent.parent / "web/js/app.js").read_text(
            encoding="utf-8")
        current, seen, problems, checked = None, set(), [], 0
        for number, line in enumerate(app.splitlines(), 1):
            if line.startswith(("function ", "async function ")):
                current, seen = line.split("(")[0].rsplit(" ", 1)[-1], set()
                continue
            if line.startswith("}"):
                current = None
                continue
            if current and line.startswith("  const ") and "=" in line:
                checked += 1
                name = line.strip()[6:].split("=")[0].strip()
                if name in seen:
                    problems.append(f"{current}:{number} — {name}")
                seen.add(name)
        self.assertGreater(checked, 100, "объявления в функциях не найдены")
        self.assertEqual(problems, [], f"повторные объявления: {problems}")

    def test_no_duplicate_top_level_function_names(self):
        from pathlib import Path

        app = (Path(__file__).resolve().parent.parent / "web/js/app.js").read_text(
            encoding="utf-8")
        names = [ln.strip().split("(")[0][9:] for ln in app.splitlines()
                 if ln.startswith("function ")]
        self.assertEqual(len(names), len(set(names)), "функции задвоились")


if __name__ == "__main__":
    unittest.main()
