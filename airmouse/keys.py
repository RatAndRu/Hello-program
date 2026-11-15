"""Горячие клавиши — независимо от раскладки (английская, русская, любая).

``cv2.waitKey`` возвращает код символа в *текущей* раскладке, причём на разных
бэкендах по-разному: Unicode-код (й = 1081), байт ANSI-кодировки Windows
(й = 233 в cp1251) или просто ASCII-код латинской клавиши. Раньше в коде
сравнивалось с ``ord("q")``, и на русской раскладке ничего не срабатывало.

Здесь клавиша описывается латинской буквой (её физическая позиция), а
совпадение проверяется по всем вариантам: латиница в обоих регистрах,
кириллица в Unicode, кириллица в cp1251.
"""

from __future__ import annotations

import string
from typing import Iterable, Set

# Клавиша (латинская буква или знак) -> та же клавиша в русской раскладке.
RU_LAYOUT: dict[str, str] = {
    "q": "й", "w": "ц", "e": "у", "r": "к", "t": "е", "y": "н", "u": "г",
    "i": "ш", "o": "щ", "p": "з", "[": "х", "]": "ъ",
    "a": "ф", "s": "ы", "d": "в", "f": "а", "g": "п", "h": "р", "j": "о",
    "k": "л", "l": "д", ";": "ж", "'": "э",
    "z": "я", "x": "ч", "c": "с", "v": "м", "b": "и", "n": "т", "m": "ь",
    ",": "б", ".": "ю", "/": ".", "`": "ё",
}

RU_TO_LATIN: dict[str, str] = {ru: en for en, ru in RU_LAYOUT.items()}

# Служебные коды, которые тоже стоит понимать: Esc, Tab, пробел.
SPECIAL: dict[str, tuple[int, ...]] = {
    "esc": (27,),
    "tab": (9,),
    "space": (32,),
}

# Всё, что больше — служебные клавиши (стрелки, F1..F12) в расширенных кодах
# OpenCV: их нельзя «нарезать» на байты, иначе стрелка влево станет «q».
_EXTENDED_FROM = 0xFF00


def to_latin(code: int) -> str:
    """Код из ``waitKey`` -> символ в нижнем регистре, переведённый в латиницу.

    Возвращает ``""``, если код не похож на печатный символ.
    """
    if not isinstance(code, int) or code < 0:
        return ""
    if code >= _EXTENDED_FROM:          # стрелки, F-клавиши, numpad-коды
        return ""

    ch = ""
    if 0x80 <= code <= 0xFF:
        # однобайтовый код Windows в cp1251: й = 233. Проверяем раньше, чем
        # chr(): chr(233) даёт «é» из latin-1, а нам нужна кириллица.
        try:
            ch = bytes([code]).decode("cp1251")
        except UnicodeDecodeError:
            ch = ""
    if not ch and 0x20 <= code < 0x110000:
        try:
            ch = chr(code)
        except ValueError:              # суррогаты
            ch = ""
    if not ch:
        return ""

    low = ch.lower()
    return RU_TO_LATIN.get(low, low)


def aliases(name: str) -> Set[int]:
    """Все коды, которыми может прийти клавиша ``name`` (``"q"``, ``"esc"``…)."""
    name = name.strip()
    if not name:
        return set()
    key = name.lower()
    if key in SPECIAL:
        return set(SPECIAL[key])

    out: Set[int] = set()
    for ch in (key, RU_LAYOUT.get(key, "")):
        if not ch:
            continue
        for variant in (ch, ch.upper()):
            out.add(ord(variant))
            try:
                raw = variant.encode("cp1251")
            except UnicodeEncodeError:
                continue
            if len(raw) == 1:           # Windows отдаёт байт ANSI-кодировки
                out.add(raw[0])
    return out


def matches(code: int, name: str) -> bool:
    """Нажата ли клавиша ``name`` (независимо от раскладки)."""
    if code is None or code < 0:
        return False
    key = name.lower()
    if key in SPECIAL:
        return (code & 0xFF) in SPECIAL[key] if code < _EXTENDED_FROM else False
    if code in aliases(key):
        return True
    return to_latin(code) == RU_TO_LATIN.get(key, key)


def matches_any(code: int, names: Iterable[str]) -> bool:
    return any(matches(code, n) for n in names)


def name_of(code: int) -> str:
    """Человеческое имя клавиши — для журнала и тестов."""
    key = to_latin(code)
    if key in RU_LAYOUT:
        return key.upper()
    for name, codes in SPECIAL.items():
        if (code & 0xFF) in codes and code < _EXTENDED_FROM:
            return name
    return ""


LETTERS = tuple(string.ascii_lowercase)
