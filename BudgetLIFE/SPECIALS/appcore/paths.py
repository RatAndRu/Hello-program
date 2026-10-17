"""
paths.py — единая структура папок проекта.

Стандарт каждого проекта (так устроены ВСЕ проекты пользователя):

    ИмяПроекта/
        app.py            ← точка входа (Flask + трей)
        start.vbs         ← тихий запуск без консоли
        stop.vbs          ← корректная остановка (по имени/пути, не «убить всех питонов»)
        start_debug.bat   ← запуск с консолью и паузой при ошибке
        requirements.txt
        readme.txt
        data/             ← ВСЁ изменяемое: json/db/port.txt/кэш  (можно удалить — не потеряется код)
        static/           ← картинки, иконки, sw.js-заготовки
        templates/        ← HTML
        logs/             ← логи (или log.txt рядом с app.py — исторически так у всех)

Ключевое правило: код и данные разделены. Пути НИКОГДА не хардкодятся
(`C:\\AI_Projects\\...` — так было в BLIND_PC/start.vbs и это единственный
проект, который нельзя просто перенести в другую папку).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def is_frozen() -> bool:
    """True, если код упакован в exe (PyInstaller и т.п.)."""
    return bool(getattr(sys, "frozen", False))


@dataclass(frozen=True)
class AppPaths:
    """Пути проекта. Создавать так: `paths = AppPaths.for_file(__file__)`."""

    base: Path          # папка проекта (или папка exe, если упакован)
    data: Path          # изменяемые данные
    static: Path        # статика для Flask
    templates: Path     # HTML-шаблоны
    logs: Path          # логи

    # ── создание ────────────────────────────────────────────────────────────

    @classmethod
    def for_file(cls, file_path: str | os.PathLike) -> "AppPaths":
        """Определяет папку проекта по файлу (app.py), а не по cwd!

        Почему не `Path.cwd()`: VBS-лаунчер, ярлык автозапуска и планировщик
        запускают процесс с разным рабочим каталогом. `__file__` — единственный
        надёжный ориентир.
        """
        if is_frozen():
            # В упакованном exe данные должны лежать РЯДОМ с exe, а не в _MEIPASS,
            # иначе они исчезнут при следующей распаковке.
            base = Path(sys.executable).resolve().parent
        else:
            base = Path(file_path).resolve().parent
        return cls.for_dir(base)

    @classmethod
    def for_dir(cls, base: str | os.PathLike) -> "AppPaths":
        base = Path(base).resolve()
        return cls(base=base, data=base / "data", static=base / "static",
                   templates=base / "templates", logs=base / "logs")

    # ── готовность ──────────────────────────────────────────────────────────

    def ensure(self) -> "AppPaths":
        """Создаёт обязательные папки. Вызывать при старте приложения.

        Всегда `exist_ok=True`: второй запуск и уже существующие папки — норма.
        """
        for folder in (self.base, self.data, self.static, self.templates, self.logs):
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError:
                # Папку может создать другой экземпляр — это не повод падать.
                pass
        return self

    # ── удобные файлы данных ────────────────────────────────────────────────

    def data_file(self, name: str) -> Path:
        """Путь к файлу в data/ (гарантированно не выйдет за пределы data)."""
        name = str(name).replace("\\", "/").lstrip("/")
        candidate = (self.data / name).resolve()
        try:
            candidate.relative_to(self.data.resolve())
        except ValueError:
            raise ValueError(f"Недопустимое имя файла данных: {name!r}") from None
        return candidate

    def log_file(self, name: str = "log.txt") -> Path:
        """Основной лог проекта: `logs/log.txt`."""
        return self.logs / name

    def resource(self, *parts: str) -> Path:
        """Путь к ресурсу рядом с кодом (static/…): может только читаться."""
        return self.base.joinpath(*parts)

    def describe(self) -> str:
        return (f"base={self.base}\n  data={self.data}\n  static={self.static}\n"
                f"  templates={self.templates}\n  logs={self.logs}")


def script_dir(file_path: str | os.PathLike) -> Path:
    """Мини-версия для мест, где dataclass избыточен."""
    return Path(file_path).resolve().parent
