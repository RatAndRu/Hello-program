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
from pathlib import Path

import manifold3d as mf
import numpy as np

from forma.geometry import export_glb, manifold_from_arrays, manifold_mesh
from forma.render import render_views
from forma.run import build
from forma.topology import analyze_topology

ROOT = Path(__file__).resolve().parents[1]
SCENE_PATH = ROOT / "examples" / "dragon_sovereign.forma"
RENDER_DIR = ROOT / "renders" / "dragon_sovereign"
EXPORT_DIR = ROOT / "exports" / "dragon_sovereign"

BODY = "#87928f"
BASE = "#505856"
BONE = "#9aa39e"
EYE = "#101817"

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
    add("# Ядро: мышцы, шея, открытая пасть, конечности и пальцы — единое SDF-поле.")
    torso = [
        sdf_ellipsoid((0, 15, 105), (42, 33, 46)),
        sdf_ellipsoid((0, 5, 151), (38, 31, 58)),
        sdf_ellipsoid((0, 0, 194), (48, 35, 48)),
        sdf_ellipsoid((0, -18, 183), (34, 22, 44)),
    ]
    neck_head = [
        sdf_capsule((0, 8, 207), (0, 30, 247), 24),
        sdf_capsule((0, 30, 242), (0, 2, 279), 20),
        sdf_ellipsoid((0, -10, 291), (31, 30, 30)),
        sdf_ellipsoid((0, -48, 285), (23, 43, 12)),
        sdf_ellipsoid((0, -78, 287), (24, 18, 10)),
        sdf_ellipsoid((0, -44, 247), (19, 40, 8)),
        sdf_ellipsoid((0, -18, 260), (24, 23, 20)),
    ]
    tail_root = [sdf_capsule((0, 28, 116), (12, 55, 98), 22)]
    legs = []
    for s in (-1, 1):
        legs += [
            sdf_ellipsoid((s * 31, 13, 122), (25, 29, 36)),
            sdf_capsule((s * 34, 8, 122), (s * 50, -7, 86), 19),
            sdf_ellipsoid((s * 50, -9, 83), (20, 21, 22)),
            sdf_capsule((s * 50, -8, 81), (s * 45, -23, 51), 13),
            sdf_ellipsoid((s * 45, -36, 40), (20, 30, 10)),
        ]
        for j, dx in enumerate((-10, 0, 10)):
            root = (s * 45 + dx, -49, 40)
            mid = (s * 45 + dx * 1.25, -64 - (2 if j == 1 else 0), 36)
            tip = (s * 45 + dx * 1.45, -74 - (3 if j == 1 else 0), 34)
            legs += [sdf_capsule(root, mid, 5.3), sdf_capsule(mid, tip, 4.1)]
    arms = [
        # Поднятая левая передняя лапа.
        sdf_ellipsoid((-42, 0, 205), (21, 23, 26)),
        sdf_capsule((-42, 0, 204), (-65, -13, 184), 14),
        sdf_ellipsoid((-67, -15, 185), (15, 15, 16)),
        sdf_capsule((-67, -15, 187), (-73, -40, 216), 11),
        sdf_ellipsoid((-73, -47, 228), (14, 11, 17)),
        # Опущенная правая передняя лапа.
        sdf_ellipsoid((42, 0, 205), (21, 23, 26)),
        sdf_capsule((42, 0, 204), (61, -7, 174), 14),
        sdf_ellipsoid((62, -9, 172), (15, 15, 16)),
        sdf_capsule((62, -10, 170), (70, -31, 141), 10.5),
        sdf_ellipsoid((70, -40, 132), (13, 11, 16)),
    ]
    for j, (dx, dy, dz) in enumerate(((-11, -3, 12), (-4, -8, 18), (4, -8, 17), (11, -3, 10))):
        root = (-73 + dx * 0.45, -49, 232)
        mid = (-73 + dx, -52 + dy * 0.35, 239 + dz * 0.35)
        tip = (-73 + dx * 1.35, -53 + dy, 239 + dz)
        arms += [sdf_capsule(root, mid, 4.3), sdf_capsule(mid, tip, 3.2)]
    for j, (dx, dy, dz) in enumerate(((-10, -3, -10), (-3, -8, -16), (4, -8, -15), (10, -2, -8))):
        root = (70 + dx * 0.4, -42, 130)
        mid = (70 + dx, -46 + dy * 0.3, 124 + dz * 0.35)
        tip = (70 + dx * 1.3, -47 + dy, 123 + dz)
        arms += [sdf_capsule(root, mid, 4.1), sdf_capsule(mid, tip, 3.0)]
    groups = [(neck_head, 8.0), (tail_root, 9.0), (legs, 7.0), (arms, 6.0)]
    if stage == "silhouette":
        groups.insert(0, (torso, 11.0))
    # В полной версии торс приходит ровно один раз вместе с чешуёй через
    # scale_bed; это исключает две почти совпадающие SDF-поверхности.
    emit_sdf("body_core", groups, [-102, -108, 20, 102, 82, 326], 2.05)

    tail_path = [
        ((0, 35, 115), (15, 65, 91), 21),
        ((15, 65, 91), (35, 103, 65), 17),
        ((35, 103, 65), (65, 137, 49), 13.5),
        ((65, 137, 49), (99, 154, 55), 10.5),
        ((99, 154, 55), (126, 151, 81), 8.0),
        ((126, 151, 81), (130, 135, 112), 5.7),
        ((130, 135, 112), (128, 128, 132), 4.0),
    ]
    emit_sdf("tail_core", [([sdf_capsule(a, b, r) for a, b, r in tail_path], 7.0)],
             [-27, 12, 25, 153, 181, 151], 1.65)


def build_wings() -> None:
    add("\n# Крыло: собственный анатомический контур, пять неравных пальцев,")
    add("# вогнутая мембрана толщиной 0,9 мм и объёмное плечо.")
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
    add(f"wing_membrane_R = extrude profile={points(outline)} height=0.9 "
        f"color={BODY} rough=0.78")
    wing_parts = ["wing_membrane_R"]
    emit_sweep("wing_arm_R", [(0, -15, 0.45), (20, -5, 0.45), (45, 0, 0.45)],
               8.5, [1.3, 1.05, 0.82], sides=24, smooth=5)
    wing_parts.append("wing_arm_R")
    for i, tip in enumerate(tips):
        direction = (tip - wrist) / float(np.linalg.norm(tip - wrist))
        end = tip + direction * 4.0
        mid = wrist * 0.48 + tip * 0.52
        mid += np.array([-direction[1], direction[0]]) * (3.0 if i < 2 else -2.0)
        name = f"wing_finger_R_{i}"
        emit_sweep(name, [(wrist[0], wrist[1], 0.45), (mid[0], mid[1], 0.45),
                          (end[0], end[1], 0.45)],
                   4.6 if i == 0 else 3.1, [1.18, 0.82, 0.16],
                   sides=20, smooth=5, caps=0.12)
        wing_parts.append(name)
    add("wing_R = union [" + ", ".join(wing_parts) + "]")
    add("wing_R = twist [wing_R] angle=-10 axis=x")
    add("rotate [wing_R] angle=62 axis=x")
    add("rotate [wing_R] angle=-32 axis=y")
    add("rotate [wing_R] angle=12 axis=z")
    add("translate [wing_R] offset=[32,15,198]")
    add("wings = mirror [wing_R] plane=x keep=да")


def build_main_horns() -> None:
    add("\n# Большие рога задают силуэт уже на первой стадии.")
    base = [(18, 0, 307), (25, 12, 327), (30, 29, 346), (26, 43, 360)]
    for s, side in ((1, "R"), (-1, "L")):
        horn(f"horn_main_{side}", mirrored_path(base, s), 8.2)
    add("body_core = union [body_core, horn_main_R, horn_main_L]")


def build_head_details() -> None:
    add("\n# Брови, cheek-рога, ноздри и глубокие глазницы.")
    brow = [(19, -24, 302), (28, -18, 315), (34, -5, 329), (35, 7, 337)]
    cheek = [(24, -1, 278), (37, 5, 280), (48, 17, 290)]
    for s, side in ((1, "R"), (-1, "L")):
        horn(f"horn_brow_{side}", mirrored_path(brow, s), 5.0)
        horn(f"horn_cheek_{side}", mirrored_path(cheek, s), 4.3)
        emit_ellipsoid(f"socket_{side}", (s * 24, -28, 296), (6.5, 5.5, 4.6), BODY)
        emit_ellipsoid(f"nostril_{side}", (s * 10, -87, 294), (3.2, 4.5, 2.6), BODY)
    add("body_core = union [body_core, horn_brow_R, horn_brow_L, "
        "horn_cheek_R, horn_cheek_L]")
    add("body_core = difference [body_core, socket_R, socket_L, nostril_R, nostril_L]")
    for s, side in ((1, "R"), (-1, "L")):
        emit_ellipsoid(f"eye_{side}", (s * 24.8, -29.5, 296), (3.7, 3.0, 3.0), EYE)
        add(f"color eye_{side} {EYE} rough=0.22")


def build_teeth_and_claws() -> None:
    add("\n# Индивидуальные зубы: верхние и нижние ряды не сливаются в гребёнку.")
    teeth = []

    def upper_gum(x, y):
        # Нижняя поверхность объединения носа и верхней челюсти. Корень
        # заглубляем на 1,5 мм выше неё, а не назначаем всем зубам одну Z.
        surfaces = []
        q = (x / 23.0) ** 2 + ((y + 48.0) / 43.0) ** 2
        if q < 0.995:
            surfaces.append(285.0 - 12.0 * math.sqrt(1.0 - q))
        q = (x / 24.0) ** 2 + ((y + 78.0) / 18.0) ** 2
        if q < 0.995:
            surfaces.append(287.0 - 10.0 * math.sqrt(1.0 - q))
        if not surfaces:
            raise ValueError(f"upper tooth outside gum: {x}, {y}")
        return max(surfaces) + 1.5

    def upper_tooth(name, x, y, tip_z, radius):
        root_z = upper_gum(x, y)
        horn(name, [(x, y, root_z), (x * 1.01, y - 0.8, (root_z + tip_z) * 0.5),
                    (x * 1.03, y - 1.5, tip_z)], radius, BONE)

    for s, side in ((1, "R"), (-1, "L")):
        for i, y in enumerate((-78, -67, -56, -45, -34, -23)):
            x = s * (12.0 + 6.0 * math.sin((i + 1) / 7 * math.pi))
            name = f"tooth_U_{side}_{i}"
            upper_tooth(name, x, y, 259.0 if i in (1, 4) else 264.0, 2.15)
            teeth.append(name)
        for i, y in enumerate((-72, -59, -46, -33)):
            x = s * (10.5 + 5.0 * math.sin((i + 1) / 5 * math.pi))
            q = (x / 19.0) ** 2 + ((y + 44.0) / 40.0) ** 2
            if q >= 0.995:
                raise ValueError(f"lower tooth outside gum: {x}, {y}")
            root_z = 247.0 + 8.0 * math.sqrt(1.0 - q) - 1.5
            tip_z = 266.0 if i == 1 else 263.0
            name = f"tooth_D_{side}_{i}"
            horn(name, [(x, y, root_z), (x, y - 0.5, (root_z + tip_z) * 0.5),
                        (x * 0.98, y - 1.0, tip_z)], 1.9, BONE)
            teeth.append(name)
    for i, x in enumerate((-8, -3, 3, 8)):
        name = f"tooth_front_{i}"
        upper_tooth(name, x, -86, 259.0, 2.0)
        teeth.append(name)
    add("body_core = union [body_core, " + ", ".join(teeth) + "]")

    add("\n# Когти на всех лапах; корни заглублены в пальцы.")
    claws = []
    for s, side in ((1, "R"), (-1, "L")):
        for j, dx in enumerate((-10, 0, 10)):
            x = s * 45 + dx * 1.45
            y = -74 - (3 if j == 1 else 0)
            name = f"claw_H_{side}_{j}"
            horn(name, [(x, y + 2, 35), (x + s * dx * 0.12, y - 7, 33),
                        (x + s * dx * 0.2, y - 13, 27)], 3.3, BONE)
            claws.append(name)
    raised = [(-87.8, -56, 251), (-78.4, -61, 257), (-67.6, -61, 256), (-58.2, -56, 249)]
    for i, tip in enumerate(raised):
        name = f"claw_F_L_{i}"
        root = (tip[0] * 0.985 - 73 * 0.015, tip[1] + 4, tip[2] - 4)
        horn(name, [root, (tip[0], tip[1] - 2, tip[2] + 1),
                    (tip[0] * 1.01, tip[1] - 6, tip[2] - 2)], 2.8, BONE)
        claws.append(name)
    lowered = [(57, -55, 113), (66, -55, 107), (75, -55, 108), (83, -51, 115)]
    for i, tip in enumerate(lowered):
        name = f"claw_F_R_{i}"
        horn(name, [(tip[0], tip[1] + 4, tip[2] + 5),
                    (tip[0], tip[1] - 1, tip[2]),
                    (tip[0], tip[1] - 5, tip[2] - 3)], 2.7, BONE)
        claws.append(name)
    add("body_core = union [body_core, " + ", ".join(claws) + "]")


def build_spines_and_tail_fin() -> None:
    add("\n# Спинной гребень и листовидный наконечник хвоста.")
    spines = []
    for i, (y, z, r) in enumerate(((26, 213, 5.5), (30, 235, 5.2),
                                   (28, 257, 4.7), (22, 279, 4.0))):
        name = f"spine_neck_{i}"
        horn(name, [(0, y - 7, z - 3), (0, y + 10, z + 6),
                    (0, y + 20, z + 22)], r)
        spines.append(name)
    for i, (x, y, z, r) in enumerate(((17, 72, 102, 5.0), (38, 110, 80, 4.5),
                                      (68, 142, 65, 4.0), (99, 157, 70, 3.4),
                                      (126, 151, 94, 2.8))):
        name = f"spine_tail_{i}"
        horn(name, [(x, y - 3, z - 5), (x + 2, y + 5, z + 7),
                    (x + 4, y + 10, z + 18)], r)
        spines.append(name)
    add("body_core = union [body_core, " + ", ".join(spines) + "]")
    add(f"tail_fin = leaf length=54 width=34 thickness=3.2 edge=0.65 "
        f"kind=заостренный curl=0.14 plane=фронт at=[153,128,115] "
        f"color={BODY} rough=0.75")
    add("rotate [tail_fin] angle=-62 axis=y pivot=[128,128,132]")
    add("body_core = union [body_core, tail_fin]")


def build_breast_plates() -> None:
    add("\n# Грудные пластины: широкие, низкие, со стреловидным центральным ритмом.")
    plates = []
    torso_sections = ((15, 33, 105, 46), (5, 31, 151, 58),
                      (0, 35, 194, 48), (-18, 22, 183, 44))
    for i, z in enumerate((205, 192, 179, 166, 153, 140, 127)):
        half = 29 + 5 * math.sin((i + 1) / 8 * math.pi)
        front_candidates = []
        for cy, ry, cz, rz in torso_sections:
            q = ((z - cz) / rz) ** 2
            if q < 1.0:
                front_candidates.append(cy - ry * math.sqrt(1.0 - q))
        front = min(front_candidates)
        # Центральная точка ленты на 0,8 мм внутри тела; боковые кромки
        # остаются рельефными, а нижние ряды больше не висят перед животом.
        y = front + 2.8
        path = [(-half, y + 9, z + 3), (-half * 0.52, y + 1, z),
                (0, y - 2, z - 4), (half * 0.52, y + 1, z), (half, y + 9, z + 3)]
        name = f"breast_{i}"
        emit_sweep(name, path, 0, [0.18, 0.9, 1.0, 0.9, 0.18], sides=20,
                   smooth=4, caps=0.05, width=5.5, height=10.5)
        plates.append(name)
    add("body_core = union [body_core, " + ", ".join(plates) + "]")


def build_scales() -> None:
    add("\n# Чешуя: ray-cast по реальному торсу, отдельные плоские листы.")
    add("# Между пластинами оставлены микрозазоры: нет сцепленных микрополостей.")
    template_terms = [
        sdf_ellipsoid((0, 15, 105), (42, 33, 46)),
        sdf_ellipsoid((0, 5, 151), (38, 31, 58)),
        sdf_ellipsoid((0, 0, 194), (48, 35, 48)),
        sdf_ellipsoid((0, -18, 183), (34, 22, 44)),
    ]
    template_expr = smooth_union(template_terms, 11.0)
    bounds = [-57, -46, 52, 57, 55, 247]
    add(f'scale_bed = from_sdf expression="{template_expr}" bounds={point(bounds)} '
        f'resolution=1.55 color={BODY} rough=0.72')
    # Вычисляем посадку один раз при генерации. В Forma попадают уже все
    # числовые команды: для открытия готового файла Python и референсы не нужны.
    probe = build(f'scale_bed = from_sdf expression="{template_expr}" '
                  f'bounds={point(bounds)} resolution=1.55')
    if not probe.ok:
        raise RuntimeError(f"scale probe: {probe.error}")
    manifold = probe.visible_solids()[0].manifold
    bb = manifold.bounding_box()
    cx, cy = (bb[0] + bb[3]) / 2.0, (bb[1] + bb[4]) / 2.0
    reach = max(bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]) * 2.0 + 10.0
    rows, per_row = 13, 28
    length, width, thick = 12.0, 7.6, 1.1
    step = 14.0
    centre_z = (bb[2] + bb[5]) / 2.0
    bottom = centre_z - (rows - 1) * step / 2.0
    outline = [(-0.22 * width, 0.50 * length), (0.22 * width, 0.50 * length),
               (0.50 * width, 0.10 * length), (0.34 * width, -0.20 * length),
               (0.0, -0.50 * length), (-0.34 * width, -0.20 * length),
               (-0.50 * width, 0.10 * length)]
    tiles = []
    tilt = math.tan(math.radians(12.0))

    def emit_rotation(name, matrix):
        # Кватернион устойчив и при повороте ровно на 180°, где простая
        # antisymmetric-формула оси вырождается в нулевой вектор.
        trace = float(np.trace(matrix))
        if trace > 0.0:
            s = math.sqrt(trace + 1.0) * 2.0
            qw = 0.25 * s
            qv = np.array([(matrix[2, 1] - matrix[1, 2]) / s,
                           (matrix[0, 2] - matrix[2, 0]) / s,
                           (matrix[1, 0] - matrix[0, 1]) / s])
        else:
            index = int(np.argmax(np.diag(matrix)))
            i, j, k = index, (index + 1) % 3, (index + 2) % 3
            s = math.sqrt(max(1e-20, 1.0 + matrix[i, i] - matrix[j, j] - matrix[k, k])) * 2.0
            if index == 0:
                qw = (matrix[2, 1] - matrix[1, 2]) / s
                qv = np.array([0.25 * s, (matrix[0, 1] + matrix[1, 0]) / s,
                               (matrix[0, 2] + matrix[2, 0]) / s])
            elif index == 1:
                qw = (matrix[0, 2] - matrix[2, 0]) / s
                qv = np.array([(matrix[0, 1] + matrix[1, 0]) / s, 0.25 * s,
                               (matrix[1, 2] + matrix[2, 1]) / s])
            else:
                qw = (matrix[1, 0] - matrix[0, 1]) / s
                qv = np.array([(matrix[0, 2] + matrix[2, 0]) / s,
                               (matrix[1, 2] + matrix[2, 1]) / s, 0.25 * s])
        norm = float(np.linalg.norm(qv))
        if norm < 1e-10:
            return
        angle = 2.0 * math.atan2(norm, float(qw))
        axis = qv / norm
        add(f"rotate [{name}] angle={fmt(math.degrees(angle))} axis={point(axis)}")

    for row in range(rows):
        z = bottom + row * step
        for col in range(per_row):
            # Гладкая зона крепления хвоста: эта пластина иначе касается и
            # торса, и корня хвоста, замыкая лишнюю топологическую петлю.
            if row == 5 and col == 7:
                continue
            angle = 2.0 * math.pi * (col + 0.5 * (row % 2) + 0.17) / per_row
            direction = np.array([math.cos(angle), math.sin(angle), 0.0])
            origin = np.array([cx, cy, z])
            hits = manifold.ray_cast(origin.tolist(), (origin + direction * reach).tolist())
            if not hits:
                continue
            hit = max(hits, key=lambda h: float(np.linalg.norm(np.asarray(h.position) - origin)))
            p = np.asarray(hit.position, dtype=float)
            n = np.asarray(hit.normal, dtype=float)
            n /= max(float(np.linalg.norm(n)), 1e-12)
            down = np.array([0.0, 0.0, -1.0])
            down -= n * float(np.dot(down, n))
            if np.linalg.norm(down) < 1e-8:
                down = np.array([-direction[1], direction[0], 0.0])
            down /= max(float(np.linalg.norm(down)), 1e-12)
            y_axis = -down - n * tilt
            y_axis /= max(float(np.linalg.norm(y_axis)), 1e-12)
            z_axis = n - y_axis * float(np.dot(n, y_axis))
            z_axis /= max(float(np.linalg.norm(z_axis)), 1e-12)
            x_axis = np.cross(y_axis, z_axis)
            x_axis /= max(float(np.linalg.norm(x_axis)), 1e-12)
            rotation = np.column_stack((x_axis, y_axis, z_axis))
            name = f"scale_{row:02d}_{col:02d}"
            add(f"{name} = extrude profile={points(outline)} height={fmt(thick)} "
                f"color={BODY} rough=0.76")
            emit_rotation(name, rotation)
            add(f"translate [{name}] offset={point(p - n * 0.4)}")
            tiles.append(name)
    add("scale_bed = union [scale_bed, " + ", ".join(tiles) + "]")
    add("body_core = union [body_core, scale_bed]")


def build_base() -> None:
    add("\n# Круглое основание и связанный каменный рельеф.")
    add(f"plinth = cylinder radius=110 height=12 segments=160 round=2 "
        f"at=[0,20,0] color={BASE} rough=0.86")
    add(f"rock_main = rock size=[190,150,22] seed=33 rough=0.42 points=72 "
        f"at=[0,20,10] color={BASE}")
    add(f"color rock_main {BASE} rough=0.9")
    rocks = ["plinth", "rock_main"]
    for i, (x, y, sx, sy, sz) in enumerate(((-72, -18, 45, 42, 18),
                                            (68, -5, 52, 40, 20),
                                            (-62, 66, 55, 46, 24),
                                            (57, 76, 48, 50, 19),
                                            (0, -48, 65, 38, 15))):
        name = f"rock_{i}"
        add(f"{name} = rock size=[{sx},{sy},{sz}] seed={41 + i} rough=0.48 "
            f"points=40 at=[{x},{y},16] color={BASE}")
        add(f"color {name} {BASE} rough=0.9")
        rocks.append(name)
    add("base = union [" + ", ".join(rocks) + "]")


def generate(stage: str) -> str:
    lines.clear()
    add("# DRAGON SOVEREIGN — параметрическая скульптура по трём референсам.")
    add("# Проектная высота 360 мм; фотограмметрический масштаб не заявляется.")
    add("# Канон: +Z вверх, −Y перед, +X право. Внешние ресурсы не нужны.")
    add("# Пропорции: основание ≈0,61H; крылья ≈1,0H; торс ≈0,36H; голова+шея ≈0,34H.")
    add("scene source=dragon_sovereign_references_33_34_35")
    build_core(stage)
    build_wings()
    build_main_horns()
    if stage == "full":
        build_head_details()
        build_teeth_and_claws()
        build_spines_and_tail_fin()
        build_breast_plates()
        build_scales()
    add("\n# Финальная сварка основных органических переходов.")
    add("dragon = union [body_core, tail_core, wings]")
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
        report["objects"].append({
            "name": solid.name,
            "triangles": int(solid.manifold.num_tri()),
            "components": len(solid.manifold.decompose()),
            "genus": int(solid.manifold.genus()),
            "volume_mm3": float(solid.manifold.volume()),
            "bbox_mm": list(solid.manifold.bounding_box()),
            "status": str(solid.manifold.status()),
            "boundary_edges": int(topology["boundary_edges"]),
            "non_manifold_edges": int(topology["non_manifold_edges"]),
            "degenerate_index": int(topology["degenerate_index"]),
            "degenerate_area": int(topology["degenerate_area"]),
        })
    if render:
        views = ("iso", "front", "right", "back", "top")
        rendered = render_views(solids, RENDER_DIR, prefix=f"dragon_{stage}",
                                size=720, ss=2, views=views, combined=True)
        report["renders"] = rendered
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
