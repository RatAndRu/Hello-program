# ПИКСЕЛЬ — от пикселя к картине

> Параметрический редактор пиксельных картинок и анимаций с нейросетевой детализацией

**Идея:** любой рисунок — это пиксели. На крупной сетке (16×16, 32×32) видны квадраты — это классический пиксель-арт. На плотной сетке (1024×1024+) квадраты сливаются в «обычный растр», фото, аниме-арт. Если научить нейросеть сначала придумать *крупную* пиксельную структуру по тексту или по координатам (x, y, цвет), то потом ей будет легко «уплотнить» сетку и проработать детали, сохранив композицию.

Этот документ — **оценка идеи + план реализации**, сделанный с учётом оформления **ФОРМА 3D v0.72**.

---

## Что берём из ФОРМА 3D напрямую

ФОРМА 3D уже решила 90% задач desktop-приложения, нам остаётся адаптировать:

| Решение ФОРМЫ | Как используем в ПИКСЕЛЬ |
|---|---|
| Тёмная тема `--bg:#0c0f14`, `--panel:#151a22`, `--line:#232b37`, шрифты JetBrains Mono + Inter | Копируем 1-в-1: тот же `app.css` с заменой акцента на пиксельный `#ff7a59` + `#7ee0c0` |
| 3-панельный layout: редактор сценария \| 3D-вьювер \| отчёт, с draggable splitters `panels.js` | Левая — пиксельный холст + палитра + промпт. Центр — превью HD. Правая — таймлайн анимации + отчёт/чеки |
| Topbar: бренд + `▶ Собрать`, `↶/↷`, `Открыть файл`, `Снимки`, `Экспорт`, `Проекты`, `Инструменты`, `?` | Меняем на: `▶ Пиксель` (сгенерировать крупную сетку) → `⬢ Детализация ×2/×4/×8` → `▶ Анимация`, остальное 1-в-1 |
| `webui.py`: `FORMA_TOKEN` в `?token=`, cookie, `_MEIPASS`, `user_data_dir()` рядом с exe | Копируем без изменений, только `APP_NAME = "Пиксель"` |
| Папки рядом с exe: `projects/`, `exports/`, `prompts/`, `textures/` | Аналогично: `projects/`, `exports/`, `palettes/`, `frames/` |
| История действий + `actions[]`, `notes[]`, `command_reference_md()` для отчёта нейросети | Пиксельный журнал: каждый клик по пикселю = запись `пиксель x=12 y=7 #ff0000`, замечание к области = `note kind=область` |
| Выделение кубических секторов `space-card` + `check … в_сетке` | Выделение прямоугольника пикселей `select x=2..8 y=3..6`, проверка `check палитра <=16 цветов` |
| Анимация `animate kind=spin`, `timeline.clips`, `frames[]`, `frame.glb` | Тот же движок, но клипы = `pixel_tween`, `camera_pan`, `detalize`; кадры = PNG/WebM |
| Экспорт GLB/OBJ/STL/PLY/3MF/PNG/DXF/GIF/WebM/ZIP | Экспорт PNG/APNG/GIF/WebM/ASE/SPRITE/ZIP |
| `forma.spec` — PyInstaller без scipy/skimage/Pillow | Повторяем тот же `.spec`: собираем `Пиксель.exe` ~45 МБ |
| Статический стенд `forma/showcase` на Fly.io (Nginx, healthz) | Тот же `fly.toml` → новое приложение `piksel-ratandru.fly.dev` |

**Детали оформления**, которые хвалим и сохраняем:
- Моноширинный gutter с нумерацией строк и подсветкой текущей строки сборки
- Тонкие splitter’ы с grip, сворачиваемые панели (`is-collapsed`)
- Badge’и `poly-badge`, `anim-focus`, `demo-badge`
- Модалки `tools-modal`, `tex-modal`, `preview-modal` с ленивой загрузкой
- Тост `toast`, `history-panel`, `cmd-input` внизу

---

## Быстрый старт (прототип уже в `piksel/web/`)

```bash
cd piksel
python -m http.server 8000 --directory web
# открыть http://localhost:8000
```

Полный Python-сервер (как у ФОРМЫ):
```bash
pip install -r piksel/requirements.txt
python piksel/server.py  # откроет http://127.0.0.1:17833/?token=...
```

Деплой на Fly.io (секрет уже в GitHub Secrets):
```bash
flyctl deploy --config piksel/fly.toml --local-only
```

---

## Структура проекта

```
piksel/
  README.md                 ← этот файл
  docs/idea_analysis.md     ← подробный разбор свежести/надёжности
  web/
    index.html              ← 1-в-1 топология ФОРМЫ, но для пикселей
    css/app.css             ← форк forma/web/css/app.css
    js/app.js               ← холст, палитра, промпт, детализация
    icons/...
  server.py                 ← форк forma/forma/webui.py под пиксели
  requirements.txt
  fly.toml
  packaging/piksel.spec     ← форк forma/packaging/forma.spec
  examples/                 ← .piksel сценарии (текстовые, как .forma)
```

Дальше читай `docs/idea_analysis.md` — там честная оценка и 3 варианта реализации.
