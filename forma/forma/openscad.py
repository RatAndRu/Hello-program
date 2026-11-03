"""Headless-адаптер настоящего OpenSCAD для SCAD и BOSL2.

Forma не интерпретирует чужой язык: subprocess только считает mesh, который
проверяется штатным mesh loader. Пользователь остаётся в Forma; GUI OpenSCAD
не запускается. Пути библиотек передаются явно через OPENSCADPATH.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .errors import GeometryError
from .ops_io import load_any

_LINE_RE = re.compile(r"(?:line|строка)\s+(\d+)", re.IGNORECASE)
_COL_RE = re.compile(r"(?:column|колонка)\s+(\d+)", re.IGNORECASE)


def find_openscad(executable: str | os.PathLike | None = None) -> str | None:
    """Возвращает путь к бинарнику, не запуская его и не открывая GUI."""
    candidate = str(executable or os.environ.get("FORMA_OPENSCAD") or
                    os.environ.get("OPENSCAD") or "").strip()
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path.resolve())
        return shutil.which(candidate) or candidate
    for name in ("openscad", "openscad-nightly", "OpenSCAD"):
        found = shutil.which(name)
        if found:
            return found
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if root:
                candidate_path = Path(root) / "OpenSCAD" / "openscad.exe"
                if candidate_path.is_file():
                    return str(candidate_path)
    return None


def _literal(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return format(float(value), ".15g")
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_literal(item) for item in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


def _error_dict(stderr: str, stdout: str = "", returncode: int | None = None) -> dict:
    text = "\n".join(part for part in (stderr, stdout) if part).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    message = next((line for line in lines if "error" in line.lower() or "ошиб" in line.lower()),
                   lines[-1] if lines else f"OpenSCAD завершился с кодом {returncode}")
    line_match = _LINE_RE.search(text)
    col_match = _COL_RE.search(text)
    hint = "Проверьте SCAD-код и версию OpenSCAD; подробный stderr сохранён в отчёте."
    if "bosl2" in text.lower() or "include" in text.lower():
        hint = "Проверьте OPENSCADPATH и pinned-каталог BOSL2; Forma не подменяет библиотеку своим parser."
    return {"message": message, "hint": hint,
            "line": int(line_match.group(1)) if line_match else 0,
            "column": int(col_match.group(1)) if col_match else 0,
            "returncode": returncode, "stderr": stderr[-16000:], "stdout": stdout[-16000:]}


@dataclass
class OpenSCADResult:
    ok: bool
    mesh_path: str = ""
    vertices: np.ndarray | None = None
    faces: np.ndarray | None = None
    stdout: str = ""
    stderr: str = ""
    command: list[str] = field(default_factory=list)
    returncode: int | None = None
    duration_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    error: dict | None = None
    source: str = ""
    output_format: str = "stl"

    def payload(self) -> dict:
        return {"ok": self.ok, "mesh_path": self.mesh_path, "stdout": self.stdout[-4000:],
                "stderr": self.stderr[-8000:], "command": list(self.command),
                "returncode": self.returncode, "duration_ms": round(self.duration_ms, 2),
                "warnings": list(self.warnings), "error": self.error,
                "source": self.source, "output_format": self.output_format,
                "vertices": 0 if self.vertices is None else int(len(self.vertices)),
                "faces": 0 if self.faces is None else int(len(self.faces))}


class OpenSCADRunner:
    def __init__(self, executable: str | os.PathLike | None = None,
                 library_paths: list[str | os.PathLike] | None = None,
                 timeout: float = 120.0, work_dir: str | os.PathLike | None = None):
        self.executable = find_openscad(executable)
        if isinstance(library_paths, (str, os.PathLike)):
            library_paths = [item for item in str(library_paths).split(";") if item.strip()]
        self.library_paths = [str(Path(path).expanduser().resolve()) for path in (library_paths or [])]
        self.timeout = max(0.1, float(timeout))
        if not math.isfinite(self.timeout):
            raise ValueError("OpenSCAD timeout должен быть конечным числом.")
        self.work_dir = Path(work_dir).expanduser().resolve() if work_dir else None

    def available(self) -> bool:
        return bool(self.executable and (Path(self.executable).is_file() or shutil.which(self.executable)))

    def info(self) -> dict:
        return {"found": self.available(), "executable": self.executable,
                "library_paths": list(self.library_paths), "headless": True,
                "note": "OpenSCAD исполняет SCAD/BOSL2; Forma получает mesh и stderr."}

    def run(self, source: str | os.PathLike, *, output_format: str = "stl",
            defines: dict | None = None, libraries: list[str | os.PathLike] | None = None,
            work_dir: str | os.PathLike | None = None) -> OpenSCADResult:
        started = time.perf_counter()
        fmt = str(output_format or "stl").lower().lstrip(".")
        if fmt not in {"stl", "3mf", "off", "obj"}:
            return OpenSCADResult(False, error={"message": f"OpenSCAD mesh format «{fmt}» не поддерживается адаптером."})
        if not self.executable:
            return OpenSCADResult(False, error={
                "message": "OpenSCAD не найден.",
                "hint": "Установите OpenSCAD или задайте FORMA_OPENSCAD; Forma не открывает внешнее GUI.",
                "line": 0})
        directory = Path(work_dir).expanduser().resolve() if work_dir else self.work_dir
        if directory is None:
            directory = Path(tempfile.mkdtemp(prefix="forma-openscad-"))
        directory.mkdir(parents=True, exist_ok=True)
        source_path = Path(source).expanduser() if isinstance(source, os.PathLike) else None
        if source_path is None and isinstance(source, str):
            possible = Path(source).expanduser()
            try:
                is_file = "\n" not in source and "\r" not in source and possible.is_file()
            except OSError:
                # Длинный inline SCAD — не имя файла; не даём ОС прервать адаптер.
                is_file = False
            if is_file:
                source_path = possible
        if source_path is not None:
            if not source_path.is_file():
                return OpenSCADResult(False, error={"message": f"SCAD-файл не найден: {source_path}"})
            source_path = source_path.resolve()
            source_text = ""
        else:
            source_text = str(source)
            source_path = directory / "forma_input.scad"
            source_path.write_text(source_text, encoding="utf-8")
        output = directory / f"forma_output.{fmt}"
        output.unlink(missing_ok=True)
        paths = list(self.library_paths)
        for item in libraries or []:
            resolved = str(Path(item).expanduser().resolve())
            if resolved not in paths:
                paths.append(resolved)
        env = os.environ.copy()
        # Не наследуем случайные библиотеки молча: явные pinned-пути идут первыми.
        inherited = env.get("OPENSCADPATH", "")
        env["OPENSCADPATH"] = os.pathsep.join(paths + ([inherited] if inherited else []))
        # CLI export не должен пытаться создать Qt window на headless Linux.
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        command = [str(self.executable), "-o", str(output)]
        for key, value in sorted((defines or {}).items()):
            command += ["-D", f"{key}={_literal(value)}"]
        command.append(str(source_path))
        try:
            completed = subprocess.run(
                command, cwd=str(directory), env=env, shell=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=self.timeout, check=False,
                creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            code = int(completed.returncode)
        except subprocess.TimeoutExpired as exc:
            return OpenSCADResult(False, stdout=str(exc.stdout or ""), stderr=str(exc.stderr or ""),
                                  command=command, duration_ms=(time.perf_counter() - started) * 1000,
                                  error={"message": f"OpenSCAD превысил timeout {self.timeout:g} с.",
                                         "hint": "Упростите SCAD или увеличьте timeout явно; процесс не оставляем в фоне.",
                                         "line": 0})
        except OSError as exc:
            return OpenSCADResult(False, command=command,
                                  duration_ms=(time.perf_counter() - started) * 1000,
                                  error={"message": f"Не удалось запустить OpenSCAD: {exc}", "line": 0})
        duration = (time.perf_counter() - started) * 1000
        warnings = [line.strip() for line in stderr.splitlines() if "warning" in line.lower()]
        if code != 0:
            return OpenSCADResult(False, stdout=stdout, stderr=stderr, command=command,
                                  returncode=code, duration_ms=duration, warnings=warnings,
                                  error=_error_dict(stderr, stdout, code), source=str(source_path),
                                  output_format=fmt)
        if not output.is_file() or output.stat().st_size == 0:
            return OpenSCADResult(False, stdout=stdout, stderr=stderr, command=command,
                                  returncode=code, duration_ms=duration, warnings=warnings,
                                  error={"message": "OpenSCAD завершился без непустого mesh-файла.",
                                         "hint": "Проверьте, что сценарий создаёт твёрдое тело, а не только echo/2D-контур.",
                                         "line": 0}, source=str(source_path), output_format=fmt)
        try:
            vertices, faces = load_any(output, scale=1.0, repair=False)
            vertices = np.asarray(vertices, dtype=np.float64)
            faces = np.asarray(faces, dtype=np.int64)
            if vertices.ndim != 2 or vertices.shape[1] != 3 or not len(vertices) or not len(faces):
                raise GeometryError("пустая или некорректная сетка")
            if not np.isfinite(vertices).all():
                raise GeometryError("сетка содержит NaN/Inf")
        except Exception as exc:
            return OpenSCADResult(False, stdout=stdout, stderr=stderr, command=command,
                                  returncode=code, duration_ms=duration, warnings=warnings,
                                  error={"message": f"OpenSCAD mesh не прошёл проверку: {exc}",
                                         "hint": "Результат не добавлен в сцену; исправьте геометрию в SCAD.",
                                         "line": 0}, source=str(source_path), output_format=fmt)
        return OpenSCADResult(True, mesh_path=str(output), vertices=vertices, faces=faces,
                              stdout=stdout, stderr=stderr, command=command, returncode=code,
                              duration_ms=duration, warnings=warnings, source=str(source_path),
                              output_format=fmt)

    def run_or_raise(self, *args, **kwargs) -> OpenSCADResult:
        result = self.run(*args, **kwargs)
        if not result.ok:
            error = result.error or {}
            raise GeometryError(error.get("message", "OpenSCAD не построил модель."),
                                hint=error.get("hint"), line=error.get("line") or None)
        return result


def run_scad(source, **kwargs) -> OpenSCADResult:
    """Короткий функциональный вход для API и скриптов."""
    runner_keys = {"executable", "library_paths", "timeout", "work_dir"}
    runner_args = {key: kwargs.pop(key) for key in list(kwargs) if key in runner_keys}
    return OpenSCADRunner(**runner_args).run(source, **kwargs)
