"""Check Tasker release overlays against a small, real upstream Git checkout."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare import prepare
from source import load_lock


class TaskerPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(os.environ.get("TMPDIR", Path.home() / "tmp"))
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="mdtermaddon-tasker-", dir=temporary_root)
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name)
        self.script = self.source / "app/build.gradle"
        self.manifest = self.source / "app/src/main/AndroidManifest.xml"
        self.manifest.parent.mkdir(parents=True)
        self.original_script = '''android {
    namespace "com.termux.tasker"
    defaultConfig {
        applicationId "com.termux.tasker"
        manifestPlaceholders.TERMUX_PACKAGE_NAME = "com.termux"
    }
}
dependencies {
    implementation "com.termux.termux-app:termux-shared:7bceab88e2"
}
'''
        self.script.write_text(self.original_script, encoding="utf-8")
        self.original_manifest = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.termux.tasker" android:sharedUserId="${TERMUX_PACKAGE_NAME}">
    <application/>
</manifest>'''
        self.manifest.write_text(self.original_manifest, encoding="utf-8")
        self.git("init")
        self.lock = load_lock()
        self.commit()

    def git(self, *arguments):
        return subprocess.check_output([
            "git", "-c", "user.name=Tasker Test", "-c", "user.email=tasker@example.invalid",
            "-C", str(self.source), *arguments,
        ], text=True, stderr=subprocess.STDOUT).strip()

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-m", "Tasker fixture")
        self.lock["addons"]["tasker"]["commit"] = self.git("rev-parse", "HEAD")

    def prepare(self):
        with patch("prepare.load_lock", return_value=self.lock), contextlib.redirect_stdout(io.StringIO()):
            prepare("tasker", self.source)

    def test_tasker_overlay_is_repeatable_and_pins_the_full_shared_dependency(self):
        self.prepare()
        first = self.script.read_text(encoding="utf-8")
        expected_commit = self.lock["addons"]["tasker"]["termux_shared_commit"]
        self.assertIn(f'implementation "com.termux.termux-app:termux-shared:{expected_commit}"', first)
        self.assertIn("ext.mdtermAddonApplicationId = 'com.termux.tasker'", first)
        self.assertIn("ext.mdtermAddonNamespace = 'com.termux.tasker'", first)
        self.assertIn("ext.mdtermAddonFlavor = ''", first)
        self.assertEqual(first.count("// BEGIN MDTermaddon signing overlay"), 1)
        self.prepare()
        self.assertEqual(self.script.read_text(encoding="utf-8"), first)
        self.assertEqual(self.manifest.read_text(encoding="utf-8"), self.original_manifest)

    def test_reject_incompatible_upstream_manifest_before_modifying_build(self):
        self.manifest.write_text(
            self.original_manifest.replace("${TERMUX_PACKAGE_NAME}", "com.other"), encoding="utf-8")
        self.commit()
        with self.assertRaisesRegex(ValueError, "sharedUserId must resolve to com.termux"):
            self.prepare()
        self.assertEqual(self.script.read_text(encoding="utf-8"), self.original_script)

    def test_reject_local_manifest_edits_before_modifying_build(self):
        self.manifest.write_text(self.original_manifest + "\n<!-- local edit -->", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "manifest has local modifications"):
            self.prepare()
        self.assertEqual(self.script.read_text(encoding="utf-8"), self.original_script)

    def test_reject_build_edits_and_preserve_them(self):
        edited = self.original_script + "\n// local build edit\n"
        self.script.write_text(edited, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unexpected local changes"):
            self.prepare()
        self.assertEqual(self.script.read_text(encoding="utf-8"), edited)

    def test_reject_upstream_dependency_drift_before_modifying_build(self):
        edited = self.original_script.replace("termux-shared:7bceab88e2", "termux-shared:unexpected")
        self.script.write_text(edited, encoding="utf-8")
        self.commit()
        with self.assertRaisesRegex(ValueError, "pinned termux-shared dependency"):
            self.prepare()
        self.assertEqual(self.script.read_text(encoding="utf-8"), edited)


if __name__ == "__main__":
    unittest.main()
