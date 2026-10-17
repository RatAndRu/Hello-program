"""
pwa.py — установка приложения на телефон и «Поделиться» в системном меню.

Собрано из bridge (share_target, причём РАЗНЫЙ для телефона и ПК; перехват
share-запроса в service worker), LanguageYOI (страница «Получено через
Поделиться», /service-worker.js), Трекер/Телепульт/SHADOW GAME (manifest,
sw.js, иконки), BLIND_PC (QR на панель с телефона).

КЛЮЧЕВЫЕ ЗНАНИЯ, ВШИТЫЕ В КОД
-----------------------------
* Android Chrome из системного «Поделиться» для локальных IP (http://192.168…)
  отдаёт ТОЛЬКО текст и ссылки (политика безопасности), а файлы — нет.
  Поэтому для мобильных делаем share_target GET (text/url), а для ПК —
  POST multipart (файлы). Решение из bridge.
* iOS/Safari не умеет POST-share: POST перехватывается в service worker и
  превращается в fetch — иначе Safari показывает пустую страницу. Решение из bridge.
* Android/iOS не отдадут «Поделиться» через приложение на http:// локальном IP
  ни при каких настройках — поэтому в интерфейсе нужна честная подсказка
  (вкладка «Файлы» + установка PWA), а не борьба с браузером.
* manifest и sw.js нужно отдавать БЕЗ кэша, иначе после правок PWA «залипает»
  на старой версии. HTML — тоже no-store (см. flask_integration).
* `launch_handler: focus-existing` — повторный запуск ярлыка на телефоне не
  плодит копии, а фокусирует уже открытое окно (приём bridge).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

# Что принимаем из системного «Поделиться» на ПК
DEFAULT_SHARE_ACCEPT = [
    "image/*", "video/*", "audio/*", "text/*",
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".svg", ".ico", ".heic",
    ".mp4", ".mov", ".webm", ".mkv", ".avi",
    ".mp3", ".wav", ".ogg", ".m4a", ".flac",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".csv", ".rtf", ".md", ".zip", ".7z",
]

SW_FILENAME = "sw.js"
MANIFEST_FILENAME = "manifest.json"


# ── manifest ────────────────────────────────────────────────────────────────

def share_target_mobile(action: str = "/api/share") -> dict:
    """GET-вариант: Android из «Поделиться» умеет отдавать только текст/ссылку."""
    return {"action": action, "method": "GET",
            "params": {"title": "title", "text": "text", "url": "url"}}


def share_target_desktop(action: str = "/api/share",
                         accept: Iterable[str] | None = None) -> dict:
    """POST-вариант с файлами (Chrome/Edge на ПК)."""
    return {
        "action": action,
        "method": "POST",
        "enctype": "multipart/form-data",
        "params": {
            "title": "title", "text": "text", "url": "url",
            "files": [{"name": "files", "accept": list(accept or DEFAULT_SHARE_ACCEPT)}],
        },
    }


def build_manifest(*, name: str, short_name: str | None = None, app_id: str | None = None,
                   description: str = "", start_url: str = "/?source=pwa", scope: str = "/",
                   theme_color: str = "#0f1628", background_color: str = "#0f1626",
                   icons: dict[str, str] | None = None, share_action: str = "/api/share",
                   share_files: bool = False, lang: str = "ru",
                   display: str = "standalone", orientation: str = "any",
                   prefer_share_target: bool = True) -> dict:
    """Собирает manifest.json по стандарту.

    icons — словарь {путь: "192"|"512"}: PWA требует минимум 192 и 512,
    а maskable-иконку Android использует для «круглой» маски на рабочем столе.
    """
    icons = icons or {"/static/icon-192.png": "192", "/static/icon-512.png": "512",
                      "/static/icon-192-maskable.png": "192", "/static/icon-512-maskable.png": "512"}
    # short_name показывают под иконкой на телефоне: 12+ символов обрезаются,
    # поэтому режем по границе слова, а не посередине.
    short = (short_name or name).strip()
    if len(short) > 12:
        short = short[:12].rsplit(" ", 1)[0].strip() or short[:12]
        if len(short) < 4:
            short = (short_name or name)[:12]
    icon_list = []
    for src, sizes in icons.items():
        purpose = "maskable" if "maskable" in str(src) else "any"
        icon_list.append({"src": src, "sizes": f"{sizes}x{sizes}", "type": "image/png",
                          "purpose": purpose})
    manifest: dict = {
        "name": name,
        "short_name": short,
        "description": description,
        "lang": lang,
        "start_url": start_url,
        "scope": scope,
        "display": display,
        "display_override": ["window-controls-overlay", "standalone", "minimal-ui"],
        "orientation": orientation,
        "background_color": background_color,
        "theme_color": theme_color,
        "icons": icon_list,
        "launch_handler": {"client_mode": "focus-existing"},
    }
    if app_id:
        manifest["id"] = app_id            # якорь обновлений: не плодит вторую копию PWA
    if prefer_share_target:
        # Один manifest на оба случая не подходит: выбираем по User-Agent на сервере
        manifest["share_target"] = share_target_desktop(share_action) if share_files \
            else share_target_mobile(share_action)
    return manifest


def manifest_json(**kwargs) -> str:
    return json.dumps(build_manifest(**kwargs), ensure_ascii=False, indent=2)


# ── service worker ──────────────────────────────────────────────────────────

def service_worker_js(*, cache_name: str, version: str, precache: Iterable[str] = (),
                      offline_url: str = "/offline.html", share_action: str = "/api/share",
                      network_first_api: bool = True) -> str:
    """Готовый sw.js (текст). Пишется в static/ или отдаётся Flask-маршрутом.

    Логика:
      * install  — кладём в кэш оболочку приложения и активируемся сразу;
      * activate — удаляем старые версии кэша (иначе телефон «залипает»);
      * share POST — перехватываем ДО обращения к сети (iOS/Safari иначе ломается);
      * навигация — сеть → кэш → offline-страница (данные на ПК всегда свежие);
      * статика — кэш → сеть с фоновым обновлением (мгновенная загрузка);
      * API — только сеть (нельзя кэшировать состояние).
    """
    precache_list = json.dumps([str(p) for p in precache], ensure_ascii=False)
    return f"""/* Автогенерировано appcore/pwa.py — не редактировать вручную.
   Приложение: {cache_name} | версия: {version} */
const CACHE = "{cache_name}-{version}";
const PRECACHE = {precache_list};
const OFFLINE_URL = "{offline_url}";

self.addEventListener("install", (event) => {{
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE).catch(() => null)));
}});

self.addEventListener("activate", (event) => {{
  event.waitUntil((async () => {{
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();     // новые страницы сразу под контролем SW
  }})());
}});

self.addEventListener("fetch", (event) => {{
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;   // в чужое не лезем

  // 1) «Поделиться» с ПК (POST): перехватываем ДО сети — требование iOS/Safari.
  if (request.method === "POST" && url.pathname === "{share_action}") {{
    event.respondWith((async () => {{
      try {{
        const form = await request.formData();
        await fetch("{share_action}", {{ method: "POST", body: form }});
      }} catch (err) {{ /* уйдёт страница с подсказкой */ }}
      return new Response(
        "<!doctype html><meta charset='utf-8'><script>" +
        "setTimeout(function(){{ if (window.history.length > 1) {{ window.history.back(); }}" +
        " else {{ window.location.href = '/?shared=ok'; }} }}, 400);</script>" +
        "<body style='font-family:system-ui;background:#0f1626;color:#eaeefb;padding:24px'>" +
        "Готово. Можно закрыть окно.</body>", {{ status: 200, headers: {{ "Content-Type": "text/html; charset=utf-8" }} }});
    }})());
    return;
  }}

  // 2) Навигация: свежие данные с ПК важнее офлайна.
  if (request.mode === "navigate") {{
    event.respondWith((async () => {{
      try {{
        return await fetch(request);
      }} catch (err) {{
        const cached = await caches.match(request);
        return cached || (await caches.match(OFFLINE_URL)) || Response.error();
      }}
    }})());
    return;
  }}

  // 3) API — состояние не кэшируем никогда (данные на ПК всегда свежие).
  if (url.pathname.startsWith("/api/")) {'{'}
    return;
  }}

  // 4) Статика: из кэша мгновенно, обновление — в фоне.
  if (request.method === "GET") {{
    event.respondWith((async () => {{
      const cached = await caches.match(request);
      const network = fetch(request).then((response) => {{
        if (response && response.ok && response.type === "basic") {{
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => null);
        }}
        return response;
      }}).catch(() => null);
      return cached || (await network) || Response.error();
    }})());
  }}
}});
"""


OFFLINE_HTML = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Нет связи с ПК</title>
<style>
  body{margin:0;min-height:100dvh;display:grid;place-items:center;background:#0f1626;color:#eaeefb;
       font:16px/1.5 system-ui,Segoe UI,sans-serif;text-align:center;padding:24px}
  .card{max-width:420px;background:#131c33;border:1px solid #223055;border-radius:16px;padding:28px}
  h1{font-size:20px;margin:0 0 8px} p{color:#9fb0d6;margin:0 0 16px}
  button{background:#2f6fed;color:#fff;border:0;border-radius:10px;padding:10px 18px;font-size:15px;cursor:pointer}
</style></head>
<body><div class="card">
  <h1>Нет связи с компьютером</h1>
  <p>Проверьте, что приложение запущено на ПК и телефон в той же Wi-Fi сети.</p>
  <button onclick="location.reload()">Повторить</button>
</div></body></html>
"""


# ── иконки ──────────────────────────────────────────────────────────────────

def icon_svg(letter: str = "A", *, background: str = "#0d6efd",
             foreground: str = "#ffffff", size: int = 512) -> str:
    """Векторная иконка без зависимостей (можно положить рядом с проектом)."""
    text = (letter or "A")[:2]
    font_size = int(size * 0.5) if len(text) == 1 else int(size * 0.38)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">'
            f'<rect width="{size}" height="{size}" rx="{int(size*0.2)}" fill="{background}"/>'
            f'<text x="50%" y="50%" dy=".35em" text-anchor="middle" '
            f'font-family="Segoe UI,Arial,sans-serif" font-weight="700" '
            f'font-size="{font_size}" fill="{foreground}">{text}</text></svg>')


def ensure_icons(static_dir: str | Path, letter: str = "A", *,
                 background: tuple = (13, 110, 253), foreground: tuple = (255, 255, 255),
                 logger=None) -> dict[str, str]:
    """Создаёт иконки PWA 192/512 + maskable + favicon + apple-touch (идемпотентно).

    Возвращает {имя: путь}. Если Pillow нет — создаёт хотя бы .svg, чтобы
    интерфейс не терял картинку (плюс предупреждение в лог).
    """
    static_dir = Path(static_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}

    svg_path = static_dir / "icon.svg"
    try:
        svg_path.write_text(icon_svg(letter, background="#" + "".join(f"{c:02x}" for c in background),
                                     foreground="#" + "".join(f"{c:02x}" for c in foreground)),
                            encoding="utf-8")
        result["icon.svg"] = str(svg_path)
    except OSError:
        pass

    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as exc:
        if logger:
            logger.warning("Иконки PNG не созданы (нет Pillow: %s). "
                           "Установите: python -m pip install pillow", exc)
        return result

    def _draw(size: int, *, maskable: bool = False):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        pad = int(size * 0.1) if maskable else int(size * 0.02)
        draw.rounded_rectangle([pad, pad, size - pad, size - pad],
                               radius=0 if maskable else int(size * 0.18),
                               fill=tuple(background) + (255,))
        font = None
        for name in ("segoeui.ttf", "arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype(name, int(size * (0.42 if maskable else 0.5)))
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        text = (letter or "A")[:2]
        try:
            box = draw.textbbox((0, 0), text, font=font)
            draw.text(((size - (box[2] - box[0])) / 2 - box[0],
                       (size - (box[3] - box[1])) / 2 - box[1]), text,
                      fill=tuple(foreground) + (255,), font=font)
        except Exception:
            draw.text((size * 0.3, size * 0.25), text, fill=tuple(foreground) + (255,), font=font)
        return img

    sizes = {
        "icon-192.png": (192, False), "icon-512.png": (512, False),
        "icon-192-maskable.png": (192, True), "icon-512-maskable.png": (512, True),
        "icon-180.png": (180, False), "favicon-32.png": (32, False),
        "icon-64.png": (64, False),
    }
    for name, (size, maskable) in sizes.items():
        path = static_dir / name
        try:
            if path.exists() and path.stat().st_size > 0:
                result[name] = str(path)
                continue
            _draw(size, maskable=maskable).save(path, "PNG")
            result[name] = str(path)
        except Exception as exc:
            if logger:
                logger.warning("Не удалось создать %s: %s", name, exc)
    try:
        ico = static_dir / "icon.ico"
        if not ico.exists():
            _draw(64).save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
            result["icon.ico"] = str(ico)
    except Exception:
        pass
    if logger:
        logger.info("Иконки PWA готовы: %d файлов в %s", len(result), static_dir)
    return result


def index_head_snippet(*, title: str, theme_color: str = "#0f1628",
                       manifest_url: str = "/manifest.json", sw_url: str = "/sw.js") -> str:
    """Готовый набор <head>-тегов для PWA (копируется в шаблон)."""
    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="{theme_color}">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="{title}">
<link rel="manifest" href="{manifest_url}">
<link rel="icon" href="/static/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/static/icon-180.png">
<title>{title}</title>
<script>
  // Регистрация SW с версией: ?v= сбрасывает старый кэш при обновлении приложения.
  if ("serviceWorker" in navigator) {{
    navigator.serviceWorker.register("{sw_url}?v=" + Date.now(), {{ scope: "/" }}).catch(() => {{}});
  }}
</script>"""


def share_button_js() -> str:
    """JS-кнопка «Поделиться» с фолбэком на копирование (bridge/LanguageYOI).

    navigator.share работает только в secure context (https или localhost).
    На http://192.168… он недоступен — тогда показываем копирование ссылки.
    """
    return """async function shareApp(url, title) {
  try {
    if (navigator.share) {           // телефон/Edge: системное меню «Поделиться»
      await navigator.share({ title: title, url: url });
      return "shared";
    }
  } catch (err) { /* пользователь закрыл меню — это норма */ }
  try {
    await navigator.clipboard.writeText(url);
    return "copied";
  } catch (err) {
    const area = document.createElement("textarea");
    area.value = url; document.body.appendChild(area); area.select();
    document.execCommand("copy"); area.remove();
    return "copied";
  }
}"""


def write_static_assets(static_dir: str | Path, **manifest_kwargs) -> dict[str, str]:
    """Раскладывает manifest.json + sw.js в static/ (для отдачи как статики).

    Flask-вариант (динамический manifest по User-Agent) — в flask_integration.
    """
    static_dir = Path(static_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    try:
        target = static_dir / MANIFEST_FILENAME
        target.write_text(manifest_json(**manifest_kwargs), encoding="utf-8")
        written[MANIFEST_FILENAME] = str(target)
    except OSError:
        pass
    return written


def file_version(path: str | Path) -> str:
    """Версия ассетов по mtime — для cache-busting в тегах <script>/<link>."""
    try:
        return str(int(os.path.getmtime(path)))
    except OSError:
        return "0"
