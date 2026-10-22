"""Открытие чужих файлов: GLB, GLTF, OBJ, STL, PLY, 3MF, OFF и .blend (через Blender)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from .errors import DslError, GeometryError
from .geometry import manifold_from_arrays
from .model import Solid
from .ops import op
from .paths import user_data_dir

SUPPORTED = (".glb", ".gltf", ".obj", ".stl", ".ply", ".3mf", ".off", ".dae")


def resolve_file(raw: str) -> Path:
    raw = (raw or "").strip().strip('"\'')
    if not raw:
        raise DslError("Укажите файл: import скульптура file=модель.glb")
    candidates = [Path(raw).expanduser()]
    candidates.append(user_data_dir() / "imports" / raw)
    candidates.append(user_data_dir() / "imports" / Path(raw).name)
    candidates.append(user_data_dir() / "exports" / Path(raw).name)
    for path in candidates:
        if path.exists():
            return path
    raise GeometryError(f"Файл не найден: {raw}",
                        hint="Перетащите файл в окно модели или положите его в папку "
                             "импорта (она показана в справке).")


def load_any(path: Path, scale: float | None = 1.0,
             repair: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Читает любой поддерживаемый файл в (вершины, грани) без внешних конвертеров."""
    suffix = path.suffix.lower()
    source = path
    temp = None
    if suffix == ".blend":
        from .blender import blend_to_glb
        source = Path(blend_to_glb(str(path)))
        suffix = ".glb"
        temp = source
    if suffix not in SUPPORTED:
        raise GeometryError(f"Формат «{suffix}» пока не поддерживается.",
                            hint="Поддерживается: GLB, GLTF, OBJ, STL, PLY, 3MF, DAE и .blend "
                                 "(если установлен Blender).")
    try:
        import trimesh
        loaded = trimesh.load(str(source), force=None)
    except Exception as exc:
        raise GeometryError(f"Не удалось прочитать файл: {exc}") from exc
    finally:
        if temp is not None:
            try:
                temp.unlink()
            except OSError:
                pass
    if hasattr(loaded, "dump"):
        try:
            merged = loaded.dump(concatenate=True)
        except Exception:
            merged = None
        if merged is None or not hasattr(merged, "faces") or len(merged.faces) == 0:
            parts = [g for g in getattr(loaded, "geometry", {}).values()
                     if hasattr(g, "faces") and len(g.faces) > 0]
            if not parts:
                raise GeometryError("В файле нет полигональной геометрии.")
            verts = []
            faces = []
            offset = 0
            for part in parts:
                verts.append(np.asarray(part.vertices, dtype=np.float64))
                faces.append(np.asarray(part.faces, dtype=np.int64) + offset)
                offset += len(part.vertices)
            v = np.vstack(verts)
            f = np.vstack(faces)
        else:
            v = np.asarray(merged.vertices, dtype=np.float64)
            f = np.asarray(merged.faces, dtype=np.int64)
    else:
        v = np.asarray(loaded.vertices, dtype=np.float64)
        f = np.asarray(loaded.faces, dtype=np.int64)
    # unit=auto раньше угадывал масштаб по размеру и ошибался в 100–1000 раз.
    # Теперь по умолчанию файл считается миллиметровым: масштаб меняется только
    # по явному указанию unit=cm|m|inch.
    # GLB/glTF хранят Y вверх (как Blender): возвращаем модель в Z-вверх,
    # иначе кружка после импорта лежит на боку.
    if path.suffix.lower() in {".glb", ".gltf"}:
        v = np.column_stack([v[:, 0], -v[:, 2], v[:, 1]])
    if scale is not None and abs(float(scale) - 1.0) > 1e-12:
        v = v * float(scale)
    if repair:
        volume_before = None
        try:
            import trimesh as _tm
            volume_before = float(_tm.Trimesh(vertices=v, faces=f, process=False).volume)
        except Exception:
            volume_before = None
        try:
            import trimesh
            mesh = trimesh.Trimesh(vertices=v, faces=f, process=True)
            if not mesh.is_watertight:
                trimesh.repair.fill_holes(mesh)
                trimesh.repair.fix_normals(mesh)
            if len(mesh.faces) and not mesh.is_watertight:
                # последняя попытка — воксельное перестроение (закрывает дыры)
                pitch = max(float(np.max(mesh.extents)) / 110.0, 0.2)
                vox = mesh.voxelized(pitch=pitch).fill()
                mesh = vox.marching_cubes
                trimesh.repair.fix_normals(mesh)
            v = np.asarray(mesh.vertices, dtype=np.float64)
            f = np.asarray(mesh.faces, dtype=np.int64)
            if volume_before:
                volume_after = float(mesh.volume)
                if abs(volume_after - volume_before) > 0.02 * abs(volume_before):
                    LIMITS.append(
                        f"починка сетки изменила объём на "
                        f"{(volume_after - volume_before) / volume_before * 100:+.1f} %")
        except Exception:
            pass
    return v, f


def weld_mesh(verts, faces):
    """Сваривает швы (вершины по месту) — свой GLB после экспорта снова замкнут."""
    try:
        import trimesh
        mesh = trimesh.Trimesh(vertices=np.asarray(verts, dtype=np.float64),
                               faces=np.asarray(faces, dtype=np.int64), process=True)
        if len(mesh.faces) == 0:
            return None
        return (np.asarray(mesh.vertices, dtype=np.float64),
                np.asarray(mesh.faces, dtype=np.int64))
    except Exception:
        return None


# Предупреждения последнего импорта (выводит команда import).
LIMITS: list[str] = []


@op("import", aliases=("импорт", "открыть", "open"), category="Сцена и материал",
    summary="Открывает чужой файл (GLB, OBJ, STL, PLY, 3MF и .blend при установленном Blender) "
            "и добавляет его объектом сцены.",
    example="скульптура = import file=модель.glb unit=auto",
    params={"target": "имя будущего объекта",
            "file": "путь к файлу (можно перетащить в окно)",
            "unit": "mm, cm, m, inch или auto (= мм, без догадок)",
            "scale": "дополнительный множитель", "repair": "починить сетку да/нет (по умолчанию нет)",
            "pos": "смещение [x, y, z]", "material": "материал для импорта"},
    positional=["target"])
def import_mesh(a, name):
    raw = a.text("file") or ""
    if not raw:
        raise DslError("Укажите файл.", hint="import скульптура file=модель.glb",
                       line=a.cmd.line, command=a.cmd.text)
    path = resolve_file(raw)
    unit = (a.text("unit") or "auto").strip().lower()
    factors = {"mm": 1.0, "мм": 1.0, "cm": 10.0, "см": 10.0, "m": 1000.0, "м": 1000.0,
               "inch": 25.4, "in": 25.4, "auto": 1.0, "авто": 1.0}
    if unit not in factors:
        raise DslError("Единицы: mm, cm, m, inch или auto.",
                       line=a.cmd.line, command=a.cmd.text)
    extra = float(a.num("scale", 1.0) or 1.0)
    base_scale = factors[unit]
    if unit in ("auto", "авто"):
        a.scene.log("info", "unit=auto: файл прочитан как миллиметровый "
                            "(уточните unit=cm|m|inch, если это не так)", a.cmd.line)
    repair = a.boolean("repair", False)
    LIMITS.clear()
    verts, faces = load_any(path, scale=base_scale * extra, repair=repair)
    for note in LIMITS:
        a.scene.log("warn", f"импорт: {note}; проверьте объём и стенки", a.cmd.line)
    pos = a.vec("pos", dims=3, default=[0.0, 0.0, 0.0])
    verts = verts + np.asarray(pos, dtype=np.float64)
    try:
        solid_mesh = manifold_from_arrays(verts, faces, what=f"импорт «{path.name}»")
    except GeometryError as exc:
        # Экспорт режет вершины по граням и нормалям, поэтому свой же GLB
        # после импорта выглядит незамкнутым. Сначала пробуем сварить швы.
        welded = weld_mesh(verts, faces)
        if welded is not None:
            try:
                solid_mesh = manifold_from_arrays(welded[0], welded[1],
                                                  what=f"импорт «{path.name}»")
                a.scene.log("info", "импорт: швы сварены (вершины совпали)", a.cmd.line)
                verts, faces = welded
            except GeometryError:
                solid_mesh = None
        if solid_mesh is None and not repair:
            raise GeometryError(
                f"Сетка файла «{path.name}» не герметична: {exc}",
                hint="Если форма важнее точности, добавьте repair=да — программа "
                     "закроет дыры, но объём может измениться. Или почините файл "
                     "в Blender.") from exc
        if solid_mesh is None:
            raise
    target = (a.text("target") or name or a.scene.auto_name("импорт")).strip() or "импорт"
    style = a.style()
    solid = Solid(name=a.scene.unique_name(target), manifold=solid_mesh,
                  color=style.get("color") or a.scene.next_color(),
                  metal=float(style.get("metal", 0.0)),
                  rough=float(style.get("rough", 0.45)),
                  density=float(style.get("density", 1.24)),
                  kind="import", op="import", line=a.cmd.line)
    a.scene.add(solid)
    a.scene.log("info", f"импорт {path.name}: {solid_mesh.num_tri()} треугольников", a.cmd.line)
    return solid
