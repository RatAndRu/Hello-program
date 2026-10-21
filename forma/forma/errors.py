"""Ошибки, которые понятны человеку и нейросети."""

from __future__ import annotations


class FormaError(Exception):
    """Базовая ошибка с подсказкой и номером строки."""

    def __init__(self, message: str, hint: str | None = None, line: int | None = None,
                 command: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.line = line
        self.command = command

    def to_dict(self) -> dict:
        data = {"message": self.message}
        if self.hint:
            data["hint"] = self.hint
        if self.line is not None:
            data["line"] = self.line
        if self.command:
            data["command"] = self.command
        return data


class DslError(FormaError):
    """Ошибка в тексте сценария."""


class GeometryError(FormaError):
    """Ошибка геометрических построений."""
