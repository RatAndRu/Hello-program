#!/usr/bin/env python3
"""Собирает ZIP только с файлами, изменёнными между двумя Git-ревизиями.

Это источниковый/ресурсный пакет, а не бинарный патч однофайлового EXE.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
README_NAME = "UPDATE_README_RU.txt"
MANIFEST_NAME = "UPDATE_MANIFEST.json"


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=repo)


def _paths(repo: Path, base: str, head: str, selector: str) -> list[str]:
    data = _git(repo, "diff", "--no-renames", "--name-only", "-z",
                f"--diff-filter={selector}", base, head, "--")
    return sorted(p.decode("utf-8") for p in data.split(b"\0") if p)


def build_update_zip(repo: Path, base: str, head: str, output: Path) -> dict:
    repo = repo.resolve()
    base_sha = _git(repo, "rev-parse", base).decode().strip()
    head_sha = _git(repo, "rev-parse", head).decode().strip()
    files = _paths(repo, base_sha, head_sha, "ACMR")
    deleted = _paths(repo, base_sha, head_sha, "D")
    manifest = {
        "schema": 1,
        "kind": "source_and_resources_delta",
        "base": base,
        "head": head,
        "base_commit": base_sha,
        "head_commit": head_sha,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "deleted": deleted,
        "executable_patch": False,
    }
    readme = f"""FORMA 3D — ПАКЕТ ИЗМЕНЁННЫХ ФАЙЛОВ

База: {base} ({base_sha})
Результат: {head} ({head_sha})
Изменено/добавлено файлов: {len(files)}
Удалено файлов: {len(deleted)}

В архиве лежат только новые версии изменённых файлов с путями от корня
репозитория. UPDATE_MANIFEST.json содержит точный список файлов и удалений.
Для обновления исходников распакуйте архив в корень репозитория с заменой;
файлы из списка deleted нужно удалить. Каталог .git в архив не входит.

ВАЖНО: это НЕ самостоятельная программа и НЕ бинарный патч Forma3D.exe.
Если изменился Python-код, для готовой Windows-версии нужен новый EXE или
полный установочный ZIP. Изменённые .forma, GLB и документацию можно
использовать отдельно без распаковки всего приложения.
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            # Берём содержимое именно из head, а не из возможно изменённого
            # рабочего дерева: пакет воспроизводит выбранную Git-ревизию.
            zf.writestr(rel, _git(repo, "show", f"{head_sha}:{rel}"))
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        zf.writestr(README_NAME, readme)
    return {
        "output": str(output),
        "bytes": output.stat().st_size,
        "files": len(files),
        "deleted": len(deleted),
        "base": base,
        "head": head,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="прежний commit/tag")
    parser.add_argument("--head", default="HEAD", help="новый commit/tag (HEAD)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_update_zip(ROOT, args.base, args.head, args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
