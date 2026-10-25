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
    # камера стоит там, куда смотрит вектор: «спереди» — со стороны −Y,
    # как в окне просмотра (иначе отчёт показывал обратную сторону детали)
    "iso": ((0.92, -1.25, 0.78), (0.0, 0.0, 1.0)),
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    # обратные стороны: нужны там, где важно посмотреть крепёж сзади
    # (задняя стенка шкафа, гвозди) или левую боковину
    "back": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "bottom": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "iso_back": ((-0.92, 1.25, 0.78), (0.0, 0.0, 1.0)),
}
VIEW_LABELS = {"iso": "изометрия", "front": "спереди", "right": "справа", "top": "сверху",
               "back": "сзади", "left": "слева", "bottom": "снизу",
               "iso_back": "изометрия сзади"}

BG_TOP = np.array([0.105, 0.118, 0.145], dtype=np.float32)
BG_BOTTOM = np.array([0.045, 0.052, 0.068], dtype=np.float32)


def _normalize(v):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _load_texture(path: str, size: int = 256):
    try:
        from .geometry import read_png, resize_rgb
        arr = read_png(path)
        if arr is None:
            return None
        return resize_rgb(arr, size).astype(np.float32) / 255.0
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
            "paint": None, "brush": None,
            "metal": float(s.metal), "rough": float(s.rough),
            "emissive": (np.array(color_to_float_rgb(s.emissive), dtype=np.float32)
                         if getattr(s, "emissive", "") else None),
            "glow": float(getattr(s, "emissive_strength", 1.0) or 1.0),
            "alpha": 1.0 - 0.8 * float(getattr(s, "transmission", 0.0) or 0.0),
            "uv": None, "tex": None,
        }
        # регионная покраска: цвет каждого треугольника (после расщепления
        # рёбер вершины те же, поэтому классификация по центрам работает)
        if getattr(s, "paint", None):
            # регионы держим как есть и считаем цвет на каждый пиксель —
            # так граница полосы ровная, без зубцов по треугольникам
            item["paint"] = list(s.paint)
        if getattr(s, "brush", None):
            # мазки кистью и ластика: тоже считаем на каждый пиксель
            item["brush"] = list(s.brush)
        tex = getattr(s, "tex", None)
        if tex and tex.get("path"):
            image = _load_texture(tex["path"])
            if image is not None:
                from .textures import uv_triangles
                # Та же развёртка, что у GLB и окна: трипланарная по мировым
                # координатам. Раньше здесь была цилиндрическая — на плоских
                # фасадах шкафа рисунок сжимался в вертикальные полосы, а в
                # окне и в Blender выглядел правильно. Теперь одинаково везде.
                gltf = np.stack([nv[:, 0], nv[:, 2], -nv[:, 1]], axis=1)
                uvs = uv_triangles(gltf, nf, getattr(s, "uv", "auto") or "auto",
                                   tile_mm=float(tex.get("tile_mm") or 140.0))
                flat = nf.reshape(-1)
                item["uv"] = uvs
                item["tex"] = image
                item["verts"] = nv[flat]
                item["normals"] = nn[flat]
                item["faces"] = np.arange(len(flat), dtype=np.int64).reshape(-1, 3)
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
    # Свет сверху (небо) + отражение от пола снизу: нижние грани больше не чёрные.
    nz = n[:, 2:3]
    amb = (0.28 + 0.10 * np.clip(nz * 0.5 + 0.5, 0, 1))
    # Отражение от пола: светим снизу тем сильнее, чем «ниже» смотрит нормаль.
    bounce = 0.38 * np.clip(-nz, 0, 1) ** 0.8 + 0.05
    col = np.asarray(col, dtype=np.float32)
    if col.ndim == 1:
        col = col[None, :]
    # у металла диффузной составляющей почти нет: свет он отражает, а не рассеивает
    base = col * (amb + bounce + diff + diff2 + rim) * (1.0 - 0.85 * metal)
    half = _normalize(key - f)
    spec = np.clip(n @ half, 0, None)[:, None] ** max(8, 2 / max(rough, 0.05) ** 2)
    spec_strength = 0.62 * (1 - rough) ** 2
    spec_col = col * (1 - metal) + metal * 0.9
    shade = base + spec * spec_strength * spec_col
    if metal > 0.02:
        # Отражение окружения: без карты окружения металл в офлайн-снимке
        # выглядел серым пятном. Берём простое «небо над горизонтом» и
        # отражаем его по нормали — зеркало и сталь сразу читаются как
        # полированные, а не как матовая краска.
        ref = 2.0 * (n @ f)[:, None] * n - f[None, :]
        t = np.clip(ref[:, 2:3] * 0.5 + 0.5, 0, 1)
        # «студия»: тёмный пол, светлая стена, яркая полоса-софтбокс сверху
        ground = np.array([0.10, 0.11, 0.14], dtype=np.float32)
        sky = np.array([0.72, 0.79, 0.92], dtype=np.float32)
        env = ground[None, :] * (1 - t) + sky[None, :] * t
        band = np.exp(-((ref[:, 2:3] - 0.72) ** 2) / (2 * 0.13 ** 2))
        env = env + band * np.array([1.0, 0.96, 0.88], dtype=np.float32) * 0.7
        # резкость отражения: гладкий металл почти как зеркало, матовый — мутный
        k_env = metal * (1.0 - min(rough, 0.95)) ** 1.4
        shade = shade + env * k_env * 1.15 * (0.35 + 0.65 * col)
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


def _mirror_ids(meshes) -> list[int]:
    """Индексы зеркальных деталей: гладкий металл, без прозрачности."""
    ids = []
    for i, m in enumerate(meshes):
        if float(m.get("alpha", 1.0)) < 0.999:
            continue
        if float(m.get("metal", 0.0)) >= 0.85 and float(m.get("rough", 0.5)) <= 0.12:
            ids.append(i)
    return ids


def _scene_triangles(meshes, skip: set[int]):
    """Треугольники сцены одним массивом + цвет грани: для трассировки лучей."""
    tris, cols = [], []
    for i, m in enumerate(meshes):
        if i in skip:
            continue
        v = m["verts"]
        f = m["faces"]
        if len(f) == 0:
            continue
        tris.append(np.asarray(v, dtype=np.float64)[f])
        cols.append(np.repeat(np.asarray(m["color"], dtype=np.float32)[None, :],
                              len(f), axis=0))
    if not tris:
        return None, None
    return np.concatenate(tris, axis=0), np.concatenate(cols, axis=0)


def _trace_rays(orig, dirs, tri, pix_chunk: int = 48, tri_chunk: int = 1024):
    """Ближайшее пересечение лучей с треугольниками (Мёллер–Трумберт)."""
    v0 = tri[:, 0]
    e1 = tri[:, 1] - v0
    e2 = tri[:, 2] - v0
    n_rays = len(orig)
    best_t = np.full(n_rays, np.inf, dtype=np.float64)
    best_i = np.full(n_rays, -1, dtype=np.int32)
    for s in range(0, n_rays, pix_chunk):
        e = min(n_rays, s + pix_chunk)
        o = orig[s:e][:, None, :]
        d = dirs[s:e][:, None, :]
        local_t = np.full(e - s, np.inf, dtype=np.float64)
        local_i = np.full(e - s, -1, dtype=np.int32)
        for c0 in range(0, len(tri), tri_chunk):
            c1 = min(len(tri), c0 + tri_chunk)
            v0c, e1c, e2c = v0[c0:c1], e1[c0:c1], e2[c0:c1]
            pvec = np.cross(d, e2c[None, :, :])
            det = np.einsum("cik,ik->ci", pvec, e1c)
            ok = np.abs(det) > 1e-9
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            tvec = o - v0c[None, :, :]
            u = np.einsum("cik,cik->ci", tvec, pvec) * inv
            qvec = np.cross(tvec, e1c[None, :, :])
            v = np.einsum("cik,cik->ci", d, qvec) * inv
            t = np.einsum("cik,ik->ci", qvec, e2c) * inv
            good = (ok & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (t > 1e-4))
            tt = np.where(good, t, np.inf)
            j = np.argmin(tt, axis=1)
            tv = tt[np.arange(len(j)), j]
            better = tv < local_t
            local_t[better] = tv[better]
            local_i[better] = j[better] + c0
        best_t[s:e] = local_t
        best_i[s:e] = local_i
    return best_t, best_i


def _mirror_pass(img, meshes, cam, nbuf, idbuf, pbuf, mirror_ids, ss: int = 1,
                 budget: int = 32_000_000):
    """Настоящее отражение соседей: луч от зеркального пикселя в сцену.

    Без этого металл отражал только «студию» из шейдера, и зеркало рядом с
    объектом выглядело пустым. Луч пускаем по нормали из G-буфера: попадание
    красим цветом детали с мягким светом, промах оставляем окружению.
    """
    h, w = img.shape[:2]
    if pbuf is None or nbuf is None or idbuf is None:
        return img
    ids = np.array([i + 1 for i in mirror_ids], dtype=np.int32)
    mask = np.isin(idbuf, ids)
    if not mask.any():
        return img
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return img
    tri, cols = _scene_triangles(meshes, set(mirror_ids))
    if tri is None:
        return img
    # бюджет: если лучей и треугольников слишком много, реже берём пиксели,
    # а промежутки потом заполняем размытием по покрытию
    pairs = float(len(ys)) * float(len(tri))
    stride = 1
    if pairs > budget:
        stride = int(np.ceil(np.sqrt(pairs / budget)))
        keep = (ys % stride == 0) & (xs % stride == 0)
        ys, xs = ys[keep], xs[keep]
        if len(ys) == 0:
            return img
    n = np.asarray(nbuf[ys, xs], dtype=np.float64)
    ln = np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    n = n / ln
    orig = np.asarray(pbuf[ys, xs], dtype=np.float64)
    view_dir = orig - cam["eye"][None, :]
    vlen = np.linalg.norm(view_dir, axis=1, keepdims=True) + 1e-12
    view_dir = view_dir / vlen
    # отражение направления взгляда относительно нормали
    dots = np.einsum("ij,ij->i", view_dir, n)[:, None]
    dirs = view_dir - 2.0 * dots * n
    dlen = np.linalg.norm(dirs, axis=1, keepdims=True) + 1e-12
    dirs = dirs / dlen
    eps = max(1e-3, float(np.linalg.norm(cam["up"])) * 0 + 1e-3)
    orig = orig + n * eps
    t_hit, i_hit = _trace_rays(orig, dirs, tri)

    hit = i_hit >= 0
    if not hit.any():
        return img
    pix = (ys[hit], xs[hit])
    # сила отражения как у шейдера: гладкий металл почти зеркало
    mesh_of = {i + 1: i for i in mirror_ids}
    strength = np.ones(len(pix[0]), dtype=np.float32)
    for value, index in mesh_of.items():
        sel = idbuf[pix] == value
        if sel.any():
            m = meshes[index]
            k = float(m.get("metal", 1.0)) * (1.0 - min(float(m.get("rough", 0.1)), 0.95)) ** 1.4
            strength[sel] = min(max(k, 0.0), 1.0) * 1.05

    # нормаль грани для мягкого света и цвет детали
    tsel = tri[i_hit[hit]]
    fn = np.cross(tsel[:, 1] - tsel[:, 0], tsel[:, 2] - tsel[:, 0])
    fl = np.linalg.norm(fn, axis=1, keepdims=True) + 1e-12
    fn = fn / fl
    key = _normalize(0.42 * cam["right"] - 0.62 * cam["up"] - 0.75 * cam["f"])
    lam = np.clip(fn @ key, 0, None)[:, None]
    hit_col = cols[i_hit[hit]]
    # отражение показывает соседа почти как он есть: лёгкий свет, без затемнения
    refl = np.clip(hit_col * (0.66 + 0.42 * lam), 0, 1).astype(np.float32)
    # дальние отражения чуть притухают — так читается глубина сцены
    fade = np.clip(1.0 - t_hit[hit] / (np.max(t_hit[hit]) * 3.0 + 1e-9), 0.72, 1.0)
    refl = refl * fade[:, None].astype(np.float32)
    k = strength[:, None]
    colored = (refl * k).astype(np.float32)
    if stride <= 1:
        # лучей столько же, сколько пикселей: ставим отражение как есть
        img[pix] = np.clip(colored + img[pix] * (1.0 - k), 0, 1)
        return img
    # лучей меньше, чем пикселей: собираем карту низкого разрешения и тянем
    # её билинейно — разреженная сетка иначе выглядит квадратиками
    lh = (h + stride - 1) // stride
    lw = (w + stride - 1) // stride
    gy = ys[hit] // stride
    gx = xs[hit] // stride
    low_acc = np.zeros((lh, lw, 3), dtype=np.float32)
    low_cov = np.zeros((lh, lw), dtype=np.float32)
    np.add.at(low_acc, (gy, gx), colored)
    np.add.at(low_cov, (gy, gx), 1.0)
    holes = low_cov <= 0
    if holes.any():
        # одиночные дырки в карте заполняем соседями
        num = _box_blur(low_acc, 1)
        den = _box_blur(low_cov[..., None], 1)[..., 0]
        soft = num / np.maximum(den[..., None], 1e-6)
        low_acc = np.where(holes[..., None], soft, low_acc)
        low_cov = np.where(holes, np.minimum(den, 1.0), low_cov)
    low = low_acc / np.maximum(low_cov[..., None], 1e-6)
    up = _upsample_bilinear(low, h, w, stride)
    cov_up = _upsample_bilinear(low_cov[..., None], h, w, stride)[..., 0]
    where = mask & (cov_up > 0.25)
    img[where] = np.clip(up[where], 0, 1)
    return img


def _render_view(meshes, center, radius, view, size, ss, bbox, grid=True,
                 shadow=True, bg=None, style=None):
    # Аниме/манга: контуры и тон считаются по буферам глубины и нормалей.
    # Стиль задаёт и фон («бумагу»), и отключение сетки — иначе рисунок пестрит.
    from .anime import normalize_style
    st = normalize_style(style) if style else None
    anime = st is not None and st["mode"] != "выкл"
    if anime:
        grid = False
        if st.get("paper"):
            bg = tuple(color_to_float_rgb(st["paper"]))
        if st["mode"] in ("манга", "линия"):
            shadow = False
    W = size * ss
    cam = _camera(center, radius, view, W, W)
    if bg is None:
        img = _background(cam).astype(np.float32)
    else:
        img = np.ones((cam["h"], cam["w"], 3), dtype=np.float32) * np.array(bg, dtype=np.float32)
    zbuf = np.full((cam["h"], cam["w"]), np.inf, dtype=np.float64)
    # зеркала тоже нуждаются в нормалях и позициях — по ним пускаются лучи
    mirror_ids = _mirror_ids(meshes)
    geom = anime or bool(mirror_ids)
    nbuf = np.zeros((cam["h"], cam["w"], 3), dtype=np.float32) if geom else None
    idbuf = np.zeros((cam["h"], cam["w"]), dtype=np.int32) if geom else None
    pbuf = (np.zeros((cam["h"], cam["w"], 3), dtype=np.float64)
            if mirror_ids else None)
    # маска свечения нужна и без аниме: по ней рисуется ореол светодиодов
    has_emissive = any(m.get("emissive") is not None for m in meshes)
    ebuf = (np.zeros((cam["h"], cam["w"]), dtype=bool)
            if (anime or has_emissive) else None)
    # цвет источников: ореол строится по нему, а не по уже затемнённому кадру
    gbuf = (np.zeros((cam["h"], cam["w"], 3), dtype=np.float32)
            if has_emissive else None)
    if shadow:
        _draw_shadow(img, cam, bbox)
    if grid:
        _draw_grid(img, zbuf, cam, bbox)

    f = cam["f"]
    # прозрачные тела (стекло) рисуем последними и смешиваем с уже готовым
    # кадром: иначе они закрывают то, что должно быть видно сквозь них
    meshes = sorted(meshes, key=lambda m: m.get("alpha", 1.0) < 0.999)
    mirror_ids = _mirror_ids(meshes)
    _mirror_set = set(mirror_ids)
    for mesh_index, mesh in enumerate(meshes):
        verts = mesh["verts"]
        faces = mesh["faces"]
        normals = mesh["normals"]
        col = mesh["color"]
        metal = mesh["metal"]
        rough = mesh["rough"]
        uv = mesh.get("uv")
        tex = mesh.get("tex")
        paint = mesh.get("paint")
        brush = mesh.get("brush")
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
            if paint is not None or brush is not None:
                from .geometry import surface_point_colors
                # положение пикселя в координатах сценария (Z вверх)
                pos = (w0[front, None] * verts[a[0]] + w1[front, None] * verts[a[1]]
                       + w2[front, None] * verts[a[2]])
                # снимок считается прямо в координатах сценария (Z вверх),
                # поэтому точка и нормаль идут как есть
                colors = surface_point_colors(col, paint, brush, pos, nn)
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
                base = colors
                colors = (tex[v0, u0] * (1 - fx) * (1 - fy) + tex[v0, u1] * fx * (1 - fy)
                          + tex[v1, u0] * (1 - fx) * fy + tex[v1, u1] * fx * fy) * base
            alpha = float(mesh.get("alpha", 1.0))
            emis = mesh.get("emissive")
            if emis is not None:
                # Светодиод не затеняется: он сам источник света. Лёгкий
                # градиент по нормали оставляет объём, чтобы грань не «плоскала».
                ang = np.clip(nn @ _normalize(0.3 * cam["right"] - 0.4 * cam["up"]
                                              - 0.85 * cam["f"]), 0, 1)[:, None]
                # Источник света: яркость растёт со strength, но оттенок не
                # выцветает — поднимаем цвет целиком, а не к белому.
                hot = np.clip(emis * (0.86 + 0.10 * min(float(mesh.get("glow", 1.0)), 5.0)),
                              0, 1)
                shade = np.clip(hot[None, :] * (0.80 + 0.20 * ang), 0, 1)
            else:
                shade = _shade(nn, colors, metal, rough, cam)
            shade = np.clip(shade, 0, 1)
            sub_img = img[miny:maxy + 1, minx:maxx + 1]
            if alpha >= 0.999:
                # G-буфер для контуров: нормаль, номер детали, свечение
                if nbuf is not None:
                    nbuf[miny:maxy + 1, minx:maxx + 1][front] = nn.astype(np.float32)
                if idbuf is not None:
                    idbuf[miny:maxy + 1, minx:maxx + 1][front] = mesh_index + 1
                if emis is not None:
                    if ebuf is not None:
                        ebuf[miny:maxy + 1, minx:maxx + 1][front] = True
                    if gbuf is not None:
                        gbuf[miny:maxy + 1, minx:maxx + 1][front] = hot
                if pbuf is not None and mesh_index in _mirror_set:
                    pos = (w0[front, None] * verts[a[0]] + w1[front, None] * verts[a[1]]
                           + w2[front, None] * verts[a[2]])
                    pbuf[miny:maxy + 1, minx:maxx + 1][front] = pos
            if alpha < 0.999:
                # стекло: смешиваем, но глубину не пишем — сквозь него видны
                # детали, которые лежат глубже
                sub_img[front] = (sub_img[front] * (1 - alpha)
                                  + shade * alpha).astype(np.float32)
            else:
                sub_img[front] = shade.astype(np.float32)
                sub_z[front] = depth[front]
                zbuf[miny:maxy + 1, minx:maxx + 1] = sub_z

    # отражения в зеркальных деталях: видим в них соседей, а не только студию
    if mirror_ids:
        img = _mirror_pass(img, meshes, cam, nbuf, idbuf, pbuf, mirror_ids, ss)

    # свечение светодиодов: мягкий ореол вокруг ярких мест (только там,
    # где источник реально виден — иначе цифры «просвечивают» сквозь корпус)
    if has_emissive and ebuf is not None:
        img = _glow_pass(img, ebuf, cam, source=gbuf)

    if anime:
        from .anime import apply_style
        img = apply_style(img, zbuf, nbuf, idbuf, ebuf, st, ss)

    # контурное затемнение по глубине (обычный вид)
    finite = np.isfinite(zbuf)
    if finite.any() and not anime:
        zf = np.where(finite, zbuf, np.nan)
        gx = np.abs(np.diff(zf, axis=1, prepend=np.nan))
        gy = np.abs(np.diff(zf, axis=0, prepend=np.nan))
        # резкие уступы (буквы, фаски, канавки) должны читаться: слабый
        # градиент глубины усиливаем, плавные скругления остаются гладкими
        edge = np.nan_to_num(np.maximum(gx, gy) / max(cam["scale"] * 2.0, 1e-9))
        edge = np.clip(edge * 3.0, 0, 1) * finite
        img *= (1.0 - 0.32 * edge)[:, :, None]

    # уменьшение (сглаживание)
    if ss > 1:
        img = img.reshape(size, ss, size, ss, 3).mean(axis=(1, 3))
    return np.clip(img, 0, 1), cam


def _box_blur(arr: np.ndarray, radius: int) -> np.ndarray:
    """Мягкое размытие кумулятивными суммами — без Pillow и scipy."""
    r = max(1, int(radius))
    out = arr.astype(np.float32)
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        pad[axis] = (r, r)
        padded = np.pad(out, pad, mode="edge")
        zero_shape = list(padded.shape)
        zero_shape[axis] = 1
        prof = np.cumsum(np.concatenate([np.zeros(zero_shape, dtype=np.float64),
                                         padded.astype(np.float64)], axis=axis), axis=axis)
        n = out.shape[axis]
        hi = np.take(prof, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
        lo = np.take(prof, np.arange(0, n), axis=axis)
        out = ((hi - lo) / (2 * r + 1)).astype(np.float32)
    return out


def _upsample_bilinear(low: np.ndarray, h: int, w: int, stride: int) -> np.ndarray:
    """Растягивает карту низкого разрешения билинейно — без «квадратиков»."""
    lh, lw = low.shape[:2]
    ys = np.clip((np.arange(h) + 0.5) / stride - 0.5, 0, lh - 1)
    xs = np.clip((np.arange(w) + 0.5) / stride - 0.5, 0, lw - 1)
    y0 = np.floor(ys).astype(np.int32)
    x0 = np.floor(xs).astype(np.int32)
    y1 = np.minimum(y0 + 1, lh - 1)
    x1 = np.minimum(x0 + 1, lw - 1)
    fy = (ys - y0)[:, None, None]
    fx = (xs - x0)[None, :, None]
    top = low[y0][:, x0] * (1.0 - fx) + low[y0][:, x1] * fx
    bottom = low[y1][:, x0] * (1.0 - fx) + low[y1][:, x1] * fx
    return (top * (1.0 - fy) + bottom * fy).astype(np.float32)


def _glow_pass(img: np.ndarray, glow: np.ndarray, cam, radius: int | None = None,
               source: np.ndarray | None = None) -> np.ndarray:
    """Свечение: размывает только видимые светящиеся пиксели и складывает с кадром.

    Маска ``glow`` берётся из буфера деталей: она уже учитывает перекрытия,
    поэтому ореол не «просвечивает» сквозь корпус и стекло. ``source`` —
    собственный цвет источников (яркий), чтобы ореол не бледнел через стекло.
    """
    h, w = img.shape[:2]
    mask = np.asarray(glow, dtype=bool)
    if not mask.any():
        return img
    bright = np.asarray(source, dtype=np.float32) * mask[..., None] if source is not None \
        else img * mask[..., None]
    r = int(radius or max(5, w // 70))
    halo = _box_blur(bright, r)
    halo = _box_blur(halo, max(1, r // 2))
    halo = _box_blur(halo, max(1, r // 3))
    # ореол цветной: он подмешивается, но не должен выбеливать сам светодиод
    halo *= 1.0
    out = np.array(img, dtype=np.float32, copy=True)
    # сам источник оставляем ярким, ореол кладём вокруг
    out = np.clip(out + halo, 0, 1)
    return out


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
                 views=("iso", "front", "right", "top"), combined=True,
                 style=None) -> dict:
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
        img, _cam = _render_view(meshes, center, radius, view, size, ss, bbox, style=style)
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
                  view="iso", style=None) -> str:
    meshes = _prepare(solids)
    if not meshes:
        raise ValueError("Нет объектов для рендера.")
    allv = np.concatenate([m["verts"] for m in meshes], axis=0)
    lo = allv.min(axis=0)
    hi = allv.max(axis=0)
    bbox = [float(lo[0]), float(lo[1]), float(lo[2]), float(hi[0]), float(hi[1]), float(hi[2])]
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo)) / 2
    img, _ = _render_view(meshes, center, radius, view, size, ss, bbox, style=style)
    os.makedirs(out_dir, exist_ok=True)
    # Имя без расширения — дописываем .png: иначе файл «есть», а открыть его
    # просмотрщиком нельзя.
    if not os.path.splitext(filename)[1]:
        filename += ".png"
    path = os.path.join(out_dir, filename)
    write_png(path, _to_bytes(img))
    return path
