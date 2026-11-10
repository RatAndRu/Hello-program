"""0.74.2: режим плиток в инструментах.

Плитка — это картинка и название; клик вставляет одну строку операции с
заводскими параметрами. Поэтому проверяется ровно то, что видит пользователь:

* картинка на каждую плитку манифеста есть, и наоборот — лишних файлов нет;
* каждое слово манифеста есть в реестре команд этой версии;
* строка, которую плитка вставляет, действительно собирается;
* сервер отдаёт плитки по `/api/thumbs`, а картинки — по `/thumbs/…`.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.request
from pathlib import Path

from forma.ops import lookup
from forma.run import build

ROOT = Path(__file__).resolve().parent.parent
THUMBS = ROOT / "web" / "thumbs"
MANIFEST = THUMBS / "tiles.json"


def manifest() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["tiles"]


def tile_script(tile: dict) -> str:
    tail = tile.get("params") or ""
    line = f"t = {tile['op']} {tail}".strip()
    return line + "\n"


class TileManifestTest(unittest.TestCase):
    def test_manifest_and_pictures_agree(self):
        tiles = manifest()
        self.assertGreaterEqual(len(tiles), 120)
        names = {tile["op"] for tile in tiles}
        self.assertEqual(len(names), len(tiles), "в манифесте повторяется слово операции")
        files = {path.stem for path in THUMBS.glob("*.png")}
        self.assertEqual(files - names, set(), "картинка без строки манифеста")
        self.assertEqual(names - files, set(), "строка манифеста без картинки")

    def test_every_tile_points_to_a_known_op(self):
        for tile in manifest():
            with self.subTest(op=tile["op"]):
                self.assertIsNotNone(lookup(tile["op"]), tile["op"])
                self.assertTrue(tile.get("title"), "у плитки нет подписи")

    def test_tile_click_builds(self):
        # Клик вставляет операцию с заводскими параметрами — она обязана
        # собираться без правок, иначе плитка обещает то, чего нет.
        for tile in manifest():
            with self.subTest(op=tile["op"]):
                result = build(tile_script(tile), analyze_model=False)
                self.assertTrue(result.ok, (result.error or {}).get("message"))
                self.assertTrue(result.scene.visible_solids(), "плитка дала пустую сцену")

    def test_pictures_are_square_png(self):
        for path in list(THUMBS.glob("*.png"))[:12]:
            data = path.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", path.name)
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            self.assertEqual((width, height), (128, 128), f"{path.name}: {width}×{height}")


class ThumbsApiTest(unittest.TestCase):
    def test_server_serves_tiles(self):
        from forma.webui import make_server

        server, _ = make_server("127.0.0.1", 0)
        state = server.forma_state
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"

        def get(path: str, token: bool = False) -> bytes:
            if token:
                path = f"{path}{'&' if '?' in path else '?'}token={state.token}"
            with urllib.request.urlopen(f"{base}{path}", timeout=20) as answer:
                return answer.read()

        try:
            items = json.loads(get("/api/thumbs", token=True))["thumbs"]
            self.assertEqual(len(items), len(manifest()))
            self.assertTrue(all(item["listed"] for item in items))
            picture = get(items[0]["url"])
            self.assertEqual(picture[:8], b"\x89PNG\r\n\x1a\n")
            page = get("/").decode("utf-8", "replace")
            self.assertIn('id="tools-tiles"', page)
            script = get("/js/app.js").decode("utf-8")
            for name in ("loadTileThumbs", "tileGrid", "renderTiles", "insertTileOp"):
                self.assertIn(f"function {name}(", script)
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
