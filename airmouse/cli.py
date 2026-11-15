"""Командная строка AirMouse.

    python -m airmouse                 # запуск управления
    python -m airmouse --no-window     # в фоне, иконка в трее
    python -m airmouse doctor          # проверить окружение и камеру
    python -m airmouse demo            # синтетическая демонстрация (без камеры)
    python -m airmouse lip record -w "стоп"
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import sys
import time
import traceback
import threading
from pathlib import Path
from typing import List, Optional

import numpy as np

from . import __version__
from .config import (
    DEFAULT_CONFIG_PATH,
    AppConfig,
    app_root,
    load_config,
    resolve_path,
    save_config,
    set_value,
)
from .lipreading import LipReader, TemplateStore, mouth_features

log = logging.getLogger("airmouse")


# --------------------------------------------------------------------------- #
#  Логирование
# --------------------------------------------------------------------------- #
def setup_logging(cfg: AppConfig, debug: bool = False) -> None:
    log_path = resolve_path(cfg.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: List[logging.Handler] = [logging.FileHandler(log_path, encoding="utf-8")]
    # В оконной сборке PyInstaller sys.stderr = None — обращаться к нему нельзя.
    stream = sys.stderr
    if stream is not None and (debug or (hasattr(stream, "isatty") and stream.isatty())):
        handlers.append(logging.StreamHandler(stream))
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


# --------------------------------------------------------------------------- #
#  run
# --------------------------------------------------------------------------- #
def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.camera is not None:
        cfg.camera.index = args.camera
    if args.video:
        cfg.camera.video_file = args.video
    if args.backend:
        cfg.tracker = args.backend
    if args.no_face:
        cfg.face.enabled = False
    if args.head_mouse:
        cfg.head_pointer = True
    if getattr(args, "gaze_mouse", False):
        cfg.gaze_pointer = True
    if args.warmup is not None:
        cfg.warmup_s = args.warmup
    if args.lip:
        cfg.lip.enabled = True
    if args.no_window:
        cfg.show_window = False
    setup_logging(cfg, args.debug)

    from .app import AirMouseApp

    app = AirMouseApp(
        cfg,
        dry_run=args.dry_run,
        show_window=cfg.show_window,
        output=Path(args.output) if args.output else None,
    )
    app.setup()
    if args.dry_run:
        log.info("Режим --dry-run: настоящие клики и движения мыши отключены")
    note = getattr(app.tracker, "fallback_reason", "")
    if note:
        log.warning("Нейросеть не используется: %s", note)
        log.warning("В окне это видно строкой «движок: классический CV»; "
                    "клавиша M переключает движки на ходу")

    if not cfg.show_window:
        if args.tray and tray_available():
            worker = threading.Thread(target=app.run, name="airmouse", daemon=True)
            worker.start()
            log.info("Приложение в фоне. Иконка в трее; выход — через меню.")
            try:
                from .tray import run as run_tray

                run_tray(app, blocking=True)
            finally:
                app.stop()
                worker.join(timeout=2.0)
            return 0
        log.info("Окно отключено. Остановка — Ctrl+C.")
        try:
            return app.run()
        except KeyboardInterrupt:
            app.stop()
            return 0

    log.info("Окно предпросмотра: Q/Esc — выход, P — пауза, H — мышь головой")
    return app.run()


def tray_available() -> bool:
    from .tray import available

    return available()


# --------------------------------------------------------------------------- #
#  doctor
# --------------------------------------------------------------------------- #
def cmd_doctor(args: argparse.Namespace) -> int:
    ok = True
    print(f"AirMouse {__version__} | Python {platform.python_version()} | {platform.platform()}")

    def check(title: str, fn, fatal: bool = True) -> None:
        nonlocal ok
        try:
            result = fn()
            print(f"  [ok]   {title}: {result}")
        except Exception as exc:
            if fatal:
                ok = False
                print(f"  [FAIL] {title}: {exc}")
            else:
                print(f"  [ -- ] {title}: {exc}")

    check("numpy", lambda: __import__("numpy").__version__)
    check("opencv", lambda: __import__("cv2").__version__)
    check("mediapipe", lambda: __import__("mediapipe").__version__)
    check("pyautogui", lambda: __import__("pyautogui").__version__)

    cfg = load_config(args.config)
    models = resolve_path(cfg.model_dir)

    def mediapipe_engine():
        """Главная проверка: нейросеть реально поднимается и обрабатывает кадр."""
        import numpy as _np

        from .tracker import MediaPipeTracker

        tracker = MediaPipeTracker(cfg.hand, cfg.face, models)
        try:
            empty = _np.zeros((240, 320, 3), dtype=_np.uint8)
            result = tracker.process(empty, 0)
        finally:
            tracker.close()
        return f"загружена ({tracker.name}/{tracker.api}), рук в пустом кадре: {len(result.hands)}"

    for name in ("hand_landmarker", "face_landmarker"):
        path = models / f"{name}.task"
        size = f"{path.stat().st_size / 1e6:.1f} МБ" if path.exists() else "нет файла"
        print(f"  модель {name}: {size}  ({path})")
    check("нейросеть MediaPipe (модели + движок)", mediapipe_engine)

    if not args.no_camera:
        def camera_probe():
            import cv2

            cap = cv2.VideoCapture(cfg.camera.index)
            if not cap.isOpened():
                raise RuntimeError("камера не открылась (занята, нет разрешения или её нет)")
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if w <= 0 or h <= 0:
                raise RuntimeError("камера вернула пустой размер кадра")
            return f"камера {cfg.camera.index}: {w}x{h}"

        check("камера", camera_probe)

    def screen_probe():
        import pyautogui

        size = pyautogui.size()
        return f"{size.width}x{size.height}"

    check("экран", screen_probe, fatal=False)

    print(f"  конфиг: {args.config or DEFAULT_CONFIG_PATH}")
    print(f"  журнал: {resolve_path(cfg.log_file)}")
    store = TemplateStore(resolve_path(cfg.lip.template_dir))
    print(f"  слова по губам: {store.summary() or 'словарь пуст'}")
    print("\nИтог:", "всё готово" if ok else "есть проблемы — см. выше")
    if not ok:
        print("Подсказка: для классического режима без нейросети запустите")
        print(f'  "{Path(sys.executable).name if getattr(sys, "frozen", False) else "python -m airmouse"}" --backend classical')
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
#  demo
# --------------------------------------------------------------------------- #
def cmd_demo(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    setup_logging(cfg, args.debug)
    from .demo import run_demo

    out = Path(args.out)
    result = run_demo(cfg, out)
    print(f"Демонстрация: {result.frames} кадров, {result.events} событий")
    print(f"  гифка:      {result.gif}")
    print(f"  раскадровка:{result.storyboard}")
    print(f"  журнал:     {result.log}")
    return 0


# --------------------------------------------------------------------------- #
#  models
# --------------------------------------------------------------------------- #
def cmd_models(args: argparse.Namespace) -> int:
    from .models import download_all

    cfg = load_config(args.config)
    paths = download_all(resolve_path(cfg.model_dir), progress=print)
    for name, path in paths.items():
        print(f"{name}: {path} ({path.stat().st_size / 1e6:.1f} МБ)")
    return 0


# --------------------------------------------------------------------------- #
#  lip
# --------------------------------------------------------------------------- #
def _open_face_source(cfg: AppConfig):
    from .camera import ThreadedCamera
    from .tracker import create_tracker

    camera = ThreadedCamera(cfg.camera).start()
    tracker = create_tracker(cfg.tracker, cfg.hand, cfg.face, cfg.model_dir, progress=log.info)
    return camera, tracker


def _grab_face(camera, tracker, timeout: float = 3.0):
    """Ждёт кадр с лицом и возвращает (frame, face, ts_ms)."""
    started = time.monotonic()
    last_seq = -1
    while time.monotonic() - started < timeout:
        frame, _stamp, seq = camera.read()
        if frame is None or seq == last_seq:
            time.sleep(0.004)
            continue
        last_seq = seq
        ts = int((time.monotonic() - started) * 1000)
        res = tracker.process(frame, ts)
        return frame, res.face, ts
    return None, None, 0


def cmd_lip_record(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    setup_logging(cfg, args.debug)
    cfg.lip.enabled = True
    store = TemplateStore(resolve_path(cfg.lip.template_dir))
    camera, tracker = _open_face_source(cfg)
    words = [w.strip() for w in args.word.split(",") if w.strip()]
    print(f"Запись слов: {', '.join(words)}")
    print("Смотрите в камеру, держите лицо в кадре. Рот перед словом должен быть закрыт.")
    saved = 0
    try:
        for word in words:
            for rep in range(args.reps):
                print(f"\n[{word}] повтор {rep + 1}/{args.reps}: приготовьтесь…")
                time.sleep(1.0)
                seq = _record_one(camera, tracker, args.frames)
                if seq is None:
                    print("  не дождался лица — повтор пропущен")
                    continue
                path = store.save(word, seq)
                saved += 1
                print(f"  сохранено: {path}")
    except KeyboardInterrupt:
        print("\n Прервано")
    finally:
        tracker.close()
        camera.stop()

    if args.action:
        cfg.lip.enabled = True
        cfg.lip.words[words[0]] = args.action
        save_config(cfg, args.config)
        print(f"Слово «{words[0]}» привязано к действию «{args.action}»")
    print(f"\nГотово: {saved} записей. Словарь: {store.summary()}")
    return 0


def _record_one(camera, tracker, frames: int, timeout: float = 8.0):
    """Пишет ``frames`` кадров, начиная с момента, когда рот начал открываться."""
    seq = []
    started = time.monotonic()
    triggered = False
    last_seq = -1
    while len(seq) < frames and time.monotonic() - started < timeout:
        frame, _stamp, s = camera.read()
        if frame is None or s == last_seq:
            time.sleep(0.004)
            continue
        last_seq = s
        ts = int((time.monotonic() - started) * 1000)
        face = tracker.process(frame, ts).face
        if face is None:
            continue
        feat = mouth_features(face)
        if feat is None:
            continue
        if not triggered:
            if feat[0] > 0.25:  # раствор рта вырос — слово началось
                triggered = True
            elif time.monotonic() - started > timeout * 0.6:
                triggered = True  # не дождались — пишем как есть
            else:
                continue
        seq.append(feat)
    if len(seq) < frames:
        return None
    return np.stack(seq)


def cmd_lip_list(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    store = TemplateStore(resolve_path(cfg.lip.template_dir))
    summary = store.summary()
    if not summary:
        print("Словарь пуст. Запишите слова: python -m airmouse lip record -w \"стоп\"")
        return 0
    print(f"Каталог шаблонов: {store.dir}")
    for word, count in summary.items():
        action = cfg.lip.words.get(word, "—")
        print(f"  «{word}»: {count} записей -> {action}")
    return 0


def cmd_lip_remove(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    store = TemplateStore(resolve_path(cfg.lip.template_dir))
    removed = store.remove(args.word)
    cfg.lip.words.pop(args.word, None)
    save_config(cfg, args.config)
    print(f"Удалено записей: {removed}")
    return 0


def cmd_lip_test(args: argparse.Namespace) -> int:
    import cv2

    cfg = load_config(args.config)
    setup_logging(cfg, args.debug)
    cfg.lip.enabled = True
    store = TemplateStore(resolve_path(cfg.lip.template_dir))
    reader = LipReader(
        store,
        window_frames=cfg.lip.window_frames,
        stride_s=cfg.lip.stride_s,
        max_distance=cfg.lip.max_distance,
        band=cfg.lip.band,
    )
    if not reader.vocabulary:
        print("Словарь пуст — сначала запишите слова.")
        return 1
    print(f"Словарь: {reader.vocabulary}. Говорите слова беззвучно, Q — выход.")
    camera, tracker = _open_face_source(cfg)
    try:
        while True:
            frame, _stamp, seq = camera.read()
            if frame is None:
                time.sleep(0.01)
                continue
            ts = int(time.time() * 1000) % 10_000_000
            face = tracker.process(frame, ts).face
            feat = mouth_features(face) if face is not None else None
            now = time.monotonic()
            result = reader.push(feat, now)
            view = frame.copy()
            if result is not None:
                cv2.putText(view, f"{result.word}  d={result.distance:.3f}",
                            (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
                print(f"«{result.word}» d={result.distance:.4f} "
                      f"(второе: {result.runner_up} {result.runner_up_distance:.4f})")
            cv2.putText(view, "Q - quit", (20, view.shape[0] - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
            cv2.imshow("AirMouse lip test", view)
            if (cv2.waitKey(1) & 0xFF) in (27, ord("q")):
                break
    finally:
        tracker.close()
        camera.stop()
        cv2.destroyAllWindows()
    return 0


# --------------------------------------------------------------------------- #
#  config / autostart / selftest
# --------------------------------------------------------------------------- #
def cmd_config(args: argparse.Namespace) -> int:
    if args.action == "show":
        cfg = load_config(args.config)
        path = Path(args.config or DEFAULT_CONFIG_PATH)
        print(f"# {path}")
        print(path.read_text(encoding="utf-8") if path.exists() else "{}")
        return 0
    cfg = load_config(args.config)
    for pair in args.values:
        if "=" not in pair:
            print(f"ожидалось key=value, получено: {pair}")
            return 2
        key, value = pair.split("=", 1)
        try:
            new = set_value(cfg, key.strip(), value.strip())
        except (KeyError, ValueError) as exc:
            print(f"{key}: {exc}")
            return 2
        print(f"{key} = {new}")
    path = save_config(cfg, args.config)
    print(f"Сохранено: {path}")
    return 0


def _autostart_command() -> str:
    """Команда автозапуска: для EXE — сам EXE, для исходников — pythonw + скрипт."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}" --no-window --tray'
    script = app_root() / "run_airmouse.py"
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else python
    return f'"{exe}" "{script}" --no-window --tray'


def cmd_autostart(args: argparse.Namespace) -> int:
    if platform.system() != "Windows":
        print("Автозапуск реализован только для Windows (реестр HKCU\\...\\Run).")
        print("Для Linux добавьте .desktop-файл в ~/.config/autostart вручную.")
        return 1
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
        if args.action == "install":
            winreg.SetValueEx(key, "AirMouse", 0, winreg.REG_SZ, _autostart_command())
            print(f"Добавлено в автозапуск: {_autostart_command()}")
        elif args.action == "remove":
            try:
                winreg.DeleteValue(key, "AirMouse")
                print("Удалено из автозапуска")
            except FileNotFoundError:
                print("Записи не было")
        else:
            try:
                value, _ = winreg.QueryValueEx(key, "AirMouse")
                print(f"Автозапуск включён: {value}")
            except FileNotFoundError:
                print("Автозапуск выключен")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Быстрая самопроверка логики без камеры и без ОС."""
    from .selftest import run_selftest

    return run_selftest(verbose=True)


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="airmouse",
        description="Управление мышью жестами рук, мимикой и «чтением по губам».",
    )
    parser.add_argument("--version", action="version", version=f"AirMouse {__version__}")
    parser.add_argument("--config", type=str, default=None, help="путь к JSON конфигурации")
    parser.add_argument("--debug", action="store_true")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="запустить управление (по умолчанию)")
    run.add_argument("--camera", type=int, default=None, help="номер камеры")
    run.add_argument("--video", type=str, default=None, help="видеофайл вместо камеры")
    run.add_argument("--backend", choices=["auto", "mediapipe", "classical", "none"])
    run.add_argument("--no-window", action="store_true", help="работать в фоне без окна")
    run.add_argument("--tray", action="store_true", default=True,
                     help="иконка в трее в фоновом режиме (по умолчанию включена)")
    run.add_argument("--dry-run", action="store_true", help="ничего не нажимать (для отладки)")
    run.add_argument("--no-face", action="store_true", help="не использовать мимику")
    run.add_argument("--head-mouse", action="store_true", help="сразу включить «мышь головой»")
    run.add_argument("--gaze-mouse", action="store_true",
                     help="сразу включить «мышь глазами» (курсор от зрачков)")
    run.add_argument("--lip", action="store_true", help="включить чтение по губам")
    run.add_argument("--output", type=str, default=None, help="сохранять последний кадр в файл")
    run.add_argument("--warmup", type=float, default=None,
                     help="секунды разминки без действий (по умолчанию 2)")

    demo = sub.add_parser("demo", help="синтетическая демонстрация без камеры")
    demo.add_argument("--out", type=str, default="output", help="каталог для гифки и раскадровки")

    doc = sub.add_parser("doctor", help="проверить окружение и нейросеть")
    doc.add_argument("--no-camera", action="store_true", help="не трогать камеру (для CI)")
    sub.add_parser("models", help="скачать модели MediaPipe")
    sub.add_parser("selftest", help="прогнать самопроверку логики")

    lip = sub.add_parser("lip", help="словарь чтения по губам")
    lip_sub = lip.add_subparsers(dest="lip_action")
    rec = lip_sub.add_parser("record", help="записать слово")
    rec.add_argument("-w", "--word", required=True, help="слово или список через запятую")
    rec.add_argument("--reps", type=int, default=8, help="сколько повторов записать")
    rec.add_argument("--frames", type=int, default=None, help="кадров в записи")
    rec.add_argument("--action", type=str, default=None,
                     help="действие для слова (left_click, toggle_pause, key:space, ...)")
    lip_sub.add_parser("list", help="показать словарь")
    rm = lip_sub.add_parser("remove", help="удалить слово")
    rm.add_argument("--word", required=True)
    lip_sub.add_parser("test", help="проверка распознавания в реальном времени")

    conf = sub.add_parser("config", help="показать/изменить конфигурацию")
    conf_sub = conf.add_subparsers(dest="action")
    conf_sub.add_parser("show")
    cset = conf_sub.add_parser("set")
    cset.add_argument("values", nargs="+", help="key=value")

    auto = sub.add_parser("autostart", help="автозапуск при входе в Windows")
    auto.add_argument("action", choices=["install", "remove", "status"])

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.debug = getattr(args, "debug", False)

    if args.command in (None, "run"):
        if not hasattr(args, "camera"):
            args = parser.parse_args((argv or []) + ["run"])
        return cmd_run(args)
    if args.command == "demo":
        return cmd_demo(args)
    if args.command == "doctor":
        return cmd_doctor(args)
    if args.command == "models":
        return cmd_models(args)
    if args.command == "selftest":
        return cmd_selftest(args)
    if args.command == "lip":
        action = getattr(args, "lip_action", None)
        if action == "record":
            if args.frames is None:
                cfg = load_config(args.config)
                args.frames = cfg.lip.window_frames
            return cmd_lip_record(args)
        if action == "list":
            return cmd_lip_list(args)
        if action == "remove":
            return cmd_lip_remove(args)
        if action == "test":
            return cmd_lip_test(args)
        parser.print_help()
        return 2
    if args.command == "config":
        if args.action == "set" and not getattr(args, "values", None):
            print("нужно хотя бы одно key=value")
            return 2
        return cmd_config(args)
    if args.command == "autostart":
        return cmd_autostart(args)
    parser.print_help()
    return 2


def _fatal(exc: BaseException) -> None:
    """Сообщить о фатальной ошибке так, чтобы её увидели и в EXE без консоли."""
    try:
        log.exception("Критическая ошибка: %s", exc)
    except Exception:
        pass
    crash = _write_crash_log(exc)
    message = f"{type(exc).__name__}: {exc}"
    if crash is not None:
        message += f"\n\nПодробности: {crash}"
    # MessageBox блокирует процесс до нажатия кнопки — в CI и на серверах
    # так нельзя, иначе сборка «зависает».
    headless = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))
    if platform.system() == "Windows" and not headless:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, message, "AirMouse — ошибка", 0x10
            )
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def _ensure_std_streams() -> None:
    """Приводим sys.stdout/sys.stderr в рабочее состояние.

    Две реальные проблемы, найденные на сборке EXE:

    * в оконной сборке PyInstaller ``sys.stdout``/``sys.stderr`` = ``None`` —
      любая печать (``--version``, ``--help`` от argparse) падала с
      ``AttributeError`` и EXE молча закрывался;
    * консоль Windows по умолчанию кодирует вывод в cp866/cp1252 — русский
      текст ронял процесс с ``UnicodeEncodeError``. Поэтому принудительно
      переключаем потоки на UTF-8 с заменой неподдерживаемых символов.
    """
    devnull = None
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            if devnull is None:
                devnull = open(os.devnull, "w", encoding="utf-8", errors="replace")
            setattr(sys, name, devnull)
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # поток без поддержки reconfigure — не критично
                pass


def _write_crash_log(exc: BaseException) -> Optional[Path]:
    """Складываем traceback рядом с приложением, чтобы было что прислать."""
    try:
        logs_dir = resolve_path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / "crash.log"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=fh)
        return path
    except Exception:
        return None


def run_main(argv: Optional[List[str]] = None) -> int:
    """Точка входа для EXE и скриптов: ловит фатальные ошибки и показывает их."""
    _ensure_std_streams()
    try:
        return main(argv)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        return 0
    except BaseException as exc:  # noqa: BLE001 - на верхнем уровне ловим всё
        _fatal(exc)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_main())
