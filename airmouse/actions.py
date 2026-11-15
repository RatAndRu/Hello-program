"""Действия в операционной системе: мышь, клавиатура, медиа-клавиши.

Есть два бэкенда: настоящий (pyautogui) и «сухой» (DryRun) — он пишет
журнал вместо нажатий, поэтому весь конвейер тестируется без ОС и
без риска случайно что-то нажать.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Tuple

from .config import AppConfig
from .gestures import Event


class Backend(Protocol):  # pragma: no cover - протокол
    def screen_size(self) -> Tuple[int, int]: ...
    def position(self) -> Tuple[int, int]: ...
    def move_to(self, x: int, y: int) -> None: ...
    def move_rel(self, dx: int, dy: int) -> None: ...
    def click(self, button: str = "left", clicks: int = 1) -> None: ...
    def mouse_down(self, button: str = "left") -> None: ...
    def mouse_up(self, button: str = "left") -> None: ...
    def scroll(self, ticks: int) -> None: ...
    def zoom(self, ticks: int) -> None: ...
    def press(self, key: str) -> None: ...
    def hotkey(self, *keys: str) -> None: ...


class DryRunBackend:
    """Ничего не нажимает, только запоминает. Основа тестов и ``--dry-run``."""

    def __init__(self, size: Tuple[int, int] = (1920, 1080)) -> None:
        self.size = size
        self.pos = (size[0] // 2, size[1] // 2)
        self.log: List[str] = []
        self.buttons: Dict[str, bool] = {"left": False, "right": False, "middle": False}

    def screen_size(self) -> Tuple[int, int]:
        return self.size

    def position(self) -> Tuple[int, int]:
        return self.pos

    def move_to(self, x: int, y: int) -> None:
        self.pos = (int(x), int(y))
        self.log.append(f"move_to({x},{y})")

    def move_rel(self, dx: int, dy: int) -> None:
        self.pos = (self.pos[0] + int(dx), self.pos[1] + int(dy))
        self.log.append(f"move_rel({dx},{dy})")

    def click(self, button: str = "left", clicks: int = 1) -> None:
        self.log.append(f"click({button}x{clicks})")

    def mouse_down(self, button: str = "left") -> None:
        self.buttons[button] = True
        self.log.append(f"down({button})")

    def mouse_up(self, button: str = "left") -> None:
        self.buttons[button] = False
        self.log.append(f"up({button})")

    def scroll(self, ticks: int) -> None:
        self.log.append(f"scroll({ticks})")

    def zoom(self, ticks: int) -> None:
        self.log.append(f"zoom({ticks})")

    def press(self, key: str) -> None:
        self.log.append(f"press({key})")

    def hotkey(self, *keys: str) -> None:
        self.log.append("hotkey(" + "+".join(keys) + ")")


class PyAutoGuiBackend:
    """Настоящее управление курсором. pyautogui импортируется лениво."""

    def __init__(self) -> None:
        import pyautogui  # noqa: WPS433 (ленивый импорт — важно для тестов)

        self._pg = pyautogui
        pyautogui.FAILSAFE = True   # курсор в левый верхний угол = аварийный стоп
        pyautogui.PAUSE = 0.0
        self._size = tuple(int(v) for v in pyautogui.size())

    def screen_size(self) -> Tuple[int, int]:
        return self._size  # type: ignore[return-value]

    def position(self) -> Tuple[int, int]:
        p = self._pg.position()
        return int(p[0]), int(p[1])

    def move_to(self, x: int, y: int) -> None:
        self._pg.moveTo(int(x), int(y), _pause=False)

    def move_rel(self, dx: int, dy: int) -> None:
        self._pg.moveRel(int(dx), int(dy), _pause=False)

    def click(self, button: str = "left", clicks: int = 1) -> None:
        self._pg.click(button=button, clicks=int(clicks), interval=0.06)

    def mouse_down(self, button: str = "left") -> None:
        self._pg.mouseDown(button=button)

    def mouse_up(self, button: str = "left") -> None:
        self._pg.mouseUp(button=button)

    def scroll(self, ticks: int) -> None:
        self._pg.scroll(int(ticks))

    def zoom(self, ticks: int) -> None:
        """Масштаб: так же, как Ctrl + колесо мыши (браузер, карты, фото)."""
        try:
            self._pg.keyDown("ctrl")
            self._pg.scroll(int(ticks))
        finally:
            self._pg.keyUp("ctrl")

    def press(self, key: str) -> None:
        self._pg.press(key)

    def hotkey(self, *keys: str) -> None:
        self._pg.hotkey(*keys)


@dataclass
class ActionRouter:
    """События распознавания -> действия. Единственное место с побочными эффектами."""

    backend: Backend
    cfg: AppConfig
    paused: bool = False
    head_pointer: bool = False
    overlay_visible: bool = True
    dragging: bool = False
    log: List[str] = field(default_factory=list)
    scroll_ticks: int = 0

    def __post_init__(self) -> None:
        self.paused = bool(self.cfg.start_paused)
        self.head_pointer = bool(self.cfg.head_pointer)

    # ------------------------------------------------------------------ #
    def handle(self, event: Event, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now

        # Пауза блокирует всё, кроме снятия паузы.
        if event.kind == "pause_set":
            self.paused = bool(event.value)
            if self.paused and self.dragging:
                self.backend.mouse_up("left")
                self.dragging = False
            self.log.append(f"paused={self.paused}")
            return
        if self.paused:
            # На паузе разрешаем только «снять паузу» (и переключить оверлей),
            # иначе приложение нельзя было бы разбудить жестом.
            allowed = self.cfg.actions.mapping.get(event.kind, "")
            if allowed in ("toggle_pause", "toggle_overlay"):
                self._dispatch(allowed, now, source=event.kind)
            return

        kind = event.kind
        if kind == "pointer":
            x, y = event.value  # type: ignore[misc]
            self.backend.move_to(int(x), int(y))
            return
        if kind == "pointer_freeze":
            return
        if kind == "zoom":
            ticks = int(event.value or 0)
            if ticks:
                self.backend.zoom(ticks)
                self.log.append(f"zoom({ticks})")
            return
        if kind == "scroll":
            ticks = int(event.value or 0)
            if ticks:
                self.backend.scroll(ticks)
                self.scroll_ticks += ticks
            return
        if kind == "drag_start":
            pos = self.backend.position()
            self.backend.move_to(*pos)
            self.backend.mouse_down("left")
            self.dragging = True
            self.log.append("drag_start")
            return
        if kind == "drag_end":
            if self.dragging:
                self.backend.mouse_up("left")
                self.dragging = False
                self.log.append("drag_end")
            return
        if kind == "lip_word":
            word = getattr(event.value, "word", "")
            action = self.cfg.lip.words.get(word, "")
            self.log.append(f"lip:{word}->{action or 'нет действия'}")
            if action:
                self._dispatch(action, now, source=f"lip:{word}")
            return

        action = self.cfg.actions.mapping.get(kind)
        if action is None:
            self.log.append(f"unmapped:{kind}")
            return
        self._dispatch(action, now, source=kind)

    # ------------------------------------------------------------------ #
    def _dispatch(self, action: str, now: float, source: str = "") -> None:
        action = (action or "").strip()
        self.log.append(f"{source}->{action}")
        if action in ("", "none"):
            return
        if action == "left_click":
            self.backend.click("left")
        elif action == "right_click":
            self.backend.click("right")
        elif action == "middle_click":
            self.backend.click("middle")
        elif action == "double_click":
            self.backend.click("left", clicks=2)
        elif action == "toggle_pause":
            self.paused = not self.paused
            self.log.append(f"paused={self.paused}")
            if self.paused and self.dragging:
                self.backend.mouse_up("left")
                self.dragging = False
        elif action == "toggle_head_pointer":
            self.head_pointer = not self.head_pointer
            self.log.append(f"head_pointer={self.head_pointer}")
        elif action == "toggle_overlay":
            self.overlay_visible = not self.overlay_visible
            self.log.append(f"overlay={self.overlay_visible}")
        elif action == "scroll_up":
            self.backend.scroll(1)
        elif action == "scroll_down":
            self.backend.scroll(-1)
        elif action.startswith("key:"):
            self.backend.press(action[4:])
        elif action.startswith("hotkey:"):
            keys = [k for k in action[7:].replace(" ", "").split("+") if k]
            if keys:
                self.backend.hotkey(*keys)
        else:
            self.log.append(f"unknown_action:{action}")

    # ------------------------------------------------------------------ #
    def dispatch(self, action: str, now: Optional[float] = None, source: str = "") -> None:
        """Выполнить действие по имени (используется меню трея и тестами)."""
        self._dispatch(action, time.monotonic() if now is None else now, source=source)

    def release_all(self) -> None:
        """Отпустить всё, что могло остаться зажатым (аварийный выход)."""
        try:
            if self.dragging:
                self.backend.mouse_up("left")
                self.dragging = False
        except Exception:  # pragma: no cover - на выходе не падаем
            pass
