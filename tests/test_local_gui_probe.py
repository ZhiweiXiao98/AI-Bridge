"""Probe protocol/unit coverage; these tests do not prove native Mac/Windows UI."""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


# Also supports running this isolated proposal before it enters the checkout.
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_gui_probe", ROOT / "app/core/local_gui_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(probe.sys, "frozen", True, raising=False)
    monkeypatch.setattr(probe.sys, "platform", "darwin")
    worker = SimpleNamespace(mode="api", api_source=object(), running=True,
                             _shutdown_complete=False, agent_runtime_bridge=SimpleNamespace(is_running=False))
    worker.isRunning = lambda: worker.running
    window = Mock()
    window.visible = True
    window.isVisible.side_effect = lambda: window.visible
    window.isEnabled.return_value = True
    window.width.return_value = 1000
    window.height.return_value = 700
    window.windowHandle.return_value.isExposed.return_value = True
    window.windowHandle.return_value.winId.return_value = 12345
    window.chat_page = SimpleNamespace(current_mode="api")
    panel = SimpleNamespace(render_mode="webengine", _tabs=[object()], _device_profiles={"desktop": object()},
                            _view=object(), _profile=object(), marker_valid=True, local_file=True, path="")
    tab = SimpleNamespace(view=SimpleNamespace(url=lambda: SimpleNamespace(
        isLocalFile=lambda: panel.local_file, toLocalFile=lambda: panel.path)))
    panel._current_tab = lambda: tab
    panel.run_javascript = Mock(side_effect=lambda script, receive: (receive(panel.marker_valid), True)[1])
    def dispose():
        panel._tabs.clear()
        panel._device_profiles.clear()
        panel._view = panel._profile = None
    panel.dispose = Mock(side_effect=dispose)
    window.embedded_browser_panel = panel
    window.open_doc_html_in_embedded_browser.side_effect = lambda path, title: setattr(panel, "path", path)
    monkeypatch.setattr(probe, "_probe_pdf", lambda home, report: report.update(
        pdf_qimage_decoded=True, pdf_fixture_pixels_verified=True))
    capture = window.grab.return_value
    capture.isNull.return_value = False
    capture.width.return_value = 1000
    capture.height.return_value = 700
    capture.save.return_value = True

    def close():
        window.visible = False
        worker.running = False
        worker._shutdown_complete = True
        panel.dispose()
        return True
    window.close.side_effect = close
    app = Mock()
    app.platformName.return_value = "cocoa"
    return app, window, worker


def run(runtime, home, timeout=0.03):
    return probe.run_native_smoke(*runtime, home, probe.time.monotonic(), timeout=timeout)


def test_success_records_only_safe_fields_and_graceful_close(runtime, tmp_path):
    result = run(runtime, tmp_path)
    assert result["passed"] and result["stage"] == "complete"
    assert result["normal_close"] and result["worker_stopped"] and result["runtime_stopped"]
    assert all(result[field] for field in ("pdf_qimage_decoded", "pdf_fixture_pixels_verified",
               "webengine_local_preview_loaded", "webengine_marker_verified", "webengine_preview_disposed"))
    assert set(result["checks"]) == set(probe.CHECKS)
    serialized = (tmp_path / probe.REPORT_NAME).read_text(encoding="utf-8")
    assert json.loads(serialized) == result
    assert "12345" not in serialized and str(tmp_path) not in serialized
    runtime[1].grab.assert_called_once_with()
    runtime[1].close.assert_called_once_with()
    runtime[1].grab.return_value.save.assert_called_once_with(str(tmp_path / probe.SCREENSHOT_NAME), "PNG")
    runtime[1].open_doc_html_in_embedded_browser.assert_called_once_with(
        str((tmp_path / "native-preview.html").resolve()), "native-preview.html")
    assert (tmp_path / "native-preview.html").read_text(encoding="utf-8") == probe.PREVIEW_HTML
    assert "default-src 'none'" in probe.PREVIEW_HTML
    runtime[1].embedded_browser_panel.run_javascript.assert_called_once()


@pytest.mark.parametrize("system,plugin,frozen", [
    ("darwin", "offscreen", True), ("win32", "offscreen", True),
    ("win32", "cocoa", True), ("darwin", "cocoa", False), ("linux", "xcb", True),
])
def test_never_accepts_offscreen_wrong_platform_or_source(runtime, tmp_path, monkeypatch, system, plugin, frozen):
    monkeypatch.setattr(probe.sys, "platform", system)
    monkeypatch.setattr(probe.sys, "frozen", frozen)
    runtime[0].platformName.return_value = plugin
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["stage"] == "native_platform"
    runtime[1].grab.assert_not_called()


def test_windows_native_plugin_is_accepted(runtime, tmp_path, monkeypatch):
    monkeypatch.setattr(probe.sys, "platform", "win32")
    runtime[0].platformName.return_value = "windows"
    assert run(runtime, tmp_path)["passed"]


def test_not_exposed_is_a_bounded_failure(runtime, tmp_path):
    runtime[1].windowHandle.return_value.isExposed.return_value = False
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["stage"] == "window_ready"
    runtime[1].grab.assert_not_called()


def test_empty_capture_cannot_pass(runtime, tmp_path):
    runtime[1].grab.return_value.isNull.return_value = True
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["stage"] == "window_capture"
    runtime[1].grab.return_value.save.assert_not_called()


def test_failed_screenshot_save_cannot_pass(runtime, tmp_path):
    runtime[1].grab.return_value.save.return_value = False
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["stage"] == "screenshot_save"
    assert result["window_capture_nonempty"] and not result["screenshot_saved"]


def test_startup_slot_errors_before_show_are_preserved(runtime, tmp_path):
    result = probe.run_native_smoke(*runtime, tmp_path, probe.time.monotonic(),
                                    timeout=0.03, failures=[True])
    assert not result["passed"] and result["qt_exception_count"] == 1
    runtime[1].grab.assert_not_called()
    # The boot collector precedes main-window construction, not just the wait loop.
    source = (ROOT / "boot_local.py").read_text(encoding="utf-8")
    assert source.index("sys.excepthook = lambda *_: native_failures.append(True)") < source.index("window = MainWindow(")


def test_ignored_close_must_wait_for_real_worker_cleanup(runtime, tmp_path):
    runtime[1].close.side_effect = lambda: False
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["stage"] == "normal_close"
    assert not result["normal_close"] and not result["worker_stopped"]


def test_qt_slot_exception_is_not_silent_success(runtime, tmp_path):
    old_hook = probe.sys.excepthook
    runtime[0].processEvents.side_effect = lambda: probe.sys.excepthook(RuntimeError, RuntimeError("private"), None)
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["qt_exception_count"] == 1
    assert probe.sys.excepthook is old_hook
    assert "private" not in (tmp_path / probe.REPORT_NAME).read_text(encoding="utf-8")


def test_pdf_decode_failure_cannot_pass(runtime, tmp_path, monkeypatch):
    def fail(home, report):
        raise RuntimeError("private image error")
    monkeypatch.setattr(probe, "_probe_pdf", fail)
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["stage"] == "pdf_decode"
    assert not result["pdf_qimage_decoded"]
    assert "private image error" not in (tmp_path / probe.REPORT_NAME).read_text(encoding="utf-8")
    runtime[1].embedded_browser_panel.dispose.assert_called_once()


@pytest.mark.parametrize("field,value", [("render_mode", "fallback"), ("marker_valid", False), ("local_file", False)])
def test_webengine_requires_real_local_marker_and_cleans_up_failure(runtime, tmp_path, field, value):
    panel = runtime[1].embedded_browser_panel
    setattr(panel, field, value)
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["stage"] == "webengine_preview"
    panel.dispose.assert_called_once()
    assert probe._preview_disposed(panel)


def test_webengine_pending_callback_has_bounded_wait(runtime, tmp_path):
    panel = runtime[1].embedded_browser_panel
    panel.run_javascript.side_effect = None
    panel.run_javascript.return_value = True
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["stage"] == "webengine_preview"
    panel.run_javascript.assert_called_once()  # Do not queue unbounded DOM requests.
    panel.dispose.assert_called_once()


def test_preview_pages_and_profiles_must_be_disposed_before_success(runtime, tmp_path):
    runtime[1].embedded_browser_panel.dispose.side_effect = None
    result = run(runtime, tmp_path)
    assert not result["passed"] and result["stage"] == "webengine_cleanup"
    assert not result["webengine_preview_disposed"]


def test_pdf_fixture_has_valid_xref_and_single_page():
    data = probe._pdf_fixture_bytes()
    xref = int(data.split(b"startxref\n")[1].splitlines()[0])
    assert data[xref:].startswith(b"xref\n0 5\n")
    entries = data[xref:].splitlines()[3:7]
    for index, entry in enumerate(entries, 1):
        assert data[int(entry[:10]):].startswith(f"{index} 0 obj\n".encode("ascii"))
    assert data.count(b"/Type /Page ") == 1 and b"/Count 1" in data


def test_generated_pdf_decodes_with_real_qimage_without_browser(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    report = {}
    probe._probe_pdf(tmp_path, report)
    assert report == {"pdf_qimage_decoded": True, "pdf_fixture_pixels_verified": True}
    assert app is not None


def test_boot_requires_fresh_home_before_loading_qt(tmp_path, monkeypatch):
    boot_spec = importlib.util.spec_from_file_location("probe_boot", ROOT / "boot_local.py")
    boot = importlib.util.module_from_spec(boot_spec)
    boot_spec.loader.exec_module(boot)
    monkeypatch.delenv("AI_BRIDGE_LOCAL_HOME", raising=False)
    with pytest.raises(SystemExit) as error:
        boot.main(["--local-native-smoke-test"])
    assert error.value.code == 2
    (tmp_path / "existing-data").write_text("preserve", encoding="utf-8")
    monkeypatch.setenv("AI_BRIDGE_LOCAL_HOME", str(tmp_path))
    with pytest.raises(SystemExit) as error:
        boot.main(["--local-native-smoke-test"])
    assert error.value.code == 2
    assert (tmp_path / "existing-data").read_text(encoding="utf-8") == "preserve"


def test_actual_offscreen_qt_application_cannot_claim_native(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(probe.sys, "platform", "darwin")
    monkeypatch.setattr(probe.sys, "frozen", True, raising=False)
    window = QWidget()
    result = probe.run_native_smoke(app, window, Mock(), tmp_path, probe.time.monotonic(), timeout=0.03)
    assert app.platformName() == "offscreen"
    assert not result["passed"] and result["stage"] == "native_platform"
    window.deleteLater()
