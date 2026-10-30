"""Измерение по фотографии: силуэт → числа, пригодные для модели.

Задача модуля — не «угадать 3D», а дать измеримые величины, которые можно
записать в постановку задачи: габарит в пикселях, профиль ширины, угол наклона
камеры по эллипсу верхней кромки и совпадение силуэта модели с фотографией.

Всё считается по маске объекта (что на фото объект, а что фон) и работает на
numpy. Маска берётся одним из двух способов:

* ``mask_by_background`` — фон однотонный или градиентный и отличается по цвету
  (синяя «студийная» заливка, белый лист, серый фон);
* готовая маска от пользователя (альфа-канал PNG или чёрно-белая картинка).

Никаких предположений о «понимании» сцены: если фон пёстрый, вызывающий код
обязан передать маску сам, иначе результат недействителен.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Iterable

import numpy as np

__all__ = [
    "Silhouette", "mask_by_background", "mask_from_alpha",
    "measure", "fit_top_arc", "camera_elevation", "iou", "compare",
]


# --------------------------------------------------------------------------
# Маска
# --------------------------------------------------------------------------
def mask_by_background(rgb: np.ndarray, tol: float = 14.0) -> np.ndarray:
    """Маска объекта: True там, где цвет не похож на фон.

    Фон оценивается по четырём углам и по верхней/нижней кромке. Модель фона —
    линейный градиент по вертикали плюс допуск ``tol`` (в уровнях 0…255).
    Так работает и на однотонном фоне, и на «студийном» градиенте.
    """
    a = np.asarray(rgb, dtype=np.float64)
    if a.ndim != 3 or a.shape[2] < 3:
        raise ValueError("нужен цветной массив H×W×3")
    h, w = a.shape[:2]
    cols = np.concatenate([a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)], axis=0)
    ys = np.concatenate([np.repeat(np.arange(h), 4), np.repeat(np.arange(h), 4)])
    # линейная регрессия цвета фона от y, отдельно по каналам
    A = np.stack([np.ones_like(ys, dtype=np.float64), ys.astype(np.float64)], axis=1)
    coef, *_ = np.linalg.lstsq(A, cols, rcond=None)
    yy = np.arange(h, dtype=np.float64)
    bg = (np.stack([np.ones_like(yy), yy], axis=1) @ coef)  # h×3
    pred = np.repeat(bg[:, None, :], w, axis=1)
    dist = np.linalg.norm(a - pred, axis=2)
    return dist > tol


def mask_from_alpha(rgba: np.ndarray) -> np.ndarray:
    a = np.asarray(rgba)
    if a.ndim != 3 or a.shape[2] < 4:
        raise ValueError("нужен массив H×W×4 с альфа-каналом")
    return a[:, :, 3] > 8


# --------------------------------------------------------------------------
# Основные метрики силуэта
# --------------------------------------------------------------------------
@dataclass
class Silhouette:
    """Всё, что можно честно измерить по одному силуэту."""

    width: int
    height: int
    area: int
    fill: float                  # площадь / площадь габарита
    cx: float
    cy: float
    principal_deg: float         # угол главной оси к горизонтали
    anisotropy: float            # sqrt(λ1/λ2) — вытянутость
    symmetry_err_pct: float      # несовпадение половин относительно оси X = cx
    width_profile: list = field(default_factory=list)   # [(доля высоты, ширина px)]
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def measure(mask: np.ndarray, profile_rows: int = 12) -> Silhouette:
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        raise ValueError("пустая маска: объект не найден")
    ys, xs = np.nonzero(m)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    area = int(m.sum())
    cx = float(xs.mean())
    cy = float(ys.mean())

    # главные оси по ковариации точек силуэта
    pts = np.stack([xs - cx, ys - cy], axis=1).astype(np.float64)
    cov = pts.T @ pts / max(len(pts), 1)
    evals, evecs = np.linalg.eigh(cov)
    order = np.argsort(evals)[::-1]
    evals = evals[order]
    v = evecs[:, order[0]]
    principal = math.degrees(math.atan2(v[1], v[0])) % 180.0
    aniso = float(math.sqrt(max(evals[0], 1e-12) / max(evals[1], 1e-12)))

    # симметрия относительно вертикальной оси, проходящей через центр
    xarr = np.arange(m.shape[1])
    xm = np.rint(2.0 * cx - xarr).astype(np.int64)
    valid = (xm >= 0) & (xm < m.shape[1])
    left = m[:, valid]
    right = m[:, xm[valid]]
    inter = np.logical_and(left, right).sum()
    union = np.logical_or(left, right).sum()
    sym = 1.0 - (inter / max(union, 1))

    prof = []
    for k in range(1, profile_rows + 1):
        fy = k / (profile_rows + 1)
        row = int(round(y0 + fy * (h - 1)))
        rr = np.nonzero(m[row])[0]
        prof.append([round(fy, 3), int(rr.max() - rr.min() + 1) if len(rr) else 0])

    notes = []
    if sym > 0.10:
        notes.append(f"силуэт несимметричен относительно x={cx:.0f} ({sym * 100:.1f} %): "
                     "у детали есть выступ с одной стороны либо камера "
                     "повёрнута вокруг оптической оси")

    return Silhouette(width=w, height=h, area=area, fill=area / float(w * h),
                      cx=cx, cy=cy, principal_deg=principal, anisotropy=aniso,
                      symmetry_err_pct=sym * 100.0, width_profile=prof, notes=notes)


# --------------------------------------------------------------------------
# Наклон камеры по верхней кромке
# --------------------------------------------------------------------------
def fit_top_arc(mask: np.ndarray):
    """Подгонка дуги эллипса к верхней кромке силуэта.

    Изображение верхнего круга тела вращения — эллипс: полуось ``a`` по
    горизонтали, ``b`` по вертикали, при ортогональной проекции
    ``b/a = sin(угла подъёма камеры)``. Верхняя дуга линейна в координатах
    ``t = sqrt(1 − ((x−cx)/a)²)``: ``y = cy − b·t``, поэтому при известных
    ``cx`` и ``a`` величины ``cy`` и ``b`` даёт обычный МНК.

    Наивная подгонка ошибается на 5–15 %, и это не мелочь: угол уезжает.
    Поэтому вводится проверка, которая отбраковывает невозможные гипотезы:

    * ``cx`` — медиана x самых верхних пикселей (там дуга горизонтальна);
    * ``a`` перебирается, а не берётся по габариту: ручка или кронштейн
      выпирают вбок и завышают ширину;
    * для каждой гипотезы дуга проверяется на физическую возможность:
      эллипс не может проходить **выше** кромки силуэта — если проходит,
      значит ``a`` взята от посторонней детали, и гипотеза отбрасывается.

    Угол, полученный так, — **кажущийся**: при перспективной съёмке верх
    ближе к камере и дуга выглядит больше (на рендере с камерой в 4 радиуса
    ошибка доходит до 3.5°). Точный ракурс даёт подгонка рендером, см.
    ``forma.vision.fit.fit_camera``.
    """
    m = np.asarray(mask, dtype=bool)
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    w = x1 - x0 + 1

    top = xs[ys <= y0 + 2]
    cx0 = float(np.median(top)) if len(top) else (x0 + x1) / 2.0

    # верхняя граница по столбцам
    tops = np.full(m.shape[1], -1, dtype=np.int64)
    for x in range(x0, x1 + 1):
        col = np.nonzero(m[:, x])[0]
        if len(col):
            tops[x] = col.min()

    best = None
    for dcx in (-0.02 * w, 0.0, 0.02 * w):
        cx = cx0 + dcx
        for frac in np.linspace(0.20, 0.55, 36):
            a = frac * w
            lo, hi = int(round(cx - a)), int(round(cx + a))
            if lo < x0 or hi > x1:
                # край эллипса за пределами силуэта — гипотеза невозможна
                if lo < x0 - 2 or hi > x1 + 2:
                    continue
            sel = np.arange(max(lo, x0), min(hi, x1) + 1)
            sel = sel[tops[sel] >= 0]
            if len(sel) < 15:
                continue
            u = (sel - cx) / a
            keep = np.abs(u) <= 0.95
            if keep.sum() < 15:
                continue
            t = np.sqrt(np.clip(1.0 - u[keep] ** 2, 0.0, 1.0))
            A = np.stack([np.ones_like(t), -t], axis=1)
            yy = tops[sel][keep].astype(np.float64)
            (cy, b), *_ = np.linalg.lstsq(A, yy, rcond=None)
            if b <= 0:
                continue
            resid = float(np.median(np.abs(A @ np.array([cy, b]) - yy)))
            if resid > max(2.0, 0.03 * b):
                continue
            # проверка невозможности: дуга не должна быть выше силуэта
            probe = np.linspace(-0.97, 0.97, 81)
            xp = np.round(cx + probe * a).astype(np.int64)
            xp = xp[(xp >= x0) & (xp <= x1)]
            if len(xp) < 20:
                continue
            tp = np.sqrt(np.clip(1.0 - ((xp - cx) / a) ** 2, 0.0, 1.0))
            yp = cy - b * tp
            above = yp < (tops[xp] - 3.0)
            if above.mean() > 0.02:
                continue
            cover = float((~above).mean())
            score = -cover + resid / max(b, 1.0)
            if best is None or score < best[0]:
                best = (score, cx, cy, a, b, resid, cover)

    if best is None:
        return None
    _, cx, cy, a, b, resid, cover = best
    if b > 1.05 * a:
        return None
    return float(cx), float(cy), float(a), float(b), resid, cover


def camera_elevation(mask: np.ndarray) -> dict:
    """Оценка угла подъёма камеры и «недонаклона» верхней кромки.

    Возвращает словарь с числами и пояснением; ``ok=False``, если кромка не
    распознана — тогда угол нельзя утверждать, и это должно попасть в отчёт.
    """
    fit = fit_top_arc(mask)
    if fit is None:
        return {"ok": False, "reason": "верхняя кромка не похожа на эллипс"}
    cx, cy, a, b, resid, cover = fit
    ratio = b / a
    elev = math.degrees(math.asin(min(max(ratio, 0.0), 1.0)))
    return {"ok": True, "cx": cx, "cy": cy, "a": a, "b": b, "ratio": ratio,
            "elevation_deg": elev, "resid_px": resid, "arc_cover": cover,
            "reason": "b/a = sin(угла подъёма камеры) при ортогональной проекции"}


# --------------------------------------------------------------------------
# Сравнение силуэтов: критерий «похоже / не похоже»
# --------------------------------------------------------------------------
def _runs(row: np.ndarray) -> list:
    """Непрерывные отрезки в отсортированном массиве индексов."""
    if len(row) == 0:
        return []
    out = []
    a = prev = int(row[0])
    for x in row[1:]:
        x = int(x)
        if x - prev > 1:
            out.append((a, prev))
            a = x
        prev = x
    out.append((a, prev))
    return out


def _frame(mask: np.ndarray, size: int) -> np.ndarray:
    """Переносит силуэт в кадр, нормируя его по высоте, низ — на центр кадра.

    Почему по высоте: высота объекта на фотографии видна целиком (он стоит), а
    толщина и глубина — нет. Почему нормировка нужна вообще: масштаб рендера
    модели произволен (модель вписывается в кадр), поэтому сравнивать пиксели
    напрямую нельзя — модель окажется «крошкой» в углу кадра.

    После такой нормировки проверяемыми становятся **пропорции**: модель на
    7 % шире при той же высоте даёт ошибку строк 3 px и IoU 0.92, а изменённая
    высота ловится через отношение ширины к высоте (проверено на кружке).

    Перенос делается **отрезками по строкам**, а не точками: точечная пересадка
    даёт дырчатую маску, и IoU падает до 0.4 даже у правильной модели.

    Абсолютный размер по одной фотографии без масштабной линейки неизвестен,
    поэтому он здесь сознательно не измеряется: проверяется форма, а не метры.
    """
    m = np.asarray(mask, dtype=bool)
    ys, xs = np.nonzero(m)
    out = np.zeros((size, size), dtype=bool)
    if len(xs) == 0:
        return out
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    # нормировка по БОЛЬШЕЙ стороне габарита: по высоте нельзя — вытянутая
    # вбок деталь (кронштейн, ручка) обрежется краями кадра, и все ошибки по
    # строкам превратятся в нули. Пропорции при этом не теряются: их отдельно
    # проверяет отношение ширины к высоте.
    scale = 0.92 * size / max(y1 - y0 + 1, x1 - x0 + 1)
    cx = (x0 + x1) / 2.0
    for oy in range(size):
        sy = int(round(y1 - ((size - 1) - oy) / scale))
        if sy < y0 or sy > y1:
            continue
        for a, b in _runs(np.nonzero(m[sy])[0]):
            ox0 = int(round((a - cx) * scale + size / 2.0))
            ox1 = int(round((b - cx) * scale + size / 2.0))
            ox0 = max(ox0, 0)
            ox1 = min(ox1, size - 1)
            if ox1 >= ox0:
                out[oy, ox0:ox1 + 1] = True
    return out


def _bbox(mask):
    ys, xs = np.nonzero(np.asarray(mask, dtype=bool))
    return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())


def iou(a: np.ndarray, b: np.ndarray) -> float:
    """IoU двух силуэтов в общей системе координат эталона ``a``."""
    size = 256
    fa = _frame(a, size)
    fb = _frame(b, size)
    inter = np.logical_and(fa, fb).sum()
    union = np.logical_or(fa, fb).sum()
    return float(inter / max(union, 1))


def compare(reference: np.ndarray, rendered: np.ndarray, cells: int = 4) -> dict:
    """Сравнение силуэта модели с силуэтом фотографии — по числам.

    Оба силуэта нормируются по большей стороне габарита и центрируются по
    своему центру габарита: глобальный сдвиг в кадре неизвестен (фотограф
    кадрирует по-своему), поэтому он не считается ошибкой — ошибкой считается
    расхождение формы и пропорций.

    Четыре числа и приговор (порог «похоже» — все условия сразу):

    * ``iou`` ≥ 0.90 — общая похожесть;
    * ``row_err_px`` ≤ 4 — медианная разница **ширины** по строкам (кадр 256):
      «на этой высоте деталь шире/уже, чем нужно»;
    * ``aspect_err_pct`` ≤ 5 — разница отношения ширины к высоте, %: ловит
      «толщина не та», когда силуэт в целом совпал;
    * ``side_err`` ≤ 6 — разница асимметрии слева/справа: положительное значит,
      что у модели справа больше материала, чем у фотографии (деталь смещена
      или повёрнута). По модулю сравниваются медианы, а не отдельные строки;
    * ``worst_cell`` ≥ 0.80 — худшая клетка сетки ``cells``×``cells``: ловит
      локальные ошибки (ручка не там), которые общий IoU почти не замечает.
    """
    size = 256
    fa = _frame(reference, size)
    fb = _frame(rendered, size)

    inter = np.logical_and(fa, fb).sum()
    union = np.logical_or(fa, fb).sum()

    def widths(m):
        out = {}
        for y in range(size):
            xs = np.nonzero(m[y])[0]
            if len(xs):
                out[y] = (int(xs.min()), int(xs.max()))
        return out

    wa, wb = widths(fa), widths(fb)
    rows = [abs((wa[y][1] - wa[y][0]) - (wb[y][1] - wb[y][0]))
            for y in wa.keys() & wb.keys()]
    row_err = float(np.median(rows)) if rows else float("nan")

    def asym(m):
        ys, xs = np.nonzero(m)
        cx = (xs.min() + xs.max()) / 2.0
        vals = []
        for y in range(size):
            xx = np.nonzero(m[y])[0]
            if len(xx):
                vals.append(((xx.max() - cx) - (cx - xx.min())))
        return float(np.median(vals)) if vals else float("nan")

    # положительное — у модели справа больше материала, чем на фото
    side_err = asym(fa) - asym(fb)

    step = size // cells
    worst = None
    for i in range(cells):
        for j in range(cells):
            sa = fa[i * step:(i + 1) * step, j * step:(j + 1) * step]
            sb = fb[i * step:(i + 1) * step, j * step:(j + 1) * step]
            u = np.logical_or(sa, sb).sum()
            if u < 40:
                continue
            ci = np.logical_and(sa, sb).sum() / u
            if worst is None or ci < worst["iou"]:
                worst = {"cell": [i, j], "iou": float(ci)}

    iou_v = float(inter / max(union, 1))

    ya, xa_ = np.nonzero(np.asarray(reference, dtype=bool))
    yb, xb_ = np.nonzero(np.asarray(rendered, dtype=bool))
    aspect_ref = (xa_.max() - xa_.min() + 1) / max(ya.max() - ya.min() + 1, 1)
    aspect_got = (xb_.max() - xb_.min() + 1) / max(yb.max() - yb.min() + 1, 1)
    aspect_err = (aspect_got / max(aspect_ref, 1e-9) - 1.0) * 100.0

    ok = (iou_v >= 0.90 and row_err <= 4.0 and abs(aspect_err) <= 5.0
          and abs(side_err) <= 6.0 and (worst is None or worst["iou"] >= 0.80))
    return {"iou": iou_v, "row_err_px": row_err, "side_err": side_err,
            "aspect_ref": float(aspect_ref), "aspect_model": float(aspect_got),
            "aspect_err_pct": float(aspect_err),
            "worst_cell": worst, "verdict": "похоже" if ok else "не похоже"}
