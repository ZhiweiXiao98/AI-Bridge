"""BLOCKED DRAFT: validate exact ciphertext structure/hash allowlist; NO upload.

This verifier has no GCM key and does NOT authenticate encryption or the sender.
Use only immediately after a successful trusted sealer in the same isolated job.
No part_count is emitted until all checks complete. Owner decryption still must
perform RSA unwrap, GCM authentication and independently trusted plaintext checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

import receive_local as R
import seal_local as S


def _expected_from_validation(path: Path, workflow_commit: str,
                              run_id: str, run_attempt: str) -> R.Expected:
    if path.name != S.VALIDATION_NAME:
        raise ValueError("Expected fixed independent package validation filename")
    with S._regular_input(path) as stream:
        before = S._identity(stream)
        data = stream.read(S.MAX_VALIDATION_SIZE + 1)
        if S._identity(stream) != before:
            raise ValueError("Package validation changed while read")
    if len(data) > S.MAX_VALIDATION_SIZE:
        raise ValueError("Package validation exceeds fixed size bound")
    def reject_constant(value):
        raise ValueError("Non-finite package validation value")
    value = json.loads(data, object_pairs_hook=S._unique_json_object,
                       parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Invalid package validation object")
    value = S._validate_validation(value, value.get("archive_size"),
                                   value.get("archive_sha256"), S.SOURCE_COMMIT,
                                   S.MATERIALS_MANIFEST_SHA256)
    expected = R.Expected(S.SOURCE_COMMIT, workflow_commit, run_id, run_attempt,
                          S.RECIPIENT_PUBLIC_SHA256, S.MATERIALS_MANIFEST_SHA256,
                          value["archive_size"], value["archive_sha256"])
    R._validate_expected(expected)
    return expected


def checked_parts(directory: Path, *, validation_path: Path,
                  workflow_commit: str, run_id: str, run_attempt: str = "1") -> int:
    S._check_review_gates()  # Same source/new-recipient/materials pins as sealer.
    S._parts(directory)
    S._parts(validation_path)
    expected = _expected_from_validation(validation_path, workflow_commit,
                                         run_id, run_attempt)
    with S._directory(directory) as directory_fd:
        envelope = R._parse_envelope(directory_fd)  # bounded read, duplicate keys
        manifest, parts, _nonce, tag, _wrapped = R._validated_envelope(envelope, expected)
        names = set(manifest["output_files"])
        if set(os.listdir(directory_fd)) != names:
            raise ValueError("Ciphertext directory differs from exact allowlist")
        complete_hash = hashlib.sha256()
        for part in parts:
            part_hash, total = hashlib.sha256(), 0
            with R._regular_at(directory_fd, part["name"]) as stream:
                before = S._identity(stream)
                if before[2] != part["size"]:
                    raise ValueError("Ciphertext part length mismatch")
                while data := stream.read(S.IO_BLOCK_SIZE):
                    total += len(data)
                    if total > part["size"]:
                        raise ValueError("Ciphertext grew during validation")
                    part_hash.update(data)
                    complete_hash.update(data)
                if S._identity(stream) != before:
                    raise ValueError("Ciphertext changed during validation")
            if total != part["size"] or part_hash.hexdigest() != part["sha256"]:
                raise ValueError("Ciphertext part hash/size mismatch")
        complete_hash.update(tag)
        if complete_hash.hexdigest() != envelope["ciphertext_sha256"]:
            raise ValueError("Complete ciphertext||tag hash mismatch")
        if set(os.listdir(directory_fd)) != names:
            raise ValueError("Output allowlist changed during validation")
        # Still only structure + hashes. A forger can recompute ordinary hashes.
        # No encryption/authentication claim is inferred from this return value.
        return len(parts)


def _append_count(path: Path, count: int):
    S._parts(path)
    with S._directory(path.parent) as parent_fd:
        fd = os.open(path.name, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW |
                     os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("GITHUB_OUTPUT must be a regular pre-existing file")
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            fd = -1
            stream.write(f"part_count={count}\n")
    finally:
        if fd >= 0:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sealed", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--workflow-commit", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID"))
    parser.add_argument("--run-attempt", default=os.environ.get("GITHUB_RUN_ATTEMPT"))
    args = parser.parse_args()
    count = checked_parts(args.sealed, validation_path=args.validation,
                          workflow_commit=args.workflow_commit, run_id=args.run_id,
                          run_attempt=args.run_attempt)
    _append_count(Path(os.environ["GITHUB_OUTPUT"]), count)
    print(json.dumps({"part_count": count, "structure_and_hashes_checked": True,
                      "gcm_authenticated": False, "sender_authenticated": False,
                      "upload_authorized": False}, sort_keys=True))


if __name__ == "__main__":
    main()
