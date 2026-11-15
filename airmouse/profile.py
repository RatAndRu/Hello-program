"""Профиль движений: «калибровка диапазона» для рук, мимики и тела.

Для глаз калибровка нужна, потому что «палец зрачка» ничего не говорит о том,
куда смотрит человек: соответствие приходится измерять. С руками, лицом и телом
иначе — модель отдаёт нормализованные landmarks, и все наши признаки уже меряются
в долях ладони или лица (``pinch``, ``smile_score``, глубина приседа). Координаты
калибровать не надо.

А вот **диапазон** у всех свой: один человек сводит пальцы до 0.10 ладони,
другой до 0.28; один улыбается на 0.09, другой на 0.04; присед у всех разный.
Поэтому здесь измеряется личный диапазон, а общие пороги (`pinch_ratio`,
`smile_delta`, …) заменяются на «середину вашего хода» — как слайдер
*Gesture size* в Camera Switches у Google, только выставленный автоматически.

Мастер короткий и без чтения во время движения: сначала экран с инструкцией,
потом по одной фразе на шаг («разожмите и сожмите», «улыбнитесь»), и каждый шаг
измеряется сам.
"""

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .filters import clamp


@dataclass(frozen=True)
class ProfileStep:
    """Один шаг замера."""

    key: str
    title: str        # что просим сделать
    hint: str         # как понять, что сделано
    seconds: float    # сколько измеряем


STEPS: Tuple[ProfileStep, ...] = (
    ProfileStep("pinch", "РАЗОЖМИТЕ И СОЖМИТЕ ПАЛЬЦЫ",
                "три-четыре раза: большой к указательному и обратно", 8.0),
    ProfileStep("smile", "УЛЫБНИТЕСЬ", "как можно шире — и держите", 5.0),
    ProfileStep("brow", "ПОДНИМИТЕ БРОВИ", "как можно выше — и держите", 5.0),
    ProfileStep("mouth", "ОТКРОЙТЕ РОТ", "как можно шире — и держите", 4.0),
    ProfileStep("squat", "ПРИСЯДЬТЕ", "один-два раза, неглубоко и медленно", 7.0),
)

STEP_TITLES = {step.key: step.title for step in STEPS}


def _quantile(values: Sequence[float], q: float, default: float = 0.0) -> float:
    """Квантиль без numpy-зависимостей в вызывающем коде (numpy есть и так)."""
    data = sorted(float(v) for v in values if v == v)
    if not data:
        return default
    if len(data) == 1:
        return data[0]
    pos = clamp(q, 0.0, 1.0) * (len(data) - 1)
    low, high = int(pos), min(int(pos) + 1, len(data) - 1)
    weight = pos - low
    return data[low] * (1.0 - weight) + data[high] * weight


@dataclass
class MotionProfile:
    """Личный диапазон движений. Всё — в тех же единицах, что и признаки."""

    pinch_open: float = 0.0      # насколько разжимаете (доли ладони)
    pinch_closed: float = 0.0    # насколько сводите
    smile: float = 0.0           # максимальный прирост ширины улыбки
    brow: float = 0.0            # максимальный подъём бровей
    mouth: float = 0.0           # максимальная раскрытость рта (0..1)
    squat: float = 0.0           # максимальная глубина приседа (0..1)
    frames: int = 0              # сколько кадров всего снято
    missing: List[str] = field(default_factory=list)   # чего не дождались

    # ------------------------------------------------------------------ #
    @property
    def pinch_range(self) -> float:
        return max(0.0, self.pinch_open - self.pinch_closed)

    def suggest(self) -> Dict[str, float]:
        """Пороги под этого человека (и «середина хода», и запас на бытовое).

        Логика одна и та же во всех строках: порог ставится **ближе к его
        собственному максимуму**, но не выше половины хода. Так жест, который
        человек делает «в полную силу», срабатывает, а половинный — нет.
        """
        out: Dict[str, float] = {}
        if self.pinch_range > 0.02:
            out["pinch_ratio"] = round(clamp(self.pinch_closed + 0.45 * self.pinch_range,
                                             0.18, 0.55), 3)
        if self.smile > 0.005:
            out["smile_delta"] = round(clamp(0.55 * self.smile, 0.030, 0.120), 4)
        if self.brow > 0.005:
            out["brow_delta"] = round(clamp(0.55 * self.brow, 0.025, 0.100), 4)
        if self.mouth > 0.02:
            out["mouth_open_ratio"] = round(clamp(0.70 * self.mouth, 0.35, 0.80), 3)
        if self.squat > 0.02:
            out["squat_down"] = round(clamp(0.75 * self.squat, 0.28, 0.80), 3)
            out["squat_up"] = round(clamp(0.35 * out["squat_down"], 0.10, 0.40), 3)
        return out

    def text(self) -> str:
        """Короткая сводка для журнала: что намерили."""
        parts = []
        if self.pinch_range > 0.02:
            parts.append(f"щипок {self.pinch_closed:.2f}…{self.pinch_open:.2f} ладони")
        if self.smile > 0.005:
            parts.append(f"улыбка до {self.smile:.3f}")
        if self.brow > 0.005:
            parts.append(f"брови до {self.brow:.3f}")
        if self.mouth > 0.02:
            parts.append(f"рот до {self.mouth:.2f}")
        if self.squat > 0.02:
            parts.append(f"присед до {self.squat:.2f}")
        if not parts:
            return "профиль движений: ничего не намерено"
        return "профиль движений: " + ", ".join(parts)

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["missing"] = list(self.missing)
        return data

    @staticmethod
    def from_dict(data: Optional[Dict[str, object]]) -> "MotionProfile":
        prof = MotionProfile()
        if not data:
            return prof
        for name in ("pinch_open", "pinch_closed", "smile", "brow", "mouth", "squat"):
            try:
                setattr(prof, name, float(data.get(name) or 0.0))
            except (TypeError, ValueError):
                pass
        prof.frames = int(data.get("frames") or 0)
        prof.missing = [str(v) for v in (data.get("missing") or [])]
        return prof


class MotionWizard:
    """Мастер «профиля движений»: шаги по времени, замер по каждому признаку.

    Мастер ничего не знает про камеру: ему на каждом кадре передают текущие
    признаки (``pinch``, ``smile``, ``brow``, ``mouth``, ``squat``), а он решает,
    что с ними делать. Поэтому его можно проверять тестами без OpenCV.
    """

    def __init__(self, steps: Sequence[ProfileStep] = STEPS, speed: float = 1.0):
        self.steps = tuple(steps)
        self.speed = max(0.2, float(speed))
        self.index = 0
        self.elapsed = 0.0
        self.done = False
        self.frames = 0
        self._values: Dict[str, List[float]] = {step.key: [] for step in self.steps}
        self._squat_ready = False     # присед меряем только если тело видно

    # ------------------------------------------------------------------ #
    @property
    def step(self) -> ProfileStep:
        return self.steps[min(self.index, len(self.steps) - 1)]

    @property
    def phase(self) -> str:
        return "done" if self.done else self.step.key

    @property
    def progress(self) -> float:
        if self.done:
            return 1.0
        return min(1.0, self.index / max(len(self.steps), 1))

    @property
    def step_progress(self) -> float:
        if self.done:
            return 1.0
        return min(1.0, self.elapsed / max(self.step.seconds / self.speed, 1e-6))

    @property
    def left_s(self) -> float:
        if self.done:
            return 0.0
        return max(0.0, self.step.seconds / self.speed - self.elapsed)

    @property
    def title(self) -> str:
        """Короткая строка для окна: шаг и что делать."""
        if self.done:
            return "ПРОФИЛЬ ДВИЖЕНИЙ: готово"
        return f"ПРОФИЛЬ ДВИЖЕНИЙ {self.index + 1}/{len(self.steps)} · {self.step.title}"

    @property
    def hint(self) -> str:
        if self.done:
            return ""
        return f"{self.step.hint}   ({self.left_s:.0f} с, ПРОБЕЛ — пропустить, Esc — отмена)"

    def text(self) -> str:
        if self.done:
            return "профиль движений: готово"
        return f"{self.title}: {self.hint}"

    # ------------------------------------------------------------------ #
    def update(self, dt: float, *, pinch: Optional[float] = None,
               smile: Optional[float] = None, brow: Optional[float] = None,
               mouth: Optional[float] = None,
               squat: Optional[float] = None) -> bool:
        """Один кадр. Возвращает ``True``, когда мастер закончил."""
        if self.done:
            return True
        values = {"pinch": pinch, "smile": smile, "brow": brow,
                  "mouth": mouth, "squat": squat}
        current = self.step.key
        value = values.get(current)
        if value is not None and value == value:
            bucket = self._values[current]
            bucket.append(float(value))
            if len(bucket) > 1200:
                del bucket[:-1200]
            if current == "squat" and float(value) > 0.10:
                self._squat_ready = True
            self.frames += 1
        self.elapsed += max(0.0, float(dt))
        if self.elapsed >= self.step.seconds / self.speed:
            return self.next_step()
        return False

    def next_step(self) -> bool:
        """Пропустить текущий шаг (ПРОБЕЛ) или перейти к следующему по времени."""
        if self.done:
            return True
        self.index += 1
        self.elapsed = 0.0
        if self.index >= len(self.steps):
            # шаг «присед» пропускаем, если тела в кадре не было совсем
            self.done = True
        return self.done

    def skip(self) -> bool:
        """Пропустить шаг: данные неполные, но мастер идёт дальше."""
        return self.next_step()

    # ------------------------------------------------------------------ #
    def finish(self) -> MotionProfile:
        """Свести замеры в профиль (устойчиво: по квантилям, а не по одному кадру)."""
        prof = MotionProfile(frames=self.frames)
        pinch = self._values.get("pinch") or []
        if len(pinch) >= 10 and max(pinch) - min(pinch) > 0.02:
            prof.pinch_open = round(_quantile(pinch, 0.90), 4)
            prof.pinch_closed = round(_quantile(pinch, 0.10), 4)
        else:
            prof.missing.append("pinch")
        for name, attr in (("smile", "smile"), ("brow", "brow"), ("mouth", "mouth")):
            values = self._values.get(name) or []
            if len(values) >= 5 and max(values) > 0.005:
                setattr(prof, attr, round(_quantile(values, 0.90), 4))
            else:
                prof.missing.append(name)
        squat = self._values.get("squat") or []
        # присед считаем только если он вообще был: 0.10 — «заметное движение»
        if self._squat_ready and len(squat) >= 5:
            prof.squat = round(_quantile(squat, 0.95), 4)
        else:
            prof.missing.append("squat")
        return prof
