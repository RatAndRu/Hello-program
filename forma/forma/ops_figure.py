"""Готовые изделия с несколькими материалами: зеркало в раме."""

from __future__ import annotations

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import ellipse_profile
from .ops import PLANE_FLAT, PLANE_FRONT, make_solid, op, stand_flat_sign
from .ops_shapes import _cross, ensure_volume


def _anchor_all(a, parts: list[mf.Manifold]) -> list[mf.Manifold]:
    """Ставит сборку целиком, не разъединяя раму и отражающую пластину."""
    at = np.asarray(a.vec("at", 3, default=(0.0, 0.0, 0.0)), dtype=np.float64)
    bb = parts[0].bounding_box()
    cx, cy, cz = (bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2, (bb[2] + bb[5]) / 2
    if a.boolean("center", False):
        tx, ty, tz = at
    else:
        tx, ty, tz = at[0], at[1], at[2] + (bb[5] - bb[2]) / 2
    d = (float(tx - cx), float(ty - cy), float(tz - cz))
    return [p.translate(d) for p in parts]


def _extra(a, base_name: str, suffix: str, m: mf.Manifold, kind: str, *,
           color: str, metal: float = 0.0, rough: float = 0.5,
           emissive: str = "", glow: float = 1.0, transmission: float = 0.0,
           mirror: bool = False):
    """Добавляет часть изделия с самостоятельным материалом."""
    from .model import Solid
    solid = Solid(name=f"{base_name}.{suffix}", manifold=m, color=color, metal=metal,
                  rough=rough, emissive=emissive, emissive_strength=glow,
                  transmission=transmission, mirror=mirror, kind=kind,
                  op=a.spec.name, line=a.cmd.line)
    base = a.scene.get(base_name)
    if base is not None:
        solid.meta["axes"] = [list(row) for row in
                              (base.meta.get("axes") or np.eye(3).tolist())]
    return a.scene.add(solid)


@op("mirror_plate", aliases=("зеркальная_плита", "зеркало_изделие", "mirror_glass"),
    category="Примитивы",
    summary="Зеркало целиком: рама, отражающая пластина и задник с креплением. "
            "Пластина получает материал mirror (metal=1, rough=0.02) и "
            "отражает соседние детали — и в окне, и на PNG-снимке. Форма "
            "рамы — прямоугольная, круглая или овальная.",
    example="зеркало = mirror_plate width=600 height=900 frame=40\n"
            "круглое = mirror_plate width=500 height=500 shape=круг frame=30",
    params={"width": "ширина, мм (600)", "height": "высота, мм (900)",
            "frame": "ширина рамы, мм (35)",
            "depth": "толщина, мм (24)",
            "shape": "прямоуг, круг или овал — «прямоуг»",
            "plane": "фронт — зеркало стоит лицом к зрителю, плашмя — лежит — «фронт»",
            "at": "положение [x,y,z]", "center": "центрировать по высоте"},
    positional=["width", "height"])
def mirror_plate(a, name):
    width = float(a.num("width", 600.0, minv=20.0))
    height = float(a.num("height", 900.0, minv=20.0))
    frame = float(a.num("frame", 35.0, minv=2.0))
    depth = float(a.num("depth", 24.0, minv=3.0))
    shape = (a.text("shape") or "прямоуг").strip().lower()
    if shape in ("круг", "круглое", "round"):
        shape = "круг"
    elif shape in ("овал", "ellipse", "овальное"):
        shape = "овал"
    else:
        shape = "прямоуг"
    plane = (a.text("plane") or "фронт").strip().lower()
    if plane not in PLANE_FRONT + PLANE_FLAT:
        raise GeometryError("mirror_plate: plane=фронт или плашмя.")
    if frame * 2 >= min(width, height) * 0.8:
        raise GeometryError("Рама съела всё зеркало.", hint="frame ≤ 0.3 × меньшей стороны.")
    if shape == "круг":
        d = min(width, height)
        outer_prof = ellipse_profile(d, d, 96)
        inner_prof = ellipse_profile(d - 2 * frame, d - 2 * frame, 96)
    elif shape == "овал":
        outer_prof = ellipse_profile(width, height, 96)
        inner_prof = ellipse_profile(width - 2 * frame, height - 2 * frame, 96)
    else:
        outer_prof = np.array([(-width / 2, -height / 2), (width / 2, -height / 2),
                               (width / 2, height / 2), (-width / 2, height / 2)])
        inner_prof = np.array([(-width / 2 + frame, -height / 2 + frame),
                               (width / 2 - frame, -height / 2 + frame),
                               (width / 2 - frame, height / 2 - frame),
                               (-width / 2 + frame, height / 2 - frame)])
    outer = _cross([tuple(p) for p in outer_prof])
    inner = _cross([tuple(p) for p in inner_prof])
    rim = outer.extrude(depth) - inner.extrude(depth * 1.2).translate((0, 0, -depth * 0.1))
    back = outer.extrude(depth * 0.12)
    hanger = mf.Manifold.cube([min(60.0, width * 0.2), 8.0, depth * 0.7], True).translate(
        (0.0, height * 0.32, depth * 0.05))
    body = mf.Manifold.batch_boolean([rim, back, hanger], mf.OpType.Add)
    body = ensure_volume(body, "рамы зеркала")
    body = stand_flat_sign(a, body)
    plate = inner.offset(0.6, mf.JoinType.Round, 1.0, 8).extrude(max(1.2, depth * 0.08))
    plate = plate.translate((0, 0, depth * 0.55))
    plate = ensure_volume(plate, "зеркальной пластины")
    plate = stand_flat_sign(a, plate)
    placed = _anchor_all(a, [body, plate])
    main = make_solid(a.scene, name, placed[0], a, kind="mirror_plate")
    _extra(a, main.name, "зеркало", placed[1], "mirror",
           color="#e8f1fb", metal=1.0, rough=0.02, mirror=True)
    a.scene.log("info", f"зеркало: {width:g}×{height:g} мм, рама {frame:g} мм, "
                        f"{body.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return main
