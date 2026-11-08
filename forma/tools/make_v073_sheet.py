from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from forma.run import build
from forma.model import Solid
from forma.render import render_views

parts = [
    ("Габарит = size: 70, а не 84", "к = face_box size=[70,70,70] mode=выпуклый profile=линза faces=все relief=7 margin=8"),
    ("Рельеф со смещением", "к = face_box size=[70,70,50] mode=вогнутый profile=квадрат faces=верх relief=8 margin=10 offset=[6,0]"),
    ("Глухое гнездо", "к = cube_hole size=[50,50,40] hole=18 depth=16"),
    ("Полость в наклонном блоке", "к = box size=[90,70,55] top_size=[74,58] wall=4"),
]
solids = []
for index, (_caption, script) in enumerate(parts):
    result = build(script, analyze_model=False)
    assert result.ok, (_caption, result.error)
    obj = result.scene.all_solids()[-1]
    solids.append(Solid(name=f"p{index}", manifold=obj.manifold.translate((index * 115.0, 0.0, 0.0)),
                        color='#cdd6e6', metal=0.05, rough=0.45))
out = Path('renders/v073_sheet')
res = render_views(solids, str(out), prefix='v073', size=1200, ss=2, views=('iso',), combined=False)
image = Image.open(res['files'][0]['path']).convert('RGB')
draw = ImageDraw.Draw(image)
font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 21)
bold = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 34)
draw.text((36, 30), 'Форма 3D 0.73 — исправления и новые параметры', font=bold, fill=(235, 240, 250))
width = image.width
for index, (caption, _script) in enumerate(parts):
    x = int(width * (index + 0.5) / len(parts))
    tw = draw.textlength(caption, font=font)
    left = max(16, min(x - tw / 2, width - tw - 16))
    draw.text((left, image.height - 62), caption, font=font, fill=(205, 214, 230))
final = Path('docs/v073_sheet.png')
image.save(final)
print(final, image.size)
