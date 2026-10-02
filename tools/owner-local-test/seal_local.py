"""BLOCKED DRAFT: local-only, streaming owner-test transport, protocol v2.

No upload, key generation for owners, installation, or distribution approval.
Production entry points refuse to run until all review pins/gates are edited.
See STREAMING_SEAL_REVIEW.md before any deployment.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import BinaryIO, Callable

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# Replacing these values requires a separately authorized, reviewed revision.
SOURCE_COMMIT = "d51dc1ef827912d84b90fee77ff84d6369588cc5"
RECIPIENT_PUBLIC_SHA256 = "a53faa294a2ba5c656af3f322c11c0c620950f2a54ed877a4842113cb04990db"
MATERIALS_MANIFEST_SHA256 = "c2f6a21e3bb435146b99be80977e9a93131e1e690628de7eef245bcff150f1ea"
PRODUCTION_SEALING_APPROVED = True
# Public SPKI fingerprint only. Its owner private key is lost; never reuse it.
RETIRED_RECIPIENT_SHA256 = "989664c0300174bf9d60b6b9d491c0cbbc3b323179386a4adc48979a291887f3"
ARCHIVE_NAME = "AI-Bridge-Local-macOS-ARM64-owner-test.dmg"
ENVELOPE_NAME = "owner-test-envelope.json"
VALIDATION_NAME = "owner-package-validation.json"
MAX_VALIDATION_SIZE = 16 * 1024
MAX_ENVELOPE_SIZE = 128 * 1024
AAD_LABEL = b"AI-Bridge owner-test transport v2\x00"
CHUNK_SIZE = 24 * 1024 * 1024
MAX_PARTS = 128
MAX_PLAINTEXT_SIZE = 3 * 1024 * 1024 * 1024
IO_BLOCK_SIZE = 1024 * 1024
TAG_SIZE = 16
MAX_PUBLIC_KEY_SIZE = 8192
ENCRYPTION = "AES-256-GCM + RSA-3072-OAEP-SHA256"


def canonical(value: object) -> bytes:
    # All producer-controlled values are ASCII, avoiding cross-language Unicode
    # canonicalization differences. Consumers must use these exact JSON rules.
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def part_layout(size: int) -> list[dict]:
    if type(size) is not int or not 0 < size <= MAX_PLAINTEXT_SIZE:
        raise ValueError("DMG must be nonempty and at most exactly 3 GiB")
    count = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
    if count > MAX_PARTS:
        raise ValueError("Ciphertext exceeds 128-part bound")
    return [{"name": f"owner-test.part{i:03d}.aesgcm",
             "size": min(CHUNK_SIZE, size - (i - 1) * CHUNK_SIZE)}
            for i in range(1, count + 1)]


def _parts(path: Path) -> tuple[str, ...]:
    # Paths must be absolute, with no parent traversal; never use resolve(),
    # which would silently accept symlinks. Every component is opened below.
    if not path.is_absolute() or path.anchor != "/" or ".." in path.parts:
        raise ValueError("Use an absolute POSIX path without parent traversal")
    if len(path.parts) < 2:
        raise ValueError("A filesystem root is not a file/output directory")
    return path.parts[1:]


@contextmanager
def _directory(path: Path):
    components = () if path == Path("/") else _parts(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for name in components:
            next_fd = os.open(name, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _regular_input(path: Path):
    _parts(path)
    with _directory(path.parent) as parent_fd:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                     os.O_NONBLOCK, dir_fd=parent_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Expected a regular, non-symlink file")
        stream = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    with stream:
        yield stream


@contextmanager
def _new_directory(path: Path):
    _parts(path)
    with _directory(path.parent) as parent_fd:
        # Existing directories and symlinks fail; parents are never created.
        os.mkdir(path.name, mode=0o700, dir_fd=parent_fd)
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                     os.O_CLOEXEC, dir_fd=parent_fd)
        try:
            identity = os.fstat(fd)
            yield fd
            current = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino):
                raise ValueError("Output directory was replaced")
        finally:
            os.close(fd)


def _new_file(directory_fd: int, name: str):
    if not name or "/" in name or name in {".", ".."}:
        raise ValueError("Output names must be fixed basenames")
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                 os.O_CLOEXEC, 0o600, dir_fd=directory_fd)
    return os.fdopen(fd, "wb")


def _identity(stream: BinaryIO) -> tuple[int, ...]:
    s = os.fstat(stream.fileno())
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


def _hash_plaintext(stream: BinaryIO) -> tuple[int, str]:
    digest, total = hashlib.sha256(), 0
    while data := stream.read(IO_BLOCK_SIZE):
        total += len(data)
        if total > MAX_PLAINTEXT_SIZE:
            raise ValueError("DMG grew past 3 GiB during hash pass")
        digest.update(data)
    part_layout(total)
    return total, digest.hexdigest()


def _manifest(size: int, plaintext_hash: str, recipient_hash: str,
              workflow_commit: str, run_id: str, run_attempt: str,
              validation: dict) -> dict:
    layout = part_layout(size)
    return {
        "schema": 2, "purpose": "private owner-requested installation test",
        "repository": "ZhiweiXiao98/AI-Bridge", "source_commit": SOURCE_COMMIT,
        "workflow_commit": workflow_commit, "run_id": run_id,
        "run_attempt": run_attempt, "filename": ARCHIVE_NAME, "size": size,
        "package_validation": validation,
        "package_validation_sha256": hashlib.sha256(canonical(validation)).hexdigest(),
        "sha256": plaintext_hash, "recipient_sha256": recipient_hash,
        "platform": "macOS", "architecture": "arm64",
        "developer_id_signed": False, "notarized": False,
        "binary_distribution_approved": False, "encryption": ENCRYPTION,
        "aad_encoding": "label || ASCII canonical JSON(manifest)",
        "tag_placement": "detached envelope.tag; not in parts",
        "tag_size": TAG_SIZE, "ciphertext_size": size + TAG_SIZE,
        "ciphertext_sha256_scope": "concat(parts in listed order) || tag",
        "chunk_bound": {"size": CHUNK_SIZE, "max_parts": MAX_PARTS,
                        "max_plaintext_size": MAX_PLAINTEXT_SIZE},
        "part_count": len(layout), "part_layout": layout,
        "output_files": [p["name"] for p in layout] + [ENVELOPE_NAME],
    }


class _ChunkWriter:
    """Bounded-memory writer: no chunk-sized buffer and no complete ciphertext."""
    def __init__(self, directory_fd: int, layout: list[dict]):
        self.directory_fd, self.layout = directory_fd, layout
        self.parts: list[dict] = []
        self.stream = None
        self.written = 0
        self.total = 0
        self.full_hash = hashlib.sha256()
        self.part_hash = hashlib.sha256()

    def write(self, data: bytes):
        remaining = memoryview(data)
        while remaining:
            if self.stream is None:
                if len(self.parts) >= len(self.layout):
                    raise ValueError("Ciphertext exceeds authenticated layout")
                self.written = 0
                self.part_hash = hashlib.sha256()
                self.stream = _new_file(self.directory_fd,
                                        self.layout[len(self.parts)]["name"])
            expected = self.layout[len(self.parts)]
            length = min(len(remaining), expected["size"] - self.written)
            piece, remaining = remaining[:length], remaining[length:]
            self.stream.write(piece)
            self.part_hash.update(piece)
            self.full_hash.update(piece)
            self.written += length
            self.total += length
            if self.written == expected["size"]:
                self.stream.flush()
                os.fsync(self.stream.fileno())
                self.stream.close()
                self.stream = None
                self.parts.append({**expected, "sha256": self.part_hash.hexdigest()})

    def finish(self, tag: bytes) -> tuple[list[dict], str]:
        if self.stream is not None or len(self.parts) != len(self.layout):
            raise ValueError("Ciphertext truncated relative to layout")
        if len(tag) != TAG_SIZE:
            raise ValueError("Expected a full 128-bit GCM tag")
        self.full_hash.update(tag)
        return self.parts, self.full_hash.hexdigest()

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def _encrypt_stream(stream: BinaryIO, emit: Callable[[bytes], None],
                    manifest: dict, key: bytes, nonce: bytes) -> bytes:
    """Internal primitive; tests supply PUBLIC zero fixtures, never real data."""
    if len(key) != 32 or len(nonce) != 12:
        raise ValueError("Expected AES-256 key and 96-bit nonce")
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(AAD_LABEL + canonical(manifest))
    digest, total = hashlib.sha256(), 0
    while plaintext := stream.read(IO_BLOCK_SIZE):
        total += len(plaintext)
        if total > manifest["size"]:
            raise ValueError("DMG grew between hash and encryption passes")
        digest.update(plaintext)
        emit(encryptor.update(plaintext))
    if total != manifest["size"] or digest.hexdigest() != manifest["sha256"]:
        raise ValueError("DMG changed between hash and encryption passes")
    emit(encryptor.finalize())
    return encryptor.tag


def _check_review_gates():
    if PRODUCTION_SEALING_APPROVED is not True:
        raise ValueError("DRAFT BLOCKED: local sealing has not been approved")
    if not re.fullmatch(r"[0-9a-f]{40}", SOURCE_COMMIT):
        raise ValueError("DRAFT BLOCKED: pin the newly approved source commit")
    if not re.fullmatch(r"[0-9a-f]{64}", RECIPIENT_PUBLIC_SHA256):
        raise ValueError("DRAFT BLOCKED: pin a NEW approved recipient SPKI SHA256")
    if RECIPIENT_PUBLIC_SHA256 == RETIRED_RECIPIENT_SHA256:
        raise ValueError("The retired owner public key is forbidden")
    if not re.fullmatch(r"[0-9a-f]{64}", MATERIALS_MANIFEST_SHA256):
        raise ValueError("DRAFT BLOCKED: pin the independently approved materials manifest")


def _load_recipient(public_path: Path):
    with _regular_input(public_path) as stream:
        public_bytes = stream.read(MAX_PUBLIC_KEY_SIZE + 1)
    if len(public_bytes) > MAX_PUBLIC_KEY_SIZE or b"PRIVATE" in public_bytes:
        raise ValueError("Only a bounded public recipient key is allowed")
    public_key = serialization.load_pem_public_key(public_bytes)
    if (not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size != 3072
            or public_key.public_numbers().e != 65537):
        raise ValueError("Expected an RSA-3072 public key with exponent 65537")
    der = public_key.public_bytes(serialization.Encoding.DER,
                                  serialization.PublicFormat.SubjectPublicKeyInfo)
    fingerprint = hashlib.sha256(der).hexdigest()
    if fingerprint == RETIRED_RECIPIENT_SHA256 or fingerprint != RECIPIENT_PUBLIC_SHA256:
        raise ValueError("Recipient public key does not match the NEW approved pin")
    return public_key, fingerprint



def _unique_json_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate validation JSON key")
        result[name] = value
    return result


def _load_validation(path: Path, archive_size: int, archive_hash: str) -> dict:
    if path.name != VALIDATION_NAME:
        raise ValueError("Expected the fixed owner-package-validation.json filename")
    with _regular_input(path) as stream:
        data = stream.read(MAX_VALIDATION_SIZE + 1)
    if len(data) > MAX_VALIDATION_SIZE:
        raise ValueError("Validation summary exceeds its fixed size bound")
    def reject_constant(value):
        raise ValueError("Non-finite validation JSON value")
    value = json.loads(data, object_pairs_hook=_unique_json_object,
                       parse_constant=reject_constant)
    return _validate_validation(value, archive_size, archive_hash, SOURCE_COMMIT,
                                MATERIALS_MANIFEST_SHA256)


def _validate_validation(value: object, archive_size: int, archive_hash: str,
                         source_commit: str, materials_manifest_sha256: str) -> dict:
    allowed = {"schema_version", "source_commit", "filename", "archive_sha256",
               "archive_size", "app_regular_file_count", "app_regular_bytes",
               "mounted_full_smoke_passed", "mounted_native_gui_passed",
               "byte_mode_link_roundtrip", "materials_manifest_sha256",
               "developer_id_signed", "notarized", "binary_distribution_approved"}
    if not isinstance(value, dict) or set(value) != allowed:
        raise ValueError("Validation summary must contain exactly the safe allowlisted fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported package validation schema")
    if value["filename"] != ARCHIVE_NAME:
        raise ValueError("Validation DMG filename does not match the fixed name")
    if (type(value["app_regular_file_count"]) is not int
            or not 0 < value["app_regular_file_count"] <= 60000
            or type(value["app_regular_bytes"]) is not int
            or not 0 < value["app_regular_bytes"] <= 4 * 1024**3):
        raise ValueError("Invalid bounded application inventory summary")
    if (not isinstance(value["materials_manifest_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["materials_manifest_sha256"])
            or value["materials_manifest_sha256"] != materials_manifest_sha256):
        raise ValueError("Validation materials do not match the independently approved pin")
    if (not isinstance(value["source_commit"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", value["source_commit"])
            or value["source_commit"] != source_commit):
        raise ValueError("Validation source does not match the approved source pin")
    if (type(value["archive_size"]) is not int
            or value["archive_size"] != archive_size
            or value["archive_sha256"] != archive_hash
            or not isinstance(value["archive_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["archive_sha256"])):
        raise ValueError("Validation summary does not match actual DMG hash/size")
    for field in ("mounted_full_smoke_passed", "mounted_native_gui_passed",
                  "byte_mode_link_roundtrip"):
        if value[field] is not True:
            raise ValueError("Required mounted/roundtrip package validation is not passed")
    for field in ("developer_id_signed", "notarized", "binary_distribution_approved"):
        if value[field] is not False:
            raise ValueError("Unsigned, unnotarized and binary-distribution-false gates must remain explicit")
    return value


def seal(archive: Path, public_path: Path, output: Path, *, workflow_commit: str,
         run_id: str, validation_path: Path, run_attempt: str = "1") -> tuple[Path, ...]:
    _check_review_gates()  # Before any input access, directory creation or RNG.
    if archive.name != ARCHIVE_NAME:
        raise ValueError("Expected the exact complete-client owner-test DMG name")
    if (not re.fullmatch(r"[0-9a-f]{40}", workflow_commit)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", run_id)
            or not re.fullmatch(r"[1-9][0-9]{0,5}", run_attempt)):
        raise ValueError("Invalid build provenance")
    _parts(archive)
    _parts(public_path)
    _parts(output)
    _parts(validation_path)
    public_key, recipient_hash = _load_recipient(public_path)
    with _regular_input(archive) as source:
        before = _identity(source)
        part_layout(before[2])
        size, plaintext_hash = _hash_plaintext(source)
        if _identity(source) != before or size != before[2]:
            raise ValueError("DMG changed during hash pass")
        validation = _load_validation(validation_path, size, plaintext_hash)
        manifest = _manifest(size, plaintext_hash, recipient_hash,
                             workflow_commit, run_id, run_attempt, validation)
        source.seek(0)
        # Only authorized synthetic interoperability tests exercise this branch
        # by temporarily patching review pins in memory; disk gates stay blocked.
        # A fresh ephemeral AES key and nonce must be used for every attempt.
        key, nonce = os.urandom(32), os.urandom(12)
        wrapped = public_key.encrypt(key, padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(),
            label=AAD_LABEL))
        if len(wrapped) != 384:
            raise ValueError("Unexpected RSA-3072 wrapped-key size")
        with _new_directory(output) as directory_fd:
            writer = _ChunkWriter(directory_fd, manifest["part_layout"])
            try:
                tag = _encrypt_stream(source, writer.write, manifest, key, nonce)
                if _identity(source) != before:
                    raise ValueError("DMG metadata changed during encryption")
                parts, ciphertext_hash = writer.finish(tag)
                envelope = {"manifest": manifest,
                            "nonce": base64.b64encode(nonce).decode("ascii"),
                            "wrapped_key": base64.b64encode(wrapped).decode("ascii"),
                            "tag": base64.b64encode(tag).decode("ascii"),
                            "ciphertext_sha256": ciphertext_hash, "parts": parts}
                # The envelope is the completion marker; never emit it on failure.
                if set(os.listdir(directory_fd)) != {p["name"] for p in parts}:
                    raise ValueError("Unexpected output before envelope creation")
                envelope_bytes = canonical(envelope) + b"\n"
                if len(envelope_bytes) > MAX_ENVELOPE_SIZE:
                    raise ValueError("Envelope exceeds fixed 128 KiB transport bound")
                with _new_file(directory_fd, ENVELOPE_NAME) as target:
                    target.write(envelope_bytes)
                    target.flush()
                    os.fsync(target.fileno())
                os.fsync(directory_fd)
                if set(os.listdir(directory_fd)) != set(manifest["output_files"]):
                    raise ValueError("Output directory does not match exact allowlist")
            except BaseException:
                writer.close()
                # Remove only the fixed envelope completion marker if written.
                # Incomplete ciphertext may remain; never recursively delete or
                # offer it for upload. A retry must use a fresh directory/key/nonce.
                try:
                    os.unlink(ENVELOPE_NAME, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
                raise
            finally:
                writer.close()
                # Python/OpenSSL do NOT guarantee wiping key material from memory.
                key = b""
    return tuple(output / name for name in manifest["output_files"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--workflow-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", default="1")
    args = parser.parse_args()
    paths = seal(args.archive, args.public_key, args.output,
                 workflow_commit=args.workflow_commit, run_id=args.run_id,
                 validation_path=args.validation,
                 run_attempt=args.run_attempt)
    print(json.dumps({"output_files": [str(p) for p in paths],
                      "binary_distribution_approved": False,
                      "upload_authorized": False}, sort_keys=True))


if __name__ == "__main__":
    main()
