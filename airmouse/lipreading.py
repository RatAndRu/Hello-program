"""«Чтение по губам» без нейросетей: признаки губ + DTW-сопоставление.

Идея ровно та же, что в системах 1990-х: из геометрии губ строится вектор
признаков, слово — это траектория в этом пространстве. Пользователь один раз
записывает несколько повторов слова, дальше распознавание — это поиск
ближайшей траектории (Dynamic Time Warping).

Честные ограничения:
* словарь маленький (5–20 слов), иначе траектории слипаются;
* диктор должен быть один и тот же — это «свой» словарь, не универсальный;
* нужен нормальный свет и видимые губы; усы/рука у рта мешают.

Тем не менее это настоящая работающая система, и она целиком на numpy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple
from collections import deque

import numpy as np

from .landmarks import F, LIPS_INNER, Face, distance, polygon_area

FEATURE_NAMES = (
    "раствор",
    "ширина внутри",
    "ширина снаружи",
    "верхняя губа",
    "нижняя губа",
    "площадь",
    "уголки",
    "протрузия",
)
FEATURE_DIM = len(FEATURE_NAMES)


def mouth_features(face: Face) -> Optional[np.ndarray]:
    """Вектор формы рта, нормированный на масштаб лица."""
    io = face.scale
    if io < 1e-5:
        return None
    top_in = face.xy(F.LIP_TOP_INNER)
    bot_in = face.xy(F.LIP_BOTTOM_INNER)
    top_out = face.xy(F.LIP_TOP_OUTER)
    bot_out = face.xy(F.LIP_BOTTOM_OUTER)
    left_in = face.xy(F.LIP_LEFT_INNER)
    right_in = face.xy(F.LIP_RIGHT_INNER)
    left = face.xy(F.MOUTH_LEFT)
    right = face.xy(F.MOUTH_RIGHT)

    corners_y = (left[1] + right[1]) / 2.0
    lip_center_y = (top_in[1] + bot_in[1]) / 2.0
    area = polygon_area(face.polygon(LIPS_INNER)) / (io * io)

    return np.array([
        distance(top_in, bot_in) / io,              # раствор рта
        distance(left_in, right_in) / io,           # ширина внутренней щели
        distance(left, right) / io,                 # ширина рта по уголкам
        distance(top_out, top_in) / io,             # толщина верхней губы
        distance(bot_in, bot_out) / io,             # толщина нижней губы
        area,                                       # площадь внутреннего контура
        (lip_center_y - corners_y) / io,            # подъём уголков
        distance(top_out, bot_out) / io,            # «протрузия» — вытянутые губы
    ], dtype=np.float64)


def normalize_sequence(seq: np.ndarray, neutral_frames: int = 3) -> np.ndarray:
    """Убирает индивидуальный покой губ: вычитаем первые кадры (нейтраль)."""
    seq = np.asarray(seq, dtype=np.float64)
    if len(seq) == 0:
        return seq
    k = min(neutral_frames, len(seq))
    return seq - seq[:k].mean(axis=0, keepdims=True)


# --------------------------------------------------------------------------- #
#  DTW
# --------------------------------------------------------------------------- #
def dtw_distance(a: np.ndarray, b: np.ndarray, band: float = 0.25) -> float:
    """Нормированное DTW-расстояние между двумя траекториями формы губ.

    Полоса Сакоэ-Чибы не даёт «схлопнуть» слово в один кадр и ускоряет расчёт.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return float("inf")

    band_cells = max(int(round(band * max(n, m))), abs(n - m) + 1)
    inf = float("inf")
    cost = np.full((n + 1, m + 1), inf, dtype=np.float64)
    cost[0, 0] = 0.0

    for i in range(1, n + 1):
        lo = max(1, i - band_cells)
        hi = min(m, i + band_cells)
        for j in range(lo, hi + 1):
            d = float(np.linalg.norm(a[i - 1] - b[j - 1]))
            cost[i, j] = d + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])

    total = cost[n, m]
    if not np.isfinite(total):
        return inf
    # Нормируем на длину пути, иначе длинные слова «дороже» коротких.
    return total / max(n, m)


# --------------------------------------------------------------------------- #
#  Хранилище шаблонов
# --------------------------------------------------------------------------- #
class TemplateStore:
    """Шаблоны слов на диске: ``<dir>/<слово>/<n>.npz``."""

    def __init__(self, directory: Path | str) -> None:
        self.dir = Path(directory)

    def words(self) -> List[str]:
        if not self.dir.exists():
            return []
        return sorted(p.name for p in self.dir.iterdir() if p.is_dir())

    def templates(self, word: str) -> List[np.ndarray]:
        folder = self.dir / word
        if not folder.exists():
            return []
        out: List[np.ndarray] = []
        for path in sorted(folder.glob("*.npz")):
            try:
                with np.load(path) as data:
                    out.append(np.asarray(data["seq"], dtype=np.float64))
            except Exception:
                continue
        return out

    def save(self, word: str, seq: np.ndarray) -> Path:
        folder = self.dir / word
        folder.mkdir(parents=True, exist_ok=True)
        index = len(list(folder.glob("*.npz")))
        path = folder / f"{index:03d}.npz"
        np.savez_compressed(path, seq=np.asarray(seq, dtype=np.float32))
        return path

    def remove(self, word: str) -> int:
        folder = self.dir / word
        if not folder.exists():
            return 0
        count = 0
        for path in folder.glob("*.npz"):
            path.unlink()
            count += 1
        try:
            folder.rmdir()
        except OSError:
            pass
        return count

    def summary(self) -> Dict[str, int]:
        return {w: len(self.templates(w)) for w in self.words()}


@dataclass
class LipResult:
    word: str
    distance: float
    runner_up: str = ""
    runner_up_distance: float = float("inf")
    frames: int = 0


class LipReader:
    """Скользящее окно формы губ -> распознанное слово (или None)."""

    def __init__(
        self,
        store: TemplateStore,
        window_frames: int = 36,
        stride_s: float = 0.15,
        max_distance: float = 0.055,
        band: float = 0.25,
        cooldown_s: float = 1.5,
        margin: float = 1.20,
    ) -> None:
        self.store = store
        self.window_frames = int(window_frames)
        self.stride_s = float(stride_s)
        self.max_distance = float(max_distance)
        self.band = float(band)
        self.cooldown_s = float(cooldown_s)
        self.margin = float(margin)
        self._buffer: Deque[np.ndarray] = deque(maxlen=self.window_frames)
        self._last_check = -1e9
        self._last_hit = -1e9
        self._armed = True
        self._templates: Dict[str, List[np.ndarray]] = {}
        self.reload()

    def reload(self) -> None:
        self._templates = {w: self.store.templates(w) for w in self.store.words()}
        self._templates = {w: t for w, t in self._templates.items() if t}

    @property
    def vocabulary(self) -> List[str]:
        return sorted(self._templates)

    def reset(self) -> None:
        self._buffer.clear()
        self._armed = True

    def push(self, features: Optional[np.ndarray], now: float) -> Optional[LipResult]:
        """Добавляет кадр. Возвращает результат, если слово распознано."""
        if features is None:
            self.reset()
            return None
        self._buffer.append(features)

        # Перевзвод после срабатывания: сначала рот должен закрыться.
        if not self._armed and features[0] < 0.12:
            self._armed = True
            self._buffer.clear()
            return None

        if len(self._buffer) < self.window_frames:
            return None
        if now - self._last_check < self.stride_s:
            return None
        self._last_check = now

        if not self._templates or not self._armed:
            return None
        if now - self._last_hit < self.cooldown_s:
            return None

        seq = normalize_sequence(np.stack(list(self._buffer)))
        best: Optional[LipResult] = None
        scores: List[Tuple[float, str]] = []
        for word, templates in self._templates.items():
            dist = min(dtw_distance(seq, tpl, self.band) for tpl in templates)
            scores.append((dist, word))
        scores.sort()
        if not scores:
            return None
        dist, word = scores[0]
        if dist > self.max_distance:
            return None
        # Слово должно быть заметно ближе второго кандидата, иначе — молчим.
        if len(scores) > 1 and scores[1][0] < dist * self.margin:
            return None

        best = LipResult(
            word=word,
            distance=dist,
            runner_up=scores[1][1] if len(scores) > 1 else "",
            runner_up_distance=scores[1][0] if len(scores) > 1 else float("inf"),
            frames=len(seq),
        )
        self._last_hit = now
        self._armed = False
        return best

    def score_all(self, seq: np.ndarray) -> List[Tuple[float, str]]:
        """Все расстояния до словаря — для отладки и калибровки порога."""
        seq = normalize_sequence(seq)
        out = []
        for word, templates in self._templates.items():
            out.append((min(dtw_distance(seq, t, self.band) for t in templates), word))
        return sorted(out)
