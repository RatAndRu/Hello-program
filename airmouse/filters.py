"""Фильтры и маленькие автоматы состояний.

Ничего специфичного для зрения: сглаживание координат, гистерезис,
защёлки, антидребезг. Всё покрыто тестами.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional


def alpha_from_cutoff(cutoff_hz: float, dt: float) -> float:
    """Коэффициент сглаживания экспоненциального фильтра низких частот."""
    if cutoff_hz <= 0:
        return 1.0
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / max(dt, 1e-6))


class OneEuroFilter:
    """Фильтр 1€ (Casiez et al., 2012): минимум дрожания при резких движениях.

    Работает и со скалярами, и с numpy-массивами любой формы.
    """

    def __init__(
        self,
        min_cutoff: float = 1.0,
        beta: float = 0.007,
        d_cutoff: float = 1.0,
    ) -> None:
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x = None
        self._dx = None
        self._t: Optional[float] = None

    def reset(self) -> None:
        self._x = None
        self._dx = None
        self._t = None

    def filter(self, value, t: float):
        if self._t is None:
            self._t = t
            self._x = value if hasattr(value, "copy") else float(value)
            self._dx = 0.0 * self._x if hasattr(self._x, "copy") else 0.0
            return value
        dt = max(t - self._t, 1e-4)
        self._t = t
        raw_dx = (value - self._x) / dt
        a_d = alpha_from_cutoff(self.d_cutoff, dt)
        self._dx = a_d * raw_dx + (1.0 - a_d) * self._dx
        speed = abs(self._dx)
        if hasattr(speed, "__len__"):
            speed = float(sum(abs(v) for v in speed) / len(speed))
        cutoff = self.min_cutoff + self.beta * float(speed)
        a = alpha_from_cutoff(cutoff, dt)
        self._x = a * value + (1.0 - a) * self._x
        return self._x

    __call__ = filter


class EMA:
    """Простое экспоненциальное сглаживание с фиксированным весом."""

    def __init__(self, alpha: float = 0.3) -> None:
        self.alpha = float(alpha)
        self.value: Optional[float] = None

    def reset(self) -> None:
        self.value = None

    def update(self, value: float) -> float:
        if self.value is None:
            self.value = float(value)
        else:
            self.value = self.alpha * float(value) + (1.0 - self.alpha) * self.value
        return self.value


class HysteresisGate:
    """Порог с двумя границами: включаетcя по ``on``, выключается по ``off``."""

    def __init__(self, on: float, off: float, inverted: bool = False) -> None:
        self.on = float(on)
        self.off = float(off)
        self.inverted = inverted
        self.active = False

    def update(self, value: float) -> bool:
        if self.inverted:  # срабатывает при значении НИЖЕ порога (например, EAR)
            if self.active:
                self.active = value < self.off
            else:
                self.active = value < self.on
        else:
            if self.active:
                self.active = value > self.off
            else:
                self.active = value > self.on
        return self.active

    def reset(self) -> None:
        self.active = False


class HoldTimer:
    """Сколько секунд подряд условие было истинным."""

    def __init__(self, hold_s: float) -> None:
        self.hold_s = float(hold_s)
        self._since: Optional[float] = None
        self._fired = False

    def reset(self) -> None:
        self._since = None
        self._fired = False

    def update(self, condition: bool, now: float) -> bool:
        """True ровно один раз, когда условие продержалось ``hold_s``."""
        if not condition:
            self.reset()
            return False
        if self._since is None:
            self._since = now
        if not self._fired and now - self._since >= self.hold_s:
            self._fired = True
            return True
        return False


class Cooldown:
    """Не чаще одного события за ``period`` секунд (на каждую «кнопку»)."""

    def __init__(self, period: float) -> None:
        self.period = float(period)
        self._last: Dict[str, float] = {}

    def ready(self, key: str, now: float) -> bool:
        last = self._last.get(key)
        return last is None or (now - last) >= self.period

    def mark(self, key: str, now: float) -> None:
        self._last[key] = now

    def try_fire(self, key: str, now: float) -> bool:
        if self.ready(key, now):
            self.mark(key, now)
            return True
        return False

    def remaining(self, key: str, now: float) -> float:
        last = self._last.get(key)
        if last is None:
            return 0.0
        return max(0.0, self.period - (now - last))

    def reset(self) -> None:
        self._last.clear()


@dataclass
class StabilityGate:
    """Требует, чтобы метка держалась N обновлений подряд."""

    frames: int = 3
    current: Optional[str] = None
    stable: Optional[str] = None
    _count: int = field(default=0, init=False)

    def update(self, label: Optional[str]) -> Optional[str]:
        if label != self.current:
            self.current = label
            self._count = 0
            self.stable = None
        self._count += 1
        if self.current is not None and self._count >= self.frames:
            self.stable = self.current
        return self.stable

    def reset(self) -> None:
        self.current = None
        self.stable = None
        self._count = 0


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def deadzone(value: float, dz: float) -> float:
    """Убирает микро-движения, плавно возвращая остаток."""
    if abs(value) <= dz:
        return 0.0
    return math.copysign(abs(value) - dz, value)
