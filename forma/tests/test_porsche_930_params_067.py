"""Тесты варианта сценария для 0.66+ (param/preset/collision).

Эти тесты запускаются только там, где установлена версия 0.66 или новее:
на ветке 0.58 команды `param` ещё нет, и файл `porsche_930_params.forma`
там принципиально не собирается. Тест не «пропускается молча»: он честно
сообщает версию и то, какая команда нужна.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from forma.run import build
from forma.version import __version__

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "porsche_930_params.forma"

L, W, H = 4291.0, 1775.0, 1310.0
WB, TRACK_F, TRACK_R = 2272.0, 1432.0, 1492.0


def _has_command(name: str) -> bool:
    from forma.run import OPS
    return name in OPS


def _has_rule(name: str) -> bool:
    """`collision` — не команда, а правило проверки: check объект collision."""
    from forma.checks import RULES
    return name in RULES


@unittest.skipUnless(_has_command("param") and _has_command("preset")
                     and _has_rule("collision"),
                     f"ФОРМА {__version__}: нужны param/preset (0.67) "
                     "и правило collision (0.66)")
class ParamsVariantTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SCRIPT.read_text(encoding="utf-8")

    def build_with(self, **overrides):
        result = build(self.text, overrides=overrides or None)
        self.assertTrue(result.ok, result.error)
        return result

    def test_stock_preset_reproduces_the_drawing(self):
        result = self.build_with()
        size = result.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], L, delta=40)
        self.assertAlmostEqual(size[1], W, delta=40)
        self.assertAlmostEqual(size[2], H, delta=15)
        self.assertEqual(result.analysis["checks_passed"], result.analysis["checks_total"])

    def test_six_drawing_numbers_are_parameters(self):
        params = self.build_with().scene.params
        for name, value in (("L", L), ("W", W), ("H", H),
                            ("WB", WB), ("KF", TRACK_F), ("KR", TRACK_R)):
            with self.subTest(param=name):
                self.assertAlmostEqual(params[name], value, delta=1e-6)

    def test_moving_a_slider_moves_the_model(self):
        """Ползунок высоты меняет габарит, но не отрывает кузов от пола."""
        for height in (1250.0, 1400.0):
            with self.subTest(H=height):
                result = self.build_with(H=height)
                size = result.analysis["metrics"]["size"]
                self.assertAlmostEqual(size[2], height, delta=15)
                body = result.scene.objects["кузов"].manifold.bounding_box()
                self.assertAlmostEqual(body[2], 150.0, delta=3.0)      # просвет на месте
                self.assertAlmostEqual(body[5], height, delta=3.0)     # верх ушёл за H
                self.assertEqual(result.analysis["checks_passed"],
                                 result.analysis["checks_total"])

    def test_length_and_width_follow_their_parameters(self):
        result = self.build_with(L=4600.0, W=1830.0)
        size = result.analysis["metrics"]["size"]
        self.assertAlmostEqual(size[0], 4600.0, delta=40)
        self.assertAlmostEqual(size[1], 1830.0, delta=40)
        self.assertEqual(result.analysis["checks_passed"], result.analysis["checks_total"])

    def test_presets_are_declared_and_stock_comes_last(self):
        """`preset` применяется сразу, поэтому «сток» обязан идти последним."""
        lines = [line for line in self.text.splitlines() if line.startswith("preset ")]
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(lines[-1].startswith("preset сток"), lines[-1])
        for name in ("низкий", "широкий"):
            with self.subTest(preset=name):
                self.assertIn("preset " + name, self.text)
                self.assertIn(name, self.build_with().scene.presets)

    def test_wheels_do_not_collide_with_the_body(self):
        result = self.build_with()
        rules = [c for c in result.analysis["checks"] if c["rule"] == "collision"]
        self.assertEqual(len(rules), 4, [c["label"] for c in rules])
        self.assertTrue(all(c["ok"] for c in rules), rules)


if __name__ == "__main__":
    unittest.main()
