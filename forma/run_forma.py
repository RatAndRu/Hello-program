"""Прямой запуск без установки: python run_forma.py [--selftest|--uistest|команда ...].

Без аргументов открывает окно приложения; с командой build/render/export работает
как консольный инструмент.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _main() -> int:
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        from forma.app import main as app_main
        return app_main(args)
    from forma.cli import main as cli_main
    return cli_main(args)


if __name__ == "__main__":
    sys.exit(_main())
