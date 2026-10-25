"""Лицо крупным планом: аниме-глаз, бровь и губы.

В аниме узнаваемость держится не на черепе, а на трёх вещах: огромный глаз
с толстой линией ресниц, тонкая бровь-дуга и маленький рот. Лепéть это
вручную из сфер и дисков каждый раз — долго и криво, поэтому здесь три
готовых инструмента.

`глаз` собирает пять тел разного цвета: белок, радужку, зрачок, блик и
ресничную линию. Их можно оставить как есть (в окне они уже выглядят
глазом) или сварить с головой через `union`.

    глаз_п = глаз width=46 height=30 at=[38,-58,224] iris=#6f8f76
    бровь_п = бровь width=52 at=[38,-62,258] color=#3a2a24
    губы = губы width=34 at=[0,-44,150]
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import ellipse_profile, normalize_color, sweep_solid
from .ops import anchor, make_solid, op
from .model import Solid


def _solid(scene, name: str, manifold: mf.Manifold, a, base_color: str,
           rough: float = 0.45) -> Solid:
    solid = Solid(name=scene.unique_name(name), manifold=manifold, color=base_color,
                  metal=0.0, rough=rough, density=1.0, kind="face",
                  op=a.spec.name, line=a.cmd.line)
    return scene.add(solid)


def _arc_path(center, width: float, height: float, tilt: float = 0.0,
              steps: int = 17) -> np.ndarray:
    """Дуга в плоскости XZ (лицо смотрит в −Y): изогнутая вверх линия."""
    ts = np.linspace(-1.0, 1.0, steps)
    x = ts * width / 2.0
    z = -height * (1.0 - ts * ts) + tilt * ts * width * 0.12
    return np.stack([center[0] + x,
                     np.full_like(ts, center[1]),
                     center[2] + z], axis=1)


def _almond(width: float, height: float, top: float = 0.62,
            steps: int = 44) -> np.ndarray:
    """Миндалевидный контур глаза: верхняя дуга выше, нижняя положе.

    Уголки сходятся в точки — именно так читается глаз в аниме, а не
    кружок. top — доля высоты, которая приходится на верхнее веко.
    """
    us = np.linspace(-1.0, 1.0, steps)
    k = np.clip(1.0 - us * us, 0.0, 1.0)
    zt = height * top * k ** 0.72
    zb = -height * (1.0 - top) * k ** 1.15
    upper = np.stack([us * width / 2.0, zt], axis=1)
    lower = np.stack([us[::-1] * width / 2.0, zb[::-1]], axis=1)
    return np.concatenate([upper, lower], axis=0)


def _extrude_xz(loop: np.ndarray, depth: float) -> mf.Manifold:
    """Выдавливает контур из плоскости XZ в глубину Y (лицо смотрит в −Y).

    `extrude` растит тело по +Z, поэтому контур поворачивается матрицей:
    локальные (u, w) → (x, z), а глубина h → (y = −h). Так передняя
    поверхность детали оказывается с той стороны, куда смотрит лицо.
    У `Manifold.rotate` углы в градусах — поэтому здесь явная матрица.
    """
    sec = mf.CrossSection([[(float(px), float(pz)) for px, pz in loop]],
                          mf.FillRule.EvenOdd)
    solid = mf.Manifold.extrude(sec, float(depth))
    mat = np.array([[1.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, -1.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0]], dtype=np.float64)
    return solid.transform(mat)


@op("глаз", aliases=("eye", "аниме_глаз", "глаза", "eyes", "взгляд"),
    category="Примитивы",
    summary="Аниме-глаз: миндалевидный белок, большая радужка, зрачок, два блика "
            "и толстая линия ресниц по верхнему веку с утолщением у внешнего "
            "уголка. Пять тел разного цвета — в окне сразу читается взгляд; при "
            "желании их можно сварить с головой через union. lid — насколько "
            "веко нависает (0 — глаз раскрыт широко), tilt — наклон разреза.",
    example="глаз_п = глаз width=46 height=30 at=[38,-52,224] iris=#6f8f76 lash=4.2\n"
            "глаз_л = глаз width=46 height=30 at=[-38,-52,224] iris=#6f8f76 tilt=-0.12",
    params={"width": "ширина глаза, мм (46)",
            "height": "высота раскрытия, мм (30)",
            "at": "центр глаза [x,y,z]; глаз смотрит в −Y",
            "iris": "цвет радужки (#5a7f6b)",
            "sclera": "цвет белка (#fbf8f4)",
            "pupil": "размер зрачка в долях радужки (0.42)",
            "lash": "толщина линии ресниц, мм (3.6)",
            "lid": "нависание века 0…0.6 (0.10)",
            "tilt": "наклон разреза, −1…1 (0.08)",
            "gloss": "два блика в радужке (да)",
            "rim": "тёмная окантовка по всему глазу (да)",
            "depth": "выпуклость глаза в долях ширины (0.5)",
            "color": "цвет ресниц и обводки (#2b2420)"})
def eye(a, name):
    width = float(a.num("width", 46.0, minv=2.0, maxv=400.0))
    height = float(a.num("height", 30.0, minv=1.0, maxv=400.0))
    at = np.asarray(a.vec("at", 3, default=(0.0, 0.0, 0.0)), dtype=np.float64)
    iris_color = normalize_color(a.text("iris") or "#5a7f6b")
    sclera_color = normalize_color(a.text("sclera") or "#fbf8f4")
    lash_color = normalize_color(a.text("color") or "#2b2420")
    pupil_k = float(a.num("pupil", 0.40, minv=0.1, maxv=0.9))
    lash = float(a.num("lash", 3.6, minv=0.0, maxv=40.0))
    lid = float(a.num("lid", 0.10, minv=0.0, maxv=0.6))
    tilt = float(a.num("tilt", 0.08, minv=-1.0, maxv=1.0))
    gloss = a.boolean("gloss", True)
    rim = a.boolean("rim", True)

    rx, rz = width / 2.0, height / 2.0
    # Глубина выпуклости глаза: в аниме глаз — почти наклейка на лице,
    # а не полусфера, торчащая из головы. 0.5 — привычное «чуть выпукло».
    depth_k = float(a.num("depth", 0.5, minv=0.12, maxv=1.0))
    depth = rx * depth_k
    top = 0.62 - lid * 0.35          # нависшее веко делает верхнюю дугу ниже

    # Белок: миндалина, выдавленная в глубину и скруглённая спереди.
    loop = _almond(width, height * (1.0 - lid * 0.5), top)
    ball = _extrude_xz(loop, depth)
    # скругляем: пересекаем с эллипсоидом, у которого передняя часть выпуклая
    dome = mf.Manifold.sphere(1.0, 44).scale((rx * 1.02, depth * 0.92, rz * 1.0))
    ball = ball ^ dome
    if tilt != 0.0:
        ball = ball.rotate((0.0, tilt * 12.0, 0.0))
    ball_shift_z = 0.0
    ball = ball.translate((at[0], at[1] + depth * 0.30, at[2] + ball_shift_z))

    front = at[1] + depth * 0.30 - depth * 0.92   # передняя точка белка
    iris_r = min(width * 0.33, height * 0.50)
    iris = mf.Manifold.cylinder(2.4, iris_r, iris_r, 44, False) \
        .rotate((90.0, 0.0, 0.0)) \
        .translate((at[0], front + 1.4, at[2] - height * 0.02))
    pupil_r = iris_r * pupil_k
    pupil = mf.Manifold.cylinder(2.6, pupil_r, pupil_r, 36, False) \
        .rotate((90.0, 0.0, 0.0)) \
        .translate((at[0], front + 0.4, at[2] - height * 0.02))

    # Радужка и блики не должны вылезать за веки: обрезаем их тем же
    # миндалевидным контуром, что и глаз. Иначе в аниме получается «круг
    # поверх глаза» вместо взгляда из-под ресниц.
    clip = _extrude_xz(loop, depth + 6.0)
    if tilt != 0.0:
        clip = clip.rotate((0.0, tilt * 12.0, 0.0))
    # лоскут выдавливается в −Y: сдвигаем так, чтобы он накрыл радужку по глубине
    clip = clip.translate((at[0], front + 2.6, at[2] + ball_shift_z))
    iris = iris ^ clip
    pupil = pupil ^ clip

    parts = [(ball, name or a.scene.auto_name("глаз"), sclera_color, 0.25),
             (iris, "_радужка", iris_color, 0.3),
             (pupil, "_зрачок", "#14100f", 0.25)]

    rim_w = max(lash * 0.55, 0.35)
    if rim:
        # Тёмная окантовка по всему глазу: в аниме глаз обведён линией, и
        # именно она делает взгляд «нарисованным», а не «шариком в прорези».
        outer = _extrude_xz(_almond(width * 1.02, height * 1.04, top),
                            max(lash * 1.1, 0.6))
        inner = _extrude_xz(_almond(width * 1.02 - rim_w * 2.6,
                                    height * 1.04 - rim_w * 2.0, top),
                            max(lash * 1.1, 0.6) + 2.0)
        ring = outer - inner.translate((0.0, 0.0, -1.0))
        if tilt != 0.0:
            ring = ring.rotate((0.0, tilt * 12.0, 0.0))
        ring = ring.translate((at[0], at[1] + depth * 0.10, at[2]))
        parts.append((ring, "_контур", lash_color, 0.55))
    if gloss:
        glint_r = max(1.2, iris_r * 0.30)
        glint = mf.Manifold.cylinder(1.6, glint_r, glint_r, 24, False) \
            .rotate((90.0, 0.0, 0.0)) \
            .translate((at[0] - iris_r * 0.38, front - 0.1,
                        at[2] + iris_r * 0.34))
        parts.append((glint, "_блик", "#ffffff", 0.1))
        glint2_r = glint_r * 0.42
        glint2 = mf.Manifold.cylinder(1.4, glint2_r, glint2_r, 20, False) \
            .rotate((90.0, 0.0, 0.0)) \
            .translate((at[0] + iris_r * 0.30, front - 0.1,
                        at[2] - iris_r * 0.40))
        glint = glint ^ clip
        glint2 = glint2 ^ clip
        parts.append((glint2, "_блик2", "#ffffff", 0.1))

    if lash > 0.01:
        # Линия ресниц — полумесяц по верхнему веку: к внешнему уголку толще,
        # у внутреннего сходит на нет. Это и есть «аниме».
        us = np.linspace(-1.0, 1.0, 49)
        k = np.clip(1.0 - us * us, 0.0, 1.0)
        zt = height * (1.0 - lid * 0.5) * top * k ** 0.72
        grow = 0.55 + 0.75 * (us * 0.5 + 0.5)        # справа (внешний уголок) толще
        h = lash * grow * k ** 0.35
        outer = np.stack([us * width * 0.512, zt + h * 1.05], axis=1)
        inner = np.stack([us[::-1] * width * 0.505, (zt - h * 0.28)[::-1]], axis=1)
        lash_solid = _extrude_xz(np.concatenate([outer, inner], axis=0),
                                 max(lash * 1.8, 0.6))
        if tilt != 0.0:
            lash_solid = lash_solid.rotate((0.0, tilt * 12.0, 0.0))
        lash_solid = lash_solid.translate((at[0], at[1] + depth * 0.06, at[2]))
        parts.append((lash_solid, "_ресницы", lash_color, 0.55))

    main = None
    for manifold, label, color, rough in parts:
        if label.startswith("_"):
            _solid(a.scene, (name or "глаз") + label, manifold, a, color, rough)
        else:
            main = make_solid(a.scene, label, manifold, a, kind="eye")
            main.color = color
            main.rough = rough
    a.scene.log("info", f"глаз: {width:g}×{height:g} мм — белок, радужка, зрачок"
                        f"{', ресницы' if lash > 0.01 else ''}"
                        f"{', блики' if gloss else ''}", a.cmd.line)
    return main


@op("бровь", aliases=("brow", "брови", "eyebrow"),
    category="Примитивы",
    summary="Бровь-дуга: тонкая полоса с утолщением у основания и остриём к "
            "виску. Выгиб и наклон задаются, поэтому одной командой получается "
            "и спокойное, и удивлённое, и сердитое лицо.",
    example="бровь_п = бровь width=54 at=[38,-60,262] tilt=0.15 arch=8 "
            "color=#3a2a24",
    params={"width": "длина брови, мм (52)",
            "at": "центр брови [x,y,z]",
            "arch": "выгиб вверх, мм (7)",
            "tilt": "наклон, −1…1 (0.1): + внешний край выше",
            "thick": "толщина у корня, мм (2.6)",
            "color": "цвет (#3a2a24)"})
def brow(a, name):
    width = float(a.num("width", 52.0, minv=2.0))
    arch = float(a.num("arch", 7.0, minv=-40.0, maxv=40.0))
    tilt = float(a.num("tilt", 0.1, minv=-1.0, maxv=1.0))
    thick = float(a.num("thick", 2.6, minv=0.2, maxv=20.0))
    color = normalize_color(a.text("color") or "#3a2a24")
    at = np.asarray(a.vec("at", 3, default=(0.0, 0.0, 0.0)), dtype=np.float64)
    path = _arc_path(at, width, arch, tilt, steps=15)
    prof = ellipse_profile(thick, thick * 0.7, 8)
    curve = [0.35, 0.6, 0.85, 1.0, 1.0, 0.96, 0.9, 0.82, 0.72,
             0.6, 0.48, 0.36, 0.26, 0.16, 0.08]
    solid = sweep_solid(path, prof, what="брови",
                        scale_curve=curve[:len(path)], round_caps=1.0)
    made = make_solid(a.scene, name, solid, a, kind="brow")
    made.color = color
    made.rough = 0.55
    return made


@op("губы", aliases=("lips", "рот", "mouth", "губа"),
    category="Примитивы",
    summary="Рот аниме: верхняя губа тоньше нижней, уголки приподняты, между "
            "ними тонкая линия. open задаёт приоткрытость (видно тёмную "
            "полость), smile — насколько уголки вверх. Одно тело, цвет — свой.",
    example="рот = губы width=30 at=[0,-46,152] smile=0.35 open=0.18",
    params={"width": "ширина рта, мм (32)",
            "at": "центр рта [x,y,z]",
            "smile": "уголки вверх, −1…1 (0.25)",
            "open": "приоткрыт, 0…1 (0.15)",
            "thick": "толщина губ, мм (2.2)",
            "color": "цвет губ (#b96a67)"})
def lips(a, name):
    width = float(a.num("width", 32.0, minv=2.0))
    smile = float(a.num("smile", 0.25, minv=-1.0, maxv=1.0))
    open_k = float(a.num("open", 0.15, minv=0.0, maxv=1.0))
    thick = float(a.num("thick", 2.2, minv=0.2, maxv=20.0))
    color = normalize_color(a.text("color") or "#b96a67")
    at = np.asarray(a.vec("at", 3, default=(0.0, 0.0, 0.0)), dtype=np.float64)

    # Профиль рта в плоскости XZ: верхняя дуга (купидон) и нижняя губа
    ts = np.linspace(-1.0, 1.0, 33)
    x = ts * width / 2.0
    upper = -smile * width * 0.10 * (1.0 - ts * ts) + thick * 0.15 * (1.0 - 0.8 * ts * ts)
    lower = -thick * (0.55 + 0.45 * (1.0 - ts * ts)) - open_k * thick * 1.6 * (1.0 - ts * ts)
    loop = np.concatenate([np.stack([x, upper], 1), np.stack([x[::-1], lower[::-1]], 1)])
    prof = loop
    # выдавливаем профиль по Y: губы выступают из лица
    depth = thick * (1.4 + 0.8 * open_k)
    solid = mf.Manifold.extrude(
        mf.CrossSection([[(float(px), float(pz)) for px, pz in prof]], mf.FillRule.EvenOdd),
        depth)
    solid = solid.transform(np.array([[1.0, 0.0, 0.0, at[0]],
                                      [0.0, 0.0, -1.0, at[1]],
                                      [0.0, 1.0, 0.0, at[2]]], dtype=np.float64))
    made = make_solid(a.scene, name, solid, a, kind="lips")
    made.color = color
    made.rough = 0.35
    a.scene.log("info", f"рот: {width:g} мм, приоткрыт на {open_k:g}", a.cmd.line)
    return made
