# РЕЦЕПТЫ КОМАНД — копируйте в окно сценария

Всё в миллиметрах, ось Z — вверх. Каждая строка — одна команда.
Вставляйте блок целиком и нажимайте «Собрать» (Ctrl+Enter).

---

## 1. Ваза с вогнутой кромкой (232 мм, стенка 9 мм)

```
ваза = lathe points=[
    [0, 0], [38, 0], [58, 4], [72, 26], [78, 62], [78, 96],
    [70, 132], [66, 158], [70, 186], [78, 208], [80, 220],
    [76, 230], [66, 232], [61, 229], [60, 222], [64, 212],
    [70, 206], [68, 196], [62, 180], [58, 160], [62, 140],
    [69, 120], [70, 96], [70, 64], [64, 28], [52, 7], [0, 7]
  ] segments=112 smooth=2
color ваза #cfd8e6 material=ceramic
check ваза watertight
check ваза wall 7..11
check ваза height 225..240
```

---

## 2. Бутылка 0,5 л с рифлёной пробкой

```
корпус = lathe points=[
    [0, 0], [36, 0], [38, 5], [38, 148],
    [36, 172], [28, 191], [20, 205], [15, 215],
    [15, 252], [16.2, 257], [16.2, 263], [0, 263]
  ] segments=128 smooth=2
полость = lathe points=[
    [0, 4], [33, 4], [33, 146], [31, 170], [24, 189],
    [17, 203], [12, 212], [12, 269], [0, 269]
  ] segments=128 smooth=2
бутылка = difference [корпус, полость]
color бутылка #8fd8c4 metal=0.0 rough=0.12

пробка = cylinder radius=18 height=26 segments=96 round=3
пробка = place [пробка] at=[0,0,248]
ложбина = box size=[5.6,7,18] at=[19.2,0,261]
ложбины = array [ложбина] count=24 mode=radial around=z center=[0,0,0]
пробка = difference [пробка, ложбины]
color пробка #3f7fe0 material=plastic
check бутылка wall 2..6
check пробка parts 1
```

---

## 3. Шестерня: 20 зубьев, шпоночный паз, окна четырёх форм

```
диск = cylinder radius=58 height=12 segments=128
зуб = box size=[18,16,12] at=[62,0,0]
зубья = array [зуб] count=20 mode=radial around=z center=[0,0,0]
заготовка = union [диск, зубья]

ступица = cylinder radius=26 height=14 segments=96 round=1.5
шестерня = union [заготовка, ступица]

вал = cylinder radius=11 height=60 segments=72
вал = place [вал] at=[0,0,-20]
паз = box size=[6,20,60]
паз = place [паз] at=[12,0,-20]
шестерня = difference [шестерня, вал, паз]

окно1 = cylinder radius=9 height=40 segments=64
окно1 = place [окно1] at=[40,0,6] align=center
окно2 = extrude profile=[[-10,-9],[10,-9],[0,12]] height=40
окно2 = place [окно2] at=[28,28,6] align=center
окно3 = box size=[15,15,40] round=2
окно3 = place [окно3] at=[0,40,6] align=center
окно4 = cylinder radius=10 height=40 segments=64
окно4 = scale [окно4] factor=[1.0,0.55,1.0]
окно4 = place [окно4] at=[-28,28,6] align=center
шестерня = difference [шестерня, окно1, окно2, окно3, окно4]
color шестерня #c9873c metal=0.85 rough=0.28
check шестерня parts 1
check шестерня genus 5
```

> Вариант с настоящим зубчатым венцом (20 трапециевидных зубьев, 8 окон)
> лежит в примере «Шестерня».

---

## 4. Витрина инструментов: twist, bend, taper, extrude, slice, align

```
скрутка = box size=[46,46,320] round=4
скрутка = twist [скрутка] angle=240 axis=z

изгиб = box size=[26,190,340] round=6
изгиб = bend [изгиб] angle=95

конус = cylinder radius=58 height=300 segments=96
конус = taper [конус] factor=0.32 axis=z

рамка = extrude profile=[[-95,-95],[95,-95],[95,95],[-95,95]] holes=[[[-58,-58],[58,-58],[58,58],[-58,58]]] height=26 fillet=8

куб = box size=[150,150,150] round=8
куб = slice [куб] axis=z at=78 keep=top

цилиндр = cylinder radius=34 height=190 segments=72
цилиндр = align [цилиндр] x=center y=center z=min
```

---

## 5. Кружка с ручкой (проверка стенки и герметичности)

```
корпус = lathe points=[[0,0],[42,0],[44,2],[44,90],[42,95],[38,95],[38,5],[0,5]] segments=160 smooth=2
ручка = sweep path=[[42,0,25],[62,0,30],[62,0,70],[42,0,75]] radius=6 smooth=10
кружка = union [корпус, ручка]
color кружка #e8e2d6 material=ceramic
check кружка watertight
check кружка wall 3..6
check кружка height 88..98
```

---

## 6. Пришелец из капли (метаболы)

```
пришелец = blob spheres=[
    [0, 0, 120, 95], [0, 0, 240, 70], [0, 0, 330, 62],
    [0, 0, 460, 120], [0, 0, 520, 92],
    [-108, 0, 679, 16], [108, 0, 679, 16]
  ] capsules=[
    [-52, 0, 540, -108, 0, 679, 7],
    [52, 0, 540, 108, 0, 679, 7],
    [-80, 0, 310, -190, 0, 190, 18],
    [80, 0, 310, 190, 0, 190, 18]
  ] blend=34
пришелец = place [пришелец] at=[0,0,0] align=bottom
глаз = sphere radius=54 segments=48
глаз = scale [глаз] factor=[1.05,0.52,1.20]
глаз = place [глаз] at=[-47,84,468] align=center
color пришелец #86d9b0 rough=0.42
check пришелец parts 1
```

---

## 7. Манекен в T-позе (фрагмент)

```
голова = sphere radius=112 segments=72
голова = scale [голова] factor=[0.86,0.94,1.16]
голова = place [голова] at=[0,0,1655] align=center

бицепс_л = capsule radius=60 height=400 segments=48
бицепс_л = rotate [бицепс_л] angle=90 axis=y
бицепс_л = place [бицепс_л] at=[-370,0,1425] align=center

бедро_л = capsule radius=92 height=560 segments=64
бедро_л = place [бедро_л] at=[-118,0,745] align=center
```

> Целиком — пример «Манекен в T-позе»: 33 000 треугольников, одна деталь.

---

## 8. Кузов: лофт по длине + стёкла-«фонарь» + арки

```
кузов = loft sections=[[ ... сечение ... ], ...] positions=[-2200,-2050,...] axis=x smooth=4 profile_smooth=2
арка = cylinder radius=440 height=330 segments=72
арка = rotate [арка] angle=90 axis=x
арка = place [арка] at=[-1400,745,335] align=center
кузов = difference [кузов, арка]

зона1 = box size=[1500,4000,520]
зона1 = place [зона1] at=[-60,0,940]
с1 = intersect [кузов, зона1]
...
стекло = union [с1, с2, с3]
стекло = scale [стекло] factor=[1.003,1.005,1.003]
show кузов
```

> Целиком — пример «Кузов машины»: 72 000 треугольников, 4 колеса, стёкла, швы дверей.

---

## 9. Анимация и материалы

```
анимация: animate kind=spin axis=z seconds=4 loop=true
мрамор:   texture кружка kind=marble scale=1.4
металл:   color деталь #c9ced8 metal=0.9 rough=0.2
```

---

## 10. Проверки (что ядро сообщает словами)

```
check деталь watertight
check деталь wall 3..5
check деталь height 90..110
check деталь volume 300..500
check деталь symmetric x 3
check деталь flat_bottom 1..
```
