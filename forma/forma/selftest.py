"""Самопроверка геометрического ядра: набор мини-сценариев с ожидаемыми проверками."""

from __future__ import annotations

from .run import build

CASES = [
    {
        "name": "Куб 50 мм",
        "script": """блок = box size=[50,50,50]
check блок size 50..50 50..50 50..50
check блок volume 125..125
check блок watertight
check блок parts 1
""",
    },
    {
        "name": "Кружка с ручкой",
        "script": """стенка = 4
высота = 95
корпус = lathe points=[[0,0],[40,0],[42,3],[42,88],[41,92],[38,92],[0,92]] segments=128 fillet=2 thickness=стенка open=top
ручка = sweep path=[[40,0,30],[56,0,30],[63,0,45],[63,0,66],[56,0,76],[40,0,76]] radius=5.5 smooth=6
кружка = union [корпус, ручка]
check кружка watertight
check кружка height 90..100
check кружка wall 3..5
check кружка symmetric y
check кружка genus 1
""",
    },
    {
        "name": "Фигура, текстура и анимация",
        "script": """ч = human height=420 sex=ж build=обычный pose=a detail=низкий
color ч #e0b298
texture ч kind=кожа scale=1
light preset=студия
scene bg=#10151c exposure=1.05
animate kind=spin seconds=3
check ч height 415..425
check ч watertight
check ч parts 1
""",
    },
    {
        "name": "Кузов лофтом",
        "script": """сеч1 = [[-30,10],[30,10],[32,30],[0,36],[-32,30]]
сеч2 = [[-34,8],[34,8],[36,32],[0,40],[-36,32]]
сеч3 = [[-24,6],[24,6],[26,34],[0,42],[-26,34]]
кузов = loft sections=[сеч1,сеч2,сеч3] positions=[-200,0,200] axis=x smooth=4
check кузов width 390..410
check кузов depth 70..90
check кузов height 33..38
check кузов watertight
""",
    },
    {
        "name": "Детальные вмятины, полости и пуговица",
        "script": """вмятина = face_box size=[60,50,40] mode=вогнутый profile=линза relief=8 margin=5 faces=верх detail=4
check вмятина size 60..60 50..50 40..40
check вмятина watertight
check вмятина parts 1
полая = prism sides=6 radius=35 height=60 wall=3 cavity=верх cavity_depth=40
check полая watertight
check полая parts 1
стержень = pipe diameter=20 wall=2 hole=нет length=80 angle=65 radius=40
check стержень watertight
check стержень parts 1
сгиб = fold_sheet width=80 length=180 thickness=1.2 parts=3 angle=115 joint=сплайн
check сгиб watertight
check сгиб parts 1
звезда = disc diameter=100 thickness=5 outline=вогнутая4 indent=.35
check звезда size 100..100 100..100 5..5
check звезда watertight
крючок = strip length=180 width=10 thickness=4 path=J curve=24
check крючок watertight
check крючок parts 1
пуговица = sewing_button diameter=30 thickness=4 holes=4 hole_d=3 pitch=8 rim_side=верх top=вогнутая
check пуговица watertight
check пуговица parts 1
check пуговица genus 4
""",
    },
]


def run_selftest() -> dict:
    results = []
    ok_all = True
    for case in CASES:
        try:
            b = build(case["script"])
        except Exception as exc:
            results.append({"name": case["name"], "ok": False, "error": str(exc)})
            ok_all = False
            continue
        if not b.ok:
            results.append({"name": case["name"], "ok": False, "error": b.error})
            ok_all = False
            continue
        checks = b.analysis["checks"] if b.analysis else []
        passed = all(c["ok"] for c in checks)
        ok_all = ok_all and passed
        results.append({
            "name": case["name"],
            "ok": passed,
            "checks": checks,
            "tris": b.analysis["metrics"]["tris"] if b.analysis else 0,
            "timings": b.timings,
        })
    return {"ok": ok_all, "cases": results}
