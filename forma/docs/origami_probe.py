#!/usr/bin/env python3
"""Замеры сгибания бумаги в ФОРМЕ — числа для docs/origami_analysis.md.

Запуск (из каталога forma, нужен numpy и manifold3d):
    python docs/origami_probe.py

Печатает markdown-таблицы. Ничего не меняет в движке: только строит сценарии
и читает `analysis["metrics"]`. Полный прогон — около полутора минут, потому что
второй сгиб перебирается по сетке направлений и смещений.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forma.run import build  # noqa: E402


def one(script: str):
    t0 = time.time()
    r = build(script)
    dt = time.time() - t0
    if not r.ok:
        err = r.error.get("message") if isinstance(r.error, dict) else str(r.error)
        return None, dt, err
    return r.analysis["metrics"], dt, None


def row(tag, m, dt, err):
    if m is None:
        return f"| {tag} | — | — | — | — | **ошибка:** {err} |"
    size = ", ".join(f"{v:.1f}" for v in m["size"])
    wall = m.get("wall")
    wall_txt = f"{wall['min']:.2f}" if wall and wall.get("min") is not None else "—"
    return (f"| {tag} | {dt:.2f} | {m['tris']} | {size} | {wall_txt} | "
            f"объём {m['volume_cm3']:.2f} см³, род {m['genus']} |")


def main() -> None:
    print("## 1. Один сгиб: угол и цена\n")
    print("| сценарий | время, с | треугольников | габарит, мм | мин. стенка, мм | итог |")
    print("|---|---:|---:|---|---:|---|")
    base = "л = sheet width=80 length=80 thickness=0.5\n"
    for tag, tail in [("плоский лист", ""),
                      ("сгиб 30°", "с = сгиб л at=[0,0,0.5] dir=0 angle=30"),
                      ("сгиб 90°", "с = сгиб л at=[0,0,0.5] dir=0 angle=90"),
                      ("сгиб 150°", "с = сгиб л at=[0,0,0.5] dir=0 angle=150"),
                      ("сгиб 179°", "с = сгиб л at=[0,0,0.5] dir=0 angle=179"),
                      ("сгиб 179°, gap=0", "с = сгиб л at=[0,0,0.5] dir=0 angle=179 gap=0"),
                      ("биг-линия: складка r=0.5",
                       "с = складка л from=[-40,0,0.5] to=[40,0,0.5] r=0.5 depth=0.1")]:
        m, dt, err = one(base + tail)
        print(row(tag, m, dt, err))

    print("\n## 2. Толщина пакета после складывания (лист 0.5 мм)\n")
    print("| сгибов | слоёв | идеал, мм | факт по Z, мм | перерасход |")
    print("|---:|---:|---:|---:|---:|")
    t = 0.5
    script = f"л = sheet width=80 length=80 thickness={t}\n"
    prev = "л"
    for i in range(4):
        m, _, err = one(script)
        if m is None:
            print(f"| {i} | {2 ** i} | {2 ** i * t:.1f} | — | ошибка: {err} |")
            break
        ideal = 2 ** i * t
        fact = m["size"][2]
        print(f"| {i} | {2 ** i} | {ideal:.1f} | {fact:.2f} | {fact / ideal:.2f}× |")
        z = round(m["bbox"][5], 1)
        script += f"с{i} = сгиб {prev} at=[0,0,{z}] dir=0 angle=179\n"
        prev = f"с{i}"

    print("\n## 3. Второй сгиб после первого: сколько сочетаний работает\n")
    first_120 = ("л = sheet width=80 length=80 thickness=0.5\n"
                 "а = сгиб л at=[0,0,0.5] dir=0 angle=120\n")
    first_179 = ("л = sheet width=80 length=80 thickness=0.5\n"
                 "а = сгиб л at=[0,0,0.5] dir=0 angle=179\n")
    for label, head, angles, lines in [("первый сгиб 120° (деталь объёмная)", first_120, (0, 45, 90, 135),
                                        (-30, -15, 0, 15, 30)),
                                       ("первый сгиб 179° (деталь плоская)", first_179, (0, 45, 90, 135),
                                        (-25, -10, 0, 10, 25))]:
        ok = 0
        total = 0
        errors: dict[str, int] = {}
        for d in angles:
            for y in lines:
                total += 1
                s = head + f"б = сгиб а at=[0,{y},0.5] dir={d} angle=120"
                _, _, err = one(s)
                if err is None:
                    ok += 1
                else:
                    errors[err] = errors.get(err, 0) + 1
        print(f"* **{label}:** работает {ok} из {total}.")
        for msg, cnt in sorted(errors.items(), key=lambda kv: -kv[1]):
            print(f"  * {cnt}× «{msg}»")

    print("\n## 4. Разгибание после сгиба\n")
    print("| попытка | итог |")
    print("|---|---|")
    for tag, tail in [
        ("тем же side", "с2 = сгиб с1 at=[0,0,0.5] dir=0 angle=150"),
        ("side=-1", "с2 = сгиб с1 at=[0,0,0.5] dir=0 angle=150 side=-1"),
        ("по линии на верхней плоскости", "с2 = сгиб с1 at=[0,0,1.5] dir=0 angle=60"),
    ]:
        m, dt, err = one("л = sheet width=80 length=80 thickness=0.5\n"
                         "с1 = сгиб л at=[0,0,0.5] dir=0 angle=150\n" + tail)
        print(f"| {tag} | {'построилось' if err is None else '**' + err + '**'} |")

    print("\n## 5. Анимация складывания через morph\n")
    m, dt, err = one("A = 1\nл = sheet width=80 length=80 thickness=0.5\n"
                     "с = сгиб л at=[0,0,0.5] dir=0 angle=A\n"
                     "animate kind=morph param=A from=1 to=180 samples=24 seconds=3")
    print(f"* один кадр модели с параметром угла: **{dt:.2f} с** "
          f"({m['tris'] if m else '—'} треугольников).")
    print("* 24 кадра — это 24 полные пересборки: "
          f"≈ **{dt * 24:.0f} с** на трёхсекундный ролик.")
    print("* `animate kind=morph param=A from=0 …` невозможен: у `сгиб` минимум "
          "`angle` = 1°.")
    for value in (0, 1, 45, 180):
        s = (f"A = {value}\nл = sheet width=80 length=80 thickness=0.5\n"
             "с = сгиб л at=[0,0,0.5] dir=0 angle=A")
        m, dt, err = one(s)
        print(f"  * A={value:3d} → {'ok' if err is None else err}")


if __name__ == "__main__":
    main()
