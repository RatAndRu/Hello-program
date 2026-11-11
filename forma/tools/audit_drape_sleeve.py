"""Повторяемый аудит стресс-сцены рукава; не создание готовой детали.

Запуск из корня репозитория: python forma/tools/audit_drape_sleeve.py
Для дополнительной независимой проверки можно установить python-fcl в
отдельное окружение. Результат выводится в stdout, проект не изменяется.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.cloth_check import _ADJACENT_INSET  # noqa: E402
from forma.geometry import manifold_mesh  # noqa: E402
from forma.run import build  # noqa: E402


def _fcl_object(fcl, vertices, faces):
    model = fcl.BVHModel()
    model.beginModel(len(vertices), len(faces))
    model.addSubModel(np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int32))
    model.endModel()
    return fcl.CollisionObject(model)


def _fcl_audit(vertices, faces, support, limit=300_000):
    try:
        import fcl
    except ImportError:
        return {"available": False, "reason": "python-fcl не установлен"}

    def pairs(obj):
        result = fcl.CollisionResult()
        fcl.collide(obj, obj, fcl.CollisionRequest(num_max_contacts=limit, enable_contact=True), result)
        return result.contacts, len(result.contacts) < limit

    body = _fcl_object(fcl, vertices, faces)
    contacts, nonadjacent_complete = pairs(body)
    # Порядок b1/b2 зависит от обхода BVH; не предполагаем, что FCL всегда
    # вернёт обе перестановки одной пары.
    nonadjacent = {tuple(sorted((int(c.b1), int(c.b2)))) for c in contacts
                   if 0 <= c.b1 < len(faces) and 0 <= c.b2 < len(faces)
                   and c.b1 != c.b2 and not set(faces[c.b1]).intersection(faces[c.b2])}
    triangles = vertices[faces]
    inset = triangles + (triangles.mean(axis=1)[:, None, :] - triangles) * _ADJACENT_INSET
    separated = np.arange(3 * len(faces), dtype=np.int32).reshape(-1, 3)
    near_contacts, adjacent_complete = pairs(_fcl_object(fcl, inset.reshape(-1, 3), separated))
    adjacent = {tuple(sorted((int(c.b1), int(c.b2)))) for c in near_contacts
                if 0 <= c.b1 < len(faces) and 0 <= c.b2 < len(faces)
                and c.b1 != c.b2 and set(faces[c.b1]).intersection(faces[c.b2])}
    support_result = fcl.CollisionResult()
    count = fcl.collide(body, _fcl_object(fcl, *support),
                        fcl.CollisionRequest(num_max_contacts=1), support_result)
    return {"available": True, "nonadjacent_pairs": len(nonadjacent),
            "nonadjacent_complete": nonadjacent_complete,
            "adjacent_pairs_after_inset": len(adjacent),
            "adjacent_complete": adjacent_complete,
            "support_surface_contact_or_crossing": bool(count)}


def main() -> int:
    path = ROOT / "benchmarks" / "drape_sleeve_stress_077.forma"
    started = time.perf_counter()
    result = build(path.read_text(encoding="utf-8"), analyze_model=False, base_dir=path.parent)
    if not result.ok:
        print(f"Сцена не собралась: {result.error}", file=sys.stderr)
        return 1
    body = result.scene.objects["проверка"]
    initial = result.scene.objects["рукав"]
    vertices, faces = manifold_mesh(body.manifold)
    support = manifold_mesh(result.scene.objects["пол"].manifold)
    report = {"scenario": str(path.relative_to(ROOT)),
              "elapsed_seconds": round(time.perf_counter() - started, 3),
              "bbox": list(body.manifold.bounding_box()),
              "volume_ratio": body.manifold.volume() / initial.manifold.volume(),
              "metadata": body.meta["cloth"], "fcl": _fcl_audit(vertices, faces, support),
              "warning": "Диагностический результат; он не является готовой деталью."}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
