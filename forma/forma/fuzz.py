"""Небольшой детерминированный fuzz-набор DSL и экспорта.

Каждый случай выполняется в отдельном spawn-процессе, поэтому зависший C++ или
Python-расчёт можно остановить, не потеряв остальные результаты. Генерируемые
сценарии намеренно короткие: при ошибке они сами являются minimal repro.

    python -m forma.fuzz --cases 24 --seed 20261102 --output fuzz-report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import queue
import random
import struct
import sys
import time
import traceback
from pathlib import Path

from .eval import _environment
from .run import build


def make_cases(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    families = ("box", "cylinder", "prism", "extrude", "hole", "fold_sheet",
                "groove", "gear", "pipe", "text", "blob", "spring")
    cases: list[dict] = []
    for index in range(count):
        family = families[index % len(families)] if index < len(families) else rng.choice(families)
        if family == "box":
            size = [round(rng.uniform(2, 100), 2) for _ in range(3)]
            script = f"деталь = box size={size}\n"
        elif family == "cylinder":
            radius = round(rng.uniform(2, 30), 2)
            height = round(rng.uniform(2, 100), 2)
            script = f"деталь = cylinder radius={radius} height={height}\n"
        elif family == "prism":
            sides = rng.randint(3, 12)
            radius = round(rng.uniform(5, 35), 2)
            height = round(rng.uniform(3, 60), 2)
            script = f"деталь = prism sides={sides} radius={radius} height={height}\n"
        elif family == "extrude":
            w, h, z = (round(rng.uniform(5, 70), 2) for _ in range(3))
            profile = [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]]
            script = f"деталь = extrude profile={profile} height={z}\n"
        elif family == "hole":
            radius = round(rng.uniform(3, 10), 2)
            script = ("основа = box size=[60,60,20]\n"
                      f"сверло = cylinder radius={radius} height=30 at=[0,0,-5]\n"
                      "деталь = difference [основа, сверло]\n")
        elif family == "fold_sheet":
            parts = rng.randint(2, 4)
            angle = rng.choice((30, 60, 90, 120, 150))
            sharp = rng.choice((0, 1))
            script = (f"деталь = fold_sheet width=80 length=200 thickness=1 parts={parts} "
                      f"angle={angle} gap=1 sharp={sharp}\n")
        elif family == "groove":
            depth = rng.choice((0.2, 0.4, 0.6))
            script = ("лист = sheet width=80 length=80 thickness=1\n"
                      f"деталь = складка лист from=[-40,0,1] to=[40,0,1] r=3 depth={depth} "
                      "mode=канавка taper=0\n")
        elif family == "gear":
            teeth = rng.choice((12, 20, 30))
            module = rng.choice((1, 2, 3))
            thickness = rng.choice((3, 5, 8))
            script = f"деталь = gear teeth={teeth} module={module} thickness={thickness}\n"
        elif family == "pipe":
            angle = rng.choice((0, 45, 90, -45))
            script = f"деталь = pipe length=100 diameter=20 wall=2 angle={angle} radius=45\n"
        elif family == "text":
            glyph = rng.choice(("R", "A", "Ф", "@", "\\"))
            script = f"деталь = text {json.dumps(glyph, ensure_ascii=False)} size=12 depth=1.5\n"
        elif family == "blob":
            script = "деталь = blob spheres=[[0,0,25,18],[0,0,55,13]] blend=8 resolution=3\n"
        else:
            script = "деталь = spring diameter=20 wire=2 turns=3 pitch=5\n"
        cases.append({"id": f"case_{index:03d}_{family}", "family": family, "script": script})
    return cases


def _check_export(result) -> int:
    data = result.glb()
    if len(data) < 20 or data[:4] != b"glTF":
        raise AssertionError("GLB: неверная сигнатура")
    version, declared = struct.unpack_from("<II", data, 4)
    if version != 2 or declared != len(data):
        raise AssertionError("GLB: несогласованная длина или версия")
    return len(data)


def analyze_case(case: dict) -> dict:
    started = time.perf_counter()
    try:
        result = build(case["script"], analyze_model=False)
        if not result.ok:
            raise AssertionError(json.dumps(result.error, ensure_ascii=False))
        solids = result.visible_solids()
        if not solids:
            raise AssertionError("Нет видимых тел")
        objects = []
        for solid in solids:
            m = solid.manifold
            if m.status().name != "NoError":
                raise AssertionError(f"{solid.name}: {m.status().name}")
            if m.is_empty() or m.num_tri() <= 0:
                raise AssertionError(f"{solid.name}: пустая сетка")
            volume = float(m.volume())
            if not math.isfinite(volume) or volume <= 0:
                raise AssertionError(f"{solid.name}: объём {volume}")
            bbox = [float(v) for v in m.bounding_box()]
            if len(bbox) != 6 or not all(math.isfinite(v) for v in bbox):
                raise AssertionError(f"{solid.name}: некорректный bbox")
            objects.append({"name": solid.name, "tris": int(m.num_tri()),
                            "volume_mm3": volume, "bbox": bbox})
        glb_bytes = _check_export(result)
        return {"ok": True, "objects": objects, "glb_bytes": glb_bytes,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "traceback": traceback.format_exc()[-4000:],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}


def _process_entry(case: dict, channel) -> None:
    channel.put(analyze_case(case))


def _run_isolated(case: dict, timeout: float) -> dict:
    started = time.perf_counter()
    ctx = mp.get_context("spawn")
    channel = ctx.Queue()
    process = ctx.Process(target=_process_entry, args=(case, channel))
    process.start()
    try:
        process.join(timeout)
        if process.is_alive():
            process.terminate()
            process.join(10)
            return {"ok": False, "error": f"timeout {timeout:g} с",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}
        try:
            return channel.get(timeout=1.0)
        except queue.Empty:
            return {"ok": False,
                    "error": f"процесс завершился без результата, exit={process.exitcode}",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)}
    finally:
        channel.close()
        channel.join_thread()
        process.close()


def run_fuzz(count: int = 24, seed: int = 20261102, timeout: float = 20.0,
             output: str | Path | None = None) -> dict:
    if count < 1:
        raise ValueError("cases должно быть положительным")
    if timeout <= 0:
        raise ValueError("timeout должен быть положительным")
    cases = make_cases(count, seed)
    results = []
    for case in cases:
        result = _run_isolated(case, timeout)
        results.append({"case": {key: value for key, value in case.items() if key != "script"},
                        "script_sha256": hashlib.sha256(
                            case["script"].encode("utf-8")).hexdigest(),
                        "result": result})
    passed = sum(1 for item in results if item["result"]["ok"])
    report = {
        "schema": "forma-fuzz-report-v1",
        "seed": seed,
        "timeout_s": timeout,
        "environment": _environment(),
        "ok": passed == len(results),
        "summary": {"cases": len(results), "passed": passed, "failed": len(results) - passed},
        "results": results,
    }
    if output:
        destination = Path(output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        for case, item in zip(cases, results):
            if item["result"]["ok"]:
                continue
            repro = destination.parent / f"{destination.stem}-repros"
            repro.mkdir(parents=True, exist_ok=True)
            (repro / f"{case['id']}.forma").write_text(case["script"], encoding="utf-8")
            (repro / f"{case['id']}.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cases", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--timeout", type=float, default=20.0, help="timeout одного случая, с")
    parser.add_argument("--output", default="fuzz-report.json")
    parser.add_argument("--allow-failures", action="store_true")


def run_cli(args) -> int:
    try:
        report = run_fuzz(args.cases, args.seed, args.timeout, args.output)
        for item in report["results"]:
            result = item["result"]
            mark = "OK  " if result["ok"] else "FAIL"
            print(f"[{mark}] {item['case']['id']}: {result['elapsed_ms']:.1f} мс"
                  + ("" if result["ok"] else f" — {result.get('error')}"))
        summary = report["summary"]
        print(f"FUZZ: {summary['passed']}/{summary['cases']}; seed={args.seed}; "
              f"отчёт {args.output}")
        return 0 if report["ok"] or args.allow_failures else 1
    except Exception as exc:
        print(f"ОШИБКА FUZZ: {exc}", file=sys.stderr)
        return 2


def main(argv=None) -> int:
    mp.freeze_support()
    parser = argparse.ArgumentParser(description="Детерминированный fuzz DSL и GLB")
    configure_parser(parser)
    return run_cli(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
