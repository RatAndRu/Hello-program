"""Маленькая сеть на numpy: байты, умножения, файл весов.

Здесь нет ни PyTorch, ни TensorFlow — специально. Устройство то же самое, что
у большой модели, просто меньше слоёв:

    вход (мешок токенов) → скрытый слой (tanh) → выход (7 чисел)

Прямой проход (inference):   h = tanh(x·W1 + b1);   y = h·W2 + b2
Обучение:   ошибка MSE, обратный проход по цепному правилу, шаг Adam.

Веса хранятся в формате **safetensors** — это то же, чем пользуются большие
модели на Hugging Face. Формат намеренно простой:

    8 байт   — длина заголовка (little-endian u64)
    N байт   — JSON: имя тензора → {dtype, shape, data_offsets}
    остаток  — сырые числа подряд, без сжатия

Никакой магии: `head.safetensors` можно открыть в hex-редакторе и увидеть
float32 своими глазами. Рядом лежит `head.json` — конфигурация (размеры,
нормировки, версия), чтобы код знал, как эти числа читать.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

__all__ = ["MLP", "save_safetensors", "load_safetensors"]


# ---------------------------------------------------------------- формат файла
_DTYPES = {np.dtype("float32"): "F32", np.dtype("int32"): "I32",
           np.dtype("float64"): "F64", np.dtype("uint8"): "U8"}
_DTYPES_BACK = {v: k for k, v in _DTYPES.items()}


def save_safetensors(path: Path, tensors: dict[str, np.ndarray]) -> int:
    """Пишет словарь тензоров в safetensors и возвращает размер файла, байт."""
    header: dict[str, dict] = {}
    blobs: list[bytes] = []
    offset = 0
    for name, arr in tensors.items():
        a = np.ascontiguousarray(arr)
        if a.dtype not in _DTYPES:
            a = a.astype(np.float32)
        raw = a.tobytes()
        header[name] = {"dtype": _DTYPES[a.dtype], "shape": list(a.shape),
                        "data_offsets": [offset, offset + len(raw)]}
        blobs.append(raw)
        offset += len(raw)
    head = json.dumps(header, separators=(",", ":")).encode("utf-8")
    head += b" " * ((8 - len(head) % 8) % 8)          # выравнивание по 8 байт
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(struct.pack("<Q", len(head)))
        f.write(head)
        for raw in blobs:
            f.write(raw)
    return path.stat().st_size


def load_safetensors(path: Path) -> dict[str, np.ndarray]:
    data = Path(path).read_bytes()
    n = struct.unpack("<Q", data[:8])[0]
    header = json.loads(data[8:8 + n].decode("utf-8"))
    base = 8 + n
    out: dict[str, np.ndarray] = {}
    for name, info in header.items():
        lo, hi = info["data_offsets"]
        dtype = _DTYPES_BACK[info["dtype"]]
        out[name] = np.frombuffer(data[base + lo:base + hi], dtype=dtype).reshape(info["shape"])
    return out


# ---------------------------------------------------------------- сеть
class MLP:
    """Два слоя, tanh посередине. Размер задаётся числами, а не фантазией."""

    def __init__(self, n_in: int, n_hidden: int = 256, n_out: int = 7, seed: int = 0):
        rng = np.random.default_rng(seed)
        self.params = {
            # инициализация Ксавье: масштаб зависит от числа входов, иначе tanh
            # сразу упирается в насыщение и обучение стоит на месте
            "W1": (rng.standard_normal((n_in, n_hidden)) * np.sqrt(2.0 / n_in)).astype(np.float32),
            "b1": np.zeros(n_hidden, dtype=np.float32),
            "W2": (rng.standard_normal((n_hidden, n_out)) * np.sqrt(2.0 / n_hidden)).astype(np.float32),
            "b2": np.zeros(n_out, dtype=np.float32),
        }
        self.n_in, self.n_hidden, self.n_out = n_in, n_hidden, n_out
        self._m = {k: np.zeros_like(v) for k, v in self.params.items()}
        self._v = {k: np.zeros_like(v) for k, v in self.params.items()}
        self._t = 0

    # -------------------------------------------------------------- проходы
    def forward(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        p = self.params
        z = x @ p["W1"] + p["b1"]
        h = np.tanh(z)
        y = h @ p["W2"] + p["b2"]
        return y, h, z

    def backward(self, x, y, target, h, z) -> dict[str, np.ndarray]:
        p = self.params
        dy = (y - target) * (2.0 / y.size)              # dMSE/dy при усреднении
        g = {"W2": h.T @ dy, "b2": dy.sum(axis=0)}
        dh = dy @ p["W2"].T
        dz = dh * (1.0 - h * h)                          # производная tanh
        g["W1"] = x.T @ dz
        g["b1"] = dz.sum(axis=0)
        return g

    def step(self, grads: dict[str, np.ndarray], lr: float = 3e-3,
             b1: float = 0.9, b2: float = 0.999, eps: float = 1e-8) -> None:
        """Один шаг Adam — тот же, что в больших моделях, только без GPU."""
        self._t += 1
        for k, g in grads.items():
            self._m[k] = b1 * self._m[k] + (1 - b1) * g
            self._v[k] = b2 * self._v[k] + (1 - b2) * (g * g)
            m_hat = self._m[k] / (1 - b1 ** self._t)
            v_hat = self._v[k] / (1 - b2 ** self._t)
            self.params[k] -= (lr * m_hat / (np.sqrt(v_hat) + eps)).astype(np.float32)

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.forward(x)[0]

    # -------------------------------------------------------------- файлы
    def save(self, weights: Path, config: Path, extra: dict | None = None) -> tuple[int, int]:
        size = save_safetensors(weights, self.params)
        cfg = {"kind": "mlp", "n_in": self.n_in, "n_hidden": self.n_hidden,
               "n_out": self.n_out, "format": "safetensors", "version": 1,
               "n_params": int(sum(v.size for v in self.params.values()))}
        cfg.update(extra or {})
        Path(config).parent.mkdir(parents=True, exist_ok=True)
        Path(config).write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        return size, int(cfg["n_params"])

    @classmethod
    def load(cls, weights: Path, config: Path) -> "MLP":
        cfg = json.loads(Path(config).read_text(encoding="utf-8"))
        net = cls(cfg["n_in"], cfg["n_hidden"], cfg["n_out"])
        net.params = load_safetensors(weights)
        return net
