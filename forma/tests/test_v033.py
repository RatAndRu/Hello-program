"""0.33: точное место в пространстве, меры везде и бюджет кубической сетки.

Проверки держат просьбы пользователя:

1. **положение** — можно проверить абсолютное место детали (угол габарита)
   и её центр, с допуском в миллиметрах;
2. **меры везде** — `top`, `height`, `cx` и другие считаются не только в
   `let`, но и прямо в аргументах любой команды;
3. **зазор на деле** — сопряжение доводит реальный зазор до заданного даже
   тогда, когда детали изначально пересекались;
4. **грани, а не коробка** — плоскость/паз встают по фактической поверхности
   повёрнутого основания;
5. **кубическая сетка** — бюджет объёма: `сетка` + `вписать` + `check в_сетке`;
6. **окно** — в карточке кубов есть запись бюджета в сценарий и подсветка.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

import forma.run  # noqa: F401  (наполняет реестр команд)
from forma.mates import residual_of
from forma.ops_grid import grid_bounds, grid_shape, overflow_mm3
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _build(script: str, analyze: bool = True):
    b = build(script, analyze_model=analyze)
    assert b.ok, (b.error or {}).get("message")
    return b


def _bbox(solid) -> list[float]:
    return [float(v) for v in solid.manifold.bounding_box()]


def _solid(b, name):
    return b.scene.objects[name]


def _checks(b) -> dict[str, dict]:
    return {c["target"]: c for c in (b.payload().get("analysis") or {}).get("checks", [])}


def _warnings(b) -> list[str]:
    return list((b.payload().get("analysis") or {}).get("warnings", []))


class PlaceCheckTest(unittest.TestCase):
    """`check имя положение x=… y=… z=…` — абсолютное место детали."""

    def test_corner_in_place_is_ok(self):
        b = _build("""
к = box size=[20, 20, 20] at=[0, 0, 0]
check к положение -10 -10 0
""")
        check = _checks(b)["к"]
        self.assertTrue(check["ok"], check["text"])
        self.assertIn("угол", check["text"])

    def test_wrong_place_is_red(self):
        b = _build("""
к = box size=[20, 20, 20] at=[0, 0, 0]
check к положение 0 0 0
""")
        check = _checks(b)["к"]
        self.assertFalse(check["ok"])
        self.assertIn("вне допуска", check["text"])

    def test_range_and_kwargs(self):
        b = _build("""
к = box size=[20, 20, 20] at=[40, 0, 10]
check к положение x=29..31 y=-11..-9 z=9..11
""")
        self.assertTrue(_checks(b)["к"]["ok"], _checks(b)["к"]["text"])

    def test_tolerance_is_honoured(self):
        script = """
к = box size=[20, 20, 20] at=[0, 0, 0]
check к положение 0 0 0{tol}
"""
        good = _build(script.format(tol=" допуск=10.5"))
        self.assertTrue(_checks(good)["к"]["ok"], _checks(good)["к"]["text"])
        bad = _build(script.format(tol=" допуск=0.2"))
        self.assertFalse(_checks(bad)["к"]["ok"])

    def test_default_tolerance_is_half_mm(self):
        b = _build("""
к = box size=[20, 20, 20] at=[0, 0, 0]
check к положение -10.4 -10 0
""")
        self.assertTrue(_checks(b)["к"]["ok"], _checks(b)["к"]["text"])

    def test_center_rule(self):
        b = _build("""
к = box size=[20, 20, 30] at=[0, 0, 0]
check к центр 0 0 15
""")
        check = _checks(b)["к"]
        self.assertTrue(check["ok"], check["text"])
        self.assertIn("центр", check["text"])

    def test_alias_place(self):
        b = _build("""
к = sphere radius=10 at=[0, 0, 0]
check к место 0 0 0
""")
        self.assertIn("к", _checks(b))


class MeasuresEverywhereTest(unittest.TestCase):
    """Меры (`top`, `height`, `cx`, …) работают в аргументах любой команды."""

    def test_top_in_at(self):
        b = _build("""
чашка = cylinder radius=40 height=95
крышка = box size=[90, 90, 10] at=[0, 0, top(чашка) + 2]
""")
        bb = _bbox(_solid(b, "крышка"))
        self.assertAlmostEqual(bb[2], 97.0, places=3)
        self.assertAlmostEqual(bb[5], 107.0, places=3)

    def test_height_in_at(self):
        b = _build("""
дет = box size=[40, 40, 20]
к = box size=[40, 40, 20] at=[0, 0, height(дет) + 10]
""")
        bb = _bbox(_solid(b, "к"))
        self.assertAlmostEqual(bb[2], 30.0, places=3)
        self.assertAlmostEqual(bb[5], 50.0, places=3)

    def test_cx_in_x(self):
        b = _build("""
дет = box size=[40, 40, 20] at=[0, 0, 0]
к = box size=[20, 20, 20] at=[cx(дет) + 30, 0, 0]
""")
        bb = _bbox(_solid(b, "к"))
        self.assertAlmostEqual(bb[0], 20.0, places=3)
        self.assertAlmostEqual(bb[3], 40.0, places=3)

    def test_measure_in_rotate(self):
        b = _build("""
плита = box size=[100, 40, 10]
плита = rotate [плита] angle=cx(плита) axis=z
""")
        self.assertAlmostEqual(_bbox(_solid(b, "плита"))[3] - _bbox(_solid(b, "плита"))[0],
                               100.0, places=1)

    def test_measure_inside_min(self):
        b = _build("""
дет = box size=[40, 40, 20] at=[0, 0, 30]
шапка = box size=[20, 20, 20] at=[0, 0, max(10, bottom(дет) - 5)]
""")
        self.assertAlmostEqual(_bbox(_solid(b, "шапка"))[2], 25.0, places=3)


class GapMateTest(unittest.TestCase):
    """`зазор` доводит именно реальный зазор, а не габаритный."""

    def _gap_after(self, script: str, moving: str, base: str) -> float:
        b = _build(script, analyze=False)
        bb_m = _bbox(_solid(b, moving))
        bb_b = _bbox(_solid(b, base))
        return bb_m[2] - bb_b[5]

    def test_overlapping_parts_are_pushed_out(self):
        gap = self._gap_after("""
осн = box size=[100, 100, 20]
дет = box size=[20, 20, 20] at=[0, 0, 15]
сопряжение дет осн type=зазор axis=z offset=5
""", "дет", "осн")
        self.assertAlmostEqual(gap, 5.0, places=2)

    def test_exact_gap_without_overlap(self):
        gap = self._gap_after("""
осн = box size=[100, 100, 20]
дет = box size=[20, 20, 20] at=[0, 0, 20]
сопряжение дет осн type=зазор axis=z offset=5
""", "дет", "осн")
        self.assertAlmostEqual(gap, 5.0, places=2)

    def test_touch_when_offset_zero(self):
        gap = self._gap_after("""
осн = box size=[100, 100, 20]
дет = box size=[20, 20, 20] at=[0, 0, 25]
сопряжение дет осн type=зазор axis=z offset=0
""", "дет", "осн")
        self.assertAlmostEqual(gap, 0.0, places=2)

    def test_spheres_get_the_gap(self):
        gap = self._gap_after("""
а = sphere radius=20
б = sphere radius=10 at=[0, 0, 40]
сопряжение б а type=зазор axis=z offset=2
""", "б", "а")
        self.assertAlmostEqual(gap, 2.0, places=2)

    def test_link_check_passes(self):
        b = _build("""
осн = box size=[100, 100, 20]
дет = box size=[20, 20, 20] at=[0, 0, 15]
сопряжение дет осн type=зазор axis=z offset=5
check дет связь
""")
        self.assertTrue(_checks(b)["дет"]["ok"], _checks(b)["дет"]["text"])
        self.assertLess(residual_of(b.scene.mates[-1], b.scene), 0.05)

    def test_x_axis_gap(self):
        b = _build("""
осн = box size=[100, 100, 20]
дет = box size=[20, 20, 20] at=[0, 0, 15]
сопряжение дет осн type=зазор axis=x offset=3
""", analyze=False)
        bb_m, bb_b = _bbox(_solid(b, "дет")), _bbox(_solid(b, "осн"))
        self.assertAlmostEqual(bb_m[0] - bb_b[3], 3.0, places=2)


class RealFaceMateTest(unittest.TestCase):
    """Плоскость и паз садятся по фактической поверхности повёрнутой детали."""

    def test_plane_on_tilted_base(self):
        b = _build("""
осн = box size=[100, 100, 10]
осн = rotate [осн] angle=30 axis=x
шапка = box size=[30, 30, 30]
сопряжение шапка осн type=плоскость axis=z
check шапка связь
""")
        self.assertTrue(_checks(b)["шапка"]["ok"], _checks(b)["шапка"]["text"])
        real = _solid(b, "шапка").manifold.min_gap(_solid(b, "осн").manifold, 600.0)
        self.assertLess(real, 0.1)

    def test_plane_side_part_keeps_the_level(self):
        b = _build("""
основание = box size=[100, 100, 20] center=да
плитка = box size=[40, 40, 10] center=да at=[300, 0, 0]
сопряжение плитка основание type=плоскость axis=z
check плитка связь
""")
        self.assertAlmostEqual(_bbox(_solid(b, "плитка"))[2], 10.0, places=2)
        self.assertTrue(_checks(b)["плитка"]["ok"], _checks(b)["плитка"]["text"])

    def test_slot_on_tilted_rail(self):
        b = _build("""
рейка = box size=[64, 400, 11] center=да at=[0, 0, 40]
рейка = rotate [рейка] angle=20 axis=x
кол = cylinder radius=10 height=20
сопряжение кол рейка type=паз axis=y
check кол связь
""")
        self.assertTrue(_checks(b)["кол"]["ok"], _checks(b)["кол"]["text"])

    def test_flat_plane_still_exact(self):
        b = _build("""
осн = box size=[100, 100, 20] center=да
плитка = box size=[40, 40, 10] center=да at=[0, 0, 200]
сопряжение плитка осн type=плоскость axis=z offset=2
""", analyze=False)
        self.assertAlmostEqual(_bbox(_solid(b, "плитка"))[2], 12.0, places=2)


class GridBudgetTest(unittest.TestCase):
    """Кубическая сетка как ограничение объёма."""

    def test_rectangle_grid(self):
        b = _build("""
сетка cell=20 origin=[-60, -60, 0] size=[6, 4, 3]
""", analyze=False)
        grid = b.scene.grid
        self.assertAlmostEqual(grid["cell"], 20.0)
        self.assertEqual(len(grid["cells"]), 72)
        self.assertAlmostEqual(grid["volume_mm3"], 72 * 8000.0)
        self.assertEqual(grid_bounds(grid), [-60.0, -60.0, 0.0, 60.0, 20.0, 60.0])

    def test_grid_shape_volume(self):
        grid = {"cell": 10.0, "origin": [0.0, 0.0, 0.0],
                "cells": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]}
        shape = grid_shape(grid["cell"], grid["origin"], [tuple(c) for c in grid["cells"]])
        self.assertAlmostEqual(float(shape.volume()), 4 * 1000.0, places=3)

    def test_fit_clips_to_budget(self):
        b = _build("""
сетка cell=20 origin=[-60, -60, 0] size=[6, 4, 3]
корпус = box size=[300, 300, 40] at=[0, 0, -10]
вписать корпус
""")
        bb = _bbox(_solid(b, "корпус"))
        self.assertLessEqual(bb[0], -60.0 + 1e-6)
        self.assertGreaterEqual(bb[3], 60.0 - 1e-6)
        self.assertLessEqual(bb[5], 60.0 + 1e-6)
        self.assertTrue(_solid(b, "корпус").notes)

    def test_check_inside_reports_outside(self):
        b = _build("""
сетка cell=20 size=[6, 4, 3]
корпус = box size=[300, 300, 40]
check корпус в_сетке
""")
        check = _checks(b)["корпус"]
        self.assertFalse(check["ok"])
        self.assertIn("вне бюджета", check["text"])
        warnings = " ".join(_warnings(b))
        self.assertIn("Вне кубической сетки", warnings)

    def test_check_inside_after_fit_is_ok(self):
        b = _build("""
сетка cell=20 size=[6, 4, 3]
корпус = box size=[300, 300, 40] at=[0, 0, -10]
вписать корпус
check корпус в_сетке
""")
        self.assertTrue(_checks(b)["корпус"]["ok"], _checks(b)["корпус"]["text"])
        self.assertEqual(_warnings(b), [])

    def test_overflow_measure(self):
        b = _build("""
сетка cell=20 origin=[-20, -20, 0] size=[2, 2, 1]
дет = box size=[100, 100, 20] at=[0, 0, 0]
""", analyze=False)
        over = overflow_mm3(_solid(b, "дет").manifold, b.scene.grid)
        inside = 40 * 40 * 20
        self.assertAlmostEqual(float(_solid(b, "дет").manifold.volume()) - over,
                               inside, delta=1.0)

    def test_cells_and_ranges(self):
        b = _build("""
сетка cell=10 cells=[[0,0,0],[1,0,0],[0,1,0]]
""", analyze=False)
        self.assertEqual(len(b.scene.grid["cells"]), 3)
        b2 = _build("""
сетка cell=10 ranges=[[0, 1, 0, 1, 0, 0]]
""", analyze=False)
        self.assertEqual(len(b2.scene.grid["cells"]), 4)

    def test_around_the_model(self):
        b = _build("""
дет = box size=[50, 50, 20]
сетка cell=10 around=да
""", analyze=False)
        grid = b.scene.grid
        self.assertGreater(len(grid["cells"]), 20)
        bounds = grid_bounds(grid)
        # кубы обязаны обхватить деталь целиком, даже с запасом на края
        self.assertLessEqual(bounds[0], -25.0)
        self.assertGreaterEqual(bounds[3], 25.0)
        self.assertGreaterEqual(bounds[5], 20.0)

    def test_fit_without_grid_is_error(self):
        b = build("дет = box size=[10, 10, 10]\nвписать дет", analyze_model=False)
        self.assertFalse(b.ok)
        self.assertIn("сетк", (b.error or {}).get("message", "").lower())

    def test_grid_in_payload(self):
        b = _build("""
сетка cell=20 size=[2, 2, 2]
""", analyze=False)
        grid = b.payload().get("grid")
        self.assertIsNotNone(grid)
        self.assertEqual(len(grid["cells"]), 8)
        self.assertAlmostEqual(grid["volume_mm3"], 64000.0)

    def test_grid_survives_animation_frames(self):
        """Сетка — настройка сцены: кадры анимации её не сбрасывают."""
        b = _build("""
сетка cell=20 size=[2, 2, 2]
дет = box size=[10, 10, 10]
animate kind=spin seconds=2
""")
        self.assertIsNotNone(b.scene.grid)


class WindowTest(unittest.TestCase):
    """Кнопка бюджета и подсветка живут в окне модели."""

    def test_budget_button_in_markup(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="space-budget"', html)

    def test_viewer_builds_grid_command(self):
        js = (WEB / "js" / "viewer.js").read_text(encoding="utf-8")
        self.assertIn("_spaceScript", js)
        self.assertIn("budget_cm3", js)
        app = (WEB / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("applyGridScript", app)
        self.assertIn("budget-alert", app)

    def test_styles_highlight_budget(self):
        css = (WEB / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".space-card.budget-alert", css)


class HelpTest(unittest.TestCase):
    """Инструменты описаны в справке — значит ИИ и человек их найдут."""

    def test_commands_are_registered(self):
        from forma.ops import lookup

        for name in ("сетка", "вписать"):
            self.assertIsNotNone(lookup(name), name)

    def test_help_mentions_budget(self):
        from forma.ops import lookup

        info = lookup("сетка")
        self.assertIsNotNone(info)
        text = " ".join([info.summary, info.example] + list(info.params.values()))
        self.assertIn("куб", text.lower())
        self.assertIn("бюджет", text.lower())

    def test_check_rules_are_known(self):
        from forma.checks import RULE_LABELS

        for rule in ("position", "center", "grid"):
            self.assertIn(rule, RULE_LABELS)


if __name__ == "__main__":
    unittest.main()
