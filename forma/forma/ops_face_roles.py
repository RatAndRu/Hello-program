"""Команда пользовательской разметки экспортных треугольников."""

from __future__ import annotations

from .errors import DslError
from .face_visibility import normalize_roles
from .geometry import _clean_manifold_arrays
from .ops import op


def _face_ids(a, key: str) -> list[int]:
    if not a.has(key):
        return []
    value = a.value(key)
    values = value if isinstance(value, (list, tuple)) else [value]
    out = set()
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)) \
                or int(item) != float(item) or int(item) < 0:
            raise DslError(
                f"Номера граней «{key}» должны быть целыми числами от нуля.",
                hint="Например: outside=[0, 4, 9]. Нумерация видна в режиме «грани».",
                line=a.cmd.line, command=a.cmd.text,
            )
        out.add(int(item))
    return sorted(out)


@op(
    "faces",
    aliases=("полигоны", "грани", "разметка_граней", "разметка_полигонов"),
    category="Проверка",
    summary="Назначает треугольникам требование: outside — целиком снаружи других тел, "
            "inside — целиком и строго внутри другого тела. Неуказанные грани серые. "
            "Команда заменяет прежнюю разметку объекта; проверка: check объект наружность.",
    example=("голова = box size=[80,70,60]\n"
             "корень = box size=[8,8,12] at=[0,0,-4]\n"
             "корень = полигоны inside=[0,1,2,3]\n"
             "check корень наружность"),
    params={
        "objects": "один объект; можно также написать `объект = полигоны …`",
        "outside": "номера синих граней, обязанных быть снаружи: [0,4,9]",
        "inside": "номера красных граней, обязанных быть строго внутри: [10,11]",
        "neutral": "необязательное явное перечисление серых граней; не пересекается с outside/inside",
    },
    positional=["objects"],
)
def faces(a, name):
    if name:
        solid = a.scene.resolve(name, "объект")
        if a.has("objects"):
            raise DslError("Объект задан и слева от «=», и в аргументах.",
                           line=a.cmd.line, command=a.cmd.text)
    else:
        solids = a.solids()
        if len(solids) != 1:
            raise DslError("Разметка граней выполняется для одного объекта за команду.",
                           line=a.cmd.line, command=a.cmd.text)
        solid = solids[0]
    outside = _face_ids(a, "outside")
    inside = _face_ids(a, "inside")
    neutral = _face_ids(a, "neutral")
    overlap = (set(outside) & set(inside)) | (set(neutral) & (set(outside) | set(inside)))
    if overlap:
        raise DslError(
            "Одна грань не может быть одновременно синей, красной и серой: "
            + ", ".join(map(str, sorted(overlap)[:12])),
            line=a.cmd.line, command=a.cmd.text,
        )
    _verts, triangles = _clean_manifold_arrays(solid.manifold)
    count = len(triangles)
    invalid = sorted({i for i in outside + inside + neutral if i >= count})
    if invalid:
        raise DslError(
            f"У «{solid.name}» нет грани {invalid[0]}: доступны индексы 0…{max(0, count - 1)}.",
            hint="После изменения топологии выберите грани заново в режиме «грани»; "
                 "старые номера не переносятся молча на другую сетку.",
            line=a.cmd.line, command=a.cmd.text,
        )
    # Нейтральные — это отсутствие требования. Полная команда заменяет старую
    # разметку, поэтому UI не выписывает тысячи серых индексов в проект.
    solid.face_roles = normalize_roles({"outside": outside, "inside": inside})
    solid.meta["face_roles_line"] = a.cmd.line
    a.scene.log(
        "info",
        f"разметка граней «{solid.name}»: снаружи {len(outside)}, "
        f"строго внутри {len(inside)}, серые остальные",
        a.cmd.line,
    )
    return None
