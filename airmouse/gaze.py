"""Калибровка взгляда: «куда смотрю» → «куда поставить курсор».

Скоростной режим («зрачок отведён — курсор едет») требует косить глазами и
быстро утомляет. Абсолютный режим куда приятнее: человек смотрит в нужную часть
экрана, и курсор оказывается там. Для этого нужна одна калибровка: попросить
посмотреть в несколько точек экрана, запомнить положение зрачка в каждой и
подобрать преобразование «зрачок → экран».

Здесь только математика: точки, подгонка (наименьшие квадраты) и применение.
Ни камеры, ни окна — поэтому всё проверяется тестами без железа.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Dict, List, Sequence, Tuple

import numpy as np

# Куда просим посмотреть: сетка 3×3 по всему экрану. Четыре самых угла, четыре
# середины сторон и центр. Именно 0 и 1, а не «около угла»: калибровка идёт на
# весь монитор, а не на окно предпросмотра, иначе курсор не достаёт до краёв.
# Девяти точек хватает, чтобы подобрать **проективное** преобразование
# (гомографию), а не только аффинное: камера снизу или сбоку искажает картинку
# неравномерно, и в промежуточных полосах аффинное давало заметный промах.
CALIBRATION_TARGETS: Tuple[Tuple[float, float], ...] = (
    (0.0, 0.0),        # 1  левый верх
    (1.0, 0.0),        # 2  правый верх
    (1.0, 1.0),        # 3  правый низ
    (0.0, 1.0),        # 4  левый низ
    (0.5, 0.0),        # 5  верх, середина
    (1.0, 0.5),        # 6  право, середина
    (0.5, 1.0),        # 7  низ, середина
    (0.0, 0.5),        # 8  лево, середина
    (0.5, 0.5),        # 9  центр — проверка
)

TARGET_TITLES = (
    "левый верхний угол",
    "правый верхний угол",
    "правый нижний угол",
    "левый нижний угол",
    "середина верхнего края",
    "середина правого края",
    "середина нижнего края",
    "середина левого края",
    "центр экрана",
)

# Сколько точек нужно, чтобы преобразование считалось надёжным (9 — сетка).
TARGETS_TOTAL = len(CALIBRATION_TARGETS)


@dataclass
class GazeCalibration:
    """Преобразование «положение зрачка → точка экрана» (0..1).

    Подбирается проективное преобразование (гомография 3×3): оно честно
    описывает перспективу, поэтому одинаково хорошо работает и в углах, и в
    серединах сторон. Старые калибровки (аффинные коэффициенты) читаются и
    работают, но помечаются как устаревшие — их лучше пройти заново.
    """

    points: List[Tuple[float, float, float, float]] = field(default_factory=list)
    H: List[float] = field(default_factory=list)      # 9 чисел, по строкам
    feature: str = ""                                 # как считался признак
    stale: bool = False                               # старая (аффинная) калибровка
    head_gain: List[float] = field(default_factory=lambda: [0.0, 0.0])

    # ------------------------------------------------------------------ #
    @property
    def ready(self) -> bool:
        return len(self.H) == 9 and len(self.points) >= 3

    @property
    def matrix(self) -> np.ndarray:
        return np.asarray(self.H, dtype=np.float64).reshape(3, 3) if self.H else np.eye(3)

    def add(self, gaze_x: float, gaze_y: float, screen_x: float, screen_y: float) -> None:
        self.points.append((float(gaze_x), float(gaze_y), float(screen_x), float(screen_y)))

    # ------------------------------------------------------------------ #
    def fit(self) -> bool:
        """Подобрать гомографию по накопленным точкам (DLT, наименьшие квадраты)."""
        if len(self.points) < 3:
            return False
        data = np.asarray(self.points, dtype=np.float64)
        src = data[:, :2]
        dst = data[:, 2:]
        # четыре точки — минимум для гомографии, меньше — только аффинно
        H = _homography(src, dst) if len(self.points) >= 4 else None
        if H is not None:
            self.H = [float(v) for v in H.reshape(9)]
            self.stale = False
            return True
        # Точки легли на линию (или глаз двигался только по одной оси) —
        # вырожденный случай: подгоняем аффинно, лишь бы не остаться без мышки.
        H = _affine_fallback(data)
        if H is None:
            return False
        self.H = [float(v) for v in H.reshape(9)]
        self.stale = False
        return True

    # ------------------------------------------------------------------ #
    #  Поворот головы: «смотрю в ту же точку — курсор там же»
    # ------------------------------------------------------------------ #
    def head_correct(self, gaze_x: float, gaze_y: float,
                     yaw: float = 0.0, pitch: float = 0.0) -> Tuple[float, float]:
        """Убирает сдвиг зрачка, вызванный поворотом головы.

        Когда человек поворачивает голову, но продолжает смотреть в ту же точку,
        измеренное положение зрачка всё равно уезжает: веко и уголки глаз лежат
        на разной глубине, глазница в кадре сжимается. Сдвиг почти
        пропорционален ``tan(угла)`` — коэффициент как раз и снимается на
        калибровке (человек вертит головой, не отводя взгляда), а здесь
        вычитается из признака.
        """
        if not self.head_gain or (self.head_gain[0] == 0.0 and self.head_gain[1] == 0.0):
            return float(gaze_x), float(gaze_y)
        ty = math.tan(math.radians(max(-60.0, min(60.0, float(yaw)))))
        tp = math.tan(math.radians(max(-60.0, min(60.0, float(pitch)))))
        return (float(gaze_x) - self.head_gain[0] * ty,
                float(gaze_y) - self.head_gain[1] * tp)

    def fit_head(self, samples: Sequence[Sequence[float]]) -> bool:
        """Подобрать коэффициенты компенсации по кадрам «верчу головой».

        ``samples`` — четвёрки ``(gaze_x, gaze_y, yaw, pitch)``, снятые, пока
        человек смотрел в одну точку и поворачивал голову. Возвращаем наклон:
        насколько зрачок уезжает на единицу ``tan`` угла поворота.
        """
        rows = [tuple(float(v) for v in s) for s in samples if len(s) >= 4]
        if len(rows) < 8 or not self.ready:
            self.head_gain = [0.0, 0.0]
            return False
        data = np.asarray(rows, dtype=np.float64)
        gx, gy = data[:, 0], data[:, 1]
        ty = np.tan(np.radians(np.clip(data[:, 2], -60.0, 60.0)))
        tp = np.tan(np.radians(np.clip(data[:, 3], -60.0, 60.0)))
        # без заметных поворотов компенсировать нечего
        if float(np.ptp(data[:, 2])) < 6.0 and float(np.ptp(data[:, 3])) < 6.0:
            self.head_gain = [0.0, 0.0]
            return False
        base_x = float(np.median(gx))
        base_y = float(np.median(gy))
        # коэффициент считаем прямо по «сколько зрачок уехал на градус поворота»:
        # регрессия без свободного члена — сдвиг нуля уже учтён медианой
        norm_x = float((ty ** 2).sum())
        norm_y = float((tp ** 2).sum())
        a = float((ty * (gx - base_x)).sum() / norm_x) if norm_x > 1e-9 else 0.0
        b = float((tp * (gy - base_y)).sum() / norm_y) if norm_y > 1e-9 else 0.0
        # правдоподобные пределы: сдвиг не больше 1.2 «единицы зрачка» на tan=1
        a = float(max(-1.2, min(1.2, a)))
        b = float(max(-1.2, min(1.2, b)))
        self.head_gain = [a, b]
        return True

    def head_gain_text(self) -> str:
        a, b = (self.head_gain + [0.0, 0.0])[:2]
        if a == 0.0 and b == 0.0:
            return "поворот головы: без компенсации"
        return f"поворот головы: поправка {a:+.2f}/{b:+.2f}"

    def apply(self, gaze_x: float, gaze_y: float) -> Tuple[float, float]:
        """Куда поставить курсор: нормированные координаты экрана 0..1."""
        if not self.ready:
            return 0.5, 0.5
        H = self.matrix
        x, y = float(gaze_x), float(gaze_y)
        w = H[2, 0] * x + H[2, 1] * y + H[2, 2]
        if abs(w) < 1e-6:                 # ушли за бесконечность — держим центр
            return 0.5, 0.5
        sx = (H[0, 0] * x + H[0, 1] * y + H[0, 2]) / w
        sy = (H[1, 0] * x + H[1, 1] * y + H[1, 2]) / w
        return float(min(1.0, max(0.0, sx))), float(min(1.0, max(0.0, sy)))

    # ------------------------------------------------------------------ #
    def error(self) -> Tuple[float, float]:
        """Насколько калибровка «промахивается» на своих же точках.

        Возвращает ``(максимум, среднее)`` в долях экрана. Это честная проверка
        «адекватности»: если после девяти точек ошибка больше нескольких
        процентов, значит человек смотрел мимо точки, зрачок перекрывало веко
        (типично для камеры снизу) или точки упёрлись в предел ±1.
        """
        if not self.points or not self.ready:
            return (1.0, 1.0)
        worst, total = 0.0, 0.0
        for gx, gy, sx, sy in self.points:
            px, py = self.apply(gx, gy)
            dx, dy = abs(px - sx), abs(py - sy)
            worst = max(worst, dx, dy)
            total += (dx + dy) / 2.0
        return (float(worst), float(total / len(self.points)))

    def quality_text(self) -> str:
        """Короткая строка для журнала: «ошибка 1.4% экрана (9 точек)»."""
        worst, mean = self.error()
        if not self.ready:
            return "калибровки нет"
        text = (f"ошибка {mean * 100:.1f}% экрана "
                f"(макс {worst * 100:.1f}%, точек {len(self.points)})")
        if self.stale:
            text += " — калибровка старого образца, нажмите B"
        return text

    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, object]:
        return {"points": [[round(v, 5) for v in p] for p in self.points],
                "H": [round(v, 6) for v in self.H],
                "feature": self.feature or "head",
                "head_gain": [round(v, 4) for v in self.head_gain]}

    @classmethod
    def from_dict(cls, data: Dict[str, object] | None) -> "GazeCalibration":
        calib = cls()
        if not data:
            return calib
        try:
            points = data.get("points") or []
            calib.points = [tuple(float(v) for v in p) for p in points if len(p) == 4]
            calib.feature = str(data.get("feature") or "")
            gain = data.get("head_gain") or []
            if len(gain) == 2:
                calib.head_gain = [float(gain[0]), float(gain[1])]
            raw_h = data.get("H") or []
            if len(raw_h) == 9:
                calib.H = [float(v) for v in raw_h]
                calib.stale = calib.feature not in ("head",)
                return calib
            # старый формат: аффинные коэффициенты по осям
            coef_x = [float(v) for v in (data.get("coef_x") or [])]
            coef_y = [float(v) for v in (data.get("coef_y") or [])]
            if len(coef_x) == 3 and len(coef_y) == 3:
                calib.H = [float(v) for v in np.array([
                    [coef_x[0], coef_x[1], coef_x[2]],
                    [coef_y[0], coef_y[1], coef_y[2]],
                    [0.0, 0.0, 1.0],
                ]).reshape(9)]
                calib.stale = True
                return calib
        except (TypeError, ValueError):
            return cls()
        if not calib.ready and calib.points:
            calib.fit()
        return calib

    def describe(self) -> str:
        if not self.ready:
            return "не калибровано"
        return f"калибровка взгляда: {len(self.points)} точек"


# --------------------------------------------------------------------------- #
#  Подгонка гомографии
# --------------------------------------------------------------------------- #
def _normalize(points: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Приведение координат к нулевому центру и среднему радиусу √2.

    Без этого матрица из уравнений плохо обусловлена, и гомография «взрывается»
    на числах порядка 0.02.
    """
    centre = points.mean(axis=0)
    shifted = points - centre
    dist = np.sqrt((shifted ** 2).sum(axis=1)).mean()
    scale = math.sqrt(2.0) / dist if dist > 1e-12 else 1.0
    T = np.array([[scale, 0.0, -scale * centre[0]],
                  [0.0, scale, -scale * centre[1]],
                  [0.0, 0.0, 1.0]])
    return shifted * scale, T


def _homography(src: np.ndarray, dst: np.ndarray) -> "np.ndarray | None":
    """Проективное преобразование src → dst по методу DLT (наименьшие квадраты)."""
    if src.shape[0] < 4:
        return None
    s_norm, T_src = _normalize(np.asarray(src, dtype=np.float64))
    d_norm, T_dst = _normalize(np.asarray(dst, dtype=np.float64))
    rows = []
    for (x, y), (u, v) in zip(s_norm, d_norm):
        rows.append([-x, -y, -1.0, 0.0, 0.0, 0.0, u * x, u * y, u])
        rows.append([0.0, 0.0, 0.0, -x, -y, -1.0, v * x, v * y, v])
    A = np.asarray(rows, dtype=np.float64)
    if not np.all(np.isfinite(A)):
        return None
    try:
        _u, _s, vt = np.linalg.svd(A, full_matrices=False)
    except np.linalg.LinAlgError:
        return None
    h = vt[-1]
    H_norm = h.reshape(3, 3)
    if not np.all(np.isfinite(H_norm)):
        return None
    # возвращаемся из нормализованных координат в исходные
    H = np.linalg.inv(T_dst) @ H_norm @ T_src
    if abs(H[2, 2]) > 1e-12:
        H = H / H[2, 2]
    if not np.all(np.isfinite(H)):
        return None
    return H


def _affine_fallback(data: np.ndarray) -> "np.ndarray | None":
    """Вырожденный случай: по осям, но без перспективы."""
    gx, gy = data[:, 0], data[:, 1]
    spread_x = float(gx.max() - gx.min())
    spread_y = float(gy.max() - gy.min())
    if spread_x < 1e-4 and spread_y < 1e-4:
        return None
    if spread_x > 1e-4 and spread_y > 1e-4:
        matrix = np.stack([gx, gy, np.ones_like(gx)], axis=1)
        cx, *_ = np.linalg.lstsq(matrix, data[:, 2], rcond=None)
        cy, *_ = np.linalg.lstsq(matrix, data[:, 3], rcond=None)
    else:
        def one_axis(values: np.ndarray, target: np.ndarray) -> List[float]:
            if float(np.ptp(values)) < 1e-6:
                return [0.0, 0.0, float(target.mean())]
            k, b = np.polyfit(values, target, 1)
            return [float(k), 0.0, float(b)]

        cx = one_axis(gx, data[:, 2]) if spread_x > 1e-4 else [0.0, 0.0, float(data[:, 2].mean())]
        cy = one_axis(gy, data[:, 3]) if spread_y > 1e-4 else [0.0, 0.0, float(data[:, 3].mean())]
    return np.array([[cx[0], cx[1], cx[2]],
                     [cy[0], cy[1], cy[2]],
                     [0.0, 0.0, 1.0]])


def screen_point(fx: float, fy: float, size: Sequence[int],
                 inset: int = 1) -> Tuple[int, int]:
    """Доля экрана (0..1) -> пиксель экрана, без «полупиксельных» сдвигов.

    ``0.0`` — первый пиксель, ``1.0`` — последний (``width - 1``), поэтому
    край экрана достижим ровно, а не «где-то рядом».

    ``inset`` отодвигает от самого края на несколько пикселей: pyautogui считает
    угловые пиксели аварийной остановкой (FAILSAFE) и на следующем действии
    бросает исключение. Одного пикселя достаточно, чтобы и край работал, и
    аварийный стоп не срабатывал.
    """
    w, h = int(size[0]), int(size[1])
    step = max(0, min(int(inset), min(w, h) // 4))
    x = int(round(float(fx) * (w - 1)))
    y = int(round(float(fy) * (h - 1)))
    return (min(max(x, step), w - 1 - step), min(max(y, step), h - 1 - step))


class GazeCursor:
    """Сглаживание абсолютной позиции курсора и мёртвая зона против дрожания.

    Зрачок дрожит (микросаккады), поэтому позицию сглаживаем, а мелкие
    перемещения в пределах ``deadzone_px`` игнорируем — иначе курсор «звенит»
    на месте. При этом крупные скачки (перевели взгляд в другой угол) проходят
    сразу — это и даёт эффект телепорта.
    """

    def __init__(self, deadzone_px: float = 12.0, alpha: float = 0.55) -> None:
        self.deadzone_px = float(deadzone_px)
        self.alpha = float(alpha)
        self.x: float | None = None
        self.y: float | None = None

    def reset(self) -> None:
        self.x = None
        self.y = None

    def update(self, target_x: float, target_y: float) -> Tuple[float, float] | None:
        """Вернуть новую позицию курсора или ``None``, если двигать не нужно."""
        if self.x is None or self.y is None:
            self.x, self.y = float(target_x), float(target_y)
            return self.x, self.y
        a = max(0.05, min(1.0, self.alpha))
        nx = a * float(target_x) + (1.0 - a) * self.x
        ny = a * float(target_y) + (1.0 - a) * self.y
        if abs(nx - self.x) < self.deadzone_px and abs(ny - self.y) < self.deadzone_px:
            return None
        self.x, self.y = nx, ny
        return nx, ny


def average_gaze(samples: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """Среднее (по осям) положение зрачка за время «смотрения» на точку."""
    if not samples:
        return 0.0, 0.0
    arr = np.asarray(samples, dtype=np.float64)
    return float(arr[:, 0].mean()), float(arr[:, 1].mean())
