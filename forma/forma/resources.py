"""Дешёвая предварительная оценка полигонажа перед интерактивной сборкой.

Оценка намеренно не строит ни одного Manifold и не вызывает булевы операции.
Это важно для предупреждения о тяжёлой команде: до подтверждения пользователя
не расходуются ни время построения, ни память под сетку. Оценка консервативная
и нужна только для паузы; фактический число треугольников по-прежнему берётся
из построенной сцены.
"""

from __future__ import annotations

import math
import re

from .dsl import Command, parse_script
from .ops import lookup
from .values import parse_number, parse_value

RESOURCE_TRI_LIMIT = 500_000
_MAX_ESTIMATE = 20_000_000
_NO_GEOMETRY = {
    "check", "gap", "clearance", "probe", "passport", "note", "param", "let",
    "help", "version", "save", "load", "light", "color", "scene", "comment",
    "info", "show", "hide", "remove", "delete", "group", "ungroup", "background",
    "материал", "цвет", "покраска", "сетка", "ориентация", "axes", "axis",
}
_CONSUMING = {"union", "weld", "join", "difference", "intersect", "cut", "common", "hull"}


def _canonical(cmd: Command) -> str:
    try:
        return str(lookup(cmd.verb).name).lower()
    except Exception:
        return (cmd.verb or "").strip().lower()


def _raw(cmd: Command, key: str):
    if key in cmd.kwargs:
        return cmd.kwargs[key]
    # Наиболее употребительные русские синонимы не требуют полного Args:
    # предварительная оценка не должна падать из-за неизвестного параметра.
    aliases = {"count": ("количество",), "segments": ("сегменты", "сегмент"),
               "detail": ("детализация",), "length": ("длина",),
               "radius": ("радиус",), "depth": ("глубина",),
               "width": ("ширина",), "height": ("высота",),
               "density": ("плотность",)}
    for alias in aliases.get(key, ()):
        if alias in cmd.kwargs:
            return cmd.kwargs[alias]
    return None


def _num(cmd: Command, key: str, default: float, params: dict) -> float:
    raw = _raw(cmd, key)
    if raw is None:
        return float(default)
    value = parse_number(str(raw), params)
    return float(default) if value is None or not math.isfinite(value) else float(value)


def _text(cmd: Command, key: str, default: str = "") -> str:
    raw = _raw(cmd, key)
    if raw is None:
        return default
    value = parse_value(str(raw), {}, {})
    return str(value if value is not None else raw).strip().lower()


def _list_value(cmd: Command, key: str, params: dict):
    raw = _raw(cmd, key)
    if raw is None:
        return None
    try:
        return parse_value(str(raw), params, {})
    except Exception:
        return None


def _refs(cmd: Command, known: set[str]) -> list[str]:
    values = list(cmd.args)
    raw = _raw(cmd, "objects")
    if raw is not None:
        values.append(str(raw))
    out: list[str] = []
    for value in values:
        for token in re.split(r"[,;\s\[\]()]+", str(value)):
            token = token.strip()
            if token in known and token not in out:
                out.append(token)
    return out


def _segments(cmd: Command, params: dict, default: int = 48) -> int:
    explicit = _num(cmd, "segments", 0, params)
    if explicit > 0:
        return max(3, min(4096, int(round(explicit))))
    detail = _num(cmd, "detail", 3, params)
    return max(8, min(4096, int(round(default * (2 ** max(0.0, detail - 3.0))))))


def _estimate(cmd: Command, params: dict, current: dict[str, int], refs: list[str]) -> int:
    op = _canonical(cmd)
    if op in _NO_GEOMETRY:
        return 0
    base = sum(current.get(ref, 0) for ref in refs)
    count = max(0, int(round(_num(cmd, "count", 0, params))))
    length = abs(_num(cmd, "length", 24, params))

    if op in {"sphere", "ellipsoid", "icosphere"}:
        if op == "icosphere" and _raw(cmd, "divisions") is not None:
            divisions = max(0, min(8, int(round(_num(cmd, "divisions", 2, params)))))
            return min(_MAX_ESTIMATE, 20 * (4 ** divisions))
        n = _segments(cmd, params)
        return min(_MAX_ESTIMATE, max(12, n * n // 2))
    if op in {"box", "cube_hole", "prism", "pyramid", "octa"}:
        sides = max(3, int(round(_num(cmd, "sides", 4, params))))
        return max(12, sides * 8)
    if op in {"cylinder", "cone", "capsule", "torus", "ring", "washer", "barrel"}:
        n = _segments(cmd, params, 48)
        return min(_MAX_ESTIMATE, max(24, n * (8 if op in {"torus", "barrel"} else 4)))
    if op in {"hair", "spikes"}:
        density = _num(cmd, "density", _num(cmd, "fill", -1, params), params)
        roots = count if count else (800 * max(0.0, density) / 100.0 if density >= 0 else (120 if op == "hair" else 12))
        if op == "spikes":
            sides = max(3, int(round(_num(cmd, "sides", 24, params))))
            return min(_MAX_ESTIMATE, int(roots * sides * 2 + base))
        style = _text(cmd, "style", "волоски")
        per = 900 if length > 60 else 320
        if style in {"пряди", "водоросли", "листья"}:
            per = int(per * 1.35)
        return min(_MAX_ESTIMATE, int(roots * per + base))
    if op in {"scales", "scale"}:
        rows = max(1, int(round(_num(cmd, "rows", 9, params))))
        per_row = max(1, int(round(_num(cmd, "per_row", 15, params))))
        return min(_MAX_ESTIMATE, int(rows * per_row * 180 + base))
    if op in {"array", "повтор", "repeat", "ряд", "grid", "сетка"}:
        n = count or max(1, int(round(_num(cmd, "copies", 1, params))))
        size = _list_value(cmd, "size", params)
        if isinstance(size, (list, tuple)) and size:
            n = 1
            for value in size:
                if isinstance(value, (int, float)):
                    n *= max(1, int(value))
        return min(_MAX_ESTIMATE, int(max(1, n) * max(base, 100)))
    if op in {"wrinkle", "crack", "складка", "сгиб", "fold", "fold_sheet"}:
        freq = abs(_num(cmd, "freq", 12, params))
        detail = abs(_num(cmd, "detail", 0, params))
        extra = freq * 700 + (min(2_000_000, 100_000 / max(detail, 0.02)) if detail else 0)
        return min(_MAX_ESTIMATE, int(base + extra + 1000))
    if op in {"refine", "subdivide", "smooth", "loop"}:
        if op == "smooth":
            level = max(1, int(round(_num(cmd, "levels", 1, params))))
            multiplier = 4 ** min(level - 1, 5)
        else:
            level = max(1, int(round(_num(cmd, "level", _num(cmd, "passes", 1, params), params))))
            multiplier = 4 ** min(level, 5)
        edge = abs(_num(cmd, "length", 0, params))
        if edge:
            multiplier = max(multiplier, min(1000, 4.0 / max(edge, 0.01)))
        return min(_MAX_ESTIMATE, int(max(base, 100) * multiplier))
    if op in {"from_sdf", "blob"}:
        resolution = abs(_num(cmd, "resolution", 0, params))
        bounds = _list_value(cmd, "bounds", params)
        if op == "blob" and not (isinstance(bounds, (list, tuple)) and len(bounds) == 6):
            xs, ys, zs = [], [], []
            spheres = _list_value(cmd, "spheres", params) or []
            capsules = _list_value(cmd, "capsules", params) or []
            for item in spheres if isinstance(spheres, list) else []:
                if isinstance(item, (list, tuple)) and len(item) == 4:
                    x, y, z, radius = (float(v) for v in item)
                    xs += [x - radius, x + radius]; ys += [y - radius, y + radius]; zs += [z - radius, z + radius]
            for item in capsules if isinstance(capsules, list) else []:
                if isinstance(item, (list, tuple)) and len(item) == 7:
                    x, y, z, x2, y2, z2, radius = (float(v) for v in item)
                    xs += [min(x, x2) - radius, max(x, x2) + radius]
                    ys += [min(y, y2) - radius, max(y, y2) + radius]
                    zs += [min(z, z2) - radius, max(z, z2) + radius]
            if xs:
                bounds = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
        if isinstance(bounds, (list, tuple)) and len(bounds) == 6:
            dx, dy, dz = (abs(float(bounds[i + 3]) - float(bounds[i])) for i in range(3))
            step = resolution or max(0.5, max(dx, dy, dz) / 120.0)
            # Площадь изоповерхности растёт как площадь сечения сетки,
            # а не как её объём. Коэффициент близок к marching-cubes сценам
            # ФОРМЫ и не наказывает обычные SDF-примеры за пустой объём bbox.
            estimate = (dx * dy + dx * dz + dy * dz) / max(step * step, 1e-9)
            return min(_MAX_ESTIMATE, max(100, int(estimate)))
        return min(_MAX_ESTIMATE, int(2_000_000 / max(resolution or 1.5, 0.05) ** 3))
    if op in {"saddle", "гипар", "hyperboloid"}:
        nu = max(4, int(round(_num(cmd, "nu", _num(cmd, "segments", 32, params), params))))
        nv = max(4, int(round(_num(cmd, "nv", _num(cmd, "segments", 32, params), params))))
        return min(_MAX_ESTIMATE, int(nu * nv * 4 + base))
    if op in {"union", "weld", "join", "difference", "intersect", "cut", "common"}:
        return min(_MAX_ESTIMATE, max(base, 100))
    if op in {"remove", "delete"}:
        return 0
    # Для незнакомой команды не блокируем работу, но учитываем явно большой
    # count: это лучше, чем молча пропустить очевидный ресурсный запрос.
    if count > 100:
        return min(_MAX_ESTIMATE, int(base + count * 100))
    return min(_MAX_ESTIMATE, max(32, base))


def estimate_script_tris(script: str, overrides: dict | None = None,
                         upto: int | None = None) -> int:
    """Возвращает оценку пикового суммарного полигонажа сцены.

    ``upto`` ограничивает оценку кадром сборки, а ``overrides`` повторяет
    подмену параметров морфинга. Парсинг ошибок здесь не скрывается: обычный
    build затем покажет исходное сообщение. Для предупреждения нечитаемый
    скрипт просто имеет нулевую оценку и идёт обычным путём.
    """
    try:
        commands = parse_script(script or "")
    except Exception:
        return 0
    if upto is not None:
        commands = commands[:max(0, int(upto))]
    override_values = dict(overrides or {})
    params: dict[str, float] = {}
    for key, value in override_values.items():
        try:
            number = float(value)
            if math.isfinite(number):
                params[str(key)] = number
        except (TypeError, ValueError):
            pass
    current: dict[str, int] = {}
    total = 0
    peak = 0
    for cmd in commands:
        # Краткая форма параметра `N = 128` — не операция и не геометрия.
        # Её тоже нужно раскрыть до оценки segments=N, иначе морфинг и
        # обычная сборка получили бы разные, неточные результаты.
        if cmd.target and (cmd.verb or "").lower() != "let":
            value = parse_number((cmd.rest or "").strip(), params)
            if value is not None and math.isfinite(value):
                if cmd.target not in override_values:
                    params[cmd.target] = value
                continue
        if (cmd.verb or "").lower() == "let":
            for key, raw in cmd.kwargs.items():
                if key in override_values:
                    continue
                value = parse_number(raw, params)
                if value is not None:
                    params[key] = value
            if cmd.target and cmd.target not in override_values:
                value = parse_number(cmd.args[0] if cmd.args else "0", params)
                if value is not None:
                    params[cmd.target] = value
            continue
        refs = _refs(cmd, set(current))
        estimate = _estimate(cmd, params, current, refs)
        op = _canonical(cmd)
        target = cmd.target
        if target:
            old = current.get(target, 0)
            if estimate > 0 or op not in _NO_GEOMETRY:
                current[target] = estimate
                total += estimate - old
                if op in _CONSUMING:
                    for ref in refs:
                        if ref != target and ref in current:
                            total -= current.pop(ref)
        elif refs:
            # Команды деформации заменяют первый объект, а не добавляют его
            # копию в сцену. Остальные ссылки уже учтены в estimate.
            first = refs[0]
            old = current.get(first, 0)
            if estimate > 0:
                current[first] = max(estimate, old if op in _NO_GEOMETRY else estimate)
                total += current[first] - old
        elif estimate > 0 and op not in _NO_GEOMETRY:
            # Команда без явного target обычно меняет текущий объект. Если
            # его нельзя сопоставить, учитываем только оценку как отдельный риск.
            total += estimate
        total = max(0, min(_MAX_ESTIMATE, total))
        peak = max(peak, total)
    return int(peak)


def resource_warning(script: str, overrides: dict | None = None,
                     upto: int | None = None) -> dict | None:
    estimate = estimate_script_tris(script, overrides=overrides, upto=upto)
    if estimate <= RESOURCE_TRI_LIMIT:
        return None
    return {
        "resource_warning": True,
        "ok": False,
        "estimated_tris": int(estimate),
        "limit": RESOURCE_TRI_LIMIT,
        "message": (f"Команда запрашивает примерно {estimate:,} трис — больше "
                    f"{RESOURCE_TRI_LIMIT:,}. Построение поставлено на паузу до подтверждения."
                    ).replace(",", " "),
    }
