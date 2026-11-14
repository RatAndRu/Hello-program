"""Проверяем готовые примеры росписи как сценарии и окрашенные GLB."""
from pathlib import Path

import manifold3d as mf
import numpy as np
import pytest

from forma.geometry import _glb_read
from forma.run import build


EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize(
    "filename,min_colors",
    [("vase_patterns_demo.forma", 6), ("vase_flower_demo.forma", 2)],
)
def test_painted_vases_export_with_vertex_colors(filename, min_colors):
    script = (EXAMPLES / filename).read_text(encoding="utf-8")
    result = build(script, analyze_model=False)
    assert result.ok, result.error
    solids = result.visible_solids()
    assert len(solids) == 1
    solid = solids[0]
    assert solid.manifold.status() == mf.Error.NoError
    assert solid.manifold.volume() > 0
    assert 0 < solid.manifold.num_tri() <= 100_000

    doc, binary = _glb_read(result.export_glb())
    prim = doc["meshes"][0]["primitives"][0]
    attributes = prim["attributes"]
    assert "COLOR_0" in attributes
    colors = doc["accessors"][attributes["COLOR_0"]]
    assert colors["count"] == doc["accessors"][attributes["POSITION"]]["count"]
    assert colors["componentType"] == 5121 and colors["type"] == "VEC4"
    view = doc["bufferViews"][colors["bufferView"]]
    assert view.get("byteStride", 4) == 4
    offset = view.get("byteOffset", 0) + colors.get("byteOffset", 0)
    data = np.frombuffer(binary, dtype=np.uint8, count=colors["count"] * 4,
                         offset=offset).reshape((-1, 4))
    assert len(np.unique(data, axis=0)) >= min_colors
