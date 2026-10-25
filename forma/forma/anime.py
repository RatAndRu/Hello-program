"""Аниме и манга: контурный рисунок поверх обычного рендера.

Задача — не «обвести силуэт», а нарисовать настоящие контуры, как в Blender
(Line Art / Freestyle): границу предмета с фоном, изломы поверхности (рёбра,
складки, фаски) и стыки отдельных деталей. Всё это считается по буферам
глубины и нормалей, поэтому линии идут по форме, а не по общему абрису.

Модуль работает в двух местах:
  * `apply_style` — пост-обработка снимка PNG (numpy, без внешних библиотек);
  * те же параметры (`normalize_style`) получает окно программы, где контуры
    рисует шейдер на WebGL (`web/js/viewer.js`) — стиль в окне и в снимке
    одинаковый.

Стили: ``аниме`` (цвет + чёткие контуры + ступени тона), ``манга`` (чёрно-белое
с растром), ``комикс`` (толстые контуры + точки в тенях), ``линия`` (только
контуры на бумаге), ``выкл``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .errors import GeometryError
from .geometry import color_to_float_rgb, normalize_color

MODES = ("аниме", "манга", "комикс", "скетч", "линия", "выкл")

MODE_ALIASES = {
    "аниме": "аниме", "anime": "аниме", "мультик": "аниме", "мультяшный": "аниме",
    "cel": "аниме", "toon": "аниме", "тун": "аниме",
    "манга": "манга", "manga": "манга", "чб": "манга", "чёрно-белый": "манга",
    "черно-белый": "манга", "скетч": "манга", "карандаш": "манга",
    "комикс": "комикс", "comic": "комикс", "комиксы": "комикс", "комиксный": "комикс",
    "скетч": "скетч", "sketch": "скетч", "карандаш": "скетч", "набросок": "скетч",
    "штриховка": "скетч", "hatch": "скетч", "рисунок": "скетч",
    "линия": "линия", "линии": "линия", "лайн": "линия", "line": "линия",
    "lineart": "линия", "контур": "линия", "контуры": "линия", "обводка": "линия",
    "выкл": "выкл", "off": "выкл", "нет": "выкл", "обычный": "выкл",
    "реалистично": "выкл",
}

PRESETS: dict[str, dict[str, Any]] = {
    "аниме": {
        "mode": "аниме", "line": 1.6, "color": "#101018", "inner": True,
        "crease": 32.0, "depth": 0.035, "seams": True, "toon": 3,
        "tone": 0.0, "paper": "#f4f6fa", "shade": True,
        "hatch": 0.0, "hatch_angle": 45.0, "hatch_step": 8.0, "paper_tex": 0.0,
        "lines": "все",
    },
    "манга": {
        "mode": "манга", "line": 1.8, "color": "#0b0b0e", "inner": True,
        "crease": 30.0, "depth": 0.03, "seams": True, "toon": 3,
        "tone": 0.75, "paper": "#fbfbf7", "shade": True,
        "hatch": 0.0, "hatch_angle": 45.0, "hatch_step": 8.0, "paper_tex": 0.25,
        "lines": "все",
    },
    "комикс": {
        "mode": "комикс", "line": 2.6, "color": "#0a0a0c", "inner": True,
        "crease": 38.0, "depth": 0.045, "seams": True, "toon": 2,
        "tone": 0.6, "paper": "#fdf4e3", "shade": True,
        "hatch": 0.0, "hatch_angle": 40.0, "hatch_step": 7.0, "paper_tex": 0.2,
        "lines": "все",
    },
    "скетч": {
        "mode": "скетч", "line": 1.5, "color": "#22242c", "inner": True,
        "crease": 26.0, "depth": 0.032, "seams": True, "toon": 0,
        "tone": 0.0, "paper": "#f6f1e6", "shade": True,
        "hatch": 0.85, "hatch_angle": 52.0, "hatch_step": 7.0, "paper_tex": 0.6,
        "lines": "все",
    },
    "линия": {
        "mode": "линия", "line": 1.4, "color": "#101018", "inner": True,
        "crease": 28.0, "depth": 0.03, "seams": True, "toon": 0,
        "tone": 0.0, "paper": "#ffffff", "shade": False,
        "hatch": 0.0, "hatch_angle": 45.0, "hatch_step": 8.0, "paper_tex": 0.0,
        "lines": "все",
    },
    "выкл": {
        "mode": "выкл", "line": 1.6, "color": "#101018", "inner": True,
        "crease": 32.0, "depth": 0.035, "seams": True, "toon": 0,
        "tone": 0.0, "paper": None, "shade": True,
        "hatch": 0.0, "hatch_angle": 45.0, "hatch_step": 8.0, "paper_tex": 0.0,
        "lines": "все",
    },
}


def normalize_mode(value: Any, default: str = "аниме") -> str:
    """«манга», «Manga», «чб» → канонический режим."""
    key = str(value or "").strip().lower()
    if not key:
        return default
    if key not in MODE_ALIASES:
        raise GeometryError(
            f"Неизвестный стиль «{value}».",
            hint="mode: " + ", ".join(MODES) + ".")
    return MODE_ALIASES[key]


def _paper(value: Any, default: str | None) -> str | None:
    """Цвет «бумаги»: hex или пусто (значит фон сцены)."""
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("", "сцена", "нет", "no", "off", "выкл", "0"):
        return None
    try:
        return normalize_color(text)
    except Exception:
        raise GeometryError(f"Непонятный цвет бумаги «{value}».",
                            hint="Например paper=#ffffff или paper=сцена.")


_LINE_MODES = {
    "все": "все", "all": "все", "детали": "все", "по деталям": "все",
    "группы": "группы", "по группам": "группы", "group": "группы",
    "groups": "группы", "grouped": "группы",
    "материалы": "материалы", "по материалам": "материалы", "material": "материалы",
    "materials": "материалы", "цвет": "материалы",
}


def _line_mode(value: Any) -> str:
    """Где рисовать линию на стыке: на каждой детали, только между группами
    или только между разными материалами."""
    key = str(value or "все").strip().lower()
    if key not in _LINE_MODES:
        raise GeometryError(f"Неизвестный режим линий «{value}».",
                            hint="lines: все, группы или материалы.")
    return _LINE_MODES[key]


def normalize_style(data: dict | None) -> dict:
    """Приводит настройки стиля к полному словарю с проверкой диапазонов."""
    src = dict(data or {})
    mode = normalize_mode(src.get("mode"), "аниме") if src else "выкл"
    if not src:
        base = dict(PRESETS["выкл"])
    else:
        base = dict(PRESETS[mode])
    if mode == "выкл":
        base["mode"] = "выкл"
    out = dict(base)
    if src.get("mode") is not None:
        out["mode"] = mode
    if "line" in src and src["line"] is not None:
        line = float(src["line"])
        if not (0.0 <= line <= 12.0):
            raise GeometryError("Толщина контура должна быть от 0 до 12 px.",
                                hint="Обычно 1…3 px.")
        out["line"] = line
    if src.get("color"):
        out["color"] = normalize_color(str(src["color"]))
    if "inner" in src and src["inner"] is not None:
        out["inner"] = bool(src["inner"])
    if "seams" in src and src["seams"] is not None:
        out["seams"] = bool(src["seams"])
    if "shade" in src and src["shade"] is not None:
        out["shade"] = bool(src["shade"])
    if "crease" in src and src["crease"] is not None:
        crease = float(src["crease"])
        if not (1.0 <= crease <= 89.0):
            raise GeometryError("Угол внутренних контуров должен быть 1…89°.",
                                hint="20–40° — обычные складки и рёбра.")
        out["crease"] = crease
    if "depth" in src and src["depth"] is not None:
        depth = float(src["depth"])
        if not (0.0005 <= depth <= 0.6):
            raise GeometryError("Порог глубины должен быть 0.0005…0.6.",
                                hint="0.03 — контур на резком перепаде глубины.")
        out["depth"] = depth
    if "toon" in src and src["toon"] is not None:
        toon = int(round(float(src["toon"])))
        if not (0 <= toon <= 8):
            raise GeometryError("Ступеней тона должно быть 0…8.",
                                hint="0 — без ступеней, 3 — обычный аниме-тон.")
        out["toon"] = toon
    if "tone" in src and src["tone"] is not None:
        tone = float(src["tone"])
        if not (0.0 <= tone <= 1.0):
            raise GeometryError("Сила растра должна быть 0…1.")
        out["tone"] = tone
    if "hatch" in src and src["hatch"] is not None:
        hatch = float(src["hatch"])
        if not (0.0 <= hatch <= 1.0):
            raise GeometryError("Сила штриховки должна быть 0…1.",
                                hint="0 — без штриховки, 0.85 — плотный карандаш.")
        out["hatch"] = hatch
    if "hatch_angle" in src and src["hatch_angle"] is not None:
        out["hatch_angle"] = float(src["hatch_angle"]) % 180.0
    if "hatch_step" in src and src["hatch_step"] is not None:
        step = float(src["hatch_step"])
        if not (2.0 <= step <= 40.0):
            raise GeometryError("Шаг штриховки должен быть 2…40 px.")
        out["hatch_step"] = step
    if "paper_tex" in src and src["paper_tex"] is not None:
        tex = float(src["paper_tex"])
        if not (0.0 <= tex <= 1.0):
            raise GeometryError("Зерно бумаги должно быть 0…1.")
        out["paper_tex"] = tex
    if "lines" in src and src["lines"] is not None:
        out["lines"] = _line_mode(src["lines"])
    if "paper" in src:
        out["paper"] = _paper(src["paper"], base.get("paper"))
    if out["mode"] == "выкл":
        out["paper"] = None
    return out


def style_from_args(a) -> dict:
    """Читает параметры команды `anime` и возвращает готовый стиль."""
    raw: dict[str, Any] = {}
    mode_text = a.text("mode")
    if mode_text:
        raw["mode"] = mode_text
    off = a.text("off")
    if off and str(off).strip().lower() in ("да", "yes", "1", "true", "вкл"):
        raw["mode"] = "выкл"
    if a.has("line"):
        raw["line"] = a.num("line", 1.6)
    if a.has("color"):
        raw["color"] = a.text("color")
    for key in ("inner", "seams", "shade"):
        if a.has(key):
            raw[key] = a.boolean(key, True)
    for key in ("crease", "depth", "toon", "tone", "hatch", "hatch_angle",
                "hatch_step", "paper_tex"):
        if a.has(key):
            raw[key] = a.num(key, PRESETS["аниме"].get(key, 0.0))
    if a.has("lines"):
        raw["lines"] = a.text("lines")
    if a.has("paper"):
        raw["paper"] = a.text("paper")
    return normalize_style(raw)


def is_active(style: dict | None) -> bool:
    try:
        return normalize_style(style)["mode"] != "выкл"
    except GeometryError:
        return False


# --------------------------------------------------------------------------- #
#  Пост-обработка снимка: контуры, тон, растр
# --------------------------------------------------------------------------- #
def _shift(a: np.ndarray, dy: int, dx: int, fill=0) -> np.ndarray:
    """Сдвиг массива без заворота краёв (пустые поля заполняются fill)."""
    out = np.full_like(a, fill)
    h, w = a.shape[:2]
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    yd0, yd1 = max(0, -dy), min(h, h - dy)
    xd0, xd1 = max(0, -dx), min(w, w - dx)
    if ys0 < ys1 and xs0 < xs1:
        out[yd0:yd1, xd0:xd1] = a[ys0:ys1, xs0:xs1]
    return out


_DIRS = ((1, 0), (0, 1), (1, 1), (1, -1))


def _edge_mask(z: np.ndarray, valid: np.ndarray, nrm: np.ndarray,
               ids: np.ndarray, style: dict,
               seam_ids: np.ndarray | None = None) -> np.ndarray:
    """Где рисовать контур: силуэт, перепад глубины, излом, стык деталей."""
    h, w = z.shape
    edge = np.zeros((h, w), dtype=bool)
    # Глубина в буфере отсчитывается от центра сцены и потому проходит через
    # ноль — относительный перепад «делить на глубину» там взрывается и красит
    # контуром всю модель. Берём размах глубины по кадру: порог style["depth"]
    # — это доля этого размаха.
    if valid.any():
        vals = z[valid]
        zmin = float(vals.min())
        span = max(float(vals.max()) - zmin, 1e-6)
    else:
        zmin, span = 0.0, 1.0
    safe_z = np.where(valid, z - zmin, 0.0)
    crease_cos = math.cos(math.radians(float(style["crease"])))
    depth_k = float(style["depth"])
    inner = bool(style["inner"])
    seams = bool(style["seams"]) and inner
    seam_src = ids if seam_ids is None else seam_ids
    # 1) силуэт — граница маски по всем восьми соседям: линия замкнутая,
    # без «штрихов» и разрывов, как у Line Art в Blender
    inner_ok = valid.copy()
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1),
                   (1, 1), (1, -1), (-1, 1), (-1, -1)):
        inner_ok &= _shift(valid, dy, dx, False)
    edge |= valid & ~inner_ok

    for dy, dx in _DIRS:
        zb = _shift(safe_z, dy, dx)
        vb = _shift(valid, dy, dx, False)
        both = valid & vb
        if not both.any():
            continue
        rel = np.abs(safe_z - zb) / span
        jump = both & (rel > depth_k)
        edge |= jump
        if not inner:
            continue
        nb = np.stack([_shift(nrm[:, :, i], dy, dx) for i in range(3)], axis=2)
        dot = np.einsum("ijk,ijk->ij", nrm, nb)
        crease = both & (dot < crease_cos) & ~jump
        edge |= crease
        if seams:
            ib = _shift(seam_src, dy, dx, -1)
            edge |= both & (seam_src != ib)
    # края кадра не считаем контуром
    edge[0, :] = edge[-1, :] = False
    edge[:, 0] = edge[:, -1] = False
    return edge


def _dilate(mask: np.ndarray, radius: float) -> np.ndarray:
    """Утолщает линии до нужной толщины (диск заданного радиуса)."""
    r = int(math.ceil(radius + 1e-6))
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if not (dy or dx):
                continue
            if math.hypot(dx, dy) > radius + 0.15:
                continue
            out |= _shift(mask, dy, dx, False)
    return out


def _soften(mask: np.ndarray) -> np.ndarray:
    """Сглаживает маску контура: линия перестаёт быть «лесенкой»."""
    m = mask.astype(np.float32)
    acc = np.zeros_like(m)
    weight = 0.0
    for dy, dx, k in ((0, 0, 4.0), (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                      (1, 1, 0.7), (1, -1, 0.7), (-1, 1, 0.7), (-1, -1, 0.7)):
        acc += _shift(m, dy, dx) * k
        weight += k
    return np.clip(acc / weight, 0.0, 1.0)


def _halftone(shape: tuple[int, int], cell: float, darkness: np.ndarray) -> np.ndarray:
    """Растр манги: точки на повёрнутой сетке, плотность от «темноты».

    Возвращает 1 там, где должна быть краска, 0 — где бумага.
    """
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = math.radians(30.0)
    ca, sa = math.cos(ang), math.sin(ang)
    cell = max(float(cell), 1.0)
    u = (xx * ca + yy * sa) / cell
    v = (-xx * sa + yy * ca) / cell
    fu = np.mod(u, 1.0) - 0.5
    fv = np.mod(v, 1.0) - 0.5
    r = np.hypot(fu, fv)
    rad = 0.60 * np.sqrt(np.clip(darkness, 0.0, 1.0))
    dots = (r <= rad).astype(np.float32)
    # чуть «подмешиваем» тон, чтобы растр не рябил на мелких деталях
    return np.clip(dots * 0.92 + np.clip(darkness, 0, 1) * 0.08, 0.0, 1.0)


def _paper_grain(shape: tuple[int, int], strength: float, seed: int = 7) -> np.ndarray:
    """Зерно бумаги: мелкий шум + редкие волокна. 1 — чистая бумага."""
    if strength <= 0.001:
        return np.ones(shape, dtype=np.float32)
    h, w = shape
    rng = np.random.default_rng(seed)
    # мелкое зерно — по строкам/столбцам шум дешевле, чем на весь кадр
    grain = rng.normal(0.0, 1.0, size=(h, w // 2 + 1)).astype(np.float32)
    grain = np.repeat(grain, 2, axis=1)[:, :w]
    grain = 0.5 * grain + 0.25 * (np.roll(grain, 1, axis=0) + np.roll(grain, 1, axis=1))
    # волокна: редкие светлые и тёмные полосы под углом
    fib = np.zeros((h, w), dtype=np.float32)
    for _ in range(max(4, (h * w) // 90000)):
        y0 = int(rng.integers(0, h))
        x0 = int(rng.integers(0, w))
        length = int(rng.integers(max(8, w // 12), max(16, w // 3)))
        thick = int(rng.integers(1, 3))
        dy = int(rng.integers(-2, 3))
        sign = 1.0 if rng.random() > 0.5 else -1.0
        for i in range(length):
            y = (y0 + (dy * i) // max(1, length // 4)) % h
            x = (x0 + i) % w
            fib[y:min(h, y + thick), x:min(w, x + 1)] += sign * 0.35
    fib = np.clip(fib, -1, 1)
    # складываем и переводим в множитель яркости
    relief = 0.55 * grain + 0.45 * fib
    return np.clip(1.0 + relief * 0.06 * strength, 0.90, 1.06).astype(np.float32)


def _hatch_mask(shape: tuple[int, int], darkness: np.ndarray, angle_deg: float,
                step: float, strength: float) -> np.ndarray:
    """Карандашная штриховка: тонкие линии под углом, плотность — от тени.

    Возвращает долю краски 0…1 на пиксель (линии мягкие, «карандашом»).
    """
    if strength <= 0.001:
        return np.zeros(shape, dtype=np.float32)
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ang = math.radians(float(angle_deg))
    ca, sa = math.cos(ang), math.sin(ang)
    # координата поперёк штрихов
    u = (xx * ca + yy * sa) / max(step, 2.0)
    frac = np.mod(u, 1.0)
    # линия — узкая полоска в середине периода, мягкий карандашный край
    line_w = 0.34
    line = np.clip(1.0 - np.abs(frac - 0.5) / (line_w * 0.5), 0.0, 1.0)
    line = line ** 0.55
    # плотность: в тени штрихи есть, на свету — почти нет
    dark = np.clip(darkness, 0.0, 1.0)
    gate = np.clip((dark - 0.06) / 0.42, 0.0, 1.0)
    # «двойная штриховка» в глубокой тени: второй слой поперёк
    cross = np.zeros_like(line)
    if strength > 0.55:
        u2 = (xx * math.cos(ang + 1.15) + yy * math.sin(ang + 1.15)) / max(step * 1.35, 2.0)
        f2 = np.mod(u2, 1.0)
        cross_line = np.clip(1.0 - np.abs(f2 - 0.5) / (line_w * 0.5), 0.0, 1.0) ** 0.7
        cross = cross_line * np.clip((dark - 0.50) / 0.45, 0.0, 1.0) * (strength - 0.55) / 0.45
    return np.clip(np.maximum(line * gate, cross) * strength, 0.0, 1.0).astype(np.float32)


def _luma(img: np.ndarray) -> np.ndarray:
    return img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114


def apply_style(img: np.ndarray, z: np.ndarray | None = None,
                normals: np.ndarray | None = None, ids: np.ndarray | None = None,
                emissive: np.ndarray | None = None, style: dict | None = None,
                ss: int = 1, groups: np.ndarray | None = None,
                mats: np.ndarray | None = None) -> np.ndarray:
    """Накладывает стиль на готовый кадр.

    ``groups`` и ``mats`` — номер группы и материала на пиксель: по ним
    режим ``lines=группы/материалы`` решает, где кончается «своё» и
    начинается «чужое».

    ``img`` — HxWx3 float 0…1, ``z`` — глубина (view depth), ``normals`` —
    мировые нормали, ``ids`` — номер объекта на пиксель, ``emissive`` — маска
    светящихся поверхностей (их не тонируем и не растрируем).
    """
    st = normalize_style(style)
    if st["mode"] == "выкл":
        return img
    out = np.array(img, dtype=np.float32, copy=True)
    h, w = out.shape[:2]
    if z is None:
        z = np.full((h, w), np.nan)
    valid = np.isfinite(z)
    if normals is None:
        normals = np.zeros((h, w, 3), dtype=np.float32)
    if ids is None:
        ids = np.zeros((h, w), dtype=np.int32)
    if emissive is None:
        emissive = np.zeros((h, w), dtype=bool)
    else:
        emissive = np.asarray(emissive, dtype=bool)

    paper = None
    if st.get("paper"):
        paper = np.array(color_to_float_rgb(st["paper"]), dtype=np.float32)
        out[~valid] = paper
    ink = np.array(color_to_float_rgb(st["color"]), dtype=np.float32)
    # зерно бумаги: живой лист, а не заливка. Считаем один раз на кадр.
    grain = None
    if float(st.get("paper_tex") or 0) > 0.001:
        grain = _paper_grain((h, w), float(st["paper_tex"]))

    body = valid & ~emissive
    # 1) плоская заливка (стиль «линия»): остаётся только контур
    if not st["shade"]:
        if paper is not None:
            out[body] = paper
        else:
            lum = _luma(out)
            out[body] = lum[body][:, None] * 0.92 + 0.04

    # 2) ступени тона (cel shading). Цвет не «пересвечиваем»: берём оттенок
    # пикселя и приглушаем его ступенями, поэтому синяя ваза остаётся синей,
    # а не превращается в серые полосы.
    steps = int(st["toon"])
    if steps >= 2 and st["mode"] != "манга":
        lum = _luma(out)
        if body.any():
            vals = lum[body]
            lo = float(np.percentile(vals, 3))
            hi = float(np.percentile(vals, 98))
        else:
            lo, hi = 0.0, 1.0
        t = np.clip((lum - lo) / max(hi - lo, 1e-4), 0.0, 1.0)
        # Мягкое квантование: ступени видны, но переход — узкая полоска,
        # а не «плывущий» градиент. Ступеней ровно `steps` от тени к свету.
        q = np.clip(t * (steps - 1), 0.0, steps - 1)
        base_q = np.floor(q)
        frac = q - base_q
        soft = np.clip((frac - 0.95) / 0.05, 0.0, 1.0)
        tq = (base_q + soft) / (steps - 1)
        # Ступенчатая яркость: внутри ступени тон ровный (это и есть cel),
        # а оттенок берём у пикселя — синяя ваза остаётся синей.
        target = lo + tq * (hi - lo)
        # ступени должны читаться: растягиваем разброс от середины диапазона
        mid = 0.5 * (lo + hi)
        target = np.clip(mid + (target - mid) * 1.9, 0.0, 1.0)
        k = np.clip(target / np.maximum(lum, 1e-3), 0.0, 3.0)
        # очень яркое (блик) подтягиваем к белому — «стеклянный» блик аниме
        spec = np.clip((t - 0.93) / 0.07, 0.0, 1.0) * 0.5
        cel = np.clip(out * k[..., None], 0.0, 1.0)
        # аниме любит насыщенный цвет: слегка поднимаем разницу каналов
        gray = _luma(cel)[..., None]
        cel = np.clip(gray + (cel - gray) * 1.32, 0.0, 1.0)
        cel = cel * (1.0 - spec[..., None]) + spec[..., None]
        out = np.where(body[..., None], cel, out)

    # 3) манга: как в настоящей манге — бумага, серый тон точками, чёрная заливка
    if st["mode"] == "манга" and st["shade"]:
        lum = np.clip(_luma(out), 0.0, 1.0)
        base = (paper if paper is not None else np.array([1.0, 1.0, 1.0], np.float32))
        if body.any():
            vals = lum[body]
            white = float(np.percentile(vals, 88))     # ближняя к свету часть — бумага
            dark = float(np.percentile(vals, 12))      # самая тёмная — заливка
        else:
            white, dark = 0.85, 0.2
        white = max(white, dark + 0.05)
        t = np.clip((lum - dark) / (white - dark), 0.0, 1.0)
        t = np.where(body, t, 1.0)
        # Четыре ступени, как в настоящей манге: бумага, лёгкий тон,
        # плотный тон и сплошная чёрная заливка — только в самой тени.
        tone = float(st["tone"])
        levels = np.select([t > 0.72, t > 0.48, t > 0.22],
                           [0.0, 0.35, 0.70], default=0.90)
        dots = _halftone((h, w), 7.2 * max(1, ss), levels)
        screen = base[None, None, :] * (1.0 - dots[..., None]) + ink * dots[..., None]
        # сплошная заливка — только в настоящей черноте (глубокий проём, зрачок)
        deep = np.broadcast_to(_luma(out)[..., None] < 0.14, out.shape)
        screen = np.where(deep, np.broadcast_to(ink, out.shape), screen)
        if tone <= 0.001:
            # без растра — чистые ступени серого
            gray = np.clip(1.0 - levels * 0.92, 0.0, 1.0)[..., None]
            screen = base[None, None, :] * gray + ink[None, None, :] * (1.0 - gray)
        out = np.where(body[..., None], screen, out)
        # светящееся оставляем светлым: в манге это «блик»
        if emissive.any():
            out[emissive] = np.array([1.0, 1.0, 1.0], np.float32)

    # 4) комикс: точки в тенях поверх цвета
    if st["mode"] == "комикс" and st["tone"] > 0 and st["shade"]:
        lum = np.clip(_luma(out), 0.0, 1.0)
        dark = np.clip((0.72 - lum) / 0.72, 0.0, 1.0)
        dots = _halftone((h, w), 6.0 * max(1, ss), dark)
        factor = 1.0 - float(st["tone"]) * 0.55 * dark * (1.0 - dots)
        out = np.where(body[..., None], out * factor[..., None], out)

    # 4.5) штриховка карандашом: слой поверх тона, только по телу
    if float(st.get("hatch") or 0) > 0.001 and st["shade"]:
        lum = np.clip(_luma(out), 0.0, 1.0)
        # «темнота» — от общей яркости; в манге удобнее считать от ступеней
        dark = np.clip((0.80 - lum) / 0.72, 0.0, 1.0)
        lines = _hatch_mask((h, w), dark, float(st.get("hatch_angle") or 45.0),
                            float(st.get("hatch_step") or 8.0),
                            float(st.get("hatch") or 0.0))
        lines = np.where(body, lines, 0.0)
        # штрих не должен перекрывать светодиоды
        lines = np.where(emissive, lines * 0.15, lines)
        out = out * (1.0 - lines[..., None]) + ink[None, None, :] * lines[..., None]

    # 4.6) режим «скетч»: мягкая бумага и лёгкая пастель вместо чистого цвета
    if st["mode"] == "скетч" and st["shade"]:
        gray = _luma(out)[..., None]
        out = np.where(body[..., None], np.clip(gray * 0.62 + out * 0.42, 0, 1), out)

    # 5) контуры
    if st["line"] > 0:
        seam_ids = ids
        mode_lines = st.get("lines") or "все"
        if mode_lines == "группы" and groups is not None:
            seam_ids = np.asarray(groups, dtype=np.int32)
        elif mode_lines == "материалы" and mats is not None:
            seam_ids = np.asarray(mats, dtype=np.int32)
        edge = _edge_mask(z, valid, normals, ids, st, seam_ids)
        radius = float(st["line"]) * max(1, ss) * 0.5
        if radius > 0.2:
            edge = _dilate(edge, radius)
        mask = _soften(edge)
        # контур не должен закрывать светодиоды целиком
        mask = np.where(emissive, mask * 0.35, mask)
        out = out * (1.0 - mask[..., None]) + ink[None, None, :] * mask[..., None]

    # 6) зерно бумаги поверх всего: и фон, и деталь лежат на одном листе
    if grain is not None:
        out = out * grain[..., None]

    return np.clip(out, 0.0, 1.0)
