"""Prepare and verify the X11 command-line companion for the MDTerm release key."""

import io
from pathlib import Path
import re
import tarfile
import zipfile


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f"Unexpected upstream X11 companion setting: {before}")
    return text.replace(before, after)


def prepare_loader_checks(script):
    # Java assertions may be removed by release dexing. These checks protect the
    # class loader and must execute regardless of the compiler's assertion mode.
    script = replace_once(script,
        "assert targetInfo != null : BuildConfig.packageNotInstalledErrorText;",
        "if (targetInfo == null) throw new AssertionError(BuildConfig.packageNotInstalledErrorText);")
    return replace_once(script,
        "assert targetInfo.signatures.length == 1 && BuildConfig.SIGNATURE == targetInfo.signatures[0].hashCode() : BuildConfig.packageSignatureMismatchErrorText;",
        "if (targetInfo.signatures == null || targetInfo.signatures.length != 1 || "
        "BuildConfig.SIGNATURE != targetInfo.signatures[0].hashCode())\n"
        "                throw new AssertionError(BuildConfig.packageSignatureMismatchErrorText);")


def prepare_companion(original):
    """Return guarded patches; the caller checks checkout identity and writes them."""
    loader_path = "shell-loader/build.gradle"
    loader = original(loader_path)
    loader = replace_once(loader,
        "def signingConfig = project(':lorie-app').android.signingConfigs.debug",
        "evaluationDependsOn(':lorie-app')\n"
        "def signingConfig = project(':lorie-app').android.signingConfigs.mdtermAddon")
    loader = replace_once(loader,
        "keyStore.load(new FileInputStream(signingConfig.storeFile), signingConfig.keyPassword.toCharArray())",
        "keyStore.load(new FileInputStream(signingConfig.storeFile), signingConfig.storePassword.toCharArray())")
    for setting in ("signingConfig null", "minifyEnabled true", "shrinkResources true",
                    "proguardFiles 'proguard-rules.pro'"):
        loader = replace_once(loader, "android.buildTypes.debug." + setting,
                              "android.buildTypes.release." + setting)
    loader = replace_once(loader, "android.buildTypes.release.signingConfig null",
        "android.buildTypes.release.signingConfig null\n"
        "android.buildTypes.release.debuggable false\n"
        "androidComponents { beforeVariants(selector().withBuildType('debug')) { it.enable = false } }")
    loader = replace_once(loader, 'it.outputFileName.set("shell-loader-debug.apk")',
                          'it.outputFileName.set("shell-loader-release.apk")')
    # This message is shown when the paired app is missing. Upstream nightly APKs
    # carry a different certificate and cannot be used with this companion.
    start = 'android.defaultConfig.buildConfigField "String", "packageNotInstalledErrorText",'
    end = 'android.defaultConfig.buildConfigField "String", "packageSignatureMismatchErrorText",'
    if loader.count(start) != 1 or loader.count(end) != 1:
        raise ValueError("Unexpected upstream X11 loader installation message")
    first, last = loader.index(start), loader.index(end)
    if first >= last:
        raise ValueError("Unexpected upstream X11 loader message order")
    loader = loader[:first] + start + '\n' + (
        '        "\\\"Install the MDTerm X11 shared UID release APK and companion package '
        'from the same MDTermaddon build.\\\""\n') + loader[last:]
    signature = ('android.defaultConfig.buildConfigField "int", "SIGNATURE", '
                 'String.valueOf(Arrays.hashCode(keyStore.getCertificate(signingConfig.keyAlias).getEncoded()))')
    if loader.count(signature) != 1:
        raise ValueError("Unexpected upstream X11 loader signature check")
    package_path = "shell-loader/companion-package.gradle"
    package = original(package_path)
    package = replace_once(package, "tasks.named('assembleDebug')", "tasks.named('assembleRelease')")
    package = replace_once(package, "outputs/apk/debug/shell-loader-debug.apk",
                            "outputs/apk/release/shell-loader-release.apk")
    entry_path = "shell-loader/src/main/java/com/termux/x11/Loader.java"
    return {loader_path: loader, package_path: package,
            entry_path: prepare_loader_checks(original(entry_path))}


def signature_hash(certificate_der):
    """Match java.util.Arrays.hashCode(byte[]) and Android Signature.hashCode()."""
    value = 1
    for byte in certificate_der:
        value = (31 * value + (byte if byte < 128 else byte - 256)) & 0xffffffff
    return value if value < 0x80000000 else value - 0x100000000


def ar_members(data):
    """Read the simple, short-name ar format emitted by the upstream .deb task."""
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("Invalid companion Debian archive")
    position, members = 8, {}
    while position < len(data):
        header = data[position:position + 60]
        if len(header) != 60 or header[58:60] != b"`\n":
            raise ValueError("Invalid companion Debian archive header")
        try:
            name = header[:16].decode("ascii").rstrip().removesuffix("/")
            size = int(header[48:58])
        except (UnicodeError, ValueError) as error:
            raise ValueError("Invalid companion Debian archive entry") from error
        position += 60
        if not name or name in members or size < 0 or position + size > len(data):
            raise ValueError("Invalid or duplicate companion Debian archive entry")
        members[name] = data[position:position + size]
        position += size
        if size % 2:
            if data[position:position + 1] != b"\n":
                raise ValueError("Invalid companion Debian archive padding")
            position += 1
    return members


def tar_members(data):
    """Read without extracting: reject links, traversal, and duplicate members."""
    files, names = {}, set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for entry in archive:
            name = entry.name.removeprefix("./").rstrip("/")
            if not name or name.startswith("/") or ".." in name.split("/") or name in names:
                raise ValueError("Invalid or duplicate companion archive path")
            names.add(name)
            if entry.isdir():
                continue
            if not entry.isfile():
                raise ValueError("Unexpected companion archive link or special file")
            files[name] = (archive.extractfile(entry).read(), entry.mode & 0o7777)
    return files


def verify_payload(files, expected):
    if files.keys() != expected.keys():
        raise ValueError("Unexpected companion package payload files")
    for name, (data, mode) in files.items():
        if data != expected[name][0] or mode != expected[name][1]:
            raise ValueError(f"Companion package payload mismatch: {name}")


def verify_companion(source, version, certificate_der):
    """Return both packages after verifying their paired release loader and scripts."""
    source = Path(source)
    build = source / "shell-loader/build"
    loader = build / "outputs/apk/release/shell-loader-release.apk"
    if list((build / "outputs/apk").rglob("*.apk")) != [loader]:
        raise ValueError("Expected only the X11 release shell loader APK")
    loader_bytes = loader.read_bytes()
    with zipfile.ZipFile(io.BytesIO(loader_bytes)) as apk:
        if "classes.dex" not in apk.namelist():
            raise ValueError("X11 shell loader APK has no classes.dex")
    configs = list((build / "generated/source/buildConfig/release").rglob("BuildConfig.java"))
    if len(configs) != 1 or not certificate_der:
        raise ValueError("Missing X11 release loader BuildConfig or signing certificate")
    signatures = re.findall(r"\bSIGNATURE\s*=\s*(-?\d+)\s*;", configs[0].read_text(encoding="utf-8"))
    if signatures != [str(signature_hash(certificate_der))]:
        raise ValueError("X11 release loader signature does not match the MDTerm certificate")
    prefix = "data/data/com.termux/files/usr"
    expected = {f"{prefix}/libexec/termux-x11/loader.apk": (loader_bytes, 0o644)}
    for name in ("termux-x11", "termux-x11-preference"):
        script = (source / f"shell-loader/scripts/{name}.in").read_bytes()
        script = script.replace(b"@APPLICATION_ID@", b"com.termux.x11")
        script = script.replace(b"@EMBEDDED_APPLICATION_ID@", b"com.termux")
        expected[f"{prefix}/bin/{name}"] = (script, 0o755)
    output = build / "outputs/companion"
    package_version = version + "-0"
    deb = output / f"termux-x11-nightly-{package_version}-all.deb"
    pacman = output / f"termux-x11-nightly-{package_version}-any.pkg.tar.xz"
    if not output.is_dir() or set(output.iterdir()) != {deb, pacman}:
        raise ValueError("Expected exactly the X11 Debian and pacman companion packages")
    members = ar_members(deb.read_bytes())
    if set(members) != {"debian-binary", "control.tar.gz", "data.tar.xz"} or members["debian-binary"] != b"2.0\n":
        raise ValueError("Unexpected companion Debian archive members")
    verify_payload(tar_members(members["data.tar.xz"]), expected)
    control = tar_members(members["control.tar.gz"])
    if set(control) != {"control", "postinst"}:
        raise ValueError("Unexpected companion Debian control files")
    metadata = control["control"][0].decode("utf-8").splitlines()
    if not all(line in metadata for line in ("Package: termux-x11-nightly", "Architecture: all",
                                             "Version: " + package_version, "Depends: xkeyboard-config")):
        raise ValueError("Unexpected companion Debian package metadata")
    pacman_files = tar_members(pacman.read_bytes())
    meta_names = {".PKGINFO", ".BUILDINFO", ".INSTALL", ".MTREE"}
    if not meta_names.issubset(pacman_files) or any(not pacman_files[name][0] for name in meta_names):
        raise ValueError("Missing companion pacman package metadata")
    metadata = pacman_files[".PKGINFO"][0].decode("utf-8").splitlines()
    if not all(line in metadata for line in ("pkgname = termux-x11-nightly", "arch = any",
                                             "pkgver = " + package_version, "depend = xkeyboard-config")):
        raise ValueError("Unexpected companion pacman package metadata")
    verify_payload({name: value for name, value in pacman_files.items() if name not in meta_names}, expected)
    return [deb, pacman]
