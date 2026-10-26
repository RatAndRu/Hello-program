"""0.38: каталог примитивов по ступеням, октаэдр, эллипсоид и скоба.

Проверки держат просьбу пользователя:

1. **порядок каталога** — первыми идут стандартные тела (лист, куб, призма,
   октаэдр, пирамида, конус, цилиндр, шар, икосфера, эллипсоид, капсула, тор,
   кольцо, шайба), потом производные, природные и готовые детали, а приёмы
   лепки и поверхностей — отдельным разделом;
2. **новые тела** — октаэдр (8 треугольных граней), эллипсоид (три полуоси)
   и скоба-профиль (П / U / замкнутая рамка) собираются одной командой;
3. **однозначные имена** — `лист` это плоскость, `листок` — лист растения,
   `плоскость` не уводит в разравнивание, `шкиф` и `иньянь` находятся;
4. **ни одной карточки без команды** — каждый `op` из панели есть в реестре.
"""

from __future__ import annotations

import math
import re
import unittest

import manifold3d as mf
import numpy as np

import forma.run  # noqa: F401  (наполняет реестр команд)
from forma.ops import OPS, lookup
from forma.run import build

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _build(script: str):
    b = build(script, analyze_model=False)
    assert b.ok, (b.error or {}).get("message")
    return b


def _solid(result, name: str):
    return result.scene.objects[name].manifold


def _size(result, name: str):
    bb = _solid(result, name).bounding_box()
    return np.array([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]], dtype=float)


class NewBodiesTest(unittest.TestCase):
    """Октаэдр, эллипсоид и скоба — новые стандартные тела."""

    def test_octa_registered(self):
        spec = lookup("октаэдр")
        self.assertIsNotNone(spec)
        self.assertEqual(spec.name, "octa")
        for key in ("radius", "height", "depth"):
            self.assertIn(key, spec.params)

    def test_octa_has_eight_triangular_faces(self):
        b = _build("к = octa radius=30 height=80")
        solid = _solid(b, "к")
        self.assertEqual(solid.num_tri(), 8)
        # объём ромбического октаэдра: (1/6)·d1·d2·d3
        self.assertAlmostEqual(solid.volume(), 60 * 60 * 80 / 6.0, delta=1.0)
        self.assertTrue(np.allclose(_size(b, "к"), [60.0, 60.0, 80.0], atol=0.01))

    def test_octa_stands_on_floor(self):
        b = _build("к = octa radius=25")
        bb = _solid(b, "к").bounding_box()
        self.assertAlmostEqual(bb[2], 0.0, delta=0.01)
        self.assertAlmostEqual(bb[5], 50.0, delta=0.01)

    def test_ellipsoid_semi_axes(self):
        b = _build("э = ellipsoid x=60 y=40 z=22")
        self.assertTrue(np.allclose(_size(b, "э"), [120.0, 80.0, 44.0], atol=0.2))
        expect = 4.0 / 3.0 * math.pi * 60 * 40 * 22
        self.assertAlmostEqual(_solid(b, "э").volume() / expect, 1.0, delta=0.01)

    def test_ellipsoid_defaults_to_sphere(self):
        b = _build("ш = ellipsoid x=30")
        self.assertTrue(np.allclose(_size(b, "ш"), [60.0, 60.0, 60.0], atol=0.2))

    def test_bracket_wall_and_opening(self):
        u = _build("у = скоба length=120 width=40 height=30 wall=3")
        p = _build("п = скоба length=120 width=40 height=30 wall=3 open=вниз")
        # открытая скоба: наружный объём минус внутренний
        expect = 120 * 40 * 30 - 120 * 34 * 27
        self.assertAlmostEqual(_solid(u, "у").volume(), expect, delta=1.0)
        self.assertAlmostEqual(_solid(p, "п").volume(), expect, delta=1.0)
        # П и U — одна деталь: Z-габарит одинаковый, но полка с другой стороны
        bb_u = _solid(u, "у").bounding_box()
        bb_p = _solid(p, "п").bounding_box()
        self.assertAlmostEqual(bb_u[5] - bb_u[2], bb_p[5] - bb_p[2], delta=0.01)
        low = mf.Manifold.cube((400, 400, 2), center=True).translate((0.0, 0.0, 1.0))
        low_u = mf.Manifold.batch_boolean([_solid(u, "у"), low], mf.OpType.Intersect)
        low_p = mf.Manifold.batch_boolean([_solid(p, "п"), low], mf.OpType.Intersect)
        # у U внизу целая полка, у П — только две стенки по бокам
        self.assertGreater(low_u.volume(), low_p.volume() * 3.0)

    def test_bracket_frame_is_closed(self):
        b = _build("р = скоба length=160 width=90 height=60 wall=4 стороны=4")
        expect = 160 * 90 * 60 - 160 * 82 * 52
        self.assertAlmostEqual(_solid(b, "р").volume(), expect, delta=2.0)
        # у замкнутой рамки внутри просвет, а не глухой лист
        hole = mf.Manifold.cube((40, 40, 20), center=True).translate((0.0, 0.0, 30.0))
        inner = mf.Manifold.batch_boolean([_solid(b, "р"), hole], mf.OpType.Intersect)
        self.assertLess(inner.volume(), 1.0)

    def test_bracket_refuses_impossible_wall(self):
        b = build("с = скоба length=100 width=10 height=10 wall=6", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("Стенка", (b.error or {}).get("message", ""))


class NamesAreUnambiguousTest(unittest.TestCase):
    """Одно слово — одна команда: ИИ не должна путать лист с листком."""

    def test_sheet_is_list(self):
        self.assertEqual(lookup("лист").name, "sheet")
        self.assertEqual(lookup("плоскость").name, "sheet")

    def test_plant_leaf_is_listok(self):
        self.assertEqual(lookup("листок").name, "leaf")
        self.assertEqual(lookup("лист_растения").name, "leaf")

    def test_common_misspellings_resolve(self):
        self.assertEqual(lookup("шкиф").name, "pulley")
        self.assertEqual(lookup("иньянь").name, "yin_yang")
        self.assertEqual(lookup("п_образная").name, "скоба")
        self.assertEqual(lookup("u-профиль").name, "скоба")

    def test_verbs_are_not_shapes(self):
        self.assertEqual(lookup("дуга").name, "bend")
        self.assertEqual(lookup("согнуть").name, "bend")
        self.assertEqual(lookup("точить").name, "lathe")
        self.assertEqual(lookup("зеркало").name, "mirror")
        self.assertEqual(lookup("выдавить").name, "extrude")

    def test_every_command_finds_itself(self):
        """Имя команды не перекрыто чужим синонимом: `bolt` — это болт."""
        bad = [(name, (lookup(name).name if lookup(name) else None))
               for name in OPS if lookup(name) is None or lookup(name).name != name]
        self.assertEqual(bad, [], f"имя команды уводит в другую: {bad}")


class CatalogOrderTest(unittest.TestCase):
    """Панель инструментов: сначала тела, потом способы."""

    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "web/js/app.js").read_text(encoding="utf-8")
        cls.block = cls.app.split("const TOOL_SHAPES = [", 1)[1].split("const TOOL_RECIPES", 1)[0]
        cls.cards = re.findall(
            r"op: '([^']+)', name: '([^']+)', title: '([^']+)', group: '([^']+)'", cls.block)
        cls.ops = [c[0] for c in cls.cards]
        cls.groups = [c[3] for c in cls.cards]

    def test_standard_bodies_go_first(self):
        standard = ["sheet", "box", "prism", "octa", "pyramid", "cone", "cylinder",
                    "sphere", "icosphere", "ellipsoid", "capsule", "torus", "ring",
                    "washer"]
        self.assertEqual(self.ops[:len(standard)], standard)
        self.assertEqual(set(self.groups[:len(standard)]), {"Стандартные примитивы"})

    def test_group_sequence(self):
        order = []
        for group in self.groups:
            if not order or order[-1] != group:
                order.append(group)
        self.assertEqual(order, ["Стандартные примитивы", "Производные примитивы",
                                 "Природные примитивы", "Готовые детали",
                                 "Скульпт", "Поверхность", "Форма", "Массивы",
                                 "Люди и вещи", "Покраска"])

    def test_derived_and_nature_follow_user_list(self):
        standard = ["sheet", "box", "prism", "octa", "pyramid", "cone", "cylinder",
                    "sphere", "icosphere", "ellipsoid", "capsule", "torus", "ring",
                    "washer", "disc", "oval"]
        derived = ["hemisphere", "sector", "bracket", "полуовал", "arch", "воронка",
                   "скоба", "lens", "полукапсула", "ingot", "paraboloid", "saddle",
                   "pie", "bead", "tri_prism", "torus_sector"]
        nature = ["egg", "drop", "crescent", "star", "lightning", "heart", "cloud",
                  "diamond", "horn", "rock", "leaf", "banana"]
        self.assertEqual(self.ops[:len(standard)], standard)
        start = len(standard)
        self.assertEqual(self.ops[start:start + len(derived)], derived)
        start += len(derived)
        self.assertEqual(self.ops[start:start + len(nature)], nature)

    def test_ready_made_follow_user_list(self):
        ready = ["yin_yang", "crown", "arrow", "tee", "yoke", "plate",
                 "spring", "gear", "saw", "nut", "bolt", "screw", "pulley",
                 "box_body", "shaft", "wheel", "spiral", "plus", "rope", "цепь",
                 "крюк", "handle", "cardboard", "swirl", "stairs", "ladder",
                 "lever", "button", "gusset", "grommet", "blade"]
        start = self.ops.index("yin_yang")
        self.assertEqual(self.ops[start:start + len(ready)], ready)

    def test_two_sections_in_panel(self):
        self.assertIn("const PRIMITIVE_GROUPS", self.app)
        self.assertIn("const TOOL_GROUP_ORDER", self.app)
        self.assertIn("'Инструменты и способы'", self.app)
        self.assertIn("tool-sec", self.app)
        css = (ROOT / "web/css/app.css").read_text(encoding="utf-8")
        self.assertIn(".tool-sec", css)

    def test_every_card_has_command(self):
        missing = sorted({op for op in self.ops if op not in OPS})
        self.assertEqual(missing, [], f"карточки без команды: {missing}")

    def test_new_cards_present(self):
        titles = {c[2]: c[0] for c in self.cards}
        self.assertEqual(titles.get("Октаэдр"), "octa")
        self.assertEqual(titles.get("Эллипсоид"), "ellipsoid")
        self.assertEqual(titles.get("Скоба (П / U)"), "скоба")
        self.assertNotIn("Форма П", titles)
        self.assertNotIn("Форма U", titles)

    def test_card_scripts_build(self):
        """Каждая новая карточка даёт исполнимый сценарий."""
        cases = {
            "октаэдр": "октаэдр = octa radius=30 height=80",
            "эллипсоид": "эллипсоид = ellipsoid x=60 y=40 z=22",
            "скоба": "скоба = скоба length=120 width=40 height=30 wall=3 open=вверх",
            "скоба_п": "скоба_п = скоба length=120 width=40 height=30 wall=3 open=вниз",
            "лист": "лист = sheet width=120 length=200 thickness=1.2",
            "листок": "листок = leaf length=90 width=45 thickness=2",
            "шкиф": "шкиф = pulley diameter=80",
            "иньянь": "иньянь = yin_yang",
        }
        for name, script in cases.items():
            with self.subTest(name=name):
                b = build(script, analyze_model=False)
                self.assertTrue(b.ok, (b.error or {}).get("message"))


class PrimitiveShowcaseTest(unittest.TestCase):
    """Пример «Стандартные примитивы» — четырнадцать тел первого ряда."""

    def test_example_builds(self):
        from forma.webui import load_example

        script = load_example("primitives")
        b = _build(script)
        names = [n for n in b.scene.objects]
        self.assertEqual(len(names), 14)
        for name in ("лист", "куб", "призма", "октаэдр", "пирамида", "конус",
                     "цилиндр", "шар", "икосфера", "эллипсоид", "капсула",
                     "тор", "кольцо", "шайба"):
            with self.subTest(name=name):
                self.assertIn(name, names)

    def test_example_in_menu(self):
        from forma.webui import EXAMPLES, load_example

        keys = [key for _, key in EXAMPLES]
        self.assertIn("primitives", keys)
        self.assertIn("Стандартные примитивы", EXAMPLES[0][0])
        self.assertGreater(len(load_example("primitives")), 100)


class HelpAndInstructionTest(unittest.TestCase):
    """Новые тела объяснены по-русски и попали в инструкцию для ИИ."""

    def test_help_explains_new_bodies(self):
        for op in ("octa", "ellipsoid", "скоба"):
            spec = OPS[op]
            with self.subTest(op=op):
                self.assertTrue(spec.summary)
                self.assertTrue(spec.example)
                self.assertGreaterEqual(len(spec.params), 3)

    def test_instruction_lists_tiers(self):
        from forma.instruction import full_instruction

        text = full_instruction()
        self.assertIn("ПРИМИТИВЫ: ЧЕГО ХВАТАЕТ ДЛЯ ЛЮБОЙ ФОРМЫ", text)
        for word in ("стандартные тела", "производные", "природные", "готовые детали",
                     "октаэдр", "эллипсоид", "скоба", "листок"):
            with self.subTest(word=word):
                self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
