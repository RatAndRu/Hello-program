"""
hotkeys.py — глобальные горячие клавиши приложения.

Взято из bridge (`keyboard.add_hotkey(... )` + `rebind_hotkeys` при смене настроек),
PromptSystem (`Ctrl+Alt+A` → собрать шаблон в буфер) и Телепульта (хоткеи из
интерфейса телефона).

ТИПИЧНЫЕ ГРАБЛИ, КОТОРЫЕ ЗДЕСЬ ЗАКРЫТЫ
-------------------------------------
  * нет библиотеки (`keyboard`/`pynput` не установлены) → приложение продолжает
    работать, в лог идёт понятная строка и точная команда установки;
  * хоткей зарегистрирован дважды при перезапуске настроек → старые обработчики
    снимаются перед добавлением новых (перепривязка «на ходу»);
  * исключение внутри обработчика убивает слушателя → каждый вызов обёрнут в
    try/except с записью в лог;
  * долгий обработчик блокирует ввод → по умолчанию работаем в отдельном потоке.

ПОЧЕМУ SUPPRESS ОСТОРОЖНО
------------------------
`suppress=True` (в keyboard) «съедает» нажатие у системы: удобно для Alt+Shift+C,
но если переусердствовать, у пользователя перестанут работать обычные сочетания.
Поэтому подавление — явный параметр при регистрации, а по умолчанию выключено.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

_logger: logging.Logger | None = None
_which: str | None = None


def set_logger(logger: logging.Logger | None) -> None:
    global _logger
    _logger = logger


def _log(level: str, message: str, *args) -> None:
    if _logger:
        getattr(_logger, level, _logger.info)(message, *args)


def backend() -> str:
    """``keyboard`` | ``pynput`` | ``none`` — чем регистрируем хоткеи."""
    global _which
    if _which:
        return _which
    import importlib.util

    def has(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except Exception:
            return False

    if has("keyboard"):
        _which = "keyboard"
    elif has("pynput"):
        _which = "pynput"
    else:
        _which = "none"
    return _which


def available() -> bool:
    return backend() != "none"


def install_hint() -> str:
    """Что написать пользователю, если хоткеи недоступны."""
    return "Хоткеи недоступны. Установите: python -m pip install keyboard"


class HotkeyManager:
    """Регистрация/перепривязка глобальных хоткеев с безопасным отказом.

    Использование::

        hk = HotkeyManager(logger=logger)
        hk.register("alt+shift+c", send_to_phone, suppress=True)
        hk.register("alt+shift+v", paste_from_phone, suppress=True)
        ...
        hk.rebind({"alt+c": send, "alt+v": paste})   # смена настроек «на ходу»
        hk.stop()
    """

    def __init__(self, *, logger: logging.Logger | None = None,
                 run_in_thread: bool = True) -> None:
        self._bindings: dict[str, tuple[str, Callable[[], None]]] = {}   # combo → (имя, функция)
        self._handles: list[object] = []
        # RLock: unregister/rebind вызывают _apply, который тоже берёт этот лок
        self._lock = threading.RLock()
        self._run_in_thread = run_in_thread
        self._stopped = False
        self._logger = logger or _logger
        if logger:
            set_logger(logger)

    # ── регистрация ──
    def register(self, combo: str, callback: Callable[[], None], *,
                 name: str | None = None, suppress: bool = False) -> bool:
        """Добавляет хоткей. False — если библиотеки нет или комбинация не разобралась."""
        combo = self._normalize(combo)
        if not combo:
            return False
        with self._lock:
            self._bindings[combo] = (name or combo, callback)
        if not available():
            self._log_once_unavailable()
            return False
        return self._apply(suppress=suppress)

    def rebind(self, bindings: dict[str, Callable[[], None]], *,
               suppress: bool = False) -> bool:
        """Заменяет все хоткеи разом (приём bridge: пользователь сменил их в настройках)."""
        with self._lock:
            self._bindings = {self._normalize(combo): (combo, callback)
                              for combo, callback in bindings.items()
                              if self._normalize(combo)}
        if not available():
            self._log_once_unavailable()
            return False
        return self._apply(suppress=suppress)

    def unregister(self, name: str) -> bool:
        with self._lock:
            for combo, (label, _) in list(self._bindings.items()):
                if label == name or combo == name:
                    self._bindings.pop(combo, None)
        return self._apply(suppress=False)

    def clear(self) -> None:
        with self._lock:
            self._bindings.clear()
        self._remove_handles()

    def stop(self) -> None:
        self.clear()
        self._stopped = True

    def active(self) -> list[str]:
        with self._lock:
            return sorted(self._bindings)

    # ── внутреннее ──
    @staticmethod
    def _normalize(combo: str) -> str:
        """Приводит «Alt + Shift + C» к виду ``alt+shift+c`` (без пробелов)."""
        text = str(combo or "").strip().lower()
        text = text.replace(" ", "")
        aliases = {"control": "ctrl", "windows": "win", "winleft": "win"}
        parts = [aliases.get(part, part) for part in text.split("+") if part]
        return "+".join(parts)

    def _remove_handles(self) -> None:
        for handle in self._handles:
            try:
                if backend() == "keyboard":
                    import keyboard
                    keyboard.remove_hotkey(handle)
                else:
                    handle.stop()                       # pyin
            except Exception:
                pass
        self._handles.clear()

    def _apply(self, *, suppress: bool) -> bool:
        """Перерегистрирует хоткеи по текущему словарю (сначала снимает старые)."""
        self._remove_handles()
        if not available():
            self._log_once_unavailable()
            return False
        ok = True
        with self._lock:
            items = list(self._bindings.items())
        for combo, (name, callback) in items:
            wrapped = self._wrap(name, callback)
            try:
                if backend() == "keyboard":
                    import keyboard
                    handle = keyboard.add_hotkey(combo, wrapped, suppress=suppress)
                else:
                    from pynput import keyboard as pynput_keyboard
                    listener = pynput_keyboard.GlobalHotKeys({f"<{combo.replace('+', '>+<')}>": wrapped})
                    listener.daemon = True
                    listener.start()
                    handle = listener
                self._handles.append(handle)
                _log("debug", "Хоткей зарегистрирован: %s (%s)", combo, name)
            except Exception as exc:
                ok = False
                _log("warning", "Хоткей %s не зарегистрирован: %s", combo, exc)
        return ok

    def _wrap(self, name: str, callback: Callable[[], None]) -> Callable[[], None]:
        def runner() -> None:
            if self._stopped:
                return
            try:
                callback()
            except Exception as exc:
                _log("error", "Ошибка в обработчике хоткея «%s»: %s", name, exc)
        if not self._run_in_thread:
            return runner

        def threaded() -> None:
            threading.Thread(target=runner, name=f"hotkey-{name}", daemon=True).start()
        return threaded

    def _log_once_unavailable(self) -> None:
        if not getattr(self, "_warned", False):
            self._warned = True
            _log("warning", "%s", install_hint())


def register_many(bindings: dict[str, Callable[[], None]], *,
                  logger: logging.Logger | None = None, suppress: bool = False) -> HotkeyManager:
    """Быстрый способ: ``register_many({"alt+c": send, "alt+v": paste})``."""
    manager = HotkeyManager(logger=logger)
    for combo, callback in bindings.items():
        manager.register(combo, callback, suppress=suppress)
    return manager
