#!/usr/bin/env python3
# Растеризация tmp/scene.json (его готовит scripts/preview.ts) — чтобы смотреть
# развёртки и сборки без браузера. Требуется pillow.
import json, math, sys
from PIL import Image, ImageDraw
SS = 2
data = json.load(open('tmp/scene.json'))

def draw(path, polys, bg, size, lines=()):
    W = int(size[0] * SS); H = int(size[1] * SS)
    img = Image.new('RGB', (W, H), bg)
    d = ImageDraw.Draw(img)
    for p in polys:
        pts = [(x[0]*SS, x[1]*SS) for x in p['pts']]
        if len(pts) >= 3:
            d.polygon(pts, fill=p['fill'], outline=None)
    for p in polys:
        pts = [(x[0]*SS, x[1]*SS) for x in p['pts']]
        if len(pts) >= 2:
            if p.get('dash'):
                # пунктир вручную
                (x0,y0),(x1,y1) = pts[0], pts[1]
                L = math.hypot(x1-x0, y1-y0); dash=p['dash'][0]*SS; gap=p['dash'][1]*SS
                t=0
                while t < L:
                    e=min(L,t+dash)
                    d.line([(x0+(x1-x0)*t/L,y0+(y1-y0)*t/L),(x0+(x1-x0)*e/L,y0+(y1-y0)*e/L)], fill=p['color'], width=max(1,int(p['w']*SS)))
                    t=e+gap
            else:
                d.line(pts, fill=p['stroke'] if 'stroke' in p else p['color'], width=max(1,int(p['w']*SS)))
    for ln in lines:
        pts = [(x[0]*SS, x[1]*SS) for x in ln['pts']]
        d.line(pts, fill=ln['color'], width=max(1,int(ln['w']*SS)))
    img = img.resize((int(size[0]), int(size[1])), Image.LANCZOS)
    img.save(path)

for i, part in enumerate(data):
    ns = part['netSize']
    lines = [p for p in part['net'] if 'color' in p]
    polys = [p for p in part['net'] if 'fill' in p]
    draw(f'tmp/net-{i}.png', polys, '#f4efe4', (ns['w'], ns['h']), lines)
    draw(f'tmp/sol-{i}.png', part['solid'], '#101318', (700, 700))
    print(i, part['name'], part['stats'])


# Композит для README: развёртка + сборка рядом
import os
os.makedirs('docs/images', exist_ok=True)
pairs = [(0, 'box'), (3, 'funnel'), (6, 'glass'), (4, 'pyramid')]
for idx, slug in pairs:
    if idx >= len(data):
        continue
    a = Image.open(f'tmp/net-{idx}.png').convert('RGB')
    # лист на рисунке обрезаем полями, чтобы он читался как бумага на подложке
    from PIL import ImageDraw as _D
    card = Image.new('RGB', (a.width + 24, a.height + 24), '#0d0f13')
    card.paste(a, (12, 12))
    d = _D.Draw(card)
    d.rectangle([12, 12, 12 + a.width - 1, 12 + a.height - 1], outline='#22262e')
    a = card
    b = Image.open(f'tmp/sol-{idx}.png').convert('RGB')
    h = max(a.height, b.height)
    W = a.width + b.width + 60
    out = Image.new('RGB', (W, h), '#0d0f13')
    out.paste(a, (20, (h - a.height) // 2))
    out.paste(b, (a.width + 40, (h - b.height) // 2))
    out.save(f'docs/images/{slug}.png')
    print('docs/images/%s.png' % slug)
