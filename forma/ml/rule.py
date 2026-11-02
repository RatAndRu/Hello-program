"""Правило вместо нейросети: точный расчёт метрик по разобранному сценарию.

Нужно для честного сравнения. Нейросеть на 144 тыс. параметров угадывает
габарит с ошибкой в десяток миллиметров, а разбор строки плюс школьная
формула дают ноль. Это не значит, что сеть плохая — это значит, что **разбор
и арифметику нейросети отдавать не надо**. Сеть нужна там, где правила нет:
по картинке понять форму, придумать сцену, выбрать приём.

Поддержаны те же примитивы, что и в `synth.py`. Формулы проверены прогоном
`build()` — см. таблицу в docstring ниже:

    torus   outer, inner — радиусы средней линии и трубки (bbox = 2(outer+inner))
    washer  outer, inner — диаметры, thickness — толщина
    prism   radius — радиус описанной окружности, n сторон
    pyramid sides, radius, height
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

__all__ = ["parse_scene", "metrics_of"]


@dataclass
class Obj:
    kind: str
    num: dict[str, float]
    at: tuple[float, float, float]


_NUM = r"(-?\d+(?:\.\d+)?)"


def _nums(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, val in re.findall(r"([A-Za-zА-Яа-я_]+)=" + _NUM, text):
        out[key] = float(val)
    for val in re.findall(r"size=\[([^\]]+)\]", text):
        vals = [float(v) for v in val.split(",")]
        out["sx"], out["sy"], out["sz"] = vals[0], vals[1], vals[2]
    return out


def parse_scene(dsl: str) -> list[Obj]:
    objs: list[Obj] = []
    for line in dsl.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        body = line.split("=", 1)[1].strip()
        kind = body.split()[0]
        n = _nums(body)
        m = re.search(r"at=\[([^\]]+)\]", body)
        at = (0.0, 0.0, 0.0)
        if m:
            vals = [float(v) for v in m.group(1).split(",")]
            at = (vals[0], vals[1], vals[2])
        objs.append(Obj(kind, n, at))
    return objs


def _solid(o: Obj) -> tuple[float, float, float, float]:
    """(объём, sx, sy, sz) в мм³ и мм; at не учитывается — сдвиг добавим снаружи."""
    n, k = o.num, o.kind
    if k == "box":
        sx, sy, sz = n["sx"], n["sy"], n["sz"]
        return sx * sy * sz, sx, sy, sz
    if k == "cylinder":
        r, h = n["radius"], n["height"]
        return math.pi * r * r * h, 2 * r, 2 * r, h
    if k == "sphere":
        r = n["radius"]
        return 4 / 3 * math.pi * r ** 3, 2 * r, 2 * r, 2 * r
    if k == "cone":
        r, h = n["radius"], n["height"]
        return math.pi * r * r * h / 3, 2 * r, 2 * r, h
    if k == "prism":
        s, r, h = n["sides"], n["radius"], n["height"]
        area = s / 2 * r * r * math.sin(2 * math.pi / s)
        # габарит по X — диаметр, по Y — проекция на перпендикуляр
        return area * h, 2 * r, 2 * r * abs(math.cos(math.pi / s)), h
    if k == "pyramid":
        s, r, h = n["sides"], n["radius"], n["height"]
        area = s / 2 * r * r * math.sin(2 * math.pi / s)
        return area * h / 3, 2 * r, 2 * r, h
    if k == "sheet":
        w, l, t = n["width"], n["length"], n["thickness"]
        return w * l * t, w, l, t
    if k == "torus":
        big, small = n["outer"], n["inner"]
        big, small = (big + small) / 2, abs(big - small) / 2
        return 2 * math.pi ** 2 * big * small * small, 2 * (big + small), 2 * (big + small), 2 * small
    if k == "washer":
        ro, ri, t = n["outer"] / 2, n["inner"] / 2, n["thickness"]
        return math.pi * (ro * ro - ri * ri) * t, 2 * ro, 2 * ro, t
    raise KeyError(k)


def metrics_of(dsl: str) -> dict[str, float]:
    """Те же семь чисел, что предсказывает сеть, но посчитанные точно.

    Объём — сумма по деталям, габарит — объединение коробок со сдвигом `at`:
    для сцен без взаимного проникновения это точно, иначе — верхняя оценка.
    """
    lo = [1e9] * 3
    hi = [-1e9] * 3
    vol = 0.0
    for o in parse_scene(dsl):
        v, sx, sy, sz = _solid(o)
        vol += v
        for axis, size in enumerate((sx, sy, sz)):
            c = o.at[axis]
            lo[axis] = min(lo[axis], c - size / 2)
            hi[axis] = max(hi[axis], c + size / 2)
    genus = sum(1 for o in parse_scene(dsl) if o.kind in ("torus", "washer"))
    return {
        "log объёма": round(math.log10(max(vol, 1e-6)), 4),
        "род (отверстия)": float(genus),
        "частей": float(len(parse_scene(dsl))),
        "log треугольников": 0.0,          # треугольники зависят от сегментов, не считаем
        "габарит X": round(hi[0] - lo[0], 4),
        "габарит Y": round(hi[1] - lo[1], 4),
        "габарит Z": round(hi[2] - lo[2], 4),
    }
