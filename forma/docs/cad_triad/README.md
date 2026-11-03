# Три CAD на одной детали: исходники теста

Здесь лежит то, что запускает `.github/workflows/cad-triad-probe.yml`:
одна и та же деталь (плита 80×60×6, два отверстия ø5) на четырёх языках.

| Файл | Что это |
|---|---|
| `plate.scad` | OpenSCAD: CSG + цикл `for` |
| `plate.f3d` | ФОРМА 3D: наш DSL |
| `plate_part.py` | FreeCAD через `Part` (CSG в Python) + экспорт STEP |
| `plate_sketch.py` | FreeCAD через `Sketcher` (ограничения) + параметрическая правка |
| `collect.py` | сводит результаты в таблицу: объём, треугольники, время, строки |
| `result/` | то, что вернул CI: `table.txt`, `summary.md`, снимки, STL, STEP |

SolveSpace готового файла не имеет: формат `.slvs` проектируется в GUI,
поэтому в CI берётся эталонный файл из его собственного набора тестов и
проверяются возможности CLI (`export-mesh`, `thumbnail`, `regenerate`).

Подробный разбор, таблицы и выводы — в `../cad_triad.md`.
