"""Портативные папки: данные рядом с exe, без %APPDATA% и ~/.forma3d."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forma import paths  # noqa: E402


class _Frozen:
    """Временно притворяется собранным exe в указанной папке."""

    def __init__(self, exe: Path):
        self.exe = exe

    def __enter__(self):
        self._frozen = getattr(sys, "frozen", None)
        self._exe = sys.executable
        sys.frozen = True
        sys.executable = str(self.exe)
        return self

    def __exit__(self, *exc):
        if self._frozen is None:
            try:
                del sys.frozen
            except AttributeError:
                pass
        else:
            sys.frozen = self._frozen
        sys.executable = self._exe


class TestPortableData(unittest.TestCase):
    def test_folders_next_to_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "Forma3D.exe"
            exe.write_bytes(b"MZ")
            old = os.environ.pop("FORMA_DATA", None)
            try:
                with _Frozen(exe):
                    self.assertEqual(paths.app_dir(), Path(tmp).resolve())
                    root = paths.user_data_dir()
                    self.assertEqual(root, Path(tmp).resolve())
                    for name in paths.SUBDIRS:
                        self.assertTrue((root / name).is_dir(), name)
                    self.assertNotIn("AppData", str(root))
                    self.assertNotIn(".forma3d", str(root))
            finally:
                if old is not None:
                    os.environ["FORMA_DATA"] = old

    def test_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("FORMA_DATA")
            os.environ["FORMA_DATA"] = tmp
            try:
                self.assertEqual(paths.user_data_dir(), Path(tmp).resolve())
                self.assertTrue((Path(tmp) / "projects").is_dir())
            finally:
                if old is None:
                    os.environ.pop("FORMA_DATA", None)
                else:
                    os.environ["FORMA_DATA"] = old

    def test_source_tree_uses_forma_data(self):
        # при запуске из исходников данные не должны уходить в домашнюю папку
        old = os.environ.pop("FORMA_DATA", None)
        try:
            root = paths.data_root()
            self.assertEqual(root, ROOT / "forma-data")
        finally:
            if old is not None:
                os.environ["FORMA_DATA"] = old

    def test_migrate_legacy_moves_and_cleans(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "новое"
            old_legacy = Path(tmp) / "Forma3D"
            (old_legacy / "projects").mkdir(parents=True)
            (old_legacy / "textures").mkdir()
            (old_legacy / "projects" / "кружка.forma").write_text("к = box", encoding="utf-8")
            (old_legacy / "textures" / "x.png").write_bytes(b"PNG")
            old = os.environ.pop("FORMA_DATA", None)
            try:
                report = paths.migrate_legacy(root=target, legacy=[old_legacy])
            finally:
                if old is not None:
                    os.environ["FORMA_DATA"] = old
            self.assertEqual(report["moved"], 2)
            self.assertFalse(old_legacy.exists(), "старая папка должна исчезнуть")
            self.assertTrue((target / "projects" / "кружка.forma").exists())
            self.assertTrue((target / "textures" / "x.png").exists())

    def test_migrate_keeps_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "новое"
            (target / "projects").mkdir(parents=True)
            (target / "projects" / "a.forma").write_text("новое", encoding="utf-8")
            legacy = Path(tmp) / "Forma3D"
            (legacy / "projects").mkdir(parents=True)
            (legacy / "projects" / "a.forma").write_text("старое", encoding="utf-8")
            old = os.environ.pop("FORMA_DATA", None)
            try:
                report = paths.migrate_legacy(root=target, legacy=[legacy])
            finally:
                if old is not None:
                    os.environ["FORMA_DATA"] = old
            self.assertTrue(report["left"], "конфликтующие файлы не должны теряться")
            self.assertTrue((legacy / "projects" / "a.forma").exists())
            self.assertEqual((target / "projects" / "a.forma").read_text(encoding="utf-8"),
                             "новое")

    def test_downloads_prefers_real_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("FORMA_DOWNLOADS")
            os.environ["FORMA_DOWNLOADS"] = tmp
            try:
                self.assertEqual(paths.downloads_dir(), Path(tmp))
            finally:
                if old is None:
                    os.environ.pop("FORMA_DOWNLOADS", None)
                else:
                    os.environ["FORMA_DOWNLOADS"] = old


if __name__ == "__main__":
    unittest.main(verbosity=2)
