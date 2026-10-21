"""Точка входа для сборки exe (PyInstaller)."""

import multiprocessing
import sys

from forma.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main(sys.argv[1:]))
