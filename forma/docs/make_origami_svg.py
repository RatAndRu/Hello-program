#!/usr/bin/env python3
"""Схемы к docs/origami_analysis.md.

Запуск: python forma/docs/make_origami_svg.py [--check]
Пишет четыре SVG в forma/docs/img/:
  origami_folds.svg        — двенадцать видов сгибов и что из них есть в движке
  origami_fold_unfold.svg  — «сложить → загладить → разогнуть» и таймлайн анимации
  origami_joints.svg       — соединения без клея и верёвки: геометрия и проверки
  origami_ai_pipeline.svg  — как просить ИИ придумать оригами: кто что делает

Все числа на схемах — из docs/origami_probe.py и docs/origami_analysis.md.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "img"
OUT.mkdir(exist_ok=True)

FONT = "font-family=\"DejaVu Sans, Segoe UI, Arial, sans-serif\""
INK = "#1f2933"
MUTED = "#6b7785"
BAD = "#c0392b"
GOOD = "#1e8449"
ACC = "#2b6cb0"
WARN = "#b7791f"
BG = "#ffffff"
LINE = "#d5dbe1"
SOFT = "#fcfdfe"
CHAR_W = 0.62

try:                                     # точная ширина строки по настоящему шрифту
    from PIL import ImageFont

    _FONTS = {False: "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              True: "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"}
    _CACHE: dict = {}

    def tw(s, size, bold=False):
        key = (size, bold)
        f = _CACHE.get(key)
        if f is None:
            f = _CACHE[key] = ImageFont.truetype(_FONTS[bold], int(round(size * 4)))
        return f.getlength(str(s)) / 4.0
except Exception:                        # PIL нет — грубая оценка
    def tw(s, size, bold=False):
        return len(str(s)) * size * CHAR_W

BOXES: list[tuple[str, float, float, float, float]] = []   # имя, x, y, w, h


def svg(w, h, body, title=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" {FONT}>\n<title>{title}</title>\n'
            f'<rect width="{w}" height="{h}" fill="{BG}"/>\n{body}\n</svg>\n')


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=13, color=INK, anchor="start", weight="normal"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')


def wrap(s, maxw, size, bold=False):
    lines, cur = [], ""
    for word in str(s).split():
        cand = (cur + " " + word).strip()
        if tw(cand, size, bold) <= maxw or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def para(x, y, s, maxw, size=12, color=INK, lh=None, bold=False):
    lh = lh or size * 1.4
    return [text(x, y + i * lh, ln, size, color, weight="bold" if bold else "normal")
            for i, ln in enumerate(wrap(s, maxw, size, bold))]


def path(pts, color=ACC, width=2.0, dash=None, close=False, fill="none"):
    d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + (" Z" if close else "")
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{width}"{da} '
            f'stroke-linejoin="round" stroke-linecap="round"/>')


def chip(x, y, label, color):
    w = 8.2 * len(label) + 16
    return (f'<rect x="{x:.1f}" y="{y - 12:.1f}" width="{w:.1f}" height="18" rx="9" '
            f'fill="{color}" opacity="0.12"/>'
            f'<rect x="{x:.1f}" y="{y - 12:.1f}" width="{w:.1f}" height="18" rx="9" '
            f'fill="none" stroke="{color}" stroke-width="0.9"/>'
            + text(x + w / 2, y + 1.5, label, 10.5, color, "middle", "bold"))


def arrow(x0, y0, x1, y1, color=INK, width=1.6, head=7):
    ang = math.atan2(y1 - y0, x1 - x0)
    bx, by = x1 - head * math.cos(ang), y1 - head * math.sin(ang)
    p1 = (bx - head * 0.5 * math.sin(ang), by + head * 0.5 * math.cos(ang))
    p2 = (bx + head * 0.5 * math.sin(ang), by - head * 0.5 * math.cos(ang))
    return (f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
            f'stroke="{color}" stroke-width="{width}"/>'
            + f'<polygon points="{x1:.1f},{y1:.1f} {p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}" '
              f'fill="{color}"/>')


def header(title, sub, w=1000):
    return [text(28, 42, title, 22, INK, weight="bold"),
            text(28, 68, sub, 13, MUTED),
            f'<line x1="28" y1="86" x2="{w - 28}" y2="86" stroke="{LINE}"/>']


# ============================================================ 1. СГИБЫ
def fig_folds():
    n0 = len(BOXES)
    W, H = 1000, 845
    body = header("Двенадцать видов сгибов: что движок умеет сегодня",
                  "слева — как сгиб выглядит с торца; справа — статус в ФОРМЕ (замеры: docs/origami_probe.py)")
    tiles = [
        ("Долина", GOOD, "есть", "сгиб angle=30…179, side=1",
         "valley"),
        ("Гора", GOOD, "есть", "тот же сгиб, side=−1 (переворот листа)", "mountain"),
        ("Плиссе", WARN, "частично", "сгиб parts=3…12 — только равные полотнища", "pleat"),
        ("Гармошка", GOOD, "есть", "fold_sheet parts / сгиб parts, один угол", "accordion"),
        ("Обратный внутрь", BAD, "нет", "нужен разворот слоя и новая линия", "reverse_in"),
        ("Обратный наружу", BAD, "нет", "то же, но слой выворачивается наружу", "reverse_out"),
        ("Сплющивание", BAD, "нет", "раскрыть карман и согнуть по двум линиям", "squash"),
        ("Лепесток", BAD, "нет", "два «уха» через общую линию", "petal"),
        ("Ухо кролика", BAD, "нет", "три луча из одной точки", "rabbit"),
        ("Утопление", BAD, "нет", "вершина уходит внутрь между слоями", "sink"),
        ("Кримп", BAD, "нет", "две встречные складки со сдвигом", "crimp"),
        ("Изогнутая складка", WARN, "частично", "складка bend= / drape, но не дуга по CP", "curved"),
    ]
    x0, y0, tw, th, gx, gy = 28, 104, 232, 214, 8, 10
    for i, (name, color, status, note, kind) in enumerate(tiles):
        col, row = i % 4, i // 4
        x = x0 + col * (tw + gx)
        y = y0 + row * (th + gy)
        BOXES.append((f"tile{i}", x, y, tw, th))
        body.append(f'<rect x="{x}" y="{y}" width="{tw}" height="{th}" rx="8" fill="{SOFT}" stroke="{LINE}"/>')
        body.append(f'<rect x="{x}" y="{y}" width="4" height="{th}" rx="2" fill="{color}"/>')
        body.append(text(x + 16, y + 28, name, 14, INK, weight="bold"))
        body.append(chip(x + 16, y + 48, status, color))
        body += para(x + 16, y + 76, note, tw - 36, 9.9, MUTED)
        icx, icy = x + tw / 2, y + 146
        body.append(f'<g transform="translate({icx:.1f},{icy:.1f}) scale(1.18) '
                    f'translate({-icx:.1f},{-icy:.1f})">')
        body += _fold_icon(icx, icy, kind)
        body.append('</g>')

    body += para(28, 786,
                 "«Только эти два» — не придирка: восемь из двенадцати сгибов физически остаются тем же "
                 "перегибом листа, но требуют нового слоя, новой линии и обратного хода. Замер: после сгиба "
                 "на 120° второй сгиб не построился ни в одном из 20 сочетаний направления и места линии.",
                 944, 12.2, INK)
    return svg(W, H, "\n".join(body), "Виды сгибов"), BOXES[n0:]


def _fold_icon(cx, cy, kind):
    """Иконка сгиба, вид с торца. Возвращает список элементов."""
    o = []
    w = 74
    if kind == "valley":
        o.append(path([(cx - w, cy - 14), (cx, cy + 18), (cx + w, cy - 14)]))
        o.append(arrow(cx, cy - 30, cx, cy + 6, MUTED, 1.4, 6))
    elif kind == "mountain":
        o.append(path([(cx - w, cy + 16), (cx, cy - 16), (cx + w, cy + 16)]))
        o.append(arrow(cx, cy + 32, cx, cy - 4, MUTED, 1.4, 6))
    elif kind == "pleat":
        o.append(path([(cx - w, cy), (cx - w / 3, cy - 16), (cx + w / 3, cy - 16), (cx + w, cy)]))
        o.append(path([(cx - w, cy + 12), (cx - w / 3, cy - 4), (cx + w / 3, cy - 4), (cx + w, cy + 12)],
                      MUTED, 1.2, "4 3"))
    elif kind == "accordion":
        pts = [(cx - w + i * (2 * w / 5), cy + (14 if i % 2 else -14)) for i in range(6)]
        o.append(path(pts))
    elif kind in ("reverse_in", "reverse_out"):
        s = 1 if kind == "reverse_in" else -1
        o.append(path([(cx - w, cy + 14), (cx, cy + 14), (cx, cy - 14 * s), (cx + w, cy - 14 * s)]))
        o.append(arrow(cx - 26, cy + 34, cx - 4, cy + 16, MUTED, 1.4, 6))
        o.append(arrow(cx + 26, cy - 34, cx + 4, cy - 16 * s, MUTED, 1.4, 6))
    elif kind == "squash":
        o.append(path([(cx, cy - 22), (cx + 30, cy), (cx, cy + 22), (cx - 30, cy)], close=True))
        o.append(path([(cx, cy - 22), (cx, cy + 22)], MUTED, 1.2, "4 3"))
        o.append(arrow(cx - 44, cy, cx - 32, cy, MUTED, 1.4, 6))
        o.append(arrow(cx + 44, cy, cx + 32, cy, MUTED, 1.4, 6))
    elif kind == "petal":
        o.append(path([(cx - 40, cy + 20), (cx, cy - 22), (cx + 40, cy + 20)], close=True))
        o.append(path([(cx - 40, cy + 20), (cx - 10, cy - 6), (cx, cy - 22)], GOOD, 1.3))
        o.append(path([(cx + 40, cy + 20), (cx + 10, cy - 6), (cx, cy - 22)], GOOD, 1.3))
    elif kind == "rabbit":
        o.append(path([(cx - 36, cy + 18), (cx, cy - 20), (cx + 36, cy + 18)], close=True))
        o.append(path([(cx, cy - 20), (cx, cy + 18)], MUTED, 1.2, "4 3"))
        o.append(arrow(cx + 4, cy - 4, cx + 22, cy - 18, MUTED, 1.3, 6))
    elif kind == "sink":
        o.append(path([(cx - w, cy - 10), (cx - 18, cy - 10), (cx, cy + 18), (cx + 18, cy - 10), (cx + w, cy - 10)]))
        o.append(path([(cx - 18, cy - 10), (cx, cy - 10), (cx + 18, cy - 10)], MUTED, 1.2, "4 3"))
    elif kind == "crimp":
        o.append(path([(cx - w, cy + 12), (cx - 20, cy + 12), (cx - 20, cy - 12), (cx + 20, cy - 12),
                       (cx + 20, cy + 12), (cx + w, cy + 12)]))
    elif kind == "curved":
        pts = []
        for i in range(41):
            t = i / 40
            pts.append((cx - w + 2 * w * t, cy + 16 * math.sin(2 * math.pi * t)))
        o.append(path(pts))
        o.append(path([(cx - w, cy + 22), (cx + w, cy + 22)], MUTED, 1.1, "4 4"))
    return o


PANELS_FOLDS: list[tuple[str, float, float, float, float]] = []

# ==================================================== 2. СЛОЖИТЬ-РАЗОГНУТЬ
def fig_unfold():
    n0 = len(BOXES)
    W, H = 1000, 800
    body = header("«Сложить, загладить, разогнуть»: как передать кромку, а не складку",
                  "слева — физика шага, справа — что из этого сегодня можно записать в сценарий")
    # --- пять состояний
    y_state, h_state = 118, 210
    states = [
        ("1. Лист", "угол 0°", "плоский, без памяти"),
        ("2. Сложить", "угол 179°", "слои легли, ребро сформировано"),
        ("3. Загладить", "угол 179° + давление", "волокна смяты по линии"),
        ("4. Разогнуть", "угол 2…5°", "остаточный угол «память»"),
        ("5. Кромка", "угол 0°, канавка", "линия видна, деталь плоская"),
    ]
    sx, sw, gap = 28, 176, 12
    for i, (name, angle, note) in enumerate(states):
        x = sx + i * (sw + gap)
        BOXES.append((f"st{i}", x, y_state, sw, h_state))
        body.append(f'<rect x="{x}" y="{y_state}" width="{sw}" height="{h_state}" rx="8" fill="{SOFT}" stroke="{LINE}"/>')
        body.append(text(x + 12, y_state + 24, name, 13, INK, weight="bold"))
        body.append(text(x + 12, y_state + 44, angle, 11, ACC))
        body += para(x + 12, y_state + 62, note, sw - 22, 10.2, MUTED)
        body += _state_icon(x + sw / 2, y_state + 132, i)
        if i < 4:
            body.append(arrow(x + sw + 2, y_state + 132, x + sw + gap - 2, y_state + 132, MUTED, 1.5, 6))

    # --- график угла
    gx, gy, gw, gh = 28, 380, 470, 210
    BOXES.append(("graph", gx, gy, gw, gh))
    body.append(f'<rect x="{gx}" y="{gy}" width="{gw}" height="{gh}" rx="8" fill="{SOFT}" stroke="{LINE}"/>')
    body.append(text(gx + 16, gy + 26, "Угол сгиба во времени", 13, INK, weight="bold"))
    ax0, ay0, ax1, ay1 = gx + 54, gy + 54, gx + gw - 20, gy + gh - 40
    body.append(f'<line x1="{ax0}" y1="{ay1}" x2="{ax1}" y2="{ay1}" stroke="{MUTED}" stroke-width="1"/>')
    body.append(f'<line x1="{ax0}" y1="{ay0}" x2="{ax0}" y2="{ay1}" stroke="{MUTED}" stroke-width="1"/>')
    for val in (0, 90, 179):
        yy = ay1 - (val / 180) * (ay1 - ay0)
        body.append(f'<line x1="{ax0 - 4}" y1="{yy:.1f}" x2="{ax1}" y2="{yy:.1f}" stroke="{LINE}" stroke-dasharray="3 4"/>')
        body.append(text(ax0 - 8, yy + 4, f"{val}°", 10, MUTED, "end"))
    # кривая: 0→179 за 2 с, держим 1 с, назад до 3° за 1.5 с, держим
    pts = []
    segs = [(0.0, 0, 0.0), (2.0, 179, 0.0), (3.0, 179, 0.0), (4.5, 3, 0.0), (6.0, 3, 0.0)]
    tmax = 6.0
    for t, v, _ in segs:
        pts.append((ax0 + (t / tmax) * (ax1 - ax0), ay1 - (v / 180) * (ay1 - ay0)))
    body.append(path(pts, ACC, 2.4))
    mid = (ay1 + ay0) / 2
    body.append(text(ax0 + 56, mid - 26, "сложить 2 с", 10, MUTED, "end"))
    body.append(text(ax0 + 0.70 * (ax1 - ax0), mid + 4, "разогнуть 1,5 с", 10, MUTED, "start"))
    body.append(text(ax0 + 0.42 * (ax1 - ax0), ay0 - 8, "держим 1 с", 10, MUTED, "middle"))
    body.append(text(ax0, ay1 + 20, "0 с", 10, MUTED, "middle"))
    body.append(text(ax1, ay1 + 20, "6 с", 10, MUTED, "middle"))


    # --- что нужно от движка
    rx, ry, rw, rh = 520, 380, 452, 210
    BOXES.append(("need", rx, ry, rw, rh))
    body.append(f'<rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" rx="8" fill="{SOFT}" stroke="{LINE}"/>')
    body.append(text(rx + 16, ry + 26, "Что для этого нужно в DSL", 13, INK, weight="bold"))
    lines = [
        ("сгиб … angle=179 unfold=да", "сложить и вернуть"),
        ("rest=3", "остаточный угол после разгиба"),
        ("crease=0.4", "полуширина канавки, мм"),
        ("memory=0.25", "глубина канавки, мм"),
        ("passes=2", "сколько раз прогладили"),
    ]
    for i, (code, note) in enumerate(lines):
        yy = ry + 54 + i * 30
        body.append(f'<rect x="{rx + 16}" y="{yy - 14}" width="228" height="22" rx="4" fill="#eef3f9" stroke="{LINE}"/>')
        body.append(text(rx + 24, yy + 2, code, 11.2, ACC))
        body.append(text(rx + 256, yy + 2, note, 10.6, MUTED))

    # --- факты
    fy = 606
    body.append(text(28, fy, "Что работает сегодня (замеры):", 13, INK, weight="bold"))
    facts = [
        (GOOD, "сгиб на 179° строится, объём сохраняется: 3.18 см³ против 3.20 см³ у листа"),
        (BAD, "разогнуть нельзя: все три попытки вернуть лист дали «Линия сгиба не пересекает деталь»"),
        (BAD, "лист 0.5 мм после одного сгиба занимает по Z 1.93 мм вместо 1.0 мм — перерасход 1.93×"),
        (BAD, "после сгиба на 120° второй сгиб не построился ни в 20 из 20 сочетаний"),
        (WARN, "линия-биг есть: складка r=0.5 depth=0.1 даёт канавку, но это не память после сгиба"),
        (GOOD, "память бумаги — это остаточный угол: 3° в модели дают видимую кромку на плоской детали"),
    ]
    for i, (color, s) in enumerate(facts):
        yy = fy + 26 + i * 24
        body.append(f'<circle cx="34" cy="{yy - 4}" r="3.2" fill="{color}"/>')
        body.append(text(46, yy, s, 12, INK))
    body.append(text(28, fy + 26 + 6 * 24 + 6,
                     "Отсюда правило: «сложить и разогнуть» — отдельный шаг сценария, а не побочный эффект сгиба.",
                     12, MUTED))
    return svg(W, H, "\n".join(body), "Сложить и разогнуть"), BOXES[n0:]


def _state_icon(cx, cy, i):
    """Пять состояний листа с торца."""
    o = []
    if i == 0:
        o.append(path([(cx - 62, cy), (cx + 62, cy)], ACC, 4))
        o.append(text(cx, cy + 24, "t = 0.5 мм", 10, MUTED, "middle"))
    elif i == 1:
        o.append(path([(cx - 62, cy - 30), (cx - 6, cy - 30), (cx - 6, cy + 26), (cx + 46, cy + 26),
                       (cx + 46, cy + 22), (cx - 2, cy + 22), (cx - 2, cy - 34)], ACC, 3))
        o.append(text(cx, cy + 48, "слои легли", 10, MUTED, "middle"))
    elif i == 2:
        o.append(path([(cx - 62, cy - 30), (cx - 6, cy - 30), (cx - 6, cy + 26), (cx + 46, cy + 26)], ACC, 3))
        o.append(f'<circle cx="{cx - 6}" cy="{cy - 2}" r="17" fill="none" stroke="{WARN}" stroke-width="1.4" stroke-dasharray="3 3"/>')
        o.append(text(cx, cy + 48, "давление", 10, WARN, "middle"))
    elif i == 3:
        o.append(path([(cx - 62, cy - 2), (cx - 50, cy - 12), (cx - 6, cy - 12), (cx + 38, cy - 2)], ACC, 3))
        o.append(f'<circle cx="{cx - 6}" cy="{cy - 10}" r="13" fill="none" stroke="{GOOD}" stroke-width="1.3"/>')
        o.append(text(cx, cy + 30, "угол 3°", 10, GOOD, "middle"))
    else:
        o.append(path([(cx - 62, cy), (cx - 10, cy), (cx + 10, cy), (cx + 62, cy)], ACC, 3))
        o.append(path([(cx - 10, cy), (cx - 2, cy + 5), (cx + 10, cy)], BAD, 1.6))
        o.append(text(cx, cy + 30, "канавка 0.25 мм", 10, BAD, "middle"))
    return o


PANELS_UNFOLD: list[tuple[str, float, float, float, float]] = []

# ==================================================== 3. СОЕДИНЕНИЯ
def fig_joints():
    n0 = len(BOXES)
    W, H = 1000, 812
    body = header("Соединения без клея и верёвки: геометрия, которую надо уметь считать",
                  "шесть механизмов; под каждым — параметры и проверка, которая ловит ошибку")
    joints = [
        ("Клапан в карман", "tab-and-pocket", "ухо w входит в карман глубиной d ≥ w + 2t",
         ["w = 8…12 мм", "d ≥ w + 2t", "зазор 0.1…0.3 мм"], "inside + clearance", GOOD,
         "Sonobe, модульные шары"),
        ("Замок коробки", "tuck lock", "клапан подсовывается под поясок и зажимается",
         ["вылет ≥ b + 2t", "натяг 0.1 мм", "заход 6…8 мм"], "clearance", GOOD,
         "масу-коробка, конверт"),
        ("Складка-замок", "pleat lock", "две встречные складки цепляются друг за друга",
         ["шаг p = 2t…3t", "сдвиг p/2", "угол 90°"], "gap", WARN,
         "лотки, крышки"),
        ("Клин / ласточкин хвост", "dovetail", "трапеция входит в паз и не выходит назад",
         ["скос 5…15°", "зазор 0.15 мм", "уклон по толщине"], "clearance + draft", GOOD,
         "картон, фанера"),
        ("Фрикционная посадка", "friction fit", "деталь держится на натяге, без замка",
         ["натяг 0.05…0.15 мм", "длина ≥ 3·t", "материал — картон"], "interference", WARN,
         "МДФ, картон"),
        ("Скрутка / бумажная заклёпка", "roll rivet", "трубка из скрученной бумаги стягивает пакет",
         ["D = 3…5 мм", "витков ≥ 3", "выступ 2 мм"], "wall + gap", WARN,
         "переплёт"),
    ]
    x0, y0, tw, th, gx, gy = 28, 104, 304, 294, 14, 14
    for i, (name, latin, what, params, check, color, where) in enumerate(joints):
        col, row = i % 3, i // 3
        x = x0 + col * (tw + gx)
        y = y0 + row * (th + gy)
        BOXES.append((f"j{i}", x, y, tw, th))
        body.append(f'<rect x="{x}" y="{y}" width="{tw}" height="{th}" rx="8" fill="{SOFT}" stroke="{LINE}"/>')
        body.append(f'<rect x="{x}" y="{y}" width="4" height="{th}" rx="2" fill="{color}"/>')
        body.append(text(x + 16, y + 26, name, 13.5, INK, weight="bold"))
        body.append(text(x + 16, y + 44, latin, 10.5, MUTED))
        cx_, cy_ = x + tw / 2, y + 118
        body.append(f'<g transform="translate({cx_:.1f},{cy_:.1f}) scale(1.22) '
                    f'translate({-cx_:.1f},{-cy_:.1f})">')
        body += _joint_icon(cx_, cy_, i)
        body.append('</g>')
        body.append(text(x + 16, y + 186, what, 10.6, INK))
        for k, prm in enumerate(params):
            body.append(text(x + 16, y + 210 + k * 17, "· " + prm, 10.4, MUTED))
        body.append(chip(x + 16, y + 268, "проверка: " + check, ACC))
        body.append(text(x + 16, y + 287, where, 9.8, MUTED))

    body += para(28, 732,
                 "Общее правило: держит не форма, а зазор. Все шесть механизмов сводятся к трём числам — "
                 "натяг, заход и зазор, — и все три у нас уже есть в проверках.",
                 944, 12.4, INK)
    return svg(W, H, "\n".join(body), "Соединения без крепежа"), BOXES[n0:]


def _joint_icon(cx, cy, i):
    o = []
    if i == 0:      # клапан в карман
        o.append(path([(cx - 60, cy - 18), (cx + 6, cy - 18), (cx + 6, cy - 4), (cx + 34, cy - 4)],
                      ACC, 2.6, fill="rgba(43,108,176,.10)"))
        o.append(path([(cx - 60, cy + 16), (cx + 30, cy + 16), (cx + 30, cy - 2), (cx - 4, cy - 2)],
                      MUTED, 2.2))
        o.append(arrow(cx + 44, cy - 26, cx + 20, cy - 8, BAD, 1.5, 6))
    elif i == 1:    # замок коробки
        o.append(path([(cx - 60, cy - 26), (cx + 20, cy - 26), (cx + 20, cy + 4), (cx + 52, cy + 4),
                       (cx + 52, cy + 18), (cx + 20, cy + 18), (cx + 20, cy + 26), (cx - 60, cy + 26)],
                      ACC, 2.4))
        o.append(path([(cx + 20, cy - 8), (cx + 44, cy - 8)], BAD, 2.0, "4 3"))
    elif i == 2:    # складка-замок
        o.append(path([(cx - 60, cy - 20), (cx - 20, cy - 20), (cx - 20, cy + 4), (cx + 20, cy + 4),
                       (cx + 20, cy - 20), (cx + 60, cy - 20)], ACC, 2.4))
        o.append(path([(cx - 60, cy + 16), (cx - 12, cy + 16), (cx - 12, cy - 8), (cx + 28, cy - 8)],
                      MUTED, 2.2))
    elif i == 3:    # ласточкин хвост
        o.append(path([(cx - 62, cy - 22), (cx + 4, cy - 22), (cx + 4, cy - 10), (cx + 30, cy - 10),
                       (cx + 30, cy + 10), (cx + 4, cy + 10), (cx + 4, cy + 22), (cx - 62, cy + 22)],
                      ACC, 2.4, fill="rgba(43,108,176,.10)"))
        o.append(path([(cx + 30, cy - 16), (cx + 60, cy - 16), (cx + 60, cy + 16), (cx + 30, cy + 16)],
                      MUTED, 2.2, "4 3"))
    elif i == 4:    # фрикционная посадка
        o.append(f'<rect x="{cx - 54}" y="{cy - 22}" width="58" height="44" rx="3" fill="none" stroke="{ACC}" stroke-width="2.4"/>')
        o.append(f'<rect x="{cx + 4}" y="{cy - 15}" width="56" height="30" rx="3" fill="rgba(183,121,31,.16)" stroke="{WARN}" stroke-width="2.2"/>')
        o.append(text(cx + 2, cy + 40, "натяг", 10, WARN, "middle"))
    else:           # скрутка
        for k in range(4):
            o.append(f'<circle cx="{cx - 30 + k * 4}" cy="{cy}" r="{20 - k * 2}" fill="none" stroke="{ACC}" stroke-width="1.8"/>')
        o.append(path([(cx + 12, cy - 20), (cx + 56, cy - 20)], MUTED, 2.2))
        o.append(path([(cx + 12, cy + 20), (cx + 56, cy + 20)], MUTED, 2.2))
    return o


PANELS_JOINTS: list[tuple[str, float, float, float, float]] = []

# ==================================================== 4. ПАЙПЛАЙН ИИ
def fig_pipeline():
    n0 = len(BOXES)
    W, H = 1000, 810
    body = header("Как просить нейросеть придумать оригами по теме",
                  "семь шагов; ИИ делает смысл и оценку, алгоритм — геометрию, проверка — отбор")
    stages = [
        ("1. Тема", "«оригами машины»", "ИИ", ACC),
        ("2. Палочки", "6 лучей из центра", "ИИ", ACC),
        ("3. Упаковка", "площадь листа", "алгоритм", GOOD),
        ("4. Развёртка", "линии горы/долины", "алгоритм", GOOD),
        ("5. Шаги", "20–30 сгибов", "алгоритм", GOOD),
        ("6. Проверка", "Кавасаки, Маэкава", "проверка", WARN),
        ("7. Оценка вида", "силуэт + VLM", "ИИ", ACC),
    ]
    x, y, bw, bh, gap = 28, 108, 137, 118, 8
    for i, (title, sub, who, color) in enumerate(stages):
        row, col = divmod(i, 4)
        bx = x + col * (bw + gap)
        by = y + row * (bh + 74)
        BOXES.append((f"p{i}", bx, by, bw, bh))
        body.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="8" fill="{SOFT}" '
                    f'stroke="{color}" stroke-width="1.4"/>')
        body.append(text(bx + 12, by + 24, title, 11.8, INK, weight="bold"))
        body.append(text(bx + 12, by + 44, sub, 9.8, MUTED))
        body.append(chip(bx + 12, by + 84, who, color))
        if col < 3 and i < 3:
            body.append(arrow(bx + bw + 2, by + bh / 2, bx + bw + gap - 2, by + bh / 2, MUTED, 1.4, 6))
        if col < 2 and i >= 4:
            body.append(arrow(bx + bw + 2, by + bh / 2, bx + bw + gap - 2, by + bh / 2, MUTED, 1.4, 6))

    # переход с первой строки на вторую
    x4 = x + 3 * (bw + gap) + bw / 2
    x5 = x + bw / 2
    yb = y + bh + 8
    body.append(path([(x4, y + bh + 2), (x4, yb), (x5, yb)], MUTED, 1.4))
    body.append(arrow(x5, yb, x5, y + bh + 74 - 4, MUTED, 1.4, 6))

    # легенда справа от второй строки
    lx, ly, lw, lh2 = x + 3 * (bw + gap) + 10, y + bh + 74, 944 - 3 * (bw + gap) - 10, 118
    body.append(f'<rect x="{lx}" y="{ly}" width="{lw}" height="{lh2}" rx="8" fill="{SOFT}" stroke="{LINE}"/>')
    body.append(text(lx + 16, ly + 26, "Кто что делает", 12.2, INK, weight="bold"))
    for k, (who, colr, note) in enumerate([("ИИ", ACC, "придумывает тему, пропорции и критикует вид"),
                                           ("алгоритм", GOOD, "считает упаковку, развёртку и шаги"),
                                           ("проверка", WARN, "отбрасывает неразрешимые складки")]):
        yy = ly + 52 + k * 24
        body.append(chip(lx + 16, yy, who, colr))
        body.append(text(lx + 132, yy + 4, note, 10.4, MUTED))

    # --- доказательства
    ey = 470
    body.append(text(28, ey, "Почему нельзя просить развёртку «одним куском»:", 13, INK, weight="bold"))
    ev = [
        ("42–53 %", "лучшие MLLM на OrigamiSpace (350 задач), эксперты — 98–100 %"),
        ("28.6 % → 66.9 %", "тот же GPT-4o, но 10 раундов обратной связи от компилятора развёрток"),
        ("≈60 %", "потолок плоско-складываемости при прямом дообучении модели на CP"),
        ("100 моделей", "весь датасет COrigami: размеченных развёрток в мире очень мало"),
    ]
    for i, (num, note) in enumerate(ev):
        yy = ey + 34 + i * 46
        body.append(f'<rect x="28" y="{yy - 24}" width="944" height="38" rx="6" fill="{SOFT}" stroke="{LINE}"/>')
        body.append(text(44, yy + 2, num, 14, BAD if i < 3 else WARN, weight="bold"))
        body.append(text(196, yy + 2, note, 11.4, INK))

    # --- что просить у ИИ
    ty = 686
    body.append(text(28, ty, "Правило формулировки:", 13, INK, weight="bold"))
    body.append(text(28, ty + 24,
                     "просите не развёртку, а «схему из палочек + список шагов»; геометрию считайте сами, "
                     "а модели оставьте смысл, пропорции и критику вида.", 12, INK))
    body += para(28, ty + 42,
                 "Ограничение: движок сегодня не умеет ни второго сгиба на объёмной детали, ни разгиба — "
                 "значит, шаги 5–6 придётся реализовать до того, как звать ИИ.",
                 944, 12, BAD)
    return svg(W, H, "\n".join(body), "Пайплайн ИИ"), BOXES[n0:]


PANELS_PIPE: list[tuple[str, float, float, float, float]] = []


# ============================================================ ПРОВЕРКА
_TXT_RE = (r'<text x="([\d.]+)" y="([\d.]+)" font-size="([\d.]+)" fill="[^"]+" '
           r'text-anchor="([a-z]+)" font-weight="([a-z]+)"[^>]*>(.*?)</text>')


def _texts(svg_text):
    for m in re.finditer(_TXT_RE, svg_text):
        yield (float(m.group(1)), float(m.group(2)), float(m.group(3)),
               m.group(4), m.group(5), m.group(6))

def check(path: Path, panels):
    s = path.read_text(encoding="utf-8")
    problems = []
    root = re.search(r'width="(\d+)" height="(\d+)"', s)
    cw, chh = (int(root.group(1)), int(root.group(2))) if root else (1000, 1000)
    for tx, ty, size, anchor, wd, txt in _texts(s):
        wd = tw(txt, size, wd != "normal")
        left = tx if anchor == "start" else (tx - wd / 2 if anchor == "middle" else tx - wd)
        if left < 20 or left + wd > cw - 20:
            problems.append(f"за холстом: «{txt[:34]}» ({left + wd - (cw - 20):+.0f} px)")
        if ty > chh - 8:
            problems.append(f"ниже холста: «{txt[:34]}» ({ty - (chh - 8):+.0f} px)")
    for name, x, y, w, h in panels:
        for tx, ty, size, anchor, wd, txt in _texts(s):
            if not (x <= tx <= x + w and y <= ty <= y + h):
                continue
            wd = tw(txt, size, wd != "normal")
            left = tx if anchor == "start" else (tx - wd / 2 if anchor == "middle" else tx - wd)
            if left < x + 8 or left + wd > x + w - 8:
                problems.append(f"{name}: «{txt[:32]}» вылезает "
                                f"({left + wd - (x + w):+.0f} px)")
    boxes = []
    for tx, ty, size, anchor, wd, txt in _texts(s):
        wd = tw(txt, size, wd != "normal")
        left = tx if anchor == "start" else (tx - wd / 2 if anchor == "middle" else tx - wd)
        boxes.append((left, left + wd, ty - size * 0.78, ty + size * 0.22, txt))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a[1] <= b[0] or b[1] <= a[0] or a[3] <= b[2] or b[3] <= a[2]:
                continue
            problems.append(f"наезд: «{a[4][:26]}» и «{b[4][:26]}»")
    print(f"  {path.name}: проблем {len(problems)}")
    for p in problems[:14]:
        print("     ·", p)
    return not problems


def main():
    figs = [
        ("origami_folds.svg", fig_folds),
        ("origami_fold_unfold.svg", fig_unfold),
        ("origami_joints.svg", fig_joints),
        ("origami_ai_pipeline.svg", fig_pipeline),
        ("origami_bad_cases.svg", fig_bad),
    ]
    ok = True
    for name, fn in figs:
        svg_text, panels = fn()
        p = OUT / name
        p.write_text(svg_text, encoding="utf-8")
        print("написано:", p)
        if "--check" in sys.argv:
            ok = check(p, panels) and ok
    if "--check" in sys.argv:
        sys.exit(0 if ok else 1)




# ==================================================== 5. ПЛОХО / ЛЕЧЕНИЕ
def fig_bad():
    n0 = len(BOXES)
    W, H = 1000, 1010
    body = header("Шесть типичных провалов и их лечение",
                  "слева — что происходит на самом деле (с числами из замеров), справа — что делать сегодня")
    rows = [
        ("Второй сгиб на объёмной детали",
         "после сгиба на 120° не построился ни один из 20 вариантов: «На плоскую часть листа "
         "остаётся 0.0 мм, а сгиб занимает 91.7 мм»",
         "панели + петля: 4 панели, 3 сопряжения type=петля, все проверки связи — остаток 0 мм",
         "fold2", "hinge"),
        ("Четыре слоя бумаги",
         "лист 0.5 мм после одного сгиба занимает 1.93 мм вместо 1.0; второй сгиб не ставится",
         "считать толщину заранее: 4 слоя 0.5 мм — это 2.0 мм; печатать развёртку и складывать руками",
         "layers", "flat"),
        ("Разогнуть после сгиба",
         "три попытки вернуть лист в плоскость: «Линия сгиба не пересекает деталь»",
         "биг канавкой до сгиба: складка depth=0.15 даёт 2.17 мм против 1.93 мм у чистого сгиба",
         "unfold", "crease"),
        ("Деталь «спекается» при складывании",
         "сгиб 179° с gap=0 дал род −1 — поверхности вошли друг в друга",
         "gap = 0.2·толщины: при gap 0.5…2 мм по Z выходит 2.2…3.7 мм, род 0",
         "selfx", "gapfix"),
        ("Соединение без клея болтается",
         "шип 20×4 в пазу 20.6×4.6: зазор 0.3 мм — держится только за счёт трения, проверки нет",
         "проверка gap 0.1..0.5 мм и сопряжение type=паз: остаток 0 мм, «держится»",
         "loose", "fit"),
        ("«Развёртка» — не то слово",
         "команда развёртка — это sweep: профиль по 3D-пути, а не развёртка листа",
         "развёртку даёт сечение (section → DXF и SVG) или ручная раскладка панелей",
         "wrongword", "net"),
    ]
    y = 104
    rh = 148
    for i, (title, bad, good, badk, goodk) in enumerate(rows):
        BOXES.append((f"row{i}", 28, y, 944, rh - 8))
        body.append(f'<rect x="28" y="{y}" width="944" height="{rh - 8}" rx="8" fill="{SOFT}" stroke="{LINE}"/>')
        body.append(text(44, y + 26, f"{i + 1}. {title}", 13.5, INK, weight="bold"))
        # плохо
        bx, bw = 44, 448
        body.append(f'<rect x="{bx}" y="{y + 36}" width="{bw}" height="{rh - 54}" rx="6" fill="#fdf3f2" stroke="{BAD}" stroke-width="0.9"/>')
        body.append(chip(bx + 12, y + 54, "плохо", BAD))
        body += para(bx + 76, y + 58, bad, bw - 96, 10.4, INK, 14)
        body += _bad_icon(bx + bw - 56, y + 92, badk)
        # лечение
        gx2, gw2 = 508, 448
        body.append(f'<rect x="{gx2}" y="{y + 36}" width="{gw2}" height="{rh - 54}" rx="6" fill="#f2f9f3" stroke="{GOOD}" stroke-width="0.9"/>')
        body.append(chip(gx2 + 12, y + 54, "лечение", GOOD))
        body += para(gx2 + 88, y + 58, good, gw2 - 108, 10.4, INK, 14)
        body += _bad_icon(gx2 + gw2 - 56, y + 92, goodk)
        y += rh
    return svg(W, H, "\n".join(body), "Плохо и лечение"), BOXES[n0:]


def _bad_icon(cx, cy, kind):
    c, g = BAD, GOOD
    o = []
    if kind == "fold2":
        o.append(path([(cx - 34, cy - 14), (cx - 2, cy - 14), (cx - 2, cy + 14), (cx + 26, cy + 14)], c, 2.2))
        o.append(text(cx - 4, cy + 26, "0.0 мм", 9.5, c, "middle"))
    elif kind == "hinge":
        o.append(path([(cx - 36, cy + 16), (cx - 4, cy + 16)], g, 2.4))
        o.append(path([(cx - 4, cy + 16), (cx + 26, cy - 8)], g, 2.4))
        o.append(f'<circle cx="{cx - 4}" cy="{cy + 16}" r="3.4" fill="none" stroke="{g}" stroke-width="1.6"/>')
        o.append(text(cx - 4, cy + 26, "петля", 9.5, g, "middle"))
    elif kind == "layers":
        for k in range(4):
            o.append(f'<rect x="{cx - 30}" y="{cy - 16 + k * 6}" width="60" height="4" fill="{c}" opacity="0.55"/>')
        o.append(text(cx, cy + 24, "2.0 мм", 9.5, c, "middle"))
    elif kind == "flat":
        o.append(f'<rect x="{cx - 30}" y="{cy - 2}" width="60" height="4" fill="{g}"/>')
        o.append(text(cx, cy + 20, "руками", 9.5, g, "middle"))
    elif kind == "unfold":
        o.append(path([(cx - 34, cy), (cx - 2, cy), (cx - 2, cy - 22), (cx + 26, cy - 22)], c, 2.2))
        o.append(path([(cx + 26, cy - 30), (cx + 4, cy - 8)], c, 1.4, "3 3"))
    elif kind == "crease":
        o.append(path([(cx - 34, cy - 4), (cx - 6, cy + 4), (cx + 22, cy - 4)], g, 2.2))
        o.append(text(cx - 4, cy + 22, "биг", 9.5, g, "middle"))
    elif kind == "selfx":
        o.append(path([(cx - 32, cy), (cx - 4, cy - 18), (cx + 24, cy)], c, 2.2))
        o.append(path([(cx - 32, cy), (cx - 4, cy + 18), (cx + 24, cy)], c, 2.2))
    elif kind == "gapfix":
        o.append(path([(cx - 32, cy - 8), (cx - 4, cy - 8)], g, 2.6))
        o.append(path([(cx - 32, cy + 8), (cx - 4, cy + 8)], g, 2.6))
        o.append(text(cx + 22, cy + 4, "gap", 9.5, g, "middle"))
    elif kind == "loose":
        o.append(f'<rect x="{cx - 34}" y="{cy - 12}" width="30" height="24" fill="none" stroke="{c}" stroke-width="1.6"/>')
        o.append(f'<rect x="{cx - 2}" y="{cy - 8}" width="26" height="16" fill="none" stroke="{c}" stroke-width="1.6" stroke-dasharray="3 3"/>')
    elif kind == "fit":
        o.append(f'<rect x="{cx - 34}" y="{cy - 14}" width="30" height="28" fill="none" stroke="{g}" stroke-width="1.8"/>')
        o.append(f'<rect x="{cx - 2}" y="{cy - 10}" width="26" height="20" fill="{g}" opacity="0.25" stroke="{g}" stroke-width="1.6"/>')
    elif kind == "wrongword":
        o.append(path([(cx - 36, cy + 12), (cx - 12, cy - 12), (cx + 12, cy + 14), (cx + 30, cy - 12)], c, 2.2))
        o.append(text(cx - 2, cy + 26, "sweep", 9.5, c, "middle"))
    elif kind == "net":
        o.append(f'<rect x="{cx - 32}" y="{cy - 16}" width="24" height="32" fill="none" stroke="{g}" stroke-width="1.5"/>')
        o.append(f'<rect x="{cx - 8}" y="{cy - 16}" width="24" height="16" fill="none" stroke="{g}" stroke-width="1.5"/>')
        o.append(f'<rect x="{cx - 8}" y="{cy}" width="24" height="16" fill="none" stroke="{g}" stroke-width="1.5"/>')
        o.append(text(cx - 4, cy + 26, "DXF", 9.5, g, "middle"))
    return o


if __name__ == "__main__":
    main()
