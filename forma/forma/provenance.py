"""Плоский provenance Forma: операция, прямые исходники и строка DSL."""
from __future__ import annotations

import re
from typing import Any

_IDENT_RE = re.compile(r"[^\W\d]\w*", re.UNICODE)
_OBJECT_KEYS = {"objects", "object", "base", "into", "source", "target"}


def direct_inputs(scene, cmd, outputs: set[str]) -> list[str]:
    """Находит только существующие имена в объектных аргументах команды.

    Числа, цвета и имена параметров не становятся фиктивными родителями. Для
    in-place операции имя может совпадать с результатом — это полезная связь
    «старая версия → новая версия», а не рекурсивное дерево.
    """
    raws = list(getattr(cmd, "args", []) or [])
    for key, raw in (getattr(cmd, "kwargs", {}) or {}).items():
        if key.lower() in _OBJECT_KEYS:
            raws.append(raw)
    found: list[str] = []
    for raw in raws:
        if not isinstance(raw, str):
            continue
        for match in _IDENT_RE.finditer(raw):
            name = match.group(0)
            if name not in scene.objects:
                continue
            # Для новой детали с другим именем output исключаем; для замены
            # того же имени оставляем self-parent, если объект действительно
            # был входом (это различает вызывающий код по before_ids).
            if name in outputs and name not in getattr(cmd, "args", []):
                continue
            if name not in found:
                found.append(name)
    return found


def record(scene, object_name: str, operation: str, line: int, parents: list[str] | None = None,
           command: str = "", source: str = "", extra: dict | None = None) -> dict:
    row: dict[str, Any] = {
        "object": str(object_name),
        "operation": str(operation or "unknown"),
        "op": str(operation or "unknown"),
        "parents": list(dict.fromkeys(str(item) for item in (parents or []))),
        "line": int(line or 0),
        "source": str(source or "script"),
    }
    if command:
        row["command"] = str(command)[:300]
    if extra:
        for key, value in extra.items():
            if key not in {"children", "tree"}:
                row[key] = value
    scene.provenance.append(row)
    del scene.provenance[:-int(getattr(scene, "provenance_limit", 512))]
    solid = scene.objects.get(object_name)
    if solid is not None:
        # На детали лежит только один плоский паспорт, а не вся рекурсивная
        # история. Родители разрешаются по именам при необходимости.
        solid.meta["provenance"] = dict(row)
    return row


def record_execution(scene, cmd, result, before_ids: dict[str, int]) -> None:
    """Снимок после обычной DSL-команды, включая in-place и multi-output ops."""
    outputs: set[str] = set()
    if result is not None and getattr(result, "name", None) in scene.objects:
        outputs.add(result.name)
    if getattr(cmd, "target", None) and cmd.target in scene.objects:
        outputs.add(cmd.target)
    for name, solid in scene.objects.items():
        if name not in before_ids or before_ids[name] != id(solid.manifold):
            if result is None or getattr(result, "name", None) == name or name not in outputs:
                outputs.add(name)
    if not outputs:
        return
    operation = (getattr(cmd, "verb", "") or "unknown").lower()
    for name in sorted(outputs):
        parents = direct_inputs(scene, cmd, {name})
        # Для новой детали не добавляем её саму; для in-place замены self-parent
        # допустим только если имя было во входах и объект сменился.
        parents = [parent for parent in parents if parent != name or name in before_ids]
        record(scene, name, operation, getattr(cmd, "line", 0), parents,
               command=getattr(cmd, "text", ""))
