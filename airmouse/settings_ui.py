"""Окно настроек с ползунками — калибровка «на месте», без правки JSON.

Идея простая: пока вы настраиваете, управление мышью на паузе (курсор не
убегает из-под руки), а все изменения применяются сразу — двигаете ползунок
«скорость курсора» и видите, как рука ведёт курсор. Кнопки внизу окна:
«сохранить и закрыть», «сбросить» и «закрыть без сохранения».

Модуль разделён на две части: описание ползунков (``Sliders``) не зависит от
графики и покрыто тестами, а само окно (``SettingsWindow``) — тонкая обёртка
над ``cv2.createTrackbar``, которая аккуратно отключается, если OpenCV собран
без GUI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from . import text as T
from .config import AppConfig, save_config

log = logging.getLogger(__name__)

WINDOW_NAME = "AirMouse — настройки"

# цвета окна настроек
_BG = (238, 238, 240)
_FG = (28, 28, 32)
_DIM = (120, 120, 128)
_ACCENT = (60, 140, 70)
_CHANGED = (40, 90, 210)


@dataclass
class Slider:
    """Один ползунок: как читать значение из конфига и как записывать обратно."""

    key: str
    label: str
    group: str
    lo: float
    hi: float
    step: float
    get: Callable[[AppConfig], float]
    set: Callable[[AppConfig, float], None]
    fmt: str = "{:.2f}"
    hint: str = ""

    # ---------------------------------------------------------------- #
    @property
    def ticks(self) -> int:
        return max(int(round((self.hi - self.lo) / self.step)), 1)

    def to_pos(self, value: float) -> int:
        """Значение -> положение ползунка (целое 0..ticks)."""
        pos = int(round((float(value) - self.lo) / self.step))
        return max(0, min(self.ticks, pos))

    def from_pos(self, pos: int) -> float:
        """Положение ползунка -> значение (кратно шагу, в пределах lo..hi)."""
        value = self.lo + max(0, min(self.ticks, int(pos))) * self.step
        return round(min(self.hi, max(self.lo, value)), 6)

    def text(self, value: float) -> str:
        return self.fmt.format(value)


# --------------------------------------------------------------------------- #
#  Список ползунков
# --------------------------------------------------------------------------- #
def _box_get(index: int) -> Callable[[AppConfig], float]:
    # для правой/нижней границы ползунок показывает отступ от края кадра
    if index >= 2:
        return lambda cfg: round(1.0 - float(cfg.pointer.active_box[index]), 6)
    return lambda cfg: float(cfg.pointer.active_box[index])


def _box_set(index: int, side: str) -> Callable[[AppConfig, float], None]:
    def setter(cfg: AppConfig, value: float) -> None:
        box = list(cfg.pointer.active_box)
        # сдвиг от края кадра (доли кадра): левая/верхняя граница или отступ справа/снизу
        box[index] = float(value) if index < 2 else 1.0 - float(value)
        # не даём сжать зону в ничто
        if box[2] - box[0] < 0.15:
            if index == 0:
                box[0] = box[2] - 0.15
            elif index == 2:
                box[2] = box[0] + 0.15
        if box[3] - box[1] < 0.15:
            if index == 1:
                box[1] = box[3] - 0.15
            elif index == 3:
                box[3] = box[1] + 0.15
        cfg.pointer.active_box = tuple(round(v, 4) for v in box)

    return setter


def _set_pinch(cfg: AppConfig, value: float) -> None:
    cfg.hand.pinch_ratio = float(value)
    # отпускание всегда чуть выше порога — иначе щипок «залипает»
    cfg.hand.pinch_release_ratio = round(float(value) + 0.10, 4)


def build_sliders() -> List[Slider]:
    """Все ползунки окна настроек (порядок = порядок в окне)."""
    items: List[Slider] = []

    # ---------------- зона, в которой рука двигает курсор ----------------
    for index, label in ((0, "зона курсора: слева"), (1, "зона курсора: сверху"),
                         (2, "зона курсора: справа"), (3, "зона курсора: снизу")):
        items.append(Slider(
            key=f"pointer.active_box[{index}]",
            label=label,
            group="Курсор: где рука «достаёт» до края экрана",
            lo=0.02, hi=0.45, step=0.01,
            get=_box_get(index),
            set=_box_set(index, label),
            fmt="{:.2f}",
            hint="меньше отступ — рука ближе к краю двигает курсор к краю",
        ))
    items.append(Slider(
        key="pointer.min_cutoff",
        label="сглаживание курсора",
        group="Курсор: где рука «достаёт» до края экрана",
        lo=0.2, hi=3.0, step=0.05,
        get=lambda cfg: cfg.pointer.min_cutoff,
        set=lambda cfg, v: setattr(cfg.pointer, "min_cutoff", float(v)),
        hint="больше — плавнее, но с задержкой",
    ))
    items.append(Slider(
        key="pointer.deadzone_norm",
        label="мёртвая зона руки",
        group="Курсор: где рука «достаёт» до края экрана",
        lo=0.0, hi=0.012, step=0.0002,
        get=lambda cfg: cfg.pointer.deadzone_norm,
        set=lambda cfg, v: setattr(cfg.pointer, "deadzone_norm", float(v)),
        fmt="{:.4f}",
        hint="больше — курсор не дрожит, но мелкие движения пропадают",
    ))
    items.append(Slider(
        key="pointer.max_step_px",
        label="рывок курсора, px",
        group="Курсор: где рука «достаёт» до края экрана",
        lo=60.0, hi=600.0, step=10.0,
        get=lambda cfg: float(cfg.pointer.max_step_px),
        set=lambda cfg, v: setattr(cfg.pointer, "max_step_px", int(v)),
        fmt="{:.0f}",
        hint="ограничение «телепорта» мыши за один кадр",
    ))

    # ---------------- щипок и клики ----------------
    items.append(Slider(
        key="hand.pinch_ratio",
        label="щипок: порог смыкания",
        group="Щипок и клики",
        lo=0.15, hi=0.50, step=0.01,
        get=lambda cfg: cfg.hand.pinch_ratio,
        set=_set_pinch,
        hint="меньше — щипок нужно сводить плотнее (меньше ложных кликов)",
    ))
    items.append(Slider(
        key="hand.pinch_approach_ratio",
        label="прицел: когда замирает курсор",
        group="Щипок и клики",
        lo=0.35, hi=1.20, step=0.01,
        get=lambda cfg: cfg.hand.pinch_approach_ratio,
        set=lambda cfg, v: setattr(cfg.hand, "pinch_approach_ratio", float(v)),
        hint="больше — курсор замирает раньше, ещё до смыкания",
    ))
    items.append(Slider(
        key="hand.pinch_min_s",
        label="щипок: минимальное удержание, с",
        group="Щипок и клики",
        lo=0.0, hi=0.30, step=0.01,
        get=lambda cfg: cfg.hand.pinch_min_s,
        set=lambda cfg, v: setattr(cfg.hand, "pinch_min_s", float(v)),
        hint="короче — не клик, а дребезг распознавания",
    ))
    items.append(Slider(
        key="hand.drag_delay_s",
        label="перетаскивание: задержка, с",
        group="Щипок и клики",
        lo=0.10, hi=1.00, step=0.01,
        get=lambda cfg: cfg.hand.drag_delay_s,
        set=lambda cfg, v: setattr(cfg.hand, "drag_delay_s", float(v)),
        hint="сколько держать щипок, чтобы началось перетаскивание",
    ))
    items.append(Slider(
        key="hand.click_cooldown_s",
        label="пауза между кликами, с",
        group="Щипок и клики",
        lo=0.10, hi=1.00, step=0.01,
        get=lambda cfg: cfg.hand.click_cooldown_s,
        set=lambda cfg, v: setattr(cfg.hand, "click_cooldown_s", float(v)),
        hint="больше — труднее случайно кликнуть дважды",
    ))
    items.append(Slider(
        key="hand.pose_stable_frames",
        label="жест должен держаться, кадров",
        group="Щипок и клики",
        lo=1.0, hi=8.0, step=1.0,
        get=lambda cfg: float(cfg.hand.pose_stable_frames),
        set=lambda cfg, v: setattr(cfg.hand, "pose_stable_frames", int(v)),
        fmt="{:.0f}",
        hint="больше — строже к жестам, меньше ложных срабатываний",
    ))
    items.append(Slider(
        key="hand.open_palm_hold_s",
        label="пауза по ладони, с",
        group="Щипок и клики",
        lo=0.60, hi=3.00, step=0.05,
        get=lambda cfg: cfg.hand.open_palm_hold_s,
        set=lambda cfg, v: setattr(cfg.hand, "open_palm_hold_s", float(v)),
        hint="сколько держать раскрытую ладонь неподвижно",
    ))
    items.append(Slider(
        key="hand.fist_scroll_gain",
        label="прокрутка кулаком: скорость",
        group="Щипок и клики",
        lo=4.0, hi=60.0, step=1.0,
        get=lambda cfg: cfg.hand.fist_scroll_gain,
        set=lambda cfg, v: setattr(cfg.hand, "fist_scroll_gain", float(v)),
        fmt="{:.0f}",
        hint="сколько «тиков» колеса на сантиметр движения кулака",
    ))

    # ---------------- мышь головой ----------------
    items.append(Slider(
        key="face.head_gain_x",
        label="мышь головой: влево-вправо",
        group="Мышь головой (клавиша H)",
        lo=2.0, hi=60.0, step=1.0,
        get=lambda cfg: cfg.face.head_gain_x,
        set=lambda cfg, v: setattr(cfg.face, "head_gain_x", float(v)),
        fmt="{:.0f}",
        hint="пикселей в секунду на градус поворота головы",
    ))
    items.append(Slider(
        key="face.head_gain_y",
        label="мышь головой: вверх-вниз",
        group="Мышь головой (клавиша H)",
        lo=2.0, hi=50.0, step=1.0,
        get=lambda cfg: cfg.face.head_gain_y,
        set=lambda cfg, v: setattr(cfg.face, "head_gain_y", float(v)),
        fmt="{:.0f}",
        hint="наклон головы вверх-вниз двигает курсор по вертикали",
    ))
    items.append(Slider(
        key="face.head_deadzone_deg",
        label="мышь головой: мёртвая зона, °",
        group="Мышь головой (клавиша H)",
        lo=0.5, hi=12.0, step=0.5,
        get=lambda cfg: cfg.face.head_deadzone_deg,
        set=lambda cfg, v: setattr(cfg.face, "head_deadzone_deg", float(v)),
        fmt="{:.1f}",
        hint="в этой зоне курсор стоит — убирает дрожание головы",
    ))

    # ---------------- две руки ----------------
    items.append(Slider(
        key="hand.two_hand_zoom_gain",
        label="масштаб двумя руками: скорость",
        group="Две руки",
        lo=5.0, hi=80.0, step=1.0,
        get=lambda cfg: cfg.hand.two_hand_zoom_gain,
        set=lambda cfg, v: setattr(cfg.hand, "two_hand_zoom_gain", float(v)),
        fmt="{:.0f}",
        hint="как сильно разведение ладоней крутит колесо с Ctrl",
    ))
    items.append(Slider(
        key="hand.two_hand_scroll_gain",
        label="прокрутка двумя руками: скорость",
        group="Две руки",
        lo=5.0, hi=60.0, step=1.0,
        get=lambda cfg: cfg.hand.two_hand_scroll_gain,
        set=lambda cfg, v: setattr(cfg.hand, "two_hand_scroll_gain", float(v)),
        fmt="{:.0f}",
        hint="два кулака вверх/вниз — сколько тиков на движение",
    ))
    return items


SLIDERS: List[Slider] = build_sliders()
DEFAULTS: Dict[str, float] = {s.key: s.get(AppConfig()) for s in SLIDERS}


def groups(sliders: Sequence[Slider]) -> List[Tuple[str, List[Slider]]]:
    """Ползунки, сгруппированные по подписям (в порядке появления)."""
    out: List[Tuple[str, List[Slider]]] = []
    for slider in sliders:
        if not out or out[-1][0] != slider.group:
            out.append((slider.group, []))
        out[-1][1].append(slider)
    return out


def apply_defaults(cfg: AppConfig, sliders: Sequence[Slider] = SLIDERS) -> None:
    """Вернуть все настройки к заводским значениям."""
    fresh = AppConfig()
    for slider in sliders:
        slider.set(cfg, slider.get(fresh))


def changed_values(cfg: AppConfig, sliders: Sequence[Slider] = SLIDERS) -> List[str]:
    """Какие параметры отличаются от заводских — для строки «изменено: N»."""
    out = []
    for slider in sliders:
        if abs(slider.get(cfg) - DEFAULTS[slider.key]) > 1e-9:
            out.append(slider.key)
    return out


# --------------------------------------------------------------------------- #
#  Панель настроек внутри окна предпросмотра
# --------------------------------------------------------------------------- #
# Ползунки рисуются сами, а не средствами OpenCV: так подписи гарантированно
# на русском (встроенные ползунки HighGUI на Windows показывают кириллицу
# «кракозябрами»), а вид совпадает с остальным окном.
PAGE_ORDER = ("Курсор", "Щипок и клики", "Голова и две руки")

_BG = (26, 26, 30)
_PANEL = (34, 34, 39)
_FG = (238, 238, 240)
_DIM = (150, 150, 158)
_ACCENT = (120, 220, 140)
_WARN = (90, 190, 250)
_CHANGED = (90, 150, 255)
_TRACK = (70, 70, 78)
_KNOB = (235, 235, 240)

BUTTONS = ("СОХРАНИТЬ", "СБРОС", "ЗАКРЫТЬ")


@dataclass
class Page:
    title: str
    sliders: List[Slider]


def build_pages(sliders: Sequence[Slider] = SLIDERS) -> List[Page]:
    """Разложить ползунки по страницам: курсор / щипок / голова и две руки."""
    groups_all = groups(sliders)
    cursor = [s for name, items in groups_all if name.startswith("Курсор") for s in items]
    pinch = [s for name, items in groups_all if name.startswith("Щипок") for s in items]
    rest = [s for name, items in groups_all
            if not name.startswith("Курсор") and not name.startswith("Щипок") for s in items]
    return [Page(PAGE_ORDER[0], cursor), Page(PAGE_ORDER[1], pinch), Page(PAGE_ORDER[2], rest)]


@dataclass
class Row:
    """Одна строка страницы: ползунок и его прямоугольник на экране."""

    slider: Optional[Slider]
    rect: Tuple[int, int, int, int]     # x, y, w, h
    track: Tuple[int, int, int, int]    # x, y, w, h — сама «дорожка»
    label_y: int


class SettingsPanel:
    """Само окно настроек: рисует ползунки, ловит мышь и клавиши.

    Управление: мышь — тянуть ползунок; клавиши ``1..3`` — страница, ``Tab`` —
    следующая страница, ``S`` — сохранить и закрыть, ``R`` — сброс,
    ``Esc``/``C`` — закрыть (изменения сохраняются, если они есть).
    """

    MARGIN = 26
    ROW_H = 38
    FIRST_Y = 106
    KNOB_R = 8

    def __init__(self, cfg: AppConfig, path: Optional[Path] = None,
                 sliders: Optional[Sequence[Slider]] = None) -> None:
        self.cfg = cfg
        self.path = path
        self.pages = build_pages(sliders if sliders is not None else SLIDERS)
        self.page = 0
        self.is_open = False
        self.dirty = False
        self.saved = False
        self.status = ""
        self.live = ""
        self._drag: Optional[Slider] = None
        self._hover_button = -1

    # ------------------------------------------------------------------ #
    @property
    def sliders(self) -> List[Slider]:
        return [s for page in self.pages for s in page.sliders]

    def open(self) -> bool:
        self.is_open = True
        self.dirty = False
        self.saved = False
        self.status = "тяните ползунки мышью"
        return True

    def close(self, save: bool = False) -> None:
        if save:
            self.save()
        self.is_open = False
        self._drag = None

    def save(self) -> Path:
        path = save_config(self.cfg, self.path)
        self.saved = True
        self.dirty = False
        self.status = f"сохранено: {path}"
        log.info("Настройки сохранены: %s", path)
        return path

    def reset(self) -> None:
        apply_defaults(self.cfg, self.sliders)
        self.dirty = True
        self.status = "вернули заводские настройки"

    def next_page(self) -> None:
        self.page = (self.page + 1) % len(self.pages)

    def goto_page(self, index: int) -> None:
        self.page = max(0, min(len(self.pages) - 1, index))

    # ------------------------------------------------------------------ #
    def layout(self, size: Tuple[int, int] = (960, 540)) -> List[Row]:
        """Положение строк текущей страницы (в пикселях кадра)."""
        w, h = size
        k = max(min(h / 540.0, w / 960.0), 0.5)
        rows: List[Row] = []
        y = int(self.FIRST_Y * k)
        x = int(self.MARGIN * k)
        row_h = int(self.ROW_H * k)
        track_w = int(w - 2 * self.MARGIN * k)
        for slider in self.pages[self.page].sliders:
            rows.append(Row(
                slider=slider,
                rect=(x, y, track_w, row_h),
                track=(x, y + int(22 * k), track_w, max(int(8 * k), 6)),
                label_y=y,
            ))
            y += row_h
        return rows

    def buttons(self, size: Tuple[int, int] = (960, 540)) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """Прямоугольники кнопок внизу страницы."""
        w, h = size
        k = max(min(h / 540.0, w / 960.0), 0.5)
        height = int(30 * k)
        y = h - height - int(46 * k)
        widths = (int(190 * k), int(150 * k), int(170 * k))
        gap = int(14 * k)
        total = sum(widths) + 2 * gap
        x = (w - total) // 2
        out = []
        for name, width in zip(BUTTONS, widths):
            out.append((name, (x, y, width, height)))
            x += width + gap
        return out

    # ------------------------------------------------------------------ #
    def value_at(self, row: Row, x: int) -> float:
        """Координата мыши по дорожке -> значение ползунка."""
        slider = row.slider
        assert slider is not None
        rx, _ry, rw, _rh = row.track
        t = 0.0 if rw <= 0 else (float(x) - rx) / float(rw)
        t = max(0.0, min(1.0, t))
        return slider.from_pos(int(round(t * slider.ticks)))

    def knob_x(self, row: Row) -> int:
        slider = row.slider
        assert slider is not None
        rx, _ry, rw, _rh = row.track
        ticks = max(slider.ticks, 1)
        return rx + int(round(rw * slider.to_pos(slider.get(self.cfg)) / ticks))

    # ------------------------------------------------------------------ #
    def on_mouse(self, event: int, x: int, y: int, size: Tuple[int, int] = (960, 540)) -> Optional[str]:
        """Обработка мыши. Возвращает действие: save/reset/close или None."""
        if not self.is_open:
            return None
        rows = self.layout(size)
        buttons = self.buttons(size)

        if event in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_LBUTTONUP, cv2.EVENT_MOUSEMOVE):
            pass

        if event == cv2.EVENT_LBUTTONDOWN:
            for name, (bx, by, bw, bh) in buttons:
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if name == "СОХРАНИТЬ":
                        self.close(save=True)
                        return "save"
                    if name == "СБРОС":
                        self.reset()
                        return "reset"
                    self.close(save=self.dirty)
                    return "close"
            for row in rows:
                rx, ry, rw, rh = row.rect
                if rx <= x <= rx + rw and ry <= y <= ry + rh:
                    self._drag = row.slider
                    self._apply(row, x)
                    return "change"

        if event == cv2.EVENT_MOUSEMOVE and self._drag is not None:
            for row in rows:
                if row.slider is self._drag:
                    self._apply(row, x)
                    return "change"

        if event == cv2.EVENT_LBUTTONUP:
            self._drag = None
        return None

    def _apply(self, row: Row, x: int) -> None:
        slider = row.slider
        assert slider is not None
        value = self.value_at(row, x)
        if abs(slider.get(self.cfg) - value) < 1e-9:
            return
        slider.set(self.cfg, value)
        self.dirty = True
        value_text = slider.text(slider.get(self.cfg))
        self.status = (f"{slider.label}: {value_text} — {slider.hint}"
                       if slider.hint else f"{slider.label}: {value_text}")

    def on_key(self, key: int) -> Optional[str]:
        """Клавиши в окне настроек. Возвращает действие или None."""
        if not self.is_open:
            return None
        if key in (27, ord("c"), ord("C"), ord("с"), ord("С")):
            self.close(save=self.dirty)
            return "close" if not self.saved else "save"
        if key in (ord("s"), ord("S"), ord("ы"), ord("Ы")):
            self.close(save=True)
            return "save"
        if key in (ord("r"), ord("R"), ord("к"), ord("К")):
            self.reset()
            return "reset"
        if key in (9, ord(" ")):
            self.next_page()
            return "page"
        if ord("1") <= key <= ord("9"):
            self.goto_page(key - ord("1"))
            return "page"
        return None

    # ------------------------------------------------------------------ #
    def draw(self, img: np.ndarray, live: str = "") -> np.ndarray:
        """Нарисовать панель поверх кадра."""
        if not self.is_open:
            return img
        h, w = img.shape[:2]
        k = max(min(h / 540.0, w / 960.0), 0.5)
        img[:] = _BG

        T.draw(img, "Настройки AirMouse", (int(self.MARGIN * k), int(14 * k)), int(24 * k), _FG)
        T.draw(img, "Ползунки двигаются мышью · управление на паузе, курсор не убежит",
               (int(self.MARGIN * k), int(48 * k)), int(14 * k), _DIM)

        # вкладки страниц
        x = int(self.MARGIN * k)
        tab_y = int(72 * k)
        for i, page in enumerate(self.pages):
            active = i == self.page
            title = f"{i + 1}. {page.title}"
            width, _ = T.measure(title, int(14 * k))
            color = _ACCENT if active else _DIM
            T.draw(img, title, (x, tab_y), int(14 * k), color)
            if active:
                cv2.line(img, (x, tab_y + int(20 * k)),
                         (x + width, tab_y + int(20 * k)), _ACCENT, 2, cv2.LINE_AA)
            x += width + int(26 * k)

        # строки-ползунки
        for row in self.layout((w, h)):
            slider = row.slider
            assert slider is not None
            value = slider.get(self.cfg)
            changed = abs(value - DEFAULTS[slider.key]) > 1e-9
            color = _CHANGED if changed else _FG
            T.draw(img, slider.label, (row.rect[0], row.label_y), int(15 * k), color)
            text = slider.text(value)
            tw, _ = T.measure(text, int(15 * k))
            T.draw(img, text, (row.rect[0] + row.rect[2] - tw, row.label_y), int(15 * k),
                   _ACCENT if changed else _WARN)

            tx, ty, tw_, th = row.track
            cv2.rectangle(img, (tx, ty), (tx + tw_, ty + th), _TRACK, -1)
            fill_to = self.knob_x(row)
            cv2.rectangle(img, (tx, ty), (fill_to, ty + th), _ACCENT if changed else _WARN, -1)
            r = int(self.KNOB_R * k)
            cv2.circle(img, (fill_to, ty + th // 2), r, _KNOB, -1, cv2.LINE_AA)
            cv2.circle(img, (fill_to, ty + th // 2), r, _BG, 1, cv2.LINE_AA)

        # кнопки
        for name, (bx, by, bw, bh) in self.buttons((w, h)):
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), _PANEL, -1)
            border = _ACCENT if name == "СОХРАНИТЬ" else _DIM
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), border, 1, cv2.LINE_AA)
            tw, th_ = T.measure(name, int(14 * k))
            T.draw(img, name, (bx + (bw - tw) // 2, by + (bh - th_) // 2), int(14 * k),
                   _ACCENT if name == "СОХРАНИТЬ" else _FG)

        # нижняя строка: что изменено, живые цифры и подсказка по последнему ползунку
        live_y = self.buttons((w, h))[0][1][1] - int(24 * k)
        differ = len(changed_values(self.cfg, self.sliders))
        note = f"изменено: {differ}" if differ else "всё как на заводе"
        T.draw(img, note, (int(self.MARGIN * k), live_y), int(13 * k),
               _CHANGED if differ else _DIM)
        left_x = int(self.MARGIN * k) + int(120 * k)
        right_edge = w - int(self.MARGIN * k)
        status = self.status[:70]
        status_w = T.measure(status, int(12 * k))[0] if status else 0
        if status:
            T.draw(img, status, (right_edge - status_w, live_y), int(12 * k), _DIM)
        if live:
            room = max(right_edge - status_w - left_x - int(16 * k), int(80 * k))
            text = live
            while text and T.measure(text, int(13 * k))[0] > room:
                text = text[:-1]
            T.draw(img, text, (left_x, live_y), int(13 * k), _FG)
        return img
