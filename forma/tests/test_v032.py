"""0.32: скульпт руками — вмятины, выдувание, щипок, стёсывание, сверление.

Проверки держат просьбы пользователя:

1. **полигонаж** — плотность сетки поднимается осознанно и не взрывается;
2. **стёсывание** — снимается ровно слой, как ножом, а не «что-то меняется»;
3. **выдувание** — объём растёт вдоль поверхности, даже если радиус по умолчанию;
4. **сверление** — отверстие с плоским дном, конусом, сферой и ступенью, сквозное;
5. **острая складка** — sharp=1 даёт ребро резче, чем обычный сгиб;
6. **вмятины** — материал уходит внутрь, валик по краю добавляет объём;
7. **разравнивание** — участок становится плоскостью;
8. **разглаживание** — шероховатость уходит, но форма не становится плоскостью;
9. **пример-проект** — аниме-портрет на плоскости собирается в один объём;
10. **щипок** — сдавливает по оси и выдавливает материал вбок;
11. **мягкость** — это параметр инструмента (soft), а не свойство объекта.
"""

from __future__ import annotations

import re
import json
import unittest
from pathlib import Path

import numpy as np

from forma.ops import help_list, lookup
from forma.run import build
import forma.run  # noqa: F401  (наполняет реестр команд)
from forma.webui import load_example

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _build(script: str):
    b = build(script, analyze_model=False)
    assert b.ok, (b.error or {}).get("message")
    return b


def _last(b):
    return list(b.scene.objects.values())[-1]


def _volume(solid) -> float:
    return float(solid.manifold.volume())


def _verts(solid) -> np.ndarray:
    mesh = solid.manifold.to_mesh()
    return np.array(mesh.vert_properties, dtype=np.float64)[:, :3]


def _error(script: str) -> dict:
    b = build(script, analyze_model=False)
    assert not b.ok, "ожидалась ошибка"
    return b.error or {}


class DentTest(unittest.TestCase):
    """Вмятина от удара: внутрь, с валиком и настраиваемой мягкостью."""

    def test_makes_a_hollow(self):
        base = _volume(_last(_build("к = box size=[60,60,60]")))
        solid = _last(_build(
            "к = box size=[60,60,60]\nк = dent [к] at=[0,0,60] depth=8 radius=18"))
        self.assertLess(_volume(solid), base - 1000)
        self.assertEqual(solid.notes[-1], "вмятина ø36 мм, глубина 8 мм")

    def test_keeps_outer_size(self):
        solid = _last(_build(
            "к = box size=[60,60,60]\nк = dent [к] at=[0,0,60] depth=8 radius=18 rim=0"))
        bb = solid.manifold.bounding_box()
        self.assertAlmostEqual(bb[5], 60.0, places=2)
        self.assertAlmostEqual(bb[0], -30.0, places=2)

    def test_soft_changes_the_profile(self):
        hard = _volume(_last(_build(
            "к = box size=[60,60,60]\nк = dent [к] at=[0,0,60] depth=8 radius=18 soft=0")))
        soft = _volume(_last(_build(
            "к = box size=[60,60,60]\nк = dent [к] at=[0,0,60] depth=8 radius=18 soft=1")))
        self.assertGreater(abs(hard - soft), 200)

    def test_rim_adds_metal_around_the_edge(self):
        plain = _volume(_last(_build(
            "к = box size=[60,60,60]\nк = dent [к] at=[0,0,60] depth=8 radius=18 rim=0")))
        rimmed = _volume(_last(_build(
            "к = box size=[60,60,60]\nк = dent [к] at=[0,0,60] depth=8 radius=18 rim=1")))
        self.assertGreater(rimmed, plain + 50)

    def test_mesh_is_refined_under_the_spot(self):
        plain = _last(_build("к = box size=[60,60,60]"))
        dented = _last(_build(
            "к = box size=[60,60,60]\nк = dent [к] at=[0,0,60] depth=8 radius=18"))
        self.assertGreater(dented.manifold.num_tri(), plain.manifold.num_tri() * 5)

    def test_alias_works(self):
        solid = _last(_build("к = box size=[40,40,40]\nк = вмятина [к] depth=4 radius=10"))
        self.assertGreater(solid.manifold.num_tri(), 100)


class BlowTest(unittest.TestCase):
    """Выдувание: поверхность уходит наружу вдоль своих нормалей."""

    def test_grows_the_volume_by_default(self):
        base = _volume(_last(_build("ш = sphere radius=30 segments=40")))
        blown = _volume(_last(_build("ш = sphere radius=30 segments=40\nш = blow [ш] height=12")))
        self.assertGreater(blown, base * 1.05)

    def test_local_spot_does_not_touch_the_far_side(self):
        b = _build("ш = sphere radius=30 segments=40\n"
                   "ш = blow [ш] at=[0,0,30] radius=14 height=10")
        solid = _last(b)
        bb = solid.manifold.bounding_box()
        self.assertAlmostEqual(bb[2], -30.0, delta=1.0)   # низ не тронут
        self.assertGreater(bb[5], 32.0)                   # верх выдут

    def test_normals_not_rays_from_a_point(self):
        """Цилиндр надувается бочкой: растёт и вбок, и вверх."""
        solid = _last(_build(
            "ц = cylinder radius=18 height=70 segments=48\n"
            "ц = blow [ц] at=[0,0,70] radius=46 height=10"))
        bb = solid.manifold.bounding_box()
        self.assertGreater(bb[3], 19.0)

    def test_alias_works(self):
        solid = _last(_build("ш = sphere radius=20 segments=32\nш = выдуть [ш] height=6"))
        self.assertTrue(solid.notes[-1].startswith("выдувание"))


class PinchTest(unittest.TestCase):
    """Щипок: сжали по оси — материал вышел вбок."""

    def test_squeezes_one_axis_and_bulges_the_others(self):
        base = _last(_build("ш = sphere radius=30 segments=40"))
        pinched = _last(_build(
            "ш = sphere radius=30 segments=40\nш = pinch [ш] axis=x amount=0.5 radius=120 bulge=1"))
        b0, b1 = base.manifold.bounding_box(), pinched.manifold.bounding_box()
        self.assertLess(b1[3] - b1[0], b0[3] - b0[0] - 15)     # по X сжалось
        self.assertGreater(b1[4] - b1[1], b0[4] - b0[1] + 10)  # по Y выдавило

    def test_volume_is_roughly_kept(self):
        base = _volume(_last(_build("ш = sphere radius=30 segments=48")))
        pinched = _volume(_last(_build(
            "ш = sphere radius=30 segments=48\nш = pinch [ш] axis=z amount=0.3 radius=18")))
        self.assertLess(abs(pinched - base) / base, 0.2)


class FlattenTest(unittest.TestCase):
    """Разравнивание: участок подтягивается к плоскости."""

    def test_top_becomes_flat(self):
        sharp = _last(_build("ш = sphere radius=30 segments=64"))
        flat = _last(_build(
            "ш = sphere radius=30 segments=64\nш = flatten [ш] at=[0,0,22] radius=26 strength=1"))
        z_sharp = _verts(sharp)[:, 2]
        z_flat = _verts(flat)[:, 2]
        top = z_flat.max()
        self.assertAlmostEqual(top, 22.5, delta=1.0)      # срезали макушку
        self.assertLess(_volume(flat), _volume(sharp))
        self.assertGreater(np.count_nonzero(np.abs(z_flat - top) < 0.05),
                           np.count_nonzero(np.abs(z_sharp - z_sharp.max()) < 0.05) + 20)

    def test_strength_zero_keeps_the_shape(self):
        base = _volume(_last(_build("ш = sphere radius=30 segments=40")))
        solid = _volume(_last(_build(
            "ш = sphere radius=30 segments=40\nш = flatten [ш] at=[0,0,30] strength=0")))
        self.assertAlmostEqual(solid, base, delta=base * 0.01)


class PolishTest(unittest.TestCase):
    """Разглаживание: убирает шероховатость, но не делает плоскостью."""

    def test_removes_roughness(self):
        rough = _last(_build(
            "к = sphere radius=30 segments=48\nк = wrinkle [к] amp=0.8 freq=40 mode=шум"))
        smooth = _last(_build(
            "к = sphere radius=30 segments=48\nк = wrinkle [к] amp=0.8 freq=40 mode=шум\n"
            "к = polish [к] passes=12 strength=1"))

        def rough_index(solid):
            v = _verts(solid)
            r = np.linalg.norm(v, axis=1)
            return float(np.std(r))

        self.assertLess(rough_index(smooth), rough_index(rough) * 0.85)

    def test_keeps_the_volume(self):
        base = _volume(_last(_build("ш = sphere radius=30 segments=48")))
        solid = _volume(_last(_build(
            "ш = sphere radius=30 segments=48\nш = polish [ш] passes=4 strength=0.7")))
        self.assertLess(abs(solid - base) / base, 0.03)

    def test_not_a_plane(self):
        """После разглаживания шар остаётся шаром, а не лепёшкой."""
        solid = _last(_build("ш = sphere radius=30 segments=48\nш = polish [ш] passes=8"))
        bb = solid.manifold.bounding_box()
        self.assertGreater(bb[5] - bb[2], 50)

    def test_alias_works(self):
        solid = _last(_build("ш = sphere radius=20 segments=24\nш = разгладить [ш] passes=2"))
        self.assertIn("сглажено", solid.notes[-1])


class ShaveTest(unittest.TestCase):
    """shave — открытая канавка; полное отсечение — отдельный cut_plane."""

    def test_cut_plane_whole_surface_layer(self):
        solid = _last(_build(
            "ц = cylinder radius=20 height=60 segments=96\nц = cut_plane [ц] depth=10"))
        self.assertAlmostEqual(_volume(solid), np.pi * 400 * 50, delta=np.pi * 400 * 0.6)

    def test_round_spot_is_open_groove(self):
        base = _last(_build("ц = cylinder radius=20 height=60 segments=96"))
        solid = _last(_build(
            "ц = cylinder radius=20 height=60 segments=96\n"
            "ц = shave [ц] depth=0 radius=8 groove=овальная groove_width=3 groove_depth=1"))
        self.assertLess(_volume(solid), _volume(base))
        self.assertAlmostEqual(solid.manifold.bounding_box()[5], 60.0, delta=1e-6)
        self.assertEqual(len([p for p in solid.manifold.decompose() if p.volume() > 1e-6]), 1)
        self.assertFalse(any(p.volume() < -1e-6 for p in solid.manifold.decompose()))

    def test_angled_cut_is_not_horizontal(self):
        solid = _last(_build(
            "б = box size=[60,60,60]\nб = cut_plane [б] at=[0,0,60] dir=[0.6,0,1] depth=6"))
        self.assertGreater(solid.manifold.num_tri(), 12)

    def test_alias_works(self):
        solid = _last(_build("б = box size=[50,50,50]\nб = стесать [б] depth=5"))
        self.assertIn("сдвиг плоскости 5 мм", solid.notes[-1])
        self.assertAlmostEqual(solid.manifold.bounding_box()[5], 50.0, delta=1e-6)

    def test_cut_alias_works(self):
        solid = _last(_build("б = box size=[50,50,50]\nб = стесать_углы [б] depth=5"))
        self.assertIn("отсечение плоскостью", solid.notes[-1])
        self.assertAlmostEqual(solid.manifold.bounding_box()[5], 45.0, delta=1e-6)


class PointTest(unittest.TestCase):
    """Заострение: конус снимается, вершина встаёт на прежний торец."""

    def test_cone_volume(self):
        solid = _last(_build(
            "к = cylinder radius=10 height=80 segments=96\nк = point [к] length=24"))
        expected = np.pi * 100 * (80 - 24) + np.pi * 100 * 24 / 3.0
        self.assertAlmostEqual(_volume(solid), expected, delta=expected * 0.01)

    def test_tip_stays_at_the_same_height(self):
        solid = _last(_build(
            "к = cylinder radius=10 height=80 segments=96\nк = point [к] length=24"))
        bb = solid.manifold.bounding_box()
        self.assertAlmostEqual(bb[5], 80.0, places=2)
        top = _verts(solid)
        top = top[np.abs(top[:, 2] - 80.0) < 0.2]
        self.assertLess(float(np.max(np.linalg.norm(top[:, :2], axis=1))), 1.0)

    def test_alias_works(self):
        solid = _last(_build("к = cylinder radius=6 height=40\nк = заострить [к] length=10"))
        self.assertTrue(solid.notes[-1].startswith("конус 10"))


class BoreTest(unittest.TestCase):
    """Сверление: дно нужной формы и сквозное отверстие."""

    PLATE = "п = box size=[70,60,20]\n"
    FULL = 70 * 60 * 20

    def test_flat_bottom(self):
        solid = _last(_build(self.PLATE + "п = bore [п] at=[0,0,20] diameter=14 depth=12"))
        self.assertAlmostEqual(_volume(solid), self.FULL - np.pi * 49 * 12, delta=40)

    def test_cone_bottom_is_deeper(self):
        flat = _volume(_last(_build(self.PLATE + "п = bore [п] at=[0,0,20] diameter=14 depth=12")))
        cone = _volume(_last(_build(
            self.PLATE + "п = bore [п] at=[0,0,20] diameter=14 depth=12 tip=конус")))
        self.assertLess(cone, flat - 200)

    def test_sphere_bottom(self):
        flat = _volume(_last(_build(self.PLATE + "п = bore [п] at=[0,0,20] diameter=14 depth=12")))
        ball = _volume(_last(_build(
            self.PLATE + "п = bore [п] at=[0,0,20] diameter=14 depth=12 tip=сфера")))
        self.assertLess(ball, flat - 500)

    def test_step_bottom(self):
        solid = _last(_build(
            self.PLATE + "п = bore [п] at=[0,0,20] diameter=14 depth=8 tip=ступень step=7"))
        hole = _volume(solid)
        self.assertLess(hole, self.FULL - np.pi * 49 * 8 - 100)      # глубже плоского
        self.assertGreater(hole, self.FULL - np.pi * 49 * 8 - 1500)  # но не насквозь

    def test_through_hole(self):
        solid = _last(_build(self.PLATE + "п = bore [п] at=[0,0,20] diameter=10 through=true"))
        self.assertGreaterEqual(solid.manifold.genus(), 1)
        self.assertAlmostEqual(_volume(solid), self.FULL - np.pi * 25 * 20, delta=60)

    def test_countersink_widens_the_entry(self):
        plain = _last(_build(self.PLATE + "п = bore [п] at=[0,0,20] diameter=12 depth=8"))
        sink = _last(_build(
            self.PLATE + "п = bore [п] at=[0,0,20] diameter=12 depth=8 countersink=4"))
        self.assertLess(_volume(sink), _volume(plain) - 100)

        def entry(solid):
            """Радиус входной кромки на верхней плоскости."""
            v = _verts(solid)
            r = np.hypot(v[:, 0], v[:, 1])
            return float(np.max(r[(np.abs(v[:, 2] - 20.0) < 0.01) & (r < 13)]))

        self.assertAlmostEqual(entry(plain), 6.0, delta=0.1)
        self.assertGreater(entry(sink), 8.5)

    def test_side_hole(self):
        solid = _last(_build(
            "п = box size=[40,40,80]\nп = bore [п] at=[0,0,80] dir=[0,-1,0] diameter=10 depth=30"))
        self.assertGreater(solid.manifold.num_tri(), 20)

    def test_too_big_hole_is_explained(self):
        err = _error(self.PLATE + "п = bore [п] at=[0,0,20] diameter=200 depth=25")
        self.assertIn("уменьшите", err["message"].lower())


class RefineTest(unittest.TestCase):
    """Полигонаж: плотность растёт предсказуемо и с ограничением."""

    def test_density_grows(self):
        base = _last(_build("ш = sphere radius=30 segments=12"))
        fine = _last(_build("ш = sphere radius=30 segments=12\nш = refine [ш] length=2"))
        self.assertGreater(fine.manifold.num_tri(), base.manifold.num_tri() * 20)
        self.assertIn("→", fine.notes[-1])

    def test_levels(self):
        base = _last(_build("ш = sphere radius=30 segments=12"))
        fine = _last(_build("ш = sphere radius=30 segments=12\nш = refine [ш] levels=2"))
        self.assertGreater(fine.manifold.num_tri(), base.manifold.num_tri())

    def test_absurd_density_is_refused_with_a_hint(self):
        err = _error("ш = sphere radius=200 segments=64\nш = refine [ш] length=0.05")
        self.assertIn("полигонаж", err["message"].lower())
        self.assertIn("length", err["hint"].lower())

    def test_polygon_alias(self):
        fine = _last(_build("ш = sphere radius=20 segments=8\nш = полигонаж [ш] length=3"))
        self.assertGreater(fine.manifold.num_tri(), 50)


class FoldSharpTest(unittest.TestCase):
    """Острая складка: у sharp=1 ребро резче, слои лежат плотнее."""

    def test_sharp_fold_is_tighter(self):
        round_fold = _last(_build(
            "л = sheet width=120 length=200 thickness=1\n"
            "fold л parts=2 angle=180 gap=6"))
        sharp_fold = _last(_build(
            "л = sheet width=120 length=200 thickness=1\n"
            "fold л parts=2 angle=180 gap=6 sharp=1"))
        h_round = round_fold.manifold.bounding_box()[5]
        h_sharp = sharp_fold.manifold.bounding_box()[5]
        self.assertLess(h_sharp, h_round - 2)

    def test_sharp_fold_still_holds_its_volume(self):
        b = _build("л = sheet width=120 length=200 thickness=1\n"
                   "fold л parts=2 angle=90 gap=2 sharp=1")
        solid = _last(b)
        self.assertGreater(_volume(solid), 120 * 200 * 1 * 0.98)


class HelpTest(unittest.TestCase):
    """У новых инструментов есть справка и понятные параметры."""

    def test_registry_has_the_sculpt_tools(self):
        help_list()  # наполняет реестр
        names = {item["name"] for item in help_list()}
        for name in ("dent", "blow", "pinch", "flatten", "polish",
                     "shave", "point", "bore"):
            self.assertIn(name, names)

    def test_help_explains_soft_and_rim(self):
        item = [i for i in help_list() if i["name"] == "dent"][0]
        keys = [p["name"] for p in item["params"]]
        self.assertIn("soft", keys)
        self.assertIn("rim", keys)
        self.assertIn("мягкость", item["summary"].lower())
        self.assertTrue(item["example"])

    def test_aliases_resolve(self):
        for alias, name in (("вмятина", "dent"), ("выдуть", "blow"), ("щипок", "pinch"),
                            ("разровнять", "flatten"), ("разгладить", "polish"),
                            ("стесать", "shave"), ("заострить", "point"),
                            ("сверло", "bore"), ("полигонаж", "refine")):
            self.assertEqual(lookup(alias).name, name)


class SoftnessIsAToolTest(unittest.TestCase):
    """Мягкость — параметр инструмента: один объект можно обработать по-разному."""

    def test_same_object_two_softness_values(self):
        script = (
            "к = box size=[60,60,60]\n"
            "жёсткая = dent [к] at=[-15,0,60] depth=6 radius=14 soft=0.1 rim=1\n"
            "к = box size=[60,60,60]\n"
            "мягкая = dent [к] at=[15,0,60] depth=6 radius=14 soft=0.9 rim=0\n")
        b = _build(script)
        self.assertIn("жёсткая", b.scene.objects)
        self.assertIn("мягкая", b.scene.objects)


class AnimeExampleTest(unittest.TestCase):
    """Пример-проект: аниме-бюст — объёмный, а не плоская панель."""

    @classmethod
    def setUpClass(cls):
        cls.text = load_example("anime_face")
        cls.build = build(cls.text, analyze_model=False)

    def _figure(self):
        for solid in self.build.scene.visible_solids():
            if solid.name == "фигура":
                return solid
        self.fail("в примере нет объёма «фигура»")

    def test_builds(self):
        self.assertTrue(self.build.ok, (self.build.error or {}).get("message"))

    def test_is_a_volume_not_a_plaque(self):
        bust = self._figure().manifold.bounding_box()
        head = self.build.scene.objects["голова"].manifold.bounding_box()
        # у головы глубина (затылок ↔ нос) сравнима с шириной: это объём
        head_w = head[3] - head[0]
        head_d = head[4] - head[1]
        self.assertGreater(head_d, head_w * 0.85)
        # а весь бюст высокий: голова, шея и плечи
        self.assertGreater(bust[5] - bust[2], 300)

    def test_head_neck_and_body_are_one_solid(self):
        figure = self._figure()
        # голова, шея и плечи сварены: части считаются по отдельным телам
        self.assertLessEqual(figure.manifold.decompose().__len__(), 2)

    def test_has_hair_and_face_parts(self):
        names = set(self.build.scene.objects)
        for part in ("голова", "тело", "волосы", "чёлка", "глаз_п", "губы"):
            self.assertIn(part, names)

    def test_has_anime_style_and_paper(self):
        style = (self.build.scene.settings or {}).get("anime") or {}
        self.assertEqual(style.get("mode"), "скетч")

    def test_listed_in_examples(self):
        from forma.webui import EXAMPLES
        self.assertIn("anime_face", [key for _title, key in EXAMPLES])


class ToolCardsTest(unittest.TestCase):
    """Карточки в «Инструментах»: группа «Скульпт» и живые миниатюры."""

    @classmethod
    def setUpClass(cls):
        cls.js = (WEB / "js" / "app.js").read_text(encoding="utf-8")

    def test_group_exists(self):
        self.assertIn("group: 'Скульпт'", self.js)

    def test_cards_for_every_tool(self):
        for op in ("dent", "blow", "pinch", "flatten", "polish",
                   "shave", "point", "bore", "refine"):
            self.assertRegex(self.js, r"op: '%s', name: '[^']+', title: '[^']+', group: 'Скульпт'" % op)

    def test_dent_card_has_soft_and_rim(self):
        block = self.js[self.js.index("op: 'dent', name:"):]
        block = block[:block.index("\n  },\n  {")]
        self.assertIn("'soft'", block)
        self.assertIn("'rim'", block)

    def test_preview_scripts_are_valid(self):
        """Каждая карточка «Скульпта» строит деталь для миниатюры."""
        cards = re.findall(
            r"op: '(\w+)', name: '([^']+)', title: '[^']+', group: 'Скульпт',\s*\n"
            r"\s*base: '([^']+)', baseName: '([^']+)',(.*?)\n  \}", self.js, re.S)
        self.assertGreaterEqual(len(cards), 9)
        for op, name, base, base_name, rest in cards:
            params = re.findall(r"\{ k: '(\w+)', label: '[^']+', v: ('[^']*'|[\d.]+)", rest)
            values = []
            for k, v in params:
                value = v.strip(chr(39))
                # Повторяем shapeParams: числовые vec-поля карточки
                # сериализуются как at=[x,y,z], а не как три токена.
                if "," in value and all(part.strip().replace(".", "", 1).replace("-", "", 1).isdigit()
                                       for part in value.split(",")):
                    value = f"[{value}]"
                values.append(f"{k}={value}")
            tail = " ".join(values)
            script = f"{base_name} = {base}\n{name} = {op} {base_name} {tail}"
            b = build(script, analyze_model=False)
            self.assertTrue(b.ok, f"{op}: {(b.error or {}).get('message')}")

    def test_fold_card_exposes_sharp(self):
        block = self.js[self.js.index("op: 'fold', name:"):]
        block = block[:block.index("\n  },\n  {")]
        self.assertIn("'sharp'", block)


class DetailTest(unittest.TestCase):
    """Степень детализации примитива: ползунок 0…5 вместо числа сегментов."""

    CASES = {
        "sphere": "ш = sphere radius=50",
        "cylinder": "ц = cylinder radius=40 height=100",
        "cone": "к = cone radius=45 height=90",
        "torus": "т = torus major=55 minor=12",
        "capsule": "к = capsule radius=18 height=90",
        "box": "к = box size=[120,80,60] round=6",
    }

    def _tris(self, op, tail):
        return int(_last(_build(f"{self.CASES[op]} {tail}")).manifold.num_tri())

    def test_detail_grows_the_mesh(self):
        for op in self.CASES:
            low = self._tris(op, "detail=0")
            high = self._tris(op, "detail=5")
            self.assertGreater(high, low * 2, f"{op}: {low} → {high} трис")

    def test_default_is_ordinary_detail(self):
        for op in ("sphere", "cylinder", "torus"):
            plain = _last(_build(f"{self.CASES[op]}")).manifold.num_tri()
            self.assertEqual(plain, self._tris(op, "detail=3"), op)

    def test_shape_stays_the_same(self):
        """Детализация меняет число граней, но не размер и не объём."""
        for op in ("sphere", "cylinder", "box"):
            coarse = _last(_build(f"{self.CASES[op]} detail=1"))
            fine = _last(_build(f"{self.CASES[op]} detail=5"))
            a, b2 = coarse.manifold.bounding_box(), fine.manifold.bounding_box()
            for i in range(6):
                self.assertAlmostEqual(a[i], b2[i], delta=0.6, msg=op)
            va, vb = _volume(coarse), _volume(fine)
            self.assertLess(abs(va - vb) / va, 0.03, op)

    def test_level_out_of_range_is_explained(self):
        err = _error("ш = sphere radius=20 detail=9")
        self.assertIn("detail", json.dumps(err, ensure_ascii=False))
        self.assertIn("0…5", err.get("message", ""))

    def test_cylinder_is_faceted_on_purpose(self):
        """detail=0 — гранёный бок: восьмиугольник вместо сотни граней."""
        tri = self._tris("cylinder", "detail=0")
        self.assertLess(tri, 120)
        self.assertGreaterEqual(tri, 32)

    def test_still_report_triangles(self):
        """Число треугольников у карточки — настоящее, из сборки."""
        for op in ("sphere", "torus"):
            solid = _last(_build(f"{self.CASES[op]} detail=4"))
            self.assertGreater(solid.manifold.num_tri(), 1000)


class DetailCardsTest(unittest.TestCase):
    """Ползунок и подпись «сколько трисов» в карточках интерфейса."""

    @classmethod
    def setUpClass(cls):
        cls.js = (WEB / "js" / "app.js").read_text(encoding="utf-8")
        cls.css = (WEB / "css" / "app.css").read_text(encoding="utf-8")

    def _card(self, op):
        start = self.js.index(f"op: '{op}', name: '")
        return self.js[start:self.js.index("\n  },\n  {", start)]

    def test_slider_rendering_exists(self):
        self.assertIn("kind === 'slider'", self.js)
        self.assertIn("input.type = 'range'", self.js)
        self.assertIn(".tool-field.tool-field-slider", self.css)

    def test_primitives_have_the_slider(self):
        for op in ("box", "sphere", "cylinder", "cone", "torus", "capsule"):
            block = self._card(op)
            self.assertIn("detailParam(", block, op)
        self.assertIn("'detail', label: 'детализация'", self.js)

    def test_icosphere_level_is_a_slider(self):
        self.assertIn("kind: 'slider'", self._card("icosphere"))

    def test_triangle_badge_is_filled_from_the_preview(self):
        self.assertIn("className = 'tool-tris'", self.js)
        self.assertIn("showToolTris(card, info)", self.js)
        self.assertIn("res.tris", self.js)
        self.assertIn(".tool-tris", self.css)

    def test_primitive_scripts_with_detail_build(self):
        for op in ("box", "sphere", "cylinder", "cone", "torus", "capsule"):
            name = self._card(op).split("name: '", 1)[1].split("'", 1)[0]
            b = build(f"{name} = {op} {_card_tail(self._card(op))}".strip(),
                      analyze_model=False)
            self.assertTrue(b.ok, f"{op}: {(b.error or {}).get('message')}")


def _card_tail(block: str) -> str:
    """Собирает значения полей карточки так, как это делает интерфейс."""
    parts = []
    for k, v in re.findall(r"\{ k: '([\w]+)', label: '[^']*', v: ('[^']*'|[\d.]+)", block):
        v = v.strip("'")
        if not v:
            continue  # auto: пустое поле интерфейс не добавляет в команду
        parts.append(f"{k}=[{v}]" if "," in v else f"{k}={v}")
    return " ".join(parts)


if __name__ == "__main__":
    unittest.main()
