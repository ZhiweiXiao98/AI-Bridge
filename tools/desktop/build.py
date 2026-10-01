"""Build a minimal frozen remote client, never a release/upload operation.

No repository directory is copied as data. PyInstaller follows Python imports;
only the exact public LICENSE is added as repository data. Verified generated
license texts are added separately before platform signing. Runtime config and
panels use their code defaults, and missing decorative icons retain text labels.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

# 兼容直接执行和测试通过 spec_from_file_location 加载。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compliance import collect_inventory, prepare_notices

ROOT = Path(__file__).resolve().parents[2]
NAME = "AI-Bridge-Remote"
# Keep this explicit. Never add '.', assets/, docs/, lib/, a DB, a local config,
# a browser profile, a driver executable, or pack_dist.py's historical payload.
REPOSITORY_DATA = ("LICENSE",)
EXCLUDES = (
    "PyQt5", "PyQt6", "PySide2", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
    "chromadb", "fastembed", "docker", "selenium", "pyvis", "networkx",
    "app.core.knowledge.service", "app.core.knowledge.reindex_runner",
    "app.core.services.knowledge_service", "app.core.services.file_service",
    "app.core.worker", "app.core.agent_manager", "app.core.docker_manager",
)


# Check actual native filenames/framework paths, not only Python imports.
# This is a scope gate, not a complete dependency-license allowlist.
UNUSED_QT_COMPONENTS = (
    "qt6virtualkeyboard", "qtvirtualkeyboard", "qt6pdf", "qtpdf", "qpdf.",
    "qt6qml", "qtqml", "qt6quick", "qtquick",
)


def unexpected_native_files(files: list[dict]) -> list[str]:
    return [entry["path"] for entry in files
            if any(name in entry["path"].lower() for name in UNUSED_QT_COMPONENTS)]


def command(output: Path) -> list[str]:
    result = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
              "--onedir", "--windowed", "--noupx", "--name", NAME,
              "--distpath", str(output / "dist"),
              "--workpath", str(output / "work"),
              "--specpath", str(output),
              "--runtime-hook", str(ROOT / "tools/desktop/runtime_hook.py"),
              "--additional-hooks-dir", str(ROOT / "tools/desktop/hooks"),
              "--hidden-import", "app.core.app_constants",
              "--collect-submodules", "tiktoken_ext"]
    for relative in REPOSITORY_DATA:
        result.extend(["--add-data", f"{ROOT / relative}{__import__('os').pathsep}."])
    result.extend(["--add-data", f"{output / 'generated-notices'}{__import__('os').pathsep}THIRD_PARTY_NOTICES"])
    for module in EXCLUDES:
        result.extend(["--exclude-module", module])
    result.append(str(ROOT / "boot_remote.py"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/desktop")
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.print_command:
        print(json.dumps(command(output), indent=2))
        return
    output.mkdir(parents=True, exist_ok=True)
    report = output / "review"
    report.mkdir(exist_ok=True)
    dependencies = prepare_notices(ROOT, output)
    subprocess.run(command(output), cwd=ROOT, check=True)
    inventory = collect_inventory(ROOT, output, dependencies)
    unexpected = unexpected_native_files(inventory["files"])
    inventory["blocked_native_components"] = unexpected
    (report / "desktop-inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    if unexpected:
        raise SystemExit("Unused Qt native components entered the bundle: " + ", ".join(unexpected))
    print(f"Built {NAME}; binary upload remains disabled pending license review.")


if __name__ == "__main__":
    main()
