"""Генерирует version_info.txt для PyInstaller из forma/version.py."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.version import APP_TITLE, __version__  # noqa: E402

TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={nums},
    prodvers={nums},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('041904B0', [
        StringStruct('CompanyName', 'ФОРМА 3D'),
        StringStruct('FileDescription', '{title}'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'Forma3D'),
        StringStruct('LegalCopyright', 'ФОРМА 3D'),
        StringStruct('OriginalFilename', 'Forma3D.exe'),
        StringStruct('ProductName', 'ФОРМА 3D'),
        StringStruct('ProductVersion', '{version}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1049, 1200])])
  ]
)
"""


def main() -> int:
    parts = (__version__.split(".") + ["0", "0", "0"])[:3]
    nums = "(" + ", ".join(str(int(p)) for p in parts) + ", 0)"
    text = TEMPLATE.format(nums=nums, title=APP_TITLE, version=__version__)
    out = ROOT / "packaging" / "version_info.txt"
    out.write_text(text, encoding="utf-8")
    try:
        print(out)
    except Exception:
        print(str(out).encode("ascii", "replace").decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
