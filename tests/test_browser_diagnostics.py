"""Browser startup diagnostics retain phases, never profile or webpage data."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from app.core.driver.connection import ConnectionManager
from app.core.driver.local_chrome import BrowserSetupError


def connection(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    monkeypatch.setenv("AI_BRIDGE_LOCAL_HOME", str(tmp_path))
    return ConnectionManager(9527, config={})


def test_diagnostic_has_no_dom_requests_and_initial_state(monkeypatch, tmp_path):
    conn = connection(monkeypatch, tmp_path)
    conn.driver = Mock()
    result = conn.diagnostic_snapshot()
    assert result["connection_stage"] == "not_connected"
    assert result["chrome_stage"] == "not_started"
    assert result["driver_created"] is True
    assert result["chrome_process_created"] is False
    conn.driver.assert_not_called()
    assert conn.driver.mock_calls == []


def test_chrome_exit_diagnostic_retains_only_code_and_phase(monkeypatch, tmp_path):
    conn = connection(monkeypatch, tmp_path)
    conn.local_session.process = SimpleNamespace(poll=lambda: -1073741515)
    conn.local_session.diagnostic_stage = "chrome_exited_before_debugger"
    conn.local_session.start = Mock(side_effect=BrowserSetupError("secret-token https://private.example/profile"))
    assert not conn.start_browser()[0]
    result = conn.diagnostic_snapshot()
    assert result["connection_stage"] == "starting_private_chrome"
    assert result["chrome_stage"] == "chrome_exited_before_debugger"
    assert result["chrome_exit_code"] == -1073741515
    assert result["error_type"] == "BrowserSetupError"
    assert result["chrome_process_running"] is False
    encoded = json.dumps(result)
    assert "secret-token" not in encoded and "private.example" not in encoded and str(tmp_path) not in encoded


def test_driver_resolution_diagnostic_keeps_versions_not_paths(monkeypatch, tmp_path):
    conn = connection(monkeypatch, tmp_path)
    session = conn.local_session
    session.profile.mkdir()
    (session.profile / "DevToolsActivePort").write_text("fixture-only")
    session.version = "154.0.8037.57"
    session.driver_version = "153.0.8000.0"
    session.diagnostic_stage = "driver_version_mismatch"
    session.resolve_driver = Mock(side_effect=BrowserSetupError("sensitive path must not enter diagnostic"))
    assert conn._build_service()[0] is False
    result = conn.diagnostic_snapshot()
    assert result["connection_stage"] == "preparing_driver"
    assert result["chrome_stage"] == "driver_version_mismatch"
    assert result["chrome_version"] == "154.0.8037.57"
    assert result["chromedriver_version"] == "153.0.8000.0"
    assert result["devtools_file_exists"] is True
    assert "sensitive" not in json.dumps(result)


def test_unknown_stage_or_malformed_versions_are_not_exported(monkeypatch, tmp_path):
    conn = connection(monkeypatch, tmp_path)
    conn.diagnostic_stage = "https://private.invalid/secret"
    conn.local_session.diagnostic_stage = "raw-private-message"
    conn.local_session.version = "private-file-path"
    conn.local_session.driver_version = "token=secret"
    conn.diagnostic_error_type = "token=secret"
    result = conn.diagnostic_snapshot()
    assert result["connection_stage"] == result["chrome_stage"] == "unknown"
    assert result["chrome_version"] == result["chromedriver_version"] == result["error_type"] == ""
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)
