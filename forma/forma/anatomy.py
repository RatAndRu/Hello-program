"""Анатомический человек: скелетные ориентиры + объёмы мышц (SDF).

Строится из анатомических пропорций (канон 7.5–8 голов), а не из «шариков»:
плечевой и тазовый пояс, грудная клетка, широчайшие, трапеции, дельтовидные,
двуглавые/трёхглавые, предплечья, кисти с пальцами, ягодичные, четырёхглавые,
икроножные, стопы с пальцами, череп с челюстью, носом, губами, ушами и глазами.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import manifold3d as mf
import numpy as np

from .errors import DslError, GeometryError
from .sdf import (Capsule, Cone, Ellipsoid, Field, Prim, RoundBox, Sphere, Torus,
                  capsule, cone, ellipsoid, lerp, rotation_matrix, round_box, sphere)

DETAILS = {
    "низкий": {"body": 5.0, "head": 3.0, "hand": 2.8, "foot": 3.2, "smooth": 1,
               "simplify": 0.5, "polish": 46.0},
    "средний": {"body": 4.0, "head": 2.2, "hand": 2.0, "foot": 2.6, "smooth": 1,
                "simplify": 0.35, "polish": 42.0},
    "высокий": {"body": 3.2, "head": 1.7, "hand": 1.5, "foot": 2.0, "smooth": 1,
                "simplify": 0.2, "polish": 38.0},
}
DETAIL_ALIASES = {"low": "низкий", "medium": "средний", "high": "высокий",
                  "низкая": "низкий", "средняя": "средний", "высокая": "высокий",
                  "малый": "низкий", "большой": "высокий"}

SEX_ALIASES = {"м": "м", "м": "м", "male": "м", "man": "м", "мужской": "м",
               "мужчина": "м", "m": "м", "ж": "ж", "female": "ж", "woman": "ж",
               "женский": "ж", "женщина": "ж", "f": "ж"}

BUILDS = {"худой": 0.82, "slim": 0.82, "тонкий": 0.85, "обычный": 1.0, "normal": 1.0,
          "спортивный": 1.12, "athletic": 1.12, "fitness": 1.12, "muscular": 1.12,
          "плотный": 1.28, "heavy": 1.28, "полный": 1.45, "fat": 1.45}


@dataclass
class HumanParams:
    height: float = 1750.0
    sex: str = "м"
    build: float = 1.0
    pose: str = "a"
    detail: str = "средний"
    hair: bool = True
    eyes: bool = True
    age: float = 0.0        # 0 — взрослый, до 1 — старческий рельеф (запас)
    muscles: bool = True    # выраженность рельефа


class Anatomy:
    def __init__(self, p: HumanParams):
        self.p = p
        self.H = float(p.height)
        self.female = p.sex == "ж"
        self.b = float(p.build)
        self._landmarks()

    # ------------------------------------------------------------------ #
    def _landmarks(self):
        H, F, b = self.H, self.female, self.b
        self.head_h = H / (7.55 if not F else 7.4)
        self.top = H
        self.chin = H - self.head_h
        # центр черепа: макушка ровно на H, низ головы — на подбородке
        self.head_c = np.array([0.0, 0.0, H - self.head_h * 0.50])
        self.shoulder_z = H * 0.815
        self.chest_z = H * 0.745
        self.waist_z = H * 0.625
        self.hip_z = H * 0.53
        self.crotch_z = H * 0.475
        self.knee_z = H * 0.285
        self.ankle_z = H * 0.042

        self.shoulder_x = H * (0.095 if not F else 0.088)
        self.hip_x = H * (0.055 if not F else 0.060)
        self.knee_x = H * (0.058 if not F else 0.060)
        self.ankle_x = H * (0.058 if not F else 0.060)

        self.chest_w = H * (0.092 if not F else 0.086) * (0.92 + 0.12 * b)
        self.chest_d = H * (0.060 if not F else 0.058) * (0.92 + 0.14 * b)
        self.waist_w = H * (0.077 if not F else 0.070) * (0.92 + 0.20 * (b - 1) + 0.08 * b)
        self.waist_d = H * (0.058 if not F else 0.056) * (0.92 + 0.22 * (b - 1) + 0.06 * b)
        self.hip_w = H * (0.093 if not F else 0.102) * (0.92 + 0.14 * b)
        self.hip_d = H * (0.068 if not F else 0.074) * (0.92 + 0.16 * b)
        self.head_w = H * (0.0445 if not F else 0.0430)
        self.head_d = H * (0.058 if not F else 0.055)
        self.head_hh = self.head_h * 0.500

        self.upper_arm = H * 0.192
        self.forearm = H * 0.152
        self.hand_len = H * 0.112
        self.thigh = H * 0.245
        self.shin = H * 0.246

        self.upper_arm_r = H * (0.027 if not F else 0.024) * (0.85 + 0.2 * b)
        self.forearm_r = H * (0.020 if not F else 0.018) * (0.9 + 0.15 * b)
        self.thigh_r = H * (0.052 if not F else 0.055) * (0.86 + 0.2 * b)
        self.calf_r = H * (0.034 if not F else 0.032) * (0.9 + 0.14 * b)

        # углы рук
        if self.p.pose == "t":
            arm_angle, elbow_bend = 88.0, 0.0
        elif self.p.pose == "relaxed":
            arm_angle, elbow_bend = 8.0, 12.0
        else:
            arm_angle, elbow_bend = 20.0, 4.0
        self.arm_angle = math.radians(arm_angle)
        self.elbow_bend = math.radians(elbow_bend)

        side = 1.0
        self.shoulder = np.array([self.shoulder_x, -H * 0.004, self.shoulder_z])
        d1 = np.array([math.sin(self.arm_angle), 0.0, -math.cos(self.arm_angle)])
        self.elbow = self.shoulder + d1 * self.upper_arm
        d2 = np.array([math.sin(self.arm_angle + self.elbow_bend), 0.02,
                       -math.cos(self.arm_angle + self.elbow_bend)])
        d2 /= np.linalg.norm(d2)
        self.wrist = self.elbow + d2 * self.forearm
        self.hand_dir = d2
        self.hip = np.array([self.hip_x, 0.0, self.hip_z])
        self.knee = np.array([self.knee_x, H * 0.004, self.knee_z])
        self.ankle = np.array([self.ankle_x, -H * 0.004, self.ankle_z])
        self._side = side

    def mirror(self, v):
        v = np.asarray(v, dtype=np.float64).copy()
        v[0] = -v[0]
        return v

    # ------------------------------------------------------------------ #
    def _torso_prims(self) -> list[Prim]:
        H, F, b = self.H, self.female, self.b
        S = self
        prims: list[Prim] = []
        add = prims.append

        # таз, ягодицы, живот
        add(ellipsoid((0, -H * 0.004, S.hip_z), (S.hip_w * 1.02, S.hip_d * 1.02, H * 0.075)))
        for sx in (1, -1):
            add(ellipsoid((sx * S.hip_x * 1.18, -S.hip_d * 0.50, S.hip_z - H * 0.006),
                          (S.hip_w * 0.34, S.hip_d * 0.38, H * 0.050)))
        add(ellipsoid((0, H * 0.006, H * 0.585), (S.waist_w * 1.02, S.waist_d * 1.02, H * 0.055)))
        add(ellipsoid((0, H * 0.008, H * 0.655), (S.waist_w * 1.05, S.waist_d * 1.05, H * 0.06)))

        # грудная клетка
        add(ellipsoid((0, H * 0.004, S.chest_z), (S.chest_w * 1.04, S.chest_d * 1.00, H * 0.092)))
        add(ellipsoid((0, H * 0.012, S.chest_z + H * 0.048),
                      (S.chest_w * 0.94, S.chest_d * 0.90, H * 0.048)))
        # грудь (женская)
        if F:
            for sx in (1, -1):
                add(ellipsoid((sx * S.chest_w * 0.42, S.chest_d * 1.02, S.chest_z + H * 0.005),
                              (S.chest_w * 0.34, S.chest_d * 0.30, H * 0.036)))
        # мужская грудь — единый объём без «шаров»; рельеф даёт рельеф мышц
        # широчайшие (спина) и трапеции
        for sx in (1, -1):
            add(ellipsoid((sx * S.chest_w * 0.72, -S.chest_d * 0.28, S.chest_z - H * 0.012),
                          (S.chest_w * 0.17, S.chest_d * 0.42, H * 0.072)))
        add(capsule((0, -H * 0.030, S.chin - H * 0.012),
                    (S.shoulder_x * 0.92, -H * 0.018, S.shoulder_z + H * 0.006),
                    H * 0.026 if not F else H * 0.020))
        add(capsule(self.mirror((0, -H * 0.030, S.chin - H * 0.012)),
                    self.mirror((S.shoulder_x * 0.92, -H * 0.018, S.shoulder_z + H * 0.006)),
                    H * 0.026 if not F else H * 0.020))

        # мышцы живота / косые
        if self.p.muscles:
            for row, (zz, sc) in enumerate(((0.575, 1.0), (0.615, 0.95), (0.655, 0.82))):
                for sx in (1, -1):
                    add(ellipsoid((sx * S.waist_w * 0.26, S.waist_d * 0.86,
                                   H * zz),
                                  (S.waist_w * 0.20 * sc, S.waist_d * 0.15, H * 0.013 * sc)))
            for sx in (1, -1):
                add(ellipsoid((sx * S.waist_w * 0.88, S.waist_d * 0.25, H * 0.605),
                              (S.waist_w * 0.18, S.waist_d * 0.45, H * 0.045)))
        # грудина и ключицы
        add(capsule((0, S.chest_d * 0.92, S.chest_z + H * 0.052),
                    (0, S.chest_d * 0.80, S.chest_z - H * 0.030), H * 0.014))
        for sx in (1, -1):
            add(capsule((sx * H * 0.006, S.chest_d * 0.80, S.chest_z + H * 0.058),
                        (sx * S.shoulder_x * 0.92, S.chest_d * 0.30, S.shoulder_z + H * 0.010),
                        H * 0.011))
        return prims

    def _neck_prims(self) -> list[Prim]:
        H, F = self.H, self.female
        prims = [
            cone((0, -H * 0.008, self.chin - H * 0.010),
                 (0, -H * 0.004, self.chin - H * 0.105),
                 H * 0.036 if not F else H * 0.031,
                 H * 0.045 if not F else H * 0.038),
        ]
        if self.p.muscles:
            for sx in (1, -1):
                prims.append(capsule((sx * H * 0.020, H * 0.028, self.chin - H * 0.020),
                                     (sx * H * 0.034, H * 0.010, self.chin - H * 0.095),
                                     H * 0.011))
        return prims

    # ------------------------------------------------------------------ #
    def _arm_prims(self, side_sign: int) -> list[Prim]:
        H, F, b = self.H, self.female, self.b
        prims: list[Prim] = []
        sh = self.shoulder.copy()
        el = self.elbow.copy()
        wr = self.wrist.copy()
        if side_sign < 0:
            sh, el, wr = self.mirror(sh), self.mirror(el), self.mirror(wr)
        d1 = (el - sh) / np.linalg.norm(el - sh)
        d2 = (wr - el) / np.linalg.norm(wr - el)
        r1 = self.upper_arm_r
        r2 = self.forearm_r

        # дельтовидная
        prims.append(ellipsoid(sh + np.array([side_sign * H * 0.003, 0, H * 0.010]),
                               (r1 * 1.06, r1 * 0.98, r1 * 1.10)))
        prims.append(ellipsoid(sh + d1 * (self.upper_arm * 0.16) + np.array([0, 0, H * 0.004]),
                               (r1 * 1.02, r1 * 0.95, r1 * 1.05)))
        # плечо (двуглавая спереди, трёхглавая сзади)
        prims.append(capsule(sh + d1 * r1 * 0.4, el - d1 * r2 * 0.4, r1 * 0.82))
        mid = sh + d1 * (self.upper_arm * 0.5)
        if self.p.muscles:
            prims.append(ellipsoid(mid + np.array([0, r1 * 0.30, 0]),
                                   (r1 * 0.48, r1 * 0.44, self.upper_arm * 0.20)))
            prims.append(ellipsoid(mid + np.array([0, -r1 * 0.26, 0]),
                                   (r1 * 0.50, r1 * 0.42, self.upper_arm * 0.22)))
        # локоть
        prims.append(sphere(el, r2 * 1.02))
        # предплечье: расширение у локтя, сужение к кисти
        prims.append(cone(el - d2 * r2 * 0.2, wr, r2 * 1.12, r2 * 0.66))
        if self.p.muscles:
            prims.append(ellipsoid(el + d2 * self.forearm * 0.3 + np.array([0, r2 * 0.45, 0]),
                                   (r2 * 0.62, r2 * 0.55, self.forearm * 0.26)))
        return prims

    def _hand_prims(self, side_sign: int, origin: np.ndarray, direction: np.ndarray,
                    fine: bool = True) -> list[Prim]:
        H, F = self.H, self.female
        prims: list[Prim] = []
        d = direction / np.linalg.norm(direction)
        side = np.array([1.0, 0.0, 0.0])
        side = side - d * float(np.dot(side, d))
        side /= np.linalg.norm(side)
        up = np.cross(d, side)
        if side_sign < 0:
            side = -side
        palm_len = self.hand_len * 0.54
        palm_w = self.hand_len * 0.36
        palm_t = self.hand_len * 0.20
        palm_c = origin + d * (palm_len * 0.55)
        rot = np.column_stack([side, up, d])
        prims.append(round_box(palm_c, (palm_w, palm_t, palm_len), palm_t * 0.45, rot=rot))
        # большой палец
        thumb_base = origin + d * (palm_len * 0.28) + side * (palm_w * 0.55)
        thumb_dir = (d * 0.55 + side * 0.75 + up * 0.15)
        thumb_dir /= np.linalg.norm(thumb_dir)
        t1 = thumb_base + thumb_dir * (self.hand_len * 0.17)
        t2 = t1 + (d * 0.6 + side * 0.35) * (self.hand_len * 0.14)
        prims.append(capsule(thumb_base, t1, self.hand_len * 0.048))
        prims.append(capsule(t1, t2, self.hand_len * 0.040))
        # четыре пальца
        finger_len = [0.155, 0.175, 0.165, 0.140]
        finger_r = [0.044, 0.045, 0.042, 0.036]
        offsets = [-0.36, -0.12, 0.12, 0.36]
        for i in range(4):
            base = origin + d * (palm_len * 0.95) + side * (palm_w * offsets[i])
            seg1 = d * 0.98 - up * 0.10 + side * offsets[i] * 0.15
            seg1 /= np.linalg.norm(seg1)
            p1 = base + seg1 * (self.hand_len * finger_len[i] * 0.5)
            p2 = p1 + (d * 0.94 - up * 0.28) * (self.hand_len * finger_len[i] * 0.32)
            p3 = p2 + (d * 0.86 - up * 0.45) * (self.hand_len * finger_len[i] * 0.26)
            r = self.hand_len * finger_r[i]
            prims.append(capsule(base, p1, r))
            prims.append(capsule(p1, p2, r * 0.92))
            prims.append(capsule(p2, p3, r * 0.80))
        return prims

    def _leg_prims(self, side_sign: int) -> list[Prim]:
        H, F, b = self.H, self.female, self.b
        prims: list[Prim] = []
        hip = self.hip.copy()
        knee = self.knee.copy()
        ankle = self.ankle.copy()
        if side_sign < 0:
            hip, knee, ankle = self.mirror(hip), self.mirror(knee), self.mirror(ankle)
        rt = self.thigh_r
        rc = self.calf_r
        # бедро
        prims.append(cone(hip + np.array([0, 0, H * 0.02]), knee, rt * 1.06, rc * 0.92))
        if self.p.muscles:
            dm = (knee - hip) / np.linalg.norm(knee - hip)
            mid = hip + dm * (self.thigh * 0.42)
            prims.append(ellipsoid(mid + np.array([0, rt * 0.34, H * 0.01]),
                                   (rt * 0.50, rt * 0.40, self.thigh * 0.24)))
            prims.append(ellipsoid(mid + np.array([0, -rt * 0.30, -H * 0.01]),
                                   (rt * 0.46, rt * 0.38, self.thigh * 0.21)))
            # приведение бедра (внутренняя поверхность)
            prims.append(ellipsoid(mid - np.array([side_sign * rt * 0.40, 0, 0]),
                                   (rt * 0.36, rt * 0.42, self.thigh * 0.22)))
        # колено
        prims.append(sphere(knee, rc * 0.86))
        prims.append(ellipsoid(knee + np.array([0, rc * 0.38, rc * 0.1]),
                               (rc * 0.40, rc * 0.26, rc * 0.34)))
        # голень
        prims.append(cone(knee, ankle, rc * 1.02, rc * 0.55))
        if self.p.muscles:
            dm = (ankle - knee) / np.linalg.norm(ankle - knee)
            prims.append(ellipsoid(knee + dm * (self.shin * 0.26) + np.array([0, -rc * 0.40, 0]),
                                   (rc * 0.52, rc * 0.44, self.shin * 0.20)))
            prims.append(ellipsoid(knee + dm * (self.shin * 0.40) + np.array([side_sign * rc * 0.24, 0, 0]),
                                   (rc * 0.34, rc * 0.38, self.shin * 0.19)))
        # лодыжка
        prims.append(sphere(ankle, rc * 0.40))
        return prims

    def _foot_prims(self, side_sign: int) -> list[Prim]:
        H = self.H
        ankle = self.ankle.copy() if side_sign > 0 else self.mirror(self.ankle)
        x = ankle[0]
        prims: list[Prim] = []
        # колодка: пятка (z 8…48) → свод → носок (z 6…30)
        prims.append(round_box((x, -H * 0.010, H * 0.030),
                               (H * 0.040, H * 0.082, H * 0.024), H * 0.014))
        prims.append(round_box((x, H * 0.062, H * 0.024),
                               (H * 0.042, H * 0.058, H * 0.019), H * 0.012))
        prims.append(round_box((x, H * 0.108, H * 0.017),
                               (H * 0.042, H * 0.040, H * 0.014), H * 0.010))
        # подъём (переход к голени)
        prims.append(ellipsoid((x, ankle[1] + H * 0.006, H * 0.042),
                               (H * 0.028, H * 0.046, H * 0.030)))
        prims.append(capsule((x, ankle[1], H * 0.040), (x, ankle[1], H * 0.075), H * 0.025))
        # пальцы ног (лежат на полу, не торчат вверх)
        for i in range(5):
            bx = x + (0.46 - i) * H * 0.0108
            by = H * 0.116 - abs(i - 0.4) * H * 0.0014
            length = H * (0.024 - 0.0034 * i)
            r = H * (0.0080 - 0.0009 * i)
            prims.append(capsule((bx, by, H * 0.0150), (bx, by + length, H * 0.0140), r))
        return prims

    # ------------------------------------------------------------------ #
    # --- геометрия лица -------------------------------------------------- #
    def _face_y(self, x: float, z: float) -> float:
        """Передняя поверхность лица (эллипсоид головы) в точке (x, z)."""
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        y0 = c[1] + hd * 0.24
        ry = hd * 0.58
        dx = x / (hw * 0.82)
        dz = (z - (c[2] - hh * 0.18)) / (hh * 0.70)
        s = max(0.0, 1.0 - dx * dx - dz * dz)
        return y0 + ry * math.sqrt(s)

    def _eye_geom(self, head=None):
        """(центр глазного яблока, радиус, нормаль).

        Если передан готовый череп, передняя поверхность лица берётся
        лучом (ray_cast) — глаз садится точно в кожу, без «выпученности».
        """
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        r = hh * 0.098
        out = []
        for sx in (1, -1):
            x = sx * hw * 0.365
            z = c[2] + hh * 0.050
            y_surface = self._face_y(x, z)
            if head is not None:
                hits = head.ray_cast((x, y_surface + hd * 1.5, z),
                                     (x, y_surface - hd * 1.5, z))
                if hits:
                    y_surface = hits[0].position[1]
            n = np.array([sx * 0.30, 0.95, 0.0])
            n /= np.linalg.norm(n)
            center = np.array([x, y_surface - r * 0.30, z])
            out.append((center, r, n))
        return out

    def _head_volumes(self) -> list[Prim]:
        """Крупные объёмы головы — сливаются мягко."""
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        prims: list[Prim] = []
        add = prims.append
        add(ellipsoid((c[0], c[1] - 0.10 * hd, c[2] + 0.06 * hh),
                      (hw * 0.97, hd * 0.86, hh * 1.00)))
        add(ellipsoid((c[0], c[1] + 0.26 * hd, c[2] - 0.16 * hh),
                      (hw * 0.76, hd * 0.58, hh * 0.64)))
        # скулы — мягким утолщением, без отдельных «жвал»
        for sx in (1, -1):
            zc = c[2] - hh * 0.06
            xc = sx * hw * 0.52
            add(ellipsoid((xc, self._face_y(xc, zc) - hd * 0.22, zc),
                          (hw * 0.15, hd * 0.16, hh * 0.12)))
        # нижняя челюсть
        zj = c[2] - hh * 0.44
        add(ellipsoid((c[0], self._face_y(0, zj) - hd * 0.24, zj),
                      (hw * 0.32, hd * 0.20, hh * 0.15)))
        return prims

    def _head_prims(self) -> list[Prim]:
        H, F = self.H, self.female
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        prims: list[Prim] = []
        add = prims.append

        # --- надбровные дуги (по поверхности лица) ---
        zb = c[2] + hh * 0.24
        for sx in (1, -1):
            xa, xb2 = sx * hw * 0.08, sx * hw * 0.46
            add(capsule((xa, self._face_y(xa, zb + hh * 0.02) - hd * 0.03, zb + hh * 0.03),
                        (xb2, self._face_y(xb2, zb) - hd * 0.03, zb),
                        hh * 0.050 if not F else hh * 0.038))
        # --- нос: переносица → кончик, крылья ---
        z_top = c[2] + hh * 0.16
        z_tip = c[2] - hh * 0.16
        add(capsule((c[0], self._face_y(0, z_top) - hd * 0.05, z_top),
                    (c[0], self._face_y(0, z_tip) - hd * 0.04, z_tip), hw * 0.070))
        add(ellipsoid((c[0], self._face_y(0, z_tip) + hd * 0.02, z_tip),
                      (hw * 0.120, hd * 0.090, hh * 0.058)))
        for sx in (1, -1):
            xn = sx * hw * 0.145
            add(ellipsoid((xn, self._face_y(xn, z_tip - hh * 0.02) - hd * 0.01,
                           z_tip - hh * 0.02), (hw * 0.085, hd * 0.070, hh * 0.045)))
        # --- губы ---
        z_up = c[2] - hh * 0.30
        z_dn = c[2] - hh * 0.355
        add(ellipsoid((c[0], self._face_y(0, z_up) + hd * 0.005, z_up),
                      (hw * 0.170, hd * 0.070, hh * 0.032)))
        add(ellipsoid((c[0], self._face_y(0, z_dn) + hd * 0.005, z_dn),
                      (hw * 0.155, hd * 0.070, hh * 0.034)))
        # --- уши ---
        for sx in (1, -1):
            add(ellipsoid((sx * hw * 0.93, c[1] - 0.04 * hd, c[2] - 0.01 * hh),
                          (hw * 0.105, hd * 0.135, hh * 0.185)))
        # --- веки: нависающая кожа над и под глазным яблоком ---

        # --- шея ---
        add(cone((c[0], c[1] + 0.02 * hd, c[2] - hh * 1.24),
                 (c[0], c[1] - 0.06 * hd, c[2] - hh * 0.74),
                 H * 0.033, H * 0.036))
        return prims

    def _eye_positions(self):
        eyes = self._eye_geom()
        return [pos for pos, _r, _n in eyes], eyes[0][1]

    def _lashes(self) -> mf.Manifold:
        """Верхние ресничные линии: тонкие тёмные дуги над глазами (аниме-стиль)."""
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        F = Field([c[0] - hw * 0.85, c[1] - hd * 0.4, c[2] + hh * 0.02,
                   c[0] + hw * 0.85, c[1] + hd * 1.05, c[2] + hh * 0.30], max(0.6, hh * 0.012))
        for pos, r, n in self._eye_geom():
            y_skin = pos[1] + r * 0.55
            pts = []
            for t in (-1.0, -0.45, 0.2, 0.75, 1.15):
                x = pos[0] + t * r * 1.22
                z = pos[2] + r * (0.56 - 0.24 * t * t + 0.10 * max(0.0, t))
                pts.append((x, y_skin + r * 0.34, z))
            for i in range(len(pts) - 1):
                rad = r * (0.12 if i < 2 else 0.18)
                F.add(capsule(pts[i], pts[i + 1], rad), 0.0)
            # утолщение у внешнего угла — аниме-акцент
            F.add(sphere(pts[-1], r * 0.19), 0.0)
        return F.mesh(smooth_iters=1, what="ресницы", clean=0.06)

    def _pupils(self) -> mf.Manifold:
        """Зрачки: тёмные диски впереди радужки."""
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        r = hh * 0.098
        F = Field([c[0] - hw * 0.7, c[1] - hd * 0.6, c[2] - hh * 0.2,
                   c[0] + hw * 0.7, c[1] + hd * 1.2, c[2] + hh * 0.35], max(0.5, hh * 0.010))
        for pos, _r, _n in self._eye_geom():
            F.add(ellipsoid((pos[0], pos[1] + r * 0.54, pos[2] - r * 0.02),
                            (r * 0.30, r * 0.18, r * 0.36)), 0.0)
        return F.mesh(smooth_iters=1, what="зрачки", clean=0.06)

    def _brows(self) -> mf.Manifold:
        """Брови: два тонких валика над глазами (отдельный объект с тёмным материалом)."""
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        zb = c[2] + hh * 0.225
        F = Field([c[0] - hw * 0.75, c[1] - hd * 0.2, c[2] + hh * 0.10,
                   c[0] + hw * 0.75, c[1] + hd * 0.95, c[2] + hh * 0.36], max(0.7, hh * 0.018))
        for sx in (1, -1):
            pts = []
            for t in (0.0, 0.5, 1.0):
                xb = sx * hw * (0.07 + 0.40 * t)
                zz = zb + hh * (0.020 + 0.012 * math.sin(math.pi * t) - 0.010 * t)
                pts.append((xb, self._face_y(xb, zz) + hd * 0.026, zz))
            F.add(capsule(pts[0], pts[1], hh * 0.030), 0.0)
            F.add(capsule(pts[1], pts[2], hh * 0.026), 0.0)
            F.add(sphere(pts[2], hh * 0.024), 0.0)
        return F.mesh(smooth_iters=1, what="брови", clean=0.05)

    def _head_lids(self) -> list[Prim]:
        """Веки: тонкие складки кожи над и под глазным яблоком."""
        lids: list[Prim] = []
        for pos, r, n in self._eye_geom():
            up = np.array([0.0, 0.0, 1.0])
            for sign, scale in ((1, 1.0), (-1, 0.85)):
                lids.append(ellipsoid(tuple(pos + n * r * 0.62 + up * sign * r * 0.78),
                                      (r * 1.00, r * 0.42 * scale, r * 0.30 * scale)))
        return lids

    def _head_cutters(self) -> list[Prim]:
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        cuts: list[Prim] = []
        # глазная щель: миндалевидная прорезь в коже, в ней видно яблоко
        # линия рта
        z_lip = c[2] - hh * 0.328
        cuts.append(round_box((0.0, self._face_y(0, z_lip) + hd * 0.04, z_lip),
                              (hw * 0.24, hd * 0.09, hh * 0.005)))
        # ноздри
        z_tip = c[2] - hh * 0.20
        for sx in (1, -1):
            cuts.append(sphere((sx * hw * 0.090, self._face_y(0, z_tip) + hd * 0.06, z_tip),
                               hw * 0.026))
        # ушные раковины (неглубокая впадина)
        for sx in (1, -1):
            cuts.append(ellipsoid((sx * hw * 1.05, c[1] - 0.04 * hd, c[2] - 0.01 * hh),
                                  (hw * 0.045, hd * 0.07, hh * 0.10)))
        return cuts

    def _hair_solid(self) -> mf.Manifold:
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        pad = 0.030 * hw
        F = Field([c[0] - hw * 1.3, c[1] - hd * 1.4, c[2] - hh * 1.3,
                   c[0] + hw * 1.3, c[1] + hd * 1.4, c[2] + hh * 1.4], 2.2)
        # оболочка по черепу
        F.add(ellipsoid((c[0], c[1] - 0.02 * hd, c[2] + 0.08 * hh),
                        (hw * 0.98 + pad, hd * 0.96 + pad, hh + pad)), 0.0)
        # срезаем лицо (спереди) и всё ниже линии роста
        F.cut(ellipsoid((c[0], c[1] + 0.56 * hd, c[2] - 0.04 * hh),
                        (hw * 0.92, hd * 0.68, hh * 0.88)))
        F.cut(ellipsoid((c[0], c[1] - 0.10 * hd, c[2] - hh * 1.35),
                        (hw * 3.2, hd * 3.0, hh * 1.05)))
        # лоб открыт: плавная линия роста волос
        F.cut(ellipsoid((c[0], c[1] + 0.92 * hd, c[2] + 0.46 * hh),
                        (hw * 1.45, hd * 0.95, hh * 0.66)))
        # виски открыты, волосы не «обнимают» уши
        for sx in (1, -1):
            F.cut(ellipsoid((sx * hw * 1.05, c[1] + 0.06 * hd, c[2] - 0.30 * hh),
                            (hw * 0.50, hd * 0.75, hh * 0.52)))
        try:
            return F.mesh(smooth_iters=2, what="волосы", clean=0.05)
        except GeometryError:
            F2 = Field([c[0] - hw * 1.3, c[1] - hd * 1.4, c[2] - hh * 1.3,
                        c[0] + hw * 1.3, c[1] + hd * 1.4, c[2] + hh * 1.4], 3.0)
            F2.add(ellipsoid((c[0], c[1] - 0.02 * hd, c[2] + 0.08 * hh),
                             (hw * 0.98 + pad, hd * 0.96 + pad, hh + pad)), 0.0)
            F2.cut(ellipsoid((c[0], c[1] + 0.50 * hd, c[2] - 0.10 * hh),
                             (hw * 0.90, hd * 0.66, hh * 0.84)))
            F2.cut(round_box((c[0], c[1] + 0.04 * hd, c[2] - hh * 0.62),
                             (hw * 2.6, hd * 2.8, hh * 0.55)))
            return F2.mesh(smooth_iters=1, what="волосы", clean=0.05)

    # ------------------------------------------------------------------ #
    def build(self) -> dict:
        p = self.p
        d = DETAILS[p.detail]
        H, F = self.H, self.female

        # --- корпус + руки + ноги ---
        body = Field([-H * 0.42, -H * 0.18, -H * 0.02, H * 0.42, H * 0.18, H * 0.90],
                     d["body"])
        for prim in self._torso_prims():
            body.add(prim, H * 0.012)
        body.add_many(self._neck_prims(), H * 0.010)
        for side in (1, -1):
            body.add_many(self._arm_prims(side), H * 0.010)
            body.add_many(self._leg_prims(side), H * 0.012)
        body_solid = body.mesh(smooth_iters=d["smooth"], simplify=d["simplify"],
                               what="тело", polish=d.get("polish", 0.0))

        # --- голова ---
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        head = Field([c[0] - hw * 1.25, c[1] - hd * 1.3, c[2] - hh * 1.55,
                      c[0] + hw * 1.25, c[1] + hd * 1.3, c[2] + hh * 1.35], d["head"])
        for prim in self._head_volumes():
            head.add(prim, H * 0.0085)
        for prim in self._head_prims():
            head.add(prim, H * 0.0016)
        for cut in self._head_cutters():
            head.cut(cut, H * 0.0008)
        head_solid = head.mesh(smooth_iters=1, simplify=d["simplify"] * 0.6, what="голова",
                               polish=d.get("polish", 0.0))

        # --- кисти ---
        hands = []
        for side in (1, -1):
            origin = self.wrist.copy()
            direction = self.hand_dir.copy()
            if side < 0:
                origin = self.mirror(origin)
                direction = self.mirror(direction)
            hand = Field([origin[0] - H * 0.10, origin[1] - H * 0.08,
                          origin[2] - H * 0.14, origin[0] + H * 0.10,
                          origin[1] + H * 0.08, origin[2] + H * 0.09], d["hand"])
            hand.add_many(self._hand_prims(side, origin, direction), H * 0.004)
            hands.append(hand.mesh(smooth_iters=1, simplify=d["simplify"] * 0.5,
                                   what="кисть", polish=d.get("polish", 0.0)))

        # --- стопы ---
        feet = []
        for side in (1, -1):
            ankle = self.ankle if side > 0 else self.mirror(self.ankle)
            foot = Field([ankle[0] - H * 0.05, ankle[1] - H * 0.06, -H * 0.01,
                          ankle[0] + H * 0.05, ankle[1] + H * 0.17, H * 0.09], d["foot"])
            foot.add_many(self._foot_prims(side), H * 0.004)
            # плоская подошва: срезаем всё ниже пола
            foot.cut(round_box((ankle[0], H * 0.04, -H * 0.03),
                               (H * 0.20, H * 0.40, H * 0.03)), H * 0.0015)
            feet.append(foot.mesh(smooth_iters=1, simplify=d["simplify"] * 0.5,
                                  what="стопа", polish=d.get("polish", 0.0)))

        parts = [body_solid, head_solid, *hands, *feet]
        skin = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
        skin = _ensure_on_floor(skin)
        if skin.is_empty():
            raise GeometryError("Не удалось собрать тело человека.")

        result = {"skin": skin, "extras": []}

        # --- глаза ---
        if p.eyes:
            eye_data = self._eye_geom(head_solid)
            positions = [pos for pos, _r, _n in eye_data]
            r = eye_data[0][1]
            pts = np.array(positions)
            lo = pts.min(axis=0) - r * 1.6
            hi = pts.max(axis=0) + r * 1.6
            # Глаз — миндалевидная линза: шар пересекаем «вековой» формой.
            seg = 48
            parts = []
            for pos in positions:
                ball = mf.Manifold.sphere(r, seg).scale((1.30, 0.62, 1.02))
                ball = ball.translate((float(pos[0]), float(pos[1]), float(pos[2])))
                almond = mf.Manifold.sphere(r * 1.2, seg).scale((1.28, 1.9, 0.62))
                almond = almond.translate((float(pos[0]), float(pos[1]), float(pos[2]) + r * 0.02))
                parts.append(mf.Manifold.batch_boolean([ball, almond], mf.OpType.Intersect)
                             .translate((0.0, 0.0, 0.0)))
            try:
                eyeballs = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
                result["extras"].append(("eyes", eyeballs, "eyes"))
            except Exception:
                pass
            # радужка/зрачок — отдельный объект чуть впереди глаз
            try:
                fl = Field([lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]], max(0.8, r / 14))
                for pos, _rr, _n in eye_data:
                    # радужка стоит впереди линзы глаза
                    fl.add(ellipsoid((pos[0], pos[1] + r * 0.34, pos[2] - r * 0.02),
                                     (r * 0.62, r * 0.32, r * 0.70)), 0.0)
                iris = fl.mesh(smooth_iters=1, what="радужка", clean=0.05)
                result["extras"].append(("iris", iris, "iris"))
            except GeometryError:
                pass

        # --- ресницы и зрачки (аниме-глаз: линия века + тёмный зрачок) ---
        try:
            result["extras"].append(("lashes", self._lashes(), "lashes"))
        except GeometryError:
            pass
        try:
            result["extras"].append(("pupils", self._pupils(), "pupils"))
        except GeometryError:
            pass

        # --- брови ---
        if p.hair:
            try:
                result["extras"].append(("brows", self._brows(), "brows"))
            except GeometryError:
                pass

        # --- волосы ---
        if p.hair:
            try:
                result["extras"].append(("hair", self._hair_solid(), "hair"))
            except GeometryError:
                pass
        return result


def _ensure_on_floor(m: mf.Manifold) -> mf.Manifold:
    bb = m.bounding_box()
    if abs(bb[2]) > 1e-6:
        m = m.translate((0.0, 0.0, -bb[2]))
    return m


def build_human(params: HumanParams) -> dict:
    return Anatomy(params).build()
