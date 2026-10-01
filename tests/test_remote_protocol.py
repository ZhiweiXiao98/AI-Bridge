import pytest
from app.core.remote_protocol import REMOTE_MESSAGE_ROUTES, SERVER_SIGNAL_ROUTES

def test_remote_protocol_smoke_import():
    m = pytest.importorskip('app.core.remote_worker', reason='PyQt/system libs unavailable in container', exc_type=ImportError)
    assert hasattr(m, '__file__')


def test_remote_worker_api_probe_methods_are_explicit():
    m = pytest.importorskip('app.core.remote_worker', reason='PyQt/system libs unavailable in container', exc_type=ImportError)
    assert "api_probe_models" in m.RemoteWorker.__dict__
    assert "api_probe_tool_support" in m.RemoteWorker.__dict__
    assert "run_driver_action_sync" in m.RemoteWorker.__dict__


def test_server_routes_have_remote_consumers():
    missing = [
        route.message_type
        for route in SERVER_SIGNAL_ROUTES
        if route.message_type not in REMOTE_MESSAGE_ROUTES
    ]
    assert missing == []


def test_remote_protocol_covers_high_churn_api_signals():
    server_routes = {route.signal_name: route for route in SERVER_SIGNAL_ROUTES}

    assert server_routes["context_status_signal"].message_type == "context_status"
    assert server_routes["context_status_signal"].delivery == "broadcast"
    assert server_routes["api_messages_deleted_signal"].delivery == "targeted"
    assert server_routes["api_manual_compact_signal"].delivery == "targeted"
    assert server_routes["mode_changed_signal"].message_type == "mode_changed"

    assert REMOTE_MESSAGE_ROUTES["context_status"].signal_name == "context_status_signal"
    assert REMOTE_MESSAGE_ROUTES["api_messages_deleted"].signal_name == "api_messages_deleted_signal"
    assert REMOTE_MESSAGE_ROUTES["api_manual_compact"].signal_name == "api_manual_compact_signal"
    assert REMOTE_MESSAGE_ROUTES["subagent_suggestion"].signal_name == "subagent_suggestion_signal"
    assert REMOTE_MESSAGE_ROUTES["daemon_suggestion"].signal_name == "daemon_suggestion_signal"


def test_remote_protocol_argument_adapters():
    assert REMOTE_MESSAGE_ROUTES["context_health"].args_builder({"total": 3, "gap": 1}) == (3, 1)
    assert REMOTE_MESSAGE_ROUTES["state_sync"].args_builder({"max_idx": 5, "snap_idx": 2}) == (5, 2)
    assert REMOTE_MESSAGE_ROUTES["batch_complete"].args_builder({}) == ()
    assert REMOTE_MESSAGE_ROUTES["pending_consumed"].args_builder({}) == ()
