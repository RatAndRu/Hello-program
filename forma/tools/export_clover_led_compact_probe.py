"""Export monochrome diagnostic meshes for the compact clover slicing study.

NOT print-ready: the coloured face is deliberately fused for an occupancy-only
slice, and the experimental lid/button have not been fitted to real hardware.
This tool writes only to an explicitly requested directory.
"""
from __future__ import annotations

import argparse
from copy import copy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forma.geometry import export_stl  # noqa: E402
from forma.run import build  # noqa: E402
from make_clover_led_compact_print_layout import (  # noqa: E402
    LAYOUT, SCENE, layout_content,
)

PARTS = {
    "body": "на_столе_корпус_клевера",
    "lid": "на_столе_крышка",
    "button": "на_столе_кнопка",
}
LEAVES = tuple(f"на_столе_лист_{d}" for d in ("верх", "право", "низ", "лево"))


def probe_meshes():
    expected = layout_content(SCENE.read_text(encoding="utf-8"))
    if LAYOUT.read_text(encoding="utf-8") != expected:
        raise ValueError("Print layout is out of date; regenerate it first")
    result = build(expected, analyze_model=False)
    if not result.ok:
        raise ValueError(result.error)
    objects = {item.name: item for item in result.visible_solids()}
    expected_names = set(PARTS.values()) | set(LEAVES)
    if objects.keys() != expected_names:
        raise ValueError(f"Unexpected visible objects: {objects.keys() ^ expected_names}")

    body = copy(objects[PARTS["body"]])
    for name in LEAVES:
        body.manifold += objects[name].manifold
    # Exactly coincident colour boundaries can leave zero-volume shells in a
    # Boolean union. Do not silently discard a real component.
    components = body.manifold.decompose()
    main = max(components, key=lambda part: part.volume())
    discarded_volume = sum(abs(part.volume()) for part in components if part is not main)
    if discarded_volume > 1e-6:
        raise ValueError(f"Unexpected disconnected material: {discarded_volume} mm³")
    body.manifold = main
    return {"body": body, "lid": objects[PARTS["lid"]], "button": objects[PARTS["button"]]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="directory for temporary probe meshes")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "NOT_FOR_PRINTING.txt").write_text(
        "DIAGNOSTIC GEOMETRY ONLY. NOT FOR PRINTING OR USE.\n"
        "The five face/body materials are fused into one monochrome mesh.\n"
        "The lid, button, hardware fits and safety remain unverified.\n", encoding="utf-8")
    for name, obj in probe_meshes().items():
        path = args.output / f"compact_{name}_probe.stl"
        path.write_bytes(export_stl([obj]))
        print(f"Wrote {path}: {obj.manifold.volume():.3f} mm³")


if __name__ == "__main__":
    main()
