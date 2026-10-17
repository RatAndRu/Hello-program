"""
Specials Demo — ЭТАЛОННЫЙ проект (SPECIALS/template).

Скопируйте папку и переименуйте проект:
    python SPECIALS/tools/new_project.py "Моё Приложение" --port-base 5120

Здесь собраны все правила «золотого стандарта» сразу в рабочем виде — каждый
блок помечен, откуда пришла идея (проект-источник). Ничего лишнего: это
одновременно и демо (показывает фишки в интерфейсе), и скелет для нового проекта.

ЧТО ДЕМОНСТРИРУЕТСЯ
  1.  Структура: app.py + start.vbs + stop.vbs + data/ + static/ + templates/ + logs/
  2.  Логи с ротацией, безопасные потоки под pythonw, перехват исключений
  3.  Один экземпляр: мьютекс + порт-лок + HTTP-идентификация (/api/identity)
  4.  Порт из СВОЕГО блока (ports.json) + data/port.txt для трея и ярлыков
  5.  Имя в диспетчере задач: AppUserModelID + SpecialsDemo.exe
  6.  Фокус существующего окна вместо второй вкладки
  7.  Трей: меню, уведомления, автозапуск (HKCU), «поделиться», QR
  8.  PWA: manifest, sw.js, «Поделиться» из системного меню, офлайн-страница
  9.  Данные: атомарная запись JSON + бэкап (JsonStore)
  10. Hot-reload при правке кода + защита от утечки памяти
  11. Брандмауэр для доступа с телефона (только своя подсеть)
  12. Корректный выход: освобождение порта/лока, os._exit без зомби
  13. Инструменты из других проектов: текст (раскладка/калькулятор/ссылки),
      буфер обмена, подсказки поверх окон (gui), клавиши и мышь (keyinput),
      глобальные хоткеи (hotkeys)
  14. URI-команды (specials_demo://notes/add?text=…), приём команд работающим
      экземпляром — как tracker:// в Трекере и blindpc:// в BLIND_PC
  15. Бэкапы данных архивом + восстановление со страховочной копией (LanguageYOI)
  16. Надзиратель: упал сервер — приложение поднимается само (DnD's)
  17. Интервальные повторения SM-2 (LanguageYOI) — готовый алгоритм для учёбы
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

# ── ПОДКЛЮЧЕНИЕ appcore ─────────────────────────────────────────────────────
# В новом проекте appcore лежит РЯДОМ (его копирует new_project.py), поэтому
# строка ниже работает как обычный импорт. Fallback нужен только для запуска
# прямо из SPECIALS/template — чтобы эталон можно было запустить «как есть».
try:
    import appcore
except ImportError:                                  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import appcore

from appcore import (autostart, clipboard, events, firewall, flask_integration, gui,
                     hotkeys, hotreload, jsonstore, keyinput, logutil, netutil,
                     paths as app_paths, ports, singleton, spaced, textutil, tray, uri,
                     versioning, watchdog, windowing)

# ── ПАСПОРТ ПРИЛОЖЕНИЯ (меняет new_project.py) ──────────────────────────────
APP_ID = "specials_demo"          # уникальный id: порты, мьютекс, кэш PWA
APP_NAME = "Specials Demo"        # человеческое имя: трей, заголовок, диспетчер задач
APP_VERSION = "1.0.0"
APP_LETTER = "S"                  # буква на иконке
HOST = "127.0.0.1"                # 0.0.0.0 — только если нужен телефон (см. tray: «Доступ с телефона»)
WANT_LAN = False                  # True → открываем порт в брандмауэре для домашней сети
HOT_RELOAD = True                 # перезапуск при правке кода (выключить в релизе)
MEMORY_LIMIT_MB = 400             # авто-перезапуск при утечке памяти

# Переключатели, которые удобно менять при запуске, не правя код:
#   python app.py --host 0.0.0.0 --lan --no-browser --no-hot-reload --port 5121
OPTIONS = {"host": HOST, "prefer_port": None, "browser": True,
           "hot_reload": HOT_RELOAD, "lan": WANT_LAN}


def parse_args(argv: list[str]) -> dict:
    """Простейший разбор аргументов (без argparse: под pythonw он не нужен)."""
    options = dict(OPTIONS)
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("--host", "--port") and index + 1 < len(argv):
            value = argv[index + 1]
            index += 1
            if arg == "--host":
                options["host"] = value
            else:
                options["prefer_port"] = int(value) if value.isdigit() else None
        elif arg.startswith("--host="):
            options["host"] = arg.split("=", 1)[1]
        elif arg.startswith("--port=") and arg.split("=", 1)[1].isdigit():
            options["prefer_port"] = int(arg.split("=", 1)[1])
        elif arg == "--lan":
            options["lan"] = True
        elif arg == "--no-browser":
            options["browser"] = False
        elif arg == "--no-hot-reload":
            options["hot_reload"] = False
        index += 1
    return options

# ── ПУТИ И ЛОГИ ─────────────────────────────────────────────────────────────
paths = app_paths.AppPaths.for_file(__file__).ensure()
logger = logutil.setup(APP_NAME, paths.log_file())
logutil.log_uncaught(logger)      # падение больше не будет «молчаливым»

logger.info("Пути проекта:\n  %s", paths.describe().replace("\n", "\n  "))

# ── ДАННЫЕ (атомарная запись + бэкап) ───────────────────────────────────────
notes_store = jsonstore.JsonStore(paths.data_file("notes.json"),
                                  default={"notes": []}, logger=logger)
settings_store = jsonstore.JsonStore(paths.data_file("settings.json"),
                                     default={"lan_access": WANT_LAN}, logger=logger)

from flask import Flask, jsonify, render_template, request  # noqa: E402

flask_app = Flask(__name__, static_folder=str(paths.static), static_url_path="/static")
flask_app.config["TEMPLATES_AUTO_RELOAD"] = True

SERVER = {"instance": None, "port": 0, "started": time.time()}

# Живые обновления в браузере без WebSocket: SSE-шина (приёмы bridge и swipe_review).
# Одна открытая страница = один подписчик; publish() рассылает событие всем.
BUS = events.EventBus(logger=logger)

# ── МАРШРУТЫ ПРИЛОЖЕНИЯ ─────────────────────────────────────────────────────

@flask_app.route("/")
def index():
    # HTML отдаётся с no-store (см. flask_integration) — правки видны сразу.
    return render_template("index.html", app_name=APP_NAME, version=APP_VERSION)


@flask_app.route("/api/notes", methods=["GET", "POST", "DELETE"])
def api_notes():
    if request.method == "GET":
        return jsonify({"ok": True, "notes": notes_store.load()["notes"], "app_id": APP_ID})
    payload = request.get_json(silent=True) or {}
    with notes_store.edit() as doc:                # правка + сохранение под одним локом
        if request.method == "POST":
            text = str(payload.get("text", "")).strip()
            if not text:
                return jsonify({"ok": False, "error": "Пустая запись"}), 400
            doc["notes"].insert(0, {"id": int(time.time() * 1000), "text": text[:500],
                                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        else:                                      # DELETE
            note_id = payload.get("id")
            doc["notes"] = [n for n in doc["notes"] if n.get("id") != note_id]
    # Событие увидят ВСЕ открытые страницы (телефон, планшет, второе окно ПК):
    # список заметок обновится сам, без перезагрузки.
    BUS.publish("notes", notes=notes_store.load()["notes"], clients=BUS.client_count())
    return jsonify({"ok": True, "notes": notes_store.load()["notes"]})


@flask_app.route("/api/status")
def api_status():
    return jsonify({
        "app_id": APP_ID, "app": APP_NAME, "version": APP_VERSION,
        "port": SERVER["port"], "pid": __import__("os").getpid(),
        "uptime_sec": int(time.time() - SERVER["started"]),
        "lan_url": netutil.lan_url(SERVER["port"] or 5120, "/"),
        "lan_access": bool(settings_store.load().get("lan_access")),
        "pages": ["/", "/api/notes", "/api/status", "/api/identity", "/api/health",
                  "/api/tools", "/api/tools/text", "/api/tools/clipboard",
                  "/api/tools/overlay", "/api/tools/keys",
                  "/manifest.json", "/sw.js"],
    })


@flask_app.route("/api/autostart", methods=["GET", "POST"])
def api_autostart():
    """Автозапуск через HKCU: без админа, командой wscript start.vbs."""
    command = autostart.launcher_command(paths.base)
    if request.method == "GET":
        return jsonify({"ok": True, "enabled": autostart.is_autostart_enabled(APP_NAME),
                        "command": command})
    desired = bool((request.get_json(silent=True) or {}).get("enabled"))
    ok = autostart.set_autostart(APP_NAME, command, desired, logger=logger)
    return jsonify({"ok": ok, "enabled": autostart.is_autostart_enabled(APP_NAME)})


@flask_app.route("/api/lan-access", methods=["POST"])
def api_lan_access():
    """Открывает порт в брандмауэре только для домашней подсети (нужен админ)."""
    desired = bool((request.get_json(silent=True) or {}).get("enabled"))
    if desired:
        ok, detail = firewall.ensure_rule(SERVER["port"], f"{APP_NAME} (домашняя сеть)",
                                         logger=logger)
        if ok:
            settings_store.save({"lan_access": True})
        return jsonify({"ok": ok, "detail": detail})
    settings_store.save({"lan_access": False})
    return jsonify({"ok": True, "detail": "Правило можно удалить командой netsh (см. логи)"})


@flask_app.route("/api/notify", methods=["POST"])
def api_notify():
    """Показать уведомление трея (демо обратной связи)."""
    text = str((request.get_json(silent=True) or {}).get("text") or "Привет из приложения!")
    ok = TRAY["instance"].notify(text, APP_NAME) if TRAY["instance"] else False
    return jsonify({"ok": ok})


# ── ИНСТРУМЕНТЫ (демонстрация appcore, «фишки» из старых проектов) ──────────
# Каждый маршрут — обёртка над модулем appcore. В новом проекте такие обёртки
# делаются только для того, что реально нужно интерфейсу.

@flask_app.route("/api/tools", methods=["GET"])
def api_tools():
    """Что доступно в этом окружении (чтобы UI не показывал мёртвые кнопки)."""
    return jsonify({
        "ok": True,
        "clipboard": {"text": True, "files": os.name == "nt",
                      "sequence": clipboard.sequence_number() > 0},
        "overlay": gui.available(),
        "hotkeys": hotkeys.available(),
        "keyinput": keyinput.available(),
        "keyinput_backend": keyinput.backend(),
    })


@flask_app.route("/api/tools/text", methods=["POST"])
def api_tools_text():
    """Текстовые утилиты: раскладка, регистр, калькулятор, HEX, чистая ссылка.

    Приёмы DeployAgent: ``ghbdtn`` → ``привет``, ``2+2*2`` → ``6``,
    ``#3fa9f5`` → RGB, из мусорной строки — только домен.
    """
    text = str((request.get_json(silent=True) or {}).get("text") or "")
    looks_like_path = ("/" in text or "\\" in text) and " " not in text.strip()
    return jsonify({
        "ok": True, "input": text,
        "layout": textutil.switch_layout(text),
        "broken_case": textutil.is_broken_case(text),
        "case_variants": textutil.case_variants(text),
        "math": textutil.safe_eval_math(text),
        "hex": textutil.parse_hex_color(text),
        "url": textutil.clean_url(text),
        "numbers": textutil.numbers_in_text(text),
        "filename": textutil.sanitize_filename(text) if looks_like_path else None,
    })


@flask_app.route("/api/tools/clipboard", methods=["GET", "POST"])
def api_tools_clipboard():
    """Буфер обмена: показать содержимое/файлы или положить текст (приём bridge)."""
    if request.method == "GET":
        text = clipboard.get_text()
        files = clipboard.get_files()
        return jsonify({"ok": True, "text": text, "files": files,
                        "is_noise": clipboard.is_noise(text or ""),
                        "hash": clipboard.content_hash(text) if text else None})
    text = str((request.get_json(silent=True) or {}).get("text") or "")
    return jsonify({"ok": clipboard.set_text(text)})


@flask_app.route("/api/tools/overlay", methods=["POST"])
def api_tools_overlay():
    """Показать подсказку поверх окон (приём DeployAgent: под pythonw нет консоли)."""
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text") or "Готово")
    mode = str(payload.get("mode") or "overlay")
    if mode == "report":
        shown = gui.report([text], title=APP_NAME, duration=float(payload.get("duration", 4)))
    else:
        shown = gui.overlay(text, duration=float(payload.get("duration", 2.5)))
    return jsonify({"ok": shown, "hint": "" if shown else "Окна недоступны (нет Tk/дисплея)"})


@flask_app.route("/api/tools/keys", methods=["POST"])
def api_tools_keys():
    """Клавиши и мышь (приёмы Телепульта и bridge) — громкость, медиа, вставка."""
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action") or "")
    value = payload.get("value")
    ok = False
    if action == "media":
        ok = keyinput.press_key(str(value or "play_pause"))
    elif action == "volume":
        step = int(value or 1)
        ok = keyinput.press_key("volume_up", presses=step) if step > 0 \
            else keyinput.press_key("volume_down", presses=abs(step))
    elif action == "paste":
        ok = clipboard.paste_text(str(value or ""))
    elif action == "type":
        ok = keyinput.type_text(str(value or ""))
    elif action == "release_modifiers":
        keyinput.release_modifiers()
        ok = True
    return jsonify({"ok": ok, "action": action,
                    "hint": "" if ok else f"Недоступно (backend={keyinput.backend()})"})


# ── URI-КОМАНДЫ (фишка Трекера и BLIND_PC) ──────────────────────────────────
# Так приложение можно запускать из Win+R, ярлыка, браузера или другого
# приложения. Схему регистрирует tray-пункт «URI-протокол» (autostart).
# Вызывать так: specials_demo://notes/add?text=привет
# Схема URI: в ней допустимы только латиница, цифры, «+», «-», «.» (RFC 3986),
# поэтому имя приложения приводим к допустимому виду (specials_demo → specials-demo).
URI_SCHEME = uri.normalize_scheme(APP_ID)
URI_ROUTER = uri.Router(name=URI_SCHEME)


@URI_ROUTER.command("ping")
def uri_ping() -> dict:
    """Проверка: приложение живо."""
    return {"pong": True, "app": APP_NAME, "version": APP_VERSION}


@URI_ROUTER.command("notes/add")
def uri_note_add(text: str = "") -> dict:
    """Добавляет заметку (и рассылает событие всем открытым страницам)."""
    if not text.strip():
        return {"added": False, "reason": "пустой текст"}
    with notes_store.edit() as doc:
        doc["notes"].append({"id": int(time.time() * 1000), "text": text.strip(),
                             "created_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    BUS.publish("notes", notes=notes_store.load()["notes"])
    return {"added": True, "text": text.strip()}


@URI_ROUTER.command("show")
def uri_show(page: str = "/") -> dict:
    """Открывает окно приложения (повторный клик по ярлыку — не новая копия)."""
    port = SERVER["port"] or ports.block_for(APP_ID).base
    windowing.focus_or_open(netutil.url_for("127.0.0.1", port, page or "/"),
                            [APP_NAME], logger=logger)
    return {"opened": page or "/"}


flask_app.add_url_rule("/api/uri", "appcore_uri", uri.make_flask_view(URI_ROUTER),
                       methods=["POST"])


@flask_app.route("/api/uri/help")
def api_uri_help():  # noqa: ANN202
    """Список URI-команд — чтобы пользователь не гадал."""
    return jsonify({"ok": True, "scheme": URI_SCHEME, "commands": URI_ROUTER.commands(),
                    "help": URI_ROUTER.help_text()})


# ── БЭКАПЫ ДАННЫХ АРХИВОМ (фишка LanguageYOI и Cooker) ──────────────────────
@flask_app.route("/api/backups", methods=["GET", "POST"])
def api_backups():  # noqa: ANN202
    """GET — список архивов и размер данных; POST — сделать бэкап сейчас."""
    folder = versioning.backups_dir(paths.data)
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        info = versioning.create_backup(paths.data, app_name=APP_ID, app_version=APP_VERSION,
                                        keep=int(payload.get("keep", 10)), logger=logger)
        if info is None:
            return jsonify({"ok": False, "error": "Не удалось создать бэкап"})
        return jsonify({"ok": True, "backup": {"name": info.name, "size": info.human_size(),
                                               "files": info.files, "created_at": info.created_at}})
    items = versioning.list_backups(folder)
    return jsonify({"ok": True, "stats": versioning.data_stats(paths.data),
                    "backups": [{"name": i.name, "size": i.human_size(), "files": i.files,
                                 "created_at": i.created_at} for i in items[:20]]})


@flask_app.route("/api/backups/restore", methods=["POST"])
def api_backups_restore():  # noqa: ANN202
    """Возвращает данные из архива (перед этим сохраняет текущие как before_restore_*)."""
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "")
    folder = versioning.backups_dir(paths.data)
    archive = (folder / Path(name).name) if name else versioning.latest_backup(folder) and \
        versioning.latest_backup(folder).path
    if not archive or not Path(archive).exists():
        return jsonify({"ok": False, "error": "Архив не найден"}), 404
    result = versioning.restore_backup(archive, paths.data, logger=logger)
    if result["ok"]:
        BUS.toast(f"Данные восстановлены из {Path(archive).name}")
    return jsonify(result)


# ── ИНТЕРВАЛЬНЫЕ ПОВТОРЕНИЯ (SM-2, фишка LanguageYOI) ───────────────────────
# Демонстрация: одна карточка, живёт в памяти. В реальном проекте состояние
# хранится в JSON/SQLite, а алгоритм остаётся тем же.
CARD = {"state": spaced.new_card()}


@flask_app.route("/api/tools/card", methods=["GET", "POST"])
def api_tools_card():  # noqa: ANN202
    """GET — состояние карточки и подсказки; POST {"grade": "хорошо"} — ответ."""
    if request.method == "POST":
        payload = request.get_json(silent=True) or {}
        grade = payload.get("grade")
        if not isinstance(grade, int):
            grade = spaced.grade_from_button(str(grade)) if grade is not None else None
        if grade is None:
            return jsonify({"ok": False, "error": 'Оценка: 1-5 или «забыл/трудно/хорошо/легко»'})
        CARD["state"] = spaced.review(CARD["state"], int(grade))
    state = CARD["state"]
    return jsonify({"ok": True, "state": state,
                    "due_in_days": spaced.due_in_days(state),
                    "schedule": spaced.schedule(state)})


# ── ЖИВЫЕ СОБЫТИЯ (SSE) ─────────────────────────────────────────────────────
# GET /api/events — поток событий; без Accept: text/event-stream вернёт справку.
events.install(flask_app, BUS, ready=lambda: [
    {"type": "hello", "app": APP_NAME, "version": APP_VERSION},
    {"type": "notes", "notes": notes_store.load()["notes"]},
])


# ── СТАНДАРТНЫЕ МАРШРУТЫ + «ПОДЕЛИТЬСЯ» + PWA ───────────────────────────────
flask_integration.install(flask_app, flask_integration.PWAConfig(
    app_id=APP_ID, app_name=APP_NAME, version=APP_VERSION,
    static_dir=paths.static, data_dir=paths.data, share_dir=paths.data / "shared",
    icon_letter=APP_LETTER, logger=logger, port_getter=lambda: SERVER["port"],
    # on_share не задан → используется save_share(): файлы/текст падают в data/shared/
))

TRAY = {"instance": None}
STOP = threading.Event()


# ── ТРЕЙ ────────────────────────────────────────────────────────────────────

def open_ui() -> None:
    """Поднять уже открытое окно, иначе открыть вкладку (приём Трекера)."""
    port = SERVER["port"] or ports.block_for(APP_ID).base
    windowing.focus_or_open(netutil.url_for("127.0.0.1", port, "/"), [APP_NAME], logger=logger)


def app_url(host: str | None = None) -> str:
    """Адрес для браузера: с телефона — по IP, локально — localhost."""
    port = SERVER["port"] or ports.block_for(APP_ID).base
    host = host or OPTIONS["host"]
    return netutil.url_for("127.0.0.1", port, "/") if host in ("0.0.0.0", "127.0.0.1") \
        else netutil.url_for(host, port, "/")


def copy_url() -> None:
    port = SERVER["port"] or ports.block_for(APP_ID).base
    netutil.copy_to_clipboard(netutil.lan_url(port, "/"))
    if TRAY["instance"]:
        TRAY["instance"].notify("Адрес скопирован в буфер обмена", APP_NAME)


def show_qr() -> None:
    """Сохраняет QR на адрес с телефона и открывает картинку."""
    port = SERVER["port"] or ports.block_for(APP_ID).base
    url = netutil.lan_url(port, "/")
    path = netutil.save_qr(url, paths.data / "qr")
    if path:
        netutil.open_url(Path(path).as_uri())
    elif TRAY["instance"]:                  # бывает только если текст длиннее QR
        TRAY["instance"].notify("Не удалось собрать QR — смотрите лог", APP_NAME)
    logger.info("QR для телефона: %s → %s", url, path)


def toggle_uri_protocol() -> None:
    """Регистрирует схему вида ``specials_demo://`` в реестре (HKCU)."""
    # Приём Трекера: схема + передача аргументов в уже запущенное приложение.
    command = autostart.uri_launcher_command(paths.base, "start.vbs")
    ok = autostart.register_uri_protocol(URI_SCHEME, command, display_name=f"{APP_NAME} URL",
                                         logger=logger)
    if ok:
        example = f"{URI_SCHEME}://notes/add?text=привет"
        clipboard.set_text(example)
        if TRAY["instance"]:
            TRAY["instance"].notify(f"URI-команды включены. Пример скопирован: {example}", APP_NAME)
    elif TRAY["instance"]:
        TRAY["instance"].notify("Не удалось зарегистрировать URI-схему — смотрите лог", APP_NAME)
    logger.info("URI-схема %s:// — %s; команды: %s", URI_SCHEME, ok, URI_ROUTER.commands())


def open_data_folder() -> None:
    try:
        if sys.platform == "win32":
            import os
            os.startfile(str(paths.data))       # noqa: S606
        else:
            netutil.open_url(paths.data.as_uri())
    except Exception as exc:
        logger.warning("Не удалось открыть папку данных: %s", exc)


def on_toggle_autostart() -> None:
    command = autostart.launcher_command(paths.base)
    enabled = autostart.toggle_autostart(APP_NAME, command, logger=logger)
    if TRAY["instance"]:
        TRAY["instance"].update_menu()
        TRAY["instance"].notify(f"Автозапуск: {'включён' if enabled else 'выключен'}", APP_NAME)


def on_toggle_lan() -> None:
    if not WANT_LAN:
        if TRAY["instance"]:
            TRAY["instance"].notify("Сначала включите WANT_LAN = True в app.py", APP_NAME)
        return
    ok, detail = firewall.ensure_rule(SERVER["port"], f"{APP_NAME} (домашняя сеть)", logger=logger)
    if TRAY["instance"]:
        TRAY["instance"].notify(detail, APP_NAME)
    logger.info("Доступ с телефона: ok=%s (%s)", ok, detail)


def restart_now() -> None:
    """Перезапуск по кнопке: освобождаем лок и запускаем start.vbs заново."""
    logger.info("Перезапуск по запросу из трея")
    STOP.set()
    shutdown_server()
    singleton.relaunch_app(paths.base, "start.vbs", logger=logger)
    singleton.exit_process(0)


def quit_app(*, cleanup: bool = True) -> None:
    """Выход: остановить сервер, снять иконку, освободить лок (без «зомби»)."""
    logger.info("Выход приложения")
    STOP.set()
    if TRAY["instance"]:
        TRAY["instance"].stop()
    if cleanup:
        shutdown_server()


def shutdown_server() -> None:
    server = SERVER.get("instance")
    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except Exception as exc:
            logger.warning("Ошибка остановки сервера: %s", exc)
        SERVER["instance"] = None


def build_tray() -> tray.TrayApp:
    config = tray.TrayConfig(
        app_id=APP_ID,
        title=f"{APP_NAME} v{APP_VERSION}",
        tooltip_url=netutil.lan_url(SERVER["port"] or ports.block_for(APP_ID).base, "/"),
        icon_letter=APP_LETTER,
        items=[
            tray.TrayItem.title(f"{APP_NAME} v{APP_VERSION}"),
            tray.TrayItem("Открыть", open_ui, default=True),   # левый клик по иконке
            tray.TrayItem("Копировать адрес", copy_url),
            tray.TrayItem("QR-код для телефона", show_qr),
            tray.TrayItem("Открыть папку данных", open_data_folder),
            tray.TrayItem.separator_item(),
            tray.TrayItem("Автозапуск",
                          on_toggle_autostart,
                          checked=lambda: autostart.is_autostart_enabled(APP_NAME),
                          enabled=True),
            tray.TrayItem("Доступ с телефона", on_toggle_lan, enabled=WANT_LAN),
            tray.TrayItem(f"Включить {URI_SCHEME}:// (URI-команды)", toggle_uri_protocol),
            tray.TrayItem.separator_item(),
            tray.TrayItem("Перезапустить", restart_now),
            tray.TrayItem("Выход", lambda: (quit_app(), singleton.exit_process(0))),
        ],
    )
    return tray.TrayApp(config, logger=logger, on_quit=shutdown_server)


# ── ЗАПУСК ──────────────────────────────────────────────────────────────────

def handle_uri_arguments() -> bool:
    """Если приложение запущено URI-ссылкой — передаём команду и выходим.

    Windows при вызове ``app://...`` запускает НОВЫЙ процесс. Он не должен
    поднимать второй сервер: команда уходит работающему экземпляру через
    ``/api/uri``, а этот процесс завершается (приём Трекера).
    """
    raw = uri.argv_uri(scheme=URI_SCHEME)
    if not raw:
        return False
    answer = uri.send_to_running(raw, ports.block_for(APP_ID).base, timeout=2.5)
    if answer is None:
        running = ports.find_running(APP_ID, "127.0.0.1")
        if running and running.port:
            answer = uri.send_to_running(raw, running.port, timeout=2.5)
    if answer is None:
        logger.info("URI %s: работающий экземпляр не ответил — команда выполнена локально", raw)
        URI_ROUTER.dispatch(raw)                # первый запуск: выполняем у себя
        return False
    logger.info("URI %s передан работающему экземпляру: %s", raw, answer)
    return True


def handle_second_launch(host: str) -> bool:
    """Если приложение уже работает — поднимаем его окно и выходим.

    Проверка идёт по /api/identity, а НЕ по занятости порта: на порту может
    оказаться чужая программа (ровно этот случай ловили в репозитории).
    """
    for block in (ports.block_for(APP_ID),):
        running = ports.find_running(APP_ID, host, block.ports)
        if not running:
            return False
        url = netutil.url_for("127.0.0.1", running.port, "/")
        logger.info("Уже запущено (pid=%s на порту %s) — открываю существующее окно",
                    running.identity.get("pid"), running.port)
        windowing.focus_or_open(url, [APP_NAME], logger=logger)
        return True


def main() -> None:
    host = OPTIONS["host"]
    # 1. Имя в диспетчере задач + AppUserModelID (до всего остального!).
    windowing.set_app_user_model_id(f"RatAndRu.Specials.{APP_ID}", title=f"{APP_NAME} v{APP_VERSION}")
    windowing.ensure_named_interpreter(paths.base, APP_NAME.replace(" ", ""), logger=logger)

    # 2. Хрупкие иконки PWA: генерируем сами, а не ищем файлом.
    flask_integration.install_static_icons(flask_app, paths.static, APP_LETTER, logger=logger)

    # 3a. Запуск по URI-ссылке (myapp://...) — передаём команду и выходим.
    if handle_uri_arguments():
        singleton.exit_process(0)

    # 3. Второй запуск? Открываем уже работающее окно и выходим.
    if handle_second_launch(host):
        singleton.exit_process(0)

    # 4. Порт-лок: защищает окно между проверкой и стартом сервера.
    lock_port = singleton.lock_port_for(APP_ID)
    if not singleton.acquire_lock_port(lock_port, logger=logger):
        # Кто-то стартует параллельно: дождёмся его и откроем окно.
        ready = ports.wait_until_ready(APP_ID, host, ports.candidates(APP_ID, prefer=None),
                                       timeout=15.0, logger=logger, data_dir=paths.data)
        if ready:
            windowing.focus_or_open(netutil.url_for("127.0.0.1", ready, "/"), [APP_NAME], logger=logger)
        else:
            windowing.message_box("Второй экземпляр уже запускается. Попробуйте ещё раз.",
                                  APP_NAME, style=0x30)
        singleton.exit_process(0)
    singleton.acquire_mutex(APP_ID)      # дополнительный, самый быстрый уровень

    # 5. Сервер: порт только из СВОЕГО блока + синхронный bind (ошибка видна сразу).
    server, port = flask_integration.serve_with_fallback(
        flask_app, app_id=APP_ID, host=host,
        candidate_ports=ports.candidates(APP_ID, prefer=OPTIONS["prefer_port"]),
        logger=logger)
    if server is None:
        logger.error("Не удалось поднять сервер — нет свободных портов в блоке")
        windowing.message_box("Не удалось поднять сервер: все порты блока заняты.",
                              APP_NAME, style=0x10)
        singleton.exit_process(1)

    SERVER.update(instance=server, port=port, started=time.time())
    ports.write_port_file(paths.data, port, APP_ID)      # data/port.txt для внешних читателей
    logger.info("Приложение доступно: %s", netutil.url_for(host, port, "/"))

    # 6. Доступ с телефона (только если включён в паспорте приложения).
    if OPTIONS["lan"]:
        ok, detail = firewall.ensure_rule(port, f"{APP_NAME} (домашняя сеть)", logger=logger)
        logger.info("Доступ с телефона: %s (%s)", ok, detail)

    # 7. Трей (в главном потоке — требование pystray в Windows).
    TRAY["instance"] = build_tray()
    if TRAY["instance"].available:
        TRAY["instance"].notify(f"Запущено на порту {port}", APP_NAME)
    else:
        logger.warning("Трей недоступен (%s). Интерфейс: http://127.0.0.1:%s",
                       TRAY["instance"].unavailable_reason(), port)
        logger.warning("%s", tray.install_hint(TRAY["instance"].unavailable_reason()))

    # 8. Hot-reload (по желанию) + защита от утечек памяти.
    if OPTIONS["hot_reload"]:
        hotreload.HotReloadWatcher(
            paths.base,
            hotreload.make_restart_handler(paths.base, vbs_name="start.vbs",
                                           before_exit=lambda: (STOP.set(), shutdown_server()),
                                           logger=logger),
            memory_limit_mb=MEMORY_LIMIT_MB, logger=logger,
            ui_active=lambda: False,
        ).start()

    # 9. Надзиратель: упал поток сервера или сервер перестал отвечать — поднимаемся
    #    заново (приём DnD's: трей-надзиратель; перезапуск — через start.vbs).
    watchdog.ThreadWatchdog(
        thread=getattr(SERVER["instance"], "server_thread", None),
        health_url=netutil.url_for("127.0.0.1", port, "/api/health"),
        on_down=hotreload.make_restart_handler(paths.base, vbs_name="start.vbs",
                                                before_exit=lambda: (STOP.set(), shutdown_server()),
                                                logger=logger),
        interval=30.0, failures=2, startup_grace=20.0, logger=logger,
        name=f"{APP_ID}-watchdog",
    ).start()

    # 10. Открываем интерфейс в браузере один раз при старте.
    if OPTIONS["browser"]:
        open_ui()

    try:
        TRAY["instance"].run()           # блокирует главный поток до «Выхода»
    except KeyboardInterrupt:
        logger.info("Остановка с клавиатуры")
    finally:
        quit_app()
        singleton.release_mutex(APP_ID)
        singleton.exit_process(0)


if __name__ == "__main__":
    OPTIONS.update(parse_args(sys.argv[1:]))
    main()
