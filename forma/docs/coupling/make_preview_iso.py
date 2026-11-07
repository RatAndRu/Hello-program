"""Изометрия-превью муфты CPI-20P-8x8 по правкам пользователя.

Геометрия (см. вывод в конце): корпус Ø20x26, отверстие Ø8,
6 поперечных надрезов (плоскости ⊥ оси, дуга 270°, перемычки в шахматном
порядке — «сверху» и «снизу»), два продольных пропила ступиц,
4 сквозных ступенчатых отверстия (шестигранник → резьба → узкий выход),
плоскости отверстий верх/низ перпендикулярны.

Рендер: программный painter's algorithm на квадах, без внешних библиотек.
"""
import math
from PIL import Image, ImageDraw, ImageFont

OUT = 'forma/docs/coupling/iso_cpi20p.png'

# ------------------------------------------------------------------ параметры
D, L = 20.0, 26.0
R = D / 2
RB = 4.0                     # отверстие под вал Ø8
L1 = 7.5                     # ступица
BAND = L - 2 * L1            # 11 мм
NSLIT = 6
SLIT_W = 0.55
SLIT_SPAN = 270.0            # дуга надреза
BRIDGE_A = 45.0              # перемычка чётных
BRIDGE_B = 225.0             # перемычка нечётных (шахматка)

HEX_AF = 5.5                 # шестигранник «под ключ»
HEX_DEPTH = 5.0              # от наружной поверхности до дна гнезда
SMALL_R = 1.1                # узкий сквозной выход

# 4 сквозных ступенчатых отверстия: (z, угол большого гнезда)
# ступица A — вертикальная плоскость (90/270), ступица B — горизонтальная (0/180)
HOLES = [(2.0, 90.0), (5.6, 270.0), (20.2, 0.0), (23.8, 180.0)]
SLITS = [(180.0, 0.0, L1), (270.0, L - L1, L)]   # (угол, z0, z1)


def slit_bridge(i):
    return BRIDGE_A if i % 2 == 0 else BRIDGE_B


def slit_z(i):
    return L1 + (i + 0.5) * (BAND / NSLIT)


# ------------------------------------------------------------------ математика
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def norm(a):
    m = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / m, a[1] / m, a[2] / m)


# камера
CAM = norm((0.72, -0.62, 0.32))
VIEW = mul(CAM, -1.0)
RIGHT = norm(cross(VIEW, (0, 0, 1)))
UP = cross(RIGHT, VIEW)
LIGHT = norm(add(add(mul(CAM, 0.85), mul(RIGHT, 0.42)), mul(UP, 0.55)))

TILT = math.radians(-64.0)       # наклон оси на экране


def rot(p):
    """Повернуть модель, чтобы ось легла диагональю на экране."""
    x, y, z = p
    c, s = math.cos(TILT), math.sin(TILT)
    return (x * c + z * s, y, -x * s + z * c)


def shade(n, base):
    lam = max(0.0, dot(norm(rot(n)), LIGHT))
    k = 0.34 + 0.66 * lam
    return tuple(min(255, int(c * k)) for c in base)


BASE = (211, 217, 221)
BASE_IN = (88, 94, 100)      # стенки разрезов и отверстие — в тени
CUT_FACE = (146, 152, 158)


class Render:
    def __init__(self, w, h, scale, cx, cy):
        self.w, self.h, self.s, self.cx, self.cy = w, h, scale, cx, cy
        self.polys = []

    def proj(self, p):
        q = rot(p)
        x, y = dot(q, RIGHT), dot(q, UP)
        return (self.cx + x * self.s, self.cy - y * self.s, dot(q, VIEW))

    def quad(self, pts3, color):
        pp = [self.proj(p) for p in pts3]
        depth = sum(p[2] for p in pp) / len(pp)
        self.polys.append((depth, [(p[0], p[1]) for p in pp], color))

    def flush(self, draw):
        self.polys.sort(key=lambda t: -t[0])
        for _, pts, col in self.polys:
            draw.polygon(pts, fill=col)


def in_slit(z, phi):
    for ang, z0, z1 in SLITS:
        d = (phi - ang + 180) % 360 - 180
        if z0 <= z <= z1 and abs(d) < math.degrees((SLIT_W / 2) / R) * 1.02:
            return True
    return False


def in_cut(z, phi):
    for i in range(NSLIT):
        zi = slit_z(i)
        if abs(z - zi) <= SLIT_W / 2:
            b = slit_bridge(i)
            d = (phi - b + 180) % 360 - 180     # 0 = перемычка
            if abs(d) > (360 - SLIT_SPAN) / 2:
                return True
    return False


def build(rend):
    NPHI, NZ = 168, 200
    # наружная поверхность
    for iz in range(NZ):
        z0 = L * iz / NZ; z1 = L * (iz + 1) / NZ
        for j in range(NPHI):
            p0 = 360.0 * j / NPHI; p1 = 360.0 * (j + 1) / NPHI
            pm = 0.5 * (p0 + p1); zm = 0.5 * (z0 + z1)
            if in_cut(zm, pm) or in_slit(zm, pm):
                continue
            c = math.cos(math.radians(pm)); s = math.sin(math.radians(pm))
            n = (c, s, 0)
            rend.quad([(R * math.cos(math.radians(p0)), R * math.sin(math.radians(p0)), z0),
                       (R * math.cos(math.radians(p1)), R * math.sin(math.radians(p1)), z0),
                       (R * math.cos(math.radians(p1)), R * math.sin(math.radians(p1)), z1),
                       (R * math.cos(math.radians(p0)), R * math.sin(math.radians(p0)), z1)],
                      shade(n, BASE))
    # внутренняя поверхность отверстия
    for iz in range(0, NZ, 2):
        z0 = L * iz / NZ; z1 = L * (iz + 2) / NZ
        for j in range(0, NPHI, 2):
            p0 = 360.0 * j / NPHI; p1 = 360.0 * (j + 2) / NPHI
            pm = 0.5 * (p0 + p1)
            c = math.cos(math.radians(pm)); s = math.sin(math.radians(pm))
            rend.quad([(RB * math.cos(math.radians(p0)), RB * math.sin(math.radians(p0)), z0),
                       (RB * math.cos(math.radians(p1)), RB * math.sin(math.radians(p1)), z0),
                       (RB * math.cos(math.radians(p1)), RB * math.sin(math.radians(p1)), z1),
                       (RB * math.cos(math.radians(p0)), RB * math.sin(math.radians(p0)), z1)],
                      shade((-c, -s, 0), BASE_IN))
    # торцы (кольцо)
    for z, nz in ((0.0, (0, 0, -1)), (L, (0, 0, 1))):
        for j in range(NPHI):
            p0 = 360.0 * j / NPHI; p1 = 360.0 * (j + 1) / NPHI
            pm = 0.5 * (p0 + p1)
            if in_slit(z, pm) or in_cut(z, pm):
                continue
            rend.quad([(RB * math.cos(math.radians(p0)), RB * math.sin(math.radians(p0)), z),
                       (R * math.cos(math.radians(p0)), R * math.sin(math.radians(p0)), z),
                       (R * math.cos(math.radians(p1)), R * math.sin(math.radians(p1)), z),
                       (RB * math.cos(math.radians(p1)), RB * math.sin(math.radians(p1)), z)],
                      shade(nz, BASE))
    # стенки надрезов
    for i in range(NSLIT):
        zi = slit_z(i); b = slit_bridge(i)
        a0 = (b + (360 - SLIT_SPAN) / 2) % 360
        a1 = (b + SLIT_SPAN + (360 - SLIT_SPAN) / 2) % 360
        n = 90
        for k in range(n):
            pa = (a0 + (SLIT_SPAN) * k / n) % 360
            pb = (a0 + (SLIT_SPAN) * (k + 1) / n) % 360
            for zz, nz in ((zi - SLIT_W / 2, (0, 0, -1)), (zi + SLIT_W / 2, (0, 0, 1))):
                rend.quad([(RB * math.cos(math.radians(pa)), RB * math.sin(math.radians(pa)), zz),
                           (R * math.cos(math.radians(pa)), R * math.sin(math.radians(pa)), zz),
                           (R * math.cos(math.radians(pb)), R * math.sin(math.radians(pb)), zz),
                           (RB * math.cos(math.radians(pb)), RB * math.sin(math.radians(pb)), zz)],
                          shade(nz, CUT_FACE))
        # торцы перемычки
        for ang in (a0, a1):
            ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            for rr in (RB, R - 1e-6):
                pass
            rend.quad([(RB * ca, RB * sa, zi - SLIT_W / 2),
                       (R * ca, R * sa, zi - SLIT_W / 2),
                       (R * ca, R * sa, zi + SLIT_W / 2),
                       (RB * ca, RB * sa, zi + SLIT_W / 2)],
                      shade((-sa, ca, 0), CUT_FACE))
    # стенки продольных пропилов
    for ang, z0, z1 in SLITS:
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        hw = SLIT_W / 2
        for dz in range(60):
            za = z0 + (z1 - z0) * dz / 60; zb = z0 + (z1 - z0) * (dz + 1) / 60
            for sgn in (-1, 1):
                nx, ny = -sa * sgn, ca * sgn
                rend.quad([(RB * ca - hw * sa * sgn, RB * sa + hw * ca * sgn, za),
                           (R * ca - hw * sa * sgn, R * sa + hw * ca * sgn, za),
                           (R * ca - hw * sa * sgn, R * sa + hw * ca * sgn, zb),
                           (RB * ca - hw * sa * sgn, RB * sa + hw * ca * sgn, zb)],
                          shade((nx, ny, 0), BASE_IN))


# ------------------------------------------------------------------ вывод
W, H = 1300, 900
img = Image.new('RGB', (W, H), '#f7f6f2')
d = ImageDraw.Draw(img)

# проход 1 — габарит в единицах проекции, чтобы вписать в кадр
r0 = Render(W, H, 1.0, 0.0, 0.0)
build(r0)
xs = [pt[0] for _, pts, _ in r0.polys for pt in pts]
ys = [pt[1] for _, pts, _ in r0.polys for pt in pts]
bw, bh = max(xs) - min(xs), max(ys) - min(ys)
scale = min(W * 0.86 / bw, H * 0.86 / bh)
cx = W / 2 - (min(xs) + max(xs)) / 2 * scale
cy = H / 2 - (min(ys) + max(ys)) / 2 * scale
rend = Render(W, H, scale, cx, cy)
build(rend)

# отсечение по видимости не делаем: painter сам решает
rend.flush(d)


def mouth_poly(cx3, phi, radius, n=40):
    """Окружность в плоскости, перпендикулярной радиальному направлению."""
    u = (math.cos(math.radians(phi)), math.sin(math.radians(phi)), 0)
    w = (0, 0, 1)
    v = cross(u, w)
    pts = []
    for k in range(n):
        t = 2 * math.pi * k / n
        p = add(cx3, add(mul(v, radius * math.cos(t)), mul(w, radius * math.sin(t))))
        pts.append(rend.proj(p)[:2])
    return pts


F = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FH = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
fsm = ImageFont.truetype(F, 15)
fb = ImageFont.truetype(FH, 24)

# отверстия рисуем поверх поверхности
for z, phi in HOLES:
    c3 = (R * math.cos(math.radians(phi)), R * math.sin(math.radians(phi)), z)
    prim = (math.cos(math.radians(phi)), math.sin(math.radians(phi)), 0)
    if dot(rot(prim), VIEW) > 0:      # гнездо смотрит от нас
        continue
    hexr = HEX_AF / 2.0
    # фаска гнезда
    d.polygon(mouth_poly(c3, phi, hexr * 1.16, 48), fill=(214, 219, 222))
    d.polygon(mouth_poly(c3, phi, hexr * 1.10, 48), fill=(150, 157, 163))
    # шестигранное гнездо с ровными стенками
    d.polygon(mouth_poly(add(c3, mul(prim, -0.35)), phi, hexr * 0.98, 6), fill=(62, 68, 74))
    d.polygon(mouth_poly(add(c3, mul(prim, -1.1)), phi, hexr * 0.90, 6), fill=(44, 49, 54))
    # резьба ближе к узкой части
    for k in range(3):
        rr = SMALL_R * (1.10 + 0.42 * k)
        d.polygon(mouth_poly(add(c3, mul(prim, -(HEX_DEPTH - 0.5 - 1.15 * k))), phi, rr, 26),
                  outline=(122, 129, 135), width=2)
    d.polygon(mouth_poly(add(c3, mul(prim, -HEX_DEPTH)), phi, SMALL_R, 26), fill=(18, 22, 26))

# узкие выходы с обратной стороны
for z, phi in HOLES:
    op = (phi + 180) % 360
    c3 = (R * math.cos(math.radians(op)), R * math.sin(math.radians(op)), z)
    prim = (math.cos(math.radians(op)), math.sin(math.radians(op)), 0)
    if dot(rot(prim), VIEW) > 0:
        continue
    d.polygon(mouth_poly(c3, op, SMALL_R * 1.5, 28), fill=(196, 202, 207))
    d.polygon(mouth_poly(c3, op, SMALL_R * 1.25, 28), fill=(58, 63, 68))
    d.polygon(mouth_poly(c3, op, SMALL_R * 0.95, 26), fill=(24, 28, 32))

# ------------------------------------------------------- опорные точки для выносок
anchors = {}
for z, phi in HOLES:
    for tag, ang, rad in (('mouth', phi, 1.0), ('exit', (phi + 180) % 360, 1.0)):
        c3 = (R * math.cos(math.radians(ang)), R * math.sin(math.radians(ang)), z)
        prim = (math.cos(math.radians(ang)), math.sin(math.radians(ang)), 0)
        vis = dot(rot(prim), VIEW) < 0
        px, py, _ = rend.proj(c3)
        anchors[f'{tag}_{int(z * 10)}'] = [round(px, 1), round(py, 1), vis]
zm = L / 2
pm = 300.0
anchors['cut_mid'] = list(rend.proj((R * math.cos(math.radians(pm)),
                                     R * math.sin(math.radians(pm)), zm))[:2])
ang, z0, z1 = SLITS[0]
anchors['slit'] = list(rend.proj((R * math.cos(math.radians(ang)),
                                  R * math.sin(math.radians(ang)), 0.5 * (z0 + z1)))[:2])
anchors['end_face'] = list(rend.proj((0.0, 0.0, L))[:2])
anchors['end_far'] = list(rend.proj((0.0, 0.0, 0.0))[:2])
anchors['bore_face'] = list(rend.proj((RB, 0.0, L))[:2])
anchors['scale'] = round(rend.s, 3)
with open('forma/docs/coupling/iso_anchors.json', 'w', encoding='utf-8') as fh:
    import json
    json.dump(anchors, fh, ensure_ascii=False, indent=1)

img.save(OUT)
print('saved', OUT, img.size)
print('надрезов', NSLIT, 'шаг', round(BAND / NSLIT, 2), 'мм, ширина', SLIT_W, 'мм, дуга', SLIT_SPAN, '°')
