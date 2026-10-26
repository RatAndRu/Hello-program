"""Пластины с полостями и кубы с рельефными гранями/срезами углов."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile
from .ops import anchor, make_solid, op, stand_flat_sign
from .shape_features import rounded_extrude, slot_contour


def _rect(width: float, height: float, cx: float = 0.0, cy: float = 0.0) -> np.ndarray:
    hx, hy = width / 2.0, height / 2.0
    return np.asarray([(cx - hx, cy - hy), (cx + hx, cy - hy),
                       (cx + hx, cy + hy), (cx - hx, cy + hy)], dtype=np.float64)


def _ellipse(width: float, height: float, cx: float = 0.0, cy: float = 0.0,
             segments: int = 96) -> np.ndarray:
    unit = np.asarray(circle_profile(1.0, segments), dtype=np.float64)
    return unit * np.asarray([width / 2.0, height / 2.0]) + np.asarray([cx, cy])


def _cs(points) -> mf.CrossSection:
    return mf.CrossSection([np.asarray(points, dtype=np.float64)])


def _subtract_cs(a: mf.CrossSection, b: mf.CrossSection) -> mf.CrossSection:
    return mf.CrossSection.batch_boolean([a, b], mf.OpType.Subtract)


def _add_cs(a: mf.CrossSection, b: mf.CrossSection) -> mf.CrossSection:
    return mf.CrossSection.batch_boolean([a, b], mf.OpType.Add)


@op("cavity_frame", aliases=("рамка_полость", "полая_рамка", "рамка_с_полостью",
                             "cavity_plate", "полостная_рамка"), category="Примитивы",
    summary="Пластина-рамка с одной сквозной полостью. outer=квадрат или круг; "
            "cavity=Г — два соединённых прямоугольных канала у выбранного угла, "
            "линия — прямой прямоугольный паз, квадрат/круг — полость у угла, "
            "овал — прямая капсула. У круглой рамки линия автоматически овальная, "
            "угловой квадрат — круглый. Все размеры, поля и кромки настраиваются.",
    example="угловая = cavity_frame size=[100,90] depth=8 cavity=Г corner=право_верх\n"
            "паз = cavity_frame outer=круг size=[100,100] cavity=линия cavity_size=[60,6]\n"
            "окно = cavity_frame size=[100,90] cavity=квадрат cavity_size=[28,24] margin=9",
    params={"size": "наружные ширина и высота [X,Y], мм (100,90)",
            "depth": "толщина пластины, мм (8)",
            "outer": "квадрат — прямоугольная рамка; круг — круг/эллипс",
            "cavity": "Г, линия, квадрат, круг или овал",
            "cavity_size": "габарит полости [X,Y], мм (50,40); для линии важна длина X",
            "line_width": "ширина линии и каждой ветви Г, мм (6)",
            "margin": "материал от угловой полости до наружного края, мм (8)",
            "corner": "право_верх, лево_верх, право_низ или лево_низ",
            "round": "радиус скругления переходных кромок, мм (0)",
            "plane": "фронт или плашмя — «фронт»", "stand": "то же, что plane=фронт",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"})
def cavity_frame(a, name):
    size = a.vec("size", 2, default=(100.0, 90.0))
    width, height = float(size[0]), float(size[1])
    depth = float(a.num("depth", 8.0, minv=0.2, maxv=1000.0))
    if min(width, height) < 4.0:
        raise GeometryError("cavity_frame: стороны size должны быть не меньше 4 мм.")
    outer = (a.text("outer", "квадрат") or "квадрат").strip().lower()
    if outer in ("квадрат", "прямоугольник", "square", "rect"):
        outer = "квадрат"
    elif outer in ("круг", "круглая", "овал", "circle", "ellipse"):
        outer = "круг"
    else:
        raise GeometryError("cavity_frame: outer=квадрат или круг.")
    cavity = (a.text("cavity", "Г") or "Г").strip().lower()
    cavity = {"г": "Г", "l": "Г", "уголок": "Г", "линия": "линия",
              "паз": "линия", "line": "линия", "квадрат": "квадрат",
              "square": "квадрат", "круг": "круг", "circle": "круг",
              "овал": "овал", "капсула": "овал", "oval": "овал"}.get(cavity)
    if cavity is None:
        raise GeometryError("cavity_frame: cavity=Г, линия, квадрат, круг или овал.")
    csize = a.vec("cavity_size", 2, default=(50.0, 40.0))
    cw, ch = float(csize[0]), float(csize[1])
    line_w = float(a.num("line_width", 6.0, minv=0.2, maxv=500.0))
    margin = float(a.num("margin", 8.0, minv=0.5, maxv=1000.0))
    round_r = float(a.num("round", 0.0, minv=0.0) or 0.0)
    corner = (a.text("corner", "право_верх") or "право_верх").strip().lower()
    corners = {"право_верх": (1, 1), "верх_право": (1, 1),
               "лево_верх": (-1, 1), "верх_лево": (-1, 1),
               "право_низ": (1, -1), "низ_право": (1, -1),
               "лево_низ": (-1, -1), "низ_лево": (-1, -1)}
    if corner not in corners:
        raise GeometryError("cavity_frame: неизвестный corner.", hint=", ".join(corners))
    sx, sy = corners[corner]
    if min(cw, ch) <= 0.2:
        raise GeometryError("cavity_size: обе стороны должны быть больше 0.2 мм.")

    outer_cs = _cs(_rect(width, height) if outer == "квадрат" else _ellipse(width, height))
    centered = cavity in ("линия", "овал")
    if centered:
        if cavity == "линия":
            cw, ch = cw, line_w
        if cavity == "овал" or (cavity == "линия" and outer == "круг"):
            tool = _cs(slot_contour(cw, ch, 24))
        else:
            tool = _cs(_rect(cw, ch))
    else:
        x0 = width / 2.0 - margin - cw if sx > 0 else -width / 2.0 + margin
        x1 = x0 + cw
        y0 = height / 2.0 - margin - ch if sy > 0 else -height / 2.0 + margin
        y1 = y0 + ch
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        if cavity == "Г":
            if line_w >= min(cw, ch):
                raise GeometryError("line_width должен быть меньше обеих сторон cavity_size.")
            hx0, hx1 = x0, x1
            hy0, hy1 = (y1 - line_w, y1) if sy > 0 else (y0, y0 + line_w)
            vx0, vx1 = (x1 - line_w, x1) if sx > 0 else (x0, x0 + line_w)
            vy0, vy1 = y0, y1
            horizontal = _cs(_rect(hx1 - hx0, hy1 - hy0,
                                   (hx0 + hx1) / 2.0, (hy0 + hy1) / 2.0))
            vertical = _cs(_rect(vx1 - vx0, vy1 - vy0,
                                 (vx0 + vx1) / 2.0, (vy0 + vy1) / 2.0))
            tool = _add_cs(horizontal, vertical)
        elif cavity == "круг" or (cavity == "квадрат" and outer == "круг"):
            tool = _cs(_ellipse(cw, ch, cx, cy))
        else:
            tool = _cs(_rect(cw, ch, cx, cy))
        # У круглой/эллиптической рамки квадратная сетка угла не работает:
        # полость скользит по диагонали к центру ровно настолько, чтобы
        # целиком остаться внутри эрозированного на margin контура.
        allowed = outer_cs.offset(-margin, mf.JoinType.Round, 2.0, 20)
        origin_tool = tool.translate((-cx, -cy))

        def fits(t):
            candidate = origin_tool.translate((cx * t, cy * t))
            excess = _subtract_cs(candidate, allowed)
            return excess.is_empty() or excess.area() <= 1e-5

        if not fits(0.0):
            raise GeometryError("Полость с заданным margin не помещается в рамке.",
                                hint="Уменьшите cavity_size/margin или увеличьте size.")
        if not fits(1.0):
            lo, hi = 0.0, 1.0
            for _ in range(28):
                middle = (lo + hi) / 2.0
                if fits(middle):
                    lo = middle
                else:
                    hi = middle
            tool = origin_tool.translate((cx * lo, cy * lo))
    outside = _subtract_cs(tool, outer_cs)
    if not outside.is_empty() and outside.area() > 1e-5:
        raise GeometryError("Полость выходит за наружный контур рамки.",
                            hint="Уменьшите cavity_size или увеличьте size; увеличение margin требует больше места.")
    cross = _subtract_cs(outer_cs, tool)
    if cross.is_empty() or cross.area() <= 1e-6:
        raise GeometryError("Полость удалила всю рамку.")
    limit = min(depth * 0.45, margin * 0.45, line_w * 0.45)
    solid = rounded_extrude(cross, depth, min(round_r, limit), "рамка с полостью")
    solid = stand_flat_sign(a, solid)
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="cavity_frame")
    out.notes.append(f"рамка {outer}, полость {cavity}, угол {corner}, "
                     f"поле {margin:g} мм")
    return out


_FACE_ALIASES = {
    "верх": "верх", "top": "верх", "+z": "верх",
    "низ": "низ", "bottom": "низ", "-z": "низ",
    "перёд": "перёд", "перед": "перёд", "front": "перёд", "-y": "перёд",
    "зад": "зад", "back": "зад", "+y": "зад",
    "право": "право", "right": "право", "+x": "право",
    "лево": "лево", "left": "лево", "-x": "лево",
}
_FACE_ROTATIONS = {
    "верх": np.eye(3),
    "низ": np.asarray([[1, 0, 0], [0, -1, 0], [0, 0, -1]], dtype=float),
    "перёд": np.asarray([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float),
    "зад": np.asarray([[-1, 0, 0], [0, 0, 1], [0, 1, 0]], dtype=float),
    "право": np.asarray([[0, 0, 1], [1, 0, 0], [0, 1, 0]], dtype=float),
    "лево": np.asarray([[0, 0, -1], [-1, 0, 0], [0, 1, 0]], dtype=float),
}
_CORNERS = {
    "перед_право_верх": (1, -1, 1), "перёд_право_верх": (1, -1, 1),
    "перед_лево_верх": (-1, -1, 1), "перёд_лево_верх": (-1, -1, 1),
    "зад_право_верх": (1, 1, 1), "зад_лево_верх": (-1, 1, 1),
    "перед_право_низ": (1, -1, -1), "перёд_право_низ": (1, -1, -1),
    "перед_лево_низ": (-1, -1, -1), "перёд_лево_низ": (-1, -1, -1),
    "зад_право_низ": (1, 1, -1), "зад_лево_низ": (-1, 1, -1),
}


def _lens_cap(width: float, height: float, relief: float) -> mf.Manifold:
    base_r = min(width, height) / 2.0
    radius = (base_r * base_r + relief * relief) / (2.0 * relief)
    sphere = mf.Manifold.sphere(radius, 48).translate((0, 0, relief - radius))
    clip = mf.Manifold.cube((radius * 4.0, radius * 4.0, relief + 0.05), True)
    cap = sphere ^ clip.translate((0, 0, (relief - 0.05) / 2.0))
    matrix = np.eye(3, 4)
    matrix[0, 0] = width / (2.0 * base_r)
    matrix[1, 1] = height / (2.0 * base_r)
    return cap.transform(matrix)


def _face_feature(width: float, height: float, relief: float, profile: str,
                  taper: float) -> mf.Manifold:
    if profile == "линза":
        return _lens_cap(width, height, relief)
    if profile == "квадрат":
        return mf.Manifold.cube((width, height, relief + 0.05), True).translate(
            (0, 0, (relief - 0.05) / 2.0))
    scale = 1.0 - taper
    pts = []
    for z, k in ((-0.05, 1.0), (relief, scale)):
        for x, y in ((-width * k / 2, -height * k / 2),
                     (width * k / 2, -height * k / 2),
                     (width * k / 2, height * k / 2),
                     (-width * k / 2, height * k / 2)):
            pts.append((x, y, z))
    return mf.Manifold.hull_points(np.asarray(pts, dtype=np.float64))


@op("face_box", aliases=("куб_граней", "формкуб", "куб_с_гранями", "face_cube"),
    category="Примитивы",
    summary="Куб с ровными, выпуклыми или вогнутыми гранями. profile=линза "
            "делает эллиптическую сферическую капу, трапеция — наклонные стенки, "
            "квадрат — прямой выступ/врез. faces=все/бока или список граней. "
            "corner_cut срезает один, верхние/нижние или все углы плоскостью "
            "через три ребра, образуя треугольные грани.",
    example="купола = face_box size=[80,80,80] mode=выпуклый profile=линза faces=все relief=7 margin=8\n"
            "пазы = face_box size=[80,80,80] mode=вогнутый profile=квадрат faces=верх,перёд relief=6\n"
            "срез = face_box size=[80,80,80] corners=один corner=перед_право_верх corner_cut=22",
    params={"size": "стороны куба [x,y,z], мм (80,80,80)",
            "mode": "ровный, выпуклый или вогнутый",
            "profile": "линза, трапеция или квадрат",
            "faces": "все, бока или список: верх,низ,перёд,зад,право,лево",
            "relief": "высота выпуклости или глубина вогнутости, мм (7)",
            "margin": "поле от края грани до рельефа, мм (8)",
            "taper": "сужение вершины трапеции 0…0.9 (0.35)",
            "corner_cut": "срез вдоль каждого из трёх рёбер, мм; 0 — нет",
            "corners": "один, верх, низ, все или нет",
            "corner": "какой один угол: перед_право_верх и т. п.",
            "at": "положение [x,y,z]", "center": "центрировать в at"})
def face_box(a, name):
    size = a.vec("size", 3, default=(80.0, 80.0, 80.0))
    dims = np.asarray([float(v) for v in size], dtype=np.float64)
    if np.any(dims < 2.0):
        raise GeometryError("face_box: каждая сторона должна быть не меньше 2 мм.")
    mode = (a.text("mode", "ровный") or "ровный").strip().lower()
    mode = {"ровный": "ровный", "ровные": "ровный", "flat": "ровный",
            "выпуклый": "выпуклый", "выпуклые": "выпуклый", "convex": "выпуклый",
            "вогнутый": "вогнутый", "вогнутые": "вогнутый", "concave": "вогнутый"}.get(mode)
    if mode is None:
        raise GeometryError("face_box: mode=ровный, выпуклый или вогнутый.")
    profile = (a.text("profile", "линза") or "линза").strip().lower()
    profile = {"линза": "линза", "сфера": "линза", "lens": "линза",
               "трапеция": "трапеция", "скос": "трапеция", "taper": "трапеция",
               "квадрат": "квадрат", "прямоугольник": "квадрат", "square": "квадрат"}.get(profile)
    if profile is None:
        raise GeometryError("face_box: profile=линза, трапеция или квадрат.")
    relief = float(a.num("relief", 7.0, minv=0.1, maxv=1000.0))
    margin = float(a.num("margin", 8.0, minv=0.0, maxv=1000.0) or 0.0)
    taper = float(a.num("taper", 0.35, minv=0.0, maxv=0.9) or 0.0)
    raw_faces = (a.text("faces", "все") or "все").strip().lower()
    if raw_faces.startswith("[") and raw_faces.endswith("]"):
        raw_faces = raw_faces[1:-1].strip()
    raw_faces = raw_faces.replace("+", ",")
    if raw_faces in ("все", "все_грани", "all"):
        faces = ["верх", "низ", "перёд", "зад", "право", "лево"]
    elif raw_faces in ("бока", "боковые", "sides"):
        faces = ["перёд", "зад", "право", "лево"]
    else:
        faces = []
        for token in raw_faces.replace(";", " ").replace(",", " ").split():
            token = token.strip()
            if token and token not in _FACE_ALIASES:
                raise GeometryError(f"face_box: неизвестная грань «{token}».")
            if token:
                faces.append(_FACE_ALIASES[token])
        faces = list(dict.fromkeys(faces))
    solid = mf.Manifold.cube(tuple(dims), True)

    corner_cut = float(a.num("corner_cut", 0.0, minv=0.0, maxv=10000.0) or 0.0)
    corners_mode = (a.text("corners", "один") or "один").strip().lower()
    corner_name = (a.text("corner", "перед_право_верх") or "перед_право_верх").strip().lower()
    if corner_name not in _CORNERS:
        raise GeometryError("face_box: неизвестный corner.", hint="Например, перед_право_верх.")
    if corners_mode not in ("один", "верх", "низ", "все", "нет"):
        raise GeometryError("face_box: corners=один, верх, низ, все или нет.")
    if corner_cut > 1e-6 and corners_mode != "нет":
        limit = min(dims) * (0.95 if corners_mode == "один" else 0.48)
        if corner_cut > limit:
            raise GeometryError(f"corner_cut не должен превышать {limit:g} мм для этого режима.")
        selected = ([_CORNERS[corner_name]] if corners_mode == "один" else
                    [v for v in dict.fromkeys(_CORNERS.values())
                     if corners_mode == "все" or (corners_mode == "верх" and v[2] > 0)
                     or (corners_mode == "низ" and v[2] < 0)])
        for signs in selected:
            signs = np.asarray(signs, dtype=float)
            corner = signs * dims / 2.0
            inward = []
            for axis in range(3):
                p = corner.copy()
                p[axis] -= signs[axis] * corner_cut
                inward.append(p)
            outside = corner + signs * 0.05
            cutter = mf.Manifold.hull_points(np.asarray([outside, *inward], dtype=np.float64))
            solid = solid - cutter

    if mode != "ровный" and faces:
        face_dims = {
            "верх": (dims[0], dims[1], 2), "низ": (dims[0], dims[1], 2),
            "перёд": (dims[0], dims[2], 1), "зад": (dims[0], dims[2], 1),
            "право": (dims[1], dims[2], 0), "лево": (dims[1], dims[2], 0),
        }
        for face in faces:
            u, v, axis = face_dims[face]
            fu, fv = u - 2.0 * margin, v - 2.0 * margin
            if min(fu, fv) <= 0.2:
                raise GeometryError(f"margin не оставляет рельефа на грани {face}.")
            if relief > min(fu, fv) * (0.9 if profile == "линза" else 1.5):
                raise GeometryError(f"relief слишком велик для грани {face}.")
            feature = _face_feature(fu, fv, relief, profile, taper)
            if mode == "вогнутый":
                feature = feature.rotate((180, 0, 0))
                solid = solid - _on_face(feature, face, dims[axis] / 2.0)
            else:
                solid = solid + _on_face(feature, face, dims[axis] / 2.0)
    if solid.is_empty() or solid.volume() <= 1e-6:
        raise GeometryError("face_box: операции удалили всё тело.")
    solid = anchor(solid, a.vec("at", 3, default=(0, 0, 0)), a.boolean("center", False))
    out = make_solid(a.scene, name, solid, a, kind="face_box")
    out.meta["faces"] = faces
    out.notes.append(f"грани {mode}/{profile}: {', '.join(faces)}; "
                     f"срез {corner_cut:g} мм, corners={corners_mode}")
    return out


def _on_face(feature: mf.Manifold, face: str, offset: float) -> mf.Manifold:
    rotation = _FACE_ROTATIONS[face]
    matrix3 = np.eye(3, 4)
    matrix3[:, :3] = rotation
    axis = {"верх": 2, "низ": 2, "перёд": 1, "зад": 1, "право": 0, "лево": 0}[face]
    sign = 1.0 if face in ("верх", "зад", "право") else -1.0
    matrix3[axis, 3] = sign * offset
    return feature.transform(np.asarray(matrix3, dtype=np.float64))
