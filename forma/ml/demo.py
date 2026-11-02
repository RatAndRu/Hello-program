#!/usr/bin/env python3
"""Сквозной прогон: данные → обучение → файл весов → инференс.

    cd forma
    python ml/demo.py                # 400 сцен, ~2 минуты
    python ml/demo.py --scenes 2000 --epochs 600

Печатает ровно то, о чём спрашивают: где лежит нейросеть, сколько она весит,
что внутри файла и насколько ошибается на сценах, которых не видела.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml import synth, train                              # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "weights"


def hexdump(path: Path, limit: int = 96) -> None:
    data = path.read_bytes()[:limit]
    print(f"  первые {len(data)} байт файла {path.name}:")
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexed = " ".join(f"{b:02x}" for b in chunk)
        print(f"    {i:04x}  {hexed}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", type=int, default=400)
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--keep", action="store_true", help="не удалять старые данные")
    args = ap.parse_args()

    if not args.keep and DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(parents=True, exist_ok=True)

    print("1. Данные: случайные сцены строятся движком, метки считает геометрия")
    t0 = time.time()
    good = synth.generate(DATA / "scenes.jsonl", scenes=args.scenes, workers=args.workers,
                          log=lambda s: print(s, flush=True))
    gen = time.time() - t0
    dsl, ys = synth.load(DATA / "scenes.jsonl")
    per_scene = gen / max(args.scenes, 1)
    print(f"   годных сцен: {good} из {args.scenes} ({good / args.scenes:.0%}), "
          f"время {gen:.1f} с, {per_scene * 1000:.0f} мс на сцену")
    print(f"   в датасете {len(dsl)} строк, {sum(len(s) for s in dsl) // 1024} КБ текста")
    print(f"   пример: {dsl[0]!r} → {ys[0]}")

    print("\n2. Обучение головы «сценарий → метрики»")
    rep = train.train(DATA / "scenes.jsonl", OUT, hidden=args.hidden,
                      epochs=args.epochs, log=lambda s: print(s, flush=True))

    print("\n3. Что получилось")
    print(f"   параметров: {rep['params']:,}   файл весов: {rep['bytes'] / 1024:.0f} КБ   "
          f"словарь: {rep['vocab']} токенов")
    print(f"   обучение: {rep['seconds']} с на 2 ядрах, сцен: {rep['train']} / "
          f"{rep['val']} / {rep['test']} (обучение / проверка / тест)")
    print(f"   средняя ошибка на новых сценах: {rep['metrics']['mae_mean']:.3f} "
          f"(предсказание средним дало бы {rep['baseline_mae']:.3f})")
    for name, mae in rep["metrics"]["mae"].items():
        r2 = rep["metrics"]["r2"][name]
        print(f"     {name:18s} ошибка {mae:8.2f}   R² {r2:6.2f}")

    print("\n4. То же правило, но без сети: разбор строки и школьная формула")
    from ml.rule import metrics_of
    dsl_te, y_te = synth.load(DATA / "scenes.jsonl")
    idx = train.split(len(dsl_te), seed=0)[2]
    rule_err, net_err = [], []
    keys = ["log объёма", "род (отверстия)", "частей", "log треугольников",
            "габарит X", "габарит Y", "габарит Z"]
    for i in idx:
        m = metrics_of(dsl_te[i])
        rule_err.append([abs(m[k] - y_te[i][j]) for j, k in enumerate(keys)])
    import numpy as np
    rule_mae = np.mean(rule_err, axis=0)
    net_mae = np.array([rep["metrics"]["mae"][k] for k in keys])
    print(f"   {'величина':20s} {'сеть':>8s} {'правило':>8s}")
    for j, k in enumerate(keys):
        print(f"   {k:20s} {net_mae[j]:8.2f} {rule_mae[j]:8.2f}")
    print("   вывод: разбор и арифметику отдаём правилу, сеть — только туда,")
    print("   где правила нет (картинка → форма, придумать сцену, выбрать приём).")

    print("\n5. Где живёт нейросеть")
    for name in ("vocab.json", "head.json", "head.safetensors"):
        p = OUT / name
        print(f"   {p.relative_to(ROOT)}  —  {p.stat().st_size / 1024:.1f} КБ")
    hexdump(OUT / "head.safetensors")
    cfg = json.loads((OUT / "head.json").read_text(encoding="utf-8"))
    print(f"   head.json: {json.dumps({k: cfg[k] for k in ('kind', 'n_in', 'n_hidden', 'n_out', 'n_params')}, ensure_ascii=False)}")

    print("\n6. Инференс из файла (кода сети уже нет — только веса)")
    samples = [
        "o0 = box size=[30,20,10] center=да at=[0,0,0]",
        "o0 = sphere radius=25 at=[0,0,0]",
        "o0 = box size=[40,40,10] center=да at=[0,0,0]\no1 = cylinder radius=10 height=30 at=[0,0,30]",
    ]
    from forma.run import build
    for text in samples:
        pred = train.predict_text(text, OUT)
        real = build(text)
        if real.ok:
            m = real.analysis["metrics"]
            import math
            truth = {"log объёма": round(math.log10(max(m["volume_cm3"] * 1000, 1e-6)), 2),
                     "род (отверстия)": m["genus"], "частей": m["parts"],
                     "log треугольников": round(math.log10(max(m["tris"], 1)), 2),
                     "габарит X": round(m["size"][0], 1), "габарит Y": round(m["size"][1], 1),
                     "габарит Z": round(m["size"][2], 1)}
            print(f"   {text.splitlines()[0][:44]:44s} "
                  f"сеть: объём {pred['log объёма']:5.2f}, габарит "
                  f"{pred['габарит X']:5.1f}×{pred['габарит Y']:4.1f}×{pred['габарит Z']:4.1f} | "
                  f"движок: {truth['log объёма']:5.2f}, "
                  f"{truth['габарит X']:5.1f}×{truth['габарит Y']:4.1f}×{truth['габарит Z']:4.1f}")

    print("\n7. Размер при других настройках (тот же код, другие числа)")
    for hidden in (64, 256, 1024):
        n_in, n_out = rep["vocab"] + 512, 7      # токены + хеш-корзины пар
        params = n_in * hidden + hidden + hidden * n_out + n_out
        print(f"   скрытый слой {hidden:5d}: {params:8,} параметров, "
              f"{params * 4 / 1024:7.0f} КБ в float32, {params / 1024:7.0f} КБ в int8")


if __name__ == "__main__":
    main()
