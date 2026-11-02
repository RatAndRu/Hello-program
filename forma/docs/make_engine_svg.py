#!/usr/bin/env python3
"""Схемы к docs/own_engine_and_model.md.

    python forma/docs/make_engine_svg.py [--check]

Пишет два SVG в forma/docs/img/:
  engine_layers.svg  — двенадцать слоёв игрового движка и что из них у нас есть
  nn_where.svg       — где живёт нейросеть: данные, обучение, запуск

Числа — из docs/own_engine_and_model.md: размеры кода через GitHub languages API,
лимиты — из документации GitHub, скорость — замер docs/train_budget.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "img"
OUT.mkdir(exist_ok=True)

FONT = 'font-family="DejaVu Sans, Segoe UI, Arial, sans-serif"'
INK, MUTED = "#1f2933", "#6b7785"
BAD, GOOD, ACC, WARN = "#c0392b", "#1e8449", "#2b6cb0", "#b7791f"
BG, LINE, SOFT = "#ffffff", "#d5dbe1", "#fcfdfe"

BOXES: list[tuple[str, float, float, float, float]] = []

try:
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
except Exception:                       # без PIL — грубая оценка
    def tw(s, size, bold=False):
        return len(str(s)) * size * 0.62


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


def chip(x, y, label, color, size=10.5):
    w = tw(label, size, True) + 16
    return (f'<rect x="{x:.1f}" y="{y - 12:.1f}" width="{w:.1f}" height="18" rx="9" '
            f'fill="{color}" opacity="0.12"/>'
            f'<rect x="{x:.1f}" y="{y - 12:.1f}" width="{w:.1f}" height="18" rx="9" '
            f'fill="none" stroke="{color}" stroke-width="0.9"/>'
            + text(x + w / 2, y + 1.5, label, size, color, "middle", "bold"))


def arrow(x0, y0, x1, y1, color=MUTED, width=1.5, head=7):
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    bx, by = x1 - head * math.cos(ang), y1 - head * math.sin(ang)
    p1 = (bx - head * 0.5 * math.sin(ang), by + head * 0.5 * math.cos(ang))
    p2 = (bx + head * 0.5 * math.sin(ang), by - head * 0.5 * math.cos(ang))
    return (f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
            f'stroke="{color}" stroke-width="{width}"/>'
            f'<polygon points="{x1:.1f},{y1:.1f} {p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}" '
            f'fill="{color}"/>')


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" {FONT}>\n<title>{esc(title)}</title>\n'
            f'<rect width="{w}" height="{h}" fill="{BG}"/>\n' + "\n".join(body) + "\n</svg>\n")


def header(title, sub, w=1000):
    return [text(28, 42, title, 22, INK, weight="bold"), text(28, 68, sub, 13, MUTED),
            f'<line x1="28" y1="86" x2="{w - 28}" y2="86" stroke="{LINE}"/>']


# ===================================================== 1. СЛОИ ДВИЖКА
def fig_layers():
    n0 = len(BOXES)
    W, H = 1000, 830
    body = header("Двенадцать слоёв игрового движка: что из этого у нас уже есть",
                  "слева — слой и его работа; в середине — порядок объёма кода; справа — статус в ФОРМЕ")
    rows = [
        ("1. Рантайм и память", "запуск сцены, сборка мусора, горячая перезагрузка скриптов", "10⁴–10⁵", "нет", BAD),
        ("2. Сериализация сцены", "сцены и префабы как файлы, ссылки на ассеты, миграции", "10⁴", "нет (есть DSL)", WARN),
        ("3. Рендерер", "конвейеры, шейдеры, тени, постобработка, батчинг", "10⁵–10⁶", "чужой: three.js", GOOD),
        ("4. Физика", "столкновения, твёрдые тела, шарниры, ткань", "10⁵", "чужой: не подключён", WARN),
        ("5. Анимация", "скелет, морфы, стейт-машины, кривые", "10⁴–10⁵", "часть: morph, keys", WARN),
        ("6. Импорт ассетов", "FBX/GLB/PNG/звук → внутренний формат и GUID", "10⁴", "часть: GLB, OBJ, STL", WARN),
        ("7. Звук", "микшер, 3D-панорама, события", "10⁴", "нет", BAD),
        ("8. Ввод и UI", "клавиши, геймпад, канвас, раскладка", "10⁴", "нет", BAD),
        ("9. Навигация и ИИ", "сетка проходимости, поиск пути, поведение", "10⁴", "нет", BAD),
        ("10. Редактор", "инспектор, гизмо, undo, режим Play", "10⁵", "свой, но простой", WARN),
        ("11. Сборка под платформы", "Windows, Web, Android, консоли, подпись", "10⁴–10⁵", "Web (GLB), exe", WARN),
        ("12. Сеть и сервисы", "мультиплеер, аккаунты, магазин, аналитика", "10⁴", "нет", BAD),
    ]
    y0, rh = 100, 52
    for i, (name, what, size, status, color) in enumerate(rows):
        y = y0 + i * rh
        BOXES.append((f"row{i}", 28, y, 944, rh - 6))
        body.append(f'<rect x="28" y="{y}" width="944" height="{rh - 6}" rx="6" fill="{SOFT}" stroke="{LINE}"/>')
        body.append(f'<rect x="28" y="{y}" width="3.5" height="{rh - 6}" fill="{color}"/>')
        body.append(text(44, y + 20, name, 12.4, INK, weight="bold"))
        body.append(text(44, y + 37, what, 10.2, MUTED))
        body.append(text(520, y + 27, size, 11, ACC))
        body.append(chip(660, y + 24, status, color))
    body += para(28, 742,
                 "Объём — порядок строк кода, а не точная цифра: у Godot 2,1 млн строк C++ "
                 "(73,6 МБ кода), у three.js 0,5 млн, у Babylon 1,4 млн, у ядра Bevy 0,65 млн. "
                 "У ФОРМЫ 44,5 тыс. строк Python — и это только геометрия, то есть слои 4–12.",
                 944, 11.6, INK)
    body += para(28, 792,
                 "Вывод: «свой движок» — это не 12 слоёв, а один. Форма уже доказала, что "
                 "один слой можно сделать хорошо; делать остальные одиннадцать — это годы.",
                 944, 11.6, MUTED)
    return svg(W, H, body, "Слои игрового движка"), BOXES[n0:]


# ===================================================== 2. ГДЕ ЖИВЁТ СЕТЬ
def fig_nn():
    n0 = len(BOXES)
    W, H = 1000, 720
    body = header("Где живёт нейросеть: данные, обучение, запуск",
                  "три разные машины; путать их — главная ошибка в планах «обучу на GitHub»")

    cols = [
        ("Данные", ACC, [
            ("своё ядро ФОРМЫ", "случайные сцены → рендер + маска + SDF", "метки точные, даром"),
            ("фото из сети", "100–50 000 снимков", "метки руками или готовой моделью"),
            ("разметка", "маска, кромки, габарит", "SAM/Depth Anything вместо человека"),
        ]),
        ("Обучение", WARN, [
            ("ноутбук, 2 ядра", "150 GFLOP/s, 1–2 дня на голову", "бесплатно, медленно"),
            ("GitHub runner, 4 ядра", "6 ч на job, без GPU", "бесплатно для публичных репо"),
            ("GPU в аренду", "T4-класс, 1–3 ч на голову", "10–30 ₽/ч, нужен за рубежом"),
        ]),
        ("Запуск", GOOD, [
            ("ноутбук, ONNX", "1–20 M параметров → 45 мс", "5–80 МБ, без интернета"),
            ("браузер, WASM", "то же, 100–300 мс", "вместе с игрой на GitHub Pages"),
            ("сервер", "только если модель большая", "дорого, нужен хостинг"),
        ]),
    ]
    cw, gap = 300, 22
    for ci, (title, color, items) in enumerate(cols):
        x = 28 + ci * (cw + gap)
        body.append(f'<rect x="{x}" y="104" width="{cw}" height="404" rx="10" fill="{SOFT}" stroke="{color}" stroke-width="1.4"/>')
        body.append(text(x + 16, 132, title, 15, INK, weight="bold"))
        BOXES.append((f"col{ci}", x, 104, cw, 404))
        for k, (name, what, note) in enumerate(items):
            yy = 156 + k * 116
            body.append(f'<rect x="{x + 14}" y="{yy}" width="{cw - 28}" height="100" rx="7" fill="#ffffff" stroke="{LINE}"/>')
            body.append(text(x + 26, yy + 22, name, 11.6, color, weight="bold"))
            body += para(x + 26, yy + 42, what, cw - 52, 10.2, INK, 13)
            body.append(text(x + 26, yy + 70, note, 9.6, MUTED))
        if ci < 2:
            body.append(arrow(x + cw + 2, 306, x + cw + gap - 2, 306, MUTED, 1.6, 7))

    body.append(text(28, 552, "Что это значит на практике", 13, INK, weight="bold"))
    body += para(28, 576,
                 "Данные делает наше ядро, обучение — чужая машина на несколько часов, запуск — "
                 "ноутбук и браузер. GitHub стоит только в середине и только для маленьких сетей: "
                 "4 ядра, 16 ГБ, 14 ГБ диска, 6 часов на job, без GPU.", 944, 11.8, INK)

    # нижняя плашка: цифры
    body.append(f'<rect x="28" y="628" width="944" height="64" rx="8" fill="#eef3f9" stroke="{ACC}"/>')
    body.append(text(44, 652, "1,7–4,4 M параметров", 13, ACC, weight="bold"))
    body.append(text(268, 652, "обучается за 2 job'а по 6 ч", 11.6, INK))
    body.append(text(560, 652, "17 МБ весов", 12.4, GOOD, weight="bold"))
    body.append(text(660, 652, "45 мс на кадр на CPU", 11.6, INK))
    body.append(text(44, 676, "70 M и больше", 13, BAD, weight="bold"))
    body.append(text(268, 676, "уже 15–27 job'ов, недели", 11.6, INK))
    body.append(text(560, 676, "~1 млрд (TripoSR)", 12.4, BAD, weight="bold"))
    body.append(text(700, 676, "10³–10⁵ GPU-часов", 11.6, INK))
    return svg(W, H, body, "Где живёт нейросеть"), BOXES[n0:]


# ===================================================== ПРОВЕРКА
_TXT_RE = (r'<text x="([\d.]+)" y="([\d.]+)" font-size="([\d.]+)" fill="[^"]+" '
           r'text-anchor="([a-z]+)" font-weight="([a-z]+)"[^>]*>(.*?)</text>')


def _texts(svg_text):
    for m in re.finditer(_TXT_RE, svg_text):
        yield (float(m.group(1)), float(m.group(2)), float(m.group(3)),
               m.group(4), m.group(5), m.group(6))


def check(path: Path, panels):
    s = path.read_text(encoding="utf-8")
    problems = []
    cw, chh = re.search(r'width="(\d+)" height="(\d+)"', s).groups()
    cw, chh = int(cw), int(chh)
    for tx, ty, size, anchor, wd, txt in _texts(s):
        wd = tw(txt, size, wd != "normal")
        left = tx if anchor == "start" else (tx - wd / 2 if anchor == "middle" else tx - wd)
        if left < 20 or left + wd > cw - 20:
            problems.append(f"за холстом: «{txt[:36]}» ({left + wd - (cw - 20):+.0f} px)")
        if ty > chh - 8:
            problems.append(f"ниже холста: «{txt[:36]}» ({ty - (chh - 8):+.0f} px)")
    for name, x, y, w, h in panels:
        for tx, ty, size, anchor, wd, txt in _texts(s):
            if not (x <= tx <= x + w and y <= ty <= y + h):
                continue
            wd = tw(txt, size, wd != "normal")
            left = tx if anchor == "start" else (tx - wd / 2 if anchor == "middle" else tx - wd)
            if left < x + 6 or left + wd > x + w - 6:
                problems.append(f"{name}: «{txt[:32]}» вылезает ({left + wd - (x + w):+.0f} px)")
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
    for p in problems[:12]:
        print("     ·", p)
    return not problems


def main():
    figs = [("engine_layers.svg", fig_layers), ("nn_where.svg", fig_nn)]
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


if __name__ == "__main__":
    main()
