"""
gui.py — единое окно Tkinter, всплывающие подсказки и диалоги.

Взято из DeployAgent (`_GuiManager` + `show_overlay`/`show_report_overlay`).
Этот проект прошёл через редкие, но очень неприятные падения Tkinter, и вывод
получился такой: **Tk нельзя создавать в разных потоках**. Поэтому здесь ровно
один root, он живёт в своём потоке, а все задачи передаются через очередь
(`submit` — не ждать, `call` — дождаться результата).

ЧТО ЭТО ДАЁТ ПРИЛОЖЕНИЮ
-----------------------
  * «всплывашка» в углу экрана поверх всех окон — для отчётов, подсказок и
    распознанного текста (приём DeployAgent, BLIND_PC);
  * модальный вопрос (да/нет, выбор из списка) из фонового потока трея;
  * выбор папки/файла (приём DeployAgent: сканирование проекта);
  * всё это НЕ мешает основному приложению: если Tk нет или нет дисплея
    (сервер, Linux без X), функции просто пишут в лог и возвращают None.

ВАЖНО: если приложению нужен трей, `gui` его не заменяет. Трей — pystray в
главном потоке (appcore.tray), а `gui` — вспомогательные окна в своём потоке.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable

_logger: logging.Logger | None = None
COLORS = {"bg": "#0d1117", "fg": "#58d68d", "warn": "#f0b429", "error": "#ff6b6b",
          "text": "#e6edf3"}


def set_logger(logger: logging.Logger | None) -> None:
    global _logger
    _logger = logger


def _log(level: str, message: str, *args) -> None:
    if _logger:
        getattr(_logger, level, _logger.info)(message, *args)


class GuiManager:
    """Один Tk-root в отдельном потоке: ``submit`` (не ждать), ``call`` (ждать)."""

    def __init__(self, *, withdraw: bool = True) -> None:
        self.root = None
        self._ready = threading.Event()
        self._tasks: queue.Queue[tuple[Callable[..., Any], queue.Queue | None]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._failed = False
        self._withdraw = withdraw
        self._overlay_lock = threading.Lock()

    # ── запуск/остановка ──
    def start(self, timeout: float = 10.0) -> bool:
        if self._thread and self._thread.is_alive():
            return self.root is not None
        self._thread = threading.Thread(target=self._run, name="appcore-gui", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=timeout)
        return self.root is not None

    def _run(self) -> None:
        try:
            import tkinter as tk
            root = tk.Tk()
            if self._withdraw:
                root.withdraw()
            try:
                root.geometry("1x1+-2000+-2000")
                root.attributes("-alpha", 0.0)
            except Exception:
                pass
            self.root = root
        except Exception as exc:
            self._failed = True
            self._ready.set()
            _log("info", "Tkinter недоступен (%s) — окна-подсказки отключены", exc)
            return
        self._ready.set()
        self._pump()

    def _pump(self) -> None:
        """Обрабатывает очередь задач и раз в 100 мс возвращается к Tk-циклу."""
        while True:
            try:
                while True:
                    func, box = self._tasks.get_nowait()
                    try:
                        result = func()
                    except Exception as exc:
                        _log("warning", "Ошибка в GUI-задаче: %s", exc)
                        result = None
                    if box is not None:
                        box.put(result)
            except queue.Empty:
                pass
            if self._failed:
                return
            try:
                self.root.update()
            except Exception:
                return
            time.sleep(0.05)

    def available(self) -> bool:
        return self.root is not None

    def stop(self) -> None:
        try:
            if self.root is not None:
                self.root.quit()
                self.root.destroy()
        except Exception:
            pass
        self.root = None

    # ── выполнение в GUI-потоке ──
    def submit(self, func: Callable[[], Any]) -> bool:
        """Выполнить функцию в GUI-потоке, не дожидаясь результата."""
        if not self.available():
            return False
        self._tasks.put((func, None))
        return True

    def call(self, func: Callable[[], Any], timeout: float = 30.0) -> Any:
        """Выполнить функцию в GUI-потоке и дождаться результата (для диалогов)."""
        if not self.available():
            return None
        box: queue.Queue = queue.Queue(maxsize=1)
        self._tasks.put((func, box))
        try:
            return box.get(timeout=timeout)
        except queue.Empty:
            _log("warning", "GUI-задача не ответила за %s с", timeout)
            return None


# ── общий менеджер и «ленивый» запуск ───────────────────────────────────────

_GUI: GuiManager | None = None
_GUI_LOCK = threading.Lock()


def manager() -> GuiManager:
    """Общий GuiManager (создаётся и запускается при первом обращении)."""
    global _GUI
    with _GUI_LOCK:
        if _GUI is None:
            _GUI = GuiManager()
            _GUI.start()
        elif not _GUI.available() and not _GUI._failed:
            _GUI.start()
        return _GUI


def available() -> bool:
    return manager().available()


# ── всплывающие подсказки ───────────────────────────────────────────────────

def overlay(text: str, duration: float = 2.5, *, top: int = 40, width: int = 480,
            color: str | None = None, font_size: int = 14) -> bool:
    """Показывает текст поверх всех окон (не блокирует вызывающий поток).

    Приём DeployAgent: под pythonw нет консоли, поэтому «что произошло» надо
    показать именно так — окно без рамки, полупрозрачное, само исчезает.
    """
    text = str(text or "").strip()
    if not text:
        return False
    gui = manager()
    if not gui.available():
        _log("info", "Подсказка (окна недоступны): %s", text)
        return False
    if not gui._overlay_lock.acquire(blocking=False):
        return False                     # уже показана другая — не наслаиваем

    built = threading.Event()

    def build() -> None:
        try:
            import tkinter as tk
            window = tk.Toplevel(gui.root)
            window.overrideredirect(True)
            window.attributes("-topmost", True)
            window.attributes("-alpha", 0.93)
            window.configure(bg=COLORS["bg"])
            screen_width = window.winfo_screenwidth()
            height = 56 if len(text) <= 60 else 92
            window.geometry(f"{width}x{height}+{(screen_width - width) // 2}+{top}")
            tk.Label(window, text=text, font=("Segoe UI", font_size, "bold"),
                     fg=color or COLORS["fg"], bg=COLORS["bg"],
                     wraplength=width - 20, justify="center").pack(expand=True, padx=8)
            window.after(int(max(0.5, duration) * 1000), window.destroy)
            built.set()
        except Exception as exc:
            _log("warning", "Не удалось показать подсказку: %s", exc)
            gui._overlay_lock.release()

    if not gui.submit(build):
        gui._overlay_lock.release()
        return False
    # Лок держим, пока окно видно: на экране не должно быть двух подсказок сразу.
    threading.Timer(max(0.8, duration + 0.5), gui._overlay_lock.release).start()
    return True


def report(lines: list[str] | str, *, title: str = "", duration: float = 4.0,
           ok_mark: str = "✓", fail_mark: str = "✕") -> bool:
    """Показывает многострочный отчёт (успех/ошибка построчно) — приём DeployAgent.

    ``report(["✓ app.py — записан", "✕ config.json — не найден"])``.
    """
    if isinstance(lines, str):
        lines = [lines]
    body = "\n".join(str(line) for line in lines[:12])
    if len(lines) > 12:
        body += f"\n… ещё {len(lines) - 12}"
    header = f"{title}\n" if title else ""
    has_fail = any(str(line).startswith(fail_mark) for line in lines)
    color = COLORS["error"] if has_fail else COLORS["fg"]
    return overlay(header + body, duration, width=560, color=color, font_size=12)


def notify(text: str, title: str = "") -> bool:
    """Уведомление: сначала трей, иначе всплывающая подсказка, иначе лог."""
    try:
        from . import tray
        instance = getattr(tray, "current", lambda: None)()
        if instance is not None and getattr(instance, "available", False):
            instance.notify(text, title or "")
            return True
    except Exception:
        pass
    return overlay(f"{title}: {text}" if title else text)


# ── диалоги ─────────────────────────────────────────────────────────────────

def ask_yes_no(question: str, *, title: str = "", timeout: float = 60.0) -> bool | None:
    """Модальный вопрос «Да/Нет». None — если окна недоступны или время вышло."""
    gui = manager()
    if not gui.available():
        _log("info", "Вопрос (окна недоступны): %s", question)
        return None

    def build():
        import tkinter as tk
        from tkinter import messagebox
        return bool(messagebox.askyesno(title or "Вопрос", question))
    return gui.call(build, timeout=timeout)


def ask_choice(question: str, options: list[str], *, title: str = "",
               timeout: float = 120.0) -> int | None:
    """Выбор из списка: возвращает индекс варианта или None."""
    gui = manager()
    if not gui.available():
        _log("info", "Выбор (окна недоступны): %s → %s", question, options)
        return None

    def build():
        import tkinter as tk
        from tkinter import simpledialog
        chosen = simpledialog.askstring(title or "Выбор", question,
                                        initialvalue=options[0] if options else "")
        if chosen is None:
            return None
        try:
            return options.index(chosen)
        except ValueError:
            return None
    return gui.call(build, timeout=timeout)


def ask_folder(title: str = "Выберите папку", *, initial: str = "",
               timeout: float = 300.0) -> str | None:
    """Диалог выбора папки (приём DeployAgent: сканирование проекта)."""
    gui = manager()
    if not gui.available():
        _log("info", "Выбор папки (окна недоступны): %s", title)
        return None

    def build():
        import tkinter as tk
        from tkinter import filedialog
        window = tk.Toplevel(gui.root)
        window.withdraw()
        window.attributes("-topmost", True)
        try:
            path = filedialog.askdirectory(title=title, initialdir=initial or None,
                                           parent=window)
        finally:
            window.destroy()
        return path or None
    return gui.call(build, timeout=timeout)


def ask_text(question: str, *, title: str = "", initial: str = "",
             timeout: float = 300.0) -> str | None:
    """Ввод строки (например, имя новой записи)."""
    gui = manager()
    if not gui.available():
        return None

    def build():
        from tkinter import simpledialog
        return simpledialog.askstring(title or "Ввод", question, initialvalue=initial)
    return gui.call(build, timeout=timeout)
