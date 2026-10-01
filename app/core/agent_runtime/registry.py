"""Honest capability discovery: installation is separate from credential validation."""
import json
from pathlib import Path
import shutil
import os
import subprocess

PI_VERSION = "0.99.1"


def runtime_options():
    root = Path(__file__).resolve().parents[3] / "runtime" / "pi"
    package = root / "node_modules" / "@earendil-works" / "pi-coding-agent" / "package.json"
    available = False
    reason = "Install the pinned Pi runtime with npm ci in runtime/pi; Node.js >=22.19.0 required"
    try:
        node = shutil.which("node")
        version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=3,
                                 env={k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR") if k in os.environ}) if node else None
        supported = bool(version and version.returncode == 0 and
                         tuple(int(v) for v in version.stdout.strip().lstrip("v").split(".")) >= (22, 19, 0))
        available = supported and (root / "sidecar.mjs").is_file() and json.loads(package.read_text())["version"] == PI_VERSION
        if available:
            reason = "Installed; provider credentials are validated only when explicitly running a request"
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        pass
    return [
        {"id": "pi", "label": "Pi", "available": available, "reason": reason,
         "capabilities": {"stream": True, "cancel": True, "approval": True, "resume": True, "tools": True}},
        {"id": "legacy", "label": "Legacy API", "available": True, "reason": "Existing API conversations",
         "capabilities": {"stream": True, "cancel": True, "approval": False, "resume": False, "tools": True}},
        *[{"id": key, "label": label, "available": False, "reason": "Adapter not yet implemented or validated; no service connection will be attempted",
           "capabilities": {"stream": False, "cancel": False, "approval": False, "resume": False, "tools": False}}
          for key, label in (("codex", "Codex"), ("claude", "Claude Agent"), ("remote", "Remote agent"))],
    ]
