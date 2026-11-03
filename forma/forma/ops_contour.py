"""DSL-конструктор аналитических Contour2D."""

from __future__ import annotations

import math

import numpy as np

from .contour import Contour2D
from .errors import GeometryError
from .geometry import FINENESS_MM, as_points
from .ops import op


_KINDS = {
    "line": "line", "линия": "line", "отрезок": "line",
    "arc": "arc", "дуга": "arc", "circle": "arc", "окружность": "arc",
    "ellipse": "ellipse", "эллипс": "ellipse",
    "bezier": "bezier", "bézier": "bezier", "безье": "bezier", "сплайн": "bezier",
}


def _kind(value) -> str:
    raw = str(value or "").strip().lower()
    if raw not in _KINDS:
        raise GeometryError(f"Contour2D: неизвестный тип сегмента «{value}».",
                            hint="Используйте line, arc, ellipse или bezier.")
    return _KINDS[raw]


def _number(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeometryError(f"Contour2D: {what} должно быть числом.")
    result = float(value)
    if not math.isfinite(result):
        raise GeometryError(f"Contour2D: {what} должно быть конечным числом.")
    return result


def _point(value, what: str) -> list[float]:
    try:
        point = as_points(value, 2, what)
    except Exception as exc:
        raise GeometryError(f"Contour2D: некорректная {what}: {exc}") from exc
    if len(point) != 1:
        raise GeometryError(f"Contour2D: {what} должна быть одной точкой [x,y].")
    return [float(point[0, 0]), float(point[0, 1])]


def _is_point(value) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value))


def _arc_end(segment: dict) -> list[float]:
    angle = math.radians(float(segment["to"]))
    if segment["kind"] == "arc":
        rx = ry = float(segment["radius"])
    else:
        rx, ry = float(segment["rx"]), float(segment["ry"])
    return [float(segment["center"][0]) + rx * math.cos(angle),
            float(segment["center"][1]) + ry * math.sin(angle)]


def _parse_segments(raw, start) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise GeometryError("Contour2D: segments должен быть непустым списком сегментов.")
    current = list(start) if start is not None else None
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, (list, tuple)) or not item:
            raise GeometryError(f"Contour2D: segments[{index}] должен быть списком с типом.")
        kind = _kind(item[0])
        try:
            if kind == "line":
                if len(item) != 2:
                    raise GeometryError("line: [\"line\",[x,y]] или [\"line\",[[x0,y0],[x1,y1]]].")
                if _is_point(item[1]):
                    if current is None:
                        raise GeometryError("Для относительной line нужен start или предыдущий сегмент.")
                    points = [current, _point(item[1], "конец line")]
                else:
                    points = as_points(item[1], 2, "line").tolist()
                    if len(points) != 2:
                        raise GeometryError("line должна содержать ровно две точки.")
                segment = {"kind": kind, "points": points}
                current = list(points[-1])
            elif kind == "arc":
                if len(item) != 5:
                    raise GeometryError("arc: [\"arc\",[cx,cy],radius,from,to], углы в градусах.")
                segment = {"kind": kind, "center": _point(item[1], "центр arc"),
                           "radius": _number(item[2], "radius"),
                           "from": _number(item[3], "from"),
                           "to": _number(item[4], "to")}
                current = _arc_end(segment)
            elif kind == "ellipse":
                if len(item) not in (4, 6):
                    raise GeometryError("ellipse: [\"ellipse\",[cx,cy],rx,ry] "
                                        "или с from,to в конце.")
                segment = {"kind": kind, "center": _point(item[1], "центр ellipse"),
                           "rx": _number(item[2], "rx"), "ry": _number(item[3], "ry"),
                           "from": _number(item[4], "from") if len(item) == 6 else 0.0,
                           "to": _number(item[5], "to") if len(item) == 6 else 360.0}
                current = _arc_end(segment)
            else:
                if len(item) != 2:
                    raise GeometryError("bezier: [\"bezier\",[[p0], [p1], [p2], …]].")
                points = as_points(item[1], 2, "bezier").tolist()
                if len(points) not in (3, 4):
                    raise GeometryError("Bézier требует 3 или 4 управляющие точки.")
                segment = {"kind": kind, "points": points}
                current = list(points[-1])
        except GeometryError as exc:
            raise GeometryError(f"Contour2D segments[{index}]: {exc}") from exc
        result.append(segment)
    return result


@op("contour2d", aliases=("contour", "контур", "sketch", "эскиз"),
    category="Тела вращения и развёртки",
    summary="Аналитический 2D-контур из line, arc, ellipse и квадратичной/"
            "кубической Bézier. Адаптивная выборка по tolerance используется "
            "extrude, lathe, loft и sweep; списки точек остаются совместимыми.",
    example="п = contour2d start=[0,0] segments=[[\"line\",[40,0]],"
            "[\"arc\",[40,10],10,-90,0],[\"line\",[40,30]]] closed=да\n"
            "д = extrude profile=п height=8 draft=2\n"
            "путь = contour2d kind=bezier points=[[0,0],[10,20],[30,20],[40,0]]\n"
            "труба = sweep path=путь radius=2",
    params={"kind": "одиночный сегмент: line, arc, ellipse, bezier",
            "points": "точки line или 3–4 управляющие точки Bézier",
            "start": "начало составного контура [x,y]",
            "segments": "сегменты: [\"line\",точка], [\"arc\",центр,r,from,to], "
                        "[\"ellipse\",центр,rx,ry], [\"bezier\",точки]",
            "center": "центр arc/ellipse [x,y] (0,0)",
            "radius": "радиус одиночной дуги/окружности",
            "rx": "полуось эллипса X", "ry": "полуось эллипса Y",
            "from": "начальный угол arc/ellipse, ° (0)",
            "to": "конечный угол arc/ellipse, ° (360)",
            "closed": "замкнутый контур/путь (да/нет)",
            "tolerance": "допуск адаптивной хорды, мм (0.06)",
            "join_tolerance": "допуск сварки стыков, мм (0.00001)",
            "max_points": "предел точек выборки 4…16384 (4096)",
            "plane": "встраивание пути sweep: xy, xz, yz (xy)",
            "at": "смещение 3D-пути sweep [x,y,z]"},
    positional=[])
def contour2d(a, name):
    default_tolerance = a.scene.precision_tolerance(FINENESS_MM)
    tolerance = float(a.num("tolerance", default_tolerance, minv=1e-6, maxv=10.0))
    join_tolerance = float(a.num("join_tolerance", 1e-5, minv=0.0, maxv=10.0))
    max_points = int(a.num("max_points", 4096, minv=4, maxv=16384))
    start = a.vec("start", 2, default=None)
    plane = (a.text("plane", "xy") or "xy").lower()
    at = tuple(a.vec("at", 3, default=(0.0, 0.0, 0.0)))
    if a.has("segments"):
        segments = _parse_segments(a.value("segments"), start)
        default_closed = False
    else:
        raw_kind = a.text("kind")
        if not raw_kind:
            raise GeometryError("Contour2D: задайте kind или segments.")
        kind = _kind(raw_kind)
        if kind == "line":
            points = as_points(a.value("points"), 2, "points").tolist()
            if len(points) < 2:
                raise GeometryError("Contour2D line: нужны минимум две точки.")
            segments = [{"kind": "line", "points": points[i:i + 2]}
                        for i in range(len(points) - 1)]
        elif kind == "bezier":
            points = as_points(a.value("points"), 2, "points").tolist()
            if len(points) not in (3, 4):
                raise GeometryError("Bézier требует 3 или 4 управляющие точки.")
            segments = [{"kind": "bezier", "points": points}]
        elif kind == "arc":
            segments = [{"kind": "arc", "center": a.vec("center", 2, default=(0, 0)),
                         "radius": float(a.num("radius", required=True, minv=1e-6)),
                         "from": float(a.num("from", 0.0)),
                         "to": float(a.num("to", 360.0))}]
        else:
            segments = [{"kind": "ellipse", "center": a.vec("center", 2, default=(0, 0)),
                         "rx": float(a.num("rx", required=True, minv=1e-6)),
                         "ry": float(a.num("ry", required=True, minv=1e-6)),
                         "from": float(a.num("from", 0.0)),
                         "to": float(a.num("to", 360.0))}]
        default_closed = (kind in ("arc", "ellipse")
                          and abs(abs(segments[0]["to"] - segments[0]["from"]) - 360.0) < 1e-7)
    closed = a.boolean("closed", default_closed)
    contour = Contour2D(name=name or a.scene.auto_name("контур"), segments=segments,
                        closed=closed, tolerance=tolerance, join_tolerance=join_tolerance,
                        max_points=max_points, start=start, plane=plane, at=at)
    # Все ошибки геометрии и допуска показываем на команде создания, а не
    # откладываем до неожиданного падения extrude/loft.
    contour.sample()
    return contour
