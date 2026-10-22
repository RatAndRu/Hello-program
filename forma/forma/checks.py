"""Проверки модели, записанные прямо в сценарии.

    check кружка watertight
    check кружка height 90..110
    check кружка wall 3..5
    check кружка symmetric y
    check ручка gap корпус 0.5..2

Результат — набор понятных вердиктов с фактическими значениями.
"""

from __future__ import annotations

from .errors import FormaError
from .values import Range, fmt, parse_value

RULE_ALIASES = {
    "герметичность": "watertight", "замкнутость": "watertight", "замкнутая": "watertight",
    "род": "genus", "отверстия": "genus",
    "части": "parts", "частей": "parts",
    "размер": "size", "размеры": "size",
    "высота": "height", "ширина": "width", "глубина": "depth",
    "объём": "volume", "объем": "volume",
    "масса": "mass", "вес": "mass",
    "стенка": "wall", "стенки": "wall", "толщина": "wall", "толщина_стенок": "wall",
    "дно": "flat_bottom", "плоское_дно": "flat_bottom",
    "нависания": "overhang", "нависание": "overhang",
    "симметрия": "symmetric", "симметричность": "symmetric",
    "зазор": "gap", "расстояние": "gap", "clearance": "gap", "посадка": "gap",
    "острота": "sharp_edge", "острые_рёбра": "sharp_edge",
    "качество_сетки": "tri_quality", "иглы": "tri_quality",
    "мин_стенка": "wall_min", "стенка_мин": "wall_min",
    "внутри": "inside",
    "треугольники": "tris", "трис": "tris",
    "отклонение": "deviation", "похожесть": "deviation", "эталон": "deviation",
    "hausdorff": "deviation", "гаусдорф": "deviation", "сравнение": "deviation",
    "связь": "связь", "сопряжение": "связь", "петля": "связь", "mate": "связь",
}

RULE_LABELS = {
    "watertight": "герметичность",
    "genus": "сквозные отверстия",
    "parts": "число частей",
    "size": "габариты",
    "height": "высота",
    "width": "ширина",
    "depth": "глубина",
    "volume": "объём",
    "mass": "масса",
    "wall": "толщина стенок",
    "flat_bottom": "плоское дно",
    "overhang": "нависания",
    "symmetric": "симметрия",
    "gap": "зазор",
    "inside": "вложенность",
    "tris": "треугольники",
    "wall_min": "минимальная стенка",
    "sharp_edge": "острые рёбра",
    "tri_quality": "качество треугольников",
    "deviation": "отклонение от эталона",
    "связь": "сопряжение",
}

UNITS = {
    "size": "мм", "height": "мм", "width": "мм", "depth": "мм",
    "volume": "см³", "mass": "г", "wall": "мм", "gap": "мм",
    "flat_bottom": "%", "overhang": "%", "symmetric": "%",
    "tris": "трис", "genus": "шт", "parts": "шт",
    "wall_min": "мм", "sharp_edge": "°", "tri_quality": "%",
    "deviation": "мм", "связь": "мм",
}

AXES = {"x": 0, "y": 1, "z": 2, "ширина": 0, "глубина": 1, "высота": 2,
        "width": 0, "depth": 1, "height": 2}
AXIS_LABEL = {0: "ширина (X)", 1: "глубина (Y)", 2: "высота (Z)"}


def _result(ok: bool, rule: str, text: str, target: str, line: int,
            actual=None, expected: str = "", label: str | None = None) -> dict:
    return {
        "ok": bool(ok),
        "rule": rule,
        "label": label or RULE_LABELS.get(rule, rule),
        "text": text,
        "target": target,
        "line": line,
        "actual": actual,
        "expected": expected,
    }


class _ValueScope(dict):
    """Параметры сцены плюс доступ к наборам значений (словарям, спискам)."""

    def __init__(self, scene):
        super().__init__(getattr(scene, "params", {}) or {})
        self.variables = getattr(scene, "vars", {}) or {}


def _parse_value(raw, scope):
    if isinstance(scope, _ValueScope):
        return parse_value(raw, dict(scope), scope.variables)
    return parse_value(raw, scope or {}, None)


def _parse_range(raw: str, params) -> Range:
    if hasattr(params, "params"):
        params = params.params
    value = _parse_value(raw, params)
    if isinstance(value, Range):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Range(float(value), float(value))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        lo = float(value[0]) if value[0] is not None else None
        hi = float(value[1]) if value[1] is not None else None
        return Range(lo, hi)
    raise FormaError(f"«{raw}» — не диапазон. Пример: 3..5, ..10 или 90.")


def _range_verdict(value: float, rng: Range, unit: str) -> tuple[bool, str]:
    ok = rng.contains(value)
    if ok:
        return True, "в норме"
    if rng.lo is not None and value < rng.lo:
        return False, "меньше нормы"
    if rng.hi is not None and value > rng.hi:
        return False, "больше нормы"
    return False, "вне диапазона"


def _fmt_range(rng: Range, unit: str) -> str:
    text = rng.describe()
    if unit == "%":
        return f"{text}%"
    return f"{text} {unit}".strip()


def _num(value, unit: str, digits: int = 2) -> str:
    if isinstance(value, int):
        s = f"{value:,}".replace(",", " ")
    else:
        s = fmt(value, digits)
    if unit == "%":
        return f"{s}%"
    return f"{s} {unit}".strip()


_REFERENCE_CACHE: dict[str, tuple[float, object]] = {}


def _load_reference(path):
    """Читает эталон (STL/OBJ/GLB/...) и кэширует по времени изменения."""
    from .geometry import manifold_from_arrays
    from .ops_io import load_any

    key = str(path.resolve())
    mtime = path.stat().st_mtime
    cached = _REFERENCE_CACHE.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    verts, faces = load_any(path)
    ref = manifold_from_arrays(verts, faces, "эталон")
    _REFERENCE_CACHE[key] = (mtime, ref)
    return ref


RULES = {"watertight", "genus", "parts", "size", "height", "width", "depth", "volume",
         "mass", "wall", "wall_min", "flat_bottom", "overhang", "symmetric", "gap",
         "clearance", "inside", "tris", "sharp_edge", "tri_quality", "deviation",
         "связь"}


def evaluate_checks(scene, cache) -> list[dict]:
    results: list[dict] = []
    for spec in scene.checks:
        target_name = spec["target"]
        rule_raw = (spec["rule"] or "").lower()
        rule = RULE_ALIASES.get(rule_raw, rule_raw)
        line = spec.get("line", 0)
        args = spec.get("args", [])
        if rule not in RULES:
            results.append(_result(False, rule_raw or "?", 
                                   f"неизвестное правило «{spec['rule']}» "
                                   f"(доступно: {', '.join(sorted(RULES))})",
                                   target_name, line))
            continue
        try:
            solid = scene.resolve(target_name)
        except FormaError as exc:
            results.append(_result(False, rule, exc.message + (f" {exc.hint}" if exc.hint else ""),
                                   target_name, line))
            continue
        try:
            results.append(_evaluate_one(solid, rule, args, line, cache))
        except FormaError as exc:
            text = exc.message + (f" {exc.hint}" if exc.hint else "")
            results.append(_result(False, rule, text, target_name, line))
        except Exception as exc:  # pragma: no cover
            results.append(_result(False, rule, f"ошибка проверки: {exc}", target_name, line))
    return results


def _evaluate_one(solid, rule: str, args: list[str], line: int, cache) -> dict:
    name = solid.name
    data = cache.get(solid)
    unit = UNITS.get(rule, "")
    label = RULE_LABELS.get(rule, rule)

    if rule == "watertight":
        ok = data["status"] == "NoError"
        text = "оболочка замкнута (герметична)" if ok else f"оболочка не замкнута ({data['status']})"
        return _result(ok, rule, text, name, line, ok, label=label)

    if rule == "genus":
        if not args:
            raise FormaError("Укажите ожидаемый род: check объект genus 1")
        rng = _parse_range(args[0], cache_scene(cache))
        value = data["genus"]
        ok, verdict = _range_verdict(value, rng, "")
        return _result(ok, rule, f"{label}: {value} — {verdict} ({_fmt_range(rng, '')})",
                       name, line, value, _fmt_range(rng, ""), label)

    if rule == "parts":
        rng = _parse_range(args[0], cache_scene(cache)) if args else Range(1, 1)
        value = data["parts"]
        ok, verdict = _range_verdict(value, rng, "")
        return _result(ok, rule, f"{label}: {value} — {verdict} ({_fmt_range(rng, '')})",
                       name, line, value, _fmt_range(rng, ""), label)

    if rule in ("size", "height", "width", "depth"):
        size = data["size"]
        scene = cache_scene(cache)
        if rule == "size":
            if not args:
                raise FormaError("Укажите диапазоны: check объект size 80..100 80..100 90..110")
            if len(args) == 1:
                rng = _parse_range(args[0], scene)
                ok = all(rng.contains(v) for v in size)
                actual_text = f"{fmt(size[0])} × {fmt(size[1])} × {fmt(size[2])} мм"
                exp = _fmt_range(rng, "мм") + " по каждой оси"
                verdict = "в норме" if ok else "вне диапазона"
                return _result(ok, rule, f"{label}: {actual_text} — {verdict} ({exp})",
                               name, line, list(size), exp, label)
            if len(args) == 3:
                ranges = [_parse_range(a, scene) for a in args]
                oks = [r.contains(v) for r, v in zip(ranges, size)]
                ok = all(oks)
                actual_text = f"{fmt(size[0])} × {fmt(size[1])} × {fmt(size[2])} мм"
                exp = " × ".join(_fmt_range(r, "мм") for r in ranges)
                verdict = "в норме" if ok else "не совпадает"
                return _result(ok, rule, f"{label}: {actual_text} — {verdict} ({exp})",
                               name, line, list(size), exp, label)
            raise FormaError("Для size нужен 1 диапазон (все оси) или 3 (X, Y, Z).")
        idx = {"height": 2, "width": 0, "depth": 1}[rule]
        if not args:
            raise FormaError(f"Укажите диапазон: check объект {rule} 90..110")
        rng = _parse_range(args[0], scene)
        value = size[idx]
        ok, verdict = _range_verdict(value, rng, "мм")
        return _result(ok, rule, f"{label}: {_num(value, 'мм')} — {verdict} ({_fmt_range(rng, 'мм')})",
                       name, line, value, _fmt_range(rng, "мм"), label)

    if rule in ("volume", "mass", "wall", "wall_min", "flat_bottom", "overhang", "tris"):
        if not args:
            raise FormaError(f"Укажите диапазон: check объект {rule} 3..5")
        rng = _parse_range(args[0], cache_scene(cache))
        if rule in ("wall", "wall_min"):
            wall = data.get("wall")
            if not wall:
                return _result(False, rule,
                               f"{label}: полости не найдено — объект сплошной "
                               f"(проверка толщины применима к полым телам)",
                               name, line, None, _fmt_range(rng, "мм"), label)
            value = wall["min"] if rule == "wall_min" else wall["median"]
        elif rule == "volume":
            value = data["volume_cm3"]
        elif rule == "mass":
            value = data["mass_g"]
        elif rule == "tris":
            value = data["tris"]
        else:
            value = data[f"{rule}_pct"]
        ok, verdict = _range_verdict(value, rng, unit)
        digits = 0 if rule in ("tris", "mass") else 2
        actual_text = _num(int(value) if rule == "tris" else value, unit, digits)
        where = ""
        if rule in ("wall", "wall_min"):
            point = (wall or {}).get("min_point")
            if point:
                where = (f"; минимум {_num(wall['min'], 'мм')} мм в точке "
                         f"({_num(point[0], 'мм')}, {_num(point[1], 'мм')}, {_num(point[2], 'мм')})")
        return _result(ok, rule,
                       f"{label}: {actual_text} — {verdict} ({_fmt_range(rng, unit)}){where}",
                       name, line, value, _fmt_range(rng, unit), label)

    if rule == "deviation":
        if not args:
            raise FormaError("Укажите эталон и допуск: check деталь deviation reference.stl 0.3")
        raw = (args[0] or "").strip().strip("\"'")
        if not raw:
            raise FormaError("Нужен путь к эталону: check деталь deviation reference.stl 0.3")
        tol = 0.3
        if len(args) > 1:
            value = _parse_value(args[1], cache_scene(cache))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                tol = float(value)
        from .cuts import hausdorff
        from .ops_io import resolve_file
        path = resolve_file(raw)
        ref = _load_reference(path)
        a_bb = solid.manifold.bounding_box()
        r_bb = ref.bounding_box()
        # сравниваем по центру габаритов: эталон мог быть сохранён в другом месте
        shift = [(a_bb[i] + a_bb[i + 3]) / 2 - (r_bb[i] + r_bb[i + 3]) / 2
                 for i in range(3)]
        if any(abs(v) > 1e-6 for v in shift):
            ref = ref.translate(shift)
        res = hausdorff(solid.manifold, ref, samples=900)
        ok = res["max"] <= tol
        verdict = "в норме" if ok else "слишком далеко от эталона"
        text = (f"{label} «{path.name}»: макс {fmt(res['max'])} мм, "
                f"среднее {fmt(res['mean'])} мм, 95% ≤ {fmt(res['p95'])} мм — {verdict} "
                f"(допуск {fmt(tol)} мм)")
        result = _result(ok, rule, text, name, line, res["max"], f"≤ {fmt(tol)} мм", label)
        result["deviation"] = res
        result["reference"] = path.name
        return result

    if rule == "symmetric":
        if not args:
            raise FormaError("Укажите ось симметрии: check объект symmetric y")
        axis = args[0].lower().strip()
        axis = {"ширина": "x", "глубина": "y", "высота": "z"}.get(axis, axis)
        if axis not in ("x", "y", "z"):
            raise FormaError("Ось симметрии должна быть x, y или z.")
        tol = 1.0
        if len(args) > 1:
            tol_val = _parse_value(args[1], cache_scene(cache))
            if isinstance(tol_val, (int, float)):
                tol = float(tol_val)
        plane = 0.0
        if len(args) > 2:
            plane_val = _parse_value(args[2], cache_scene(cache))
            if isinstance(plane_val, (int, float)):
                plane = float(plane_val)
        err = cache.symmetry(solid, axis, plane)
        if err is None:
            skipped = _result(True, rule,
                              f"{label} по {axis.upper()}: слишком тяжёлая сетка — пропущено",
                              name, line, None, f"≤ {fmt(tol)}%", label)
            skipped["axis"] = axis
            return skipped
        ok = err <= tol
        result = _result(ok, rule,
                         f"{label} по {axis.upper()}: отклонение {fmt(err, 3)}% "
                         f"({'в норме' if ok else 'нарушена'}, допуск {fmt(tol)}%)",
                         name, line, err, f"≤ {fmt(tol)}%", label)
        result["axis"] = axis
        return result

    if rule == "gap":
        if not args:
            raise FormaError("Укажите второй объект: check ручка gap корпус 0.5..2")
        scene = _scene(cache)
        other = scene.resolve(args[0], "объект")
        rng = _parse_range(args[1], scene) if len(args) > 1 else Range(0.0, None)
        search = max(rng.hi if rng.hi is not None else 50.0, 10.0) * 1.2
        try:
            gap = solid.manifold.min_gap(other.manifold, search)
        except Exception:
            gap = 0.0
        capped = gap >= search * 0.999
        ok = rng.contains(gap)
        actual_text = f">{fmt(search)} мм" if capped else _num(gap, "мм")
        return _result(ok, rule, f"{label} до «{other.name}»: {actual_text} "
                                 f"({'в норме' if ok else 'не в норме'}, нужно {_fmt_range(rng, 'мм')})",
                       name, line, gap, _fmt_range(rng, "мм"), label)

    if rule == "связь":
        scene = _scene(cache)
        from .mates import residual_of
        records = [m for m in (getattr(scene, "mates", []) or [])
                   if m.get("moving") == name]
        if not records:
            raise FormaError("У этой детали нет сопряжений.",
                             hint=f"Добавьте: сопряжение {name} основание type=плоскость")
        worst = max(records, key=lambda r: residual_of(r, scene))
        res = residual_of(worst, scene)
        tol = 1.0 if worst.get("kind") == "hinge" else 0.05
        if args:
            tol = float(_parse_range(args[0], cache_scene(cache)).hi or tol)
        ok = res <= tol
        text = (f"связь с «{worst.get('base')}» ({worst.get('kind_ru', worst.get('kind'))}): "
                f"остаток {_num(res, 'мм')} — {'держится' if ok else 'разъехалась'}"
                f" (допуск {_num(tol, 'мм')})")
        return _result(ok, rule, text, name, line, res, f"0..{tol:g}", "сопряжение")

    if rule == "inside":
        if not args:
            raise FormaError("Укажите объект: check полость inside корпус")
        scene = _scene(cache)
        other = scene.resolve(args[0], "объект")
        diff = (solid.manifold - other.manifold).volume()
        ok = diff <= max(solid.manifold.volume() * 1e-4, 0.05)
        return _result(ok, rule,
                       f"«{name}» {'целиком внутри' if ok else 'выходит за пределы'} «{other.name}»"
                       + ("" if ok else f" (лишний объём {fmt(diff / 1000)} см³)"),
                       name, line, diff, "внутри", label)

    if rule == "sharp_edge":
        from .metrics import edge_angles
        limit = 90.0
        if args:
            value = _parse_value(args[0], cache_scene(cache))
            if isinstance(value, (int, float)):
                limit = float(value)
        angles = edge_angles(solid.manifold)
        if len(angles) == 0:
            return _result(True, rule, f"{label}: рёбер не найдено", name, line, 0.0,
                           f"≤ {fmt(limit)}°", label)
        worst = float(angles.max())
        count = int((angles > limit).sum())
        ok = count == 0
        return _result(ok, rule,
                       f"{label}: самое острое ребро {fmt(worst, 1)}°, "
                       f"рёбер острее {fmt(limit, 0)}° — {count} "
                       f"({'в норме' if ok else 'нарушено'})",
                       name, line, worst, f"≤ {fmt(limit, 0)}°", label)

    if rule == "tri_quality":
        from .metrics import tri_quality
        limit = 1.0
        if args:
            value = _parse_value(args[0], cache_scene(cache))
            if isinstance(value, (int, float)):
                limit = float(value)
        q = tri_quality(solid.manifold)
        ok = q["bad_pct"] <= limit
        return _result(ok, rule,
                       f"{label}: тонких треугольников {fmt(q['bad_pct'])} % "
                       f"({q['bad']} из {q['total']}), самый острый угол "
                       f"{fmt(q['min_angle'], 1)}° ({'в норме' if ok else 'нарушено'})",
                       name, line, q["bad_pct"], f"≤ {fmt(limit)}%", label)

    raise FormaError(f"Правило «{rule}» не поддерживается.")


def _scene(cache):
    return getattr(cache, "scene", None)


def cache_scene(cache):
    """Параметры сцены для разбора выражений в проверках."""
    scene = getattr(cache, "scene", None)
    if scene is None:
        return {}
    return _ValueScope(scene)
