"""在一次性构建环境中验证修改过的 LGPL PySide 支持代码确实进入并运行于 PYZ。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MARKER = "ai-bridge-public-recombination-probe-v1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/desktop-recombination")
    parser.add_argument("--baseline", type=Path, default=ROOT / "build/desktop")
    args = parser.parse_args()
    # 必须明确隔离，避免修改系统 Python；原始字节在 finally 恢复。
    if sys.prefix == sys.base_prefix:
        raise SystemExit("请在一次性的 venv 中运行此测试，不能修改系统安装")
    source = Path(importlib.util.find_spec("PySide6.support.deprecated").origin)
    original = source.read_bytes()
    if MARKER.encode() in original:
        raise SystemExit("此环境已有测试修改，请使用干净 venv")
    modified = original + f'\nAI_BRIDGE_RECOMBINATION_MARKER = {MARKER!r}\n'.encode()
    args.output.mkdir(parents=True, exist_ok=True)
    install_report = args.baseline / "install-report.json"
    if install_report.is_file():
        shutil.copyfile(install_report, args.output / "install-report.json")
    try:
        source.write_bytes(modified)
        subprocess.run([sys.executable, str(ROOT / "tools/desktop/build.py"),
                        "--output", str(args.output)], cwd=ROOT, check=True)
        subprocess.run([sys.executable, str(ROOT / "tools/desktop/smoke.py"),
                        "--output", str(args.output), "--expect-recombination-marker", MARKER],
                       cwd=ROOT, check=True)
        proof = {
            "status": "passed", "modified_component": "PySide6.support.deprecated",
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "modified_sha256": hashlib.sha256(modified).hexdigest(), "observed_marker": MARKER,
            "scope": "PySide LGPL Python 支持模块重新组合；不等于 Qt 原生共享库替换验证",
            "private_signing_key_required": False, "binary_distribution_approved": False,
        }
        (args.baseline / "review/recombination-test.json").write_text(
            json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        source.write_bytes(original)
        # 避免留下已修改源码的字节码；仅删除本次触及模块的缓存。
        cache = Path(importlib.util.cache_from_source(str(source)))
        if cache.exists():
            cache.unlink()


if __name__ == "__main__":
    main()
