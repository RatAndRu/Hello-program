"""Сборка результатов теста трёх CAD в одну таблицу.

Читает `out/*.json` (их пишут сами инструменты и скрипты обвязки), считает
независимые метрики по STL через trimesh и печатает две таблицы:

1. **что мы померили сами** — одинаковым trimesh по STL, поэтому столбцы сравнимы;
2. **что инструмент сообщает сам** — без сторонних программ и без STL.

    python3 collect.py --out out

Смысл разделения: «замкнутость» от trimesh и «замкнутость» от FreeCAD — разные
вещи, и смешивать их в одном столбце нельзя.
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
    try:
        mesh = trimesh.load(path, force="mesh")
        volume = abs(float(mesh.volume)) / 1000.0
        return {
            "volume_cm3": round(volume, 4),
            "tris": int(len(mesh.faces)),
            "watertight": bool(mesh.is_watertight),
            "size": [round(float(v), 2) for v in mesh.extents],
        }
    except Exception as exc:  # noqa: BLE001
        return {"stl_error": str(exc)}


def source_stats(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines()
             if ln.strip() and not ln.strip().startswith(("#", "//"))]
    return {"lines": len(lines), "bytes": len(text.encode("utf-8"))}


def fmt_num(value, digits: int = 3, suffix: str = "") -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}{suffix}"
    return "—"


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
        item.update({k: v for k, v in source_stats(SOURCES.get(key, Path("/none"))).items()
                     if k not in item})
        item["label"] = LABELS[key]
        item["same_part"] = key != "solvespace"
        rows.append(item)

    lines = ["=" * 104,
             "ОДНА ДЕТАЛЬ (плита 80×60×6, два отверстия ø5) — ЧЕТЫРЕ ИНСТРУМЕНТА",
             f"эталон без CAD: {REFERENCE_CM3:.4f} см³",
             "=" * 104,
             "",
             "Таблица 1. Что померили мы сами: STL прочитан одним и тем же trimesh",
             ""]
    lines.append(f"{'инструмент':32s}{'строк':>6s}{'байт':>7s}{'сборка':>9s}"
                 f"{'объём':>9s}{'Δ%':>7s}{'трис':>6s}{'замкнут':>9s}")
    for r in rows:
        vol = r.get("volume_cm3")
        if not r["same_part"]:
            delta = "не та"
        elif isinstance(vol, (int, float)):
            delta = f"{(vol - REFERENCE_CM3) / REFERENCE_CM3 * 100:+.2f}"
        else:
            delta = "—"
        lines.append(
            f"{r['label'][:31]:32s}"
            f"{str(r.get('lines', '—')):>6s}{str(r.get('bytes', '—')):>7s}"
            f"{fmt_num(r.get('build_ms'), 0, ' мс') if r.get('build_ms') else '—':>9s}"
            f"{fmt_num(vol):>9s}{delta:>7s}"
            f"{str(r.get('tris', '—')):>6s}"
            f"{('да' if r.get('watertight') else 'нет') if 'watertight' in r else '—':>9s}"
        )

    lines += ["", "Таблица 2. Что инструмент сообщает сам, без сторонних программ", ""]
    lines.append(f"{'инструмент':32s}{'свой объём':>12s}{'годность':>10s}"
                 f"{'STEP':>10s}{'STEP→объём':>12s}{'ограничения':>12s}")
    for r in rows:
        own = r.get("tool_volume_cm3")
        valid = r.get("valid")
        step = r.get("step_bytes")
        back = r.get("step_roundtrip_cm3")
        dof = r.get("FullyConstrained")
        lines.append(
            f"{r['label'][:31]:32s}"
            f"{fmt_num(own) if own is not None else 'нет':>12s}"
            f"{('да' if valid else 'нет') if valid is not None else 'нет':>10s}"
            f"{(f'{step / 1024:.0f} КБ' if step else 'нет'):>10s}"
            f"{(fmt_num(back) if back is not None else '—'):>12s}"
            f"{(str(dof) if dof is not None else 'нет'):>12s}"
        )
    for r in rows:
        if r.get("notes"):
            lines.append(f"  {r['label'][:31]:32s} {r['notes']}")
        if r.get("stl_error"):
            lines.append(f"  {r['label'][:31]:32s} STL не прочитан: {r['stl_error']}")

    edits = [r for r in rows if r.get("volume_after_edit_tool_cm3")]
    if edits:
        lines += ["", "Таблица 3. Параметрическая правка: ширина 80 → 120 мм", ""]
        for r in edits:
            lines.append(
                f"  {r['label'][:31]:32s} {fmt_num(r.get('edit_ms'), 0, ' мс')}, "
                f"объём {r['volume_after_edit_tool_cm3']:.3f} см³ "
                f"(ожидание {r.get('expected_after_edit_cm3', 0):.3f})"
            )

    text = "\n".join(lines)
    print(text)
    (out / "table.txt").write_text(text + "\n", encoding="utf-8")
    (out / "raw.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
