"""Одиночный плацкартный вагон 61-4194, масштаб 1:20, Forma 0.52.

Запуск из корня репозитория:
    PYTHONPATH=forma python forma/docs/make_train_carriage.py

Создаёт редактируемую examples/train_carriage.forma, контрольный GLB,
экстерьерные/интерьерные виды и JSON с геометрическими проверками.
Наружные модели, mesh-референсы, текстуры и второй вагон не используются.
"""
from __future__ import annotations

import fnmatch
import json
import math
from itertools import combinations
from pathlib import Path

import manifold3d as mf
import numpy as np

from forma.geometry import manifold_mesh
from forma.render import _prepare, _render_view
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "examples" / "train_carriage.forma"
RENDER_DIR = ROOT / "renders" / "train_carriage"
EXPORT_DIR = ROOT / "exports" / "train_carriage"
BG = (0.065, 0.078, 0.095)
SCALE = 20.0
BODY_LENGTH = 1180.0
BODY_WIDTH = 155.25
COUPLER_AXIS = 24537.0 / SCALE / 2.0
BOGIE_CENTERS = (-425.0, 425.0)
SECTION_START = -390.0
SECTION_PITCH = 840.0 / 9.0
SECTION_CENTERS = [SECTION_START + (i + 0.5) * SECTION_PITCH for i in range(9)]

lines: list[str] = []
CAR: set[str] = set()
TRACK: set[str] = set()


def name_part(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).replace("-", "m").replace(".", "p")


def add(text: str = "") -> None:
    lines.append(text)


def emit(text: str, bucket: str = "car") -> str:
    add(text)
    if "=" in text and not text.lstrip().startswith("#"):
        name = text.split("=", 1)[0].strip()
        if name and " " not in name:
            (CAR if bucket == "car" else TRACK).add(name)
            return name
    return ""


def paint(name: str, color: str, metal: float = 0.0, rough: float = 0.55,
          transmission: float = 0.0, emissive: str | None = None) -> None:
    extra = f" metal={metal:g} rough={rough:g}"
    if transmission:
        extra += f" transmission={transmission:g}"
    if emissive:
        extra += f" emissive={emissive} emissive_strength=1.6"
    add(f"color {name} {color}{extra}")


def box(name: str, size, at, color: str, round_r: float = 0.0,
        bucket: str = "car") -> None:
    if round_r:
        round_r = min(round_r, min(size) * 0.45)
    extra = f" round={round_r:g}" if round_r else ""
    emit(f"{name} = box size={list(size)} center=да at={list(at)}{extra} color={color}", bucket)


def cylinder(name: str, radius: float, height: float, at, color: str,
             axis: str = "z", segments: int = 40, bucket: str = "car") -> None:
    emit(f"{name} = cylinder radius={radius:g} height={height:g} segments={segments} "
         f"center=да color={color}", bucket)
    if axis == "x":
        add(f"rotate [{name}] angle=90 axis=y")
    elif axis == "y":
        add(f"rotate [{name}] angle=90 axis=x")
    elif axis != "z":
        raise ValueError(axis)
    add(f"translate [{name}] offset={list(at)}")


def lathe(name: str, points, at, color: str, axis: str = "z",
          segments: int = 56, fillet: float = 0.0, bucket: str = "car") -> None:
    extra = f" fillet={fillet:g}" if fillet else ""
    emit(f"{name} = lathe points={points} segments={segments}{extra} color={color}", bucket)
    if axis == "x":
        add(f"rotate [{name}] angle=90 axis=y")
    elif axis == "y":
        add(f"rotate [{name}] angle=90 axis=x")
    elif axis != "z":
        raise ValueError(axis)
    add(f"translate [{name}] offset={list(at)}")


def torus(name: str, major: float, minor: float, at, color: str,
          axis: str = "z", bucket: str = "car") -> None:
    emit(f"{name} = torus major={major:g} minor={minor:g} segments=56 "
         f"minor_segments=12 color={color}", bucket)
    if axis == "x":
        add(f"rotate [{name}] angle=90 axis=y")
    elif axis == "y":
        add(f"rotate [{name}] angle=90 axis=x")
    add(f"translate [{name}] offset={list(at)}")


def sweep(name: str, path, radius: float, color: str, sides: int = 12,
          smooth: int = 0, bucket: str = "car") -> None:
    extra = f" smooth={smooth}" if smooth else ""
    emit(f"{name} = sweep path={path} radius={radius:g} sides={sides}{extra} color={color}", bucket)


def beam_xz(name: str, a, b, width_y: float, thickness: float, color: str) -> None:
    dx, dz = b[0] - a[0], b[2] - a[2]
    length = math.hypot(dx, dz)
    angle = -math.degrees(math.atan2(dz, dx))
    box(name, (length, width_y, thickness), (0, 0, 0), color, min(0.5, thickness * 0.2))
    add(f"rotate [{name}] angle={angle:g} axis=y")
    add(f"translate [{name}] offset={[(a[0]+b[0])/2, (a[1]+b[1])/2, (a[2]+b[2])/2]}")


def grating(name: str, width: float, height: float, depth: float, at, color: str,
            pattern: str = "клетка", vertical: bool = False, bucket: str = "car",
            **kwargs) -> None:
    params = " ".join(f"{key}={value}" for key, value in kwargs.items())
    emit(f"{name} = grating width={width:g} height={height:g} depth={depth:g} "
         f"pattern={pattern} center=да {params} color={color}", bucket)
    if vertical:
        add(f"rotate [{name}] angle=90 axis=x")
    add(f"translate [{name}] offset={list(at)}")


def text(name: str, value: str, size: float, at, color: str,
         far: bool = False, bucket: str = "car") -> None:
    # Поворот выполняется до размещения: rotate без pivot работает от начала сцены.
    origin = [0, 0, 0] if far else list(at)
    emit(f'{name} = text "{value}" size={size:g} depth=0.2 align=center '
         f'plane=xz at={origin} color={color}', bucket)
    if far:
        add(f"rotate [{name}] angle=180 axis=z")
        add(f"translate [{name}] offset={list(at)}")


def cut(target: str, cutter: str, size, at, round_r: float = 0.0) -> None:
    box(cutter, size, at, "#ffffff", round_r)
    add(f"{target} = difference [{target},{cutter}]")
    CAR.discard(cutter)


def socket(name: str, at) -> None:
    emit(f"{name} = socket sockets=1 ground=да screws=нет color=#e8e3d8")
    for suffix in ("insert_1", "bezel_1", "ground_1_top", "ground_1_bottom"):
        CAR.add(f"{name}.{suffix}")
    add(f"scale [{name}] factor=[0.12,0.12,0.12]")
    add(f"translate [{name}] offset={list(at)}")


def switch(name: str, at) -> None:
    emit(f"{name} = switch rockers=1 state=on led=да screws=нет color=#e8e3d8")
    CAR.add(f"{name}.rocker_1")
    CAR.add(f"{name}.led_1")
    add(f"scale [{name}] factor=[0.12,0.12,0.12]")
    add(f"translate [{name}] offset={list(at)}")


add("# ПЛАЦКАРТНЫЙ ВАГОН 61-4194 — одиночный вагон, масштаб 1:20")
add("# Forma 0.52. Все размеры в мм модели; исходный масштаб получается умножением на 20.")
add("# Канон: +Z вверх, +X вправо, -Y вперёд. Продольная ось вагона — X.")
add("# Длина по осям автосцепок 1226.85; ширина кузова 155.25; база вагона 850.")
add("# Высоты пола/полок/крыши — проектные, не заявлены как справочные размеры прототипа.")
add()

# ---------------------------------------------------------------------------
# Несущий кузов: отдельные стены, торцы, пол и замкнутая арочная крыша.
# ---------------------------------------------------------------------------
add("# --- Несущий кузов и настоящие проёмы ---")
box("car_wall_far", (1168, 5, 115), (0, 73.9, 121.5), "#b8bdc0")
box("car_wall_near", (1168, 5, 115), (0, -73.9, 121.5), "#b8bdc0")
box("car_floor", (1168, 142.8, 2), (0, 0, 66), "#55575a")
roof_profile = [
    [-77.55, 178], [-62, 190], [-38, 201], [0, 207], [38, 201], [62, 190], [77.55, 178],
    [76.35, 179], [60, 188], [36, 198], [0, 201], [-36, 198], [-60, 188], [-76.35, 179],
]
emit(f"car_roof = loft sections=[{roof_profile},{roof_profile}] positions=[-590,590] "
     "axis=x smooth=1 color=#b9bec1")
paint("car_roof", "#b9bec1", metal=0.42, rough=0.38)
end_profile = [[-76.4, 64], [76.4, 64], [76.4, 179], [60, 188], [36, 198],
               [0, 201], [-36, 198], [-60, 188], [-76.4, 179]]
for side, positions in (("left", [-590, -584]), ("right", [584, 590])):
    name = f"car_end_{side}"
    emit(f"{name} = loft sections=[{end_profile},{end_profile}] positions={positions} "
         "axis=x smooth=1 color=#afb5b9")
    cut(name, f"cut_end_{side}", (20, 40, 93),
        (-587 if side == "left" else 587, 0, 113.5), 2.0)

OPENINGS = {"far": [], "near": []}
RIB_EXCLUSIONS = {"far": [], "near": []}


def window(wall: str, index: int, x: float, z: float, width: float, height: float) -> None:
    side = 1 if wall == "far" else -1
    prefix = f"win_{wall}_{index:02d}"
    cut(f"car_wall_{wall}", f"cut_{wall}_{index:02d}",
        (width + 4, 12, height + 4), (x, side * 73.9, z), 2.0)
    OPENINGS[wall].append((x, z, width + 4, height + 4))
    box(f"{prefix}_glass", (width, 1.2, height), (x, side * 73.9, z), "#8fb3c2", 0.45)
    paint(f"{prefix}_glass", "#8fb3c2", metal=0.05, rough=0.14, transmission=0.42)
    for suffix, xx in (("left", x - (width + 1) / 2), ("right", x + (width + 1) / 2)):
        box(f"{prefix}_frame_{suffix}", (2, 1.0, height + 4),
            (xx, side * 76.9, z), "#d7d9d8", 0.35)
    for suffix, zz in (("bottom", z - (height + 1) / 2), ("top", z + (height + 1) / 2)):
        box(f"{prefix}_frame_{suffix}", (width + 2, 1.0, 2),
            (x, side * 76.9, zz), "#d7d9d8", 0.35)
    box(f"{prefix}_transom", (width, 1.1, 1.2),
        (x, side * 76.95, z + height * 0.18), "#c9cdce", 0.25)


window_index = {"far": 0, "near": 0}
for i, x in enumerate(SECTION_CENTERS, 1):
    for wall in ("far", "near"):
        window_index[wall] += 1
        if wall == "far":
            window(wall, window_index[wall], x, 134, 58, 44)
        else:
            window(wall, window_index[wall], x, 132, 52, 40)
for wall in ("far", "near"):
    for x, z, w, h in ((-532.5, 145, 20, 20), (515, 145, 20, 20),
                       (-495, 140, 24, 24), (-432.5, 134, 44, 40)):
        window_index[wall] += 1
        window(wall, window_index[wall], x, z, w, h)


def side_door(wall: str, end: str, x: float) -> None:
    side = 1 if wall == "far" else -1
    prefix = f"door_{wall}_{end}"
    cut(f"car_wall_{wall}", f"cut_{prefix}", (36, 12, 110), (x, side * 73.9, 122), 2.0)
    OPENINGS[wall].append((x, 122, 36, 110))
    # Дверь закрыта, но все её элементы остаются самостоятельными объектами.
    for suffix, xx in (("left", x - 15), ("right", x + 15)):
        box(f"{prefix}_stile_{suffix}", (2, 2, 110), (xx, side * 73.9, 122), "#aeb4b7", 0.5)
    box(f"{prefix}_lower", (28, 2, 53), (x, side * 73.9, 93.5), "#b7bcbf", 0.7)
    box(f"{prefix}_upper", (28, 2, 20), (x, side * 73.9, 167), "#b7bcbf", 0.7)
    box(f"{prefix}_rail", (28, 2, 5), (x, side * 73.9, 122.5), "#b7bcbf", 0.5)
    box(f"{prefix}_glass", (26, 1.2, 30), (x, side * 73.9, 141), "#8fb3c2", 0.8)
    paint(f"{prefix}_glass", "#8fb3c2", metal=0.05, rough=0.14, transmission=0.42)
    for suffix, xx in (("left", x - 17), ("right", x + 17)):
        box(f"{prefix}_frame_{suffix}", (2, 1.2, 114), (xx, side * 76.8, 122), "#d4d6d5", 0.4)
    for suffix, zz in (("bottom", 66), ("top", 178)):
        box(f"{prefix}_frame_{suffix}", (36, 1.2, 2), (x, side * 76.8, zz), "#d4d6d5", 0.4)
    cylinder(f"{prefix}_handle", 0.8, 8, (x + 10, side * 76.0, 117), "#d5d7d6", axis="z")
    for step, (yy, zz, depth) in enumerate(((84, 44, 14), (81, 53, 12), (79, 62, 10)), 1):
        box(f"{prefix}_step_{step}", (32, depth, 2), (x, side * yy, zz), "#666d71", 0.45)
        for bracket, xx in enumerate((x - 11, x + 11), 1):
            sweep(f"{prefix}_step_{step}_bracket_{bracket}",
                  [[xx, side * 75.5, zz - 4], [xx, side * yy, zz - 1]], 0.65, "#555c60")
    for rail, xx in enumerate((x - 21, x + 21), 1):
        sweep(f"{prefix}_grab_{rail}",
              [[xx, side * 75.8, 78], [xx, side * 79.0, 82],
               [xx, side * 79.0, 153], [xx, side * 75.8, 157]], 0.65, "#d7d9d8", smooth=3)


for wall in ("far", "near"):
    side_door(wall, "left", -566)
    side_door(wall, "right", 566)

# Гофры обрываются у проёмов и табличек, а не проходят сквозь стекло и надписи.
for wall in ("far", "near"):
    side = 1 if wall == "far" else -1
    RIB_EXCLUSIONS[wall].extend([(-260, 166, 62, 18), (480, 92, 62, 16)])
    for ri, z in enumerate((72, 77, 82, 87, 92, 97, 164, 169, 174), 1):
        intervals = [(-584.0, 584.0)]
        blocks = OPENINGS[wall] + RIB_EXCLUSIONS[wall]
        for bx, bz, bw, bh in blocks:
            if abs(z - bz) > bh / 2 + 0.8:
                continue
            left, right = bx - bw / 2 - 0.6, bx + bw / 2 + 0.6
            next_intervals = []
            for a, b in intervals:
                if right <= a or left >= b:
                    next_intervals.append((a, b))
                else:
                    if left > a:
                        next_intervals.append((a, left))
                    if right < b:
                        next_intervals.append((right, b))
            intervals = next_intervals
        for si, (a, b) in enumerate(intervals, 1):
            if b - a < 1.0:
                continue
            box(f"rib_{wall}_{ri:02d}_{si:02d}", (b - a, 1.4, 1.2),
                ((a + b) / 2, side * 76.925, z), "#c2c6c8", 0.35)
    box(f"livery_{wall}_red_stripe", (1168, 0.45, 5.5),
        (0, side * 77.15, 104), "#b42332", 0.18)
    text(f"logo_{wall}_rzd", "РЖД", 10, (-260, side * 77.55, 161), "#b42332", far=wall == "far")
    box(f"number_{wall}_plate", (58, 1.0, 13), (480, side * 77.0, 92), "#aeb4b7", 0.6)
    text(f"number_{wall}_text", "61-4194  РЖД", 5.2, (480, side * 77.65, 89), "#9f1f2d", far=wall == "far")
    text(f"capacity_{wall}_text", "54 МЕСТА", 3.0, (535, side * 77.55, 160), "#444b50", far=wall == "far")
add()

# ---------------------------------------------------------------------------
# Торцевые гармошки, двери, автосцепки СА-3 и буферы. Второго вагона нет.
# ---------------------------------------------------------------------------
add("# --- Торцевые переходы с закрытыми дверями и автосцепки ---")
for end, sign in (("left", -1), ("right", 1)):
    for fold in range(4):
        name = f"gangway_{end}_fold_{fold+1}"
        x = sign * (591 + fold * 2.6)
        box(name, (1.6, 48 + fold * 0.8, 100 + fold * 0.8), (x, 0, 114), "#3f464a", 0.5)
        cut(name, f"cut_{name}", (4, 40 + fold * 0.8, 92 + fold * 0.8), (x, 0, 114), 1.2)
    box(f"gangway_{end}_door", (2, 40, 92), (sign * 601.5, 0, 114), "#777f83", 1.0)
    box(f"gangway_{end}_window", (0.8, 18, 24), (sign * 602.7, 0, 132), "#7999a7", 0.4)
    cylinder(f"gangway_{end}_handle", 0.8, 8, (sign * 603.0, -12, 108), "#d1d4d4", axis="z")
    for side in (-1, 1):
        cylinder(f"buffer_{end}_{name_part(side)}_stem", 4.2, 14, (sign * 594, side * 27, 53), "#4d5559", axis="x")
        cylinder(f"buffer_{end}_{name_part(side)}_head", 7.0, 2.4, (sign * 602, side * 27, 53), "#343b3f", axis="x")
        sweep(f"hose_{end}_{name_part(side)}",
              [[sign * 585, side * 18, 52], [sign * 596, side * 20, 43],
               [sign * 603, side * 15, 47]], 1.1, "#8e3035" if side < 0 else "#344f68", smooth=4)
        box(f"marker_{end}_{name_part(side)}", (2.4, 4.5, 6), (sign * 590.8, side * 55, 112), "#792832", 0.8)
        paint(f"marker_{end}_{name_part(side)}", "#a52a35", rough=0.25, emissive="#7b121c")
    box(f"draft_{end}", (30, 18, 16), (sign * 575, 0, 52), "#42494d", 1.2)
    cylinder(f"coupler_{end}_shank", 4.2, 38, (sign * 594, 0, 52), "#3d4549", axis="x")
    axis_x = sign * COUPLER_AXIS
    head_profile = [[-8, 46], [5, 46], [9, 50], [8, 58], [2, 60], [-7, 57], [-9, 52]]
    emit(f"coupler_{end}_head = loft sections=[{head_profile},{head_profile}] "
         f"positions={[axis_x-9, axis_x+9]} axis=x smooth=1 color=#343c40")
    cylinder(f"coupler_{end}_pin", 2.0, 20, (axis_x, 0, 52), "#242b2e", axis="y")
add()

# ---------------------------------------------------------------------------
# Рама и подвагонное оборудование.
# ---------------------------------------------------------------------------
add("# --- Рама, ёмкости, электрооборудование и тормозная магистраль ---")
box("frame_center", (1140, 32, 8), (0, 0, 56), "#454c50", 1.0)
for side in (-1, 1):
    box(f"frame_side_{name_part(side)}", (1180, 5, 10), (0, side * 68.9, 60), "#596065", 0.8)
for i, x in enumerate((-540, -425, -300, -150, 0, 150, 300, 425, 540), 1):
    box(f"frame_cross_{i:02d}", (8, 138, 6), (x, 0, 62), "#4b5357", 0.6)
box("under_water_tank", (140, 58, 28), (-155, 0, 38), "#646d71", 4.0)
paint("under_water_tank", "#646d71", metal=0.5, rough=0.38)
for x in (-205, -105):
    box(f"under_water_strap_{name_part(x)}", (3, 60, 30), (x, 0, 38), "#363d41", 0.5)
box("under_battery_box", (116, 44, 28), (25, 43, 38), "#50585d", 2.0)
for i in range(6):
    box(f"under_battery_louver_{i}", (2, 1.0, 16), (-15 + i * 15, 65.5, 38), "#252c30", 0.25)
cylinder("under_generator", 16, 74, (115, -38, 38), "#4a5459", axis="x", segments=56)
for x in (82, 148):
    cylinder(f"under_generator_flange_{x}", 18, 2.5, (x, -38, 38), "#333b40", axis="x")
cylinder("under_brake_reservoir", 11, 72, (230, 10, 38), "#555e62", axis="x", segments=48)
box("under_electrical_cabinet", (62, 38, 30), (-275, -38, 39), "#4d565b", 1.5)
grating("under_electrical_vent", 42, 18, 0.8, (-275, -57.4, 39), "#282f33",
        pattern="планки", vertical=True, bars=7, bar=1.0, frame=1.2)
for y in (-19, 19):
    sweep(f"under_brake_pipe_{name_part(y)}", [[-560, y, 48], [-300, y, 48], [0, y, 48],
                                    [300, y, 48], [560, y, 48]], 0.65, "#8a713f")
for x in (-425, 425):
    cylinder(f"under_center_plate_{name_part(x)}", 12, 4, (x, 0, 51), "#343b3f")
add()

# ---------------------------------------------------------------------------
# Две двухосные тележки: база 120, колёса Ø47.5, рессоры и тормоза.
# ---------------------------------------------------------------------------
add("# --- Двухосные тележки с профильными колёсами и двойным подвешиванием ---")
wheel_profile = [[3, -3.8], [17, -3.8], [20, -3.0], [22, -3.0],
                 [23.75, -2.2], [23.75, 2.2], [22, 3.0], [20, 3.0],
                 [17, 3.8], [3, 3.8], [3, -3.8]]
for bogie, center in zip(("left", "right"), BOGIE_CENTERS):
    for axle_index, axle_x in enumerate((center - 60, center + 60), 1):
        cylinder(f"axle_{bogie}_{axle_index}", 2.8, 104, (axle_x, 0, 23.75), "#3e464a", axis="y")
        for side in (-1, 1):
            tag = "near" if side < 0 else "far"
            wheel = f"wheel_{bogie}_{axle_index}_{tag}"
            lathe(wheel, wheel_profile, (axle_x, side * 38, 23.75), "#41494d", axis="y", segments=72)
            paint(wheel, "#41494d", metal=0.72, rough=0.3)
            # Гребень находится с внутренней стороны рельса и не пересекает его головку.
            torus(f"flange_{bogie}_{axle_index}_{tag}", 23.35, 1.25,
                  (axle_x, side * 33.75, 23.75), "#353d41", axis="y")
            cylinder(f"hub_{bogie}_{axle_index}_{tag}", 6.2, 9,
                     (axle_x, side * 38, 23.75), "#30383c", axis="y")
            cylinder(f"bearing_{bogie}_{axle_index}_{tag}", 6.8, 8,
                     (axle_x, side * 48, 23.75), "#596267", axis="y")
            box(f"axlebox_{bogie}_{axle_index}_{tag}", (13, 7, 12),
                (axle_x, side * 51, 25), "#4b555a", 1.8)
            for bolt in range(4):
                angle = math.pi / 4 + bolt * math.pi / 2
                cylinder(f"hubbolt_{bogie}_{axle_index}_{tag}_{bolt}", 0.65, 0.9,
                         (axle_x + 4.3 * math.cos(angle), side * 42.0,
                          23.75 + 4.3 * math.sin(angle)), "#92999b", axis="y", segments=12)
            for brake_side in (-1, 1):
                box(f"brake_shoe_{bogie}_{axle_index}_{tag}_{name_part(brake_side)}", (3, 6, 12),
                    (axle_x + brake_side * 25.5, side * 38, 23.75), "#2c3336", 0.8)
                sweep(f"brake_hanger_{bogie}_{axle_index}_{tag}_{name_part(brake_side)}",
                      [[axle_x + brake_side * 25.5, side * 45, 35],
                       [axle_x + brake_side * 25.5, side * 41, 28],
                       [axle_x + brake_side * 25.5, side * 38, 25]], 0.65, "#545d61")
    for side in (-1, 1):
        tag = "near" if side < 0 else "far"
        box(f"bogie_{bogie}_top_{tag}", (124, 5, 5), (center, side * 51, 33), "#4a5459", 0.8)
        box(f"bogie_{bogie}_bottom_{tag}", (104, 4, 4), (center, side * 51, 16.5), "#424b50", 0.6)
        beam_xz(f"bogie_{bogie}_diag_a_{tag}", (center - 55, side * 51, 18),
                (center - 15, side * 51, 31), 4, 4, "#4b555a")
        beam_xz(f"bogie_{bogie}_diag_b_{tag}", (center + 55, side * 51, 18),
                (center + 15, side * 51, 31), 4, 4, "#4b555a")
        for spring_index, x in enumerate((center - 30, center + 30), 1):
            box(f"spring_seat_{bogie}_{tag}_{spring_index}", (16, 10, 2),
                (x, side * 51, 16), "#3a4347", 0.5)
            emit(f"spring_{bogie}_{tag}_{spring_index} = spring diameter=7 wire=0.75 "
                 f"turns=5 pitch=2.65 at=[{x},{side*51},17] color=#3b4448")
            box(f"spring_cap_{bogie}_{tag}_{spring_index}", (15, 10, 2),
                (x, side * 51, 30.5), "#434c51", 0.5)
        for x in (center - 60, center + 60):
            emit(f"primary_spring_{bogie}_{tag}_{name_part(x)} = spring diameter=5.5 wire=0.65 "
                 f"turns=4 pitch=2.2 at=[{x},{side*51},28] color=#394247")
    box(f"bogie_{bogie}_bolster", (20, 108, 8), (center, 0, 39), "#465055", 1.4)
    cylinder(f"bogie_{bogie}_kingpin", 5, 13, (center, 0, 45.5), "#343c40")
    for side in (-1, 1):
        beam_xz(f"bogie_{bogie}_brake_beam_{name_part(side)}", (center - 86, side * 38, 15),
                (center + 86, side * 38, 15), 2.2, 2.2, "#596267")
    cylinder(f"bogie_{bogie}_brake_cylinder", 4.5, 24, (center, -20, 27), "#555f64", axis="x")
    sweep(f"bogie_{bogie}_brake_link", [[center - 12, -20, 27], [center, -30, 20],
                                       [center + 45, -38, 15]], 0.8, "#6a7275")
add()

# ---------------------------------------------------------------------------
# Крышевое оборудование: кондиционер, вентиляторы, решётки и швы.
# ---------------------------------------------------------------------------
add("# --- Крышевой кондиционер, вентиляция и поперечные швы ---")
box("hvac_base", (154, 52, 4), (120, 0, 203.5), "#858e93", 1.2)
box("hvac_housing", (150, 50, 15), (120, 0, 212), "#a7afb3", 3.0)
paint("hvac_housing", "#a7afb3", metal=0.35, rough=0.4)
for i, x in enumerate((75, 165), 1):
    cylinder(f"hvac_fan_{i}", 10, 1.2, (x, 0, 220), "#3f484d", segments=56)
    torus(f"hvac_fan_ring_{i}", 10.2, 0.55, (x, 0, 220.8), "#c0c5c7")
    for blade in range(3):
        name = f"hvac_fan_{i}_blade_{blade}"
        box(name, (15, 2.2, 0.5), (0, 0, 0), "#737d82", 0.2)
        add(f"rotate [{name}] angle={blade*60} axis=z")
        add(f"translate [{name}] offset=[{x},0,220.8]")
    grating(f"hvac_fan_guard_{i}", 23, 23, 0.6, (x, 0, 221.5), "#aab1b4",
            pattern="клетка", cols=4, rows=4, bar=0.45, frame=0.8)
for side in (-1, 1):
    grating(f"hvac_side_louver_{name_part(side)}", 118, 10, 0.7, (120, side * 25.4, 211), "#606a6f",
            pattern="планки", vertical=True, bars=14, bar=0.65, frame=0.8)
for i, x in enumerate((-430, -250, -60, 300, 450), 1):
    seam_path = [[x, -76.8, 179], [x, -61, 190.5], [x, -37, 201.5],
                 [x, 0, 207.5], [x, 37, 201.5], [x, 61, 190.5], [x, 76.8, 179]]
    sweep(f"roof_seam_{i}", seam_path, 0.42, "#d0d3d4", sides=10, smooth=2)
for i, x in enumerate((-300, 355), 1):
    cylinder(f"roof_vent_{i}", 5.0, 6, (x, 0, 210), "#7c868b", segments=40)
    cylinder(f"roof_vent_cap_{i}", 6.2, 1.4, (x, 0, 213.5), "#a9b0b3", segments=40)
add()

# ---------------------------------------------------------------------------
# Салон: отделка, девять открытых секций, 36 основных и 18 боковых мест.
# ---------------------------------------------------------------------------
add("# --- Салон: 9 секций, 36 основных + 18 боковых пассажирских мест ---")
box("int_floor_finish", (1164, 140, 0.8), (0, 0, 67.4), "#6a6158")
box("int_aisle_carpet", (840, 32, 0.35), (30, -27, 67.95), "#334d5b", 0.12)
for side in (-1, 1):
    box(f"int_wall_lower_{name_part(side)}", (1164, 0.6, 43), (0, side * 71.05, 89), "#d4cbbb", 0.2)
    box(f"int_wall_upper_{name_part(side)}", (1164, 0.6, 19), (0, side * 71.05, 168.5), "#ded5c5", 0.2)


def bedding(prefix: str, x: float, y: float, sx: float, sy: float,
            upper: bool, color: str, pillow_x: float | None = None) -> None:
    frame_z = 132.5 if upper else 81.5
    mattress_z = 136.5 if upper else 85.5
    box(f"{prefix}_frame", (sx, sy, 3), (x, y, frame_z), "#b9b2a5", 0.8)
    box(f"{prefix}_mattress", (sx - 1.2, sy - 1.2, 5), (x, y, mattress_z), color, 1.8)
    px = x if pillow_x is None else pillow_x
    pillow_y = y + (sy * 0.30 if sy >= sx else 0)
    pillow_size = (min(22, sx - 5), min(16, sy - 5), 3) if sy >= sx else (min(16, sx - 5), min(20, sy - 5), 3)
    box(f"{prefix}_pillow", pillow_size, (px, pillow_y, mattress_z + 4), "#eee9dd", 1.2)
    if not upper:
        box(f"{prefix}_base", (sx, sy, 13), (x, y, 73.5), "#7f7770", 1.0)
        blanket_size = (sx - 5, min(30, sy * 0.42), 0.9) if sy >= sx else (min(34, sx * 0.42), sy - 5, 0.9)
        blanket_y = y - sy * 0.20 if sy >= sx else y
        blanket_x = x - sx * 0.20 if sx > sy else x
        box(f"{prefix}_blanket", blanket_size, (blanket_x, blanket_y, 88.45), "#7e2938", 0.35)


for i, x in enumerate(SECTION_CENTERS, 1):
    tag = f"{i:02d}"
    main_color = "#7f2e3e" if i % 3 else "#743040"
    # Основные места: две пары полок длиной по Y у стены +Y.
    for berth_index, dx in enumerate((-22.0, 22.0), 1):
        bx = x + dx
        bedding(f"berth_main_{tag}_{berth_index}_lower", bx, 31.0, 42, 79, False, main_color)
        bedding(f"berth_main_{tag}_{berth_index}_upper", bx, 31.0, 42, 79, True, main_color)
        cylinder(f"berth_main_{tag}_{berth_index}_upper_rail", 0.5, 36,
                 (bx, -9.5, 143), "#c6c9c7", axis="x", segments=16)
        for post, px in enumerate((bx - 17, bx + 17), 1):
            cylinder(f"berth_main_{tag}_{berth_index}_railpost_{post}", 0.45, 4,
                     (px, -9.5, 141), "#bfc3c2", segments=12)
    for post, px in enumerate((x - 43.4, x + 43.4), 1):
        cylinder(f"berth_main_{tag}_post_{post}", 0.7, 65,
                 (px, 68, 99.5), "#b9bdbc", segments=16)
    # Общая лестница на верхние основные полки, не выступает в коридор.
    for rail, dx in enumerate((-4.0, 4.0), 1):
        cylinder(f"ladder_main_{tag}_rail_{rail}", 0.55, 51,
                 (x + dx, -9.8, 111.5), "#c5c8c7", segments=16)
        sweep(f"ladder_main_{tag}_hook_{rail}",
              [[x + dx, -9.8, 133.5], [x + dx, -7.0, 133.5]], 0.55, "#c5c8c7")
    for rung, z in enumerate((94, 108, 122), 1):
        cylinder(f"ladder_main_{tag}_rung_{rung}", 0.5, 8,
                 (x, -9.8, z), "#c5c8c7", axis="x", segments=16)
    # Столик у окна между нижними полками.
    box(f"table_main_{tag}", (14, 36, 2), (x, 50, 99), "#c5b69e", 0.8)
    for bracket, dx in enumerate((-5, 5), 1):
        sweep(f"table_main_{tag}_bracket_{bracket}",
              [[x + dx, 70.5, 91], [x + dx, 38, 98]], 0.55, "#9c9f9d")
    grating(f"luggage_main_{tag}", 84, 55, 0.8, (x, 35, 176), "#b8bcba",
            pattern="планки", bars=8, bar=0.65, frame=0.8)
    cylinder(f"luggage_main_{tag}_rail", 0.65, 84, (x, 6.8, 179), "#c4c7c5", axis="x", segments=16)
    for bracket, dx in enumerate((-35, 35), 1):
        sweep(f"luggage_main_{tag}_bracket_{bracket}",
              [[x + dx, 70.7, 168], [x + dx, 60, 176], [x + dx, 10, 176]], 0.55, "#b8bcba")
    grating(f"pocket_main_{tag}", 20, 12, 0.55, (x, 70.6, 113), "#8e9290",
            pattern="клетка", vertical=True, cols=3, rows=2, bar=0.35, frame=0.55)
    text(f"section_number_{tag}", str(i), 3.0, (x, -9.05, 131), "#f1e7d3")
    # Боковые места: длина по X у стены -Y.
    bedding(f"berth_side_{tag}_lower", x, -58.3, 88, 27, False, "#823244", pillow_x=x - 27)
    bedding(f"berth_side_{tag}_upper", x, -58.3, 88, 27, True, "#823244", pillow_x=x - 27)
    # Верхняя боковая полка ниже основной, как в плацкартном салоне.
    for suffix in ("frame", "mattress", "pillow"):
        add(f"translate [berth_side_{tag}_upper_{suffix}] offset=[0,0,-10]")
    for post, dx in enumerate((-44.1, 44.1), 1):
        cylinder(f"berth_side_{tag}_post_{post}", 0.6, 45,
                 (x + dx, -47, 102.5), "#b8bcba", segments=16)
    cylinder(f"berth_side_{tag}_safety_rail", 0.5, 72,
             (x, -44.6, 134), "#c3c6c4", axis="x", segments=16)
    for post, dx in enumerate((-34, 34), 1):
        cylinder(f"berth_side_{tag}_railpost_{post}", 0.45, 10,
                 (x + dx, -44.6, 129), "#bfc3c1", segments=12)
    box(f"table_side_{tag}", (24, 8, 1.5), (x, -66.5, 102), "#c6b79f", 0.6)
    cylinder(f"table_side_{tag}_hinge", 0.7, 24, (x, -71.0, 102), "#a8adab", axis="x", segments=16)
    text(f"side_number_{tag}", f"{i*2-1}/{i*2}", 2.3, (x, -44.1, 123), "#f1e7d3", far=True)
    if i in (1, 5, 9):
        socket(f"socket_main_{tag}", (x, 71.0, 108))

# Линейные светильники и вентиляция под сводом.
for i, x in enumerate((-340, -190, -40, 110, 260, 405), 1):
    box(f"ceiling_light_{i}", (72, 8, 1.4), (x, -20, 198.8), "#e8e2cf", 0.5)
    paint(f"ceiling_light_{i}", "#fff1cf", rough=0.3, emissive="#ffe2a3")
    grating(f"ceiling_vent_{i}", 28, 10, 0.6, (x + 45, -20, 198.5), "#b4b9b7",
            pattern="планки", bars=5, bar=0.45, frame=0.6)
add()

# ---------------------------------------------------------------------------
# Служебные помещения, два туалета и двухместное купе проводников.
# ---------------------------------------------------------------------------
add("# --- Туалеты, служебное отделение и двухместное купе проводников ---")
rooms = [
    ("toilet_left", -550.0, -515.0),
    ("service", -515.0, -475.0),
    ("crew", -475.0, -390.0),
    ("toilet_right", 490.0, 540.0),
]
for room, xa, xb in rooms:
    xc = (xa + xb) / 2
    length = xb - xa
    partition = f"int_{room}_partition"
    box(partition, (length, 1.5, 113), (xc, 12, 123.5), "#d7cdbc", 0.35)
    door_x = xc if room != "crew" else -405
    cut(partition, f"cut_{room}_door", (24, 5, 85), (door_x, 12, 109.5), 1.2)
    box(f"int_{room}_door", (22, 1.4, 83), (door_x, 12, 108.5), "#c8bca9", 0.8)
    cylinder(f"int_{room}_door_handle", 0.55, 2.5, (door_x + 7, 10.8, 110), "#b8a26c", axis="y", segments=16)
    for boundary, xx in (("a", xa), ("b", xb)):
        if boundary == "b" and xx in (-515, -475):
            continue  # общая стенка уже создана соседним помещением
        box(f"int_{room}_cross_{boundary}", (1.5, 58.65, 113), (xx, 42.075, 123.5), "#d2c7b6", 0.3)
    box(f"int_{room}_ceiling", (length, 59.4, 1.5), (xc, 41.7, 180.5), "#ddd5c7", 0.3)
    box(f"int_{room}_light", (18, 7, 0.8), (xc, 40, 179.3), "#eee5ce", 0.3)
    paint(f"int_{room}_light", "#fff0ce", rough=0.3, emissive="#ffe1a0")


def toilet_fixture(room: str, x: float) -> None:
    # Пьедестал, чаша с полостью, сиденье и закрытая крышка — отдельные тела.
    lathe(f"toilet_{room}_pedestal", [[0, 0], [5, 0], [5.5, 3], [4.5, 12], [0, 12]],
          (x, 52, 67), "#dedbd2", segments=48, fillet=0.35)
    lathe(f"toilet_{room}_bowl", [[4, 8], [7, 9], [9, 15], [8.5, 20], [6, 20],
                                   [5.5, 15], [3.5, 10], [4, 8]],
          (x, 52, 67), "#e7e3da", segments=56, fillet=0.25)
    lathe(f"toilet_{room}_seat", [[5.5, 20], [9, 20], [9.2, 21.5], [5.5, 21.5], [5.5, 20]],
          (x, 52, 67), "#c8c5bc", segments=56)
    box(f"toilet_{room}_lid", (14, 15, 1.5), (x, 52, 89.5), "#d9d5cc", 0.65)
    cylinder(f"toilet_{room}_flush", 1.4, 1.2, (x + 7, 63, 102), "#b8bdbd", segments=24)
    # Умывальник и смеситель у входа.
    box(f"toilet_{room}_vanity", (16, 15, 28), (x, 27, 81), "#b8b1a6", 1.2)
    lathe(f"toilet_{room}_sink", [[0, 0], [7.5, 0], [8, 2], [7.2, 7], [5.8, 8],
                                   [5.2, 3], [0, 2], [0, 0]],
          (x, 27, 95), "#e1ded5", segments=56, fillet=0.2)
    sweep(f"toilet_{room}_faucet", [[x, 34, 99], [x, 34, 108], [x, 28, 108], [x, 27, 105]],
          0.55, "#bfc5c6", smooth=4)
    box(f"toilet_{room}_mirror", (14, 0.5, 20), (x, 70.8, 128), "#a8bdc4", 0.5)
    paint(f"toilet_{room}_mirror", "#b7c9cf", metal=0.9, rough=0.08)
    cylinder(f"toilet_{room}_paper", 2.2, 4, (x + 10, 65, 105), "#e7e0d1", axis="y", segments=28)
    cylinder(f"toilet_{room}_bin", 3.0, 10, (x - 10, 35, 72), "#777f80", segments=32)
    sweep(f"toilet_{room}_pipe", [[x, 52, 68], [x, 58, 66], [x, 66, 64]], 1.0, "#656e70")


toilet_fixture("left", -532.5)
toilet_fixture("right", 515)

# Двухместное купе проводников: две полки не входят в 54 пассажирских места.
bedding("crew_lower", -432.5, 45, 80, 32, False, "#6f3542", pillow_x=-460)
bedding("crew_upper", -432.5, 45, 80, 32, True, "#6f3542", pillow_x=-460)
box("crew_table", (20, 20, 2), (-402, 27, 99), "#c4b49c", 0.8)
for rail, y in enumerate((22, 30), 1):
    cylinder(f"crew_ladder_rail_{rail}", 0.5, 46, (-393, y, 110), "#bfc3c1", segments=16)
for rung, z in enumerate((94, 108, 122), 1):
    cylinder(f"crew_ladder_rung_{rung}", 0.45, 8, (-393, 26, z), "#bfc3c1", axis="y", segments=16)

# Титан, холодильник, СВЧ, шкаф и электрика служебного отделения.
box("service_fridge", (22, 22, 44), (-502, 27, 89), "#c6c8c4", 1.5)
box("service_fridge_door", (20, 1.0, 40), (-502, 15.6, 89), "#d6d7d2", 0.8)
cylinder("service_fridge_handle", 0.45, 14, (-494, 14.8, 91), "#777f80", segments=16)
box("service_microwave", (22, 18, 14), (-502, 29, 118), "#858d8e", 1.2)
box("service_microwave_door", (18, 0.8, 10), (-502, 19.6, 118), "#3f4a4e", 0.6)
cylinder("service_titan", 7.0, 42, (-484, 55, 88), "#9da5a5", segments=48)
paint("service_titan", "#9da5a5", metal=0.65, rough=0.32)
cylinder("service_titan_cap", 7.5, 1.5, (-484, 55, 109.5), "#bdc2c0", segments=48)
sweep("service_titan_tap", [[-484, 48, 82], [-484, 44, 82], [-484, 44, 79]], 0.6, "#c3c7c5")
box("service_cabinet", (12, 24, 70), (-506, 52, 102), "#b6aa98", 1.0)
switch("service_switch", (-480, 12.4, 120))
socket("service_socket", (-490, 70.9, 128))

# Пожарное и аварийное оборудование в тамбурах.
for end, x in (("left", -575), ("right", 575)):
    cylinder(f"vestibule_{end}_extinguisher", 3.0, 18, (x, 55, 78), "#a62d35", segments=36)
    cylinder(f"vestibule_{end}_extinguisher_neck", 1.0, 3, (x, 55, 88.5), "#c0c3bd", segments=20)
    box(f"vestibule_{end}_emergency_box", (10, 3, 14), (x, -68, 115), "#b13a3e", 0.8)
    text(f"vestibule_{end}_label", "АВАРИЙНЫЙ", 2.2, (x, -70, 120), "#f4e9da")
add()

# ---------------------------------------------------------------------------
# Небольшой участок пути: рельсы с профилем, шпалы, крепления и балласт.
# ---------------------------------------------------------------------------
add("# --- Участок пути; это окружение, не второй вагон ---")
rail_profile = [[-6.5, -33], [6.5, -33], [6.5, -30], [1.0, -27], [0.8, -6],
                [3.0, -4], [3.0, 0], [-3.0, 0], [-3.0, -4], [-0.8, -6],
                [-1.0, -27], [-6.5, -30]]
for tag, y in (("near", -38), ("far", 38)):
    profile = [[round(py + y, 4), pz] for py, pz in rail_profile]
    emit(f"track_rail_{tag} = loft sections=[{profile},{profile}] positions=[-650,650] "
         "axis=x smooth=1 color=#565f63", "track")
    paint(f"track_rail_{tag}", "#596267", metal=0.72, rough=0.34)
box("track_ballast_bed", (1300, 125, 6), (0, 0, -45), "#4f4c48", 1.0, "track")
box("track_sleeper_proto", (12, 112, 6), (-620, 0, -36), "#60564b", 0.7, "track")
emit("track_sleepers = array [track_sleeper_proto] mode=linear count=22 "
     "offset=[59,0,0] as=merged", "track")
TRACK.discard("track_sleeper_proto")
for side in (-1, 1):
    emit(f"track_fastener_proto_{name_part(side)} = prism sides=6 radius=1.2 height=1.2 "
         f"at=[-620,{side*45},-33] color=#333b3e", "track")
    emit(f"track_fasteners_{name_part(side)} = array [track_fastener_proto_{name_part(side)}] mode=linear "
         f"count=22 offset=[59,0,0] as=merged", "track")
    TRACK.discard(f"track_fastener_proto_{name_part(side)}")
emit("track_stone_proto = rock size=[5,4,3] points=16 rough=0.45 seed=4194 flat=да color=#706a61", "track")
emit("track_stones = scatter [track_stone_proto] count=140 area=[1280,115] "
     "scale=[0.6,1.3] z=-42 as=merged seed=4194", "track")
TRACK.discard("track_stone_proto")
add()

# Непересекающиеся группы: весь вагон целиком и отдельный путь.
add("# --- Группы для выбора и скрытия без изменения геометрии ---")
add("wagon = group [" + ",".join(sorted(CAR)) + "]")
add("track = group [" + ",".join(sorted(TRACK)) + "]")
for name in ("car_wall_far", "car_wall_near", "car_roof", "car_end_left", "car_end_right",
             "under_water_tank", "toilet_left_bowl", "toilet_right_sink"):
    add(f"check {name} watertight")
add("# Дополнительный ручной контроль: interference tolerance=0.02 limit=200")


def make_script() -> str:
    return "\n".join(lines) + "\n"


def bbox(solid) -> np.ndarray:
    return np.asarray(solid.manifold.bounding_box(), dtype=float)


def aabb_overlap(a, b, eps=1e-5) -> bool:
    return bool(np.all(np.minimum(a[3:], b[3:]) - np.maximum(a[:3], b[:3]) > eps))


def intersection_volume(a, b) -> float:
    if not aabb_overlap(bbox(a), bbox(b)):
        return 0.0
    return abs(float((a.manifold ^ b.manifold).volume()))


def allowed_contact(a: str, b: str) -> bool:
    # Только очевидные крепёжные/опорные соединения в focused interference.
    pair = {a, b}
    if any(n.startswith(("win_", "door_", "rib_", "livery_", "logo_", "number_")) for n in pair):
        return True
    if any(n.startswith(("berth_", "ladder_", "table_", "luggage_")) for n in pair):
        return True
    if a.split(".")[0] == b.split(".")[0]:
        return True
    return False


def validate(result):
    solids = result.visible_solids()
    objects = {s.name: s for s in solids}
    problems: list[str] = []
    triangles = 0
    degenerate = []
    for solid in solids:
        status = str(solid.manifold.status())
        volume = float(solid.manifold.volume())
        bounds = bbox(solid)
        if status not in ("NoError", "Error.NoError") or solid.manifold.is_empty() or volume <= 1e-7:
            problems.append(f"{solid.name}: status={status}, volume={volume}")
        if not np.all(np.isfinite(bounds)):
            problems.append(f"{solid.name}: нечисловой bounding box")
        vertices, faces = manifold_mesh(solid.manifold)
        triangles += len(faces)
        if not np.all(np.isfinite(vertices)):
            problems.append(f"{solid.name}: нечисловые вершины")
        if len(faces):
            tri = vertices[faces]
            area2 = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
            bad = int(np.count_nonzero(area2 <= 1e-12))
            if bad:
                degenerate.append({"object": solid.name, "faces": bad})
    if degenerate:
        problems.append(f"Вырожденные треугольники: {sum(x['faces'] for x in degenerate)}")

    placement = {}
    for name, sign, x in (("logo_far_rzd", 1, -260), ("logo_near_rzd", -1, -260),
                          ("number_far_text", 1, 480), ("number_near_text", -1, 480)):
        b = bbox(objects[name])
        center = (b[:3] + b[3:]) / 2
        placement[name] = center.tolist()
        if center[1] * sign < 77 or abs(center[0] - x) > 0.01:
            problems.append(f"{name}: надпись смещена поворотом: {center}")
    for name in ("side_number_01", "side_number_09"):
        center = (bbox(objects[name])[:3] + bbox(objects[name])[3:]) / 2
        placement[name] = center.tolist()
        if center[1] > -43:
            problems.append(f"{name}: номер бокового места ушёл на противоположную сторону")
    for solid in solids:
        if solid.name.startswith("hvac_fan_") and "_blade_" in solid.name:
            center = (bbox(solid)[:3] + bbox(solid)[3:]) / 2
            if abs(center[1]) > 10:
                problems.append(f"{solid.name}: лопасть ушла с крыши: {center}")

    # Справочные продольные размеры и принятая колея/базы.
    skin = [s for s in solids if s.name.startswith(("car_wall_", "rib_", "car_roof"))]
    width = max(bbox(s)[4] for s in skin) - min(bbox(s)[1] for s in skin)
    coupler_span = (bbox(objects["coupler_right_head"])[3] + bbox(objects["coupler_right_head"])[0]) / 2 - \
                   (bbox(objects["coupler_left_head"])[3] + bbox(objects["coupler_left_head"])[0]) / 2
    wagon_base = bbox(objects["bogie_right_kingpin"])[0] - bbox(objects["bogie_left_kingpin"])[0]
    bogie_base = bbox(objects["axle_left_2"])[0] - bbox(objects["axle_left_1"])[0]
    dimensions = {
        "body_width_mm": float(width), "coupler_axes_mm": float(coupler_span),
        "wagon_base_mm": float(wagon_base), "bogie_base_mm": float(bogie_base),
        "wheel_diameter_mm": float(bbox(objects["wheel_left_1_near"])[5] - bbox(objects["wheel_left_1_near"])[2]),
        "wheel_contact_z": float(bbox(objects["wheel_left_1_near"])[2]),
        "rail_head_z": float(bbox(objects["track_rail_near"])[5]),
        "rail_gauge_mm": float((bbox(objects["track_rail_far"])[1] + bbox(objects["track_rail_far"])[4]) / 2 -
                              (bbox(objects["track_rail_near"])[1] + bbox(objects["track_rail_near"])[4]) / 2),
    }
    expected = {"body_width_mm": 155.25, "coupler_axes_mm": 1226.85,
                "wagon_base_mm": 850.0, "bogie_base_mm": 120.0,
                "wheel_diameter_mm": 47.5, "wheel_contact_z": 0.0, "rail_head_z": 0.0,
                "rail_gauge_mm": 76.0}
    for key, target in expected.items():
        if abs(dimensions[key] - target) > 0.002:
            problems.append(f"{key}: {dimensions[key]} вместо {target}")

    # Ровно 54 пассажирских спальных места; купе проводников считается отдельно.
    passenger_mattresses = [s for s in solids if s.name.startswith("berth_") and s.name.endswith("_mattress")]
    main_lower = [s for s in passenger_mattresses if s.name.startswith("berth_main_") and "_lower_" in s.name]
    main_upper = [s for s in passenger_mattresses if s.name.startswith("berth_main_") and "_upper_" in s.name]
    side_lower = [s for s in passenger_mattresses if s.name.startswith("berth_side_") and "_lower_" in s.name]
    side_upper = [s for s in passenger_mattresses if s.name.startswith("berth_side_") and "_upper_" in s.name]
    berth_counts = {"main_lower": len(main_lower), "main_upper": len(main_upper),
                    "side_lower": len(side_lower), "side_upper": len(side_upper),
                    "passenger_total": len(passenger_mattresses),
                    "crew": len([s for s in solids if s.name in ("crew_lower_mattress", "crew_upper_mattress")])}
    if berth_counts != {"main_lower": 18, "main_upper": 18, "side_lower": 9,
                        "side_upper": 9, "passenger_total": 54, "crew": 2}:
        problems.append(f"Неверный состав мест: {berth_counts}")
    for solid in main_lower + main_upper:
        b = bbox(solid)
        if not (b[4] - b[1] > b[3] - b[0]):
            problems.append(f"{solid.name}: основная полка не ориентирована по Y")
    for solid in side_lower + side_upper:
        b = bbox(solid)
        if not (b[3] - b[0] > b[4] - b[1]):
            problems.append(f"{solid.name}: боковая полка не ориентирована по X")

    # Объёмные зонды проёмов: стекло/дверь специально не входят в проверку стены.
    opening_results = []
    for wall in ("far", "near"):
        side = 1 if wall == "far" else -1
        for index, (x, z, w, h) in enumerate(OPENINGS[wall], 1):
            probe = mf.Manifold.cube((max(1, w - 5), 12, max(1, h - 5)), True).translate((x, side * 73.9, z))
            residual = abs(float((objects[f"car_wall_{wall}"].manifold ^ probe).volume()))
            opening_results.append({"wall": wall, "index": index, "residual_mm3": residual})
            if residual > 1e-4:
                problems.append(f"Проём {wall}/{index} не сквозной: {residual}")

    interior_door_probes = []
    for room, xa, xb in rooms:
        door_x = (xa + xb) / 2 if room != "crew" else -405
        probe = mf.Manifold.cube((18, 5, 78), True).translate((door_x, 12, 108.5))
        residual = abs(float((objects[f"int_{room}_partition"].manifold ^ probe).volume()))
        interior_door_probes.append({"room": room, "residual_mm3": residual})
        if residual > 1e-4:
            problems.append(f"Внутренняя дверь {room} не сквозная: {residual}")

    # Свободный коридор по всем девяти секциям, от пола до верхних полок.
    aisle_probe = mf.Manifold.cube((836, 32, 87.8), True).translate((30, -27, 112.1))
    aisle_hits = []
    for solid in solids:
        if solid.name.startswith("track_"):
            continue
        if not aabb_overlap(bbox(solid), [-392, -43, 68.2, 448, -11, 156]):
            continue
        volume = abs(float((solid.manifold ^ aisle_probe).volume()))
        if volume > 0.02:
            aisle_hits.append({"object": solid.name, "volume_mm3": round(volume, 5)})
    if aisle_hits:
        problems.append(f"Коридор занят: {len(aisle_hits)} объектов")

    # Колёса и гребни не должны врезаться в рельс: касание проверяется по Z отдельно.
    wheel_rail_hits = []
    for solid in solids:
        if not solid.name.startswith(("wheel_", "flange_")):
            continue
        for rail in ("track_rail_near", "track_rail_far"):
            volume = intersection_volume(solid, objects[rail])
            if volume > 0.002:
                wheel_rail_hits.append({"wheel": solid.name, "rail": rail, "volume_mm3": volume})
    if wheel_rail_hits:
        problems.append(f"Колёса пересекают рельсы: {len(wheel_rail_hits)}")

    # Подвагонные ёмкости не заходят в колёса/рамки тележек.
    under_hits = []
    equipment = [objects[n] for n in ("under_water_tank", "under_battery_box", "under_generator",
                                     "under_brake_reservoir", "under_electrical_cabinet")]
    running = [s for s in solids if s.name.startswith(("wheel_", "flange_", "bogie_", "axlebox_"))]
    for a in equipment:
        for b in running:
            volume = intersection_volume(a, b)
            if volume > 0.02:
                under_hits.append({"equipment": a.name, "running": b.name, "volume_mm3": volume})
    if under_hits:
        problems.append(f"Оборудование пересекает ходовую часть: {len(under_hits)}")

    # Focused interference среди основных панелей и мебели; крепёж учитывается отдельно.
    structural_names = ["car_floor", "car_roof", "car_wall_far", "car_wall_near",
                        "car_end_left", "car_end_right", "frame_center"]
    structural_hits = []
    for a_name, b_name in combinations(structural_names, 2):
        volume = intersection_volume(objects[a_name], objects[b_name])
        if volume > 0.02:
            structural_hits.append({"a": a_name, "b": b_name, "volume_mm3": volume})
    # Крыша/торцы и рама/пол имеют проектные стыки с небольшим заходом; это соединения, не дефект.
    unexpected_structural = [h for h in structural_hits if {h["a"], h["b"]} not in
                             ({"car_roof", "car_wall_far"}, {"car_roof", "car_wall_near"},
                              {"car_roof", "car_end_left"}, {"car_roof", "car_end_right"},
                              {"car_end_left", "car_wall_far"}, {"car_end_left", "car_wall_near"},
                              {"car_end_right", "car_wall_far"}, {"car_end_right", "car_wall_near"})]
    if unexpected_structural:
        problems.append(f"Неожиданные пересечения несущих панелей: {len(unexpected_structural)}")

    service_panels = [s for s in solids if s.name.startswith("int_") and
                      any(k in s.name for k in ("_partition", "_cross_", "_ceiling"))]
    service_panel_hits = []
    for a, b in combinations(service_panels, 2):
        volume = intersection_volume(a, b)
        if volume <= 0.02:
            continue
        # Потолочная панель на 0.25 мм заходит на верхний торец стены.
        if "ceiling" in a.name or "ceiling" in b.name:
            continue
        service_panel_hits.append({"a": a.name, "b": b.name, "volume_mm3": volume})
    if service_panel_hits:
        problems.append(f"Дубли/пересечения служебных перегородок: {len(service_panel_hits)}")

    support_counts = {
        "luggage_brackets": len([s for s in solids if s.name.startswith("luggage_main_") and "_bracket_" in s.name]),
        "side_rail_posts": len([s for s in solids if s.name.startswith("berth_side_") and "_railpost_" in s.name]),
        "ladder_hooks": len([s for s in solids if s.name.startswith("ladder_main_") and "_hook_" in s.name]),
    }
    if support_counts != {"luggage_brackets": 18, "side_rail_posts": 18, "ladder_hooks": 18}:
        problems.append(f"Не хватает креплений: {support_counts}")

    berth_solids = [s for s in solids if s.name.startswith("berth_") and
                    s.name.endswith(("_base", "_frame", "_mattress", "_pillow", "_blanket"))]
    furniture_hits = []
    for a, b in combinations(berth_solids, 2):
        if not aabb_overlap(bbox(a), bbox(b)):
            continue
        # Детали одной полки опираются друг на друга; разные полки пересекаться не должны.
        root_a = a.name.rsplit("_", 1)[0]
        root_b = b.name.rsplit("_", 1)[0]
        if root_a == root_b:
            continue
        volume = intersection_volume(a, b)
        if volume > 0.02:
            furniture_hits.append({"a": a.name, "b": b.name, "volume_mm3": volume})
    if furniture_hits:
        problems.append(f"Пересечения разных полок: {len(furniture_hits)}")

    report = {
        "scene": str(SCENE_PATH), "scale": "1:20", "single_car": True,
        "objects": len(solids), "triangles": triangles,
        "all_bodies_valid": not any("status=" in p for p in problems),
        "degenerate_faces": degenerate, "placement": placement, "dimensions": dimensions,
        "berths": berth_counts, "opening_probes": opening_results,
        "interior_door_probes": interior_door_probes, "support_counts": support_counts,
        "aisle_obstructions": aisle_hits, "wheel_rail_intersections": wheel_rail_hits,
        "underfloor_running_intersections": under_hits,
        "structural_contacts": structural_hits,
        "unexpected_structural_intersections": unexpected_structural,
        "service_panel_intersections": service_panel_hits,
        "furniture_intersections": furniture_hits,
        "problems": problems,
    }
    if problems:
        raise RuntimeError(json.dumps(report, ensure_ascii=False, indent=2))
    return report, solids


def render(solids, groups, view: str, path: Path, size: int = 1100,
           center=None, radius=None, margin: float = 1.08) -> None:
    from PIL import Image
    meshes = _prepare(solids, groups)
    if not meshes:
        raise ValueError(f"Нет объектов для {path}")
    vertices = np.concatenate([m["verts"] for m in meshes])
    lo, hi = vertices.min(0), vertices.max(0)
    if center is None:
        center = (lo + hi) / 2.0
    if radius is None:
        radius = float(np.linalg.norm(hi - lo)) / 2.0 * margin
    image, _ = _render_view(meshes, center, radius, view, size, 1,
                            [*lo, *hi], grid=False, shadow=True, bg=BG, style=None)
    Image.fromarray((np.clip(image, 0, 1) * 255).astype(np.uint8), "RGB").save(path)


def contact_sheet(paths: list[tuple[str, Path]], output: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 23)
    title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
    tile, header, label = 760, 92, 50
    canvas = Image.new("RGB", (tile * 2 + 60, header + (tile + label) * 2 + 40), (17, 23, 30))
    draw = ImageDraw.Draw(canvas)
    draw.text((28, 24), "Плацкартный вагон 61-4194 · 1:20 · один вагон", font=title_font, fill=(238, 240, 235))
    for i, (caption, path) in enumerate(paths):
        image = Image.open(path).convert("RGB").resize((tile, tile), Image.Resampling.LANCZOS)
        x = 20 + (i % 2) * (tile + 20)
        y = header + (i // 2) * (tile + label + 20)
        canvas.paste(image, (x, y))
        draw.text((x + 8, y + tile + 9), caption, font=font, fill=(215, 222, 224))
    canvas.save(output, optimize=True)


def interior_solids(solids):
    """Только фильтр существующих solids: крыша и ближняя стена скрыты для вида."""
    result = []
    for s in solids:
        n = s.name
        if n.startswith("track_"):
            continue
        if n == "car_roof" or n.startswith(("roof_", "hvac_")):
            continue
        if n == "car_wall_near" or n in ("int_wall_lower_m1", "int_wall_upper_m1") or n.startswith(
                ("win_near_", "door_near_", "rib_near_", "livery_near_", "logo_near_",
                 "number_near_", "capacity_near_")):
            continue
        if n.startswith(("bogie_", "wheel_", "flange_", "axle", "bearing_", "hub", "brake_",
                         "spring_", "primary_spring_", "under_")):
            continue
        result.append(s)
    return result


def glb_roundtrip(result, glb_path: Path, solids):
    import trimesh
    loaded = trimesh.load(glb_path, file_type="glb", force="scene")
    mesh = loaded.to_mesh()
    gltf_bounds = np.asarray(mesh.bounds, dtype=float)
    if not np.all(np.isfinite(gltf_bounds)) or len(mesh.faces) == 0:
        raise RuntimeError("GLB round-trip: пустая или нечисловая сцена")
    # Экспорт Forma переводит Z-up в glTF Y-up: (x, z, -y).
    forma_bounds = np.array([
        [gltf_bounds[0, 0], -gltf_bounds[1, 2], gltf_bounds[0, 1]],
        [gltf_bounds[1, 0], -gltf_bounds[0, 2], gltf_bounds[1, 1]],
    ])
    source_lo = np.min([bbox(s)[:3] for s in solids], axis=0)
    source_hi = np.max([bbox(s)[3:] for s in solids], axis=0)
    source_bounds = np.array([source_lo, source_hi])
    deviation = float(np.max(np.abs(forma_bounds - source_bounds)))
    expected_faces = sum(len(manifold_mesh(s.manifold)[1]) for s in solids)
    if deviation > 0.002 or len(mesh.faces) != expected_faces:
        raise RuntimeError(f"GLB round-trip: deviation={deviation}, faces={len(mesh.faces)}/{expected_faces}")
    return {"importer": "trimesh", "vertices": int(len(mesh.vertices)),
            "faces": int(len(mesh.faces)), "expected_faces": int(expected_faces),
            "bounds_gltf_yup": gltf_bounds.tolist(), "bounds_forma_zup": forma_bounds.tolist(),
            "max_bounds_deviation_mm": deviation, "axis_map": "glTF(x,y,z) = Forma(x,z,-y)",
            "watertight_components_note": "Сцена содержит отдельные детали; общий mesh не обязан быть одним телом."}


def main() -> None:
    script = make_script()
    SCENE_PATH.write_text(script, encoding="utf-8")
    result = build(script, analyze_model=False)
    if not result.ok:
        raise SystemExit(str(result.error) + "\n" + str(result.log))
    report, solids = validate(result)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    glb_path = EXPORT_DIR / "train_carriage.glb"
    glb_path.write_bytes(result.glb())
    report["glb_roundtrip"] = glb_roundtrip(result, glb_path, solids)

    rendered = []
    exterior_path = RENDER_DIR / "train_exterior_iso.png"
    render(solids, result.scene.groups, "iso", exterior_path, 1200, margin=0.92)
    rendered.append(("Экстерьер: гофры, РЖД, тележки и путь", exterior_path))
    side_path = RENDER_DIR / "train_exterior_side.png"
    render(solids, result.scene.groups, "front", side_path, 1200)
    interior = interior_solids(solids)
    interior_path = RENDER_DIR / "train_interior_iso.png"
    render(interior, result.scene.groups, "iso", interior_path, 1200, margin=0.94)
    rendered.append(("Салон: 9 секций и боковые места", interior_path))
    top_path = RENDER_DIR / "train_interior_top.png"
    render(interior, result.scene.groups, "top", top_path, 1100)

    detail_center = SECTION_CENTERS[4]
    detail = [s for s in interior if -95 + detail_center <= (bbox(s)[0] + bbox(s)[3]) / 2 <= 95 + detail_center
              and bbox(s)[5] >= 67]
    detail_path = RENDER_DIR / "train_section_detail.png"
    render(detail, result.scene.groups, "iso", detail_path, 1050,
           center=(detail_center, 20, 116), radius=103)
    rendered.append(("Открытая секция: полки, столик и лестница", detail_path))

    bogie = [s for s in solids if any(token in s.name for token in ("_left_",)) and
             s.name.startswith(("bogie_", "wheel_", "flange_", "axle", "bearing_", "hub",
                                "brake_", "spring_", "primary_spring_"))]
    bogie_path = RENDER_DIR / "train_bogie_detail.png"
    render(bogie, result.scene.groups, "iso", bogie_path, 1050, margin=0.96)
    rendered.append(("Тележка: колёса, рессоры и тормоза", bogie_path))
    sheet_path = RENDER_DIR / "train_carriage_views.png"
    contact_sheet(rendered, sheet_path)

    report.update({
        "glb": str(glb_path), "glb_bytes": glb_path.stat().st_size,
        "renders": [str(p) for p in (exterior_path, side_path, interior_path, top_path,
                                      detail_path, bogie_path, sheet_path)],
        "render_method": "Та же сцена; interior-виды фильтруют существующие solids без разреза и копии вагона.",
        "blender_check": "Не выполнялся: в среде нет рабочего Blender/bpy; GLB повторно прочитан через trimesh.",
    })
    (RENDER_DIR / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
