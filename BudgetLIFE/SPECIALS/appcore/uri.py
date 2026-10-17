"""URI-команды: ``myapp://timer/start?name=Зарядка`` — фишка Трекера и BLIND_PC.

В Трекере 18 URI-команд (`tracker://timer/start`, `tracker://task/done?id=3` и
т.п.), в BLIND_PC — свой протокол `blindpc`. Приложение регистрирует схему в
реестре (`autostart.register_uri_protocol`), и тогда его можно запускать из
Win+R, ярлыка, браузера или другого приложения.

Тонкость, из-за которой этот модуль вообще нужен: при повторном вызове Windows
**запускает второй процесс** приложения. Второй процесс должен понять, что
экземпляр уже работает, передать ему команду и выйти. Здесь есть всё для этого:

  * ``parse(uri)`` — разбор адреса в (команда, параметры);
  * ``Router`` — таблица «команда → обработчик», ``register``/``dispatch``;
  * ``argv_uri(argv)`` — находит URI среди аргументов (``start.vbs "%1"``);
  * ``send_to_running(uri, port)`` — POST на ``/api/uri`` работающего экземпляра;
  * ``forward_or_run(uri, port, fallback)`` — «передать, иначе выполнить у себя».

Обработчики получают параметры как именованные аргументы
(``handler(**params)``) и возвращают словарь/строку/None — что переживёт
``jsonify``.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable

__all__ = ["parse", "Router", "argv_uri", "send_to_running", "forward_or_run",
           "make_flask_view", "normalize_scheme"]


def normalize_scheme(name: str, *, fallback: str = "myapp") -> str:
    """Превращает имя приложения в допустимую схему URI.

    По RFC 3986 в схеме разрешены только латинские буквы, цифры, «+», «-» и «.»,
    причём начинаться она должна с буквы. Поэтому ``specials_demo`` → ``specials-demo``,
    а ``моё приложение`` → ``moe-prilozhenie`` (кириллица транслитерируется).
    """
    table = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya",
    })
    text = str(name or "").strip().lower().translate(table)
    out = []
    for char in text:
        out.append(char if (char.isalnum() and char.isascii()) or char in "+-." else "-")
    scheme = "".join(out).strip("-.")
    while "--" in scheme:
        scheme = scheme.replace("--", "-")
    if not scheme or not scheme[0].isalpha():
        scheme = f"{fallback}-{scheme}" if scheme else fallback
    return scheme[:40]


def parse(uri: str) -> tuple[str, dict[str, str]]:
    """``myapp://timer/start?name=x`` → ``("timer/start", {"name": "x"})``.

    Понимает и короткую форму ``myapp:timer/start``, и «путь-команду» с
    косой чертой: команда — всё, что идёт после ``://`` до ``?``.
    """
    uri = (uri or "").strip().strip('"')
    if "://" in uri:
        scheme, rest = uri.split("://", 1)
    elif ":" in uri:
        scheme, rest = uri.split(":", 1)
    else:
        raise ValueError("Это не URI-адрес приложения")
    if not scheme or not scheme.replace("-", "").replace("+", "").isalnum():
        raise ValueError(f"Непонятная схема: {scheme!r}")
    rest = rest.lstrip("/")
    path, _, query = rest.partition("?")
    command = path.strip("/").lower()
    params: dict[str, str] = {}
    for key, values in urllib.parse.parse_qs(query, keep_blank_values=True).items():
        params[key.strip().lower()] = values[0] if values else ""
    return command, params


class Router:
    """Таблица «команда → обработчик» с понятными ошибками.

    Пример:
        router = Router()
        @router.command("notes/add")
        def add(text: str = ""): ...
        router.dispatch("myapp://notes/add?text=привет")
    """

    def __init__(self, *, name: str = "app") -> None:
        self.name = name
        self._handlers: dict[str, Callable[..., object]] = {}
        self._lock = threading.RLock()

    # ── регистрация ─────────────────────────────────────────────────────────
    def command(self, name: str, handler: Callable[..., object] | None = None):
        """Декоратор (``@router.command("x")``) или прямая регистрация."""
        key = name.strip("/").lower()
        if handler is None:
            def decorator(func: Callable[..., object]) -> Callable[..., object]:
                with self._lock:
                    self._handlers[key] = func
                return func
            return decorator
        with self._lock:
            self._handlers[key] = handler
        return handler

    def add(self, name: str, handler: Callable[..., object]) -> None:
        self.command(name, handler)

    def remove(self, name: str) -> bool:
        with self._lock:
            return self._handlers.pop(name.strip("/").lower(), None) is not None

    def commands(self) -> list[str]:
        with self._lock:
            return sorted(self._handlers)

    def help_text(self) -> str:
        """Список команд для лога, интерфейса или голосового ответа."""
        lines = [f"{self.name}://{name}" for name in self.commands()]
        return "\n".join(lines) if lines else f"{self.name}: команд нет"

    # ── выполнение ──────────────────────────────────────────────────────────
    def dispatch(self, uri: str) -> dict:
        """Выполняет команду из URI. Ошибка — это тоже ответ, а не исключение."""
        try:
            command, params = parse(uri)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "command": ""}
        with self._lock:
            handler = self._handlers.get(command)
        if handler is None:
            return {"ok": False, "command": command,
                    "error": f"Неизвестная команда: {command}",
                    "commands": self.commands()}
        try:
            result = handler(**params)
        except TypeError as exc:                # не тот набор параметров
            return {"ok": False, "command": command,
                    "error": f"Команда не приняла параметры: {exc}"}
        except Exception as exc:                # noqa: BLE001 — чужая ошибка не должна ронять сервер
            return {"ok": False, "command": command, "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(result, dict):
            return {"ok": True, "command": command, **result}
        return {"ok": True, "command": command, "result": result}


def argv_uri(argv: list[str] | None = None, *, scheme: str = "") -> str | None:
    """Первый аргумент, похожий на URI (регистр схемы не важен)."""
    import sys

    for raw in (argv if argv is not None else sys.argv[1:]):
        text = str(raw).strip().strip('"')
        if "://" not in text and ":" not in text:
            continue
        head = text.split(":", 1)[0].lower()
        if not head or not head.replace("-", "").replace("+", "").isalnum():
            continue
        if scheme and head != scheme.lower():
            continue
        return text
    return None


def send_to_running(uri: str, port: int, *, host: str = "127.0.0.1", timeout: float = 2.0,
                    path: str = "/api/uri") -> dict | None:
    """Передаёт URI уже запущенному экземпляру. None — если он не ответил."""
    url = f"http://{host}:{int(port)}{path}"
    body = json.dumps({"uri": uri}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def forward_or_run(uri: str, *, port: int, router: Router, host: str = "127.0.0.1",
                   logger=None) -> dict:
    """Сначала пробуем передать команду работающему экземпляру.

    Если никто не ответил — выполняем у себя (первый запуск приложения).
    """
    answer = send_to_running(uri, port, host=host)
    if answer is not None:
        if logger:
            logger.info("URI передан работающему экземпляру: %s → %s", uri, answer.get("ok"))
        return {**answer, "forwarded": True}
    if logger:
        logger.info("URI выполняет этот процесс: %s", uri)
    return {**router.dispatch(uri), "forwarded": False}


def make_flask_view(router: Router) -> Callable[[], object]:
    """Готовый обработчик для Flask: POST ``{"uri": "..."}`` → результат.

    Подключается одной строкой (см. эталонный ``template/app.py``)::

        flask_app.add_url_rule("/api/uri", "uri", uri.make_flask_view(router), methods=["POST"])
    """
    def view():
        from flask import jsonify, request
        payload = request.get_json(silent=True) or {}
        raw = payload.get("uri") or request.args.get("uri") or ""
        if not raw:
            return jsonify({"ok": False, "error": "Не передан uri", "commands": router.commands()})
        return jsonify(router.dispatch(raw))

    return view
