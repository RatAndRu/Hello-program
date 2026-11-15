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

# --------------------------------------------------------------------------- #
#  Калибровка «веди взгляд за точкой» (smooth pursuit)
# --------------------------------------------------------------------------- #
# Так делает и Apple в Eye Tracking (iOS 18): «as a dot appears in different
# locations, follow its movement with your eyes». Точечный мастер требует
# попасть взглядом в угол секунду-две и не даёт никакой информации о динамике,
# а плавное ведение даёт сразу: где именно взгляд смотрит на экран, насколько
# быстро зрачок меняет положение и насколько он шумит.
PURSUIT_ROWS = (0.10, 0.30, 0.50, 0.70, 0.90)
PURSUIT_SWEEP_S = 2.6            # столько идёт проход по одной строке
PURSUIT_MARGIN = 0.045           # отступ от края: точка у самого края не читается
PURSUIT_DURATION_S = PURSUIT_SWEEP_S * len(PURSUIT_ROWS)


def _pursuit_segments(duration: float) -> List[Tuple[str, int, float]]:
    """Разбиение траектории на отрезки: проход по строке и переход на следующую.

    Переходы нужны, чтобы точка не телепортировалась: если она просто «моргнёт»
    с конца строки на начало следующей, глаз физически не успеет (саккада 30–80
    мс плюс задержка зрачка), и такие кадры только испортят подгонку.
    """
    rows = len(PURSUIT_ROWS)
    w_row, w_vert = 1.0, 0.14
    total = rows * w_row + (rows - 1) * w_vert
    unit = max(0.1, float(duration)) / total
    segments: List[Tuple[str, int, float]] = []
    for i in range(rows):
        segments.append(("row", i, unit * w_row))
        if i < rows - 1:
            segments.append(("vert", i, unit * w_vert))
    return segments


def pursuit_point(t: float, duration: float = PURSUIT_DURATION_S) -> Tuple[float, float]:
    """Где сейчас красная точка (нормированные координаты экрана).

    Змейка по пяти строкам: слева направо, строка ниже — справа налево, между
    строками — короткий плавный переход. Так взгляд проходит и углы, и середину
    краёв, а предсказуемое непрерывное движение (в отличие от случайных прыжков)
    удобно вести глазами — зрачок успевает «догнать» точку.
    """
    duration = max(0.1, float(duration))
    t = min(max(0.0, float(t)), duration - 1e-6)
    left = PURSUIT_MARGIN
    span = 1.0 - 2.0 * PURSUIT_MARGIN
    passed = 0.0
    for kind, index, length in _pursuit_segments(duration):
        if t <= passed + length or length <= 0.0:
            u = 0.0 if length <= 0.0 else (t - passed) / length
            u = min(max(u, 0.0), 1.0)
            y = left + span * PURSUIT_ROWS[index]
            if kind == "row":
                forward = index % 2 == 0
                x = left + span * (u if forward else 1.0 - u)
                return (x, y)
            # переход вниз: x стоит на краю строки, y едет к следующей
            forward = index % 2 == 0
            x = left + span * (1.0 if forward else 0.0)
            y_next = left + span * PURSUIT_ROWS[index + 1]
            return (x, y + (y_next - y) * u)
        passed += length
    y = left + span * PURSUIT_ROWS[-1]
    x = left + span * (1.0 if (len(PURSUIT_ROWS) - 1) % 2 == 0 else 0.0)
    return (x, y)


def pursuit_metrics(samples: Sequence[Sequence[float]]) -> Dict[str, float]:
    """Динамика взгляда по кадрам «вёл за точкой».

    ``samples`` — пятёрки ``(t, gaze_u, gaze_v, screen_x, screen_y)``.
    Возвращает:

    * ``latency_ms`` — на сколько зрачок отстаёт от цели (по максимуму
      корреляции скоростей);
    * ``responsiveness`` — насколько согласованно двигаются цель и зрачок
      (1 — идеально, 0 — зрачок живёт своей жизнью);
    * ``speed`` — медианная скорость зрачка, «единиц зрачка в секунду».
    """
    rows = [tuple(float(v) for v in s) for s in samples if len(s) >= 5]
    if len(rows) < 8:
        return {"latency_ms": 0.0, "responsiveness": 0.0, "speed": 0.0, "frames": float(len(rows))}
    data = np.asarray(rows, dtype=np.float64)
    t, gx, gy, sx, sy = data[:, 0], data[:, 1], data[:, 2], data[:, 3], data[:, 4]
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
    if dt <= 1e-6:
        return {"latency_ms": 0.0, "responsiveness": 0.0, "speed": 0.0, "frames": float(len(rows))}
    gvx, gvy = np.diff(gx) / dt, np.diff(gy) / dt
    svx, svy = np.diff(sx) / dt, np.diff(sy) / dt
    gspeed = np.hypot(gvx, gvy)
    sspeed = np.hypot(svx, svy)

    def corr(a: np.ndarray, b: np.ndarray) -> float:
        if a.size < 4 or float(a.std()) < 1e-9 or float(b.std()) < 1e-9:
            return 0.0
        return float(np.clip(np.corrcoef(a, b)[0, 1], -1.0, 1.0))

    # Задержку ищем по **вектору** скорости, а не по её величине: точка едет с
    # ровной скоростью, и «модуль» почти не меняется — зато направление и знак
    # компонент меняются на поворотах, и сдвиг по времени виден чётко.
    best_r, best_lag = -2.0, 0
    max_lag = 8
    for lag in range(0, max_lag + 1):
        if lag == 0:
            ax, bx, ay, by = gvx, svx, gvy, svy
        else:
            ax, bx = gvx[lag:], svx[:-lag]
            ay, by = gvy[lag:], svy[:-lag]
        r = 0.5 * (corr(ax, bx) + corr(ay, by))
        if r > best_r:
            best_r, best_lag = r, lag
    return {
        "latency_ms": float(best_lag * dt * 1000.0),
        "responsiveness": float(np.clip(best_r, 0.0, 1.0)),
        "speed": float(np.median(gspeed)),
        "frames": float(len(rows)),
    }


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
    latency_ms: float = 0.0          # насколько зрачок отстаёт от цели
    responsiveness: float = 0.0      # согласованность движения с целью (0..1)
    pursuit_frames: int = 0          # сколько кадров снято «ведением»
    face_scale: float = 0.0          # межзрачковое расстояние при калибровке

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
    def fit(self, robust: bool = True) -> bool:
        """Подобрать гомографию по накопленным точкам (DLT, наименьшие квадраты).

        Когда точек много (калибровка «веди взглядом»), подгонка делается
        **с отбраковкой**: пара выбросов — моргание, сдвиг головы, — иначе
        уводит всю калибровку. Отбрасываем худшие 15% по промаху и подгоняем
        заново (два прохода).
        """
        if robust and len(self.points) >= 32:
            for _ in range(2):
                if not self._fit_once() or not self.ready:
                    return False
                residuals = []
                for gx, gy, sx, sy in self.points:
                    px, py = self.apply(gx, gy)
                    residuals.append(max(abs(px - sx), abs(py - sy)))
                if max(residuals) < 0.01:
                    # подгонка и так точная: выбросов нет, точки не выбрасываем
                    return True
                cutoff = float(np.quantile(residuals, 0.85))
                kept = [p for p, r in zip(self.points, residuals) if r <= cutoff]
                if len(kept) < 12 or len(kept) == len(self.points):
                    break
                self.points = kept
            return self._fit_once()
        return self._fit_once()

    def _fit_once(self) -> bool:
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
                "head_gain": [round(v, 4) for v in self.head_gain],
                "latency_ms": round(self.latency_ms, 1),
                "responsiveness": round(self.responsiveness, 3),
                "pursuit_frames": int(self.pursuit_frames),
                "face_scale": round(self.face_scale, 4)}

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
            calib.latency_ms = float(data.get("latency_ms") or 0.0)
            calib.responsiveness = float(data.get("responsiveness") or 0.0)
            calib.pursuit_frames = int(data.get("pursuit_frames") or 0)
            calib.face_scale = float(data.get("face_scale") or 0.0)
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


class GazeDwell:
    """Выбор «взглядом с удержанием»: посмотрел и подержал — клик.

    Зачем, если клик и так делается щипком. По литературе «взгляд + щипок»
    точнее, чем «взгляд + удержание», но у удержания есть своё место: руки
    заняты, или щипок не берётся из-за перчатки/света. Классика жанра —
    «Midas touch»: любое движение глаз активирует кнопку. Лечение одно и то же
    с 1980-х: **пауза взгляда** (dwell time) плюс видимый прогресс, чтобы
    человек понимал, что вот-вот сработает. Исследования дают 400–800 мс,
    600 мс — самый удобный вариант (Majaranta et al.; usability study, Displays
    2021), 200 мс — слишком мало: люди не успевают передумать.

    Прогресс сбрасывается, если взгляд ушёл дальше ``radius_px`` — иначе
    «удержание» засчитывалось бы дрожанию зрачка.
    """

    def __init__(self, dwell_s: float = 0.6, radius_px: float = 60.0,
                 cooldown_s: float = 1.0) -> None:
        self.dwell_s = max(0.05, float(dwell_s))
        self.radius_px = max(1.0, float(radius_px))
        self.cooldown_s = max(0.0, float(cooldown_s))
        self.reset()

    def reset(self) -> None:
        self._anchor: Optional[Tuple[float, float]] = None
        self._since = 0.0
        self._last_fire = -1e9
        self.progress = 0.0

    def update(self, x: float, y: float, now: float, valid: bool = True) -> Tuple[float, bool]:
        """Один кадр: ``(прогресс 0..1, сработал ли клик сейчас)``."""
        if not valid:
            self.reset()
            return (0.0, False)
        if self._anchor is None or math.hypot(x - self._anchor[0], y - self._anchor[1]) > self.radius_px:
            self._anchor = (float(x), float(y))
            self._since = now
        elapsed = max(0.0, now - self._since)
        self.progress = min(1.0, elapsed / self.dwell_s)
        fired = False
        if self.progress >= 1.0 and (now - self._last_fire) >= self.cooldown_s:
            fired = True
            self._last_fire = now
            # после клика начинаем заново: чтобы не «долбить» каждые 0.6 с,
            # человек должен сдвинуть взгляд или подождать cooldown
            self._anchor = (float(x), float(y))
            self._since = now
            self.progress = 0.0
        return (self.progress, fired)


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
