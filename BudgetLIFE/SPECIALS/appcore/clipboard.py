"""
clipboard.py — буфер обмена без сюрпризов.

Собрано из проектов, где буфер обмена — основа работы:
  * bridge       — «вставить с телефона, НЕ затерев обычный буфер» (Win+V не портится);
  * DeployAgent  — чтение файлов из буфера (CF_HDROP) и GetClipboardSequenceNumber
                   вместо холостых проверок раз в секунду;
  * BLIND_PC     — текст в буфер и Ctrl+V от голосовой команды;
  * Телепульт    — вставка текста на компьютер с телефона.

ЧТО ЗДЕСЬ ЕСТЬ
--------------
  get_text() / set_text()        — чтение и запись текста (pyperclip → ctypes → tkinter);
  get_files()                    — список файлов, если в буфере «скопированы файлы»;
  sequence_number()              — номер изменения буфера (0 — не поддержано);
  changed_since(seq)             — «буфер изменился?» без чтения содержимого;
  paste_text(text, ...)          — вставить текст в активное окно, вернув буфер как было.

Почему это отдельный модуль: буфер обмена в Windows — общий ресурс, его нельзя
держать открытым, а любая ошибка (занят другим процессом) не должна ронять
приложение. Поэтому все функции молча возвращают None/False и пишут в лог.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

WINDOWS = os.name == "nt"
_CF_HDROP = 15
_UINT_MAX = 0xFFFFFFFF
_open_attempts = 3
_open_pause = 0.05

_logger: logging.Logger | None = None


def set_logger(logger: logging.Logger | None) -> None:
    """Подключает лог приложения (необязательно)."""
    global _logger
    _logger = logger


def _log(level: str, message: str, *args) -> None:
    if _logger:
        getattr(_logger, level, _logger.info)(message, *args)


# ── текст ───────────────────────────────────────────────────────────────────

def get_text() -> str | None:
    """Текст из буфера обмена. None — если буфер пуст или занят другим процессом."""
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        pass
    if WINDOWS:
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
            user32.OpenClipboard.restype = ctypes.wintypes.BOOL
            user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
            user32.GetClipboardData.restype = ctypes.wintypes.HANDLE
            user32.CloseClipboard.restype = ctypes.wintypes.BOOL
            kernel32 = ctypes.windll.kernel32
            kernel32.GlobalLock.argtypes = [ctypes.wintypes.HANDLE]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HANDLE]
            if not _open_clipboard(user32):
                return None
            try:
                if not user32.IsClipboardFormatAvailable(13):       # CF_UNICODETEXT
                    return None
                handle = user32.GetClipboardData(13)
                if not handle:
                    return None
                pointer = kernel32.GlobalLock(handle)
                if not pointer:
                    return None
                try:
                    return ctypes.wstring_at(pointer)
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        except Exception as exc:
            _log("warning", "Чтение буфера обмена не удалось: %s", exc)
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        value = root.clipboard_get()
        root.destroy()
        return value
    except Exception:
        return None


def set_text(text: str) -> bool:
    """Кладёт текст в буфер обмена. False — если ни один способ не сработал."""
    text = str(text)
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    if WINDOWS:
        try:
            proc = subprocess.run(["clip"], input=text, text=True, shell=True,
                                  capture_output=True, timeout=5)
            if proc.returncode == 0:
                return True
        except Exception:
            pass
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()                       # без update буфер очистится при destroy
        root.destroy()
        return True
    except Exception as exc:
        _log("warning", "Запись в буфер обмена не удалась: %s", exc)
        return False


def clear() -> bool:
    """Очищает буфер (приём bridge: перед «чистым» Ctrl+C обнуляем буфер)."""
    return set_text("")


# ── файлы (Windows, CF_HDROP) ───────────────────────────────────────────────

def get_files() -> list[str]:
    """Пути файлов, если в буфере лежат файлы (Проводник → Ctrl+C). Иначе [].

    Приём DeployAgent: без этого «перетащи файлы в окно» не отличить от
    «скопирован текст».
    """
    if not WINDOWS:
        return []
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        shell32.DragQueryFileW.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.UINT,
                                           ctypes.wintypes.LPWSTR, ctypes.wintypes.UINT]
        shell32.DragQueryFileW.restype = ctypes.wintypes.UINT
        if not _open_clipboard(user32):
            return []
        try:
            if not user32.IsClipboardFormatAvailable(_CF_HDROP):
                return []
            handle = user32.GetClipboardData(_CF_HDROP)
            if not handle:
                return []
            count = shell32.DragQueryFileW(handle, _UINT_MAX, None, 0)
            if count <= 0:
                return []
            buffer = ctypes.create_unicode_buffer(520)
            result = []
            for index in range(count):
                if shell32.DragQueryFileW(handle, index, buffer, 520) > 0:
                    result.append(buffer.value)
            return result
        finally:
            user32.CloseClipboard()
    except Exception as exc:
        _log("warning", "Чтение файлов из буфера не удалось: %s", exc)
        return []


def _open_clipboard(user32) -> bool:
    """Открывает буфер с повторами: его может держать другой процесс."""
    for _ in range(_open_attempts):
        try:
            if user32.OpenClipboard(None):
                return True
        except Exception:
            return False
        time.sleep(_open_pause)
    return False


# ── «мусор» и дедупликация (приёмы bridge) ─────────────────────────────────

# Подписи, которые Windows/Android подставляют сами: «Ножницы», «Поделиться» и т.п.
JUNK_TITLES = {
    "ножницы", "snipping tool", "screenshot", "снимок экрана", "скриншот",
    "photos", "фотографии", "галерея", "gallery", "camera", "камера",
    "share", "поделиться", "файл", "file", "image", "изображение",
    "shared image", "shared file", "image.png", "video", "видео",
}


def is_noise(text: str) -> bool:
    """True, если строка — «мусорная» подпись приложения, а не полезный текст.

    Приём bridge: Windows Share и «Ножницы» любят отдавать вместо содержимого
    собственное имя (``title: "Ножницы"``). Если это не фильтровать, история
    обмена забивается мусором за пару дней.
    """
    if text is None:
        return True
    value = str(text).strip()
    if not value:
        return True
    if len(value) > 80:
        return False                       # длинный текст почти наверняка полезен
    return value.lower() in JUNK_TITLES


def content_hash(value: str | bytes) -> str:
    """Короткий хеш содержимого — для «не плодить дубликаты» и «файл уже был»."""
    import hashlib
    data = value.encode("utf-8", "replace") if isinstance(value, str) else bytes(value)
    return hashlib.sha256(data).hexdigest()[:16]


def file_hash(path: str, *, chunk: int = 1 << 20) -> str | None:
    """Хеш файла (потоково, без загрузки в память). None — если файл не читается."""
    import hashlib
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                block = handle.read(chunk)
                if not block:
                    break
                digest.update(block)
        return digest.hexdigest()[:16]
    except OSError as exc:
        _log("warning", "Не удалось посчитать хеш файла %s: %s", path, exc)
        return None


class Deduplicator:
    """Окно дедупликации по времени: «этот же файл уже приходил минуту назад»."""

    def __init__(self, window_seconds: float = 300.0, *, logger: logging.Logger | None = None) -> None:
        self.window = float(window_seconds)
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()
        if logger:
            set_logger(logger)

    def seen(self, key: str, *, remember: bool = True) -> bool:
        """True, если ключ уже встречался в окне. Новые ключи запоминает."""
        import time
        now = time.time()
        with self._lock:
            for old_key, stamp in list(self._seen.items()):
                if now - stamp > self.window:
                    self._seen.pop(old_key, None)
            if key in self._seen:
                return True
            if remember:
                self._seen[key] = now
            return False

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()


# ── «изменился ли буфер» ────────────────────────────────────────────────────

def sequence_number() -> int:
    """Номер изменения буфера обмена (Windows). 0 — не поддерживается.

    Приём DeployAgent: опрашивать буфер раз в секунду дорого и заметно (буфер
    дёргается), поэтому сравниваем номер — если он не менялся, читать нечего.
    """
    if not WINDOWS:
        return 0
    try:
        import ctypes
        import ctypes.wintypes
        user32 = ctypes.windll.user32
        user32.GetClipboardSequenceNumber.restype = ctypes.wintypes.DWORD
        return int(user32.GetClipboardSequenceNumber())
    except Exception:
        return 0


def changed_since(sequence: int) -> tuple[bool, int]:
    """``(изменился, текущий_номер)``. Если номер недоступен — всегда ``(True, 0)``."""
    current = sequence_number()
    if current == 0 or sequence == 0:
        return True, current
    return current != sequence, current


# ── вставка без затирания буфера ────────────────────────────────────────────

def paste_text(text: str, *, restore: bool = True, keys=None,
               delay_before: float = 0.05, delay_after: float = 0.12) -> bool:
    """Вставляет текст в активное окно через буфер + Ctrl+V, возвращая буфер как был.

    Приём bridge: обычный Ctrl+V затирает то, что пользователь нёс в буфере, и
    «Win+V» перестаёт быть полезным. Здесь мы запоминаем старое содержимое и
    возвращаем его после вставки.

    keys — объект с методом ``hotkey("ctrl", "v")`` (например appcore.keyinput);
    если не передан, используется appcore.keyinput автоматически.
    """
    previous = get_text() if restore else None
    if not set_text(str(text)):
        return False
    time.sleep(delay_before)
    injector = keys
    if injector is None:
        try:
            from . import keyinput
            injector = keyinput
        except Exception as exc:
            _log("warning", "Нет модуля вставки клавиш: %s", exc)
            return False
    ok = bool(injector.hotkey("ctrl", "v"))
    time.sleep(delay_after)
    if restore and previous is not None:
        set_text(previous)
    return ok


def paste_without_clobber(text: str, **kwargs) -> bool:
    """Синоним ``paste_text`` — «вставить, не затерев буфер»."""
    return paste_text(text, restore=True, **kwargs)
