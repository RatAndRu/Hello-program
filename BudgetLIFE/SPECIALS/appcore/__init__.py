"""
appcore — «золотой стандарт» общего кода для локальных PWA-приложений (Flask + трей).

Идея: каждый новый проект собирается из одних и тех же проверенных кирпичей,
чтобы не повторять одни и те же грабли (порты, pythonw, автозапуск, диспетчер
задач, реестр, hot-reload, PWA-кэш, потеря данных при записи).

ОТКУДА ВЗЯТО (см. SPECIALS/README.md — подробная таблица):
  logutil     — LanguageYOI (ротация логов 1 МБ) + DeployAgent (sys.excepthook)
  jsonstore   — LanguageYOI (atomic write: tmp + fsync + os.replace, бэкапы)
  ports       — LanguageYOI (проверка личности сервера по HTTP), DnD's (port.txt),
                Cooker/PlotMaker (динамический выбор), Трекер (убийство старого на порту)
  singleton   — DeployAgent (порт-лок с повторами), LanguageYOI (именованный мьютекс)
  tray        — pystray из Cooker/DeployAgent/Трекера/Телепульта + фолбэк без pystray
  autostart   — Cooker/DeployAgent/BLIND_PC (HKCU\\...\\Run), Трекер (URI-протокол),
                shedevrum_bot (ярлык в Startup)
  windowing   — LanguageYOI (AppUserModelID, фильтр окон, имена в диспетчере задач),
                DeployAgent (копия pythonw.exe с именем приложения), Трекер (фокус окна)
  hotreload   — DeployAgent + BLIND_PC (перезапуск при изменении кода, memory-guard)
  pwa         — bridge (share_target GET/POST, SW-перехват POST), LanguageYOI (Share),
                Трекер/Телепульт (manifest, sw.js), BLIND_PC (QR)
  flask_integration — общие маршруты: /api/identity, /api/health, /manifest.json, /sw.js, /api/share

ПРИКЛАДНЫЕ МОДУЛИ (то, что раньше копировалось между проектами кусками):
  textutil    — раскладка RU↔EN, «кривой» регистр, безопасный калькулятор (без eval),
                HEX-цвет, чистая ссылка, безопасное имя файла, русские числительные
  clipboard   — буфер обмена: файлы (CF_HDROP), номер изменения, вставка БЕЗ затирания
                буфера, фильтр «мусорных» подписей, дедупликация по хешу
  keyinput    — клавиши/мышь: WinAPI keybd_event или pyautogui/pynput, медиа-клавиши,
                отпускание модификаторов перед Ctrl+C/V
  gui         — один Tk-root в своём потоке: всплывающие подсказки, отчёты, диалоги
  hotkeys     — глобальные хоткеи с безопасным отказом и перепривязкой «на ходу»
  sqlite_store — SQLite: миграции по user_version, авто-бэкапы (API SQLite),
                восстановление со safety-копией, integrity_check, экспорт
  events      — живые обновления в браузере без WebSocket (SSE): телефон и ПК
                видят одно и то же состояние, счётчик клиентов, тосты
  qr          — QR-код без зависимостей: SVG и PNG (свой кодировщик), нужен,
                когда пакета qrcode нет, а адрес для телефона показать надо
  versioning  — бэкапы данных архивом (ZIP + манифест), восстановление со
                страховочной копией, экспорт/импорт JSON — «данные не теряются»
  uri         — URI-команды myapp://… : разбор, таблица команд, передача
                команды работающему экземпляру (Трекер, BLIND_PC)
  spaced      — интервальные повторения SM-2: когда показать карточку снова
  watchdog    — надзиратель за сервером: упал поток или сервер молчит —
                приложение поднимается заново (DnD's, DeployAgent)

ПРАВИЛА ПОЛЬЗОВАНИЯ:
  * Модули импортируются как обычный пакет: `from appcore import ports, tray, ...`
  * Код безопасен на не-Windows: всё, что нельзя выполнить, тихо деградирует
    с записью в лог (важно для отладки и для запуска «на посмотреть» где угодно).
  * Windows-специфика изолирована: winreg / ctypes / netsh / PowerShell.
  * Никаких жёстких путей вида C:\\AI_Projects\\... — только пути относительно файла.
"""

__version__ = "1.2.0"

__all__ = [
    # инфраструктура приложения
    "paths", "logutil", "jsonstore", "netutil", "processes", "ports",
    "singleton", "autostart", "firewall", "windowing", "tray", "hotreload",
    "pwa", "flask_integration",
    # прикладные «фишки», собранные по проектам
    "textutil", "clipboard", "keyinput", "gui", "hotkeys", "sqlite_store", "events",
    "qr", "versioning", "uri", "spaced", "watchdog",
    # утилиты пакета
    "pystray_available", "safe_import", "module_available", "require_module",
]

import logging
import sys


def pystray_available() -> bool:
    """Есть ли pystray (трей). Ошибка импорта не должна ронять приложение."""
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:  # pragma: no cover - зависит от окружения
        return False


def module_available(module_name: str) -> bool:
    """Есть ли модуль (без импорта — не тратит время и не падает).

    Понимает и внешние пакеты (``"pystray"``), и свои модули (``"qr"`` —
    он же ``"appcore.qr"``): так проект может проверить наличие возможности,
    не спотыкаясь о разные формы имени.
    """
    import importlib.util

    names = [module_name]
    if "." not in module_name:
        names.append(f"{__package__ or 'appcore'}.{module_name}")
    for name in names:
        try:
            if importlib.util.find_spec(name) is not None:
                return True
        except Exception:
            continue
    return False


def require_module(module_name: str, package: str | None = None,
                   logger: logging.Logger | None = None):
    """Импортирует модуль и, если его нет, ПОДСКАЗЫВАЕТ команду установки.

    Так делают все проекты пользователя: приложение продолжает работать без
    необязательной библиотеки, но в логе есть точная инструкция.
        pystray = require_module("pystray", "pystray")
    """
    try:
        return __import__(module_name)
    except Exception as exc:
        hint = f" Установите: python -m pip install {package or module_name}"
        if logger:
            logger.warning("Модуль %s недоступен (%s).%s", module_name, exc, hint)
        return None


def safe_import(module_name: str, logger: logging.Logger | None = None):
    """Импорт необязательной зависимости без падения.

    Возвращает модуль или None. Так делают все проекты пользователя
    (HAS_PSUTIL / HAS_TRAY / HAS_WATCHDOG), но здесь это в одном месте:
    трей и приложение продолжают работать, а в лог попадает причина.
    """
    try:
        return __import__(module_name)
    except Exception as exc:  # pragma: no cover
        if logger:
            logger.warning("Модуль %s недоступен: %s", module_name, exc)
        return None
