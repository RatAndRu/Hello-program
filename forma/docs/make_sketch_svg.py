#!/usr/bin/env python3
"""Схема «зачем контуру кривые» к docs/primitives_gap_analysis.md.

Запуск: python forma/docs/make_sketch_svg.py
Пишет forma/docs/img/sketch_curve_why.svg

Три панели, все числа посчитаны здесь же:
1. овал, записанный 70 точками, против овала из двух чисел;
2. линия без толщины → замкнутый контур → тело после выдавливания;
3. зуб шестерни: трапеция (как в коде сейчас) против эвольвенты.

Проверка вёрстки: python forma/docs/make_sketch_svg.py --check
(считает, что текст не вылезает за панель и элементы не наезжают друг на друга).
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
BG = "#ffffff"
LINE = "#d5dbe1"
SOFT = "#fcfdfe"

W = 1000
PX = 28            # левое поле
PW = W - 2 * PX    # ширина панели
PANELS: list[tuple[str, int, int]] = []   # (имя, y, высота) — для проверки

# коэффициенты для оценки ширины строки (DejaVu Sans, кириллица чуть шире латиницы)
CHAR_W = 0.545


def svg(w, h, body, title=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" {FONT}>\n'
        f"<title>{title}</title>\n"
        f'<rect width="{w}" height="{h}" fill="{BG}"/>\n'
        f"{body}\n</svg>\n"
    )


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=13, color=INK, anchor="start", weight="normal"):
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
        f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>'
    )


def panel(y, h, num, title, sub, color=ACC):
    """Шапка панели. Возвращает (элементы, y начала рабочей области)."""
    PANELS.append((num, y, h))
    out = [f'<rect x="{PX}" y="{y}" width="{PW}" height="{h}" rx="8" fill="{SOFT}" stroke="{LINE}"/>',
           f'<rect x="{PX}" y="{y}" width="5" height="{h}" rx="2" fill="{color}"/>',
           text(PX + 20, y + 32, f"{num}. {title}", 15.5, INK, weight="bold"),
           text(PX + 20, y + 55, sub, 12, MUTED)]
    return out, y + 55


def notes(x, y0, lines, size=12):
    """Три-четыре строки вывода в правой колонке."""
    out = []
    for i, (s, col) in enumerate(lines):
        out.append(text(x, y0 + i * 22, s, size, col))
    return out


# --------------------------------------------------------------- 1. овал
def oval_panel(y, h):
    out, _ = panel(y, h, "1", "Один и тот же овал: 140 чисел или два",
                   "в examples/anime_face.forma контур века набран 70 точками с шагом 5.67 мм", BAD)
    a, b = 88, 62
    cy = y + 150
    cx_l, cx_r = PX + 170, PX + 430

    pts = []
    for i in range(70):
        t = 2 * math.pi * i / 70
        pts.append(f"{cx_l + a * math.cos(t):.2f},{cy + b * math.sin(t):.2f}")
    out.append(f'<polygon points="{" ".join(pts)}" fill="rgba(192,57,43,.06)" '
               f'stroke="{BAD}" stroke-width="1.2"/>')
    for i in range(0, 70, 1):
        t = 2 * math.pi * i / 70
        out.append(f'<circle cx="{cx_l + a * math.cos(t):.2f}" cy="{cy + b * math.sin(t):.2f}" '
                   f'r="1.7" fill="{BAD}"/>')
    out.append(text(cx_l, cy + b + 28, "70 точек · 140 чисел", 12, BAD, "middle", "bold"))
    out.append(text(cx_l, cy + b + 48, "шаг 5.67 мм, связь с радиусом потеряна", 11, MUTED, "middle"))

    out.append(f'<ellipse cx="{cx_r}" cy="{cy}" rx="{a}" ry="{b}" fill="rgba(30,132,73,.06)" '
               f'stroke="{GOOD}" stroke-width="1.8"/>')
    out.append(f'<line x1="{cx_r - a}" y1="{cy}" x2="{cx_r + a}" y2="{cy}" stroke="{GOOD}" '
               f'stroke-width="0.9" stroke-dasharray="4 4"/>')
    out.append(f'<line x1="{cx_r}" y1="{cy - b}" x2="{cx_r}" y2="{cy + b}" stroke="{GOOD}" '
               f'stroke-width="0.9" stroke-dasharray="4 4"/>')
    out.append(text(cx_r, cy + b + 28, "2 числа · дуга остаётся дугой", 12, GOOD, "middle", "bold"))
    out.append(text(cx_r, cy + b + 48, "отклонение от идеального эллипса 0.27 мм", 11, MUTED, "middle"))

    out += notes(PX + 620, y + 96, [
        ("Что видно: контур «почти эллипс»", INK),
        ("(0.27 мм), но записан как данные.", MUTED),
        ("", INK),
        ("Профиль в DSL принимает только", INK),
        ("[[x, y], …] — подать кривую нечем,", BAD),
        ("поэтому её копируют точками.", BAD),
        ("", INK),
        ("При правке радиуса список надо", INK),
        ("пересчитывать целиком.", MUTED),
    ])
    return out


# ---------------------------------------------------- 2. линия → толщина
def extrude_panel(y, h):
    out, _ = panel(y, h, "2", "У линии нет толщины — толщину даёт операция",
                   "контур задаёт сечение; тело появляется на выдавливании, вращении или протяжке", GOOD)
    cy = y + 150
    cx = PX + 150
    a, b = 78, 34

    def oval_pts(x0, y0, aa, bb, n=72, top_only=False):
        if top_only:
            return [(x0 + aa * math.cos(math.pi * i / n), y0 + bb * math.sin(math.pi * i / n))
                    for i in range(n + 1)]
        return [(x0 + aa * math.cos(2 * math.pi * i / n), y0 + bb * math.sin(2 * math.pi * i / n))
                for i in range(n)]

    # контур: замкнутая кривая
    out.append('<polygon points="%s" fill="none" stroke="%s" stroke-width="2.6"/>'
               % (" ".join(f"{px:.1f},{py:.1f}" for px, py in oval_pts(cx, cy, a, b)), ACC))
    out.append(text(cx, cy + b + 34, "контур: замкнутая кривая", 12, ACC, "middle", "bold"))
    out.append(text(cx, cy + b + 54, "толщина 0", 11, MUTED, "middle"))

    # стрелка
    x0, x1, ay = cx + a + 26, cx + a + 96, cy - 6
    out.append(f'<line x1="{x0}" y1="{ay}" x2="{x1 - 12}" y2="{ay}" stroke="{INK}" stroke-width="1.6"/>')
    out.append(f'<polygon points="{x1},{ay} {x1 - 13},{ay - 6} {x1 - 13},{ay + 6}" fill="{INK}"/>')
    out.append(text((x0 + x1) / 2, ay - 14, "extrude", 12, INK, "middle", "bold"))
    out.append(text((x0 + x1) / 2, ay + 22, "height = h", 11, MUTED, "middle"))

    # тело: цилиндр — верхняя половина эллипса, боковины, нижняя дуга
    bx = cx + 300
    top_y, bot_y = cy - 46, cy + 34

    def arc(x0, y0, aa, bb, t0, t1, n=48):
        return [(x0 + aa * math.cos(t0 + (t1 - t0) * i / n),
                 y0 + bb * math.sin(t0 + (t1 - t0) * i / n)) for i in range(n + 1)]

    sil = arc(bx, top_y, a, b, math.pi, 2 * math.pi)      # верх: слева → вверх → справа
    sil += [(bx + a, bot_y)]
    sil += arc(bx, bot_y, a, b, 0.0, math.pi)              # низ: справа → вниз → слева
    sil += [(bx - a, top_y)]
    out.append('<polygon points="%s" fill="rgba(43,108,176,.12)" stroke="%s" stroke-width="1.8"/>'
               % (" ".join(f"{px:.1f},{py:.1f}" for px, py in sil), ACC))
    out.append('<ellipse cx="%.1f" cy="%.1f" rx="%.1f" ry="%.1f" fill="rgba(43,108,176,.20)" '
               'stroke="%s" stroke-width="1.4"/>' % (bx, top_y, a, b, ACC))
    out.append(text(bx, bot_y + b + 34, "тело с толщиной h", 12, ACC, "middle", "bold"))

    out += notes(PX + 620, y + 96, [
        ("Те же правила у lathe (вращение)", INK),
        ("и sweep (протяжка по пути).", INK),
        ("", INK),
        ("Дуга не «тоньше» линии: она задаёт", INK),
        ("форму, а размер детали задаёт", INK),
        ("операция над контуром.", INK),
        ("", INK),
        ("Нужен график кривой в DSL, а не её", GOOD),
        ("копия из точек.", GOOD),
    ])
    return out


# --------------------------------------------------- 3. зуб шестерни
def tooth_panel(y, h):
    out, _ = panel(y, h, "3", "Зуб шестерни: трапеция не входит в зацепление",
                   "gear teeth=20 module=2 — в коде профиль зуба задан четырьмя точками (ops_shapes.py)",
                   BAD)
    m, z = 2.0, 20
    rp = m * z / 2
    ra, rf = rp + m, rp - 1.25 * m
    alpha = math.radians(20)
    inv = lambda a: math.tan(a) - a
    psi_b = (math.pi * m / 2) / (2 * rp) + inv(alpha)
    step = 2 * math.pi / z

    def psi_inv(rr):
        if rr <= rp * math.cos(alpha):
            return None
        return psi_b - inv(math.acos(rp * math.cos(alpha) / rr))

    def psi_trap(rr):
        f = (rr - rf) / (ra - rf)
        return (0.30 - 0.14 * f) * step

    px_mm, py_mm = 26.0, 24.0          # масштаб: мм по дуге / мм по радиусу
    cx, base = PX + 190, y + 236       # центр по x, линия r основания по y

    def pt(rr, psi, sign):
        s_mm = sign * rr * psi          # длина по дуге от средней линии
        return (cx + s_mm * px_mm, base - (rr - rf) * py_mm)

    def flank(psi_fn, rf_from, n, sign):
        pts = []
        for i in range(n + 1):
            rr = rf_from + (ra - rf_from) * i / n
            psi = psi_fn(rr)
            if psi is None:
                continue
            pts.append(pt(rr, psi, sign))
        return pts

    out.append(f'<line x1="{cx - 96}" y1="{base}" x2="{cx + 96}" y2="{base}" stroke="{LINE}" stroke-width="1"/>')
    out.append(f'<line x1="{cx - 96}" y1="{base - (rp - rf) * py_mm:.1f}" x2="{cx + 96}" '
               f'y2="{base - (rp - rf) * py_mm:.1f}" stroke="{LINE}" stroke-width="1" stroke-dasharray="4 4"/>')
    out.append(text(cx + 56, base + 4, "r 17.5 · основание", 10.5, MUTED, "start"))
    out.append(text(cx + 56, base - (rp - rf) * py_mm + 4, "r 20 · делительная", 10.5, MUTED, "start"))

    rb = rp * math.cos(alpha)

    def psi_full(rr):
        # ниже основной окружности эвольвенты нет — берём радиальный участок
        if rr <= rb:
            return psi_b
        return psi_inv(rr)

    inv_l = flank(psi_full, rf, 48, +1)
    inv_r = flank(psi_full, rf, 48, -1)
    trap_l = flank(psi_trap, rf, 2, +1)
    trap_r = flank(psi_trap, rf, 2, -1)
    out.append('<polygon points="%s" fill="rgba(192,57,43,.08)" stroke="%s" stroke-width="2" '
               'stroke-dasharray="6 3"/>' % (" ".join(f"{a:.1f},{b:.1f}" for a, b in trap_l + trap_r[::-1]), BAD))
    out.append('<polygon points="%s" fill="none" stroke="%s" stroke-width="2.4"/>'
               % (" ".join(f"{a:.1f},{b:.1f}" for a, b in inv_l + inv_r[::-1]), GOOD))
    # размер 0.41 мм у вершины
    yv = base - (ra - rf) * py_mm
    xt = trap_r[-1][0]
    xi = inv_r[-1][0]
    out.append(f'<line x1="{xi:.1f}" y1="{yv:.1f}" x2="{xt:.1f}" y2="{yv:.1f}" stroke="{INK}" '
               f'stroke-width="1.2" stroke-dasharray="2 2"/>')
    out.append(text((xi + xt) / 2 + 6, yv - 8, "0.41 мм", 11, INK, "start", "bold"))
    out.append(text(PX + 20, base + 30, "профиль зуба, развёрнутый по радиусу", 11.5, MUTED))

    lx = PX + 380
    out.append(f'<line x1="{lx}" y1="{y + 100}" x2="{lx + 26}" y2="{y + 100}" stroke="{GOOD}" stroke-width="2.4"/>')
    out.append(text(lx + 36, y + 104, "эвольвента — нужна кривая (40+ точек)", 12, GOOD, "start", "bold"))
    out.append(f'<line x1="{lx}" y1="{y + 130}" x2="{lx + 26}" y2="{y + 130}" stroke="{BAD}" '
               f'stroke-width="2.4" stroke-dasharray="6 3"/>')
    out.append(text(lx + 36, y + 134, "трапеция из 4 точек — как сейчас", 12, BAD, "start", "bold"))

    out += notes(lx, y + 168, [
        ("Модуль 2 мм, 20 зубьев: профили", INK),
        ("расходятся на 0.41 мм.", INK),
        ("", INK),
        ("Толщина зуба на вершине:", INK),
        ("2.21 мм у трапеции против 1.39 мм", BAD),
        ("у эвольвенты — на 59 % толще.", BAD),
        ("Такой зуб не сядет в паз настоящей", MUTED),
        ("шестерни: заклинивание или люфт.", MUTED),
    ])
    return out


def build():
    H = 1010
    body = [text(PX, 42, "Зачем контуру кривые: где заканчивается список точек", 22, INK, weight="bold"),
            text(PX, 68, "Все числа посчитаны по файлам репозитория; это не иллюстрации «на глаз».",
                 13, MUTED),
            f'<line x1="{PX}" y1="86" x2="{W - PX}" y2="86" stroke="{LINE}"/>']
    body += oval_panel(104, 268)
    body += extrude_panel(392, 268)
    body += tooth_panel(680, 310)
    return svg(W, H + 20, "\n".join(body), "Зачем контуру кривые")


# ------------------------------------------------------------------ проверка
def check(path: Path):
    s = path.read_text(encoding="utf-8")
    problems = []
    for num, py, ph in PANELS:
        for m in re.finditer(r'<text x="([\d.]+)" y="([\d.]+)" font-size="([\d.]+)"[^>]*'
                             r'text-anchor="([a-z]+)"[^>]*>(.*?)</text>', s):
            x, y, size, anchor, txt = float(m.group(1)), float(m.group(2)), float(m.group(3)), m.group(4), m.group(5)
            if not (py <= y <= py + ph):
                continue
            width = len(txt) * size * CHAR_W
            left = x if anchor == "start" else (x - width / 2 if anchor == "middle" else x - width)
            right = left + width
            if left < PX + 12 or right > W - PX - 12:
                problems.append(f"панель {num}: «{txt[:38]}» выходит за поле "
                                f"[{left:.0f}; {right:.0f}]")
    # пересечение текстовых строк: только если совпадают и по x, и по y
    boxes = []
    for m in re.finditer(r'<text x="([\d.]+)" y="([\d.]+)" font-size="([\d.]+)"[^>]*'
                         r'text-anchor="([a-z]+)"[^>]*>(.*?)</text>', s):
        x, y, size, anchor, txt = (float(m.group(1)), float(m.group(2)), float(m.group(3)),
                                   m.group(4), m.group(5))
        w = len(txt) * size * CHAR_W
        left = x if anchor == "start" else (x - w / 2 if anchor == "middle" else x - w)
        boxes.append((left, left + w, y - size * 0.78, y + size * 0.22, txt))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a[1] <= b[0] or b[1] <= a[0]:
                continue
            if a[3] <= b[2] or b[3] <= a[2]:
                continue
            problems.append(f"наезд: «{a[4][:28]}» и «{b[4][:28]}»")
    print(f"панели: {[(n, y, h) for n, y, h in PANELS]}")
    print("проблем:", len(problems))
    for p in problems:
        print("  ·", p)
    return not problems


def main():
    path = OUT / "sketch_curve_why.svg"
    path.write_text(build(), encoding="utf-8")
    print("написано:", path)
    if "--check" in sys.argv:
        sys.exit(0 if check(path) else 1)


if __name__ == "__main__":
    main()
