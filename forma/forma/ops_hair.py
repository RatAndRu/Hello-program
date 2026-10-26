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


def _strand_from_path(path: np.ndarray, thick: float, sharp: float = 1.0,
                      thin_ratio: float | None = None, what: str = "волоса") -> mf.Manifold:
    """Замкнутая волосинка/лист по уже построенной центральной линии."""
    w = max(float(thick), 0.08)
    ratio = (0.45 + 0.25 * (1.0 - sharp)) if thin_ratio is None else float(thin_ratio)
    prof = ellipse_profile(w, max(0.035, w * ratio), 8)
    n = len(path)
    curve = list(np.linspace(1.0, 0.025, n) ** 0.72)
    curve[0] = 1.0
    curve[-1] = 0.025
    return sweep_solid(np.asarray(path, dtype=np.float64), prof, what=what,
                       scale_curve=curve, round_caps=1.0)


def _single_strand(start, direction, length, thick, bend, curl, side,
                   sharp: float = 1.0) -> mf.Manifold:
    """Один волос: плоское веретено с остриём на конце."""
    path = _strand_path(start, direction, length, bend, curl, side)
    return _strand_from_path(path, thick, sharp)


def _guided_strand_path(start: np.ndarray, direction: np.ndarray, flow: np.ndarray,
                        length: float, bend: float, side: np.ndarray,
                        align: float, steps: int, base=None, centre=None,
                        thick: float = 1.0, drape: bool = False) -> np.ndarray:
    """Путь с общим направлением кончиков и (при drape) огибанием носителя.

    Кубический участок даёт корню нормальное направление, а кончику — общий
    поток. До свободного свисания точки проецируются обратно на реальную
    поверхность лучами; поэтому длинный волос не остаётся прямым отрезком.
    """
    d0 = direction / max(float(np.linalg.norm(direction)), 1e-9)
    f = flow / max(float(np.linalg.norm(flow)), 1e-9)
    s = side - d0 * float(np.dot(side, d0))
    s /= max(float(np.linalg.norm(s)), 1e-9)
    align = float(np.clip(align, 0.0, 1.0))
    end = start + d0 * (length * (1.0 - align)) + f * (length * align)
    c1 = start + d0 * (length * 0.32)
    c2 = end - f * (length * 0.32 * align) - d0 * (length * 0.32 * (1.0 - align))
    ts = np.linspace(0.0, 1.0, max(9, int(steps)))
    path = []
    reach = length * 2.0 + 10.0
    for t in ts:
        q = 1.0 - t
        point = (q ** 3 * start + 3.0 * q * q * t * c1
                 + 3.0 * q * t * t * c2 + t ** 3 * end)
        point = point + s * (length * bend * 0.10 * math.sin(math.pi * t) * t)
        if drape and base is not None and centre is not None and 0.08 < t < 0.78:
            toward = np.asarray(centre) - point
            norm = float(np.linalg.norm(toward))
            if norm > 1e-8:
                toward /= norm
                hits = base.ray_cast([float(v) for v in (point - toward * reach)],
                                     [float(v) for v in (point + toward * reach)])
                if hits:
                    hit = min(hits, key=lambda h: float(np.linalg.norm(
                        np.asarray(h.position, dtype=np.float64) - point)))
                    hp = np.asarray(hit.position, dtype=np.float64)
                    hn = np.asarray(hit.normal, dtype=np.float64)
                    hn /= max(float(np.linalg.norm(hn)), 1e-9)
                    if float(np.dot(hn, hp - np.asarray(centre))) < 0:
                        hn = -hn
                    projected = hp + hn * (thick * 0.52)
                    weight = math.sin(math.pi * (t - 0.08) / 0.70)
                    weight = max(0.0, min(1.0, weight))
                    point = point * (1.0 - weight) + projected * weight
        path.append(point)
    return np.asarray(path, dtype=np.float64)


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


@op("hair", aliases=("волосы", "причёска", "прическа", "мех", "шерсть",
                     "hair_style", "fur"),
    category="Форма и деформации",
    summary="Наращивает иголки, волоски, локоны или мех на поверхности "
            "выбранного существующего объекта и сваривает корни с ним в одно "
            "тело. Не создаёт голову, сферу или шапочку-основу. surface выбирает "
            "каноническую сторону, at+radius ограничивают пятно; style=иголки, "
            "волоски, локоны или мех. thick — толщина корня в миллиметрах.",
    example="ёж = sphere radius=35 segments=48\n"
            "hair ёж style=иголки surface=вся count=90 length=24 thick=2 seed=4\n"
            "шкура = box size=[100,70,18] round=5\n"
            "hair шкура style=мех surface=верх count=140 length=9 thick=.8",
    params={"objects": "существующий объект [a] или a (обязательно)",
            "style": "иголки, волоски, пряди, локоны, мех или водоросли — «волоски»",
            "surface": "верх, низ, право, лево, перёд, зад или вся",
            "growth": "нормаль, вниз или авто (длинные волосы в авто свисают вниз)",
            "dir": "общее направление потока [x,y,z]; например [0,0,-1]",
            "tip_align": "сонаправленность кончиков 0…1 (авто)",
            "drape": "да — огибать поверхность перед свободным свисанием",
            "density": "заполнение доступной площади 0…100% без count",
            "fill": "синоним density",
            "width": "ширина пряди/листа, мм (авто от thick)",
            "thin": "толщина сечения пряди/листа, мм (авто)",
            "at": "необязательный центр пятна [x,y,z]",
            "radius": "радиус пятна на поверхности, мм; 0 — вся выбранная сторона",
            "length": "максимальная длина, мм (24)",
            "thick": "толщина корня, мм (по стилю)",
            "count": "число корней; clumps/density — совместимые синонимы",
            "spread": "разброс направлений и длин 0…1 (0.25)",
            "bend": "изгиб волосков и меха 0…3 (0.25)",
            "turns": "витки локона 0.2…8 (1.2)",
            "curl_radius": "радиус локона, мм (0.12·length)",
            "seed": "повторяемая раскладка (7)"},
    positional=["objects"])
def hair(a, name):
    from .ops_extra import _derived, _one
    from .ops_surface import _frame, _surface_samples
    from .ops_shapes import ensure_volume

    base = _one(a, "hair")
    style = (a.text("style", "волоски") or "волоски").strip().lower()
    style = {"иголки": "иголки", "иглы": "иголки", "needles": "иголки", "spikes": "иголки",
             "волоски": "волоски", "волосы": "волоски", "hair": "волоски",
             "пряди": "пряди", "прядь": "пряди", "locks": "пряди", "strands": "пряди",
             "аниме": "волоски", "anime": "волоски", "хвост": "волоски", "tail": "волоски",
             "короткий": "волоски", "short": "волоски",
             "локоны": "локоны", "кудри": "локоны", "curls": "локоны",
             "мех": "мех", "шерсть": "мех", "fur": "мех",
             "водоросли": "водоросли", "листья": "водоросли", "seaweed": "водоросли",
             "leaves": "водоросли", "leaf": "водоросли"}.get(style)
    if style is None:
        raise GeometryError(f"Неизвестный стиль hair «{a.text('style')}».",
                            hint="style: иголки, волоски, локоны или мех.")
    surface_raw = a.text("surface", None)
    surface = (surface_raw or ("вся" if style == "мех" else "верх")).strip().lower()
    sides = {"верх": (0, 0, 1), "низ": (0, 0, -1), "право": (1, 0, 0),
             "лево": (-1, 0, 0), "перёд": (0, -1, 0), "перед": (0, -1, 0),
             "зад": (0, 1, 0)}
    if surface in ("все", "всё", "all"):
        surface = "вся"
    if surface != "вся" and surface not in sides:
        raise GeometryError("hair: surface=верх, низ, право, лево, перёд, зад или вся.")
    length = float(a.num("length", 24.0, minv=0.5, maxv=5000.0))
    default_thick = {"иголки": 1.8, "волоски": 1.2, "пряди": 3.8,
                     "локоны": 5.0, "мех": 0.9, "водоросли": 1.0}[style]
    thick = float(a.num("thick", default_thick, minv=0.08, maxv=100.0))
    strand_width = float(a.num("width", thick * (2.8 if style == "водоросли" else 1.9),
                               minv=0.08, maxv=300.0))
    strand_thin = float(a.num("thin", thick * (0.16 if style == "водоросли" else 0.45),
                              minv=0.03, maxv=100.0))
    density = a.num("density", None, minv=0.0, maxv=100.0)
    if density is None:
        density = a.num("fill", None, minv=0.0, maxv=100.0)
    density_mode = density is not None and not a.has("count") and not a.has("clumps")
    count_value = a.num("count", None, minv=1, maxv=800)
    if count_value is None:
        count_value = a.num("clumps", None, minv=1, maxv=800)
    if count_value is None:
        count_value = a.num("roots", 120 if style == "мех" else 48, minv=1, maxv=800)
    count = int(count_value)
    spread = float(a.num("spread", 0.25, minv=0.0, maxv=1.0))
    bend = float(a.num("bend", 0.45 if style == "мех" else 0.25, minv=0.0, maxv=3.0))
    turns = float(a.num("turns", 1.2, minv=0.2, maxv=8.0))
    curl_radius = float(a.num("curl_radius", length * 0.12, minv=0.1, maxv=1000.0))
    seed = int(a.num("seed", 7, minv=0, maxv=1_000_000))
    patch_at = a.vec("at", 3, default=None)
    patch_radius = float(a.num("radius", 0.0, minv=0.0, maxv=5000.0) or 0.0)
    rng = np.random.default_rng(seed)
    growth = (a.text("growth", "авто") or "авто").strip().lower()
    growth = {"normal": "нормаль", "нормаль": "нормаль", "наружу": "нормаль",
              "вниз": "вниз", "down": "вниз", "свисание": "вниз",
              "авто": "авто", "auto": "авто"}.get(growth)
    if growth is None:
        raise GeometryError("hair: growth=нормаль, вниз или авто.")
    dir_raw = a.vec("dir", 3, default=None)
    flow = (np.asarray(dir_raw, dtype=np.float64).reshape(3) if dir_raw is not None
            else np.asarray([0.0, 0.0, -1.0]))
    if float(np.linalg.norm(flow)) < 1e-9:
        raise GeometryError("hair: dir не должен быть нулевым.")
    flow /= float(np.linalg.norm(flow))
    align_raw = a.num("tip_align", None, minv=0.0, maxv=1.0)
    if align_raw is None:
        align_raw = a.num("align", None, minv=0.0, maxv=1.0)

    mesh = base.manifold.to_mesh()
    verts = np.asarray(mesh.vert_properties, dtype=np.float64)[:, :3]
    faces = np.asarray(mesh.tri_verts, dtype=np.int64).reshape(-1, 3)
    bb = base.manifold.bounding_box()
    ext = np.asarray([bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]])
    base_centre = np.asarray([(bb[i] + bb[i + 3]) * 0.5 for i in range(3)])
    down_mode = growth == "вниз" or dir_raw is not None
    if growth == "авто" and style in ("волоски", "пряди", "водоросли"):
        down_mode = length > max(30.0, float(ext.min()) * 1.5)
    tip_align = float(align_raw) if align_raw is not None else (0.85 if down_mode else 0.0)
    drape = a.boolean("drape", down_mode)
    points, normals = _surface_samples(
        verts, faces, max(3000, min(40000, count * (40 if density_mode else 14))), rng)
    mask = np.ones(len(points), dtype=bool)
    if surface != "вся":
        side = np.asarray(sides[surface], dtype=np.float64)
        mask &= (normals @ side) > 0.25
    if patch_at is not None and patch_radius > 0:
        centre = np.asarray(patch_at, dtype=np.float64).reshape(3)
        mask &= np.linalg.norm(points - centre, axis=1) <= patch_radius
    indices = np.flatnonzero(mask)
    if len(indices) == 0 or (not density_mode and len(indices) < count):
        raise GeometryError(f"На выбранной поверхности найдено только {len(indices)} из {count} корней.",
                            hint="Увеличьте surface/radius или уменьшите count.")
    points, normals = points[indices], normals[indices]
    available_area = float(base.manifold.surface_area()) * len(indices) / len(mask)
    # Сначала раскладываем корни с реальным зазором. Для широких прядей и
    # листьев используется их ширина, а не только тонкое сечение.
    root_gap = (max(thick * 1.25, strand_width * 1.05)
                if style in ("пряди", "водоросли") else thick * 1.25)
    chosen = ([] if density_mode and float(density) <= 0.0
              else [int(rng.integers(0, len(points)))])
    best = (np.full(len(points), -1.0) if not chosen else
            np.sum((points - points[chosen[0]]) ** 2, axis=1))
    if chosen:
        best[chosen[0]] = -1.0
    while (density_mode and float(density) > 0.0 and len(chosen) < 800) or (not density_mode and len(chosen) < count):
        index = int(np.argmax(best))
        if best[index] < root_gap * root_gap:
            if density_mode:
                break
            raise GeometryError(f"На поверхности не помещаются {count} корней без пересечений.",
                                hint="Уменьшите count/thick/width или выберите больший объект.")
        chosen.append(index)
        best = np.minimum(best, np.sum((points - points[index]) ** 2, axis=1))
        best[chosen] = -1.0
    packing_capacity = len(chosen)
    if density_mode:
        count = max(0, int(round(packing_capacity * float(density) / 100.0)))
        chosen = chosen[:count]
    selected = np.asarray(chosen, dtype=np.int64)
    points, normals = points[selected], normals[selected]
    count = len(selected)

    pieces: list[mf.Manifold] = []
    root = max(0.25, thick * 0.65)
    for p, normal in zip(points, normals):
        normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
        tangent = rng.normal(0.0, 1.0, 3)
        tangent -= normal * float(np.dot(tangent, normal))
        if float(np.linalg.norm(tangent)) < 1e-8:
            tangent = np.cross(normal, np.array([1.0, 0.0, 0.0]))
        tangent /= max(float(np.linalg.norm(tangent)), 1e-12)
        direction = normal + tangent * float(rng.normal(0.0, spread * 0.55))
        direction /= max(float(np.linalg.norm(direction)), 1e-12)
        ln = length * (1.0 - spread * 0.55 * rng.random())
        start = p - normal * root
        if style == "иголки":
            piece = mf.Manifold.cylinder(ln + root, thick * 0.5, 0.0, 8, False)
            frame = _frame(direction)
            frame[:, 3] = start
            pieces.append(piece.transform(frame))
        elif style == "локоны":
            steps = int(np.clip(24 + turns * 18, 28, 180))
            t = np.linspace(0.0, 1.0, steps)
            other = np.cross(direction, tangent)
            other /= max(float(np.linalg.norm(other)), 1e-12)
            angle = 2.0 * math.pi * turns * t
            rr = curl_radius * (1.0 - np.exp(-8.0 * t)) * (1.0 - 0.35 * t)
            path = (start[None, :] + direction[None, :] * (ln * t)[:, None]
                    + tangent[None, :] * (rr * np.sin(angle))[:, None]
                    + other[None, :] * (rr * (np.cos(angle) - 1.0))[:, None])
            profile = ellipse_profile(thick, thick * 0.55, 10)
            curve = list(np.linspace(1.0, 0.06, steps) ** 0.65)
            curve[-1] = 0.02
            pieces.append(sweep_solid(path, profile, what="локона на поверхности",
                                      scale_curve=curve, round_caps=0.5))
        elif down_mode or tip_align > 1e-9:
            steps = int(np.clip(9 + ln / 22.0, 9, 20))
            path = _guided_strand_path(start, direction, flow, ln, bend, tangent,
                                       tip_align, steps,
                                       base=base.manifold if drape else None,
                                       centre=base_centre, thick=thick, drape=drape)
            if style in ("пряди", "водоросли"):
                pieces.append(_strand_from_path(
                    path, strand_width, thin_ratio=strand_thin / max(strand_width, 1e-9),
                    what="пряди" if style == "пряди" else "тонкого листа водоросли"))
            else:
                pieces.append(_strand_from_path(path, thick, what="волоса с огибанием"))
        elif style in ("пряди", "водоросли"):
            pieces.append(_clump(start, direction, ln, strand_width, strand_thin,
                                 bend, 0.0, tangent, wobble=0.35))
        else:
            pieces.append(_single_strand(start, direction, ln, thick, bend, 0.0,
                                         tangent, sharp=1.0))

    solid = mf.Manifold.batch_boolean([base.manifold] + pieces, mf.OpType.Add)
    solid = ensure_volume(solid, "волос на поверхности")
    parts = len([p for p in solid.decompose() if p.volume() > 1e-6])
    if parts != 1:
        raise GeometryError(f"Волосы не сварились с объектом: получилось {parts} частей.",
                            hint="Увеличьте thick, уменьшите spread или выберите другую surface.")
    a.scene.log("info", f"hair: {style}, surface={surface}, корней {count}, "
                        f"length={length:g}, thick={thick:g}, одно тело", a.cmd.line)
    out = _derived(a, name, solid, base, "hair")
    out.meta.update(hair_style=style, roots=count, growth="вниз" if down_mode else "нормаль",
                    tip_align=tip_align, drape=bool(drape))
    if density_mode:
        out.meta.update(density_requested=float(density), packing_capacity=packing_capacity,
                        available_area=available_area,
                        density_actual=100.0 * count / max(packing_capacity, 1))
    out.notes.append(f"наращено на исходном объекте: {style}, корней {count}, surface={surface}, "
                     f"growth={'вниз' if down_mode else 'нормаль'}, tip_align={tip_align:g}")
    return out


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
            "thick=1.1 bend=0.3 curl=0",
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
