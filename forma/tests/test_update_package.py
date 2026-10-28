"""ZIP обновления содержит только дельту исходников и явный список удалений."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from tools.build_update_zip import (MANIFEST_NAME, README_NAME,
                                    build_update_zip)


class UpdatePackageTest(unittest.TestCase):
    def test_only_changed_files_and_deletions_are_packaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            output = repo.parent / f"{repo.name}-update.zip"

            def git(*args: str) -> str:
                return subprocess.check_output(["git", *args], cwd=repo,
                                               text=True).strip()

            git("init", "--quiet")
            git("config", "user.email", "forma-test@example.invalid")
            git("config", "user.name", "Forma Test")
            (repo / "keep.txt").write_text("keep", encoding="utf-8")
            (repo / "change.txt").write_text("old", encoding="utf-8")
            (repo / "delete.txt").write_text("delete", encoding="utf-8")
            git("add", ".")
            git("commit", "--quiet", "-m", "base")
            base = git("rev-parse", "HEAD")

            (repo / "change.txt").write_text("new", encoding="utf-8")
            (repo / "delete.txt").unlink()
            (repo / "add.txt").write_text("add", encoding="utf-8")
            git("add", ".")
            git("commit", "--quiet", "-m", "head")
            head = git("rev-parse", "HEAD")
            # Незакоммиченная правка не должна попасть в пакет выбранной ревизии.
            (repo / "change.txt").write_text("dirty", encoding="utf-8")
            try:
                result = build_update_zip(repo, base, head, output)
                self.assertEqual(result["files"], 2)
                self.assertEqual(result["deleted"], 1)
                with zipfile.ZipFile(output) as zf:
                    self.assertEqual(set(zf.namelist()), {
                        "add.txt", "change.txt", MANIFEST_NAME, README_NAME})
                    self.assertEqual(zf.read("change.txt"), b"new")
                    manifest = json.loads(zf.read(MANIFEST_NAME))
                    self.assertEqual(manifest["deleted"], ["delete.txt"])
                    self.assertFalse(manifest["executable_patch"])
            finally:
                output.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
