"""Словесное сопровождение для совместной работы с нейросетью.

Приложение может само сформулировать запрос к помощнику: что строим,
какие есть ограничения, что уже сделано. Это делает цикл
«команда → построение → проверка → правка» удобным и для человека,
и для модели.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

from .run import Build, commands_help

DOCS_INDEX = """СПРАВКА ФОРМА 3D (кратко)
Единицы: миллиметры. Ось Z — вверх, пол по z=0. Файл проекта — обычный текст,
одна команда на строку. Цикл работы: строим → читаем отчёт и PNG-виды → правим → снова.

БАЗОВЫЕ ПРИМИТИВЫ
  имя = box size=[x,y,z] [round=r] [at=[x,y,z]]
  имя = sphere radius=r [at=[x,y,z]]
  имя = cylinder radius=r height=h [r2=верхний] [round=r]
  имя = cone radius=r height=h
  имя = torus major=R minor=r
  имя = prism sides=n radius=r height=h
  имя = capsule radius=r height=h
  имя = hull [объекты] | hull points=[[x,y,z],...]

ТЕЛА ВРАЩЕНИЯ И РАЗВЁРТКИ (главное для посуды и кузовов)
  имя = lathe points=[[r,z],...] [segments=128] [fillet=r] [smooth=n]
  имя = extrude profile=[[x,y],...] height=h [fillet=r] [holes=[[[...]]]] [twist=deg]
  имя = sweep path=[[x,y,z],...] radius=r | [profile=[[x,y],...]] [smooth=n] [closed_path=true]
  имя = loft sections=[[[...]],[...]] [positions=[...]] [axis=x|y|z] [smooth=n]

БУЛЕВЫ
  имя = union [a, b]    имя = difference [основа, вычитаемое]    имя = intersect [a, b]
  имя = shell [a] thickness=t open=top|bottom|both|none
  имя = offset [a] delta=+2      имя = fillet [a] radius=r (скругление стыков)

МАССИВЫ И ПРЕОБРАЗОВАНИЯ
  имя = array [a] count=n mode=linear|radial|grid [offset=] [around=z] [counts=] [spacing=]
  имя = translate [a] offset=[dx,dy,dz]     имя = rotate [a] angle=deg axis=z
  имя = scale [a] factor=2 | factor=[sx,sy,sz]
  имя = mirror [a] plane=x [keep=true]      имя = place [a] at=[x,y,z] align=bottom
  имя = twist [a] angle=deg | taper [a] factor=0.6 | bend [a] angle=deg
  имя = refine [a] length=1.5 | simplify [a] tolerance=0.3

МАТЕМАТИЧЕСКИЕ ПОВЕРХНОСТИ
  имя = from_sdf expression="sd_sphere(x,y,z,30)-sd_sphere(x,y,z,24)" bounds=[...] resolution=1.5
  имя = blob spheres=[[x,y,z,r],...] capsules=[[x1,y1,z1,x2,y2,z2,r],...] blend=12

ПАРАМЕТРЫ, ЦВЕТ, ПРОВЕРКИ
  толщина = 4            (параметр; используется в выражениях: height=толщина*2)
  color имя material=ceramic|metal|wood|plastic | color=#RRGGBB
  show/hide имя
  check имя watertight | genus 1 | parts 1 | height 90..110 | size 80..100 80..100 90..110
  check имя volume 300..500 | mass 200..400 | wall 3..5 | flat_bottom 5.. | overhang ..20
  check имя symmetric y | tris ..200000 | gap другой 0.5..2 | inside другой

ОТЧЁТ
  После построения приложение возвращает: габариты, объём, массу, толщину стенок,
  симметрию, нависания, плоское дно, число частей, род, проверки ✓/✗, замечания.
  Плюс PNG четырёх видов: изометрия, спереди, справа, сверху.
"""


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def build_prompt(build: Build | None, goal: str = "", out_path: str | None = None) -> str:
    parts = []
    parts.append("# Запрос к помощнику по проекту «ФОРМА 3D»")
    parts.append("")
    parts.append(f"Дата: {_now()}")
    if goal.strip():
        parts.append("")
        parts.append("## Что требуется")
        parts.append(goal.strip())
    parts.append("")
    parts.append("## Текущий сценарий")
    parts.append("```forma")
    parts.append((build.script if build else "").strip() or "# пусто")
    parts.append("```")
    if build and build.ok and build.analysis:
        parts.append("")
        parts.append("## Отчёт приложения о результате")
        parts.append("```")
        parts.append(build.analysis.get("text", "").strip())
        parts.append("```")
    elif build and build.error:
        parts.append("")
        parts.append("## Ошибка построения")
        parts.append(f"{build.error.get('message')} (строка {build.error.get('line')})")
        if build.error.get("hint"):
            parts.append(f"Подсказка: {build.error['hint']}")
    parts.append("")
    parts.append("## Как отвечать")
    parts.append(
        "1. Сначала коротко скажи, что не так или что нужно изменить (словами, по измерениям).\n"
        "2. Затем выдай ПОЛНЫЙ новый сценарий в одном блоке ```forma — без сокращений.\n"
        "3. Добавь или обнови строки check, чтобы результат можно было проверить словами.\n"
        "4. Укажи, какие виды (изометрия/спереди/справа/сверху) нужно посмотреть, чтобы убедиться."
    )
    parts.append("")
    parts.append("## Справочник команд")
    parts.append(DOCS_INDEX)
    text = "\n".join(parts)
    if out_path:
        Path(os.path.dirname(os.path.abspath(out_path))).mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(text, encoding="utf-8")
    return text


def commands_markdown() -> str:
    rows = ["| Команда | Что делает | Пример |", "|---|---|---|"]
    by_cat: dict[str, list] = {}
    for spec in commands_help():
        by_cat.setdefault(spec["category"], []).append(spec)
    for cat, specs in by_cat.items():
        rows.append(f"| **{cat}** | | |")
        for s in specs:
            example = s.get("example", "").replace("\n", "<br>").replace("|", "\\|")
            summary = s.get("summary", "").replace("|", "\\|")
            rows.append(f"| `{s['name']}` | {summary} | `{example}` |")
    return "\n".join(rows)


def command_reference_md() -> str:
    out = ["# Справочник команд ФОРМА 3D", ""]
    by_cat: dict[str, list] = {}
    for spec in commands_help():
        by_cat.setdefault(spec["category"], []).append(spec)
    for cat, specs in by_cat.items():
        out.append(f"## {cat}")
        out.append("")
        for s in specs:
            out.append(f"### {s['name']}")
            if s.get("aliases"):
                out.append(f"Синонимы: {', '.join(s['aliases'])}")
            out.append("")
            out.append(s.get("summary", ""))
            out.append("")
            if s.get("params"):
                out.append("| Параметр | Описание |")
                out.append("|---|---|")
                for p in s["params"]:
                    out.append(f"| `{p['name']}` | {p['desc']} |")
                out.append("")
            if s.get("example"):
                out.append("```forma")
                out.append(s["example"])
                out.append("```")
                out.append("")
    return "\n".join(out)
