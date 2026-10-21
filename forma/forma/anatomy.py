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
               "simplify": 0.5},
    "средний": {"body": 4.0, "head": 2.2, "hand": 2.0, "foot": 2.6, "smooth": 1,
                "simplify": 0.35},
    "высокий": {"body": 3.2, "head": 1.7, "hand": 1.5, "foot": 2.0, "smooth": 1,
                "simplify": 0.2},
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
        self.head_c = np.array([0.0, 0.0, H - self.head_h * 0.54])
        self.shoulder_z = H * 0.815
        self.chest_z = H * 0.745
        self.waist_z = H * 0.625
        self.hip_z = H * 0.53
        self.crotch_z = H * 0.475
        self.knee_z = H * 0.285
        self.ankle_z = H * 0.042

        self.shoulder_x = H * (0.098 if not F else 0.090)
        self.hip_x = H * (0.055 if not F else 0.060)
        self.knee_x = H * (0.058 if not F else 0.060)
        self.ankle_x = H * (0.058 if not F else 0.060)

        self.chest_w = H * (0.105 if not F else 0.098) * (0.92 + 0.12 * b)
        self.chest_d = H * (0.068 if not F else 0.062) * (0.92 + 0.14 * b)
        self.waist_w = H * (0.077 if not F else 0.070) * (0.92 + 0.20 * (b - 1) + 0.08 * b)
        self.waist_d = H * (0.058 if not F else 0.056) * (0.92 + 0.22 * (b - 1) + 0.06 * b)
        self.hip_w = H * (0.093 if not F else 0.102) * (0.92 + 0.14 * b)
        self.hip_d = H * (0.068 if not F else 0.074) * (0.92 + 0.16 * b)
        self.head_w = H * (0.047 if not F else 0.045)
        self.head_d = H * (0.058 if not F else 0.055)
        self.head_hh = self.head_h * 0.52

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
        add(ellipsoid((0, H * 0.004, S.chest_z), (S.chest_w * 1.06, S.chest_d * 1.02, H * 0.098)))
        add(ellipsoid((0, H * 0.010, S.chest_z + H * 0.045),
                      (S.chest_w * 0.96, S.chest_d * 0.92, H * 0.052)))
        # грудь (женская)
        if F:
            for sx in (1, -1):
                add(ellipsoid((sx * S.chest_w * 0.42, S.chest_d * 1.02, S.chest_z + H * 0.005),
                              (S.chest_w * 0.34, S.chest_d * 0.30, H * 0.036)))
        # мужская грудь — единый объём без «шаров»; рельеф даёт рельеф мышц
        # широчайшие (спина) и трапеции
        for sx in (1, -1):
            add(ellipsoid((sx * S.chest_w * 0.76, -S.chest_d * 0.30, S.chest_z - H * 0.012),
                          (S.chest_w * 0.20, S.chest_d * 0.46, H * 0.078)))
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
                 H * 0.040 if not F else H * 0.034,
                 H * 0.050 if not F else H * 0.042),
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
        # колодка: пятка → плюсна → носок (мягко, без «ботинка»)
        prims.append(round_box((x, -H * 0.035 + H * 0.050, H * 0.026),
                               (H * 0.034, H * 0.100, H * 0.026), H * 0.013))
        prims.append(round_box((x, H * 0.105, H * 0.019),
                               (H * 0.038, H * 0.090, H * 0.019), H * 0.010))
        # подъём и переход к голени
        prims.append(ellipsoid((x, ankle[1] + H * 0.004, H * 0.036),
                               (H * 0.029, H * 0.052, H * 0.028)))
        prims.append(capsule((x, ankle[1], H * 0.038), (x, ankle[1], H * 0.072), H * 0.026))
        # пятка
        prims.append(sphere((x, -H * 0.014, H * 0.026), H * 0.025))
        # пальцы ног
        for i in range(5):
            bx = x + (0.62 - i) * H * 0.0122
            by = H * 0.112 - abs(i - 0.4) * H * 0.002
            length = H * (0.031 - 0.0042 * i)
            r = H * (0.0092 - 0.0011 * i)
            prims.append(capsule((bx, by, H * 0.0155), (bx, by + length, H * 0.0135), r))
        return prims

    # ------------------------------------------------------------------ #
    def _head_prims(self) -> list[Prim]:
        H, F = self.H, self.female
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        prims: list[Prim] = []
        # череп
        prims.append(ellipsoid((c[0], c[1] - hd * 0.06, c[2] + hh * 0.06),
                               (hw * 0.98, hd * 0.98, hh * 0.98)))
        # лицо и скулы
        prims.append(ellipsoid((c[0], c[1] + hd * 0.42, c[2] - hh * 0.20),
                               (hw * 0.84, hd * 0.62, hh * 0.70)))
        for sx in (1, -1):
            prims.append(ellipsoid((sx * hw * 0.62, c[1] + hd * 0.52, c[2] - hh * 0.08),
                                   (hw * 0.30, hd * 0.32, hh * 0.24)))
        # челюсть и подбородок
        prims.append(ellipsoid((c[0], c[1] + hd * 0.55, c[2] - hh * 0.62),
                               (hw * 0.66, hd * 0.48, hh * 0.40)))
        prims.append(ellipsoid((c[0], c[1] + hd * 0.72, c[2] - hh * 0.72),
                               (hw * 0.34, hd * 0.24, hh * 0.20)))
        # надбровье
        prims.append(capsule((c[0] - hw * 0.56, c[1] + hd * 0.62, c[2] + hh * 0.30),
                             (c[0] + hw * 0.56, c[1] + hd * 0.62, c[2] + hh * 0.30),
                             hh * 0.14 if not F else hh * 0.10))
        # нос
        prims.append(cone((c[0], c[1] + hd * 0.62, c[2] + hh * 0.22),
                          (c[0], c[1] + hd * 0.92, c[2] - hh * 0.16),
                          hw * 0.16, hw * 0.24))
        prims.append(sphere((c[0], c[1] + hd * 0.92, c[2] - hh * 0.15), hw * 0.20))
        for sx in (1, -1):
            prims.append(sphere((sx * hw * 0.20, c[1] + hd * 0.86, c[2] - hh * 0.25), hw * 0.12))
        # губы
        prims.append(ellipsoid((c[0], c[1] + hd * 0.80, c[2] - hh * 0.42),
                               (hw * 0.38, hd * 0.18, hh * 0.085)))
        prims.append(ellipsoid((c[0], c[1] + hd * 0.76, c[2] - hh * 0.54),
                               (hw * 0.33, hd * 0.16, hh * 0.075)))
        # уши
        for sx in (1, -1):
            prims.append(ellipsoid((sx * hw * 0.98, c[1] + hd * 0.02, c[2] - hh * 0.05),
                                   (hw * 0.14, hd * 0.28, hh * 0.34)))
            prims.append(ellipsoid((sx * hw * 0.94, c[1] + hd * 0.06, c[2] - hh * 0.10),
                                   (hw * 0.09, hd * 0.20, hh * 0.24)))
        # шея входит в голову
        prims.append(cone((c[0], c[1] + hd * 0.10, c[2] - hh * 1.00),
                          (c[0], c[1] - hd * 0.05, c[2] - hh * 0.62),
                          H * 0.042, H * 0.050))
        return prims

    def _eye_positions(self):
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        r = hh * 0.125
        return [np.array([sx * hw * 0.36, c[1] + hd * 0.60, c[2] + hh * 0.10])
                for sx in (1, -1)], r

    def _head_cutters(self) -> list[Prim]:
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        cuts: list[Prim] = []
        # глазные впадины
        for sx in (1, -1):
            cuts.append(sphere((sx * hw * 0.36, c[1] + hd * 0.76, c[2] + hh * 0.10), hh * 0.115))
        return cuts

    def _hair_solid(self) -> mf.Manifold:
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        F = Field([c[0] - hw * 1.25, c[1] - hd * 1.3, c[2] - hh * 1.25,
                   c[0] + hw * 1.25, c[1] + hd * 1.3, c[2] + hh * 1.35], 2.2)
        F.add(ellipsoid((c[0], c[1] - hd * 0.05, c[2] + hh * 0.10),
                        (hw * 1.06, hd * 1.06, hh * 1.10)), 0.0)
        # убираем лицо и шею
        F.cut(ellipsoid((c[0], c[1] + hd * 0.95, c[2] + hh * 0.05),
                        (hw * 0.92, hd * 0.62, hh * 0.95)))
        F.cut(round_box((c[0], c[1] + hd * 0.1, c[2] - hh * 0.95), (hw * 2.2, hd * 2.6, hh * 0.6)))
        try:
            return F.mesh(smooth_iters=1, what="волосы")
        except GeometryError:
            F2 = Field([c[0] - hw * 1.25, c[1] - hd * 1.3, c[2] - hh * 1.25,
                        c[0] + hw * 1.25, c[1] + hd * 1.3, c[2] + hh * 1.35], 3.0)
            F2.add(ellipsoid((c[0], c[1] - hd * 0.05, c[2] + hh * 0.10),
                             (hw * 1.05, hd * 1.05, hh * 1.08)), 0.0)
            F2.cut(ellipsoid((c[0], c[1] + hd * 1.05, c[2] + hh * 0.05),
                             (hw * 1.0, hd * 0.7, hh * 1.0)))
            return F2.mesh(smooth_iters=1, what="волосы")

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
                               what="тело")

        # --- голова ---
        c = self.head_c
        hw, hd, hh = self.head_w, self.head_d, self.head_hh
        head = Field([c[0] - hw * 1.25, c[1] - hd * 1.3, c[2] - hh * 1.55,
                      c[0] + hw * 1.25, c[1] + hd * 1.3, c[2] + hh * 1.35], d["head"])
        for prim in self._head_prims():
            head.add(prim, H * 0.0055)
        for cut in self._head_cutters():
            head.cut(cut, H * 0.002)
        head_solid = head.mesh(smooth_iters=2, simplify=d["simplify"] * 0.6, what="голова")

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
                                   what="кисть"))

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
                                  what="стопа"))

        parts = [body_solid, head_solid, *hands, *feet]
        skin = mf.Manifold.batch_boolean(parts, mf.OpType.Add)
        skin = _ensure_on_floor(skin)
        if skin.is_empty():
            raise GeometryError("Не удалось собрать тело человека.")

        result = {"skin": skin, "extras": []}

        # --- глаза ---
        if p.eyes:
            positions, r = self._eye_positions()
            pts = np.array(positions)
            lo = pts.min(axis=0) - r * 1.6
            hi = pts.max(axis=0) + r * 1.6
            fs = Field([lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]], max(0.8, r / 12))
            for pos in positions:
                fs.add(sphere(pos, r), 0.0)
            try:
                eyes = fs.mesh(smooth_iters=1, what="глаза")
                result["extras"].append(("eyes", eyes, "eyes"))
            except GeometryError:
                pass
            # радужка/зрачок — отдельный объект чуть впереди глаз
            try:
                fl = Field([lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]], max(0.8, r / 14))
                for pos in positions:
                    fl.add(sphere(pos + np.array([0, r * 0.78, 0]), r * 0.46), 0.0)
                iris = fl.mesh(smooth_iters=1, what="радужка")
                result["extras"].append(("iris", iris, "iris"))
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
