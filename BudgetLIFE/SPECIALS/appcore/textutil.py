"""
textutil.py — текстовые утилиты, которые нужны почти любому приложению.

Взято из DeployAgent (текстовые помощники для буфера обмена: смена раскладки,
регистр, безопасный калькулятор, HEX-цвет, чистка ссылок) и BLIND_PC (разбор
русских числительных в голосовых командах, «человеческий» размер файла).

ПОЧЕМУ ЭТО ЗДЕСЬ, А НЕ В КАЖДОМ ПРОЕКТЕ
---------------------------------------
Это ровно те «мелочи», ради которых обычно копируют куски кода между проектами,
и ровно тот код, где легко наделать ошибок:

  * перевод раскладки RU↔EN нельзя делать через str.translate «по буквам» наивно:
    надо отсеивать пути, URL, код, хештеги и текст, где букв меньше 70 %;
  * считать выражение из буфера обмена через eval() — дыра в безопасности
    (любой может подсунуть `__import__("os").system(...)`);
  * имя файла из чужого текста («../../windows/system32/cmd.exe») — классический
    выход за пределы папки данных.

Всё это — чистые функции без зависимостей, их можно вызывать из любого потока.
"""

from __future__ import annotations

import ast
import math
import os
import re
import unicodedata
from pathlib import Path

# ── раскладка RU ↔ EN ───────────────────────────────────────────────────────
# Раскладки «ЙЦУКЕН» и QWERTY: позиции клавиш совпадают, поэтому текст можно
# «перепечатать» в другую раскладку простым отображением символов.
_EN_TO_RU = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?"
    "`~@#$^&",
    "йцукенгшщзхъфывапролджэячсмитьбю.ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,"
    "ёЁ\"№;:?",
)
_RU_TO_EN = str.maketrans(
    "йцукенгшщзхъфывапролджэячсмитьбю.ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,"
    "ёЁ\"№;:?",
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>?"
    "`~@#$^&",
)

_RE_CYR = re.compile(r"[а-яё]", re.I)
_RE_LAT = re.compile(r"[a-z]", re.I)
_RE_FILENAME_EXT = re.compile(r"^[\w\-. ]+\.[A-Za-z0-9]{1,6}$")
_RE_CODE_SYMBOLS = re.compile(r"[{}<>;$|\\`=~^\[\]]")


def switch_layout(text: str) -> str | None:
    """Переводит текст в другую раскладку (``ghbdtn`` ↔ ``привет``).

    Возвращает None, если текст не похож на «забыл переключить язык»:
    пути и URL, имена файлов, код, хештеги, строки с цифрами и знаками.

    Приём DeployAgent: главное здесь — не мешать. Лучше не предложить замену,
    чем испортить пользователю путь к файлу или кусок кода.
    """
    text = str(text or "")
    if not text.strip():
        return None
    stripped = text.strip()
    if "/" in text or "\\" in text:
        return None
    if stripped.lower().startswith(("http:", "https:", "ftp:")):
        return None
    if _RE_FILENAME_EXT.match(stripped):
        return None
    if stripped.startswith("#"):
        return None
    if _RE_CODE_SYMBOLS.search(text):
        return None
    letters = sum(1 for char in stripped if char.isalpha())
    if letters < len(stripped) * 0.7:
        return None
    has_cyr, has_lat = bool(_RE_CYR.search(text)), bool(_RE_LAT.search(text))
    if has_cyr and not has_lat:
        return text.translate(_RU_TO_EN)
    if has_lat and not has_cyr:
        return text.translate(_EN_TO_RU)
    return None


# ── регистр ─────────────────────────────────────────────────────────────────

def is_broken_case(text: str) -> bool:
    """True для «кривого» регистра: ``пРИВЕТ``, ``СлОВО``, ``ПРИВЕТ привет``."""
    text = str(text or "")
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 2:
        return False
    if text == text.lower() or text == text.upper() or text == text.capitalize():
        return False
    words = [word for word in text.split() if any(char.isalpha() for char in word)]
    if not words:
        return False
    styles = set()
    for word in words:
        if word == word.lower():
            styles.add("lower")
        elif word == word.upper():
            styles.add("upper")
        elif word == word.capitalize():
            styles.add("title")
        else:
            return True                      # внутри слова регистр перемешан
    return styles == {"upper", "lower"} and len(words) > 1


def case_variants(text: str) -> list[tuple[str, str]]:
    """Варианты регистра, если текст «кривой»: [("нижний", ...), ...]."""
    if not is_broken_case(text):
        return []
    return [("нижний", text.lower()), ("Первая заглавная", text.capitalize()),
            ("ВЕРХНИЙ", text.upper())]


# ── безопасный калькулятор ──────────────────────────────────────────────────

MATH_MAX_LENGTH = 60
MATH_MAX_AST_NODES = 40
MATH_MAX_ABS = 1e15

# Разрешены только эти функции: ни eval, ни getattr, ни импортов.
_MATH_FUNCTIONS: dict[str, object] = {
    "abs": abs, "round": round, "min": min, "max": max, "pow": pow, "int": int,
    "float": float, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "log": math.log, "log10": math.log10, "exp": math.exp,
    "floor": math.floor, "ceil": math.ceil, "pi": math.pi, "e": math.e,
}
_RE_MATH_WORDS = [
    (re.compile(r"\bплюс\b"), "+"), (re.compile(r"\bминус\b"), "-"),
    (re.compile(r"\bумножить на\b"), "*"), (re.compile(r"\bумножить\b"), "*"),
    (re.compile(r"\bразделить на\b"), "/"), (re.compile(r"\bделить на\b"), "/"),
    (re.compile(r"\bв степени\b"), "**"),
]
_RE_MATH_DIGITS = re.compile(r"(\d)\s*[xх*]\s*(\d)", re.I)
_RE_MATH_CLEAN = re.compile(r"[^0-9a-zA-Zа-яё_+\-*/%.,()= ]")


def _checked_math_value(value: object) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("нужен числовой результат")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("бесконечный результат")
    if abs(value) > MATH_MAX_ABS:
        raise ValueError("слишком большой результат")
    return value


def _eval_math_node(node: ast.AST) -> float | int:
    """Вычисляет только разрешённые узлы AST (без eval — так безопасно)."""
    if isinstance(node, ast.Expression):
        return _eval_math_node(node.body)
    if isinstance(node, ast.Constant):
        return _checked_math_value(node.value)
    if isinstance(node, ast.BinOp):
        left, right = _eval_math_node(node.left), _eval_math_node(node.right)
        if isinstance(node.op, ast.Add):
            return _checked_math_value(left + right)
        if isinstance(node.op, ast.Sub):
            return _checked_math_value(left - right)
        if isinstance(node.op, ast.Mult):
            return _checked_math_value(left * right)
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("деление на ноль")
            return _checked_math_value(left / right)
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise ValueError("деление на ноль")
            return _checked_math_value(left % right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > 64 or (abs(left) > 1 and right > 64):
                raise ValueError("слишком большая степень")
            return _checked_math_value(left ** right)
        raise ValueError("недопустимая операция")
    if isinstance(node, ast.UnaryOp):
        value = _eval_math_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise ValueError("недопустимая операция")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _MATH_FUNCTIONS:
            raise ValueError("недопустимая функция")
        args = [_eval_math_node(arg) for arg in node.args]
        return _checked_math_value(_MATH_FUNCTIONS[node.func.id](*args))  # type: ignore[operator]
    if isinstance(node, ast.Name):
        if node.id in _MATH_FUNCTIONS:
            value = _MATH_FUNCTIONS[node.id]
            if isinstance(value, (int, float)):
                return value
        raise ValueError("неизвестное имя")
    raise ValueError("недопустимое выражение")


def _normalize_math_expression(expression: str) -> str:
    text = str(expression).strip().lower().replace(",", ".")
    for pattern, replacement in _RE_MATH_WORDS:
        text = pattern.sub(replacement, text)
    text = _RE_MATH_DIGITS.sub(r"\1*\2", text)
    text = re.sub(r"(?<=[\d)])\s*\(", "*(", text)        # 2(3+4) → 2*(3+4)
    text = text.rstrip("= ").strip()
    return text


def safe_eval_math(expression: str) -> str | None:
    """Безопасно вычисляет «человеческое» выражение, не используя eval().

    Примеры: ``2+2*2`` → ``"6"``, ``сколько будет 10% от 200``? — нет, проценты
    не поддерживаются намеренно. А вот ``2 x 3``, ``10 / 4``, ``sqrt(16)``,
    ``2 в степени 10`` — работают. None, если это не выражение.

    Приём DeployAgent («буфер обмена посчитал за меня»): подходит для оверлеев,
    голосовых команд («посчитай 2 плюс 2») и умных полей ввода.
    """
    if not isinstance(expression, str):
        return None
    raw = expression.strip()
    if not raw or len(raw) > MATH_MAX_LENGTH:
        return None
    raw = _RE_MATH_CLEAN.sub("", raw)
    if not raw:
        return None
    normalized = _normalize_math_expression(expression)
    if not normalized:
        return None
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError:
        return None
    nodes = list(ast.walk(tree))
    # Просто число — не вычисление (иначе оверлей будет всплывать от каждой цифры)
    if len(nodes) > MATH_MAX_AST_NODES:
        return None
    if not any(isinstance(node, (ast.BinOp, ast.Call)) for node in nodes):
        return None
    try:
        return format_math_result(_eval_math_node(tree))
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None


def format_math_result(value: float | int) -> str:
    """Аккуратно печатает результат: без ``0.30000000000000004``.

    Десятичный разделитель — запятая (русская запись): «10 / 4» → «2,5».
    """
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.10g}".replace(".", ",")
    return str(value)


# ── цвета ───────────────────────────────────────────────────────────────────

def parse_hex_color(text: str) -> tuple[int, int, int] | None:
    """``#3fa9f5`` / ``3fa9f5`` / ``#abc`` → (r, g, b) либо None."""
    text = str(text or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return None
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def rgb_to_hsl(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """(r, g, b) → (h 0..360, s 0..1, l 0..1). Нужно для «подбери цвет темы»."""
    red, green, blue = (max(0, min(255, int(part))) / 255 for part in rgb)
    maximum, minimum = max(red, green, blue), min(red, green, blue)
    lightness = (maximum + minimum) / 2
    if maximum == minimum:
        return 0.0, 0.0, lightness
    delta = maximum - minimum
    saturation = delta / (2 - maximum - minimum) if lightness > 0.5 else delta / (maximum + minimum)
    if maximum == red:
        hue = (green - blue) / delta + (6 if green < blue else 0)
    elif maximum == green:
        hue = (blue - red) / delta + 2
    else:
        hue = (red - green) / delta + 4
    return hue * 60, saturation, lightness


# ── ссылки и имена файлов ───────────────────────────────────────────────────

def clean_url(text: str) -> str | None:
    """Из «мусорной» строки достаёт ``http(s)://host`` или None.

    Путь, параметры, якорь, логин/пароль и порт отбрасываются намеренно: нужен
    именно домен (приём DeployAgent — «вставить чистую ссылку»). Домен не
    проверяется по списку зон: есть IDN, IPv4/IPv6 и любые новые TLD.

    Примеры: ``«смотри https://github.com/user/repo?x=1#z»`` → ``https://github.com``,
    ``example.com/page`` → ``https://example.com``.
    """
    from urllib.parse import urlsplit
    raw = str(text or "").strip()
    if not raw:
        return None
    match = re.search(r"https?://[^\s<>\"'«»()]+", raw)
    if match:
        candidate = match.group(0).rstrip(".,;:!?")
    else:
        # Голый домен: только если вся строка похожа на адрес (иначе это текст)
        plain = raw.strip("<>\"'").rstrip(".,;:!?")
        if not re.fullmatch(r"[A-Za-z0-9][\w.-]*\.[A-Za-z]{2,}(/[^\s]*)?", plain):
            return None
        candidate = "https://" + plain
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname
    if "." not in host and host != "localhost":
        return None
    return f"{parts.scheme}://{host}"


def sanitize_filename(name: str, *, fallback: str = "file", max_length: int = 120) -> str:
    """Безопасное имя файла: без путей, ``..``, запрещённых символов Windows.

    Используется там, где имя приходит извне (принятый «Поделиться» файл,
    загруженная картинка, название из чужого текста). Без этого ``Path(name).name``
    спасает не всегда: на Windows имя ``CON``/``NUL``/``com1`` тоже запрещено.
    """
    raw = str(name or "").replace("\\", "/").split("/")[-1]
    raw = unicodedata.normalize("NFKC", raw).strip().strip(".")
    raw = re.sub(r'[<>:"|?*\x00-\x1f]', "_", raw)
    raw = re.sub(r"\s+", " ", raw)
    if not raw or raw in {".", ".."}:
        return fallback
    reserved = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                *(f"lpt{i}" for i in range(1, 10))}
    if Path(raw).stem.lower() in reserved:
        raw = "_" + raw
    if len(raw) > max_length:
        stem, dot, suffix = raw.rpartition(".")
        keep = max_length - (len(suffix) + 1 if dot else 0)
        raw = (stem[:keep].rstrip() + (dot + suffix if dot else "")) if keep > 0 \
            else raw[:max_length]
    return raw or fallback


def human_size(size: float) -> str:
    """1234567 → «1,18 МБ» (приём bridge/Cooker: показывать людям, а не байты)."""
    value = float(size or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if value < 1024 or unit == "ТБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.2f} {unit}".replace(".", ",")
        value /= 1024
    return f"{value:.2f} ТБ"


def strip_html(text: str) -> str:
    """Грубая очистка HTML → текст (для парсеров страниц, как в LanguageYOI)."""
    raw = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", str(text or ""))
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = (raw.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
           .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    raw = re.sub(r"[ \t]+", " ", raw)
    return re.sub(r"\n{3,}", "\n\n", raw).strip()


# ── русские числительные (голосовые команды) ────────────────────────────────

_UNITS = {
    "ноль": 0, "один": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
    "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
    "девятнадцать": 19,
}
_TENS = {
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "семьдесят": 70, "восемьдесят": 80, "девяносто": 90,
}
_HUNDREDS = {
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
_THOUSAND = {"тысяча", "тысячи", "тысяч"}


def words_to_number(text: str) -> int | None:
    """«сто двадцать три» → 123. Приём BLIND_PC (голосовые команды, напоминания).

    Понимает единицы, десятки, сотни и тысячи в пределах одного числа.
    Для распознавания речи этого достаточно: «напомни через двадцать минут».
    """
    words = re.findall(r"[а-яё]+", str(text or "").lower())
    if not words:
        return None
    total = 0
    current = 0
    found = False
    for word in words:
        if word in _UNITS:
            current += _UNITS[word]
            found = True
        elif word in _TENS:
            current += _TENS[word]
            found = True
        elif word in _HUNDREDS:
            current += _HUNDREDS[word]
            found = True
        elif word in _THOUSAND:
            total += max(current, 1) * 1000
            current = 0
            found = True
        elif found:
            break                        # «двадцать минут» — на «минут» заканчиваем
    return total + current if found else None


def numbers_in_text(text: str) -> list[int]:
    """Вытаскивает числа из строки: и цифрами («через 15 минут»), и словами."""
    raw = str(text or "")
    result = [int(match) for match in re.findall(r"\d+", raw)]
    if result:
        return result
    number = words_to_number(raw)
    return [number] if number is not None else []


def resolve_data_path(base: str | os.PathLike, *parts: str) -> Path:
    """Путь внутри папки данных с защитой от выхода наружу (``..`` из текста)."""
    root = Path(base)
    candidate = root.joinpath(*[sanitize_filename(part) for part in parts])
    resolved = candidate.resolve()
    if not str(resolved).startswith(str(root.resolve())):
        raise ValueError(f"Путь выходит за пределы папки данных: {candidate}")
    return resolved
