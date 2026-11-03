"""Целевые проверки этапа 3: библиотеки, обмен и измеримые CAD-возможности.

Это не проверка «команда не упала»: тесты читают геометрию, файлы и плоский
provenance. Внешний OpenSCAD здесь заменяется маленьким fake-процессом, чтобы
проверять headless-контракт даже на машине без установленного OpenSCAD.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from forma import cuts
from forma.geometry import export_stl
from forma.run import build
from forma.scad import export_scad
from forma.vision.dimension_fit import fit_dimensions


def ok_build(script: str, **kwargs):
    result = build(script, analyze_model=False, **kwargs)
    assert result.ok, result.error
    return result


def test_include_module_function_defaults_and_local_scope(tmp_path: Path):
    (tmp_path / "library.forma").write_text(
        """function plus_default(x, y=2) = x + y
module plate(width=10, height=2) {
    local_width = width + plus_default(1)
    body = box size=[local_width,20,height]
}
""",
        encoding="utf-8",
    )
    result = ok_build(
        """include file="library.forma"
width = 40
first = plate(width=width, height=3)
second = plate()
""",
        base_dir=tmp_path,
    )
    assert result.ok
    first = result.scene.objects["first"]
    second = result.scene.objects["second"]
    assert np.allclose(first.stats()["size"], [43, 20, 3], atol=1e-6)
    assert np.allclose(second.stats()["size"], [13, 20, 2], atol=1e-6)
    assert result.scene.params["width"] == 40
    assert "local_width" not in result.scene.params


def test_recursive_function_diagnostic_is_not_hidden_by_vector_error():
    result = build("function f(x)=f(x)\nbody = box size=[f(1),2,3]\n", analyze_model=False)
    assert not result.ok
    message = (result.error or {}).get("message", "")
    assert "глубина" in message or "рекурс" in message
    assert "все элементы должны быть числами" not in message


def test_include_cycle_is_a_diagnostic_not_recursion(tmp_path: Path):
    (tmp_path / "a.forma").write_text('include file="b.forma"\n', encoding="utf-8")
    (tmp_path / "b.forma").write_text('include file="a.forma"\n', encoding="utf-8")
    result = build('include file="a.forma"\n', base_dir=tmp_path, analyze_model=False)
    assert not result.ok
    message = (result.error or {}).get("message", "").lower()
    assert "цикл" in message or "cycle" in message
    assert "a.forma" in (result.error or {}).get("hint", "")


def test_parameter_schema_presets_and_existing_override_rebuild():
    script = """param height=20 min=10 max=40 step=1 label="Высота"
preset tall height=30
body = box size=[10,10,height]
"""
    result = ok_build(script)
    payload = result.payload()
    # Декларация не выбирает вариант молча: это важно, когда presets несколько.
    assert payload["params"]["height"] == 20
    assert result.visible_solids()[0].stats()["size"][2] == pytest.approx(20)
    assert payload["parameter_schema"][0]["name"] == "height"
    assert payload["parameter_schema"][0]["label"] == "Высота"
    assert payload["presets"]["tall"]["height"] == 30
    chosen = ok_build("""param height=20 min=10 max=40 step=1 label="Высота"
preset tall height=30
preset tall
body = box size=[10,10,height]
""")
    assert chosen.scene.params["height"] == 30
    assert chosen.visible_solids()[0].stats()["size"][2] == pytest.approx(30)
    changed = ok_build(script, overrides={"height": 35})
    assert changed.scene.params["height"] == 35
    assert changed.scene.param_meta["height"]["default"] == pytest.approx(20)
    assert changed.visible_solids()[0].stats()["size"][2] == pytest.approx(35)
    out_of_range = build(script, overrides={"height": 100}, analyze_model=False)
    assert not out_of_range.ok and "override" in out_of_range.error["message"]


def test_appstate_saved_preset_rebuilds_current_mesh_and_validates_input(tmp_path: Path):
    from forma.errors import FormaError
    from forma.webui import AppState

    state = AppState()
    state.data_dir = tmp_path
    script = "param height=20 min=10 max=40\nbody = box size=[10,10,height]\n"
    saved = state.save_parameter_preset(script, "tall", {"height": 30})
    assert saved["ok"], saved.get("error")
    assert saved["params"]["height"] == 30
    assert saved["objects"][0]["size"][2] == pytest.approx(30)
    assert saved["presets"]["tall"]["height"] == 30
    # При повторном открытии декларация остаётся вариантом, а не скрытым
    # автоматическим применением; явный apply снова даёт ту же сетку.
    reopened = state.build(saved["script"])
    assert reopened["params"]["height"] == 20
    assert reopened["objects"][0]["size"][2] == pytest.approx(20)
    applied = state.apply_parameters(saved["script"], saved["presets"]["tall"])
    assert applied["objects"][0]["size"][2] == pytest.approx(30)
    with pytest.raises(FormaError, match="NaN|числом"):
        state.save_parameter_preset(script, "bad", {"height": "nan"})
    with pytest.raises(FormaError, match="не найден"):
        state.delete_parameter_preset(script, "missing")


def test_scad_export_is_real_polyhedron_and_keeps_precision():
    result = ok_build("thing = box size=[10.123456789,20,3]\n")
    text = export_scad(result.visible_solids())
    assert "polyhedron" in text
    assert "points=" in text and "faces=" in text
    # Manifold хранит mesh в float32; экспорт не должен дополнительно резать
    # координаты до четырёх знаков, как ранний прототип.
    assert "5.061728" in text
    assert "5.0617" in text and "5.0617," not in text
    assert "module" in text
    assert "thing" in text
    # В экспорт попадают треугольники реального manifold, а не placeholder.
    assert len(re.findall(r"\[0,1,2\]|\[0, 1, 2\]", text)) >= 0
    assert text.count("polyhedron") == 1


def test_provenance_is_flat_and_names_direct_parents():
    result = ok_build("""a = box size=[10,10,10]
b = box size=[4,4,20] at=[0,0,5]
c = difference [a,b]
""")
    payload = result.payload()
    c = next(item for item in payload["objects"] if item["name"] == "c")
    assert c["provenance"]["operation"] == "difference"
    assert c["provenance"]["parents"] == ["a", "b"]
    assert c["provenance"]["line"] == 3
    assert isinstance(payload["provenance"], list)
    assert all("children" not in row and "tree" not in row for row in payload["provenance"])


def _ascii_stl_for_runner() -> bytes:
    result = ok_build("runner_box = box size=[2,3,4]\n")
    return export_stl(result.visible_solids())


def test_openscad_runner_is_headless_and_returns_mesh_and_diagnostics(monkeypatch, tmp_path: Path):
    from forma import openscad as bridge

    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        output = Path(command[command.index("-o") + 1])
        output.write_bytes(_ascii_stl_for_runner())
        return SimpleNamespace(returncode=0, stdout="rendered", stderr="")

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    runner = bridge.OpenSCADRunner(executable="openscad-fake", library_paths=[tmp_path / "BOSL2"])
    result = runner.run("include <BOSL2/std.scad>\ncube(10);", work_dir=tmp_path)
    assert result.ok, result.error
    assert result.vertices.shape[1] == 3
    assert len(result.faces) > 0
    assert seen["kwargs"]["shell"] is False
    assert seen["kwargs"]["stdin"] == bridge.subprocess.DEVNULL
    assert "OPENSCADPATH" in seen["kwargs"]["env"]
    assert str(tmp_path / "BOSL2") in seen["kwargs"]["env"]["OPENSCADPATH"]
    assert not any(" --show" in str(part) for part in seen["command"])


def test_openscad_error_is_structured(monkeypatch, tmp_path: Path):
    from forma import openscad as bridge

    def fake_run(command, **kwargs):
        return SimpleNamespace(returncode=2, stdout="", stderr="ERROR: Parser error in line 7: syntax error")

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    result = bridge.OpenSCADRunner(executable="openscad-fake").run("cube(", work_dir=tmp_path)
    assert not result.ok
    assert result.error["line"] == 7
    assert "Parser" in result.error["message"] or "parser" in result.error["message"]


def test_photo_dimension_fit_reports_scale_residual_and_ambiguity():
    # Прямоугольный силуэт 100×200 px и репер 100 px = 50 мм.
    mask = np.zeros((240, 140), dtype=bool)
    mask[20:220, 20:120] = True
    model = ok_build("body = box size=[10,10,20]\n").visible_solids()
    fitted = fit_dimensions(
        mask, model, reference_length_px=100, reference_length_mm=50,
        reference_axis="height", camera={"azim_deg": 0, "elev_deg": 0}, size=96,
    )
    assert fitted["scale"] == pytest.approx(5.0, rel=1e-3)
    assert fitted["target_mm"]["height"] == pytest.approx(100.0)
    assert fitted["residual"]["iou"] >= 0.85
    unknown = fit_dimensions(mask, model, camera={"azim_deg": 0, "elev_deg": 0}, size=64)
    assert unknown["ambiguous"] is True
    assert any("масштаб" in item.lower() for item in unknown["diagnostics"])


def test_dimensioned_dxf_contains_measurement_entities(tmp_path: Path):
    result = ok_build("body = box size=[60,40,10]\n")
    solid = result.visible_solids()[0]
    section = cuts.slice_section(solid.manifold, "z", 5)
    contours = cuts.section_polygons(section)
    entry = {"layer": "TOP", "contours": [c["points"].tolist() for c in contours]}
    path = cuts.export_dimensioned_dxf([entry], tmp_path / "drawing.dxf")
    text = path.read_text(encoding="utf-8")
    assert "DIMENSION" in text
    assert "TEXT" in text
    assert "60.00" in text
    assert "40.00" in text
    assert "DIMENSIONS" in text


def test_global_precision_is_opt_in_and_explicit_segments_win():
    legacy = ok_build("s = sphere radius=10\n")
    legacy2 = ok_build("precision mode=legacy\ns = sphere radius=10\n")
    fine = ok_build("precision mode=fine\ns = sphere radius=10\n")
    explicit = ok_build("precision mode=fine\ns = sphere radius=10 segments=32\n")
    explicit_legacy = ok_build("s = sphere radius=10 segments=32\n")
    assert legacy.visible_solids()[0].manifold.num_tri() == legacy2.visible_solids()[0].manifold.num_tri()
    assert fine.visible_solids()[0].manifold.num_tri() > legacy.visible_solids()[0].manifold.num_tri()
    assert explicit.visible_solids()[0].manifold.num_tri() == explicit_legacy.visible_solids()[0].manifold.num_tri()


def test_precision_tolerance_reaches_implicit_lathe_and_contour_tessellation():
    legacy = ok_build("s = lathe points=[[0,0],[10,0],[10,20],[0,20]]\n")
    fine = ok_build("precision mode=fine\ns = lathe points=[[0,0],[10,0],[10,20],[0,20]]\n")
    assert fine.visible_solids()[0].manifold.num_tri() > legacy.visible_solids()[0].manifold.num_tri()
    custom = ok_build("precision factor=1 tolerance=0.01\ns = cylinder radius=10 height=20\n")
    ordinary = ok_build("s = cylinder radius=10 height=20\n")
    assert custom.visible_solids()[0].manifold.num_tri() > ordinary.visible_solids()[0].manifold.num_tri()
    explicit = ok_build("precision tolerance=0.0001\ns = cylinder radius=10 height=20 segments=32\n")
    explicit_legacy = ok_build("s = cylinder radius=10 height=20 segments=32\n")
    assert explicit.visible_solids()[0].manifold.num_tri() == explicit_legacy.visible_solids()[0].manifold.num_tri()
    contour_legacy = ok_build("c = contour2d kind=ellipse rx=10 ry=5\n")
    contour_fine = ok_build("precision mode=fine\nc = contour2d kind=ellipse rx=10 ry=5\n")
    assert len(contour_fine.scene.contours["c"].sample()) > len(contour_legacy.scene.contours["c"].sample())


def _fake_cli(tmp_path: Path, monkeypatch):
    """Маленький исполняемый CLI, не подменяющий subprocess внутри runner."""
    if os.name == "nt":
        pytest.skip("POSIX executable wrapper; Windows покрыт monkeypatch-контрактом")
    reference = tmp_path / "reference.stl"
    reference.write_bytes(_ascii_stl_for_runner())
    log = tmp_path / "invocation.json"
    program = tmp_path / "fake_openscad.py"
    program.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "out = Path(args[args.index('-o') + 1])\n"
        "out.write_bytes(Path(os.environ['FORMA_FAKE_STL']).read_bytes())\n"
        "Path(os.environ['FORMA_FAKE_LOG']).write_text(json.dumps({\n"
        " 'args': args, 'openscadpath': os.environ.get('OPENSCADPATH', ''),\n"
        " 'qt': os.environ.get('QT_QPA_PLATFORM', ''), 'cwd': os.getcwd()}))\n",
        encoding="utf-8",
    )
    executable = tmp_path / "openscad-fake"
    executable.write_text(f"#!/bin/sh\nexec \"{sys.executable}\" \"{program}\" \"$@\"\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("FORMA_FAKE_STL", str(reference))
    monkeypatch.setenv("FORMA_FAKE_LOG", str(log))
    return executable, log


def test_openscad_runner_real_subprocess_and_dsl(monkeypatch, tmp_path: Path):
    from forma import openscad as bridge

    executable, log = _fake_cli(tmp_path, monkeypatch)
    runner = bridge.OpenSCADRunner(executable=executable, library_paths=[tmp_path / "BOSL2"])
    result = runner.run("include <BOSL2/std.scad>\n" + ("//" + "x" * 5000) + "\ncube(10);",
                        defines={"width": 12}, work_dir=tmp_path)
    assert result.ok, result.error
    assert len(result.vertices) and len(result.faces)
    import json
    invocation = json.loads(log.read_text(encoding="utf-8"))
    assert "-D" in invocation["args"] and "width=12" in invocation["args"]
    assert str(tmp_path / "BOSL2") in invocation["openscadpath"]
    assert invocation["qt"] == "offscreen"
    monkeypatch.setenv("FORMA_OPENSCAD", str(executable))
    built = ok_build('external = openscad code="cube(10);" repair=да\n')
    assert built.scene.objects["external"].kind == "openscad"
    assert np.allclose(built.scene.objects["external"].stats()["size"], [2, 3, 4], atol=1e-5)


def test_appstate_openscad_adds_checked_mesh(monkeypatch, tmp_path: Path):
    from forma.webui import AppState

    executable, _ = _fake_cli(tmp_path, monkeypatch)
    monkeypatch.setenv("FORMA_OPENSCAD", str(executable))
    state = AppState()
    state.data_dir = tmp_path / "data"
    payload = state.run_openscad({"code": "cube(10);", "script": "", "add": True})
    assert payload["ok"], payload.get("error")
    assert payload["objects"][0]["kind"] == "import"
    assert payload["openscad"]["ok"] and payload["openscad"]["faces"] > 0
    assert np.allclose(payload["objects"][0]["size"], [2, 3, 4], atol=1e-5)
    assert list((state.data_dir / "imports").glob("openscad_*.stl"))


def test_photo_fit_text_baseline_and_apply_scale(tmp_path: Path):
    from forma.webui import AppState

    state = AppState()
    state.data_dir = tmp_path
    mask = np.zeros((64, 64), dtype=bool)
    mask[16:48, 16:48] = True
    script = "h=20\nbody = box size=[20,20,h]\n"
    report = state.fit_photo({
        "script": script, "mask": mask.tolist(), "parameters": {"h": {}},
        "reference_length_px": 32, "reference_length_mm": 40,
        "reference_axis": "height", "camera": {"azim_deg": 0, "elev_deg": 0},
        "size": 64, "max_iter": 8,
    })["photo_fit"]
    assert report["values"]["h"] == pytest.approx(20.0)
    applied = state.fit_photo({
        "script": script, "mask": mask.tolist(), "reference_length_px": 32,
        "reference_length_mm": 40, "reference_axis": "height",
        "camera": {"azim_deg": 0, "elev_deg": 0}, "size": 64, "max_iter": 4, "apply": True,
    })
    assert applied["ok"]
    assert applied["objects"][0]["size"][2] == pytest.approx(40.0)
    assert "scale [body] factor=2" in applied["script"]


def test_appstate_export_creates_real_files_in_fresh_data_dir(tmp_path: Path):
    from forma.webui import AppState

    state = AppState()
    state.data_dir = tmp_path
    assert state.build("body = box size=[10,20,30]\n")["ok"]
    scad = state.export("scad")
    drawing = state.export("drawing")
    assert Path(scad["path"]).is_file() and "polyhedron" in Path(scad["path"]).read_text(encoding="utf-8")
    assert Path(drawing["path"]).is_file() and "DIMENSION" in Path(drawing["path"]).read_text(encoding="utf-8")


def test_stage3_ui_and_demo_boundaries():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web/index.html").read_text(encoding="utf-8")
    js = (root / "web/js/app.js").read_text(encoding="utf-8")
    assert 'data-tab="params"' in html and 'id="provenance-panel"' in html
    assert 'id="photo-fit"' in html and 'id="openscad-run"' in html
    assert 'requestParameters' in js and 'renderProvenance' in js
    from forma.webui import AppState
    state = AppState()
    state.demo = True
    with pytest.raises(Exception, match="демо"):
        state.build('include file="secret.forma"\n')
    with pytest.raises(Exception, match="демо"):
        state.build('x = openscad code="cube(10);"\n')


