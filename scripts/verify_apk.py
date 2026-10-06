#!/usr/bin/env python3
"""Verify the APK's MDTerm contract before publishing any artifacts."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET
import zipfile

from source import ROOT, load_lock

ANDROID = "{http://schemas.android.com/apk/res/android}"


def validate_manifest(xml, addon, shared_user_id):
    manifest = ET.fromstring(xml)
    expected = addon["application_id"]
    if manifest.get("package") != expected:
        raise ValueError(f"APK package must be {expected}")
    if manifest.get(ANDROID + "sharedUserId") != shared_user_id:
        raise ValueError(f"APK sharedUserId must be {shared_user_id}")
    sdk = manifest.find("uses-sdk")
    if sdk is None or sdk.get(ANDROID + "minSdkVersion") != str(addon["min_sdk"]):
        raise ValueError("Unexpected minimum SDK")
    if sdk.get(ANDROID + "targetSdkVersion") != "28":
        raise ValueError("Unexpected target SDK; keep upstream Termux behavior")
    application = manifest.find("application")
    if application is None:
        raise ValueError("APK has no application")
    debuggable = application.get(ANDROID + "debuggable", "false")
    if debuggable != "false":
        raise ValueError("Release APK must not be debuggable")


def validate_certificate(report, expected):
    digests = re.findall(r"^Signer #\d+ certificate SHA-256 digest:\s*([0-9a-fA-F]+)\s*$", report, re.M)
    if len(digests) != 1 or digests[0].lower() != expected.lower():
        raise ValueError("APK signer does not match the selected MDTerm certificate")


def source_archive(source, destination):
    """Include the patched source and build tooling, but no caches or private key."""
    tracked = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"]).decode().split("\0")
    with tarfile.open(destination, "w:gz") as archive:
        for name in filter(None, tracked):
            archive.add(source / name, arcname=f"MDTermaddon/upstream/{name}", recursive=False)
        project_files = [ROOT / "sources.lock.json", ROOT / "README.md", ROOT / ".gitignore"]
        for directory in ("scripts", "gradle", ".github/workflows", "tests"):
            project_files.extend(path for path in (ROOT / directory).rglob("*")
                                 if path.is_file() and "__pycache__" not in path.parts)
        for path in project_files:
            archive.add(path, arcname=f"MDTermaddon/{path.relative_to(ROOT)}", recursive=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("addon", choices=("api", "boot", "styling"))
    parser.add_argument("--source", type=Path, default=Path("upstream"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--certificate-sha256", required=True)
    args = parser.parse_args()
    lock = load_lock()
    addon = lock["addons"][args.addon]
    source = args.source.resolve()
    apks = list((source / "app/build/outputs/apk/release").glob("*.apk"))
    if len(apks) != 1:
        raise ValueError(f"Expected exactly one APK, found {len(apks)}")
    apk = apks[0]
    sdk_root = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk_root:
        raise ValueError("ANDROID_HOME is required")
    signer = Path(sdk_root) / "build-tools/34.0.0/apksigner"
    report = subprocess.check_output([
        str(signer), "verify", "--verbose", "--print-certs", str(apk)
    ], text=True)
    validate_certificate(report, args.certificate_sha256)
    xml = subprocess.check_output(["apkanalyzer", "manifest", "print", str(apk)], text=True)
    validate_manifest(xml, addon, lock["mdterm"]["shared_user_id"])
    with zipfile.ZipFile(apk) as package:
        if any(name.startswith("lib/") and name.endswith(".so") for name in package.namelist()):
            raise ValueError("Unexpected native library in the upstream universal APK")

    args.output.mkdir(parents=True, exist_ok=True)
    stem = f"MDTerm-{args.addon}-v{addon['version']}-release"
    output = args.output / f"{stem}.apk"
    shutil.copyfile(apk, output)
    source_output = args.output / f"{stem}-source.tar.gz"
    source_archive(source, source_output)
    info_output = args.output / f"{stem}-build-info.json"
    info = {
        "addon": args.addon,
        "build_type": "release",
        "application_id": addon["application_id"],
        "shared_user_id": lock["mdterm"]["shared_user_id"],
        "certificate_sha256": args.certificate_sha256,
        "upstream_repository": addon["repository"],
        "upstream_commit": addon["commit"],
        "upstream_version": addon["version"],
        "mdterm_reference_commit": lock["mdterm"]["commit"],
        "builder_commit": os.environ.get("GITHUB_SHA", "local"),
    }
    info_output.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in (output, source_output, info_output)
    )
    (args.output / f"{stem}-sha256sums.txt").write_text(checksums, encoding="utf-8")
    print(f"Verified {output.name}: {addon['application_id']}, signer {args.certificate_sha256}")


if __name__ == "__main__":
    main()
