#!/usr/bin/env python3
"""
new_project.py — создать новый проект по золотому стандарту SPECIALS.

Что делает:
  1. копирует SPECIALS/template целиком (app.py, start.vbs, stop.vbs, …);
  2. подставляет в app.py: APP_ID, APP_NAME, APP_LETTER, версию и блок портов;
  3. подставляет в readme.txt: имя, версию, диапазон портов;
  4. копирует библиотеку SPECIALS/appcore в проект (проект остаётся самодостаточным:
     его можно переносить и отдавать одним архивом, без зависимости от репозитория);
  5. добавляет проект в SPECIALS/ports.json (чтобы порты не пересекались) и кладёт
     его собственный tiny-ports.json внутрь проекта — appcore читает файл рядом с
     собой, поэтому проект знает свой блок даже вне репозитория.

Примеры:
    python SPECIALS/tools/new_project.py "Мой Трекер"
    python SPECIALS/tools/new_project.py "Recipe Box" --port-base 5030 --id cooker
    python SPECIALS/tools/new_project.py "Игра" --dir ../games/игра --no-register

Без зависимостей, Python 3.8+.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SPECIALS = Path(__file__).resolve().parents[1]
TEMPLATE = SPECIALS / "template"
APPCORE = SPECIALS / "appcore"
REGISTRY = SPECIALS / "ports.json"

# Свободные зоны для новых проектов (см. docs/PORTS.md): 5120-5599 и 8020-8999.
AUTO_ZONE_START, AUTO_ZONE_END = 5120, 5599
RESERVED = {5120}          # 5120 занят эталонным Specials Demo


def app_id_from_name(name: str) -> str:
    """«Мой Трекер» → my_tracker (латиница/цифры/_, без транслита зависимостей)."""
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya",
    }
    lowered = name.lower()
    result = "".join(translit.get(ch, ch) for ch in lowered)
    result = re.sub(r"[^a-z0-9]+", "_", result).strip("_")
    if not result or result[0].isdigit():
        result = "app_" + result
    return result[:40]


def used_ports() -> set[int]:
    ports: set[int] = set()
    try:
        raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
        for block in raw.get("blocks", []):
            base = int(block.get("base", 0))
            size = int(block.get("size", 10))
            if base:
                ports.update(range(base, base + size))
    except Exception:
        pass
    return ports


def pick_free_block(port_base: int | None) -> int:
    used = used_ports() | RESERVED
    if port_base:
        if any(port in used for port in range(port_base, port_base + 10)):
            print(f"! Блок {port_base}-{port_base + 9} уже занят в ports.json — подберу свободный")
        else:
            return port_base
    for base in range(AUTO_ZONE_START, AUTO_ZONE_END, 10):
        if all(port not in used for port in range(base, base + 10)):
            return base
    raise SystemExit("Свободных блоков в зоне 5120-5599 нет — укажите --port-base вручную")


def register_block(app_id: str, name: str, base: int, project_dir: Path) -> None:
    """Добавляет блок в SPECIALS/ports.json, НЕ переформатируя чужой файл.

    Файл-реестр читают и люди, и скрипты: он написан «одна строка — один блок».
    Поэтому новая запись вставляется строкой, а существующая правится на месте.
    """
    try:
        raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        raw = {"version": 1, "blocks": []}
    try:
        relative = project_dir.relative_to(SPECIALS.parent).as_posix()
    except ValueError:
        relative = project_dir.as_posix()
    entry = {"app_id": app_id, "name": name, "base": base, "size": 10,
             "current_file": f"{relative}/app.py", "note": "создан new_project.py"}
    text = REGISTRY.read_text(encoding="utf-8")
    line = "    " + json.dumps(entry, ensure_ascii=False) + ","
    lines = text.splitlines()
    replaced = False
    for index, existing in enumerate(lines):
        if f'"app_id": "{app_id}"' in existing:
            lines[index] = line
            replaced = True
            break
    if not replaced:
        for index, existing in enumerate(lines):
            if existing.strip() == '"blocks": [':
                lines.insert(index + 1, line)
                break
        else:
            print("! В ports.json нет секции blocks — регистрация пропущена")
            return
    REGISTRY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:                                    # проверяем, что файл остался валидным JSON
        json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"! ports.json получился невалидным ({exc}) — верните файл из git")
        return
    # Реестр дублируется ВНУТРЬ проекта: appcore ищет ports.json рядом с собой,
    # поэтому без этой копии проект не знал бы свой блок (и брал случайный по хэшу).
    own = {
        "_комментарий": "Блок портов этого проекта. Полный реестр — SPECIALS/ports.json.",
        "version": 1,
        "blocks": [entry],
    }
    (project_dir / "ports.json").write_text(
        json.dumps(own, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def patch(path: Path, replacements: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Новый проект по стандарту SPECIALS")
    parser.add_argument("name", help="человеческое имя проекта, напр. «Мой Трекер»")
    parser.add_argument("--id", dest="app_id", default=None, help="машинный id (по умолчанию из имени)")
    parser.add_argument("--dir", dest="target", default=None, help="куда создать (по умолчанию ../Имя)")
    parser.add_argument("--port-base", type=int, default=None, help="основной порт блока")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--no-appcore", action="store_true",
                        help="не копировать appcore (если он будет общим)")
    parser.add_argument("--no-register", action="store_true", help="не трогать ports.json")
    parser.add_argument("--force", action="store_true", help="писать в непустую папку")
    args = parser.parse_args(argv)

    name = args.name.strip()
    app_id = (args.app_id or app_id_from_name(name)).strip()
    base = pick_free_block(args.port_base)
    target = Path(args.target).resolve() if args.target else (SPECIALS.parent / name)
    letter = next((ch for ch in name if ch.isalnum()), "A").upper()

    if not TEMPLATE.exists():
        raise SystemExit(f"Нет шаблона {TEMPLATE}")
    if target.exists() and any(target.iterdir()) and not args.force:
        raise SystemExit(f"Папка {target} не пуста. Используйте --force или другой --dir")

    # 1) копируем шаблон (без сгенерированных данных и логов)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "logs", "*.pyc",
                                                  "port.txt", "notes.json", "settings.json",
                                                  "shared"))
    (target / "data").mkdir(exist_ok=True)
    (target / "data" / ".gitkeep").touch()

    # 2) подставляем паспорт приложения
    patch(target / "app.py", {
        'APP_ID = "specials_demo"': f'APP_ID = "{app_id}"',
        'APP_NAME = "Specials Demo"': f'APP_NAME = "{name}"',
        'APP_VERSION = "1.0.0"': f'APP_VERSION = "{args.version}"',
        'APP_LETTER = "S"': f'APP_LETTER = "{letter}"',
    })
    patch(target / "readme.txt", {
        "{{APP_NAME}}": name,
        "{{VERSION}}": args.version,
        "{{PORT_BASE}}": str(base),
        "{{PORT_END}}": str(base + 9),
    })

    # 3) appcore — внутрь проекта (самодостаточность важнее «единого источника»)
    if not args.no_appcore and APPCORE.exists():
        shutil.copytree(APPCORE, target / "appcore", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # 4) регистрируем блок портов
    if not args.no_register:
        register_block(app_id, name, base, target)

    print(f"Проект создан: {target}")
    print(f"  app_id     : {app_id}")
    print(f"  блок портов: {base}-{base + 9}")
    print(f"  appcore    : {'не копировался' if args.no_appcore else 'скопирован в проект'}")
    print()
    print("Дальше:")
    print(f"  1. cd \"{target}\"")
    print("  2. python -m pip install -r requirements.txt")
    print("  3. start_debug.bat — первый запуск с консолью (видно ошибки)")
    print("  4. start.vbs — обычный запуск; интерфейс откроется сам")
    print("  5. впишите свою логику в app.py и templates/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
