"""0.79: типы параметров из общей таблицы и примеры, которые правда собираются.

Ядро знает не только 12 «избранных» команд: таблица ``param_types`` один раз
объявляет тип повторяющихся имён (``radius``, ``wall``, ``at``) и отдаёт его
всем операциям. Проверяется факт: сколько параметров получило тип, что явное
объявление важнее общего и что ни один контрол не выходит за известные виды.

Вторая половина — примеры, которые раньше не собирались: у ``hinge_move``,
``slider``, ``kerf_cut``, ``scatter``, ``fold_pattern`` и ``import`` не было
деталей или файлов. Теперь пример самодостаточен, и это закреплено тестом.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from forma.errors import FormaError
from forma.ops import OPS, lookup
from forma.param_spec import SPECS, generic_entry, payload, spec_for
from forma.param_types import TYPES, generic_spec
from forma.run import build

ROOT = Path(__file__).resolve().parent.parent

# Имена, у которых тип зависит от команды: ``size`` у плиты и у вектора — разное.
DISPUTED = {"size", "points", "sections", "factor", "start", "top"}

# Примеры, которые должны собираться без внешних программ.
FIXED_EXAMPLES = ("hinge_move", "slider", "kerf_cut", "scatter", "fold_pattern", "import")


def build_example(name: str):
    spec = lookup(name)
    if spec is None:
        raise AssertionError(f"нет команды {name}")
    return build(spec.example, analyze_model=False)


class ParamTypesTableTest(unittest.TestCase):
    def test_table_is_plain_data(self):
        for name, entry in TYPES.items():
            self.assertTrue(name, "пустое имя параметра")
            self.assertIn(entry["type"], {"num", "int", "vec", "flag", "str"}, name)
            if entry["type"] == "vec":
                self.assertIn(entry.get("size"), (2, 3), name)
            if "min" in entry and "max" in entry:
                self.assertLess(float(entry["min"]), float(entry["max"]), name)

    def test_generic_spec_returns_a_copy(self):
        entry = generic_spec("wall")
        self.assertIsNotNone(entry)
        self.assertIn("type", entry)
        entry["label"] = "испорчено"
        self.assertNotEqual(TYPES["wall"].get("label"), "испорчено")

    def test_disputed_names_stay_free(self):
        for name in DISPUTED:
            self.assertIsNone(generic_spec(name), name)

    def test_unknown_name_has_no_type(self):
        self.assertIsNone(generic_spec("совершенно_новый_параметр"))


class GenericSpecsTest(unittest.TestCase):
    def test_types_cover_most_parameters(self):
        total = typed = 0
        with_types = 0
        for spec in OPS.values():
            names = list(spec.params)
            found = spec_for(spec.name, names)
            total += len(names)
            typed += len(found)
            if found:
                with_types += 1
        self.assertGreaterEqual(total, 2000)
        self.assertGreaterEqual(typed / total, 0.5, f"типы только у {typed} из {total}")
        self.assertGreaterEqual(with_types, 220)

    def test_explicit_declaration_wins(self):
        explicit = SPECS["box"]
        merged = spec_for("box", ["size"])
        for key, value in explicit.items():
            self.assertEqual(merged[key], value)

    def test_names_outside_specs_are_added(self):
        merged = spec_for("bolt", ["radius", "wall", "d"])
        self.assertEqual(merged["radius"]["type"], "num")
        self.assertEqual(merged["wall"]["type"], "num")
        # У bolt нет явной таблицы: даже общеизвестное ``d`` берётся из общей.
        self.assertEqual(merged["d"]["type"], "num")
        self.assertIsNone(SPECS.get("bolt"))

    def test_explicit_beats_generic_for_the_same_name(self):
        explicit = SPECS["box"]["at"]
        merged = spec_for("box", ["at"])
        self.assertEqual(merged["at"], explicit)
        self.assertNotEqual(merged["at"], generic_entry("at"))

    def test_no_params_means_explicit_only(self):
        self.assertEqual(spec_for("bolt"), SPECS.get("bolt", {}))

    def test_controls_are_known_kinds(self):
        for spec in OPS.values():
            for name, entry in spec_for(spec.name, list(spec.params)).items():
                self.assertIn(entry["type"], {"num", "int", "vec", "flag", "enum", "str"},
                              f"{spec.name}.{name}")
                if entry["type"] == "vec":
                    self.assertIn(int(entry.get("size") or 3), (2, 3), f"{spec.name}.{name}")
                if entry["type"] in {"num", "int"}:
                    low, high = entry.get("min"), entry.get("max")
                    if low is not None and high is not None:
                        self.assertLess(low, high, f"{spec.name}.{name}")

    def test_generic_entry_is_a_control(self):
        entry = generic_entry("wall")
        self.assertEqual(entry["type"], "num")
        self.assertTrue(entry["label"])
        self.assertIn("min", entry)

    def test_payload_accepts_param_names(self):
        with_names = payload("bolt", list(OPS["bolt"].params))
        self.assertEqual(with_names["d"]["type"], "num")
        self.assertEqual(with_names["at"]["type"], "vec")
        self.assertEqual(with_names["at"]["size"], 3)

    def test_help_payload_reports_typed_count(self):
        from forma.run import build as build_text

        result = build_text("b = bolt d=10 length=40\n", analyze_model=False)
        self.assertTrue(result.ok, result.error)
        help_data = OPS["bolt"].help_dict()
        self.assertGreater(help_data["typed"], 0)
        self.assertFalse(help_data["declared"], "bolt не объявлен явно")


class FixedExamplesTest(unittest.TestCase):
    def test_every_fixed_example_builds(self):
        for name in FIXED_EXAMPLES:
            if name == "import":
                result = build_example(name)
                # Ассет лежит в репозитории: пример обязан работать без сети.
                self.assertTrue(result.ok, f"{name}: {result.error}")
                continue
            result = build_example(name)
            self.assertTrue(result.ok, f"{name}: {result.error}")
            self.assertTrue(result.scene.visible_solids(), name)

    def test_kerf_cut_example_has_separate_lines(self):
        lines = [line for line in lookup("kerf_cut").example.splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertIn("=", line)

    def test_openscad_example_needs_no_extra_file(self):
        example = lookup("openscad").example
        self.assertNotIn("file=", example)
        self.assertIn("code=", example)
        if not shutil.which("openscad"):
            result = build_example("openscad")
            self.assertFalse(result.ok)
            self.assertIn("OpenSCAD", (result.error or {}).get("message", ""))

    def test_fold_assets_exist(self):
        for name in ("crease_square.fold", "crease_square.cp"):
            path = ROOT / "examples" / "assets" / name
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 0)


class AuditClassificationTest(unittest.TestCase):
    def test_failure_reasons_are_grouped(self):
        import importlib.util

        path = ROOT / "tools" / "audit_commands.py"
        module_spec = importlib.util.spec_from_file_location("forma_audit_commands", path)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)

        self.assertEqual(module.classify("OpenSCAD не найден. Установите OpenSCAD"), "tool")
        self.assertEqual(module.classify("Не найден объект «дверь»."), "object")
        self.assertEqual(module.classify("fold_pattern: не удалось прочитать x.fold"), "file")
        self.assertEqual(module.classify("Лишний аргумент «=»."), "script")
        self.assertEqual(module.classify(""), "script")


if __name__ == "__main__":
    unittest.main()
