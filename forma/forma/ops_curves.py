"""Тела вращения, выдавливание, развёртка, лофт."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import (as_points, catmull_rom, circle_profile, ellipse_profile,
                       ensure_ccw, fillet_polyline, loft_solid, loft_solid_smooth,
                       polygon_area, smooth_closed_profile, sweep_solid)
from .ops import ensure_solid, make_solid, op
from .values import parse_value


def _clean_profile(pts: np.ndarray, what: str = "профиль") -> np.ndarray:
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 3:
        raise GeometryError(f"{what.capitalize()} должен содержать минимум 3 точки.")
    if abs(polygon_area(pts)) < 1e-9:
        raise GeometryError(f"{what.capitalize()} имеет нулевую площадь.",
                            hint="Проверьте, что точки не лежат на одной линии.")
    return pts


@op("lathe", aliases=("точить", "вращение", "тело_вращения", "revolve", "vrashenie"),
    category="Тела вращения и развёртки",
    summary="Вращает замкнутый профиль (радиус, высота) вокруг оси Z. Основа для посуды, ваз, бутылок.",
    example="""корпус = lathe points=[[0,0],[40,0],[42,3],[42,90],[39,92],[38,8],[0,5]] segments=128 fillet=2""",
    params={"points": "контур в плоскости (r,z): [[r,z],...] (обязательно)",
            "segments": "сегментов по кругу (128)",
            "arc": "угол вращения в градусах (360)",
            "smooth": "сгладить профиль: число подсегментов на участок",
            "fillet": "скруглить углы профиля радиусом, мм",
            "thickness": "сделать стенку заданной толщины (пустотелое тело)",
            "open": "где открыть полость: top, bottom, both"},
    positional=["points"])
def lathe(a, name):
    pts = a.points("points", 2)
    pts = _clean_profile(np.asarray(pts, dtype=np.float64))
    pts = pts.copy()
    if np.any(pts[:, 0] < -1e-6):
        raise GeometryError("Радиус профиля не может быть отрицательным.",
                            hint="Первая координата точки — расстояние от оси вращения (≥ 0).")
    pts[:, 0] = np.clip(pts[:, 0], 0.0, None)
    fillet = a.num("fillet", 0.0, minv=0.0)
    smooth = a.int("smooth", 0, minv=0, maxv=32)
    if fillet and fillet > 0:
        pts = fillet_polyline(pts, float(fillet), closed=True, skip_axis=True)
    if smooth and smooth > 1:
        pts = smooth_closed_profile(pts, samples=int(smooth))
    segments = a.int("segments", 128, minv=8, maxv=1024)
    arc = a.num("arc", 360.0, minv=0.1, maxv=360.0)
    if abs(arc - 360.0) < 1e-9:
        solid = mf.Manifold.revolve(mf.CrossSection([pts]), int(segments))
    else:
        solid = mf.Manifold.revolve(mf.CrossSection([pts]), int(segments), float(arc))
    thickness = a.num("thickness", 0.0, minv=0.0)
    if thickness and thickness > 0:
        open_mode = a.text("open", "top", ["top", "bottom", "both", "none"]) or "top"
        solid = _lathe_shell(solid, pts, float(thickness), int(segments), open_mode,
                             float(arc))
    return make_solid(a.scene, name, solid, a, kind="lathe")


def _lathe_shell(solid, pts: np.ndarray, t: float, segments: int, open_mode: str,
                 arc: float) -> mf.Manifold:
    """Полость для тела вращения: точное 2D-смещение профиля внутрь.

    Ось вращения не является поверхностью, поэтому профиль зеркалится
    относительно оси, сжимается на толщину стенки и обрезается по x >= 0 —
    так дно и кромки получают ровную толщину без «стержня» по центру.
    """
    pts = np.asarray(pts, dtype=np.float64)
    zmin, zmax = float(pts[:, 1].min()), float(pts[:, 1].max())
    if (zmax - zmin) <= 2 * t + 1e-6:
        raise GeometryError(f"Толщина стенки {t:g} мм больше размеров тела.")
    mirrored = np.vstack([pts, pts[::-1] * np.array([-1.0, 1.0])])
    try:
        inner = mf.CrossSection([mirrored]).offset(-t)
    except Exception as exc:
        raise GeometryError(f"Не удалось построить полость: {exc}") from exc
    big = float(np.abs(pts[:, 0]).max()) * 3 + 10
    clip = mf.CrossSection([np.array([[0.0, zmin - 10.0], [big, zmin - 10.0],
                                      [big, zmax + 10.0], [0.0, zmax + 10.0]])])
    try:
        cavity = mf.CrossSection.batch_boolean([inner, clip], mf.OpType.Intersect)
    except Exception as exc:
        raise GeometryError(f"Не удалось обрезать полость: {exc}") from exc
    if cavity.num_contour() == 0 or cavity.area() <= 1e-9:
        raise GeometryError("Полость пустая: уменьшите толщину стенки.",
                            hint=f"Для тела высотой {zmax - zmin:g} мм стенка должна быть меньше.")
    contours = []
    lift = max(5.0, (zmax - zmin) * 0.25)
    for poly in cavity.to_polygons():
        arr = np.asarray(poly, dtype=np.float64)
        if len(arr) < 3:
            continue
        arr = arr.copy()
        if open_mode in ("top", "both"):
            arr[arr[:, 1] >= zmax - t * 1.5, 1] = zmax + lift
        if open_mode in ("bottom", "both"):
            arr[arr[:, 1] <= zmin + t * 1.5, 1] = zmin - lift
        contours.append(arr)
    if not contours:
        raise GeometryError("Не удалось построить полость.")
    cavity_cs = mf.CrossSection(contours)
    if cavity_cs.num_contour() == 0 or cavity_cs.area() <= 1e-9:
        raise GeometryError("Полость пустая: уменьшите толщину стенки.")
    if abs(arc - 360.0) < 1e-9:
        cavity_m = mf.Manifold.revolve(cavity_cs, segments)
    else:
        cavity_m = mf.Manifold.revolve(cavity_cs, segments, arc)
    result = solid - cavity_m
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После выдалбливания ничего не осталось: уменьшите толщину стенки.")
    return result


@op("extrude", aliases=("выдавить", "вытянуть", "extrusion"),
    category="Тела вращения и развёртки",
    summary="Выдавливает 2D-профиль вверх по Z; можно закручивать и сужать верх.",
    example="""планка = extrude profile=[[-50,-10],[50,-10],[50,10],[-50,10]] height=8 fillet=2""",
    params={"profile": "контур [[x,y],...] (обязательно)",
            "holes": "отверстия: [[[x,y],...], ...]",
            "height": "высота, мм (обязательно)",
            "twist": "закрутка верха, градусы",
            "scale_top": "масштаб верхнего сечения (число или [sx,sy])",
            "fillet": "скруглить углы профиля, мм",
            "divisions": "промежуточных сечений (для закрутки)"},
    positional=["profile"])
def extrude(a, name):
    prof = _clean_profile(as_points(a.value("profile"), 2, "profile"))
    prof = ensure_ccw(prof)
    fillet = a.num("fillet", 0.0, minv=0.0)
    if fillet and fillet > 0:
        prof = fillet_polyline(prof, float(fillet), closed=True)
    contours = [prof]
    if a.has("holes"):
        holes_val = a.value("holes")
        if not isinstance(holes_val, list):
            raise GeometryError("Параметр holes должен быть списком контуров.")
        for i, hole in enumerate(holes_val):
            hp = _clean_profile(as_points(hole, 2, f"holes[{i}]"))
            contours.append(ensure_ccw(hp)[::-1])
    height = a.num("height", required=True, minv=1e-3)
    twist = a.num("twist", 0.0)
    scale_top = a.vec("scale_top", 2, default=(1.0, 1.0))
    divisions = a.int("divisions", 0, minv=0, maxv=256) or 0
    if abs(twist) > 1e-6 and divisions == 0:
        divisions = max(1, int(abs(twist) / 10))
    solid = mf.CrossSection(contours).extrude(float(height), int(divisions),
                                              float(twist), scale_top)
    return make_solid(a.scene, name, solid, a, kind="extrude")


@op("sweep", aliases=("развёртка", "протяжка", "труба_по_пути", "ручка"),
    category="Тела вращения и развёртки",
    summary="Протягивает профиль вдоль 3D-пути. Идеально для ручек, поручней, рам, спиралей.",
    example="""ручка = sweep path=[[42,0,20],[58,0,45],[42,0,70]] radius=5.5 smooth=8""",
    params={"path": "путь [[x,y,z],...] (обязательно)",
            "profile": "2D-профиль [[x,y],...]; если нет — круг radius или эллипс width/height",
            "radius": "радиус круглого профиля, мм",
            "width": "ширина эллипса",
            "height": "высота эллипса",
            "sides": "точек в круглом профиле (24)",
            "smooth": "сглаживание пути: подсегментов на участок",
            "closed_path": "замкнутый путь (кольцо)",
            "twist": "закрутка профиля по пути, градусы",
            "scale_end": "масштаб профиля в конце пути",
            "scale_curve": "толщина по длине пути: [0.4, 1.0, 0.5] — банан, луковица",
            "round_caps": "скруглить торцы: 0..1 (0 — плоские, 0.6 — заметная полусфера)",
            "up": "вектор «вверх» для ориентации профиля [x,y,z]",
            "caps": "закрывать торцы (true)"},
    positional=["path", "profile"])
def sweep(a, name):
    path = a.points("path", 3)
    path = np.asarray(path, dtype=np.float64)
    if len(path) < 2:
        raise GeometryError("Путь развёртки должен содержать минимум 2 точки.")
    if a.has("profile"):
        prof = _clean_profile(as_points(a.value("profile"), 2, "profile"))
    elif a.has("radius"):
        prof = circle_profile(a.num("radius", required=True, minv=0.01),
                              a.int("sides", 24, minv=3, maxv=256))
    elif a.has("width") and a.has("height"):
        prof = ellipse_profile(a.num("width", required=True, minv=0.01),
                               a.num("height", required=True, minv=0.01),
                               a.int("sides", 24, minv=3, maxv=256))
    else:
        raise GeometryError("Для развёртки нужен profile, radius или width+height.",
                            hint="Например: sweep path=[[40,0,20],[60,0,45],[40,0,70]] radius=5")
    prof = ensure_ccw(prof)
    smooth = a.int("smooth", 0, minv=0, maxv=32) or 0
    closed_path = a.boolean("closed_path", False)
    if smooth > 1:
        path = catmull_rom(path, closed=closed_path, samples=smooth)
    up = a.vec("up", 3, default=(0.0, 0.0, 1.0))
    curve_raw = a.value("scale_curve", None)
    curve = None
    if curve_raw is not None:
        if not isinstance(curve_raw, list) or len(curve_raw) < 2:
            raise GeometryError("scale_curve — список чисел: [0.4, 1.0, 0.6].")
        curve = [float(v) for v in curve_raw]
        if min(curve) <= 0.0:
            raise GeometryError("scale_curve: все значения должны быть > 0.")
    solid = sweep_solid(path, prof, closed_path=closed_path,
                        twist_deg=float(a.num("twist", 0.0) or 0.0),
                        scale_end=float(a.num("scale_end", 1.0, minv=0.01) or 1.0),
                        up_hint=up, what="развёртка", scale_curve=curve,
                        round_caps=float(a.num("round_caps", 0.0, minv=0.0, maxv=1.0) or 0.0))
    if not closed_path and not a.boolean("caps", True):
        a.scene.log("warn", "caps=false пока не поддерживается: торцы закрыты.", a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="sweep")


def _parse_sections(raw) -> list[np.ndarray]:
    if not isinstance(raw, list) or not raw:
        raise GeometryError("Сечения задаются списком контуров: sections=[[[x,y],...], ...].")
    sections: list[np.ndarray] = []
    for i, sec in enumerate(raw):
        if isinstance(sec, (list, tuple)):
            arr = as_points(sec, 2, f"sections[{i}]")
        else:
            raise GeometryError(f"sections[{i}] должен быть списком точек.")
        if len(arr) < 3:
            raise GeometryError(f"В сечении {i + 1} меньше 3 точек.")
        sections.append(arr)
    return sections


@op("loft", aliases=("лофт", "сечения", "переход", "кузов"),
    category="Тела вращения и развёртки",
    summary="Соединяет набор 2D-сечений вдоль оси — основной инструмент для кузовов, корпусов и обтекаемых форм.",
    example="""кузов = loft sections=[[[-30,10],[30,10],[32,30],[0,38],[-32,30]], [[-40,8],[40,8],[42,28],[0,40],[-42,28]]] positions=[0,400] axis=x""",
    params={"sections": "список 2D-сечений; координаты — две другие оси (для axis=x это y,z) (обязательно)",
            "positions": "координаты сечений вдоль оси (по умолчанию 0..height)",
            "z": "то же, что positions",
            "height": "длина, если positions не заданы",
            "axis": "ось: z (по умолчанию), x или y",
            "smooth": "сглаживание вдоль оси (1 = выключено)",
            "profile_smooth": "сглаживание самого контура сечения (1 = выключено)",
            "caps": "закрывать торцы (true)"},
    positional=["sections"])
def loft(a, name):
    raw = a.value("sections")
    sections = _parse_sections(raw)
    counts = {len(s) for s in sections}
    if len(counts) > 1:
        raise GeometryError(
            f"У сечений разное количество точек: {sorted(counts)}.",
            hint="Все сечения должны иметь одинаковое число точек в одинаковом порядке.",
        )
    axis = (a.text("axis", "z", ["z", "x", "y"]) or "z").lower()
    pos_raw = a.value("positions", None)
    if pos_raw is None:
        pos_raw = a.value("z", None)
    if pos_raw is not None:
        if not isinstance(pos_raw, list):
            raise GeometryError("positions должен быть списком чисел.")
        positions = [float(p) for p in pos_raw]
    else:
        height = a.num("height", 100.0, minv=0.01)
        n = len(sections)
        positions = list(np.linspace(0.0, float(height), n)) if n > 1 else [0.0]
    if len(positions) != len(sections):
        raise GeometryError(f"Сечений {len(sections)}, а позиций {len(positions)} — должно совпадать.")
    smooth = a.int("smooth", 1, minv=1, maxv=16) or 1
    profile_smooth = a.int("profile_smooth", 1, minv=1, maxv=8) or 1
    if profile_smooth > 1:
        sections = [smooth_closed_profile(sec, samples=int(profile_smooth), keep_count=True)
                    for sec in sections]
    caps = a.boolean("caps", True)
    if smooth > 1:
        solid = loft_solid_smooth(sections, positions, axis=axis, caps=caps, smooth=int(smooth))
    else:
        solid = loft_solid(sections, positions, axis=axis, caps=caps)
    return make_solid(a.scene, name, solid, a, kind="loft")
