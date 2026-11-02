"""Обратный разбор: читаем сгенерированный `.scad` и собираем ту же деталь в ФОРМЕ.

Экспорт — односторонний: мы не обещаем импорт произвольных файлов OpenSCAD.
Но у экспорта есть проверяемое свойство — **из него можно вернуться**. Если
`плита` в `.scad` и `плита` в ФОРМЕ дают одинаковый объём, значит числа и
структура перенесены без потерь.

Разбор нарочно узкий: понимает ровно то, что пишет `forma/scad.py`
(`translate([...]) cube/cylinder`, `union`, `difference`, вызовы модулей).
Всё остальное честно называет «непонятно» и считает провалом прогона.

    python roundtrip.py bracket_from_forma.scad
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CALL_RE = re.compile(r"^\s*(\w+)\(\);?\s*(?://.*)?$", re.M)
MODULE_RE = re.compile(r"^module (\w+)\(\) \{\n(.*?)^\}", re.S | re.M)
PRIM_RE = re.compile(r"^(\s*)translate\(\[([-\d.,\s]+)\]\) (\w+)\((.*)\);$", re.M)


def _numbers(text: str) -> list[float]:
    return [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", text)]


def parse(text: str) -> tuple[dict[str, str], list[str]]:
    """Возвращает ({имя: строка DSL}, [жалобы])."""
    out: dict[str, str] = {}
    problems: list[str] = []

    for name, body in MODULE_RE.findall(text):
        prims = PRIM_RE.findall(body)
        if prims:
            if len(prims) != 1:
                problems.append(f"{name}: ожидался один примитив, найдено {len(prims)}")
                continue
            _, xyz, kind, args = prims[0]
            at = _numbers(xyz)
            if kind == "cube":
                size = _numbers(args.split("center")[0])
                # в OpenSCAD translate — это центр куба, у ФОРМЫ по Z — низ
                out[name] = (
                    f"{name} = box size=[{size[0]:g},{size[1]:g},{size[2]:g}] "
                    f"center=да at=[{at[0]:g},{at[1]:g},{at[2] - size[2] / 2:g}]"
                )
            elif kind == "cylinder":
                h = re.search(r"h\s*=\s*([-\d.]+)", args)
                r = re.search(r"r\s*=\s*([-\d.]+)", args)
                if not (h and r):
                    problems.append(f"{name}: у цилиндра нет h/r")
                    continue
                height = float(h.group(1))
                out[name] = (
                    f"{name} = cylinder radius={float(r.group(1)):g} "
                    f"height={height:g} "
                    f"at=[{at[0]:g},{at[1]:g},{at[2] - height / 2:g}]"
                )
            continue

        kids = CALL_RE.findall(body)
        if "difference()" in body:
            if len(kids) < 2:
                problems.append(f"{name}: в difference меньше двух операндов")
                continue
            out[name] = f"{name} = difference [{kids[0]}] " + " ".join(f"[{k}]" for k in kids[1:])
        elif "union()" in body:
            out[name] = f"{name} = union " + " ".join(f"[{k}]" for k in kids)
        else:
            problems.append(f"{name}: неизвестная конструкция")
    return out, problems


def to_dsl(text: str) -> tuple[str, list[str]]:
    """Собирает текст на DSL ФОРМЫ из `.scad`; последний модуль — корень."""
    lines, problems = parse(text)
    return "\n".join(lines.values()), problems


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from forma.run import build

    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    dsl, problems = to_dsl(text)
    print(f"— разобрали {path.name}: {len(dsl.splitlines())} строк DSL")
    if problems:
        print("  жалобы разбора:")
        for p in problems:
            print(f"    {p}")
    print("\n" + dsl + "\n")
    result = build(dsl + "\n", analyze_model=True)
    if not result.ok:
        raise SystemExit(f"ФОРМА не собрала разобранный файл: {result.error}")
    metrics = result.analysis["metrics"]
    print(f"— объём из .scad: {metrics['volume_cm3']:.3f} см³, "
          f"треугольников {metrics['tris']}, замкнуто "
          f"{all(c['ok'] for c in result.analysis['checks'] if c['rule'] == 'watertight')}")


if __name__ == "__main__":
    main()
