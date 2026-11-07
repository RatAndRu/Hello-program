"""Лист-превью №2: изометрия + торцы + разрез отверстия + вид спереди.

Собирает forma/docs/coupling/proposal_v2.png из iso_cpi20p.png и анкоров
iso_anchors.json (их пишет make_preview_iso.py).
"""
import json
import math
from PIL import Image, ImageDraw, ImageFont

BASE = 'forma/docs/coupling/'
W, H = 1700, 1470

img = Image.new('RGB', (W, H), '#f7f6f2')
d = ImageDraw.Draw(img)

F = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
f12 = ImageFont.truetype(F, 17); f11 = ImageFont.truetype(F, 15)
fsm = ImageFont.truetype(F, 14); fsmb = ImageFont.truetype(FB, 15)
fb = ImageFont.truetype(FB, 25); fh = ImageFont.truetype(FB, 18)
INK = (32, 34, 38); BLUE = (30, 90, 170); GREY = (122, 127, 133); RED = (186, 58, 48)


def text(x, y, s, font=f12, fill=INK, anchor='la'):
    d.text((x, y), s, font=font, fill=fill, anchor=anchor)


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


def leader(p_from, p_to, label, anchor='la', font=fsm, color=INK, dy=-9):
    line(p_from, p_to, GREY, 1)
    d.ellipse([p_from[0] - 3, p_from[1] - 3, p_from[0] + 3, p_from[1] + 3], fill=color)
    text(p_to[0], p_to[1] + dy, label, font, color, anchor=anchor)


def dim_h(x1, x2, y, label, color=BLUE):
    line((x1, y), (x2, y), color, 2)
    for x, e in ((x1, 1), (x2, -1)):
        line((x, y - 6), (x, y + 6), color, 2)
        d.polygon([(x, y), (x + 8 * e, y - 4), (x + 8 * e, y + 4)], fill=color)
    text((x1 + x2) / 2, y - 28, label, f12, color, anchor='ma')


def dim_v(y1, y2, x, label, color=BLUE):
    line((x, y1), (x, y2), color, 2)
    for y in (y1, y2):
        line((x - 6, y), (x + 6, y), color, 2)
    d.polygon([(x, y1), (x, y1 - 8), (x + 7, y1)], fill=color)
    d.polygon([(x, y2), (x, y2 + 8), (x + 7, y2)], fill=color)
    text(x + 14, (y1 + y2) / 2, label, f12, color, anchor='lm')


# ------------------------------------------------------------------ шапка
text(36, 18, 'МУФТА CPI-20P-8x8 — превью №2: изометрия и разрез', fb)
text(36, 52, 'Изометрия — эскиз моего понимания детали, а не финальная модель. '
             'Справа — торцы и разрез отверстия, слева снизу — вид спереди.', f12, GREY)

# ------------------------------------------------------------------ изометрия
ISO_SC = 0.775
iso = Image.open(BASE + 'iso_cpi20p.png').convert('RGB')
iso = iso.resize((int(iso.width * ISO_SC), int(iso.height * ISO_SC)), Image.LANCZOS)
IX, IY = 16, 86
img.paste(iso, (IX, IY))
A = json.load(open(BASE + 'iso_anchors.json', encoding='utf-8'))


def ap(key):
    x, y = A[key][0], A[key][1]
    return (IX + x * ISO_SC, IY + y * ISO_SC)


leader(ap('exit_238'), (60, 112), 'узкий выход того же\nотверстия', anchor='la')
leader(ap('mouth_202'), (556, 108), 'гнездо B: шестигранник,\nстенки ровные', anchor='la')
leader(ap('cut_mid'), (700, 322), '6 этажей надрезов:\nплоскости ⊥ оси,\nперемычки через один', anchor='la')
leader(ap('mouth_56'), (40, 686), 'гнездо A: у дна резьба,\nдальше узкий проход', anchor='la')
leader(ap('slit'), (40, 748), 'продольный пропил\nступицы A (180°)', anchor='la')
leader(ap('end_far'), (700, 762), 'торец A: Ø8 и пропил', anchor='la')

# ------------------------------------------------------------------ торцы
R = 70
for cx, cy, t1, t2, holes, slit_ang in [
    (1166, 318, 'СТУПИЦА A', 'отверстия в вертикальной плоскости',
     [(90, 'big', 2.0), (270, 'small', 5.6)], 180),
    (1476, 318, 'СТУПИЦА B', 'в горизонтальной, ⊥ плоскости A',
     [(0, 'big', 20.2), (180, 'small', 23.8)], 270),
]:
    text(cx, cy - R - 44, t1, f12, INK, anchor='ma')
    text(cx, cy - R - 24, t2, fsm, GREY, anchor='ma')
    circ(cx, cy, R, outline=INK, w=2)
    circ(cx, cy, R * 0.4, outline=INK, w=2)
    a = math.radians(slit_ang)
    line((cx + R * 0.4 * math.cos(a), cy - R * 0.4 * math.sin(a)),
         (cx + R * math.cos(a), cy - R * math.sin(a)), INK, 3)
    for ang, kind, _z in holes:
        aa = math.radians(ang)
        hx, hy = cx + R * 0.72 * math.cos(aa), cy - R * 0.72 * math.sin(aa)
        if kind == 'big':
            circ(hx, hy, 11, fill=(74, 80, 86), outline=INK, w=2)
            d.regular_polygon((hx, hy, 7.2), 6, fill=(40, 45, 50))
        else:
            circ(hx, hy, 5.5, fill=(56, 62, 68), outline=INK, w=1)
    line((cx - R - 22, cy), (cx + R + 22, cy), GREY, 1, dash=7)

text(1321, 408, 'Плоскости отверстий A и B перпендикулярны', f11, BLUE, anchor='ma')
text(1321, 428, 'шестиугольник — гнездо, точка — узкий выход того же отверстия',
     fsm, GREY, anchor='ma')

# ------------------------------------------------------------------ разрез
text(1080, 470, 'РАЗРЕЗ ПО ОСИ ОТВЕРСТИЯ', fh, GREY)
S3 = 11.0
sx, sy = 1080, 506
lw, lh = 26 * S3, 20 * S3
mat = (226, 231, 234)
d.rectangle([sx, sy, sx + lw, sy + lh], fill=mat, outline=INK, width=2)
bore_top = sy + (10 - 4) * S3
bore_bot = sy + (10 + 4) * S3
d.rectangle([sx, bore_top, sx + lw, bore_bot], fill=(250, 250, 250), outline=INK, width=1)
zh = 5.6
hx = sx + zh * S3
hexw = 6.0 * S3
d.rectangle([hx - hexw / 2, sy, hx + hexw / 2, sy + 4.6 * S3], fill=(120, 127, 133), outline=INK)
for k in range(4):
    yy = sy + (4.9 + 0.55 * k) * S3
    d.rectangle([hx - 1.3 * S3, yy, hx + 1.3 * S3, yy + 0.45 * S3], fill=(150, 156, 162), outline=INK)
d.rectangle([hx - 1.1 * S3, sy + 4.6 * S3, hx + 1.1 * S3, bore_top], fill=(246, 246, 246), outline=INK, width=1)
d.rectangle([hx - 1.1 * S3, bore_top, hx + 1.1 * S3, sy + lh], fill=(246, 246, 246), outline=INK, width=1)
line((hx - 1.1 * S3, bore_bot), (hx + 1.1 * S3, bore_bot), INK, 1)

leader((hx + hexw / 2, sy + 2.2 * S3), (sx + lw + 28, sy + 2.0 * S3), 'гнездо 5,5 мм: стенки ровные', anchor='la')
leader((hx + 1.3 * S3, sy + 5.6 * S3), (sx + lw + 28, sy + 5.4 * S3), 'резьба M2,5', anchor='la')
leader((hx + 1.1 * S3, sy + 10.5 * S3), (sx + lw + 28, sy + 8.6 * S3), 'узкий проход Ø2,2 через вал', anchor='la')
leader((hx + 1.1 * S3, sy + 17.0 * S3), (sx + lw + 28, sy + 15.4 * S3), 'выход с другой стороны —\nмаленькое отверстие', anchor='la')
dim_h(sx + 2 * S3, sx + 24 * S3, sy + lh + 34, 'L = 26')
dim_v(sy, sy + lh, sx - 26, 'D = 20')

# ------------------------------------------------------------------ вид спереди
text(60, 846, 'ВИД СПЕРЕДИ: 6 этажей, перемычки через один', fh, GREY)
S2 = 12.0
FX, FY = 60, 1160
Dm, Lm, L1m = 20.0, 26.0, 7.5
band = Lm - 2 * L1m
pitch = band / 6


def X(mm): return FX + mm * S2
def Y(mm): return FY - mm * S2


d.rectangle([X(0), Y(Dm), X(Lm), Y(0)], outline=INK, width=3)
line((X(-2), Y(Dm / 2)), (X(Lm + 2), Y(Dm / 2)), GREY, 1, dash=9)
bridge_up = True
for i in range(6):
    zc = L1m + (i + 0.5) * pitch
    if bridge_up:
        line((X(zc), Y(Dm)), (X(zc), Y(2.2)), INK, 2)     # перемычка внизу
        line((X(zc - 0.3), Y(Dm)), (X(zc + 0.3), Y(Dm)), INK, 4)
    else:
        line((X(zc), Y(0)), (X(zc), Y(Dm - 2.2)), INK, 2)  # перемычка сверху
        line((X(zc - 0.3), Y(0)), (X(zc + 0.3), Y(0)), INK, 4)
    bridge_up = not bridge_up
line((X(0), Y(13.0)), (X(L1m), Y(13.0)), INK, 3)
line((X(Lm - L1m), Y(7.0)), (X(Lm), Y(7.0)), INK, 3)
text(X(1.0), Y(13.0) - 24, 'пропил A', fsm, GREY, anchor='la')
text(X(Lm - 1.0), Y(7.0) + 20, 'пропил B', fsm, GREY, anchor='ra')
dim_h(X(0), X(Lm), FY + 56, 'L = 26')
dim_h(X(0), X(L1m), FY + 104, 'L1 = 7,5')
dim_h(X(Lm - L1m), X(Lm), FY + 104, 'L1 = 7,5')
dim_v(Y(Dm), Y(0), X(Lm) + 60, 'D = 20')
text(60, FY + 150, f'шаг {pitch:.2f} мм, ширина надреза 0,55 мм, дуга 270°, перемычка 90°'.replace('.', ','), fsm, GREY)
text(60, FY + 172, 'у соседних перемычка с другой стороны — на кромке это «диагональ»', fsm, GREY)

# ------------------------------------------------------------------ правки
NX = 780
text(NX, 846, 'Что поправил по твоим замечаниям', fb)
items = [
 '1) Надрез — через весь диаметр (а не «радиусом»), у соседних перемычка с другой стороны.',
 '2) Этажей шесть, перемычки через один: сверху / снизу, в шахматку.',
 '3) Отверстий четыре, все сквозные: гнездо → резьба → узкий выход с другой стороны.',
 '4) Внутри гнезда шестигранник по всей длине, стенки ровные; у дна — резьба.',
 '5) Отверстия ступицы A в одной плоскости, ступицы B — в перпендикулярной.',
 '6) Продольные пропилы — по одному на ступицу, с разных сторон (A 180°, B 270°).',
]
for i, s in enumerate(items):
    text(NX, 888 + i * 27, s, f12)

text(NX, 1076, 'Что уточнить перед сборкой', fb)
qs = [
 '1) Шаг 1,83 мм при 6 надрезах — или другая разбивка пояса 11 мм?',
 '2) Дуга 270°, перемычка 90° — или надрез идёт ещё дальше?',
 '3) Гнездо: шестигранник 5,5 мм, глубина 4,6 мм — верно?',
 '4) Узкий проход Ø2,2 — и он выходит с другой стороны снаружи?',
 '5) Углы отверстий: A = 90° и 270°, B = 0° и 180° — так?',
]
for i, s in enumerate(qs):
    text(NX, 1118 + i * 27, s, f12, BLUE)

# ------------------------------------------------------------------ варианты надреза
VY = 1268
text(NX, VY, 'Два чтения «полного надреза» — выбери', fb)
for k, (cx, title, sub) in enumerate([
    (NX + 120, 'А — как нарисовано', 'дуга 270°, перемычка 90°'),
    (NX + 380, 'Б — насквозь', 'плоскость через ось, наискось'),
]):
    cy = VY + 78
    circ(cx, cy, 38, outline=INK, w=2)
    circ(cx, cy, 15, outline=INK, w=2)
    if k == 0:
        # дуга 270° — разрыв сверху справа
        d.arc([cx - 38, cy - 38, cx + 38, cy + 38], start=-50, end=215, fill=INK, width=5)
        d.arc([cx - 15, cy - 15, cx + 15, cy + 15], start=-50, end=215, fill=INK, width=3)
    else:
        line((cx - 27, cy + 27), (cx + 27, cy - 27), INK, 5)
        line((cx - 11, cy + 11), (cx + 11, cy - 11), (250, 250, 250), 9)
        line((cx - 11, cy + 11), (cx + 11, cy - 11), INK, 3)
    text(cx, VY + 132, title, fsm, INK, anchor='ma')
    text(cx, VY + 150, sub, fsm, GREY, anchor='ma')

text(36, H - 26, 'Превью, не рабочий чертёж · Ø20, L 26, L1 7,5 — заводская таблица CPI-20P(C) · '
                 'прочее — по фото и твоим правкам', fsm, GREY)

img.save(BASE + 'proposal_v2.png')
print('saved proposal_v2.png', img.size)
