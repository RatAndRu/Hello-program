#!/usr/bin/env python3
"""Схема «семейства вместо количества команд» к docs/primitives_gap_analysis.md.

Запуск: python forma/docs/make_family_svg.py
Пишет forma/docs/img/families_vs_count.svg

Панель A — пять видов пружин: одна геометрия, разные концы и профиль.
Панель B — сколько знаков и токенов стоит одна команда в реестре и в каталоге
           (посчитано по forma/instruction.py, раздел «Методика»).
Панель C — что даёт вариант внутри команды против новой команды.
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

W = 1000
PX = 28
PW = W - 2 * PX
CHAR_W = 0.545
PANELS: list[tuple[str, int, int]] = []

# измеренные величины (см. docs/sketch_and_families.md, раздел «Методика»)
REG_CHARS = 77749        # имя + алиасы + описание + параметры, 227 команд
CAT_CHARS = 266231       # полный каталог команд
FULL_CHARS = 283500      # инструкция целиком
N_OPS = 227


def svg(w, h, body, title=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" {FONT}>\n<title>{title}</title>\n'
            f'<rect width="{w}" height="{h}" fill="{BG}"/>\n{body}\n</svg>\n')


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size=13, color=INK, anchor="start", weight="normal"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')


def panel(y, h, num, title, sub, color=ACC):
    PANELS.append((num, y, h))
    return [f'<rect x="{PX}" y="{y}" width="{PW}" height="{h}" rx="8" fill="{SOFT}" stroke="{LINE}"/>',
            f'<rect x="{PX}" y="{y}" width="5" height="{h}" rx="2" fill="{color}"/>',
            text(PX + 20, y + 32, f"{num}. {title}", 15.5, INK, weight="bold"),
            text(PX + 20, y + 55, sub, 12, MUTED)]


# ------------------------------------------------------------- A. пружины
def coil(cx, cy, turns, r, pitch, n=26):
    """Боковая проекция винтовой пружины: ломаная по виткам."""
    pts = []
    total = turns * n
    for i in range(total + 1):
        t = i / n * 2 * math.pi
        pts.append((cx + r * math.cos(t), cy + (i / total - 0.5) * turns * pitch))
    return pts


def spring_panel(y, h):
    out = panel(y, h, "A", "Пять видов пружин — одна основа, разные концы и профиль",
                "сжатия, растяжения, кручения, тарельчатая (Belleville), волновая", GOOD)
    r, ell_ry = 30, 10

    def turn_ellipses(cx, cy, n, dy, rx=r, ry=ell_ry, phase=0):
        o = []
        for k in range(n):
            o.append(f'<ellipse cx="{cx + (6 if k % 2 else -6)}" cy="{cy + (k - (n - 1) / 2) * dy}" '
                     f'rx="{rx}" ry="{ry}" fill="none" stroke="{ACC}" stroke-width="1.9"/>')
        return o

    names = [("сжатия", "торцы поджаты"),
             ("растяжения", "концы — крючки"),
             ("кручения", "ось поперёк, рычаги"),
             ("тарельчатая", "профиль — конус"),
             ("волновая", "торец — волна")]
    for i, (name, feature) in enumerate(names):
        cx, cy = PX + 96 + i * 186, y + 122
        if i == 0:      # сжатие: 5 витков, поджатые торцы
            out += turn_ellipses(cx, cy, 5, 7)
            out.append(f'<line x1="{cx - r}" y1="{cy - 26}" x2="{cx + r}" y2="{cy - 26}" stroke="{ACC}" stroke-width="2.4"/>')
            out.append(f'<line x1="{cx - r}" y1="{cy + 26}" x2="{cx + r}" y2="{cy + 26}" stroke="{ACC}" stroke-width="2.4"/>')
        elif i == 1:    # растяжение: те же витки + крючки
            out += turn_ellipses(cx, cy, 5, 7)
            out.append(f'<path d="M {cx - r},{cy - 28} L {cx - r - 12},{cy - 42} L {cx - 4},{cy - 50}" '
                       f'fill="none" stroke="{ACC}" stroke-width="2.4"/>')
            out.append(f'<path d="M {cx + r},{cy + 28} L {cx + r + 12},{cy + 42} L {cx + 4},{cy + 50}" '
                       f'fill="none" stroke="{ACC}" stroke-width="2.4"/>')
        elif i == 2:    # кручение: витки вокруг горизонтальной оси + два рычага
            for k in range(4):
                out.append(f'<ellipse cx="{cx + (k - 1.5) * 13}" cy="{cy}" rx="7" ry="{r}" '
                           f'fill="none" stroke="{ACC}" stroke-width="1.9"/>')
            out.append(f'<line x1="{cx - 18}" y1="{cy - r}" x2="{cx - 34}" y2="{cy - r - 10}" '
                       f'stroke="{ACC}" stroke-width="2.4"/>')
            out.append(f'<line x1="{cx + 18}" y1="{cy + r}" x2="{cx + 34}" y2="{cy + r + 10}" '
                       f'stroke="{ACC}" stroke-width="2.4"/>')
        elif i == 3:    # тарельчатая: два конуса-шайбы
            for dy in (-16, 6):
                yy = cy + dy
                out.append(f'<path d="M {cx - 40},{yy + 12} L {cx - 10},{yy - 6} L {cx + 10},{yy + 12} '
                           f'L {cx + 40},{yy - 6}" fill="none" stroke="{ACC}" stroke-width="2.4"/>')
            out.append(f'<line x1="{cx - 46}" y1="{cy + 24}" x2="{cx + 46}" y2="{cy + 24}" '
                       f'stroke="{MUTED}" stroke-width="0.9" stroke-dasharray="3 3"/>')
        else:           # волновая: два кольца с волной по торцу
            top = [(cx + 40 * math.cos(2 * math.pi * j / 72),
                    cy - 8 + 5 * math.sin(4 * 2 * math.pi * j / 72)) for j in range(73)]
            bot = [(cx + 40 * math.cos(2 * math.pi * j / 72),
                    cy + 10 + 5 * math.sin(4 * 2 * math.pi * j / 72)) for j in range(73)]
            out.append('<polygon points="%s" fill="rgba(43,108,176,.10)" stroke="%s" stroke-width="2"/>'
                       % (" ".join(f"{a:.1f},{b:.1f}" for a, b in top + bot[::-1]), ACC))
        out.append(text(cx, y + h - 52, name, 12, INK, "middle", "bold"))
        out.append(text(cx, y + h - 34, feature, 11, MUTED, "middle"))

    out.append(text(PX + 20, y + h - 12,
                    "Основа одна: винтовая линия или тело вращения. Отличаются концы, профиль витка и число витков.",
                    12, MUTED))
    return out


# ------------------------------------------------------- B. цена команды
def cost_panel(y, h):
    out = panel(y, h, "B", "Сколько стоит одна команда в промпте агента",
                f"посчитано по forma/instruction.py: {N_OPS} команд, знаки в UTF-8", WARN)
    per_reg = REG_CHARS / N_OPS
    per_cat = CAT_CHARS / N_OPS
    toks = lambda chars: chars / 3.2          # русский текст, ~3.2 знака на токен

    rows = [
        ("описание команды в реестре", per_reg, INK),
        ("строка команды в полном каталоге", per_cat, ACC),
        ("одно значение variant", 65, GOOD),
    ]
    x0, y0 = PX + 345, y + 84
    scale = 0.24
    for i, (name, chars, col) in enumerate(rows):
        yy = y0 + i * 32
        out.append(text(x0 - 12, yy + 5, name, 11.5, MUTED, "end"))
        wpx = chars * scale
        out.append(f'<rect x="{x0}" y="{yy - 9}" width="{wpx:.1f}" height="18" rx="3" fill="{col}" opacity="0.85"/>')
        out.append(text(x0 + wpx + 8, yy + 5, f"{chars:.0f} зн. ≈ {toks(chars):.0f} токенов",
                        11.5, col, "start", "bold"))

    total_cat = toks(CAT_CHARS)
    total_reg = toks(REG_CHARS)
    total_full = toks(FULL_CHARS)
    out.append(text(PX + 20, y + h - 66,
                    f"Реестр {N_OPS} команд: {REG_CHARS} знаков ≈ {total_reg:.0f} токенов. "
                    f"Каталог «все команды»: {total_cat / 1000:.0f} тыс. токенов.", 12, INK))
    out.append(text(PX + 20, y + h - 44,
                    f"Инструкция целиком: {FULL_CHARS} знаков ≈ {total_full:.0f} тыс. токенов — "
                    "это уже почти всё окно модели.", 12, BAD))
    out.append(text(PX + 20, y + h - 22,
                    "+26 команд × 367 токенов ≈ 9.5 тыс. токенов; +60 значений variant × 20 ≈ 1.2 тыс.",
                    12, GOOD))
    return out


# -------------------------------------------------- C. вариант и команда
def variant_panel(y, h):
    out = panel(y, h, "C", "Вариант внутри команды против новой команды",
                "одинаковое покрытие — разная цена в выборе и в промпте", GOOD)
    lx, rx = PX + 40, PX + 500
    out.append(text(lx, y + 92, "ПЯТЬ КОМАНД", 13, BAD, weight="bold"))
    out.append(text(rx, y + 92, "ОДНА КОМАНДА С ВАРИАНТОМ", 13, GOOD, weight="bold"))

    five = ["spring_compression", "spring_extension", "spring_torsion",
            "spring_disc", "spring_wave"]
    for i, s in enumerate(five):
        yy = y + 122 + i * 26
        out.append(f'<rect x="{lx}" y="{yy - 18}" width="330" height="24" rx="4" fill="#fdeceb" stroke="{BAD}" stroke-width="0.8"/>')
        out.append(text(lx + 10, yy, s, 12.5, BAD))
    out.append(text(lx, y + 252, "пять описаний, пять примеров, пять мест, где можно ошибиться",
                    11.5, MUTED))

    out.append(f'<rect x="{rx}" y="{y + 102}" width="330" height="192" rx="6" fill="#eaf5ee" stroke="{GOOD}" stroke-width="1.2"/>')
    out.append(text(rx + 12, y + 126, "spring variant=…", 13, GOOD, weight="bold"))
    for i, v in enumerate(["сжатия", "растяжения", "кручения", "тарельчатая", "волновая"]):
        yy = y + 146 + i * 19
        out.append(text(rx + 26, yy, f"· {v}", 12, INK))
    out.append(text(rx + 12, y + 278, "одно описание, общая физика, проверка одна", 11.5, MUTED))

    out.append(text(PX + 20, y + h - 22,
                    "Правило: новый примитив — только если у формы другая геометрия, а не другой режим "
                    "работы той же геометрии.", 12, INK))
    return out


def build():
    H = 975
    body = [text(PX, 42, "Семейства вместо количества: цена команды и цена варианта", 22, INK, weight="bold"),
            text(PX, 68, "Числа посчитаны по реестру команд репозитория; внешние замеры по выбору инструментов — в тексте со ссылками.",
                 13, MUTED),
            f'<line x1="{PX}" y1="86" x2="{W - PX}" y2="86" stroke="{LINE}"/>']
    body += spring_panel(104, 252)
    body += cost_panel(372, 250)
    body += variant_panel(638, 320)
    return svg(W, H + 20, "\n".join(body), "Семейства вместо количества")


def check(path: Path):
    s = path.read_text(encoding="utf-8")
    problems = []
    for num, py, ph in PANELS:
        for m in re.finditer(r'<text x="([\d.]+)" y="([\d.]+)" font-size="([\d.]+)"[^>]*'
                             r'text-anchor="([a-z]+)"[^>]*>(.*?)</text>', s):
            x, y, size, anchor, txt = (float(m.group(1)), float(m.group(2)), float(m.group(3)),
                                       m.group(4), m.group(5))
            if not (py <= y <= py + ph):
                continue
            w = len(txt) * size * CHAR_W
            left = x if anchor == "start" else (x - w / 2 if anchor == "middle" else x - w)
            if left < PX + 8 or left + w > W - PX - 8:
                problems.append(f"панель {num}: «{txt[:36]}» за полем")
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
            if a[1] <= b[0] or b[1] <= a[0] or a[3] <= b[2] or b[3] <= a[2]:
                continue
            problems.append(f"наезд: «{a[4][:26]}» и «{b[4][:26]}»")
    print("проблем:", len(problems))
    for p in problems:
        print("  ·", p)
    return not problems


def main():
    path = OUT / "families_vs_count.svg"
    path.write_text(build(), encoding="utf-8")
    print("написано:", path)
    if "--check" in sys.argv:
        sys.exit(0 if check(path) else 1)


if __name__ == "__main__":
    main()
