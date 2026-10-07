"""Exercise source releases against real recursive Git submodule checkouts."""

import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_apk import source_archive


class SourceArchiveTests(unittest.TestCase):
    def git(self, repository, *arguments):
        return subprocess.check_output([
            "git", "-c", "protocol.file.allow=always",
            "-c", "user.name=Source Archive Test",
            "-c", "user.email=source-archive@example.invalid",
            "-C", str(repository), *arguments,
        ], text=True, stderr=subprocess.STDOUT).strip()

    def write(self, root, name, content):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def repository(self, name, files):
        repository = self.base / name
        repository.mkdir()
        self.git(repository, "init")
        for path, content in files.items():
            self.write(repository, path, content)
        self.commit(repository)
        return repository

    def commit(self, repository):
        self.git(repository, "add", ".")
        self.git(repository, "commit", "--allow-empty", "-m", "Test fixture")

    def setUp(self):
        temporary_root = Path(os.environ.get("TMPDIR", Path.home() / "tmp"))
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="mdtermaddon-archive-", dir=temporary_root)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        leaf = self.repository("leaf", {"LICENSE": "leaf license", "leaf.c": "leaf source"})
        dependency = self.repository("dependency", {"COPYING": "dependency license", "core.c": "core source"})
        self.git(dependency, "submodule", "add", str(leaf), "nested/leaf")
        self.commit(dependency)
        self.source = self.repository("upstream", {"LICENSE": "root license", "app.txt": "original",
                                                     "debug.keystore": "private key fixture"})
        self.git(self.source, "submodule", "add", str(dependency), "native/dependency")
        self.commit(self.source)
        self.git(self.source, "submodule", "update", "--init", "--recursive")
        self.dependency = self.source / "native/dependency"
        self.leaf = self.dependency / "nested/leaf"
        self.project = self.base / "project"
        for name in ("sources.lock.json", "README.md", ".gitignore", "scripts/build.sh",
                     "gradle/build.gradle", ".github/workflows/build.yml", "tests/test.py"):
            self.write(self.project, name, f"project {name}")
        self.destination = self.base / "source.tar.gz"

    def archive(self):
        with patch("verify_apk.ROOT", self.project):
            source_archive(self.source, self.destination)

    def test_archive_contains_patched_recursive_sources_licenses_and_tooling(self):
        self.write(self.source, "app.txt", "patched application")
        self.write(self.dependency, "core.c", "patched dependency")
        self.write(self.leaf, "leaf.c", "patched leaf")
        for root in (self.source, self.dependency, self.leaf):
            self.write(root, "build/generated.txt", "generated output")
            self.write(root, "release.p12", "private key fixture")
        for name in ("scripts/__pycache__/build.pyc", "scripts/.gradle/cache", "scripts/release.jks",
                     "gradle/local.properties", "tests/.git/config"):
            self.write(self.project, name, "excluded fixture")

        self.archive()

        with tarfile.open(self.destination) as archive:
            names = set(archive.getnames())
            expected = {
                "MDTermaddon/upstream/app.txt": "patched application",
                "MDTermaddon/upstream/LICENSE": "root license",
                "MDTermaddon/upstream/native/dependency/core.c": "patched dependency",
                "MDTermaddon/upstream/native/dependency/COPYING": "dependency license",
                "MDTermaddon/upstream/native/dependency/nested/leaf/leaf.c": "patched leaf",
                "MDTermaddon/upstream/native/dependency/nested/leaf/LICENSE": "leaf license",
                "MDTermaddon/scripts/build.sh": "project scripts/build.sh",
                "MDTermaddon/gradle/build.gradle": "project gradle/build.gradle",
                "MDTermaddon/.github/workflows/build.yml": "project .github/workflows/build.yml",
                "MDTermaddon/tests/test.py": "project tests/test.py",
            }
            for name, content in expected.items():
                with self.subTest(path=name):
                    self.assertEqual(archive.extractfile(name).read().decode(), content)
            self.assertIn("MDTermaddon/upstream/.gitmodules", names)
            self.assertIn("MDTermaddon/upstream/native/dependency/.gitmodules", names)
            for name in names:
                self.assertNotIn(".git", Path(name).parts)
                self.assertNotIn("__pycache__", name)
                self.assertNotIn(".gradle/", name)
                self.assertNotIn("generated.txt", name)
                self.assertNotIn("local.properties", name)
                self.assertNotIn(Path(name).suffix, (".jks", ".p12", ".keystore", ".pyc"))

    def test_reject_uninitialized_submodule(self):
        self.git(self.source, "submodule", "deinit", "-f", "native/dependency")
        with self.assertRaisesRegex(ValueError, "not initialized: native/dependency"):
            self.archive()
        self.assertFalse(self.destination.exists())

    def test_reject_uninitialized_nested_submodule(self):
        self.git(self.dependency, "submodule", "deinit", "-f", "nested/leaf")
        with self.assertRaisesRegex(ValueError, "not initialized: native/dependency/nested/leaf"):
            self.archive()
        self.assertFalse(self.destination.exists())

    def test_reject_submodule_at_wrong_commit(self):
        self.commit(self.dependency)
        with self.assertRaisesRegex(ValueError, "locked commit: native/dependency"):
            self.archive()
        self.assertFalse(self.destination.exists())

    def test_reject_nested_submodule_at_wrong_commit(self):
        self.commit(self.leaf)
        with self.assertRaisesRegex(ValueError, "locked commit: native/dependency/nested/leaf"):
            self.archive()
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
