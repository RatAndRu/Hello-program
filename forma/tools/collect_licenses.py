"""Собрать лицензии установленных при сборке пакетов и внешние уведомления.

Запускать ДО PyInstaller в той же Windows-среде. manifest описывает установленные
пакеты, включая сборочные, а не притворяется точным SBOM содержимого EXE.
"""
from __future__ import annotations

import importlib.metadata as metadata
import json
import platform
import shutil
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "build" / "third-party-licenses"
REQUIRED = ("numpy", "manifold3d", "trimesh", "pyfastnoiselite", "pywebview",
            "pythonnet", "clr-loader", "cffi", "pycparser", "proxy-tools",
            "bottle", "typing-extensions", "pyinstaller")
STATIC = ("FastNoiseLite-MIT.txt", "PyFastNoiseLite-0.0.7-MIT.txt", "Python-3.12.10.txt",
          "Microsoft-WebView2-SDK.txt", "NVIDIA-FXAA-BSD.txt", "proxy-tools-BSD.txt",
          "symbol-es6-MIT.txt", "domJSON-MIT.txt", "Native-Promise-Only-MIT.txt")


def collect(output: Path = OUTPUT):
    output = Path(output)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    entries = []
    installed = sorted(metadata.distributions(), key=lambda d: (d.metadata.get("Name") or "").lower())
    names = {str(d.metadata.get("Name") or "").lower().replace("_", "-") for d in installed}
    if sys.platform == "win32":
        missing = set(REQUIRED) - names
        if missing:
            raise RuntimeError(f"Отсутствуют пакеты сборки: {sorted(missing)}")
    for dist in installed:
        name = str(dist.metadata.get("Name") or "unknown")
        version = dist.version
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in f"{name}-{version}")
        directory = output / "packages" / safe
        directory.mkdir(parents=True, exist_ok=True)
        raw = dist.read_text("METADATA") or dist.read_text("PKG-INFO") or ""
        (directory / "METADATA.txt").write_text(raw, encoding="utf-8")
        copied = []
        for item in dist.files or ():
            if not any(key in item.name.lower() for key in ("license", "licence", "copying", "notice")):
                continue
            src = Path(dist.locate_file(item))
            if not src.is_file():
                continue
            # Плоское имя сохраняет путь как текст: фильтр PyInstaller не удалит
            # лицензии из numpy/.../include и одноимённые файлы не перезапишутся.
            target = str(item).replace("\\", "__").replace("/", "__")
            shutil.copyfile(src, directory / target)
            copied.append(target)
        entries.append({"name": name, "version": version,
                        "license_expression": dist.metadata.get("License-Expression"),
                        "license_classifiers": [x for x in (dist.metadata.get_all("Classifier") or [])
                                                if x.startswith("License ::")],
                        "license_files": copied, "metadata": f"packages/{safe}/METADATA.txt"})
    static = output / "vendor"
    static.mkdir()
    for filename in STATIC:
        shutil.copyfile(ROOT / "docs" / "licenses" / filename, static / filename)
    shutil.copyfile(ROOT / "web" / "vendor" / "THREE_LICENSE.txt", static / "THREE_LICENSE.txt")
    shutil.copyfile(ROOT / "examples" / "assets" / "human_skeleton.LICENSE.txt", static / "human_skeleton.LICENSE.txt")
    # pywebview несёт отдельные JS-полифиллы со своими copyright-заголовками.
    try:
        import webview
        for name in ("dom_json.js", "polyfill.js"):
            source = Path(webview.__file__).parent / "js" / "lib" / name
            if source.is_file():
                shutil.copyfile(source, static / ("pywebview-" + name + ".txt"))
    except ImportError:
        pass
    # Точный файл лицензии интерпретатора из установленного Python, если он есть.
    candidates = (Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_path("stdlib")) / "LICENSE.txt")
    python_license = next((p for p in candidates if p.is_file()), None)
    if python_license:
        shutil.copyfile(python_license, static / "Python-installed-LICENSE.txt")
    manifest = {"format": "forma.build-license-inventory.v1", "scope": "installed build environment, not exact EXE SBOM",
                "python": sys.version, "platform": platform.platform(),
                "python_installed_license_copied": bool(python_license),
                "packages": entries,
                "notes": ["Proxy-tools metadata says MIT but its source says BSD; the upstream BSD notice is included.",
                          "Human skeleton is CC BY-SA 4.0 and contains CC BY 4.0 components.",
                          "NumPy's bundled native components are described in its wheel LICENSE.txt.",
                          "Installed packages include build-time packages; license inventory is not a legal clearance."]}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(ROOT / "docs" / "license_audit_0765.md", output / "ПРОЧИТАЙТЕ_ЛИЦЕНЗИИ.md")
    print("Лицензии:", output, "; установленных пакетов:", len(entries), flush=True)
    return manifest


if __name__ == "__main__":
    collect()
