"""Пространственный паспорт — факты, ограничения, отсутствие изменения проекта."""
import hashlib
import json
import zipfile

import pytest

from forma.errors import FormaError
from forma.run import build
from forma.spatial_passport import create_passport, passport_markdown
from forma.webui import AppState


SCRIPT = "a = box size=[20,30,40] at=[0,0,0]\nb = box size=[20,30,40] at=[40,0,0]\n"


def scene(script=SCRIPT):
    result = build(script, analyze_model=False)
    assert result.ok, result.error
    return result.scene


def test_coordinates_relations_and_center_slices():
    s = scene()
    doc = create_passport(s, SCRIPT)
    assert doc["source_sha256_utf8"] == hashlib.sha256(SCRIPT.encode()).hexdigest()
    assert doc["orientation"] == {"up": "+Z", "down": "-Z", "right": "+X", "front": "-Y"}
    a = doc["facts"]["objects"][0]
    assert a["bbox_mm"] == [-10, -15, 0, 10, 15, 40]
    assert a["size_mm"] == [20, 30, 40]
    assert a["bbox_center_mm"] == [0, 0, 20]
    assert a["volume_mm3"] == 24000
    pair = doc["facts"]["bbox_relations"]["pairs"][0]
    assert pair["axes"]["x"]["b_relative_to_a"] == "positive"
    assert pair["axes"]["x"]["bbox_gap_mm"] == 20
    assert pair["bbox_distance_lower_bound_mm"] == 20
    assert "не проверены" in pair["note"]
    cuts = [x for x in doc["facts"]["sections"] if x["object"] == "a"]
    assert [(x["axis"], x["area_mm2"]) for x in cuts] == [("x", 1200), ("y", 800), ("z", 600)]
    assert all(x["status"] == "ok" for x in cuts)
    assert doc["hypotheses"] == []
    assert "не доказывает" in " ".join(doc["limitations"])
    assert "Пространственный паспорт" in passport_markdown(doc)
    json.dumps(doc, allow_nan=False)


def test_detailed_slices_and_hole_are_not_3d_claims():
    script = ("outer = cylinder radius=20 height=40 segments=32\n"
              "hole = cylinder radius=5 height=40 segments=32\n"
              "ring = difference [outer,hole]\n")
    d = create_passport(scene(script), script, mode="detail")
    z_slices = [s for s in d["facts"]["sections"] if s["object"] == "ring" and s["axis"] == "z"]
    assert len(z_slices) == 3
    assert all(s["status"] == "ok" and s["negative_contours_in_slice"] == 1 for s in z_slices)
    assert all(s["contour_count"] == 2 for s in z_slices)
    assert "не доказывают отсутствие отверстий" in " ".join(d["limitations"])
    assert "hole" not in [obj["name"] for obj in d["facts"]["objects"]]


def test_explicit_limits_and_hidden_objects():
    script = "\n".join(f"obj{i} = box size=[1,2,3] at=[{i*3},0,0]" for i in range(18)) + "\nhide obj17\n"
    d = create_passport(scene(script), script, "fast")
    assert len(d["facts"]["objects"]) == 17
    assert len(d["facts"]["sections"]) == 8 * 3
    assert len(d["facts"]["sections_skipped_objects"]) == 9
    assert d["facts"]["bbox_relations"]["total_possible"] == 17 * 16 // 2
    assert all(x["reason"] for x in d["facts"]["sections_skipped_objects"])
    with pytest.raises(FormaError):
        create_passport(scene(), SCRIPT, "other")


def test_export_is_a_snapshot_and_does_not_change_scene(tmp_path, monkeypatch):
    monkeypatch.setenv("FORMA_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("FORMA_DOWNLOADS", str(tmp_path / "downloads"))
    app = AppState()
    app.last_build = build(SCRIPT, analyze_model=False)
    app.last_script = SCRIPT
    before = [s.manifold.bounding_box() for s in app.last_build.visible_solids()]
    for fmt, count in (("passport-fast", 6), ("passport-detail", 18)):
        response = app.export(fmt)
        path = tmp_path / "data" / "exports" / response["name"]
        with zipfile.ZipFile(path) as zf:
            assert set(zf.namelist()) == {"passport.json", "ПАСПОРТ.md", "source.forma"}
            assert zf.read("source.forma").decode() == SCRIPT
            doc = json.loads(zf.read("passport.json"))
            assert len(doc["facts"]["sections"]) == count
            assert "Ограничения" in zf.read("ПАСПОРТ.md").decode()
    assert [s.manifold.bounding_box() for s in app.last_build.visible_solids()] == before
    assert app.last_script == SCRIPT
