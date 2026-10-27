"""Готовит ровно 206 анатомических костей из проверенного открытого источника.

Это offline-инструмент, а не зависимость Forma 3D. Для исходного Draco GLB нужны:
    pip install trimesh numpy DracoPy fast-simplification scipy scikit-image networkx

Воспроизведение текущего asset (фиксированный commit источника):
    git clone https://github.com/dreamrain314/human-skeleton-3d /tmp/human-skeleton-ref
    git -C /tmp/human-skeleton-ref checkout b78fc8e711dac5809a35f16209dc27a3df9f054d
    python tools/prepare_human_skeleton.py --source /tmp/human-skeleton-ref

Опция --hyoid принимает ранее восстановленную STL в исходных метрах. Без неё
подъязычная кость восстанавливается voxel fill + marching cubes автоматически.
Лицензии и авторство: examples/assets/human_skeleton.LICENSE.txt.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import struct
import subprocess

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE = {"FMA45097", "FMA45098"}  # две необязательные сесамовидные кости
EXPECTED_COMMIT = "b78fc8e711dac5809a35f16209dc27a3df9f054d"
COPYRIGHT = (
    "AnatomyTOOL / Z-Anatomy (CC BY-SA 4.0); ossicles neurothing/McGill audilab "
    "and BodyParts3D/DBCLS (CC BY 4.0); adaptation Forma 3D. "
    "See human_skeleton.LICENSE.txt."
)


def clean(mesh, normals=True):
    result = mesh.copy()
    result.merge_vertices(digits_vertex=6, merge_tex=True, merge_norm=True)
    result.remove_unreferenced_vertices()
    if len(result.faces):
        result.update_faces(result.nondegenerate_faces())
        result.update_faces(result.unique_faces())
        result.remove_unreferenced_vertices()
    if normals and len(result.faces) and not result.is_winding_consistent:
        trimesh.repair.fix_normals(result, multibody=True)
    return result


def repair_hyoid(mesh):
    """Закрывает повреждённый исходный hyoid, не запуская тяжёлый split()."""
    voxels = mesh.voxelized(pitch=0.00035).fill()
    result = voxels.marching_cubes
    # В использованной версии trimesh marching cubes возвращает voxel indices.
    result.apply_transform(voxels.transform)
    result = clean(result)
    if not result.is_watertight or not result.is_winding_consistent:
        raise RuntimeError("Не удалось восстановить замкнутую подъязычную кость")
    if result.volume < 0:
        result.invert()
    return result


def target_faces(count, node):
    if node == "FMA52749":
        return 1400
    ratio = 0.38 if count > 8000 else 0.42 if count > 3000 else 0.55 if count > 1000 else 1.0
    return max(64, round(count * ratio))


def embed_metadata(path: Path, commit: str, triangles: int):
    raw = path.read_bytes()
    magic, version, _ = struct.unpack_from("<4sII", raw)
    if magic != b"glTF" or version != 2:
        raise RuntimeError("Ожидался GLB 2.0")
    length, kind = struct.unpack_from("<I4s", raw, 12)
    if kind != b"JSON":
        raise RuntimeError("В GLB отсутствует JSON chunk")
    document = json.loads(raw[20:20 + length])
    asset = document.setdefault("asset", {})
    asset["copyright"] = COPYRIGHT
    asset["extras"] = {
        "license": "CC-BY-SA-4.0",
        "source": "https://github.com/dreamrain314/human-skeleton-3d",
        "sourceCommit": commit,
        "boneCount": 206,
        "triangles": triangles,
        "educationalUseOnly": True,
    }
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    text += b" " * ((-len(text)) % 4)
    remainder = raw[20 + length:]
    output = (struct.pack("<4sII", magic, version, 12 + 8 + len(text) + len(remainder))
              + struct.pack("<I4s", len(text), b"JSON") + text + remainder)
    path.write_bytes(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True,
                        help="клон dreamrain314/human-skeleton-3d на фиксированном commit")
    parser.add_argument("--hyoid", type=Path,
                        help="необязательная уже восстановленная STL в исходных метрах")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "examples/assets/human_skeleton.glb")
    parser.add_argument("--report", type=Path,
                        default=ROOT / "docs/human_skeleton_source_audit.json")
    args = parser.parse_args()
    source = args.source.resolve()
    scene = trimesh.load(source / "models/skeleton.glb", process=False)
    bones = json.loads((source / "data/bones.json").read_text(encoding="utf-8"))
    node_ids = [key for key in bones if key not in EXCLUDE]
    if len(node_ids) != 206 or len(scene.graph.nodes_geometry) != 210:
        raise RuntimeError("Неожиданный исходник: нужны 208 записей и 210 geometry nodes; "
                           "проверьте commit и установку DracoPy")
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        commit = EXPECTED_COMMIT
    if commit != EXPECTED_COMMIT:
        raise RuntimeError(f"Проверен только источник {EXPECTED_COMMIT}, получен {commit}")

    source_bounds = scene.bounds
    height = float(source_bounds[1][1] - source_bounds[0][1])
    if not 1.0 < height < 3.0:
        raise RuntimeError(f"Некорректный рост исходника {height}; вероятно, Draco не декодирован")
    scale = 1.75 / height
    transform = np.eye(4)
    transform[0, 0] = -scale       # анатомическое право источника −X → Forma +X
    transform[1, 1] = scale
    transform[2, 2] = scale
    transform[1, 3] = -float(source_bounds[0][1]) * scale
    hyoid_repaired = clean(trimesh.load(args.hyoid, process=False)) if args.hyoid else None

    def world(node):
        if node == "FMA52749" and hyoid_repaired is not None:
            return hyoid_repaired.copy()
        matrix, geometry = scene.graph[node]
        mesh = scene.geometry[geometry].copy()
        mesh.apply_transform(matrix)
        mesh = clean(mesh)
        return repair_hyoid(mesh) if node == "FMA52749" else mesh

    def simplified(node):
        original = world(node)
        count = len(original.faces)
        goal = target_faces(count, node)
        candidate = original
        if goal < count * 0.98:
            try:
                candidate = clean(original.simplify_quadric_decimation(face_count=goal))
                if not candidate.is_watertight or not candidate.is_winding_consistent:
                    candidate = original
            except Exception:
                candidate = original
        return candidate

    def finish(mesh):
        result = mesh.copy()
        result.apply_transform(transform)
        if not result.is_winding_consistent:
            trimesh.repair.fix_normals(result, multibody=True)
        if result.volume < 0:
            result.invert()
        return result

    result = trimesh.Scene()
    rows = []
    for index, node in enumerate(node_ids, 1):
        if node == "FMA7371":
            parts = [simplified(name) for name in ("FMA7371", "FMA7371_1", "FMA7371_2")]
            mesh = trimesh.util.concatenate(parts)
        else:
            mesh = simplified(node)
        mesh = finish(mesh)
        result.add_geometry(mesh, node_name=node, geom_name=node)
        rows.append({
            "node": node, "en": bones[node]["en"], "region": bones[node]["region"],
            "group": bones[node]["group"], "tris": len(mesh.faces),
            "watertight": bool(mesh.is_watertight),
            "winding": bool(mesh.is_winding_consistent),
            "bounds": mesh.bounds.tolist(),
            "parts": len(mesh.split(only_watertight=False)),
        })
        if index % 20 == 0 or index == 206:
            print(f"{index}/206, triangles={sum(row['tris'] for row in rows)}", flush=True)
        gc.collect()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    result.export(args.output)
    triangles = sum(row["tris"] for row in rows)
    embed_metadata(args.output, commit, triangles)
    report = {
        "source": "AnatomyTOOL / Z-Anatomy via dreamrain314/human-skeleton-3d",
        "source_commit": commit, "bones": len(rows), "triangles": triangles,
        "bounds_gltf_m": result.bounds.tolist(),
        "bad": [row for row in rows if not row["watertight"] or not row["winding"]],
        "parts_not_one": {row["node"]: row["parts"] for row in rows if row["parts"] != 1},
        "rows": rows, "output": args.output.name, "bytes": args.output.stat().st_size,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"},
                     ensure_ascii=False, indent=2))
    assert not report["bad"], report["bad"]
    assert len(result.graph.nodes_geometry) == 206
    assert result.bounds[0][1] > -0.0001 and abs(result.bounds[1][1] - 1.75) < 0.0002


if __name__ == "__main__":
    main()
