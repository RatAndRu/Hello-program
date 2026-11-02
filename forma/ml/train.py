"""Обучение головы «сценарий ФОРМЫ → метрики» и честный отчёт по ошибке.

Что делает сеть: читает текст сценария (мешок токенов), выдаёт семь чисел —
log объёма, род, число частей, log треугольников и габарит. Это и есть
«понимание примитивов» в узком, проверяемом смысле: сеть должна предсказать
свойства, которые посчитает геометрия, ещё не строя её.

Проверка устроена так же, как в остальных документах: не «выглядит неплохо»,
а ошибка на **новых** сценах, которых не было в обучении, с разбивкой по
каждому из семи чисел.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from .mlp import MLP
from .synth import N_TARGETS, load
from .tokenizer import Tokenizer

__all__ = ["build_xy", "split", "train", "evaluate", "NAMES"]

NAMES = ["log объёма", "род (отверстия)", "частей", "log треугольников",
         "габарит X", "габарит Y", "габарит Z"]


def build_xy(dsl: list[str], ys: list[list[float]], tok: Tokenizer,
             seq_len: int = 96, n_hash: int = 512) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Текст → числа: частоты токенов плюс хешированные пары соседних токенов.

    Мешок слов (bag of words) теряет порядок: `box size=[30,20,10]` и
    `box size=[10,20,30]` для него одинаковы, а габариты разные. Добавляем
    пары соседних токенов в 512 хеш-корзин — это дешёвая замена свёртке по
    последовательности: число параметров растёт на 512·hidden, зато порядок
    начинает учитываться. Полноценное решение — трансформер (§7 документа).
    """
    n = len(dsl)
    n_in = len(tok) + n_hash
    x = np.zeros((n, n_in), dtype=np.float32)
    for i, text in enumerate(dsl):
        ids = tok.encode(text, seq_len)
        for idx in ids:
            x[i, idx] += 1.0
        for a, b in zip(ids, ids[1:]):
            x[i, len(tok) + (a * 31 + b) % n_hash] += 1.0
    x /= np.maximum(x.sum(axis=1, keepdims=True), 1.0)
    y = np.asarray(ys, dtype=np.float32)
    return x, y, x


def split(n: int, seed: int = 0, val: float = 0.2,
          test: float = 0.2) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    n_test = int(n * test)
    n_val = int(n * val)
    return idx[n_test + n_val:], idx[n_test:n_test + n_val], idx[:n_test]


def normalize(y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu = y.mean(axis=0)
    sd = y.std(axis=0)
    sd[sd < 1e-8] = 1.0
    return (y - mu) / sd, mu, sd


def train(data: Path, out_dir: Path, hidden: int = 256, epochs: int = 400,
          lr: float = 3e-3, batch: int = 64, seed: int = 0, log=print) -> dict:
    dsl, ys = load(data)
    tok = Tokenizer().fit(dsl, min_count=2)
    x, y, _ = build_xy(dsl, ys, tok)

    tr, va, te = split(len(dsl), seed=seed)
    x_tr, y_tr = x[tr], y[tr]
    _, mu, sd = normalize(y_tr)
    y_all = (y - mu) / sd

    net = MLP(x.shape[1], hidden, N_TARGETS, seed=seed)
    t0 = time.time()
    rng = np.random.default_rng(seed)
    best = (1e9, None)
    history: list[float] = []   # ошибка на проверке каждые 10 эпох: видно плато
    for epoch in range(epochs):
        order = rng.permutation(len(tr))
        for start in range(0, len(order), batch):
            sel = order[start:start + batch]
            xb, yb = x_tr[sel], y_all[tr][sel]
            out, h, z = net.forward(xb)
            net.step(net.backward(xb, out, yb, h, z), lr=lr)
        if epoch % 20 == 0 or epoch == epochs - 1:
            val_loss = float(np.mean((net.predict(x[va]) - y_all[va]) ** 2))
            if val_loss < best[0]:
                best = (val_loss, {k: v.copy() for k, v in net.params.items()})
            if epoch % 10 == 0:
                history.append(round(val_loss, 4))
            if log and epoch % 100 == 0:
                log(f"  эпоха {epoch:4d}: ошибка на проверке {val_loss:.4f}")
    if best[1] is not None:
        net.params = best[1]
    dt = time.time() - t0

    metrics = evaluate(net, x[te], y[te], mu, sd)
    out_dir = Path(out_dir)
    size, n_params = net.save(
        out_dir / "head.safetensors", out_dir / "head.json",
        extra={"targets": NAMES, "y_mu": mu.tolist(), "y_sd": sd.tolist(),
               "seq_len": 96, "trained_on": len(tr), "hidden": hidden},
    )
    tok.save(out_dir / "vocab.json")

    report = {"scenes": len(dsl), "train": len(tr), "val": len(va), "test": len(te),
              "vocab": len(tok), "hidden": hidden, "params": n_params,
              "bytes": size, "seconds": round(dt, 1), "metrics": metrics,
              "baseline_mae": baseline_mae(y[te]), "history": history}
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def evaluate(net: MLP, x: np.ndarray, y: np.ndarray, mu, sd) -> dict:
    pred = net.predict(x) * sd + mu
    err = np.abs(pred - y)
    mae = err.mean(axis=0)
    return {"mae": {NAMES[i]: round(float(mae[i]), 3) for i in range(N_TARGETS)},
            "mae_mean": round(float(mae.mean()), 3),
            "r2": {NAMES[i]: round(float(1 - np.mean((pred[:, i] - y[:, i]) ** 2) /
                                        max(np.var(y[:, i]), 1e-8)), 3)
                   for i in range(N_TARGETS)}}


def baseline_mae(y: np.ndarray) -> float:
    """Ошибка «предсказывать среднее» — с ней надо сравнивать, иначе 0.3 ничего не значит."""
    return round(float(np.abs(y - y.mean(axis=0)).mean()), 3)


def predict_text(text: str, out_dir: Path) -> dict:
    """Инференс: читаем веса из файлов и считаем то же, что `build()`.

    Это и есть ответ на вопрос «где живёт нейросеть»: здесь её нет ни в exe,
    ни в коде — только `head.json` + `head.safetensors` и 20 строк умножений.
    """
    out_dir = Path(out_dir)
    # MLP.load уже читает head.json; второй раз читать незачем — конфиг нужен
    # только для нормировок, поэтому берём его из загруженной сети
    net = MLP.load(out_dir / "head.safetensors", out_dir / "head.json")
    cfg = json.loads((out_dir / "head.json").read_text(encoding="utf-8"))
    tok = Tokenizer.load(out_dir / "vocab.json")
    x, _, _ = build_xy([text], [[0.0] * N_TARGETS], tok, seq_len=cfg.get("seq_len", 96))
    pred = net.predict(x)[0] * np.array(cfg["y_sd"]) + np.array(cfg["y_mu"])
    return {NAMES[i]: round(float(pred[i]), 2) for i in range(N_TARGETS)}
