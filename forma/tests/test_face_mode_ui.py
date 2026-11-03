"""Статический контракт UI разметки граней (browser audit дополняет его)."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
VIEWER = (ROOT / "web" / "js" / "viewer.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")


class FaceModeUiTests(unittest.TestCase):
    def test_controls_and_three_roles_exist(self):
        for element_id in (
            "btn-face-mode", "face-card", "face-object", "face-xray",
            "face-outside", "face-inside", "face-neutral", "face-check",
            "face-clear", "face-report",
        ):
            self.assertIn(f'id="{element_id}"', HTML)
        self.assertIn("соседние тела прозрачные", HTML)

    def test_viewer_has_precise_face_picking_and_xray(self):
        for token in (
            "pickFaceAt(clientX, clientY)", "hit.faceIndex", "setFaceSelection",
            "setFaceRoles", "setFaceTarget", "setFaceXray",
        ):
            self.assertIn(token, VIEWER)
        self.assertIn("this.faceTarget ? this.objectMeshes(this.faceTarget)", VIEWER)
        self.assertIn("material.opacity = ghost ? 0.16 : 1", VIEWER)

    def test_diagnostic_colors_are_not_pbr_or_anime(self):
        self.assertIn("new THREE.MeshBasicMaterial", VIEWER)
        self.assertIn("vertexColors: true, side: THREE.DoubleSide, toneMapped: false", VIEWER)
        self.assertIn("role === 'outside' ? 0x2384ff", VIEWER)
        self.assertIn("role === 'inside' ? 0xef4444", VIEWER)
        self.assertIn("!this.faceMode && (this._bloomOn || animeOn)", VIEWER)

    def test_selection_and_script_persistence(self):
        self.assertIn("additive: e.shiftKey", VIEWER)
        self.assertIn("subtract: e.ctrlKey || e.metaKey", VIEWER)
        self.assertIn("state.viewer.onFaceSelect", APP)
        self.assertIn("полигоны ${JSON.stringify(name)}", APP)
        self.assertIn("outside=[${outside.join(',')}]", APP)
        self.assertIn("inside=[${inside.join(',')}]", APP)
        self.assertIn("faceCommandBelongs", APP)
        self.assertIn("applyFaceRole('neutral')", APP)

    def test_face_mode_does_not_stop_playback(self):
        start = APP.index("function setFaceMode(on)")
        end = APP.index("function handleFaceSelect", start)
        block = APP[start:end]
        self.assertNotIn("playAnimation(false)", block)
        self.assertNotIn("anim.playing = false", block)
        self.assertNotIn("togglePlayAnim", block)

    def test_view_preferences_and_deleted_target_survive_diagnostic_mode(self):
        shading = VIEWER[VIEWER.index("setShading(mode)"):VIEWER.index("applyMaterial(name")]
        polygons = VIEWER[VIEWER.index("setObjectPolygons(name"):VIEWER.index("objectPolygons(name")]
        self.assertIn("o.userData.faceDiagnostic.material", shading)
        self.assertIn("o.userData.faceDiagnostic?.material", polygons)
        sync = APP[APP.index("function syncFaceRoles"):APP.index("function faceCommandBelongs")]
        self.assertIn("populateFaceObjects", sync)
        self.assertIn("state.viewer.faceTarget !== target", sync)

    def test_responsive_face_card(self):
        self.assertIn("width: min(280px, calc(100% - 24px))", CSS)
        self.assertIn("max-height: min(300px, calc(100% - 52px))", CSS)
        self.assertIn("grid-template-columns: 1fr 1fr", CSS)
        mobile = CSS[CSS.index("/* 0.72: разметка"):]
        self.assertIn("position: fixed", mobile)
        self.assertIn("max-height: calc(100vh - 100px)", mobile)
        self.assertIn("white-space: normal", mobile)
        self.assertIn("overflow-wrap: anywhere", mobile)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", mobile)


if __name__ == "__main__":
    unittest.main()
