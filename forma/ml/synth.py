"""Данные для обучения: случайные сцены из примитивов и их честные метрики.

Идея простая и она же главная: **данные делает сам движок**. Мы не размечаем
ничего руками — генерируем сценарий на языке ФОРМЫ, строим его через `build()`
и забираем метрики, которые посчитала геометрия: объём, род (число сквозных
отверстий), число частей, треугольники, габарит. Метки точные по построению,
их нельзя «перепутать».

Формат строки (JSON Lines, по одной сцене на строку):

    {"dsl": "o0 = box size=[30,20,10] center=да at=[0,0,0]", "y": [3.48, 0, 1, 3.9, 30, 20, 10]}

где y — семь чисел-ответов:
    0: log10(объём в мм³)
    1: род (сквозные отверстия)
    2: число частей
    3: log10(треугольников)
    4,5,6: габарит по X, Y, Z в мм
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

__all__ = ["SAMPLE", "make_scene", "scene_row", "generate", "N_TARGETS"]

N_TARGETS = 7

#: примитивы, у которых параметры стабильны и сцена почти всегда собирается
_TABLE = [
    ("box", lambda r: f"box size=[{r.randint(10, 60)},{r.randint(10, 60)},{r.randint(10, 60)}]", True),
    ("cylinder", lambda r: f"cylinder radius={r.randint(5, 30)} height={r.randint(10, 60)}", True),
    ("sphere", lambda r: f"sphere radius={r.randint(5, 30)}", False),
    ("cone", lambda r: f"cone radius={r.randint(5, 25)} height={r.randint(10, 50)}", True),
    ("prism", lambda r: f"prism sides={r.randint(3, 8)} radius={r.randint(8, 25)} height={r.randint(10, 40)}", True),
    ("pyramid", lambda r: f"pyramid sides={r.randint(3, 8)} radius={r.randint(8, 25)} height={r.randint(10, 40)}", True),
    ("sheet", lambda r: f"sheet width={r.randint(20, 80)} length={r.randint(20, 80)} thickness=2", True),
    ("torus", lambda r: f"torus outer={r.randint(30, 70)} inner={r.randint(8, 20)}", False),
    ("washer", lambda r: f"washer outer={r.randint(20, 50)} inner={r.randint(5, 15)} thickness=3", False),
]


def make_scene(rng: random.Random, max_objects: int = 3) -> str:
    """Случайная сцена из 1…max_objects примитивов. Детерминирована по rng."""
    n = rng.randint(1, max_objects)
    lines = []
    for k in range(n):
        _name, body, center = rng.choice(_TABLE)
        args = body(rng)
        pos = f"at=[{rng.randint(-30, 30)},{rng.randint(-30, 30)},{k * 30}]"
        lines.append(f"o{k} = {args}{' center=да' if center else ''} {pos}")
    return "\n".join(lines)


def scene_row(dsl: str) -> dict | None:
    """Строит сцену и возвращает (dsl, y) или None, если сцена не собралась."""
    from forma.run import build

    r = build(dsl)
    if not r.ok:
        return None
    m = r.analysis["metrics"]
    vol = max(float(m["volume_cm3"]) * 1000.0, 1e-6)      # см³ → мм³
    tris = max(float(m["tris"]), 1.0)
    sx, sy, sz = (float(v) for v in m["size"])
    y = [math.log10(vol), float(m["genus"]), float(m["parts"]),
         math.log10(tris), sx, sy, sz]
    return {"dsl": dsl, "y": [round(v, 4) for v in y]}


def generate(out: Path, scenes: int = 400, seed: int = 0, max_objects: int = 3,
             workers: int = 2, log=None) -> int:
    """Пишет JSONL и возвращает число удачных сцен.

    Перебор параллельный: `build()` держит GIL не всё время, а объединение
    мешей в manifold3d считается вне Python, поэтому 2 процесса на 2 ядрах
    дают почти двукратный выигрыш.
    """
    import multiprocessing as mp

    rng = random.Random(seed)
    tasks = [make_scene(rng, max_objects) for _ in range(scenes)]
    out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if workers > 1:
        with mp.Pool(workers) as pool:
            # imap (не imap_unordered): порядок строк в датасете должен быть
            # одинаковым при каждом запуске, иначе обучение не воспроизводится
            for i, row in enumerate(pool.imap(scene_row, tasks, chunksize=8), 1):
                if row is not None:
                    rows.append(row)
                if log and i % 100 == 0:
                    log(f"  собрано {i} из {scenes}, удачных {len(rows)}")
    else:
        for i, dsl in enumerate(tasks, 1):
            row = scene_row(dsl)
            if row is not None:
                rows.append(row)
            if log and i % 100 == 0:
                log(f"  собрано {i} из {scenes}, удачных {len(rows)}")
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


def load(path: Path) -> tuple[list[str], list[list[float]]]:
    dsl, ys = [], []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            dsl.append(row["dsl"])
            ys.append(row["y"])
    return dsl, ys
