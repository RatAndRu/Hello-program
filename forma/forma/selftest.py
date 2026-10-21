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
