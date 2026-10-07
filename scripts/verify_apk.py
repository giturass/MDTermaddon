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
from x11 import verify_companion

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
    if addon.get("flavor") == "sharedUid":
        process = application.get(ANDROID + "process")
        if process != shared_user_id:
            raise ValueError("X11 sharedUid application must run in com.termux")
        for component in application:
            if component.tag in ("activity", "activity-alias", "service", "receiver", "provider"):
                if component.get(ANDROID + "process", process) != shared_user_id:
                    raise ValueError("X11 sharedUid components must run in com.termux")


def validate_native_libraries(names, addon):
    libraries = [name for name in names if name.startswith("lib/") and name.endswith(".so")]
    expected_abis = set(addon.get("native_abis", []))
    if not expected_abis:
        if libraries:
            raise ValueError("Unexpected native library in the upstream universal APK")
        return
    if any(len(name.split("/")) != 3 for name in libraries):
        raise ValueError("Unexpected native library path")
    actual_abis = {name.split("/")[1] for name in libraries}
    if actual_abis != expected_abis:
        raise ValueError("APK native ABIs do not match sources.lock.json")
    for abi in expected_abis:
        if f"lib/{abi}/{addon['native_library']}" not in libraries:
            raise ValueError(f"Missing X11 native library for {abi}")


def find_apk(source, addon):
    directory = source / addon.get("module", "app") / "build/outputs/apk"
    if addon.get("flavor"):
        directory /= addon["flavor"]
    apks = list((directory / "release").glob("*.apk"))
    if len(apks) != 1:
        raise ValueError(f"Expected exactly one release APK in {directory}, found {len(apks)}")
    return apks[0]


def validate_certificate(report, expected):
    digests = re.findall(r"^Signer #\d+ certificate SHA-256 digest:\s*([0-9a-fA-F]+)\s*$", report, re.M)
    if len(digests) != 1 or digests[0].lower() != expected.lower():
        raise ValueError("APK signer does not match the selected MDTerm certificate")


def source_archive(source, destination):
    """Include the patched source and build tooling, but no caches or private key."""
    def excluded(path):
        return (any(part in {".git", ".gradle", "__pycache__", ".venv"} for part in path.parts)
                or path.name == "local.properties"
                or path.suffix.lower() in {".pyc", ".jks", ".keystore", ".p12", ".pfx"})

    def tracked_files(repository, prefix=Path()):
        entries = subprocess.check_output([
            "git", "-C", str(repository), "ls-files", "--stage", "-z"
        ]).split(b"\0")
        files = []
        for entry in filter(None, entries):
            metadata, raw_name = entry.split(b"\t", 1)
            mode, commit, stage = metadata.decode("ascii").split()
            name = Path(os.fsdecode(raw_name))
            relative = prefix / name
            path = repository / name
            if stage != "0":
                raise ValueError(f"Unmerged source file: {relative}")
            if mode == "160000":
                # An empty submodule directory otherwise resolves to its parent's
                # repository, so require its own checkout before reading HEAD.
                if not (path / ".git").exists():
                    raise ValueError(f"Submodule is not initialized: {relative}")
                try:
                    top = subprocess.check_output([
                        "git", "-C", str(path), "rev-parse", "--show-toplevel"
                    ], text=True, stderr=subprocess.STDOUT).strip()
                    actual = subprocess.check_output([
                        "git", "-C", str(path), "rev-parse", "HEAD"
                    ], text=True, stderr=subprocess.STDOUT).strip()
                except subprocess.CalledProcessError as error:
                    raise ValueError(f"Invalid submodule checkout: {relative}") from error
                if Path(top).resolve() != path.resolve() or actual != commit:
                    raise ValueError(f"Submodule does not match locked commit: {relative}")
                files.extend(tracked_files(path, relative))
            elif not excluded(relative):
                files.append((path, relative))
        return files

    # Validate every nested gitlink before creating a publishable archive. Read
    # tracked files from the worktree so the build's patches are included too.
    tracked = tracked_files(source)
    with tarfile.open(destination, "w:gz") as archive:
        for path, relative in tracked:
            archive.add(path, arcname=f"MDTermaddon/upstream/{relative}", recursive=False)
        project_files = [ROOT / "sources.lock.json", ROOT / "README.md", ROOT / ".gitignore"]
        for directory in ("scripts", "gradle", ".github/workflows", "tests"):
            project_files.extend(path for path in (ROOT / directory).rglob("*")
                                 if path.is_file() and not excluded(path.relative_to(ROOT)))
        for path in project_files:
            archive.add(path, arcname=f"MDTermaddon/{path.relative_to(ROOT)}", recursive=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("addon", choices=load_lock()["addons"])
    parser.add_argument("--source", type=Path, default=Path("upstream"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--certificate-sha256", required=True)
    args = parser.parse_args()
    lock = load_lock()
    addon = lock["addons"][args.addon]
    source = args.source.resolve()
    apk = find_apk(source, addon)
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
        validate_native_libraries(package.namelist(), addon)

    companions = []
    if args.addon == "x11":
        cert = subprocess.check_output([
            "keytool", "-exportcert", "-keystore", os.environ["MDTERM_ADDON_STORE_FILE"],
            "-alias", os.environ["MDTERM_ADDON_KEY_ALIAS"],
            "-storepass:env", "MDTERM_ADDON_STORE_PASSWORD",
        ])
        if hashlib.sha256(cert).hexdigest() != args.certificate_sha256.lower():
            raise ValueError("Companion certificate does not match the APK signer")
        companions = verify_companion(source, addon["companion_version"], cert)
        loader = source / "shell-loader/build/outputs/apk/release/shell-loader-release.apk"
        if subprocess.check_output(["apkanalyzer", "manifest", "debuggable", str(loader)], text=True).strip() != "false":
            raise ValueError("X11 companion loader must not be debuggable")

    args.output.mkdir(parents=True, exist_ok=True)
    variant = f"{addon['flavor']}-release" if addon.get("flavor") else "release"
    stem = f"MDTerm-{args.addon}-v{addon['version']}-{variant}"
    output = args.output / f"{stem}.apk"
    shutil.copyfile(apk, output)
    source_output = args.output / f"{stem}-source.tar.gz"
    source_archive(source, source_output)
    info_output = args.output / f"{stem}-build-info.json"
    info = {
        "addon": args.addon,
        "build_type": "release",
        "flavor": addon.get("flavor"),
        "application_id": addon["application_id"],
        "shared_user_id": lock["mdterm"]["shared_user_id"],
        "certificate_sha256": args.certificate_sha256,
        "upstream_repository": addon["repository"],
        "upstream_commit": addon["commit"],
        "upstream_version": addon["version"],
        "mdterm_reference_commit": lock["mdterm"]["commit"],
        "builder_commit": os.environ.get("GITHUB_SHA", "local"),
        "native_abis": addon.get("native_abis", []),
        "companion_packages": [path.name for path in companions],
    }
    info_output.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    companion_outputs = []
    for path in companions:
        destination = args.output / path.name
        shutil.copyfile(path, destination)
        companion_outputs.append(destination)
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in (output, source_output, info_output, *companion_outputs)
    )
    (args.output / f"{stem}-sha256sums.txt").write_text(checksums, encoding="utf-8")
    print(f"Verified {output.name}: {addon['application_id']}, signer {args.certificate_sha256}")


if __name__ == "__main__":
    main()
