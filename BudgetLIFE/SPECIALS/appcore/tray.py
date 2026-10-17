"""
tray.py — трей без сюрпризов.

Собрано лучшее из Cooker, DeployAgent, Трекера, Телепульта, LanguageYOI и SHADOW GAME:
  * иконка рисуется в памяти (Pillow), а не ищется файлом на диске:
    нет `_tray.ico` → нет «трей не появился»;
  * меню описывается данными (`TrayItem`), а не вложенными lambda — приложение
    не зависит от версии pystray и легко тестируется;
  * фолбэк, если pystray нет: приложение продолжает работать, в лог пишется
    понятная причина и точная команда установки (так делает LanguageYOI);
  * «мёртвый» пункт меню лучше убрать (`enabled=False`), а обратную связь дать
    уведомлением (`notify`) — иначе пользователь думает, что клик не сработал;
  * перезапуск/выход — через appcore.singleton (освободить лок, потом выйти).

ВАЖНО ПРО ПОТОКИ: pystray на Windows должен запускаться в ГЛАВНОМ потоке
(`icon.run()` в конце main()). Нельзя создавать второй tkinter.Tk() в чужом
потоке (это ловушка, на которую наткнулся DeployAgent — он держит один общий
Tk-root в отдельном потоке). Если нужно своё окно — используйте один общий root.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import netutil

SEPARATOR = object()


def install_hint(reason: str = "") -> str:
    """Что написать в лог, если трей не работает.

    Важно различать два разных случая (иначе пользователь ставит библиотеку,
    которая уже установлена): пакета нет — «установите», пакет есть, но нет
    графической сессии (сервер, запуск по SSH, служба) — «некуда показывать».
    """
    import importlib.util
    try:
        has_package = importlib.util.find_spec("pystray") is not None
    except Exception:
        has_package = False
    if not has_package:
        return "Установите трей: python -m pip install pystray pillow"
    return ("pystray установлен, но графическая сессия недоступна "
            f"({reason or 'нет дисплея'}) — приложение работает без иконки")


@dataclass
class TrayItem:
    """Пункт меню трея (данные вместо вложенных lambda)."""
    label: str
    action: Callable[..., None] | None = None
    checked: Callable[[], bool] | None = None
    enabled: bool = True
    default: bool = False        # срабатывает по левому клику на иконку
    separator: bool = False
    visible: Callable[[], bool] | None = None

    @classmethod
    def separator_item(cls) -> "TrayItem":
        return cls(label="", separator=True)

    @classmethod
    def title(cls, text: str) -> "TrayItem":
        """Пункт-заголовок (версия/адрес): виден, но не кликается."""
        return cls(label=text, enabled=False)


@dataclass
class TrayConfig:
    app_id: str
    title: str                     # всплывающая подсказка
    tooltip_url: str = ""
    icon_letter: str = "A"
    background: tuple = (0, 120, 212)
    foreground: tuple = (255, 255, 255)
    size: int = 64
    items: list[TrayItem] = field(default_factory=list)


def make_icon(letter: str = "A", *, background=(0, 120, 212), foreground=(255, 255, 255),
              size: int = 64, font_size: int | None = None):
    """Рисует иконку-букву в памяти (Pillow). None, если Pillow нет."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([1, 1, size - 2, size - 2], radius=size // 5, fill=tuple(background))
    text = (letter or "A")[:2]
    font = None
    for candidate in ("segoeui.ttf", "arial.ttf", "calibri.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(candidate, font_size or int(size * 0.58))
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    try:
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((size - (box[2] - box[0])) / 2 - box[0],
                   (size - (box[3] - box[1])) / 2 - box[1]), text, fill=tuple(foreground), font=font)
    except Exception:
        draw.text((size * 0.3, size * 0.25), text, fill=tuple(foreground))
    return img


class TrayApp:
    """Обёртка над pystray с фолбэком.

    Пример:
        tray = TrayApp(TrayConfig(app_id="demo", title="Demo v1.0",
                                  items=[TrayItem("Открыть", open_ui, default=True),
                                         TrayItem("Выход", goodbye)]))
        tray.run()          # блокирует главный поток до выхода
    """

    def __init__(self, config: TrayConfig, *, logger=None, on_quit: Callable[[], None] | None = None):
        self.config = config
        self.logger = logger
        self.on_quit = on_quit
        self._icon = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pystray_error = ""
        self._available = self._import_pystray()

    # ── внутреннее ──────────────────────────────────────────────────────────

    def _import_pystray(self) -> bool:
        try:
            import pystray  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except Exception as exc:
            self._pystray_error = str(exc)
            return False

    def _build_menu(self):
        import pystray

        def _wrap(item: TrayItem):
            def _handler(icon=None, menu_item=None):
                if item.action:
                    try:
                        item.action()
                    except Exception as exc:
                        self.notify(f"Ошибка: {exc}", "Ошибка")
                        if self.logger:
                            self.logger.exception("Ошибка в пункте меню %r", item.label)
            kwargs = {"enabled": item.enabled}
            if item.checked:
                kwargs["checked"] = lambda menu_item: bool(item.checked())
            if item.visible:
                kwargs["visible"] = lambda menu_item: bool(item.visible())
            if item.default:
                kwargs["default"] = True
            return pystray.MenuItem(item.label, _handler, **kwargs)

        entries = []
        for item in self.config.items:
            entries.append(pystray.Menu.SEPARATOR if item.separator else _wrap(item))
        return pystray.Menu(*entries)

    # ── публичное ───────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._available

    def unavailable_reason(self) -> str:
        return self._pystray_error or "pystray/Pillow не установлены"

    def notify(self, message: str, title: str | None = None, *, timeout: int = 5) -> bool:
        """Уведомление рядом с треем (обратная связь для действий без окна)."""
        if self._icon is not None:
            try:
                self._icon.notify(str(message), str(title or self.config.title))
                return True
            except Exception as exc:
                if self.logger:
                    self.logger.info("icon.notify не сработал: %s", exc)
        if self.logger:
            self.logger.info("[Уведомление] %s — %s", title or self.config.title, message)
        return False

    def update_menu(self) -> None:
        """Перерисовать меню (например, после переключения автозапуска)."""
        if self._icon is not None:
            try:
                self._icon.update_menu()
            except Exception:
                pass

    def set_tooltip(self, text: str) -> None:
        self.config.title = text
        if self._icon is not None:
            try:
                self._icon.title = text
            except Exception:
                pass

    def run(self, *, blocking: bool = True) -> None:
        """Запускает трей. По умолчанию блокирует главный поток (правильно для Windows)."""
        if not self._available:
            if self.logger:
                self.logger.warning("Трей недоступен: %s", install_hint(self.unavailable_reason()))
            if blocking:
                # Без трея приложение обязано продолжать работать: ждём вечно.
                try:
                    while not self._stop.wait(1.0):
                        pass
                except KeyboardInterrupt:
                    pass
            return
        import pystray
        image = make_icon(self.config.icon_letter, background=self.config.background,
                          foreground=self.config.foreground, size=self.config.size)
        if image is None:
            image = _fallback_image(self.config.size)
        tooltip = self.config.title
        if self.config.tooltip_url:
            tooltip = f"{tooltip}\n{self.config.tooltip_url}"
        self._icon = pystray.Icon(self.config.app_id, image, tooltip, self._build_menu())
        if blocking:
            try:
                self._icon.run()
            except TypeError:
                # старые версии pystray
                self._icon.run(setup=lambda icon: setattr(icon, "visible", True))
            finally:
                self._shutdown()
        else:
            self._thread = threading.Thread(target=self._icon.run, daemon=True, name="tray")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
        self._shutdown()

    def _shutdown(self) -> None:
        if self.on_quit:
            try:
                self.on_quit()
            except Exception as exc:
                if self.logger:
                    self.logger.error("Ошибка в on_quit: %s", exc)


def _fallback_image(size: int = 64):
    """Иконка без Pillow: pystray умеет принимать путь к .ico, но его нет.

    Поэтому при отсутствии Pillow трей просто не запускаем (см. available=False),
    а здесь возвращаем None — функция оставлена точкой расширения.
    """
    return None


def copy_url_item(label: str, url: str) -> TrayItem:
    """Готовый пункт «Копировать адрес» (приём из Телепульта/BLIND_PC)."""
    return TrayItem(label, lambda: netutil.copy_to_clipboard(url))


def open_url_item(label: str, url: str, *, hints: Iterable[str] = (), default: bool = False) -> TrayItem:
    """Пункт «Открыть»: поднимает окно, если оно уже есть, иначе открывает вкладку."""
    hints = list(hints)
    return TrayItem(label, lambda: __import__("appcore.windowing", fromlist=["x"])
                    .focus_or_open(url, hints), default=default)
