"""Проверка окружения перед сборкой EXE.

Пакеты OpenCV занимают больше половины веса сборки, поэтому важно, чтобы
стояла ровно одна обычная сборка (cv2.pyd ~68 МБ), а не contrib (~108 МБ).
Скрипт печатает ::notice::/:error:: — это единственный способ увидеть
подробности в анотациях CI.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # чтобы проверять и сам пакет airmouse
    sys.path.insert(0, str(ROOT))


def _installed_names() -> set[str]:
    try:
        import importlib.metadata as md
    except Exception:  # pragma: no cover
        return set()
    names = set()
    for dist in md.distributions():
        try:
            name = (dist.metadata["Name"] or "").lower()
        except Exception:
            continue
        if name:
            names.add(name)
    return names


def main() -> int:
    # airmouse обязательно первым: он ставит заглушку matplotlib, без которой
    # mediapipe.tasks.python.vision не импортируется (у него import matplotlib).
    import airmouse  # noqa: F401
    import cv2
    import mediapipe
    import numpy

    pkg_dir = pathlib.Path(cv2.__file__).parent
    pyd = pkg_dir / "cv2.pyd"
    if not pyd.exists():  # на Linux сборка не нужна, но скрипт не должен падать
        pyd = next(iter(sorted(pkg_dir.glob("cv2.*"))), None)  # type: ignore[arg-type]
    pyd_mb = pyd.stat().st_size / 1048576 if pyd is not None else 0.0

    print(f"cv2 {cv2.__version__} | mediapipe {mediapipe.__version__} | numpy {numpy.__version__}")
    print(f"::notice::версии: cv2 {cv2.__version__}, mediapipe {mediapipe.__version__}, numpy {numpy.__version__}")
    print(f"::notice::ядро OpenCV весит {pyd_mb:.1f} МБ ({pyd})")
    for dll in sorted(pkg_dir.glob("*.dll")):
        print(f"::notice::  {dll.name} = {dll.stat().st_size / 1048576:.1f} МБ")

    problems: list[str] = []
    if pyd_mb > 80:
        problems.append(
            f"ядро OpenCV весит {pyd_mb:.1f} МБ — установлена contrib-сборка, нужна обычная opencv-python"
        )

    # Тот же порядок импортов, что и в приложении: airmouse (ставит заглушку
    # matplotlib) -> mediapipe -> vision. Ловит поломки раньше PyInstaller.
    try:
        from mediapipe.tasks.python import vision

        if not (hasattr(vision, "HandLandmarker") and hasattr(vision, "FaceLandmarker")):
            problems.append("в mediapipe.tasks.python.vision нет HandLandmarker/FaceLandmarker")
        else:
            print("::notice::mediapipe vision импортируется (заглушка matplotlib работает)")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"импорт mediapipe vision упал: {type(exc).__name__}: {exc}")

    installed = _installed_names()
    if "opencv-contrib-python" in installed:
        problems.append("установлен opencv-contrib-python — он и даёт тяжёлое ядро OpenCV")
    for extra in ("matplotlib", "scipy", "pandas"):
        if extra in installed:
            print(f"::warning::установлен {extra} — в EXE он не попадает, но замедляет установку")

    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        return 1
    print("::notice::ядро OpenCV в порядке (обычная сборка)")
    return 0


if __name__ == "__main__":
    import traceback

    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - падение должно быть видно в аннотациях CI
        one_line = traceback.format_exc().strip().replace("\n", " | ")
        print(f"::error::проверка окружения упала: {one_line[:900]}")
        raise SystemExit(1)
