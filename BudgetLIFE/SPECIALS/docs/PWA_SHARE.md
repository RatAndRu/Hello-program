# PWA: установка на телефон, «Поделиться», QR, офлайн

Локальные приложения из этого репозитория — это веб-приложения, которые
устанавливаются на телефон как обычные приложения (PWA). Здесь собрано всё, что
было выяснено в проектах `bridge`, `LanguageYOI`, `Трекер`, `Телепульт`,
`SHADOW GAME`, `BLIND_PC`, плюс то, что реализовано в `appcore.pwa`.

---

## 1. Что должно быть у каждого проекта

| Элемент | Зачем | Где |
|---|---|---|
| `/manifest.json` | имя, иконки, режим `standalone`, `share_target` | `pwa.build_manifest` |
| `/sw.js` | офлайн, кэш статики, перехват «Поделиться» | `pwa.service_worker_js` |
| `/offline.html` | «нет связи с ПК» вместо белого экрана | `pwa.OFFLINE_HTML` |
| иконки 192/512 + `maskable` | установка на Android и «круглая» маска | `pwa.ensure_icons` |
| `theme-color`, `apple-touch-icon` | цвет статус-бара, иконка на iOS | `pwa.index_head_snippet` |
| `no-store` для HTML | правки видны сразу, старая версия не залипает | `flask_integration.install` |
| `no-store` для `/sw.js` | новый service worker подхватывается сразу | там же |

---

## 2. «Поделиться» из системного меню

### Две разные формы — и почему

| Платформа | Форма `share_target` | Что дойдёт |
|---|---|---|
| Android (Chrome) | `method: "GET"` (params: title/text/url) | **только текст и ссылки** |
| Windows (Chrome/Edge) | `method: "POST"`, `enctype: multipart/form-data` | файлы любого типа |

Это не мелочь: Android из-за политики безопасности **не отдаёт файлы** приложению,
работающему по `http://` на локальном IP. Поэтому манифест формируется **на сервере
с учётом User-Agent** — так сделано в `bridge/app.py` (`/manifest.json` отдаёт
GET-вариант телефону и POST-вариант ПК). В `appcore` за это отвечает
`flask_integration.install` + `pwa.share_target_mobile/desktop`.

### Перехват POST в service worker (критично для iOS)

Safari не умеет отправлять POST-форму в `share_target` так, как это делает Chrome.
Поэтому в `sw.js` стоит обработчик:

```js
if (request.method === "POST" && url.pathname === "/api/share") {
  event.respondWith((async () => {
    const form = await request.formData();          // забираем данные ДО сети
    await fetch("/api/share", { method: "POST", body: form });
    return new Response("<script>window.close()</script>", { headers: {...} });
  })());
  return;
}
```

Приём из `bridge/app.py` (`sw.js`: «Caught share request!»). Без него iOS
показывает пустую страницу вместо результата.

### Что делать с принятым

`flask_integration.save_share` складывает в `data/shared/`:
* текст/ссылки → `share-ГГГГММДД-ЧЧММСС.txt`;
* файлы → `<дата>-<имя>` (имя очищается через `Path(name).name` — защита от
  `../../windows/system32` из чужого имени файла).

Для GET-запроса (открыт браузер) отдаётся человеческая страница «Получено через
«Поделиться»» (как `LanguageYOI/templates/share.html`), для fetch — JSON.

### Кнопка «Поделиться» внутри интерфейса

`navigator.share` доступен только в защищённом контексте (`https` или `localhost`).
По `http://192.168…` его нет → нужен фолбэк на копирование (`pwa.share_button_js`).
Именно поэтому в интерфейсе кнопка сначала пробует `navigator.share`, а потом
`navigator.clipboard` и `document.execCommand("copy")`.

---

## 3. Иконки

`pwa.ensure_icons(static_dir, letter)` создаёт (идемпотентно, без файлов в репозитории):

```
icon-192.png  icon-512.png            — purpose: any
icon-192-maskable.png  icon-512-maskable.png  — purpose: maskable (Android-маска)
icon-180.png  favicon-32.png  icon-64.png  icon.ico
icon.svg                               — запасной вариант, если Pillow нет
```

Приём Трекера и BLIND_PC: приложение генерирует иконки само при первом запуске —
не бывает ситуации «не хватает файла, поэтому PWA не устанавливается». Логотип
задаётся буквой (`APP_LETTER`), как в эталонном проекте.

---

## 4. Кэш и версии (самое частое место ошибок)

1. `/sw.js` отдаётся с `Cache-Control: no-store` и `Service-Worker-Allowed: /`.
   Иначе браузер кэширует сам service worker, и правки не доходят **никогда**.
2. HTML отдаётся с `no-store` (`flask_integration`): веб-интерфейс локального
   приложения не должен кэшироваться — данные и разметка меняются каждый день.
3. В `index.html` регистрация идёт с версией: `sw.js?v=<timestamp>` — приём
   `bridge/templates/index.html`. Старый SW вытесняется, новый активируется
   (`skipWaiting` + `clients.claim`).
4. API (`/api/...`) **никогда не кэшируется** — состояние живёт на ПК.
5. Навигация: сеть → кэш → `offline.html`. Данные на ПК важнее мгновенности.
6. Статика: кэш → сеть с фоновым обновлением (мгновенная загрузка и «свежесть»).

---

## 5. Установка на устройствах

| Платформа | Как установить | Нюанс |
|---|---|---|
| Android / Chrome | меню ⋮ → «Установить приложение» | PWA и `share_target` работают; на локальном IP «Поделиться» отдаёт только текст |
| iPhone / Safari | «Поделиться» → «На экран Домой» | **нет** `beforeinstallprompt`, `navigator.share` доступен; PWA по http работает с ограничениями, iOS может требовать https |
| Windows / Chrome, Edge | иконка ⊕ в адресной строке | с ПК-версией `share_target` работает приём файлов |
| Приложение закрыто | ничего не откроется | PWA не заменяет сервер: приложение на ПК должно быть запущено |

Поэтому в интерфейсе есть честная подсказка (взято из `bridge/templates/index.html`):
Android — «меню ⋮», iPhone — «Поделиться → На экран Домой», ПК — «иконка ⊕»,
а для файлов с телефона — вкладка «Файлы» (не бороться с политикой браузера).

---

## 6. QR-код: как телефон попадает на страницу

* `netutil.local_ip()` — адрес в Wi-Fi сети (UDP-трюк, не требует интернета);
* `netutil.qr_png_bytes(url)` — PNG, `qr_svg_text(url)` — SVG; **работают всегда**:
  сначала пробуется пакет `qrcode`, а если его нет — свой кодировщик `appcore.qr`
  (чистый Python + `zlib`, без Pillow). Так `/api/qr` не отвечает отказом 501
  ни на одной машине;
* `netutil.save_qr(url, data/"qr")` — сохраняет картинку рядом с приложением;
* маршрут `/api/qr` (в `flask_integration`) отдаёт PNG (или SVG, если PNG не
  получился) и заголовок `X-QR-Target`.

Приём BLIND_PC: пункт трея «QR-код» — самый быстрый способ открыть приложение на
телефоне (не нужно диктовать IP). DnD's дополнительно отдаёт QR страницы игрока, а
swipe_review — SVG без бинарных зависимостей.

---

## 7. Мобильный интерфейс (проверенные мелочи)

Из `BLIND_PC/static/index_mobile.html`, `Телепульт/static/*` и `bridge`:

* `viewport-fit=cover` + `env(safe-area-inset-*)` — не залезать под «бровь» и жесты iPhone;
* крупные кнопки (минимум ~44 px по высоте) и `touch-action: manipulation`
  (убирает задержку 300 мс и случайный зум);
* `-webkit-tap-highlight-color: transparent` — нет серых вспышек;
* `100dvh` вместо `100vh` — корректная высота при появлении адресной строки;
* индикатор связи: `window.addEventListener("online"/"offline")` + бейдж «нет связи с ПК»;
* никакого `innerHTML` с пользовательским текстом (в эталоне — `textContent`) — XSS;
* тёмная тема и крупный шрифт по умолчанию — как в LanguageYOI/bridge.

---

## 8. Безопасность PWA-доступа

* Приложение с телефоном по умолчанию слушает `127.0.0.1`; вывод в сеть —
  осознанное решение (`--host 0.0.0.0 --lan`) + правило брандмауэра
  `profile=private remoteip=localsubnet` (см. `docs/PORTS.md`, раздел 6).
* Для управления ПК (мышь, клавиатура, буфер обмена) — только с токеном.
  Образец: `bridge` — пароль → `secrets.token_urlsafe(32)` → cookie + список
  устройств в `data/devices.json`; отзыв устройства удалением записи.
* Никогда не выводить приложение в публичную сеть: `profile=private` это и
  гарантирует, а `remoteip=localsubnet` ограничивает даже гостевую сеть.
