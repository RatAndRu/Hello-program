"""Лофт по трём осям: сечения (u, v) вдоль x, y и z.

Регрессия: для `axis=y` отображение (u, v, w) → (x, y, z) меняет ориентацию,
и без разворота обхода треугольников ядро считало тело вывернутым наизнанку —
лофт получался пустым («Лофт получилась пустой»).
"""
from __future__ import annotations

import pytest

from forma.run import build


SQUARE = "[[0,0],[100,0],[100,100],[0,100]]"
SMALL = "[[0,0],[90,0],[90,90],[0,90]]"


@pytest.mark.parametrize("axis,size", [
    ("z", (100.0, 100.0, 20.0)),
    ("x", (20.0, 100.0, 100.0)),
    ("y", (100.0, 20.0, 100.0)),
])
def test_loft_along_each_axis(axis, size):
    script = (f"a = loft sections=[{SQUARE},{SMALL}] positions=[0,20] axis={axis} caps=1\n"
              "check a watertight\n")
    result = build(script)
    assert result.ok, result.error
    assert result.analysis["checks_passed"] == result.analysis["checks_total"] == 1
    assert [round(v, 3) for v in result.analysis["metrics"]["size"]] == list(size)


def test_loft_axis_y_is_not_mirrored():
    """Ось Y не должна ни разворачивать деталь, ни сдвигать её по глубине."""
    script = (f"a = loft sections=[{SQUARE},{SMALL}] positions=[10,30] axis=y caps=1\n")
    result = build(script)
    assert result.ok, result.error
    bbox = result.analysis["metrics"]["bbox"]
    assert bbox[1] == pytest.approx(10.0, abs=1e-6)     # низ по Y
    assert bbox[4] == pytest.approx(30.0, abs=1e-6)     # верх по Y
