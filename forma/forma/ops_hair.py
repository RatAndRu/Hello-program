"""Волосы по-настоящему: локоны, волосинки и чёлка.

В 0.32 у `hair` были пряди-клинья на сфере-шапочке — причёска угадывалась,
но отдельной волосинки не существовало: нельзя было положить чёлку на лоб,
завить прядь у щеки или рассыпать короткие волоски по макушке.

Здесь три инструмента, каждый — про свою вещь:

* `волосинки` — **пучок** тонких волосков из линии или из дуги. Волоски
  растут из общей основы, поэтому не «висят в воздухе», и у них есть
  изгиб, завиток на конце и случайный разброс (seed — повторяемость);
* `локон` — **один** завиток: спираль с уменьшающимся радиусом, сужением
  к кончику и плоским сечением. Так рисуют локоны в аниме — пружинка,
  которая кончается остриём;
* `чёлка` — ряд волосинок по дуге через лоб, с рваным краем и разной
  длиной: то, что закрывает лоб и «обрамляет» лицо.

Все три возвращают **одно тело**: волоски входят в основу (полосу кожи
скальпа), а основа — часть того же объёма. Поэтому волосы можно
присоединять к голове через `union`, и модель остаётся слитной.

    чёлка = волосинки from=[-52,-40,196] to=[52,-40,196] count=46 length=42
                     thick=1.6 bend=0.5 curl=0.35 base=да
    локон = локон at=[62,-18,150] length=120 radius=16 turns=1.4 thick=13
"""

from __future__ import annotations

import math

import manifold3d as mf
import numpy as np

from .errors import GeometryError
from .geometry import ellipse_profile, sweep_solid
from .ops import anchor, make_solid, op


def _vec(a, key: str, default=None, count: int = 3) -> np.ndarray:
    raw = a.vec(key, count, default=default)
    if raw is None:
        raise GeometryError(f"Нужен параметр {key}=[x, y, z].")
    return np.asarray(raw, dtype=np.float64).reshape(count)


def _place_exact(a, m: mf.Manifold) -> mf.Manifold:
    """Волосы ставятся по координатам как есть.

    В отличие от `box` и остальных примитивов, `at` здесь — не «низ на z»,
    а обычный сдвиг: линия роста и корни локонов задаются абсолютными
    координатами (from/to/at), иначе примерять их к голове невозможно.
    `center=да` центрирует габарит на at — на случай, когда удобнее так.
    """
    at = np.asarray(a.vec("at", 3, default=(0.0, 0.0, 0.0)), dtype=np.float64)
    if a.boolean("center", False):
        return anchor(m, at, True)
    return m.translate((float(at[0]), float(at[1]), float(at[2])))


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _strand_path(start: np.ndarray, direction: np.ndarray, length: float,
                 bend: float, curl: float, side: np.ndarray | None,
                 steps: int = 9) -> np.ndarray:
    """Путь одной волосинки: прямой участок, изгиб, завиток на конце.

    bend — общий изгиб (0 — прямо, 1 — почти крючком),
    curl — завиток у кончика (витки спирали, 0 — нет).
    """
    d = direction / max(float(np.linalg.norm(direction)), 1e-9)
    s = side if side is not None else np.array([0.0, 0.0, 1.0])
    s = s - d * float(np.dot(s, d))
    if float(np.linalg.norm(s)) < 1e-6:
        s = np.cross(d, np.array([1.0, 0.0, 0.0]))
    s /= max(float(np.linalg.norm(s)), 1e-9)
    pts = []
    for i in range(steps):
        t = i / (steps - 1)
        # изгиб: поперечное смещение растёт как t² (волос гнётся к концу)
        sag = length * bend * (t * t) * 0.55
        # завиток: спираль в конце, амплитуда включается после середины
        twist = length * curl * max(0.0, t - 0.45) * 1.6
        angle = twist * 2.0 * math.pi / max(length * 0.12, 1e-6)
        pts.append(start + d * (length * t)
                   + s * (sag + math.sin(angle) * twist * 0.35)
                   + np.cross(d, s) * math.cos(angle) * twist * 0.35)
    return np.asarray(pts)


def _single_strand(start, direction, length, thick, bend, curl, side,
                   sharp: float = 1.0) -> mf.Manifold:
    """Один волос: плоское веретено с остриём на конце."""
    path = _strand_path(start, direction, length, bend, curl, side)
    w = max(thick, 0.12)
    prof = ellipse_profile(w, w * (0.45 + 0.25 * (1.0 - sharp)), 6)
    # у корня полная толщина, к кончику — остриё
    curve = [1.0, 0.96, 0.88, 0.74, 0.56, 0.36, 0.2, 0.08, 0.02]
    return sweep_solid(path, prof, what="волоса", scale_curve=curve, round_caps=1.0)


def _base_strip(path, width: float, thick: float) -> mf.Manifold:
    """Основа, в которую входят волоски: узкая полоса по линии роста.

    Путь может быть ломаной (дуга чёлки, затылок), а не только отрезком —
    иначе пряди по краям дуги повисают в воздухе и модель распадается.
    """
    pts = np.asarray(path, dtype=np.float64)
    if pts.ndim != 2 or len(pts) < 2:
        return mf.Manifold()
    keep = [pts[0]]
    for p in pts[1:]:
        if float(np.linalg.norm(p - keep[-1])) > 1e-6:
            keep.append(p)
    if len(keep) < 2:
        return mf.Manifold()
    prof = ellipse_profile(max(width, thick * 1.2), thick, 12)
    curve = [1.0] + [0.92] * (len(keep) - 2) + [1.0] if len(keep) > 2 else [0.85, 1.0]
    return sweep_solid(np.asarray(keep), prof, what="основы волос",
                       scale_curve=curve, round_caps=1.0)


def _clump(start, direction, length, width, thin, bend, curl, side,
           wobble: float = 0.0) -> mf.Manifold:
    """Одна широкая прядь: у корня во всю ширину, к кончику — остриё.

    Так выглядят волосы в аниме: не проволока, а плоский клин с острым
    концом. `wobble` добавляет волну по длине — край не выглядит линейкой.
    """
    path = _strand_path(start, direction, length, bend, curl, side)
    if wobble > 1e-6:
        path = path.copy()
        t = np.linspace(0.0, 1.0, len(path))
        off = np.sin(t * math.pi * 2.4) * wobble * length * 0.06
        s = side if side is not None else np.array([0.0, 0.0, 1.0])
        s = s / max(float(np.linalg.norm(s)), 1e-9)
        path = path + s[None, :] * off[:, None]
    w = max(width, 0.12)
    prof = ellipse_profile(w, max(thin, 0.08), 12)
    n = len(path)
    curve = list(np.linspace(1.0, 0.25, n) ** 0.7)
    curve[0] = 1.02
    curve[-1] = 0.03
    return sweep_solid(path, prof, what="пряди", scale_curve=curve, round_caps=1.0)


@op("волосинки", aliases=("strands", "волоски", "пряди", "волосы_пучок", "hair_strands",
                        "пух", "ворс"),
    category="Примитивы",
    summary="Пучок тонких волосков: растут из общей основы (полосы по линии "
            "роста), поэтому это одно тело, а не облако отдельных палочек. "
            "Линию роста задают from= и to=, волоски смотрят по dir= (по "
            "умолчанию — от головы наружу). У каждого свой изгиб, завиток на "
            "кончике и случайная длина; seed делает результат повторяемым. "
            "Годится для чёлки, ресниц, шерсти, травы и меха.",
    example="чёлка = волосинки from=[-52,-36,196] to=[52,-36,196] count=46 "
            "length=44 thick=1.6 bend=0.6 curl=0.4 dir=[0,-0.55,-1] base=да\n"
            "мех = волосинки from=[-40,0,20] to=[40,0,20] count=120 length=18 "
            "thick=1.1 bend=0.3 curl=0 thick=1.1",
    params={"from": "начало линии роста [x,y,z]",
            "to": "конец линии роста [x,y,z]",
            "count": "сколько волосков (40)",
            "length": "длина волоса, мм (60)",
            "thick": "толщина волоса, мм (1.4)",
            "dir": "направление роста [x,y,z] (от модели наружу)",
            "bend": "изгиб к кончику 0…1 (0.35)",
            "curl": "завиток на конце, витков 0…2 (0)",
            "spread": "разброс длин и направлений 0…1 (0.25)",
            "base": "добавить основу, в которую входят волоски (да)",
            "base_width": "ширина основы, мм (thick × 6)",
            "seed": "зерно случайности — одинаковое даёт тот же пучок (1)",
            "at": "сдвиг всего пучка [x,y,z] (координаты абсолютные)",
            "center": "центрировать по высоте"})
def strands(a, name):
    p0 = _vec(a, "from", (0.0, 0.0, 0.0))
    raw_to = a.vec("to", 3, default=None)
    if raw_to is None:
        raise GeometryError("Укажите линию роста: from=[x,y,z] to=[x,y,z].",
                            hint="Пример: волосинки from=[-50,0,100] to=[50,0,100] count=40")
    p1 = np.asarray(raw_to, dtype=np.float64).reshape(3)
    count = int(a.num("count", 40, minv=1, maxv=4000))
    length = float(a.num("length", 60.0, minv=0.5))
    thick = float(a.num("thick", 1.4, minv=0.08, maxv=40.0))
    spread = float(a.num("spread", 0.25, minv=0.0, maxv=1.0))
    bend = float(a.num("bend", 0.35, minv=0.0, maxv=3.0))
    curl = float(a.num("curl", 0.0, minv=0.0, maxv=4.0))
    seed = int(a.num("seed", 1, minv=0, maxv=1_000_000))
    rng = np.random.default_rng(seed)
    dir_raw = a.vec("dir", 3, default=None)
    base_dir = (np.asarray(dir_raw, dtype=np.float64).reshape(3) if dir_raw is not None
                else None)

    pieces: list[mf.Manifold] = []
    for i in range(count):
        t = (i + 0.5) / count
        # по линии с небольшим дрожанием, чтобы ряд не выглядел гребёнкой
        start = p0 + (p1 - p0) * t
        jitter = spread * thick * 2.0
        start = start + rng.normal(0.0, max(jitter, 1e-6), 3)
        if base_dir is not None:
            direction = base_dir / max(float(np.linalg.norm(base_dir)), 1e-9)
        else:
            direction = np.array([0.0, 0.0, 1.0])
        direction = direction + rng.normal(0.0, 0.22 * spread, 3)
        direction /= max(float(np.linalg.norm(direction)), 1e-9)
        ln = length * (1.0 - spread * 0.55 * rng.random())
        side = None
        if base_dir is not None:
            side = np.cross(direction, (p1 - p0) / max(float(np.linalg.norm(p1 - p0)), 1e-9))
        pieces.append(_single_strand(start, direction, ln, thick,
                                     bend * (0.7 + 0.6 * rng.random()),
                                     curl * (0.7 + 0.6 * rng.random()), side,
                                     sharp=1.0))

    use_base = a.boolean("base", True)
    if use_base:
        bw = float(a.num("base_width", thick * 6.0, minv=0.2))
        # основа идёт по той же линии с шагом, что и волоски
        line = np.stack([p0 + (p1 - p0) * t for t in np.linspace(0.0, 1.0,
                                                                  max(2, min(count, 24)))])
        pieces.insert(0, _base_strip(line, bw, max(thick * 1.6, 0.6)))

    solid = pieces[0] if len(pieces) == 1 else mf.Manifold.batch_boolean(pieces, mf.OpType.Add)
    solid = _place_exact(a, solid)
    parts = len([p for p in solid.decompose() if p.volume() > 0])
    a.scene.log("info", f"волосинки: {count} шт. по {length:g} мм, частей {parts}, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    if use_base and parts > 2:
        a.scene.log("warn", f"часть волосков не достаёт до основы ({parts} кусков) — "
                            f"увеличьте thick или уменьшите spread", a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="strands")


@op("локон", aliases=("curl", "lock", "кудри", "кудрявый", "ringlet", "пружинка"),
    category="Примитивы",
    summary="Один локон-пружинка: спираль с уменьшающимся радиусом, плоским "
            "сечением и остриём на конце. Так рисуют локоны в аниме и манге. "
            "turns — сколько витков, radius — радиус завитка, taper — насколько "
            "сужается к кончику. dir задаёт, куда локон падает, side — куда "
            "закручивается (влево/вправо). Локон — одно тело.",
    example="локон = локон at=[62,-18,150] length=130 radius=18 turns=1.3 "
            "thick=14 taper=0.15 dir=[0,0,-1]\n"
            "кудри = локон at=[-60,-20,160] length=110 radius=14 turns=1.8 thick=12",
    params={"length": "длина локона по спирали, мм (120)",
            "radius": "радиус завитка, мм (16)",
            "turns": "витков спирали (1.2)",
            "thick": "ширина локона у корня, мм (12)",
            "thin": "толщина сечения, мм (thick × 0.45)",
            "taper": "сужение к кончику 0…0.9 (0.2)",
            "dir": "куда падает локон [x,y,z] (вниз)",
            "side": "направление закрутки [x,y,z] (вбок)",
            "at": "корень локона [x,y,z]", "center": "центрировать по высоте"})
def curl(a, name):
    length = float(a.num("length", 120.0, minv=2.0))
    radius = float(a.num("radius", 16.0, minv=0.5))
    turns = float(a.num("turns", 1.2, minv=0.2, maxv=8.0))
    thick = float(a.num("thick", 12.0, minv=0.2))
    thin = float(a.num("thin", thick * 0.45, minv=0.08))
    taper = float(a.num("taper", 0.2, minv=0.0, maxv=0.9))
    dir_raw = a.vec("dir", 3, default=(0.0, 0.0, -1.0))
    down = np.asarray(dir_raw, dtype=np.float64).reshape(3)
    down /= max(float(np.linalg.norm(down)), 1e-9)
    side_raw = a.vec("side", 3, default=None)
    side = (np.asarray(side_raw, dtype=np.float64).reshape(3) if side_raw is not None
            else np.array([0.0, -1.0, 0.0]))
    side = side - down * float(np.dot(side, down))
    if float(np.linalg.norm(side)) < 1e-6:
        side = np.cross(down, np.array([1.0, 0.0, 0.0]))
    side /= max(float(np.linalg.norm(side)), 1e-9)
    other = np.cross(down, side)

    steps = int(np.clip(28 + turns * 18, 24, 220))
    ts = np.linspace(0.0, 1.0, steps)
    # спираль: локон закручивается, а его витки сужаются к концу
    angle = 2.0 * math.pi * turns * ts
    r = radius * (1.0 - 0.65 * ts)
    path = (down[None, :] * (length * ts)[:, None]
            + side[None, :] * (r * np.cos(angle))[:, None]
            + other[None, :] * (r * np.sin(angle))[:, None])
    # корень чуть выше и внутрь: локон «выходит» из причёски
    prof = ellipse_profile(thick, thin, 10)
    curve = list(np.linspace(1.0, max(1.0 - taper, 0.05), steps) ** 1.3)
    curve[-1] = 0.02
    solid = sweep_solid(path, prof, what="локона", scale_curve=curve, round_caps=1.0)
    solid = _place_exact(a, solid)
    a.scene.log("info", f"локон: {turns:g} витка, радиус {radius:g} мм, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="curl")


@op("чёлка", aliases=("fringe", "bangs", "челка", "прядь_на_лоб", "хвостик_волос"),
    category="Примитивы",
    summary="Чёлка: ряд широких прядей дугой через лоб, у корня пряди "
            "смыкаются, к кончикам сужаются в острия и висят на разной длине — "
            "край рваный, как рисуют в аниме. arc выгибает дугу вперёд (по "
            "форме лба), dir задаёт направление роста. Пряди входят в основу по "
            "всей дуге, поэтому это одно тело, а не гребень из палочек: его "
            "можно сразу соединить с головой через union.",
    example="лоб = чёлка width=150 height=64 arc=32 teeth=9 thick=9 at=[0,-52,168] "
            "dir=[0,-0.35,-1]\n"
            "короткая = чёлка width=120 height=40 arc=18 teeth=7 thick=7 bend=0.2",
    params={"width": "ширина чёлки, мм (120)",
            "height": "длина прядей, мм (52)",
            "arc": "насколько дуга выгнута вперёд, мм (26)",
            "teeth": "число прядей (9)",
            "thick": "ширина пряди у корня, мм (8)",
            "thin": "толщина пряди, мм (thick × 0.32)",
            "bend": "изгиб к кончику 0…1 (0.45)",
            "curl": "завиток на конце, витков (0.06)",
            "jag": "рваность края 0…1 (0.45)",
            "lean": "наклон вбок, −1…1 (0): край зачёсан на сторону",
            "base": "основа по линии роста (да)",
            "dir": "направление роста [x,y,z] (вниз-вперёд)",
            "at": "сдвиг чёлки [x,y,z] (координаты абсолютные)",
            "center": "центрировать по высоте"})
def fringe(a, name):
    width = float(a.num("width", 120.0, minv=2.0))
    height = float(a.num("height", 52.0, minv=1.0))
    arc = float(a.num("arc", 26.0, minv=-400.0, maxv=400.0))
    teeth = int(a.num("teeth", 9, minv=2, maxv=200))
    thick = float(a.num("thick", 8.0, minv=0.12))
    thin = float(a.num("thin", thick * 0.32, minv=0.08))
    bend = float(a.num("bend", 0.45, minv=0.0, maxv=3.0))
    curl = float(a.num("curl", 0.06, minv=0.0, maxv=4.0))
    jag = float(a.num("jag", 0.45, minv=0.0, maxv=1.0))
    lean = float(a.num("lean", 0.0, minv=-1.0, maxv=1.0))
    dir_raw = a.vec("dir", 3, default=(0.0, -0.35, -1.0))
    down = np.asarray(dir_raw, dtype=np.float64).reshape(3)
    down /= max(float(np.linalg.norm(down)), 1e-9)
    rng = np.random.default_rng(11)

    # линия роста — дуга: в середине лоб уходит вперёд (−Y), к вискам назад
    line = []
    for i in range(teeth * 3 + 1):
        t = i / (teeth * 3)
        x = (t - 0.5) * width
        y = -arc * math.cos((t - 0.5) * math.pi * 0.95) + arc * 0.62
        line.append(np.array([x, y, 0.0]))
    line = np.asarray(line)

    pieces: list[mf.Manifold] = []
    span = width / teeth
    for i in range(teeth):
        t = (i + 0.5) / teeth
        start = line[int(round(t * (len(line) - 1)))]
        # пряди чуть заходят друг за друга у корней: чёлка без щелей
        side = np.array([1.0, lean * 0.35, 0.0])
        direction = down + np.array([(rng.random() - 0.5) * 0.18 * jag + lean * 0.15,
                                     (rng.random() - 0.5) * 0.10 * jag, 0.0])
        direction /= max(float(np.linalg.norm(direction)), 1e-9)
        edge = abs(t - 0.5) * 2.0
        # у висков короче — чёлка обрамляет лицо
        ln = height * (1.0 - 0.38 * edge ** 1.8) * (1.0 - jag * 0.35 * rng.random())
        if lean > 0.05:
            ln *= 1.0 + lean * 0.35 * (t - 0.5) * 2.0
        pieces.append(_clump(start, direction, ln, span * 1.85, thin,
                             bend * (0.7 + 0.5 * rng.random()),
                             curl * rng.random(), side,
                             wobble=jag * (0.6 + 0.8 * rng.random())))
    if a.boolean("base", True):
        pieces.insert(0, _base_strip(line[::2], max(thin * 4.0, 1.2), max(thin * 2.2, 0.8)))
    solid = pieces[0] if len(pieces) == 1 else mf.Manifold.batch_boolean(pieces, mf.OpType.Add)
    solid = _place_exact(a, solid)
    parts = len([p for p in solid.decompose() if p.volume() > 0])
    a.scene.log("info", f"чёлка: {teeth} прядей длиной {height:g} мм, частей {parts}, "
                        f"{solid.num_tri():,} трис".replace(",", " "), a.cmd.line)
    return make_solid(a.scene, name, solid, a, kind="fringe")
