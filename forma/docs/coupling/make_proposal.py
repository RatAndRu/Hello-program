"""Чертёж-превью муфты CPI-20P-8x8 — схема компоновки на согласование.

Запуск:  /tmp/venv/bin/python forma/docs/coupling/make_proposal.py
Результат: forma/docs/coupling/proposal_cpi20p.png
Правится только этот файл; цифры ниже — из заводской таблицы CPI-20P(C).
"""
from PIL import Image, ImageDraw, ImageFont
import math

W, H = 1680, 1520
S = 15.0                      # px/мм для видов
img = Image.new('RGB', (W, H), '#f7f6f2')
d = ImageDraw.Draw(img)
F = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
f12 = ImageFont.truetype(F, 17); f11 = ImageFont.truetype(F, 15)
fsm = ImageFont.truetype(F, 14); fsmb = ImageFont.truetype(FB, 15)
fb = ImageFont.truetype(FB, 23); fh = ImageFont.truetype(FB, 18)
INK = (32, 34, 38); BLUE = (30, 90, 170); GREY = (128, 132, 138); RED = (190, 60, 50)


def line(p1, p2, fill=INK, w=2, dash=None):
    if not dash:
        d.line([p1, p2], fill=fill, width=w); return
    x1, y1 = p1; x2, y2 = p2
    L = math.hypot(x2 - x1, y2 - y1); n = max(1, int(L // dash))
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    for i in range(n):
        a = i * dash
        d.line([(x1 + ux * a, y1 + uy * a),
                (x1 + ux * (a + dash * 0.55), y1 + uy * (a + dash * 0.55))], fill=fill, width=w)


def circ(cx, cy, r, fill=None, outline=INK, w=2):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill, outline=outline, width=w)


def text(x, y, s, font=f12, fill=INK, anchor='la'):
    d.text((x, y), s, font=font, fill=fill, anchor=anchor)


def dim_h(x1, x2, y, label, color=BLUE):
    line((x1, y), (x2, y), color, 2)
    for x, e in ((x1, 1), (x2, -1)):
        line((x, y - 6), (x, y + 6), color, 2)
        d.polygon([(x, y), (x + 8 * e, y - 4), (x + 8 * e, y + 4)], fill=color)
    text((x1 + x2) / 2, y - 28, label, f12, color, anchor='ma')


def dim_v(y1, y2, x, label, color=BLUE, left=False):
    line((x, y1), (x, y2), color, 2)
    for y in (y1, y2):
        line((x - 6, y), (x + 6, y), color, 2)
    d.polygon([(x, y1), (x, y1 - 8), (x + 7, y1)], fill=color)
    d.polygon([(x, y2), (x, y2 + 8), (x + 7, y2)], fill=color)
    text(x - 14 if left else x + 14, (y1 + y2) / 2, label, f12, color,
         anchor='rm' if left else 'lm')


# --------------------------------------------------------------- параметры
D, L, L1 = 20.0, 26.0, 7.5
BAND = L - 2 * L1
NSLIT = 4
PITCH = BAND / (NSLIT + 1)
slit_w = 1.15
CIRC = math.pi * D
ARC = 270.0                      # дуга прорези
BRIDGE = 360.0 - ARC
holes = [(2.6, 80, 5.6, 'A'), (5.6, 250, 3.4, 'A'),
         (23.4, 100, 5.6, 'B'), (20.4, 260, 3.4, 'B')]
bridge_of = [90, 270, 90, 270]

text(40, 22, 'МУФТА INNOCONT CPI-20P-8x8 — чертёж-превью на согласование', fb)
text(40, 56, 'Схема компоновки, а не модель. Поправь любую цифру — пересоберу по ней.', f12, GREY)

# --------------------------------------------------------------- вид спереди
ox, y0 = 140, 520.0
def X(mm): return ox + mm * S
def Y(mm): return y0 - mm * S

text(ox, 104, 'ВИД СПЕРЕДИ', fh, GREY)
text(ox, 132, f'пояс {BAND:g} мм (z {L1:g}…{L - L1:g}): {NSLIT} поперечные прорези, '
              f'шаг {PITCH:.1f} мм, ширина {slit_w:g} мм'.replace('.', ','), f12, GREY)
text(ox, 156, f'перемычка ≈{BRIDGE:.0f}° — прорезь её не дорезает; '
              'у соседних перемычка с другой стороны', fsm, GREY)
d.rectangle([X(0), Y(D), X(L), Y(0)], outline=INK, width=3)
for zz in (L1, L - L1):
    line((X(zz), Y(D)), (X(zz), Y(0)), GREY, 1, dash=7)
line((X(-2), Y(D / 2)), (X(L + 2), Y(D / 2)), GREY, 1, dash=11)
yy = Y(D) - 18
line((X(L1), yy + 8), (X(L1), yy - 6), GREY, 1)
line((X(L - L1), yy + 8), (X(L - L1), yy - 6), GREY, 1)
line((X(L1), yy), (X(L - L1), yy), GREY, 1)
for i in range(NSLIT):
    zc = L1 + PITCH * (i + 1); z1, z2 = zc - slit_w / 2, zc + slit_w / 2; gap = 1.6
    if bridge_of[i] == 90:
        line((X(z1), Y(D)), (X(z1), Y(gap)), INK, 2)
        line((X(z2), Y(D)), (X(z2), Y(gap)), INK, 2)
        line((X(z1), Y(D)), (X(z2), Y(D)), INK, 4)
    else:
        line((X(z1), Y(D - gap)), (X(z1), Y(0)), INK, 2)
        line((X(z2), Y(D - gap)), (X(z2), Y(0)), INK, 2)
        line((X(z1), Y(0)), (X(z2), Y(0)), INK, 4)
line((X(0), Y(13.0)), (X(L1), Y(13.0)), INK, 3)
line((X(L - L1), Y(7.0)), (X(L), Y(7.0)), INK, 3)
circ(X(2.0), Y(15.0), 13, fill='#f7f6f2', outline=GREY, w=1)
text(X(2.0), Y(15.0) + 1, 'A', fsmb, GREY, anchor='mm')
circ(X(24.0), Y(9.0), 13, fill='#f7f6f2', outline=GREY, w=1)
text(X(24.0), Y(9.0) + 1, 'B', fsmb, GREY, anchor='mm')
dim_h(X(0), X(L), y0 + 72, 'L = 26')
dim_h(X(0), X(L1), y0 + 128, 'L1 = 7,5')
dim_h(X(L - L1), X(L), y0 + 128, 'L1 = 7,5')
dim_v(Y(D), Y(0), X(L) + 72, 'D = 20')

# --------------------------------------------------------------- торцы
R = D / 2 * S
for cx, cy, title, slit_ang, slit_lbl, hs in [
    (1000, 360, 'СТУПИЦА A  (низ, z = 0…7,5)', 180, 'прорезь A: 180°',
     [h for h in holes if h[3] == 'A']),
    (1400, 360, 'СТУПИЦА B  (верх, z = 18,5…26)', 0, 'прорезь B: 0°',
     [h for h in holes if h[3] == 'B']),
]:
    text(cx, cy - R - 70, title, f12, INK, anchor='ma')
    circ(cx, cy, R, outline=INK, w=3)
    circ(cx, cy, 4 * S, outline=INK, w=2)
    aa = math.radians(slit_ang)
    line((cx + 4 * S * math.cos(aa), cy - 4 * S * math.sin(aa)),
         (cx + R * math.cos(aa), cy - R * math.sin(aa)), INK, 3)
    lx, ly = cx + R * math.cos(aa), cy - R * math.sin(aa)
    text(lx + (8 if math.cos(aa) >= 0 else -8), ly + 22, slit_lbl, fsm, RED, anchor='ma')
    for z, ang, dia, tag in hs:
        a2 = math.radians(ang)
        line((cx, cy), (cx + R * 0.88 * math.cos(a2), cy - R * 0.88 * math.sin(a2)), RED, 1)
        hx, hy = cx + R * 0.62 * math.cos(a2), cy - R * 0.62 * math.sin(a2)
        circ(hx, hy, dia / 2 * S, outline=INK, w=2)
        circ(hx, hy, dia / 2 * S * 0.45, outline=INK, w=1)
        tx = hx + (56 if math.cos(a2) >= 0 else -56)
        text(tx, hy - 11, f'{ang}°', f11, RED, anchor='la' if math.cos(a2) >= 0 else 'ra')

# --------------------------------------------------------------- развёртка
U = 10.0
ux0, uy0 = 150, 1060
U0 = 45.0                        # шов развёртки, чтобы прорезь B не легла на кромку
CW = CIRC * U
def UX(deg): return ux0 + (((deg - U0) % 360) / 360) * CW
def UY(mm): return uy0 - mm * U

text(ux0, 740, 'РАЗВЁРТКА БОКОВОЙ ПОВЕРХНОСТИ — прорезь идёт дугой, а не кольцом', fh, GREY)
text(ux0, 766, 'разрывы в толстых линиях — перемычки ≈90°, у соседних строк сдвинуты на 180°',
     fsm, GREY)
d.rectangle([ux0, UY(L), ux0 + CW, UY(0)], outline=INK, width=3)
for zz in (L1, L - L1):
    line((ux0, UY(zz)), (ux0 + CW, UY(zz)), GREY, 1, dash=6)
for deg in (0, 90, 180, 270):
    x = UX(deg)
    line((x, UY(0)), (x, UY(-1.6)), INK, 2)
    text(x, UY(-2.6), '0° / 360°' if deg == 0 else f'{deg}°', fsm, GREY, anchor='ma')
for i in range(NSLIT):
    zc = L1 + PITCH * (i + 1)
    b = bridge_of[i]
    u1, u2 = UX((b + BRIDGE / 2) % 360), UX((b - BRIDGE / 2) % 360)
    if u2 > u1:
        segs = [(u1, u2)]
    else:
        segs = [(u1, ux0 + CW), (ux0, u2)]
    for s0, s1 in segs:
        d.rectangle([s0, UY(zc) - 4, s1, UY(zc) + 4], fill=INK)
    mx = (u1 + u2) / 2
    line((mx, UY(zc) - 3), (mx, UY(zc) + 3), '#f7f6f2', 1)
line((UX(180), UY(L1)), (UX(180), UY(0)), INK, 3)
line((UX(0), UY(L)), (UX(0), UY(L - L1)), INK, 3)
text(UX(180) + 9, UY(3.2), 'A', fsmb, GREY)
text(UX(0) - 20, UY(22.4), 'B', fsmb, GREY)
for z, ang, dia, tag in holes:
    hx, hy, r = UX(ang), UY(z), dia / 2 * U
    circ(hx, hy, r, outline=RED, w=2)
    lab = f'ø{dia}'.replace('.', ',') + ' ' + tag
    text(hx, hy - r - 20 if z > 13 else hy + r + 6, lab, fsm, RED, anchor='ma')
dim_h(ux0, ux0 + CW, UY(0) + 92, f'πD = {CIRC:.0f} мм'.replace('.', ','))
dim_v(UY(L), UY(0), ux0 - 46, 'L = 26', left=True)

# --------------------------------------------------------------- подписи
y = 1210
text(110, y, 'Как я теперь прочитал референсы', fb)
for i, s in enumerate([
    'Корпус — цилиндр Ø20 × 26, отверстие Ø8 насквозь, фаски 0,5 на торцах.',
    f'Пояс {BAND:g} мм разрезан {NSLIT} поперечными прорезями: плоскости строго ⊥ оси,'.replace('.', ','),
    f'наклона нет. Каждая — дуга ≈{ARC:.0f}°, перемычка ≈{BRIDGE:.0f}°, у соседней с другой стороны.',
    'Продольные прорези A и B — по одной на ступицу, с разных сторон.',
    'Винтов четыре: по два на ступицу, углы у A и B разные.',
    'Один винт в зенковке ø5,6 (утоплен), второй — обычное резьбовое M2.5.',
]):
    text(110, y + 38 + i * 27, s, f12)

text(980, y, 'Что подтвердить до сборки', fb)
for i, s in enumerate([
    f'1) Прорезей {NSLIT} при шаге {PITCH:.1f} мм — или 5?'.replace('.', ','),
    '2) Дуга 270° и перемычка 90° — или другие доли?',
    '3) Винтов 4 (по два на ступицу) — или больше?',
    '4) Углы: A = 80° и 250°, B = 100° и 260° — так?',
    '5) Продольные прорези: A на 180°, B на 0° — так?',
]):
    text(980, y + 38 + i * 27, s, f12, BLUE)

text(40, H - 30, 'Масштаб условный · схема для согласования · Ø20, L 26, L1 7,5, M2.5 — '
                  'из заводской таблицы CPI-20P(C)', fsm, GREY)
img.save('/home/user/Hello-program/forma/docs/coupling/proposal_cpi20p.png')
print('ok', img.size)
