#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перекодирование .vbs-файлов проекта в понятный Windows формат.

ПОЧЕМУ ЭТО НУЖНО
----------------
Windows Script Host (wscript.exe/cscript.exe) понимает в .vbs только два
варианта: ANSI (системная кодовая страница) и UTF-16LE с BOM.
UTF-8 с BOM он НЕ понимает: три байта EF BB BF превращаются в мусор «ï»¿»
перед первой строкой, и запуск падает с ошибкой компиляции:

    Недопустимый знак / Invalid character (800A0408)

Поэтому после любого редактирования .vbs (особенно в редакторах на Linux,
Git и в веб-интерфейсах) файл нужно перекодировать. ANSI нам не подходит:
кириллица превратится в кракозябры на английской Windows. Остаётся UTF-16LE.

ИСПОЛЬЗОВАНИЕ
-------------
    python tools/vbs_encoding.py             # перекодировать все .vbs проекта
    python tools/vbs_encoding.py --check     # только проверить, не меняя файлы
    python tools/vbs_encoding.py --all       # включить и SPECIALS/template

Возвращаемые коды: 0 — всё в порядке, 1 — есть файлы не в UTF-16LE.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"node_modules", "dist", "dev-dist", ".git", "data", "logs", "coverage"}

UTF16_BOM = b"\xff\xfe"
UTF8_BOM = b"\xef\xbb\xbf"


def read_text(path: Path) -> str:
    """Читает файл, распознавая BOM (UTF-16LE/BE, UTF-8) и ANSI-фолбэк."""
    raw = path.read_bytes()
    if raw.startswith(UTF16_BOM):
        return raw.decode("utf-16-le")
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be")
    if raw.startswith(UTF8_BOM):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")   # старый ANSI-вариант


def to_utf16(text: str) -> bytes:
    """UTF-16LE + BOM и переводы строк CRLF — то, что ждёт WSH."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    return UTF16_BOM + normalized.encode("utf-16-le")


def find_files(include_specials: bool) -> list[Path]:
    files: list[Path] = []
    for path in BASE.rglob("*.vbs"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not include_specials and "SPECIALS" in path.parts:
            continue
        files.append(path)
    return sorted(files)


def main() -> int:
    args = sys.argv[1:]
    check_only = "--check" in args
    include_specials = "--all" in args

    files = find_files(include_specials)
    if not files:
        print("Не найдено ни одного .vbs-файла")
        return 0

    bad: list[Path] = []
    for path in files:
        raw = path.read_bytes()
        # В UTF-16LE байты CR и LF разделены нулями, поэтому проверяем по тексту
        if raw.startswith(UTF16_BOM):
            ok = "\n" not in raw.decode("utf-16-le", errors="replace").replace("\r\n", "")
        else:
            ok = False
        name = path.relative_to(BASE)
        if ok:
            print(f"  ok   {name}")
            continue
        bad.append(path)
        if check_only:
            print(f"  ПЛОХО {name} — не UTF-16LE с BOM (запуск упадёт с «Недопустимый знак»)")
            continue
        text = read_text(path)
        path.write_bytes(to_utf16(text))
        print(f"  исправлено {name} → UTF-16LE+BOM, CRLF")

    if bad and check_only:
        print(f"\nФайлов требуют перекодирования: {len(bad)}. Запустите без --check.")
        return 1
    if bad:
        print(f"\nПерекодировано файлов: {len(bad)}.")
    else:
        print("\nВсе .vbs уже в UTF-16LE с BOM.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
