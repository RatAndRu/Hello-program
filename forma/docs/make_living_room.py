"""Пересобранная гостиная 1:20: параметрическая сцена Forma 0.52.

Запуск из корня репозитория:
    PYTHONPATH=forma python forma/docs/make_living_room.py

Создаёт examples/living_room_diorama.forma, GLB, общие и детальные виды,
контрольный лист и JSON с геометрическими проверками. Внешние модели, сетки,
текстуры и координатные шаблоны не используются.
"""
from __future__ import annotations

import fnmatch
import json
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
    add(f"{name} = cylinder radius={radius:g} height={height:g} segments={segments} "
        f"at={list(at)} color={color}")


add("# ГОСТИНАЯ 1:20 — пересобранная параметрическая диорамма Forma 0.52")
add("# Канон: +Z вверх, +X вправо, -Y вперёд. Все размеры в мм.")
add("# Панели не заходят друг в друга; новые узлы остаются отдельными и редактируемыми.")
add()
add("# --- Основание, смешанный текст на табличке и отдельные планки пола ---")
box("display_base", (350, 270, 8), (0, 0, -12.8), "#26333a", 1.8)
box("floor_substrate", (340, 260, 8), (0, 0, -4.8), "#5c3d2d", 0.8)
box("name_plate", (110, 1.2, 6.5), (0, -135.6, -12.8), "#c7a968", 0.35)
add('name_text = text "Гостиная 1:20" size=3.2 depth=0.3 align=center '
    'plane=xz at=[0,-136.35,-13.2] color=#26333a')
add('name_subtext = text "FORMA 3D" size=1.8 depth=0.3 align=center '
    'plane=xz at=[0,-136.35,-15.5] color=#26333a')
box("floor_a", (26.3, 240, 0.8), (-146.85, 0, -0.4), "#ad7b50")
box("floor_b", (26.3, 240, 0.8), (-146.85, 0, -0.4), "#bd8b60")
add("floorboards = array [floor_a,floor_b] mode=linear count=12 "
    "offset=[26.7,0,0] sequence=loop as=objects")
add()
add("# --- Стены: стыки без наложения объёмов, настоящие сквозные проёмы ---")
box("wall_back", (332, 6, 140.8), (0, 123, 70), "#e7dfcf", 0.4)
box("window_cut", (184, 12, 58), (20, 123, 98), "#ffffff")
add("wall_back = difference [wall_back,window_cut]")
box("wall_left", (6, 240, 140.8), (-163, 0, 70), "#e7dfcf", 0.4)
box("door_cut", (12, 79, 119), (-163, -72, 58.7), "#ffffff")
add("wall_left = difference [wall_left,door_cut]")
box("wall_front_cutaway", (320, 6, 10.8), (0, -123, 4.6), "#e7dfcf", 0.4)
box("wall_right_cutaway", (6, 240, 14.8), (163, 0, 6.6), "#e7dfcf", 0.4)
box("baseboard_back", (318, 2, 7), (1, 119, 3.5), "#f5f0e6", 0.2)
box("baseboard_left_front", (2, 9, 7), (-159, -115.5, 3.5), "#f5f0e6", 0.2)
box("baseboard_left_rear", (2, 151, 7), (-159, 42.5, 3.5), "#f5f0e6", 0.2)
add()
add("# --- Окно: распределённые без внутренних наложений рама, переплёт и стёкла ---")
box("window_jamb_l", (4, 5, 58), (-70, 122.5, 98), "#f6f3e9", 0.25)
box("window_jamb_r", (4, 5, 58), (110, 122.5, 98), "#f6f3e9", 0.25)
box("window_rail_bottom", (176, 5, 4), (20, 122.5, 71), "#f6f3e9", 0.25)
box("window_rail_top", (176, 5, 4), (20, 122.5, 125), "#f6f3e9", 0.25)
box("window_mullion_low", (3, 5, 23.5), (20, 122.5, 84.75), "#f6f3e9", 0.2)
box("window_mullion_high", (3, 5, 23.5), (20, 122.5, 111.25), "#f6f3e9", 0.2)
box("window_crossbar", (176, 5, 3), (20, 122.5, 98), "#f6f3e9", 0.2)
for name, x, width in (("left", -24.75, 85.5), ("right", 65.0, 85.0)):
    for row, z, height in (("low", 84.75, 22.5), ("high", 111.25, 22.5)):
        part = f"window_glass_{name}_{row}"
        box(part, (width, 1, height), (x, 123.5, z), "#b9e2e8", 0.1)
        add(f"color {part} #b9e2e8 material=glass transmission=0.55 rough=0.08")
box("window_handle", (2, 3, 9), (23, 118.5, 96), "#c8b078", 0.5)
box("window_sill", (190, 14, 4), (20, 113, 67), "#f6f3e9", 0.7)
box("window_trim_l", (5, 3, 60), (-75, 118.5, 99), "#f8f4eb", 0.3)
box("window_trim_r", (5, 3, 60), (115, 118.5, 99), "#f8f4eb", 0.3)
box("window_trim_top", (185, 3, 3), (20, 118.5, 130.5), "#f8f4eb", 0.25)
add()
add("# --- Две объёмные шторы 0.52; карниз и кольца — отдельные копии ---")
add("curtain_left = curtain width=28 height=63 folds=4 fold_depth=2.2 thickness=0.12 "
    "wave=0.45 billow=0.5 detail=8 rows=24 rod=нет rings=нет "
    "at=[-66,104,69] color=#c98568")
add("curtain_right = curtain width=28 height=63 folds=4 fold_depth=2.2 thickness=0.12 "
    "wave=0.45 billow=0.5 detail=8 rows=24 rod=нет rings=нет "
    "at=[102,104,69] color=#c98568")
add("curtain_rod = cylinder radius=1.2 height=216 segments=40 center=да")
add("rotate [curtain_rod] angle=90 axis=y")
add("translate [curtain_rod] offset=[20,104,135]")
add("color curtain_rod #b89b62 metal=0.65 rough=0.28")
add("curtain_ring_proto = torus major=2.4 minor=0.22 segments=40")
add("rotate [curtain_ring_proto] angle=90 axis=y")
add("translate [curtain_ring_proto] offset=[-78,104,135]")
add("curtain_rings = array [curtain_ring_proto] mode=linear count=12 "
    "offset=[18,0,0] as=objects")
for index, x in enumerate((-90.6, 130.6)):
    add(f"curtain_finial_{index} = sphere radius=2.6 segments=32 "
        f"at=[{x},104,135] color=#b89b62")
add()
add("# --- Дверь 0.52: коробка, филёнки, петли, ручка и замок раздельны ---")
add("entry = door width=70 height=114 thickness=3.5 frame=4 frame_depth=8 gap=0.5 "
    "panels=2 columns=1 panel_margin=7 panel_depth=0.35 hinges=3 lock=да "
    "handle_height=57 handle_offset=9 handle_length=8 handle_radius=0.7 backset=3")
add("rotate [entry] angle=90 axis=z")
add("translate [entry] offset=[-162,-72,0]")
add("rotate [entry.leaf] angle=-35 axis=z pivot=[-160.25,-106,0]")
add()
add("# --- Настенные электрика 0.52 и рама с настоящим смешанным текстом ---")
add("wall_switch = switch rockers=1 width=50 height=50 depth=10 state=on angle=7 led=да screws=да")
add("scale [wall_switch] factor=0.2")
add("rotate [wall_switch] angle=90 axis=z")
add("translate [wall_switch] offset=[-159,-24,48]")
add("wall_socket = socket sockets=1 width=50 height=50 depth=10 insert_radius=20 "
    "holes=2 pin_pitch=10 ground=да screws=да")
add("scale [wall_socket] factor=0.2")
add("translate [wall_socket] offset=[-105,119,24]")
box("art_back", (0.8, 70, 30), (-159.6, 20, 116), "#29434a", 0.15)
box("art_side_0", (1, 2, 32), (-159.1, -16, 116), "#c7a968", 0.15)
box("art_side_1", (1, 2, 32), (-159.1, 56, 116), "#c7a968", 0.15)
box("art_rail_0", (1, 68, 2), (-159.1, 20, 100), "#c7a968", 0.15)
box("art_rail_1", (1, 68, 2), (-159.1, 20, 132), "#c7a968", 0.15)
add('art_text = text "Forma & 3D" size=5 depth=0.2 plane=yz '
    'at=[-159.1,20,113] color=#eadfbe')
add('art_subtext = text "living / 02" size=2.8 depth=0.2 plane=yz '
    'at=[-159.1,20,106] color=#eadfbe')
add()
add("# --- ТВ-тумба: видимые панели и ниша, без скрытого массивного корпуса ---")
box("media_back", (3, 100, 23), (-153.5, 20, 17.5), "#6f4c38", 0.5)
box("media_top", (28, 100, 3), (-141, 20, 30.5), "#7c573f", 0.5)
box("media_bottom", (25, 94, 3), (-139.5, 20, 7.5), "#6f4c38", 0.45)
box("media_side_0", (25, 3, 20), (-139.5, -28.5, 19), "#6f4c38", 0.45)
box("media_side_1", (25, 3, 20), (-139.5, 68.5, 19), "#6f4c38", 0.45)
box("media_stile_0", (4, 2, 20), (-129, -3, 19), "#6f4c38", 0.35)
box("media_stile_1", (4, 2, 20), (-129, 43, 19), "#6f4c38", 0.35)
box("media_drawer_0", (1.5, 22, 16), (-127.75, -15, 19), "#8a6248", 0.45)
box("media_drawer_1", (1.5, 22, 16), (-127.75, 55, 19), "#8a6248", 0.45)
box("media_handle_0", (1.5, 10, 1.2), (-126.2, -15, 19), "#c9aa6d", 0.45)
box("media_handle_1", (1.5, 10, 1.2), (-126.2, 55, 19), "#c9aa6d", 0.45)
for index, y in enumerate((-23, 63)):
    box(f"media_leg_{index}", (4, 4, 6), (-148, y, 3), "#3d3430", 0.5)
    box(f"media_leg_{index + 2}", (4, 4, 6), (-133, y, 3), "#3d3430", 0.5)
box("media_receiver", (8, 28, 8), (-140, 20, 13), "#252a2d", 0.45)
add("media_receiver_led = sphere radius=0.65 segments=20 at=[-135.35,10,13] color=#78d9b4")
add("color media_receiver_led #78d9b4 emissive=#78d9b4 emissive_strength=2")
box("soundbar", (4, 60, 4), (-136, 20, 34), "#252a2e", 1.2)
box("soundbar_slot_proto", (0.4, 1.5, 1.8), (-133.8, -2, 34), "#0e1519", 0.15)
add("soundbar_slots = array [soundbar_slot_proto] mode=linear count=12 "
    "offset=[0,4,0] as=objects")
add()
add("# --- Телевизор: экран и текст обращены в комнату (+X) ---")
box("tv_frame", (4, 96, 58), (-140, 20, 66), "#171d22", 1.2)
box("tv_screen", (0.6, 88, 50), (-137.7, 20, 66), "#17394b", 0.25)
add("color tv_screen #17394b metal=0.25 rough=0.08")
for index, y in enumerate((-10, 50)):
    box(f"tv_stand_{index}", (4, 7, 5), (-140, y, 34.5), "#20272c", 0.5)
box("tv_status", (0.3, 4, 0.6), (-137.25, 20, 40), "#80c9b0", 0.12)
add('tv_text = text "FORMA" size=7 depth=0.2 plane=yz '
    'at=[-137.3,20,63] color=#8fc6c8')
add()
add("# --- Диван: панели и подушки разделены зазорами, складка пледа рассчитывается ---")
box("sofa_base", (170, 43.85, 12), (0, 85.925, 12), "#657d78", 2.5)
box("sofa_back", (170, 10, 58), (0, 113, 35), "#5c7570", 2.5)
for index, x in enumerate((-50, 0, 50)):
    box(f"sofa_seat_{index}", (46, 35.85, 10), (x, 82.075, 23), "#78928a", 2.8)
    box(f"sofa_back_cushion_{index}", (46, 8, 30), (x, 104, 43), "#708a82", 2.4)
box("sofa_arm_0", (10, 43.85, 32), (-80, 85.925, 34), "#607973", 2.8)
box("sofa_arm_1", (10, 43.85, 32), (80, 85.925, 34), "#607973", 2.8)
for index, (x, y) in enumerate(((-72, 73), (72, 73), (-72, 102), (72, 102))):
    box(f"sofa_leg_{index}", (4, 4, 6), (x, y, 3), "#3c3430", 0.5)
box("sofa_pillow_mustard", (22, 8, 22), (-58, 96, 39), "#d2a84f", 3.2)
box("sofa_pillow_rust", (22, 8, 22), (58, 96, 39), "#b96f55", 3.2)
add("throw_sheet = box size=[34,24,0.3] at=[0,82,30] color=#e4d4b7")
add("throw = drape [throw_sheet] on=sofa_seat_1 detail=24 "
    "iterations=70 constraints=10 stiffness=0.9 bend=0.12 damping=0.86 "
    "gravity=0.2 pin=back gap=0.3 thickness=0.15")
add()
add("# --- Ковёр 0.52 и овальный стол с пользовательскими прототипами ---")
add("living_rug = rug width=180 length=110 shape=rounded corner=10 thickness=1.2 "
    "pad=0.25 border=7 pattern=полосы pattern_size=2.5 pattern_step=12 "
    "wave=0.12 lift=2.5 lift_corner=front_right binding=0.25 stitches=да "
    "fringe=ends fringe_length=6 fringe_count=20 detail=64 rings=8 "
    "at=[0,-5,1.49] color=#a95f4b border_color=#dfc39f")
add("coffee_top_proto = oval width=82 length=54 thickness=4 round=1 color=#7b523a")
add("coffee_leg_proto = lathe points=[[0,0],[2.2,0],[2.2,0.8],[1.5,20],[1.8,22],[0,22]] "
    "segments=40 color=#3b3430")
add("coffee = table [coffee_top_proto] leg_object=coffee_leg_proto height=28 "
    "shape=ellipse legs=3 layout=circle inset=10 splay=0 at=[5,-5,1.6]")
add()
add("# --- Пульт перемещается группой; чашка имеет полость и sweep-ручку ---")
box("remote_body", (8, 24, 2.2), (0, 0, 1.1), "#20262b", 0.8)
for index, (x, y, radius) in enumerate(((0, 8, 1.0), (-2, 4, 0.8), (2, 4, 0.8),
                                       (-2, 0, 0.8), (2, 0, 0.8), (-2, -4, 0.8),
                                       (2, -4, 0.8), (0, -8, 1.4))):
    cylinder(f"remote_button_{index}", radius, 0.45, (x, y, 2.2),
             "#b95648" if index == 0 else "#8b969d", 24)
add("remote = group [remote_body," + ",".join(f"remote_button_{i}" for i in range(8)) + "]")
add("rotate [remote] angle=-12")
add("translate [remote] offset=[18,-8,29.6]")
add("cup_body = lathe points=[[0,0],[4,0],[4.5,1],[4.5,7],[3.5,7],[3.5,1.5],[0,1.5]] "
    "segments=48 fillet=0.2 color=#e6ded0")
add("cup_handle = sweep path=[[-4,0,5],[-7,0,5.5],[-8,0,3],[-7,0,1],[-4,0,1.5]] "
    "radius=0.65 smooth=8 color=#e6ded0")
cylinder("cup_coffee", 3.4, 0.25, (0, 0, 6.4), "#4b2d21", 48)
add("cup = group [cup_body,cup_handle,cup_coffee]")
add("translate [cup] offset=[-10,3,29.6]")
add()
add("# --- Пуф и трёхногий придиванный столик с книгой ---")
cylinder("pouf_body", 20, 17, (125, -65, 0), "#d0a34f", 64)
add("pouf_top = oval diameter=40 thickness=4 top=выпуклая sag=1.2 "
    "at=[125,-65,17] color=#ddb45f")
add("side_table = table width=32 length=32 height=26 thickness=3 shape=ellipse "
    "legs=3 layout=circle inset=6 leg_shape=round leg_radius=1.3 at=[-108,72,0]")
box("side_book_bottom", (16.4, 11.4, 0.25), (-108, 72, 26.125), "#3f6d72", 0.1)
box("side_book_pages", (16, 11, 1.4), (-108, 72, 26.95), "#e8dfc9", 0.2)
box("side_book_top", (16.4, 11.4, 0.25), (-108, 72, 27.775), "#3f6d72", 0.1)
add()
add("# --- Шкаф: каждая панель занимает собственный объём, без скрытых нахлёстов ---")
box("bookcase_side_l", (2, 22, 108), (125, 107, 54), "#72513d", 0.35)
box("bookcase_side_r", (2, 22, 108), (155, 107, 54), "#72513d", 0.35)
box("bookcase_back", (28, 2, 103.2), (140, 117, 54), "#624534", 0.25)
box("bookcase_bottom", (28, 18, 2.4), (140, 106, 1.2), "#72513d", 0.3)
box("bookcase_top", (28, 18, 2.4), (140, 106, 106.8), "#72513d", 0.3)
for index, z in enumerate((26, 55, 82)):
    box(f"bookcase_shelf_{index}", (27.84, 17.84, 1.8), (140, 106, z), "#806047", 0.25)
box("bookcase_basket", (22, 14, 17), (140, 105.8, 10.9), "#b58a59", 1.2)
box("basket_inner_cut", (19, 11, 17), (140, 105.8, 12.5), "#ffffff", 0.8)
add("bookcase_basket = difference [bookcase_basket,basket_inner_cut]")
box("basket_handle_cut", (8, 4, 3), (140, 99.5, 16), "#ffffff", 0.7)
add("bookcase_basket = difference [bookcase_basket,basket_handle_cut]")
box("book_a", (4, 12, 18), (0, 0, 9), "#416b70")
box("book_b", (5, 12, 20), (0, 0, 10), "#b96b52")
box("book_c", (3.5, 12, 16), (0, 0, 8), "#d0a34f")
for row in range(3):
    add(f"books_{row} = array [book_a,book_b,book_c] mode=pack on=bookcase_shelf_{row} "
        "count=5 gap=0.5 inset=1.2 sequence=loop justify=center align=bottom as=objects")
add()
add("# --- Ваза и тор наверху шкафа ---")
add("decor_vase = lathe points=[[0,0],[4,0],[5,2],[4,8],[2.5,12],[2.5,14],"
    "[1.7,14],[1.7,12],[3.2,8],[3.8,2],[0,1.2]] segments=48 color=#557a78")
add("translate [decor_vase] offset=[132,106,108]")
box("decor_base", (10, 6, 1), (148, 106, 108.5), "#c7a968", 0.25)
add("decor_torus = torus major=4 minor=0.8 segments=48")
add("rotate [decor_torus] angle=90 axis=x")
add("translate [decor_torus] offset=[148,106,113.8]")
add("color decor_torus #c7a968 metal=0.45 rough=0.3")
add()
add("# --- Дуговой торшер, полый абажур и перевернутая лампочка E14 0.52 ---")
cylinder("lamp_base", 11, 2, (116, 46, 0), "#3a4242", 64)
add("lamp_arc = sweep path=[[116,46,2.2],[116,46,45],[112,46,82],[106,46,112],"
    "[96,46,112],[96,46,110]] radius=1.2 smooth=8 color=#b69a62")
cylinder("lamp_mount", 1.2, 6, (96, 46, 104), "#b69a62", 32)
cylinder("lamp_socket", 3, 4, (96, 46, 100), "#4a4540", 40)
add("lamp_shade = lathe points=[[13,0],[9,18],[7.8,18],[11.5,0],[13,0]] "
    "segments=64 color=#eadcbe")
add("translate [lamp_shade] offset=[96,46,90]")
add("lamp_spider = torus major=8 minor=0.3 segments=48")
add("translate [lamp_spider] offset=[96,46,106]")
add("color lamp_spider #b69a62 metal=0.55 rough=0.3")
box("lamp_spoke_proto", (8, 0.6, 0.6), (4, 0, 106), "#b69a62", 0.2)
add("lamp_spokes = array [lamp_spoke_proto] mode=radial count=3 radius=0 "
    "angle=360 spin=да as=objects at=[96,46,0]")
add("lamp_bulb = bulb shape=candle base=E14 diameter=18 height=32 glass_wall=0.3 "
    "thread=да glow=да glow_color=#ffd7a0 glow_strength=3 segments=48")
add("scale [lamp_bulb] factor=0.5")
add("rotate [lamp_bulb] angle=180 axis=x")
add("translate [lamp_bulb] offset=[96,46,102]")
add()
add("# --- Растение: полый горшок, видимый грунт и объёмные листья ---")
add("plant_pot = lathe points=[[0,0],[10,0],[11,2],[14,21],[14,23],[12,23],"
    "[11.5,20],[8.5,4],[0,4]] segments=64 fillet=0.25 color=#b96f50")
add("translate [plant_pot] offset=[-130,95,0]")
cylinder("plant_soil", 10.8, 0.8, (-130, 95, 20), "#4b3829", 48)
cylinder("plant_stem", 1.0, 55, (-130, 95, 20.8), "#55704b", 24)
leaf_specs = [
    (0, 30, 26, 13, -10), (55, 37, 25, 12, 10), (115, 44, 26, 13, -10),
    (175, 51, 24, 12, 10), (230, 58, 22, 11, -10), (295, 65, 20, 10, 10),
    (35, 72, 18, 9, -8),
]
for index, (angle, z, length, width, tilt) in enumerate(leaf_specs):
    name = f"plant_leaf_{index}"
    add(f"{name} = leaf length={length} width={width} thickness=0.8 curl=0.18 "
        f"plane=плашмя segments=36 color=#4f7b55")
    add(f"rotate [{name}] angle={tilt} axis=y")
    add(f"rotate [{name}] angle={angle} axis=z")
    add(f"translate [{name}] offset=[-130,95,{z}]")
add()
add("# --- Часы на свободном участке задней стены ---")
add("clock_body = cylinder radius=10 height=3 segments=64 center=да")
add("rotate [clock_body] angle=90 axis=x")
add("translate [clock_body] offset=[140,118.5,124]")
add("color clock_body #b89459")
add("clock_face = cylinder radius=8.7 height=0.5 segments=64 center=да")
add("rotate [clock_face] angle=90 axis=x")
add("translate [clock_face] offset=[140,116.75,124]")
add("color clock_face #eee6d4")
box("clock_hand_hour", (0.8, 0.4, 5), (140, 116.3, 126.5), "#344044", 0.18)
box("clock_hand_minute", (6, 0.4, 0.8), (143, 116.3, 124), "#344044", 0.18)
for index, (x, z) in enumerate(((140, 131.5), (140, 116.5), (132.5, 124), (147.5, 124))):
    add(f"clock_mark_{index} = sphere radius=0.6 segments=16 "
        f"at=[{x},115.9,{z}] color=#7d684b")
add()
add("check wall_back watertight")
add("check wall_left watertight")
add("check entry.leaf watertight")
add("check living_rug watertight")
add("check coffee watertight")
add("# По требованию: interference tolerance=0.01 limit=200")


def make_script() -> str:
    return "\n".join(lines) + "\n"


def bbox(solid):
    return np.asarray(solid.manifold.bounding_box(), dtype=float)


def aabb_overlap(a, b, eps=1e-5) -> bool:
    return bool(np.all(np.minimum(a[3:], b[3:]) - np.maximum(a[:3], b[:3]) > eps))


def assembly_root(name: str) -> str:
    return name.split(".", 1)[0]


# Только понятные механические/ботанические соединения. Никаких широких масок
# для мебели: панели шкафа, дивана и тумбы проверяются между собой полностью.
ALLOWED_CONTACTS = (
    ("cup_handle", "cup_body"),
    ("plant_stem", "plant_leaf_*"),
    ("clock_hand_hour", "clock_hand_minute"),
    ("lamp_socket", "lamp_bulb*"),
    ("lamp_arc", "lamp_mount"),
    ("lamp_spider", "lamp_shade"),
    ("lamp_spokes_*", "lamp_spider"),
    ("lamp_spokes_*", "lamp_mount"),
    ("lamp_spokes_*", "lamp_spokes_*"),
)


def allowed_contact(a: str, b: str) -> bool:
    if assembly_root(a) == assembly_root(b):
        return True
    return any((fnmatch.fnmatch(a, left) and fnmatch.fnmatch(b, right)) or
               (fnmatch.fnmatch(a, right) and fnmatch.fnmatch(b, left))
               for left, right in ALLOWED_CONTACTS)


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
    # Проёмы проверяются объёмными зондами, а не успешным кодом boolean.
    door_probe = mf.Manifold.cube((20, 30, 80), True).translate((-163, -72, 58))
    window_probe = mf.Manifold.cube((60, 20, 30), True).translate((20, 123, 98))
    door_void = abs(float((objects["wall_left"].manifold ^ door_probe).volume()))
    window_void = abs(float((objects["wall_back"].manifold ^ window_probe).volume()))
    if door_void > 1e-4:
        problems.append(f"Дверной проём не сквозной: {door_void}")
    if window_void > 1e-4:
        problems.append(f"Оконный проём не сквозной: {window_void}")

    expected_top = 29.6
    remote_bottom = float(bbox(objects["remote_body"])[2])
    cup_bottom = float(bbox(objects["cup_body"])[2])
    if abs(remote_bottom - expected_top) > 1e-4:
        problems.append(f"Пульт не на столешнице: z={remote_bottom}")
    if abs(cup_bottom - expected_top) > 1e-4:
        problems.append(f"Чашка не на столешнице: z={cup_bottom}")

    collisions = []
    intentional = []
    candidates = 0
    for a, b in combinations(solids, 2):
        if not aabb_overlap(bbox(a), bbox(b)):
            continue
        candidates += 1
        volume = abs(float((a.manifold ^ b.manifold).volume()))
        if volume <= 0.01:
            continue
        record = {"a": a.name, "b": b.name, "volume_mm3": round(volume, 6)}
        if allowed_contact(a.name, b.name):
            intentional.append(record)
        else:
            collisions.append(record)
    if collisions:
        problems.append(f"Нежелательные пересечения: {len(collisions)}")

    frame_names = ["bookcase_side_l", "bookcase_side_r", "bookcase_back",
                   "bookcase_bottom", "bookcase_top"] + [f"bookcase_shelf_{i}" for i in range(3)]
    frame_overlaps = []
    for left, right in combinations(frame_names, 2):
        volume = abs(float((objects[left].manifold ^ objects[right].manifold).volume()))
        if volume > 1e-5:
            frame_overlaps.append({"a": left, "b": right, "volume_mm3": volume})
    if frame_overlaps:
        problems.append(f"Пересечения каркаса шкафа: {len(frame_overlaps)}")

    cloth = objects["throw"].meta.get("cloth", {})
    if not cloth.get("contacts") or cloth.get("free", 0) <= 0:
        problems.append("Плед не имеет свободных узлов и контактов с опорой")

    report = {
        "scene": str(SCENE_PATH),
        "objects": len(solids),
        "triangles": triangles,
        "all_bodies_valid": not any("status=" in p for p in problems),
        "door_opening_residual_mm3": door_void,
        "window_opening_residual_mm3": window_void,
        "remote_bottom_z": remote_bottom,
        "cup_bottom_z": cup_bottom,
        "interference_candidates": candidates,
        "unexpected_collisions": collisions,
        "allowed_contacts": intentional,
        "bookcase_frame_overlaps": frame_overlaps,
        "cloth": cloth,
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
    draw.text((30, 24), "Гостиная 1:20 — пересборка 0.52", font=title_font, fill=(238, 240, 233))
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
        raise SystemExit(str(result.error) + "\n" + str(result.log))
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
    detail_solids = [s for s in solids if s.name.startswith(
        ("coffee", "remote_", "cup_", "living_rug"))]
    detail_path = RENDER_DIR / "living_room_table_detail.png"
    render(detail_solids, result.scene.groups, "iso", detail_path, 900)
    bookcase_path = RENDER_DIR / "living_room_bookcase_detail.png"
    bookcase_solids = [s for s in solids if s.name.startswith(
        ("bookcase_", "books_", "bookcase", "decor_"))]
    render(bookcase_solids, result.scene.groups, "iso", bookcase_path, 900)
    contact_sheet(rendered, RENDER_DIR / "living_room_views.png")
    report.update({
        "glb": str(glb_path), "glb_bytes": glb_path.stat().st_size,
        "renders": [str(p) for _, p in rendered] + [str(detail_path), str(bookcase_path)],
    })
    (RENDER_DIR / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
