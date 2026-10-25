"""Куда смотрит деталь: её собственные верх, низ, бока и центр массы.

Поворот в сцене «запекается» в геометрию: после `rotate` от угла остаётся
только новая сетка. Нейросети (и люди) на этом месте путаются — «верх» детали
уже не +Z, а куда-то повёрнут. Здесь хранится маленькая памятка: матрица
*мир ← деталь*. Её обновляют `rotate`, `mirror` и `place осями=хозяина`,
а читают `ориентация` и относительная посадка.

    A = axes_of(деталь)          # столбцы: куда смотрят локальные X, Y, Z
    верх_в_мире = A[:, 2]        # локальный +Z
    перед_в_мире = -A[:, 1]      # локальный −Y (лицо смотрит в −Y)

Ещё здесь считается **центр массы** — он нужен, когда центр габарита
попадает в пустоту: у тора, воронки, кольца коробка пустая внутри.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

AXIS_LETTERS = ("X", "Y", "Z")

# Локальные оси детали: право +X, перёд −Y, верх +Z (как у примитивов).
SIDE_VECTORS = {
    "top": np.array([0.0, 0.0, 1.0]),
    "bottom": np.array([0.0, 0.0, -1.0]),
    "right": np.array([1.0, 0.0, 0.0]),
    "left": np.array([-1.0, 0.0, 0.0]),
    "front": np.array([0.0, -1.0, 0.0]),
    "back": np.array([0.0, 1.0, 0.0]),
    "center": np.zeros(3),
}

SIDE_WORDS = {
    "top": "top", "сверху": "top", "верх": "top", "сверху_от": "top",
    "bottom": "bottom", "снизу": "bottom", "низ": "bottom",
    "right": "right", "справа": "right", "право": "right", "правый": "right",
    "left": "left", "слева": "left", "лево": "left", "левый": "left",
    "front": "front", "спереди": "front", "перёд": "front", "перед": "front",
    "back": "back", "сзади": "back", "зад": "back", "тыл": "back",
    "center": "center", "центр": "center", "по_центру": "center",
}

SIDE_RU = {"top": "сверху", "bottom": "снизу", "right": "справа", "left": "слева",
           "front": "спереди", "back": "сзади", "center": "по центру"}


def axes_of(solid) -> np.ndarray:
    """Матрица «мир ← деталь»: столбцы — локальные оси в мировых координатах."""
    raw = (getattr(solid, "meta", None) or {}).get("axes")
    if not raw:
        return np.eye(3)
    try:
        arr = np.asarray(raw, dtype=np.float64).reshape(3, 3)
    except Exception:
        return np.eye(3)
    return arr


def set_axes(solid, matrix) -> np.ndarray:
    arr = np.asarray(matrix, dtype=np.float64).reshape(3, 3)
    solid.meta["axes"] = [[float(x) for x in row] for row in arr]
    return arr


def is_identity(matrix, tol: float = 1e-9) -> bool:
    return bool(np.max(np.abs(np.asarray(matrix) - np.eye(3))) < tol)


def mirrored(matrix) -> bool:
    return float(np.linalg.det(np.asarray(matrix, dtype=np.float64))) < 0.0


def rotate_axes(axes, angle_deg: float, axis) -> np.ndarray:
    """Поворачивает памятку вместе с деталью: A' = R · A."""
    a = np.asarray(axis, dtype=np.float64)
    n = float(np.linalg.norm(a))
    if n < 1e-12 or abs(angle_deg) < 1e-12:
        return np.asarray(axes, dtype=np.float64)
    a = a / n
    ang = math.radians(float(angle_deg))
    c, s = math.cos(ang), math.sin(ang)
    x, y, z = a
    r = np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])
    return r @ np.asarray(axes, dtype=np.float64)


def mirror_axes(axes, plane: str) -> np.ndarray:
    """Отражение памятки: det станет −1 — деталь зеркальная, а не повёрнутая."""
    m = np.eye(3)
    idx = {"x": 0, "y": 1, "z": 2}.get((plane or "x").lower(), 0)
    m[idx, idx] = -1.0
    return m @ np.asarray(axes, dtype=np.float64)


def basis(up, front) -> np.ndarray:
    """Матрица по «верх» и «перёд»: локальные +Z и −Y, третья ось — из них."""
    up_v = np.asarray(up, dtype=np.float64)
    front_v = np.asarray(front, dtype=np.float64)
    if np.linalg.norm(up_v) < 1e-9 or np.linalg.norm(front_v) < 1e-9:
        raise ValueError("Верх и перёд должны быть ненулевыми направлениями.")
    z = up_v / np.linalg.norm(up_v)
    y = -front_v / np.linalg.norm(front_v)     # локальный +Y — это «зад»
    y = y - np.dot(y, z) * z
    if np.linalg.norm(y) < 1e-9:
        raise ValueError("Верх и перёд не могут смотреть вдоль одной прямой.")
    y = y / np.linalg.norm(y)
    x = np.cross(y, z)
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    return np.column_stack([x, y, z])


def describe_direction(vec) -> str:
    """«+X», «−Y», а для косого направления — ещё и числа."""
    v = np.asarray(vec, dtype=np.float64)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return "—"
    v = v / n
    i = int(np.argmax(np.abs(v)))
    sign = "+" if v[i] >= 0 else "−"
    label = f"{sign}{AXIS_LETTERS[i]}"
    if abs(v[i]) < 0.995:
        nums = ", ".join(f"{c:+.2f}" for c in v)
        return f"{label} ≈ ({nums})"
    return label


def extent_along(manifold: mf.Manifold, direction) -> tuple[float, float]:
    """Границы детали вдоль любого направления — по вершинам, а не по коробке."""
    d = np.asarray(direction, dtype=np.float64)
    n = float(np.linalg.norm(d))
    if n < 1e-12:
        return 0.0, 0.0
    d = d / n
    mesh = manifold.to_mesh()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    proj = verts @ d
    return float(proj.min()), float(proj.max())


def mass_center(manifold: mf.Manifold) -> np.ndarray:
    """Центр массы объёма — там, где у тора есть материал, а у центра коробки нет."""
    try:
        mesh = manifold.to_mesh()
        verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
        tris = np.asarray(mesh.tri_verts, dtype=np.int64).reshape(-1, 3)
        if len(tris) == 0:
            raise ValueError("empty")
        a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
        six_v = np.einsum("ij,ij->i", a, np.cross(b, c))
        total = float(six_v.sum()) / 6.0
        if abs(total) < 1e-9:
            raise ValueError("zero volume")
        centroids = (a + b + c) / 4.0
        return (six_v[:, None] * centroids).sum(axis=0) / (6.0 * total)
    except Exception:
        bb = manifold.bounding_box()
        return np.array([(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2])


def bbox_center(manifold: mf.Manifold) -> np.ndarray:
    bb = manifold.bounding_box()
    return np.array([(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2])


def faces(solid) -> dict[str, str]:
    """Куда в мире смотрят верх, низ, бока и перёд/зад детали."""
    a = axes_of(solid)
    return {
        "верх": describe_direction(a[:, 2]),
        "низ": describe_direction(-a[:, 2]),
        "право": describe_direction(a[:, 0]),
        "лево": describe_direction(-a[:, 0]),
        "перед": describe_direction(-a[:, 1]),
        "зад": describe_direction(a[:, 1]),
    }


def _num(value: float) -> float:
    """−0.0 в отчёте выглядит как ошибка — приводим к нулю."""
    v = round(float(value), 3)
    return 0.0 if abs(v) < 1e-9 else v


def report(solid) -> dict:
    """Подробный разбор: оси, центр габарита, центр массы, пусто ли в центре."""
    from . import cuts

    manifold = solid.manifold
    center = bbox_center(manifold)
    mass = mass_center(manifold)
    holes = False
    try:
        holes = not bool(cuts.point_info(manifold, center).get("inside"))
    except Exception:
        holes = False
    bb = manifold.bounding_box()
    return {
        "object": solid.name,
        "axes": [[round(float(x), 4) for x in row] for row in axes_of(solid)],
        "faces": faces(solid),
        "rotation": "зеркальная" if mirrored(axes_of(solid)) else (
            "нет" if is_identity(axes_of(solid)) else "повёрнута"),
        "bbox": [_num(v) for v in bb],
        "bbox_center": [_num(v) for v in center],
        "mass_center": [_num(v) for v in mass],
        "center_empty": bool(holes),
    }


def side_key(raw: str | None) -> str:
    """Приводит «слева», «сверху», left… к одному из side-ключей."""
    text = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    return SIDE_WORDS.get(text, text)
