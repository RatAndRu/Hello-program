"""
logutil.py — логи, которые не теряются и не пухнут.

Собрано лучшее:
  * LanguageYOI: ротация (лог.txt до 1 МБ, потом .1 … .3), utf-8, единый формат.
  * DeployAgent: обрезка старого лога и sys.excepthook (без него падение под
    pythonw вообще не оставляет следов).
  * Трекер: запись под threading.Lock, чтобы два потока не перемешали строки.

ГЛАВНАЯ БОЛЬ pythonw
--------------------
Под pythonw.exe нет консоли: `sys.stdout is None`. Любой чужой код с
`sys.stdout.write(...)` или `sys.stdout.flush()` падает с AttributeError прямо
в середине запуска — приложение «молча не стартует». `install_safe_streams()`
подменяет потоки-заглушки, которые пишут в лог, — это лечит целый класс
«необъяснимых» падений.
"""

from __future__ import annotations

import io
import logging
import logging.handlers
import sys
import threading
import traceback
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

MAX_BYTES = 1 * 1024 * 1024   # 1 МБ — как в LanguageYOI/DeployAgent
BACKUP_COUNT = 3              # log.txt.1 … log.txt.3
_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO,
           "warning": logging.WARNING, "error": logging.ERROR}


class _LogStream(io.TextIOBase):
    """Поток-заглушка для pythonw: пишет строки в лог, никогда не бросает."""

    def __init__(self, logger: logging.Logger, level: int = logging.INFO, tag: str = "stdout"):
        self._logger = logger
        self._level = level
        self._tag = tag

    def writable(self) -> bool:
        return True

    def write(self, text):  # noqa: D102
        text = str(text)
        if text.strip():
            for line in text.rstrip("\n").splitlines():
                self._logger.log(self._level, "[%s] %s", self._tag, line)
        return len(text)

    def flush(self) -> None:  # noqa: D102
        return None


def setup(app_name: str, log_path: str | Path, *, level: str = "info",
          stdio: bool = True, console_also: bool = True,
          max_bytes: int = MAX_BYTES, backup_count: int = BACKUP_COUNT) -> logging.Logger:
    """Настраивает корневой логгер приложения. Вызывать ОДИН раз в начале main().

    log_path : путь к logs/log.txt (см. AppPaths.log_file)
    stdio    : заменить sys.stdout/sys.stderr безопасными потоками (pythonw!)
    console_also : писать также в консоль, если она есть (запуск через start_debug.bat)

    Повторный вызов не дублирует обработчики (важно для hot-reload и тестов).
    """
    log_path = Path(log_path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    root = logging.getLogger()
    root.setLevel(_LEVELS.get(str(level).lower(), logging.INFO))

    # --- файл с ротацией -----------------------------------------------------
    file_handler = None
    for handler in list(root.handlers):
        if getattr(handler, "_appcore_file", False):
            if Path(getattr(handler, "baseFilename", "")) == log_path:
                file_handler = handler
            else:
                root.removeHandler(handler)
                handler.close()
    if file_handler is None:
        try:
            file_handler = logging.handlers.RotatingFileHandler(
                log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
            file_handler._appcore_file = True  # помечаем «свой» обработчик
            root.addHandler(file_handler)
        except OSError as exc:
            print(f"[logutil] не удалось открыть лог {log_path}: {exc}")

    # --- консоль (если есть) -------------------------------------------------
    if console_also and sys.stderr is not None and not any(
            isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
            for h in root.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        stream._appcore_stream = True
        root.addHandler(stream)

    logger = logging.getLogger(app_name)

    if stdio:
        install_safe_streams(logger)

    # Записываем строку-маркер: по ней видно, что интерпретатор вообще дошёл
    # до кода (LanguageYOI: «если приложение не стартует — в логе должно быть
    # видно, дошёл ли Python до первой строки»).
    logger.info("=" * 70)
    logger.info("%s стартует | pid=%s | python=%s", app_name, _safe_pid(), sys.executable)
    return logger


def _safe_pid() -> int:
    import os
    try:
        return os.getpid()
    except Exception:  # pragma: no cover
        return -1


def install_safe_streams(logger: logging.Logger) -> None:
    """pythonw: sys.stdout/sys.stderr == None → подменяем пишущими в лог."""
    if sys.stdout is None:
        sys.stdout = _LogStream(logger, logging.INFO, "stdout")
    if sys.stderr is None:
        sys.stderr = _LogStream(logger, logging.ERROR, "stderr")
    # Некоторые библиотеки пишут в sys.__stdout__ (не None даже под pythonw? нет —
    # тоже None), на всякий случай выравниваем.
    if getattr(sys, "__stdout__", None) is None:
        sys.__stdout__ = sys.stdout
    if getattr(sys, "__stderr__", None) is None:
        sys.__stderr__ = sys.stderr


def log_uncaught(logger: logging.Logger) -> None:
    """Пишет необработанные исключения (в т.ч. в потоках) в лог.

    Без этого приложение под pythonw падает «в никуда»: ни окна, ни записи.
    Ставится как sys.excepthook + threading.excepthook (Python 3.8+).
    """
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logger.critical("НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ:\n%s",
                        "".join(traceback.format_exception(exc_type, exc_value, exc_tb)))

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):
        def _thread_hook(args):
            if issubclass(args.exc_type, SystemExit):
                return
            logger.critical("ИСКЛЮЧЕНИЕ В ПОТОКЕ %s:\n%s", getattr(args.thread, "name", "?"),
                            "".join(traceback.format_exception(
                                args.exc_type, args.exc_value, args.exc_traceback)))
        threading.excepthook = _thread_hook


class RateLimitedLog:
    """Не даёт спамить лог: одинаковые сообщения не чаще, чем раз в N секунд.

    Нужно для вотчеров (файлы, буфер обмена): при ошибке в цикле раз в 2 секунды
    лог превращался в мусорку.
    """

    def __init__(self, logger: logging.Logger, interval: float = 30.0, level: int = logging.WARNING):
        self._logger = logger
        self._interval = interval
        self._level = level
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        import time
        self._time = time.monotonic

    def __call__(self, key: str, msg: str, *args) -> None:
        now = self._time()
        with self._lock:
            if now - self._last.get(key, -1e9) < self._interval:
                return
            self._last[key] = now
        self._logger.log(self._level, msg, *args)
