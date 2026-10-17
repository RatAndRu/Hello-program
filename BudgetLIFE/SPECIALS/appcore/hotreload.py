"""
hotreload.py — самообновление при изменении кода + защита от утечек памяти.

Идея из DeployAgent (`hot_reload_watcher`) и BLIND_PC (`hot_reload_watcher`):
пока проект дорабатывается, после каждого сохранения app.py приложение само
закрывает трей и перезапускается через start.vbs. Разработка «в один клик».

Что добавлено к оригиналу (там были грабли):
  * НАБЛЮДАЕМ всё, что реально меняется при правках (.py, .vbs, .html, .css, .js),
    а не только app.py;
  * ЖДЁМ «успокоения» файла (settle): редактор/нейросеть может писать файл
    по частям, и перезапуск в середине записи давал синтаксическую ошибку;
  * ДЕБАУНС: после перезапуска не дёргаемся от эха файловой системы;
  * игнорируем data/, логи, __pycache__, .git — иначе сохранение данных
    вызывало бы бесконечный цикл перезапусков;
  * MEMORY-GUARD из DeployAgent: если процесс распух (например, утечка в OCR),
    перезапускаемся и об этом пишем в лог;
  * всё это не мешает приложению: поток daemon, ошибки только логируются.

ВАЖНО: перезапуск должен выполняться через appcore.singleton.relaunch_app,
который сперва освобождает порт-лок. Иначе новый экземпляр не сможет занять лок
(старый ещё держит сокет) — грабли, описанные в самом DeployAgent.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

# Что считаем «кодом» проекта
DEFAULT_PATTERNS = ("*.py", "*.vbs", "*.js", "*.css", "*.html", "*.json")
# Файлы в корне проекта, которые НЕ надо считать кодом (данные и логи)
IGNORED_DIRS = {"data", "logs", "__pycache__", ".git", "node_modules", ".venv", "venv", "backup", "backups"}
IGNORED_FILES = {"port.txt", "_config.json", "settings.json", "config.json"}


class HotReloadWatcher:
    """Следит за файлами проекта и вызывает on_restart при изменениях.

    Параметры:
        source_dir   — папка проекта (AppPaths.base)
        on_restart   — что сделать при изменении (обычно singleton.relaunch_app + exit)
        patterns     — маски файлов
        interval     — период опроса, сек
        settle       — сколько ждать неизменности файла перед перезапуском
        memory_limit_mb — порог памяти для авто-перезапуска (None — выключено)
        ui_active    — функция «идёт операция, перезапуск сейчас нежелателен»
    """

    def __init__(self, source_dir: str | Path, on_restart: Callable[[str], None], *,
                 patterns: Iterable[str] = DEFAULT_PATTERNS,
                 interval: float = 4.0, settle: float = 1.2,
                 memory_limit_mb: int | None = None,
                 ui_active: Callable[[], bool] | None = None,
                 logger=None, extra_ignore: Iterable[str] = ()):
        self.source_dir = Path(source_dir)
        self.on_restart = on_restart
        self.patterns = tuple(patterns)
        self.interval = max(1.0, float(interval))
        self.settle = max(0.2, float(settle))
        self.memory_limit_mb = memory_limit_mb
        self.ui_active = ui_active or (lambda: False)
        self.logger = logger
        self.extra_ignore = set(extra_ignore)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: dict[str, tuple[float, int]] = {}
        self._pending: dict[str, tuple[float, int, float]] = {}
        self._last_restart = 0.0

    # ── снимок файлов ───────────────────────────────────────────────────────

    def _iter_files(self):
        for root, dirs, files in os.walk(self.source_dir):
            dirs[:] = [d for d in dirs
                       if d.lower() not in IGNORED_DIRS and d not in self.extra_ignore]
            for name in files:
                if name in IGNORED_FILES:
                    continue
                if any(fnmatch.fnmatch(name.lower(), pat.lower()) for pat in self.patterns):
                    yield Path(root) / name

    def _take_snapshot(self) -> dict[str, tuple[float, int]]:
        snapshot: dict[str, tuple[float, int]] = {}
        for path in self._iter_files():
            try:
                stat = path.stat()
                snapshot[str(path)] = (stat.st_mtime, stat.st_size)
            except OSError:
                continue
        return snapshot

    # ── жизненный цикл ──────────────────────────────────────────────────────

    def start(self) -> "HotReloadWatcher":
        self._snapshot = self._take_snapshot()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="hotreload")
        self._thread.start()
        if self.logger:
            self.logger.info("Hot-reload: слежу за %d файлами в %s (интервал %.1f с)",
                             len(self._snapshot), self.source_dir, self.interval)
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if self._check_memory():
                    return                      # перезапуск по памяти инициирован
                if self._check_files():
                    return                      # перезапуск по файлам инициирован
            except Exception as exc:            # вотчер не должен ничего ронять
                if self.logger:
                    self.logger.warning("Hot-reload: ошибка проверки: %s", exc)

    def _check_memory(self) -> bool:
        if not self.memory_limit_mb:
            return False
        from . import processes
        mb = processes.memory_mb()
        if mb is None or mb <= self.memory_limit_mb:
            return False
        if self.ui_active():
            if self.logger:
                self.logger.info("Память %.0f МБ > %d МБ, но идёт операция — ждём",
                                 mb, self.memory_limit_mb)
            return False
        self._restart(f"память {mb:.0f} МБ > {self.memory_limit_mb} МБ")
        return True

    def _check_files(self) -> bool:
        current = self._take_snapshot()
        changed = [path for path, meta in current.items() if self._snapshot.get(path) != meta]
        removed = [path for path in self._snapshot if path not in current]
        for path in changed + removed:
            self._pending[path] = (*current.get(path, (0.0, 0)), time.monotonic())

        # Оставляем только те файлы, которые «успокоились» (settle)
        ready: list[str] = []
        now = time.monotonic()
        for path, meta in list(self._pending.items()):
            if now - meta[2] >= self.settle:
                ready.append(path)
                self._pending.pop(path, None)
        if not ready:
            self._snapshot = current
            return False
        # Дебаунс: не перезапускаемся чаще, чем раз в 5 секунд
        if now - self._last_restart < 5.0:
            self._snapshot = current
            return False
        names = ", ".join(sorted(Path(p).name for p in ready)[:5])
        self._snapshot = current
        self._restart(f"изменён код: {names}")
        return True

    def _restart(self, reason: str) -> None:
        self._last_restart = time.monotonic()
        if self.logger:
            self.logger.info("HOT-RELOAD: %s → перезапуск", reason)
        try:
            self.on_restart(reason)
        except Exception as exc:
            if self.logger:
                self.logger.error("Hot-reload: не удалось перезапустить: %s", exc)


# ── вспомогательное ─────────────────────────────────────────────────────────

def make_restart_handler(app_dir: str | Path, *, vbs_name: str = "start.vbs",
                         before_exit: Callable[[], None] | None = None, logger=None):
    """Готовый on_restart: остановить фоновые дела, перезапустить, выйти.

    Ожидаемый порядок (см. DeployAgent._do_restart):
        1) выставить флаги остановки, 2) освободить лок-порт/мьютекс,
        3) запустить start.vbs, 4) жёстко выйти (os._exit).
    """
    from . import singleton

    def _handler(reason: str) -> None:
        if before_exit:
            try:
                before_exit()
            except Exception:
                pass
        singleton.relaunch_app(app_dir, vbs_name, logger=logger)
        singleton.exit_process(0)

    return _handler


def trim_log_file(path: str | Path, *, max_bytes: int = 1024 * 1024,
                  keep_lines: int = 500, logger=None) -> bool:
    """Обрезка лога, если он вырос (страховка для логов, которые не ротируются).

    Приём DeployAgent._trim_log: оставляем последние N строк, чтобы файл не
    вырос в гигабайт и его можно было открыть блокнотом.
    """
    path = Path(path)
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return False
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        keep = lines[-keep_lines:]
        keep.insert(0, f"[logutil] лог обрезан: было {len(lines)} строк")
        from .jsonstore import atomic_write_text
        atomic_write_text(path, "\n".join(keep) + "\n")
        return True
    except Exception as exc:
        if logger:
            logger.warning("Не удалось обрезать лог %s: %s", path, exc)
        return False


def disk_free_mb(path: str | Path = ".") -> float | None:
    """Свободно на диске (МБ) — для диагностики в трее/аудите."""
    try:
        return shutil.disk_usage(str(path)).free / (1024 * 1024)
    except Exception:
        return None
