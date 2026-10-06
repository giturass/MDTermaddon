#!/usr/bin/env python3
"""Print locked checkout metadata as GitHub Actions step outputs."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_lock():
    return json.loads((ROOT / "sources.lock.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("addon", choices=("api", "boot", "styling"))
    args = parser.parse_args()
    for key, value in load_lock()["addons"][args.addon].items():
        if "\n" in str(value) or "\r" in str(value):
            raise SystemExit(f"Invalid newline in {key}")
        print(f"{key}={value}")
