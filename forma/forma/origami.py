"""Ограниченная история складок и обмен развёртками FOLD / .cp.

Здесь нет общего rigid-origami solver: история относится только к операциям
листа и хранит небольшие JSON-записи плюс скрытые геометрические снимки.
FOLD описывает плоскую схему в миллиметрах; ORIPA .cp при записи использует
единый масштаб и центрируется в квадрате 0…1 без изменения углов складок.
"""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from .errors import GeometryError

HISTORY_PER_OBJECT = 8
HISTORY_TOTAL = 32
_ASSIGNMENTS = {"B", "M", "V", "A", "U", "F"}
_CP_TO_ASSIGNMENT = {"0": "U", "1": "B", "2": "M", "3": "V", "4": "A", "5": "F"}
_ASSIGNMENT_TO_CP = {value: key for key, value in _CP_TO_ASSIGNMENT.items()}


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        result = float(value)
        if not math.isfinite(result):
            raise GeometryError("В истории складок появилось нечисловое значение.")
        return result
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def _state(scene):
    if not hasattr(scene, "fold_history"):
        scene.fold_history = []
    if not hasattr(scene, "_fold_snapshots"):
        scene._fold_snapshots = {}
    if not hasattr(scene, "_fold_sequence"):
        scene._fold_sequence = 0
    return scene.fold_history, scene._fold_snapshots


def _drop(scene, record):
    history, snapshots = _state(scene)
    history.remove(record)
    snapshots.pop(record["id"], None)


def _trim(scene):
    history, _ = _state(scene)
    while len(history) > HISTORY_TOTAL:
        _drop(scene, history[0])
    counts = {}
    for record in history:
        counts[record["object"]] = counts.get(record["object"], 0) + 1
    for record in list(history):
        name = record["object"]
        if counts[name] > HISTORY_PER_OBJECT:
            _drop(scene, record)
            counts[name] -= 1


def record_fold(scene, object_name: str, record: dict, snapshot) -> dict:
    """Добавить одну складку; manifold живёт только в приватном snapshot-store."""
    history, snapshots = _state(scene)
    scene._fold_sequence += 1
    item = {"id": scene._fold_sequence, "object": str(object_name), **_clean(record)}
    item["id"] = scene._fold_sequence
    item["object"] = str(object_name)
    history.append(item)
    snapshots[item["id"]] = snapshot
    _trim(scene)
    return item


def records_for(scene, object_name: str) -> list[dict]:
    history, _ = _state(scene)
    return [item for item in history if item["object"] == object_name]


def snapshot_for(scene, record: dict):
    _, snapshots = _state(scene)
    return snapshots.get(record["id"])


def consume_fold_history(scene, object_name: str, through: dict, all_folds: bool = False):
    """Удалить записи только после успешного создания разогнутой детали."""
    for record in list(records_for(scene, object_name)):
        if all_folds or record["id"] >= through["id"]:
            _drop(scene, record)


def _normalize_pattern(data: dict) -> dict:
    if not isinstance(data, dict):
        raise GeometryError("FOLD: корневой элемент должен быть JSON-объектом.")
    raw_vertices = data.get("vertices_coords")
    raw_edges = data.get("edges_vertices")
    if not isinstance(raw_vertices, list) or not isinstance(raw_edges, list):
        raise GeometryError("FOLD/.cp: нужны vertices_coords и edges_vertices.")
    vertices = []
    for point in raw_vertices:
        if not isinstance(point, (list, tuple)) or len(point) not in (2, 3):
            raise GeometryError("FOLD: каждая вершина должна содержать 2 или 3 координаты.")
        try:
            p = [float(v) for v in point]
        except (TypeError, ValueError) as exc:
            raise GeometryError("FOLD: координата вершины не является числом.") from exc
        if not all(math.isfinite(v) for v in p):
            raise GeometryError("FOLD: координаты должны быть конечными числами.")
        vertices.append(p)
    edges = []
    for edge in raw_edges:
        if not isinstance(edge, (list, tuple)) or len(edge) != 2:
            raise GeometryError("FOLD: каждое ребро должно содержать два индекса.")
        try:
            a, b = int(edge[0]), int(edge[1])
        except (TypeError, ValueError) as exc:
            raise GeometryError("FOLD: индекс ребра не является целым числом.") from exc
        if a == b or not (0 <= a < len(vertices) and 0 <= b < len(vertices)):
            raise GeometryError("FOLD: ребро имеет неверный индекс вершины.")
        edges.append([a, b])
    assignments = list(data.get("edges_assignment") or ["U"] * len(edges))
    if len(assignments) != len(edges):
        raise GeometryError("FOLD: edges_assignment не совпадает по длине с edges_vertices.")
    assignments = [str(value).upper() for value in assignments]
    unknown = sorted(set(assignments) - _ASSIGNMENTS)
    if unknown:
        raise GeometryError("FOLD: неизвестный тип ребра " + ", ".join(unknown))
    angles = list(data.get("edges_foldAngle") or [0.0] * len(edges))
    if len(angles) != len(edges):
        raise GeometryError("FOLD: edges_foldAngle не совпадает по длине с edges_vertices.")
    angles = [0.0 if value is None else float(value) for value in angles]
    out = {
        "file_spec": float(data.get("file_spec", 1.0)),
        "file_creator": str(data.get("file_creator", "Forma 3D")),
        "file_classes": list(data.get("file_classes") or ["singleModel"]),
        "frame_classes": list(data.get("frame_classes") or ["creasePattern"]),
        "frame_unit": str(data.get("frame_unit", "mm")),
        "vertices_coords": vertices,
        "edges_vertices": edges,
        "edges_assignment": assignments,
        "edges_foldAngle": angles,
    }
    if "faces_vertices" in data:
        out["faces_vertices"] = [[int(v) for v in face] for face in data["faces_vertices"]]
    if "frame_title" in data:
        out["frame_title"] = str(data["frame_title"])
    return out


def decode_fold(text_or_data) -> dict:
    if isinstance(text_or_data, dict):
        return _normalize_pattern(text_or_data)
    if isinstance(text_or_data, bytes):
        text_or_data = text_or_data.decode("utf-8-sig")
    try:
        data = json.loads(text_or_data)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GeometryError(f"Не удалось прочитать FOLD JSON: {exc}") from exc
    return _normalize_pattern(data)


def encode_fold(pattern: dict) -> str:
    return json.dumps(_normalize_pattern(pattern), ensure_ascii=False, indent=2) + "\n"


def decode_cp(text) -> dict:
    if isinstance(text, bytes):
        text = text.decode("utf-8-sig")
    vertices: list[list[float]] = []
    edges: list[list[int]] = []
    assignments: list[str] = []

    def vertex(point):
        key = (round(float(point[0]), 10), round(float(point[1]), 10))
        for index, existing in enumerate(vertices):
            if (round(existing[0], 10), round(existing[1], 10)) == key:
                return index
        vertices.append([float(point[0]), float(point[1])])
        return len(vertices) - 1

    for line_number, raw in enumerate(str(text).splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.replace(",", " ").split()
        if len(fields) != 5:
            raise GeometryError(f".cp строка {line_number}: нужно 5 полей: тип x1 y1 x2 y2.")
        code = fields[0].upper()
        assignment = _CP_TO_ASSIGNMENT.get(code, code if code in _ASSIGNMENTS else None)
        if assignment is None:
            raise GeometryError(f".cp строка {line_number}: неизвестный тип ребра {fields[0]}.")
        try:
            coords = [float(value) for value in fields[1:]]
        except ValueError as exc:
            raise GeometryError(f".cp строка {line_number}: координата не является числом.") from exc
        if not all(math.isfinite(value) for value in coords):
            raise GeometryError(f".cp строка {line_number}: координата не конечна.")
        a = vertex(coords[:2])
        b = vertex(coords[2:])
        if a == b:
            continue
        edges.append([a, b])
        assignments.append(assignment)
    if not edges:
        raise GeometryError(".cp: в файле нет рёбер.")
    return _normalize_pattern({
        "file_creator": "ORIPA / Forma 3D", "frame_unit": "unit",
        "vertices_coords": vertices, "edges_vertices": edges,
        "edges_assignment": assignments,
        "edges_foldAngle": [-180.0 if a == "M" else 180.0 if a == "V" else 0.0
                            for a in assignments],
    })


def encode_cp(pattern: dict) -> str:
    pattern = _normalize_pattern(pattern)
    xy = np.asarray([point[:2] for point in pattern["vertices_coords"]], dtype=float)
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = np.maximum(hi - lo, 1e-12)
    # CP не должен менять углы диагональных складок: масштаб единый по осям,
    # а более короткая сторона центрируется внутри единичного квадрата.
    scale = float(max(span))
    normalized = (xy - lo) / scale + (1.0 - span / scale) * 0.5
    lines = ["# ORIPA CP 1.0 — exported by Forma 3D; uniform scale, centered in 0…1"]
    for edge, assignment in zip(pattern["edges_vertices"], pattern["edges_assignment"]):
        a, b = normalized[edge[0]], normalized[edge[1]]
        lines.append(f"{_ASSIGNMENT_TO_CP[assignment]} {a[0]:.10g} {a[1]:.10g} "
                     f"{b[0]:.10g} {b[1]:.10g}")
    return "\n".join(lines) + "\n"


def _cross2(a, b):
    return float(a[0] * b[1] - a[1] * b[0])


def _clip_line_rect(point, direction, bounds):
    point = np.asarray(point[:2], dtype=float)
    direction = np.asarray(direction[:2], dtype=float)
    if np.linalg.norm(direction) < 1e-12:
        return None
    direction /= np.linalg.norm(direction)
    lo = np.asarray(bounds[:2], dtype=float)
    hi = np.asarray(bounds[2:4], dtype=float)
    t0, t1 = -1e100, 1e100
    for axis in range(2):
        if abs(direction[axis]) < 1e-12:
            if point[axis] < lo[axis] - 1e-8 or point[axis] > hi[axis] + 1e-8:
                return None
            continue
        ta = (lo[axis] - point[axis]) / direction[axis]
        tb = (hi[axis] - point[axis]) / direction[axis]
        t0, t1 = max(t0, min(ta, tb)), min(t1, max(ta, tb))
    if t1 - t0 <= 1e-8:
        return None
    return point + t0 * direction, point + t1 * direction


def pattern_from_scene(scene) -> dict:
    """Собрать плоскую CP-развёртку из снимка листа и сохранённых линий."""
    history, snapshots = _state(scene)
    records = [r for r in history if r.get("lines") or r.get("point")]
    patterns = getattr(scene, "crease_patterns", {})
    if patterns and all(r.get("kind") == "pattern_crease" for r in records):
        visible = [s for s in scene.visible_solids() if s.name in patterns]
        if visible:
            # Источник сохраняет точный контур и линии, даже если bounded history
            # уже вытеснила часть snapshots.
            return _normalize_pattern(patterns[visible[-1].name])
    if records:
        snapshot = snapshots[records[0]["id"]]
        bounds = snapshot.bounding_box()
    else:
        sheets = [s for s in scene.visible_solids()
                  if s.kind in {"sheet", "fold_sheet", "fold_pattern", "unfold"}]
        if not sheets:
            raise GeometryError("Для FOLD/.cp нужен лист или сохранённая складка.")
        bounds = sheets[-1].manifold.bounding_box()
    xmin, ymin, xmax, ymax = float(bounds[0]), float(bounds[1]), float(bounds[3]), float(bounds[4])
    if xmax - xmin < 1e-8 or ymax - ymin < 1e-8:
        raise GeometryError("FOLD: развёртка должна быть плоским прямоугольным листом в XY.")
    rect = [xmin, ymin, xmax, ymax]
    corners = [np.array([xmin, ymin]), np.array([xmax, ymin]),
               np.array([xmax, ymax]), np.array([xmin, ymax])]
    creases = []
    for record in records:
        lines = record.get("lines") or [record]
        for line in lines:
            if "point" not in line or "dir" not in line:
                continue
            segment = _clip_line_rect(line["point"], line["dir"], rect)
            if segment is None:
                continue
            angle = float(line.get("angle", record.get("angle", 90.0)))
            assignment = str(line.get("assignment") or ("M" if angle >= 0 else "V"))
            creases.append({"ends": segment, "angle": angle, "assignment": assignment})
    points = [p.copy() for p in corners]
    for crease in creases:
        points.extend([crease["ends"][0], crease["ends"][1]])
    for i, left in enumerate(creases):
        for right in creases[i + 1:]:
            p = left["ends"][0]
            d = left["ends"][1] - p
            q = right["ends"][0]
            e = right["ends"][1] - q
            denominator = _cross2(d, e)
            if abs(denominator) < 1e-10:
                continue
            t = _cross2(q - p, e) / denominator
            u = _cross2(q - p, d) / denominator
            if 1e-8 < t < 1 - 1e-8 and 1e-8 < u < 1 - 1e-8:
                points.append(p + t * d)
    vertices: list[list[float]] = []

    def vertex_id(point):
        key = (round(float(point[0]), 8), round(float(point[1]), 8))
        for index, existing in enumerate(vertices):
            if (round(existing[0], 8), round(existing[1], 8)) == key:
                return index
        vertices.append([float(point[0]), float(point[1])])
        return len(vertices) - 1

    for point in points:
        vertex_id(point)
    edges, assignments, angles = [], [], []

    def split_edge(p0, p1, assignment, angle):
        vector = p1 - p0
        length = float(np.linalg.norm(vector))
        if length < 1e-9:
            return
        direction = vector / length
        ts = [0.0, 1.0]
        for point in points:
            rel = point - p0
            t = float(np.dot(rel, direction) / length)
            if 1e-8 < t < 1 - 1e-8 and abs(_cross2(rel, direction)) < 1e-6:
                ts.append(t)
        ts = sorted(set(round(t, 10) for t in ts))
        for ta, tb in zip(ts, ts[1:]):
            if tb - ta < 1e-8:
                continue
            edges.append([vertex_id(p0 + ta * vector), vertex_id(p0 + tb * vector)])
            assignments.append(assignment)
            angles.append(float(angle))

    for index in range(4):
        split_edge(corners[index], corners[(index + 1) % 4], "B", 180.0)
    for crease in creases:
        angle = abs(float(crease["angle"]))
        signed = -angle if crease["assignment"] == "M" else angle
        split_edge(*crease["ends"], crease["assignment"], signed)
    return _normalize_pattern({
        "file_creator": "Forma 3D", "frame_unit": "mm",
        "vertices_coords": vertices, "edges_vertices": edges,
        "edges_assignment": assignments, "edges_foldAngle": angles,
    })


def pattern_creases(pattern: dict) -> list[dict]:
    pattern = _normalize_pattern(pattern)
    lines = []
    for edge, assignment, angle in zip(pattern["edges_vertices"],
                                       pattern["edges_assignment"],
                                       pattern["edges_foldAngle"]):
        if assignment not in {"M", "V"}:
            continue
        p0 = np.asarray(pattern["vertices_coords"][edge[0]][:2], dtype=float)
        p1 = np.asarray(pattern["vertices_coords"][edge[1]][:2], dtype=float)
        direction = p1 - p0
        if np.linalg.norm(direction) < 1e-10:
            continue
        lines.append({"point": [*p0, 0.0], "dir": [*(direction / np.linalg.norm(direction)), 0.0],
                      "normal": [0.0, 0.0, 1.0], "assignment": assignment,
                      "angle": float(angle if angle else (180.0 if assignment == "V" else -180.0))})
    return lines
