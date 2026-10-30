#!/usr/bin/env python3
"""Собрать самодостаточный index.html из шаблона и ассетов.

Зачем: сайт должен открываться без сервера, без сети и без сборки на стороне
читателя — двойным кликом по файлу или внутри sandbox-iframe. Поэтому CSS, JS и
все 31 схема зашиваются прямо в один HTML-файл (схемы — как data:URI).

    python3 forma/topology-course/build.py            # собрать index.html
    python3 forma/topology-course/build.py --check    # только проверить сборку

Исходники: src/template.html, styles.css, app.js, assets/fig/*.svg.
Собранный index.html перезаписывается целиком — правьте исходники.
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TPL = ROOT / "src" / "template.html"
CSS = ROOT / "styles.css"
JS = ROOT / "app.js"
FIG_DIR = ROOT / "assets" / "fig"
OUT = ROOT / "index.html"

# Пары «плохо / лечение» из app.js: ключи должны иметь оба файла.
GALLERY_KEY = re.compile(r'key:\s*"([a-z0-9-]+)"')
IMG_SRC = re.compile(r'src="assets/fig/([a-z0-9-]+\.svg)"')


def data_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:image/svg+xml;base64," + payload


def collect_figures() -> dict[str, str]:
    return {p.name: data_uri(p) for p in sorted(FIG_DIR.glob("*.svg"))}


def build(write: bool = True) -> tuple[str, list[str]]:
    problems: list[str] = []

    if not TPL.exists():
        raise SystemExit(f"нет шаблона: {TPL}")

    tpl = TPL.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    figures = collect_figures()

    if not figures:
        problems.append("в assets/fig нет ни одной схемы — запустите tools/make_topology_figures.py")

    # 1. Схемы: <img src="assets/fig/x.svg"> -> data:URI
    used: set[str] = set()

    def swap_img(match: re.Match[str]) -> str:
        name = match.group(1)
        used.add(name)
        if name not in figures:
            problems.append(f"в шаблоне ссылка на отсутствующую схему: {name}")
            return match.group(0)
        return 'src="' + figures[name] + '"'

    html = IMG_SRC.sub(swap_img, tpl)

    # 2. Схемы галереи, которые подставляет app.js по ключу пары
    for key in GALLERY_KEY.findall(js):
        for suffix in ("-bad.svg", "-good.svg"):
            name = key + suffix
            used.add(name)
            if name not in figures:
                problems.append(f"галерея: нет схемы {name}")

    unused = sorted(set(figures) - used)
    if unused:
        problems.append("схемы не используются на странице: " + ", ".join(unused))

    # 4. CSS и JS внутрь файла
    link = '<link rel="stylesheet" href="styles.css">'
    if link not in html:
        problems.append("в шаблоне не найден <link> на styles.css")
    html = html.replace(link, "<style>\n" + css.strip() + "\n</style>", 1)

    script = '<script src="app.js"></script>'
    if script not in html:
        problems.append("в шаблоне не найден <script src=\"app.js\">")
    fig_map = "window.TOPO_FIG = {" + ",".join(
        '"%s":"%s"' % (name, uri) for name, uri in sorted(figures.items())
    ) + "};"
    inline = "<script>\n" + fig_map + "\n</script>\n<script>\n" + js.strip() + "\n</script>"
    html = html.replace(script, inline, 1)

    # 5. Целостность разметки: уникальные id, живые якоря.
    ids = re.findall(r'\bid="([^"]+)"', html)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        problems.append("повторяющиеся id: " + ", ".join(dupes))
    for anchor in re.findall(r'href="#([^"]+)"', html):
        if anchor not in ids:
            problems.append(f"якорь #{anchor} не найден")

    # 6. Контроль: страница не должна ничего догружать извне.
    #    Разрешены только data:URI, якоря (#...) и абсолютные адреса в <a href>
    #    (это текстовые ссылки на источники, а не загрузка ресурсов).
    for m in re.finditer(r'\b(src|href)="([^"]*)"', html):
        attr, value = m.group(1), m.group(2)
        if value.startswith("data:") or value.startswith("#"):
            continue
        if attr == "href" and value.startswith(("http://", "https://", "mailto:")):
            continue
        line_no = html.count("\n", 0, m.start()) + 1
        problems.append(f"строка {line_no}: внешний ресурс {attr}=\"{value[:60]}\"")
    for bad in ("@import", "url(http"):
        if bad in css:
            problems.append(f"styles.css содержит внешнюю загрузку «{bad}»")

    if write and not problems:
        OUT.write_text(html, encoding="utf-8")

    return html, problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Сборка одностраничного index.html")
    ap.add_argument("--check", action="store_true", help="не писать файл, только проверить")
    args = ap.parse_args(argv)

    html, problems = build(write=not args.check)

    if problems:
        print("Проблемы сборки:")
        for p in problems:
            print("  •", p)
        return 1

    kb = len(html.encode("utf-8")) / 1024
    action = "проверено" if args.check else "записано"
    print(f"{action}: {OUT.name} — {kb:.0f} КБ, схем: {len(collect_figures())}, "
          f"строк: {len(html.splitlines())}")
    print(f"внешних ссылок на ассеты: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
