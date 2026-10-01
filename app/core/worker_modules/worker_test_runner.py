# filename: app/core/worker_modules/worker_test_runner.py
from __future__ import annotations

import os
import re
import subprocess
import sys

from app.core.logging import get_logger
from app.core.project_context import ProjectContext

logger = get_logger("app.core.worker.test_runner", side="worker")


class WorkerTestRunnerBridge:
    """Run project pytest in the background and project results to the UI."""

    def __init__(self, worker):
        self.worker = worker

    def run_remote_tests(self, client_id="Host", **kwargs):
        self.worker.safe_emit_status("🧪 [测试] 正在后台运行 pytest...")
        self.run_tests_bg(client_id)

    def run_tests_bg(self, client_id):
        worker = self.worker
        cwd = ProjectContext.get().get_project_root()
        cmd = [sys.executable, "-m", "pytest", "tests/", "-v"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=cwd,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            full_log = []
            logger.info("TestRunner: 开始执行 pytest...")

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                logger.debug("测试日志: %s", line)
                full_log.append(line)

            process.wait()

            result_payload = self.build_result_payload(client_id, full_log)
            worker.test_result_signal.emit(result_payload)
            worker.safe_emit_status(
                f"✅ [测试完成] Pass: {result_payload['passed']}, Fail: {result_payload['failed']}"
            )

        except Exception as exc:
            err_msg = f"测试启动失败: {exc}"
            logger.error(err_msg)
            worker.test_result_signal.emit(
                {
                    "target_client_id": client_id,
                    "passed": 0,
                    "failed": 1,
                    "duration": "0",
                    "full_log": err_msg,
                }
            )

    def build_result_payload(self, client_id, full_log):
        full_text = "\n".join(full_log or [])
        passed = full_text.count("PASSED")
        failed = full_text.count("FAILED")
        error = full_text.count("ERROR")

        duration = "0"
        last_line = full_text.splitlines()[-1] if full_log else ""
        match = re.search(r"in ([\d\.]+)s", last_line)
        if match:
            duration = match.group(1)

        return {
            "target_client_id": client_id,
            "passed": passed,
            "failed": failed + error,
            "duration": duration,
            "full_log": full_text,
        }
