"""
events.py — живые обновления в браузере без WebSocket (Server-Sent Events).

Идея и разбор граблей — из bridge (`broadcast`, `SSE_CLIENTS`, «pc_toast») и
swipe_review (`bump_and_broadcast`, счётчик активных клиентов). Оба проекта
показывают одно и то же: для локального приложения SSE проще и надёжнее
WebSocket — это обычный HTTP-ответ, он не требует отдельной библиотеки, работает
через любой прокси и переживает перезапуск страницы.

ЧТО ЗАКРЫВАЕТ ЭТОТ МОДУЛЬ
------------------------
  * «телефон и ПК видят одно и то же» — данные меняются на ПК, страница на
    телефоне обновляется сама (общий буфер, свайпы, счёт очков, прогресс);
  * уведомления-тосты на всех открытых устройствах;
  * счётчик «кто ещё подключён» (bridge: «2 устройства»);
  * корректное завершение: очередь не растёт бесконечно, «мёртвые» клиенты
    отваливаются по таймауту, а браузер получает heartbeat, чтобы не решать,
    что связь потеряна.

ПРИМЕР
------
    bus = appcore.events.EventBus(logger=logger)
    appcore.events.install(app, bus)         # добавит GET /api/events (SSE)
    bus.publish("clip", text="привет")       # увидят все открытые страницы

В браузере:
    const source = new EventSource("/api/events");
    source.onmessage = (e) => { const msg = JSON.parse(e.data); ... };
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any, Callable, Iterable

_logger: logging.Logger | None = None


def set_logger(logger: logging.Logger | None) -> None:
    global _logger
    _logger = logger


def _log(level: str, message: str, *args) -> None:
    if _logger:
        getattr(_logger, level, _logger.info)(message, *args)


class EventBus:
    """Простая шина событий: подписчики-очереди + рассылка всем живым."""

    def __init__(self, *, keep_alive: float = 15.0, max_queue: int = 200,
                 logger: logging.Logger | None = None) -> None:
        self.keep_alive = float(keep_alive)
        self.max_queue = int(max_queue)
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._last_seen: dict[int, float] = {}
        self.started_at = time.time()
        if logger:
            set_logger(logger)

    # ── подписка ──
    def subscribe(self) -> queue.Queue:
        """Новая подписка (одна открытая страница = одна очередь)."""
        box: queue.Queue = queue.Queue(maxsize=self.max_queue)
        with self._lock:
            self._subscribers.append(box)
            self._last_seen[id(box)] = time.time()
        _log("debug", "SSE: подключился клиент (всего %s)", self.client_count())
        return box

    def unsubscribe(self, box: queue.Queue) -> None:
        with self._lock:
            if box in self._subscribers:
                self._subscribers.remove(box)
            self._last_seen.pop(id(box), None)
        _log("debug", "SSE: клиент отключился (осталось %s)", self.client_count())

    def touch(self, box: queue.Queue) -> None:
        """Отметить активность подписчика (вызывается при отправке heartbeat)."""
        with self._lock:
            self._last_seen[id(box)] = time.time()

    def client_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # ── отправка ──
    def publish(self, event: str, **payload: Any) -> int:
        """Отправляет событие всем подписчикам. Возвращает число доставленных.

        Если у подписчика переполнена очередь (страница замерла), событие для него
        пропускается: лучше потерять одно уведомление, чем подвесить всё приложение.
        """
        message = json.dumps({"type": event, **payload}, ensure_ascii=False)
        delivered = 0
        with self._lock:
            boxes = list(self._subscribers)
        for box in boxes:
            try:
                box.put_nowait(message)
                delivered += 1
            except queue.Full:
                _log("warning", "SSE: очередь клиента переполнена, событие %s пропущено", event)
        return delivered

    broadcast = publish          # привычное имя из bridge

    def stream(self, box: queue.Queue | None = None,
               *, ready: Callable[[], Iterable[dict]] | None = None) -> Iterable[str]:
        """Генератор для Flask: отдаёт события в формате SSE.

        ``ready`` — необязательная функция, которая возвращает начальные события
        при подключении (например, снимок текущего состояния), чтобы новая
        страница сразу была в курсе дела.
        """
        box = box or self.subscribe()
        try:
            if ready is not None:
                try:
                    for payload in ready() or ():
                        yield self._format(payload)
                except Exception as exc:
                    _log("warning", "SSE: стартовые события не собраны: %s", exc)
            last_heartbeat = time.time()
            while True:
                try:
                    message = box.get(timeout=1.0)
                except queue.Empty:
                    if time.time() - last_heartbeat >= self.keep_alive:
                        last_heartbeat = time.time()
                        self.touch(box)
                        yield ": keep-alive\n\n"          # комментарий SSE = «я жив»
                    continue
                yield f"data: {message}\n\n"
                last_heartbeat = time.time()
        except GeneratorExit:                            # браузер закрыл соединение
            _log("debug", "SSE: соединение закрыто клиентом")
            raise
        finally:
            self.unsubscribe(box)

    @staticmethod
    def _format(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    # ── удобные события ──
    def toast(self, text: str, *, level: str = "info") -> int:
        """Всплывающая подсказка на всех открытых страницах (приём bridge)."""
        return self.publish("toast", text=str(text), level=level)

    def clients(self) -> int:
        """Сообщить всем, сколько клиентов подключено (счётчик в углу страницы)."""
        return self.publish("clients", clients=self.client_count())


def install(app, bus: EventBus | None = None, *, path: str = "/api/events",
            ready: Callable[[], Iterable[dict]] | None = None,
            logger: logging.Logger | None = None) -> EventBus:
    """Добавляет Flask-маршрут ``GET /api/events`` (SSE) и возвращает шину.

    Заголовки важны: ``text/event-stream`` + ``no-store`` + отключение буферизации;
    иначе браузер (или intermediate-прокси) будет ждать закрытия ответа.
    """
    from flask import Response, jsonify, request     # импорт внутри — Flask нужен не всегда

    if logger:
        set_logger(logger)
    bus = bus or EventBus(logger=logger)

    @app.route(path, methods=["GET"])
    def _appcore_events():                            # noqa: ANN202
        box = bus.subscribe()
        if "text/event-stream" not in (request.headers.get("Accept") or ""):
            # request() как обычный API: «сколько сейчас клиентов» (удобно для отладки)
            bus.unsubscribe(box)
            return jsonify({"ok": True, "clients": bus.client_count(),
                            "subscribe": request.url_root.rstrip("/") + path})
        response = Response(bus.stream(box, ready=ready), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
        return response

    return bus
