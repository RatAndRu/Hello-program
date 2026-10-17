"""
firewall.py — доступ с телефона без «дыры в интернет».

Взято из LanguageYOI (shared.py: firewall_rule_command / allow_phone_access).
Ключевые детали, которые важно не потерять:
  * profile=private  — правило работает только для домашней/рабочей сети,
    в общественном Wi-Fi порт остаётся закрытым;
  * remoteip=localsubnet — открываем порт ТОЛЬКО своей подсети, а не всему миру;
  * перед добавлением проверяем, нет ли уже такого правила (без прав админа);
  * netsh требует прав администратора → если их нет, возвращаем понятный текст,
    который трей покажет уведомлением, а не «тихую ошибку».

Для приложений, к которым телефон не подключается, правило НЕ создаётся:
по умолчанию сервер слушает 127.0.0.1 (см. docs/PORTS.md, раздел «Безопасность»).
"""

from __future__ import annotations

import os
import subprocess

WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0

DEFAULT_PROFILE = "private"
DEFAULT_REMOTE = "localsubnet"


def _log(logger, level: str, msg: str, *args) -> None:
    if logger:
        getattr(logger, level, logger.info)(msg, *args)


def is_admin() -> bool:
    """Запущен ли процесс с правами администратора (netsh без них не сработает)."""
    if not WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def rule_command(port: int, name: str, *, profile: str = DEFAULT_PROFILE,
                 remoteip: str = DEFAULT_REMOTE) -> list[str]:
    """Команда netsh для добавления правила (без выполнения — удобно тестировать)."""
    return ["netsh", "advfirewall", "firewall", "add", "rule",
            f"name={name}", "dir=in", "action=allow", "protocol=TCP",
            f"localport={int(port)}", f"profile={profile}", f"remoteip={remoteip}"]


def rule_exists(name: str, port: int | None = None, *, run=None) -> bool:
    """Есть ли правило с таким именем (проверка НЕ требует прав админа)."""
    if not WINDOWS:
        return False
    runner = run or subprocess.run
    try:
        result = runner(["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                        capture_output=True, text=True, timeout=10, creationflags=CREATE_NO_WINDOW)
    except Exception:
        return False
    if getattr(result, "returncode", 1) != 0:
        return False
    output = str(getattr(result, "stdout", "") or "")
    if not output.strip():
        return False
    return True if port is None else str(int(port)) in output


def ensure_rule(port: int, name: str, *, logger=None, run=None,
                profile: str = DEFAULT_PROFILE, remoteip: str = DEFAULT_REMOTE) -> tuple[bool, str]:
    """Открывает порт для домашней сети. Возвращает (успех, пояснение для UI)."""
    if not WINDOWS:
        return False, "Брандмауэр настраивается только в Windows"
    if rule_exists(name, port, run=run):
        return True, f"Порт {port} уже открыт для домашней сети"
    if not is_admin():
        return False, ("Нужны права администратора: запустите проект от имени администратора "
                       "или добавьте правило вручную: " +
                       " ".join(rule_command(port, name, profile=profile, remoteip=remoteip)))
    runner = run or subprocess.run
    try:
        result = runner(rule_command(port, name, profile=profile, remoteip=remoteip),
                        capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW)
    except Exception as exc:
        return False, f"Не удалось выполнить netsh: {exc}"
    ok = getattr(result, "returncode", 1) == 0
    if ok:
        _log(logger, "info", "Правило брандмауэра %r открыло порт %s для %s",
             name, port, remoteip)
        return True, f"Порт {port} открыт для домашней сети (профиль {profile})"
    detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
    _log(logger, "warning", "netsh вернул ошибку для порта %s: %s", port, detail[:200])
    return False, detail[:200] or "netsh вернул ошибку"


def remove_rule(name: str, *, logger=None) -> bool:
    """Убирает правило (при удалении приложения)."""
    if not WINDOWS:
        return False
    try:
        result = subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                                 f"name={name}"], capture_output=True, text=True, timeout=20,
                                creationflags=CREATE_NO_WINDOW)
        ok = result.returncode == 0
        _log(logger, "info" if ok else "warning", "Удаление правила брандмауэра %r: %s",
             name, "ок" if ok else (result.stderr or result.stdout or "")[:160])
        return ok
    except Exception as exc:
        _log(logger, "warning", "Ошибка удаления правила: %s", exc)
        return False
