"""Resolve trusted bundled runtime files independently of the writable data root."""
from pathlib import Path
import shutil
import sys


def runtime_root():
    if getattr(sys, "frozen", False):
        # Frozen builds must never load executable code from a user's config,
        # working directory, PATH or environment-variable override.
        return Path(sys._MEIPASS).resolve() / "runtime"
    return Path(__file__).resolve().parents[3] / "runtime"


def sidecar_path():
    # PyInstaller macOS bundles link data from Frameworks into Resources. Node
    # resolves import.meta.url, but leaves argv[1] as supplied; the sidecar's
    # main-module check therefore needs the canonical file path in argv[1].
    return (runtime_root() / "pi" / "sidecar.mjs").resolve()


def node_executable():
    if getattr(sys, "frozen", False):
        relative = Path("node/node.exe") if sys.platform == "win32" else Path("node/bin/node")
        return str(runtime_root() / relative)
    return shutil.which("node")
