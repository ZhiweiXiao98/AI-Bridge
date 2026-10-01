"""Build a minimal frozen remote client, never a release/upload operation.

No repository directory is copied as data. PyInstaller follows Python imports;
only the exact public LICENSE is added as repository data. Runtime config and
panels use their code defaults, and missing decorative icons retain text labels.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

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
    for module in EXCLUDES:
        result.extend(["--exclude-module", module])
    result.append(str(ROOT / "boot_remote.py"))
    return result


def collect_notices(destination: Path) -> list[dict]:
    """Preserve installed exact-version license/notice texts, not just identifiers.

    This is review input, NOT a claim of complete binary redistribution compliance.
    The workflow deliberately does not upload the binary pending that review.
    """
    records = []
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata.get("Name", "").lower()):
        name = dist.metadata.get("Name", "unknown")
        target = destination / f"{name}-{dist.version}"
        target.mkdir(parents=True, exist_ok=True)
        (target / "METADATA.txt").write_text(dist.read_text("METADATA") or "", encoding="utf-8")
        copied = []
        for path in dist.files or ():
            parts = path.parts
            if ".." in parts or path.is_absolute():
                continue
            low = str(path).lower()
            if not any(word in low for word in ("license", "licence", "copying", "notice", "sbom")):
                continue
            source = Path(dist.locate_file(path))
            if source.is_file():
                out = target.joinpath(*parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, out)
                copied.append(str(path))
        records.append({"name": name, "version": dist.version, "notice_files": copied})
    return records


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
    dependencies = collect_notices(output / "dependency-notices")
    subprocess.run(command(output), cwd=ROOT, check=True)
    files = []
    for path in sorted((output / "dist").rglob("*")):
        if path.is_file():
            files.append({"path": path.relative_to(output / "dist").as_posix(),
                          "size": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    unexpected = unexpected_native_files(files)
    (report / "desktop-inventory.json").write_text(json.dumps({
        "entry_point": "boot_remote.py", "platform": sys.platform,
        "repository_data": list(REPOSITORY_DATA), "dependencies": dependencies,
        "binary_distribution_approved": False, "files": files,
        "blocked_native_components": unexpected,
    }, indent=2), encoding="utf-8")
    if unexpected:
        raise SystemExit("Unused Qt native components entered the bundle: " + ", ".join(unexpected))
    print(f"Built {NAME}; binary upload remains disabled pending license review.")


if __name__ == "__main__":
    main()
