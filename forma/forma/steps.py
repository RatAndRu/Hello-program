"""Шаг в стек объекта: одна операция поверх готовой детали.

Стек объекта в панели — это строки сценария, у которых слева то же имя. Шаг
добавляет ещё одну такую строку: объединить, вычесть, повернуть, покрасить.
Никакого второго хранилища нет — шаг становится текстом `.forma`, и если
сценарий после него не собирается, текст возвращается к прежнему виду.

Каталог шагов объявлен здесь один раз: сервер по нему строит строку, клиент —
поля. Ни регулярных выражений, ни подстановок по шаблону со скобками: строка
складывается из проверенных значений.
"""

from __future__ import annotations

from .dsl import parse_script
from .errors import FormaError

# Поля описывают то, что видно в интерфейсе: название, вид значения, умолчание.
# kind: object — имя готовой детали, number — число, vec3 — три числа,
#       axis/plane — перечисление, color — цвет #rrggbb, text — строка.
STEPS: list[dict] = [
    {
        "op": "union",
        "title": "Объединить с деталью",
        "hint": "Сливает выбранный объект и другую деталь в одно тело с тем же именем.",
        "fields": [
            {"k": "other", "label": "деталь", "kind": "object", "required": True},
        ],
    },
    {
        "op": "difference",
        "title": "Вычесть деталь",
        "hint": "Вырезает форму второй детали из выбранного объекта.",
        "fields": [
            {"k": "other", "label": "вычесть", "kind": "object", "required": True},
        ],
    },
    {
        "op": "intersect",
        "title": "Оставить общее",
        "hint": "Оставляет только пересечение двух деталей.",
        "fields": [
            {"k": "other", "label": "пересечь с", "kind": "object", "required": True},
        ],
    },
    {
        "op": "weld",
        "title": "Сварить с деталью",
        "hint": "Объединяет детали и скругляет вогнутый стык радиусом сварки.",
        "fields": [
            {"k": "other", "label": "деталь", "kind": "object", "required": True},
            {"k": "tolerance", "label": "зазор", "kind": "number", "default": 0.05},
        ],
    },
    {
        "op": "translate",
        "title": "Сдвинуть",
        "hint": "Переносит объект на вектор — без поворотов и чужих осей.",
        "fields": [
            {"k": "offset", "label": "смещение", "kind": "vec3", "default": [10, 0, 0]},
        ],
    },
    {
        "op": "rotate",
        "title": "Повернуть",
        "hint": "Поворот вокруг оси сцены: +Z верх, +X право, −Y перед.",
        "fields": [
            {"k": "angle", "label": "угол, °", "kind": "number", "default": 90},
            {"k": "axis", "label": "ось", "kind": "axis", "default": "z"},
        ],
    },
    {
        "op": "scale",
        "title": "Масштаб",
        "hint": "Растягивает объект по осям сцены.",
        "fields": [
            {"k": "factor", "label": "множители", "kind": "vec3", "default": [1, 1, 1.25]},
        ],
    },
    {
        "op": "slice",
        "title": "Разрезать",
        "hint": "Оставляет верхнюю или нижнюю часть по плоскости реза.",
        "fields": [
            {"k": "axis", "label": "ось", "kind": "axis", "default": "z"},
            {"k": "at", "label": "высота реза", "kind": "number", "default": 0},
            {"k": "keep", "label": "оставить", "kind": "keep", "default": "top"},
        ],
    },
    {
        "op": "color",
        "title": "Покрасить",
        "hint": "Меняет цвет и материал детали, не трогая геометрию.",
        "fields": [
            {"k": "color", "label": "цвет", "kind": "color", "default": "#c9d1e3"},
            {"k": "material", "label": "материал", "kind": "text", "default": "plastic"},
        ],
    },
]

CATALOG: dict[str, dict] = {entry["op"]: entry for entry in STEPS}

AXES = {"x", "y", "z"}
KEEP = {"top", "bottom"}
HEX = set("0123456789abcdefABCDEF")


def catalog() -> list[dict]:
    """Каталог для интерфейса: без функций и без внутренних полей."""
    return [{"op": entry["op"], "title": entry["title"], "hint": entry["hint"],
             "fields": [dict(field) for field in entry["fields"]]} for entry in STEPS]


def _num(value, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise FormaError(f"«{field}» — это должно быть число.", param=field)


def number_text(value: float) -> str:
    """Число так, как его приятно видеть в сценарии: 90, 0.05, 12.5."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _vec3(value, field: str) -> str:
    if isinstance(value, str):
        parts = value.replace(",", " ").split()
    else:
        parts = list(value or [])
    if len(parts) != 3:
        raise FormaError(f"«{field}» — нужны три числа.", param=field)
    return "[" + ", ".join(number_text(_num(item, field)) for item in parts) + "]"


def _color(value, field: str) -> str:
    text = str(value or "").strip()
    if len(text) != 7 or not text.startswith("#") or any(ch not in HEX for ch in text[1:]):
        raise FormaError(f"«{field}» — цвет вида #rrggbb.", param=field)
    return text.lower()


def _word(value, field: str, allowed: set[str]) -> str:
    text = str(value or "").strip().lower()
    if text not in allowed:
        raise FormaError(f"«{field}»: допустимо {', '.join(sorted(allowed))}.", param=field)
    return text


def build_line(op: str, target: str, values: dict | None = None) -> str:
    """Строка сценария для шага. Единственное место, где она складывается."""
    entry = CATALOG.get(str(op or "").strip().lower())
    if entry is None:
        raise FormaError(f"Неизвестный шаг «{op}».")
    name = str(target or "").strip()
    if not name:
        raise FormaError("Шаг добавляется к объекту: не выбрано имя.")
    values = values or {}
    other = str(values.get("other") or "").strip()
    if entry["op"] in {"union", "difference", "intersect", "weld"}:
        if not other:
            raise FormaError("Укажите вторую деталь.", param="other")
        if other == name:
            raise FormaError("Деталь нельзя применить к самой себе.", param="other")
    if entry["op"] == "union":
        return f"{name} = union [{name}, {other}]"
    if entry["op"] == "difference":
        return f"{name} = difference [{name}, {other}]"
    if entry["op"] == "intersect":
        return f"{name} = intersect [{name}, {other}]"
    if entry["op"] == "weld":
        tolerance = number_text(_num(values.get("tolerance", 0.05), "tolerance"))
        return f"{name} = weld [{name}, {other}] tolerance={tolerance}"
    if entry["op"] == "translate":
        return f"translate [{name}] offset={_vec3(values.get('offset', [10, 0, 0]), 'offset')}"
    if entry["op"] == "rotate":
        angle = number_text(_num(values.get("angle", 90), "angle"))
        axis = _word(values.get("axis", "z"), "axis", AXES)
        return f"rotate [{name}] angle={angle} axis={axis}"
    if entry["op"] == "scale":
        return f"scale [{name}] factor={_vec3(values.get('factor', [1, 1, 1]), 'factor')}"
    if entry["op"] == "slice":
        axis = _word(values.get("axis", "z"), "axis", AXES)
        at = number_text(_num(values.get("at", 0), "at"))
        keep = _word(values.get("keep", "top"), "keep", KEEP)
        return f"{name} = slice [{name}] axis={axis} at={at} keep={keep}"
    if entry["op"] == "color":
        color = _color(values.get("color", "#c9d1e3"), "color")
        material = str(values.get("material") or "").strip()
        tail = f" material={material}" if material else ""
        return f"color {name} {color}{tail}"
    raise FormaError(f"Шаг «{op}» пока не умеет собирать строку.")


def _tokens(values) -> list[str]:
    """Имена объектов из значения: [a, b], a или «a» — без регулярных выражений."""
    out: list[str] = []
    for raw in values or ():
        text = str(raw)
        for chunk in text.replace(",", " ").replace("[", " ").replace("]", " ").split():
            out.append(chunk.strip("'\""))
    return out


def _mentions(command, name: str) -> bool:
    values = list(getattr(command, "args", None) or [])
    values += list((getattr(command, "kwargs", None) or {}).values())
    return name in _tokens(values)


# Слова, которые меняют готовый объект на месте: такие строки — продолжение
# его стека, а не «использование». Остальные упоминания имени считаются
# использованием: шаг обязан стоять выше них.
IN_PLACE = {"translate", "rotate", "scale", "color", "paint", "hide", "show",
            "texture", "кисть", "ластик", "pattern"}


def insertion_index(script: str, target: str, other: str | None = None) -> int | None:
    """Куда поставить шаг: после деталей и своего стека, но до первого использования.

    Шаг меняет объект, поэтому он обязан стоять ниже строк, создающих и его
    самого, и вторую деталь. Ниже — всех собственных шагов: стек растёт вниз.
    И выше первой строки, которая пользуется объектом: иначе группа, проверка
    или булева операция увидят старую форму.
    """
    try:
        commands = parse_script(str(script or ""))
    except Exception:  # синтаксис ещё не готов — подскажет клиент
        return None
    lines = str(script or "").splitlines()
    anchor = 0
    for command in commands:
        last = getattr(command, "last_line", None) or command.line
        if command.target == target or (other and command.target == other):
            anchor = max(anchor, last)
    if not anchor:
        return None
    for command in commands:
        if command.line <= anchor:
            continue
        last = getattr(command, "last_line", None) or command.line
        verb = str(getattr(command, "verb", "") or "").lower()
        if command.target == target or (verb in IN_PLACE and _mentions(command, target)):
            anchor = max(anchor, last)
            continue
        if _mentions(command, target):
            return max(anchor, command.line - 1)
    return min(anchor, len(lines))


def append_step(script: str, target: str, op: str, values: dict | None = None,
                after_line: int | None = None) -> dict:
    """Возвращает новый текст сценария с одной добавленной строкой.

    Сама сборка — дело вызывающего: он проверяет сценарий и только потом
    отдаёт текст в редактор. Здесь текст не меняется ни при какой ошибке.
    """
    line = build_line(op, target, values)
    lines = str(script or "").splitlines()
    other = str((values or {}).get("other") or "").strip() or None
    index = insertion_index(script, str(target).strip(), other)
    if index is None:
        # Разбор не удался или объект создан не в этом тексте (include, блок):
        # тогда работаем по подсказке клиента, а иначе — в конец.
        index = len(lines)
        if isinstance(after_line, int) and 1 <= after_line <= len(lines):
            index = after_line
    index = max(0, min(index, len(lines)))
    lines.insert(index, line)
    text = "\n".join(lines).rstrip("\n") + "\n"
    return {"ok": True, "script": text, "line": line, "line_number": index + 1,
            "object": str(target).strip(), "op": str(op).strip().lower()}
