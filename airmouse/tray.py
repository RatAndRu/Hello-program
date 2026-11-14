"""Иконка в системном трее — чтобы приложение жило в фоне без окна."""

from __future__ import annotations

import logging
log = logging.getLogger("airmouse")


def available() -> bool:
    try:
        import pystray  # noqa: F401  (проверка наличия)
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def _make_icon(paused: bool = False):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (230, 120, 80, 255) if paused else (120, 220, 120, 255)
    d.ellipse((4, 4, 60, 60), fill=(30, 30, 34, 255), outline=color, width=4)
    # стрелка курсора
    d.polygon([(24, 18), (44, 36), (34, 37), (39, 48), (33, 51), (28, 40), (21, 46)],
              fill=color)
    return img


def run(app, blocking: bool = True) -> bool:
    """Запускает трей. Возвращает False, если pystray недоступен."""
    if not available():
        log.warning("pystray/Pillow не установлены — трей недоступен")
        return False
    import pystray

    icon = pystray.Icon("AirMouse", _make_icon(app.router.paused), "AirMouse")

    def refresh() -> None:
        try:
            icon.icon = _make_icon(app.router.paused)
            icon.title = "AirMouse — пауза" if app.router.paused else "AirMouse — работает"
            icon.update_menu()
        except Exception:
            pass

    def toggle_pause(icon_, item=None) -> None:
        app.router.paused = not app.router.paused
        if app.router.paused:
            app.router.release_all()
        refresh()

    def toggle_head(icon_, item=None) -> None:
        app.router.head_pointer = not app.router.head_pointer
        refresh()

    def quit_app(icon_, item=None) -> None:
        app.stop()
        icon_.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem(
            "Пауза", toggle_pause, checked=lambda item: app.router.paused
        ),
        pystray.MenuItem(
            "Мышь головой", toggle_head, checked=lambda item: app.router.head_pointer
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Выход", quit_app),
    )
    if blocking:
        icon.run()
    else:  # pragma: no cover
        icon.run_detached()
    return True
