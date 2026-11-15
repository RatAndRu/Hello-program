"""Синтетические точки лица — для тестов и демо-режима без камеры.

Геометрия строится «от анатомии»: глаза, брови, губы и нос расставляются так,
чтобы метрики (EAR, ширина рта, подъём уголков, высота бровей, поворот головы)
принимали наперёд заданные значения. Плотная сетка из 468 точек для
остальных индексов не нужна — она заполняется заглушкой.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from .landmarks import F, FACE_OVAL, LIPS_INNER, LIPS_OUTER, Face


def synthetic_face(
    center: Tuple[float, float] = (0.5, 0.40),
    scale: float = 1.0,
    ear: Tuple[float, float] = (0.30, 0.30),
    smile: float = 0.0,
    brow: float = 0.0,
    yaw: float = 0.0,
    pitch: float = 0.0,
    mouth_open: float = 0.12,
    frown: float = 0.0,
    gaze: Tuple[float, float] = (0.0, 0.0),
    iris: bool = True,
    seed: int = 7,
) -> Face:
    """Лицо с заданными EAR, улыбкой (в единицах лица), бровями и поворотом.

    ``ear`` — «высота глаза»: 0.30 открыт, 0.08 закрыт (реальные значения
    EAR лежат примерно в 0.15..0.35). ``frown`` — опущенные уголки губ (грусть),
    ``gaze`` — куда смотрит зрачок: (0, 0) центр, (+0.6, 0) вправо.
    ``iris`` — добавлять ли 10 точек радужки (478 точек вместо 468).
    """
    FU = 0.44 * scale            # «единица лица»: ширина головы ~2 FU
    cx, cy = center
    io = 0.52 * FU               # межзрачковое расстояние (масштаб лица)
    n_points = 478 if iris else 468
    pts = np.zeros((n_points, 3), dtype=np.float32)

    # заглушка для остальных точек: компактное облако вокруг центра лица
    rng = np.random.default_rng(seed)
    cloud = rng.normal(0.0, 0.09 * scale, size=(n_points, 2))
    pts[:, 0] = cx + cloud[:, 0]
    pts[:, 1] = cy + cloud[:, 1]

    def put(idx: int, x: float, y: float) -> None:
        pts[idx, 0] = cx + x
        pts[idx, 1] = cy + y

    # ---------------- овал лица (контур головы) ----------------------- #
    # Ставим первым: точки, которые дальше расставляются по анатомии,
    # перекроют общие индексы. Нужен, чтобы AR-контур читался как голова.
    n_oval = len(FACE_OVAL)
    for k, idx in enumerate(FACE_OVAL):
        angle = -math.pi / 2.0 + 2.0 * math.pi * k / n_oval
        put(idx, 0.98 * FU * math.cos(angle), 0.06 * FU + 1.12 * FU * math.sin(angle))

    # ---------------- глаза ------------------------------------------- #
    def eye(ids, cx_eye: float, sign: float, ear_value: float) -> None:
        outer, up2, up3, inner, low3, low2 = ids
        ew = 0.12 * FU
        put(outer, cx_eye - ew, 0.0)
        put(inner, cx_eye + ew, 0.0)
        half_h = ear_value * ew
        put(up2, cx_eye - 0.55 * ew, -half_h)
        put(up3, cx_eye + 0.55 * ew, -half_h)
        put(low2, cx_eye - 0.55 * ew, half_h)
        put(low3, cx_eye + 0.55 * ew, half_h)

    eye(F.EYE_A, -0.14 * FU, -1.0, ear[0])   # 33 — внешний угол, 133 — внутренний
    eye(F.EYE_B, +0.14 * FU, +1.0, ear[1])   # 362 ... 263

    # ---------------- радужка (зрачок) -------------------------------- #
    if iris:
        gx, gy = gaze
        for ids, cx_eye, ear_v in ((F.IRIS_A, -0.14 * FU, ear[0]),
                                   (F.IRIS_B, +0.14 * FU, ear[1])):
            ew = 0.12 * FU
            half_h = max(ear_v * ew, 0.02 * FU)
            px = cx_eye + float(gx) * ew * 0.9
            py = float(gy) * half_h * 0.9
            r = 0.028 * FU
            put(ids[0], px, py)                      # центр зрачка
            put(ids[1], px - r, py)
            put(ids[2], px, py - r)
            put(ids[3], px + r, py)
            put(ids[4], px, py + r)

    # верхние веки (для отрисовки и для высоты бровей)
    put(F.EYE_A_TOP, -0.14 * FU, -ear[0] * 0.12 * FU)
    put(F.EYE_B_TOP, +0.14 * FU, -ear[1] * 0.12 * FU)

    # ---------------- брови ------------------------------------------- #
    brow_y = -ear[0] * 0.12 * FU - (0.35 + brow) * FU
    put(F.BROW_A, -0.14 * FU, brow_y)
    put(F.BROW_B, +0.14 * FU, brow_y)

    # ---------------- рот --------------------------------------------- #
    my = 0.62 * FU
    half_w = (0.15 + smile + 0.5 * frown) * FU
    lift = 0.40 * (smile - frown) * FU
    inner_half = 0.85 * half_w
    gap = max(mouth_open * 2.0 * inner_half, 0.006 * FU)

    # Сначала кольца губ (для площади контура), затем — ключевые точки,
    # потому что индексы пересекаются и «главные» точки должны победить.
    def ring(indices, half_w_: float, half_h_: float) -> None:
        # Индексы губ идут по контуру: левый уголок -> верх -> правый -> низ.
        # Ставим их в том же порядке, иначе контур рисуется «зигзагом».
        n = len(indices)
        for k, idx in enumerate(indices):
            angle = math.pi - 2.0 * math.pi * k / n
            put(idx, half_w_ * math.cos(angle), my - half_h_ * math.sin(angle))

    ring(LIPS_INNER, inner_half, max(gap / 2.0, 0.006 * FU))
    ring(LIPS_OUTER, half_w, gap / 2.0 + 0.04 * FU)

    put(F.LIP_LEFT_INNER, -inner_half, my)
    put(F.LIP_RIGHT_INNER, +inner_half, my)
    put(F.LIP_TOP_INNER, 0.0, my - gap / 2.0)
    put(F.LIP_BOTTOM_INNER, 0.0, my + gap / 2.0)
    put(F.LIP_TOP_OUTER, 0.0, my - gap / 2.0 - 0.035 * FU)
    put(F.LIP_BOTTOM_OUTER, 0.0, my + gap / 2.0 + 0.045 * FU)
    put(F.MOUTH_LEFT, -half_w, my - lift)
    put(F.MOUTH_RIGHT, +half_w, my - lift)

    # ---------------- нос, подбородок, щёки --------------------------- #
    nose_x = io * math.tan(math.radians(yaw))
    nose_y = io * math.tan(math.radians(pitch))
    put(F.NOSE_TIP, nose_x, nose_y)
    put(F.NOSE_BRIDGE, nose_x * 0.4, -0.30 * FU)
    put(F.CHIN, nose_x * 0.5, 1.15 * FU)
    put(F.FOREHEAD, 0.0, -1.05 * FU)
    put(F.CHEEK_LEFT, -0.95 * FU, 0.15 * FU)
    put(F.CHEEK_RIGHT, +0.95 * FU, 0.15 * FU)

    # клип в пределы кадра — как настоящие нормализованные координаты
    pts[:, 0] = np.clip(pts[:, 0], 0.0, 1.0)
    pts[:, 1] = np.clip(pts[:, 1], 0.0, 1.0)
    # искажение поворотом: чем дальше от центра, тем сильнее смещение (грубо)
    if abs(yaw) > 1e-6 or abs(pitch) > 1e-6:
        pts[:, 0] += (pts[:, 0] - cx) * (math.cos(math.radians(yaw)) - 1.0)
        pts[:, 1] += (pts[:, 1] - cy) * (math.cos(math.radians(pitch)) - 1.0)
    return Face(pts)


def blink_sequence(frames: int, blinks, fps: float = 25.0, **kwargs):
    """Готовое лицо на каждый кадр с морганиями в заданные моменты.

    ``blinks`` — список моментов (в секундах), когда глаз закрывается.
    """
    out = []
    closed_for = 0.12
    for i in range(frames):
        t = i / fps
        closed = any(0.0 <= (t - b) <= closed_for for b in blinks)
        ear = (0.08, 0.08) if closed else (0.30, 0.30)
        out.append(synthetic_face(ear=ear, **kwargs))
    return out
