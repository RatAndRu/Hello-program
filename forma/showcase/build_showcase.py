#!/usr/bin/env python3
"""Собирает статический стенд: GLB, лёгкий preview, WebP и каталог версий.

Preview не упрощает геометрию. Нормали и треугольники полного экспорта
сохраняются; узлы лишь пакетируются по одинаковым материалам. Полный GLB
с отдельными деталями всегда остаётся отдельным файлом для скачивания.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

from forma.geometry import (
    _glb_geometry,
    _glb_patch_materials,
    color_to_gltf,
    manifold_mesh,
)
from forma.render import render_single
from forma.run import build

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOWCASE_ROOT = Path(__file__).resolve().parent
MAX_BATCH_VERTICES = 60_000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def train_interior_solids(solids):
    """Фильтр только для статического ракурса салона, не для скачиваемой сцены."""
    result = []
    for solid in solids:
        name = solid.name
        if name.startswith("track_"):
            continue
        if name == "car_roof" or name.startswith(("roof_", "hvac_")):
            continue
        if name == "car_wall_near" or name in ("int_wall_lower_m1", "int_wall_upper_m1") or name.startswith(
                ("win_near_", "door_near_", "rib_near_", "livery_near_", "logo_near_",
                 "number_near_", "capacity_near_")):
            continue
        if name.startswith(("bogie_", "wheel_", "flange_", "axle", "bearing_", "hub", "brake_",
                            "spring_", "primary_spring_", "under_")):
            continue
        result.append(solid)
    return result


def material_key(solid) -> tuple:
    return (
        tuple(color_to_gltf(solid.color)),
        round(float(solid.metal), 6),
        round(float(solid.rough), 6),
        str(getattr(solid, "emissive", "") or ""),
        round(float(getattr(solid, "emissive_strength", 1.0)), 6),
        round(float(getattr(solid, "transmission", 0.0) or 0.0), 6),
        round(float(getattr(solid, "mirror", 0.0) or 0.0), 6),
        bool(solid.meta.get("smooth_normals")),
        str(getattr(solid, "uv", "auto") or "auto"),
    )


def has_special_surface(solids) -> bool:
    return any(getattr(s, "paint", None) or getattr(s, "brush", None) or getattr(s, "tex", None)
               for s in solids)


def _batch_material(name: str, proto) -> PBRMaterial:
    mirror = float(getattr(proto, "mirror", 0.0) or 0.0)
    prefix = ("mirror__" if mirror >= 0.999 else
              f"mirror{mirror:.2f}__" if mirror > 1e-6 else "")
    material = PBRMaterial(
        name=f"mat_{prefix}{name}",
        baseColorFactor=color_to_gltf(proto.color),
        metallicFactor=max(float(proto.metal), mirror),
        roughnessFactor=max(0.02, float(proto.rough) * (1.0 - mirror)),
        doubleSided=False,
    )
    emissive = getattr(proto, "emissive", "") or ""
    if emissive:
        material.emissiveFactor = [round(c, 4) for c in color_to_gltf(emissive)[:3]]
    return material


def _pack_geometry(items, max_vertices=MAX_BATCH_VERTICES):
    """Пакует уже разбитые по нормалям meshes, не меняя ни одного индекса."""
    chunks = []
    current = []
    current_vertices = 0
    for item in items:
        vertex_count = len(item["vertices"])
        if current and current_vertices + vertex_count > max_vertices:
            chunks.append(current)
            current = []
            current_vertices = 0
        current.append(item)
        current_vertices += vertex_count
    if current:
        chunks.append(current)
    return chunks


def export_preview_glb(solids) -> tuple[bytes, dict]:
    """Экспорт статического preview с пакетами материалов и исходной тесселяцией."""
    if has_special_surface(solids):
        raise ValueError("Покраска и текстуры требуют отдельного пути экспорта preview.")
    grouped = OrderedDict()
    for solid in solids:
        vertices, normals, faces = _glb_geometry(
            solid.manifold,
            crease_angle=120.0 if solid.meta.get("smooth_normals") else 38.0,
        )
        item = {
            "solid": solid,
            "vertices": vertices,
            "normals": normals,
            "faces": faces,
        }
        grouped.setdefault(material_key(solid), []).append(item)

    scene = trimesh.Scene()
    styles = {}
    batch_index = 0
    source_meshes = 0
    for items in grouped.values():
        for chunk in _pack_geometry(items):
            vertices = []
            normals = []
            faces = []
            offset = 0
            for item in chunk:
                vertices.append(item["vertices"])
                normals.append(item["normals"])
                faces.append(item["faces"] + offset)
                offset += len(item["vertices"])
            proto = chunk[0]["solid"]
            name = f"material_{batch_index:03d}"
            batch_index += 1
            source_meshes += len(chunk)
            mesh = trimesh.Trimesh(
                vertices=np.concatenate(vertices),
                faces=np.concatenate(faces),
                vertex_normals=np.concatenate(normals),
                process=False,
                visual=trimesh.visual.TextureVisuals(material=_batch_material(name, proto)),
            )
            scene.add_geometry(mesh, node_name=name, geom_name=name)
            styles[name] = {
                "emissive": getattr(proto, "emissive", "") or "",
                "emissive_strength": float(getattr(proto, "emissive_strength", 1.0)),
                "transmission": float(getattr(proto, "transmission", 0.0) or 0.0),
                "mirror": float(getattr(proto, "mirror", 0.0) or 0.0),
            }
    if not scene.geometry:
        raise ValueError("Нет видимой геометрии для preview.")
    data = bytes(trimesh.exchange.gltf.export_glb(scene, include_normals=True))
    if any(style["emissive"] and abs(style["emissive_strength"] - 1.0) > 0.001
           or style["transmission"] > 0.01 for style in styles.values()):
        data = _glb_patch_materials(data, styles)
    return data, {
        "optimized": True,
        "source_meshes": source_meshes,
        "preview_draw_calls": len(scene.geometry),
        "batch_vertex_limit": MAX_BATCH_VERTICES,
    }


def _scene_metrics(data: bytes) -> dict:
    scene = trimesh.load(io.BytesIO(data), file_type="glb", force="scene", process=False)
    faces = int(sum(len(mesh.faces) for mesh in scene.geometry.values()))
    vertices = int(sum(len(mesh.vertices) for mesh in scene.geometry.values()))
    bounds = np.asarray(scene.bounds, dtype=float)
    if not faces or not np.all(np.isfinite(bounds)):
        raise RuntimeError("GLB содержит пустую или нечисловую геометрию.")
    return {
        "scene": scene,
        "faces": faces,
        "vertices": vertices,
        "nodes": len(scene.graph.nodes_geometry),
        "bounds": bounds,
    }


def validate_glb_pair(full_glb: bytes, preview_glb: bytes, solids) -> dict:
    """Независимый round-trip обоих файлов и сравнение с исходными solids."""
    full = _scene_metrics(full_glb)
    preview = _scene_metrics(preview_glb)
    expected_faces = int(sum(len(manifold_mesh(solid.manifold)[1]) for solid in solids))
    if full["faces"] != expected_faces or preview["faces"] != expected_faces:
        raise RuntimeError(
            f"Тесселяция изменилась: source={expected_faces}, full={full['faces']}, "
            f"preview={preview['faces']}",
        )
    source_lo = []
    source_hi = []
    for solid in solids:
        bb = solid.manifold.bounding_box()
        source_lo.append([bb[0], bb[2], -bb[4]])
        source_hi.append([bb[3], bb[5], -bb[1]])
    expected_bounds = np.array([
        np.min(source_lo, axis=0),
        np.max(source_hi, axis=0),
    ])
    deviations = {
        "full": float(np.max(np.abs(full["bounds"] - expected_bounds))),
        "preview": float(np.max(np.abs(preview["bounds"] - expected_bounds))),
    }
    if max(deviations.values()) > 0.002:
        raise RuntimeError(f"Габариты GLB изменились: {deviations}")
    return {
        "triangles": expected_faces,
        "full_vertices": full["vertices"],
        "preview_vertices": preview["vertices"],
        "full_nodes": full["nodes"],
        "preview_nodes": preview["nodes"],
        "bounds_deviation_mm": deviations,
    }


def _write(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"bytes": len(data), "sha256": sha256(data)}


def _render_posters(model, solids, groups, output: Path) -> list[dict]:
    from PIL import Image

    posters = []
    for poster in model.get("posters", [{"view": "iso", "label": "Общий вид"}]):
        view = poster.get("view", "iso")
        selected = train_interior_solids(solids) if view == "train_interior" else solids
        render_view = "iso" if view == "train_interior" else view
        stem = f"{model['id']}_{view}"
        png_path = output / "posters" / f"{stem}.png"
        render_single(selected, output / "posters", f"{stem}.png", size=960, ss=1,
                      view=render_view, groups=groups)
        webp_path = output / "assets" / "posters" / f"{stem}.webp"
        webp_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(png_path) as image:
            image = image.convert("RGB")
            image.save(webp_path, "WEBP", quality=84, method=6)
            width, height = image.size
        data = webp_path.read_bytes()
        posters.append({
            "view": view,
            "label": poster.get("label", view),
            "url": f"assets/posters/{webp_path.name}",
            "bytes": len(data),
            "sha256": sha256(data),
            "width": width,
            "height": height,
        })
    return posters


def build_model(model, repo_root: Path, output: Path) -> dict:
    started = time.perf_counter()
    source_path = repo_root / model["source"]
    script = source_path.read_text(encoding="utf-8")
    result = build(script, analyze_model=False)
    if not result.ok:
        raise RuntimeError(f"{model['id']}: {result.error}")
    solids = result.visible_solids()
    if not solids:
        raise RuntimeError(f"{model['id']}: пустая сцена")

    full_glb = result.glb()
    if has_special_surface(solids):
        # Честный fallback: ничего не теряем, просто не объединяем такую сцену.
        preview_glb = full_glb
        optimization = {
            "optimized": False,
            "source_meshes": len(solids),
            "preview_draw_calls": len(solids),
            "reason": "Покраска/текстуры сохранены в исходных узлах без пакетирования.",
        }
    else:
        preview_glb, optimization = export_preview_glb(solids)
    geometry = validate_glb_pair(full_glb, preview_glb, solids)
    if geometry["preview_nodes"] != optimization["preview_draw_calls"]:
        raise RuntimeError(f"{model['id']}: число preview-узлов не совпадает с экспортом")

    models_dir = output / "assets" / "models"
    forma_info = _write(models_dir / f"{model['id']}.forma", source_path.read_bytes())
    full_info = _write(models_dir / f"{model['id']}.glb", full_glb)
    preview_info = _write(models_dir / f"{model['id']}.preview.glb", preview_glb)
    posters = _render_posters(model, solids, result.scene.groups, output)

    excluded = {"source", "posters"}
    manifest = {key: value for key, value in model.items() if key not in excluded}
    manifest.update({
        "forma": {
            "url": f"assets/models/{model['id']}.forma",
            "file_name": f"{model.get('download_base', model['id'])}.forma",
            **forma_info,
        },
        "full_glb": {
            "url": f"assets/models/{model['id']}.glb",
            "file_name": f"{model.get('download_base', model['id'])}.glb",
            **full_info,
        },
        "preview_glb": {
            "url": f"assets/models/{model['id']}.preview.glb",
            "file_name": f"{model.get('download_base', model['id'])}.preview.glb",
            **preview_info,
        },
        "posters": posters,
        "stats": {
            "objects": len(solids),
            "triangles": geometry["triangles"],
            "full_vertices": geometry["full_vertices"],
            "preview_vertices": geometry["preview_vertices"],
            "preview_draw_calls": geometry["preview_nodes"],
            "optimized": optimization["optimized"],
            "bounds_deviation_mm": geometry["bounds_deviation_mm"],
        },
    })
    elapsed = time.perf_counter() - started
    print(
        f"{model['id']}: {len(solids)} objects -> {geometry['preview_nodes']} draw calls; "
        f"{geometry['triangles']} tris; full={len(full_glb)} B; preview={len(preview_glb)} B; "
        f"{elapsed:.1f}s",
        flush=True,
    )
    return manifest


def copy_static(output: Path) -> None:
    shutil.copytree(SHOWCASE_ROOT / "static", output, dirs_exist_ok=True)
    vendor_source = REPO_ROOT / "forma" / "web" / "vendor"
    vendor_output = output / "assets" / "vendor"
    vendor_output.mkdir(parents=True, exist_ok=True)
    for name in ("three.module.js", "OrbitControls.js", "GLTFLoader.js", "THREE_LICENSE.txt"):
        shutil.copy2(vendor_source / name, vendor_output / name)
    (vendor_output / "utils").mkdir(exist_ok=True)
    shutil.copy2(vendor_source / "utils" / "BufferGeometryUtils.js",
                 vendor_output / "utils" / "BufferGeometryUtils.js")


def precompress(output: Path) -> None:
    suffixes = {".html", ".css", ".js", ".json", ".glb", ".forma", ".svg", ".txt"}
    for path in output.rglob("*"):
        if path.is_file() and path.suffix in suffixes:
            raw = path.read_bytes()
            path.with_name(path.name + ".gz").write_bytes(gzip.compress(raw, 9, mtime=0))


def build_site(repo_root: Path, output: Path, revision: str) -> dict:
    output = output.resolve()
    if output in (Path("/"), repo_root.resolve()):
        raise ValueError("Небезопасная папка вывода стенда.")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    copy_static(output)
    catalog = json.loads((SHOWCASE_ROOT / "catalog.source.json").read_text(encoding="utf-8"))
    versions = []
    for version in catalog["versions"]:
        item = {key: value for key, value in version.items() if key != "models"}
        item["models"] = [build_model(model, repo_root, output) for model in version["models"]]
        versions.append(item)
    manifest = {
        "format": 1,
        "mode": "static-showcase",
        "revision": revision,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "versions": versions,
    }
    catalog_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    _write(output / "assets" / "catalog.json", catalog_bytes)
    health = {
        "ok": True,
        "mode": "static-showcase",
        "revision": revision,
        "versions": len(versions),
    }
    _write(output / "healthz", json.dumps(health, ensure_ascii=False).encode("utf-8"))
    precompress(output)
    shutil.rmtree(output / "posters", ignore_errors=True)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=Path("/tmp/forma-showcase-site"))
    parser.add_argument("--revision", default=os.environ.get("FORMA_REVISION", "local"))
    args = parser.parse_args()
    manifest = build_site(args.repo_root.resolve(), args.output, args.revision)
    models = sum(len(version["models"]) for version in manifest["versions"])
    print(f"Static showcase ready: {len(manifest['versions'])} versions, {models} models at {args.output}")


if __name__ == "__main__":
    main()
