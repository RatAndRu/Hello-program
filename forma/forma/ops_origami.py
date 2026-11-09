"""Этап 3: разгиб, FOLD/.cp, пакет, кинематика и резка с kerf."""
from __future__ import annotations

import math
from pathlib import Path

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import anchor, make_solid, op, rotate as rotate_manifold, translate as translate_manifold
from .ops_extra import _derived, _one
from .origami import (consume_fold_history, decode_cp, decode_fold, encode_cp, encode_fold,
                      pattern_creases, record_fold, records_for, snapshot_for)


def _unit(value, what="направление"):
    vector = np.asarray(value, dtype=float).reshape(3)
    length = float(np.linalg.norm(vector))
    if length < 1e-10:
        raise GeometryError(f"Нулевое {what}.")
    return vector / length


def _axis(value, default=(0, 0, 1)):
    if value is None:
        return np.asarray(default, dtype=float)
    if isinstance(value, str) and value.lower() in {"x", "y", "z"}:
        result = np.zeros(3)
        result["xyz".index(value.lower())] = 1.0
        return result
    return _unit(value, "ось")


def _outline_loops(pattern):
    """Вернуть замкнутые boundary-контуры FOLD, включая контур из faces."""
    edges = [tuple(edge) for edge, assignment in zip(pattern["edges_vertices"],
                                                      pattern["edges_assignment"])
             if assignment == "B"]
    if not edges and pattern.get("faces_vertices"):
        counts = {}
        directed = {}
        for face in pattern["faces_vertices"]:
            for left, right in zip(face, face[1:] + face[:1]):
                key = tuple(sorted((int(left), int(right))))
                counts[key] = counts.get(key, 0) + 1
                directed[key] = (int(left), int(right))
        edges = [directed[key] for key, count in counts.items() if count == 1]
    if not edges:
        return []
    adjacency = {}
    unused = set()
    for left, right in edges:
        key = tuple(sorted((int(left), int(right))))
        if key[0] == key[1]:
            continue
        unused.add(key)
        adjacency.setdefault(key[0], set()).add(key[1])
        adjacency.setdefault(key[1], set()).add(key[0])
    loops = []
    while unused:
        first = min(unused)
        start = first[0]
        previous, current = None, start
        loop = []
        while True:
            loop.append(current)
            candidates = sorted(neighbor for neighbor in adjacency.get(current, ())
                                if tuple(sorted((current, neighbor))) in unused)
            if not candidates:
                break
            following = next((n for n in candidates if n != previous), candidates[0])
            unused.remove(tuple(sorted((current, following))))
            previous, current = current, following
            if current == start:
                break
            if len(loop) > len(pattern["vertices_coords"]) + 1:
                raise GeometryError("FOLD: boundary-контур содержит цикл с повторением вершин.")
        if current != start or len(loop) < 3:
            raise GeometryError("FOLD: boundary-рёбра не образуют замкнутый контур.",
                                hint="Проверьте edges_assignment=B или faces_vertices.")
        loops.append(loop)
    return loops


def _pattern_sheet(pattern, lo, span, length, width, thickness, at):
    """Построить лист по настоящему контуру, а не по его bounding box."""
    loops = _outline_loops(pattern)
    if not loops:
        return mf.Manifold.cube((length, width, thickness), True)
    contours = []
    for loop in loops:
        points = []
        for index in loop:
            point = np.asarray(pattern["vertices_coords"][index][:2], dtype=float)
            mapped = ((point - lo) / span * np.array([length, width])
                      - np.array([length, width]) * 0.5 + np.asarray(at[:2], dtype=float))
            points.append(mapped.tolist())
        contours.append(points)
    cross = mf.CrossSection(contours, fillrule=mf.FillRule.EvenOdd)
    if cross.is_empty() or cross.area() <= 1e-10:
        raise GeometryError("FOLD/.cp: контур листа вырожден или самопересекается.")
    return cross.extrude(thickness).translate((0.0, 0.0, -thickness * 0.5))


def _cutter(base, p0, p1, width, depth=None, side="top", normal=None):
    p0, p1 = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
    span = p1 - p0
    length = float(np.linalg.norm(span))
    if length < 1e-8:
        raise GeometryError("Линия реза имеет нулевую длину.")
    x = span / length
    bb = base.bounding_box()
    if normal is None:
        ext = np.asarray(bb[3:]) - np.asarray(bb[:3])
        normal = np.zeros(3)
        normal[int(np.argmin(ext))] = 1.0
    z = _unit(normal, "нормаль")
    z = z - x * float(np.dot(z, x))
    if np.linalg.norm(z) < 1e-8:
        raise GeometryError("Нормаль реза параллельна его линии.")
    z = _unit(z)
    y = _unit(np.cross(z, x))
    z = _unit(np.cross(x, y))
    middle = (p0 + p1) * 0.5
    eps = 1e-4
    if depth is None:
        diagonal = float(np.linalg.norm(np.asarray(bb[3:]) - np.asarray(bb[:3])))
        cutter_depth = max(2.0 * diagonal, 1.0)
    else:
        corners = np.array([[bb[0] if i & 1 else bb[3], bb[1] if i & 2 else bb[4],
                             bb[2] if i & 4 else bb[5]] for i in range(8)])
        projections = corners @ z
        surface = float(projections.max() if side == "top" else projections.min())
        # Наружу добавляем только eps; внутрь материал уходит ровно depth.
        desired = (surface - depth * 0.5 + eps * 0.5 if side == "top"
                   else surface + depth * 0.5 - eps * 0.5)
        middle = middle + z * (desired - float(np.dot(middle, z)))
        cutter_depth = depth + eps
    matrix = np.eye(3, 4, dtype=float)
    matrix[:, :3] = np.column_stack([x, y, z])
    matrix[:, 3] = middle
    return mf.Manifold.cube((length + 2 * eps, width, cutter_depth), True).transform(matrix)


@op("unfold", aliases=("разгиб", "разогнуть", "unbend", "разгиб_листа"),
    category="Форма и деформации",
    summary="Разгибает последнюю сохранённую складку листа. Восстанавливает "
            "геометрию до неё и по умолчанию оставляет настоящую канавку: "
            "материал не становится нетронутым, как до фиктивного сгиба.",
    example="лист = fold_sheet width=120 length=200 thickness=1 angle=80\n"
            "разгиб = unfold лист groove=0.5 depth=0.2",
    params={"objects": "один согнутый лист",
            "groove": "ширина оставшейся канавки, мм; 0 — без канавки (0.5)",
            "depth": "глубина канавки, мм (0.25)",
            "side": "top или bottom — сторона канавки (top)",
            "all": "да — разогнуть всю ограниченную историю этого листа"},
    positional=["objects"])
def unfold(a, name):
    base = _one(a, "unfold")
    records = records_for(a.scene, base.name)
    if not records:
        raise GeometryError(f"Для «{base.name}» нет сохранённой истории складок.",
                            hint="Сначала используйте fold, fold_sheet или сгиб; "
                                 "unfold не требует общего дерева истории модели.")
    all_folds = a.boolean("all", False)
    record = records[0] if all_folds else records[-1]
    snapshot = snapshot_for(a.scene, record)
    if snapshot is None:
        raise GeometryError("Снимок этой складки уже вытеснен из ограниченной истории.")
    width = float(a.num("groove", 0.5, minv=0.0, maxv=1000.0) or 0.0)
    depth = float(a.num("depth", 0.25, minv=0.001, maxv=1000.0) or 0.0)
    side = a.text("side", "top", ["top", "bottom", "верх", "низ"]) or "top"
    side = "top" if side in {"top", "верх"} else "bottom"
    solid = snapshot
    selected = records if all_folds else [record]
    if width > 0:
        for item in selected:
            for line in item.get("lines") or ([item] if item.get("point") else []):
                point = np.asarray(line.get("point"), dtype=float)
                direction = _unit(line.get("dir"))
                diagonal = float(np.linalg.norm(np.asarray(snapshot.bounding_box()[3:]) -
                                                np.asarray(snapshot.bounding_box()[:3])))
                p0, p1 = point - direction * diagonal, point + direction * diagonal
                cutter = _cutter(snapshot, p0, p1, width, depth, side, line.get("normal"))
                solid = solid - cutter
                if solid.is_empty():
                    raise GeometryError("Канавка разгиба удалила весь лист.",
                                        hint="Уменьшите depth или groove.")
    out = _derived(a, name, solid, base, "unfold")
    consume_fold_history(a.scene, base.name, record, all_folds)
    out.meta["unfold"] = {"groove": width, "depth": depth if width else 0.0,
                          "side": side, "all": all_folds,
                          "restored_fold": record["id"]}
    out.notes.append(f"разгиб складки #{record['id']}; канавка {width:g}×{depth:g} мм")
    return out


@op("fold_pattern", aliases=("crease_pattern", "fold_import", "cp_import", "развертка",
                             "развёртка", "оригами_схема"),
    category="Сцена и материал",
    summary="Импортирует FOLD JSON или ORIPA .cp как лист постоянной толщины "
            "и редактируемую схему Mountain/Valley. Не притворяется общим "
            "решателем одновременного rigid-origami складывания.",
    example="деталь = fold_pattern file=examples/assets/crease_square.fold thickness=0.6\n"
            "схема = fold_pattern file=examples/assets/crease_square.cp width=160 length=160",
    params={"file": "путь к .fold/.json или .cp",
            "width": "ширина по Y, мм; по умолчанию из файла, для .cp сохраняется пропорция",
            "length": "длина по X, мм; по умолчанию из файла, для .cp сохраняется пропорция",
            "thickness": "толщина листа, мм (0.6)",
            "at": "положение листа [x,y,z]", "center": "центрировать по высоте"})
def fold_pattern(a, name):
    filename = a.text("file")
    if not filename:
        raise GeometryError("fold_pattern: задайте file=путь к .fold или .cp.")
    path = Path(filename).expanduser()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GeometryError(f"fold_pattern: не удалось прочитать {path}: {exc}") from exc
    source = "CP" if path.suffix.lower() == ".cp" else "FOLD"
    pattern = decode_cp(raw) if source == "CP" else decode_fold(raw)
    coords = np.asarray([p[:2] for p in pattern["vertices_coords"]], dtype=float)
    lo, hi = coords.min(axis=0), coords.max(axis=0)
    span = hi - lo
    if np.any(span < 1e-9):
        raise GeometryError("fold_pattern: развёртка вырождена по X или Y.")
    normalized = float(max(span)) <= 1.000001
    if normalized:
        # Восстанавливаем соотношение сторон, сохранённое единым CP-масштабом.
        default_length = 100.0 if span[0] >= span[1] else 100.0 * span[0] / span[1]
        default_width = 100.0 if span[1] >= span[0] else 100.0 * span[1] / span[0]
    else:
        default_length, default_width = float(span[0]), float(span[1])
    length = float(a.num("length", default_length, minv=0.01, maxv=10000.0))
    width = float(a.num("width", default_width, minv=0.01, maxv=10000.0))
    thickness = float(a.num("thickness", 0.6, minv=0.01, maxv=100.0))
    at = a.vec("at", 3, default=(0, 0, 0))
    solid = _pattern_sheet(pattern, lo, span, length, width, thickness, at)
    solid = anchor(solid, at, a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="fold_pattern")
    top = float(solid.bounding_box()[5])
    lines = []
    for line in pattern_creases(pattern):
        point = np.asarray(line["point"][:2], dtype=float)
        direction = np.asarray(line["dir"][:2], dtype=float)
        mapped = ((point - lo) / span * np.array([length, width])
                  - np.array([length, width]) * 0.5 + np.asarray(at[:2], dtype=float))
        mapped_dir = _unit([direction[0] / span[0] * length,
                            direction[1] / span[1] * width, 0.0])
        lines.append({"point": [float(mapped[0]), float(mapped[1]), top],
                      "dir": mapped_dir.tolist(), "normal": [0.0, 0.0, 1.0],
                      "assignment": line["assignment"], "angle": line["angle"],
                      "source": source})
        record_fold(a.scene, out.name, {"kind": "pattern_crease", "source": source,
                                       "lines": [lines[-1]]}, solid)
    if not hasattr(a.scene, "crease_patterns"):
        a.scene.crease_patterns = {}
    a.scene.crease_patterns[out.name] = pattern
    out.meta["crease_pattern"] = {"format": source, "file": str(path),
                                  "vertices": len(pattern["vertices_coords"]),
                                  "edges": len(pattern["edges_vertices"]),
                                  "creases": len(lines), "length": length, "width": width}
    out.notes.append(f"{source}: {len(lines)} линий сгиба; лист {length:g}×{width:g}×{thickness:g} мм")
    return out


@op("packet", aliases=("пакет", "fold_packet", "стопка", "пакет_листов"),
    category="Массивы и преобразования",
    summary="Собирает реальный многослойный пакет: каждая копия имеет свою "
            "толщину, зазор и положение; толщина пакета вычисляется из геометрии.",
    example="слой = sheet width=160 length=220 thickness=0.8\n"
            "пакет = packet слой layers=6 gap=0.15 axis=z",
    params={"objects": "один исходный лист или деталь", "layers": "число слоёв 2…100",
            "gap": "просвет между слоями, мм (0)", "axis": "x, y или z (z)"},
    positional=["objects"])
def packet(a, name):
    base = _one(a, "packet")
    layers = int(a.int("layers", 2, minv=2, maxv=100) or 2)
    gap = float(a.num("gap", 0.0, minv=0.0, maxv=10000.0) or 0.0)
    axis_name = (a.text("axis", "z", ["x", "y", "z"]) or "z").lower()
    axis = "xyz".index(axis_name)
    bb = base.manifold.bounding_box()
    extent = float(bb[axis + 3] - bb[axis])
    if extent < 1e-8:
        raise GeometryError("packet: исходный слой имеет нулевую толщину по axis.")
    copies = []
    for index in range(layers):
        offset = np.zeros(3)
        offset[axis] = index * (extent + gap)
        copies.append(translate_manifold(base.manifold, offset))
    solid = mf.Manifold.batch_boolean(copies, mf.OpType.Add)
    out = _derived(a, name, solid, base, "packet")
    total = extent * layers + gap * (layers - 1)
    out.meta["packet"] = {"layers": layers, "gap": gap, "axis": axis_name,
                          "layer_thickness": extent, "thickness": total}
    out.notes.append(f"пакет: {layers} слоёв, реальная толщина {total:g} мм")
    return out


def _obstacles(a):
    if not a.has("against"):
        return []
    raw = a.value("against")
    values = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    result = []
    for value in values:
        for solid in a.scene.expand(value):
            if solid.visible and solid not in result:
                result.append(solid)
    return result


def _collision(moving, obstacles, tolerance):
    bb = moving.bounding_box()
    for obstacle in obstacles:
        other = obstacle.manifold.bounding_box()
        overlap = np.minimum(np.asarray(bb[3:]), np.asarray(other[3:])) - \
            np.maximum(np.asarray(bb[:3]), np.asarray(other[:3]))
        if not np.all(overlap > 1e-8):
            continue
        volume = abs(float((moving ^ obstacle.manifold).volume()))
        if volume > tolerance:
            return {"object": obstacle.name, "volume_mm3": volume}
    return None


def _kinematic(a, name, mode):
    base = _one(a, mode)
    steps = int(a.int("steps", 8, minv=1, maxv=256) or 8)
    tolerance = float(a.num("tolerance", 0.001, minv=0.0) or 0.0)
    allow = a.boolean("allow", False)
    obstacles = _obstacles(a)
    if mode == "hinge_move":
        angle = float(a.num("angle", required=True))
        axis = _axis(a.value("axis") if a.has("axis") else "z")
        pivot = np.asarray(a.vec("pivot", 3, default=(0, 0, 0)), dtype=float)
        transform = lambda fraction: rotate_manifold(base.manifold, angle * fraction, axis, pivot)
        control = {"angle": angle, "axis": axis.tolist(), "pivot": pivot.tolist()}
    else:
        distance = float(a.num("distance", required=True))
        direction = _axis(a.value("direction") if a.has("direction") else (1, 0, 0))
        transform = lambda fraction: translate_manifold(base.manifold, direction * (distance * fraction))
        control = {"distance": distance, "direction": direction.tolist()}
    collisions = []
    final = base.manifold
    for step in range(1, steps + 1):
        fraction = step / steps
        moved = transform(fraction)
        hit = _collision(moved, obstacles, tolerance)
        if hit:
            hit.update({"step": step, "fraction": fraction})
            collisions.append(hit)
            if not allow:
                raise GeometryError(
                    f"Обнаружено столкновение «{base.name}» с «{hit['object']}» "
                    f"на шаге {step}/{steps}; объём {hit['volume_mm3']:.6g} мм³.",
                    hint="Измените ось/траекторию или задайте allow=да для записи отчёта без остановки.")
        final = moved
    out = _derived(a, name, final, base, mode)
    if not hasattr(a.scene, "mechanisms"):
        a.scene.mechanisms = []
    report = {"type": "hinge" if mode == "hinge_move" else "slider",
              "object": out.name, "steps_checked": steps, "collisions": collisions,
              "allowed_collisions": allow, **control}
    a.scene.mechanisms.append(report)
    out.meta["mechanism"] = report
    out.notes.append(f"кинематика: {report['type']}, проверено положений {steps}, "
                     f"столкновений {len(collisions)}")
    return out


@op("hinge_move", aliases=("hinge_kinematic", "шарнирное_движение", "поворот_шарнира"),
    category="Массивы и преобразования",
    summary="Управляемый поворот детали вокруг петли с проверкой промежуточных "
            "столкновений. Это кинематика и геометрические пересечения, не FEA.",
    example="стена = box size=[200, 8, 200] at=[0, 14, 0]\n"
            "дверь = box size=[90, 4, 190] at=[45, 8, 0]\n"
            "створка = hinge_move дверь angle=-90 axis=z pivot=[0, 8, 0] "
            "against=[стена] steps=16",
    params={"objects": "одна движущаяся деталь", "angle": "итоговый угол, градусы",
            "axis": "x/y/z или вектор оси", "pivot": "точка оси [x,y,z]",
            "against": "неподвижные объекты или группа для collision-check",
            "steps": "число проверяемых промежуточных положений (8)",
            "tolerance": "допуск объёма пересечения, мм³ (0.001)",
            "allow": "да — не останавливаться, а записать столкновения в отчёт"},
    positional=["objects"])
def hinge_move(a, name):
    return _kinematic(a, name, "hinge_move")


@op("slider", aliases=("slide", "ползун", "слайдер", "поступательное_движение"),
    category="Массивы и преобразования",
    summary="Управляемое линейное перемещение детали с проверкой всего пути "
            "на геометрические столкновения.",
    example="рельс_л = box size=[10, 300, 10] at=[-95, 0, 5]\n"
            "рельс_п = box size=[10, 300, 10] at=[95, 0, 5]\n"
            "ящик = box size=[180, 280, 120] at=[0, 0, 70]\n"
            "ход = slider ящик distance=120 direction=[0,-1,0] "
            "against=[рельс_л, рельс_п] steps=12",
    params={"objects": "одна движущаяся деталь", "distance": "ход, мм; знак задаёт направление",
            "direction": "x/y/z или вектор направления", "against": "неподвижные объекты",
            "steps": "число проверяемых положений (8)", "tolerance": "допуск, мм³ (0.001)",
            "allow": "записать столкновения вместо остановки"},
    positional=["objects"])
def slider(a, name):
    return _kinematic(a, name, "slider")


@op("kerf_cut", aliases=("kerf", "надрез", "надрезы", "рез_с_kerf"),
    category="Булевы операции",
    summary="Прямой рез или неглубокий надрез с настоящей шириной kerf. "
            "Вычитает объём, поэтому после сквозного реза остаётся физический зазор.",
    example="лист = sheet width=200 length=200 thickness=2\n"
            "рез = kerf_cut лист from=[0,-100,0.5] to=[0,100,0.5] kerf=0.6\n"
            "биг = kerf_cut лист from=[0,-100,1] to=[0,100,1] kerf=0.5 depth=0.2 side=top",
    params={"objects": "одна деталь", "from": "начало линии [x,y,z]", "to": "конец линии [x,y,z]",
            "kerf": "ПОЛНАЯ ширина реза, мм", "depth": "глубина; без неё — сквозной рез",
            "side": "top/bottom — сторона неглубокого реза (top)",
            "normal": "нормаль поверхности; по умолчанию тонкая ось габарита"},
    positional=["objects"])
def kerf_cut(a, name):
    base = _one(a, "kerf_cut")
    p0 = a.vec("from", 3, required=True)
    p1 = a.vec("to", 3, required=True)
    width = float(a.num("kerf", required=True, minv=1e-5, maxv=10000.0))
    depth = a.num("depth", None, minv=1e-5, maxv=10000.0)
    side = a.text("side", "top", ["top", "bottom", "верх", "низ"]) or "top"
    side = "top" if side in {"top", "верх"} else "bottom"
    cutter = _cutter(base.manifold, p0, p1, width,
                     float(depth) if depth is not None else None, side, a.vec("normal", 3))
    solid = base.manifold - cutter
    if solid.is_empty():
        raise GeometryError("kerf_cut: рез удалил всю деталь.")
    out = _derived(a, name, solid, base, "kerf_cut")
    out.meta["kerf"] = {"width": width, "depth": float(depth) if depth is not None else "through",
                        "side": side, "from": p0, "to": p1}
    out.notes.append(f"kerf {width:g} мм; " + (f"глубина {float(depth):g} мм" if depth is not None else "сквозной рез"))
    return out
