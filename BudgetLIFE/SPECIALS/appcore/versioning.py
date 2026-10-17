"""Резервные копии данных архивом — фишка LanguageYOI, Cooker и DnD's.

Проекты подходят к бэкапам по-разному: LanguageYOI делает копию базы перед
восстановлением и экспортирует данные в CSV/Anki/ZIP, Cooker умеет экспорт и
импорт JSON, DnD's хранит всё в папке `data/`. Здесь собрано общее:

  * ``create_backup(data_dir)`` — ZIP всей папки данных + ``manifest.json``
    внутри (версия приложения, дата, список файлов) — «бэкап одним файлом»;
  * ``list_backups()`` / ``latest_backup()`` / ``prune_backups()`` — порядок;
  * ``restore_backup()` — распаковка **с проверкой путей** (защита от zip-slip),
    перед этим текущие данные копируются в ``before_restore_*``;
  * ``export_json()`` / ``import_json()`` — «перенести на другой ПК» (Cooker);
  * ``verify_backup()`` — архив читается и не битый (CRC).

Всё работает без внешних зависимостей (``zipfile`` + ``json``) и на любой ОС.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

__all__ = ["BackupInfo", "backups_dir", "create_backup", "list_backups", "latest_backup",
           "prune_backups", "restore_backup", "verify_backup", "export_json",
           "import_json", "data_stats"]

_SKIP_PARTS = {"__pycache__", ".git", "logs"}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".log"}


def backups_dir(data_dir: str | Path, sub: str = "backups") -> Path:
    """Папка для архивов внутри data/ (создаётся)."""
    path = Path(data_dir) / sub
    path.mkdir(parents=True, exist_ok=True)
    return path


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_PARTS for part in path.relative_to(root).parts):
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES or path.name.endswith((".bak", "-wal", "-shm")):
            continue
        yield path


@dataclass
class BackupInfo:
    """Что известно об архиве (без распаковки)."""

    path: Path
    created_at: str
    size: int
    files: int
    app_version: str = ""
    manifest: dict | None = None

    @property
    def name(self) -> str:
        return self.path.name

    def human_size(self) -> str:
        if self.size < 1024:
            return f"{self.size} Б"
        if self.size < 1024 * 1024:
            return f"{self.size / 1024:.0f} КБ"
        return f"{self.size / 1024 / 1024:.1f} МБ"

    def describe(self) -> str:
        return f"{self.created_at} · {self.human_size()} · файлов: {self.files}"


def create_backup(data_dir: str | Path, *, app_name: str = "app", app_version: str = "",
                  stamp: str | None = None, dest: str | Path | None = None,
                  keep: int | None = None, logger=None) -> BackupInfo | None:
    """Собирает ZIP с содержимым ``data_dir``. Возвращает описание архива.

    * ``keep`` — сколько последних архивов оставить (остальные удаляются);
    * ``dest`` — куда положить архив (по умолчанию ``data_dir/backups``);
    * тайм stamp можно задать явно — удобно для тестов.
    """
    root = Path(data_dir)
    if not root.exists():
        return None
    # Папка бэкапов сама в архив не попадает (иначе бэкапы бэкапов).
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    folder = Path(dest) if dest else backups_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{app_name}_{stamp}.zip"

    files = list(_iter_files(root))
    manifest = {
        "app": app_name,
        "version": app_version,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": len(files),
        "total_bytes": sum(p.stat().st_size for p in files),
        "python": f"{__import__('sys').version_info.major}.{__import__('sys').version_info.minor}",
    }
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as arc:
            for path in files:
                arc.write(path, path.relative_to(root).as_posix())
            arc.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    except OSError as exc:
        if logger:
            logger.warning("Не удалось создать бэкап: %s", exc)
        return None

    info = BackupInfo(target, manifest["created_at"], target.stat().st_size,
                      manifest["files"], app_version, manifest)
    if keep:
        prune_backups(folder, keep=keep, logger=logger)
    if logger:
        logger.info("Бэкап данных: %s (%s)", target.name, info.human_size())
    return info


def verify_backup(path: str | Path) -> bool:
    """Проверяет, что архив целый (CRC всех записей) и не пустой."""
    try:
        with zipfile.ZipFile(path) as arc:
            if not arc.namelist():
                return False
            return arc.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def list_backups(folder: str | Path) -> list[BackupInfo]:
    """Все архивы папки, свежие — первыми."""
    path = Path(folder)
    if not path.exists():
        return []
    out: list[BackupInfo] = []
    for file in sorted(path.glob("*.zip")):
        if file.name.startswith("before_restore"):
            continue
        manifest = None
        files = 0
        version = ""
        created = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(file.stat().st_mtime))
        try:
            with zipfile.ZipFile(file) as arc:
                if "manifest.json" in arc.namelist():
                    manifest = json.loads(arc.read("manifest.json").decode("utf-8"))
                    created = manifest.get("created_at", created)
                    files = int(manifest.get("files", 0) or 0)
                    version = str(manifest.get("version", "") or "")
        except (OSError, zipfile.BadZipFile, ValueError):
            pass
        out.append(BackupInfo(file, created, file.stat().st_size, files, version, manifest))
    return sorted(out, key=lambda info: info.created_at, reverse=True)


def latest_backup(folder: str | Path) -> BackupInfo | None:
    items = list_backups(folder)
    return items[0] if items else None


def prune_backups(folder: str | Path, keep: int = 10, *, logger=None) -> int:
    """Оставляет ``keep`` свежих архивов, остальные удаляет. Возвращает счёт."""
    items = list_backups(folder)
    removed = 0
    for info in items[keep:]:
        try:
            info.path.unlink()
            removed += 1
        except OSError:
            pass
    if removed and logger:
        logger.info("Старые бэкапы удалены: %d (оставлено %d)", removed, keep)
    return removed


def _safe_extract(arc: zipfile.ZipFile, target: Path) -> int:
    """Распаковка с защитой от «zip-slip» (путей вида ../../windows)."""
    base = target.resolve()
    extracted = 0
    for member in arc.infolist():
        if member.is_dir():
            continue
        name = member.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            continue                            # подозрительный путь — пропускаем
        if name == "manifest.json":
            continue                            # служебный файл не восстанавливаем
        destination = (base / name).resolve()
        if not str(destination).startswith(str(base)):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with arc.open(member) as source, open(destination, "wb") as out:
            shutil.copyfileobj(source, out)
        extracted += 1
    return extracted


def restore_backup(archive: str | Path, data_dir: str | Path, *, logger=None,
                   stamp: str | None = None) -> dict:
    """Возвращает данные из архива, сохранив текущие как ``before_restore_*``.

    Результат: ``{"ok", "restored", "safety" (путь к страховочной копии),
    "error"}``. Перед восстановлением архив проверяется (CRC).
    """
    archive = Path(archive)
    data = Path(data_dir)
    if not archive.exists():
        return {"ok": False, "restored": 0, "safety": None, "error": "Архив не найден"}
    if not verify_backup(archive):
        return {"ok": False, "restored": 0, "safety": None,
                "error": "Архив повреждён или пуст"}

    safety = None
    if data.exists() and any(data.iterdir()):
        stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
        safety = data.parent / f"before_restore_{data.name}_{stamp}"
        try:
            shutil.copytree(data, safety, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("backups", "__pycache__"))
            if logger:
                logger.warning("Перед восстановлением данные сохранены: %s", safety)
        except OSError as exc:
            if logger:
                logger.error("Не удалось сохранить страховочную копию: %s", exc)
            return {"ok": False, "restored": 0, "safety": None,
                    "error": "Не удалось сохранить страховочную копию"}

    try:
        with zipfile.ZipFile(archive) as arc:
            extracted = _safe_extract(arc, data)
    except (OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "restored": 0, "safety": str(safety) if safety else None,
                "error": f"Ошибка распаковки: {exc}"}
    if logger:
        logger.info("Восстановлено из %s: файлов %d (страховка: %s)",
                    archive.name, extracted, safety or "не требовалась")
    return {"ok": True, "restored": extracted,
            "safety": str(safety) if safety else None, "error": ""}


def export_json(path: str | Path, payload, *, logger=None) -> bool:
    """Экспорт «в один файл» — чтобы перенести данные на другой ПК (Cooker)."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError) as exc:
        if logger:
            logger.warning("Экспорт не удался: %s", exc)
        return False


def import_json(path: str | Path, *, default=None, logger=None):
    """Чтение экспортированного JSON (битый файл — это ``default``, а не падение)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if logger:
            logger.warning("Импорт не удался: %s", exc)
        return default


def data_stats(data_dir: str | Path) -> dict:
    """Сколько файлов и байт лежит в данных (для трея и интерфейса)."""
    root = Path(data_dir)
    if not root.exists():
        return {"files": 0, "bytes": 0, "oldest": "", "newest": ""}
    files = [p for p in root.rglob("*") if p.is_file()]
    if not files:
        return {"files": 0, "bytes": 0, "oldest": "", "newest": ""}
    stamps = [p.stat().st_mtime for p in files]
    return {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "oldest": time.strftime("%Y-%m-%d %H:%M", time.localtime(min(stamps))),
        "newest": time.strftime("%Y-%m-%d %H:%M", time.localtime(max(stamps))),
    }
