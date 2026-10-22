"""Быстрый просмотр примера: python tools/preview_example.py mug [вид] [размер]."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma.render import render_views  # noqa: E402
from forma.run import build  # noqa: E402


def main() -> int:
    key = sys.argv[1] if len(sys.argv) > 1 else "mug"
    view = sys.argv[2] if len(sys.argv) > 2 else "iso"
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 900
    script = (ROOT / "examples" / f"{key}.forma").read_text(encoding="utf-8")
    b = build(script)
    if not b.ok:
        print("ОШИБКА:", b.error)
        return 1
    out = Path("/tmp/preview")
    out.mkdir(exist_ok=True)
    info = render_views(b.visible_solids(), str(out), prefix=key, size=size, ss=2, views=(view,))
    print("готово:", info["files"][0]["path"])
    print(b.analysis["text"].split("\n\n")[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
