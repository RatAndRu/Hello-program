"""Собственный офлайн-рендерер: 4 ортографических вида в PNG.

Нужен для честной проверки результата без видеокарты и браузера:
я (нейросеть) и пользователь можем посмотреть на снимки и увидеть,
что реально получилось.
"""

from __future__ import annotations

import math
import os

import numpy as np

from .geometry import crease_normals, color_to_float_rgb, manifold_mesh, write_png

VIEWS = {
    "iso": ((0.92, 1.25, 0.78), (0.0, 0.0, 1.0)),
    "front": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
}
VIEW_LABELS = {"iso": "изометрия", "front": "спереди", "right": "справа", "top": "сверху"}

BG_TOP = np.array([0.105, 0.118, 0.145], dtype=np.float32)
BG_BOTTOM = np.array([0.045, 0.052, 0.068], dtype=np.float32)


def _normalize(v):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _load_texture(path: str, size: int = 256):
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB").resize((size, size), Image.BILINEAR)
        return (np.asarray(img, dtype=np.float32) / 255.0)
    except Exception:
        return None


def _prepare(solids):
    meshes = []
    for s in solids:
        v, f = manifold_mesh(s.manifold)
        if len(f) == 0:
            continue
        nv, nn, nf = crease_normals(v, f, 38.0)
        item = {
            "verts": nv, "faces": nf, "normals": nn,
            "color": np.array(color_to_float_rgb(s.color), dtype=np.float32),
            "metal": float(s.metal), "rough": float(s.rough),
            "uv": None, "tex": None,
        }
        tex = getattr(s, "tex", None)
        if tex and tex.get("path"):
            image = _load_texture(tex["path"])
            if image is not None:
                lo = nv.min(axis=0)
                hi = nv.max(axis=0)
                span = np.maximum(hi - lo, 1e-9)
                mode = getattr(s, "uv", "cylinder")
                if mode == "planar":
                    u = (nv[:, 0] - lo[0]) / span[0]
                    w = (nv[:, 1] - lo[1]) / span[1]
                else:
                    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
                    u = np.arctan2(nv[:, 1] - cy, nv[:, 0] - cx) / (2 * np.pi) + 0.5
                    w = (nv[:, 2] - lo[2]) / span[2]
                item["uv"] = np.stack([u, w], axis=1).astype(np.float32)
                item["tex"] = image
        meshes.append(item)
    return meshes


def _camera(center, radius, view, width, height):
    dir_v, up_world = VIEWS[view]
    eye_dir = _normalize(dir_v)
    f = -eye_dir  # направление взгляда
    up_world = _normalize(up_world)
    right = np.cross(f, up_world)
    if np.linalg.norm(right) < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    right = _normalize(right)
    up = _normalize(np.cross(right, f))
    scale = min(width, height) * 0.46 / max(radius, 1e-9)
    return {
        "f": f, "right": right, "up": up, "scale": scale,
        "center": np.asarray(center, dtype=np.float64),
        "eye": np.asarray(center, dtype=np.float64) - f * radius * 4,
        "w": width, "h": height,
    }


def _project(points, cam):
    d = points - cam["center"]
    u = d @ cam["right"]
    v = d @ cam["up"]
    depth = d @ cam["f"]
    x = cam["w"] / 2 + u * cam["scale"]
    y = cam["h"] / 2 - v * cam["scale"]
    return np.stack([x, y], axis=1), depth


def _background(cam):
    w, h = cam["w"], cam["h"]
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    img = BG_TOP[None, None, :] * (1 - t) + BG_BOTTOM[None, None, :] * t
    img = np.repeat(img, w, axis=1)
    # лёгкая виньетка
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = (xx - w / 2) / (w / 2)
    dy = (yy - h / 2) / (h / 2)
    vig = 1.0 - 0.18 * np.clip(dx * dx + dy * dy, 0, 1.5)
    return img * vig[:, :, None]


def _grid_step(span):
    target = span / 6.5
    steps = [0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000, 2000]
    for s in steps:
        if s >= target:
            return s
    return 5000


def _draw_grid(img, zbuf, cam, bbox):
    if cam["f"][2] < -0.9:
        return  # вид сверху — сетка не нужна
    center_depth = float((np.asarray([(bbox[0] + bbox[3]) / 2, (bbox[1] + bbox[4]) / 2,
                                      0.0]) - cam["center"]) @ cam["f"])
    xmin, ymin, zmin, xmax, ymax, zmax = bbox
    span = max(xmax - xmin, ymax - ymin)
    step = _grid_step(max(span, 1.0))
    limit = max(span, step * 4) * 1.4
    gx = np.arange(-limit, limit + step * 0.5, step)
    h, w = img.shape[:2]
    line_color = np.array([0.30, 0.34, 0.43], dtype=np.float32)
    axis_x = np.array([0.55, 0.28, 0.30], dtype=np.float32)
    axis_y = np.array([0.30, 0.50, 0.34], dtype=np.float32)
    n = 600

    def draw(p0, p1, color, alpha=0.5):
        ts = np.linspace(0, 1, n)
        pts = np.array(p0)[None, :] * (1 - ts)[:, None] + np.array(p1)[None, :] * ts[:, None]
        scr, dep = _project(pts, cam)
        xi = np.round(scr[:, 0]).astype(int)
        yi = np.round(scr[:, 1]).astype(int)
        ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
        xi, yi, dep = xi[ok], yi[ok], dep[ok]
        if len(xi) == 0:
            return
        closer = (dep < zbuf[yi, xi]) & (dep > center_depth)
        xi, yi, dep = xi[closer], yi[closer], dep[closer]
        if len(xi) == 0:
            return
        zbuf[yi, xi] = dep
        img[yi, xi] = img[yi, xi] * (1 - alpha) + color * alpha

    for y in gx:
        if abs(y) < step * 0.01:
            continue
        draw((-limit, y, 0), (limit, y, 0), line_color, 0.34)
    for x in gx:
        if abs(x) < step * 0.01:
            continue
        draw((x, -limit, 0), (x, limit, 0), line_color, 0.34)
    draw((-limit, 0, 0), (limit, 0, 0), axis_x, 0.55)
    draw((0, -limit, 0), (0, limit, 0), axis_y, 0.55)


def _shade(normals, col, metal, rough, cam):
    f = cam["f"]
    right, up = cam["right"], cam["up"]
    key = _normalize(0.42 * right - 0.62 * up - 0.75 * f)
    fill = _normalize(-0.65 * right + 0.15 * up - 0.35 * f)
    back = _normalize(0.1 * right + 0.8 * up + 0.4 * f)
    n = normals
    diff = np.clip(n @ key, 0, None)[:, None] * 0.72
    diff2 = np.clip(n @ fill, 0, None)[:, None] * 0.24
    rim = np.clip(n @ back, 0, None)[:, None] * 0.16
    amb = (0.17 + 0.10 * np.clip(n[:, 2:3] * 0.5 + 0.5, 0, 1))
    col = np.asarray(col, dtype=np.float32)
    if col.ndim == 1:
        col = col[None, :]
    base = col * (amb + diff + diff2 + rim)
    half = _normalize(key - f)
    spec = np.clip(n @ half, 0, None)[:, None] ** max(8, 2 / max(rough, 0.05) ** 2)
    spec_strength = 0.62 * (1 - rough) ** 2
    spec_col = col * (1 - metal) + metal * 0.9
    shade = base + spec * spec_strength * spec_col
    return _tonemap(shade)


def _tonemap(x):
    x = np.clip(x, 0, None) * 1.12
    return np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)


def _draw_shadow(img, cam, bbox):
    if cam["f"][2] < -0.9:
        return
    xmin, ymin, zmin, xmax, ymax, zmax = bbox
    corners = np.array([[xmin, ymin, 0.0], [xmax, ymin, 0.0],
                        [xmax, ymax, 0.0], [xmin, ymax, 0.0]])
    scr, _dep = _project(corners, cam)
    cx, cy = scr.mean(axis=0)
    rx = max(4.0, (scr[:, 0].max() - scr[:, 0].min()) / 2 * 1.15)
    ry = max(3.0, (scr[:, 1].max() - scr[:, 1].min()) / 2 * 1.1)
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    alpha = 0.42 * np.exp(-2.6 * d) * (d < 2.2)
    img *= (1.0 - alpha)[:, :, None]


def _render_view(meshes, center, radius, view, size, ss, bbox, grid=True,
                 shadow=True, bg=None):
    W = size * ss
    cam = _camera(center, radius, view, W, W)
    if bg is None:
        img = _background(cam).astype(np.float32)
    else:
        img = np.ones((cam["h"], cam["w"], 3), dtype=np.float32) * np.array(bg, dtype=np.float32)
    zbuf = np.full((cam["h"], cam["w"]), np.inf, dtype=np.float64)
    if shadow:
        _draw_shadow(img, cam, bbox)
    if grid:
        _draw_grid(img, zbuf, cam, bbox)

    f = cam["f"]
    for mesh in meshes:
        verts = mesh["verts"]
        faces = mesh["faces"]
        normals = mesh["normals"]
        col = mesh["color"]
        metal = mesh["metal"]
        rough = mesh["rough"]
        uv = mesh.get("uv")
        tex = mesh.get("tex")
        scr, dep = _project(verts, cam)
        tri = faces
        n0, n1, n2 = normals[tri[:, 0]], normals[tri[:, 1]], normals[tri[:, 2]]
        # отсечение задних граней по геометрической нормали
        e1 = verts[tri[:, 1]] - verts[tri[:, 0]]
        e2 = verts[tri[:, 2]] - verts[tri[:, 0]]
        fn = np.cross(e1, e2)
        facing = np.einsum("ij,j->i", fn, f) < 0
        idx = np.nonzero(facing)[0]

        for ti in idx:
            a = tri[ti]
            p = scr[a]
            d = dep[a]
            x0, y0 = p[0]
            x1, y1 = p[1]
            x2, y2 = p[2]
            minx = int(max(0, math.floor(min(x0, x1, x2))))
            maxx = int(min(W - 1, math.ceil(max(x0, x1, x2))))
            miny = int(max(0, math.floor(min(y0, y1, y2))))
            maxy = int(min(W - 1, math.ceil(max(y0, y1, y2))))
            if minx > maxx or miny > maxy:
                continue
            area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
            if abs(area) < 1e-12:
                continue
            xs = np.arange(minx, maxx + 1, dtype=np.float64) + 0.5
            ys = np.arange(miny, maxy + 1, dtype=np.float64) + 0.5
            X, Y = np.meshgrid(xs, ys)
            w0 = ((x1 - X) * (y2 - Y) - (x2 - X) * (y1 - Y)) / area
            w1 = ((x2 - X) * (y0 - Y) - (x0 - X) * (y2 - Y)) / area
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            depth = w0 * d[0] + w1 * d[1] + w2 * d[2]
            sub_z = zbuf[miny:maxy + 1, minx:maxx + 1]
            front = inside & (depth < sub_z)
            if not front.any():
                continue
            nx = w0 * n0[ti, 0] + w1 * n1[ti, 0] + w2 * n2[ti, 0]
            ny = w0 * n0[ti, 1] + w1 * n1[ti, 1] + w2 * n2[ti, 1]
            nz = w0 * n0[ti, 2] + w1 * n1[ti, 2] + w2 * n2[ti, 2]
            ln = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-12
            nn = np.stack([(nx / ln)[front], (ny / ln)[front], (nz / ln)[front]], axis=1)
            colors = col
            if uv is not None and tex is not None:
                u = (w0 * uv[a[0], 0] + w1 * uv[a[1], 0] + w2 * uv[a[2], 0])
                vv = (w0 * uv[a[0], 1] + w1 * uv[a[1], 1] + w2 * uv[a[2], 1])
                th, tw = tex.shape[:2]
                uu = (u[front] % 1.0) * tw - 0.5
                vv2 = (1.0 - np.clip(vv[front], 0, 1)) * th - 0.5
                u0 = np.floor(uu).astype(np.int32)
                v0 = np.floor(vv2).astype(np.int32)
                fx = (uu - u0)[:, None]
                fy = (vv2 - v0)[:, None]
                u1 = (u0 + 1) % tw
                v1 = (v0 + 1) % th
                u0 %= tw
                v0 %= th
                colors = (tex[v0, u0] * (1 - fx) * (1 - fy) + tex[v0, u1] * fx * (1 - fy)
                          + tex[v1, u0] * (1 - fx) * fy + tex[v1, u1] * fx * fy) * col[None, :]
            shade = _shade(nn, colors, metal, rough, cam)
            shade = np.clip(shade, 0, 1)
            sub_img = img[miny:maxy + 1, minx:maxx + 1]
            sub_img[front] = shade.astype(np.float32)
            sub_z[front] = depth[front]
            zbuf[miny:maxy + 1, minx:maxx + 1] = sub_z

    # контурное затемнение по глубине
    finite = np.isfinite(zbuf)
    if finite.any():
        zf = np.where(finite, zbuf, np.nan)
        gx = np.abs(np.diff(zf, axis=1, prepend=np.nan))
        gy = np.abs(np.diff(zf, axis=0, prepend=np.nan))
        edge = np.nan_to_num(np.maximum(gx, gy) / max(cam["scale"] * 2.0, 1e-9))
        edge = np.clip(edge, 0, 1) * finite
        img *= (1.0 - 0.22 * edge)[:, :, None]

    # уменьшение (сглаживание)
    if ss > 1:
        img = img.reshape(size, ss, size, ss, 3).mean(axis=(1, 3))
    return np.clip(img, 0, 1), cam


def _compose(images, gap=8, bg=(0.055, 0.062, 0.078)):
    if len(images) == 1:
        return images[0]
    h, w = images[0].shape[:2]
    n = len(images)
    if n == 4:
        cols = 2
    elif n == 3:
        cols = 3
    else:
        cols = n
    rows = int(math.ceil(n / cols))
    canvas = np.zeros((rows * h + (rows - 1) * gap, cols * w + (cols - 1) * gap, 3),
                      dtype=np.float32)
    canvas[:] = np.array(bg, dtype=np.float32)
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        y = r * (h + gap)
        x = c * (w + gap)
        canvas[y:y + h, x:x + w] = im
    return canvas


def _to_bytes(img: np.ndarray) -> np.ndarray:
    return (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)


def render_views(solids, out_dir, prefix="model", size=640, ss=2,
                 views=("iso", "front", "right", "top"), combined=True) -> dict:
    """Рендерит набор видов. Возвращает пути к PNG и массив общего вида."""
    meshes = _prepare(solids)
    if not meshes:
        raise ValueError("Нет объектов для рендера.")
    allv = np.concatenate([m["verts"] for m in meshes], axis=0)
    lo = allv.min(axis=0)
    hi = allv.max(axis=0)
    bbox = [float(lo[0]), float(lo[1]), float(lo[2]), float(hi[0]), float(hi[1]), float(hi[2])]
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo)) / 2
    os.makedirs(out_dir, exist_ok=True)

    files = []
    images = []
    for view in views:
        img, _cam = _render_view(meshes, center, radius, view, size, ss, bbox)
        arr = _to_bytes(img)
        path = os.path.join(out_dir, f"{prefix}_{view}.png")
        write_png(path, arr)
        files.append({"view": view, "label": VIEW_LABELS.get(view, view), "path": path})
        images.append(img)
    result = {"files": files, "bbox": bbox}
    if combined and len(images) > 1:
        canvas = _to_bytes(_compose(images))
        path = os.path.join(out_dir, f"{prefix}_all.png")
        write_png(path, canvas)
        result["combined"] = path
    return result


def render_single(solids, out_dir, filename="preview.png", size=720, ss=2,
                  view="iso") -> str:
    meshes = _prepare(solids)
    if not meshes:
        raise ValueError("Нет объектов для рендера.")
    allv = np.concatenate([m["verts"] for m in meshes], axis=0)
    lo = allv.min(axis=0)
    hi = allv.max(axis=0)
    bbox = [float(lo[0]), float(lo[1]), float(lo[2]), float(hi[0]), float(hi[1]), float(hi[2])]
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo)) / 2
    img, _ = _render_view(meshes, center, radius, view, size, ss, bbox)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    write_png(path, _to_bytes(img))
    return path
