"""0.19: сопряжения, проверка связи, мастер зазоров и карточки команд.

Проверяем то, что просили в этой итерации:
* деталь встаёт на место отношением (плоскость, ось, паз, зазор, точка, петля);
* связь запоминается и пересчитывается: после сдвига `check имя связь` краснеет;
* мастер зазоров честно показывает, какая деталь висит и на сколько;
* у каждой команды в справочнике есть описание, параметры и пример.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from forma.links import analyse
from forma.mates import point_gap, residual_of
from forma.run import build, commands_help

ROOT = Path(__file__).resolve().parent.parent


def scene(script: str):
    res = build(script)
    if not res.ok:
        raise AssertionError(res.error)
    return res


def checks_of(res):
    return {c["target"]: c for c in res.payload()["analysis"]["checks"]}


class MatesTest(unittest.TestCase):
    def test_plane_puts_part_on_top(self):
        res = scene("""
основание = box size=[100, 100, 20] center=да at=[0, 0, 0]
плитка = box size=[40, 40, 10] center=да at=[300, 0, 0]
сопряжение плитка основание type=плоскость axis=z
check плитка связь
""")
        obj = {o["name"]: o for o in res.payload()["objects"]}["плитка"]
        self.assertAlmostEqual(obj["bbox"][2], 10.0, places=2)
        self.assertTrue(checks_of(res)["плитка"]["ok"])

    def test_axis_centers_in_other_axes(self):
        res = scene("""
втулка = cylinder radius=8 height=10 center=да at=[0, 0, 300]
шайба = cylinder radius=16 height=6 center=да at=[200, 90, 400]
сопряжение шайба втулка type=ось axis=z
check шайба связь
""")
        obj = {o["name"]: o for o in res.payload()["objects"]}["шайба"]
        self.assertAlmostEqual((obj["bbox"][0] + obj["bbox"][3]) / 2, 0.0, places=2)
        self.assertAlmostEqual((obj["bbox"][1] + obj["bbox"][4]) / 2, 0.0, places=2)

    def test_slot_centers_and_seats(self):
        res = scene("""
рейка = box size=[64, 400, 11] center=да at=[0, 0, 100]
колесо = wheel diameter=26 width=12 rim=5 spokes=3 hub=8 tire=2 segments=48
сопряжение колесо рейка type=паз axis=y
check колесо связь
""")
        obj = {o["name"]: o for o in res.payload()["objects"]}["колесо"]
        self.assertAlmostEqual(obj["bbox"][2], 105.5, places=2)
        self.assertAlmostEqual((obj["bbox"][0] + obj["bbox"][3]) / 2, 0.0, places=2)

    def test_gap_keeps_exact_distance(self):
        res = scene("""
плита = box size=[200, 200, 10] center=да at=[0, 0, 0]
шайба = cylinder radius=20 height=4 center=да at=[0, 0, 300]
сопряжение шайба плита type=зазор offset=3
check шайба связь
""")
        obj = {o["name"]: o for o in res.payload()["objects"]}["шайба"]
        self.assertAlmostEqual(obj["bbox"][2], 8.0, places=2)

    def test_point_lands_on_target(self):
        res = scene("""
плита = box size=[200, 200, 10] center=да at=[0, 0, 0]
кнопка = box size=[10, 10, 10] center=да at=[0, 0, 0]
сопряжение кнопка плита type=точка point=[0, 0, 0] to=[30, 40, 12]
check кнопка связь
""")
        obj = {o["name"]: o for o in res.payload()["objects"]}["кнопка"]
        self.assertAlmostEqual((obj["bbox"][0] + obj["bbox"][3]) / 2, 30.0, places=2)
        self.assertAlmostEqual((obj["bbox"][1] + obj["bbox"][4]) / 2, 40.0, places=2)
        self.assertAlmostEqual(obj["bbox"][2], 7.0, places=2)

    def test_hinge_rotates_around_point(self):
        res = scene("""
корпус = box size=[400, 30, 400] center=да at=[0, 0, 0]
дверь = box size=[180, 18, 360] center=да at=[-200, -24, 0]
сопряжение дверь корпус type=петля axis=z point=[-290, -24, 0] angle=90
check дверь связь
""")
        obj = {o["name"]: o for o in res.payload()["objects"]}["дверь"]
        # Петля на левом краю: после поворота на 90° дверь уходит вперёд по Y,
        # а по X остаётся только её толщина.
        self.assertGreater(obj["bbox"][4], 100)
        self.assertLess(obj["bbox"][3] - obj["bbox"][0], 30)
        self.assertTrue(checks_of(res)["дверь"]["ok"])

    def test_record_saved_in_payload(self):
        res = scene("""
основание = box size=[100, 100, 20] center=да at=[0, 0, 0]
плитка = box size=[40, 40, 10] center=да at=[0, 0, 200]
сопряжение плитка основание type=плоскость axis=z
""")
        mates = res.payload()["mates"]
        self.assertEqual(len(mates), 1)
        self.assertEqual(mates[0]["moving"], "плитка")
        self.assertEqual(mates[0]["base"], "основание")
        self.assertEqual(mates[0]["kind"], "plane")
        self.assertGreater(mates[0]["line"], 0)

    def test_check_turns_red_when_link_breaks(self):
        script = (ROOT / "examples" / "mates.forma").read_text(encoding="utf-8")
        res = scene(script)
        self.assertTrue(all(c["ok"] for c in res.payload()["analysis"]["checks"]))
        moved = scene(script + "\ntranslate [каретка] offset=[0, 0, 5]\ncheck каретка связь\n")
        self.assertFalse(checks_of(moved)["каретка"]["ok"])

    def test_unknown_kind_is_reported(self):
        res = build("а = box size=[10, 10, 10]\nб = box size=[10, 10, 10]\n"
                    "сопряжение а б type=магия")
        self.assertFalse(res.ok)
        self.assertIn("сопряжение", res.error["message"].lower())


class LinksTest(unittest.TestCase):
    def test_separated_parts_are_reported(self):
        res = scene("""
плита = box size=[200, 200, 10] center=да at=[0, 0, 0]
блок = box size=[20, 20, 20] center=да at=[0, 0, 5]
гайка = box size=[10, 10, 10] center=да at=[0, 0, 400]
""")
        data = analyse(res.visible_solids())
        self.assertEqual(data["objects"], 3)
        self.assertEqual(data["groups"], 2)
        loose = {item["name"]: item for item in data["loose"]}
        self.assertIn("гайка", loose)
        self.assertGreater(loose["гайка"]["gap"], 100)

    def test_touching_parts_form_one_assembly(self):
        res = scene("""
низ = box size=[100, 100, 10] center=да at=[0, 0, 0]
верх = box size=[100, 100, 10] center=да at=[0, 0, 10]
""")
        data = analyse(res.visible_solids())
        self.assertEqual(data["groups"], 1)
        self.assertEqual(data["loose"], [])
        self.assertGreaterEqual(data["touches"], 1)

    def test_residual_is_recomputed(self):
        res = scene("""
основание = box size=[100, 100, 20] center=да at=[0, 0, 0]
плитка = box size=[40, 40, 10] center=да at=[0, 0, 200]
сопряжение плитка основание type=плоскость axis=z
""")
        record = res.scene.mates[0]
        self.assertLess(residual_of(record, res.scene), 1e-6)
        from forma.mates import move
        move(res.scene.resolve("плитка"), [0, 0, 7])
        self.assertAlmostEqual(residual_of(record, res.scene), 7.0, places=3)

    def test_point_gap_on_surface_is_zero(self):
        res = scene("плита = box size=[100, 100, 10] center=да at=[0, 0, 0]")
        block = res.scene.resolve("плита")
        self.assertLess(point_gap(block, [0, 0, 5]), 0.2)
        self.assertAlmostEqual(point_gap(block, [0, 0, 25]), 20.0, places=1)


class ImportBackTest(unittest.TestCase):
    """Свой GLB возвращается в сцену: швы сварены, оси Z-вверх."""

    def test_glb_round_trip(self):
        import tempfile
        res = scene("кружка = cup diameter=80 height=95 wall=4")
        path = Path(tempfile.mkdtemp()) / "кружка.glb"
        path.write_bytes(res.glb())
        back = scene(f"импорт = import file={path}\ncheck импорт watertight\n"
                     "check импорт height 92..98")
        obj = {o["name"]: o for o in back.payload()["objects"]}["импорт"]
        self.assertAlmostEqual(obj["bbox"][2], 0.0, places=1)
        self.assertAlmostEqual(obj["bbox"][5], 95.0, places=1)
        self.assertTrue(all(c["ok"] for c in back.payload()["analysis"]["checks"]))


class CommandsTest(unittest.TestCase):
    def test_every_command_has_card_fields(self):
        commands = commands_help()
        self.assertGreaterEqual(len(commands), 100)
        for c in commands:
            self.assertTrue(c["summary"], c["name"])
            self.assertTrue(c["params"], c["name"])
            self.assertTrue(c["example"], c["name"])
            self.assertTrue(c["category"], c["name"])

    def test_mate_command_in_reference(self):
        names = {c["name"] for c in commands_help()}
        self.assertIn("сопряжение", names)
        mate = next(c for c in commands_help() if c["name"] == "сопряжение")
        text = " ".join(p["desc"] for p in mate["params"])
        for kind in ("плоскость", "ось", "паз", "зазор", "точка", "петля"):
            self.assertIn(kind, text)

    def test_example_mates_builds(self):
        script = (ROOT / "examples" / "mates.forma").read_text(encoding="utf-8")
        res = scene(script)
        payload = res.payload()
        self.assertEqual(len(payload["mates"]), 7)
        self.assertEqual(len(payload["timeline"]["clips"]), 2)
        self.assertTrue(all(c["ok"] for c in payload["analysis"]["checks"]))


if __name__ == "__main__":
    unittest.main()
