"""Исследовательская проверка MuJoCo 4 для задачи драпировки.

Это НЕ решатель приложения: параметры и масштаб подобраны только для двух
контрольных сцен. Цель — измерить, а не обещать, поведение альтернативного
контакта на исходной замкнутой поверхности.
Нужны отдельное окружение с mujoco-core==4.0.0 и, для FCL, python-fcl.

Пример из корня репозитория:
    OPENBLAS_NUM_THREADS=1 PYTHONPATH=forma python \
        forma/tools/drape_mujoco_probe.py --sides 16 --steps 200
"""
from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma import cloth  # noqa: E402
from forma.cloth_check import self_intersections  # noqa: E402
from forma.geometry import manifold_mesh  # noqa: E402
from forma.run import build  # noqa: E402
from audit_drape_sleeve import _fcl_audit, _fcl_object  # noqa: E402


def input_mesh(case: str, sides: int, *, refine=True):
    if case == 'sleeve':
        source = f"""
пол = box size=[150,100,6] at=[0,0,-6]
рукав = pipe length=70 diameter=22 wall=0.6 sides={sides} at=[0,0,40]
"""
        body_name, support_names, step, budget = 'рукав', ['пол'], 6., 5000
    else:
        # Геометрия соответствует обычной испытательной сцене 0.77.
        source = """
пол = box size=[620,200,6] at=[0,0,-6]
болванка_стола = box size=[80,80,40] round=12 at=[150,0,0]
срез_под_столом = box size=[100,100,21] at=[150,0,-1]
столешница = difference [болванка_стола,срез_под_столом]
ножка_левая_передняя = box size=[7,7,20] at=[122,-28,0]
ножка_правая_передняя = box size=[7,7,20] at=[178,-28,0]
ножка_левая_задняя = box size=[7,7,20] at=[122,28,0]
ножка_правая_задняя = box size=[7,7,20] at=[178,28,0]
лист = box size=[120,120,0.6] at=[150,0,70]
"""
        body_name = 'лист'
        support_names = ['пол', 'столешница', 'ножка_левая_передняя', 'ножка_правая_передняя',
                         'ножка_левая_задняя', 'ножка_правая_задняя']
        step, budget = 6.8, 2500
    scene = build(source, analyze_model=False)
    if not scene.ok:
        raise RuntimeError(str(scene.error))
    vertices, faces = manifold_mesh(scene.scene.objects[body_name].manifold)
    if refine:
        vertices, faces = cloth.subdivide_to(vertices, faces, step, budget)
    supports = {name: manifold_mesh(scene.scene.objects[name].manifold) for name in support_names}
    support_tri = np.concatenate([v[f] for v, f in supports.values()])
    position = cloth.place(vertices, support_tri, np.array([0., 0., -1.]), 0.25)
    return vertices, faces, position, supports


def combined_support(supports):
    vertices, faces = [], []
    offset = 0
    for v, f in supports.values():
        vertices.append(v)
        faces.append(f + offset)
        offset += len(v)
    return np.vstack(vertices), np.vstack(faces)


def support_fcl(position, faces, supports):
    try:
        import fcl
    except ImportError:
        return None
    body = _fcl_object(fcl, position, faces)
    answer = {}
    for name, support in supports.items():
        result = fcl.CollisionResult()
        count = fcl.collide(body, _fcl_object(fcl, *support),
                            fcl.CollisionRequest(num_max_contacts=1), result)
        answer[name] = bool(count)  # Пересечение поверхности ИЛИ касание.
    return answer


def _numbers(array):
    return " ".join(str(value) for value in np.asarray(array).ravel())


class TrajectoryAudit:
    """Дополнительная CCD-проверка линейных отрезков между шагами, не решатель."""

    def __init__(self, position, faces, supports, min_distance=0.):
        try:
            import ipctk
        except ImportError as exc:
            raise RuntimeError('Для --ccd нужен ipctk в исследовательском окружении') from exc
        if min_distance < 0:
            raise ValueError('CCD: отрицательный зазор')
        ipctk.set_num_threads(1)
        self.ipctk = ipctk
        self.boundary = np.unique(faces)
        local = np.full(len(position), -1, dtype=int)
        local[self.boundary] = np.arange(len(self.boundary))
        static_v, static_f = combined_support(supports)
        count = len(self.boundary)
        all_faces = np.vstack((local[faces], static_f + count)).astype(np.int32)
        self.static = np.asarray(static_v, dtype=float)
        initial = self.points(position)
        edges = cloth._edge_arrays(all_faces).astype(np.int32)
        self.mesh = ipctk.CollisionMesh(initial, edges, all_faces)
        self.mesh.can_collide = ipctk.make_static_obstacle_filter(count)
        self.mesh.init_adjacencies()
        self.min_distance = float(min_distance)
        if ipctk.has_intersections(self.mesh, initial):
            raise RuntimeError('CCD: исходная позиция после размещения уже пересекается')
        # Дополнительно проверяем неподвижный первый отрезок, включая
        # запрошенный зазор, а не только собственно пересечения.
        if not ipctk.is_step_collision_free(self.mesh, initial, initial, self.min_distance):
            raise RuntimeError('CCD: исходный зазор после размещения не выдержан')
        self.previous = initial
        self.steps = 0
        self.seconds = 0.

    def points(self, position):
        return np.ascontiguousarray(np.vstack((position[self.boundary], self.static)), dtype=float)

    def check(self, position):
        current = self.points(position)
        start = time.perf_counter()
        safe = self.ipctk.is_step_collision_free(self.mesh, self.previous, current, self.min_distance)
        self.seconds += time.perf_counter() - start
        self.steps += 1
        self.previous = current
        return bool(safe)


def tet_boundary(vertices, tetrahedra):
    """Ориентированные тетраэдры и их внешняя треугольная граница."""
    tets = np.asarray(tetrahedra, dtype=np.int64).copy()
    if not len(tets):
        raise ValueError('Нет тетраэдров')
    p = vertices[tets]
    determinant = np.linalg.det(np.stack((p[:, 1] - p[:, 0], p[:, 2] - p[:, 0],
                                          p[:, 3] - p[:, 0]), axis=2))
    if np.any(np.abs(determinant) < 1e-12):
        raise ValueError('В объёмной сетке есть вырожденные тетраэдры')
    negative = determinant < 0
    tets[negative, :2] = tets[negative, 1::-1]
    tet_faces = np.concatenate([tets[:, ids] for ids in ([1, 2, 3], [0, 3, 2],
                                                          [0, 1, 3], [0, 2, 1])])
    _keys, first, repeats = np.unique(np.sort(tet_faces, axis=1), axis=0,
                                       return_index=True, return_counts=True)
    if np.any(repeats > 2):
        raise ValueError('Неманифольная стенка тетраэдров')
    return tet_faces[first[repeats == 1]], tets, float(np.sum(np.abs(determinant)) / 6.)


def sampled_surface_distance(points, vertices, faces):
    """Максимум расстояний перечисленных точек до треугольной поверхности."""
    tri = vertices[faces]
    if not len(tri) or not len(points):
        return float('nan')
    chunk = max(1, min(len(points), 300_000 // len(tri)))
    maximum = 0.
    for start in range(0, len(points), chunk):
        group = points[start:start + chunk]
        query = np.repeat(group, len(tri), axis=0)
        targets = np.tile(tri, (len(group), 1, 1))
        closest = cloth._closest_on_triangles(query, targets)
        distance = np.linalg.norm(closest - query, axis=1).reshape(len(group), len(tri))
        maximum = max(maximum, float(np.max(np.min(distance, axis=1))))
    return maximum


def surface_samples(vertices, faces):
    """Вершины, середины рёбер и центры граней для оценки, не граница ошибки."""
    edges = cloth._edge_arrays(faces)
    return np.vstack((vertices[np.unique(faces)], vertices[edges].mean(axis=1),
                      vertices[faces].mean(axis=1)))


def changed_surface_distances(vertices, source_faces, boundary_faces):
    """Выборочное различие двух поверхностей с общей индексацией вершин."""
    def keys(faces):
        return {tuple(sorted(face)) for face in faces.tolist()}

    source_keys, boundary_keys = keys(source_faces), keys(boundary_faces)
    source_only = np.asarray([f for f in source_faces if tuple(sorted(f)) not in boundary_keys],
                             dtype=np.int64).reshape(-1, 3)
    boundary_only = np.asarray([f for f in boundary_faces if tuple(sorted(f)) not in source_keys],
                               dtype=np.int64).reshape(-1, 3)
    return {'source_changed_faces': len(source_only), 'boundary_changed_faces': len(boundary_only),
            'sampled_source_to_boundary_mm': sampled_surface_distance(
                surface_samples(vertices, source_only), vertices, boundary_faces) if len(source_only) else 0.,
            'sampled_boundary_to_source_mm': sampled_surface_distance(
                surface_samples(vertices, boundary_only), vertices, source_faces) if len(boundary_only) else 0.,
            'note': 'Вершины, середины рёбер и центры изменённых граней; не полная ошибка Хаусдорфа.'}


def wild_tetrahedra(vertices, faces, eps, edge, iterations):
    """Опциональный опыт с общим тетраэдрализатором; геометрия приближается."""
    try:
        import wildmeshing
    except ImportError as exc:
        raise RuntimeError('Для --wild нужен wildmeshing в исследовательском окружении') from exc
    surface = {'V': vertices, 'cells': {'triangle': {'connectivity': faces}}}
    options = {'input': ['body'], 'filter': 'tracked', 'skip_simplify': True,
               'num_threads': 1, 'max_iterations': iterations, 'eps_rel': eps,
               'length_rel': edge, 'preserve_topology': True, 'throw_on_fail': True}
    outputs, report = wildmeshing.tetwild(options, {'body': surface})
    volume_mesh = outputs['mesh']
    new_vertices = np.asarray(volume_mesh['V'], dtype=float)
    new_faces, tets, tet_volume = tet_boundary(
        new_vertices, volume_mesh['cells']['tetrahedron']['connectivity'])
    if not cloth.is_closed(new_faces):
        raise ValueError('Объёмная сетка не имеет замкнутой границы')
    original_volume, _ = cloth._volume_data(vertices, faces)
    remeshed_volume, _ = cloth._volume_data(new_vertices, new_faces)
    if not np.isclose(tet_volume, remeshed_volume, rtol=1e-6):
        raise ValueError('Объём тетраэдров и их границы не совпадает')
    to_source = sampled_surface_distance(surface_samples(new_vertices, new_faces), vertices, faces)
    to_output = sampled_surface_distance(surface_samples(vertices, faces), new_vertices, new_faces)
    boundary_vertices = new_vertices[np.unique(new_faces)]
    nearest = []
    for start in range(0, len(vertices), 64):
        distances = np.linalg.norm(vertices[start:start + 64, None, :] - boundary_vertices[None, :, :], axis=2)
        nearest.extend(np.min(distances, axis=1).tolist())
    summary = {'volume_ratio_after_remeshing': tet_volume / abs(original_volume),
               'sampled_output_to_input_mm': to_source,
               'sampled_input_to_output_mm': to_output,
               'source_vertex_max_nearest_vertex_mm': max(nearest, default=0.),
               'source_vertices_without_matching_vertex': int(np.count_nonzero(np.asarray(nearest) > 1e-8)),
               'source_vertices': len(vertices), 'source_faces': len(faces),
               'output_boundary_vertices': len(boundary_vertices), 'output_boundary_faces': len(new_faces),
               'input_euler': report.get('input_euler_characteristic'),
               'output_euler': report.get('output_euler_characteristic'),
               'envelope_mm': report.get('eps'), 'quality_max': report.get('max_energy'),
               'note': 'Вершины, середины рёбер и центры граней; это не оценка полной ошибки Хаусдорфа.'}
    return new_vertices, new_faces, tets, summary


def tetrahedral_shell(case, vertices, faces):
    """Призмы двух контрольных объектов, не общий тетраэдрализатор.

    Труба образована соосными стенками, лист — параллельными плоскостями.
    Каждая треугольная призма делится на три тетраэдра; единый порядок узлов
    согласует общие боковые грани соседних призм. Граничная триангуляция
    торцов может отличаться от исходной (на плоских квадратах).
    """
    count = len(vertices)
    if case == 'sleeve':
        wall, _rest = cloth._shell_pairs_by_component(
            vertices, faces, cloth._components(faces, count), np.array([0.]), .6)
        if 2 * len(wall) != count:
            raise ValueError('В экспериментальной трубке не все узлы имеют пару')
        radius = np.linalg.norm(vertices[:, 1:] - [0., 51.], axis=1)
        outer = np.where(radius[wall[:, 0]] > radius[wall[:, 1]], wall[:, 0], wall[:, 1])
        inner = np.where(radius[wall[:, 0]] > radius[wall[:, 1]], wall[:, 1], wall[:, 0])
    elif case == 'table':
        mid = .5 * (vertices[:, 2].min() + vertices[:, 2].max())
        outer = np.nonzero(vertices[:, 2] > mid)[0]
        inner_ids = np.nonzero(vertices[:, 2] < mid)[0]
        key = lambda point: tuple(np.round(point[:2], 6))
        lookup = {key(vertices[index]): index for index in inner_ids}
        if len(lookup) != len(inner_ids) or len(outer) != len(inner_ids):
            raise ValueError('В экспериментальном листе нет однозначных пар')
        inner = np.asarray([lookup[key(vertices[index])] for index in outer], dtype=int)
    else:
        raise ValueError('неизвестный контрольный объект')
    opposite = np.full(count, -1, dtype=int)
    opposite[outer] = inner
    is_outer = np.zeros(count, dtype=bool)
    is_outer[outer] = True
    top = np.sort(faces[np.all(is_outer[faces], axis=1)], axis=1)
    bottom = {tuple(sorted(face)) for face in faces[np.all(~is_outer[faces], axis=1)].tolist()}
    if len(top) != len(bottom) or any(tuple(sorted(opposite[face])) not in bottom for face in top):
        raise ValueError('Триангуляция двух сторон не совпадает')
    tets = np.empty((3 * len(top), 4), dtype=np.int64)
    i, j, k = top.T
    ii, jj, kk = opposite[i], opposite[j], opposite[k]
    tets[0::3] = np.stack((i, j, k, kk), axis=1)
    tets[1::3] = np.stack((i, j, jj, kk), axis=1)
    tets[2::3] = np.stack((i, ii, jj, kk), axis=1)
    surface, tets, tet_volume = tet_boundary(vertices, tets)
    original_volume, _ = cloth._volume_data(vertices, faces)
    boundary_volume, _ = cloth._volume_data(vertices, surface)
    if not np.isclose(tet_volume, abs(original_volume), rtol=1e-6) or not np.isclose(
            tet_volume, boundary_volume, rtol=1e-6):
        raise ValueError('Сумма объёмов или ориентация стенки не совпадают')
    original_faces = {tuple(sorted(face)) for face in faces.tolist()}
    changed_faces = len(original_faces - {tuple(sorted(face)) for face in surface.tolist()})
    return surface, tets, changed_faces


def make_xml(vertices, faces, *, scale, mass, dt, g, radius, young,
             bending, edge_time, ipc, rigid_supports, tets, volume_young,
             volume_poisson, volume_damping, manual_nodes=False):
    # Единица сцены — миллиметр. В эксперименте используем изменённый
    # масштаб, поскольку IPC MuJoCo 4.0 имеет фиксированный зазор 1 мм в
    # своих единицах; это не является готовой калибровкой материалов.
    points = _numbers(np.asarray(vertices) * scale)
    elements = _numbers(faces.astype(int))
    elastic = (f'<elasticity young="{young}" poisson="0.3" thickness="{0.6*scale}" '
               f'elastic2d="{bending}" damping="0.02"/>') if young else ''
    edge = (f'<edge equality="true" solref="{edge_time} 1" '
            'solimp="0.99 0.999 0.0001"/>') if edge_time else ''
    flag = 'enable' if ipc else 'disable'
    # Для опыта со столом каждая выбранная опора задаётся исходными
    # треугольниками как неподвижный flex. Пол — бесконечная плоскость;
    # независимо проверяем конечный пол исходной сцены.
    static = []
    for index, (v, f) in enumerate(rigid_supports):
        static.append(f'''<flexcomp name="support{index}" type="direct" dim="2" rigid="true"
                         radius="{radius}" point="{_numbers(v * scale)}" element="{_numbers(f)}">
                         <contact selfcollide="none"/></flexcomp>''')
    static = '\n'.join(static)
    solid = ''
    if tets is not None:
        bodies = ' '.join(f'sleeve_{index}' for index in range(len(vertices)))
        solid = f'''<flex name="solid" dim="3" radius="0"
                   body="{bodies}" element="{_numbers(tets)}">
                   <contact contype="0" conaffinity="0" selfcollide="none"/>
                   <elasticity young="{volume_young}" poisson="{volume_poisson}"
                               damping="{volume_damping}"/>
                   </flex>'''
    if manual_nodes:
        if tets is None or edge_time or young:
            raise ValueError('Ручные узлы требуют объёмный материал без поверхностных ограничений')
        # Внутренние узлы не встречаются в граничных треугольниках, поэтому
        # flexcomp их не создаёт. Задаём все тела явно и распределяем массу
        # по объёмам прилегающих тетраэдров, не по плотности узлов.
        p = vertices[tets]
        volume = np.abs(np.linalg.det(np.stack((p[:, 1] - p[:, 0], p[:, 2] - p[:, 0],
                                                p[:, 3] - p[:, 0]), axis=2))) / 6.
        weights = np.bincount(tets.ravel(), weights=np.repeat(volume / 4., 4), minlength=len(vertices))
        if np.any(weights <= 0):
            raise ValueError('В объёмной сетке есть неиспользованные узлы')
        masses = mass * weights / weights.sum()
        nodes = []
        for index, (point, node_mass) in enumerate(zip(vertices * scale, masses)):
            inertia = node_mass * .005 ** 2 / 6.
            nodes.append(f'''<body name="sleeve_{index}" pos="{_numbers(point)}">
                           <inertial pos="0 0 0" mass="{node_mass}" diaginertia="{inertia} {inertia} {inertia}"/>
                           <joint type="slide" axis="1 0 0"/>
                           <joint type="slide" axis="0 1 0"/>
                           <joint type="slide" axis="0 0 1"/>
                           </body>''')
        dynamic = '\n'.join(nodes)
        boundary_ids = np.unique(faces)
        local = np.full(len(vertices), -1, dtype=int)
        local[boundary_ids] = np.arange(len(boundary_ids))
        boundary_bodies = ' '.join(f'sleeve_{index}' for index in boundary_ids)
        collision = f'''<flex name="sleeve" dim="2" radius="{radius}"
                        body="{boundary_bodies}" element="{_numbers(local[faces])}">
                        <contact selfcollide="auto" condim="3"/></flex>'''
        deformable = f'<deformable>{solid}{collision}</deformable>'
    else:
        dynamic = f'''<flexcomp name="sleeve" type="direct" dim="2" radius="{radius}"
                       mass="{mass}" point="{points}" element="{elements}">
                         <contact selfcollide="auto" condim="3"/>
                         {edge}{elastic}</flexcomp>'''
        deformable = f'<deformable>{solid}</deformable>' if solid else ''
    return f'''<mujoco model="drape probe">
      <option timestep="{dt}" integrator="discrete" solver="Newton"
              tolerance="1e-6" iterations="150" gravity="0 0 {-g}">
        <flag ipc="{flag}"/>
      </option>
      <size memory="400M"/>
      <worldbody>
        <geom type="plane" size="2 2 0.1" friction="0.9 0.005 0.0001"/>
        {dynamic}{static}
      </worldbody>
      {deformable}
    </mujoco>'''


def restart_from_rest(mujoco, model, data, body_ids, scale, steps):
    """Повторный свободный запуск из результата с нулевой скоростью и без drag.

    Это диагностический тест подвижности, не прямой баланс сил: IPC MuJoCo
    учитывается при дискретном шаге, а не просто в qfrc_constraint mj_forward.
    """
    scratch = mujoco.MjData(model)
    scratch.qpos[:] = data.qpos
    mujoco.mj_forward(model, scratch)
    start = scratch.xpos[body_ids].copy()
    initial = 0.
    peak = 0.
    for step in range(int(steps)):
        old_time = scratch.time
        mujoco.mj_step(model, scratch)
        if (np.any(scratch.warning.number) or scratch.time <= old_time
                or not np.all(np.isfinite(scratch.qvel))):
            raise RuntimeError(f'Численная ошибка при перезапуске из покоя, шаг {step + 1}')
        speed = float(np.max(np.linalg.norm(scratch.qvel.reshape(-1, 3), axis=1))) / scale
        peak = max(peak, speed)
        if step == 0:
            initial = speed / model.opt.timestep
    mujoco.mj_kinematics(model, scratch)
    displacement = np.linalg.norm(scratch.xpos[body_ids] - start, axis=1) / scale
    return {'steps': steps, 'first_step_effective_acceleration_mm_s2': initial,
            'max_speed_mm_s': peak, 'last_speed_mm_s': speed if steps else 0.,
            'max_displacement_mm': float(np.max(displacement)),
            'note': 'Исследовательский повтор из покоя без drag; не проверка точного баланса сил.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['sleeve', 'table'], default='sleeve')
    parser.add_argument('--sides', type=int, default=16)
    parser.add_argument('--steps', type=int, default=200)
    parser.add_argument('--interval', type=int, default=20)
    parser.add_argument('--scale', type=float, default=.01, help='единиц MuJoCo на мм сцены')
    parser.add_argument('--dt', type=float, default=.002)
    parser.add_argument('--g', type=float, default=9.81)
    parser.add_argument('--mass', type=float, default=.1)
    parser.add_argument('--drag', type=float, default=3., help='вязкое затухание 1/с')
    parser.add_argument('--radius', type=float, default=.0001)
    parser.add_argument('--young', type=float, default=0.)
    parser.add_argument('--bending', choices=['none', 'bend', 'stretch', 'both'], default='none')
    parser.add_argument('--edge-time', type=float, default=.005)
    parser.add_argument('--wall', choices=['none', 'equality', 'spring'], default='none',
                        help='экспериментальные связи между сторонами стенки')
    parser.add_argument('--shear', action='store_true',
                        help='добавить поперечные диагонали между сторонами стенки')
    parser.add_argument('--wall-stiffness', type=float, default=10000.)
    parser.add_argument('--volume-young', type=float, default=0.,
                        help='ненулевое значение включает экспериментальные тетраэдры')
    parser.add_argument('--volume-poisson', type=float, default=.3)
    parser.add_argument('--volume-damping', type=float, default=.02)
    parser.add_argument('--wild', action='store_true',
                        help='тестировать общий тетраэдрализатор wildmeshing вместо специальных призм')
    parser.add_argument('--wild-eps-rel', type=float, default=.0001)
    parser.add_argument('--wild-edge-rel', type=float, default=.05)
    parser.add_argument('--wild-iterations', type=int, default=4)
    parser.add_argument('--ccd', action='store_true',
                        help='проверять каждый линейный отрезок движения через ipctk')
    parser.add_argument('--ccd-min-distance', type=float, default=0., help='зазор CCD, мм')
    parser.add_argument('--restart-probe', type=int, default=0,
                        help='дополнительные шаги из результата с нулевой скоростью и без drag')
    parser.add_argument('--no-ipc', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        import mujoco
    except ImportError as exc:
        raise SystemExit('MuJoCo не установлен в экспериментальном окружении') from exc
    # Не создаём MUJOCO_LOG.TXT в проекте; предупреждения остаются видимыми.
    mujoco.set_mju_user_warning(lambda message: print(f'Предупреждение MuJoCo: {message}',
                                                      file=sys.stderr, flush=True))
    if args.wild and (args.volume_young <= 0 or args.wall != 'none' or args.shear
                      or args.edge_time or args.young):
        raise SystemExit('--wild требует --volume-young > 0 --edge-time 0 '
                         'и не поддерживает --wall/--shear или поверхностную упругость')
    if args.restart_probe < 0:
        raise SystemExit('--restart-probe должен быть неотрицательным')
    original, faces, placed, supports = input_mesh(args.case, args.sides, refine=not args.wild)
    source_faces = faces.copy() if not args.wild else None
    tets, retriangulated, meshing = None, 0, None
    if args.wild:
        # Общая сетка меняет и индексы, и число граней: значение «0» здесь
        # ошибочно означало бы сохранённую триангуляцию.
        retriangulated = None
        meshing_started = time.perf_counter()
        original, faces, tets, meshing = wild_tetrahedra(
            original, faces, args.wild_eps_rel, args.wild_edge_rel, args.wild_iterations)
        meshing['seconds'] = round(time.perf_counter() - meshing_started, 3)
        support_tri = np.concatenate([v[f] for v, f in supports.values()])
        placed = cloth.place(original, support_tri, np.array([0., 0., -1.]), .25)
    elif args.volume_young:
        faces, tets, retriangulated = tetrahedral_shell(args.case, original, faces)
    edges = cloth._edge_arrays(faces)
    initial_lengths = np.linalg.norm(original[edges[:, 1]] - original[edges[:, 0]], axis=1)
    if args.wild:
        wall, wall_rest = np.zeros((0, 2), dtype=int), np.zeros(0)
    else:
        components = cloth._components(faces, len(original))
        wall, wall_rest = cloth._shell_pairs_by_component(original, faces, components, np.array([0.]), .6)
    xml = make_xml(placed, faces, scale=args.scale, mass=args.mass, dt=args.dt, g=args.g,
                   radius=args.radius, young=args.young, bending=args.bending,
                   edge_time=args.edge_time, ipc=not args.no_ipc,
                   rigid_supports=[support for name, support in supports.items() if name != 'пол'],
                   tets=tets, volume_young=args.volume_young, manual_nodes=args.wild,
                   volume_poisson=args.volume_poisson, volume_damping=args.volume_damping)
    if args.edge_time and args.young:
        raise SystemExit('MuJoCo 4.0 не сочетает ограничения рёбер flex с его elasticity')
    if args.shear and args.wall == 'none':
        raise SystemExit('--shear требует --wall equality или --wall spring')
    t0 = time.perf_counter()
    if args.wall == 'none':
        model = mujoco.MjModel.from_xml_string(xml)
        wall_link_count = 0
    else:
        # Стяжки здесь возможны лишь благодаря однозначно найденным парам
        # стенки данной тестовой трубки. Для произвольной детали это не доказано.
        links = {tuple(sorted((int(a), int(b)))) for a, b in wall}
        if args.shear:
            opposite = np.full(len(original), -1, dtype=int)
            opposite[wall[:, 0]], opposite[wall[:, 1]] = wall[:, 1], wall[:, 0]
            existing = {tuple(e) for e in edges.tolist()}
            for a, b in edges:
                if opposite[a] < 0 or opposite[b] < 0:
                    continue
                for c, d in ((a, opposite[b]), (b, opposite[a])):
                    link = tuple(sorted((int(c), int(d))))
                    if c != d and link not in existing:
                        links.add(link)
        spec = mujoco.MjSpec.from_string(xml)
        for node in sorted({index for pair in links for index in pair}):
            spec.body(f'sleeve_{node}').add_site(name=f'node{node}', pos=[0., 0., 0.])
        for index, (a, b) in enumerate(sorted(links)):
            name = f'link{index}'
            tendon = spec.add_tendon(name=name, stiffness=[args.wall_stiffness, 0., 0.] if args.wall == 'spring'
                                     else [0., 0., 0.], width=.0001)
            tendon.wrap_site(f'node{a}')
            tendon.wrap_site(f'node{b}')
            if args.wall == 'equality':
                spec.add_equality(type=mujoco.mjtEq.mjEQ_TENDON, name1=name,
                                  objtype=mujoco.mjtObj.mjOBJ_TENDON,
                                  solref=[max(2 * args.dt, args.edge_time), 1.],
                                  solimp=[.99, .999, .0001, .5, 2.])
        model = spec.compile()
        wall_link_count = len(links)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    if np.any(data.warning.number):
        raise RuntimeError(f'Предупреждения MuJoCo на старте: {data.warning.number.tolist()}')
    body_ids = np.asarray([mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, f'sleeve_{index}')
                           for index in range(len(original))], dtype=int)
    if np.any(body_ids < 0):
        raise RuntimeError('MuJoCo не создал часть узлов экспериментальной сетки')
    ordering_error = float(np.max(np.abs(data.xpos[body_ids] / args.scale - placed)))
    if ordering_error > 1e-5:
        raise RuntimeError(f'Порядок вершин изменился: {ordering_error} мм')
    print(json.dumps({'mujoco': mujoco.__version__, 'arguments': vars(args) | {'output': str(args.output)},
                      'vertices': len(original), 'faces': len(faces),
                      'wall_pairs': len(wall), 'wall_links': wall_link_count,
                      'tetrahedra': len(tets) if tets is not None else 0,
                      'retriangulated_boundary_faces': retriangulated, 'meshing': meshing,
                      'compile_seconds': round(time.perf_counter() - t0, 3),
                      'ordering_error_mm': ordering_error}, ensure_ascii=False), flush=True)
    if model.nv != len(original) * 3:
        raise RuntimeError('В опыте ожидались три степени свободы на вершину детали')
    ccd = TrajectoryAudit(placed, faces, supports, args.ccd_min_distance) if args.ccd else None
    velocity = acceleration = 0.0
    recent_velocity, recent_acceleration = deque(maxlen=50), deque(maxlen=50)
    for step in range(args.steps):
        # Искусственное вязкое затухание только для поиска неподвижной позы.
        data.qfrc_applied[:] = -args.drag * model.dof_M0 * data.qvel
        old_time = data.time
        mujoco.mj_step(model, data)
        if np.any(data.warning.number) or data.time <= old_time or not np.all(np.isfinite(data.qvel)):
            raise RuntimeError(f'Численная ошибка MuJoCo на шаге {step + 1}: '
                               f'{data.warning.number.tolist()}, время {data.time}')
        if ccd is not None:
            # mj_step обновляет qpos, но ещё не пересчитывает позиции тел.
            mujoco.mj_kinematics(model, data)
            current = np.asarray(data.xpos[body_ids]).copy() / args.scale
            if not ccd.check(current):
                raise RuntimeError(f'CCD: пересечение или нарушение заданного зазора '
                                   f'на линейном отрезке шага {step + 1}')
        velocity = float(np.max(np.linalg.norm(data.qvel.reshape(-1, 3), axis=1))) / args.scale
        acceleration = float(np.max(np.linalg.norm(data.qacc.reshape(-1, 3), axis=1))) / args.scale
        recent_velocity.append(velocity)
        recent_acceleration.append(acceleration)
        if (step + 1) % args.interval == 0 or step == args.steps - 1:
            print(json.dumps({'step': step + 1, 'elapsed': round(time.perf_counter() - t0, 3),
                              'max_speed_mm_s': velocity, 'warning_counts': data.warning.number.tolist()},
                             ensure_ascii=False), flush=True)
    mujoco.mj_forward(model, data)
    position = np.asarray(data.xpos[body_ids]).copy() / args.scale
    lengths = np.linalg.norm(position[edges[:, 1]] - position[edges[:, 0]], axis=1)
    strain = np.abs(lengths / initial_lengths - 1.)
    audit = self_intersections(position, faces)
    wall_lengths = np.linalg.norm(position[wall[:, 1]] - position[wall[:, 0]], axis=1)
    wall_strain = np.abs(wall_lengths / np.maximum(wall_rest, 1e-12) - 1.)
    initial_volume, _ = cloth._volume_data(original, faces)
    final_volume, _ = cloth._volume_data(position, faces)
    result = {'mujoco': mujoco.__version__, 'arguments': vars(args) | {'output': str(args.output)},
              'vertices': len(original), 'faces': len(faces), 'wall_pairs': len(wall),
              'wall_links': wall_link_count, 'tetrahedra': len(tets) if tets is not None else 0,
              'retriangulated_boundary_faces': retriangulated, 'meshing': meshing,
              'elapsed_seconds': round(time.perf_counter() - t0, 3),
              'volume_ratio': float(final_volume / initial_volume),
              'max_wall_pair_strain': float(np.max(wall_strain)) if len(wall_strain) else None,
              'p90_wall_pair_strain': float(np.percentile(wall_strain, 90)) if len(wall_strain) else None,
              'bbox_mm': np.concatenate((position.min(axis=0), position.max(axis=0))).tolist(),
              'max_edge_strain': float(np.max(strain)),
              'p90_edge_strain': float(np.percentile(strain, 90)),
              'last_max_speed_mm_s': velocity,
              'last_max_acceleration_mm_s2': acceleration,
              'recent_max_speed_mm_s': max(recent_velocity, default=0.),
              'recent_max_acceleration_mm_s2': max(recent_acceleration, default=0.),
              'recent_steps': len(recent_velocity), 'warnings': data.warning.number.tolist(),
              'trajectory_ccd': ({'steps': ccd.steps, 'min_distance_mm': ccd.min_distance,
                                  'seconds': round(ccd.seconds, 3),
                                  'note': 'Только линейные отрезки после размещения; '
                                          'касание соседних граней исключено.'}
                                 if ccd is not None else None),
              'surface': audit, 'fcl': _fcl_audit(position, faces, combined_support(supports)),
              'fcl_each_support_contact_or_crossing': support_fcl(position, faces, supports),
              'note': 'Исследовательский пример, а не проверенное равновесие или реализация drape.'}
    if tets is not None:
        def determinants(points):
            p = points[tets]
            return np.linalg.det(np.stack((p[:, 1] - p[:, 0], p[:, 2] - p[:, 0],
                                           p[:, 3] - p[:, 0]), axis=2))
        jacobian = determinants(position) / determinants(original)
        tet_edges = np.unique(np.sort(np.concatenate([tets[:, [i, j]]
                                                      for i in range(4) for j in range(i + 1, 4)]), axis=1), axis=0)
        before = np.linalg.norm(original[tet_edges[:, 1]] - original[tet_edges[:, 0]], axis=1)
        after = np.linalg.norm(position[tet_edges[:, 1]] - position[tet_edges[:, 0]], axis=1)
        tet_strain = np.abs(after / np.maximum(before, 1e-12) - 1.)
        result['tetra_min_jacobian'] = float(jacobian.min())
        result['tetra_max_jacobian'] = float(jacobian.max())
        result['tetra_inverted'] = int(np.count_nonzero(jacobian <= 0))
        result['tetra_edge_max_strain'] = float(tet_strain.max())
        result['tetra_edge_p90_strain'] = float(np.percentile(tet_strain, 90))
    if source_faces is not None and retriangulated:
        result['source_connectivity'] = changed_surface_distances(position, source_faces, faces)
        result['source_connectivity']['surface'] = self_intersections(position, source_faces)
        result['source_connectivity']['fcl'] = _fcl_audit(position, source_faces, combined_support(supports))
    if args.restart_probe:
        result['restart_from_rest'] = restart_from_rest(
            mujoco, model, data, body_ids, args.scale, args.restart_probe)
    if args.case == 'table':
        center = (np.abs(original[:, 0] - 150.) < 25.) & (np.abs(original[:, 1]) < 25.)
        edge = (np.abs(original[:, 0] - 150.) > 50.) | (np.abs(original[:, 1]) > 50.)
        result['median_hanging_mm'] = float(np.median(position[center, 2]) - np.median(position[edge, 2]))
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    if args.output:
        sv, sf = combined_support(supports)
        np.savez_compressed(args.output, original=original, placed=placed, faces=faces,
                            source_faces=source_faces if source_faces is not None else np.empty((0, 3), dtype=int),
                            tets=tets if tets is not None else np.empty((0, 4), dtype=int),
                            qpos=data.qpos, qvel=data.qvel, final=position,
                            support_vertices=sv, support_faces=sf)


if __name__ == '__main__':
    main()
