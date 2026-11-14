#!/usr/bin/env python3
"""Точка входа AirMouse (её же прописывает автозапуск Windows)."""

from airmouse.cli import run_main

if __name__ == "__main__":
    raise SystemExit(run_main())
