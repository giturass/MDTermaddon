#!/usr/bin/env python3
"""Restore the MDTerm release key and print its certificate SHA-256."""

import argparse
import base64
import hashlib
import os
from pathlib import Path
import subprocess


def key_bytes():
    encoded = os.environ.get("MDTERM_RELEASE_KEYSTORE_BASE64", "")
    if not encoded:
        raise ValueError("Missing MDTERM_RELEASE_KEYSTORE_BASE64; copy the same secret from MDTerm")
    result = base64.b64decode("".join(encoded.split()), validate=True)
    if not result:
        raise ValueError("Release keystore is empty")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    for name in ("STORE_FILE", "STORE_PASSWORD", "KEY_ALIAS", "KEY_PASSWORD"):
        if not os.environ.get(f"MDTERM_ADDON_{name}"):
            raise ValueError(f"Missing MDTERM_ADDON_{name}")
    data = key_bytes()
    key = Path(os.environ["MDTERM_ADDON_STORE_FILE"])
    # The caller creates a private directory under ~/tmp and always removes it.
    with key.open("xb") as stream:
        key.chmod(0o600)
        stream.write(data)
    cert = subprocess.check_output([
        "keytool", "-exportcert", "-keystore", str(key),
        "-alias", os.environ["MDTERM_ADDON_KEY_ALIAS"],
        "-storepass:env", "MDTERM_ADDON_STORE_PASSWORD",
    ])
    digest = hashlib.sha256(cert).hexdigest()
    expected = os.environ.get("MDTERM_RELEASE_CERT_SHA256", "")
    if expected:
        if digest != expected.replace(":", "").strip().lower():
            raise ValueError("Release key does not match MDTERM_RELEASE_CERT_SHA256")
    print(digest)


if __name__ == "__main__":
    main()
