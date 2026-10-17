"""Надзиратель за сервером и потоками — фишка DnD's (трей-надзиратель).

В DnD's отдельный процесс-надзиратель следит за сервером и **перезапускает его,
если тот упал**: игра не должна «умереть» посреди вечера. В нашем стандарте
сервер живёт в потоке того же процесса, но беда та же: упавший фоновый поток или
«залипший» сервер не видно, пока пользователь не скажет «не открывается».

``ThreadWatchdog`` закрывает это:

* раз в ``interval`` секунд проверяет, жив ли поток/процесс и отвечает ли
  ``health_url`` (по умолчанию — свой ``/api/health``);
* одна случайная неудача ничего не делает (сеть/загрузка), а вот ``failures``
  подряд — это уже авария;
* по аварии вызывается ``on_down``: обычно это
  ``singleton.relaunch_app(...)`` + ``os._exit(0)`` — приложение поднимается
  заново (приём DeployAgent/BLIND_PC: перезапуск через ``start.vbs``);
* есть предохранитель ``max_restarts`` на окно ``restart_window`` — чтобы не
  уйти в бесконечный цикл перезапусков при системной ошибке.

Модуль намеренно ничего не знает ни про Flask, ни про Windows: мониторить можно
и поток сервера, и внешний процесс.
"""

from __future__ import annotations

import threading
import time
import urllib.request
from collections import deque
from collections.abc import Callable

__all__ = ["ThreadWatchdog", "http_ok"]


def http_ok(url: str, timeout: float = 2.0, *, expect: int = 200) -> bool:
    """Отвечает ли сервер (любой 2xx, если ``expect`` не задан явно)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= int(response.status) < (300 if expect == 200 else expect + 1)
    except Exception:
        return False


class ThreadWatchdog:
    """Следит за потоком и (необязательно) за ответом сервера по URL."""

    def __init__(self, *, thread: threading.Thread | None = None,
                 health_url: str | None = None, on_down: Callable[[str], None] | None = None,
                 interval: float = 20.0, failures: int = 2, startup_grace: float = 15.0,
                 max_restarts: int = 3, restart_window: float = 600.0, logger=None,
                 name: str = "watchdog") -> None:
        self.thread = thread
        self.health_url = health_url
        self.on_down = on_down
        self.interval = max(2.0, float(interval))
        self.failures_needed = max(1, int(failures))
        self.startup_grace = max(0.0, float(startup_grace))
        self.max_restarts = max(1, int(max_restarts))
        self.restart_window = max(60.0, float(restart_window))
        self.logger = logger
        self.name = name

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fails = 0
        self._restarts: deque[float] = deque(maxlen=max_restarts + 1)
        self.stats = {"checks": 0, "failures": 0, "restarts": 0, "last_error": ""}

    # ── жизненный цикл ──────────────────────────────────────────────────────
    def start(self) -> "ThreadWatchdog":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()
        self._log("info", "Надзиратель запущен: проверка каждые %.0f с, порог %d",
                  self.interval, self.failures_needed)
        return self

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── проверки ────────────────────────────────────────────────────────────
    def check(self) -> str:
        """Одна проверка. Возвращает "" если всё хорошо, иначе причину."""
        if self.thread is not None and not self.thread.is_alive():
            return "поток сервера завершился"
        if self.health_url and not http_ok(self.health_url):
            return f"сервер не отвечает: {self.health_url}"
        return ""

    def _loop(self) -> None:
        if self.startup_grace:
            self._stop.wait(self.startup_grace)
        while not self._stop.is_set():
            reason = self.check()
            self.stats["checks"] += 1
            if reason:
                self._fails += 1
                self.stats["failures"] += 1
                self.stats["last_error"] = reason
                self._log("warning", "Проверка %d из %d не прошла: %s",
                          self._fails, self.failures_needed, reason)
                if self._fails >= self.failures_needed:
                    self._handle_down(reason)
                    self._fails = 0
            else:
                self._fails = 0
            self._stop.wait(self.interval)

    def _handle_down(self, reason: str) -> None:
        now = time.time()
        self._restarts.append(now)
        while self._restarts and now - self._restarts[0] > self.restart_window:
            self._restarts.popleft()
        if len(self._restarts) > self.max_restarts:
            self._log("error", "Перезапусков больше %d за %.0f с — надзиратель останавливается "
                               "(причина последней аварии: %s)",
                      self.max_restarts, self.restart_window, reason)
            self._stop.set()
            return
        self.stats["restarts"] += 1
        self._log("error", "Авария: %s. Поднимаю приложение заново", reason)
        if self.on_down is None:
            self._log("warning", "on_down не задан — перезапуск не выполнен")
            return
        try:
            self.on_down(reason)
        except Exception as exc:                # noqa: BLE001 — надзиратель не должен падать сам
            self._log("error", "on_down упал: %s", exc)

    def _log(self, level: str, message: str, *args) -> None:
        if self.logger:
            getattr(self.logger, level, self.logger.info)(message, *args)
