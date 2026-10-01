"""Exercise the built login window in fresh temporary state with a hard timeout."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=Path("build/desktop"))
parser.add_argument("--expect-recombination-marker")
args = parser.parse_args()
root = args.output.resolve() / "dist"
if sys.platform == "darwin":
    executable = root / "AI-Bridge-Remote.app/Contents/MacOS/AI-Bridge-Remote"
elif sys.platform == "win32":
    executable = root / "AI-Bridge-Remote/AI-Bridge-Remote.exe"
else:
    executable = root / "AI-Bridge-Remote/AI-Bridge-Remote"
with tempfile.TemporaryDirectory(prefix="ai-bridge-smoke-") as state:
    env = os.environ.copy()
    env.update(AI_BRIDGE_CLIENT_HOME=state, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([str(executable), "--desktop-smoke-test"],
                            cwd=state, env=env, timeout=90, check=True)
    marker = Path(state) / "desktop-smoke-ok.txt"
    if marker.read_text(encoding="utf-8") != "login-window-ok\n":
        raise RuntimeError("The frozen login-window smoke test did not complete")
    runtime = json.loads((Path(state) / "desktop-runtime.json").read_text(encoding="utf-8"))
    if runtime["recombination_marker"] != args.expect_recombination_marker:
        raise RuntimeError("重新组合后的 PySide 支持模块标记不匹配")
    inventory_path = args.output.resolve() / "review/desktop-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    expected = inventory["runtime_build_environment"]
    if runtime["python"] != expected["python"] or runtime["qt"] != expected["qt"]:
        raise RuntimeError("冻结运行时与构建环境版本不一致")
    inventory["frozen_runtime_probe"] = runtime
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
print("Frozen remote-client import/login smoke test passed (no server login attempted).")
