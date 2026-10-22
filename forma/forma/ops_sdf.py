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


# --------------------------------------------------------------------------- #
#  Функции для SDF-выражений
# --------------------------------------------------------------------------- #

def _sd_sphere(x, y, z, r):
    return math.sqrt(x * x + y * y + z * z) - r


def _sd_box(x, y, z, hx, hy, hz):
    qx = abs(x) - hx
    qy = abs(y) - hy
    qz = abs(z) - hz
    ax, ay, az = max(qx, 0.0), max(qy, 0.0), max(qz, 0.0)
    return math.sqrt(ax * ax + ay * ay + az * az) + min(max(qx, max(qy, qz)), 0.0)


def _sd_capsule(x, y, z, ax, ay, az, bx, by, bz, r):
    px, py, pz = x - ax, y - ay, z - az
    ex, ey, ez = bx - ax, by - ay, bz - az
    denom = ex * ex + ey * ey + ez * ez
    t = 0.0 if denom < 1e-12 else max(0.0, min(1.0, (px * ex + py * ey + pz * ez) / denom))
    dx, dy, dz = px - ex * t, py - ey * t, pz - ez * t
    return math.sqrt(dx * dx + dy * dy + dz * dz) - r


def _sd_cylinder(x, y, z, r, h):
    dx = math.sqrt(x * x + y * y) - r
    dz = abs(z) - h / 2.0
    ax, az = max(dx, 0.0), max(dz, 0.0)
    return min(max(dx, dz), 0.0) + math.sqrt(ax * ax + az * az)


def _sd_torus(x, y, z, R, r):
    q = math.sqrt(x * x + y * y) - R
    return math.sqrt(q * q + z * z) - r


def _sd_ellipsoid(x, y, z, rx, ry, rz):
    k0 = math.sqrt((x / rx) ** 2 + (y / ry) ** 2 + (z / rz) ** 2)
    k1 = math.sqrt((x / (rx * rx)) ** 2 + (y / (ry * ry)) ** 2 + (z / (rz * rz)) ** 2)
    if k1 < 1e-12:
        return -min(rx, ry, rz)
    return k0 * (k0 - 1.0) / k1


def _smin(a, b, k):
    if k <= 1e-9:
        return min(a, b)
    h = max(0.0, min(1.0, 0.5 + 0.5 * (b - a) / k))
    return b + (a - b) * h - k * h * (1.0 - h)


def _smax(a, b, k):
    return -_smin(-a, -b, k)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _smoothstep(a, b, v):
    t = _clamp((v - a) / (b - a), 0.0, 1.0) if abs(b - a) > 1e-12 else 0.0
    return t * t * (3 - 2 * t)


SDF_NAMESPACE: dict[str, Any] = {
    "pi": math.pi, "e": math.e, "tau": math.tau,
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "abs": abs, "min": min, "max": max, "pow": pow, "exp": math.exp, "log": math.log,
    "floor": math.floor, "ceil": math.ceil, "round": round, "hypot": math.hypot,
    "clamp": _clamp, "smoothstep": _smoothstep,
    "smin": _smin, "smax": _smax,
    "sd_sphere": _sd_sphere, "sd_box": _sd_box, "sd_capsule": _sd_capsule,
    "sd_cylinder": _sd_cylinder, "sd_torus": _sd_torus, "sd_ellipsoid": _sd_ellipsoid,
    "len": lambda x, y, z: math.sqrt(x * x + y * y + z * z),
}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load,
    ast.Call, ast.IfExp, ast.Compare, ast.BoolOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
    ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)


def compile_sdf(expression: str):
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

    def safe(x, y, z):
        # Исключение Python внутри обратного вызова C++ роняло процесс
        # (segmentation fault). Теперь «сбойная» точка считается внешней.
        try:
            value = float(fn(x, y, z))
        except Exception:
            return 1e6
        if not math.isfinite(value):
            return 1e6
        return value

    return safe


def _grid_budget(bounds: list[float], resolution: float) -> float:
    return ((bounds[3] - bounds[0]) / resolution + 1) * \
           ((bounds[4] - bounds[1]) / resolution + 1) * \
           ((bounds[5] - bounds[2]) / resolution + 1) * 2.0


def _choose_resolution(a, bounds: list[float], default_div: float = 100.0) -> float:
    res = a.num("resolution", None, minv=0.1)
    if res is None:
        extent = max(bounds[3] - bounds[0], bounds[4] - bounds[1], bounds[5] - bounds[2])
        res = max(0.5, extent / default_div)
        if _grid_budget(bounds, res) > MAX_GRID_POINTS:
            res = max(0.5, res * (_grid_budget(bounds, res) / MAX_GRID_POINTS) ** (1 / 3))
            a.scene.log("warn", f"SDF: разрешение автоматически уменьшено до {res:.2f} мм "
                                f"(иначе расчёт был бы слишком долгим).", a.cmd.line)
    if _grid_budget(bounds, res) > MAX_GRID_POINTS * 1.05:
        raise GeometryError(
            f"Слишком мелкое разрешение {res:g} мм для области {bounds}.",
            hint=f"Увеличьте resolution (сейчас {res:g}) или уменьшите bounds. "
                 f"Лимит — {MAX_GRID_POINTS:,} точек.".replace(",", " "))
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
    fn = compile_sdf(expr)
    bounds = a.vec("bounds", 6, required=True)
    if not (bounds[0] < bounds[3] and bounds[1] < bounds[4] and bounds[2] < bounds[5]):
        raise GeometryError("bounds заданы неверно: минимумы должны быть меньше максимумов.")
    res = _choose_resolution(a, bounds)
    # Сетка ровно по целому числу ячеек: так изоповерхность не «рвётся» на краю.
    span = max(bounds[3] - bounds[0], bounds[4] - bounds[1], bounds[5] - bounds[2])
    cells = max(8, int(round(span / res)))
    res = span / cells
    level = a.num("level", 0.0)
    try:
        solid = mf.Manifold.level_set(lambda x, y, z: -fn(x, y, z), bounds, res, float(level))
    except Exception as exc:
        raise GeometryError(f"Не удалось извлечь поверхность: {exc}") from exc
    if solid.is_empty():
        raise GeometryError(
            "Поверхность пуста — функция нигде не становится отрицательной внутри bounds.",
            hint="Проверьте формулу и границы: внутри области должно быть f < 0.",
        )
    return make_solid(a.scene, name, solid, a, kind="sdf")


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
    fn = compile_sdf(expr)
    margin = max(1.0, blend) + 2.0
    bounds = [min(xs) - margin, min(ys) - margin, min(zs) - margin,
              max(xs) + margin, max(ys) + margin, max(zs) + margin]
    res = _choose_resolution(a, bounds, default_div=110.0)
    try:
        solid = mf.Manifold.level_set(lambda x, y, z: -fn(x, y, z), bounds, res)
    except Exception as exc:
        raise GeometryError(f"Не удалось слепить форму: {exc}") from exc
    if solid.is_empty():
        raise GeometryError("Форма пуста — проверьте координаты и радиусы.")
    return make_solid(a.scene, name, solid, a, kind="blob")
