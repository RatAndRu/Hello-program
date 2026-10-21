import json, numpy as np, sys
from PIL import Image
M = json.load(open(sys.argv[1])); out = sys.argv[2]
P = np.array(M['pos'], np.float32).reshape(-1, 3); I = np.array(M['idx']).reshape(-1, 3); C = np.array(M['col'], np.float32).reshape(-1, 3)
def view(az, el, W=400, H=400):
    a, e = np.radians(az), np.radians(el); d = 260
    cam = np.array([d*np.cos(e)*np.sin(a), d*np.cos(e)*np.cos(a), d*np.sin(e)]); tgt = np.array([0, 0, 35.])
    z = tgt - cam; z /= np.linalg.norm(z); x = np.cross(z, [0, 0, 1.]); x /= np.linalg.norm(x); y = np.cross(z, x)
    Rm = np.stack([x, y, z]); Q = (P - cam) @ Rm.T; f = 700
    u = f * Q[:, 0] / Q[:, 2] + W / 2; v = f * Q[:, 1] / Q[:, 2] + H / 2
    img = np.full((H, W, 3), 30, np.float32); zb = np.full((H, W), np.inf)
    # нормали граней для освещения
    A, B, Cc = P[I[:, 0]], P[I[:, 1]], P[I[:, 2]]; N = np.cross(B - A, Cc - A); N /= np.linalg.norm(N, axis=1, keepdims=True) + 1e-9
    light = -z; sh = 0.55 + 0.45 * np.clip(N @ light, 0, 1)
    order = np.argsort(-Q[I].mean(1)[:, 2])
    for t in order:
        i0, i1, i2 = I[t]
        xs = np.array([u[i0], u[i1], u[i2]]); ys = np.array([v[i0], v[i1], v[i2]])
        x0, x1 = int(max(0, xs.min())), int(min(W - 1, xs.max() + 1)); y0, y1 = int(max(0, ys.min())), int(min(H - 1, ys.max() + 1))
        if x1 < x0 or y1 < y0: continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-9: continue
        l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den; l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den; l2 = 1 - l0 - l1
        ins = (l0 >= -0.01) & (l1 >= -0.01) & (l2 >= -0.01)
        if not ins.any(): continue
        zz = l0 * Q[i0, 2] + l1 * Q[i1, 2] + l2 * Q[i2, 2]
        sub = zb[y0:y1+1, x0:x1+1]; ok = ins & (zz < sub)
        col = (l0[..., None] * C[i0] + l1[..., None] * C[i1] + l2[..., None] * C[i2]) * (sh[t] if len(sys.argv) > 3 else 1)
        sub[ok] = zz[ok]; img[y0:y1+1, x0:x1+1][ok] = col[ok]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
ims = [view(a, e) for a, e in [(0, 30), (90, 30), (200, 50), (300, 15)]]
Wd = Image.new('RGB', (1600, 400)); [Wd.paste(im, (i * 400, 0)) for i, im in enumerate(ims)]; Wd.save(out)
