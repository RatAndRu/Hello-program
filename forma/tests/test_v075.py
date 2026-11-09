"""0.75: правка сценария по смещениям, типы параметров и скорости.

Проверяется главное обещание: панель параметров меняет **ровно одну строку**
текста ``.forma`` и не держит второго хранилища значений. Регулярных выражений
в правке нет — значит и проверять надо на неудобных случаях: комментарии,
перенос строки обратным слэшем, вектор внутри значения, имя параметра с
кириллицей и связанное значение вида ``R/2``.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path

from forma.dsl import parse_script
from forma.edit import edit_source, commands_payload
from forma.errors import FormaError
from forma.param_spec import SPECS, spec_for
from forma.run import build

ROOT = Path(__file__).resolve().parent.parent

SAMPLE = """R = 30
body = cylinder R=30 h=12 at=[0,0,5]  # тело
cut = box [200,100,60] at=[0,0,30]
rim = tube 40 3 \\
    at=[0,0,9]
"""


class SpansTest(unittest.TestCase):
    def test_value_span_points_at_value(self):
        text = SAMPLE
        cmd = [c for c in parse_script(text) if c.line == 2][0]
        begin, end = cmd.spans["kwargs"]["h"]["value"]
        self.assertEqual(text[begin:end], "12")

    def test_array_value_span_is_whole_vector(self):
        cmd = [c for c in parse_script(SAMPLE) if c.line == 3][0]
        begin, end = cmd.spans["kwargs"]["at"]["value"]
        self.assertEqual(SAMPLE[begin:end], "[0,0,30]")

    def test_continuation_line_maps_to_original(self):
        cmd = [c for c in parse_script(SAMPLE) if c.line == 4][0]
        begin, end = cmd.spans["kwargs"]["at"]["value"]
        self.assertEqual(SAMPLE[begin:end], "[0,0,9]")

    def test_comment_not_part_of_command(self):
        cmd = [c for c in parse_script(SAMPLE) if c.line == 2][0]
        begin, end = cmd.spans["line"]
        self.assertNotIn("#", SAMPLE[begin:end:])

    def test_args_have_spans(self):
        cmd = parse_script("cut = box [200,100,60] at=[0,0,30]\n")[0]
        self.assertEqual(len(cmd.spans["args"]), 1)
        begin, end = cmd.spans["args"][0]
        self.assertEqual(cmd.text[begin - cmd.spans["line"][0]:end - cmd.spans["line"][0]],
                         "[200,100,60]")


    def test_spans_agree_on_every_example(self):
        """Срезы по смещениям обязаны совпадать с текстом токенов."""
        files = sorted((ROOT / "examples").glob("*.forma"))
        self.assertTrue(files)
        checked = 0
        for path in files:
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            for cmd in parse_script(text):
                # Логическая строка склеена из физических: переводы строк внутри
                # вектора становятся пробелами, смещения при этом настоящие.
                def flat(chunk: str) -> str:
                    return " ".join(chunk.split())

                begin, end = cmd.spans["line"]
                self.assertEqual(flat(text[begin:end]), flat(cmd.text), path.name)
                for key, span in cmd.spans.get("kwargs", {}).items():
                    value_begin, value_end = span["value"]
                    self.assertEqual(flat(text[value_begin:value_end]),
                                     flat(cmd.kwargs[key]),
                                     f"{path.name}:{cmd.line} {key}")
                    key_begin, key_end = span["key"]
                    self.assertEqual(text[key_begin:key_end].strip(), key,
                                     f"{path.name}:{cmd.line}")
                    checked += 1
                for token, span in zip(cmd.args, cmd.spans.get("args", [])):
                    self.assertEqual(flat(text[span[0]:span[1]]), flat(token),
                                     f"{path.name}:{cmd.line}")
        self.assertGreater(checked, 50)


class EditTest(unittest.TestCase):
    def test_set_existing_param_changes_one_line(self):
        result = edit_source(SAMPLE, {"action": "set_param", "line": 2, "param": "h",
                                      "value": 40})
        self.assertTrue(result["ok"])
        before = SAMPLE.split("\n")
        after = result["script"].split("\n")
        self.assertEqual(len(before), len(after))
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(changed, [1])
        self.assertEqual(after[1], "body = cylinder R=30 h=40 at=[0,0,5]  # тело")

    def test_missing_param_is_appended_and_survives(self):
        result = edit_source(SAMPLE, {"action": "set_param", "line": 3, "param": "h",
                                      "value": 5})
        self.assertIn(" at=[0,0,30] h=5", result["script"])
        # повторная правка находит уже записанное значение
        again = edit_source(result["script"], {"action": "set_param", "line": 3,
                                               "param": "h", "value": 6})
        self.assertEqual(again["edit"]["action"], "replace")
        self.assertIn("h=6", again["script"])

    def test_unset_removes_param_and_spacing(self):
        result = edit_source(SAMPLE, {"action": "unset_param", "line": 2, "param": "at"})
        self.assertEqual(result["script"].split("\n")[1],
                         "body = cylinder R=30 h=12  # тело")

    def test_linked_value_needs_confirmation(self):
        linked = "R = 30\nbody = cylinder R=30 h=R/2\n"
        refused = edit_source(linked, {"action": "set_param", "line": 2, "param": "h",
                                       "value": 7})
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["edit"]["reason"], "linked")
        self.assertEqual(refused["script"], linked)
        broken = edit_source(linked, {"action": "set_param", "line": 2, "param": "h",
                                      "value": 7, "break_link": True})
        self.assertTrue(broken["ok"])
        self.assertIn("h=7", broken["script"])

    def test_set_params_applies_both(self):
        result = edit_source(SAMPLE, {"action": "set_params", "line": 2,
                                      "values": {"R": 25, "h": 8}})
        self.assertEqual(result["script"].split("\n")[1],
                         "body = cylinder R=25 h=8 at=[0,0,5]  # тело")

    def test_add_command_inserts_after_line(self):
        result = edit_source(SAMPLE, {"action": "add_command", "after_line": 2,
                                      "text": "cap = sphere 6 at=[0,0,7]"})
        lines = result["script"].split("\n")
        self.assertEqual(lines[2], "cap = sphere 6 at=[0,0,7]")
        self.assertEqual(len(lines), len(SAMPLE.split("\n")) + 1)

    def test_delete_and_move_line(self):
        deleted = edit_source(SAMPLE, {"action": "delete_line", "line": 3})
        self.assertNotIn("cut = box", deleted["script"])
        moved = edit_source(SAMPLE, {"action": "move_line", "line": 4, "to": 1})
        self.assertTrue(moved["script"].split("\n")[1].startswith("rim = tube"))

    def test_definition_body_is_read_only(self):
        script = "module frame() {\n  a = box [10,10,10]\n}\n"
        commands = commands_payload(script)
        inside = [c for c in commands if "box" in c["text"]]
        self.assertTrue(inside and inside[0]["in_definition"])
        with self.assertRaises(FormaError):
            edit_source(script, {"action": "set_param", "line": 2, "param": "size",
                                 "value": [1, 2, 3]})

    def test_alias_key_edits_existing_spelling(self):
        script = "a = sphere радиус=10 at=[0,0,10]\n"
        result = edit_source(script, {"action": "set_param", "line": 1,
                                      "param": "radius", "value": 12})
        self.assertEqual(result["script"], "a = sphere радиус=12 at=[0,0,10]\n")

    def test_vector_value_round_trip(self):
        result = edit_source(SAMPLE, {"action": "set_param", "line": 3, "param": "at",
                                      "value": [0, 0, 45]})
        self.assertIn("at=[0, 0, 45]", result["script"])
        self.assertTrue(result["ok"])


class ToggleTest(unittest.TestCase):
    def test_disable_and_enable_keeps_comment(self):
        script = "a = sphere radius=5\nb = box [10,20,30] at=[0,0,10]\n# ручной комментарий\n"
        off = edit_source(script, {"action": "set_enabled", "line": 2, "enabled": False})
        self.assertTrue(off["script"].split("\n")[1].startswith("# b = box"))
        on = edit_source(off["script"], {"action": "set_enabled", "line": 2, "enabled": True})
        self.assertEqual(on["script"], script)

    def test_disabled_command_is_visible_to_panel(self):
        script = "a = sphere radius=5\n# b = box [10,20,30] at=[0,0,10]\n"
        commands = commands_payload(script)
        disabled = [c for c in commands if c["enabled"] is False]
        self.assertEqual(len(disabled), 1)
        self.assertEqual(disabled[0]["target"], "b")
        self.assertEqual(disabled[0]["line"], 2)

    def test_disabled_line_can_be_deleted(self):
        script = "a = sphere radius=5\n# b = box [10,20,30]\n"
        result = edit_source(script, {"action": "delete_line", "line": 2})
        self.assertEqual(result["script"], "a = sphere radius=5\n")


class ParamSpecTest(unittest.TestCase):
    REQUIRED = ["box", "cylinder", "cone", "sphere", "prism", "pyramid", "torus",
                "washer", "gear", "icosphere", "shaft", "pipe"]

    def test_required_ops_are_declared(self):
        for op in self.REQUIRED:
            self.assertTrue(spec_for(op), f"нет param_spec у {op}")

    def test_every_declared_param_has_known_type(self):
        allowed = {"num", "int", "vec", "flag", "enum", "str"}
        for op, params in SPECS.items():
            for key, spec in params.items():
                self.assertIn(spec["type"], allowed, f"{op}.{key}")
                self.assertTrue(spec.get("label"), f"{op}.{key}: нет подписи")
                if spec["type"] == "enum":
                    self.assertTrue(spec.get("items"), f"{op}.{key}: пустой список")
                    values = [item["value"] for item in spec["items"]]
                    self.assertIn(spec.get("default"), values, f"{op}.{key}")

    def test_auto_modes_are_declared(self):
        for op, params in SPECS.items():
            for key, spec in params.items():
                if not spec.get("auto"):
                    continue
                self.assertIn(spec["auto"], {"omitted", "sentinel", "enum"})
                if spec["auto"] == "sentinel":
                    self.assertIsNotNone(spec.get("sentinel_value"))
                self.assertTrue(spec.get("auto_hint"), f"{op}.{key}: нет подсказки")

    def test_bounds_are_sane(self):
        for op, params in SPECS.items():
            for key, spec in params.items():
                if spec.get("min") is not None and spec.get("max") is not None:
                    self.assertLess(spec["min"], spec["max"], f"{op}.{key}")

    def test_only_text_fields_are_free(self):
        for op, params in SPECS.items():
            for key, spec in params.items():
                if spec["type"] != "str":
                    self.assertFalse(spec.get("free"), f"{op}.{key}")

    def test_required_primitive_params_are_covered(self):
        """У примитивов каждый объявленный в ops.py параметр типизирован."""
        from forma.ops import lookup

        for op in self.REQUIRED:
            spec = lookup(op)
            declared = spec_for(op)
            # синонимы (expansion, expand_degree…) отдельных элементов не требуют
            missing = [key for key in spec.params
                       if key not in declared
                       and not str(spec.params[key]).startswith("синоним")]
            self.assertEqual(missing, [], f"{op}: без типа остались {missing}")


class PresetTest(unittest.TestCase):
    """Пресет формы — это значения параметров, а не второй набор геометрии."""

    BASE = {
        "box": "деталь = box size=[100,80,60]",
        "cylinder": "деталь = cylinder radius=40 height=90",
        "cone": "деталь = cone radius=40 height=60",
        "sphere": "деталь = sphere radius=40",
        "prism": "деталь = prism sides=6 radius=30 height=50",
        "torus": "деталь = torus major=30 minor=6",
        "gear": "деталь = gear teeth=20 module=2 thickness=8",
        "icosphere": "деталь = icosphere radius=30",
        "pipe": "деталь = pipe diameter=32 wall=2 length=200",
        "shaft": "деталь = shaft length=100 diameter=20",
    }

    def test_every_preset_uses_declared_params_and_builds(self):
        from forma.ops import lookup
        from forma.param_spec import presets_for

        for op, line in self.BASE.items():
            verb_kwargs = {}
            for token in line.split()[2:]:
                if "=" in token:
                    key, value = token.split("=", 1)
                    verb_kwargs[key] = value
            presets = presets_for(op, verb_kwargs)
            self.assertTrue(presets, f"нет пресетов у {op}")
            allowed = set(lookup(op).params)
            for preset in presets:
                self.assertTrue(set(preset["changes"]) <= allowed,
                                f"{op}/{preset['name']}: {set(preset['changes']) - allowed}")
                result = edit_source(line + "\n", {"action": "set_params", "line": 1,
                                                    "values": preset["changes"]})
                self.assertTrue(result["ok"], preset["name"])
                built = build(result["script"], analyze_model=False)
                self.assertTrue(built.ok, f"{op}/{preset['name']}: "
                                          f"{built.error and built.error.get('message')}")

    def test_preset_is_one_line(self):
        from forma.param_spec import presets_for

        line = "деталь = box size=[100,80,60]"
        preset = [p for p in presets_for("box", {"size": "[100,80,60]"})
                  if p["name"] == "плита"][0]
        result = edit_source(line + "\n", {"action": "set_params", "line": 1,
                                            "values": preset["changes"]})
        self.assertEqual(len(result["script"].split("\n")), 2)
        self.assertNotIn("\n\n", result["script"])

    def test_scene_presets_untouched(self):
        """Пресет формы не пишет в presets сцены и не читает их."""
        from forma.param_spec import presets_for

        names = {p["name"] for p in presets_for("box", {"size": "[10,10,10]"})}
        self.assertNotIn("preset", names)
        script = "R = 10\nb = box size=[10,10,10]\n"
        built = build(script, analyze_model=False)
        before = dict(built.scene.presets)
        edit_source(script, {"action": "set_params", "line": 2,
                             "values": {"size": [20, 20, 20]}})
        after = build(script, analyze_model=False).scene.presets
        self.assertEqual(before, after)


class UiWiringTest(unittest.TestCase):
    """Интерфейс обязан пользоваться серверными типами, а не своим списком."""

    def setUp(self):
        self.app = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        self.controls = (ROOT / "web" / "js" / "param_controls.js").read_text(
            encoding="utf-8")

    def test_app_uses_typed_controls(self):
        self.assertIn("from './param_controls.js'", self.app)
        self.assertIn("renderCommandParams", self.app)
        self.assertIn("renderObjectParams(payload)", self.app)

    def test_app_edits_source_instead_of_overrides(self):
        self.assertIn("'/api/edit'", self.app)
        self.assertIn("action: 'unset_param'", self.app)
        self.assertIn("formatValue(value)", self.app)

    def test_invalid_edit_rolls_back(self):
        self.assertIn("payload.ok === false", self.app)
        self.assertIn("setScript(before, { build: false, record: false", self.app)

    def test_free_input_only_for_strings(self):
        self.assertIn("FREE_TYPES = new Set(['str'])", self.controls)

    def test_panel_is_visible_and_follows_selection(self):
        """Панель не должна прятаться: иначе её просто не находят."""
        self.assertIn("renderObjectParams(state.payload || {});", self.app)
        self.assertIn("panel.hidden = false;", self.app)
        self.assertIn("Выберите деталь в списке", self.app)
        self.assertIn("object-params-jump", self.app)

    def test_panel_markup_exists(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="object-params-list"', html)
        self.assertIn('id="object-params-name"', html)


class PayloadTest(unittest.TestCase):
    def test_build_reports_commands_and_timings(self):
        script = (ROOT / "examples" / "alien.forma").read_text(encoding="utf-8")
        started = time.perf_counter()
        result = build(script, analyze_model=False)
        elapsed = time.perf_counter() - started
        self.assertTrue(result.ok)
        payload = result.payload(light=True)
        self.assertIn("timings", payload)
        self.assertIn("commands", payload)
        self.assertTrue(payload["commands"])
        for command in payload["commands"]:
            self.assertIn("spans", command)
            self.assertIn("editable", command)
        self.assertLess(elapsed, 5.0, "сборка без анализа не должна быть тяжёлой")

    def test_edit_applies_to_real_example(self):
        script = (ROOT / "examples" / "alien.forma").read_text(encoding="utf-8")
        commands = build(script, analyze_model=False).commands()
        target = None
        for command in commands:
            if command["verb"] == "sphere" and "radius" in command["kwargs"]:
                target = command
                break
        self.assertIsNotNone(target)
        edited = edit_source(script, {"action": "set_param", "line": target["line"],
                                      "param": "radius", "value": 7})
        self.assertTrue(edited["ok"])
        rebuilt = build(edited["script"], analyze_model=False)
        self.assertTrue(rebuilt.ok)


if __name__ == "__main__":
    unittest.main()
