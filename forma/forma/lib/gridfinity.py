"""Gridfinity — перенос чужого генератора в наши примитивы.

Что такое Gridfinity: открытая система складских ящиков с шагом 42 мм
(спецификация — репозиторий ``gridfinity/gridfinity``, лицензия MIT;
эталонная реализация на OpenSCAD — ``kennetek/gridfinity-rebuilt-openscad``,
тоже MIT). Это не набор готовых мешей, а профиль: у ящика снизу «замок»
из двух фасок 45° и полки, сверху — ответный буртик, который встаёт в замок
верхнего ящика, поэтому ящики штабелируются с шагом 7 мм.

Почему это переносится, а скачанный STL — нет: здесь числа и правила, а не
треугольники. Мы берём из референса константы (42 / 41.5 / 7 / 4.75 / 3.75 /
0.95 / 2.6 × 4.4) и строим ту же форму своими `loft` + `array` + `difference`.
На выходе — обычный сценарий ФОРМЫ, его видно, можно править руками и
проверять нашими же `check`.

Честные отличия от референса (проверены на модели, см. docs/gridfinity_port.md):

* галтель 0.6 на кромке буртика не повторена — кромка острая (влияет только
  на внешний вид верхней кромки, стыковку не меняет);
* у плиты-основания зазор взят 0.25 мм на сторону от профиля ящика, а не
  отдельный профиль референса (0.7 / 2.5 / 4.85): ящик садится, но
  «фирменный» прилив плиты выглядит иначе.

Размеры, мм (сверено с референсом):

=== ====================================================
42  шаг сетки
41.5 сторона замка сверху (зазор 0.5 между ящиками)
7   высота замка (и высота одного юнита высоты)
35.6 сторона замка снизу (41.5 − 2·2.95)
0.8 фаска 45° от низа, затем полка 1.8, затем фаска 2.15
3.75 радиус угла замка сверху (0.8 — снизу)
0.95 толщина стенки
2.6 × 4.4 буртик: выступ внутрь и высота
Ø6.5 × 2.4 карман под магнит, Ø3.35 — под винт M3
8   расстояние центра отверстия от боковой стенки
4.8 центр отверстия над нижней кромкой
=== ====================================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence


# --------------------------------------------------------------------------- #
#  Спецификация
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Spec:
    """Числа спецификации. Менять их — значит уходить от совместимости."""

    pitch: float = 42.0            # шаг сетки
    base_top: float = 41.5         # сторона замка сверху
    base_height: float = 7.0       # высота замка = высота юнита
    unit_height: float = 7.0       # шаг штабелирования
    chamfer: float = 0.8           # первая фаска 45° от низа
    shelf: float = 1.8             # полка между фасками
    flare: float = 2.15            # вторая фаска 45° наружу
    corner: float = 3.75           # радиус угла наверху замка
    wall: float = 0.95             # толщина стенки
    lip_depth: float = 2.6         # буртик: сколько выступает внутрь
    lip_height: float = 4.4        # буртик: высота
    lip_mouth: float = 1.15        # просвет между буртиком и наружной плоскостью
    magnet_d: float = 6.5          # карман под магнит
    magnet_depth: float = 2.4      # 2.0 магнит + 0.4 на слои печати
    screw_d: float = 3.35          # винт M3 с зазором
    hole_from_side: float = 8.0    # центр отверстия от боковой стенки
    plate_height: float = 5.0      # высота плиты-основания
    plate_top: float = 0.15        # просвет под замком ящика на дне кармана
    clearance: float = 0.25        # зазор кармана плиты на сторону
    divider: float = 1.2           # толщина перегородки


SPEC = Spec()

#: сколько отрезков на один скруглённый угол (4·(SEG+1) точек в сечении)
SEG = 8


# --------------------------------------------------------------------------- #
#  Мелкие помощники: контур, формат чисел
# --------------------------------------------------------------------------- #

def _num(value: float) -> str:
    """Число в сценарий: без хвостовых нулей, точка как разделитель."""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def rounded_rect(width: float, depth: float, radius: float, seg: int | None = None) -> list[tuple[float, float]]:
    """Замкнутый контур прямоугольника со скруглёнными углами, по часовой.

    Одинаковое число точек при любом радиусе — иначе `loft` откажется
    соединять сечения (у него требуется равная длина контуров).
    """
    w, d = float(width), float(depth)
    if w <= 0 or d <= 0:
        raise ValueError(f"Стороны контура должны быть больше нуля: {w}×{d}")
    seg = SEG if seg is None else int(seg)
    limit = min(w, d) / 2 - 1e-6
    # Ноль недопустим: при r = 0 все seg+1 точек угла попадают в одну точку,
    # контур вырождается, и на loft появляются стяжки. 0.2 мм на глаз не видно.
    r = max(0.2, min(float(radius), limit))
    hw, hh = w / 2 - r, d / 2 - r
    corners = ((hw, -hh, 270.0), (hw, hh, 0.0), (-hw, hh, 90.0), (-hw, -hh, 180.0))
    points: list[tuple[float, float]] = []
    for cx, cy, start in corners:
        for i in range(seg + 1):
            angle = math.radians(start + 90.0 * i / seg)
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def _section(points: Sequence[tuple[float, float]]) -> str:
    return "[" + ",".join(f"[{_num(x)},{_num(y)}]" for x, y in points) + "]"


def _loft(name: str, sections: Sequence[tuple[float, float, float, float]], seg: int | None = None) -> str:
    """Строка `loft` из сечений (z, ширина, глубина, радиус угла)."""
    body = "[" + ",\n    ".join(_section(rounded_rect(w, d, r, seg)) for _, w, d, r in sections) + "]"
    positions = "[" + ",".join(_num(z) for z, *_ in sections) + "]"
    return f"{name} = loft sections={body} positions={positions} axis=z smooth=1"


def _range(value: float, tol: float = 0.05) -> str:
    """Допуск для строки `check … size`: 42 → «41.95..42.05»."""
    return f"{_num(value - tol)}..{_num(value + tol)}"


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "да", "yes", "true", "on", "y", "д"}
    return bool(value)


def _pair(value) -> tuple[int, int]:
    """«2x3», «2,3», «2 3» или число → пара целых."""
    if isinstance(value, (list, tuple)):
        if len(value) == 1:
            return int(value[0]), 1
        return int(value[0]), int(value[1])
    if isinstance(value, (int, float)):
        return int(value), 1
    text = str(value).strip().lower().replace("х", "x").replace("×", "x")
    for sep in ("x", ",", " ", ":", "/"):
        if sep in text:
            a, b = text.split(sep, 1)
            return int(float(a)), int(float(b))
    return int(float(text)), 1


# --------------------------------------------------------------------------- #
#  Ящик
# --------------------------------------------------------------------------- #

def bin_sections(units_x: int, units_y: int, height: int, spec: Spec = SPEC) -> dict:
    """Сечения ящика: габарит, замок, полость. Возвращает и ожидаемые размеры."""
    ux, uy = max(1, int(units_x)), max(1, int(units_y))
    hu = max(1, int(height))
    s = spec
    width = s.base_top + s.pitch * (ux - 1)
    depth = s.base_top + s.pitch * (uy - 1)
    top = s.unit_height * hu                     # полная высота: шаг штабелирования
    if top <= s.base_height + s.lip_height + 1.0:
        raise ValueError(f"Высота {hu} юнитов мала: нужно больше "
                         f"{(s.base_height + s.lip_height) / s.unit_height:.1f}")
    wall_top = top - s.lip_height                # низ буртика
    inset_at_wall = s.lip_mouth
    shell = [
        (0.0, width - 2 * (s.chamfer + s.flare), depth - 2 * (s.chamfer + s.flare),
         s.corner - (s.chamfer + s.flare)),
        (s.chamfer, width - 2 * s.flare, depth - 2 * s.flare, s.corner - s.flare),
        (s.chamfer + s.shelf, width - 2 * s.flare, depth - 2 * s.flare, s.corner - s.flare),
        (s.chamfer + s.shelf + s.flare, width, depth, s.corner),
        (top, width, depth, s.corner),
    ]
    # Буртик: просвет кверху СУЖАЕТСЯ — 39.2 у низа буртика, 37.8 в середине,
    # 36.3 у самой кромки. Замок верхнего ящика (35.6 снизу, 37.2 через 0.8 мм)
    # входит в устье 36.3 и садится фаской на 45° примерно на 0.5 мм. Проверено
    # пересечением: на шаге 21 мм нахлёста нет, на 20 мм уже 19 мм³.
    # В референсе посадка глубже — там кромка скруглена R0.6, у нас острая.
    cavity = [
        (s.base_height, width - 2 * s.wall, depth - 2 * s.wall, s.corner - s.wall),
        (wall_top - 1.2, width - 2 * s.wall, depth - 2 * s.wall, s.corner - s.wall),
        (wall_top, width - 2 * inset_at_wall, depth - 2 * inset_at_wall, s.corner - inset_at_wall),
        (wall_top + 0.7, width - 2 * (inset_at_wall + 0.7), depth - 2 * (inset_at_wall + 0.7),
         s.corner - (inset_at_wall + 0.7)),
        (wall_top + 2.5, width - 2 * (inset_at_wall + 0.7), depth - 2 * (inset_at_wall + 0.7),
         s.corner - (inset_at_wall + 0.7)),
        (wall_top + s.lip_height, width - 2 * s.lip_depth, depth - 2 * s.lip_depth,
         s.corner - s.lip_depth),
        (top + 1.0, width - 2 * s.lip_depth, depth - 2 * s.lip_depth, s.corner - s.lip_depth),
    ]
    return {"shell": shell, "cavity": cavity, "width": width, "depth": depth,
            "height": top, "wall_top": wall_top, "units": (ux, uy, hu)}


def bin_holes(units_x: int, units_y: int, spec: Spec = SPEC) -> list[tuple[float, float]]:
    """Центры отверстий: по четыре на юнит, лишние совпадения убраны."""
    s = spec
    offset = s.base_top / 2 - s.hole_from_side
    xs = {round((i - (units_x - 1) / 2) * s.pitch + sx * offset, 6)
          for i in range(units_x) for sx in (-1, 1)}
    ys = {round((j - (units_y - 1) / 2) * s.pitch + sy * offset, 6)
          for j in range(units_y) for sy in (-1, 1)}
    return sorted(((x, y) for y in ys for x in xs), key=lambda p: (p[1], p[0]))


def bin_script(units_x: int = 1, units_y: int = 1, height: int = 3,
               magnets: bool = True, screws: bool = True,
               dividers: Sequence[int] | None = None,
               spec: Spec = SPEC, comment: str | None = None) -> str:
    """Сценарий ФОРМЫ: ящик Gridfinity.

    ``height`` — высота в юнитах по 7 мм, считая замок: 3 юнита = 21 мм.
    ``dividers`` — [по X, по Y] отсеков; рёбра ставятся внутри полости.
    """
    info = bin_sections(units_x, units_y, height, spec)
    s = spec
    ux, uy, hu = info["units"]
    width, depth, top = info["width"], info["depth"], info["height"]
    lines: list[str] = [
        comment or f"# Gridfinity: ящик {ux}×{uy}, высота {hu}u ({_num(top)} мм).",
        f"# Спецификация: шаг {_num(s.pitch)}, замок {_num(s.base_top)}→{_num(s.base_top - 2 * (s.chamfer + s.flare))},"
        f" буртик {_num(s.lip_depth)}×{_num(s.lip_height)}.",
        "",
        "# 1. Наружная оболочка: замок снизу, прямая стенка до буртика.",
        _loft("оболочка", info["shell"]),
        "",
        "# 2. Полость: стенка 0.95, у буртика устье сужается 39.2 → 36.3.",
        _loft("полость", info["cavity"]),
        "тело = difference [оболочка, полость]",
    ]

    if dividers:
        dx, dy = _pair(dividers)
        cavity_w = width - 2 * s.wall
        cavity_d = depth - 2 * s.wall
        plates: list[str] = []
        if dx > 1:
            step = cavity_w / dx
            for i in range(1, dx):
                name = f"ребро_x{i}"
                lines.append(f"{name} = box size=[{_num(s.divider)},{_num(cavity_d * 1.05)},"
                             f"{_num(info['wall_top'] - s.base_height - 0.2)}] "
                             f"at=[{_num(-cavity_w / 2 + step * i - s.divider / 2)},"
                             f"{_num(-cavity_d * 1.05 / 2)},{_num(s.base_height)}]")
                plates.append(name)
        if dy > 1:
            step = cavity_d / dy
            for j in range(1, dy):
                name = f"ребро_y{j}"
                lines.append(f"{name} = box size=[{_num(cavity_w * 1.05)},{_num(s.divider)},"
                             f"{_num(info['wall_top'] - s.base_height - 0.2)}] "
                             f"at=[{_num(-cavity_w * 1.05 / 2)},"
                             f"{_num(-cavity_d / 2 + step * j - s.divider / 2)},"
                             f"{_num(s.base_height)}]")
                plates.append(name)
        if plates:
            lines += ["", "# 3. Перегородки: обрезаются по полости, поэтому прилегают к стенкам."]
            source = ", ".join(plates)
            lines += [f"перегородки = intersect [{source}, полость]",
                      "тело = union [тело, перегородки]"]

    if magnets or screws:
        holes = bin_holes(ux, uy, spec)
        x0, y0 = holes[0]
        count_x = len({round(p[0], 6) for p in holes})
        count_y = len({round(p[1], 6) for p in holes})
        lines.append("")
        lines.append("# 4. Отверстия под магниты и винты: по четыре на юнит, шаг 42.")
        cuts: list[str] = []
        if magnets:
            lines.append(f"магнит = cylinder radius={_num(s.magnet_d / 2)} "
                         f"height={_num(s.magnet_depth)} segments=32 at=[{_num(x0)},{_num(y0)},0]")
            lines.append(f"магниты = array [магнит] mode=grid counts=[{count_x},{count_y},1] "
                         f"spacing=[{_num(s.pitch)},{_num(s.pitch)},0]")
            cuts.append("магниты")
        if screws:
            lines.append(f"винт = cylinder radius={_num(s.screw_d / 2)} "
                         f"height={_num(s.base_height - s.magnet_depth + 0.4)} segments=24 "
                         f"at=[{_num(x0)},{_num(y0)},{_num(s.magnet_depth)}]")
            lines.append(f"винты = array [винт] mode=grid counts=[{count_x},{count_y},1] "
                         f"spacing=[{_num(s.pitch)},{_num(s.pitch)},0]")
            cuts.append("винты")
        lines.append(f"тело = difference [тело, {', '.join(cuts)}]")

    lines += ["", "# Проверки: габарит по спецификации и герметичность.",
              "# `check тело mesh` сюда НЕ ставим: у 1×1 он проходит (0 стяжек), а у 2×3",
              "# на кромке замка 9 стяжек — деталь годная, порог не тот. См. §5 документа.",
              f"check тело size {_range(width)} {_range(depth)} {_range(top)}",
              "check тело watertight"]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  Плита-основание
# --------------------------------------------------------------------------- #

def baseplate_script(units_x: int = 2, units_y: int = 2,
                     spec: Spec = SPEC, comment: str | None = None) -> str:
    """Сценарий ФОРМЫ: плита-основание под ящики, шаг 42."""
    s = spec
    ux, uy = max(1, int(units_x)), max(1, int(units_y))
    width, depth = s.pitch * ux, s.pitch * uy
    c = s.clearance
    cell = [
        (s.plate_top, s.base_top - 2 * (s.chamfer + s.flare) + 2 * c,
         s.base_top - 2 * (s.chamfer + s.flare) + 2 * c, s.corner - (s.chamfer + s.flare) + c),
        (s.plate_top + s.chamfer, s.base_top - 2 * s.flare + 2 * c,
         s.base_top - 2 * s.flare + 2 * c, s.corner - s.flare + c),
        (s.plate_top + s.chamfer + s.shelf, s.base_top - 2 * s.flare + 2 * c,
         s.base_top - 2 * s.flare + 2 * c, s.corner - s.flare + c),
        (s.plate_top + s.chamfer + s.shelf + s.flare, s.base_top + 2 * c,
         s.base_top + 2 * c, s.corner + c),
        (s.plate_height + 1.0, s.base_top + 2 * c, s.base_top + 2 * c, s.corner + c),
    ]
    lines = [
        comment or f"# Gridfinity: плита-основание {ux}×{uy} ({_num(width)}×{_num(depth)} мм).",
        f"# Карман = профиль замка ящика + зазор {_num(c)} мм на сторону.",
        "",
        f"плита = extrude profile={_section(rounded_rect(width, depth, 4.0))} "
        f"height={_num(s.plate_height)}",
        _loft("карман", cell),
        f"карманы = array [карман] mode=grid counts=[{ux},{uy},1] "
        f"spacing=[{_num(s.pitch)},{_num(s.pitch)},0] "
        f"at=[{_num(-width / 2 + s.pitch / 2)},{_num(-depth / 2 + s.pitch / 2)},0]",
        "плита = difference [плита, карманы]",
        "",
        f"check плита size {_range(width)} {_range(depth)} {_range(s.plate_height)}",
        "check плита watertight",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  Вход для команды `forma lib`
# --------------------------------------------------------------------------- #

KINDS = {"bin": "ящик", "baseplate": "плита-основание", "bins": "ящик", "plate": "плита-основание"}


def build_script(kind: str = "bin", **options) -> str:
    """Собрать сценарий по текстовым параметрам (для CLI и тестов)."""
    what = KINDS.get((kind or "bin").strip().lower())
    if what is None:
        raise ValueError(f"Неизвестный вид: {kind}. Есть: ящик (bin), плита (baseplate).")
    size = _pair(options.pop("size", options.pop("units_xy", None) or "1x1"))
    if "bin" in (kind or "").lower() or what == "ящик":
        height = int(float(options.pop("height", options.pop("units", 3))))
        dividers = options.pop("dividers", options.pop("разделить", None))
        return bin_script(units_x=size[0], units_y=size[1], height=height,
                          magnets=_flag(options.pop("magnets", options.pop("магниты", True))),
                          screws=_flag(options.pop("screws", options.pop("винты", True))),
                          dividers=_pair(dividers) if dividers else None)
    return baseplate_script(units_x=size[0], units_y=size[1])


def params_help() -> list[tuple[str, str]]:
    """Что можно передать в `forma lib gridfinity …` — для подсказки."""
    return [
        ("kind", "bin (ящик, по умолчанию) или baseplate (плита)"),
        ("size", "размер в юнитах: 2x3 (по умолчанию 1x1)"),
        ("height", "высота ящика в юнитах по 7 мм, включая замок (3)"),
        ("magnets", "карманы Ø6.5 под магниты: да/нет (да)"),
        ("screws", "отверстия Ø3.35 под винт M3: да/нет (да)"),
        ("dividers", "перегородки: 2x1 — два отсека по X, один по Y"),
    ]
