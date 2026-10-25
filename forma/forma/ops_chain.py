"""Цепи: готовое звено-кольцо и соединение готовых деталей цепью.

Цепь — редкая вещь, которую не собрать из примитивов «на глаз»: звенья
должны быть зацеплены, а не нанизаны, и повёрнуты друг к другу на 90°.
Поэтому здесь два инструмента:

* `цепь` — сразу цепочка из N звеньев вдоль направления: серьга, поводок,
  стропа, цепь на ворота;
* `соединить` — цепь между двумя **готовыми** деталями: находит, где они
  ближе всего друг к другу (или берёт from/to), вешает цепь с провисом и
  подбирает число звеньев по расстоянию. Это ответ на «свяжи две вещи»,
  когда склейка не нужна.

    цепь links=8 size=26 wire=4 at=[0,0,60] dir=[1,0,0]
    соединить [крюк, ведро] size=16 wire=2.4 sag=0.18
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import circle_profile, sweep_solid
from .ops import make_solid, op


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64).reshape(3)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        raise GeometryError("Нулевое направление.",
                            hint="Задайте другое направление (dir).")
    return v / n


def _link(length: float, width: float, wire: float, seg: int = 18,
          minor: int = 12) -> mf.Manifold:
    """Звено цепи — вытянутое кольцо (стадион), а не круг.

    Круглые кольца не сцепляются: у них сосед просто проходит рядом, а не
    сквозь отверстие. У вытянутого звена соседнее звено, повёрнутое на 90°,
    проходит как раз через его проушину — как у настоящей цепи.
    """
    lc = max(length - wire, wire * 1.2)          # осевая линия по длине
    wc = max(width - wire, wire * 0.9)           # осевая линия по ширине
    half = max(lc - wc, 0.01) * 0.5
    rad = wc * 0.5
    pts = []
    steps = max(8, seg // 2)
    for i in range(steps + 1):                    # правый полукруг
        a = -math.pi / 2 + math.pi * i / steps
        pts.append((half + rad * math.cos(a), rad * math.sin(a)))
    for i in range(steps + 1):                    # левый полукруг
        a = math.pi / 2 + math.pi * i / steps
        pts.append((-half + rad * math.cos(a), rad * math.sin(a)))
    path = np.asarray([[x, y, 0.0] for x, y in pts[:-1]], dtype=np.float64)
    prof = circle_profile(max(wire * 0.5, 0.1), minor)
    return sweep_solid(path, prof, closed_path=True, what="звена",
                       round_caps=0.0)


def _placed(link: mf.Manifold, center, x_axis, z_axis) -> mf.Manifold:
    """Ставит звено так, что его плоскость содержит x_axis, а ось — z_axis."""
    x = _unit(x_axis)
    z = np.asarray(z_axis, dtype=np.float64).reshape(3)
    z = z - x * float(np.dot(z, x))
    if float(np.linalg.norm(z)) < 1e-7:
        z = np.cross(x, np.array([0.0, 0.0, 1.0]))
        if float(np.linalg.norm(z)) < 1e-7:
            z = np.cross(x, np.array([1.0, 0.0, 0.0]))
    z = _unit(z)
    y = np.cross(z, x)
    matrix = np.hstack([np.stack([x, y, z], axis=1),
                        np.asarray(center, dtype=np.float64).reshape(3, 1)])
    return link.transform(np.ascontiguousarray(matrix, dtype=np.float64))


def _chain(points: np.ndarray, size: float, width: float, wire: float,
           pitch: float | None, ref_up) -> mf.Manifold:
    """Звенья вдоль ломаной: шаг по длине дуги, поворот на 90° друг к другу."""
    pitch = float(pitch) if pitch else (size - wire) * 0.62
    pitch = max(pitch, wire * 2.0)
    seg = points[1:] - points[:-1]
    seg_len = np.linalg.norm(seg, axis=1)
    total = float(seg_len.sum())
    if total < 1e-6:
        raise GeometryError("Длина цепи нулевая.", hint="Разведите точки.")
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    count = int(max(2, min(400, math.floor(total / pitch) + 1)))
    base_link = _link(size, width, wire, seg=18,
                      minor=max(8, int(18 * wire / max(size, 1e-3)) + 7))

    ref = np.asarray(ref_up, dtype=np.float64).reshape(3)
    links = []
    for i in range(count):
        s = i * pitch
        j = int(np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(seg) - 1))
        t = (s - cum[j]) / max(seg_len[j], 1e-9)
        t = float(np.clip(t, 0.0, 1.0))
        center = points[j] + seg[j] * t
        tangent = seg[j] / max(seg_len[j], 1e-9)
        axis = ref - tangent * float(np.dot(ref, tangent))
        if float(np.linalg.norm(axis)) < 0.2 * float(np.linalg.norm(ref)):
            axis = np.cross(tangent, np.array([1.0, 0.0, 0.0]))
        axis = _unit(axis)
        # соседние звенья повёрнуты на 90°: ось вращается вокруг касательной
        ang = (math.pi / 2.0) * i
        c, s_ = math.cos(ang), math.sin(ang)
        axis = _unit(axis * c + np.cross(tangent, axis) * s_)
        links.append(_placed(base_link, center, tangent, axis))
    return mf.Manifold.batch_boolean(links, mf.OpType.Add)


@op("цепь", aliases=("chain", "цепочка", "звенья", "цепь_звеньев"),
    category="Примитивы",
    summary="Цепь из звеньев: кольца зацеплены друг за друга и повёрнуты на 90°, "
            "поэтому это настоящая цепь, а не ряд колец рядом. Задаются размер "
            "звена, толщина прутка, число звеньев и направление.",
    example="цепь links=8 size=26 wire=4 at=[0,0,80] dir=[1,0,0]\n"
            "подвес = цепь links=14 size=18 wire=3 at=[0,0,120] dir=[0,0,-1]\n"
            "цепь links=6 size=30 wire=5 at=[0,0,40] dir=[1,0,0.4] metal=0.9",
    params={"links": "сколько звеньев (8)",
            "size": "длина звена, мм (24)",
            "width": "ширина звена, мм (0.58·size)",
            "wire": "толщина прутка, мм (3)",
            "pitch": "шаг между звеньями, мм (само: 0.62·size)",
            "at": "начало цепи [x,y,z] (0,0,0)",
            "dir": "направление цепи [x,y,z] (1,0,0)",
            "metal": "металличность 0…1 (0.75)"})
def chain(a, name):
    links = int(a.num("links", 8, minv=1, maxv=400))
    size = float(a.num("size", 24.0, minv=1.0, maxv=2000.0))
    width = float(a.num("width", size * 0.58, minv=size * 0.2, maxv=size))
    wire = float(a.num("wire", 3.0, minv=0.2, maxv=width * 0.5))
    pitch = a.num("pitch", None, minv=0.2)
    at = np.asarray(a.vec("at", 3, default=(0.0, 0.0, 0.0)), dtype=np.float64).reshape(3)
    direction = _unit(a.vec("dir", 3, default=(1.0, 0.0, 0.0)))
    step = float(pitch) if pitch else (size - wire) * 0.62
    points = np.stack([at, at + direction * (step * (links - 1) + size * 0.5)], axis=0)
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(ref, direction))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    solid = _chain(points, size, width, wire, step, ref)
    made = make_solid(a.scene, name, solid, a, kind="chain")
    made.metal = float(a.num("metal", 0.75, minv=0.0, maxv=1.0))
    made.rough = 0.35
    a.scene.log("info", f"цепь: {links} звеньев, {size:g} мм", a.cmd.line)
    return made


def _facing_points(solid_a, solid_b) -> tuple[np.ndarray, np.ndarray]:
    """Ближайшие друг к другу точки габаритов двух деталей."""
    ba = np.array(solid_a.manifold.bounding_box(), dtype=np.float64)
    bb = np.array(solid_b.manifold.bounding_box(), dtype=np.float64)
    ca = np.array([(ba[i] + ba[i + 3]) * 0.5 for i in range(3)])
    cb = np.array([(bb[i] + bb[i + 3]) * 0.5 for i in range(3)])
    ha = np.array([(ba[i + 3] - ba[i]) * 0.5 for i in range(3)])
    hb = np.array([(bb[i + 3] - bb[i]) * 0.5 for i in range(3)])
    d = cb - ca
    n = float(np.linalg.norm(d))
    if n < 1e-9:
        d, n = np.array([0.0, 0.0, 1.0]), 1.0
    d = d / n
    ra = float(np.sum(np.abs(d) * ha))
    rb = float(np.sum(np.abs(d) * hb))
    return ca + d * ra, cb - d * rb


@op("соединить", aliases=("chain_between", "связать_цепью", "прицепить",
                          "соединить_цепью", "подвесить"),
    category="Сборка",
    summary="Соединяет две готовые детали цепью: берёт ближайшие точки (или "
            "заданные from и to), вешает цепь с провисом, число звеньев "
            "подбирает по расстоянию. Когда склейка не нужна — это честное "
            "соединение: деталь висит на цепи.",
    example="крюк = torus major=20 minor=4 at=[0,0,200]\n"
            "ведро = cylinder radius=34 height=60 at=[0,0,40]\n"
            "соединить [крюк, ведро] size=16 wire=2.4 sag=0.15\n"
            "плита = box size=[120,60,10]\n"
            "лампа = sphere radius=20 at=[0,0,-80]\n"
            "соединить [плита, лампа] size=10 wire=1.6 links=9",
    params={"objects": "две детали [a, b]",
            "size": "длина звена, мм (18)",
            "width": "ширина звена, мм (0.58·size)",
            "wire": "толщина прутка, мм (2.6)",
            "links": "сколько звеньев (0 — подобрать по длине)",
            "sag": "провис 0…1 от длины (0.15)",
            "from": "начало цепи [x,y,z] (ближайшая точка первой детали)",
            "to": "конец цепи [x,y,z] (ближайшая точка второй)",
            "metal": "металличность 0…1 (0.75)"},
    positional=["objects"])
def chain_between(a, name):
    solids = a.solids()
    if len(solids) != 2:
        raise GeometryError("соединить ждёт ровно две детали.",
                            hint="Формат: connect = соединить [крюк, ведро] …")
    size = float(a.num("size", 18.0, minv=1.0, maxv=400.0))
    width = float(a.num("width", size * 0.58, minv=size * 0.2, maxv=size))
    wire = float(a.num("wire", 2.6, minv=0.2, maxv=width * 0.5))
    sag = float(a.num("sag", 0.15, minv=-1.0, maxv=1.0))
    links = int(a.num("links", 0, minv=0, maxv=400))
    pa, pb = _facing_points(solids[0], solids[1])
    from_p = a.vec("from", 3, default=None)
    to_p = a.vec("to", 3, default=None)
    if from_p is not None:
        pa = np.asarray(from_p, dtype=np.float64).reshape(3)
    if to_p is not None:
        pb = np.asarray(to_p, dtype=np.float64).reshape(3)

    # точка подвеса: чуть выше середины, провис — вниз
    mid = (pa + pb) * 0.5
    length = float(np.linalg.norm(pb - pa))
    mid = mid - np.array([0.0, 0.0, sag * max(length, 1.0) * 0.5])
    ts = np.linspace(0.0, 1.0, 9)
    path = ((1.0 - ts) ** 2)[:, None] * pa[None, :] \
        + (2.0 * (1.0 - ts) * ts)[:, None] * mid[None, :] \
        + (ts ** 2)[:, None] * pb[None, :]

    pitch = None
    if links > 1:
        pitch = max(float(np.linalg.norm(path[-1] - path[0])) / (links - 0.5),
                    wire * 2.0)
    ref = np.array([0.0, 0.0, 1.0])
    solid = _chain(path, size, width, wire, pitch, ref)
    made = make_solid(a.scene, name, solid, a, kind="chain")
    made.metal = float(a.num("metal", 0.75, minv=0.0, maxv=1.0))
    made.rough = 0.35
    a.scene.log("info",
                f"соединить: цепь {length:.0f} мм между «{solids[0].name}» "
                f"и «{solids[1].name}»", a.cmd.line)
    return made
