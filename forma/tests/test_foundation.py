"""Этап 0: eval, профилирование, golden/fuzz и регрессии оригами."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from forma.eval import compare_reports, evaluate_task, load_suite
from forma.fuzz import analyze_case, make_cases, run_fuzz
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "benchmarks" / "foundation.json"


def one_solid(result):
    solids = result.visible_solids()
    if len(solids) != 1:
        raise AssertionError(f"Ожидалось одно видимое тело, получено {len(solids)}")
    return solids[0].manifold


class TestCommandProfile(unittest.TestCase):
    def test_every_command_is_timed_and_exposed(self):
        script = "a = box size=[10,20,30]\nb = translate [a] offset=[5,0,0]\ncheck b watertight\n"
        result = build(script)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(result.command_timings), 3)
        self.assertEqual([row["verb"] for row in result.command_timings],
                         ["box", "translate", "check"])
        self.assertEqual([row["status"] for row in result.command_timings], ["ok"] * 3)
        self.assertTrue(all(row["ms"] >= 0 for row in result.command_timings))
        self.assertEqual(result.payload()["command_timings"], result.command_timings)

    def test_failed_command_and_parse_time_are_not_lost(self):
        result = build("a = box size=[10,10,10]\na = команда_которой_нет\n", analyze_model=False)
        self.assertFalse(result.ok)
        self.assertEqual(len(result.command_timings), 2)
        self.assertEqual(result.command_timings[-1]["status"], "error")
        self.assertGreaterEqual(result.command_timings[-1]["ms"], 0)
        parse_error = build("a =", analyze_model=False)
        self.assertFalse(parse_error.ok)
        self.assertIn("total", parse_error.timings)
        self.assertGreaterEqual(parse_error.timings["total"], parse_error.timings["parse"])


class TestFoundationEval(unittest.TestCase):
    def test_suite_is_valid_and_has_independent_checks(self):
        suite = load_suite(SUITE)
        self.assertEqual(suite["schema"], "forma-eval-suite-v1")
        self.assertEqual(len(suite["tasks"]), 20)
        self.assertEqual(len({task["id"] for task in suite["tasks"]}), 20)
        for task in suite["tasks"]:
            self.assertNotIn("\ncheck ", task["script"])
            self.assertTrue(task["checks"])

    def test_candidate_cannot_pass_by_deleting_checks_or_changing_shape(self):
        task = next(item for item in load_suite(SUITE)["tasks"] if item["id"] == "primitive_box")
        good = evaluate_task(task, ["блок = box size=[40,30,20]\n"])
        self.assertTrue(good["ok"], good["error"])
        self.assertEqual(len(good["checks"]), 4)
        wrong = evaluate_task(task, ["блок = box size=[40,30,21]\n"])
        self.assertFalse(wrong["ok"])
        self.assertTrue(any(not check["ok"] for check in wrong["checks"]))
        no_required = evaluate_task(task, ["блок = sphere radius=20\n"])
        self.assertFalse(no_required["ok"])
        self.assertTrue(no_required["violations"])

    def test_repair_attempts_and_comparison(self):
        task = next(item for item in load_suite(SUITE)["tasks"] if item["id"] == "primitive_box")
        result = evaluate_task(task, ["блок = box size=[40,30,21]\n",
                                      "блок = box size=[40,30,20]\n"])
        self.assertTrue(result["ok"])
        self.assertFalse(result["first_attempt_ok"])
        self.assertEqual(result["iterations"], 2)
        baseline = {"tasks": [{"id": "x", "ok": True, "first_attempt_ok": True, "checks": []}]}
        current = {"tasks": [{"id": "x", "ok": False, "first_attempt_ok": False, "checks": []}]}
        comparison = compare_reports(baseline, current)
        self.assertFalse(comparison["ok"])
        self.assertEqual({item["kind"] for item in comparison["regressions"]},
                         {"success", "first_attempt"})


class TestOrigamiFoundation(unittest.TestCase):
    def test_low_angle_fold_preserves_curved_strip(self):
        result = build("л = sheet width=80 length=80 thickness=0.5\n"
                       "с = сгиб л at=[0,0,0.5] dir=0 angle=3", analyze_model=False)
        self.assertTrue(result.ok, result.error)
        solid = one_solid(result)
        self.assertEqual(solid.status().name, "NoError")
        self.assertEqual(len(solid.decompose()), 1)
        self.assertGreaterEqual(solid.num_tri(), 500)
        self.assertAlmostEqual(solid.volume(), 3200.0, delta=32.0)

    def test_repeated_fold_fails_instead_of_silent_volume_loss(self):
        prefix = ("л = sheet width=80 length=80 thickness=0.5\n"
                  "с1 = fold л angle=179 sharp=1 gap=0.05\n"
                  "с2 = fold с1 angle=179 sharp=1 gap=0.05\n")
        second = build(prefix, analyze_model=False)
        self.assertTrue(second.ok, second.error)
        third = build(prefix + "с3 = fold с2 angle=179 sharp=1 gap=0.05\n", analyze_model=False)
        self.assertFalse(third.ok)
        self.assertIn("отклонение объёма", third.error["message"])
        self.assertIn("панели", third.error.get("hint", ""))

    def test_fold_sheet_volume_regression(self):
        result = build("с = fold_sheet width=80 length=80 thickness=0.5 parts=4 angle=179",
                       analyze_model=False)
        self.assertTrue(result.ok, result.error)
        solid = one_solid(result)
        self.assertEqual(len(solid.decompose()), 1)
        self.assertAlmostEqual(solid.volume(), 3200.0, delta=64.0)


class TestFoundationFuzz(unittest.TestCase):
    def test_cases_are_deterministic_and_export_is_checked(self):
        self.assertEqual(make_cases(24, 20261102), make_cases(24, 20261102))
        case = make_cases(1, 20261102)[0]
        result = analyze_case(case)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertGreater(result["glb_bytes"], 20)

    def test_isolated_run_writes_machine_readable_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "fuzz.json"
            report = run_fuzz(count=2, seed=20261102, timeout=30, output=output)
            self.assertTrue(report["ok"], report)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["summary"]["passed"], 2)
            self.assertEqual(saved["schema"], "forma-fuzz-report-v1")


if __name__ == "__main__":
    unittest.main()
