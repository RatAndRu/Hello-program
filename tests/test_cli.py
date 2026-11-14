"""Запуск в «оконном» окружении (как в PyInstaller EXE без консоли)."""

from __future__ import annotations

import logging
import sys

from airmouse.cli import build_parser, setup_logging
from airmouse.config import AppConfig


def test_setup_logging_without_stderr(monkeypatch, tmp_path):
    """В оконной сборке sys.stderr = None — запуск не должен падать."""
    cfg = AppConfig()
    cfg.log_file = str(tmp_path / "logs" / "airmouse.log")
    monkeypatch.setattr(sys, "stderr", None)
    setup_logging(cfg)  # не бросает
    handlers = logging.getLogger().handlers
    assert handlers
    assert all(not isinstance(h, logging.StreamHandler) or isinstance(h, logging.FileHandler)
               for h in handlers)


def test_parser_has_run_subcommand():
    parser = build_parser()
    args = parser.parse_args(["run", "--backend", "classical", "--warmup", "3"])
    assert args.command == "run"
    assert args.backend == "classical"
    assert args.warmup == 3.0
