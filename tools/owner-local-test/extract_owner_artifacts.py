"""Bounded, fixed-name local extraction for the reviewed owner artifact layout.

Ciphertext transport only: this does not authenticate GCM or authorize delivery.
Exactly artifact 001 contains envelope + part001; all later artifacts one part.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import struct
import zipfile
import zlib

import receive_local as R
import seal_local as S

MAX_CENTRAL_DIRECTORY = 4096
EOCD = struct.Struct("<4s4H2LH")
LOCAL = struct.Struct("<4s5H3L2H")


@dataclass(frozen=True)
class Artifact:
    number: int
    name: str
    artifact_id: str
    run_id: str
    run_attempt: str
    size: int
    sha256: str


@dataclass(frozen=True)
class LocalArtifact:
    artifact_id: str
    path: Path


def artifact_name(number: int, workflow_commit: str) -> str:
    return f"owner-local-cipher-{number:03d}-{workflow_commit}"


def validate_artifacts(artifacts: tuple[Artifact, ...], expected: R.Expected):
    R._validate_expected(expected)
    layout = S.part_layout(expected.archive_size)
    if type(artifacts) is not tuple or len(artifacts) != len(layout):
        raise ValueError("Artifact count differs from independent plaintext bound")
    for number, artifact in enumerate(artifacts, 1):
        if (not isinstance(artifact, Artifact) or type(artifact.number) is not int
                or artifact.number != number
                or artifact.name != artifact_name(number, expected.workflow_commit)
                or not isinstance(artifact.artifact_id, str)
                or not re.fullmatch(r"[1-9][0-9]{0,19}", artifact.artifact_id)
                or artifact.run_id != expected.run_id or artifact.run_attempt != expected.run_attempt
                or type(artifact.size) is not int
                or not 0 < artifact.size <= R.TRANSFER_LIMIT
                or not R._hex(artifact.sha256, 64)):
            raise ValueError("Invalid independent fixed artifact descriptor")
    if len({item.artifact_id for item in artifacts}) != len(artifacts):
        raise ValueError("Duplicate trusted GitHub artifact identity")
    return layout


def _read_exact(stream, length):
    data = stream.read(length)
    if len(data) != length:
        raise ValueError("Truncated ZIP structure")
    return data


def _central_bounds(stream, size: int, wanted_count: int):
    # Read EOCD directly BEFORE ZipFile allocates central-directory objects.
    # No comments, trailers, multipart ZIPs, ZIP64 or self-extracting prefix.
    if size < EOCD.size:
        raise ValueError("Truncated ZIP")
    stream.seek(size - EOCD.size)
    signature, disk, start_disk, count_disk, count, length, offset, comment = EOCD.unpack(
        _read_exact(stream, EOCD.size))
    if (signature != b"PK\x05\x06" or disk != 0 or start_disk != 0
            or count_disk != wanted_count or count != wanted_count or comment != 0
            or not 0 < length <= MAX_CENTRAL_DIRECTORY
            or offset <= 0 or offset + length != size - EOCD.size
            or offset == 0xFFFFFFFF or length == 0xFFFFFFFF):
        raise ValueError("ZIP EOCD/count/bounds are outside fixed artifact format")
    return offset


def _checked_infos(stream, archive, central_offset, wanted):
    infos = archive.infolist()
    if (len(infos) != len(wanted)
            or {info.filename for info in infos} != set(wanted)):
        raise ValueError("Unknown, duplicate, missing or traversal ZIP entries")
    for info in infos:
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if (info.orig_filename != info.filename or "\x00" in info.orig_filename
                or "/" in info.filename or "\\" in info.filename
                or info.is_dir() or kind not in (0, stat.S_IFREG)
                or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or (info.compress_type == zipfile.ZIP_STORED and info.compress_size != info.file_size)
                or info.file_size > info.compress_size + 1024
                or info.flag_bits & ~(0x8 | 0x800)
                or info.extra or info.comment or info.volume != 0
                or info.extract_version not in (10, 20)):
            raise ValueError("Nonregular/compressed/encrypted/extended ZIP entry refused")
        limit = wanted[info.filename]
        if not 0 < info.file_size <= limit:
            raise ValueError("ZIP entry exceeds independently bounded size")
        if info.filename != S.ENVELOPE_NAME and info.file_size != limit:
            raise ValueError("Ciphertext part ZIP length differs from expected layout")
    # Require contiguous, nonoverlapping local records; unindexed payload and
    # duplicate local entries cannot hide between the central-directory entries.
    cursor = 0
    members = []
    for info in sorted(infos, key=lambda item: item.header_offset):
        if info.header_offset != cursor:
            raise ValueError("ZIP local records overlap or contain unindexed data")
        stream.seek(cursor)
        (signature, version, flags, method, _time, _date, crc,
         compressed, plain, name_length, extra_length) = LOCAL.unpack(_read_exact(stream, LOCAL.size))
        name = info.filename.encode("ascii")
        if (signature != b"PK\x03\x04" or version != info.extract_version
                or flags != info.flag_bits or method != info.compress_type
                or name_length != len(name) or extra_length != 0
                or _read_exact(stream, name_length) != name):
            raise ValueError("ZIP local/central headers disagree")
        if flags & 0x8:
            if crc not in (0, info.CRC) or compressed not in (0, info.compress_size) or plain not in (0, info.file_size):
                raise ValueError("Invalid streaming ZIP local sizes")
        elif (crc, compressed, plain) != (info.CRC, info.compress_size, info.file_size):
            raise ValueError("ZIP local CRC/size mismatch")
        members.append((info, stream.tell()))
        cursor = stream.tell() + info.compress_size
        if cursor > central_offset:
            raise ValueError("ZIP entry overlaps its central directory")
        if flags & 0x8:
            stream.seek(cursor)
            first = _read_exact(stream, 4)
            if first == b"PK\x07\x08":
                values = struct.unpack("<3L", _read_exact(stream, 12))
                cursor += 16
            else:
                values = struct.unpack("<3L", first + _read_exact(stream, 8))
                cursor += 12
            if values != (info.CRC, info.compress_size, info.file_size):
                raise ValueError("ZIP data descriptor disagrees with central directory")
    if cursor != central_offset:
        raise ValueError("Unexpected ZIP data between entries and central directory")
    return members


def _member_blocks(raw, info, offset):
    """Bounded raw inflation, checking true EOF/unused data instead of trusting
    a ZIP header's declared uncompressed size. Never allocate a full member.
    """
    raw.seek(offset)
    remaining, total, crc = info.compress_size, 0, 0
    inflater = zlib.decompressobj(-15) if info.compress_type == zipfile.ZIP_DEFLATED else None
    while remaining:
        pending = _read_exact(raw, min(S.IO_BLOCK_SIZE, remaining))
        remaining -= len(pending)
        while pending:
            previous = len(pending)
            if inflater is None:
                block, pending = pending, b""
            else:
                block = inflater.decompress(pending, min(S.IO_BLOCK_SIZE, info.file_size - total + 1))
                pending = inflater.unconsumed_tail
                if inflater.unused_data or (inflater.eof and (pending or remaining)):
                    raise ValueError("Trailing or concatenated deflate data refused")
                if not block and len(pending) >= previous:
                    raise ValueError("Deflate stream made no progress")
            total += len(block)
            if total > info.file_size:
                raise ValueError("Actual ZIP inflation exceeds declared independent bound")
            crc = zlib.crc32(block, crc)
            if block:
                yield block
    if inflater is not None and not inflater.eof:
        raise ValueError("Incomplete deflate stream")
    if total != info.file_size or crc != info.CRC:
        raise ValueError("Actual ZIP member size/CRC mismatch")


def extract_artifacts(artifacts: tuple[Artifact, ...], local_files: tuple[LocalArtifact, ...],
                      output_directory: Path, *, expected: R.Expected) -> tuple[Path, ...]:
    layout = validate_artifacts(artifacts, expected)
    if type(local_files) is not tuple or len(local_files) != len(artifacts):
        raise ValueError("Local ZIP map must exactly cover trusted artifact identities")
    mapping = {}
    for local in local_files:
        if not isinstance(local, LocalArtifact) or local.artifact_id in mapping:
            raise ValueError("Duplicate or invalid local artifact mapping")
        S._parts(local.path)
        mapping[local.artifact_id] = local.path
    if (set(mapping) != {item.artifact_id for item in artifacts}
            or len(set(mapping.values())) != len(mapping)):
        raise ValueError("Local map has missing/extra IDs or duplicate paths")
    S._parts(output_directory)
    created, identities = [], set()
    envelope = None
    with S._new_directory(output_directory) as output_fd:
        try:
            for artifact, part in zip(artifacts, layout):
                wanted = {part["name"]: part["size"]}
                if artifact.number == 1:
                    wanted[S.ENVELOPE_NAME] = R.MAX_ENVELOPE_SIZE
                # The arbitrary local basename is NEVER treated as identity.
                # Identity comes from receipt id/name/run + exact ZIP hash/size.
                with S._regular_input(mapping[artifact.artifact_id]) as raw:
                    before = S._identity(raw)
                    if before[:2] in identities:
                        raise ValueError("Multiple artifact IDs map to the same file inode")
                    identities.add(before[:2])
                    if before[2] != artifact.size or not 0 < before[2] <= R.TRANSFER_LIMIT:
                        raise ValueError("Actual ZIP file exceeds/mismatches independent size")
                    total, digest = 0, hashlib.sha256()
                    while block := raw.read(S.IO_BLOCK_SIZE):
                        total += len(block)
                        if total > artifact.size:
                            raise ValueError("ZIP grew beyond its transfer bound")
                        digest.update(block)
                    if total != artifact.size or digest.hexdigest() != artifact.sha256:
                        raise ValueError("ZIP does not match independently trusted SHA-256")
                    central_offset = _central_bounds(raw, artifact.size, len(wanted))
                    raw.seek(0)
                    with zipfile.ZipFile(raw) as archive:
                        members = _checked_infos(raw, archive, central_offset, wanted)
                        for info, offset in members:
                            if info.filename == S.ENVELOPE_NAME:
                                collected = bytearray()
                                for block in _member_blocks(raw, info, offset):
                                    if len(collected) + len(block) > R.MAX_ENVELOPE_SIZE:
                                        raise ValueError("Envelope expanded beyond bound")
                                    collected.extend(block)
                                envelope = bytes(collected)
                            else:
                                with S._new_file(output_fd, info.filename) as target:
                                    created.append(info.filename)
                                    for block in _member_blocks(raw, info, offset):
                                        target.write(block)
                                    target.flush()
                                    os.fsync(target.fileno())
                    if S._identity(raw) != before:
                        raise ValueError("ZIP changed during extraction")
            if envelope is None:
                raise ValueError("First ZIP did not provide the required envelope")
            # Completion envelope is created only after ALL ZIPs verify.
            with S._new_file(output_fd, S.ENVELOPE_NAME) as target:
                created.append(S.ENVELOPE_NAME)
                target.write(envelope)
                target.flush()
                os.fsync(target.fileno())
            names = [part["name"] for part in layout] + [S.ENVELOPE_NAME]
            if set(os.listdir(output_fd)) != set(names):
                raise ValueError("Extracted output differs from exact allowlist")
            os.fsync(output_fd)
        except BaseException:
            for name in created:
                try:
                    os.unlink(name, dir_fd=output_fd)
                except FileNotFoundError:
                    pass
            raise
    return tuple(output_directory / name for name in names)
