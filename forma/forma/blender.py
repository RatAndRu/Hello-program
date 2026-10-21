"""Мост к установленному Blender: чтение .blend и сохранение .blend.

Blender не входит в поставку (это сотни мегабайт), но если он установлен,
приложение находит его само и конвертирует файлы через командную строку.
Без Blender остаются открытые форматы: GLB, GLTF, OBJ, STL, PLY, 3MF.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .errors import GeometryError

_WINDOWS_HINTS = [
    r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
]
_MAC_HINTS = ["/Applications/Blender.app/Contents/MacOS/Blender"]


def find_blender() -> str | None:
    """Ищет blender в PATH и стандартных местах установки."""
    for name in ("blender", "Blender"):
        found = shutil.which(name)
        if found:
            return found
    hints = []
    if os.name == "nt":
        hints.extend(_WINDOWS_HINTS)
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            base = Path(root) / "Blender Foundation"
            if base.exists():
                for child in sorted(base.iterdir(), reverse=True):
                    exe = child / "blender.exe"
                    if exe.exists():
                        hints.append(str(exe))
    elif sys.platform == "darwin":
        hints.extend(_MAC_HINTS)
    for candidate in hints:
        if Path(candidate).exists():
            return candidate
    return None


def available() -> dict:
    exe = find_blender()
    return {"found": bool(exe), "path": exe or "",
            "hint": ("" if exe else
                     "Blender не найден. Установите Blender — и .blend будет "
                     "открываться и сохраняться автоматически, либо используйте GLB.")}


def _run(args: list[str], timeout: int = 240) -> None:
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise GeometryError("Blender не успел обработать файл за отведённое время.",
                            hint="Файл слишком тяжёлый или Blender завис.") from exc
    except OSError as exc:
        raise GeometryError(f"Не удалось запустить Blender: {exc}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")[-600:]
        raise GeometryError("Blender завершился с ошибкой.",
                            hint=tail.strip() or "Проверьте файл.")


def blend_to_glb(src: str, dst: str | None = None) -> str:
    """Конвертирует .blend в .glb (все видимые меши)."""
    exe = find_blender()
    if not exe:
        raise GeometryError("Открыть .blend можно только при установленном Blender.",
                            hint="Установите Blender (бесплатно, blender.org) — приложение "
                                 "найдёт его само. Или экспортируйте из Blender файл .glb.")
    src_path = Path(src)
    if not src_path.exists():
        raise GeometryError(f"Файл не найден: {src_path}")
    target = Path(dst) if dst else Path(tempfile.gettempdir()) / (src_path.stem + "_forma.glb")
    expr = (
        "import bpy, sys\n"
        f"bpy.ops.wm.open_mainfile(filepath=r'{src_path}')\n"
        "for obj in bpy.context.scene.objects:\n"
        "    obj.hide_set(False); obj.hide_select = False\n"
        "    try:\n"
        "        obj.hide_viewport = False\n"
        "    except Exception:\n"
        "        pass\n"
        f"bpy.ops.export_scene.gltf(filepath=r'{target}', export_format='GLB', "
        "export_apply=True, use_visible=True)\n"
    )
    _run([exe, "-b", "--factory-startup", "--python-expr", expr])
    if not target.exists():
        raise GeometryError("Blender не создал GLB. Возможно, в файле нет мешей.")
    return str(target)


def glb_to_blend(glb_path: str, dst: str) -> str:
    """Открывает GLB и сохраняет .blend (геометрия + материалы + анимация)."""
    exe = find_blender()
    if not exe:
        raise GeometryError("Сохранение .blend доступно при установленном Blender.",
                            hint="Установите Blender и повторите, либо экспортируйте GLB — "
                                 "Blender открывает его напрямую.")
    expr = (
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        f"bpy.ops.import_scene.gltf(filepath=r'{glb_path}')\n"
        f"bpy.ops.wm.save_as_mainfile(filepath=r'{dst}')\n"
    )
    _run([exe, "-b", "--factory-startup", "--python-expr", expr])
    if not Path(dst).exists():
        raise GeometryError("Blender не сохранил .blend.")
    return dst
