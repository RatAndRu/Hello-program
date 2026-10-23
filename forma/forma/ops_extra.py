"""Дополнительные инструменты: сглаживание, вырезы, выравнивание, срезы, канавки.

Эти команды появились после разбора моделей: не хватало безопасных способов
убрать «лесенки» на переходах, аккуратно вырезать окна и отверстия, выровнять
деталь и сделать канавки (например, на пробке бутылки).
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import make_solid, op

MAX_TRIS = 1_600_000


def _derived(a, name, manifold, base, kind: str):
    solid = make_solid(a.scene, name or base.name, manifold, a, base=base, kind=kind)
    a.scene.consume(base)
    return solid


def _one(a, command: str):
    solids = a.solids()
    if len(solids) != 1:
        raise GeometryError(f"{command} работает с одним объектом.",
                            hint=f"Формат: имя = {command} [объект] …")
    return solids[0]


# --------------------------------------------------------------------------- #
#  Сглаживание и округление переходов
# --------------------------------------------------------------------------- #

def _sharp_edge_count(manifold: mf.Manifold, angle_deg: float = 25.0) -> int:
    """Сколько рёбер имеет излом больше angle_deg.

    Нужно, чтобы не гонять дорогое скругление по гладкой поверхности
    (тор, сфера, лофт): там нет острых рёбер, и minkowski — чистая трата
    времени. Считаем по сетке: нормали треугольников + парные рёбра.
    """
    try:
        mesh = manifold.to_mesh()
        verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
        tris = np.asarray(mesh.tri_verts, dtype=np.int64)
    except Exception:
        return 1
    if len(tris) == 0:
        return 0
    p0 = verts[tris[:, 0]]
    n = np.cross(verts[tris[:, 1]] - p0, verts[tris[:, 2]] - p0)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=0)
    edges.sort(axis=1)
    face = np.tile(np.arange(len(tris)), 3)
    key = edges[:, 0].astype(np.int64) * (int(verts.shape[0]) + 1) + edges[:, 1]
    order = np.argsort(key, kind="stable")
    key, face = key[order], face[order]
    same = key[1:] == key[:-1]
    if not np.any(same):
        return 0
    i = np.where(same)[0]
    dots = np.einsum("ij,ij->i", n[face[i]], n[face[i + 1]])
    dots = np.clip(dots, -1.0, 1.0)
    angles = np.degrees(np.arccos(dots))
    return int(np.count_nonzero(angles > angle_deg))


_BALL_CACHE: dict[tuple[float, int], mf.Manifold] = {}


def _round_ball(radius: float, segments: int) -> mf.Manifold:
    key = (round(float(radius), 4), int(segments))
    ball = _BALL_CACHE.get(key)
    if ball is None:
        ball = mf.Manifold.sphere(float(radius), int(segments))
        if len(_BALL_CACHE) > 24:
            _BALL_CACHE.clear()
        _BALL_CACHE[key] = ball
    return ball


def _convex_chamfer(manifold: mf.Manifold, width: float, angle_deg: float = 25.0,
                    limit: int = 4000) -> tuple[mf.Manifold, int]:
    """Быстрая фаска: снимает каждую выпуклую кромку клином.

    Морфологическое скругление (minkowski) красиво, но на деталях с сотнями
    кромок — отверстия, зубья, рёбра — считается минутами и раздувает сетку.
    Здесь на каждую выпуклую кромку строится клин (сечение — треугольник
    между кромкой и двумя точками на гранях на расстоянии width) и всё
    вычитается одним пакетом. Время — доли секунды, форма — честная фаска.

    Выпуклость кромки определяется знаком смешанного произведения
    (n1 × n2) · e — это локальный и точный признак, в отличие от проверки
    «где лежит третья вершина», которая врёт на вытянутых треугольниках.
    """
    mesh = manifold.to_mesh()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    tris = np.asarray(mesh.tri_verts, dtype=np.int64)
    if len(tris) == 0:
        return manifold, 0
    p0s = verts[tris[:, 0]]
    normals = np.cross(verts[tris[:, 1]] - p0s, verts[tris[:, 2]] - p0s)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    edges = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=0)
    faces = np.tile(np.arange(len(tris)), 3)
    key = edges.min(axis=1) * (int(verts.shape[0]) + 1) + edges.max(axis=1)
    order = np.argsort(key, kind="stable")
    edges, faces, key = edges[order], faces[order], key[order]
    same = np.where(key[1:] == key[:-1])[0]
    if len(same) == 0:
        return manifold, 0
    cos_thr = math.cos(math.radians(angle_deg))
    width = float(width)
    wedges: list[mf.Manifold] = []
    for i in same:
        if len(wedges) >= limit:
            break
        f1, f2 = int(faces[i]), int(faces[i + 1])
        a, b = int(edges[i][0]), int(edges[i][1])
        n1, n2 = normals[f1], normals[f2]
        dot = float(np.clip(np.dot(n1, n2), -1.0, 1.0))
        if dot > cos_thr:
            continue  # грань почти плоская — кромки нет
        e = verts[b] - verts[a]
        length = float(np.linalg.norm(e))
        if length < 1e-9:
            continue
        e = e / length
        if float(np.dot(np.cross(n1, n2), e)) <= 0.0:
            continue  # вогнутая кромка — фаска её не трогает
        t1 = np.cross(n1, e)
        t1 /= max(float(np.linalg.norm(t1)), 1e-12)
        if float(t1 @ (-n2)) < 0.0:
            t1 = -t1
        t2 = np.cross(n2, e)
        t2 /= max(float(np.linalg.norm(t2)), 1e-12)
        if float(t2 @ (-n1)) < 0.0:
            t2 = -t2
        y = np.cross(e, t1)
        y /= max(float(np.linalg.norm(y)), 1e-12)
        if float(t2 @ y) < 0.0:
            y = -y
        u = float(t2 @ t1)
        v = float(t2 @ y)
        if width * abs(v) < 1e-9:
            continue
        # вершину клина выносим наружу на 5 % ширины: иначе грани клина
        # ложатся ровно на поверхность детали и булево оставляет «бахрому»
        out = max(0.02, width * 0.05)
        section = [(-out, -out), (width, 0.0), (width * u, width * v)]
        # клин выпускаем за концы кромки не дальше половины её длины:
        # на мелких кромках (кольцо отверстия) длинный выпуск рисует «звёзды»
        ext = min(width * 1.02, length * 0.5)
        start = verts[a] - e * ext
        matrix = [[t1[0], y[0], e[0], start[0]],
                  [t1[1], y[1], e[1], start[1]],
                  [t1[2], y[2], e[2], start[2]]]
        try:
            wedge = mf.Manifold.extrude(mf.CrossSection([section]),
                                        length + 2.0 * ext).transform(matrix)
        except Exception:
            continue
        if wedge.volume() > 1e-9:
            wedges.append(wedge)
    if not wedges:
        return manifold, 0
    try:
        result = mf.Manifold.batch_boolean([manifold] + wedges, mf.OpType.Subtract)
    except Exception:
        result = manifold
        cuts = 0
        for wedge in wedges:
            piece = result - wedge
            if piece.is_empty() or piece.volume() <= 1e-9:
                continue
            result = piece
            cuts += 1
        return result, cuts
    if result.is_empty() or result.volume() <= 1e-9:
        return manifold, 0
    # после пакетного вычитания много «лишних» кромок на разрезах —
    # стягиваем их в пределах 2 % ширины, форма не меняется
    try:
        simple = result.simplify(max(0.01, float(width) * 0.02))
        if not simple.is_empty() and simple.volume() > 0:
            result = simple
    except Exception:
        pass
    return result, len(wedges)


def _ball_segments(wanted: int, tris: int, sharp: int) -> int:
    """Качество скругления под размер сетки.

    Маленькая деталь получает полный segments, крупная — меньше шаров:
    minkowski стоит ~ tri·ball_tris, поэтому на 60 000 треугольников
    «24» превращаются в минуту ожидания. Ниже 8 не опускаемся — фаска
    перестаёт быть круглой.
    """
    if tris <= 12_000:
        return int(wanted)
    # масштаб по корню из отношения размеров: 4× треугольников → вдвое меньше
    scale = (12_000.0 / float(tris)) ** 0.5
    return max(8, min(int(wanted), int(round(wanted * scale))))

@op("smooth", aliases=("сгладить", "сглаживание", "плавно", "умягчить", "soften"),
    category="Форма и деформации",
    summary="Сглаживает переходы и убирает «лесенки» на гранях: G1-непрерывность "
            "и дополнительное дробление поверхности. Размер модели сохраняется.",
    example='кружка = box size=[40,40,40] round=2\nкружка = smooth [кружка] angle=50 soft=0.2 levels=1',
    params={"objects": "объект",
            "angle": "угол, выше которого ребро остаётся острым, ° (50)",
            "soft": "мягкость 0…1 (0.2 — безопасно; больше 0.4 деформирует)",
            "levels": "дробление поверхности 1…3 (1 — без дробления)"},
    positional=["objects"])
def smooth(a, name):
    base = _one(a, "smooth")
    angle = a.num("angle", 50.0, minv=0.0, maxv=180.0)
    soft = a.num("soft", 0.2, minv=0.0, maxv=1.0)
    levels = a.int("levels", 1, minv=1, maxv=3)
    tris = base.manifold.num_tri()
    if tris * (4 ** (levels - 1)) > MAX_TRIS:
        raise GeometryError(
            f"Сглаживание слишком тяжёлое: {tris:,} трис × 4^{levels - 1}.".replace(",", " "),
            hint="Уменьшите levels до 1 или сначала упростите объект (simplify).")
    if soft <= 1e-6 and levels <= 1:
        a.scene.log("info", "smooth: мягкость 0 и без дробления — менять нечего",
                    a.cmd.line)
        return _derived(a, name, base.manifold, base, "smooth")
    try:
        result = base.manifold.smooth_out(float(angle), float(soft))
        if levels > 1:
            result = result.refine(int(levels))
    except Exception as exc:
        raise GeometryError(f"Не удалось сгладить объект: {exc}") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После сглаживания объект исчез — уменьшите параметры.")
    result = _keep_envelope(a, base.manifold, result, "smooth")
    return _derived(a, name, result, base, "smooth")


def _keep_envelope(a, source, result, kind: str) -> mf.Manifold:
    """Возвращает габарит исходной детали (сглаживание любит «раздувать»)."""
    b0 = source.bounding_box()
    b1 = result.bounding_box()
    s0 = [b0[i + 3] - b0[i] for i in range(3)]
    s1 = [b1[i + 3] - b1[i] for i in range(3)]
    ratios = [s0[i] / s1[i] for i in range(3) if s1[i] > 1e-9 and s0[i] > 1e-9]
    if not ratios:
        return result
    k = sum(ratios) / len(ratios)
    k = min(max(k, 0.5), 2.0)
    if abs(k - 1.0) < 2e-3:
        return result
    center = [(b1[i] + b1[i + 3]) / 2.0 for i in range(3)]
    shifted = result.translate([-center[0], -center[1], -center[2]])
    out = shifted.scale([k, k, k]).translate([center[0], center[1], center[2]])
    a.scene.log("info", f"{kind}: габарит приведён к исходному (множитель {k:.3f})", a.cmd.line)
    return out


@op("bevel", aliases=("фаска", "скос", "округление", "кромка"), category="Форма и деформации",
    summary="Снимает наружные рёбра: на простых деталях — настоящим радиусом, на сложных "
            "(отверстия, зубья, сотни кромок) — фаской 45° клиньями. Размер детали "
            "не меняется, материал снимается только на кромках.",
    example='плита = box size=[60,40,20]\nплита = bevel [плита] radius=3',
    params={"objects": "объект",
            "radius": "радиус скругления или ширина фаски, мм (по умолчанию 4% тонкой стороны)",
            "segments": "качество скругления 8…64 (24)",
            "mode": "авто (простое — скругление, сложное — фаска 45°), "
                    "скругление, фаска",
            "soft": "устаревшее: доля от половины тонкой стороны (0…1)",
            "levels": "устаревшее: не используется"},
    positional=["objects"])
def bevel(a, name):
    base = _one(a, "bevel")
    bbox = base.manifold.bounding_box()
    thin = min(bbox[3] - bbox[0], bbox[4] - bbox[1], bbox[5] - bbox[2])
    soft = a.num("soft", None, minv=0.0, maxv=1.0)
    radius = a.num("radius", None, minv=0.01)
    if radius is None:
        radius = float(soft) * thin / 2.0 if soft else thin * 0.02
    radius = min(float(radius), thin * 0.45)
    seg = a.int("segments", 24, minv=8, maxv=64)
    tris = base.manifold.num_tri()
    if tris > 60000:
        raise GeometryError(
            "Слишком подробная сетка для фаски — это надолго.",
            hint="Сначала упростите объект: имя = simplify [объект] tolerance=0.2. "
                 "Для плавных тел лучше smooth.")
    # На гладком теле (сфера, тор, лофт) острых рёбер нет — скруглять нечего.
    sharp = _sharp_edge_count(base.manifold, 25.0)
    mode = (a.text("mode") or "авто").strip().lower()
    if mode in ("avto", "auto", "авто", ""):
        mode = "авто"
    if mode in ("фаска", "chamfer", "плоская", "45"):
        mode = "фаска"
    elif mode in ("скругление", "round", "круглое", "radius"):
        mode = "скругление"
    elif mode != "авто":
        raise GeometryError("Параметр mode: авто, скругление или фаска.")
    if sharp == 0:
        a.scene.log("info", "bevel: острых рёбер нет — тело гладкое, фаска не нужна",
                    a.cmd.line)
        return _derived(a, name, base.manifold, base, "bevel")
    # Морфологическое скругление честное, но дорогое: на деталях с сотнями
    # кромок (отверстия, зубья, стенки) — минуты и сотни тысяч треугольников.
    # Простым деталям — настоящее скругление, сложным — фаска 45° клиньями.
    simple = sharp <= 24 and tris <= 2000
    if mode == "авто":
        mode = "скругление" if simple else "фаска"
    if mode == "скругление" and tris * sharp > 40000:
        raise GeometryError(
            f"Скругление radius={radius:g} на такой сетке ({tris} трис, {sharp} кромок) "
            f"считалось бы минутами.",
            hint="Добавьте mode=фаска — та же кромка снимается плоскостью за доли "
                 "секунды, или упростите деталь: имя = simplify [объект] tolerance=0.2.")
    if mode == "фаска":
        result, cuts = _convex_chamfer(base.manifold, float(radius), 25.0)
        if cuts == 0:
            raise GeometryError("Не нашлось выпуклых кромок для фаски.")
        a.scene.log("info", f"bevel: фаска 45° {radius:g} мм по {cuts} кромкам "
                            f"(сетка {tris} трис, быстро)", a.cmd.line)
        return _derived(a, name, result, base, "bevel")
    seg = _ball_segments(seg, tris, sharp)
    try:
        ball = _round_ball(float(radius), int(seg))
        # «раскрытие»: сжатие на радиус и обратный рост — скругляет выпуклые
        # рёбра, не раздувая деталь (в отличие от простого сглаживания).
        result = base.manifold.minkowski_difference(ball).minkowski_sum(ball)
    except Exception as exc:
        raise GeometryError(f"Не удалось сделать фаску: {exc}") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После фаски объект исчез — уменьшите radius.")
    b1 = result.bounding_box()
    v0, v1 = float(base.manifold.volume()), float(result.volume())
    shrink = max((bbox[i + 3] - bbox[i]) - (b1[i + 3] - b1[i]) for i in range(3))
    if v1 < v0 * 0.85 or shrink > max(1.0, thin * 0.08):
        raise GeometryError(
            f"Фаска radius={radius:g} мм слишком велика для этой детали: "
            f"объём уменьшился на {(1 - v1 / v0) * 100:.0f} %, "
            f"габарит — на {shrink:.1f} мм.",
            hint="Уменьшите radius (например, в 2 раза) или примените smooth — "
                 "он не снимает материал. У тонкостенных деталей фаска «съедает» стенку.")
    grew = max(abs((b1[i + 3] - b1[i]) - (bbox[i + 3] - bbox[i])) for i in range(3))
    delta = (result.volume() - base.manifold.volume()) / base.manifold.volume() * 100.0
    a.scene.log("info",
                f"bevel: радиус {radius:.2f} мм, объём {delta:+.2f} %, "
                f"габарит {grew:+.3f} мм", a.cmd.line)
    return _derived(a, name, result, base, "bevel")


@op("clean", aliases=("почистить", "убрать_мусор", "remove_degenerate", "ремонт"),
    category="Форма и деформации",
    summary="Сваривает совпавшие вершины, убирает вырожденные и дублирующиеся "
            "треугольники. Полезно после импорта и сложных булевых операций.",
    example='деталь = sphere radius=30 segments=32\nдеталь = clean [деталь]',
    params={"objects": "объект", "tolerance": "допуск сварки вершин, мм (0.01)"},
    positional=["objects"])
def clean(a, name):
    from .geometry import manifold_from_arrays, manifold_mesh
    base = _one(a, "clean")
    tol = float(a.num("tolerance", 0.01, minv=0.0) or 0.01)
    try:
        import trimesh
        verts, faces = manifold_mesh(base.manifold)
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
        result = manifold_from_arrays(np.asarray(mesh.vertices), np.asarray(mesh.faces),
                                      what="чистка")
    except Exception as exc:
        raise GeometryError(f"Не удалось почистить сетку: {exc}") from exc
    a.scene.log("info", f"clean: {base.manifold.num_tri()} → {result.num_tri()} треугольников",
                a.cmd.line)
    return _derived(a, name, result, base, "clean")


# --------------------------------------------------------------------------- #
#  Вырезы готовыми формами
# --------------------------------------------------------------------------- #

def _cutter(a, at) -> mf.Manifold:
    shape = (a.text("shape", "sphere") or "sphere").strip().lower()
    shape = {"шар": "sphere", "сфера": "sphere", "блок": "box", "куб": "box",
             "цилиндр": "cylinder", "конус": "cone", "кольцо": "ring"}.get(shape, shape)
    seg = a.int("segments", 48, minv=6, maxv=256)
    if shape == "sphere":
        r = a.num("radius", required=True, minv=0.05)
        m = mf.Manifold.sphere(float(r), int(seg))
    elif shape == "box":
        size = a.vec("size", 3, default=None)
        if size is None:
            r = a.num("radius", 10.0, minv=0.1)
            size = [r * 2, r * 2, r * 2]
        m = mf.Manifold.cube([float(v) for v in size], True)
        r = a.num("round", 0.0, minv=0.0)
        if r > 1e-6:
            if min(size) <= 2 * r:
                raise GeometryError(f"Скругление {r:g} мм слишком велико для выреза {size}.")
            inner = [float(v) - 2 * r for v in size]
            m = mf.Manifold.cube(inner, True).minkowski_sum(mf.Manifold.sphere(float(r), 24))
    elif shape == "cylinder":
        r = a.num("radius", required=True, minv=0.05)
        r2 = a.num("r2", float(r), minv=0.0)
        h = a.num("height", a.num("depth", 40.0), minv=0.1)
        m = mf.Manifold.cylinder(float(h), float(r), float(r2), int(seg), True)
    elif shape == "cone":
        r = a.num("radius", required=True, minv=0.05)
        h = a.num("height", a.num("depth", 40.0), minv=0.1)
        m = mf.Manifold.cylinder(float(h), float(r), 0.0, int(seg), True)
    elif shape == "ring":
        r = a.num("radius", required=True, minv=0.1)
        width = a.num("width", 3.0, minv=0.05)
        h = a.num("height", a.num("depth", 10.0), minv=0.1)
        outer = mf.Manifold.cylinder(float(h), float(r) + width / 2, float(r) + width / 2, int(seg), True)
        inner = mf.Manifold.cylinder(float(h) * 1.5, max(0.01, float(r) - width / 2),
                                     max(0.01, float(r) - width / 2), int(seg), True)
        m = outer - inner
    else:
        raise GeometryError(f"Неизвестная форма выреза «{shape}».",
                            hint="shape=sphere | box | cylinder | cone | ring")
    return m.translate([float(v) for v in at])


@op("cut", aliases=("вырезать", "вырез", "отверстие", "прокол", "выемка"),
    category="Булевы операции",
    summary="Вырезает готовую форму из объекта одной командой: сфера, блок, "
            "цилиндр, конус или кольцо в точке at.",
    example='кружка = cylinder radius=40 height=95\nкружка = cut [кружка] shape=box size=[30,30,60] at=[0,0,80]',
    params={"objects": "объект", "shape": "sphere|box|cylinder|cone|ring (sphere)",
            "at": "центр выреза [x,y,z] (0,0,0)", "radius": "радиус, мм",
            "size": "размер блока [x,y,z]", "height": "высота цилиндра/конуса, мм",
            "round": "скругление блока, мм", "segments": "гладкость (48)"},
    positional=["objects"])
def cut(a, name):
    base = _one(a, "cut")
    at = a.vec("at", 3, default=(0, 0, 0))
    cutter = _cutter(a, at)
    try:
        result = base.manifold - cutter
    except Exception as exc:
        raise GeometryError(f"Не удалось вырезать: {exc}") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("После выреза ничего не осталось.",
                            hint="Вырез перекрыл весь объект — уменьшите размер или сдвиньте at.")
    return _derived(a, name, result, base, "cut")


@op("groove", aliases=("канавка", "борозда", "насечка", "рифление"), category="Форма и деформации",
    summary="Прорезает кольцевую канавку вокруг вертикальной оси — как на пробке "
            "или крышке. Можно задать несколько канавок.",
    example='пробка = cylinder radius=18 height=40 segments=64\nпробка = groove [пробка] at=[0,0,20] radius=14 depth=1.2 height=2 count=3',
    params={"objects": "объект", "at": "центр первой канавки [x,y,z]",
            "radius": "радиус канавки, мм (обязательно)", "depth": "глубина, мм (1.2)",
            "height": "высота канавки, мм (2)", "count": "сколько канавок (1)",
            "step": "расстояние между канавками по Z, мм", "segments": "гладкость (64)"},
    positional=["objects"])
def groove(a, name):
    base = _one(a, "groove")
    at = a.vec("at", 3, default=(0, 0, 0))
    radius = a.num("radius", required=True, minv=0.2)
    depth = a.num("depth", 1.2, minv=0.05)
    height = a.num("height", 2.0, minv=0.05)
    count = a.int("count", 1, minv=1, maxv=40)
    step = a.num("step", height * 2, minv=0.01)
    seg = a.int("segments", 64, minv=8, maxv=256)
    result = base.manifold
    for i in range(count):
        z = float(at[2]) + i * float(step)
        outer = mf.Manifold.cylinder(float(height), float(radius) + float(depth) + 0.6,
                                     float(radius) + float(depth) + 0.6, int(seg), True)
        inner = mf.Manifold.cylinder(float(height) * 1.2, float(radius),
                                     float(radius), int(seg), True)
        ring = (outer - inner).translate([float(at[0]), float(at[1]), z])
        result = result - ring
    if result.is_empty():
        raise GeometryError("Канавка срезала объект целиком — уменьшите глубину.")
    return _derived(a, name, result, base, "groove")


# --------------------------------------------------------------------------- #
#  Выравнивание и срезы
# --------------------------------------------------------------------------- #

@op("align", aliases=("выровнять", "прижать", "поставить", "выравнивание"),
    category="Массивы и преобразования",
    summary="Выравнивает объект по осям: min|center|max или точное число. "
            "Например, align деталь z=min поставит её на пол.",
    example='деталь = box size=[40,40,40] at=[30,30,30]\nдеталь = align [деталь] x=center y=center z=min',
    params={"objects": "объект", "x": "min|center|max|число",
            "y": "min|center|max|число", "z": "min|center|max|число"},
    positional=["objects"])
def align(a, name):
    base = _one(a, "align")
    bb = base.manifold.bounding_box()
    lo = np.array(bb[:3], dtype=np.float64)
    hi = np.array(bb[3:], dtype=np.float64)
    offset = np.zeros(3)
    modes = {}
    for i, axis in enumerate("xyz"):
        raw = a.text(axis)
        if raw is None:
            continue
        val = raw.strip().lower()
        if val in ("min", "мин", "низ", "начало"):
            offset[i] = -lo[i]
        elif val in ("max", "макс", "верх", "конец"):
            offset[i] = -hi[i]
        elif val in ("center", "центр", "середина"):
            offset[i] = -(lo[i] + hi[i]) / 2
        else:
            try:
                offset[i] = float(val) - lo[i]
            except ValueError as exc:
                raise GeometryError(f"align {axis}={raw}: нужно min, center, max или число.") from exc
        modes[axis] = val
    if not modes:
        raise GeometryError("Укажите хотя бы одну ось: align деталь z=min.")
    result = base.manifold.translate([float(v) for v in offset])
    return _derived(a, name, result, base, "align")


@op("slice", aliases=("срез", "разрезать", "отрезать", "обрезать"), category="Булевы операции",
    summary="Отрезает объект плоскостью по X/Y/Z: keep=top|bottom|left|right|front|back.",
    example='корпус = box size=[60,60,80]\nкорпус = slice [корпус] axis=z at=0 keep=top',
    params={"objects": "объект", "axis": "x|y|z (z)", "at": "координата плоскости, мм (0)",
            "keep": "top|bottom (top)", "size": "размер режущего блока, мм (10000)"},
    positional=["objects"])
def slice(a, name):
    base = _one(a, "slice")
    axis = (a.text("axis", "z") or "z").lower()
    if axis not in ("x", "y", "z"):
        raise GeometryError("axis должен быть x, y или z.")
    at = a.num("at", 0.0)
    keep = (a.text("keep", "top") or "top").lower()
    size = a.num("size", 10000.0, minv=10.0)
    positive = keep in ("top", "верх", "right", "справа", "back", "сзади", "max")
    idx = "xyz".index(axis)
    vec = [0.0, 0.0, 0.0]
    vec[idx] = float(at) + (size / 2 if positive else -size / 2)
    block = mf.Manifold.cube([size, size, size], True).translate(vec)
    result = mf.Manifold.batch_boolean([base.manifold, block], mf.OpType.Intersect)
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("Срез не оставил ничего.",
                            hint="Проверьте at и keep — плоскость может быть вне модели.")
    return _derived(a, name, result, base, "slice")


@op("mirror_copy", aliases=("отразить_копию", "симметрия"), category="Массивы и преобразования",
    summary="Оставляет объект и добавляет его отражённую копию — удобно для парных деталей.",
    example='ручка = box size=[20,10,80] at=[40,0,0]\nручки = mirror_copy [ручка] plane=x',
    params={"objects": "объект", "plane": "x|y|z (x)", "gap": "зазор между половинами, мм (0)"},
    positional=["objects"])
def mirror_copy(a, name):
    base = _one(a, "mirror_copy")
    plane = (a.text("plane", "x") or "x").lower()
    if plane not in ("x", "y", "z"):
        raise GeometryError("plane должен быть x, y или z.")
    gap = a.num("gap", 0.0, minv=0.0)
    idx = "xyz".index(plane)
    shift = [0.0, 0.0, 0.0]
    if gap > 0:
        bb = base.manifold.bounding_box()
        shift[idx] = gap / 2 - bb[idx]
    source = base.manifold.translate(shift)
    mirrored = source.mirror([1.0 if i == idx else 0.0 for i in range(3)])
    result = source + mirrored
    return _derived(a, name, result, base, "mirror_copy")
