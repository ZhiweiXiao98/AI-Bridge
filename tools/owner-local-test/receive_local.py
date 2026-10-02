"""BLOCKED DRAFT: authenticate a v2 owner envelope before releasing plaintext.

The caller must provide a locally held RSA private-key object and independently
trusted expected provenance/hash. There is no private-key import/export CLI.
Owner key use and production receiving remain blocked pending separate approval.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import seal_local as S

SOURCE_COMMIT = "887594cacc6de1c6baa204e8157de000d31f4506"
RECIPIENT_PUBLIC_SHA256 = "a53faa294a2ba5c656af3f322c11c0c620950f2a54ed877a4842113cb04990db"
MATERIALS_MANIFEST_SHA256 = "32540be458d5bb452581f78f6184b8bbf575a674cf994e1e026c6fc8404cd7ce"
PRODUCTION_RECEIVING_APPROVED = True
MAX_ENVELOPE_SIZE = S.MAX_ENVELOPE_SIZE
UNVERIFIED_NAME = ".owner-test-unverified.tmp"
RECEIPT_NAME = "owner-test-received.json"
TRANSFER_LIMIT = 32 * 1024 * 1024
# Exact two-entry ZIP_STORED recipe, no extra fields/comments, fixed ASCII names.
ZIP_OVERHEAD_BUDGET = 1024
assert S.CHUNK_SIZE + MAX_ENVELOPE_SIZE + ZIP_OVERHEAD_BUDGET < TRANSFER_LIMIT


@dataclass(frozen=True)
class Expected:
    source_commit: str
    workflow_commit: str
    run_id: str
    run_attempt: str
    recipient_sha256: str
    materials_manifest_sha256: str
    archive_size: int
    archive_sha256: str


def _hex(value, digits):
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{digits}}}", value)


def _check_review_gates(expected: Expected):
    if PRODUCTION_RECEIVING_APPROVED is not True:
        raise ValueError("DRAFT BLOCKED: production receiving has not been approved")
    if (not _hex(SOURCE_COMMIT, 40) or not _hex(RECIPIENT_PUBLIC_SHA256, 64)
            or not _hex(MATERIALS_MANIFEST_SHA256, 64)):
        raise ValueError("DRAFT BLOCKED: receiver review pins must be approved")
    if RECIPIENT_PUBLIC_SHA256 == S.RETIRED_RECIPIENT_SHA256:
        raise ValueError("Retired owner public key is forbidden")
    _validate_expected(expected)
    if (expected.source_commit != SOURCE_COMMIT
            or expected.recipient_sha256 != RECIPIENT_PUBLIC_SHA256
            or expected.materials_manifest_sha256 != MATERIALS_MANIFEST_SHA256):
        raise ValueError("Expected provenance does not match independent review pins")


def _validate_expected(expected: Expected):
    """Shared structural validation; does not authorize receiving or uploading."""
    if not isinstance(expected, Expected):
        raise ValueError("Independent expected provenance is required")
    if (not _hex(expected.source_commit, 40)
            or not _hex(expected.recipient_sha256, 64)
            or expected.recipient_sha256 == S.RETIRED_RECIPIENT_SHA256
            or not _hex(expected.materials_manifest_sha256, 64)
            or not _hex(expected.workflow_commit, 40)
            or not isinstance(expected.run_id, str)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", expected.run_id)
            or not isinstance(expected.run_attempt, str)
            or not re.fullmatch(r"[1-9][0-9]{0,5}", expected.run_attempt)
            or not _hex(expected.archive_sha256, 64)):
        raise ValueError("Invalid independently expected provenance/hash")
    S.part_layout(expected.archive_size)


@contextmanager
def _regular_at(directory_fd, name):
    if not name or "/" in name or name in {".", ".."}:
        raise ValueError("Only fixed basenames are allowed")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                 os.O_CLOEXEC, dir_fd=directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Expected a regular non-symlink input")
        stream = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    with stream:
        yield stream


def _parse_envelope(directory_fd):
    with _regular_at(directory_fd, S.ENVELOPE_NAME) as stream:
        data = stream.read(MAX_ENVELOPE_SIZE + 1)
    if len(data) > MAX_ENVELOPE_SIZE:
        raise ValueError("Envelope exceeds 128 KiB")
    def reject_constant(value):
        raise ValueError("Non-finite envelope value")
    value = json.loads(data, object_pairs_hook=S._unique_json_object,
                       parse_constant=reject_constant)
    if not isinstance(value, dict) or set(value) != {
            "manifest", "nonce", "wrapped_key", "tag", "ciphertext_sha256", "parts"}:
        raise ValueError("Envelope keys/schema are invalid")
    return value


def _decode(value, length):
    if not isinstance(value, str):
        raise ValueError("Expected canonical base64 string")
    raw = base64.b64decode(value, validate=True)
    if len(raw) != length or base64.b64encode(raw).decode("ascii") != value:
        raise ValueError("Invalid encoded key/nonce/tag length or canonicalization")
    return raw


def _validated_envelope(envelope, expected):
    _validate_expected(expected)
    manifest = envelope["manifest"]
    if not isinstance(manifest, dict):
        raise ValueError("Invalid manifest")
    validation = S._validate_validation(
        manifest.get("package_validation"), expected.archive_size,
        expected.archive_sha256, expected.source_commit,
        expected.materials_manifest_sha256)
    # Rebuild the complete expected manifest, rejecting unknown fields, modified
    # bounds, extra names and JSON bool/int confusion via canonical comparison.
    wanted = S._manifest(expected.archive_size, expected.archive_sha256,
                         expected.recipient_sha256, expected.workflow_commit,
                         expected.run_id, expected.run_attempt, validation)
    wanted["source_commit"] = expected.source_commit
    if S.canonical(manifest) != S.canonical(wanted):
        raise ValueError("Manifest does not match trusted expected context/protocol")
    parts = envelope["parts"]
    if type(parts) is not list or len(parts) != len(wanted["part_layout"]):
        raise ValueError("Unexpected part count")
    for part, layout in zip(parts, wanted["part_layout"]):
        if (not isinstance(part, dict) or set(part) != {"name", "size", "sha256"}
                or type(part["size"]) is not int
                or part["size"] != layout["size"] or part["name"] != layout["name"]
                or not _hex(part["sha256"], 64)):
            raise ValueError("Invalid/reordered part descriptor")
    if not _hex(envelope["ciphertext_sha256"], 64):
        raise ValueError("Invalid complete ciphertext hash")
    return (manifest, parts, _decode(envelope["nonce"], 12),
            _decode(envelope["tag"], S.TAG_SIZE),
            _decode(envelope["wrapped_key"], 384))


def _publish_verified(directory_fd, receipt):
    """Called ONLY after GCM finalize + all hashes pass. Never overwrite."""
    linked = False
    marker_created = False
    try:
        # Hard-link publication is atomic and fails if the final name exists.
        os.link(UNVERIFIED_NAME, S.ARCHIVE_NAME, src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd, follow_symlinks=False)
        linked = True
        os.unlink(UNVERIFIED_NAME, dir_fd=directory_fd)
        with S._new_file(directory_fd, RECEIPT_NAME) as target:
            marker_created = True
            target.write(S.canonical(receipt) + b"\n")
            target.flush()
            os.fsync(target.fileno())
        os.fsync(directory_fd)
    except BaseException:
        if marker_created:
            os.unlink(RECEIPT_NAME, dir_fd=directory_fd)
        if linked:
            os.unlink(S.ARCHIVE_NAME, dir_fd=directory_fd)
        raise


def receive(input_directory: Path, output_directory: Path, *,
            private_key: rsa.RSAPrivateKey, expected: Expected) -> tuple[Path, Path]:
    _check_review_gates(expected)  # Before key use, input access or output creation.
    S._parts(input_directory)
    S._parts(output_directory)
    if (not isinstance(private_key, rsa.RSAPrivateKey) or private_key.key_size != 3072
            or private_key.public_key().public_numbers().e != 65537):
        raise ValueError("Expected a locally held RSA-3072 private-key object")
    public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(public_der).hexdigest() != expected.recipient_sha256:
        raise ValueError("Private key does not correspond to the approved recipient")
    with S._directory(input_directory) as source_fd:
        envelope = _parse_envelope(source_fd)
        manifest, parts, nonce, tag, wrapped_key = _validated_envelope(envelope, expected)
        if set(os.listdir(source_fd)) != set(manifest["output_files"]):
            raise ValueError("Input directory differs from exact artifact allowlist")
        key = private_key.decrypt(wrapped_key, padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(),
            label=S.AAD_LABEL))
        if len(key) != 32:
            raise ValueError("Unwrapped key is not AES-256")
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(S.AAD_LABEL + S.canonical(manifest))
        cipher_hash = hashlib.sha256()
        plaintext_hash = hashlib.sha256()
        total = 0
        with S._new_directory(output_directory) as output_fd:
            try:
                with S._new_file(output_fd, UNVERIFIED_NAME) as quarantined:
                    for part in parts:
                        part_hash, part_total = hashlib.sha256(), 0
                        with _regular_at(source_fd, part["name"]) as source:
                            before = S._identity(source)
                            if before[2] != part["size"]:
                                raise ValueError("Part length mismatch/truncation")
                            while data := source.read(S.IO_BLOCK_SIZE):
                                part_total += len(data)
                                if part_total > part["size"]:
                                    raise ValueError("Part grew during verification")
                                part_hash.update(data)
                                cipher_hash.update(data)
                                plaintext = decryptor.update(data)
                                quarantined.write(plaintext)
                                plaintext_hash.update(plaintext)
                                total += len(plaintext)
                            if S._identity(source) != before:
                                raise ValueError("Part changed during verification")
                        if part_total != part["size"] or part_hash.hexdigest() != part["sha256"]:
                            raise ValueError("Part length/hash mismatch")
                    cipher_hash.update(tag)
                    if cipher_hash.hexdigest() != envelope["ciphertext_sha256"]:
                        raise ValueError("Complete ciphertext hash mismatch")
                    final = decryptor.finalize()  # AUTHENTICATION BOUNDARY.
                    quarantined.write(final)
                    plaintext_hash.update(final)
                    total += len(final)
                    if total != expected.archive_size or plaintext_hash.hexdigest() != expected.archive_sha256:
                        raise ValueError("Authenticated plaintext length/hash mismatch")
                    quarantined.flush()
                    os.fsync(quarantined.fileno())
                if set(os.listdir(output_fd)) != {UNVERIFIED_NAME}:
                    raise ValueError("Unexpected output before authenticated publication")
                receipt = {"schema_version": 1, "authenticated": True,
                           "source_commit": expected.source_commit,
                           "workflow_commit": expected.workflow_commit,
                           "run_id": expected.run_id, "run_attempt": expected.run_attempt,
                           "filename": S.ARCHIVE_NAME, "archive_size": total,
                           "archive_sha256": plaintext_hash.hexdigest(),
                           "binary_distribution_approved": False}
                _publish_verified(output_fd, receipt)
            except BaseException:
                try:
                    os.unlink(UNVERIFIED_NAME, dir_fd=output_fd)
                except FileNotFoundError:
                    pass
                raise
            finally:
                key = b""  # Not a guarantee of Python/OpenSSL memory erasure.
    return output_directory / S.ARCHIVE_NAME, output_directory / RECEIPT_NAME
