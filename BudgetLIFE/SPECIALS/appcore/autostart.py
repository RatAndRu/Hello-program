"""
autostart.py — автозапуск и системный реестр (Windows, HKCU — без прав админа).

Взято и систематизировано:
  * Cooker / DeployAgent / BLIND_PC — автозапуск через HKCU\\...\\Run;
  * shedevrum_bot / swipe_review    — ярлык в папке «Автозагрузка»;
  * Трекер / BLIND_PC               — регистрация URI-протокола (tracker://) в HKCU\\Software\\Classes;
  * LanguageYOI                     — единый источник имён (AppUserModelID, имена в трее).

ЖЕЛЕЗНЫЕ ПРАВИЛА
----------------
1. Только HKEY_CURRENT_USER: приложению не нужен администратор, а чистка
   пользовательских ключей не ломает систему.
2. В автозапуск ставим НЕ pythonw.exe, а `wscript.exe "…\\start.vbs"`:
   тогда переезд папки, смена версии Python или имени exe ничего не ломают —
   VBS сам найдёт питон и файл (главный урок всех start.vbs в репозитории).
3. Все функции возвращают True/False и НИКОГДА не бросают исключение наружу:
   реестр может быть недоступен (политики, песочница) — приложение обязано жить.
4. Для удаления ключей URI-протокола нужен РЕКУРСИВНЫЙ проход: winreg.DeleteKey
   не удаляет ключ с подключами (BLIND_PC решает это вручную — здесь так же).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CLASSES_KEY = r"Software\Classes"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0


def _log(logger, level: str, msg: str, *args) -> None:
    if logger:
        getattr(logger, level, logger.info)(msg, *args)


# ── командные строки ────────────────────────────────────────────────────────

def quote(value: str | Path) -> str:
    return f'"{value}"'


def launcher_command(app_dir: str | Path, vbs_name: str = "start.vbs") -> str:
    """Команда автозапуска: `wscript.exe "C:\\…\\start.vbs"` (без окна)."""
    return f"wscript.exe {quote(Path(app_dir) / vbs_name)}"


def uri_launcher_command(app_dir: str | Path, vbs_name: str = "start.vbs") -> str:
    """Команда для URI-протокола: `wscript.exe "…\start.vbs" "%1"`.

    Windows подставит вместо `%1` полный адрес (`myapp://notes/add?text=…`),
    а `start.vbs` пробросит его в приложение. Без `%1` команда не сработает
    (частая ошибка при ручной регистрации в реестре).
    """
    return f'{launcher_command(app_dir, vbs_name)} "%1"'


def direct_python_command(script: str | Path, *, named_exe: str | None = None) -> str:
    """Запасной вариант: `"pythonw.exe" "app.py"` (или именованный exe — см. windowing)."""
    script = Path(script)
    if named_exe:
        exe = Path(sys.executable).parent / named_exe
        if exe.exists():
            return f"{quote(exe)} {quote(script)}"
    pyw = Path(sys.executable).parent / ("pythonw.exe" if WINDOWS else Path(sys.executable).name)
    base = pyw if pyw.exists() else Path(sys.executable)
    return f"{quote(base)} {quote(script)}"


# ── HKCU\\…\\Run ────────────────────────────────────────────────────────────

def is_autostart_enabled(name: str) -> bool:
    """Есть ли запись автозапуска с таким именем (читается без прав админа)."""
    if not WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    except Exception:
        return False


def autostart_value(name: str) -> str | None:
    """Текущая команда автозапуска (удобно показать в трее/логе)."""
    if not WINDOWS:
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except Exception:
        return None


def set_autostart(name: str, command: str, enable: bool, *, logger=None) -> bool:
    """Включает/выключает автозапуск. Возвращает успех, не бросает исключений."""
    if not WINDOWS:
        _log(logger, "info", "Автозапуск доступен только в Windows")
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
                _log(logger, "info", "Автозапуск включён: %s = %s", name, command)
            else:
                try:
                    winreg.DeleteValue(key, name)
                    _log(logger, "info", "Автозапуск выключен: %s", name)
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        _log(logger, "warning", "Не удалось изменить автозапуск (%s): %s", name, exc)
        return False


def toggle_autostart(name: str, command: str, *, logger=None) -> bool:
    """Переключает автозапуск и возвращает НОВОЕ состояние."""
    new_state = not is_autostart_enabled(name)
    set_autostart(name, command, new_state, logger=logger)
    return new_state


# ── URI-протокол (myapp://…) ────────────────────────────────────────────────

def register_uri_protocol(scheme: str, command: str, *, display_name: str | None = None,
                          logger=None) -> bool:
    """Регистрирует `scheme://` в HKCU\\Software\\Classes (приём Трекера/BLIND_PC).

    command должен содержать `"%1"` — сюда Windows подставит полный URI.
    Пример: `wscript.exe "C:\\App\\start.vbs" "%1"` — так Трекер принимает
    `tracker://add?type=daily&...` и добавляет напоминание в уже запущенное окно.
    """
    if not WINDOWS:
        return False
    scheme = str(scheme).strip().lower()
    if not scheme or "://" in scheme:
        _log(logger, "error", "Некорректная схема URI: %r", scheme)
        return False
    try:
        import winreg
        title = display_name or f"URL:{scheme} Protocol"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, rf"{CLASSES_KEY}\{scheme}", 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, title)
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                rf"{CLASSES_KEY}\{scheme}\shell\open\command", 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)
        _log(logger, "info", "Протокол %s:// зарегистрирован: %s", scheme, command)
        return True
    except OSError as exc:
        _log(logger, "warning", "Не удалось зарегистрировать %s://: %s", scheme, exc)
        return False


def unregister_uri_protocol(scheme: str, *, logger=None) -> bool:
    """Полностью удаляет схему (рекурсивно, включая shell\\open\\command)."""
    if not WINDOWS:
        return False
    scheme = str(scheme).strip().lower()
    try:
        import winreg

        def _delete_tree(root, path: str) -> None:
            try:
                with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
                    while True:
                        try:
                            sub = winreg.EnumKey(key, 0)
                        except OSError:
                            break
                        _delete_tree(root, path + "\\" + sub)
                winreg.DeleteKey(root, path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                _log(logger, "warning", "Не удалить ключ %s: %s", path, exc)

        _delete_tree(winreg.HKEY_CURRENT_USER, rf"{CLASSES_KEY}\{scheme}")
        _log(logger, "info", "Протокол %s:// удалён", scheme)
        return True
    except Exception as exc:
        _log(logger, "warning", "Ошибка удаления протокола %s://: %s", scheme, exc)
        return False


# ── альтернатива: ярлык в «Автозагрузке» ────────────────────────────────────

def startup_folder() -> Path | None:
    """Папка «Автозагрузка» текущего пользователя."""
    if not WINDOWS:
        return None
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def create_startup_shortcut(app_dir: str | Path, name: str, *,
                            vbs_name: str = "start.vbs", logger=None) -> bool:
    """Создаёт .lnk в «Автозагрузке» через COM WScript.Shell (без pywin32).

    Плюс ярлыка против ключа Run: его видно пользователю в «Диспетчере задач →
    Автозагрузка», где можно отключить в один клик. Минус — нужен COM, поэтому
    это ОПЦИЯ, а основной путь — ключ Run.
    """
    folder = startup_folder()
    if folder is None:
        return False
    app_dir = Path(app_dir)
    target = app_dir / vbs_name
    if not target.exists():
        _log(logger, "warning", "Нет %s — ярлык автозапуска не создан", target)
        return False
    link = folder / f"{name}.lnk"
    ps = (
        "$s = (New-Object -COM WScript.Shell).CreateShortcut('{link}');"
        "$s.TargetPath = 'wscript.exe';"
        "$s.Arguments = '\"{target}\"';"
        "$s.WorkingDirectory = '{cwd}';"
        "$s.WindowStyle = 7;"
        "$s.Description = '{desc}';"
        "$s.Save()"
    ).format(link=str(link).replace("'", "''"), target=str(target).replace("'", "''"),
             cwd=str(app_dir).replace("'", "''"), desc=f"{name} autostart")
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-Command", ps],
                                capture_output=True, text=True, timeout=20,
                                creationflags=CREATE_NO_WINDOW)
        ok = result.returncode == 0 and link.exists()
        _log(logger, "info" if ok else "warning",
             "Ярлык автозапуска %s: %s", link.name, "создан" if ok else "не создан")
        return ok
    except Exception as exc:
        _log(logger, "warning", "Ошибка создания ярлыка: %s", exc)
        return False


def remove_startup_shortcut(name: str, *, logger=None) -> bool:
    folder = startup_folder()
    if folder is None:
        return False
    link = folder / f"{name}.lnk"
    try:
        if link.exists():
            link.unlink()
            _log(logger, "info", "Ярлык автозапуска удалён: %s", link.name)
        return True
    except OSError as exc:
        _log(logger, "warning", "Не удалить ярлык %s: %s", link, exc)
        return False


# ── диагностика автозапуска (для tools/audit_windows.py) ────────────────────

def list_autostart_entries() -> list[tuple[str, str]]:
    """[(имя, команда)] из HKCU\\...\\Run. Помогает найти дубли автозапуска."""
    if not WINDOWS:
        return []
    entries: list[tuple[str, str]] = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                entries.append((str(name), str(value)))
                index += 1
    except Exception:
        pass
    return entries
