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
    return runtime_root() / "pi" / "sidecar.mjs"


def node_executable():
    if getattr(sys, "frozen", False):
        relative = Path("node/node.exe") if sys.platform == "win32" else Path("node/bin/node")
        return str(runtime_root() / relative)
    return shutil.which("node")
