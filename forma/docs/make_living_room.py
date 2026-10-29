"""Детальная миниатюрная гостиная 1:20 из собственных параметрических примитивов.

Запуск из корня репозитория:
    PYTHONPATH=forma python forma/docs/make_living_room.py

Создаёт examples/living_room_diorama.forma, GLB, четыре общих вида,
детальный вид журнального столика, контрольный лист и JSON с проверками.
Никакие внешние модели, сетки, текстуры или координатные шаблоны не используются.
"""
from __future__ import annotations

import json
import math
from itertools import combinations
from pathlib import Path

import manifold3d as mf
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.geometry import manifold_mesh
from forma.render import _prepare, _render_view
from forma.run import build

ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "examples" / "living_room_diorama.forma"
RENDER_DIR = ROOT / "renders" / "living_room"
EXPORT_DIR = ROOT / "exports" / "living_room"
BG = (0.075, 0.087, 0.105)

lines: list[str] = []


def add(text: str = "") -> None:
    lines.append(text)


def box(name: str, size, at, color: str, round_r: float = 0.0) -> None:
    if round_r:
        round_r = min(round_r, min(size) * 0.45)
    extra = f" round={round_r:g}" if round_r else ""
    add(f"{name} = box size={list(size)} center=да at={list(at)}{extra} color={color}")


def cylinder(name: str, radius: float, height: float, at, color: str,
             segments: int = 48) -> None:
    add(f"{name} = cylinder radius={radius} height={height} segments={segments} "
        f"at={list(at)} color={color}")


def door_transform(name: str) -> None:
    add(f"{name} = rotate [{name}] angle=-30 axis=z")
    add(f"{name} = translate [{name}] offset=[-160,-107,0]")


add("# ГОСТИНАЯ 1:20 — собственная параметрическая диорамма")
add("# Канон: +Z вверх, +X вправо, -Y вперёд. Все размеры в мм.")
add("# Полные задняя и левая стены; передняя и правая показаны низким архитектурным срезом.")
add()
add("# --- Витринное основание и деревянный пол ---")
box("display_base", (350, 270, 8), (0, 0, -12.8), "#26333a", 1.8)
box("floor_substrate", (340, 260, 8), (0, 0, -4.8), "#5c3d2d", 0.8)
box("name_plate", (126, 1.2, 7), (0, -135.2, -12.8), "#c7a968", 0.35)
add('name_text = text "ГОСТИНАЯ  1:20" size=6 depth=0.6 align=center '
    'plane=xz at=[0,-136,-15.5] color=#26333a')

floor_colors = ["#a97850", "#b38358", "#ad7b50", "#b9895e"]
count = 12
gap = 0.35
width = (320.0 - gap * (count - 1)) / count
for i in range(count):
    x0 = -160.0 + i * (width + gap)
    xc = x0 + width / 2
    joint = -22.0 if i % 2 == 0 else 24.0
    cuts = [(-120.0, joint - 0.18), (joint + 0.18, 120.0)]
    for j, (y0, y1) in enumerate(cuts):
        box(f"floor_{i:02d}_{j}", (width, y1 - y0, 0.8),
            (xc, (y0 + y1) / 2, -0.4), floor_colors[(i + j) % len(floor_colors)])
add()
add("# --- Стены с настоящими сквозными проёмами ---")
box("wall_back", (332, 6, 140), (0, 123, 70), "#e7dfcf", 0.45)
box("window_cut", (184, 12, 58), (20, 123, 98), "#ffffff")
add("wall_back = difference [wall_back,window_cut]")
box("wall_left", (6, 252, 140), (-163, 0, 70), "#e7dfcf", 0.45)
box("door_cut", (12, 70, 114), (-163, -72, 57), "#ffffff")
add("wall_left = difference [wall_left,door_cut]")
box("wall_front_cutaway", (332, 6, 10), (0, -123, 5), "#e7dfcf", 0.45)
box("wall_right_cutaway", (6, 240, 14), (163, 0, 7), "#e7dfcf", 0.45)
add("walls = union [wall_back,wall_left,wall_front_cutaway,wall_right_cutaway]")
box("baseboard_back", (320, 2, 7), (0, 119, 3.5), "#f5f0e6", 0.25)
box("baseboard_left_front", (2, 13, 7), (-159, -113.5, 3.5), "#f5f0e6", 0.25)
box("baseboard_left_rear", (2, 157, 7), (-159, 41.5, 3.5), "#f5f0e6", 0.25)
add()
add("# --- Двухстворчатое окно: четыре стекла, рама, ручка, подоконник ---")
for name, x in [("window_jamb_l", -70), ("window_jamb_r", 110),
                ("window_mullion", 20)]:
    box(name, (3.5 if name == "window_mullion" else 4, 5, 58),
        (x, 122.5, 98), "#f6f3e9", 0.3)
for name, z in [("window_rail_bottom", 71), ("window_rail_top", 125),
                ("window_crossbar", 98)]:
    box(name, (184, 5, 3.5 if name == "window_crossbar" else 4),
        (20, 122.5, z), "#f6f3e9", 0.3)
for row, z in enumerate((85, 111)):
    for col, x in enumerate((-24, 64)):
        box(f"window_glass_{row}_{col}", (84, 1, 22), (x, 123.5, z), "#b9e2e8", 0.15)
        add(f"color window_glass_{row}_{col} #b9e2e8 material=glass transmission=0.55 rough=0.08")
box("window_handle", (2, 3, 10), (23, 118.8, 96), "#c8b078", 0.6)
box("window_sill", (190, 16, 4), (15, 114, 67), "#f6f3e9", 0.8)
for name, x in [("window_trim_l", -75), ("window_trim_r", 115)]:
    box(name, (5, 3, 64), (x, 118.5, 98), "#f8f4eb", 0.35)
for name, z in [("window_trim_top", 129), ("window_trim_bottom", 67)]:
    box(name, (190, 3, 4), (20, 118.5, z), "#f8f4eb", 0.35)
add("curtain_rod = cylinder radius=1.5 height=210 segments=32 center=да")
add("curtain_rod = rotate [curtain_rod] angle=90 axis=y")
add("curtain_rod = translate [curtain_rod] offset=[20,104,135]")
add("color curtain_rod #b89b62 metal=0.65 rough=0.28")
for side, x in [("left", -64), ("right", 104)]:
    box(f"curtain_{side}", (14, 2.5, 62), (x, 107, 101), "#c98568", 1.0)
    for k, dx in enumerate((-4, 0, 4)):
        cylinder(f"curtain_{side}_pleat_{k}", 1.15, 62,
                 (x + dx, 105.4, 70), "#d7987b", 24)
for i, x in enumerate((-85, 125)):
    add(f"curtain_finial_{i} = sphere radius=3 at=[{x},104,135] color=#b89b62")
add()
add("# --- Открытая дверь, наличники, петли и фурнитура ---")
box("door_slab", (4, 70, 112), (-2, 35, 56), "#9a6b48", 0.65)
for index, z in enumerate((30, 79)):
    box(f"door_panel_cut_{index}", (1.5, 46, 34), (0.5, 35, z), "#ffffff", 0.7)
    add(f"door_slab = difference [door_slab,door_panel_cut_{index}]")
door_transform("door_slab")
for name, y in [("door_trim_front", -109), ("door_trim_back", -35)]:
    box(name, (4, 4, 116), (-159, y, 58), "#f8f4eb", 0.45)
box("door_trim_top", (4, 78, 4), (-159, -72, 116), "#f8f4eb", 0.45)
box("door_handle_plate", (1.2, 5, 14), (0.8, 61, 56), "#c8a75f", 0.45)
door_transform("door_handle_plate")
add("door_handle_knob = sphere radius=2.2 at=[2.2,61,56] color=#d7b76e")
door_transform("door_handle_knob")
box("door_handle_lever", (2, 11, 2), (3.3, 56.5, 56), "#d7b76e", 0.7)
door_transform("door_handle_lever")
for index, z in enumerate((23, 87)):
    cylinder(f"door_hinge_{index}", 1.8, 10, (-159.5, -106.5, z), "#b99a5e", 32)
box("light_switch", (1.2, 8, 12), (-159.2, -25, 55), "#f7f3ea", 0.8)
box("light_switch_toggle", (1.0, 3, 5), (-158.3, -25, 55), "#d4cec2", 0.45)
add()
add("# --- ТВ-тумба с настоящей открытой нишей и ящиками ---")
box("media_body", (30, 110, 26), (-140, 25, 20), "#6f4c38", 1.0)
box("media_recess_cut", (30, 34, 11), (-120, 25, 20), "#ffffff")
add("media_body = difference [media_body,media_recess_cut]")
for i, (x, y) in enumerate(((-150, -20), (-130, -20), (-150, 70), (-130, 70))):
    box(f"media_leg_{i}", (4, 4, 7), (x, y, 3.5), "#3d3430", 0.6)
for i, y in enumerate((-11, 61)):
    box(f"media_drawer_{i}", (1.5, 32, 10), (-124.2, y, 20), "#8a6248", 0.55)
    box(f"media_handle_{i}", (2, 14, 2), (-122.8, y, 20), "#c9aa6d", 0.75)
box("media_receiver", (8, 28, 7), (-131, 25, 20), "#252a2d", 0.5)
add("media_receiver_led = sphere radius=0.8 at=[-126.5,15,20] color=#78d9b4")
add("color media_receiver_led #78d9b4 emissive=#78d9b4 emissive_strength=2")
box("soundbar", (4, 70, 5), (-127, 25, 35.5), "#252a2e", 1.4)
for i in range(12):
    box(f"soundbar_slot_{i}", (0.5, 1.5, 2.2), (-124.8, -2 + i * 5, 35.5), "#0e1519", 0.2)
add()
add("# --- Телевизор на двух ножках; экран обращён в комнату (+X) ---")
box("tv_frame", (5, 104, 66), (-132, 25, 75), "#171d22", 1.6)
box("tv_screen", (0.8, 96, 58), (-129.1, 25, 75), "#17394b", 0.65)
add("color tv_screen #17394b metal=0.25 rough=0.08")
for i, y in enumerate((0, 50)):
    box(f"tv_stand_{i}", (4, 8, 9), (-132, y, 37.5), "#20272c", 0.7)
box("tv_status", (0.5, 5, 0.8), (-128.6, 25, 44.5), "#80c9b0", 0.2)
add()
add("# --- Диван: основание, три посадочных места, подушки, плед ---")
box("sofa_base", (170, 48, 16), (20, 94, 14), "#657d78", 3.0)
box("sofa_back", (170, 10, 42), (20, 113, 43), "#5c7570", 3.5)
for i, x in enumerate((-30, 20, 70)):
    box(f"sofa_seat_{i}", (48, 38, 10), (x, 85, 27), "#78928a", 3.2)
    box(f"sofa_back_cushion_{i}", (48, 8, 30), (x, 105.5, 45), "#708a82", 3.0)
for i, x in enumerate((-65, 105)):
    box(f"sofa_arm_{i}", (10, 52, 32), (x, 92, 32), "#607973", 3.2)
for i, (x, y) in enumerate(((-55, 78), (95, 78), (-55, 108), (95, 108))):
    box(f"sofa_leg_{i}", (4, 4, 6), (x, y, 3), "#3c3430", 0.6)
box("sofa_pillow_mustard", (22, 10, 24), (-45, 98, 47), "#d2a84f", 3.4)
box("sofa_pillow_rust", (22, 10, 24), (75, 98, 47), "#b96f55", 3.4)
box("sofa_throw_top", (16, 44, 2), (105, 90, 49), "#e4d4b7", 0.7)
box("sofa_throw_drop", (2, 44, 28), (111, 90, 35), "#e4d4b7", 0.7)
for i in range(6):
    cylinder(f"sofa_throw_fringe_{i}", 0.55, 4, (111, 72 + i * 7, 17), "#e4d4b7", 16)
add()
add("# --- Ковёр и овальный журнальный стол ---")
box("rug_base", (180, 115, 1), (5, 15, 0.5), "#a95f4b", 0.3)
box("rug_inner", (170, 105, 0.25), (5, 15, 1.125), "#c77d61", 0.08)
add("coffee_top = oval width=82 length=54 thickness=4 round=1 at=[5,10,23] color=#7b523a")
add("coffee_shelf = oval width=64 length=40 thickness=2 round=0.5 at=[5,10,8] color=#624432")
for i, (x, y) in enumerate(((-20, -5), (30, -5), (-20, 25), (30, 25))):
    cylinder(f"coffee_leg_{i}", 2, 21.75, (x, y, 1.25), "#3b3430", 32)
add()
add("# --- Пульт именно лежит на столешнице: низ корпуса z=27 ---")
box("remote_body", (8, 24, 2.2), (0, 0, 1.1), "#20262b", 0.8)
for i, (x, y, r) in enumerate(((0, 8, 1.0), (-2, 4, 0.8), (2, 4, 0.8),
                                (-2, 0, 0.8), (2, 0, 0.8), (-2, -4, 0.8),
                                (2, -4, 0.8), (0, -8, 1.4))):
    cylinder(f"remote_button_{i}", r, 0.45, (x, y, 2.2),
             "#b95648" if i == 0 else "#8b969d", 24)
for name in ["remote_body"] + [f"remote_button_{i}" for i in range(8)]:
    add(f"{name} = rotate [{name}] angle=-12 axis=z")
    add(f"{name} = translate [{name}] offset=[8,5,27]")
add()
add("# --- Чашка с полостью, кофе и ручкой ---")
add("cup_body = lathe points=[[0,0],[4,0],[4.5,1],[4.5,7],[3.5,7],[3.5,1.5],[0,1.5],[0,0]] "
    "segments=48 fillet=0.25 color=#e6ded0")
add("cup_body = translate [cup_body] offset=[-15,12,27]")
cylinder("cup_coffee", 3.4, 0.3, (-15, 12, 32.7), "#4b2d21", 48)
add("cup_handle = torus major=3 minor=0.7 segments=48")
add("cup_handle = rotate [cup_handle] angle=90 axis=x")
add("cup_handle = translate [cup_handle] offset=[-20,12,30.5]")
add("color cup_handle #e6ded0")
add()
add("# --- Пуф и придиванный столик с книгой ---")
cylinder("pouf_body", 22, 18, (80, -65, 0), "#d0a34f", 64)
add("pouf_top = oval diameter=44 thickness=5 top=выпуклая sag=1.5 at=[80,-65,17] color=#ddb45f")
cylinder("side_top", 18, 3, (-92, 85, 25), "#7b523a", 64)
for i, angle in enumerate((0, 120, 240)):
    x = -92 + 12 * math.cos(math.radians(angle))
    y = 85 + 12 * math.sin(math.radians(angle))
    cylinder(f"side_leg_{i}", 1.5, 25, (round(x, 3), round(y, 3), 0), "#3b3430", 32)
box("side_book_pages", (18, 12, 1.6), (-92, 85, 28.8), "#e8dfc9", 0.25)
box("side_book_cover", (18.5, 12.5, 0.4), (-92, 85, 29.8), "#3f6d72", 0.15)
add()
add("# --- Книжный шкаф: четыре яруса, корзина и отдельные книги ---")
for name, x in [("bookcase_side_l", 121.5), ("bookcase_side_r", 153.5)]:
    box(name, (3, 20, 100), (x, 108, 50), "#72513d", 0.55)
box("bookcase_back", (35, 2, 100), (137.5, 117, 50), "#624534", 0.35)
for name, z in [("bookcase_bottom", 1.5), ("bookcase_top", 98.5)]:
    box(name, (35, 20, 3), (137.5, 108, z), "#72513d", 0.55)
for i, z in enumerate((25, 50, 75)):
    box(f"bookcase_shelf_{i}", (32, 18, 2), (137.5, 107, z), "#806047", 0.4)
box("bookcase_basket", (25, 14, 16), (137.5, 106, 11), "#b58a59", 1.4)
box("bookcase_basket_cut", (8, 3, 3), (137.5, 98.5, 15), "#ffffff", 0.8)
add("bookcase_basket = difference [bookcase_basket,bookcase_basket_cut]")
book_colors = ["#416b70", "#b96b52", "#d0a34f", "#6e7f61", "#dfd2b4", "#47546a"]
for row, bottom in enumerate((26, 51, 76)):
    x = 124.0
    for col in range(6):
        w = (3.6, 4.2, 3.4, 4.6, 3.8, 4.0)[col]
        h = (19, 17, 20, 18, 19, 16)[(col + row) % 6]
        box(f"book_{row}_{col}", (w, 12, h), (x + w / 2, 106, bottom + h / 2),
            book_colors[(col + 2 * row) % len(book_colors)], 0.25)
        box(f"book_band_{row}_{col}", (w * 0.65, 0.35, 0.7),
            (x + w / 2, 99.85, bottom + h - 3), "#d6bc7d", 0.1)
        x += w + 0.75
add()
add("# --- Торшер с полым абажуром и тёплой лампой ---")
cylinder("lamp_base", 12, 2, (125, 55, 0), "#3a4242", 64)
cylinder("lamp_stem", 1.3, 92, (125, 55, 2), "#b69a62", 32)
add("lamp_shade = lathe points=[[17,0],[11,18],[9.5,18],[15.5,0],[17,0]] "
    "segments=64 color=#eadcbe")
add("lamp_shade = translate [lamp_shade] offset=[125,55,90]")
add("lamp_bulb = sphere radius=4 segments=32 at=[125,55,99] color=#ffd58a")
add("color lamp_bulb #ffd58a emissive=#ffd58a emissive_strength=3")
add()
add("# --- Растение: полый горшок, грунт, стебель и объёмные листья ---")
add("plant_pot = lathe points=[[0,0],[11,0],[12,2],[16,21],[16,23],[13.5,23],[12.5,20],[9.5,4],[0,4],[0,0]] "
    "segments=64 fillet=0.35 color=#b96f50")
add("plant_pot = translate [plant_pot] offset=[-130,102,0]")
cylinder("plant_soil", 12.5, 1.5, (-130, 102, 19), "#4b3829", 48)
cylinder("plant_stem", 1.2, 43, (-130, 102, 20), "#55704b", 24)
leaf_specs = [
    (0, 39, 30, 16, -18), (55, 45, 28, 15, 22), (115, 50, 30, 17, -20),
    (175, 55, 27, 15, 18), (230, 59, 25, 14, -16), (295, 63, 23, 13, 20),
    (35, 67, 20, 12, -12),
]
for i, (angle, z, length, width, tilt) in enumerate(leaf_specs):
    name = f"plant_leaf_{i}"
    add(f"{name} = leaf length={length} width={width} thickness=1 curl=0.18 "
        f"plane=плашмя segments=36 color=#4f7b55")
    add(f"{name} = rotate [{name}] angle={tilt} axis=y")
    add(f"{name} = rotate [{name}] angle={angle} axis=z")
    add(f"{name} = translate [{name}] offset=[-130,102,{z}]")
add()
add("# --- Настенные часы над книжным шкафом ---")
add("clock_body = cylinder radius=12 height=3 segments=64 center=да")
add("clock_body = rotate [clock_body] angle=90 axis=x")
add("clock_body = translate [clock_body] offset=[137,118,120]")
add("color clock_body #b89459")
add("clock_face = cylinder radius=10 height=0.5 segments=64 center=да")
add("clock_face = rotate [clock_face] angle=90 axis=x")
add("clock_face = translate [clock_face] offset=[137,116.2,120]")
add("color clock_face #eee6d4")
box("clock_hand_hour", (1, 0.7, 6), (137, 115.6, 122.5), "#344044", 0.3)
box("clock_hand_minute", (7, 0.7, 1), (140, 115.5, 120), "#344044", 0.3)
for i, (x, z) in enumerate(((137, 128), (137, 112), (129, 120), (145, 120))):
    add(f"clock_mark_{i} = sphere radius=0.8 segments=16 at=[{x},115.4,{z}] color=#7d684b")
add()
add("# Проверки ключевых тел выполняются также внешним сценарием сборки.")
add("check walls watertight")
add("check door_slab watertight")
add("check media_body watertight")
add("check remote_body watertight")


def make_script() -> str:
    return "\n".join(lines) + "\n"


def bbox(solid):
    return np.asarray(solid.manifold.bounding_box(), dtype=float)


def aabb_overlap(a, b, eps=1e-5) -> bool:
    return bool(np.all(np.minimum(a[3:], b[3:]) - np.maximum(a[:3], b[:3]) > eps))


def assembly_of(name: str) -> str | None:
    prefixes = [
        ("sofa_", "sofa"), ("media_", "media"), ("tv_", "media"),
        ("soundbar", "media"), ("coffee_", "coffee"), ("remote_", "coffee"),
        ("cup_", "coffee"), ("rug_", "rug"), ("bookcase_", "bookcase"),
        ("book_", "bookcase"), ("plant_", "plant"), ("lamp_", "lamp"),
        ("pouf_", "pouf"), ("side_", "side"), ("door_", "door"),
        ("window_", "window"), ("curtain_", "window"), ("clock_", "clock"),
        ("walls", "walls"), ("baseboard_", "walls"),
    ]
    for prefix, group in prefixes:
        if name.startswith(prefix):
            return group
    return None


def validate(result):
    solids = result.visible_solids()
    problems = []
    triangles = 0
    for solid in solids:
        status = str(solid.manifold.status())
        volume = float(solid.manifold.volume())
        bounds = bbox(solid)
        if status not in ("NoError", "Error.NoError") or solid.manifold.is_empty() or volume <= 1e-7:
            problems.append(f"{solid.name}: status={status}, volume={volume}")
        if not np.all(np.isfinite(bounds)):
            problems.append(f"{solid.name}: нечисловой bounding box")
        triangles += len(manifold_mesh(solid.manifold)[1])

    objects = {s.name: s for s in solids}
    # Проёмы проверяются объёмными зондами, а не только успешным boolean.
    walls = objects["walls"].manifold
    door_probe = mf.Manifold.cube((20, 30, 80), True).translate((-163, -72, 58))
    window_probe = mf.Manifold.cube((60, 20, 30), True).translate((20, 123, 98))
    door_void = abs(float((walls ^ door_probe).volume()))
    window_void = abs(float((walls ^ window_probe).volume()))
    if door_void > 1e-4:
        problems.append(f"Дверной проём не сквозной: {door_void}")
    if window_void > 1e-4:
        problems.append(f"Оконный проём не сквозной: {window_void}")

    # Пульт и чашка должны опираться на плоскую столешницу z=27, не висеть и не тонуть.
    remote_bottom = float(bbox(objects["remote_body"])[2])
    cup_bottom = float(bbox(objects["cup_body"])[2])
    if abs(remote_bottom - 27.0) > 1e-4:
        problems.append(f"Пульт не на столешнице: z={remote_bottom}")
    if abs(cup_bottom - 27.0) > 1e-4:
        problems.append(f"Чашка не на столешнице: z={cup_bottom}")

    groups: dict[str, list] = {}
    for solid in solids:
        group = assembly_of(solid.name)
        if group:
            groups.setdefault(group, []).append(solid)
    allowed = {
        frozenset(("door", "walls")), frozenset(("window", "walls")),
        frozenset(("clock", "walls")),
    }
    collisions = []
    for ga, gb in combinations(sorted(groups), 2):
        if frozenset((ga, gb)) in allowed:
            continue
        for a in groups[ga]:
            ba = bbox(a)
            for b in groups[gb]:
                if not aabb_overlap(ba, bbox(b)):
                    continue
                volume = abs(float((a.manifold ^ b.manifold).volume()))
                if volume > 0.01:
                    collisions.append({"a": a.name, "b": b.name, "volume_mm3": round(volume, 5)})
    if collisions:
        problems.append(f"Нежелательные пересечения узлов: {len(collisions)}")

    report = {
        "scene": str(SCENE_PATH),
        "objects": len(solids),
        "triangles": triangles,
        "all_bodies_valid": not any("status=" in p for p in problems),
        "door_opening_residual_mm3": door_void,
        "window_opening_residual_mm3": window_void,
        "remote_bottom_z": remote_bottom,
        "cup_bottom_z": cup_bottom,
        "unexpected_collisions": collisions,
        "problems": problems,
    }
    if problems:
        raise RuntimeError(json.dumps(report, ensure_ascii=False, indent=2))
    return report, solids


def render(solids, groups, view: str, path: Path, size: int = 1000) -> None:
    meshes = _prepare(solids, groups)
    vertices = np.concatenate([m["verts"] for m in meshes])
    lo, hi = vertices.min(0), vertices.max(0)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo)) / 2.0 * 1.06
    image, _ = _render_view(meshes, center, radius, view, size, 2,
                            [*lo, *hi], grid=False, shadow=True,
                            bg=BG, style=None)
    Image.fromarray((np.clip(image, 0, 1) * 255).astype(np.uint8), "RGB").save(path)


def contact_sheet(paths: list[tuple[str, Path]], output: Path) -> None:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font = ImageFont.truetype(font_path, 24)
    title_font = ImageFont.truetype(bold_path, 34)
    tile = 760
    header = 95
    label = 52
    canvas = Image.new("RGB", (tile * 2 + 60, header + (tile + label) * 2 + 60), (19, 25, 32))
    draw = ImageDraw.Draw(canvas)
    draw.text((30, 24), "Гостиная 1:20 — контрольные виды", font=title_font, fill=(238, 240, 233))
    for i, (label_text, path) in enumerate(paths):
        image = Image.open(path).convert("RGB").resize((tile, tile), Image.Resampling.LANCZOS)
        x = 20 + (i % 2) * (tile + 20)
        y = header + (i // 2) * (tile + label + 20)
        canvas.paste(image, (x, y))
        draw.text((x + 8, y + tile + 10), label_text, font=font, fill=(215, 222, 224))
    canvas.save(output, optimize=True)


def main() -> None:
    script = make_script()
    SCENE_PATH.write_text(script, encoding="utf-8")
    result = build(script, analyze_model=False)
    if not result.ok:
        raise SystemExit(str(result.error))
    report, solids = validate(result)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    glb_path = EXPORT_DIR / "living_room_diorama.glb"
    glb_path.write_bytes(result.glb())

    views = [("iso", "Общая изометрия"), ("top", "Сверху"),
             ("front", "Спереди"), ("right", "Справа")]
    rendered = []
    for view, label in views:
        path = RENDER_DIR / f"living_room_{view}.png"
        render(solids, result.scene.groups, view, path, 1000)
        rendered.append((label, path))
    detail_solids = [s for s in solids if s.name.startswith(("coffee_", "remote_", "cup_"))]
    detail_path = RENDER_DIR / "living_room_table_detail.png"
    render(detail_solids, result.scene.groups, "iso", detail_path, 900)
    contact_sheet(rendered, RENDER_DIR / "living_room_views.png")
    report.update({
        "glb": str(glb_path), "glb_bytes": glb_path.stat().st_size,
        "renders": [str(p) for _, p in rendered] + [str(detail_path)],
    })
    (RENDER_DIR / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
