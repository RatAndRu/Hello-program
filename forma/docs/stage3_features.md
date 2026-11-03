# Этап 3: библиотеки, параметры и CAD-обмен

Документ описывает только добавленный набор Forma. Это не переход на FreeCAD,
BRep или SolveSpace и не второй интерпретатор OpenSCAD. Старые сценарии без
новых команд сохраняют прежнюю детализацию и поведение.

## 1. Собственные библиотеки Forma

`include` текстуально подключает `.forma`/`.f3d` относительно исходного файла.
Циклические включения и глубокая рекурсия заканчиваются диагностикой с цепочкой
файлов, а не бесконечным вызовом. Для SCAD используется отдельная команда
`openscad`, а не `include`.

```forma
# lib/plates.forma
function with_margin(x, margin=2) = x + margin
module plate(width=40, height=3) {
    local_width = with_margin(width)
    body = box size=[local_width,20,height]
}

# main.forma
include file="lib/plates.forma"
width = 40
first = plate(width=width, height=3)
second = plate()
```

Функции возвращают число и поддерживают позиционные/именованные аргументы и
значения по умолчанию. Модули исполняют обычные команды Forma в дочернем scope:
локальные присваивания не попадают в параметры родителя, а созданные Solid и
Contour2D возвращаются с уникальными именами. Вложенные определения и рекурсия
ограничены; ошибки содержат строку и контекст вызова.

`Build.payload()` содержит `params`, `parameter_schema`, `presets` и плоский
`provenance`. Это не дерево зависимостей FreeCAD.

## 2. Панель параметров и presets

Числовое присваивание уже становится параметром. Для подписи и границ используйте
`param`; для именованного набора — `preset`:

```forma
param height=95 min=20 max=200 step=1 label="Высота" unit="мм"
preset tall height=140
preset low height=70
preset tall  # явный выбор для последующих команд; без него действует default
body = cylinder radius=35 height=height
```

`preset имя значение=…` только объявляет вариант: несколько наборов не
применяются неявно друг за другом. `preset имя` (или кнопка **Применить**)
выбирает набор до построения следующих тел. Вкладка **Параметры** изменяет
значения через тот же `run_build(overrides=…)`, что и существующий morph.
Explicit `overrides` имеют приоритет над preset и default. `default` сохраняется
отдельно от текущего значения, поэтому кнопка «по умолчанию» возвращает исходную
величину. Preset сохраняется однострочно в сценарии и может быть удалён без
ручного поиска строки; сохранение сразу показывает выбранные значения через
тот же rebuild, но не превращает вариант в автоматически активный при следующем
открытии.

### Размерные зависимости без дерева FreeCAD

Для связанных размеров используется `derive` (синоним `link`). Источник должен
быть объявлен раньше: выражение вычисляется в месте команды, а при rebuild
выполняется снова в том же порядке.

```forma
param base_h=68 min=45 max=100
column_ratio = 1.25
column_h = derive base_h * column_ratio
column_top = derive base_h + column_h
joint_z = derive column_top + 12
колонна = cylinder radius=12 height=column_h at=[0,0,base_h]
шарнир = sphere radius=10 at=[0,0,joint_z]
```

Зависимые значения доступны в `params`, `parameter_schema` и плоском
`dimension_links`, но в панели они read-only: выражение и рассчитанное значение
видны, редактируется источник. Если старый клиент всё же передал override для
зависимого имени, `derive` игнорирует его и вычисляет значение из источника.
Это намеренно не constraint-solver и не история FreeCAD: циклы и forward
references не разрешаются автоматически, а связи остаются короткими и явными.

HTTP:

* `GET /api/parameters` — схема, значения и presets текущей сборки;
* `POST /api/parameters` с `{script, values}` — rebuild;
* `{action:"apply", preset:"tall"}` — применить набор;
* `{action:"save", name:"…", values:{…}}` и `{action:"delete", name:"…"}` —
  изменить сценарий;
* `{action:"reset"}` — вернуть default.

## 3. Нативный SCAD mesh export

Меню **Экспорт → SCAD** и CLI создают настоящий OpenSCAD `polyhedron` с
`points=` и `faces=` из построенного Manifold, в миллиметрах. В ZIP также
включён `.scad`.

```bash
python -m forma export model.forma --format scad --out model.scad
```

Экспортируется **уже построенная сетка**, с координатами доступной точности
Manifold (обычно float32). Исходные выражения, constraints и параметрическое
дерево из итогового mesh не восстанавливаются. Поэтому параметрический
SCAD-round-trip не заявляется. Комментарии и `scad_manifest()` сохраняют
название объекта, операцию, прямых родителей и строку сценария.

## 4. Произвольный SCAD/BOSL2 через фоновый runner

Forma вызывает настоящий OpenSCAD subprocess без GUI, с `-o`, `-D`,
`OPENSCADPATH`, `QT_QPA_PLATFORM=offscreen` и timeout. Проверяются exit code,
непустой файл и читаемая конечная mesh. stderr/stdout, returncode, команда,
число вершин/граней и warnings возвращаются в приложение. Ошибочный результат
не добавляется в сцену.

```forma
# Файл рядом со сценарием или в imports/
detail = openscad file="detail.scad" repair=да

# BOSL2 исполняет OpenSCAD, а не parser Forma.
part = openscad code="include <BOSL2/std.scad>\ncube(10);" libraries="/opt/BOSL2"
```

Также работает `import file="detail.scad"`: для этого расширения Forma
делегирует файл тому же runner. Вкладка **Параметры → OpenSCAD / BOSL2** вызывает
`/api/openscad`; кнопка не открывает внешнее приложение. `GET /api/state` и
`forma doctor` показывают, найден ли executable. Путь можно задать через
`FORMA_OPENSCAD`/`OPENSCAD`.

BOSL2 и другие библиотеки подключаются pinned-каталогом (tag/commit, URL,
SHA-256 и LICENSE/NOTICE должны сопровождать распространяемый asset). Путь
через `OPENSCADPATH` не является разрешением копировать библиотеку в релиз без
проверки лицензии. OpenSCAD stable и nightly/Manifold не смешиваются молча.

В публичном демо `include`, файловый import и OpenSCAD subprocess отключены;
локальная Forma их разрешает.

## 5. Плоский provenance

Для каждого объекта доступны `object`, `operation`, `parents`, `line`, `source`
и укороченная исходная команда. Вкладка **Объекты** показывает только прямые
связи выбранного объекта и позволяет перейти к родителю. Полного дерева всей
модели нет; ограниченная история складок остаётся отдельной и не раздувается в
общий CAD-graph. `GET /api/provenance` возвращает ограниченный плоский список.

## 6. Подгонка размеров по фотографии

`forma.vision.dimension_fit.fit_dimensions()` использует существующие
`silhouette`/`fit_camera`/`render_mask`. Нужны видимая длина репера в пикселях и
миллиметрах; без неё абсолютный масштаб остаётся неизвестным. Возвращаются
`scale`, `values`, `camera`, `target_mm`, `scaled_size`, `residual` (IoU,
row/RMSE, evaluations), `ambiguous` и диагностика.

Вкладка **Параметры → Подгонка размеров по фотографии** принимает PNG/JPEG:
браузер нормализует изображение в PNG, сервер использует собственный декодер.
Можно ограничить поиск выбранными параметрами. При «применить» найденные
значения проходят через общий rebuild, а равномерный реперный масштаб пишется
обычными `scale` в `.forma`. Одна проекция не доказывает скрытую геометрию,
поэтому низкий IoU и близкие альтернативы не скрываются.

API: `POST /api/photo/fit` с `script`, `mask` или base64 PNG, `parameters`,
`reference_length_px`, `reference_length_mm`, `reference_axis`, опционально
`camera`, `apply`.

## 7. Чертёж DXF с размерами

**Экспорт → DXF — чертёж с размерами** использует существующие сечения или
среднее сечение самого крупного видимого тела. Нативный R12 DXF содержит контур,
слой `DIMENSIONS`, block geometry, `DIMENSION`, `TEXT`, фактические ширину и
высоту в мм и witness lines. Внешний CAD не нужен.

```bash
python -m forma export model.forma --format drawing --out model-drawing.dxf
```

Для своих размеров Python API принимает
`{"p1":[x,y], "p2":[x,y], "offset":10, "text":"…"}`.

## 8. Глобальная точность с обратной совместимостью

```forma
precision mode=legacy   # прежнее поведение, default
precision mode=fine     # opt-in: более плотная неявная детализация
precision mode=ultra
precision factor=1.25
```

`draft`, `fine`, `ultra` и пользовательский `factor` влияют на неявную
детализацию через общий `detail_factor` и соответствующие tessellation-пути
(включая lathe и Contour2D). `precision tolerance=0.02` задаёт хордовый допуск
по умолчанию в мм; явный `tolerance=…` конкретной операции остаётся главнее.
Явные `detail=…` и `segments=…` имеют приоритет и не пересчитываются глобальным
множителем. Старый проект без команды `precision` не меняется.

## 9. Бюджет настоящих микрофасок

`lathe` и `extrude` по-прежнему строят дуговые фаски через
`fillet_polyline`; Loop/subdivision smoothing для этого не используется.
`fillet_steps` задаёт верхний бюджет отрезков одной дуги (по умолчанию 8; для компактной лампы выбран 4),
а фактическое число выбирается по хордовому отклонению. Почти коллинеарные
samples плавной исходной дуги не превращаются каждый в отдельную микрофаску.
Для особого случая `fillet_angle=0` принудительно обрабатывает все переломы;
это может закономерно увеличить сетку. Если у `lathe` уже задан `smooth>1` и
новые параметры не указаны, сохраняется прежняя дискретизация профиля: иначе
изменение числа точек до downstream-сглаживания меняет форму (регрессия mug
проверяется отдельно). Явные `fillet_steps`/`fillet_angle` включают новый режим.

```forma
основание = lathe points=[[0,0],[30,0],[30,20],[0,20]] \\
    segments=32 fillet=2 fillet_steps=4
```

Проверять нужно не только `NoError`: сравниваются triangles по деталям,
габарит и объём, а для сборки — все пары пересечений и фактические зазоры.

## Проверки

```bash
python -m pytest -q tests/test_stage3_features.py
python -m pytest -q tests/test_lamp_rework.py tests/test_banker_lamp.py
python -m pytest -q tests/test_rules_upgrade.py
node --check web/js/app.js
```

Targeted-набор проверяет не только отсутствие исключений: реальные Manifold,
GLB/API, SCAD/DXF байты, плоские родительские связи, baseline и residual
фото-подгонки, а также subprocess-контракт runner. Исполняемый fake-CLI в тесте
проверяет только адаптер; он не является доказательством работы произвольного
OpenSCAD/BOSL2. Для него нужен настоящий установленный executable и pinned
библиотека. Полный регресс и Windows EXE/UI smoke выполняются в CI.
