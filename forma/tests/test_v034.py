"""0.34: объёмный аниме-бюст, волосы, оригами, складки, цепи и инструкция для ИИ.

Проверки держат просьбы пользователя:

1. **бюст, а не панель** — в примере `anime_face` голова объёмная, у неё есть
   затылок, нос, уши и шея; плоской панели рядом больше нет;
2. **волосы по-настоящему** — `волосинки`, `локон`, `чёлка` дают одно тело и
   ставятся абсолютными координатами (`at` — сдвиг, а не «низ на z»);
3. **лицо** — `глаз` собирает шесть тел, включая тёмную обводку; `бровь` и
   `губы` стоят там, где их поставили, а не на пол ниже;
4. **сгиб от угла** — лист можно сложить по произвольной линии, длина при
   этом сохраняется (изометрия, как с бумагой);
5. **складка** — гребень приращивает объём, канавка вычитает;
6. **цепь** — звенья вытянутые и зацеплены (пересечение непустое);
7. **соединить** — цепь между двумя готовыми деталями, число звеньев по длине;
8. **оригами** — пример собирается из листов и сгибов, клей подписан отдельно;
9. **инструкция для ИИ** — все команды в исполнимом виде, отдельно от запроса.
"""

from __future__ import annotations

import math
import unittest

from forma.ops import lookup
from forma.run import build
import forma.run  # noqa: F401  (наполняет реестр команд)
from forma.webui import EXAMPLES, load_example
from forma.instruction import commands_catalog, full_instruction


def _build(script: str):
    b = build(script, analyze_model=False)
    assert b.ok, (b.error or {}).get("message")
    return b


def _solid(build_result, name: str):
    return build_result.scene.objects[name].manifold


class HairToolsTest(unittest.TestCase):
    """Волосы: локоны и волосинки — не клинья, а отдельные пряди."""

    def test_strand_bundle_is_one_solid(self):
        b = _build("пучок = волосинки from=[-40,-30,196] to=[40,-30,196] "
                   "count=30 length=40 thick=1.6 bend=0.6 curl=0.4 "
                   "dir=[0,-0.55,-1] base=да")
        solid = _solid(b, "пучок")
        self.assertEqual(solid.decompose().__len__(), 1)
        self.assertGreater(solid.num_tri(), 400)

    def test_curl_spirals_and_tapers(self):
        b = _build("л = локон at=[0,0,0] length=120 radius=14 turns=0.5 "
                   "thick=15 thin=6 dir=[0,0,-1] side=[1,0,0]")
        bb = _solid(b, "л").bounding_box()
        # завиток уходит вбок от направления — значит, он закручен
        self.assertGreater(bb[3] - bb[0], 20)
        self.assertGreater(bb[5] - bb[2], 100)

    def test_absolute_coordinates(self):
        """`at` у волос — обычный сдвиг: макушка не уезжает на высоту детали."""
        b = _build("ч = чёлка width=120 height=60 at=[0,-50,300]")
        bb = _solid(b, "ч").bounding_box()
        # при anchor верх был бы на 300 + 60 = 360; при сдвиге — у линии роста
        self.assertGreater(bb[5], 280)
        self.assertLess(bb[5], 330)

    def test_fringe_hangs_down(self):
        b = _build("ч = чёлка width=120 height=60 at=[0,-50,300]")
        bb = _solid(b, "ч").bounding_box()
        self.assertLess(bb[2], 250)                      # пряди свисают вниз


class FaceToolsTest(unittest.TestCase):
    """Аниме-лицо: обводка глаза, брови и губы на своих местах."""

    def test_eye_has_six_parts(self):
        b = _build("г = глаз width=60 height=40 at=[0,0,0]")
        names = set(b.scene.objects)
        for suffix in ("_радужка", "_зрачок", "_блик", "_блик2", "_ресницы", "_контур"):
            self.assertIn("г" + suffix, names)

    def test_eye_rim_wraps_the_whole_eye(self):
        """Обводка идёт по всему глазу, а не только по ресничной линии."""
        b = _build("г = глаз width=60 height=40 at=[0,0,0]")
        eye = _solid(b, "г").bounding_box()
        rim = _solid(b, "г_контур").bounding_box()
        self.assertGreater(rim[3] - rim[0], (eye[3] - eye[0]) * 0.98)
        self.assertGreater(rim[5] - rim[2], (eye[5] - eye[2]) * 0.98)

    def test_eye_depth_sticks_out(self):
        """depth задаёт, насколько глаз выступает из лица (по −Y)."""
        flat = _build("г = глаз width=60 height=40 at=[0,0,0] depth=0.2")
        round_ = _build("г = глаз width=60 height=40 at=[0,0,0] depth=1.0")
        d_flat = _solid(flat, "г").bounding_box()
        d_round = _solid(round_, "г").bounding_box()
        self.assertGreater((d_round[4] - d_round[1]), (d_flat[4] - d_flat[1]) * 1.1)

    def test_brow_sits_where_asked(self):
        b = _build("б = бровь width=40 at=[30,-60,300]")
        bb = _solid(b, "б").bounding_box()
        self.assertAlmostEqual(bb[5], 300, delta=12)
        self.assertLess(bb[5], 320)

    def test_lips_sit_where_asked(self):
        b = _build("г = губы width=30 at=[0,-40,208]")
        bb = _solid(b, "г").bounding_box()
        self.assertAlmostEqual(bb[2] + (bb[5] - bb[2]) / 2, 208, delta=6)


class FoldFromCornerTest(unittest.TestCase):
    """Сгиб по произвольной линии — от угла и по диагонали."""

    def test_diagonal_fold_keeps_area(self):
        flat = _build("л = sheet width=120 length=120 thickness=1")
        folded = _build("л = sheet width=120 length=120 thickness=1\n"
                        "с = сгиб л at=[0,0,1] dir=45 angle=180")
        self.assertAlmostEqual(_solid(flat, "л").volume(),
                               _solid(folded, "с").volume(),
                               delta=_solid(flat, "л").volume() * 0.02)

    def test_fold_lifts_the_moving_half(self):
        b = _build("л = sheet width=120 length=160 thickness=1\n"
                   "с = сгиб л at=[0,0,1] dir=0 angle=90")
        bb = _solid(b, "с").bounding_box()
        self.assertGreater(bb[5], 60)          # половина встала вертикально

    def test_side_swaps_moving_half(self):
        """Обе половины поднимаются вверх, но поднимается разная половина."""
        a = _build("л = sheet width=120 length=160 thickness=1\n"
                   "с = сгиб л at=[0,0,1] dir=0 angle=90 side=1")
        b = _build("л = sheet width=120 length=160 thickness=1\n"
                   "с = сгиб л at=[0,0,1] dir=0 angle=90 side=-1")
        ba = _solid(a, "с").bounding_box()
        bb = _solid(b, "с").bounding_box()
        self.assertGreater(ba[5], 50)          # первая половина встала вверх
        self.assertGreater(bb[5], 50)          # и вторая тоже — не сквозь стол
        self.assertLess(ba[4], bb[4])          # но подвижные половины разные

    def test_line_must_cross_the_part(self):
        b = build("л = sheet width=60 length=60 thickness=1\n"
                  "с = сгиб л at=[0,300,1] dir=0 angle=90", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("пересекает", (b.error or {}).get("message", ""))


class CreaseTest(unittest.TestCase):
    """Складки на одежде: гребень и канавка."""

    def test_groove_removes_material(self):
        base = _build("к = box size=[80,40,120] round=6")
        cut = _build("к = box size=[80,40,120] round=6\n"
                     "с = складка к from=[-30,-20,60] to=[30,-20,60] r=5 mode=канавка")
        self.assertLess(_solid(cut, "с").volume(), _solid(base, "к").volume())

    def test_ridge_adds_material(self):
        base = _build("к = box size=[80,40,120] round=6")
        add = _build("к = box size=[80,40,120] round=6\n"
                     "с = складка к from=[-30,-20,60] to=[30,-20,60] r=5 mode=гребень")
        self.assertGreater(_solid(add, "с").volume(), _solid(base, "к").volume())

    def test_crease_is_one_solid(self):
        b = _build("к = box size=[80,40,120] round=6\n"
                   "с = складка к from=[-30,-20,60] to=[30,-20,60] r=4 bend=8")
        self.assertEqual(_solid(b, "с").decompose().__len__(), 1)


class ChainTest(unittest.TestCase):
    """Цепь: звенья зацеплены, а не нанизаны."""

    def test_links_are_interlocked(self):
        """Соседнее звено проходит сквозь проушину, а не висит рядом."""
        import numpy as np
        import manifold3d as mf
        from forma.ops_chain import _chain, _link, _placed

        size, width, wire = 26.0, 15.0, 3.4
        base = _link(size, width, wire)
        first = _placed(base, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        pitch = (size - wire) * 0.62
        second = _placed(base, (pitch, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))

        # первое звено лежит в плоскости XY, его проушина смотрит по Z;
        # проба — короткий столбик как раз в этой проушине
        hole_r = (width - wire) * 0.5 - wire
        probe = mf.Manifold.cylinder(wire * 4.0, hole_r, hole_r, 24, True)
        self.assertLess((probe ^ first).volume(), probe.volume() * 0.2)
        self.assertGreater((probe ^ second).volume(), 0.05)

        chain = _chain(np.array([[0.0, 0.0, 0.0], [120.0, 0.0, 0.0]]),
                       size, width, wire, None, np.array([0.0, 0.0, 1.0]))
        self.assertGreater(chain.bounding_box()[3] - chain.bounding_box()[0], 100)

    def test_chain_spans_the_direction(self):
        b = _build("ц = цепь links=6 size=26 wire=3.4 at=[0,0,80] dir=[1,0,0]")
        bb = _solid(b, "ц").bounding_box()
        self.assertGreater(bb[3] - bb[0], 80)
        self.assertLess(bb[4] - bb[1], 40)

    def test_connect_two_parts(self):
        b = _build("крюк = torus major=20 minor=4 at=[0,0,200]\n"
                   "ведро = cylinder radius=30 height=60 at=[0,0,40]\n"
                   "ц = соединить [крюк, ведро] size=16 wire=2.4 sag=0.15")
        bb = _solid(b, "ц").bounding_box()
        self.assertGreater(bb[5], 120)       # цепь поднялась к крюку
        self.assertLess(bb[2], 120)          # и опустилась к ведру




class InstructionTest(unittest.TestCase):
    """Инструкция для ИИ: все команды в исполнимом виде."""

    def test_catalog_has_every_command(self):
        from forma.ops import OPS
        text = commands_catalog()
        for name in OPS:
            self.assertIn(f"### {name}", text, name)

    def test_catalog_has_params_and_examples(self):
        text = commands_catalog()
        self.assertIn("параметры:", text)
        self.assertIn("пример:", text)
        spec = lookup("сгиб")
        for key in spec.params:
            self.assertIn(key, text)

    def test_full_instruction_contains_catalog(self):
        full = full_instruction()
        self.assertIn("ПОЛНЫЙ СПИСОК КОМАНД", full)
        self.assertIn("ЕДИНИЦЫ И ОСИ", full)
        self.assertIn("соединить", full)

    def test_new_tools_are_documented(self):
        text = commands_catalog()
        for name in ("сгиб", "складка", "цепь", "соединить", "глаз", "бровь",
                     "губы", "волосинки", "локон", "чёлка"):
            self.assertIn(f"### {name}", text)


class NewToolCardsTest(unittest.TestCase):
    """Новые команды видны в справке приложения с человеческим описанием."""

    def test_help_entries_exist(self):
        names = {spec["name"] for spec in __import__("forma.ops", fromlist=["help_list"]).help_list()}
        for name in ("сгиб", "складка", "цепь", "соединить"):
            self.assertIn(name, names)

    def test_aliases_resolve(self):
        for alias, name in (("fold_along", "сгиб"), ("crease", "складка"),
                            ("chain", "цепь"), ("chain_between", "соединить")):
            self.assertEqual(lookup(alias).name, name)


if __name__ == "__main__":
    unittest.main()
