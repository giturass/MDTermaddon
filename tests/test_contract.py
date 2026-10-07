"""Reject incompatible APKs and accidental signing fallbacks without Android tools."""

import base64
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from signing import key_bytes
from source import load_lock
from verify_apk import find_apk, validate_certificate, validate_manifest, validate_native_libraries


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
                if addon.get("flavor") == "sharedUid":
                    xml = xml.replace("<application ", '<application android:process="com.termux" ')
                validate_manifest(xml, addon, "com.termux")

    def x11_manifest(self):
        return self.xml.replace("com.termux.api", "com.termux.x11").replace(
            '<application android:debuggable="false"/>',
            '<application android:debuggable="false" android:process="com.termux">'
            '<activity android:name=".MainActivity"/>'
            '<service android:name=".ServerService" android:process="com.termux"/>'
            '</application>')

    def test_x11_shared_uid_process_can_be_inherited_or_explicit(self):
        validate_manifest(self.x11_manifest(), self.lock["addons"]["x11"], "com.termux")

    def test_x11_rejects_standalone_identity_and_sdk(self):
        xml = self.x11_manifest()
        for invalid, message in (
            (xml.replace('android:sharedUserId="com.termux"', ""), "sharedUserId"),
            (xml.replace('targetSdkVersion="28"', 'targetSdkVersion="34"'), "target SDK"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_manifest(invalid, self.lock["addons"]["x11"], "com.termux")

    def test_x11_rejects_missing_or_isolated_application_process(self):
        for process in ("", 'android:process=":x11"', 'android:process="com.termux.x11"'):
            xml = self.x11_manifest().replace('android:process="com.termux"', process, 1)
            with self.subTest(process=process), self.assertRaisesRegex(ValueError, "application.*com.termux"):
                validate_manifest(xml, self.lock["addons"]["x11"], "com.termux")

    def test_x11_rejects_components_outside_shared_process(self):
        for component in ("activity", "activity-alias", "service", "receiver", "provider"):
            xml = self.x11_manifest().replace(
                "</application>",
                f'<{component} android:name=".Isolated" android:process=":isolated"/></application>')
            with self.subTest(component=component), self.assertRaisesRegex(ValueError, "components.*com.termux"):
                validate_manifest(xml, self.lock["addons"]["x11"], "com.termux")

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


class NativeLibraryTests(unittest.TestCase):
    def setUp(self):
        self.lock = load_lock()
        self.addon = self.lock["addons"]["x11"]
        self.libraries = [f"lib/{abi}/libXlorie.so" for abi in self.addon["native_abis"]]

    def test_x11_accepts_all_four_native_abis(self):
        validate_native_libraries(["classes.dex", *self.libraries], self.addon)

    def test_x11_rejects_missing_or_extra_abis(self):
        for libraries in ([], self.libraries[:-1], self.libraries + ["lib/mips/libXlorie.so"]):
            with self.subTest(libraries=libraries), self.assertRaisesRegex(ValueError, "native ABIs"):
                validate_native_libraries(libraries, self.addon)

    def test_x11_requires_its_native_library_for_each_abi(self):
        for index, library in enumerate(self.libraries):
            libraries = self.libraries.copy()
            libraries[index] = library.replace("libXlorie.so", "libunrelated.so")
            with self.subTest(library=library), self.assertRaisesRegex(ValueError, "Missing X11 native library"):
                validate_native_libraries(libraries, self.addon)

    def test_x11_rejects_malformed_native_library_paths(self):
        with self.assertRaisesRegex(ValueError, "native library path"):
            validate_native_libraries(self.libraries + ["lib/arm64-v8a/nested/libXlorie.so"], self.addon)

    def test_other_addons_continue_to_reject_native_libraries(self):
        for name in ("api", "boot", "styling", "tasker"):
            with self.subTest(addon=name):
                addon = self.lock["addons"][name]
                validate_native_libraries(["classes.dex"], addon)
                with self.assertRaisesRegex(ValueError, "Unexpected native library"):
                    validate_native_libraries(self.libraries, addon)


class ApkSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(os.environ.get("TMPDIR", Path.home() / "tmp"))
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="mdtermaddon-apk-", dir=temporary_root)
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name)
        self.lock = load_lock()

    def output(self, relative):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"APK fixture")
        return path

    def test_x11_selects_only_shared_uid_release_output(self):
        expected = self.output("lorie-app/build/outputs/apk/sharedUid/release/lorie-app-sharedUid-release.apk")
        for relative in (
            "lorie-app/build/outputs/apk/standalone/release/lorie-app-standalone-release.apk",
            "lorie-app/build/outputs/apk/sharedUid/debug/lorie-app-sharedUid-debug.apk",
            "app/build/outputs/apk/release/app-release.apk",
        ):
            self.output(relative)
        self.assertEqual(find_apk(self.source, self.lock["addons"]["x11"]), expected)

    def test_x11_rejects_only_standalone_or_debug_outputs(self):
        for relative in (
            "lorie-app/build/outputs/apk/standalone/release/lorie-app-standalone-release.apk",
            "lorie-app/build/outputs/apk/sharedUid/debug/lorie-app-sharedUid-debug.apk",
        ):
            path = self.output(relative)
            with self.subTest(output=relative), self.assertRaisesRegex(ValueError, "exactly one release APK.*found 0"):
                find_apk(self.source, self.lock["addons"]["x11"])
            path.unlink()

    def test_x11_rejects_ambiguous_shared_uid_release_outputs(self):
        self.output("lorie-app/build/outputs/apk/sharedUid/release/first.apk")
        self.output("lorie-app/build/outputs/apk/sharedUid/release/second.apk")
        with self.assertRaisesRegex(ValueError, "exactly one release APK.*found 2"):
            find_apk(self.source, self.lock["addons"]["x11"])

    def test_tasker_uses_the_standard_app_release_directory(self):
        expected = self.output("app/build/outputs/apk/release/app-release.apk")
        self.output("app/build/outputs/apk/debug/app-debug.apk")
        self.assertEqual(find_apk(self.source, self.lock["addons"]["tasker"]), expected)


if __name__ == "__main__":
    unittest.main()
