"""Пакетный процедурный шум FastNoiseLite для геометрии и карт.

Алгоритм предоставлен PyFastNoiseLite/FastNoiseLite (MIT); обработка координат
сразу массивом исключает вызовы C++ по одной точке из Python. Это не SDF и не
обещает совпадения 3D-деформации с любой UV-развёрткой текстуры.
"""
from __future__ import annotations

import numpy as np


def fast_noise(points, *, seed: int = 0, kind: str = "simplex", octaves: int = 4) -> np.ndarray:
    """Значения для массива (N,2) или (N,3); входные координаты без единиц."""
    from pyfastnoiselite.pyfastnoiselite import (
        CellularDistanceFunction, CellularReturnType, FastNoiseLite,
        FractalType, NoiseType,
    )

    p = np.asarray(points)
    if p.ndim != 2 or p.shape[1] not in (2, 3) or not np.all(np.isfinite(p)):
        raise ValueError("fast_noise: нужны конечные координаты (N,2) или (N,3)")
    if not len(p):
        return np.empty(0, dtype=np.float32)
    names = {
        "simplex": NoiseType.NoiseType_OpenSimplex2S,
        "perlin": NoiseType.NoiseType_Perlin,
        "value": NoiseType.NoiseType_Value,
        "cellular": NoiseType.NoiseType_Cellular,
    }
    if kind not in names:
        raise ValueError(f"fast_noise: неизвестный тип {kind}")
    # C++ принимает знаковое 32-битное зерно, независимо от размера int Python.
    s = (int(seed) + 2**31) % 2**32 - 2**31
    engine = FastNoiseLite(seed=s)
    engine.frequency = 1.0
    engine.noise_type = names[kind]
    if kind == "cellular":
        # F2-F1, не готовая пена и не SDF.
        engine.cellular_distance_function = CellularDistanceFunction.CellularDistanceFunction_Euclidean
        engine.cellular_return_type = CellularReturnType.CellularReturnType_Distance2Sub
        engine.fractal_type = FractalType.FractalType_None
    else:
        engine.fractal_type = FractalType.FractalType_FBm
        engine.fractal_octaves = max(1, min(int(octaves), 8))
    coords = np.ascontiguousarray(p.T, dtype=np.float32)
    result = np.asarray(engine.gen_from_coords(coords), dtype=np.float32)
    if kind == "cellular":
        result = 2.0 * np.clip(result + 1.0, 0.0, 1.0) - 1.0
    if result.shape != (len(p),) or not np.all(np.isfinite(result)):
        raise ValueError("FastNoiseLite вернул неверный массив значений")
    return result


def tileable_noise(size: int, scale: float, seed: int, kind: str = "simplex") -> np.ndarray:
    """Периодическая 2D-карта 0..1; сглаженное смешивание четырёх сдвигов."""
    n = int(size)
    if n < 1:
        raise ValueError("size должен быть положительным")
    period = float(np.clip(scale, 0.1, 64.0))
    axis = np.arange(n, dtype=np.float32) / n
    x, y = np.meshgrid(axis * period, axis * period)
    xy = np.column_stack((x.ravel(), y.ravel())).astype(np.float32, copy=False)
    a = fast_noise(xy, seed=seed, kind=kind).reshape(n, n)
    xy[:, 0] -= period
    b = fast_noise(xy, seed=seed, kind=kind).reshape(n, n)
    xy[:, 1] -= period
    d = fast_noise(xy, seed=seed, kind=kind).reshape(n, n)
    xy[:, 0] += period
    c = fast_noise(xy, seed=seed, kind=kind).reshape(n, n)
    w = axis * axis * (3.0 - 2.0 * axis)
    wx, wy = w[None, :], w[:, None]
    top = a * (1.0 - wx) + b * wx
    bottom = c * (1.0 - wx) + d * wx
    return np.clip((top * (1.0 - wy) + bottom * wy + 1.0) * 0.5, 0.0, 1.0).astype(np.float32)
