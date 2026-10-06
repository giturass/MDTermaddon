"""Reject incompatible APKs and accidental signing fallbacks without Android tools."""

import base64
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from signing import key_bytes
from source import load_lock
from verify_apk import validate_certificate, validate_manifest


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.lock = load_lock()
        self.addon = self.lock["addons"]["api"]
        self.xml = '''<manifest xmlns:android="http://schemas.android.com/apk/res/android"
            package="com.termux.api" android:sharedUserId="com.termux">
            <uses-sdk android:minSdkVersion="24" android:targetSdkVersion="28"/>
            <application android:debuggable="false"/>
        </manifest>'''

    def test_upstream_contract_matches_mdterm(self):
        for name, addon in self.lock["addons"].items():
            with self.subTest(addon=name):
                self.assertEqual(addon["application_id"], "com.termux." + name)
                xml = self.xml.replace("com.termux.api", addon["application_id"])
                xml = xml.replace('minSdkVersion="24"', f'minSdkVersion="{addon["min_sdk"]}"')
                validate_manifest(xml, addon, "com.termux")

    def test_reject_renamed_package(self):
        with self.assertRaisesRegex(ValueError, "package"):
            validate_manifest(self.xml.replace("com.termux.api", "com.mdterm.api"), self.addon, "com.termux")

    def test_reject_missing_shared_uid(self):
        with self.assertRaisesRegex(ValueError, "sharedUserId"):
            validate_manifest(self.xml.replace('android:sharedUserId="com.termux"', ""), self.addon, "com.termux")

    def test_reject_wrong_shared_uid(self):
        with self.assertRaisesRegex(ValueError, "sharedUserId"):
            validate_manifest(self.xml.replace('sharedUserId="com.termux"', 'sharedUserId="com.other"'), self.addon, "com.termux")

    def test_release_must_not_be_debuggable(self):
        with self.assertRaisesRegex(ValueError, "must not be debuggable"):
            validate_manifest(self.xml.replace('debuggable="false"', 'debuggable="true"'), self.addon, "com.termux")
        validate_manifest(self.xml.replace('android:debuggable="false"', ""), self.addon, "com.termux")

    def test_certificate_must_be_exactly_the_selected_key(self):
        expected = "abcdef0123456789" * 4  # A fixture, not an actual signing certificate.
        report = f"Signer #1 certificate SHA-256 digest: {expected.upper()}\n"
        validate_certificate(report, expected)
        for invalid in ("", report.replace(expected.upper(), "0" * 64), report + report):
            with self.subTest(report=invalid), self.assertRaisesRegex(ValueError, "signer"):
                validate_certificate(invalid, expected)

    def test_missing_release_key_is_rejected(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "Missing MDTERM_RELEASE"):
            key_bytes()

    def test_release_base64_accepts_line_wrapping(self):
        encoded = base64.b64encode(b"private test fixture").decode()
        with patch.dict(os.environ, {"MDTERM_RELEASE_KEYSTORE_BASE64": encoded[:8] + "\n" + encoded[8:]}):
            self.assertEqual(key_bytes(), b"private test fixture")

    def test_release_base64_rejects_invalid_input(self):
        for value in ("not-base64!", "   "):
            with self.subTest(value=value), patch.dict(os.environ, {"MDTERM_RELEASE_KEYSTORE_BASE64": value}):
                with self.assertRaises(ValueError):
                    key_bytes()

    def test_build_rejects_legacy_mode_argument(self):
        script = Path(__file__).resolve().parents[1] / "scripts/build.sh"
        result = subprocess.run(["bash", str(script), "api", "debug"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Release only", result.stderr)

    def test_build_fails_before_creating_files_when_secrets_are_missing(self):
        script = Path(__file__).resolve().parents[1] / "scripts/build.sh"
        environment = {key: value for key, value in os.environ.items() if not key.startswith("MDTERM_")}
        result = subprocess.run(["bash", str(script), "api"], env=environment, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MDTERM_RELEASE_KEYSTORE_BASE64", result.stderr)


if __name__ == "__main__":
    unittest.main()
