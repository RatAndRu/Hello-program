"""Скульпт: плотность сетки, вмятины, выдувание, щипок, стёсывание, сверление.

Зачем отдельный модуль: до 0.32 форма менялась либо целиком (масштаб, изгиб,
сужатель), либо булевыми вырезами. Не хватало инструментов «как руками»:

* **dent** — вмятина от удара: поверхность проминается внутрь с плавным краем;
* **blow** — выдувание объёма изнутри, как у стеклодува;
* **pinch** — щипок: сдавливаем с двух сторон, материал выдавливается наружу;
* **flatten** — разравнивание: участок подтягивается к плоскости;
* **polish** — разглаживание: убирает шероховатость, но не делает плоскостью;
* **shave** — стёсывание: срезаем слой фасеткой под любым углом;
* **point** — заострить: снимаем конус, как точилка с карандаша;
* **drill** — сверление с формой дна: плоско, конусом, сферой или ступенью.

Важная общая часть — **дробление под размер инструмента**: `warp` двигает
только существующие вершины, поэтому мелкая вмятина на крупной сетке
превращается в «гранёную ямку». Перед деформацией сетка дробится так, чтобы
на радиус инструмента приходилось несколько рёбер, а число треугольников
остаётся в разумных пределах.

Мягкость задаётся **параметром инструмента** (`soft=0…1`), а не свойством
предмета: в текстовом сценарии видно, чем и как сделана вмятина, а один и тот
же объект можно обработать по-разному в разных местах.
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .ops import make_solid, op

# Потолок треугольников после дробления: дальше скульпт становится вязким,
# а на глаз разница уже не видна.
WARP_BUDGET = 420_000


# --------------------------------------------------------------------------- #
#  Общие помощники
# --------------------------------------------------------------------------- #
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


def _unit(v) -> np.ndarray:
    arr = np.asarray(v, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(arr))
    if n < 1e-9:
        return np.array([0.0, 0.0, 1.0])
    return arr / n


def _center(bb) -> np.ndarray:
    return np.array([(bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0,
                     (bb[2] + bb[5]) / 2.0])


def _diag(bb) -> float:
    return float(math.sqrt(sum((bb[i + 3] - bb[i]) ** 2 for i in range(3))))


def _dir_of(a, at: np.ndarray, center: np.ndarray) -> np.ndarray:
    """Направление удара: явное `dir` или наружу от центра тела к точке."""
    given = a.vec("dir", 3, default=None)
    if given is not None:
        return _unit(given)
    return _unit(at - center)


def _frame(dirv, origin) -> np.ndarray:
    """Матрица 3×4: локальная ось Z смотрит вдоль dirv, начало — в origin."""
    z = _unit(dirv)
    helper = np.array([0.0, 0.0, 1.0]) if abs(z[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    x = _unit(np.cross(helper, z))
    y = np.cross(z, x)
    m = np.eye(3, 4)
    m[:, 0], m[:, 1], m[:, 2] = x, y, z
    m[:, 3] = np.asarray(origin, dtype=np.float64)
    return m


def _surface_refine(m: mf.Manifold, radius: float, detail: int) -> mf.Manifold:
    """Дробит сетку под размер инструмента (иначе вмятина выйдет гранёной)."""
    detail = max(1, min(int(detail), 24))
    # detail — сколько рёбер уложить по диаметру пятна
    target = max(0.35, 2.0 * float(radius) / detail)
    area = float(m.surface_area())
    tris = int(m.num_tri())
    # после дробления площадь треугольника ≈ target² / 2
    est = area / max(target * target * 0.43, 1e-9)
    if est > WARP_BUDGET:
        target *= math.sqrt(est / WARP_BUDGET)
        est = WARP_BUDGET
    if est <= max(tris * 1.06, tris + 24):
        return m
    try:
        fine = m.refine_to_length(float(target))
    except Exception:
        return m
    return _relax_triangles(fine)


def _relax_triangles(m: mf.Manifold, iters: int = 4, weight: float = 0.6) -> mf.Manifold:
    """Выравнивает треугольники, не меняя форму.

    `refine_to_length` дробит только длинные рёбра: на скруглённом теле рядом
    оказываются крупные и совсем мелкие треугольники. После деформации такие
    «иголки» вылезают гребешками по краю вмятины. Здесь вершины сдвигаются
    вдоль поверхности (тангенциально) к середине соседей — треугольники
    становятся ровнее, а форма остаётся прежней.

    Вершины на острых рёбрах (куда сходятся грани под большим углом) не
    трогаем: иначе скруглились бы углы детали.
    """
    v, t = _mesh_of(m)
    if len(t) == 0:
        return m
    fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    acc = np.empty_like(v)
    for k in range(3):
        acc[:, k] = np.bincount(t.ravel(), weights=np.repeat(fn[:, k], 3),
                                minlength=len(v))
    norm = np.linalg.norm(acc, axis=1)
    area = np.bincount(t.ravel(), weights=np.repeat(np.linalg.norm(fn, axis=1) / 2.0, 3),
                       minlength=len(v))
    # |Σ 2A·n| / (2·ΣA): у вершины на плоскости равно 1, на ребре куба 0.71,
    # в углу 0.58 — так и отличаем гладкие места от жёстких рёбер
    flat = norm / np.maximum(2.0 * area, 1e-12)
    mask = np.clip((flat - 0.78) / 0.12, 0.0, 1.0)
    n = acc / np.maximum(norm, 1e-12)[:, None]

    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    deg = np.bincount(e[:, 0], minlength=len(v)).astype(np.float64)
    deg[deg == 0] = 1.0
    for _ in range(max(0, int(iters))):
        accv = np.empty_like(v)
        for k in range(3):
            accv[:, k] = np.bincount(e[:, 0], weights=v[e[:, 1], k], minlength=len(v))
        d = accv / deg[:, None] - v
        d -= np.sum(d * n, axis=1)[:, None] * n
        v = v + (weight * mask)[:, None] * d
    try:
        out = mf.Manifold(mf.Mesh(vert_properties=v.astype(np.float32),
                                  tri_verts=t.astype(np.uint32)))
    except Exception:
        return m
    # Страховка: если выравнивание всё же вылезло за габарит (это была бы
    # вспухшая кромка), оставляем исходную сетку.
    a, b2 = m.bounding_box(), out.bounding_box()
    if any(b2[i] < a[i] - 0.02 or b2[i + 3] > a[i + 3] + 0.02 for i in range(3)):
        return m
    return out


def _falloff(q, soft: float):
    """Профиль вмятины: 0 — жёсткий «штамп», 1 — мягкий «палец»."""
    q = np.clip(np.asarray(q, dtype=np.float64), 0.0, 1.0)
    soft = max(0.0, min(1.0, float(soft)))
    return (1.0 - q * q) ** (0.45 + 1.55 * soft)


def _mesh_of(m: mf.Manifold) -> tuple[np.ndarray, np.ndarray]:
    mesh = m.to_mesh()
    v = np.array(mesh.vert_properties, dtype=np.float64)[:, :3]
    t = np.array(mesh.tri_verts, dtype=np.uint32).reshape(-1, 3)
    return v, t


def _vertex_normals(v: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Нормали вершин: сумма нормалей треугольников с весом площади.

    Нужны выдуванию: объём растёт вдоль поверхности, а не от одной точки,
    поэтому шар надувается шаром, а цилиндр — бочкой.
    """
    fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    acc = np.empty_like(v)
    for k in range(3):
        acc[:, k] = np.bincount(t.ravel(), weights=np.repeat(fn[:, k], 3),
                                minlength=len(v))
    length = np.linalg.norm(acc, axis=1)
    length[length < 1e-12] = 1.0
    return acc / length[:, None]


def _manifold_of(v: np.ndarray, t: np.ndarray, what: str) -> mf.Manifold:
    try:
        out = mf.Manifold(mf.Mesh(v.astype(np.float32), t.astype(np.uint32)))
    except Exception as exc:
        raise GeometryError(f"{what}: не удалось перестроить поверхность — {exc}") from exc
    if out.is_empty() or out.volume() <= 1e-9:
        raise GeometryError(f"{what}: от объекта ничего не осталось — уменьшите силу.")
    return out


def _laplacian(v: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Вектор Лапласа: среднее соседей минус сама вершина."""
    e = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]], axis=0)
    e = np.concatenate([e, e[:, ::-1]], axis=0)
    n = len(v)
    acc = np.empty_like(v)
    for k in range(3):
        acc[:, k] = np.bincount(e[:, 0], weights=v[e[:, 1], k], minlength=n)
    cnt = np.bincount(e[:, 0], minlength=n).astype(np.float64)
    cnt[cnt == 0] = 1.0
    return acc / cnt[:, None] - v


def _smooth_vertices(v: np.ndarray, t: np.ndarray, passes: int, strength: float,
                     weight: np.ndarray | None = None) -> np.ndarray:
    """Сглаживание Таубина: убирает мелкую шероховатость, форму бережёт.

    Пара шагов на проход: λ подтягивает вершину к среднему соседей, μ с
    обратным знаком возвращает объём. Обычный Лаплас «съедает» деталь —
    шар за восемь проходов теряет 5% радиуса и покрывается рябью у полюсов;
    пара λ/μ держит размер в пределах десятых долей процента.
    """
    lam = 0.72 * max(0.0, min(1.0, float(strength)))
    mu = -0.76 * max(0.0, min(1.0, float(strength)))
    w = np.ones(len(v)) if weight is None else np.clip(weight, 0.0, 1.0)
    out = v.copy()
    for _ in range(max(0, int(passes))):
        out += (lam * w)[:, None] * _laplacian(out, t)
        out += (mu * w)[:, None] * _laplacian(out, t)
    return out


def _warp(base, fn, a, name, kind: str, radius: float, detail: int, prepared=None):
    source = prepared if prepared is not None else _surface_refine(base.manifold, radius, detail)
    before = int(source.num_tri())
    try:
        result = source.warp_batch(fn)
    except GeometryError:
        raise
    except Exception as exc:
        raise GeometryError(f"{kind}: деформация не удалась — {exc}") from exc
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError(f"{kind}: объект исчез, уменьшите глубину или силу.")
    solid = _derived(a, name, result, base, kind)
    solid.notes.append(f"сетка {before} трис")
    return solid


def _preserve_volume(m: mf.Manifold, target: float, center: np.ndarray) -> tuple[mf.Manifold, float]:
    """Подгоняет объём однородным масштабом вокруг точки.

    Щипок сжимает середину, но гребни остаются — наивная деформация добавляет
    объём (у шара до +30%). Настоящий щипок объём сохраняет, поэтому после
    деформации масштабируем тело так, чтобы объём вернулся к исходному.
    """
    try:
        got = float(m.volume())
    except Exception:
        return m, 1.0
    if target <= 1e-9 or got <= 1e-9:
        return m, 1.0
    factor = (target / got) ** (1.0 / 3.0)
    if abs(factor - 1.0) < 0.005:
        return m, 1.0
    c = np.asarray(center, dtype=np.float64)
    out = m.translate((-c[0], -c[1], -c[2]))
    out = out.scale((factor, factor, factor))
    out = out.translate((c[0], c[1], c[2]))
    return out, factor


def _region_mask(points: np.ndarray, at: np.ndarray, radius: float) -> np.ndarray:
    if radius <= 0:
        return np.ones(len(points))
    return np.linalg.norm(points - at, axis=1) / float(radius)


# --------------------------------------------------------------------------- #
#  Вмятина
# --------------------------------------------------------------------------- #
@op("dent", aliases=("вмятина", "вдавить", "удар", "отпечаток", "нажать", "dint"),
    category="Форма и деформации",
    summary="Вмятина от удара: поверхность проминается внутрь, край плавный. "
            "Мягкость задаётся параметром soft: у мягкого материала вмятина "
            "широкая и гладкая, у жёсткого — узкая и резкая.",
    example="кружка = cylinder radius=40 height=120 segments=64\n"
            "кружка = dent [кружка] at=[0, -40, 70] depth=8 radius=22 soft=0.6",
    params={"objects": "объект", "at": "точка удара [x,y,z] (верх детали)",
            "depth": "глубина, мм (6)", "radius": "радиус пятна, мм (20)",
            "soft": "мягкость 0…1 (0.5): 1 — гладкая вмятина, 0 — резкая",
            "rim": "валик по краю 0…1 (0.3): у жёсткого металла он заметнее",
            "dir": "направление удара [x,y,z] (от центра к at)",
            "detail": "рёбер на радиус (10): больше — глаже"},
    positional=["objects"])
def dent(a, name):
    base = _one(a, "dent")
    bb = base.manifold.bounding_box()
    center = _center(bb)
    at = np.array(a.vec("at", 3, default=(center[0], center[1], bb[5])), dtype=np.float64)
    depth = float(a.num("depth", 6.0, minv=0.01))
    radius = float(a.num("radius", 20.0, minv=0.5))
    soft = float(a.num("soft", 0.5, minv=0.0, maxv=1.0))
    rim = float(a.num("rim", 0.3, minv=0.0, maxv=1.0))
    detail = int(a.int("detail", 10, minv=2, maxv=24))
    # у мягкого материала валик сглажен, у жёсткого — выступает
    rim_height = depth * 0.12 * rim * (1.0 - 0.7 * soft)
    dirv = _dir_of(a, at, center)
    if depth > radius * 0.95:
        depth = radius * 0.95
        a.scene.log("warn", f"dent: глубина ограничена радиусом — {depth:g} мм", a.cmd.line)
    # мягкий материал получает более частую сетку: сглаживать нечего, если
    # поверхность и так состоит из крупных плоских граней
    detail_eff = int(round(detail * (1.0 + 0.6 * soft)))
    at_c = at

    def fn(p: np.ndarray) -> np.ndarray:
        q = np.linalg.norm(p - at_c, axis=1) / radius
        side = (p - at_c) @ dirv
        gate = np.clip((side + radius * 0.6) / (radius * 0.6), 0.0, 1.0)
        w = _falloff(q, soft) * gate
        # валик по краю: металл выпирает вокруг удара
        ring = np.exp(-((q - 0.82) / 0.45) ** 2) * gate
        # валик только «придерживает» спуск: выше исходной поверхности он не
        # поднимается, иначе на краю получается тонкий гребень, который на
        # рендере читается как рваная линия
        push = np.minimum(rim_height * ring - depth * w, 0.0)
        return p + dirv[None, :] * push[:, None]

    solid = _warp(base, fn, a, name, "dent", radius, detail_eff)
    solid.notes.append(f"вмятина ø{radius * 2:g} мм, глубина {depth:g} мм")
    return solid


# --------------------------------------------------------------------------- #
#  Выдувание
# --------------------------------------------------------------------------- #
@op("blow", aliases=("выдувание", "выдуть", "надуть", "пузырь", "blow", "inflate"),
    category="Форма и деформации",
    summary="Выдувает объём изнутри, как стеклодув: поверхность расходится "
            "вдоль своих нормалей, а не растягивается от одной точки. Так шар "
            "надувается шаром, а цилиндр — бочкой.",
    example="колба = sphere radius=26 segments=48\n"
            "колба = blow [колба] radius=34 height=10 soft=0.7",
    params={"objects": "объект", "at": "центр пятна [x,y,z] (центр детали)",
            "radius": "толщина слоя, который надуваем, мм (вся деталь)",
            "height": "насколько выдуть в середине, мм (10)",
            "soft": "мягкость края 0…1 (0.7)",
            "detail": "рёбер на радиус (10)"},
    positional=["objects"])
def blow(a, name):
    base = _one(a, "blow")
    bb = base.manifold.bounding_box()
    center = _center(bb)
    at = np.array(a.vec("at", 3, default=tuple(center)), dtype=np.float64)
    # Дуем в «оболочку» вокруг at: у шара все точки поверхности равноудалены
    # от центра, и мерить расстояние от at напрямую нельзя — выдувание
    # получалось бы нулевым. Считаем слой между ближней и дальней точкой
    # поверхности: ближняя надувается на полную высоту, дальняя — на ноль.
    # У шара слой нулевой, поэтому он надувается целиком (растёт шаром),
    # у цилиндра надувается бок, а торцы расходятся меньше (растёт бочкой).
    v, _t = _mesh_of(base.manifold)
    dist = np.linalg.norm(v - at, axis=1)
    near = float(dist.min())
    far = float(dist.max())
    shell = max(far - near, far * 0.6, 1e-6)
    radius = float(a.num("radius", shell, minv=0.05))
    height = float(a.num("height", 10.0, minv=0.01))
    soft = float(a.num("soft", 0.7, minv=0.0, maxv=1.0))
    detail = int(a.int("detail", 10, minv=2, maxv=24))
    if height > far:
        height = far
        a.scene.log("warn", f"blow: высота ограничена размером детали — {height:g} мм",
                    a.cmd.line)
    at_c = at
    near_c = near
    shell_c = radius

    def fn(p: np.ndarray) -> np.ndarray:
        out = np.array(p, dtype=np.float64)
        t = tris[0]
        n = _vertex_normals(out, t)
        # 0 у ближней к at поверхности, 1 у самой дальней: шар от центра
        # надувается весь, цилиндр — бочкой (торцы почти не двигаются)
        layer = np.maximum(np.linalg.norm(out - at_c, axis=1) - near_c, 0.0) / shell_c
        w = _falloff(layer, soft)
        return out + n * (height * w)[:, None]

    source = _surface_refine(base.manifold, radius, detail)
    mesh = source.to_mesh()
    tris = [np.array(mesh.tri_verts, dtype=np.uint32).reshape(-1, 3)]
    solid = _warp(base, fn, a, name, "blow", radius, detail, prepared=source)
    solid.notes.append(f"выдувание {height:g} мм в радиусе {radius:g} мм")
    return solid


# --------------------------------------------------------------------------- #
#  Щипок
# --------------------------------------------------------------------------- #
@op("pinch", aliases=("щипок", "щипнуть", "сдавить", "зажать", "pinch"),
    category="Форма и деформации",
    summary="Щипок: сдавливает деталь с двух противоположных сторон, а материал "
            "выдавливается вбок — как если ухватить пальцами.",
    example="заготовка = sphere radius=36 segments=48\n"
            "заготовка = pinch [заготовка] axis=x amount=0.45 radius=30 bulge=0.9",
    params={"objects": "объект", "at": "центр щипка [x,y,z] (центр детали)",
            "axis": "ось сдавливания: x, y или z (x)",
            "amount": "насколько сжать 0…0.9 (0.4)",
            "bulge": "насколько выдать вбок 0…2 (0.8)",
            "radius": "полуширина захвата вдоль оси, мм (около половины детали)",
            "detail": "рёбер на радиус (10)"},
    positional=["objects"])
def pinch(a, name):
    base = _one(a, "pinch")
    bb = base.manifold.bounding_box()
    center = _center(bb)
    at = np.array(a.vec("at", 3, default=tuple(center)), dtype=np.float64)
    axis = (a.text("axis", "x", ["x", "y", "z", "+x", "-x", "+y", "-y", "+z", "-z"])
            or "x").lstrip("+-").lower()
    amount = float(a.num("amount", 0.4, minv=0.01, maxv=0.9))
    bulge = float(a.num("bulge", 0.8, minv=0.0, maxv=2.0))
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    span = (bb[idx + 3] - bb[idx])
    radius = float(a.num("radius", max(span * 0.45, 1.0), minv=0.5))
    detail = int(a.int("detail", 10, minv=2, maxv=24))
    axis_vec = np.zeros(3)
    axis_vec[idx] = 1.0
    at_c = at

    def fn(p: np.ndarray) -> np.ndarray:
        rel = p - at_c
        # Захват — полоса поперёк оси: сжимается всё сечение, а не шар
        # вокруг точки, иначе щипок «не достаёт» до поверхности.
        along_scalar = rel @ axis_vec
        w = _falloff(np.abs(along_scalar) / radius, 0.7)
        along = along_scalar[:, None] * axis_vec[None, :]
        perp = rel - along
        squeezed = along * (1.0 - amount * w)[:, None] + perp * (1.0 + bulge * amount * w)[:, None]
        return at_c + squeezed

    solid = _warp(base, fn, a, name, "pinch", radius, detail)
    fixed, factor = _preserve_volume(solid.manifold, float(base.manifold.volume()), at_c)
    if factor != 1.0:
        solid.manifold = fixed
        solid.notes.append(f"объём выправлен ×{factor:.3f}")
    solid.notes.append(f"щипок по {axis} на {amount * 100:.0f}%")
    return solid


# --------------------------------------------------------------------------- #
#  Разравнивание и разглаживание
# --------------------------------------------------------------------------- #
@op("flatten", aliases=("разровнять", "плоскость", "приплюснуть", "flatten", "plane"),
    category="Форма и деформации",
    summary="Разравнивает участок поверхности, приближая его к плоскости: "
            "внутри пятна поверхность ложится ровно, к краю — плавный переход. "
            "Плоскость задаётся точкой at и нормалью dir; сила 1 — совсем плоско.",
    example="плита = box size=[120, 80, 30] round=4\n"
            "плита = flatten [плита] at=[0, 0, 15] radius=40 strength=0.9 soft=0.7",
    params={"objects": "объект", "at": "точка на выравниваемой плоскости [x,y,z]",
            "dir": "нормаль плоскости [x,y,z] (вверх)",
            "radius": "радиус участка, мм (20)", "strength": "сила 0…1 (0.8)",
            "soft": "ширина перехода 0…1 (0.6)", "detail": "рёбер на радиус (10)"},
    positional=["objects"])
def flatten(a, name):
    base = _one(a, "flatten")
    bb = base.manifold.bounding_box()
    center = _center(bb)
    at = np.array(a.vec("at", 3, default=(center[0], center[1], bb[5])), dtype=np.float64)
    normal = _dir_of(a, at, center)
    radius = float(a.num("radius", 20.0, minv=0.5))
    strength = float(a.num("strength", 0.8, minv=0.0, maxv=1.0))
    soft = float(a.num("soft", 0.6, minv=0.0, maxv=1.0))
    detail = int(a.int("detail", 10, minv=2, maxv=24))
    level = float(at @ normal)
    at_c = at
    n = normal

    # внутри пятна выравниваем начисто, к краю — плавный переход:
    # ширина перехода задаётся soft (0 — резкая граница, 1 — пологая)
    edge = 0.15 + 0.55 * soft

    def fn(p: np.ndarray) -> np.ndarray:
        q = np.linalg.norm(p - at_c, axis=1) / radius
        side = p @ n - level
        # не тянем то, что лежит глубже половины радиуса под плоскостью:
        # иначе «выравнивание» начинает втягивать противоположную стенку
        gate = np.clip((side + radius) / (0.5 * radius), 0.0, 1.0)
        ramp = np.clip((1.0 - q) / max(edge, 1e-6), 0.0, 1.0)
        ramp = ramp * ramp * (3.0 - 2.0 * ramp)          # smoothstep
        w = ramp * gate
        return p - n[None, :] * (side * strength * w)[:, None]

    solid = _warp(base, fn, a, name, "flatten", radius, detail)
    solid.notes.append(f"выровнено ø{radius * 2:g} мм до {strength * 100:.0f}%")
    return solid


@op("polish", aliases=("разгладить", "полировать", "затереть", "polish", "sand"),
    category="Форма и деформации",
    summary="Разглаживает поверхность, не превращая её в плоскость: убирает "
            "мелкую шероховатость, рябь и «лесенки», форму и объём сохраняет. "
            "Крупный рельеф остаётся. Не путать с flatten: тот именно "
            "выравнивает участок к плоскости.",
    example="камень = sphere radius=36 segments=24\n"
            "камень = corrugate [камень] step=6 amp=1.2 mode=гофра\n"
            "камень = polish [камень] passes=4 strength=0.6",
    params={"objects": "объект", "passes": "проходов 1…40 (6)",
            "strength": "сила прохода 0…1 (0.5)",
            "at": "центр участка [x,y,z] (вся поверхность)",
            "radius": "радиус участка, мм (весь объект)"},
    positional=["objects"])
def polish(a, name):
    base = _one(a, "polish")
    passes = int(a.int("passes", 6, minv=1, maxv=40))
    strength = float(a.num("strength", 0.5, minv=0.05, maxv=1.0))
    at_raw = a.vec("at", 3, default=None)
    radius = float(a.num("radius", 0.0, minv=0.0) or 0.0)
    before = int(base.manifold.num_tri())
    if before > 200_000 and passes > 3:
        passes = 3
        a.scene.log("warn", "polish: сетка крупная, проходов не больше трёх", a.cmd.line)
    v, t = _mesh_of(base.manifold)
    weight = None
    if at_raw is not None and radius > 0:
        at = np.asarray(at_raw, dtype=np.float64)
        q = np.linalg.norm(v - at, axis=1) / radius
        weight = _falloff(q, 0.75)
    out = _smooth_vertices(v, t, passes, strength, weight)
    result = _manifold_of(out, t, "polish")
    # Сглаживание всегда чуть подсаживает объём (на грубой сетке заметно).
    # Возвращаем исходный объём однородным масштабом: обещание «объём
    # сохраняет» должно быть правдой, а не оговоркой.
    centre = np.asarray(at_raw, dtype=np.float64) if at_raw is not None else v.mean(axis=0)
    result, factor = _preserve_volume(result, float(base.manifold.volume()), centre)
    solid = _derived(a, name, result, base, "polish")
    if abs(factor - 1.0) >= 0.005:
        solid.notes.append(f"объём выправлен ×{factor:.3f}")
    solid.notes.append(f"сглажено {passes} проход(ов), трис {before}")
    return solid


# --------------------------------------------------------------------------- #
#  Стёсывание и заострение
# --------------------------------------------------------------------------- #
@op("shave", aliases=("стесать", "стёсывание", "срезать_слой", "фасетка", "shave", "whittle"),
    category="Форма и деформации",
    summary="Стёсывает слой с поверхности ровной фасеткой под любым углом — "
            "как ножом или наждаком по плоскости. Можно ограничить кругом.",
    example="брусок = box size=[60, 40, 120] round=3\n"
            "брусок = shave [брусок] at=[0, 0, 120] dir=[0, 1, 1] depth=12 radius=26",
    params={"objects": "объект", "at": "точка на поверхности [x,y,z] (верх детали)",
            "dir": "наружу от среза [x,y,z] (от центра к at)",
            "depth": "сколько снять от at, мм (5)",
            "radius": "радиус пятна, мм (0 — вся поверхность)",
            "segments": "гладкость круга (64)"},
    positional=["objects"])
def shave(a, name):
    base = _one(a, "shave")
    bb = base.manifold.bounding_box()
    center = _center(bb)
    at = np.array(a.vec("at", 3, default=(center[0], center[1], bb[5])), dtype=np.float64)
    dirv = _dir_of(a, at, center)
    depth = float(a.num("depth", 5.0, minv=0.01))
    radius = float(a.num("radius", 0.0, minv=0.0) or 0.0)
    seg = int(a.int("segments", 64, minv=8, maxv=192))
    size = _diag(bb) * 2.0 + depth * 4.0 + 20.0
    frame = _frame(dirv, at)
    # в локальных координатах наружу — +Z: срез идёт по плоскости z = −depth,
    # всё, что выше, снимаем
    cutter = mf.Manifold.cube([size, size, size], True).translate(
        (0.0, 0.0, -depth + size / 2.0))
    if radius > 0:
        cyl = mf.Manifold.cylinder(size * 2.0, radius, radius, seg, True)
        cutter = cutter ^ cyl
    cutter = cutter.transform(frame)
    result = base.manifold - cutter
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("Стёсывание срезало всю деталь — уменьшите depth.")
    solid = _derived(a, name, result, base, "shave")
    solid.notes.append(f"снято {depth:g} мм" + (f" в круге ø{radius * 2:g} мм" if radius else ""))
    return solid


@op("point", aliases=("заострить", "острие", "остриё", "точить", "pencil", "sharp_point"),
    category="Форма и деформации",
    summary="Заостряет конец детали конусом — как точилка карандаш. "
            "Длина конуса задаётся, вершина встаёт ровно на прежний торец.",
    example="карандаш = cylinder radius=7 height=120 segments=48\n"
            "карандаш = point [карандаш] length=22 side=верх segments=64",
    params={"objects": "объект", "length": "длина конуса, мм (15)",
            "side": "верх или низ (верх)", "axis": "ось заострения: x, y, z (z)",
            "segments": "гладкость конуса (64)"},
    positional=["objects"])
def point(a, name):
    base = _one(a, "point")
    axis = (a.text("axis", "z", ["x", "y", "z"]) or "z").lower()
    idx = {"x": 0, "y": 1, "z": 2}[axis]
    side = (a.text("side", "верх", ["верх", "низ", "верхний", "нижний", "top", "bottom"])
            or "верх").lower()
    up = side in ("верх", "верхний", "top")
    length = float(a.num("length", 15.0, minv=0.2))
    seg = int(a.int("segments", 64, minv=12, maxv=192))
    bb = base.manifold.bounding_box()
    lo, hi = bb[idx], bb[idx + 3]
    span = max(hi - lo, 1e-6)
    if length >= span * 0.98:
        length = span * 0.98
        a.scene.log("warn", f"point: длина конуса ограничена габаритом — {length:g} мм",
                    a.cmd.line)
    tip = hi if up else lo
    shoulder = tip - length if up else tip + length
    # радиус у основания конуса: берём самый широкий поясок вершин у торца
    v, _t = _mesh_of(base.manifold)
    others = [i for i in range(3) if i != idx]
    mid = np.array([(bb[o] + bb[o + 3]) / 2.0 for o in others])
    tip_side = v[:, idx] >= shoulder - 1e-6 if up else v[:, idx] <= shoulder + 1e-6
    r0 = 0.0
    if np.count_nonzero(tip_side) >= 3:
        rel = v[tip_side][:, others] - mid
        r0 = float(np.max(np.linalg.norm(rel, axis=1)))
    if r0 < 0.2:
        r0 = float(min((bb[others[0] + 3] - bb[others[0]]),
                       (bb[others[1] + 3] - bb[others[1]])) / 2.0)
    # на волос шире фактического радиуса: конус не должен оставлять ступеньку
    r0 *= 1.005
    if r0 < 0.2:
        raise GeometryError("point: деталь слишком тонкая у торца — конус не построить.")
    direction = 1.0 if up else -1.0
    dir_vec = np.zeros(3)
    dir_vec[idx] = direction
    mat = _frame(dir_vec, [0.0, 0.0, 0.0])
    mat[:, 3] = np.zeros(3)
    mat[idx, 3] = shoulder          # локальное z=0 — на уровне основания конуса
    # конус от shoulder к торцу: у основания r0, у вершины ноль
    cone = mf.Manifold.cylinder(length, r0, 0.0, seg, False).transform(mat)
    size = _diag(bb) * 2.0 + 40.0
    # остальное тело — полупространство со стороны основания
    rest = mf.Manifold.cube([size, size, size], True).translate(
        (0.0, 0.0, -size / 2.0)).transform(mat)
    allowed = cone + rest
    result = base.manifold ^ allowed
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("Заострение срезало всю деталь — уменьшите length.")
    solid = _derived(a, name, result, base, "point")
    solid.notes.append(f"конус {length:g} мм, основание ø{r0 * 2:g} мм")
    return solid


# --------------------------------------------------------------------------- #
#  Сверление с формой дна
# --------------------------------------------------------------------------- #
@op("bore", aliases=("сверление", "сверло", "высверлить", "углубление", "bore"),
    category="Форма и деформации",
    summary="Сверлит отверстие нужной формы: плоское дно, конус как у сверла, "
            "скруглённое сферой или ступенькой под шляпку. Можно с зенковкой.",
    example="плита = box size=[120, 90, 20]\n"
            "плита = bore [плита] at=[0, 0, 20] diameter=10 depth=9 tip=конус angle=118",
    params={"objects": "объект", "at": "точка входа [x,y,z] (верх детали)",
            "dir": "направление сверления [x,y,z] (внутрь детали)",
            "diameter": "диаметр, мм (8)", "depth": "глубина, мм (10)",
            "tip": "дно: плоский|конус|сфера|ступень (плоский)",
            "angle": "угол сверла, ° (118)", "through": "сквозное да/нет (нет)",
            "countersink": "зенковка, мм (0)", "step": "диаметр ступени, мм (½ диаметра)",
            "segments": "гладкость (48)"},
    positional=["objects"])
def bore(a, name):
    base = _one(a, "bore")
    bb = base.manifold.bounding_box()
    center = _center(bb)
    at = np.array(a.vec("at", 3, default=(center[0], center[1], bb[5])), dtype=np.float64)
    outward = _dir_of(a, at, center)
    given_dir = a.vec("dir", 3, default=None)
    dirv = _unit(given_dir) if given_dir is not None else -outward
    diameter = float(a.num("diameter", 8.0, minv=0.4))
    r = diameter / 2.0
    through = a.boolean("through", False)
    depth = float(a.num("depth", 10.0, minv=0.2))
    tip = (a.text("tip", "плоский", ["плоский", "конус", "сфера", "ступень",
                                    "flat", "cone", "sphere", "step"]) or "плоский").lower()
    angle = float(a.num("angle", 118.0, minv=20.0, maxv=175.0))
    countersink = float(a.num("countersink", 0.0, minv=0.0) or 0.0)
    step_d = float(a.num("step", r, minv=0.2) or r)
    seg = int(a.int("segments", 48, minv=12, maxv=192))
    span = _diag(bb)
    if through:
        depth = span + 4.0
    elif countersink > 0:
        depth += countersink
    frame = _frame(dirv, at)
    tools = []
    # локальная ось Z смотрит ВНУТРЬ детали: режущее тело идёт от z=0 вглубь
    tools.append(mf.Manifold.cylinder(depth, r, r, seg, False))
    if tip == "конус" and not through:
        h = min(r / max(math.tan(math.radians(angle / 2.0)), 1e-3), depth * 0.9)
        # у дна (z = depth) радиус r, ниже — вершина конуса
        tools.append(mf.Manifold.cylinder(h, r, 0.0, seg, False).translate(
            (0.0, 0.0, depth - 1e-3)))
    elif tip == "сфера" and not through:
        # шар с центром на дне: нижняя полусфера даёт круглое дно (как палец)
        tools.append(mf.Manifold.sphere(r, seg).translate((0.0, 0.0, depth)))
    elif tip == "ступень" and not through:
        extra = max(depth * 0.6, r * 1.5)
        tools.append(mf.Manifold.cylinder(extra, step_d / 2.0, step_d / 2.0, seg, False).translate(
            (0.0, 0.0, depth - 1e-3)))
    if countersink > 0:
        # конус зенковки: у поверхности шире (r + cs), к дну сужается до r
        h = countersink + 0.6
        tools.append(mf.Manifold.cylinder(h, r + countersink, r, seg, False).translate(
            (0.0, 0.0, -0.6)))

    cutter = tools[0]
    for extra_tool in tools[1:]:
        cutter = cutter + extra_tool
    cutter = cutter.transform(frame)
    result = base.manifold - cutter
    if result.is_empty() or result.volume() <= 1e-9:
        raise GeometryError("Сверление срезало всю деталь — уменьшите диаметр или глубину.")
    solid = _derived(a, name, result, base, "bore")
    solid.notes.append(f"отверстие ø{diameter:g} × {min(depth, span):g} мм, дно {tip}")
    return solid
