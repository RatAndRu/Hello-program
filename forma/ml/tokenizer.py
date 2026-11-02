"""Словарь языка ФОРМЫ: превращаем текст сценария в числа и обратно.

Зачем это нужно. Нейросеть не видит слов — она видит целые числа (индексы) и
на их месте достаёт строки таблицы весов. Поэтому «понимать примитивы» в
математическом смысле означает: выучить распределение последовательностей
токенов `box size = [ 30 , 20 , 10 ] center = да`, у которых параметры связаны
через геометрию.

Схема токенизации:

* слова (команды, параметры, `да`, `нет`) — один токен;
* каждое число — токен `<num>` и дальше цифры по одной, минус — отдельным
  токеном, точка — отдельным. Так сеть не обязана знать все 10 000 целых;
* всё остальное (`=`, `[`, `]`, `,`, `\n`) — по одному символу.

Словарь — обычный JSON: его можно открыть, прочитать и поправить руками.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = ["Tokenizer", "TOKEN_RE"]

TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*|\d+|[^\sA-Za-zА-Яа-яЁё_0-9]")

PAD, UNK, NUM = "<pad>", "<unk>", "<num>"
SPECIAL = [PAD, UNK, NUM, "\n"]


class Tokenizer:
    def __init__(self, vocab: dict[str, int] | None = None):
        self.vocab: dict[str, int] = dict(vocab or {t: i for i, t in enumerate(SPECIAL)})
        self.inv: dict[int, str] = {i: t for t, i in self.vocab.items()}

    # ---------------------------------------------------------------- обучение
    def fit(self, texts: list[str], min_count: int = 2) -> "Tokenizer":
        counts: dict[str, int] = {}
        for text in texts:
            for tok in self.tokens(text):
                counts[tok] = counts.get(tok, 0) + 1
        for tok, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            if n >= min_count and tok not in self.vocab:
                self.vocab[tok] = len(self.vocab)
        self.inv = {i: t for t, i in self.vocab.items()}
        return self

    # ---------------------------------------------------------------- работа
    @staticmethod
    def tokens(text: str) -> list[str]:
        out: list[str] = []
        for raw in TOKEN_RE.findall(text):
            if raw.isdigit():
                out.append(NUM)
                out.extend(list(raw))
            else:
                out.append(raw)
        return out

    def encode(self, text: str, length: int | None = None) -> list[int]:
        ids = [self.vocab.get(t, self.vocab[UNK]) for t in self.tokens(text)]
        if length is None:
            return ids
        return (ids + [self.vocab[PAD]] * length)[:length]

    def decode(self, ids: list[int]) -> str:
        """Обратное превращение: числа → текст. Пробелы расставляются грубо,
        но сценарий остаётся читаемым — это проверка, что словарь не врёт."""
        parts: list[str] = []
        in_number = False
        for i in ids:
            tok = self.inv.get(int(i), UNK)
            if tok == PAD:
                continue
            if tok == "\n":
                parts.append("\n")
                in_number = False
            elif tok == NUM:
                parts.append(" ")
                in_number = True
            elif re.fullmatch(r"\d", tok) and in_number:
                parts.append(tok)
            elif re.fullmatch(r"\d", tok):
                parts.append(tok)
            elif tok in "=[].,":
                parts.append(tok)
                in_number = False
            else:
                parts.append(" " + tok)
                in_number = False
        return re.sub(r"[ \t]+", " ", "".join(parts)).strip()

    # ---------------------------------------------------------------- файл
    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.vocab, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Tokenizer":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def __len__(self) -> int:
        return len(self.vocab)
