"""Точка входа для сборки PyInstaller.

Файл специально лежит отдельно: PyInstaller анализирует именно его, а сам
пакет ``airmouse`` подхватывается из корня репозитория (pathex в .spec).
"""

import multiprocessing
import sys


def main() -> int:
    from airmouse.cli import run_main

    return run_main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
