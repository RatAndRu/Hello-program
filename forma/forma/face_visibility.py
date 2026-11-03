"""Проверка пользовательской разметки треугольников «снаружи / строго внутри».

Синяя грань должна целиком лежать снаружи всех других видимых тел. Красная —
целиком и строго внутри хотя бы одного другого замкнутого тела. Серые грани не
проверяются. Это проверка вложенности поверхности, а не направления нормали и
не утверждение о видимости из произвольной камеры.

Важно: проверять только центр треугольника нельзя. Сначала ищется контакт всей
грани с оболочкой контейнера; если его нет, один parity-ray по внутренней точке
однозначно классифицирует всю грань. Поэтому частично торчащий корень зуба не
получает ложный «внутри» из-за центра, оказавшегося в материале головы.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import _clean_manifold_arrays

ROLES = ("outside", "inside")


def normalize_roles(value) -> dict[str, list[int]]:
    """JSON-совместимая, детерминированная форма разметки Solid.face_roles."""
    source = value or {}
    out = {}
    for role in ROLES:
        try:
            ids = sorted({int(i) for i in (source.get(role) or []) if int(i) >= 0})
        except (TypeError, ValueError):
            ids = []
        if ids:
            out[role] = ids
    return out


def roles_payload(solid) -> dict | None:
    roles = normalize_roles(getattr(solid, "face_roles", None))
    return roles or None


@dataclass
class _Body:
    name: str
    verts: np.ndarray
    faces: np.ndarray
    tris: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    eps: float
    watertight: bool | None = None


def _body(solid) -> _Body:
    # Тот же экспортный порядок граней, который видит three.js после picking.
    verts, faces = _clean_manifold_arrays(solid.manifold)
    verts = np.asarray(verts, dtype=np.float64)[:, :3]
    faces = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    tris = np.asarray(verts[faces], dtype=np.float64)
    if len(verts):
        lo, hi = verts.min(axis=0), verts.max(axis=0)
        diagonal = float(np.linalg.norm(hi - lo))
    else:
        lo, hi, diagonal = np.zeros(3), np.zeros(3), 1.0
    return _Body(solid.name, verts, faces, tris, lo, hi,
                 max(1e-7, diagonal * 1e-8))


def _is_watertight(body: _Body) -> bool:
    if body.watertight is None:
        if not len(body.faces):
            body.watertight = False
        else:
            directed = body.faces[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
            edges = np.sort(directed, axis=1)
            _unique, counts = np.unique(edges, axis=0, return_counts=True)
            body.watertight = bool(np.all(counts == 2))
    return body.watertight


def _point_in_triangle(point, tri) -> bool:
    """2D barycentric test; граница тоже считается контактом."""
    p = np.asarray(point, dtype=np.float64)
    a, b, c = np.asarray(tri, dtype=np.float64)
    v0, v1, v2 = b - a, c - a, p - a
    den = v0[0] * v1[1] - v1[0] * v0[1]
    if abs(den) < 1e-18:
        return False
    u = (v2[0] * v1[1] - v1[0] * v2[1]) / den
    v = (v0[0] * v2[1] - v2[0] * v0[1]) / den
    return u >= -1e-8 and v >= -1e-8 and u + v <= 1.0 + 1e-8


def _on_segment(point, a, b, eps: float) -> bool:
    p = np.asarray(point, dtype=np.float64)
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    ab = b - a
    length = float(np.linalg.norm(ab))
    if length <= eps:
        return bool(np.linalg.norm(p - a) <= eps)
    cross = abs(float(ab[0] * (p[1] - a[1]) - ab[1] * (p[0] - a[0])))
    if cross > eps * max(length, 1.0):
        return False
    dot = float(np.dot(p - a, ab))
    return -eps * length <= dot <= length * length + eps * length


def _segments_contact(a, b, c, d, eps: float) -> bool:
    a, b, c, d = [np.asarray(p, dtype=np.float64) for p in (a, b, c, d)]
    if np.linalg.norm(b - a) <= eps:
        return _on_segment(a, c, d, eps)
    if np.linalg.norm(d - c) <= eps:
        return _on_segment(c, a, b, eps)

    def orient(p, q, r):
        return float((q[0] - p[0]) * (r[1] - p[1])
                     - (q[1] - p[1]) * (r[0] - p[0]))

    scale = max(1.0, float(np.linalg.norm(b - a)), float(np.linalg.norm(d - c)))
    tol = eps * scale
    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    if ((o1 > tol and o2 < -tol) or (o1 < -tol and o2 > tol)) and \
            ((o3 > tol and o4 < -tol) or (o3 < -tol and o4 > tol)):
        return True
    return ((abs(o1) <= tol and _on_segment(c, a, b, eps))
            or (abs(o2) <= tol and _on_segment(d, a, b, eps))
            or (abs(o3) <= tol and _on_segment(a, c, d, eps))
            or (abs(o4) <= tol and _on_segment(b, c, d, eps)))


def _segment_triangle_contact(a, b, tri, eps: float) -> bool:
    if _point_in_triangle(a, tri) or _point_in_triangle(b, tri):
        return True
    return any(_segments_contact(a, b, tri[i], tri[(i + 1) % 3], eps)
               for i in range(3))


def _coplanar_triangles_contact(other, marked, eps: float) -> bool:
    for i in range(3):
        if _segment_triangle_contact(other[i], other[(i + 1) % 3], marked, eps):
            return True
    return _point_in_triangle(marked[0], other)


def _plane_basis(triangle):
    a, b, c = np.asarray(triangle, dtype=np.float64)
    normal = np.cross(b - a, c - a)
    length = float(np.linalg.norm(normal))
    if not np.isfinite(length) or length <= 1e-12:
        return None
    normal /= length
    ux = b - a
    ux /= float(np.linalg.norm(ux))
    uy = np.cross(normal, ux)
    return a, normal, ux, uy


def _project(points, basis):
    a, _normal, ux, uy = basis
    rel = np.asarray(points, dtype=np.float64) - a
    return np.stack([rel @ ux, rel @ uy], axis=-1)


def _surface_contact(triangle, body: _Body) -> bool:
    """Контакт/пересечение треугольника с любой гранью оболочки body."""
    tri = np.asarray(triangle, dtype=np.float64)
    basis = _plane_basis(tri)
    if basis is None:
        return True
    lo, hi = tri.min(axis=0), tri.max(axis=0)
    eps = body.eps
    if not len(body.tris):
        return False
    other_lo = body.tris.min(axis=1)
    other_hi = body.tris.max(axis=1)
    candidates = np.nonzero(
        np.all(other_hi >= lo - eps, axis=1)
        & np.all(other_lo <= hi + eps, axis=1)
    )[0]
    if not len(candidates):
        return False
    marked2 = _project(tri, basis)
    origin, normal, _ux, _uy = basis
    for q in body.tris[candidates]:
        dist = (q - origin) @ normal
        if np.all(np.abs(dist) <= eps):
            if _coplanar_triangles_contact(_project(q, basis), marked2, eps):
                return True
            continue
        points = []
        for i in range(3):
            j = (i + 1) % 3
            d0, d1 = float(dist[i]), float(dist[j])
            p0, p1 = q[i], q[j]
            if abs(d0) <= eps:
                points.append(p0)
            if (d0 > eps and d1 < -eps) or (d0 < -eps and d1 > eps):
                t = d0 / (d0 - d1)
                points.append(p0 + (p1 - p0) * t)
            if abs(d1) <= eps:
                points.append(p1)
        if not points:
            continue
        unique = []
        for point in points:
            if not any(float(np.linalg.norm(point - old)) <= eps for old in unique):
                unique.append(point)
        if len(unique) == 1:
            if _point_in_triangle(_project(unique, basis)[0], marked2):
                return True
        else:
            # Сечение неcoplanar-треугольника плоскостью — отрезок.
            a, b = _project(np.asarray(unique[:2]), basis)
            if _segment_triangle_contact(a, b, marked2, eps):
                return True
    return False


def _point_inside(point, body: _Body) -> bool | None:
    """Parity ray; None означает, что замкнутость/луч не дают доказательства."""
    if not _is_watertight(body):
        return None
    p = np.asarray(point, dtype=np.float64)
    eps = body.eps
    if np.any(p < body.lo - eps) or np.any(p > body.hi + eps):
        return False
    if not len(body.tris):
        return False
    directions = (
        (1.0, 0.3713906763541037, 0.7437813527082074),
        (0.2672612419124244, 1.0, 0.5345224838248488),
        (0.408248290463863, 0.816496580927726, 1.0),
        (1.0, 0.5773502691896258, 0.3333333333333333),
    )
    v0 = body.tris[:, 0]
    edge1 = body.tris[:, 1] - v0
    edge2 = body.tris[:, 2] - v0
    for raw in directions:
        direction = np.asarray(raw, dtype=np.float64)
        direction /= np.linalg.norm(direction)
        pvec = np.cross(np.broadcast_to(direction, edge2.shape), edge2)
        det = np.einsum("ij,ij->i", edge1, pvec)
        valid = np.abs(det) > 1e-12
        if not np.any(valid):
            continue
        inv = np.zeros_like(det)
        inv[valid] = 1.0 / det[valid]
        tvec = p - v0
        u = np.einsum("ij,ij->i", tvec, pvec) * inv
        qvec = np.cross(tvec, edge1)
        v = np.einsum("ij,ij->i", np.broadcast_to(direction, qvec.shape), qvec) * inv
        distance = np.einsum("ij,ij->i", edge2, qvec) * inv
        bary_eps = 1e-9
        hit = (valid & (distance > eps) & (u >= -bary_eps) & (v >= -bary_eps)
               & (u + v <= 1.0 + bary_eps))
        if not np.any(hit):
            return False
        # Попадание ровно в ребро/вершину может быть посчитано дважды.
        ambiguous = hit & ((np.abs(u) < bary_eps) | (np.abs(v) < bary_eps)
                           | (np.abs(u + v - 1.0) < bary_eps))
        if np.any(ambiguous):
            continue
        return bool(int(np.count_nonzero(hit)) % 2)
    return None


def _relation(triangle, body: _Body) -> str:
    tri = np.asarray(triangle, dtype=np.float64)
    lo, hi = tri.min(axis=0), tri.max(axis=0)
    if np.any(hi < body.lo - body.eps) or np.any(lo > body.hi + body.eps):
        return "outside"
    if _surface_contact(tri, body):
        return "boundary"
    inside = _point_inside(tri.mean(axis=0), body)
    if inside is None:
        return "unknown"
    return "inside" if inside else "outside"


def _failure_text(role: str, face: int, actual: str, container: str) -> str:
    if role == "outside":
        if actual == "inside":
            return f"грань {face}: должна быть снаружи, но целиком внутри «{container}»"
        if actual == "boundary":
            return (f"грань {face}: не целиком снаружи — пересекает или касается "
                    f"поверхности «{container}»")
        return f"грань {face}: наружность не доказана — оболочка «{container}» не замкнута"
    if actual == "boundary":
        return (f"грань {face}: должна быть строго внутри, но пересекает или касается "
                f"«{container}»; часть грани может торчать")
    if actual == "unknown":
        return f"грань {face}: вложенность не доказана — оболочка «{container}» не замкнута"
    return f"грань {face}: должна быть строго внутри другого тела, но находится снаружи"


def analyze_face_visibility(scene, max_details: int = 1000) -> dict:
    """Проверяет только размеченные грани видимых объектов сцены."""
    cached = getattr(scene, "_face_visibility_cache", None)
    if cached is not None:
        return cached
    visible = list(scene.visible_solids())
    bodies: dict[str, _Body] = {}

    def body(solid):
        if solid.name not in bodies:
            bodies[solid.name] = _body(solid)
        return bodies[solid.name]

    object_reports = []
    violations = []
    details = 0
    truncated = 0
    marked = outside = inside = checked = skipped_hidden = 0
    for solid in scene.objects.values():
        roles = normalize_roles(getattr(solid, "face_roles", None))
        count_out = len(roles.get("outside", []))
        count_in = len(roles.get("inside", []))
        if not count_out and not count_in:
            continue
        marked += count_out + count_in
        outside += count_out
        inside += count_in
        entry = {"object": solid.name, "outside": count_out, "inside": count_in,
                 "ok": True, "violations": 0, "checked": 0, "faces": []}
        object_reports.append(entry)
        if not solid.visible or solid.manifold.is_empty():
            skipped_hidden += count_out + count_in
            continue
        source = body(solid)
        for role in ROLES:
            for face_id in roles.get(role, []):
                if face_id >= len(source.tris):
                    # Команда DSL валидирует индексы; защита нужна для прямого API.
                    result = {"face": face_id, "role": role, "ok": False,
                              "actual": "missing", "container": "",
                              "message": f"грань {face_id}: индекс вне сетки ({len(source.tris)} граней)"}
                else:
                    checked += 1
                    entry["checked"] += 1
                    triangle = source.tris[face_id]
                    best = None
                    passed = False
                    for other in visible:
                        if other.name == solid.name:
                            continue
                        candidate = body(other)
                        actual = _relation(triangle, candidate)
                        if role == "outside":
                            if actual == "outside":
                                continue
                            best = {"actual": actual, "container": other.name}
                            break
                        if actual == "inside":
                            best = {"actual": actual, "container": other.name}
                            passed = True
                            break
                        priority = {"boundary": 2, "unknown": 1, "outside": 0}
                        if best is None or priority[actual] > priority[best["actual"]]:
                            best = {"actual": actual, "container": other.name}
                    if role == "outside" and best is None:
                        best = {"actual": "outside", "container": ""}
                        passed = True
                    if best is None:
                        best = {"actual": "outside", "container": ""}
                    actual = best["actual"]
                    ok = bool(passed)
                    result = {"face": face_id, "role": role, "ok": ok,
                              "actual": actual, "container": best["container"],
                              "message": "" if ok else _failure_text(
                                  role, face_id, actual, best["container"])}
                if not result["ok"]:
                    entry["ok"] = False
                    entry["violations"] += 1
                    violations.append({"object": solid.name, **result})
                if details < max_details:
                    entry["faces"].append(result)
                    details += 1
                else:
                    truncated += 1
    bad = sum(1 for item in violations)
    report = {
        "ok": bad == 0,
        "marked": marked,
        "outside": outside,
        "inside": inside,
        "checked": checked,
        "violations": bad,
        "skipped_hidden": skipped_hidden,
        "objects": object_reports,
        "violation_list": violations[:200],
        "truncated": truncated + max(0, len(violations) - 200),
    }
    # Analyze/check используют один и тот же расчёт в пределах построенной сцены.
    scene._face_visibility_cache = report
    return report


def object_face_report(scene, name: str) -> dict | None:
    report = analyze_face_visibility(scene)
    return next((item for item in report["objects"] if item["object"] == name), None)


def summary_metrics(report: dict) -> dict:
    return {key: report[key] for key in
            ("ok", "marked", "outside", "inside", "checked", "violations", "skipped_hidden")}
