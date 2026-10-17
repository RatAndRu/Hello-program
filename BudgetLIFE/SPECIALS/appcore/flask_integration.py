"""
flask_integration.py — общие Flask-маршруты, которые должны быть у КАЖДОГО проекта.

Один вызов `install(app, cfg)` добавляет:
  * GET  /api/identity — «кто на порту»: по нему второй запуск понимает, что
    приложение уже работает (appcore.ports.check_identity), а трей — версию и pid;
  * GET  /api/health   — быстрая проверка живости (для лаунчера/трея);
  * GET  /manifest.json — динамический manifest: на телефон — share_target GET,
    на ПК — POST с файлами (приём bridge);
  * GET  /sw.js        — service worker с правильными заголовками
    (Service-Worker-Allowed: /, Cache-Control: no-store) — иначе PWA «залипает»;
  * GET  /offline.html — страница «нет связи с ПК»;
  * GET/POST /api/share — приём того, чем поделились (текст/ссылки/файлы);
  * GET  /api/qr       — PNG (или SVG) с QR-кодом на локальный адрес для телефона;
                          пакет qrcode не обязателен: есть встроенный appcore.qr;
  * обработчик 500     — трассировка в лог, а не «белый экран»;
  * after_request      — HTML отдаётся с no-store (правки видны сразу, PWA не
    показывает вчерашнюю версию интерфейса).

Всё опционально: если Flask-приложение не хочет какой-то маршрут — параметр
`enable_*` в PWAConfig.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import netutil, ports, pwa


@dataclass
class PWAConfig:
    app_id: str
    app_name: str
    version: str
    static_dir: str | Path
    data_dir: str | Path | None = None
    share_dir: str | Path | None = None          # куда складывать принятое «Поделиться»
    theme_color: str = "#0f1628"
    background_color: str = "#0f1626"
    port_getter: Callable[[], int] | None = None  # актуальный порт (мог смениться)
    on_share: Callable[[dict], dict | None] | None = None
    share_files: bool = False                    # показывать приём файлов в manifest
    enable_identity: bool = True
    enable_health: bool = True
    enable_manifest: bool = True
    enable_sw: bool = True
    enable_offline: bool = True
    enable_share: bool = True
    enable_qr: bool = True
    no_store_html: bool = True
    icon_letter: str = "A"
    extra_identity: dict = field(default_factory=dict)
    logger: "logging.Logger | None" = None      # без аннотации dataclass не примет аргумент


def install(app, cfg: PWAConfig):
    """Подключает стандартные маршруты к Flask-приложению. Возвращает cfg."""
    from flask import Response, jsonify, request, send_from_directory

    started = time.time()
    static_dir = Path(cfg.static_dir)

    # ── identity/health ─────────────────────────────────────────────────────
    def _port() -> int:
        try:
            if cfg.port_getter:
                return int(cfg.port_getter() or 0)
            return int(request.host.split(":")[-1]) if ":" in request.host else 80
        except Exception:
            return 0

    if cfg.enable_identity:
        @app.route(ports.API_IDENTITY, methods=["GET"])
        def _appcore_identity():  # noqa: ANN202
            payload = ports.identity_payload(cfg.app_id, cfg.app_name, cfg.version,
                                             _port(), extra=dict(cfg.extra_identity))
            payload["uptime_sec"] = int(time.time() - started)
            return jsonify(payload)

    if cfg.enable_health:
        @app.route("/api/health", methods=["GET"])
        def _appcore_health():  # noqa: ANN202
            return jsonify({"ok": True, "app_id": cfg.app_id, "version": cfg.version,
                            "pid": __import__("os").getpid(), "uptime_sec": int(time.time() - started)})

    # ── manifest / sw / offline ─────────────────────────────────────────────
    if cfg.enable_manifest:
        @app.route("/" + pwa.MANIFEST_FILENAME, methods=["GET"])
        def _appcore_manifest():  # noqa: ANN202
            user_agent = (request.headers.get("User-Agent") or "").lower()
            is_mobile = any(token in user_agent for token in ("android", "iphone", "ipad"))
            icons = {}
            for name, size in (("icon-192.png", "192"), ("icon-512.png", "512"),
                               ("icon-192-maskable.png", "192"), ("icon-512-maskable.png", "512")):
                if (static_dir / name).exists():
                    icons[f"/static/{name}"] = size
            manifest = pwa.build_manifest(
                name=cfg.app_name, short_name=cfg.app_name, app_id=cfg.app_id,
                theme_color=cfg.theme_color, background_color=cfg.background_color,
                icons=icons or None, prefer_share_target=cfg.enable_share,
                share_files=cfg.share_files and not is_mobile,
            )
            if is_mobile:
                # Телефон умеет отдать только текст/ссылку — файлы не обещаем.
                manifest["share_target"] = pwa.share_target_mobile("/api/share")
            response = Response(json.dumps(manifest, ensure_ascii=False, indent=2),
                                mimetype="application/manifest+json")
            response.headers["Cache-Control"] = "no-cache"
            return response

    if cfg.enable_sw:
        @app.route("/" + pwa.SW_FILENAME, methods=["GET"])
        def _appcore_sw():  # noqa: ANN202
            body = pwa.service_worker_js(
                cache_name=cfg.app_id, version=cfg.version,
                precache=["/", "/offline.html", "/static/icon.svg"],
                offline_url="/offline.html", share_action="/api/share")
            response = Response(body, mimetype="application/javascript")
            # Service-Worker-Allowed нужен, если sw.js отдаётся не из корня.
            response.headers["Service-Worker-Allowed"] = "/"
            response.headers["Cache-Control"] = "no-store"
            return response

    if cfg.enable_offline:
        @app.route("/offline.html", methods=["GET"])
        def _appcore_offline():  # noqa: ANN202
            return Response(pwa.OFFLINE_HTML, mimetype="text/html")

    # ── «Поделиться» ────────────────────────────────────────────────────────
    if cfg.enable_share:
        @app.route("/api/share", methods=["GET", "POST"])
        def _appcore_share():  # noqa: ANN202
            payload = _collect_share(request, cfg)
            # По умолчанию складываем принятое в data/shared/ (текст .txt, файлы как есть).
            handler = cfg.on_share or (lambda data: save_share(data, share_dir=cfg.share_dir))
            result = None
            try:
                result = handler(payload)
            except Exception as exc:
                if cfg.logger:
                    cfg.logger.exception("Ошибка обработки «Поделиться»: %s", exc)
            # Если открыт браузер (GET) — показываем человеческую страницу,
            # если это fetch из SW — отдаём JSON.
            if request.method == "GET" and "application/json" not in (request.headers.get("Accept") or ""):
                return Response(_share_page(cfg, payload, result), mimetype="text/html")
            return jsonify({"ok": True, "received": _share_summary(payload), "result": result})

    # ── QR ──────────────────────────────────────────────────────────────────
    if cfg.enable_qr:
        @app.route("/api/qr", methods=["GET"])
        def _appcore_qr():  # noqa: ANN202
            import os
            target = (request.args.get("url") or request.args.get("target")
                      or netutil.lan_url(_port() or 80, "/"))
            data = netutil.qr_png_bytes(target)
            if data is not None:
                response = Response(data, mimetype="image/png")
            else:
                # PNG не получился — отдаём SVG тем же маршрутом (браузер покажет
                # так же, а сканер прочитает не хуже). Причина, по которой это
                # вообще возможно: текст длиннее, чем влезает в QR 40-й версии.
                svg = netutil.qr_svg_text(target)
                if svg is None:
                    return jsonify({"ok": False, "error": "Текст слишком длинный для QR-кода",
                                    "url": target}), 501
                response = Response(svg, mimetype="image/svg+xml")
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-QR-Target"] = target
            _ = os  # noqa: F841
            return response

    # ── страховка от «белого экрана» и залипшего кэша ───────────────────────
    @app.errorhandler(500)
    def _appcore_error_500(exc):  # noqa: ANN202
        if cfg.logger:
            cfg.logger.exception("Необработанная ошибка в обработчике: %s", exc)
        return Response("<h1>500</h1><p>Ошибка записана в лог.</p>", status=500,
                        mimetype="text/html")

    if cfg.no_store_html:
        @app.after_request
        def _appcore_no_store(response):  # noqa: ANN202
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type and "no-store" not in (response.headers.get("Cache-Control") or ""):
                # Правки интерфейса должны быть видны сразу, а PWA не должен
                # показывать вчерашнюю страницу.
                response.headers["Cache-Control"] = "no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
            return response

    return cfg


# ── «Поделиться»: сбор и сохранение ─────────────────────────────────────────

def _collect_share(request, cfg: PWAConfig) -> dict:
    """Приводит GET- и POST-варианты «Поделиться» к одному виду."""
    payload: dict = {"title": (request.args.get("title") or "").strip(),
                     "text": (request.args.get("text") or "").strip(),
                     "url": (request.args.get("url") or "").strip(),
                     "files": [], "source": "share"}
    if request.method == "POST":
        form = request.form
        payload["title"] = (form.get("title") or payload["title"]).strip()
        payload["text"] = (form.get("text") or payload["text"]).strip()
        payload["url"] = (form.get("url") or payload["url"]).strip()
        for storage in request.files.getlist("files"):
            name = Path(storage.filename or "shared.bin").name
            data = storage.read()
            payload["files"].append({"name": name, "size": len(data), "data": data})
        if not payload["files"] and (payload["text"] or payload["url"]):
            payload["source"] = "share-text"
    if not payload["title"] and not payload["text"] and not payload["url"] and not payload["files"]:
        # Ничего не передали — считаем это открытием страницы «Поделиться».
        payload["source"] = "share-open"
    return payload


def _share_summary(payload: dict) -> dict:
    return {"title": payload.get("title", ""), "text": payload.get("text", "")[:200],
            "url": payload.get("url", ""),
            "files": [{"name": f["name"], "size": f["size"]} for f in payload.get("files", [])],
            "source": payload.get("source", "")}


def save_share(payload: dict, *, share_dir: str | Path | None = None) -> dict:
    """Сохраняет принятое в data/shared/ и возвращает сводку.

    Текст — в .txt с датой в имени, файлы — как есть (имя очищается от пути:
    защита от «../../windows/system32» из чужого имени файла).
    """
    import time as _time
    stamp = _time.strftime("%Y%m%d-%H%M%S")
    base = Path(share_dir) if share_dir else None
    saved: list[str] = []
    if base is None:
        return {"saved": [], "note": "share_dir не задан — данные не сохранены"}
    base.mkdir(parents=True, exist_ok=True)
    text = "\n".join(part for part in (payload.get("title", ""), payload.get("text", ""),
                                       payload.get("url", "")) if part)
    if text.strip():
        target = base / f"share-{stamp}.txt"
        try:
            target.write_text(text, encoding="utf-8")
            saved.append(target.name)
        except OSError:
            pass
    for item in payload.get("files", []):
        safe = Path(item["name"]).name or "shared.bin"
        target = base / f"{stamp}-{safe}"
        try:
            target.write_bytes(item["data"])
            saved.append(target.name)
        except OSError:
            pass
    return {"saved": saved, "folder": str(base)}


def _share_page(cfg: PWAConfig, payload: dict, result: dict | None) -> str:
    summary = _share_summary(payload)
    rows = []
    if summary["title"]:
        rows.append(f"<p><b>Заголовок:</b> {_escape(summary['title'])}</p>")
    if summary["text"]:
        rows.append(f"<p><b>Текст:</b> {_escape(summary['text'])}</p>")
    if summary["url"]:
        rows.append(f"<p><b>Ссылка:</b> <a href='{_escape(summary['url'])}'>{_escape(summary['url'])}</a></p>")
    for item in summary["files"]:
        rows.append(f"<p>📎 {_escape(item['name'])} — {item['size']} байт</p>")
    saved = (result or {}).get("saved") or []
    saved_block = ("<p style='color:#7ee2a8'>Сохранено: " + _escape(", ".join(saved)) + "</p>"
                   if saved else "<p style='color:#ffb4b4'>Данные не сохранены (нет share_dir).</p>")
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_escape(cfg.app_name)} — получено</title>
<style>body{{margin:0;min-height:100dvh;display:grid;place-items:center;background:{cfg.background_color};
color:#eaeefb;font:16px/1.55 system-ui,Segoe UI,sans-serif;padding:24px}}
.card{{max-width:520px;background:#131c33;border:1px solid #223055;border-radius:16px;padding:26px}}
h1{{font-size:19px;margin:0 0 12px}} p{{margin:0 0 10px;color:#cbd7f0}} a{{color:#7fb1ff}}</style></head>
<body><div class="card"><h1>Получено через «Поделиться»</h1>{''.join(rows) or '<p>Пустая передача.</p>'}
{saved_block}<p style="color:#8fa2c8">Окно можно закрыть.</p></div></body></html>"""


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


# ── вспомогательные штуки для «полного» проекта ─────────────────────────────

def install_static_icons(app, static_dir: str | Path, letter: str = "A", *, logger=None):
    """Создаёт иконки и раздаёт их по /static/... (Flask это умеет сам)."""
    static_dir = Path(static_dir)
    pwa.ensure_icons(static_dir, letter, logger=logger)
    return static_dir


def tray_ready_url(port: int, host: str = "127.0.0.1") -> str:
    return netutil.url_for(host, port, "/")


# ── запуск сервера с гарантией, что порт действительно наш ──────────────────

def serve_with_fallback(flask_app, *, app_id: str, host: str, candidate_ports,
                        preferred: int | None = None, threaded: bool = True,
                        logger=None):
    """Поднимает WSGI-сервер на первом реально свободном порту своего блока.

    Возвращает (server, port) или (None, None). У сервера есть атрибут
    ``server_thread`` — поток, в котором он работает (для надзирателя).

    Почему не `flask_app.run(thread=True, port=...)`:
      * `app.run()` при занятом порте падает в потоке — наружу это видно только
        по отсутствию сервера, а приложение «молча не работает» (типовая беда);
      * здесь порт занимает `make_server` СИНХРОННО, поэтому ошибку видно сразу
        и можно спокойно попробовать следующий порт своего блока;
      * `server.shutdown()` даёт корректный останов без «зомби» в диспетчере задач.
    """
    try:
        from werkzeug.serving import make_server
    except Exception as exc:                     # pragma: no cover
        if logger:
            logger.error("Нет werkzeug (входит в Flask): %s", exc)
        return None, None
    import threading as _threading

    ordered = list(dict.fromkeys([int(p) for p in candidate_ports]))
    if preferred and int(preferred) in ordered:
        ordered.remove(int(preferred))
        ordered.insert(0, int(preferred))

    for port in ordered:
        try:
            server = make_server(host, port, flask_app, threaded=threaded)
        except OSError as exc:
            if logger:
                logger.warning("Порт %s занят (%s) — пробую следующий из своего блока", port, exc)
            continue
        thread = _threading.Thread(target=server.serve_forever, daemon=True,
                                   name=f"{app_id}-server")
        thread.start()
        # Поток сервера вешаем на сам объект: его проверяет надзиратель
        # (watchdog.ThreadWatchdog) — «сервер жив?» без опроса порта.
        server.server_thread = thread
        if logger:
            bind_note = " (все интерфейсы)" if host in ("0.0.0.0", "::") else ""
            logger.info("Сервер слушает %s:%s%s", host, port, bind_note)
        return server, port

    if logger:
        logger.error("Ни один порт из блока %s не свободен: %s", app_id, ordered)
    return None, None
