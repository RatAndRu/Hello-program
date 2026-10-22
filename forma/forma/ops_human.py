"""Команда human — анатомический человек математическим полем (SDF)."""

from __future__ import annotations

import time

from .errors import DslError, GeometryError
from .model import Solid
from .ops import op

SKIN_DEFAULT = "#e0b298"
HAIR_DEFAULT = "#2a1d16"
EYE_DEFAULT = "#f2efe8"
IRIS_DEFAULT = "#4a3423"


@op("human", aliases=("человек", "фигура", "humanoid", "person"), category="Математические поверхности",
    summary="Строит анатомическую фигуру человека: рост, пол, телосложение, поза, детализация. "
            "Форма задаётся математически (SDF) и потому остаётся редактируемой.",
    example="человек = human height=1780 sex=м build=спортивный pose=a detail=средний",
    params={"height": "рост в мм (1750)",
            "sex": "пол: м / ж",
            "build": "телосложение: 0.82 худой … 1.0 обычный … 1.12 спортивный … 1.45 полный",
            "pose": "поза: a (руки в стороны), t (полностью в стороны), relaxed (опущены)",
            "detail": "детализация: низкий, средний, высокий",
            "hair": "волосы да/нет", "eyes": "глаза да/нет",
            "muscles": "рельеф мышц да/нет",
            "skin": "цвет кожи #RRGGBB", "hair_color": "цвет волос"})
def human(a, name):
    from .anatomy import DETAIL_ALIASES, DETAILS, Anatomy, HumanParams

    height = float(a.num("height", 1750.0) or 1750.0)
    if not (300.0 <= height <= 3000.0):
        raise DslError("Рост должен быть от 300 до 3000 мм.",
                       line=a.cmd.line, command=a.cmd.text)
    sex = (a.text("sex") or "м").strip().lower()
    if sex in ("female", "woman", "женский", "женщина", "ж", "f"):
        sex = "ж"
    elif sex in ("male", "man", "мужской", "мужчина", "м", "m"):
        sex = "м"
    else:
        raise DslError("Пол: м или ж.", line=a.cmd.line, command=a.cmd.text)

    build_raw = (a.text("build") or "обычный").strip().lower()
    from .anatomy import BUILDS
    if build_raw in BUILDS:
        build = BUILDS[build_raw]
    else:
        try:
            build = float(build_raw.replace(",", "."))
        except ValueError:
            raise DslError(f"Неизвестное телосложение «{build_raw}».",
                           hint="Слова: худой, обычный, спортивный, плотный, полный — "
                                "или число 0.82…1.45", line=a.cmd.line, command=a.cmd.text)
    build = max(0.7, min(1.6, build))

    detail = (a.text("detail") or "средний").strip().lower()
    detail = DETAIL_ALIASES.get(detail, detail)
    if detail not in DETAILS:
        detail = "средний"
    pose = (a.text("pose") or "a").strip().lower()
    if pose not in ("a", "t", "relaxed"):
        pose = "a"

    params = HumanParams(height=height, sex=sex, build=build, pose=pose, detail=detail,
                         hair=a.boolean("hair", True), eyes=a.boolean("eyes", True),
                         muscles=a.boolean("muscles", True))
    t0 = time.perf_counter()
    try:
        result = Anatomy(params).build()
    except GeometryError:
        raise
    except Exception as exc:  # pragma: no cover - защита от редких сбоев
        raise GeometryError(f"Не удалось построить человека: {exc}") from exc
    elapsed = time.perf_counter() - t0

    base_name = name or a.scene.auto_name("человек")
    skin_color = a.text("skin") or SKIN_DEFAULT
    hair_color = a.text("hair_color") or HAIR_DEFAULT
    try:
        from .geometry import normalize_color
        skin_color = normalize_color(skin_color)
        hair_color = normalize_color(hair_color)
    except Exception:
        pass

    solid = Solid(name=base_name, manifold=result["skin"], color=skin_color,
                  metal=0.0, rough=0.55, density=1.0, kind="human", op="human",
                  line=a.cmd.line)
    a.scene.add(solid)
    for extra_name, manifold, kind in result.get("extras", []):
        color = {"hair": hair_color, "eyes": EYE_DEFAULT,
                 "iris": IRIS_DEFAULT, "brows": hair_color}.get(kind, "#cccccc")
        rough = {"hair": 0.42, "eyes": 0.18, "iris": 0.3, "brows": 0.5}.get(kind, 0.5)
        labels = {"hair": "волосы", "eyes": "глаза", "iris": "радужка", "brows": "брови"}
        named = base_name + "_" + labels.get(kind, extra_name)
        a.scene.add(Solid(name=a.scene.unique_name(named), manifold=manifold,
                          color=color, metal=0.0, rough=rough, density=1.0,
                          kind=kind, op="human", line=a.cmd.line))
    a.scene.log("info", f"человек: {height:.0f} мм, {detail}, собрано за {elapsed:.1f} с",
                a.cmd.line)
    return solid
