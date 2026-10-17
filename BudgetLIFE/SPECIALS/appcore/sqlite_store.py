"""
sqlite_store.py — база данных SQLite «по-взрослому»: миграции, бэкапы, восстановление.

Взято из LanguageYOI (`create_backup_api` / `restore_backup_api` со safety-копией,
восстановление после сбоя), DnD's (`init_db` со схемой и внешними ключами,
открытие соединения на запрос) и Cooker (схема + подключение в каждом запросе).

ЧЕМУ ЭТО УЧИТ ВЕСЬ РЕПОЗИТОРИЙ (и почему модуль нужен)
------------------------------------------------------
  * SQLite в локальном приложении — это ФАЙЛ. Пользователь выключит ПК, приложение
    упадёт, антивирус вмешается — и файл можно потерять. Значит: WAL + бэкапы.
  * Приложение обновляется, схема меняется. Без миграций пользователь получает
    «no such column» после обновления. Значит: `user_version` + список ALTER.
  * Восстановление из бэкапа обязано сначала сохранить ТЕКУЩУЮ базу (safety-copy),
    иначе «восстановил и потерял всё» — реальный сценарий (приём LanguageYOI).
  * Соединение нельзя держать глобально: с ним работают Flask-потоки и трей.
    Значит: соединение на операцию, `Row`-доступ по имени, транзакция контекстом.

ПРИМЕР
------
    store = SqliteStore(paths.data / "notes.db", backup_dir=paths.data / "backups",
                        logger=logger)
    store.init_schema(\"\"\"
        CREATE TABLE IF NOT EXISTS note (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    \"\"\", migrations=[(2, "ALTER TABLE note ADD COLUMN pinned INTEGER DEFAULT 0")])
    with store.connect() as con:
        con.execute("INSERT INTO note(text, created_at) VALUES(?, datetime('now'))", (text,))
    store.backup()                     # копия: notes-20261006-101500.db
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

_logger: logging.Logger | None = None


def set_logger(logger: logging.Logger | None) -> None:
    global _logger
    _logger = logger


def _log(level: str, message: str, *args) -> None:
    if _logger:
        getattr(_logger, level, _logger.info)(message, *args)


def _safe_name(name: str) -> str:
    return "".join(char if char.isalnum() or char in "._- " else "_" for char in str(name))


class SqliteStore:
    """Обёртка над SQLite: схема, миграции, безопасные бэкапы и восстановление."""

    def __init__(self, path: str | os.PathLike, *, backup_dir: str | os.PathLike | None = None,
                 logger: logging.Logger | None = None, timeout: float = 10.0,
                 wal: bool = True) -> None:
        self.path = Path(path)
        self.backup_dir = Path(backup_dir) if backup_dir else self.path.parent / "backups"
        self.timeout = float(timeout)
        self.wal = bool(wal)
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if logger:
            set_logger(logger)
        else:
            set_logger(_logger)

    # ── соединение ──
    @contextmanager
    def connect(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        """Соединение на операцию (безопасно для многопоточного Flask).

        Автоматически: ``row_factory`` (доступ по имени столбца), внешние ключи,
        WAL-режим, busy-timeout. Коммит при выходе без ошибок, откат при ошибке.
        """
        uri = f"file:{self.path}?mode=ro" if readonly else None
        connection = sqlite3.connect(uri or str(self.path), timeout=self.timeout,
                                     uri=bool(uri), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            if self.wal and not readonly:
                connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = %d" % int(self.timeout * 1000))
            yield connection
            if not readonly:
                connection.commit()
        except Exception:
            try:
                connection.rollback()
            except Exception:
                pass
            raise
        finally:
            connection.close()

    # ── запросы-помощники ──
    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Выполняет запрос, возвращает ``lastrowid`` (для INSERT) или число изменённых строк."""
        with self.connect() as connection:
            cursor = connection.execute(sql, tuple(params))
            return int(cursor.lastrowid or cursor.rowcount or 0)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        """SELECT → список словарей (готово к ``jsonify``)."""
        with self.connect(readonly=True) as connection:
            return [dict(row) for row in connection.execute(sql, tuple(params)).fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        """SELECT одной строки → словарь или None (LIMIT добавляется, если его нет)."""
        query = sql if "LIMIT" in sql.upper() else f"{sql.rstrip().rstrip(';')} LIMIT 1"
        rows = self.query(query, params)
        return rows[0] if rows else None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Несколько изменений одной транзакцией («всё или ничего»)."""
        with self.connect() as connection:
            yield connection

    # ── схема и миграции ──
    def init_schema(self, schema_sql: str, *,
                    migrations: Sequence[tuple[int, str]] = ()) -> int:
        """Создаёт таблицы и применяет миграции по ``user_version``.

        ``migrations`` — список ``(версия, SQL)``, применяется всё, что выше текущей
        версии, по возрастанию. Версия хранится в самой базе (``PRAGMA user_version``),
        поэтому обновление приложения не зависит от внешних файлов.

        Возвращает итоговую версию схемы.
        """
        with self._lock, self.connect() as connection:
            connection.executescript(schema_sql or "")
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            for version, sql in sorted(migrations, key=lambda item: item[0]):
                if version <= current:
                    continue
                statements = [part.strip() for part in str(sql).split(";") if part.strip()]
                for statement in statements:
                    try:
                        connection.execute(statement)
                    except sqlite3.OperationalError as exc:
                        # «duplicate column name» — миграция уже применена вручную: не падаем
                        if "duplicate column" in str(exc).lower():
                            _log("info", "Миграция %s уже применена: %s", version, exc)
                            continue
                        raise
                connection.execute(f"PRAGMA user_version = {int(version)}")
                current = int(version)
                _log("info", "База %s: применена миграция схемы v%s", self.path.name, version)
            return current

    def schema_version(self) -> int:
        with self.connect(readonly=True) as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def add_column(self, table: str, column: str, definition: str) -> bool:
        """Добавляет столбец, если его ещё нет (простая миграция «на ходу»)."""
        columns = {row["name"] for row in self.query(f"PRAGMA table_info({_safe_name(table)})")}
        if column in columns:
            return False
        self.execute(f"ALTER TABLE {_safe_name(table)} ADD COLUMN {_safe_name(column)} {definition}")
        _log("info", "База %s: добавлен столбец %s.%s", self.path.name, table, column)
        return True

    # ── бэкапы ──
    def backup(self, *, prefix: str = "", keep: int | None = None) -> Path | None:
        """Делает резервную копию базы. Возвращает путь к копии или None.

        Используется API самой SQLite (``Connection.backup``): копия корректна
        даже если в этот момент идёт запись (в отличие от простого shutil.copy).
        """
        if not self.path.exists():
            return None
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{_safe_name(prefix) + '_' if prefix else ''}{self.path.stem}_{stamp}{self.path.suffix}"
        target = self.backup_dir / name
        try:
            with sqlite3.connect(str(self.path), timeout=self.timeout) as source:
                with sqlite3.connect(str(target)) as destination:
                    source.backup(destination)
            _log("info", "Бэкап базы: %s", target)
        except Exception as exc:
            _log("error", "Не удалось сделать бэкап %s: %s", self.path, exc)
            try:
                shutil.copy2(self.path, target)      # запасной путь
            except Exception as exc2:
                _log("error", "Копирование тоже не удалось: %s", exc2)
                return None
        if keep and keep > 0:
            self.prune_backups(keep=keep)
        return target

    def list_backups(self) -> list[dict]:
        """Список копий: имя, размер, дата (свежие сверху) — для страницы «Бэкапы»."""
        if not self.backup_dir.exists():
            return []
        items = []
        pattern = f"*{self.path.stem}*{self.path.suffix}*"   # и safety-копии тоже
        for path in sorted(self.backup_dir.glob(pattern),
                           key=lambda item: item.stat().st_mtime, reverse=True):
            stat = path.stat()
            items.append({"name": path.name, "size": stat.st_size,
                          "size_human": _human(stat.st_size),
                          "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
        return items

    def prune_backups(self, *, keep: int = 10) -> int:
        """Оставляет ``keep`` свежих копий, остальные удаляет. Возвращает число удалённых."""
        backups = list(reversed(self.list_backups()))       # от старых к новым
        removed = 0
        for item in backups[:-keep] if keep > 0 else backups:
            try:
                (self.backup_dir / item["name"]).unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def restore_backup(self, name: str) -> dict:
        """Восстанавливает базу из копии, СОХРАНИВ текущую (safety-copy).

        Возвращает ``{"ok": bool, "restored": name, "safety_backup": ...}``.
        """
        source = self.backup_dir / _safe_name(name)
        if not source.exists() or source.suffix != self.path.suffix:
            return {"ok": False, "error": f"Копия не найдена: {name}"}
        safety = None
        try:
            # 1. Сначала страхуем текущее состояние (даже если оно «битое»)
            if self.path.exists():
                safety_path = self.backup(prefix="before_restore")
                safety = safety_path.name if safety_path else None
            # 2. Подменяем файл (сначала копия рядом, затем атомарная замена)
            temporary = self.path.with_suffix(self.path.suffix + ".restoring")
            shutil.copy2(source, temporary)
            os.replace(temporary, self.path)
            for suffix in ("-wal", "-shm"):                   # хвосты WAL от старой базы
                leftover = Path(str(self.path) + suffix)
                if leftover.exists():
                    leftover.unlink()
            _log("warning", "База восстановлена из %s (страховка: %s)", name, safety)
            return {"ok": True, "restored": name, "safety_backup": safety}
        except Exception as exc:
            _log("error", "Восстановление базы не удалось: %s", exc)
            return {"ok": False, "error": str(exc), "safety_backup": safety}

    def capture(self, *, name: str | None = None) -> Path | None:
        """Именованная копия «на память» (например, перед опасной операцией)."""
        return self.backup(prefix=name or "manual")

    # ── обслуживание ──
    def integrity_check(self) -> bool:
        """``PRAGMA integrity_check`` — True, если база в порядке."""
        try:
            with self.connect(readonly=True) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()[0]
            return str(result).lower() == "ok"
        except Exception as exc:
            _log("error", "Проверка целостности не удалась: %s", exc)
            return False

    def vacuum(self) -> bool:
        """Сжимает файл (после массовых удалений). Требует места на диске."""
        try:
            self.execute("VACUUM")
            return True
        except Exception as exc:
            _log("warning", "VACUUM не выполнен: %s", exc)
            return False

    def size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def tables(self) -> list[str]:
        """Имена таблиц (пригодится для экспорта и диагностики)."""
        rows = self.query("SELECT name FROM sqlite_master WHERE type='table' "
                          "AND name NOT LIKE 'sqlite_%' ORDER BY name")
        return [row["name"] for row in rows]

    def export_json(self, table: str) -> list[dict]:
        """Выгрузка таблицы в список словарей (для «экспорт в JSON/CSV»)."""
        if table not in self.tables():
            return []
        return self.query(f"SELECT * FROM {_safe_name(table)}")


def _human(size: float) -> str:
    value = float(size or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.2f} {unit}".replace(".", ",")
        value /= 1024
    return f"{value:.2f} ГБ"


def open_store(path: str | os.PathLike, **kwargs) -> SqliteStore:
    """Короткая форма: ``store = open_store(paths.data / "app.db")``."""
    return SqliteStore(path, **kwargs)


# Сколько времени держим «занятость» базы в тестах и на слабых ПК
BUSY_RETRY_SECONDS = 5.0


def backup_before_change(store: SqliteStore, *, keep: int = 20) -> Path | None:
    """Удобный однострочник: «сделай копию перед опасной операцией».

    Приём LanguageYOI: копия делается не «когда-нибудь по расписанию», а прямо
    перед импортом/восстановлением/массовой правкой.
    """
    return store.backup(prefix="before_change", keep=keep)


def wait_for_free(path: str | os.PathLike, *, timeout: float = BUSY_RETRY_SECONDS) -> bool:
    """Ждёт, пока файл БД не будет занят другим процессом (редкий случай на Windows)."""
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        try:
            with sqlite3.connect(str(path), timeout=0.5) as connection:
                connection.execute("PRAGMA quick_check").fetchone()
            return True
        except sqlite3.OperationalError:
            time.sleep(0.15)
        except Exception:
            return False
    return False
