"""0.36: крюк, полуовал и посадка на настоящую границу детали.

Проверки держат просьбы пользователя:

1. **крюк** — одна непрерывная деталь без ушка: хвостик, соединитель
   и дуга; загиб задаётся углом, свободный кончик — капсулой или остриём;
2. **полуовал** — пластина с прямой кромкой и дугой; отверстие по центру
   есть или его нет (`hole=0`), слишком большое отверстие подрезается,
   чтобы не выйти за кромку;
3. **посадка на границу** — `на_границе` находит настоящую поверхность,
   а не центр габарита: шайба садится на кольцо тора, шарик — на его бок,
   деталь встаёт на верх куба; `align=нормаль` разворачивает по нормали;
4. **карточки и примеры** — у обоих примитивов есть миниатюра в инструментах,
   есть рецепт «Деталь на границу», примеры собираются.
"""

from __future__ import annotations

import math
import unittest

import manifold3d as mf
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


class HookTest(unittest.TestCase):
    """Крюк: непрерывная дуга и хвостик без отдельного ушка."""

    def test_hook_registered_with_aliases(self):
        for name in ("крюк", "крючок", "hook"):
            with self.subTest(name=name):
                self.assertIsNotNone(lookup(name))
        spec = lookup("крюк")
        self.assertEqual(spec.name, "крюк")
        self.assertIn("без кольца", spec.summary)
        self.assertIn("open", spec.params)

    def test_hook_is_one_solid_piece(self):
        b = _build("к = крюк wire=6 radius=22 length=70 open=240")
        part = b.scene.objects["к"]
        self.assertEqual(len(part.manifold.decompose()), 1)
        self.assertFalse(part.manifold.is_empty())
        self.assertGreater(part.manifold.volume(), 1000.0)
        self.assertEqual(part.manifold.status(), mf.Error.NoError)

    def test_hook_has_no_eye_and_tip_changes_end(self):
        capsule = _build("к = крюк wire=6 radius=22 length=70 open=240 tip=капсула")
        sharp = _build("к = крюк wire=6 radius=22 length=70 open=240 tip=острый")
        self.assertEqual(_solid(capsule, "к").genus(), 0)
        self.assertEqual(_solid(sharp, "к").genus(), 0)
        self.assertLess(_solid(sharp, "к").volume(), _solid(capsule, "к").volume())
        rejected = build("к = крюк eye=да", analyze_model=False)
        self.assertFalse(rejected.ok)
        self.assertIn("eye", (rejected.error or {}).get("message", ""))

    def test_bend_angle_changes_reach(self):
        # загиб на 90° уводит конец вверх, на 180° — вбок: размах больше
        quarter = _build("к = крюк radius=18 length=70 open=90")
        half = _build("к = крюк radius=18 length=70 open=180")
        self.assertGreater(_size(half, "к")[0], _size(quarter, "к")[0] + 15.0)

    def test_length_grows_upward(self):
        low = _build("к = крюк radius=20 length=50 open=240")
        high = _build("к = крюк radius=20 length=130 open=240")
        self.assertGreater(_size(high, "к")[2], _size(low, "к")[2] + 70.0)
        # низ остаётся на полу: крюк стоит на z=0, а не висит в воздухе
        self.assertAlmostEqual(_solid(low, "к").bounding_box()[2], 0.0, places=3)

    def test_wire_controls_thickness(self):
        thin = _build("к = крюк wire=3 radius=20 length=60")
        thick = _build("к = крюк wire=12 radius=20 length=60")
        self.assertGreater(_size(thick, "к")[1], _size(thin, "к")[1] * 3.0)

    def test_zero_tail_keeps_the_hook_arc(self):
        b = _build("к = крюк length=0")
        self.assertEqual(len(_solid(b, "к").decompose()), 1)
        self.assertGreater(_solid(b, "к").volume(), 0.0)
        self.assertEqual(_solid(b, "к").genus(), 0)


class HalfOvalTest(unittest.TestCase):
    """Полуовал: пластина с отверстием или без."""

    def test_half_oval_registered_with_aliases(self):
        for name in ("полуовал", "полуэллипс", "half_oval"):
            with self.subTest(name=name):
                self.assertIsNotNone(lookup(name))
        spec = lookup("полуовал")
        self.assertIn("отверстие", spec.summary)
        self.assertIn("hole", spec.params)

    def test_size_follows_width_and_height(self):
        # с 0.41 полуовал стоит: X — ширина, Y — толщина, Z — высота
        b = _build("п = полуовал width=90 height=55 thickness=8 hole=0")
        w, d, h = _size(b, "п")
        self.assertAlmostEqual(w, 90.0, delta=0.05)
        self.assertAlmostEqual(d, 8.0, delta=0.05)
        self.assertAlmostEqual(h, 55.0, delta=0.05)
        # плашмя лежит, как раньше
        flat = _build("п = полуовал width=90 height=55 thickness=8 hole=0 plane=плашмя")
        fw, fd, fh = _size(flat, "п")
        self.assertAlmostEqual(fd, 55.0, delta=0.05)
        self.assertAlmostEqual(fh, 8.0, places=3)

    def test_half_oval_is_one_piece_on_the_floor(self):
        b = _build("п = полуовал width=90 height=55 thickness=8 hole=0")
        part = b.scene.objects["п"]
        self.assertEqual(len(part.manifold.decompose()), 1)
        self.assertAlmostEqual(part.manifold.bounding_box()[2], 0.0, places=3)

    def test_hole_is_optional_and_through(self):
        solid = _build("п = полуовал width=90 height=55 thickness=8 hole=0")
        holed = _build("п = полуовал width=90 height=55 thickness=8 hole=16")
        self.assertEqual(_solid(solid, "п").genus(), 0)
        self.assertEqual(_solid(holed, "п").genus(), 1)
        # отверстие сквозное: объём уменьшился примерно на цилиндр Ø16
        cut = 2.0 * (16.0 / 2.0) ** 2 * 8.0
        lost = _solid(solid, "п").volume() - _solid(holed, "п").volume()
        self.assertGreater(lost, cut * 0.7)
        self.assertLess(lost, cut * 2.0)

    def test_hole_is_trimmed_to_the_edge(self):
        b = _build("п = полуовал width=60 height=60 thickness=6 hole=55")
        warns = [l for l in b.scene.logs if l["level"] == "warn"]
        self.assertTrue(any("уменьшено" in l["message"] for l in warns))
        self.assertEqual(_solid(b, "п").genus(), 1)

    def test_thickness_and_center(self):
        thin = _build("п = полуовал width=80 height=40 thickness=2 hole=0")
        thick = _build("п = полуовал width=80 height=40 thickness=20 hole=0")
        self.assertGreater(_size(thick, "п")[1], _size(thin, "п")[1] + 17.0)


class BoundaryPlacementTest(unittest.TestCase):
    """«Не от центра тора, а от кольца»: настоящая поверхность."""

    def test_snaps_to_outer_edge_of_ring(self):
        b = _build("т = torus major=40 minor=8 at=[0,0,40]\n"
                   "ш = cylinder radius=6 height=4\n"
                   "ш = на_границе [ш] on=т point=[60,0,40] offset=1 align=нормаль")
        bb = _solid(b, "ш").bounding_box()
        # внешняя кромка кольца — радиус 48; шайба начинается в 1 мм от неё
        self.assertGreater(bb[0], 48.0)
        self.assertLess(bb[0], 52.0)
        self.assertLess(bb[3], 62.0)
        self.assertAlmostEqual((bb[2] + bb[5]) / 2.0, 40.0, delta=3.0)

    def test_without_align_part_keeps_upright(self):
        b = _build("т = torus major=40 minor=8 at=[0,0,40]\n"
                   "ш = cylinder radius=6 height=8\n"
                   "ш = на_границе [ш] on=т point=[60,0,40]")
        w, _d, h = _size(b, "ш")
        self.assertAlmostEqual(h, 8.0, places=3)   # высота цилиндра не изменилась
        self.assertAlmostEqual(w, 12.0, places=3)

    def test_inner_edge_of_ring(self):
        b = _build("т = torus major=40 minor=8 at=[0,0,40]\n"
                   "в = cylinder radius=4 height=10\n"
                   "в = на_границе [в] on=т point=[0,0,40]")
        bb = _solid(b, "в").bounding_box()
        cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
        # центр детали — в 4 мм от внутренней стенки радиусом 32
        self.assertAlmostEqual(math.hypot(cx, cy), 28.0, delta=1.2)

    def test_snaps_to_top_of_box(self):
        # полуовал лежит плашмя, чтобы «на границе» прижимало его плоскостью
        b = _build("к = box size=[80,80,80]\n"
                   "н = полуовал width=40 height=20 thickness=4 hole=0 plane=плашмя\n"
                   "н = на_границе [н] on=к point=[0,0,100] offset=0.5")
        bb = _solid(b, "н").bounding_box()
        self.assertAlmostEqual(bb[2], 80.5, places=3)
        self.assertAlmostEqual(bb[5], 84.5, places=3)

    def test_offset_and_at(self):
        b = _build("к = box size=[80,80,80]\n"
                   "ш = cylinder radius=5 height=4\n"
                   "ш = на_границе [ш] on=к point=[0,0,100] offset=10 at=[100,0,0]")
        bb = _solid(b, "ш").bounding_box()
        self.assertAlmostEqual(bb[2], 90.0, places=3)
        self.assertAlmostEqual((bb[0] + bb[3]) / 2.0, 100.0, places=3)

    def test_alignment_rotates_the_part(self):
        upright = _build("к = box size=[80,80,80]\n"
                         "ш = cylinder radius=5 height=20\n"
                         "ш = на_границе [ш] on=к point=[60,0,40]")
        turned = _build("к = box size=[80,80,80]\n"
                        "ш = cylinder radius=5 height=20\n"
                        "ш = на_границе [ш] on=к point=[60,0,40] align=нормаль")
        self.assertAlmostEqual(_size(upright, "ш")[2], 20.0, places=3)
        self.assertAlmostEqual(_size(turned, "ш")[0], 20.0, places=3)

    def test_keeps_material_and_replaces_the_part(self):
        b = _build("т = torus major=40 minor=8 at=[0,0,40]\n"
                   "ш = cylinder radius=6 height=4\n"
                   "color ш color=#ff0000 metal=0.8 rough=0.2\n"
                   "ш = на_границе [ш] on=т point=[60,0,40]")
        self.assertEqual(len(b.scene.objects), 2)          # старой копии нет
        self.assertEqual(b.scene.objects["ш"].color.lower(), "#ff0000")
        self.assertAlmostEqual(b.scene.objects["ш"].metal, 0.8, places=3)
        self.assertEqual(b.scene.objects["ш"].kind, "на_границе")

    def test_notes_name_the_host_and_point(self):
        b = _build("т = torus major=40 minor=8 at=[0,0,40]\n"
                   "ш = cylinder radius=6 height=4\n"
                   "ш = на_границе [ш] on=т point=[60,0,40]")
        self.assertTrue(any("на границе т" in n for n in b.scene.objects["ш"].notes))

    def test_requires_host(self):
        b = build("ш = cylinder radius=6 height=4\nш = на_границе [ш]",
                  analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("к чему приставить", (b.error or {}).get("message", ""))

    def test_unknown_host_is_reported(self):
        b = build("ш = cylinder radius=6 height=4\nш = на_границе [ш] on=нетакого",
                  analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("нетакого", (b.error or {}).get("message", ""))


class CardsAndExamplesTest(unittest.TestCase):
    """Карточки инструментов и примеры — чтобы примитивы были видны сразу."""

    def test_cards_exist(self):
        root = __import__("pathlib").Path(__file__).resolve().parent.parent
        app = (root / "web/js/app.js").read_text(encoding="utf-8")
        self.assertIn("op: 'крюк'", app)
        self.assertIn("op: 'полуовал'", app)
        self.assertIn("title: 'Деталь на границу'", app)
        self.assertIn("на_границе", app)

    def test_examples_registered(self):
        names = {e[1] if isinstance(e, (list, tuple)) else e for e in EXAMPLES}
        for key in ("hook", "half_oval", "surface"):
            with self.subTest(key=key):
                self.assertIn(key, names)

    def test_examples_build(self):
        for key in ("hook", "half_oval", "surface"):
            with self.subTest(key=key):
                b = build(load_example(key), analyze_model=False)
                self.assertTrue(b.ok, (b.error or {}).get("message"))
                self.assertGreaterEqual(len(b.scene.objects), 3)

    def test_surface_example_uses_true_boundary(self):
        b = build(load_example("surface"), analyze_model=False)
        self.assertTrue(b.ok)
        bb = b.scene.objects["шайба"].manifold.bounding_box()
        self.assertGreater(bb[0], 48.0)
        self.assertLess(bb[0], 53.0)


if __name__ == "__main__":
    unittest.main()
