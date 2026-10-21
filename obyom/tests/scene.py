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
# предмет: цилиндр r=24 h=0..42 (полоски) + шар r=17 центр z=58 (шахматка) + «ручка»-кубик сбоку
def shade_obj(P, Nrm, kind):
    L = np.array([0.4, -0.5, 0.75]); L /= np.linalg.norm(L)
    lam = 0.35 + 0.65 * np.clip((Nrm * L).sum(-1), 0, 1)
    col = np.zeros(P.shape, np.float32)
    ang = np.arctan2(P[..., 1], P[..., 0])
    if kind == 'cyl':
        band = (np.floor(P[..., 2] / 7) % 2).astype(bool); sec = (np.floor((ang + np.pi) / (np.pi / 6)) % 2).astype(bool)
        col[:] = [0.85, 0.25, 0.2]; col[band ^ sec] = [0.95, 0.8, 0.2]
    elif kind == 'sph':
        q = P - np.array([0, 0, 58.0]); th = np.arctan2(q[..., 1], q[..., 0]); ph = np.arccos(np.clip(q[..., 2] / 17, -1, 1))
        ch = ((np.floor(th / (np.pi / 5)) + np.floor(ph / (np.pi / 6))) % 2).astype(bool)
        col[:] = [0.2, 0.45, 0.9]; col[ch] = [0.9, 0.9, 0.95]
    else:
        col[:] = [0.25, 0.75, 0.35]
    if os.environ.get('OBJWHITE'):  # однотонный светлый матовый предмет (как дезодорант)
        col[:] = [0.88, 0.88, 0.9]
    return col * lam[..., None]
def render(Rm, t):
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    d_cam = np.stack([(xs - cx) / f, (ys - cy) / f, np.ones_like(xs)], -1)
    Rt = Rm.T; o = -Rt @ t
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
    pl = np.where(onmat[..., None], paper, base)
    # тень от предмета (простая: круг под предметом, смещённый от света)
    sh = np.hypot(P[..., 0] - 10, P[..., 1] + 12) < 30
    pl = pl * np.where(sh[..., None], 0.75, 1.0)
    m = tz > 0
    best[m] = tz[m]; img[m] = pl[m]
    # фон-стена далеко (если луч не попал на стол)
    img[~m] = [float(v) for v in os.environ['TABLE'].split(',')] if os.environ.get('TABLE') else [0.6, 0.62, 0.65]
    def hit(tt, Pn, Nn, kind, ok):
        nonlocal best, img
        ok = ok & (tt > 0) & (tt < best)
        if ok.any():
            c = shade_obj(Pn, Nn, kind)
            img[ok] = c[ok]; best[ok] = tt[ok]
    # цилиндр (бок)
    a = d[..., 0]**2 + d[..., 1]**2; b = 2 * (o[0] * d[..., 0] + o[1] * d[..., 1]); c = o[0]**2 + o[1]**2 - 24**2
    disc = b * b - 4 * a * c; sq = np.sqrt(np.maximum(disc, 0))
    t1 = (-b - sq) / (2 * a + 1e-12); Pc = o + d * t1[..., None]
    Nc = np.stack([Pc[..., 0], Pc[..., 1], np.zeros_like(t1)], -1) / 24
    hit(t1, Pc, Nc, 'cyl', (disc > 0) & (Pc[..., 2] >= 0) & (Pc[..., 2] <= 42))
    # верх цилиндра
    tt = (42 - o[2]) / np.where(np.abs(d[..., 2]) < 1e-9, 1e-9, d[..., 2]); Pt = o + d * tt[..., None]
    hit(tt, Pt, np.broadcast_to(np.array([0, 0, 1.0]), Pt.shape), 'cyl', np.hypot(Pt[..., 0], Pt[..., 1]) <= 24)
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
    objm = best < np.where(m, tz, np.inf) - 1e-3
    img = np.clip(img + rng.normal(0, noise / 255, img.shape), 0, 1)
    return (img * 255).astype(np.uint8), objm
def look(cam, target):
    z = target - cam; z /= np.linalg.norm(z)
    x = np.cross(z, [0, 0, 1.0]); x /= np.linalg.norm(x); y = np.cross(z, x)
    Rm = np.stack([x, y, z]); return Rm, -Rm @ cam
frames = []
for i in range(N):
    if mode == 'spin':  # вертушка, раскрученная рукой: 10 к/с, ω0 = 120°/с, затухание τ = 5 с, держатель на 35°
        tt = i / 10.0; az = 120 * 5 * (1 - np.exp(-tt / 5)); el = 35; dist = 380
        frames_w = 120 * np.exp(-tt / 5)
    elif mode == 'turn':
        az = i * 360 / N; el = [32, 52][i % 2]; dist = 380
    else:
        az = i * 360 / N + rng.normal(0, 3); el = 30 + 25 * (i % 3) / 2 + rng.normal(0, 2); dist = 340 + rng.normal(0, 20)
    a = np.radians(az); e = np.radians(el)
    cam = np.array([dist * np.cos(e) * np.sin(a), dist * np.cos(e) * np.cos(a), dist * np.sin(e)])
    Rm, t = look(cam, np.array([0, 0, 25.0]) + (rng.normal(0, 5, 3) if mode == 'walk' else 0))
    img, objm = render(Rm, t)
    Image.fromarray((objm * 255).astype(np.uint8)).save(f'{out}/m{i:03d}.png')
    im = Image.fromarray(img).filter(ImageFilter.GaussianBlur(0.6))
    if mode == 'spin':  # смаз при движении: ~2.7 пикс на градус, выдержка 1/30 с
        L = frames_w / 30 * 2.7
        if L > 1.5 and not os.environ.get('NOBLUR'): im = im.filter(ImageFilter.BoxBlur(float(L) / 2))
    im.save(f'{out}/f{i:03d}.jpg', quality=88)
    frames.append({'file': f'f{i:03d}.jpg', 'R': Rm.flatten().tolist(), 't': t.tolist(), 'az': az, 'el': el})
json.dump({'K': {'fx': f, 'fy': f, 'cx': cx, 'cy': cy}, 'w': W, 'h': H, 'frames': frames}, open(f'{out}/gt.json', 'w'))
print('ok', N)
