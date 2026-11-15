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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from . import text as T
from . import keys
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

    # ---------------- моргание и глаза ----------------
    items.append(Slider(
        key="face.blink_min_s",
        label="моргание: время захвата, с",
        group="Моргание и глаза",
        lo=0.04, hi=0.30, step=0.01,
        get=lambda cfg: cfg.face.blink_min_s,
        set=lambda cfg, v: setattr(cfg.face, "blink_min_s", float(v)),
        fmt="{:.2f}",
        hint="короче этого — не моргание, а случайное прищуривание",
    ))
    items.append(Slider(
        key="face.wink_min_s",
        label="подмигивание: сколько держать, с",
        group="Моргание и глаза",
        lo=0.10, hi=0.80, step=0.05,
        get=lambda cfg: cfg.face.wink_min_s,
        set=lambda cfg, v: setattr(cfg.face, "wink_min_s", float(v)),
        fmt="{:.2f}",
        hint="один глаз закрыт дольше этого — подмигивание",
    ))
    items.append(Slider(
        key="face.eyes_closed_cap_s",
        label="закрытые глаза: предел, с",
        group="Моргание и глаза",
        lo=1.0, hi=10.0, step=0.5,
        get=lambda cfg: cfg.face.eyes_closed_cap_s,
        set=lambda cfg, v: setattr(cfg.face, "eyes_closed_cap_s", float(v)),
        fmt="{:.1f}",
        hint="дольше — ничего не засчитываем, пока глаза не откроются",
    ))
    items.append(Slider(
        key="face.gaze_speed_px_s",
        label="мышь глазами: скорость",
        group="Моргание и глаза",
        lo=100.0, hi=1500.0, step=25.0,
        get=lambda cfg: cfg.face.gaze_speed_px_s,
        set=lambda cfg, v: setattr(cfg.face, "gaze_speed_px_s", float(v)),
        fmt="{:.0f}",
        hint="пикселей в секунду, когда зрачок у края глаза",
    ))
    items.append(Slider(
        key="face.gaze_deadzone",
        label="мышь глазами: мёртвая зона, влево-вправо",
        group="Моргание и глаза",
        lo=0.02, hi=0.30, step=0.01,
        get=lambda cfg: cfg.face.gaze_deadzone,
        set=lambda cfg, v: setattr(cfg.face, "gaze_deadzone", float(v)),
        fmt="{:.2f}",
        hint="доля полуширины глаза: в этой зоне курсор стоит",
    ))
    items.append(Slider(
        key="face.gaze_deadzone_y",
        label="мышь глазами: мёртвая зона, вверх-вниз",
        group="Моргание и глаза",
        lo=0.01, hi=0.20, step=0.01,
        get=lambda cfg: cfg.face.gaze_deadzone_y,
        set=lambda cfg, v: setattr(cfg.face, "gaze_deadzone_y", float(v)),
        fmt="{:.2f}",
        hint="по вертикали зрачок ходит меньше, поэтому зона своя",
    ))
    items.append(Slider(
        key="face.gaze_full_scale_x",
        label="мышь глазами: размах, влево-вправо",
        group="Моргание и глаза",
        lo=0.10, hi=0.60, step=0.01,
        get=lambda cfg: cfg.face.gaze_full_scale_x,
        set=lambda cfg, v: setattr(cfg.face, "gaze_full_scale_x", float(v)),
        fmt="{:.2f}",
        hint="меньше — резче: отклонение зрачка, дающее полную скорость",
    ))
    items.append(Slider(
        key="face.gaze_full_scale_y",
        label="мышь глазами: размах, вверх-вниз",
        group="Моргание и глаза",
        lo=0.06, hi=0.45, step=0.01,
        get=lambda cfg: cfg.face.gaze_full_scale_y,
        set=lambda cfg, v: setattr(cfg.face, "gaze_full_scale_y", float(v)),
        fmt="{:.2f}",
        hint="меньше — резче по вертикали",
    ))

    # ---------------- окно и трекер кисти ----------------
    items.append(Slider(
        key="window_scale",
        label="окно при старте: доля экрана",
        group="Окно и рука",
        lo=0.4, hi=1.0, step=0.05,
        get=lambda cfg: cfg.window_scale,
        set=lambda cfg, v: setattr(cfg, "window_scale", float(v)),
        fmt="{:.2f}",
        hint="1.00 — во весь экран, 0.85 — почти весь; F — полный экран на ходу",
    ))
    items.append(Slider(
        key="hand.predict_frames",
        label="кисть: дорисовывать, кадров",
        group="Окно и рука",
        lo=0.0, hi=15.0, step=1.0,
        get=lambda cfg: float(cfg.hand.predict_frames),
        set=lambda cfg, v: setattr(cfg.hand, "predict_frames", int(round(float(v)))),
        fmt="{:.0f}",
        hint="сколько кадров вести руку по инерции, когда её не видно (6 ≈ 0.2 с)",
    ))

    # ---------------- надёжность руки ----------------
    items.append(Slider(
        key="hand.min_score",
        label="уверенность, что это рука",
        group="Надёжность руки",
        lo=0.20, hi=0.90, step=0.05,
        get=lambda cfg: cfg.hand.min_score,
        set=lambda cfg, v: setattr(cfg.hand, "min_score", float(v)),
        fmt="{:.2f}",
        hint="выше — меньше ложных «рук» там, где их нет; ниже — ловит дальние руки",
    ))

    # ---------------- тело целиком ----------------
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
        key="body.min_visibility",
        label="тело: порог видимости точки",
        group="Тело",
        lo=0.20, hi=0.90, step=0.05,
        get=lambda cfg: cfg.body.min_visibility,
        set=lambda cfg, v: setattr(cfg.body, "min_visibility", float(v)),
        fmt="{:.2f}",
        hint="выше — строже: «видно по пояс» становится чаще, случайные точки реже",
    ))
    items.append(Slider(
        key="body.every_n_frames",
        label="тело: считать позу раз в N кадров",
        group="Тело",
        lo=1.0, hi=5.0, step=1.0,
        get=lambda cfg: float(cfg.body.every_n_frames),
        set=lambda cfg, v: setattr(cfg.body, "every_n_frames", max(1, int(round(v)))),
        fmt="{:.0f}",
        hint="2 — вдвое меньше нагрузки на CPU, поза обновляется 15 раз в секунду",
    ))
    items.append(Slider(
        key="body.squat_down",
        label="присед: глубина «присел»",
        group="Тело",
        lo=0.25, hi=0.80, step=0.05,
        get=lambda cfg: cfg.body.squat_down,
        set=lambda cfg, v: setattr(cfg.body, "squat_down", float(v)),
        fmt="{:.2f}",
        hint="не считает приседания — уменьшите; считает лишние — увеличьте",
    ))
    items.append(Slider(
        key="body.squat_up",
        label="присед: глубина «встал»",
        group="Тело",
        lo=0.05, hi=0.40, step=0.05,
        get=lambda cfg: cfg.body.squat_up,
        set=lambda cfg, v: setattr(cfg.body, "squat_up", float(v)),
        fmt="{:.2f}",
        hint="должно быть меньше «присел»: разница — запас против дребезга",
    ))
    items.append(Slider(
        key="body.squat_min_s",
        label="присед: минимальный повтор, с",
        group="Тело",
        lo=0.10, hi=1.00, step=0.05,
        get=lambda cfg: cfg.body.squat_min_s,
        set=lambda cfg, v: setattr(cfg.body, "squat_min_s", float(v)),
        fmt="{:.2f}",
        hint="короче — дребезг точек, а не повторение",
    ))
    items.append(Slider(
        key="body.lean_deg",
        label="наклон корпуса, градусы",
        group="Тело",
        lo=10.0, hi=60.0, step=5.0,
        get=lambda cfg: cfg.body.lean_deg,
        set=lambda cfg, v: setattr(cfg.body, "lean_deg", float(v)),
        fmt="{:.0f}",
        hint="с какого угла считать наклоном вперёд/в сторону",
    ))
    items.append(Slider(
        key="body.arms_up_hold_s",
        label="руки вверх: сколько держать, с",
        group="Тело",
        lo=0.20, hi=2.00, step=0.10,
        get=lambda cfg: cfg.body.arms_up_hold_s,
        set=lambda cfg, v: setattr(cfg.body, "arms_up_hold_s", float(v)),
        fmt="{:.1f}",
        hint="дольше — случайно поднятая рука не считается жестом",
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
PAGE_ORDER = ("Режимы", "Курсор", "Щипок и клики", "Голова и руки",
              "Моргание и глаза", "Тело", "Окно и рука")
PAGE_EYES = 4
PAGE_BODY = 5
PAGE_WINDOW = 6

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

# готовые наборы режимов — одна кнопка вместо трёх переключателей
PRESETS = ("РУКА", "РУКА + ЛИЦО", "ДВЕ РУКИ", "ТОЛЬКО ЛИЦО")


@dataclass
class Toggle:
    """Переключатель режима: что включено прямо сейчас и как это менять."""

    key: str
    label: str
    hint: str
    get: Callable[[AppConfig, Any], bool]
    set: Callable[[AppConfig, Any, bool], None]

    def state(self, cfg: AppConfig, runtime: Any = None) -> bool:
        return bool(self.get(cfg, runtime))

    def flip(self, cfg: AppConfig, runtime: Any = None) -> bool:
        value = not self.state(cfg, runtime)
        self.set(cfg, runtime, value)
        return self.state(cfg, runtime)


def _set_two_hand(mode: str) -> Callable[[AppConfig, Any, bool], None]:
    def setter(cfg: AppConfig, runtime: Any, on: bool) -> None:
        if on:
            # одновременно «вторая рука нажимает» и «две руки масштабируют»
            # невозможно — это одни и те же две руки в кадре
            cfg.hand.roles = "single"
            cfg.hand.two_hand = mode
        elif cfg.hand.two_hand == mode:
            cfg.hand.two_hand = "off"

    return setter


def _set_body(cfg: AppConfig, runtime: Any, on: bool) -> None:
    """Режим тела: сам движок пересоздаёт приложение (см. AirMouseApp.set_body)."""
    cfg.body.enabled = bool(on)


def build_toggles() -> List[Toggle]:
    """Режимы, которые можно включать в любых сочетаниях."""
    return [
        Toggle(
            key="mode.hand",
            label="Рука: курсор, клики, жесты",
            hint="одна рука: курсор, клики, жесты",
            get=lambda cfg, rt: cfg.hand.enabled,
            set=lambda cfg, rt, on: setattr(cfg.hand, "enabled", bool(on)),
        ),
        Toggle(
            key="mode.second_hand",
            label="Вторая рука: только нажатия и жесты",
            hint="первая ведёт курсор, вторая нажимает",
            get=lambda cfg, rt: cfg.hand.roles == "split",
            set=lambda cfg, rt, on: setattr(cfg.hand, "roles", "split" if on else "single"),
        ),
        Toggle(
            key="mode.simple_two_hand",
            label="Двумя руками: щипок проще",
            hint="щипок ловится с меньшим запасом",
            get=lambda cfg, rt: bool(getattr(cfg.hand, "simple_two_hand", True)),
            set=lambda cfg, rt, on: setattr(cfg.hand, "simple_two_hand", bool(on)),
        ),
        Toggle(
            key="mode.two_zoom",
            label="Две руки: масштаб (Ctrl + колесо)",
            hint="обе ладони: развести или свести",
            get=lambda cfg, rt: cfg.hand.two_hand == "zoom",
            set=_set_two_hand("zoom"),
        ),
        Toggle(
            key="mode.two_scroll",
            label="Две руки: прокрутка двумя кулаками",
            hint="два кулака вверх или вниз",
            get=lambda cfg, rt: cfg.hand.two_hand == "scroll",
            set=_set_two_hand("scroll"),
        ),
        Toggle(
            key="mode.face",
            label="Лицо: мимика, кивок, поворот",
            hint="мимика, моргание, кивок — вместе с рукой",
            get=lambda cfg, rt: cfg.face.enabled,
            set=lambda cfg, rt, on: setattr(cfg.face, "enabled", bool(on)),
        ),
        Toggle(
            key="mode.head_pointer",
            label="Мышь головой",
            hint="наклон головы двигает курсор",
            get=lambda cfg, rt: bool(getattr(rt, "head_pointer", cfg.head_pointer)),
            set=_set_head_pointer,
        ),
        Toggle(
            key="mode.body",
            label="Тело: скелет и упражнения",
            hint="приседания, наклон, руки вверх (нужен MediaPipe)",
            get=lambda cfg, rt: bool(getattr(cfg.body, "enabled", False)),
            set=_set_body,
        ),
        Toggle(
            key="mode.gaze_pointer",
            label="Мышь глазами: курсор от зрачков",
            hint="взгляд уводит курсор (нужна калибровка)",
            get=lambda cfg, rt: bool(getattr(rt, "gaze_pointer", cfg.gaze_pointer)),
            set=_set_gaze_pointer,
        ),
    ]


HAND_TOGGLES: List[Toggle] = [
    Toggle(
        key="hand.physics",
        label="Физика пальцев",
        hint="пределы сгиба и связка соседних пальцев",
        get=lambda cfg, rt: bool(getattr(cfg.hand, "physics", True)),
        set=lambda cfg, rt, on: setattr(cfg.hand, "physics", bool(on)),
    ),
    Toggle(
        key="hand.predict_use_body",
        label="Кисть по телу",
        hint="предсказанную кисть подтягивать к запястью из тела",
        get=lambda cfg, rt: bool(getattr(cfg.hand, "predict_use_body", True)),
        set=lambda cfg, rt, on: setattr(cfg.hand, "predict_use_body", bool(on)),
    ),
]


BODY_TOGGLES: List[Toggle] = [
    Toggle(
        key="body.sport",
        label="Спорт: сгибания, T-поза, бокс",
        hint="считает повторы, стойку и удары по скелету тела",
        get=lambda cfg, rt: bool(getattr(cfg.body, "sport", True)),
        set=lambda cfg, rt, on: setattr(cfg.body, "sport", bool(on)),
    ),
]


def _set_head_pointer(cfg: AppConfig, runtime: Any, on: bool) -> None:
    cfg.head_pointer = bool(on)
    if runtime is not None and hasattr(runtime, "head_pointer"):
        runtime.head_pointer = bool(on)


def _set_gaze_pointer(cfg: AppConfig, runtime: Any, on: bool) -> None:
    cfg.gaze_pointer = bool(on)
    if runtime is not None and hasattr(runtime, "gaze_pointer"):
        runtime.gaze_pointer = bool(on)


TOGGLES: List[Toggle] = build_toggles()


@dataclass
class Page:
    title: str
    sliders: List[Slider]
    toggles: List[Toggle] = field(default_factory=list)
    presets: bool = False


def build_pages(sliders: Sequence[Slider] = SLIDERS,
                toggles: Sequence[Toggle] = TOGGLES) -> List[Page]:
    """Страницы: режимы / курсор / щипок / голова и две руки."""
    groups_all = groups(sliders)
    def pick(prefixes):
        return [s for name, items in groups_all
                if any(name.startswith(p) for p in prefixes) for s in items]

    cursor = pick(("Курсор",))
    pinch = pick(("Щипок",))
    eyes = pick(("Моргание",))
    body = pick(("Тело",))
    window = pick(("Окно",))
    rest = [s for name, items in groups_all
            if not any(name.startswith(p) for p in ("Курсор", "Щипок", "Моргание", "Тело",
                                                    "Окно"))
            for s in items]
    return [
        Page(PAGE_ORDER[0], [], list(toggles), presets=True),
        Page(PAGE_ORDER[1], cursor),
        Page(PAGE_ORDER[2], pinch),
        Page(PAGE_ORDER[3], rest),
        Page(PAGE_ORDER[4], eyes),
        Page(PAGE_ORDER[5], body, list(BODY_TOGGLES)),
        Page(PAGE_ORDER[6], window, list(HAND_TOGGLES), presets=False),
    ]


# --------------------------------------------------------------------------- #
#  Готовые наборы режимов
# --------------------------------------------------------------------------- #
def modes_summary(cfg: AppConfig, runtime: Any = None) -> str:
    """Короткое описание того, что сейчас включено: «рука + лицо»."""
    parts: List[str] = []
    if cfg.hand.enabled:
        parts.append("рука")
        if cfg.hand.roles == "split":
            parts.append("2-я рука: нажатия")
        elif cfg.hand.two_hand == "zoom":
            parts.append("две руки: масштаб")
        elif cfg.hand.two_hand == "scroll":
            parts.append("две руки: прокрутка")
    if cfg.face.enabled:
        parts.append("лицо")
    if bool(getattr(runtime, "head_pointer", cfg.head_pointer)):
        parts.append("мышь головой")
    if bool(getattr(runtime, "gaze_pointer", cfg.gaze_pointer)):
        parts.append("мышь глазами")
    return " + ".join(parts) if parts else "всё выключено"


def current_preset(cfg: AppConfig, runtime: Any = None) -> str:
    """Какой готовый режим сейчас действует (по состоянию переключателей)."""
    if not cfg.hand.enabled and cfg.face.enabled:
        return "ТОЛЬКО ЛИЦО"
    if cfg.hand.enabled and cfg.hand.roles == "split":
        return "ДВЕ РУКИ"
    if cfg.hand.enabled and cfg.face.enabled:
        return "РУКА + ЛИЦО"
    return "РУКА"


def cycle_preset(cfg: AppConfig, runtime: Any = None) -> str:
    """Переключить готовый режим по кругу (клавиша V) и вернуть его название."""
    names = list(PRESETS)
    current = current_preset(cfg, runtime)
    index = names.index(current) if current in names else -1
    nxt = names[(index + 1) % len(names)]
    apply_preset(cfg, runtime, nxt)
    return nxt


def apply_preset(cfg: AppConfig, runtime: Any, name: str) -> None:
    """Один клик — готовое сочетание режимов."""
    def find(key: str) -> Toggle:
        return next(t for t in TOGGLES if t.key == key)

    def state(toggle: Toggle) -> bool:
        return toggle.state(cfg, runtime)

    def turn(keys: Sequence[str], on: bool) -> None:
        for key in keys:
            toggle = find(key)
            if state(toggle) != on:
                toggle.set(cfg, runtime, on)

    if name == "РУКА":
        # строго одна рука: вторая ничего не делает, лицо выключено
        turn(["mode.two_zoom", "mode.two_scroll", "mode.second_hand"], False)
        turn(["mode.hand"], True)
        turn(["mode.face"], False)
        turn(["mode.head_pointer", "mode.gaze_pointer"], False)
    elif name == "РУКА + ЛИЦО":
        turn(["mode.two_zoom", "mode.two_scroll", "mode.second_hand"], False)
        turn(["mode.hand", "mode.face"], True)
    elif name == "ДВЕ РУКИ":
        turn(["mode.two_zoom", "mode.two_scroll"], False)
        turn(["mode.hand", "mode.second_hand"], True)
    elif name == "ТОЛЬКО ЛИЦО":
        turn(["mode.two_zoom", "mode.two_scroll", "mode.second_hand"], False)
        turn(["mode.face"], True)
        turn(["mode.hand"], False)


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
    ROW_H = 34
    FIRST_Y = 106
    KNOB_R = 8

    def __init__(self, cfg: AppConfig, path: Optional[Path] = None,
                 sliders: Optional[Sequence[Slider]] = None,
                 runtime: Any = None,
                 toggles: Optional[Sequence[Toggle]] = None,
                 hooks: Optional[Dict[str, Any]] = None) -> None:
        self.cfg = cfg
        self.path = path
        self.runtime = runtime
        self.hooks: Dict[str, Any] = dict(hooks or {})
        self.toggle_items: List[Toggle] = list(toggles if toggles is not None else TOGGLES)
        self.pages = build_pages(sliders if sliders is not None else SLIDERS,
                                 self.toggle_items)
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
        self.status = "переключайте режимы или тяните ползунки"
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
    def toggles_in_columns(self) -> int:
        """Сколько колонок у переключателей: на «Режимах» их много — в две."""
        page = self.pages[self.page]
        return 2 if len(page.toggles) > 6 else 1

    def toggle_rows(self, size: Tuple[int, int] = (960, 540)) -> List[Tuple[Toggle, Tuple[int, int, int, int]]]:
        """Строки-переключатели текущей страницы: (переключатель, прямоугольник)."""
        page = self.pages[self.page]
        if not page.toggles:
            return []
        w, h = size
        k = max(min(h / 540.0, w / 960.0), 0.5)
        columns = self.toggles_in_columns()
        gap = int(16 * k)
        total = int(w - 2 * self.MARGIN * k)
        width = int((total - gap * (columns - 1)) / columns) if columns > 1 else total
        # высота строки одна и та же в любой раскладке: под названием идёт
        # подсказка, и в одну колонку она налезала на следующий переключатель
        row_h = int((self.ROW_H + 8) * k)
        out = []
        for i, toggle in enumerate(page.toggles):
            row, col = divmod(i, columns)
            x = int(self.MARGIN * k) + col * (width + gap)
            y = int(self.FIRST_Y * k) + row * row_h
            out.append((toggle, (x, y, width, row_h)))
        return out

    def preset_buttons(self, size: Tuple[int, int] = (960, 540)) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """Кнопки готовых режимов (только на странице «Режимы»)."""
        if not self.pages[self.page].presets:
            return []
        w, h = size
        k = max(min(h / 540.0, w / 960.0), 0.5)
        rows = self.toggle_rows(size)
        y = (rows[-1][1][1] + rows[-1][1][3] + int(14 * k)) if rows else int(self.FIRST_Y * k)
        height = int(32 * k)
        widths = [int(120 * k), int(150 * k), int(140 * k), int(150 * k)]
        gap = int(12 * k)
        x = int((w - (sum(widths) + gap * (len(widths) - 1))) / 2)
        out = []
        for name, width in zip(PRESETS, widths):
            out.append((name, (x, y, width, height)))
            x += width + gap
        return out

    def side_buttons(self, size: Tuple[int, int] = (960, 540)) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """Кнопки калибровки стороны кисти (только на странице «Режимы»)."""
        if not self.pages[self.page].presets:
            return []
        w, h = size
        k = max(min(h / 540.0, w / 960.0), 0.5)
        presets = self.preset_buttons(size)
        y = (presets[0][1][1] + presets[0][1][3] + int(10 * k)) if presets else int(self.FIRST_Y * k)
        names = ("КАЛИБРОВАТЬ ЛАДОНЬ (K)", "ИНВЕРТИРОВАТЬ",
                 f"ТЫЛОМ: {'ВКЛ' if self.cfg.hand.side_actions else 'ВЫКЛ'}")
        widths = (int(200 * k), int(150 * k), int(170 * k))
        gap = int(12 * k)
        x = int((w - (sum(widths) + gap * (len(widths) - 1))) / 2)
        out = []
        for name, width in zip(names, widths):
            out.append((name, (x, y, width, int(28 * k))))
            x += width + gap
        return out

    def gaze_buttons(self, size: Tuple[int, int] = (960, 540)) -> List[Tuple[str, Tuple[int, int, int, int]]]:
        """Кнопки калибровки взгляда (только на странице «Моргание и глаза»)."""
        if self.page != PAGE_EYES:
            return []
        w, h = size
        k = max(min(h / 540.0, w / 960.0), 0.5)
        rows = self.layout(size)
        if rows:
            last = rows[-1]
            y = last.rect[1] + last.rect[3] + int(10 * k)
        else:
            y = int(self.FIRST_Y * k)
        names = ("КАЛИБРОВАТЬ ВЗГЛЯД (B)", "СБРОСИТЬ КАЛИБРОВКУ")
        widths = (int(220 * k), int(190 * k))
        gap = int(12 * k)
        x = int((w - (sum(widths) + gap * (len(widths) - 1))) / 2)
        out = []
        for name, width in zip(names, widths):
            out.append((name, (x, y, width, int(28 * k))))
            x += width + gap
        return out

    def side_state(self) -> str:
        """Что сейчас видно: «ладонь», «тыл» или «не определена»."""
        hook = self.hooks.get("side")
        if callable(hook):
            return str(hook())
        return "не определена"

    def layout(self, size: Tuple[int, int] = (960, 540)) -> List[Row]:
        """Положение строк текущей страницы (в пикселях кадра)."""
        w, h = size
        k = max(min(h / 540.0, w / 960.0), 0.5)
        rows: List[Row] = []
        y = int(self.FIRST_Y * k)
        # если на странице есть переключатели, ползунки начинаются под ними
        toggle_rows = self.toggle_rows(size)
        if toggle_rows:
            y = max(rect[1] + rect[3] for _t, rect in toggle_rows) + int(10 * k)
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
            for name, (bx, by, bw, bh) in self.preset_buttons(size):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    apply_preset(self.cfg, self.runtime, name)
                    self.dirty = True
                    self.status = f"режим: {name} — {self.modes_text()}"
                    return "reset"
            for name, (bx, by, bw, bh) in self.gaze_buttons(size):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if name.startswith("КАЛИБРОВАТЬ"):
                        hook = self.hooks.get("gaze_calibrate")
                        text = hook() if callable(hook) else ""
                        self.close(save=True)
                        return "save"
                    hook = self.hooks.get("gaze_reset")
                    text = hook() if callable(hook) else ""
                    self.dirty = True
                    self.status = str(text)
                    return "change"
            for name, (bx, by, bw, bh) in self.side_buttons(size):
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if name.startswith("КАЛИБРОВАТЬ"):
                        hook = self.hooks.get("calibrate")
                        ok = bool(hook()) if callable(hook) else False
                        self.dirty = True
                        self.status = ("ладонь запомнена" if ok
                                       else "покажите ладонь в камеру и нажмите ещё раз")
                        return "change"
                    if name.startswith("ИНВЕРТИРОВАТЬ"):
                        hook = self.hooks.get("flip")
                        if callable(hook):
                            hook()
                        self.dirty = True
                        self.status = f"сторона: {self.side_state()}"
                        return "change"
                    self.cfg.hand.side_actions = not self.cfg.hand.side_actions
                    self.dirty = True
                    self.status = ("команды тылом включены" if self.cfg.hand.side_actions
                                   else "команды тылом выключены")
                    return "reset"
            for toggle, (tx, ty, tw, th) in self.toggle_rows(size):
                if tx <= x <= tx + tw and ty <= y <= ty + th:
                    on = toggle.flip(self.cfg, self.runtime)
                    self.dirty = True
                    self.status = f"{toggle.label}: {'ВКЛ' if on else 'ВЫКЛ'}"
                    return "reset"
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

    def modes_text(self) -> str:
        """Строка вида «рука + лицо» — что сейчас работает."""
        return modes_summary(self.cfg, self.runtime)

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
        # раскладка не важна: клавиша понимается по физической позиции
        if keys.matches(key, "esc") or keys.matches(key, "c"):
            self.close(save=self.dirty)
            return "close" if not self.saved else "save"
        if keys.matches(key, "s"):
            self.close(save=True)
            return "save"
        if keys.matches(key, "r"):
            self.reset()
            return "reset"
        if keys.matches(key, "tab") or keys.matches(key, "space"):
            self.next_page()
            return "page"
        pressed = keys.to_latin(key)
        if len(pressed) == 1 and "1" <= pressed <= "9":
            self.goto_page(ord(pressed) - ord("1"))
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
        T.draw(img, "Мышь на паузе, пока панель открыта · режимы можно сочетать",
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

        # строки-переключатели (страница «Режимы»)
        columns = self.toggles_in_columns()
        label_size = int((14 if columns > 1 else 15) * k)
        hint_size = int((10 if columns > 1 else 11) * k)
        for toggle, (tx, ty, tw, th) in self.toggle_rows((w, h)):
            on = toggle.state(self.cfg, self.runtime)
            T.draw(img, toggle.label, (tx, ty + int(4 * k)), label_size, _FG)
            pill_w, pill_h = int((64 if columns > 1 else 74) * k), int(24 * k)
            px = tx + tw - pill_w
            py = ty + int(4 * k)
            cv2.rectangle(img, (px, py), (px + pill_w, py + pill_h),
                          _ACCENT if on else _TRACK, -1)
            word = "ВКЛ" if on else "ВЫКЛ"
            ww, wh = T.measure(word, int(13 * k))
            T.draw(img, word, (px + (pill_w - ww) // 2, py + (pill_h - wh) // 2),
                   int(13 * k), _BG if on else _FG)
            # подсказка не должна залезать под соседнюю колонку
            hint = toggle.hint
            room = tw - pill_w - int(8 * k)
            while hint and T.measure(hint, hint_size)[0] > room:
                hint = hint[:-1]
            T.draw(img, hint, (tx, ty + int(26 * k)), hint_size, _DIM)

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

        # готовые наборы режимов
        for name, (bx, by, bw, bh) in self.preset_buttons((w, h)):
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), _PANEL, -1)
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), _WARN, 1, cv2.LINE_AA)
            tw, th_ = T.measure(name, int(12 * k))
            T.draw(img, name, (bx + (bw - tw) // 2, by + (bh - th_) // 2), int(12 * k), _WARN)

        # калибровка стороны кисти
        for name, (bx, by, bw, bh) in self.side_buttons((w, h)):
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), _PANEL, -1)
            color = _ACCENT if name.startswith("КАЛИБРОВАТЬ") else _DIM
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), color, 1, cv2.LINE_AA)
            tw, th_ = T.measure(name, int(11 * k))
            T.draw(img, name, (bx + (bw - tw) // 2, by + (bh - th_) // 2), int(11 * k), color)

        # кнопки калибровки взгляда
        for name, (bx, by, bw, bh) in self.gaze_buttons((w, h)):
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), _PANEL, -1)
            color = _ACCENT if name.startswith("КАЛИБРОВАТЬ") else _WARN
            cv2.rectangle(img, (bx, by), (bx + bw, by + bh), color, 1, cv2.LINE_AA)
            tw, th_ = T.measure(name, int(12 * k))
            T.draw(img, name, (bx + (bw - tw) // 2, by + (bh - th_) // 2), int(12 * k), color)

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
        left_x = int(self.MARGIN * k) + int(150 * k)
        right_edge = w - int(self.MARGIN * k)
        if self.pages[self.page].presets:
            live = f"сейчас: {self.modes_text()} · сторона: {self.side_state()}"
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
