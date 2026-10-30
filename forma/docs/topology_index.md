# Индекс: всё для нейросети-разработчика ФОРМА 3D

Что это: единая точка входа во все результаты аудита топологии. Документ
разделён на три категории, которые нельзя смешивать:

* **A. Алгоритмы и математические модели** — что считать и как, с числами.
* **B. Автоматика без мышления ИИ** — работает всегда, сама, с порогом и откатом.
* **C. Инструменты выбора ИИ** — нейросеть решает, когда их применять, и это
  решение описано таблицей «когда / как / чего не делать».

Ветка: `arena/4e8fdd4f-hello-program`. Все ссылки — на GitHub, без песочных
адресов. Для загрузки в модель удобнее `raw`: замените `/blob/` на `/raw/`.

---

## 1. Карта документов

| # | Документ | Что внутри | Разделов |
|---|---|---|---|
| 1 | [topology_automation.md](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/topology_automation.md) | главный отчёт: что приложение делает само, план P0–P2, контракт для ИИ, 15 кодов дефектов | 8 |
| 2 | [topology_kernel_guarantees.md](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/topology_kernel_guarantees.md) | что ядро гарантирует, что реально ломается (с замерами), судьба проверок и инструментов | 5 |
| 3 | [topology_human_face.md](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/topology_human_face.md) | тело, голова, лицо: петли, полюса, плотности, тесты деформации | 6 |
| 4 | [mesh_economy.md](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/mesh_economy.md) | экономия полигонов: закон хорды, 9 приёмов, бюджеты, 8 метрик | 7 |
| 5 | [topology_autofix_spec.md](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/topology_autofix_spec.md) | спецификация: модули, пороги, псевдокод лечения, гейт на экспорте, план на 10 шагов | 9 |
| 6 | [topology_guide.md](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/topology_guide.md) | базовый гайд (877 строк), из него выросли пункты 1–5 | — |
| 7 | [editor_geometry_audit.md](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/editor_geometry_audit.md) | как устроен редактор геометрии | — |
| 8 | [smoothing_transitions.md](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/smoothing_transitions.md) | скругления и переходы | — |
| 9 | [modeling_prompt_ru.md](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/modeling_prompt_ru.md) | действующий промпт ИИ-моделировщика | — |

Схемы (SVG, встраиваются в документы):

* [img/mesh_chord_error.svg](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/img/mesh_chord_error.svg) — хорда и число сегментов;
* [img/face_loops.svg](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/img/face_loops.svg) — карта петель лица, правильно/неправильно;
* [img/topology_bad_good.svg](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/img/topology_bad_good.svg) — пять дефектов и лечение;
* генератор схем: [make_topology_svg.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/docs/make_topology_svg.py).

---

## 2. Категория A — алгоритмы и математические модели

Всё считается по массивам `verts (V,3)` и `faces (T,3)`, без внешних
библиотек кроме numpy.

| Модель | Формула / правило | Где описано |
|---|---|---|
| Ошибка хорды | `s = r·(1 − cos(π/n)) ≈ r·π²/(2n²)`; `n = ⌈π/arccos(1 − s/r)⌉` | mesh_economy §1 |
| Сегменты по допуску | печать 0.1–0.2 мм, SLA 0.05, рендер 0.05–0.1, фон 0.3–0.5 | mesh_economy §1 |
| Длина ребра к размеру инструмента | `edge ≤ 1/3` диаметра инструмента | mesh_economy §3.5 |
| Бюджет по классу объекта | 200–2 000 (мелочь) … 40 000–150 000 (герой) | mesh_economy §4 |
| Сварка для диагностики | квантование `round(v/eps)`, `eps = max(1e-4, 0.1·diag·1e-6)` | autofix §1.1 |
| Карта рёбер | `counts==1` граница, `==2` норма, `>2` non-manifold | autofix §1.2 |
| Вырожденность | `area < (1e-4·median_edge)²`, относительно, не абсолютно | autofix §1.3 |
| Оболочки и род | `χ = V − E + F`, `g = (2 − χ)/2`, знак объёма | autofix §1.4 |
| Иглы | `min_angle < 3°`; отдельно **плоские** (двугранный ≤ 5°) и **на изгибе** | autofix §1.6 |
| Плотность | `p5/p50/p95` длин рёбер, `ratio = p95/p5`, доля рёбер < 0.05 мм | autofix §1.7 |
| Порог «игл на изгибе» | ≤ 1 % площади для печати, ≤ 0.2 % для деформации | autofix §2 |
| Допуск упрощения | `simplify(tolerance)` с гарантией двустороннего отклонения Хаусдорфа | mesh_economy §2, ядро |
| LOD | 100 / 50 / 25 / 12 % при допусках 0 / 0.05 / 0.1 / 0.2 мм | autofix §3.4 |
| Тесты деформации | 8 поз (отведение 90/180°, сгиб локтя 135°, колено 120°, кулак, шея 60°…) | human_face §5 |
| Плотность головы | мобилка 1–3 k, игра 4–8 k, герой 15–40 k, кино 40 k+; лицо — 60–70 % | human_face §6 |
| Кратность петель | кольцо конечности кратно 4 (переходы 2-1, 4-1) | human_face §2 |

**Ключевой вывод A.** Ошибка падает как `1/n²`, а полигоны растут как `n`:
удвоение сегментов даёт вчетверо меньше ошибки. Значит плотность задаётся
допуском, а не привычкой «48 на всё».

---

## 3. Категория B — автоматика без участия нейросети

Каждая строка: **модуль → триггер → порог → действие → откат**. Всё это
выполняется само, даже если ИИ ничего не написал.

| Модуль | Триггер | Порог | Действие | Откат |
|---|---|---|---|---|
| `metrics.analyze()` → блок `topology` | каждый вызов анализа | — | заполняет `Topology` по объекту, кэш `имя:tris` | — |
| `checks.py` | `check` в сценарии/UI | свои пороги | 6 новых правил: `shells, slivers, slivers_bend, poles, edge_spread, topology` | — |
| `sdf.py::mesh_field` | конец SDF-генерации | `set_tolerance(0.25h)`, `simplify`, `smooth_out+refine_to_tolerance` | убирает 3 non-manifold ребра (`alien`) и короткие рёбра | — |
| `heal.py::heal_manifold` | кнопка «Починить», `heal`, импорт | см. §3 spec | 8 шагов: с tolerance → вырожденные → мелкие оболочки → дыры → сглаживание → бюджет | шаг отменяется, если объём ±2 %, габарит ±0.1 мм, род/оболочки изменились |
| `ops_io.export` / `cli export` | любой экспорт | `status == error` | **останавливает** экспорт и пишет `<файл>.topology.json` | пользователь ставит `force=да` |
| `ops_io.import` | импорт внешнего файла | объём ±2 %, `repair=да` | сварка, `fill_holes`, `fix_normals`, воксельный фолбэк | предупреждение, не откат |
| `topology_audit` (CLI) | CI, вручную | 15 кодов | exit 0/1/2, `--json`, `--weld` обязателен | — |
| `heal` идемпотентность | тест | `heal(heal(x)) == heal(x)` | — | — |

Доказательная база порогов — замеры (§4 отчёта): `mug` 41 248 трис / 76.97 %
игл, но на изгибе 0.01 %; `clock` 2 ошибки `degenerate_index`; `alien` 3
non-manifold после сварки; `living_room` 96 граней `lamp_bulb`. Поэтому
`slivers` — «инфо», а `slivers_bend` — реальный порог.

**Чего автоматика не делает никогда** (честные границы):

1. не решает, какой формы должен быть объект;
2. не ставит полюса и петли — в треугольной сетке ФОРМА 3D их нет;
3. не заменяет ретопологию под скиннинг — только предупреждает;
4. не угадывает назначение: пороги зависят от `purpose`.

---

## 4. Категория C — инструменты, которые выбирает ИИ

Здесь нейросеть думает. Задача таблицы — снять с неё угадывание: когда
инструмент нужен, как его вызвать, чего он не делает.

| Инструмент | Когда применять | Как вызывать | Чего не делать |
|---|---|---|---|
| `refine` | перед мелкой работой (`dent`, `складка`, `emboss`, `гравюра`): ребро крупнее 1/3 инструмента | `деталь = refine [деталь] length=2` | не дробить «на всякий случай»: `levels=4` — это ×256 граней |
| `simplify` | после SDF/импорта/булевой, когда треугольников больше бюджета | `деталь = simplify [деталь] deviation=0.2` | не упрощать до потери силуэта; проверять `p95/p5` |
| `clean` | после импорта, после множества булевых | `деталь = clean [деталь]` | не лечит дыры и non-manifold — для них `repair`/`heal` |
| `repair` | дыры после импорта или ручного удаления | `деталь = repair [деталь]` | не применять к своим (замкнутым) телам — там нечего чинить |
| `heal` (новый) | экспорт заблокирован гейтом | `деталь = heal [деталь] purpose=печать` | не запускать на сцене целиком без нужды: дорого |
| `smooth` | лесенка/фасетка от SDF, воксельный фолбэк | `деталь = smooth [деталь] iterations=2` | не сглаживать острые кромки — они «поплывут» |
| `polish` | финиш перед рендером | `деталь = polish [деталь]` | не делать вместо `refine` там, где нужна плотность |
| `weld` | две детали должны стать одним телом | `узел = weld [a] [b]` | не сваривать подвижные посадки |
| `shell` | печать полого, экономия материала | `деталь = shell [деталь] thickness=2` | не делать стенку тоньше 2 диаметров сопла |
| `chamfer` | убить «мыло» на кромке | `деталь = chamfer [деталь] size=0.5 segments=1` | 3 сегмента — только под крупный блик |
| `fillet` | скругление, которое видно в силуэте | `деталь = fillet [деталь] radius=3` | не ставить радиус больше половины меньшей грани |
| `array` | повторяющиеся детали | `ряд = array [деталь] count=12` | не собирать 12 копий 12 операциями |
| `shrinkwrap` | обтянуть одну поверхность другой (одежда, чехол) | `чехол = shrinkwrap [чехол] [тело] offset=1` | не обтягивать незамкнутое тело |
| `lattice` | решётка для печати/облегчения | `каркас = lattice [деталь] cell=8 strut=1.2` | не применять к тонким стенкам: ячейка должна быть в 3 раза меньше |
| `import repair=да` | любой внешний файл | `модель = import "x.stl" repair=да` | не отключать проверку объёма: она ловит вывернутые нормали |
| `export` + `force` | осознанный выпуск с дефектами | `export "x.glb" force=да` | не ставить `force` по умолчанию |

### Порядок выбора (короткое дерево решений)

```
1. Объект новый и из примитивов?      → чинить нечего, идти к форме
2. Пришёл извне (stl/obj/glb)?        → import repair=да → clean → heal
3. Сделан из SDF (blob/from_sdf)?     → heal (tolerance+simplify) → smooth
4. Будет мелкая деталь?               → refine(length ≤ 1/3 инструмента) → деталь
5. Треугольников больше бюджета?      → simplify(deviation) → проверить силуэт
6. Готов к экспорту?                  → гейт сам скажет, что осталось
```

### Что ИИ говорить пользователю

Одна фраза на проблему, с кодом и следующей командой:

> «3 non-manifold ребра после сварки — "пришелец". Это совпавшие вершины из
> SDF-поля. Выполните `пришелец = heal [пришелец]`, либо экспорт с `force=да`,
> если так и задумано.»

---

## 5. Код, на который опирается всё выше

| Файл | Что важно |
|---|---|
| [forma/checks.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/checks.py) | 25 правил `check`, сюда добавляются 6 новых |
| [forma/metrics.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/metrics.py) | `analyze`, `edge_angles`, `tri_quality` (порог 3°), `MetricsCache` |
| [forma/ops_shape.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/ops_shape.py) | `refine` (`length`/`levels`), `simplify` (`tolerance`/`deviation`), `weld`, `shell`, `chamfer`, `fillet` |
| [forma/ops_surface.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/ops_surface.py) | `repair` (веерное зашивание — переписать на grid fill), `smooth`, `polish`, `shrinkwrap`, `lattice` |
| [forma/ops_extra.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/ops_extra.py) | `clean`: сварка дублей, дегенераты, дубли граней |
| [forma/ops_io.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/ops_io.py) | `import repair=да`, воксельный фолбэк, предупреждение при объёме ±2 %; `export` — точка гейта |
| [forma/sdf.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/sdf.py) | `mesh_field`, самописный marching cubes; куда вставлять `set_tolerance` |
| [forma/mesher.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/mesher.py) | `_pad_outside`, `_drop_specks`, `_laplacian_smooth` |
| [forma/primitive_topology.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/primitive_topology.py) | квад-логика (только сферы) |
| [forma/instruction.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/instruction.py) | промпт ИИ: одна строка про `weld/repair/simplify` — расширить |
| [forma/agent.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/forma/agent.py) | пример `check watertight` — тавтология, убрать |
| [tools/topology_audit.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/tools/topology_audit.py) | 15 кодов, `--weld/--min-angle/--max-aspect/--top/--json`, exit 0/1/2 |
| [tests/test_topology_audit.py](https://github.com/RatAndRu/Hello-program/blob/arena/4e8fdd4f-hello-program/forma/tests/test_topology_audit.py) | 10 тестов, проходят |

---

## 6. Ответ на исходный вопрос — в двух абзацах

Гарантия ядра верна **не потому, что «работаем с гранями»**, а потому что все
тела — `mf.Manifold`, а пользовательских операций над вершинами и рёбрами нет.
Отсюда: замкнутость, ровно две грани на ребро, согласованная ориентация,
честный объём. Проверка `check watertight` для своей геометрии — чтение
`stats()["status"]`, то есть тавтология.

Но удалять проверки и инструменты **нельзя**: замеры показали 4 класса реальных
дефектов, которые ядро не ловит по построению — совпавшие вершины из marchig
cubes (`alien`, 3 non-manifold), вырожденные грани (`clock` 2, `living_room` 96),
качество поверхности (`mug` 76.97 % игл) и внешний импорт. Итог: оставить всё,
добавить 6 правил, починить `tri_quality` (разделить «плоско/изгиб»), ввести
гейт на экспорте, переписать `repair` на grid fill и заменить самописный
marching cubes на `Manifold.level_set`.

---

## 7. Как передавать это нейросети-разработчику

1. Сначала — **2** (гарантии) и **5** (спецификация): это границы и контракт.
2. Затем **1** (план работ) — что делать в каком порядке.
3. **3** и **4** — справочники, подключать по надобности, не целиком.
4. Схемы — вставлять в интерфейс подсказок, они объясняют «почему» без текста.

Промпт-затравка:

> Ты — разработчик геометрического ядра ФОРМА 3D. Ядро даёт замкнутые
> многообразия; дефекты приходят от SDF, импорта и вырожденных граней. Внедри
> модуль `forma/topology.py` по спецификации (разделы 1–2), гейт на экспорте
> (раздел 4) и `heal` (раздел 3). Пороги не менять: они получены замерами.
> Каждый шаг лечения обязан откатываться, если объём изменился больше 2 %,
> а род или число оболочек — вообще. Тесты из раздела 7 должны проходить.
