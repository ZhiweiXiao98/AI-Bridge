"""Explicit frozen native-window acceptance probe, using only an empty test HOME."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time


REPORT_NAME = "local-native-smoke.json"
SCREENSHOT_NAME = "local-native-smoke.png"
CHECKS = [
    "隔离空数据目录", "原生Qt平台插件", "真实主窗口显示与曝光",
    "主窗口非空渲染捕获", "主窗口正常关闭", "本地Worker与运行时停止",
]


def initial_report():
    return {
        "schema_version": 1, "mode": "native-gui", "fixture": "isolated-empty-home",
        "frozen": bool(getattr(sys, "frozen", False)), "qt": "", "platform_plugin": "",
        "window_visible": False, "window_exposed": False, "window_enabled": False,
        "window_nonzero_size": False, "native_window_id_valid": False,
        "api_mode_ready": False, "window_capture_nonempty": False,
        "screenshot_saved": False, "startup_ready_ms": 0, "normal_close": False,
        "window_closed": False, "worker_stopped": False, "runtime_stopped": False,
        "qt_exception_count": 0, "passed": False, "stage": "qt_startup", "checks": [],
    }


def write_report(home: Path, report):
    (home / REPORT_NAME).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _window_state(window, worker):
    handle = window.windowHandle()
    return {
        "window_visible": bool(window.isVisible()),
        "window_exposed": bool(handle is not None and handle.isExposed()),
        "window_enabled": bool(window.isEnabled()),
        "window_nonzero_size": window.width() > 0 and window.height() > 0,
        "native_window_id_valid": bool(handle is not None and int(handle.winId())),
        "api_mode_ready": bool(worker.isRunning() and worker.mode == "api"
                               and worker.api_source is not None
                               and window.chat_page.current_mode == "api"),
    }


def _wait(app, predicate, timeout, failures):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if failures:
            raise RuntimeError("Qt callback failed")
        if predicate():
            return
        time.sleep(0.02)
    raise TimeoutError("Native GUI probe timed out")


def run_native_smoke(app, window, worker, home: Path, started_at: float, timeout=10.0, failures=None):
    """Require native exposure and a real widget grab, then use normal closeEvent.

    The outer runner owns the 60-second cold-start/process-exit deadline and
    descendant cleanup. No screen/desktop capture, provider request or browser
    navigation is performed here. This is startup evidence, not visual QA.
    """
    from PySide6.QtCore import qVersion

    report = initial_report()
    report.update(qt=qVersion(), platform_plugin=app.platformName(), stage="native_platform")
    failures = [] if failures is None else failures
    old_hook = sys.excepthook
    sys.excepthook = lambda *_: failures.append(True)
    try:
        expected = {"darwin": "cocoa", "win32": "windows"}.get(sys.platform)
        if not expected or not report["frozen"] or report["platform_plugin"] != expected:
            raise RuntimeError("Frozen native Qt platform required")
        report["stage"] = "window_ready"

        def ready():
            state = _window_state(window, worker)
            report.update(state)
            return all(state.values())

        _wait(app, ready, timeout, failures)
        report["startup_ready_ms"] = max(0, round((time.monotonic() - started_at) * 1000))
        report["stage"] = "window_capture"
        capture = window.grab()  # The fixture app only; never QScreen.grabWindow(0).
        report["window_capture_nonempty"] = bool(not capture.isNull() and capture.width() > 0 and capture.height() > 0)
        if not report["window_capture_nonempty"]:
            raise RuntimeError("Empty native window capture")
        report["stage"] = "screenshot_save"
        report["screenshot_saved"] = bool(capture.save(str(home / SCREENSHOT_NAME), "PNG"))
        if not report["screenshot_saved"]:
            raise RuntimeError("Native fixture screenshot was not saved")
        report["stage"] = "normal_close"
        window.close()  # May initially be ignored while the existing lifecycle unwinds.

        def stopped():
            report["window_closed"] = not window.isVisible()
            report["worker_stopped"] = not worker.isRunning()
            report["runtime_stopped"] = not worker.agent_runtime_bridge.is_running
            report["normal_close"] = bool(report["window_closed"] and worker._shutdown_complete)
            return all(report[key] for key in ("normal_close", "worker_stopped", "runtime_stopped"))

        _wait(app, stopped, timeout, failures)
        report.update(passed=True, stage="complete", checks=list(CHECKS))
    except Exception:
        # Only allowlisted booleans/stages enter the report, never raw exceptions,
        # paths, handles, credentials or a screenshot's contents.
        pass
    finally:
        report["qt_exception_count"] = len(failures)
        sys.excepthook = old_hook
        write_report(home, report)
    return report
