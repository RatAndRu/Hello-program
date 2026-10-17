"""
jsonstore.py — надёжное хранение данных в JSON.

Взято из LanguageYOI (shared.py: запись конфига через tmp + fsync + os.replace)
и развито до переиспользуемого класса.

Почему нельзя `open(path,"w"); json.dump(...)`:
  * Если в момент записи закрыть окно/выключить ПК — на диске останется
    обрезанный файл, и при следующем запуске json.load упадёт (потеря ВСЕХ данных).
  * Два потока (Flask + трей/вотчер) пишут одновременно — файл перемешивается.

Решение — атомарная замена: пишем во временный файл рядом, сбрасываем на диск
(fsync) и подменяем `os.replace` (атомарна на NTFS и POSIX). Плюс страховка
`.bak` и восстановление + карантин битого файла.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

DEFAULT_INDENT = 2


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> None:
    """Записать текст «всё или ничего» (см. описание модуля)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding=encoding, newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())   # данные реально на диске, а не в кэше ОС
    os.replace(tmp, path)       # атомарная подмена
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass


def load_json(path: str | Path, default: Any = None, *, logger=None) -> Any:
    """Чтение JSON с восстановлением из .bak и карантином битого файла.

    Порядок: основной файл → .bak → default. Битый файл переименовывается
    в `.corrupt-YYYYmmdd-HHMMSS`, чтобы его можно было посмотреть руками.
    """
    path = Path(path)
    for candidate in (path, path.with_suffix(path.suffix + ".bak")):
        try:
            if not candidate.exists():
                continue
            with open(candidate, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if candidate != path:
                _log(logger, "warning", "Данные восстановлены из %s", candidate.name)
                atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=DEFAULT_INDENT))
            return data
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            if candidate == path:
                _quarantine(path, logger)
            else:
                _log(logger, "warning", "Резервный файл %s тоже не читается: %s",
                     candidate.name, exc)
    return default


def _quarantine(path: Path, logger=None) -> None:
    try:
        broken = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
        os.replace(path, broken)
        _log(logger, "error", "Файл %s повреждён, отложен как %s", path.name, broken.name)
    except OSError:
        pass


def _log(logger, level: str, msg: str, *args) -> None:
    if logger is None:
        return
    getattr(logger, level, logger.info)(msg, *args)


class JsonStore:
    """Потокобезопасное JSON-хранилище с атомарной записью.

    Пример:
        store = JsonStore(paths.data_file("tasks.json"), default={"items": []})
        data = store.load()
        with store.edit() as doc:      # правки + сохранение под одним локом
            doc["items"].append({"id": 1})
    """

    def __init__(self, path: str | Path, default: Any = None, *,
                 indent: int = DEFAULT_INDENT, keep_backup: bool = True,
                 logger=None, autosave_interval: float = 0.0):
        self.path = Path(path)
        self.default = default if default is not None else {}
        self.indent = indent
        self.keep_backup = keep_backup
        self.logger = logger
        self.autosave_interval = autosave_interval
        self._lock = threading.RLock()
        self._cache: Any = None
        self._dirty = False
        self._last_save = 0.0

    # ── чтение/запись ───────────────────────────────────────────────────────

    @property
    def backup_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".bak")

    def load(self, force: bool = False) -> Any:
        """Возвращает данные (из кэша, если уже читали)."""
        with self._lock:
            if self._cache is None or force:
                import copy
                data = load_json(self.path, default=None, logger=self.logger)
                self._cache = copy.deepcopy(data) if data is not None else copy.deepcopy(self.default)
            return self._cache

    def save(self, data: Any | None = None) -> bool:
        """Атомарно сохраняет данные. Возвращает False вместо исключения."""
        with self._lock:
            if data is not None:
                self._cache = data
            if self._cache is None:
                return False
            text = json.dumps(self._cache, ensure_ascii=False, indent=self.indent)
            try:
                if self.keep_backup and self.path.exists():
                    try:
                        shutil.copy2(self.path, self.backup_path)
                    except OSError:
                        pass
                atomic_write_text(self.path, text)
                self._dirty = False
                self._last_save = time.monotonic()
                return True
            except OSError as exc:
                _log(self.logger, "error", "Не удалось сохранить %s: %s", self.path.name, exc)
                return False

    def edit(self) -> "_EditContext":
        """`with store.edit() as doc:` — правки и атомарное сохранение под локом."""
        return _EditContext(self)

    def reset(self) -> Any:
        """Сброс к значению по умолчанию (файл перезаписывается)."""
        import copy
        with self._lock:
            self._cache = copy.deepcopy(self.default)
            self.save()
            return self._cache

    def touch(self) -> None:
        """Отметить «есть изменения» (для autosave_interval)."""
        with self._lock:
            self._dirty = True
            if self.autosave_interval and time.monotonic() - self._last_save >= self.autosave_interval:
                self.save()

    def save_if_dirty(self) -> None:
        with self._lock:
            if self._dirty:
                self.save()


class _EditContext:
    def __init__(self, store: JsonStore):
        self._store = store
        self._lock = None

    def __enter__(self) -> Any:
        self._lock = self._store._lock
        self._lock.acquire()
        return self._store.load()

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self._store.save()
        finally:
            self._lock.release()
        return False


def guarded(default: Any = None, *, logger=None) -> Callable:
    """Декоратор: ошибка в чтении/записи данных не должна убивать приложение."""
    def wrapper(func: Callable) -> Callable:
        def inner(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - осознанно широкий
                _log(logger, "error", "%s: %s", func.__name__, exc)
                return default
        return inner
    return wrapper
