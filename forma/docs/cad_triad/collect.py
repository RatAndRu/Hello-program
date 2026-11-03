"""Сборка результатов теста трёх CAD в одну таблицу.

Читает `out/*.json` (их пишут сами инструменты и скрипты обвязки), считает
независимые метрики по STL через trimesh и печатает таблицу.

    python3 collect.py --out out

Смысл: числа в разных столбцах должны быть посчитаны **одинаково**, иначе
сравнение врёт. Поэтому объём и треугольники везде берутся из STL одним и тем
же trimesh, а «свои» числа инструмента показываются отдельным столбцом.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import trimesh

ROOT = Path(__file__).resolve().parents[3]  # корень репозитория
SOURCES = {
    "openscad": ROOT / "forma/docs/cad_triad/plate.scad",
    "forma": ROOT / "forma/docs/cad_triad/plate.f3d",
    "freecad_part": ROOT / "forma/docs/cad_triad/plate_part.py",
    "freecad_sketch": ROOT / "forma/docs/cad_triad/plate_sketch.py",
}
STLS = {
    "openscad": "plate_openscad.stl",
    "forma": "plate_forma.stl",
    "freecad_part": "plate_freecad.stl",
    "solvespace": "plate_solvespace.stl",
}
LABELS = {
    "openscad": "OpenSCAD (текст, CSG)",
    "freecad_part": "FreeCAD Part (Python, CSG)",
    "freecad_sketch": "FreeCAD Sketcher (ограничения)",
    "solvespace": "SolveSpace (CLI, чужой тест)",
    "forma": "ФОРМА 3D (наш DSL)",
}
#: эталон, посчитанный в Python без CAD: (80·60 − 2·π·2,5²)·6 / 1000
REFERENCE_CM3 = (80 * 60 - 2 * 3.141592653589793 * 2.5 ** 2) * 6 / 1000.0


def stl_stats(path: Path) -> dict:
    if not path.exists():
        return {}
    mesh = trimesh.load(path, force="mesh")
    return {
        "volume_cm3": round(abs(float(mesh.volume)) / 1000.0, 4),
        "tris": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "size": [round(float(v), 2) for v in mesh.extents],
    }


def source_stats(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith(("#", "//"))]
    return {"lines": len(lines), "bytes": len(text.encode("utf-8"))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    out = Path(args.out)

    data: dict[str, dict] = {}
    for path in sorted(out.glob("*.json")):
        try:
            data[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data[path.stem] = {"json_error": True}
    for key, name in STLS.items():
        stats = stl_stats(out / name)
        if stats:
            data.setdefault(key, {}).update(stats)

    rows = []
    for key in ("openscad", "freecad_part", "freecad_sketch", "solvespace", "forma"):
        item = dict(data.get(key, {}))
        item.update({k: v for k, v in source_stats(SOURCES.get(key, Path("/нет"))).items()
                     if k not in item})
        item["label"] = LABELS[key]
        rows.append(item)

    lines = []
    lines.append("=" * 100)
    lines.append("ОДНА ДЕТАЛЬ (плита 80×60×6, два отверстия ø5) — ЧЕТЫРЕ ИНСТРУМЕНТА")
    lines.append(f"эталон без CAD: {REFERENCE_CM3:.4f} см³")
    lines.append("=" * 100)
    head = f"{'инструмент':32s}{'строк':>6s}{'байт':>7s}{'сборка':>9s}{'объём':>9s}{'Δ%':>7s}{'трис':>6s}{'свой объём':>12s}"
    lines.append(head)
    for r in rows:
        vol = r.get("volume_cm3")
        delta = f"{(vol - REFERENCE_CM3) / REFERENCE_CM3 * 100:+.2f}" if isinstance(vol, (int, float)) else "—"
        build = r.get("build_ms")
        build_txt = f"{build:.0f} мс" if isinstance(build, (int, float)) else "—"
        own = r.get("tool_volume_cm3")
        own_txt = f"{own:.3f}" if isinstance(own, (int, float)) else "нет"
        lines.append(
            f"{r['label'][:31]:32s}{str(r.get('lines', '—')):>6s}{str(r.get('bytes', '—')):>7s}"
            f"{build_txt:>9s}"
            f"{(f'{vol:.3f}' if isinstance(vol, (int, float)) else '—'):>9s}{delta:>7s}"
            f"{str(r.get('tris', '—')):>6s}{own_txt:>12s}"
        )

    lines.append("")
    lines.append("Что инструмент умеет сам (без сторонних программ и без STL):")
    for r in rows:
        caps = []
        if r.get("valid") is not None:
            caps.append(f"проверка годности: {'да' if r['valid'] else 'нет'}")
        if r.get("watertight") is not None:
            caps.append(f"замкнутость: {'да' if r['watertight'] else 'нет'}")
        if r.get("step_bytes"):
            caps.append(f"STEP: {r['step_bytes'] / 1024:.0f} КБ")
        if r.get("step_roundtrip_cm3"):
            caps.append(f"STEP обратно: {r['step_roundtrip_cm3']:.3f} см³")
        if r.get("dof_known"):
            caps.append(f"степени свободы: {r.get('FullyConstrained', '—')}")
        if r.get("notes"):
            caps.append(r["notes"])
        lines.append(f"  {r['label'][:31]:32s} {'; '.join(caps) or 'только STL'}")

    edits = [r for r in rows if r.get("volume_after_edit_cm3")]
    if edits:
        lines.append("")
        lines.append("Параметрическая правка (ширина 80 → 120 мм):")
        for r in edits:
            lines.append(
                f"  {r['label'][:31]:32s} {r.get('edit_ms', '—')} мс, "
                f"объём {r['volume_after_edit_cm3']:.3f} см³ "
                f"(ожидание {r.get('expected_after_edit_cm3', 0):.3f}), "
                f"правок в тексте: {r.get('edit_chars', 0)}"
            )

    text = "\n".join(lines)
    print(text)
    (out / "table.txt").write_text(text + "\n", encoding="utf-8")
    (out / "raw.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
