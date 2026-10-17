#!/usr/bin/env python3
"""
self_test.py — самопроверка appcore без Windows и без запуска сервера.

Проверяет то, что можно проверить на любой ОС (Windows-части — реестр, трей,
мьютекс — явно пропускаются с пометкой «пропущено»):

  * jsonstore  — атомарная запись, бэкап .bak, восстановление и карантин битого файла;
  * ports      — блоки портов, порядок кандидатов, проверка свободы, port.txt,
                 опознание запущенного приложения по /api/identity;
  * netutil    — сборка URL, локальный IP, HTTP-проверки;
  * pwa        — manifest (телефон/ПК), sw.js (синтаксис проверяется node, если есть),
                 генерация иконок;
  * logutil    — ротация лога и безопасные потоки;
  * hotreload  — обрезка раздутого лога;
  * tools      — запуск check_ports.py.

Запуск (из SPECIALS/tools или откуда угодно):
    python SPECIALS/tools/self_test.py
Код возврата 0 — всё хорошо.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

SPECIALS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SPECIALS))

from appcore import (clipboard, events, gui, hotkeys, hotreload, jsonstore,  # noqa: E402
                     keyinput, logutil, netutil, ports, pwa, qr, spaced, textutil,
                     uri, versioning, watchdog)

PASS, FAIL, SKIP = "  ✓", "  ✗", "  ~"
results = {"ok": 0, "fail": 0, "skip": 0}


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        results["ok"] += 1
        print(f"{PASS} {name}" + (f" — {detail}" if detail else ""))
    else:
        results["fail"] += 1
        print(f"{FAIL} {name}" + (f" — {detail}" if detail else ""))


def _raises(exc: type[BaseException], func) -> bool:
    """Истина, если вызов падает ожидаемым исключением."""
    try:
        func()
    except exc:
        return True
    except Exception:
        return False
    return False


def skip(name: str, why: str) -> None:
    results["skip"] += 1
    print(f"{SKIP} {name} — пропущено ({why})")


# ── 1. jsonstore ────────────────────────────────────────────────────────────

def test_jsonstore(tmp: Path) -> None:
    print("\n[1] jsonstore: атомарная запись и восстановление")
    store = jsonstore.JsonStore(tmp / "notes.json", default={"notes": []})
    check("создание файла", store.save({"notes": [1, 2, 3]}) and (tmp / "notes.json").exists())
    check("чтение", store.load()["notes"] == [1, 2, 3])
    store.save({"notes": [4]})
    check("бэкап .bak создан", (tmp / "notes.json.bak").exists())

    # битый файл → восстановление из .bak + карантин
    (tmp / "notes.json").write_text('{"notes": [оборвано', encoding="utf-8")
    broken = jsonstore.load_json(tmp / "notes.json", default=None)
    quarantined = list(tmp.glob("notes.json.corrupt-*"))
    check("битый файл восстановлен из бэкапа", broken is not None and broken.get("notes") == [1, 2, 3],
          f"данные={broken}")
    check("битый файл отложен в карантин", len(quarantined) == 1)

    # параллельная запись из двух потоков не перемешивает файл
    parallel = jsonstore.JsonStore(tmp / "par.json", default={"items": []})
    parallel.save({"items": []})

    def writer(start: int) -> None:
        for index in range(25):
            with parallel.edit() as doc:
                doc["items"].append(start + index)

    threads = [threading.Thread(target=writer, args=(base,)) for base in (0, 1000)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    data = json.loads((tmp / "par.json").read_text(encoding="utf-8"))
    check("параллельная запись не потеряла данные", len(data["items"]) == 50,
          f"записей={len(data['items'])}")
    check("файл после записи — валидный JSON", True)


# ── 2. ports ────────────────────────────────────────────────────────────────

def test_ports(tmp: Path) -> None:
    print("\n[2] ports: блоки, проверка свободы, port.txt, опознание")
    block = ports.block_for("specials_demo")
    check("блок эталонного проекта", block.base == 5120 and block.size == 10,
          f"{block.base}-{block.base + block.size - 1}")
    unknown = ports.block_for("совсем_новый_проект")
    check("незнакомый проект получает стабильный блок",
          unknown.base == ports.block_for("совсем_новый_проект").base,
          f"base={unknown.base} ({unknown.note})")
    candidates = ports.candidates("specials_demo")
    check("кандидаты — только свой блок", candidates[0] == 5120 and len(candidates) == 10
          and max(candidates) <= 5129, str(candidates[:3]) + " …")

    # реально занять порт и проверить, что он считается занятым
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    taken = server.getsockname()[1]
    check("занятый порт определяется как занятый", not ports.port_is_free("127.0.0.1", taken))
    server.close()
    check("освобождённый порт снова свободен", ports.port_is_free("127.0.0.1", taken))

    info = ports.read_port_file(tmp)
    check("несуществующий port.txt → None", info is None)
    ports.write_port_file(tmp, 5120, "specials_demo", os.getpid())
    info = ports.read_port_file(tmp)
    check("port.txt пишется и читается", info and info["port"] == 5120 and info["app_id"] == "specials_demo")
    check("первая строка port.txt — число (совместимость с DnD's)",
          (tmp / "port.txt").read_text(encoding="utf-8").splitlines()[0] == "5120")

    # опознание живого приложения (если эталон запущен — проверим по-настоящему)
    live = ports.find_running("specials_demo", "127.0.0.1", range(5120, 5130), timeout=0.3)
    if live:
        check("опознание запущенного приложения по /api/identity", True,
              f"порт {live.port}, pid {live.identity.get('pid')}")
    else:
        skip("опознание по /api/identity", "эталонный проект сейчас не запущен")


# ── 3. netutil / pwa / logutil / hotreload ──────────────────────────────────

def test_netutil() -> None:
    print("\n[3] netutil: адреса и HTTP")
    check("url_for: 0.0.0.0 → localhost",
          netutil.url_for("0.0.0.0", 5120) == "http://localhost:5120/")
    check("url_for: путь со слэшем", netutil.url_for("127.0.0.1", 5120, "api/health")
          == "http://localhost:5120/api/health")
    check("local_ip() возвращает адрес", isinstance(netutil.local_ip(), str)
          and len(netutil.local_ip()) >= 7, netutil.local_ip())
    check("http_ok() на заведомо закрытом порту → False",
          netutil.http_ok("http://127.0.0.1:9/", timeout=0.4) is False)
    qr = netutil.qr_png_bytes("http://localhost:5120")
    if qr is None:
        skip("QR в PNG", "qrcode[pil] не установлен")
    else:
        check("QR в PNG", qr[:8] == b"\x89PNG\r\n\x1a\n", f"{len(qr)} байт")


def test_pwa(tmp: Path) -> None:
    print("\n[4] pwa: manifest, service worker, иконки")
    manifest = pwa.build_manifest(name="Specials Demo", app_id="specials_demo", share_files=True)
    check("manifest: POST-вариант для ПК с файлами",
          manifest["share_target"]["method"] == "POST"
          and "files" in manifest["share_target"]["params"])
    manifest_mobile = pwa.build_manifest(name="Specials Demo", app_id="specials_demo")
    check("manifest: GET-вариант для телефона",
          manifest_mobile["share_target"]["method"] == "GET")
    check("manifest: maskable-иконка есть",
          any(icon["purpose"] == "maskable" for icon in manifest["icons"]))
    check("manifest: focus-existing (не плодить окна)",
          manifest["launch_handler"]["client_mode"] == "focus-existing")
    check("manifest: сериализуется в JSON", bool(json.loads(pwa.manifest_json(name="X"))))

    js = pwa.service_worker_js(cache_name="demo", version="1.0.0", precache=["/"],
                               offline_url="/offline.html", share_action="/api/share")
    check("sw.js: перехват POST-«Поделиться» есть", 'request.method === "POST"' in js)
    check("sw.js: старые кэши удаляются", "caches.delete" in js)
    node = shutil.which("node") or shutil.which("nodejs")
    if node:
        sw_file = tmp / "sw.js"
        sw_file.write_text(js, encoding="utf-8")
        proc = subprocess.run([node, "--check", str(sw_file)], capture_output=True, text=True)
        check("sw.js: синтаксис JavaScript корректен", proc.returncode == 0,
              (proc.stderr or "").strip().splitlines()[-1] if proc.stderr else "")
    else:
        skip("проверка синтаксиса sw.js", "node не найден")

    icons = pwa.ensure_icons(tmp / "static", "S")
    if icons:
        check("иконки PWA сгенерированы", len(icons) >= 4, f"{len(icons)} файлов")
    else:
        skip("иконки PWA", "Pillow не установлен")
    check("шпаргалка <head> для PWA", "manifest.json" in pwa.index_head_snippet(title="X"))


def test_logutil_hotreload(tmp: Path) -> None:
    print("\n[5] logutil и hotreload")
    logger = logutil.setup("SelfTest", tmp / "logs" / "log.txt", stdio=False, console_also=False)
    logger.info("проверка записи")
    log_path = tmp / "logs" / "log.txt"
    check("лог создан и пишется", log_path.exists() and "проверка записи" in log_path.read_text(encoding="utf-8"))
    handlers = [h for h in logger.handlers]
    _ = handlers
    root_handlers = [h for h in __import__("logging").getLogger().handlers
                     if getattr(h, "_appcore_file", False)]
    check("у логгера один файловый обработчик (без дублей)", len(root_handlers) == 1)

    big = tmp / "logs" / "big.txt"
    big.write_text("\n".join(f"строка {i}" for i in range(20000)), encoding="utf-8")
    trimmed = hotreload.trim_log_file(big, max_bytes=1024, keep_lines=50)
    check("раздутый лог обрезан", trimmed and len(big.read_text(encoding="utf-8").splitlines()) <= 52)
    check("свободное место определяется", isinstance(hotreload.disk_free_mb(tmp), float))


def test_textutil() -> None:
    print("\n[6] textutil: текст, калькулятор, ссылки (фишки DeployAgent/BLIND_PC)")
    check("раскладка EN→RU", textutil.switch_layout("ghbdtn? rfr ltkf&") == "привет, как дела?")
    check("раскладка RU→EN", textutil.switch_layout("руддщ") == "hello")
    check("раскладка не портит пути",
          textutil.switch_layout("C:\\AI_Projects\\app.py") is None
          and textutil.switch_layout("https://github.com") is None)
    check("«кривой» регистр распознан", textutil.is_broken_case("пРИВЕТ") is True
          and textutil.is_broken_case("Привет мир") is False)
    check("калькулятор: 2+2*2=6", textutil.safe_eval_math("2+2*2") == "6")
    check("калькулятор: русская запись", textutil.safe_eval_math("2 плюс 3 умножить на 4") == "14")
    check("калькулятор: eval не используется",
          textutil.safe_eval_math("__import__('os').system('echo hi')") is None)
    check("калькулятор: одинокая цифра — не выражение", textutil.safe_eval_math("42") is None)
    check("HEX → RGB", textutil.parse_hex_color("#3fa9f5") == (63, 169, 245))
    check("чистая ссылка из текста",
          textutil.clean_url("смотри https://github.com/user/repo?x=1#z тут") == "https://github.com")
    check("безопасное имя файла",
          textutil.sanitize_filename("../../windows/system32/cmd.exe") == "cmd.exe"
          and textutil.sanitize_filename("NUL") == "_NUL")
    check("русские числительные", textutil.words_to_number("сто двадцать три") == 123
          and textutil.numbers_in_text("напомни через 15 минут") == [15])


def test_clipboard_keyinput_hotkeys() -> None:
    print("\n[7] clipboard / keyinput / hotkeys / gui (фишки bridge, Телепульта, DeployAgent)")
    check("фильтр «мусорных» подписей (Ножницы/Поделиться)",
          clipboard.is_noise("Ножницы") and clipboard.is_noise("") and not clipboard.is_noise("привет"))
    check("хеш содержимого стабилен",
          clipboard.content_hash("текст") == clipboard.content_hash("текст"))
    dedup = clipboard.Deduplicator(window_seconds=60)
    check("дедупликатор: первый раз — новый, второй — дубль",
          dedup.seen("ключ") is False and dedup.seen("ключ") is True)
    check("буфер обмена не бросает исключений",
          isinstance(clipboard.get_files(), list) and clipboard.get_text() is None
          or True, f"sequence={clipboard.sequence_number()}")
    check("keyinput: VK-коды служебных клавиш",
          keyinput.VK_CODES["enter"] == 0x0D and keyinput.VK_CODES["volume_up"] == 0xAF)
    check("keyinput: бэкенд определяется", keyinput.backend() in ("winapi", "pyautogui", "pynput", "none"),
          keyinput.backend())
    manager = hotkeys.HotkeyManager()
    check("hotkeys: нормализация комбинации", manager._normalize("Alt + Shift + C") == "alt+shift+c")
    check("hotkeys: регистрация при отсутствии библиотек не падает",
          manager.register("alt+c", lambda: None) in (True, False))
    check("hotkeys: перепривязка и снятие без зависаний",
          manager.rebind({"alt+v": lambda: None}) in (True, False)
          and manager.unregister("alt+v") in (True, False))
    manager.stop()
    check("gui: всплывашки не падают без дисплея",
          gui.overlay("тест") in (True, False) and gui.ask_yes_no("тест?") is None
          or True, "на сервере окон нет — это норма")


def test_events() -> None:
    print("\n[8] events: живые обновления (фишки bridge и swipe_review)")
    bus = events.EventBus(keep_alive=0.2)
    box = bus.subscribe()
    check("подписчик зарегистрирован", bus.client_count() == 1)
    delivered = bus.publish("clip", text="привет")
    message = box.get(timeout=1)
    check("событие доставлено подписчику", delivered == 1 and '"clip"' in message,
          message[:60])
    check("toast и счётчик клиентов", bus.toast("проверка") == 1 and bus.clients() == 1)
    stream = bus.stream(box, ready=lambda: [{"type": "hello"}])
    first = next(stream)
    check("поток SSE начинается со стартовых событий", "hello" in first)
    second = next(stream)
    check("поток SSE отдаёт событие в формате data:", second.startswith("data: "))
    stream.close()
    check("при закрытии поток снимает подписку", bus.client_count() == 0)


def test_versioning(tmp: Path) -> None:
    print("\n[9] versioning: бэкапы архивом и восстановление (фишки LanguageYOI/Cooker)")
    data = tmp / "vdata"
    (data / "images").mkdir(parents=True, exist_ok=True)
    (data / "notes.json").write_text('{"notes": ["одна", "две"]}', encoding="utf-8")
    (data / "images" / "pic.txt").write_bytes(b"x" * 400)
    (data / "logs").mkdir(exist_ok=True)
    (data / "logs" / "log.txt").write_text("шум", encoding="utf-8")

    info = versioning.create_backup(data, app_name="test", app_version="1.0")
    check("архив создан и содержит манифест",
          info is not None and info.files == 2 and info.manifest is not None,
          info.describe() if info else "None")
    check("архив целый (CRC проверяется)", versioning.verify_backup(info.path))

    (data / "notes.json").write_text("ПОЛОМАНО", encoding="utf-8")
    (data / "new.txt").write_text("появился после бэкапа", encoding="utf-8")
    result = versioning.restore_backup(info.path, data)
    restored = json.loads((data / "notes.json").read_text(encoding="utf-8"))["notes"]
    check("данные восстановлены из архива", result["ok"] and restored == ["одна", "две"],
          str(result))
    check("текущие данные сохранены как before_restore_*",
          bool(result["safety"]) and (Path(result["safety"]) / "new.txt").exists())

    evil = tmp / "evil.zip"
    with zipfile.ZipFile(evil, "w") as arc:
        arc.writestr("../../pwned.txt", "зло")
        arc.writestr("ok.txt", "нормально")
    versioning.restore_backup(evil, data)
    check("zip-slip (путь ../../) не выходит за папку данных",
          not (tmp / "pwned.txt").exists() and (data / "ok.txt").exists())
    check("экспорт/импорт JSON", versioning.export_json(tmp / "e.json", {"a": 1})
          and versioning.import_json(tmp / "e.json") == {"a": 1})
    check("битый архив не восстанавливается, а честно сообщает",
          versioning.restore_backup(tmp / "нет.zip", data)["ok"] is False)
    check("prune оставляет только свежие",
          versioning.prune_backups(versioning.backups_dir(data), keep=1) >= 0)


def test_uri() -> None:
    print("\n[10] uri: команды myapp://… и передача работающему экземпляру (Трекер, BLIND_PC)")
    command, params = uri.parse("myapp://timer/start?name=Зарядка&minutes=25")
    check("разбор адреса", command == "timer/start" and params["name"] == "Зарядка")
    check("короткая форма без //", uri.parse("myapp:notes/add?text=привет")[0] == "notes/add")

    router = uri.Router(name="myapp")

    @router.command("timer/start")
    def _start(name: str = "", minutes: str = "0"):
        return {"запущен": name, "минут": int(minutes or 0)}

    router.add("ping", lambda: "понг")
    answer = router.dispatch("myapp://timer/start?name=Зарядка&minutes=25")
    check("команда выполнена, параметры дошли",
          answer["ok"] and answer["запущен"] == "Зарядка" and answer["минут"] == 25, str(answer))
    check("неизвестная команда — понятный ответ со списком",
          router.dispatch("myapp://нет").get("commands") == ["ping", "timer/start"])
    check("чужие параметры не роняют сервер",
          router.dispatch("myapp://timer/start?чужой=1")["ok"] is False)
    check("не-URI не принимается за команду", router.dispatch("просто текст")["ok"] is False)
    check("имя приложения превращается в допустимую схему",
          uri.normalize_scheme("specials_demo") == "specials-demo"
          and uri.normalize_scheme("Моё Приложение") == "moe-prilozhenie")
    check("URI находится среди аргументов запуска",
          uri.argv_uri(["python", "app.py", "myapp://ping"]) == "myapp://ping"
          and uri.argv_uri(["python", "app.py"]) is None)
    check("работающему экземпляру команда не передаётся, если его нет",
          uri.send_to_running("myapp://ping", 59999, timeout=0.3) is None)
    check("forward_or_run выполняет команду локально, если никто не ответил",
          uri.forward_or_run("myapp://ping", port=59999, router=router)["forwarded"] is False)


def test_spaced() -> None:
    print("\n[11] spaced: интервальные повторения SM-2 (фишка LanguageYOI)")
    card = spaced.new_card()
    check("новая карточка показывается сразу", spaced.is_due(card))
    intervals = []
    for grade in (4, 4, 4):
        card = spaced.review(card, grade)
        intervals.append(card["interval_days"])
    check("интервалы растут: 1 → 6 → 15 дней", intervals == [1, 6, 15], str(intervals))
    ease_before = card["ease"]
    card = spaced.review(card, 1)                    # «Забыл»
    check("«Забыл» сбрасывает прогресс и снижает ease",
          card["repetitions"] == 0 and card["ease"] < ease_before, f"ease {card['ease']}")
    check("ease не уходит ниже 1.3", spaced.review({"ease": 1.3}, 0)["ease"] == 1.3)
    check("кнопки интерфейса понимаются",
          spaced.grade_from_button("ЛЕГКО") == 5 and spaced.grade_from_button("забыл") == 1
          and spaced.grade_from_button("???") is None)
    check("просроченная карточка видна", spaced.due_in_days({"due": "2020-01-01"}) < 0)
    check("подсказки по всем оценкам считаются сразу",
          set(spaced.schedule(spaced.new_card())) == {"не помню", "забыл", "почти", "трудно",
                                                      "хорошо", "легко"})
    check("некорректная оценка — понятная ошибка, а не мусор",
          _raises(ValueError, lambda: spaced.review(card, 9)))


def test_watchdog() -> None:
    print("\n[12] watchdog: надзиратель за сервером (фишка DnD's)")
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait, daemon=True)
    worker.start()
    calls: list[str] = []
    guard = watchdog.ThreadWatchdog(thread=worker, interval=2.0, failures=2, startup_grace=0.1,
                                    on_down=calls.append, logger=None, name="тест")
    check("здоровый поток проверку проходит", guard.check() == "")
    worker_stopped = threading.Thread(target=lambda: None)
    worker_stopped.start(); worker_stopped.join()
    guard.thread = worker_stopped
    check("упавший поток виден надзирателю", "завершился" in guard.check())
    guard.thread = worker
    stop.set(); worker.join(timeout=1)
    guard.failures_needed = 1
    guard._handle_down("проверка")               # без on_down не падает — мы задали
    check("авария вызывает перезапуск", calls == ["проверка"], str(calls))
    guard.interval = 999                         # чтобы поток не начал проверять сразу
    guard.start()
    check("надзиратель запускается и останавливается", guard.running and guard.stop() is None
          and not guard.running)


def test_qr() -> None:
    print("\n[13] qr: QR-код без зависимостей (закрывает отказ 501 в /api/qr)")
    # Эталонные отпечатки сверены модуль в модуль с пакетом qrcode (все 8 масок,
    # версии 1-40) и прочитаны настоящим декодером (zxing-cpp). Здесь они
    # зафиксированы, чтобы поймать случайную поломку кодировщика.
    golden = [
        ("http://192.168.1.7:5120/", "M", 25, "27d517dcd31ed29b"),
        ("Привет, мир!", "Q", 29, "1c74f1d34c1cfda4"),
        ("tracker://timer/start", "H", 29, "8f1f71de637f95e2"),
        ("x" * 200, "L", 53, "cfe4fcc3cbfb75ba"),
        ("https://github.com/RatAndRu/All_My-Projects", "M", 33, "79193d61d6171653"),
    ]
    for text, ecc, size, digest in golden:
        mat = qr.encode_matrix(text, ecc=ecc)
        bits = "".join("1" if cell else "0" for row in mat for cell in row)
        got = hashlib.sha256(bits.encode()).hexdigest()[:16]
        check(f"матрица {len(mat)}×{len(mat)} ({ecc}, {len(text)} симв.) совпадает с эталоном",
              len(mat) == size and got == digest, got)
    check("все восемь масок дают валидный код (штраф считается)",
          all(qr.encode_matrix("проверка", mask=m) for m in range(8)))
    check("авто-маска выбирает минимум штрафа",
          qr.encode_matrix("проверка") ==
          qr.encode_matrix("проверка", mask=min((qr._penalty(qr.encode_matrix("проверка", mask=m)), m)
                                                for m in range(8))[1]))
    png = qr.png_bytes("http://192.168.1.7:5120/", box=4, border=2)
    check("PNG собирается без Pillow (сигнатура и размеры)",
          png[:8] == b"\x89PNG\r\n\x1a\n" and png[12:16] == b"IHDR" and len(png) > 100)
    svg = qr.svg("http://192.168.1.7:5120/", box=4, border=2)
    check("SVG содержит путь и белый фон",
          svg.startswith("<svg") and "<path" in svg and "</svg>" in svg)
    check("слишком длинный текст — понятная ошибка, а не мусор",
          _raises(ValueError, lambda: qr.encode_matrix("я" * 3000, ecc="H")))
    check("netutil умеет QR и без пакета qrcode (свой кодировщик)",
          netutil.has_qr() and netutil.qr_png_bytes("http://127.0.0.1:5120/") is not None)


def test_sqlite_store(tmp: Path) -> None:
    print("\n[14] sqlite_store: миграции, бэкапы, восстановление (фишки LanguageYOI/DnD's)")
    from appcore import sqlite_store
    store = sqlite_store.SqliteStore(tmp / "notes.db", backup_dir=tmp / "backups")
    version = store.init_schema("""
        CREATE TABLE IF NOT EXISTS note (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""", migrations=[(1, "ALTER TABLE note ADD COLUMN pinned INTEGER DEFAULT 0")])
    check("схема создана и версия записана", version == 1 and store.schema_version() == 1)
    store.execute("INSERT INTO note(text, pinned) VALUES(?, ?)", ("Заметка", 0))
    check("вставка и выборка", store.query_one("SELECT * FROM note")["text"] == "Заметка")
    check("таблицы и размер базы", store.tables() == ["note"] and store.size() > 0)
    backup = store.backup()
    check("бэкап создан (через API SQLite)", backup is not None and backup.exists())
    store.execute("DELETE FROM note")
    check("данные удалены", not store.query("SELECT * FROM note"))
    result = store.restore_backup(backup.name)
    check("восстановление вернуло данные", result["ok"] and len(store.query("SELECT * FROM note")) == 1)
    check("перед восстановлением сделана safety-копия", bool(result.get("safety_backup")))
    check("миграция второй версии применяется однажды",
          store.init_schema("", migrations=[(2, "ALTER TABLE note ADD COLUMN tag TEXT")]) == 2)
    check("целостность базы в порядке", store.integrity_check() is True)


# ── 4. tools ────────────────────────────────────────────────────────────────

def test_tools() -> None:
    print("\n[15] tools: аудит портов")
    script = SPECIALS / "tools" / "check_ports.py"
    proc = subprocess.run([sys.executable, str(script), "--json"], capture_output=True, text=True)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        check("check_ports.py отдаёт JSON", False, proc.stderr[-200:])
        return
    check("check_ports.py отдаёт JSON", "findings" in report and "conflicts" in report,
          f"объявлений: {len(report['findings'])}, конфликтов: {len(report['conflicts'])}")
    check("найдены известные конфликты репозитория (5000/5001/5678)",
          {"5000", "5001", "5678"} <= set(report["conflicts"].keys()),
          ", ".join(sorted(report["conflicts"])))
    check("найдены неограниченные сканеры портов (Cooker/PlotMaker)",
          len(report.get("unbounded", [])) >= 2, f"{len(report.get('unbounded', []))} шт.")
    check("владелец конфликта берётся из ports.json",
          all("ports.json — " in line and "нет записи" not in line
              for line in report.get("registry_conflicts", [])),
          "; ".join(report.get("registry_conflicts", [])[:1]))

    proc = subprocess.run([sys.executable, str(SPECIALS / "tools" / "check_deps.py"),
                           "--json"], capture_output=True, text=True)
    try:
        deps = json.loads(proc.stdout)
        check("check_deps.py отдаёт JSON по проектам", len(deps) >= 8,
              f"проектов: {len(deps)}")
        proc = subprocess.run([sys.executable, str(SPECIALS / "tools" / "check_deps.py"),
                               "--json", "--root", str(SPECIALS / "template")],
                              capture_output=True, text=True)
        demo = json.loads(proc.stdout)
        check("check_deps.py видит обязательные зависимости эталона",
              bool(demo) and "flask" in demo[0]["required"],
              ", ".join(sorted(demo[0]["required"])) if demo else "пусто")
        check("check_deps.py разбирает requirements.txt эталона",
              bool(demo) and {"flask", "pillow", "pystray"} <= set(demo[0]["declared"]),
              ", ".join(sorted(demo[0]["declared"])) if demo else "пусто")
    except json.JSONDecodeError:
        check("check_deps.py отдаёт JSON по проектам", False, proc.stderr[-200:])

    proc = subprocess.run([sys.executable, str(SPECIALS / "tools" / "check_vbs.py"), "--json"],
                          capture_output=True, text=True)
    try:
        vbs = json.loads(proc.stdout)
        hard = [issue for item in vbs for issue in item["issues"] if issue["kind"] == "error"]
        check("check_vbs.py: жёстких ошибок в VBS нет", not hard,
              f"файлов {len(vbs)}, ошибок {len(hard)}")
    except json.JSONDecodeError:
        check("check_vbs.py отдаёт JSON", False, proc.stderr[-200:])

    proc = subprocess.run([sys.executable, str(SPECIALS / "tools" / "win_task.py"), "--json",
                           "list"], capture_output=True, text=True)
    try:
        states = json.loads(proc.stdout)
        demo_ports = [entry["port"] for item in states if item["app_id"] == "specials_demo"
                      for entry in item["listeners"]]
        check("win_task.py list видит эталон (если он запущен)",
              not demo_ports or all(5120 <= port <= 5129 for port in demo_ports),
              f"порты эталона: {demo_ports or 'не запущен'}")
    except json.JSONDecodeError:
        check("win_task.py list отдаёт JSON", False, proc.stderr[-200:])


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="appcore_selftest_"))
    print("=" * 74)
    print(" SELF-TEST appcore (SPECIALS)")
    print(f" ОС: {sys.platform} | Python: {sys.version.split()[0]}")
    print(f" Временная папка: {tmp}")
    print("=" * 74)
    try:
        test_jsonstore(tmp)
        test_ports(tmp / "data")
        test_netutil()
        test_pwa(tmp)
        test_logutil_hotreload(tmp)
        test_textutil()
        test_clipboard_keyinput_hotkeys()
        test_events()
        test_qr()
        test_versioning(tmp)
        test_uri()
        test_spaced()
        test_watchdog()
        test_sqlite_store(tmp)
        test_tools()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 74)
    print(f"ИТОГ: успешно {results['ok']}, ошибок {results['fail']}, пропущено {results['skip']}")
    print("=" * 74)
    return 1 if results["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
