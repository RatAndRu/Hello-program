"""Ошибки, которые понятны человеку и нейросети."""

from __future__ import annotations


class FormaError(Exception):
    """Базовая ошибка с подсказкой и номером строки.

    Если ошибка вызвана конкретным параметром, в неё кладутся его имя,
    допустимые рамки (``min``/``max``) и то, что было задано. По ним окно
    превью честно объясняет, **почему** деталь не построилась, а не просто
    пишет «нет модели».
    """

    def __init__(self, message: str, hint: str | None = None, line: int | None = None,
                 command: str | None = None, param: str | None = None,
                 minv: float | None = None, maxv: float | None = None,
                 value: float | str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.line = line
        self.command = command
        self.param = param
        self.minv = minv
        self.maxv = maxv
        self.value = value

    def with_param(self, param: str, minv: float | None = None,
                   maxv: float | None = None,
                   value: float | str | None = None) -> "FormaError":
        """Дополняет ошибку сведениями о параметре, не теряя сообщение."""
        if self.param is None:
            self.param = param
            self.minv = minv
            self.maxv = maxv
            self.value = value
        return self

    def bounds_text(self) -> str:
        """«12…40» — человеческие рамки параметра, если они известны."""
        lo, hi = self.minv, self.maxv
        if lo is None and hi is None:
            return ""
        if lo is None:
            return f"до {hi:g}"
        if hi is None:
            return f"от {lo:g}"
        return f"{lo:g}…{hi:g}"

    def to_dict(self) -> dict:
        data = {"message": self.message}
        if self.hint:
            data["hint"] = self.hint
        if self.line is not None:
            data["line"] = self.line
        if self.command:
            data["command"] = self.command
        if self.param:
            data["param"] = self.param
        bounds = self.bounds_text()
        if bounds:
            data["bounds"] = bounds
        if self.minv is not None:
            data["min"] = self.minv
        if self.maxv is not None:
            data["max"] = self.maxv
        if self.value is not None:
            data["value"] = self.value
        return data


class DslError(FormaError):
    """Ошибка в тексте сценария."""


class GeometryError(FormaError):
    """Ошибка геометрических построений."""
