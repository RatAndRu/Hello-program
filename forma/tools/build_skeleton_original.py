"""Экспорт и визуальный аудит оригинального параметрического скелета.

Запуск из папки forma:
    PYTHONPATH=. python tools/build_skeleton_original.py --render
Без --render записываются только GLB, имена и машинный аудит — это режим CI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.model import Solid  # noqa: E402
from forma.run import build  # noqa: E402
from forma.skeleton_original import (audit_original_skeleton,  # noqa: E402
                                      build_original_skeleton,
                                      intersection_report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    project = ROOT / "examples" / "human_skeleton_original.forma"
    result = build(project.read_text(encoding="utf-8"))
    if not result.ok:
        raise SystemExit(result.error)
    if len(result.scene.objects) != 206 or not all(c["ok"] for c in result.analysis["checks"]):
        raise SystemExit("Проект не прошёл встроенные проверки")
    bones = build_original_skeleton()
    report = audit_original_skeleton(bones)
    hits = intersection_report(bones, min_volume=1.0)
    if report["defects"] or hits:
        raise SystemExit(json.dumps({"defects": report["defects"], "intersections": hits},
                                    ensure_ascii=False, indent=2))
    data = result.glb()
    json_len, json_type = struct.unpack_from("<I4s", data, 12)
    if json_type != b"JSON":
        raise SystemExit("Повреждён GLB JSON chunk")
    document = json.loads(data[20:20+json_len])
    if len(document["meshes"]) != 206 or sum("mesh" in n for n in document["nodes"]) != 206:
        raise SystemExit("GLB должен содержать 206 независимых костей")

    assets = ROOT / "examples" / "assets"
    assets.mkdir(exist_ok=True)
    glb_path = assets / "human_skeleton_original.glb"
    glb_path.write_bytes(data)
    names = {s.name: s.meta["title"] for s in result.scene.objects.values()}
    (assets / "human_skeleton_original.names.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    audit = {
        "schema": 1,
        "project": "examples/human_skeleton_original.forma",
        "generator": "forma/skeleton_original.py",
        "geometry_origin": "original_parametric_only",
        "third_party_mesh_import": False,
        "height_mm": 1750.0,
        "objects": len(result.scene.objects),
        "glb_meshes": len(document["meshes"]),
        "glb_nodes_with_mesh": sum("mesh" in n for n in document["nodes"]),
        "embedded_checks": len(result.analysis["checks"]),
        "embedded_checks_ok": sum(c["ok"] for c in result.analysis["checks"]),
        "intersections_above_1_mm3": hits,
        **report,
        "glb_bytes": len(data),
        "glb_sha256": hashlib.sha256(data).hexdigest(),
    }
    audit_path = assets / "human_skeleton_original.audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"glb": str(glb_path), "bytes": len(data), "triangles": report["triangles"],
                      "counts": report["counts"], "defects": report["defects"],
                      "intersections": len(hits)}, ensure_ascii=False, indent=2))

    if args.render:
        from forma.render import render_single, render_views
        docs = ROOT / "docs" / "human_skeleton_original"
        docs.mkdir(parents=True, exist_ok=True)
        solids = [Solid(name=b.name, manifold=b.solid, color="#d9cfb6", rough=0.72,
                        density=1.7, meta={"smooth_normals": True}) for b in bones]
        render_views(solids, str(docs), prefix="skeleton", size=700, ss=1,
                     views=("front", "back", "right", "iso"), combined=True)
        shutil.copyfile(docs / "skeleton_all.png", ROOT / "docs" / "human_skeleton_original.png")
        selected = {
            "skull": [s for s,b in zip(solids,bones)
                      if b.region in ("skull","ear_ossicles","hyoid")],
            "pelvis": [s for s,b in zip(solids,bones)
                       if b.region == "pelvis" or b.name in ("sacrum","coccyx")],
            "hand_right": [s for s,b in zip(solids,bones)
                           if b.side == "right" and b.region in ("carpals","metacarpals","hand_phalanges")],
            "foot_right": [s for s,b in zip(solids,bones)
                           if b.side == "right" and b.region in ("tarsals","metatarsals","foot_phalanges")],
        }
        render_single(selected["skull"], str(docs), "skull_front.png", size=850, ss=1, view="front")
        render_single(selected["skull"], str(docs), "skull_iso.png", size=850, ss=1, view="iso")
        render_single(selected["pelvis"], str(docs), "pelvis_front.png", size=850, ss=1, view="front")
        render_single(selected["hand_right"], str(docs), "hand_right.png", size=850, ss=1, view="front")
        render_single(selected["foot_right"], str(docs), "foot_right_iso.png", size=850, ss=1, view="iso")
        print("Рендеры:", docs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
