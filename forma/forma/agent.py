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
  имя = heart width=60 depth=18 round=3          — сердце настоящей формы
  имя = plus arm=60 thick=18 depth=14 round=2    — плюс/перекрестие
  имя = sector radius=50 angle=90 [thickness=4] [up=верх|низ|обе]  — сектор шара
        (90° — четвертинка, 180° — полусфера, 360° — шар; thickness — стенка)
  имя = spiral radius=60 turns=3 wire=6 height=6 — плоская спираль-улитка
  имя = rope length=200 diameter=20 strands=3 twist=55 — кручёная верёвка
  имя = seven_seg text="21:38" height=54 depth=2 — светодиодные цифры (0-9 A-F : -)

ТЕЛА ВРАЩЕНИЯ И РАЗВЁРТКИ (главное для посуды и кузовов)
  имя = lathe points=[[r,z],...] [segments=128] [fillet=r] [smooth=n]
  имя = extrude profile=[[x,y],...] height=h [fillet=r] [holes=[[[...]]]] [twist=deg]
  имя = sweep path=[[x,y,z],...] radius=r | [profile=[[x,y],...]] [smooth=n] [closed_path=true]
  имя = loft sections=[[[...]],[...]] [positions=[...]] [axis=x|y|z] [smooth=n]

БУЛЕВЫ
  имя = union [a, b]    имя = difference [основа, вычитаемое]    имя = intersect [a, b]
  имя = fuse [a, b] radius=5 edges=вогнутые|все   — СВАРИТЬ: убирает шов на стыке.
        Главный инструмент «одного объёма»: скругляет вогнутые рёбра в радиусе
        radius. Для органики и корпусов всегда лучше union: детали перестают
        выглядеть приставленными. radius ≈ 10–20 % от размера детали.
  имя = shell [a] thickness=t open=top|bottom|both|none
  имя = offset [a] delta=+2      имя = fillet [a] radius=r edges=convex|concave|all
  имя = chamfer [a] width=w edges=convex|concave|all  (плоская фаска 45°)

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

ГРУППЫ И АНИМАЦИЯ ПО ОБЪЕКТАМ (у каждого объекта своя очередь клипов)
  сборка = group [дверь, ручка]      — группа двигается одним клипом
  animate дверь turn angle=90 axis=z pivot=[-40, 0, 0] seconds=2   — поворот вокруг петли
  animate дверь move dy=-250 seconds=2                  — выехать вперёд на 250 мм
  animate колесо roll distance=250 radius=13 axis=x     — качение: угол = путь / радиус
  animate колесо spin turns=2 seconds=4                 — два оборота
  animate дверь wait seconds=1 | scale from=1 to=1.2 | keyframe ...
  animate kind=spin seconds=6         — вся модель: вращение
  animate kind=formation seconds=4    — рост из нуля
  animate kind=explode amount=30 seconds=3  — разлёт на части
  animate kind=assembly hold=0.8      — сборка: каждый шаг сценария как кадр
  axis: x — влево/вправо, y — глубина (вперёд/назад), z — вверх; «−» — обратно.
  pivot=[x,y,z] — точка вращения (петля двери, ось колеса). start=, fps=, track=1..8 —
  когда начинать и на какой дорожке; клипы разных объектов играют параллельно.
  Анимация сохраняется в GLB (Blender покажет действиями). Клипы можно ставить
  в любом месте сценария; «анимация сборки» показывает настоящие промежуточные модели.

ПАРАМЕТРЫ, ЦВЕТ, ПРОВЕРКИ
  толщина = 4            (параметр; используется в выражениях: height=толщина*2)
  color имя material=ceramic|metal|wood|plastic|glass|mirror|led|neon|lamp|screen
  color имя #RRGGBB metal=0..1 rough=0..1 emissive=#RRGGBB emissive_strength=1..20
  color имя ... transmission=0..1     — свечение (LED, неон, экран) и стекло
        emissive — цвет свечения: в окне включается bloom, в GLB пишется
        KHR_materials_emissive_strength. transmission — прозрачность стекла
        (KHR_materials_transmission), в PNG-снимках тоже видно насквозь.
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


def _coord_block(build) -> list[str]:
    """Координаты объектов — коротко, чтобы модель понимала объём и положение."""
    if not build or not build.ok or not build.analysis:
        return []
    objs = (build.analysis.get("metrics") or {}).get("objects") or []
    if not objs:
        return []
    lines = ["## Координаты (мм, ось Z вверх)"]
    for o in objs:
        bb = o.get("bbox") or []
        c = o.get("center") or []
        if len(bb) == 6 and len(c) == 3:
            lines.append(
                f"- {o['name']}: центр ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f}); "
                f"габарит {o['size'][0]:.1f}×{o['size'][1]:.1f}×{o['size'][2]:.1f}; "
                f"X {bb[0]:.1f}…{bb[3]:.1f}, Y {bb[1]:.1f}…{bb[4]:.1f}, Z {bb[2]:.1f}…{bb[5]:.1f}; "
                f"{o['tris']} трис")
    return lines


def _actions_block(actions: list[dict] | None) -> list[str]:
    if not actions:
        return []
    lines = ["", "## Журнал действий (что делал пользователь и приложение)"]
    for a in actions[-25:]:
        mark = "✓" if a.get("ok", True) else "✗"
        lines.append(f"- {a.get('time', '')} {mark} {a.get('kind', '')}: {a.get('text', '')}".replace("  ", " "))
    bad = [a for a in actions if not a.get("ok", True)]
    if bad:
        lines.append("")
        lines.append("Не выполнено / пропущено из-за ошибок:")
        for a in bad[-8:]:
            lines.append(f"- {a.get('time', '')} {a.get('kind', '')}: {a.get('text', '')}")
    return lines


def _notes_block(notes: list[dict] | None) -> list[str]:
    if not notes:
        return []
    lines = ["", "## Замечания пользователя к областям модели"]
    for n in notes[-12:]:
        c = n.get("center") or []
        size = n.get("size") or []
        where = ""
        if len(c) == 3:
            where = f" центр ({c[0]:.1f}, {c[1]:.1f}, {c[2]:.1f})"
        if len(size) == 3:
            where += f", область {size[0]:.1f}×{size[1]:.1f}×{size[2]:.1f} мм"
        if n.get("cells"):
            lines.append(f"- приписка к пустому пространству: {n['cells']} куб. по "
                         f"{n.get('cell', 0):g} мм [{n.get('indices', '')}], "
                         f"объём {n.get('volume_cm3', 0):g} см³{where}: {n.get('text', '')}")
        else:
            lines.append(f"- «{n.get('object', '')}», {n.get('tris', 0)} трис, "
                         f"{n.get('area_mm2', 0)} мм²{where}: {n.get('text', '')}")
    return lines


def _render_block(renders: dict | None) -> list[str]:
    if not renders or not renders.get("files"):
        return []
    lines = ["", "## Снимки модели (PNG, четыре ракурса)"]
    for f in renders["files"]:
        lines.append(f"- {f.get('label', '')}: {f.get('path', '')}")
    if renders.get("combined"):
        lines.append(f"- общий лист: {renders['combined']}")
    lines.append("Снимки смотреть глазами: по ним видно форму, которой нет в числах.")
    return lines


def _animation_block(build) -> list[str]:
    """Что сейчас анимировано и какие кадры сборки есть — для нейросети."""
    scene = getattr(build, "scene", None)
    if scene is None:
        return []
    clips = list(getattr(scene, "animations", []) or [])
    frames = build.frames() if hasattr(build, "frames") else []
    if not clips and not frames:
        return ["", "## Анимация", "Клипов нет. Добавьте строку animate, например "
                "`animate kind=spin seconds=6` или `animate kind=assembly hold=0.8`."]
    names = {"spin": "вращение", "formation": "формирование", "explode": "разлёт",
             "assembly": "сборка по шагам", "move": "перемещение", "scale": "масштаб",
             "turn": "поворот", "roll": "качение", "wait": "пауза", "morph": "форма"}
    out = ["", "## Анимация", "| объект | клип | с | длительность |", "|---|---|---|---|"]
    plan = scene.animation_plan(len(frames))
    for clip in plan["clips"]:
        kind = names.get(clip["kind"], clip["kind"])
        target = clip.get("object") or "вся модель"
        out.append(f"| {target} | {kind} | {clip['start']:.1f} | {clip['length']:.1f} |")
    if frames:
        out += ["", f"Кадров сборки: {len(frames)} (шаги сценария: "
                + ", ".join(str(f["n"]) for f in frames[:24]) + ")"]
    return out


def _metrics_block(build) -> list[str]:
    """Короткая таблица измерений — чтобы нейросеть видела цифры прошлой сборки."""
    metrics = (build.analysis or {}).get("metrics") or {}
    if not metrics:
        return []
    size = metrics.get("size") or [0, 0, 0]
    checks = (build.analysis or {}).get("checks") or []
    bad = [c for c in checks if not c.get("ok")]
    rows = [
        ("габариты, мм", f"{size[0]:.2f} × {size[1]:.2f} × {size[2]:.2f}"),
        ("объём, см³", f"{metrics.get('volume_cm3', 0):.2f}"),
        ("площадь, см²", f"{metrics.get('area_cm2', 0):.2f}"),
        ("масса, г", f"{metrics.get('mass_g', 0):.2f}"),
        ("треугольников", f"{metrics.get('tris', 0)}"),
        ("отверстий (genus)", f"{metrics.get('genus', 0)}"),
        ("частей", f"{metrics.get('parts', 0)}"),
        ("проверок", f"{len(checks) - len(bad)} из {len(checks)} в норме"),
    ]
    wall = metrics.get("wall") or {}
    if wall.get("median"):
        rows.append(("стенка (медиана), мм", f"{wall['median']:.2f}"))
        rows.append(("стенка (минимум), мм", f"{wall.get('min', 0):.2f}"))
    lines = ["## Метрики прошлой сборки", "| показатель | значение |", "|---|---|"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    if bad:
        lines.append("")
        lines.append("Невыполненные проверки:")
        lines += [f"- {c.get('text')}" for c in bad[:8]]
    return lines


def build_prompt(build: Build | None, goal: str = "", out_path: str | None = None,
                 notes: list[dict] | None = None, actions: list[dict] | None = None,
                 with_reference: bool = True, renders: dict | None = None) -> str:
    """Текст запроса для нейросети.

    Справочник команд прикладывается только когда просят (обычно один раз —
    при первом знакомстве). Дальше в запрос идут только конкретные отчёты:
    измерения, координаты, проверки, замечания пользователя и журнал действий.
    """
    parts = ["# Запрос к помощнику по проекту «ФОРМА 3D»", "", f"Дата: {_now()}"]
    if goal.strip():
        parts += ["", "## Что требуется", goal.strip()]
    parts += ["", "## Текущий сценарий", "```forma",
              (build.script if build else "").strip() or "# пусто", "```"]
    if build and build.ok and build.analysis:
        parts += ["", "## Отчёт приложения о результате", "```",
                  build.analysis.get("text", "").strip(), "```"]
        parts += [""] + _metrics_block(build)
        parts += [""] + _coord_block(build)
    elif build and build.error:
        parts += ["", "## Ошибка построения",
                  f"{build.error.get('message')} (строка {build.error.get('line')})"]
        if build.error.get("hint"):
            parts.append(f"Подсказка: {build.error['hint']}")
    parts += _animation_block(build)
    parts += _render_block(renders)
    parts += _actions_block(actions)
    parts += _notes_block(notes)
    parts += ["", "## Как отвечать",
              "1. Сначала коротко скажи, что не так или что нужно изменить (словами, по измерениям).\n"
              "2. Затем выдай ПОЛНЫЙ новый сценарий в одном блоке ```forma — без сокращений.\n"
              "3. Обнови строки check, чтобы результат можно было проверить словами.\n"
              "4. Если в запросе есть замечания к выделенным областям — ответь по каждой области отдельно."]
    if with_reference:
        parts += ["", "## Справочник команд (показывать один раз)", DOCS_INDEX]
    else:
        parts += ["", "## Справочник команд",
                  "Не приложен: он уже был показан ранее. Команды берутся из текущего сценария."]
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
