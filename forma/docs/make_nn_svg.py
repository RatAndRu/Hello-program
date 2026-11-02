#!/usr/bin/env python3
"""Схемы к docs/neural_network_explained.md.

    python forma/docs/make_nn_svg.py [--check]

Пишет два SVG в forma/docs/img/:

  nn_files.svg       — из чего физически состоит сеть: 4 файла и байты весов
  nn_who_does_what.svg — что делает сеть, а что геометрия ядра; шкала размеров

Числа совпадают с прогоном `forma/ml/demo.py` (144 135 параметров, 563 КБ,
словарь 43 токена) и с `docs/train_budget.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_engine_svg import (ACC, BAD, BG, BOXES, GOOD, INK, LINE, MUTED,  # noqa: E402
                             SOFT, WARN, arrow, check, chip, header, para, svg, text)

OUT = Path(__file__).resolve().parent / "img"
OUT.mkdir(exist_ok=True)


# ============================================ 1. ЧЕТЫРЕ ФАЙЛА И БАЙТЫ ВЕСОВ
def fig_files():
    n0 = len(BOXES)
    W, H = 1000, 760
    body = header("Нейросеть — это четыре файла, и ни один из них не exe",
                  "веса — просто числа подряд; архитектура — двадцать строк кода, который эти числа умножает")

    # левая колонка: список файлов
    files = [
        ("head.safetensors", "563 КБ", "числа", GOOD,
         "8 байт длины заголовка + JSON с формой матриц + сырые float32"),
        ("head.json", "0,7 КБ", "конфиг", ACC,
         "n_in=555, n_hidden=256, n_out=7, средние и разбросы меток"),
        ("vocab.json", "0,5 КБ", "словарь", ACC,
         "43 токена: имена команд, поля, <num>, цифры"),
        ("ml/mlp.py", "6,8 КБ", "код", WARN,
         "два умножения матриц, tanh, разворот меток — и всё"),
    ]
    y0 = 104
    for i, (name, size, kind, color, what) in enumerate(files):
        y = y0 + i * 74
        BOXES.append((f"f{i}", 28, y, 470, 66))
        body.append(f'<rect x="28" y="{y}" width="470" height="66" rx="7" fill="{SOFT}" stroke="{LINE}"/>')
        body.append(f'<rect x="28" y="{y}" width="3.5" height="66" fill="{color}"/>')
        body.append(text(44, y + 22, name, 12.6, INK, weight="bold"))
        body.append(text(232, y + 22, size, 11.4, color, weight="bold"))
        body.append(chip(320, y + 18, kind, color))
        body.append(text(44, y + 40, what[:62], 9.9, MUTED))
        if len(what) > 62:
            body.append(text(44, y + 54, what[62:], 9.9, MUTED))

    body.append(text(28, 424, "Ни один не исполняется сам по себе: числа лежат отдельно от кода.", 11.8, INK))

    # правая колонка: байты
    body.append(f'<rect x="520" y="104" width="452" height="330" rx="9" fill="#f7fafc" stroke="{ACC}"/>')
    body.append(text(538, 130, "head.safetensors, первые 48 байт", 12.4, ACC, weight="bold"))
    rows = [
        ("08 01 00 00 00 00 00 00", "длина заголовка: 264 байта", GOOD),
        ('{"W1":{"dtype":"F32",', "JSON: имя тензора, тип", INK),
        (' "shape":[555,256],', "форма: 555 входов, 256 нейронов", INK),
        (' "data_offsets":[0,', "где в файле начинаются числа", INK),
        ("  568320]},", "конец: 555·256·4 = 568 320 байт", INK),
        ("...", "дальше — сами float32 подряд", MUTED),
    ]
    BOXES.append(("bytes", 520, 104, 452, 330))
    for i, (code, note, color) in enumerate(rows):
        y = 160 + i * 43
        body.append(text(538, y, code, 11.2, color, weight="bold"))
        body.append(text(538, y + 16, note, 9.6, MUTED))
    body.append(text(538, 418, "Итого 144 135 чисел × 4 байта ≈ 563 КБ.", 10.4, INK))

    # нижняя полоса: форматы
    body.append(text(28, 474, "Те же числа в других обёртках", 12.6, INK, weight="bold"))
    fmts = [
        (".pt / .pth", "zip с pickle: код исполняется при загрузке", BAD),
        (".ckpt", "то же, формат TensorFlow/PyTorch Lightning", WARN),
        (".onnx", "граф + веса в protobuf, считается без Python", GOOD),
        (".gguf", "квантованные веса LLM: 4 бита вместо 32", ACC),
        (".safetensors", "только числа, ничего не исполняется", GOOD),
    ]
    for i, (name, what, color) in enumerate(fmts):
        x = 28 + (i % 3) * 316
        y = 494 + (i // 3) * 62
        w = 300
        BOXES.append((f"fmt{i}", x, y, w, 54))
        body.append(f'<rect x="{x}" y="{y}" width="{w}" height="54" rx="6" fill="#ffffff" stroke="{color}"/>')
        body.append(text(x + 14, y + 21, name, 11.6, color, weight="bold"))
        body.append(text(x + 14, y + 39, what[:46], 9.5, MUTED))

    body += para(28, 640,
                 "exe нужен ровно в одном случае: когда веса вшивают в бинарник, чтобы получатель не мог "
                 "их заменить. Тогда к 563 КБ чисел добавляется интерпретатор — 20 строк превращаются "
                 "в 10–50 МБ рантайма. Для нас это лишнее: файл весов читается за 3 мс.", 944, 11.2, INK)
    body += para(28, 690,
                 "И наоборот: 4,4 M параметров — это 17 МБ в float32 и 4,4 МБ в int8. Такой файл "
                 "пересылается почтой, лежит в репозитории и не требует ни GPU, ни установки.", 944, 11.2, MUTED)
    return svg(W, H, body, "Файлы нейросети"), BOXES[n0:]


# ============================================ 2. КТО ЧТО ДЕЛАЕТ
def fig_split():
    n0 = len(BOXES)
    W, H = 1000, 700
    body = header("Что делает сеть, а что геометрия: граница проходит по проверяемости",
                  "сеть выдаёт числа-подсказки; всё, что можно посчитать точно, считает ядро")

    # две дорожки
    body.append(f'<rect x="28" y="100" width="944" height="128" rx="9" fill="#eef7f0" stroke="{GOOD}"/>')
    body.append(text(44, 124, "НЕЙРОСЕТЬ — там, где правила нет", 12.6, GOOD, weight="bold"))
    body.append(f'<rect x="28" y="242" width="944" height="128" rx="9" fill="#f7fafc" stroke="{ACC}"/>')
    body.append(text(44, 266, "ЯДРО — там, где есть формула или проверка", 12.6, ACC, weight="bold"))

    net = [("картинка\nили текст", 44), ("маска\nсилуэта", 236), ("20 чисел:\nгабарит, наклон", 428),
           ("токены DSL:\nпримитив + числа", 620)]
    for label, x in net:
        body.append(f'<rect x="{x}" y="140" width="168" height="70" rx="7" fill="#ffffff" stroke="{GOOD}"/>')
        for k, line in enumerate(label.split("\n")):
            body.append(text(x + 84, 166 + k * 17, line, 10.6, INK, "middle"))
    for x in (216, 408, 600):
        body.append(arrow(x - 2, 175, x + 16, 175, GOOD, 1.5, 6))
    BOXES.append(("net", 28, 100, 944, 128))

    core = [("разбор\nсценария", 44), ("сборка\nтел", 236), ("проверки\n25 правил", 428),
            ("метрики\nточные", 620)]
    for label, x in core:
        body.append(f'<rect x="{x}" y="282" width="168" height="70" rx="7" fill="#ffffff" stroke="{ACC}"/>')
        for k, line in enumerate(label.split("\n")):
            body.append(text(x + 84, 308 + k * 17, line, 10.6, INK, "middle"))
    for x in (216, 408, 600):
        body.append(arrow(x - 2, 317, x + 16, 317, ACC, 1.5, 6))
    BOXES.append(("core", 28, 242, 944, 128))
    body.append(arrow(704, 278, 704, 214, MUTED, 1.4, 6))
    body.append(text(716, 250, "проверка не прошла — назад в сеть", 9.4, MUTED))

    # шкала размеров
    body.append(text(28, 404, "Сколько параметров нужно, чтобы это работало", 12.6, INK, weight="bold"))
    x0, x1, y = 120, 940, 470
    body.append(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{LINE}" stroke-width="2"/>')
    marks = [
        (0.00, "0,14 M", "эта демонстрация", GOOD),
        (0.35, "0,1–1 M", "голова: 20 чисел", GOOD),
        (0.60, "4,4 M", "SDF 32³, 12,7 ч", WARN),
        (0.80, "70 M", "U-Net 96, 6,8 сут", BAD),
        (0.97, "~1000 M", "TripoSR: 10³–10⁵ GPU-ч", BAD),
    ]
    for pos, big, small, color in marks:
        x = x0 + pos * (x1 - x0)
        body.append(f'<line x1="{x:.0f}" y1="{y - 7}" x2="{x:.0f}" y2="{y + 7}" stroke="{color}" stroke-width="2"/>')
        body.append(f'<circle cx="{x:.0f}" cy="{y}" r="4" fill="{color}"/>')
        anchor = "middle" if pos > 0.05 else "start"
        body.append(text(x, y - 14, big, 10.6, color, anchor, "bold"))
        body.append(text(x, y + 24, small, 9.2, MUTED, anchor))
    body += para(28, 530,
                 "Слева — то, что считается на ноутбуке за минуты и даёт проверяемый результат. "
                 "Справа — то, что требует GPU, недель и всё равно ошибается: большая модель не "
                 "гарантирует правильной геометрии, она гарантирует только правдоподобную картинку.",
                 944, 11.2, INK)
    body += para(28, 586,
                 "Поэтому у нас сеть отвечает за выбор и оценку, а сборку, топологию и допуски "
                 "делает код, у которого есть ответ «да/нет». Это не компромисс, а разделение "
                 "ответственности: у чисел сети нет способа доказать свою правоту.", 944, 11.2, MUTED)
    return svg(W, H, body, "Сеть и геометрия"), BOXES[n0:]


def main():
    figs = [("nn_files.svg", fig_files), ("nn_who_does_what.svg", fig_split)]
    ok = True
    for name, fn in figs:
        BOXES.clear()
        s, panels = fn()
        p = OUT / name
        p.write_text(s, encoding="utf-8")
        print("написано:", p)
        if "--check" in sys.argv:
            ok = check(p, panels) and ok
    if "--check" in sys.argv:
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
