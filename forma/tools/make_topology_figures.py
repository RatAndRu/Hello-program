#!/usr/bin/env python3
"""Генератор SVG-схем для учебного сайта по топологии.

    python3 forma/tools/make_topology_figures.py          # записать SVG
    python3 forma/tools/make_topology_figures.py --sheet  # + контактный лист PNG

Схемы рисуются кодом намеренно: каждое «плохо» и каждое «лечение» — это
конкретная сетка с конкретными вершинами, полюсами и рёбрами, а не картинка
из интернета. Поэтому тексту сайта и рисункам можно верить одинаково.

Куда пишет: forma/topology-course/assets/fig/*.svg
Для --sheet нужен resvg-py (pip install resvg-py) — получается один PNG
со всеми схемами, чтобы глазами проверить результат.
"""

from __future__ import annotations

import argparse
import html
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "topology-course" / "assets" / "fig"

# --------------------------------------------------------------------------- #
#  Палитра и общий каркас
# --------------------------------------------------------------------------- #

BAD = "#d1495b"       # ошибка / «так нельзя»
GOOD = "#2a9d8f"      # норма / «так лечим»
WARN = "#e09f3e"      # предупреждение
INK = "#2b2a27"
MUTED = "#8a8478"
GRID = "#a9a294"
GRID_SOFT = "#cdc6b9"
PAPER = "#fbfaf6"
FILL = "#efe9dc"

STYLE = f"""
.w{{fill:none;stroke:{GRID};stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}}
.ws{{fill:none;stroke:{GRID_SOFT};stroke-width:1.2;stroke-linejoin:round}}
.wb{{fill:none;stroke:{BAD};stroke-width:2.2;stroke-linejoin:round;stroke-linecap:round}}
.wg{{fill:none;stroke:{GOOD};stroke-width:2.2;stroke-linejoin:round;stroke-linecap:round}}
.wd{{fill:none;stroke:{MUTED};stroke-width:1.2;stroke-dasharray:4 4}}
.fb{{fill:{BAD};fill-opacity:.16;stroke:{BAD};stroke-width:2}}
.fg{{fill:{GOOD};fill-opacity:.14;stroke:{GOOD};stroke-width:2}}
.fn{{fill:{FILL};fill-opacity:.85;stroke:{GRID};stroke-width:1.5}}
.fs{{fill:{FILL};fill-opacity:.45;stroke:{GRID_SOFT};stroke-width:1.2}}
.dot{{fill:{INK}}}
.pb{{fill:{BAD};stroke:{PAPER};stroke-width:1.5}}
.pg{{fill:{GOOD};stroke:{PAPER};stroke-width:1.5}}
.pw{{fill:{WARN};stroke:{PAPER};stroke-width:1.5}}

.tb{{font-family:'DejaVu Sans',sans-serif;font-size:10px;fill:{BAD};font-weight:bold}}
.tg{{font-family:'DejaVu Sans',sans-serif;font-size:10px;fill:{GOOD};font-weight:bold}}
.ti{{font-family:'DejaVu Sans',sans-serif;font-size:10px;fill:{INK}}}
.arrow{{fill:none;stroke:{INK};stroke-width:1.3}}
.arw{{fill:{INK}}}
"""


def f(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


class Fig:
    def __init__(self, w: int = 320, h: int = 210, badge: str | None = None,
                 badge_kind: str = "bad"):
        self.w, self.h = w, h
        self.el: list[str] = []
        if badge:
            cls = "fb" if badge_kind == "bad" else "fg"
            st = "tb" if badge_kind == "bad" else "tg"
            self.el.append(f'<rect x="8" y="8" rx="6" width="72" height="19" class="{cls}"/>')
            self.el.append(f'<text x="44" y="21" text-anchor="middle" class="{st}">{badge}</text>')

    # --- примитивы ---------------------------------------------------------
    def raw(self, s: str) -> "Fig":
        self.el.append(s)
        return self

    def line(self, x1, y1, x2, y2, cls="w") -> "Fig":
        return self.raw(f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" '
                        f'y2="{f(y2)}" class="{cls}"/>')

    def pl(self, pts, cls="w", close=False) -> "Fig":
        d = "M " + " L ".join(f"{f(x)} {f(y)}" for x, y in pts)
        if close:
            d += " Z"
        return self.raw(f'<path d="{d}" class="{cls}"/>')

    def poly(self, pts, cls="fn") -> "Fig":
        return self.pl(pts, cls=cls, close=True)

    def circle(self, x, y, r, cls="dot") -> "Fig":
        return self.raw(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" class="{cls}"/>')

    def text(self, x, y, s, cls="t", anchor="start") -> "Fig":
        return self.raw(f'<text x="{f(x)}" y="{f(y)}" class="{cls}" '
                        f'text-anchor="{anchor}">{html.escape(s)}</text>')

    def arrow(self, x1, y1, x2, y2, cls="arrow") -> "Fig":
        ang = math.atan2(y2 - y1, x2 - x1)
        a = 6
        p1 = (x2 - a * math.cos(ang - 0.4), y2 - a * math.sin(ang - 0.4))
        p2 = (x2 - a * math.cos(ang + 0.4), y2 - a * math.sin(ang + 0.4))
        self.line(x1, y1, x2, y2, cls)
        return self.poly([(x2, y2), p1, p2], cls="arw")

    def arc(self, cx, cy, r, a0, a1, cls="w") -> "Fig":
        x0, y0 = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
        x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
        large = 1 if abs(a1 - a0) > 180 else 0
        sweep = 1 if a1 > a0 else 0
        return self.raw(f'<path d="M {f(x0)} {f(y0)} A {f(r)} {f(r)} 0 {large} {sweep} '
                        f'{f(x1)} {f(y1)}" class="{cls}"/>')

    def body(self) -> str:
        return "".join(self.el)

    def svg(self) -> str:
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
                f'height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
                f'role="img">')
        return (head + f"<style>{STYLE}</style>"
                + f'<rect width="{self.w}" height="{self.h}" fill="{PAPER}"/>'
                + self.body() + "</svg>")


# --------------------------------------------------------------------------- #
#  Общие построители сеток
# --------------------------------------------------------------------------- #

def grid_quad(fig: Fig, x, y, w, h, nx, ny, cls="w", dots=False,
              dot_r=2.0, dot_cls="dot") -> list[list[tuple]]:
    """Прямоугольная квадовая решётка, возвращает координаты вершин."""
    pts = [[(x + i * w / nx, y + j * h / ny) for i in range(nx + 1)] for j in range(ny + 1)]
    for j in range(ny + 1):
        fig.pl([pts[j][i] for i in range(nx + 1)], cls=cls)
    for i in range(nx + 1):
        fig.pl([pts[j][i] for j in range(ny + 1)], cls=cls)
    if dots:
        for row in pts:
            for px, py in row:
                fig.circle(px, py, dot_r, dot_cls)
    return pts


def caption(fig: Fig, *lines: str, cls: str = "ti", y0: float | None = None,
            x: float = 10) -> Fig:
    """Подпись внизу схемы. Строки короткие — иначе выйдут за границу."""
    y = y0 if y0 is not None else fig.h - 10 - 14 * (len(lines) - 1)
    for i, line in enumerate(lines):
        fig.text(x, y + i * 14, line, cls)
    return fig


def bent_tube(x0=44.0, y0=62.0, run=76.0, radius=46.0, drop=44.0,
              sides=8, half=26.0):
    """Осевая линия гнутой трубы: горизонтальный участок, четверть дуги,
    вертикальный участок. Возвращает список станций (центр, нормаль, t),
    где t — доля пути (0…1), и функции для рисования."""
    pts = []
    for i in range(4):
        pts.append(((x0 + run * i / 3, y0), (0.0, 1.0), i / 3 * 0.38))
    cx, cy = x0 + run, y0 + radius
    for i in range(1, 6):
        a = math.radians(-90 + 90 * i / 5)
        pts.append(((cx + radius * math.cos(a), cy + radius * math.sin(a)),
                    (math.cos(a), math.sin(a)), 0.38 + 0.4 * i / 5))
    for i in range(1, 4):
        pts.append(((cx, cy + drop * i / 3), (1.0, 0.0), 0.78 + 0.22 * i / 3))
    return pts, half, sides


def draw_tube(fig: Fig, stations, half, sides, cls="w", rings: list[float] | None = None,
              tilt: float = 0.0, dots: bool = False) -> None:
    """Рисует силуэт трубы и поперечные петли в указанных долях пути."""
    left, right = [], []
    for (p, n, t) in stations:
        dx, dy = half * n[0], half * n[1]
        left.append((p[0] - dx, p[1] - dy))
        right.append((p[0] + dx, p[1] + dy))
    fig.pl(left, cls)
    fig.pl(right, cls)
    for (p, n, t) in stations:
        if rings is None:
            continue
        if not any(abs(t - r) < 1e-6 for r in rings):
            continue
        a = math.radians(tilt)
        nx = n[0] * math.cos(a) - n[1] * math.sin(a)
        ny = n[0] * math.sin(a) + n[1] * math.cos(a)
        fig.line(p[0] - half * nx, p[1] - half * ny,
                 p[0] + half * nx, p[1] + half * ny, cls)
        if dots:
            fig.circle(p[0] - half * nx, p[1] - half * ny, 2.4, "dot")
            fig.circle(p[0] + half * nx, p[1] + half * ny, 2.4, "dot")
    # продольные рёбра: несколько линий вдоль силуэта
    for k in (0.28, 0.5, 0.72):
        fig.pl([(l[0] * (1 - k) + r[0] * k, l[1] * (1 - k) + r[1] * k)
                for l, r in zip(left, right)], "ws")


# --------------------------------------------------------------------------- #
#  Схемы
# --------------------------------------------------------------------------- #

def fig_valence() -> Fig:
    """Валентность: 3, 4, 5, 6 рёбер в вершине."""
    fig = Fig(340, 140)
    cases = [(3, BAD, "3 — полюс"), (4, GOOD, "4 — норма"), (5, WARN, "5 — полюс"),
             (6, BAD, "6+ — звезда")]
    for i, (n, color, label) in enumerate(cases):
        cx, cy = 48 + i * 82, 48
        cls = "wg" if color == GOOD else ("wb" if color == BAD else "w")
        for k in range(n):
            a = math.radians(-90 + 360 * k / n)
            fig.line(cx, cy, cx + 24 * math.cos(a), cy + 24 * math.sin(a), cls)
        fig.circle(cx, cy, 3.4, "pg" if color == GOOD else "pb")
        fig.text(cx, cy + 42, label, "tg" if color == GOOD else "tb", "middle")
    caption(fig, "Квад регулярен при 4, треугольник — при 6.")
    return fig


def fig_loop_ring() -> Fig:
    """Петля и кольцо на одной сетке."""
    fig = Fig(320, 160)
    grid_quad(fig, 40, 34, 240, 80, 6, 3)
    fig.raw('<path d="M 60 34 L 220 34" class="wg"/>')
    fig.raw('<path d="M 60 114 L 220 114" class="wb"/>')
    fig.text(60, 28, "петля", "tg")
    fig.text(60, 132, "кольцо", "tb")
    caption(fig, "Петля — по рёбрам, кольцо — полоса граней между ними.")
    return fig


def fig_welded_body() -> Fig:
    """Итоговая схема: тело из согласованных частей."""
    fig = Fig(320, 190)
    fig.poly([(36, 56), (140, 56), (140, 148), (36, 148)], "fn")
    fig.pl([(36, 56), (140, 56), (140, 148), (36, 148)], "w", close=True)
    fig.poly([(140, 56), (252, 78), (252, 148), (140, 148)], "fn")
    fig.pl([(140, 56), (252, 78), (252, 148), (140, 148)], "w", close=True)
    for x in (62, 88, 114, 175, 210, 236):
        fig.line(x, 56 if x < 140 else 70, x, 148, "ws")
    fig.circle(140, 56, 4.6, "pg")
    caption(fig, "Замкнутое тело: обход согласован, 2 грани на ребро,",
            "полюса на плоском, острые рёбра поддержаны.")
    return fig


def fig_pole_bend(bad: bool) -> Fig:
    """Полюс в зоне изгиба (плохо) и вынесенный на плоское (норма)."""
    fig = Fig(320, 200, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    stations, half, sides = bent_tube()
    rings = [s[2] for s in stations][1:-1]
    draw_tube(fig, stations, half, sides, "w", rings=None)
    # поперечные петли: в изгибе и на прямых участках
    for (p, n, t) in stations:
        fig.line(p[0] - half * n[0], p[1] - half * n[1],
                 p[0] + half * n[0], p[1] + half * n[1], "w")
    if bad:
        px, py = stations[6][0]
        fig.circle(px, py, 6, "pb")
        fig.arrow(px + 22, py + 34, px + 4, py + 6)
        fig.text(px + 26, py + 40, "полюс на изгибе", "tb")
        caption(fig, "Пять рёбер сходятся на скруглении:", "при SubD здесь ямка.")
    else:
        px, py = stations[1][0]
        fig.circle(px, py, 6, "pg")
        fig.arrow(px + 12, py - 34, px + 4, py - 7)
        fig.text(px + 16, py - 38, "полюс на плоском", "tg")
        caption(fig, "Ребро уведено на прямой участок —", "щипка в изгибе нет.")
    return fig


def fig_single_loop(bad: bool) -> Fig:
    """Одна петля в суставе против четырёх."""
    fig = Fig(320, 200, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    stations, half, sides = bent_tube(drop=40)
    cls = "wb" if bad else "wg"
    draw_tube(fig, stations, half, sides, cls, rings=None)
    bend = [s for s in stations if 0.4 < s[2] < 0.78]
    keep = [bend[len(bend) // 2]] if bad else bend
    keep = keep + [s for s in stations if s[2] in (0.0, 0.19, 1.0)]
    for (p, n, t) in keep:
        fig.line(p[0] - half * n[0], p[1] - half * n[1],
                 p[0] + half * n[0], p[1] + half * n[1], cls)
    if bad:
        caption(fig, "Весь изгиб на одном ряду граней:", "он складывается в ноль.")
    else:
        caption(fig, "Изгиб разложен на несколько петель:", "объём сохраняется.")
    return fig


def fig_ngon(bad: bool) -> Fig:
    """N-гон на скруглении и его разбор."""
    fig = Fig(320, 190, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    cx, cy, r = 130, 96, 56
    if bad:
        pts = [(cx + r * math.cos(math.radians(-90 + 60 * k)),
                cy + r * math.sin(math.radians(-90 + 60 * k))) for k in range(6)]
        fig.poly(pts, "fb")
        for p in pts:
            fig.line(cx, cy, p[0], p[1], "wb")
        fig.circle(cx, cy, 5.5, "pb")
        fig.text(cx + 66, cy - 40, "один n-гон", "tb")
        fig.text(cx + 66, cy - 24, "и звезда 6", "tb")
        caption(fig, "N-гон под SubD непредсказуем,", "а веер из центра даёт иглы.")
    else:
        fig.raw(f'<circle cx="{cx}" cy="{cy}" r="{r}" class="wg"/>')
        for k in range(6):
            a = math.radians(-90 + 60 * k)
            fig.circle(cx + r * math.cos(a), cy + r * math.sin(a), 4.2, "pg")
        for rr in (16, 36):
            fig.raw(f'<circle cx="{cx}" cy="{cy}" r="{rr}" class="wg"/>')
        for k in range(6):
            a = math.radians(-90 + 60 * k + 30)
            fig.line(cx + 16 * math.cos(a), cy + 16 * math.sin(a),
                     cx + r * math.cos(a), cy + r * math.sin(a), "wg")
        fig.circle(cx, cy, 4.2, "pg")
        fig.text(cx + 66, cy - 40, "кольца и полюса", "tg")
        fig.text(cx + 66, cy - 24, "парами, без веера", "tg")
        caption(fig, "N-гон разобран: кольца, полюса по кругу,", "плотность ровная.")
    return fig


def fig_slivers(bad: bool) -> Fig:
    """Иглы вдоль скругления и нормальная триангуляция."""
    fig = Fig(320, 200, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    xs = [40 + i * 48 for i in range(6)]
    top = [(x, 44 + (10 if i % 2 else 0)) for i, x in enumerate(xs)]
    bot = [(x, 84 + (10 if i % 2 else 0)) for i, x in enumerate(xs)]
    fig.pl(top, "w")
    fig.pl(bot, "w")
    if bad:
        for i in range(5):
            if i % 2:
                fig.line(*top[i], *bot[i + 1], "wb")
            else:
                fig.line(*bot[i], *top[i + 1], "wb")
        fig.text(40, 120, "длинные стороны идут вдоль скругления —", "tb")
        fig.text(40, 136, "нормали тянутся полосами", "tb")
        caption(fig, "Признак: угол < 3° и сосед в другой плоскости.")
    else:
        mid = [(x, 64 + (10 if i % 2 else 0)) for i, x in enumerate(xs)]
        fig.pl(mid, "wg")
        for i in range(5):
            for band in ((top, mid), (mid, bot)):
                a, b = band
                fig.pl([a[i], a[i + 1], b[i + 1], b[i]], "wg", close=True)
        fig.text(40, 120, "добавлен ряд вершин —", "tg")
        fig.text(40, 136, "треугольники стали короткими", "tg")
        caption(fig, "У длинной тонкой детали добавляют сегменты вдоль оси.")
    return fig


def fig_density(bad: bool) -> Fig:
    """Плотность: рывок и плавный переход."""
    fig = Fig(320, 200, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    x0, x1, y0, y1 = 30, 290, 44, 108
    fig.line(x0, y0, x1, y0, "w")
    fig.line(x0, y1, x1, y1, "w")
    if bad:
        xs = [x0, x0 + 90, x0 + 160, x0 + 190, x0 + 210, x0 + 224, x0 + 235,
              x0 + 243, x0 + 250, x0 + 256, x0 + 261, x0 + 266, x0 + 272, x1]
    else:
        xs = [x0, x0 + 60, x0 + 115, x0 + 162, x0 + 201, x0 + 233, x0 + 260, x1]
    for xx in xs:
        fig.line(xx, y0, xx, y1, "wb" if bad else "wg")
    for xx in xs:
        fig.circle(xx, (y0 + y1) / 2, 2.4, "pb" if bad else "pg")
    if bad:
        fig.arrow(200, 140, 272, 140)
        fig.text(150, 160, "рывок плотности", "tb")
        caption(fig, "Под SubD даёт волну на ровной части поверхности.")
    else:
        fig.raw('<path d="M 30 148 Q 160 124 290 148" class="wg"/>')
        fig.text(96, 160, "шаг меняется плавно", "tg")
        caption(fig, "Переход через полюса: SubD даёт ровную поверхность.")
    return fig


def fig_support(bad: bool) -> Fig:
    """Острый край: что делает SubD без поддержки и с ней."""
    fig = Fig(320, 210, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    # вид сбоку на угол: контрольная сетка — ломаная, результат — кривая
    corner = [(64, 46), (64, 132), (232, 132)]
    fig.pl(corner, "wn" if False else "w")
    fig.line(64, 46, 64, 132, "wd")
    fig.line(64, 132, 232, 132, "wd")
    if bad:
        fig.raw('<path d="M 64 78 Q 84 128 118 132" class="wb"/>')
        fig.circle(64, 132, 4.6, "pb")
        fig.text(126, 58, "SubD без поддержки", "tb")
        fig.text(126, 74, "съедает угол", "tb")
        caption(fig, "Контур уходит внутрь: габарит «худеет»,", "фаска пропадает.")
    else:
        for dx in (10, 22):
            fig.line(64 + dx, 46, 64 + dx, 132, "wg")
            fig.line(64, 132 - dx, 232, 132 - dx, "wg")
        fig.raw('<path d="M 64 48 L 64 130 L 230 132" class="wg"/>')
        fig.text(126, 58, "две support loops", "tg")
        fig.text(126, 74, "край держится", "tg")
        caption(fig, "Петли ставят в 1–3 % габарита от края:", "ближе — жёстче.")
    return fig


def fig_diagonal(bad: bool) -> Fig:
    """Диагональный поток против поперечных петель."""
    fig = Fig(320, 200, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    stations, half, sides = bent_tube(run=64, radius=40, drop=38, half=24)
    cls = "wb" if bad else "wg"
    draw_tube(fig, stations, half, sides, cls, rings=None)
    tilt = 16.0 if bad else 0.0
    for (p, n, t) in stations[1:-1:2]:
        a = math.radians(tilt)
        nx = n[0] * math.cos(a) - n[1] * math.sin(a)
        ny = n[0] * math.sin(a) + n[1] * math.cos(a)
        fig.line(p[0] - half * nx, p[1] - half * ny,
                 p[0] + half * nx, p[1] + half * ny, cls)
    if bad:
        fig.text(196, 62, "петли под углом", "tb")
        fig.text(196, 78, "к форме и изгибу", "tb")
        caption(fig, "При сгибе грани «винтом» уходят в сторону,",
                "а нормали расходятся.")
    else:
        fig.text(196, 62, "петли поперёк изгиба", "tg")
        fig.text(196, 78, "и вдоль формы", "tg")
        caption(fig, "Грани остаются плоскими при любом сгибе,",
                "подразбиение предсказуемо.")
    return fig


def fig_winding(bad: bool) -> Fig:
    """Перевёрнутая грань и её лечение."""
    fig = Fig(320, 190, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    pts = grid_quad(fig, 44, 44, 232, 80, 4, 2, "w")
    q = [pts[0][1], pts[1][1], pts[1][2], pts[0][2]]
    fig.poly(q, "fb" if bad else "fg")
    # стрелка обхода
    x1, y1 = pts[0][1]
    x2, y2 = pts[1][1]
    x3, y3 = pts[1][2]
    x4, y4 = pts[0][2]
    fig.arrow(x1 + 6, y1 + 4, x2 - 6, y2 + 4)
    fig.arrow(x2 - 6, y2 + 4, x3 - 6, y3 - 4)
    fig.arrow(x3 - 6, y3 - 4, x4 + 6, y4 - 4)
    fig.arrow(x4 + 6, y4 - 4, x1 + 6, y1 + 4)
    if bad:
        fig.text(150, 32, "обход против соседей", "tb")
        caption(fig, "Нормали смотрят в разные стороны —", "тёмное пятно на ровном месте.")
    else:
        fig.text(150, 32, "обход как у всех", "tg")
        caption(fig, "Shift+N и сварка вершин закрепляют", "согласованный обход.")
    return fig


def fig_hole(bad: bool) -> Fig:
    fig = Fig(320, 190, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    fig.el.append(f'<rect x="40" y="40" width="240" height="86" class="fn"/>')
    pts = grid_quad(fig, 40, 40, 240, 86, 4, 2, "w")
    q = [pts[0][2], pts[1][2], pts[1][3], pts[0][3]]
    if bad:
        fig.raw(f'<path d="M {q[0][0]} {q[0][1]} L {q[1][0]} {q[1][1]} '
                f'L {q[2][0]} {q[2][1]} L {q[3][0]} {q[3][1]} Z" fill="{PAPER}" '
                f'stroke="{BAD}" stroke-width="2" stroke-dasharray="5 4"/>')
        fig.text(q[0][0] + 16, q[0][1] + 26, "грани нет", "tb")
        caption(fig, "Граничные рёбра: тело не замкнуто,", "внутренняя сторона видна.")
    else:
        fig.poly(q, "fg")
        fig.text(q[0][0] + 16, q[0][1] + 26, "Grid Fill", "tg")
        caption(fig, "F или Grid Fill по контуру; для чётного", "числа вершин — ровная решётка.")
    return fig


def fig_nonmanifold(bad: bool) -> Fig:
    fig = Fig(320, 200, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    if bad:
        # «пол» и «плавник», приклеенные к одному ребру
        floor = [(48, 118), (152, 96), (256, 118), (152, 140)]
        fig.poly(floor, "fs")
        fig.pl(floor, "w", close=True)
        fin = [(152, 96), (196, 44), (196, 74), (152, 140)]
        fig.poly(fin, "fb")
        fig.pl(fin, "w", close=True)
        fig.line(152, 96, 152, 140, "wb")
        fig.circle(152, 96, 5, "pb")
        fig.circle(152, 140, 5, "pb")
        fig.text(206, 96, "3 грани на ребре", "tb")
        caption(fig, "Непонятно, где внутри: не тело,", "а лист, приклеенный ребром.")
    else:
        fig.poly([(52, 58), (144, 58), (144, 134), (52, 134)], "fg")
        fig.pl([(52, 58), (144, 58), (144, 134), (52, 134)], "wg", close=True)
        fig.poly([(168, 58), (260, 58), (260, 134), (168, 134)], "fg")
        fig.pl([(168, 58), (260, 58), (260, 134), (168, 134)], "wg", close=True)
        fig.arrow(146, 96, 166, 96)
        caption(fig, "Только тело или два отдельных объекта;", "«лист ребром» — не решение.")
    return fig


def fig_duplicates(bad: bool) -> Fig:
    fig = Fig(320, 190, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    if bad:
        for dx in (0, 9):
            fig.pl([(64 + dx, 48), (152 + dx, 48), (152 + dx, 128), (64 + dx, 128)],
                   "wb", close=True)
        fig.circle(64, 48, 4.4, "pb")
        fig.circle(161, 48, 4.4, "pb")
        fig.text(176, 76, "вершины не слиты", "tb")
        fig.text(176, 92, "шов расходится", "tb")
        caption(fig, "Половинки держатся только на вид;", "при сгибе появляется щель.")
    else:
        fig.pl([(64, 48), (160, 48), (160, 128), (64, 128)], "wg", close=True)
        fig.circle(64, 48, 4.4, "pg")
        fig.circle(160, 48, 4.4, "pg")
        fig.text(176, 76, "M ▸ By Distance", "tg")
        fig.text(176, 92, "вершины слиты", "tg")
        caption(fig, "Сварка — первая кнопка при любой", "странной нормали.")
    return fig


def fig_tjunction(bad: bool) -> Fig:
    fig = Fig(320, 190, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    if bad:
        fig.el.append('<rect x="52" y="48" width="216" height="78" class="fs"/>')
        fig.pl([(52, 48), (260, 48), (260, 126), (52, 126)], "w", close=True)
        fig.line(156, 48, 156, 126, "wb")
        fig.circle(156, 87, 5, "pw")
        fig.text(52, 40, "вершина на ребре соседа", "tb")
        caption(fig, "T-стык: вершина не входит в грань —", "при деформации появляется щель.")
    else:
        fig.line(52, 48, 260, 48, "wg")
        fig.line(52, 126, 260, 126, "wg")
        fig.line(156, 48, 156, 126, "wg")
        fig.circle(156, 48, 4.6, "pg")
        fig.circle(156, 126, 4.6, "pg")
        fig.text(52, 40, "ребро разрезано по вершине", "tg")
        caption(fig, "J / Connect доводит новое ребро", "до вершины — стык закрыт.")
    return fig


def fig_sphere_pole(bad: bool) -> Fig:
    fig = Fig(320, 200, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    cx, cy, r = 122, 104, 62
    fig.raw(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{GRID}" '
            f'stroke-width="1.5"/>')
    if bad:
        for k in range(12):
            a = math.radians(360 * k / 12)
            fig.line(cx, cy - r, cx + r * math.cos(a), cy + r * math.sin(a) * 0.96, "wb")
        for rr in (0.42, 0.72):
            fig.raw(f'<ellipse cx="{cx}" cy="{cy}" rx="{r * rr:.1f}" '
                    f'ry="{r * rr * 0.5:.1f}" class="ws"/>')
        fig.circle(cx, cy - r, 6, "pb")
        fig.text(cx + 74, cy - r + 2, "12 рёбер", "tb")
        fig.text(cx + 74, cy - r + 18, "в одной точке", "tb")
        caption(fig, "Полюс UV-сферы: звезда, иглы у полюса", "и щипок при SubD.")
    else:
        for rr in (0.34, 0.6, 0.82, 0.97):
            fig.raw(f'<ellipse cx="{cx}" cy="{cy}" rx="{r * rr:.1f}" '
                    f'ry="{r * rr * 0.52:.1f}" fill="none" class="wg"/>')
        for k in range(8):
            a = math.radians(360 * k / 8)
            fig.line(cx + r * 0.34 * math.cos(a), cy + r * 0.34 * 0.52 * math.sin(a),
                     cx + r * 0.6 * math.cos(a), cy + r * 0.6 * 0.52 * math.sin(a), "wg")
            fig.line(cx + r * 0.6 * math.cos(a), cy + r * 0.6 * 0.52 * math.sin(a),
                     cx + r * 0.82 * math.cos(a), cy + r * 0.82 * 0.52 * math.sin(a), "wg")
            fig.line(cx + r * 0.82 * math.cos(a), cy + r * 0.82 * 0.52 * math.sin(a),
                     cx + r * 0.97 * math.cos(a), cy + r * 0.97 * 0.52 * math.sin(a), "wg")
        fig.circle(cx, cy, 4.6, "pg")
        fig.text(cx + 74, cy - 24, "полюс 4 на кольце", "tg")
        fig.text(cx + 74, cy - 8, "плотность ровная", "tg")
        caption(fig, "Кольца и полюса по кругу: сфера", "держит форму и подразбивается.")
    return fig


def fig_tris_deform(bad: bool) -> Fig:
    """Лестница из треугольников в суставе против квадов."""
    fig = Fig(320, 190, "ПЛОХО" if bad else "ЛЕЧЕНИЕ", "bad" if bad else "good")
    seg = [44, 100, 156, 212, 268]
    for y in (44, 68, 92, 116):
        fig.line(44, y, 268, y, "w")
    if bad:
        for i in range(4):
            for j in range(3):
                x0, x1 = seg[i], seg[i + 1]
                y0, y1 = 44 + j * 24, 44 + (j + 1) * 24
                if (i + j) % 2:
                    fig.line(x0, y0, x1, y1, "wb")
                else:
                    fig.line(x1, y0, x0, y1, "wb")
        fig.text(44, 138, "каждая грань разрезана по диагонали", "tb")
        caption(fig, "При сгибе диагонали ведут себя по-разному —", "«лестница».")
    else:
        for x in seg:
            fig.line(x, 44, x, 116, "wg")
        fig.text(44, 138, "квады, петли поперёк изгиба", "tg")
        caption(fig, "Сгиб распределяется по ряду петель,", "а не по диагоналям.")
    return fig


FIGURES = {
    # концептуальные
    "valence": fig_valence,
    "loop-ring": fig_loop_ring,
    "welded-body": fig_welded_body,
    # пары «плохо / лечение»
    "pole-bend": (fig_pole_bend, "pole-bend"),
    "single-loop": (fig_single_loop, "single-loop"),
    "ngon": (fig_ngon, "ngon"),
    "slivers": (fig_slivers, "slivers"),
    "density": (fig_density, "density"),
    "support": (fig_support, "support"),
    "diagonal": (fig_diagonal, "diagonal"),
    "winding": (fig_winding, "winding"),
    "hole": (fig_hole, "hole"),
    "nonmanifold": (fig_nonmanifold, "nonmanifold"),
    "duplicates": (fig_duplicates, "duplicates"),
    "tjunction": (fig_tjunction, "tjunction"),
    "sphere-pole": (fig_sphere_pole, "sphere-pole"),
    "tris-deform": (fig_tris_deform, "tris-deform"),
}

PAIRS = {
    "pole-bend": "Полюс в зоне изгиба",
    "single-loop": "Одна петля в суставе",
    "ngon": "N-гон на скруглении",
    "slivers": "Иглы вдоль скругления",
    "density": "Рывок плотности",
    "support": "SubD съедает острый край",
    "diagonal": "Диагональный поток",
    "winding": "Перевёрнутая грань",
    "hole": "Дырка в поверхности",
    "nonmanifold": "Лист ребром (non-manifold)",
    "duplicates": "Незаваренные вершины",
    "tjunction": "T-стык",
    "sphere-pole": "Полюс UV-сферы",
    "tris-deform": "Треугольники в суставе",
}


def build() -> dict[str, Fig]:
    figs: dict[str, Fig] = {}
    for name, spec in FIGURES.items():
        if isinstance(spec, tuple):
            fn, _ = spec
            figs[f"{name}-bad"] = fn(True)
            figs[f"{name}-good"] = fn(False)
        else:
            figs[name] = spec()
    return figs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SVG-схемы для сайта о топологии")
    ap.add_argument("--sheet", action="store_true",
                    help="собрать контактный лист PNG (нужен resvg-py)")
    ap.add_argument("--sheet-out", default="/tmp/topology-sheet.png")
    args = ap.parse_args(argv)
    figs = build()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fig in figs.items():
        (OUT / f"{name}.svg").write_text(fig.svg(), encoding="utf-8")
    print(f"{len(figs)} схем записано в {OUT.relative_to(ROOT)}")
    if args.sheet:
        try:
            import resvg_py
        except ImportError:
            print("Нет resvg-py: pip install resvg-py. Лист не собран.")
            return 0
        cols, cell_w, cell_h = 6, 344, 224
        rows = (len(figs) + cols - 1) // cols
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{cols * cell_w}" '
                 f'height="{rows * cell_h}"><style>{STYLE}</style>'
                 f'<rect width="100%" height="100%" fill="#ffffff"/>']
        for i, name in enumerate(sorted(figs)):
            cx = (i % cols) * cell_w + 2
            cy = (i // cols) * cell_h + 2
            fig = figs[name]
            parts.append(
                f'<g transform="translate({cx},{cy})">'
                f'<rect width="{fig.w}" height="{fig.h}" fill="{PAPER}" '
                f'stroke="#e6e0d2"/>{fig.body()}</g>')
        parts.append("</svg>")
        png = resvg_py.svg_to_bytes(svg_string="".join(parts),
                                    font_dirs=["/usr/share/fonts/truetype"],
                                    background="#ffffff")
        Path(args.sheet_out).write_bytes(png)
        print(f"лист: {args.sheet_out} ({len(figs)} шт., {cols}×{rows})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
