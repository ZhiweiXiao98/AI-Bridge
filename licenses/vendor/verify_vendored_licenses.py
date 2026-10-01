#!/usr/bin/env python3
"""Read-only SHA-256 verification for this source attribution supplement."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path,
                        help="Optional AI-Bridge source root containing lib/")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "LICENSE_FILES_SHA256.json").read_text(encoding="utf-8"))
    errors = []
    for item in manifest:
        path = root / item["path"]
        if not path.is_file():
            errors.append(f"Missing supplement file: {item['path']}")
        else:
            data = path.read_bytes()
            if len(data) != item["size_bytes"] or digest(data) != item["sha256"]:
                errors.append(f"Supplement mismatch: {item['path']}")
    source_count = 0
    if args.source_root is not None:
        provenance = json.loads((root / "VENDORED_PROVENANCE.json").read_text(encoding="utf-8"))
        for item in provenance["assets"]:
            path = args.source_root / item["path"]
            if not path.is_file():
                errors.append(f"Missing source asset: {item['path']}")
                continue
            data = path.read_bytes()
            git_hash = hashlib.sha1(
                b"blob " + str(len(data)).encode() + b"\0" + data
            ).hexdigest()
            if (len(data) != item["size_bytes"]
                    or digest(data) != item["sha256"]
                    or git_hash != item["git_blob_sha1"]):
                errors.append(f"Source asset mismatch: {item['path']}")
            source_count += 1
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"PASS: {len(manifest)} supplement files; "
          f"{source_count} source assets verified")
    print("Scope: integrity verification only; see the documented open issues")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
