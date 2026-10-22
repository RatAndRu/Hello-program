# синтетическая съёмка: коврик + предмет, известные камеры. python3 scene.py out_dir mode(turn|walk) n [theme] [noise]
import numpy as np, sys, json, os
from PIL import Image, ImageFilter
out, mode, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
theme = sys.argv[4] if len(sys.argv) > 4 else 'light'
noise = float(sys.argv[5]) if len(sys.argv) > 5 else 2.0
os.makedirs(out, exist_ok=True)
mat = np.asarray(Image.open(f'/tmp/t/mat_{theme}.pgm')).astype(np.float32) / 255
PPM = 6.0; MW, MH = 210.0, 297.0
W, H = 1280, 720; f = 0.78 * W; cx, cy = W / 2, H / 2
rng = np.random.default_rng(1)
# положение предмета: OBJPOSE="rx,ry,rz,tx,ty,tz" (градусы, мм; повороты по осям X, затем Y, затем Z) — для «доснять низ»
QR = np.eye(3); QT = np.zeros(3)
if os.environ.get('OBJPOSE'):
    v = [float(x) for x in os.environ['OBJPOSE'].split(',')]
    def rot(ax, a):
        a = np.radians(a); c, s_ = np.cos(a), np.sin(a)
        return {0: np.array([[1, 0, 0], [0, c, -s_], [0, s_, c]]), 1: np.array([[c, 0, s_], [0, 1, 0], [-s_, 0, c]]), 2: np.array([[c, -s_, 0], [s_, c, 0], [0, 0, 1]])}[ax]
    QR = rot(2, v[2]) @ rot(1, v[1]) @ rot(0, v[0]); QT = np.array(v[3:6])
# предмет: цилиндр r=24 h=0..42 (полоски) + шар r=17 центр z=58 (шахматка) + «ручка»-кубик сбоку
def shade_obj(P, Nrm, kind):
    L = np.array([float(v) for v in os.environ.get('LDIR', '0.4,-0.5,0.75').split(',')]); L /= np.linalg.norm(L)  # LDIR — направление на лампу (при az=0 камера на +Y)
    if LIGHTCAM:  # лампа стоит в комнате: на вертушке она поворачивается относительно предмета вместе с камерой
        a_ = np.radians(AZ[0]); L = np.array([L[0] * np.cos(a_) + L[1] * np.sin(a_), -L[0] * np.sin(a_) + L[1] * np.cos(a_), L[2]])
    if BUMP and kind == 'cyl':  # рельеф: горизонтальные бороздки на боку цилиндра, h(z) = 0.3·sin(2πz/5) мм (наклон до ±21°)
        side = np.abs(Nrm[..., 2]) < 0.5
        Nrm = Nrm.copy(); gz = -0.3 * 2 * np.pi / 5 * np.cos(2 * np.pi * P[..., 2] / 5); gs = 0 * gz
        if BUMP == 2:  # BUMP=2: внизу (z<21) бороздки, вверху — сетка выпуклостей h = 0.4·cos(2πs/6)·cos(2πz/6), s — длина дуги
            ang_ = np.arctan2(P[..., 1], P[..., 0]); s_ = 24 * ang_; k_ = 2 * np.pi / 6; up = P[..., 2] >= 21
            gz = np.where(up, 0.4 * k_ * np.cos(k_ * s_) * np.sin(k_ * P[..., 2]), gz)   # n = r̂ − ∂h/∂s·t̂ − ∂h/∂z·ẑ
            gs = np.where(up, 0.4 * k_ * np.sin(k_ * s_) * np.cos(k_ * P[..., 2]), 0 * gz)
            tx, ty = -np.sin(ang_), np.cos(ang_)
            Nrm[..., 0] = np.where(side, Nrm[..., 0] + gs * tx, Nrm[..., 0]); Nrm[..., 1] = np.where(side, Nrm[..., 1] + gs * ty, Nrm[..., 1])
        Nrm[..., 2] = np.where(side, gz, Nrm[..., 2])
        Nrm = Nrm / np.linalg.norm(Nrm, axis=-1, keepdims=True)
    Nrm = Nrm @ QR.T
    lam = 0.35 + 0.65 * np.clip((Nrm * L).sum(-1), 0, 1)
    if TORCH:  # фонарик телефона у объектива: точечный свет из камеры, спад 1/d²; комната — слабая доля TORCH
        Pw = P @ QR.T + QT; Lv = CAMW[0] + TOFF[0] - Pw; dd = np.linalg.norm(Lv, axis=-1); Lv = Lv / dd[..., None]
        lam = TORCH * lam + 1.25 * (1 - TORCH) * np.clip((Nrm * Lv).sum(-1), 0, 1) * (TD0 / dd) ** 2
        L = Lv
    spec = 0
    if SPEC or MATS:  # блик (Блинн — Фонг): белый, зависит от направления взгляда
        Pw = P @ QR.T + QT; V = CAMW[0] - Pw; V = V / np.linalg.norm(V, axis=-1, keepdims=True)
        Hh = V + L; Hh = Hh / np.linalg.norm(Hh, axis=-1, keepdims=True)
        nh = np.clip((Nrm * Hh).sum(-1), 0, 1)
        spec = SPEC * nh ** 40
        # MATS=1: цилиндр матовый, шар — глянцевый пластик (узкий белый блик), кубик-ручка — металл (широкий цветной блик, тёмный диффузный)
        if MATS: spec = {'cyl': 0 * nh, 'sph': 0.7 * nh ** 200, 'box': 0.9 * nh ** 30}.get(kind, spec)
    col = np.zeros(P.shape, np.float32)
    ang = np.arctan2(P[..., 1], P[..., 0])
    if kind == 'cyl':
        band = (np.floor(P[..., 2] / 7) % 2).astype(bool); sec = (np.floor((ang + np.pi) / (np.pi / 6)) % 2).astype(bool)
        col[:] = [0.85, 0.25, 0.2]; col[band ^ sec] = [0.95, 0.8, 0.2]
    elif kind == 'sph':
        q = P - np.array([0, 0, 58.0]); th = np.arctan2(q[..., 1], q[..., 0]); ph = np.arccos(np.clip(q[..., 2] / 17, -1, 1))
        ch = ((np.floor(th / (np.pi / 5)) + np.floor(ph / (np.pi / 6))) % 2).astype(bool)
        col[:] = [0.2, 0.45, 0.9]; col[ch] = [0.9, 0.9, 0.95]
    elif kind == 'poly':
        ch = ((np.floor(P[..., 0] / 8) + np.floor(P[..., 1] / 8) + np.floor(P[..., 2] / 8)) % 2).astype(bool)
        col[:] = [0.85, 0.45, 0.15]; col[ch] = [0.95, 0.9, 0.8]
    else:
        col[:] = [0.25, 0.75, 0.35]
    if os.environ.get('OBJWHITE'):  # однотонный светлый матовый предмет (как дезодорант)
        col[:] = [0.88, 0.88, 0.9]
    if MATS and kind == 'box':  # металл: блик цвета металла, диффузного почти нет
        return np.clip(col * lam[..., None] * 0.15 + spec[..., None] * col / col.max(-1, keepdims=True), 0, 1)
    return np.clip(col * lam[..., None] + (spec[..., None] if (SPEC or MATS) else 0), 0, 1)
AZ = [0.0]; NOOBJ = [False]; CAMW = [np.zeros(3)]
BUMP = int(os.environ.get('BUMP', 0) or 0); MATS = bool(os.environ.get('MATS'))  # рельеф и разные материалы (v2.0)
LIGHTCAM = bool(os.environ.get('LIGHTCAM')); SPEC = float(os.environ.get('SPEC', 0))  # свет в комнате; сила блика
EXPO = float(os.environ.get('EXPO', 0))  # разброс автоэкспозиции между кадрами (σ лог-усиления), напр. 0.1
TORCH = float(os.environ.get('TORCH', 0) or 0)  # фонарик (v2.1): доля комнатного света, напр. 0.25; 0 — без фонарика
TD0 = float(os.environ.get('TD0', 360)); TOFF = [np.zeros(3)]  # TD0 — расстояние, на котором фонарик даёт яркость 1
STATIC = bool(os.environ.get('STATIC'))  # вертушка у неподвижной камеры: стол и стена неподвижны относительно камеры
K1 = float(os.environ.get('K1', 0) or 0)  # радиальная дисторсия, напр. -0.06 (бочка)
def render(Rm, t):
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    xd = (xs - cx) / f; yd = (ys - cy) / f; xu = xd.copy(); yu = yd.copy()
    if K1:  # дисторсия объектива (v2.3): пиксель (xs, ys) — искажённый; луч — по неискажённым координатам x_d = x_u·(1 + k1·r_u²)
        for _ in range(8): s_ = 1 + K1 * (xu * xu + yu * yu); xu = xd / s_; yu = yd / s_
    d_cam = np.stack([xu, yu, np.ones_like(xs)], -1)
    Rt = Rm.T; o = -Rt @ t; CAMW[0] = o.copy()
    TOFF[0] = Rm.T @ np.array([12.0, -8.0, 0])  # светодиод в ~1.4 см от объектива
    d = d_cam @ Rt.T; d /= np.linalg.norm(d, axis=-1, keepdims=True)
    best = np.full((H, W), np.inf, np.float32); img = np.zeros((H, W, 3), np.float32)
    # плоскость z=0
    tz = -o[2] / np.where(np.abs(d[..., 2]) < 1e-9, -1e-9, d[..., 2])
    P = o + d * tz[..., None]
    u = P[..., 0] + MW / 2; v = MH / 2 - P[..., 1]
    onmat = (tz > 0) & (u >= 0) & (u < MW) & (v >= 0) & (v < MH)
    mi = np.clip((v * PPM).astype(int), 0, mat.shape[0] - 1); mj = np.clip((u * PPM).astype(int), 0, mat.shape[1] - 1)
    wood = 0.45 + 0.08 * np.sin(P[..., 0] * 0.15 + np.sin(P[..., 1] * 0.05) * 3)
    base = np.stack([wood * 1.0, wood * 0.75, wood * 0.5], -1)
    if os.environ.get('TABLE'):  # трудный случай: стол/стена цвета предмета, напр. TABLE=0.86,0.86,0.9
        tc = np.array([float(v) for v in os.environ['TABLE'].split(',')]); base = (1 + 0.03 * np.sin(P[..., 0] * 0.01))[..., None] * tc
    paper = mat[mi, mj][..., None] * np.array([0.93, 0.92, 0.9])
    if STATIC:  # стол и стена — в системе камеры (повёрнуты на az относительно коврика)
        ca, sa = np.cos(np.radians(AZ[0])), np.sin(np.radians(AZ[0]))
        Pfx = ca * P[..., 0] - sa * P[..., 1]; Pfy = sa * P[..., 0] + ca * P[..., 1]
        wood = 0.45 + 0.08 * np.sin(Pfx * 0.15 + np.sin(Pfy * 0.05) * 3)
        base = np.stack([wood * 1.0, wood * 0.75, wood * 0.5], -1)
        ofy = sa * o[0] + ca * o[1]; dfy = sa * d[..., 0] + ca * d[..., 1]
        tw = (-260 - ofy) / np.where(np.abs(dfy) < 1e-9, -1e-9, dfy)
        Pw = o + d * tw[..., None]; Pwx = ca * Pw[..., 0] - sa * Pw[..., 1]
        wall = (0.78 + 0.04 * np.sin(Pwx * 0.02) + 0.03 * (Pw[..., 2] > 180))[..., None] * np.array([1.0, 0.97, 0.92])
        wall = np.where(((np.abs(Pwx + 120) < 60) & (np.abs(Pw[..., 2] - 150) < 45))[..., None], np.array([0.3, 0.5, 0.6]), wall)  # картинка на стене
        onwall = (dfy < 0) & (tw > 0) & ((tz <= 0) | (Pfy < -260))
        base = np.where(onwall[..., None], wall, base)
    pl = np.where(onmat[..., None], paper, base)
    if TORCH:  # пятно фонарика на коврике и столе
        Lm = o + TOFF[0] - P; dm = np.linalg.norm(Lm, axis=-1); cz = np.clip(Lm[..., 2] / dm, 0, 1)
        pl = pl * (TORCH + 1.25 * (1 - TORCH) * cz * (TD0 / np.maximum(dm, 1)) ** 2)[..., None]
    # тень от предмета (простая: круг под предметом, смещённый от света)
    shx, shy = 10.0, -12.0
    if LIGHTCAM: a_ = np.radians(AZ[0]); shx, shy = 10 * np.cos(a_) - 12 * np.sin(a_), -10 * np.sin(a_) - 12 * np.cos(a_)
    sh = np.hypot(P[..., 0] - shx, P[..., 1] - shy) < 30
    if not NOOBJ[0]: pl = pl * np.where(sh[..., None], 0.75, 1.0)
    m = tz > 0
    best[m] = tz[m]; img[m] = pl[m]
    if STATIC: img[onwall] = pl[onwall]; best[onwall] = tw[onwall]; m = m & ~onwall
    bgd = best.copy()  # глубина фона (стол, коврик, стена): предмет — то, что ближе неё
    # фон-стена далеко (если луч не попал на стол)
    img[~m & ~(onwall if STATIC else False)] = [float(v) for v in os.environ['TABLE'].split(',')] if os.environ.get('TABLE') else [0.6, 0.62, 0.65]
    ow, dw_ = o, d
    o = QR.T @ (ow - QT); d = d @ QR  # луч в систему предмета
    def hit(tt, Pn, Nn, kind, ok):
        nonlocal best, img
        ok = ok & (tt > 0) & (tt < best) & (not NOOBJ[0])
        if ok.any():
            c = shade_obj(Pn, Nn, kind)
            img[ok] = c[ok]; best[ok] = tt[ok]
    if os.environ.get('OBJ') == 'mug':  # v2.3: кружка — полая (внутри видно только сверху): r 30 / 26.5, высота 80, дно 7, П-ручка
        RO, RI, HM, HB_ = 30.0, 26.5, 80.0, 7.0
        inner = 'plain' if os.environ.get('MUGPLAIN') else 'sph'  # внутри: однотонно или с рисунком
        def cyl_roots(r):
            a_ = d[..., 0]**2 + d[..., 1]**2; b_ = 2 * (o[0] * d[..., 0] + o[1] * d[..., 1]); c_ = o[0]**2 + o[1]**2 - r * r
            dc = b_ * b_ - 4 * a_ * c_; q_ = np.sqrt(np.maximum(dc, 0)); return dc > 0, (-b_ - q_) / (2 * a_ + 1e-12), (-b_ + q_) / (2 * a_ + 1e-12)
        okc, t1, _ = cyl_roots(RO); Pc = o + d * t1[..., None]
        hit(t1, Pc, np.stack([Pc[..., 0], Pc[..., 1], np.zeros_like(t1)], -1) / RO, 'cyl', okc & (Pc[..., 2] >= 0) & (Pc[..., 2] <= HM))
        oki, _, t2 = cyl_roots(RI); Pi = o + d * t2[..., None]
        hit(t2, Pi, -np.stack([Pi[..., 0], Pi[..., 1], np.zeros_like(t2)], -1) / RI, inner, oki & (Pi[..., 2] >= HB_) & (Pi[..., 2] <= HM))
        def plane(z0, nz_, rmin, rmax, kind):
            tz_ = (z0 - o[2]) / np.where(np.abs(d[..., 2]) < 1e-9, 1e-9, d[..., 2]); Pz = o + d * tz_[..., None]; rr = np.hypot(Pz[..., 0], Pz[..., 1])
            hit(tz_, Pz, np.broadcast_to(np.array([0, 0, nz_]), Pz.shape), kind, (rr >= rmin) & (rr <= rmax))
        plane(HM, 1.0, RI, RO, 'cyl'); plane(HB_, 1.0, 0, RI, inner); plane(0.0, -1.0, 0, RO, 'cyl')
        inv = 1 / np.where(np.abs(d) < 1e-9, 1e-9, d)
        for lo, hi in [((28, -5, 20.0), (46, 5, 28.0)), ((28, -5, 52.0), (46, 5, 60.0)), ((39, -5, 28.0), (46, 5, 52.0))]:
            lo = np.array(lo); hi = np.array(hi); t0 = (lo - o) * inv; t1b = (hi - o) * inv
            tmin = np.minimum(t0, t1b).max(-1); tmax = np.maximum(t0, t1b).min(-1); Pb = o + d * tmin[..., None]
            nb = np.zeros_like(Pb); ax = np.argmax(np.minimum(t0, t1b), -1)
            for k in range(3): nb[..., k] = np.where(ax == k, -np.sign(d[..., k]), 0)
            hit(tmin, Pb, nb, 'box', tmax > np.maximum(tmin, 0))
        objm = best < bgd - 1e-3
        img = np.clip(img + rng.normal(0, noise / 255, img.shape), 0, 1)
        return (img * 255).astype(np.uint8), objm
    if os.environ.get('OBJ') in ('box', 'hex', 'pbank'):  # выпуклый многогранник (коробка 60×40×45, повёрнута на 20°; шестигранник r=30 h=50;
        # pbank — павербанк, поставленный вертикально: 66×24×140, размеры можно задать BOXDIM="66,24,140")
        if os.environ['OBJ'] in ('box', 'pbank'):
            bx, by, bz = [float(x) for x in os.environ.get('BOXDIM', '60,40,45' if os.environ['OBJ'] == 'box' else '66,24,140').split(',')]
            th = np.radians(20); u = np.array([np.cos(th), np.sin(th), 0]); v = np.array([-np.sin(th), np.cos(th), 0])
            PL = [(u, bx / 2), (-u, bx / 2), (v, by / 2), (-v, by / 2), (np.array([0, 0, 1.0]), bz), (np.array([0, 0, -1.0]), 0)]
        else:
            PL = [(np.array([np.cos(a_), np.sin(a_), 0]), 30 * np.cos(np.pi / 6)) for a_ in np.arange(6) * np.pi / 3 + 0.2] + [(np.array([0, 0, 1.0]), 50), (np.array([0, 0, -1.0]), 0)]
        tn = np.full(d.shape[:2], -np.inf); tf = np.full(d.shape[:2], np.inf); nn = np.zeros(d.shape); ok = np.ones(d.shape[:2], bool)
        for k_, (n_, h_) in enumerate(PL):
            dn = d @ n_; on = o @ n_ - h_
            t_ = -on / np.where(np.abs(dn) < 1e-9, 1e-9, dn)
            ent = dn < 0
            upd = ent & (t_ > tn); tn = np.where(upd, t_, tn); nn[upd] = n_
            tf = np.where(~ent & (t_ < tf), t_, tf)
            ok &= ~((np.abs(dn) < 1e-9) & (on > 0))
        Pp = o + d * tn[..., None]
        hit(tn, Pp, nn, 'poly', ok & (tn < tf))
        objm = best < bgd - 1e-3
        img = np.clip(img + rng.normal(0, noise / 255, img.shape), 0, 1)
        return (img * 255).astype(np.uint8), objm
    # цилиндр (бок)
    a = d[..., 0]**2 + d[..., 1]**2; b = 2 * (o[0] * d[..., 0] + o[1] * d[..., 1]); c = o[0]**2 + o[1]**2 - 24**2
    disc = b * b - 4 * a * c; sq = np.sqrt(np.maximum(disc, 0))
    t1 = (-b - sq) / (2 * a + 1e-12); Pc = o + d * t1[..., None]
    Nc = np.stack([Pc[..., 0], Pc[..., 1], np.zeros_like(t1)], -1) / 24
    hit(t1, Pc, Nc, 'cyl', (disc > 0) & (Pc[..., 2] >= 0) & (Pc[..., 2] <= 42))
    # верх цилиндра
    tt = (42 - o[2]) / np.where(np.abs(d[..., 2]) < 1e-9, 1e-9, d[..., 2]); Pt = o + d * tt[..., None]
    hit(tt, Pt, np.broadcast_to(np.array([0, 0, 1.0]), Pt.shape), 'cyl', np.hypot(Pt[..., 0], Pt[..., 1]) <= 24)
    # дно цилиндра (видно, когда предмет лежит на боку — OBJPOSE)
    tb = (0 - o[2]) / np.where(np.abs(d[..., 2]) < 1e-9, 1e-9, d[..., 2]); Pb0 = o + d * tb[..., None]
    hit(tb, Pb0, np.broadcast_to(np.array([0, 0, -1.0]), Pb0.shape), 'cyl', np.hypot(Pb0[..., 0], Pb0[..., 1]) <= 24)
    # шар
    oc = o - np.array([0, 0, 58.0]); b2 = (d * oc).sum(-1); c2 = (oc**2).sum() - 17**2; dd = b2 * b2 - c2
    ts = -b2 - np.sqrt(np.maximum(dd, 0)); Ps = o + d * ts[..., None]
    hit(ts, Ps, (Ps - np.array([0, 0, 58.0])) / 17, 'sph', dd > 0)
    # кубик-ручка: x 24..40, y -6..6, z 10..30
    lo = np.array([22, -6, 10.0]); hi = np.array([40, 6, 30.0])
    inv = 1 / np.where(np.abs(d) < 1e-9, 1e-9, d)
    t0 = (lo - o) * inv; t1b = (hi - o) * inv
    tmin = np.minimum(t0, t1b).max(-1); tmax = np.maximum(t0, t1b).min(-1)
    Pb = o + d * tmin[..., None]
    nb = np.zeros_like(Pb); ax = np.argmax(np.minimum(t0, t1b), -1)
    for k in range(3): nb[..., k] = np.where(ax == k, -np.sign(d[..., k]), 0)
    hit(tmin, Pb, nb, 'box', tmax > np.maximum(tmin, 0))
    objm = best < bgd - 1e-3
    img = np.clip(img + rng.normal(0, noise / 255, img.shape), 0, 1)
    return (img * 255).astype(np.uint8), objm
def look(cam, target):
    z = target - cam; z /= np.linalg.norm(z)
    x = np.cross(z, [0, 0, 1.0]); x /= np.linalg.norm(x); y = np.cross(z, x)
    Rm = np.stack([x, y, z]); return Rm, -Rm @ cam
frames = []
for i in range(N):
    if mode == 'spin':  # вертушка, раскрученная рукой: 10 к/с, ω0 = 120°/с, затухание τ = 5 с, держатель на 35°
        tt = i / 10.0; az = 120 * 5 * (1 - np.exp(-tt / 5)); el = float(os.environ.get('EL', 35)); dist = 380  # EL — высота держателя
        frames_w = 120 * np.exp(-tt / 5)
    elif mode == 'turn':
        az = i * 360 / N; el = [32, 52][i % 2]; dist = 380
    else:
        az = i * 360 / N + rng.normal(0, 3); el = 30 + 25 * (i % 3) / 2 + rng.normal(0, 2); dist = 340 + rng.normal(0, 20)
        if os.environ.get('TOPV'): el = [30, 52, 74][i % 3] + rng.normal(0, 2)  # v2.3: с кадрами почти сверху (заглянуть в кружку)
    if os.environ.get('DIST'): dist = float(os.environ['DIST']) + rng.normal(0, 8)  # крупные планы (досъёмка для текстуры)
    a = np.radians(az); e = np.radians(el)
    cam = np.array([dist * np.cos(e) * np.sin(a), dist * np.cos(e) * np.cos(a), dist * np.sin(e)])
    Rm, t = look(cam, np.array([0, 0, float(os.environ.get('LOOKZ', 25))]) + (rng.normal(0, 5, 3) if mode == 'walk' else 0))
    AZ[0] = az; img, objm = render(Rm, t)
    if STATIC and i == 0:  # кадр фона: пустая вертушка
        NOOBJ[0] = True; pim, _ = render(Rm, t); NOOBJ[0] = False
        Image.fromarray(pim).filter(ImageFilter.GaussianBlur(0.6)).save(f'{out}/plate.jpg', quality=88)
    Image.fromarray((objm * 255).astype(np.uint8)).save(f'{out}/m{i:03d}.png')
    if EXPO:  # автоэкспозиция и баланс белого «гуляют» от кадра к кадру
        g_ = np.exp(rng.normal(0, EXPO) + rng.normal(0, EXPO * 0.3, 3)); img = np.clip(img.astype(np.float32) * g_, 0, 255).astype(np.uint8)
    im = Image.fromarray(img).filter(ImageFilter.GaussianBlur(0.6))
    if mode == 'spin':  # смаз при движении: ~2.7 пикс на градус, выдержка 1/30 с
        L = frames_w / 30 * 2.7
        if L > 1.5 and not os.environ.get('NOBLUR'): im = im.filter(ImageFilter.BoxBlur(float(L) / 2))
    im.save(f'{out}/f{i:03d}.jpg', quality=88)
    frames.append({'file': f'f{i:03d}.jpg', 'R': Rm.flatten().tolist(), 't': t.tolist(), 'az': az, 'el': el})
json.dump({'K': {'fx': f, 'fy': f, 'cx': cx, 'cy': cy}, 'w': W, 'h': H, 'frames': frames}, open(f'{out}/gt.json', 'w'))
print('ok', N)
