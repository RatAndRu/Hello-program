"""Minimal repro: GLB и payload обязаны описывать одну ревизию модели."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forma.run import build  # noqa: E402


def glb_json(data: bytes) -> dict:
    length = int.from_bytes(data[12:16], "little")
    return json.loads(data[20:20 + length])


class AssetFingerprintTests(unittest.TestCase):
    def test_main_glb_carries_payload_variant(self):
        result = build("a = box size=[10,20,30]", analyze_model=False,
                       overrides={})
        self.assertTrue(result.ok, result.error)
        doc = glb_json(result.glb())
        extras = doc["asset"]["extras"]
        self.assertEqual(extras["forma_variant"], result.variant_hash)
        self.assertEqual(extras["forma_script"], result.script_hash)

    def test_catalog_lamp_payload_and_glb_are_one_revision(self):
        from forma.webui import AppState, load_example
        source = load_example("arte_lamp_banker_a2492lt_1ab")
        with tempfile.TemporaryDirectory() as tmp:
            state = AppState()
            state.data_dir = Path(tmp)
            payload = state.build(source)
            self.assertTrue(payload["ok"], payload.get("error"))
            visible = [item for item in payload["objects"] if item["visible"]]
            self.assertEqual(len(visible), 54)
            self.assertEqual(sum(item["tris"] for item in visible), 10_724)
            doc = glb_json(state.glb())
            self.assertEqual(doc["asset"]["extras"]["forma_variant"],
                             payload["variant_hash"])
            self.assertEqual(doc["asset"]["extras"]["forma_script"],
                             payload["script_hash"])

    def test_variant_covers_overrides_and_engine_revision(self):
        result = build("param h=10\na = box size=[10,20,h]", analyze_model=False)
        self.assertTrue(result.ok, result.error)
        base = build(result.script, analyze_model=False, overrides={"h": 20})
        self.assertNotEqual(result.variant_hash, base.variant_hash)
        with patch("forma.run._FORMA_VERSION", "test-before"):
            before = result.variant_hash
        with patch("forma.run._FORMA_VERSION", "test-after"):
            after = result.variant_hash
        self.assertNotEqual(before, after)
        self.assertNotEqual(result.variant_hash, result.script_hash)


if __name__ == "__main__":
    unittest.main()
