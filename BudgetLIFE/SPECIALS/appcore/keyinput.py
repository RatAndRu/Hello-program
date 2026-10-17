"""
keyinput.py — эмуляция клавиатуры и мыши (для «умных» приложений и телефона-пульта).

Взято из Телепульта (нажатия через WinAPI `keybd_event` — работают даже там, где
pyautogui «не доходит», например в играх и окнах с высокими правами) и bridge
(сначала отпустить модификаторы Alt/Ctrl/Shift, потом нажимать Ctrl+V — иначе
получается «Alt+V» и ничего не вставляется).

ФИЛОСОФИЯ БЕЗОПАСНОСТИ
----------------------
  * Все функции возвращают True/False и никогда не бросают исключения: приложение
    не должно падать из-за того, что мышь не подвинулась.
  * Никаких «опасных» действий (выключение ПК, запуск программ) здесь нет —
    это прикладной уровень. Здесь только клавиши и мышь.
  * На не-Windows используется pyautogui/pynput, если они есть; иначе функции
    честно возвращают False (приложение продолжает работать).
"""

from __future__ import annotations

import logging
import os
import time

WINDOWS = os.name == "nt"

# Виртуальные коды Windows (VK_*) для служебных клавиш — приём Телепульта.
VK_CODES: dict[str, int] = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "shift": 0x10,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "pause": 0x13, "capslock": 0x14,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "pageup": 0x21, "pagedown": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "insert": 0x2D, "delete": 0x2E, "del": 0x2E,
    "winleft": 0x5B, "win": 0x5B, "winright": 0x5C, "apps": 0x5D,
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "separator": 0x6C, "subtract": 0x6D,
    "decimal": 0x6E, "divide": 0x6F,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "numlock": 0x90, "scrolllock": 0x91,
    "volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
    "next_track": 0xB0, "prev_track": 0xB1, "stop": 0xB2, "play_pause": 0xB3,
    "media_play_pause": 0xB3, "play": 0xB3, "media_next": 0xB0, "media_prev": 0xB1,
    "browser_back": 0xA6, "browser_forward": 0xA7, "browser_refresh": 0xA8,
    "browser_search": 0xAA, "browser_home": 0xAC,
    "printscreen": 0x2C, "sleep": 0x5F,
}

_MODIFIER_NAMES = ("ctrl", "control", "shift", "alt", "win", "winleft", "winright",
                   "left ctrl", "right ctrl", "left shift", "right shift",
                   "left alt", "right alt")

_logger: logging.Logger | None = None
_user32 = None
_backend: str | None = None


def set_logger(logger: logging.Logger | None) -> None:
    global _logger
    _logger = logger


def _log(level: str, message: str, *args) -> None:
    if _logger:
        getattr(_logger, level, _logger.info)(message, *args)


def _windows():
    """Ленивая загрузка user32 (вне Windows — None)."""
    global _user32
    if not WINDOWS:
        return None
    if _user32 is None:
        try:
            import ctypes
            _user32 = ctypes.windll.user32
        except Exception as exc:
            _log("warning", "WinAPI недоступен: %s", exc)
            _user32 = False
    return _user32 or None


def backend() -> str:
    """Чем работаем: ``winapi`` | ``pyautogui`` | ``pynput`` | ``none``."""
    global _backend
    if _backend:
        return _backend
    if _windows():
        _backend = "winapi"
    elif _module("pyautogui"):
        _backend = "pyautogui"
    elif _module("pynput"):
        _backend = "pynput"
    else:
        _backend = "none"
    return _backend


def _module(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def available() -> bool:
    """Есть ли вообще способ эмулировать ввод (нужно для пунктов меню трея)."""
    return backend() != "none"


# ── клавиши ─────────────────────────────────────────────────────────────────

def _vk(name: str) -> int | None:
    """VK-код клавиши: служебные по таблице, одиночные символы — по ASCII."""
    key = str(name or "").strip().lower()
    if key in VK_CODES:
        return VK_CODES[key]
    if len(key) == 1:
        code = _user32.VkKeyScanW(key) if WINDOWS and _user32 else None
        if code and code != -1:
            return int(code) & 0xFF
        return ord(key.upper()) if key.isalnum() else None
    return None


def press_key(key: str, *, presses: int = 1, interval: float = 0.02) -> bool:
    """Одно нажатие клавиши (поддерживает служебные имена: ``enter``, ``volume_up``)."""
    for _ in range(max(1, int(presses))):
        if not _press_once(key):
            return False
        time.sleep(interval)
    return True


def _press_once(key: str) -> bool:
    backend_name = backend()
    if backend_name == "winapi":
        code = _vk(key)
        if code is None:
            return False
        try:
            user32 = _windows()
            user32.keybd_event(code, 0, 0, 0)                 # WM_KEYDOWN
            time.sleep(0.01)
            user32.keybd_event(code, 0, 2, 0)                 # KEYEVENTF_KEYUP
            return True
        except Exception as exc:
            _log("warning", "keybd_event(%s) не сработал: %s", key, exc)
            return False
    if backend_name == "pyautogui":
        try:
            import pyautogui
            pyautogui.press(key)
            return True
        except Exception:
            return False
    if backend_name == "pynput":
        try:
            from pynput.keyboard import Controller, Key
            controller = Controller()
            special = getattr(Key, str(key).lower(), None)
            controller.press(special or str(key))
            controller.release(special or str(key))
            return True
        except Exception:
            return False
    return False


def hotkey(*keys: str) -> bool:
    """Сочетание клавиш: ``hotkey("ctrl", "shift", "f5")``."""
    names = [str(key) for key in keys if key]
    if not names:
        return False
    backend_name = backend()
    if backend_name == "winapi":
        codes = [_vk(name) for name in names]
        if any(code is None for code in codes):
            return False
        try:
            user32 = _windows()
            for code in codes:
                user32.keybd_event(code, 0, 0, 0)
                time.sleep(0.01)
            for code in reversed(codes):
                user32.keybd_event(code, 0, 2, 0)
                time.sleep(0.01)
            return True
        except Exception as exc:
            _log("warning", "Сочетание %s не сработало: %s", "+".join(names), exc)
            return False
    if backend_name == "pyautogui":
        try:
            import pyautogui
            pyautogui.hotkey(*names)
            return True
        except Exception:
            return False
    if backend_name == "pynput":
        try:
            from pynput.keyboard import Controller, Key
            controller = Controller()
            resolved = [getattr(Key, name.lower(), None) or name for name in names]
            for key in resolved:
                controller.press(key)
            for key in reversed(resolved):
                controller.release(key)
            return True
        except Exception:
            return False
    return False


def type_text(text: str, *, interval: float = 0.0) -> bool:
    """Печатает текст (для юникода на Windows используется буфер обмена).

    Надёжнее всего — через буфер + Ctrl+V: keybd_event не умеет юникод напрямую
    (приём Телепульта). Для «латинницы» работает посимвольный ввод.
    """
    text = str(text or "")
    if not text:
        return False
    if text.isascii() and backend() == "winapi":
        ok = True
        for char in text:
            if char == "\n":
                ok = press_key("enter") and ok
                continue
            if char == "\t":
                ok = press_key("tab") and ok
                continue
            ok = press_key(char) and ok
            if interval:
                time.sleep(interval)
        return ok
    from . import clipboard
    return clipboard.paste_text(text, restore=True)


def release_modifiers() -> None:
    """Отпускает Alt/Ctrl/Shift/Win — иначе хоткей превращается в чужие комбинации.

    Приём bridge: перед «чистым» Ctrl+C обязательно, иначе получится Alt+C.
    """
    if not WINDOWS:
        return
    for name in _MODIFIER_NAMES:
        code = _vk(name)
        if code is None:
            continue
        try:
            _windows().keybd_event(code, 0, 2, 0)
        except Exception:
            continue


# ── мышь ────────────────────────────────────────────────────────────────────

def mouse_move(dx: int, dy: int) -> bool:
    """Сдвигает курсор на (dx, dy) — относительное движение (мышь с телефона)."""
    if WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.mouse_event(0x0001, int(dx), int(dy), 0, 0)
            return True
        except Exception:
            pass
    if _module("pyautogui"):
        try:
            import pyautogui
            pyautogui.moveRel(int(dx), int(dy), duration=0)
            return True
        except Exception:
            return False
    return False


def mouse_click(*, right: bool = False) -> bool:
    """Клик левой/правой кнопкой в текущей позиции курсора."""
    if WINDOWS:
        try:
            import ctypes
            flags = 0x0008 | 0x0010 if right else 0x0002 | 0x0004   # DOWN|UP
            ctypes.windll.user32.mouse_event(flags, 0, 0, 0, 0)
            return True
        except Exception:
            pass
    if _module("pyautogui"):
        try:
            import pyautogui
            pyautogui.rightClick() if right else pyautogui.click()
            return True
        except Exception:
            return False
    return False


def mouse_scroll(steps: int) -> bool:
    """Прокрутка колесом (положительное — вверх)."""
    if WINDOWS:
        try:
            import ctypes
            ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(steps) * 120, 0)
            return True
        except Exception:
            pass
    if _module("pyautogui"):
        try:
            import pyautogui
            pyautogui.scroll(int(steps) * 200)
            return True
        except Exception:
            return False
    return False
