"""Математические поверхности: SDF-выражения и «метаболы».

Это режим настоящего математического моделирования: форма задаётся формулой
f(x, y, z) < 0, а приложение извлекает поверхность (marching tetrahedra).
"""

from __future__ import annotations

import ast
import math
from typing import Any

import manifold3d as mf
import numpy as np

from .errors import DslError, GeometryError
from .ops import make_solid, op
from .values import parse_value

MAX_GRID_POINTS = 2_200_000
MAX_CELLS = 12_000_000


# --------------------------------------------------------------------------- #
#  Функции для SDF-выражений
# --------------------------------------------------------------------------- #

def _sd_sphere(x, y, z, r):
    return np.sqrt(x * x + y * y + z * z) - r


def _sd_box(x, y, z, hx, hy, hz):
    qx, qy, qz = np.abs(x) - hx, np.abs(y) - hy, np.abs(z) - hz
    ax, ay, az = np.maximum(qx, 0.0), np.maximum(qy, 0.0), np.maximum(qz, 0.0)
    return (np.sqrt(ax * ax + ay * ay + az * az)
            + np.minimum(np.maximum(qx, np.maximum(qy, qz)), 0.0))


def _sd_capsule(x, y, z, ax, ay, az, bx, by, bz, r):
    px, py, pz = x - ax, y - ay, z - az
    ex, ey, ez = bx - ax, by - ay, bz - az
    denom = ex * ex + ey * ey + ez * ez
    t = np.clip((px * ex + py * ey + pz * ez) / denom, 0.0, 1.0) if denom > 1e-12 else 0.0
    dx, dy, dz = px - ex * t, py - ey * t, pz - ez * t
    return np.sqrt(dx * dx + dy * dy + dz * dz) - r


def _sd_cylinder(x, y, z, r, h):
    dx = np.sqrt(x * x + y * y) - r
    dz = np.abs(z) - h / 2.0
    ax, az = np.maximum(dx, 0.0), np.maximum(dz, 0.0)
    return np.minimum(np.maximum(dx, dz), 0.0) + np.sqrt(ax * ax + az * az)


def _sd_torus(x, y, z, R, r):
    q = np.sqrt(x * x + y * y) - R
    return np.sqrt(q * q + z * z) - r


def _sd_ellipsoid(x, y, z, rx, ry, rz):
    k0 = np.sqrt((x / rx) ** 2 + (y / ry) ** 2 + (z / rz) ** 2)
    k1 = np.sqrt((x / (rx * rx)) ** 2 + (y / (ry * ry)) ** 2 + (z / (rz * rz)) ** 2)
    k1 = np.maximum(k1, 1e-12)
    return np.where(k1 < 1e-12, -min(rx, ry, rz), k0 * (k0 - 1.0) / k1)


def _smin(a, b, k):
    if k <= 1e-9:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


def _smax(a, b, k):
    return -_smin(-a, -b, k)


def _clamp(v, lo, hi):
    return np.clip(v, lo, hi)


def _smoothstep(a, b, v):
    t = np.clip((v - a) / (b - a), 0.0, 1.0) if abs(b - a) > 1e-12 else 0.0
    return t * t * (3 - 2 * t)


SDF_NAMESPACE: dict[str, Any] = {
    "pi": math.pi, "e": math.e, "tau": math.tau,
    "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos, "tan": np.tan,
    "asin": np.arcsin, "acos": np.arccos, "atan": np.arctan, "atan2": np.arctan2,
    "abs": np.abs, "min": np.minimum, "max": np.maximum, "pow": np.power,
    "exp": np.exp, "log": np.log,
    "floor": np.floor, "ceil": np.ceil, "round": np.round,
    "hypot": np.hypot,
    "clamp": _clamp, "smoothstep": _smoothstep,
    "smin": _smin, "smax": _smax,
    "sd_sphere": _sd_sphere, "sd_box": _sd_box, "sd_capsule": _sd_capsule,
    "sd_cylinder": _sd_cylinder, "sd_torus": _sd_torus, "sd_ellipsoid": _sd_ellipsoid,
    "len": lambda x, y, z: np.sqrt(x * x + y * y + z * z),
}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
    ast.Call, ast.IfExp, ast.Compare, ast.BoolOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
    ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)


def _compile_expression(expression: str):
    expression = (expression or "").strip()
    if not expression:
        raise DslError("Пустое выражение для SDF.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise DslError(f"Синтаксическая ошибка в выражении: {exc.msg}.",
                       hint="Пример: sd_sphere(x,y,z,30) - sd_sphere(x,y,z,20)") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise DslError("В SDF-выражении разрешены только числа, x/y/z, "
                           "арифметика и функции из справки.",
                           hint="Запрещены атрибуты, индексы, лямбды и импорты.")
        if isinstance(node, ast.Name) and node.id not in SDF_NAMESPACE and node.id not in "xyz":
            raise DslError(f"Неизвестное имя «{node.id}» в SDF-выражении.",
                           hint="Доступно: x, y, z, sd_sphere, sd_box, sd_capsule, "
                                "sd_cylinder, sd_torus, sd_ellipsoid, smin, smax, "
                                "len, clamp, sin, cos, sqrt, pi.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in SDF_NAMESPACE:
                raise DslError("Можно вызывать только встроенные функции SDF.")
            if not callable(SDF_NAMESPACE[node.func.id]):
                raise DslError(f"«{node.func.id}» — не функция.")
    env: dict[str, Any] = {"__builtins__": {}}
    env.update(SDF_NAMESPACE)
    try:
        fn = eval(f"lambda x, y, z: ({expression})", env)
    except Exception as exc:
        raise DslError(f"Не удалось вычислить выражение: {exc}") from exc
    try:
        fn(0.0, 0.0, 0.0)
    except Exception as exc:
        raise DslError(f"Ошибка в формуле при проверке: {exc}") from exc
    return fn


def compile_sdf(expression: str):
    """Скалярный вариант (по одной точке) — оставлен для совместимости."""
    fn = _compile_expression(expression)

    def safe(x, y, z):
        try:
            value = float(fn(x, y, z))
        except Exception:
            return 1e6
        if not math.isfinite(value):
            return 1e6
        return value

    return safe


def compile_field(expression: str):
    """Векторный вариант: считает поле сразу на numpy-массиве точек.

    Раньше формула вызывалась из C++ по одной точке (сотни тысяч вызовов
    Python). Теперь поле считается массивами, а поверхность извлекает
    marching cubes — это в десятки раз быстрее и без падений на «плохих»
    точках: исключение внутри массива не роняет процесс.
    """
    fn = _compile_expression(expression)

    def field(x, y, z):
        with np.errstate(all="ignore"):
            try:
                value = fn(x, y, z)
            except Exception:
                value = 1e6
            arr = np.asarray(value, dtype=np.float64)
        return np.nan_to_num(arr, nan=1e6, posinf=1e6, neginf=-1e6)

    return field


def surface_from_field(field, bounds: list[float], res: float,
                       level: float = 0.0):
    """Извлекает поверхность из поля. Возвращает (вершины, грани, шаг)."""
    from .mesher import mesh_field

    x0, y0, z0, x1, y1, z1 = [float(v) for v in bounds]
    step = max(float(res), 1e-3)
    # держим сетку в разумной памяти
    for _ in range(40):
        nx = int(round((x1 - x0) / step)) + 1
        ny = int(round((y1 - y0) / step)) + 1
        nz = int(round((z1 - z0) / step)) + 1
        if nx * ny * nz <= MAX_CELLS:
            break
        step *= 1.12
    else:
        raise GeometryError("Слишком мелкая сетка для SDF — увеличьте resolution.")
    xs = np.linspace(x0, x1, nx, dtype=np.float32)
    ys = np.linspace(y0, y1, ny, dtype=np.float32)
    zs = np.linspace(z0, z1, nz, dtype=np.float32)
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    values = np.asarray(field(X, Y, Z), dtype=np.float64)
    del X, Y, Z
    if not np.isfinite(values).all():
        values = np.nan_to_num(values, nan=1e6, posinf=1e6, neginf=-1e6)
    if values.min() >= level:
        return None, None, step
    hx = (x1 - x0) / max(nx - 1, 1)
    hy = (y1 - y0) / max(ny - 1, 1)
    hz = (z1 - z0) / max(nz - 1, 1)
    verts, faces = mesh_field(values.astype(np.float32), origin=(x0, y0, z0),
                              spacing=(hx, hy, hz), level=float(level))
    if len(faces) == 0:
        return None, None, step
    return np.asarray(verts, dtype=np.float64), np.asarray(faces, dtype=np.int64), step


def finalize_sdf(verts: np.ndarray, faces: np.ndarray, step: float,
                 what: str = "поверхность", report: dict | None = None):
    """Собирает SDF и убирает лишние трис без скрытого перестроения формы.

    Базовый допуск прежний — 0.06 шага. Если диагностическая сварка всё же
    находит non-manifold рёбра, перебираются несколько чуть больших допусков
    ядерного simplify. Кандидат принимается только при исчезновении дефекта и
    одновременном сохранении объёма, площади, габаритов, частей и рода.
    """
    from .geometry import manifold_mesh, solid_parts
    from .topology import analyze_topology

    raw = mesh_to_manifold(verts, faces, what)
    baseline_tolerance = max(float(step) * 0.06, 0.01)
    baseline = raw
    try:
        simplified = raw.simplify(baseline_tolerance)
        if not simplified.is_empty():
            before, after = raw.volume(), simplified.volume()
            if before > 0 and 0.97 < after / before < 1.03:
                baseline = simplified
    except Exception:
        pass

    def topology(solid):
        return analyze_topology(*manifold_mesh(solid), include_quality=False)

    baseline_topology = topology(baseline)
    chosen = baseline
    chosen_topology = baseline_topology
    candidates: list[dict] = []
    if baseline_topology["non_manifold_edges"]:
        base_volume = float(baseline.volume())
        base_area = float(baseline.surface_area())
        base_bbox = np.asarray(baseline.bounding_box(), dtype=np.float64)
        base_genus = int(baseline.genus())
        base_parts = int(solid_parts(baseline))
        for factor in (0.065, 0.070, 0.075, 0.080, 0.100, 0.120):
            tolerance = max(float(step) * factor, 0.01)
            if tolerance <= baseline_tolerance * (1.0 + 1e-9):
                continue
            entry: dict = {"factor": factor, "tolerance_mm": float(tolerance)}
            try:
                candidate = raw.simplify(tolerance)
                if candidate.is_empty() or candidate.status() != mf.Error.NoError:
                    entry["rejected"] = "пустое или невалидное тело"
                    candidates.append(entry)
                    continue
                candidate_topology = topology(candidate)
                volume_delta = (float(candidate.volume()) / base_volume - 1.0) * 100.0
                area_delta = (float(candidate.surface_area()) / base_area - 1.0) * 100.0 \
                    if base_area > 0 else 0.0
                bbox_delta = float(np.max(np.abs(
                    np.asarray(candidate.bounding_box(), dtype=np.float64) - base_bbox
                )))
                same_genus = int(candidate.genus()) == base_genus
                same_parts = int(solid_parts(candidate)) == base_parts
                guards = (
                    abs(volume_delta) <= 0.2
                    and abs(area_delta) <= 1.0
                    and bbox_delta <= float(step) * 0.1 + 1e-9
                    and same_genus
                    and same_parts
                )
                topology_clean = (
                    candidate_topology["non_manifold_edges"] == 0
                    and candidate_topology["boundary_edges"] == 0
                    and candidate_topology["inconsistent_winding"] == 0
                    and candidate_topology["duplicate_faces"] == 0
                    and candidate_topology["nonfinite_values"] == 0
                )
                entry.update({
                    "non_manifold_edges": candidate_topology["non_manifold_edges"],
                    "volume_delta_pct": float(volume_delta),
                    "area_delta_pct": float(area_delta),
                    "bbox_delta_mm": bbox_delta,
                    "genus_preserved": bool(same_genus),
                    "parts_preserved": bool(same_parts),
                })
                if guards and topology_clean:
                    entry["accepted"] = True
                    candidates.append(entry)
                    chosen = candidate
                    chosen_topology = candidate_topology
                    break
                entry["rejected"] = "guard" if not guards else "топологический дефект остался"
            except Exception as exc:
                entry["rejected"] = str(exc)
            candidates.append(entry)

    base_volume = float(baseline.volume())
    base_area = float(baseline.surface_area())
    base_bbox = np.asarray(baseline.bounding_box(), dtype=np.float64)
    final_bbox = np.asarray(chosen.bounding_box(), dtype=np.float64)
    if report is not None:
        report.clear()
        report.update({
            "step_mm": float(step),
            "simplify_tolerance_mm": float(
                baseline_tolerance if chosen is baseline else
                next(c["tolerance_mm"] for c in candidates if c.get("accepted"))
            ),
            "adaptive": bool(chosen is not baseline),
            "non_manifold_before": int(baseline_topology["non_manifold_edges"]),
            "non_manifold_after": int(chosen_topology["non_manifold_edges"]),
            "volume_delta_pct": float((chosen.volume() / base_volume - 1.0) * 100.0),
            "area_delta_pct": float((chosen.surface_area() / base_area - 1.0) * 100.0)
                if base_area > 0 else 0.0,
            "bbox_delta_mm": float(np.max(np.abs(final_bbox - base_bbox))),
            "genus_before": int(baseline.genus()),
            "genus_after": int(chosen.genus()),
            "parts_before": int(solid_parts(baseline)),
            "parts_after": int(solid_parts(chosen)),
            "raw_triangles": int(raw.num_tri()),
            "triangles": int(chosen.num_tri()),
            "candidates": candidates,
        })
    return chosen


def mesh_to_manifold(verts: np.ndarray, faces: np.ndarray, what: str = "поверхность"):
    """Собирает Manifold из сетки marching cubes, подбирая ориентацию граней."""
    from .geometry import manifold_from_arrays

    last: Exception | None = None
    for candidate in (faces, faces[:, ::-1]):
        try:
            solid = manifold_from_arrays(verts, candidate, what=what)
            if not solid.is_empty() and solid.volume() > 0:
                return solid
        except Exception as exc:
            last = exc
    if last is not None:
        raise GeometryError(f"Не удалось собрать поверхность: {last}") from last
    raise GeometryError("Поверхность пуста.")


def _grid_budget(bounds: list[float], resolution: float) -> float:
    return ((bounds[3] - bounds[0]) / resolution + 1) * \
           ((bounds[4] - bounds[1]) / resolution + 1) * \
           ((bounds[5] - bounds[2]) / resolution + 1) * 2.0


def _choose_resolution(a, bounds: list[float], default_div: float = 100.0,
                       limit: float = MAX_GRID_POINTS) -> float:
    res = a.num("resolution", None, minv=0.1)
    if res is None:
        extent = max(bounds[3] - bounds[0], bounds[4] - bounds[1], bounds[5] - bounds[2])
        res = max(0.5, extent / default_div)
        if _grid_budget(bounds, res) > limit:
            res = max(0.5, res * (_grid_budget(bounds, res) / limit) ** (1 / 3))
            a.scene.log("warn", f"SDF: разрешение автоматически уменьшено до {res:.2f} мм "
                                f"(иначе расчёт был бы слишком долгим).", a.cmd.line)
    if _grid_budget(bounds, res) > limit * 1.05:
        raise GeometryError(
            f"Слишком мелкое разрешение {res:g} мм для области {bounds}.",
            hint=f"Увеличьте resolution (сейчас {res:g}) или уменьшите bounds. "
                 f"Лимит — {limit:,} точек.".replace(",", " "))
    return float(res)


@op("from_sdf", aliases=("sdf", "формула", "поверхность", "из_функции"),
    category="Математические поверхности",
    summary="Строит поверхность по математической функции f(x,y,z) (отрицательное значение — внутри).",
    example="""капля = from_sdf expression="smin(sd_sphere(x,y,z-40,30), sd_sphere(x,y,z-95,20), 12)" bounds=[-40,-40,-5,40,40,120] resolution=1.5""",
    params={"expression": "формула от x, y, z (обязательно)",
            "bounds": "[xmin,ymin,zmin,xmax,ymax,zmax] (обязательно)",
            "resolution": "шаг сетки, мм (авто)",
            "level": "уровень изоповерхности (0)"},
    positional=["expression"])
def from_sdf(a, name):
    expr = a.text("expression")
    if not expr:
        raise DslError("Укажите expression — формулу поверхности.",
                       hint="Например: sd_sphere(x,y,z,30) - sd_sphere(x,y,z,24)")
    bounds = a.vec("bounds", 6, required=True)
    if not (bounds[0] < bounds[3] and bounds[1] < bounds[4] and bounds[2] < bounds[5]):
        raise GeometryError("bounds заданы неверно: минимумы должны быть меньше максимумов.")
    fn = compile_field(expr)
    res = _choose_resolution(a, bounds, default_div=120.0, limit=MAX_CELLS)
    level = float(a.num("level", 0.0) or 0.0)
    try:
        verts, faces, step = surface_from_field(fn, bounds, res, level)
    except GeometryError:
        raise
    except Exception as exc:
        raise GeometryError(f"Не удалось извлечь поверхность: {exc}") from exc
    if verts is None:
        raise GeometryError(
            "Поверхность пуста — функция нигде не становится отрицательной внутри bounds.",
            hint="Проверьте формулу и границы: внутри области должно быть f < 0.",
        )
    meshing: dict = {}
    solid = finalize_sdf(verts, faces, step, f"SDF «{name or 'фигура'}»", report=meshing)
    a.scene.log("info", f"from_sdf: сетка {step:g} мм, {solid.num_tri()} треугольников", a.cmd.line)
    result = make_solid(a.scene, name, solid, a, kind="sdf")
    result.meta["meshing"] = meshing
    if meshing.get("adaptive"):
        a.scene.log(
            "info",
            f"from_sdf: адаптивная очистка {meshing['simplify_tolerance_mm']:.3g} мм; "
            f"non-manifold {meshing['non_manifold_before']} → "
            f"{meshing['non_manifold_after']}, объём {meshing['volume_delta_pct']:+.3f}%",
            a.cmd.line,
        )
    elif meshing.get("non_manifold_after"):
        a.scene.log("warn", "from_sdf: non-manifold сварка осталась; экспорт будет остановлен",
                    a.cmd.line)
    return result


@op("blob", aliases=("метаболы", "органика", "слепить", "капля"), category="Математические поверхности",
    summary="Органическая форма из сфер и капсул, плавно слитых между собой (метаболы).",
    example="""тело = blob spheres=[[0,0,80,35],[0,0,130,28]] capsules=[[0,0,60,0,0,20,14]] blend=12""",
    params={"spheres": "сферы [[x,y,z,r], ...]",
            "capsules": "капсулы [[x1,y1,z1,x2,y2,z2,r], ...]",
            "blend": "радиус плавного слияния, мм (авто)",
            "resolution": "шаг сетки (авто)",
            "bounds": "границы области (авто, если не заданы)"},
    positional=[])
def blob(a, name):
    spheres_raw = a.value("spheres", []) or []
    capsules_raw = a.value("capsules", []) or []
    spheres: list[tuple[float, float, float, float]] = []
    capsules: list[tuple[float, ...]] = []
    if spheres_raw:
        if not isinstance(spheres_raw, list):
            raise GeometryError("spheres должен быть списком [x,y,z,r].")
        for i, item in enumerate(spheres_raw):
            vals = [float(v) for v in (item if isinstance(item, (list, tuple)) else [])]
            if len(vals) != 4:
                raise GeometryError(f"spheres[{i}]: нужно 4 числа (x,y,z,r).")
            if vals[3] <= 0:
                raise GeometryError(f"spheres[{i}]: радиус должен быть больше нуля.")
            spheres.append(tuple(vals))
    if capsules_raw:
        if not isinstance(capsules_raw, list):
            raise GeometryError("capsules должен быть списком [x1,y1,z1,x2,y2,z2,r].")
        for i, item in enumerate(capsules_raw):
            vals = [float(v) for v in (item if isinstance(item, (list, tuple)) else [])]
            if len(vals) != 7:
                raise GeometryError(f"capsules[{i}]: нужно 7 чисел (x1,y1,z1,x2,y2,z2,r).")
            if vals[6] <= 0:
                raise GeometryError(f"capsules[{i}]: радиус должен быть больше нуля.")
            capsules.append(tuple(vals))
    if not spheres and not capsules:
        raise GeometryError("Для blob нужны spheres или capsules.",
                            hint="Например: blob spheres=[[0,0,50,30],[0,0,100,20]] blend=10")
    radii = [s[3] for s in spheres] + [c[6] for c in capsules]
    blend = a.num("blend", max(1.0, min(radii) * 0.5), minv=0.0)
    if blend is None:
        blend = max(1.0, min(radii) * 0.5)
    terms: list[str] = []
    xs, ys, zs = [], [], []
    for (cx, cy, cz, r) in spheres:
        terms.append(f"sd_sphere(x-({cx}),y-({cy}),z-({cz}),{r})")
        xs += [cx - r, cx + r]
        ys += [cy - r, cy + r]
        zs += [cz - r, cz + r]
    for (x1, y1, z1, x2, y2, z2, r) in capsules:
        terms.append(f"sd_capsule(x,y,z,{x1},{y1},{z1},{x2},{y2},{z2},{r})")
        xs += [min(x1, x2) - r, max(x1, x2) + r]
        ys += [min(y1, y2) - r, max(y1, y2) + r]
        zs += [min(z1, z2) - r, max(z1, z2) + r]
    expr = terms[0]
    for term in terms[1:]:
        expr = f"smin({expr},{term},{blend})"
    fn = compile_field(expr)
    margin = max(1.0, blend) + 2.0
    bounds = [min(xs) - margin, min(ys) - margin, min(zs) - margin,
              max(xs) + margin, max(ys) + margin, max(zs) + margin]
    res = _choose_resolution(a, bounds, default_div=120.0, limit=MAX_CELLS)
    try:
        verts, faces, step = surface_from_field(fn, bounds, res)
    except GeometryError:
        raise
    except Exception as exc:
        raise GeometryError(f"Не удалось слепить форму: {exc}") from exc
    if verts is None:
        raise GeometryError("Форма пуста — проверьте координаты и радиусы.")
    meshing: dict = {}
    solid = finalize_sdf(verts, faces, step, "капля", report=meshing)
    a.scene.log("info", f"blob: сетка {step:g} мм, {solid.num_tri()} треугольников", a.cmd.line)
    result = make_solid(a.scene, name, solid, a, kind="blob")
    result.meta["meshing"] = meshing
    if meshing.get("adaptive"):
        a.scene.log(
            "info",
            f"blob: адаптивная очистка {meshing['simplify_tolerance_mm']:.3g} мм; "
            f"non-manifold {meshing['non_manifold_before']} → "
            f"{meshing['non_manifold_after']}, объём {meshing['volume_delta_pct']:+.3f}%",
            a.cmd.line,
        )
    elif meshing.get("non_manifold_after"):
        a.scene.log("warn", "blob: non-manifold сварка осталась; экспорт будет остановлен",
                    a.cmd.line)
    return result
