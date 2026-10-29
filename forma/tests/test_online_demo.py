"""Публичный online-demo: health, стартовый проект и серверные ограничения."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from forma.errors import FormaError
from forma.webui import AppState, make_server

ROOT = Path(__file__).resolve().parents[1]


class OnlineDemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "FORMA_DATA": self.tmp.name,
            "FORMA_DEMO": "1",
            "FORMA_START_PROJECT": "train_carriage",
            "FORMA_REVISION": "abc1234demo",
        })
        self.env.start()
        self.server, _ = make_server(host="127.0.0.1", port=0)
        projects = Path(self.tmp.name) / "projects"
        projects.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "examples" / "train_carriage.forma", projects / "train_carriage.forma")
        shutil.copy(ROOT / "examples" / "living_room_diorama.forma",
                    projects / "living_room_diorama.forma")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.token = self.server.forma_state.token

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.env.stop()
        self.tmp.cleanup()

    def get(self, path: str, token: bool = True):
        url = self.base + path
        if token:
            url += ("&" if "?" in path else "?") + "token=" + self.token
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, response.read()

    def post(self, path: str, body, raw: bool = False):
        data = body if raw else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path + "?token=" + self.token,
            data=data,
            headers={"Content-Type": "application/octet-stream" if raw else "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health_revision_and_start_project(self):
        status, data = self.get("/healthz", token=False)
        health = json.loads(data)
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])
        self.assertTrue(health["demo"])
        self.assertEqual(health["revision"], "abc1234demo")
        status, data = self.get("/api/state")
        state = json.loads(data)
        self.assertEqual(status, 200)
        self.assertTrue(state["demo"])
        self.assertEqual(state["revision"], "abc1234demo")
        self.assertEqual(state["project"], "train_carriage")
        self.assertIn("ПЛАЦКАРТНЫЙ ВАГОН 61-4194", state["script"])
        self.assertEqual(len(state["projects"]), 2)

    def test_demo_blocks_server_writes_and_local_operations(self):
        for path, body, raw in (
            ("/api/save", {"name": "shared", "script": "a = box size=[1,1,1]"}, False),
            ("/api/reveal", {"path": self.tmp.name}, False),
            ("/api/import", {"name": "mesh", "script": ""}, False),
            ("/api/prompt", {"script": "a = box size=[1,1,1]"}, False),
            ("/api/upload", b"not-a-mesh", True),
            ("/api/save-file", b"not-an-image", True),
        ):
            with self.subTest(path=path):
                status, response = self.post(path, body, raw=raw)
                self.assertEqual(status, 400)
                self.assertIn("демо", response["error"]["message"])

    def test_demo_import_and_heavy_override_are_blocked_before_build(self):
        status, response = self.post("/api/build", {
            "script": "mesh = import file=/etc/passwd", "allow_heavy": True,
        })
        self.assertEqual(status, 400)
        self.assertIn("импорт", response["error"]["message"])
        warning = {"resource_warning": True, "estimated_tris": 900000, "limit": 500000}
        with patch("forma.webui.resource_warning", return_value=warning), \
                patch("forma.webui.run_build") as run:
            with self.assertRaises(FormaError):
                self.server.forma_state.build("a = box size=[1,1,1]", allow_heavy=True)
            run.assert_not_called()

    def test_train_is_allowed_inside_demo_limit(self):
        script = (ROOT / "examples" / "train_carriage.forma").read_text(encoding="utf-8")
        result = self.server.forma_state.build(script, allow_heavy=True)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["analysis"]["metrics"]["tris"], 336536)

    def test_normal_mode_keeps_heavy_confirmation(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"FORMA_DATA": directory, "FORMA_DEMO": "0"}):
            state = AppState()
            warning = {"resource_warning": True, "estimated_tris": 900000, "limit": 500000}
            with patch("forma.webui.resource_warning", return_value=warning), \
                    patch("forma.webui.run_build") as run:
                result = state.build("a = box size=[1,1,1]", allow_heavy=False)
            self.assertTrue(result["resource_warning"])
            self.assertTrue(result["paused"])
            run.assert_not_called()

    def test_demo_ui_has_revision_badge_and_save_guard(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "css" / "app.css").read_text(encoding="utf-8")
        self.assertIn('id="demo-badge"', html)
        self.assertIn("state.demo = Boolean(st.demo)", js)
        self.assertIn("state.revision.slice(0, 7)", js)
        self.assertIn("if (state.demo)", js)
        self.assertIn("Используйте экспорт .forma", js)
        self.assertIn(".demo-badge", css)


if __name__ == "__main__":
    unittest.main()
