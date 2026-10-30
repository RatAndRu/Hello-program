#!/usr/bin/env python3
"""Схемы к документам об экономии полигонов и топологии.

Запуск: python forma/docs/make_topology_svg.py
Пишет три SVG в forma/docs/img/.
"""
from __future__ import annotations

import math
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
    s = esc(s)
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
        f'text-anchor="{anchor}" font-weight="{weight}">{s}</text>'
    )


# ---------------------------------------------------------------- 1. хорда
def chord_figure():
    W, H = 980, 520
    b = [text(28, 40, "Сегменты и ошибка хорды", 22, INK, weight="bold"),
         text(28, 66, "s = r·(1 − cos(π/n)) ≈ r·π²/(2n²): чтобы уменьшить ошибку в 4 раза, "
                      "надо удвоить число сегментов.", 13, MUTED)]

    cy = 240
    for i, n in enumerate((8, 16, 32)):
        cx = 150 + i * 205
        r = 88
        s_err = r * (1 - math.cos(math.pi / n))
        pts = " ".join(f"{cx + r * math.cos(2 * math.pi * k / n):.2f},"
                       f"{cy + r * math.sin(2 * math.pi * k / n):.2f}" for k in range(n))
        b.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{LINE}" '
                 f'stroke-width="1.2" stroke-dasharray="3 4"/>')
        b.append(f'<polygon points="{pts}" fill="rgba(43,108,176,0.10)" stroke="{ACC}" stroke-width="2"/>')
        b.append(text(cx, cy + r + 32, f"n = {n}", 15, INK, "middle", "bold"))
        b.append(text(cx, cy + r + 53, f"ошибка {s_err:.2f} ед. при r = 88", 12, MUTED, "middle"))

    # диаграмма: ошибка против n
    gx, gy = 790, 120
    bars = [(8, 0.0), (16, 0.0), (32, 0.0), (64, 0.0)]
    e0 = 1 - math.cos(math.pi / 8)
    maxw = 150
    b.append(text(gx, gy - 22, "ошибка при том же радиусе", 12.5, ACC))
    for i, (n, _) in enumerate(bars):
        e = 1 - math.cos(math.pi / n)
        y = gy + i * 34
        w = maxw * e / e0
        b.append(f'<rect x="{gx}" y="{y}" width="{w:.1f}" height="20" rx="3" fill="{ACC}" opacity="{0.85 - i * 0.15:.2f}"/>')
        b.append(text(gx + w + 8, y + 15, f"n={n}", 11.5, INK))
    b.append(text(gx, gy + 158, "×2 сегментов → ÷4 ошибки", 12, GOOD))
    b.append(text(gx, gy + 178, "×4 сегментов → ÷16 ошибки", 12, MUTED))

    b.append(text(28, 462,
                  "Практика: сегменты задаются допуском n = ⌈π / arccos(1 − s/r)⌉, "
                  "а не привычным «48 на всё».", 13.5, INK))
    b.append(text(28, 486,
                  "Печать FDM: s = 0.1–0.2 мм · SLA: 0.05 мм · рендер крупным планом: 0.05–0.1 мм · фон: 0.3–0.5 мм.",
                  13, MUTED))
    return svg(W, H, "\n".join(b), "Сегменты и ошибка хорды")


# ------------------------------------------------------- 2. плохо / лечение
def bad_good_figure():
    W, H = 1000, 750
    b = [text(28, 40, "Пять типовых дефектов сетки: как выглядит и чем лечится", 22, INK, weight="bold"),
         text(28, 66, "Слева — дефект, справа — то же место после автоматического лечения. "
                      "Подписи дают код дефекта и команду.", 13, MUTED)]

    rows = [
        ("игла (sliver)", "min-угол < 3°, высота к основанию < 1/10",
         "set_tolerance(0.05·h) — схлопнуть короткое ребро"),
        ("совпавшие вершины → non-manifold", "две грани делят ребро, но вершины не сшиты",
         "схлопывать рёбра (set_tolerance), не сваривать вершины"),
        ("T-стык / дырка (boundary)", "у ребра один сосед: грань «нависает» над краем",
         "grid fill по петле; для тела — запрет на экспорт"),
        ("вырожденная грань (degenerate)", "площадь ≈ 0, нормаль не считается",
         "удалить грань, затем dissolve коллинеарных вершин"),
        ("лесенка на изгибе (density)", "шаг 0.4 мм рядом с шагом 12 мм",
         "smooth_out + refine_to_tolerance, затем simplify"),
    ]

    top = 100
    rowh = 116
    for i, (name, why, fix) in enumerate(rows):
        y = top + i * rowh
        b.append(f'<line x1="28" y1="{y - 16}" x2="{W - 28}" y2="{y - 16}" stroke="{LINE}"/>')
        b.append(text(28, y + 4, name, 14.5, INK, weight="bold"))
        b.append(text(28, y + 26, why, 12, MUTED))
        b.append(text(28, y + 48, fix, 12, GOOD))
        draw_defect(b, i, 470, y + 18)

    b.append(text(28, H - 20,
                  "Все пять ловятся одним проходом по массивам вершин и граней за 0.1–0.3 с на 10 тыс. треугольников "
                  "(см. topology_autofix_spec.md).", 12.5, MUTED))
    return svg(W, H, "\n".join(b), "Пять дефектов сетки")


def draw_defect(b, kind, x0, y0):
    """Пара «плохо / хорошо» на каждый дефект. y0 — верх пары боксов."""
    bw, bh = 210, 84

    def frame(x, label, color):
        b.append(text(x + 2, y0 - 8, label, 11, color, "start", "bold"))
        b.append(f'<rect x="{x}" y="{y0}" width="{bw}" height="{bh}" rx="6" fill="#fcfdfe" '
                 f'stroke="{color}" stroke-width="1.4" stroke-dasharray="'
                 f'{"" if color == GOOD else "5 4"}"/>')

    def dot(x, y, r=2.6, color=INK):
        b.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')

    def tri(p1, p2, p3, fill, stroke):
        pts = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in (p1, p2, p3))
        b.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.3"/>')

    def cap(x, s_, color):
        b.append(text(x, y0 + bh - 9, s_, 10.5, color, "middle"))

    bx, gx = x0, x0 + bw + 30
    frame(bx, "дефект", BAD)
    frame(gx, "после лечения", GOOD)
    cy = y0 + 38
    cxb, cxg = bx + bw / 2, gx + bw / 2

    if kind == 0:  # игла
        tri((bx + 30, cy - 22), (bx + 180, cy - 22), (bx + 30, cy + 18), "rgba(192,57,43,.10)", BAD)
        cap(cxb, "высота 3 % длины", BAD)
        tri((gx + 34, cy - 20), (gx + 176, cy - 20), (gx + 105, cy + 20), "rgba(30,132,73,.10)", GOOD)
        cap(cxg, "близко к равностороннему", GOOD)

    elif kind == 1:  # совпавшие вершины
        tri((bx + 34, cy - 22), (bx + 108, cy - 22), (bx + 34, cy + 20), "rgba(192,57,43,.10)", BAD)
        tri((bx + 116, cy - 22), (bx + 182, cy - 22), (bx + 182, cy + 20), "rgba(192,57,43,.10)", BAD)
        b.append(f'<line x1="{bx + 108}" y1="{cy - 22}" x2="{bx + 116}" y2="{cy - 22}" stroke="{BAD}" stroke-width="3"/>')
        dot(bx + 108, cy - 22, 2.8, BAD)
        dot(bx + 116, cy - 22, 2.8, BAD)
        cap(cxb, "две вершины в одной точке", BAD)
        tri((gx + 34, cy - 22), (gx + 108, cy - 22), (gx + 34, cy + 20), "rgba(30,132,73,.10)", GOOD)
        tri((gx + 108, cy - 22), (gx + 182, cy - 22), (gx + 108, cy + 20), "rgba(30,132,73,.10)", GOOD)
        dot(gx + 108, cy - 22, 2.8, GOOD)
        cap(cxg, "вершина сшита, ребро общее", GOOD)

    elif kind == 2:  # дырка
        b.append(f'<rect x="{bx + 36}" y="{cy - 22}" width="140" height="44" rx="4" fill="{BAD}" fill-opacity="0.06" '
                 f'stroke="{BAD}" stroke-width="2"/>')
        cap(cxb, "ребро с одной гранью", BAD)
        b.append(f'<rect x="{gx + 36}" y="{cy - 22}" width="140" height="44" rx="4" fill="rgba(30,132,73,.07)" '
                 f'stroke="{GOOD}" stroke-width="2"/>')
        b.append(f'<line x1="{gx + 36}" y1="{cy}" x2="{gx + 176}" y2="{cy}" stroke="{GOOD}" stroke-width="1"/>')
        b.append(f'<line x1="{gx + 106}" y1="{cy - 22}" x2="{gx + 106}" y2="{cy + 22}" stroke="{GOOD}" stroke-width="1"/>')
        cap(cxg, "grid fill по петле", GOOD)

    elif kind == 3:  # вырожденная
        b.append(f'<polygon points="{bx + 36},{cy + 18} {bx + 180},{cy + 18} {bx + 60},{cy + 18}" '
                 f'fill="rgba(192,57,43,.35)" stroke="{BAD}" stroke-width="2"/>')
        b.append(text(cxb, cy - 2, "S = 0", 13, BAD, "middle", "bold"))
        cap(cxb, "три точки на одной прямой", BAD)
        tri((gx + 46, cy + 20), (gx + 168, cy + 20), (gx + 106, cy - 18), "rgba(30,132,73,.10)", GOOD)
        cap(cxg, "грань удалена, вершины слиты", GOOD)

    else:  # лесенка
        px = bx + 36
        b.append(f'<polyline points="{px},{cy + 20} {px},{cy - 4} {px + 88},{cy - 4} '
                 f'{px + 88},{cy + 20} {px + 140},{cy + 20}" fill="none" stroke="{BAD}" stroke-width="2"/>')
        cap(cxb, "шаг 12 мм рядом с 0.4 мм", BAD)
        b.append(f'<path d="M {gx + 36} {cy + 20} C {gx + 76} {cy - 30}, {gx + 138} {cy - 30}, {gx + 176} {cy + 20}" '
                 f'fill="rgba(30,132,73,.08)" stroke="{GOOD}" stroke-width="2"/>')
        for k in range(1, 8):
            t = k / 8
            xx = gx + 36 + 140 * t
            yy = cy + 20 - 42 * (3 * t * (1 - t))
            dot(xx, yy, 1.8, GOOD)
        cap(cxg, "плотность по кривизне", GOOD)


# --------------------------------------------------------- 3. карта лица
def face_map():
    W, H = 1000, 812
    AMBER = "#b7791f"
    b = [text(28, 38, "Карта петель лица: что правильно и что нет", 22, INK, weight="bold"),
         text(28, 62, "Орбитальная и оральная петли строятся первыми; полюса — только на плоском. "
                      "Справа — типичные ошибки новичка.", 13, MUTED)]

    def head(cx, cy, w, h, color, fill):
        b.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{w / 2}" ry="{h / 2}" fill="{fill}" '
                 f'stroke="{color}" stroke-width="2"/>')

    cy = 340
    # ------------------------------------------------ правильно
    cx = 275
    head(cx, cy, 300, 400, GOOD, "#fbfefc")
    b.append(text(cx, 118, "правильно", 15, GOOD, "middle", "bold"))

    for ex in (cx - 58, cx + 58):
        b.append(f'<ellipse cx="{ex}" cy="{cy - 60}" rx="34" ry="20" fill="none" stroke="{ACC}" stroke-width="2"/>')
        b.append(f'<ellipse cx="{ex}" cy="{cy - 60}" rx="19" ry="11" fill="none" stroke="{ACC}" stroke-width="1.2" '
                 f'stroke-dasharray="3 3"/>')
        b.append(f'<circle cx="{ex}" cy="{cy - 60}" r="4" fill="{INK}"/>')

    b.append(f'<ellipse cx="{cx}" cy="{cy + 72}" rx="56" ry="24" fill="none" stroke="#8e44ad" stroke-width="2"/>')
    b.append(f'<ellipse cx="{cx}" cy="{cy + 72}" rx="40" ry="15" fill="none" stroke="#8e44ad" stroke-width="1.2"/>')
    b.append(f'<ellipse cx="{cx}" cy="{cy + 72}" rx="26" ry="8" fill="none" stroke="#8e44ad" stroke-width="1"/>')

    b.append(f'<path d="M {cx} {cy - 24} L {cx} {cy + 24}" stroke="{ACC}" stroke-width="1.4"/>')
    b.append(f'<path d="M {cx - 18} {cy + 32} Q {cx} {cy + 42} {cx + 18} {cy + 32}" stroke="{ACC}" fill="none"/>')
    for s_ in (-1, 1):
        b.append(f'<path d="M {cx + s_ * 24} {cy + 30} L {cx + s_ * 30} {cy + 34} L {cx + s_ * 22} {cy + 44}" '
                 f'stroke="{ACC}" stroke-width="1.2" fill="none"/>')
        b.append(f'<path d="M {cx + s_ * 30} {cy + 40} Q {cx + s_ * 52} {cy + 56} {cx + s_ * 52} {cy + 70}" '
                 f'stroke="{MUTED}" stroke-width="1.2" fill="none" stroke-dasharray="4 3"/>')

    def pole(x, y, n, col):
        b.append(f'<circle cx="{x}" cy="{y}" r="8.5" fill="{col}"/>')
        b.append(text(x, y + 4, str(n), 11, "#ffffff", "middle", "bold"))

    pole(cx - 95, cy - 74, 5, GOOD)
    pole(cx + 95, cy - 74, 5, GOOD)
    pole(cx - 24, cy - 58, 3, AMBER)
    pole(cx + 24, cy - 58, 3, AMBER)
    pole(cx - 64, cy + 64, 5, GOOD)
    pole(cx + 64, cy + 64, 5, GOOD)
    pole(cx - 33, cy + 24, 3, AMBER)
    pole(cx + 33, cy + 24, 3, AMBER)

    b.append(text(cx, 600, "орбитальная петля + 2 кольца наружу, петля по кромке века",
                  12, INK, "middle"))
    b.append(text(cx, 620, "оральная петля: кромка + 2–3 кольца + ряд внутрь",
                  12, INK, "middle"))
    b.append(text(cx, 640, "петли носа уходят вниз к рту, а не в щёку",
                  12, INK, "middle"))

    # ------------------------------------------------ неправильно
    cx2 = 720
    head(cx2, cy, 300, 400, BAD, "#fffafa")
    b.append(text(cx2, 118, "неправильно", 15, BAD, "middle", "bold"))

    for yy in (cy - 140, cy - 108, cy + 118, cy + 146):
        b.append(f'<path d="M {cx2 - 140} {yy} Q {cx2} {yy + 14} {cx2 + 140} {yy}" stroke="{BAD}" '
                 f'stroke-width="1.4" fill="none"/>')
    for (x, y, n) in [(cx2 - 58, cy - 60, 6), (cx2 + 58, cy - 60, 6),
                      (cx2 - 56, cy + 72, 6), (cx2 + 56, cy + 72, 6), (cx2, cy + 100, 8)]:
        b.append(f'<circle cx="{x}" cy="{y}" r="11.5" fill="{BAD}"/>')
        b.append(text(x, y + 4, str(n), 12, "#ffffff", "middle", "bold"))
    b.append(f'<ellipse cx="{cx2}" cy="{cy + 72}" rx="56" ry="24" fill="none" stroke="{BAD}" '
             f'stroke-width="1.2" stroke-dasharray="4 4"/>')

    b.append(text(cx2, 600, "петли идут поперёк мышц и через глаз / рот", 12, BAD, "middle"))
    b.append(text(cx2, 620, "полюса 6 и 8 — в самых подвижных точках", 12, BAD, "middle"))
    b.append(text(cx2, 640, "плотность ровная «как получилось»", 12, BAD, "middle"))

    # ------------------------------------------------ легенда
    b.append(f'<line x1="60" y1="686" x2="{W - 60}" y2="686" stroke="{LINE}"/>')
    items = [
        (ACC, "орбитальная и носовая петли"),
        ("#8e44ad", "оральная петля"),
        (MUTED, "носогубная связка"),
        (GOOD, "5-полюс: разводка на скуле и уголке рта"),
        (AMBER, "3-полюс: терминатор у слёзника и ноздри"),
    ]
    for i, (c, s_) in enumerate(items):
        col = i % 2
        row = i // 2
        x = 60 + col * 470
        y = 714 + row * 24
        b.append(f'<circle cx="{x + 7}" cy="{y - 4}" r="7" fill="{c}"/>')
        b.append(text(x + 22, y, s_, 12, INK))

    b.append(text(60, 800,
                  "6-полюс на деформации запрещён. Полюс в уголке рта неизбежен — его отодвигают "
                  "на 1–2 квада наружу, а не оставляют в подвижной точке.", 12, MUTED))

    return svg(W, H, "\n".join(b), "Карта петель лица")


def main():
    (OUT / "mesh_chord_error.svg").write_text(chord_figure(), encoding="utf-8")
    (OUT / "topology_bad_good.svg").write_text(bad_good_figure(), encoding="utf-8")
    (OUT / "face_loops.svg").write_text(face_map(), encoding="utf-8")
    print("ok:", *(p.name for p in sorted(OUT.glob("*.svg"))))


if __name__ == "__main__":
    main()
