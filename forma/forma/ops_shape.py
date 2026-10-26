"""Булевы операции, полые тела, массивы, преобразования и деформации."""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import DslError, GeometryError
from . import orient
from .geometry import fibonacci_sphere
from .ops import (anchor, ensure_solid, make_solid, mirror as mirror_manifold,
                  merge_solids, op, rotate as rotate_manifold, scale as scale_manifold,
                  translate as translate_manifold)


def _derived(a, name, manifold, base, kind: str):
    solid = make_solid(a.scene, name or base.name, manifold, a, base=base, kind=kind)
    a.scene.consume(base)
    return solid


def _parts_follow(a, base, fn, rotation=None) -> None:
    """Двигает вместе с объектом его составные детали.

    Если задана матрица поворота 3×3, тем же преобразованием обновляются и
    локальные оси каждой детали — корпус не расходится с экраном и кнопками.

    Составные команды (mirror_plate, семисегментные часы…) кладут в сцену не одно
    тело, а корпус и детали «корпус.экран», «корпус.цифры», «корпус.стекло».
    Раньше поворот или сдвиг двигал только корпус, и цифры оставались висеть
    на старом месте. Здесь та же операция применяется к деталям.
    """
    prefix = f"{base.name}."
    for child in list(a.scene.objects.values()):
        if child is base or not child.name.startswith(prefix):
            continue
        if any("использован" in n for n in getattr(child, "notes", []) or []):
            continue
        try:
            child.manifold = fn(child.manifold)
            child._stats = None
            if rotation is not None:
                orient.set_axes(child, np.asarray(rotation, dtype=np.float64).reshape(3, 3)
                                @ orient.axes_of(child))
        except Exception:
            continue


# --------------------------------------------------------------------------- #
#  Булевы операции
# --------------------------------------------------------------------------- #

@op("union", aliases=("объединить", "объединение", "плюс", "add"), category="Булевы операции",
    summary="Объединяет объекты в один. Исходные объекты скрываются.",
    example='корпус = cylinder radius=40 height=95\nручка = box size=[40,12,30] at=[30,0,50]\nкружка = union [корпус, ручка]',
    params={"objects": "список объектов [a, b, ...]"}, positional="*")
def union(a, name):
    solids = a.solids()
    if len(solids) < 2:
        raise GeometryError("Для объединения нужно минимум два объекта.")
    try:
        merged = merge_solids(solids, mf.OpType.Add)
    except Exception as exc:
        raise GeometryError(f"Не удалось объединить объекты: {exc}") from exc
    for s in solids:
        a.scene.consume(s)
    made = make_solid(a.scene, name, merged, a, base=solids[0], kind="union")
    # объединение деталей с разными осями теряет общую ориентацию
    frames = [orient.axes_of(s) for s in solids]
    if any(not np.allclose(f, frames[0], atol=1e-6) for f in frames[1:]):
        orient.set_axes(made, np.eye(3))
    return made


@op("difference", aliases=("вычесть", "минус", "subtract", "отверстие"), category="Булевы операции",
    summary="Вычитает объекты из первого. Первый объект — основа, остальные — вычитаемые.",
    example='заготовка = box size=[60,60,60]\nполость = sphere radius=22 at=[0,0,50]\nстакан = difference [заготовка, полость]',
    params={"objects": "список [основа, вычитаемое, ...]"}, positional="*")
def difference(a, name):
    solids = a.solids()
    if len(solids) < 2:
        raise GeometryError("Для вычитания нужны минимум два объекта: основа и вычитаемое.",
                           hint="Например: difference [корпус, отверстие]")
    try:
        merged = merge_solids(solids, mf.OpType.Subtract)
    except Exception as exc:
        raise GeometryError(f"Не удалось вычесть объекты: {exc}") from exc
    if merged.is_empty() or merged.volume() <= 1e-9:
        raise GeometryError("После вычитания ничего не осталось.",
                            hint="Вычитаемый объект полностью перекрыл основу.")
    for s in solids:
        a.scene.consume(s)
    return make_solid(a.scene, name, merged, a, base=solids[0], kind="difference")


def _weld_manifold(m: mf.Manifold, tol: float) -> mf.Manifold:
    """Сварка шва: склеивает совпадающие вершины и убирает вырожденные грани."""
    from .geometry import manifold_from_arrays, manifold_mesh
    try:
        import trimesh
        verts, faces = manifold_mesh(m)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        mesh.merge_vertices()
        if tol > 0:
            mesh.merge_vertices(merge_tex=False, merge_norm=False)
            mesh.update_faces(mesh.nondegenerate_faces())
            try:
                mesh.update_faces(mesh.unique_faces())
            except Exception:
                pass
            mesh.remove_unreferenced_vertices()
            # сжимаем близкие вершины к средней точке — шов становится единым
            if len(mesh.vertices):
                try:
                    mesh.merge_vertices()
                except Exception:
                    pass
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.remove_unreferenced_vertices()
        return manifold_from_arrays(np.asarray(mesh.vertices), np.asarray(mesh.faces),
                                    what="спайка")
    except Exception as exc:
        raise GeometryError(f"Не удалось спаять шов: {exc}") from exc


@op("weld", aliases=("спаять", "спайка", "сварить", "шов", "объединить_шов"),
    category="Булевы операции",
    summary="Спаивает детали в один объект и сваривает шов: внутри не остаётся "
            "скрытой геометрии, стык ровный. Для ручки кружки, корпуса и т.п.",
    example='корпус = cylinder radius=40 height=95\nручка = box size=[40,12,30] at=[30,0,50]\nкружка = weld [корпус, ручка] tolerance=0.05',
    params={"objects": "список [деталь, деталь, ...]",
            "tolerance": "допуск сварки вершин, мм (0.05)"},
    positional="*")
def weld(a, name):
    solids = a.solids()
    if not solids:
        raise GeometryError("weld: нечего спаивать.",
                            hint="Например: кружка = weld [корпус, ручка]")
    tol = float(a.num("tolerance", 0.05, minv=0.0) or 0.0)
    try:
        if len(solids) > 1:
            merged = merge_solids(solids, mf.OpType.Add)
        else:
            merged = solids[0].manifold
        for s in solids:
            a.scene.consume(s)
        result = _weld_manifold(merged, tol)
    except Exception as exc:
        if isinstance(exc, GeometryError):
            raise
        raise GeometryError(f"Не удалось спаять объекты: {exc}") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После спайки ничего не осталось.")
    a.scene.log("info", f"спайка: {merged.num_tri()} → {result.num_tri()} треугольников, "
                        f"допуск {tol:g} мм", a.cmd.line)
    return make_solid(a.scene, name, result, a, base=solids[0], kind="weld")


@op("trim", aliases=("отсечь", "обрезать", "отрезать", "обрезка"),
    category="Булевы операции",
    summary="Отсекает лишнее: вычитает из первой детали остальные и спаивает шов. "
            "Внутри не остаётся геометрии — только чистый стык.",
    example='ручка = cylinder radius=6 height=40 at=[40,0,0]\nкорпус = box size=[60,60,60]\nручка = trim [ручка, корпус] tolerance=0.05',
    params={"objects": "список [основа, лишнее, ...]",
            "tolerance": "допуск сварки вершин, мм (0.05)"},
    positional="*")
def trim(a, name):
    solids = a.solids()
    if len(solids) < 2:
        raise GeometryError("trim: нужна основа и то, что отсекаем.",
                            hint="Например: ручка = trim [ручка, корпус]")
    tol = float(a.num("tolerance", 0.05, minv=0.0) or 0.0)
    try:
        merged = merge_solids(solids, mf.OpType.Subtract)
    except Exception as exc:
        raise GeometryError(f"Не удалось отсечь: {exc}") from exc
    if merged.is_empty() or merged.volume() <= 1e-9:
        raise GeometryError("После отсечения ничего не осталось.")
    for s in solids:
        a.scene.consume(s)
    result = _weld_manifold(merged, tol)
    a.scene.log("info", f"отсечение: {merged.num_tri()} → {result.num_tri()} треугольников, "
                        f"допуск {tol:g} мм", a.cmd.line)
    return make_solid(a.scene, name, result, a, base=solids[0], kind="trim")


@op("intersect", aliases=("пересечение", "пересечь", "and", "общее"), category="Булевы операции",
    summary="Оставляет только общий объём объектов.",
    example='сфера1 = sphere radius=30\nсфера2 = sphere radius=30 at=[20,0,20]\nлинза = intersect [сфера1, сфера2]',
    params={"objects": "список объектов [a, b, ...]"}, positional="*")
def intersect(a, name):
    solids = a.solids()
    if len(solids) < 2:
        raise GeometryError("Для пересечения нужно минимум два объекта.")
    try:
        merged = merge_solids(solids, mf.OpType.Intersect)
    except Exception as exc:
        raise GeometryError(f"Не удалось пересечь объекты: {exc}") from exc
    if merged.is_empty() or merged.volume() <= 1e-9:
        raise GeometryError("Объекты не пересекаются — общий объём пуст.")
    for s in solids:
        a.scene.consume(s)
    return make_solid(a.scene, name, merged, a, base=solids[0], kind="intersect")


# --------------------------------------------------------------------------- #
#  Полые тела и скругления
# --------------------------------------------------------------------------- #

def shell_manifold(m: mf.Manifold, thickness: float, open_mode: str = "top") -> mf.Manifold:
    t = float(thickness)
    if t <= 1e-6:
        return m
    bb = m.bounding_box()
    smallest = min(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
    if t * 2 >= smallest:
        raise GeometryError(
            f"Толщина стенки {t:g} мм слишком велика для объекта размером {smallest:.1f} мм.",
            hint="Стенка должна быть меньше половины наименьшего габарита.",
        )
    if m.num_tri() > 120_000:
        raise GeometryError(
            "Объект слишком подробный для полости этим способом "
            f"({m.num_tri():,} треугольников).".replace(",", " "),
            hint="Сделайте стенку прямо в lathe: thickness=4 open=top, "
                 "или упростите форму командой simplify.",
        )
    ball = mf.Manifold.sphere(t, 20)
    inner = m.minkowski_difference(ball)
    if inner.is_empty():
        raise GeometryError("Не удалось построить полость: уменьшите толщину стенки.")
    ibb = inner.bounding_box()
    extra = (bb[5] - bb[2]) + 4 * t + 10
    if open_mode in ("top", "both"):
        z = ibb[5] - t * 0.45
        if z > ibb[2] + 1e-6:
            cs = inner.slice(z)
            if cs.num_contour() > 0:
                inner = inner + cs.extrude(extra).translate((0, 0, z))
    if open_mode in ("bottom", "both"):
        z = ibb[2] + t * 0.45
        if z < ibb[5] - 1e-6:
            cs = inner.slice(z)
            if cs.num_contour() > 0:
                inner = inner + cs.extrude(extra).translate((0, 0, z - extra))
    result = m - inner
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После выдалбливания ничего не осталось: уменьшите толщину стенки.")
    return result


@op("shell", aliases=("оболочка", "полый", "выдолбить", "hollow"), category="Форма и деформации",
    summary="Делает объект полым с заданной толщиной стенки. Можно открыть верх, низ или оба.",
    example='заготовка = box size=[60,60,60] round=4\nкружка = shell [заготовка] thickness=4 open=top',
    params={"objects": "объект [a] или a", "thickness": "толщина стенки, мм (обязательно)",
            "open": "top (по умолчанию), bottom, both, none"},
    positional=["objects"])
def shell(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("shell работает с одним объектом.")
    thickness = a.num("thickness", required=True, minv=0.05)
    open_mode = a.text("open", "top", ["top", "bottom", "both", "none"]) or "top"
    result = shell_manifold(solids[0].manifold, float(thickness), open_mode)
    a.scene.consume(solids[0])
    return make_solid(a.scene, name, result, a, base=solids[0], kind="shell")


@op("offset", aliases=("смещение", "раздуть", "ужать", "inset", "outset"),
    category="Форма и деформации",
    summary="Расширяет (delta>0) или сжимает (delta<0) объект на заданную величину.",
    example='деталь = sphere radius=30 segments=48\nдеталь = offset [деталь] delta=-0.4',
    params={"objects": "объект", "delta": "смещение, мм (плюс — наружу)",
            "segments": "качество скругления (32)"},
    positional=["objects"])
def offset(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("offset работает с одним объектом.")
    delta = a.num("delta", required=True)
    if abs(delta) < 1e-6:
        return _derived(a, name, solids[0].manifold, solids[0], "offset")
    ball = mf.Manifold.sphere(abs(delta), a.int("segments", 32, minv=8, maxv=96))
    source = solids[0]
    result = source.manifold.minkowski_sum(ball) if delta > 0 else \
        source.manifold.minkowski_difference(ball)
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После сжатия объект исчез.")
    a.scene.consume(source)
    return make_solid(a.scene, name, result, a, base=source, kind="offset")


def _edge_mode(a, default: str = "all") -> str:
    raw = (a.text("edges") or a.text("кромки") or default).strip().lower()
    table = {
        "all": "all", "все": "all", "обе": "all", "оба": "all",
        "convex": "convex", "выпуклые": "convex", "наружные": "convex",
        "concave": "concave", "вогнутые": "concave", "внутренние": "concave",
    }
    mode = table.get(raw)
    if mode is None:
        raise DslError("edges бывает convex (выпуклые), concave (вогнутые) или all.",
                         hint="Пример: деталь = fillet [деталь] radius=2 edges=convex")
    return mode


def _clean_rounded(m: mf.Manifold) -> mf.Manifold:
    """Убирает вырожденные треугольники, которые оставляет minkowski."""
    from .geometry import manifold_from_arrays, manifold_mesh
    try:
        import trimesh
        verts, faces = manifold_mesh(m)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
        out = manifold_from_arrays(np.asarray(mesh.vertices), np.asarray(mesh.faces),
                                   what="скругление")
        if not out.is_empty() and abs(out.volume() - m.volume()) < m.volume() * 0.02:
            return out
    except Exception:
        pass
    return m


def _morph(a, source: mf.Manifold, tool: mf.Manifold, mode: str, kind: str) -> mf.Manifold:
    """Морфологическое скругление.

    Выпуклые рёбра скругляет opening (сжатие → рост), вогнутые — closing
    (рост → сжатие). Порядок важен: сначала closing, потом opening. Обратный
    порядок на L-образных деталях уходит в многочасовой расчёт.
    """
    steps: list[str] = []
    if mode in ("concave", "all"):
        steps.append("closing")
    if mode in ("convex", "all"):
        steps.append("opening")
    shrink = 0.0
    for step in steps:
        try:
            if step == "closing":
                source = source.minkowski_sum(tool).minkowski_difference(tool)
            else:
                source = source.minkowski_difference(tool).minkowski_sum(tool)
        except Exception as exc:
            raise GeometryError(f"Не удалось выполнить {kind} ({step}): {exc}") from exc
        if source.is_empty():
            raise GeometryError(f"{kind}: объект исчез на шаге {step} — уменьшите радиус.")
        if source.num_tri() > 120000:
            raise GeometryError(
                f"{kind}: слишком подробная сетка после {step} ({source.num_tri()} треугольников).",
                hint="Уменьшите radius/segments или примените скругление к более простой детали.")
    return source


@op("fillet", aliases=("скругление", "скруглить", "зализать"),
    category="Форма и деформации",
    summary="Скругляет рёбра радиусом: выпуклые (наружные), вогнутые (внутренние) "
            "или все сразу — в отличие от bevel, который снимает материал только снаружи.",
    example='корпус = box size=[60,60,80]\nкорпус = fillet [корпус] radius=3 edges=convex',
    params={"objects": "объект", "radius": "радиус скругления, мм (обязательно)",
            "edges": "convex (наружные), concave (внутренние) или all (оба; по умолчанию)",
            "segments": "качество скругления 8…40 (12 — без тонких треугольников)"},
    positional=["objects"])
def fillet(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("fillet работает с одним объектом.")
    radius = a.num("radius", required=True, minv=0.05)
    mode = _edge_mode(a, "all")
    source = solids[0]
    if source.manifold.num_tri() > 12000:
        raise GeometryError(
            "Слишком подробная сетка для скругления рёбер — это надолго.",
            hint="Сначала упростите: имя = simplify [объект] tolerance=0.2, "
                 "или задайте round у примитива.")
    ball = mf.Manifold.sphere(float(radius), a.int("segments", 12, minv=8, maxv=40))
    v0 = float(source.manifold.volume())
    result = _morph(a, source.manifold, ball, mode, "fillet")
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После скругления объект исчез — уменьшите radius.")
    result = _clean_rounded(result)
    v1 = float(result.volume())
    if v1 < v0 * 0.7:
        raise GeometryError(
            f"Скругление radius={radius:g} слишком велико: объём упал на {(1 - v1 / v0) * 100:.0f} %.",
            hint="Уменьшите radius или сделайте скругление на примитиве (round=…).")
    a.scene.log("info", f"fillet: {mode}, радиус {radius:g} мм, "
                        f"объём {(v1 / v0 - 1) * 100:+.2f} %", a.cmd.line)
    a.scene.consume(source)
    return make_solid(a.scene, name, result, a, base=source, kind="fillet")


def _chamfer_tool(width: float) -> mf.Manifold:
    """Инструмент фаски — октаэдр (ромб).

    Opening кубом ничего не срезает (куб «совпадает» с гранями детали),
    а ромб срезает кромку плоской гранью под 45° — это и есть фаска.
    """
    r = float(width) * 1.7320508  # вписанная сфера октаэдра = r/√3 = width
    return mf.Manifold.hull_points([[r, 0, 0], [-r, 0, 0], [0, r, 0],
                                    [0, -r, 0], [0, 0, r], [0, 0, -r]])


@op("chamfer", aliases=("снять_фаску", "срез", "кромка45"),
    category="Форма и деформации",
    summary="Снимает кромку плоской фаской под 45° (в отличие от fillet — без радиуса).",
    example='плита = box size=[60,40,20]\nплита = chamfer [плита] width=2 edges=convex',
    params={"objects": "объект", "width": "ширина фаски, мм (2% самой тонкой стороны)",
            "edges": "convex (наружные), concave (внутренние) или all"},
    positional=["objects"])
def chamfer(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("chamfer работает с одним объектом.")
    source = solids[0]
    bbox = source.manifold.bounding_box()
    thin = min(bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2])
    width = a.num("width", None, minv=0.05)
    if width is None:
        width = thin * 0.02
    width = float(min(width, thin * 0.4))
    mode = _edge_mode(a, "convex")
    if source.manifold.num_tri() > 40000:
        raise GeometryError(
            "Слишком подробная сетка для фаски — это надолго.",
            hint="Сначала упростите: имя = simplify [объект] tolerance=0.2.")
    tool = _chamfer_tool(width)
    v0 = float(source.manifold.volume())
    result = _morph(a, source.manifold, tool, mode, "chamfer")
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После фаски объект исчез — уменьшите width.")
    result = _clean_rounded(result)
    v1 = float(result.volume())
    if v1 < v0 * 0.7:
        raise GeometryError(
            f"Фаска width={width:g} слишком велика: объём упал на {(1 - v1 / v0) * 100:.0f} %.",
            hint="Уменьшите width.")
    a.scene.log("info", f"chamfer: {mode}, ширина {width:g} мм, "
                        f"объём {(v1 / v0 - 1) * 100:+.2f} %", a.cmd.line)
    a.scene.consume(source)
    return make_solid(a.scene, name, result, a, base=source, kind="chamfer")


# --------------------------------------------------------------------------- #
#  Массивы
# --------------------------------------------------------------------------- #

def _rotate_about(m, axis: str, angle: float, center) -> mf.Manifold:
    axis_vec = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
    return rotate_manifold(m, angle, axis_vec, center)


@op("array", aliases=("массив", "копии", "повторить", "размножить"), category="Массивы и преобразования",
    summary="Создаёт копии объекта: линейно, по кругу или сеткой. Радиальный массив "
            "ставит копии на окружность радиуса radius, поворачивает каждую вокруг "
            "своей оси или распределяет по сектору angle.",
    example='стойка = cylinder radius=6 height=60\n'
            'кольцо = array [стойка] count=8 mode=radial radius=60 around=z\n'
            'деталь = box size=[24,10,8]\n'
            'веер = array [деталь] count=5 mode=radial radius=80 angle=180 spin=да',
    params={"objects": "исходный объект (или несколько — они объединяются)",
            "count": "количество копий (включая исходную)",
            "mode": "linear (по умолчанию), radial (по кругу), grid (сетка)",
            "offset": "шаг для linear [dx,dy,dz]",
            "around": "ось вращения для radial: x, y или z",
            "radius": "радиус окружности для radial, мм (0 — вращать на месте)",
            "angle": "полный угол для radial: 360 — полный круг, меньше — сектор (360)",
            "start": "начальный угол для radial, градусы (0)",
            "spin": "поворачивать каждую копию вокруг своей оси (да)",
            "center": "центр вращения / точка отсчёта сетки",
            "counts": "для grid: [nx,ny,nz]",
            "spacing": "для grid: шаг [dx,dy,dz]",
            "at": "сдвиг готового массива [x,y,z]"},
    positional=["objects"])
def array(a, name):
    sources = a.solids()
    base = sources[0]
    source = merge_solids(sources) if len(sources) > 1 else sources[0].manifold
    mode = a.text("mode", "linear", ["linear", "radial", "grid"]) or "linear"
    count = a.int("count", 2, minv=1, maxv=400)
    if count is None:
        count = 2
    copies = [source]
    if mode == "linear":
        offset = a.vec("offset", 3, default=(20.0, 0.0, 0.0))
        for i in range(1, count):
            copies.append(translate_manifold(source, np.array(offset) * i))
    elif mode == "radial":
        axis = (a.text("around", "z", ["x", "y", "z"]) or "z").lower()
        center = np.asarray(a.vec("center", 3, default=(0.0, 0.0, 0.0)),
                            dtype=np.float64)
        total = float(a.num("angle", 360.0) or 360.0)
        start = float(a.num("start", 0.0) or 0.0)
        radius = float(a.num("radius", 0.0, minv=0.0) or 0.0)
        spin = a.boolean("spin", True)
        full = abs(abs(total) - 360.0) < 1e-6
        if count > 1:
            step = total / count if full else total / (count - 1)
        else:
            step = 0.0
        if radius <= 1e-9:
            for i in range(1, count):
                copies.append(_rotate_about(source, axis, start + step * i, center))
        else:
            # окружность в плоскости, перпендикулярной оси; по умолчанию она
            # охватывает сам предмет, а не начало координат
            if axis == "x":
                u, v = np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, 1.0])
            elif axis == "y":
                u, v = np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])
            else:
                u, v = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
            sb = source.bounding_box()
            own = np.array([(sb[0] + sb[3]) / 2.0, (sb[1] + sb[4]) / 2.0,
                            (sb[2] + sb[5]) / 2.0])
            hub = center if a.has("center") else own
            copies = []                     # все копии встают на окружность
            for i in range(count):
                az = start + step * i
                ang = math.radians(az)
                point = hub + radius * (math.cos(ang) * u + math.sin(ang) * v)
                copy = translate_manifold(source, point - own)
                if spin:
                    copy = _rotate_about(copy, axis, az, point)
                copies.append(copy)
    else:
        counts = a.vec("counts", 3, default=(2.0, 1.0, 1.0))
        counts_i = [max(1, int(round(c))) for c in counts]
        spacing = a.vec("spacing", 3, default=(20.0, 0.0, 0.0))
        center = a.vec("center", 3, default=(0.0, 0.0, 0.0))
        if counts_i[0] * counts_i[1] * counts_i[2] > 500:
            raise GeometryError("Слишком много копий в сетке (максимум 500).")
        for ix in range(counts_i[0]):
            for iy in range(counts_i[1]):
                for iz in range(counts_i[2]):
                    if ix == 0 and iy == 0 and iz == 0:
                        continue
                    off = np.array([ix * spacing[0], iy * spacing[1], iz * spacing[2]])
                    copies.append(translate_manifold(source, np.array(center) + off))
    for s in sources:
        a.scene.consume(s)
    merged = mf.Manifold.batch_boolean(copies, mf.OpType.Add)
    if a.has("at"):
        merged = translate_manifold(merged, np.asarray(a.vec("at", 3), dtype=np.float64))
    if merged.num_tri() > 1_500_000:
        a.scene.log("warn", "Массив получился очень тяжёлым — уменьшите количество копий.",
                    a.cmd.line)
    made = make_solid(a.scene, name, merged, a, base=base, kind="array")
    # у копий разные повороты — общей ориентации у массива нет
    orient.set_axes(made, np.eye(3))
    return made


# --------------------------------------------------------------------------- #
#  Преобразования
# --------------------------------------------------------------------------- #

@op("translate", aliases=("сдвинуть", "переместить", "move", "сдвиг"), category="Массивы и преобразования",
    summary="Сдвигает объект на вектор.",
    example='шкив = cylinder radius=30 height=14\nдеталь = translate [шкив] offset=[0,0,20]',
    params={"objects": "объект", "offset": "вектор [dx,dy,dz] или число",
            "x": "сдвиг по X", "y": "сдвиг по Y", "z": "сдвиг по Z"},
    positional=["objects"])
def translate(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("translate работает с одним объектом.")
    base = solids[0]
    if a.has("offset"):
        off = a.vec("offset", 3, default=(0, 0, 0))
    else:
        off = [a.num("x", 0.0) or 0.0, a.num("y", 0.0) or 0.0, a.num("z", 0.0) or 0.0]
    if abs(off[0]) + abs(off[1]) + abs(off[2]) < 1e-9:
        return _derived(a, name, base.manifold, base, "translate")
    result = translate_manifold(base.manifold, off)
    _parts_follow(a, base, lambda m: translate_manifold(m, off))
    return _derived(a, name, result, base, "translate")


@op("rotate", aliases=("повернуть", "вращать", "поворот"), category="Массивы и преобразования",
    summary="Поворачивает объект вокруг оси (по умолчанию Z) на угол в градусах.",
    example='деталь = box size=[60,20,20]\nдеталь = rotate [деталь] angle=90 axis=z',
    params={"objects": "объект", "angle": "угол, градусы",
            "axis": "x, y, z или вектор [x,y,z]",
            "pivot": "точка, вокруг которой вращать"},
    positional=["objects"])
def rotate(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("rotate работает с одним объектом.")
    base = solids[0]
    angle = a.num("angle", required=True)
    axis_raw = a.text("axis", "z")
    if axis_raw in ("x", "y", "z"):
        axis = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis_raw]
    else:
        axis = a.vec("axis", 3, default=(0, 0, 1))
    pivot = a.vec("pivot", 3, default=(0, 0, 0))
    turned = rotate_manifold(base.manifold, float(angle), axis, pivot)
    axes_before = orient.axes_of(base)
    rotation = orient.rotate_axes(np.eye(3), float(angle), axis)
    _parts_follow(a, base,
                  lambda m: rotate_manifold(m, float(angle), axis, pivot),
                  rotation=rotation)
    made = _derived(a, name, turned, base, "rotate")
    # памятка «где теперь верх» поворачивается вместе с деталью
    orient.set_axes(made, rotation @ axes_before)
    return made


@op("scale", aliases=("масштабировать", "увеличить", "size"), category="Массивы и преобразования",
    summary="Масштабирует объект: равномерно (factor=2) или по осям (factor=[1,2,1]).",
    example='деталь = box size=[20,20,40]\nдеталь = scale [деталь] factor=[1,1,1.5]',
    params={"objects": "объект", "factor": "число или [sx,sy,sz]",
            "pivot": "точка отсчёта масштаба"},
    positional=["objects"])
def scale(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("scale работает с одним объектом.")
    base = solids[0]
    factor = a.vec("factor", 3, required=True)
    if any(f <= 0 for f in factor):
        raise GeometryError("Масштаб должен быть больше нуля.")
    pivot = a.vec("pivot", 3, default=(0, 0, 0))
    scaled = scale_manifold(base.manifold, factor, pivot)
    _parts_follow(a, base, lambda m: scale_manifold(m, factor, pivot))
    return _derived(a, name, scaled, base, "scale")


@op("place", aliases=("поставить", "позиционировать", "align"), category="Массивы и преобразования",
    summary="Ставит деталь к другой: сверху, снизу, слева, справа, спереди, сзади "
            "или по центру. Зазор отсчитывается от крайней границы хозяина, а не "
            "от его центра. Осями=хозяина — ставит по собственным осям хозяина: "
            "если хозяин повёрнут, «верх» едет вместе с ним, и деталь тоже "
            "разворачивается по этим осям. face=низ/верх/перед/зад/лево/право "
            "выбирает СВОЮ контактную сторону: деталь сама разворачивается ей "
            "к локальной стороне side хозяина, затем устанавливается с точным "
            "зазором от крайних точек объёма.",
    example="крышка = plate diameter=90 depth=10\n"
            "кружка = cylinder radius=40 height=95\n"
            "крышка = place [крышка] on=кружка side=top offset=2\n"
            "панель = box size=[50,4,30]\n"
            "панель = place [панель] on=кружка side=front face=front gap=1\n"
            "# слева от ящика, на расстоянии одной его длины, по осям ящика:\n"
            "ящик = box size=[80,50,30]\n"
            "ручка = cylinder radius=5 height=40\n"
            "ручка = place [ручка] on=ящик side=left offset=length(ящик) осями=хозяина",
    params={"objects": "деталь",
            "at": "точка [x,y,z] (режим без on)",
            "align": "bottom (по умолчанию), center или top; в режиме осями=хозяина — "
                     "разворачивать ли деталь по осям хозяина (да)",
            "center_xy": "центрировать по X и Y (да)",
            "on": "к какому объекту приставить (имя)",
            "side": "top/сверху, bottom/снизу, left/слева, right/справа, "
                    "front/спереди, back/сзади, center/по центру; с face= это "
                    "локальная сторона хозяина",
            "face": "своя контактная сторона: top/верх, bottom/низ, left/лево, "
                    "right/право, front/перёд, back/зад; автоматически разворачивает "
                    "деталь этой стороной к хозяину",
            "own_side": "то же, что face",
            "своей": "то же, что face (например: своей=низ)",
            "стороной": "то же, что face (например: стороной=перёд)",
            "offset": "зазор от крайней границы хозяина, мм (0); можно меркой — "
                      "offset=length(хозяин)",
            "gap": "то же, что offset (удобная запись)",
            "центр": "габарит (по умолчанию) или масса — какой центр считать "
                     "центром хозяина и детали",
            "осями": "мир (по умолчанию) или хозяина — чьи оси считать верхом "
                     "и левом",
            "axes": "то же, что осями (мир или хозяина)",
            "sides": "то же, что side (синоним для «сторона»)",
            "center": "то же, что центр: габарит или масса"},
    positional=["objects"])
def place(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("place работает с одним объектом.")
    base = solids[0]
    if a.has("on"):
        host = a.scene.resolve(a.text("on") or "")
        side_raw = a.text("side") or a.text("sides") or "top"
        side = orient.side_key(side_raw)
        if side not in orient.SIDE_VECTORS:
            raise GeometryError(f"place: неизвестная сторона «{side_raw}».",
                                hint="Стороны: top/сверху, bottom/снизу, left/слева, "
                                     "right/справа, front/спереди, back/сзади, "
                                     "center/по центру.")
        gap = a.num("offset", None)
        if gap is None:
            gap = a.num("gap", 0.0)
        gap = float(gap or 0.0)
        mode = (a.text("center") or a.text("центр") or "габарит").strip().lower()
        by_mass = mode in ("масса", "mass", "центр_масс", "центр_массы", "масс")
        frame = (a.text("осями") or a.text("axes") or "мир").strip().lower()
        host_frame = frame in ("хозяина", "хозяин", "host", "детали", "деталь",
                               "своими", "своя", "свои")
        face_raw = (a.text("face") or a.text("own_side") or a.text("своей")
                    or a.text("стороной") or "").strip()
        face = orient.side_key(face_raw) if face_raw else None
        if face is not None:
            if face not in orient.SIDE_VECTORS or face == "center":
                raise GeometryError(f"place: неизвестная своя сторона «{face_raw}».",
                                    hint="face: верх, низ, лево, право, перёд или зад.")
            if side == "center":
                raise GeometryError("place: face задаёт контакт со стороной, "
                                    "поэтому side=center с ним не используется.")
            # Контактная посадка всегда говорит о ЛОКАЛЬНОЙ стороне хозяина.
            host_frame = True

        if not host_frame:
            hb = host.manifold.bounding_box()
            ob = base.manifold.bounding_box()
            if by_mass:
                hc = orient.mass_center(host.manifold)
                oc = orient.mass_center(base.manifold)
            else:
                hc = np.array([(hb[0] + hb[3]) / 2, (hb[1] + hb[4]) / 2,
                               (hb[2] + hb[5]) / 2])
                oc = np.array([(ob[0] + ob[3]) / 2, (ob[1] + ob[4]) / 2,
                               (ob[2] + ob[5]) / 2])
            os_ = [ob[3] - ob[0], ob[4] - ob[1], ob[5] - ob[2]]
            target = list(hc)
            if side == "top":
                target = [hc[0], hc[1], hb[5] + gap + os_[2] / 2]
            elif side == "bottom":
                target = [hc[0], hc[1], hb[2] - gap - os_[2] / 2]
            elif side == "right":
                target = [hb[3] + gap + os_[0] / 2, hc[1], hc[2]]
            elif side == "left":
                target = [hb[0] - gap - os_[0] / 2, hc[1], hc[2]]
            elif side == "back":
                target = [hc[0], hb[4] + gap + os_[1] / 2, hc[2]]
            elif side == "front":
                target = [hc[0], hb[1] - gap - os_[1] / 2, hc[2]]
            off = (target[0] - oc[0], target[1] - oc[1], target[2] - oc[2])
            a.scene.log("info", f"place: {base.name} → {orient.SIDE_RU.get(side, side)} "
                                f"от {host.name}, зазор {gap:g} мм", a.cmd.line)
            _parts_follow(a, base, lambda m: translate_manifold(m, off))
            return _derived(a, name, translate_manifold(base.manifold, off), base, "place")

        # ---- по осям хозяина: верх/лево — его собственные, с учётом поворота ----
        A = orient.axes_of(host)
        B = orient.axes_of(base)
        align = a.boolean("align", True)
        if face is not None:
            # Наружная нормаль своей контактной стороны смотрит ПРОТИВ
            # наружной нормали хозяина: две стороны обращены друг к другу.
            host_normal = A @ orient.SIDE_VECTORS[side]
            own_normal = B @ orient.SIDE_VECTORS[face]
            R = orient.rotation_between(own_normal, -host_normal)
        else:
            R = A @ B.T if align else np.eye(3)
        pb = base.manifold.bounding_box()
        pc = np.array([(pb[0] + pb[3]) / 2, (pb[1] + pb[4]) / 2, (pb[2] + pb[5]) / 2])
        mat = np.hstack([R, (pc - R @ pc).reshape(3, 1)])
        turned = base.manifold.transform(np.ascontiguousarray(mat, dtype=np.float64))

        shift = np.zeros(3)
        if side == "center":
            if by_mass:
                hc = orient.mass_center(host.manifold)
                cc = orient.mass_center(turned)
            else:
                hc = orient.bbox_center(host.manifold)
                cc = orient.bbox_center(turned)
            for k in range(3):
                u = A[:, k]
                shift += (float(hc @ u) - float(cc @ u)) * u
        else:
            local = orient.SIDE_VECTORS[side]
            k = int(np.argmax(np.abs(local)))
            sign = float(np.sign(local[k]))
            for axis_k in range(3):
                u = A[:, axis_k]
                hmin, hmax = orient.extent_along(host.manifold, u)
                pmin, pmax = orient.extent_along(turned, u)
                if axis_k == k:
                    # деталь целиком за границей хозяина: её ближняя к хозяину
                    # точка — на зазоре от его крайней точки вдоль этой оси
                    if sign > 0:
                        shift += (hmax + gap - pmin) * u
                    else:
                        shift += (hmin - gap - pmax) * u
                elif by_mass:
                    shift += (float(orient.mass_center(host.manifold) @ u)
                              - float(orient.mass_center(turned) @ u)) * u
                else:
                    shift += ((hmin + hmax) / 2 - (pmin + pmax) / 2) * u

        def _move(m):
            return translate_manifold(m.transform(np.ascontiguousarray(mat, dtype=np.float64)),
                                      shift)

        moved = translate_manifold(turned, shift)
        _parts_follow(a, base, _move, rotation=R)
        made = _derived(a, name, moved, base, "place")
        if face is not None:
            orient.set_axes(made, R @ B)
            made.meta["contact"] = {"host": host.name, "host_side": side,
                                    "own_side": face, "gap": gap}
        elif align:
            orient.set_axes(made, A)
        a.scene.log("info",
                    f"place: {base.name} → {orient.SIDE_RU.get(side, side)} от {host.name} "
                    f"по осям хозяина, зазор {gap:g} мм"
                    + (f"; к хозяину развёрнута своя сторона {face}" if face is not None
                       else "; деталь развёрнута по этим осям" if align else ""), a.cmd.line)
        return made

    at = a.vec("at", 3, default=(0, 0, 0))
    align = (a.text("align", "bottom", ["bottom", "center", "top"]) or "bottom").lower()
    bb = base.manifold.bounding_box()
    size = (bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
    center = (bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2
    center_xy = a.boolean("center_xy", True)
    tx = at[0] if center_xy else at[0] + size[0] / 2
    ty = at[1] if center_xy else at[1] + size[1] / 2
    if align == "bottom":
        target = (tx, ty, at[2] + size[2] / 2)
    elif align == "top":
        target = (tx, ty, at[2] - size[2] / 2)
    else:
        target = (tx, ty, at[2])
    off = (target[0] - center[0], target[1] - center[1], target[2] - center[2])
    _parts_follow(a, base, lambda m: translate_manifold(m, off))
    return _derived(a, name, translate_manifold(base.manifold, off), base, "place")


@op("mirror", aliases=("зеркало", "отразить", "симметрия"), category="Массивы и преобразования",
    summary="Отражает объект через плоскость. keep=true — оставляет и оригинал (симметричная сборка).",
    example='ножка = cylinder radius=8 height=70 at=[40,0,0]\nножки = mirror [ножка] plane=x',
    params={"objects": "объект", "plane": "x (по умолчанию), y или z",
            "at": "координата плоскости (0)", "keep": "оставить оригинал (true)"},
    positional=["objects"])
def mirror(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("mirror работает с одним объектом.")
    base = solids[0]
    plane = (a.text("plane", "x", ["x", "y", "z"]) or "x").lower()
    at = float(a.num("at", 0.0) or 0.0)
    keep = a.boolean("keep", True)
    reflected = mirror_manifold(base.manifold, plane, at)
    result = mf.Manifold.batch_boolean([base.manifold, reflected], mf.OpType.Add) if keep else reflected

    def _mirror_part(m):
        img = mirror_manifold(m, plane, at)
        return mf.Manifold.batch_boolean([m, img], mf.OpType.Add) if keep else img

    axes_before = orient.axes_of(base)
    reflection = orient.mirror_axes(np.eye(3), plane)
    _parts_follow(a, base, _mirror_part,
                  rotation=None if keep else reflection)
    made = _derived(a, name, result, base, "mirror")
    # при keep=да в детали и оригинал, и отражение — ориентация неоднозначна
    # и остаётся мировой; при keep=нет деталь действительно зеркальная
    mirrored_axes = reflection @ axes_before
    prefix = f"{base.name}."
    if keep:
        orient.set_axes(made, np.eye(3))
        for child in a.scene.objects.values():
            if child.name.startswith(prefix) and child.name != made.name:
                orient.set_axes(child, np.eye(3))
    else:
        orient.set_axes(made, mirrored_axes)
    return made


@op("refine", aliases=("уточнить", "подразбить", "subdivide", "полигонаж",
                       "детализация", "плотность", "polygon"),
    category="Форма и деформации",
    summary="Полигонаж: повышает плотность сетки. Нужен перед тонкой работой — "
            "вмятиной, складкой, сверлением: на крупной сетке край выходит "
            "гранёным, а после дробления инструмент ложится гладко. "
            "length — целевая длина ребра в мм, levels — готовые уровни "
            "подразбиения (1…4, каждый учетверяет число граней).",
    example="# крупная сетка — и после неё мелкая вмятина\n"
            "заготовка = sphere radius=30 segments=12\n"
            "заготовка = refine [заготовка] length=2\n"
            "заготовка = dent [заготовка] radius=14 depth=5",
    params={"objects": "объект", "length": "целевая длина ребра, мм (1.5)",
            "levels": "число уровней подразбиения 1…4"},
    positional=["objects"])
def refine(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("refine работает с одним объектом.",
                            hint="Формат: имя = refine [объект] length=2")
    base = solids[0]
    before = int(base.manifold.num_tri())
    if a.has("levels"):
        levels = a.int("levels", 1, minv=1, maxv=4)
        result = base.manifold.refine(int(levels))
    else:
        length = a.num("length", 1.5, minv=0.05)
        area = float(base.manifold.surface_area())
        est = area / max(float(length) ** 2 * 0.43, 1e-9)
        if est > 2_500_000:
            raise GeometryError(
                f"Полигонаж дал бы около {est / 1e6:.1f} млн граней — это "
                "тяжело даже для просмотра.",
                hint="Увеличьте length (длину ребра) или уменьшите деталь.",
                param="length", minv=0.05)
        result = base.manifold.refine_to_length(float(length))
    solid = _derived(a, name, result, base, "refine")
    after = int(solid.manifold.num_tri())
    solid.notes.append(f"сетка {before} → {after} трис")
    return solid


@op("simplify", aliases=("упростить", "облегчить", "optimize", "оптимизировать"),
    category="Форма и деформации",
    summary="Упрощает сетку, сохраняя форму: меньше треугольников при отклонении "
            "не больше tolerance. Отклонение меряется двусторонним расстоянием "
            "Хаусдорфа. Ровные участки теряют лишние грани.",
    example='деталь = sphere radius=30 segments=64\nдеталь = optimize [деталь] deviation=0.2',
    params={"objects": "объект", "tolerance": "шаг упрощения, мм (0.3)",
            "deviation": "допустимое отклонение от исходной формы, мм"},
    positional=["objects"])
def simplify(a, name):
    def _all(v) -> bool:
        return isinstance(v, str) and v.strip().lower() in ("all", "*", "все", "всё")

    asked = list(a.extra) + ([a.kwargs["objects"]] if "objects" in a.kwargs else [])
    if any(_all(v) for v in asked):
        solids = [s for s in a.scene.objects.values()]
    else:
        solids = a.solids()
    if not solids:
        raise GeometryError("simplify: нечего упрощать.")
    if len(solids) > 1:
        tol = float(a.num("tolerance", 0.15, minv=0.0) or 0.0)
        dev_param = a.num("deviation")
        if dev_param is not None:
            tol = min(tol, float(dev_param))
        before = sum(int(s.manifold.num_tri()) for s in solids)
        for solid in list(solids):
            try:
                result = solid.manifold.simplify(tol)
                if result.is_empty():
                    continue
                _derived(a, solid.name, result, solid, "simplify")
            except Exception as exc:
                a.scene.log("warn", f"simplify {solid.name}: {exc}", a.cmd.line)
        after = sum(int(s.manifold.num_tri()) for s in a.scene.objects.values())
        a.scene.log("info", f"оптимизация: {before} → {after} треугольников "
                            f"(допуск {tol:g} мм)", a.cmd.line)
        return None
    base = solids[0]
    tol = float(a.num("tolerance", 0.3, minv=0.0) or 0.0)
    dev_param = a.num("deviation")
    if dev_param is not None and tol <= 0:
        tol = max(0.05, float(dev_param))
    limit = float(dev_param) if dev_param is not None else tol
    result = base.manifold.simplify(tol)
    if result.is_empty():
        raise GeometryError("Не удалось упростить объект с таким допуском.")
    worst = 0.0
    if tol > 0 and limit > 0:
        # simplify не всегда укладывается в допуск — проверяем честным
        # двусторонним расстоянием Хаусдорфа и повторяем с меньшим шагом.
        from .cuts import hausdorff
        for factor in (1.0, 0.6, 0.35, 0.2):
            candidate = result if factor == 1.0 else base.manifold.simplify(tol * factor)
            if candidate.is_empty():
                break
            samples = 400 if candidate.num_tri() > 25_000 else 700
            measured = hausdorff(base.manifold, candidate, samples=samples)
            worst = measured["max"]
            result = candidate
            if worst <= limit:
                break
        a.scene.log("info",
                    f"simplify: {'допуск' if dev_param is None else 'отклонение'} "
                    f"{limit:g} мм, фактическое отклонение ≤ {worst:.3f} мм",
                    a.cmd.line)
    return _derived(a, name, result, base, "simplify")


# --------------------------------------------------------------------------- #
#  Деформации
# --------------------------------------------------------------------------- #

def _warp(a, base, fn, kind: str, name=None):
    # manifold3d.warp двигает только существующие вершины, поэтому без
    # предварительного разбиения изгиб/скрутка превращаются в «сдвиг» углов.
    # Дробим сетку (refine), чтобы кривая получилась настоящей.
    source = base.manifold
    try:
        refine = int(a.num("refine", 1, minv=0, maxv=6))
    except Exception:
        refine = 1
    if refine > 0:
        # Дробим по длине ребра, а не «в 4^n»: warp двигает только вершины,
        # поэтому крупные грани иначе остаются плоскими и изгиб выглядит гранёным.
        bb = source.bounding_box()
        diag = math.sqrt(sum((bb[i + 3] - bb[i]) ** 2 for i in range(3)))
        target_len = max(0.8, diag / 45.0)
        tris = int(source.num_tri())
        budget = 300000
        try:
            if tris * (diag / target_len) ** 2 > budget * 4:
                target_len = diag / math.sqrt(budget / max(tris, 1))
            source = source.refine_to_length(float(target_len))
        except Exception:
            source = base.manifold
    try:
        result = source.warp(fn)
    except Exception as exc:
        raise GeometryError(f"Деформация не удалась: {exc}") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После деформации объект исчез.")
    return _derived(a, name, result, base, kind)


@op("twist", aliases=("скрутить", "закрутить"), category="Форма и деформации",
    summary="Скручивает объект вокруг оси: угол растёт вдоль оси.",
    example='деталь = box size=[40,40,160] round=3\nдеталь = twist [деталь] angle=90 axis=z',
    params={"objects": "объект", "angle": "полный угол закрутки, градусы",
            "axis": "x, y или z", "pivot": "центр оси"},
    positional=["objects"])
def twist(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("twist работает с одним объектом.")
    base = solids[0]
    angle = float(a.num("angle", required=True))
    axis = (a.text("axis", "z", ["x", "y", "z"]) or "z").lower()
    pivot = a.vec("pivot", 3, default=(0, 0, 0))
    bb = base.manifold.bounding_box()
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    lo, hi = bb[idx], bb[idx + 3]
    span = max(hi - lo, 1e-9)
    ang = math.radians(angle)
    axis_vec = np.array([1.0 if axis == "x" else 0.0,
                         1.0 if axis == "y" else 0.0,
                         1.0 if axis == "z" else 0.0])
    pv = np.array(pivot, dtype=np.float64)

    def fn(p):
        t = (p[idx] - lo) / span
        teta = ang * t
        v = np.array([p[0], p[1], p[2]], dtype=np.float64) - pv
        c, s = math.cos(teta), math.sin(teta)
        x, y, z = v
        if axis == "z":
            v2 = np.array([x * c - y * s, x * s + y * c, z])
        elif axis == "x":
            v2 = np.array([x, y * c - z * s, y * s + z * c])
        else:
            v2 = np.array([x * c + z * s, y, -x * s + z * c])
        return [float(v2[0] + pv[0]), float(v2[1] + pv[1]), float(v2[2] + pv[2])]

    return _warp(a, base, fn, "twist", name)


@op("taper", aliases=("сузить", "конусность", "taper"), category="Форма и деформации",
    summary="Плавно сужает объект кверху (factor<1) или расширяет (factor>1).",
    example='деталь = cylinder radius=20 height=80 segments=48\nдеталь = taper [деталь] factor=0.6 axis=z',
    params={"objects": "объект", "factor": "масштаб на дальнем конце (0.6)",
            "axis": "x, y или z", "pivot": "центр по осям сечения"},
    positional=["objects"])
def taper(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("taper работает с одним объектом.")
    base = solids[0]
    factor = float(a.num("factor", 0.6, minv=0.01, maxv=100))
    axis = (a.text("axis", "z", ["x", "y", "z"]) or "z").lower()
    pivot = a.vec("pivot", 3, default=(0, 0, 0))
    bb = base.manifold.bounding_box()
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    lo, hi = bb[idx], bb[idx + 3]
    span = max(hi - lo, 1e-9)
    others = [i for i in range(3) if i != idx]

    def fn(p):
        t = (p[idx] - lo) / span
        s = 1.0 + (factor - 1.0) * t
        out = [float(p[0]), float(p[1]), float(p[2])]
        for i in others:
            out[i] = float(pivot[i] + (p[i] - pivot[i]) * s)
        return out

    return _warp(a, base, fn, "taper", name)


@op("bend", aliases=("согнуть", "изгиб", "дуга"), category="Форма и деформации",
    summary="Сгибает объект дугой. Ось Z изгибается в плоскости XZ.",
    example='прут = cylinder radius=6 height=160 segments=48\nпрут = bend [прут] angle=60',
    params={"objects": "объект", "angle": "угол изгиба, градусы", "pivot": "смещение центра"},
    positional=["objects"])
def bend(a, name):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError("bend работает с одним объектом.")
    base = solids[0]
    angle = float(a.num("angle", required=True))
    if abs(angle) > 350:
        raise GeometryError("Угол изгиба должен быть меньше 350 градусов.")
    bb = base.manifold.bounding_box()
    z0, z1 = bb[2], bb[5]
    length = max(z1 - z0, 1e-9)
    total = math.radians(angle)
    radius = length / total if abs(total) > 1e-9 else 1e12

    def fn(p):
        t = (p[2] - z0) / length
        teta = total * t
        r = radius + p[0]
        x = r * math.cos(teta) - radius
        z = r * math.sin(teta) + z0
        return [float(x), float(p[1]), float(z)]

    return _warp(a, base, fn, "bend", name)
