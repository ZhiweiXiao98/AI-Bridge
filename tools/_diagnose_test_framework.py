
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/workspace")
LOG_FILE = ROOT / "tools" / "_diagnose_test_framework.log"

TARGET_FILES = [
    "tests/conftest.py",
    "pytest.ini",
    "tests/test_ui_logic.py",
    "tests/test_remote_protocol.py",
    "tests/test_ui_startup_lock.py",
    "tests/test_server_dual_channel.py",
]

def log(msg: str):
    print(msg, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(msg + "\\n")

def header(title: str):
    line = "=" * 100
    log(f"\\n{line}\\n{title}\\n{line}")

def print_file(path: Path):
    header(f"[FILE] {path}")
    if not path.exists():
        log("❌ FILE NOT FOUND")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    log(f"行数: {len(lines)}")
    log("-" * 100)
    log(text)

def run_cmd_stream(cmd):
    header(f"[CMD] {' '.join(cmd)}")
    start = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip("\\n"))
    code = proc.wait()
    cost = time.time() - start
    log(f"[EXIT] {code} | elapsed={cost:.2f}s")
    return code

def main():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text("", encoding="utf-8")
    log("🔍 开始诊断测试框架（实时输出 + 文件快照 + pytest日志）")

    for rel in TARGET_FILES:
        print_file(ROOT / rel)

    run_cmd_stream([sys.executable, "-m", "pytest", "tests/", "-q"])
    run_cmd_stream([sys.executable, "-m", "pytest", "tests/", "-vv", "--maxfail=20"])
    run_cmd_stream([sys.executable, "-m", "pytest", "tests/test_ui_logic.py", "-vv"])
    run_cmd_stream([sys.executable, "-m", "pytest", "tests/test_remote_protocol.py", "-vv"])
    run_cmd_stream([sys.executable, "-m", "pytest", "tests/test_ui_startup_lock.py", "-vv"])
    run_cmd_stream([sys.executable, "-m", "pytest", "tests/test_server_dual_channel.py", "-vv"])

    header("✅ 诊断完成")
    log(f"日志文件: {LOG_FILE}")

if __name__ == "__main__":
    main()
