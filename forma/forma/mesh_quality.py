"""Диагностика качества треугольной сетки: стяжки, полюса, иглы, плотность.

Зачем модуль
------------
Ядро (manifold3d) честно отвечает на вопросы «замкнуто ли» и «герметично ли»,
но молчит о том, что видно глазом: как именно сетка уложена. Из-за этого
дефекты вроде «веера из 74 треугольников в одной точке», «игл на фаске
цилиндра» или «сгустка на стыке с цилиндром» всплывают уже на скриншоте,
когда править дорого.

Здесь считается то, что в литературе по сеткам называют *quality metrics*
(Shewchuk 2002; Sorgente et al. 2023) и *degenerate element classification*
(Botsch & Kobbelt 2004), плюс две метрики топологии, которых в этих статьях
нет, но которые нужны именно для CSG-моделей:

  * **полюс** (hub) — вершина с аномально большой валентностью;
  * **стяжка** (fan/strut) — полюс, у которого все треугольники «иглы»;
  * **перегруз плотности** — участок, где на единицу площади приходится в
    разы больше треугольников, чем в медиане (неравномерный sizing field,
    Frey & Borouchaki 1999);
  * **шов** (seam) — стык двух гладких областей, где длины рёбер отличаются
    в разы: типичный след булевой операции «цилиндр × плита».

Всё считается в долях площади, а не в штуках: 300 игл на 1 мм² и 300 игл на
всей детали — разные вещи.

Публичный интерфейс
-------------------
    mq = analyze(solid.manifold)            # Manifold
    mq = analyze((verts, faces))            # голые массивы
    print(format_report(mq))
    warnings = short_warnings(mq)           # строки для отчёта сборки

Пороги меняются через `Rules(...)`; значения по умолчанию подобраны по
деталям ФОРМЫ (кронштейн 00.039, корпусные тела 50–250 мм).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "Rules", "analyze", "format_report", "short_warnings", "mesh_of",
    "Artifact", "link_cycles", "vertex_links",
]


# --------------------------------------------------------------------------- #
#  Пороги
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Rules:
    """Пороги. Углы в градусах, площади в долях от общей площади сетки."""

    needle_deg: float = 5.0        # «игла»: угол меньше этого
    cap_deg: float = 170.0         # «колпак»: угол больше этого
    sliver_area_pct: float = 1.0   # допустимая доля площади под иглами
    hub_valence: int = 12          # валентность, выше которой вершина — полюс
    hub_ratio: float = 2.5         # …и во сколько раз она больше медианы
    strut_min_faces: int = 8       # сколько игл в звезде делают стяжку
    density_ratio: float = 10.0    # перегруз: faces/мм² к медиане
    density_min_faces: int = 10    # …и не меньше стольких треугольников
    seam_ratio: float = 6.0        # скачок длины ребра на гладком стыке
    seam_flat_deg: float = 25.0    # стык считается гладким до этого угла
    seam_edge_factor: float = 2.0  # шов ищем только на рёбрах длиннее медианы×это
    seam_min_edges: int = 6        # мельче — это не зона, а случайное ребро
    density_min_cluster: int = 3   # мельче — не сгусток, а одна вершина
    curved_deg: float = 5.0        # сосед с нормалью дальше этого — кривизна
    top: int = 5                   # сколько мест показывать в отчёте


# --------------------------------------------------------------------------- #
#  Служебные структуры
# --------------------------------------------------------------------------- #

@dataclass
class Artifact:
    """Одно найденное место: что, где и насколько."""
    kind: str                # "полюс", "стяжка", "игла", "перегруз", "шов"
    where: tuple[float, float, float]
    value: float             # численная мера (валентность, отношение, площадь)
    detail: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "where": [round(c, 2) for c in self.where],
                "value": round(float(self.value), 3), "detail": self.detail}


def _face_array(value) -> np.ndarray:
    """Принимает N×3 и плоский PyVista-формат [3, a, b, c, …]."""
    raw = np.asarray(value, dtype=np.int64)
    if raw.ndim == 1 and raw.size and raw.size % 4 == 0:
        cells = raw.reshape(-1, 4)
        if np.all(cells[:, 0] == 3):
            return cells[:, 1:]
    return raw.reshape(-1, 3)


def mesh_of(solid) -> tuple[np.ndarray, np.ndarray]:
    """(verts, faces) из Manifold, PyVista/Trimesh или пары массивов."""
    if isinstance(solid, (tuple, list)) and len(solid) == 2:
        v, f = solid
        return np.asarray(v, float)[:, :3], _face_array(f)
    mesh = getattr(solid, "to_mesh", None)
    if mesh is not None:                       # manifold3d.Manifold
        m = solid.to_mesh()
        v = np.asarray(m.vert_properties, float)
        return v[:, :3], _face_array(m.tri_verts)
    if hasattr(solid, "faces") and (hasattr(solid, "vertices") or hasattr(solid, "points")):
        vertices = solid.vertices if hasattr(solid, "vertices") else solid.points
        return np.asarray(vertices, float)[:, :3], _face_array(solid.faces)
    raise TypeError("analyze принимает Manifold, (verts, faces), trimesh или pyvista")


def _edge_index(faces: np.ndarray) -> dict[tuple[int, int], list[int]]:
    edges: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, tri in enumerate(faces.tolist()):
        a, b, c = tri
        edges[(a, b) if a < b else (b, a)].append(i)
        edges[(b, c) if b < c else (c, b)].append(i)
        edges[(c, a) if c < a else (a, c)].append(i)
    return edges


def _clusters(indices, edges, verts) -> list[list[int]]:
    """Склеивает помеченные вершины в связные куски по рёбрам сетки.

    Один дефект обычно занимает не одну вершину, а пятачок: 30 «перегруженных»
    вершин на фаске — это один сгусток, а не 30 замечаний.
    """
    wanted = set(int(i) for i in indices)
    if not wanted:
        return []
    adj: dict[int, list[int]] = defaultdict(list)
    for (a, b) in edges:
        if a in wanted and b in wanted:
            adj[a].append(b)
            adj[b].append(a)
    seen: set[int] = set()
    out: list[list[int]] = []
    for start in wanted:
        if start in seen:
            continue
        comp, stack = [], [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(adj.get(cur, ()))
        out.append(comp)
    out.sort(key=len, reverse=True)
    return out


def vertex_links(faces: np.ndarray) -> dict[int, set[int]]:
    """Для каждой вершины — множество соседних вершин (её «зонтик»)."""
    links: dict[int, set[int]] = defaultdict(set)
    for a, b, c in faces.tolist():
        links[a].update((b, c))
        links[b].update((a, c))
        links[c].update((a, b))
    return links


def link_edges(faces: np.ndarray) -> dict[int, list[tuple[int, int]]]:
    """Рёбра «зонта» каждой вершины: пары соседей, соединённых ребром.

    Для вершины v каждый её треугольник (v, a, b) даёт ребро (a, b). Один
    проход по граням — и дальше число колец считается локально, без обхода
    всей сетки на каждую вершину.
    """
    out: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for a, b, c in faces.tolist():
        out[a].append((b, c))
        out[b].append((c, a))
        out[c].append((a, b))
    return out


def _components(nodes: set[int], edges: list[tuple[int, int]]) -> int:
    """Сколько связных кусков в графе «соседи вершины»."""
    parent = {n: n for n in nodes}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        if a not in parent or b not in parent:
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    return len({find(n) for n in nodes})


def link_cycles(faces: np.ndarray, vertex: int, links=None, edges=None) -> int:
    """Сколько замкнутых колец образуют соседи вершины.

    У обычной вершины замкнутой поверхности кольцо одно. Два и больше — это
    «песочные часы»: две поверхности касаются в одной точке. Внешне выглядит
    как стяжка, но лечится по-другому (сдвигом одной из частей), поэтому
    считается отдельно.
    """
    vertex = int(vertex)
    if links is None:
        links = vertex_links(faces)
    if edges is None:
        edges = link_edges(faces)
    nbrs = links.get(vertex) or set()
    if not nbrs:
        return 0
    return _components(set(nbrs), edges.get(vertex) or [])


# --------------------------------------------------------------------------- #
#  Основной анализ
# --------------------------------------------------------------------------- #

def analyze(solid, rules: Rules | None = None) -> dict:
    """Полный отчёт по сетке. Возвращает словарь, пригодный для JSON."""
    r = rules or Rules()
    verts, faces = mesh_of(solid)
    n_faces = len(faces)
    if n_faces and (int(faces.min()) < 0 or int(faces.max()) >= len(verts)):
        raise ValueError("грань ссылается на несуществующую вершину")
    report: dict = {
        "faces": int(n_faces),
        "vertices": int(len(verts)),
        "rules": {k: getattr(r, k) for k in r.__dataclass_fields__},
        "ok": True,
        "problems": [],
        "artifacts": [],
    }
    if n_faces == 0:
        report["ok"] = False
        report["problems"].append("сетка пуста")
        return report

    tri = verts[faces]
    e0 = np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1)
    e1 = np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1)
    e2 = np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)
    area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                        tri[:, 2] - tri[:, 0]), axis=1)
    total_area = float(area.sum())

    # ---- углы: минимальный и максимальный в каждом треугольнике ----------
    def _angle(opp: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        cos = (u * u + v * v - opp * opp) / np.maximum(2.0 * u * v, 1e-12)
        return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))

    ang = np.stack([_angle(e0, e1, e2), _angle(e1, e2, e0), _angle(e2, e0, e1)])
    min_ang = ang.min(axis=0)
    max_ang = ang.max(axis=0)

    # Shewchuk 2002: качество треугольника = 2A/(l_max·h), нормированное так,
    # что у равностороннего единица. Через площадь и наибольшую сторону.
    l_max = np.maximum.reduce([e0, e1, e2])
    quality = 2.0 * math.sqrt(3.0) * area / np.maximum(l_max * l_max, 1e-12)

    needle = min_ang < r.needle_deg
    cap = max_ang > r.cap_deg
    degen = area <= max(total_area, 1e-12) * 1e-12

    report["area_mm2"] = round(total_area, 2)
    report["edge_median_mm"] = round(float(np.median(np.concatenate([e0, e1, e2]))), 3)
    report["quality_median"] = round(float(np.median(quality)), 3)
    report["min_angle_deg"] = round(float(min_ang.min()), 2)
    # Иглы бывают двух совсем разных сортов. На плоском участке все нормали
    # одинаковы, и «звезда» из треугольников не даёт ни одного видимого
    # артефакта — это косметика. На кривизне (фаска, стык с цилиндром) каждая
    # игла даёт свою нормаль, и получаются те самые «артефактные полигоны».
    edges = _edge_index(faces)
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(nrm, axis=1)
    ok_n = ln > 1e-12
    nrm[ok_n] /= ln[ok_n, None]
    # «Видимая» игла: её САМОЕ ДЛИННОЕ ребро выходит на соседа с другой
    # нормалью. У законной вытянутой грани (боковина цилиндра, боковина
    # пластины) длинное ребро делит плоский четырёхугольник с такой же
    # нормалью — такая игла не даёт артефакта, хотя угол у неё крошечный.
    longest_idx = np.argmax(np.stack([e0, e1, e2], axis=1), axis=1)
    verts_of = [((0, 1), (1, 2), (2, 0))[i] for i in range(3)]
    visible = np.zeros(n_faces, dtype=bool)
    for f_i, tri_i in enumerate(faces.tolist()):
        v0, v1 = verts_of[longest_idx[f_i]]
        a, b = tri_i[v0], tri_i[v1]
        key = (a, b) if a < b else (b, a)
        adj = edges.get(key) or []
        if len(adj) != 2:
            continue
        other = adj[0] if adj[1] == f_i else adj[1]
        cosang = float(np.clip(np.dot(nrm[f_i], nrm[other]), -1.0, 1.0))
        visible[f_i] = math.degrees(math.acos(cosang)) > r.curved_deg
    curved = visible
    report["needle_count"] = int(needle.sum())
    report["needle_area_pct"] = round(float(area[needle].sum() / max(total_area, 1e-12) * 100), 3)
    report["needle_flat_count"] = int((needle & ~curved).sum())
    report["needle_curved_count"] = int((needle & curved).sum())
    report["needle_curved_area_pct"] = round(
        float(area[needle & curved].sum() / max(total_area, 1e-12) * 100), 3)
    report["cap_count"] = int(cap.sum())
    report["degenerate_count"] = int(degen.sum())

    # ---- топология --------------------------------------------------------
    boundary = [k for k, v in edges.items() if len(v) == 1]
    nonmanifold_edges = [k for k, v in edges.items() if len(v) > 2]
    tri_keys = [tuple(sorted(t)) for t in faces.tolist()]
    dup = len(tri_keys) - len(set(tri_keys))
    report["boundary_edges"] = len(boundary)
    report["nonmanifold_edges"] = len(nonmanifold_edges)
    report["duplicate_faces"] = int(dup)

    # ---- валентность, полюса, стяжки -------------------------------------
    faces_of: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(faces.tolist()):
        faces_of[t[0]].append(i)
        faces_of[t[1]].append(i)
        faces_of[t[2]].append(i)
    links = vertex_links(faces)
    valence = np.array([len(faces_of[v]) for v in range(len(verts))], dtype=np.int64)
    used = valence > 0
    median_val = float(np.median(valence[used])) if used.any() else 0.0
    report["valence_median"] = median_val
    report["valence_max"] = int(valence.max())
    report["valence_hist"] = {int(k): int((valence == k).sum())
                              for k in np.unique(valence[used]) if k >= r.hub_valence}

    hubs: list[tuple[int, int]] = []
    struts: list[Artifact] = []
    for v in np.nonzero(used)[0]:
        val = int(valence[v])
        if val < r.hub_valence or val < r.hub_ratio * max(median_val, 1.0):
            continue
        hubs.append((int(v), val))
        star = faces_of[int(v)]
        needles_in_star = int(needle[star].sum())
        star_area = float(area[star].sum())
        if needles_in_star >= r.strut_min_faces:
            share = needles_in_star / len(star)
            struts.append(Artifact("стяжка", tuple(float(c) for c in verts[v]),
                                   float(needles_in_star),
                                   f"валентность {val}, игл {needles_in_star} "
                                   f"({share * 100:.0f} % звезды), "
                                   f"площадь звезды {star_area:.2f} мм²"))
    hubs.sort(key=lambda t: -t[1])
    report["hub_count"] = len(hubs)
    report["hubs"] = [{"where": [round(float(c), 2) for c in verts[v]], "valence": val}
                      for v, val in hubs[:r.top]]
    struts.sort(key=lambda a: -a.value)
    report["strut_count"] = len(struts)

    # ---- перегруз плотности ---------------------------------------------
    dens = np.zeros(len(verts))
    for v in np.nonzero(used)[0]:
        star = faces_of[int(v)]
        dens[v] = len(star) / max(float(area[star].sum()), 1e-9)
    med_dens = float(np.median(dens[used])) if used.any() else 0.0
    report["density_median_per_mm2"] = round(med_dens, 4)
    star_area = np.zeros(len(verts))
    for v in np.nonzero(used)[0]:
        star_area[v] = float(area[faces_of[int(v)]].sum())
    # звезда из вырожденных треугольников даёт плотность «на нуле» — это
    # отдельный дефект (вырожденные грани), а не перегруз
    solid_star = star_area > max(total_area, 1e-12) * 1e-6
    hot = np.nonzero((dens > r.density_ratio * max(med_dens, 1e-12))
                     & (valence >= r.density_min_faces) & solid_star)[0]
    clusters = _clusters(hot, edges.keys(), verts)
    hotspots = []
    for comp in clusters:
        if len(comp) < r.density_min_cluster:
            continue
        worst = max(comp, key=lambda v: dens[v])
        centre = verts[comp].mean(axis=0)
        hotspots.append(Artifact(
            "перегруз", tuple(float(c) for c in centre),
            float(dens[worst] / max(med_dens, 1e-12)),
            f"{len(comp)} вершин, максимум {int(valence[worst])} треугольников "
            f"на {float(area[faces_of[int(worst)]].sum()):.2f} мм²"))
    hotspots.sort(key=lambda a: -a.value)
    report["density_hotspot_vertices"] = int(len(hot))
    report["density_hotspot_count"] = len(hotspots)

    # ---- швы: гладкий стык с разной крупностью сетки ---------------------
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm_len = np.linalg.norm(normals, axis=1)
    normals[norm_len > 1e-12] /= norm_len[norm_len > 1e-12, None]
    edge_len = {}
    for (a, b), idx in edges.items():
        edge_len[(a, b)] = float(np.linalg.norm(verts[a] - verts[b]))
    edge_limit = r.seam_edge_factor * report["edge_median_mm"]
    seams: list[Artifact] = []
    for (a, b), idx in edges.items():
        if len(idx) != 2:
            continue
        i, j = idx
        cosang = float(np.clip(np.dot(normals[i], normals[j]), -1.0, 1.0))
        if math.degrees(math.acos(cosang)) > r.seam_flat_deg:
            continue
        if edge_len[(a, b)] < edge_limit:
            continue
        big, small = max(area[i], area[j]), min(area[i], area[j])
        ratio = big / max(small, 1e-12)
        if ratio <= r.seam_ratio:
            continue
        mid = (verts[a] + verts[b]) / 2.0
        seams.append(Artifact("шов", tuple(float(c) for c in mid), float(ratio),
                              f"ребро {edge_len[(a, b)]:.2f} мм, "
                              f"площади соседей {big:.2f} / {small:.2f} мм²"))
    seams.sort(key=lambda a: -a.value)
    # швы тоже группируем: один стык цилиндра с плитой — это одна зона,
    # а не 400 отдельных рёбер
    cell = max(2.0 * report["edge_median_mm"], 1e-6)
    zones: dict[tuple[int, int, int], list[Artifact]] = defaultdict(list)
    for a in seams:
        zones[(int(a.where[0] // cell), int(a.where[1] // cell),
               int(a.where[2] // cell))].append(a)
    seam_zones = []
    for group in zones.values():
        if len(group) < r.seam_min_edges:
            continue
        worst = max(group, key=lambda a: a.value)
        seam_zones.append(Artifact("шов", worst.where, worst.value,
                                   f"{len(group)} рёбер, наибольший перепад "
                                   f"площадей ×{worst.value:.0f}"))
    seam_zones.sort(key=lambda a: -a.value)
    report["seam_edges"] = len(seams)
    report["seam_count"] = len(seam_zones)

    # ---- структурные ошибки ---------------------------------------------
    problems = []
    if boundary:
        problems.append(f"граничных рёбер: {len(boundary)} (не замкнуто)")
    if nonmanifold_edges:
        problems.append(f"non-manifold рёбер: {len(nonmanifold_edges)}")
    if dup:
        problems.append(f"дублирующихся граней: {dup}")
    if degen.sum():
        problems.append(f"вырожденных граней: {int(degen.sum())}")
    # «Песочные часы»: у обычной вершины замкнутой поверхности число граней в
    # звезде равно числу соседей. Если соседей меньше — звезда распалась на
    # два кольца (две поверхности касаются в одной точке). Такой дешёвый
    # признак отсеивает всех кандидатов, а дорогую проверку колец делаем
    # только для них.
    bowties = 0
    bowtie_at = []
    le = link_edges(faces)
    for v in np.nonzero(used)[0]:
        v = int(v)
        if len(links.get(v) or ()) < 3:
            continue
        if _components(set(links[v]), le[v]) > 1:
            bowties += 1
            if len(bowtie_at) < r.top:
                bowtie_at.append([round(float(c), 2) for c in verts[v]])
    report["bowties"] = bowtie_at
    report["nonmanifold_vertices"] = bowties
    if bowties:
        problems.append(f"вершин-«песошниц» (две поверхности в одной точке): {bowties}")
    if report["needle_curved_area_pct"] > r.sliver_area_pct:
        problems.append(f"иглы на кривизне занимают "
                        f"{report['needle_curved_area_pct']:.2f} % площади "
                        f"(порог {r.sliver_area_pct} %) — это видно на рендере")
    if struts:
        problems.append(f"стяжек: {len(struts)}")
    if hotspots:
        problems.append(f"перегрузов плотности: {len(hotspots)}")

    report["problems"] = problems
    # «ok» — это вердикт для check/CI, а не только признак замкнутости.
    # Дубли, стяжки, перегрузы и превышение порога игл тоже должны дать
    # ненулевой код возврата; иначе JSON называл сетку чистой при проблемах.
    report["ok"] = not problems
    seams = seam_zones
    artifacts = struts[:r.top] + hotspots[:r.top] + seams[:r.top]
    report["artifacts"] = [a.as_dict() for a in artifacts]
    return report


# --------------------------------------------------------------------------- #
#  Печать
# --------------------------------------------------------------------------- #

def format_report(report: dict, titles: bool = True) -> str:
    """Человеческий отчёт по результату `analyze`."""
    r = report
    lines = []
    if titles:
        lines.append("КАЧЕСТВО СЕТКИ")
    if not r.get("faces"):
        lines.append("• сетка пуста")
        return "\n".join(lines)
    lines.append(f"• треугольников {r['faces']:,}".replace(",", " ")
                 + f", вершин {r['vertices']:,}".replace(",", " ")
                 + f", площадь {r['area_mm2']:g} мм²")
    lines.append(f"• медиана: ребро {r['edge_median_mm']:g} мм, качество "
                 f"{r['quality_median']:g} (1 — равносторонний), "
                 f"валентность {r['valence_median']:g}")
    lines.append(f"• минимум: угол {r['min_angle_deg']:g}°, игл {r['needle_count']} "
                 f"({r['needle_area_pct']:g} % площади), из них на кривизне "
                 f"{r['needle_curved_count']} ({r['needle_curved_area_pct']:g} %), "
                 f"колпаков {r['cap_count']}")
    lines.append(f"• полюсов (валентность ≥ {r['rules']['hub_valence']}): "
                 f"{r['hub_count']}, самая большая валентность {r['valence_max']}; "
                 f"стяжек {r['strut_count']}")
    lines.append(f"• перегрузов плотности: {r['density_hotspot_count']} "
                 f"(медиана {r['density_median_per_mm2']:g} трис/мм²); "
                 f"швов {r['seam_count']}")
    if r.get("hubs"):
        top = ", ".join(f"{h['valence']} в ({h['where'][0]:g}, {h['where'][1]:g}, "
                        f"{h['where'][2]:g})" for h in r["hubs"][:3])
        lines.append(f"• главные полюса: {top}")
    if r["problems"]:
        lines.append("")
        lines.append("ПРОБЛЕМЫ СЕТКИ")
        for p in r["problems"]:
            lines.append(f"• {p}")
    return "\n".join(lines)


def short_warnings(report: dict) -> list[str]:
    """Короткие строки для блока ЗАМЕЧАНИЯ в отчёте сборки."""
    out = []
    if report.get("strut_count"):
        a = (report.get("artifacts") or [None])[0]
        where = ""
        if a is not None:
            x, y, z = a["where"]
            where = f" (крупнейшая в ({x:g}, {y:g}, {z:g}))"
        out.append(f"Стяжка в сетке: {report['strut_count']} полюс(ов) с веером игл"
                   f"{where} — на рендере видно как «звезда» из треугольников")
    if report.get("density_hotspot_count"):
        out.append(f"Неравномерная плотность сетки: {report['density_hotspot_count']} "
                   f"сгустк(ов), медиана {report['density_median_per_mm2']:g} трис/мм²")
    if report.get("seam_count"):
        out.append(f"Швы с разной крупностью: {report['seam_count']} мест, где "
                   f"соседние треугольники отличаются площадью более чем в "
                   f"{report['rules']['seam_ratio']:g} раз")
    if report.get("needle_curved_area_pct", 0) > report.get("rules", {}).get("sliver_area_pct", 1.0):
        out.append(f"Тонкие треугольники на кривизне: {report['needle_curved_count']} шт, "
                   f"{report['needle_curved_area_pct']:g} % площади — видно на рендере")
    return out
