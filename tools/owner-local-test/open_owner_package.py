"""本地本人测试包接收入口草案：门禁未批准时拒绝运行。

独立收据及其固定SHA-256先于任何私钥加载。CLI不接受私钥、私钥路径、
口令或密钥环境变量；仅在本人交互终端隐藏输入，绝不上传或打印秘密。
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import getpass
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import warnings

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import extract_owner_artifacts as E
import receive_local as R
import seal_local as S

OWNER_RECEIVE_APPROVED = False
TRUSTED_RECEIPT_SHA256 = "TBD"
RECEIPT_NAME = "owner-delivery-receipt.json"
MAX_RECEIPT_SIZE = 64 * 1024
MAX_PRIVATE_KEY_FILE = 32 * 1024
MAX_LOCAL_MAP_SIZE = 64 * 1024


@dataclass(frozen=True)
class DeliveryReceipt:
    expected: R.Expected
    artifacts: tuple[E.Artifact, ...]


def load_trusted_receipt(path: Path) -> DeliveryReceipt:
    if OWNER_RECEIVE_APPROVED is not True or not R._hex(TRUSTED_RECEIPT_SHA256, 64):
        raise ValueError("DRAFT BLOCKED: owner接收授权及独立收据固定hash尚未批准")
    if path.name != RECEIPT_NAME:
        raise ValueError("必须使用固定独立收据文件名")
    with S._regular_input(path) as stream:
        before = S._identity(stream)
        data = stream.read(MAX_RECEIPT_SIZE + 1)
        if S._identity(stream) != before:
            raise ValueError("独立收据读取期间发生变化")
    if len(data) > MAX_RECEIPT_SIZE or hashlib.sha256(data).hexdigest() != TRUSTED_RECEIPT_SHA256:
        raise ValueError("独立收据超限或不符合可信渠道提供的固定hash")
    def reject_constant(value):
        raise ValueError("收据不能包含非有限数值")
    value = json.loads(data, object_pairs_hook=S._unique_json_object, parse_constant=reject_constant)
    fields = {"schema_version", "filename", "source_commit", "workflow_commit", "run_id",
              "run_attempt", "recipient_sha256", "materials_manifest_sha256", "archive_size",
              "archive_sha256", "artifacts", "binary_distribution_approved"}
    if (not isinstance(value, dict) or set(value) != fields
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["filename"] != S.ARCHIVE_NAME
            or value["binary_distribution_approved"] is not False):
        raise ValueError("独立收据schema/字段/发行门禁无效")
    expected = R.Expected(**{name: value[name] for name in R.Expected.__dataclass_fields__})
    R._check_review_gates(expected)  # Core source/new-recipient/materials pins.
    if not isinstance(value["artifacts"], list) or not 1 <= len(value["artifacts"]) <= S.MAX_PARTS:
        raise ValueError("独立ZIP清单数量不符")
    artifacts = []
    for record in value["artifacts"]:
        if not isinstance(record, dict) or set(record) != {"number", "name", "artifact_id", "run_id", "run_attempt", "size", "sha256"}:
            raise ValueError("ZIP收据包含未知或缺失字段")
        artifacts.append(E.Artifact(**record))
    result = DeliveryReceipt(expected, tuple(artifacts))
    E.validate_artifacts(result.artifacts, result.expected)
    return result


def load_local_map(path: Path) -> tuple[E.LocalArtifact, ...]:
    with S._regular_input(path) as stream:
        data = stream.read(MAX_LOCAL_MAP_SIZE + 1)
    if len(data) > MAX_LOCAL_MAP_SIZE:
        raise ValueError("本地ZIP路径映射超限")
    def reject_constant(value):
        raise ValueError("本地映射包含非法数值")
    value = json.loads(data, object_pairs_hook=S._unique_json_object, parse_constant=reject_constant)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "artifacts"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or not isinstance(value["artifacts"], list)
            or not 1 <= len(value["artifacts"]) <= S.MAX_PARTS):
        raise ValueError("本地ZIP映射结构无效")
    items = []
    for item in value["artifacts"]:
        if (not isinstance(item, dict) or set(item) != {"artifact_id", "path"}
                or not isinstance(item["artifact_id"], str) or not isinstance(item["path"], str)):
            raise ValueError("本地ZIP映射字段无效")
        items.append(E.LocalArtifact(item["artifact_id"], Path(item["path"])))
    return tuple(items)


def _recover(receipt_path: Path, local_files: tuple[E.LocalArtifact, ...], output_directory: Path, key_provider):
    receipt = load_trusted_receipt(receipt_path)  # BEFORE key-provider invocation.
    S._parts(output_directory)
    with S._new_directory(output_directory):
        sealed = output_directory / "sealed"
        verified = output_directory / "verified"
        E.extract_artifacts(receipt.artifacts, local_files, sealed, expected=receipt.expected)
        # Reject malformed/wrong-context envelope before prompting for any key.
        with S._directory(sealed) as fd:
            R._validated_envelope(R._parse_envelope(fd), receipt.expected)
        private_key = key_provider()
        try:
            return R.receive(sealed, verified, private_key=private_key, expected=receipt.expected)
        finally:
            private_key = None  # No guarantee of Python/OpenSSL memory erasure.


def recover_with_key(receipt_path: Path, local_files: tuple[E.LocalArtifact, ...],
                     output_directory: Path, *, private_key: rsa.RSAPrivateKey):
    """Local in-process API. The private-key object is never serialized/logged."""
    return _recover(receipt_path, local_files, output_directory, lambda: private_key)


def _interactive_private_key():
    # This owner-only path is NOT exercised by the synthetic test suite. A user
    # runs it locally after separately reviewed final provenance pins are set.
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ValueError("私钥加载只允许本人交互终端，不接受管道输入")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        key_path = Path(getpass.getpass("本地私钥绝对物理路径（隐藏输入）："))
        with S._regular_input(key_path) as stream:
            metadata = os.fstat(stream.fileno())
            if (metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) not in (0o400, 0o600)
                    or metadata.st_nlink != 1):
                raise ValueError("私钥必须由当前本人账户独占，权限0400/0600且无额外硬链接")
            data = stream.read(MAX_PRIVATE_KEY_FILE + 1)
        if len(data) > MAX_PRIVATE_KEY_FILE or b"PRIVATE KEY" not in data:
            raise ValueError("本地私钥格式或大小不符合固定上限")
        text = getpass.getpass("私钥口令（隐藏输入；未加密则直接回车）：")
        password = text.encode("utf-8") if text else None
        text = ""
        try:
            key = serialization.load_pem_private_key(data, password=password)
        finally:
            data = b""
            password = None
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 3072:
            raise ValueError("只接受本人已持有的RSA-3072私钥")
        return key


class _PrivateSafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "参数无效；私钥、私钥路径和口令不能放入命令行。\n")


def main():
    parser = _PrivateSafeParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True, help="独立可信收据，不可来自加密封套")
    parser.add_argument("--artifact-map", type=Path, required=True, help="GitHub artifact ID到本地ZIP路径的显式映射")
    parser.add_argument("--output", type=Path, required=True, help="必须不存在的新输出目录")
    args = parser.parse_args()
    try:
        load_trusted_receipt(args.receipt)  # Approval/receipt gate before local map or owner input.
        local_files = load_local_map(args.artifact_map)
        dmg, _receipt = _recover(args.receipt, local_files, args.output, _interactive_private_key)
    except (Exception, KeyboardInterrupt):
        # Do not print exception repr/traceback: path/password/key errors may
        # contain sensitive local context. No secret can enter arguments/logs.
        print("接收失败或已取消；未确认的文件不能安装。请核对审批门禁、可信收据和本地文件。", file=sys.stderr)
        return 1
    print(f"已完成认证及明文校验：{dmg}")
    print("公开二进制发行仍未批准；本步骤不会安装、运行或上传应用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
