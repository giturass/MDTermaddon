"""Verify that both companion formats contain the loader paired with the release key."""

import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from x11 import ar_members, prepare_loader_checks, signature_hash, tar_members, verify_companion


class LoaderChecksTests(unittest.TestCase):
    original = """assert targetInfo != null : BuildConfig.packageNotInstalledErrorText;
assert targetInfo.signatures.length == 1 && BuildConfig.SIGNATURE == targetInfo.signatures[0].hashCode() : BuildConfig.packageSignatureMismatchErrorText;"""

    def test_release_checks_do_not_depend_on_java_assertions(self):
        prepared = prepare_loader_checks(self.original)
        self.assertNotIn("assert ", prepared)
        self.assertIn("if (targetInfo == null) throw new AssertionError(BuildConfig.packageNotInstalledErrorText);", prepared)
        self.assertIn("if (targetInfo.signatures == null || targetInfo.signatures.length != 1 || "
                      "BuildConfig.SIGNATURE != targetInfo.signatures[0].hashCode())", prepared)
        self.assertIn("throw new AssertionError(BuildConfig.packageSignatureMismatchErrorText);", prepared)

    def test_changed_upstream_checks_are_rejected(self):
        for changed in (self.original.replace("targetInfo != null", "true"),
                        self.original.replace("BuildConfig.SIGNATURE", "123"),
                        self.original + self.original):
            with self.subTest(source=changed), self.assertRaisesRegex(ValueError, "upstream"):
                prepare_loader_checks(changed)


def make_tar(files, compression="xz"):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:" + compression) as archive:
        directory = tarfile.TarInfo(".")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        for name, (data, mode) in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mode = mode
            archive.addfile(entry, io.BytesIO(data))
    return output.getvalue()


def make_ar(members):
    output = b"!<arch>\n"
    for name, data in members.items():
        output += f"{name:<16}{0:<12}{1000:<6}{1000:<6}{'100644':<8}{len(data):<10}`\n".encode()
        output += data + (b"\n" if len(data) % 2 else b"")
    return output


class CompanionTests(unittest.TestCase):
    def setUp(self):
        temporary_root = Path(os.environ.get("TMPDIR", Path.home() / "tmp"))
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="mdtermaddon-x11-test-", dir=temporary_root)
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name)
        self.build = self.source / "shell-loader/build"
        self.loader = self.build / "outputs/apk/release/shell-loader-release.apk"
        self.loader.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.loader, "w") as archive:
            archive.writestr("classes.dex", b"test loader bytecode")
        self.cert = bytes([0, 127, 128, 255])
        self.config = self.build / "generated/source/buildConfig/release/com/termux/x11/shell_loader/BuildConfig.java"
        self.config.parent.mkdir(parents=True)
        # Independently calculated Java byte-array hash: (((31 + 0)*31 + 127)*31 - 128)*31 - 1.
        self.config.write_text("public static final int SIGNATURE = 1041599;\n", encoding="utf-8")
        scripts = self.source / "shell-loader/scripts"
        scripts.mkdir(parents=True)
        self.payload = {"data/data/com.termux/files/usr/libexec/termux-x11/loader.apk":
                        (self.loader.read_bytes(), 0o644)}
        for name in ("termux-x11", "termux-x11-preference"):
            script = b"#!/data/data/@EMBEDDED_APPLICATION_ID@/files/usr/bin/bash\necho @APPLICATION_ID@\n"
            (scripts / (name + ".in")).write_bytes(script)
            self.payload[f"data/data/com.termux/files/usr/bin/{name}"] = (
                b"#!/data/data/com.termux/files/usr/bin/bash\necho com.termux.x11\n", 0o755)
        self.output = self.build / "outputs/companion"
        self.output.mkdir(parents=True)
        self.deb = self.output / "termux-x11-nightly-1.03.01-0-all.deb"
        self.pacman = self.output / "termux-x11-nightly-1.03.01-0-any.pkg.tar.xz"
        self.package()

    def package(self, deb_payload=None, pacman_payload=None):
        control = {
            "control": (b"Package: termux-x11-nightly\nArchitecture: all\nVersion: 1.03.01-0\nDepends: xkeyboard-config\n", 0o644),
            "postinst": (b"#!/bin/sh\n", 0o755),
        }
        self.deb.write_bytes(make_ar({"debian-binary": b"2.0\n", "control.tar.gz": make_tar(control, "gz"),
                                     "data.tar.xz": make_tar(self.payload if deb_payload is None else deb_payload)}))
        pacman = dict(self.payload if pacman_payload is None else pacman_payload)
        pacman.update({
            ".PKGINFO": (b"pkgname = termux-x11-nightly\npkgver = 1.03.01-0\narch = any\ndepend = xkeyboard-config\n", 0o644),
            ".BUILDINFO": (b"format = 2\n", 0o644),
            ".INSTALL": (b"post_install() { :; }\n", 0o644),
            ".MTREE": (b"test metadata", 0o644),
        })
        self.pacman.write_bytes(make_tar(pacman))

    def verify(self):
        return verify_companion(self.source, "1.03.01", self.cert)

    def test_paired_release_loader_is_accepted_in_both_formats(self):
        self.assertEqual(self.verify(), [self.deb, self.pacman])

    def test_certificate_hash_matches_signed_java_bytes(self):
        self.assertEqual(signature_hash(self.cert), 1041599)
        self.assertEqual(signature_hash(b""), 1)
        self.assertEqual(signature_hash(b"\xff"), 30)
        self.assertEqual(signature_hash(b"abcdef"), -536882268)

    def test_wrong_signing_certificate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_companion(self.source, "1.03.01", b"other certificate")

    def test_missing_generated_signature_is_rejected(self):
        self.config.write_text("public static final boolean DEBUG = false;\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "signature"):
            self.verify()

    def test_mismatched_loader_is_rejected_in_each_format(self):
        wrong = dict(self.payload)
        wrong["data/data/com.termux/files/usr/libexec/termux-x11/loader.apk"] = (b"official debug loader", 0o644)
        for argument in ("deb_payload", "pacman_payload"):
            with self.subTest(format=argument):
                self.package(**{argument: wrong})
                with self.assertRaisesRegex(ValueError, "payload mismatch.*loader.apk"):
                    self.verify()

    def test_wrong_wrapper_identity_and_permissions_are_rejected(self):
        name = "data/data/com.termux/files/usr/bin/termux-x11"
        for value in ((b"wrong package ID", 0o755), (self.payload[name][0], 0o644)):
            with self.subTest(payload=value):
                wrong = dict(self.payload)
                wrong[name] = value
                self.package(deb_payload=wrong)
                with self.assertRaisesRegex(ValueError, "payload mismatch"):
                    self.verify()

    def test_missing_or_extra_packages_are_rejected(self):
        self.deb.unlink()
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.verify()
        self.package()
        (self.output / "stale.deb").write_bytes(b"stale")
        with self.assertRaisesRegex(ValueError, "exactly"):
            self.verify()

    def test_debug_loader_output_is_rejected(self):
        debug = self.build / "outputs/apk/debug/shell-loader-debug.apk"
        debug.parent.mkdir(parents=True)
        debug.write_bytes(b"debug")
        with self.assertRaisesRegex(ValueError, "only.*release"):
            self.verify()

    def test_missing_loader_is_rejected(self):
        self.loader.unlink()
        with self.assertRaisesRegex(ValueError, "release shell loader"):
            self.verify()

    def test_extra_payload_is_rejected(self):
        wrong = dict(self.payload)
        wrong["data/data/com.termux/files/usr/bin/extra"] = (b"extra", 0o755)
        self.package(pacman_payload=wrong)
        with self.assertRaisesRegex(ValueError, "payload files"):
            self.verify()

    def test_invalid_ar_and_tar_paths_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Debian archive"):
            ar_members(b"not an archive")
        with self.assertRaisesRegex(ValueError, "archive path"):
            tar_members(make_tar({"../escape": (b"bad", 0o644)}))


if __name__ == "__main__":
    unittest.main()
