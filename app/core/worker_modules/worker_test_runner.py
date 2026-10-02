# filename: app/core/worker_modules/worker_test_runner.py
from __future__ import annotations

import re
import os
import subprocess
import sys
import threading
import time

from app.core.logging import get_logger
from app.core.project_context import ProjectContext
from app.core.python_runtime import resolve_project_python, python_subprocess_environment

logger = get_logger("app.core.worker.test_runner", side="worker")


class WorkerTestRunnerBridge:
    """Run project pytest in the background and project results to the UI."""

    def __init__(self, worker):
        self.worker = worker
        self._local_desktop = os.environ.get("AI_BRIDGE_LOCAL_MODE") == "1"
        self._lock = threading.Lock()
        self._closed = False
        self._processes = set()
        self._cleanup_threads = {}

    def run_remote_tests(self, client_id="Host", **kwargs):
        if self._closed:
            return
        self.worker.safe_emit_status("🧪 [测试] 正在后台运行 pytest...")
        if self._local_desktop:
            return self.worker.executor.submit(self.run_tests_bg, client_id)
        return self.run_tests_bg(client_id)

    def _request_stop(self, process):
        with self._lock:
            if process in self._cleanup_threads:
                return self._cleanup_threads[process]
            def stop_owned_tree():
                # Only inspect descendants of the Popen child owned by this
                # bridge. Never kill processes by executable name or port.
                import psutil
                try:
                    if process.poll() is not None:
                        return
                    owned = psutil.Process(process.pid)
                    children = owned.children(recursive=True)
                    for child in children:
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    process.terminate()
                    _, remaining = psutil.wait_procs(children, timeout=0.5)
                    for child in remaining:
                        try:
                            child.kill()
                        except psutil.NoSuchProcess:
                            pass
                    process.wait(timeout=1)
                except (OSError, psutil.Error, subprocess.TimeoutExpired):
                    if process.poll() is None:
                        process.kill()
            thread = threading.Thread(target=stop_owned_tree, daemon=True, name="local-pytest-cleanup")
            self._cleanup_threads[process] = thread
            thread.start()
            return thread

    def shutdown(self, timeout=3.0):
        if not self._local_desktop:
            return True
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            self._closed = True
            processes = list(self._processes)
        for process in processes:
            self._request_stop(process)
        with self._lock:
            threads = list(self._cleanup_threads.values())
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
        return (not any(thread.is_alive() for thread in threads)
                and not any(process.poll() is None for process in processes))

    def run_tests_bg(self, client_id):
        worker = self.worker
        cwd = ProjectContext.get().get_project_root()
        process = watchdog = None
        try:
            if self._closed:
                return
            python = resolve_project_python(
                cwd, worker.config.get("sandbox_local_python", ""), purpose="运行 pytest"
            )
            cmd = [python, "-m", "pytest", "tests/", "-v"]
            with self._lock:
                if self._closed:
                    return
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    cwd=cwd,
                    env=python_subprocess_environment(),
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if self._local_desktop:
                    self._processes.add(process)
            if self._local_desktop:
                timeout = max(1.0, float(worker.config.get("test_timeout_seconds", 600)))
                watchdog = threading.Timer(timeout, self._request_stop, args=(process,))
                watchdog.daemon = True
                watchdog.start()

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
            if self._local_desktop and process.returncode:
                result_payload["failed"] = max(1, result_payload["failed"])
                result_payload["full_log"] += "\n测试未正常完成，已取消、超时或进程异常退出。"
            worker.test_result_signal.emit(result_payload)
            label = "⚠️ [测试已结束]" if self._local_desktop and result_payload["failed"] else "✅ [测试完成]"
            worker.safe_emit_status(
                f"{label} Pass: {result_payload['passed']}, Fail: {result_payload['failed']}"
            )

        except Exception as exc:
            err_msg = f"测试启动失败: {exc}"
            logger.error(err_msg)
            worker.safe_emit_status(err_msg)
            worker.test_result_signal.emit(
                {
                    "target_client_id": client_id,
                    "passed": 0,
                    "failed": 1,
                    "duration": "0",
                    "full_log": err_msg,
                }
            )
        finally:
            if watchdog:
                watchdog.cancel()
            if process is not None and self._local_desktop:
                if process.poll() is None:
                    self._request_stop(process)
                else:
                    if process.stdout:
                        process.stdout.close()
                    with self._lock:
                        self._processes.discard(process)

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
