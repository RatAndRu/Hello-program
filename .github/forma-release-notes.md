**Форма 3D 0.68** — параметрический 3D-редактор, которым управляют текстом.

## Файлы

- `Forma3D-0.68-windows.zip` — распакуйте и запустите `Forma3D.exe`.
- `Forma3D.exe` — то же CI-собранное приложение одним файлом.
- `Forma3D-0.68-exe.zip` — отдельный архив только с новым `Forma3D.exe`, созданный и проверенный в Windows CI.
- Готовые модели поставляются парами **GLB + Forma**: GLB для Blender и других 3D-программ, Forma — редактируемый параметрический исходник.

## Что нового в 0.68

- Собственные библиотеки Forma: `include`, числовые `function` с defaults и именованными аргументами, параметрические `module` с локальными scope, диагностика циклических включений и рекурсии.
- Вкладка **Параметры**: схема, границы, presets и reset работают через существующий rebuild/morph. Явные overrides имеют приоритет; исходный default не затирается.
- **SCAD export**: нативный `.scad` с `polyhedron(points=…, faces=…)` из построенной сетки. Это не параметрический round-trip.
- **OpenSCAD/BOSL2 runner**: настоящий subprocess без GUI, `-D`, `OPENSCADPATH`, timeout, проверка mesh и structured stderr/stdout. Внешнюю программу пользователю открывать не нужно; отсутствие executable показывается честной диагностикой.
- Плоский **provenance**: объект, операция, прямые исходные объекты, строка и команда сценария. Полного дерева FreeCAD нет; ограниченная история складок сохранена отдельно.
- **Фото-подгонка**: репер px/mm, существующие silhouette/camera fitting, residual и диагностика неоднозначности. Применение использует parametric rebuild и записывает найденный масштаб в `.forma`.
- **DXF с размерами**: нативный контур, `DIMENSION`/`TEXT`, фактические размеры и witness lines без внешнего CAD.
- **Глобальная точность**: `precision legacy/fine/ultra` и `factor`; старое поведение остаётся default, явные `detail`/`segments` имеют приоритет.
- Исправления 0.68: сохранение preset сразу делает rebuild с теми же overrides, объявления presets не применяются неявно, рекурсивные функции сохраняют причину ошибки, а `precision tolerance` реально влияет на неявную tessellation. Добавлена проверка границ и NaN/Inf в preset API.
- Подробная документация: `forma/docs/stage3_features.md`.

## Проверки выпуска

- Targeted acceptance нового набора и регрессий: **18/18** на Linux; Windows повторяет его в CI (POSIX-only executable wrapper помечен skip на Windows, subprocess-контракт отдельно покрыт mock).
- Наследованные targeted `test_rules_upgrade.py`: **32/32**.
- Проверены реальные Manifold/GLB, HTTP API, файлы SCAD/DXF, добавление mesh в сцену, baseline/residual фото-подгонки и demo-границы.
- Windows CI повторяет полный Python/JS-регресс, golden-compare, deterministic fuzz, самопроверку и UI/API smoke перед сборкой EXE и отдельного EXE-only ZIP.
- Технический CI не заменяет визуальную приёмку моделей. Произвольный SCAD/BOSL2 требует настоящий OpenSCAD и pinned-библиотеки с проверенными лицензиями; fake-CLI в тестах не является такой проверкой.
