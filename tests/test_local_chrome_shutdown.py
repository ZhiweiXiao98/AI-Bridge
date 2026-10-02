"""Owned Chrome graceful close is ordered, bounded and never targets remote Chrome."""
import subprocess
import threading
import time
from unittest.mock import Mock

import pytest


@pytest.fixture
def connection(monkeypatch, tmp_path):
    from app.core.driver.connection import ConnectionManager
    monkeypatch.setenv("AI_BRIDGE_LOCAL_MODE", "1")
    monkeypatch.setenv("AI_BRIDGE_LOCAL_HOME", str(tmp_path))
    manager = ConnectionManager(9527, config={})
    events = []
    exited = threading.Event()
    process = Mock()
    process.poll.side_effect = lambda: 0 if exited.is_set() else None
    def wait(timeout):
        if not exited.wait(timeout):
            raise subprocess.TimeoutExpired("owned-browser", timeout)
        return 0
    def terminate():
        events.append("terminate")
        exited.set()
    process.wait.side_effect = wait
    process.terminate.side_effect = terminate
    manager.local_session.process = process
    manager.local_session._owned_processes = [process]
    manager.local_session._capture_descendants = Mock()
    manager.driver = Mock()
    manager._service = Mock()
    manager._service.stop.side_effect = lambda: events.append("service.stop")
    return manager, process, exited, events


def test_owned_browser_closes_before_service_without_terminate_and_only_once(connection):
    manager, process, exited, events = connection
    driver, service = manager.driver, manager._service
    def close(command, params):
        assert (command, params) == ("Browser.close", {})
        events.append("Browser.close")
        exited.set()
    driver.execute_cdp_cmd.side_effect = close
    assert manager.shutdown(1)
    assert manager.shutdown(0)
    assert events == ["Browser.close", "service.stop"]
    driver.execute_cdp_cmd.assert_called_once_with("Browser.close", {})
    driver.quit.assert_not_called()
    process.terminate.assert_not_called()
    service.stop.assert_called_once()


def test_hung_close_respects_each_deadline_and_does_not_restart_grace(connection):
    manager, process, _, events = connection
    entered, release = threading.Event(), threading.Event()
    driver = manager.driver
    def close(*_):
        events.append("Browser.close")
        entered.set()
        release.wait(3)
    driver.execute_cdp_cmd.side_effect = close
    try:
        before = time.monotonic()
        assert not manager.shutdown(0)
        assert entered.wait(1)
        grace_deadline = manager._browser_close_deadline
        assert not manager.shutdown(0.02)
        assert time.monotonic() - before < 0.3
        assert manager._browser_close_deadline == grace_deadline
        manager._service.stop.assert_not_called()
        process.terminate.assert_not_called()
        # Deterministically expire the one grace interval without sleeping.
        manager._browser_close_deadline = time.monotonic() - 1
        before = time.monotonic()
        assert manager.shutdown(0.02)
        assert time.monotonic() - before < 0.3
        assert manager._browser_close_worker.is_alive()
        process.terminate.assert_called_once()
        assert events == ["Browser.close", "service.stop", "terminate"]
        driver.execute_cdp_cmd.assert_called_once()
    finally:
        release.set()
        assert manager.shutdown(1)
        manager._browser_close_worker.join(1)
        assert not manager._browser_close_worker.is_alive()


def test_failed_close_falls_back_to_only_owned_process(connection):
    manager, process, _, events = connection
    manager._BROWSER_CLOSE_GRACE_SECONDS = 0
    driver = manager.driver
    driver.execute_cdp_cmd.side_effect = RuntimeError("driver disconnected")
    assert manager.shutdown(1)
    driver.execute_cdp_cmd.assert_called_once_with("Browser.close", {})
    process.terminate.assert_called_once()
    assert events == ["service.stop", "terminate"]


def test_remote_service_cleanup_never_closes_shared_browser(monkeypatch):
    from app.core.driver.connection import ConnectionManager
    monkeypatch.delenv("AI_BRIDGE_LOCAL_MODE", raising=False)
    manager = ConnectionManager(9527, config={})
    driver, service = Mock(), Mock()
    manager.driver, manager._service = driver, service
    assert manager.shutdown(1)
    service.stop.assert_called_once()
    driver.execute_cdp_cmd.assert_not_called()
    driver.quit.assert_not_called()
    driver.close.assert_not_called()


def test_owned_browser_without_live_driver_uses_bounded_fallback(connection):
    manager, process, _, events = connection
    manager.driver = None
    assert manager.shutdown(1)
    assert manager._browser_close_worker is None
    process.terminate.assert_called_once()
    assert events == ["service.stop", "terminate"]
