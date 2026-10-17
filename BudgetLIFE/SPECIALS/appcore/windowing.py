"""
windowing.py — «приложение как приложение»: имя в диспетчере задач и фокус окна.

Три приёма, каждый решает свою боль:

1. AppUserModelID (LanguageYOI `set_windows_app_id`)
   Без него Windows считает приложение «Python», а уведомления трея и закрепление
   на панели задач путаются между проектами. Ставим `RatAndRu.Specials.Demo`.

2. Копия интерпретатора с именем приложения (DeployAgent `_ensure_named_exe`)
   В диспетчере задач и в трее видно «SpecialsDemo.exe», а не безликое
   «python.exe». Работает без сборки exe: копируем pythonw.exe рядом с app.py.

3. Фокус существующего окна (Трекер `focus_tracker_window`)
   Второй клик по ярлыку НЕ открывает вторую вкладку: приложение ищет окно
   браузера, в заголовке которого есть имя приложения, и поднимает его
   (EnumWindows → ShowWindow → SetForegroundWindow). Фильтр по процессам берём
   из LanguageYOI: окно «Проводник: LanguageYOI» или папка с таким именем —
   это НЕ наше окно, поднимать его нельзя.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0

# Классы окон проводника/рабочего стола — никогда не «наше приложение».
_SHELL_CLASSES = {
    "cabinetwclass", "explorewclass", "progman", "workerw",
    "shell_traywnd", "shell_secondarytraywnd", "taskmanagerwindow",
}
_BROWSER_PROCESSES = {
    "msedge.exe", "chrome.exe", "brave.exe", "vivaldi.exe", "opera.exe",
    "firefox.exe", "librewolf.exe", "chromium.exe", "yandex.exe", "browser.exe",
    "msedgewebview2.exe", "applicationframehost.exe",
}
_INTERPRETERS = {"python.exe", "pythonw.exe", "python3.exe", "python3w.exe"}


def _log(logger, level: str, msg: str, *args) -> None:
    if logger:
        getattr(logger, level, logger.info)(msg, *args)


# ── 1. идентичность приложения ──────────────────────────────────────────────

def set_app_user_model_id(app_id: str, *, title: str | None = None, logger=None) -> bool:
    """Ставит AppUserModelID и (опционально) заголовок консоли.

    Вызывать в самом начале main(): тогда «Диск», трей, уведомления и панель
    задач ассоциируют процесс с приложением, а не с pythonw.exe.
    """
    if not WINDOWS:
        return False
    ok = False
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(app_id))
        ok = True
    except Exception as exc:
        _log(logger, "info", "AppUserModelID не установлен: %s", exc)
    if title:
        set_console_title(title)
    return ok


def set_console_title(title: str, *, logger=None) -> bool:
    """Имя в диспетчере задач для процессов с консолью (запуск через start_debug.bat)."""
    if not WINDOWS:
        return False
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(ctypes.c_wchar_p(str(title)))
        return True
    except Exception as exc:
        _log(logger, "info", "Не удалось задать заголовок консоли: %s", exc)
        return False


# ── 2. имя exe в диспетчере задач ───────────────────────────────────────────

def ensure_named_interpreter(app_dir: str | Path, name: str, *,
                             logger=None) -> Path | None:
    """Создаёт рядом с app.py копию pythonw.exe с именем `<name>.exe`.

    Идемпотентно: если файл уже есть — просто возвращает путь. Копия весит
    копейки (основной код — в python3x.dll), зато в диспетчере задач и в
    «Автозагрузке» видно имя приложения. Запуск: `<name>.exe app.py`.
    """
    if not WINDOWS:
        return None
    target = Path(app_dir) / f"{name}.exe"
    # Штамп «копия доделана» — приём LanguageYOI: start.vbs использует именованный
    # exe ТОЛЬКО при наличии штампа, иначе недописанная копия молча ломала запуск.
    stamp = Path(app_dir) / f"{name}.launcher"
    try:
        if target.exists() and stamp.exists():
            return target
        source = Path(sys.executable)
        if source.name.lower() not in _INTERPRETERS:
            # Проект уже собран в exe или запущен странным интерпретатором — не трогаем.
            _log(logger, "info", "Именованная копия не нужна: %s", source.name)
            return None
        if stamp.exists():
            stamp.unlink()                      # пересоздаём: копия могла быть битой
        shutil.copy2(source, target)
        stamp.write_text(f"{source.name}\n{target.stat().st_size}\n", encoding="ascii")
        _log(logger, "info", "Создан %s (для имени в диспетчере задач)", target.name)
        return target
    except Exception as exc:
        _log(logger, "warning", "Не удалось создать %s: %s", target.name, exc)
        return None


# ── 3. фокус окна ───────────────────────────────────────────────────────────

def _process_name(pid: int) -> str:
    """Имя exe процесса (для фильтра «это окно браузера или проводника»)."""
    if not WINDOWS or not pid:
        return ""
    try:
        import psutil
        return psutil.Process(int(pid)).name().lower()
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf_len = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(buf_len)):
                return Path(buf.value).name.lower()
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def _window_class(hwnd) -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value.lower()
    except Exception:
        return ""


def find_app_window(title_hints: list[str], *, logger=None):
    """:return: hwnd окна, в заголовке которого есть одна из подсказок, иначе None.

    Проверяем: окно видимо, класс не системный, процесс — браузер/интерпретатор/
    именованный exe приложения, в заголовке — имя приложения.
    """
    if not WINDOWS:
        return None
    hints = [str(h).lower() for h in title_hints if h]
    if not hints:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        allowed = _BROWSER_PROCESSES | _INTERPRETERS

        found = {"hwnd": None}

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            if _window_class(hwnd) in _SHELL_CLASSES:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if not length:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.lower()
            if not any(hint in title for hint in hints):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = _process_name(pid.value)
            if proc and proc not in allowed and not proc.startswith(hints[0].split()[0]):
                return True
            found["hwnd"] = hwnd
            return False   # останавливаем перебор

        user32.EnumWindows(_callback, 0)
        return found["hwnd"]
    except Exception as exc:
        _log(logger, "info", "Поиск окна не удался: %s", exc)
        return None


def focus_window(hwnd, *, logger=None) -> bool:
    """Поднимает окно наверх. False — если Windows не дала (тогда откроем вкладку)."""
    if not WINDOWS or not hwnd:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)          # SW_RESTORE — из свёрнутого состояния
        if user32.SetForegroundWindow(hwnd):
            return True
        # Иногда Windows блокирует смену фокуса чужому процессу: обходной путь.
        user32.SwitchToThisWindow(hwnd, True)
        return True
    except Exception as exc:
        _log(logger, "info", "Не удалось поднять окно: %s", exc)
        return False


def focus_or_open(url: str, title_hints: list[str], *, logger=None) -> str:
    """Главная функция для меню трея и второго запуска.

    Возвращает: "focused" (подняли существующее окно) | "opened" (открыли браузер).
    """
    from . import netutil
    hwnd = find_app_window(title_hints, logger=logger)
    if hwnd and focus_window(hwnd, logger=logger):
        _log(logger, "info", "Окно приложения найдено и поднято: %s", title_hints)
        return "focused"
    netutil.open_url(url)
    _log(logger, "info", "Открываю браузер: %s", url)
    return "opened"


def bring_console_forward() -> None:
    """Поднять консольное окно текущего процесса (для режима отладки)."""
    if not WINDOWS:
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def message_box(text: str, title: str = "", *, style: int = 0x40) -> None:
    """Простой MessageBox для аварийных случаев (Python не найден и т.п.).

    style 0x40 = иконка информации, 0x30 = предупреждение, 0x10 = ошибка.
    """
    if not WINDOWS:
        print(f"[{title}] {text}")
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, str(text), str(title or "Сообщение"), style)
    except Exception:
        pass
