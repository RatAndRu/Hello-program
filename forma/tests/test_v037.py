"""0.37: воронка, ориентация детали и посадка по осям хозяина.

Проверки держат просьбы пользователя:

1. **воронка** — новая деталь: широкий конус, трубка-носок, сквозной канал
   и настоящая стенка; одна герметичная деталь, а не «конус минус конус»;
2. **ориентация** — после поворота видно, куда смотрят верх, низ и бока;
   команда предупреждает, что центр габарита у тора и воронки — в пустоте;
3. **относительное расположение** — зазор считается от крайней границы
   хозяина и может задаваться его длиной: `offset=length(ящик)`;
4. **оси хозяина** — `place … осями=хозяина` ставит деталь на настоящий верх
   повёрнутого предмета и разворачивает её вместе с ним;
5. **центр массы** — мерки `mx/my/mz` и `центр=масса` там, где центр габарита
   пустой;
6. **сторона у на_границе** — поиск ближайшей точки можно ограничить верхом,
   низом или боком.
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


class FunnelTest(unittest.TestCase):
    """Воронка: конус, носок и стенка."""

    def test_funnel_registered(self):
        for name in ("воронка", "funnel"):
            with self.subTest(name=name):
                self.assertIsNotNone(lookup(name))
        spec = lookup("воронка")
        for key in ("top", "bottom", "height", "wall", "spout", "lip"):
            self.assertIn(key, spec.params)

    def test_funnel_is_one_hollow_piece(self):
        b = _build("в = воронка top=120 bottom=16 height=80 spout=40 wall=3")
        part = b.scene.objects["в"]
        self.assertEqual(len(part.manifold.decompose()), 1)
        self.assertEqual(part.manifold.genus(), 1)     # канал насквозь
        self.assertGreater(part.manifold.volume(), 1000.0)
        self.assertEqual(part.manifold.status().name, "NoError")

    def test_size_follows_parameters(self):
        b = _build("в = воронка top=120 bottom=16 height=80 spout=40 wall=3 lip=0")
        w, d, h = _size(b, "в")
        self.assertAlmostEqual(w, 120.0, delta=0.15)   # дискретизация круга
        self.assertAlmostEqual(d, 120.0, delta=0.15)
        self.assertAlmostEqual(h, 120.0, delta=0.05)   # носок 40 + конус 80

    def test_lip_widens_the_top(self):
        plain = _build("в = воронка top=120 bottom=16 height=80 spout=40 wall=3 lip=0")
        lipped = _build("в = воронка top=120 bottom=16 height=80 spout=40 wall=3 lip=5")
        self.assertAlmostEqual(_size(plain, "в")[0], 120.0, delta=0.15)
        self.assertAlmostEqual(_size(lipped, "в")[0], 130.0, delta=0.15)

    def test_spout_length_adds_height(self):
        short = _build("в = воронка top=100 bottom=14 height=60 spout=10 wall=3")
        long = _build("в = воронка top=100 bottom=14 height=60 spout=50 wall=3")
        self.assertGreater(_size(long, "в")[2], _size(short, "в")[2] + 35.0)

    def test_wall_changes_material(self):
        thin = _build("в = воронка top=120 bottom=16 height=80 spout=40 wall=2")
        thick = _build("в = воронка top=120 bottom=16 height=80 spout=40 wall=4")
        self.assertGreater(_solid(thick, "в").volume(),
                           _solid(thin, "в").volume() * 1.4)

    def test_too_thick_wall_is_refused(self):
        b = build("в = воронка top=120 bottom=10 height=80 wall=6", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("канала", (b.error or {}).get("message", ""))

    def test_bottom_wider_than_top_is_refused(self):
        b = build("в = воронка top=20 bottom=40 height=50", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("носок шире", (b.error or {}).get("message", ""))

    def test_funnel_is_open_from_above(self):
        b = _build("в = воронка top=120 bottom=16 height=80 spout=40 wall=3")
        # в верхней части материал есть только у стенки: центр — пустота
        from forma.cuts import point_info
        info = point_info(_solid(b, "в"), [0.0, 0.0, 100.0])
        self.assertFalse(info["inside"])


class OrientationTest(unittest.TestCase):
    """Куда смотрит деталь после поворота."""

    def test_default_axes_point_along_world(self):
        b = _build("к = box size=[40,20,10]")
        self.assertEqual(b.scene.objects["к"].meta["axes"], np.eye(3).tolist())

    def test_rotate_turns_the_remembered_top(self):
        b = _build("к = box size=[40,20,10]\nк = rotate [к] angle=90 axis=x")
        axes = np.asarray(b.scene.objects["к"].meta["axes"])
        # локальный +Z после поворота на 90° вокруг X смотрит в −Y
        self.assertAlmostEqual(axes[1, 2], -1.0, places=6)

    def test_orientation_reports_faces_and_holes(self):
        b = _build("кольцо = torus major=40 minor=8\n"
                   "кольцо = rotate [кольцо] angle=90 axis=x\n"
                   "ориентация кольцо")
        data = b.scene.objects["кольцо"].meta["orientation"]
        self.assertEqual(data["faces"]["верх"], "−Y")
        self.assertEqual(data["faces"]["перед"], "−Z")
        self.assertTrue(data["center_empty"])       # центр тора — дырка
        self.assertEqual(data["rotation"], "повёрнута")

    def test_orientation_of_solid_box_is_not_empty(self):
        b = _build("к = box size=[40,20,10]\nориентация к")
        data = b.scene.objects["к"].meta["orientation"]
        self.assertFalse(data["center_empty"])
        self.assertEqual(data["rotation"], "нет")

    def test_orientation_can_be_set_manually(self):
        b = _build("д = box size=[30,20,10]\nориентация [д] верх=+x перед=-y")
        data = b.scene.objects["д"].meta["orientation"]
        self.assertEqual(data["faces"]["верх"], "+X")
        self.assertEqual(data["faces"]["перед"], "−Y")

    def test_orientation_needs_both_directions(self):
        b = build("д = box size=[30,20,10]\nориентация [д] верх=+x", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("вместе", (b.error or {}).get("message", ""))

    def test_axes_survive_translate_and_scale(self):
        b = _build("д = box size=[30,20,10]\n"
                   "д = rotate [д] angle=90 axis=z\n"
                   "д = translate [д] offset=[50,0,0]\n"
                   "д = scale [д] factor=2")
        axes = np.asarray(b.scene.objects["д"].meta["axes"])
        self.assertAlmostEqual(axes[0, 0], 0.0, places=6)     # +X ушёл в +Y
        self.assertAlmostEqual(axes[1, 0], 1.0, places=6)

    def test_mirror_without_keep_flips_axes(self):
        b = _build("д = box size=[30,20,10]\nд = mirror [д] plane=x keep=нет")
        axes = np.asarray(b.scene.objects["д"].meta["axes"])
        self.assertAlmostEqual(float(np.linalg.det(axes)), -1.0, places=6)


class RelativePlacementTest(unittest.TestCase):
    """Зазор от крайней границы и по чьим осям считать верх."""

    def test_gap_is_measured_from_extreme_boundary(self):
        b = _build("ящик = box size=[80,50,30]\n"
                   "ручка = cylinder radius=5 height=40\n"
                   "ручка = place [ручка] on=ящик side=left offset=length(ящик)")
        bb = _solid(b, "ручка").bounding_box()
        # ящик: x −40…40; ручка шириной 10 стоит слева через 80 мм
        self.assertAlmostEqual(bb[3], -120.0, places=3)
        self.assertAlmostEqual(bb[0], -130.0, places=3)

    def test_russian_side_names(self):
        b = _build("ящик = box size=[80,50,30]\n"
                   "крышка = cylinder radius=10 height=4\n"
                   "крышка = place [крышка] on=ящик сторона=сверху смещение=2")
        bb = _solid(b, "крышка").bounding_box()
        self.assertAlmostEqual(bb[2], 32.0, places=3)

    def test_gap_alias(self):
        b = _build("ящик = box size=[80,50,30]\n"
                   "ш = cylinder radius=5 height=4\n"
                   "ш = place [ш] on=ящик side=top gap=5")
        self.assertAlmostEqual(_solid(b, "ш").bounding_box()[2], 35.0, places=3)

    def test_host_axes_put_part_on_real_top(self):
        b = _build("корпус = box size=[140,40,40]\n"
                   "корпус = rotate [корпус] angle=90 axis=y\n"
                   "крышка = cylinder radius=18 height=6\n"
                   "крышка = place [крышка] on=корпус side=top осями=хозяина")
        bb = _solid(b, "крышка").bounding_box()
        # верх корпуса теперь смотрит в +X: после поворота корпус x 0…40
        self.assertAlmostEqual(bb[0], 40.0, places=3)
        self.assertAlmostEqual(bb[3], 46.0, places=3)
        axes = np.asarray(b.scene.objects["крышка"].meta["axes"])
        self.assertAlmostEqual(axes[0, 2], 1.0, places=6)

    def test_host_axes_without_align_keeps_part_orientation(self):
        b = _build("корпус = box size=[140,40,40]\n"
                   "корпус = rotate [корпус] angle=90 axis=x\n"
                   "ш = cylinder radius=6 height=20\n"
                   "ш = place [ш] on=корпус side=top осями=хозяина align=нет")
        self.assertAlmostEqual(_size(b, "ш")[2], 20.0, places=3)

    def test_center_by_mass_uses_material_center(self):
        b = _build("кольцо = torus major=40 minor=8 at=[0,0,60]\n"
                   "ш = cylinder radius=6 height=4\n"
                   "ш = place [ш] on=кольцо side=center центр=масса")
        bb = _solid(b, "ш").bounding_box()
        self.assertAlmostEqual((bb[2] + bb[5]) / 2.0, 60.0, places=3)

    def test_unknown_side_is_explained(self):
        b = build("ящик = box size=[80,50,30]\nш = cylinder radius=5 height=4\n"
                  "ш = place [ш] on=ящик side=наискосок", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("неизвестная сторона", (b.error or {}).get("message", ""))


class MassCenterMeasuresTest(unittest.TestCase):
    """mx/my/mz — центр массы, а не центр коробки."""

    def test_mass_center_of_torus_is_in_its_ring_plane(self):
        b = _build("к = torus major=40 minor=8\n"
                   "т = cylinder radius=4 height=6 at=[mx(к), my(к), mz(к)+20]")
        bb = _solid(b, "т").bounding_box()
        self.assertAlmostEqual((bb[0] + bb[3]) / 2.0, 0.0, places=3)
        self.assertAlmostEqual(bb[2], 20.0, places=3)

    def test_mass_center_follows_offset_body(self):
        b = _build("к = box size=[20,20,20] at=[100,0,0]\n"
                   "ш = cylinder radius=2 height=2 at=[mx(к), my(к), mz(к)]")
        bb = _solid(b, "ш").bounding_box()
        self.assertAlmostEqual((bb[0] + bb[3]) / 2.0, 100.0, places=2)

    def test_russian_mass_measure_names(self):
        b = _build("к = box size=[20,20,20] at=[30,0,0]\n"
                   "ш = cylinder radius=2 height=2 at=[центр_масс_x(к), 0, 0]")
        self.assertAlmostEqual((_solid(b, "ш").bounding_box()[0] +
                                _solid(b, "ш").bounding_box()[3]) / 2.0, 30.0, places=2)


class BoundarySideTest(unittest.TestCase):
    """на_границе можно ограничить нужной стороной."""

    def test_side_filter_searches_top_half(self):
        b = _build("к = box size=[80,80,80]\n"
                   "ш = cylinder radius=6 height=4\n"
                   "ш = на_границе [ш] on=к point=[0,0,200] сторона=верх")
        bb = _solid(b, "ш").bounding_box()
        self.assertAlmostEqual(bb[2], 80.0, places=3)

    def test_side_filter_prevents_inner_wall_of_torus(self):
        b = _build("к = torus major=40 minor=8\n"
                   "ш = cylinder radius=6 height=4\n"
                   "ш = на_границе [ш] on=к point=[0,0,200] сторона=верх offset=0")
        self.assertGreater(_solid(b, "ш").bounding_box()[2], 4.0)


class CardsExamplesTest(unittest.TestCase):
    """Карточки инструментов и примеры."""

    def test_card_exists(self):
        root = __import__("pathlib").Path(__file__).resolve().parent.parent
        app = (root / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("op: 'воронка'", app)
        self.assertIn("title: 'Деталь по осям хозяина'", app)

    def test_examples_registered(self):
        names = {e[1] if isinstance(e, (list, tuple)) else e for e in EXAMPLES}
        for key in ("funnel", "orientation"):
            with self.subTest(key=key):
                self.assertIn(key, names)

    def test_examples_build(self):
        for key in ("funnel", "orientation"):
            with self.subTest(key=key):
                b = build(load_example(key), analyze_model=False)
                self.assertTrue(b.ok, (b.error or {}).get("message"))
                self.assertGreaterEqual(len(b.scene.objects), 3)

    def test_funnel_example_has_real_funnels(self):
        b = build(load_example("funnel"), analyze_model=False)
        self.assertTrue(b.ok)
        self.assertEqual(b.scene.objects["кухонная"].manifold.genus(), 1)
        self.assertGreater(len(b.scene.objects["кухонная"].manifold.decompose()), 0)


if __name__ == "__main__":
    unittest.main()
