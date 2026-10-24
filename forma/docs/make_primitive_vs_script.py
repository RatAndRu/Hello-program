"""Сравнение «вызов примитива» против ручной сборки тем же сценарием.

Три пары: сердце, кручёная верёвка, семисегментный индикатор «21:38».
Ручная сборка сделана добросовестно — с подгонкой размеров и `fuse`, — но
она всё равно длиннее, тяжелее по числу треугольников и даёт худшую форму.

Запуск из каталога forma/:

    PYTHONPATH=. python docs/make_primitive_vs_script.py

Результат: docs/primitive_vs_script_023.png — лист 2 × 3 с подписями
(строки, символы, треугольники, тела и совпадение силуэта с примитивом).
"""
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from forma.run import build
from forma.render import _prepare, _render_view
from forma.geometry import write_png

ROOT = Path(__file__).resolve().parent
FONTS = Path("/usr/share/fonts/truetype/dejavu")


def _font(name: str, size: int):
    # PIL без TTF не рисует кириллицу — подписи только через truetype
    return ImageFont.truetype(str(FONTS / name), size)


F_TITLE = _font("DejaVuSans-Bold.ttf", 23)
F_TEXT = _font("DejaVuSans.ttf", 17)
F_SMALL = _font("DejaVuSans.ttf", 15)


def info(b):
    tris = bodies = genus = 0
    vol = 0.0
    for o in b.scene.objects.values():
        if not o.visible:
            continue
        m = o.manifold
        tris += m.num_tri()
        bodies += len(m.decompose())
        genus += m.genus()
        vol += m.volume() / 1000.0
    return dict(tris=tris, bodies=bodies, genus=genus, vol=vol)


def measure(script, label):
    t = time.time()
    b = build(script, analyze_model=False)
    dt = time.time() - t
    if b is None or b.scene is None:
        raise SystemExit(f"{label}: {b.error}")
    d = info(b)
    d.update(time=dt, lines=len([l for l in script.splitlines() if l.strip()]),
             chars=len(script.replace("\n", "").replace("  ", " ")), build=b, script=script)
    print(f"{label:32s} {d['lines']:3d} стр. {d['chars']:6d} симв. {d['time']:6.3f} с "
          f"{d['tris']:7d} трис {d['bodies']:3d} тел род {d['genus']:3d} объём {d['vol']:7.1f}")
    return d


def shot(scene, px=532, ss=2, view="iso", pad=1.12):
    for o in scene.objects.values():
        o.color, o.metal, o.rough = "#cfd3da", 0.0, 0.45
    meshes = _prepare([o for o in scene.objects.values() if o.visible])
    v = np.concatenate([m["verts"] for m in meshes])
    lo, hi = v.min(0), v.max(0)
    c = (lo + hi) / 2.0
    r = float(np.linalg.norm(hi - lo)) / 2.0 * pad
    img, _ = _render_view(meshes, c, r, view, px, ss, [*lo, *hi], grid=False,
                          shadow=False, bg=(0.043, 0.047, 0.055))
    p = ROOT / "_tile.png"
    write_png(p, (np.clip(img, 0, 1) * 255).astype(np.uint8))
    return Image.open(p).convert("RGB")


def silhouette(b):
    cs = None
    for o in b.scene.objects.values():
        if not o.visible:
            continue
        p = o.manifold.project()
        cs = p if cs is None else cs + p
    return cs


def iou(a, b):
    A, B = silhouette(a), silhouette(b)
    return (A ^ B).area() / max((A + B).area(), 1e-9) * 100.0


def fmt(n):
    return f"{n:,}".replace(",", " ")


# ---------------------------------------------------------------- сердце
HEART_P = "сердце = heart width=72 depth=20 round=3"
HEART_S = """л = sphere radius=19 at=[-18,11,10]
п = sphere radius=19 at=[18,11,10]
л = scale [л] factor=[1,1,0.53] pivot=[-18,11,10]
п = scale [п] factor=[1,1,0.53] pivot=[18,11,10]
к = prism sides=3 30 20
к = rotate [к] angle=270 axis=z
к = translate [к] offset=[0,-6,0]
h = fuse [л,п,к] radius=2"""

# ---------------------------------------------------------------- верёвка
ROPE_P = "канат = rope length=150 diameter=26 strands=3"


def rope_script(length=150.0, diameter=26.0, strands=3, n=150, wire=None):
    sn = math.sin(math.pi / strands)
    wire = diameter * sn / (1.0 + sn) * 1.08 if wire is None else wire
    R = (diameter - wire) / 2.0
    pitch = diameter * 2.5
    lines = []
    for s in range(strands):
        pts = []
        ph = 2 * math.pi * s / strands
        for i in range(n):
            t = i / (n - 1)
            ang = ph + 2 * math.pi * length * t / pitch
            pts.append([round(R * math.cos(ang), 2), round(R * math.sin(ang), 2),
                        round(length * t, 2)])
        body = ",".join(f"[{p[0]},{p[1]},{p[2]}]" for p in pts)
        lines.append(f"нить{s+1} = sweep path=[{body}] radius={wire/2:.2f} sides=10 smooth=0")
    return "\n".join(lines)


# ---------------------------------------------------------------- индикатор
SEG_P = 'цифры = seven_seg text="21:38" height=54 depth=2'


def seg_script(text="21:38", h=54.0, depth=2.0):
    """Ручная сборка индикатора прямоугольниками — та же раскладка, что у примитива."""
    w, t = h * 0.58, h * 0.15
    gap = h * 0.32
    on = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
          "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}

    def cw(ch):
        return w * 0.34 if ch == ":" else (w * 0.45 if ch == " " else w)

    total = sum(cw(c) for c in text) + gap * max(0, len(text) - 1)
    x = -total / 2.0
    lines = []
    off = t * 0.28
    vlen = h / 2 - t * 0.7
    for ch in text:
        cx = x + cw(ch) / 2.0
        if ch == ":":
            r = t * 0.55
            for cy in (h * 0.22, -h * 0.22):
                lines.append(f"с{len(lines)} = cylinder radius={r:.2f} height={depth:g} at=[{cx:.1f},{cy:.1f},0]")
        else:
            for sg in on[ch]:
                if sg in "agd":
                    sx, sy = w - off, t
                    cy = h / 2 - t / 2 if sg == "a" else (-h / 2 + t / 2 if sg == "d" else 0.0)
                    px_ = cx
                else:
                    sx, sy = t, vlen
                    px_ = cx - w / 2 + t / 2 if sg in "fe" else cx + w / 2 - t / 2
                    cy = h / 4 if sg in "fb" else -h / 4
                lines.append(f"с{len(lines)} = box size=[{sx:.1f},{sy:.1f},{depth:g}] "
                             f"at=[{px_:.1f},{cy:.1f},0]")
        x += cw(ch) + gap
    return "\n".join(lines)


CASES = [
    ("Сердце", HEART_P, HEART_S),
    ("Верёвка", ROPE_P, rope_script()),
    ("Индикатор", SEG_P, seg_script()),
]
VIEWS_ROW = {"Индикатор": "top"}

rows = []
for name, sp, ss_ in CASES:
    a = measure(sp, name + " — примитив")
    b = measure(ss_, name + " — сценарий")
    rows.append((name, a, b))

# ---------------------------------------------------------------- лист
TILE = 532
CAP = 96
W, H = TILE * 2, (TILE + CAP) * len(rows)
sheet = Image.new("RGB", (W, H), (13, 15, 19))
dr = ImageDraw.Draw(sheet)
for r, (name, a, b) in enumerate(rows):
    y0 = r * (TILE + CAP)
    for c, d, title in ((0, a, f"{name} — вызов примитива"),
                        (1, b, f"{name} — сборка сценарием")):
        im = shot(d["build"].scene, view=VIEWS_ROW.get(name, "iso"))
        im = im.resize((TILE, TILE), Image.LANCZOS)
        sheet.paste(im, (c * TILE, y0))
        sub = f"{d['lines']} стр. · {fmt(d['chars'])} симв. · {fmt(d['tris'])} трис · {d['bodies']} тел"
        dr.text((c * TILE + 14, y0 + TILE + 6), title, font=F_TITLE, fill=(238, 240, 245))
        dr.text((c * TILE + 14, y0 + TILE + 42), sub, font=F_TEXT, fill=(150, 158, 172))
        if c == 1 and name in ("Сердце", "Индикатор"):
            dr.text((c * TILE + 14, y0 + TILE + 66),
                    f"силуэт совпал с примитивом: {iou(a['build'], b['build']):.0f} %",
                    font=F_SMALL, fill=(126, 134, 148))
        dr.line([(c * TILE, y0 + TILE), (c * TILE, y0 + TILE + CAP)], fill=(90, 96, 108))
        if c == 0:
            dr.line([(0, y0 + TILE + CAP - 1), (W, y0 + TILE + CAP - 1)], fill=(38, 42, 50))
out = ROOT / "primitive_vs_script_023.png"
sheet.save(out)
print("сохранено:", out, sheet.size)
(ROOT / "_tile.png").unlink(missing_ok=True)
