"""Тесты пакета ml: файл весов, словарь, правило и честность метрик.

Проверяется не «сеть хорошо учится» (это вопрос данных и времени), а
инженерные свойства, которые легко сломать незаметно:

* safetensors пишется и читается без потерь (иначе обучение бессмысленно);
* декодер словаря возвращает читаемый сценарий;
* правило `rule.metrics_of` совпадает с движком там, где обязано совпадать;
* маленькая сеть действительно обучается на 60 сценах за секунды, то есть
  механизм обучения рабочий, а не декоративный.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from forma.run import build
from ml import synth, train
from ml.mlp import MLP, load_safetensors, save_safetensors
from ml.rule import metrics_of
from ml.tokenizer import Tokenizer


class SafetensorsTest(unittest.TestCase):
    def test_round_trip(self):
        tensors = {"W1": np.arange(12, dtype=np.float32).reshape(3, 4),
                   "b": np.array([1.5, -2.5], dtype=np.float32)}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.safetensors"
            size = save_safetensors(p, tensors)
            self.assertEqual(size, p.stat().st_size)
            back = load_safetensors(p)
        for k, v in tensors.items():
            self.assertEqual(back[k].shape, v.shape)
            np.testing.assert_array_equal(back[k], v)

    def test_header_is_eight_bytes_then_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.safetensors"
            save_safetensors(p, {"w": np.zeros(4, dtype=np.float32)})
            raw = p.read_bytes()
            n = int.from_bytes(raw[:8], "little")
            header = json.loads(raw[8:8 + n])
        self.assertEqual(header["w"]["dtype"], "F32")
        self.assertEqual(header["w"]["shape"], [4])
        self.assertEqual(header["w"]["data_offsets"], [0, 16])

    def test_mlp_save_load_keeps_predictions(self):
        net = MLP(5, 7, 2, seed=1)
        x = np.random.default_rng(0).standard_normal((3, 5)).astype(np.float32)
        with tempfile.TemporaryDirectory() as d:
            net.save(Path(d) / "w.safetensors", Path(d) / "c.json")
            back = MLP.load(Path(d) / "w.safetensors", Path(d) / "c.json")
        np.testing.assert_allclose(net.predict(x), back.predict(x), rtol=1e-6)

    def test_config_records_shape(self):
        net = MLP(11, 13, 3)
        with tempfile.TemporaryDirectory() as d:
            net.save(Path(d) / "w.safetensors", Path(d) / "c.json")
            cfg = json.loads((Path(d) / "c.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["n_in"], cfg["n_hidden"], cfg["n_out"]), (11, 13, 3))
        self.assertEqual(cfg["n_params"], 11 * 13 + 13 + 13 * 3 + 3)


class TokenizerTest(unittest.TestCase):
    def test_vocabulary_is_small(self):
        tok = Tokenizer()
        tok.fit(["o0 = box size=[30,20,10] center=да at=[0,0,0]",
                 "o1 = sphere radius=25"])
        self.assertLess(len(tok), 60)

    def test_round_trip_keeps_command_names(self):
        text = "o0 = box size=[30,20,10] center=да at=[0,0,0]"
        tok = Tokenizer()
        tok.fit([text], min_count=1)      # иначе редкие слова уйдут в <unk>
        back = tok.decode(tok.encode(text, 96))
        for word in ("box", "size", "center", "at"):
            self.assertIn(word, back)


class RuleTest(unittest.TestCase):
    """Правило обязано совпадать с движком там, где считается точно."""

    def test_volume_and_bbox_of_single_box(self):
        dsl = "o0 = box size=[30,20,10] center=да at=[0,0,0]"
        r = build(dsl)
        self.assertTrue(r.ok)
        m = r.analysis["metrics"]
        mine = metrics_of(dsl)
        self.assertAlmostEqual(mine["log объёма"], np.log10(m["volume_cm3"] * 1000), places=2)
        for axis, key in enumerate(("габарит X", "габарит Y", "габарит Z")):
            self.assertAlmostEqual(mine[key], m["size"][axis], delta=0.5)

    def test_shift_in_bbox(self):
        dsl = "o0 = box size=[10,10,10] center=да at=[0,0,0]\no1 = box size=[10,10,10] center=да at=[40,0,0]"
        mine = metrics_of(dsl)
        self.assertAlmostEqual(mine["габарит X"], 50.0, delta=0.5)
        self.assertEqual(mine["частей"], 2)

    def test_genus_counts_holes(self):
        self.assertEqual(metrics_of("o0 = torus outer=60 inner=20")["род (отверстия)"], 1.0)
        self.assertEqual(metrics_of("o0 = box size=[10,10,10] center=да")["род (отверстия)"], 0.0)


class TrainingTest(unittest.TestCase):
    """Не «качество», а работоспособность механизма: ошибка должна падать."""

    def test_head_learns_small_set(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "scenes.jsonl"
            synth.generate(data, scenes=60, seed=3, workers=1)
            self.assertTrue(data.exists())
            rep = train.train(data, Path(d) / "w", hidden=32, epochs=120)
            self.assertTrue((Path(d) / "w" / "head.safetensors").exists())
            self.assertTrue((Path(d) / "w" / "vocab.json").exists())
        hist = rep["history"]
        self.assertGreater(len(hist), 5)
        self.assertLess(min(hist), hist[0] * 0.9, "обучение не сдвинуло ошибку")

    def test_scene_row_has_seven_numbers(self):
        row = synth.scene_row("o0 = box size=[30,20,10] center=да at=[0,0,0]")
        self.assertIsNotNone(row)
        self.assertEqual(len(row["y"]), synth.N_TARGETS)

    def test_generate_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.jsonl", Path(d) / "b.jsonl"
            synth.generate(a, scenes=12, seed=5, workers=2)
            synth.generate(b, scenes=12, seed=5, workers=2)
            self.assertEqual(a.read_text(encoding="utf-8"), b.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
