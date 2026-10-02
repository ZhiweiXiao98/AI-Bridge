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
    "QImage解码本地单页PDF", "内置WebEngine加载本地HTML", "内置WebEngine页面与配置清理",
]
PREVIEW_MARKER = "本地静态预览标记"
PREVIEW_HTML = ("<!doctype html><html><head><meta charset='utf-8'>"
                "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'\">"
                "<title>本地预览自检</title></head><body>"
                f"<p id='native-preview-marker'>{PREVIEW_MARKER}</p></body></html>")
PREVIEW_SCRIPT = """(() => {
    const marker = document.getElementById('native-preview-marker');
    return document.readyState === 'complete' && location.protocol === 'file:' &&
        marker !== null && marker.textContent === '本地静态预览标记' &&
        marker.getBoundingClientRect().width > 0 && marker.getBoundingClientRect().height > 0;
})()"""


def initial_report():
    return {
        "schema_version": 1, "mode": "native-gui", "fixture": "isolated-empty-home",
        "frozen": bool(getattr(sys, "frozen", False)), "qt": "", "platform_plugin": "",
        "window_visible": False, "window_exposed": False, "window_enabled": False,
        "window_nonzero_size": False, "native_window_id_valid": False,
        "api_mode_ready": False, "window_capture_nonempty": False,
        "screenshot_saved": False, "startup_ready_ms": 0, "normal_close": False,
        "window_closed": False, "worker_stopped": False, "runtime_stopped": False,
        "pdf_qimage_decoded": False, "pdf_fixture_pixels_verified": False,
        "webengine_local_preview_loaded": False, "webengine_marker_verified": False,
        "webengine_preview_disposed": False,
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


def _pdf_fixture_bytes():
    """A single 72-point page filled with RGB (32, 128, 224), without fonts/files."""
    stream = b"0.12549 0.50196 0.87843 rg 0 0 72 72 re f\n"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] /Resources << >> /Contents 4 0 R >>",
               b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream"]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, item in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode("ascii") + item + b"\nendobj\n")
    xref = len(data)
    data.extend(b"xref\n0 5\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(data)


def _probe_pdf(home, report):
    from PySide6.QtGui import QImage

    path = home / "native-preview.pdf"
    path.write_bytes(_pdf_fixture_bytes())
    image = QImage()
    report["pdf_qimage_decoded"] = bool(image.load(str(path)) and not image.isNull()
                                        and image.width() > 0 and image.height() > 0)
    if not report["pdf_qimage_decoded"]:
        raise RuntimeError("QImage PDF decoder unavailable")
    pixel = image.pixelColor(image.width() // 2, image.height() // 2)
    report["pdf_fixture_pixels_verified"] = all(abs(actual - expected) <= 3 for actual, expected in
                                               zip((pixel.red(), pixel.green(), pixel.blue()), (32, 128, 224)))
    if not report["pdf_fixture_pixels_verified"]:
        raise RuntimeError("Decoded PDF fixture pixels differ")


def _probe_webengine(app, window, home, report, timeout, failures):
    panel = window.embedded_browser_panel
    if panel.render_mode != "webengine":
        raise RuntimeError("WebEngine preview cannot use a fallback renderer")
    path = (home / "native-preview.html").resolve()
    path.write_text(PREVIEW_HTML, encoding="utf-8")
    window.open_doc_html_in_embedded_browser(str(path), "native-preview.html")
    tab = panel._current_tab()
    if tab is None or tab.view is None:
        raise RuntimeError("Existing document preview did not create a WebEngine page")
    state = {"inflight": False, "verified": False}

    def receive(value):
        state.update(inflight=False, verified=value is True)

    def loaded():
        url = tab.view.url()
        report["webengine_local_preview_loaded"] = bool(url.isLocalFile() and Path(url.toLocalFile()).resolve() == path)
        if not state["inflight"] and not state["verified"]:
            state["inflight"] = True
            if not panel.run_javascript(PREVIEW_SCRIPT, receive):
                raise RuntimeError("WebEngine DOM callback unavailable")
        report["webengine_marker_verified"] = state["verified"]
        return report["webengine_local_preview_loaded"] and report["webengine_marker_verified"]

    _wait(app, loaded, timeout, failures)


def _preview_disposed(panel):
    # Plain Python ownership fields only: Qt pages/profiles may already be deleted.
    return not panel._tabs and not panel._device_profiles and panel._view is None and panel._profile is None


def run_native_smoke(app, window, worker, home: Path, started_at: float, timeout=10.0, failures=None):
    """Require native exposure and a real widget grab, then use normal closeEvent.

    The outer runner owns the 60-second cold-start/process-exit deadline and
    descendant cleanup. Preview content is a fixed local fixture; no desktop
    capture, provider request or external navigation is performed here.
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
        report["stage"] = "pdf_decode"
        _probe_pdf(home, report)
        report["stage"] = "webengine_preview"
        _probe_webengine(app, window, home, report, timeout, failures)
        report["stage"] = "normal_close"
        window.close()  # May initially be ignored while the existing lifecycle unwinds.

        def stopped():
            report["window_closed"] = not window.isVisible()
            report["worker_stopped"] = not worker.isRunning()
            report["runtime_stopped"] = not worker.agent_runtime_bridge.is_running
            report["normal_close"] = bool(report["window_closed"] and worker._shutdown_complete)
            return all(report[key] for key in ("normal_close", "worker_stopped", "runtime_stopped"))

        _wait(app, stopped, timeout, failures)
        report["stage"] = "webengine_cleanup"
        report["webengine_preview_disposed"] = _preview_disposed(window.embedded_browser_panel)
        if not report["webengine_preview_disposed"]:
            raise RuntimeError("WebEngine preview pages or profiles remain owned")
        report.update(passed=True, stage="complete", checks=list(CHECKS))
    except Exception:
        # Only allowlisted booleans/stages enter the report, never raw exceptions,
        # paths, handles, credentials or a screenshot's contents.
        pass
    finally:
        panel = getattr(window, "embedded_browser_panel", None)
        if panel is not None and not _preview_disposed(panel):
            try:
                panel.dispose()
            except Exception:
                report["passed"] = False
        report["qt_exception_count"] = len(failures)
        sys.excepthook = old_hook
        write_report(home, report)
    return report
