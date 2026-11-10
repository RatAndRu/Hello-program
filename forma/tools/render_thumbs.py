"""Плитки инструментов: изометрические миниатюры в ``web/thumbs``.

Плитка — это одна картинка и название. Ни пола, ни сетки, ни тени: на 96–128 px
любая лишняя линия превращается в шум. Поэтому рендер идёт с
``view="iso"``, ``shadow=False``, ``grid=False``.

Набор плиток не переписывается руками: он берётся из реестра команд — все
операции категории «Примитивы» (кроме действий вроде ``drive``, которые ничего
не создают). Заводские параметры для миниатюры лежат в ``FACTORY``; там, где их
нет, операция строится со своими умолчаниями — значит плитка показывает ровно
то, что получится у пользователя при клике.

Рядом с картинками пишется ``tiles.json``: слово операции, строка параметров,
подпись и порядок. Это не второе хранилище сцены — это манифест картинок:
интерфейс по нему рисует плитки и по клику вставляет ту самую строку.

Скрипт идемпотентен: существующий файл не перерисовывается, если не передан
``--force``. Так повторный запуск в CI не тратит минуты на ту же картинку.

    python tools/render_thumbs.py            # только недостающие
    python tools/render_thumbs.py --force    # перерисовать всё
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.render import render_single   # noqa: E402
from forma.run import build              # noqa: E402

OUT = ROOT / "web" / "thumbs"
MANIFEST = OUT / "tiles.json"

# Заводские параметры для миниатюры. Это не «пресет формы»: значения взяты
# такими, чтобы силуэт операции читался в маленькой картинке.
FACTORY: dict[str, str] = {
    "box": "size=[120, 80, 60]",
    "sheet": "width=120 length=160 thickness=4",
    "cylinder": "radius=40 height=90",
    "cone": "radius=40 height=70",
    "sphere": "radius=45",
    "icosphere": "radius=45",
    "ellipsoid": "x=60 y=40 z=30",
    "prism": "sides=6 radius=40 height=60",
    "pyramid": "sides=4 radius=45 height=70",
    "octa": "radius=45",
    "torus": "major=40 minor=10",
    "tube": "diameter=40 wall=4 length=120",
    "washer": "outer=40 inner=16 thickness=6",
    "gear": "teeth=20 module=2 thickness=10",
    "shaft": "length=100 diameter=20 chamfer=1",
    "capsule": "radius=20 height=80",
    "disc": "diameter=100 thickness=10",
    "bead": "diameter=40 height=40 hole=8",
    "ring": "diameter=100 thickness=8 width=12",
    "paraboloid": "diameter=80 height=60",
    "stairs": "steps=5 rise=18 run=26 width=100",
    "spring": "diameter=40 wire=3 turns=8",
    # Операции без умолчаний: без этих значений плитка не построится.
    "hull": "points=[[0,0,0],[90,0,0],[0,90,0],[0,0,70]]",
    "membrane": "root=[40,-5] outline=[[0,-20],[20,-5],[45,0],[100,50],[140,0],[100,-50],[0,-30]]",
    "text": '"Ф3" size=40 depth=8',
    "pipe": "diameter=32 wall=3 length=160",
    "lathe": "points=[[0,0],[40,0],[42,4],[42,60],[30,70],[0,72]] fillet=2",
    "extrude": "profile=[[-40,-25],[40,-25],[40,25],[-40,25]] height=40 fillet=4",
    "sweep": "path=[[0,0,0],[40,0,30],[0,0,60]] radius=12",
    "loft": "sections=[[[-30,10],[30,10],[32,30],[0,38],[-32,30]],[[-40,8],[40,8],[42,28],[0,40],[-42,28]]] positions=[0,400] axis=x",
    "blob": "spheres=[[0,0,80,35],[0,0,130,28]] capsules=[[0,0,60,0,0,20,14]] blend=12",
    "blot": "radius=45 thickness=4 dome=1.4 lobes=9 irregularity=.85 droplets=7 seed=12",
    "волосинки": "from=[-40,0,20] to=[40,0,20] count=40 length=20 thick=1.5",
}

# Подписи, которые уже стоят на плитках: короткие и по делу. Остальные берутся
# из первой фразы описания операции.
TITLES: dict[str, str] = {
    "box": "Куб",
    "sheet": "Лист",
    "cylinder": "Цилиндр",
    "cone": "Конус",
    "sphere": "Сфера",
    "icosphere": "Икосфера",
    "ellipsoid": "Эллипсоид",
    "prism": "Призма",
    "pyramid": "Пирамида",
    "octa": "Октаэдр",
    "torus": "Тор",
    "tube": "Труба",
    "washer": "Шайба",
    "gear": "Шестерня",
    "shaft": "Вал",
    "capsule": "Капсула",
    "disc": "Диск",
    "bead": "Бусина",
    "ring": "Кольцо",
    "paraboloid": "Параболоид",
    "stairs": "Лестница",
    "spring": "Пружина",
    "hull": "Оболочка",
    "membrane": "Мембрана",
    "text": "Текст",
    "волосинки": "Волоски",
    "pipe": "Труба",
    "lathe": "Точение",
    "extrude": "Выдавливание",
    "sweep": "Протяжка",
    "loft": "Лофт",
    "blob": "Метабол",
    "barrel": "Бочка",
    "blade": "Клинок",
    "box_body": "Корпус",
    "crescent": "Полумесяц",
    "curtain": "Штора",
    "door": "Дверь",
    "eyeball": "Глазное яблоко",
    "face_box": "Куб с рельефом",
    "horn": "Рог",
    "knot": "Узел",
    "ladder": "Приставная лестница",
    "rock": "Камень",
    "saddle": "Седло",
    "socket": "Розетка",
    "stairs": "Ступени",
    "strip": "Полоса",
    "turbine_blade": "Лопасть",
    "yin_yang": "Инь-ян",
    "seven_seg": "Индикатор",
    "tri_prism": "Треугольная призма",
    "arc_prism": "Дугообразная призма",
    "profile2020": "Профиль 2020",
    "banana": "Банан",
    "bicycle_chain": "Велоцепь",
    "door_handle": "Ручка двери",
    "cavity_frame": "Рамка-полость",
}

# Слово → категория реестра, из которой берутся плитки. Примитивы берутся
# целиком, конструкторы перечислены поимённо: contour2d — это 2D, а фигуры
# человека и скелет слишком тяжёлые для миниатюры.
CATEGORIES = {"Примитивы": "*",
              "Тела вращения и развёртки": {"lathe", "extrude", "sweep", "loft", "pipe"},
              "Математические поверхности": {"blob"}}

# Действия: они меняют готовые объекты и ничего не создают — плитки им не нужны.
SKIP = {"drive"}

TITLE_LIMIT = 22


STOPWORDS = {"с", "со", "из", "для", "на", "в", "во", "к", "от", "до", "по",
             "под", "над", "без", "при", "и", "или", "как", "одной", "один",
             "одна", "одним", "двух", "трёх", "пяти", "шести", "семи"}


def short_title(summary: str) -> str:
    """Первая фраза описания, обрезанная по предлогу: «Арка», «Болт»."""
    text = (summary or "").strip()
    cut = len(text)
    for mark in (":", " — ", " – ", ". ", " ("):
        pos = text.find(mark)
        if 0 < pos < cut:
            cut = pos
    words = text[:cut].strip().rstrip(" .,—-").split()
    # Хвост из предлога («призма с…») в подписи читается как обрыв: режем по
    # первому предлогу, но первое слово оставляем всегда.
    for index in range(1, len(words)):
        if words[index].lower().strip(",") in STOPWORDS:
            words = words[:index]
            break
    while words and len(" ".join(words)) > TITLE_LIMIT:
        words.pop()
    while len(words) > 1 and words[-1].lower().strip(",") in STOPWORDS:
        words.pop()
    # Обрывок из одного прилагательного («Выпуклая») ничего не называет:
    # тогда берём ещё одно слово, даже если там предлог.
    endings = ("ый", "ий", "ой", "ая", "яя", "ое", "ее", "ые", "ие")
    if len(words) == 1 and words[0].lower().endswith(endings):
        rest = text[:cut].strip().rstrip(" .,—-").split()[1:4]
        words = words + [w for w in rest if w.lower().strip(",") not in STOPWORDS][:1]
    text = " ".join(words).rstrip(" .,—-") or "деталь"
    if text[0].isupper() and len(words) > 1 and not text[1:2].isupper():
        text = " ".join([words[0]] + [w.lower() if w[:1].isupper() else w for w in words[1:]])
    return text


def primitives() -> dict[str, str]:
    """Все примитивы реестра: слово → строка параметров для миниатюры."""
    import forma.run  # noqa: F401  — импорт регистрирует операции
    from forma.ops import OPS

    items = {}
    for spec in sorted(OPS.values(), key=lambda s: s.name):
        wanted = CATEGORIES.get(spec.category)
        if wanted is None or spec.name in SKIP:
            continue
        if wanted != "*" and spec.name not in wanted:
            continue
        items[spec.name] = FACTORY.get(spec.name, "")
    return items


def sample_script(op: str, params: str) -> str:
    tail = f" {params}" if params else ""
    return f"плитка = {op}{tail}\n"


def render_one(op: str, params: str, force: bool = False) -> tuple[str, bool]:
    target = OUT / f"{op}.png"
    if target.exists() and not force:
        return op, False
    result = build(sample_script(op, params), analyze_model=False)
    if not result.ok:
        raise SystemExit(f"{op}: не собралось — {(result.error or {}).get('message')}")
    solids = result.scene.visible_solids()
    if not solids:
        raise SystemExit(f"{op}: нечего рисовать — операция не дала тел")
    render_single(solids, str(OUT), f"{op}.png", size=128, ss=2, view="iso",
                  shadow=False, grid=False)
    return op, True


def manifest(rows: list[dict]) -> None:
    """Манифест плиток: одна строка на плитку, без путей и картинок."""
    MANIFEST.write_text(json.dumps({"tiles": rows}, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Миниатюры инструментов (плитки)")
    parser.add_argument("--force", action="store_true", help="перерисовать всё")
    parser.add_argument("--only", default="", help="через запятую: какие операции")
    args = parser.parse_args()
    from forma.ops import OPS

    wanted = [name.strip() for name in args.only.split(",") if name.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    made, skipped, failed = 0, 0, 0
    rows: list[dict] = []
    for op, params in primitives().items():
        if wanted and op not in wanted:
            continue
        try:
            _op, created = render_one(op, params, force=args.force)
        except SystemExit as exc:
            print(f"  ! {exc}", file=sys.stderr)
            failed += 1
            continue
        if created:
            made += 1
            print(f"  + {op}.png")
        else:
            skipped += 1
        spec = OPS[op]
        file = OUT / f"{op}.png"
        if not file.exists():
            failed += 1
            continue
        title = TITLES.get(op) or short_title(spec.summary)
        rows.append({"op": op, "title": title, "params": params,
                     "bytes": file.stat().st_size})
    if not wanted:
        rows.sort(key=lambda row: row["op"])
        manifest(rows)
        print(f"манифест: {MANIFEST.relative_to(ROOT)} — {len(rows)} плиток")
    print(f"плитки: сделано {made}, уже было {skipped}, ошибок {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
