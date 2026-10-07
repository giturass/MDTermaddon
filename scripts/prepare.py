#!/usr/bin/env python3
"""Check pinned upstream identity and apply the MDTerm release overlays."""

import argparse
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from source import load_lock
from x11 import prepare_companion

ANDROID = "{http://schemas.android.com/apk/res/android}"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def git(source, *args):
    return subprocess.check_output(["git", "-C", str(source), *args], text=True).strip()


def literal_setting(script, name):
    values = re.findall(r"(?m)^\s*" + re.escape(name) + r"\s+['\"]([^'\"]+)['\"]\s*$", script)
    require(len(values) == 1, f"Expected one literal {name} in application build.gradle")
    return values[0]


def prepare(addon, source):
    lock = load_lock()
    config = lock["addons"][addon]
    package = "com.termux." + addon
    require(lock["mdterm"]["package"] == "com.termux" and
            lock["mdterm"]["shared_user_id"] == "com.termux", "Unexpected MDTerm package or shared UID")
    require(config["application_id"] == package, "Unexpected addon application ID")
    source = source.resolve(strict=True)
    require(Path(git(source, "rev-parse", "--show-toplevel")).resolve() == source,
            "--source must be the upstream checkout root")
    require(git(source, "rev-parse", "HEAD") == config["commit"],
            "Upstream HEAD does not match sources.lock.json")

    # Accept only the pinned contents or our exact, repeatable overlays.
    def original(path):
        return subprocess.check_output(["git", "-C", str(source), "show", "HEAD:" + path], text=True)

    module = config.get("module", "app")
    flavor = config.get("flavor", "")
    namespace = config.get("namespace", package)
    script_path = f"{module}/build.gradle"
    manifests = [f"{module}/src/main/AndroidManifest.xml"]
    if addon == "x11":
        require(flavor == "sharedUid", "X11 must use the sharedUid flavor")
        manifests += [f"{module}/src/sharedUid/AndroidManifest.xml", "lorie/src/main/AndroidManifest.xml"]
    for path in manifests:
        require((source / path).read_text(encoding="utf-8") == original(path),
                f"Upstream manifest has local modifications: {path}")
    manifest = original(manifests[1] if addon == "x11" else manifests[0])
    script = original(script_path)
    require(literal_setting(script, "applicationId") == package, "Unexpected applicationId")
    require(literal_setting(script, "namespace") == namespace, "Unexpected namespace")
    require("applicationIdSuffix" not in script, "Unexpected applicationIdSuffix")
    placeholders = dict(re.findall(
        r"manifestPlaceholders\.([A-Z_]+)\s*=\s*['\"]([^'\"]+)['\"]", script))

    def resolve(value):
        return re.sub(r"\$\{([A-Z_]+)\}", lambda m: placeholders.get(m[1], m[0]), value)

    root = ET.fromstring(manifest)
    require(root.tag == "manifest" and resolve(root.get(ANDROID + "sharedUserId", "")) == "com.termux",
            "Manifest sharedUserId must resolve to com.termux")
    if root.get("package") is not None:
        require(resolve(root.get("package")) == package, "Unexpected manifest package")
    if addon == "x11":
        application = root.find("application")
        require(application is not None and application.get(ANDROID + "process") == "com.termux",
                "X11 sharedUid application must run in com.termux")

    prepared = script
    if "termux_shared_commit" in config:
        shared_commit = config["termux_shared_commit"]
        require(re.fullmatch(r"[0-9a-f]{40}", shared_commit) is not None and
                shared_commit.startswith("7bceab88e2"), "Unexpected termux-shared commit")
        dependency = 'implementation "com.termux.termux-app:termux-shared:7bceab88e2"'
        require(prepared.count(dependency) == 1, "Expected one pinned termux-shared dependency")
        prepared = prepared.replace(dependency,
            'implementation "com.termux.termux-app:termux-shared:' + shared_commit + '"')
    prepared += (
        "\n// BEGIN MDTermaddon signing overlay\n"
        + "ext.mdtermAddonApplicationId = '" + package + "'\n"
        + "ext.mdtermAddonNamespace = '" + namespace + "'\n"
        + "ext.mdtermAddonFlavor = '" + flavor + "'\n"
        + "def mdtermAddonOverlay = System.getenv('MDTERM_ADDON_GRADLE')\n"
        + "if (!mdtermAddonOverlay || !new File(mdtermAddonOverlay).isFile()) {\n"
        + "    throw new GradleException('MDTERM_ADDON_GRADLE must point to gradle/mdterm-addon.gradle')\n"
        + "}\n"
        + "apply from: mdtermAddonOverlay\n"
        + "// END MDTermaddon signing overlay\n"
    )
    changes = {script_path: prepared}
    if addon == "x11":
        changes.update(prepare_companion(original))
    # Validate every file before writing any overlay.
    for path, content in changes.items():
        require((source / path).read_text(encoding="utf-8") in (original(path), content),
                f"Unexpected local changes in {path}")
    for path, content in changes.items():
        target = source / path
        if target.read_text(encoding="utf-8") != content:
            target.write_text(content, encoding="utf-8")
    print(f"Prepared {package} at {config['commit']}; shared UID com.termux")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("addon", choices=load_lock()["addons"])
    parser.add_argument("--source", type=Path, default=Path("upstream"))
    args = parser.parse_args()
    try:
        prepare(args.addon, args.source)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, ET.ParseError) as error:
        parser.exit(1, f"prepare: {error}\n")


if __name__ == "__main__":
    main()
