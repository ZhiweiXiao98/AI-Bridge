"""Seal an owner-requested test package; only ciphertext may leave the runner.

This is transport confidentiality, not binary-distribution/legal clearance.
The corresponding private key never exists on the build runner.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SOURCE_COMMIT = "415309cd195973fa495efecff4a7a0dcb3d56f02"
ARCHIVE_NAME = "AI-Bridge-Remote-macOS-ARM64-owner-test.dmg"
AAD_LABEL = b"AI-Bridge owner-test transport v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def seal(archive: Path, public_path: Path, output: Path, workflow_commit: str, run_id: str):
    if archive.name != ARCHIVE_NAME or archive.is_symlink() or not archive.is_file():
        raise ValueError("Expected the exact verified DMG file")
    if not re.fullmatch(r"[0-9a-f]{40}", workflow_commit) or not run_id.isdigit():
        raise ValueError("Invalid build provenance")
    public_bytes = public_path.read_bytes()
    if len(public_bytes) > 8192 or b"PRIVATE" in public_bytes:
        raise ValueError("Only a public recipient key is allowed")
    public_key = serialization.load_pem_public_key(public_bytes)
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size != 3072:
        raise ValueError("Expected an RSA-3072 public key")
    plaintext = archive.read_bytes()
    if not 0 < len(plaintext) <= 1_500_000_000:
        raise ValueError("Package size outside the fixed delivery limit")
    public_der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    manifest = {
        "schema": 1, "purpose": "private owner-requested installation test",
        "repository": "ZhiweiXiao98/AI-Bridge", "source_commit": SOURCE_COMMIT,
        "workflow_commit": workflow_commit, "run_id": run_id,
        "filename": ARCHIVE_NAME, "size": len(plaintext),
        "sha256": hashlib.sha256(plaintext).hexdigest(),
        "recipient_sha256": hashlib.sha256(public_der).hexdigest(),
        "platform": "macOS", "architecture": "arm64",
        "developer_id_signed": False, "notarized": False,
        "binary_distribution_approved": False,
        "encryption": "AES-256-GCM + RSA-3072-OAEP-SHA256",
    }
    aes_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    aad = AAD_LABEL + canonical(manifest)
    ciphertext = AESGCM(aes_key).encrypt(nonce, plaintext, aad)
    wrapped = public_key.encrypt(aes_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=AAD_LABEL))
    envelope = {"manifest": manifest, "nonce": base64.b64encode(nonce).decode("ascii"),
                "wrapped_key": base64.b64encode(wrapped).decode("ascii"),
                "ciphertext_sha256": hashlib.sha256(ciphertext).hexdigest()}
    # A new, dedicated directory and explicit filenames prevent upload glob leaks.
    output.mkdir(parents=True, exist_ok=False)
    (output / "owner-test.dmg.aesgcm").write_bytes(ciphertext)
    (output / "owner-test-envelope.json").write_bytes(canonical(envelope) + b"\n")
    print("Owner test package sealed; public binary-release approval remains false.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    seal(args.archive, args.public_key, args.output, os.environ["GITHUB_SHA"], os.environ["GITHUB_RUN_ID"])
