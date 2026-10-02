"""Real Node regression for PyInstaller's macOS Frameworks/Resources symlinks.

Only the credential-free `close` protocol command runs: no SDK initialization,
provider request, tool execution, or network access is needed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.core.agent_runtime import PiRuntime
from app.core.agent_runtime import paths


@pytest.mark.parametrize("link_kind", ["directory", "entrypoint"])
def test_frozen_symlinked_sidecar_starts_real_node_protocol(tmp_path, monkeypatch, link_kind):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required for the real entrypoint regression")
    source = Path(__file__).resolve().parents[1] / "runtime" / "pi"
    contents = tmp_path / "AI Bridge.app" / "Contents"
    resources = contents / "Resources" / "runtime" / "pi"
    frameworks = contents / "Frameworks"
    resources.mkdir(parents=True)
    frameworks.mkdir()
    for name in ("sidecar.mjs", "pi-session.mjs", "protocol.mjs"):
        shutil.copy2(source / name, resources / name)
    try:
        if link_kind == "directory":
            (frameworks / "runtime").symlink_to(Path("../Resources/runtime"), target_is_directory=True)
        else:
            (frameworks / "runtime" / "pi").mkdir(parents=True)
            (frameworks / "runtime" / "pi" / "sidecar.mjs").symlink_to(
                Path("../../../Resources/runtime/pi/sidecar.mjs")
            )
    except OSError as exc:
        if os.name == "nt":
            pytest.skip(f"Windows host does not allow creating macOS-style symlinks: {exc}")
        raise

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(frameworks), raising=False)
    monkeypatch.setenv("PI_SIDECAR_PATH", str(tmp_path / "untrusted.mjs"))
    resolved = paths.sidecar_path()
    assert resolved == resources / "sidecar.mjs"
    assert PiRuntime().command[1] == str(resolved)
    assert not resolved.is_symlink()

    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR") if key in os.environ}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), TMPDIR=str(tmp_path))
    result = subprocess.run(
        [node, str(resolved)],
        input=json.dumps({"id": "symlink-entrypoint", "type": "close"}) + "\n",
        capture_output=True, text=True, encoding="utf-8", timeout=10,
        cwd=tmp_path, env=env,
    )
    assert result.returncode == 0
    packets = [json.loads(line) for line in result.stdout.splitlines()]
    assert packets == [{"id": "symlink-entrypoint", "type": "response", "command": "close", "success": True}]
