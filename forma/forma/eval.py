"""Воспроизводимый eval сценариев ФОРМЫ без привязки к LLM-провайдеру.

Benchmark хранит независимые проверки отдельно от эталонного сценария. Поэтому
кандидат не может улучшить результат, удалив собственные ``check``. Каталог
кандидатов принимает ``<task>.forma`` для одной попытки либо последовательность
``<task>.attempt01.forma``, ``<task>.attempt02.forma`` … для цикла исправлений.

Запуск из каталога ``forma``::

    python -m forma.eval --out docs/foundation_baseline.json
    python -m forma.eval --candidates /path/to/attempts --out candidate.json
    python -m forma.eval --candidates /path/to/attempts --compare docs/foundation_baseline.json

Модуль не вызывает сеть и не знает, какой моделью был написан сценарий.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import statistics
import sys
import time
from pathlib import Path

from .dsl import parse_script
from .ops import lookup
from .run import build
from .version import __version__

SUITE_SCHEMA = "forma-eval-suite-v1"
REPORT_SCHEMA = "forma-eval-report-v1"
DEFAULT_SUITE = Path(__file__).resolve().parents[1] / "benchmarks" / "foundation.json"
ATTEMPT_RE = re.compile(r"^(?P<id>[A-Za-z0-9_-]+)\.attempt(?P<n>[0-9]{2})\.forma$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_suite(path: str | Path) -> dict:
    source = Path(path)
    suite = json.loads(source.read_text(encoding="utf-8"))
    if suite.get("schema") != SUITE_SCHEMA:
        raise ValueError(f"Ожидался {SUITE_SCHEMA}, получен {suite.get('schema')!r}.")
    tasks = suite.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("В benchmark должен быть непустой список tasks.")
    seen: set[str] = set()
    for task in tasks:
        task_id = task.get("id", "")
        if not ID_RE.match(task_id):
            raise ValueError(f"Недопустимый id задачи: {task_id!r}.")
        if task_id in seen:
            raise ValueError(f"Повторяющийся id задачи: {task_id}.")
        seen.add(task_id)
        if not isinstance(task.get("script"), str) or not task["script"].strip():
            raise ValueError(f"{task_id}: пустой эталонный script.")
        if not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
            raise ValueError(f"{task_id}: пустой prompt.")
        checks = task.get("checks")
        if not isinstance(checks, list) or not checks or not all(
                isinstance(item, str) and item.strip().lower().startswith("check ")
                for item in checks):
            raise ValueError(f"{task_id}: нужны независимые строки checks вида 'check …'.")
        for key in ("required_verbs", "forbidden_verbs"):
            value = task.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"{task_id}: {key} должен быть списком строк.")
    return suite


def _canonical_verbs(script: str) -> tuple[list[str], int, str | None]:
    try:
        commands = parse_script(script)
    except Exception as exc:
        return [], 0, str(exc)
    verbs: list[str] = []
    for command in commands:
        spec = lookup(command.verb or "")
        if spec:
            verbs.append(spec.name)
    return verbs, len(commands), None


def _contract(task: dict, script: str) -> dict:
    verbs, command_count, parse_error = _canonical_verbs(script)
    present = set(verbs)
    violations: list[str] = []
    for raw in task.get("required_verbs", []):
        spec = lookup(raw)
        name = spec.name if spec else raw
        if name not in present:
            violations.append(f"не использована обязательная команда {name}")
    for raw in task.get("forbidden_verbs", []):
        spec = lookup(raw)
        name = spec.name if spec else raw
        if name in present:
            violations.append(f"использована запрещённая команда {name}")
    return {
        "commands": command_count,
        "verbs": sorted(present),
        "violations": violations,
        "parse_error": parse_error,
    }


def _metric_subset(build_result) -> dict:
    if not build_result.analysis:
        return {}
    metrics = build_result.analysis.get("metrics") or {}
    keys = ("size", "bbox", "volume_cm3", "area_cm2", "tris", "verts", "parts",
            "genus", "visible_count", "total_count")
    return {key: metrics.get(key) for key in keys if key in metrics}


def evaluate_attempt(task: dict, script: str) -> dict:
    """Строит одну попытку и применяет внешние проверки задачи."""
    started = time.perf_counter()
    contract = _contract(task, script)
    external = list(task["checks"])
    evaluation_script = script.rstrip() + "\n\n# Независимые проверки benchmark\n" + "\n".join(external) + "\n"
    result = build(evaluation_script)
    all_checks = list((result.analysis or {}).get("checks") or []) if result.analysis else []
    external_checks = all_checks[-len(external):] if external else []
    own_checks = all_checks[:-len(external)] if external else all_checks
    external_ok = bool(external_checks) and all(item.get("ok") for item in external_checks)
    own_ok = all(item.get("ok") for item in own_checks)
    ok = bool(result.ok and external_ok and own_ok and not contract["violations"])
    return {
        "ok": ok,
        "script_sha256": _sha(script),
        "commands": contract["commands"],
        "verbs": contract["verbs"],
        "violations": contract["violations"],
        "error": result.error,
        "checks": external_checks,
        "checks_passed": sum(1 for item in external_checks if item.get("ok")),
        "checks_total": len(external_checks),
        "own_checks_failed": sum(1 for item in own_checks if not item.get("ok")),
        "metrics": _metric_subset(result),
        "timings": result.timings,
        "command_timings": result.command_timings,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def evaluate_task(task: dict, scripts: list[str]) -> dict:
    attempts: list[dict] = []
    for index, script in enumerate(scripts, 1):
        attempt = evaluate_attempt(task, script)
        attempt["attempt"] = index
        attempts.append(attempt)
        if attempt["ok"]:
            break
    if not attempts:
        attempts.append({
            "attempt": 0, "ok": False, "commands": 0, "verbs": [], "violations": [],
            "error": {"message": "Нет сценария кандидата."}, "checks": [],
            "checks_passed": 0, "checks_total": len(task["checks"]),
            "own_checks_failed": 0, "metrics": {}, "timings": {}, "command_timings": [],
            "elapsed_ms": 0.0,
        })
    final = attempts[-1]
    return {
        "id": task["id"],
        "category": task.get("category", "general"),
        "ok": final["ok"],
        "first_attempt_ok": attempts[0]["ok"],
        "iterations": len(attempts) if scripts else 0,
        "commands": final["commands"],
        "metrics": final["metrics"],
        "checks": final["checks"],
        "error": final["error"],
        "violations": final["violations"],
        "attempts": attempts,
        "elapsed_ms": round(sum(item["elapsed_ms"] for item in attempts), 3),
    }


def _candidate_scripts(directory: Path, task_id: str) -> list[str]:
    direct = directory / f"{task_id}.forma"
    if direct.exists():
        return [direct.read_text(encoding="utf-8")]
    found: list[tuple[int, Path]] = []
    for path in directory.glob(f"{task_id}.attempt*.forma"):
        match = ATTEMPT_RE.match(path.name)
        if match and match.group("id") == task_id:
            found.append((int(match.group("n")), path))
    return [path.read_text(encoding="utf-8") for _, path in sorted(found)]


def _environment() -> dict:
    def version(package: str) -> str:
        try:
            return importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            return "unknown"
    return {
        "forma": __version__,
        "python": platform.python_version(),
        "manifold3d": version("manifold3d"),
        "numpy": version("numpy"),
    }


def run_suite(suite_path: str | Path = DEFAULT_SUITE,
              candidates: str | Path | None = None, label: str | None = None) -> dict:
    source = Path(suite_path)
    suite = load_suite(source)
    candidate_dir = Path(candidates) if candidates else None
    if candidate_dir and not candidate_dir.is_dir():
        raise ValueError(f"Каталог кандидатов не найден: {candidate_dir}")
    tasks = []
    for task in suite["tasks"]:
        scripts = ([task["script"]] if candidate_dir is None
                   else _candidate_scripts(candidate_dir, task["id"]))
        tasks.append(evaluate_task(task, scripts))
    passed = sum(1 for item in tasks if item["ok"])
    first_passed = sum(1 for item in tasks if item["first_attempt_ok"])
    repaired = sum(1 for item in tasks if item["ok"] and not item["first_attempt_ok"])
    checks_passed = sum(sum(1 for check in item["checks"] if check.get("ok")) for item in tasks)
    checks_total = sum(len(item["checks"]) for item in tasks)
    categories: dict[str, dict] = {}
    for item in tasks:
        row = categories.setdefault(item["category"], {"tasks": 0, "passed": 0,
                                                       "first_attempt_passed": 0})
        row["tasks"] += 1
        row["passed"] += int(item["ok"])
        row["first_attempt_passed"] += int(item["first_attempt_ok"])
    summary = {
        "tasks": len(tasks),
        "passed": passed,
        "success_rate": round(passed / len(tasks), 6),
        "first_attempt_passed": first_passed,
        "first_attempt_success_rate": round(first_passed / len(tasks), 6),
        "repaired": repaired,
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "check_pass_rate": round(checks_passed / checks_total, 6) if checks_total else 0.0,
        "total_iterations": sum(item["iterations"] for item in tasks),
        "total_elapsed_ms": round(sum(item["elapsed_ms"] for item in tasks), 3),
        "median_task_ms": round(statistics.median(item["elapsed_ms"] for item in tasks), 3),
        "total_tris": sum((item["metrics"].get("tris") or 0) for item in tasks if item["ok"]),
        "failed": [item["id"] for item in tasks if not item["ok"]],
        "by_category": categories,
    }
    return {
        "schema": REPORT_SCHEMA,
        "mode": "candidates" if candidate_dir else "reference",
        "label": label or ("candidates" if candidate_dir else "reference"),
        "suite": {
            "name": suite.get("name", source.stem),
            "version": suite.get("version", 1),
            "sha256": _sha(source.read_text(encoding="utf-8")),
        },
        "environment": _environment(),
        "ok": passed == len(tasks),
        "summary": summary,
        "tasks": tasks,
    }


def compare_reports(baseline: dict, current: dict) -> dict:
    """Сравнивает успех и первую попытку, но не машинно-зависимое время."""
    before = {item["id"]: item for item in baseline.get("tasks", [])}
    after = {item["id"]: item for item in current.get("tasks", [])}
    regressions: list[dict] = []
    improvements: list[dict] = []
    for task_id, old in before.items():
        new = after.get(task_id)
        if new is None:
            regressions.append({"id": task_id, "kind": "missing"})
            continue
        for key, kind in (("ok", "success"), ("first_attempt_ok", "first_attempt")):
            if old.get(key) and not new.get(key):
                regressions.append({"id": task_id, "kind": kind})
            elif not old.get(key) and new.get(key):
                improvements.append({"id": task_id, "kind": kind})
        old_checks = sum(1 for check in old.get("checks", []) if check.get("ok"))
        new_checks = sum(1 for check in new.get("checks", []) if check.get("ok"))
        if new_checks < old_checks:
            regressions.append({"id": task_id, "kind": "checks",
                                "before": old_checks, "after": new_checks})
    added = sorted(set(after) - set(before))
    return {"ok": not regressions, "regressions": regressions,
            "improvements": improvements, "added": added}


def _print_report(report: dict) -> None:
    for item in report["tasks"]:
        mark = "OK  " if item["ok"] else "FAIL"
        first = "первая" if item["first_attempt_ok"] else f"попыток {item['iterations']}"
        tris = item["metrics"].get("tris", "—")
        print(f"[{mark}] {item['id']}: {first}, {item['elapsed_ms']:.1f} мс, {tris} трис")
        if not item["ok"]:
            error = item.get("error") or {}
            message = error.get("message") or "; ".join(item.get("violations") or [])
            failed_checks = [check.get("text") for check in item["checks"] if not check.get("ok")]
            if failed_checks:
                message = (message + "; " if message else "") + "проверки: " + "; ".join(failed_checks)
            if message:
                print(f"       {message}")
    summary = report["summary"]
    print("\nИТОГ EVAL:")
    print(f"  финальный успех: {summary['passed']}/{summary['tasks']} "
          f"({summary['success_rate']:.1%})")
    print(f"  первая попытка: {summary['first_attempt_passed']}/{summary['tasks']} "
          f"({summary['first_attempt_success_rate']:.1%})")
    print(f"  независимые проверки: {summary['checks_passed']}/{summary['checks_total']}")
    print(f"  исправлено после первой попытки: {summary['repaired']}")
    print(f"  треугольники в успешных сценах: {summary['total_tris']}")
    print(f"  время: {summary['total_elapsed_ms']:.1f} мс; "
          f"медиана задачи {summary['median_task_ms']:.1f} мс")


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--suite", default=str(DEFAULT_SUITE), help="JSON benchmark")
    parser.add_argument("--candidates", help="каталог .forma ответов модели")
    parser.add_argument("--out", help="записать полный JSON-отчёт")
    parser.add_argument("--compare", help="сравнить с прежним JSON-отчётом")
    parser.add_argument("--label", help="имя прогона в отчёте")
    parser.add_argument("--json", action="store_true", help="вывести полный JSON в stdout")
    parser.add_argument("--allow-failures", action="store_true",
                        help="вернуть код 0 даже при непройденных задачах")


def run_cli(args) -> int:
    try:
        report = run_suite(args.suite, args.candidates, args.label)
        if args.out:
            output = Path(args.out)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_report(report)
            if args.out:
                print(f"\nОтчёт: {args.out}")
        comparison_ok = True
        if args.compare:
            baseline = json.loads(Path(args.compare).read_text(encoding="utf-8"))
            comparison = compare_reports(baseline, report)
            comparison_ok = comparison["ok"]
            print(f"\nСРАВНЕНИЕ: регрессий {len(comparison['regressions'])}, "
                  f"улучшений {len(comparison['improvements'])}")
            for item in comparison["regressions"]:
                print(f"  REGRESSION {item}")
        return 0 if (report["ok"] and comparison_ok) or args.allow_failures else 1
    except Exception as exc:
        print(f"ОШИБКА EVAL: {exc}", file=sys.stderr)
        return 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark и eval сценариев ФОРМЫ")
    configure_parser(parser)
    return run_cli(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
