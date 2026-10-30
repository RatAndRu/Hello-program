#!/usr/bin/env python3
"""Аудит топологии готовой сетки: GLB (glTF 2.0) и OBJ.

Скрипт отвечает на вопрос «что в этой сетке сломано и где», не открывая
редактор. Он не строит геометрию и не требует numpy/trimesh — только stdlib,
поэтому запускается где угодно, в том числе в CI.

    python3 forma/tools/topology_audit.py файл.glb
    python3 forma/tools/topology_audit.py файл.glb --json отчёт.json
    python3 forma/tools/topology_audit.py файл.obj --weld 0.01 --min-angle 5

Что проверяется
---------------
1.  Сварка: сколько вершин стоят в одной точке (дубли, «шов» из двух половин).
2.  Многообразие: рёбра с 1 гранью (дырка), с >2 гранями (non-manifold),
    рёбра с одинаковым обходом (перевёрнутая / несогласованная нормаль).
3.  Мусор: вырожденные треугольники (нулевая площадь), повторяющиеся грани,
    вершины-сироты, нулевые рёбра.
4.  Оболочки: сколько отдельных кусков, какие замкнуты, их род (genus),
    знак объёма (наружу ли нормали).
5.  Качество треугольников: «иглы» (угол < порога) и вытянутые
    (отношение сторон > порога). Иглы делятся на плоские — они безвредны,
    раз все соседи в одной плоскости, — и иглы на изгибе, которые портят
    интерполяцию нормалей и дают полосы при сглаживании.
6.  Валентность вершин: полюса 3/5 и «звёзды» 6+.
    В треугольной сетке регулярна валентность 6, в квадовой — 4; скрипт
    считает обе шкалы, потому что у GLB всегда треугольники.
7.  Плотность: длина рёбер (мин/медиана/макс) и разброс плотности —
    именно он даёт волны при подразбиении.

Коды возврата: 0 — грубых дефектов нет, 1 — есть, 2 — файл не прочитан.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Чтение файлов
# --------------------------------------------------------------------------- #

COMPONENT = {
    5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
    5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4),
}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class ParseError(Exception):
    pass


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    if len(data) < 12:
        raise ParseError("файл короче заголовка GLB")
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ParseError("это не GLB (нет подписи glTF)")
    if version != 2:
        raise ParseError(f"GLB версии {version}: поддерживается только 2")
    if total != len(data):
        # не фатально: некоторые писатели оставляют старую длину
        pass
    js: dict | None = None
    binary = b""
    off = 12
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        body = data[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(body.decode("utf-8"))
        elif ctype == 0x004E4942:
            binary = body
        off += 8 + clen + (-clen % 4)
    if js is None:
        raise ParseError("в GLB нет JSON-чанка")
    return js, binary


def _accessor(js: dict, binary: bytes, index: int) -> list:
    acc = js["accessors"][index]
    count = int(acc["count"])
    ncomp = NCOMP.get(acc["type"], 1)
    fmt, size = COMPONENT[acc["componentType"]]
    if "bufferView" not in acc:
        return [tuple([0.0] * ncomp)] * count if ncomp > 1 else [0.0] * count
    bv = js["bufferViews"][acc["bufferView"]]
    base = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    stride = int(bv.get("byteStride", 0)) or size * ncomp
    out = []
    unpack = struct.Struct("<" + fmt * ncomp).unpack_from
    for i in range(count):
        vals = unpack(binary, base + i * stride)
        out.append(vals[0] if ncomp == 1 else vals)
    if acc.get("normalized") and fmt in "BH":
        m = 255.0 if fmt == "B" else 65535.0
        out = [tuple(v / m for v in item) if ncomp > 1 else item / m for item in out]
    return out


def read_glb_meshes(path: Path) -> tuple[list[dict], dict]:
    js, binary = read_glb(path)
    meshes = []
    for mi, mesh in enumerate(js.get("meshes", [])):
        name = mesh.get("name") or f"mesh_{mi}"
        for pi, prim in enumerate(mesh.get("primitives", [])):
            mode = int(prim.get("mode", 4))
            if mode != 4:
                meshes.append({"name": f"{name}", "skipped": f"режим {mode} (не треугольники)"})
                continue
            attrs = prim.get("attributes", {})
            if "POSITION" not in attrs:
                continue
            verts = [tuple(float(c) for c in v) for v in _accessor(js, binary, attrs["POSITION"])]
            if "indices" in prim:
                idx = _accessor(js, binary, prim["indices"])
                idx = [int(i) for i in idx]
            else:
                idx = list(range(len(verts)))
            normals = None
            if "NORMAL" in attrs:
                try:
                    normals = [tuple(float(c) for c in n)
                               for n in _accessor(js, binary, attrs["NORMAL"])]
                except (KeyError, struct.error):
                    normals = None
            label = name if len(mesh.get("primitives", [])) == 1 else f"{name}[{pi}]"
            meshes.append({"name": label, "verts": verts, "tris": idx,
                           "normals": normals})
    info = {
        "формат": "GLB 2.0",
        "мешей": len(js.get("meshes", [])),
        "узлов": len(js.get("nodes", [])),
        "расширения": js.get("extensionsUsed", []),
        "генератор": (js.get("asset") or {}).get("generator", ""),
    }
    return meshes, info


def read_obj_meshes(path: Path) -> tuple[list[dict], dict]:
    verts: list[tuple] = []
    groups: dict[str, list[int]] = {}
    current = "obj"
    groups[current] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("v "):
            parts = line.split()
            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif line[:2] in ("o ", "g "):
            current = line[2:].strip() or current
            groups.setdefault(current, [])
        elif line.startswith("f "):
            face = []
            for tok in line.split()[1:]:
                i = int(tok.split("/")[0])
                face.append(i - 1 if i > 0 else len(verts) + i)
            # веерная триангуляция n-гона — так же, как это делает большинство
            # экспортёров без «beauty»-триангуляции
            for k in range(1, len(face) - 1):
                groups[current].extend([face[0], face[k], face[k + 1]])
    meshes = []
    for name, tris in groups.items():
        if not tris:
            continue
        # индексы в OBJ глобальные: сжимаем их в локальные, чтобы объекты
        # не «слипались» при сварке по совпадающим координатам
        used = sorted(set(tris))
        local = {g: i for i, g in enumerate(used)}
        meshes.append({
            "name": name,
            "verts": [verts[i] for i in used],
            "tris": [local[i] for i in tris],
        })
    return meshes, {"формат": "OBJ", "мешей": len(meshes), "узлов": None,
                    "расширения": [], "генератор": ""}


# --------------------------------------------------------------------------- #
#  Топологические примитивы
# --------------------------------------------------------------------------- #

def weld(verts: list[tuple], tol: float) -> tuple[list[int], int]:
    """Возвращает (карта старый→новый индекс, сколько вершин слилось).

    Слияние по сетке с проверкой 26 соседних ячеек: иначе две вершины,
    стоящие на 1e-9 по разные стороны границы ячейки, не слились бы.
    """
    if tol <= 0:
        return list(range(len(verts))), 0
    cells: dict[tuple, list[int]] = {}
    parent = list(range(len(verts)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    keys = []
    for i, (x, y, z) in enumerate(verts):
        key = (round(x / tol), round(y / tol), round(z / tol))
        keys.append(key)
        cells.setdefault(key, []).append(i)

    for i, key in enumerate(keys):
        own = cells[key]
        if len(own) > 1:
            head = own[0]
            for j in own[1:]:
                union(head, j)
        cx, cy, cz = key
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    if dx == 0 and dy == 0 and dz == 0:
                        continue
                    other = cells.get((cx + dx, cy + dy, cz + dz))
                    if not other:
                        continue
                    ax, ay, az = verts[i]
                    for j in other:
                        bx, by, bz = verts[j]
                        if abs(ax - bx) <= tol and abs(ay - by) <= tol and abs(az - bz) <= tol:
                            union(i, j)
    remap = {}
    out = []
    for i in range(len(verts)):
        root = find(i)
        if root not in remap:
            remap[root] = len(remap)
        out.append(remap[root])
    return out, len(verts) - len(remap)


def normal_health(verts: list[tuple], normals: list[tuple] | None,
                  tris: list[int]) -> dict:
    """Насколько заявленные нормали соответствуют геометрии.

    Считается по «сырым» индексам, до сварки: glTF намеренно разводит вершины
    по швам UV и жёстким рёбрам, поэтому сварка смешала бы разные нормали.
    """
    if not normals or len(normals) < len(verts):
        return {"есть": False}
    dots = []
    inward = 0
    flat = 0
    for t in range(0, len(tris) - 2, 3):
        a, b, c = tris[t], tris[t + 1], tris[t + 2]
        pa, pb, pc = verts[a], verts[b], verts[c]
        u = [pb[i] - pa[i] for i in range(3)]
        v = [pc[i] - pa[i] for i in range(3)]
        n = [u[1] * v[2] - u[2] * v[1],
             u[2] * v[0] - u[0] * v[2],
             u[0] * v[1] - u[1] * v[0]]
        ln = math.dist((0, 0, 0), n)
        if ln <= 1e-12:
            continue
        n = [x / ln for x in n]
        na, nb, nc = normals[a], normals[b], normals[c]
        avg = [na[i] + nb[i] + nc[i] for i in range(3)]
        la = math.dist((0, 0, 0), avg)
        if la <= 1e-12:
            continue
        d = sum(n[i] * avg[i] for i in range(3)) / la
        dots.append(d)
        if d < 0:
            inward += 1
        elif d < 0.5:
            flat += 1
    if not dots:
        return {"есть": True, "проверено": 0}
    return {
        "есть": True,
        "проверено": len(dots),
        "средний_dot": sum(dots) / len(dots),
        "доля_перевёрнутых_%": 100.0 * inward / len(dots),
        "доля_расхождений_%": 100.0 * flat / len(dots),
    }


def analyse(verts: list[tuple], tris: list[int], tol: float,
            min_angle: float, max_aspect: float) -> dict:
    remap, merged = weld(verts, tol)
    nv = (max(remap) + 1) if remap else 0

    # --- грани: убираем вырожденные по индексам, но считаем их ---------------
    faces = []
    degenerate_idx = 0
    repeat_idx = 0
    for t in range(0, len(tris) - 2, 3):
        a, b, c = remap[tris[t]], remap[tris[t + 1]], remap[tris[t + 2]]
        if a == b or b == c or a == c:
            degenerate_idx += 1
            continue
        faces.append((a, b, c))

    # --- геометрия ----------------------------------------------------------
    # координаты после сварки
    pos = [None] * nv
    for i, r in enumerate(remap):
        if pos[r] is None:
            pos[r] = verts[i]

    def sub(p, q):
        return (p[0] - q[0], p[1] - q[1], p[2] - q[2])

    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0])

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    def norm(u):
        return math.sqrt(dot(u, u))

    # масштаб для порога площади: средняя длина ребра
    edge_len = []
    area = 0.0
    degenerate_area = 0
    slivers = 0
    sliver_area = 0.0
    stretched = 0
    stretched_area = 0.0
    min_ang_seen = 180.0
    vol6 = 0.0
    fnorm: list[tuple] = []      # единичная нормаль грани, по индексу грани
    is_sliver: list[bool] = []   # игла ли грань
    for a, b, c in faces:
        pa, pb, pc = pos[a], pos[b], pos[c]
        n = cross(sub(pb, pa), sub(pc, pa))
        twice = norm(n)
        area += twice * 0.5
        vol6 += dot(pa, cross(pb, pc))
        e = [norm(sub(pb, pa)), norm(sub(pc, pb)), norm(sub(pa, pc))]
        edge_len.extend(e)
        if twice <= 1e-12:
            degenerate_area += 1
            fnorm.append((0.0, 0.0, 0.0))
            is_sliver.append(False)
            continue
        fnorm.append((n[0] / twice, n[1] / twice, n[2] / twice))
        is_sliver.append(False)
        longest = max(e)
        shortest = min(e)
        if shortest > 0 and longest / shortest > max_aspect:
            stretched += 1
            stretched_area += twice * 0.5
        # минимальный угол
        best = 180.0
        for i in range(3):
            u = sub(pos[(a, b, c)[(i + 1) % 3]], pos[(a, b, c)[i]])
            v = sub(pos[(a, b, c)[(i + 2) % 3]], pos[(a, b, c)[i]])
            nu, nvv = norm(u), norm(v)
            if nu <= 0 or nvv <= 0:
                continue
            cos = max(-1.0, min(1.0, dot(u, v) / (nu * nvv)))
            best = min(best, math.degrees(math.acos(cos)))
        min_ang_seen = min(min_ang_seen, best)
        if best < min_angle:
            slivers += 1
            sliver_area += twice * 0.5
            is_sliver[len(fnorm) - 1] = True

    # --- рёбра --------------------------------------------------------------
    edge_faces: dict[tuple, list[tuple]] = defaultdict(list)
    for f, (a, b, c) in enumerate(faces):
        for u, v in ((a, b), (b, c), (c, a)):
            key = (u, v) if u < v else (v, u)
            edge_faces[key].append((f, u, v))

    boundary = 0
    nonmanifold = 0
    bad_winding = 0
    for key, uses in edge_faces.items():
        if len(uses) == 1:
            boundary += 1
        elif len(uses) > 2:
            nonmanifold += 1
        else:
            # у согласованной сетки соседние грани идут по ребру в разные стороны
            if uses[0][1:] == uses[1][1:]:
                bad_winding += 1

    # --- иглы на изогнутой поверхности -------------------------------------
    # Игла в плоской панели безвредна: её длинные стороны граничат с такими же
    # плоскими треугольниками, нормаль одна на всю панель. Игла на скруглении
    # опасна: нормали вдоль длинной стороны разные, интерполяция даёт полосы.
    # Поэтому смотрим не на все соседи, а только на соседей через две длинные
    # стороны — именно вдоль них тянется поверхность.
    bad_sliver = 0
    bad_sliver_area = 0.0
    for f, (a, b, c) in enumerate(faces):
        if not is_sliver[f]:
            continue
        pa, pb, pc = pos[a], pos[b], pos[c]
        sides = [((a, b), norm(sub(pb, pa))),
                 ((b, c), norm(sub(pc, pb))),
                 ((c, a), norm(sub(pa, pc)))]
        sides.sort(key=lambda item: -item[1])
        worst = 0.0
        for (u, v), _length in sides[:2]:
            key = (u, v) if u < v else (v, u)
            for g, _gu, _gv in edge_faces.get(key, ()):
                if g == f:
                    continue
                d = dot(fnorm[f], fnorm[g])
                ang = math.degrees(math.acos(max(-1.0, min(1.0, d))))
                if ang > worst:
                    worst = ang
        # 2…30° — плавный изгиб: нормали вдоль иглы действительно разные.
        # Меньше 2° — плоско, больше 30° — жёсткое ребро, там нормали всё равно
        # разведены по шву, и форма иглы ни при чём.
        if 2.0 < worst <= 30.0:
            bad_sliver += 1
            bad_sliver_area += norm(cross(sub(pb, pa), sub(pc, pa))) * 0.5

    # --- повторяющиеся грани ------------------------------------------------
    canon = Counter(tuple(sorted(f)) for f in faces)
    dup_faces = sum(n - 1 for n in canon.values() if n > 1)

    # --- вершины-сироты, валентность ---------------------------------------
    used = set()
    for f in faces:
        used.update(f)
    loose = nv - len(used)
    valence = Counter()
    for key in edge_faces:
        valence[key[0]] += 1
        valence[key[1]] += 1
    v3 = v5 = v6p = 0
    for vtx in used:
        val = valence.get(vtx, 0)
        if val == 3:
            v3 += 1
        elif val == 5:
            v5 += 1
        elif val >= 6:
            v6p += 1
    quad_regular = sum(1 for vtx in used if valence.get(vtx, 0) == 4)
    tri_regular = sum(1 for vtx in used if valence.get(vtx, 0) == 6)

    # --- оболочки (связные компоненты граней) ------------------------------
    parent = list(range(len(faces)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for uses in edge_faces.values():
        if len(uses) > 1:
            f0 = find(uses[0][0])
            for other in uses[1:]:
                r = find(other[0])
                if r != f0:
                    parent[r] = f0
    shells: dict[int, dict] = {}
    for f in range(len(faces)):
        shells.setdefault(find(f), {"faces": 0, "boundary": 0, "edges": set(),
                                    "verts": set(), "volume6": 0.0})["faces"] += 1
    for key, uses in edge_faces.items():
        sh = shells[find(uses[0][0])]
        sh["edges"].add(key)
        if len(uses) == 1:
            sh["boundary"] += 1
    for f, (a, b, c) in enumerate(faces):
        sh = shells[find(f)]
        sh["verts"].update((a, b, c))
        pa, pb, pc = pos[a], pos[b], pos[c]
        sh["volume6"] += dot(pa, cross(pb, pc))

    shells_out = []
    for sh in shells.values():
        v, e, fc = len(sh["verts"]), len(sh["edges"]), sh["faces"]
        chi = v - e + fc
        closed = sh["boundary"] == 0
        shells_out.append({
            "faces": fc,
            "verts": v,
            "edges": e,
            "boundary_edges": sh["boundary"],
            "closed": closed,
            "euler": chi,
            # у замкнутой ориентируемой поверхности χ = 2 - 2g
            "genus": (2 - chi) // 2 if closed else None,
            "volume": sh["volume6"] / 6.0,
        })
    shells_out.sort(key=lambda s: s["faces"], reverse=True)

    def pct(a: int, b: int) -> float:
        return 100.0 * a / b if b else 0.0

    edge_len.sort()
    med = edge_len[len(edge_len) // 2] if edge_len else 0.0
    return {
        "вершин": nv,
        "слито_вершин": merged,
        "треугольников": len(faces),
        "площадь": area,
        "объём": vol6 / 6.0,
        "проверки": {
            "вырожденные_по_индексам": degenerate_idx,
            "вырожденные_по_площади": degenerate_area,
            "повторяющиеся_грани": dup_faces,
            "граничные_рёбра": boundary,
            "non_manifold_рёбра": nonmanifold,
            "несогласованный_обход": bad_winding,
            "вершины_сироты": loose,
            "оболочки": len(shells_out),
            "замкнутые_оболочки": sum(1 for s in shells_out if s["closed"]),
            "открытые_оболочки": sum(1 for s in shells_out if not s["closed"]),
        },
        "валентность": {"3": v3, "4": quad_regular, "5": v5, "6+": v6p,
                        "регулярных_квад": pct(quad_regular, len(used)),
                        "регулярных_три": pct(tri_regular, len(used))},
        "качество": {"иглы": slivers, "иглы_%": pct(slivers, len(faces)),
                     # площадь важнее штук: игла в плоской панели косметична,
                     # а игла на изогнутой поверхности портит нормали
                     "иглы_площадь_%": pct(sliver_area, area) if area else 0.0,
                     "иглы_на_изгибе": bad_sliver,
                     "иглы_на_изгибе_площадь_%": pct(bad_sliver_area, area) if area else 0.0,
                     "вытянутые": stretched, "вытянутые_%": pct(stretched, len(faces)),
                     "вытянутые_площадь_%": pct(stretched_area, area) if area else 0.0,
                     "мин_угол": min_ang_seen if faces else 0.0},
        "рёбра": {"мин": edge_len[0] if edge_len else 0.0,
                  "медиана": med,
                  "макс": edge_len[-1] if edge_len else 0.0,
                  "разброс": (edge_len[-1] / edge_len[0]) if edge_len and edge_len[0] > 0 else 0.0},
        "оболочки_детали": shells_out,
    }


# --------------------------------------------------------------------------- #
#  Вердикты
# --------------------------------------------------------------------------- #

# код: (уровень, что это, единица, чем плохо)
CODES = {
    "non_manifold": ("ошибка", "рёбра с 3+ гранями", "рёбер",
                     "нормали на стыке не определены, тело не замкнуто"),
    "boundary": ("ошибка", "граничные рёбра", "рёбер",
                 "поверхность не замкнута — дырка"),
    "winding": ("ошибка", "несогласованный обход рёбер", "рёбер",
                "у соседних граней противоположные нормали: тёмные пятна, дыры"),
    "degenerate_area": ("ошибка", "грани нулевой площади", "граней",
                        "нормаль не вычисляется, мусор после булевых операций"),
    "degenerate_index": ("ошибка", "грани, схлопнувшиеся после сварки", "граней",
                         "два угла ближе допуска: типовая болячка полюсов сферы "
                         "и стыков булевых операций"),
    "duplicate_faces": ("ошибка", "грани-дубли", "граней",
                        "z-fighting, неверный объём и знак нормали"),
    "inverted": ("ошибка", "замкнутые оболочки с отрицательным объёмом", "оболоч.",
                 "нормали смотрят внутрь"),
    "normals_inverted": ("ошибка", "нормали против геометрии", "объектов",
                         "усреднение через перевёрнутые грани"),
    "normals_flat": ("предупреждение", "нормали не сглажены", "объектов",
                     "фасетка на изогнутой поверхности"),
    "slivers": ("инфо", "треугольники-иглы", "шт.",
                "минимальный угол ниже порога. Приговор зависит от контекста: "
                "в плоской панели это косметика, на плавном изгибе — полосы "
                "при сглаживании, у длинной тонкой детали — неизбежность"),
    "stretched": ("инфо", "вытянутые треугольники", "шт.",
                  "отношение сторон выше порога"),
    "density": ("предупреждение", "неравномерная плотность", "объектов",
                "разброс длин рёбер: волны при подразбиении, плохая UV"),
    "loose": ("предупреждение", "вершины-сироты", "шт.",
              "мусор после булевых операций и удаления граней"),
    "doubles": ("инфо", "совпадающие вершины", "шт.",
                "швы нормалей/UV: в glTF это норма, в OBJ — настоящие дубли"),
    "shells": ("инфо", "отдельные оболочки", "оболоч.",
               "много кусков — лишние draw call, сложнее печать"),
}


def verdicts(rep: dict, name: str, min_angle: float, fmt: str) -> list[dict]:
    c = rep["проверки"]
    q = rep["качество"]
    out = []

    def add(code: str, value: float, note: str = "") -> None:
        if not value:
            return
        out.append({"код": code, "уровень": CODES[code][0], "объект": name,
                    "значение": value, "note": note})

    add("non_manifold", c["non_manifold_рёбра"])
    add("boundary", c["граничные_рёбра"],
        f"открытых оболочек {c['открытые_оболочки']}" if c["граничные_рёбра"] else "")
    add("winding", c["несогласованный_обход"])
    add("degenerate_area", c["вырожденные_по_площади"])
    add("degenerate_index", c["вырожденные_по_индексам"])
    add("duplicate_faces", c["повторяющиеся_грани"])
    add("loose", c["вершины_сироты"])
    # в glTF вершины законно разводятся по швам — это не дефект, поэтому «инфо»
    add("doubles", rep["слито_вершин"],
        "в glTF это развод по нормалям/UV" if fmt.startswith("GLB") else "настоящие дубли")
    if q["иглы"]:
        out.append({"код": "slivers", "уровень": "инфо", "объект": name,
                    "значение": q["иглы"],
                    "note": f"мин. угол {q['мин_угол']:.2f}°, площадь игл "
                            f"{q['иглы_площадь_%']:.1f}%, из них на плавном "
                            f"изгибе {q['иглы_на_изгибе_площадь_%']:.1f}%"})
    if q["вытянутые_%"] > 2.0:
        add("stretched", q["вытянутые"], f"{q['вытянутые_%']:.1f}% граней, "
                                         f"{q['вытянутые_площадь_%']:.1f}% площади")
    # разброс в тысячу раз — это уже «два кольца почти в одной точке»,
    # а не просто длинная деталь
    if rep["рёбра"]["разброс"] > 1000 and rep["треугольников"] > 500:
        add("density", 1, f"×{rep['рёбра']['разброс']:.0f} "
                          f"({rep['рёбра']['мин']:.3g} … {rep['рёбра']['макс']:.3g})")
    neg = [sh for sh in rep["оболочки_детали"] if sh["closed"] and sh["volume"] < 0]
    add("inverted", len(neg))
    nr = rep.get("нормали") or {}
    if nr.get("есть") and nr.get("доля_перевёрнутых_%", 0) > 10:
        add("normals_inverted", 1, f"{nr['доля_перевёрнутых_%']:.1f}% граней")
    elif nr.get("есть") and nr.get("доля_расхождений_%", 0) > 20:
        add("normals_flat", 1, f"{nr['доля_расхождений_%']:.1f}% граней")
    if c["оболочки"] > 1:
        add("shells", c["оболочки"])
    return out


# --------------------------------------------------------------------------- #
#  Отчёт
# --------------------------------------------------------------------------- #

def run(path: Path, tol: float, min_angle: float, max_aspect: float) -> dict:
    if path.suffix.lower() == ".glb":
        meshes, info = read_glb_meshes(path)
    elif path.suffix.lower() == ".obj":
        meshes, info = read_obj_meshes(path)
    else:
        raise ParseError("поддерживаются .glb и .obj")
    objects = []
    problems = []
    skipped = []
    for m in meshes:
        if "skipped" in m:
            skipped.append({"имя": m["name"], "причина": m["skipped"]})
            continue
        if not m["tris"]:
            continue
        rep = analyse(m["verts"], m["tris"], tol, min_angle, max_aspect)
        rep["имя"] = m["name"]
        rep["нормали"] = normal_health(m["verts"], m.get("normals"), m["tris"])
        objects.append(rep)
        problems.extend(verdicts(rep, m["name"], min_angle, info["формат"]))

    # сводка по кодам: сколько всего и у каких объектов
    grouped: dict[str, dict] = {}
    for p in problems:
        g = grouped.setdefault(p["код"], {"код": p["код"], "уровень": p["уровень"],
                                          "значение": 0, "объекты": []})
        g["значение"] += p["значение"]
        g["объекты"].append(p)
    order = {"ошибка": 0, "предупреждение": 1, "инфо": 2}
    codes = sorted(grouped.values(),
                   key=lambda g: (order[g["уровень"]], -len(g["объекты"])))
    return {
        "файл": str(path),
        "информация": info,
        "параметры": {"сварка": tol, "порог_угла": min_angle, "порог_сторон": max_aspect},
        "сводка": {
            "объектов": len(objects),
            "треугольников": sum(o["треугольников"] for o in objects),
            "вершин": sum(o["вершин"] for o in objects),
            "пропущено": skipped,
            "ошибок": sum(1 for p in problems if p["уровень"] == "ошибка"),
            "предупреждений": sum(1 for p in problems if p["уровень"] == "предупреждение"),
        },
        "коды": codes,
        "объекты": objects,
    }


ICON = {"ошибка": "✗", "предупреждение": "!", "инфо": "·"}


def render(rep: dict, top: int) -> str:
    inf = rep["информация"]
    s = rep["сводка"]
    head = (f"Формат: {inf['формат']}"
            + (f", генератор: {inf['генератор']}" if inf.get("генератор") else "")
            + (f", мешей {inf['мешей']}" if inf.get("мешей") is not None else "")
            + (f", узлов {inf['узлов']}" if inf.get("узлов") else ""))
    lines = [f"Топология: {rep['файл']}", head,
             f"Объектов: {s['объектов']}, вершин: {s['вершин']:,}, "
             f"треугольников: {s['треугольников']:,}".replace(",", " "),
             f"Ошибок: {s['ошибок']}, предупреждений: {s['предупреждений']}", ""]
    if s["пропущено"]:
        lines.append("Пропущено: " + ", ".join(f"{p['имя']} ({p['причина']})"
                                               for p in s["пропущено"]) + "\n")
    if not rep["коды"]:
        lines.append("Проблем не найдено: сетка замкнута, согласована, "
                     "без мусора и грубых игл.\n")
    else:
        lines.append("ПРОБЛЕМЫ")
        for g in rep["коды"]:
            level, title, unit, why = CODES[g["код"]]
            n = g["значение"]
            value = f"{n:.0f}" if float(n).is_integer() else f"{n:.2f}"
            head_line = f"  {ICON[level]} {title}: {value} {unit}, объектов {len(g['объекты'])}"
            if g["код"] == "density":
                head_line = f"  {ICON[level]} {title}: объектов {len(g['объекты'])}"
            lines.append(head_line)
            lines.append(f"      {why}")
            detail = []
            for p in g["объекты"][:6]:
                detail.append(p["объект"] + (f" ({p['note']})" if p["note"] else ""))
            more = len(g["объекты"]) - 6
            lines.append("      " + "; ".join(detail) + (f"; ещё {more}" if more > 0 else ""))
        lines.append("")
    bad = sorted(rep["объекты"],
                 key=lambda o: (-o["проверки"]["non_manifold_рёбра"],
                                -o["проверки"]["граничные_рёбра"],
                                -o["проверки"]["вырожденные_по_индексам"],
                                -o["проверки"]["вырожденные_по_площади"],
                                -o["качество"]["иглы"],
                                -o["треугольников"]))
    lines.append(f"ХУДШИЕ ОБЪЕКТЫ (первые {min(top, len(bad))} из {len(bad)})")
    lines.append("  объект                          |  трис  | NM | граница | иглы %  |"
                 " игл на изгибе % | мин.угол | оболоч.")
    for o in bad[:top]:
        c, q = o["проверки"], o["качество"]
        lines.append(f"  {o['имя'][:31]:31s} | {o['треугольников']:6d} | "
                     f"{c['non_manifold_рёбра']:2d} | {c['граничные_рёбра']:7d} | "
                     f"{q['иглы_%']:7.2f} | {q['иглы_на_изгибе_площадь_%']:10.2f} | "
                     f"{q['мин_угол']:9.2f} | {c['оболочки']:7d}")
    lines.append("")
    tot = max(1, s["треугольников"])
    total = {"иглы": sum(o["качество"]["иглы"] for o in rep["объекты"]),
             "NM": sum(o["проверки"]["non_manifold_рёбра"] for o in rep["объекты"]),
             "граница": sum(o["проверки"]["граничные_рёбра"] for o in rep["объекты"]),
             "дубли": sum(o["слито_вершин"] for o in rep["объекты"]),
             "V": sum(o["вершин"] for o in rep["объекты"]),
             "T": s["треугольников"]}
    closed = [sh for o in rep["объекты"] for sh in o["оболочки_детали"] if sh["closed"]]
    opened = [sh for o in rep["объекты"] for sh in o["оболочки_детали"] if not sh["closed"]]
    lines.append("ИТОГО ПО ФАЙЛУ")
    lines.append(f"  V={total['V']}  T={total['T']}  оболочек={len(closed) + len(opened)}")
    lines.append(f"  non-manifold рёбер={total['NM']}  граничных рёбер={total['граница']}  "
                 f"слитых совпадений={total['дубли']}")
    lines.append(f"  игл={total['иглы']} ({100.0 * total['иглы'] / tot:.3f}% треугольников)")
    if closed:
        g = Counter(sh["genus"] for sh in closed)
        lines.append(f"  замкнутых оболочек: {len(closed)} "
                     f"(род: {', '.join(f'{v} шт. с родом {k}' for k, v in sorted(g.items()))})")
    if opened:
        lines.append(f"  открытых оболочек: {len(opened)} — если деталь должна быть телом, "
                     "это дырки")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Аудит топологии GLB/OBJ: дырки, non-manifold, нормали, "
                    "вырожденные грани, дубли вершин, иглы, плотность.")
    ap.add_argument("file", type=Path, help="файл .glb или .obj")
    ap.add_argument("--weld", type=float, default=1e-4,
                    help="допуск сварки вершин в единицах модели (по умолчанию 1e-4)")
    ap.add_argument("--min-angle", type=float, default=3.0,
                    help="порог «иглы» в градусах (по умолчанию 3)")
    ap.add_argument("--max-aspect", type=float, default=10.0,
                    help="порог отношения сторон для «вытянутых» (по умолчанию 10)")
    ap.add_argument("--top", type=int, default=10, help="сколько объектов показать")
    ap.add_argument("--json", type=Path, help="записать полный отчёт в JSON")
    ap.add_argument("--quiet", action="store_true", help="не печатать отчёт")
    args = ap.parse_args(argv)

    try:
        rep = run(args.file, args.weld, args.min_angle, args.max_aspect)
    except (ParseError, OSError, KeyError, struct.error, ValueError) as exc:
        print(f"Не удалось прочитать {args.file}: {exc}", file=sys.stderr)
        return 2
    if not args.quiet:
        print(render(rep, args.top))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        if not args.quiet:
            print(f"\nJSON: {args.json}")
    return 1 if rep["сводка"]["ошибок"] else 0


if __name__ == "__main__":
    sys.exit(main())
