"""Оригинальный параметрический скелет: 206 костей без импортируемых сеток.

Все координаты ниже — анатомические проектные параметры автора кода, а не
извлечённые точки чужой модели.  Канон Forma: право +X, перёд −Y, верх +Z.
Единица — миллиметр; канонический рост 1750 мм.  Поверхности строятся здесь из
кольцевых сечений, изогнутых пластин и SDF-оболочек, затем проверяются Manifold.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache, reduce
import math

import manifold3d as mf
import numpy as np

from .geometry import manifold_from_arrays, solid_parts
from .ops_sdf import finalize_sdf, surface_from_field

CANONICAL_HEIGHT = 1750.0


@dataclass
class Bone:
    name: str
    title: str
    division: str             # axial / appendicular
    region: str
    side: str                 # right / left / midline
    solid: mf.Manifold


def _mesh(vertices, faces, what: str) -> mf.Manifold:
    v = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    f = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if not len(v) or not len(f):
        raise ValueError(f"{what}: пустая исходная сетка")
    p = v[f]
    signed = float(np.einsum("ij,ij->", p[:, 0],
                             np.cross(p[:, 1], p[:, 2])) / 6.0)
    if signed < 0:
        f = f[:, ::-1]
    return manifold_from_arrays(v, f, what=what)


def _catmull(points, radii=None, steps=4, closed=False):
    p = np.asarray(points, dtype=np.float64)
    n = len(p)
    if radii is None:
        r = np.ones((n, 2), dtype=np.float64)
    else:
        r = np.asarray(radii, dtype=np.float64)
        if r.ndim == 0:
            r = np.full((n, 2), float(r))
        elif r.ndim == 1:
            r = np.column_stack([r, r]) if len(r) == n else np.tile(r, (n, 1))
    out_p, out_r = [], []
    segments = n if closed else n - 1
    for i in range(segments):
        if closed:
            p0, p1, p2, p3 = p[(i-1) % n], p[i], p[(i+1) % n], p[(i+2) % n]
            r0, r1, r2, r3 = r[(i-1) % n], r[i], r[(i+1) % n], r[(i+2) % n]
        else:
            p0, p1, p2, p3 = p[max(0, i-1)], p[i], p[i+1], p[min(n-1, i+2)]
            r0, r1, r2, r3 = r[max(0, i-1)], r[i], r[i+1], r[min(n-1, i+2)]
        for j in range(steps):
            t = j / steps
            t2, t3 = t*t, t*t*t
            q = 0.5 * ((2*p1) + (-p0+p2)*t +
                       (2*p0-5*p1+4*p2-p3)*t2 +
                       (-p0+3*p1-3*p2+p3)*t3)
            qr = 0.5 * ((2*r1) + (-r0+r2)*t +
                        (2*r0-5*r1+4*r2-r3)*t2 +
                        (-r0+3*r1-3*r2+r3)*t3)
            out_p.append(q)
            out_r.append(np.maximum(qr, 0.15))
    if not closed:
        out_p.append(p[-1])
        out_r.append(np.maximum(r[-1], 0.15))
    return np.asarray(out_p), np.asarray(out_r)


def _tube(points, radii, what: str, segments=12, steps=4, closed=False,
          lobes=0.0) -> mf.Manifold:
    """Замкнутая трубка переменного эллиптического сечения по 3D-пути."""
    centers, rr = _catmull(points, radii, steps=steps, closed=closed)
    n = len(centers)
    rings = []
    previous_u = None
    for i, c in enumerate(centers):
        if closed:
            tangent = centers[(i+1) % n] - centers[(i-1) % n]
        elif i == 0:
            tangent = centers[1] - c
        elif i == n-1:
            tangent = c - centers[i-1]
        else:
            tangent = centers[i+1] - centers[i-1]
        tangent /= max(np.linalg.norm(tangent), 1e-12)
        if previous_u is None:
            ref = np.array([0.0, 1.0, 0.0])
            if abs(float(np.dot(tangent, ref))) > 0.88:
                ref = np.array([1.0, 0.0, 0.0])
            u = np.cross(tangent, ref)
        else:
            u = previous_u - tangent * float(np.dot(previous_u, tangent))
        if np.linalg.norm(u) < 1e-8:
            u = np.cross(tangent, [1.0, 0.0, 0.0])
        u /= max(np.linalg.norm(u), 1e-12)
        v = np.cross(tangent, u)
        previous_u = u
        ring = []
        for j in range(segments):
            theta = 2 * math.pi * j / segments
            organic = 1.0 + lobes * math.cos(3 * theta)
            ring.append(c + u * (rr[i, 0] * math.cos(theta) * organic) +
                        v * (rr[i, 1] * math.sin(theta) * organic))
        rings.append(ring)
    verts = np.asarray(rings, dtype=np.float64).reshape(-1, 3)
    faces = []
    links = n if closed else n-1
    for i in range(links):
        ni = (i+1) % n
        for j in range(segments):
            nj = (j+1) % segments
            a, b = i*segments+j, ni*segments+j
            c, d = ni*segments+nj, i*segments+nj
            faces.extend([(a, c, b), (a, d, c)])
    if not closed:
        start = len(verts)
        end = start + 1
        verts = np.vstack([verts, centers[0], centers[-1]])
        for j in range(segments):
            nj = (j+1) % segments
            faces.append((start, nj, j))
            a, b = (n-1)*segments+j, (n-1)*segments+nj
            faces.append((end, a, b))
    return _mesh(verts, faces, what)


def _ellipsoid(center, radii, what: str, segments=18, rings=12,
               organic=0.0) -> mf.Manifold:
    """UV-эллипсоид с опциональным собственным низкочастотным рельефом."""
    center = np.asarray(center, dtype=np.float64)
    rx, ry, rz = map(float, radii)
    verts = [center + [0, 0, rz]]
    for i in range(1, rings):
        theta = math.pi * i / rings
        for j in range(segments):
            phi = 2 * math.pi * j / segments
            unit = np.array([math.sin(theta)*math.cos(phi),
                             math.sin(theta)*math.sin(phi), math.cos(theta)])
            factor = 1.0 + organic * (0.55*math.sin(3*phi)*math.sin(theta)**2 +
                                      0.45*math.cos(4*theta+phi))
            verts.append(center + unit * np.array([rx, ry, rz]) * factor)
    bottom = len(verts)
    verts.append(center - [0, 0, rz])
    faces = []
    for j in range(segments):
        nj = (j+1) % segments
        faces.append((0, 1+j, 1+nj))
    for i in range(rings-2):
        row, nxt = 1+i*segments, 1+(i+1)*segments
        for j in range(segments):
            nj = (j+1) % segments
            faces.extend([(row+j, nxt+j, nxt+nj), (row+j, nxt+nj, row+nj)])
    last = 1+(rings-2)*segments
    for j in range(segments):
        nj = (j+1) % segments
        faces.append((bottom, last+nj, last+j))
    return _mesh(verts, faces, what)


def _plate(boundary, thickness: float, bulge: float, what: str,
           normal=None, outline_steps=3) -> mf.Manifold:
    """Двусторонняя замкнутая пластина с куполом и тонкой кромкой."""
    boundary, _ = _catmull(boundary, steps=max(6, outline_steps), closed=True)
    center = np.mean(boundary, axis=0)
    if normal is None:
        normal = np.zeros(3)
        for i in range(len(boundary)):
            a, b = boundary[i], boundary[(i+1) % len(boundary)]
            normal += [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2],
                       a[0]*b[1]-a[1]*b[0]]
    normal = np.asarray(normal, dtype=np.float64)
    normal /= max(np.linalg.norm(normal), 1e-12)
    scales = (0.12,0.25,0.38,0.52,0.66,0.78,0.89,1.0)
    all_verts, side_indices = [], []
    for sign in (1.0, -1.0):
        side = [len(all_verts)]
        all_verts.append(center + normal*(bulge + sign*thickness*0.5))
        for scale in scales:
            ids = []
            edge_t = thickness*(0.42 + 0.58*(1-scale))
            for p in boundary:
                q = center + scale*(p-center) + normal*(bulge*(1-scale*scale) + sign*edge_t*0.5)
                ids.append(len(all_verts))
                all_verts.append(q)
            side.append(ids)
        side_indices.append(side)
    n = len(boundary)
    faces = []
    for side_no, side in enumerate(side_indices):
        reverse = side_no == 1
        for j in range(n):
            nj = (j+1) % n
            tri = (side[0], side[1][j], side[1][nj])
            faces.append(tri[::-1] if reverse else tri)
        for k in range(1, len(scales)):
            inner, outer = side[k], side[k+1]
            for j in range(n):
                nj = (j+1) % n
                tris = [(inner[j], outer[j], outer[nj]),
                        (inner[j], outer[nj], inner[nj])]
                faces.extend(t[::-1] if reverse else t for t in tris)
    front, back = side_indices[0][-1], side_indices[1][-1]
    for j in range(n):
        nj = (j+1) % n
        faces.extend([(front[j], back[j], back[nj]),
                      (front[j], back[nj], front[nj])])
    return _mesh(all_verts, faces, what)


def _fuse(solids, what: str) -> mf.Manifold:
    items = [s for s in solids if s is not None and not s.is_empty()]
    if not items:
        raise ValueError(f"{what}: нет геометрии")
    return reduce(lambda a, b: a+b, items)


def _largest(solid: mf.Manifold) -> mf.Manifold:
    """Убирает микроскопический обрезок контактного шва, не основную анатомическую часть."""
    pieces = [p for p in solid.decompose() if p.volume() > 1e-6]
    return max(pieces, key=lambda p: p.volume()) if pieces else solid


def _mirror(solid: mf.Manifold) -> mf.Manifold:
    return solid.mirror((1, 0, 0))


def _ellipsoid_distance(X, Y, Z, center, radii):
    cx, cy, cz = center
    rx, ry, rz = radii
    q = np.sqrt(((X-cx)/rx)**2 + ((Y-cy)/ry)**2 + ((Z-cz)/rz)**2)
    return (q-1.0) * min(rx, ry, rz)


def _capsule_distance(X,Y,Z,a,b,r):
    ax,ay,az=a; bx,by,bz=b
    ex,ey,ez=bx-ax,by-ay,bz-az
    px,py,pz=X-ax,Y-ay,Z-az
    denom=ex*ex+ey*ey+ez*ez
    t=np.clip((px*ex+py*ey+pz*ez)/max(denom,1e-12),0.0,1.0)
    dx,dy,dz=px-ex*t,py-ey*t,pz-ez*t
    return np.sqrt(dx*dx+dy*dy+dz*dz)-r


def _smooth_min(a,b,k=2.0):
    if k<=0:
        return np.minimum(a,b)
    h=np.clip(0.5+0.5*(b-a)/k,0.0,1.0)
    return b+(a-b)*h-k*h*(1.0-h)


def _hip_wing_sdf():
    """Веерное подвздошное крыло с ямкой и гребнем — одна гладкая SDF-поверхность."""
    def field(X,Y,Z):
        wing_rx=30.0+0.25*(Z-900.0)
        wing_cx=95.0+0.10*(Z-900.0)
        q=np.sqrt(((X-wing_cx)/wing_rx)**2+((Y-35.0)/9.0)**2+((Z-950.0)/50.0)**2)
        wing=(q-1.0)*8.0
        fossa=_ellipsoid_distance(X,Y,Z,(100,20,950),(42,9,38))
        value=np.maximum(wing,-fossa)
        crest=[(55,32,970),(75,32,987),(110,32,990),(140,32,970)]
        crest,_=_catmull(crest,steps=3,closed=False)
        for a,b in zip(crest,crest[1:]):
            value=_smooth_min(value,_capsule_distance(X,Y,Z,a,b,4.5),2.5)
        return value
    bounds=[35,10,890,170,65,1010]
    verts,faces,step=surface_from_field(field,bounds,0.9)
    if verts is None:
        raise ValueError("подвздошное крыло: пустое SDF-поле")
    return _largest(finalize_sdf(verts,faces,step,what="подвздошное крыло SDF"))


def _cranial_patch(name, region, zmin, bounds, resolution=1.8):
    def field(X, Y, Z):
        outer = _ellipsoid_distance(X, Y, Z, (0, 5, 1645), (70, 80, 83))
        inner = _ellipsoid_distance(X, Y, Z, (0, 5, 1645), (65, 75, 78))
        value = np.maximum(np.maximum(outer, -inner), zmin-Z)
        for expression in region:
            value = np.maximum(value, expression(X, Y, Z))
        return value
    verts, faces, step = surface_from_field(field, bounds, resolution)
    if verts is None:
        raise ValueError(f"{name}: пустая SDF-пластина")
    return finalize_sdf(verts, faces, step, what=name)


def _add(bones, name, title, division, region, side, solid):
    if solid.is_empty() or solid.volume() <= 0:
        raise ValueError(f"{name}: пустая кость")
    bones.append(Bone(name, title, division, region, side, solid))


def _skull(bones):
    # Черепная крышка: толщина 5 мм, сагиттальный/венечный/ламбдовидный швы — зазоры.
    right_regions = [
        ("frontal", "Лобная кость", "midline",
         [lambda X,Y,Z: Y+10.5], 1578, [-75,-90,1575,75,-9,1750]),
        ("parietal", "Теменная кость", "right",
         [lambda X,Y,Z: 0.5-X, lambda X,Y,Z: -9.0-Y, lambda X,Y,Z: Y-44.0],
         1618, [0,-12,1615,75,46,1750]),
        ("occipital", "Затылочная кость", "midline",
         [lambda X,Y,Z: 45.5-Y], 1558, [-75,44,1555,75,90,1750]),
    ]
    cranial = {}
    for name, title, side, region, zmin, bounds in right_regions:
        solid = _cranial_patch(name, region, zmin, bounds)
        cranial[name] = solid
        _add(bones, name, title, "axial", "skull", side, solid)
        if name == "parietal":
            _add(bones, "parietal_l", "Теменная кость левая", "axial", "skull", "left", _mirror(solid))
            bones[-2].name = "parietal_r"
            bones[-2].title = "Теменная кость правая"

    # Височные кости: чешуя, сосцевидный отросток и настоящий слуховой канал.
    temporal_r = _fuse([
        _ellipsoid((59, 14, 1608), (17, 29, 31), "височная чешуя", organic=0.05),
        _ellipsoid((57, 31, 1580), (10, 12, 16), "сосцевидный отросток", organic=0.05),
    ], "височная кость")
    canal = _tube([(43, 4, 1606), (80, 4, 1606)], [4.2, 4.2], "слуховой канал", steps=1)
    middle_ear = _ellipsoid((64, 10, 1606), (11, 14, 13), "полость среднего уха")
    mandibular_fossa = _ellipsoid((55, 1, 1590), (10, 12, 8), "нижнечелюстная впадина")
    cranial_cavity = _ellipsoid((0, 5, 1645), (65, 75, 78), "внутренняя полость черепа",
                                segments=24, rings=16)
    temporal_r = temporal_r - cranial_cavity - canal - middle_ear - mandibular_fossa
    _add(bones, "temporal_r", "Височная кость правая", "axial", "skull", "right", temporal_r)
    _add(bones, "temporal_l", "Височная кость левая", "axial", "skull", "left", _mirror(temporal_r))

    sphenoid = _fuse([
        _ellipsoid((0, 5, 1593), (18, 22, 15), "тело клиновидной кости", organic=0.04),
        _ellipsoid((27, 0, 1600), (25, 13, 8), "большое крыло", organic=0.04),
        _ellipsoid((-27, 0, 1600), (25, 13, 8), "большое крыло", organic=0.04),
        _tube([(-10, 4, 1585), (-14, 2, 1568)], [5, 3], "крыловидный отросток", steps=2),
        _tube([(10, 4, 1585), (14, 2, 1568)], [5, 3], "крыловидный отросток", steps=2),
    ], "клиновидная кость")
    # Базальный шов задаётся явно: клиновидная кость обрезает контактную зону.
    for bone in bones:
        if bone.name in ("temporal_r", "temporal_l"):
            bone.solid = bone.solid - sphenoid
    _add(bones, "sphenoid", "Клиновидная кость", "axial", "skull", "midline", sphenoid)
    frontal_solid = next(b.solid for b in bones if b.name == "frontal")
    ethmoid = _largest(_fuse([
        _ellipsoid((0, -43, 1610), (10, 14, 19), "решетчатый лабиринт", organic=0.06),
        _ellipsoid((0, -48, 1601), (2.2, 11, 11), "перпендикулярная пластинка"),
    ], "решетчатая кость") - frontal_solid)
    _add(bones, "ethmoid", "Решетчатая кость", "axial", "skull", "midline", ethmoid)

    # Лицевой скелет. Орбиты и носовая апертура вычитаются, а не нарисованы.
    maxilla_r = _fuse([
        _plate([(8,-68,1585),(18,-72,1594),(40,-57,1588),(43,-42,1568),
                (28,-45,1555),(10,-60,1558)],7.0,3.0,"тело верхней челюсти",
               normal=(0,-1,0),outline_steps=3),
        _tube([(18,-52,1574), (15,-63,1592), (14,-68,1608)], [(7,6),(5,4),(4,3)],
              "лобный отросток верхней челюсти", segments=12, steps=4),
        _tube([(30,-43,1575), (43,-39,1585)], [(8,7),(6,5)],
              "скуловой отросток верхней челюсти", segments=12, steps=3),
        _tube([(24,-48,1562),(24,-52,1548)],[(7,6),(6,5)],
              "альвеолярное тело верхней челюсти",segments=12,steps=3),
        _tube([(0,-73,1546), (18,-67,1543), (34,-52,1545), (36,-31,1551)],
              [(3,4), (5,6), (5,6), (4,5)], "альвеолярный отросток", steps=3),
    ], "верхняя челюсть").trim_by_plane((1,0,0),1.0)
    zygoma_r = _fuse([
        _ellipsoid((52, -48, 1598), (13, 11, 17), "скуловое тело", organic=0.05),
        _tube([(52,-42,1601), (61,-27,1600), (60,-18,1602)], [4.5,3.8,4.0],
              "скуловая дуга", segments=10, steps=4),
    ], "скуловая кость")
    nasal_r = _ellipsoid((6.5, -79, 1625), (5.2, 2.5, 9), "носовая кость", organic=0.03)
    lacrimal_r = _ellipsoid((16, -48, 1608), (2.5, 5.0, 9), "слезная кость")
    concha_r = _tube([(10,-42,1588), (14,-51,1580), (11,-59,1573), (7,-54,1570)],
                     [2.0,2.8,2.5,1.5], "нижняя носовая раковина", segments=10, steps=3)
    palatine_r = _fuse([
        _ellipsoid((12, -12, 1548), (11, 14, 3.2), "горизонтальная пластинка"),
        _ellipsoid((20, -12, 1562), (3.2, 11, 15), "вертикальная пластинка"),
    ], "небная кость")
    paired = [
        ("maxilla", "Верхняя челюсть", maxilla_r),
        ("zygomatic", "Скуловая кость", zygoma_r),
        ("nasal", "Носовая кость", nasal_r),
        ("lacrimal", "Слезная кость", lacrimal_r),
        ("inferior_nasal_concha", "Нижняя носовая раковина", concha_r),
        ("palatine", "Нёбная кость", palatine_r),
    ]
    # Вычитание двух орбит из костей, образующих их края.
    cutters = [_ellipsoid((s*32, -64, 1610), (22, 27, 21), "орбитальный резак", segments=24, rings=16)
               for s in (-1, 1)]
    for name, title, solid in paired:
        if name in ("maxilla", "zygomatic"):
            solid = solid - frontal_solid
        if name == "inferior_nasal_concha":
            solid = _largest(solid - maxilla_r - frontal_solid)
        if name == "lacrimal":
            solid = solid - frontal_solid
        if name in ("maxilla", "zygomatic"):
            for cutter in cutters:
                solid = solid - cutter
        if name == "maxilla":
            solid = _fuse([solid,
                _tube([(15,-66,1570),(15,-66,1595)],[3.5,3.5],
                      "медиальный край орбиты",segments=10,steps=3),
                _tube([(34,-52,1562),(34,-52,1588)],[4.0,4.0],
                      "латеральный край орбиты",segments=10,steps=3)],
                "верхняя челюсть с краями орбиты")
        _add(bones, name+"_r", title+" правая", "axial", "skull", "right", solid)
        _add(bones, name+"_l", title+" левая", "axial", "skull", "left", _mirror(solid))
    # Орбиты проходят и через лобную кость; меняем только что созданный объект.
    for bone in bones:
        if bone.name == "frontal":
            for cutter in cutters:
                bone.solid = bone.solid - cutter
    nasal_aperture = _ellipsoid((0, -69, 1579), (12, 24, 18), "носовая апертура", segments=22, rings=14)
    for bone in bones:
        if bone.name in ("frontal", "maxilla_r", "maxilla_l"):
            bone.solid = bone.solid - nasal_aperture

    vomer = _largest(_ellipsoid((0, -35, 1574), (1.8, 14, 16), "сошник") - frontal_solid)
    _add(bones, "vomer", "Сошник", "axial", "skull", "midline", vomer)
    mandible_path = [
        (-55,1,1590), (-53,-4,1555), (-47,-20,1534), (-34,-47,1520),
        (-17,-66,1514), (0,-73,1512), (17,-66,1514), (34,-47,1520),
        (47,-20,1534), (53,-4,1555), (55,1,1590),
    ]
    mandible = _tube(mandible_path,
                     [(6,7),(7,8),(8,9),(8,9),(8,8),(9,8),(8,8),(8,9),(8,9),(7,8),(6,7)],
                     "нижняя челюсть", segments=14, steps=4)
    alveolar_path = [(36,-31,1538),(34,-52,1533),(18,-67,1532),(0,-73,1534),
                     (-18,-67,1532),(-34,-52,1533),(-36,-31,1538)]
    mandibular_body = _tube([(x,y,z-11) for x,y,z in alveolar_path],
                            [(7,9)]*7,"тело нижней челюсти",segments=14,steps=4)
    mandibular_alveolar = _tube(alveolar_path,[(4.2,4.2)]*7,
                                "альвеолярный отросток нижней челюсти",segments=12,steps=4)
    ramus_r = _plate([(52,0,1584),(59,1,1570),(54,-7,1538),(45,-20,1532)],
                     5.0,2.0,"ветвь нижней челюсти",normal=(1,0,0),outline_steps=3)
    mandible = _fuse([mandible, mandibular_body, mandibular_alveolar, ramus_r, _mirror(ramus_r),
                      _ellipsoid((0,-70,1523),(18,7,13),"подбородочный выступ",organic=0.03),
                      _ellipsoid((-55,1,1590),(8,10,6),"мыщелок"),
                      _ellipsoid((55,1,1590),(8,10,6),"мыщелок")], "нижняя челюсть")
    frontal_final = next(b.solid for b in bones if b.name == "frontal")
    for bone in bones:
        if bone.name in ("temporal_r", "temporal_l"):
            parietal = next(b.solid for b in bones if b.name == "parietal_"+bone.name[-1])
            bone.solid = bone.solid - frontal_final - mandible - parietal
    _add(bones, "mandible", "Нижняя челюсть", "axial", "skull", "midline", mandible)

    # Слуховые косточки — самостоятельные миниатюрные тела, не текстурные метки.
    for side, sign in (("r",1),("l",-1)):
        def at(x,y,z): return (sign*x,y,z-10)
        malleus = _fuse([
            _ellipsoid(at(62,7,1618),(2.2,2.5,3.5),"головка молоточка",segments=12,rings=8),
            _tube([at(62,7,1616),at(64,5,1609)],[1.5,1.0],"рукоятка молоточка",segments=8,steps=2),
        ], "молоточек")
        incus = _fuse([
            _ellipsoid(at(64,12,1619),(2.8,2.0,2.2),"тело наковальни",segments=12,rings=8),
            _tube([at(64,12,1618),at(66,14,1612)],[1.3,0.9],"ножка наковальни",segments=8,steps=2),
        ], "наковальня")
        stapes = _tube([at(66,8,1610),at(69,8,1612),at(69,8,1615),at(66,8,1614)],
                       [0.8,0.8,0.8,0.8],"стремя",segments=8,steps=2,closed=True)
        for nm,title,solid in (("malleus","Молоточек",malleus),("incus","Наковальня",incus),("stapes","Стремя",stapes)):
            _add(bones,f"{nm}_{side}",f"{title} {'правый' if side=='r' else 'левый'}","axial","ear_ossicles",side,solid)

    hyoid = _tube([(-18,-12,1503),(-22,-24,1498),(-12,-35,1496),(0,-39,1496),
                   (12,-35,1496),(22,-24,1498),(18,-12,1503)],
                  [2.0,2.4,2.7,3.0,2.7,2.4,2.0], "подъязычная кость", segments=10, steps=4)
    _add(bones,"hyoid","Подъязычная кость","axial","hyoid","midline",hyoid)


def _vertebra(name, title, z, kind, index):
    dims = {"cervical": (17,14,8), "thoracic": (21,17,10), "lumbar": (27,21,12)}[kind]
    rx, ry, rz = dims
    y = 30 if kind == "cervical" else 35
    if name == "c1":
        ring = _tube([(0,17,z),(17,25,z),(24,43,z),(14,58,z),(0,62,z),
                      (-14,58,z),(-24,43,z),(-17,25,z)],
                     [(5,6)]*8, "атлант", segments=12, steps=3, closed=True)
        return _fuse([ring,
                      _ellipsoid((19,39,z),(8,13,7),"латеральная масса"),
                      _ellipsoid((-19,39,z),(8,13,7),"латеральная масса")], "атлант")
    body = _ellipsoid((0,y,z),(rx,ry,rz),name+" тело",segments=18,rings=10,organic=0.025)
    arch = _tube([(-rx*0.75,y+7,z),(-rx-3,y+23,z),(-rx*0.55,y+38,z),
                  (0,y+43,z),(rx*0.55,y+38,z),(rx+3,y+23,z),(rx*0.75,y+7,z)],
                 [5.0]*7, name+" дуга",segments=10,steps=3)
    transverse = [
        _tube([(sign*(rx-2),y+25,z),(sign*(rx+17),y+28,z-1)],
              [5.0,3.0],name+" поперечный отросток",segments=10,steps=3)
        for sign in (-1,1)
    ]
    drop = {"cervical":4,"thoracic":15,"lumbar":3}[kind]
    length = {"cervical":22,"thoracic":30,"lumbar":25}[kind]
    spinous = _tube([(0,y+39,z),(0,y+39+length,z-drop)],
                    [5.0,2.2 if kind != "lumbar" else 4.0],name+" остистый отросток",
                    segments=10,steps=3)
    pieces = [body,arch,spinous]+transverse
    if name == "c2":
        pieces.append(_tube([(0,y, z+4),(0,y,z+24)],[7.0,5.0],"зубовидный отросток",segments=12,steps=3))
    return _fuse(pieces,name)


def _spine(bones):
    cervical_z = [1530,1508,1486,1464,1442,1420,1398]
    for i,z in enumerate(cervical_z,1):
        name=f"c{i}"
        _add(bones,name,f"Шейный позвонок C{i}","axial","spine","midline",
             _vertebra(name,f"C{i}",z,"cervical",i))
    for i in range(1,13):
        z=1374-(i-1)*24
        name=f"t{i}"
        _add(bones,name,f"Грудной позвонок T{i}","axial","spine","midline",
             _vertebra(name,f"T{i}",z,"thoracic",i))
    for i,z in enumerate([1065,1030,995,960,925],1):
        name=f"l{i}"
        _add(bones,name,f"Поясничный позвонок L{i}","axial","spine","midline",
             _vertebra(name,f"L{i}",z,"lumbar",i))
    sacrum = _tube([(0,42,908),(0,49,877),(0,57,838),(0,65,795)],
                   [(47,17),(40,15),(28,12),(12,8)],"крестец",segments=20,steps=5)
    sacrum = _fuse([sacrum,
                    _ellipsoid((43,43,895),(24,18,18),"крестцовое крыло",organic=0.04),
                    _ellipsoid((-43,43,895),(24,18,18),"крестцовое крыло",organic=0.04)],"крестец")
    for z,x in ((885,25),(860,23),(835,19),(812,14)):
        for sign in (-1,1):
            hole=_tube([(sign*x,20,z),(sign*x,80,z)],[3.5,3.5],"крестцовое отверстие",segments=10,steps=1)
            sacrum=sacrum-hole
    _add(bones,"sacrum","Крестец","axial","spine","midline",sacrum)
    coccyx=_tube([(0,65,782),(0,69,765),(0,66,750)],[(9,7),(6,5),(2,2)],"копчик",segments=14,steps=4)
    _add(bones,"coccyx","Копчик","axial","spine","midline",coccyx)


def _thorax(bones):
    widths=[75,94,112,128,140,148,151,149,143,132,112,82]
    drops=[18,23,29,35,41,47,53,57,58,54,43,30]
    for i in range(1,13):
        z=1374-(i-1)*24
        w=widths[i-1]
        drop=drops[i-1]
        if i<=7:
            end=((23 if i <= 2 else 17),-91,z-drop)
            path=[(12,57,z+2),(45,63,z+4),(w*0.80,40,z-4),(w,0,z-drop*0.45),
                  (w*0.78,-55,z-drop*0.80),end]
        elif i<=10:
            end=(30+(i-8)*9,-68+(i-8)*8,z-drop)
            path=[(12,57,z+2),(45,63,z+4),(w*0.82,35,z-5),(w,0,z-drop*0.5),
                  (w*0.75,-42,z-drop*0.85),end]
        else:
            end=(w*0.83,-18,z-drop)
            path=[(12,57,z+2),(43,62,z+3),(w*0.78,35,z-5),end]
        rib=_tube(path,[(5.5,4.0)]+[(4.2,3.0)]*(len(path)-2)+[(2.2,2.0)],
                  f"ребро {i}",segments=10,steps=5)
        vertebra = next(b.solid for b in bones if b.name == f"t{i}")
        rib = rib - vertebra
        _add(bones,f"rib_{i}_r",f"Ребро {i} правое","axial","ribs","right",rib)
        _add(bones,f"rib_{i}_l",f"Ребро {i} левое","axial","ribs","left",_mirror(rib))
    manubrium=_ellipsoid((0,-93,1355),(19,5,27),"рукоятка грудины",organic=0.04)
    body=_tube([(0,-94,1328),(0,-96,1260),(0,-94,1182)],[(13,4),(12,4),(9,3.5)],
               "тело грудины",segments=14,steps=5)
    xiphoid=_ellipsoid((0,-93,1168),(6,3,14),"мечевидный отросток",organic=0.05)
    # Три взрослые костные части остаются раздельными внутри одной анатомической кости.
    sternum=_fuse([manubrium,body,xiphoid],"грудина")
    _add(bones,"sternum","Грудина","axial","sternum","midline",sternum)


def _small_bone(p0, p1, radius, what, segments=10):
    a, b = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
    points = [a, a*0.72+b*0.28, a*0.28+b*0.72, b]
    radii = [(radius*1.18,radius*1.05),(radius*0.82,radius*0.76),
             (radius*0.76,radius*0.82),(radius*1.08,radius)]
    return _tube(points,radii,what,segments=segments,steps=3)


def _shoulder_and_arm(bones):
    clavicle=_tube([(8,-82,1398),(42,-81,1408),(86,-64,1415),
                    (132,-38,1413),(174,-18,1412)],
                   [(6,5),(5.5,4.5),(5,4),(5.5,4.5),(7,5)],
                   "ключица",segments=14,steps=5)
    _add(bones,"clavicle_r","Ключица правая","appendicular","shoulder","right",clavicle)
    _add(bones,"clavicle_l","Ключица левая","appendicular","shoulder","left",_mirror(clavicle))
    scapula_plate=_plate([(55,75,1405),(96,82,1420),(164,55,1392),(158,64,1270),
                          (105,88,1228),(64,88,1285)],4.5,8.0,"лопатка",normal=(0,1,0))
    scapula=_fuse([scapula_plate,
                   _tube([(60,88,1360),(105,88,1370),(158,72,1382),(179,36,1407)],
                         [5,5,6,7],"акромион и ость лопатки",segments=12,steps=4),
                   _ellipsoid((171,39,1394),(10,12,17),"суставная впадина",organic=0.03)],
                  "лопатка")
    _add(bones,"scapula_r","Лопатка правая","appendicular","shoulder","right",scapula)
    _add(bones,"scapula_l","Лопатка левая","appendicular","shoulder","left",_mirror(scapula))

    humerus_shaft=_tube([(188,12,1380),(204,15,1312),(223,7,1225),
                         (239,-3,1152),(245,-5,1128)],
                        [(13,14),(10,10),(8.5,9),(11,10),(17,12)],
                        "плечевая кость",segments=16,steps=5,lobes=0.025)
    humerus=_fuse([humerus_shaft,
                   _ellipsoid((190,10,1397),(21,21,22),"головка плечевой кости",organic=0.025),
                   _ellipsoid((236,-6,1122),(11,12,11),"мыщелок плечевой кости"),
                   _ellipsoid((254,-6,1122),(10,11,10),"головка мыщелка")],"плечевая кость")
    _add(bones,"humerus_r","Плечевая кость правая","appendicular","upper_limb","right",humerus)
    _add(bones,"humerus_l","Плечевая кость левая","appendicular","upper_limb","left",_mirror(humerus))

    radius=_fuse([
        _tube([(257,-8,1110),(270,-10,1055),(287,-12,990),(300,-12,942)],
              [(8,8),(6.5,6),(7,6.5),(13,10)],"лучевая кость",segments=14,steps=5),
        _ellipsoid((257,-8,1110),(10,10,6),"головка лучевой кости")],"лучевая кость")
    ulna=_fuse([
        _tube([(231,3,1125),(239,4,1060),(257,3,995),(275,0,946)],
              [(10,9),(7,7),(5.5,5.5),(6.5,6)],"локтевая кость",segments=14,steps=5,lobes=0.035),
        _tube([(231,3,1125),(229,15,1140),(238,17,1147)],[(9,8),(8,7),(5,5)],
              "локтевой отросток",segments=12,steps=3)],"локтевая кость")
    elbow_clearance = _fuse([
        _ellipsoid((236,-6,1122),(12.5,13.5,12.5),"полость блока плечевой кости"),
        _ellipsoid((254,-6,1122),(11.5,12.5,11.5),"полость головки мыщелка")],
        "локтевой суставной зазор")
    radius = (radius - humerus) - elbow_clearance
    ulna = (ulna - humerus) - elbow_clearance
    for name,title,solid in (("radius","Лучевая кость",radius),("ulna","Локтевая кость",ulna)):
        _add(bones,name+"_r",title+" правая","appendicular","upper_limb","right",solid)
        _add(bones,name+"_l",title+" левая","appendicular","upper_limb","left",_mirror(solid))


def _hand_right():
    result=[]
    carpals=[
        ("scaphoid","Ладьевидная",(307,-10,924),(7.5,9,8.5)),
        ("lunate","Полулунная",(291,-8,924),(7.2,8.5,8)),
        ("triquetral","Трёхгранная",(275,-5,923),(7.0,8,8)),
        ("pisiform","Гороховидная",(275,-22,925),(5.0,4.8,5.0)),
        ("trapezium","Трапеция",(307,-11,904),(7.5,8.5,8)),
        ("trapezoid","Трапециевидная",(291,-8,903),(6.8,8,8)),
        ("capitate","Головчатая",(275,-5,902),(7.5,9,9)),
        ("hamate","Крючковидная",(259,-2,901),(7.2,9,8.5)),
    ]
    for name,title,center,radii in carpals:
        solid=_ellipsoid(center,radii,"запястье "+name,segments=14,rings=10,organic=0.10)
        if name=="hamate":
            hook=_tube([(258,-9,900),(257,-17,895),(261,-19,890)],[2.5,2.2,1.4],
                       "крючок крючковидной кости",segments=8,steps=3)
            solid=_fuse([solid,hook],name)
        result.append((name,title,"carpals",solid))
    metacarpals=[
        (1,(309,-12,892),(334,-18,854),5.0),
        (2,(295,-10,889),(298,-14,834),4.6),
        (3,(279,-6,889),(280,-8,827),4.7),
        (4,(263,-2,888),(262,-3,834),4.4),
        (5,(251,1,883),(245,2,841),4.2),
    ]
    for i,p0,p1,r in metacarpals:
        result.append((f"metacarpal_{i}",f"Пястная кость {i}","metacarpals",
                       _small_bone(p0,p1,r,f"пястная кость {i}",segments=12)))
    fingers={
        1:[((337,-19,844),(348,-22,818),4.6),((350,-23,811),(360,-25,791),4.0)],
        2:[((298,-14,824),(299,-15,790),4.2),((299,-15,783),(300,-16,758),3.6),
           ((300,-16,751),(300,-17,733),3.1)],
        3:[((280,-8,817),(280,-9,779),4.3),((280,-9,772),(280,-10,746),3.7),
           ((280,-10,739),(280,-11,721),3.1)],
        4:[((262,-3,824),(260,-4,789),4.0),((260,-4,782),(258,-5,758),3.4),
           ((258,-5,751),(257,-6,734),2.9)],
        5:[((245,2,831),(240,3,801),3.7),((240,3,794),(236,4,773),3.1),
           ((236,4,766),(233,4,749),2.7)],
    }
    ph_names={1:["proximal","distal"],2:["proximal","middle","distal"]}
    for digit,segments in fingers.items():
        for idx,(p0,p1,r) in enumerate(segments):
            phalange=ph_names[1 if digit==1 else 2][idx]
            title=f"{('Большой','Указательный','Средний','Безымянный','Мизинец')[digit-1]} палец: {phalange} фаланга"
            result.append((f"hand_phalanx_{digit}_{phalange}",title,"hand_phalanges",
                           _small_bone(p0,p1,r,title,segments=10)))
    return result


def _hands(bones):
    for name,title,region,solid in _hand_right():
        _add(bones,name+"_r",title+" правая","appendicular",region,"right",solid)
        _add(bones,name+"_l",title+" левая","appendicular",region,"left",_mirror(solid))


def _pelvis_and_legs(bones):
    wing=_hip_wing_sdf()
    acetabular_outer=_ellipsoid((65,5,865),(27,25,27),"наружная вертлужная впадина",
                                segments=22,rings=16)
    acetabular_inner=_ellipsoid((65,5,865),(21.5,21.5,21.5),"полость вертлужной впадины",
                                segments=22,rings=16)
    acetabulum=(acetabular_outer-acetabular_inner).trim_by_plane((-1,0,0),-65)
    obturator=_tube([(92,5,862),(80,-5,829),(47,-15,803),(14,-15,820),
                     (16,-5,850),(51,5,870)],[8.2]*6,
                    "запирательное отверстие",segments=14,steps=5,closed=True)
    hip=_fuse([wing,acetabulum,obturator,
               _tube([(100,35,915),(76,12,882)],[10,10],"тело подвздошной кости",segments=14,steps=4),
               _tube([(72,10,880),(92,8,862)],[9,9],"вертлужное тело",segments=14,steps=4),
               _tube([(104,18,884),(91,8,862)],[9,9],"седалищное тело",segments=14,steps=4)],
              "тазовая кость")
    femur=_fuse([
        _tube([(102,17,838),(111,19,760),(111,15,665),(104,7,565),(100,2,500)],
              [(12,12),(10.5,10.5),(10,10),(11,11),(17,14)],"диафиз бедренной кости",
              segments=16,steps=5,lobes=0.025),
        _tube([(102,17,838),(85,8,851),(65,5,865)],[(12,12),(11,11),(13,13)],
              "шейка бедренной кости",segments=14,steps=4),
        _ellipsoid((65,5,865),(19,19,19),"головка бедренной кости",organic=0.02),
        _ellipsoid((88,-1,490),(14,16,16),"медиальный мыщелок бедра"),
        _ellipsoid((113,-1,490),(14,16,16),"латеральный мыщелок бедра")],"бедренная кость")
    hip_clearance=_fuse([
        _ellipsoid((65,5,865),(21,21,21),"зазор вертлужной впадины"),
        _tube([(102,17,838),(85,8,851),(65,5,865)],[(13.5,13.5),(12.5,12.5),(14,14)],
              "зазор шейки бедренной кости",segments=14,steps=4),
        _tube([(102,17,845),(111,19,760)],[(13,13),(13,13)],
              "зазор проксимального диафиза",segments=14,steps=4)],
        "тазобедренный суставной зазор")
    hip=(hip-femur)-hip_clearance
    _add(bones,"hip_r","Тазовая кость правая","appendicular","pelvis","right",hip)
    _add(bones,"hip_l","Тазовая кость левая","appendicular","pelvis","left",_mirror(hip))
    patella=_ellipsoid((100,-28,491),(11,6,15),"надколенник",segments=16,rings=12,organic=0.06)
    tibia=_fuse([
        _tube([(100,5,449),(106,8,355),(102,2,230),(98,-5,99)],
              [(15,13),(10,9),(8.5,8),(14,11)],"большеберцовая кость",
              segments=16,steps=6,lobes=0.075),
        _ellipsoid((100,5,455),(22,18,11),"мыщелки большеберцовой кости",organic=0.025)],
        "большеберцовая кость")
    fibula=_fuse([
        _tube([(126,9,443),(128,12,350),(124,9,230),(120,5,92)],
              [(6,6),(4.2,4.2),(3.8,4),(7,6)],"малоберцовая кость",
              segments=12,steps=6,lobes=0.04),
        _ellipsoid((126,9,443),(8,8,9),"головка малоберцовой кости")],"малоберцовая кость")
    for name,title,solid in (("femur","Бедренная кость",femur),("patella","Надколенник",patella),
                             ("tibia","Большеберцовая кость",tibia),("fibula","Малоберцовая кость",fibula)):
        _add(bones,name+"_r",title+" правая","appendicular","lower_limb","right",solid)
        _add(bones,name+"_l",title+" левая","appendicular","lower_limb","left",_mirror(solid))


def _foot_right():
    result=[]
    tarsals=[
        ("talus","Таранная",(100,0,67),(17,22,18)),
        ("calcaneus","Пяточная",(105,20,24),(20,40,23)),
        ("navicular","Ладьевидная",(91,-43,49),(18,16,13)),
        ("cuboid","Кубовидная",(125,-36,30),(13,20,13)),
        ("medial_cuneiform","Медиальная клиновидная",(75,-75,32),(12,18,12)),
        ("intermediate_cuneiform","Промежуточная клиновидная",(97,-78,31),(9,16,11)),
        ("lateral_cuneiform","Латеральная клиновидная",(116,-73,30),(10,17,11)),
    ]
    for name,title,center,radii in tarsals:
        result.append((name,title,"tarsals",_ellipsoid(center,radii,"предплюсна "+name,
                                                        segments=16,rings=12,organic=0.09)))
    metatarsals=[
        (1,(75,-97,30),(68,-151,20),6.5),
        (2,(95,-99,29),(88,-160,18),5.0),
        (3,(112,-94,28),(108,-157,18),4.8),
        (4,(128,-87,27),(128,-149,18),4.5),
        (5,(140,-74,28),(145,-139,20),4.8),
    ]
    for i,p0,p1,r in metatarsals:
        result.append((f"metatarsal_{i}",f"Плюсневая кость {i}","metatarsals",
                       _small_bone(p0,p1,r,f"плюсневая кость {i}",segments=12)))
    toes={
        1:[((67,-159,20),(64,-181,18),5.4),((63,-187,17),(61,-204,15),4.6)],
        2:[((88,-168,18),(86,-187,15),4.0),((86,-192,14),(84,-204,12),3.3),
           ((84,-209,11),(83,-220,10),2.8)],
        3:[((108,-165,18),(108,-183,15),3.8),((108,-188,14),(107,-201,12),3.1),
           ((107,-206,11),(106,-216,10),2.6)],
        4:[((128,-157,18),(130,-174,16),3.6),((130,-179,15),(131,-191,13),3.0),
           ((131,-196,12),(132,-205,11),2.5)],
        5:[((146,-147,20),(151,-161,18),3.5),((152,-166,17),(155,-177,15),2.9),
           ((156,-182,14),(158,-191,13),2.4)],
    }
    for digit,segments in toes.items():
        names=["proximal","distal"] if digit==1 else ["proximal","middle","distal"]
        for idx,(p0,p1,r) in enumerate(segments):
            phalange=names[idx]
            title=f"Палец стопы {digit}: {phalange} фаланга"
            result.append((f"foot_phalanx_{digit}_{phalange}",title,"foot_phalanges",
                           _small_bone(p0,p1,r,title,segments=10)))
    return result


def _feet(bones):
    for name,title,region,solid in _foot_right():
        _add(bones,name+"_r",title+" правая","appendicular",region,"right",solid)
        _add(bones,name+"_l",title+" левая","appendicular",region,"left",_mirror(solid))


EXPECTED = {
    "total":206,"axial":80,"appendicular":126,"skull":22,"ear_ossicles":6,
    "hyoid":1,"spine":26,"ribs":24,"sternum":1,"shoulder":4,"pelvis":2,
    "upper_limb":6,"lower_limb":8,"carpals":16,"metacarpals":10,
    "hand_phalanges":28,"tarsals":14,"metatarsals":10,"foot_phalanges":28,
}


@lru_cache(maxsize=1)
def _canonical_bones():
    """Однократный расчёт канонической геометрии; Manifold-объекты неизменяемы."""
    bones=[]
    _skull(bones)
    _spine(bones)
    _thorax(bones)
    _shoulder_and_arm(bones)
    _hands(bones)
    _pelvis_and_legs(bones)
    _feet(bones)
    if len(bones)!=EXPECTED["total"]:
        raise ValueError(f"Внутренняя ошибка состава: {len(bones)} вместо 206")
    return tuple(bones)


def build_original_skeleton(height=CANONICAL_HEIGHT):
    """Масштабирует собственную каноническую сборку к заданному общему росту."""
    source=_canonical_bones()
    bones=[Bone(b.name,b.title,b.division,b.region,b.side,b.solid) for b in source]
    lo_z=min(b.solid.bounding_box()[2] for b in bones)
    hi_z=max(b.solid.bounding_box()[5] for b in bones)
    factor=float(height)/(hi_z-lo_z)
    for bone in bones:
        matrix=np.array([[factor,0,0,0],[0,factor,0,0],[0,0,factor,-lo_z*factor]],dtype=float)
        bone.solid=bone.solid.transform(matrix)
    return bones


def audit_original_skeleton(bones):
    counts={key:0 for key in EXPECTED}
    counts["total"]=len(bones)
    defects=[]
    for bone in bones:
        counts[bone.division]+=1
        counts[bone.region]+=1
        status=bone.solid.status().name
        parts=solid_parts(bone.solid)
        if status!="NoError" or bone.solid.volume()<=0:
            defects.append({"bone":bone.name,"issue":status})
        if parts!= (3 if bone.name=="sternum" else 1):
            defects.append({"bone":bone.name,"issue":f"connected_parts={parts}"})
    for key,expected in EXPECTED.items():
        if counts[key]!=expected:
            defects.append({"group":key,"actual":counts[key],"expected":expected})
    return {"counts":counts,"defects":defects,
            "triangles":sum(b.solid.num_tri() for b in bones),
            "vertices":sum(b.solid.num_vert() for b in bones),
            "volume_mm3":sum(b.solid.volume() for b in bones)}


def intersection_report(bones, min_volume=0.25):
    """Попарный аудит после AABB-отбора; сообщает реальный объём пересечений."""
    boxes=[b.solid.bounding_box() for b in bones]
    hits=[]
    for i,a in enumerate(bones):
        ba=boxes[i]
        for j in range(i+1,len(bones)):
            bb=boxes[j]
            if any(ba[k+3] < bb[k]-0.05 or bb[k+3] < ba[k]-0.05 for k in range(3)):
                continue
            common=a.solid ^ bones[j].solid
            volume=common.volume() if not common.is_empty() else 0.0
            if volume>min_volume:
                hits.append({"a":a.name,"b":bones[j].name,"volume_mm3":volume})
    return hits
