"""Внутренний тест упаковки IPC; это НЕ Форма и не исполняемый файл выпуска.

Запускается в чистом каталоге как PyInstaller one-file на Windows CI.
Проверяет, что NumPy/SciPy/IPC загружены из временного каталога сборки, и
выполняет две проверки CCD. Не проверяет интерфейс Формы и шесть сцен.
"""
from pathlib import Path
import sys

import numpy as np
import scipy
import ipctk


def main():
    if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        raise RuntimeError("Тест предназначен для однофайлового PyInstaller-пробника")
    unpacked = Path(sys._MEIPASS).resolve()
    for module in (np, scipy, ipctk):
        source = Path(module.__file__).resolve()
        if not source.is_relative_to(unpacked):
            raise RuntimeError(f"{module.__name__} загружен вне пакета: {source}")
        print(f"{module.__name__}: импорт из однофайлового пакета подтверждён")

    # Три вершины детали и один неподвижный треугольник опоры.
    points = np.asarray([[.1, .1, 1.], [.8, .1, 1.], [.1, .8, 1.],
                         [0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
    faces = np.asarray([[0, 1, 2], [3, 4, 5]], dtype=np.int32)
    edges = np.asarray([[0, 1], [1, 2], [0, 2], [3, 4], [4, 5], [3, 5]], dtype=np.int32)
    ipctk.set_num_threads(1)
    mesh = ipctk.CollisionMesh(points, edges, faces)
    mesh.can_collide = ipctk.make_static_obstacle_filter(3)
    mesh.init_adjacencies()
    safe = points.copy()
    safe[:3, 2] += .25
    crossing = points.copy()
    crossing[:3, 2] -= 2.
    if ipctk.has_intersections(mesh, points):
        raise AssertionError("Исходные треугольники не должны пересекаться")
    if not ipctk.is_step_collision_free(mesh, points, safe):
        raise AssertionError("Безопасный шаг должен проходить проверку")
    if ipctk.is_step_collision_free(mesh, points, crossing):
        raise AssertionError("Проход через опору должен быть обнаружен")
    alpha = float(ipctk.compute_collision_free_stepsize(mesh, points, crossing))
    if not 0.0 < alpha < 1.0:
        raise AssertionError(f"Неверная безопасная доля шага: {alpha}")
    print(f"IPC {ipctk.__version__}: CCD безопасного и опасного шагов прошла; alpha={alpha:.6f}")
    print("Это только технический пробник IPC, не Форма и не проверка шести сцен.")


if __name__ == "__main__":
    main()
