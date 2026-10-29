"""Лёгкий статический стенд версий и геометрическая честность preview."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

import manifold3d as mf

from forma.geometry import export_glb
from forma.model import Solid
from showcase.build_showcase import (
    export_preview_glb,
    train_interior_solids,
    validate_glb_pair,
)

ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = ROOT / "showcase"


class ShowcaseTest(unittest.TestCase):
    def test_catalog_has_versioned_changes_and_existing_sources(self):
        catalog = json.loads((SHOWCASE / "catalog.source.json").read_text(encoding="utf-8"))
        self.assertEqual([v["id"] for v in catalog["versions"]],
                         ["train-2026-10", "0.53", "0.52"])
        for version in catalog["versions"]:
            self.assertGreaterEqual(len(version["changes"]), 4)
            self.assertTrue(version["title"])
            for model in version["models"]:
                self.assertTrue((ROOT.parent / model["source"]).is_file(), model["source"])
                self.assertTrue(model["posters"])

    def test_preview_batching_preserves_faces_normals_and_bounds(self):
        first = Solid("a", mf.Manifold.cube([10, 10, 10]), color="#aabbcc")
        second = Solid("b", mf.Manifold.cube([8, 8, 8]).translate([20, 0, 0]), color="#aabbcc")
        third = Solid("c", mf.Manifold.cube([6, 6, 6]).translate([40, 0, 0]), color="#112233")
        solids = [first, second, third]
        full = export_glb(solids)
        preview, optimization = export_preview_glb(solids)
        report = validate_glb_pair(full, preview, solids)
        self.assertEqual(report["triangles"], 36)
        self.assertEqual(report["full_nodes"], 3)
        self.assertEqual(report["preview_nodes"], 2)
        self.assertEqual(optimization["source_meshes"], 3)
        self.assertLessEqual(max(report["bounds_deviation_mm"].values()), 0.002)

    def test_train_interior_filter_does_not_modify_scene(self):
        solids = [
            Solid("track_rail", mf.Manifold.cube([1, 1, 1])),
            Solid("car_roof", mf.Manifold.cube([1, 1, 1])),
            Solid("seat", mf.Manifold.cube([1, 1, 1])),
        ]
        filtered = train_interior_solids(solids)
        self.assertEqual([s.name for s in filtered], ["seat"])
        self.assertEqual(len(solids), 3)

    def test_frontend_is_lazy_and_disposes_hidden_gl(self):
        index = (SHOWCASE / "static" / "index.html").read_text(encoding="utf-8")
        app = (SHOWCASE / "static" / "app.js").read_text(encoding="utf-8")
        viewer = (SHOWCASE / "static" / "viewer.js").read_text(encoding="utf-8")
        self.assertIn('id="viewer-dialog"', index)
        self.assertNotIn("forma-token", index)
        self.assertIn("import('./viewer.js')", app)
        self.assertIn('loading="lazy"', app)
        self.assertIn("closeViewer()", app)
        self.assertIn("forceContextLoss", viewer)
        self.assertIn("document.hidden", viewer)
        self.assertNotIn("/api/build", app)

    @unittest.skipUnless(shutil.which("node"), "Node.js не установлен")
    def test_javascript_syntax(self):
        for name in ("app.js", "viewer.js"):
            with self.subTest(name=name):
                subprocess.run(["node", "--check", str(SHOWCASE / "static" / name)], check=True)

    def test_production_is_static_nginx_with_precompressed_assets(self):
        nginx = (SHOWCASE / "nginx.conf").read_text(encoding="utf-8")
        docker = (SHOWCASE / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("gzip_static on", nginx)
        self.assertIn("no-transform", nginx)
        self.assertIn("listen 8000", nginx)
        self.assertIn("return 410", nginx)
        self.assertIn("AS assets", docker)
        self.assertIn("nginxinc/nginx-unprivileged", docker)
        self.assertNotIn("run_forma.py", docker)


if __name__ == "__main__":
    unittest.main()
