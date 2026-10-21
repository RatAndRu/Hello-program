"""Запуск приложения ФОРМА 3D: окно (pywebview) или браузер."""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser

from .version import APP_NAME, APP_TITLE, __version__
from .webui import serve_in_thread


def say(message: str = "") -> None:
    """Печать, безопасная в оконном режиме без консоли."""
    try:
        if sys.stdout is not None:
            print(message, flush=True)
    except Exception:
        pass


def _start_window(url: str) -> bool:
    try:
        import webview  # type: ignore
    except Exception as exc:
        say(f"Окно недоступно ({exc}). Открываю в браузере.")
        return False
    try:
        webview.create_window(
            APP_TITLE, url,
            width=1520, height=960,
            min_size=(1080, 680),
            background_color="#0c0f14",
            confirm_close=False,
        )
        webview.start(debug=False, private_mode=False)
        return True
    except Exception as exc:
        say(f"Не удалось открыть окно ({exc}). Открываю в браузере.")
        return False


def _run_selftest(report_path: str | None) -> int:
    from .selftest import run_selftest

    result = run_selftest()
    lines = []
    for case in result["cases"]:
        mark = "OK  " if case["ok"] else "FAIL"
        if case.get("error"):
            lines.append(f"[{mark}] {case['name']}: {case['error']}")
        else:
            lines.append(f"[{mark}] {case['name']}: {case.get('tris')} трис")
            for chk in case.get("checks", []):
                lines.append(("   ✓ " if chk["ok"] else "   ✗ ") + chk["text"])
    lines.append("")
    lines.append("ИТОГ: " + ("всё в порядке" if result["ok"] else "есть проблемы"))
    text = "\n".join(lines)
    say(text)
    if report_path:
        try:
            from pathlib import Path
            Path(report_path).write_text(text, encoding="utf-8")
        except Exception:
            pass
    return 0 if result["ok"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} {__version__}")
    parser.add_argument("--port", type=int, default=0, help="порт (0 — свободный)")
    parser.add_argument("--host", default="127.0.0.1", help="адрес прослушивания")
    parser.add_argument("--browser", action="store_true", help="открыть в браузере")
    parser.add_argument("--no-open", action="store_true", help="не открывать окно/браузер")
    parser.add_argument("--selftest", action="store_true", help="проверить геометрическое ядро")
    parser.add_argument("--report", default=None, help="куда записать отчёт самопроверки")
    parser.add_argument("--version", action="store_true", help="показать версию")
    args, _unknown = parser.parse_known_args(argv)

    if args.version:
        say(f"{APP_NAME} {__version__}")
        return 0
    if args.selftest:
        return _run_selftest(args.report)

    server, url = serve_in_thread(host=args.host, port=args.port, open_browser=False, verbose=False)
    say(f"{APP_NAME} {__version__}")
    say(f"Адрес интерфейса: {url}")
    say(f"Папка данных: {server.forma_state.data_dir}")

    if args.no_open:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            say("\nОстановлено.")
        return 0

    if args.browser:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            say("\nОстановлено.")
        return 0

    # по умолчанию — собственное окно; если не получилось, открываем браузер
    if _start_window(url):
        return 0
    webbrowser.open(url)
    say("Приложение работает в браузере. Закройте это окно для остановки.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        say("\nОстановлено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
