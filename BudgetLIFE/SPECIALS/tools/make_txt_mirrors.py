#!/usr/bin/env python3
"""
make_txt_mirrors.py — .txt-копии исходников рядом с файлами.

В этом репозитории исторически принято держать рядом с `app.py` его копию
`app.txt` (то же для `start.txt`, `shared.txt`, `prompt_templates.txt`): такие
копии удобно отдавать нейросети одним «плоским» текстом, их не портит подсветка
и они не требуют архива. Минус — копии быстро устаревают.

Этот скрипт обновляет копии: для каждого файла-источника создаёт `<имя>.txt`
(или обновляет, если содержимое изменилось).

Запуск:
    python SPECIALS/tools/make_txt_mirrors.py                 # весь репозиторий
    python SPECIALS/tools/make_txt_mirrors.py --root Cooker    # только проект
    python SPECIALS/tools/make_txt_mirrors.py --check          # только проверить (код 1, если отстают)
    python SPECIALS/tools/make_txt_mirrors.py --clean          # удалить все зеркала

По умолчанию зеркалятся: .py, .vbs, .bat, .html, .css, .js (без vendor/node_modules).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MIRROR_SUFFIXES = {".py", ".vbs", ".bat", ".html", ".css", ".js"}
# По умолчанию зеркало — ТОЧНАЯ копия файла (так уже сделано в репозитории:
# app.py → app.txt). Флаг --header добавит строку-маркер сверху.
HEADER = "===== ЗЕРКАЛО ФАЙЛА {name} (создано make_txt_mirrors.py, не редактировать) =====\n"
IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "build", "dist",
                "vendor", "logs", "_backup", "appcore"}
SKIP_NAMES = {"make_txt_mirrors.py", "check_ports.py", "audit_windows.py", "new_project.py"}


def should_skip(path: Path) -> bool:
    # .txt — это и есть зеркала, источники считаем только из MIRROR_SUFFIXES
    if path.suffix.lower() not in MIRROR_SUFFIXES:
        return True
    if path.name in SKIP_NAMES:
        return True
    if any(part in IGNORED_DIRS for part in path.parts):
        return True
    # сами зеркала и файлы, которые уже являются копиями кода
    if path.stem.endswith(" — копия"):
        return True
    return False


def mirror_path(path: Path) -> Path:
    return path.with_suffix(".txt")


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def expected_content(source: Path, header: bool = False) -> str | None:
    text = read_text(source)
    if text is None:
        return None
    return (HEADER.format(name=source.name) if header else "") + text


def process(root: Path, *, check: bool, clean: bool, header: bool = False,
            create_all: bool = False) -> dict[str, int]:
    """Обновляет зеркала. Возвращает счётчики: updated/stale/current/removed/missing."""
    stats = {"updated": 0, "stale": 0, "current": 0, "removed": 0, "missing": 0}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or should_skip(path):
            continue
        target = mirror_path(path)
        expected = expected_content(path, header)
        if expected is None:
            continue
        exists = target.exists()
        if clean:
            if exists:
                target.unlink()
                stats["removed"] += 1
            continue
        # По умолчанию обновляем ТОЛЬКО уже существующие зеркала (как принято в
        # репозитории: app.py → app.txt). --all создаёт зеркала для всех файлов.
        if not exists and not create_all:
            stats["missing"] += 1
            continue
        if exists and read_text(target) == expected:
            stats["current"] += 1
            continue
        if check:
            stats["stale"] += 1
            print(f"  устарело: {path}")
            continue
        try:
            target.write_text(expected, encoding="utf-8", newline="\n")
            stats["updated"] += 1
            print(f"  обновлено: {target}")
        except OSError as exc:
            print(f"  ошибка записи {target}: {exc}")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Обновить .txt-копии исходников")
    parser.add_argument("--root", default=None,
                        help="папка (по умолчанию — весь репозиторий, два уровня вверх)")
    parser.add_argument("--check", action="store_true", help="только проверить")
    parser.add_argument("--clean", action="store_true", help="удалить зеркала")
    parser.add_argument("--header", action="store_true",
                        help="добавить строку-маркер в начало зеркала")
    parser.add_argument("--all", action="store_true",
                        help="создать зеркала и для файлов, у которых их ещё нет")
    args = parser.parse_args(argv)

    default_root = Path(__file__).resolve().parents[2]
    root = (Path(args.root) if args.root else default_root).resolve()
    if not root.exists():
        print(f"Папка не найдена: {root}")
        return 2

    print(f"Зеркала .txt: {root}")
    stats = process(root, check=args.check, clean=args.clean,
                    header=args.header, create_all=args.all)
    if args.clean:
        print(f"Удалено зеркал: {stats['removed']}")
    elif args.check:
        print(f"Актуальны: {stats['current']}; устарели: {stats['stale']}; "
              f"без зеркала: {stats['missing']}")
        if stats["stale"]:
            print("Запустите без --check, чтобы обновить.")
    else:
        print(f"Обновлено: {stats['updated']}; уже актуальны: {stats['current']}; "
              f"без зеркала: {stats['missing']} (создать: --all)")
    return 1 if (args.check and stats["stale"]) else 0


if __name__ == "__main__":
    sys.exit(main())
