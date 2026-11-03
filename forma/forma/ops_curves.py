"""Тела вращения, выдавливание, развёртка, лофт."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .contour import resolve_contour, unify_closed_profiles
from .errors import GeometryError
from .geometry import (FINENESS_MM, as_points, auto_segments, catmull_rom, circle_profile,
                       ellipse_profile, ensure_ccw, fillet_polyline, limit_segments,
                       loft_solid, loft_solid_smooth, polygon_area,
                       smooth_closed_profile, sweep_solid)
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


def _operation_tolerance(a) -> float | None:
    return (float(a.num("tolerance", None, minv=1e-6, maxv=10.0))
            if a.has("tolerance") else None)


def _points_value(a, value, dims: int, what: str) -> np.ndarray:
    """Список точек либо именованный Contour2D → координаты для операции."""
    contour = resolve_contour(a.scene, value)
    if contour is None:
        return as_points(value, dims, what)
    if dims == 3:
        # tolerance операции относится к 2D-профилю; 3D-путь уже имеет свой
        # допуск в contour2d и не должен конфликтовать с profile=... .
        return contour.points3d()
    return contour.sample(tolerance=_operation_tolerance(a))


@op("lathe", aliases=("точить", "вращение", "тело_вращения", "revolve", "vrashenie"),
    category="Тела вращения и развёртки",
    summary="Вращает замкнутый профиль (радиус, высота) вокруг оси Z. Основа для посуды, ваз, бутылок.",
    example="""корпус = lathe points=[[0,0],[40,0],[42,3],[42,90],[39,92],[38,8],[0,5]] segments=128 fillet=2""",
    params={"points": "контур в плоскости (r,z): [[r,z],...] (обязательно)",
            "segments": "сегментов по кругу (по размеру)",
            "arc": "угол вращения в градусах (360)",
            "smooth": "сгладить профиль: число подсегментов на участок",
            "fillet": "скруглить углы профиля радиусом, мм",
            "fillet_steps": "максимум отрезков на дугу фаски (8)",
            "fillet_angle": "минимальный перелом для фаски, градусы; 0 — все углы",
            "thickness": "сделать стенку заданной толщины (пустотелое тело)",
            "open": "где открыть полость: top, bottom, both",
            "tolerance": "хордовый допуск Contour2D, мм (иначе допуск контура)"},
    positional=["points"])
def lathe(a, name):
    pts = _points_value(a, a.value("points"), 2, "профиль")
    pts = _clean_profile(np.asarray(pts, dtype=np.float64))
    pts = pts.copy()
    if np.any(pts[:, 0] < -1e-6):
        raise GeometryError("Радиус профиля не может быть отрицательным.",
                            hint="Первая координата точки — расстояние от оси вращения (≥ 0).")
    pts[:, 0] = np.clip(pts[:, 0], 0.0, None)
    fillet = a.num("fillet", 0.0, minv=0.0)
    fillet_steps = a.int("fillet_steps", 8, minv=2, maxv=48)
    fillet_angle = (a.num("fillet_angle", None, minv=0.0, maxv=180.0)
                    if a.has("fillet_angle") else None)
    smooth = a.int("smooth", 0, minv=0, maxv=32)
    legacy_smooth_profile = (smooth > 1 and not a.has("fillet_steps")
                             and not a.has("fillet_angle"))
    if fillet and fillet > 0:
        pts = fillet_polyline(pts, float(fillet), closed=True, skip_axis=True,
                              arc_steps=int(fillet_steps),
                              min_turn=(None if fillet_angle is None
                                        else math.radians(float(fillet_angle))),
                              adaptive=not legacy_smooth_profile)
    if smooth and smooth > 1:
        pts = smooth_closed_profile(pts, samples=int(smooth))
    radius_max = float(np.max(np.abs(pts[:, 0]))) if len(pts) else 50.0
    asked = a.int("segments", None, minv=8, maxv=1024)
    tolerance = (a.scene.precision_tolerance(FINENESS_MM, scale=False)
                 if asked is None else FINENESS_MM)
    factor = a.scene.precision_factor if asked is None else 1.0
    segments = int(limit_segments(asked, radius_max, tolerance=tolerance,
                                  max_n=1024, factor=factor))
    if asked and segments < asked:
        a.scene.log("info", f"точение: {asked} → {segments} сегментов "
                            f"(отклонение ≤ {FINENESS_MM:g} мм)", a.cmd.line)
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


def _extrude_cavity(cs: mf.CrossSection, height: float, thickness: float,
                    open_mode: str) -> mf.Manifold:
    """Полость по истинному 2D-offset всего сечения, включая отверстия."""
    inner = cs.offset(-float(thickness))
    if inner.num_contour() == 0 or inner.area() <= 1e-9:
        raise GeometryError("Полость пустая: уменьшите толщину стенки.")
    margin = max(1.0, thickness, height * 0.01)
    if open_mode == "top":
        z0, cavity_height = thickness, height - thickness + margin
    elif open_mode == "bottom":
        z0, cavity_height = -margin, height - thickness + margin
    elif open_mode == "both":
        z0, cavity_height = -margin, height + 2 * margin
    else:
        if height <= 2 * thickness:
            raise GeometryError("Закрытая полость требует height > 2·thickness.")
        z0, cavity_height = thickness, height - 2 * thickness
    return inner.extrude(float(cavity_height)).translate([0.0, 0.0, float(z0)])


def _offset_loft(profile: np.ndarray, z0: float, z1: float,
                 offset0: float, offset1: float, what: str = "Литейный уклон") -> mf.Manifold:
    """Лофт двух точных 2D-offset'ов одного контура на разных высотах."""
    if z1 <= z0:
        raise GeometryError(f"{what}: верх сечения должен быть выше низа.")
    base = ensure_ccw(np.asarray(profile, dtype=np.float64))
    cs = mf.CrossSection([base])
    cs0 = cs if abs(offset0) < 1e-12 else cs.offset(float(offset0))
    cs1 = cs if abs(offset1) < 1e-12 else cs.offset(float(offset1))
    if (cs0.num_contour() != 1 or cs1.num_contour() != 1
            or cs0.area() <= 1e-9 or cs1.area() <= 1e-9):
        raise GeometryError(f"{what}: сечение выродилось; уменьшите уклон, толщину или height.")
    p0 = np.asarray(cs0.to_polygons()[0], dtype=np.float64)
    p1 = np.asarray(cs1.to_polygons()[0], dtype=np.float64)
    rings = unify_closed_profiles([p0, p1])
    return loft_solid(rings, [z0, z1], axis="z", caps=True, what=what,
                      cap_end_profile=rings[-1])


def _draft_ring(profile: np.ndarray, height: float, offset: float) -> mf.Manifold:
    """Прямая двухсекционная вытяжка с точным offset верхнего сечения."""
    return _offset_loft(profile, 0.0, height, 0.0, offset)


def _draft_cavity(profile: np.ndarray, holes: list[np.ndarray], height: float,
                  draft: float, thickness: float, open_mode: str) -> mf.Manifold:
    """Полость с тем же уклоном, что и наружное тело, без mesh-Minkowski.

    Смещение стенки по нормали учитывает наклон: горизонтальный offset равен
    t·sqrt(1+tan(draft)²). Для отверстий знак offset противоположный.
    """
    slope = math.tan(math.radians(draft))
    normal_offset = thickness * math.sqrt(1.0 + slope * slope)
    margin = max(1e-4, min(0.1, height * 0.01))
    if open_mode == "top":
        z0, z1 = thickness, height + margin
    elif open_mode == "bottom":
        z0, z1 = -margin, height - thickness
    elif open_mode == "both":
        z0, z1 = -margin, height + margin
    else:
        if height <= 2 * thickness:
            raise GeometryError("Закрытая полость требует height > 2·thickness.")
        z0, z1 = thickness, height - thickness
    cavity = _offset_loft(profile, z0, z1,
                          -slope * z0 - normal_offset,
                          -slope * z1 - normal_offset, "Полость с уклоном")
    for hole in holes:
        cutter = _offset_loft(hole, z0, z1,
                              slope * z0 + normal_offset,
                              slope * z1 + normal_offset, "Полость отверстия")
        cavity = cavity - cutter
    if cavity.is_empty() or cavity.volume() <= 1e-9:
        raise GeometryError("Полость с уклоном пуста: уменьшите толщину стенки.")
    return cavity


def _draft_extrude(profile: np.ndarray, holes: list[np.ndarray], height: float,
                   draft: float) -> mf.Manifold:
    delta = height * math.tan(math.radians(draft))
    solid = _draft_ring(profile, height, -delta)
    for hole in holes:
        solid = solid - _draft_ring(hole, height, delta)
    return solid


@op("extrude", aliases=("выдавить", "вытянуть", "extrusion"),
    category="Тела вращения и развёртки",
    summary="Выдавливает 2D-профиль вверх по Z; стенка и уклон строятся точным offset.",
    example="""планка = extrude profile=[[-50,-10],[50,-10],[50,10],[-50,10]] height=8 fillet=2""",
    params={"profile": "контур [[x,y],...] или имя Contour2D (обязательно)",
            "holes": "отверстия: списки точек или имена Contour2D",
            "height": "высота, мм (обязательно)",
            "twist": "закрутка верха, градусы",
            "scale_top": "масштаб верхнего сечения (число или [sx,sy])",
            "fillet": "скруглить углы профиля, мм",
            "fillet_steps": "максимум отрезков на дугу фаски (8)",
            "fillet_angle": "минимальный перелом для фаски, градусы; 0 — все углы",
            "divisions": "промежуточных сечений (для закрутки)",
            "thickness": "толщина стенки, мм; 0 — сплошное тело",
            "open": "открытая сторона при thickness: top, bottom, both, none",
            "draft": "литейный уклон, градусы; положительный сужает наружный контур",
            "tolerance": "хордовый допуск Contour2D, мм"},
    positional=["profile"])
def extrude(a, name):
    prof = _clean_profile(_points_value(a, a.value("profile"), 2, "profile"))
    prof = ensure_ccw(prof)
    fillet = a.num("fillet", 0.0, minv=0.0)
    fillet_steps = a.int("fillet_steps", 8, minv=2, maxv=48)
    fillet_angle = (a.num("fillet_angle", None, minv=0.0, maxv=180.0)
                    if a.has("fillet_angle") else None)
    if fillet and fillet > 0:
        prof = fillet_polyline(prof, float(fillet), closed=True,
                               arc_steps=int(fillet_steps),
                               min_turn=(None if fillet_angle is None
                                         else math.radians(float(fillet_angle))))
    contours = [prof]
    holes: list[np.ndarray] = []
    if a.has("holes"):
        holes_val = a.value("holes")
        if isinstance(holes_val, str) or resolve_contour(a.scene, holes_val) is not None:
            holes_val = [holes_val]
        elif (isinstance(holes_val, list) and holes_val
              and all(isinstance(p, (list, tuple)) and len(p) == 2
                      and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p)
                      for p in holes_val)):
            # Удобная короткая форма: holes=[[x,y], ...] — один контур.
            holes_val = [holes_val]
        if not isinstance(holes_val, list):
            raise GeometryError("Параметр holes должен быть списком контуров.")
        for i, hole in enumerate(holes_val):
            hp = _clean_profile(_points_value(a, hole, 2, f"holes[{i}]"))
            hp = ensure_ccw(hp)
            holes.append(hp)
            contours.append(hp[::-1])
    height = float(a.num("height", required=True, minv=1e-3))
    twist = a.num("twist", 0.0)
    scale_top = a.vec("scale_top", 2, default=(1.0, 1.0))
    divisions = a.int("divisions", 0, minv=0, maxv=256) or 0
    thickness = float(a.num("thickness", 0.0, minv=0.0))
    open_mode = a.text("open", "top", ["top", "bottom", "both", "none"]) or "top"
    draft = float(a.num("draft", 0.0, minv=-45.0, maxv=45.0))
    if a.has("open") and thickness <= 0:
        raise GeometryError("open задаёт открытую сторону только при thickness>0.")
    if abs(twist) > 1e-6 and divisions == 0:
        divisions = max(1, int(abs(twist) / 10))
    if abs(draft) > 1e-9:
        if abs(twist) > 1e-9 or np.linalg.norm(scale_top - np.ones(2)) > 1e-9:
            raise GeometryError("draft нельзя совмещать с twist или scale_top.",
                                hint="Литейный уклон уже задаёт точное верхнее сечение.")
        solid = _draft_extrude(prof, holes, height, draft)
    else:
        solid = mf.CrossSection(contours).extrude(height, int(divisions),
                                                  float(twist), scale_top)
    if thickness > 0:
        if abs(draft) > 1e-9:
            solid = solid - _draft_cavity(prof, holes, height, draft, thickness, open_mode)
        else:
            solid = solid - _extrude_cavity(mf.CrossSection(contours), height,
                                            thickness, open_mode)
    if solid.is_empty() or solid.volume() <= 1e-9:
        raise GeometryError("После построения стенки/уклона ничего не осталось.")
    out = make_solid(a.scene, name, solid, a, kind="extrude")
    out.meta.update({"wall_thickness": thickness, "draft_angle": draft,
                     "contour_tolerance": _operation_tolerance(a)})
    return out


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
            "caps": "закрывать торцы (true)",
            "tolerance": "хордовый допуск 2D Contour2D, мм"},
    positional=["path", "profile"])
def sweep(a, name):
    path_contour = resolve_contour(a.scene, a.value("path"))
    path = _points_value(a, a.value("path"), 3, "path")
    path = np.asarray(path, dtype=np.float64)
    if len(path) < 2:
        raise GeometryError("Путь развёртки должен содержать минимум 2 точки.")
    def _sides(radius: float) -> int:
        asked = a.int("sides", 24, minv=3, maxv=256)
        got = int(limit_segments(asked, radius, tolerance=FINENESS_MM, max_n=256))
        if got < asked:
            a.scene.log("info", f"развёртка: {asked} → {got} сторон профиля "
                                f"(отклонение ≤ {FINENESS_MM:g} мм)", a.cmd.line)
        return max(3, got)

    if a.has("profile"):
        prof = _clean_profile(_points_value(a, a.value("profile"), 2, "profile"))
    elif a.has("radius"):
        radius = a.num("radius", required=True, minv=0.01)
        prof = circle_profile(radius, _sides(radius))
    elif a.has("width") and a.has("height"):
        w = a.num("width", required=True, minv=0.01)
        h = a.num("height", required=True, minv=0.01)
        prof = ellipse_profile(w, h, _sides(max(w, h) / 2.0))
    else:
        raise GeometryError("Для развёртки нужен profile, radius или width+height.",
                            hint="Например: sweep path=[[40,0,20],[60,0,45],[40,0,70]] radius=5")
    prof = ensure_ccw(prof)
    smooth = a.int("smooth", 0, minv=0, maxv=32) or 0
    closed_path = a.boolean("closed_path", bool(path_contour is not None and path_contour.is_closed))
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


def _parse_sections(raw, scene, tolerance: float | None) -> tuple[list[np.ndarray], bool]:
    if not isinstance(raw, list) or not raw:
        raise GeometryError("Сечения задаются списком контуров: sections=[[[x,y],...], ...].")
    sections: list[np.ndarray] = []
    used_contour = False
    for i, sec in enumerate(raw):
        contour = resolve_contour(scene, sec)
        if contour is not None:
            arr = contour.sample(tolerance=tolerance)
            used_contour = True
        elif isinstance(sec, (list, tuple)):
            arr = as_points(sec, 2, f"sections[{i}]")
        else:
            raise GeometryError(f"sections[{i}] должен быть списком точек или именем Contour2D.")
        if len(arr) < 3:
            raise GeometryError(f"В сечении {i + 1} меньше 3 точек.")
        sections.append(arr)
    return sections, used_contour


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
            "caps": "закрывать торцы (true)",
            "tolerance": "хордовый допуск Contour2D, мм"},
    positional=["sections"])
def loft(a, name):
    raw = a.value("sections")
    sections, used_contour = _parse_sections(raw, a.scene, _operation_tolerance(a))
    if used_contour:
        sections = unify_closed_profiles(sections)
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
    end_profile = sections[-1] if used_contour else None
    if smooth > 1:
        solid = loft_solid_smooth(sections, positions, axis=axis, caps=caps, smooth=int(smooth),
                                  cap_end_profile=end_profile)
    else:
        solid = loft_solid(sections, positions, axis=axis, caps=caps,
                           cap_end_profile=end_profile)
    return make_solid(a.scene, name, solid, a, kind="loft")
