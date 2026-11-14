#!/usr/bin/env bash
# AirMouse: запуск на Linux/macOS
cd "$(dirname "$0")"
exec python3 run_airmouse.py "$@"
