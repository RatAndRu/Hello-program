"""Реестр команд языка ФОРМА."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Callable

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .model import Scene, Solid


@dataclass
class OpSpec:
    name: str
    fn: Callable
    aliases: tuple[str, ...] = ()
    category: str = "Прочее"
    summary: str = ""
    example: str = ""
    params: dict[str, str] = field(default_factory=dict)
    positional: list[str] | str | None = None

    def help_dict(self) -> dict:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "category": self.category,
            "summary": self.summary,
            "example": self.example,
            "params": [{"name": k, "desc": v} for k, v in self.params.items()],
        }


OPS: dict[str, OpSpec] = {}
ALIASES: dict[str, str] = {}


def op(name: str, aliases: tuple[str, ...] = (), category: str = "Прочее",
       summary: str = "", example: str = "", params: dict[str, str] | None = None,
       positional: list[str] | str | None = None):
    def deco(fn: Callable):
        spec = OpSpec(name=name, fn=fn, aliases=aliases, category=category, summary=summary,
                      example=example, params=dict(params or {}), positional=positional)
        OPS[name] = spec
        ALIASES[name] = name
        for al in aliases:
            ALIASES[al.lower()] = name
        fn.op_spec = spec
        return fn
    return deco


def lookup(verb: str) -> OpSpec | None:
    return OPS.get(ALIASES.get((verb or "").lower(), (verb or "").lower()))


def suggest(verb: str) -> list[str]:
    return difflib.get_close_matches((verb or "").lower(), list(ALIASES), n=3, cutoff=0.5)


def help_list() -> list[dict]:
    order = ["Примитивы", "Тела вращения и развёртки", "Булевы операции",
             "Форма и деформации", "Массивы и преобразования", "Математические поверхности",
             "Сцена и материал", "Проверка"]
    specs = sorted(OPS.values(), key=lambda s: (order.index(s.category)
                                                if s.category in order else 99, s.name))
    return [s.help_dict() for s in specs]


# --------------------------------------------------------------------------- #
#  Общие преобразования и создание объектов
# --------------------------------------------------------------------------- #

def translation_matrix(offset) -> np.ndarray:
    m = np.eye(3, 4, dtype=np.float64)
    m[:, 3] = np.asarray(offset, dtype=np.float64)
    return m


def rotation_matrix(angle_deg: float, axis, pivot=(0.0, 0.0, 0.0)) -> np.ndarray:
    ax = np.asarray(axis, dtype=np.float64)
    norm = np.linalg.norm(ax)
    if norm < 1e-12:
        raise GeometryError("Ось поворота не может быть нулевой.")
    ax = ax / norm
    a = np.radians(angle_deg)
    c, s = np.cos(a), np.sin(a)
    x, y, z = ax
    r = np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ], dtype=np.float64)
    p = np.asarray(pivot, dtype=np.float64)
    mat = np.eye(3, 4, dtype=np.float64)
    mat[:, :3] = r
    mat[:, 3] = p - r @ p
    return mat


def affine(m: mf.Manifold, matrix: np.ndarray) -> mf.Manifold:
    return m.transform(np.ascontiguousarray(matrix, dtype=np.float64))


def translate(m: mf.Manifold, offset) -> mf.Manifold:
    off = np.asarray(offset, dtype=np.float64)
    if not np.any(np.abs(off) > 1e-12):
        return m
    return affine(m, translation_matrix(off))


def rotate(m: mf.Manifold, angle_deg: float, axis, pivot=(0.0, 0.0, 0.0)) -> mf.Manifold:
    if abs(angle_deg) < 1e-12:
        return m
    return affine(m, rotation_matrix(angle_deg, axis, pivot))


def scale(m: mf.Manifold, factors, pivot=(0.0, 0.0, 0.0)) -> mf.Manifold:
    f = np.asarray(factors, dtype=np.float64)
    if np.any(f <= 0):
        raise GeometryError("Масштаб должен быть положительным.")
    mat = np.eye(3, 4, dtype=np.float64)
    mat[0, 0], mat[1, 1], mat[2, 2] = f
    p = np.asarray(pivot, dtype=np.float64)
    mat[:, 3] = p - f * p
    return affine(m, mat)


def mirror(m: mf.Manifold, axis: str = "x", plane_at: float = 0.0) -> mf.Manifold:
    normal = {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "z": [0.0, 0.0, 1.0]}.get(axis)
    if normal is None:
        raise GeometryError("Плоскость зеркала должна быть x, y или z.")
    out = m.mirror(normal)
    if abs(plane_at) > 1e-12:
        out = translate(out, [2 * plane_at if axis == "x" else 0,
                              2 * plane_at if axis == "y" else 0,
                              2 * plane_at if axis == "z" else 0])
    return out


def anchor(m: mf.Manifold, at=None, center: bool = False) -> mf.Manifold:
    """Ставит объект: по умолчанию — центр по XY и низ на z=0."""
    target = np.asarray(at if at is not None else (0.0, 0.0, 0.0), dtype=np.float64)
    bb = m.bounding_box()
    cx = (bb[0] + bb[3]) / 2
    cy = (bb[1] + bb[4]) / 2
    cz = (bb[2] + bb[5]) / 2
    if center:
        tx, ty, tz = target
    else:
        tx, ty, tz = target[0], target[1], target[2] + (bb[5] - bb[2]) / 2
    return translate(m, (tx - cx, ty - cy, tz - cz))


def ensure_solid(m: mf.Manifold | None, what: str = "объект") -> mf.Manifold:
    if m is None or not isinstance(m, mf.Manifold):
        raise GeometryError(f"Не удалось построить {what}.")
    if m.is_empty():
        raise GeometryError(
            f"{what.capitalize()} пустая.",
            hint="Проверьте размеры: возможно, вычитание удалило всю форму.",
        )
    if m.volume() <= 0:
        raise GeometryError(f"{what.capitalize()} имеет нулевой объём.")
    return m


def make_solid(scene: Scene, name: str | None, manifold: mf.Manifold, args,
               base: Solid | None = None, kind: str | None = None) -> Solid:
    manifold = ensure_solid(manifold, "фигура")
    style = args.style()
    color = style.get("color") or (base.color if base else None) or scene.next_color()
    metal = style.get("metal", base.metal if base else 0.0)
    rough = style.get("rough", base.rough if base else 0.5)
    density = style.get("density", base.density if base else 1.24)
    emissive = style.get("emissive", base.emissive if base else "") or ""
    glow = float(style.get("emissive_strength", base.emissive_strength if base else 1.0))
    transmission = float(style.get("transmission", base.transmission if base else 0.0))
    visible = style.get("visible", True)
    mirror = bool(style.get("mirror", base.mirror if base else False))
    solid_name = name or scene.auto_name(kind or args.spec.name)
    solid = Solid(name=solid_name, manifold=manifold, color=color, metal=float(metal),
                  rough=float(rough), density=float(density), visible=bool(visible),
                  emissive=emissive, emissive_strength=glow, transmission=transmission,
                  mirror=mirror,
                  kind=kind or args.spec.name, op=args.spec.name, line=args.cmd.line)
    return scene.add(solid)


def merge_solids(solids: list[Solid], op_type: mf.OpType = mf.OpType.Add) -> mf.Manifold:
    if len(solids) == 1:
        return solids[0].manifold
    return mf.Manifold.batch_boolean([s.manifold for s in solids], op_type)
