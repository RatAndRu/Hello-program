"""Параметрический дракон по трём визуальным референсам.

Запуск из корня репозитория:
    PYTHONPATH=forma python forma/docs/make_dragon_sovereign.py --stage silhouette
    PYTHONPATH=forma python forma/docs/make_dragon_sovereign.py --stage full

Создаёт редактируемый Forma-сценарий, GLB, контрольные виды и JSON-паспорт.
Фотограмметрия и абсолютный масштаб не заявляются: 360 мм — проектная высота,
невидимые стороны реконструированы по аналогии. Внешние mesh/текстуры не нужны.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path

import manifold3d as mf
import numpy as np

from forma.geometry import export_glb, manifold_from_arrays, manifold_mesh
from forma.render import render_views
from forma.run import build
from forma.sdf import round_cone_distance
from forma.topology import analyze_topology

ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "examples" / "dragon_sovereign.forma"
RENDER_DIR = ROOT / "renders" / "dragon_sovereign"
EXPORT_DIR = ROOT / "exports" / "dragon_sovereign"

BODY = "#87928f"
BASE = "#505856"
BONE = "#9aa39e"
EYE = "#101817"
WING_CAMBER = 24.0
FRONT_RESOLUTION = 1.20

UPPER_JAW_PATH = [(0, -28, 289), (0, -54, 286), (0, -82, 282)]
UPPER_JAW_RADII = [20, 16, 10]
UPPER_JAW_Z_SCALE = 0.55
LOWER_JAW_PATH = [(0, -25, 256), (0, -52, 253), (0, -78, 256)]
LOWER_JAW_RADII = [16, 12, 8]
LOWER_JAW_Z_SCALE = 0.45
TAIL_PATH = [(0, 68, 120), (15, 65, 94), (40, 105, 67), (75, 140, 52),
             (108, 151, 68), (128, 143, 96), (127, 127, 122), (118, 118, 133)]
TAIL_RADII = [22, 19, 15, 11, 8, 6, 4.2, 3.0]

lines: list[str] = []


def add(text: str = "") -> None:
    lines.append(text)


def fmt(value: float) -> str:
    return f"{value:.5f}".rstrip("0").rstrip(".")


def point(p) -> str:
    return "[" + ",".join(fmt(float(v)) for v in p) + "]"


def points(values) -> str:
    return "[" + ",".join(point(p) for p in values) + "]"


def numbers(values) -> str:
    return "[" + ",".join(fmt(float(v)) for v in values) + "]"


def sdf_ellipsoid(center, radii) -> str:
    c = [fmt(float(v)) for v in center]
    r = [fmt(float(v)) for v in radii]
    return f"sd_ellipsoid(x-({c[0]}),y-({c[1]}),z-({c[2]}),{r[0]},{r[1]},{r[2]})"


def sdf_capsule(a, b, radius: float) -> str:
    vals = [fmt(float(v)) for v in (*a, *b, radius)]
    return "sd_capsule(x,y,z," + ",".join(vals) + ")"


def sdf_round_cone(a, b, ra: float, rb: float) -> str:
    vals = [fmt(float(v)) for v in (*a, *b, ra, rb)]
    return "sd_round_cone(x,y,z," + ",".join(vals) + ")"


def sdf_chain(path, radii, z_scale: float = 1.0) -> str:
    """Касательная цепочка: никакого smin между её собственными сегментами."""
    if z_scale == 1.0:
        terms = [sdf_round_cone(a, b, ra, rb)
                 for a, b, ra, rb in zip(path[:-1], path[1:], radii[:-1], radii[1:])]
    else:
        terms = []
        for a, b, ra, rb in zip(path[:-1], path[1:], radii[:-1], radii[1:]):
            aa = (a[0], a[1], a[2] / z_scale)
            bb = (b[0], b[1], b[2] / z_scale)
            terms.append(f"({sdf_round_cone(aa, bb, ra, rb).replace('z,', f'z/{fmt(z_scale)},', 1)}"
                         f"*{fmt(z_scale)})")
    expr = terms[0]
    for term in terms[1:]:
        expr = f"min({expr},{term})"
    return expr


def smooth_union(terms, blend: float) -> str:
    if not terms:
        raise ValueError("empty SDF group")
    expr = terms[0]
    for term in terms[1:]:
        expr = f"smin({expr},{term},{fmt(blend)})"
    return expr


def emit_sdf(name: str, groups, bounds, resolution: float, color: str = BODY) -> None:
    expr = smooth_union([smooth_union(terms, blend) for terms, blend in groups], 5.0)
    add(f'{name} = from_sdf expression="{expr}" bounds={point(bounds)} '
        f'resolution={fmt(resolution)} color={color} rough=0.72')


def emit_sweep(name: str, path, radius: float, curve=None, *, color: str = BODY,
               sides: int = 20, smooth: int = 4, caps: float = 0.08,
               width: float | None = None, height: float | None = None) -> None:
    profile = f"radius={fmt(radius)}"
    if width is not None and height is not None:
        profile = f"width={fmt(width)} height={fmt(height)}"
    scale = f" scale_curve={numbers(curve)}" if curve else ""
    add(f"{name} = sweep path={points(path)} {profile} sides={sides} "
        f"smooth={smooth}{scale} round_caps={fmt(caps)} color={color} rough=0.72")


def emit_ellipsoid(name: str, center, radii, color: str = BODY) -> None:
    add(f"{name} = ellipsoid x={fmt(radii[0])} y={fmt(radii[1])} z={fmt(radii[2])} "
        f"center=да at={point(center)} detail=4 color={color} rough=0.7")


def horn(name: str, path, radius: float, color: str = BODY) -> None:
    n = len(path)
    curve = [1.22] + [max(0.035, 1.0 - 0.97 * (i / (n - 1)) ** 0.82)
                      for i in range(1, n)]
    emit_sweep(name, path, radius, curve, color=color, sides=24, smooth=5, caps=0.12)


def mirrored_path(path, sign: int):
    return [(sign * p[0], p[1], p[2]) for p in path]


def build_core(stage: str) -> None:
    add("# Ядро v2: четыре опоры, касательные round-cone цепочки, открытая пасть.")
    torso = [
        sdf_ellipsoid((0, 25, 118), (37, 33, 44)),
        sdf_ellipsoid((0, 8, 157), (36, 29, 52)),
        sdf_ellipsoid((0, -4, 194), (42, 31, 43)),
    ]
    neck_path = [(0, -5, 202), (0, 6, 229), (0, 5, 253), (0, -15, 276)]
    neck = sdf_chain(neck_path, [22, 19, 17, 18])
    emit_sdf("body_bed", [(torso, 10.0), ([neck], 7.0)],
             [-52, -48, 65, 52, 52, 298], 1.7)

    # Череп отделён от пасти: в полной версии только его наружная поверхность
    # получает мелкие наросты, поэтому шипы не появляются внутри рта.
    emit_sdf("skull_bed", [([sdf_ellipsoid((0, -28, 290), (27, 28, 25))], 1.0)],
             [-32, -61, 260, 32, 5, 320], 1.25)
    jaws = [
        sdf_chain(UPPER_JAW_PATH, UPPER_JAW_RADII, UPPER_JAW_Z_SCALE),
        sdf_chain(LOWER_JAW_PATH, LOWER_JAW_RADII, LOWER_JAW_Z_SCALE),
        sdf_ellipsoid((0, -18, 264), (22, 14, 20)),
        sdf_ellipsoid((0, -54, 260), (8, 20, 2.2)),
    ]
    for s in (-1, 1):
        jaws.append(sdf_chain([(s * 16, -30, 281), (s * 15, -45, 278),
                               (s * 12, -60, 278), (s * 8, -77, 278), (s * 4, -87, 281)],
                              [1.4, 1.8, 1.8, 1.4, 0.8]))
        jaws.append(sdf_chain([(s * 13, -28, 261), (s * 12, -45, 260),
                               (s * 10, -60, 259), (s * 7, -72, 258.5), (s * 3, -83, 258)],
                              [1.3, 1.6, 1.6, 1.2, 0.7]))
    emit_sdf("body_core", [(jaws, 5.0)], [-31, -101, 238, 31, 5, 305], 1.3)

    # Обе передние лапы опущены. Пальцы входят в то же SDF-поле, но их
    # касательные сегменты не раздуваются сглаживанием каждого сустава.
    for s, side in ((1, "R"), (-1, "L")):
        front_path = [(s * 40, -8, 204), (s * 57, -25, 153),
                      (s * 63, -52, 91), (s * 63, -61, 69)]
        front = [
            sdf_ellipsoid((s * 40, -8, 201), (15, 17, 20)),
            sdf_ellipsoid((s * 55, -25, 154), (11, 12, 17)),
            sdf_chain(front_path, [12, 10, 7, 7.5]),
            sdf_ellipsoid((s * 63, -64, 64), (11, 13, 10)),
        ]
        for j, dx in enumerate((-10.0, -3.0, 4.0, 11.0)):
            finger = [(s * 63 + dx * 0.55, -60, 62),
                      (s * 63 + dx, -70 - (2 if j == 1 else 0), 41),
                      (s * 63 + dx * 1.15, -81 - (3 if j == 1 else 0), 24)]
            front.append(sdf_chain(finger, [3.8, 3.1, 2.35]))
        xb = (24, 84) if s > 0 else (-84, -24)
        emit_sdf(f"front_limb_{side}", [(front, 4.0)],
                 [xb[0], -104, 20, xb[1], 16, 227], FRONT_RESOLUTION)

        hind_path = [(s * 34, 24, 124), (s * 50, 4, 84), (s * 45, -22, 51)]
        hind = [
            sdf_ellipsoid((s * 32, 24, 123), (22, 25, 31)),
            sdf_ellipsoid((s * 49, 3, 84), (15, 17, 18)),
            sdf_chain(hind_path, [16, 12, 8]),
            sdf_ellipsoid((s * 45, -30, 40), (16, 23, 9)),
        ]
        for j, dx in enumerate((-9.0, 0.0, 9.0)):
            toe = [(s * 45 + dx * 0.65, -40, 39),
                   (s * 45 + dx, -54 - (2 if j == 1 else 0), 35),
                   (s * 45 + dx * 1.15, -66 - (3 if j == 1 else 0), 33)]
            hind.append(sdf_chain(toe, [4.5, 3.6, 2.7]))
        xb = (18, 76) if s > 0 else (-76, -18)
        emit_sdf(f"hind_limb_{side}", [(hind, 4.5)],
                 [xb[0], -86, 20, xb[1], 58, 158], 1.4)

    tail_path = TAIL_PATH
    tail_radii = TAIL_RADII
    emit_sdf("tail_core", [([sdf_chain(tail_path, tail_radii)], 1.0)],
             [-27, 5, 25, 153, 176, 158], 1.30)


def build_wings() -> None:
    add("\n# Крыло v2: парашютный camber=24 мм и пять интегральных рёбер.")
    add("# Рёбра — рельеф самой замкнутой мембраны, не вторые тела поверх неё.")
    wrist = np.array([45.0, 0.0])
    tips = [np.array(p, dtype=float) for p in
            ((150, 85), (175, 35), (165, -15), (135, -55), (95, -75))]
    outline = [(0.0, -20.0), (20.0, -5.0), tuple(wrist), (96.0, 48.0), tuple(tips[0])]

    def scalloped(a, b, amount):
        result = []
        for k in range(1, 10):
            u = k / 9.0
            p = (1.0 - u) * a + u * b
            p += (wrist - p) * (amount * math.sin(math.pi * u))
            result.append(tuple(float(v) for v in p))
        return result

    for i in range(len(tips) - 1):
        outline += scalloped(tips[i], tips[i + 1], 0.22 if i else 0.16)
    trailing = np.array([8.0, -35.0])
    outline += scalloped(tips[-1], trailing, 0.18)
    membrane_root = np.array([38.0, -3.0])
    rib_angles = [math.degrees(math.atan2(tip[1] - membrane_root[1],
                                         tip[0] - membrane_root[0])) for tip in tips]
    add(f"wing_R = membrane root=[38,-3] outline={points(outline)} "
        f"camber={fmt(WING_CAMBER)} thick=0.9 rings=14 "
        f"rib_angles={numbers(rib_angles)} rib_height=3.2 rib_width=5 "
        f"color={BODY} rough=0.78")
    add("wing_R = twist [wing_R] angle=-10 axis=x")
    add("rotate [wing_R] angle=62 axis=x")
    add("rotate [wing_R] angle=-32 axis=y")
    add("rotate [wing_R] angle=12 axis=z")
    add("translate [wing_R] offset=[32,15,198]")
    add("wings = mirror [wing_R] plane=x keep=да")

def build_main_horns() -> None:
    add("\n# Большие рога задают силуэт уже на первой стадии.")
    base = [(15, -13, 306), (22, 2, 326), (28, 23, 347), (23, 39, 360)]
    for s, side in ((1, "R"), (-1, "L")):
        horn(f"horn_main_{side}", mirrored_path(base, s), 8.2)
    add("skull_bed = union [skull_bed, horn_main_R, horn_main_L]")


def build_head_details() -> None:
    add("\n# Лицо v2: губные валики, язык, брови, венец рогов и глубокие глазницы.")
    brow = [(18, -42, 303), (26, -32, 313), (32, -15, 324), (31, 2, 333)]
    cheek = [(22, -20, 278), (34, -10, 280), (45, 5, 290)]
    crown_a = [(16, -30, 300), (31, -20, 308), (45, -8, 319)]
    crown_b = [(13, -26, 296), (28, -18, 301), (43, 2, 309)]
    for s, side in ((1, "R"), (-1, "L")):
        horn(f"horn_brow_{side}", mirrored_path(brow, s), 4.6)
        horn(f"horn_cheek_{side}", mirrored_path(cheek, s), 4.0)
        horn(f"horn_crown_a_{side}", mirrored_path(crown_a, s), 3.4)
        horn(f"horn_crown_b_{side}", mirrored_path(crown_b, s), 2.8)
        emit_ellipsoid(f"socket_{side}", (s * 23, -42, 298), (5.8, 6.0, 4.2), BODY)
        emit_ellipsoid(f"nostril_{side}", (s * 6, -84, 286), (2.5, 3.5, 2.0), BODY)
    horn("horn_nose", [(0, -58, 294), (0, -50, 306), (0, -40, 314)], 3.0)
    add("skull_bed = union [skull_bed, horn_brow_R, horn_brow_L, horn_cheek_R, "
        "horn_cheek_L, horn_crown_a_R, horn_crown_a_L, horn_crown_b_R, horn_crown_b_L]")
    add("body_core = union [body_core, horn_nose]")
    add("skull_bed = difference [skull_bed, socket_R, socket_L]")
    add("body_core = difference [body_core, nostril_R, nostril_L]")
    for s, side in ((1, "R"), (-1, "L")):
        emit_ellipsoid(f"eye_{side}", (s * 23.8, -43.5, 298), (3.3, 3.1, 2.8), EYE)
        add(f"color eye_{side} {EYE} rough=0.22")


def build_teeth_and_claws() -> None:
    add("\n# Зубы v2: корни по настоящей десне, кончики внутри скруглённого контура.")
    add("skin_origin = union [body_bed, front_limb_R, front_limb_L, hind_limb_R, "
        "hind_limb_L, tail_core]")
    teeth = []

    def jaw_distance(x, y, z, path, radii, z_scale):
        values = []
        for a, b, ra, rb in zip(path[:-1], path[1:], radii[:-1], radii[1:]):
            aa = (a[0], a[1], a[2] / z_scale)
            bb = (b[0], b[1], b[2] / z_scale)
            values.append(float(round_cone_distance(x, y, z / z_scale, aa, bb, ra, rb)) * z_scale)
        return min(values)

    def gum_boundary(x, y, path, radii, z_scale, upper):
        grid = np.linspace(235.0, 310.0, 301)
        values = np.array([jaw_distance(x, y, z, path, radii, z_scale) for z in grid])
        inside = np.flatnonzero(values < 0.0)
        if not len(inside):
            raise ValueError(f"tooth outside shaped gum: {x}, {y}")
        index = int(inside[0] if upper else inside[-1])
        if (upper and index == 0) or (not upper and index == len(grid) - 1):
            raise ValueError(f"unbracketed gum boundary: {x}, {y}")
        lo, hi = (grid[index - 1], grid[index]) if upper else (grid[index], grid[index + 1])
        for _ in range(24):
            mid = (lo + hi) * 0.5
            negative = jaw_distance(x, y, mid, path, radii, z_scale) < 0.0
            if upper:
                if negative:
                    hi = mid
                else:
                    lo = mid
            else:
                if negative:
                    lo = mid
                else:
                    hi = mid
        return (lo + hi) * 0.5

    def upper_gum(x, y):
        return gum_boundary(x, y, UPPER_JAW_PATH, UPPER_JAW_RADII,
                            UPPER_JAW_Z_SCALE, True) + 1.0

    def upper_tooth(name, x, y, tip_z, radius):
        root_z = upper_gum(x, y)
        horn(name, [(x, y, root_z), (x * 1.005, y - 0.4, (root_z + tip_z) * 0.5),
                    (x * 1.01, y - 0.8, tip_z)], radius, BONE)

    for s, side in ((1, "R"), (-1, "L")):
        for i, (y, width) in enumerate(zip((-77, -66, -55, -44, -36),
                                           (6.5, 9.5, 11.0, 10.0, 8.0))):
            x = s * width
            name = f"tooth_U_{side}_{i}"
            upper_tooth(name, x, y, 261.0 if i == 1 else 267.0,
                        2.25 if i == 1 else 1.65)
            teeth.append(name)
        for i, (y, width) in enumerate(zip((-72, -61, -50),
                                           (5.5, 7.5, 8.5))):
            x = s * width
            root_z = gum_boundary(x, y, LOWER_JAW_PATH, LOWER_JAW_RADII,
                                  LOWER_JAW_Z_SCALE, False) - 1.0
            name = f"tooth_D_{side}_{i}"
            horn(name, [(x, y, root_z), (x, y - 0.3, (root_z + 270.0) * 0.5),
                        (x * 0.99, y - 0.6, 270.0)], 1.45, BONE)
            teeth.append(name)
    for i, x in enumerate((-4.0, 4.0)):
        name = f"tooth_front_{i}"
        upper_tooth(name, x, -80, 268.0, 1.55)
        teeth.append(name)
    add("body_core = union [body_core, " + ", ".join(teeth) + "]")

    add("\n# Четыре опоры: по три когтя сзади и по четыре на передних лапах.")
    all_claws = []
    for s, side in ((1, "R"), (-1, "L")):
        front_claws = []
        for j, dx in enumerate((-10.0, -3.0, 4.0, 11.0)):
            x = s * 63 + dx * 1.15
            y = -81 - (3 if j == 1 else 0)
            name = f"claw_F_{side}_{j}"
            horn(name, [(x, y + 2, 25), (x + s * dx * 0.05, y - 5, 19),
                        (x + s * dx * 0.10, y - 9, 11.5)], 2.8, BONE)
            front_claws.append(name)
        all_claws.extend(front_claws)
        hind_claws = []
        for j, dx in enumerate((-9.0, 0.0, 9.0)):
            x = s * 45 + dx * 1.15
            y = -66 - (3 if j == 1 else 0)
            name = f"claw_H_{side}_{j}"
            horn(name, [(x, y + 2, 34), (x + s * dx * 0.10, y - 5, 31),
                        (x + s * dx * 0.18, y - 11, 26)], 3.0, BONE)
            hind_claws.append(name)
        all_claws.extend(hind_claws)
    add("skin_origin = union [skin_origin, " + ", ".join(all_claws) + "]")


def build_spines_and_tail_fin() -> None:
    add("\n# Спинной гребень и листовидный наконечник хвоста.")
    spines = []
    for i, (y, z, r) in enumerate(((20, 213, 5.0), (27, 235, 4.8),
                                   (22, 257, 4.2), (2, 281, 3.8))):
        name = f"spine_neck_{i}"
        horn(name, [(0, y - 7, z - 3), (0, y + 10, z + 6),
                    (0, y + 20, z + 22)], r)
        spines.append(name)
    for i, (x, y, z, r) in enumerate(((15, 65, 108, 4.5), (40, 105, 80, 4.0),
                                      (75, 140, 62, 3.4), (108, 151, 77, 2.8),
                                      (128, 143, 105, 2.2))):
        name = f"spine_tail_{i}"
        horn(name, [(x, y - 3, z - 5), (x + 2, y + 5, z + 7),
                    (x + 4, y + 10, z + 18)], r)
        spines.append(name)
    add("body_core = union [body_core, " + ", ".join(spines) + "]")
    fin_outline = [(-5, 0), (-16, 14), (-12, 28), (-5, 24), (0, 48),
                   (5, 24), (12, 28), (16, 14), (5, 0)]
    add(f"tail_fin = membrane root=[0,12] outline={points(fin_outline)} "
        f"camber=2 thick=2.2 rings=8 color={BODY} rough=0.75")
    add("rotate [tail_fin] angle=90 axis=x")
    add("rotate [tail_fin] angle=-20 axis=z")
    add("translate [tail_fin] offset=[118,118,132]")
    horn("tail_spear", [(118, 118, 136), (113, 114, 155), (107, 110, 178)], 3.2)
    add("body_core = union [body_core, tail_fin, tail_spear]")


def build_breast_plates() -> None:
    add("\n# Грудь v2: крупные выпуклые chevron-щитки, не трубчатые складки.")
    plates = []
    torso_sections = ((25, 33, 118, 44), (8, 29, 157, 52), (-4, 31, 194, 43))
    for i, z in enumerate((208, 194, 180, 166, 152, 138, 124)):
        half = 30 + 5 * math.sin((i + 1) / 8 * math.pi)
        front_candidates = []
        for cy, ry, cz, rz in torso_sections:
            q = ((z - cz) / rz) ** 2
            if q < 1.0:
                front_candidates.append(cy - ry * math.sqrt(1.0 - q))
        front = min(front_candidates)
        # Сплошная зона контакта: задняя сторона центра остаётся внутри тела.
        # Ряды визуально наслаиваются, но физически не замыкают циклы друг с другом.
        y = front + (3.8 if i == 3 else 3.0)
        outline = [(-half, 4), (-half * .55, 5), (0, 1.5),
                   (half * .55, 5), (half, 4), (half * .65, -4),
                   (0, -8), (-half * .65, -4)]
        name = f"breast_{i}"
        add(f"{name} = membrane root=[0,0] outline={points(outline)} "
            f"camber=3.2 thick=1.8 rings=6 color={BODY} rough=0.75")
        add(f"rotate [{name}] angle=90 axis=x")
        add(f"translate [{name}] offset=[0,{y:.3f},{z}]")
        plates.append(name)
    add("body_core = union [body_core, " + ", ".join(plates) + "]")


def build_scales() -> None:
    add("\n# Финальная чешуя: ray-cast по skin_origin, safe по всему dragon.")
    add("# После этой операции в dragon уже не добавляются детали с неучтёнными контактами.")
    add("skull_bed = spikes [skull_bed] surface=вся density=32 height=3.2 "
        "base_d=3.4 tip_d=0.35 sides=12 seed=9 safe=да")
    add("dragon = union [body_core, skull_bed, skin_origin, wings]")
    body_path = [(0, 25, 82), (0, 8, 150), (0, -4, 194),
                 (0, 6, 229), (0, 5, 253), (0, -15, 276)]
    front_r = [(40, -8, 204), (57, -25, 153), (63, -52, 91), (63, -61, 69)]
    front_l = mirrored_path(front_r, -1)
    hind_r = [(34, 24, 124), (50, 4, 84), (45, -22, 51)]
    hind_l = mirrored_path(hind_r, -1)
    tail_path = TAIL_PATH
    paths = [body_path, front_r, front_l, hind_r, hind_l, tail_path]
    paths_text = "[" + ",".join(points(path) for path in paths) + "]"
    add(f"scales dragon on=skin_origin kind=дракон paths={paths_text} "
        "pitch=9 per_row=18 length=8 thick=0.75 tilt=22 safe=да seed=2")


def build_base() -> None:
    add("\n# Круглое основание и связанный каменный рельеф.")
    add(f"plinth = cylinder radius=122 height=12 segments=160 round=2 "
        f"at=[0,0,0] color={BASE} rough=0.86")
    add(f"rock_main = rock size=[200,180,22] seed=33 rough=0.42 points=72 "
        f"at=[0,5,10] color={BASE}")
    add(f"color rock_main {BASE} rough=0.9")
    rocks = ["plinth", "rock_main"]
    for i, (x, y, sx, sy, sz) in enumerate(((-72, -18, 45, 42, 18),
                                            (68, -5, 52, 40, 20),
                                            (-62, 66, 55, 46, 24),
                                            (57, 76, 48, 50, 19),
                                            (0, -48, 65, 38, 15))):
        name = f"rock_{i}"
        add(f"{name} = rock size=[{sx},{sy},{sz}] seed={41 + i} rough=0.48 "
            f"points=40 at=[{x},{y},{10 if i >= 5 else 16}] color={BASE}")
        add(f"color {name} {BASE} rough=0.9")
        rocks.append(name)
    for s, side in ((1, "R"), (-1, "L")):
        name = f"hind_rest_{side}"
        add(f"{name} = rock size=[64,62,12] seed={55 + (s < 0)} rough=0.5 "
            f"points=40 at=[{s * 45},-66,18] color={BASE}")
        add(f"color {name} {BASE} rough=0.9")
        rocks.append(name)
    add("base = union [" + ", ".join(rocks) + "]")


def generate(stage: str) -> str:
    lines.clear()
    add("# DRAGON SOVEREIGN — параметрическая скульптура по трём референсам.")
    add("# Проектная высота 360 мм; фотограмметрический масштаб не заявляется.")
    add("# Канон: +Z вверх, −Y перед, +X право. Внешние ресурсы не нужны.")
    add("# Пропорции: основание ≈0,61H; крылья ≈1,0H; торс ≈0,36H; голова+шея ≈0,34H.")
    add("scene source=dragon_sovereign_references_34_38_39")
    build_core(stage)
    build_wings()
    build_main_horns()
    if stage == "full":
        build_head_details()
        build_spines_and_tail_fin()
        build_breast_plates()
        build_teeth_and_claws()
        build_scales()  # последняя геометрическая операция над dragon
    add("\n# Финальная сварка основных органических переходов.")
    if stage != "full":
        add("dragon = union [body_core, skull_bed, body_bed, front_limb_R, front_limb_L, "
            "hind_limb_R, hind_limb_L, tail_core, wings]")
    build_base()
    add("check dragon watertight")
    add("check dragon parts 1")
    add("check base watertight")
    add("check base parts 1")
    return "\n".join(lines) + "\n"


def inspect_glb_roundtrip(glb_path: Path) -> list[dict]:
    """Проверяет сам файл, а не только исходный Manifold.

    glTF закономерно дублирует вершины на UV/normal seams. Перед структурной
    проверкой такие дубли свариваются только по координатам; грани и форма не
    изменяются. Это не repair: после сварки выполняется строгий exact-анализ.
    """
    import trimesh

    loaded = trimesh.load(glb_path, force="scene")
    reports = []
    for name, source_mesh in loaded.geometry.items():
        mesh = source_mesh.copy()
        mesh.merge_vertices(merge_tex=True, merge_norm=True)
        mesh.remove_unreferenced_vertices()
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        topology = analyze_topology(verts, faces, tolerance=1e-12, include_quality=False)
        solid = manifold_from_arrays(verts, faces, what=f"GLB «{name}»")
        reports.append({
            "name": name,
            "triangles": int(len(faces)),
            "components": len(solid.decompose()),
            "genus": int(solid.genus()),
            "status": str(solid.status()),
            "boundary_edges": int(topology["boundary_edges"]),
            "non_manifold_edges": int(topology["non_manifold_edges"]),
            "degenerate_index": int(topology["degenerate_index"]),
            "degenerate_area": int(topology["degenerate_area"]),
            "watertight_after_position_weld": bool(mesh.is_watertight),
        })
    return reports


def validate_and_export(stage: str, script: str, render: bool = True) -> dict:
    SCENE_PATH.write_text(script, encoding="utf-8")
    result = build(script)
    if not result.ok:
        raise RuntimeError(json.dumps(result.error, ensure_ascii=False, indent=2))
    solids = result.visible_solids()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    glb_path = EXPORT_DIR / ("dragon_sovereign.glb" if stage == "full"
                             else "dragon_sovereign_silhouette.glb")
    glb_path.write_bytes(export_glb(solids))
    report = {
        "stage": stage,
        "script": str(SCENE_PATH.relative_to(ROOT)),
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "glb": str(glb_path.relative_to(ROOT)),
        "glb_bytes": glb_path.stat().st_size,
        "glb_sha256": hashlib.sha256(glb_path.read_bytes()).hexdigest(),
        "scale_assumption_mm": 360,
        "reference_measurements": "проектные пропорции, не фотограмметрия",
        "objects": [],
        "glb_roundtrip": inspect_glb_roundtrip(glb_path),
        "build_log": result.log,
    }
    for solid in solids:
        verts, faces = manifold_mesh(solid.manifold)
        topology = analyze_topology(verts, faces, include_quality=True)
        exact = analyze_topology(verts, faces, tolerance=1e-12, include_quality=False)
        components = len(solid.manifold.decompose())
        item = {
            "name": solid.name,
            "triangles": int(solid.manifold.num_tri()),
            "components": components,
            "genus": int(solid.manifold.genus()),
            "volume_mm3": float(solid.manifold.volume()),
            "bbox_mm": list(solid.manifold.bounding_box()),
            "status": str(solid.manifold.status()),
            "boundary_edges": int(topology["boundary_edges"]),
            "non_manifold_edges": int(topology["non_manifold_edges"]),
            "degenerate_index": int(topology["degenerate_index"]),
            "degenerate_area": int(topology["degenerate_area"]),
            "exact_boundary_edges": int(exact["boundary_edges"]),
            "exact_non_manifold_edges": int(exact["non_manifold_edges"]),
            "exact_degenerate_index": int(exact["degenerate_index"]),
        }
        report["objects"].append(item)
        if (components != 1 or item["genus"] != 0 or solid.manifold.status().name != "NoError"
                or topology["boundary_edges"] or topology["non_manifold_edges"]
                or exact["boundary_edges"] or exact["non_manifold_edges"]):
            raise RuntimeError("Source gate: " + json.dumps(item, ensure_ascii=False))
    glb_bad = [o for o in report["glb_roundtrip"] if
               (o["components"] != 1 or o["genus"] != 0 or o["boundary_edges"]
                or o["non_manifold_edges"] or o["degenerate_index"] or o["degenerate_area"]
                or not o["watertight_after_position_weld"])]
    if glb_bad:
        raise RuntimeError("GLB gate: " + json.dumps(glb_bad, ensure_ascii=False))
    if stage == "full":
        base = next(s for s in solids if s.name == "base")
        supports = []
        for name, obj in sorted(result.scene.objects.items()):
            if not name.startswith("claw_"):
                continue
            contact = float((base.manifold ^ obj.manifold).volume())
            supports.append({"name": name, "contact_mm3": contact})
        report["support_checks"] = supports
        if len(supports) != 14 or any(s["contact_mm3"] <= 1e-6 for s in supports):
            raise RuntimeError("Support gate: " + json.dumps(supports, ensure_ascii=False))
        report["design_checks"] = {
            "supports": "4 опоры; объёмный контакт всех 8 передних и 6 задних когтей",
            "wing_camber_mm": WING_CAMBER,
            "wing_relief": "5 интегральных рёбер в замкнутой мембране на каждое крыло",
            "front_sdf_resolution_mm": FRONT_RESOLUTION,
            "scales": "scales.on по skin_origin; safe по полному dragon после всех деталей",
            "breast_plates": "7 выпуклых chevron-щитков; не трубчатые sweep-валики",
        }
    if render:
        views = ("iso", "front", "right", "back", "top")
        rendered = render_views(solids, RENDER_DIR, prefix=f"dragon_{stage}",
                                size=800, ss=2, views=views, combined=True)
        report["renders"] = rendered
        if stage == "full":
            from forma import render as render_backend
            meshes = render_backend._prepare(solids)
            center = np.array([0.0, -22.0, 305.0])
            radius = 88.0
            head_bbox = [*(center - radius), *(center + radius)]
            head_files = []
            for view in ("iso", "right"):
                image, _ = render_backend._render_view(
                    meshes, center, radius, view, 800, 2, head_bbox,
                    grid=False, shadow=False)
                path = RENDER_DIR / f"dragon_head_{view}.png"
                render_backend.write_png(path, render_backend._to_bytes(image))
                head_files.append(str(path.relative_to(ROOT)))
            report["head_renders"] = head_files
            shutil.copyfile(RENDER_DIR / "dragon_full_iso.png",
                            ROOT / "docs" / "dragon_sovereign_preview.png")
    report_path = EXPORT_DIR / f"dragon_sovereign_{stage}_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("build_log", "renders")},
                     ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("silhouette", "full"), default="full")
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()
    script = generate(args.stage)
    report = validate_and_export(args.stage, script, render=not args.no_render)
    bad = [o for o in report["objects"] if o["name"] in ("dragon", "base") and
           (o["components"] != 1 or o["boundary_edges"] or o["non_manifold_edges"] or
            o["degenerate_area"] or o["genus"] != 0)]
    glb_bad = [o for o in report["glb_roundtrip"] if
               (o["components"] != 1 or o["boundary_edges"] or o["non_manifold_edges"] or
                o["degenerate_index"] or o["degenerate_area"] or
                not o["watertight_after_position_weld"] or o["genus"] != 0)]
    if bad or glb_bad:
        raise SystemExit("Топологический контроль не пройден: " +
                         json.dumps({"source": bad, "glb": glb_bad}, ensure_ascii=False))


if __name__ == "__main__":
    main()
