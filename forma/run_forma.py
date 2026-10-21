"""Прямой запуск без установки: python run_forma.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from forma.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
